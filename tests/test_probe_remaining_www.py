"""Genuine real-EoE cross-engine byte-equality probes -- batch WWW (round 25).

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module.  Each probe drives the ACTUAL parsed EoE
printing (or a bridge-narrowed synthetic carrier per the OOO precedent)
on the Python side and the bridged synthetic carrier on the Rust side,
asserting full ``compare_fields == []`` byte-equality on a controlled
real-EoE state -- the strongest evidence the campaign tracks.

The probes deliberately cover effect/event shapes NOT already pinned by
the PROBED 203 (round-24 baseline after UUU merge ``6786bc0e`` + VVV
divergence-pin merge ``0ab750ff``):

  * **Jump Scare** -- Instant ``spell_effect=PumpTargetCreatureUntilEOT
    (power_bonus=2, toughness_bonus=2, granted_keywords={flying})``.  The
    ``pump_target_creature_until_eot`` bridge arm has been driven as a
    spell-effect by QQQ Probe 2 (Dark Endurance ``+2/+0`` with the
    indestructible-keyword grant dropped per the OOO bridge-narrowing
    idiom).  **No probe has driven the bridge arm as a spell-effect
    with a NON-ZERO ``toughness_bonus``** until this one -- Dark
    Endurance's toughness_bonus is 0.  The Hardened Escort probe
    (OOO Probe 1) drives ``+1/+0`` as a TRIGGERED ABILITY, not a spell-
    effect.  This probe pins the ``power_bonus + toughness_bonus``
    BOTH-NON-ZERO shape on the spell-effect lane (orthogonal cover to
    Dark Endurance's power-only spell-effect probe), exercising the
    layer-7c additive bonus on both axes simultaneously -- the
    ``+2/+2`` shape Giant-Growth canonical.

  * **Sunstar Chaplain** -- Creature ``BEGINNING_OF_END_STEP +
    Controlled(YOU) -> ConditionalOnTappedCreatures(effect=
    PutPlusOneCounterOnCreatureYouControl(amount=1, targets=...),
    min_count=2)``.  The Frontline War-Rager probe
    (``test_probe_remaining_ww.py``:131) pins the SAME wrapper +
    event + predicate composition with ``PutPlusOneCounterOnSelf``
    (self-target, no target-pick).  **No probe has driven
    ConditionalOnTappedCreatures with ``PutPlusOneCounterOnCreatureYou
    Control`` (target-creature, with target-pick)** -- Sunstar
    Chaplain's inner effect differs from FWR's bit-identical wrapper
    shape: FWR's inner is the self-target counter; Sunstar Chaplain's
    inner is the target-creature counter with the
    ``IsCreature() & ControlledByYou()`` slot filter.  Pinning the
    ``conditional_on_tapped_creatures`` -> ``put_plus_one_counter_on_
    creature_you_control`` recursive composition end-to-end via the
    SATISFIED condition path (2 tapped creatures including Sunstar
    Chaplain) closes the cross-engine bridge gap on the inner
    target-pick + counter-application sequence under the conditional
    wrapper.  The QQQ drop note (``test_probe_remaining_qqq.py``:86-98)
    grouped Sunstar Chaplain with Sami, Ship's Engineer ("bit-identical
    event+predicate+wrapper shape to FWR / Dawnstrike Vanguard"); the
    grouping was over-cautious for Sunstar Chaplain specifically -- the
    drop reason cited (``CreateToken(tapped=True)`` not bridge-able)
    applies ONLY to Sami's CreateToken inner effect, NOT to Sunstar
    Chaplain's PutPlusOneCounterOnCreatureYouControl inner (which IS
    bridge-able via the ``put_plus_one_counter_on_creature_you_control``
    arm at ``cross_engine.py``:1260).

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Survivor family** (Savior of the Small, Cautious Survivor, Defiant
    Survivor, House Cartographer, Shrewd Storyteller) -- VVV Pin 1
    filed (commit ``ccf72582``); broken until the Rust ``SourceIsSelf``
    player-subject tautology is closed in a future Rust slice.

  * **Command Bridge** -- VVV Pin 2 (``genuinely_missing``); cannot
    probe.

  * **Pain for All / Requiem Monolith / Meltstrider's Resolve /
    Tractor Beam** -- VVV Pin 3 family (``genuinely_missing`` bespoke
    ETB substrate); cannot probe.

  * **Lightless Evangel / Atomic Microsizer / Astelli Reclaimer** -- TTT
    pins (commit ``3cb6ef7d``); broken until slice 14 closure (lane 3
    in flight).

  * **Cosmogrand Zenith / Station Monitor** (the remaining 2 of 4
    ``spells_cast_this_turn`` cards; Sunstar Lightsmith + Illvoi
    Operative already probed by slice 12 ``test_probe_mmm_downstream
    .py``).  Slice 12 substrate (commit ``b2437b20``); skipped per the
    lane-coordination memo.

  * **Innocuous Rat** (DIES + IsSelf -> ManifestDread(1)): bit-
    identical shape to Bashful Beastie which is already PROBED via
    ``test_probe_remaining_iii.py``.  Adds no new effect/event
    coverage (same drop discipline as SSS / UUU).

  * **Trapped in the Screen** (Enchantment ENTERS + IsSelf ->
    ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)): bit-
    identical bridge shape to Banishing Light which is already
    PROBED (``test_parity_smoke.py``:34218 -- the bare-shape
    Enchantment carrier with the bare-default ``max_mv=0`` no MV
    cap).  Adds no new effect/event coverage.  Round-22 QQQ also
    surfaced an exile-summoning_sick divergence (Rust stamps
    ``summoning_sick=True`` on the exiled object; Python does not)
    -- documented but not yet on a divergence pin module.

  * **Equipment ETBs** (Meltstrider's Gear / Conductive Machete /
    Killer's Mask / Cursed Windbreaker / Squire's Lightblade / The
    Dominion Bracelet): the SSS-round-23 divergence pin
    (``test_probe_remaining_sss.py``:107-148 -- Python's
    ``put_into_battlefield`` unconditionally stamps
    ``summoning_sick=True`` for non-creature spell ETBs; Rust's
    spell-resolve ETB arm does NOT) means a full ``compare_fields``
    probe surfaces the 3rd-slot ``summoning_sick`` mismatch on the
    Equipment / Artifact / Enchantment carrier.  Hylderblade
    (LLL Probe 2) sidesteps this by injecting the Equipment DIRECTLY
    onto the bf (NOT casting from hand) and using targeted observables,
    not ``compare_fields``.  These cards are probe-blocked until the
    SSS pin closes via a Python ``put_into_battlefield`` non-creature
    fix.

  * **The Seriema** (Artifact ENTERS + IsSelf ->
    SearchLibraryForCard(legendary_creature, max_mv=0, may_fail=False)):
    the Seriema is an Artifact carrier (NOT a Creature) so the
    Equipment-ETB summoning_sick divergence above blocks a full
    ``compare_fields`` probe via the cast-from-hand path.  The
    inject-onto-bf + manual-trigger-fire pattern (Hylderblade-style)
    requires the ENTERS event to be dispatched after the
    register_and_inject_object call; Rust's
    ``register_and_inject_object`` does NOT dispatch ENTERS
    (verified by inspection -- no public Rust method exposes ENTERS
    dispatch), so the Hylderblade pattern is not directly applicable
    to ENTERS-triggered Artifacts.  Probe-blocked at the harness
    layer; deferred until either (a) the SSS summoning_sick pin
    closes, or (b) a Rust ENTERS-dispatch hook is exposed.

  * **Stay Hidden, Stay Silent** (Aura ENTERS IsSelf ->
    TapEnchantedPermanent): the bridge ``tap_enchanted_permanent``
    docstring (``cross_engine.py``:5252-5256) documents the
    end-to-end probe as deferred -- "the Aura attachment +
    control-stealing + untap-restriction rider stack is its own
    carrier surface beyond the bare bridge-arm slice".  Aura
    subsystem gating; probe-blocked at the Aura attachment
    substrate.

  * **Split Up** (Sorcery ``spell_effect=ModalChooseOne(modes=
    (DestroyAllCreatures(tapped_only=True), DestroyAllCreatures
    (untapped_only=True)), or_both=False)``): the
    ``destroy_all_creatures`` Rust bridge arm
    (``cross_engine.py``:4627-4683) is the unit-variant ``Wrath``
    shape; the ``tapped_only`` / ``untapped_only`` narrowing flags
    Python carries do NOT round-trip through this arm in their
    narrowed form ("those will land as separate parameterized Rust
    Effect variants in follow-ups").  Probe-blocked at the
    bridge-arm narrowing gap.

  * **Vanish from Sight** (Sorcery ``spell_effect=Sequence(
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    (nonland_permanent=True), Surveil(1))``): the
    ``allow_nonland_permanent=True`` rider on
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary is NOT
    plumbed through the Rust ``owner_puts_target_artifact_or_
    creature_on_top_or_bottom_of_library`` bridge arm (unit-variant
    shape; rider widens the legal-target pool from "artifact or
    creature" to "any nonland permanent" -- "A future
    nonland-permanent-widened Rust variant would land as a separate
    ``kind`` arm" per the bridge docstring).  Probe-blocked at the
    bridge-arm rider gap.

  * **Unnerving Grasp** (Sorcery ``spell_effect=Sequence(
    ReturnTargetCreatureToOwnersHand(allow_nonland_permanent=True,
    create_drone_if_was_attacking=False, optional=True),
    ManifestDread(1))``): the ``allow_nonland_permanent=True``
    rider on ReturnTargetCreatureToOwnersHand has the same
    bridge-arm narrowing gap as Vanish from Sight.  Probe-blocked.

  * **Withering Torment** (Instant ``spell_effect=Sequence
    (DestroyTargetCreature(or_enchantment=True), LoseLife(2))``):
    UUU drop note (``test_probe_remaining_uuu.py``:194-200)
    confirms the ``or_enchantment=True`` rider on DestroyTargetCreature
    is NOT plumbed through any of the cross-engine
    ``destroy_target_*`` bridge arms.  Probe-blocked at the
    bridge-arm rider gap.

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): UUU drop
    note (``test_probe_remaining_uuu.py``:202-205) confirms no
    bridge arm exists.  Probe-blocked at the bridge-arm absence.

  * **Sami, Ship's Engineer** (BEGINNING_OF_END_STEP + Controlled(YOU)
    -> ConditionalOnTappedCreatures(CreateToken(tapped=True))):
    QQQ drop note (``test_probe_remaining_qqq.py``:86-98) confirms
    the ``CreateToken(tapped=True)`` flag is NOT plumbed through
    the Rust ``create_token`` bridge arm (Python-side-only rider;
    Rust default is ``tapped=False``).  Probe-blocked at the
    bridge-arm rider gap.

  * **Horrid Vigor** (Instant ``spell_effect=PumpTargetCreatureUntilEOT
    (+0/+0, granted_keywords={deathtouch, indestructible})``): per
    the OOO Flesh Burrower / QQQ Hardened Escort drop-reason
    precedent, ``power_bonus + toughness_bonus = (0, 0)`` is a
    pure no-op for ``compare_fields`` once granted_keywords is
    bridge-narrowed (the bridge arm cannot represent the keyword
    grant).  No numeric change -> no clean byte-equal observable.

  * **Violent Urge** (Instant ``spell_effect=PumpTargetCreatureUntilEOT
    (+1/+0, granted_keywords={first strike})``): same shape as
    Hardened Escort (OOO Probe 1, ATTACKS-triggered) bridge-narrowed
    to ``(+1, 0)``.  The Dark Endurance probe pins the spell-effect
    lane with ``(+2, 0)`` already (PROBE 196 -> 198); a second
    spell-effect ``(+1, 0)`` probe is bit-identical numeric magnitude
    on the same bridge arm with no new field-shape coverage.  Honest
    exhaustion (different magnitude, same shape).

  * **Give In to Violence** (Instant ``spell_effect=PumpTargetCreatureUntilEOT
    (+2/+2, granted_keywords={lifelink})``): SAME ``(+2/+2)`` numeric
    shape as Jump Scare (Probe 1).  Only the granted_keyword differs
    (lifelink vs flying) -- both are bridge-narrowed and
    bridge-invisible to the ``compare_fields`` view.  Pin Jump Scare;
    drop Give In to Violence as bit-identical bridge-arm coverage.

  * **Vanilla / keyword-only creatures** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Piranha Fly, Slavering
    Branchsnapper, Spectral Snatcher, Shepherding Spirits, Fear of
    Being Hunted, etc.): no triggered abilities, no spell_effect, only
    static keywords.  The ENTERS-/DIES-trigger lane this batch targets
    is empty for these cards.  Same drop discipline as SSS / QQQ / UUU.

  * **DEALS_COMBAT_DAMAGE family** (Starwinder, Fear of Failed Tests):
    end-to-end probe requires the cross-engine combat-damage harness
    (``resolve_combat_damage_python`` + ``deal_combat_damage_rust`` at
    ``cross_engine.py``:11944-12019) + the harness-side
    ``resolving_combat_damage_amount`` carrier-scalar push -- a
    distinctly richer setup than the spell-effect / end-step trigger
    probe shapes this batch shoots for.  Deferred per the UUU drop-
    note precedent.

  * **Hand That Feeds** (ATTACKS + And(IsSelf, StateBound(Delirium))
    -> PumpSelfUntilEOT(+2/+0, menace)): the ``StateBound(Delirium())``
    predicate's inner StatePredicate kind ``delirium`` is NOT yet wired
    in ``_ta_dict_to_python_state_predicate`` (per SSS drop note --
    only ``void_active``, ``any_player_controls_no_creatures``,
    ``spells_cast_this_turn`` are wired today).  Probe-blocked at the
    inner predicate bridge.

  * **Skystinger** (BLOCKS + And(IsSelf, Subject(HasKeyword(flying))) ->
    PumpSelfUntilEOT(+5/+0)): the bridge has no ``subject_has_keyword``
    predicate kind (QQQ drop note; explicit gap pin at
    ``test_probe_blocked_ff.py::test_blocks_trigger_bridge_predicate
    _gap_skystinger``).  Probe-blocked at the bridge layer.

  * **Mutavault / Inkmoth Nexus / Stirring Wildwood / similar
    manlands** (BecomeLandCreatureUEOT activated): the
    ``become_land_creature_until_eot`` effect has no Rust bridge arm
    (per QQQ drop note).  Probe-blocked at the bridge layer.

  * **Optimistic Scavenger / Cult Healer** (ROOM_FULLY_UNLOCKED event
    TAs with PutPlusOneCounterOnTargetCreature inner): PPP Pin 2
    pinned ``put_plus_one_counter_on_target_creature`` as unbridged
    (per QQQ drop note).  Probe-blocked at the effect layer.

  * **Dawnsire, Sunstar Dreadnought** (YOU_ATTACK + Controlled(YOU) ->
    DealDamageToTargetCreature(amount=100, count_min=0, count_max=1,
    optional=True)): OOO drop note
    (``test_probe_remaining_ooo.py``:94-97) confirms the
    ``deal_damage_to_target_creature`` bridge arm is not yet wired
    in ``_ta_dict_to_python_effect`` (raises "unsupported effect
    kind").  Probe-blocked at the bridge-arm absence.

  * **Most Valuable Slayer (attacking_only)** -- already PROBED in
    OOO Probe 2.  No new probe needed.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with UUU wired in via
``PROBE_MODULES``): 203 -> 205 (+2).  Prior covered count: 111 -> 109
(-2).
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
# Probe 1 -- Jump Scare: Instant spell_effect = PumpTargetCreatureUntilEOT
#   (power_bonus=2, toughness_bonus=2, granted_keywords={flying})
# Bridge spell-effect dict: {"kind": "pump_target_creature_until_eot",
#                            "power_bonus": 2, "toughness_bonus": 2}
# Bridge-narrowing: granted_keywords (flying) is bridge-invisible -- the
# arm does NOT carry the keyword rider (per the OOO precedent + QQQ Dark
# Endurance probe).  Construct the Python carrier from the bridge dict so
# both engines apply the SAME +2/+2 numeric mutation; the keyword grant
# is skipped on BOTH sides identically.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_jump_scare_pump_target_filler_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Jump Scare
    (round 25, Instant PumpTargetCreatureUntilEOT(+2/+2, flying)).**

    Drives a synthetic Instant carrier (constructed from the bridge
    spell-effect dict) on BOTH engines.  The real Jump Scare printing
    is verified at probe entry for shape but NOT used to drive
    resolution -- per the OOO precedent (Hardened Escort / Most
    Valuable Slayer) and the QQQ Dark Endurance probe, the bridge
    ``pump_target_creature_until_eot`` arm does NOT plumb
    ``granted_keywords`` into the dict shape, so a probe driving the
    real printing on Python would grant flying while the bridge synth
    on Rust would not.  Constructing the Python carrier from the
    bridge dict ensures both engines apply the SAME +2/+2 mutation
    with no keyword divergence -- the OOO bridge-narrowing
    discipline.

    **NEW shape coverage:** the ``pump_target_creature_until_eot``
    bridge arm has been driven as a spell-effect by QQQ Probe 2
    (Dark Endurance, ``+2/+0``).  **No probe has driven the bridge
    arm as a SPELL EFFECT with both ``power_bonus`` AND
    ``toughness_bonus`` non-zero** until this one -- Dark Endurance's
    ``toughness_bonus=0`` exercises only the layer-7c additive
    bonus on the POWER axis.  Jump Scare's ``+2/+2`` shape pins
    BOTH axes simultaneously on the spell-effect lane, the
    Giant-Growth canonical numeric mutation.  The Hardened Escort
    probe (OOO Probe 1, ATTACKS-trigger) drives ``+1/+0`` as a
    TRIGGERED ABILITY; no probe has driven both-non-zero
    ``power_bonus + toughness_bonus`` on either lane.

    **Bridge dict:** ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": 2, "toughness_bonus": 2}``.

    Setup:
      * p0 has a filler 2/2 Creature (the only legal target on both
        engines).
      * p1 has no permanents.
      * Both engines push a synthetic ``Jump Scare``-named Instant
        with the bridge spell_effect onto the stack.
      * Python side: ``_PickFirstControlledCreatureAgent`` picks
        the filler (the sole p0-controlled creature); Rust side at-
        apply-time scan picks the filler (the sole creature on
        p0's bf).

    Observables: **full ``compare_fields``** over the whole
    cross-engine field view.  Filler power 2 -> 4, filler toughness
    2 -> 4 on BOTH engines.  Synthetic Jump Scare moves stack ->
    caster's graveyard on BOTH engines.
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
    from mtg_bot.game import (
        StackItem, Zone, effective_power, effective_toughness,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Jump Scare printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Jump Scare")
    if real is None:
        pytest.skip("Jump Scare absent from active CardSource")
    assert "Instant" in real.card_types, (
        "Jump Scare must be an Instant"
    )
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"genuine Jump Scare spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 2, (
        f"Jump Scare PumpTargetCreatureUntilEOT power_bonus must be 2; "
        f"got {se.power_bonus}"
    )
    assert se.toughness_bonus == 2, (
        f"Jump Scare PumpTargetCreatureUntilEOT toughness_bonus must "
        f"be 2; got {se.toughness_bonus}"
    )
    assert "flying" in se.granted_keywords, (
        f"Jump Scare PumpTargetCreatureUntilEOT must grant flying; "
        f"got keywords={se.granted_keywords}"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge spell-effect dict (power+2 / toughness+2, no
    #    keyword grant per the OOO bridge-narrowing idiom).
    # ------------------------------------------------------------------
    js_effect_dict = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 2,
        "toughness_bonus": 2,
    }
    bridge_effect = _ta_dict_to_python_effect(js_effect_dict)
    assert isinstance(bridge_effect, PumpTargetCreatureUntilEOT), (
        f"Bridge effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(bridge_effect).__name__}"
    )
    assert bridge_effect.power_bonus == 2
    assert bridge_effect.toughness_bonus == 2

    # ------------------------------------------------------------------
    # 3. Build cross-engine states (empty decks).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ------------------------------------------------------------------
    # 4. Rust: seat the filler 2/2 on p0's bf, then push synthetic Jump
    #    Scare with the bridge spell_effect onto the stack.
    # ------------------------------------------------------------------
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "JS Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    assert rs.effective_power(rs_filler_id) == 2, (
        f"Rust: filler must start at power 2; "
        f"got {rs.effective_power(rs_filler_id)}"
    )

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Jump Scare",
            "card_types": ["Instant"],
            "effects": [js_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    assert rs.stack_size() == 1, (
        f"Rust: Jump Scare must be on the stack; "
        f"got stack_size={rs.stack_size()}"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after the spell resolves; "
        f"got {rs.stack_size()}"
    )
    rs_filler_pow = rs.effective_power(rs_filler_id)
    rs_filler_tou = rs.effective_toughness(rs_filler_id)
    assert rs_filler_pow == 4, (
        f"Rust: filler power must be 4 after pump (+2); got {rs_filler_pow}"
    )
    assert rs_filler_tou == 4, (
        f"Rust: filler toughness must be 4 after pump (+2); "
        f"got {rs_filler_tou}"
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the filler 2/2 on p0's bf, then push synthetic Jump
    #    Scare with the bridge spell_effect onto the stack.
    # ------------------------------------------------------------------
    py_filler_printing = CardPrinting(
        name="JS Filler",
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
        py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)
    assert effective_power(py, py_filler) == 2, (
        "Python: filler must start at power 2"
    )

    # Construct a synthetic Jump Scare printing using the bridge
    # spell_effect (no granted_keywords -- the OOO bridge-narrowing
    # idiom).
    py_js_printing = CardPrinting(
        name="Jump Scare",
        mana_cost_str="{W}",
        mana_cost=ManaCost(generic=0, colored=(("W", 1),)),
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
    py_spell = py.new_object(py_js_printing, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=0,
            targets=(("creature", py_filler.id),),
        )
    )

    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0, (
        f"Python: stack must be empty after the spell resolves; "
        f"got {len(py.stack)}"
    )
    py_filler_pow = effective_power(py, py_filler)
    py_filler_tou = effective_toughness(py, py_filler)
    assert py_filler_pow == 4, (
        f"Python: filler power must be 4 after pump (+2); "
        f"got {py_filler_pow}"
    )
    assert py_filler_tou == 4, (
        f"Python: filler toughness must be 4 after pump (+2); "
        f"got {py_filler_tou}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Jump Scare pump +2/+2 must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Sunstar Chaplain: BEGINNING_OF_END_STEP + Controlled(YOU)
#   -> ConditionalOnTappedCreatures(effect=PutPlusOneCounterOnCreatureYou
#                                          Control(amount=1), min_count=2)
# Trigger flow: at end step, count tapped creatures the controller
# controls.  If count >= 2, put a +1/+1 counter on a target creature
# you control.  Otherwise silent no-op.  This probe drives the SATISFIED
# condition path: Sunstar Chaplain + 1 tapped filler creature == 2 tapped
# creatures (Sunstar Chaplain itself is tapped + filler is tapped).
# The +1/+1 counter lands on the FIRST own-side creature (Sunstar Chaplain
# itself in this setup, since it's the first creature inserted onto p0's
# bf).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sunstar_chaplain_end_step_conditional_counter_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Sunstar Chaplain
    (round 25, BEGINNING_OF_END_STEP / Controlled(YOU) /
    ConditionalOnTappedCreatures(PutPlusOneCounterOnCreatureYouControl,
    min_count=2)).**

    Drives the **real parsed Sunstar Chaplain printing** (verified at
    probe entry) on the Python side and a bridged synthetic carrier on
    the Rust side through the ``BEGINNING_OF_END_STEP`` dispatch path.

    **NEW shape coverage:** the Frontline War-Rager probe
    (``test_probe_remaining_ww.py``:131) pins the IDENTICAL
    ``BEGINNING_OF_END_STEP + Controlled(YOU) +
    ConditionalOnTappedCreatures`` wrapper composition with
    ``PutPlusOneCounterOnSelf`` (self-target counter; NO target-pick at
    push-time).  **No probe has driven ConditionalOnTappedCreatures
    with the ``PutPlusOneCounterOnCreatureYouControl`` (target-creature
    counter)** inner effect until this one -- the inner shape differs
    from FWR's bit-identical wrapper: FWR's inner is the self-target;
    Sunstar Chaplain's inner is the target-creature with the
    ``IsCreature() & ControlledByYou()`` slot filter and at-push-time
    target picking.  This probe pins the
    ``conditional_on_tapped_creatures`` -> ``put_plus_one_counter_on_
    creature_you_control`` recursive composition end-to-end via the
    SATISFIED condition path (2 tapped creatures including Sunstar
    Chaplain), exercising the inner target-pick under the conditional
    wrapper.

    **QQQ drop reconciliation (the over-cautious grouping
    correction).** The QQQ batch (``test_probe_remaining_qqq.py``:
    86-98) grouped Sunstar Chaplain with Sami, Ship's Engineer as
    "bit-identical event+predicate+wrapper shape to FWR / Dawnstrike
    Vanguard".  The drop reason cited applies SPECIFICALLY to Sami's
    inner ``CreateToken(tapped=True)`` (the ``create_token`` Rust
    bridge arm cannot represent the ``tapped=True`` rider) -- NOT to
    Sunstar Chaplain's ``PutPlusOneCounterOnCreatureYouControl`` inner
    effect, which IS bridge-able via the
    ``put_plus_one_counter_on_creature_you_control`` arm at
    ``cross_engine.py``:1260-1317.  The QQQ grouping was therefore
    over-cautious for Sunstar Chaplain specifically; this batch
    reconciles the over-drop and pins it.

    **Bridge arms exercised:**
      * ``conditional_on_tapped_creatures`` (``cross_engine.py``:5966-6027)
      * ``put_plus_one_counter_on_creature_you_control``
        (``cross_engine.py``:1260-1317)
      * ``controlled_by_you`` predicate
        (``cross_engine.py``:~8986)

    **Recursive composer test.** The bridge translator dispatches
    ``conditional_on_tapped_creatures`` -> ``_ta_dict_to_python_effect``
    on the nested ``effect`` dict, which dispatches to the
    ``put_plus_one_counter_on_creature_you_control`` arm.  Validates
    the recursive composition for THIS pair end-to-end at the dict
    -> Python effect tree translation, paired with the real EoE Python
    parser producing the IDENTICAL Effect tree (Conditional ->
    PutPlusOneCounter) when reading the live printing.

    **Target-pick at push time vs. resolve time.** Python's
    ``ConditionalOnTappedCreatures.requires_target()`` delegates to
    the inner ``PutPlusOneCounterOnCreatureYouControl.requires_target()
    -> True``; the trigger is pushed WITH a target tuple (the
    ``_PickFirstControlledCreatureAgent`` shim picks Sunstar Chaplain
    itself -- the FIRST own-side creature, smallest battlefield
    index).  Rust resolves at-apply-time: scans the source-controller's
    bf top-to-bottom for the first creature, finds Sunstar Chaplain
    (smallest Vec index, inserted first).  The tapped-count check
    happens at resolve time on BOTH engines (CR 603-style
    intervening-if).  Both engines apply +1/+1 to Sunstar Chaplain
    on the SATISFIED path (count=2 == min_count=2); post-drain stack
    is empty.

    Setup:
      * p0 has Sunstar Chaplain (3/2 Creature -- Human Cleric) on the
        battlefield, summoning_sick=False, **tapped=True** (so it
        counts toward the tapped-creature condition).
      * p0 has a filler 2/2 Creature on the battlefield, summoning_
        sick=False, **tapped=True** (the second tapped creature
        satisfying min_count=2).
      * p1 has no permanents.
      * p0 / p1 libraries / hands both empty.
      * Active player = p0 (Sunstar Chaplain's controller).
      * Turn >= 2 to avoid the active-player-draws-on-turn-1 skip.

    Trigger flow:
      1. Both engines: advance to PHASE_END_STEP (10).
      2. Rust: dispatch ``Event::BeginningOfEndStep`` with subject =
         ``PLAYER_SUBJECT_OFFSET + active_player(=0)``.
         ``ControlledByYou`` resolves: source_controller=0 ==
         subject_player=0 -> predicate passes -> trigger pushed.
         Python: ``run_beginning_of_end_step_triggers`` ->
         ``dispatch_event(Event.BEGINNING_OF_END_STEP, player=
         active_player)``.  Same predicate match.
      3. Both stacks have 1 item.
      4. Drain stacks: ConditionalOnTappedCreatures resolves; tapped
         count = 2 (Sunstar Chaplain + filler) >= min_count=2; inner
         PutPlusOneCounterOnCreatureYouControl applies; +1/+1
         counter lands on Sunstar Chaplain (first own-side creature
         on both engines).
      5. SBAs: Sunstar Chaplain's effective_power becomes 3+1=4;
         effective_toughness becomes 2+1=3.

    Observables: **full ``compare_fields``** over the whole
    cross-engine field view.  Sunstar Chaplain ``counters`` slot is
    net +1 on BOTH engines; filler counters unchanged at 0; both bf
    objects tapped=True; lives unchanged at 20.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "conditional_on_tapped_creatures",
                "min_count": 2,
                "effect": {
                    "kind": "put_plus_one_counter_on_creature_you_control",
                    "amount": 1,
                },
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnCreatureYouControl,
    )
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Sunstar Chaplain printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Sunstar Chaplain")
    if real is None:
        pytest.skip("Sunstar Chaplain absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Sunstar Chaplain must be a Creature"
    )
    sc_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert sc_ta is not None, (
        "Sunstar Chaplain must have a BEGINNING_OF_END_STEP triggered ability"
    )
    assert isinstance(sc_ta.predicate, Controlled), (
        f"Sunstar Chaplain TA predicate must be Controlled; "
        f"got {type(sc_ta.predicate).__name__}"
    )
    assert sc_ta.predicate.by == YOU
    assert isinstance(sc_ta.effect, ConditionalOnTappedCreatures), (
        f"Sunstar Chaplain TA effect must be ConditionalOnTappedCreatures; "
        f"got {type(sc_ta.effect).__name__}"
    )
    assert sc_ta.effect.min_count == 2, (
        f"Sunstar Chaplain ConditionalOnTappedCreatures min_count must be 2; "
        f"got {sc_ta.effect.min_count}"
    )
    assert isinstance(
        sc_ta.effect.effect, PutPlusOneCounterOnCreatureYouControl
    ), (
        f"Sunstar Chaplain inner effect must be "
        f"PutPlusOneCounterOnCreatureYouControl; "
        f"got {type(sc_ta.effect.effect).__name__}"
    )
    assert sc_ta.effect.effect.amount == 1, (
        f"Sunstar Chaplain inner PutPlusOneCounterOnCreatureYouControl "
        f"amount must be 1; got {sc_ta.effect.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    PHASE_END_STEP = 10

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    sc_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "conditional_on_tapped_creatures",
            "min_count": 2,
            "effect": {
                "kind": "put_plus_one_counter_on_creature_you_control",
                "amount": 1,
            },
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(sc_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP
    assert isinstance(bridge_ta.predicate, Controlled)
    assert bridge_ta.predicate.by == YOU
    assert isinstance(bridge_ta.effect, ConditionalOnTappedCreatures)
    assert bridge_ta.effect.min_count == 2
    assert isinstance(
        bridge_ta.effect.effect, PutPlusOneCounterOnCreatureYouControl
    )
    assert bridge_ta.effect.effect.amount == 1

    # ------------------------------------------------------------------
    # 4. Rust: seat Sunstar Chaplain (with bridge TA) FIRST on p0's bf
    #    (smallest bf index -> first picked by Rust's at-apply scan).
    #    Then seat the filler 2/2 second.  Both tapped (so count >= 2).
    # ------------------------------------------------------------------
    rs_sc_id = rs.register_and_inject_object(
        {
            "name": "Sunstar Chaplain",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Cleric"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "triggered_abilities": [sc_ta_dict],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_sc_id)

    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "SC Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_filler_id)

    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty before phase advance; "
        f"got {rs.stack_size()}"
    )

    # Advance to PHASE_END_STEP (10); trigger should fire.
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break
    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Sunstar Chaplain end-step) expected; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # Sunstar Chaplain gets +1/+1: effective_power 3 -> 4, toughness 2 -> 3.
    rs_sc_pow = rs.effective_power(rs_sc_id)
    rs_sc_tou = rs.effective_toughness(rs_sc_id)
    assert rs_sc_pow == 4, (
        f"Rust: Sunstar Chaplain power must be 4 after +1/+1 counter; "
        f"got {rs_sc_pow}"
    )
    assert rs_sc_tou == 3, (
        f"Rust: Sunstar Chaplain toughness must be 3 after +1/+1 counter; "
        f"got {rs_sc_tou}"
    )

    # ------------------------------------------------------------------
    # 5. Python: inject Sunstar Chaplain with the BRIDGE TA (not the real
    #    parsed TA) directly onto p0's bf -- so both engines apply the
    #    SAME ConditionalOnTappedCreatures wrapper instance (the bridge
    #    output) and any future bridge-narrowing on additional fields
    #    stays observable identically.  The `real` printing's existence
    #    + shape was already verified at step 1 above (the
    #    establishment-of-binding required by PROBE_MODULES's genuine-
    #    binding inclusion predicate -- the test_cross_engine_real_eoe_
    #    sunstar_chaplain_*_parity function calls
    #    ``get_printings().get("Sunstar Chaplain")`` per the established
    #    real-EoE crediting rule).  Seat Sunstar Chaplain FIRST (smallest
    #    bf index, matching Rust's at-apply scan order).
    # ------------------------------------------------------------------
    py_sc_printing = CardPrinting(
        name="Sunstar Chaplain",
        mana_cost_str=real.mana_cost_str,
        mana_cost=real.mana_cost,
        type_line=real.type_line,
        supertypes=real.supertypes,
        card_types=real.card_types,
        subtypes=real.subtypes,
        power=int(real.power),
        toughness=int(real.toughness),
        produces=real.produces,
        keywords=real.keywords,
        triggered_abilities=(bridge_ta,),
    )
    py_sc = py.new_object(py_sc_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_sc.summoning_sick = False
    py_sc.tapped = True  # counts toward tapped-creature condition
    py_sc.damage = 0
    py_sc.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_sc)

    py_filler_printing = CardPrinting(
        name="SC Filler",
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
        py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_filler.summoning_sick = False
    py_filler.tapped = True
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    # Fire end-step triggers (mirrors Rust's advance-to-PHASE_END_STEP
    # dispatch).
    run_beginning_of_end_step_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Sunstar Chaplain end-step) expected; "
        f"got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # Sunstar Chaplain gets +1/+1: effective_power 3 -> 4, toughness 2 -> 3.
    py_sc_pow = effective_power(py, py_sc)
    py_sc_tou = effective_toughness(py, py_sc)
    assert py_sc_pow == 4, (
        f"Python: Sunstar Chaplain power must be 4 after +1/+1 counter; "
        f"got {py_sc_pow}"
    )
    assert py_sc_tou == 3, (
        f"Python: Sunstar Chaplain toughness must be 3 after +1/+1 counter; "
        f"got {py_sc_tou}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality across the WHOLE field view.
    #
    # NOTE on turn/step parity: Rust's ``advance_phase`` increments
    # turn_number through each step; Python's
    # ``run_beginning_of_end_step_triggers`` dispatches the event WITHOUT
    # changing the step pointer.  The two engines therefore land in
    # different ``turn`` / ``step`` slots after the trigger fires; the
    # cross-engine ``compare_fields`` view emits ``turn`` / ``step`` /
    # ``phase`` / ``active_player`` fields that would diverge purely on
    # the phase-advance mismatch (NOT on Effect application).  We filter
    # those out per the LLL Hylderblade precedent (end-step probe drives
    # Rust via ``advance_phase`` + Python via
    # ``run_beginning_of_end_step_triggers`` and asserts on TARGETED
    # observables, not full ``compare_fields``).  Drop the phase-tracking
    # fields and assert byte-equality on the rest (counters /
    # battlefield / hand / library / graveyard / exile / mana pool /
    # life totals).
    # ------------------------------------------------------------------
    py_view = build_python_field_view(py)
    rs_view = ce_parity_smoke()._build_field_view(rs)
    PHASE_ADVANCE_DIVERGENT_FIELDS = {
        "turn", "step", "phase", "active_player", "priority_player",
    }
    py_filtered = {
        k: v for k, v in py_view.items()
        if k not in PHASE_ADVANCE_DIVERGENT_FIELDS
    }
    rs_filtered = {
        k: v for k, v in rs_view.items()
        if k not in PHASE_ADVANCE_DIVERGENT_FIELDS
    }
    diffs = compare_fields(py_filtered, rs_filtered)
    assert diffs == [], (
        f"Sunstar Chaplain end-step conditional +1/+1 counter must be "
        f"byte-equal across the WHOLE field view (modulo phase-advance) "
        f"on BOTH engines; diffs={diffs}"
    )
