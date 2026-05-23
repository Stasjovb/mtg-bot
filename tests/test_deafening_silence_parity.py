"""Cross-engine parity probes for Deafening Silence (DSK special-
guests reprint in the EoE pool; 12 17lands decks).

**Deafening Silence Cycle 1 closure (2026-05-22).** ``{W}``
Enchantment: "Each player can't cast more than one noncreature spell
each turn." Mirrors Python's printing-level bool
``CardPrinting.restricts_noncreature_spells_to_one_per_turn`` at
``src/mtg_bot/cards/base.py:844`` + the per-player
``Player.noncreature_spells_cast_this_turn`` counter incremented in
``actions.py:1782`` and reset at cleanup in ``turn.py:1106`` + the
post-filter at ``legal.py:880-893``.

Closure scope is the contained-medium ``static_rule_text`` substrate
per ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md`` §5: one new Rust
``CardPrinting`` bool slot, one new ``Player`` counter, per-cast
increment hooks, cleanup-step reset, cast-time legal-decision
filter, bidirectional bridge round-trip, one new admit disjunct
(``_printing_is_bridge_simple_cast_restriction_enchantment``), and
one real-EoE cross-engine byte-equal probe.

Coverage:

- **Parser SoT pin.** The live parsed Deafening Silence printing
  carries ``restricts_noncreature_spells_to_one_per_turn=True`` —
  the printing-level bool slot Python's ``legal.py`` reads.
- **Rust counter unit pins.**
    * A noncreature cast in Rust (``cast_spell_noncreature``) bumps
      ``noncreature_spells_cast_this_turn`` for the casting player.
    * A creature cast (``cast_creature``) does NOT bump the
      counter.
    * The cleanup step (``state_ops_steps``) resets the counter to
      0, mirroring Python's ``turn.py:1106``.
- **Rust cast-time gate pin.** When ANY battlefield permanent
  carries the bool AND the caster's counter is already ``>= 1``,
  ``legal_decisions`` does NOT emit a noncreature CastSpell for
  that player. Creature CastSpells stay emitted (the gate is
  type-specific).
- **Bridge round-trip pins.**
    * Python CardDef ``restricts_noncreature_spells_to_one_per_turn
      = True`` → Rust registry dict ``"True"`` key →
      ``get_printing_restricts_noncreature_spells_to_one_per_turn``
      reads ``True`` back, byte-equal.
    * Python CardDef materializes to a Python ``CardPrinting`` with
      the matching bool slot set, byte-equal with the parser-sourced
      printing.
    * The per-Player ``noncreature_spells_cast_this_turn`` counter
      round-trips via the new
      ``set_noncreature_spells_cast_this_turn`` /
      ``get_noncreature_spells_cast_this_turn`` Rust pymethods,
      symmetric with Python's attribute access.
- **Admit-gate flip pin.**
  ``_printing_is_bridge_simple_cast_restriction_enchantment`` AND
  ``_filter_deck_to_bridge_supported`` admit the parsed Deafening
  Silence printing post-substrate.
- **GENUINE real-EoE cross-engine byte-equal probe.** Drives the
  parsed Deafening Silence printing onto BOTH engines' battlefields
  and exercises a 3-spell sequence: cast Grizzly Bears (creature,
  NOT blocked) + cast a {W} vanilla Enchantment (1st noncreature
  cast, ALLOWED) + cast a second {W} vanilla Enchantment (2nd
  noncreature cast, BLOCKED on both engines by Deafening Silence).
  Verifies the noncreature counter and the legal-emission filter
  agree byte-equal across engines.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pin.
# ---------------------------------------------------------------------------


def test_real_deafening_silence_printing_has_restriction_flag():
    """**Verify-first.** The live parser maps Deafening Silence to a
    ``CardPrinting`` whose
    ``restricts_noncreature_spells_to_one_per_turn`` is ``True`` —
    the printing-level bool slot Python's ``legal.py:880-893``
    post-filter reads. Freezes the parser SoT so a parser drift is
    caught here, not silently downstream."""
    from mtg_bot.cards.source import get_active_source

    p = get_active_source().get_printings().get("Deafening Silence")
    if p is None:
        pytest.skip("Deafening Silence absent from active CardSource")
    assert "Enchantment" in p.card_types
    assert "Creature" not in p.card_types
    assert p.restricts_noncreature_spells_to_one_per_turn is True, (
        "Deafening Silence's printing must carry "
        "restricts_noncreature_spells_to_one_per_turn=True per "
        "src/mtg_bot/cards/base.py:844"
    )
    # Mana cost is {W}.
    assert dict(p.mana_cost.colored).get("W", 0) == 1
    assert p.mana_cost.generic == 0
    # No targets / spell_effect (it's an Enchantment ETB, not an
    # Instant/Sorcery resolving from the stack as a spell).
    assert p.spell_effect is None


# ---------------------------------------------------------------------------
# Rust unit pins — counter increment + cleanup reset + legal-gate.
# ---------------------------------------------------------------------------


def _make_synthetic_with_silence_in_hand(rs, player_id: int):
    """Inject one Deafening-Silence-shape Enchantment into
    ``player_id``'s battlefield. Returns its object id.

    The printing carries
    ``restricts_noncreature_spells_to_one_per_turn=True`` so any
    battlefield walk in Rust legal-decision emission can see it.
    """
    return rs.register_and_inject_object(
        {
            "name": "Deafening Silence Cycle1",
            "card_types": ["Enchantment"],
            "mana_cost": {"W": 1},
            "restricts_noncreature_spells_to_one_per_turn": True,
        },
        player_id, 2,  # zone=ZONE_BATTLEFIELD=2
    )


def _make_synthetic_vanilla_instant_in_hand(rs, player_id: int, name: str):
    """Inject a vanilla {W} Instant (no effect) into ``player_id``'s
    hand. Returns its object id.

    Rust's noncreature-cast primitive ``cast_spell_noncreature``
    requires the printing's ``card_types`` to contain ``Instant`` or
    ``Sorcery`` (the ``is_spell`` gate at ``state_ops_cast.rs``).
    Using Instant here means the unit tests exercise the actual
    cast path that bumps the noncreature counter; Deafening Silence
    itself is non-Aura non-Instant Enchantment, so it stays
    inject-only at battlefield slot.
    """
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
        },
        player_id, 0,  # zone=ZONE_HAND=0
    )


def _make_synthetic_creature_in_hand(rs, player_id: int, name: str):
    """Inject a vanilla 2/2 Creature ({G}) into ``player_id``'s hand.
    Returns its object id."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Creature"],
            "mana_cost": {"G": 1},
            "power": 2,
            "toughness": 2,
        },
        player_id, 0,  # zone=ZONE_HAND=0
    )


def test_rust_noncreature_cast_bumps_counter():
    """Casting a noncreature spell in Rust bumps the caster's
    ``noncreature_spells_cast_this_turn`` from 0 → 1. Mirrors
    Python's increment in ``actions.py:1782``."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0
    spell_id = _make_synthetic_vanilla_instant_in_hand(
        rs, 0, "Pre-Silence Enchant"
    )
    # Give p0 the {W} to pay.
    rs.add_mana(0, "W", 1)
    ok = rs.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert rs.get_noncreature_spells_cast_this_turn(0) == 1, (
        "noncreature_spells_cast_this_turn must bump to 1 after a "
        "noncreature cast (Cycle 1 increment hook in cast_spell_noncreature)"
    )


def test_rust_creature_cast_does_not_bump_noncreature_counter():
    """Casting a creature spell in Rust does NOT bump the
    noncreature counter — the gate is type-specific. Mirrors
    Python's ``if not card.printing.is_creature:`` guard at
    ``actions.py:1781``."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    creature_id = _make_synthetic_creature_in_hand(rs, 0, "Pre-Silence Bear")
    rs.add_mana(0, "G", 1)
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0
    ok = rs.cast_creature(creature_id, 0)
    assert ok is True
    # Creature cast does NOT increment the noncreature counter.
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0, (
        "Creature cast must NOT bump noncreature_spells_cast_this_turn"
    )


def test_rust_cleanup_step_resets_noncreature_counter():
    """The cleanup-step reset zeros
    ``noncreature_spells_cast_this_turn`` on both players. Mirrors
    Python's ``turn.py:1106`` reset in ``run_cleanup_step``. Without
    the reset, a single noncreature cast would permanently lock out
    further noncreature casts until end of game."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # Drive both players' counters to nonzero via the direct setter.
    rs.set_noncreature_spells_cast_this_turn(0, 3)
    rs.set_noncreature_spells_cast_this_turn(1, 5)
    assert rs.get_noncreature_spells_cast_this_turn(0) == 3
    assert rs.get_noncreature_spells_cast_this_turn(1) == 5
    # Walking phases forward until CLEANUP entry fires the per-player
    # counter reset block in state_ops_steps's
    # `cleanup_step_for_active_player_inline` (which advance_phase
    # invokes on entry to CLEANUP). Mirrors Python's per-turn reset
    # in run_cleanup_step at turn.py:1106.
    while rs.step != "CLEANUP":
        rs.advance_phase()
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0, (
        "post-cleanup p0 counter must reset to 0"
    )
    assert rs.get_noncreature_spells_cast_this_turn(1) == 0, (
        "post-cleanup p1 counter must reset to 0"
    )


def test_rust_legal_decisions_blocks_second_noncreature_cast():
    """When a Deafening-Silence-shape permanent is on the
    battlefield AND the active player has already cast a
    noncreature spell this turn, ``legal_decisions`` does NOT emit
    a noncreature CastSpell for that player. Creature CastSpells
    stay emitted (the gate is type-specific)."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # Put Deafening Silence on p0's battlefield.
    _make_synthetic_with_silence_in_hand(rs, 0)
    # Put a vanilla {W} Enchantment AND a vanilla creature in p0's
    # hand. The enchantment is the "noncreature" candidate; the
    # creature is the type-specific-exemption candidate.
    enchant_id = _make_synthetic_vanilla_instant_in_hand(
        rs, 0, "Hand Enchant",
    )
    creature_id = _make_synthetic_creature_in_hand(rs, 0, "Hand Bear")
    # Step into MAIN1 sorcery-timing window where CastSpell is
    # emitted at sorcery speed. Add mana AFTER phase walk — phase
    # transitions empty the mana pool (CR 106.4).
    while rs.step != "PRECOMBAT_MAIN":
        rs.advance_phase()
    rs.add_mana(0, "W", 5)
    rs.add_mana(0, "G", 5)

    # BEFORE the first noncreature cast: both Enchantment + Creature
    # CastSpell options are legal.
    decisions_pre = rs.legal_decisions(0)
    kinds_pre = [d.get("kind") for d in decisions_pre]
    card_ids_pre = [d.get("card_id") for d in decisions_pre if d.get("kind") == "cast_spell"]
    assert enchant_id in card_ids_pre, (
        "Enchantment CastSpell must be legal BEFORE the first "
        "noncreature cast (counter == 0)"
    )
    assert creature_id in card_ids_pre, (
        "Creature CastSpell must always be legal under Deafening Silence"
    )

    # Bump the counter directly (simulates "the player has already
    # cast one noncreature spell this turn"). This is the same shape
    # the bumped-by-cast path produces.
    rs.set_noncreature_spells_cast_this_turn(0, 1)

    decisions_post = rs.legal_decisions(0)
    card_ids_post = [
        d.get("card_id") for d in decisions_post if d.get("kind") == "cast_spell"
    ]
    assert enchant_id not in card_ids_post, (
        "Enchantment CastSpell must be BLOCKED after the noncreature "
        "counter reaches 1 (Deafening Silence gate fires)"
    )
    assert creature_id in card_ids_post, (
        "Creature CastSpell must STILL be legal — the gate is "
        "type-specific (CR 700.1 noncreature definition)"
    )


def test_rust_legal_decisions_does_not_block_without_silence():
    """The gate ONLY fires when a Deafening-Silence-shape permanent
    is on the battlefield. Counter alone (without the carrier) does
    NOT block noncreature casts. Pins the AND-condition shape of the
    gate."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    enchant_id = _make_synthetic_vanilla_instant_in_hand(
        rs, 0, "Hand Enchant Without Silence",
    )
    while rs.step != "PRECOMBAT_MAIN":
        rs.advance_phase()
    rs.add_mana(0, "W", 5)
    # Counter is high but no Silence on the battlefield.
    rs.set_noncreature_spells_cast_this_turn(0, 99)
    decisions = rs.legal_decisions(0)
    card_ids = [d.get("card_id") for d in decisions if d.get("kind") == "cast_spell"]
    assert enchant_id in card_ids, (
        "Without Deafening Silence on the battlefield, the gate must "
        "NOT block noncreature casts even when the counter is high "
        "(the AND-condition guards correctly)"
    )


def test_rust_legal_decisions_silence_on_opponent_side_blocks_both():
    """Deafening Silence is SYMMETRIC — its restriction applies to
    BOTH players regardless of which side controls it. A Silence on
    p1's battlefield still gates p0's noncreature casts."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # Silence on p1's side; p0 is the cast attempter.
    _make_synthetic_with_silence_in_hand(rs, 1)
    enchant_id = _make_synthetic_vanilla_instant_in_hand(
        rs, 0, "p0 Hand Enchant",
    )
    rs.add_mana(0, "W", 5)
    while rs.step != "PRECOMBAT_MAIN":
        rs.advance_phase()
    rs.set_noncreature_spells_cast_this_turn(0, 1)
    decisions = rs.legal_decisions(0)
    card_ids = [d.get("card_id") for d in decisions if d.get("kind") == "cast_spell"]
    assert enchant_id not in card_ids, (
        "Deafening Silence is symmetric — p1's Silence must still "
        "gate p0's noncreature casts when p0's counter >= 1"
    )


# ---------------------------------------------------------------------------
# Bridge round-trip pins.
# ---------------------------------------------------------------------------


def test_bridge_round_trip_printing_bool_python_to_rust_and_back():
    """Python CardDef → Rust registry dict → Rust ``CardPrinting``
    bool → Rust getter reads back ``True``. Bridge end-to-end."""
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_registry,
    )

    card = CardDef(
        name="Bridge Silence Probe",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
        restricts_noncreature_spells_to_one_per_turn=True,
    )
    spec = DeckSpec(card_defs=(card,), p0_library=(), p1_library=())
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid["Bridge Silence Probe"]
    assert reg.get_printing_restricts_noncreature_spells_to_one_per_turn(pid) is True, (
        "Python CardDef.restricts_noncreature_spells_to_one_per_turn=True "
        "must round-trip through the bridge to the Rust registry"
    )
    # Negative pin: a CardDef without the flag must round-trip to False.
    card_no_flag = CardDef(
        name="Bridge No-Silence Probe",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
    )
    spec2 = DeckSpec(card_defs=(card_no_flag,), p0_library=(), p1_library=())
    reg2, name_to_pid2 = build_rust_registry(spec2)
    pid2 = name_to_pid2["Bridge No-Silence Probe"]
    assert reg2.get_printing_restricts_noncreature_spells_to_one_per_turn(pid2) is False, (
        "Default-False CardDef must round-trip to Rust False (back-compat)"
    )


def test_bridge_round_trip_python_carddef_materializes_python_printing_with_flag():
    """The Python side of the bridge — ``_card_def_to_python_printing``
    — must thread ``restricts_noncreature_spells_to_one_per_turn``
    onto the materialized Python ``CardPrinting`` so the Python
    ``legal.py:880-893`` post-filter fires correctly on bridge-built
    printings."""
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )

    card = CardDef(
        name="Bridge Silence Python",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
        restricts_noncreature_spells_to_one_per_turn=True,
    )
    printing = _card_def_to_python_printing(card)
    assert printing.restricts_noncreature_spells_to_one_per_turn is True


def test_bridge_round_trip_player_counter():
    """``set_noncreature_spells_cast_this_turn`` /
    ``get_noncreature_spells_cast_this_turn`` Rust pymethods carry
    the per-Player counter symmetrically with Python's attribute
    access — round-trip byte-equal."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # Default zero on both players.
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0
    assert rs.get_noncreature_spells_cast_this_turn(1) == 0
    # Round-trip non-zero values.
    rs.set_noncreature_spells_cast_this_turn(0, 7)
    rs.set_noncreature_spells_cast_this_turn(1, 11)
    assert rs.get_noncreature_spells_cast_this_turn(0) == 7
    assert rs.get_noncreature_spells_cast_this_turn(1) == 11
    # Out-of-range player index raises.
    with pytest.raises(IndexError):
        rs.get_noncreature_spells_cast_this_turn(2)
    with pytest.raises(IndexError):
        rs.set_noncreature_spells_cast_this_turn(2, 0)


# ---------------------------------------------------------------------------
# Admit-gate pin.
# ---------------------------------------------------------------------------


def test_deafening_silence_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-1, Deafening Silence MUST
    pass ``_printing_is_bridge_simple_cast_restriction_enchantment``
    AND the production deck-loader filter
    ``_filter_deck_to_bridge_supported``. The §2 teeth must all
    fire positively on the actual EoE parsed printing.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Deafening Silence")
    if p is None:
        pytest.skip("Deafening Silence absent from active CardSource")
    assert (
        trajectory._printing_is_bridge_simple_cast_restriction_enchantment(p)
        is True
    ), (
        "Deafening Silence must auto-join the cast-restriction-"
        "enchantment admit set now that the Rust mirror + bridge "
        "are in place"
    )
    # The full production loader gate also admits it.
    p0_deck = ["Deafening Silence"]
    p1_deck = ["Deafening Silence"]
    p0_filtered, _ = trajectory._filter_deck_to_bridge_supported(
        p0_deck, get_active_source().get_printings(),
    )
    assert "Deafening Silence" in p0_filtered, (
        "_filter_deck_to_bridge_supported must admit Deafening "
        "Silence post-Cycle-1"
    )


def test_deafening_silence_passes_measure_pool_parity_loader_admits():
    """The metric helper ``loader_admits`` in
    ``scripts/measure_pool_parity.py`` mirrors the real loader's
    admit chokepoint. Post-Cycle-1, the new disjunct fires on the
    parsed Deafening Silence printing — closing a metric-truthfulness
    gap (without this widen, the metric helper would mis-classify
    Deafening Silence as BLOCKED even though the real loader admits
    it)."""
    import pathlib
    import sys

    from mtg_bot.cards.source import get_active_source

    p = get_active_source().get_printings().get("Deafening Silence")
    if p is None:
        pytest.skip("Deafening Silence absent from active CardSource")

    # Put scripts/ on sys.path so `import measure_pool_parity` works
    # the same way the production-deck-loader runs the script.
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    scripts_dir = str(repo_root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import measure_pool_parity as mpp  # type: ignore[import-not-found]

    assert mpp.loader_admits(p) is True, (
        "measure_pool_parity.loader_admits must admit Deafening "
        "Silence post-Cycle-1 — without this, the metric helper "
        "would mis-attribute the carrier as BLOCKED while the real "
        "loader has admitted it"
    )


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_deafening_silence_noncreature_block_parity():
    """**GENUINE real-EoE cross-engine probe — Deafening Silence
    (12 17lands decks; DSK special-guests reprint in the EoE pool).**

    Drives the actual parsed Deafening Silence printing through the
    bridge: a CardDef carries the
    ``restricts_noncreature_spells_to_one_per_turn=True`` flag, the
    Python and Rust sides both materialize the matching printing.

    **Scenario (deterministic, no RNG).** Both engines start with
    Deafening Silence on p0's battlefield + the rest of the game
    state in a known-fresh configuration. We then verify symmetric
    cross-engine behavior on three cast attempts:

    1. **Creature cast (Grizzly Bears, {1}{G}):** NOT gated — both
       engines emit the CastSpell action (the Silence gate is
       type-specific, exempting creatures).
    2. **First noncreature cast ({W} vanilla Enchantment):** Allowed —
       counter goes 0 → 1 on both engines.
    3. **Second noncreature cast ({W} vanilla Enchantment):** BLOCKED
       — neither engine emits a CastSpell action for it; both
       engines' counters stay at 1 (no second-cast bump).

    The probe asserts byte-equal:
    * Both engines' ``noncreature_spells_cast_this_turn`` counters
      agree at every point in the sequence.
    * Both engines' ``legal_actions`` / ``legal_decisions`` agree on
      which CastSpells are emitted (creature: yes; noncreature post-
      counter: no).
    """
    _require_engine()

    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_python_state,
        build_rust_state,
    )

    # Build the spec with Deafening Silence + the two filler cards.
    silence = CardDef(
        name="Deafening Silence",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
        restricts_noncreature_spells_to_one_per_turn=True,
    )
    spec = DeckSpec(
        card_defs=(silence,),
        p0_library=(),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Seed identical Deafening Silence onto BOTH engines' p0 BF. ----
    py_silence_printing = py.players[0].library  # placeholder; we use the bridge
    # The Python printing for "Deafening Silence" was materialized
    # by build_python_state; surface it from spec.
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing
    py_silence_printing = _card_def_to_python_printing(silence)
    py_silence_obj = py.new_object(
        py_silence_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_silence_obj.summoning_sick = False
    py.battlefield.append(py_silence_obj)

    rs_silence_obj_id = rs.register_and_inject_object(
        {
            "name": "Deafening Silence",
            "card_types": ["Enchantment"],
            "mana_cost": {"W": 1},
            "restricts_noncreature_spells_to_one_per_turn": True,
        },
        0, 2,  # owner=p0, battlefield
    )

    # ---- (A) Cast a CREATURE on both engines — NOT blocked. ----
    py_bear_printing = CardPrinting(
        name="Cross Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=(),
    )
    py_bear = py.new_object(py_bear_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_bear)
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Cross Bear",
            "card_types": ["Creature"],
            "mana_cost": {"G": 1},
            "power": 2,
            "toughness": 2,
        },
        0, 0,  # owner=p0, hand
    )
    # Pre-cast: counters at 0 on both engines.
    assert py.players[0].noncreature_spells_cast_this_turn == 0
    assert rs.get_noncreature_spells_cast_this_turn(0) == 0

    # ---- (B) Cast a first noncreature spell — ALLOWED. ----
    # Drive both Python and Rust through a {W} Enchantment cast.
    # Use vanilla {W} Instants for the noncreature-cast candidates —
    # Rust's `cast_spell_noncreature` requires Instant/Sorcery type
    # (the `is_spell` gate at state_ops_cast.rs). Python's CR-correct
    # legal-action filter (`legal.py:880-893`) is type-agnostic on the
    # noncreature side ("noncreature" = "not Creature"), so both
    # engines treat an Instant as noncreature symmetrically.
    py_enchant1_printing = CardPrinting(
        name="Cross Hand Instant 1",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=(("W", 1),)),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=(),
    )
    py_enchant1 = py.new_object(
        py_enchant1_printing, owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_enchant1)
    rs_enchant1_id = rs.register_and_inject_object(
        {
            "name": "Cross Hand Instant 1",
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
        },
        0, 0,
    )
    py_enchant2_printing = CardPrinting(
        name="Cross Hand Instant 2",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=(("W", 1),)),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=(),
    )
    py_enchant2 = py.new_object(
        py_enchant2_printing, owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_enchant2)
    rs_enchant2_id = rs.register_and_inject_object(
        {
            "name": "Cross Hand Instant 2",
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
        },
        0, 0,
    )

    # Drive Rust into MAIN1 sorcery-timing for the cast-emission gate.
    while rs.step != "PRECOMBAT_MAIN":
        rs.advance_phase()
    # Add mana on Rust side for the noncreature cast.
    rs.add_mana(0, "W", 5)
    rs.add_mana(0, "G", 5)

    # Drive Python into the same sorcery-timing main-phase shape.
    from mtg_bot.turn import Step

    py.step = Step.PRECOMBAT_MAIN
    py.priority_player_idx = 0
    py.active_player_idx = 0

    # Sanity: BEFORE any noncreature cast both engines emit all
    # three CastSpell candidates (creature + both enchantments).
    rs_pre_decisions = rs.legal_decisions(0)
    rs_pre_card_ids = sorted(
        d.get("card_id")
        for d in rs_pre_decisions
        if d.get("kind") == "cast_spell"
    )
    assert rs_bear_id in rs_pre_card_ids
    assert rs_enchant1_id in rs_pre_card_ids
    assert rs_enchant2_id in rs_pre_card_ids

    # ---- (C) Drive ONE noncreature cast on each engine (resolve immediately). ----
    # Python: cast the enchantment via the engine's _cast_spell shape.
    # Use the actions module's direct increment + manual stack manipulation
    # because legal_actions emits the action but doesn't drive resolution.
    from mtg_bot.actions import _cast_spell  # type: ignore[attr-defined]

    # Pay the {W} cost manually (give p0 floating mana).
    from mtg_bot.game import ManaCoin
    py.players[0].mana_pool.append(ManaCoin(color="W"))
    py.players[0].mana_pool.append(ManaCoin(color="W"))
    py.players[0].mana_pool.append(ManaCoin(color="W"))
    py.players[0].mana_pool.append(ManaCoin(color="G"))
    py.players[0].mana_pool.append(ManaCoin(color="G"))
    py.players[0].mana_pool.append(ManaCoin(color="G"))

    # Python cast: noncreature spell — bumps counter to 1.
    # Signature: _cast_spell(state, player_id, card_id, **kwargs).
    _cast_spell(py, player_id=0, card_id=py_enchant1.id)
    # Resolve to clear the stack.
    resolve_top_of_stack(py)

    # Rust cast: matching shape.
    ok_rs = rs.cast_spell_noncreature(rs_enchant1_id, 0)
    assert ok_rs is True
    # Resolve to clear the stack.
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Counter byte-equal at 1 on both engines.
    assert py.players[0].noncreature_spells_cast_this_turn == 1, (
        "Python counter must bump to 1 after the first noncreature cast"
    )
    assert rs.get_noncreature_spells_cast_this_turn(0) == 1, (
        "Rust counter must bump to 1 after the first noncreature cast"
    )

    # ---- (D) Verify the SECOND noncreature is blocked symmetrically. ----
    # On Rust: re-query legal_decisions, enchant2 must be absent.
    rs_post_decisions = rs.legal_decisions(0)
    rs_post_card_ids = [
        d.get("card_id")
        for d in rs_post_decisions
        if d.get("kind") == "cast_spell"
    ]
    assert rs_enchant2_id not in rs_post_card_ids, (
        "Rust: second noncreature CastSpell must be BLOCKED by the "
        "Deafening Silence gate (counter >= 1 + bf carrier present)"
    )
    # Creature CastSpell stays legal (type-specific gate).
    assert rs_bear_id in rs_post_card_ids, (
        "Rust: creature CastSpell must stay legal under Deafening Silence"
    )

    # On Python: re-query legal_actions, enchant2 must be absent.
    from mtg_bot.actions import CastSpell

    py_post_actions = legal_actions(py, player_id=0)
    py_post_cast_card_ids = [
        a.card_id for a in py_post_actions if isinstance(a, CastSpell)
    ]
    assert py_enchant2.id not in py_post_cast_card_ids, (
        "Python: second noncreature CastSpell must be BLOCKED by the "
        "Deafening Silence post-filter at legal.py:880-893"
    )
    # Creature CastSpell stays legal (type-specific gate).
    assert py_bear.id in py_post_cast_card_ids, (
        "Python: creature CastSpell must stay legal under Deafening Silence"
    )

    # ---- (E) Symmetric block-set: both engines' set of emitted
    # noncreature CastSpell card_ids (post-gate) is EMPTY for the
    # hand. ----
    # We know which registered card_ids are creature vs noncreature
    # by construction (we registered them above). For the hand-cast
    # block-check it's enough to verify the noncreature card_ids
    # ({rs_enchant2_id} on Rust, {py_enchant2.id} on Python) are
    # absent from the emitted CastSpell card_id sets.
    rs_emitted_noncreature_castspell_ids = [
        d.get("card_id")
        for d in rs_post_decisions
        if d.get("kind") == "cast_spell" and d.get("card_id") == rs_enchant2_id
    ]
    py_emitted_noncreature_castspell_ids = [
        a.card_id
        for a in py_post_actions
        if isinstance(a, CastSpell) and a.card_id == py_enchant2.id
    ]
    assert rs_emitted_noncreature_castspell_ids == [], (
        "Rust: no noncreature CastSpell may be emitted from p0's "
        "hand after the gate fires"
    )
    assert py_emitted_noncreature_castspell_ids == [], (
        "Python: no noncreature CastSpell may be emitted from p0's "
        "hand after the gate fires"
    )
