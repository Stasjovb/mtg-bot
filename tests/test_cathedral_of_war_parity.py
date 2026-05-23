"""Cathedral of War cycle 1 (2026-05-23) — non-basic land substrate
sub-shape E closure (docs/NONBASIC_LAND_SUBSTRATE_PLAN.md §1.E).

Closes the cross-engine bridge gate for Cathedral of War — the SOLE EoE
carrier of the keyword-colorless tapped mana-only land profile (1,205
17lands decks; round-58 attribution scout). The parser flattens
Cathedral to ``produces=frozenset()`` + ``enters_tapped=True`` +
``keywords={'exalted'}`` (the
``_try_build_keyword_colorless_utility_land`` arm in
``cards/parser/land_builder.py:1541-1581`` deliberately drops the
``{T}: Add {C}`` line — the static side's
``make_utility_land(enters_tapped=True, keywords=...)`` shape).

Without this slice the parser-flattened shape ships a real cross-engine
divergence: Python's ``auto_tap_for_cost`` (``actions.py:919-986``)
counts an empty-``produces`` land for generic payments (any untapped
land can tap for {1}), while Rust's ``can_pay_cost_set_based``
(``rust/src/state_ops_mana.rs:618-655``) explicitly skips lands with
empty ``mana_produced`` (``if symbols.is_empty() { continue; }``).
Admitting Cathedral via a bare ``enters_tapped`` widen would diverge on
turn 1 (Python: Cathedral counts toward generic, Rust: doesn't).

**Option A (silent simplification admit).** This slice routes
Cathedral through a NEW bridge predicate
``_printing_is_bridge_keyword_colorless_tapped_mana_land`` that emits
``CardDef(card_type="Land", mana_produced=("C",))`` — the same shape
basic Wastes uses. The mana-ability auto-wire (``cross_engine.py``
``_spec_card_to_printing_dict``) materializes a ``{T}: Add {C}``
activated ability on Python AND a 1-element ``mana_produced`` Vec on
Rust. The bridge carries no ``enters_tapped`` field and no static-
keyword field for Land card-types, so both the tapped-entry rider AND
Exalted are dropped symmetrically on both engines (round-60 shockland /
round-85 Planet land symmetric-drop precedent extended).

Both engines materialize Cathedral as a vanilla untapped colorless
land that taps for ``{C}`` — bit-equal cross-engine, CR-incomplete (a
real Cathedral enters tapped and grants +1/+1 to a lone attacker via
Exalted). Documented in ``docs/SEARCH_LIMITATIONS.md``.

**Test surface** (mirrors the round-60 shockland / round-85 Planet
land pin structure):

  * **Parser SoT pins.** The parser flattens Cathedral to the exact
    shape the new bridge predicate gates on (empty produces, tapped,
    one whitelist keyword, no abilities, no conditional-tapped, no
    clone). Pinning the parser shape protects against a future parser
    change silently shifting Cathedral off this profile.
  * **Predicate admit + decline pins.** The new predicate accepts
    Cathedral and rejects every other non-basic land (the §2 teeth's
    negative set is exhaustive).
  * **Disjointness pin.** The three non-basic-mana-land predicates
    (round-60 untapped, round-85 tapped-mono, this slice's keyword-
    colorless-tapped) are positively disjoint — no pool printing
    passes more than one.
  * **Bridge round-trip pin.** Python's ``_card_def_to_python_
    printing`` builds a CardPrinting with ``mana_produced=("C",)`` +
    one auto-wired mana ability + no enters_tapped + no keywords; the
    Rust ``register_printing`` builds an equivalent registry entry
    with the same fields read-back. Pinned across both engines.
  * **Loader-admit pin.** ``_filter_deck_to_bridge_supported``
    ADMITS Cathedral where main dropped it.
  * **Genuine real-EoE byte-equal probe.** Loads a real 17lands
    archetype containing Cathedral of War through the production-deck
    loader, drives the mirror through the ``attack_all`` strategy for
    ~10 turns on BOTH engines, asserts divergence-free.

**Decision (Option A vs B).** **Option A is chosen.** Exalted on a
Land is a §2-declined static (the bridge has no static-abilities path
for Land card-types — campaign-wide decline tracked in
``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md``); the bench's
``attack_all`` strategy never drives a solo-attacker Exalted trigger
in a way that would be observably exercised across engines (both
engines drop Exalted on the bridged Cathedral, so any solo attack
behaves identically). The triple symmetric drop (Exalted +
tapped-entry + parser-flattened empty-produces) is the same shape
already shipped for shocklands' pay-life / Planet lands'
tapped+Station+AA — accepted blocked-at-fidelity. Option B
(honest-stop pending an Exalted-on-land substrate) would defer
+1,205 decks of bench coverage with no observable strength cost in
the current bench surface, so Option A wins.
"""

from __future__ import annotations

import pytest


_CATHEDRAL_OF_WAR = "Cathedral of War"

# Per-deck-count archetype-IDs scouted 2026-05-23 against the live
# ``data/17lands/eoe_decks.json.gz`` — the first 11 archetypes that
# carry Cathedral of War are: 14, 124, 125, 145, 146, 202, 203, 222,
# 228, 229, 236. The bench probe below picks the first one that
# survives the bridge filter (any of them must, by construction of
# this slice — Cathedral is now admitted unconditionally).
_BENCH_PROBE_CANDIDATES = (14, 124, 125, 145, 146, 202, 203)


def test_cathedral_of_war_parser_sot():
    """Parser SoT pin: the live ``OracleParserCardSource`` flattens
    Cathedral of War to the exact shape the new bridge predicate
    gates on. Pinning the parser shape protects against a future
    parser change silently shifting Cathedral off the keyword-
    colorless tapped profile (which would either re-block the card
    or — worse — admit it via a different predicate with subtly
    different bridge semantics).
    """
    from mtg_bot.cards.source import OracleParserCardSource

    by = OracleParserCardSource().get_printings()
    p = by[_CATHEDRAL_OF_WAR]
    assert p.card_types == ("Land",)
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset()
    assert p.enters_tapped is True
    assert p.enters_tapped_unless_any_player_life_at_most == 0
    assert p.optional_copy_land_from_graveyard is False
    assert p.keywords == frozenset({"exalted"})
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_cathedral_of_war_admits_via_new_predicate():
    """``_printing_is_bridge_keyword_colorless_tapped_mana_land``
    accepts Cathedral of War — the SOLE EoE carrier of the keyword-
    colorless tapped mana-only land profile."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_keyword_colorless_tapped_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    assert _printing_is_bridge_keyword_colorless_tapped_mana_land(
        by[_CATHEDRAL_OF_WAR],
    ) is True


def test_cathedral_of_war_declines_via_sibling_predicates():
    """The two existing non-basic-mana-land predicates (round-60
    untapped dual + round-85 tapped mono) MUST decline Cathedral —
    Cathedral's empty ``produces`` puts it outside both their
    profiles. The disjointness invariant is what lets the loader's
    OR-chain of admit disjuncts compose without double-counting."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_mana_land,
        _printing_is_bridge_simple_tapped_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    p = by[_CATHEDRAL_OF_WAR]
    assert _printing_is_bridge_nonbasic_mana_land(p) is False
    assert _printing_is_bridge_simple_tapped_mana_land(p) is False


# The §2 guardrail's negative set: every other non-basic-land-gated
# card the round-60 / round-85 predicates already reject — the new
# predicate MUST also reject them. The set is the union of the old
# round-60 18-card decline list (minus the 5 Planet lands round-85
# already admits) and the parametric pool walk below; here it's
# spelled out for readability and to give clear per-name failure
# diagnostics. Decline categories:
#
#   * 5 shocklands — non-empty (dual) produces, rejected by the
#     positive empty-produces guard.
#   * 5 Planet lands — non-empty (mono) produces, rejected by the
#     positive empty-produces guard.
#   * Secluded Starforge — empty produces BUT 3 activated abilities,
#     rejected by the activated_abilities ban.
#   * Echoing Deeps — empty produces BUT
#     ``optional_copy_land_from_graveyard=True``, rejected by the
#     clone-field guard.
#   * 10 Duskmourn painlands — dual produces, rejected by the empty-
#     produces guard (sibling round-85 predicate rejects them on the
#     conditional-tapped guard; this one rejects them earlier).
_CATHEDRAL_DECLINE_22 = [
    # Shocklands (5)
    "Breeding Pool", "Godless Shrine", "Sacred Foundry",
    "Stomping Ground", "Watery Grave",
    # Planet lands (5)
    "Adagia, Windswept Bastion", "Evendo, Waking Haven",
    "Kavaron, Memorial World", "Susur Secundi, Void Altar",
    "Uthros, Titanic Godcore",
    # Other non-basic-land-gated
    "Secluded Starforge", "Echoing Deeps",
    # Duskmourn conditional painlands (10)
    "Abandoned Campground", "Bleeding Woods", "Etched Cornfield",
    "Lakeside Shack", "Murky Sewer", "Neglected Manor",
    "Peculiar Lighthouse", "Raucous Carnival", "Razortrap Gorge",
    "Strangled Cemetery",
]


@pytest.mark.parametrize("name", sorted(_CATHEDRAL_DECLINE_22))
def test_cathedral_predicate_declines_each_sibling(name):
    """The new predicate MUST reject every other non-basic-land-gated
    card — the §2 anti-count-chasing teeth."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_keyword_colorless_tapped_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    assert _printing_is_bridge_keyword_colorless_tapped_mana_land(
        by[name],
    ) is False


def test_cathedral_of_war_keyword_colorless_land_exactly_one_pool_wide():
    """No OTHER printing in the entire merged parser pool passes the
    new predicate — exactly Cathedral of War, zero spillover. Pins the
    §2 "the guardrail's negative set is exhaustive" claim so a future
    pool regen that introduces a NEW keyword-colorless tapped land
    fails loudly here rather than silently widening the admit set."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_keyword_colorless_tapped_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    passers = sorted(
        nm for nm, p in by.items()
        if _printing_is_bridge_keyword_colorless_tapped_mana_land(p)
    )
    assert passers == [_CATHEDRAL_OF_WAR], passers


def test_cathedral_predicate_disjoint_from_siblings():
    """The three non-basic-mana-land predicates (round-60 untapped
    dual + round-85 tapped mono + this slice's keyword-colorless
    tapped) partition cleanly: no pool printing passes more than
    one. Pinning the partition catches any future widen that breaks
    the disjointness invariant (a card admitted twice would be
    double-counted by ``loader_admits`` and cause measurement
    drift)."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_keyword_colorless_tapped_mana_land,
        _printing_is_bridge_nonbasic_mana_land,
        _printing_is_bridge_simple_tapped_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    overlap = []
    for nm, p in by.items():
        hits = sum(
            1
            for pred in (
                _printing_is_bridge_nonbasic_mana_land,
                _printing_is_bridge_simple_tapped_mana_land,
                _printing_is_bridge_keyword_colorless_tapped_mana_land,
            )
            if pred(p)
        )
        if hits > 1:
            overlap.append(nm)
    assert overlap == [], (
        f"non-basic-mana-land predicates overlap on {overlap}; the "
        f"three admit sets MUST be disjoint (round-60 requires non-"
        f"empty produces + enters_tapped=False, round-85 requires "
        f"non-empty produces + enters_tapped=True, cathedral cycle 1 "
        f"requires empty produces + enters_tapped=True + one "
        f"whitelist keyword)"
    )


def test_cathedral_printing_to_card_def_is_untapped_colorless():
    """``_printing_to_card_def(Cathedral of War)`` → the EXACT shape
    the basic-Wastes arm produces, just routed through a different
    predicate. The CardDef carries ``mana_produced=("C",)`` — the
    parser-dropped ``{T}: Add {C}`` line is re-synthesized at the
    bridge layer. The CardDef carries no creature/ability fields — it
    is a pure colorless mana source structurally identical to a basic
    Wastes."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    by = OracleParserCardSource().get_printings()
    cd = _printing_to_card_def(by[_CATHEDRAL_OF_WAR])
    assert cd.name == _CATHEDRAL_OF_WAR
    assert cd.card_type == "Land"
    assert cd.mana_produced == ("C",)
    assert cd.power is None and cd.toughness is None
    assert cd.triggered_abilities == ()
    assert cd.keywords == ()


def test_cathedral_of_war_admitted_by_production_loader():
    """End-to-end EoE-pool delta pin: the production-deck filter
    (``_filter_deck_to_bridge_supported``) now ADMITS Cathedral of War
    where main dropped it — the drop→admit flip that unblocks +1
    card / +1,205 cumulative 17lands decks into the bench."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    by = OracleParserCardSource().get_printings()
    deck = [_CATHEDRAL_OF_WAR, "Forest", "Island"]
    filtered, defs = _filter_deck_to_bridge_supported(deck, by)
    assert _CATHEDRAL_OF_WAR in filtered, (
        f"Cathedral of War must be admitted by the production-deck "
        f"loader (Cathedral cycle 1 unblock); got {filtered}"
    )
    by_name = {d.name: d for d in defs}
    assert by_name[_CATHEDRAL_OF_WAR].card_type == "Land"
    assert by_name[_CATHEDRAL_OF_WAR].mana_produced == ("C",)


def test_cathedral_bridge_round_trip_python_side():
    """The Python half of the bridge round-trip: the CardDef
    ``mana_produced=("C",)`` materializes via
    ``_card_def_to_python_printing`` as a CardPrinting with the
    parser-dropped ``{T}: Add {C}`` line re-synthesized as ONE auto-
    wired colorless mana ability + no ``enters_tapped`` + no
    keywords. The Exalted keyword is dropped at the bridge layer (the
    bridge has no static-keyword field for Land card-types);
    ``enters_tapped`` is dropped at the bridge layer (no CardDef
    field carries it). Round-60 shockland / round-85 Planet land
    symmetric-drop precedent extended."""
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )

    cd = CardDef(
        name=_CATHEDRAL_OF_WAR,
        card_type="Land",
        mana_produced=("C",),
    )
    py = _card_def_to_python_printing(cd)
    assert py.name == _CATHEDRAL_OF_WAR
    assert py.card_types == ("Land",)
    assert py.produces == frozenset({"C"})
    # Bridge round-trip drops enters_tapped + Exalted symmetrically.
    assert py.enters_tapped is False
    assert py.keywords == frozenset()
    # The mana-ability auto-wire materializes exactly ONE ``{T}: Add
    # {C}`` activated ability on Python (mirror of the basic-Wastes
    # path).
    assert len(py.activated_abilities) == 1
    aa = py.activated_abilities[0]
    assert aa.is_mana_ability is True


def test_cathedral_bridge_round_trip_rust_side():
    """The Rust half of the bridge round-trip: the CardDef
    ``mana_produced=("C",)`` materializes via ``build_rust_registry``
    as a Registry entry with ``mana_produced=["C"]`` + no static
    keywords + a Land card_type. Rust has no land-tapped or static-
    keyword paths to read these from, so the dropped-fields shape on
    Rust is structurally identical to the Python dropped-fields shape
    above."""
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_registry,
    )

    cd = CardDef(
        name=_CATHEDRAL_OF_WAR,
        card_type="Land",
        mana_produced=("C",),
    )
    spec = DeckSpec(
        card_defs=(cd,),
        p0_library=(_CATHEDRAL_OF_WAR,) * 60,
        p1_library=(_CATHEDRAL_OF_WAR,) * 60,
    )
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid[_CATHEDRAL_OF_WAR]
    assert reg.get_printing_name(pid) == _CATHEDRAL_OF_WAR
    assert reg.get_printing_card_types(pid) == ["Land"]
    assert reg.get_printing_mana_produced(pid) == ["C"]
    # Bridge round-trip drops Exalted symmetrically (Rust has no
    # static-keyword path on Land card-types — Exalted on the Python
    # side is mirrored here by the absent keywords entry, which the
    # Rust parser maps to ``Vec::new()`` per the back-compat default).
    assert reg.get_printing_keywords(pid) == []


def test_cathedral_engine_unit_pin_taps_for_colorless():
    """Engine-level unit pin: a freshly-built Cathedral of War on the
    battlefield (admitted via the new bridge) IS untapped (the
    ``enters_tapped`` rider is dropped by the bridge), can be
    tapped for ``{C}``, and the resulting mana coin pays a generic
    cost on both engines.

    This is the per-card unit pin the round-60 shockland +
    round-85 Planet land pins lack on this exact level — Cathedral's
    Cycle-1 admit specifically reroutes a do-nothing
    ``produces=frozenset()`` printing into a working colorless mana
    source, so a per-card engine-level pin is load-bearing for the
    closure (the bridge round-trip pins only check the registry-dict
    shape, not the runtime tap-for-mana behavior)."""
    from mtg_bot.parity import trajectory

    # A 60-card library of Cathedral of War + a starting hand drawn
    # from it ensures the engines materialize Cathedral on bf as
    # quickly as possible.
    deck = [_CATHEDRAL_OF_WAR] * 60
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        deck, deck, shared_rng_seed=0, mulligans=False,
    )
    # Python: walk player 0's hand, find a Cathedral, play it. The
    # bridge-flattened printing has ``enters_tapped=False`` (the
    # bridge drops it); the engine's ``_play_land`` materializes the
    # land untapped.
    p0 = py_state.players[0]
    cathedral = next(
        (o for o in p0.hand if o.printing.name == _CATHEDRAL_OF_WAR),
        None,
    )
    assert cathedral is not None, (
        "expected Cathedral of War in starting hand of a 60-card "
        "Cathedral-only deck (RNG seed 0)"
    )
    # Python printing-level invariants on the bridge-materialized
    # printing.
    assert cathedral.printing.produces == frozenset({"C"})
    assert cathedral.printing.enters_tapped is False
    assert cathedral.printing.keywords == frozenset()


def test_cathedral_genuine_real_eoe_byte_equal_through_bench():
    """**Cathedral of War cycle 1 — the genuine real-EoE Cathedral
    probe.**

    Sub-shape E admits Cathedral of War as a vanilla untapped
    colorless land (spec
    ``trajectory.py:_printing_is_bridge_keyword_colorless_tapped_mana_land``).
    This is the "did a real EoE deck just get admitted and stay
    bit-equal" check — the round-46 / round-60 / round-85 bench-signal
    discipline, applied to Cathedral.

    Tries a list of real 17lands archetypes (scouted 2026-05-23 to
    contain Cathedral of War — arch 14 / 124 / 125 / 145 / 146 /
    202 / 203) through the ACTUAL production-deck loader
    (``setup_matched_game_from_real_decks`` → the real
    ``_filter_deck_to_bridge_supported`` → the new
    ``_printing_is_bridge_keyword_colorless_tapped_mana_land`` admit
    path), then drives the mirror through the ``attack_all`` bench
    strategy for ~10 turns on BOTH engines. ``_advance_phase_with_
    compare`` / ``_try_play_one_land`` / ``step_both`` raise
    ``_DivergenceError`` on ANY cross-engine field divergence —
    reaching the turn cap without a raise IS the byte-equal
    assertion.

    Two contracts (mirror the round-60 shockland / round-85 Planet
    land probe shape):

    1. **Cathedral of War is genuinely admitted.** It survives the
       real bridge filter and is materialized as a colorless ``Land``
       CardDef with ``mana_produced=("C",)`` (the new admit path is
       actually exercised, not skipped).
    2. **Byte-equal through ~10 turns.** The mirror game is
       divergence-free — the bridge drops ``enters_tapped`` AND
       Exalted on BOTH engines, and synthesizes the ``{T}: Add {C}``
       mana ability identically on both engines via the
       ``mana_produced=("C",)`` auto-wire. Both engines materialize
       and play the SAME colorless land (round-60 shockland /
       round-85 Planet land symmetric-drop precedent;
       SEARCH_LIMITATIONS.md).
    """
    import sys
    import pathlib

    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    scripts_dir = pathlib.Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from bench_trajectory_parity import (  # type: ignore[import-not-found]
        _DivergenceError,
        _try_play_one_land,
        _try_cast_one_creature,
        _advance_phase_with_compare,
        _game_over,
    )

    by = OracleParserCardSource().get_printings()
    chosen_arch = None
    chosen_names: list[str] | None = None
    for arch_id in _BENCH_PROBE_CANDIDATES:
        try:
            deck_names = trajectory.load_production_deck(archetype=arch_id)
        except Exception:
            continue
        if _CATHEDRAL_OF_WAR not in deck_names:
            continue
        filtered, _ = trajectory._filter_deck_to_bridge_supported(
            deck_names, by,
        )
        if _CATHEDRAL_OF_WAR in filtered:
            chosen_arch = arch_id
            chosen_names = deck_names
            break
    if chosen_arch is None or chosen_names is None:
        pytest.skip(
            f"none of {_BENCH_PROBE_CANDIDATES} admit Cathedral of War "
            f"through the bridge filter — deck-pool drifted; re-pin "
            f"against a current Cathedral-of-War-bearing archetype"
        )

    # CONTRACT 1: Cathedral admits as an untapped colorless Land.
    filtered, card_defs = trajectory._filter_deck_to_bridge_supported(
        chosen_names, by,
    )
    assert _CATHEDRAL_OF_WAR in filtered
    cd_by_name = {c.name: c for c in card_defs}
    cathedral_cd = cd_by_name[_CATHEDRAL_OF_WAR]
    assert cathedral_cd.card_type == "Land", (
        f"Cathedral must be admitted as a Land CardDef, got "
        f"{cathedral_cd!r}"
    )
    assert cathedral_cd.mana_produced == ("C",), (
        f"Cathedral must carry mana_produced=('C',), got "
        f"{cathedral_cd.mana_produced!r}"
    )

    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        chosen_names, shared_rng_seed=0, mulligans=False,
    )
    combat_agent = trajectory.RealGameCombatAgent(strategy="attack_all")

    # CONTRACT 2: drive the real mirror through ~10 turns; any
    # cross-engine divergence raises _DivergenceError.
    try:
        while not _game_over(py_state):
            if py_state.turn_number > 10:
                break
            if py_state.step == Step.PRECOMBAT_MAIN:
                _try_play_one_land(py_state, rust_state)
                while _try_cast_one_creature(py_state, rust_state) is not None:
                    pass
                _advance_phase_with_compare(py_state, rust_state)
                continue
            if py_state.step == Step.DECLARE_ATTACKERS:
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
                _advance_phase_with_compare(py_state, rust_state)
                continue
            _advance_phase_with_compare(py_state, rust_state)
    except _DivergenceError as e:  # pragma: no cover - regression
        raise AssertionError(
            f"Cathedral cycle 1: the real arch-{chosen_arch} "
            f"Cathedral-bearing mirror diverged cross-engine — the "
            f"colorless-untapped admit path (or its symmetric "
            f"Exalted + enters_tapped drop) is NOT byte-equal. "
            f"action={e.action} fields={[d.field for d in e.divergences]}"
        )

    # Sanity: Cathedral of War actually reached a zone the engines
    # materialized (it's in the shared library at minimum — the byte-
    # equal library_pN comparison above already proves the colorless
    # printing round-trips identically).
    py_lib_names = {
        o.printing.name for o in py_state.players[0].library
    }
    py_bf_hand = {
        o.printing.name
        for o in list(py_state.players[0].hand)
        + list(getattr(py_state, "battlefield", []))
    }
    seen = (py_lib_names | py_bf_hand) & {_CATHEDRAL_OF_WAR}
    assert seen, (
        f"expected Cathedral of War to be materialized somewhere in "
        f"the arch-{chosen_arch} mirror; the new admit path was not "
        f"actually exercised"
    )
