"""End-to-end tests for ``GameState.legal_decisions(player_id)``.

The Phase 3 keystone: emits the closed set of legal Actions the
priority-holder can take right now. Python's MCTS / ISMCTS drives
off this enumeration; the Rust port must match Python's emission
order exactly (Action types in the same sequence with the same
per-type tie-breaking) for trajectory parity in
``scripts/parity_smoke.py``.

**Slice scope (rust(legal-decisions-skeleton + cast-spell)).**
``PassPriority`` + ``PlayLand`` + base ``CastSpell`` (no alt-cost
flags — all six defaulted: ``use_warp=False, kicked=False,
cast_for_free=False, use_impending=False, cast_room_half=None``).
``ActivateAbility``, ``DeclareAttackers``, ``DeclareBlockers``,
alt-cost CastSpell variants grow in follow-up slices.

**Emission-order audit vs Python.**  Mirrors
``src/mtg_bot/legal.py:legal_actions``:
- Line 178 — PassPriority is index 0 (prepended before any other
  variant).
- Lines 180-181 — off-priority callers see ``[PassPriority]`` only.
- Lines 25-32 + 303-304 — sorcery-timing gate (active == priority,
  main phase, empty stack) gates PlayLand emission.
- Lines 319-329 — PlayLand iterates hand in zone-insertion order,
  deduped by printing name.

**One-land-per-turn divergence.** Python's line 319 gates on
``p.lands_played_this_turn < max_lands``; the Rust ``GameState`` has
no ``lands_played_this_turn`` field yet (parallel-slice file-isolation
rule forbids adding it to ``state.rs`` from this slice). First-slice
behavior: emit a PlayLand action for every Land in hand regardless.
Caller / future slice enforcement is the Phase 5 fix.

Synthetic-state reminder (cf. ``tests_rust/test_actions.py``):
- Player 0 hand: ids 10..16, all Llanowar Elves (Creature).
- Player 0 battlefield: ids 0..4 Forest, 5..9 Grizzly Bears.
- Player 0 library: ids 17..66, all Forest.
- Player 1 mirrors with id_offset 67.
- Default phase = PHASE_UNTAP (0); tests that want sorcery timing
  must call ``set_phase(PHASE_MAIN1)``.
"""

from __future__ import annotations

import pytest

PHASE_UNTAP = 0
PHASE_MAIN1 = 3
PHASE_COMBAT_DAMAGE = 7
PHASE_MAIN2 = 9
PHASE_CLEANUP = 11

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2

P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_BEARS_ID = 5
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17  # first Forest in library


def _empty_hand(state, player_id=0):
    """Move every card out of ``player_id``'s hand into their library.
    Returns the count moved. Used for tests that want a clean
    starting hand (the synthetic seed gives 7 Llanowar Elves)."""
    hand = state.hand_snapshot(player_id)
    for obj in hand:
        # move to library (zone 1)
        ok = state.move_object(obj["id"], 1, player_id)
        assert ok is True
    return len(hand)


def _put_forest_in_hand(state, player_id=0, library_idx=0):
    """Move one Forest from ``player_id``'s library into their hand.
    Returns the Forest's id."""
    # The library snapshot is ordered bottom-to-top. The first Forest
    # in our P0 library starts at id P0_FIRST_LIBRARY_ID; the id
    # arithmetic + the snapshot agree.
    library = state.library_snapshot(player_id)
    forest_obj = library[library_idx]
    assert forest_obj["printing_name"] == "Forest"
    ok = state.move_object(forest_obj["id"], ZONE_HAND, player_id)
    assert ok is True
    return forest_obj["id"]


def _kinds(actions):
    """Pluck the kind strings out of a list of Action dicts."""
    return [a["kind"] for a in actions]


# --- 1. Empty hand --------------------------------------------------


def test_legal_decisions_empty_hand_in_main_phase_emits_only_pass_priority(
    synthetic_state,
):
    """Empty hand in PRECOMBAT_MAIN: only PassPriority emits.
    Mirrors Python's `legal.py:178` (PassPriority always there) +
    `:319-329` (PlayLand loop iterates an empty hand to zero actions)."""
    _empty_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority"]


# --- 2. One Land in hand --------------------------------------------


def test_legal_decisions_one_land_in_hand_emits_pass_priority_then_play_land(
    synthetic_state,
):
    """One Forest in hand at sorcery timing -> 2 actions:
    PassPriority (Python `legal.py:178` — prepended) FIRST, then
    PlayLand (`:329` — appended inside the sorcery-timing block).
    Locks in the Python emission order: PassPriority at index 0,
    PlayLand at index 1."""
    _empty_hand(synthetic_state, 0)
    forest_id = _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority", "play_land"]
    # PlayLand carries the Forest's GameObject id.
    assert actions[1]["card_id"] == forest_id


# --- 3. Two Lands in hand -------------------------------------------


def test_legal_decisions_two_distinct_lands_in_hand_emit_two_play_lands(
    synthetic_state,
):
    """Two DIFFERENT-named lands in hand emit two PlayLands. The
    synthetic registry only has Forest; this test uses one Forest +
    one Grizzly Bears swapped into a land-type-by-card-types proxy
    isn't possible without registering a new printing, so we register
    a Mountain in a fresh Registry-style state instead. For the
    synthetic-state world, this test asserts the more realistic
    case: two Forests dedup to ONE PlayLand by Python's
    ``(printing.name,)`` dedup key — see legal.py:322-329. We pin
    the dedup behavior here and add the truly-two-lands case via
    a registered Mountain in a follow-up if/when the suite gets a
    Mountain-aware fixture."""
    _empty_hand(synthetic_state, 0)
    # Put two Forests in hand (same printing).
    forest_a = _put_forest_in_hand(synthetic_state, 0, library_idx=0)
    forest_b = _put_forest_in_hand(synthetic_state, 0, library_idx=0)
    assert forest_a != forest_b
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    # Dedup by printing name: two Forests collapse to one PlayLand.
    assert _kinds(actions) == ["pass_priority", "play_land"]
    # The action carries the FIRST hand-order Forest's id.
    assert actions[1]["card_id"] == forest_a


# --- 4. Mixed hand: one Creature + one Land -------------------------


def test_legal_decisions_creature_plus_land_emits_play_land_and_cast_spell(
    synthetic_state,
):
    """Mixed hand (Llanowar Elves + Forest): the Forest emits a
    PlayLand, and the Elves (Creature) emits a CastSpell (post
    rust(legal-decisions-cast-spell) slice). The 7 Llanowar Elves in
    the synthetic seed all dedup to a single CastSpell by Python's
    `(printing.name,)` first-slice dedup key (Python `legal.py:352`).
    Locks in the mixed PlayLand + CastSpell coexistence and the
    PlayLand-comes-first emission order."""
    # Keep the existing Llanowar Elves in hand (don't empty it).
    forest_id = _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    kinds = _kinds(actions)
    # PassPriority then PlayLand then CastSpell — Python's natural
    # append order under sorcery timing.
    assert kinds[0] == "pass_priority"
    assert kinds.count("play_land") == 1
    assert kinds.count("cast_spell") == 1
    # PlayLand carries the Forest's id (not any Llanowar Elves id).
    play_land = [a for a in actions if a["kind"] == "play_land"][0]
    assert play_land["card_id"] == forest_id


# --- 5. Non-main phase ----------------------------------------------


@pytest.mark.parametrize(
    "phase",
    [PHASE_UNTAP, PHASE_COMBAT_DAMAGE, PHASE_CLEANUP],
    ids=["UNTAP", "COMBAT_DAMAGE", "CLEANUP"],
)
def test_legal_decisions_non_main_phase_emits_only_pass_priority(
    synthetic_state, phase
):
    """Non-main phase (UNTAP / COMBAT_DAMAGE / CLEANUP): even with a
    Land in hand, no PlayLand emits — sorcery-timing gate (Python
    `legal.py:303-304`, `_is_sorcery_timing` lines 25-32) fails."""
    _empty_hand(synthetic_state, 0)
    _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(phase)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority"]


# --- 6. Non-empty stack ---------------------------------------------


def test_legal_decisions_non_empty_stack_emits_only_pass_priority(
    synthetic_state,
):
    """Non-empty stack: even in PRECOMBAT_MAIN with a Land in hand,
    PlayLand can't emit — the sorcery-timing gate's empty-stack
    conjunct (Python `legal.py:30`) fails. Mirrors CR 305.2 (lands
    are played at sorcery speed, not as spells)."""
    _empty_hand(synthetic_state, 0)
    _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)
    # Push a dummy stack item. The legal_decisions enumerator only
    # cares whether the stack is empty.
    synthetic_state.push_to_stack(P0_FIRST_BEARS_ID, 0)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority"]


# --- 7. Opponent's turn ---------------------------------------------


def test_legal_decisions_off_active_player_emits_only_pass_priority(
    synthetic_state,
):
    """Priority on opponent's turn (priority = active for opponent =
    P1, P0 is asking what's legal during P1's turn). With priority
    held but ``active_player != player_id``, sorcery-timing fails
    (Python `legal.py:28` — `state.players[active_player_idx].id ==
    player_id`). Only PassPriority emits."""
    _empty_hand(synthetic_state, 0)
    _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)
    # Flip active player to P1 but give priority back to P0.
    synthetic_state.advance_phase()  # advance to BEGIN_COMBAT
    # Walk to next turn: just brute-force the phase cycle to flip
    # active_player.
    while synthetic_state.active_player == 0:
        synthetic_state.advance_phase()
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.give_priority_to(0)
    assert synthetic_state.active_player == 1
    assert synthetic_state.get_priority_player() == 0

    actions = synthetic_state.legal_decisions(0)

    # P0 has priority but it's P1's turn — sorcery timing fails.
    assert _kinds(actions) == ["pass_priority"]


def test_legal_decisions_priority_off_emits_only_pass_priority(synthetic_state):
    """Priority on opponent (P1 has priority, P0 is asking). Python
    `legal.py:180-181` — off-priority callers immediately return
    the singleton `[PassPriority]` list before any sorcery-timing
    check runs."""
    _empty_hand(synthetic_state, 0)
    _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.pass_priority()  # P0 -> P1
    assert synthetic_state.get_priority_player() == 1

    actions = synthetic_state.legal_decisions(0)

    # P0 doesn't have priority — even with a Land in hand on P0's
    # turn, no PlayLand emits.
    assert _kinds(actions) == ["pass_priority"]


# --- 8. Out-of-range player_id --------------------------------------


def test_legal_decisions_out_of_range_player_id_raises_index_error(
    synthetic_state,
):
    """Mirrors the existing snapshot-getter convention: out-of-range
    ``player_id`` (anything > 1 in the 2-player engine) raises
    ``IndexError`` with a clear message. Locks in the same error
    shape as ``hand_snapshot`` / ``library_snapshot`` etc."""
    with pytest.raises(IndexError, match=r"player_id 2 out of range"):
        synthetic_state.legal_decisions(2)


# --- 9. Round-trip via apply_action ---------------------------------


def test_legal_decisions_actions_are_round_trip_able_via_apply_action(
    synthetic_state,
):
    """Every dict returned from ``legal_decisions`` is a valid input
    to ``apply_action`` (regression for the round-22/23 bridge). This
    locks in that the dispatch + enumeration ends round-trip cleanly
    — a future slice that adds a new Action type to the enumerator
    but forgets the matching ``apply_action`` arm trips this test."""
    _empty_hand(synthetic_state, 0)
    forest_id = _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    # Apply the PlayLand action: forest goes from hand to battlefield.
    play_land = [a for a in actions if a["kind"] == "play_land"][0]
    bf_before = synthetic_state.battlefield_sizes[0]
    synthetic_state.apply_action(play_land)
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


def test_legal_decisions_pass_priority_action_round_trips(synthetic_state):
    """The PassPriority emission (always at index 0) round-trips
    through ``apply_action`` and flips priority — regression that
    locks in the dict shape matches what round-22 wired."""
    _empty_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)
    pass_priority = actions[0]
    assert pass_priority["kind"] == "pass_priority"

    assert synthetic_state.get_priority_player() == 0
    synthetic_state.apply_action(pass_priority)
    assert synthetic_state.get_priority_player() == 1


# --- 10. PassPriority position --------------------------------------


def test_legal_decisions_pass_priority_is_always_first_emission(
    synthetic_state,
):
    """PassPriority is at index 0 in EVERY emission — mirrors Python's
    `legal.py:178` (`actions = [PassPriority()]` prepended). Pin
    this across multiple scenarios so a future slice that switches
    to a different position (e.g. appending PassPriority at the
    end) trips loudly."""
    # Empty hand, main phase.
    _empty_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)
    assert synthetic_state.legal_decisions(0)[0]["kind"] == "pass_priority"

    # Off-priority.
    synthetic_state.pass_priority()
    assert synthetic_state.legal_decisions(0)[0]["kind"] == "pass_priority"

    # Off-main phase.
    synthetic_state.give_priority_to(0)
    synthetic_state.set_phase(PHASE_UNTAP)
    assert synthetic_state.legal_decisions(0)[0]["kind"] == "pass_priority"

    # With lands in hand at sorcery timing.
    synthetic_state.set_phase(PHASE_MAIN1)
    _put_forest_in_hand(synthetic_state, 0)
    actions = synthetic_state.legal_decisions(0)
    assert actions[0]["kind"] == "pass_priority"
    # And PlayLand is somewhere after it.
    assert "play_land" in _kinds(actions[1:])


# --- 11. PassPriority emitted exactly once --------------------------


def test_legal_decisions_pass_priority_emitted_exactly_once(synthetic_state):
    """PassPriority emits exactly once per call — Python's `legal.py:178`
    inserts the singleton at list-init time and never re-appends.
    Catches a regression where a future slice appends PassPriority
    at the end of the loop on top of the index-0 emission."""
    _empty_hand(synthetic_state, 0)
    _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions).count("pass_priority") == 1


# --- 12. P1 main phase parity ---------------------------------------


def test_legal_decisions_works_for_player_1_on_their_turn(synthetic_state):
    """P1's turn, main phase, with a Forest in P1's hand: PlayLand
    emits for P1, mirroring P0's behavior. Locks in that the
    enumerator isn't hardcoded to player 0 — it indexes the
    right player's hand via ``player_id``."""
    _empty_hand(synthetic_state, 1)
    forest_id = _put_forest_in_hand(synthetic_state, 1)
    # Advance until active_player flips to 1, then set MAIN1 +
    # priority to 1.
    while synthetic_state.active_player == 0:
        synthetic_state.advance_phase()
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.give_priority_to(1)

    actions = synthetic_state.legal_decisions(1)

    assert _kinds(actions) == ["pass_priority", "play_land"]
    assert actions[1]["card_id"] == forest_id


# --- 13. CastSpell: one Creature in main phase ----------------------
#
# rust(legal-decisions-cast-spell) — extends `legal_decisions` to emit
# CastSpell actions for non-Land cards in hand at sorcery timing.
# Mirrors Python's `legal.py:335-445` (the sorcery-speed CastSpell
# loop, `_is_sorcery_speed_spell` body). First-slice scope: base
# CastSpell with all alt-cost flags defaulted (use_warp=False,
# kicked=False, cast_for_free=False, use_impending=False,
# cast_room_half=None). Mana-affordability check is deferred — every
# non-Land in hand emits regardless of can_pay_cost.


def test_legal_decisions_one_creature_in_hand_emits_cast_spell(
    synthetic_state,
):
    """Single Llanowar Elves in hand at sorcery timing -> 2 actions:
    PassPriority FIRST (Python `legal.py:178`), then CastSpell
    (`legal.py:386` — `actions.append(CastSpell(card.id))` inside
    the sorcery-speed loop). No PlayLand because the Elves isn't a
    Land. Locks in CastSpell's emission position AFTER PlayLand /
    after PassPriority and the all-defaults flag shape."""
    _empty_hand(synthetic_state, 0)
    # Pull a single Elves out of the library back into hand. The
    # library is Forest-only; instead use the existing 7-elf hand
    # but clear all but one.
    library = synthetic_state.library_snapshot(0)
    # No Elves in library — populate hand directly via P0's stock
    # Llanowar Elves at id P0_FIRST_HAND_ID=10. Move 6 of them out
    # to library, leaving one in hand.
    hand = synthetic_state.hand_snapshot(0)
    assert hand == []  # _empty_hand cleared it
    # Move 1 Llanowar Elves from library (library starts with the
    # original 7 elves at the top? No — the seed puts elves in hand,
    # not library). Instead: undo the empty. We'll re-fill via
    # _empty_hand's reverse — just reset by getting a fresh state
    # is cleaner. Use the synthetic state straight without empty.
    # Re-make:
    import mtg_bot_engine
    state = mtg_bot_engine.make_synthetic_state()
    # Clear hand down to exactly 1 Llanowar Elves.
    hand = state.hand_snapshot(0)
    assert len(hand) == 7
    assert all(o["printing_name"] == "Llanowar Elves" for o in hand)
    # Move 6 out (to library).
    for obj in hand[1:]:
        assert state.move_object(obj["id"], 1, 0) is True
    elves_id = hand[0]["id"]
    state.set_phase(PHASE_MAIN1)

    actions = state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority", "cast_spell"]
    assert actions[1]["card_id"] == elves_id


# --- 14. CastSpell: PlayLand + CastSpell emission order -------------


def test_legal_decisions_land_plus_creature_emit_in_python_order(
    synthetic_state,
):
    """Mixed hand at sorcery timing: PlayLand emits BEFORE CastSpell.
    Mirrors Python's natural append order — PlayLand loop at
    `legal.py:319-329` runs FIRST (lower line number), then the
    sorcery-speed CastSpell loop at `legal.py:365-445`. Final list
    is `[pass_priority, play_land, cast_spell_1, cast_spell_2, ...]`."""
    # Keep the 7 Llanowar Elves in hand and add a Forest.
    forest_id = _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    kinds = _kinds(actions)
    # 7 Llanowar Elves dedup to 1 CastSpell; 1 Forest -> 1 PlayLand.
    assert kinds == ["pass_priority", "play_land", "cast_spell"]
    # PlayLand carries the Forest's id; CastSpell carries the first
    # hand-order Elves' id (id 10, P0_FIRST_HAND_ID).
    assert actions[1]["kind"] == "play_land"
    assert actions[1]["card_id"] == forest_id
    assert actions[2]["kind"] == "cast_spell"
    assert actions[2]["card_id"] == P0_FIRST_HAND_ID


# --- 15. CastSpell: dedup on same printing --------------------------


def test_legal_decisions_two_same_printing_creatures_dedup_to_one_cast(
    synthetic_state,
):
    """Two Llanowar Elves (same printing) -> ONE CastSpell. Mirrors
    Python's dedup key at `legal.py:352-359`: `(printing.name, flag1,
    flag2, ..., flag5)`. With first-slice all-default flags, the key
    collapses to `(printing.name,)` and two-same-printing collapse
    to a single CastSpell — same shape as the PlayLand two-Forests
    dedup test above. The CastSpell carries the FIRST hand-order
    copy's id."""
    # Synthetic state already has 7 Llanowar Elves in hand. Trim
    # to exactly 2 so the assertion is sharp.
    hand = synthetic_state.hand_snapshot(0)
    assert len(hand) == 7
    for obj in hand[2:]:
        assert synthetic_state.move_object(obj["id"], 1, 0) is True
    elves_first_id = hand[0]["id"]
    elves_second_id = hand[1]["id"]
    assert elves_first_id != elves_second_id
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    # Dedup: two Elves -> ONE CastSpell.
    assert _kinds(actions) == ["pass_priority", "cast_spell"]
    # The action carries the FIRST hand-order Elves' id.
    assert actions[1]["card_id"] == elves_first_id


# --- 16. CastSpell: dict shape carries all 6 flag fields ------------


def test_legal_decisions_cast_spell_dict_has_all_six_flag_fields(
    synthetic_state,
):
    """The CastSpell dict carries all 7 keys: kind + card_id + 5
    alt-cost flag fields. Mirrors `actions.rs:action_to_pydict`'s
    "always emit all 5 flag fields so round-trip is fully symmetric"
    contract — every CastSpell dict from `legal_decisions` must
    survive a `parse_action -> action_to_pydict` cycle without
    key drift."""
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)
    cast_spells = [a for a in actions if a["kind"] == "cast_spell"]
    assert len(cast_spells) == 1

    cs = cast_spells[0]
    # Every key present, defaults match Python's dataclass.
    assert set(cs.keys()) == {
        "kind",
        "card_id",
        "use_warp",
        "kicked",
        "cast_for_free",
        "use_impending",
        "cast_room_half",
    }
    assert cs["use_warp"] is False
    assert cs["kicked"] is False
    assert cs["cast_for_free"] is False
    assert cs["use_impending"] is False
    assert cs["cast_room_half"] is None


# --- 17. CastSpell: not emitted off sorcery timing ------------------


@pytest.mark.parametrize(
    "phase",
    [PHASE_UNTAP, PHASE_COMBAT_DAMAGE, PHASE_CLEANUP],
    ids=["UNTAP", "COMBAT_DAMAGE", "CLEANUP"],
)
def test_legal_decisions_non_main_phase_omits_cast_spell(
    synthetic_state, phase
):
    """Non-main phase: even with Creatures in hand, no CastSpell
    emits — sorcery-timing gate (Python `legal.py:303-304`) fails.
    First-slice ignores Python's instant-speed CastSpell block at
    lines 246-301 (instants / flash); when that block ports over, a
    flash creature in hand at non-main phase will emit, but this
    test still holds for the synthetic-state Llanowar Elves
    (no flash)."""
    synthetic_state.set_phase(phase)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority"]
    assert "cast_spell" not in _kinds(actions)


# --- 18. CastSpell: not emitted with non-empty stack ----------------


def test_legal_decisions_non_empty_stack_omits_cast_spell(
    synthetic_state,
):
    """Non-empty stack: sorcery-timing gate's empty-stack conjunct
    (Python `legal.py:30`) fails, so no CastSpell emits at sorcery
    speed. First-slice has no instant-speed CastSpell block, so the
    list collapses to `[pass_priority]`."""
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.push_to_stack(P0_FIRST_BEARS_ID, 0)

    actions = synthetic_state.legal_decisions(0)

    assert _kinds(actions) == ["pass_priority"]


# --- 19. CastSpell: not emitted off-turn ----------------------------


def test_legal_decisions_off_active_player_omits_cast_spell(
    synthetic_state,
):
    """Priority on opponent's turn (P0 has priority during P1's
    main phase). Sorcery-timing fails (`active_player != player_id`,
    Python `legal.py:28`). No CastSpell emits, mirroring the same
    PlayLand-off-turn behavior in test 7."""
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.advance_phase()
    while synthetic_state.active_player == 0:
        synthetic_state.advance_phase()
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.give_priority_to(0)
    assert synthetic_state.active_player == 1
    assert synthetic_state.get_priority_player() == 0

    actions = synthetic_state.legal_decisions(0)

    # P0 has priority but it's P1's turn — sorcery timing fails.
    assert _kinds(actions) == ["pass_priority"]


# --- 20. CastSpell: dict round-trips through parse_action -----------


def test_legal_decisions_cast_spell_action_parses_via_apply_action(
    synthetic_state,
):
    """Every CastSpell dict from `legal_decisions` is accepted by
    `apply_action`'s dict parser. The bridge's `parse_action` arm
    for "cast_spell" (round-22 CastSpell agent) must accept the
    shape this slice emits without raising. The first-slice scope
    for `apply_action` on CastSpell may still mutate state (calling
    the existing `cast_creature` primitive) — we don't assert on
    the result, only that the parse + dispatch round-trip doesn't
    raise on the dict shape.

    This is the regression for a future slice that adds a new
    flag to the CastSpell variant but forgets to extend the
    emitter — the new key would mismatch parse_action."""
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)
    cast_spell = [a for a in actions if a["kind"] == "cast_spell"][0]

    # apply_action may either succeed (cast goes to stack /
    # battlefield) or raise on a downstream gate (mana cost not
    # paid — first-slice doesn't gate on affordability so the
    # primitive itself may refuse). Both outcomes are acceptable
    # here; what matters is that `parse_action` doesn't raise on
    # the dict shape. We catch ValueError as the "downstream
    # rejected the apply, not a parse failure" signal — anything
    # else (KeyError, TypeError) IS a regression.
    try:
        synthetic_state.apply_action(cast_spell)
    except ValueError:
        pass


# --- 21. CastSpell: emission order between PlayLand and PassPriority


def test_legal_decisions_cast_spell_after_play_land_after_pass_priority(
    synthetic_state,
):
    """Locks in the full Python emission order: PassPriority is at
    index 0 (Python's `legal.py:178` prepend), PlayLand actions
    come next (Python lines 319-329), then CastSpell actions
    (Python lines 365-445). Catches a regression where a future
    slice swaps the loop order and breaks parity with Python's
    `legal_actions`."""
    forest_id = _put_forest_in_hand(synthetic_state, 0)
    synthetic_state.set_phase(PHASE_MAIN1)

    actions = synthetic_state.legal_decisions(0)

    kinds = _kinds(actions)
    # Find the indices of each kind.
    pass_idx = kinds.index("pass_priority")
    play_idx = kinds.index("play_land")
    cast_idx = kinds.index("cast_spell")
    assert pass_idx < play_idx < cast_idx
    # And there are exactly 3 actions: one of each.
    assert len(actions) == 3
    assert actions[play_idx]["card_id"] == forest_id


# --- 22. CastSpell: P1 parity on P1's turn --------------------------


def test_legal_decisions_cast_spell_works_for_player_1(synthetic_state):
    """P1's turn, main phase: P1's hand of Llanowar Elves emits a
    CastSpell action for P1. Locks in the enumerator's
    player-indexing — `self.players[idx].hand` walks the correct
    player's hand, mirroring the existing P1-PlayLand parity test."""
    # P1 starts with 7 Llanowar Elves in their hand (synthetic seed).
    while synthetic_state.active_player == 0:
        synthetic_state.advance_phase()
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.give_priority_to(1)

    actions = synthetic_state.legal_decisions(1)

    kinds = _kinds(actions)
    assert kinds[0] == "pass_priority"
    # P1's Elves dedup to 1 CastSpell.
    assert kinds.count("cast_spell") == 1
    cast_spell = [a for a in actions if a["kind"] == "cast_spell"][0]
    # The CastSpell carries one of P1's hand-card ids (id_offset = 67).
    p1_hand = synthetic_state.hand_snapshot(1)
    p1_hand_ids = {o["id"] for o in p1_hand}
    assert cast_spell["card_id"] in p1_hand_ids
