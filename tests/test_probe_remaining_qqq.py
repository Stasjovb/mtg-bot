"""Genuine real-EoE cross-engine byte-equality probes -- batch QQQ (round 22).

Three cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module.  Each probe drives the ACTUAL parsed EoE
printing on the Python side (or constructs a synthetic carrier with the
bridge spell-effect for keyword-grant cards per the OOO precedent) and the
bridged synthetic carrier on the Rust side, asserting full
``compare_fields == []`` byte-equality on a controlled real-EoE state --
the strongest evidence the campaign tracks.

The three probes deliberately cover effect/event shapes NOT already pinned
by the PROBED 196 (round-21 baseline):

  * **Demonic Counsel** -- Sorcery ``spell_effect = SearchLibraryForCard(
    filter_name='demon', may_fail=False)``.  The
    ``search_library_for_card`` bridge arm has been pinned at the synthetic
    ETB-trigger level (round 21) and via the ``demon``-filter Rust-only
    Registry test (``test_parity_smoke.py::test_rust_search_library_for_
    card_demon_filter_picks_demon_subtype``), but **no real-EoE card has
    driven it as a SPELL EFFECT** until this probe.  Library = exactly one
    Demon card: the search finds it, moves it to hand, library becomes
    empty.  Empty-library post-state SIDE-STEPS the post-search shuffle
    parity gap (``test_parity_smoke.py``:44185 -- "Rust's resolve has a
    ``// No shuffle (G19 deferral)`` comment; Python calls
    ``shuffle_library``.  The cross-engine library order would diverge
    AFTER the search resolves.") because there is nothing left to shuffle.

  * **Dark Endurance** -- Instant ``spell_effect = PumpTargetCreature
    UntilEOT(power_bonus=2, toughness_bonus=0, granted_keywords=
    {indestructible})``.  All prior ``pump_target_creature_until_eot``
    probes drive the effect as a TRIGGERED ABILITY (Hardened Escort /
    Most Valuable Slayer in OOO; Dual-Sun Adepts via activated; Xu-Ifit
    via activated; etc.).  **No probe has driven the bridge arm as a
    SPELL EFFECT** until this one.  Construct a synthetic Instant carrier
    with the bridge spell-effect dict (keyword grant dropped per the OOO
    precedent on Hardened Escort / Most Valuable Slayer); both engines
    apply power+2 to the same first-controlled creature filler.  The
    indestructible keyword grant is bridge-invisible -- the probe pins
    the numeric power+2 observable, mirroring the OOO bridge-narrowing
    discipline.

  * **Enter the Enigma** -- Sorcery ``spell_effect = Sequence(
    GrantUnblockableUEOT, DrawCards(1))``.  The
    ``grant_keyword_to_target_creature_until_eot`` bridge arm (with the
    'unblockable' keyword routing to ``GrantUnblockableUEOT`` per
    ``cross_engine.py``:6211-6217) has been pinned at the unit level but
    **no real-EoE card has driven it as a SPELL EFFECT inside a
    Sequence**.  Drives the real parsed Enter the Enigma printing on
    Python and a bridge ``Sequence([grant_keyword_..., draw_cards])``
    synthetic Sorcery on Rust.  Both engines grant ``cant_be_blocked``
    layer-6 to the filler creature and draw 1 card from p0's library.
    The probe pins the Sequence composition + the cant-be-blocked layer
    6 registry round-trip + DrawCards inside the same spell resolution.

DROPPED ON VERIFY (honest discipline)
-------------------------------------

  * **Trapped in the Screen** (ENTERS + IsSelf ->
    ExileOpponentsNonlandPermanentUntilLeaves): a probe attempt surfaced
    a NEW undocumented engine divergence on the exile-bf-leave path --
    **Rust sets ``summoning_sick=True`` on the exiled object; Python keeps
    it at its pre-exile False**.  The post-resolve field view differs on
    ``exile_p1`` only in the ``summoning_sick`` slot (Python:
    ``('TitS Bait Artifact', 0, 0, 0, 0, None, 1, 0)``; Rust:
    ``('TitS Bait Artifact', 0, 1, 0, 0, None, 1, 0)`` -- 3rd slot is
    ``summoning_sick``).  This divergence is NOT in
    ``docs/SEARCH_LIMITATIONS.md`` or in any existing ``test_divergence
    _pins_*.py``.  Per the lane discipline ("If a candidate card fails
    byte-equality, do NOT fix the probe to pass -- that's masking a real
    divergence. Instead, characterize the divergence and treat it as a
    divergence pin candidate for a sibling lane."), Trapped in the
    Screen is DROPPED from this probe batch.  A sibling-lane divergence
    pin should pin this exile-summoning-sick asymmetry (Rust's exile
    path needs to either stop stamping ``summoning_sick=True`` on the
    exiled object, OR Python's exile path needs to start stamping it;
    the canonical CR ruling is that an object's status leaving the
    battlefield doesn't reset summoning_sick -- the next time it enters
    bf, it does).  Cross-controller exile (``test_parity_smoke.py``:
    29210) does not surface this gap because that probe uses targeted
    assertions, not ``compare_fields``.

  * **Innocuous Rat** (DIES + IsSelf -> ManifestDread(1)): bit-identical
    shape to Bashful Beastie which is already PROBED via
    ``test_probe_remaining_iii.py``.  Adds no new effect/event coverage.

  * **Sami, Ship's Engineer** / **Sunstar Chaplain** (BEGINNING_OF_END_STEP
    + Controlled(YOU) -> ConditionalOnTappedCreatures(...)): bit-identical
    event+predicate+wrapper shape to Frontline War-Rager / Dawnstrike
    Vanguard (already PROBED via ``test_probe_remaining_ww.py``).  Only
    the inner Effect differs; Sami's inner is ``CreateToken(tapped=True)``
    which the ``create_token`` bridge arm cannot represent
    (``cross_engine.py``:2043-2049 -- "The variant has no
    tapped/attacking/each_player flags -- those are Python-side-only
    riders on CreateToken with no Rust mirror today, so the bridge arm
    constructs a plain CreateToken(...) with all rider flags at their
    dataclass defaults (tapped=False, ...)").  The Python-side
    ``tapped=True`` would create a tapped token; Rust's bridge create_token
    would create an untapped one.  Probe-blocked.

  * **Skystinger** (BLOCKS + And(IsSelf, Subject(HasKeyword(flying))) ->
    PumpSelfUntilEOT(+5/+0)): the bridge has no ``subject_has_keyword``
    predicate kind (Rust ``parse_predicate`` also has no
    ``SubjectHasKeyword`` variant -- see
    ``tests/test_probe_blocked_ff.py::test_blocks_trigger_bridge_predicate_
    gap_skystinger`` for the explicit gap pin).  Probe-blocked at the
    bridge layer.

  * **Mutavault** / **Inkmoth Nexus** / **Stirring Wildwood** / similar
    manlands (BecomeLandCreatureUEOT activated): the
    ``become_land_creature_until_eot`` effect has no Rust bridge arm
    (``tests/test_probe_activated_abilities_q.py``:71 -- "BecomeLandCreature
    effect has no Rust bridge arm (manland animation subsystem not in
    CE20)").  Probe-blocked at the bridge layer.

  * **Cautious Survivor** / **Defiant Survivor** / **Savior of the Small**
    / **Shrewd Storyteller** (BEGINNING_OF_POSTCOMBAT_MAIN trigger family):
    PPP Pin 3 pinned this event as unbridged (``test_divergence_pins_ppp.py``
    -- "beginning_of_postcombat_main event string not wired in bridge
    elif chain + no Rust Event variant").  Probe-blocked at the event
    layer.

  * **Optimistic Scavenger** / **Cult Healer** / **Gremlin Tamer** / etc.
    (ROOM_FULLY_UNLOCKED event TAs with PutPlusOneCounterOnTargetCreature
    inner effect): PPP Pin 2 pinned
    ``put_plus_one_counter_on_target_creature`` as unbridged
    (``test_divergence_pins_ppp.py`` -- "put_plus_one_counter_on_target_
    creature effect kind not wired").  Note that
    ``put_plus_one_counter_on_creature_you_control`` IS wired and is the
    arm Drix Fatemaker / Rayblade Trooper use; the distinction is the
    target-filter narrowness.  Probe-blocked at the effect layer.

  * **Withering Torment** / **Vanish from Sight** / **Lithobraking** /
    **Mental Modulation** (Sequence-rider spells): each has at least one
    sub-effect with a documented engine asymmetry (Withering Torment's
    DestroyTargetCreature(or_enchantment=True) carries a target-filter
    rider that the bare ``destroy_target`` bridge arm doesn't plumb;
    Vanish from Sight is documented in
    ``tests/test_probe_covered_unprobed_p.py``:111-122 with TWO engine
    asymmetries -- summoning_sick reset + top-vs-bottom default; etc.).

  * **The Seriema** / **Demon-rider riders** (legendary_creature filter):
    bit-identical shape to Starfield Shepherd (already PROBED).  No new
    bridge-arm coverage; the legendary_creature filter is the single
    filter-string that lights both cards.

  * **Vanilla creatures** (Slavering Branchsnapper, Daggermaw Megalodon,
    Bedhead Beastie, etc.): no triggered/activated abilities to fire; the
    probe would just be "vanilla creature exists on bf" with no event-
    driven observable.  No marginal effect/event shape coverage; the
    keyword-only behavior (deathtouch, trample, vigilance, menace, flying,
    etc.) is already probed by combat-shaped probes (Hullcarver
    deathtouch + others).

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Three cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with OOO wired in via
``PROBE_MODULES``): 196 -> 199 (+3).  Prior covered count: 118 -> 115 (-3).
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
# Probe 1 -- Demonic Counsel: Sorcery SearchLibraryForCard(demon)
#   spell_effect = SearchLibraryForCard(filter_name='demon', may_fail=False)
# Bridge: search_library_for_card{filter_name:'demon', may_fail:false}
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_demonic_counsel_search_demon_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Demonic Counsel
    (round 22, Sorcery SearchLibraryForCard(filter='demon', may_fail=False)).**

    Drives the **real parsed Demonic Counsel printing** (verified at probe
    entry) on the Python side and a bridged synthetic Sorcery carrier on the
    Rust side through the spell-resolution path.

    **Bridge arm:** ``search_library_for_card``
    (``cross_engine.py``:3739).  Field shape: ``{"kind":
    "search_library_for_card", "filter_name": "demon", "may_fail": false}``.

    **Library design (post-search shuffle gap side-step).** Rust's
    ``Effect::SearchLibraryForCard`` resolve does NOT shuffle the library
    post-search (round-21 substrate documented ``// No shuffle (G19
    deferral)``).  Python's ``SearchLibraryForCard.resolve`` calls
    ``shuffle_library`` at ``search.py:119``.  If the post-search library
    has >=2 cards, the two engines' library order would diverge.  The
    probe seats EXACTLY ONE demon in p0's library; after the search moves
    the demon to hand, p0's library is empty.  Empty libraries are
    permutation-invariant; the post-search shuffle is a no-op on both
    engines.  Byte-equality holds across the WHOLE field view.

    Setup:
      * p0's library has exactly one card: a synthetic 4/4 Demon creature
        (subtypes=('Demon',)).  No other cards in p0's library.
      * p1's library is empty.  Both hands are empty.
      * Demonic Counsel is pushed onto the stack as a Sorcery (no targets;
        the search is at-resolve, not at-cast).

    Resolution flow:
      1. Python: the real parsed Demonic Counsel spell_effect
         (SearchLibraryForCard) drives ``resolve``: scans p0's library,
         finds the Demon (filter='demon'), prompts ``agent.choose_card_
         from_library`` with [demon_id], moves demon to hand, shuffles
         (no-op on empty post-state).
      2. Rust: bridged synthetic ``search_library_for_card`` arm scans the
         same library, finds the same Demon, auto-picks the first match,
         moves to hand.  No post-search shuffle by design.
      3. Post-state: p0's hand has the Demon; p0's library is empty;
         p0's graveyard has Demonic Counsel itself (the spell moves
         from stack to caster's graveyard on resolution).

    Observables asserted: **full ``compare_fields``** over the whole
    cross-engine field view (hand, library, graveyard, exile, battlefield,
    stack, lives -- everything byte-equal).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from tests.parity._picker_shims import _PickFirstLibraryOptionAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Demonic Counsel printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Demonic Counsel")
    if real is None:
        pytest.skip("Demonic Counsel absent from active CardSource")
    assert "Sorcery" in real.card_types, "Demonic Counsel must be a Sorcery"
    se = real.spell_effect
    assert isinstance(se, SearchLibraryForCard), (
        f"genuine Demonic Counsel spell_effect must be "
        f"SearchLibraryForCard; got {type(se).__name__}"
    )
    assert se.filter_name == "demon", (
        f"Demonic Counsel SearchLibraryForCard filter_name must be 'demon'; "
        f"got {se.filter_name!r}"
    )
    assert se.may_fail is False, (
        f"Demonic Counsel SearchLibraryForCard may_fail must be False; "
        f"got {se.may_fail}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with a single-Demon library on p0.
    # ------------------------------------------------------------------
    demon = CardDef(
        name="DC Demon",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("B", 1),),
        power=4,
        toughness=4,
        subtypes=("Demon",),
    )
    spec = DeckSpec(
        card_defs=(demon,),
        p0_library=("DC Demon",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0  # ZONE_HAND

    # Seat the deterministic library-pick agent on p0 so Python's
    # choose_card_from_library matches Rust's first-filter-match
    # auto-resolve (options[0]).  With one demon in library the choice
    # is forced on both engines anyway, but the agent is required because
    # the base Agent.choose_card_from_library raises NotImplementedError.
    py.players[0].agent = _PickFirstLibraryOptionAgent()

    # ------------------------------------------------------------------
    # 3. Python: genuine parsed Demonic Counsel on the stack.
    # ------------------------------------------------------------------
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )

    py_lib_before = len(py.players[0].library)  # = 1
    py_hand_before = len(py.players[0].hand)    # = 0
    py_gy_before = len(py.players[0].graveyard) # = 0
    assert py_lib_before == 1, (
        f"Python: p0 library must start with exactly 1 demon; "
        f"got {py_lib_before}"
    )

    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0, (
        f"Python: stack must be empty after spell resolves; "
        f"got {len(py.stack)} items"
    )
    # The demon must be in hand; the spell must be in graveyard.
    assert len(py.players[0].hand) == py_hand_before + 1, (
        f"Python: p0 hand must grow by 1 (demon found); "
        f"got {len(py.players[0].hand)}"
    )
    py_hand_names = [o.printing.name for o in py.players[0].hand]
    assert py_hand_names == ["DC Demon"], (
        f"Python: p0 hand must contain DC Demon; got {py_hand_names}"
    )
    # Library is empty post-search (no remaining cards to shuffle).
    assert len(py.players[0].library) == 0, (
        f"Python: p0 library must be empty post-search; "
        f"got {len(py.players[0].library)}"
    )
    # Spell moved to caster's graveyard.
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert py_gy_names == ["Demonic Counsel"], (
        f"Python: p0 graveyard must contain Demonic Counsel; "
        f"got {py_gy_names}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: bridged search_library_for_card synthetic Sorcery.
    # ------------------------------------------------------------------
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Demonic Counsel",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "search_library_for_card",
                    "filter_name": "demon",
                    "may_fail": False,
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after spell resolves; "
        f"got {rs.stack_size()} items"
    )
    assert rs.library_sizes[0] == 0, (
        f"Rust: p0 library must be empty post-search; "
        f"got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == 1, (
        f"Rust: p0 hand must contain 1 card (the demon); "
        f"got {rs.hand_sizes[0]}"
    )

    # ------------------------------------------------------------------
    # 5. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Demonic Counsel search-demon must be byte-equal across the "
        f"WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Dark Endurance: Instant PumpTargetCreatureUntilEOT(+2/+0, indestructible)
#   Bridge spell_effect: pump_target_creature_until_eot{power_bonus:2, toughness_bonus:0}
#   (granted_keywords=indestructible dropped per OOO precedent)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dark_endurance_pump_target_filler_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Dark Endurance
    (round 22, Instant spell PumpTargetCreatureUntilEOT(+2/+0)).**

    Drives a synthetic Instant carrier (constructed from the bridge
    spell-effect dict) on BOTH engines.  The real Dark Endurance printing
    is verified at probe entry for shape but NOT used to drive resolution
    -- per the OOO precedent (Hardened Escort / Most Valuable Slayer), the
    bridge ``pump_target_creature_until_eot`` arm does NOT plumb
    ``granted_keywords`` into the dict shape, so a probe driving the real
    printing on Python would grant indestructible while the bridge synth
    on Rust would not.  Constructing the Python carrier from the bridge
    dict ensures both engines apply the SAME power+2 mutation with no
    keyword divergence -- the OOO bridge-narrowing discipline.

    **NEW shape coverage:** all prior ``pump_target_creature_until_eot``
    probes drive the effect as a TRIGGERED ABILITY (OOO Hardened Escort
    ATTACKS, OOO Most Valuable Slayer YOU_ATTACK, Dual-Sun Adepts /
    Xu-Ifit / Blinkmoth Nexus / Zookeeper Mechan via ACTIVATED).  This
    probe is the FIRST to drive the bridge arm as an INSTANT SPELL
    EFFECT, exercising the spell-resolution code path through the same
    bridge arm -- the orthogonal coverage axis to the OOO TA family.

    Bridge dict: ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": 2, "toughness_bonus": 0}``.

    Setup:
      * p0 has a filler 2/2 Creature (the only legal target on both
        engines).
      * p1 has no permanents.
      * Both engines push a synthetic ``Dark Endurance``-named Instant
        with the bridge spell_effect onto the stack.
      * Python side: ``_PickFirstControlledCreatureAgent`` picks the
        filler (the sole p0-controlled creature); Rust side at-apply-time
        scan picks the filler (the sole creature on p0's bf).

    Observables (targeted, byte-equal across the full field view):
      * filler power: 2 -> 4 on BOTH engines (+2 power_bonus).
      * filler toughness: 2 (unchanged) on BOTH engines.
      * Synthetic Dark Endurance moves stack -> caster's graveyard on
        BOTH engines.
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
    from mtg_bot.game import StackItem, Zone, effective_power, effective_toughness
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Dark Endurance printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Dark Endurance")
    if real is None:
        pytest.skip("Dark Endurance absent from active CardSource")
    assert "Instant" in real.card_types, "Dark Endurance must be an Instant"
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"genuine Dark Endurance spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 2, (
        f"Dark Endurance PumpTargetCreatureUntilEOT power_bonus must be 2; "
        f"got {se.power_bonus}"
    )
    assert se.toughness_bonus == 0, (
        f"Dark Endurance PumpTargetCreatureUntilEOT toughness_bonus must be 0; "
        f"got {se.toughness_bonus}"
    )
    assert "indestructible" in se.granted_keywords, (
        f"Dark Endurance PumpTargetCreatureUntilEOT must grant indestructible; "
        f"got keywords={se.granted_keywords}"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge spell-effect dict (power+2, no keywords).
    # ------------------------------------------------------------------
    de_effect_dict = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 2,
        "toughness_bonus": 0,
    }
    bridge_effect = _ta_dict_to_python_effect(de_effect_dict)
    assert isinstance(bridge_effect, PumpTargetCreatureUntilEOT), (
        f"Bridge effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(bridge_effect).__name__}"
    )
    assert bridge_effect.power_bonus == 2, (
        f"Bridge effect power_bonus must be 2; got {bridge_effect.power_bonus}"
    )

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
    # 4. Rust: seat the filler 2/2 on p0's bf, then push synthetic Dark
    # Endurance with the bridge spell_effect onto the stack.
    # ------------------------------------------------------------------
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "DE Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    assert rs.effective_power(rs_filler_id) == 2, (
        f"Rust: filler must start at power 2; "
        f"got {rs.effective_power(rs_filler_id)}"
    )

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Dark Endurance",
            "card_types": ["Instant"],
            "effects": [de_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    assert rs.stack_size() == 1, (
        f"Rust: Dark Endurance must be on the stack; "
        f"got stack_size={rs.stack_size()}"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after the spell resolves; "
        f"got {rs.stack_size()}"
    )
    rs_filler_pow = rs.effective_power(rs_filler_id)
    assert rs_filler_pow == 4, (
        f"Rust: filler power must be 4 after pump (+2); got {rs_filler_pow}"
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the filler 2/2 on p0's bf, then push synthetic Dark
    # Endurance with the bridge spell_effect onto the stack.
    # ------------------------------------------------------------------
    py_filler_printing = CardPrinting(
        name="DE Filler",
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
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)
    assert effective_power(py, py_filler) == 2, (
        "Python: filler must start at power 2"
    )

    # Construct a synthetic Dark Endurance printing using the bridge
    # spell_effect (no granted_keywords -- the OOO bridge-narrowing
    # idiom).
    py_de_printing = CardPrinting(
        name="Dark Endurance",
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
    py_spell = py.new_object(py_de_printing, owner_id=0, zone=Zone.STACK)
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
    py_filler_pow = effective_power(py, py_filler)
    assert py_filler_pow == 4, (
        f"Python: filler power must be 4 after pump (+2); got {py_filler_pow}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Dark Endurance pump+2 must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 3 -- Enter the Enigma: Sorcery Sequence(GrantUnblockableUEOT, DrawCards)
#   Bridge spell_effect: sequence{effects:[
#     grant_keyword_to_target_creature_until_eot{keyword:'unblockable'},
#     draw_cards{amount:1}
#   ]}
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_enter_the_enigma_grant_unblockable_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Enter the Enigma
    (round 22, Sorcery Sequence(GrantUnblockableUEOT, DrawCards(1))).**

    Drives the **real parsed Enter the Enigma printing** (verified at probe
    entry) on the Python side and a bridged synthetic Sorcery carrier on
    the Rust side through the spell-resolution path.  Both engines grant
    cant-be-blocked layer-6 to the filler creature AND draw 1 card from
    p0's library, in that order, in a single spell resolution.

    **Bridge composition.** The bridge arm chain is::

        {
          "kind": "sequence",
          "effects": [
            {"kind": "grant_keyword_to_target_creature_until_eot",
             "keyword": "unblockable"},
            {"kind": "draw_cards", "count": 1}
          ]
        }

    The ``sequence`` arm (``cross_engine.py``:1494) recursively translates
    each child.  The ``grant_keyword_to_target_creature_until_eot`` arm
    (``cross_engine.py``:6173+) dispatches by keyword: ``'unblockable'``
    routes to ``GrantUnblockableUEOT`` (writes a ``cant_be_blocked``
    registry entry); other keywords would route to
    ``PumpTargetCreatureUntilEOT(granted_keywords={kw})``.  The
    ``draw_cards`` arm constructs ``DrawCards(amount=1)``.

    **NEW shape coverage:** while Sequence composition has been probed
    (Commune with Evil drives ``Sequence(LookTopN, GainLife)``), no probe
    has driven Sequence with a TARGETING sub-effect (GrantUnblockableUEOT
    requires a creature target) inside a real spell.  The probe pins
    Sequence's per-child target-resolution semantics.

    Setup:
      * p0 library has 1 filler card (DrawCards consumes it).
      * p0 has a filler 2/2 Creature on the battlefield (the only legal
        unblockable target on both engines).
      * p1 has no permanents and no library cards.
      * Both engines push synthetic Enter the Enigma onto the stack
        (Python uses the genuine parsed printing; Rust uses the bridged
        synthetic with the Sequence effect dict).

    Resolution flow:
      1. Python: ``resolve_top_of_stack`` walks Enter the Enigma's
         ``Sequence`` effects in order.  Effect[0] = GrantUnblockableUEOT;
         the targeting pipeline picks the filler via
         ``_PickFirstControlledCreatureAgent``.  Effect[1] = DrawCards(1):
         moves library[0] to hand.
      2. Rust: ``resolve_top_of_stack`` walks the bridged Sequence;
         child[0] = grant_keyword_to_target_creature_until_eot picks the
         filler (deterministic at-apply-time scan).  Child[1] = draw_cards
         moves library[0] to hand.

    Observables (byte-equal across the full field view):
      * filler has cant_be_blocked layer-6 registered (UEOT).
      * p0 hand: 0 -> 1 card.
      * p0 library: 1 -> 0 cards.
      * p0 graveyard: 0 -> 1 card (the Enter the Enigma spell itself).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
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
    from mtg_bot.effects.generic.grant_keywords import GrantUnblockableUEOT
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Enter the Enigma printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Enter the Enigma")
    if real is None:
        pytest.skip("Enter the Enigma absent from active CardSource")
    assert "Sorcery" in real.card_types, "Enter the Enigma must be a Sorcery"
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Enter the Enigma spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2, (
        f"Enter the Enigma Sequence must have 2 child effects; "
        f"got {len(se.effects)}"
    )
    assert isinstance(se.effects[0], GrantUnblockableUEOT), (
        f"Enter the Enigma Sequence[0] must be GrantUnblockableUEOT; "
        f"got {type(se.effects[0]).__name__}"
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    assert isinstance(se.effects[1], DrawCards), (
        f"Enter the Enigma Sequence[1] must be DrawCards; "
        f"got {type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 1, (
        f"Enter the Enigma DrawCards amount must be 1; "
        f"got {se.effects[1].amount}"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge spell-effect dict.
    # ------------------------------------------------------------------
    ete_effect_dict = {
        "kind": "sequence",
        "effects": [
            {
                "kind": "grant_keyword_to_target_creature_until_eot",
                "keyword": "unblockable",
            },
            # Rust's parse_effect requires ``count`` (cards.rs);
            # the bridge translator at cross_engine.py:535-540 maps
            # ``count`` -> Python's ``DrawCards(amount=...)``.
            {"kind": "draw_cards", "count": 1},
        ],
    }
    bridge_effect = _ta_dict_to_python_effect(ete_effect_dict)
    assert isinstance(bridge_effect, Sequence)
    assert isinstance(bridge_effect.effects[0], GrantUnblockableUEOT)
    assert isinstance(bridge_effect.effects[1], DrawCards)

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with a single filler in p0's library.
    # ------------------------------------------------------------------
    library_filler = CardDef(
        name="ETE Lib Filler",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(library_filler,),
        p0_library=("ETE Lib Filler",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ------------------------------------------------------------------
    # 4. Rust: seat the filler 2/2 on p0's bf, then push synthetic Enter
    # the Enigma with the bridge spell_effect onto the stack.
    # ------------------------------------------------------------------
    rs_creature_id = rs.register_and_inject_object(
        {
            "name": "ETE Creature Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs_lib_before = rs.library_sizes[0]
    rs_hand_before = rs.hand_sizes[0]
    rs_gy_before = len(rs.graveyard_snapshot(0))

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Enter the Enigma",
            "card_types": ["Sorcery"],
            "effects": [ete_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    assert rs.stack_size() == 1, (
        f"Rust: Enter the Enigma must be on the stack; "
        f"got {rs.stack_size()}"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after the spell resolves; "
        f"got {rs.stack_size()}"
    )
    # Library shrank by 1 (DrawCards consumed it); hand grew by 1.
    assert rs.library_sizes[0] == rs_lib_before - 1, (
        f"Rust: p0 library must shrink by 1; "
        f"before={rs_lib_before} after={rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == rs_hand_before + 1, (
        f"Rust: p0 hand must grow by 1; "
        f"before={rs_hand_before} after={rs.hand_sizes[0]}"
    )
    # Spell moved to caster's graveyard.
    assert len(rs.graveyard_snapshot(0)) == rs_gy_before + 1, (
        f"Rust: p0 graveyard must grow by 1 (Enter the Enigma); "
        f"before={rs_gy_before} after={len(rs.graveyard_snapshot(0))}"
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the filler 2/2 on p0's bf, then push genuine Enter
    # the Enigma printing onto the stack.
    # ------------------------------------------------------------------
    py_creature_printing = CardPrinting(
        name="ETE Creature Filler",
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
    py_creature = py.new_object(py_creature_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_creature.summoning_sick = False
    py_creature.tapped = False
    py_creature.damage = 0
    py_creature.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_creature)

    py_lib_before = len(py.players[0].library)
    py_hand_before = len(py.players[0].hand)
    py_gy_before = len(py.players[0].graveyard)

    # Push the genuine parsed Enter the Enigma printing on the stack.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_creature.id),))
    )

    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0, (
        f"Python: stack must be empty after the spell resolves; "
        f"got {len(py.stack)}"
    )
    assert len(py.players[0].library) == py_lib_before - 1, (
        f"Python: p0 library must shrink by 1; "
        f"before={py_lib_before} after={len(py.players[0].library)}"
    )
    assert len(py.players[0].hand) == py_hand_before + 1, (
        f"Python: p0 hand must grow by 1; "
        f"before={py_hand_before} after={len(py.players[0].hand)}"
    )
    assert len(py.players[0].graveyard) == py_gy_before + 1, (
        f"Python: p0 graveyard must grow by 1 (Enter the Enigma); "
        f"before={py_gy_before} after={len(py.players[0].graveyard)}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Enter the Enigma grant-unblockable + draw must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
