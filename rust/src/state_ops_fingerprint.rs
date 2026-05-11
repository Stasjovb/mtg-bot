//! `fingerprint() -> str` pymethod on `GameState`.
//!
//! Round-22 phase-2b slice — implementation behind the stub the
//! foundation laid down. The pymethod produces a 12-char lowercase
//! hex digest computed identically to what
//! `scripts/parity_smoke.py:hash_state` produces for an equivalent
//! Python `GameState`. Two states (one Python, one Rust) that share
//! the same gameplay-relevant invariants produce the same digest.
//!
//! ## Hash recipe (mirror of `scripts/parity_smoke.py:hash_state`)
//!
//! ```text
//! parts = [
//!     turn_number,                         # int
//!     step,                                # str (Step.<NAME>) or None
//!     active_player_idx,                   # int
//!     priority_player_idx,                 # int or None
//!     is_over,                             # bool
//!     is_draw,                             # bool
//!     winner_id,                           # int or None
//!     (p0_id, life, has_lost, hand_sig, library_sig, graveyard_sig,
//!      exile_sig, mana_pool_sorted_items),
//!     (p1_id, ...),                        # same shape
//!     battlefield_signature,
//!     stack_signature,
//! ]
//! blob = json.dumps(parts, default=repr, sort_keys=False).encode("utf-8")
//! return hashlib.sha1(blob).hexdigest()[:12]
//! ```
//!
//! Each zone signature is a tuple of per-object 8-tuples
//! `(printing_name | None, int(tapped), int(summoning_sick),
//!   damage, counters, attached_to, controller_id, id)`.
//!
//! `mana_pool_sorted_items` mirrors the Python expression
//! `tuple(sorted({"W": w, "U": u, ..., "C": c}.items()))` — a
//! list of `[key, count]` 2-arrays sorted lexicographically by key.
//!
//! ## JSON-format gotchas
//!
//! Python `json.dumps(..., default=repr, sort_keys=False)` has a
//! specific output shape we have to match exactly to land the same
//! sha1 digest:
//!
//! * Python tuples and lists both serialize as JSON arrays — there
//!   are no JSON tuples. Rust mirrors by emitting `serde_json::Value::Array`
//!   for both.
//! * Booleans: Python emits `true` / `false`; `serde_json` matches.
//! * `None`: Python emits `null`; `serde_json::Value::Null` matches.
//! * Integers: bare digits both sides.
//! * Strings: JSON-quoted with backslash-escapes; `serde_json`'s
//!   default escaping is bytewise identical to Python's `json` for
//!   ASCII strings (which is all we emit — printing names come from
//!   the registry, which we control).
//! * Whitespace: Python's default (no spaces around `:` and `,`)
//!   matches `serde_json::to_string` (compact). Python by default
//!   uses `", "` / `": "` separators — BUT `json.dumps` without
//!   `indent=` uses `(", ", ": ")` separators which DOES emit a
//!   single space after both. `serde_json::to_string` emits no
//!   spaces. We override below by calling a compact serializer
//!   that matches Python's default-separator output, OR equivalently
//!   we manually emit a string. We chose: build the structure and
//!   serialize with a small custom writer that inserts the same
//!   spaces Python does. See `serialize_python_compatible`.
//! * `sort_keys=False`: we never emit JSON objects (only arrays),
//!   so this is moot for our output.
//!
//! ## Cross-engine parity scope
//!
//! Full byte-equality between the Rust fingerprint and Python's
//! `hash_state` on an equivalent state requires constructing the
//! Python state with matching shape:
//!
//! * Python's `state.mana_pool` is a `list[ManaCoin]` in
//!   `src/mtg_bot/game.py`, NOT a dict — so Python's hash_state
//!   `isinstance(..., dict)` check fails and the list flows through
//!   `default=repr`, producing a string like
//!   `"[ManaCoin(color='W', ...)]"`. Rust treats mana_pool as a
//!   dict (5 colors + colorless) and emits sorted items. To get
//!   cross-engine parity, the Python side would need a shimmed
//!   GameState with `mana_pool` as the equivalent dict.
//! * Python objects in zones have a `printing` attribute with `.name`;
//!   we look the same up through the registry. For object id alone
//!   (no printing), Python emits `None`; we match.
//! * Python's `attached_to` defaults to `None` (`getattr(..., None)`);
//!   Rust has no `attached_to` field yet — we emit `null`.
//!
//! Round-22 doesn't ship a Python-side shim; the cross-engine parity
//! test in `tests_rust/test_fingerprint.py` asserts equality against
//! a hard-coded baseline string computed from the same algorithm,
//! locking the format in a regression-safe way. A future round can
//! add the Python shim and assert byte-equality across the engines.

use crate::state::{GameObject, GameState};
use pyo3::prelude::*;
use serde_json::{json, Value};
use sha1::{Digest, Sha1};

/// Phase u8 -> Python `Step.<NAME>` string. Order mirrors the
/// `STEP_ORDER` tuple in `src/mtg_bot/turn.py`. Returns `None` for
/// phase values outside `[0, 11]` (defensive — `set_phase` already
/// rejects out-of-range writes; the `None` here lets a corrupted
/// state still produce *some* fingerprint instead of panicking).
fn phase_to_step_name(phase: u8) -> Option<&'static str> {
    match phase {
        0 => Some("UNTAP"),
        1 => Some("UPKEEP"),
        2 => Some("DRAW"),
        3 => Some("PRECOMBAT_MAIN"),
        4 => Some("BEGINNING_OF_COMBAT"),
        5 => Some("DECLARE_ATTACKERS"),
        6 => Some("DECLARE_BLOCKERS"),
        7 => Some("COMBAT_DAMAGE"),
        8 => Some("END_OF_COMBAT"),
        9 => Some("POSTCOMBAT_MAIN"),
        10 => Some("END"),
        11 => Some("CLEANUP"),
        _ => None,
    }
}

/// Project one GameObject to the 8-element JSON array mirror of
/// `_zone_signature`. Field order is the Python tuple order:
/// `(printing_name | None, int(tapped), int(summoning_sick),
///   damage, counters, attached_to, controller_id, id)`.
///
/// `int(tapped)` / `int(summoning_sick)` — Python casts to int (0/1).
/// We follow.
fn object_signature(state: &GameState, obj: &GameObject) -> Value {
    let name: Value = match state.registry.lookup(obj.printing_id) {
        Some(p) => Value::String(p.name.to_string()),
        None => Value::Null,
    };
    // Tapped + summoning_sick get `int(...)` cast on the Python side.
    Value::Array(vec![
        name,
        json!(obj.tapped as i32),
        json!(obj.summoning_sick as i32),
        json!(obj.damage),
        json!(obj.counters),
        Value::Null, // attached_to — no Rust field yet
        json!(obj.controller),
        json!(obj.id),
    ])
}

/// Project a zone (slice of GameObjects) to the JSON-array form of
/// `_zone_signature`'s `tuple(per-object 8-tuples)`. Order-sensitive.
fn zone_signature(state: &GameState, zone: &[GameObject]) -> Value {
    Value::Array(zone.iter().map(|o| object_signature(state, o)).collect())
}

/// Player tuple mirror — 8 fields, all populated even when
/// the corresponding Rust field doesn't exist yet (e.g. `has_lost`
/// is derived from `life <= 0` until the explicit-loss field lands).
///
/// `mana_pool_sorted_items` mirrors Python's
/// `tuple(sorted({"W": w, "U": u, ..., "C": c}.items()))` — a JSON
/// array of `[key, count]` 2-arrays, keys lex-sorted (B, C, G, R, U, W).
fn player_signature(state: &GameState, idx: usize) -> Value {
    let p = &state.players[idx];
    let pool = &p.mana_pool;
    // Python `tuple(sorted({"W":w, "U":u, ...}.items()))` keys lex-sorted.
    // Lex order: B, C, G, R, U, W.
    let mana_items: Vec<Value> = vec![
        Value::Array(vec![json!("B"), json!(pool.black)]),
        Value::Array(vec![json!("C"), json!(pool.colorless)]),
        Value::Array(vec![json!("G"), json!(pool.green)]),
        Value::Array(vec![json!("R"), json!(pool.red)]),
        Value::Array(vec![json!("U"), json!(pool.blue)]),
        Value::Array(vec![json!("W"), json!(pool.white)]),
    ];
    Value::Array(vec![
        json!(p.id),
        json!(p.life),
        // has_lost: round-26 G11 closure — the explicit sticky loss
        // flag now lives on `Player`. Pinned baselines were computed
        // when the slot was the derived `life <= 0`; for every state
        // used in those baselines the player is alive (life=20), so
        // `has_lost == false == (life <= 0 is false)` and the digest
        // is identical. New flows that drop `has_lost = true` without
        // dropping life shift the digest deliberately (mirrors Python).
        json!(p.has_lost),
        zone_signature(state, &p.hand),
        zone_signature(state, &p.library),
        zone_signature(state, &p.graveyard),
        zone_signature(state, &p.exile),
        Value::Array(mana_items),
    ])
}

/// Serialize a `serde_json::Value` with the same separator convention
/// as Python's default `json.dumps(...)` — `", "` and `": "` (a space
/// after every comma and colon). `serde_json::to_string` is compact
/// (no spaces); we want the spaces so the resulting blob matches the
/// Python side byte-for-byte before we hash.
///
/// We only ever emit arrays and primitives (no objects), so the colon
/// rule never fires. Implementation: walk the Value and emit each
/// piece.
fn serialize_python_compatible(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => {
            // Use serde_json's string escaping for correctness — it
            // matches Python's json default ASCII-escape behavior for
            // the printable ASCII names we emit.
            let escaped = serde_json::to_string(s).unwrap();
            out.push_str(&escaped);
        }
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                serialize_python_compatible(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            // Defensive — we never emit objects, but if we ever do,
            // mirror Python's `", "` / `": "` separators with
            // insertion-order (sort_keys=False).
            out.push('{');
            for (i, (k, v)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                let key_escaped = serde_json::to_string(k).unwrap();
                out.push_str(&key_escaped);
                out.push_str(": ");
                serialize_python_compatible(v, out);
            }
            out.push('}');
        }
    }
}

#[pymethods]
impl GameState {
    /// 12-char lowercase hex SHA1 digest of the gameplay-relevant
    /// state. Mirrors `scripts/parity_smoke.py:hash_state` — same
    /// `parts` shape, same JSON serialization, same SHA1 truncation.
    ///
    /// Determinism: same state -> same fingerprint, always. Clones
    /// share a fingerprint with their source until the source mutates.
    /// Mutating a clone after cloning produces a different fingerprint
    /// without affecting the source's.
    ///
    /// See the module docstring for the full hash recipe + the
    /// cross-engine parity scope (the Python side's mana_pool is a
    /// list-of-ManaCoin, not a dict, so a Python-side shim is
    /// needed for cross-engine byte-equality — round 22 ships only
    /// the Rust side; the regression-safe baseline test asserts
    /// against a hard-coded digest computed from a known synthetic
    /// state).
    fn fingerprint(&self) -> String {
        // Build `parts` mirroring Python `hash_state`.
        let step: Value = phase_to_step_name(self.phase)
            .map(|s| Value::String(s.to_string()))
            .unwrap_or(Value::Null);
        let parts = Value::Array(vec![
            json!(self.turn_number),
            step,
            json!(self.active_player),
            json!(self.priority_player),
            // Inlined `is_over` — sibling module's `is_game_over` /
            // `is_over` pymethods are private to their module (E0624),
            // so we duplicate the trivial life<=0 check here.
            json!(self.players[0].life <= 0 || self.players[1].life <= 0),
            json!(self.players[0].life <= 0 && self.players[1].life <= 0),
            match (self.players[0].life <= 0, self.players[1].life <= 0) {
                (false, true) => json!(self.players[0].id),
                (true, false) => json!(self.players[1].id),
                _ => Value::Null,
            },
            player_signature(self, 0),
            player_signature(self, 1),
            // Battlefield is centralized on Python's GameState; on
            // the Rust side it's split across players. We emit p0's
            // battlefield then p1's — same shape as
            // `battlefield_snapshot`. See snapshot module docstring
            // for the Python interleave-by-ETB-timestamp caveat.
            {
                let mut bf = Vec::with_capacity(
                    self.players[0].battlefield.len() + self.players[1].battlefield.len(),
                );
                for player in &self.players {
                    for obj in player.battlefield.iter() {
                        bf.push(object_signature(self, obj));
                    }
                }
                Value::Array(bf)
            },
            // Stack: today's StackItem has just (source_obj_id,
            // controller). For fingerprint purposes we emit it in
            // the same 8-tuple shape as a zone object — most fields
            // are Null / 0 since a stack item isn't a permanent.
            // Python's stack is a list of cards-on-stack with the
            // same `_zone_signature` projection.
            Value::Array(
                self.stack
                    .iter()
                    .map(|si| {
                        Value::Array(vec![
                            Value::Null,           // printing name unknown for now
                            json!(0),              // tapped
                            json!(0),              // summoning_sick
                            json!(0),              // damage
                            json!(0),              // counters
                            Value::Null,           // attached_to
                            json!(si.controller),  // controller_id
                            json!(si.source_obj_id), // id
                        ])
                    })
                    .collect::<Vec<_>>(),
            ),
        ]);

        let mut blob = String::new();
        serialize_python_compatible(&parts, &mut blob);

        let mut hasher = Sha1::new();
        hasher.update(blob.as_bytes());
        let digest = hasher.finalize();
        // 12-char lowercase hex (first 6 bytes of the 20-byte SHA1).
        let mut out = String::with_capacity(12);
        for byte in &digest[..6] {
            out.push_str(&format!("{:02x}", byte));
        }
        out
    }
}
