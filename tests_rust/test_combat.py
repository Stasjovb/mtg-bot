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
