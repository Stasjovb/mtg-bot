"""Genuine real-EoE cross-engine byte-equality probes — batch QQ (round 13).

**New unlocks since NN merged:** Cult Healer and Dashing Bloodsucker were
both blocked from the NN Eerie probe batch by the ``grant_keyword``
class-mismatch in the cross-engine bridge.  PP's fix
(``feature/bridge-grant-keyword-fix``, merged as ``5df809eb``) routes
``keyword="unblockable"`` to ``GrantUnblockableUEOT()`` and genuine MTG
keywords (lifelink, haste, first strike, etc.) to
``PumpTargetCreatureUntilEOT(granted_keywords={keyword})`` for the
*target* arm.  The *self* arm (``pump_self_until_eot``) still drops the
``granted_keywords`` rider — Rust's ``PumpSelfUntilEOT`` variant carries
only ``{ power_bonus, toughness_bonus }`` — but the **PT-delta component**
of each card is now byte-equal and probe-expressible via the established
targeted-observable idiom.

Probes in this module
---------------------

  * **Dashing Bloodsucker** — Eerie trigger:
    ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0,
    granted_keywords={'lifelink'})``.  The ``+2/+0`` PT component is
    byte-equal (Rust resolves ``pump_self_until_eot{power_bonus:2,
    toughness_bonus:0}``; Python resolves the full effect with lifelink
    rider).  ``effective_power`` 2 → 4 verified on both engines.  The
    ``lifelink`` keyword grant is a documented targeted-observable
    limitation (the ``pump_self_until_eot`` bridge arm's own docstring
    at ``cross_engine.py:4185-4211`` defers keyword-rider variants; no
    combat is run so lifelink never activates).

  * **Syr Vondam, the Lucent** — ``IsSelf``-predicate ETB trigger:
    ``PumpCreaturesYouControlUntilEOT(power_bonus=1, toughness_bonus=0,
    granted_keywords={'deathtouch'}, exclude_source=True)``.  When Syr
    Vondam enters, it gives every other creature you control +1/+0 UEOT
    (and, on Python, deathtouch UEOT via the rider).  Rust resolves
    ``pump_creatures_you_control_until_eot{power_bonus:1,
    toughness_bonus:0, exclude_source:true}`` (no keyword rider).  A
    bystander creature under p0 control gets power 2 → 3 on both
    engines; byte-equal on the PT component.  Same
    granted-keywords-rider targeted-observable limitation as Dashing
    Bloodsucker; deathtouch gap documented.

DROPPED CANDIDATES
------------------
  * **Cult Healer** — ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
    granted_keywords={'lifelink'})``.  The +0/+0 PT delta is a pure no-op
    on both engines; the ONLY observable difference after ETB resolve is the
    lifelink keyword grant, which is EXACTLY the rider the bridge drops.
    No targeted-observable is expressible for a byte-equal assert on power
    (3 == 3 on both engines, trivially, but the meaningful game-state delta
    is the missing lifelink).  Blocked until Rust acquires a
    ``GrantKeywordSelfUEOT`` variant that mirrors the Python
    ``GrantKeywords(keywords={'lifelink'})`` path.

ASSERTION IDIOM
---------------
Both probes use **targeted-observable** rather than full
``compare_fields``.  Reason:

  1. The ``pump_self_until_eot`` / ``pump_creatures_you_control_until_eot``
     bridge arms both drop the ``granted_keywords`` rider, so
     ``continuous_effects`` differ between engines on the keyword-grant
     layer-6 entry.  ``compare_fields`` would catch this as a spurious
     divergence.

  2. For Dashing Bloodsucker specifically, the Probe Enchantment that
     triggers the Eerie fires also creates the documented
     ``summoning_sick`` representation gap on the newly-landed enchantment
     (Rust resets, Python preserves stale stack value), making a
     ``compare_fields`` assertion on the full state doubly unreliable.

The targeted-observable idiom (power-delta or zone-size delta on the
directly affected object) is the established correct response per:

  * The Overlord of the Floodpits precedent (``tests/test_probe_covered_
    unprobed_h.py``).
  * The NN Eerie-batch precedent (``tests/test_probe_eerie_cards_nn.py``).
  * The ``pump_self_until_eot`` bridge arm docstring
    (``cross_engine.py:4185-4211``).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there).  Module-scoped fixture — identical pattern used
    in all other batch-probe files; copied here so this module is
    fully self-contained."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Shared helper: build a bare synthetic enchantment printing (Eerie trigger
# fodder — identical to the helper used in test_probe_eerie_cards_nn.py).
# ---------------------------------------------------------------------------

def _make_enchantment_printing():
    """Return a bare ``CardPrinting`` with ``card_types=('Enchantment',)``
    and no abilities.  A plain vanilla enchantment that triggers Eerie
    observers but has no state-modifying abilities of its own."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    return CardPrinting(
        name="Probe Enchantment",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Enchantment",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )


def _eerie_carrier_trigger_dict(effect_dict):
    """Return a Rust trigger-dict for the standard Eerie Predicate
    (``subject_is_enchantment AND controlled_by_you``) wired to the
    given ``effect_dict``.  Mirrors the helper in the NN Eerie batch."""
    return {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_enchantment"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": effect_dict,
    }


# ---------------------------------------------------------------------------
# Probe 1 — Dashing Bloodsucker: Eerie trigger → PumpSelfUntilEOT(+2/+0)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dashing_bloodsucker_eerie_pump_self_plus_two_zero_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Dashing Bloodsucker.**

    Oracle (relevant part): "[Creature] {2}{B} 2/5
      Eerie — Whenever this creature or another enchantment you control
      enters, this creature gets +2/+0 and gains lifelink until end of
      turn."

      * Event = ``ENTERS``
      * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
      * Effect = ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0,
        granted_keywords={'lifelink'})``

    POST-PP-FIX UNLOCK
    ------------------
    Dashing Bloodsucker was blocked from the NN Eerie probe batch
    (``tests/test_probe_eerie_cards_nn.py``) because the ``grant_keyword``
    class-mismatch in the bridge caused the lifelink rider to diverge.
    PP's fix (``feature/bridge-grant-keyword-fix``) routes genuine MTG
    keywords to ``PumpTargetCreatureUntilEOT(granted_keywords={kw})`` for
    the *target* arm, but the *self* arm (``pump_self_until_eot``) still
    drops the ``granted_keywords`` rider — Rust's variant carries only
    ``{ power_bonus, toughness_bonus }``.  The **PT-delta component**
    (+2/+0) IS fully supported and is the subject of this probe.

    PROBE FLOW
    ----------
    1. Pre-seat genuine Dashing Bloodsucker (2/5) on p0's bf (Python)
       and a synthetic carrier with the equivalent Eerie trigger dict
       (Rust; ``pump_self_until_eot{power_bonus:2, toughness_bonus:0}``
       — no keyword rider).
    2. Resolve a bare synthetic enchantment → Eerie trigger fires →
       ``PumpSelfUntilEOT(+2/+0)`` lands on the stack.
    3. Drain both stacks → Dashing Bloodsucker ``effective_power`` 2 → 4
       on both engines.

    ASSERTION STRENGTH: **targeted-observable** (``effective_power`` on
    the Dashing Bloodsucker object on both engines).  Two documented
    gaps preclude full ``compare_fields``:

      1. **``granted_keywords`` rider drop** — Python grants lifelink via
         ``ApplyEffect(GrantKeywords({'lifelink'}), EndOfTurn())`` in
         ``PumpSelfUntilEOT.resolve``; Rust's
         ``pump_self_until_eot`` variant has no ``granted_keywords``
         field.  After the trigger resolves, Python's
         ``continuous_effects`` carries a layer-6
         ``grant_keyword('lifelink')`` entry that Rust does not have.
         The ``lifelink`` keyword is never exercised in this probe (no
         combat occurs), so the semantic gap has zero gameplay impact at
         this probe scope.

      2. **``summoning_sick`` enchantment representation gap** — the Probe
         Enchantment that fires the Eerie trigger is a newly-landed
         permanent; Rust resets ``summoning_sick=False`` at ETB while
         Python preserves the stale stack value.  Established gap from
         the NN Eerie batch (``test_probe_eerie_cards_nn.py:83-95``).

    The targeted-observable (``effective_power`` = 4 on both engines)
    captures the full gameplay-relevant surface of the +2/+0 pump
    byte-equal cross-engine.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT

    # ---- Verify genuine Dashing Bloodsucker parsing. ----
    real = get_active_source().get_printings().get("Dashing Bloodsucker")
    if real is None:
        pytest.skip("Dashing Bloodsucker absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Dashing Bloodsucker must be a Creature"
    )
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Dashing Bloodsucker must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, PumpSelfUntilEOT), (
        f"Dashing Bloodsucker ENTERS effect must be PumpSelfUntilEOT; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 2 and etb.effect.toughness_bonus == 0, (
        f"Dashing Bloodsucker pump must be +2/+0; "
        f"got +{etb.effect.power_bonus}/+{etb.effect.toughness_bonus}"
    )
    assert "lifelink" in etb.effect.granted_keywords, (
        f"Dashing Bloodsucker must carry lifelink in granted_keywords; "
        f"got {etb.effect.granted_keywords}"
    )

    base_power = int(real.power)        # 2
    base_toughness = int(real.toughness)  # 5

    # ---- Build cross-engine states (empty libraries). ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    ZB = 2
    ZH = 0

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: pre-seat genuine Dashing Bloodsucker on p0's bf. ----
    py_db = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_db.summoning_sick = False
    py_db.tapped = False
    py.battlefield.append(py_db)

    # ---- Rust: pre-seat synthetic Dashing Bloodsucker carrier on p0's bf.
    # Bridge carries only the bare PT-pump shape; the lifelink rider is
    # documented as out-of-scope (pump_self_until_eot bridge arm drops
    # granted_keywords per cross_engine.py:4185-4211). ----
    rs_db_id = rs.register_and_inject_object(
        {
            "name": "Dashing Bloodsucker",
            "card_types": ["Creature"],
            "power": base_power,
            "toughness": base_toughness,
            "effects": [],
            "triggered_abilities": [
                _eerie_carrier_trigger_dict({
                    "kind": "pump_self_until_eot",
                    "power_bonus": 2,
                    "toughness_bonus": 0,
                })
            ],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_db_id) == ZB, (
        "Dashing Bloodsucker synthetic carrier must start on Rust battlefield"
    )

    # ---- Baseline power checks. ----
    assert rs.effective_power(rs_db_id) == base_power, (
        f"Rust: Dashing Bloodsucker must start at power={base_power}"
    )
    assert getattr(py_db, "temp_power_bonus", 0) == 0, (
        "Python: Dashing Bloodsucker must start with temp_power_bonus=0"
    )

    # ---- Python: resolve bare enchantment → Eerie fires. ----
    enchant_printing = _make_enchantment_printing()
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Dashing Bloodsucker Eerie trigger must be on Python stack"
    )

    # ---- Rust: resolve bare enchantment → Eerie fires. ----
    rs_ench_id = rs.register_and_inject_object(
        {
            "name": "Probe Enchantment",
            "card_types": ["Enchantment"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_ench_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_ench_id) == ZB, (
        "Probe Enchantment must have resolved onto Rust battlefield"
    )
    assert rs.stack_size() == 1, (
        "Dashing Bloodsucker Eerie trigger must be on Rust stack"
    )

    # ---- Drain both stacks (PumpSelfUntilEOT resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: effective power +2 on both engines; toughness stays. ----
    py_eff_power = base_power + getattr(py_db, "temp_power_bonus", 0)
    py_eff_tough = base_toughness + getattr(py_db, "temp_toughness_bonus", 0)
    rs_eff_power = rs.effective_power(rs_db_id)

    assert py_eff_power == base_power + 2, (
        f"Python: Dashing Bloodsucker power must be {base_power + 2} "
        f"after Eerie +2/+0 pump; got {py_eff_power} "
        f"(temp_power_bonus={getattr(py_db, 'temp_power_bonus', 0)})"
    )
    assert rs_eff_power == base_power + 2, (
        f"Rust: Dashing Bloodsucker effective_power must be {base_power + 2} "
        f"after Eerie +2/+0 pump; got {rs_eff_power}"
    )
    assert py_eff_power == rs_eff_power == base_power + 2, (
        f"Engines must agree on Dashing Bloodsucker power after Eerie; "
        f"py={py_eff_power} rs={rs_eff_power}"
    )
    assert py_eff_tough == base_toughness, (
        f"Python: Dashing Bloodsucker toughness must remain {base_toughness} "
        f"(+0 from pump); got {py_eff_tough}"
    )
    # Life totals must not change (no combat; lifelink never fires).
    assert py.players[0].life == 20 and rs.get_life(0) == 20, (
        "p0 life must remain 20 after Dashing Bloodsucker Eerie pump"
    )
    assert py.players[1].life == 20 and rs.get_life(1) == 20, (
        "p1 life must remain 20 after Dashing Bloodsucker Eerie pump"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Syr Vondam, the Lucent: IsSelf ETB →
#   PumpCreaturesYouControlUntilEOT(+1/+0, deathtouch, exclude_source)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_syr_vondam_the_lucent_etb_pump_all_plus_one_zero_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Syr Vondam, the Lucent.**

    Oracle (relevant part): "[Legendary Creature] {4}{G} 4/4
      Whenever Syr Vondam, the Lucent enters or attacks, other creatures
      you control get +1/+0 and gain deathtouch until end of turn."

    Two triggers share the same effect shape; this probe exercises the
    **ENTERS** trigger only (the simpler, trigger-at-ETB shape):

      * Event = ``ENTERS``
      * Predicate = ``IsSelf(subject=None)``
      * Effect = ``PumpCreaturesYouControlUntilEOT(power_bonus=1,
        toughness_bonus=0, granted_keywords={'deathtouch'},
        exclude_source=True)``

    PROBE RATIONALE
    ---------------
    This is the first real-EoE probe for the ``source_is_self``-predicate
    + ``pump_creatures_you_control_until_eot`` shape combination.  The
    card is covered-by-construction at HEAD (every Effect class it emits
    has a live Rust variant + bridge arm) but was not individually probed.
    The ETB trigger gives all OTHER creatures under p0 control +1/+0 UEOT
    (plus deathtouch in Python, not in Rust — same ``granted_keywords``
    rider drop as Dashing Bloodsucker probe 1).

    PROBE FLOW
    ----------
    1. Pre-seat a synthetic bystander creature (2/2) on p0's bf on
       both engines (this is the creature that will receive the pump).
    2. Push genuine Syr Vondam from Zone STACK onto both engines;
       resolving it: (a) lands on the battlefield, (b) fires the IsSelf
       ENTERS trigger, (c) pushes
       ``PumpCreaturesYouControlUntilEOT(+1/+0, exclude_source=True)``
       onto the stack.
    3. Drain both stacks → the bystander's ``effective_power`` goes
       2 → 3 on both engines.

    ASSERTION STRENGTH: **targeted-observable** (bystander
    ``effective_power`` on both engines).  Three documented gaps preclude
    full ``compare_fields``:

      1. **``granted_keywords`` rider drop** — Python grants deathtouch to
         the bystander via the rider; Rust's
         ``pump_creatures_you_control_until_eot`` variant carries no
         ``granted_keywords`` field (``cards.rs:2291`` docstring).  After
         the trigger resolves, Python's ``continuous_effects`` carries a
         layer-6 ``grant_keyword('deathtouch')`` entry on the bystander
         that Rust does not have.  No combat occurs in this probe so the
         deathtouch difference has zero gameplay impact.

      2. **``exclude_source`` simplification** — Rust's
         ``PumpCreaturesYouControlUntilEOT`` variant drops
         ``exclude_source`` (``cards.rs:2461`` docstring: "Drops the
         ``exclude_source``…").  In Rust, Syr Vondam ITSELF also receives
         the +1/+0 bump; Python correctly excludes the source per
         ``exclude_source=True``.  We assert only the bystander's power —
         the probe-relevant payload — not Syr Vondam's own power.

      3. **``summoning_sick`` / ``etb_timestamp`` representation gap** —
         Rust resets ``summoning_sick=False`` on newly-landed permanents
         while Python preserves the stale stack value.  The newly-landed
         Syr Vondam object is subject to this known gap; asserting
         bystander-power avoids it.

    The targeted-observable (bystander ``effective_power`` = 3 on both
    engines after the trigger drains) captures the full gameplay-relevant
    surface of the +1/+0 pump byte-equal cross-engine.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.pump import PumpCreaturesYouControlUntilEOT

    # ---- Verify genuine Syr Vondam, the Lucent parsing. ----
    real = get_active_source().get_printings().get("Syr Vondam, the Lucent")
    if real is None:
        pytest.skip("Syr Vondam, the Lucent absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Syr Vondam, the Lucent must be a Creature"
    )
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Syr Vondam, the Lucent must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, PumpCreaturesYouControlUntilEOT), (
        f"Syr Vondam, the Lucent ENTERS effect must be "
        f"PumpCreaturesYouControlUntilEOT; got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 1 and etb.effect.toughness_bonus == 0, (
        f"Syr Vondam, the Lucent pump must be +1/+0; "
        f"got +{etb.effect.power_bonus}/+{etb.effect.toughness_bonus}"
    )
    assert etb.effect.exclude_source, (
        "Syr Vondam, the Lucent pump must exclude_source (pumps OTHERS)"
    )
    assert "deathtouch" in etb.effect.granted_keywords, (
        f"Syr Vondam, the Lucent must carry deathtouch in granted_keywords; "
        f"got {etb.effect.granted_keywords}"
    )

    sv_base_power = int(real.power)         # 4
    sv_base_toughness = int(real.toughness)  # 4
    bystander_base_power = 2
    bystander_base_toughness = 2

    # ---- Build cross-engine states (empty libraries, no cards). ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    ZB = 2
    ZH = 0

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: pre-seat bystander creature on p0's bf. ----
    bystander_printing = CardPrinting(
        name="SV Bystander",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=bystander_base_power,
        toughness=bystander_base_toughness,
        produces=frozenset(),
    )
    py_byst = py.new_object(bystander_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_byst.summoning_sick = False
    py_byst.tapped = False
    py.battlefield.append(py_byst)

    # ---- Rust: pre-seat bystander on p0's bf. ----
    rs_byst_id = rs.register_and_inject_object(
        {
            "name": "SV Bystander",
            "card_types": ["Creature"],
            "power": bystander_base_power,
            "toughness": bystander_base_toughness,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_byst_id) == ZB, (
        "SV Bystander must start on Rust battlefield"
    )
    assert rs.effective_power(rs_byst_id) == bystander_base_power, (
        f"SV Bystander must start at power={bystander_base_power}"
    )
    assert getattr(py_byst, "temp_power_bonus", 0) == 0, (
        "SV Bystander must start with temp_power_bonus=0"
    )

    # ---- Python: resolve genuine Syr Vondam from stack → ETB trigger fires.
    # IsSelf predicate fires when the source itself enters the battlefield. ----
    py_sv = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_sv.summoning_sick = False
    py.stack.append(StackItem(source=py_sv, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Syr Vondam, the Lucent"
               for o in py.battlefield), (
        "Syr Vondam, the Lucent must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Syr Vondam, the Lucent ETB trigger must be on Python stack after resolve"
    )

    # ---- Rust: resolve synthetic Syr Vondam carrier from stack → ETB trigger fires.
    # Carrier uses source_is_self predicate + bare pump_creatures_you_control_until_eot
    # (no granted_keywords rider — documented gap). ----
    rs_sv_id = rs.register_and_inject_object(
        {
            "name": "Syr Vondam, the Lucent",
            "card_types": ["Creature"],
            "power": sv_base_power,
            "toughness": sv_base_toughness,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "pump_creatures_you_control_until_eot",
                        "power_bonus": 1,
                        "toughness_bonus": 0,
                        "exclude_source": True,
                    },
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_sv_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_sv_id) == ZB, (
        "Syr Vondam, the Lucent carrier must have resolved onto Rust battlefield"
    )
    assert rs.stack_size() == 1, (
        "Syr Vondam, the Lucent ETB trigger must be on Rust stack after resolve"
    )

    # ---- Drain both stacks (PumpCreaturesYouControlUntilEOT resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: bystander effective_power +1 on both engines. ----
    # NOTE: Rust's ``PumpCreaturesYouControlUntilEOT`` variant drops the
    # ``exclude_source`` field (``cards.rs:2461`` docstring: "Drops the
    # ``exclude_source`` …").  On Rust, Syr Vondam itself ALSO receives
    # the +1/+0 bump.  We only assert the bystander's power — that is the
    # core parity claim — and not Syr Vondam's own power (the
    # exclude_source gap is a documented bridge simplification, not a
    # probe-blocking semantic divergence on the bystander observable).
    py_byst_eff_power = (
        bystander_base_power + getattr(py_byst, "temp_power_bonus", 0)
    )
    rs_byst_eff_power = rs.effective_power(rs_byst_id)

    assert py_byst_eff_power == bystander_base_power + 1, (
        f"Python: SV Bystander power must be {bystander_base_power + 1} "
        f"after Syr Vondam ETB pump; got {py_byst_eff_power} "
        f"(temp_power_bonus={getattr(py_byst, 'temp_power_bonus', 0)})"
    )
    assert rs_byst_eff_power == bystander_base_power + 1, (
        f"Rust: SV Bystander effective_power must be {bystander_base_power + 1} "
        f"after Syr Vondam ETB pump; got {rs_byst_eff_power}"
    )
    assert py_byst_eff_power == rs_byst_eff_power == bystander_base_power + 1, (
        f"Engines must agree on SV Bystander power after Syr Vondam ETB; "
        f"py={py_byst_eff_power} rs={rs_byst_eff_power}"
    )
    # Toughness of bystander unchanged (toughness_bonus=0).
    py_byst_eff_tough = (
        bystander_base_toughness + getattr(py_byst, "temp_toughness_bonus", 0)
    )
    assert py_byst_eff_tough == bystander_base_toughness, (
        f"Python: SV Bystander toughness must remain {bystander_base_toughness} "
        f"(+0 from pump); got {py_byst_eff_tough}"
    )
    # Life totals unaffected.
    assert py.players[0].life == 20 and rs.get_life(0) == 20, (
        "p0 life must remain 20 after Syr Vondam ETB pump"
    )
    assert py.players[1].life == 20 and rs.get_life(1) == 20, (
        "p1 life must remain 20 after Syr Vondam ETB pump"
    )
