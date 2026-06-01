"""Echoing Deeps — per-card real-EoE cross-engine byte-equal probe
(BLOCKED → PROBED tier flip; Non-basic land substrate, Echoing Deeps
clone Cycle).

Echoing Deeps is a ``{0}`` Land — Cave in the Stellar Sights pool
(``data/stellar_sights.json``) carrying an ETB replacement:

    "You may have this land enter tapped as a copy of any land card in
    a graveyard, except it's a Cave in addition to its other types.
    {T}: Add {C}."

The live ``OracleParserCardSource`` maps the first line to
``CardPrinting.optional_copy_land_from_graveyard=True`` (verified in
``test_echoing_deeps_parser_claims_card`` below). On ETB the controller
MAY have the land enter as a copy of an eligible land card in ANY
graveyard; the entering object's printing rebinds to the target's land
with "Cave" injected into its subtypes, and the land enters TAPPED.
Declining (or no eligible graveyard land) enters the land normally.

**Substrate that landed alongside this probe (2026-05-31).**

  * **Rust** ``CardPrinting`` grew an
    ``optional_copy_land_from_graveyard: bool`` field
    (``rust/src/cards.rs``) + a ``parse_printing`` arm + an optional
    getter + the 3 synthetic-state literal sites; ``play_land``
    (``rust/src/state_ops_cast.rs``) grew the ETB-copy routing —
    locate the smallest-id eligible graveyard land across BOTH
    players' graveyards (the HEAD convention), mint a fresh registry
    printing derived from the target's printing with "Cave" injected
    into ``subtypes`` (reusing the same registry ``push_printing`` +
    ``GameObject.original_printing_id`` snapshot machinery the
    Thespian's Stage Phase-3C ``Effect::BecomesCopyOfTargetLand``
    resolve arm uses), rebind the entering object's ``printing_id``,
    and force ``tapped = true``.
  * **Bridge** ``CardDef`` grew an
    ``optional_copy_land_from_graveyard: bool`` field
    (``cross_engine.py``) + the registry-dict emit arm
    (``_spec_card_to_printing_dict``) + the
    ``_card_def_to_python_printing`` thread.

**Scope discipline (probe-driven, precedence-1).** This is a
PROBED-tier flip driven by a controlled cross-engine play_land — NOT a
loader_admits flip. Echoing Deeps stays loader-DECLINED for the bench
corpus (``_printing_to_card_def`` raises; ``_filter_deck_to_bridge_
supported`` returns ``[]``): the clone's downstream behavior over
arbitrary graveyard contents is not fully bridged, so admitting it into
production decks would risk silent mistranslation. The probe seeds the
graveyard with EXACTLY the eligible land so the ETB choice is forced
(HEAD == the only eligible land), making the Rust side's deterministic
HEAD chooser and the Python side's seeded agent agree byte-equal. See
``docs/SEARCH_LIMITATIONS.md``.

**Byte-equal observable.** The cross-engine field-view per-object
signature (``parity_smoke._zone_signature``) keys on ``printing.name``
+ ``tapped`` (+ damage / counters / attached / controller / id). On
copy, Echoing Deeps' object takes the copied land's NAME on both
engines (Python ``dataclasses.replace(target.printing, subtypes=...)``
preserves the target's ``name``; Rust clones the target's printing and
mutates only ``subtypes``), and enters TAPPED on both. The richer
copiable characteristics (subtypes incl. "Cave", produces) are asserted
Python-side (the same EEEE-idiom the Abandoned Campground /
Thespian's Stage probes use — the cross-engine name+tapped byte-equality
is the field-view contract; the Cave-injection + produces flow are
established by the Python-side ETB resolve + the shared registry-clone
machinery the Rust arm mirrors).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 4


# ---------------------------------------------------------------------------
# (1) Parser SoT — Echoing Deeps is parser-claimed and carries the
# ``optional_copy_land_from_graveyard`` flag.
# ---------------------------------------------------------------------------


def test_echoing_deeps_parser_claims_card():
    assert "Echoing Deeps" in _PRINTINGS, (
        "Echoing Deeps must be parser-claimed by the active CardSource"
    )


def test_echoing_deeps_printed_attrs():
    """Pins the basic printing surface: single-typed Land, Cave subtype,
    no mana cost, the ``optional_copy_land_from_graveyard`` clone flag
    set, no triggered / static abilities."""
    p = _PRINTINGS["Echoing Deeps"]
    assert p.card_types == ("Land",)
    assert "Cave" in p.subtypes
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.optional_copy_land_from_graveyard is True
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the optional_copy_land_from_graveyard flag
# round-trips byte-equal through the CardDef bridge.
# ---------------------------------------------------------------------------


def _echoing_deeps_card_def():
    """Build the CardDef the bridge would carry for Echoing Deeps (the
    real printing is loader-DECLINED so ``_printing_to_card_def`` raises;
    we construct the CardDef directly to exercise the field round-trip).
    """
    from mtg_bot.parity.cross_engine import CardDef

    return CardDef(
        name="Echoing Deeps",
        card_type="Land",
        mana_produced=("C",),
        subtypes=("Cave",),
        optional_copy_land_from_graveyard=True,
    )


def test_echoing_deeps_card_def_emits_clone_flag_in_registry_dict():
    """``_spec_card_to_printing_dict`` emits the
    ``optional_copy_land_from_graveyard`` key (only) when the CardDef
    carries the flag — the registry-dict shape Rust's ``parse_printing``
    consumes."""
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    cd = _echoing_deeps_card_def()
    d = _spec_card_to_printing_dict(cd)
    assert d.get("optional_copy_land_from_graveyard") is True

    # Back-compat: a CardDef WITHOUT the flag omits the key entirely
    # (byte-identical to every pre-substrate registry dict).
    from mtg_bot.parity.cross_engine import CardDef

    plain = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    d2 = _spec_card_to_printing_dict(plain)
    assert "optional_copy_land_from_graveyard" not in d2


def test_echoing_deeps_card_def_to_python_printing_threads_clone_flag():
    """``_card_def_to_python_printing`` threads the clone flag onto the
    rebuilt Python ``CardPrinting`` (default ``False`` when absent)."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = _echoing_deeps_card_def()
    p = _card_def_to_python_printing(cd)
    assert p.optional_copy_land_from_graveyard is True

    plain = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    p2 = _card_def_to_python_printing(plain)
    assert p2.optional_copy_land_from_graveyard is False


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier acceptance — Rust's parse_printing accepts
# the optional_copy_land_from_graveyard flag + the getter reads it back.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_optional_copy_land_from_graveyard():
    """Lockstep pin: Rust's ``register_printing`` accepts an
    Echoing-Deeps-shape dict carrying
    ``optional_copy_land_from_graveyard: True`` and the getter reads it
    back; a printing WITHOUT the key defaults to ``False`` (back-compat).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Echoing Deeps",
            "card_types": ["Land"],
            "subtypes": ["Cave"],
            "mana_cost": {"generic": 0},
            "optional_copy_land_from_graveyard": True,
        }
    )
    assert isinstance(pid, int)
    assert reg.get_printing_optional_copy_land_from_graveyard(pid) is True

    pid2 = reg.register_printing(
        {
            "name": "Forest",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "mana_cost": {"generic": 0},
        }
    )
    assert reg.get_printing_optional_copy_land_from_graveyard(pid2) is False


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Echoing Deeps printing's ETB-copy through play_land on
# BOTH engines on a controlled state (a Mountain seeded in the
# graveyard), asserting the entering permanent's name + tapped state are
# byte-equal cross-engine.
# ---------------------------------------------------------------------------


def _seed_python_copy_state(target_subtype: str = "Mountain"):
    """Build a Python state with the REAL Echoing Deeps printing in p0's
    hand and a ``target_subtype`` basic land in p0's graveyard. The
    agent picks the smallest-id graveyard land (the HEAD convention —
    matching Rust's deterministic chooser). Returns (state, ed_id)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import Zone
    from mtg_bot.agents import Agent

    class _PickHeadAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            if not legal_targets:
                return None
            # Smallest target id == HEAD (Rust's deterministic chooser).
            return min(legal_targets, key=lambda c: c[1])

    real = _PRINTINGS["Echoing Deeps"]
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    state = build_python_state(spec)
    state.players[0].agent = _PickHeadAgent()
    state.players[1].agent = _PickHeadAgent()
    if target_subtype is not None:
        gy_land = state.new_object(
            BASIC_LANDS[target_subtype], 0, Zone.GRAVEYARD,
        )
        state.players[0].graveyard.append(gy_land)
    ed = state.new_object(real, 0, Zone.HAND)
    state.players[0].hand.append(ed)
    return state, ed.id


def _seed_rust_copy_state(target_subtype: str = "Mountain"):
    """Build a Rust state with an Echoing-Deeps-shape carrier in p0's
    hand and a ``target_subtype`` basic land in p0's graveyard. Returns
    (rust_state, ed_id). The Rust play_land chooser is deterministic
    (smallest-id eligible graveyard land == HEAD)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    if target_subtype is not None:
        rs.register_and_inject_object(
            {
                "name": target_subtype,
                "card_types": ["Land"],
                "subtypes": [target_subtype],
                "mana_cost": {"generic": 0},
                "produces": [["R", 1]] if target_subtype == "Mountain"
                else [["G", 1]],
            },
            0,
            ZONE_GRAVEYARD,
        )
    ed = rs.register_and_inject_object(
        {
            "name": "Echoing Deeps",
            "card_types": ["Land"],
            "subtypes": ["Cave"],
            "mana_cost": {"generic": 0},
            "optional_copy_land_from_graveyard": True,
        },
        0,
        ZONE_HAND,
    )
    return rs, ed


@_rust_skip
def test_cross_engine_real_eoe_echoing_deeps_copy_land_from_graveyard_parity():
    """**GENUINE real-EoE cross-engine probe — Echoing Deeps ETB copy
    line. PROBED-tier flip (BLOCKED → PROBED).**

    Seeds a Mountain in p0's graveyard + the REAL parsed Echoing Deeps
    printing in p0's hand on BOTH engines, then drives ``play_land``.
    The ETB-copy replacement fires:

      * Python (``actions._offer_echoing_deeps_copy``): the seeded
        agent picks the lone graveyard Mountain;
        ``card.printing = dataclasses.replace(Mountain.printing,
        subtypes=("Mountain", "Cave"))``; ``card.tapped = True``.
      * Rust (``state_ops_cast::play_land``): the deterministic HEAD
        chooser picks the lone graveyard Mountain; mints a fresh
        registry printing = Mountain's printing + "Cave" subtype;
        rebinds the entering object's ``printing_id``;
        ``tapped = true``.

    Post-play, the entering permanent's NAME == "Mountain" and
    ``tapped == True`` on BOTH engines — the field-view per-object
    signature (``_zone_signature`` keys on ``printing.name`` + tapped)
    is byte-equal. Python-side richer assertions confirm the
    Cave-injection + Mountain's produce surface flow through.
    """
    from mtg_bot.actions import apply_action, PlayLand

    real = _PRINTINGS.get("Echoing Deeps")
    if real is None:
        pytest.skip("Echoing Deeps absent from active CardSource")
    assert real.optional_copy_land_from_graveyard is True

    # ---- Python: play the real Echoing Deeps; copy the gy Mountain.
    py_state, ed_id = _seed_python_copy_state("Mountain")
    apply_action(py_state, 0, PlayLand(card_id=ed_id))
    py_bf = py_state.battlefield
    assert len(py_bf) == 1
    py_obj = py_bf[0]
    assert py_obj.printing.name == "Mountain", (
        f"Python: Echoing Deeps must enter as a copy named 'Mountain'; "
        f"got {py_obj.printing.name!r}"
    )
    assert py_obj.tapped is True, "Python: the clone must enter tapped"
    # Cave injection + Mountain's surface (Python-side richer view).
    assert "Cave" in py_obj.printing.subtypes
    assert "Mountain" in py_obj.printing.subtypes
    assert py_obj.printing.produces == frozenset({"R"}), (
        f"Python: the clone must carry Mountain's produce surface "
        f"({{'R'}}); got {py_obj.printing.produces}"
    )

    # ---- Rust: play the Echoing-Deeps carrier; copy the gy Mountain.
    rs, rs_ed_id = _seed_rust_copy_state("Mountain")
    ok = rs.play_land(rs_ed_id, 0)
    assert ok is True
    rs_bf = rs.battlefield_snapshot()
    assert len(rs_bf) == 1
    rs_obj = rs_bf[0]
    assert rs_obj["printing_name"] == "Mountain", (
        f"Rust: Echoing Deeps must enter as a copy named 'Mountain'; "
        f"got {rs_obj['printing_name']!r}"
    )
    assert rs_obj["tapped"] is True, "Rust: the clone must enter tapped"

    # ---- Cross-engine byte-equal: name + tapped (the field-view
    # per-object signature axes) match on BOTH engines.
    assert py_obj.printing.name == rs_obj["printing_name"], (
        f"Cross-engine clone NAME mismatch: py="
        f"{py_obj.printing.name!r} rust={rs_obj['printing_name']!r}"
    )
    assert bool(py_obj.tapped) == bool(rs_obj["tapped"]), (
        f"Cross-engine clone TAPPED mismatch: py={py_obj.tapped} "
        f"rust={rs_obj['tapped']}"
    )


@_rust_skip
def test_cross_engine_real_eoe_echoing_deeps_no_eligible_graveyard_land_parity():
    """**GENUINE real-EoE cross-engine probe — Echoing Deeps no-copy
    (empty graveyard) line.**

    With NO eligible land in any graveyard, the ETB-copy replacement
    declines on BOTH engines and Echoing Deeps enters NORMALLY (untapped
    — Echoing Deeps prints no static ``enters_tapped`` flag and no
    conditional-tapped threshold). The entering permanent's NAME stays
    "Echoing Deeps" and ``tapped == False`` on both engines — byte-equal.
    """
    from mtg_bot.actions import apply_action, PlayLand

    real = _PRINTINGS.get("Echoing Deeps")
    if real is None:
        pytest.skip("Echoing Deeps absent from active CardSource")

    # ---- Python: empty graveyard → no copy.
    py_state, ed_id = _seed_python_copy_state(target_subtype=None)
    assert all(len(p.graveyard) == 0 for p in py_state.players)
    apply_action(py_state, 0, PlayLand(card_id=ed_id))
    py_bf = py_state.battlefield
    assert len(py_bf) == 1
    py_obj = py_bf[0]
    assert py_obj.printing.name == "Echoing Deeps", (
        f"Python: with no eligible graveyard land, Echoing Deeps must "
        f"enter normally; got {py_obj.printing.name!r}"
    )
    assert py_obj.tapped is False, (
        "Python: Echoing Deeps enters UNTAPPED on the no-copy path "
        "(no static enters_tapped, no conditional threshold)"
    )

    # ---- Rust: empty graveyard → no copy.
    rs, rs_ed_id = _seed_rust_copy_state(target_subtype=None)
    ok = rs.play_land(rs_ed_id, 0)
    assert ok is True
    rs_bf = rs.battlefield_snapshot()
    assert len(rs_bf) == 1
    rs_obj = rs_bf[0]
    assert rs_obj["printing_name"] == "Echoing Deeps", (
        f"Rust: with no eligible graveyard land, Echoing Deeps must "
        f"enter normally; got {rs_obj['printing_name']!r}"
    )
    assert rs_obj["tapped"] is False, (
        "Rust: Echoing Deeps enters UNTAPPED on the no-copy path"
    )

    # ---- Cross-engine byte-equal: name + tapped match on both engines.
    assert py_obj.printing.name == rs_obj["printing_name"]
    assert bool(py_obj.tapped) == bool(rs_obj["tapped"])
