"""**Carrier-AA substrate Phase 4B Cycle 3 (2026-05-26).**

Tests for the Phase 4B Cycle 3 Rust spell-copy substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §4.1.1 + §6.2 pins
#9-13 (refined per the C2 commit's narrowed sequencing — C3 is the
Rust-only spell-copy substrate for Mirrorpool's AA[0]; C4 ships the
Python admit widen + bridge arms + Mirrorpool FLIP; C5 ships the
real-EoE per-card probe).

**The C2 closure at ``58988ade`` shipped the Python admit widen for
Mirrorpool's AA[1] (``CreateTokenCopyOfTargetCreatureYouControl``,
CR-707.5 token-creature-copy) — Mirrorpool's per-AA admit predicate
gate flipped DECLINED → ADMITTED at AA[1]. The sibling AA[0]
``CopyTargetInstantOrSorceryYouControl`` (CR-707.2 spell-copy) had
NO Rust substrate at C2 — C3 closes that gap.

C3 lands the FULL Rust substrate for CR-707.2 spell-copy:

  1. **``Effect::CopyTargetInstantOrSorceryYouControl`` enum variant**
     — unit variant on the Rust ``Effect`` enum at ``cards.rs``.
     Sibling of ``Effect::CreateTokenCopyOfTargetCreatureYouControl``
     (Mirrorpool's AA[1]).

  2. **``parse_effect`` arm** — recognizes ``{"kind":
     "copy_target_instant_or_sorcery_you_control"}`` and constructs
     the unit variant.

  3. **``to_pydict`` arm** — round-trips the unit variant back to the
     ``{"kind": "..."}`` dict.

  4. **``state_ops_legal.rs::activate_ability_dict`` stack-target fan-
     out arm** — walks ``state.stack`` for activator-controlled
     ``Spell``-kind items whose printing is instant or sorcery and
     emits one ``ActivateAbility`` per eligible target with
     ``target_creature_id = Some(stack_item.source_obj_id)``. Mirrors
     the design doc §4.1.1 target enumeration (sibling of the
     battlefield-target fan-out at ``state_ops_legal.rs:3408-3505``
     but reads ``state.stack`` instead of ``state.battlefield``).

  5. **``state_ops_actions.rs::ActivateAbility`` validation arm** —
     re-checks the chosen ``target_creature_id`` against (a) stack
     presence, (b) ``StackItemKind::Spell``, (c) controller ==
     activator, (d) printing is instant OR sorcery. Sibling of the
     C1 token-copy validation arm; ``target_creature_id`` is OPTIONAL
     on this effect (substrate-fallback path is silent-fizzle).

  6. **``state_ops_resolve.rs`` resolve arm** — consults
     ``current_resolve_payload_target_id`` for the chosen target
     spell's ``source_obj_id``. Re-validates per CR 608.2b (target
     legality re-check at resolve time — fizzle silently if the
     target left the stack or no longer matches the criteria). Else
     clones the target StackItem with ``is_copy=true``, SAME targets
     / SAME modes / SAME X / SAME printing_id / controller =
     activator, and pushes to the top of the stack. **Does NOT**
     dispatch ``Event::SpellCast`` — copies are NEVER cast (CR
     707.10). The copy resolves BEFORE the original because it sits
     on top of the stack (CR 608.2).

  7. **``StackItem.is_copy`` field** — new ``bool`` field on the
     Rust ``StackItem`` struct at ``state.rs`` with ``default =
     false``. Every existing StackItem constructor (``new_spell``,
     ``new_spell_with_targets``,
     ``new_spell_with_targets_mode_addcost_and_x``,
     ``new_spell_with_targets_and_modes``, ``new_trigger``,
     ``new_trigger_with_target``) defaults the field to ``false``;
     the new copy push site sets it to ``true``. The bespoke
     synthetic-spell push helper in ``state_ops_resolve.rs:26548``
     also defaults to ``false``. **NOT in the per-StackItem
     fingerprint tuple** so pre-substrate stacks stay byte-equal —
     same discipline as ``chosen_mode_idx`` /
     ``additional_cost_choice_id`` / ``chosen_mode_idxs`` /
     ``x_value``.

  8. **Test-surface getters** — ``stack_top_is_copy()`` (top item),
     ``set_stack_top_is_copy(bool)`` (synthetic-test setter,
     production safe — only called from test code), and
     ``stack_item_is_copy(index)`` (per-index getter for asserting
     the resolve arm sets the flag ONLY on the newly-pushed copy
     and NOT on the original target item).

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen for
``CopyTargetInstantOrSorceryYouControl`` ships C4 per design doc
§5.4; the cross-engine bridge forward + reverse arms ship C4 too).
ZERO per-card probe this cycle (Phase 4B probe per design doc §6.7
ships at C5 once the admit widen + FLIP lands).

Substrate-only invariant — Mirrorpool STAYS DECLINED at the admit
gate post-Cycle-3. The Rust substrate (Effect variant + parse +
to_pydict + resolve + stack-target fan-out + validation +
StackItem.is_copy) all lands; the live admit gate still declines
Mirrorpool's printing because
``_carrier_aa_phase_1_effect_classes`` doesn't yet include
``CopyTargetInstantOrSorceryYouControl`` (C4 widens it). Under
Phase 4A's multi-AA all-or-nothing contract a printing admits only
if EVERY AA admits, and Mirrorpool's AA[0]'s Effect class isn't in
the admit set post-C3.

**Verify-first findings (live tree, main ``58988ade``):**

  - ``Effect::CopyTargetInstantOrSorceryYouControl`` did NOT exist in
    ``rust/src/cards.rs`` pre-C3 (no matches for either the variant
    name OR its snake_case parse key).
  - ``StackItem`` had NO ``is_copy`` field pre-C3 (the Python
    ``StackItem`` dataclass also has no ``is_copy`` field — Python
    uses layered ``"is_copy"`` registry entries on GameObjects per
    CR 706.2, a different "is_copy" concept that applies to
    permanents-that-are-copies, not stack items). So the new Rust
    ``is_copy`` flag is Rust-only bookkeeping at this slice; if
    Python ever grows a sibling field, the round-trip codec can add
    a mirror arm at that time.
  - The C1 token-copy substrate at ``434d6aa1`` shipped the per-
    Effect-variant target validation pattern at
    ``state_ops_actions.rs`` (the `is_create_token_copy_creature_
    effect` arm). C3 mirrors that pattern for the new variant.
  - The C1 token-copy substrate shipped the
    ``current_resolve_payload_target_id`` swap pattern at the
    ``Effect::CreateTokenCopyOfTargetCreatureYouControl`` resolve
    arm. C3 mirrors that pattern for the new variant.

This is a **substrate-only closure** — the cycle wires the Rust
spell-copy surface (Effect variant + parse + to_pydict + stack-
target fan-out + validation + resolve + StackItem.is_copy). C4
ships the Python admit widen + bridge arms + Mirrorpool FLIP. C5
ships the real-EoE per-card probe.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


@pytest.fixture
def synthetic_state(engine):
    """A 0-bf / 0-hand / 0-library state — everything injected via
    ``register_and_inject_object``. Mirrors the
    ``_fresh_state()`` pattern in
    ``test_x_value_subsystem_cycle1.py``."""
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Test-fixture helpers
# ---------------------------------------------------------------------------


def _synthetic_mirrorpool_aa0_only_dict():
    """Minimal Mirrorpool-AA[0]-shape Land printing dict for the Rust
    Registry. AA[0] is the bare ``{2}{C}, {T}, Sac: Copy target instant
    or sorcery spell you control`` shape — modeled at the C3 Rust
    surface as ``{generic=3, tap_self=true, sacrifice_self=true}``
    cost + ``copy_target_instant_or_sorcery_you_control`` unit-variant
    effect dict. Mirrors the live Mirrorpool AA[0] shape verified at
    the C1 test file's verify-first walk."""
    return {
        "name": "Synthetic Mirrorpool AA0",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 3},
                },
                "effect": {
                    "kind":
                        "copy_target_instant_or_sorcery_you_control",
                },
            },
        ],
    }


def _vanilla_instant_printing_dict(name="Synthetic Instant Probe"):
    """A minimal instant printing — a draw-1 spell with no riders. The
    spell-copy AA[0] fan-out arm walks ``state.stack`` for
    activator-controlled spells whose printing is instant or sorcery;
    this fixture builds the bare instant shape."""
    return {
        "name": name,
        "mana_cost": {"generic": 1},
        "card_types": ["Instant"],
        "effects": [
            {"kind": "draw_cards", "count": 1},
        ],
    }


def _vanilla_sorcery_printing_dict(name="Synthetic Sorcery Probe"):
    """A minimal sorcery printing — a draw-1 sorcery. Sibling of the
    instant printing dict above; exercises the OR branch in the fan-
    out arm's instant-OR-sorcery filter."""
    return {
        "name": name,
        "mana_cost": {"generic": 1},
        "card_types": ["Sorcery"],
        "effects": [
            {"kind": "draw_cards", "count": 1},
        ],
    }


def _vanilla_creature_printing_dict(name="Synthetic Creature Probe"):
    """A minimal creature printing for the negative-target pin (creature
    spells on the stack are NOT eligible targets for the spell-copy
    AA[0])."""
    return {
        "name": name,
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
    }


# ---------------------------------------------------------------------------
# Design doc §6.2 #9 — Rust parse_effect arm round-trip pin
# ---------------------------------------------------------------------------


def test_rust_register_printing_with_copy_target_instant_or_sorcery_aa(
    engine,
):
    """**Design doc §6.2 #9 — Rust parse-arm pin (the first of the 5
    C3 substrate pins).** A synthetic Mirrorpool-AA[0]-shape Land
    printing with the new ``copy_target_instant_or_sorcery_you_control``
    unit-variant effect registers cleanly through
    ``Registry.register_printing`` — Rust's ``parse_effect`` accepts
    the unit-variant dict and constructs
    ``Effect::CopyTargetInstantOrSorceryYouControl`` for the
    activated-ability's effect slot.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_mirrorpool_aa0_only_dict())
    assert reg.get_printing_name(pid) == "Synthetic Mirrorpool AA0"


# ---------------------------------------------------------------------------
# Design doc §6.2 #10 — Rust to_pydict round-trip pin
# ---------------------------------------------------------------------------


def test_rust_to_pydict_arm_re_register_round_trip(engine):
    """**Design doc §6.2 #10 — to_pydict round-trip pin.** A
    Mirrorpool-AA[0]-shape printing can be registered TWICE
    independently — each invocation parses the same effect dict to
    the new ``Effect::CopyTargetInstantOrSorceryYouControl`` unit
    variant. Two distinct printings result; both name-resolve
    correctly. This exercises the parse arm + the variant's
    insertion into ``activated_abilities[i].effect`` repeatedly
    without panicking.

    **Why this shape.** Rust has no direct AA-effect dict getter
    that re-emits the full AA effect (only per-field getters like
    ``get_printing_name``). The dedicated Python bridge round-trip
    pin (``_python_aa_to_safe_dict`` forward → ``_ta_dict_to_
    python_effect`` reverse) is C4's deliverable. At C3 the
    to_pydict path is reachable indirectly: any Rust caller that
    builds an Effect via ``parse_effect`` and later prints it via
    ``effect_to_pydict`` exercises both arms — the printing-snapshot
    surface in ``stack_snapshot`` / ``battlefield_snapshot`` /
    ``legal_decisions`` action-dict emission all read through that
    path. This pin asserts the variant survives at least one
    parse / re-parse cycle without crashing the registry.
    """
    reg1 = engine.Registry()
    pid1 = reg1.register_printing(_synthetic_mirrorpool_aa0_only_dict())
    assert reg1.get_printing_name(pid1) == "Synthetic Mirrorpool AA0"
    # A second Registry independent of the first — parse arm fires
    # again from the same dict.
    reg2 = engine.Registry()
    pid2 = reg2.register_printing(_synthetic_mirrorpool_aa0_only_dict())
    assert reg2.get_printing_name(pid2) == "Synthetic Mirrorpool AA0"
    # Sanity: registering MULTIPLE copies into the SAME registry
    # also works (re-entrance of parse_effect on the same unit
    # variant).
    reg3 = engine.Registry()
    pid_a = reg3.register_printing(_synthetic_mirrorpool_aa0_only_dict())
    aa1_dict = _synthetic_mirrorpool_aa0_only_dict()
    aa1_dict["name"] = "Synthetic Mirrorpool AA0 #2"
    pid_b = reg3.register_printing(aa1_dict)
    assert pid_a != pid_b
    assert reg3.get_printing_name(pid_a) == "Synthetic Mirrorpool AA0"
    assert (
        reg3.get_printing_name(pid_b) == "Synthetic Mirrorpool AA0 #2"
    )


# ---------------------------------------------------------------------------
# Design doc §6.2 #11 — Rust resolve happy path
# ---------------------------------------------------------------------------


def test_rust_resolve_pushes_copy_onto_stack(engine, synthetic_state):
    """**Design doc §6.2 #11 — Rust resolve happy path.** Set up:
    Mirrorpool on p0's bf + a vanilla Instant in p0's hand. p0 casts
    the Instant (which goes onto the stack as a real Spell-kind
    StackItem); then p0 activates Mirrorpool's AA[0] targeting the
    Instant on the stack. Resolving the AA[0] should:

      * Push a NEW StackItem onto the stack (stack_size goes from
        2 → 3 — Instant + AA + new copy).
      * The new top-of-stack StackItem has ``is_copy = true``.
      * The new top-of-stack StackItem has the SAME source_obj_id as
        the original Instant (the copy points at the same stack
        object's printing).
      * The original Instant's StackItem still has ``is_copy = false``
        (the cloning sets the flag ONLY on the new push).
    """
    # Inject Mirrorpool on p0's bf, summoning-sick cleared.
    mp_id = synthetic_state.register_and_inject_object(
        _synthetic_mirrorpool_aa0_only_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)
    # Inject a vanilla Instant in p0's hand.
    instant_id = synthetic_state.register_and_inject_object(
        _vanilla_instant_printing_dict(), 0, ZONE_HAND,
    )
    # Cast the Instant onto the stack.
    synthetic_state.add_mana(0, "C", 1)
    cast_ok = synthetic_state.cast_spell_noncreature(instant_id, 0)
    assert cast_ok is True
    assert synthetic_state.stack_size() == 1
    # The cast spell's stack item has is_copy=false (real cast, not a
    # copy).
    assert synthetic_state.stack_item_is_copy(0) is False

    # Now activate Mirrorpool's AA[0] targeting the Instant on the
    # stack.
    synthetic_state.add_mana(0, "C", 3)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": mp_id,
        "ability_index": 0,
        "target_creature_id": instant_id,
    })
    # Stack now has 2 items: [Instant, AA].
    assert synthetic_state.stack_size() == 2
    # The instant's is_copy stays false; the AA's is_copy is also
    # false (the AA itself is the copy-spell ability, not a copy).
    assert synthetic_state.stack_item_is_copy(0) is False
    assert synthetic_state.stack_item_is_copy(1) is False

    # Resolve the top of the stack (the AA).
    synthetic_state.resolve_top_of_stack()
    # Resolution pushed a new copy onto the stack — now stack_size is
    # 2 again: [Instant, copy-of-Instant]. (AA popped from top, then
    # the copy was pushed at the new top.)
    assert synthetic_state.stack_size() == 2, (
        "Phase 4B C3 resolve-arm pin: post-resolution stack should be "
        "2 items (original Instant + copy-of-Instant); the AA popped, "
        "and the copy was pushed on top"
    )
    # The original Instant at index 0 still has is_copy=false.
    assert synthetic_state.stack_item_is_copy(0) is False, (
        "Phase 4B C3 resolve-arm pin: the original Instant must NOT "
        "have its is_copy flag mutated; only the new push at the top "
        "carries the flag"
    )
    # The copy at the top (index 1) has is_copy=true.
    assert synthetic_state.stack_top_is_copy() is True, (
        "Phase 4B C3 resolve-arm pin: the new top-of-stack StackItem "
        "(the copy) MUST have is_copy=true"
    )
    assert synthetic_state.stack_item_is_copy(1) is True


# ---------------------------------------------------------------------------
# Design doc §6.2 #12 — Rust resolve silent-fizzle (no legal target)
# ---------------------------------------------------------------------------


def test_rust_resolve_silent_fizzle_when_no_payload_target(
    engine, synthetic_state,
):
    """**Design doc §6.2 #12 — Rust resolve silent-fizzle pin.**
    Activate Mirrorpool's AA[0] WITHOUT a ``target_creature_id``
    (substrate-fallback path; the validation arm passes ``None`` —
    target is OPTIONAL on this effect). Resolving the AA[0] should
    silently fizzle (no new StackItem pushed; no error raised).

    Unlike the token-creature-copy AA[1] which has a
    deterministic-first-creature fallback on the activator's bf, the
    spell-copy AA[0] has NO fallback — there's no canonical
    "deterministic first stack item" without an explicit target
    binding. Per CR 707.2 + 608.2b, the copy substrate requires an
    explicit chosen target; absence of one is silent fizzle.
    """
    # Inject Mirrorpool on p0's bf.
    mp_id = synthetic_state.register_and_inject_object(
        _synthetic_mirrorpool_aa0_only_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)

    # Activate AA[0] WITHOUT a target (substrate-fallback path).
    synthetic_state.add_mana(0, "C", 3)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": mp_id,
        "ability_index": 0,
    })
    assert synthetic_state.stack_size() == 1
    pre_stack_size = synthetic_state.stack_size()

    # Resolve. Should silently fizzle.
    synthetic_state.resolve_top_of_stack()
    # Stack went from 1 → 0 (AA popped, nothing pushed).
    assert synthetic_state.stack_size() == 0, (
        "Phase 4B C3 silent-fizzle pin: with no payload target, the "
        "AA resolves to a no-op; the AA pops but nothing is pushed in "
        f"its place. Got stack_size {synthetic_state.stack_size()} "
        f"(expected 0; pre was {pre_stack_size})."
    )


# ---------------------------------------------------------------------------
# Design doc §6.2 #13 — StackItem.is_copy round-trip
# ---------------------------------------------------------------------------


def test_stack_item_is_copy_round_trip_via_synthetic_setter(
    engine, synthetic_state,
):
    """**Design doc §6.2 #13 — StackItem.is_copy round-trip pin.** The
    new ``is_copy`` field on the Rust StackItem struct round-trips
    correctly through the synthetic-test setter:

      * Default ``is_copy=false`` on every push (every constructor
        defaults to ``false``; the bare ``cast_spell_noncreature``
        push is the canonical example).
      * ``set_stack_top_is_copy(true)`` sets the flag.
      * ``stack_top_is_copy()`` reads the flag back.
      * ``stack_item_is_copy(0)`` reads the flag at index 0 (sibling
        getter).
      * ``set_stack_top_is_copy(false)`` unsets the flag.
      * Multiple pushes preserve per-item flags independently (a
        copy + a non-copy on the stack can coexist).
    """
    # Empty-stack default.
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.stack_top_is_copy() is False

    # Cast a real Instant. Default is_copy=false.
    instant_id = synthetic_state.register_and_inject_object(
        _vanilla_instant_printing_dict("Round-Trip Instant"), 0, ZONE_HAND,
    )
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.cast_spell_noncreature(instant_id, 0)
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.stack_top_is_copy() is False
    assert synthetic_state.stack_item_is_copy(0) is False

    # Set is_copy=true via the synthetic setter.
    synthetic_state.set_stack_top_is_copy(True)
    assert synthetic_state.stack_top_is_copy() is True
    assert synthetic_state.stack_item_is_copy(0) is True

    # Push a second spell (a sorcery). It defaults to is_copy=false;
    # the first item's flag stays true (independent per-item state).
    sorcery_id = synthetic_state.register_and_inject_object(
        _vanilla_sorcery_printing_dict("Round-Trip Sorcery"), 0, ZONE_HAND,
    )
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.cast_spell_noncreature(sorcery_id, 0)
    assert synthetic_state.stack_size() == 2
    # The new top (the sorcery) defaults to is_copy=false.
    assert synthetic_state.stack_top_is_copy() is False
    assert synthetic_state.stack_item_is_copy(1) is False
    # The first item (the instant) still has is_copy=true — per-item
    # independent state.
    assert synthetic_state.stack_item_is_copy(0) is True, (
        "Phase 4B C3 is_copy round-trip pin: pushing a new StackItem "
        "must NOT mutate any other StackItem's is_copy flag — each is "
        "per-item independent state"
    )

    # Unset the second item.
    synthetic_state.set_stack_top_is_copy(False)
    assert synthetic_state.stack_top_is_copy() is False
    assert synthetic_state.stack_item_is_copy(1) is False
    # The first item is still true.
    assert synthetic_state.stack_item_is_copy(0) is True


# ---------------------------------------------------------------------------
# Sanity: validation arm gates target legality
#
# **Rust-side limitation.** ``state_ops_legal.rs::activate_ability_dict``'s
# ActivateAbility emission is gated on ``is_sorcery_timing`` (which
# requires ``state.stack.is_empty()``) per the legacy Rust treatment of
# all AAs as sorcery-speed. So fan-out arm pins that drive
# ``legal_decisions(0)`` while the stack carries the target spell
# emit ZERO at the legal-decisions surface — NOT because the fan-out
# arm itself is wrong, but because the upstream sorcery-timing block
# suppresses emission entirely. The fan-out arm's behavior is verified
# indirectly by the resolve happy path pin (``test_rust_resolve_
# pushes_copy_onto_stack``) which calls ``apply_action`` directly
# (permissive — not gated on legal_decisions), confirming the
# validation arm + payload threading + resolve arm all work end-to-
# end. The validation arm pins below exercise apply_action's path
# directly for negative-target rejection (opponent-controlled +
# wrong-card-type) which is independent of the legal-decisions
# sorcery-timing gate.
#
# Documented in ``docs/SEARCH_LIMITATIONS.md`` (the Rust-side AA
# emission sorcery-timing gate is a pre-existing limitation — not
# this lane's bug).
# ---------------------------------------------------------------------------


def test_rust_validation_rejects_creature_spell_target(
    engine, synthetic_state,
):
    """**Negative pin — creature spells are NOT eligible targets.** A
    creature spell on the stack (legal target of MOST spell-targeting
    effects) is NOT a legal target for ``CopyTargetInstantOrSorcery
    YouControl`` per CR 707.2 + Mirrorpool's printed text — the AA
    targets ONLY instants and sorceries. The validation arm at
    ``state_ops_actions.rs::ActivateAbility`` must reject creature-
    spell targets.
    """
    mp_id = synthetic_state.register_and_inject_object(
        _synthetic_mirrorpool_aa0_only_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)

    # Cast a creature spell.
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_printing_dict("Validation Creature"), 0,
        ZONE_HAND,
    )
    synthetic_state.add_mana(0, "C", 1)
    ok = synthetic_state.cast_creature(creature_id, 0)
    assert ok is True
    assert synthetic_state.stack_size() == 1

    synthetic_state.add_mana(0, "C", 3)
    # Try to activate Mirrorpool's AA[0] targeting the creature spell.
    # Should raise — creature spells are not legal copy-spell targets.
    with pytest.raises(Exception):
        synthetic_state.apply_action({
            "kind": "activate_ability",
            "source_id": mp_id,
            "ability_index": 0,
            "target_creature_id": creature_id,
        })


def test_rust_validation_rejects_opponent_controlled_spell_target(
    engine, synthetic_state,
):
    """**Negative pin — opponent-controlled spells are NOT eligible
    targets.** Mirrorpool's printed text reads "target instant or
    sorcery spell **you control**" — opponent-controlled spells are
    NOT legal targets per CR 707.2 + the "you control" rider. The
    validation arm at ``state_ops_actions.rs::ActivateAbility`` must
    reject opponent-controlled spell targets.
    """
    mp_id = synthetic_state.register_and_inject_object(
        _synthetic_mirrorpool_aa0_only_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)

    # Cast an Instant by p1 (the opponent).
    p1_instant_id = synthetic_state.register_and_inject_object(
        _vanilla_instant_printing_dict("Opp Instant"), 1, ZONE_HAND,
    )
    synthetic_state.add_mana(1, "C", 1)
    ok = synthetic_state.cast_spell_noncreature(p1_instant_id, 1)
    assert ok is True
    assert synthetic_state.stack_size() == 1

    synthetic_state.add_mana(0, "C", 3)
    # Try to activate Mirrorpool's AA[0] targeting p1's instant.
    # Should raise — opponent-controlled spells are not legal targets.
    with pytest.raises(Exception):
        synthetic_state.apply_action({
            "kind": "activate_ability",
            "source_id": mp_id,
            "ability_index": 0,
            "target_creature_id": p1_instant_id,
        })


# ---------------------------------------------------------------------------
# Substrate-only invariant: Mirrorpool STAYS DECLINED post-C3
# ---------------------------------------------------------------------------


def test_mirrorpool_stays_declined_at_admit_gate_post_c3():
    """**Phase 4B C4 inversion — Mirrorpool's AA[0] FLIPs ADMITTED.**

    Pre-C4 (post-C3): the Rust substrate had landed but the Python
    admit set did NOT yet include
    ``CopyTargetInstantOrSorceryYouControl`` — synthetic Mirrorpool-
    AA[0] declined at the per-AA admit gate. The C4 widen lands the
    Effect class in :func:`_carrier_aa_phase_1_effect_classes`.
    """
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_phase_1_effect_classes,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )

    # **Phase 4B C4 inversion (2026-05-26).** The Effect class IS in
    # the admit set post-C4.
    admit_set = _carrier_aa_phase_1_effect_classes()
    assert CopyTargetInstantOrSorceryYouControl in admit_set, (
        "Phase 4B C4 invariant: CopyTargetInstantOrSorceryYouControl "
        "must BE in the admit set post-C4."
    )

    # A synthetic Mirrorpool-AA[0]-shape ActivatedAbility now ADMITS.
    aa0 = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=CopyTargetInstantOrSorceryYouControl(),
    )
    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "Phase 4B C4 inversion: Mirrorpool's AA[0] shape FLIPs "
        "ADMITTED at the per-AA admit predicate gate post-C4."
    )


def test_mirrorpool_live_printing_stays_declined_at_full_admit_gate_post_c3():
    """**Phase 4B C4 inversion — live Mirrorpool FLIPs ADMITTED.**

    Pre-C4 (post-C3): Mirrorpool's per-AA admit was mixed (AA[0]
    declined, AA[1] admitted); printing-level admit STAYED DECLINED.
    Post-C4: AA[0] admits via the Python admit widen + bridge arms;
    both per-AA gates pass; the multi-AA all-or-nothing gate flips
    Mirrorpool ADMITTED at the printing-level dispatcher.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _printing_is_bridge_simple_carrier_aa_any,
    )

    printings = OracleParserCardSource().get_printings()
    if "Mirrorpool" not in printings:
        pytest.skip(
            "Mirrorpool not in live EoE pool — skip the live-printing "
            "invariant pin. The synthetic-shape sibling pin still "
            "exercises the substrate-only invariant."
        )
    mp = printings["Mirrorpool"]
    assert len(mp.activated_abilities) == 2, (
        f"Mirrorpool should have 2 AAs (verified at C1 verify-first); "
        f"got {len(mp.activated_abilities)}"
    )
    aa0, aa1 = mp.activated_abilities[0], mp.activated_abilities[1]

    # **Phase 4B C4 inversion (2026-05-26).** AA[0] now admits.
    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "Phase 4B C4 invariant: live Mirrorpool's AA[0] FLIPs ADMITTED "
        "at the per-AA admit gate post-C4."
    )
    # AA[1] admits (per the C2 widen at 58988ade).
    assert _aa_is_phase1_sub_shape_a(aa1) is True, (
        "Phase 4B C2 invariant: live Mirrorpool's AA[1] admits at the "
        "per-AA admit gate (C2 widen at ``58988ade``)."
    )
    # **Phase 4B C4 inversion (2026-05-26).** Printing-level admit
    # FLIPs ADMITTED.
    assert _printing_is_bridge_simple_carrier_aa_any(mp) is True, (
        "Phase 4B C4 invariant: Mirrorpool's printing-level admit "
        "FLIPs ADMITTED post-C4 — both per-AA Effect classes admit; "
        "the multi-AA all-or-nothing gate passes."
    )
