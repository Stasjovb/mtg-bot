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

    Mirrors :func:`apply_action`'s dispatch table. Supported kinds in
    the first slice:

    * ``pass_priority`` → ``PassPriority()``
    * ``play_land`` → ``PlayLand(card_id=...)``
    * ``cast_spell`` → ``CastSpell(card_id=...)``

    Unknown kinds raise ``ValueError`` to mirror Rust's strict-parse
    contract.
    """
    from mtg_bot.actions import CastSpell, PassPriority, PlayLand

    kind = action_dict.get("kind")
    if kind == "pass_priority":
        return PassPriority()
    if kind == "play_land":
        return PlayLand(card_id=int(action_dict["card_id"]))
    if kind == "cast_spell":
        return CastSpell(card_id=int(action_dict["card_id"]))
    raise ValueError(
        f"unsupported action kind for cross-engine step: {kind!r} "
        f"(action dict: {action_dict!r})"
    )


def step_both(py_state, rust_state, action_dict: dict) -> CrossEngineStep:
    """Apply ``action_dict`` to both engines and compare post-step views.

    The action drives a single decision; both sides are mutated in
    place. Returns a :class:`CrossEngineStep` carrying the views +
    the per-field divergence list. The step index is left at -1 by
    default — the outer harness fills it in.
    """
    from mtg_bot.actions import apply_action as py_apply_action

    py_action = _dict_to_python_action(action_dict)
    # Python's apply_action takes (state, player_id, action). We use
    # priority_player_idx as the actor — matches Rust's
    # ``apply_action`` which reads ``priority_player`` for the actor.
    py_apply_action(py_state, py_state.priority_player_idx, py_action)
    rust_state.apply_action(action_dict)

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
