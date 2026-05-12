"""Cross-engine smoke harness — drive Python AND Rust states side by side.

Round-27 Phase-5 slice. The pieces already in place (round 25):

* ``scripts/parity_smoke.py --mode field-diff`` — per-field OK/DIFFER
  diff of TWO views built from ONE Rust state. Useful for verifying
  the field-diff machinery works (the smoke-test-the-smoke), but it
  doesn't actually compare Python and Rust to each other.
* ``scripts/parity_smoke.py --mode trajectory`` — Rust-only N-step
  walk + clone-replay determinism check. Catches Rust-internal
  non-determinism but says nothing about cross-engine agreement.
* ``hash_state`` / ``_hash_rust_state`` — the parity-load-bearing
  fingerprint shim. Asserted byte-equal on a vanilla synthetic state
  by ``--mode initial-state`` (round 23).

What was missing until this slice: an actual cross-engine compare.
That's what this module ships.

Design
------

The first cross-engine slice uses the smallest possible synthetic
state — only two card kinds, Forest and Grizzly Bears, identical
short libraries, empty hands, no battlefield. The point is NOT to
play a real game on this state; it's to confirm the parity-bridge
plumbing (fingerprint recipe, snapshot getters, apply_action, the
priority/step model) agrees on something boring before we layer on
real cards.

Three primitives:

* :func:`build_matched_states` — construct a Python ``GameState`` and
  a Rust ``GameState`` with byte-identical (modulo known-gap) starting
  contents from one ``DeckSpec``.
* :func:`step_both` — drive one decision on each engine and return
  both post-step fingerprints + the field views.
* :func:`compare_fields` — given two field views (one Python, one
  Rust), return the list of fields that differ along with their
  values + an optional gap-doc lookup.

The CLI ``--mode cross-engine`` in ``scripts/parity_smoke.py``
threads these primitives into a per-step loop and prints a
human-readable divergence report.

Coordinated context
-------------------

The Rust engine's PassPriority dispatch flips ``priority_player``;
Python's ``apply_action(PassPriority)`` is a no-op (priority
management is owned by ``priority_loop``, not by ``apply_action``).
For this slice the harness drives both engines through ``apply_action``
directly; the priority divergence is expected and surfaces as the
first detectable cross-engine divergence — which is exactly the
diagnostic value of the harness.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# parity_smoke import shim
# ---------------------------------------------------------------------------

# We use ``scripts/parity_smoke.py``'s field-view + fingerprint helpers as
# the canonical state-view recipe so the cross-engine code can't drift from
# the existing single-engine diagnostics. The script lives outside the
# package on sys.path; load it by file path the same way the test suite does.
def _load_parity_smoke():
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(
            f"could not load parity_smoke module from {script_path!r}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Lazy attribute proxy — calling ``parity_smoke()`` returns the module on first
# use and caches it. Avoids a circular-import head-stand if parity_smoke.py
# ever decides to import this module too.
_cached_parity_smoke: Any = None


def parity_smoke():
    global _cached_parity_smoke
    if _cached_parity_smoke is None:
        _cached_parity_smoke = _load_parity_smoke()
    return _cached_parity_smoke


# ---------------------------------------------------------------------------
# Deck specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardDef:
    """A minimal card definition shared by Python and Rust state builders.

    Only the fields both engines understand from a parity standpoint are
    represented. Both sides materialize a printing from this and a matching
    GameObject from the (printing, controller) pair. The Rust registry
    consumes this via ``register_printing(dict)`` and the Python side
    constructs a ``CardPrinting`` with type-line + supertypes derived from
    ``card_type``.

    Two card kinds are needed for the first slice:
      * a vanilla basic Land (Forest) — produces {G}, no spell effect.
      * a vanilla Creature (Grizzly Bears) — 2/2, costs {1}{G}, no effects.
    """

    name: str
    card_type: str          # "Land" or "Creature"
    mana_cost_generic: int = 0
    mana_cost_colored: tuple[tuple[str, int], ...] = ()
    mana_produced: tuple[str, ...] = ()  # for lands
    power: Optional[int] = None
    toughness: Optional[int] = None


@dataclass(frozen=True)
class DeckSpec:
    """A pair of decklists + the card registry needed to build them.

    A DeckSpec is the contract between the cross-engine harness and the
    state-builder code. The same DeckSpec produces a Python ``GameState``
    via :func:`build_python_state` and a Rust ``GameState`` via
    :func:`build_rust_state`; ``build_matched_states`` is the convenience
    wrapper that calls both.

    ``card_defs`` is the union card pool — both Python's printings dict
    and Rust's Registry are populated from this list. ``p0_library`` and
    ``p1_library`` are per-player lists of card-NAME strings; each name
    must resolve to a ``CardDef`` in ``card_defs``. ``shuffle_seed`` is
    forwarded to the Rust ``make_state``; Python's library is shuffled
    by an in-process ``random.Random`` with the same shape (Fisher-Yates
    via ``random.shuffle`` on a list — Rust uses its own Fisher-Yates
    so the resulting permutation is the SAME modulo any known shuffle-
    convention parity gaps).
    """

    card_defs: tuple[CardDef, ...]
    p0_library: tuple[str, ...]
    p1_library: tuple[str, ...]
    shuffle_seed: Optional[int] = None


# Two pre-built decks for the smoke harness. Anything larger is the next
# slice's problem; this is the absolute minimum that exercises the bridge.

_FOREST = CardDef(
    name="Forest",
    card_type="Land",
    mana_produced=("G",),
)

_BEARS = CardDef(
    name="Grizzly Bears",
    card_type="Creature",
    mana_cost_generic=1,
    mana_cost_colored=(("G", 1),),
    power=2,
    toughness=2,
)


# Second basic land type — used by ``slightly_bigger_deckspec`` to expand
# the cross-engine smoke beyond the mono-color Forest+Bears slice.
# Mountain is the canonical red basic; including it exercises
# heterogeneous library / hand zone signatures (printing_name varies
# Forest vs Mountain) and a second `mana_produced` color in the
# registry without dragging in spell-cast / play-land / mana-tap
# action plumbing. PassPriority decisions remain the only driver,
# matching the first slice's scope.
_MOUNTAIN = CardDef(
    name="Mountain",
    card_type="Land",
    mana_produced=("R",),
)


def tiny_synthetic_deckspec() -> DeckSpec:
    """The first-slice deck: 3-card libraries each, no shuffle.

    p0 library: [Forest, Forest, Grizzly Bears]
    p1 library: [Grizzly Bears, Forest, Forest]

    The asymmetric order is intentional — it gives the library snapshot
    a non-trivial signature so a "library order bug" would actually
    flip the digest rather than coincide with a mirror-image bug.
    """
    return DeckSpec(
        card_defs=(_FOREST, _BEARS),
        p0_library=("Forest", "Forest", "Grizzly Bears"),
        p1_library=("Grizzly Bears", "Forest", "Forest"),
    )


def slightly_bigger_deckspec() -> DeckSpec:
    """Second-slice deck: adds Mountain to the Forest + Bears registry.

    Smallest viable expansion of the inaugural ``tiny_synthetic_deckspec``.
    Both players' libraries now contain THREE card kinds (Forest,
    Mountain, Grizzly Bears) interleaved in an asymmetric order so the
    per-zone signature has a non-trivial 4-card-deep sequence.

    p0 library: [Forest, Mountain, Forest, Grizzly Bears]
    p1 library: [Mountain, Grizzly Bears, Forest, Mountain]

    What this exercises that the first slice doesn't:
      * Heterogeneous library zone signature — the per-object 8-tuple
        snapshot now has varying ``printing_name`` slots in adjacent
        positions, so a "zone signature collapse" bug (e.g. printing_name
        accidentally being a constant) would surface on the
        ``library_pN`` field-view comparison.
      * Registry with a second basic land — Rust ``register_printing``
        is exercised with TWO basic-land entries differing only in
        ``mana_produced``. Round-trips ``mana_produced`` through Rust's
        printing schema for a non-Forest color.
      * No new action surface — PassPriority decisions are still the
        only driver. Legal-action enumerator parity, PlayLand /
        CastSpell apply_action dispatch, and mana-tap activation are
        all explicitly out of scope so the next-slice surface stays
        narrow.

    The point of the slice: confirm the cross-engine bridge's zone-
    signature recipe and registry round-trip stay parity-clean as the
    card pool grows by one color. If they DO stay clean, the next
    natural slice expands the decision script (play_land /
    activate_ability) on this same deck.
    """
    return DeckSpec(
        card_defs=(_FOREST, _BEARS, _MOUNTAIN),
        p0_library=("Forest", "Mountain", "Forest", "Grizzly Bears"),
        p1_library=("Mountain", "Grizzly Bears", "Forest", "Mountain"),
    )


def multi_blocker_deckspec() -> DeckSpec:
    """Third-slice deck: 7-card libs designed to drive a multi-blocker
    combat at turn 15 (p0 attacks, p1 blocks with TWO Bears).

    The audits' predicted CE6/CE7 closure target — damage assignment
    order — requires multiple blockers per attacker to surface. The
    inaugural ``slightly_bigger_deckspec`` only has ONE Grizzly Bears
    on p1's side and only on p1's library + hand (never reaches the
    battlefield in time to block — p1 lacks the mana cadence to cast
    its single Bears before p0 attacks). This deck adds a second Bears
    to p1's library and reshapes both libraries so by the time p0
    attacks at turn 15, p1 has TWO unsick untapped Grizzly Bears on
    its side of the battlefield, eligible to block.

    Library design rationale:

    * **p0 library: 7 cards, Bears at index 5.**
      ``(Forest, Forest, Forest, Forest, Forest, Bears, Forest)``.
      p0 draws on turns 3, 5, 7, 9, 11, 13, 15 (7 draws — exact lib
      size, no empty-draws within the test window). Bears drawn at
      turn 13 (the 6th draw). Cast turn 13 PRECOMBAT_MAIN (3 Forests
      already on bf from turns 3/5/7/9/11 land plays). Bears
      summoning-sick through turn 14. Turn 15 UNTAP clears the
      sickness → attack at turn 15 DECLARE_ATTACKERS.

    * **p1 library: 7 cards, two Bears interleaved.**
      ``(Forest, Forest, Bears, Forest, Bears, Forest, Forest)``.
      p1 draws on turns 2, 4, 6, 8, 10, 12, 14 (7 draws). Bears#1
      drawn turn 6, Bears#2 drawn turn 10. p1 plays Forests on its
      MAIN1 of turns 2/4 (2 lands available by turn 6 MAIN1). Casts
      Bears#1 turn 6 (tap 2 Forests). Bears#1 sick through turn 7.
      Turn 8 UNTAP clears Bears#1 sickness. Turn 8 MAIN1: Bears#2
      not yet in hand (drawn turn 10), no second Bears to cast yet.
      Turn 10 MAIN1: cast Bears#2 (2 untapped Forests from turns 6/8
      land plays + the turn 8 UNTAP cleared the turn 6 cast). Bears#2
      sick through turn 11. Turn 12 UNTAP clears Bears#2 sickness.
      By turn 15 (p0 attacks): both Bears unsick AND untapped (p1
      never attacks in this slice — see ``multi_block_combat_selector``
      — so neither Bears' tap state is touched).

    * **Cast-time SBA timing.** The cast at turn 13 (p0) fires
      Python's ``state_based_actions`` via the harness's
      :func:`resolve_top_of_stack_python` mirror. Both libraries
      still have unread cards at turn 13 (p0 has 1 card left, p1
      has 1 card left) — neither player has tried-and-failed to
      draw from an empty library yet, so ``has_lost`` stays False
      on both. The cast's SBA pass finds no losers → ``winner_id``
      stays None → no premature ``is_over`` flip. Same SBA-safe
      cast window as the inaugural :func:`slightly_bigger_deckspec`
      (which casts at turn 9 with 0 lib cards left but also no
      prior empty-draw attempts).

    Total deck size: 14 cards across both players (7+7). Smallest
    library shape that simultaneously:

    * Provides enough draws to deliver a Bears to each player's hand
      with enough mana to cast it before the multi-block window.
    * Avoids the cast-time SBA-firing asymmetry that would surface
      a winner_id divergence (CE10-adjacent) before the CE6 target.
    * Suppresses the existing combat_selector's I26-adjacent
      empty-blocker walk (the slightly_bigger_deckspec only delivers
      0 blockers).

    Future slices that probe more combat surfaces (e.g. trample +
    multi-block, deathtouch + multi-block, first-strike + multi-block)
    will build on this deck shape by adding keywords to the Bears
    printing or swapping in richer creatures.
    """
    return DeckSpec(
        card_defs=(_FOREST, _BEARS),
        p0_library=(
            "Forest", "Forest", "Forest", "Forest", "Forest",
            "Grizzly Bears", "Forest",
        ),
        p1_library=(
            "Forest", "Forest", "Grizzly Bears", "Forest",
            "Grizzly Bears", "Forest", "Forest",
        ),
    )


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------


def build_rust_state(spec: DeckSpec):
    """Construct a Rust ``GameState`` from ``spec``.

    The Rust ``Registry`` is populated in ``card_defs`` order — card
    name -> printing_id is the position in the tuple. Then ``make_state``
    consumes per-player decklists translated to printing_id arrays.

    Returns the Rust ``GameState`` (a ``mtg_bot_engine.GameState``
    handle). Caller must have already verified the extension is built.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    name_to_pid: dict[str, int] = {}
    for card in spec.card_defs:
        # Build the registry dict matching the Rust register_printing
        # schema. The keys we use here are validated by the round-22
        # bridge code; unknown keys are silently ignored, so any future
        # CardDef field that Rust doesn't yet understand stays inert.
        printing_dict = {
            "name": card.name,
            "card_types": [card.card_type],
            "mana_cost": dict(
                (("generic", card.mana_cost_generic),) if card.mana_cost_generic else ()
            ) | {color: n for color, n in card.mana_cost_colored},
            "effects": [],
        }
        if card.mana_produced:
            printing_dict["mana_produced"] = list(card.mana_produced)
        if card.power is not None:
            printing_dict["power"] = card.power
        if card.toughness is not None:
            printing_dict["toughness"] = card.toughness
        pid = reg.register_printing(printing_dict)
        name_to_pid[card.name] = pid

    p0_lib_pids = [name_to_pid[n] for n in spec.p0_library]
    p1_lib_pids = [name_to_pid[n] for n in spec.p1_library]

    return mtg_bot_engine.make_state(
        reg,
        p0_lib_pids,
        p1_lib_pids,
        shuffle_seed=spec.shuffle_seed,
    )


def build_python_state(spec: DeckSpec):
    """Construct a Python ``GameState`` from the same ``spec``.

    Materializes a fresh ``GameState`` with two empty Players, then
    walks each deck list and creates one GameObject per card name.
    Object IDs are allocated in the same order Rust allocates them
    (p0 library, p0 hand (empty), p1 library, p1 hand (empty)) so a
    cross-engine fingerprint comparison sees matching id slots in the
    8-tuple per-object signature.

    No shuffle is applied (parity with the no-shuffle Rust slices
    that don't pass a ``shuffle_seed``). If ``spec.shuffle_seed`` is
    set, Python uses ``random.Random(seed)`` to shuffle ``p0.library``
    in-place; Rust internally does its own Fisher-Yates on the same
    seed. Shuffle parity is a separate concern (see RUST_PARITY_GAPS
    G19 for related search-shuffle gaps) — for the first slice we
    leave shuffle_seed=None.

    The starting state is configured to match Rust's ``make_state``
    output:
      * life=20 (Python default)
      * active_player_idx=0, priority_player_idx=0 (defaults)
      * turn_number=1 (Python default)
      * step=Step.UNTAP (Rust uses PHASE_UNTAP=0 → "UNTAP")
      * empty hands / battlefield / graveyard / exile / stack
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    # Materialize Python CardPrintings from CardDefs.
    printings: dict[str, CardPrinting] = {}
    for card in spec.card_defs:
        cost = ManaCost(
            generic=card.mana_cost_generic,
            colored=tuple(sorted(card.mana_cost_colored)),
        )
        # Type-line is reconstructed from card_type + a basic-land
        # subtype heuristic; this is cosmetic for the engine but keeps
        # the printing well-formed.
        if card.card_type == "Land":
            type_line = f"Basic Land - {card.name}"
            supertypes: tuple[str, ...] = ("Basic",)
            subtypes: tuple[str, ...] = (card.name,)
        else:
            type_line = card.card_type
            supertypes = ()
            subtypes = ()
        # Lands with ``mana_produced`` get an explicit ``{T}: Add {C}``
        # activated ability so ``ActivateAbility(land_id, 0)`` works on
        # the Python side. Rust's ``ActivateAbility`` dispatch reads the
        # printing's ``mana_produced`` directly (no per-printing ability
        # list); Python's ``_activate_ability`` walks the printing's
        # ``activated_abilities`` tuple. Without this explicit wire-up
        # the two engines would diverge on the very first
        # ``activate_ability`` call: Rust would tap the land and credit
        # the pool, Python would silently no-op (empty ability list →
        # ability_index out of range → return). That divergence is a
        # harness construction issue, not a real engine divergence —
        # ``cards.lands.make_basic_land`` ships the same explicit
        # ability wire-up for production printings (see
        # ``cards.lands.Command Bridge`` for a parallel pattern). Mana
        # abilities flagged ``is_mana_ability=True`` bypass the stack
        # at resolve time (CR 605), matching Rust's direct-pool-credit
        # shape on the ``ActivateAbility`` arm.
        activated_abilities: tuple[ActivatedAbility, ...] = ()
        if card.card_type == "Land" and card.mana_produced:
            activated_abilities = tuple(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=((color, 1),)),
                    is_mana_ability=True,
                )
                for color in card.mana_produced
            )
        printings[card.name] = CardPrinting(
            name=card.name,
            mana_cost_str="",
            mana_cost=cost,
            type_line=type_line,
            supertypes=supertypes,
            card_types=(card.card_type,),
            subtypes=subtypes,
            power=card.power,
            toughness=card.toughness,
            produces=frozenset(card.mana_produced),
            activated_abilities=activated_abilities,
        )

    state = GameState()
    p0 = Player(id=0)
    p1 = Player(id=1)
    state.players = [p0, p1]

    # ID allocation order mirrors Rust:
    # p0 library, p0 hand (empty), p1 library, p1 hand (empty).
    for name in spec.p0_library:
        obj = state.new_object(printings[name], owner_id=0, zone=Zone.LIBRARY)
        p0.library.append(obj)
    for name in spec.p1_library:
        obj = state.new_object(printings[name], owner_id=1, zone=Zone.LIBRARY)
        p1.library.append(obj)

    # Match Rust's PHASE_UNTAP starting step. Without this Python's
    # default state.step is None; the fingerprint would then encode
    # the literal None at the step slot while Rust encodes "UNTAP".
    state.step = Step.UNTAP

    if spec.shuffle_seed is not None:
        # Match Rust's per-player shuffle: p0 uses seed, p1 uses seed *
        # P1_SEED_MULTIPLIER (the magic constant in state_ops_setup.rs).
        # Python's random.Random uses Mersenne Twister and the Rust
        # implementation is a fisher-yates with xorshift64; the two
        # WILL diverge. Document this in the gap doc as a known issue
        # if/when we start using shuffle_seed. The first-slice tests
        # pass shuffle_seed=None to dodge the issue.
        import random

        random.Random(spec.shuffle_seed).shuffle(p0.library)
        random.Random(spec.shuffle_seed * 6364136223846793005 & 0xFFFFFFFFFFFFFFFF).shuffle(p1.library)

    return state


def build_matched_states(spec: DeckSpec):
    """Build Python + Rust states from the same ``DeckSpec`` in one call.

    Returns a tuple ``(py_state, rust_state)``. The caller then drives
    decisions on both and compares fingerprints / field views step by
    step.
    """
    return build_python_state(spec), build_rust_state(spec)


# ---------------------------------------------------------------------------
# Field view of a Python state
# ---------------------------------------------------------------------------


def build_python_field_view(state) -> dict:
    """Mirror :func:`parity_smoke._build_field_view` for a Python state.

    Walks the same 22 fields the Rust field-view emits, reading from
    the Python ``GameState`` attribute surface. The point is field-by-
    field parity inspection: for every field present in both views,
    the values should agree on a parity-clean state.

    Two notes on the conversion shape:

    * ``step`` — Python's ``state.step`` is a ``Step`` enum; we emit
      the ``.name`` attribute (e.g. ``"UNTAP"``) so it matches the
      string Rust's ``step`` getter returns.
    * ``mana_pool_pN`` — Python represents mana as a ``list[ManaCoin]``
      while Rust uses a 6-color counter dict (B/C/G/R/U/W). We emit
      a sorted 6-key tuple keyed by canonical single-letter color
      with the count derived from the Python list. Empty pools on
      both sides produce ``(('B',0),('C',0),('G',0),('R',0),('U',0),('W',0))``.
      Without this normalization the first cross-engine compare
      would flag a TYPE mismatch (list vs dict) instead of the
      actual-but-narrow "fields out of sync" finding it's meant to
      surface.
    """
    ps = parity_smoke()
    view: dict = {}
    step = state.step
    step_name = step.name if step is not None and hasattr(step, "name") else step

    view["turn"] = state.turn_number
    view["step"] = step_name
    view["phase"] = step_name
    view["active_player"] = state.active_player_idx
    view["priority_player"] = state.priority_player_idx
    view["is_over"] = state.is_over()
    view["is_draw"] = getattr(state, "is_draw", False)
    view["winner_id"] = getattr(state, "winner_id", None)
    for pid, p in enumerate(state.players):
        view[f"life_p{pid}"] = p.life
        view[f"hand_p{pid}"] = ps._zone_signature(p.hand)
        view[f"library_p{pid}"] = ps._zone_signature(p.library)
        view[f"graveyard_p{pid}"] = ps._zone_signature(p.graveyard)
        view[f"exile_p{pid}"] = ps._zone_signature(getattr(p, "exile", []))
        view[f"mana_pool_p{pid}"] = _python_mana_pool_signature(p.mana_pool)
    view["battlefield"] = ps._zone_signature(getattr(state, "battlefield", []))
    # Python stack is list[StackItem]; the rust analog is empty by
    # construction in this synthetic slice. Emit an empty tuple.
    view["stack"] = ps._zone_signature(getattr(state, "stack", []))
    return view


# Canonical Rust color ordering. Mirror this in the Python normalizer so
# the sorted-key tuple comparison is apples-to-apples.
_RUST_COLORS: tuple[str, ...] = ("B", "C", "G", "R", "U", "W")


def _python_mana_pool_signature(mana_pool) -> tuple:
    """Translate a Python ``list[ManaCoin]`` to the Rust 6-color tuple.

    Rust always emits all six color counts even when empty; matching
    that shape on the Python side is the only way the field-view
    comparison says "both empty" rather than "Python is list, Rust is
    dict — type mismatch".

    The Python ``ManaCoin`` carries a single-character color tag; we
    histogram them into the 6-color bucket and emit sorted items.
    """
    counts: dict[str, int] = {c: 0 for c in _RUST_COLORS}
    if mana_pool:
        for coin in mana_pool:
            color = getattr(coin, "color", None)
            if color is None:
                # Defensive: a coin object without a recognizable color
                # is folded into colorless ``C``. Should never happen
                # in practice — every mana coin has a known color.
                color = "C"
            # Normalize aliases — some sources use lowercase or names.
            color = color.upper()[:1]
            if color in counts:
                counts[color] += 1
    return tuple(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclass
class FieldDivergence:
    """One field's value differing between two engine views.

    ``field`` is the field name (matches :data:`parity_smoke.FIELD_DIFF_FIELDS`).
    ``py_value`` and ``rust_value`` are the two engines' values.
    ``known_gap`` is the gap doc reference (e.g. ``"G3"``) if the
    divergence matches a documented gap, else ``None`` for novel
    divergences.
    """

    field: str
    py_value: Any
    rust_value: Any
    known_gap: Optional[str] = None


def compare_fields(
    py_view: dict, rust_view: dict, gap_lookup: Optional[Callable[[str], Optional[str]]] = None,
) -> list[FieldDivergence]:
    """Walk every field in :data:`parity_smoke.FIELD_DIFF_FIELDS` and
    return a list of divergences.

    ``gap_lookup`` (optional) maps a field name to a documented-gap id
    (``"G3"`` / ``"I9"`` / ...). Defaults to :func:`default_gap_lookup`
    which does a literal grep against ``docs/RUST_PARITY_GAPS.md``.

    The order of returned divergences matches FIELD_DIFF_FIELDS
    ordering so the first one is the "earliest" by canonical
    convention (turn / step / phase before zones).
    """
    ps = parity_smoke()
    if gap_lookup is None:
        gap_lookup = default_gap_lookup

    divergences: list[FieldDivergence] = []
    for field_name in ps.FIELD_DIFF_FIELDS:
        py_val = py_view.get(field_name)
        rust_val = rust_view.get(field_name)
        if py_val != rust_val:
            divergences.append(
                FieldDivergence(
                    field=field_name,
                    py_value=py_val,
                    rust_value=rust_val,
                    known_gap=gap_lookup(field_name),
                )
            )
    return divergences


# ---------------------------------------------------------------------------
# Gap-doc lookup
# ---------------------------------------------------------------------------


# Cached parse of RUST_PARITY_GAPS.md — keyed by field-name snippet → gap id.
_gap_doc_cache: Optional[dict[str, str]] = None


def _load_gap_doc_index() -> dict[str, str]:
    """Parse ``docs/RUST_PARITY_GAPS.md`` once and return an index of
    canonical-field-name → most-likely gap section id (e.g. ``"G3"``).

    Hard-coded routing for the fields we have prior knowledge about.
    This is intentionally a small curated map rather than a fuzzy
    full-text grep — false positives (pointing the operator at a gap
    that isn't relevant) are *not* cheap when the smoke is the first
    cross-engine check and the operator needs trustworthy signal to
    triage real divergences.

    Each entry says "if FIELD differs, the most relevant doc section
    is X" based on hand-inspecting RUST_PARITY_GAPS.md. Fields not in
    this table return ``None`` from :func:`default_gap_lookup` — that
    signals "NOVEL divergence; investigate."

    Implementation note: we still verify the section *exists* in the
    doc before returning it, so a future doc renumbering can't
    invent a phantom gap reference. The doc's section ids stay
    monotonic (per its own "Maintenance" section), so this check
    catches the rare case of someone renumbering downward.
    """
    global _gap_doc_cache
    if _gap_doc_cache is not None:
        return _gap_doc_cache

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    gaps_path = repo_root / "docs" / "RUST_PARITY_GAPS.md"

    # Curated lookup table. Each FIELD maps to a list of candidate
    # section ids in order of relevance; the first existing one wins.
    # The reasoning behind each mapping:
    #   priority_player -> I25 (priority composition layer; Rust's
    #     apply_action(PassPriority) toggles priority_player, Python's
    #     is a no-op — engine-side G3/G4/G15 closed by the composer
    #     in r27, but the cross-engine apply_action surface remains
    #     because Python owns priority in simulate.priority_loop, not
    #     in apply_action). G3 / G15 dropped from "Confirmed gaps" but
    #     I25 is the parity-invariant entry covering the residual.
    #   active_player -> I25 (same advance_phase wrap reset)
    #   step / phase -> G7 was the deferred UEOT cleanup expiration,
    #     closed in r27 by the UEOT framework (I23 now). G16 is the
    #     deliberate set_phase asymmetry.
    #   mana_pool -> I20 documents the advance_phase composition; on
    #     the cross-engine smoke a mana_pool divergence is typically
    #     a TYPE mismatch (Python list vs Rust 6-color dict) which is
    #     NOVEL — we route to None there. The :func:`_python_mana_pool_signature`
    #     normalizer should prevent that surfacing.
    field_to_candidates: dict[str, list[str]] = {
        "priority_player": ["I25"],
        "active_player": ["I25"],
        # Counter cancellation gap (G8) only fires when counters move
        # around; battlefield-level differences in the synthetic smoke
        # are more likely cosmetic. Map to None until a real counter
        # divergence shows.
    }

    section_re = re.compile(r"^### ([GI]\d+)\.")
    existing_sections: set[str] = set()
    if gaps_path.is_file():
        for line in gaps_path.read_text(encoding="utf-8").splitlines():
            m = section_re.match(line)
            if m is not None:
                existing_sections.add(m.group(1))

    index: dict[str, str] = {}
    for field_name, candidates in field_to_candidates.items():
        for candidate in candidates:
            if candidate in existing_sections:
                index[field_name] = candidate
                break

    _gap_doc_cache = index
    return index


def default_gap_lookup(field_name: str) -> Optional[str]:
    """Best-effort gap-doc lookup for a field name.

    Returns the gap id (``"G3"`` / ``"I9"`` / ...) if the field's
    keyword appears in any section's body, else ``None``. Falls
    through silently if RUST_PARITY_GAPS.md is missing or empty.
    """
    index = _load_gap_doc_index()
    return index.get(field_name)


# ---------------------------------------------------------------------------
# Step driver
# ---------------------------------------------------------------------------


@dataclass
class CrossEngineStep:
    """One step's outcome from driving both engines through the same action.

    ``action_dict`` is the action that was applied (Rust form: a dict
    with ``kind`` + extra fields). The Python side mirrors it via
    :func:`_dict_to_python_action`.

    ``py_view`` / ``rust_view`` are the post-step field views.
    ``divergences`` are the list of fields where they disagree (empty
    on a clean step).
    """

    step_index: int
    action_dict: dict
    py_view: dict = field(default_factory=dict)
    rust_view: dict = field(default_factory=dict)
    divergences: list[FieldDivergence] = field(default_factory=list)


def _dict_to_python_action(action_dict: dict):
    """Convert a Rust-style action dict to a Python ``Action`` instance.

    Mirrors :func:`apply_action`'s dispatch table. Supported kinds:

    * ``pass_priority`` → ``PassPriority()``
    * ``play_land`` → ``PlayLand(card_id=...)``
    * ``cast_spell`` → ``CastSpell(card_id=...)``
    * ``activate_ability`` → ``ActivateAbility(source_id=..., ability_index=...)``
    * ``declare_attackers`` → ``DeclareAttackers(attacker_ids=frozenset(...))``
    * ``declare_blockers`` → ``DeclareBlockers(assignments=((blocker_id, attacker_id), ...))``

    Unknown kinds raise ``ValueError`` to mirror Rust's strict-parse
    contract.
    """
    from mtg_bot.actions import (
        ActivateAbility, CastSpell, DeclareAttackers, DeclareBlockers,
        PassPriority, PlayLand,
    )

    kind = action_dict.get("kind")
    if kind == "pass_priority":
        return PassPriority()
    if kind == "play_land":
        return PlayLand(card_id=int(action_dict["card_id"]))
    if kind == "cast_spell":
        return CastSpell(card_id=int(action_dict["card_id"]))
    if kind == "activate_ability":
        return ActivateAbility(
            source_id=int(action_dict["source_id"]),
            ability_index=int(action_dict["ability_index"]),
        )
    if kind == "declare_attackers":
        # Rust shape: ``attacker_ids`` is a list of u32; Python's
        # ``DeclareAttackers.attacker_ids`` is a frozenset[int]. The
        # set conversion drops Rust's iteration order, but Python's
        # ``_declare_attackers`` re-filters through ``eligible_attackers``
        # which iterates ``state.battlefield`` (centralized) — so the
        # post-apply attacker order is parity-equivalent regardless.
        return DeclareAttackers(
            attacker_ids=frozenset(int(i) for i in action_dict["attacker_ids"])
        )
    if kind == "declare_blockers":
        # Rust shape: ``assignments`` is a list of (blocker_id, attacker_id)
        # tuples. Python's ``DeclareBlockers.assignments`` is the same
        # shape (tuple of 2-tuples). Coerce each pair to int.
        return DeclareBlockers(
            assignments=tuple(
                (int(pair[0]), int(pair[1]))
                for pair in action_dict["assignments"]
            )
        )
    raise ValueError(
        f"unsupported action kind for cross-engine step: {kind!r} "
        f"(action dict: {action_dict!r})"
    )


def resolve_top_of_stack_python(py_state) -> int:
    """Harness-side mirror of Rust's auto-resolve-on-cast semantics (CE5 closure).

    Rust's ``cast_spell`` (``state_ops_cast.rs::cast_creature``) fuses
    cast + resolve into one primitive — the card moves directly from
    hand to battlefield, skipping the stack entirely (no-stack
    semantics per the docstring at line 293). Python's ``_cast_spell``
    pushes a ``StackItem`` onto ``state.stack`` and defers the bf
    transition to ``resolve_top_of_stack``, which fires once both
    players pass priority (CR 117.4) via ``simulate.priority_loop``.

    To compare apples-to-apples on the cross-engine smoke without
    growing Rust a full stack-and-priority surface, this harness
    primitive drains Python's stack down to empty after every
    ``cast_spell`` action. The drain mirrors the canonical pattern in
    ``simulate.priority_loop`` (line 257): pop one item, run SBAs,
    repeat until the stack is empty.

    This is the same pattern as :func:`advance_phase_python` — a
    HARNESS-only Python mirror of a Rust primitive's semantics. The
    production Python engine still drives spell resolution through the
    real priority loop; this helper only runs from the cross-engine
    walker.

    Returns the count of stack items drained (0 if the stack was
    already empty — a harmless no-op on non-cast actions).
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions

    drained = 0
    # Each resolve may itself push triggered-ability items (ETBs etc.)
    # onto the stack; the while-loop drains them too, matching the
    # priority loop's "keep resolving until empty" contract. On the
    # current synthetic deck (Bears has no ETB) the loop runs exactly
    # one iteration, but the shape is correct for future printings
    # that ship triggers.
    while py_state.stack:
        resolve_top_of_stack(py_state)
        state_based_actions(py_state)
        drained += 1
    return drained


# Action kinds whose Rust-side semantics fuse cast+resolve into a
# single mutation — the harness drains Python's stack after these to
# match Rust's empty-stack observable. Today this is exactly
# ``cast_spell``; if a future Rust primitive grows similar no-stack
# semantics (e.g. an ``activate_non_mana_ability`` arm that bypasses
# the stack), append its kind here.
_RUST_AUTO_RESOLVE_ACTION_KINDS: frozenset[str] = frozenset({"cast_spell"})


def step_both(py_state, rust_state, action_dict: dict) -> CrossEngineStep:
    """Apply ``action_dict`` to both engines and compare post-step views.

    The action drives a single decision; both sides are mutated in
    place. Returns a :class:`CrossEngineStep` carrying the views +
    the per-field divergence list. The step index is left at -1 by
    default — the outer harness fills it in.

    **CE5 closure — cast-vs-resolve mirror.** When ``action_dict``'s
    kind is in :data:`_RUST_AUTO_RESOLVE_ACTION_KINDS` (today:
    ``cast_spell``), the harness drains Python's stack via
    :func:`resolve_top_of_stack_python` AFTER both engines apply the
    action and BEFORE the field-view compare runs. This parity-aligns
    the cross-engine view on Rust's no-stack ``cast_creature``
    semantics without modifying production Rust to grow a real stack.
    """
    from mtg_bot.actions import apply_action as py_apply_action

    py_action = _dict_to_python_action(action_dict)
    # Python's apply_action takes (state, player_id, action). For most
    # action kinds we use priority_player_idx as the actor — matches
    # Rust's ``apply_action`` which reads ``priority_player`` for the
    # actor.
    #
    # **Declare-blockers actor exception**. Python's ``_declare_blockers``
    # filters by ``eligible_blockers(state, player_id)`` — the actor
    # must be the DEFENDER (the player whose creatures are blocking),
    # not the priority player (which in our harness is the active
    # player throughout combat because we don't model the
    # priority-handoff to defender at DECLARE_BLOCKERS). Without this
    # override Python's validate-loop drops every non-empty
    # ``assignments`` entry because the active player owns no
    # eligible blockers, and the harness sees an empty blocked_by set
    # on the attacker — a parity gap that's a harness construction
    # issue, not a real cross-engine divergence. Rust's
    # ``declare_blocker`` primitive reads the blocker's controller
    # from the bf index so no actor parameter is needed on that side.
    actor = py_state.priority_player_idx
    if action_dict.get("kind") == "declare_blockers":
        actor = 1 - py_state.active_player_idx
    py_apply_action(py_state, actor, py_action)
    rust_state.apply_action(action_dict)

    # CE5 closure: drain Python's stack for actions whose Rust analog
    # auto-resolves. See :func:`resolve_top_of_stack_python` docstring.
    if action_dict.get("kind") in _RUST_AUTO_RESOLVE_ACTION_KINDS:
        resolve_top_of_stack_python(py_state)

    ps = parity_smoke()
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)

    return CrossEngineStep(
        step_index=-1,
        action_dict=action_dict,
        py_view=py_view,
        rust_view=rust_view,
        divergences=compare_fields(py_view, rust_view),
    )


# ---------------------------------------------------------------------------
# Full-walk harness
# ---------------------------------------------------------------------------


@dataclass
class CrossEngineWalkResult:
    """Aggregate outcome of a cross-engine walk.

    ``initial_divergences`` — divergences detected BEFORE any
    decision is applied (i.e., on the matched starting states). A
    non-empty list here means the two engines disagree at step 0,
    which is a signal the bridge plumbing itself is misaligned —
    fingerprint recipe, snapshot getters, or starting-state defaults.

    ``steps`` — one CrossEngineStep per applied decision. The first
    step whose ``divergences`` is non-empty is the "first
    divergence step"; subsequent steps continue running so the
    operator can see what cascades from the first split.

    ``aborted_at`` — set to the step index where an exception
    interrupted the walk (e.g. ``apply_action`` raising on the
    Python side because the engine's invariants are stricter than
    Rust's). None on clean termination.

    ``error`` — short human-readable message for the abort case.
    """

    initial_divergences: list[FieldDivergence] = field(default_factory=list)
    steps: list[CrossEngineStep] = field(default_factory=list)
    aborted_at: Optional[int] = None
    error: Optional[str] = None

    def first_divergence_step(self) -> Optional[int]:
        """Return the index of the first step where divergences appeared,
        or None on a fully-clean walk."""
        if self.initial_divergences:
            return -1  # sentinel: "before any decision"
        for step in self.steps:
            if step.divergences:
                return step.step_index
        return None


def walk_both(
    spec: DeckSpec,
    n_decisions: int = 10,
    decision_selector: Optional[Callable[[Any, Any, int], dict]] = None,
    inject_divergence: bool = False,
) -> CrossEngineWalkResult:
    """Build matched Python+Rust states, drive ``n_decisions`` actions,
    and report a per-step divergence aggregate.

    Default decision selector: PassPriority on every step. PassPriority
    is the only action both engines can drive trivially without
    needing legal-action enumerator parity (Python's ``legal_actions``
    and Rust's ``legal_decisions`` have known emission differences for
    PlayLand / CastSpell — that's the next slice's parity surface).

    ``decision_selector`` (optional): callback ``(py_state, rust_state,
    step_index) -> action_dict``. Replaces the default PassPriority
    selector for callers that want to drive a custom decision script.

    ``inject_divergence``: when True, ARTIFICIALLY perturb the Rust
    state's life on player 0 BEFORE comparing the initial states.
    This is the smoke-test-the-smoke path — proves the harness DOES
    flag a fake cross-engine divergence at step 0. Mirrors the
    round-25 ``--mode field-diff --inject-divergence`` pattern.

    Returns a :class:`CrossEngineWalkResult`.
    """
    result = CrossEngineWalkResult()

    try:
        py_state, rust_state = build_matched_states(spec)
    except Exception as e:
        result.aborted_at = -2
        result.error = f"build_matched_states failed: {type(e).__name__}: {e}"
        return result

    if inject_divergence:
        # Smoke-test-the-smoke: poke a known-different field into the
        # Rust state so a downstream "is this harness even working?"
        # gate fires deterministically. Mirrors --mode field-diff's
        # --inject-divergence semantics — visible at step 0.
        rust_state.set_life(0, 19)

    ps = parity_smoke()
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)
    result.initial_divergences = compare_fields(py_view, rust_view)

    selector = decision_selector or _default_pass_priority_selector

    for step_index in range(n_decisions):
        try:
            action_dict = selector(py_state, rust_state, step_index)
            step = step_both(py_state, rust_state, action_dict)
        except Exception as e:
            result.aborted_at = step_index
            result.error = f"step {step_index}: {type(e).__name__}: {e}"
            return result
        step.step_index = step_index
        result.steps.append(step)

    return result


def _default_pass_priority_selector(py_state, rust_state, step_index: int) -> dict:
    """Default decision selector: always pass priority.

    PassPriority is the lowest-common-denominator action both engines
    accept. The exact divergence behavior differs (Python's
    ``apply_action(PassPriority)`` is a no-op; Rust's flips
    ``priority_player``) — that's exactly the cross-engine divergence
    this slice is meant to surface.
    """
    return {"kind": "pass_priority"}


def play_a_land_selector(py_state, rust_state, step_index: int) -> dict:
    """Phase-5 follow-up selector: draw + play_land probe.

    This selector extends the inaugural pass-priority script with two
    real action surfaces:

    * **Draw (step 0 only)** — On ``step_index == 0``, the selector
      mutates BOTH engines directly: it calls Python's
      ``turn.draw_card`` on p0's library and Rust's ``draw_card``
      pymethod on the same player. This is NOT an action both engines
      apply through ``apply_action`` (Python's Action enum has no
      ``DrawCard`` variant — draws are turn-based actions, not
      priority decisions). After the side-channel draw, the selector
      still emits ``pass_priority`` so ``step_both`` runs its
      compare AFTER the draw and the harness reports whatever
      hand/library divergences surface.

    * **PlayLand (step >= 1)** — Subsequent steps scan p0's Python
      hand for a Land printing. If found, the selector emits
      ``play_land`` for that card's id; otherwise it falls back to
      ``pass_priority``. The land lookup runs on the Python hand
      because (a) Python's ``GameObject.printing.card_types`` is the
      natural type-tag accessor and (b) once the two engines diverge
      on step 0 the hands differ between them — using Python's hand
      mirrors "the parity reference decides the script; the Rust
      impl is exercised by replaying that script", which is the
      shape any real cross-engine comparison wants.

    Deliberately NOT phased through UNTAP -> UPKEEP -> DRAW ->
    PRECOMBAT_MAIN. Python's ``apply_action(PlayLand)`` does not
    gate on the step (the gate lives in ``legal_actions``, NOT in
    ``actions._play_land`` — see ``src/mtg_bot/actions.py``), and
    Rust's ``play_land`` primitive likewise has no step gate (see
    ``rust/src/state_ops_cast.rs::play_land`` docstring "Does not
    consult sorcery speed"). The land enters from a step=UNTAP state
    just fine; that mirrors the apply-action-only scope of this
    slice.

    **CE3 finding.** This selector surfaces the **library pop-
    orientation divergence** that has been latent in the cross-engine
    bridge since both engines exposed a ``draw_card`` but nothing
    drove it. Python's ``turn.draw_card`` does ``library.pop(0)``
    (TOP of list = deck-top). Rust's ``draw_card`` does ``lib.pop()``
    (TAIL of Vec = deck-top). Built from the same ``DeckSpec`` in
    the same source order, the two engines disagree on WHICH card
    is the next to draw. After the step-0 side-channel draw,
    ``hand_p0`` and ``library_p0`` field views diverge — and may
    cascade onto the battlefield if the play_land selector lands on
    differing cards. See ``docs/RUST_PARITY_GAPS.md`` CE3 entry for
    the full diagnosis and closure plan.
    """
    if step_index == 0:
        # Drive a single draw on both engines so subsequent steps have
        # a card in hand to play (or in Rust's case, to compare
        # against). The Python-side import is local because
        # ``mtg_bot.turn`` isn't imported at module top (the
        # cross-engine module deliberately keeps its imports narrow).
        from mtg_bot.turn import draw_card as _py_draw_card

        if py_state.players[0].library:
            _py_draw_card(py_state, 0)
        # Rust's draw_card returns Option<u32>; the result is unused —
        # we only care about the side-effect on hand/library.
        rust_state.draw_card(0)
        return {"kind": "pass_priority"}

    # Subsequent steps: look for a Land in p0's Python hand. The
    # printing exposes a ``card_types`` tuple; "Land" matches both
    # basic and nonbasic. If found, emit play_land; else pass.
    p0_hand = py_state.players[0].hand
    for obj in p0_hand:
        if "Land" in obj.printing.card_types:
            return {"kind": "play_land", "card_id": int(obj.id)}
    return {"kind": "pass_priority"}


# ---------------------------------------------------------------------------
# Phase-5 multi-turn slice — side-channel advance_phase helper
# ---------------------------------------------------------------------------
#
# Rust exposes ``state.advance_phase()`` as a pymethod that fully composes the
# phase-boundary side effects (CR 106.4 mana-pool empty on exit + CR 302.1
# untap sweep + CR 514.1/514.2 cleanup discard/damage clear + CR 504.1
# draw-step gated by CR 103.7c). Python's apply_action(PassPriority) is a
# pure no-op; Python's natural phase advancer is ``simulate.run_step`` /
# ``run_turn`` which run the whole step including the priority loop, triggers,
# and turn-based actions. That's MUCH more than Rust's ``advance_phase`` does.
#
# For the multi-turn cross-engine harness we want the SAME composition on
# both sides — just the side-effects Rust models, no Python-side extras.
# The shape below is a deliberate mirror of Rust's ``advance_phase`` body
# in ``rust/src/state_ops_steps.rs`` so a cross-engine walk that calls
# both engines' advance_phase yields parity-matched state changes. This is
# a HARNESS-only helper (not a real Python engine method) — the production
# Python engine drives phase changes through ``run_turn`` / ``run_step``,
# not through this routine. Documenting it here as a harness limitation
# rather than as a real engine fix, per the task brief.
#
# If a future slice needs the full Python composition (triggers, UEOT
# cleanup, etc.), the natural shape is to delete this helper and have
# the harness drive ``run_step`` on Python while still driving
# ``advance_phase`` on Rust — and then re-derive the cross-engine
# divergence-mapping as the new shape's first slice.
# ---------------------------------------------------------------------------


# Canonical Python step order matching Rust's PHASE_UNTAP..PHASE_CLEANUP
# integer sequence. Index in this tuple == Rust phase integer.
_PY_STEP_BY_PHASE_INT: tuple = ()


def _step_for_phase(phase_int: int):
    """Translate a Rust phase integer (0..11) to the matching Python
    ``Step`` enum. Rust's PHASE_UNTAP=0 .. PHASE_CLEANUP=11, mirroring
    ``turn.STEP_ORDER``.
    """
    from mtg_bot.turn import STEP_ORDER

    if 0 <= phase_int < len(STEP_ORDER):
        return STEP_ORDER[phase_int]
    raise ValueError(f"phase_int out of range: {phase_int}")


def advance_phase_python(py_state) -> int:
    """Side-channel Python mirror of Rust's ``state.advance_phase()``.

    Mirrors the composition in ``rust/src/state_ops_steps.rs::advance_phase``
    bit-for-bit:

    1. Empty both players' mana pools (CR 106.4 — phase-exit).
    2. If phase == CLEANUP: wrap to UNTAP, ``turn_number += 1``, swap
       ``active_player_idx``, reset ``priority_player_idx`` to the new
       active player.
    3. Else: tick the phase forward by 1.
    4. If new phase == UNTAP: run the untap sweep (untap all permanents
       for the new active player) and clear summoning sickness on
       their permanents.
    5. If new phase == DRAW and ``turn_number != 1``: draw a card for
       the active player (CR 504.1 gated by CR 103.7c).
    6. If new phase == CLEANUP: run the cleanup-step's hand-size
       discard for the active player (max=7) and clear marked damage
       on all battlefield permanents (CR 514.1 + CR 514.2).

    Returns the new phase integer (matches Rust's return shape).

    Deliberately NOT a real Python engine entrypoint — this is a
    harness primitive used only by the cross-engine smoke walker.
    The production Python engine drives phase changes through
    ``simulate.run_step`` / ``run_turn`` which compose a much larger
    surface (triggers, UEOT continuous-effect expiration, priority
    loop). This helper restricts the composition to exactly what
    Rust's ``advance_phase`` does so the cross-engine walk compares
    apples-to-apples.
    """
    from mtg_bot.turn import (
        STEP_ORDER,
        Step,
        run_untap_step,
    )

    # 1. CR 106.4 — empty both players' mana pools BEFORE the phase counter
    #    ticks forward. Mirrors Rust's ``empty_all_mana_pools_inline``.
    for p in py_state.players:
        p.mana_pool.clear()

    # Determine current phase as an integer.
    cur_step = py_state.step
    cur_phase_int = STEP_ORDER.index(cur_step) if cur_step in STEP_ORDER else 0

    if cur_step == Step.CLEANUP:
        # 2. Wrap to UNTAP, bump turn, swap active player, reset priority.
        new_phase_int = 0
        py_state.turn_number += 1
        py_state.active_player_idx = 1 - py_state.active_player_idx
        py_state.priority_player_idx = py_state.active_player_idx
    else:
        new_phase_int = cur_phase_int + 1

    new_step = STEP_ORDER[new_phase_int]
    py_state.step = new_step

    if new_step == Step.UNTAP:
        # 4. Untap sweep + summoning-sick clear via the existing primitive.
        #    ``run_untap_step`` does both (and a bunch of Python-only
        #    bookkeeping that Rust doesn't model — controller_untap
        #    expiry, phasing, agent overrides). The Python-only extras
        #    are inert on the synthetic deck (no continuous effects,
        #    no phased cards, no agent overrides), so calling
        #    ``run_untap_step`` produces the same observable state as
        #    a minimal "untap + clear summoning sick" mirror would.
        run_untap_step(py_state)

    if new_step == Step.DRAW and py_state.turn_number != 1:
        # 5. CR 504.1 gated by CR 103.7c. Same draw_card primitive used
        #    by the play_a_land_selector's step-0 side-channel draw.
        from mtg_bot.turn import draw_card as _py_draw_card

        _py_draw_card(py_state, py_state.active_player_idx)

    if new_step == Step.CLEANUP:
        # 6. CR 514.1 hand-size discard + CR 514.2 damage clear.
        #    NOT calling ``run_cleanup_step`` directly because that
        #    Python primitive composes a much larger surface (UEOT
        #    expiration, copy reverts, control-change reverts, layer
        #    cache rebuilds) that Rust's ``advance_phase`` does NOT
        #    do. We inline only the two CR 514 hooks Rust models.
        from mtg_bot.game import Zone

        ap = py_state.player_by_id(py_state.active_player_idx)
        while len(ap.hand) > 7:
            card = ap.hand.pop()
            card.zone = Zone.GRAVEYARD
            ap.graveyard.append(card)
        # Damage clear on both battlefields. ``damage`` is the Python
        # field (a per-GameObject scalar — Rust's ``damage`` slot maps
        # to the same observable). The reset happens at the same
        # phase boundary on both sides.
        for obj in py_state.battlefield:
            obj.damage = 0

    return new_phase_int


def multi_turn_selector(py_state, rust_state, step_index: int) -> dict:
    """Phase-5 multi-turn cross-engine smoke selector.

    Drives multiple turns of play by combining:

    * **Side-channel phase advance.** When the current phase is NOT a
      phase where a meaningful action lives (UNTAP / UPKEEP / DRAW /
      BEGINNING_OF_COMBAT / DECLARE_ATTACKERS / DECLARE_BLOCKERS /
      COMBAT_DAMAGE / END_OF_COMBAT / END_STEP / CLEANUP), the selector
      side-channels ``advance_phase`` on BOTH engines and then emits
      ``pass_priority`` so the harness's per-step compare fires after
      the phase-boundary side effects have settled. Using a side-
      channel is a deliberate harness limitation — Python's
      ``apply_action(PassPriority)`` is a pure no-op and there is no
      ``advance_phase`` action variant either side dispatches through
      ``apply_action``. The same pattern as the inaugural draw side-
      channel in :func:`play_a_land_selector`.

    * **MAIN-phase land drop.** When the current phase is
      PRECOMBAT_MAIN or POSTCOMBAT_MAIN and p0's hand contains a Land,
      emit ``play_land`` for the first such land. Subsequent decisions
      on the same MAIN phase find no more lands (Python's
      ``_play_land`` removed the only one), so the selector advances
      phase on the next call.

    The harness's per-step compare fires AFTER both side-channels +
    the emitted action are applied. The point of the slice is to surface
    the first NOVEL divergence triggered by multi-turn play — most
    likely candidates per :doc:`docs/RUST_PARITY_GAPS.md`:

    * **I18 (CR 103.7c first-turn skip)** — on turn 1's DRAW step, both
      engines must skip the auto-draw. If they don't agree, hand_p0
      and library_p0 diverge at the UNTAP -> DRAW boundary.
    * **I20 (advance_phase mana-empty + CLEANUP hooks)** — if the two
      engines compose phase-boundary effects differently, mana_pool /
      hand / battlefield diverge after the relevant boundary.
    * **Untap sweep + summoning-sick clear (I10)** — first surfaces
      on turn 2's UNTAP entry since turn 1's UNTAP is the starting
      state's phase (no prior phase to advance FROM).
    * **CLEANUP -> UNTAP wrap** — turn 2's beginning involves
      ``turn_number += 1`` + ``active_player_idx`` swap. First test
      of these composed side effects under cross-engine.

    The selector deliberately does NOT touch combat (no creatures
    to attack with on this deck, and the selector returns
    pass_priority through DECLARE_ATTACKERS / DECLARE_BLOCKERS).
    """
    from mtg_bot.turn import STEP_ORDER, Step

    cur_step = py_state.step
    active_idx = py_state.active_player_idx

    # Phases where we have a meaningful action to drive. Right now: MAIN1
    # / MAIN2 for play_land. Everything else: advance and pass.
    if cur_step in (Step.PRECOMBAT_MAIN, Step.POSTCOMBAT_MAIN):
        # Look for a Land in the active player's hand.
        ap_hand = py_state.players[active_idx].hand
        for obj in ap_hand:
            if "Land" in obj.printing.card_types:
                return {"kind": "play_land", "card_id": int(obj.id)}
        # No land available — advance phase past this MAIN step.
        advance_phase_python(py_state)
        rust_state.advance_phase()
        return {"kind": "pass_priority"}

    # All other phases: side-channel advance on both engines, then emit
    # pass_priority so the harness's compare runs after the phase boundary.
    advance_phase_python(py_state)
    rust_state.advance_phase()
    return {"kind": "pass_priority"}


# ---------------------------------------------------------------------------
# Phase 5 follow-up #4: cast_bears_selector — extend the harness past
# land-only play into creature spells + mana abilities + summoning sick.
# Builds on multi_turn_selector's phase-walk + land-drop foundation.
#
# Decision script shape (state-machine, re-derived from observable state on
# every call so the selector is stateless):
#
#   1. If active player has Grizzly Bears in hand AND (untapped Forests on bf)
#      AND active_player.mana_pool has fewer than 2 G coins AND it's MAIN1
#      AND haven't cast yet this turn: emit ``activate_ability(forest_id, 0)``
#      to tap one Forest and credit {G}.
#   2. If active player has Grizzly Bears in hand AND mana_pool has >= 2 G
#      coins AND it's MAIN1: emit ``cast_spell(bears_id)`` to spend {1}{G}
#      and put Bears on stack (Python) / move to bf (Rust).
#   3. Otherwise: delegate to multi_turn_selector's behavior (play lands in
#      MAIN1 if available, side-channel advance phase + pass_priority
#      otherwise).
#
# Why no explicit step counter / "have I cast?" flag: Python's ``_cast_spell``
# removes the Bears from hand at cast time, so after the cast the
# "Bears in hand" check naturally fails on every subsequent call. The
# selector then falls through to multi_turn_selector behavior. Rust's
# ``cast_creature`` likewise removes the card from hand.
#
# **Expected behavior on this slice's tiny synthetic deck.** Per the
# ``slightly_bigger_deckspec`` library:
#   p0 library: [Forest, Mountain, Forest, Grizzly Bears]
#   p1 library: [Mountain, Grizzly Bears, Forest, Mountain]
# Auto-draw is skipped on turn 1 (CR 103.7c) and fires for the new active
# player every subsequent turn. Combined with land-per-turn + the
# multi_turn_selector's MAIN1-only land-drop pattern, the first time the
# active player has Grizzly Bears in hand AND >= 2 untapped basics on bf
# is turn 5 or later. The selector activates Forests until the pool has
# {G}{G} (enough to pay {1}{G} since Python's auto_tap_for_cost consumes
# the {G} coin to satisfy the generic pip first), then casts.
#
# **Predicted divergence**. Python's ``_cast_spell`` pushes the Bears
# StackItem onto ``state.stack`` (CR 601.2 — spells go on the stack
# before resolution; the resolving step happens later via
# ``resolve_top_of_stack``). Rust's ``cast_creature`` (state_ops_cast.rs)
# fuses cast + resolve into one primitive — the card moves directly from
# hand to battlefield, skipping the stack entirely. After the
# ``cast_spell`` decision both engines diverge:
#   * Python: stack=[Bears StackItem], battlefield=[2x Forest], hand=[]
#   * Rust:   stack=[],                battlefield=[2x Forest, Bears (sick)], hand=[]
# The harness's per-field compare surfaces this as CE5 candidates on the
# ``stack`` and ``battlefield`` fields. Whether to file as a single CE5
# (entry + closure plan) is the slice's outcome question.
# ---------------------------------------------------------------------------


def cast_bears_selector(py_state, rust_state, step_index: int) -> dict:
    """Cross-engine smoke selector that drives 2 mana-ability activations
    then a Grizzly Bears cast in MAIN1.

    State machine is re-derived from observable state on every call:

      * If MAIN1 + Bears-in-hand + pool has >= 2 green coins → cast_spell.
      * If MAIN1 + Bears-in-hand + untapped Forest available + pool has
        < 2 green coins → activate_ability on the first untapped Forest.
      * Else delegate to :func:`multi_turn_selector` (play land in MAIN1,
        side-channel advance + pass on non-MAIN phases).

    The selector reads Python state for the script logic (Python is the
    parity reference; the harness replays the script on Rust). Once the
    cast decision is emitted, subsequent calls fall through to the
    multi_turn_selector branch — there's nothing more to do on this deck
    after Bears is cast (no further creature in hand, no combat from the
    selector). The harness's per-step compare on the cast step surfaces
    the stack/battlefield divergence the slice is meant to probe.
    """
    from mtg_bot.turn import Step

    cur_step = py_state.step
    active_idx = py_state.active_player_idx
    ap = py_state.players[active_idx]

    # Detect Bears-in-hand on the active player.
    bears_in_hand = next(
        (
            obj for obj in ap.hand
            if obj.printing.name == "Grizzly Bears"
        ),
        None,
    )

    # Count green coins in the active player's mana pool. Both ``G`` and
    # ``any`` coins satisfy a green requirement; we count strictly the
    # ``G``-color coins to match what ``slightly_bigger_deckspec``'s
    # Forest mana ability produces (no ``any``-color coins available
    # from the printing's ability list).
    green_coins = sum(
        1 for coin in ap.mana_pool
        if getattr(coin, "color", None) == "G"
    )

    # The cast/activate sequence is gated to MAIN1 (mirrors Python's
    # sorcery-speed cast gate for creatures — though the harness's
    # apply_action bypass means we could in principle cast in any
    # phase; gating to MAIN1 keeps the script semantically MTG-correct
    # and avoids surfacing a sorcery-speed-only timing CE that's
    # well-documented in the gap doc rather than a real divergence).
    if cur_step == Step.PRECOMBAT_MAIN and bears_in_hand is not None:
        # Step 2: enough green mana in the pool → cast Bears.
        if green_coins >= 2:
            return {
                "kind": "cast_spell",
                "card_id": int(bears_in_hand.id),
            }
        # Step 1: not enough green yet → tap an untapped Forest.
        # Walk active player's bf for an untapped basic Forest the
        # selector controls. Mountain doesn't satisfy {G} requirements
        # so we filter by ``produces`` set.
        #
        # **Sick-land filter.** A land that just entered the battlefield
        # this turn carries ``summoning_sick=True`` on both engines
        # (Python's ``make_state``-equivalent path + Rust's CE1
        # closure both default new objects to sick=True; neither
        # engine's ``play_land`` clears it). Per CR 302.1 summoning
        # sickness applies to CREATURES tapping for tap-cost
        # abilities, NOT to lands — Python's
        # ``actions._activate_ability`` correctly doesn't gate on it,
        # but Rust's ``ActivateAbility`` dispatch in
        # ``state_ops_actions.rs`` rejects ANY summoning-sick source
        # (creature or land) with a hard ``ValueError``. The selector
        # filters sick lands here so the harness doesn't abort with
        # the Rust raise on a freshly-played land; the underlying
        # divergence is a CE candidate documented in
        # ``docs/RUST_PARITY_GAPS.md``.
        untapped_forest = next(
            (
                obj for obj in py_state.battlefield
                if obj.controller_id == active_idx
                and obj.printing.is_land
                and not obj.tapped
                and not obj.summoning_sick
                and "G" in obj.printing.produces
            ),
            None,
        )
        if untapped_forest is not None:
            return {
                "kind": "activate_ability",
                "source_id": int(untapped_forest.id),
                "ability_index": 0,
            }
        # Fall through to multi_turn_selector — no untapped Forest yet,
        # need to advance turns until p0/p1 has drawn + played enough
        # Forests.

    # Delegate to the multi-turn baseline for everything else.
    return multi_turn_selector(py_state, rust_state, step_index)


# ---------------------------------------------------------------------------
# Phase 5 follow-up #5: combat_selector — extend cast_bears_selector past the
# cast into combat declarations and damage. Builds on cast_bears_selector's
# state machine + adds three new branches:
#
#   1. DECLARE_ATTACKERS step, active player controls a non-sick, non-tapped,
#      undeclared creature: emit ``declare_attackers`` with that creature.
#   2. DECLARE_BLOCKERS step, defender has no eligible blockers (this slice's
#      synthetic deck): emit ``declare_blockers`` with empty assignments so
#      both engines see the no-block path before advance fires.
#   3. COMBAT_DAMAGE step: side-channel ``resolve_combat_damage`` (Python) +
#      ``deal_combat_damage`` (Rust) to actually deal damage, then fall
#      through to multi_turn_selector for the phase advance. Both helpers
#      are NOT routed through ``apply_action`` on either engine — Python's
#      ``simulate.run_step`` calls ``resolve_combat_damage`` directly at the
#      COMBAT_DAMAGE step; Rust exposes ``deal_combat_damage`` as a
#      pymethod the harness must invoke explicitly (no auto-fire in
#      ``advance_phase``). Same "side-channel a method neither engine
#      reaches via apply_action" pattern as :func:`advance_phase_python`.
#   4. END_OF_COMBAT step: side-channel ``clear_combat_state`` (Python) +
#      ``clear_combat`` (Rust) to drop the attacking / blocking flags and
#      reset the per-state attackers / blockers Vecs. Without this Rust's
#      ``self.attackers`` would persist across turns and the next
#      DECLARE_ATTACKERS step's eligibility check would already see the
#      stale entries.
#
# **Expected behavior on the slightly_bigger_deckspec.** After
# cast_bears_selector lands Bears on p0's battlefield at step 108 (turn 9
# PRECOMBAT_MAIN), the harness walks the remaining combat steps as pass-
# only (Bears is summoning-sick, can't attack). Turn 9's combat is empty;
# turn 9 cleanup wraps to turn 10 (p1 active, no creatures); turn 10
# cleanup wraps to turn 11 (p0 active, Bears unsick). At turn 11
# DECLARE_ATTACKERS, the selector emits ``declare_attackers([3])`` for
# Bears. Defender p1 has no creatures so DECLARE_BLOCKERS emits empty
# assignments. COMBAT_DAMAGE deals 2 to p1 (Bears unblocked, 2/2). p1's
# life drops 20 -> 18 on both engines.
#
# **Predicted CE candidates** (from RUST_BF_ITERATION_AUDIT.md §3 and
# CE5_CE6_CE7_CLOSURE_PLAYBOOK.md §3): the audits flag damage assignment
# ORDER as the next likely surfacing surface (Python walks
# ``state.battlefield`` filtered by ``attacker.blocked_by`` per
# combat.py:389/405; Rust walks ``self.blockers`` Vec per
# state_ops_combat.rs:849/962/1025). On a single-attacker / zero-blocker
# slice (which this is), the order question doesn't arise — the
# divergence requires multi-blocker. So this probe is the **gate** that
# unblocks the order-CE probe rather than the order-CE probe itself.
# ---------------------------------------------------------------------------


def resolve_combat_damage_python(py_state) -> bool:
    """Harness-side mirror of Python's ``simulate.run_step`` combat-damage hook.

    Python's combat damage is NOT routed through ``apply_action``; the
    real engine calls :func:`mtg_bot.combat.resolve_combat_damage` from
    ``simulate.run_step`` when ``state.step == Step.COMBAT_DAMAGE``. The
    cross-engine harness drives ``apply_action`` directly + side-channel
    advance_phase, so this hook never fires automatically. The harness
    helper invokes ``resolve_combat_damage`` against the side opposite
    the active player (mirroring ``simulate.run_step`` lines 339-346),
    then runs SBAs.

    Returns ``True`` if any attacker was on the battlefield (i.e. damage
    actually fired), ``False`` if no attackers (fast no-op).

    Same side-channel HARNESS-only pattern as
    :func:`advance_phase_python` and :func:`resolve_top_of_stack_python`.
    """
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.turn import state_based_actions

    if not any(o.attacking for o in py_state.battlefield):
        return False
    # Defender is the non-active player. Python's ``_next_alive`` walks
    # the player list filtering out lost players; on the synthetic
    # 2-player deck this collapses to ``1 - active_player_idx``.
    defender_idx = 1 - py_state.active_player_idx
    defender_id = py_state.players[defender_idx].id
    resolve_combat_damage(py_state, defender_id)
    state_based_actions(py_state)
    return True


def deal_combat_damage_rust(rust_state) -> bool:
    """Harness-side mirror of Rust's combat-damage entry on the Rust side.

    Rust's ``deal_combat_damage`` is exposed as a pymethod and must be
    invoked explicitly — ``advance_phase`` only composes mana-pool /
    untap / draw / cleanup side effects, not combat damage. The harness
    fires it whenever Python's mirror fired (so both sides apply damage
    in the same step) and returns ``True`` if any attacker was declared
    on the Rust side, else ``False``.

    **SBA pass after damage.** Python's
    :func:`mtg_bot.combat.resolve_combat_damage` (the mirror's parity
    target) does NOT itself fire SBAs, but
    :func:`mtg_bot.simulate.run_step` runs ``state_based_actions(state)``
    immediately after the combat-damage hook (simulate.py:343-345). The
    Python-side harness mirror :func:`resolve_combat_damage_python`
    composes the same shape (damage + SBA pass) so this Rust mirror
    must do the same. Without the SBA pass here, Python's
    ``has_lost`` / ``is_over`` flips eagerly (e.g. on an empty-library
    draw flag that gets locked in by SBA) while Rust's surface stays
    stale — a synthetic asymmetry that's a HARNESS bug, not a real
    cross-engine divergence (I19's two-layer winloss surface).
    Mirroring the SBA pass keeps both engines aligned post-CE10.
    """
    # ``GameState.attackers`` isn't exposed as a pymethod; we infer
    # "any attackers" by checking for a non-empty battlefield_snapshot
    # entry with attacking=True via Python's side instead. Since this
    # helper is always called paired with resolve_combat_damage_python,
    # the caller already gates on Python's "any attacker" check; we
    # just unconditionally invoke ``deal_combat_damage`` here, which
    # is a no-op when ``self.attackers`` is empty (the for-loop at
    # state_ops_combat.rs:849 walks an empty Vec).
    rust_state.deal_combat_damage()
    # Mirror Python's post-damage ``state_based_actions(state)`` from
    # simulate.run_step. ``apply_sbas`` is the Rust analog — it walks
    # every state-based action category (creature lethality, empty-
    # library loss, life <= 0 loss, ...) and commits the loss-flag
    # transition into the sticky ``Player.has_lost``. Post-CE10 the
    # surface accessor ``is_over()`` is gated on ``has_lost``, so
    # this call is what keeps Python's eager SBA-driven
    # ``is_over`` / ``is_draw`` flips in sync with Rust's.
    rust_state.apply_sbas()
    return True


def clear_combat_both(py_state, rust_state) -> None:
    """Side-channel clear-combat mirror.

    Python's ``simulate.run_step`` calls
    :func:`mtg_bot.combat.clear_combat_state` at END_OF_COMBAT to drop
    ``attacking`` / ``blocking`` / ``blocked_by`` from every battlefield
    object. Rust exposes ``clear_combat`` as a pymethod that empties
    ``self.attackers`` / ``self.blockers``.

    Without this side-channel, Rust's ``self.attackers`` would persist
    across turns; the next DECLARE_ATTACKERS step would see stale
    entries. Python's per-object ``attacking`` flag isn't in the
    cross-engine field-view's 8-tuple, but the tapped flag IS — and
    once Bears is tapped from attacking, the per-object signature
    diverges from a freshly-untapped Bears the next turn until the
    untap sweep clears it. This helper is the per-call discipline that
    keeps the symmetric clear-combat shape parity-aligned.
    """
    from mtg_bot.combat import clear_combat_state

    clear_combat_state(py_state)
    rust_state.clear_combat()


def combat_selector(py_state, rust_state, step_index: int) -> dict:
    """Cross-engine smoke selector that drives cast + combat to completion.

    Wraps :func:`cast_bears_selector` and adds four new branches:

      * **DECLARE_ATTACKERS, active player owns a non-sick non-tapped
        Creature** → emit ``declare_attackers`` with that creature's id.
        Multiple eligible creatures sort by id (deterministic) and all
        attack — but on the current ``slightly_bigger_deckspec`` only
        one Grizzly Bears is ever cast per game, so the set is at most
        a 1-element set.

      * **DECLARE_BLOCKERS, defender has 0 eligible blockers** → emit
        ``declare_blockers`` with empty assignments. The empty-set
        path exercises Rust's ``Action::DeclareBlockers { assignments
        = [] }`` arm and Python's ``DeclareBlockers(assignments=())``
        arm so both engines see the no-block dispatch fire (rather
        than just side-channel advancing past the step).

      * **COMBAT_DAMAGE step** → side-channel
        :func:`resolve_combat_damage_python` + the Rust mirror, then
        delegate to multi_turn_selector for the phase advance. The
        damage application + advance both happen in this single
        decision so the harness's per-step compare on COMBAT_DAMAGE
        sees the post-damage state.

      * **END_OF_COMBAT step** → side-channel
        :func:`clear_combat_both` to drop ``attacking`` / ``blocking``
        flags and reset Rust's ``self.attackers`` / ``self.blockers``,
        then delegate to multi_turn_selector for the advance. Without
        this Rust's attackers Vec would persist into the next turn.

    Anything not matching one of the four combat branches above falls
    back to :func:`cast_bears_selector` (which itself falls back to
    :func:`multi_turn_selector`).
    """
    from mtg_bot.turn import Step

    cur_step = py_state.step
    active_idx = py_state.active_player_idx
    ap = py_state.players[active_idx]

    if cur_step == Step.DECLARE_ATTACKERS:
        # Find non-sick non-tapped creatures the active player controls.
        # Filter intentionally narrow: only ``card_types`` containing
        # "Creature" (the Bears in this deck) — the Forests / Mountains
        # are also on the bf but lands aren't legal attackers. The
        # ``attacking is False`` guard prevents re-declaring on the
        # second visit to this step (the harness emits declare_attackers
        # ONCE; on the next selector call Bears is now tapped and
        # filtered out by the ``not o.tapped`` check anyway, but the
        # explicit ``not o.attacking`` guard is the load-bearing one
        # for the empty-attacker case).
        attackers = sorted(
            int(o.id) for o in py_state.battlefield
            if o.controller_id == active_idx
            and "Creature" in o.printing.card_types
            and not o.tapped
            and not o.summoning_sick
            and not getattr(o, "attacking", False)
        )
        if attackers:
            return {
                "kind": "declare_attackers",
                "attacker_ids": attackers,
            }
        # No eligible attackers (or already declared) — advance past
        # this step via the multi_turn fallback.

    elif cur_step == Step.DECLARE_BLOCKERS:
        # Emit ``declare_blockers`` with empty assignments AND
        # side-channel advance the phase in the same selector call. The
        # advance has to happen here (not on the next call) because
        # there's no observable state change from an empty-assignments
        # ``DeclareBlockers`` apply — without an in-call advance the
        # selector would re-emit on every visit and the harness would
        # spin forever in DECLARE_BLOCKERS step.
        #
        # The advance fires BEFORE step_both applies declare_blockers.
        # That's OK because Python's ``_declare_blockers`` doesn't gate
        # on ``state.step`` (it only reads per-object ``attacking`` /
        # ``blocking`` flags), and Rust's ``Action::DeclareBlockers``
        # dispatch goes through ``declare_blocker`` per-pair which
        # checks ``self.attackers.contains(&attacker_id)``, also not
        # gated on phase. The post-apply state has Python's step at
        # COMBAT_DAMAGE and Rust's phase at COMBAT_DAMAGE — both moved
        # together, parity preserved.
        attackers_present = any(
            getattr(o, "attacking", False) for o in py_state.battlefield
        )
        if attackers_present:
            advance_phase_python(py_state)
            rust_state.advance_phase()
            return {
                "kind": "declare_blockers",
                "assignments": [],
            }

    elif cur_step == Step.COMBAT_DAMAGE:
        # Side-channel: apply combat damage on BOTH engines, then run
        # the multi_turn fallback to advance past this step. The damage
        # mirror is harmless on a no-attackers state (Rust's
        # ``deal_combat_damage`` walks an empty Vec; Python's helper
        # short-circuits on ``any(attacking)``). Fire unconditionally
        # to keep the per-step compare's invariant simple — combat
        # damage either fires on both engines or on neither.
        fired_py = resolve_combat_damage_python(py_state)
        if fired_py:
            deal_combat_damage_rust(rust_state)
        # Fall through to multi_turn_selector to advance past
        # COMBAT_DAMAGE -> END_OF_COMBAT. The advance fires
        # AFTER the damage application above.

    elif cur_step == Step.END_OF_COMBAT:
        # Side-channel: clear ``attacking`` / ``blocking`` flags on
        # Python objects and ``self.attackers`` / ``self.blockers``
        # on Rust. Mirrors Python's ``simulate.run_step`` END_OF_COMBAT
        # hook. Fire BEFORE the advance so the post-step compare sees
        # the cleared state. (If we cleared AFTER the advance, the
        # comparison at END_OF_COMBAT would see lingering attackers on
        # Rust — invisible to the field-view 8-tuple, but a hazard for
        # future probes that observe via the legal_decisions emitter.)
        clear_combat_both(py_state, rust_state)
        # Fall through to multi_turn_selector to advance phase.

    # All non-combat branches (and the combat-branch fall-throughs)
    # delegate to cast_bears_selector, which in turn delegates to
    # multi_turn_selector. This composes the inheritance chain cleanly.
    return cast_bears_selector(py_state, rust_state, step_index)


# ---------------------------------------------------------------------------
# Phase 5 follow-up #6: multi_block_combat_selector — surface the audits'
# predicted CE6 (now claimed as CE9 if it surfaces) — combat damage
# assignment order.
#
# Builds on combat_selector with two narrowing changes:
#
#   1. **Only p0 attacks.** The base ``combat_selector`` lets either
#      active player declare attackers when they control an eligible
#      creature. With both players running the cast script on
#      :func:`multi_blocker_deckspec`, p1's first Bears comes off
#      summoning sickness at turn 8 — well before p0 attacks at turn 15.
#      If p1 attacks first, p1's Bears tap on declare and lose blocker
#      eligibility (CR 509.1b — a tapped creature can't block). To
#      preserve p1's two Bears as untapped blockers, this selector
#      suppresses p1's DECLARE_ATTACKERS emission entirely.
#
#   2. **Multi-block in REVERSE bf order.** When p0 attacks with a
#      Bears and p1 has 2+ eligible blockers on the battlefield, this
#      selector declares ALL of them as blockers but in REVERSE bf-
#      iteration order. The reversal is the load-bearing detail: it
#      forces Python's bf-order damage walk (``combat.py:389,405`` —
#      ``[o for o in state.battlefield if o.id in attacker.blocked_by]``)
#      and Rust's ``self.blockers`` declare-order walk
#      (``state_ops_combat.rs:865-868`` — ``self.blockers.iter().find_map``)
#      to pick DIFFERENT first blockers. Same attacker, same blockers,
#      same damage amount — but a different blocker dies on each side.
#
# **Predicted CE6 (now CE9 numerically). ** Per the audits
# (``docs/RUST_BF_ITERATION_AUDIT.md`` §3 and
# ``docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`` §3), the iteration sites at
# ``rust/src/state_ops_combat.rs:849, 962, 1025`` walk
# ``self.attackers`` / ``self.blockers`` Vecs in DECLARE PUSH order,
# while Python's counterpart walks ``state.battlefield`` filtered by
# ``attacker.blocked_by`` membership in BATTLEFIELD ETB order. On a
# single-attacker / single-blocker scene the order question is
# vacuous (one choice either way). On a single-attacker / two-blocker
# scene with blockers DECLARED in reverse-bf order, the two iteration
# orders pick different "first blockers" and the attacker's full
# power lands on a DIFFERENT blocker per engine.
#
# **Closure plan reference.** ``CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`` §3
# describes the closure: replace Rust's ``self.blockers``-Vec walk
# with a ``bf_iter_etb_sorted(state)``-filtered walk so the engine
# picks blockers in bf-ETB order (matching Python's bug for short-
# term smoke parity per Option A) or fix Python's combat.py to walk
# declare-order instead (Option B, the engineering-correct fix). The
# slice author's recommendation in the playbook is Option A. This
# selector ships the PROBE that surfaces the divergence; the closure
# itself is the next slice.
# ---------------------------------------------------------------------------


def multi_block_combat_selector(py_state, rust_state, step_index: int) -> dict:
    """Cross-engine smoke selector that drives p0's attack into p1's
    multi-block defense on :func:`multi_blocker_deckspec`.

    Two narrowing changes vs :func:`combat_selector`:

      * **DECLARE_ATTACKERS, active player == 0 only**: emit
        ``declare_attackers`` for p0's Bears. p1's
        DECLARE_ATTACKERS step falls through to multi_turn_selector
        (pass + advance). This keeps p1's Bears untapped so they
        remain eligible blockers when p0 attacks.

      * **DECLARE_BLOCKERS, defender has 2+ eligible blockers**:
        emit ``declare_blockers`` with the defender's eligible
        blockers ALL blocking the attacker — but in REVERSE
        bf-iteration order. This is the load-bearing detail that
        forces a CE6/CE9-shape divergence: Python's
        battlefield-order damage walk picks the
        *lower*-bf-position blocker, Rust's declare-order walk
        picks the *higher*-bf-position blocker (the one declared
        first).

    Anything not matching the two narrowed branches above falls back
    to :func:`combat_selector` (which itself delegates further to
    :func:`cast_bears_selector` and :func:`multi_turn_selector`).

    The selector is stateless — every branch is derived from
    observable state on each call. Same shape as the rest of the
    selector chain.
    """
    from mtg_bot.turn import Step

    cur_step = py_state.step
    active_idx = py_state.active_player_idx

    if cur_step == Step.DECLARE_ATTACKERS:
        # Narrowing change #1: only p0 may declare attackers. p1's
        # attackers fall through to the combat_selector fallback,
        # which inherits the cast_bears -> multi_turn chain and
        # advances past DECLARE_ATTACKERS via pass_priority. The
        # combat_selector's own DECLARE_ATTACKERS branch is NOT
        # entered when active_idx != 0 because we route through
        # combat_selector via cast_bears -> multi_turn here, not
        # via combat_selector at the top.
        if active_idx == 0:
            attackers = sorted(
                int(o.id) for o in py_state.battlefield
                if o.controller_id == active_idx
                and "Creature" in o.printing.card_types
                and not o.tapped
                and not o.summoning_sick
                and not getattr(o, "attacking", False)
            )
            if attackers:
                return {
                    "kind": "declare_attackers",
                    "attacker_ids": attackers,
                }
        # active_idx == 1 OR no eligible attackers: fall through to
        # cast_bears_selector. The cast_bears_selector branch for
        # DECLARE_ATTACKERS doesn't exist (only combat_selector has
        # one) — so this falls through to multi_turn_selector, which
        # advances phase past DECLARE_ATTACKERS and emits pass_priority.
        return cast_bears_selector(py_state, rust_state, step_index)

    if cur_step == Step.DECLARE_BLOCKERS:
        # Narrowing change #2: multi-block when defender has 2+
        # eligible blockers. The reverse-bf-order declaration is
        # the load-bearing detail.
        attackers_present = [
            o for o in py_state.battlefield
            if getattr(o, "attacking", False)
        ]
        if attackers_present:
            attacker = attackers_present[0]
            defender_idx = 1 - active_idx
            # Eligible blockers: defender's untapped non-sick creatures.
            # CR 509.1b — a tapped creature can't block. CR 302.1 —
            # summoning-sick creatures can't tap to attack, but CAN
            # block (sickness applies only to TAPPING for activation
            # and TAPPING from attacking, not to blocking itself).
            # However for the multi-block probe shape we want
            # confidence that both blockers will live through the
            # cross-engine compare, so we keep the filter conservative
            # (non-sick AND untapped).
            eligible_blocker_objs = [
                o for o in py_state.battlefield
                if o.controller_id == defender_idx
                and "Creature" in o.printing.card_types
                and not o.tapped
                and not o.summoning_sick
            ]
            if len(eligible_blocker_objs) >= 2:
                # Reverse-bf-order declaration: walk the bf in order
                # (eligible_blocker_objs is already bf-iteration-order
                # because list-comprehension preserves iteration order),
                # then reverse for the declare list.
                eligible_ids_in_bf_order = [
                    int(o.id) for o in eligible_blocker_objs
                ]
                declare_order = list(reversed(eligible_ids_in_bf_order))
                assignments = [
                    [bid, int(attacker.id)] for bid in declare_order
                ]
                # Same pre-advance pattern as the combat_selector's
                # DECLARE_BLOCKERS branch — empty OR non-empty,
                # declare_blockers leaves no observable state change
                # that would gate the next selector call's branch
                # (the per-object blocking flags aren't visible to
                # the selector's filter), so we advance phase here
                # to avoid spin.
                advance_phase_python(py_state)
                rust_state.advance_phase()
                return {
                    "kind": "declare_blockers",
                    "assignments": assignments,
                }
        # No attackers OR <2 blockers: fall through to combat_selector
        # which handles the empty / single-blocker case. Note this
        # delegates back to combat_selector's DECLARE_BLOCKERS branch
        # which handles the empty-assignments case.

    # All non-multi-block branches delegate to combat_selector.
    return combat_selector(py_state, rust_state, step_index)
