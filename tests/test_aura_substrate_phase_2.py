"""Aura-attachment substrate — Phase 2 first deliverable tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 2 +
``docs/AURA_ATTACHMENT_PHASE1_DESIGN.md`` §3.7 (the symmetric-drop
``flash`` admit rationale).

**Phase 2 first-deliverable scope (round-79).** Phase 2 per the plan
§3 is the full S2 (control-changing) Aura substrate — a multi-round
Rust slice. The first deliverable of Phase 2, scoped to **admit the
first live EoE Aura without any new Rust work**, widens the
``_printing_is_bridge_simple_aura`` predicate's static-keyword check
to admit ``flash`` (round-39 Ward / round-59 shockland
symmetric-drop precedent — the CardDef bridge does NOT propagate the
source printing's ``keywords`` field through to the materialized
CardDef → CardPrinting round-trip on either engine, so the rider is
symmetrically dropped on both bridge sides bit-equally).

Cards admitted by Phase 2 first deliverable:

* **Frantic Strength** — first live EoE Aura through the loader.
  Cleanest S1 carrier: ``(+2,+2,{trample})``, no ``aura_yours_only``,
  no rider beyond ``flash``. 0 EoE 17lands decks — the substrate's
  value is the **first live admit**, not the deck count.
* **Shardmage's Rescue** — second S1 carrier. ``aura_yours_only=True``
  (independently bridge-correct on both engines per
  ``actions.py:1337-1357`` / ``state_ops_cast.rs:2000-2055``); the
  conditional ``entered_this_turn``-gated hexproof grant is not parsed
  by the live parser at all (shared CR-incompleteness on both bridge
  sides — symmetric).

The full Phase 2 of the plan §3 (S2 control-changing Auras —
Duskmourn's Domination + Tractor Beam's static halves) remains
deferred to a follow-up Rust slice (layer-2 control-swap / layer-6
lose-abilities / layer-7 set-base-PT static-grant-on-attach analogue
of ``apply_aura_static_grants_on_attach``).

**SL entry mandatory:** ``docs/SEARCH_LIMITATIONS.md`` carries the
"Aura ``flash`` cast-timing rider dropped symmetrically" entry,
sibling to the round-39 Ward / round-59 shockland precedents.
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _FOREST,
    _card_def_to_python_printing,
    build_python_state,
)
from mtg_bot.parity.trajectory import (
    _AURA_SAFE_EXTRA_KEYWORDS,
    _SAFE_KEYWORDS,
    _filter_deck_to_bridge_supported,
    _printing_is_bridge_simple_aura,
    _printing_to_card_def,
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Constant pins
# ---------------------------------------------------------------------------


def test_aura_safe_extra_keywords_is_exactly_flash():
    """Phase 2 first deliverable extends the Aura-keyword admit set by
    exactly one keyword: ``flash``. Pin the constant so any future
    widen of the Aura-only set is explicit — a creature-side widen of
    the broader :data:`_SAFE_KEYWORDS` must go through its own
    per-keyword parity verification (combat-side semantics)."""
    assert _AURA_SAFE_EXTRA_KEYWORDS == frozenset({"flash"})


def test_safe_keywords_unchanged_by_phase_2_widen():
    """The broader :data:`_SAFE_KEYWORDS` (used by
    ``_printing_is_bridge_simple_creature``) MUST NOT change in Phase
    2's first deliverable — only the Aura-only extension set carries
    ``flash``. This pin makes any accidental cross-pollination of
    ``flash`` into the creature predicate explicit."""
    assert "flash" not in _SAFE_KEYWORDS


# ---------------------------------------------------------------------------
# Live-EoE: the two S1 carriers now admit
# ---------------------------------------------------------------------------


def _live_printing(name):
    from mtg_bot.cards.source import get_active_source
    return get_active_source().get_printings()[name]


def test_phase_2_admits_frantic_strength_live():
    """Frantic Strength — the cleanest live EoE S1 Aura — passes the
    Phase 2 first-deliverable predicate. This is the **first live EoE
    Aura** to admit through the loader."""
    fs = _live_printing("Frantic Strength")
    assert fs.is_aura is True
    assert fs.keywords == frozenset({"flash"})
    assert fs.equipment_bonuses == (2, 2, frozenset({"trample"}))
    assert _printing_is_bridge_simple_aura(fs) is True


def test_phase_2_admits_shardmages_rescue_live():
    """Shardmage's Rescue — the second live EoE S1 Aura — also passes
    the predicate. ``aura_yours_only=True`` is correctly threaded
    through both engines; the conditional hexproof grant is not parsed
    by the live parser (shared CR-incompleteness, symmetric)."""
    sr = _live_printing("Shardmage's Rescue")
    assert sr.is_aura is True
    assert sr.aura_yours_only is True
    assert sr.keywords == frozenset({"flash"})
    assert sr.equipment_bonuses == (1, 1, frozenset())
    assert _printing_is_bridge_simple_aura(sr) is True


# ---------------------------------------------------------------------------
# CardDef bridge: flash is symmetrically dropped on the aura arm
# ---------------------------------------------------------------------------


def test_carddef_bridge_drops_flash_symmetrically_for_frantic_strength():
    """The §2 safety argument: the CardDef bridge (the aura arm in
    :func:`_printing_to_card_def`) does NOT propagate the source
    printing's ``keywords`` field. Both engines materialize the Aura
    with NO ``flash`` keyword on the Aura's printing. The drop is
    therefore bit-equal cross-engine — this is the round-39 Ward /
    round-59 shockland precedent applied to the Aura cast-timing
    rider."""
    fs = _live_printing("Frantic Strength")
    cd = _printing_to_card_def(fs)
    assert cd is not None
    # The Aura's CardDef carries the bonus tuple (the grant) but not
    # the source's static keywords — flash does not flow through.
    assert cd.is_aura is True
    assert cd.aura_power_bonus == 2
    assert cd.aura_toughness_bonus == 2
    assert cd.aura_granted_keywords == ("trample",)
    # The CardDef itself carries an empty keywords tuple (the broad
    # keywords field is for creature riders; the aura arm doesn't fill
    # it). Same on the Python re-materialization:
    assert cd.keywords == ()
    py_pr = _card_def_to_python_printing(cd)
    # Both engines materialize the Aura with empty keywords — flash is
    # gone from BOTH sides post-bridge.
    assert py_pr.keywords == frozenset()
    assert py_pr.is_aura is True
    assert py_pr.equipment_bonuses == (2, 2, frozenset({"trample"}))


def test_carddef_bridge_drops_flash_symmetrically_for_shardmages_rescue():
    """Same symmetric-drop property for Shardmage's Rescue —
    ``aura_yours_only`` survives the round-trip (it's an aura field,
    not a keyword), ``flash`` is dropped."""
    sr = _live_printing("Shardmage's Rescue")
    cd = _printing_to_card_def(sr)
    assert cd is not None
    assert cd.is_aura is True
    assert cd.aura_yours_only is True
    assert cd.aura_power_bonus == 1
    assert cd.aura_toughness_bonus == 1
    assert cd.aura_granted_keywords == ()
    assert cd.keywords == ()
    py_pr = _card_def_to_python_printing(cd)
    assert py_pr.keywords == frozenset()
    assert py_pr.is_aura is True
    assert py_pr.aura_yours_only is True


# ---------------------------------------------------------------------------
# Loader: a deck with Frantic Strength + creatures + lands flows
# through and produces matching Python + Rust state
# ---------------------------------------------------------------------------


def test_loader_admits_real_eoe_frantic_strength_deck():
    """A deck mixing Forest + a real bridged creature + Frantic Strength
    flows entirely through the loader (no card dropped to the
    not-bridged sink)."""
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    # Pick a known bridge-simple creature. Spire Greyhound (1/2 {1}{W}
    # vigilance) historically admits; fall back to any vigilance
    # creature in the pool if naming drifts.
    bridge_creatures = [
        name for name, pr in printings.items()
        if "Creature" in pr.card_types
        and not pr.is_aura
        and pr.power is not None
        and pr.toughness is not None
        and not pr.triggered_abilities
        and not pr.activated_abilities
        and not pr.static_abilities
        and (not pr.keywords or pr.keywords.issubset(_SAFE_KEYWORDS))
        and not pr.warp_cost and not pr.kicker_cost
        and not pr.impending_cost and not pr.room_halves
        and pr.loyalty is None
        and not pr.cost_reductions
        and not pr.external_cost_reductions
        and not pr.attached_grants_control
    ]
    assert bridge_creatures, (
        "Need at least one bridge-simple creature in the live EoE pool"
    )
    creature_name = bridge_creatures[0]
    deck = ["Forest"] * 20 + [creature_name] * 4 + ["Frantic Strength"] * 2
    not_bridged_sink: list[str] = []
    filtered, card_defs = _filter_deck_to_bridge_supported(
        deck, printings, not_bridged_sink=not_bridged_sink,
    )
    assert "Frantic Strength" in filtered
    assert filtered.count("Frantic Strength") == 2
    # Frantic Strength MUST NOT appear in the not-bridged sink.
    assert "Frantic Strength" not in not_bridged_sink
    # The CardDef set carries the Aura.
    aura_defs = [cd for cd in card_defs if cd.name == "Frantic Strength"]
    assert len(aura_defs) == 1
    assert aura_defs[0].is_aura is True


# ---------------------------------------------------------------------------
# Cross-engine: the aura admitted by Phase 2 round-trips bit-identically
# (Python + Rust build_state on the same DeckSpec)
# ---------------------------------------------------------------------------


def test_phase_2_aura_decks_pec_round_trips_python_rust():
    """A DeckSpec carrying Frantic Strength's CardDef shape (no
    static ``keywords`` — the bridge drops them) builds both engines'
    states with byte-equal aura representations. This is the strongest
    pre-cast cross-engine pin: from the SAME CardDef, BOTH engines
    materialize the Aura printing identically."""
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        build_rust_registry,
        read_rust_printing_aura_fields,
    )
    # The Frantic Strength CardDef shape (what the loader produces).
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_yours_only=False,
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    spec = DeckSpec(
        card_defs=(_FOREST, cd),
        p0_library=("Forest", "Forest", "Frantic Strength"),
        p1_library=("Forest", "Forest", "Forest"),
    )
    # Python side
    py_state = build_python_state(spec)
    aura_obj = next(
        o for o in py_state.players[0].library
        if o.printing.name == "Frantic Strength"
    )
    assert aura_obj.printing.is_aura is True
    # Symmetric drop: the Python-side printing has NO flash keyword.
    assert aura_obj.printing.keywords == frozenset()
    assert aura_obj.printing.equipment_bonuses == (
        2, 2, frozenset({"trample"})
    )

    # Rust side — registry-only build to surface the aura fields.
    reg, _ = build_rust_registry(spec)
    # Forest is printing 0, Frantic Strength is printing 1 (the
    # build_rust_registry helper assigns ids in CardDefs order — the
    # STEP-6 tests use printing_id=1 for the aura when the spec is
    # (Forest, aura)).
    rust_fields = read_rust_printing_aura_fields(reg, 1)
    assert rust_fields["is_aura"] is True
    assert rust_fields["aura_enchant_type"] == "creature"
    assert rust_fields["aura_yours_only"] is False
    # Both engines: aura_power_bonus=2, aura_toughness_bonus=2,
    # trample. Symmetric drop on flash.
    assert rust_fields["equipment_bonuses"] == (
        2, 2, frozenset({"trample"})
    )
