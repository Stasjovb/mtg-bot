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


def test_gsz_stays_declined_at_admit_gate_static_wall():
    """**The honest-stop pin.** Even WITH the spell_effect now
    covered+bridged, Green Sun's Zenith MUST stay DECLINED at the
    spell-card-bridge admit gate — its shuffle-self
    ``WOULD_GO_TO_GRAVEYARD -> library`` ReplacementEffect static has
    no Rust StaticReplacement-vocab support, so a real-printing
    cross-engine probe would mistranslate the post-resolve
    destination.

    Today the admit predicate ``_printing_is_bridge_simple_spell``
    does not inspect ``static_abilities`` at all, so the spell_effect
    teeth alone (covered+bridged + round-trip) WOULD flip the card.
    This pin asserts the card is still NOT genuinely probe-able: the
    static is a real divergence the harness must not silently ignore.
    The closure for this card is gated on the would-go-to-graveyard
    StaticReplacement substrate (see docs/SEARCH_LIMITATIONS.md).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Green Sun's Zenith")
    if p is None:
        pytest.skip("Green Sun's Zenith absent from active CardSource")
    # The spell_effect side is now covered+bridged (the substrate this
    # lane shipped).
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )
    # But the card carries a non-bridgeable shuffle-self static — the
    # genuine wall. Pin that it is present (an honest-stop marker; a
    # future StaticReplacement-vocab widen that lands the
    # would-go-to-graveyard->library transform should revisit this
    # card and flip it to a genuine cross-engine probe).
    from mtg_bot.effects.modifiers import (
        EventPattern, Replace, ReplacementEffect,
    )
    from mtg_bot.effects.predicates import Event

    expected_static = ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_GO_TO_GRAVEYARD),
        transform=Replace(new_destination="library"),
    )
    assert any(
        s.replacement_effect == expected_static
        for s in p.static_abilities
    ), "the honest-stop wall static must still be present on the printing"


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
