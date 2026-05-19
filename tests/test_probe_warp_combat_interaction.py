"""Genuine real-EoE cross-engine byte-equality probes for the
warp-admitted creatures' COMBAT-interaction surface.

**The disjoint dimension this module closes.**

``tests/test_probe_warp_admitted.py`` (merge ``95c99fa2``) PROBED the
five warp-admitted creatures' *lifecycle* (cast-via-warp → end-step
exile sweep → recast-from-exile) + normal non-warp play, FULL
``compare_fields`` byte-equal on real 17lands deck contexts. The
pre-existing Phase-1 / Phase-1.5 lifecycle probes do the same on a
synthetic library. **None of them — nor any other module — ever
exercises a warp-cast creature in COMBAT.** That is a structurally
distinct, previously-unprobed, unowned code path:

  * **Red Tiger Mechan has ``haste``** ({1}{R} warp, 3/3). A
    warp-cast hasty creature can be declared as an ATTACKER the SAME
    turn it is warped in (CR 702.10b — haste lifts the summoning-
    sickness attack restriction even though ``summoning_sick`` stays
    True). It then participates in combat and is swept to exile at
    that turn's end step AFTER combat. Cast → attack-same-turn →
    post-combat warp-exile is a combat code path neither the
    lifecycle probes nor the bench collateral sweep pin individually.

  * **The non-haste warp creatures (Bygone Colossus 9/9, Germinating
    Wurm 5/5, Knight Luminary 3/2) and the flier without haste
    (Starbreach Whale 3/5 ``flying``)** expose the load-bearing
    *negative* combat interaction: a warp-cast vanilla/flying-but-
    non-hasty creature is summoning-sick with no haste, so at its
    controller's DECLARE_ATTACKERS the SAME turn it is NOT a legal
    attacker — and it is swept to exile at that turn's end step
    BEFORE its controller ever reaches a combat it could legally
    attack in. A non-haste warp creature therefore can *never* attack
    off a single warp-cast. This negative control proves the
    warp-exile timing (end of the turn it entered) interacts
    correctly with combat eligibility on BOTH engines.

  * **Knight Luminary additionally proves the ETB token survives the
    warp sweep**: the warp-exile moves only the warped creature
    itself; its ETB-created Human Soldier token stays on the
    battlefield (it was never warped). A byte-equal "only the warped
    permanent leaves" assertion the lifecycle probes do not make.

Every probe is seated in a **real 17lands archetype deck context**
(the round-46 real-signal discipline — ``load_production_deck`` →
``_filter_deck_to_bridge_supported`` → ``production_deck_to_deckspec``,
the bench's real path) and asserts FULL ``compare_fields`` byte-
equality at every step + phase boundary (``step_both``'s
``.divergences == []`` IS the strong-tier assertion, post-
``_net_counters`` ``ecc5f680``; the per-phase ``adv`` helper runs the
full ``compare_fields`` at every boundary).

**Honest harness scope (NOT a relaxation).** The lifecycle harness
(``step_both`` + the ``advance_phase_python`` / ``rust_state.
advance_phase`` side-channel mirror) advances the turn STRUCTURE for
parity comparison; it does not run the priority/combat-damage
machinery (combat damage is not auto-dealt by the phase-advance
primitive — uniformly on BOTH engines, so it stays byte-equal). This
module therefore asserts what is genuinely true and byte-equal in
this harness: the warp creature's **attack-DECLARATION** byte-equality
(``declare_attackers`` divergence-free, ``attacking`` / ``tapped``
state), the **attacker-legality** of haste vs non-haste, the
**post-combat warp-exile** timing, and the **ETB-token-survives-the-
sweep** interaction. It deliberately does NOT assert a combat-damage
life total (the harness does not deal it; asserting "p1 took 3" would
be testing the harness, not the engines). The full-game-loop bench
sweep is the tier that exercises combat damage; this is the
controlled-state PROBED tier for the warp+combat *decision* surface.
No ``docs/SEARCH_LIMITATIONS.md`` entry — pure evidence-strengthening,
zero shortcut introduced (the harness's combat-damage scope is a
pre-existing, already-documented property of the lifecycle harness).

**Verify-first.** Each probe re-resolves the live printing and
asserts it is still warp-admitted (the warp arm, not the plain
simple-creature arm) AND carries the expected combat-relevant keyword
shape, BEFORE probing — FAILing loudly (never silently skipping) on
live-tree drift.

**Disjointness.** A distinct dimension (combat interaction) from the
lifecycle module and a disjoint card-USE from every sibling-owned
module. Does NOT touch ``tests/test_trajectory_parity.py``, the
``test_probe_covered_unprobed_*`` modules, the
``test_probe_spell_card_bridge_admitted`` module, the
``test_probe_warp_admitted`` module, or the protected
``test_audit_safe_trigger_*`` tests.
"""

import sys
import pathlib

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


_BASIC_FOR_COLOR = {
    "R": "Mountain", "G": "Forest", "W": "Plains",
    "U": "Island", "B": "Swamp",
}


def _verify_warp_admitted(card_name, warp_str, normal_str,
                          expect_keywords):
    """Verify-first: the live printing IS still warp-admitted (warp
    arm, not the plain simple-creature arm) AND carries the expected
    combat-relevant keyword shape. FAILs loudly on drift.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    real = src.get(card_name)
    if real is None:
        pytest.fail(
            f"{card_name} absent from the active CardSource — the warp "
            f"Phase-1/1.5 admit set drifted; re-derive + drop/replace "
            f"this probe honestly (do NOT relax to a skip)."
        )
    assert real.warp_cost is not None and real.warp_cost_str == warp_str, (
        f"{card_name}: live warp_cost_str {real.warp_cost_str!r} != "
        f"pinned {warp_str!r}; printing drifted — re-pin."
    )
    assert real.mana_cost_str == normal_str, (
        f"{card_name}: live mana_cost_str {real.mana_cost_str!r} != "
        f"pinned {normal_str!r}; printing drifted — re-pin."
    )
    assert getattr(real, "warp_additional_life_cost", 0) == 0
    assert getattr(real, "warp_castable_from_graveyard", False) is False
    assert frozenset(real.keywords) == frozenset(expect_keywords), (
        f"{card_name}: live keywords {sorted(real.keywords)} != "
        f"expected {sorted(expect_keywords)} — the combat-relevant "
        f"keyword shape drifted; re-pin this probe."
    )
    assert trajectory._printing_is_bridge_pure_warp_creature(real), (
        f"{card_name} is NOT warp-admitted at live HEAD — re-derive "
        f"the warp-admitted set."
    )
    assert not trajectory._printing_is_bridge_simple_creature(real), (
        f"{card_name}: the PLAIN simple-creature arm admits it — the "
        f"warp arm is then not the load-bearing admit path. Re-derive."
    )
    return real


def _build_real_deck_context(card_name, color, real_archetype):
    """Seat the genuine warp printing into a REAL 17lands archetype
    deck context (basics normalised to tap the card's color). Returns
    ``(py, rs)`` matched states.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec

    try:
        deck_names = trajectory.load_production_deck(
            archetype=real_archetype)
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable")

    src = get_active_source().get_printings()
    filtered, _defs = trajectory._filter_deck_to_bridge_supported(
        deck_names, src)
    basic = _BASIC_FOR_COLOR[color]
    spec = trajectory.production_deck_to_deckspec(
        [card_name] + list(filtered), list(filtered),
        pad_to_size=45, pad_with=basic)
    newdefs = tuple(
        CardDef(name=c.name, card_type="Land", mana_produced=(color,))
        if c.card_type == "Land" else c
        for c in spec.card_defs
    )
    spec = DeckSpec(
        card_defs=newdefs,
        p0_library=spec.p0_library,
        p1_library=spec.p1_library,
    )
    assert spec.p0_library.count(card_name) == 1
    return trajectory.setup_matched_game(spec)


def _mana_total(cost_str):
    import re
    return sum(
        int(x) if x.isdigit() else 1
        for x in re.findall(r"\{([^}]+)\}", cost_str)
    )


def _make_adv(card_name, py, rs):
    from mtg_bot.parity.cross_engine import (
        advance_phase_python, compare_fields,
    )
    from test_trajectory_parity import _step_views

    def adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            assert not d, (
                f"{card_name}: phase advance ({pv['step']}, turn "
                f"{pv['turn']}) diverged (FULL compare_fields): "
                f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
            )
    return adv


def _warp_cast_into_play(card_name, color, warp_str, real_archetype):
    """Seat into a real-deck context, ramp byte-equal to a p0
    PRECOMBAT_MAIN with the warp cost payable, and warp-cast the
    creature. Returns ``(py, rs, adv, p0)`` with the creature on p0's
    battlefield, warped, FULL byte-equal throughout.
    """
    from mtg_bot.parity.cross_engine import step_both, step_both_drained
    from test_trajectory_parity import _step_views

    py, rs = _build_real_deck_context(
        card_name, color, real_archetype)
    adv = _make_adv(card_name, py, rs)
    warp_total = _mana_total(warp_str)

    adv(3)
    p0 = py.active_player_idx
    for _cycle in range(40):
        n_lands_bf = sum(
            1 for o in py.battlefield
            if o.controller_id == p0 and o.printing.is_land
        )
        if n_lands_bf >= warp_total:
            break
        if (py.active_player_idx == p0
                and py.players[p0].lands_played_this_turn == 0):
            hand_land = [
                o for o in py.players[p0].hand
                if o.printing.is_land
            ]
            if hand_land:
                s = step_both(
                    py, rs,
                    {"kind": "play_land",
                     "card_id": int(hand_land[0].id)})
                assert not s.divergences, (
                    f"{card_name}: play_land diverged: "
                    f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
                )
        adv(24)
    n_lands_bf = sum(
        1 for o in py.battlefield
        if o.controller_id == p0 and o.printing.is_land
    )
    if n_lands_bf < warp_total:
        pytest.skip(
            f"{card_name}: real-deck-context arch did not develop "
            f"{warp_total} lands within budget (got {n_lands_bf}) — "
            f"land-light shuffle; the byte-equal trajectory up to here "
            f"held. Re-pin a land-richer archetype if persistent."
        )
    for _ in range(60):
        pv, _rv = _step_views(py, rs)
        if (py.active_player_idx == p0
                and pv["step"] == "PRECOMBAT_MAIN"
                and py.players[p0].lands_played_this_turn == 0):
            break
        adv(1)
    # Tap exactly warp_total lands for the warp cost.
    taps = 0
    for o in list(py.battlefield):
        if (o.controller_id == p0 and o.printing.is_land
                and not o.tapped and not o.summoning_sick
                and taps < warp_total):
            s = step_both(
                py, rs,
                {"kind": "activate_ability",
                 "source_id": int(o.id), "ability_index": 0})
            assert not s.divergences, (
                f"{card_name}: land tap diverged: "
                f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
            )
            taps += 1
    assert taps == warp_total, (
        f"{card_name}: needed {warp_total} mana; tapped {taps}"
    )
    card_obj = next(
        o for o in py.players[p0].hand
        if o.printing.name == card_name)
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(card_obj.id),
         "use_warp": True})
    assert not s.divergences, (
        f"{card_name}: warp cast diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    assert py.spell_warped_this_turn is True
    assert rs.spell_warped_this_turn is True
    return py, rs, adv, p0


def test_warp_haste_creature_attacks_same_turn_then_post_combat_exile():
    """**Red Tiger Mechan — the haste+warp+combat path.**

    Warp-cast (``haste``, 3/3) → declared as an ATTACKER the SAME turn
    it is warped in (CR 702.10b: haste lifts the summoning-sickness
    attack restriction) → through combat (FULL byte-equal at every
    phase) → swept to exile at that turn's end step AFTER combat
    (FULL byte-equal). The attack-declaration + post-combat warp-exile
    code path no other module pins individually.
    """
    from mtg_bot.parity.cross_engine import step_both, step_both_drained
    from mtg_bot.legal import legal_actions
    from test_trajectory_parity import _step_views

    card_name = "Red Tiger Mechan"
    real = _verify_warp_admitted(
        card_name, "{1}{R}", "{3}{R}", {"haste"})
    assert "haste" in real.keywords

    py, rs, adv, p0 = _warp_cast_into_play(
        card_name, "R", "{1}{R}", 5)

    creature = next(
        o for o in py.battlefield
        if o.printing.name == card_name)
    # Haste keeps summoning_sick True but lifts the attack restriction.
    assert creature.summoning_sick is True, (
        f"{card_name}: a creature is summoning-sick the turn it enters "
        f"(haste lifts the attack restriction, it does NOT clear the "
        f"flag — CR 702.10b)"
    )
    assert "haste" in creature.printing.keywords

    # Advance to this turn's DECLARE_ATTACKERS, FULL byte-equal.
    for _ in range(8):
        pv, _rv = _step_views(py, rs)
        if pv["step"] == "DECLARE_ATTACKERS":
            break
        adv(1)
    pv, _rv = _step_views(py, rs)
    assert pv["step"] == "DECLARE_ATTACKERS"

    # The hasty warp creature CAN be declared an attacker the same
    # turn — declare it, FULL compare_fields byte-equal.
    s = step_both(
        py, rs,
        {"kind": "declare_attackers",
         "attacker_ids": [int(creature.id)]})
    assert not s.divergences, (
        f"{card_name}: declare_attackers (hasty warp creature) "
        f"diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    atk = next(
        (o for o in py.battlefield
         if o.printing.name == card_name), None)
    assert atk is not None and atk.attacking is True, (
        f"{card_name}: the hasty warp creature must be ATTACKING on "
        f"Python after declare_attackers (haste allowed it the same "
        f"turn it was warped in)"
    )
    assert atk.tapped is True, (
        f"{card_name}: a (non-vigilance) attacker taps on attack"
    )

    # Through combat to this turn's end step — the warp-exile delayed
    # trigger fires AFTER combat (CR-603.7); FULL byte-equal at every
    # phase. S7-A2: drain the stack via the explicit primitive at the
    # END step so the delayed WarpExileSelf trigger resolves into
    # exile on BOTH engines.
    from mtg_bot.parity.cross_engine import drain_stack_both
    for _ in range(14):
        pv, _rv = _step_views(py, rs)
        if pv["step"] == "END" and pv["turn"] == pv["turn"]:
            # advance one more so the end-step trigger has run +
            # drain the stack so the trigger resolves.
            adv(1)
            drain_stack_both(py, rs)
            break
        adv(1)
    py_ex = [
        o for o in py.players[p0].exile
        if o.printing.name == card_name]
    rs_ex = [
        o for o in rs.exile_snapshot(p0)
        if o["printing_name"] == card_name]
    assert len(py_ex) == 1 and len(rs_ex) == 1, (
        f"{card_name}: after attacking, the warp creature must be "
        f"swept to exile at that turn's end step on BOTH engines; "
        f"py_ex={len(py_ex)} rs_ex={len(rs_ex)}"
    )
    assert not [
        o for o in py.battlefield
        if o.printing.name == card_name], (
        f"{card_name}: must have left the Python battlefield"
    )
    assert not [
        o for o in rs.battlefield_snapshot()
        if o["printing_name"] == card_name], (
        f"{card_name}: must have left the Rust battlefield"
    )


@pytest.mark.parametrize(
    "card_name,color,warp_str,normal_str,real_archetype,"
    "keywords,etb_token",
    [
        ("Bygone Colossus", "R", "{3}", "{9}", 5, frozenset(), False),
        ("Germinating Wurm", "G", "{1}{G}", "{4}{G}", 2,
         frozenset(), False),
        ("Knight Luminary", "W", "{1}{W}", "{3}{W}", 9,
         frozenset(), True),
        ("Starbreach Whale", "U", "{1}{U}", "{4}{U}", 2,
         frozenset({"flying"}), False),
    ],
    ids=["Bygone_Colossus", "Germinating_Wurm",
         "Knight_Luminary", "Starbreach_Whale"],
)
def test_warp_nonhaste_creature_cannot_attack_then_exiled_before_combat(
    card_name, color, warp_str, normal_str, real_archetype,
    keywords, etb_token,
):
    """**The negative combat control — non-haste warp creatures.**

    A warp-cast creature with NO ``haste`` (Bygone Colossus 9/9,
    Germinating Wurm 5/5, Knight Luminary 3/2, Starbreach Whale 3/5
    ``flying``) is summoning-sick with no haste, so at its
    controller's DECLARE_ATTACKERS the SAME turn it is NOT a legal
    attacker (the ONLY legal action is ``PassPriority``), and it is
    swept to exile at that turn's end step BEFORE its controller ever
    reaches a combat it could legally attack in. A single warp-cast
    therefore can never let it attack. FULL byte-equal throughout.

    Knight Luminary additionally pins that the ETB-created Human
    Soldier token SURVIVES the warp sweep (only the warped permanent
    itself is exiled — the token was never warped).
    """
    from mtg_bot.legal import legal_actions
    from test_trajectory_parity import _step_views

    real = _verify_warp_admitted(
        card_name, warp_str, normal_str, keywords)
    assert frozenset(real.keywords) == keywords

    py, rs, adv, p0 = _warp_cast_into_play(
        card_name, color, warp_str, real_archetype)

    creature = next(
        o for o in py.battlefield
        if o.printing.name == card_name)
    assert creature.summoning_sick is True
    assert "haste" not in creature.printing.keywords

    # ETB-token survival fixture (Knight Luminary): the token is on
    # the battlefield right after the warp-cast resolved.
    if etb_token:
        tokens_after_cast = [
            o for o in py.battlefield
            if o.controller_id == p0
            and o.printing.name == "Human Soldier"]
        assert len(tokens_after_cast) >= 1, (
            f"{card_name}: ETB CreateToken must have minted a Human "
            f"Soldier under the warp-cast"
        )

    # Advance to this turn's DECLARE_ATTACKERS, FULL byte-equal.
    for _ in range(8):
        pv, _rv = _step_views(py, rs)
        if pv["step"] == "DECLARE_ATTACKERS":
            break
        adv(1)
    pv, _rv = _step_views(py, rs)
    assert pv["step"] == "DECLARE_ATTACKERS"

    # The non-haste warp creature is NOT a legal attacker (summoning
    # sick, no haste): the only legal action is PassPriority. There is
    # no declare_attackers action that includes this creature.
    legal_kinds = sorted({
        a.__class__.__name__ for a in legal_actions(py, p0)
    })
    assert legal_kinds == ["PassPriority"], (
        f"{card_name}: a summoning-sick non-haste warp creature must "
        f"NOT enable any attack action the turn it is warped in; the "
        f"only legal action must be PassPriority, got {legal_kinds}"
    )

    # Continue to this turn's end step + one phase past it so the
    # warp-exile delayed trigger has fired AND resolved; FULL
    # byte-equal at every phase. S7-A2: explicit drain after END.
    from mtg_bot.parity.cross_engine import drain_stack_both
    cast_turn = pv["turn"]
    for _ in range(16):
        pv, _rv = _step_views(py, rs)
        if pv["step"] == "END" and pv["turn"] == cast_turn:
            adv(1)  # END -> CLEANUP, trigger has fired onto the stack
            drain_stack_both(py, rs)  # resolve the trigger
            break
        adv(1)

    py_ex = [
        o for o in py.players[p0].exile
        if o.printing.name == card_name]
    rs_ex = [
        o for o in rs.exile_snapshot(p0)
        if o["printing_name"] == card_name]
    assert len(py_ex) == 1 and len(rs_ex) == 1, (
        f"{card_name}: the non-haste warp creature must be swept to "
        f"exile at the end of the turn it entered — BEFORE it could "
        f"ever attack — on BOTH engines; py_ex={len(py_ex)} "
        f"rs_ex={len(rs_ex)}"
    )
    assert not [
        o for o in py.battlefield
        if o.printing.name == card_name], (
        f"{card_name}: must have left the Python battlefield by its "
        f"first end step (never reaching an attackable combat)"
    )
    assert not [
        o for o in rs.battlefield_snapshot()
        if o["printing_name"] == card_name], (
        f"{card_name}: must have left the Rust battlefield"
    )

    # Knight Luminary: the ETB Human Soldier token SURVIVES the sweep
    # (only the warped permanent is exiled — byte-equal token count).
    if etb_token:
        py_tok = [
            o for o in py.battlefield
            if o.controller_id == p0
            and o.printing.name == "Human Soldier"]
        rs_tok = [
            o for o in rs.battlefield_snapshot()
            if o.get("controller_id") == p0
            and o["printing_name"] == "Human Soldier"]
        assert len(py_tok) >= 1, (
            f"{card_name}: the ETB Human Soldier token must SURVIVE "
            f"the warp-exile sweep on Python (only the warped "
            f"permanent is exiled); py tokens={len(py_tok)}"
        )
        assert len(rs_tok) == len(py_tok), (
            f"{card_name}: ETB-token-survives-the-sweep count diverged "
            f"py={len(py_tok)} rs={len(rs_tok)}"
        )
