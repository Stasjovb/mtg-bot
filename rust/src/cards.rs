// Card-data bridge: closed-vocabulary Rust representations of card
// printings + Python <-> Rust dict parsing / serialization.
//
// Design (see rust/README.md and worklog 2026-05-09):
//
// - Python builds nested dicts describing each card; the dicts are
//   plain (serializable, diffable, easy to fixture in tests).
// - Rust owns the closed enum vocabulary: `Effect`, `TargetFilter`,
//   `ManaCost`, `CardPrinting`. Every variant Python emits has a
//   Rust counterpart.
// - The dict parser is the single point of validation. Unknown
//   `kind` strings, missing required fields, type mismatches all
//   raise loudly at `register_printing` time, not at game-resolution
//   time.
// - `Registry` is a `#[pyclass]` Python holds explicitly. No global
//   mutable state. CardPrintings are immutable once registered;
//   GameObjects reference printings by id (see state.rs).
//
// First-slice scope: one effect (`DealDamage`), two target filters
// (`AnyPlayer`, `AnyCreature`), 5-color mana cost. Future commits
// add variants one at a time, each with parity tests against the
// Python equivalent on a real EoE card.
//
// **Storage shape:** `RegistryData` is the plain-Rust struct that
// owns the printings. `Registry` is the pyclass wrapper that holds
// a builder Vec; `snapshot()` freezes a clone of that Vec into an
// `Arc<RegistryData>` that `GameState` shares at refcount-bump
// cost. The first-slice register-then-snapshot workflow (build the
// registry up front, then snapshot once) means we don't yet need
// interior mutability — append-then-freeze is enough.

use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;
use std::time::Instant;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ManaCost {
    pub generic: u8,
    pub white: u8,
    pub blue: u8,
    pub black: u8,
    pub red: u8,
    pub green: u8,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TargetFilter {
    AnyPlayer,
    AnyCreature,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Effect {
    DealDamage { amount: i32, target: TargetFilter },
    /// Controller draws `count` cards. No target — caller's
    /// controller is implicit. Real "target player draws N" effects
    /// (e.g. Wheel of Fortune) need a player-target variant.
    DrawCards { count: i32 },
    /// Controller gains `amount` life. No target — caller's
    /// controller is implicit. Real "target player gains N life"
    /// effects need a player-target variant.
    GainLife { amount: i32 },
    /// Bounce: target permanent's owner (= controller in first slice)
    /// puts it back into their hand. Composes round-1 zones move.
    ReturnToHand { target: TargetFilter },
    /// Mill: caller's controller puts the top `count` cards of their
    /// library into their graveyard. No target — controller implicit.
    Mill { count: i32 },
    /// Exile target permanent (CR 406). Removes from its current
    /// zone to its owner's exile zone. First-slice owner =
    /// controller.
    ExileTarget { target: TargetFilter },
    /// Tap target permanent (CR 701.20a). Idempotent on already-
    /// tapped targets. AnyPlayer target raises (you can't tap a
    /// player).
    TapTarget { target: TargetFilter },
    /// Untap target permanent (CR 701.20b). Idempotent on already-
    /// untapped targets. AnyPlayer target raises.
    UntapTarget { target: TargetFilter },
    /// Sacrifice target permanent (CR 701.16). First-slice: target
    /// is the active player's first creature on their own
    /// battlefield (you sacrifice your own permanents). AnyPlayer
    /// raises.
    Sacrifice { target: TargetFilter },
    /// Add `count` +1/+1 (positive) or -1/-1 (negative) counters to
    /// target creature on the defending player's battlefield. Routes
    /// through round-2's net-counter model — `add_counters` adds the
    /// signed amount to a single i32 net counter on the GameObject.
    /// AnyPlayer raises (you can't counter a player). Round-15 first
    /// slice picks the AnyCreature target deterministically as the
    /// first creature on the defending player's battlefield, mirroring
    /// the DealDamage / TapTarget / UntapTarget convention.
    AddCounters { target: TargetFilter, count: i32 },
    /// Target player discards one card from hand (CR 701.8). First
    /// slice: deterministic choice = first card in target's hand
    /// (defending player for opponent-targeted discards). AnyCreature
    /// raises (you can't discard a creature). Empty hand = silent
    /// no-op (Python parity).
    DiscardCard { target: TargetFilter },
    /// Scry N (CR 701.18): controller looks at the top `count` cards
    /// of their library and chooses any number to put on the bottom;
    /// the rest stay on top in any order. No target — controller
    /// implicit. Routes through round-4's apply_scry primitive.
    /// First-slice deterministic choice: keep all cards on top
    /// (no-op-shaped-as-scry; future slice will plumb a decision
    /// callback for "which to bottom"). Negative `count` raises.
    ScryN { count: i32 },
    /// Destroy target permanent (CR 701.7). Diverges from Sacrifice
    /// in two ways: (a) the target is on the DEFENDING player's
    /// battlefield (not the active player's), and (b) it bypasses
    /// "you sacrifice your own permanent" semantics. First slice
    /// picks the AnyCreature target as the defender's first creature,
    /// mirroring DealDamage / TapTarget convention. AnyPlayer raises
    /// (you can't destroy a player). Empty defender battlefield =
    /// fizzle silently. Indestructible (round-13) is honored — the
    /// destroy is suppressed exactly like in the SBA path.
    DestroyTarget { target: TargetFilter },
    /// Deal `amount` damage to each opponent of the controller
    /// (CR 701.4 + AOE pattern). Two-player engine first slice:
    /// damages defender (= the one opponent). No target — implicit.
    /// Negative `amount` raises. Composes with round-14's
    /// deal_damage_to_player primitive.
    DamageEachOpponent { amount: i32 },
    /// Deal `amount` damage to each creature on the battlefield
    /// (CR 701.4 — Pyroclasm/Anger of the Gods pattern). Damages all
    /// creatures regardless of controller; round-13 indestructible
    /// honored at SBA time. No target — implicit. Negative `amount`
    /// raises.
    DamageEachCreature { amount: i32 },
    /// Create `count` token creatures on the controller's battlefield
    /// (CR 701.6). The token's stats come from a pre-registered
    /// printing referenced by `token_printing_id` — caller registers
    /// the token-printing once (e.g. "1/1 white Soldier creature
    /// token") and references its id in the effect. Tokens enter
    /// summoning-sick like other creatures; future "tokens cease to
    /// exist when they leave the battlefield" CR 110.5g handling is
    /// deferred. Negative `count` raises.
    CreateToken { count: i32, token_printing_id: u32 },
    /// Controller adds `amount` mana of `color` to their mana pool.
    /// CR 106.1 — the resolution of a mana ability. Color is one of
    /// W/U/B/R/G/C; amount is non-negative. AddManaToPool is the
    /// second-most-frequent Effect across the EoE pool (33 cards per
    /// round-20 measurement), powering land mana abilities and
    /// mana-rocks like Mind Stone.
    ///
    /// **Schema simplification vs Python.** Python's `AddManaToPool`
    /// dataclass carries a `produces: tuple[tuple[str, int], ...]`
    /// and a `spend_restriction: str | None` — a single Python
    /// dataclass can mint multiple colors per resolution and tag
    /// each coin with a payment-filtering restriction (e.g.
    /// "spend only on artifact spells"). The Rust closed-vocabulary
    /// bridge models the same behavior with a flatter shape: one
    /// `AddManaToPool` per (color, amount) pair, no spend
    /// restriction. A printing that produces multi-color mana
    /// stacks multiple `AddManaToPool` entries in its `effects`
    /// Vec; spend-restriction tagging is deferred until the bridge
    /// schema needs it (no EoE card today combines mana production
    /// with the restriction tagging through this dispatch path).
    AddManaToPool { color: String, amount: i32 },
    /// Search controller's library for up to ``count`` basic lands,
    /// put each onto the battlefield tapped, then shuffle the
    /// library (CR 701.19 search + 701.22 shuffle). Powers Rampant
    /// Growth, Beamsaw Prospector, Kavaron Harrier — 15 cards in
    /// the EoE pool per round-20 measurement. The "basic land"
    /// filter and "tapped" arrival flag are part of the variant's
    /// spec (no field). The single `count` field mirrors Python's
    /// `SearchLibraryForBasicLandTapped(count: int = 1)` dataclass
    /// shape — a count > 1 finds up to `count` basic lands one at
    /// a time (Larval Scoutlander / cycling-land bodies).
    ///
    /// **First-slice scope:**
    /// - **Deterministic first-match pick.** Scans the library
    ///   top-to-bottom (Vec iter().rev()) and grabs the topmost
    ///   matching object. Real MTG lets the player choose any
    ///   matching card; that's a future plumbing decision once
    ///   decision callbacks exist.
    /// - **Basic land filter = card_types contains "Land".** The
    ///   Rust bridge has no `supertypes` field today, so the
    ///   "basic" half of "basic land" is approximated by the
    ///   `card_types` Land check. In the EoE pool every basic land
    ///   is exactly card_types=["Land"] with no compound non-basic
    ///   land carrying this dispatch, so the proxy is faithful for
    ///   the current set. See SEARCH_LIMITATIONS entry for the
    ///   deferred supertypes work.
    /// - **No shuffle.** CR 701.19 says searches always shuffle the
    ///   library regardless of search outcome. This slice
    ///   deliberately does NOT shuffle — the deterministic first-
    ///   match pick makes the dispatch reproducible without
    ///   threading an RNG seed through `apply_effect`. The
    ///   `search_library_for_first_of_type_and_shuffle` primitive
    ///   in `state_ops_library.rs` is the right composition for a
    ///   future slice once RNG-externalization lands; see
    ///   SEARCH_LIMITATIONS entry.
    /// - **count<0 raises** loudly (mirrors ScryN / DealDamage /
    ///   DamageEach* / CreateToken raise-on-negative shape).
    /// - **count=0 is a legal no-op** (mirrors GainLife / DrawCards
    ///   / Mill / CreateToken zero-count conventions).
    /// - **Empty library / count > matching lands** stops early
    ///   silently — partial fill is allowed (Python's
    ///   `next(... None)` short-circuit on miss).
    SearchLibraryForBasicLandTapped { count: i32 },
    /// Put `amount` +1/+1 counters on the resolving spell's source
    /// permanent — the "this creature" / "self" target (CR 122.6 +
    /// 701.13). Powers Blade of the Swarm, Atomic Microsizer — 16
    /// cards in the EoE pool per round-20 measurement.
    ///
    /// **"Self" semantics.** The recipient is the source GameObject
    /// at the top of the stack (i.e. the resolving spell's source).
    /// This is distinct from `AddCounters`, which deterministically
    /// picks the DEFENDING player's first creature. Mirrors Python's
    /// `PutPlusOneCounterOnSelf` which reads
    /// `state.resolving_source` during ability resolution.
    ///
    /// **Counter shape.** `amount` is the number of +1/+1 counters
    /// to add; it lands as a positive delta on the round-2 signed
    /// net-counter i32 field via `saturating_add`. Default is 1
    /// (mirrors Python's `amount: int = 1` dataclass default).
    /// Negative `amount` raises at register / resolve time —
    /// "put -N +1/+1 counters on self" isn't a sensible printing.
    ///
    /// **Source-finder dispatch.** Round-23's earlier arms (AddMana
    /// to Pool, SearchLibraryForBasicLandTapped, AddCounters,
    /// DamageEachCreature, etc.) get their target from
    /// `state.active_player` or from the defending player's
    /// battlefield Vec; "self" needs the actual source object. The
    /// resolve loop owns `top.source_obj_id` and threads it into
    /// `apply_effect` so this arm can locate the source across
    /// zones. The other arms ignore it (the param is opaque to
    /// them).
    ///
    /// **Source-not-on-battlefield handling.** Real MTG: if the
    /// source has left the battlefield by the time the counter is
    /// added (e.g. the creature was destroyed in response), the
    /// effect "puts the counter on nothing" / fizzles. First slice
    /// honors that: if the source is not on a battlefield zone, the
    /// counter add is a silent no-op (the source-finder walks both
    /// players' battlefields; sources sitting in hand / library /
    /// graveyard / stack are NOT counter targets). Mirrors Python's
    /// `source is None` short-circuit in the dataclass's `resolve`.
    ///
    /// **amount=0 is a legal no-op** (mirrors GainLife / DrawCards /
    /// Mill / SearchLibraryForBasicLandTapped / CreateToken
    /// zero-amount conventions).
    PutPlusOneCounterOnSelf { amount: i32 },
}

#[derive(Clone, Debug)]
pub struct CardPrinting {
    pub name: Arc<str>,
    pub mana_cost: ManaCost,
    pub effects: Vec<Effect>,
    /// Printed power. `None` for non-creatures (instants, sorceries,
    /// non-creature lands, etc.). Stored as `i16` to leave headroom
    /// for negatives produced by anthem-like effects (the printed
    /// value itself is always non-negative).
    pub power: Option<i16>,
    /// Printed toughness. `None` for non-creatures. Same rationale
    /// as `power` for the `i16` choice.
    pub toughness: Option<i16>,
    /// Mana the printing produces when tapped, expressed as a list
    /// of single-letter color symbols (W/U/B/R/G/C). `None` for
    /// printings that don't produce mana on tap. A single-color
    /// land like Forest stores `Some(vec!["G"])`. Vec-of-strings
    /// (rather than a single String) leaves room for "tap for {G}{G}"
    /// or future multi-pip producers without re-shaping the field.
    /// "Tap for one of any color" / hybrid producers will need a
    /// richer schema and are deferred.
    pub mana_produced: Option<Vec<String>>,
    /// MTG card types: "Creature", "Land", "Instant", "Sorcery",
    /// "Artifact", "Enchantment", "Planeswalker", "Battle". Most
    /// cards have one type; multi-typed cards (artifact creatures,
    /// enchantment creatures) carry multiple. Empty Vec is allowed
    /// for first-slice synthetic test cards but real cards always
    /// have at least one.
    pub card_types: Vec<String>,
    /// Static keyword abilities printed on the card. Stored as
    /// lowercase strings ("flying", "vigilance", "trample",
    /// "first strike", "double strike", "deathtouch", "lifelink",
    /// "haste", "reach", "menace", "defender"). Keywords with
    /// associated values (protection from X, ward N, hexproof
    /// from X) need a richer schema and are deferred. Empty Vec
    /// when the card has no static keywords.
    pub keywords: Vec<String>,
    /// "When ~ enters the battlefield" effects. Fire on any
    /// permanent landing on the battlefield (creature, artifact,
    /// enchantment, planeswalker). Empty Vec = no ETB. First-slice
    /// scope: the effects fire IMMEDIATELY on entry, no separate
    /// stack item — real MTG triggers them onto the stack and
    /// resolves in priority order; that timing nuance is deferred.
    pub etb_effects: Vec<Effect>,
}

/// Plain Rust container for the printings table. Held behind an
/// `Arc` once a `GameState` snapshots the registry — at that point
/// it's immutable and clonable at refcount-bump cost from any
/// number of game-state copies.
#[derive(Clone, Debug, Default)]
pub struct RegistryData {
    pub printings: Vec<CardPrinting>,
}

impl RegistryData {
    pub fn lookup(&self, id: u32) -> Option<&CardPrinting> {
        self.printings.get(id as usize)
    }

    pub fn len(&self) -> usize {
        self.printings.len()
    }
}

// --- dict -> Rust ------------------------------------------------

fn require<'py>(
    dict: &Bound<'py, PyDict>,
    key: &str,
) -> PyResult<Bound<'py, PyAny>> {
    dict.get_item(key)?
        .ok_or_else(|| PyKeyError::new_err(format!("missing required key: {key:?}")))
}

fn parse_mana_cost(dict: &Bound<'_, PyDict>) -> PyResult<ManaCost> {
    let mut cost = ManaCost::default();
    for (key_obj, value_obj) in dict.iter() {
        let key: String = key_obj.extract()?;
        let value: u8 = value_obj.extract().map_err(|e| {
            PyValueError::new_err(format!(
                "mana_cost[{key:?}] must be a non-negative integer (got: {e})"
            ))
        })?;
        match key.as_str() {
            "generic" | "C" => cost.generic = value,
            "W" => cost.white = value,
            "U" => cost.blue = value,
            "B" => cost.black = value,
            "R" => cost.red = value,
            "G" => cost.green = value,
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown mana_cost key {other:?}; valid: generic, W, U, B, R, G"
                )))
            }
        }
    }
    Ok(cost)
}

fn parse_target_filter(dict: &Bound<'_, PyDict>) -> PyResult<TargetFilter> {
    let kind: String = require(dict, "kind")?.extract()?;
    match kind.as_str() {
        "any_player" => Ok(TargetFilter::AnyPlayer),
        "any_creature" => Ok(TargetFilter::AnyCreature),
        other => Err(PyValueError::new_err(format!(
            "unknown target filter kind {other:?}; valid: any_player, any_creature"
        ))),
    }
}

fn parse_effect(dict: &Bound<'_, PyDict>) -> PyResult<Effect> {
    let kind: String = require(dict, "kind")?.extract()?;
    match kind.as_str() {
        "deal_damage" => {
            let amount: i32 = require(dict, "amount")?.extract()?;
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("deal_damage.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::DealDamage { amount, target })
        }
        "draw_cards" => {
            let count: i32 = require(dict, "count")?.extract()?;
            Ok(Effect::DrawCards { count })
        }
        "gain_life" => {
            let amount: i32 = require(dict, "amount")?.extract()?;
            Ok(Effect::GainLife { amount })
        }
        "return_to_hand" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("return_to_hand.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::ReturnToHand { target })
        }
        "mill" => {
            let count: i32 = require(dict, "count")?.extract()?;
            Ok(Effect::Mill { count })
        }
        "exile_target" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("exile_target.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::ExileTarget { target })
        }
        "tap_target" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("tap_target.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::TapTarget { target })
        }
        "untap_target" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("untap_target.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::UntapTarget { target })
        }
        "sacrifice" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("sacrifice.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::Sacrifice { target })
        }
        "add_counters" => {
            let count: i32 = require(dict, "count")?.extract()?;
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("add_counters.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::AddCounters { target, count })
        }
        "discard_card" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("discard_card.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::DiscardCard { target })
        }
        "scry_n" => {
            let count: i32 = require(dict, "count")?.extract()?;
            Ok(Effect::ScryN { count })
        }
        "destroy_target" => {
            let target_any = require(dict, "target")?;
            let target_dict = target_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("destroy_target.target must be a dict")
            })?;
            let target = parse_target_filter(target_dict)?;
            Ok(Effect::DestroyTarget { target })
        }
        "damage_each_opponent" => {
            let amount: i32 = require(dict, "amount")?.extract()?;
            Ok(Effect::DamageEachOpponent { amount })
        }
        "damage_each_creature" => {
            let amount: i32 = require(dict, "amount")?.extract()?;
            Ok(Effect::DamageEachCreature { amount })
        }
        "create_token" => {
            let count: i32 = require(dict, "count")?.extract()?;
            let token_printing_id: u32 = require(dict, "token_printing_id")?.extract()?;
            Ok(Effect::CreateToken { count, token_printing_id })
        }
        "add_mana_to_pool" => {
            let color: String = require(dict, "color")?.extract()?;
            // Validate against the closed mana-color vocab. Shared
            // helper with `parse_mana_produced` — reject "X", "g"
            // (lowercase), "WG" (compound), etc. at register time.
            validate_mana_symbol(&color)?;
            let amount: i32 = require(dict, "amount")?.extract()?;
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "add_mana_to_pool: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::AddManaToPool { color, amount })
        }
        "search_library_for_basic_land_tapped" => {
            // Python's `SearchLibraryForBasicLandTapped(count: int = 1)`
            // has a count field with default 1. Mirror that here:
            // missing `count` defaults to 1, present `count` extracts
            // as i32. Negative counts surface at register time
            // (defense-in-depth; `apply_effect` re-checks).
            let count: i32 = match dict.get_item("count")? {
                Some(c) => c.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "search_library_for_basic_land_tapped.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "search_library_for_basic_land_tapped: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::SearchLibraryForBasicLandTapped { count })
        }
        "put_plus_one_counter_on_self" => {
            // Python's `PutPlusOneCounterOnSelf(amount: int = 1)` has
            // an `amount` field defaulting to 1. Mirror that here:
            // missing `amount` defaults to 1, present `amount`
            // extracts as i32. Negative `amount` surfaces at register
            // time (defense-in-depth; `apply_effect` re-checks).
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_plus_one_counter_on_self.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "put_plus_one_counter_on_self: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::PutPlusOneCounterOnSelf { amount })
        }
        other => Err(PyValueError::new_err(format!(
            "unknown effect kind {other:?}; valid: deal_damage, draw_cards, gain_life, return_to_hand, mill, exile_target, tap_target, untap_target, sacrifice, add_counters, discard_card, scry_n, destroy_target, damage_each_opponent, damage_each_creature, create_token, add_mana_to_pool, search_library_for_basic_land_tapped, put_plus_one_counter_on_self"
        ))),
    }
}

/// Validate that a string is one of the closed mana-color vocab
/// (W/U/B/R/G/C). Returns the input on success; raises ValueError
/// otherwise. Shared by `parse_mana_produced` and is callable from
/// the `mana_produced` field validator.
fn validate_mana_symbol(sym: &str) -> PyResult<()> {
    match sym {
        "W" | "U" | "B" | "R" | "G" | "C" => Ok(()),
        other => Err(PyValueError::new_err(format!(
            "unknown mana symbol {other:?} in mana_produced; valid: W, U, B, R, G, C"
        ))),
    }
}

fn parse_mana_produced(any: Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    let mut out: Vec<String> = Vec::new();
    for item in any.try_iter().map_err(|_| {
        PyValueError::new_err("mana_produced must be an iterable of color strings")
    })? {
        let item = item?;
        let s: String = item.extract().map_err(|_| {
            PyValueError::new_err("mana_produced entries must be strings")
        })?;
        validate_mana_symbol(&s)?;
        out.push(s);
    }
    Ok(out)
}

pub fn parse_printing(dict: &Bound<'_, PyDict>) -> PyResult<CardPrinting> {
    let name: String = require(dict, "name")?.extract()?;
    let mana_cost = match dict.get_item("mana_cost")? {
        Some(mc_any) => {
            let mc_dict = mc_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("mana_cost must be a dict")
            })?;
            parse_mana_cost(mc_dict)?
        }
        None => ManaCost::default(),
    };
    let effects = match dict.get_item("effects")? {
        Some(eff_any) => {
            let mut out = Vec::new();
            for item in eff_any.try_iter()? {
                let item = item?;
                let eff_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err("each effect must be a dict")
                })?;
                out.push(parse_effect(eff_dict)?);
            }
            out
        }
        None => Vec::new(),
    };
    let power = match dict.get_item("power")? {
        Some(p) => Some(p.extract::<i16>().map_err(|e| {
            PyValueError::new_err(format!(
                "power must be an integer (got: {e})"
            ))
        })?),
        None => None,
    };
    let toughness = match dict.get_item("toughness")? {
        Some(t) => Some(t.extract::<i16>().map_err(|e| {
            PyValueError::new_err(format!(
                "toughness must be an integer (got: {e})"
            ))
        })?),
        None => None,
    };
    let mana_produced = match dict.get_item("mana_produced")? {
        Some(mp_any) => Some(parse_mana_produced(mp_any)?),
        None => None,
    };
    let card_types = match dict.get_item("card_types")? {
        Some(ct_any) => {
            let iter = ct_any.try_iter().map_err(|_| {
                PyValueError::new_err("card_types must be an iterable of type strings")
            })?;
            let mut out = Vec::new();
            for item in iter {
                let s: String = item?.extract().map_err(|_| {
                    PyValueError::new_err("card_types entries must be strings")
                })?;
                out.push(s);
            }
            out
        }
        None => Vec::new(),
    };
    let keywords = match dict.get_item("keywords")? {
        Some(kw_any) => {
            let iter = kw_any.try_iter().map_err(|_| {
                PyValueError::new_err("keywords must be an iterable of keyword strings")
            })?;
            let mut out = Vec::new();
            for item in iter {
                let s: String = item?.extract().map_err(|_| {
                    PyValueError::new_err("keywords entries must be strings")
                })?;
                out.push(s.to_lowercase());
            }
            out
        }
        None => Vec::new(),
    };
    let etb_effects = match dict.get_item("etb_effects")? {
        Some(eff_any) => {
            let mut out = Vec::new();
            for item in eff_any.try_iter()? {
                let item = item?;
                let eff_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err("each etb_effect must be a dict")
                })?;
                out.push(parse_effect(eff_dict)?);
            }
            out
        }
        None => Vec::new(),
    };
    Ok(CardPrinting {
        name: Arc::from(name),
        mana_cost,
        effects,
        power,
        toughness,
        mana_produced,
        card_types,
        keywords,
        etb_effects,
    })
}

// --- Rust -> dict (round-trip) -----------------------------------

fn mana_cost_to_pydict<'py>(
    py: Python<'py>,
    cost: &ManaCost,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    if cost.generic > 0 {
        d.set_item("generic", cost.generic)?;
    }
    if cost.white > 0 {
        d.set_item("W", cost.white)?;
    }
    if cost.blue > 0 {
        d.set_item("U", cost.blue)?;
    }
    if cost.black > 0 {
        d.set_item("B", cost.black)?;
    }
    if cost.red > 0 {
        d.set_item("R", cost.red)?;
    }
    if cost.green > 0 {
        d.set_item("G", cost.green)?;
    }
    Ok(d)
}

fn target_filter_to_pydict<'py>(
    py: Python<'py>,
    target: &TargetFilter,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match target {
        TargetFilter::AnyPlayer => d.set_item("kind", "any_player")?,
        TargetFilter::AnyCreature => d.set_item("kind", "any_creature")?,
    }
    Ok(d)
}

fn effect_to_pydict<'py>(
    py: Python<'py>,
    effect: &Effect,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match effect {
        Effect::DealDamage { amount, target } => {
            d.set_item("kind", "deal_damage")?;
            d.set_item("amount", *amount)?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::DrawCards { count } => {
            d.set_item("kind", "draw_cards")?;
            d.set_item("count", *count)?;
        }
        Effect::GainLife { amount } => {
            d.set_item("kind", "gain_life")?;
            d.set_item("amount", *amount)?;
        }
        Effect::ReturnToHand { target } => {
            d.set_item("kind", "return_to_hand")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::Mill { count } => {
            d.set_item("kind", "mill")?;
            d.set_item("count", *count)?;
        }
        Effect::ExileTarget { target } => {
            d.set_item("kind", "exile_target")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::TapTarget { target } => {
            d.set_item("kind", "tap_target")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::UntapTarget { target } => {
            d.set_item("kind", "untap_target")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::Sacrifice { target } => {
            d.set_item("kind", "sacrifice")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::AddCounters { target, count } => {
            d.set_item("kind", "add_counters")?;
            d.set_item("count", *count)?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::DiscardCard { target } => {
            d.set_item("kind", "discard_card")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::ScryN { count } => {
            d.set_item("kind", "scry_n")?;
            d.set_item("count", *count)?;
        }
        Effect::DestroyTarget { target } => {
            d.set_item("kind", "destroy_target")?;
            d.set_item("target", target_filter_to_pydict(py, target)?)?;
        }
        Effect::DamageEachOpponent { amount } => {
            d.set_item("kind", "damage_each_opponent")?;
            d.set_item("amount", *amount)?;
        }
        Effect::DamageEachCreature { amount } => {
            d.set_item("kind", "damage_each_creature")?;
            d.set_item("amount", *amount)?;
        }
        Effect::CreateToken { count, token_printing_id } => {
            d.set_item("kind", "create_token")?;
            d.set_item("count", *count)?;
            d.set_item("token_printing_id", *token_printing_id)?;
        }
        Effect::AddManaToPool { color, amount } => {
            d.set_item("kind", "add_mana_to_pool")?;
            d.set_item("color", color)?;
            d.set_item("amount", *amount)?;
        }
        Effect::SearchLibraryForBasicLandTapped { count } => {
            d.set_item("kind", "search_library_for_basic_land_tapped")?;
            d.set_item("count", *count)?;
        }
        Effect::PutPlusOneCounterOnSelf { amount } => {
            d.set_item("kind", "put_plus_one_counter_on_self")?;
            d.set_item("amount", *amount)?;
        }
    }
    Ok(d)
}

// --- Registry pyclass --------------------------------------------

#[pyclass(name = "Registry")]
#[derive(Debug, Default)]
pub struct Registry {
    /// Builder-side Vec. `register_printing` appends here. A
    /// `snapshot()` call freezes a clone of this Vec into an
    /// `Arc<RegistryData>` that GameStates share. Keeping the
    /// builder separate from the snapshot avoids interior
    /// mutability (Mutex/RwLock) on the snapshot path —
    /// first-slice workflow is "build, snapshot once, never
    /// mutate again", which is what synthetic states do today.
    printings: Vec<CardPrinting>,
}

#[pymethods]
impl Registry {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    /// Register a card printing from a Python dict; returns its
    /// stable u32 id. Unknown `kind` values, missing required keys,
    /// and type mismatches raise rather than silently no-op.
    fn register_printing(&mut self, dict: &Bound<'_, PyDict>) -> PyResult<u32> {
        let printing = parse_printing(dict)?;
        let id = self.printings.len() as u32;
        self.printings.push(printing);
        Ok(id)
    }

    fn __len__(&self) -> usize {
        self.printings.len()
    }

    fn get_printing_name(&self, id: u32) -> PyResult<String> {
        let p = self.lookup(id)?;
        Ok(p.name.to_string())
    }

    fn get_printing_mana_cost<'py>(
        &self,
        py: Python<'py>,
        id: u32,
    ) -> PyResult<Bound<'py, PyDict>> {
        let p = self.lookup(id)?;
        mana_cost_to_pydict(py, &p.mana_cost)
    }

    fn get_printing_effects<'py>(
        &self,
        py: Python<'py>,
        id: u32,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let p = self.lookup(id)?;
        p.effects
            .iter()
            .map(|e| effect_to_pydict(py, e))
            .collect()
    }

    /// Printed power for a creature printing; `None` for non-creatures.
    fn get_printing_power(&self, id: u32) -> PyResult<Option<i16>> {
        Ok(self.lookup(id)?.power)
    }

    /// Printed toughness for a creature printing; `None` for non-creatures.
    fn get_printing_toughness(&self, id: u32) -> PyResult<Option<i16>> {
        Ok(self.lookup(id)?.toughness)
    }

    /// Mana symbols this printing produces when tapped, or `None`
    /// when the printing has no mana-production behavior. A
    /// single-color land like Forest returns `Some(["G"])`.
    fn get_printing_mana_produced(&self, id: u32) -> PyResult<Option<Vec<String>>> {
        Ok(self.lookup(id)?.mana_produced.clone())
    }

    /// MTG card types: "Creature", "Land", "Instant", etc.
    fn get_printing_card_types(&self, id: u32) -> PyResult<Vec<String>> {
        Ok(self.lookup(id)?.card_types.clone())
    }

    /// Static printed keywords (lowercase): "flying", "vigilance",
    /// "trample", etc.
    fn get_printing_keywords(&self, id: u32) -> PyResult<Vec<String>> {
        Ok(self.lookup(id)?.keywords.clone())
    }

    /// "When ~ enters the battlefield" effects (round-9 bridge ext).
    fn get_printing_etb_effects<'py>(
        &self,
        py: Python<'py>,
        id: u32,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let p = self.lookup(id)?;
        p.etb_effects.iter().map(|e| effect_to_pydict(py, e)).collect()
    }

    /// Microbench helper: round-trip ``n`` copies of the same dict
    /// through the parser. Returns mean per-call microseconds.
    fn register_n_times_micros(
        &mut self,
        dict: &Bound<'_, PyDict>,
        n: usize,
    ) -> PyResult<f64> {
        let start = Instant::now();
        for _ in 0..n {
            let printing = parse_printing(dict)?;
            std::hint::black_box(printing);
        }
        let elapsed = start.elapsed();
        Ok((elapsed.as_secs_f64() * 1_000_000.0) / n as f64)
    }
}

impl Registry {
    fn lookup(&self, id: u32) -> PyResult<&CardPrinting> {
        self.printings.get(id as usize).ok_or_else(|| {
            PyKeyError::new_err(format!(
                "no printing with id {id} (registry has {})",
                self.printings.len()
            ))
        })
    }

    /// Freeze the current builder Vec into an `Arc<RegistryData>`
    /// suitable for sharing into a `GameState`. Used by
    /// `make_synthetic_state` and (later) by Python code that
    /// builds a game state from a finalized registry.
    pub fn snapshot(&self) -> Arc<RegistryData> {
        Arc::new(RegistryData {
            printings: self.printings.clone(),
        })
    }

    /// Push a `CardPrinting` directly (used by `make_synthetic_state`
    /// to seed an in-process registry without the dict round-trip).
    /// Returns the new printing's id.
    pub fn push_printing(&mut self, printing: CardPrinting) -> u32 {
        let id = self.printings.len() as u32;
        self.printings.push(printing);
        id
    }
}
