"""B3-S2 — the codec slot-source switch (Rust decision -> fixed
policy slot), v-chain-SAFE, + the G2 PlayLand interim mask.

The load-bearing proof: for the SAME matched state, encoding the SAME
decision through the Rust provider (RustZoneView slot source) yields
the IDENTICAL policy slot the Python MtgGameStateAdapter yields — under
BOTH positional_v1 and canonical_v2. The slot mapping is byte-
identical; only its data source moved (the v-chain-SAFE requirement,
spec §3.2 — trained v17 weights keep working).

Also covers:
* the RustZoneView shim presents the codec's player_by_id/battlefield
  surface from the Rust *_snapshot pymethods;
* the G2 PlayLand per-turn-limit interim mask filters the
  structurally-over-offered extra PlayLand once a land was played.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, PassPriority, PlayLand
from mtg_bot.training import action_encoding as ae

V1 = "positional_v1"
V2 = "canonical_v2"


def _matched(spec_fn=None):
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        build_matched_states, tiny_synthetic_deckspec,
    )
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    spec = (spec_fn or tiny_synthetic_deckspec)()
    py_state, rust_state = build_matched_states(spec)
    py_adapter = MtgGameStateAdapter(
        py_state, expose_combat_decisions=True,
    )
    rust_adapter = make_rust_game_state_adapter(rust_state, spec=spec)
    return spec, py_adapter, rust_adapter


# ---------------------------------------------------------------------------
# The RustZoneView shim
# ---------------------------------------------------------------------------


def test_zone_view_presents_codec_surface():
    from mtg_bot.search.rust_zone_view import RustZoneView

    _, _, rust_adapter = _matched()
    zv = rust_adapter.engine_state
    assert isinstance(zv, RustZoneView)
    # The codec touches player_by_id(viewer).hand/graveyard/exile/
    # library + a flat .battlefield.
    p0 = zv.player_by_id(0)
    assert hasattr(p0, "hand") and hasattr(p0, "graveyard")
    assert hasattr(p0, "exile") and hasattr(p0, "library")
    assert isinstance(zv.battlefield, list)
    # tiny_synthetic_deckspec: 3-card libraries, empty hands at start.
    assert len(p0.library) == 3
    for c in p0.library:
        assert isinstance(c.id, int)
        assert isinstance(c.printing.name, str) and c.printing.name


def test_zone_view_engine_state_via_codec_helper():
    """The codec reaches the zone source through
    `_engine_state(state)` = getattr(state, "engine_state", state).
    The Rust provider's engine_state property must satisfy that."""
    from mtg_bot.search.rust_zone_view import RustZoneView

    _, _, rust_adapter = _matched()
    eng = ae._engine_state(rust_adapter)
    assert isinstance(eng, RustZoneView)


# ---------------------------------------------------------------------------
# v-chain-SAFE: identical slots from Rust vs Python source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [V1, V2])
def test_pass_priority_slot_identical(version):
    _, py_a, rust_a = _matched()
    py_slot = ae.encode(PassPriority(), py_a, 0, version=version)
    rust_slot = ae.encode(PassPriority(), rust_a, 0, version=version)
    assert py_slot == rust_slot == ae.SLOT_PASS


@pytest.mark.parametrize("version", [V1, V2])
def test_hand_card_slots_identical_after_draws(version):
    """Drive both engines a few turns so cards land in hand, then for
    every hand card assert the PlayLand/CastSpell slot encodes
    identically from the Rust source and the Python source. This is
    the v-chain-SAFE proof: same slot mapping, different data source.
    """
    import random

    spec, py_a, rust_a = _matched()
    # Advance both adapters in lockstep with the SAME decisions so the
    # zones match (drive via the Python adapter's legal set; replay
    # the byte-equal decision on the Rust adapter).
    rng = random.Random(2027)
    for _ in range(40):
        if py_a.is_terminal() or rust_a.is_terminal():
            break
        legal = py_a.legal_decisions()
        if not legal:
            break
        choice = rng.choice(legal)
        # Only drive priority-window decisions (S2 scope); skip
        # combat-phase decision types if they appear.
        if type(choice).__name__ in ("AttackerDecision", "BlockerDecision"):
            choice = next(
                (d for d in legal if isinstance(d, PassPriority)), choice
            )
        py_a.apply(choice)
        try:
            rust_a.apply(choice)
        except Exception:
            # Engines can diverge on a real game (that's what the S4
            # shadow-checker is for); this S2 test only needs SOME
            # shared hand state to compare slot encodings, so stop
            # driving on the first apply mismatch and compare what we
            # have.
            break

    # Compare hand-card slot encodings on whatever hand state exists.
    eng_py = ae._engine_state(py_a)
    for viewer in (0, 1):
        hand = list(eng_py.player_by_id(viewer).hand)
        for card in hand:
            d_land = PlayLand(card_id=card.id)
            d_cast = CastSpell(card_id=card.id)
            for dec in (d_land, d_cast):
                try:
                    s_py = ae.encode(dec, py_a, viewer, version=version)
                except ae.EncodingOverflowError:
                    continue
                s_rust = ae.encode(dec, rust_a, viewer, version=version)
                assert s_py == s_rust, (
                    f"slot mismatch v={version} viewer={viewer} "
                    f"card={card.printing.name} dec={type(dec).__name__}: "
                    f"py={s_py} rust={s_rust}"
                )


@pytest.mark.parametrize("version", [V1, V2])
def test_legal_action_mask_identical_at_start(version):
    """legal_action_mask over the Rust provider must equal the mask
    over the Python adapter at the matched start state (the codec
    enumerates + encodes; both must agree slot-for-slot)."""
    _, py_a, rust_a = _matched()
    m_py = ae.legal_action_mask(py_a, 0, version=version)
    m_rust = ae.legal_action_mask(rust_a, 0, version=version)
    assert m_py.shape == m_rust.shape == (ae.ACTION_VOCAB_SIZE,)
    # At the matched start (empty hands, 3-card libs, UNTAP->first
    # priority) the only legal decision is PassPriority on both.
    assert m_py[ae.SLOT_PASS] and m_rust[ae.SLOT_PASS]
    assert (m_py == m_rust).all(), (
        f"v={version}: mask differs at slots "
        f"{[i for i in range(ae.ACTION_VOCAB_SIZE) if m_py[i] != m_rust[i]]}"
    )


# ---------------------------------------------------------------------------
# G2 — PlayLand per-turn-limit interim mask
# ---------------------------------------------------------------------------


def _forest_heavy_adapter():
    """A Forest-only library so lands get drawn into hand within a
    few turns and PlayLand becomes legal (DeckSpec has no hand field;
    all cards start in the library and are drawn)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        DeckSpec, _FOREST, build_rust_state,
    )
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    spec = DeckSpec(
        card_defs=(_FOREST,),
        p0_library=tuple(["Forest"] * 20),
        p1_library=tuple(["Forest"] * 20),
    )
    return make_rust_game_state_adapter(build_rust_state(spec), spec=spec)


def _drive_until_playland(adapter, max_steps=200):
    """Drive the adapter (passing) until a PlayLand decision is legal.
    Returns the legal list at that moment, or None if none reached."""
    for _ in range(max_steps):
        if adapter.is_terminal():
            return None
        legal = adapter.legal_decisions()
        if any(isinstance(d, PlayLand) for d in legal):
            return legal
        passes = [d for d in legal if isinstance(d, PassPriority)]
        adapter.apply(passes[0] if passes else legal[0])
    return None


def test_g2_playland_mask_filters_extra_land():
    """After a PlayLand is applied this turn, the provider's
    legal_decisions() must NOT offer another PlayLand (Rust's
    legal_decisions over-offers; the provider's B3-side mask filters
    it — spec §2.4-G2)."""
    adapter = _forest_heavy_adapter()
    legal = _drive_until_playland(adapter)
    assert legal is not None, "test did not reach a PlayLand decision"
    lands = [d for d in legal if isinstance(d, PlayLand)]
    adapter.apply(lands[0])
    # Immediately after: NO PlayLand may be offered again this turn
    # (the G2 interim mask filters Rust's structural over-offer).
    post = adapter.legal_decisions()
    assert not any(isinstance(d, PlayLand) for d in post), (
        "G2 interim mask failed: a PlayLand was still offered after "
        "a land was played this turn"
    )


def test_g2_mask_survives_clone():
    """The G2 land-played bookkeeping must propagate through clone()
    (search clones thousands of times per decision)."""
    adapter = _forest_heavy_adapter()
    legal = _drive_until_playland(adapter)
    assert legal is not None
    lands = [d for d in legal if isinstance(d, PlayLand)]
    adapter.apply(lands[0])
    clone = adapter.clone()
    assert not any(
        isinstance(d, PlayLand) for d in clone.legal_decisions()
    ), "clone lost the G2 land-played bookkeeping"


# ---------------------------------------------------------------------------
# Structured-NN action history surface on the Rust providers
# ---------------------------------------------------------------------------


def test_rust_provider_recent_actions_is_empty_and_shadow_delegates_to_python():
    """``NNEvaluator`` reads ``state.recent_actions`` for the structured
    action-history tokens. The Rust provider has no Python engine
    state to snapshot, so it exposes an (always) empty history; the
    shadow-checked adapter delegates to its Python checker, whose
    ``apply`` records the real history in lockstep."""
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    spec, py_adapter, rust_adapter = _matched()
    assert rust_adapter.recent_actions == ()
    assert rust_adapter.clone().recent_actions == ()
    shadow = build_shadow_checked_adapter(spec)
    assert shadow.recent_actions is shadow.py_adapter.recent_actions
    assert shadow.recent_actions == ()
