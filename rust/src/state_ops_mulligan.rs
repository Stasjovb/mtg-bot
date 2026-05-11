//! Mulligan / opening-hand primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! ## Slice scope
//!
//! `mulligan(player_id, seed)` moves all cards in the player's hand
//! BACK to the library, shuffles the library with `seed`, then draws
//! 7 cards (or until the library is empty). The caller separately
//! tracks the mulligan count and (per CR 103.4 / London mulligan)
//! chooses which N cards to put on the bottom afterwards — that
//! "put N to bottom" step is a separate primitive that this slice
//! does not yet provide (deferred to a future slice).
//!
//! There is no separate `opening_hand` convenience: the synthetic
//! state seeds 7 cards in hand already, so an opening-hand call is
//! logically a hand-replace, which is what `mulligan` does. One
//! primitive covers both the at-game-start and iterative-mulligan
//! call sites.
//!
//! ## Cross-file friction (inlined logic)
//!
//! `shuffle_library_with_seed` (round-4 library) and `draw_card`
//! (round-1 zones) are pymethods, exposed to Python but Rust-private.
//! Calling them from this module would require either making them
//! `pub` (touches sibling files in this round) or duplicating their
//! logic here. Per the recurring round pattern, this slice inlines
//! both:
//!
//!   - The xorshift64 RNG + Fisher-Yates shuffle (mirroring
//!     `state_ops_library.rs::shuffle_library_with_seed`).
//!   - The pop-from-library-tail + push-to-hand draw step
//!     (mirroring `state_ops_zones.rs::draw_card`).
//!
//! When a later slice consolidates the public surface, the obvious
//! refactor is to lift the helpers into a private module both files
//! can depend on without growing `pub` API. Documented here so the
//! duplication is visible to the next round.
//!
//! ## Max-mulligan cap (round-26 G23 closure)
//!
//! Each call to `mulligan` or `mulligan_to_n` increments
//! `Player.mulligan_count` BEFORE the shuffle. If the count exceeds
//! 7, the call raises `PyValueError` instead of mutating any zone.
//! Mirrors Python `simulate.setup_game(max_mulligans=7)` — the
//! London-mulligan loop allows at most 7 mulligans per player before
//! forcing a keep; an 8th call is nonsensical (mulligan to -1 cards).
//!
//! `mulligan_count` is intentionally NOT serialized into the
//! fingerprint — it's a per-call safety counter, not part of the
//! gameplay-relevant state digest.
//!
//! ## Atomic London transaction (round-27 G21 + G22 closure)
//!
//! `mulligan_atomic(player_id, seed, bottom_card_ids)` is the
//! parity-correct entrypoint for the harness — it folds shuffle +
//! redraw + bottom-N into one call so a caller can't observe a
//! state with the hand still at 7 after the Nth mulligan. The
//! bottom-count is gated against the per-player `mulligan_count`
//! pre-increment: the Nth mulligan (where `mulligan_count` is N-1
//! at call time, incrementing to N) bottoms exactly N cards. The
//! legacy `mulligan` / `mulligan_to_n` / `bottom_cards_from_hand`
//! primitives are KEPT for backwards compatibility with existing
//! tests and call sites, but parity-driving callers should use
//! `mulligan_atomic`.
//!
//! ## CoW
//!
//! All mutation flows through `Arc::make_mut` on the touched zones
//! (the player's hand and library). Cloning a `GameState` and then
//! calling `mulligan` on the clone leaves the source state's hand
//! and library untouched — verified by
//! `test_clone_then_mulligan_does_not_affect_original`.

use crate::state::GameState;
use crate::state_ops_zones::{ZONE_HAND, ZONE_LIBRARY};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::sync::Arc;

/// Inline xorshift64 — duplicated from `state_ops_library.rs`. See
/// the module docstring for the cross-file-friction rationale.
struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
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

    fn next_usize_below(&mut self, n: usize) -> usize {
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

#[pymethods]
impl GameState {
    /// Move every card in `player_id`'s hand back to that player's
    /// library, shuffle the library with `seed`, then draw 7 cards
    /// (or until the library is empty). Each touched object's `zone`
    /// field is updated to match its destination.
    ///
    /// Raises `ValueError` if `player_id` is not 0 or 1.
    ///
    /// CoW-safe: hand + library mutations both route through
    /// `Arc::make_mut`. Same `(state, seed)` produces the same
    /// post-mulligan state, byte for byte (determinism guarantee).
    fn mulligan(&mut self, player_id: u8, seed: u64) -> PyResult<()> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        let player = &mut self.players[idx];

        // Round-26 G23 closure: cap mulligan count per player at 7.
        // Mirrors Python `simulate.setup_game(max_mulligans=7)` — the
        // London-mulligan loop allows up to 7 mulligans before
        // forcing a keep. The 8th call is nonsensical (mulligan to
        // -1 cards) and raises. The counter increments BEFORE the
        // cap check so the 8th call (which would set count=8) is the
        // one that raises, while calls 1..7 (count becomes 1..7) all
        // succeed.
        player.mulligan_count = player.mulligan_count.saturating_add(1);
        if player.mulligan_count > 7 {
            return Err(PyValueError::new_err(format!(
                "player {player_id} has already mulliganed 7 times \
                 (CR 103.4 / Python simulate.max_mulligans cap); \
                 mulligan_count is now {count}",
                count = player.mulligan_count,
            )));
        }

        // Step 1: drain the hand into the library. Each returned
        // object's zone field is restamped to ZONE_LIBRARY so a
        // post-mulligan find_object_zone read of the field agrees
        // with where the object actually lives. Scoped so the &mut
        // borrows of player.hand / player.library don't outlast the
        // step (we need a fresh &mut player.hand in step 3).
        {
            let hand = Arc::make_mut(&mut player.hand);
            let returning: Vec<_> = hand.drain(..).collect();
            let lib = Arc::make_mut(&mut player.library);
            for mut obj in returning {
                obj.zone = ZONE_LIBRARY;
                lib.push(obj);
            }

            // Step 2: Fisher-Yates shuffle of the library (no-op when
            // n < 2). Mirrors state_ops_library.rs's shuffle.
            let n = lib.len();
            if n >= 2 {
                let mut rng = XorShift64::new(seed);
                for i in (1..n).rev() {
                    let j = rng.next_usize_below(i + 1);
                    lib.swap(i, j);
                }
            }
        }

        // Step 3: draw 7 (or until empty). Top of library = LAST
        // element of the Vec, matching state_ops_zones.rs's draw_card
        // convention.
        let hand = Arc::make_mut(&mut player.hand);
        let lib = Arc::make_mut(&mut player.library);
        for _ in 0..7 {
            let Some(mut obj) = lib.pop() else {
                break;
            };
            obj.zone = ZONE_HAND;
            hand.push(obj);
        }
        Ok(())
    }

    /// Parameterized variant of [`mulligan`]: returns the player's
    /// hand to the library, shuffles with `seed`, and draws exactly
    /// `n_cards` cards back into hand. Powers London-mulligan callers
    /// that take progressively smaller hands (7, 6, 5, ...) on each
    /// successive mulligan; the "put N to the bottom" step that real
    /// London also requires is a separate primitive (deferred slice).
    ///
    /// Errors:
    ///
    /// - `ValueError` if `player_id` is not 0 or 1.
    /// - `ValueError` if `n_cards` is negative.
    /// - `ValueError` if `n_cards` exceeds the post-return library
    ///   size. Defensive guard — real London never asks for more
    ///   cards than the library can provide.
    ///
    /// CoW-safe (same `Arc::make_mut` discipline as `mulligan`).
    fn mulligan_to_n(&mut self, player_id: u8, n_cards: i32, seed: u64) -> PyResult<()> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        if n_cards < 0 {
            return Err(PyValueError::new_err(format!(
                "n_cards {n_cards} must be non-negative"
            )));
        }
        let n_cards = n_cards as usize;
        let player = &mut self.players[idx];

        // Round-26 G23 closure: shared cap with `mulligan` — at most
        // 7 mulligan / mulligan_to_n calls per player. Same shape as
        // above: increment first, raise if the post-increment count
        // exceeds 7.
        player.mulligan_count = player.mulligan_count.saturating_add(1);
        if player.mulligan_count > 7 {
            return Err(PyValueError::new_err(format!(
                "player {player_id} has already mulliganed 7 times \
                 (CR 103.4 / Python simulate.max_mulligans cap); \
                 mulligan_count is now {count}",
                count = player.mulligan_count,
            )));
        }

        // Step 1 + 2: drain the hand into the library, then shuffle.
        // Same as mulligan(); the only divergence is the draw count.
        {
            let hand = Arc::make_mut(&mut player.hand);
            let returning: Vec<_> = hand.drain(..).collect();
            let lib = Arc::make_mut(&mut player.library);
            for mut obj in returning {
                obj.zone = ZONE_LIBRARY;
                lib.push(obj);
            }

            // Defensive guard: post-return library must have at least
            // n_cards cards to satisfy the request.
            if n_cards > lib.len() {
                return Err(PyValueError::new_err(format!(
                    "mulligan_to_n: requested {n_cards} cards but only \
                     {avail} are available in player {player_id}'s library",
                    avail = lib.len(),
                )));
            }

            let n = lib.len();
            if n >= 2 {
                let mut rng = XorShift64::new(seed);
                for i in (1..n).rev() {
                    let j = rng.next_usize_below(i + 1);
                    lib.swap(i, j);
                }
            }
        }

        // Step 3: draw exactly n_cards (guarded above to be ≤ lib.len()).
        let hand = Arc::make_mut(&mut player.hand);
        let lib = Arc::make_mut(&mut player.library);
        for _ in 0..n_cards {
            let Some(mut obj) = lib.pop() else {
                break;
            };
            obj.zone = ZONE_HAND;
            hand.push(obj);
        }
        Ok(())
    }

    /// Take the FIRST `n` cards in `player_id`'s hand (insertion
    /// order, hand[0..n]) and put them on the BOTTOM of that player's
    /// library. The card at `hand[0]` lands at the very bottom
    /// (`library[0]`); `hand[1]` lands just above it (`library[1]`);
    /// and so on. The remaining hand entries (`hand[n..]`) shift down
    /// to occupy `hand[0..hand_size-n]`.
    ///
    /// "Library bottom" = INDEX 0 of the library Vec; "library top" =
    /// LAST element (matches the round-1 zone convention and `scry`).
    /// The library top is therefore unaffected by bottoming — only
    /// indices 0..n are inserted.
    ///
    /// This is the second half of the London mulligan (CR 103.4):
    /// round-11's `mulligan(player, seed)` draws 7 cards, and this
    /// primitive bottoms `n_mulligans_taken` of them. The choice of
    /// WHICH `n` cards to bottom is deterministic-by-position for now
    /// (always the first `n`); a future decision-callback slice will
    /// model real player choice.
    ///
    /// Errors:
    ///
    /// - `ValueError` if `player_id` is not 0 or 1.
    /// - `ValueError` if `n` is negative.
    /// - `ValueError` if `n` exceeds the current hand size.
    ///
    /// CoW-safe: hand + library mutations both route through
    /// `Arc::make_mut`, so cloning a `GameState` and bottoming on the
    /// clone leaves the source's hand and library untouched (verified
    /// by `test_bottom_cards_clone_isolation`).
    fn bottom_cards_from_hand(&mut self, player_id: u8, n: i32) -> PyResult<()> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        if n < 0 {
            return Err(PyValueError::new_err(format!(
                "n {n} must be non-negative"
            )));
        }
        let n = n as usize;
        let player = &mut self.players[idx];
        if n > player.hand.len() {
            return Err(PyValueError::new_err(format!(
                "can't bottom more cards than in hand: requested {n} \
                 but player {player_id}'s hand only has {hand_size}",
                hand_size = player.hand.len(),
            )));
        }
        if n == 0 {
            return Ok(());
        }

        let hand = Arc::make_mut(&mut player.hand);
        // Drain the first `n` cards from the hand (insertion order).
        // `drain(..n)` returns them in hand[0]..hand[n-1] order.
        let bottoming: Vec<_> = hand.drain(..n).collect();

        let lib = Arc::make_mut(&mut player.library);
        // Insert each card at index 0 IN ORDER. After the loop:
        //   - hand[0] inserted first → ends up at lib[n-1] of the
        //     bottomed batch (each later insert pushes it down).
        //   - hand[n-1] inserted last → sits at lib[0].
        // That's the OPPOSITE of what we want. We want hand[0] at
        // lib[0] (very bottom). So insert in REVERSE order: insert
        // hand[n-1] first (ends up at lib[n-1]), then hand[n-2]
        // (becomes the new lib[0], pushing hand[n-1] to lib[1]),
        // ..., finally hand[0] (becomes lib[0], pushing the rest up).
        for mut obj in bottoming.into_iter().rev() {
            // Reset per-instance state on the way out of hand. The
            // card is leaving any battlefield-only context (it can't
            // legally have been on the battlefield anyway, but be
            // defensive — future slices may reuse this primitive on
            // wider zones, and a stale `tapped` / `summoning_sick`
            // bit on a now-library object would be a latent bug).
            obj.zone = ZONE_LIBRARY;
            obj.tapped = false;
            obj.summoning_sick = false;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            lib.insert(0, obj);
        }
        Ok(())
    }

    /// Round-27 G21 + G22 closure: atomic London-mulligan transaction.
    ///
    /// Folds shuffle + redraw-7 + bottom-N into a single primitive so
    /// the harness can never observe a state with the hand still at
    /// 7 after the Nth mulligan. The Nth mulligan (where the per-
    /// player `mulligan_count` is N-1 at call time, incrementing to
    /// N) bottoms exactly N cards — the bottom-count is gated against
    /// the post-increment `mulligan_count` so the first call
    /// bottoms 1, the second bottoms 2, etc.
    ///
    /// Ordering:
    ///
    /// 1. Validate `player_id`.
    /// 2. Pre-check `bottom_card_ids.len() == mulligan_count + 1`
    ///    (count check BEFORE any mutation so a wrong-count call
    ///    leaves the state byte-identical to its pre-call shape).
    /// 3. Increment `mulligan_count`.
    /// 4. Cap check: if post-increment > 7, raise `ValueError`
    ///    BEFORE any zone mutation (matches the legacy
    ///    `mulligan` / `mulligan_to_n` ordering).
    /// 5. Shuffle: drain hand into library, Fisher-Yates with `seed`,
    ///    redraw 7 (or until library is empty).
    /// 6. Verify each `bottom_card_id` is in the post-redraw hand;
    ///    raise `ValueError` on any unknown id (the shuffle has
    ///    already happened, so the state has mutated — bottom step
    ///    is skipped on a verification failure).
    /// 7. Bottom the chosen ids in the caller-specified order: the
    ///    FIRST id ends up at the very bottom (`lib[0]`); each
    ///    successive id sits one slot above. Matches the
    ///    `bottom_cards_from_hand` orientation contract.
    ///
    /// Errors:
    ///
    /// - `ValueError` if `player_id` is not 0 or 1.
    /// - `ValueError` if `bottom_card_ids.len() != mulligan_count + 1`
    ///   (count mismatch — no mutation has happened yet).
    /// - `ValueError` if post-increment `mulligan_count > 7` (cap;
    ///   no zone mutation has happened yet, but `mulligan_count`
    ///   has been bumped — matches the legacy variants).
    /// - `ValueError` if any `bottom_card_id` is not in the post-
    ///   redraw hand (shuffle has happened; bottom step skipped).
    ///
    /// The CALLER chooses which cards to bottom (no decision-callback
    /// machinery in the Rust port yet). Since the post-shuffle hand
    /// is deterministic in `(state, seed)`, parity_smoke and MCTS
    /// can pre-compute the bottom set offline.
    ///
    /// CoW-safe (same `Arc::make_mut` discipline as `mulligan` /
    /// `bottom_cards_from_hand`). Backwards-compatibility note: the
    /// legacy `mulligan`, `mulligan_to_n`, and `bottom_cards_from_hand`
    /// primitives remain in place — only `mulligan_atomic` is the
    /// parity-correct entrypoint for new callers.
    fn mulligan_atomic(
        &mut self,
        player_id: u8,
        seed: u64,
        bottom_card_ids: Vec<u32>,
    ) -> PyResult<()> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        let player = &mut self.players[idx];

        // Step 2: pre-check the bottom count against the per-player
        // mulligan_count. The Nth mulligan (count BEFORE increment is
        // N-1, becomes N after the increment in step 3) bottoms
        // exactly N cards, so the expected size is
        // `mulligan_count + 1` at this point. Doing this BEFORE the
        // increment means a wrong-count call leaves state byte-
        // identical to its pre-call shape (no mulligan_count bump,
        // no shuffle, no bottom).
        let expected = (player.mulligan_count as usize).saturating_add(1);
        if bottom_card_ids.len() != expected {
            return Err(PyValueError::new_err(format!(
                "mulligan_atomic: bottom_card_ids has {got} entries, expected \
                 {expected} (the Nth mulligan must bottom N cards; \
                 mulligan_count is currently {pre} so this is mulligan #{n})",
                got = bottom_card_ids.len(),
                pre = player.mulligan_count,
                n = expected,
            )));
        }

        // Step 3 + 4: increment then cap-check. Same ordering as the
        // legacy variants — the 8th call (which would push count from
        // 7 to 8) is the one that raises. Mirrors Python
        // `simulate.setup_game(max_mulligans=7)`.
        player.mulligan_count = player.mulligan_count.saturating_add(1);
        if player.mulligan_count > 7 {
            return Err(PyValueError::new_err(format!(
                "player {player_id} has already mulliganed 7 times \
                 (CR 103.4 / Python simulate.max_mulligans cap); \
                 mulligan_count is now {count}",
                count = player.mulligan_count,
            )));
        }

        // Step 5: shuffle. Same recipe as `mulligan` — drain hand
        // into library, Fisher-Yates with `seed`, redraw 7 (or until
        // empty). Scoped block so the `&mut player.hand` /
        // `&mut player.library` borrows from the shuffle don't outlast
        // the redraw step.
        {
            let hand = Arc::make_mut(&mut player.hand);
            let returning: Vec<_> = hand.drain(..).collect();
            let lib = Arc::make_mut(&mut player.library);
            for mut obj in returning {
                obj.zone = ZONE_LIBRARY;
                lib.push(obj);
            }

            let n = lib.len();
            if n >= 2 {
                let mut rng = XorShift64::new(seed);
                for i in (1..n).rev() {
                    let j = rng.next_usize_below(i + 1);
                    lib.swap(i, j);
                }
            }
        }

        // Redraw 7 (or until empty). Top of library = LAST element.
        {
            let hand = Arc::make_mut(&mut player.hand);
            let lib = Arc::make_mut(&mut player.library);
            for _ in 0..7 {
                let Some(mut obj) = lib.pop() else {
                    break;
                };
                obj.zone = ZONE_HAND;
                hand.push(obj);
            }
        }

        // Step 6: verify every bottom_card_id is in the post-redraw
        // hand. The shuffle has already mutated state — atomic-vs-
        // legacy distinction is that the legacy split would let the
        // caller forget the bottom step entirely; here, any invalid
        // id raises BEFORE the bottoming runs, but the shuffle has
        // already happened. Callers should pre-compute valid ids.
        {
            let hand_ids: std::collections::HashSet<u32> =
                player.hand.iter().map(|o| o.id).collect();
            for id in &bottom_card_ids {
                if !hand_ids.contains(id) {
                    return Err(PyValueError::new_err(format!(
                        "mulligan_atomic: bottom_card_id {id} is not in \
                         player {player_id}'s post-redraw hand (hand has \
                         {hand_size} cards)",
                        hand_size = player.hand.len(),
                    )));
                }
            }
            // Also reject duplicate ids — bottoming the same card
            // twice is nonsensical and would corrupt the library.
            if hand_ids.len() < bottom_card_ids.len() {
                // The hand has at least bottom_card_ids.len() distinct
                // entries (since each id passed the contains check),
                // so if there are duplicates in bottom_card_ids itself
                // we'd see a duplicate-key insertion below. Check
                // explicitly via a count.
            }
            let unique: std::collections::HashSet<u32> =
                bottom_card_ids.iter().copied().collect();
            if unique.len() != bottom_card_ids.len() {
                return Err(PyValueError::new_err(format!(
                    "mulligan_atomic: bottom_card_ids contains duplicate \
                     entries ({duplicates} unique of {total})",
                    duplicates = unique.len(),
                    total = bottom_card_ids.len(),
                )));
            }
        }

        // Step 7: remove each chosen id from hand and append it to
        // the bottom of the library. Per the orientation contract
        // (`bottom_cards_from_hand`: hand[0] ends up at lib[0] /
        // very bottom; later ids sit above it), the FIRST id in
        // `bottom_card_ids` lands at the very bottom (`lib[0]`).
        // Implementation: walk the ids in REVERSE and insert each at
        // `lib[0]` — the last-walked (which is the first-supplied)
        // ends up at the bottom-most slot.
        let hand = Arc::make_mut(&mut player.hand);
        let lib = Arc::make_mut(&mut player.library);
        for id in bottom_card_ids.iter().rev() {
            // Find the position in hand by id. Linear scan is fine —
            // hand is at most 7 entries here.
            let pos = hand
                .iter()
                .position(|o| o.id == *id)
                .expect("verified above that id is in hand");
            let mut obj = hand.remove(pos);
            // Reset per-instance state (mirrors `bottom_cards_from_hand`).
            obj.zone = ZONE_LIBRARY;
            obj.tapped = false;
            obj.summoning_sick = false;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            lib.insert(0, obj);
        }
        Ok(())
    }
}
