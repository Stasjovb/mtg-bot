"""Combat primitives on the Rust ``GameState``.

Ported from ``src/mtg_bot/combat.py`` (the canonical Python combat module)
and the per-attacker/blocker scaffolding in ``tests/test_combat.py``.
The Python side spreads combat across hundreds of lines: predicate-style
event dispatch, first-strike/double-strike timing, trample, deathtouch,
lifelink, infect, prevention, exalted/vigilance, "whenever attacks"
triggers, etc. The Rust first slice carves off the irreducible primitives
needed to drive the round-5 end-to-end "attacker hits a blocker, both
might die" scenario — declare attackers, declare blockers, deal one round
of combat damage, clear combat state.

**Scope simplifications** (mirrored in the module docstring on
``rust/src/state_ops_combat.rs``):

- **No first-strike / double-strike / deathtouch / trample / lifelink
  / vigilance / infect / protection / unblockable.** Damage in this
  slice is one symmetric round: each attacker assigns ``power`` damage
  to its first blocker (or to the defending player if unblocked), and
  each blocker assigns ``power`` damage back to the attacker.
  Future combat slices peel off one keyword at a time.
- **No legality checks beyond "creature on attacker's battlefield,
  untapped, not summoning-sick".** Tapped creatures and summoning-sick
  creatures are rejected as attackers; that's the full attack-eligibility
  vocabulary today. Defender keyword, "can't attack" effects, attacked-
  alone restrictions are deferred.
- **Single-blocker damage assignment.** When multiple blockers are
  declared on the same attacker, the attacker assigns its full power
  to the FIRST declared blocker (the earliest entry in
  ``state.blockers`` matching the attacker_id). All declared blockers
  still deal their power back to the attacker. Trample / multi-blocker
  damage ordering (CR 510.1c) is the SBA-and-trample slice's job.
- **No "whenever attacks/blocks/deals combat damage" triggers.** Those
  fire through the predicate dispatcher in Python; the Rust engine has
  no event/trigger machinery yet.
- **No SBAs after damage.** Lethal-damage-removes-creature is CR 704.5h
  state-based action enforcement and lives in the SBA sibling slice.
  After ``deal_combat_damage``, dead creatures stay on the battlefield
  with ``damage >= toughness`` until an SBA pass runs.
- **Attackers stay tapped after ``clear_combat``.** Untapping is the
  untap-step's job (``state_ops_steps.rs:advance_phase`` / ``state_ops_
  tap.rs:untap_all_for_player``); ``clear_combat`` only zeroes the
  attacker / blocker Vecs.

Synthetic seed reminder (see ``make_synthetic_state`` in
``rust/src/state.rs``):

- Player 0 battlefield: ids 0..4 Forest (non-creature), 5..9 Grizzly
  Bears (2/2 creature).
- Player 0 hand: ids 10..16, all Llanowar Elves (1/1 creature, cost {G}).
- Player 1: same shape, ids start at 67. P1 battlefield: 67..71
  Forest, 72..76 Grizzly Bears.

The defending-player end-to-end test exercises the life slice through
the combat slice (``deal_combat_damage`` should subtract attacker.power
from defender.life via the same path ``lose_life`` uses).
"""

from __future__ import annotations

import pytest

# Synthetic state id layout (defaults: 10 battlefield, 7 hand, 50 library
# per side).
P0_FIRST_FOREST_ID = 0
P0_FIRST_BEAR_ID = 5  # battlefield slots 5..9 are Grizzly Bears (2/2)
P0_FIRST_HAND_ID = 10  # hand[0] is a Llanowar Elves
P1_FIRST_FOREST_ID = 67
P1_FIRST_BEAR_ID = 72  # p1 battlefield slots 72..76 are Grizzly Bears (2/2)


# ----------------------------- declare_attacker -----------------------------


def test_declare_attacker_records_id_and_taps(synthetic_state):
    """Declaring a creature as attacker pushes its id onto
    ``state.attackers`` (read via ``get_attackers``) and taps it.
    Mirrors the Python side's ``combat.declare_attackers`` — the
    no-vigilance default — which calls ``tap_permanent`` on each
    declared attacker."""
    bear_id = P0_FIRST_BEAR_ID
    assert synthetic_state.is_tapped(bear_id) is False
    assert synthetic_state.declare_attacker(bear_id) is True
    assert bear_id in synthetic_state.get_attackers()
    assert synthetic_state.is_tapped(bear_id) is True


def test_declare_attacker_returns_true_on_success(synthetic_state):
    """Successful declaration returns True. Distinguishes from the
    silent-no-op ``False`` paths (unknown id, non-creature, tapped,
    summoning-sick)."""
    assert synthetic_state.declare_attacker(P0_FIRST_BEAR_ID) is True


def test_declare_attacker_unknown_id_returns_false(synthetic_state):
    """Unknown id returns False without raising — same silent-no-op
    convention as ``tap_object`` and ``deal_damage``."""
    assert synthetic_state.declare_attacker(999_999) is False
    assert synthetic_state.get_attackers() == []


def test_declare_attacker_non_creature_returns_false(synthetic_state):
    """A Forest is not a creature (printing.power is None). Cannot
    attack. Returns False; nothing pushed onto attackers."""
    forest_id = P0_FIRST_FOREST_ID
    assert synthetic_state.declare_attacker(forest_id) is False
    assert synthetic_state.get_attackers() == []
    # And the forest must NOT have been tapped as a side effect of the
    # rejected declaration.
    assert synthetic_state.is_tapped(forest_id) is False


def test_declare_attacker_already_tapped_returns_false(synthetic_state):
    """A tapped creature can't be declared as attacker (CR 508.1a —
    "the creature is tapped" disqualifies it). Returns False; no
    duplicate entry on attackers."""
    bear_id = P0_FIRST_BEAR_ID
    assert synthetic_state.tap_object(bear_id) is True
    assert synthetic_state.declare_attacker(bear_id) is False
    assert synthetic_state.get_attackers() == []


def test_declare_attacker_summoning_sick_returns_false(synthetic_state):
    """A creature with summoning sickness can't attack (CR 302.1).
    Cast a fresh elf (which stamps summoning_sick=True per
    ``state_ops_cast.rs``) and try to attack with it."""
    # Need {G} to cast Llanowar Elves.
    synthetic_state.add_mana(0, "G", 1)
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.cast_creature(elf_id, 0) is True
    # Sanity check: the just-cast creature is summoning sick.
    assert synthetic_state.is_summoning_sick(elf_id) is True
    # Now try to attack with it — should be refused.
    assert synthetic_state.declare_attacker(elf_id) is False
    assert synthetic_state.get_attackers() == []
    # The summoning-sick rejection must NOT have tapped it as a side
    # effect.
    assert synthetic_state.is_tapped(elf_id) is False


def test_declare_attacker_get_attackers(synthetic_state):
    """``get_attackers`` returns the list of declared attacker ids in
    declaration order. Two bears declared in sequence yield a 2-element
    list with both ids."""
    bear_a = P0_FIRST_BEAR_ID
    bear_b = P0_FIRST_BEAR_ID + 1
    assert synthetic_state.declare_attacker(bear_a) is True
    assert synthetic_state.declare_attacker(bear_b) is True
    attackers = synthetic_state.get_attackers()
    assert attackers == [bear_a, bear_b]


# ----------------------------- declare_blocker ------------------------------


def test_declare_blocker_records_pair(synthetic_state):
    """``declare_blocker(blocker_id, attacker_id)`` appends an
    ``(attacker_id, blocker_id)`` pair to ``state.blockers`` (read
    via ``get_blockers``). The blocker is NOT tapped — blocking
    doesn't tap (CR 509.1)."""
    attacker = P0_FIRST_BEAR_ID
    blocker = P1_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(blocker, attacker) is True
    assert (attacker, blocker) in synthetic_state.get_blockers()
    # Blocking doesn't tap the blocker.
    assert synthetic_state.is_tapped(blocker) is False


def test_declare_blocker_unknown_attacker_returns_false(synthetic_state):
    """Blocker references an attacker id not in ``state.attackers``
    (no creature has been declared as attacker, or the id never
    existed). Returns False; nothing pushed."""
    blocker = P1_FIRST_BEAR_ID
    assert synthetic_state.declare_blocker(blocker, 999_999) is False
    assert synthetic_state.get_blockers() == []


def test_declare_blocker_unknown_blocker_returns_false(synthetic_state):
    """Blocker id doesn't exist anywhere. Returns False even when the
    attacker id is valid."""
    attacker = P0_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(999_999, attacker) is False
    assert synthetic_state.get_blockers() == []


def test_declare_blocker_non_creature_returns_false(synthetic_state):
    """A Forest can't block (not a creature). The attacker exists, the
    blocker id resolves, but the blocker fails the creature predicate."""
    attacker = P0_FIRST_BEAR_ID
    forest_blocker = P1_FIRST_FOREST_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(forest_blocker, attacker) is False
    assert synthetic_state.get_blockers() == []


def test_declare_blocker_tapped_creature_returns_false(synthetic_state):
    """A tapped creature can't block (CR 509.1b). Returns False."""
    attacker = P0_FIRST_BEAR_ID
    blocker = P1_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.tap_object(blocker) is True
    assert synthetic_state.declare_blocker(blocker, attacker) is False
    assert synthetic_state.get_blockers() == []


def test_declare_blocker_attacker_not_in_attackers_returns_false(synthetic_state):
    """Even when ``attacker_id`` resolves to a real battlefield
    creature, if it has not been declared as attacker (not in
    ``state.attackers``), the block is refused. The "attacker_id"
    param is checked against the attackers Vec, not the battlefield."""
    bear = P0_FIRST_BEAR_ID  # exists, but never declared as attacker
    blocker = P1_FIRST_BEAR_ID
    assert bear not in synthetic_state.get_attackers()
    assert synthetic_state.declare_blocker(blocker, bear) is False
    assert synthetic_state.get_blockers() == []


# ----------------------------- combat damage --------------------------------


def test_unblocked_attacker_damages_defending_player(synthetic_state):
    """End-to-end: declare a 2/2 bear as attacker, no blocker,
    ``deal_combat_damage`` subtracts 2 from the defending player's
    life. Exercises the cross-slice composition between combat and
    life — the same code path ``lose_life`` uses to decrement
    ``players[idx].life``."""
    attacker = P0_FIRST_BEAR_ID  # 2/2
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker) is True
    synthetic_state.deal_combat_damage()
    # Defending player (p1, the non-active one) loses 2 life.
    assert synthetic_state.get_life(1) == 18
    # Active player's life unchanged.
    assert synthetic_state.get_life(0) == 20


def test_blocked_attacker_damages_blocker_not_player(synthetic_state):
    """Attacker is blocked. Defending player life unchanged; the
    blocker has the attacker's power marked as damage."""
    attacker = P0_FIRST_BEAR_ID  # 2/2
    blocker = P1_FIRST_BEAR_ID  # 2/2
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(blocker, attacker) is True
    synthetic_state.deal_combat_damage()
    # Defending player untouched.
    assert synthetic_state.get_life(1) == 20
    # Blocker took 2 damage (attacker power).
    assert synthetic_state.get_damage(blocker) == 2


def test_blocker_damages_attacker(synthetic_state):
    """Symmetric back-damage: the blocker assigns its power to the
    attacker as well. With two 2/2 bears trading, both take 2 damage.
    (Once SBAs land, both die.)"""
    attacker = P0_FIRST_BEAR_ID  # 2/2
    blocker = P1_FIRST_BEAR_ID  # 2/2
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(blocker, attacker) is True
    synthetic_state.deal_combat_damage()
    # Attacker takes blocker's power (2) — the back-damage half of the
    # symmetric exchange.
    assert synthetic_state.get_damage(attacker) == 2
    # Blocker also took 2.
    assert synthetic_state.get_damage(blocker) == 2


# ----------------------------- clear_combat ---------------------------------


def test_clear_combat_empties_attackers_and_blockers(synthetic_state):
    """After ``clear_combat``, both ``attackers`` and ``blockers`` are
    empty. Mirrors Python's ``combat.clear_combat_state`` — the
    end-of-combat zeroing of per-combat scaffolding."""
    attacker = P0_FIRST_BEAR_ID
    blocker = P1_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.declare_blocker(blocker, attacker) is True
    assert synthetic_state.get_attackers() != []
    assert synthetic_state.get_blockers() != []
    synthetic_state.clear_combat()
    assert synthetic_state.get_attackers() == []
    assert synthetic_state.get_blockers() == []


def test_clear_combat_does_not_untap_attackers(synthetic_state):
    """Untapping declared attackers is the untap-step's job (CR 502.1).
    ``clear_combat`` is end-of-combat cleanup; the attacker stays
    tapped through end-of-combat / end step / cleanup, then untaps
    next turn's untap step."""
    attacker = P0_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(attacker) is True
    assert synthetic_state.is_tapped(attacker) is True
    synthetic_state.clear_combat()
    # Still tapped.
    assert synthetic_state.is_tapped(attacker) is True


# ----------------------------- CoW canaries ---------------------------------


def test_clone_then_declare_attacker_does_not_affect_original(synthetic_state):
    """**CoW canary.** Cloning the state and declaring an attacker on
    the clone must not mutate the original's ``attackers`` Vec or its
    battlefield (the attacker should be tapped on the clone only).
    Same load-bearing invariant as the per-zone CoW canaries in
    ``test_tap.py`` and ``test_damage.py``."""
    bear_id = P0_FIRST_BEAR_ID
    other = synthetic_state.clone_once()
    assert synthetic_state.get_attackers() == []
    assert other.get_attackers() == []
    # Declare on the clone only.
    assert other.declare_attacker(bear_id) is True
    assert other.get_attackers() == [bear_id]
    assert other.is_tapped(bear_id) is True
    # Original must NOT see either side of the change.
    assert synthetic_state.get_attackers() == [], (
        "CoW broken: declaring attacker on clone leaked into original "
        "attackers Vec"
    )
    assert synthetic_state.is_tapped(bear_id) is False, (
        "CoW broken: declaring attacker on clone leaked into original "
        "battlefield (the bear was tapped on the original)"
    )


def test_clone_then_combat_damage_does_not_affect_original(synthetic_state):
    """**CoW canary.** The clone runs a full combat exchange — declare
    attacker, declare blocker, deal damage — and the original observes
    none of it: no attackers, no blockers, no damage on either bear,
    no life change on the defending player."""
    attacker = P0_FIRST_BEAR_ID
    blocker = P1_FIRST_BEAR_ID
    other = synthetic_state.clone_once()
    # Run combat on the clone only.
    assert other.declare_attacker(attacker) is True
    assert other.declare_blocker(blocker, attacker) is True
    other.deal_combat_damage()
    assert other.get_damage(attacker) == 2
    assert other.get_damage(blocker) == 2
    # Original sees no fallout.
    assert synthetic_state.get_attackers() == []
    assert synthetic_state.get_blockers() == []
    assert synthetic_state.get_damage(attacker) == 0, (
        "CoW broken: combat damage on clone leaked into original"
    )
    assert synthetic_state.get_damage(blocker) == 0, (
        "CoW broken: combat damage on clone leaked into original"
    )
    assert synthetic_state.get_life(1) == 20
    # And the attacker on the original is untapped.
    assert synthetic_state.is_tapped(attacker) is False


# ----------------------------- vigilance ------------------------------------
#
# Vigilance (CR 702.20): an attacking creature with vigilance doesn't tap
# when it attacks. It must still be untapped to attack, and vigilance does
# not grant haste — summoning-sick vigilance creatures still can't attack.
#
# These tests use the cross-slice fixture
# ``register_and_inject_object(printing_dict, controller, zone)`` from
# ``state_ops_resolve.rs`` to inject a printing with
# ``keywords=["vigilance"]`` onto player 0's battlefield, then exercise
# the four combinations: vigilant + ok, non-vigilant + ok (sanity),
# vigilant + tapped (still rejected), vigilant + summoning-sick (still
# rejected).

ZONE_BATTLEFIELD = 2  # mirrors rust/src/state_ops_zones.rs


def _vigilance_bear_dict():
    """A 2/2 creature printing carrying just the ``vigilance`` keyword.
    Shaped to land on the battlefield as an already-resolved permanent
    (the test harness uses ``register_and_inject_object`` with
    ZONE_BATTLEFIELD)."""
    return {
        "name": "Test Vigilance Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "keywords": ["vigilance"],
        "effects": [],
    }


def test_vigilance_creature_does_not_tap_when_attacking(synthetic_state):
    """A vigilance creature declared as attacker is recorded on
    ``state.attackers`` (so combat damage and triggers see it) but its
    ``tapped`` flag stays False — the load-bearing distinction from the
    no-keyword path."""
    obj_id = synthetic_state.register_and_inject_object(
        _vigilance_bear_dict(), 0, ZONE_BATTLEFIELD
    )
    # Synthetic state defaults summoning_sick=False on injected objects;
    # confirm starting conditions before we declare.
    assert synthetic_state.is_tapped(obj_id) is False
    assert synthetic_state.is_summoning_sick(obj_id) is False
    assert synthetic_state.declare_attacker(obj_id) is True
    # Recorded as attacker.
    assert obj_id in synthetic_state.get_attackers()
    # Did NOT tap — that's vigilance.
    assert synthetic_state.is_tapped(obj_id) is False


def test_non_vigilance_creature_taps_when_attacking(synthetic_state):
    """Sanity / regression: keyword-less Grizzly Bears still taps when
    attacking. The vigilance branch must not have leaked into the
    default path."""
    bear_id = P0_FIRST_BEAR_ID  # Grizzly Bears, no keywords
    assert synthetic_state.declare_attacker(bear_id) is True
    assert bear_id in synthetic_state.get_attackers()
    # Non-vigilance: tapped on attack.
    assert synthetic_state.is_tapped(bear_id) is True


def test_vigilance_creature_already_tapped_still_returns_false(synthetic_state):
    """Vigilance prevents the tap-on-attack but does NOT bypass the
    "must be untapped to attack" precondition (CR 508.1a). Pre-tapping
    the vigilance creature and then trying to declare it as attacker
    should still be refused."""
    obj_id = synthetic_state.register_and_inject_object(
        _vigilance_bear_dict(), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.tap_object(obj_id) is True
    assert synthetic_state.is_tapped(obj_id) is True
    # Declaration refused — already tapped.
    assert synthetic_state.declare_attacker(obj_id) is False
    assert synthetic_state.get_attackers() == []


def test_vigilance_summoning_sick_still_returns_false(synthetic_state):
    """Vigilance does not grant haste. A summoning-sick vigilance
    creature still can't attack (CR 302.1).

    Build a vigilance creature on player 0's battlefield as
    summoning-sick (the synthetic-injection fixture defaults
    summoning_sick=False, so we cast a fresh creature instead — but
    cast_creature targets the registered Llanowar Elves, not vigilance.
    Instead, we register the printing in HAND, then cast it: the
    cast-flow stamps summoning_sick=True. Since cast_creature only
    works on creatures with mana_cost the seed knows how to pay, we
    manually inject onto battlefield and then flip summoning_sick via
    end_turn / new turn — but that's heavy. Pragmatic: inject onto
    battlefield, verify summoning_sick=False (synthetic injects with
    summoning_sick=False), THEN exercise the cast path with a
    vigilance printing.

    Simpler still: cast a vigilance creature from hand (the cast slice
    stamps summoning_sick=True) and try to attack with it.
    """
    # Inject the vigilance printing into player 0's HAND, give them
    # the mana to cast it, cast it, then try to attack with the
    # freshly-cast (summoning-sick) creature.
    ZONE_HAND = 0
    obj_id = synthetic_state.register_and_inject_object(
        _vigilance_bear_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)  # cover the {1} generic
    assert synthetic_state.cast_creature(obj_id, 0) is True
    # Just-cast: summoning sick.
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # Vigilance does not grant haste.
    assert synthetic_state.declare_attacker(obj_id) is False
    assert synthetic_state.get_attackers() == []
    # And the rejection didn't tap it as a side effect.
    assert synthetic_state.is_tapped(obj_id) is False


# ----------------------------- deathtouch + lifelink ------------------------
#
# Deathtouch (CR 702.2): any nonzero amount of combat damage from a
# creature with deathtouch is enough to mark lethal damage on a creature.
# Implementation: after the regular `damage += power` add, upgrade the
# recipient's `damage` to at least its toughness so the round-5 SBA pass
# (`apply_sbas`) destroys it.
#
# Lifelink (CR 702.15): damage dealt by a creature with lifelink also
# causes its controller to gain that much life. This first slice fires
# only on combat damage (the only damage source visible inside
# `deal_combat_damage`); other damage sources will gain the same hook
# when they grow up.
#
# Scope simplifications mirrored from the module docstring on
# `state_ops_combat.rs`:
#
# - Deathtouch requires NONZERO damage (CR 702.2b "any nonzero amount").
#   A 0-power deathtouch creature does not mark lethal.
# - First-strike / double-strike are still out of scope; combat damage
#   is one symmetric step.
# - "Damage isn't dealt" replacement effects (protection, prevention)
#   are out of scope, so deathtouch / lifelink fire whenever the
#   regular path would have dealt damage.
# - These tests use the same `register_and_inject_object` injection
#   path the vigilance tests above already exercise.


def _keyword_creature_dict(power, toughness, keywords):
    """A creature printing with the given P/T and keyword list. The
    name varies by keyword so multiple injections can coexist; the
    cost shape ({G}+{1}) is identical to ``_vigilance_bear_dict`` so
    the cast-creature path keeps working when a test wants to cast
    one of these (none of the deathtouch/lifelink tests below need
    to cast — they all inject directly to battlefield)."""
    return {
        "name": "Test " + "+".join(keywords) + f" {power}/{toughness}",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": power,
        "toughness": toughness,
        "keywords": list(keywords),
        "effects": [],
    }


def test_deathtouch_attacker_marks_lethal_on_blocker_with_more_toughness(synthetic_state):
    """A 1/1 deathtouch attacker fights a 3/3 blocker. The regular
    add gives the blocker 1 damage; deathtouch upgrades that to its
    full toughness (3) so the round-5 SBA pass would destroy it."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["deathtouch"]), 0, ZONE_BATTLEFIELD
    )
    # Use a Grizzly Bears slot from p1's battlefield as the blocker —
    # but the synthetic Bears are 2/2. Inject a 3/3 vanilla blocker
    # for an unambiguous toughness mismatch.
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgraded the 1 damage to >= 3 (the blocker's toughness).
    assert synthetic_state.get_damage(blocker_id) >= 3, (
        "deathtouch must mark damage to AT LEAST the recipient's toughness "
        "(CR 702.2b)"
    )


def test_deathtouch_blocker_marks_lethal_on_attacker_with_more_toughness(synthetic_state):
    """Symmetric: a 1/1 deathtouch blocker upgrades its hit on a 3/3
    attacker to lethal."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["deathtouch"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    assert synthetic_state.get_damage(attacker_id) >= 3, (
        "deathtouch on the blocker must upgrade attacker damage to lethal"
    )


def test_deathtouch_with_zero_power_does_not_mark_lethal(synthetic_state):
    """CR 702.2b — deathtouch fires on any NONZERO amount of damage.
    A 0/1 deathtouch creature deals 0 damage, so deathtouch does not
    fire and the recipient's damage stays at 0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 1, ["deathtouch"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # No damage dealt at all (attacker is 0 power); deathtouch must
    # NOT fire because it requires nonzero damage to be dealt.
    assert synthetic_state.get_damage(blocker_id) == 0, (
        "deathtouch must NOT mark lethal when the source dealt 0 damage "
        "(CR 702.2b — requires nonzero damage)"
    )


def test_lifelink_attacker_unblocked_gains_life_for_controller(synthetic_state):
    """A 3/3 lifelink attacker, no blocker. The defending player
    takes 3 damage (the existing unblocked path) AND the attacker's
    controller gains 3 life."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["lifelink"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Defending player took 3.
    assert synthetic_state.get_life(1) == 17
    # Attacker's controller gained 3 from lifelink.
    assert synthetic_state.get_life(0) == 23, (
        "lifelink must gain life on the controller equal to combat damage dealt"
    )


def test_lifelink_attacker_blocked_gains_life_for_damage_dealt_to_blocker(synthetic_state):
    """A 2/2 lifelink attacker is blocked by a 3/3. The blocker
    takes 2 damage; the attacker's controller gains 2 life."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["lifelink"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Defending player untouched (attacker was blocked).
    assert synthetic_state.get_life(1) == 20
    # Blocker took 2 damage.
    assert synthetic_state.get_damage(blocker_id) == 2
    # Lifelink fired — attacker controller gained 2.
    assert synthetic_state.get_life(0) == 22, (
        "lifelink must gain life equal to damage dealt to the blocker"
    )


def test_lifelink_blocker_gains_life_for_damage_dealt_to_attacker(synthetic_state):
    """A 2/2 attacker meets a 3/3 lifelink blocker. The blocker
    deals 3 damage to the attacker; the blocker's controller gains
    3 life."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["lifelink"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Attacker took 3 damage.
    assert synthetic_state.get_damage(attacker_id) == 3
    # Lifelink on the blocker — blocker's controller (player 1) gained 3.
    assert synthetic_state.get_life(1) == 23, (
        "lifelink on the blocker must gain life on the blocker's controller"
    )


def test_attacker_without_keywords_does_not_gain_life_or_mark_lethal(synthetic_state):
    """Sanity / regression: a vanilla 2/2 attacker vs vanilla 3/3
    blocker leaves the existing path untouched. No life gain on
    either side, blocker damage stays at the literal added power
    (2), no lethal upgrade."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took attacker's literal power (2), not its toughness (3) —
    # no deathtouch upgrade.
    assert synthetic_state.get_damage(blocker_id) == 2
    # No life change on either side — no lifelink in play.
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20


def test_deathtouch_and_lifelink_compose(synthetic_state):
    """A 1/1 with BOTH deathtouch and lifelink against a 3/3 blocker.
    Deathtouch upgrades the 1-damage hit to lethal (>= 3); lifelink
    fires on the literal damage dealt (1) so the attacker's
    controller gains 1 life. Lifelink fires on the actual amount,
    not the upgraded mark — see CR 702.2c (deathtouch only changes
    how damage is treated for lethality, not the dealt amount that
    other rules read)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["deathtouch", "lifelink"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgraded the blocker's marked damage to lethal.
    assert synthetic_state.get_damage(blocker_id) >= 3, (
        "composed: deathtouch must still mark lethal even with lifelink in play"
    )
    # Lifelink fired on the actual damage (1).
    assert synthetic_state.get_life(0) == 21, (
        "composed: lifelink fires on the literal damage dealt (1), not on "
        "deathtouch's upgraded mark"
    )


# ----------------------------- trample -------------------------------------
#
# Trample (CR 702.19): an attacking creature with trample can assign damage
# in excess of what's needed to deal lethal damage to all of its blockers
# to the defending player (or planeswalker). The first slice models this
# only for the single-blocker case the round-5 combat slice already
# supports: with one blocker, trample assigns
# `max(attacker.power - blocker.toughness, 0)` to the defending player.
#
# Multi-blocker assignment ordering / damage distribution remains deferred
# (the round-5 combat slice itself only ever applies attacker.power to
# the FIRST declared blocker; a "spread across blockers" damage model is
# the SBA-and-trample slice's job).
#
# Trample does NOT affect the unblocked path — an unblocked attacker
# already deals all of its power to the defending player; the trample
# branch must not double-count.


def test_trample_unblocked_no_excess_to_defender(synthetic_state):
    """A trample 3/3 attacker, no blocker. The defender takes 3 (the
    existing unblocked path) and the trample branch does NOT
    double-count: defender life lost is exactly 3, not 6."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["trample"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Defender lost exactly 3 — trample doesn't add a second helping
    # of damage when the attacker is unblocked.
    assert synthetic_state.get_life(1) == 17, (
        "trample on an unblocked attacker must not double-count: defender "
        "loses attacker.power (3), not 6"
    )


def test_trample_blocked_excess_goes_to_defender(synthetic_state):
    """Trample 5/5 attacker vs 2/2 blocker. The blocker takes 2
    (lethal); the 3-point excess (5 - 2) goes through to the defending
    player."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, ["trample"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took at least its toughness (2) — the regular hit.
    assert synthetic_state.get_damage(blocker_id) == 2
    # Defender took the trample excess: 5 - 2 = 3.
    assert synthetic_state.get_life(1) == 17, (
        "trample excess (attacker.power - blocker.toughness = 5 - 2 = 3) "
        "must go to the defending player"
    )


def test_trample_blocked_no_excess_when_attacker_smaller_than_blocker_toughness(synthetic_state):
    """Trample 2/2 attacker vs 4/4 blocker. The blocker takes 2 (the
    full damage), no excess goes through (since attacker.power
    < blocker.toughness)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["trample"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    assert synthetic_state.get_damage(blocker_id) == 2
    # No trample excess — defender life unchanged.
    assert synthetic_state.get_life(1) == 20, (
        "no trample excess when attacker.power <= blocker.toughness: "
        "defender life must stay at 20"
    )


def test_trample_blocked_exact_lethal_no_excess(synthetic_state):
    """Trample 3/3 attacker vs 3/3 blocker. Exact lethal — no excess.
    The blocker takes 3, defender takes 0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["trample"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    assert synthetic_state.get_damage(blocker_id) == 3
    assert synthetic_state.get_life(1) == 20, (
        "exact-lethal trample (attacker.power == blocker.toughness) leaves "
        "no excess for the defender"
    )


# ----------------------------- trample + deathtouch ------------------------
#
# CR 702.19c: a creature with both trample and deathtouch only has to
# assign 1 damage to each blocker before assigning the rest as trample.
# The composition: deathtouch (CR 702.2) treats any nonzero damage as
# lethal, so trample's "must assign at least lethal to blockers" rule
# (CR 702.19b) is satisfied at 1 damage per blocker. The remainder
# tramples through to the defender.
#
# Pinned behavior:
# - trample+deathtouch: blocker absorbs min(power, 1), the rest goes to
#   the defending player.
# - trample only (no deathtouch): blocker absorbs min(power, toughness)
#   — pins the existing round-9 behavior.
# - deathtouch only (no trample): no trample-through to the defender;
#   damage is the symmetric mutual exchange with deathtouch lethal-mark
#   upgrade — pins the existing round-8 behavior.


def test_trample_deathtouch_4_4_vs_3_3_blocker_one_to_blocker_three_to_defender(
    synthetic_state,
):
    """A 4/4 with trample+deathtouch attacks a 3/3 blocker. Deathtouch
    makes 1 damage lethal, so trample's "lethal to blockers" floor is
    1. The blocker takes 1 (deathtouch upgrades the mark to its
    toughness for SBA cleanup), and the remaining 3 tramples through
    to the defending player (life 20 → 17). CR 702.19c."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, ["trample", "deathtouch"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgrades the blocker's marked damage to lethal (>= 3).
    assert synthetic_state.get_damage(blocker_id) >= 3, (
        "trample+deathtouch: blocker still takes lethal (deathtouch "
        "upgrades the 1-damage mark to its toughness)"
    )
    # Remaining 3 (= 4 - 1) tramples through to the defender.
    assert synthetic_state.get_life(1) == 17, (
        "trample+deathtouch (CR 702.19c): only 1 damage required to "
        "satisfy the trample 'lethal to blocker' floor; the rest "
        "(power - 1 = 3) goes to the defending player"
    )


def test_trample_deathtouch_4_4_vs_5_5_blocker_one_to_blocker_three_to_defender(
    synthetic_state,
):
    """A 4/4 with trample+deathtouch attacks a 5/5 blocker. Without
    deathtouch, trample would cap blocker damage at 4 (= attacker.power
    < blocker.toughness, no excess). With deathtouch, the cap drops to
    1 — the blocker takes 1 (deathtouch upgrades to lethal=5), and
    3 tramples to the defender (life 20 → 17)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, ["trample", "deathtouch"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgrades the blocker's marked damage to lethal (>= 5).
    assert synthetic_state.get_damage(blocker_id) >= 5, (
        "trample+deathtouch vs higher-toughness blocker: deathtouch "
        "still upgrades to lethal"
    )
    # Remaining 3 (= 4 - 1) tramples through.
    assert synthetic_state.get_life(1) == 17, (
        "trample+deathtouch vs higher-toughness blocker: cap drops to 1, "
        "so power - 1 = 3 tramples through"
    )


def test_trample_only_4_4_vs_3_3_blocker_pins_existing_round9_behavior(
    synthetic_state,
):
    """Pin the existing round-9 trample-only behavior: a 4/4 trample
    attacker (no deathtouch) vs 3/3 blocker assigns 3 to the blocker
    (lethal at toughness=3) and 1 trample-through to the defender."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, ["trample"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Round-9 cap = blocker.toughness, so 3 to blocker.
    assert synthetic_state.get_damage(blocker_id) == 3, (
        "trample-only (no deathtouch): cap stays at blocker.toughness=3"
    )
    # Excess = 4 - 3 = 1.
    assert synthetic_state.get_life(1) == 19, (
        "trample-only (no deathtouch): excess = power - toughness = 1"
    )


def test_deathtouch_only_4_4_vs_5_5_blocker_pins_existing_round8_behavior(
    synthetic_state,
):
    """Pin the existing round-8 deathtouch-only behavior: a 4/4
    deathtouch attacker (no trample) vs 5/5 blocker. Mutual damage:
    blocker takes 4, deathtouch upgrades to lethal=5 (dies); attacker
    takes 5 (also dies). Defender life unchanged — no trample-through
    without trample."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, ["deathtouch"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgraded the blocker's mark to lethal.
    assert synthetic_state.get_damage(blocker_id) >= 5, (
        "deathtouch-only: blocker mark is upgraded to lethal"
    )
    # Attacker took the symmetric 5-damage hit.
    assert synthetic_state.get_damage(attacker_id) == 5
    # No trample without the trample keyword — defender life unchanged.
    assert synthetic_state.get_life(1) == 20, (
        "deathtouch-only (no trample): no trample-through to defender"
    )


def test_trample_deathtouch_1_1_vs_3_3_blocker_no_trample_excess(
    synthetic_state,
):
    """Edge case: a 1/1 with trample+deathtouch vs 3/3 blocker.
    Cap drops to 1 (deathtouch); blocker takes 1 (upgraded to lethal);
    no trample excess (1 - 1 = 0). Defender life unchanged."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["trample", "deathtouch"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker mark upgraded to lethal.
    assert synthetic_state.get_damage(blocker_id) >= 3, (
        "trample+deathtouch 1/1: blocker takes 1 damage, deathtouch "
        "upgrades to lethal"
    )
    # power - cap = 1 - 1 = 0; no trample excess.
    assert synthetic_state.get_life(1) == 20, (
        "trample+deathtouch 1/1: no trample excess (power == cap == 1)"
    )


def test_trample_deathtouch_exact_one_power_no_excess(synthetic_state):
    """A 1/1 with trample+deathtouch vs a 1/1 blocker. Cap = 1;
    blocker takes 1 (deathtouch lethal); excess = 1 - 1 = 0.
    Mutual destruction with no trample-through."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["trample", "deathtouch"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 1 (already lethal at toughness=1).
    assert synthetic_state.get_damage(blocker_id) >= 1
    # No trample excess.
    assert synthetic_state.get_life(1) == 20, (
        "trample+deathtouch 1/1 vs 1/1: cap == power, no trample-through"
    )


# ----------------------------- first-strike --------------------------------
#
# First-strike (CR 702.7): a creature with first strike deals combat damage
# in a separate, earlier sub-step (the first-strike damage step). For this
# slice, `deal_combat_damage` runs in two passes when ANY participant has
# first-strike:
#
# 1. **First-strike damage step.** Only first-strike creatures deal damage.
#    After applying their damage, anyone whose marked `damage` >=
#    `printed toughness` is considered "dead" for the regular damage step
#    (we don't have an SBA-fire here yet — it's a within-function check).
# 2. **Regular damage step.** Only NON-first-strike creatures still alive
#    AND first-strike creatures still alive (the latter wouldn't have hit
#    anything new in the regular step in real MTG either, but they don't
#    deal damage in this step because they already did it; we partition
#    into "first-strike sources" vs "rest" and run the rest now).
#
# Trample fires inside whichever pass applies the damage.
#
# **No double-strike** in this slice (a double-strike creature deals
# damage in BOTH steps). Deferred.


def test_first_strike_attacker_kills_blocker_before_blocker_strikes_back(synthetic_state):
    """A first-strike 2/2 attacker vs vanilla 2/2 blocker. The blocker
    takes 2 in the first-strike step, dies before regular damage, so
    the attacker takes 0 damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 2 (lethal) in the first-strike step.
    assert synthetic_state.get_damage(blocker_id) == 2
    # Attacker took 0 — blocker died before regular damage.
    assert synthetic_state.get_damage(attacker_id) == 0, (
        "first-strike attacker must kill blocker before blocker can strike "
        "back; attacker damage should be 0"
    )


def test_first_strike_blocker_kills_attacker_before_attacker_strikes_back(synthetic_state):
    """Symmetric: vanilla 2/2 attacker vs first-strike 2/2 blocker.
    Attacker takes 2 in first-strike step, dies before regular damage,
    so the blocker takes 0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Attacker took 2 (lethal) in the first-strike step.
    assert synthetic_state.get_damage(attacker_id) == 2
    # Blocker took 0 — attacker died before regular damage.
    assert synthetic_state.get_damage(blocker_id) == 0, (
        "first-strike blocker must kill attacker before attacker can strike "
        "back; blocker damage should be 0"
    )


def test_both_first_strike_simultaneous_first_strike_step(synthetic_state):
    """Both attacker and blocker have first-strike. They deal damage
    simultaneously in the first-strike step; neither deals damage in
    the regular step. Both 2/2s end up with 2 damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Both took 2 in the first-strike step (simultaneous).
    assert synthetic_state.get_damage(attacker_id) == 2, (
        "both-first-strike: both creatures deal damage in the first-strike "
        "step simultaneously"
    )
    assert synthetic_state.get_damage(blocker_id) == 2, (
        "both-first-strike: both creatures deal damage in the first-strike "
        "step simultaneously"
    )


def test_neither_first_strike_uses_single_step(synthetic_state):
    """Sanity / regression: keyword-less 2/2 vs keyword-less 2/2 still
    produces the round-5 mutual-damage exchange. The first-strike
    branch must not have leaked into the default path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Mutual damage — both take 2.
    assert synthetic_state.get_damage(attacker_id) == 2
    assert synthetic_state.get_damage(blocker_id) == 2


def test_first_strike_does_not_skip_lifelink(synthetic_state):
    """A 3/3 attacker with BOTH first-strike and lifelink vs a vanilla
    2/2 blocker. The attacker deals 3 to the blocker in the
    first-strike step (overkill), the blocker dies, the attacker takes
    0 in the regular step. Lifelink fires on the 3 damage dealt — the
    attacker's controller gains 3 life."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["first_strike", "lifelink"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 3 in first-strike step.
    assert synthetic_state.get_damage(blocker_id) == 3
    # Attacker took 0 — blocker died before regular damage.
    assert synthetic_state.get_damage(attacker_id) == 0, (
        "first-strike + lifelink composition: blocker died before regular "
        "damage; attacker takes 0"
    )
    # Lifelink fired on the 3 damage dealt — controller gained 3.
    assert synthetic_state.get_life(0) == 23, (
        "first-strike + lifelink composition: lifelink must still gain life "
        "for the damage dealt in the first-strike step"
    )


# ----------------------------- haste ---------------------------------------
#
# Haste (CR 702.10): a creature with haste ignores the summoning-sickness
# restriction. Specifically, the "creature has been continuously controlled
# by you since your most recent turn began" precondition for attacking
# (CR 302.1) and for activating tap- / untap-cost abilities is bypassed.
# A haste creature CAN attack the turn it enters the battlefield.
#
# Implementation hook in `state_ops_combat.rs:declare_attacker`: today the
# rejection is `if tapped || summoning_sick { return false; }`. This slice
# changes that to `if tapped || (summoning_sick && !has_haste)`, where
# `has_haste = battlefield_has_keyword(state, obj_id, "haste")`.
#
# Scope simplifications (mirrored from the module docstring on
# `state_ops_combat.rs`):
#
# - Haste does NOT change the "must be untapped to attack" precondition
#   (CR 508.1a — a tapped creature can't attack regardless). Pre-tapped
#   haste creatures are still rejected.
# - Haste does NOT skip the tap-on-attack step. A haste creature without
#   vigilance still taps when declared as attacker. Composition with
#   vigilance (haste + vigilance: attack on first turn AND don't tap)
#   is exercised by `test_haste_plus_vigilance_does_not_tap`.
# - Haste also affects activated tap-abilities (CR 302.1 covers both
#   attacking and tapping for an ability). This slice only models the
#   attacking half because `declare_attacker` is the only summoning-sick
#   gate today; an activated-abilities slice will pick up the second half.


def test_haste_creature_can_attack_when_summoning_sick(synthetic_state):
    """A freshly-cast haste creature (summoning_sick=True) can be
    declared as attacker — CR 702.10 bypasses the summoning-sickness
    rejection in `declare_attacker`."""
    # Cast the haste creature from hand so the cast-flow stamps
    # summoning_sick=True (mirrors the vigilance summoning-sick test
    # pattern). Mana cost {G}+{1} — same shape as the other keyword
    # printings.
    ZONE_HAND = 0
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["haste"]), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)  # cover the {1} generic
    assert synthetic_state.cast_creature(obj_id, 0) is True
    # Just-cast: summoning sick.
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # Haste lets it attack despite summoning sickness.
    assert synthetic_state.declare_attacker(obj_id) is True, (
        "haste must let a summoning-sick creature attack (CR 702.10)"
    )
    assert obj_id in synthetic_state.get_attackers()
    # Haste is NOT vigilance — declaring as attacker still taps it.
    assert synthetic_state.is_tapped(obj_id) is True


def test_non_haste_creature_summoning_sick_still_rejects(synthetic_state):
    """Sanity / regression: a freshly-cast NON-haste creature (the
    Llanowar Elves baked into the synthetic seed's hand) still gets
    refused as an attacker. The haste branch must not have leaked into
    the default summoning-sickness-rejection path."""
    synthetic_state.add_mana(0, "G", 1)
    elf_id = P0_FIRST_HAND_ID  # Llanowar Elves, no haste
    assert synthetic_state.cast_creature(elf_id, 0) is True
    assert synthetic_state.is_summoning_sick(elf_id) is True
    # No haste: still rejected.
    assert synthetic_state.declare_attacker(elf_id) is False
    assert synthetic_state.get_attackers() == []
    # And the rejection must NOT have tapped it as a side effect.
    assert synthetic_state.is_tapped(elf_id) is False


def test_haste_does_not_skip_already_tapped(synthetic_state):
    """Haste bypasses summoning sickness, NOT the "must be untapped to
    attack" precondition (CR 508.1a). A pre-tapped haste creature is
    still refused. Doesn't grant untap."""
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["haste"]), 0, ZONE_BATTLEFIELD
    )
    # Inject sets summoning_sick=False, so the only rejection cause
    # left is the tap. Tap it manually.
    assert synthetic_state.tap_object(obj_id) is True
    assert synthetic_state.is_tapped(obj_id) is True
    # Even with haste, tapped creatures can't attack.
    assert synthetic_state.declare_attacker(obj_id) is False, (
        "haste does not bypass the must-be-untapped precondition (CR 508.1a)"
    )
    assert synthetic_state.get_attackers() == []


def test_haste_creature_taps_when_attacking_unless_vigilance(synthetic_state):
    """Haste alone still taps the creature on attack — haste != vigilance.
    A summoning-sick haste creature attacks AND taps."""
    ZONE_HAND = 0
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["haste"]), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    assert synthetic_state.cast_creature(obj_id, 0) is True
    assert synthetic_state.is_summoning_sick(obj_id) is True
    assert synthetic_state.is_tapped(obj_id) is False
    # Attack with the haste creature.
    assert synthetic_state.declare_attacker(obj_id) is True
    # Haste alone DOES tap — only vigilance skips the tap step.
    assert synthetic_state.is_tapped(obj_id) is True, (
        "haste does NOT skip the tap-on-attack step; only vigilance does that"
    )


def test_haste_plus_vigilance_does_not_tap(synthetic_state):
    """Keyword composition: a creature with BOTH haste and vigilance,
    freshly cast (summoning_sick=True), can attack AND skip the tap.
    Haste lets it attack on its first turn; vigilance suppresses the
    tap-on-attack."""
    ZONE_HAND = 0
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["haste", "vigilance"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    assert synthetic_state.cast_creature(obj_id, 0) is True
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # Haste lets it attack despite summoning sickness.
    assert synthetic_state.declare_attacker(obj_id) is True, (
        "haste+vigilance: haste must still bypass summoning sickness"
    )
    assert obj_id in synthetic_state.get_attackers()
    # Vigilance suppresses the tap.
    assert synthetic_state.is_tapped(obj_id) is False, (
        "haste+vigilance: vigilance must still skip the tap-on-attack step"
    )


# ----------------------------- flying + reach ------------------------------
#
# Flying (CR 702.9): a creature with flying can be blocked only by creatures
# with flying or reach. Other creatures can't block it.
#
# Reach (CR 702.17): a creature with reach can block creatures with flying.
# Reach has no effect on the creature's own attacking — a reach creature
# attacks like any ground creature, blockable by anything.
#
# Implementation hook in `state_ops_combat.rs:declare_blocker`: today the
# rejection set is `{ attacker not declared, blocker missing/non-creature,
# blocker tapped }`. This slice adds: if the attacker has the `"flying"`
# keyword AND the blocker has neither `"flying"` nor `"reach"` in its
# printing keywords, refuse the block.
#
# Scope simplifications (mirrored from the module docstring):
#
# - Reach only affects the BLOCKING direction. A reach attacker is treated
#   like a ground creature — any blocker can stop it (see
#   `test_reach_alone_does_not_grant_flying`).
# - Flying + reach on the same attacker still cannot be blocked by anything
#   that lacks both — except it CAN be blocked by anything because flying
#   is the restriction and reach doesn't add a new blocking restriction.
#   Wait, re-read CR 702.9: flying restricts blocking. Reach on the
#   attacker doesn't change what can block the attacker. The flying
#   restriction stays — so `flying+reach` attacker is still only
#   blockable by flying/reach. We don't have a test asserting the OPEN
#   interpretation; we DO have a sanity test confirming that a flying
#   attacker is still blockable by either flying OR reach, regardless
#   of whether the attacker also has reach (which on attack is a no-op).


def test_flying_attacker_cannot_be_blocked_by_grounded_creature(synthetic_state):
    """A flying 2/2 attacker; a non-flying / non-reach 3/3 blocker tries
    to block. ``declare_blocker`` returns False; nothing pushed onto
    ``state.blockers``."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # Grounded creature can't block a flyer (CR 702.9).
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is False, (
        "non-flying/non-reach blocker must not be able to block a flying "
        "attacker (CR 702.9)"
    )
    assert synthetic_state.get_blockers() == []


def test_flying_attacker_can_be_blocked_by_flying_creature(synthetic_state):
    """Flying 2/2 attacker; flying 2/2 blocker. ``declare_blocker``
    returns True; the pair lands on ``state.blockers``."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_flying_attacker_can_be_blocked_by_reach_creature(synthetic_state):
    """Flying 2/2 attacker; reach 2/2 blocker. ``declare_blocker``
    returns True (CR 702.17 — reach lets a creature block flyers)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["reach"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "reach blocker must be able to block a flying attacker (CR 702.17)"
    )
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_non_flying_attacker_can_be_blocked_by_anything(synthetic_state):
    """Sanity / regression: a non-flying 2/2 attacker can still be
    blocked by a non-flying / non-reach 2/2 blocker. The flying-rule
    branch must not have leaked into the default path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_reach_alone_does_not_grant_flying(synthetic_state):
    """Reach affects blocking, NOT attacking. A reach creature attacking
    is essentially a ground creature for blocking purposes — any
    blocker can stop it (flying or not). And a reach attacker doesn't
    pick up flying's "only blockable by flying/reach" restriction."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["reach"]), 0, ZONE_BATTLEFIELD
    )
    # Non-flying / non-reach blocker can stop a reach attacker (which
    # has no flying so no blocking restriction applies).
    grounded_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(grounded_blocker_id, attacker_id) is True, (
        "reach attacker (no flying) is treated as a ground creature for "
        "blocking purposes — any blocker can stop it"
    )
    assert (attacker_id, grounded_blocker_id) in synthetic_state.get_blockers()


def test_reach_attacker_can_also_be_blocked_by_flyer(synthetic_state):
    """Companion to the reach-attacker-blockable test: an opposing flying
    creature can also block a reach (= ground) attacker. Flying on the
    blocker doesn't restrict its blocking choices in any direction."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["reach"]), 0, ZONE_BATTLEFIELD
    )
    flying_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(flying_blocker_id, attacker_id) is True
    assert (attacker_id, flying_blocker_id) in synthetic_state.get_blockers()


def test_flying_plus_reach_attacker_can_be_blocked_by_anything(synthetic_state):
    """Defensive sanity: an attacker with BOTH flying AND reach is
    still bound by the flying restriction (reach on the attacker is a
    no-op for blocking purposes; reach only enables a creature to
    block flyers when it's on the BLOCKER, not on the attacker).
    Blockers that would already pass the flying gate (flying or reach
    on the blocker) keep working — verified here with a flying blocker."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["flying", "reach"]), 0, ZONE_BATTLEFIELD
    )
    flying_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(flying_blocker_id, attacker_id) is True, (
        "flying+reach attacker can be blocked by a flying blocker"
    )
    assert (attacker_id, flying_blocker_id) in synthetic_state.get_blockers()


# ----------------------------- defender ------------------------------------
#
# Defender (CR 702.3): a creature with defender can't attack. The keyword has
# no impact on blocking, on combat damage, or on any other phase — only on
# eligibility for `declare_attacker`.
#
# Implementation hook in `state_ops_combat.rs:declare_attacker`: today the
# eligibility gates are { battlefield creature, untapped, not summoning-sick
# (modulo haste) }. This slice adds: if the printing carries the
# `"defender"` keyword, refuse the declaration.
#
# Defender wins over haste — a creature with both keywords still can't
# attack (haste only bypasses summoning-sickness; it doesn't grant the
# ability to attack a creature otherwise prohibited from attacking).


def test_defender_creature_cannot_attack(synthetic_state):
    """A 0/4 defender creature cannot be declared as attacker
    (CR 702.3). ``declare_attacker`` returns False; nothing pushed onto
    ``state.attackers``; the would-be attacker is NOT tapped as a
    side-effect of the rejection."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 4, ["defender"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.is_tapped(attacker_id) is False
    assert synthetic_state.is_summoning_sick(attacker_id) is False
    assert synthetic_state.declare_attacker(attacker_id) is False, (
        "defender creature must not be declarable as attacker (CR 702.3)"
    )
    assert synthetic_state.get_attackers() == []
    # And the rejection didn't tap it as a side effect.
    assert synthetic_state.is_tapped(attacker_id) is False


def test_non_defender_creature_attacks_normally(synthetic_state):
    """Sanity / regression: a vanilla 2/2 attacker with no keywords still
    attacks fine. The defender branch must not have leaked into the
    default path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert attacker_id in synthetic_state.get_attackers()
    assert synthetic_state.is_tapped(attacker_id) is True


def test_defender_plus_haste_still_cannot_attack(synthetic_state):
    """Composition: a creature with BOTH defender and haste still can't
    attack. Haste only bypasses summoning sickness; it does NOT grant
    the ability to attack a creature whose printing forbids attacking
    (defender wins)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 4, ["defender", "haste"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is False, (
        "defender+haste: defender wins. Haste does not override defender."
    )
    assert synthetic_state.get_attackers() == []


# ----------------------------- menace --------------------------------------
#
# Menace (CR 702.110): a creature with menace can't be blocked except by two
# or more creatures.
#
# **Enforcement model: validation predicate, not declare-time rejection.**
# `declare_blocker` for a menace attacker is chicken-and-egg with the
# multi-block requirement — the first blocker assigned to a menace
# attacker is illegal in isolation but legal once a second blocker is
# added. Rejecting at declare time would force callers to declare the
# blockers in some artificial "all at once" form.
#
# Instead, this slice exposes a `is_legal_block_assignment(attacker_id)`
# predicate on `GameState` that returns False if the attacker has menace
# AND exactly one blocker assigned, True otherwise (zero blockers, 2+
# blockers, or no menace). Callers run the predicate after all blocks
# have been declared and unwind / reject the assignment if it returns
# False.
#
# Scope simplifications:
#
# - The predicate only checks the menace constraint. Other multi-blocker
#   constraints (e.g. "can't be blocked by more than two creatures") are
#   deferred.
# - The predicate only counts entries in `self.blockers` matching the
#   attacker. Blockers not actually present in the Vec are ignored.
# - The predicate is read-only; calling it does not mutate state.


def test_menace_attacker_cannot_be_blocked_by_one_blocker_alone(synthetic_state):
    """A 3/3 menace attacker is "blocked" by a single non-menace
    blocker. ``is_legal_block_assignment(attacker_id)`` returns False —
    menace requires two or more blockers (CR 702.110)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["menace"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    # The block landed on the Vec (declare-time accepts), but the
    # validation predicate refuses the assignment because it's a single
    # blocker against a menace attacker.
    assert synthetic_state.is_legal_block_assignment(attacker_id) is False, (
        "menace attacker with exactly 1 blocker must fail the legality "
        "predicate (CR 702.110)"
    )


def test_menace_attacker_blocked_by_two_creatures_legal(synthetic_state):
    """Same setup, but two blockers. ``is_legal_block_assignment``
    returns True — menace's "two or more" requirement is satisfied."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["menace"]), 0, ZONE_BATTLEFIELD
    )
    blocker_a = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    blocker_b = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_a, attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_b, attacker_id) is True
    assert synthetic_state.is_legal_block_assignment(attacker_id) is True, (
        "menace attacker with 2+ blockers satisfies the multi-block "
        "requirement (CR 702.110)"
    )


def test_menace_attacker_unblocked_legal(synthetic_state):
    """Zero blockers against a menace attacker is legal — menace only
    constrains how the attacker CAN be blocked (must be 2+), not whether
    it must be blocked at all. An unblocked menace attacker passes the
    predicate."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["menace"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # No blockers declared.
    assert synthetic_state.is_legal_block_assignment(attacker_id) is True, (
        "unblocked menace attacker is legal — menace doesn't require blocking"
    )


def test_non_menace_attacker_with_one_blocker_legal(synthetic_state):
    """Sanity / regression: a vanilla attacker with a single blocker
    passes the predicate. The menace branch must not have leaked into
    the default path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    assert synthetic_state.is_legal_block_assignment(attacker_id) is True, (
        "non-menace attacker with one blocker is legal"
    )


# ----------------------------- double-strike -------------------------------
#
# Double-strike (CR 702.4): a creature with double strike deals combat damage
# in BOTH the first-strike damage step AND the regular damage step. Layered
# on top of the round-9 first-strike two-substep machinery in
# `state_ops_combat.rs:deal_combat_damage`:
#
# - **First-strike substep:** includes sources whose printing carries
#   `"first_strike"` OR `"double_strike"`.
# - **Regular substep:** includes sources whose printing carries NEITHER
#   first-strike NOR double-strike (the keyword-less / unkeyworded baseline)
#   AND sources whose printing carries `"double_strike"` IF they survived
#   the first-strike step (their marked `damage` is still < their printed
#   `toughness`).
#
# Scope notes for this slice:
#
# - **No double-strike + trample interaction.** A double-strike + trample
#   creature would deal trample-excess to the defender twice in real MTG;
#   today the simplified model just routes whichever path the attacker is
#   on (blocked vs unblocked) per substep. If the blocker dies during the
#   first-strike substep, the second-strike has no creature target and —
#   without trample wired in for the unblocked-substep-after-block path —
#   the second strike fizzles. This matches the `single-blocker model with
#   no trample-on-blocker-died spillover` simplification.
# - **No SBAs between substeps.** Same as the round-9 first-strike slice:
#   the within-function `damage < toughness` predicate gates the second
#   strike from a creature that took lethal damage in step 1. The SBA
#   sibling slice still owns lethal-damage-destroys-creature.
# - **Damage marks are not cleared between substeps.** A double-strike
#   creature that dealt 2 in step 1 and 2 more in step 2 to the same
#   blocker leaves 4 marked damage on that blocker.


def test_double_strike_attacker_strikes_twice_unblocked(synthetic_state):
    """A 2/2 double-strike attacker, unblocked, deals damage in BOTH
    substeps — the defender takes 2 in the first-strike step and 2 more
    in the regular step, for 4 total. With life=20 starting, defender
    ends at 16."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["double_strike"]), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Defender took 2 in each substep = 4 total.
    assert synthetic_state.get_life(1) == 16, (
        "double-strike attacker, unblocked, must deal damage in BOTH the "
        "first-strike substep AND the regular substep — defender takes "
        "2 + 2 = 4 (life: 20 - 4 = 16)"
    )


def test_double_strike_attacker_kills_blocker_in_first_strike_step(synthetic_state):
    """A 2/2 double-strike attacker vs a 2/2 vanilla blocker. The
    first-strike substep deals 2 to the blocker (lethal mark). The
    regular substep: the attacker's second strike has no remaining
    blocker target (single-blocker model, blocker died during step 1)
    — the second strike fizzles since this slice does NOT wire
    double-strike + trample. The blocker did NOT first-strike, so in
    the regular substep the dead blocker contributes no back-damage
    (its damage>=toughness gates it out). Net: blocker has 2 damage,
    attacker has 0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["double_strike"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 2 in step 1 (lethal), no second hit (attacker's
    # second strike fizzles — no trample, single-blocker model).
    assert synthetic_state.get_damage(blocker_id) == 2, (
        "double-strike vs vanilla 2/2: blocker takes lethal in first-strike "
        "step; second-strike has no creature target and does not pile on"
    )
    # Attacker took 0 — blocker died before the regular substep, so
    # its non-first-strike back-damage doesn't fire.
    assert synthetic_state.get_damage(attacker_id) == 0, (
        "double-strike vs vanilla 2/2: blocker died in step 1, can't "
        "back-damage the attacker in step 2"
    )


def test_double_strike_blocker_kills_attacker_then_strikes_again_useless(synthetic_state):
    """Symmetric: vanilla 2/2 attacker vs double-strike 2/2 blocker.
    Step 1: blocker deals 2 to attacker (lethal). Step 2: attacker
    can't strike (took lethal in step 1), and the blocker's second
    strike has no remaining attacker target (single-attacker model
    in this slice) — it fizzles. Net: attacker has 2 damage,
    blocker has 0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["double_strike"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Attacker took 2 (lethal) in step 1.
    assert synthetic_state.get_damage(attacker_id) == 2
    # Blocker took 0 — attacker died in step 1, can't strike back.
    assert synthetic_state.get_damage(blocker_id) == 0, (
        "vanilla attacker vs double-strike blocker: attacker died in step "
        "1, the regular-step back-damage from a non-FS source must NOT "
        "fire from a dead source"
    )


def test_double_strike_vs_first_strike_both_strike_in_first_step(synthetic_state):
    """A 3/3 double-strike attacker vs a 2/2 first-strike blocker.
    Step 1 (first-strike substep): both deal damage. The DS attacker
    deals 3 to the blocker (lethal — damage>=toughness); the FS
    blocker deals 2 to the attacker (NOT lethal — 2 < 3). Step 2
    (regular substep): the attacker is alive and has double-strike,
    so it strikes again — but the blocker is already dead (single-
    blocker model, no trample). Second strike fizzles. The blocker
    is FS, not DS — its second-step damage is gated out (FS sources
    only fire in step 1).

    Net: blocker has 3 damage, attacker has 2 damage (alive)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["double_strike"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Both struck simultaneously in step 1.
    assert synthetic_state.get_damage(blocker_id) == 3, (
        "DS vs FS step 1: both strike together — DS attacker deals 3 to "
        "blocker"
    )
    assert synthetic_state.get_damage(attacker_id) == 2, (
        "DS vs FS step 1: both strike together — FS blocker deals 2 to "
        "attacker; the attacker survived (2 < 3) and the FS blocker did "
        "NOT strike again in step 2 (FS only fires once)"
    )


def test_non_double_strike_attacker_strikes_only_once(synthetic_state):
    """Sanity / regression: a vanilla 2/2 attacker, unblocked, deals
    only its power once (defender drops by 2). The double-strike
    branch must not have leaked into the default path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    synthetic_state.deal_combat_damage()
    assert synthetic_state.get_life(1) == 18, (
        "vanilla attacker unblocked deals power once — defender drops by "
        "2, not 4"
    )


def test_clone_then_double_strike_combat_does_not_affect_original(synthetic_state):
    """**CoW canary.** Run a full DS combat exchange on a clone — declare
    attacker, deal damage twice via the DS path — and the original sees
    none of it: no attackers, no life change, no damage on the
    attacker."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["double_strike"]), 0, ZONE_BATTLEFIELD
    )
    other = synthetic_state.clone_once()
    # Run DS combat on the clone only.
    assert other.declare_attacker(attacker_id) is True
    other.deal_combat_damage()
    # Clone sees the full DS effect on the defender (4 total).
    assert other.get_life(1) == 16
    # Original sees no fallout.
    assert synthetic_state.get_attackers() == []
    assert synthetic_state.get_life(1) == 20, (
        "CoW broken: DS combat on clone leaked into original life total"
    )
    assert synthetic_state.get_damage(attacker_id) == 0
    assert synthetic_state.is_tapped(attacker_id) is False, (
        "CoW broken: declaring DS attacker on clone leaked into original "
        "battlefield"
    )


# ----------------------------- skulk ---------------------------------------

# Skulk (CR 702.118): a creature with skulk can't be blocked by creatures
# with greater power. The check is at ``declare_blocker``-time (mirrors
# the flying+reach gate): if the attacker has ``"skulk"`` in its
# printing.keywords AND the candidate blocker's power is strictly greater
# than the attacker's power, the block is refused. Equal-power blockers
# pass (CR 702.118 says "greater power", not "equal or greater").


def test_skulk_attacker_blocked_by_lower_power_creature(synthetic_state):
    """A 3/3 skulk attacker; a 2/2 blocker (power 2 < attacker power 3).
    ``declare_blocker`` returns True — blocker's power is not greater
    than the attacker's."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "skulk attacker (power 3) must be blockable by a 2/2 blocker — "
        "skulk forbids GREATER power, not equal-or-greater"
    )
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_skulk_attacker_blocked_by_equal_power_creature(synthetic_state):
    """A 3/3 skulk attacker; a 3/3 blocker (power equal to the
    attacker's). ``declare_blocker`` returns True — CR 702.118 says
    GREATER power, and 3 is not greater than 3."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "skulk: equal-power blocker is legal (CR 702.118 — 'greater "
        "power', not 'equal or greater')"
    )
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_skulk_attacker_cannot_be_blocked_by_higher_power_creature(synthetic_state):
    """A 2/2 skulk attacker; a 3/3 blocker (power 3 > attacker power 2).
    ``declare_blocker`` returns False (CR 702.118)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is False, (
        "skulk: blocker (power 3) > attacker (power 2) must be refused"
    )
    assert synthetic_state.get_blockers() == []


def test_skulk_attacker_cannot_be_blocked_by_much_higher_power_creature(synthetic_state):
    """A 3/3 skulk attacker; a 4/4 blocker. ``declare_blocker``
    returns False — 4 > 3 trips the skulk gate."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 4, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is False, (
        "skulk 3/3 attacker must not be blockable by a 4/4 (4 > 3)"
    )
    assert synthetic_state.get_blockers() == []


def test_non_skulk_attacker_blocked_normally(synthetic_state):
    """Sanity / regression: a non-skulk 2/2 attacker can be blocked by
    a higher-power blocker. The skulk gate must not have leaked into
    the default blocking path."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "non-skulk attacker must be blockable by anything (no power "
        "constraint)"
    )
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_skulk_with_zero_power_blocked_by_zero_power_creature(synthetic_state):
    """A 0/3 skulk attacker; a 0/3 blocker (power 0 == attacker's
    power 0). 0 is not GREATER than 0, so the block is legal."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 3, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "skulk 0-power attacker: 0-power blocker is equal, not greater — "
        "block is legal"
    )
    assert (attacker_id, blocker_id) in synthetic_state.get_blockers()


def test_skulk_with_zero_power_cannot_be_blocked_by_one_power_creature(synthetic_state):
    """A 0/3 skulk attacker; a 1/1 blocker (power 1 > attacker's 0).
    The block is refused — anything with positive power is greater than
    0."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 3, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is False, (
        "skulk 0-power attacker: any positive-power blocker is greater — "
        "block refused"
    )
    assert synthetic_state.get_blockers() == []


def test_skulk_plus_flying_combined(synthetic_state):
    """An attacker with BOTH skulk AND flying composes: a candidate
    blocker must pass the flying gate (have flying or reach) AND the
    skulk gate (power not greater than attacker's).

    - Non-flying 1/1 blocker: fails the flying gate → refused.
    - Flying 1/1 blocker: passes flying, passes skulk (1 not > 2) →
      legal.
    - Flying 3/3 blocker: passes flying, FAILS skulk (3 > 2) →
      refused."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["skulk", "flying"]), 0, ZONE_BATTLEFIELD
    )
    ground_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    flying_small_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    flying_big_blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # Ground 1/1: fails flying gate.
    assert synthetic_state.declare_blocker(ground_blocker_id, attacker_id) is False, (
        "skulk+flying attacker: non-flying blocker fails flying gate"
    )
    # Flying 1/1: passes both gates.
    assert synthetic_state.declare_blocker(flying_small_blocker_id, attacker_id) is True, (
        "skulk+flying attacker: flying 1/1 passes flying gate AND skulk "
        "gate (1 not > 2)"
    )
    # Flying 3/3: passes flying but fails skulk.
    assert synthetic_state.declare_blocker(flying_big_blocker_id, attacker_id) is False, (
        "skulk+flying attacker: flying 3/3 passes flying gate but FAILS "
        "skulk gate (3 > 2)"
    )
    # Only the flying 1/1 made it onto the blockers list.
    assert synthetic_state.get_blockers() == [(attacker_id, flying_small_blocker_id)]


# ----------------------------- cross-keyword interactions -------------------
#
# Multi-keyword composition tests. The per-keyword slices (rounds 9-15) each
# verified their own keyword in isolation; these tests pin the behavior when
# two or more keywords meet in the same combat. They share the existing
# ``_keyword_creature_dict`` fixture and the ``register_and_inject_object``
# injection path — no Rust changes are required, only test coverage on top
# of the implemented arms.
#
# Where the actual engine behavior is more subtle than CR alone would
# suggest, the test docstring notes the round/slice that owns the simplification.


def test_trample_plus_first_strike_overkill_tramples_through(synthetic_state):
    """Trample + first-strike (round-9 + r10-style composition).
    A 4/1 with both keywords vs a vanilla 1/1 blocker.
    First-strike substep: attacker deals 4 — only 1 needed to kill the
    1/1, so 3 tramples through to the defender (life 20 -> 17). Blocker
    dies in the first-strike substep, so its regular-substep back-damage
    never fires; the attacker is left at 0 marked damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(4, 1, ["trample", "first_strike"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took its toughness (1) and dies; trample carried the 3
    # excess to the defender in the first-strike substep.
    assert synthetic_state.get_damage(blocker_id) == 1, (
        "trample+first_strike: blocker takes attacker.power capped at "
        "blocker.toughness (= 1) in the first-strike substep"
    )
    assert synthetic_state.get_life(1) == 17, (
        "trample+first_strike: trample excess (power - toughness = 4 - 1 "
        "= 3) carries through to the defender even when applied in the "
        "first-strike substep"
    )
    # Blocker died in step 1; no back-damage in the regular substep.
    assert synthetic_state.get_damage(attacker_id) == 0, (
        "trample+first_strike: blocker dies in step 1, no back-damage "
        "in step 2 — attacker stays clean"
    )


def test_lifelink_plus_double_strike_gains_life_twice(synthetic_state):
    """Lifelink + double-strike: a 1/1 with both keywords, unblocked,
    deals 1 in the first-strike substep AND 1 in the regular substep,
    so the defender takes 2 total (20 -> 18) and lifelink fires on
    BOTH hits — the controller gains 2 life total (20 -> 22). Pins the
    double-strike-multiplies-lifelink behavior."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["lifelink", "double_strike"]),
        0,
        ZONE_BATTLEFIELD,
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Defender took 1 + 1 = 2.
    assert synthetic_state.get_life(1) == 18, (
        "lifelink+double_strike unblocked: defender takes power in BOTH "
        "substeps = 2 total"
    )
    # Lifelink fired on each hit; controller gained 1 + 1 = 2.
    assert synthetic_state.get_life(0) == 22, (
        "lifelink+double_strike: lifelink fires on EACH substep's damage, "
        "so controller gains power twice (= 2)"
    )


def test_lifelink_deathtouch_trample_caps_blocker_damage_at_one(synthetic_state):
    """Lifelink + deathtouch + trample on a 1/1 attacker vs a 5/5
    blocker. Per CR 702.19c, deathtouch lets trample treat the
    'lethal-to-blocker' floor as 1 — so the cap drops to 1. With the
    attacker dealing only 1 power, ``power - cap = 0`` so nothing
    tramples through (defender life unchanged at 20). Deathtouch
    upgrades the blocker's marked damage to its toughness (5), and
    lifelink fires on the literal damage dealt (1) so the controller
    gains 1 life. The 5/5 blocker still strikes back for 5 — the
    attacker takes 5 marked damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["lifelink", "deathtouch", "trample"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Deathtouch upgrades blocker mark to lethal (>= 5).
    assert synthetic_state.get_damage(blocker_id) >= 5, (
        "deathtouch+trample+lifelink: deathtouch still upgrades blocker "
        "mark to its toughness even with the trample cap dropped to 1"
    )
    # power - cap = 1 - 1 = 0; no trample excess.
    assert synthetic_state.get_life(1) == 20, (
        "deathtouch+trample 1/1: cap drops to 1, no excess — defender "
        "life unchanged (CR 702.19c)"
    )
    # Lifelink fires on the literal 1 damage dealt — controller +1.
    assert synthetic_state.get_life(0) == 21, (
        "deathtouch+lifelink: lifelink fires on the actual damage dealt "
        "(1), not on deathtouch's upgraded mark"
    )
    # 5/5 blocker back-damages the 1/1 attacker for 5.
    assert synthetic_state.get_damage(attacker_id) == 5


def test_first_strike_plus_indestructible_attacker_survives_back_damage(
    synthetic_state,
):
    """First-strike + indestructible 1/1 attacker vs a vanilla 5/5
    blocker. First-strike substep: attacker deals 1 to blocker (not
    lethal, 1 < 5). Regular substep: blocker (alive, vanilla) deals 5
    to the attacker. Without indestructible the attacker would die at
    SBA time, but indestructible spares it (CR 702.12). After
    ``apply_sbas`` both creatures remain on the battlefield. The
    attacker still carries 5 marked damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["first_strike", "indestructible"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 1 in the first-strike step — not lethal.
    assert synthetic_state.get_damage(blocker_id) == 1
    # Attacker took the full 5 in the regular step (blocker survived
    # step 1).
    assert synthetic_state.get_damage(attacker_id) == 5
    # SBAs: blocker survives (1 < 5 toughness), attacker survives
    # because indestructible (5 marked damage >= 1 toughness, but
    # 702.12 exempts it from 704.5g).
    assert synthetic_state.apply_sbas() == 0, (
        "first_strike+indestructible vs vanilla 5/5: neither dies — "
        "blocker (1 dmg < 5 toughness) nor indestructible attacker"
    )
    assert synthetic_state.find_object_zone(attacker_id) == ZONE_BATTLEFIELD, (
        "first_strike+indestructible attacker takes 5 damage but stays "
        "on the battlefield (CR 702.12)"
    )
    assert synthetic_state.find_object_zone(blocker_id) == ZONE_BATTLEFIELD


def test_vigilance_plus_haste_freshly_cast_attacks_untapped(synthetic_state):
    """Composition cross-check: a freshly-cast vigilance+haste creature
    (summoning_sick=True via the cast-flow) can attack on its first
    turn (haste) AND stays untapped after attacking (vigilance). Two
    keywords from different round slices (r9 vigilance, r10 haste)
    composing on the same creature."""
    ZONE_HAND = 0
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["vigilance", "haste"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)  # cover the {1} generic
    assert synthetic_state.cast_creature(obj_id, 0) is True
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # Haste bypasses the summoning-sickness rejection.
    assert synthetic_state.declare_attacker(obj_id) is True, (
        "vigilance+haste freshly cast: haste must bypass summoning sickness"
    )
    # Vigilance suppresses the tap.
    assert synthetic_state.is_tapped(obj_id) is False, (
        "vigilance+haste: vigilance must skip the tap-on-attack step"
    )
    assert obj_id in synthetic_state.get_attackers()


def test_flying_plus_menace_needs_two_flying_or_reach_blockers(synthetic_state):
    """Flying + menace composition. A 3/3 with both keywords requires
    blockers that pass BOTH the flying gate (flying or reach) AND the
    menace count (2+). A single flying blocker fails
    ``is_legal_block_assignment``; adding a second flying blocker
    satisfies menace. A non-flying blocker is rejected outright at
    declare-time by the flying gate, regardless of menace."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["flying", "menace"]),
        0,
        ZONE_BATTLEFIELD,
    )
    flying1 = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    flying2 = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["flying"]), 1, ZONE_BATTLEFIELD
    )
    ground = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # First flying blocker lands on the Vec, but is illegal in isolation
    # (menace requires 2+).
    assert synthetic_state.declare_blocker(flying1, attacker_id) is True
    assert synthetic_state.is_legal_block_assignment(attacker_id) is False, (
        "flying+menace with one flying blocker: flying gate passes but "
        "menace fails (single blocker)"
    )
    # Ground blocker fails the flying gate outright.
    assert synthetic_state.declare_blocker(ground, attacker_id) is False, (
        "flying+menace: non-flying/non-reach blocker is rejected at "
        "declare-time by the flying gate (CR 702.9)"
    )
    # Second flying blocker satisfies menace.
    assert synthetic_state.declare_blocker(flying2, attacker_id) is True
    assert synthetic_state.is_legal_block_assignment(attacker_id) is True, (
        "flying+menace with two flying blockers: both gates satisfied"
    )


def test_menace_attacker_with_only_one_blocker_fails_legality(synthetic_state):
    """Composition probe: a single menace attacker faces a defender with
    only one creature available to block. The defender's one creature
    is declared and lands on the blockers Vec, but the menace legality
    predicate refuses the assignment — the caller must unwind the block
    (a real game would either rebuild with two blockers or leave the
    attacker unblocked)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["menace"]), 0, ZONE_BATTLEFIELD
    )
    sole_blocker = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(sole_blocker, attacker_id) is True
    # Predicate refuses — caller is expected to drop the block.
    assert synthetic_state.is_legal_block_assignment(attacker_id) is False, (
        "menace + only-one-available-blocker: legality predicate must "
        "refuse the assignment (CR 702.110)"
    )


def test_defender_plus_haste_still_refused(synthetic_state):
    """A defender+haste creature, freshly injected onto battlefield
    (summoning_sick=False), still cannot attack — defender (CR 702.3)
    is an unconditional attack prohibition that haste does not lift.
    Pairs with ``test_defender_plus_haste_still_cannot_attack`` above
    but at a different P/T to confirm the rejection is keyword-driven,
    not stat-driven."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 5, ["defender", "haste"]),
        0,
        ZONE_BATTLEFIELD,
    )
    assert synthetic_state.is_summoning_sick(attacker_id) is False
    assert synthetic_state.declare_attacker(attacker_id) is False, (
        "defender+haste: defender prohibition wins even when haste would "
        "otherwise allow attacking"
    )
    assert synthetic_state.get_attackers() == []


def test_defender_plus_vigilance_still_refused(synthetic_state):
    """Defender composes with vigilance the same way it composes with
    haste: defender wins. A defender+vigilance creature still can't
    attack."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(0, 6, ["defender", "vigilance"]),
        0,
        ZONE_BATTLEFIELD,
    )
    assert synthetic_state.declare_attacker(attacker_id) is False, (
        "defender+vigilance: defender prohibition wins"
    )
    assert synthetic_state.get_attackers() == []


def test_skulk_plus_first_strike_blocker_passes_both_gates(synthetic_state):
    """Skulk + first-strike on the attacker: the skulk power gate
    governs blocking (small blockers only), and first-strike sequences
    combat damage. A 2/2 skulk+FS attacker vs a 1/1 vanilla blocker
    passes the skulk gate (1 not > 2) and the FS substep deals 2 —
    lethal at toughness 1. Blocker dies before the regular substep, so
    the attacker takes no back-damage."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["skulk", "first_strike"]),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # Skulk gate: 1 not > 2 — block legal.
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker takes 2 in FS substep (overkill at toughness 1).
    assert synthetic_state.get_damage(blocker_id) == 2
    # Attacker took no back-damage; blocker died in step 1.
    assert synthetic_state.get_damage(attacker_id) == 0


def test_skulk_one_one_attacker_blocked_by_equal_power_one_one(synthetic_state):
    """Skulk 1/1 attacker vs 1/1 blocker: equal power passes the skulk
    gate (CR 702.118 says GREATER power, not equal). Companion to the
    skulk-vs-higher-power test — pins behavior at the boundary."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True, (
        "skulk 1/1: equal-power blocker passes (CR 702.118 — greater, "
        "not equal-or-greater)"
    )


def test_skulk_one_one_attacker_refuses_two_two_blocker(synthetic_state):
    """Companion to the previous test at the other side of the boundary:
    a 1/1 skulk attacker refuses a 2/2 blocker (2 > 1)."""
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, ["skulk"]), 0, ZONE_BATTLEFIELD
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is False, (
        "skulk 1/1: 2/2 blocker (power 2 > 1) rejected"
    )
    assert synthetic_state.get_blockers() == []


def test_indestructible_5_5_survives_ten_damage_via_sba(synthetic_state):
    """Round-13 indestructible interaction cross-check inside the combat
    test file: a 5/5 indestructible takes 10 damage (overkill by 2x);
    ``apply_sbas`` returns 0, the creature remains on the battlefield
    with its 10 marked damage intact (CR 702.12, CR 704.5g)."""
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, ["indestructible"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.deal_damage(obj_id, 10)
    assert synthetic_state.apply_sbas() == 0, (
        "indestructible 5/5 with 10 damage: SBA destruction skipped "
        "(CR 702.12 / CR 704.5g)"
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # Damage marker preserved — indestructible doesn't prevent damage,
    # only the destruction SBA.
    assert synthetic_state.get_damage(obj_id) == 10


def test_indestructible_5_5_survives_zero_toughness_via_negative_counters(
    synthetic_state,
):
    """Round-13 indestructible + 0-toughness SBA. A 5/5 indestructible
    creature loaded with five -1/-1 counters has effective toughness 0,
    which would normally trigger CR 704.5f (creatures with toughness 0
    or less are put into the graveyard). Indestructible's CR 702.12b
    text exempts it — the creature stays on the battlefield."""
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(5, 5, ["indestructible"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.set_counters(obj_id, -5)  # effective toughness 0
    assert synthetic_state.apply_sbas() == 0, (
        "indestructible with effective toughness 0: 704.5f is a "
        "destruction SBA, exempted by 702.12b"
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_multi_attacker_first_strike_only_one_blocker(synthetic_state):
    """Two attackers — one with first-strike, one vanilla — and a single
    blocker assigned to the first-strike attacker.

    First-strike substep: FS attacker deals 2 to blocker (not lethal at
    toughness 3). Blocker has no first-strike, so it deals 0 in step 1.
    Regular substep: vanilla attacker is unblocked and hits the
    defender for 2 (life 20 -> 18). Blocker (alive, has no FS) deals 3
    back to the FS attacker. The FS attacker already struck in step 1
    and does NOT strike again here (only double-strike fires twice).

    Net pinned behavior: blocker 2 dmg, FS attacker 3 dmg, vanilla
    attacker 0 dmg, defender life 18."""
    fs_attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["first_strike"]),
        0,
        ZONE_BATTLEFIELD,
    )
    vanilla_attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []),
        0,
        ZONE_BATTLEFIELD,
    )
    blocker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(fs_attacker_id) is True
    assert synthetic_state.declare_attacker(vanilla_attacker_id) is True
    # Only the FS attacker gets blocked.
    assert synthetic_state.declare_blocker(blocker_id, fs_attacker_id) is True
    assert synthetic_state.get_life(1) == 20
    synthetic_state.deal_combat_damage()
    # Blocker took 2 in step 1 (FS attacker's hit) — survived.
    assert synthetic_state.get_damage(blocker_id) == 2, (
        "multi-attacker: blocker takes FS attacker's 2 damage in step 1"
    )
    # FS attacker took 3 in step 2 (blocker still alive, hit back).
    assert synthetic_state.get_damage(fs_attacker_id) == 3, (
        "multi-attacker: FS attacker survived step 1, blocker (vanilla) "
        "back-damages it for 3 in step 2"
    )
    # Vanilla attacker was unblocked and took no damage.
    assert synthetic_state.get_damage(vanilla_attacker_id) == 0
    # Defender lost only the vanilla attacker's 2.
    assert synthetic_state.get_life(1) == 18, (
        "multi-attacker: only the unblocked vanilla attacker reaches the "
        "defender — 2 damage. The FS attacker was blocked; its damage "
        "stayed on the blocker."
    )


# ----------------------------- round-27 UEOT-bonus combat composition --------
#
# The UEOT-framework slice adds `UeotModifier::PowerToughnessBonus` to
# every effective-P/T reader, including `battlefield_creature_power` /
# `battlefield_creature_toughness` in `state_ops_combat.rs`. These tests
# pin the bridge between the UEOT modifier stack and the combat-damage
# math: a haste creature with a +N/+N ETB-pump-self attacks for
# `printed_power + N` (not `printed_power`) when unblocked.
#
# Why HASTE on the creature: a freshly-resolved creature is
# summoning-sick (CR 302.1, stamped at post-resolve), so it can't
# attack on the turn it was cast unless it has haste. Without haste
# the test would need to walk a full turn boundary (untap step clears
# summoning sickness) — but cleanup clears UEOT modifiers too, so the
# bonus would expire before combat. Haste on the printing lifts the
# summoning-sick gate without touching the cleanup pathway.


def _haste_pump_self_creature_dict(power_bonus=2, toughness_bonus=2):
    """A 2/2 haste creature whose ETB pumps itself +N/+M UEOT. Haste
    lifts the summoning-sick gate so the same-turn attack succeeds
    while the UEOT modifier is still live."""
    return {
        "name": f"Haste UEOT-pump Bear +{power_bonus}/+{toughness_bonus}",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "keywords": ["haste"],
        "effects": [],
        "etb_effects": [
            {
                "kind": "pump_self_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def test_ueot_pumped_attacker_damages_defender_for_effective_power(
    synthetic_state,
):
    """A haste 2/2 with ETB +2/+2-self UEOT attacks unblocked. The
    defender takes 4 damage (printed 2 + UEOT 2), not the bare 2 the
    pre-UEOT reader would have returned. Pins
    ``battlefield_creature_power``'s UEOT-bonus fold."""
    ZONE_HAND_LOCAL = 0
    obj_id = synthetic_state.register_and_inject_object(
        _haste_pump_self_creature_dict(2, 2), 0, ZONE_HAND_LOCAL
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Sanity: creature landed with UEOT modifier; effective power 4.
    assert synthetic_state.effective_power(obj_id) == 4
    # Haste lifts the summoning-sick attack gate.
    assert synthetic_state.declare_attacker(obj_id) is True
    life_before = synthetic_state.get_life(1)
    synthetic_state.deal_combat_damage()
    # Defender lost 4 = effective power.
    assert synthetic_state.get_life(1) == life_before - 4


def test_ueot_pumped_blocker_survives_what_would_have_been_lethal(
    synthetic_state,
):
    """A haste 2/2 with ETB +0/+2-self UEOT blocks a 3-power attacker.
    The attacker deals 3 damage to the blocker — pre-UEOT, the 2/2
    would die (3 >= 2 toughness); with +0/+2 the blocker becomes
    effective 2/4, so 3 damage is non-lethal and SBA's lethal-damage
    check returns False. Pins ``battlefield_creature_toughness``'s
    UEOT-bonus fold AND `is_lethal`'s UEOT fold."""
    ZONE_HAND_LOCAL = 0
    # Attacker: a 3/3 with haste from p0's existing bears? Easier: use
    # a fresh haste 3/3 attacker.
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, ["haste"]), 0, ZONE_BATTLEFIELD
    )
    # Blocker on p1: a 2/2 haste with +0/+2 ETB pump (effective 2/4).
    blocker_id = synthetic_state.register_and_inject_object(
        _haste_pump_self_creature_dict(0, 2), 1, ZONE_HAND_LOCAL
    )
    # Resolving a spell while priority is on p0 still works for p1's
    # creature via this slice's simplified non-priority-aware
    # resolve — push as p1 and resolve.
    synthetic_state.push_to_stack(blocker_id, 1)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.effective_toughness(blocker_id) == 4

    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Blocker took 3 damage. With UEOT-bumped toughness 4, that's
    # NON-lethal — is_lethal returns False.
    assert synthetic_state.get_damage(blocker_id) == 3
    assert synthetic_state.is_lethal(blocker_id) is False


def test_ueot_pumped_creature_dies_when_ueot_clears(synthetic_state):
    """The flip side: a 2/2 was pre-damaged to 3, kept alive by a
    +0/+2 UEOT bonus (effective toughness 4 > damage 3); after the
    cleanup step clears the modifier, effective toughness drops to 2
    and an SBA pass marks it dead. Pins the cleanup → SBA lifecycle
    that powers "combat tricks that fade".
    """
    ZONE_HAND_LOCAL = 0
    obj_id = synthetic_state.register_and_inject_object(
        _haste_pump_self_creature_dict(0, 2), 0, ZONE_HAND_LOCAL
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Stamp 3 damage on the 2/4 effective creature — non-lethal under
    # the UEOT bump.
    synthetic_state.deal_damage(obj_id, 3)
    assert synthetic_state.is_lethal(obj_id) is False
    assert synthetic_state.get_damage(obj_id) == 3

    # Cleanup drains the UEOT bonus AND zeroes marked damage (CR
    # 514.2). After cleanup the creature is back to 2/2 with 0
    # damage — alive.
    synthetic_state.cleanup_step_for_active_player()
    assert synthetic_state.effective_toughness(obj_id) == 2
    assert synthetic_state.get_damage(obj_id) == 0
    assert synthetic_state.is_lethal(obj_id) is False


def test_ueot_granted_keyword_via_has_keyword_reader(synthetic_state):
    """A printing's `has_keyword` reader returns True for any printed
    keyword. Round-27 also folds UEOT-granted keywords — but
    PumpSelfUntilEOT today only pushes PowerToughnessBonus modifiers
    (the Rust enum has a `GrantKeyword` variant but no Effect arm
    surfaces it yet). This test pins the printed-side baseline so a
    UEOT-side bug that drops the printed contributions surfaces
    here. Future-slice `Effect::GrantKeywordUEOT` (or similar) will
    extend this test to assert the UEOT-side fold.
    """
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, ["haste", "flying"]),
        0,
        ZONE_BATTLEFIELD,
    )
    assert synthetic_state.has_keyword(obj_id, "haste") is True
    assert synthetic_state.has_keyword(obj_id, "flying") is True
    assert synthetic_state.has_keyword(obj_id, "trample") is False


# ---------------------------------------------------------------------------
# CE9 closure regression tests — combat damage assignment walks the
# battlefield in bf-ETB-timestamp order via the shared
# ``bf_iter_etb_sorted`` helper (not declare-order push of
# ``self.blockers``). Mirrors Python's ``combat.py:389,405``
# `[o for o in state.battlefield if o.id in attacker.blocked_by]`
# walk. Filed and closed by `feature/ce9-blocker-bf-order` — see
# `docs/RUST_PARITY_GAPS.md` I31 and the closure summary in
# `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` §3.
# ---------------------------------------------------------------------------


def test_multi_block_damage_assignment_picks_etb_first_blocker(synthetic_state):
    """CE9 regression. Declare two blockers against one attacker in
    REVERSE bf-ETB order (the higher-timestamp blocker declared
    first, then the lower-timestamp blocker). Assert that the
    LOWER-timestamp blocker is the one that takes the attacker's
    damage — matching the bf-ETB order, NOT the declare order.

    Pre-CE9 closure, Rust walked ``self.blockers`` Vec in declare
    push order and picked the higher-timestamp blocker (declared
    first) as the damage recipient — diverging from Python's
    ``[o for o in state.battlefield if o.id in attacker.blocked_by]``
    walk which is bf-ETB ordered (post-CE4). Post-closure, Rust
    walks ``bf_iter_etb_sorted`` filtered to ids in ``self.blockers``
    so the per-attacker first-blocker pick agrees with Python.
    """
    # Inject in order so ETB timestamps are: attacker < first_blocker
    # < second_blocker. ``register_and_inject_object`` bumps
    # ``next_etb_timestamp`` on every battlefield injection.
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    # bf-ETB order: this blocker comes BEFORE the second one.
    bf_first_blocker = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    # bf-ETB order: this blocker comes AFTER the first one.
    bf_second_blocker = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # Declare blockers in REVERSE bf-ETB order: the bf-later blocker
    # gets declared FIRST, the bf-earlier blocker second. Pre-CE9
    # Rust's find_map walk of self.blockers Vec would pick the
    # bf-later one (the first push); post-CE9 the bf-ETB walk picks
    # the bf-earlier one.
    assert synthetic_state.declare_blocker(bf_second_blocker, attacker_id) is True
    assert synthetic_state.declare_blocker(bf_first_blocker, attacker_id) is True
    # Sanity: self.blockers Vec is in declare push order.
    assert synthetic_state.get_blockers() == [
        (attacker_id, bf_second_blocker),
        (attacker_id, bf_first_blocker),
    ]
    synthetic_state.deal_combat_damage()
    # The attacker's 2 power goes to the FIRST blocker in BF-ETB
    # order (bf_first_blocker), not the first-declared one. The
    # bf-later blocker takes 0 damage from the attacker because the
    # single-blocker damage simplification (round-5 scope reminder)
    # assigns the attacker's full power to ONE blocker only.
    assert synthetic_state.get_damage(bf_first_blocker) == 2, (
        "CE9 regression: attacker's damage must go to the "
        "bf-ETB-first blocker, not the declare-first blocker"
    )
    assert synthetic_state.get_damage(bf_second_blocker) == 0
    # Both blockers still deal back-damage to the attacker (2+2=4).
    # Pre-CE9 the back-damage walk also iterated self.blockers
    # directly — post-CE9 the back-damage walk uses
    # bf_iter_etb_sorted too. The accumulated total is unchanged
    # (every blocker still emits its damage entry); only the order
    # of accumulation differs (no observable difference on this
    # 2/2 vs 2/2 exchange).
    assert synthetic_state.get_damage(attacker_id) == 4


def test_multi_block_damage_back_damage_uses_etb_order(synthetic_state):
    """CE9 regression: the back-damage walk (each blocker dealing
    its power to the attacker) also iterates the battlefield in
    bf-ETB-timestamp order via ``bf_iter_etb_sorted``, not the
    ``self.blockers`` Vec push order. The accumulated damage on
    the attacker is unchanged (2+2=4 vs 2+2=4); the ordering shift
    is invisible on a symmetric exchange but matters for any
    future variant where the order of accumulation is observable
    (e.g. lifelink life gain on an interleaved bf, deathtouch
    upgrade-then-mark-lethal sequencing).
    """
    attacker_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(3, 3, []), 0, ZONE_BATTLEFIELD
    )
    bf_first_blocker = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 1, ZONE_BATTLEFIELD
    )
    bf_second_blocker = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(1, 1, []), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.declare_attacker(attacker_id) is True
    # Declare in reverse bf order.
    assert synthetic_state.declare_blocker(bf_second_blocker, attacker_id) is True
    assert synthetic_state.declare_blocker(bf_first_blocker, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Sum of blocker powers: 2 + 1 = 3 damage to attacker.
    assert synthetic_state.get_damage(attacker_id) == 3
    # Attacker damage routed to the bf-ETB-first blocker (3 power
    # to bf_first_blocker, none spilled to bf_second_blocker per
    # the single-blocker damage simplification).
    assert synthetic_state.get_damage(bf_first_blocker) == 3
    assert synthetic_state.get_damage(bf_second_blocker) == 0


def test_apply_sbas_clears_damage_on_creature_move_to_graveyard(synthetic_state):
    """CE9 secondary closure: when SBA destruction moves a lethally
    damaged creature to its controller's graveyard, the obj's
    ``damage`` and ``tapped`` fields reset to 0 / false on the way
    in. Mirrors Python's ``turn.move_off_battlefield``:230-240
    semantics (CR 400.7 / 614.12).

    Pre-closure, Rust's `apply_sbas` move-to-graveyard preserved
    the damage mark and the tapped flag — invisible on most
    pre-CE9 tests because graveyard contents were rarely compared
    on a per-object damage basis, but surfaced by the multi-block
    cross-engine smoke when Python's gy entry showed damage=0 and
    Rust's showed damage=lethal.
    """
    # Inject a 2/2 with damage already at lethal (pre-stamped via
    # deal_damage instead of routing through combat).
    obj_id = synthetic_state.register_and_inject_object(
        _keyword_creature_dict(2, 2, []), 0, ZONE_BATTLEFIELD
    )
    # Tap and damage to lethal so SBA picks it up.
    synthetic_state.tap_object(obj_id)
    synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.get_damage(obj_id) == 2
    assert synthetic_state.is_tapped(obj_id) is True
    # Run SBAs — the creature has lethal damage marked (CR 704.5g).
    destroyed = synthetic_state.apply_sbas()
    assert destroyed >= 1
    # Locate the dead creature in p0's graveyard.
    gy_entries = synthetic_state.graveyard_snapshot(0)
    matching = [e for e in gy_entries if e["id"] == obj_id]
    assert len(matching) == 1, f"expected one gy entry for {obj_id}, got {matching}"
    gy_obj = matching[0]
    # Damage and tapped were cleared on the move-off-battlefield.
    assert gy_obj["damage"] == 0, (
        f"CE9 secondary: damage should be cleared on move to gy; got {gy_obj}"
    )
    assert gy_obj["tapped"] is False, (
        f"CE9 secondary: tapped should be cleared on move to gy; got {gy_obj}"
    )


# ---------------------------------------------------------------------------
# I32: `state.resolving_combat_damage_amount` production write site —
# per-event set / reset around the combat-damage assignment apply loop.
# Closes the deferred write site documented in SEARCH_LIMITATIONS.md
# (the Effect::DrawCardsEqualToResolvingCombatDamage closure left the
# write site for this slice; CE9 owned state_ops_combat.rs concurrently
# and has now landed). Mirrors Python's per-event set / reset boundaries
# at combat.py:618,623 (granted dealt-damage trigger resolve) and
# actions.py:2684,2699 (stack-pushed trigger resolve).
#
# The slot is set INSIDE apply_damage_pass for the duration of each
# per-PlanEntry application (so any downstream effect that reads it
# sees this event's amount) and reset to 0 between events (so a Late-
# resolving trigger doesn't read a stale value from a prior event).
# ---------------------------------------------------------------------------


def _starwinder_dict():
    """Starwinder-shape printing carrying
    Effect::DrawCardsEqualToResolvingCombatDamage. Mirrors the shape
    used in tests_rust/test_resolve.py for the read-side tests; copied
    here so the I32 cross-engine tests don't take a hard dependency on
    that file's private helper."""
    return {
        "name": "Synthetic Starwinder (I32)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "U": 1},
        "power": 2,
        "toughness": 3,
        "effects": [
            {"kind": "draw_cards_equal_to_resolving_combat_damage"}
        ],
    }


def test_resolving_combat_damage_amount_reset_to_zero_after_player_damage(
    synthetic_state,
):
    """I32 reset boundary: after `deal_combat_damage` runs through to
    completion, the `resolving_combat_damage_amount` slot is 0 — no
    matter what value any per-event write set it to during apply.

    A 2/2 attacker hitting an undefended player applies one Player-
    target damage entry of amount=2. The slot is set to 2 inside the
    apply loop, then reset to 0 immediately after the entry. Post-
    `deal_combat_damage`, observers reading the slot see 0.
    """
    bear_id = P0_FIRST_BEAR_ID  # 2/2 Grizzly Bears on p0 battlefield
    assert synthetic_state.declare_attacker(bear_id) is True
    # Pre-condition: slot starts at 0.
    assert synthetic_state.resolving_combat_damage_amount == 0
    synthetic_state.deal_combat_damage()
    # Defending player took 2.
    assert synthetic_state.get_life(1) == 18
    # Slot reset to 0 after the per-event apply finished.
    assert synthetic_state.resolving_combat_damage_amount == 0, (
        "I32: write site must reset slot to 0 between events / after "
        "deal_combat_damage so a Late-resolving trigger doesn't see "
        "a stale value"
    )


def test_resolving_combat_damage_amount_reset_to_zero_after_creature_damage(
    synthetic_state,
):
    """I32 reset boundary: also verified for creature-target damage
    entries (attacker damages blocker; blocker damages attacker —
    multiple events in one `deal_combat_damage` call). The slot ends
    at 0 regardless of how many events fired."""
    attacker_id = P0_FIRST_BEAR_ID  # 2/2 on p0
    blocker_id = P1_FIRST_BEAR_ID  # 2/2 on p1
    assert synthetic_state.declare_attacker(attacker_id) is True
    assert synthetic_state.declare_blocker(blocker_id, attacker_id) is True
    synthetic_state.deal_combat_damage()
    # Both took 2.
    assert synthetic_state.get_damage(attacker_id) == 2
    assert synthetic_state.get_damage(blocker_id) == 2
    # Slot reset to 0 after the final event.
    assert synthetic_state.resolving_combat_damage_amount == 0


def test_resolving_combat_damage_amount_write_overrides_pre_existing_value(
    synthetic_state,
):
    """I32 set boundary: any pre-existing value in the slot at the
    time `deal_combat_damage` is called gets overwritten by the
    per-event writes and then reset to 0. A stale sentinel value
    (e.g. left over from a prior, badly-cleaned event) cannot
    survive the apply loop.

    Setup: pre-set the slot to a sentinel (99). After
    `deal_combat_damage` the slot is 0 — proving the write site both
    overwrote the sentinel during apply AND reset to 0 after.
    """
    bear_id = P0_FIRST_BEAR_ID
    assert synthetic_state.declare_attacker(bear_id) is True
    synthetic_state.set_resolving_combat_damage_amount(99)
    assert synthetic_state.resolving_combat_damage_amount == 99
    synthetic_state.deal_combat_damage()
    # Sentinel overwritten and reset to 0.
    assert synthetic_state.resolving_combat_damage_amount == 0
    # Defender still took the right amount.
    assert synthetic_state.get_life(1) == 18


def test_resolving_combat_damage_amount_no_attackers_leaves_slot_untouched(
    synthetic_state,
):
    """Negative-case sanity: when `deal_combat_damage` has no attacker
    plan entries (no attackers declared, OR attackers all have 0
    power), there are no per-event writes — and so the slot stays at
    whatever value the caller had pre-set. The reset only fires
    PER-EVENT inside the apply loop; outside the loop the slot is
    untouched.

    This pins that the I32 write site is scoped to the per-event
    apply, NOT a sweeping pre-/post- clear of the slot around the
    whole `deal_combat_damage` call. A future caller that pre-sets
    the slot for a reason (e.g. testing the read-side via the setter)
    and then triggers a no-op `deal_combat_damage` should NOT see
    their pre-set value clobbered.
    """
    synthetic_state.set_resolving_combat_damage_amount(7)
    # No attackers declared.
    assert synthetic_state.get_attackers() == []
    synthetic_state.deal_combat_damage()
    # Slot untouched — no entries fired, no writes happened.
    assert synthetic_state.resolving_combat_damage_amount == 7


def test_resolving_combat_damage_amount_cross_engine_draw_eq_starwinder(
    synthetic_state,
):
    """I32 cross-engine: drive an actual combat damage event with a
    Starwinder-shape printing on the battlefield, then resolve the
    Starwinder Effect with the slot pre-set to the dealt amount.
    Verifies the controller draws N where N == damage dealt.

    Note: Rust's combat-damage apply loop does NOT push triggered
    abilities onto the stack today (no trigger dispatcher in
    state_ops_combat.rs; the SEARCH_LIMITATIONS.md entry calls this
    out as a future slice). The cross-engine test composes the
    pieces that DO exist:

    1. Stage a Starwinder printing on p0's battlefield.
    2. Run `deal_combat_damage` with a 2/2 attacker (no blocker;
       defender takes 2). This invokes the I32 write site — the
       slot is set to 2 inside the apply loop and reset to 0 after.
    3. Re-establish the slot to the dealt amount (2) — emulating
       what a future apply-loop trigger emitter would carry forward
       to the stack-pushed trigger's resolve context.
    4. Push the Starwinder Effect onto the stack and resolve. The
       Effect reads the slot and draws that many cards.

    This is the highest-fidelity end-to-end exercise of the I32
    write site we can do today without trigger-dispatch infrastructure.
    Once the apply-loop trigger emitter lands, step 3 collapses into
    the per-event write itself.
    """
    starwinder_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 0, ZONE_BATTLEFIELD
    )
    bear_id = P0_FIRST_BEAR_ID  # 2/2
    assert synthetic_state.declare_attacker(bear_id) is True
    # Step 2: real combat damage — slot transiently set to 2, then reset.
    synthetic_state.deal_combat_damage()
    assert synthetic_state.get_life(1) == 18
    assert synthetic_state.resolving_combat_damage_amount == 0
    # Step 3: re-establish to the dealt amount (emulating the carry-
    # forward a stack-pushed trigger would receive).
    synthetic_state.set_resolving_combat_damage_amount(2)
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]
    # Step 4: resolve the Starwinder Effect on the stack.
    synthetic_state.push_to_stack(starwinder_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Controller drew N == damage dealt.
    assert synthetic_state.hand_sizes[0] == p0_hand_before + 2, (
        "I32 cross-engine: Starwinder Effect should draw N cards where "
        f"N == damage dealt (2); got hand growth "
        f"{synthetic_state.hand_sizes[0] - p0_hand_before}"
    )
    assert synthetic_state.library_sizes[0] == p0_lib_before - 2
