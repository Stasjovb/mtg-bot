"""Consult the Star Charts — per-card real-EoE cross-engine byte-equal
probe (BLOCKED → PROBED tier flip; Kicker-rider + impulse-look-X-by-
lands + bottom-rest-random closure).

Consult the Star Charts is a ``{1}{U}`` Instant in the EoE pool
(``data/edge_of_eternities.json``) with the Kicker mechanic:

    "Kicker {1}{U} (You may pay an additional {1}{U} as you cast this
     spell.)
     Look at the top X cards of your library, where X is the number of
     lands you control. Put one of those cards into your hand. If this
     spell was kicked, put two of those cards into your hand instead.
     Put the rest on the bottom of your library in a random order."

The parser maps it (``cards/parser/effects.py``) to the bespoke
``ConsultTheStarChartsEffect`` (``effects/bespoke.py:1139``) as the
printing's ``spell_effect``, with ``kicker_cost = ManaCost(generic=1,
colored=(('U', 1),))`` / ``kicker_cost_str = '{1}{U}'``. It is
**kicker-only** — there is NO warp cost on this printing
(``warp_cost is None``).

**Why this card was BLOCKED.** It is multi-gated in POOL_PARITY:
"Kicker / Impending cost" (the declined cost-mechanic) AND
"Effect-uncovered (no covered Rust counterpart)" — the bespoke
``ConsultTheStarChartsEffect`` had no Rust ``Effect::`` variant. This
slice ships the Rust ``Effect::ConsultTheStarCharts`` variant + the
``was_kicked`` StackItem flag + the resolve-time
``current_resolve_was_kicked`` transient, mirroring Python's
``StackItem.kicked`` → ``state.resolving_kicked`` swap. PROBED is
precedence-1 (probe-driven, no loader admit): the kicker cost-mechanic
gate is sidestepped by driving the kicked branch via the
``set_stack_top_was_kicked`` synthetic setter rather than the deferred
kicker mana-payment cast pipeline (which ``cast_spell_noncreature``
does not yet model — documented in SEARCH_LIMITATIONS.md).

**Python already models kicker end-to-end** — the ``CastSpell.kicked``
flag, the ``legal.py`` kicked/unkicked dual emission, the
``StackItem.kicked`` field, and the ``state.resolving_kicked`` swap at
resolve. NO Python change was needed; this slice is Rust + bridge +
probe only.

This probe drives the **ACTUAL parsed Consult the Star Charts
printing** on the Python side (its genuine ``spell_effect``) and a
bridged synthetic carrier on Rust, asserting byte-equality on the
post-resolve hand + library zones across BOTH cast modes:

  * **Unkicked** — keep 1; rest to the bottom in random order.
  * **Kicked** — keep 2; rest to the bottom in random order.

and across the random-bottom path (a shared ``random.Random`` threaded
into both engines so the Fisher-Yates bottom-shuffle is byte-identical
via ``external_rng::next_below``).
"""

from __future__ import annotations

import importlib.util
import random

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.bespoke import ConsultTheStarChartsEffect


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2


_CONSULT_SYNTH = {
    "name": "Consult the Star Charts",
    "card_types": ["Instant"],
    "mana_cost": {"generic": 1, "U": 1},
    "effects": [{"kind": "consult_the_star_charts_effect"}],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Consult the Star Charts is parser-claimed, is an
# Instant, carries the bespoke ConsultTheStarChartsEffect spell_effect,
# and is kicker-only ({1}{U} kicker, no warp).
# ---------------------------------------------------------------------------


def test_consult_the_star_charts_parser_claims_card():
    assert "Consult the Star Charts" in _PRINTINGS, (
        "Consult the Star Charts must be parser-claimed by the active "
        "CardSource"
    )


def test_consult_the_star_charts_printed_attrs():
    p = _PRINTINGS["Consult the Star Charts"]
    assert p.is_instant, "Consult the Star Charts is an Instant"
    assert p.mana_cost.generic == 1 and p.mana_cost.colored == (("U", 1),), (
        "Consult's cast cost is {1}{U}"
    )


def test_consult_the_star_charts_is_kicker_only_not_warp():
    """Verify-first (the scout has mis-framed cost-mechanic walls
    before): Consult carries the Kicker cost mechanic ({1}{U}), and is
    KICKER-ONLY — there is NO warp cost on this printing."""
    p = _PRINTINGS["Consult the Star Charts"]
    assert p.kicker_cost is not None, "Consult carries a kicker cost"
    assert p.kicker_cost_str == "{1}{U}", (
        f"Consult's kicker cost is {{1}}{{U}}; got {p.kicker_cost_str!r}"
    )
    assert p.kicker_cost.generic == 1 and p.kicker_cost.colored == (
        ("U", 1),
    )
    assert getattr(p, "warp_cost", None) is None, (
        "Consult the Star Charts is kicker-ONLY — it must NOT carry a "
        "warp cost (the verify-first wall-framing check)"
    )


def test_consult_the_star_charts_spell_effect_shape():
    p = _PRINTINGS["Consult the Star Charts"]
    assert isinstance(p.spell_effect, ConsultTheStarChartsEffect), (
        f"Consult's spell_effect must be the bespoke "
        f"ConsultTheStarChartsEffect; got {type(p.spell_effect).__name__}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the consult_the_star_charts_effect dict shape
# bridges to the bespoke Python ConsultTheStarChartsEffect, byte-equal
# to the genuine parsed spell_effect.
# ---------------------------------------------------------------------------


def test_consult_the_star_charts_bridge_arm_round_trip():
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "consult_the_star_charts_effect"}
    )
    assert isinstance(bridged, ConsultTheStarChartsEffect)
    # Effect-level byte-equality between the parsed real-EoE printing's
    # spell_effect and the bridged Effect.
    p = _PRINTINGS["Consult the Star Charts"]
    assert p.spell_effect == bridged, (
        f"Consult's spell_effect must be byte-equal to the bridged "
        f"Effect; got parsed={p.spell_effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's parse_effect accepts the
# consult_the_star_charts_effect dict on an Instant carrier, and the
# was_kicked StackItem flag getter/setter round-trips.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_consult_synthetic_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_CONSULT_SYNTH)
    assert isinstance(pid, int)


@_rust_skip
def test_rust_was_kicked_stack_flag_round_trips():
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    spell_id = rs.register_and_inject_object(_CONSULT_SYNTH, 0, ZONE_HAND)
    rs.push_to_stack(spell_id, 0)
    # Default push is unkicked.
    assert rs.stack_top_was_kicked() is False
    rs.set_stack_top_was_kicked(True)
    assert rs.stack_top_was_kicked() is True
    rs.set_stack_top_was_kicked(False)
    assert rs.stack_top_was_kicked() is False


# ---------------------------------------------------------------------------
# Shared driver helpers for the byte-equal probes.
# ---------------------------------------------------------------------------


def _build_rust(land_names, library_names, *, shared_seed=None):
    """Rust state: p0 controls the given lands on the battlefield + the
    given library (top-to-bottom). Returns (rs, spell_id)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    if shared_seed is not None:
        rs.set_external_rng(random.Random(shared_seed))
    for i, ln in enumerate(land_names):
        rs.register_and_inject_object(
            {"name": ln, "card_types": ["Land"], "supertypes": ["Basic"]},
            0,
            ZONE_BATTLEFIELD,
        )
    # NOTE: ``register_and_inject_object`` into the library injects at
    # the TOP (the snapshot's top-to-bottom order is the REVERSE of the
    # injection order — injecting [A, B, C] yields top-to-bottom
    # [C, B, A]). Python's ``build_python`` appends in list order
    # (first-listed = top). To make both engines share the same
    # top-to-bottom library for the same ``library_names`` list, inject
    # into Rust in REVERSE so the last-injected (= top) is
    # ``library_names[0]``.
    for nm in reversed(library_names):
        rs.register_and_inject_object(
            {"name": nm, "card_types": ["Creature"], "power": 1,
             "toughness": 1},
            0,
            ZONE_LIBRARY,
        )
    spell_id = rs.register_and_inject_object(_CONSULT_SYNTH, 0, ZONE_HAND)
    return rs, spell_id


def _build_python(land_names, library_names, *, shared_seed=None):
    """Python state with the GENUINE Consult printing in p0's hand, the
    given lands on p0's battlefield, and the given library top-to-
    bottom. Returns (py_state, consult_obj)."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    real = _PRINTINGS["Consult the Star Charts"]
    state = GameState()
    state.players = [Player(id=0), Player(id=1)]
    state.step = Step.UNTAP
    if shared_seed is not None:
        state.rng = random.Random(shared_seed)

    land_printing = CardPrinting(
        name="__land__",  # overridden per-land below
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Basic Land",
        supertypes=("Basic",),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    for ln in land_names:
        lp = land_printing.__class__(
            **{**land_printing.__dict__, "name": ln}
        )
        obj = state.new_object(lp, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.etb_timestamp = state.next_timestamp
        state.next_timestamp += 1
        state.battlefield.append(obj)

    fodder = CardPrinting(
        name="__fodder__",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    for nm in library_names:
        fp = fodder.__class__(**{**fodder.__dict__, "name": nm})
        obj = state.new_object(fp, owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)

    consult_obj = state.new_object(real, owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(consult_obj)
    return state, consult_obj


def _resolve_python(py_state, consult_obj, *, kicked):
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone

    py_state.players[0].hand.remove(consult_obj)
    consult_obj.zone = Zone.STACK
    py_state.stack.append(
        StackItem(source=consult_obj, controller_id=0, kicked=kicked)
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)


def _resolve_rust(rs, spell_id, *, kicked):
    rs.push_to_stack(spell_id, 0)
    if kicked:
        rs.set_stack_top_was_kicked(True)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


def _rust_zone(rs, snapshot_fn):
    return [e["printing_name"] for e in snapshot_fn(0)]


def _py_hand(py_state):
    return [o.printing.name for o in py_state.players[0].hand]


def _py_lib(py_state):
    return [o.printing.name for o in py_state.players[0].library]


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal — UNKICKED (keep 1),
# deterministic (rest < 2 so no shuffle).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_consult_the_star_charts_unkicked_parity():
    """**GENUINE real-EoE cross-engine probe — Consult the Star Charts,
    UNKICKED.** X = 2 lands; library top-to-bottom = [A, B, C]. Examine
    top 2 [A, B]; keep 1 (A) → hand; the rest [B] (single card → no
    shuffle, deterministic) → bottom. Library after = [C, B] on both
    engines. Drives the GENUINE parsed Consult printing's spell_effect
    on Python (StackItem.kicked=False) and the bridged carrier on Rust
    (default-unkicked push)."""
    real = _PRINTINGS.get("Consult the Star Charts")
    if real is None:
        pytest.skip("Consult the Star Charts absent from active CardSource")

    lands = ["Island", "Island"]
    lib = ["A", "B", "C"]

    rs, spell_id = _build_rust(lands, lib)
    py_state, consult = _build_python(lands, lib)

    _resolve_rust(rs, spell_id, kicked=False)
    _resolve_python(py_state, consult, kicked=False)

    rust_hand = _rust_zone(rs, rs.hand_snapshot)
    rust_lib = _rust_zone(rs, rs.library_snapshot)
    py_hand = _py_hand(py_state)
    py_lib = _py_lib(py_state)

    # Keep 1: the topmost examined card A goes to hand.
    assert py_hand == ["A"], f"Python hand should be [A]; got {py_hand}"
    assert rust_hand == ["A"], f"Rust hand should be [A]; got {rust_hand}"
    # Library: the unexamined C stays on top; the non-kept examined B is
    # bottomed (single card → deterministic).
    assert py_lib == ["C", "B"], f"Python lib should be [C, B]; got {py_lib}"
    assert rust_lib == ["C", "B"], f"Rust lib should be [C, B]; got {rust_lib}"
    # Cross-engine byte-equality.
    assert rust_hand == py_hand
    assert rust_lib == py_lib


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal — KICKED (keep 2),
# deterministic (rest < 2).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_consult_the_star_charts_kicked_parity():
    """**GENUINE real-EoE cross-engine probe — Consult the Star Charts,
    KICKED.** Same staging as the unkicked probe (X = 2; library
    [A, B, C]); examine top 2 [A, B]; ``was_kicked`` → keep 2 [A, B] →
    hand; the rest is EMPTY (no shuffle). Library after = [C] on both
    engines. This is the load-bearing kicked-branch assertion: Python
    drives ``StackItem.kicked=True`` → ``state.resolving_kicked``; Rust
    drives ``set_stack_top_was_kicked(True)`` →
    ``current_resolve_was_kicked``. A naive port that ignored the
    kicked flag would keep only 1 here (a §2 silent divergence)."""
    real = _PRINTINGS.get("Consult the Star Charts")
    if real is None:
        pytest.skip("Consult the Star Charts absent from active CardSource")

    lands = ["Island", "Island"]
    lib = ["A", "B", "C"]

    rs, spell_id = _build_rust(lands, lib)
    py_state, consult = _build_python(lands, lib)

    _resolve_rust(rs, spell_id, kicked=True)
    _resolve_python(py_state, consult, kicked=True)

    rust_hand = _rust_zone(rs, rs.hand_snapshot)
    rust_lib = _rust_zone(rs, rs.library_snapshot)
    py_hand = _py_hand(py_state)
    py_lib = _py_lib(py_state)

    assert py_hand == ["A", "B"], f"Python hand should be [A, B]; got {py_hand}"
    assert rust_hand == ["A", "B"], f"Rust hand should be [A, B]; got {rust_hand}"
    assert py_lib == ["C"], f"Python lib should be [C]; got {py_lib}"
    assert rust_lib == ["C"], f"Rust lib should be [C]; got {rust_lib}"
    assert rust_hand == py_hand
    assert rust_lib == py_lib


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal — KICKED with a
# RANDOM-ORDER bottom (rest >= 2). Threads ONE shared random.Random into
# both engines so the Fisher-Yates bottom-shuffle is byte-identical
# (Python random.Random.shuffle vs Rust external_rng::next_below).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_consult_the_star_charts_kicked_random_bottom_parity():
    """**GENUINE real-EoE cross-engine probe — Consult the Star Charts,
    KICKED, RANDOM-ORDER bottom (the load-bearing RNG byte-equality).**

    X = 5 lands; library top-to-bottom = [A, B, C, D, E, F]. Examine
    top 5 [A..E]; kicked → keep 2 [A, B] → hand; the rest [C, D, E]
    (THREE cards) is put on the BOTTOM in a RANDOM order. F (unexamined)
    stays on top. The post-resolve library is [F, <shuffled C,D,E>].

    Both engines consume the SAME shared ``random.Random(seed)`` for the
    bottom-shuffle: Python ``state.rng.shuffle(remaining)``; Rust the
    external-rng Fisher-Yates via ``external_rng::next_below`` (#16
    ``_randbelow`` callback). Two ``random.Random(seed)`` at the same MT
    position produce a byte-identical permutation — if this FAILS the
    two engines are NOT consuming the same draw stream in the same order
    (the §2 stream-position desync contract)."""
    real = _PRINTINGS.get("Consult the Star Charts")
    if real is None:
        pytest.skip("Consult the Star Charts absent from active CardSource")

    seed = 0xC0FFEE
    lands = ["Island"] * 5
    lib = ["A", "B", "C", "D", "E", "F"]

    rs, spell_id = _build_rust(lands, lib, shared_seed=seed)
    py_state, consult = _build_python(lands, lib, shared_seed=seed)

    _resolve_rust(rs, spell_id, kicked=True)
    _resolve_python(py_state, consult, kicked=True)

    rust_hand = _rust_zone(rs, rs.hand_snapshot)
    rust_lib = _rust_zone(rs, rs.library_snapshot)
    py_hand = _py_hand(py_state)
    py_lib = _py_lib(py_state)

    # Keep 2: A, B to hand on both.
    assert py_hand == ["A", "B"], f"Python hand should be [A, B]; got {py_hand}"
    assert rust_hand == ["A", "B"]
    # Library: F on top, then the shuffled {C, D, E} block at the bottom.
    assert py_lib[0] == "F", f"unexamined F should stay on top; got {py_lib}"
    assert sorted(py_lib[1:]) == ["C", "D", "E"], (
        f"the non-kept examined cards should be bottomed; got {py_lib}"
    )
    # The load-bearing cross-engine byte-equality on the RANDOM order.
    assert rust_lib == py_lib, (
        f"Rust and Python must produce the SAME random bottom order "
        f"(shared random.Random stream); py={py_lib!r}, rust={rust_lib!r}"
    )
    assert rust_hand == py_hand
