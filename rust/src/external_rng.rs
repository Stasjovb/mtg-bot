//! External-RNG callback substrate for CE8 Slice 1.
//!
//! Lets Rust gameplay shuffles consume draws from a caller-supplied
//! Python `random.Random` instance via PyO3. The harness-side use case
//! is: pass the SAME `random.Random` into both Python and Rust so any
//! draw-order divergence between the two engines surfaces as a loud
//! stream-position desync instead of a silent "different permutation
//! but same RNG seed" mismatch.
//!
//! ## Why `_randbelow`
//!
//! Python's `random.Random.shuffle` is a Fisher-Yates over the
//! semi-private `_randbelow(n)` primitive (rejection-sampling
//! uniform draw in `[0, n)`). To get bit-identical permutations to
//! Python's `shuffle`, Rust's Fisher-Yates must consume the SAME
//! `_randbelow(n)` calls in the same order.
//!
//! `_randbelow` has been stable since Python 3.0 — the docstring +
//! algorithm have shifted twice for code-clarity reasons (commits
//! `cba9a44f8a`, `2f0d8b7b3a`), but the signature `_randbelow(n: int)
//! -> int` and the output sequence for a given Mersenne-Twister state
//! have not changed. See CE8 playbook §11 Risk 4 for a mitigation
//! checklist if a future Python release ever shifts the algorithm.
//!
//! ## Backward compat — `next_below` accepts `Option`
//!
//! Every gameplay-RNG site that takes an `rng: Option<&Bound<'_, PyAny>>`
//! parameter falls back to its slice-local xorshift64 when `rng` is
//! `None`. Production callers (cli / bench) keep passing `None` and
//! stay byte-equivalent to pre-slice behavior; only the parity harness
//! and CE8 cross-engine smoke tests opt into the external-RNG path.

use pyo3::prelude::*;

/// Consume a single uniform draw in `[0, n)` from a Python
/// `random.Random` instance via the `_randbelow(n)` method.
///
/// Matches the exact primitive Python's `random.shuffle` uses, so a
/// Fisher-Yates loop in Rust that consumes `next_below(rng, i+1)` for
/// `i` in `(1..n).rev()` produces the SAME permutation as
/// `random.shuffle(list)` running on the same Python `Random`.
///
/// Caller is expected to pass an object that has a `_randbelow`
/// callable — any `random.Random` subclass (including the default
/// `random.Random`) qualifies. Passing an object without
/// `_randbelow` surfaces as a PyAttributeError-wrapped PyResult.
///
/// ## Performance
///
/// One callback per draw is ~1-2 µs (GIL is already held; the cost is
/// attribute lookup + integer marshal). A 60-card library shuffle is
/// ~60 callbacks → ~60-120 µs. Acceptable for cross-engine smoke
/// paths where wall-time isn't a hot constraint. If a production
/// codepath ever needs Python-MT shuffles, see the playbook §11
/// Risk 2 batched-draw mitigation.
#[inline]
pub fn next_below(rng: &Bound<'_, PyAny>, n: usize) -> PyResult<usize> {
    let result = rng.call_method1("_randbelow", (n,))?;
    result.extract::<usize>()
}
