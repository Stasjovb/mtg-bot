//! Closed `Action` enum + Python-dict bridge.
//!
//! Round-22 foundation stub. The `rust-action-foundation` slice fills
//! in the variants (starting with `PassPriority`), the dict parser /
//! serializer, and the apply_action dispatch surface.
//!
//! Mirrors the cards.rs pattern (closed Effect enum + dict bridge).
//! Python builds plain dicts describing each Action; Rust parses to
//! the closed enum at the FFI boundary. Every Python `Action`
//! subclass has a corresponding Rust variant — no fallback path,
//! per round 5's no-opaque-blob design.

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    // Variants land in feature/rust-action-foundation. Empty for now
    // so the build is green pre-slice; downstream code uses a
    // placeholder stub function until the slice fills this in.
    _Reserved,
}
