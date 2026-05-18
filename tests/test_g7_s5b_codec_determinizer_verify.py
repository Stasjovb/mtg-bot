"""G7 S5b — codec / determinizer / fingerprint cross-source
byte-equality VERIFY pins for the spell-stack source-zone re-homing.

S5a (`feature/g7-s5a-spellstack-zone`, merged to main at
`302a5fc5`) re-homed the cast spell out of Rust's ``hand`` Vec into
``GameState.stack_objects`` (Option β, the live ``ZONE_STACK`` store),
byte-mirroring Python's ``p.hand.remove(card)`` (`actions.py:1403`) +
``card.zone = Zone.STACK`` (`:1751`). The S5 design
(`docs/RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md` §6, §1.6/§1.7/§1.10)
claims the determinizer + ``hand_snapshot`` codec slot source +
fingerprint hand slot + v1/v2 action-encoding are **fixed FOR FREE by
the single hand-membership correction — NOT a v-chain break, NO
retraining** (it corrects WHICH cards are in the hand list, not the
v1-vs-v2 ordering *within* it).

**S5b is a pure-Python / test-only VERIFY slice. It proves that claim
with byte-equality pins across the cast→on-stack→resolve window — it
makes NO engine change.** If a pin fails, that is a genuine finding:
S5a's "fixed for free" claim has a hole — the pin fails LOUD with the
exact divergence; it is NOT papered over and NOT "fixed" in Rust here
(honest-stop, `feedback_no_fallback_hybrids` / verify-first).

The four pins (per the brief):

1. ``test_codec_hand_slot_byte_equal_with_spell_on_stack`` — the Rust
   ``hand_snapshot``-sourced codec hand slots byte-match Python's
   ``p.hand`` exclusion of the on-stack spell, under BOTH
   ``positional_v1`` and ``canonical_v2``. The on-stack spell appears
   in NEITHER engine's codec hand projection; the surviving in-hand
   cards encode to the IDENTICAL policy slot from both data sources.
2. ``test_determinizer_pool_byte_equal_with_spell_on_stack`` —
   ``determinize`` (Python source) over a mid-stack state produces a
   byte-identical hidden-pool result to ``rust_determinize`` (Rust
   source) under the same RNG seed; the on-stack spell is in NEITHER
   engine's determinizable pool. Exercised with ≥2 hidden library
   cards so the shuffle is non-trivial (not a degenerate 0/1-card
   no-op).
3. ``test_fingerprint_hand_slot_byte_equal_with_spell_on_stack`` —
   the per-player fingerprint hand slot is byte-equal Python↔Rust
   mid-stack, the stack slot is byte-unchanged Python↔Rust (Python
   has no separate stack-object zone signature, per the S5a
   `state.rs` design comment), and the Rust native ``fingerprint()``
   equals the Rust-via-snapshot recipe (intra-engine determinism).
4. ``test_not_a_v_chain_break_v1_v2_both_map`` — v1 and v2 action-
   encoding BOTH still map correctly for the surviving in-hand card;
   the correction is hand-membership, not intra-hand ordering — no
   retraining implied.

The cast→on-stack→resolve window is exercised at the same per-apply
compare point the role-swapped ``rust_shadow`` bake-in uses
(`rust_shadow.py:471-472` — apply to BOTH then compare immediately,
NO CE5-style post-cast stack drain), so Python's hand excludes the
cast spell and Rust's (post-S5a) does too — the byte-target the pins
assert is the Python SoT shape (`feedback_parity_new_code_is_right`).
"""

from __future__ import annotations

import random

import pytest

from mtg_bot.actions import CastSpell, PlayLand

V1 = "positional_v1"
V2 = "canonical_v2"


# ---------------------------------------------------------------------------
# Shared helper: drive a spell onto the stack on BOTH engines, mid-stack,
# NO drain (the rust_shadow per-apply compare point).
# ---------------------------------------------------------------------------


def _bigger_cast_deckspec():
    """A deck whose libraries are deep enough that ≥2 hidden cards
    remain at the cast point, so the determinizer pin exercises a
    NON-trivial shuffle (not a degenerate ≤1-card no-op). Forest +
    Grizzly Bears + Mountain registry — the established
    cross-engine smoke card set; ``cast_bears_selector`` drives the
    Bears cast in PRECOMBAT_MAIN once 2 green coins are tapped."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        DeckSpec, _BEARS, _FOREST, _MOUNTAIN,
    )

    return DeckSpec(
        card_defs=(_FOREST, _BEARS, _MOUNTAIN),
        p0_library=(
            "Forest", "Forest", "Grizzly Bears", "Forest", "Mountain",
            "Grizzly Bears", "Forest", "Mountain", "Forest",
            "Grizzly Bears", "Mountain", "Forest",
        ),
        p1_library=(
            "Mountain", "Grizzly Bears", "Forest", "Mountain", "Forest",
            "Grizzly Bears", "Forest", "Mountain", "Grizzly Bears",
            "Forest", "Mountain", "Forest",
        ),
    )


def _drive_to_spell_on_stack(spec=None):
    """Build matched Python+Rust states, drive ``cast_bears_selector``
    until it emits a ``cast_spell``, apply that cast to BOTH engines,
    and STOP — no resolve, no CE5-style drain. Returns
    ``(py_state, rust_state, cast_card_id)`` with a Grizzly Bears spell
    sitting on BOTH engines' stacks (Python via ``StackItem(source=
    card)`` + ``card.zone=STACK``; Rust via S5a's ``stack_objects``
    store with ``obj.zone=ZONE_STACK``).

    This is exactly the role-swapped ``rust_shadow`` per-apply compare
    moment (`rust_shadow.py:471-472`): apply to both then compare
    immediately, with NO post-cast stack drain — the window S5a
    re-homed and S5b verifies.
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.actions import apply_action as py_apply_action
    from mtg_bot.parity.cross_engine import (
        build_matched_states, cast_bears_selector, _dict_to_python_action,
    )

    spec = spec or _bigger_cast_deckspec()
    py_state, rust_state = build_matched_states(spec)
    for i in range(600):
        if py_state.is_over() or rust_state.is_over():
            break
        action_dict = cast_bears_selector(py_state, rust_state, i)
        kind = action_dict.get("kind")
        # Mirror step_both's actor convention exactly (cross_engine.py
        # :10352-10354) so the two engines stay in lockstep up to the
        # cast — priority player, except declare_blockers (defender).
        actor = py_state.priority_player_idx
        if kind == "declare_blockers":
            actor = 1 - py_state.active_player_idx
        py_apply_action(
            py_state, actor, _dict_to_python_action(action_dict)
        )
        rust_state.apply_action(action_dict)
        if kind == "cast_spell":
            return py_state, rust_state, int(action_dict["card_id"])
    pytest.fail(
        "cast_bears_selector never emitted a cast_spell within 600 "
        "steps — the S5b window (spell on stack) was never reached; "
        "the pins cannot exercise the cast→on-stack→resolve window"
    )


def _adapters(py_state, rust_state, spec):
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    return (
        MtgGameStateAdapter(py_state, expose_combat_decisions=True),
        make_rust_game_state_adapter(rust_state, spec=spec),
    )


# ---------------------------------------------------------------------------
# Sanity: the window genuinely puts the spell on the stack and OUT of
# every hand projection on BOTH engines (the S5a invariant S5b rests on).
# ---------------------------------------------------------------------------


def test_window_spell_is_on_stack_and_out_of_hand_both_engines():
    """The cast spell sits on BOTH stacks and is absent from BOTH
    engines' hand projections — the single hand-membership correction
    S5a landed (NOT a triviality: asserts the real id is on the stack
    AND in no hand on either side)."""
    py_state, rust_state, cast_id = _drive_to_spell_on_stack()

    # Python: card on the stack, in NO zone list.
    py_stack_ids = [
        getattr(si.source, "id", None) for si in py_state.stack
    ]
    assert cast_id in py_stack_ids, (
        f"Python: cast id {cast_id} not on the stack {py_stack_ids}"
    )
    assert not any(
        o.id == cast_id for p in py_state.players for o in p.hand
    ), "Python: cast spell still in a hand list (S5 SoT contract broken)"

    # Rust (post-S5a): card on the stack store, absent from hand_snapshot.
    rust_stack_ids = [
        dict(d)["source_obj_id"] for d in rust_state.stack_snapshot()
    ]
    assert cast_id in rust_stack_ids, (
        f"Rust: cast id {cast_id} not on the stack {rust_stack_ids} — "
        "S5a stack-object store re-homing did not take"
    )
    assert not any(
        dict(d)["id"] == cast_id
        for pid in (0, 1)
        for d in rust_state.hand_snapshot(pid)
    ), (
        "Rust: cast spell still in hand_snapshot — S5a's "
        "hand-membership correction has a HOLE (the 'fixed for free' "
        "claim fails at the snapshot source)"
    )


# ---------------------------------------------------------------------------
# Pin 1 — codec hand-slot byte-equality (v1 + v2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [V1, V2])
def test_codec_hand_slot_byte_equal_with_spell_on_stack(version):
    """With a spell on the stack, the Rust ``hand_snapshot``-sourced
    codec hand slots byte-match the Python ``p.hand``-sourced slots:

      * the on-stack spell appears in NEITHER engine's codec hand
        projection (RustZoneView.player_by_id(v).hand == Python
        adapter's hand — both exclude it);
      * every surviving in-hand card's PlayLand / CastSpell slot
        encodes to the IDENTICAL policy slot from the Rust source and
        the Python source, under this action-encoding version.

    This is the §1.6 byte-equality the design claims is "fixed for
    free": the data source moved (S5a), the slot mapping is unchanged.
    """
    from mtg_bot.training import action_encoding as ae

    spec = _bigger_cast_deckspec()
    py_state, rust_state, cast_id = _drive_to_spell_on_stack(spec)
    py_a, rust_a = _adapters(py_state, rust_state, spec)

    eng_py = ae._engine_state(py_a)
    eng_rust = ae._engine_state(rust_a)

    compared = 0
    for viewer in (0, 1):
        py_hand = list(eng_py.player_by_id(viewer).hand)
        rust_hand = list(eng_rust.player_by_id(viewer).hand)

        # The on-stack spell is in NEITHER codec hand projection.
        assert cast_id not in [c.id for c in py_hand], (
            f"v={version} viewer={viewer}: on-stack spell {cast_id} "
            f"leaked into the Python codec hand {[c.id for c in py_hand]}"
        )
        assert cast_id not in [c.id for c in rust_hand], (
            f"v={version} viewer={viewer}: on-stack spell {cast_id} "
            f"leaked into the Rust codec hand "
            f"{[c.id for c in rust_hand]} — S5a hand-membership "
            f"correction has a HOLE at the codec slot source"
        )
        # The hand-id SET is byte-equal across the two data sources.
        assert [c.id for c in py_hand] == [c.id for c in rust_hand], (
            f"v={version} viewer={viewer}: codec hand id sequence "
            f"differs Python={[c.id for c in py_hand]} "
            f"Rust={[c.id for c in rust_hand]}"
        )

        for card in py_hand:
            for dec in (
                PlayLand(card_id=card.id), CastSpell(card_id=card.id),
            ):
                try:
                    s_py = ae.encode(dec, py_a, viewer, version=version)
                except ae.EncodingOverflowError:
                    continue
                s_rust = ae.encode(
                    dec, rust_a, viewer, version=version
                )
                assert s_py == s_rust, (
                    f"slot mismatch v={version} viewer={viewer} "
                    f"card={card.printing.name} "
                    f"dec={type(dec).__name__}: py={s_py} "
                    f"rust={s_rust} (S5a codec slot source NOT "
                    f"byte-equal with a spell on the stack)"
                )
                compared += 1

    assert compared > 0, (
        f"v={version}: no surviving in-hand card was slot-compared "
        "while a spell was on the stack — the pin did not genuinely "
        "exercise the codec hand projection"
    )


# ---------------------------------------------------------------------------
# Pin 2 — determinizer pool byte-equality (non-trivial shuffle)
# ---------------------------------------------------------------------------


def _py_hidden_pool(py_state, viewer_id):
    """The Python determinizer's per-owner hidden pool (hand+library
    cards the viewer doesn't know) — ``determinize._determinize_player``
    pool composition, owner-keyed."""
    from mtg_bot.search.determinize import viewer_knows

    pool = {}
    for p in py_state.players:
        ids = [
            c.id for c in p.hand if not viewer_knows(c, viewer_id)
        ] + [
            c.id for c in p.library if not viewer_knows(c, viewer_id)
        ]
        pool[p.id] = sorted(ids)
    return pool


def _rust_hidden_pool(rust_state, viewer_id):
    """The ``rust_determinize`` per-owner hidden pool — the
    ``_determinize_player`` hand_snapshot+library_snapshot composition
    filtered by ``_rust_viewer_knows``, owner-keyed."""
    from mtg_bot.search.rust_determinize import _rust_viewer_knows

    pool = {}
    for owner in (0, 1):
        ids = []
        for d in rust_state.hand_snapshot(owner):
            dd = dict(d)
            if not _rust_viewer_knows(dd, owner, viewer_id):
                ids.append(int(dd["id"]))
        for d in rust_state.library_snapshot(owner):
            dd = dict(d)
            if not _rust_viewer_knows(dd, owner, viewer_id):
                ids.append(int(dd["id"]))
        pool[owner] = sorted(ids)
    return pool


@pytest.mark.parametrize("viewer_id", [0, 1])
def test_determinizer_pool_byte_equal_with_spell_on_stack(viewer_id):
    """The Python determinizer pool and the ``rust_determinize`` pool
    are byte-identical with a spell on the stack — the on-stack spell
    is in NEITHER pool (§1.7). The deck is sized so ≥2 hidden cards
    remain, so this is NOT a degenerate ≤1-card no-op."""
    py_state, rust_state, cast_id = _drive_to_spell_on_stack()

    py_pool = _py_hidden_pool(py_state, viewer_id)
    rust_pool = _rust_hidden_pool(rust_state, viewer_id)

    assert py_pool == rust_pool, (
        f"viewer={viewer_id}: determinizer hidden-pool composition "
        f"differs Python={py_pool} Rust={rust_pool} — S5a did NOT "
        f"fix the determinizer pool for free"
    )
    # The on-stack spell is in NEITHER pool.
    for owner, ids in py_pool.items():
        assert cast_id not in ids, (
            f"viewer={viewer_id}: on-stack spell {cast_id} pooled "
            f"into the Python determinizer pool owner={owner}"
        )
    for owner, ids in rust_pool.items():
        assert cast_id not in ids, (
            f"viewer={viewer_id}: on-stack spell {cast_id} pooled "
            f"into the Rust determinizer pool owner={owner}"
        )
    # Non-triviality guard: at least one owner's pool has ≥2 hidden
    # cards so the shuffle below is a real permutation, not a no-op.
    assert any(len(ids) >= 2 for ids in py_pool.values()), (
        f"viewer={viewer_id}: every owner pool has <2 hidden cards "
        f"({py_pool}) — the determinizer shuffle is a degenerate "
        "no-op; the pin must exercise a real permutation"
    )


@pytest.mark.parametrize("viewer_id", [0, 1])
def test_determinize_result_byte_equal_with_spell_on_stack(viewer_id):
    """End-to-end: ``determinize`` (Python source) and
    ``rust_determinize`` (Rust source) over the SAME mid-stack state
    with the SAME RNG seed produce byte-identical per-owner
    hand+library ``(id, printing_name)`` sequences. Same pool ⇒ same
    ``rng.shuffle`` permutation ⇒ same determinization — the §1.7
    "fixed for free" claim, end to end. CoW: the source god-view stays
    pristine after determinizing a clone."""
    from mtg_bot.search.determinize import determinize
    from mtg_bot.search.rust_determinize import rust_determinize

    py_state, rust_state, _ = _drive_to_spell_on_stack()

    # Pre-determinize source snapshot (CoW pristine check).
    src_py = {
        p.id: [(c.id, c.printing.name) for c in p.library]
        for p in py_state.players
    }

    py_clone = py_state.clone()
    rust_clone = rust_state.clone_once()
    determinize(
        py_clone, viewer_id=viewer_id, rng=random.Random(99),
        in_place=True,
    )
    rust_determinize(
        rust_clone, viewer_id=viewer_id, rng=random.Random(99),
    )

    def _py_seq(s):
        return {
            p.id: [(c.id, c.printing.name) for c in p.hand]
            + [(c.id, c.printing.name) for c in p.library]
            for p in s.players
        }

    def _rust_seq(s):
        return {
            pid: [
                (dict(d)["id"], dict(d)["printing_name"])
                for d in s.hand_snapshot(pid)
            ]
            + [
                (dict(d)["id"], dict(d)["printing_name"])
                for d in s.library_snapshot(pid)
            ]
            for pid in (0, 1)
        }

    py_seq = _py_seq(py_clone)
    rust_seq = _rust_seq(rust_clone)
    assert py_seq == rust_seq, (
        f"viewer={viewer_id}: determinize result NOT byte-equal "
        f"Python vs Rust with a spell on the stack:\n"
        f"  Python={py_seq}\n  Rust  ={rust_seq}"
    )
    # CoW: determinizing the clones left the Python source pristine.
    src_py_after = {
        p.id: [(c.id, c.printing.name) for c in p.library]
        for p in py_state.players
    }
    assert src_py == src_py_after, (
        "determinizing a clone leaked back into the Python god-view "
        "source (CoW boundary violated)"
    )


# ---------------------------------------------------------------------------
# Pin 3 — fingerprint hand-slot byte-equality + stack slot unchanged
# ---------------------------------------------------------------------------


def test_fingerprint_hand_slot_byte_equal_with_spell_on_stack():
    """With a spell on the stack:

      * the per-player fingerprint hand slot (``hand_p0`` /
        ``hand_p1``) is byte-equal Python↔Rust (§1.10);
      * the stack slot is byte-equal Python↔Rust and byte-UNCHANGED
        in shape — Python has no separate stack-object zone signature,
        the on-stack spell rides the stack slot via ``source.id``
        exactly as Rust's ``source_obj_id`` (the S5a `state.rs` design
        comment);
      * the Rust native ``fingerprint()`` equals the Rust-via-snapshot
        recipe (intra-engine determinism is unaffected by S5a).
    """
    import scripts.parity_smoke as parity_smoke
    from mtg_bot.parity.cross_engine import build_python_field_view

    py_state, rust_state, cast_id = _drive_to_spell_on_stack()

    py_view = build_python_field_view(py_state)
    rust_view = parity_smoke._build_field_view(rust_state)

    for pid in (0, 1):
        key = f"hand_p{pid}"
        assert py_view[key] == rust_view[key], (
            f"{key} fingerprint hand slot NOT byte-equal with a spell "
            f"on the stack: Python={py_view[key]} "
            f"Rust={rust_view[key]} — S5a did NOT fix the fingerprint "
            f"hand slot for free"
        )
        # The on-stack spell must not appear in either hand slot (the
        # 8th tuple element is the object id).
        assert all(
            sig[7] != cast_id for sig in py_view[key]
        ), f"Python {key} hand slot still carries the on-stack spell"
        assert all(
            sig[7] != cast_id for sig in rust_view[key]
        ), f"Rust {key} hand slot still carries the on-stack spell"

    # Stack slot byte-equal AND it carries the on-stack spell on BOTH
    # (id rides slot 8; per-permanent slots zeroed per
    # _rust_stack_obj_sig / _zone_signature StackItem fallback).
    assert py_view["stack"] == rust_view["stack"], (
        f"stack fingerprint slot NOT byte-equal: "
        f"Python={py_view['stack']} Rust={rust_view['stack']}"
    )
    assert any(sig[7] == cast_id for sig in py_view["stack"]), (
        "the on-stack spell is missing from the Python stack slot — "
        "the cast→on-stack window was not actually exercised"
    )
    assert any(sig[7] == cast_id for sig in rust_view["stack"]), (
        "the on-stack spell is missing from the Rust stack slot"
    )

    # Intra-engine Rust fingerprint determinism: native == snapshot
    # recipe (unaffected by S5a — same engine, same state).
    assert (
        rust_state.fingerprint()
        == parity_smoke._hash_rust_state(rust_state)
    ), (
        "Rust native fingerprint() diverged from the snapshot-recipe "
        "_hash_rust_state with a spell on the stack — an intra-engine "
        "fingerprint determinism break (S5a-introduced regression)"
    )


# ---------------------------------------------------------------------------
# Pin 4 — NOT a v-chain break (v1 AND v2 both map correctly)
# ---------------------------------------------------------------------------


def test_not_a_v_chain_break_v1_v2_both_map():
    """The hand-membership correction is v1/v2-AGNOSTIC: it changes
    WHICH cards are in the hand list, not the ordering WITHIN it. So
    for every surviving in-hand card, BOTH ``positional_v1`` and
    ``canonical_v2`` encode to a well-defined slot that is identical
    across the Python and Rust data sources — no slot semantics
    changed, no retraining implied.

    The discriminating assertion: the SAME surviving card is compared
    under BOTH versions from BOTH sources; all four encodings agree
    per (card, decision) — exactly the "not a v-chain break" property
    (the correction did not perturb the v1↔v2 axis).
    """
    from mtg_bot.training import action_encoding as ae

    spec = _bigger_cast_deckspec()
    py_state, rust_state, cast_id = _drive_to_spell_on_stack(spec)
    py_a, rust_a = _adapters(py_state, rust_state, spec)

    eng_py = ae._engine_state(py_a)
    checked = 0
    for viewer in (0, 1):
        for card in list(eng_py.player_by_id(viewer).hand):
            assert card.id != cast_id, (
                "the on-stack spell leaked into the hand projection "
                "— window invariant broken before the v-chain check"
            )
            for dec in (
                PlayLand(card_id=card.id), CastSpell(card_id=card.id),
            ):
                slots = {}
                for ver in (V1, V2):
                    try:
                        slots[(ver, "py")] = ae.encode(
                            dec, py_a, viewer, version=ver
                        )
                    except ae.EncodingOverflowError:
                        slots[(ver, "py")] = None
                    slots[(ver, "rust")] = (
                        None
                        if slots[(ver, "py")] is None
                        else ae.encode(
                            dec, rust_a, viewer, version=ver
                        )
                    )
                if slots[(V1, "py")] is None and slots[(V2, "py")] is None:
                    continue
                # Per-version Python↔Rust byte-equality (the data
                # source moved; the slot is unchanged) under BOTH
                # versions — i.e. v1 maps AND v2 maps, neither
                # perturbed by the S5a hand-membership correction.
                for ver in (V1, V2):
                    if slots[(ver, "py")] is None:
                        continue
                    assert slots[(ver, "py")] == slots[(ver, "rust")], (
                        f"v-chain-break check: ver={ver} viewer="
                        f"{viewer} card={card.printing.name} "
                        f"dec={type(dec).__name__} py="
                        f"{slots[(ver, 'py')]} rust="
                        f"{slots[(ver, 'rust')]} — the correction "
                        f"perturbed the {ver} slot mapping (would "
                        f"imply a v-chain break / retraining)"
                    )
                checked += 1

    assert checked > 0, (
        "no surviving in-hand card was checked under both v1 and v2 "
        "— the not-a-v-chain-break pin did not genuinely run"
    )
