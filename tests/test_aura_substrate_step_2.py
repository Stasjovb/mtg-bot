"""Aura-attachment substrate — Phase 1 STEP 2 tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1 step 2.

**STEP 2 scope:** Rust ``parse_printing`` now reads the aura-key family
the Python bridge has been emitting since STEP 1 (round-77, commit
``fac76412``). Specifically:

* ``is_aura: bool`` (default False)
* ``aura_enchant_type: str`` (default "creature")
* ``aura_yours_only: bool`` (default False)
* ``aura_equipment_bonuses: {"power_bonus": int, "toughness_bonus":
  int, "granted_keywords": [str, ...]}`` (nested dict; absent ->
  (0, 0, []))

The values land in the Rust ``CardPrinting`` struct
(``rust/src/cards.rs:5908+``) and are exposed via four
``Registry.get_printing_*`` getters
(``get_printing_is_aura`` / ``get_printing_aura_enchant_type`` /
``get_printing_aura_yours_only`` / ``get_printing_aura_grant``).

**Inert until STEPs 3-6 land.** STEP 2 stores the values but no
downstream Rust consumer reads them yet (cast-time enchant-target
decision, resolution attach arm, CR-704.5n SBA, bidir bridge are all
later Phase-1 steps — honest-stopped per the plan §3). The tests below
prove the substrate is faithfully round-tripped through the Rust
parse path so the remaining steps can wire in without further parse
work.
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _FOREST,
    build_rust_state,
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _aura_spec(aura_card_def):
    """Smallest possible DeckSpec carrying Forest + the given Aura."""
    return DeckSpec(
        card_defs=(_FOREST, aura_card_def),
        p0_library=("Forest",) * 7,
        p1_library=("Forest",) * 7,
    )


def _mana_cost_dict(card_def):
    """Build the Rust-side mana_cost dict from a CardDef, mirroring
    the inline construction in
    ``cross_engine.build_rust_state`` (`cross_engine.py:10219-10221`).
    """
    base = (
        {"generic": card_def.mana_cost_generic}
        if card_def.mana_cost_generic
        else {}
    )
    base.update({color: n for color, n in card_def.mana_cost_colored})
    return base


def _build_registry_with_aura(aura_card_def):
    """Build a fresh ``mtg_bot_engine.Registry`` populated with Forest
    + the given Aura CardDef. Returns ``(reg, aura_pid)``. The
    constructed dict mirrors what ``build_rust_state`` emits for the
    Aura — this isolates the STEP-2 parse arm without dragging the
    full GameState build path."""
    import mtg_bot_engine
    reg = mtg_bot_engine.Registry()
    # Forest first (mirrors build_rust_state ordering — gives Aura
    # pid=1 below).
    forest_pid = reg.register_printing({
        "name": "Forest",
        "mana_cost": {},
        "card_types": ["Land"],
        "subtypes": ["Forest"],
        "supertypes": ["Basic"],
        "mana_produced": ["G"],
    })
    assert forest_pid == 0
    # Build the Aura registry dict the same way build_rust_state does.
    aura_dict = {
        "name": aura_card_def.name,
        "mana_cost": _mana_cost_dict(aura_card_def),
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
    }
    if aura_card_def.is_aura:
        aura_dict["is_aura"] = True
        aura_dict["aura_enchant_type"] = aura_card_def.aura_enchant_type
        if aura_card_def.aura_yours_only:
            aura_dict["aura_yours_only"] = True
        if (
            aura_card_def.aura_power_bonus
            or aura_card_def.aura_toughness_bonus
            or aura_card_def.aura_granted_keywords
        ):
            aura_dict["aura_equipment_bonuses"] = {
                "power_bonus": aura_card_def.aura_power_bonus,
                "toughness_bonus": aura_card_def.aura_toughness_bonus,
                "granted_keywords": [
                    kw.replace(" ", "_")
                    for kw in aura_card_def.aura_granted_keywords
                ],
            }
    aura_pid = reg.register_printing(aura_dict)
    assert aura_pid == 1
    return reg, aura_pid


# ---------------------------------------------------------------------------
# is_aura default + explicit
# ---------------------------------------------------------------------------


def test_rust_default_is_aura_false_for_non_aura_printing():
    """**Back-compat invariant.** A registry dict that omits the
    ``is_aura`` key parses with ``is_aura=False`` — every
    pre-substrate registry dict (Forest, Grizzly Bears, etc.) is
    bit-identical to before STEP 2."""
    _require_engine()
    import mtg_bot_engine
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Forest",
        "mana_cost": {"generic": 0},
        "card_types": ["Land"],
        "subtypes": ["Forest"],
        "supertypes": ["Basic"],
        "mana_produced": ["G"],
    })
    assert reg.get_printing_is_aura(pid) is False
    assert reg.get_printing_aura_enchant_type(pid) == "creature"
    assert reg.get_printing_aura_yours_only(pid) is False
    assert reg.get_printing_aura_grant(pid) == (0, 0, [])


def test_rust_is_aura_true_lands_from_dict():
    """The Rust parse arm reads ``is_aura=True`` off the registry
    dict and stores it in ``CardPrinting.is_aura``."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_is_aura(aura_pid) is True


def test_rust_aura_enchant_type_lands_creature():
    """``aura_enchant_type="creature"`` round-trips through the Rust
    parse arm."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_enchant_type(aura_pid) == "creature"


def test_rust_aura_enchant_type_lands_artifact():
    """``aura_enchant_type="artifact"`` round-trips through the Rust
    parse arm (Hardlight Containment shape — admitted in a later
    Phase)."""
    _require_engine()
    cd = CardDef(
        name="Synthetic Artifact Aura",
        card_type="Enchantment",
        mana_cost_generic=2,
        is_aura=True,
        aura_enchant_type="artifact",
    )
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_enchant_type(aura_pid) == "artifact"
    assert reg.get_printing_is_aura(aura_pid) is True


def test_rust_aura_yours_only_lands_true():
    """``aura_yours_only=True`` (Shardmage's Rescue shape) lands on
    the Rust side."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_yours_only(aura_pid) is True


def test_rust_aura_yours_only_default_false():
    """An Aura without ``aura_yours_only`` set lands with
    ``aura_yours_only=False`` (the Frantic Strength shape — bridge
    omits the key when False per ``cross_engine.py:10371-10373``)."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_yours_only(aura_pid) is False


# ---------------------------------------------------------------------------
# aura_equipment_bonuses sub-dict
# ---------------------------------------------------------------------------


def test_rust_aura_grant_pt_only():
    """An Aura with P/T bonus but no granted keywords lands with the
    correct (p, t, []) triple."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_grant(aura_pid) == (1, 1, [])


def test_rust_aura_grant_pt_and_keyword():
    """An Aura with both P/T and keyword grant lands with the full
    triple. Keywords use the underscore-form the bridge emits."""
    _require_engine()
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
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_grant(aura_pid) == (2, 2, ["trample"])


def test_rust_aura_grant_multi_keyword_with_space():
    """Granted keywords with spaces (``first strike``) round-trip via
    the bridge's underscore-mapping (``first_strike``). The order of
    the underlying tuple is preserved on the Rust side."""
    _require_engine()
    cd = CardDef(
        name="Synthetic Multi-Keyword Aura",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("W", 1),),
        is_aura=True,
        aura_power_bonus=0,
        aura_toughness_bonus=0,
        aura_granted_keywords=("first strike", "vigilance"),
    )
    reg, aura_pid = _build_registry_with_aura(cd)
    (p, t, kws) = reg.get_printing_aura_grant(aura_pid)
    assert (p, t) == (0, 0)
    assert set(kws) == {"first_strike", "vigilance"}


def test_rust_aura_grant_bare_no_bonus_omitted_yields_zero_triple():
    """An Aura with no P/T and no keywords causes the bridge to
    OMIT the ``aura_equipment_bonuses`` sub-dict entirely
    (``cross_engine.py:10374-10391``). Rust parses the absence to
    ``(0, 0, [])`` — the back-compat default. This pins the §2
    omission semantics for keyword-less, P/T-less Auras (a future
    sub-shape that might exist as pure rules-text-only)."""
    _require_engine()
    cd = CardDef(
        name="Synthetic Bare Aura",
        card_type="Enchantment",
        mana_cost_generic=2,
        is_aura=True,
        aura_power_bonus=0,
        aura_toughness_bonus=0,
        aura_granted_keywords=(),
    )
    reg, aura_pid = _build_registry_with_aura(cd)
    assert reg.get_printing_aura_grant(aura_pid) == (0, 0, [])
    # is_aura still True even though no equipment_bonuses sub-dict.
    assert reg.get_printing_is_aura(aura_pid) is True


# ---------------------------------------------------------------------------
# end-to-end via build_rust_state (the real bridge path)
# ---------------------------------------------------------------------------


def test_build_rust_state_admits_aura_carddef_without_crash():
    """End-to-end via the real ``build_rust_state`` path: the Aura
    CardDef registers cleanly and the Rust state's registry holds
    the Aura at pid=1 (Forest is pid=0)."""
    _require_engine()
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
    assert rs.registry_size == 2


# ---------------------------------------------------------------------------
# Type-error pins: a malformed registry dict raises rather than
# silently accepting bad input (the same parse-strict shape every
# other CardPrinting field uses).
# ---------------------------------------------------------------------------


def test_rust_is_aura_wrong_type_raises():
    """A non-bool ``is_aura`` raises a ValueError at parse time."""
    _require_engine()
    import mtg_bot_engine
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="is_aura must be a bool"):
        reg.register_printing({
            "name": "Bad Aura",
            "mana_cost": {"generic": 1},
            "card_types": ["Enchantment"],
            "is_aura": "yes",  # NOT a bool
        })


def test_rust_aura_enchant_type_wrong_type_raises():
    """A non-string ``aura_enchant_type`` raises a ValueError."""
    _require_engine()
    import mtg_bot_engine
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="aura_enchant_type must be a string"):
        reg.register_printing({
            "name": "Bad Aura",
            "mana_cost": {"generic": 1},
            "card_types": ["Enchantment"],
            "aura_enchant_type": 42,  # NOT a string
        })


def test_rust_aura_equipment_bonuses_wrong_type_raises():
    """A non-dict ``aura_equipment_bonuses`` raises a ValueError."""
    _require_engine()
    import mtg_bot_engine
    reg = mtg_bot_engine.Registry()
    with pytest.raises(
        ValueError, match="aura_equipment_bonuses must be a dict"
    ):
        reg.register_printing({
            "name": "Bad Aura",
            "mana_cost": {"generic": 1},
            "card_types": ["Enchantment"],
            "aura_equipment_bonuses": [2, 2, []],  # NOT a dict
        })
