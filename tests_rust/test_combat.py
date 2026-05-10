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
