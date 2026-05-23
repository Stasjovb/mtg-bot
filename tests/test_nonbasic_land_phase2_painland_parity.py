"""Non-basic land substrate — Phase 2 painland conditional parity tests.

**Spec:** ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §3 Phase 2
(2026-05-23). Closes sub-shape C — the Duskmourn conditional-painland
cycle. The substrate that landed alongside these tests:

* **Python** already had ``CardPrinting.enters_tapped_unless_any_
  player_life_at_most`` and the ``actions._play_land`` check; the parser
  set it on 9 (10 incl. Strangled Cemetery) Duskmourn painlands.
* **Rust** ``CardPrinting`` carries the new
  ``enters_tapped_unless_any_player_life_at_most`` field;
  ``parse_printing`` reads it; ``state_ops_cast::play_land`` routes
  the conditional-tapped check before the move (the freshly-pushed
  object lands with the correct ``tapped`` flag BEFORE
  ``drain_pending_etb_dispatches`` fires).
* **Bridge** ``CardDef`` carries the field; the registry-dict emitter
  threads it to Rust when ``> 0``; ``_card_def_to_python_printing``
  threads it back when materializing the Python printing.
* **Loader admit predicate**
  ``_printing_is_bridge_nonbasic_painland_conditional`` admits the
  parser-flattened painland shape (dual-color, threshold==13, no
  other riders) and rejects every other land sub-shape.

The Phase-2 substrate is reusable for any future EoE printing with
the same shape; the 9 (10) Duskmourn painlands have 0 EoE 17lands
decks today (off-set DSK cards in the merged pool), so the bench
signal yield is 0 — card-count fidelity only.
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    build_matched_states,
    build_rust_registry,
    _card_def_to_python_printing,
    _spec_card_to_printing_dict,
)
from mtg_bot.parity.trajectory import (
    _filter_deck_to_bridge_supported,
    _printing_is_bridge_basic_land,
    _printing_is_bridge_nonbasic_mana_land,
    _printing_is_bridge_nonbasic_painland_conditional,
    _printing_is_bridge_simple_tapped_mana_land,
    _printing_to_card_def,
)


# The 9 Duskmourn painlands the spec calls out — the canonical Phase-2
# admit set. Strangled Cemetery is the 10th cycle member (B/G) the
# round-59 audit missed; it shares the same shape and the predicate
# admits it too. Both groups are pinned below.
_PHASE_2_PAINLANDS: tuple[tuple[str, str, str], ...] = (
    ("Abandoned Campground", "U", "W"),
    ("Bleeding Woods", "G", "R"),
    ("Etched Cornfield", "G", "W"),
    ("Lakeside Shack", "G", "U"),
    ("Murky Sewer", "B", "U"),
    ("Neglected Manor", "B", "W"),
    ("Peculiar Lighthouse", "R", "U"),
    ("Raucous Carnival", "R", "W"),
    ("Razortrap Gorge", "B", "R"),
)
_PHASE_2_BONUS_TENTH_PAINLAND: tuple[str, str, str] = (
    "Strangled Cemetery",
    "B",
    "G",
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _parser_printings():
    from mtg_bot.cards.parser.source import OracleParserCardSource

    return OracleParserCardSource().get_printings()


# ---------------------------------------------------------------------------
# §1. Parser SoT — the 9 named painlands carry the field == 13
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,c1,c2",
    list(_PHASE_2_PAINLANDS),
)
def test_parser_sot_painland_field_is_13(name: str, c1: str, c2: str):
    """The live parser emits each named painland with
    ``enters_tapped_unless_any_player_life_at_most == 13`` and the
    expected dual ``produces`` colors — the SoT every other test
    layer round-trips through.
    """
    pr = _parser_printings()[name]
    assert pr.enters_tapped_unless_any_player_life_at_most == 13
    assert pr.produces == frozenset({c1, c2})
    # The painlands carry no plain `enters_tapped` (the parser
    # structures the conditional INSTEAD).
    assert pr.enters_tapped is False
    # The predicate guard requires no other riders.
    assert pr.activated_abilities == ()
    assert pr.triggered_abilities == ()
    assert pr.static_abilities == ()
    assert not pr.keywords


def test_parser_sot_bonus_tenth_painland_also_landed():
    """The audit's missed 10th cycle member (Strangled Cemetery, B/G)
    has the same parser shape — admitted by the predicate too. Pinned
    so a future audit pass can credit Phase 2 with the full cycle.
    """
    name, c1, c2 = _PHASE_2_BONUS_TENTH_PAINLAND
    pr = _parser_printings()[name]
    assert pr.enters_tapped_unless_any_player_life_at_most == 13
    assert pr.produces == frozenset({c1, c2})


# ---------------------------------------------------------------------------
# §2. Admit-gate predicate — accepts the 9 + bonus, rejects siblings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,c1,c2", list(_PHASE_2_PAINLANDS))
def test_admit_predicate_accepts_each_painland(name: str, c1: str, c2: str):
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is True


def test_admit_predicate_accepts_bonus_tenth_painland():
    name, _c1, _c2 = _PHASE_2_BONUS_TENTH_PAINLAND
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is True


@pytest.mark.parametrize(
    "name",
    # Round-60 untapped shocklands — sub-shape A.
    [
        "Breeding Pool",
        "Watery Grave",
        "Stomping Ground",
        "Godless Shrine",
        "Sacred Foundry",
    ],
)
def test_admit_predicate_rejects_round60_shocklands(name: str):
    """Round-60 untapped shocklands are not painlands — the painland
    predicate must reject them (they carry no positive threshold).
    The round-60 predicate continues to own them.
    """
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is False
    # Belt-and-braces: the round-60 predicate still admits them.
    assert _printing_is_bridge_nonbasic_mana_land(pr) is True


@pytest.mark.parametrize(
    "name",
    # Round-85 mono-color tapped Planet lands — sub-shape B.
    [
        "Adagia, Windswept Bastion",
        "Evendo, Waking Haven",
        "Kavaron, Memorial World",
        "Susur Secundi, Void Altar",
        "Uthros, Titanic Godcore",
    ],
)
def test_admit_predicate_rejects_round85_planet_lands(name: str):
    """Round-85 Planet lands are mono-color tapped lands — the
    painland predicate must reject them (no positive threshold).
    The round-85 predicate continues to own them.
    """
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is False
    # Belt-and-braces: the round-85 predicate still admits them.
    assert _printing_is_bridge_simple_tapped_mana_land(pr) is True


@pytest.mark.parametrize(
    "name",
    # Other land sub-shapes that should NOT be admitted by this
    # predicate (sub-shapes D, E, F — Secluded Starforge,
    # Cathedral of War, Echoing Deeps).
    ["Secluded Starforge", "Cathedral of War", "Echoing Deeps"],
)
def test_admit_predicate_rejects_other_nonbasic_lands(name: str):
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is False


def test_admit_predicate_rejects_basic_land():
    """Basic lands have a different supertype gate — owned by
    ``_printing_is_bridge_basic_land``, not this predicate.
    """
    pr = _parser_printings()["Forest"]
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is False
    assert _printing_is_bridge_basic_land(pr) is True


# ---------------------------------------------------------------------------
# §3. CardDef arm — `_printing_to_card_def` emits the field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,c1,c2", list(_PHASE_2_PAINLANDS))
def test_printing_to_card_def_carries_threshold(name: str, c1: str, c2: str):
    """``_printing_to_card_def`` builds a CardDef carrying the
    conditional-tapped threshold field. The mana-produced tuple is
    the same sorted-color shape the shockland / Planet land arms emit.
    """
    pr = _parser_printings()[name]
    cd = _printing_to_card_def(pr)
    assert cd.card_type == "Land"
    assert cd.mana_produced == tuple(sorted({c1, c2}))
    assert cd.enters_tapped_unless_any_player_life_at_most == 13
    # All other CardDef fields default — no riders thread through.
    assert cd.mana_cost_generic == 0
    assert cd.mana_cost_colored == ()
    assert cd.triggered_abilities == ()
    assert cd.keywords == ()


# ---------------------------------------------------------------------------
# §4. Bridge round-trip — Python -> registry-dict -> Python byte-equal
# ---------------------------------------------------------------------------


def _expected_painland_card_def(name: str, c1: str, c2: str) -> CardDef:
    return CardDef(
        name=name,
        card_type="Land",
        mana_produced=tuple(sorted({c1, c2})),
        enters_tapped_unless_any_player_life_at_most=13,
    )


def test_bridge_registry_dict_emits_threshold_key():
    """The CardDef -> registry-dict emitter writes the
    ``enters_tapped_unless_any_player_life_at_most`` key when set.
    Pre-substrate Rust dicts never carried this key; pinned so a
    future emitter-side regression that drops the key surfaces
    immediately as a test failure.
    """
    cd = _expected_painland_card_def("Murky Sewer", "B", "U")
    d = _spec_card_to_printing_dict(cd)
    assert d["enters_tapped_unless_any_player_life_at_most"] == 13


def test_bridge_registry_dict_omits_threshold_when_zero():
    """A non-painland CardDef (the back-compat shape) carries no
    threshold key in the registry dict — keeps every pre-substrate
    bridge call byte-identical.
    """
    cd = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    d = _spec_card_to_printing_dict(cd)
    assert "enters_tapped_unless_any_player_life_at_most" not in d


@pytest.mark.parametrize("name,c1,c2", list(_PHASE_2_PAINLANDS))
def test_bridge_python_carddef_to_python_printing_round_trip(
    name: str, c1: str, c2: str,
):
    """CardDef -> Python printing materialization carries the
    threshold field through to ``CardPrinting.enters_tapped_unless_
    any_player_life_at_most``. Python's ``_play_land`` reads that
    field, so the bridge MUST thread it (otherwise an admitted
    painland would silently enter untapped on every life total).
    """
    cd = _expected_painland_card_def(name, c1, c2)
    pr = _card_def_to_python_printing(cd)
    assert pr.enters_tapped_unless_any_player_life_at_most == 13
    assert pr.produces == frozenset({c1, c2})
    assert pr.enters_tapped is False


def test_bridge_rust_registry_carries_threshold():
    """End-to-end: the Rust ``Registry``, populated through
    ``build_rust_registry`` from a painland CardDef, exposes the
    threshold via the ``get_printing_enters_tapped_unless_any_
    player_life_at_most`` accessor (added alongside the substrate).
    """
    _require_engine()
    cd = _expected_painland_card_def("Bleeding Woods", "G", "R")
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            cd,
        ),
        p0_library=("Bleeding Woods", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    threshold = reg.get_printing_enters_tapped_unless_any_player_life_at_most(
        name_to_pid["Bleeding Woods"],
    )
    assert threshold == 13
    # Forest carries the default 0.
    forest_threshold = (
        reg.get_printing_enters_tapped_unless_any_player_life_at_most(
            name_to_pid["Forest"],
        )
    )
    assert forest_threshold == 0


# ---------------------------------------------------------------------------
# §5. Rust unit pins — play-land routes the conditional-tapped check
# ---------------------------------------------------------------------------


def _bench_paint_state_with_painland_in_hand(p0_life: int, p1_life: int):
    """Build matched Py + Rust states with one painland (Bleeding
    Woods, R/G) in p0's hand and no other p0 library card to play.
    Used for cross-engine play-land routing pins.

    Both players start with their library full of basic Forests so
    the shared rng / shuffle bookkeeping stays clean; the painland is
    placed in p0's hand explicitly via ``register_and_inject_object``
    on Rust + ``new_object`` on Python.
    """
    cd_painland = _expected_painland_card_def("Bleeding Woods", "G", "R")
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            cd_painland,
        ),
        # Just enough Forests for each engine's library not to be empty.
        p0_library=("Forest",) * 5,
        p1_library=("Forest",) * 5,
    )
    py_state, rust_state = build_matched_states(spec)
    # Set life totals on both engines.
    py_state.players[0].life = p0_life
    py_state.players[1].life = p1_life
    rust_state.set_life(0, p0_life)
    rust_state.set_life(1, p1_life)
    return py_state, rust_state, cd_painland


def _inject_painland_into_hand_both(py_state, rust_state, cd_painland):
    """Inject one copy of ``cd_painland`` into p0's hand on both
    engines. Returns ``(py_obj_id, rust_obj_id)``.
    """
    from mtg_bot.game import Zone

    # ---- Python ----
    pr = _card_def_to_python_printing(cd_painland)
    py_obj = py_state.new_object(pr, owner_id=0, zone=Zone.HAND)
    py_state.players[0].hand.append(py_obj)

    # ---- Rust ----
    ZONE_HAND = 0
    rust_dict = _spec_card_to_printing_dict(cd_painland)
    rust_obj_id = rust_state.register_and_inject_object(
        rust_dict,
        0,  # controller = p0
        ZONE_HAND,
    )
    return int(py_obj.id), int(rust_obj_id)


def test_rust_play_land_painland_enters_untapped_when_life_low():
    """**Rust pin — the LOW-LIFE branch.** When any player's life is
    at or below the threshold (13), the painland enters UNTAPPED on
    Rust (mirrors Python ``actions.py:1100`` ``any_low=True ->
    card.tapped = not any_low = False``).
    """
    _require_engine()
    _py_state, rust_state, cd_painland = (
        _bench_paint_state_with_painland_in_hand(p0_life=10, p1_life=20)
    )
    # Inject one painland into Rust p0's hand only — Python isn't
    # needed for this Rust-side pin.
    from mtg_bot.game import Zone  # noqa: F401  (kept for parity with helper)

    ZONE_HAND = 0
    rust_dict = _spec_card_to_printing_dict(cd_painland)
    rust_obj_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND,
    )
    played = rust_state.play_land(int(rust_obj_id), 0)
    assert played is True
    tapped = rust_state.is_tapped(int(rust_obj_id))
    assert tapped is False, (
        "p0 at 10 life satisfies the <=13 threshold; the painland MUST "
        "enter untapped on Rust (matches Python's actions._play_land)."
    )


def test_rust_play_land_painland_enters_tapped_when_life_high():
    """**Rust pin — the HIGH-LIFE branch.** When every player is above
    the threshold (life > 13), the painland enters TAPPED on Rust
    (mirrors Python ``actions.py:1099-1101`` ``any_low=False ->
    card.tapped = not any_low = True``). Pre-substrate Rust would
    silently enter untapped here — this is the divergence the slice
    closes.
    """
    _require_engine()
    _py_state, rust_state, cd_painland = (
        _bench_paint_state_with_painland_in_hand(p0_life=20, p1_life=20)
    )
    ZONE_HAND = 0
    rust_dict = _spec_card_to_printing_dict(cd_painland)
    rust_obj_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND,
    )
    played = rust_state.play_land(int(rust_obj_id), 0)
    assert played is True
    tapped = rust_state.is_tapped(int(rust_obj_id))
    assert tapped is True, (
        "Both players at 20 life are above the 13 threshold; the "
        "painland MUST enter tapped on Rust (matches Python's "
        "actions._play_land)."
    )


def test_rust_play_land_painland_boundary_exactly_13_low_branch():
    """**Rust pin — the boundary (life == threshold).** Exactly 13 life
    counts as low (``life <= 13``); the painland enters untapped.
    """
    _require_engine()
    _py_state, rust_state, cd_painland = (
        _bench_paint_state_with_painland_in_hand(p0_life=20, p1_life=13)
    )
    ZONE_HAND = 0
    rust_dict = _spec_card_to_printing_dict(cd_painland)
    rust_obj_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND,
    )
    played = rust_state.play_land(int(rust_obj_id), 0)
    assert played is True
    assert rust_state.is_tapped(int(rust_obj_id)) is False


def test_rust_play_land_painland_boundary_exactly_14_high_branch():
    """**Rust pin — the boundary (life == threshold + 1).** Exactly 14
    life is ABOVE the 13 threshold; the painland enters tapped.
    """
    _require_engine()
    _py_state, rust_state, cd_painland = (
        _bench_paint_state_with_painland_in_hand(p0_life=20, p1_life=14)
    )
    ZONE_HAND = 0
    rust_dict = _spec_card_to_printing_dict(cd_painland)
    rust_obj_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND,
    )
    played = rust_state.play_land(int(rust_obj_id), 0)
    assert played is True
    assert rust_state.is_tapped(int(rust_obj_id)) is True


# ---------------------------------------------------------------------------
# §6. Cross-engine byte-equal probe — play the painland on BOTH engines
#     with seeded life totals; post-play tapped state matches.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p0_life,p1_life,expected_tapped",
    [
        (20, 20, True),    # No player low — tapped on both.
        (10, 20, False),   # p0 low — untapped on both.
        (20, 13, False),   # p1 at threshold — untapped on both.
        (20, 14, True),    # p1 just above threshold — tapped on both.
        (5, 5, False),     # Both low — untapped on both.
    ],
)
def test_cross_engine_painland_play_byte_equal_tapped_state(
    p0_life: int, p1_life: int, expected_tapped: bool,
):
    """**The genuine cross-engine probe.** Drive ``play_land`` on
    Abandoned Campground on BOTH engines with seeded life totals;
    assert the resulting battlefield permanent's ``tapped`` state
    matches across engines AND matches the expected per-CR-614 outcome.

    Pre-Phase-2 Rust would always enter untapped (no threshold field /
    no play-land routing); the probe would have diverged on every
    high-life seed. With the substrate landed, the engines agree on
    every seed.
    """
    _require_engine()
    cd_painland = _expected_painland_card_def(
        "Abandoned Campground", "U", "W",
    )
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            cd_painland,
        ),
        p0_library=("Forest",) * 5,
        p1_library=("Forest",) * 5,
    )
    py_state, rust_state = build_matched_states(spec)
    # Set life totals on both engines.
    py_state.players[0].life = p0_life
    py_state.players[1].life = p1_life
    rust_state.set_life(0, p0_life)
    rust_state.set_life(1, p1_life)
    # Inject one painland into p0's hand on both engines.
    py_obj_id, rust_obj_id = _inject_painland_into_hand_both(
        py_state, rust_state, cd_painland,
    )

    # Drive play_land on Python.
    from mtg_bot.actions import _play_land

    _play_land(py_state, 0, py_obj_id)
    py_card = next(c for c in py_state.battlefield if c.id == py_obj_id)
    py_tapped = py_card.tapped

    # Drive play_land on Rust.
    played = rust_state.play_land(int(rust_obj_id), 0)
    assert played is True
    rust_tapped = rust_state.is_tapped(int(rust_obj_id))

    assert py_tapped == rust_tapped, (
        f"Cross-engine painland tapped-state divergence at "
        f"life=({p0_life},{p1_life}): Python={py_tapped} Rust={rust_tapped}"
    )
    assert py_tapped is expected_tapped


# ---------------------------------------------------------------------------
# §7. Loader admit — `_filter_deck_to_bridge_supported` admits the 9
# ---------------------------------------------------------------------------


def test_loader_admits_all_nine_painlands():
    """The production-deck loader admits each Phase-2 painland by
    name — the user-facing closure (bench corpus tier shifts).
    """
    printings = _parser_printings()
    names = [name for (name, _c1, _c2) in _PHASE_2_PAINLANDS]
    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        names, printings,
    )
    # All 9 admitted (no drops).
    assert set(filtered_names) == set(names)
    # All 9 yielded a CardDef carrying the threshold (set-de-duped on
    # name — `_filter_deck_to_bridge_supported` returns one CardDef
    # per unique name).
    threshold_by_name = {
        cd.name: cd.enters_tapped_unless_any_player_life_at_most
        for cd in card_defs
    }
    for name in names:
        assert threshold_by_name[name] == 13


# ---------------------------------------------------------------------------
# §8. Belt-and-braces — Phase 1 shocklands still admitted (no regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Breeding Pool", "Watery Grave", "Stomping Ground",
     "Godless Shrine", "Sacred Foundry"],
)
def test_phase1_shocklands_still_admitted(name: str):
    """Phase 1 (round-60) shockland admit must NOT regress under
    Phase 2's substrate widening. The two predicates are positively
    disjoint on the conditional-tapped guard.
    """
    pr = _parser_printings()[name]
    assert _printing_is_bridge_nonbasic_mana_land(pr) is True
    assert _printing_is_bridge_nonbasic_painland_conditional(pr) is False
