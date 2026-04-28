"""Scuttlemutt + White Knight — exercises CR 613 layer 5
(color-changing effects) with a meaningful underlying mechanic
(protection-from-color enforced in combat block legality).

Cards (real Magic, outside the EoE pool, in
``mtg_bot.cards.demo_layers``):

- ``WHITE_KNIGHT`` — 2/2 white Knight with first strike and
  protection from black. The protection clause is wired as
  ``CardPrinting.protection_from_color="B"``; combat ``can_block``
  reads ``effective_protection_from_colors`` (printing-derived)
  and rejects blocks from creatures whose ``effective_colors``
  intersects.
- ``SCUTTLEMUTT`` — 3/3 Scarecrow with ``{T}: Target creature
  becomes the color or colors of your choice until end of turn.``
  Activation writes a layer-5 ``"set_colors"`` registry entry
  with ``expires_at="cleanup"``; the entry REPLACES the target's
  printing-derived color set.

Pinned behavior:

- A printed-black creature (Grave Brute) cannot block White
  Knight — protection from black rejects.
- After Scuttlemutt activates and picks white, Grave Brute
  becomes white. Now ``can_block`` allows the block.
- After cleanup, the layer-5 entry is dropped; Grave Brute
  reverts to black; the block is rejected again.
- Multiple Scuttlemutt activations stack by timestamp: the
  most-recent ``set_colors`` entry wins (since "set" replaces).
- ``effective_colors`` of an unaffected creature is just its
  printing-derived color set.
"""

from __future__ import annotations

from mtg_bot.actions import drain_stack, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.demo_layers import SCUTTLEMUTT, WHITE_KNIGHT
from mtg_bot.combat import can_block
from mtg_bot.effects.generic import ScuttlemuttColorChangeUEOT
from mtg_bot.game import (
    GameState, Player, StackItem, Zone,
    effective_colors, effective_protection_from_colors,
)
from mtg_bot.turn import Step, run_cleanup_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickColor(Agent):
    """Agent that picks a fixed color from choose_mana_color and the
    first legal target."""

    def __init__(self, color: str = "W"):
        self.color = color

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return self.color if self.color in options else options[0]

    # Cleanup invokes turn machinery that may try to discard; provide
    # safe stubs so the test isn't tripped up by NotImplementedError.
    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0] if hand_card_ids else -1


def _new_state(agent: Agent | None = None) -> GameState:
    state = GameState()
    a = agent or _PickColor("W")
    state.players.append(Player(id=0, agent=a))
    state.players.append(Player(id=1, agent=a))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------- Printing shape ----------


def test_white_knight_printing_shape():
    assert WHITE_KNIGHT.is_creature is True
    assert WHITE_KNIGHT.power == 2
    assert WHITE_KNIGHT.toughness == 2
    assert "first strike" in WHITE_KNIGHT.keywords
    assert WHITE_KNIGHT.protection_from_color == "B"
    # White Knight is white.
    assert "W" in WHITE_KNIGHT.mana_cost.colors


def test_scuttlemutt_printing_shape():
    assert SCUTTLEMUTT.is_creature is True
    assert SCUTTLEMUTT.power == 3
    assert SCUTTLEMUTT.toughness == 3
    assert "Scarecrow" in SCUTTLEMUTT.subtypes
    assert len(SCUTTLEMUTT.activated_abilities) == 1
    assert isinstance(
        SCUTTLEMUTT.activated_abilities[0].effect, ScuttlemuttColorChangeUEOT
    )


def test_demo_layers_not_in_eoe_pool():
    """Demo-only cards must not leak into _PRINTINGS."""
    assert "White Knight" not in _PRINTINGS
    assert "Scuttlemutt" not in _PRINTINGS
    assert "White Knight" not in _PRINTINGS
    assert "Scuttlemutt" not in _PRINTINGS


# ---------- effective_colors / effective_protection_from_colors ----------


def test_effective_colors_default_from_mana_cost():
    """Without any layer-5 entries, ``effective_colors`` returns the
    printing-derived color set."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    assert effective_colors(state, bear) == frozenset({"G"})


def test_effective_protection_default_from_printing():
    """Printed protection populates the read."""
    state = _new_state()
    knight = _put(state, WHITE_KNIGHT, owner_id=0)
    assert effective_protection_from_colors(state, knight) == \
        frozenset({"B"})


def test_effective_protection_empty_when_no_printed_protection():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    assert effective_protection_from_colors(state, bear) == frozenset()


# ---------- Layer 5 registry: set_colors via Scuttlemutt ----------


def test_scuttlemutt_writes_layer5_set_colors_entry():
    """Resolving Scuttlemutt's effect writes a layer-5
    ``set_colors`` entry with ``expires_at="cleanup"``."""
    state = _new_state(agent=_PickColor("W"))
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    ScuttlemuttColorChangeUEOT().resolve(
        state, controller_id=0,
        targets=(("creature", grave_brute.id),),
    )

    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 5 and ce.kind == "set_colors"
    ]
    assert len(entries) == 1
    assert entries[0].source_id == scuttle.id
    assert entries[0].target_id == grave_brute.id
    assert entries[0].params == (frozenset({"W"}),)
    assert entries[0].expires_at == "cleanup"


def test_scuttlemutt_changes_effective_colors():
    """Effective colors flip from printed black to the chosen color."""
    state = _new_state(agent=_PickColor("R"))
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)
    assert effective_colors(state, grave_brute) == frozenset({"B"})
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    ScuttlemuttColorChangeUEOT().resolve(
        state, controller_id=0,
        targets=(("creature", grave_brute.id),),
    )

    assert effective_colors(state, grave_brute) == frozenset({"R"})


def test_set_colors_replaces_not_unions():
    """``set_colors`` REPLACES — a previously-black creature picked
    to be white is white, not white-and-black."""
    state = _new_state(agent=_PickColor("W"))
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", grave_brute.id),),
    )

    colors = effective_colors(state, grave_brute)
    assert "W" in colors
    assert "B" not in colors


# ---------- Combat: protection from color rejects block ----------


def test_white_knight_attacked_by_black_creature_block_rejected():
    """White Knight has protection from black: Grave Brute cannot
    legally block it."""
    state = _new_state()
    knight = _put(state, WHITE_KNIGHT, owner_id=0)
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)

    assert can_block(state, blocker=grave_brute, attacker=knight) is False


def test_scuttlemutt_makes_black_creature_white_block_now_legal():
    """After Scuttlemutt makes the black creature white, the block
    becomes legal — protection from black no longer applies."""
    state = _new_state(agent=_PickColor("W"))
    knight = _put(state, WHITE_KNIGHT, owner_id=0)
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    # Pre-change: block rejected.
    assert can_block(state, blocker=grave_brute, attacker=knight) is False

    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", grave_brute.id),),
    )

    # Post-change: block allowed.
    assert can_block(state, blocker=grave_brute, attacker=knight) is True


def test_protection_does_not_reject_non_matching_color_blocker():
    """Non-black creatures are unaffected by protection from black."""
    state = _new_state()
    knight = _put(state, WHITE_KNIGHT, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)

    assert can_block(state, blocker=bear, attacker=knight) is True


def test_block_rejected_when_block_target_has_no_protection():
    """A creature without protection-from-color uses the default
    block-legality path. (Pin that we didn't accidentally add a
    universal restriction.)"""
    state = _new_state()
    bear_attacker = _put(
        state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
    )
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)

    assert can_block(
        state, blocker=grave_brute, attacker=bear_attacker
    ) is True


# ---------- Cleanup expiration ----------


def test_color_change_reverts_at_cleanup():
    """The layer-5 entry has ``expires_at="cleanup"``; running the
    cleanup step drops it and the target reverts to its printed
    colors."""
    state = _new_state(agent=_PickColor("W"))
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=0)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", grave_brute.id),),
    )
    assert effective_colors(state, grave_brute) == frozenset({"W"})

    state.expire_continuous_effects("cleanup")

    assert effective_colors(state, grave_brute) == frozenset({"B"})
    # Block legality also reverts.
    knight = _put(state, WHITE_KNIGHT, owner_id=1)
    assert can_block(state, blocker=grave_brute, attacker=knight) is False


# ---------- Multiple activations: most-recent timestamp wins ----------


def test_two_scuttlemutt_activations_most_recent_set_wins():
    """Two activations on the same target: T1 sets {W}, T2 sets {R}.
    Both entries exist, both have expires_at='cleanup', but the
    most-recent timestamp (T2's red) is the effective color set."""
    state = _new_state()
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=0)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.resolving_source = scuttle

    state.players[0].agent = _PickColor("W")
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", grave_brute.id),),
    )
    state.players[0].agent = _PickColor("R")
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", grave_brute.id),),
    )

    assert effective_colors(state, grave_brute) == frozenset({"R"})
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 5 and ce.kind == "set_colors"
        and ce.target_id == grave_brute.id
    ]
    assert len(entries) == 2  # both retained
    assert entries[0].timestamp < entries[1].timestamp
    assert entries[1].params == (frozenset({"R"}),)


# ---------- Activated-ability path through legal_actions ----------


def test_scuttlemutt_resolves_via_full_stack_pipeline():
    """Drive Scuttlemutt's ability through the stack — verify the
    layer-5 entry lands and the target's effective colors flip."""
    from mtg_bot.actions import push_triggered_ability

    state = _new_state(agent=_PickColor("W"))
    grave_brute = _put(state, SYNTHETIC_CREATURES["Grave Brute"], owner_id=1)
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.stack.append(StackItem(
        source=scuttle,
        controller_id=0,
        ability=SCUTTLEMUTT.activated_abilities[0],
        targets=(("creature", grave_brute.id),),
    ))
    resolve_top_of_stack(state)
    drain_stack(state)

    assert effective_colors(state, grave_brute) == frozenset({"W"})
