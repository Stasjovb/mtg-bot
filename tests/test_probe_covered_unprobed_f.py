"""Genuine real-EoE cross-engine byte-equality probes — batch F.

CONTINUOUS-PIPELINE phase: convert high-deck-count
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against a bridged synthetic carrier on the Rust side
(``register_and_inject_object`` carrying the SAME printed keyword) in
a controlled real-EoE cross-engine **combat** state, and asserts
**full ``compare_fields(...) == []``** (byte-equality across the WHOLE
cross-engine field view — the strongest Effect+bridge-level evidence)
where the harness drives it cleanly, else the established
targeted-cross-engine-observable idiom with a precise documented
reason.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch F — the cleanly-constructible frontier)
-------------------------------------------------------------------
Sibling agents own the disjoint batch A
(``tests/test_probe_covered_unprobed_a.py``) + B + C + D + E + the
spell-card-bridge sweep (``tests/test_probe_spell_card_bridge_
admitted.py``) + the warp-admitted creatures (``tests/test_probe_
warp_admitted.py``) + the warp+combat-interaction module
(``tests/test_probe_warp_combat_interaction.py``); a Rust agent owns
Seedship Impact / Orbital Plunge. This module owns **batch F**: the
NEXT highest-deck cleanly-probe-constructible covered-but-unprobed
cards NOT in any sibling/Rust set. The covered-by-construction-but-
unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool`` +
``scripts/scout_r58_subsystem_attribution._deck_counts``, sorted by
17lands deck count desc) was verify-first-recomputed at live HEAD
``97069ef1``; every card below is (a) covered-by-construction,
(b) NOT individually probed, (c) NOT in batch A / B / C / D / E /
the spell-card-bridge module / the warp module / the warp+combat
module / the Rust-owned pair.

THE EXHAUSTED-FRONTIER FINDING (honest conclusion, not padding)
---------------------------------------------------------------
Verify-first established that the **Effect-exercising
trigger/spell-effect lane is drained for batch F**: every
deck-bearing single-trigger candidate above the keyword-only band has
a NON-bridge-expressible predicate (``HasCounter`` /
``StateBound``/``SpellsCastThisTurn`` / ``OpponentControlsMoreLands
ThanYou`` — the bridge predicate vocabulary at
``cross_engine.py``:8453-8545 supports only ``always`` /
``source_is_self`` / ``source_is_creature`` / ``subject_is_*`` /
``controlled_by_you`` / ``subject_has_subtype`` / ``not`` / ``and`` /
``or``) OR a non-idiom effect, ALL with established drop precedents:

  * **Selfcraft Mechan** (~26,200) / **Oreplate Pangolin**
    (~18,411) / **Kavaron Harrier** (~9,057) — ETB/ATTACKS →
    ``OptionalSacArtifactForEffect`` / ``OptionalManaCostThenEffect``
    (an optional-cost agent-decision leg with no established
    cross-engine optional-cost mirror idiom — the batch-A / batch-E
    Scrounge-for-Eternity / Lithobraking precedent).
  * **Weftblade Enhancer** (~14,406) —
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures``: the bridge
    arm's OWN docstring (``cross_engine.py``:3903-3919) defers the
    real-EoE probe pending a multi-target picker shim mirroring
    Rust's exact iterator order (the explicit batch-C drop).
  * **Starfield Shepherd** (~12,788) — ``ModalChooseOne`` over
    ``SearchLibraryForCard``; the ``search_library_for_card`` bridge
    arm's OWN docstring (``cross_engine.py``:3774-3781) explicitly
    DEFERS the real-EoE Starfield Shepherd / The Seriema probes
    ("the printed-card variants carry additional triggers / may_fail
    asymmetric agent paths that the bare bridge-arm slice doesn't
    need to exercise").
  * **Sunstar Expansionist** (~12,252) — two ENTERS triggers; the
    higher-leverage CreateToken leg is gated by a non-bridge-
    expressible ``OpponentControlsMoreLandsThanYou`` ``StateBound``,
    so a faithful 2-trigger synthetic mirror is not constructible
    (the batch-B Syr-Vondam "the bare synthetic doesn't carry the
    genuine card's other rider/trigger" precedent).
  * **Cerebral Download** (~11,768) — its ``Sequence`` spell_effect
    is the EXISTING known-divergence xfail pin in
    ``test_parity_smoke.py`` (the batch-D/E precedent).

The genuinely-clean DECK-BEARING covered-but-unprobed frontier is
exactly the **keyword-only creatures** (0 Effects + loader-admitted
``_printing_is_bridge_simple_creature`` — covered-by-construction;
all four printed keywords are in ``trajectory._SAFE_KEYWORDS``). The
0-17lands-deck keyword creatures (Bedhead Beastie, Cackling Slasher,
Daggermaw Megalodon, Piranha Fly, …) are NOT probed — they carry zero
leverage and would be padding. This module pins the 4 deck-bearing
ones, each exercising its genuine printed keyword in a real
cross-engine combat state (the established ``test_parity_smoke.py``
declare_attacker / declare_blocker / deal_combat_damage cross-engine
combat-keyword idiom).

The 4 cards pinned here (deck counts at the verify-first walk):

  | card                     | decks  | keyword    | combat axis      |
  |--------------------------|-------:|------------|------------------|
  | Hullcarver               | 20,796 | deathtouch | 1 dmg = lethal   |
  | Tapestry Warden          |  5,977 | vigilance  | attacks untapped |
  | Monoist Sentry           |  5,893 | defender   | can't attack     |
  | Mm'menon, the Right Hand |  3,738 | flying     | ground can't blk |

(Hullcarver's verify-first 17lands count is 20,397; the table label
rounds; the load-bearing value is "highest-deck covered-but-unprobed
keyword-only creature".)

3/4 assert **full ``compare_fields == []``** over the whole
cross-engine field view (the strongest tier — deathtouch / vigilance
/ flying-evasion). Monoist Sentry (defender) uses the established
cross-engine-eligibility idiom + documented reason: Python's
``legal_actions`` does NOT enumerate ``declare_attackers`` subsets
(it factors combat decisions search-side — the documented
``state_ops_legal.rs`` Python/Rust shape asymmetry), so a faithful
defender probe asserts the cross-engine SEMANTIC predicate (Python
``eligible_attackers`` EXCLUDES it ∧ Rust ``declare_attacker``
REFUSES it ∧ Rust ``legal_decisions`` emits NO ``declare_attackers``
subset containing it) rather than ``compare_fields`` on a
combat-shape Python does not enumerate — the CE17 defender-gate
idiom established in ``test_parity_smoke.py``.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registered in
``scripts/measure_pool_parity.PROBE_MODULES``.
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


def _seat_real_py(py, real, owner_id):
    """Seat the GENUINE parsed printing on ``owner_id``'s battlefield,
    non-summoning-sick, untapped, undamaged — the established
    batch-B/D bf-seating idiom."""
    from mtg_bot.game import Zone

    o = py.new_object(real, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.tapped = False
    o.damage = 0
    o.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(o)
    return o


def _seat_vanilla_py(py, name, owner_id, power, toughness):
    """Seat a plain vanilla creature (no keywords) on ``owner_id``'s
    battlefield — the negative-control / combat-partner shape."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    o = py.new_object(
        CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=power, toughness=toughness, produces=frozenset(),
            keywords=frozenset(),
        ),
        owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    o.summoning_sick = False
    o.tapped = False
    o.damage = 0
    o.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(o)
    return o


def _fv_diff(parity_smoke_mod, py, rs):
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


# ---------------------------------------------------------------------
# Batch-F probe #1 — Hullcarver (~20,397 17lands decks).
#
# Verified covered (0 Effects + loader-admitted
# ``_printing_is_bridge_simple_creature`` → covered-by-construction)
# + unprobed at HEAD 97069ef1. Oracle: a 1/1 Artifact Creature with
# **deathtouch** (∈ ``trajectory._SAFE_KEYWORDS``). The genuine
# printed keyword is exercised in a real cross-engine combat state:
# the 1/1 Hullcarver BLOCKS a vanilla 3/3 → its 1 combat damage is
# LETHAL via deathtouch (CR 702.2b) so BOTH creatures die; the 3/3's
# 3 back-damage also kills the 1/1 on BOTH. Full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_hullcarver_deathtouch_block_lethal_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Hullcarver (~20,397
    17lands decks). Batch-F covered→PROBED.**

    Python: the ACTUAL parsed Hullcarver printing (1/1, deathtouch)
    seated on p0's battlefield as the BLOCKER of a p1 vanilla 3/3
    attacker; combat damage resolved directly (the established
    ``test_parity_smoke.py`` LL+DT / FS+DT direct-combat idiom). Rust:
    a synthetic carrier carrying the SAME ``deathtouch`` keyword,
    driven via ``declare_attacker`` / ``declare_blocker`` /
    ``deal_combat_damage``.

    Deathtouch upgrades Hullcarver's 1-damage mark on the 3/3 to
    lethal (CR 702.2b) → the 3/3 dies; the 3/3's 3 back-damage kills
    the 1/1 → BOTH die on BOTH engines.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (both creatures leave the bf to their
    owners' graveyards; lives unchanged — no trample/lifelink;
    byte-equal on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Hullcarver")
    if real is None:
        pytest.skip("Hullcarver absent from active CardSource")
    assert "Creature" in real.card_types
    assert "deathtouch" in {str(k) for k in (real.keywords or ())}, (
        f"genuine Hullcarver must carry deathtouch; "
        f"got keywords={sorted(real.keywords or ())}"
    )
    assert int(real.power) == 1 and int(real.toughness) == 1, (
        "probe pins the genuine 1/1 body — its 1 damage is only "
        "lethal via deathtouch (the load-bearing axis)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 vanilla 3/3 attacker; p0 blocks with the genuine Hullcarver.
    py_atk = _seat_vanilla_py(py, "HC Attacker", 1, 3, 3)
    py_atk.controller_id = 1
    py_blk = _seat_real_py(py, real, 0)
    py_atk.attacking = True
    py_atk.tapped = True
    py_blk.blocking = int(py_atk.id)
    py_atk.blocked_by.append(int(py_blk.id))

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    resolve_combat_damage(py, defending_player_id=0)
    py_sba(py)

    py_bf_names = {o.printing.name for o in py.battlefield}
    assert "HC Attacker" not in py_bf_names, (
        "Python: the vanilla 3/3 must DIE to Hullcarver's deathtouch "
        "1-damage mark (CR 702.2b)"
    )
    assert "Hullcarver" not in py_bf_names, (
        "Python: the 1/1 Hullcarver must DIE to the 3/3's back-damage"
    )
    assert py.players[0].life == py_p0_life0
    assert py.players[1].life == py_p1_life0

    rs_atk = rs.register_and_inject_object(
        {"name": "HC Attacker", "card_types": ["Creature"],
         "power": 3, "toughness": 3, "keywords": []}, 1, ZB)
    rs_blk = rs.register_and_inject_object(
        {"name": "Hullcarver",
         "card_types": ["Artifact", "Creature"],
         "power": int(real.power), "toughness": int(real.toughness),
         "keywords": ["deathtouch"]}, 0, ZB)
    rs.clear_summoning_sick_for_player(0)
    rs.clear_summoning_sick_for_player(1)
    assert rs.declare_attacker(rs_atk) is True
    assert rs.declare_blocker(rs_blk, rs_atk) is True
    rs.deal_combat_damage()
    rs.apply_sbas()

    rs_bf_ids = {int(e["id"]) for e in rs.battlefield_snapshot()}
    assert rs_atk not in rs_bf_ids, (
        "Rust: the vanilla 3/3 must DIE to deathtouch"
    )
    assert rs_blk not in rs_bf_ids, (
        "Rust: the 1/1 Hullcarver must DIE to the 3/3's back-damage"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Hullcarver deathtouch-block-lethal must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-F probe #2 — Tapestry Warden (~5,977 17lands decks).
#
# Verified covered (0 Effects + loader-admitted) + unprobed at HEAD.
# Oracle: a 3/4 Artifact Creature with **vigilance** (∈
# ``trajectory._SAFE_KEYWORDS``). The genuine printed keyword is
# exercised cross-engine: declaring the Warden as an attacker does
# NOT tap it (CR 702.21b) on BOTH engines — Python via the engine
# ``declare_attackers`` path, Rust via ``declare_attacker``. Full
# ``compare_fields`` (the attacker is ATTACKING + UNTAPPED on BOTH).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_tapestry_warden_vigilance_attacks_untapped_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Tapestry Warden
    (~5,977 17lands decks). Batch-F covered→PROBED.**

    Python: the ACTUAL parsed Tapestry Warden printing (3/4,
    vigilance) seated on p0's battlefield, declared as an attacker
    via the engine ``combat.declare_attackers`` path. Rust: a
    synthetic carrier carrying the SAME ``vigilance`` keyword via
    ``declare_attacker``.

    Vigilance (CR 702.21b): attacking does NOT tap the creature. On
    BOTH engines the Warden ends ATTACKING + UNTAPPED.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the Warden's ``tapped`` slot is False +
    its ``attacking`` slot True on BOTH — byte-equal). Concretely
    double-pinned (Python ``obj.tapped is False``; Rust
    ``is_tapped`` False).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers, eligible_attackers

    real = get_active_source().get_printings().get("Tapestry Warden")
    if real is None:
        pytest.skip("Tapestry Warden absent from active CardSource")
    assert "Creature" in real.card_types
    assert "vigilance" in {str(k) for k in (real.keywords or ())}, (
        f"genuine Tapestry Warden must carry vigilance; "
        f"got keywords={sorted(real.keywords or ())}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py_atk = _seat_real_py(py, real, 0)
    elig_ids = {o.id for o in eligible_attackers(py, 0)}
    assert py_atk.id in elig_ids, (
        "probe pre-condition: the Warden must be an eligible attacker "
        "for p0 (non-sick, untapped, no defender)"
    )
    declare_attackers(py, [int(py_atk.id)])
    assert py_atk.attacking is True, (
        "Python: the Warden must be ATTACKING after declare_attackers"
    )
    assert py_atk.tapped is False, (
        "Python: vigilance → declaring the attack must NOT tap the "
        "Warden (CR 702.21b)"
    )

    rs_atk = rs.register_and_inject_object(
        {"name": "Tapestry Warden",
         "card_types": ["Artifact", "Creature"],
         "power": int(real.power), "toughness": int(real.toughness),
         "keywords": ["vigilance"]}, 0, ZB)
    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_atk) is True
    assert rs.is_tapped(rs_atk) is False, (
        "Rust: vigilance → declare_attacker must NOT tap the Warden"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Tapestry Warden vigilance-attacks-untapped must be "
        f"byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-F probe #3 — Monoist Sentry (~5,893 17lands decks).
#
# Verified covered (0 Effects + loader-admitted) + unprobed at HEAD.
# Oracle: a 4/1 Artifact Creature with **defender** (∈
# ``trajectory._SAFE_KEYWORDS``). Defender (CR 702.3): the creature
# CAN'T attack. The established CE17 defender-gate cross-engine idiom
# (``test_parity_smoke.py``): Python's ``legal_actions`` does NOT
# enumerate ``declare_attackers`` subsets (it factors combat
# decisions search-side — the documented ``state_ops_legal.rs``
# Python/Rust shape asymmetry), so a faithful probe asserts the
# cross-engine SEMANTIC predicate: Python ``eligible_attackers``
# EXCLUDES it ∧ Rust ``declare_attacker`` REFUSES it ∧ Rust
# ``legal_decisions`` emits NO ``declare_attackers`` subset
# containing it. NOT ``compare_fields`` (Python does not enumerate
# the combat-shape this pins) — the documented established idiom +
# precise reason.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_monoist_sentry_defender_cannot_attack_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Monoist Sentry
    (~5,893 17lands decks). Batch-F covered→PROBED.**

    Python: the ACTUAL parsed Monoist Sentry printing (4/1,
    defender) seated on p0's battlefield. Rust: a synthetic carrier
    carrying the SAME ``defender`` keyword.

    Defender (CR 702.3): the creature can't be declared as an
    attacker. **Established CE17 cross-engine-eligibility idiom +
    documented reason** (NOT ``compare_fields``): Python's
    ``legal_actions`` does not enumerate ``declare_attackers``
    subsets (it factors combat decisions search-side — the
    documented ``state_ops_legal.rs`` Python/Rust shape asymmetry),
    so the faithful cross-engine assertion is the SEMANTIC predicate:

      * Python ``combat.eligible_attackers(state, 0)`` EXCLUDES the
        Sentry (CR 702.3-correct, ``combat.py:eligible_attackers``).
      * Rust ``declare_attacker`` REFUSES it (returns False — the
        apply-time gate).
      * Rust ``legal_decisions(0)`` emits NO ``declare_attackers``
        subset containing the Sentry id (the CE17 enumeration-time
        eligibility-filter contract).

    Both engines agree the defender can never attack — byte-equal
    SEMANTICS on the only axis Python exposes for it.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import eligible_attackers

    real = get_active_source().get_printings().get("Monoist Sentry")
    if real is None:
        pytest.skip("Monoist Sentry absent from active CardSource")
    assert "Creature" in real.card_types
    assert "defender" in {str(k) for k in (real.keywords or ())}, (
        f"genuine Monoist Sentry must carry defender; "
        f"got keywords={sorted(real.keywords or ())}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py_d = _seat_real_py(py, real, 0)
    elig_ids = {o.id for o in eligible_attackers(py, 0)}
    assert py_d.id not in elig_ids, (
        f"Python: the defender must be EXCLUDED from "
        f"eligible_attackers (CR 702.3); elig={elig_ids}"
    )

    rs_d = rs.register_and_inject_object(
        {"name": "Monoist Sentry",
         "card_types": ["Artifact", "Creature"],
         "power": int(real.power), "toughness": int(real.toughness),
         "keywords": ["defender"]}, 0, ZB)
    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_d) is False, (
        "Rust: declare_attacker must REFUSE the defender (CR 702.3 "
        "apply-time gate)"
    )
    ld = rs.legal_decisions(0)
    da_subsets = [
        tuple(a.get("attacker_ids", [])) for a in ld
        if a.get("kind") == "declare_attackers"
    ]
    illegal = [s for s in da_subsets if rs_d in s]
    assert not illegal, (
        f"Rust: legal_decisions must emit NO declare_attackers "
        f"subset containing the defender (CE17 enumeration-time "
        f"eligibility filter); offending subsets={illegal}"
    )


# ---------------------------------------------------------------------
# Batch-F probe #4 — Mm'menon, the Right Hand (~3,738 17lands decks).
#
# Verified covered (0 Effects + loader-admitted) + unprobed at HEAD.
# Oracle: a 3/4 Creature with **flying** (∈
# ``trajectory._SAFE_KEYWORDS``). Flying (CR 702.9): can be blocked
# only by creatures with flying or reach (CR 702.17). The genuine
# printed keyword is exercised cross-engine: Mm'menon attacks; a
# vanilla ground 2/2 CANNOT block it on BOTH engines (Python
# ``combat.can_block`` returns False; Rust ``declare_blocker``
# refuses) → unblocked, deals 3 to the defending player on BOTH.
# Full ``compare_fields`` (the established flying-evasion idiom).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_mmenon_the_right_hand_flying_evasion_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Mm'menon, the Right
    Hand (~3,738 17lands decks). Batch-F covered→PROBED.**

    Python: the ACTUAL parsed Mm'menon, the Right Hand printing (3/4,
    flying) seated on p0's battlefield as an attacker; a p1 vanilla
    ground 2/2 attempts to block. Rust: a synthetic carrier carrying
    the SAME ``flying`` keyword via ``declare_attacker`` /
    ``declare_blocker``.

    Flying (CR 702.9 / 702.17): a creature without flying or reach
    can't block it. On BOTH engines the ground 2/2's block is
    REFUSED (Python ``combat.can_block`` False; Rust
    ``declare_blocker`` False) → Mm'menon is unblocked and deals 3
    combat damage to p1.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (Mm'menon ATTACKING + alive + 0 damage;
    the ground 2/2 alive + NOT blocking + 0 damage; p1 life −3 — all
    byte-equal on BOTH). Concretely double-pinned (p1 life delta on
    BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import can_block, resolve_combat_damage
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get(
        "Mm'menon, the Right Hand")
    if real is None:
        pytest.skip(
            "Mm'menon, the Right Hand absent from active CardSource")
    assert "Creature" in real.card_types
    assert "flying" in {str(k) for k in (real.keywords or ())}, (
        f"genuine Mm'menon must carry flying; "
        f"got keywords={sorted(real.keywords or ())}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py_atk = _seat_real_py(py, real, 0)
    py_blk = _seat_vanilla_py(py, "MM Ground", 1, 2, 2)
    py_blk.controller_id = 1
    assert can_block(py, py_blk, py_atk) is False, (
        "Python: a vanilla ground creature must NOT be able to block "
        "the flyer (CR 702.9 / 702.17)"
    )

    # The block is refused → Mm'menon attacks unblocked.
    py_atk.attacking = True
    py_atk.tapped = True
    py_p1_life0 = py.players[1].life
    resolve_combat_damage(py, defending_player_id=1)
    py_sba(py)
    assert py.players[1].life == py_p1_life0 - int(real.power), (
        f"Python: unblocked flyer deals {real.power} to p1; "
        f"{py_p1_life0} → {py.players[1].life}"
    )
    py_bf_names = {o.printing.name for o in py.battlefield}
    assert "Mm'menon, the Right Hand" in py_bf_names, (
        "Python: the unblocked flyer takes no back-damage → alive"
    )
    assert "MM Ground" in py_bf_names, (
        "Python: the would-be blocker never engaged → alive"
    )

    rs_atk = rs.register_and_inject_object(
        {"name": "Mm'menon, the Right Hand",
         "card_types": ["Creature"],
         "power": int(real.power), "toughness": int(real.toughness),
         "keywords": ["flying"]}, 0, ZB)
    rs_blk = rs.register_and_inject_object(
        {"name": "MM Ground", "card_types": ["Creature"],
         "power": 2, "toughness": 2, "keywords": []}, 1, ZB)
    rs.clear_summoning_sick_for_player(0)
    rs.clear_summoning_sick_for_player(1)
    assert rs.declare_attacker(rs_atk) is True
    assert rs.declare_blocker(rs_blk, rs_atk) is False, (
        "Rust: declare_blocker must REFUSE a vanilla ground blocker "
        "against the flyer (CR 702.9 / 702.17)"
    )
    rs_p1_life0 = rs.get_life(1)
    rs.deal_combat_damage()
    rs.apply_sbas()
    assert rs.get_life(1) == rs_p1_life0 - int(real.power), (
        f"Rust: unblocked flyer deals {real.power} to p1; "
        f"{rs_p1_life0} → {rs.get_life(1)}"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Mm'menon flying-evasion (ground can't block, unblocked "
        f"3-to-face) must be byte-equal across the WHOLE field view "
        f"on BOTH; diffs={diffs}"
    )
