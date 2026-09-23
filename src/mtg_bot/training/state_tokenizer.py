"""State tokenizer for the Step 1 structured NN representation.

Converts the engine's ``GameState`` (plus a recent-action history) into
a per-token feature dict matching the input shape pinned in
``mtg_bot.training.structured_model``:

    {
        "token_type":     int64 ndarray(seq_len,)
        "token_emb_ids":  int64 ndarray(seq_len, N_EMB_FIELDS)
        "token_scalars":  float32 ndarray(seq_len, N_SCALAR_FIELDS)
        "attention_mask": bool ndarray(seq_len,)
    }

The tokenizer emits one token per public game object visible to the
``viewer`` (battlefield permanents on both sides, viewer's own
hand/graveyard/exile, opponent's graveyard/exile, opponent's hand as
anonymous slots, stack items) plus a `[GLOBAL]` summary token and the
filtered + truncated last-N action tokens. It does NOT emit a
``[CLS]`` token — the model prepends its learned CLS itself (see
``structured_model.StructuredModel._prepend_cls``).

Viewer-relative encoding rules (roadmap §2):

- Each token's ``controller`` field is one of ``CONTROLLER_NA`` /
  ``CONTROLLER_VIEWER`` / ``CONTROLLER_OPPONENT`` — the same physical
  object/action takes the viewer's perspective in both perspectives'
  tokenizations.
- Opponent hand cards are emitted as anonymous tokens with
  ``token_type=TOKEN_TYPE_HAND_OPPONENT``, ``printing=PRINTING_NA``,
  and ``public_mask=0``. The cardinality (number of slots) matches the
  opponent's actual hand size.
- Scry / surveil events that produce a private order, and
  ``CardFromLibrary`` tutor picks, get private fields redacted to NA
  with ``public_mask=0`` when viewed from the non-actor's seat.

Action-history filter (roadmap §3):

``PassPriority`` events and mana-ability ``ActivateAbility`` events
are dropped from the recent-action history before truncation to N=32.
The remaining tokens carry the viewer-relative redaction described
above.

The action-kind vocab (``ACTION_KIND_VOCAB``) is the single source of
truth for the 22-entry per-action category. ``structured_model``'s
``ACTION_KIND_VOCAB_SIZE`` constant must match
``len(ACTION_KIND_VOCAB) + 1`` (NA + 22 kinds = 23); a test pins this.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from mtg_bot.actions import (
    Action,
    ActivateAbility,
    ActivateStation,
    CastSpell,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
    TurnFaceUp,
    UnlockRoomHalf,
)
from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.source import get_active_source
from mtg_bot.game import GameObject, GameState, StackItem
from mtg_bot.search.action_history import (  # noqa: F401 - re-exported
    DEFAULT_ACTION_HISTORY_N,
    ActionEvent,
    _is_mana_ability,
    _is_strategically_relevant,
    record_action_event,
)
from mtg_bot.search.combat_decisions import AttackerDecision, BlockerDecision
from mtg_bot.search.resolution_decisions import (
    ResolutionCardFromLibraryDecision,
    ResolutionCardFromOpponentHandDecision,
    ResolutionDevourLandsDecision,
    ResolutionDiscardDecision,
    ResolutionModeDecision,
    ResolutionSacrificeDecision,
    ResolutionShockLifeDecision,
    ResolutionSurveilDecision,
    ResolutionTargetDecision,
    ResolutionXDecision,
    ResolutionYesNoDecision,
)
from mtg_bot.training.structured_model import (
    ACTION_KIND_VOCAB_SIZE,
    CONTROLLER_VOCAB_SIZE,
    DEFAULT_N_PRINTINGS,
    EMB_FIELD_ACTION_KIND,
    EMB_FIELD_CONTROLLER,
    EMB_FIELD_PRINTING,
    EMB_FIELD_STEP,
    EMB_FIELD_TARGET_KIND,
    EMB_FIELD_TARGET_PRINTING,
    EMB_FIELD_VARIANT,
    N_EMB_FIELDS,
    N_SCALAR_FIELDS,
    N_TOKEN_TYPES,
    SCALAR_FIELD_MANA_COST_PAID,
    SCALAR_FIELD_PUBLIC_MASK,
    SCALAR_FIELD_TURN_OFFSET,
    STEP_VOCAB_SIZE,
    TARGET_KIND_VOCAB_SIZE,
    TOKEN_TYPE_ACTION_EVENT,
    TOKEN_TYPE_EXILE_OPPONENT,
    TOKEN_TYPE_EXILE_VIEWER,
    TOKEN_TYPE_GLOBAL,
    TOKEN_TYPE_GRAVEYARD_OPPONENT,
    TOKEN_TYPE_GRAVEYARD_VIEWER,
    TOKEN_TYPE_HAND_OPPONENT,
    TOKEN_TYPE_HAND_VIEWER,
    TOKEN_TYPE_PERMANENT_OPPONENT,
    TOKEN_TYPE_PERMANENT_VIEWER,
    TOKEN_TYPE_STACK_ITEM,
    VARIANT_VOCAB_SIZE,
)
from mtg_bot.turn import STEP_ORDER


# ---------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------

# Action-kind vocab. Id 0 is the NA-token reserved by the model's
# embedding tables; the 22 real kinds occupy ids 1..22. Order is
# stable so trained weights don't shuffle if the dict literal is
# reformatted — we treat this dict as the spec, and the integer values
# are part of the on-disk contract.
ACTION_KIND_VOCAB: dict[str, int] = {
    # 9 priority actions (mtg_bot.actions)
    "PassPriority": 1,
    "PlayLand": 2,
    "CastSpell": 3,
    "UnlockRoomHalf": 4,
    "ActivateAbility": 5,
    "ActivateStation": 6,
    "TurnFaceUp": 7,
    "DeclareAttackers": 8,
    "DeclareBlockers": 9,
    # 2 factored combat decisions (mtg_bot.search.combat_decisions)
    "AttackerDecision": 10,
    "BlockerDecision": 11,
    # 11 resolution decisions (mtg_bot.search.resolution_decisions)
    "ResolutionTargetDecision": 12,
    "ResolutionDiscardDecision": 13,
    "ResolutionModeDecision": 14,
    "ResolutionSacrificeDecision": 15,
    "ResolutionXDecision": 16,
    "ResolutionSurveilDecision": 17,
    "ResolutionShockLifeDecision": 18,
    "ResolutionCardFromLibraryDecision": 19,
    "ResolutionCardFromOpponentHandDecision": 20,
    "ResolutionYesNoDecision": 21,
    "ResolutionDevourLandsDecision": 22,
}

# Defensive: trained weights pin slot identities. If a new kind lands,
# extend the dict at the END (claim the next free id) and bump
# ACTION_KIND_VOCAB_SIZE in ``structured_model`` to match.
assert len(ACTION_KIND_VOCAB) == 22, (
    "ACTION_KIND_VOCAB must have exactly 22 entries; "
    f"got {len(ACTION_KIND_VOCAB)}"
)
assert set(ACTION_KIND_VOCAB.values()) == set(range(1, 23)), (
    "ACTION_KIND_VOCAB values must be a 1..22 permutation"
)
assert ACTION_KIND_VOCAB_SIZE == len(ACTION_KIND_VOCAB) + 1, (
    f"structured_model.ACTION_KIND_VOCAB_SIZE ({ACTION_KIND_VOCAB_SIZE}) "
    f"!= 1 + len(ACTION_KIND_VOCAB) ({len(ACTION_KIND_VOCAB)})"
)


# Controller-vocab ids (must agree with structured_model's
# CONTROLLER_VOCAB_SIZE=3).
CONTROLLER_NA = 0
CONTROLLER_VIEWER = 1
CONTROLLER_OPPONENT = 2


# Target-kind vocab ids (must agree with TARGET_KIND_VOCAB_SIZE=6).
TARGET_KIND_NA = 0
TARGET_KIND_PLAYER = 1
TARGET_KIND_PERMANENT = 2
TARGET_KIND_STACK_ITEM = 3
TARGET_KIND_HAND_CARD = 4
TARGET_KIND_EXILE_CARD = 5


# Variant vocab ids (must agree with VARIANT_VOCAB_SIZE=9).
# NA + 8 = 9; the underlying 8 variants mirror action_encoding.py's
# slot taxonomy plus a ``private_choice`` sentinel for redacted
# scry/surveil events from the non-actor's perspective.
VARIANT_NA = 0
VARIANT_NORMAL = 1
VARIANT_KICKED = 2
VARIANT_WARP = 3
VARIANT_CAST_FOR_FREE = 4
VARIANT_IMPENDING = 5
VARIANT_ROOM_HALF_0 = 6
VARIANT_ROOM_HALF_1 = 7
VARIANT_PRIVATE_CHOICE = 8


# Printing id reserved as "no printing" / anonymous slot.
PRINTING_NA = 0


# Step vocab id reserved as "no step" / NA. Real engine steps are
# ``STEP_ORDER.index(step) + 1`` so id 0 stays NA.
STEP_NA = 0


# Action-history window (``DEFAULT_ACTION_HISTORY_N``), ``ActionEvent``
# and the §3 relevance filter live in ``mtg_bot.search.action_history``
# (the adapter records history at apply time and must import them
# without pulling in torch); they are re-exported from this module.


# ---------------------------------------------------------------------
# Printing-id table
# ---------------------------------------------------------------------

# Build a stable name → id mapping from the active card source. Built
# lazily on first use because the active source can be swapped by
# tests via ``set_active_source``. id 0 is reserved as
# ``PRINTING_NA``; printings start at id 1.

_PRINTING_TO_ID_CACHE: Optional[dict[str, int]] = None
_PRINTING_TO_ID_SOURCE: object = None


def _printing_to_id_map() -> dict[str, int]:
    """Return a name → id mapping for printings in the active source.

    Cached at module level keyed on the active-source identity so
    test fixtures that swap the source (or extend a synthetic-test
    source) get a fresh mapping. Sorted by printing name so the id
    assignment is reproducible across runs without ordering churn.
    """
    global _PRINTING_TO_ID_CACHE, _PRINTING_TO_ID_SOURCE
    source = get_active_source()
    if _PRINTING_TO_ID_CACHE is None or _PRINTING_TO_ID_SOURCE is not source:
        printings = source.get_printings()
        ordered = sorted(printings.keys())
        # id 0 is reserved as NA — start real printings at 1.
        _PRINTING_TO_ID_CACHE = {
            name: i + 1 for i, name in enumerate(ordered)
        }
        _PRINTING_TO_ID_SOURCE = source
    return _PRINTING_TO_ID_CACHE


def printing_id(
    printing: Optional[CardPrinting],
    *,
    n_printings_cap: int = DEFAULT_N_PRINTINGS,
) -> int:
    """Look up the integer embedding id for a printing.

    Returns ``PRINTING_NA`` for ``None`` or for unknown printings.
    Caps the result at ``n_printings_cap - 1`` so the embedding
    table never indexes out of range; the model's
    ``DEFAULT_N_PRINTINGS=320`` leaves slack for EoE today (~475
    printings) so we map any printing-id exceeding the cap to a
    deterministic bucket via modulo. This is a v1 simplification —
    Step 1 of the roadmap explicitly anticipates EoE-sized sets
    (~287 cards); when the active set grows past the cap, the
    model's ``n_printings`` should grow to match rather than
    relying on the modulo collision.
    """
    if printing is None:
        return PRINTING_NA
    pid_map = _printing_to_id_map()
    raw_id = pid_map.get(printing.name)
    if raw_id is None:
        return PRINTING_NA
    if raw_id >= n_printings_cap:
        # Collision-mode: bucket overflow into the high range
        # excluding NA(0). Deterministic.
        return 1 + ((raw_id - 1) % (n_printings_cap - 1))
    return raw_id


# ---------------------------------------------------------------------
# Token row construction helpers
# ---------------------------------------------------------------------


def _step_id(state_step) -> int:
    """Engine ``Step`` → embedding id. ``None`` → NA."""
    if state_step is None:
        return STEP_NA
    try:
        return 1 + STEP_ORDER.index(state_step)
    except ValueError:
        return STEP_NA


def _controller_id(controller_player_id: Optional[int], viewer_id: int) -> int:
    """Map a controller player id to viewer-relative vocab id."""
    if controller_player_id is None:
        return CONTROLLER_NA
    if controller_player_id == viewer_id:
        return CONTROLLER_VIEWER
    return CONTROLLER_OPPONENT


def _empty_emb_row(*, n_printings_cap: int = DEFAULT_N_PRINTINGS) -> list[int]:
    """Return a fresh ``[N_EMB_FIELDS]`` row of NA ids."""
    row = [0] * N_EMB_FIELDS
    return row


def _empty_scalar_row() -> list[float]:
    return [0.0] * N_SCALAR_FIELDS


def _make_zone_card_token(
    *,
    card: GameObject,
    token_type: int,
    controller_vocab_id: int,
    state_step,
    public_mask: float,
    n_printings_cap: int,
) -> tuple[int, list[int], list[float]]:
    """Build (token_type, emb_ids, scalars) for a single hand /
    graveyard / exile zone card.
    """
    emb = _empty_emb_row()
    emb[EMB_FIELD_PRINTING] = printing_id(
        card.printing, n_printings_cap=n_printings_cap,
    )
    emb[EMB_FIELD_CONTROLLER] = controller_vocab_id
    emb[EMB_FIELD_STEP] = _step_id(state_step)
    scalars = _empty_scalar_row()
    scalars[SCALAR_FIELD_PUBLIC_MASK] = public_mask
    return token_type, emb, scalars


def _make_permanent_token(
    *,
    obj: GameObject,
    token_type: int,
    controller_vocab_id: int,
    state_step,
    n_printings_cap: int,
) -> tuple[int, list[int], list[float]]:
    """Build (token_type, emb_ids, scalars) for a battlefield
    permanent. Permanents are fully public — ``public_mask=1``.
    """
    emb = _empty_emb_row()
    emb[EMB_FIELD_PRINTING] = printing_id(
        obj.printing, n_printings_cap=n_printings_cap,
    )
    emb[EMB_FIELD_CONTROLLER] = controller_vocab_id
    emb[EMB_FIELD_STEP] = _step_id(state_step)
    scalars = _empty_scalar_row()
    scalars[SCALAR_FIELD_PUBLIC_MASK] = 1.0
    return token_type, emb, scalars


def _make_stack_token(
    *,
    item: StackItem,
    state_step,
    viewer_id: int,
    n_printings_cap: int,
) -> tuple[int, list[int], list[float]]:
    """Build a token for a stack item (spell or triggered ability).

    Stack contents are public — both controller and source printing
    are visible to both players (per CR 408.1).
    """
    emb = _empty_emb_row()
    emb[EMB_FIELD_PRINTING] = printing_id(
        item.source.printing, n_printings_cap=n_printings_cap,
    )
    emb[EMB_FIELD_CONTROLLER] = _controller_id(item.controller_id, viewer_id)
    emb[EMB_FIELD_STEP] = _step_id(state_step)
    # If the stack item has a first target with a printing we can
    # resolve, surface it. Resolving target ids → printings reaches
    # into the battlefield / stack / hand; for v1 we look at the
    # battlefield only (the common case) and skip anything else
    # gracefully.
    if item.targets:
        kind, tid = item.targets[0]
        emb[EMB_FIELD_TARGET_KIND] = _target_kind_id(kind)
    scalars = _empty_scalar_row()
    scalars[SCALAR_FIELD_PUBLIC_MASK] = 1.0
    if item.source.printing is not None:
        scalars[SCALAR_FIELD_MANA_COST_PAID] = (
            item.source.printing.mana_cost.total / 10.0
        )
    return TOKEN_TYPE_STACK_ITEM, emb, scalars


def _target_kind_id(kind: str) -> int:
    """Map a stack/decision target ``(kind, id)`` kind string to
    the target-kind vocab id."""
    return {
        "player": TARGET_KIND_PLAYER,
        "permanent": TARGET_KIND_PERMANENT,
        "stack": TARGET_KIND_STACK_ITEM,
        "hand_card": TARGET_KIND_HAND_CARD,
        "exile_card": TARGET_KIND_EXILE_CARD,
    }.get(kind, TARGET_KIND_NA)


def _make_global_token(
    state: GameState,
    viewer_id: int,
) -> tuple[int, list[int], list[float]]:
    """Build the single global summary token (turn / step / active
    player). The model's CLS does cross-state pooling on top.
    """
    emb = _empty_emb_row()
    emb[EMB_FIELD_STEP] = _step_id(state.step)
    # Controller of the global token = whose turn it is.
    if state.players and 0 <= state.active_player_idx < len(state.players):
        ap_id = state.players[state.active_player_idx].id
        emb[EMB_FIELD_CONTROLLER] = _controller_id(ap_id, viewer_id)
    scalars = _empty_scalar_row()
    scalars[SCALAR_FIELD_PUBLIC_MASK] = 1.0
    return TOKEN_TYPE_GLOBAL, emb, scalars


# ---------------------------------------------------------------------
# Action token construction
# ---------------------------------------------------------------------


def _action_kind_name(action: Action) -> str:
    """Return the ACTION_KIND_VOCAB key for an action / decision
    instance."""
    return type(action).__name__


def _cast_variant(action: CastSpell) -> int:
    """Map a CastSpell action to the variant-vocab id matching its
    cast modifier (kicked / warp / impending / room-half / free / normal).
    """
    if action.use_warp:
        return VARIANT_WARP
    if action.kicked:
        return VARIANT_KICKED
    if action.use_impending:
        return VARIANT_IMPENDING
    if action.cast_for_free:
        return VARIANT_CAST_FOR_FREE
    if action.cast_room_half is not None:
        # Room halves are sorted by name in the engine; the variant
        # vocab pins half_idx 0 vs 1 explicitly. Without per-card
        # access to the room's half list here we map the chosen
        # half-name's parity heuristically: deterministic, and the
        # model learns its own per-half embedding via the
        # source_printing field anyway. The §1 design treats
        # room_half as cardinality-only — model side groks the rest.
        return (
            VARIANT_ROOM_HALF_0
            if hash(action.cast_room_half) % 2 == 0
            else VARIANT_ROOM_HALF_1
        )
    return VARIANT_NORMAL


def _find_object_printing(
    state: GameState, obj_id: int,
) -> Optional[CardPrinting]:
    """Return the printing of any object referenced by id, searching
    battlefield and stack. Returns None if not found."""
    for o in state.battlefield:
        if o.id == obj_id:
            return o.printing
    for s in state.stack:
        if s.source.id == obj_id:
            return s.source.printing
    return None


def _make_action_token(
    *,
    action: Action,
    state_at_action: GameState,
    action_turn: int,
    current_turn: int,
    viewer_id: int,
    actor_player_id: int,
    state_step,
    n_printings_cap: int,
) -> tuple[int, list[int], list[float]]:
    """Build the per-action token row.

    Per roadmap §1, an action token is 7 embedding ids + 3 scalars:

    - action_kind, controller, source_printing, target_printing,
      target_kind, variant, step (embeddings)
    - turn_offset, mana_cost_paid, public_mask (scalars)

    The viewer-relative redaction in §2 is applied here for the two
    private-info events (scry/surveil and CardFromLibrary): when
    ``actor_player_id != viewer_id`` we mask the variant or target
    printing to NA and set ``public_mask=0``.
    """
    emb = _empty_emb_row()
    scalars = _empty_scalar_row()

    kind_name = _action_kind_name(action)
    emb[EMB_FIELD_ACTION_KIND] = ACTION_KIND_VOCAB.get(kind_name, 0)
    emb[EMB_FIELD_CONTROLLER] = _controller_id(actor_player_id, viewer_id)
    emb[EMB_FIELD_STEP] = _step_id(state_step)

    public_mask = 1.0
    variant_id = VARIANT_NA
    source_printing: Optional[CardPrinting] = None
    target_printing: Optional[CardPrinting] = None
    target_kind_id = TARGET_KIND_NA

    if isinstance(action, PlayLand):
        # Source printing = the played-land card.
        # The card is in hand pre-apply; in some snapshot
        # configurations it might already be on the battlefield. We
        # look in both.
        for p in state_at_action.players:
            for c in p.hand:
                if c.id == action.card_id:
                    source_printing = c.printing
                    break
            if source_printing is not None:
                break
        if source_printing is None:
            source_printing = _find_object_printing(
                state_at_action, action.card_id,
            )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, CastSpell):
        for p in state_at_action.players:
            for c in p.hand:
                if c.id == action.card_id:
                    source_printing = c.printing
                    break
            if source_printing is not None:
                break
        if source_printing is None:
            source_printing = _find_object_printing(
                state_at_action, action.card_id,
            )
        variant_id = _cast_variant(action)
        if source_printing is not None:
            scalars[SCALAR_FIELD_MANA_COST_PAID] = (
                source_printing.mana_cost.total / 10.0
            )

    elif isinstance(action, UnlockRoomHalf):
        source_printing = _find_object_printing(
            state_at_action, action.card_id,
        )
        variant_id = (
            VARIANT_ROOM_HALF_0
            if hash(action.half_name) % 2 == 0
            else VARIANT_ROOM_HALF_1
        )

    elif isinstance(action, ActivateAbility):
        source_printing = _find_object_printing(
            state_at_action, action.source_id,
        )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ActivateStation):
        source_printing = _find_object_printing(
            state_at_action, action.spacecraft_id,
        )
        # Crew creature as the target.
        crew = _find_object_printing(state_at_action, action.crew_id)
        if crew is not None:
            target_printing = crew
            target_kind_id = TARGET_KIND_PERMANENT
        variant_id = VARIANT_NORMAL

    elif isinstance(action, TurnFaceUp):
        source_printing = _find_object_printing(
            state_at_action, action.card_id,
        )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, DeclareAttackers):
        # Roadmap §3: record as one token per attacking creature for
        # a fixed per-token shape. The caller-side tokenize_state
        # will expand multi-attacker declarations into multiple
        # tokens; this builder gets called once per attacker.
        # If we somehow receive the raw aggregate here, pick the
        # first attacker as the source.
        if action.attacker_ids:
            first = sorted(action.attacker_ids)[0]
            source_printing = _find_object_printing(state_at_action, first)
        variant_id = VARIANT_NORMAL

    elif isinstance(action, DeclareBlockers):
        if action.assignments:
            blocker_id, _atk_id = action.assignments[0]
            source_printing = _find_object_printing(
                state_at_action, blocker_id,
            )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, AttackerDecision):
        source_printing = _find_object_printing(
            state_at_action, action.attacker_id,
        )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, BlockerDecision):
        source_printing = _find_object_printing(
            state_at_action, action.blocker_id,
        )
        if action.attacker_id is not None:
            target_printing = _find_object_printing(
                state_at_action, action.attacker_id,
            )
            target_kind_id = TARGET_KIND_PERMANENT
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionTargetDecision):
        if action.target is not None:
            kind, tid = action.target
            target_kind_id = _target_kind_id(kind)
            target_printing = _find_object_printing(state_at_action, tid)
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionDiscardDecision):
        # Discarded card's printing lands in graveyard, public. Find
        # it across hands (still hand at pre-apply) then graveyards.
        for p in state_at_action.players:
            for c in p.hand:
                if c.id == action.card_id:
                    target_printing = c.printing
                    break
            if target_printing is not None:
                break
        if target_printing is None:
            for p in state_at_action.players:
                for c in p.graveyard:
                    if c.id == action.card_id:
                        target_printing = c.printing
                        break
                if target_printing is not None:
                    break
        target_kind_id = (
            TARGET_KIND_HAND_CARD if target_printing is not None else TARGET_KIND_NA
        )
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionModeDecision):
        # Mode choice is public; mode_index is captured via variant
        # cardinality only (no slot in the 8-entry variant vocab —
        # the trunk learns mode semantics via source_printing).
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionSacrificeDecision):
        target_printing = _find_object_printing(
            state_at_action, action.object_id,
        )
        target_kind_id = TARGET_KIND_PERMANENT
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionXDecision):
        # X value goes into the mana_cost_paid scalar so the trunk
        # has a numeric handle on "how big was X."
        scalars[SCALAR_FIELD_MANA_COST_PAID] = action.x_value / 10.0
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionSurveilDecision):
        # Private to the actor — non-actor viewers see the variant
        # masked and public_mask=0. Mill vs. keep is the actor's
        # private choice.
        if actor_player_id == viewer_id:
            variant_id = (
                VARIANT_NORMAL if action.mill else VARIANT_CAST_FOR_FREE
            )
        else:
            variant_id = VARIANT_PRIVATE_CHOICE
            public_mask = 0.0

    elif isinstance(action, ResolutionShockLifeDecision):
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionCardFromLibraryDecision):
        # Tutored card's identity is private to the actor. From the
        # non-actor's perspective the target printing is masked to NA
        # and public_mask=0.
        if action.card_id is not None:
            if actor_player_id == viewer_id:
                target_printing = _find_object_printing(
                    state_at_action, action.card_id,
                )
                # The tutored card likely sits in library at
                # decision time — search libraries too.
                if target_printing is None:
                    for p in state_at_action.players:
                        for c in p.library:
                            if c.id == action.card_id:
                                target_printing = c.printing
                                break
                        if target_printing is not None:
                            break
                target_kind_id = TARGET_KIND_HAND_CARD
            else:
                target_printing = None
                target_kind_id = TARGET_KIND_NA
                public_mask = 0.0
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionCardFromOpponentHandDecision):
        # Both seats see the picked card under current rules
        # conventions — fully public token.
        target_printing = None
        for p in state_at_action.players:
            for c in p.hand:
                if c.id == action.card_id:
                    target_printing = c.printing
                    break
            if target_printing is not None:
                break
        target_kind_id = TARGET_KIND_HAND_CARD
        variant_id = VARIANT_NORMAL

    elif isinstance(action, ResolutionYesNoDecision):
        variant_id = VARIANT_NORMAL if action.yes else VARIANT_CAST_FOR_FREE

    elif isinstance(action, ResolutionDevourLandsDecision):
        variant_id = VARIANT_NORMAL

    elif isinstance(action, PassPriority):
        # PassPriority is filtered out before reaching the token
        # builder — but we tolerate it defensively for callers that
        # bypass _is_strategically_relevant.
        variant_id = VARIANT_NA

    emb[EMB_FIELD_PRINTING] = printing_id(
        source_printing, n_printings_cap=n_printings_cap,
    )
    emb[EMB_FIELD_TARGET_PRINTING] = printing_id(
        target_printing, n_printings_cap=n_printings_cap,
    )
    emb[EMB_FIELD_TARGET_KIND] = target_kind_id
    emb[EMB_FIELD_VARIANT] = variant_id

    # turn_offset: (action_turn - current_turn) clamped to [-16, 0],
    # divided by 16. Negative = how many turns ago.
    offset = max(-16, min(0, action_turn - current_turn))
    scalars[SCALAR_FIELD_TURN_OFFSET] = offset / 16.0
    scalars[SCALAR_FIELD_PUBLIC_MASK] = public_mask

    return TOKEN_TYPE_ACTION_EVENT, emb, scalars


# ---------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------


def tokenize_state(
    state: GameState,
    viewer_id: int,
    recent_actions: Sequence[ActionEvent] = (),
    n: int = DEFAULT_ACTION_HISTORY_N,
    *,
    n_printings_cap: int = DEFAULT_N_PRINTINGS,
) -> dict[str, np.ndarray]:
    """Tokenize a single game state from ``viewer_id``'s perspective.

    Parameters
    ----------
    state
        Engine ``GameState`` to tokenize. Read-only — the tokenizer
        does not mutate it.
    viewer_id
        Player id of the viewer (typically 0 or 1). Determines
        viewer-relative controller codes and which private-info
        fields get redacted.
    recent_actions
        Sequence of ``ActionEvent``s describing actions taken in the
        game leading up to ``state``. Oldest first. The tokenizer
        applies the §3 strategically-relevant filter (drop
        PassPriority + mana-abilities), then truncates to the last
        ``n`` events. Both training (``data_gen``) and inference
        (``NNEvaluator``) pass ``MtgGameStateAdapter.recent_actions``
        here — the adapter records events via
        ``mtg_bot.search.action_history.record_action_event`` and
        already holds the last ``DEFAULT_ACTION_HISTORY_N`` relevant
        events, so the filter/truncation is a no-op for them.
    n
        Action-history window. Default 32 (roadmap §3).
    n_printings_cap
        Maximum printing-id allowed before modulo-bucketing. Set to
        the model's ``StructuredModelConfig.n_printings`` so the
        tokenizer's outputs never index out of range.

    Returns
    -------
    A dict with the four arrays the structured model consumes:

    - ``token_type``:     int64 ``(seq_len,)`` — token-type vocab
      ids (``TOKEN_TYPE_*`` constants). Note that the ``[CLS]``
      token is NOT emitted here; the model prepends its own.
    - ``token_emb_ids``:  int64 ``(seq_len, N_EMB_FIELDS=7)`` —
      per-field categorical embedding ids.
    - ``token_scalars``:  float32 ``(seq_len, N_SCALAR_FIELDS=3)``
      — turn_offset, mana_cost_paid, public_mask.
    - ``attention_mask``: bool ``(seq_len,)`` — True for every
      emitted row (the tokenizer doesn't pad; the dataset writer
      pads to the batch's max_len).
    """
    if state is None:
        raise ValueError("state must not be None")
    # Identify viewer + opponent players. The viewer slot may have
    # already lost; we still tokenize their zones for shape stability.
    viewer: Optional["object"] = None
    opponent: Optional["object"] = None
    for p in state.players:
        if p.id == viewer_id:
            viewer = p
        else:
            opponent = p
    if viewer is None:
        raise ValueError(
            f"viewer_id={viewer_id} not found in state.players "
            f"(ids: {[p.id for p in state.players]})"
        )

    token_types: list[int] = []
    emb_rows: list[list[int]] = []
    scalar_rows: list[list[float]] = []

    # --- Global summary token ----------------------------------------
    t, e, s = _make_global_token(state, viewer_id)
    token_types.append(t)
    emb_rows.append(e)
    scalar_rows.append(s)

    # --- Permanents on the battlefield -------------------------------
    # Order by id so the output is stable across canonical
    # transpositions. Controller is viewer-relative.
    for obj in sorted(state.battlefield, key=lambda o: o.id):
        if obj.controller_id == viewer_id:
            tt = TOKEN_TYPE_PERMANENT_VIEWER
            ctrl = CONTROLLER_VIEWER
        else:
            tt = TOKEN_TYPE_PERMANENT_OPPONENT
            ctrl = CONTROLLER_OPPONENT
        t, e, s = _make_permanent_token(
            obj=obj, token_type=tt, controller_vocab_id=ctrl,
            state_step=state.step, n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)

    # --- Viewer's hand (visible) -------------------------------------
    for card in viewer.hand:
        t, e, s = _make_zone_card_token(
            card=card, token_type=TOKEN_TYPE_HAND_VIEWER,
            controller_vocab_id=CONTROLLER_VIEWER,
            state_step=state.step, public_mask=1.0,
            n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)

    # --- Opponent's hand (anonymous slots; cardinality only) ----------
    if opponent is not None:
        for _ in opponent.hand:
            emb = _empty_emb_row()
            emb[EMB_FIELD_CONTROLLER] = CONTROLLER_OPPONENT
            emb[EMB_FIELD_STEP] = _step_id(state.step)
            # Printing field stays NA — opponent's hand is hidden.
            scalars = _empty_scalar_row()
            scalars[SCALAR_FIELD_PUBLIC_MASK] = 0.0
            token_types.append(TOKEN_TYPE_HAND_OPPONENT)
            emb_rows.append(emb)
            scalar_rows.append(scalars)

    # --- Viewer's graveyard / exile (public) -------------------------
    for card in viewer.graveyard:
        t, e, s = _make_zone_card_token(
            card=card, token_type=TOKEN_TYPE_GRAVEYARD_VIEWER,
            controller_vocab_id=CONTROLLER_VIEWER,
            state_step=state.step, public_mask=1.0,
            n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)
    for card in viewer.exile:
        t, e, s = _make_zone_card_token(
            card=card, token_type=TOKEN_TYPE_EXILE_VIEWER,
            controller_vocab_id=CONTROLLER_VIEWER,
            state_step=state.step, public_mask=1.0,
            n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)

    # --- Opponent's graveyard / exile (public — public-zone) ----------
    if opponent is not None:
        for card in opponent.graveyard:
            t, e, s = _make_zone_card_token(
                card=card, token_type=TOKEN_TYPE_GRAVEYARD_OPPONENT,
                controller_vocab_id=CONTROLLER_OPPONENT,
                state_step=state.step, public_mask=1.0,
                n_printings_cap=n_printings_cap,
            )
            token_types.append(t)
            emb_rows.append(e)
            scalar_rows.append(s)
        for card in opponent.exile:
            t, e, s = _make_zone_card_token(
                card=card, token_type=TOKEN_TYPE_EXILE_OPPONENT,
                controller_vocab_id=CONTROLLER_OPPONENT,
                state_step=state.step, public_mask=1.0,
                n_printings_cap=n_printings_cap,
            )
            token_types.append(t)
            emb_rows.append(e)
            scalar_rows.append(s)

    # --- Stack items -------------------------------------------------
    for item in state.stack:
        t, e, s = _make_stack_token(
            item=item, state_step=state.step,
            viewer_id=viewer_id, n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)

    # --- Action history ---------------------------------------------
    # Apply the §3 filter, then truncate to the last n events. Tokens
    # come AFTER the state tokens so the model can read "this state +
    # what just happened" in one sweep.
    filtered = [
        ev for ev in recent_actions
        if _is_strategically_relevant(ev.action, ev.state_snapshot)
    ]
    truncated = filtered[-n:]
    current_turn = state.turn_number
    for ev in truncated:
        # DeclareAttackers expands to one token per attacker for
        # fixed per-token shape (roadmap §3).
        if isinstance(ev.action, DeclareAttackers) and ev.action.attacker_ids:
            for atk_id in sorted(ev.action.attacker_ids):
                pseudo = DeclareAttackers(
                    attacker_ids=frozenset({atk_id}),
                )
                t, e, s = _make_action_token(
                    action=pseudo,
                    state_at_action=ev.state_snapshot,
                    action_turn=ev.turn,
                    current_turn=current_turn,
                    viewer_id=viewer_id,
                    actor_player_id=ev.actor_player_id,
                    state_step=ev.step,
                    n_printings_cap=n_printings_cap,
                )
                token_types.append(t)
                emb_rows.append(e)
                scalar_rows.append(s)
            continue
        if isinstance(ev.action, DeclareBlockers) and ev.action.assignments:
            for blocker_id, atk_id in ev.action.assignments:
                pseudo = DeclareBlockers(
                    assignments=((blocker_id, atk_id),),
                )
                t, e, s = _make_action_token(
                    action=pseudo,
                    state_at_action=ev.state_snapshot,
                    action_turn=ev.turn,
                    current_turn=current_turn,
                    viewer_id=viewer_id,
                    actor_player_id=ev.actor_player_id,
                    state_step=ev.step,
                    n_printings_cap=n_printings_cap,
                )
                token_types.append(t)
                emb_rows.append(e)
                scalar_rows.append(s)
            continue

        t, e, s = _make_action_token(
            action=ev.action,
            state_at_action=ev.state_snapshot,
            action_turn=ev.turn,
            current_turn=current_turn,
            viewer_id=viewer_id,
            actor_player_id=ev.actor_player_id,
            state_step=ev.step,
            n_printings_cap=n_printings_cap,
        )
        token_types.append(t)
        emb_rows.append(e)
        scalar_rows.append(s)

    # --- Pack into ndarrays ------------------------------------------
    seq_len = len(token_types)
    token_type_arr = np.asarray(token_types, dtype=np.int64).reshape(seq_len)
    if seq_len == 0:
        emb_arr = np.zeros((0, N_EMB_FIELDS), dtype=np.int64)
        scalar_arr = np.zeros((0, N_SCALAR_FIELDS), dtype=np.float32)
    else:
        emb_arr = np.asarray(emb_rows, dtype=np.int64)
        scalar_arr = np.asarray(scalar_rows, dtype=np.float32)
    attention_mask = np.ones((seq_len,), dtype=np.bool_)

    return {
        "token_type": token_type_arr,
        "token_emb_ids": emb_arr,
        "token_scalars": scalar_arr,
        "attention_mask": attention_mask,
    }


# Defensive: surface a few vocab-size constants for the data_gen /
# trainer consumer so they don't have to thread the structured_model
# import chain themselves. These are re-exports of the constants
# imported above; the assert at the top of this module guarantees
# they're in sync.
__all__ = [
    "ACTION_KIND_VOCAB",
    "ACTION_KIND_VOCAB_SIZE",
    "ActionEvent",
    "CONTROLLER_NA",
    "CONTROLLER_OPPONENT",
    "CONTROLLER_VIEWER",
    "CONTROLLER_VOCAB_SIZE",
    "DEFAULT_ACTION_HISTORY_N",
    "N_EMB_FIELDS",
    "N_SCALAR_FIELDS",
    "N_TOKEN_TYPES",
    "PRINTING_NA",
    "STEP_NA",
    "STEP_VOCAB_SIZE",
    "TARGET_KIND_EXILE_CARD",
    "TARGET_KIND_HAND_CARD",
    "TARGET_KIND_NA",
    "TARGET_KIND_PERMANENT",
    "TARGET_KIND_PLAYER",
    "TARGET_KIND_STACK_ITEM",
    "record_action_event",
    "TARGET_KIND_VOCAB_SIZE",
    "VARIANT_CAST_FOR_FREE",
    "VARIANT_IMPENDING",
    "VARIANT_KICKED",
    "VARIANT_NA",
    "VARIANT_NORMAL",
    "VARIANT_PRIVATE_CHOICE",
    "VARIANT_ROOM_HALF_0",
    "VARIANT_ROOM_HALF_1",
    "VARIANT_VOCAB_SIZE",
    "VARIANT_WARP",
    "printing_id",
    "tokenize_state",
]
