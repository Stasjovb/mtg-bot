//! Library / discard / scry primitives on `GameState`.
//!
//! Ports the library-mutation patterns from the Python engine —
//! `shuffle_library` in `src/mtg_bot/game.py` (which open-codes
//! `state.rng.shuffle(p.library)`) and the discard pattern in
//! `src/mtg_bot/actions.py` (`p.hand.remove(card); card.zone =
//! Zone.GRAVEYARD; p.graveyard.append(card)`). Each is collapsed
//! into a single primitive on `GameState`.
//!
//! ## RNG choice (inline xorshift64)
//!
//! Shuffle uses an inline xorshift64 generator rather than pulling in
//! the `rand` crate. The motivation is purely a Cargo.toml race-
//! avoidance concern with sibling slices in this round — adding a
//! dependency would extend `Cargo.lock` and risk a merge conflict.
//! xorshift64 is ~6 lines and statistically sufficient for a Fisher-
//! Yates over a 60-99 card library; if production-quality randomness
//! ever matters here we swap it for `rand_pcg` in a follow-up.
//!
//! Determinism guarantee: `shuffle_library_with_seed(player_id, seed)`
//! is a pure function of `(library, seed)` — same library + same seed
//! produces the same permutation, byte for byte. The
//! `test_shuffle_with_seed_is_deterministic` test is the load-bearing
//! check.
//!
//! ## "Top of library" convention
//!
//! Inherited from `state_ops_zones.rs` (post-CE3): the FIRST element
//! of the library `Vec` (index 0) is the top of the library, matching
//! Python's `library.pop(0)` convention. `scry` reads the head and
//! returns ids in top-first order (`lib[0]` first); `apply_scry`
//! treats `top_ids[0]` as the new top of library after the operation.
//!
//! ## CoW
//!
//! `discard` mutates two zones (hand + graveyard) on the same player;
//! `shuffle_library_with_seed` mutates one zone (library). Both go
//! through `Arc::make_mut` on each zone they touch, preserving the
//! CoW invariant. The `*_clone_does_not_affect_original` tests are
//! the load-bearing canaries.
//!
//! ## CE8 Slice 2 — external-RNG path on the three gameplay shuffle sites
//!
//! `shuffle_library_with_seed`, `search_library_and_move_to_hand`,
//! and `search_library_for_first_of_type_and_shuffle` each gain an
//! optional `rng: Option<&Bound<'_, PyAny>>` kwarg. When `Some(_)`,
//! the Fisher-Yates draws come from the supplied Python
//! `random.Random` via `external_rng::next_below`, matching what
//! `random.Random.shuffle(list)` would produce on the Python side
//! (bit-identical). When `None` (default), the legacy xorshift64
//! path runs unchanged so production cli/bench callers and every
//! existing pinned baseline stay byte-equivalent.

use crate::state::{GameObject, GameState};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use std::sync::Arc;

/// Inline xorshift64 — see module docstring for the dependency-
/// avoidance rationale. Period 2^64 - 1, fails a couple of BigCrush
/// suites but is fine for shuffling a library of at most a couple
/// hundred cards.
struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
        // xorshift64 collapses to zero if seeded with zero, so map
        // 0 to a non-zero constant. Any non-zero value works — pick
        // a recognizable one for debug prints.
        let state = if seed == 0 { 0xdead_beef_dead_beef } else { seed };
        Self { state }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    /// Unbiased index in `[0, n)` for small `n` (n << u64::MAX).
    /// Uses the bit-trick rejection sampler to keep determinism
    /// independent of `n`.
    fn next_usize_below(&mut self, n: usize) -> usize {
        // n is small (library sizes are O(100)), so the simple
        // modulo-with-rejection bound is `u64::MAX - (u64::MAX % n)`.
        let n_u64 = n as u64;
        let bound = u64::MAX - (u64::MAX % n_u64);
        loop {
            let r = self.next_u64();
            if r < bound {
                return (r % n_u64) as usize;
            }
        }
    }
}

/// Fisher-Yates (Knuth) shuffle of a `GameObject` slice in place.
///
/// When `rng` is `Some(py_random)`, draws come from the supplied
/// Python `random.Random` via `external_rng::next_below`, matching
/// what `random.Random.shuffle(list)` produces on the Python side
/// bit-for-bit. When `rng` is `None`, falls back to the inline
/// xorshift64 seeded with `seed`. No-op for len < 2.
///
/// CE8 Slice 2 substrate: shared by all three gameplay shuffle sites
/// in this module (`shuffle_library_with_seed`,
/// `search_library_and_move_to_hand`,
/// `search_library_for_first_of_type_and_shuffle`). The control flow
/// is the standard `for i in (1..n).rev() { swap(i, j) }` Fisher-Yates
/// loop; only the source of `j` differs between the two paths.
fn fisher_yates_shuffle_optional(
    v: &mut [GameObject],
    rng: Option<&Bound<'_, PyAny>>,
    seed: u64,
) -> PyResult<()> {
    let n = v.len();
    if n < 2 {
        return Ok(());
    }
    if let Some(py_rng) = rng {
        for i in (1..n).rev() {
            let j = crate::external_rng::next_below(py_rng, i + 1)?;
            v.swap(i, j);
        }
    } else {
        let mut xorshift = XorShift64::new(seed);
        for i in (1..n).rev() {
            let j = xorshift.next_usize_below(i + 1);
            v.swap(i, j);
        }
    }
    Ok(())
}

#[pymethods]
impl GameState {
    /// Move the object with id `obj_id` from `player_id`'s HAND to
    /// that player's graveyard. Returns `true` on success.
    ///
    /// Returns `false` (no-op, no zone mutation) if any precondition
    /// fails: object id not present in the player's hand. This
    /// includes the case where the object exists but lives on the
    /// battlefield / in the library / in the graveyard already — the
    /// primitive is intentionally narrow (hand -> graveyard only).
    /// Callers that want a generic "send to graveyard from anywhere"
    /// reach for `move_object` from the zone slice instead.
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`
    /// so cloning a `GameState` and then discarding on the clone
    /// leaves the source's hand and graveyard untouched.
    fn discard(&mut self, obj_id: u32, player_id: u8) -> PyResult<bool> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(false);
        }
        let player = &mut self.players[idx];
        // Find in hand only — battlefield / graveyard / library
        // misses all return False per the docstring.
        let pos = match player.hand.iter().position(|o| o.id == obj_id) {
            Some(p) => p,
            None => return Ok(false),
        };
        let hand = Arc::make_mut(&mut player.hand);
        let mut obj = hand.remove(pos);
        obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
        Arc::make_mut(&mut player.graveyard).push(obj);
        Ok(true)
    }

    /// Shuffle `player_id`'s library in place using Fisher-Yates.
    /// When `rng` is `Some(py_random)`, draws come from the supplied
    /// Python `random.Random` (CE8 Slice 2 substrate — matches
    /// `random.Random.shuffle(list)` byte-for-byte). When `rng` is
    /// `None` (default), falls back to an inline xorshift64 seeded
    /// with `seed` for backward compatibility. Same
    /// `(library_state, seed)` on the `rng=None` path always produces
    /// the same permutation — see module docstring for the
    /// determinism guarantee and RNG-choice rationale.
    ///
    /// CoW-safe: routes through `Arc::make_mut` on the library Vec.
    /// No-op if the library has 0 or 1 element (Fisher-Yates does
    /// nothing meaningful in those cases, but we still pay the
    /// `Arc::make_mut` cost for consistency — callers that care can
    /// gate on `library_sizes[player_id] >= 2` themselves).
    #[pyo3(signature = (player_id, seed, *, rng = None))]
    fn shuffle_library_with_seed(
        &mut self,
        player_id: u8,
        seed: u64,
        rng: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(());
        }
        let player = &mut self.players[idx];
        let lib = Arc::make_mut(&mut player.library);
        fisher_yates_shuffle_optional(lib, rng, seed)?;
        Ok(())
    }

    /// Peek at the top `n` cards of `player_id`'s library and return
    /// their obj_ids in top-first order (top of library = FIRST
    /// element of the Vec, so the returned list reads the head
    /// of the Vec forward).
    ///
    /// Pure read — no library mutation, no Arc clone-on-write.
    /// Returns at most `min(n, library_size)` ids; an empty library
    /// or `n == 0` returns an empty list.
    fn scry(&self, player_id: u8, n: usize) -> PyResult<Vec<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(Vec::new());
        }
        let lib = &self.players[idx].library;
        let take = n.min(lib.len());
        // Library is stored top-first (post-CE3): "top" = lib[0].
        // Read the head forward to produce top-first order.
        let mut out = Vec::with_capacity(take);
        for obj in lib[..take].iter() {
            out.push(obj.id);
        }
        Ok(out)
    }

    /// Find the first GameObject in `player_id`'s library matching
    /// `printing_id` and return its `obj_id`, without moving or
    /// reordering the library. Returns `None` if no card with that
    /// printing_id is in the library.
    ///
    /// Pure read — no library mutation, no `Arc::make_mut` clone.
    /// "First" = first by Vec position (lib[0] = TOP of library
    /// post-CE3); for tutor-style effects callers usually only care
    /// that *some* matching card was found, not which one.
    fn search_library_for_first_with_printing(
        &self,
        player_id: u8,
        printing_id: u32,
    ) -> PyResult<Option<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(None);
        }
        let lib = &self.players[idx].library;
        for obj in lib.iter() {
            if obj.printing_id == printing_id {
                return Ok(Some(obj.id));
            }
        }
        Ok(None)
    }

    /// Find the first GameObject in `player_id`'s library matching
    /// `printing_id`, move it to that player's hand (zone field
    /// updated to `ZONE_HAND`), and shuffle the library afterward
    /// using the supplied `shuffle_seed` (inline xorshift64 +
    /// Fisher-Yates, same RNG as `shuffle_library_with_seed`).
    /// Returns the moved object's `obj_id` on success, or `None` if
    /// no card with that printing_id is in the library.
    ///
    /// Real MTG: per CR 701.18, even a *failed* search shuffles the
    /// library — the search itself is the trigger for the shuffle,
    /// not the move. This primitive honors that: on a miss, the
    /// library still gets shuffled with the supplied seed; only the
    /// hand-move is skipped.
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`,
    /// so cloning a `GameState` and calling this on the clone leaves
    /// the source's library and hand untouched.
    #[pyo3(signature = (player_id, printing_id, shuffle_seed, *, rng = None))]
    fn search_library_and_move_to_hand(
        &mut self,
        player_id: u8,
        printing_id: u32,
        shuffle_seed: u64,
        rng: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Option<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(None);
        }
        let player = &mut self.players[idx];
        // Locate the first match in the library; if found, remove it
        // and move to hand BEFORE the shuffle (so the shuffle operates
        // on the post-removal library, matching the rule that the
        // searched card is no longer in the library when it's
        // reshuffled).
        let pos = player
            .library
            .iter()
            .position(|o| o.printing_id == printing_id);
        let moved_id = if let Some(p) = pos {
            let lib = Arc::make_mut(&mut player.library);
            let mut obj = lib.remove(p);
            obj.zone = crate::state_ops_zones::ZONE_HAND;
            let id = obj.id;
            Arc::make_mut(&mut player.hand).push(obj);
            Some(id)
        } else {
            None
        };
        // Shuffle the library regardless of search outcome — failed
        // search still shuffles per CR 701.18. CE8 Slice 2: when `rng`
        // is `Some(_)`, the post-search shuffle consumes draws from the
        // external stream; otherwise the legacy xorshift64 path runs
        // seeded with `shuffle_seed`.
        let lib = Arc::make_mut(&mut player.library);
        fisher_yates_shuffle_optional(lib, rng, shuffle_seed)?;
        Ok(moved_id)
    }

    /// Find the first GameObject in `player_id`'s library whose
    /// printing's `card_types` contains `card_type` (e.g. "Creature",
    /// "Land", "Instant"), iterating top-to-bottom, and return its
    /// `obj_id`. Returns `None` if no card with that type is in the
    /// library.
    ///
    /// "Top-to-bottom" honors the post-CE3 zone convention that
    /// `lib[0]` is the top of the library — this primitive iterates
    /// the Vec forward so the very top card is checked first. Tutor
    /// effects that fetch by type (Worldly Tutor, Crop Rotation,
    /// Demonic Tutor's "any card" generalization) usually take the
    /// topmost qualifying card so the search is deterministic;
    /// "first by Vec position" matches player intent on a stacked
    /// library when index 0 is the top.
    ///
    /// Pure read — no library mutation, no `Arc::make_mut` clone.
    ///
    /// Raises `ValueError` on out-of-range `player_id`. (The
    /// printing-id sibling returns `None` on a bad player; this
    /// method is loud per the round-15 spec — silent no-op on
    /// caller bug obscures real bugs at the bridge layer.)
    fn search_library_for_first_of_type(
        &self,
        player_id: u8,
        card_type: &str,
    ) -> PyResult<Option<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        let lib = &self.players[idx].library;
        // Iterate top-to-bottom: top of library = lib[0] (post-CE3).
        for obj in lib.iter() {
            let printing = match self.registry.lookup(obj.printing_id) {
                Some(p) => p,
                None => continue,
            };
            if printing.card_types.iter().any(|t| t == card_type) {
                return Ok(Some(obj.id));
            }
        }
        Ok(None)
    }

    /// Find the first GameObject in `player_id`'s library whose
    /// printing's `card_types` contains `card_type` (top-to-bottom
    /// iteration), move it to that player's hand (zone field updated
    /// to `ZONE_HAND`), and return the moved object's `obj_id`.
    /// Returns `None` if no card with that type is in the library —
    /// in which case **neither** the library nor the hand are mutated
    /// (no shuffle on miss; this method is the bit-for-bit no-op
    /// composition of search + move, not the round-14 "failed search
    /// still shuffles" variant).
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`,
    /// so cloning a `GameState` and calling this on the clone leaves
    /// the source's library and hand untouched.
    ///
    /// Raises `ValueError` on out-of-range `player_id`, mirroring the
    /// search-only sibling.
    fn search_library_for_first_of_type_and_move_to_hand(
        &mut self,
        player_id: u8,
        card_type: &str,
    ) -> PyResult<Option<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        // Locate top-to-bottom: scan from lib[0] (top, post-CE3)
        // forward; the first index whose printing has `card_type`
        // in its `card_types` is our match. Inlined here rather than
        // calling the search-only method because we need the Vec
        // INDEX (to remove), not just the obj_id.
        let pos: Option<usize> = {
            let lib = &self.players[idx].library;
            let mut found: Option<usize> = None;
            for (i, obj) in lib.iter().enumerate() {
                let printing = match self.registry.lookup(obj.printing_id) {
                    Some(p) => p,
                    None => continue,
                };
                if printing.card_types.iter().any(|t| t == card_type) {
                    found = Some(i);
                    break;
                }
            }
            found
        };
        let p = match pos {
            Some(p) => p,
            None => return Ok(None),
        };
        let player = &mut self.players[idx];
        let lib = Arc::make_mut(&mut player.library);
        let mut obj = lib.remove(p);
        obj.zone = crate::state_ops_zones::ZONE_HAND;
        let id = obj.id;
        Arc::make_mut(&mut player.hand).push(obj);
        Ok(Some(id))
    }

    /// Tutor-style: find the first GameObject in `player_id`'s library
    /// whose printing's `card_types` contains `card_type` (top-to-bottom
    /// iteration), move it to that player's hand if found, and ALWAYS
    /// shuffle the library afterward (CR 701.19) — whether or not a
    /// matching card was found. Returns the moved object's `obj_id`,
    /// or `None` if no match was in the library (the library is still
    /// shuffled in the no-match case).
    ///
    /// This is round-15's `search_library_for_first_of_type_and_move_to_hand`
    /// composed with an unconditional post-search shuffle. The shuffle
    /// uses an inline xorshift64 + Fisher-Yates seeded with `seed` —
    /// same RNG as `shuffle_library_with_seed`. Same `(library, found
    /// or not, seed)` produces the same resulting library order.
    ///
    /// Why per-CR 701.19 we shuffle even on a miss: in real MTG, a
    /// failed tutor search still publicly reveals to the opponent that
    /// the card-type isn't in the library. Mechanically the rule
    /// collapses success and failure into a single "shuffle library"
    /// step, so the engine primitive does the same thing.
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`,
    /// so cloning a `GameState` and calling this on the clone leaves
    /// the source's library and hand untouched.
    ///
    /// Raises `ValueError` on out-of-range `player_id`, mirroring the
    /// search-only sibling.
    #[pyo3(signature = (player_id, card_type, seed, *, rng = None))]
    fn search_library_for_first_of_type_and_shuffle(
        &mut self,
        player_id: u8,
        card_type: &str,
        seed: u64,
        rng: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Option<u32>> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        // Locate top-to-bottom: scan from lib[0] (top, post-CE3)
        // forward; first index whose printing has `card_type` in its
        // `card_types` is our match. Inlined here (vs. delegating to
        // the no-shuffle sibling) because we need the Vec INDEX for
        // removal and we still want the shuffle to run on a miss.
        let pos: Option<usize> = {
            let lib = &self.players[idx].library;
            let mut found: Option<usize> = None;
            for (i, obj) in lib.iter().enumerate() {
                let printing = match self.registry.lookup(obj.printing_id) {
                    Some(p) => p,
                    None => continue,
                };
                if printing.card_types.iter().any(|t| t == card_type) {
                    found = Some(i);
                    break;
                }
            }
            found
        };
        let player = &mut self.players[idx];
        let moved_id: Option<u32> = if let Some(p) = pos {
            let lib = Arc::make_mut(&mut player.library);
            let mut obj = lib.remove(p);
            obj.zone = crate::state_ops_zones::ZONE_HAND;
            let id = obj.id;
            Arc::make_mut(&mut player.hand).push(obj);
            Some(id)
        } else {
            None
        };
        // ALWAYS shuffle (CR 701.19) — operates on the post-removal
        // library when a card was found, on the unchanged library on
        // a miss. CE8 Slice 2: when `rng` is `Some(_)`, the post-search
        // shuffle consumes draws from the external stream; otherwise
        // the legacy xorshift64 path runs seeded with `seed`.
        let lib = Arc::make_mut(&mut player.library);
        fisher_yates_shuffle_optional(lib, rng, seed)?;
        Ok(moved_id)
    }

    /// Mill `count` cards from the top of `player_id`'s library into
    /// that player's graveyard. Returns the actual number of cards
    /// milled (`usize`) — may be less than `count` if the library
    /// runs out before `count` is reached.
    ///
    /// Complement to round-1's `Effect::Mill`, which always mills the
    /// resolving spell's controller (= `active_player`). This primitive
    /// is the "specify which player gets milled" form — needed for
    /// effects whose target is "target player puts the top N cards of
    /// their library into their graveyard" (Glimpse the Unthinkable,
    /// Mind Funeral, Tasha's Hideous Laughter — anything that names a
    /// non-controller target).
    ///
    /// **"Top of library" convention** (post-CE3, inherited from
    /// `state_ops_zones.rs`): `lib[0]` is the top of the library, so
    /// each mill `remove(0)`s the head.
    ///
    /// **Per-object state reset on zone change** (CR 400.7): each
    /// milled card lands in the graveyard with `tapped`,
    /// `summoning_sick`, `damage`, and `counters` all zeroed plus
    /// `zone` stamped to `ZONE_GRAVEYARD`. Mirrors the reset pattern
    /// in `move_object` and `draw_card` (`state_ops_zones.rs`) and the
    /// other graveyard-bound effect handlers in `state_ops_resolve.rs`
    /// (ReturnToHand / Sacrifice / etc.).
    ///
    /// **Empty library / count = 0 short-circuit:** no `Arc::make_mut`
    /// clone fires on the no-op paths — mirrors round-3's
    /// `clear_damage_for_player` skip-CoW-on-empty optimization. Real
    /// MTG: milling an empty library is NOT a deck-out by itself
    /// (CR 704.5b applies to drawing, not milling), so the silent
    /// "stop early when library runs dry" matches round-1 `Effect::Mill`
    /// semantics.
    ///
    /// **Validation:**
    /// - `count < 0` raises `ValueError` (loud-fail per the project
    ///   convention; `gain_life` / `lose_life` / `pay_life_cost` use
    ///   the same shape). `count = 0` is a legal no-op and returns 0.
    /// - `player_id` not in `{0, 1}` raises `IndexError`, mirroring
    ///   how `move_object_from_graveyard_to_battlefield` and the other
    ///   round-1 player-indexed primitives validate.
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`,
    /// so cloning a `GameState` and milling on the clone leaves the
    /// source's library and graveyard untouched.
    fn mill_target_player(
        &mut self,
        player_id: u8,
        count: i32,
    ) -> PyResult<usize> {
        if count < 0 {
            return Err(PyValueError::new_err(format!(
                "count {count} must be >= 0"
            )));
        }
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyIndexError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        // Short-circuit: count = 0 OR empty library = no-op, no
        // Arc::make_mut clone. Mirrors round-3's `clear_damage_for_player`.
        let n = count as usize;
        if n == 0 {
            return Ok(0);
        }
        if self.players[idx].library.is_empty() {
            return Ok(0);
        }
        // Cap milled count at library size (silent stop on early
        // deck-out, matches round-1 Effect::Mill).
        let player = &mut self.players[idx];
        let to_mill = n.min(player.library.len());
        let lib = Arc::make_mut(&mut player.library);
        // Remove top-of-library cards (= head of Vec, post-CE3),
        // pushing each onto graveyard with the per-object state reset.
        // Collect first to release the &mut borrow on `lib` before we
        // touch graveyard.
        let mut milled: Vec<GameObject> = Vec::with_capacity(to_mill);
        for _ in 0..to_mill {
            // Always remove index 0 — that's the current top after each
            // prior remove shifts the next-top down to index 0.
            let mut obj = lib.remove(0);
            obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
            obj.tapped = false;
            obj.summoning_sick = false;
            obj.damage = 0;
            obj.counters = 0;
            milled.push(obj);
        }
        let gy = Arc::make_mut(&mut player.graveyard);
        gy.extend(milled);
        Ok(to_mill)
    }

    /// Apply a scry decision: the top `top_ids.len() + bottom_ids.len()`
    /// cards of `player_id`'s library are reordered so that:
    ///
    /// - `top_ids` lands at the new top of library, in the order
    ///   given (first element of `top_ids` is the new very top).
    /// - `bottom_ids` lands at the bottom of library, in the order
    ///   given (first element of `bottom_ids` is the very bottom of
    ///   the new library).
    ///
    /// Validates that the union of `top_ids + bottom_ids` exactly
    /// matches the top `N` ids the caller would have peeked at via
    /// `scry(player_id, N)`. Returns `false` (no library mutation)
    /// on validation failure: missing id, extra id, duplicated id,
    /// or an id that wasn't in the top N. Returns `true` on success.
    ///
    /// CoW-safe: routes through `Arc::make_mut` on the library Vec
    /// only after validation passes (so a failed validation costs
    /// nothing in CoW terms).
    fn apply_scry(
        &mut self,
        player_id: u8,
        top_ids: Vec<u32>,
        bottom_ids: Vec<u32>,
    ) -> PyResult<bool> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Ok(false);
        }
        let total = top_ids.len() + bottom_ids.len();
        let lib_len = self.players[idx].library.len();
        if total > lib_len {
            return Ok(false);
        }
        // Validate: the multiset of (top_ids + bottom_ids) must equal
        // the multiset of the top `total` library ids. Post-CE3,
        // lib[0..total] is the top-N window (head of Vec = top).
        let lib = &self.players[idx].library;
        // Top-N obj_ids (in arbitrary order — we're checking set/multiset
        // equality, not ordering).
        let mut top_n: Vec<u32> = lib[..total].iter().map(|o| o.id).collect();
        let mut requested: Vec<u32> =
            top_ids.iter().chain(bottom_ids.iter()).copied().collect();
        top_n.sort_unstable();
        requested.sort_unstable();
        if top_n != requested {
            return Ok(false);
        }
        // Validation passed — build the replacement slice.
        // Find each requested id's GameObject by scanning the top-N
        // window (we already know they're all in there).
        // Cost is O(total^2) which is fine for scry depths in single
        // digits.
        let player = &mut self.players[idx];
        let lib = Arc::make_mut(&mut player.library);
        // Snapshot the top-N (drained) objects so we can recompose
        // them in the new order. Library is top-first (lib[0] = top
        // post-CE3), so the drained head is the top of the library.
        let drained: Vec<GameObject> = lib.drain(..total).collect();
        let find_obj = |id: u32| -> GameObject {
            // Round-27 (UEOT framework): GameObject lost its `Copy`
            // derive when `ueot_modifiers: Vec<UeotModifier>` landed.
            // Replace the `*ref` deref with an explicit `.clone()` on
            // the found reference. The empty-modifiers case (the
            // common path for cards-in-library, which haven't seen
            // any UEOT effect) clones a single null heap pointer +
            // zero len/cap — cheap even without Copy semantics.
            drained
                .iter()
                .find(|o| o.id == id)
                .expect("validated above: id must be in drained")
                .clone()
        };
        // Rebuild the library as (front -> back, top -> bottom):
        //   [top_ids in given order]     (top_ids[0] = very top, lib[0])
        //   [old lib[total..] unchanged] (the below-the-scry portion)
        //   [bottom_ids in given order]  (bottom_ids[0] = lib's tail-
        //                                 most-but-first-of-bottom; the
        //                                 LAST bottom_id is lib[len-1]
        //                                 = very bottom)
        // Sending a card to the bottom = push to the end of the Vec
        // (tail = bottom post-CE3). The first bottom_id sits just
        // above the second, etc., so bottom_ids[0] is the FIRST-of-
        // bottom (closest to the existing library middle); the LAST
        // bottom_id is the very bottom. To honor "first id = very
        // bottom" semantics seen in the legacy version, we keep that
        // contract: bottom_ids[0] = very bottom = lib[len-1].
        // Implementation: append bottom_ids in REVERSE so the last-
        // appended (bottom_ids[0]) is at lib.len()-1.
        let kept_below: Vec<GameObject> = lib.drain(..).collect();
        let mut rebuilt: Vec<GameObject> = Vec::with_capacity(lib_len);
        // Top portion first.
        for &id in top_ids.iter() {
            rebuilt.push(find_obj(id));
        }
        // Below-the-scry-window middle.
        rebuilt.extend(kept_below);
        // Bottom portion: append in reverse so bottom_ids[0] lands
        // at the very last index (the bottom).
        for &id in bottom_ids.iter().rev() {
            rebuilt.push(find_obj(id));
        }
        debug_assert_eq!(rebuilt.len(), lib_len);
        *lib = rebuilt;
        Ok(true)
    }
}
