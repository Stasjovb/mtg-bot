"""**Warping Wail Cycle 3 substrate (2026-05-24).**

Tests for the new token-AA bridge widen — the
``_token_creature_with_safe_mana_activated_ability_card_def`` helper +
the matching ``_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY`` dict constant —
that admits creature tokens with a sac-self mana activated ability
(Warping Wail mode 3's "Create a 1/1 colorless Eldrazi Scion creature
token. It has '{T}, Sacrifice this token: Add {C}.'" — the engine
authors the token as the simplified bare ``Sacrifice this token: Add
{C}`` AA on a 1/1 creature body per ``cards/tokens.py``).

This is a **substrate-only closure** — the cycle adds the
creature-token-with-sac-self-mana-AA bridge admission as a reusable
infrastructure lever. Warping Wail itself stays DECLINED at the
spell-card-bridge admit gate this cycle because the Phase-6 modal
admit gate widen + per-mode binder still gap (Cycle 4).

  - **Mode 1 (Cycle 1a, landed)**:
    ``ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)``.
  - **Mode 2 (Cycle 2, landed)**: ``CounterTargetSpell.filter_types``.
  - **Mode 3 (this cycle)**: token-AA bridge widen for creature tokens
    with sac-self mana abilities.
  - **Cycle 4**: admit-gate widen for the ``(0, 1)``+
    ``or_both=False`` Phase-6 modal shape, per-mode binders, +
    cross-engine probe.

See ``docs/SEARCH_LIMITATIONS.md`` "Warping Wail Cycle 1a substrate
LANDED" and "Warping Wail Cycle 2 substrate LANDED" blocks for the
4-cycle decomposition rationale.

**Test plan:**

  - Helper SoT pins: the new
    ``_token_creature_with_safe_mana_activated_ability_card_def``
    admits the EoE ``Eldrazi Scion`` printing and declines every
    per-disqualifier variant (§2 silent-mistranslation discipline).
  - Pre-existing helpers are unchanged: ``_token_vanilla_card_def``
    declines the Eldrazi Scion (activated ability ≠ vanilla);
    ``_token_with_safe_activated_ability_card_def`` declines the
    Eldrazi Scion (Lander-shape gate rejects creature body + non-mana
    cost shape).
  - Cross-engine byte-equal-printing pin: the Python
    ``CardPrinting`` materialized by ``_card_def_to_python_printing``
    from the helper's CardDef is bit-identical to the authored
    ``TOKEN_PRINTINGS["Eldrazi Scion"]`` for every forward-relevant
    field (P/T, card types, subtypes, supertypes, the
    ``activated_abilities`` tuple).
  - Synthetic-state probe: mint the Eldrazi Scion on a Rust state
    via the bridge-correct dict shape + activate the sac-self mana
    AA + verify (a) the token leaves the battlefield (sac), (b) the
    {C} mana lands in the controller's pool, (c) no stack activity
    (mana ability bypasses the stack per CR 605.3a). The matching
    Python execution is exercised via direct
    ``_activate_ability`` on a synthetic state with the Python
    bridge's materialized printing, and the observables (mana pool,
    battlefield) must match.
  - **Substrate-only invariant**: the Cycle 1a
    ``test_warping_wail_stays_declined_at_admit_gate_post_cycle_1a``
    pin continues to fire — Warping Wail's
    ``_printing_is_bridge_simple_spell`` admit-gate verdict is
    unchanged (still declined).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


# ---------------------------------------------------------------------------
# Helper-side SoT pins
# ---------------------------------------------------------------------------


def test_helper_admits_authored_eldrazi_scion():
    """**Helper SoT pin.** The new
    ``_token_creature_with_safe_mana_activated_ability_card_def``
    helper admits the real EoE ``Eldrazi Scion`` token printing — the
    creature-token sac-self mana AA shape Warping Wail mode 3 mints.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    scion = TOKEN_PRINTINGS.get("Eldrazi Scion")
    assert scion is not None
    cd = _token_creature_with_safe_mana_activated_ability_card_def(scion)
    assert cd is not None, (
        "the new helper must ADMIT the authored Eldrazi Scion "
        "(creature body, sac-self mana AA — Warping Wail mode 3)"
    )
    assert cd.name == "Eldrazi Scion"
    assert cd.card_type == "Creature"
    assert cd.extra_card_types == ()
    assert cd.power == 1
    assert cd.toughness == 1
    assert cd.subtypes == ("Eldrazi", "Scion")
    assert cd.supertypes == ("Token",)
    # The CardDef carries exactly one token_activated_abilities dict
    # matching :data:`_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY`.
    assert len(cd.token_activated_abilities) == 1
    aa = cd.token_activated_abilities[0]
    assert aa == {
        "cost": {"sacrifice_self": True},
        "effect": {"kind": "add_mana_to_pool", "color": "C", "amount": 1},
        "is_mana_ability": True,
    }


def test_helper_declines_lander_token():
    """**§2 sibling-split pin.** The new helper declines the Lander
    token — the Lander's gate
    (``_token_with_safe_activated_ability_card_def``) is the canonical
    admit-site for that shape (non-creature artifact + {2}+sac+Search
    AA), and the creature-token+mana-AA helper is a separate sibling
    that must NOT cross-admit it.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    lander = TOKEN_PRINTINGS.get("Lander")
    assert lander is not None
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(lander)
        is None
    ), "Lander (non-creature artifact) must NOT admit on the creature-shape gate"


def test_helper_declines_treasure_token():
    """**§2 sibling-split pin.** The Treasure token (tap+sac→Add any)
    declines — it has the wrong cost shape (``tap_self=True`` on top of
    ``sacrifice_self=True``), and it's a non-creature artifact.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    treasure = TOKEN_PRINTINGS.get("Treasure")
    assert treasure is not None
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(treasure)
        is None
    ), "Treasure (non-creature + tap_self) must NOT admit"


def test_helper_declines_vanilla_creature_token():
    """**§2 sibling-split pin.** A vanilla creature token (the Human
    Soldier) carries NO activated abilities — the creature-shape gate
    requires EXACTLY ONE matching AA. Declines via the AA-count check.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    soldier = TOKEN_PRINTINGS.get("Human Soldier")
    assert soldier is not None
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(soldier)
        is None
    ), "vanilla creature token (no AAs) must NOT admit"


def test_helper_declines_added_mana_cost():
    """**§2 per-disqualifier pin.** A creature token whose AA has the
    Scion's structure but adds a ``{1}`` generic mana cost fails the
    strict cost gate (cost.mana must be None — the real Scion AA has
    no mana cost).
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    bad = CardPrinting(
        name="Bad Scion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Creature - Eldrazi Scion",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Eldrazi", "Scion"),
        power=1, toughness=1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=ManaCost(generic=1),
                    sacrifice_self=True,
                ),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


def test_helper_declines_non_mana_ability_flag():
    """**§2 per-disqualifier pin.** A creature token whose AA matches
    the cost + effect shape but is flagged ``is_mana_ability=False``
    declines — the stack-bypass behavior is part of the shape contract
    (mana abilities resolve immediately per CR 605.3a; non-mana
    abilities push to stack), and silently dropping the flag would
    diverge the timing cross-engine.
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    bad = CardPrinting(
        name="Bad Scion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Creature - Eldrazi Scion",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Eldrazi", "Scion"),
        power=1, toughness=1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=False,  # the disqualifier
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


def test_helper_declines_wrong_color():
    """**§2 per-disqualifier pin.** A creature token whose AA produces
    ``{W}`` instead of ``{C}`` declines — the shape contract pins the
    color so a future Spirit-shape (white mana) variant is a separate
    recognizer-widen, not a silent extension.
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    bad = CardPrinting(
        name="Bad Scion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Creature - Eldrazi Scion",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Eldrazi", "Scion"),
        power=1, toughness=1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("W", 1),)),  # not {C}
                is_mana_ability=True,
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


def test_helper_declines_non_creature_token():
    """**§2 per-disqualifier pin.** A non-creature token (the Lander
    artifact) with the Scion-shape AA declines on the creature-type
    gate. The new helper §2-strictly requires a Creature body — a
    non-creature with the same AA is a separate shape and would
    surface here only by a registry copy-paste bug.
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    # Artifact-only token, no Creature type.
    bad = CardPrinting(
        name="Synthetic Mana Source",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=(),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


def test_helper_declines_two_activated_abilities():
    """**§2 per-disqualifier pin.** A creature token with TWO AAs (the
    first matches the Scion shape, the second is anything else) declines
    — admitting it would silently drop the second ability cross-engine.
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    bad = CardPrinting(
        name="Bad Scion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Creature - Eldrazi Scion",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Eldrazi", "Scion"),
        power=1, toughness=1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
            # A second AA — exact shape doesn't matter, presence kills.
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


def test_helper_declines_keyword_carrier():
    """**§2 per-disqualifier pin.** A creature token with the Scion-
    shape AA + a ``flying`` keyword declines — the CardDef bridge
    threads keywords through ``CardDef.keywords``, but the helper
    requires the token to be otherwise clean. Admitting a keyword
    rider here would silently land in the bridge unverified.
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    bad = CardPrinting(
        name="Bad Scion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Creature - Eldrazi Scion",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Eldrazi", "Scion"),
        power=1, toughness=1,
        keywords=frozenset({"flying"}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    assert (
        _token_creature_with_safe_mana_activated_ability_card_def(bad)
        is None
    )


# ---------------------------------------------------------------------------
# Pre-existing helpers continue to decline the Scion (§2-honest split)
# ---------------------------------------------------------------------------


def test_vanilla_helper_continues_to_decline_eldrazi_scion():
    """**§2 sibling-split pin.** ``_token_vanilla_card_def`` is
    UNCHANGED — it declines the Eldrazi Scion (has an activated
    ability, so the no-AAs gate at line 2861 returns None).
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import _token_vanilla_card_def

    scion = TOKEN_PRINTINGS.get("Eldrazi Scion")
    assert scion is not None
    assert _token_vanilla_card_def(scion) is None, (
        "vanilla gate must still decline a token with any AA"
    )


def test_lander_helper_continues_to_decline_eldrazi_scion():
    """**§2 sibling-split pin.**
    ``_token_with_safe_activated_ability_card_def`` (the Lander-shape
    helper) is UNCHANGED — it declines the Eldrazi Scion (creature
    body fails the ``if "Creature" in card_types: return None`` gate).
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_with_safe_activated_ability_card_def,
    )

    scion = TOKEN_PRINTINGS.get("Eldrazi Scion")
    assert scion is not None
    assert _token_with_safe_activated_ability_card_def(scion) is None, (
        "Lander-shape gate must still decline a creature-body token"
    )


# ---------------------------------------------------------------------------
# Cross-engine byte-equal printing-materialization pin
# ---------------------------------------------------------------------------


def test_cross_engine_byte_equal_printing_for_eldrazi_scion():
    """**Byte-equal printing-materialization pin.** The Python
    ``CardPrinting`` materialized by the cross-engine bridge
    (``_card_def_to_python_printing`` consuming the helper's CardDef)
    is bit-identical to the authored ``TOKEN_PRINTINGS["Eldrazi
    Scion"]`` for every forward-relevant field. This is the §2
    correctness guarantee for the printing-registration walk: the
    seated token's bridge-materialized printing matches what Python's
    direct ``TOKEN_PRINTINGS["Eldrazi Scion"]`` would mint, so
    Warping Wail mode 3's eventual cross-engine resolve probe (in
    Cycle 4) can pivot on either side to identical observables.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing
    from mtg_bot.parity.trajectory import (
        _token_creature_with_safe_mana_activated_ability_card_def,
    )

    scion = TOKEN_PRINTINGS["Eldrazi Scion"]
    cd = _token_creature_with_safe_mana_activated_ability_card_def(scion)
    assert cd is not None
    bridge_pr = _card_def_to_python_printing(cd)

    # Forward-relevant field comparisons (the same fields the round-51
    # cache key folds in — name, card_types, P/T, subtypes, supertypes,
    # keywords, triggered_abilities, token_activated_abilities).
    assert bridge_pr.name == scion.name
    assert bridge_pr.card_types == scion.card_types
    assert bridge_pr.power == scion.power
    assert bridge_pr.toughness == scion.toughness
    assert bridge_pr.subtypes == scion.subtypes
    assert bridge_pr.supertypes == scion.supertypes
    assert bridge_pr.keywords == scion.keywords
    assert bridge_pr.triggered_abilities == scion.triggered_abilities
    assert bridge_pr.activated_abilities == scion.activated_abilities


# ---------------------------------------------------------------------------
# Synthetic-state probe — sac-self mana AA byte-equal across engines
# ---------------------------------------------------------------------------


def _rust_inject_eldrazi_scion(rs, owner):
    """Mint an Eldrazi Scion on owner's battlefield using the bridge-
    correct dict shape (the same shape the helper's CardDef → Rust
    registry-dict path emits). Returns the object id.

    Mirrors the registry-dict shape ``build_rust_state`` would emit
    from a CardDef synthesized by
    ``_token_creature_with_safe_mana_activated_ability_card_def``."""
    return rs.register_and_inject_object(
        {
            "name": "Eldrazi Scion",
            "card_types": ["Creature"],
            "mana_cost": {},
            "power": 1,
            "toughness": 1,
            "subtypes": ["Eldrazi", "Scion"],
            "supertypes": ["Token"],
            "activated_abilities": [
                {
                    "cost": {"sacrifice_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "C",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        },
        owner, _ZONE_BATTLEFIELD,
    )


def test_rust_synthetic_state_sac_self_mana_activation_byte_equal():
    """**Synthetic-state probe (Rust half).** Mint the Eldrazi Scion
    on a Rust state, activate its sac-self mana AA, and verify the
    byte-equal observables Warping Wail mode 3 cares about:

      * the token leaves the battlefield (sac path: bf_pos removed
        per CR 117.10 cost-pay-before-effect ordering);
      * the {C} mana lands in the controller's pool;
      * the stack is empty (mana ability bypasses the stack per
        CR 605.3a);
      * graveyard is empty (a token ceases to exist on leaving the
        battlefield per CR 704.5d — does NOT go to graveyard).
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    oid = _rust_inject_eldrazi_scion(rs, owner=0)
    # Clear summoning sickness so the activation path is the no-tap
    # case (the Scion has no tap cost, but the dispatch path checks
    # sickness for safety on creature-typed sources).
    rs.clear_summoning_sick_for_player(0)
    pool_before = rs.get_mana_pool(0)
    assert pool_before["C"] == 0
    assert rs.find_object_zone(oid) == _ZONE_BATTLEFIELD

    rs.apply_action({
        "kind": "activate_ability",
        "source_id": oid,
        "ability_index": 0,
    })

    # Observable 1: {C} pool increment.
    pool_after = rs.get_mana_pool(0)
    assert pool_after["C"] == 1, (
        f"sac-self mana AA must add exactly one {{C}} to the pool; "
        f"got pool_after={pool_after!r}"
    )

    # Observable 2: token sacrificed off the battlefield (token ceases
    # to exist on bf-leave per CR 704.5d — the Rust path returns None
    # for find_object_zone when the token is gone).
    assert rs.find_object_zone(oid) is None, (
        "Eldrazi Scion token must cease to exist after sac (CR 704.5d)"
    )

    # Observable 3: stack stayed empty (mana ability bypasses stack
    # per CR 605.3a — both engines short-circuit the stack push for
    # is_mana_ability=True).
    assert rs.stack_size() == 0

    # Observable 4: graveyard remained empty (token CR 704.5d — no
    # graveyard pass-through).
    gy_sizes = rs.graveyard_sizes
    assert gy_sizes == [0, 0], (
        f"token cease-to-exist must NOT route through graveyard "
        f"(CR 704.5d); got graveyard_sizes={gy_sizes!r}"
    )


def test_python_direct_sac_self_mana_activation_byte_equal():
    """**Synthetic-state probe (Python half).** Activate the
    authored ``TOKEN_PRINTINGS["Eldrazi Scion"]`` via Python's
    ``_activate_ability`` on a synthetic state with the token on the
    battlefield, and verify the SAME observables Rust honors:

      * {C} pool increment (exactly one colorless ``ManaCoin``);
      * token leaves the battlefield (sacrifice cost — CR 117.10);
      * stack stayed empty (CR 605.3a mana-ability stack-bypass).

    Byte-equal cross-engine: the same authored printing on the
    Python side produces the same pool/bf delta the Rust path does in
    the sibling test above."""
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.actions import _activate_ability
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state

    # Build a minimal synthetic Python state — the same
    # ``build_python_state`` path the cross-engine harness uses for
    # synthetic-only probes (no decklist, no card_defs union; the
    # state is empty except for the Eldrazi Scion we inject below).
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    scion_printing = TOKEN_PRINTINGS["Eldrazi Scion"]
    token = py.new_object(scion_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    token.summoning_sick = False
    token.tapped = False
    token.damage = 0
    token.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(token)

    # Pre-activation observables: empty mana pool, token on bf,
    # empty stack.
    p0_pool = py.players[0].mana_pool
    assert len(p0_pool) == 0
    assert any(o.id == token.id for o in py.battlefield)
    assert len(py.stack) == 0

    _activate_ability(py, 0, token.id, 0)

    # Observable 1: {C} pool increment (exactly one colorless coin).
    p0_pool = py.players[0].mana_pool
    c_coins = [c for c in p0_pool if c.color == "C"]
    assert len(c_coins) == 1, (
        f"Python sac-self mana AA must add exactly one {{C}} to the "
        f"pool; got mana_pool={p0_pool!r}"
    )
    # No other-color coins land — the produces=(("C", 1),) shape
    # mints exactly one colorless mana, nothing else.
    assert len(p0_pool) == 1, (
        f"sac-self mana AA must produce ONLY the {{C}} mana; "
        f"got mana_pool={p0_pool!r}"
    )

    # Observable 2: token off the battlefield (sacrifice cost — CR
    # 117.10 pays before the effect resolves). CR 704.5d's
    # cease-to-exist for tokens is enforced at state-based-action
    # time; the cycle's invariant pin is "off the battlefield", which
    # the sac cost guarantees regardless of where the token routes
    # next.
    bf_ids = [o.id for o in py.battlefield]
    assert token.id not in bf_ids, (
        "Eldrazi Scion must leave the battlefield after sac (CR 117.10)"
    )

    # Observable 3: stack stayed empty (mana-ability bypasses stack
    # per CR 605.3a — Python's ``_activate_ability`` short-circuits
    # the stack push when ``ability.is_mana_ability`` is True, just
    # like Rust's ActivateAbility dispatch arm).
    assert len(py.stack) == 0


# ---------------------------------------------------------------------------
# Substrate-only invariant — Warping Wail STAYS DECLINED at the admit gate
# ---------------------------------------------------------------------------


def test_warping_wail_stays_declined_at_admit_gate_post_cycle_3():
    """**Substrate-only invariant pin (this cycle).** Cycle 3 ships
    ONLY the token-AA bridge widen + the synthetic probe.
    ``_printing_is_bridge_simple_spell`` MUST still decline Warping
    Wail — flipping it requires the Cycle 4 admit-gate widen for the
    ``(0, 1)`` + ``or_both=False`` Phase-6 modal shape + the per-mode
    binders. The pin mirrors the Cycle 1a equivalent at
    ``test_warping_wail_substrate_cycle_1a.py:test_warping_wail_
    stays_declined_at_admit_gate_post_cycle_1a``.

    If this pin fails — i.e. Warping Wail starts admitting on this
    branch — the substrate-only invariant has been violated and the
    cross-engine probe will run BEFORE the Cycle 4 admit-gate widen,
    producing wrong byte-equal claims. Catch the drift here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Warping Wail")
    if real is None:
        pytest.skip("Warping Wail absent from active CardSource")
    assert not trajectory._printing_is_bridge_simple_spell(real), (
        "Warping Wail MUST still be declined at the admit gate after "
        "Cycle 3 substrate-only landing (the (0,1)+or_both=False "
        "Phase-6 modal admit-gate widen + per-mode binders still gap; "
        "see docs/SEARCH_LIMITATIONS.md 'Warping Wail Cycle 1a "
        "substrate LANDED'). A flip here is a substrate-scope "
        "violation."
    )
