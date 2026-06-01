"""Cross-engine parity probes for Green Sun's Zenith.

**Green-creature X-tutor Effect substrate (2026-05-31; substrate-only
honest-stop).** Green Sun's Zenith `{X}{G}` Sorcery (Special Guests
reprint in the EoE pool): "Search your library for a green creature
card with mana value X or less, put it onto the battlefield, then
shuffle. Exile Green Sun's Zenith."

**What this lane ships (the genuinely-missing self-contained piece).**
The bespoke Python effect
``effects.generic.search.SearchLibraryForGreenCreatureWithMVAtMostX``
(a parameterless frozen dataclass that reads
``state.resolving_x_value``) had NO Rust mirror. This lane adds:

  * Rust ``Effect::SearchLibraryForGreenCreatureWithMVAtMostX`` unit
    variant + parse arm + ``to_pydict`` arm + resolve arm (reads
    ``current_resolve_x_value`` per the C1 bracket, filters the
    controller's library for the topmost green creature with MV ≤ X,
    puts it onto the battlefield, then always shuffles — the same
    external-rng Fisher-Yates / xorshift fallback shuffle block
    ``Effect::SearchLibraryForBasicLandTapped`` uses).
  * The ``search_library_for_green_creature_with_mv_at_most_x``
    dict→Python bridge arm + the reverse-serializer leaf in
    ``trajectory._python_spell_effect_to_dict``.

This makes ``SearchLibraryForGreenCreatureWithMVAtMostX`` a
covered+bridged class (the
``effect_coverage.covered_python_class_set()`` 1:1 identity mapping).

**Why this is NOT a PROBED flip (the honest-stop).** Green Sun's
Zenith carries a SELF-scope ``StaticAbility`` with a
``ReplacementEffect(WOULD_GO_TO_GRAVEYARD, Replace(new_destination=
"library"))`` — the shuffle-self redirect it shares with Nexus of
Fate (it models the oracle's "Exile Green Sun's Zenith" as a
shuffle-into-library on resolve). The Rust ``StaticReplacement``
substrate (Phase 5, 2026-05-31) has a CLOSED vocab — events
``would_create_token`` / ``would_place_counter`` /
``triggered_ability_triggers`` and transforms ``multiply_count`` /
``add_instances`` (a single int param each). The
``would_go_to_graveyard`` event + the destination-string ``replace``
transform are OUTSIDE that vocab and have no Rust resolve hook in the
post-resolve spell-movement path. A real-printing cross-engine probe
would therefore mistranslate the spell's post-resolve destination
(Python shuffles GSZ into library; Rust sends it to graveyard). That
is the genuine remaining wall — a SEPARATE substrate from the X-mana
subsystem (which IS fully on main; see
``test_zero_point_ballad_parity.py``). Documented in
``docs/SEARCH_LIMITATIONS.md``.

**Cross-engine fetch asymmetry.** Python's no-agent harness path
DECLINES the fetch (``p.agent is None`` → ``chosen_id`` stays None →
shuffle, fetch nothing). The Rust engine has no
``choose_card_from_library`` agent surface and takes the topmost match
(the deterministic-first convention every other Rust library-search
arm uses). The two are byte-equal ONLY in the no-match (empty-fetch)
configuration. The Rust unit pins below drive the deterministic-first
fetch at a seated X directly (the synthetic surface that the no-agent
harness can never produce alone).
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_gsz_spell_effect_and_x_cost():
    """**Verify-first.** The live parser maps Green Sun's Zenith to a
    ``SearchLibraryForGreenCreatureWithMVAtMostX`` spell_effect with
    ``mana_cost.x_pips == 1`` ({X}{G}) and carries the shuffle-self
    ``WOULD_GO_TO_GRAVEYARD -> library`` ReplacementEffect static.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects import SearchLibraryForGreenCreatureWithMVAtMostX
    from mtg_bot.effects.modifiers import (
        EventPattern, Replace, ReplacementEffect,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Green Sun's Zenith")
    if p is None:
        pytest.skip("Green Sun's Zenith absent from active CardSource")
    assert "Sorcery" in p.card_types
    assert isinstance(
        p.spell_effect, SearchLibraryForGreenCreatureWithMVAtMostX
    )
    assert p.mana_cost.x_pips == 1, (
        f"GSZ mana_cost.x_pips must be 1 ({{X}}{{G}}); "
        f"got {p.mana_cost.x_pips}"
    )
    # The shuffle-self static is the load-bearing honest-stop wall.
    expected_static = ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_GO_TO_GRAVEYARD),
        transform=Replace(new_destination="library"),
    )
    assert any(
        s.replacement_effect == expected_static
        for s in p.static_abilities
    ), "GSZ must carry the shuffle-self WOULD_GO_TO_GRAVEYARD->library static"


# -------------------------------------------------------------------
# Coverage + round-trip pins (the substrate this lane lands).
# -------------------------------------------------------------------


def test_gsz_effect_class_covered():
    """The Rust ``Effect::SearchLibraryForGreenCreatureWithMVAtMostX``
    variant makes the Python class covered (1:1 identity mapping)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "SearchLibraryForGreenCreatureWithMVAtMostX" in covered, (
        "Rust Effect variant must make the Python class covered"
    )


def test_gsz_serializer_round_trip():
    """The reverse serializer emits the kind-only unit dict; the
    dict→Python bridge reconstructs the field-free effect."""
    from mtg_bot.effects import SearchLibraryForGreenCreatureWithMVAtMostX
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = SearchLibraryForGreenCreatureWithMVAtMostX()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {
        "kind": "search_library_for_green_creature_with_mv_at_most_x"
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, SearchLibraryForGreenCreatureWithMVAtMostX)


def test_gsz_admits_at_bridge_gate_after_redirect_widen():
    """**The flip pin (was the honest-stop pin).** With the
    ``would_go_to_graveyard -> library`` StaticReplacement
    destination-redirect now bridged (the Rust
    ``move_source_post_resolve`` hook reroutes the resolving spell to
    its owner's library + shuffles, mirroring Python's
    ``_send_to_graveyard_or_library``), Green Sun's Zenith ADMITS at
    the spell-card-bridge gate — its shuffle-self static is no longer a
    decline reason and its ``SearchLibraryForGreenCreatureWithMVAtMostX``
    spell_effect is covered+bridged.

    This is the inverse of the prior honest-stop pin: the card is now
    genuinely probe-able (see the real-EoE byte-equal probe below).
    Nexus of Fate / Quantum Riddler MUST stay declined — verified in
    ``test_gsz_redirect_widen_keeps_nexus_and_quantum_riddler_declined``.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Green Sun's Zenith")
    if p is None:
        pytest.skip("Green Sun's Zenith absent from active CardSource")
    # The spell_effect side is covered+bridged (the prior substrate).
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )
    # The shuffle-self redirect static is now BRIDGEABLE — the guard no
    # longer declines it.
    assert (
        trajectory._printing_has_unbridgeable_replacement_static(p)
        is False
    ), "GSZ's graveyard->library redirect is now bridgeable"
    # And the card admits at the spell-card-bridge gate.
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Green Sun's Zenith must ADMIT post-redirect-widen"
    )
    # The replacement quad the bridge threads through to the CardDef:
    reps = trajectory._static_replacements_from_printing(p)
    assert reps == (
        ("would_go_to_graveyard", "replace", 0, "library"),
    ), f"GSZ redirect must round-trip as the replace quad; got {reps}"


def test_gsz_redirect_widen_keeps_nexus_and_quantum_riddler_declined():
    """The redirect widen must NOT over-grow the admit set. Nexus of
    Fate (shares the identical shuffle-self redirect static, but its
    ``TakeExtraTurnAfterThisOne`` spell_effect is NOT covered — the
    extra-turn substrate is unbuilt) and Quantum Riddler (a Creature
    carrying a ``would_draw_cards`` ``AddToCount`` replacement outside
    the bridgeable event vocab) BOTH stay declined."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()

    nexus = src.get("Nexus of Fate")
    if nexus is not None:
        # Its redirect static is now bridgeable (shared with GSZ)...
        assert (
            trajectory._printing_has_unbridgeable_replacement_static(nexus)
            is False
        )
        # ...but it STAYS declined via the covered-set gate (its
        # spell_effect is not covered+bridged).
        assert (
            trajectory._printing_is_bridge_simple_spell(nexus) is False
        ), "Nexus of Fate must stay declined (extra-turn substrate unbuilt)"

    qr = src.get("Quantum Riddler")
    if qr is not None:
        # would_draw_cards is outside the bridgeable event vocab.
        assert (
            trajectory._printing_has_unbridgeable_replacement_static(qr)
            is True
        ), "Quantum Riddler's would_draw_cards replacement stays unbridgeable"
        assert trajectory._printing_is_bridge_simple_spell(qr) is False


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — green/MV/X filter +
# put-onto-battlefield + shuffle).
# -------------------------------------------------------------------


_ZL = 1  # library zone id


def _build_rust_gsz_state(*, lib_cards=(), x_value=0):
    """Build a Rust state with GSZ on p0's stack + ``lib_cards`` seeded
    into p0's library + X bound to the StackItem via the C1 setter.

    ``lib_cards``: iterable of (name, card_types, mana_cost_dict)
    tuples seeded top-to-bottom into p0's library (first = top).
    Returns ``(rs, lib_ids)`` where ``lib_ids`` is the seeded ids in
    order.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    lib_ids = []
    for name, card_types, mc in lib_cards:
        oid = rs.register_and_inject_object(
            {
                "name": name,
                "card_types": list(card_types),
                "power": 2,
                "toughness": 2,
                "mana_cost": dict(mc),
            },
            0,
            _ZL,
        )
        lib_ids.append(oid)
    spell_id = rs.register_and_inject_object(
        {
            "name": "Green Sun's Zenith",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind":
                    "search_library_for_green_creature_with_mv_at_most_x"
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.set_stack_top_x_value(x_value)
    return rs, lib_ids


def test_rust_gsz_fetches_green_creature_within_mv_limit():
    """X=2 — fetches the topmost green creature with MV ≤ 2 onto the
    battlefield; a green MV-4 creature and a blue MV-2 creature are
    NOT fetched."""
    rs, ids = _build_rust_gsz_state(
        lib_cards=(
            ("Green MV2", ("Creature",), {"generic": 1, "G": 1}),
            ("Green MV4", ("Creature",), {"generic": 3, "G": 1}),
            ("Blue MV2", ("Creature",), {"generic": 1, "U": 1}),
        ),
        x_value=2,
    )
    green2, green4, blue2 = ids
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    bf = {e["id"] for e in rs.battlefield_snapshot()}
    assert green2 in bf, "green MV-2 creature must be fetched at X=2"
    assert green4 not in bf, "green MV-4 creature must NOT be fetched at X=2"
    assert blue2 not in bf, "blue MV-2 creature must NOT be fetched"
    # The fetched creature enters summoning-sick (CR 302.1).
    entered = next(
        e for e in rs.battlefield_snapshot() if e["id"] == green2
    )
    assert entered.get("summoning_sick", True) is True


def test_rust_gsz_x_zero_fetches_nothing():
    """X=0 — no green creature has MV ≤ 0, so nothing is fetched (the
    only configuration byte-equal to Python's no-agent decline). The
    spell still resolves cleanly + shuffles."""
    rs, ids = _build_rust_gsz_state(
        lib_cards=(
            ("Green MV2", ("Creature",), {"generic": 1, "G": 1}),
        ),
        x_value=0,
    )
    (green2,) = ids
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    bf = {e["id"] for e in rs.battlefield_snapshot()}
    assert green2 not in bf, "nothing is fetchable at X=0 (MV 2 > 0)"
    # The green creature is still in p0's library.
    lib_ids = {e["id"] for e in rs.library_snapshot(0)}
    assert green2 in lib_ids


def test_rust_gsz_no_green_creature_fizzles_and_shuffles():
    """X high but the library holds only non-green creatures — nothing
    is fetched; resolve is a clean fizzle (still shuffles)."""
    rs, ids = _build_rust_gsz_state(
        lib_cards=(
            ("Blue MV1", ("Creature",), {"U": 1}),
            ("Red MV1", ("Creature",), {"R": 1}),
        ),
        x_value=9,
    )
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    bf = {e["id"] for e in rs.battlefield_snapshot()}
    assert not (set(ids) & bf), "no green creature → nothing fetched"


def test_rust_gsz_non_creature_green_card_not_fetched():
    """A green NON-creature card (e.g. a green sorcery) with MV ≤ X is
    NOT fetched — the filter requires the Creature card type."""
    rs, ids = _build_rust_gsz_state(
        lib_cards=(
            ("Green Sorcery MV1", ("Sorcery",), {"G": 1}),
            ("Green Creature MV3", ("Creature",), {"generic": 2, "G": 1}),
        ),
        x_value=3,
    )
    green_sorc, green_creat = ids
    rs.resolve_top_of_stack()
    bf = {e["id"] for e in rs.battlefield_snapshot()}
    assert green_sorc not in bf, "green non-creature must not be fetched"
    assert green_creat in bf, "green creature MV-3 must be fetched at X=3"


# -------------------------------------------------------------------
# Rust redirect-hook unit pin (the GSZ-flip substrate this lane lands):
# would_go_to_graveyard -> library destination redirect.
# -------------------------------------------------------------------


_ZONE_GRAVEYARD = 3
_ZONE_BATTLEFIELD = 2


def test_rust_gsz_redirect_static_shuffles_self_into_library():
    """**The redirect-hook pin.** A resolving Sorcery whose printing
    carries the ``would_go_to_graveyard -> replace(library)``
    ``StaticReplacement`` is rerouted to its owner's LIBRARY (not the
    graveyard) by the Rust ``move_source_post_resolve`` hook — Green
    Sun's Zenith's shuffle-self redirect.

    Empty-library config (no fetchable creature) so the fetch surface
    is dormant and the post-redirect library shuffle is a deterministic
    no-op (the lone redirected GSZ is the only card → ``lib_len < 2``)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    spell_id = rs.register_and_inject_object(
        {
            "name": "Green Sun's Zenith",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind":
                    "search_library_for_green_creature_with_mv_at_most_x"
                }
            ],
            "static_replacements": [
                {
                    "event": "would_go_to_graveyard",
                    "transform_kind": "replace",
                    "transform_dest": "library",
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.set_stack_top_x_value(9)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    # GSZ shuffled itself into p0's LIBRARY, NOT the graveyard.
    lib_ids = {e["id"] for e in rs.library_snapshot(0)}
    assert spell_id in lib_ids, (
        "GSZ must be redirected into its owner's library by the "
        "would_go_to_graveyard->library StaticReplacement"
    )
    gy_ids = {e["id"] for e in rs.graveyard_snapshot(0)}
    assert spell_id not in gy_ids, "GSZ must NOT be in the graveyard"


def test_rust_sorcery_without_redirect_static_goes_to_graveyard():
    """Control: a resolving Sorcery WITHOUT the redirect static goes to
    the graveyard as before (the hook is gated on the replacement being
    present — non-GSZ spell movement is byte-identical)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    spell_id = rs.register_and_inject_object(
        {
            "name": "Plain Sorcery",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind":
                    "search_library_for_green_creature_with_mv_at_most_x"
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.set_stack_top_x_value(0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    gy_ids = {e["id"] for e in rs.graveyard_snapshot(0)}
    assert spell_id in gy_ids, "plain Sorcery must resolve to the graveyard"
    lib_ids = {e["id"] for e in rs.library_snapshot(0)}
    assert spell_id not in lib_ids


# -------------------------------------------------------------------
# GENUINE real-printing cross-engine PROBE (the PROBED-tier flip).
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_green_suns_zenith_shuffle_self_parity():
    """**GENUINE real-printing cross-engine probe — Green Sun's Zenith
    shuffle-self redirect. PROBED-tier flip (covered_by_construction →
    PROBED).**

    Drives the **ACTUAL parsed Green Sun's Zenith printing** on the
    Python side: ``get_active_source().get_printings()["Green Sun's
    Zenith"]`` — which the live parser maps to a ``spell_effect`` of
    ``SearchLibraryForGreenCreatureWithMVAtMostX()`` (verified above)
    with ``mana_cost.x_pips == 1`` AND the shuffle-self
    ``WOULD_GO_TO_GRAVEYARD -> Replace(new_destination="library")``
    ``StaticReplacement`` static.

    Oracle (``data/edge_of_eternities.json``): "[Sorcery] {X}{G} —
    Search your library for a green creature card with mana value X or
    less, put it onto the battlefield, then shuffle. Exile Green Sun's
    Zenith." The engine models "Exile Green Sun's Zenith" as the
    shuffle-self ``would_go_to_graveyard -> library`` redirect static.

    **Empty-library config (the byte-equal harness shape).** p0's
    library is EMPTY, so:

      * The fetch surface is dormant on BOTH engines (no green creature
        to fetch → nothing put onto the battlefield; this also sidesteps
        the documented fetch asymmetry — Python's no-agent harness
        declines the fetch, Rust takes the topmost match, byte-equal
        ONLY in the no-match config).
      * The search-arm post-search shuffle (#1) operates on the empty
        library — a no-op.
      * The redirect reroutes GSZ to p0's library; the post-redirect
        shuffle (#2) operates on the lone GSZ (``len < 2``) — a no-op.

    So the WHOLE post-resolve field view is deterministic + byte-equal:
    GSZ ends as the SOLE card in p0's LIBRARY (NOT the graveyard) on
    both engines, and every other observable matches. This is the
    genuine PROBED-tier evidence that the redirect substrate translates
    byte-equal cross-engine.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        build_python_field_view,
        compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects import SearchLibraryForGreenCreatureWithMVAtMostX

    real = get_active_source().get_printings().get("Green Sun's Zenith")
    if real is None:
        pytest.skip("Green Sun's Zenith absent from active CardSource")
    assert "Sorcery" in real.card_types
    assert isinstance(
        real.spell_effect, SearchLibraryForGreenCreatureWithMVAtMostX
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: cast the genuine GSZ with X=9 (X is irrelevant on an
    # empty library — nothing is fetchable). agent is None by default,
    # so the search path declines and shuffles; the StackItem x_value is
    # set explicitly to mirror the Rust C1 seat byte-equal.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0, x_value=9))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: push the bridged GSZ carrier (genuine effect-kind +
    # the would_go_to_graveyard->library redirect static), seat X=9 via
    # the C1 setter, resolve.
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Green Sun's Zenith",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind":
                    "search_library_for_green_creature_with_mv_at_most_x"
                }
            ],
            "static_replacements": [
                {
                    "event": "would_go_to_graveyard",
                    "transform_kind": "replace",
                    "transform_dest": "library",
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.set_stack_top_x_value(9)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- FULL byte-equal field-view compare.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Green Sun's Zenith shuffle-self redirect must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )

    # ---- Observable cross-checks: GSZ in LIBRARY, not graveyard.
    assert py_spell.zone == Zone.LIBRARY, (
        "Python: GSZ must shuffle itself into the library (not graveyard)"
    )
    assert any(o.id == py_spell.id for o in py.players[0].library)
    assert all(o.id != py_spell.id for o in py.players[0].graveyard)
    rs_lib = {e["id"] for e in rs.library_snapshot(0)}
    rs_gy = {e["id"] for e in rs.graveyard_snapshot(0)}
    assert rs_spell in rs_lib, (
        "Rust: GSZ must shuffle itself into the library (byte-equal)"
    )
    assert rs_spell not in rs_gy
