"""Genuine real-EoE cross-engine byte-equality probes — batch J.

CONTINUOUS-PIPELINE phase: convert high-value
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against the bridged synthetic carrier on the Rust side
(``register_and_inject_object`` with the closed-vocab effect dict the
production bridge round-trips — the established Embrace-Oblivion /
Decode-Transmissions / Sami's-Curiosity cross-engine driving pattern;
the full Sorcery/Instant is NOT loader-admitted, there is no
Instant/Sorcery bench path) and asserts **full ``compare_fields(...)
== []``** — byte-equality across the WHOLE cross-engine field view,
the strongest Effect+bridge-level evidence — after a real EoE deck
context (the carrier resolved end-to-end on both engines, the spell
fired, the stack drained). Made campaign-wide possible by the
round-r70 ``_zone_signature`` ``_net_counters`` counters-blindness fix.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch J — SORCERY primary, trivial INSTANT ok)
---------------------------------------------------------------------
This module is batch J, extending the SORCERY (and trivially-resolving
INSTANT) covered-but-unprobed lane after batches A/D/E/G. Sibling
agents K (ETB triggers) and L (BECOMES_TAPPED + landfall) run in
parallel worktrees. The covered-by-construction-but-unprobed list
(computed read-only via ``scripts/measure_pool_parity.classify_pool``,
sorted by 17lands deck count desc) was verify-first-recomputed at live
HEAD; every card below is (a) covered-by-construction, (b) NOT
individually probed, (c) NOT in any sibling batch, (d) an Instant or
Sorcery with a ``spell_effect`` that resolves directly with no
creature-trigger involvement.

The 4 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Murder               (~0 17lands decks) — Instant,
     DestroyTargetCreature (plain vanilla destroy, no riders)
  2. Impossible Inferno   (~0 17lands decks) — Instant,
     DealDamageToTargetCreature(6)
  3. Midnight Mayhem      (~0 17lands decks) — Sorcery,
     CreateToken(Gremlin 1/1, count=3)
  4. Winter's Intervention (~0 17lands decks) — Instant,
     Sequence(DealDamageToTargetCreature(2), GainLife(2))

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Lithobraking** (~3,368 decks) — ``spell_effect`` is
    ``Sequence(CreateToken(Lander, 1), OptionalSacArtifactForEffect(
    DealNDamageToEachCreature(2)))``. The second leg is an
    optional-cost activated mechanic: ``OptionalSacArtifactForEffect``
    fires only if the caster pays an additional cost (sacrifice an
    artifact). No established bridge arm for the optional-cost
    sub-shape; driving only the CreateToken leg would not be a
    faithful full-card probe. Dropped.
  * **Dark Endurance** (~1,978 decks) — ``PumpTargetCreatureUntilEOT(
    +2/+0, indestructible)``. The ``grant_keywords_to_target_creature_
    until_eot`` bridge arm forces ``you_control_only=True`` but the
    oracle text "target creature" is unrestricted; a faithful
    cross-engine probe at Rust's bridge would diverge on the target-
    side (Rust targets caster's own side, Python has no such constraint
    by default). Dropped.
  * **Rig for War** (~2,372 decks) — ``PumpTargetCreatureUntilEOT(
    +3/+0, reach+first_strike)``. No single combined PT+keywords bridge
    arm exists: ``pump_target_creature_until_eot`` carries only
    ``power_bonus``/``toughness_bonus`` (no keywords);
    ``grant_keywords_to_target_creature_until_eot`` carries only
    keywords (no PT bonus). Dropped.
  * **Withering Torment** (~0 decks) — ``Sequence(
    DestroyTargetCreature(or_enchantment=True), LoseLife(2))``. The
    ``or_enchantment=True`` rider requires the ``subject_is_enchantment``
    predicate which is noted as missing in the Rust bridge vocab. The
    plain ``DestroyTargetCreature`` shape is already pinned by Murder
    below. Dropped; the batch avoids the enchantment-predicate gap.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_h / batch_i / spell_card_bridge_admitted /
warp_admitted / warp_combat_interaction modules nor the 6
``test_audit_safe_trigger_*`` tests — those are owned/protected; this
module avoids all collision and touches no STALENESS-SENTINEL).
Registered in ``scripts/measure_pool_parity.PROBE_MODULES``.
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
    builder lives there). Identical to ``test_parity_smoke.py``'s
    module-scoped fixture — copied here so this module is fully
    self-contained / collision-free with the owned test files."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Batch-J probe #1 — Murder (~0 17lands decks; genuine EoE card).
#
# Covered (``DestroyTargetCreature`` in covered set) + unprobed at
# HEAD. Oracle:
#   "[Instant] {1}{B}{B} — Destroy target creature."
# Parser -> ``spell_effect = DestroyTargetCreature(targets=(
#   TargetSpec(IsCreature()),), or_spacecraft=False,
#   or_enchantment=False)``.
#
# The ``destroy_target`` bridge arm (cross_engine.py:2567) maps to
# Python's ``DestroyTargetCreature`` (base Destroy + IsCreature
# filter). Rust picks the first creature on the defender's bf;
# Python's ``_PickFirstOpponentTargetAgent`` mirrors that pick
# exactly (single opponent creature -> forced). The targeted creature
# is destroyed (bf -> graveyard) on BOTH engines. Deck count is 0
# in the 17lands draft pool (Murder is a non-EoE reprint) but is a
# genuine EoE pool member and genuinely covered-by-construction.
#
# Note: the probe drives the pure unridered destroy shape (no
# or_spacecraft, no or_enchantment) to avoid predicate gaps noted
# for those riders. Embrace Oblivion (batch A) already pins the
# or_spacecraft=True variant; Murder pins the pure vanilla form.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_murder_destroy_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Murder
    (~0 17lands decks; genuine EoE covered card). Batch-J covered->PROBED.**

    Python: the ACTUAL parsed Murder printing on a ``StackItem`` with
    the chosen creature target. Rust: the bridged
    ``{"kind":"destroy_target","target":{"kind":"any_creature"}}``
    synthetic Instant (AnyCreature first-slice picker -> p1 bf[0]).

    Murder is the purest ``DestroyTargetCreature`` shape: no
    ``or_spacecraft`` / ``or_enchantment`` rider, single creature
    target, no draw. Complements Embrace Oblivion (batch A, which
    carries ``or_spacecraft=True``) by pinning the bare vanilla destroy
    arm byte-equal end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 2/2 destroyed -> p1 graveyard on
    BOTH; battlefield empty on BOTH; lives unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Murder")
    if real is None:
        pytest.skip("Murder absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Murder spell_effect must be DestroyTargetCreature; "
        f"got {type(se).__name__}"
    )
    assert se.or_spacecraft is False
    assert se.or_enchantment is False

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 2/2 creature — the legal target on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="Murder Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "Murder Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Murder on a StackItem, controller p0,
    # chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "Murder Victim must be destroyed, not on p1 bf (Python)"
    )
    assert py_vic in py.players[1].graveyard, (
        "Murder Victim must be in p1 graveyard after destroy (Python)"
    )

    # ---- Rust: bridged destroy_target synthetic Instant (AnyCreature
    # first-slice picker -> p1 bf[0]). ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Murder", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    assert rs_alive is False, (
        f"Murder Victim must be destroyed on Rust side; "
        f"bf={[e['printing_name'] for e in rs.battlefield_snapshot()]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Murder destroy-creature must be byte-equal across the WHOLE "
        f"field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-J probe #2 — Impossible Inferno (~0 17lands decks; genuine EoE).
#
# Covered (``DealDamageToTargetCreature`` in covered set) + unprobed
# at HEAD. Oracle:
#   "[Instant] {3}{R}{R} — Impossible Inferno deals 6 damage to
#    target creature."
# Parser -> ``spell_effect = DealDamageToTargetCreature(amount=6,
#   targets=(TargetSpec(IsCreature()),))``.
#
# The ``deal_damage`` bridge arm (cross_engine.py:568) with
# ``target: {"kind": "any_creature"}`` maps to Python's
# ``DealDamageToTargetCreature``. Rust picks the first creature on
# the defender's bf; Python's ``_PickFirstOpponentTargetAgent``
# mirrors that pick exactly (single opponent creature -> forced).
# A vanilla 2/2 creature is seated on p1's bf: 6 damage >= 2
# toughness, so SBA destroys it on BOTH engines (the
# ``DealDamageToTargetCreature`` + ``DealDamage`` shape is distinct
# from the unit ``DealDamageAnyTarget`` arm — the ``deal_damage``
# arm is filter-parametric with ``any_creature`` narrowing).
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_impossible_inferno_deal_6_damage_to_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Impossible Inferno
    (~0 17lands decks; genuine EoE covered card). Batch-J covered->PROBED.**

    Python: the ACTUAL parsed Impossible Inferno printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"deal_damage","amount":6,"target":{"kind":"any_creature"}}``
    synthetic Instant (AnyCreature first-slice picker -> p1 bf[0]).

    The 6-damage amount is far above the 2/2 victim's toughness, so
    the creature dies in the SBA pass on BOTH engines. This pins the
    ``DealDamageToTargetCreature`` covered Effect + ``deal_damage``
    bridge arm byte-equal end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 2/2 destroyed -> p1 graveyard on
    BOTH; battlefield empty; lives unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.damage import DealDamageToTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Impossible Inferno")
    if real is None:
        pytest.skip("Impossible Inferno absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DealDamageToTargetCreature), (
        f"genuine Impossible Inferno spell_effect must be "
        f"DealDamageToTargetCreature; got {type(se).__name__}"
    )
    assert se.amount == 6

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 2/2 creature. 6 >= 2 -> destroyed by SBA.
    py_vic = py.new_object(
        CardPrinting(
            name="II Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "II Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Impossible Inferno on a StackItem,
    # controller p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "II Victim must be destroyed by 6 damage (Python)"
    )
    assert py_vic in py.players[1].graveyard, (
        "II Victim must be in p1 graveyard after lethal damage (Python)"
    )

    # ---- Rust: bridged deal_damage any_creature synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Impossible Inferno", "card_types": ["Instant"],
         "effects": [{"kind": "deal_damage", "amount": 6,
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    assert rs_alive is False, (
        f"II Victim must be destroyed on Rust side; "
        f"bf={[e['printing_name'] for e in rs.battlefield_snapshot()]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Impossible Inferno deal-6-to-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-J probe #3 — Midnight Mayhem (~0 17lands decks; genuine EoE).
#
# Covered (``CreateToken`` in covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {1}{R} — Create three 1/1 colorless Gremlin artifact
#    creature tokens."
# Parser -> ``spell_effect = CreateToken(token_printing=Gremlin,
#   count=3)``.
#
# The ``create_token`` bridge arm (cross_engine.py) requires a
# ``token_printing_id`` registered in the Rust object registry.
# The Gremlin pid is assigned as ``rs.registry_size`` before injection
# (the established Sami's-Curiosity / Scrounge-for-Eternity pid idiom).
# Python's ``TOKEN_PRINTINGS["Gremlin"]`` is seeded in p0's library so
# the starting field view is pid-symmetric on both engines. Untargeted,
# no RNG. Three Gremlin tokens appear on p0's battlefield on BOTH.
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_midnight_mayhem_create_three_gremlins_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Midnight Mayhem
    (~0 17lands decks; genuine EoE covered card). Batch-J covered->PROBED.**

    Python: the ACTUAL parsed Midnight Mayhem printing on a
    ``StackItem`` (no targets). Rust: the bridged
    ``{"kind":"create_token","count":3,"token_printing_id":<Gremlin_pid>}``
    synthetic Sorcery (the established Sami's-Curiosity token-pid
    idiom). Three 1/1 Gremlin tokens appear on p0's battlefield on
    BOTH engines.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (three Gremlin tokens on p0's battlefield
    byte-equal on BOTH; hands, graveyards, libraries empty; lives
    unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.tokens import CreateToken

    real = get_active_source().get_printings().get("Midnight Mayhem")
    if real is None:
        pytest.skip("Midnight Mayhem absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CreateToken), (
        f"genuine Midnight Mayhem spell_effect must be CreateToken; "
        f"got {type(se).__name__}"
    )
    assert se.token_printing.name == "Gremlin", (
        f"Midnight Mayhem token must be Gremlin; "
        f"got {se.token_printing.name!r}"
    )
    assert se.count == 3, (
        f"Midnight Mayhem must create 3 tokens; got {se.count}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Register Gremlin pid on Rust; seed TOKEN_PRINTINGS["Gremlin"] in
    # p0's library so the field-view token-printing-id is symmetric on
    # both engines (the established Sami's-Curiosity idiom, batch D).
    gremlin_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Gremlin", "card_types": ["Artifact", "Creature"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0},
         "power": 1, "toughness": 1},
        0, 1,  # owner p0, ZONE_HAND (inert pre-probe)
    )
    py_gremlin_seed = py.new_object(
        TOKEN_PRINTINGS["Gremlin"], owner_id=0, zone=Zone.LIBRARY
    )
    py_gremlin_seed.summoning_sick = False
    py.players[0].library.append(py_gremlin_seed)

    # ---- Python: genuine parsed Midnight Mayhem on a StackItem,
    # controller p0, no targets (token creation is untargeted). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    py_gremlins = [o for o in py.battlefield
                   if o.printing.name == "Gremlin"]
    assert len(py_gremlins) == 3, (
        f"Midnight Mayhem must create exactly 3 Gremlins (Python); "
        f"got {len(py_gremlins)}"
    )

    # ---- Rust: bridged create_token(Gremlin pid, count=3) synthetic
    # Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Midnight Mayhem", "card_types": ["Sorcery"],
         "effects": [{"kind": "create_token", "count": 3,
                      "token_printing_id": gremlin_pid}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    rs_gremlins = [e for e in rs.battlefield_snapshot()
                   if e["printing_name"] == "Gremlin"]
    assert len(rs_gremlins) == 3, (
        f"Midnight Mayhem must create exactly 3 Gremlins (Rust); "
        f"got {len(rs_gremlins)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Midnight Mayhem create-three-Gremlins must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-J probe #4 — Winter's Intervention (~0 17lands decks; EoE).
#
# Covered (``Sequence`` / ``DealDamageToTargetCreature`` /
# ``GainLife`` in covered set) + unprobed at HEAD. Oracle:
#   "[Instant] {G} — Winter's Intervention deals 2 damage to target
#    creature. You gain 2 life."
# Parser -> ``spell_effect = Sequence(
#   DealDamageToTargetCreature(amount=2, targets=(TargetSpec(
#     IsCreature()),)),
#   GainLife(amount=2))``.
#
# The ``sequence[deal_damage(2, any_creature), gain_life(2)]`` bridge
# shape is straightforward: Rust's sequence arm evaluates the first
# sub-effect (deal_damage 2 to defender's bf[0]) then the second
# (gain_life 2 for source controller). A 2/4 creature is seated on
# p1's bf so 2 damage is non-lethal (damage < toughness) — the
# creature SURVIVES with 2 damage counters, and p0 gains 2 life
# on BOTH engines, giving an observable state on both axes that the
# ``compare_fields`` assertion pins.
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_winters_intervention_deal_2_gain_2_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Winter's Intervention
    (~0 17lands decks; genuine EoE covered card). Batch-J covered->PROBED.**

    Python: the ACTUAL parsed Winter's Intervention printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"sequence","effects":[{"kind":"deal_damage","amount":2,
    "target":{"kind":"any_creature"}},{"kind":"gain_life","amount":2}]}``
    synthetic Instant.

    A 2/4 creature on p1's bf takes 2 non-lethal damage and survives
    (2 < 4 toughness); p0 gains 2 life on BOTH engines. The battlefield
    state (creature with 2 damage + tapped flag) and p0 life are
    both observable in the ``compare_fields`` field view.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (2/4 still on p1's battlefield with 2
    damage; p0 life +2; no graveyard movement on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.damage import DealDamageToTargetCreature
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Winter's Intervention")
    if real is None:
        pytest.skip("Winter's Intervention absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Winter's Intervention spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(se.effects[0], DealDamageToTargetCreature), (
        f"first effect must be DealDamageToTargetCreature; "
        f"got {type(se.effects[0]).__name__}"
    )
    assert se.effects[0].amount == 2
    assert isinstance(se.effects[1], GainLife), (
        f"second effect must be GainLife; "
        f"got {type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single 2/4 creature. 2 damage < 4 toughness -> survives.
    # Observables: creature remains on bf with 2 damage; p0 gains 2 life.
    py_vic = py.new_object(
        CardPrinting(
            name="WI Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=4, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()
    py_p0_life0 = py.players[0].life

    rs_vic_id = rs.register_and_inject_object(
        {"name": "WI Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 4}, 1, ZB,
    )
    rs_p0_life0 = rs.get_life(0)

    # ---- Python: genuine parsed Winter's Intervention on a StackItem,
    # controller p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic in py.battlefield, (
        "WI Victim (2/4) must survive 2 non-lethal damage (Python)"
    )
    assert py_vic.damage == 2, (
        f"WI Victim must have 2 damage counters (Python); "
        f"got {py_vic.damage}"
    )
    assert py.players[0].life == py_p0_life0 + 2, (
        "p0 must gain 2 life from Winter's Intervention (Python)"
    )

    # ---- Rust: bridged sequence[deal_damage(2, any_creature),
    # gain_life(2)] synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Winter's Intervention", "card_types": ["Instant"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "deal_damage", "amount": 2,
              "target": {"kind": "any_creature"}},
             {"kind": "gain_life", "amount": 2},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_vic_state = next(
        (e for e in rs.battlefield_snapshot() if e["id"] == rs_vic_id),
        None,
    )
    assert rs_vic_state is not None, (
        "WI Victim (2/4) must survive 2 non-lethal damage (Rust)"
    )
    assert rs_vic_state.get("damage", 0) == 2, (
        f"WI Victim must have 2 damage (Rust); "
        f"got {rs_vic_state.get('damage', 0)}"
    )
    assert rs.get_life(0) == rs_p0_life0 + 2, (
        "p0 must gain 2 life from Winter's Intervention (Rust)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Winter's Intervention deal-2-gain-2 must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
