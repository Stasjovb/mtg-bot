"""The website's Forgetful Fish bot: a RandomAgent with three Fish cards
narrowed to the casts that make sense.

RandomAgent picks uniformly among its legal non-pass actions, so the bot
cast Mind Bend on a land for no reason, Accumulated Knowledge for a single
card when it had no land to miss, and Vision Charm at random. The rules
below narrow only those casts. Every other choice, and every random draw,
is RandomAgent's own: with no rule firing the bot plays exactly as before.

- Mind Bend / Crystal Spray (CR 612) are cast only to kill an opponent's
  Dandân. The target is that Dandân, and the new land type is one its
  controller controls none of. Dandân's "When you control no <type>,
  sacrifice this creature" is a state trigger (CR 603.8), so it dies at
  once. Never the bot's own Dandân.
- Accumulated Knowledge draws 1 plus the AK cards in the graveyards. With no
  AK in a graveyard it draws 1, so it is cast only when the bot has no land
  in hand and fewer than 8 lands in play (otherwise it would miss a land
  drop). With an AK in a graveyard it draws two or more: no limit.
- Vision Charm is cast only to sacrifice Dandân: when the opponent has more
  Dandân than the bot, or the bot's are all tapped while an opponent's is
  not. The bot always picks the land-type mode (every Island changes type,
  which sacrifices every Dandân, the bot's own included). It never picks the
  mill or artifact mode; those are left to the learning loop.

Shortcuts are listed in docs/SEARCH_LIMITATIONS.md ("Forgetful Fish
website bot").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.game import effective_card_types, effective_subtypes

DANDAN = "Dandân"
TEXT_CHANGE_CARDS = frozenset({"Mind Bend", "Crystal Spray"})
ACCUMULATED_KNOWLEDGE = "Accumulated Knowledge"
VISION_CHARM = "Vision Charm"
LAND_LIMIT = 8
# The new land type of a kill: Dandân's words are "Island", which only
# change to another basic type.
KILL_TYPES = ("Plains", "Mountain", "Swamp", "Forest")


def _hand_card(state, player_id: int, card_id: int):
    return next(
        (c for c in state.player_by_id(player_id).hand if c.id == card_id), None,
    )


def _battlefield_object(state, object_id: int):
    return next((o for o in state.battlefield if o.id == object_id), None)


def _is_land(state, obj) -> bool:
    return "Land" in effective_card_types(state, obj)


def _mode_index(options, matches) -> int | None:
    return next((i for i, text in enumerate(options) if matches(text)), None)


def _kill_type(state, dandan) -> str | None:
    """The basic land type its controller controls none of, so that the
    Dandân's sacrifice holds once its text reads that type; None when the
    controller has every one of them."""
    present = {
        s for o in state.battlefield if o.controller_id == dandan.controller_id
        for s in effective_subtypes(state, o)
    }
    return next((t for t in KILL_TYPES if t not in present), None)


def _killable_dandans(state, player_id: int) -> list:
    return [
        o for o in state.battlefield
        if o.printing.name == DANDAN and o.controller_id != player_id
        and _kill_type(state, o) is not None
    ]


def _accumulated_knowledge_ok(state, player_id: int) -> bool:
    if any(
        c.printing.name == ACCUMULATED_KNOWLEDGE
        for g in state.distinct_graveyards() for c in g
    ):
        return True  # it draws two or more
    hand = state.player_by_id(player_id).hand
    if any(_is_land(state, c) for c in hand):
        return False  # a land in hand: no land drop to miss
    lands_in_play = sum(
        1 for o in state.battlefield
        if o.controller_id == player_id and _is_land(state, o)
    )
    return lands_in_play < LAND_LIMIT


def _vision_charm_kills(state, player_id: int) -> bool:
    """Whether Vision Charm's land-type mode pays. It sacrifices every
    Dandân (no Island is left), so it is worth its card when the opponent
    has more of them, or when the bot's are all tapped while an opponent's
    is not (the user's rule)."""
    dandans = [o for o in state.battlefield if o.printing.name == DANDAN]
    mine = [o for o in dandans if o.controller_id == player_id]
    theirs = [o for o in dandans if o.controller_id != player_id]
    if len(theirs) > len(mine):
        return True
    return (
        bool(mine)
        and all(o.tapped for o in mine)
        and any(not o.tapped for o in theirs)
    )


def _rule_allows(state, player_id: int, action) -> bool:
    """Whether the bot may take ``action`` under the Fish card rules."""
    if not isinstance(action, CastSpell):
        return True
    card = _hand_card(state, player_id, action.card_id)
    if card is None:
        return True
    name = card.printing.name
    if name == VISION_CHARM:
        return _vision_charm_kills(state, player_id)
    if name in TEXT_CHANGE_CARDS:
        return bool(_killable_dandans(state, player_id))
    if name == ACCUMULATED_KNOWLEDGE:
        return _accumulated_knowledge_ok(state, player_id)
    return True


@dataclass
class FishBotAgent(RandomAgent):
    """RandomAgent under the Forgetful Fish card rules (module docstring)."""

    # Set when the chosen cast is a text-changing card: its target is the
    # Dandân that the cast kills (see choose_target).
    _text_change_cast: bool = field(default=False, init=False, repr=False)
    # The Dandân chosen as the target, whose kill type choose_mode uses.
    _text_target: int | None = field(default=None, init=False, repr=False)
    # Set when the chosen cast is Vision Charm: its mode is chosen next.
    _vision_charm_cast: bool = field(default=False, init=False, repr=False)
    # Set once Vision Charm's land-type mode is chosen: its resolution
    # names the Island -> X pair next.
    _vision_land_pending: bool = field(default=False, init=False, repr=False)

    def choose_action(self, state, player_id, legal):
        self._text_change_cast = False
        self._vision_charm_cast = False
        allowed = [
            a for a in legal
            if not isinstance(a, PassPriority) and _rule_allows(state, player_id, a)
        ]
        if not allowed:
            return PassPriority()
        pick = self.rng.choice(allowed)
        if isinstance(pick, CastSpell):
            card = _hand_card(state, player_id, pick.card_id)
            name = card.printing.name if card is not None else None
            self._text_change_cast = name in TEXT_CHANGE_CARDS
            self._vision_charm_cast = name == VISION_CHARM
        return pick

    def choose_target(self, state, player_id, legal_targets):
        if not self._text_change_cast:
            return super().choose_target(state, player_id, legal_targets)
        self._text_change_cast = False
        killable = {o.id: o for o in _killable_dandans(state, player_id)}
        for target in legal_targets:
            kind, tid = target
            if kind == "permanent" and tid in killable:
                self._text_target = tid
                return target
        return None

    def choose_mode(self, state, player_id, mode_descriptions):
        target_id, self._text_target = self._text_target, None
        if target_id is not None:
            dandan = _battlefield_object(state, target_id)
            kill = _kill_type(state, dandan) if dandan is not None else None
            if kill is not None:
                index = _mode_index(
                    mode_descriptions, lambda text: text == f"Island -> {kill}",
                )
                if index is not None:
                    return index
        if self._vision_charm_cast:
            # Cast time: the land-type mode is the one that kills.
            self._vision_charm_cast = False
            index = _mode_index(mode_descriptions, lambda text: "land type" in text)
            if index is not None:
                self._vision_land_pending = True
                return index
        if self._vision_land_pending:
            # Resolution: Island -> one basic type.
            self._vision_land_pending = False
            index = _mode_index(
                mode_descriptions, lambda text: text.startswith("Island -> "),
            )
            if index is not None:
                return index
        return super().choose_mode(state, player_id, mode_descriptions)
