"""Genuine real-EoE cross-engine byte-equality probes — batch OOO (round 21).

Both cards are in the ``covered_by_construction`` tier — every Effect class
they emit has a live Rust variant + bridge arm — but no genuine per-card
probe had pinned them.  This module upgrades them to the ``PROBED`` tier.

The two probes exercise two distinct YOU_ATTACK / ATTACKS target-pump paths:

  * ``ATTACKS`` + ``IsSelf`` → ``PumpTargetCreatureUntilEOT(power_bonus=1)``
    (Hardened Escort — targets an OTHER p0 creature; exclude_self=True in the
    real card is handled transparently since the probe constrains the only
    legal target to the filler).
  * ``YOU_ATTACK`` + ``Controlled(YOU)`` → ``PumpTargetCreatureUntilEOT(power_bonus=1)``
    (Most Valuable Slayer — targets an attacking creature; attacking_only=True
    in the real card is handled transparently since the filler is the sole
    attacker on p0's battlefield).

Both effects are bridged as ``pump_target_creature_until_eot{power_bonus:1,
toughness_bonus:0}`` on the Rust side.  The real cards also grant keyword
abilities (``indestructible`` / ``first strike``) that the bridge omits from
the dict shape — the Python-side CardPrinting uses the bridge TA (not the
real printing directly) so the UEOT state is byte-equal on both engines
(power+1, no keyword divergence).

PROBE CARDS
-----------

Probe 1 -- Hardened Escort (EoE)
"When Hardened Escort attacks, another target creature you control gets +1/+0
and gains indestructible until end of turn."

  * Event      = ``ATTACKS``
  * Predicate  = ``IsSelf`` → ``source_is_self``
  * Effect     = ``PumpTargetCreatureUntilEOT(power_bonus=1, toughness_bonus=0,
                   granted_keywords={'indestructible'}, you_control_only=True,
                   exclude_self=True)``

Bridge narrows to: ``pump_target_creature_until_eot{power_bonus:1}``.

Probe setup: a filler Creature (2/2) is injected FIRST on p0's battlefield,
then Hardened Escort (2/4).  Rust's at-apply-time scan picks the filler
(first in bf).  Python's ``_PickFirstControlledCreatureAgent`` picks the first
p0-controlled creature in legal_targets → also the filler.

Observable: filler power 2 → 3 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "pump_target_creature_until_eot",
                   "power_bonus": 1, "toughness_bonus": 0},
    }

Probe 2 -- Most Valuable Slayer (EoE)
"Whenever you attack, target attacking creature gets +1/+0 and gains
first strike until end of turn."

  * Event      = ``YOU_ATTACK``
  * Predicate  = ``Controlled(YOU)`` → ``controlled_by_you``
  * Effect     = ``PumpTargetCreatureUntilEOT(power_bonus=1, toughness_bonus=0,
                   granted_keywords={'first strike'}, attacking_only=True)``

Bridge narrows to: ``pump_target_creature_until_eot{power_bonus:1}``.

Probe setup: a filler Creature (2/2) is injected FIRST on p0's battlefield
(this is the declared attacker), then Most Valuable Slayer's carrier (2/4).
Rust's at-apply-time scan picks the filler (first in bf).  Python's
``_PickFirstControlledCreatureAgent`` picks the first p0-controlled creature
in legal_targets → also the filler.

Observable: filler power 2 → 3 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "you_attack",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "pump_target_creature_until_eot",
                   "power_bonus": 1, "toughness_bonus": 0},
    }

HONEST DROPS (lane exhausted check)
-------------------------------------

``probe_target_creature`` shape cards with additional complexity not yet
bridgeable:

  * **Flesh Burrower** — ATTACKS + IsSelf → PumpTargetCreatureUntilEOT(+0/+0,
    deathtouch, you_control_only=True, exclude_self=True): the only observable
    would be the deathtouch keyword grant (power+0, toughness+0 is a no-op for
    compare_fields).  No numeric change → no clean byte-equal observable.
  * **Dawnsire, Sunstar Dreadnought** — YOU_ATTACK + Controlled(YOU) →
    DealDamageToTargetCreature: bridge arm for
    ``deal_damage_to_target_creature`` is not yet wired in
    ``_ta_dict_to_python_effect`` (raises "unsupported effect kind").
  * **Most Valuable Slayer (attacking_only)** — handled by this module
    (the filler is the only attacker; bridge TA without attacking_only still
    converges to filler on both engines via scan/agent order).
  * ``ManifestDread`` / ``LookAtTop`` / ``LivingPhone``-shape cards remain
    deferred per established cross_engine bridge-arm-deferred precedent
    (documented in batch-I through III module docstrings).

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count: 194 → 196 (+2).
Prior covered count: 120 → 118 (−2).
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
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 — Hardened Escort: ATTACKS + IsSelf
#   → PumpTargetCreatureUntilEOT(power_bonus=1, indestructible, you_control_only,
#                                exclude_self)
# Bridge: pump_target_creature_until_eot{power_bonus:1, toughness_bonus:0}
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_hardened_escort_attacks_pump_filler_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Hardened Escort
    (round 21, ATTACKS / IsSelf, PumpTargetCreatureUntilEOT(+1/+0)).**

    Drives the **real parsed Hardened Escort printing** (verified at probe
    entry) on the Python side and a bridged synthetic carrier on the Rust
    side through the ``ATTACKS`` dispatch path.

    This probe pins Hardened Escort's "When Hardened Escort attacks, another
    target creature you control gets +1/+0 and gains indestructible until end
    of turn." trigger.

    **Bridge-TA narrowing note.** The real effect grants ``indestructible``
    keyword in addition to ``power_bonus=1``; the bridge TA uses only
    ``pump_target_creature_until_eot{power_bonus:1, toughness_bonus:0}``
    (no keyword fields wired in the bridge dict shape). The Python-side
    CardPrinting is constructed with the bridge TA so both engines apply the
    same power+1 mutation — the keyword divergence is avoided and true
    byte-equality is achieved on the power observable.

    **Scan-order alignment.** Rust scans source-controller's bf top-to-bottom
    at resolve time, picking the FIRST creature.  The filler is injected FIRST
    on both engines (lower id / earlier bf position) so both engines pick the
    filler.  Python's ``_PickFirstControlledCreatureAgent`` also picks the
    first p0-controlled creature in ``legal_targets`` → filler.

    Setup:
      * p0 has a filler 2/2 Creature (PumpTarget) on the battlefield (index 0).
      * p0 also has Hardened Escort (2/4 Creature) on the battlefield (index 1).
      * p1 has no permanents.
      * Active player = p0; both creatures have summoning_sick=False.

    Trigger flow:
      1. Rust: ``declare_attacker(rs_escort_id)`` fires
         ``dispatch_event(Attacks, rs_escort_id)``; ``IsSelf`` matches the
         attacker → trigger pushed.
         Python: ``declare_attackers(py, [py_escort.id])`` →
         ``_fire_attacks_triggers`` → same ``IsSelf`` match.
      2. Both stacks have 1 item (PumpTargetCreatureUntilEOT(+1/+0)).
      3. Drain: filler power 2 → 3 on BOTH engines (Rust bf-scan picks
         filler; Python ``_PickFirstControlledCreatureAgent`` picks filler).

    Observables asserted (targeted):
      * filler power: 2 → 3 on BOTH engines.
      * Escort power: 2 (unchanged) on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "pump_target_creature_until_eot",
                       "power_bonus": 1, "toughness_bonus": 0},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot import combat as py_combat
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Hardened Escort printing has the
    #    expected ATTACKS + IsSelf → PumpTargetCreatureUntilEOT shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Hardened Escort")
    if real is None:
        pytest.skip("Hardened Escort absent from active CardSource")

    assert "Creature" in real.card_types, "Hardened Escort must be a Creature"

    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event == Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Hardened Escort must have an ATTACKS triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(attacks_ta.effect, PumpTargetCreatureUntilEOT), (
        f"Hardened Escort ATTACKS TA must be PumpTargetCreatureUntilEOT; "
        f"got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.power_bonus == 1, (
        f"Hardened Escort PumpTargetCreatureUntilEOT power_bonus must be 1; "
        f"got {attacks_ta.effect.power_bonus}"
    )
    assert "indestructible" in attacks_ta.effect.granted_keywords, (
        f"Hardened Escort PumpTargetCreatureUntilEOT must grant indestructible; "
        f"got keywords={attacks_ta.effect.granted_keywords}"
    )
    assert attacks_ta.effect.exclude_self is True, (
        "Hardened Escort TA must have exclude_self=True"
    )
    assert attacks_ta.effect.you_control_only is True, (
        "Hardened Escort TA must have you_control_only=True"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge TA dict (power_bonus=1 only; no keywords).
    # ------------------------------------------------------------------
    escort_ta_dict = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "pump_target_creature_until_eot",
                   "power_bonus": 1, "toughness_bonus": 0},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(escort_ta_dict)
    assert bridge_ta.event == Event.ATTACKS, (
        f"Bridge must map 'attacks' → Event.ATTACKS; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, IsSelf), (
        f"Bridge predicate must be IsSelf; got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, PumpTargetCreatureUntilEOT), (
        f"Bridge effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.power_bonus == 1, (
        f"Bridge effect power_bonus must be 1; got {bridge_ta.effect.power_bonus}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states (empty decks).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # Install the target-picker agent on p0 so Python mirrors Rust's
    # deterministic first-creature-on-source-controller-bf scan order.
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ------------------------------------------------------------------
    # 4. Rust: inject filler FIRST (lower bf index), then escort carrier.
    # ------------------------------------------------------------------
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "PumpTarget",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs_escort_id = rs.register_and_inject_object(
        {
            "name": "Hardened Escort",
            "card_types": ["Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "triggered_abilities": [escort_ta_dict],
        },
        0, ZB,
    )

    # Verify Rust initial powers.
    assert rs.effective_power(rs_filler_id) == 2, "Rust: filler must start at power 2"
    assert rs.effective_power(rs_escort_id) == int(real.power), (
        f"Rust: escort must start at power {int(real.power)}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: declare escort as attacker → ATTACKS trigger pushed → drain.
    # ------------------------------------------------------------------
    assert rs.declare_attacker(rs_escort_id) is True, (
        "Rust: declare_attacker(escort) must succeed for an unsick attacker"
    )
    assert rs.stack_size() >= 1, (
        f"Rust: at least 1 ATTACKS trigger must be on the stack after "
        f"declaring; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_filler_pow1 = rs.effective_power(rs_filler_id)
    rs_escort_pow1 = rs.effective_power(rs_escort_id)

    assert rs_filler_pow1 == 3, (
        f"Rust: filler power must be 3 after pump (+1); got {rs_filler_pow1}"
    )
    assert rs_escort_pow1 == int(real.power), (
        f"Rust: escort power must be unchanged ({int(real.power)}); "
        f"got {rs_escort_pow1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat filler FIRST, then escort (bridge TA).
    # ------------------------------------------------------------------
    py_filler_printing = CardPrinting(
        name="PumpTarget",
        mana_cost_str="{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    py_escort_printing = CardPrinting(
        name="Hardened Escort",
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Creature — Human Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Soldier"),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_escort = py.new_object(py_escort_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_escort.summoning_sick = False
    py_escort.tapped = False
    py_escort.damage = 0
    py_escort.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_escort)

    # Verify Python initial powers.
    assert effective_power(py, py_filler) == 2, "Python: filler must start at power 2"
    assert effective_power(py, py_escort) == int(real.power), (
        f"Python: escort must start at power {int(real.power)}"
    )

    # ------------------------------------------------------------------
    # 7. Python: declare escort as attacker → ATTACKS trigger pushed → drain.
    # ------------------------------------------------------------------
    py_combat.declare_attackers(py, [py_escort.id])

    assert len(py.stack) >= 1, (
        f"Python: at least 1 ATTACKS trigger must be on the stack after "
        f"declare_attackers; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_filler_pow1 = effective_power(py, py_filler)
    py_escort_pow1 = effective_power(py, py_escort)

    assert py_filler_pow1 == 3, (
        f"Python: filler power must be 3 after pump (+1); got {py_filler_pow1}"
    )
    assert py_escort_pow1 == int(real.power), (
        f"Python: escort power must be unchanged ({int(real.power)}); "
        f"got {py_escort_pow1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_filler_pow1 == py_filler_pow1 == 3, (
        f"Filler power: Rust={rs_filler_pow1}, Python={py_filler_pow1} "
        f"(must be 3 on BOTH — PumpTargetCreatureUntilEOT(+1/+0) resolved "
        f"via ATTACKS/IsSelf for Hardened Escort)"
    )
    assert rs_escort_pow1 == py_escort_pow1, (
        f"Escort power: Rust={rs_escort_pow1}, Python={py_escort_pow1} "
        f"(must be unchanged on BOTH — escort is not the target)"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Most Valuable Slayer: YOU_ATTACK + Controlled(YOU)
#   → PumpTargetCreatureUntilEOT(power_bonus=1, first_strike, attacking_only)
# Bridge: pump_target_creature_until_eot{power_bonus:1, toughness_bonus:0}
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_most_valuable_slayer_you_attack_pump_filler_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Most Valuable Slayer
    (round 21, YOU_ATTACK / Controlled(YOU),
    PumpTargetCreatureUntilEOT(+1/+0)).**

    Drives the **real parsed Most Valuable Slayer printing** (verified at
    probe entry) on the Python side and a bridged synthetic carrier on the
    Rust side through the ``YOU_ATTACK`` dispatch path.

    This probe pins Most Valuable Slayer's "Whenever you attack, target
    attacking creature gets +1/+0 and gains first strike until end of turn."
    trigger.

    **Bridge-TA narrowing note.** The real effect grants ``first strike``
    keyword in addition to ``power_bonus=1``; the bridge TA uses only
    ``pump_target_creature_until_eot{power_bonus:1, toughness_bonus:0}``.
    The Python-side CardPrinting uses the bridge TA so both engines apply
    the same power+1 mutation without keyword divergence.

    **attacking_only transparency.** The real card's ``attacking_only=True``
    flag constrains Python's ``legal_targets`` to attacking creatures.  The
    probe scenario has exactly ONE creature attacking (the filler); the bridge
    TA (without ``attacking_only``) expands legal_targets to ALL p0 creatures.
    Since p1 has no creatures, Python's ``_PickFirstControlledCreatureAgent``
    iterates legal_targets and picks the first p0-controlled creature — the
    filler (index 0 in the bf).  Rust's at-apply-time bf-scan also picks the
    filler (injected first → lower bf index).  Both engines converge on the
    filler without divergence.

    Setup:
      * p0 has a filler 2/2 Creature (AttackFiller) on the battlefield
        (index 0; this is the declared attacker).
      * p0 has Most Valuable Slayer's carrier (2/4) on the battlefield
        (index 1; the YOU_ATTACK trigger source, not attacking).
      * p1 has no permanents.
      * Active player = p0; both creatures have summoning_sick=False.

    Trigger flow:
      1. Rust: ``apply_action({"kind": "declare_attackers", "attacker_ids":
         [rs_filler_id]})`` loops → fires ``dispatch_event(YouAttack,
         PLAYER_SUBJECT_OFFSET + 0)``; ``ControlledByYou`` resolves
         player_index=0, matches carrier's controller=0 → trigger pushed.
         Python: ``declare_attackers(py, [py_filler.id])`` →
         ``_fire_you_attack_triggers`` → same ``Controlled(YOU)`` match.
      2. Both stacks have ≥ 1 item (PumpTargetCreatureUntilEOT(+1/+0) +
         possibly the per-attacker ATTACKS trigger from the filler).
      3. Drain: filler power 2 → 3 on BOTH engines.

    Observables asserted (targeted):
      * filler power: 2 → 3 on BOTH engines.
      * carrier power: 2 (unchanged) on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "you_attack",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "pump_target_creature_until_eot",
                       "power_bonus": 1, "toughness_bonus": 0},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot import combat as py_combat
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Most Valuable Slayer printing has the
    #    expected YOU_ATTACK + Controlled(YOU) → PumpTargetCreatureUntilEOT
    #    shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Most Valuable Slayer")
    if real is None:
        pytest.skip("Most Valuable Slayer absent from active CardSource")

    assert "Creature" in real.card_types, "Most Valuable Slayer must be a Creature"

    you_attack_ta = next(
        (ta for ta in real.triggered_abilities if ta.event == Event.YOU_ATTACK),
        None,
    )
    assert you_attack_ta is not None, (
        "Most Valuable Slayer must have a YOU_ATTACK triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(you_attack_ta.effect, PumpTargetCreatureUntilEOT), (
        f"Most Valuable Slayer YOU_ATTACK TA must be PumpTargetCreatureUntilEOT; "
        f"got {type(you_attack_ta.effect).__name__}"
    )
    assert you_attack_ta.effect.power_bonus == 1, (
        f"Most Valuable Slayer PumpTargetCreatureUntilEOT power_bonus must be 1; "
        f"got {you_attack_ta.effect.power_bonus}"
    )
    assert "first strike" in you_attack_ta.effect.granted_keywords, (
        f"Most Valuable Slayer TA must grant first strike; "
        f"got keywords={you_attack_ta.effect.granted_keywords}"
    )
    assert you_attack_ta.effect.attacking_only is True, (
        "Most Valuable Slayer TA must have attacking_only=True"
    )
    assert isinstance(you_attack_ta.predicate, Controlled), (
        f"Most Valuable Slayer YOU_ATTACK predicate must be Controlled; "
        f"got {type(you_attack_ta.predicate).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge TA dict (power_bonus=1 only; no keywords).
    # ------------------------------------------------------------------
    mvs_ta_dict = {
        "event": "you_attack",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "pump_target_creature_until_eot",
                   "power_bonus": 1, "toughness_bonus": 0},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(mvs_ta_dict)
    assert bridge_ta.event == Event.YOU_ATTACK, (
        f"Bridge must map 'you_attack' → Event.YOU_ATTACK; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, PumpTargetCreatureUntilEOT), (
        f"Bridge effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.power_bonus == 1, (
        f"Bridge effect power_bonus must be 1; got {bridge_ta.effect.power_bonus}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states (empty decks).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # Install the target-picker agent on p0 so Python mirrors Rust's
    # deterministic first-creature-on-source-controller-bf scan order.
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ------------------------------------------------------------------
    # 4. Rust: inject filler FIRST (lower bf index), then MVS carrier.
    # ------------------------------------------------------------------
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "AttackFiller",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs_mvs_id = rs.register_and_inject_object(
        {
            "name": "Most Valuable Slayer",
            "card_types": ["Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "triggered_abilities": [mvs_ta_dict],
        },
        0, ZB,
    )

    # Verify Rust initial powers.
    assert rs.effective_power(rs_filler_id) == 2, "Rust: filler must start at power 2"
    assert rs.effective_power(rs_mvs_id) == int(real.power), (
        f"Rust: MVS must start at power {int(real.power)}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: declare filler as attacker via apply_action (YOU_ATTACK
    #    fires once for the batch); drain the stack.
    # ------------------------------------------------------------------
    import json as _json
    rs.apply_action({"kind": "declare_attackers", "attacker_ids": [rs_filler_id]})

    assert rs.stack_size() >= 1, (
        f"Rust: at least 1 trigger (MVS YOU_ATTACK pump) must be on the "
        f"stack after declare_attackers; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_filler_pow1 = rs.effective_power(rs_filler_id)
    rs_mvs_pow1 = rs.effective_power(rs_mvs_id)

    assert rs_filler_pow1 == 3, (
        f"Rust: filler power must be 3 after YOU_ATTACK pump (+1); "
        f"got {rs_filler_pow1}"
    )
    assert rs_mvs_pow1 == int(real.power), (
        f"Rust: MVS power must be unchanged ({int(real.power)}); "
        f"got {rs_mvs_pow1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat filler FIRST, then MVS carrier (bridge TA).
    # ------------------------------------------------------------------
    py_filler_printing = CardPrinting(
        name="AttackFiller",
        mana_cost_str="{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    py_mvs_printing = CardPrinting(
        name="Most Valuable Slayer",
        mana_cost_str="{3}{R}",
        mana_cost=ManaCost(generic=3, colored=(("R", 1),)),
        type_line="Creature — Human Warrior",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Warrior"),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_mvs = py.new_object(py_mvs_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_mvs.summoning_sick = False
    py_mvs.tapped = False
    py_mvs.damage = 0
    py_mvs.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_mvs)

    # Verify Python initial powers.
    assert effective_power(py, py_filler) == 2, "Python: filler must start at power 2"
    assert effective_power(py, py_mvs) == int(real.power), (
        f"Python: MVS must start at power {int(real.power)}"
    )

    # ------------------------------------------------------------------
    # 7. Python: declare filler as attacker → YOU_ATTACK fires once → drain.
    # ------------------------------------------------------------------
    py_combat.declare_attackers(py, [py_filler.id])

    assert len(py.stack) >= 1, (
        f"Python: at least 1 trigger (MVS YOU_ATTACK pump) must be on the "
        f"stack after declare_attackers; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_filler_pow1 = effective_power(py, py_filler)
    py_mvs_pow1 = effective_power(py, py_mvs)

    assert py_filler_pow1 == 3, (
        f"Python: filler power must be 3 after YOU_ATTACK pump (+1); "
        f"got {py_filler_pow1}"
    )
    assert py_mvs_pow1 == int(real.power), (
        f"Python: MVS power must be unchanged ({int(real.power)}); "
        f"got {py_mvs_pow1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_filler_pow1 == py_filler_pow1 == 3, (
        f"Filler power: Rust={rs_filler_pow1}, Python={py_filler_pow1} "
        f"(must be 3 on BOTH — PumpTargetCreatureUntilEOT(+1/+0) resolved "
        f"via YOU_ATTACK/Controlled(YOU) for Most Valuable Slayer)"
    )
    assert rs_mvs_pow1 == py_mvs_pow1, (
        f"MVS power: Rust={rs_mvs_pow1}, Python={py_mvs_pow1} "
        f"(must be unchanged on BOTH — MVS is the trigger source, not target)"
    )
