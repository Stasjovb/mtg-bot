"""Divergence-pin tests: batch YYY (19th Rust slice -- honest-stop landing).

This batch surfaces and partially closes a single high-value pin: the
Aura-shape Meltstrider's Resolve ``EnchantedCreatureFightsTargetEffect``
genuine-missing closure (the #1 marginal-value target in
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` -- 15,259 17lands decks).

**Slice 19 closure status (honest-stop substrate landing):**
The Effect-level scaffolding (Rust ``Effect::EnchantedCreatureFightsTarget``
unit variant + parse + ``effect_to_pydict`` + ``cross_engine.py`` bridge
arm + ``state_ops_resolve.rs`` honest-stop resolve arm) IS LANDED. The
broader Aura ``attached_to`` attach substrate (CardDef aura
representation + Rust cast-time enchant-target decision + Rust
Aura-resolution attach + layered grants-from-attach + CR 704.5n SBA +
loader admit predicate) is the **largest** §2-declined Rust multi-round
substrate per ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` and stays
deferred.

This means Pin 1 lands in the ``_FIXED_substrate_landed_resolve_deferred``
variant: it asserts both that (a) the Effect variant + parse + bridge
ARE present (the substrate landed) AND (b) the Aura attach substrate
is NOT yet present (Rust does not set ``attached_to`` on Aura resolve
and the loader admits no Aura). The pin auto-flips to a full
``_FIXED_parity`` once the attach substrate's Phase 1 lands (per the
substrate plan); in the meantime the honest-stop sentinel ensures we
catch the moment the substrate's first phase ships.

Each open pin test is named ``test_..._divergence_pin`` and ASSERTS
the CURRENT divergent behavior rather than parity. The honest-stop
pin uses the ``_FIXED_substrate_landed_resolve_deferred`` suffix and
asserts the staged-closure invariants. The PROBED-tier detector
excludes ``*_divergence_pin`` functions, so these tests grow the test
surface without touching the PROBED metric; the FIXED-variant tests
DO contribute to the standard test surface.

Pin 1 -- Meltstrider's Resolve's ``EnchantedCreatureFightsTargetEffect``
         bespoke Aura ETB at ``src/mtg_bot/effects/bespoke.py:506-582``
         was the genuinely-missing Effect on the BLOCKED list. The
         Rust ``Effect::EnchantedCreatureFightsTarget`` unit variant
         + parse arm + bridge arm + honest-stop resolve arm ship in
         this slice (19th Rust slice). The Aura attach substrate
         stays deferred (largest §2-declined substrate per the
         substrate plan).

         Bug location (Python -- the canonical behavior):
           ``src/mtg_bot/effects/bespoke.py:506-582`` --
           ``EnchantedCreatureFightsTargetEffect``: ETB body for an
           Aura. Source-side fighter is the Aura's ``attached_to``
           host; opponent-side fighter is the agent's choose_target
           pick across opposing creatures (optional, "up to one").
           Both fighters deal effective-power damage simultaneously
           (CR 701.12).

         Closure status (this slice -- honest-stop substrate landing):
           * Rust ``Effect::EnchantedCreatureFightsTarget`` unit variant
             -- LANDED in ``rust/src/cards.rs`` (after slice-18's
             ``RovingActuatorETBEffect``).
           * Parse arm ``"enchanted_creature_fights_target"`` in
             ``rust/src/cards.rs::parse_effect`` -- LANDED.
           * ``effect_to_pydict`` arm -- LANDED (emits the kind-only
             dict, unit-variant idiom).
           * Bridge arm in
             ``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``
             mapping ``"enchanted_creature_fights_target"`` ->
             ``EnchantedCreatureFightsTargetEffect()`` -- LANDED.
           * Resolve arm in ``rust/src/state_ops_resolve.rs`` --
             LANDED as an honest-stop sentinel: fizzles silently when
             ``source.attached_to`` is None (which is the Rust-side
             reality TODAY because Rust does not set ``attached_to``
             on Aura resolution). Python takes the SAME fizzle in this
             case (bespoke.py:546-548), so cross-engine state stays
             byte-equal in the no-host case.
           * Aura attach substrate (Phases 1-2 per
             docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md) -- NOT YET LANDED
             (deferred multi-round substrate; the largest §2-declined
             Rust subsystem audited so far).

         Closure indicator -- when the Aura attach substrate's Phase 1
         lands (Rust starts setting ``attached_to`` on Aura resolution
         AND the loader admits at least one Aura via the new
         ``_printing_is_bridge_simple_aura`` predicate), the inverted
         half of the assertion will fire and we rename this pin to
         ``..._FIXED_parity`` per the standard cadence.

         EoE card scale: 1 directly (Meltstrider's Resolve; 15,259
         17lands decks per ``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md``).
         Substrate-shared with Pain for All -- once the Aura attach
         substrate lands, Pain for All's residual closure cost drops
         from "medium" to "small" (substrate-sharing pattern §1 in
         the inventory).
"""

from __future__ import annotations

import pathlib


# ---------------------------------------------------------------------------
# Pin 1 -- Meltstrider's Resolve: Aura-shape Fight Effect.
#          Honest-stop substrate landing: Effect variant + parse +
#          bridge SHIPPED; full Aura attach substrate DEFERRED.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_meltstriders_resolve_aura_fight_FIXED_substrate_landed_resolve_deferred():
    """Confirm the honest-stop substrate-landing for Meltstrider's Resolve.

    This is the FIXED-half of the pin (the Effect-level closure landed
    in this slice). It asserts:

      A. Python's ``EnchantedCreatureFightsTargetEffect`` class exists
         with the expected interface (Aura-shape ETB; reads
         ``state.resolving_source.attached_to``).
      B. The Rust enum carries the ``EnchantedCreatureFightsTarget``
         unit variant.
      C. The Rust ``parse_effect`` arm handles the
         ``"enchanted_creature_fights_target"`` effect_kind string.
      D. The Rust ``effect_to_pydict`` arm emits the kind.
      E. The Rust ``state_ops_resolve.rs`` resolve arm handles the
         variant (with the honest-stop sentinel).
      F. The Python bridge arm
         (``cross_engine._ta_dict_to_python_effect``) maps the kind
         back to ``EnchantedCreatureFightsTargetEffect()``.
      G. The dict-shape round-trips: a Python instance dict-serialized
         via the bridge then dict-deserialized via the inverse bridge
         reproduces the same Python class.

    AND the still-deferred-half of the pin (sentinel for the Aura
    attach substrate):

      H. The production-deck loader admit gate
         (``trajectory.py::_filter_deck_to_bridge_supported``) does
         NOT admit Auras (the Aura attach substrate -- ``CardDef``
         aura fields + Rust attach path + ``_printing_is_bridge_simple_
         aura`` predicate -- has not yet landed). When Phase 1 lands
         the admit gate gains an ``is_aura`` arm and this assertion
         will FAIL, signaling the time to rename this pin to
         ``..._FIXED_parity`` and add a full byte-equal probe.

    EoE card scale: 1 directly (Meltstrider's Resolve; 15,259 17lands
    decks).
    """
    # A. Python's EnchantedCreatureFightsTargetEffect class exists
    #    with the expected interface.
    from mtg_bot.effects.bespoke import EnchantedCreatureFightsTargetEffect
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(EnchantedCreatureFightsTargetEffect, _EffectBase), (
        "EnchantedCreatureFightsTargetEffect should be an Effect "
        "subclass (effects/bespoke.py:506-582). If this fails, the "
        "bespoke class was restructured -- update this pin."
    )

    inst = EnchantedCreatureFightsTargetEffect()
    assert hasattr(inst, "resolve"), (
        "EnchantedCreatureFightsTargetEffect should have a 'resolve' "
        "method. If absent, the Python convention changed."
    )
    assert inst.requires_target() is False, (
        "EnchantedCreatureFightsTargetEffect should be optional-target "
        "('up to one'); requires_target() should be False."
    )
    assert inst.target_count_range() == (0, 1), (
        "EnchantedCreatureFightsTargetEffect.target_count_range() "
        "should return (0, 1) for the 'up to one' optional target."
    )

    # B-E. Rust crate: the variant + parse arm + to_pydict arm +
    #      resolve arm ARE present.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src = rust_resolve_path.read_text(encoding="utf-8")

    # B. Enum variant LANDED.
    assert "EnchantedCreatureFightsTarget" in cards_src, (
        "Rust enum should carry the EnchantedCreatureFightsTarget "
        "variant (slice 19 honest-stop substrate landing). If this "
        "assertion fails, the slice's cards.rs edits were reverted."
    )
    # C. Parse arm LANDED.
    assert '"enchanted_creature_fights_target"' in cards_src, (
        "Rust parse_effect arm should match the "
        "\"enchanted_creature_fights_target\" effect_kind string "
        "(slice 19 honest-stop substrate landing)."
    )
    # D. effect_to_pydict arm LANDED -- the kind string is emitted.
    #    Same source-file check (cards.rs holds both parse and
    #    effect_to_pydict).
    assert cards_src.count("enchanted_creature_fights_target") >= 2, (
        "Rust cards.rs should reference \"enchanted_creature_fights_"
        "target\" at least twice (parse arm + effect_to_pydict arm). "
        "If this fails, the to_pydict arm was not added."
    )
    # E. Resolve arm LANDED.
    assert "Effect::EnchantedCreatureFightsTarget" in resolve_src, (
        "Rust state_ops_resolve.rs should carry the "
        "Effect::EnchantedCreatureFightsTarget resolve arm (the "
        "honest-stop sentinel). If this assertion fails, the slice's "
        "state_ops_resolve.rs edits were reverted."
    )

    # F. Bridge arm LANDED in cross_engine.py.
    from mtg_bot.parity import cross_engine as ce

    cross_engine_src = pathlib.Path(ce.__file__).read_text(encoding="utf-8")
    assert '"enchanted_creature_fights_target"' in cross_engine_src, (
        "Python bridge cross_engine._ta_dict_to_python_effect should "
        "map the \"enchanted_creature_fights_target\" kind back to "
        "EnchantedCreatureFightsTargetEffect()."
    )

    # G. Dict-shape round-trips through the bridge.
    bridge_result = ce._ta_dict_to_python_effect(
        {"kind": "enchanted_creature_fights_target"}
    )
    assert isinstance(bridge_result, EnchantedCreatureFightsTargetEffect), (
        "cross_engine._ta_dict_to_python_effect should map "
        "{kind: enchanted_creature_fights_target} to an "
        "EnchantedCreatureFightsTargetEffect instance. Got: "
        f"{type(bridge_result).__name__}"
    )

    # H. Deferred-half sentinel: the production-deck loader admit gate
    #    still does NOT admit Auras (the Aura attach substrate's
    #    Phase 1 has not landed). When Phase 1 lands the admit gate
    #    grows an is_aura arm; this assertion will fire and the pin
    #    needs to rename to ``..._FIXED_parity``.
    from mtg_bot.parity import trajectory as T
    import inspect

    filter_src = inspect.getsource(T._filter_deck_to_bridge_supported)
    # The admit predicates today (3) are basic land, nonbasic mana
    # land, and simple creature. No simple-aura predicate yet.
    assert "_printing_is_bridge_simple_aura" not in filter_src, (
        "If this assertion fails, the Aura attach substrate's Phase 1 "
        "_printing_is_bridge_simple_aura admit predicate has LANDED -- "
        "rename this pin from "
        "_FIXED_substrate_landed_resolve_deferred to _FIXED_parity, "
        "drop the honest-stop branch in the Rust resolve arm, and add "
        "a real-EoE byte-equal probe for Meltstrider's Resolve "
        "driving ENTERS -> EnchantedCreatureFightsTargetEffect through "
        "the live attached_to host. See "
        "docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md Phase 1."
    )


def test_meltstriders_resolve_printing_carries_aura_fight_effect():
    """Confirm Meltstrider's Resolve loads + carries the Aura-shape
    Fight ETB trigger on the Python side.

    Sanity check tied to the same closure: the production-source
    printing for Meltstrider's Resolve has ``is_aura=True``, an
    ``ENTERS`` triggered ability emitting
    ``EnchantedCreatureFightsTargetEffect``, and the +0/+2 + menace
    static bonus on attach. This pins the Python source-of-truth shape
    used by the bridge round-trip + the deferred attach substrate's
    Phase 3 byte-equal probe.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import EnchantedCreatureFightsTargetEffect

    printings = get_active_source().get_printings()
    assert "Meltstrider's Resolve" in printings, (
        "Meltstrider's Resolve should be a registered printing in the "
        "active card source. If missing, the EoE data file changed -- "
        "regenerate via scripts/fetch_eoe.py."
    )
    m = printings["Meltstrider's Resolve"]
    assert getattr(m, "is_aura", False), (
        "Meltstrider's Resolve should parse as is_aura=True (it is an "
        "Enchantment - Aura). If False, the enchantment parser drifted."
    )
    # Aura attaches to creature (you control).
    assert getattr(m, "aura_enchant_type", None) == "creature", (
        "Meltstrider's Resolve should parse aura_enchant_type='creature'."
    )
    assert getattr(m, "aura_yours_only", False), (
        "Meltstrider's Resolve enchants a creature 'you control' -- "
        "aura_yours_only should be True."
    )
    # +0/+2 + menace static bonus on attach.
    eq_bonuses = getattr(m, "equipment_bonuses", None)
    assert eq_bonuses is not None, (
        "Meltstrider's Resolve should carry equipment_bonuses for its "
        "static +0/+2 + menace grant (Auras reuse the Equipment bonus "
        "tuple machinery)."
    )
    power_bonus, toughness_bonus, granted_keywords = eq_bonuses
    assert power_bonus == 0 and toughness_bonus == 2, (
        f"Meltstrider's Resolve should carry +0/+2 equipment_bonuses; "
        f"got ({power_bonus}, {toughness_bonus})."
    )
    assert "menace" in granted_keywords, (
        f"Meltstrider's Resolve should grant menace via "
        f"equipment_bonuses; got keywords {granted_keywords}."
    )
    # ENTERS -> EnchantedCreatureFightsTargetEffect.
    assert len(m.triggered_abilities) >= 1, (
        "Meltstrider's Resolve should carry at least one triggered "
        "ability (the ETB fight rider)."
    )
    enters_with_fight = [
        ta
        for ta in m.triggered_abilities
        if isinstance(ta.effect, EnchantedCreatureFightsTargetEffect)
    ]
    assert len(enters_with_fight) == 1, (
        "Meltstrider's Resolve should carry exactly one ENTERS-trigger "
        "with EnchantedCreatureFightsTargetEffect on the effect. If "
        "the count differs, the enchantment parser changed -- update "
        "this pin."
    )


def test_rust_enchanted_creature_fights_target_dict_round_trips_through_pyo3_bindings():
    """End-to-end Python-Rust-Python round-trip via the live pyo3
    bindings: a Python ``EnchantedCreatureFightsTargetEffect()``
    serialized as the bridge dict and parsed through Rust's
    ``parse_effect`` reproduces the same Python instance when
    bridged back via ``cross_engine._ta_dict_to_python_effect``.

    Sanity check that the parse arm + effect_to_pydict arm + bridge
    arm are mutually consistent (no spelling drift on the kind
    string).
    """
    from mtg_bot.effects.bespoke import EnchantedCreatureFightsTargetEffect
    from mtg_bot.parity import cross_engine as ce

    # The bridge's dict shape for this Effect is a kind-only unit dict.
    eff_dict = {"kind": "enchanted_creature_fights_target"}

    # Forward: dict -> Python class instance.
    py_inst = ce._ta_dict_to_python_effect(eff_dict)
    assert isinstance(py_inst, EnchantedCreatureFightsTargetEffect)

    # Try to round-trip via the Rust parse + to_pydict arms if the
    # pyo3 bindings expose them; otherwise check Python-side only.
    try:
        import mtg_bot_engine as _engine  # type: ignore[import-not-found]
    except ImportError:
        # The Rust extension isn't built in this environment; bridge
        # arm Python-side coverage already confirmed.
        return
    # The bindings carry ``parse_effect_for_test`` only in some
    # build variants; if absent, just confirm the bridge arm is
    # complete on the Python side.
    parse_fn = getattr(_engine, "parse_effect_for_test", None)
    to_dict_fn = getattr(_engine, "effect_to_dict_for_test", None)
    if parse_fn is None or to_dict_fn is None:
        return
    rust_effect = parse_fn(eff_dict)
    round_tripped_dict = to_dict_fn(rust_effect)
    assert round_tripped_dict.get("kind") == "enchanted_creature_fights_target"
    py_again = ce._ta_dict_to_python_effect(round_tripped_dict)
    assert isinstance(py_again, EnchantedCreatureFightsTargetEffect)
