"""Aura-attachment substrate — Phase 1 first-deliverable tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1.

**This slice ships the substrate ONLY:**

* :class:`mtg_bot.parity.cross_engine.CardDef` gains the aura
  representation fields (``is_aura`` / ``aura_enchant_type`` /
  ``aura_yours_only`` / ``aura_power_bonus`` / ``aura_toughness_bonus``
  / ``aura_granted_keywords``).
* :func:`mtg_bot.parity.cross_engine.build_rust_state` emits the
  matching aura keys into the registry ``printing_dict``; Rust's
  ``parse_printing`` silently ignores unknown keys so the round-trip is
  inert on the Rust side this slice (the long-pole cast-time
  enchant-target decision + aura-resolution arm + CR-704.5n SBA are
  honest-stopped — see Phase 1 §3 of the plan).
* :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`
  materializes the Python ``CardPrinting`` aura fields (including the
  ``"Aura"`` subtype + ``Enchantment - Aura`` type-line) so Python's
  ``CardPrinting.is_aura`` derivation fires correctly on a CardDef-built
  printing.
* :func:`mtg_bot.parity.trajectory._printing_is_bridge_simple_aura` is
  the §2 positive-allowlist predicate per the plan §3 Phase 1 step 7.
  It is NOT yet OR'd into :func:`_filter_deck_to_bridge_supported`'s
  5-disjunct admit chokepoint — substrate-only, no Aura reaches the
  bench this slice.
* :func:`mtg_bot.parity.trajectory._printing_to_card_def` gains the
  aura branch (callable directly for tests; unreachable from the loader
  this slice because the predicate is not wired in).

**Honest-stop sentinels (Phase 1 remaining items, NOT in this slice):**

* Rust ``parse_printing`` arm to consume the new ``is_aura`` /
  ``aura_enchant_type`` / ``aura_yours_only`` /
  ``aura_equipment_bonuses`` registry-dict keys (step 1+2 partial).
* Rust cast-time enchant-target decision over legal hosts per
  ``aura_enchant_type`` / ``aura_yours_only`` (step 3 — the long
  pole).
* Rust Aura-resolution arm that stamps ``aura.attached_to =
  Some(host_id)`` + applies the layer-7 P/T + keyword grant via an
  ``attached_to``-scan analogue of Python's ``game._effective_*`` (step
  4).
* Rust CR-704.5n SBA (bury host-less Aura) + host-leave bury (step 5).
* Bidirectional bridge arms across the new Rust state slots (step 6).
* One-line OR-in of ``_printing_is_bridge_simple_aura`` into
  :func:`_filter_deck_to_bridge_supported`'s 5-disjunct (step 7
  wire-up).

Once those land, Phase 1 closes for sub-shape S1 (Frantic Strength,
Shardmage's Rescue — both 0 EoE 17lands decks; the value is the
substrate). Phase 2 adds S2 control-changing Auras (Duskmourn's
Domination), which then unblocks Tractor Beam's static halves; Phase 3
ships the residue Aura-shape Effects (Meltstrider's Resolve, Pain for
All, Tractor Beam composition); Phase 4 ships S3/S4 (Moonlit Meditation
+ Chorale of the Void / Cracked Skull / Sporogenic Infection — each
needs additional substrate on top of attach).
"""

from __future__ import annotations

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _FOREST,
    _card_def_to_python_printing,
    build_python_state,
)
from mtg_bot.parity.trajectory import (
    _filter_deck_to_bridge_supported,
    _printing_is_bridge_simple_aura,
    _printing_to_card_def,
)


# ---------------------------------------------------------------------------
# CardDef shape: the new aura fields exist with back-compat defaults
# ---------------------------------------------------------------------------


def test_carddef_has_aura_fields_with_back_compat_defaults():
    """The CardDef dataclass MUST carry the Phase-1 aura fields and
    every one MUST default to the no-aura value so every pre-substrate
    CardDef is bit-identical to before this slice landed."""
    fields = CardDef.__dataclass_fields__
    assert "is_aura" in fields
    assert "aura_enchant_type" in fields
    assert "aura_yours_only" in fields
    assert "aura_power_bonus" in fields
    assert "aura_toughness_bonus" in fields
    assert "aura_granted_keywords" in fields
    # Back-compat defaults — a CardDef built with no aura args is
    # bit-identical to a pre-substrate CardDef.
    cd = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    assert cd.is_aura is False
    assert cd.aura_enchant_type == "creature"
    assert cd.aura_yours_only is False
    assert cd.aura_power_bonus == 0
    assert cd.aura_toughness_bonus == 0
    assert cd.aura_granted_keywords == ()


def test_carddef_is_frozen_with_aura_fields():
    """The aura fields preserve the frozen-dataclass contract — the
    same hash-discipline every other CardDef field obeys."""
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    # frozen=True → mutation raises
    with pytest.raises(Exception):
        cd.is_aura = False  # type: ignore[misc]
    # And the dataclass is hashable (frozen contract).
    assert hash(cd) == hash(cd)


# ---------------------------------------------------------------------------
# Python-side bridge: _card_def_to_python_printing materialization
# ---------------------------------------------------------------------------


def test_python_bridge_non_aura_carddef_is_bit_identical_pre_substrate():
    """A non-aura CardDef (``is_aura=False`` default) materializes a
    Python CardPrinting whose aura-related fields are exactly the
    Python defaults — bit-identical to a pre-substrate materialization."""
    cd = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    pr = _card_def_to_python_printing(cd)
    assert pr.is_aura is False
    assert pr.aura_enchant_type == "creature"  # Python's default
    assert pr.aura_yours_only is False  # Python's default
    assert pr.equipment_bonuses is None  # Python's default


def test_python_bridge_aura_static_pt_carddef_materializes_correctly():
    """An S1 static-P/T Aura CardDef (Frantic Strength shape) builds a
    Python CardPrinting that fires ``is_aura`` (the predicate derives
    from card_types contains Enchantment AND subtypes contains Aura per
    ``cards/base.py:1060``)."""
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    pr = _card_def_to_python_printing(cd)
    assert pr.is_aura is True
    assert "Enchantment" in pr.card_types
    assert "Aura" in pr.subtypes
    assert pr.aura_enchant_type == "creature"
    assert pr.aura_yours_only is False
    assert pr.equipment_bonuses == (2, 2, frozenset({"trample"}))


def test_python_bridge_aura_yours_only_round_trips():
    """The ``aura_yours_only`` flag (Shardmage's Rescue shape) round-
    trips through the bridge unchanged."""
    cd = CardDef(
        name="Shardmage's Rescue",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("W", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_yours_only=True,
        aura_power_bonus=1,
        aura_toughness_bonus=1,
        aura_granted_keywords=(),
    )
    pr = _card_def_to_python_printing(cd)
    assert pr.is_aura is True
    assert pr.aura_yours_only is True
    # Empty granted keywords + nonzero bonus -> equipment_bonuses populated.
    assert pr.equipment_bonuses == (1, 1, frozenset())


def test_python_bridge_aura_bare_no_bonus_yields_none_equipment_bonuses():
    """An Aura CardDef with zero P/T bonus and empty granted keywords
    materializes a Python CardPrinting with ``equipment_bonuses=None``
    (the no-grant shape)."""
    cd = CardDef(
        name="Bare Aura",
        card_type="Enchantment",
        is_aura=True,
        aura_enchant_type="creature",
    )
    pr = _card_def_to_python_printing(cd)
    assert pr.is_aura is True
    assert pr.equipment_bonuses is None


def test_python_bridge_aura_artifact_enchant_type():
    """An Aura that enchants ARTIFACT (Hardlight Containment shape;
    plan §1 calls out artifact-enchanting as a valid Phase-1 sub-shape
    variant) round-trips with ``aura_enchant_type='artifact'``."""
    cd = CardDef(
        name="Artifact Aura",
        card_type="Enchantment",
        mana_cost_generic=1,
        is_aura=True,
        aura_enchant_type="artifact",
        aura_power_bonus=0,
        aura_toughness_bonus=0,
    )
    pr = _card_def_to_python_printing(cd)
    assert pr.is_aura is True
    assert pr.aura_enchant_type == "artifact"


# ---------------------------------------------------------------------------
# Rust-side bridge: build_rust_state registers aura CardDef without crash
# ---------------------------------------------------------------------------


def _aura_spec(aura_card_def):
    """Build a smallest possible DeckSpec carrying a Forest + the
    given Aura CardDef. Both libraries are Forests so neither engine
    tries to draw the (uncastable in synthetic state) Aura."""
    return DeckSpec(
        card_defs=(_FOREST, aura_card_def),
        p0_library=("Forest",) * 7,
        p1_library=("Forest",) * 7,
    )


@pytest.mark.skipif(
    pytest.importorskip("importlib.util") is None,
    reason="never skip — placeholder for missing-rust skip",
)
def test_rust_side_aura_carddef_registers_without_crash():
    """The Rust registry MUST accept a CardDef carrying the new aura
    keys without raising. ``parse_printing`` silently ignores any
    unknown key (verified at ``rust/src/cards.rs:8341`` —
    ``match dict.get_item { Some => extract, None => default }`` for
    every optional field), so this slice's emission is inert on the
    Rust side until the parse arm lands in a later Phase-1 step."""
    import importlib
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    from mtg_bot.parity.cross_engine import build_rust_state
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    spec = _aura_spec(cd)
    rs = build_rust_state(spec)
    # The Aura registered as the second printing (Forest is first).
    assert rs.registry_size == 2


def test_python_side_aura_carddef_builds_state_with_correct_printing():
    """``build_python_state`` materializes the Aura printing onto every
    library object built from the spec — the printing's ``is_aura``
    fires, and its equipment_bonuses tuple matches the CardDef's
    declared grant."""
    cd = CardDef(
        name="Shardmage's Rescue",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("W", 1),),
        is_aura=True,
        aura_yours_only=True,
        aura_power_bonus=1,
        aura_toughness_bonus=1,
    )
    spec = DeckSpec(
        card_defs=(_FOREST, cd),
        p0_library=("Forest", "Shardmage's Rescue", "Forest"),
        p1_library=("Forest", "Forest", "Forest"),
    )
    state = build_python_state(spec)
    aura_obj = state.players[0].library[1]
    assert aura_obj.printing.name == "Shardmage's Rescue"
    assert aura_obj.printing.is_aura is True
    assert aura_obj.printing.aura_yours_only is True
    assert aura_obj.printing.equipment_bonuses == (1, 1, frozenset())


# ---------------------------------------------------------------------------
# Loader predicate: _printing_is_bridge_simple_aura
# ---------------------------------------------------------------------------


def _live_printing(name):
    """Look up a live (parser-built) CardPrinting by name."""
    from mtg_bot.cards.source import get_active_source
    return get_active_source().get_printings()[name]


def test_predicate_declines_non_aura():
    """A non-Aura printing (any Land / Creature / Instant / etc.) is
    positively declined — the predicate is the §2 positive-allowlist
    by aura-shape."""
    forest = _live_printing("Forest")
    assert _printing_is_bridge_simple_aura(forest) is False


def test_predicate_declines_every_live_eoe_aura_today():
    """**§2 verify-first**: at HEAD, every Aura in the live parser pool
    is positively declined by the predicate. This pins the round-61 N1
    scout's finding (``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §1)
    that the Phase-1 first-deliverable slice admits ZERO real Auras —
    Phase-1 S1 (Frantic Strength, Shardmage's Rescue) carry ``flash``
    which is outside :data:`_SAFE_KEYWORDS`; S2/S3/S4 are positively
    declined by the rider checks.

    When a Phase widens the admit set, this test's NAMED-decline list
    flips — drop the cards that now admit from the assert below and
    add per-card admit pins. This is the same verify-first discipline
    the warp / spell guardrails use."""
    from mtg_bot.cards.source import get_active_source
    pool = get_active_source().get_printings()
    declined: list[tuple[str, str]] = []
    admitted: list[str] = []
    for name, p in pool.items():
        if not getattr(p, "is_aura", False):
            continue
        if _printing_is_bridge_simple_aura(p):
            admitted.append(name)
        else:
            declined.append((name, "declined"))
    assert admitted == [], (
        f"Phase-1 first-deliverable admits NO live Aura. Newly-admitted "
        f"set: {admitted!r}. If this is intentional (a later Phase-1 step "
        f"widened the predicate's admit shape), update this pin to assert "
        f"the new expected admit list explicitly."
    )
    # Sanity: the parser pool has at least the 14 Auras the scout
    # documented; if it grew, we just want >= the round-61 count.
    assert len(declined) >= 14


def test_predicate_admits_synthetic_phase1_s1_aura():
    """A SYNTHETIC printing carrying ONLY the Phase-1 S1 admit shape
    (is_aura + safe-keyword-only granted-keywords + no triggers / no
    riders / parseable cost) IS admitted. This proves the predicate
    accepts the shape — when the Phase-1 Rust steps land + the loader
    wires the OR-in, a real S1 carrier whose ``flash`` is admitted (or
    whose static ``flash`` keyword is dropped on both sides) flips
    automatically."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    pr = CardPrinting(
        name="Synthetic S1 Aura",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Enchantment - Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        power=None,
        toughness=None,
        produces=frozenset(),
        aura_enchant_type="creature",
        aura_yours_only=False,
        # The S1 grant: +2/+2/trample. trample IS in _SAFE_KEYWORDS.
        equipment_bonuses=(2, 2, frozenset({"trample"})),
    )
    assert _printing_is_bridge_simple_aura(pr) is True


def test_predicate_declines_unsafe_granted_keyword():
    """The granted-keyword check on ``equipment_bonuses`` declines an
    Aura whose grant carries a keyword outside :data:`_SAFE_KEYWORDS`
    — even if the Aura is otherwise rider-free."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    pr = CardPrinting(
        name="Synthetic Unsafe-grant Aura",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Enchantment - Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        power=None,
        toughness=None,
        produces=frozenset(),
        aura_enchant_type="creature",
        # "flash" is NOT in _SAFE_KEYWORDS — this is the live-Aura
        # decline reason for Frantic Strength / Shardmage's Rescue,
        # mirrored here on a synthetic carrier so the granted-keyword
        # path is tested independently.
        equipment_bonuses=(1, 1, frozenset({"flash"})),
    )
    assert _printing_is_bridge_simple_aura(pr) is False


def test_predicate_declines_static_unsafe_keyword():
    """The printing's static-keyword check (mirroring the simple-
    creature guardrail) declines an Aura whose own ``keywords``
    frozenset contains a non-safe entry."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    pr = CardPrinting(
        name="Synthetic Static-Unsafe Aura",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Enchantment - Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset({"flash"}),
        aura_enchant_type="creature",
        equipment_bonuses=(1, 1, frozenset()),
    )
    assert _printing_is_bridge_simple_aura(pr) is False


def test_predicate_declines_aura_with_triggered_ability():
    """S4 sub-shape: an Aura with a triggered ability (Sheltered by
    Ghosts ETB, Chorale of the Void attack-trigger, ...) is positively
    declined — Phase 4 of the plan."""
    sheltered = _live_printing("Sheltered by Ghosts")
    assert sheltered.is_aura is True
    assert _printing_is_bridge_simple_aura(sheltered) is False


def test_predicate_declines_aura_with_control_swap():
    """S2 sub-shape: an Aura that grants control (Duskmourn's
    Domination, Tractor Beam) is positively declined — Phase 2 of the
    plan."""
    dd = _live_printing("Duskmourn's Domination")
    assert dd.is_aura is True
    assert dd.attached_grants_control is True
    assert _printing_is_bridge_simple_aura(dd) is False


def test_predicate_declines_aura_with_replacement():
    """S3 sub-shape: an Aura that carries the
    ``replaces_first_tokens_with_copies`` replacement effect (Moonlit
    Meditation, the 633-deck single-gated single-card S3 carrier per
    the plan §1) is positively declined — Phase 4 of the plan."""
    moonlit = _live_printing("Moonlit Meditation")
    assert moonlit.is_aura is True
    assert moonlit.replaces_first_tokens_with_copies is True
    assert _printing_is_bridge_simple_aura(moonlit) is False


# ---------------------------------------------------------------------------
# Loader wire-up: the predicate is NOT yet in the 5-disjunct
# (substrate-only — Phase 1 honest-stop sentinel)
# ---------------------------------------------------------------------------


def test_loader_does_not_yet_admit_any_aura():
    """**Honest-stop sentinel.** Even though the predicate is
    correctly defined + tested above,
    :func:`_filter_deck_to_bridge_supported` MUST NOT admit any Aura
    this slice — the predicate is NOT yet OR'd into the 5-disjunct
    admit chokepoint. When the Phase-1 Rust steps (cast-target
    decision + resolve arm + SBA) land, a one-line wire-up flip will
    close the gap; until then this pin guards against an accidental
    silent admit-widen.

    The pin works by trying to load a deck containing a known-Aura
    name (Frantic Strength) and asserting the Aura is dropped from
    the filtered name list."""
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    # Use a deck mix that hits the existing 5-disjunct (Forest) AND
    # includes an Aura that the §2 teeth would currently decline.
    deck = ["Forest", "Forest", "Frantic Strength", "Forest"]
    not_bridged_sink: list[str] = []
    filtered, _ = _filter_deck_to_bridge_supported(
        deck,
        printings,
        not_bridged_sink=not_bridged_sink,
    )
    assert "Frantic Strength" not in filtered, (
        "Loader silently admitted an Aura — the Phase-1 first-deliverable "
        "slice MUST keep the 5-disjunct unchanged. If Phase 1's remaining "
        "steps have landed AND _printing_is_bridge_simple_aura was OR'd "
        "in, drop this pin (it is the honest-stop sentinel)."
    )
    assert "Frantic Strength" in not_bridged_sink


def test_loader_still_admits_basic_land_unchanged():
    """Sanity: the existing 5-disjunct admit paths are bit-identical
    to before this slice — Phase-1 first-deliverable is substrate-
    only, no behavior change at the loader."""
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    deck = ["Forest", "Forest", "Forest"]
    filtered, card_defs = _filter_deck_to_bridge_supported(deck, printings)
    assert filtered == deck
    assert len(card_defs) == 1
    assert card_defs[0].name == "Forest"


# ---------------------------------------------------------------------------
# _printing_to_card_def: the aura branch (callable in isolation, NOT
# yet reached from the loader — substrate-only)
# ---------------------------------------------------------------------------


def test_printing_to_card_def_handles_synthetic_aura():
    """The aura branch of :func:`_printing_to_card_def` produces a
    CardDef whose aura fields match the source printing — even though
    the loader never reaches this branch this slice (the predicate is
    not in the 5-disjunct), the branch is callable directly. This pin
    proves the Phase-1 wire-up flip will work cleanly: drop one
    one-liner into the 5-disjunct and a real S1 carrier flows through
    end-to-end."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    pr = CardPrinting(
        name="Synthetic S1 Aura",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Enchantment - Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        power=None,
        toughness=None,
        produces=frozenset(),
        aura_enchant_type="creature",
        aura_yours_only=False,
        equipment_bonuses=(2, 2, frozenset({"trample"})),
    )
    assert _printing_is_bridge_simple_aura(pr) is True
    cd = _printing_to_card_def(pr)
    assert cd.is_aura is True
    assert cd.aura_enchant_type == "creature"
    assert cd.aura_yours_only is False
    assert cd.aura_power_bonus == 2
    assert cd.aura_toughness_bonus == 2
    assert cd.aura_granted_keywords == ("trample",)
    # Round-trip back through _card_def_to_python_printing reproduces
    # the printing's aura shape.
    pr2 = _card_def_to_python_printing(cd)
    assert pr2.is_aura is True
    assert pr2.aura_enchant_type == "creature"
    assert pr2.equipment_bonuses == (2, 2, frozenset({"trample"}))


def test_printing_to_card_def_handles_synthetic_aura_yours_only():
    """The aura branch round-trips ``aura_yours_only`` correctly — the
    Shardmage's Rescue shape (the second Phase-1 S1 carrier per the
    plan §1)."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    pr = CardPrinting(
        name="Synthetic Shardmage's Rescue",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Enchantment - Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        power=None,
        toughness=None,
        produces=frozenset(),
        aura_enchant_type="creature",
        aura_yours_only=True,
        equipment_bonuses=(1, 1, frozenset()),
    )
    assert _printing_is_bridge_simple_aura(pr) is True
    cd = _printing_to_card_def(pr)
    assert cd.is_aura is True
    assert cd.aura_yours_only is True
    assert cd.aura_power_bonus == 1
    assert cd.aura_toughness_bonus == 1
    assert cd.aura_granted_keywords == ()
