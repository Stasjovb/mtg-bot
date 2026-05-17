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
    /// Target player puts the top `count` cards of their library into
    /// their graveyard (CR 701.13b "mill"). 2 cards in EoE pool per
    /// round-20 measurement (Scrabbling Skullcrab etc.).
    ///
    /// **Distinct from `Effect::Mill`** — that arm mills the
    /// CONTROLLER's library. `MillTargetPlayer` mills a chosen target
    /// player (in 2-player engine = defender). First-slice
    /// deterministic choice: defender (= 1 - controller). Future
    /// multiplayer / archenemy work needs an explicit choice callback.
    ///
    /// Negative `count` raises. count=0 is a legal no-op. If the
    /// library has fewer than `count` cards, all remaining cards mill
    /// (Python parity).
    MillTargetPlayer { count: i32 },
    /// **BLOCKED-RUST-EFFECT slice (round 42) -- mill an opponent
    /// player a number of cards equal to the source-controller's
    /// current life total.** Mirrors Python's
    /// `MillTargetPlayer(use_controller_life=True)` (Space-Time
    /// Anomaly, EoE; `effects/generic/draw_mill.py:151`). Sister of
    /// rounds 32 / 35 / 36 / 37 (damage substrate, four denominators:
    /// artifact-count / hand-size / lands-controlled / creatures-you-
    /// control), round 33 (counters-on-self substrate, one denominator
    /// so far), and round 34 (surveil substrate, one denominator so
    /// far) — same dynamic-X-from-count plumbing, NEW apply substrate
    /// (mill-target-player in place of damage / counters / surveil)
    /// AND NEW denominator axis (source-controller life total, vs the
    /// four bf-permanent-count denominators and hand-size denominator
    /// already shipped). Establishes the FIFTH denominator and the
    /// FOURTH apply substrate on the X-from-count plumbing,
    /// confirming bidirectional extensibility across substrate AND
    /// denominator axes.
    ///
    /// **Mechanism — count + apply.** At resolve time, resolve the
    /// source's controller (5-zone walk + stack scan; mirrors
    /// round-32 / 35 / 36 / 37 sister source-controller resolution
    /// pattern). Read `state.players[controller].life`; clamp to a
    /// non-negative count via `max(0, life)` (a negative life total
    /// — e.g. arbitrary loss-of-life past zero — produces a
    /// zero-count silent no-op, matching Python's
    /// `max(0, state.player_by_id(controller_id).life)` clamp at
    /// `draw_mill.py:187`). Mill that many cards from the opponent's
    /// library top (= `1 - controller` per round-32 / 35 / 36 / 37
    /// sister target shape; first-slice deterministic single-opponent
    /// pick). If the opponent's library is empty mid-mill, stop early
    /// (matches Python's `if not target.library: break` shape and
    /// mirrors the round-19 MillTargetPlayer arm's
    /// `n_to_mill = min(count, lib.len())` clamp).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 / 35 / 36 / 37 sister shape — needs to
    /// resolve even if source has left bf, e.g. counterspelled
    /// trigger that still drives the count from the original ETB
    /// snapshot). If untrackable -> silent fizzle.
    ///
    /// **Target semantics — first-slice deterministic.** Pick
    /// `1 - controller` on a 2-player engine (mirrors the round-19
    /// MillTargetPlayer arm's deterministic `target_idx = 1 -
    /// controller` shape post-I77 controller-of-effect fix). Future
    /// multiplayer fanout needs an explicit target-player choice
    /// callback (mirrors round-19's deferred-multiplayer note).
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `MillTargetPlayer` carries an
    /// `amount: int = 1` AND a `use_controller_life: bool = False`
    /// flag; this Rust arm is the dedicated dynamic-X sister to the
    /// existing `MillTargetPlayer { count: i32 }` arm, matching the
    /// sister-variant precedent established by rounds 32 / 35 / 36 /
    /// 37 (damage substrate splits the static-amount sister
    /// `DealDamageToOpponentCreature { amount }` from the
    /// dynamic-X-from-count sisters). The Python bridge translates
    /// this Rust unit variant to
    /// `MillTargetPlayer(use_controller_life=True)` (the existing
    /// Python class's flag lane) — no new Python class needed
    /// because the flag-on-existing-class shape already exists and is
    /// tested; only the Rust substrate and the bridge arm are new.
    /// Mirrors round-30 / 31 / 32 / 33 / 34 / 35 / 36 / 37
    /// unit-variant schema convention.
    MillTargetPlayerEqualToYourLifeTotal,
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
    /// **BLOCKED-RUST-EFFECT slice — Faller's Faithful ETB
    /// (~14,108 17lands decks).** "When this creature enters, destroy
    /// up to one OTHER target creature. If that creature wasn't dealt
    /// damage this turn, its controller draws `draw_amount` cards."
    ///
    /// Structural sibling of `DestroyTarget { AnyCreature }`: same
    /// source-controller resolution (`current_resolve_source_controller`
    /// with active-player fallback), same `defender = 1 - controller`
    /// bf[0] first-slice deterministic target pick, same
    /// indestructible-suppress gate (CR 702.12), same LTB fan-out
    /// (`pending_leaves_dispatches.push` + `queue_token_cease`). Adds
    /// the Faller's-Faithful draw rider: BEFORE the destroy mutates
    /// anything, snapshot whether the chosen creature carries marked
    /// damage (`obj.damage == 0` → "wasn't dealt damage"); record the
    /// victim's controller; AFTER the destroy, if the snapshot said
    /// undamaged, the victim's controller draws `draw_amount` cards
    /// (CR 121.1 — the destroyed creature's controller, per the
    /// printed text). The "other target" / `exclude_self` shape is
    /// already enforced by the defender-bf scan (the source ETBs on
    /// the controller's bf; the defender scan never sees it).
    ///
    /// **Effect-half / damage-ledger split (see SEARCH_LIMITATIONS.md).**
    /// Python maintains a per-object `damaged_this_turn` boolean
    /// (`effects/base.py:300`, cleared on zone moves) that survives a
    /// heal-to-0; Rust carries only `obj.damage` (marked damage,
    /// cleared at cleanup). For the realistic Faller's Faithful ETB
    /// (instant-speed destroy with no prior damage marked on the
    /// target this turn) the two reads are byte-equal: a creature with
    /// no marked damage `obj.damage == 0` ⇔ Python's
    /// `not obj.damaged_this_turn`. The asymmetric corner —
    /// damaged-then-healed-to-0 within the same turn — is NOT modeled
    /// on the Rust side; the full general damaged-this-turn ledger is
    /// the loader-gated subsystem half (the card is NOT admitted to
    /// the production-deck loader allowlist). Mirrors Python's
    /// `DestroyTargetCreature(draw_if_undamaged_amount=draw_amount,
    /// optional=True, exclude_self=True)`
    /// (`effects/generic/destroy.py:94`).
    ///
    /// **Empty defender bf = silent fizzle** (the "up to one"
    /// optional shape collapses to a no-op when no legal target — CR
    /// 608.2c — and the draw rider does not run).
    DestroyTargetCreatureThenDrawIfUndamaged { draw_amount: i32 },
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
    /// **BLOCKED-RUST-EFFECT slice (round 43) -- each living player
    /// creates `count` token creatures under their own control.**
    /// Sister of the static `CreateToken { count, token_printing_id }`
    /// arm above; the only behavioral difference is the recipient set
    /// (every living player, each under their own control, vs the
    /// source-controller alone). Mirrors Python's
    /// `CreateToken(token_printing=..., count=N, each_player=True)`
    /// (`effects/generic/tokens.py:198,210` — when `each_player=True`,
    /// `recipients = [p.id for p in state.players if not p.has_lost]`).
    ///
    /// EoE consumer: Edge Rover (Artifact Creature -- Robot Scout,
    /// "When this creature dies, each player creates a Lander
    /// token."). This is the FIRST each-player token shape in the
    /// audit's BLOCKED-RUST-EFFECT residue, and a precondition for
    /// the broader "each player creates X" family if future EoE
    /// expansions (or other set work) prints sister cards.
    ///
    /// **Mechanism -- recipient fanout.** Iterate over
    /// `0..state.players.len()`, skip any player with `has_lost ==
    /// true` (CR 102.5 living-players-only convention; mirrors
    /// Python's `if not p.has_lost` guard at tokens.py:212). For each
    /// living recipient, push `count` fresh tokens onto THEIR
    /// battlefield (NOT the source-controller's), tagged with
    /// `controller = recipient`. Each recipient gets the SAME static
    /// `count`. Tokens enter summoning-sick like every other ETB
    /// (mirrors the sister `CreateToken` arm's summoning_sick=true).
    ///
    /// **Schema parity with Python.** Mirrors the sister
    /// `CreateToken` arm's two-field schema; adds NO new field
    /// because the `each_player` boolean is encoded by variant name
    /// (closed-vocab convention -- bool fields are second-class in
    /// the bridge, every other binary choice lives in a separate
    /// variant). Python's `each_player=True` is the same shape
    /// (per-instance bool on the existing dataclass), but the bridge
    /// MAPS to a distinct dict `kind` for round-trip clarity.
    ///
    /// **Negative `count` raises** loudly (mirrors the sister
    /// `CreateToken` arm). `count == 0` is a legal no-op.
    /// **Unknown `token_printing_id` raises** at resolve time before
    /// any state mutation (mirrors the sister arm's whole-or-nothing
    /// validation contract -- one invalid registry id should not
    /// half-fanout some recipients before erroring).
    ///
    /// **First-slice scope (parity with the sister arm).**
    /// CR 614 token-creation replacement effects (Anointed Procession
    /// doubling, Moonlit-Meditation copy-replacement, Exalted Sunborn
    /// counter-stamping) and the `tapped` / `attacking` /
    /// `schedule_end_of_combat_sacrifice` flag bundle are NOT
    /// plumbed in this Rust arm -- the EoE consumer (Edge Rover ->
    /// Lander) doesn't engage any of those riders, and the sister
    /// `CreateToken` arm's first-slice docs explicitly defer the
    /// same surface for the same reason. Those richer surfaces
    /// still resolve through the Python path.
    ///
    /// **Each-player ENTERS dispatch.** Mirrors the sister
    /// `CreateToken` arm's `pending_etb_dispatches.extend(token_ids)`
    /// shape: every fresh token id is queued for ENTERS event
    /// dispatch by the surrounding resolver, regardless of which
    /// player it ended up under. The CE4 etb_timestamp stamping
    /// preserves a strict per-token monotonic order across all
    /// recipients combined (recipient iteration order =
    /// `state.players` index order = controller id order, mirroring
    /// Python's `for p in state.players` natural order).
    CreateTokenEachPlayer { count: i32, token_printing_id: u32 },
    /// **Phase 6 token-printing substrate -- Phase 4 (round 50): the
    /// `tapped` create-token rider.** Sister of the static
    /// `CreateToken { count, token_printing_id }` arm; the ONLY
    /// behavioral difference is that every fresh token enters the
    /// battlefield TAPPED (CR 701.6 + the "create a tapped ~" oracle
    /// rider). Mirrors Python's
    /// `CreateToken(token_printing=..., count=N, tapped=True)`
    /// (`effects/generic/tokens.py:286-287` -- the `if self.tapped:
    /// obj.tapped = True` branch).
    ///
    /// **EoE consumer: Gravpack Monoist** (Creature -- Robot, flying;
    /// "When this creature dies, create a tapped 2/2 Robot token.").
    /// 25,252 of the 129,996 17lands EoE decks run it -- the single
    /// highest real-card-coverage lever in the token-printing
    /// substrate after Phase 1 (its Robot token is already vanilla, so
    /// Phase 4 needs no Phase-3 Lander-activated-ability work). Round
    /// 49's `tapped=True` rider was DECLINED by the Phase-1 recognizer
    /// (`docs/TOKEN_PRINTING_SUBSTRATE.md` §2.3) precisely because the
    /// bare `CreateToken` variant has no `tapped` mirror -- this
    /// variant closes that decline.
    ///
    /// **Schema parity with Python -- sister-variant convention.**
    /// Mirrors the sister `CreateToken` / `CreateTokenEachPlayer`
    /// two-field schema (`count: i32`, `token_printing_id: u32`); adds
    /// NO new field because the `tapped` boolean is encoded by variant
    /// name (closed-vocab convention -- bool fields are second-class
    /// in the bridge, every binary choice rides on a separate variant;
    /// round-19/30/31/.. / round-43 `CreateTokenEachPlayer`
    /// precedent). Python's `tapped=True` is a per-instance bool on
    /// the existing dataclass, but the bridge MAPS it to a distinct
    /// dict `kind` (`create_token_tapped`) for round-trip clarity.
    ///
    /// **Negative `count` raises** loudly (mirrors the sister
    /// `CreateToken` arm). `count == 0` is a legal no-op. **Unknown
    /// `token_printing_id` raises** at resolve time before any state
    /// mutation (mirrors the sister arm's whole-or-nothing validation
    /// contract).
    ///
    /// **First-slice scope (parity with the sister arm).** CR 614
    /// token-creation replacement effects (Anointed Procession
    /// doubling, ...) and the `each_player` / `attacking` /
    /// `schedule_end_of_combat_sacrifice` riders are NOT plumbed here
    /// -- the EoE consumer (Gravpack Monoist -> a single tapped Robot
    /// on its own controller's battlefield) engages NONE of them, and
    /// the sister arms defer the same surface for the same reason.
    /// Those richer surfaces still resolve through the Python path.
    ///
    /// **ENTERS dispatch.** Mirrors the sister `CreateToken` arm's
    /// `pending_etb_dispatches.extend(token_ids)` shape: every fresh
    /// token id is queued for ENTERS event dispatch by the
    /// surrounding resolver. The CE4 etb_timestamp stamping preserves
    /// a strict per-token monotonic order. The token enters TAPPED but
    /// is otherwise identical to the sister arm's token (same
    /// summoning-sick=true, controller-of-effect resolution, fresh-id
    /// allocator).
    CreateTokenTapped { count: i32, token_printing_id: u32 },
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
    /// Surveil N (CR 701.42 / equivalent): controller looks at the top
    /// `count` cards of their library, then chooses any number to put
    /// into their graveyard. The rest stay on top of the library in
    /// any order. Powers Appendage Amalgam, etc. — 16 cards in the EoE
    /// pool per round-20 measurement. Sibling of ScryN (round 16) —
    /// same shape, different destination zone (graveyard not bottom).
    ///
    /// First-slice deterministic choice: put NONE into the graveyard;
    /// keep all `count` cards on top in their current order. This is
    /// the safest deterministic default (mirrors ScryN's "keep all on
    /// top" first-slice choice from round 16). Future slice plumbs a
    /// real "which to graveyard" decision callback through. Negative
    /// count raises.
    Surveil { count: i32 },
    /// Counter target spell on the stack (CR 701.5). Powers Annul,
    /// Cancel, etc. — 7 cards in the EoE pool per round-20 measurement.
    ///
    /// **Python schema simplification.** Python's `CounterTargetSpell`
    /// dataclass carries a `filter_types: frozenset[str] = frozenset()`
    /// field — an empty set means "any spell", non-empty restricts what
    /// card types are legal targets (e.g. `frozenset({"Artifact",
    /// "Enchantment"})` for Annul). The Rust first slice does NOT
    /// carry that field — assumes target is "any spell". Refined-target
    /// variants (counter creature spell only, counter non-creature,
    /// etc.) wait for richer target plumbing on the Rust side, the
    /// same deferral shape as TargetFilter for the rest of the variant
    /// family.
    ///
    /// **First-slice deterministic choice: pick the TOP stack item
    /// that isn't this Effect's own source.** Mirrors the "first-
    /// eligible" convention from existing Effect arms (DealDamage
    /// picks defender's battlefield[0], AddCounters likewise). The
    /// self-exclusion guard uses the round-23 `source_obj_id`
    /// parameter threaded through `apply_effect`: a counter-spell
    /// resolving on the stack shouldn't counter itself before it
    /// resolves. If the stack is empty (or only contains self), the
    /// effect fizzles silently — Python parity with the
    /// `if not targets: return` short-circuit in
    /// `CounterTargetSpell.resolve`.
    ///
    /// **Composition with round-7 counter_spell primitive.** The
    /// round-7 `state_ops_counterspell.rs::counter_spell(target_obj_id)`
    /// primitive removes the target from the stack and moves its
    /// source to the controller's graveyard (CR 701.6). Per the
    /// per-slice file-isolation pattern + the E0624 cross-file
    /// `#[pymethods]` friction, this arm inlines the equivalent
    /// logic rather than calling through to the primitive: find the
    /// stack item by source_obj_id, remove it, find the source
    /// GameObject in any tracked zone, move it to the stack item
    /// controller's graveyard. A follow-up consolidation slice can
    /// collapse onto the shared primitive once cross-file private-fn
    /// calls re-open.
    ///
    /// **No "can't be countered" enforcement.** Python's
    /// `_is_uncounterable` checks `spell_is_uncounterable` on the
    /// printing and `grants_creature_spells_uncounterable` on
    /// battlefield static abilities. The Rust bridge has neither
    /// flag today — deferred along with the rest of the
    /// `cant_be_countered` shape (mirrors the round-7 counter_spell
    /// primitive's same deferral).
    CounterTargetSpell,
    /// Return a creature card from your graveyard to the battlefield
    /// (CR 400.7 + 302.1 — reanimation). Powers Emerge from the Cocoon,
    /// Reanimate-style sugar, etc. — 8 cards in the EoE pool per
    /// round-20 measurement.
    ///
    /// **First-slice deterministic target choice.** The recipient is
    /// the FIRST creature card encountered scanning the controller's
    /// (= `state.active_player`'s, by first-slice convention) graveyard
    /// in zone-iteration order (front = oldest, smallest Vec index).
    /// "Creature card" = the printing's `card_types` contains
    /// "Creature". Real MTG lets the player choose any creature card
    /// in the graveyard as the target; richer target plumbing is a
    /// future slice once decision callbacks exist.
    ///
    /// **Python schema simplification.** Python's
    /// `ReturnCreatureFromYourGraveyardToBattlefield` extends the
    /// unified `ReturnFromGraveyard` dataclass which carries a number
    /// of optional widening / capping fields (`or_enchantment`,
    /// `or_spacecraft`, `or_artifact`, `max_mv`, `max_n`, etc.). The
    /// Rust first slice carries NONE of these — the variant is a unit
    /// shape ("first creature card in your graveyard"). Refined-target
    /// variants ("creature with mana value <= N", "creature or
    /// enchantment", multi-pick) wait for richer target plumbing on
    /// the Rust side, same deferral shape as TargetFilter / filter_types.
    ///
    /// **Empty / no-creature graveyard: silent fizzle.** Mirrors the
    /// `if not targets: return` short-circuit shape every other
    /// graveyard-walk arm uses (and the round-17
    /// `move_object_from_graveyard_to_battlefield` primitive's
    /// `Ok(false)` return on absent obj_id).
    ///
    /// **Composition with round-17 primitive.** The round-17
    /// `state_ops_zones.rs::move_object_from_graveyard_to_battlefield(
    /// player_id, obj_id)` primitive does exactly the recipient-side
    /// work this Effect needs (remove from graveyard, push onto
    /// battlefield with summoning_sick=true + per-object state reset
    /// per CR 400.7). Routing through it would require
    /// cross-`#[pymethods]` plumbing inside `apply_effect` where we
    /// already hold `state: &mut GameState` — the same E0624 friction
    /// every other Effect arm hit. Per the recurring per-slice
    /// file-isolation pattern (DealDamage / ReturnToHand / Mill /
    /// DrawCards / ExileTarget / Sacrifice / DestroyTarget / TapTarget
    /// / UntapTarget / AddCounters / DiscardCard / CreateToken /
    /// AddManaToPool / SearchLibraryForBasicLandTapped /
    /// PutPlusOneCounterOnSelf / CounterTargetSpell all inline their
    /// primitives for the same reason), this arm inlines the
    /// equivalent logic. A follow-up consolidation slice can collapse
    /// onto the shared primitive once cross-file private-fn calls
    /// re-open.
    ReturnCreatureFromYourGraveyardToBattlefield,
    /// **Phase 5 rider-widened return-to-battlefield (Option B —
    /// additive bespoke arm).** Return the first creature OR
    /// enchantment card from the source-controller's graveyard to
    /// that player's battlefield. Mirrors Python's
    /// `ReturnCreatureFromYourGraveyardToBattlefield(or_enchantment=True)`
    /// (`graveyard.py:361`) — the rider widens the legal-target
    /// pool to admit enchantment cards alongside creatures, and the
    /// destination is the BATTLEFIELD (vs the to-hand sibling which
    /// pushes to hand).
    ///
    /// **EoE consumer (audit).** Rescue Skiff (EoE): "When this
    /// Spacecraft enters, return target creature or enchantment
    /// card from your graveyard to the battlefield." Unlike the
    /// to-hand sibling arm (where Rescue Skiff does NOT consume),
    /// THIS arm is the direct unblocker for Rescue Skiff itself.
    ///
    /// **Filter contract.** A graveyard card qualifies iff its
    /// printing's `card_types` contains "Creature" OR "Enchantment".
    /// (CR 400 / 506 — type predicates read off the printing's
    /// static card_types; the Rust registry stores card_types as
    /// the Scryfall type-line components on the LHS of the em-dash.)
    /// Sister enchantment-creatures (printings carrying BOTH
    /// "Enchantment" AND "Creature") match the disjunction at the
    /// first hit and are pulled. Cards with neither type are
    /// skipped. The scan preserves the unit-variant's iterator
    /// order (`state.players[controller_idx].graveyard.iter().find_map`),
    /// so test predictability matches the existing arms exactly.
    ///
    /// **Controller-of-effect.** Inherits the I83 contract (same
    /// pattern as the bare to-bf unit variant): `controller_idx`
    /// derives from `current_resolve_source_controller`, falling
    /// back to `active_player` for direct `apply_effect_pub`
    /// callers. The graveyard scan, the destination battlefield
    /// push, AND the GameObject.controller stamp on the
    /// reanimated permanent all anchor to the source's controller —
    /// cross-controller routing (p1's ETB resolving on p0's turn)
    /// Just Works.
    ///
    /// **Zone-change reset (CR 400.7) + summoning sickness (CR 302.1).**
    /// Same as the bare to-bf unit variant: `tapped`,
    /// `summoning_sick=true`, `damage`, `counters`, `attached_to`,
    /// `exiled_with_source`, `loyalty_counters` all reset on the
    /// move to battlefield. A fresh `etb_timestamp` is reserved
    /// before the player-mut borrow (CE4 closure). The reanimated
    /// permanent fires its ENTERS triggers via the deferred-
    /// dispatch queue (`pending_etb_dispatches.push(entered_id)`)
    /// regardless of recipient bf, mirroring the unit variant.
    /// Walker-shape printings reseed `loyalty_counters` to the
    /// printed `starting_loyalty` (CE20 Slice 5).
    ///
    /// **Schema simplification vs Python.** Drops `max_mv` and the
    /// other rider flags (`or_artifact`, `or_spacecraft`,
    /// untargeted_all, plus_one_counter, log_suffix). Bare
    /// `or_enchantment` only — Rescue Skiff carries no max_mv cap
    /// or +1/+1-counter rider on the printed text, so the bare
    /// rider arm is sufficient for the unique EoE consumer.
    ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield,
    /// "You discard a card" (CR 701.8). The SOURCE's controller
    /// discards `amount` cards from their hand. Punisher / drawback
    /// shape (Irreverent Gremlin pattern) — 8 cards in the EoE pool
    /// per round-20 measurement.
    ///
    /// **Distinct from `DiscardCard { target: AnyPlayer }`.**
    /// `DiscardCard` deterministically targets the DEFENDING player
    /// (Mind Rot / Wrench Mind shape — the active player forces the
    /// opponent to discard). `DiscardSelf` is the SOURCE's own
    /// controller — the punisher fires on whoever cast / controls
    /// the source, regardless of active_player.
    ///
    /// **Source-finder dispatch (round-23 pattern).** Locates the
    /// source by `source_obj_id` threaded through `apply_effect`.
    /// The scan walks both players' hand / library / battlefield /
    /// graveyard / exile zones to find the source's `controller`
    /// (this is how DiscardSelf differs from
    /// `PutPlusOneCounterOnSelf`, which restricts the source to the
    /// battlefield — the punisher pattern fires regardless of where
    /// the source has moved to, since the controller doesn't change
    /// when a permanent leaves the battlefield). Additionally checks
    /// the stack — the source may still be resolving (e.g. an
    /// instant / sorcery / triggered ability that just fired with
    /// `you discard a card` as its effect).
    ///
    /// **First-slice deterministic choice: discard hand[0]** of the
    /// source's controller (zone-iteration order, mirrors the round-15
    /// `DiscardCard` arm's hand[0] convention). Empty hand = silent
    /// no-op (Python parity with `if not p.hand: break` in
    /// `DiscardSelf.resolve`). Source not found anywhere = silent
    /// no-op (lost-track-of-source tolerance, mirrors
    /// `PutPlusOneCounterOnSelf`'s `source is None` short-circuit).
    ///
    /// **`amount` shape mirrors Python.** Python's
    /// `DiscardSelf(amount: int = 1)` carries an `amount: int = 1`
    /// default; this Rust variant mirrors that exactly. The
    /// dispatch resolves up to `amount` discards in a row (stop
    /// early on empty hand, matching the Python `for _ in
    /// range(self.amount): if not p.hand: break` shape). Negative
    /// `amount` raises at register / resolve time.
    DiscardSelf { amount: i32 },
    /// Each opponent of the source's controller loses `amount` life
    /// (CR 118.4 — life loss, not damage). Punisher / drawback shape
    /// (Balemurk Leech pattern) — 6 cards in the EoE pool per
    /// round-20 measurement.
    ///
    /// **Distinct from `DamageEachOpponent` (round 17).** Damage
    /// routes through damage-prevention / Worship-style replacement
    /// effects (CR 614 — damage replacement); life-loss directly
    /// subtracts from `players[idx].life` and is NOT reducible by
    /// damage-prevention. Two-player engine first slice: both arms
    /// look identical in their net effect on the defender's life
    /// total, but the variants stay distinct to mirror Python's
    /// closed `Effect` vocabulary (round-15 pattern). Future slices
    /// that wire damage-prevention through DealDamage /
    /// DamageEachOpponent will keep this arm a direct subtraction.
    ///
    /// **Source-finder dispatch (round-23 pattern).** Threads
    /// `source_obj_id` through `apply_effect` and walks both
    /// players' five tracked zones (hand / library / battlefield /
    /// graveyard / exile) plus the stack to recover the source's
    /// `controller`. Mirrors `DiscardSelf` (round-24) — punisher
    /// effects fire on whoever controls the source regardless of
    /// where the source currently sits, since the `controller` field
    /// doesn't change on zone moves. Source not found anywhere =
    /// silent fizzle (lost-track-of-source tolerance).
    ///
    /// **Two-player "each opponent" reduces to "the one opponent".**
    /// The opponent of player N is `1 - N`. The single opponent's
    /// `life` field is decremented by `amount`. Negative life is
    /// handled by the SBA loop (round-5+); no clamp here.
    ///
    /// **amount=0 is a legal no-op** (mirrors GainLife / DrawCards /
    /// Mill / DamageEachOpponent / DiscardSelf zero-amount
    /// conventions). **amount<0 raises** loudly (mirrors round-3
    /// DealDamage / round-17 DamageEachOpponent / round-24
    /// DiscardSelf raise-on-negative shape; "lose -2 life" is
    /// schema nonsense).
    EachOpponentLosesLife { amount: i32 },
    /// **BLOCKED-RUST-EFFECT slice (round 44) -- each opponent of the
    /// source-controller loses life equal to the number of ARTIFACTS the
    /// source-controller controls.** Mirrors Python's
    /// `EachOpponentLosesLifeEqualToArtifactCount`
    /// (`effects/generic/life.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-26's static
    /// `EachOpponentLosesLife { amount }` -- same recipient set + dispatch
    /// (each opponent of the source-controller, direct life subtraction
    /// CR 118.4 not damage), NEW dynamic-X denominator (artifact-count
    /// instead of static `amount`). FIFTH apply substrate to receive the
    /// X-from-count plumbing established by round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount` (damage), round-33's
    /// `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact` (counters),
    /// round-34's `SurveilXEqualToArtifactCount` (surveil), round-42's
    /// `MillTargetPlayerEqualToYourLifeTotal` (mill -- different
    /// denominator). Walks the apply-substrate axis to a fifth entry
    /// (life-loss-each-opponent), confirming the round-35
    /// bidirectionally-extensible X-from-count plumbing generalizes
    /// across both the substrate axis (damage / counters / surveil / mill
    /// / life-loss) and the denominator axis (artifact-count workhorse
    /// across damage / counters / surveil now also drives life-loss).
    ///
    /// **Mechanism -- count + apply.** At resolve time, count the
    /// source-controller's artifacts on bf
    /// (`printing.card_types.iter().any(|t| t == "Artifact")`) -- matches
    /// Python's `sum(1 for o in state.battlefield if o.controller_id ==
    /// controller_id and o.printing.is_artifact)` shape (mirrors the
    /// round-32 / round-34 artifact-count denominator BIT-FOR-BIT --
    /// same scan, same predicate, same `saturating_add` overflow guard).
    /// Lands that are also artifacts count, tokens like Lander count.
    /// Dual-typed artifact-creatures count for BOTH the artifact-count
    /// denominator and any creatures-controlled denominator
    /// independently (Scryfall lists both "Artifact" and "Creature" in
    /// card_types; checked independently per arm). The
    /// source-controller's OWN artifacts count toward the denominator if
    /// the source is itself an Artifact still on the bf at resolve time
    /// (mirrors Python's vanilla walk over `state.battlefield` -- no
    /// source-exclusion clause, mirrors round-32 / round-34 sister
    /// convention). If the artifact count is <= 0 -> silent no-op
    /// (matches Python's `if artifact_count <= 0: return` short-circuit
    /// before the per-opponent loop, also mirrors GainLife / DrawCards /
    /// Mill / EachOpponentLosesLife / DiscardSelf zero-amount no-op
    /// convention).
    ///
    /// **Apply -- each opponent loses `count` life.** In 2-player land
    /// this is "the one opponent" at `1 - controller`. Direct life
    /// subtraction via `saturating_sub` -- not damage; not reducible by
    /// damage-prevention / Worship-style replacement effects (CR 614);
    /// negative life is handled by the SBA loop on both engines, no
    /// clamp here. Mirrors the round-26 sister
    /// `Effect::EachOpponentLosesLife` apply step BIT-FOR-BIT, only the
    /// amount source differs (dynamic-X count vs static field).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors the round-26 sister `EachOpponentLosesLife` shape +
    /// every other dynamic-X arm exactly -- needs to resolve even if
    /// source has left bf, e.g. counterspelled trigger that still drives
    /// the count from the original ETB snapshot). If untrackable ->
    /// silent fizzle (lost-track-of-source tolerance, mirrors
    /// EachOpponentLosesLife / DiscardSelf shape).
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// no constructor args (the dynamic-X is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 / round-42 unit-variant schema convention.
    EachOpponentLosesLifeEqualToArtifactCount,
    /// **BLOCKED-RUST-EFFECT slice (round 48) -- each opponent of the
    /// source-controller loses life equal to the source-controller's
    /// CURRENT LIFE TOTAL.** Mirrors Python's
    /// `EachOpponentLosesLifeEqualToYourLifeTotal`
    /// (`effects/generic/life.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-44's
    /// `EachOpponentLosesLifeEqualToArtifactCount` -- SAME recipient set
    /// + dispatch (each opponent of the source-controller, direct life
    /// subtraction CR 118.4 not damage) and SAME apply substrate
    /// (life-loss-each-opponent), only the DENOMINATOR read differs
    /// (source-controller's current life total instead of their
    /// artifact count). This is the SECOND denominator on the
    /// life-loss-each-opponent apply substrate (artifact-count round-44
    /// -> life-total round-48); the round-42
    /// `MillTargetPlayerEqualToYourLifeTotal` (mill substrate) and
    /// round-47 `DealDamageToOpponentCreatureByLifeTotal` (damage
    /// substrate) are the life-total-denominator precedents on OTHER
    /// substrates. Walks the X-from-count matrix to a third
    /// (substrate, life-total) cell.
    ///
    /// **Mechanism -- read + apply.** At resolve time, read the
    /// source-controller's current life total and clamp negative life
    /// to 0 (`life.max(0)`) -- matches Python's `max(0, life)` clamp
    /// and the round-42 `MillTargetPlayerEqualToYourLifeTotal` /
    /// round-47 `DealDamageToOpponentCreatureByLifeTotal` life-total-
    /// denominator clamping precedent (negative life can arise from a
    /// prior loss/damage in the same resolution window before the SBA
    /// loop runs; a negative denominator would be nonsensical). If the
    /// clamped life is 0 -> silent no-op (matches Python's `if amount
    /// <= 0: return` short-circuit before the per-opponent loop, also
    /// mirrors GainLife / DrawCards / Mill / EachOpponentLosesLife /
    /// EachOpponentLosesLifeEqualToArtifactCount / DiscardSelf
    /// zero-amount no-op convention).
    ///
    /// **Apply -- each opponent loses `life` life.** In 2-player land
    /// this is "the one opponent" at `1 - controller`. Direct life
    /// subtraction via `saturating_sub` -- not damage; not reducible by
    /// damage-prevention / Worship-style replacement effects (CR 614);
    /// negative life is handled by the SBA loop on both engines, no
    /// clamp on the APPLY side here (the clamp is on the DENOMINATOR
    /// read only). Mirrors the round-44 sister
    /// `Effect::EachOpponentLosesLifeEqualToArtifactCount` apply step
    /// BIT-FOR-BIT, only the amount source differs (life-total read vs
    /// artifact-count walk).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors the round-44 sister
    /// `EachOpponentLosesLifeEqualToArtifactCount` shape exactly --
    /// needs to resolve even if source has left bf, e.g.
    /// counterspelled trigger that still drives the count from the
    /// original ETB snapshot). If untrackable -> silent fizzle
    /// (lost-track-of-source tolerance, mirrors
    /// EachOpponentLosesLife / DiscardSelf shape). NOTE: unlike the
    /// round-42 mill arm (which leans on
    /// `current_resolve_source_controller`), the dynamic-X each-opponent
    /// arms use the 5-zone walk for cross-arm consistency with the
    /// round-44 sister and so the inject-and-fire-ENTERS synthetic
    /// harness (where the resolve-harness shortcut isn't set) resolves
    /// correctly.
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// no constructor args (the dynamic-X is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 / round-42 / round-44 / round-45 / round-47
    /// unit-variant schema convention.
    EachOpponentLosesLifeEqualToYourLifeTotal,
    /// **BLOCKED-RUST-EFFECT slice (round 45) -- the source's
    /// controller GAINS life equal to the number of ARTIFACTS the
    /// source-controller controls.** Mirrors Python's
    /// `GainLifeEqualToArtifactCount` (`effects/generic/life.py` --
    /// shipped in this slice; no pre-existing class). Sister of
    /// round-26's static `GainLife { amount }` -- same recipient
    /// (the source's controller, NOT the opponent) + same apply step
    /// (direct life addition CR 119.3, not damage healing), NEW
    /// dynamic-X denominator (artifact-count instead of static
    /// `amount`). SIXTH apply substrate to receive the X-from-count
    /// plumbing established by round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount` (damage),
    /// round-33's `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`
    /// (counters), round-34's `SurveilXEqualToArtifactCount` (surveil),
    /// round-42's `MillTargetPlayerEqualToYourLifeTotal` (mill --
    /// different denominator), and round-44's
    /// `EachOpponentLosesLifeEqualToArtifactCount` (life-loss-each-
    /// opponent). Walks the apply-substrate axis to a SIXTH entry
    /// (gain-life-controller-self), and is the controller-self
    /// MIRROR of the round-44 each-opponent-life-loss arm: same
    /// denominator (artifact-count workhorse), same dispatch shape,
    /// inverted recipient (controller-self vs opponents-of-controller)
    /// AND inverted sign (gain vs loss).
    ///
    /// **Mechanism -- count + apply.** At resolve time, count the
    /// source-controller's artifacts on bf
    /// (`printing.card_types.iter().any(|t| t == "Artifact")`) -- matches
    /// Python's `sum(1 for o in state.battlefield if o.controller_id ==
    /// controller_id and o.printing.is_artifact)` shape (mirrors the
    /// round-32 / round-34 / round-44 artifact-count denominator
    /// BIT-FOR-BIT -- same scan, same predicate, same `saturating_add`
    /// overflow guard). Lands that are also artifacts count, tokens
    /// like Lander count. Dual-typed artifact-creatures count for BOTH
    /// the artifact-count denominator and any creatures-controlled
    /// denominator independently (Scryfall lists both "Artifact" and
    /// "Creature" in card_types; checked independently per arm). The
    /// source-controller's OWN artifacts count toward the denominator
    /// if the source is itself an Artifact still on the bf at resolve
    /// time (mirrors Python's vanilla walk over `state.battlefield` --
    /// no source-exclusion clause, mirrors round-32 / round-34 /
    /// round-44 sister convention). If the artifact count is <= 0 ->
    /// silent no-op (matches Python's `if artifact_count <= 0: return`
    /// short-circuit before the per-controller life-add, also mirrors
    /// GainLife / DrawCards / Mill / EachOpponentLosesLife /
    /// DiscardSelf zero-amount no-op convention).
    ///
    /// **Apply -- the source's controller gains `count` life.** Direct
    /// life addition via simple `+=` (matches the round-26 sister
    /// `Effect::GainLife { amount }` apply step BIT-FOR-BIT -- only the
    /// amount source differs, dynamic-X count vs static field). Not
    /// damage; not amplifiable by life-gain triggers' damage-prevention
    /// hooks (CR 119.3 distinguishes life gain from damage prevention).
    /// In the engine's two-player land the recipient is exactly the
    /// source-controller (= the caster on a typical ETB).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors the round-26 sister `EachOpponentLosesLife` /
    /// round-44 `EachOpponentLosesLifeEqualToArtifactCount` shape +
    /// every other dynamic-X arm exactly -- needs to resolve even if
    /// source has left bf, e.g. counterspelled trigger that still
    /// drives the count from the original ETB snapshot). If
    /// untrackable -> silent fizzle (lost-track-of-source tolerance,
    /// mirrors EachOpponentLosesLife / DiscardSelf shape). Bare
    /// `Effect::GainLife { amount }` uses
    /// `state.current_resolve_source_controller` as a shortcut (set by
    /// the standard resolve harness), but the dynamic-X arm needs the
    /// 5-zone walk because the count denominator must read from the
    /// source's ACTUAL controller's bf, not whoever happens to be the
    /// resolve-time active player.
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored on
    /// the variant. Python's `@dataclass(frozen=True)` class has no
    /// constructor args (the dynamic-X is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 / round-42 / round-44 unit-variant schema
    /// convention.
    GainLifeEqualToArtifactCount,
    /// **BLOCKED-RUST-EFFECT slice (round 49) -- the source's
    /// controller GAINS life equal to the source-controller's CURRENT
    /// LIFE TOTAL.** Mirrors Python's `GainLifeEqualToYourLifeTotal`
    /// (`effects/generic/life.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-45's
    /// `GainLifeEqualToArtifactCount` -- SAME recipient (the source's
    /// controller, NOT the opponent) + SAME apply step (direct life
    /// addition via the `gain_life` helper CR 119.3, not damage
    /// healing) and SAME apply substrate (gain-life-controller-self),
    /// only the DENOMINATOR read differs (source-controller's current
    /// life total instead of their artifact count). This is the SECOND
    /// denominator on the gain-life-controller-self apply substrate
    /// (artifact-count round-45 -> life-total round-49); the round-42
    /// `MillTargetPlayerEqualToYourLifeTotal` (mill substrate), round-47
    /// `DealDamageToOpponentCreatureByLifeTotal` (damage substrate) and
    /// round-48 `EachOpponentLosesLifeEqualToYourLifeTotal`
    /// (life-loss-each-opponent substrate) are the life-total-
    /// denominator precedents on OTHER substrates. Walks the
    /// X-from-count matrix to a FOURTH (substrate, life-total) cell.
    ///
    /// **Mechanism -- read + apply.** At resolve time, read the
    /// source-controller's current life total and clamp negative life
    /// to 0 (`life.max(0)`) -- matches Python's `max(0, life)` clamp
    /// and the round-42 `MillTargetPlayerEqualToYourLifeTotal` /
    /// round-47 `DealDamageToOpponentCreatureByLifeTotal` / round-48
    /// `EachOpponentLosesLifeEqualToYourLifeTotal` life-total-
    /// denominator clamping precedent (negative life can arise from a
    /// prior loss/damage in the same resolution window before the SBA
    /// loop runs; a negative denominator would be nonsensical). If the
    /// clamped life is 0 -> silent no-op (matches Python's `if amount
    /// <= 0: return` short-circuit before the life-add, also mirrors
    /// GainLife / DrawCards / Mill / EachOpponentLosesLife /
    /// GainLifeEqualToArtifactCount / DiscardSelf zero-amount no-op
    /// convention).
    ///
    /// **Apply -- the source's controller gains `life` life.** Direct
    /// life addition via the `gain_life` helper (mirrors the round-45
    /// sister `Effect::GainLifeEqualToArtifactCount` apply step
    /// BIT-FOR-BIT -- only the amount source differs, life-total read
    /// vs artifact-count walk). Not damage; not amplifiable by
    /// life-gain triggers' damage-prevention hooks (CR 119.3
    /// distinguishes life gain from damage prevention). In the engine's
    /// two-player land the recipient is exactly the source-controller
    /// (= the caster on a typical ETB).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors the round-45 sister `GainLifeEqualToArtifactCount`
    /// shape exactly -- needs to resolve even if source has left bf,
    /// e.g. counterspelled trigger that still drives the count from the
    /// original ETB snapshot). If untrackable -> silent fizzle
    /// (lost-track-of-source tolerance, mirrors
    /// GainLifeEqualToArtifactCount / EachOpponentLosesLife /
    /// DiscardSelf shape). Bare `Effect::GainLife { amount }` uses
    /// `state.current_resolve_source_controller` as a shortcut (set by
    /// the standard resolve harness), but the dynamic-X arm needs the
    /// 5-zone walk because the life-total denominator must read from
    /// the source's ACTUAL controller, not whoever happens to be the
    /// resolve-time active player.
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored on
    /// the variant. Python's `@dataclass(frozen=True)` class has no
    /// constructor args (the dynamic-X is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 / round-42 / round-44 / round-45 / round-47
    /// / round-48 unit-variant schema convention.
    GainLifeEqualToYourLifeTotal,
    /// The SOURCE's controller loses `amount` life (CR 118.4 — life
    /// loss, not damage). 7 cards in EoE pool per round-20 measurement
    /// (Decode Transmissions etc.). Punisher / drawback pattern — the
    /// caster pays a life cost on resolution.
    ///
    /// **Distinct from `EachOpponentLosesLife` (round 24)** — that arm
    /// subtracts from the OPPONENT's life. This arm subtracts from the
    /// SOURCE's CONTROLLER's life (typically the caster). Both use the
    /// same source-finder pattern (round-24 5-zone walk + stack scan).
    ///
    /// **Distinct from `GainLife` with negative `amount`** — that
    /// pattern raises ("gain -2 life" is schema nonsense). `LoseLife`
    /// is the closed-vocab variant for losing life; negative `amount`
    /// here also raises (defense-in-depth).
    ///
    /// amount=0 is a legal no-op. Negative amount raises.
    LoseLife { amount: i32 },
    /// Target opponent loses `amount` life (CR 118.4). 2 cards in EoE
    /// pool per round-20 measurement (Dubious Delicacy etc.).
    ///
    /// **Distinct from `EachOpponentLosesLife` (round 24)** — that arm
    /// hits ALL opponents (in 2-player land = the one opponent).
    /// `TargetOpponentLosesLife` is targeted: the caster CHOOSES which
    /// opponent loses life. In a 2-player engine these collapse to the
    /// same runtime effect, but the variants stay distinct to mirror
    /// Python's closed Effect vocabulary.
    ///
    /// **First-slice deterministic choice**: the one opponent (= 1 -
    /// controller). Future multiplayer / archenemy work needs an
    /// explicit choice callback. Negative `amount` raises; amount=0
    /// is a legal no-op.
    TargetOpponentLosesLife { amount: i32 },
    /// Each opponent of the source's controller discards a card (CR
    /// 701.8). Let's Play a Game pattern — 2 cards in the EoE pool
    /// per round-20 measurement. Mirrors Python's
    /// `EachOpponentDiscards(count: int = 1)` dataclass.
    ///
    /// **Distinct from `DiscardCard { target: AnyPlayer }` (round 15)**
    /// — that arm picks the DEFENDING player's hand[0] (caller-
    /// targeted, Mind Rot shape — active player forces the defender to
    /// discard). `EachOpponentDiscards` fires on the SOURCE'S
    /// controller's opponents (source-relative, independent of
    /// active_player at apply-effect time). In two-player land both
    /// collapse to "the one opponent discards hand[0]" but the
    /// variants stay distinct to mirror Python's closed Effect
    /// vocabulary (round-15 pattern).
    ///
    /// **Distinct from `DiscardSelf` (round 24).** Same source-finder
    /// pattern (5-zone walk + stack scan) and same hand[0] +
    /// graveyard-push primitive, but `DiscardSelf` fires on the
    /// CONTROLLER while this arm fires on the OPPONENT of the
    /// controller. Inverted target on an otherwise identical dispatch
    /// shape — composes round-24 EachOpponentLosesLife's opponent-
    /// resolution with round-24 DiscardSelf's discard primitive.
    ///
    /// **Source-finder dispatch (round-23 pattern).** Walks both
    /// players' five tracked zones (hand / library / battlefield /
    /// graveyard / exile) plus the stack to recover the source's
    /// `controller`. Punisher / "let's play a game" effects fire on
    /// whoever controls the source regardless of where the source
    /// currently sits, since the `controller` field doesn't change on
    /// zone moves.
    ///
    /// **Two-player "each opponent" reduces to "the one opponent".**
    /// opponent_id = 1 - controller. The single opponent's hand[0] is
    /// popped to graveyard with CR 400.7 state reset (mirrors round-24
    /// DiscardSelf). Up to `count` discards in a row; empty hand stops
    /// early (Python parity with `for _ in range(self.count): if not
    /// p.hand: break` inside `EachOpponentDiscards.resolve`).
    ///
    /// **Empty opponent hand = silent no-op** (Python parity). **Source
    /// not found anywhere = silent fizzle** (lost-track-of-source
    /// tolerance, mirrors round-24 / round-25 / round-26 shape).
    ///
    /// **`count` shape mirrors Python.** Python's
    /// `EachOpponentDiscards(count: int = 1)` carries a `count: int = 1`
    /// default; this Rust variant mirrors that exactly. Missing
    /// `count` registers as count=1 (NOT a KeyError, mirrors
    /// DiscardSelf / TargetOpponentDiscards default-handling). Negative
    /// `count` raises at register / resolve time.
    EachOpponentDiscards { count: i32 },
    /// Destroy every creature on the battlefield (Wrath of God pattern,
    /// CR 701.7 + 701.4 AOE). Indestructible creatures (CR 702.12)
    /// are NOT destroyed — round-13 keyword check is honored.
    /// Destroyed creatures go to their owner's graveyard (CR 400.6).
    /// 3 cards in the EoE pool per round-20 measurement (Restricted
    /// Office // Lecture Hall and friends).
    ///
    /// **Symmetric AOE: applies to BOTH players' battlefields** — like
    /// DamageEachCreature, this is implicit-target and hits every
    /// creature regardless of controller. No target filter — the
    /// variant doesn't carry a TargetFilter for that reason.
    ///
    /// **Creature-only filter via printing's card_types.** Lands /
    /// artifacts / enchantments / planeswalkers on the battlefield
    /// stay where they are; only objects whose printing has "Creature"
    /// in card_types are destroyed.
    ///
    /// **Indestructible is honored INLINE** (CR 702.12) — unlike
    /// DamageEachCreature (which writes damage and lets the SBA reap),
    /// DestroyAllCreatures moves creatures directly to graveyard. So
    /// the indestructible keyword check happens here, inline, mirroring
    /// the DestroyTarget arm.
    ///
    /// **Per-object state reset on graveyard move** (CR 400.7) —
    /// tapped / summoning_sick / damage / counters all reset on the
    /// way to graveyard, mirroring the DestroyTarget / Sacrifice /
    /// ExileTarget reset convention.
    ///
    /// **Python schema simplification.** Python's
    /// `DestroyAllCreatures` carries optional narrowing fields:
    /// `tapped_only` / `untapped_only` (Split Up modal Wrath) and
    /// `min_power` (Restricted Office "destroy all creatures with
    /// power 3+"). The Rust first slice carries NONE of these — it's
    /// a unit shape ("destroy all creatures, unconditional"). The
    /// narrowed variants wait for richer dispatch plumbing and are
    /// deferred along with the rest of the TargetFilter widening
    /// shape elsewhere in the bridge.
    DestroyAllCreatures,
    /// Destroy target non-land permanent on the defending player's
    /// battlefield (CR 701.7 + scoped target filter — Drag to the
    /// Roots / Drill Too Deep pattern). 2 cards in the EoE pool per
    /// round-20 measurement. Scans defender's battlefield top-to-
    /// bottom and picks the first non-Land, non-indestructible
    /// object. Mirrors round-17 DestroyTarget's pick-bf[0] shape
    /// with a Land-skip + indestructible-skip filter. Unit variant —
    /// the "non-land permanent" target shape is intrinsic.
    DestroyTargetNonlandPermanent,
    /// Destroy target artifact on the defending player's battlefield
    /// (CR 701.7, artifact-filter). 2 cards in EoE pool per round-20
    /// measurement (Drill Too Deep, Scour for Scrap). Unit variant.
    ///
    /// **First-slice deterministic choice**: defender's FIRST artifact
    /// (top-to-bottom scan), skipping indestructible (CR 702.12) per
    /// the round-24 DestroyTargetNonlandPermanent convention.
    /// Empty / no-artifacts / only-indestructible-artifacts = silent
    /// fizzle.
    ///
    /// **Distinct from `DestroyTargetNonlandPermanent` (round 24)** —
    /// that arm filters `!card_types.contains("Land")` (picks creatures,
    /// artifacts, enchantments, planeswalkers — anything non-land).
    /// This arm filters `card_types.contains("Artifact")` (artifacts
    /// only). Identical dispatch shape otherwise (defender-side scan,
    /// indestructible-skip, first-match, silent fizzle on empty /
    /// only-indestructible-artifacts). Mirrors Python's
    /// `DestroyTargetArtifact(Destroy)` constructor sugar with
    /// `targets=(TargetSpec(IsArtifact()),)`.
    DestroyTargetArtifact,
    /// Destroy target land on the defending player's battlefield
    /// (CR 701.7, land-filter). 2 cards in EoE pool per round-20
    /// measurement (Dust Bowl etc.). Unit variant.
    ///
    /// **First-slice deterministic choice**: defender's FIRST land
    /// (top-to-bottom scan), skipping indestructible. Mirrors round-25
    /// `DestroyTargetArtifact` exactly with the filter swapped.
    /// Empty / no-lands / only-indestructible-lands = silent fizzle.
    ///
    /// **Distinct from `DestroyTargetArtifact` (round 25)** —
    /// that arm filters `card_types.contains("Artifact")` (artifacts
    /// only). This arm filters `card_types.contains("Land")` (lands
    /// only). Identical dispatch shape otherwise (defender-side scan,
    /// indestructible-skip, first-match, silent fizzle on empty /
    /// only-indestructible-lands). Mirrors Python's
    /// `DestroyTargetLand(Destroy)` constructor sugar with
    /// `targets=(TargetSpec(IsLand()),)`.
    DestroyTargetLand,
    /// **BLOCKED-RUST-EFFECT slice (round 52) — Extinguisher Battleship
    /// ETB head.** Destroy target NONCREATURE permanent (CR 701.7 with
    /// a `!IsCreature() & !IsPlayer()` filter). Unit variant — the
    /// "noncreature permanent" target shape is intrinsic.
    ///
    /// **Distinct from `DestroyTargetNonlandPermanent` (round 24)** —
    /// that arm filters `!card_types.contains("Land")` (picks
    /// creatures, artifacts, enchantments, planeswalkers — anything
    /// non-land; EXCLUDES lands). THIS arm filters
    /// `!card_types.contains("Creature")` (picks artifacts,
    /// enchantments, planeswalkers, LANDS — anything non-creature;
    /// EXCLUDES creatures). The two filters are NOT interchangeable:
    /// `nonland` admits creatures + excludes lands; `noncreature`
    /// admits lands + excludes creatures. The real Extinguisher
    /// Battleship printing parses (faithfully) to Python's
    /// `DestroyTargetNoncreaturePermanent` whose `TargetSpec` filter
    /// is exactly `~IsCreature() & ~IsPlayer()` — so this slice ships
    /// the precise sibling rather than approximating via the
    /// pre-existing nonland arm (no `nonland≈noncreature` shortcut).
    ///
    /// **First-slice deterministic choice**: scan BOTH players'
    /// battlefield in ETB-timestamp order
    /// (`bf_iter::bf_iter_etb_sorted`), pick the FIRST object whose
    /// printing `card_types` does NOT contain "Creature" and which is
    /// not indestructible (CR 702.12). Empty / no-noncreature /
    /// only-indestructible-noncreature = silent fizzle. Players are
    /// structurally excluded (the bf walk only iterates GameObjects).
    /// Identical dispatch/LTB-fanout shape to the round-24
    /// `DestroyTargetNonlandPermanent` arm with the filter predicate
    /// swapped Land→Creature. Mirrors Python's
    /// `effects/generic/destroy.py:DestroyTargetNoncreaturePermanent`.
    DestroyTargetNoncreaturePermanent,
    /// **Effect-uncovered Tier-A — Radiant Strike inner half.**
    /// Destroy the first battlefield permanent matching
    /// (Artifact) OR (Creature AND tapped), in ETB-timestamp order,
    /// skipping indestructible. Field-free unit variant (no payload —
    /// the typed-OR filter is the whole behavior). Mirrors Python's
    /// `DestroyTargetArtifactOrTappedCreature`
    /// (`effects/generic/destroy.py:475`) whose `TargetSpec` filter is
    /// `IsArtifact() | (IsCreature() & IsTapped())`.
    ///
    /// **Distinct from `DestroyTargetArtifact` (round 25)** — that
    /// arm filters `card_types.contains("Artifact")` (artifacts only).
    /// THIS arm admits artifacts OR tapped creatures: an untapped
    /// non-artifact creature is NOT a legal pick (the OR-filter
    /// teeth). Identical dispatch/LTB-fanout shape otherwise (BOTH
    /// players' bf in ETB-timestamp order, indestructible-skip,
    /// first-match, silent fizzle on empty / only-indestructible /
    /// only-untapped-non-artifact-creatures). The `tapped` term is
    /// read off the scanned `GameObject` (live battlefield state, the
    /// round-53 effective-state lesson — read where the real card
    /// would; `obj.tapped` IS the effective tapped state).
    ///
    /// The `Sequence`+`GainLife` outer shell is already live — Radiant
    /// Strike's full effect is
    /// `Sequence([DestroyTargetArtifactOrTappedCreature, GainLife{3}])`,
    /// composed entirely from existing arms + this one new arm.
    DestroyTargetArtifactOrTappedCreature,
    /// **Effect-uncovered Tier-A — Seedship Impact (Lander-rider).**
    /// Destroy the first battlefield (Artifact OR Enchantment) in
    /// ETB-timestamp order, skipping indestructible. If it was
    /// actually destroyed AND its printed mana value ≤ 2, create one
    /// Lander token under the source's controller. Mirrors Python's
    /// `SeedshipImpactEffect` (`effects/bespoke.py:1219`): pick target
    /// (artifact OR `"Enchantment" in card_types`); read
    /// `mv = obj.printing.mana_cost.total` **before** destroy;
    /// `destroy(state, obj)` (returns `False` for indestructible →
    /// **no Lander consolation**); if destroyed AND `mv ≤ 2` →
    /// `CreateToken(Lander)` for the controller.
    ///
    /// **NOT a field-free unit variant (mini-spec deviation,
    /// documented).** The mini-spec sketched a unit variant, but
    /// Rust's registry has NO intrinsic Lander concept —
    /// `RegistryData::is_token` is purely supertype-derived and a
    /// bespoke token-minting arm must carry the Lander's
    /// `token_printing_id: u32` exactly as `Effect::CreateToken`
    /// does (the only bridge-correct option; the bridge ships the pid
    /// via the round-49/56 `TOKEN_PRINTING_SUBSTRATE`). The Python
    /// `SeedshipImpactEffect` is still field-free — it resolves the
    /// Lander intrinsically via `TOKEN_PRINTINGS["Lander"]`; the pid
    /// is a Rust-side registry-index carrier only, dropped at the
    /// bridge (the bridge constructs the bare Python class).
    ///
    /// **Indestructible parity nuance (§2):** the scan SKIPS
    /// indestructible permanents (matching the shipped
    /// `DestroyTargetArtifact` precedent), so an
    /// indestructible-only board → no target → no destroy → no
    /// Lander, byte-equal to Python's `destroy()`-returns-False →
    /// early-return (no Lander consolation). Both engines reach the
    /// same observable. Re-derive the Lander create block privately
    /// (file-iso) — do NOT cross-import the `Effect::CreateToken`
    /// arm.
    SeedshipImpactEffect { token_printing_id: u32 },
    /// Deal `amount` damage to any target — creature OR player
    /// (Lightning Bolt pattern, CR 701.4). 7 cards in EoE pool per
    /// round-20 measurement (Debris Field Crusher etc.). Mirrors
    /// Python's `DealDamageAnyTarget(DealDamage)` constructor sugar —
    /// the "any target" filter is intrinsic to the variant, distinct
    /// from `DealDamage { target: AnyPlayer/AnyCreature }` which
    /// requires a target dict.
    ///
    /// First-slice deterministic choice: prefer the defender's first
    /// creature on their battlefield (mirrors the `AnyCreature` arm
    /// in `DealDamage`); fall back to defender-as-player life
    /// subtraction (mirrors the `AnyPlayer` arm) when no creature is
    /// available. Future slice plumbs an explicit choice callback.
    /// Negative `amount` raises at register and at resolve time.
    DealDamageAnyTarget { amount: i32 },
    /// **Round 27 UEOT-framework proof.** Source gets
    /// `+power/+toughness` until end of turn. Mirrors Python's
    /// `PumpSelfUntilEOT(power_bonus, toughness_bonus)` dataclass
    /// (12 cards in the EoE pool — Attack-in-the-Box, etc.).
    ///
    /// **"Self" semantics.** The recipient is the source GameObject
    /// at the top of the stack (i.e. the resolving spell or
    /// activated-ability source). Same `state.resolving_source`
    /// shape Python reads — and the same `source_obj_id`
    /// `apply_effect` parameter the round-23 `PutPlusOneCounterOnSelf`
    /// arm already threads through. If the source has left the
    /// battlefield between cast and resolve, the effect is a silent
    /// no-op (mirrors Python's `if source is None: return`).
    ///
    /// **Mechanism.** Pushes a
    /// `UeotModifier::PowerToughnessBonus { power, toughness }` entry
    /// onto the source object's `ueot_modifiers` Vec on the
    /// battlefield. Effective power/toughness queries
    /// (`battlefield_creature_power`/`_toughness` in
    /// `state_ops_combat.rs`, `effective_toughness` in
    /// `state_ops_sba.rs`) walk the Vec on top of printed P/T at
    /// read time. The bonus auto-expires at the next
    /// `cleanup_step_for_active_player` /
    /// `advance_phase`-through-PHASE_CLEANUP via the round-27
    /// CR 514.3 UEOT-clear pass.
    ///
    /// **Schema simplification vs Python.** Python's
    /// `PumpSelfUntilEOT` also accepts an optional
    /// `granted_keywords: frozenset[str]` to grant keywords UEOT in
    /// the same effect. The Rust first slice does NOT carry that
    /// field — the cards in the EoE pool with keyword riders compose
    /// via separate effect chains (the bridge dispatch can layer a
    /// `GrantKeyword` UEOT modifier in a future PumpSelf variant).
    /// Negative bonuses are legal (Cryptolith Rite-shape debuffs);
    /// raise-on-negative is NOT enforced. count=0/0 is a legal
    /// no-op for parity-test edge cases.
    PumpSelfUntilEOT { power_bonus: i32, toughness_bonus: i32 },
    /// **Round 28 UEOT-coverage extension.** Target creature gets
    /// `+power/+toughness` until end of turn. Mirrors Python's
    /// `PumpTargetCreatureUntilEOT(power_bonus, toughness_bonus)`
    /// dataclass (26 cards in the EoE pool — Giant Growth-shape
    /// instants and sorceries, highest-frequency Effect class not
    /// yet in Rust per r27 measurement).
    ///
    /// **Target semantics — first-slice deterministic.** The
    /// recipient is the FIRST creature on the SOURCE'S CONTROLLER's
    /// battlefield (smallest Vec index). This mirrors the
    /// "you-control target" convention that the vast majority of
    /// pump spells use (Giant Growth: "target creature gets +3/+3
    /// UEOT"; typically cast to buff your own creature). If the
    /// source's controller controls NO creatures on battlefield,
    /// the spell fizzles silently — mirrors Python's
    /// `if not legal_targets: return` short-circuit when `optional`
    /// is set or no creature exists. No
    /// explicit target choice today; rich target enumeration is the
    /// future decision-callback follow-up (G20 substrate already
    /// in place from r27).
    ///
    /// **Source-on-battlefield edge.** If `source_obj_id` itself is
    /// a creature on the source's controller's battlefield (rare for
    /// instants/sorceries, but possible for activated-ability sources
    /// or self-resolving permanents), it IS eligible. The Rust
    /// first-slice does NOT carry Python's `another: bool` field
    /// (which excludes self-as-target on cards like Perigee Beckoner);
    /// a future slice can layer it on.
    ///
    /// **Schema simplification vs Python.** Python's
    /// `PumpTargetCreatureUntilEOT` carries `granted_keywords`,
    /// `you_control_only`, `opponents_only`, `target_subtype`,
    /// `optional`, `another`, `granted_triggered_ability`, and a
    /// `draw_if_target_has_plus_one_counter` rider. The Rust first
    /// slice carries NONE of these — cards with those riders compose
    /// via separate effect chains or wait for a decision-callback-
    /// driven richer target plumbing slice. Negative bonuses are
    /// legal (debuff-shaped pumps); no raise-on-negative guard.
    /// `(0, 0)` is a legal no-op for parity edge cases.
    ///
    /// **Mechanism.** Same UEOT-modifier push as `PumpSelfUntilEOT`,
    /// just on the chosen target rather than the source. The
    /// modifier auto-expires at the next cleanup step via the r27
    /// CR 514.3 UEOT-clear pass.
    PumpTargetCreatureUntilEOT { power_bonus: i32, toughness_bonus: i32 },
    /// **BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner ETB.**
    /// "When this creature enters, until end of turn, ANOTHER target
    /// creature you control gets +power/+toughness and gains 'When
    /// this creature dies, return it to the battlefield tapped under
    /// its owner's control.'" (~21,131 17lands decks.)
    ///
    /// This is the `granted_triggered_ability`-carrying shape of
    /// `PumpTargetCreatureUntilEOT` that the bare round-28 arm
    /// explicitly does NOT carry (see that variant's "Schema
    /// simplification vs Python" doc-comment — the
    /// `granted_triggered_ability` rider was deferred to a follow-up
    /// slice; this IS that slice for the Perigee shape). Mirrors
    /// Python's
    /// `PumpTargetCreatureUntilEOT(power_bonus=2, you_control_only=
    /// True, exclude_self=True, granted_triggered_ability=
    /// TriggeredAbility(effect=PerigeeBeckonerDiesReturnTappedEffect(),
    /// event=Event.DIES, predicate=IsSelf()))`.
    ///
    /// **Target semantics — first-slice deterministic, ANOTHER /
    /// you-control.** Recipient = the FIRST creature on the source-
    /// controller's battlefield (smallest Vec index) that is NOT the
    /// source object itself (Perigee's "ANOTHER target creature you
    /// control"). Empty / only-self → silent fizzle (mirrors Python's
    /// `optional`-free `if not legal_targets: return`). Same
    /// first-creature-on-own-bf scan `PumpTargetCreatureUntilEOT`
    /// uses, plus the source-id exclusion.
    ///
    /// **Mechanism.** Pushes BOTH a `UeotModifier::PowerToughnessBonus
    /// { power: power_bonus, toughness: toughness_bonus }` AND a
    /// `UeotModifier::GrantedDiesReturnTapped` marker onto the chosen
    /// target. The marker is honored by the SBA destroy path
    /// (`state_ops_sba.rs`): if the carrier is destroyed via SBA it
    /// is returned from its owner's graveyard to its OWNER's
    /// battlefield, tapped, dropping ONLY the
    /// `GrantedDiesReturnTapped` marker (no re-fire on a 2nd death)
    /// while KEEPING the `PowerToughnessBonus` — Python's
    /// source-of-truth behavior, since its
    /// `PerigeeBeckonerDiesReturnTappedEffect` re-uses the same object
    /// and `put_into_battlefield` leaves `temp_power_bonus` intact
    /// (round-53 effective-state lesson; see state_ops_sba.rs). Both
    /// modifiers auto-expire at the next CR 514.3 UEOT-clear pass, so
    /// a target that survives the turn loses the rider at cleanup
    /// exactly as Python's `EndOfTurn`-bounded grant does.
    ///
    /// **Honest split (round 60).** This closes the Effect half
    /// byte-equal (pump + the fixed Perigee dies-return-tapped
    /// rider). The GENERAL nested-trigger-grant subsystem (an
    /// arbitrary granted triggered ability via a Rust layer-6
    /// registry analogous to Python's `continuous_effects`
    /// `grant_triggered_ability`) is the deferred multi-round half;
    /// the full Perigee Beckoner card stays loader-gated (also
    /// `warp_cost`, a §2-declined cost-mechanic). See
    /// docs/SEARCH_LIMITATIONS.md round-60.
    PumpTargetCreatureUntilEotGrantDiesReturnTapped {
        power_bonus: i32,
        toughness_bonus: i32,
    },
    /// **BLOCKED-RUST-EFFECT slice — Fight effect arm.** "Target
    /// creature you control fights target creature an opponent
    /// controls" (CR 701.12). Both fighters deal damage equal to
    /// their power to the other simultaneously; per CR 701.12c, if
    /// either fighter has left the battlefield by resolve time, no
    /// damage is dealt at all (the fight fizzles).
    ///
    /// Mirrors Python's `FightTargetCreatureWithTargetCreature`
    /// generic-fight class shipped in the same slice (a sibling of
    /// `EnchantedCreatureFightsTargetEffect`, which is the
    /// Aura-attached-creature-fights-opponent shape used by
    /// Meltstrider's Resolve specifically).
    ///
    /// **Target semantics — first-slice deterministic.** The
    /// SOURCE-side fighter is the FIRST creature on the source-
    /// controller's battlefield (smallest Vec index). The
    /// OPPONENT-side fighter is the FIRST creature on the
    /// opponent's battlefield (1 - source_controller, smallest
    /// Vec index). This mirrors the same first-creature-on-bf
    /// scan PumpTargetCreatureUntilEOT (caster side) and
    /// DealDamageAnyTarget (opponent side) use. Neither side
    /// has explicit target choice today; the future decision-
    /// callback slice plumbs explicit target picks through.
    ///
    /// **Source-controller resolution.** Routes through the
    /// I67 controller-of-effect substrate
    /// (`current_resolve_source_controller` with active_player
    /// fallback) so cross-controller fight (a flicker re-ETB
    /// firing while the OTHER seat is active) routes correctly:
    /// the source-side scan is on the SOURCE'S controller's bf,
    /// not the active player's bf. Same shape as the
    /// PumpTargetCreatureUntilEOT cross-controller routing.
    ///
    /// **Mechanism.** Compute both fighters' effective power BEFORE
    /// applying any damage (CR 701.12 — simultaneous damage event).
    /// If both targets exist at resolve time, deal each fighter's
    /// power as damage to the other via `deal_damage` (the per-
    /// object damage marker the `state_ops_damage` slice exposes).
    /// SBAs are not run inline by this arm; they fire on the next
    /// SBA pass after the resolve, by which point both damage
    /// markers are in place — deathtouch-style "both die" outcomes
    /// surface when the SBA loop runs.
    ///
    /// **Fizzle cases (silent — no damage applied).**
    /// - Source-controller untrackable (source object not in any
    ///   tracked zone) — silent fizzle.
    /// - Source-controller has no creatures on bf — silent fizzle.
    /// - Opponent has no creatures on bf — silent fizzle.
    /// - Either fighter's printing carries `power: None` (non-
    ///   creature, edge case the creature-filter scan should
    ///   prevent but defensive `unwrap_or(0)` keeps us safe).
    ///
    /// **Schema simplification vs Python's full Fight family.**
    /// Python's full Fight class hierarchy carries variants for
    /// "fights up to one" (optional target), "fights with trample
    /// / deathtouch", "fights twice", and the Aura-shape
    /// (enchanted creature fights). The Rust first-slice only
    /// carries the bare bilateral-fight shape ("creature you
    /// control fights creature opponent controls"). The Aura
    /// shape (Meltstrider's Resolve specifically) is documented
    /// as a deferred follow-up in
    /// `docs/EOE_PROBE_READINESS_AUDIT.md` — it needs the
    /// Aura-attachment substrate routed through the source's
    /// `attached_to` field, which the current Aura ETB-trigger
    /// path does not yet plumb end-to-end on Rust. Other
    /// variants (with-trample, with-deathtouch, optional)
    /// compose via future Effect arms.
    ///
    /// **Empty-bf no-op shape.** `(0, 0)` doesn't apply here (no
    /// numeric fields) — the fizzle on missing fighters is the
    /// no-op equivalent.
    FightTargetCreatureWithTargetCreature,
    /// **BLOCKED-RUST-EFFECT slice (round 31) — double target
    /// creature's power until end of turn.** Mirrors Python's
    /// `DoubleTargetCreaturesPowerUEOT` (`effects/generic/pump.py:194`
    /// — Mightform Harmonizer's landfall trigger; 1 EoE card).
    ///
    /// **Mechanism — snapshot-pump.** Read the target's effective
    /// power at RESOLUTION TIME (so any prior pumps / counters / base
    /// PT overrides this turn already factor in), then push a UEOT
    /// `PowerToughnessBonus { power: snapshot, toughness: 0 }`
    /// modifier onto the target. The bonus is fixed at the snapshot
    /// — further counter gains or pumps later this turn do NOT
    /// re-double (matches Python's class docstring: "the bonus is a
    /// one-time snapshot at resolution"). The modifier auto-expires
    /// at the next cleanup step via the r27 CR 514.3 UEOT-clear pass.
    ///
    /// **Target semantics — first-slice deterministic.** The recipient
    /// is the FIRST creature on the SOURCE'S CONTROLLER's battlefield
    /// (smallest Vec index). Mirrors `PumpTargetCreatureUntilEOT`'s
    /// you-control target convention — Mightform Harmonizer's oracle
    /// reads "double the power of target creature **you control**".
    /// Empty bf / no creatures → silent fizzle.
    ///
    /// **Source-controller resolution (I79 substrate).** Routes
    /// through `current_resolve_source_controller` with active_player
    /// fallback. Same shape as `PumpTargetCreatureUntilEOT`'s caster-
    /// side scan.
    ///
    /// **Snapshot ≤ 0 fizzle.** If the chosen target's effective power
    /// at resolve time is ≤ 0, no modifier is pushed (matches Python's
    /// `if snapshot <= 0: return` guard at `pump.py:235`). Doubling
    /// a 0/X creature is a no-op; doubling a -N power would invert via
    /// addition (subtracting again), which Python explicitly avoids.
    ///
    /// **Effective power read.** Uses the private
    /// `read_battlefield_creature_power` helper at
    /// `state_ops_resolve.rs:755` (already in place from the round-17
    /// Fight slice) — that helper inlines `effective_power` to dodge
    /// the per-slice file-isolation borrow split.
    ///
    /// **Schema simplification vs Python.** Unit variant on both
    /// sides; no fields beyond `kind`. Python's class has no
    /// constructor args either (`@dataclass(frozen=True)` with only
    /// inherited Effect fields).
    DoubleTargetCreaturesPowerUEOT,
    /// **BLOCKED-RUST-EFFECT slice (round 32) — deal damage to
    /// target creature an opponent controls equal to the number of
    /// artifacts the source's controller controls.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByArtifactCount`
    /// (`effects/generic/damage.py:406` — Warmaker Gunship's ETB; 1
    /// EoE consumer). First dynamic-X-from-permanent-count primitive
    /// in Rust — pre-positions the X-from-count plumbing for sister
    /// arms (e.g. damage-equal-to-creatures-you-control,
    /// X-equal-to-permanents-controlled).
    ///
    /// **Mechanism — count + apply.** At resolve time, count the
    /// source-controller's battlefield permanents whose printing's
    /// `card_types` contains "Artifact" (matches Python: lands that
    /// are also artifacts count, tokens like Lander count). If
    /// the count is ≤ 0 → silent fizzle. Otherwise apply that
    /// damage amount to the FIRST creature on any opponent's
    /// battlefield (mirrors `DealDamageToOpponentCreature`'s target
    /// shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors `DealDamageToOpponentCreature`'s shape — needs to
    /// resolve even if source has left bf, e.g. counterspelled
    /// trigger that still drives the count from the original ETB
    /// snapshot). If untrackable → silent fizzle.
    ///
    /// **Target semantics — first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent
    /// creature → silent fizzle.
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X is the whole point of the class).
    DealDamageToOpponentCreatureByArtifactCount,
    /// **BLOCKED-RUST-EFFECT slice (round 51) — Monoist Circuit-Feeder
    /// ETB (real EoE card; 14,727 17lands decks).** Until end of turn:
    /// a creature the source-controller controls gets `+X/+0`; a
    /// creature an opponent controls gets `-0/-X`; X = the number of
    /// artifacts the source-controller controls. Mirrors Python's NEW
    /// deterministic-pick class `PumpYoursAndDebuffOpponentByArtifact
    /// CountUntilEOT` (`effects/generic/pump.py` — shipped in this
    /// slice as the BRIDGE SIBLING of the agent-driven, two-required-
    /// target `PairedTargetPumpDebuffUEOT` that the real-card parser
    /// emits). This is the exact `FightTargetCreatureWithTargetCreature`
    /// (deterministic Rust unit-variant + deterministic Python bridge
    /// sibling) vs `EnchantedCreatureFightsTargetEffect` (agent-driven
    /// real-card class) precedent: the deterministic class exists
    /// purely as the cross-engine bridge target; the genuine real-EoE
    /// probe drives the actual parsed `PairedTargetPumpDebuffUEOT`
    /// constrained by a picker shim so the agent's two-target pick is
    /// forced to the FIRST own / FIRST opponent creature, byte-equal
    /// with this arm's deterministic scan.
    ///
    /// **Why this is NOT loader-admitted (§2 bridge-correctness).** The
    /// real Monoist Circuit-Feeder Python card parses to the
    /// AGENT-DRIVEN `PairedTargetPumpDebuffUEOT` (two REQUIRED targets,
    /// CR 601.2c; the controller freely picks ANY legal own creature +
    /// ANY legal opponent creature). Routing that through the
    /// production-deck loader's deterministic-first-creature bridge
    /// would SILENTLY degrade free agent targeting to a fixed
    /// first-creature pick in multi-creature board states — a §2
    /// silent-mistranslation. Per the Fight precedent (the
    /// deterministic `FightTargetCreatureWithTargetCreature` is NOT
    /// loader-admitted for any real card; Meltstrider's Resolve stays
    /// deferred), this slice ships the Effect arm + bridge sibling +
    /// GENUINE real-EoE probe but deliberately does NOT add a
    /// `_SAFE_*` loader admit. Documented in
    /// `docs/SEARCH_LIMITATIONS.md`.
    ///
    /// **Mechanism — count + apply.** At resolve time, resolve the
    /// source-controller (5-zone + stack scan; mirrors round-32
    /// `DealDamageToOpponentCreatureByArtifactCount` shape — must
    /// resolve even if the source has left bf). Count the
    /// source-controller's battlefield permanents whose printing's
    /// `card_types` contains "Artifact" (matches Python: artifact-lands
    /// and artifact tokens count). Clamp `x = count.max(0)`; if
    /// `x <= 0` → silent no-op (matches the round-32..49 X-from-count
    /// zero short-circuit and Python's `if x <= 0: return`). Otherwise:
    /// pick the source-side target = FIRST creature on the
    /// source-controller's bf (smallest Vec index); pick the
    /// opponent-side target = FIRST creature on the opponent's bf.
    /// Each side independently: if missing, that side is a silent
    /// no-op and the OTHER side still applies (CR 608.2c — two
    /// independent "target" clauses, NOT "up to one"; matches Python's
    /// per-slot independent apply). Apply an until-EOT
    /// `PowerToughnessBonus` modifier: source side `{ power: x,
    /// toughness: 0 }`; opponent side `{ power: 0, toughness: -x }`.
    /// End-of-turn cleanup is the existing UEOT-modifier expiry path.
    ///
    /// **Target semantics — first-slice deterministic.** Same
    /// first-creature-on-bf scan `FightTargetCreatureWithTargetCreature`
    /// / `PumpTargetCreatureUntilEOT` use (the established campaign
    /// no-decision-callback convention). The genuine real-EoE probe's
    /// picker shim mirrors this exact order on the agent-driven side.
    ///
    /// **Schema parity with Python.** Unit variant on both sides — X
    /// is computed from state at resolve time, not stored on the
    /// variant. Python's `@dataclass(frozen=True)` deterministic class
    /// has no constructor args. Mirrors the round-32..49 unit-variant
    /// schema convention.
    TwoSubjectPumpAndDebuffByArtifactCount,
    /// **BLOCKED-RUST-EFFECT slice (round 35) — deal damage to target
    /// creature an opponent controls equal to the number of cards in
    /// the source-controller's hand.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByCardsInHand`
    /// (`effects/generic/damage.py:464` — Roaring Furnace's door
    /// trigger; 1 EoE consumer). Sister of round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount` — same
    /// apply-substrate (damage-to-opponent-creature, first-eligible
    /// target, fizzle-on-empty-bf), NEW denominator (hand size in
    /// place of artifact count). Establishes a SECOND orthogonal
    /// X-from-count denominator on the same apply substrate, after
    /// round-32 / round-33 / round-34 walked the substrate axis with
    /// the artifact-count denominator.
    ///
    /// **Mechanism — count + apply.** At resolve time, count the
    /// source-controller's hand size (`state.players[idx].hand.len()`)
    /// — matches Python's `len(state.player_by_id(controller_id).hand)`
    /// at damage.py:511. Note: the source itself is NOT in the
    /// controller's hand at resolve time (it's already on the
    /// battlefield by the time the door trigger / ETB resolves), so a
    /// hand-of-N + the cast Room produces N damage, not N+1. If the
    /// hand size is ≤ 0 → silent fizzle. Otherwise apply that damage
    /// amount to the FIRST creature on any opponent's battlefield
    /// (mirrors `DealDamageToOpponentCreature` /
    /// `DealDamageToOpponentCreatureByArtifactCount` target shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 `DealDamageToOpponentCreatureByArtifactCount`
    /// shape — needs to resolve even if source has left bf, e.g.
    /// counterspelled trigger that still drives the count from the
    /// original ETB snapshot). If untrackable → silent fizzle.
    ///
    /// **Target semantics — first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent
    /// creature → silent fizzle. BIT-FOR-BIT identical to round-32's
    /// target shape (same apply substrate).
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X from hand size is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 unit-variant
    /// schema convention.
    DealDamageToOpponentCreatureByCardsInHand,
    /// **BLOCKED-RUST-EFFECT slice (round 36) — deal damage to target
    /// creature an opponent controls equal to the number of LANDS the
    /// source-controller controls.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByLandsControlled`
    /// (`effects/generic/damage.py` — shipped in this slice; no
    /// pre-existing class). Sister of round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount` and round-35's
    /// `DealDamageToOpponentCreatureByCardsInHand` — same
    /// apply-substrate (damage-to-opponent-creature, first-eligible
    /// target, fizzle-on-empty-bf), NEW denominator (lands-controlled
    /// in place of artifact-count / hand-size). Walks the
    /// X-from-count denominator axis to a THIRD entry after round-35
    /// established the bidirectionally-extensible plumbing across
    /// BOTH axes (substrate × denominator).
    ///
    /// **Mechanism — count + apply.** At resolve time, count the
    /// source-controller's lands on bf
    /// (`printing.card_types.iter().any(|t| t == "Land")`) — matches
    /// Python's `sum(1 for o in state.battlefield if o.controller_id ==
    /// controller_id and o.printing.is_land)` shape (mirrors the
    /// round-32 artifact-count denominator BIT-FOR-BIT, replacing
    /// "Artifact" with "Land"). Scryfall's `card_types` convention
    /// lists "Land" for any land (including non-basic lands; basic
    /// lands also carry "Land" as their sole entry; dual-typed
    /// artifact-lands carry both "Land" and "Artifact" -- they count
    /// for BOTH the artifact-count and the lands-controlled
    /// denominators, mirroring Scryfall's typeline conventions and
    /// Python's `is_land` / `is_artifact` disjunction at the printing
    /// level). If the lands count is ≤ 0 → silent fizzle. Otherwise
    /// apply that damage amount to the FIRST creature on any opponent's
    /// battlefield (mirrors `DealDamageToOpponentCreature` /
    /// `DealDamageToOpponentCreatureByArtifactCount` /
    /// `DealDamageToOpponentCreatureByCardsInHand` target shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 / round-35 sister shape — needs to resolve
    /// even if source has left bf, e.g. counterspelled trigger that
    /// still drives the count from the original ETB snapshot). If
    /// untrackable → silent fizzle.
    ///
    /// **Target semantics — first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent
    /// creature → silent fizzle. BIT-FOR-BIT identical to round-32's
    /// / round-35's target shape (same apply substrate).
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X from lands count is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35
    /// unit-variant schema convention.
    DealDamageToOpponentCreatureByLandsControlled,
    /// **BLOCKED-RUST-EFFECT slice (round 37) -- deal damage to target
    /// creature an opponent controls equal to the number of CREATURES
    /// the source-controller controls.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByCreaturesYouControl`
    /// (`effects/generic/damage.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount`, round-35's
    /// `DealDamageToOpponentCreatureByCardsInHand`, and round-36's
    /// `DealDamageToOpponentCreatureByLandsControlled` -- same
    /// apply-substrate (damage-to-opponent-creature, first-eligible
    /// target, fizzle-on-empty-bf), NEW denominator
    /// (creatures-controlled in place of artifact-count / hand-size /
    /// lands-controlled). Walks the X-from-count denominator axis to a
    /// FOURTH entry, completing the artifact / hand / lands / creatures
    /// quadruplet on this apply substrate. Confirms the round-35
    /// bidirectionally-extensible X-from-count plumbing generalizes
    /// across FOUR denominators on the same apply substrate.
    ///
    /// **Mechanism -- count + apply.** At resolve time, count the
    /// source-controller's creatures on bf
    /// (`printing.card_types.iter().any(|t| t == "Creature")`) --
    /// matches Python's `sum(1 for o in state.battlefield if
    /// o.controller_id == controller_id and o.printing.is_creature)`
    /// shape (mirrors the round-32 artifact-count denominator
    /// BIT-FOR-BIT, replacing "Artifact" with "Creature"). The
    /// source-controller's OWN creatures count toward the
    /// denominator (mirrors Python's vanilla `is_creature` walk over
    /// `state.battlefield` -- including the source if the source is a
    /// creature still on the bf). Dual-typed artifact-creatures count
    /// for BOTH the artifact-count and the creatures-controlled
    /// denominators independently (Scryfall lists both "Artifact" and
    /// "Creature" in card_types; Rust checks each type string
    /// independently in the relevant arm; Python's `is_artifact` and
    /// `is_creature` properties are independent disjunctions over
    /// `card_types`). If the creatures count is <= 0 -> silent
    /// fizzle. Otherwise apply that damage amount to the FIRST
    /// creature on any opponent's battlefield (mirrors
    /// `DealDamageToOpponentCreature` /
    /// `DealDamageToOpponentCreatureByArtifactCount` /
    /// `DealDamageToOpponentCreatureByCardsInHand` /
    /// `DealDamageToOpponentCreatureByLandsControlled` target shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 / round-35 / round-36 sister shape -- needs
    /// to resolve even if source has left bf, e.g. counterspelled
    /// trigger that still drives the count from the original ETB
    /// snapshot). If untrackable -> silent fizzle.
    ///
    /// **Target semantics -- first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent
    /// creature -> silent fizzle. BIT-FOR-BIT identical to round-32's
    /// / round-35's / round-36's target shape (same apply substrate).
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X from creatures count is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 unit-variant schema convention.
    DealDamageToOpponentCreatureByCreaturesYouControl,
    /// **BLOCKED-RUST-EFFECT slice (round 46) -- deal damage to target
    /// creature an opponent controls equal to the number of CARDS in
    /// the source-controller's GRAVEYARD.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByCardsInGraveyard`
    /// (`effects/generic/damage.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount`, round-35's
    /// `DealDamageToOpponentCreatureByCardsInHand`, round-36's
    /// `DealDamageToOpponentCreatureByLandsControlled`, and round-37's
    /// `DealDamageToOpponentCreatureByCreaturesYouControl` -- same
    /// apply-substrate (damage-to-opponent-creature, first-eligible
    /// target, fizzle-on-empty-bf), NEW denominator
    /// (cards-in-graveyard in place of artifact-count / hand-size /
    /// lands-controlled / creatures-controlled). Walks the X-from-count
    /// denominator axis to a FIFTH entry on the round-32 damage
    /// substrate, completing the artifact / hand / lands / creatures /
    /// graveyard quintuplet on this apply substrate. SIXTH overall
    /// X-from-count denominator across the substrate matrix (prior
    /// five: artifact-count / hand-size / lands-controlled /
    /// creatures-controlled / life-total -- round-42 mill uses life
    /// total). Confirms the round-35 bidirectionally-extensible
    /// X-from-count plumbing extends to a graveyard-zone-size
    /// denominator (the prior denominators all read from hand, bf, or
    /// life total -- graveyard is the FIRST zone-size denominator
    /// pulled from a NON-battlefield, NON-hand source).
    ///
    /// **Mechanism -- count + apply.** At resolve time, count the
    /// source-controller's graveyard size
    /// (`state.players[idx].graveyard.len()`) -- matches Python's
    /// `len(state.player_by_id(controller_id).graveyard)` shape. The
    /// source itself is on the battlefield at resolve time for an
    /// ETB-style trigger, so the source does NOT contribute to the
    /// denominator (it's not in the graveyard yet). For an LTB-style
    /// or graveyard-resolve trigger where the source is already in
    /// the graveyard, the source WOULD contribute +1 by virtue of
    /// having moved (no source-exclusion clause, mirroring round-32 /
    /// round-35 / round-36 / round-37 sister "vanilla walk -- no
    /// source-exclusion clause" convention). If the graveyard size is
    /// <= 0 -> silent fizzle. Otherwise apply that damage amount to
    /// the FIRST creature on any opponent's battlefield (mirrors
    /// `DealDamageToOpponentCreature` /
    /// `DealDamageToOpponentCreatureByArtifactCount` /
    /// `DealDamageToOpponentCreatureByCardsInHand` /
    /// `DealDamageToOpponentCreatureByLandsControlled` /
    /// `DealDamageToOpponentCreatureByCreaturesYouControl` target
    /// shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 / round-35 / round-36 / round-37 sister
    /// shape -- needs to resolve even if source has left bf, e.g.
    /// counterspelled trigger that still drives the count from the
    /// original ETB snapshot). If untrackable -> silent fizzle.
    ///
    /// **Target semantics -- first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent creature
    /// -> silent fizzle. BIT-FOR-BIT identical to round-32's /
    /// round-35's / round-36's / round-37's target shape (same apply
    /// substrate).
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X from graveyard size is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 unit-variant schema convention.
    DealDamageToOpponentCreatureByCardsInGraveyard,
    /// **BLOCKED-RUST-EFFECT slice (round 47) -- deal damage to target
    /// creature an opponent controls equal to the source-controller's
    /// LIFE TOTAL.** Mirrors Python's
    /// `DealDamageToOpponentCreatureByLifeTotal`
    /// (`effects/generic/damage.py` -- shipped in this slice; no
    /// pre-existing class). Sister of round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount`, round-35's
    /// `DealDamageToOpponentCreatureByCardsInHand`, round-36's
    /// `DealDamageToOpponentCreatureByLandsControlled`, round-37's
    /// `DealDamageToOpponentCreatureByCreaturesYouControl`, and
    /// round-46's `DealDamageToOpponentCreatureByCardsInGraveyard` --
    /// same apply-substrate (damage-to-opponent-creature,
    /// first-eligible target, fizzle-on-empty-bf), NEW denominator
    /// (source-controller's life total in place of artifact-count /
    /// hand-size / lands-controlled / creatures-controlled /
    /// graveyard-size). Walks the X-from-count denominator axis to a
    /// SIXTH entry on the round-32 damage substrate, COMPLETING the
    /// artifact / hand / lands / creatures / graveyard / life-total
    /// sextuplet on this apply substrate (the damage substrate is now
    /// the first fully-saturated row of the 6-substrate x 6-denominator
    /// X-from-count matrix). Confirms the round-35
    /// bidirectionally-extensible X-from-count plumbing extends to the
    /// life-total scalar denominator on the damage substrate (round-42
    /// already drove life-total on the mill substrate; this slice
    /// confirms the same scalar denominator generalizes onto the
    /// damage apply substrate).
    ///
    /// **Mechanism -- count + apply.** At resolve time, read the
    /// source-controller's life total
    /// (`state.players[idx].life`, an `i32`) and clamp negative life
    /// to zero (`life.max(0)`) -- matches Python's
    /// `max(0, state.player_by_id(controller_id).life)` clamp
    /// (mirrors the round-42 `MillTargetPlayerEqualToYourLifeTotal`
    /// `life.max(0)` precedent at state_ops_resolve.rs:1276; negative
    /// life arises only in arbitrary lose-life-past-zero / infect-
    /// style scenarios, an SBA would normally have ended the game --
    /// the clamp is a defensive silent no-op). If the clamped life is
    /// <= 0 -> silent fizzle. Otherwise apply that damage amount to
    /// the FIRST creature on any opponent's battlefield (mirrors
    /// `DealDamageToOpponentCreature` /
    /// `DealDamageToOpponentCreatureByArtifactCount` /
    /// `DealDamageToOpponentCreatureByCardsInHand` /
    /// `DealDamageToOpponentCreatureByLandsControlled` /
    /// `DealDamageToOpponentCreatureByCreaturesYouControl` /
    /// `DealDamageToOpponentCreatureByCardsInGraveyard` target shape).
    ///
    /// **Source-controller resolution.** 5-zone scan + stack scan
    /// (mirrors round-32 / round-35 / round-36 / round-37 / round-46
    /// sister shape -- needs to resolve even if source has left bf,
    /// e.g. counterspelled trigger that still drives the count from
    /// the original ETB snapshot). If untrackable -> silent fizzle.
    ///
    /// **Target semantics -- first-slice deterministic.** Iterate
    /// opponents in ascending player order; pick the FIRST creature
    /// on each opponent's bf (smallest Vec index). 2-player engine =
    /// exactly one opponent at `1 - controller`. No opponent creature
    /// -> silent fizzle. BIT-FOR-BIT identical to round-32's /
    /// round-35's / round-36's / round-37's / round-46's target shape
    /// (same apply substrate).
    ///
    /// **Schema parity with Python.** Unit variant on both sides --
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// only the inherited `targets` tuple; no static `amount` field
    /// (the dynamic-X from life total is the whole point of the
    /// class). Mirrors round-32 / round-33 / round-34 / round-35 /
    /// round-36 / round-37 / round-46 unit-variant schema convention.
    DealDamageToOpponentCreatureByLifeTotal,
    /// **BLOCKED-RUST-EFFECT slice (round 33) — put a +1/+1 counter
    /// on this creature for each OTHER creature and/or artifact you
    /// control.** Mirrors Python's
    /// `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`
    /// (`effects/generic/counters.py:394` — Luxknight Breacher's ETB,
    /// 1 EoE consumer). Second dynamic-X-from-permanent-count
    /// primitive in Rust (sister to round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount`); applies the
    /// X-from-count plumbing to the SELF-counter substrate instead
    /// of the opponent-creature damage substrate.
    ///
    /// **Mechanism — count + apply.** At resolve time, locate the
    /// source on a battlefield zone (mirrors `PutPlusOneCounterOnSelf`
    /// shape — round-23 precedent). Walk the source-controller's
    /// battlefield once; count permanents (other than the source
    /// itself) whose printing's `card_types` contains "Creature" OR
    /// "Artifact" (matches Python's `o.printing.is_creature or
    /// o.printing.is_artifact` disjunction at counters.py:417).
    /// Artifact-creatures count once (the `or` short-circuits — same
    /// as Python). If count ≤ 0 → silent fizzle. Otherwise add that
    /// many `+1/+1` counters to the source via `obj.counters
    /// .saturating_add(count)`.
    ///
    /// **Self exclusion.** The source is excluded from the count
    /// mid-loop (Python: `if o.id == source.id: continue`). Luxknight
    /// Breacher itself is on the bf when the ETB resolves, so without
    /// the exclusion the source would count itself as a +1.
    ///
    /// **Source-controller resolution.** Same shape as
    /// `PutPlusOneCounterOnSelf`'s round-23 battlefield-only scan
    /// (no 5-zone walk needed — the source MUST be on a battlefield
    /// zone for a "+1/+1 counter on this creature" effect to do
    /// anything; if it's gone, silent fizzle is correct). Owner /
    /// controller comes off the located GameObject's `controller`
    /// field, mirroring how `PutPlusOneCounterOnSelf` already locates
    /// its source.
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class has
    /// no constructor args (only the inherited `Effect` fields); the
    /// dynamic-X is the whole point of the class.
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    /// **BLOCKED-RUST-EFFECT slice (round 34) — surveil X, where X is
    /// the number of artifacts the source's controller controls.**
    /// Mirrors Python's `Surveil(use_artifact_count=True)`
    /// (`effects/generic/library_lookat.py:569` — Cerebral Download's
    /// "Surveil X, where X is the number of artifacts you control"
    /// clause; 1 EoE consumer). Third dynamic-X-from-permanent-count
    /// primitive in Rust (sister to round-32's
    /// `DealDamageToOpponentCreatureByArtifactCount` and round-33's
    /// `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`); applies
    /// the X-from-artifact-count denominator (same as round-32) to the
    /// SURVEIL substrate (round-15 `Effect::Surveil`).
    ///
    /// **Mechanism — count + apply.** At resolve time, count the
    /// source-controller's battlefield permanents whose printing's
    /// `card_types` contains "Artifact" (matches Python: lands that
    /// are also artifacts count, tokens like Lander count). Mirrors
    /// the round-32 `DealDamageToOpponentCreatureByArtifactCount`
    /// counting denominator BIT-FOR-BIT — same scan, same predicate,
    /// same `saturating_add` overflow guard. Then pop
    /// `min(count, library_len)` cards off the controller's library
    /// top into a `SurveilChoice` PendingDecision — IDENTICAL post-pop
    /// state shape to the round-15 `Effect::Surveil` resolve arm at
    /// `state_ops_resolve.rs:2692`. Mirrors Surveil's `count = 0`
    /// invariant: every Surveil emits exactly one PendingDecision
    /// (auto-resolve discards an empty SurveilChoice in O(1)) so the
    /// caller's "every Surveil emits exactly one PendingDecision"
    /// contract holds even when the controller has zero artifacts.
    ///
    /// **Source-controller resolution.** Try the
    /// `current_resolve_source_controller` transient slot first
    /// (mirrors round-15 `Effect::Surveil` shape — set by the
    /// resolve-time harness for triggers / cast effects). Fall back
    /// to a 5-zone scan + stack scan if the slot isn't stamped
    /// (mirrors `DealDamageToOpponentCreatureByArtifactCount`
    /// robustness for synthetic harnesses driving `apply_effect_pub`
    /// directly). Silent fizzle (zero-card SurveilChoice with the
    /// active player as controller) only if both fail — preserves the
    /// "always emit exactly one PendingDecision" contract.
    ///
    /// **Schema parity with Python.** Unit variant on both sides —
    /// the count is computed from state at resolve time, not stored
    /// on the variant. Python's `@dataclass(frozen=True)` class HAS
    /// fields (`amount: int = 1` and `use_artifact_count: bool =
    /// False`) but the dynamic-X variant is selected at construct
    /// time by `use_artifact_count=True`; the `amount` field is
    /// ignored on the dynamic lane. Rust's unit variant carries no
    /// fields — the dispatch happens on the variant tag, not a runtime
    /// flag, which is the same shape round-32 / round-33 use. The
    /// bridge translator constructs the Python class with
    /// `use_artifact_count=True` set, ignoring any `count` / `amount`
    /// field on the dict (mirrors round-32 / round-33's extra-key
    /// tolerance).
    SurveilXEqualToArtifactCount,
    /// **Round 28 highest-frequency-class coverage.** Run multiple
    /// effects in order as a single composite effect. Mirrors
    /// Python's `Sequence(effects: tuple[Effect, ...])`
    /// (`src/mtg_bot/effects/combinators.py:1314`) — 54 cards in the
    /// EoE pool use it (highest-frequency Python class not yet in
    /// Rust per r27 measurement).
    ///
    /// **Mechanism.** At resolve time, walks the `effects` Vec and
    /// calls `apply_effect` on each child in order with the same
    /// `source_obj_id`. Children share resolve-time state mutations
    /// (e.g. a `Sequence` of `[DrawCards{count:1}, DiscardSelf]`
    /// resolves to "draw, then discard" — a looting effect).
    ///
    /// **Targeting simplification.** Python's `Sequence` carries
    /// cast-time targeting machinery (at most one child may require
    /// a target; the target is passed to that child at resolve).
    /// The Rust first-slice does NOT carry cast-time target plumbing
    /// for nested effects — each child resolves with the same
    /// first-slice deterministic-target convention it uses on its own
    /// (e.g. `TapTarget{AnyCreature}` picks defender's bf[0],
    /// independent of the Sequence wrapper).
    ///
    /// **Recursion.** A Sequence can contain Sequences — the variant
    /// is fully nestable because `apply_effect` is a regular function
    /// and the `Vec<Effect>` type is heap-allocated.
    ///
    /// **Empty Sequence.** A `Sequence { effects: vec![] }` is a
    /// legal no-op (matches Python's empty-tuple-initialized
    /// Sequence).
    Sequence { effects: Vec<Effect> },
    /// **Round 28 UEOT-coverage extension.** Every creature on the
    /// source's controller's battlefield gets `+power/+toughness`
    /// until end of turn. Mirrors Python's
    /// `PumpCreaturesYouControlUntilEOT(power_bonus, toughness_bonus, ...)`
    /// (6 EoE cards — Stage-3 anthem-shape effects).
    ///
    /// **Mechanism.** Locate the source's controller; iterate that
    /// player's battlefield; for every object whose printing is a
    /// creature, push a `UeotModifier::PowerToughnessBonus` onto the
    /// object's `ueot_modifiers` Vec. Effective P/T queries pick up
    /// the bonus; cleanup-step expiration drains the modifiers at the
    /// end of the turn (CR 514.3 via the r27 UEOT framework).
    ///
    /// **Schema simplification.** Python's class also carries
    /// `granted_keywords`, `exclude_source`, `attacking_only`, and
    /// `also_untap_if_not_your_turn`. The Rust first slice carries
    /// ONLY power/toughness. Cards with riders wait for richer
    /// composition. Negative bonuses are legal (controller-side
    /// debuff pumps); `(0, 0)` is a legal no-op for parity edge cases.
    PumpCreaturesYouControlUntilEOT { power_bonus: i32, toughness_bonus: i32 },
    /// **Round 28 coverage extension.** Return the first creature card
    /// from the source-controller's graveyard to that player's hand.
    /// Mirrors Python's `ReturnCreatureFromYourGraveyardToHand`
    /// (`bounce.py:356` — 3 EoE cards).
    ///
    /// **First-slice deterministic target choice.** Same shape as the
    /// existing `ReturnCreatureFromYourGraveyardToBattlefield` arm —
    /// scans the active-player's graveyard front-to-back, picks the
    /// first creature card. Empty / no-creature graveyard fizzles
    /// silently.
    ///
    /// **Schema simplification.** Drops `max_mv` / `or_spacecraft` /
    /// `or_artifact` Python riders.
    ///
    /// **Zone-change reset (CR 400.7).** `tapped`, `summoning_sick`,
    /// `damage`, `counters` reset on move to hand. summoning_sick
    /// matches the round-28 CE1 universal-true default for hand-zone
    /// objects.
    ReturnCreatureFromYourGraveyardToHand,
    /// **Phase 5 rider-widened return-to-hand (Option B — additive
    /// bespoke arm).** Return the first creature OR artifact card
    /// from the source-controller's graveyard to that player's hand.
    /// Mirrors Python's
    /// `ReturnCreatureFromYourGraveyardToHand(or_artifact=True)`
    /// (`bounce.py:356`) — the rider widens the legal-target pool
    /// to admit artifact cards alongside creatures.
    ///
    /// **EoE consumer (audit).** Interceptor Mechan (EoE): "When this
    /// creature enters, return target artifact or creature card from
    /// your graveyard to your hand."
    ///
    /// **Filter contract.** A graveyard card qualifies iff its
    /// printing's `card_types` contains "Creature" OR "Artifact".
    /// (CR 400 / 506 — type predicates read off the printing's
    /// static card_types; the Rust registry stores card_types as
    /// the Scryfall type-line components on the LHS of the em-dash.)
    /// Sister artifact-creatures (printing carrying BOTH "Artifact"
    /// AND "Creature") match the disjunction at the first hit and
    /// are pulled. Cards with neither type are skipped. The scan
    /// preserves the unit-variant's iterator order
    /// (state.players[controller_idx].graveyard.iter().find_map),
    /// so test predictability matches the existing arm exactly.
    ///
    /// **Controller-of-effect.** Mirrors the I82 fix: source/dest
    /// derive from `current_resolve_source_controller`
    /// (falls back to active_player for direct apply_effect_pub
    /// callers). On p0's turn, p1's controlled trigger scans p1's
    /// graveyard and pushes to p1's hand.
    ///
    /// **Zone-change reset (CR 400.7).** Same as the bare unit
    /// variant: `tapped`, `summoning_sick`, `damage`, `counters`,
    /// `attached_to`, `exiled_with_source` all reset on move to hand.
    /// summoning_sick=true matches the round-28 CE1 universal-true
    /// default for hand-zone objects.
    ///
    /// **Schema simplification vs Python.** Drops `max_mv` and the
    /// other rider flags (`or_spacecraft`, `or_enchantment`,
    /// untargeted_all, plus_one_counter, log_suffix). The current
    /// EoE consumer pool needs the bare `or_artifact` widening only;
    /// richer Python axes re-enter as separate parametric Rust
    /// variants when their first real consumer arrives.
    ReturnArtifactOrCreatureFromYourGraveyardToHand,
    /// **Phase 5 rider-widened return-to-hand (Option B — additive
    /// bespoke arm).** Return the first creature OR Spacecraft card
    /// from the source-controller's graveyard to that player's hand.
    /// Mirrors Python's
    /// `ReturnCreatureFromYourGraveyardToHand(or_spacecraft=True)`
    /// (`bounce.py:356`) — the rider widens the legal-target pool
    /// to admit Spacecraft cards alongside creatures.
    ///
    /// **EoE consumer (audit).** Fell Gravship (EoE) suffix: "...
    /// then return a creature or Spacecraft card from your graveyard
    /// to your hand." (Composed inside a Sequence with mill-3 today;
    /// the bare arm here is the leaf-effect substrate.)
    ///
    /// **Filter contract.** A graveyard card qualifies iff EITHER
    /// its printing's `card_types` contains "Creature" OR its
    /// printing's `subtypes` contains "Spacecraft". Spacecraft is a
    /// SUBTYPE (an artifact subtype on the type line, e.g.
    /// "Artifact — Spacecraft"), not a card type — Python's
    /// `printing.is_spacecraft` reads off `"Spacecraft" in subtypes`
    /// at `cards.py` (Subtypes substrate). The Rust mirror reads
    /// `printing.subtypes.iter().any(|s| s == "Spacecraft")` directly
    /// off the static registry, matching the existing subject-has-
    /// subtype helpers at `cards.rs:2141`. No effective_subtypes
    /// layer yet (CR 613 layer 4 — type-modifying continuous
    /// effects). The disjunction is short-circuit: a creature-but-
    /// not-Spacecraft card pulls on the creature side; a Spacecraft-
    /// but-not-creature (e.g. an unactivated artifact-Spacecraft
    /// like Fell Gravship itself before Station) pulls on the
    /// Spacecraft side.
    ///
    /// **Controller-of-effect.** Mirrors the I82 fix: source/dest
    /// derive from `current_resolve_source_controller`. Same
    /// behavior as the bare unit variant and the
    /// or-artifact-rider variant.
    ///
    /// **Zone-change reset (CR 400.7).** Same as the sibling
    /// variants.
    ///
    /// **Schema simplification vs Python.** Drops `max_mv` and other
    /// rider flags (`or_artifact`, `or_enchantment`, untargeted_all,
    /// plus_one_counter, log_suffix). Bare `or_spacecraft` only.
    ReturnCreatureOrSpacecraftFromYourGraveyardToHand,
    /// **Phase 5 rider-widened return-to-hand (Option B — additive
    /// bespoke arm).** Return the first creature OR enchantment card
    /// from the source-controller's graveyard to that player's hand.
    /// Mirrors Python's
    /// `ReturnCreatureFromYourGraveyardToHand(or_enchantment=True)`
    /// (`bounce.py:356`) — the rider widens the legal-target pool
    /// to admit enchantment cards alongside creatures.
    ///
    /// **EoE consumer (audit).** Rescue Skiff (EoE) carries the
    /// "creature or enchantment card from your graveyard" rider on
    /// its ETB trigger but with the destination set to the
    /// battlefield (not hand); the destination-to-hand variant of
    /// the rider is the natural sibling of the existing
    /// `or_artifact` / `or_spacecraft` to-hand arms and lands here
    /// as part of the to-hand rider cluster. A separate
    /// `ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield`
    /// arm (mirror of this one with destination=battlefield) is the
    /// future slice that closes the loop on Rescue Skiff itself.
    ///
    /// **Filter contract.** A graveyard card qualifies iff its
    /// printing's `card_types` contains "Creature" OR "Enchantment".
    /// (CR 400 / 506 — type predicates read off the printing's
    /// static card_types; the Rust registry stores card_types as
    /// the Scryfall type-line components on the LHS of the em-dash.)
    /// Sister enchantment-creatures (printing carrying BOTH
    /// "Enchantment" AND "Creature") match the disjunction at the
    /// first hit and are pulled. Cards with neither type are
    /// skipped. The scan preserves the unit-variant's iterator
    /// order (`state.players[controller_idx].graveyard.iter().find_map`),
    /// so test predictability matches the existing arms exactly.
    ///
    /// **Controller-of-effect.** Mirrors the I82 fix: source/dest
    /// derive from `current_resolve_source_controller`
    /// (falls back to active_player for direct apply_effect_pub
    /// callers). On p0's turn, p1's controlled trigger scans p1's
    /// graveyard and pushes to p1's hand.
    ///
    /// **Zone-change reset (CR 400.7).** Same as the sibling
    /// variants: `tapped`, `summoning_sick`, `damage`, `counters`,
    /// `attached_to`, `exiled_with_source` all reset on move to
    /// hand. summoning_sick=true matches the round-28 CE1
    /// universal-true default for hand-zone objects.
    ///
    /// **Schema simplification vs Python.** Drops `max_mv` and the
    /// other rider flags (`or_artifact`, `or_spacecraft`,
    /// untargeted_all, plus_one_counter, log_suffix). Bare
    /// `or_enchantment` only.
    ReturnEnchantmentOrCreatureFromYourGraveyardToHand,
    /// **Round 28 coverage extension.** Put `amount` +1/+1 counter(s)
    /// on each creature the source's controller controls. Mirrors
    /// Python's `PutPlusOneCounterOnEachCreatureYouControl(amount: int = 1)`
    /// (counters.py:737 — Atmospheric Greenhouse-shape, 3 EoE cards).
    ///
    /// **Mechanism.** Locate source controller; iterate that player's
    /// battlefield; for every creature, add `amount` to the per-object
    /// `counters` scalar (the same single-scalar counter the existing
    /// PutPlusOneCounterOnSelf / AddCounters arms use — G8 multi-kind
    /// counter map is still future work). Non-creature permanents are
    /// skipped. (0) is a legal no-op; negative `amount` raises.
    ///
    /// **Schema simplification vs Python.** Drops the `exclude_source`
    /// rider ("each OTHER creature you control" — skips the triggering
    /// permanent). Cards with that rider compose via separate effect
    /// chains for now.
    PutPlusOneCounterOnEachCreatureYouControl { amount: i32 },
    /// **Round 28 coverage extension.** Put `amount` +1/+1 counter(s)
    /// on a target creature the source's controller controls. Mirrors
    /// Python's `PutPlusOneCounterOnCreatureYouControl(amount: int = 1)`
    /// (counters.py:844 — Rayblade-Trooper-shape, 3 EoE cards).
    ///
    /// **First-slice deterministic target choice.** Same shape as
    /// `PumpTargetCreatureUntilEOT`: pick the FIRST creature on the
    /// source-controller's battlefield (zone-iteration order). Empty
    /// battlefield or no eligible creatures = silent fizzle.
    ///
    /// **Schema simplification.** Python's class composes via the
    /// `PutPlusOneCounters` base which carries a `targets` filter
    /// (IsCreature & ControlledByYou). The Rust first slice carries
    /// the implicit shape via the resolve arm's selection logic.
    /// negative `amount` raises; `amount=0` is a legal no-op.
    PutPlusOneCounterOnCreatureYouControl { amount: i32 },
    /// **Round 28 coverage extension.** Add `amount` mana of a single
    /// color chosen by the controller at resolution time. Mirrors
    /// Python's `AddNManaOfChosenColor(amount: int, options: tuple[str, ...])`
    /// (`mana.py:85` — Lotus-Field-shape, 4 EoE cards: "Add three mana
    /// of any one color").
    ///
    /// **First-slice deterministic color choice.** Picks `options[0]`
    /// (first available color, default `"W"`). Mirrors Python's
    /// "first color in options" deterministic fallback when no agent
    /// is seated. Future decision-callback slice plumbs the explicit
    /// player choice through the pending_decisions queue.
    ///
    /// **Schema.** `amount: i32` and `options: Vec<String>` (default
    /// WUBRG). Empty options Vec is illegal; non-WUBRGC entries
    /// raise. amount<0 raises at parse + apply. amount=0 is a legal
    /// no-op (no color minted).
    AddNManaOfChosenColor { amount: i32, options: Vec<String> },
    /// **Round 28 coverage extension.** Search the source-controller's
    /// library for a card matching `filter_name`, reveal it, put it
    /// into that player's hand. Mirrors Python's
    /// `SearchLibraryForCard(filter_name, max_mv=0, may_fail=True)`
    /// (`search.py:30` — 9 EoE cards).
    ///
    /// **Filter vocabulary** (post Round-30 supertypes/subtypes
    /// substrate). Rust dispatches on the same string set Python does
    /// at `search.py:_matches` — arm-for-arm parity:
    ///   - `"basic_land"` → `card_types` contains `"Land"`
    ///     (legacy proxy; the historical reason was the missing
    ///     supertypes field, which the Round-30 substrate now carries.
    ///     Kept on the legacy proxy because every EoE basic land has
    ///     `card_types=["Land"]` with no compound non-basic land
    ///     routing this dispatch path, and changing the proxy now
    ///     would break in-flight fixtures whose CardDef omits the
    ///     supertypes hint).
    ///   - `"basic_plains"` / `"basic_island"` / `"basic_swamp"` /
    ///     `"basic_mountain"` / `"basic_forest"` → `printing.name`
    ///     equals the canonical basic name.
    ///   - `"creature_small"` (with `max_mv`) → `card_types` contains
    ///     `"Creature"` AND `mana_cost.total() <= max_mv`. `max_mv=0`
    ///     means "creatures with cost <= 0" (rarely matches; specify
    ///     a real `max_mv` value).
    ///   - `"artifact"` → `card_types` contains `"Artifact"`.
    ///   - `"legendary_creature"` → `card_types` contains `"Creature"`
    ///     AND `supertypes` contains `"Legendary"` (Round-30
    ///     substrate; powers The Seriema's tutor + Starfield Shepherd's
    ///     dual-clause inner half).
    ///   - `"spacecraft"` → `subtypes` contains `"Spacecraft"`
    ///     (Round-30 substrate).
    ///   - `"sliver"` → `subtypes` contains `"Sliver"` (Round-30
    ///     substrate).
    ///   - `"demon"` → `subtypes` contains `"Demon"` (Round-30
    ///     substrate; powers Demonic Counsel from Duskmourn).
    ///   - unknown filter → silent fizzle (matches Python's
    ///     `_matches` returning False for unknown).
    ///
    /// **Deterministic first-match pick (top-to-bottom).** Library
    /// Vec is bottom-first (lib[len-1] = top); scan via `iter().rev()`.
    /// Real MTG lets the player choose any matching card; deferred
    /// until decision callbacks exist.
    ///
    /// **No shuffle.** Same deferral as
    /// `SearchLibraryForBasicLandTapped` — CR 701.19 mandates shuffle
    /// but the Rust port hasn't externalized RNG yet (G19).
    ///
    /// **`may_fail` flag.** Python's flag controls whether the
    /// controller may choose to skip the fetch. The Rust first-slice
    /// always fetches if a match exists (deterministic choice); the
    /// flag is preserved on the variant for parity round-trip but
    /// not consulted at apply time.
    SearchLibraryForCard {
        filter_name: String,
        max_mv: i32,
        may_fail: bool,
    },
    /// **Round 28 coverage extension.** Every creature on the
    /// source's controller's OPPONENTS' battlefields gets
    /// `+power/+toughness` until end of turn. Mirror of
    /// `PumpCreaturesYouControlUntilEOT` but with the opponent-target
    /// orientation. 2 EoE cards use this shape — debuff anthem.
    ///
    /// **Two-player simplification.** In the current engine,
    /// "opponents" reduces to "the one opponent" = `1 - controller`.
    /// Iterates that player's battlefield; for every creature, push
    /// a `UeotModifier::PowerToughnessBonus`. Negative bonuses are
    /// the typical use case (controller-side curse-shape effects
    /// that shrink the enemy creatures); positive bonuses are
    /// inexpressible in real-life MTG but the variant accepts
    /// them for parity edge cases.
    ///
    /// **Same UEOT cleanup semantics** as PumpSelfUntilEOT — the
    /// modifier auto-expires at the next CR 514.3 cleanup-step pass.
    /// `(0, 0)` short-circuits; empty opponent bf fizzles silently.
    PumpCreaturesOpponentsControlUntilEOT { power_bonus: i32, toughness_bonus: i32 },
    /// **Mouth-of-the-Storm sibling — extended-duration variant.**
    /// Same shape as `PumpCreaturesOpponentsControlUntilEOT` (mass
    /// +/-power / +/-toughness on every creature controlled by the
    /// source-controller's opponents) but the printed duration is
    /// "until your next turn" rather than the bare "until end of
    /// turn". The Python sibling
    /// `PumpCreaturesOpponentsControlUntilEOT(until_caster_next_turn=
    /// True, ...)` writes the modifier through
    /// `grant_pt_pump_until_player_next_turn` (layer-7c registry
    /// entry tagged `expires_at="controller_untap"`,
    /// `expires_at_player_id` = source-controller); the modifier
    /// survives the casting turn's cleanup AND the opponent's full
    /// subsequent turn, expiring only at the start (`run_untap_step`)
    /// of the source-controller's next turn.
    ///
    /// **Real-EoE consumer:** Mouth of the Storm
    /// (EoE Creature, {6}{U} Elemental):
    ///   "When this creature enters, creatures your opponents
    ///    control get -3/-0 until your next turn."
    ///
    /// **Substrate-only first slice — cleanup-gate divergence
    /// deferred.** The current `UeotModifier` enum is implicitly
    /// `expires_at = "cleanup"` (drained wholesale by
    /// `clear_ueot_modifiers_all`/`cleanup_step_for_active_player`);
    /// adding a tagged-lifetime field cascades through the four
    /// effective-P/T / effective-keyword readers in `state.rs`,
    /// the two cleanup primitives, and a new untap-step hook.
    /// That cascade is out of this slice's budget. The first-slice
    /// resolve arm pushes the SAME `UeotModifier::PowerToughnessBonus`
    /// the bare sibling pushes — the post-resolve effective-P/T
    /// observable matches the bare sibling exactly. The divergence
    /// (Python keeps the debuff into the opponent's turn; Rust
    /// drops it at the casting-turn cleanup) is documented in
    /// `docs/SEARCH_LIMITATIONS.md` and is a follow-up Rust slice
    /// (the parametric duration field on `UeotModifier`).
    ///
    /// The discriminator-only sibling matters NOW because:
    ///   1. The bridge can route Mouth of the Storm cleanly
    ///      (extended-duration variant -> Python's
    ///      `until_caster_next_turn=True`).
    ///   2. Once the cleanup-gate slice lands, only THIS variant's
    ///      resolve arm changes — every call site, every parse arm,
    ///      every test pin already targets the right discriminator.
    ///
    /// `(0, 0)` short-circuits; empty opponent bf fizzles silently
    /// (mirrors the bare sibling).
    PumpCreaturesOpponentsControlUntilCasterNextTurn {
        power_bonus: i32,
        toughness_bonus: i32,
    },
    /// **Round 28 coverage extension.** Put a target card from a
    /// graveyard on the bottom of its owner's library. Mirrors
    /// Python's `PutCardFromGraveyardOnBottomOfLibrary`
    /// (`graveyard.py:420` — Chrome-Companion-shape, 2 EoE cards).
    ///
    /// **First-slice deterministic target choice.** Scans graveyards
    /// in player-order (p0 first, then p1). Takes the FIRST card
    /// encountered (`graveyard[0]` if non-empty). Real MTG lets the
    /// activating player choose any card in any graveyard; deferred
    /// until decision callbacks exist.
    ///
    /// **Zone-change reset (CR 400.7).** tapped, summoning_sick,
    /// damage, counters reset on move. summoning_sick=true per r28
    /// CE1 universal default (library zone, gameplay-irrelevant).
    ///
    /// **"Bottom of library" = `lib[len-1]`** post-CE3 (lib[0] = top,
    /// tail = bottom). Append via `lib.push(...)`.
    ///
    /// Empty-graveyards-on-both-sides = silent fizzle.
    PutCardFromGraveyardOnBottomOfLibrary,
    /// **Round 28 coverage extension.** Move all +1/+1 counters from
    /// the source to the first creature on the source-controller's
    /// battlefield. Mirrors Python's
    /// `MoveSelfCountersToTargetCreatureYouControl` (`counters.py:263`
    /// — Dockworker-Drone-shape dies trigger, 2 EoE cards).
    ///
    /// **Mechanism.** Locate source's `counters` scalar; if zero
    /// or source isn't found, silent no-op. Locate first creature on
    /// source-controller's battlefield (zone-iteration order, gates
    /// on `card_types contains "Creature"`). Transfer: subtract from
    /// source's counters (= 0 after transfer), add same amount to
    /// target's counters. Source-not-on-bf path silent fizzle.
    ///
    /// **Semantics — true "move" not "copy".** Source's counters are
    /// cleared on transfer. Python's resolve doesn't subtract from
    /// source because by trigger-time the source is typically in
    /// graveyard (counters are gone with it). The Rust port models
    /// the cleaner "move" semantics: if source still exists with
    /// counters, transfer + clear. Documented divergence for dies-
    /// trigger interactions.
    ///
    /// **First-slice deterministic target choice.** First creature
    /// on source-controller's bf. Real MTG lets the player choose;
    /// deferred until decision callbacks.
    MoveSelfCountersToTargetCreatureYouControl,
    /// **Round 28 coverage extension.** Deal damage equal to the
    /// source's effective power to any target (mirrors Python's
    /// `DealDamageEqualToSourcePowerAnyTarget` — 2 EoE cards,
    /// Mishra's Bauble-style power-scaling damage spells).
    ///
    /// **Mechanism.** Locate the source on the battlefield; read its
    /// effective power (printed + UEOT bonus); deal that many damage
    /// to the first eligible target (defender's first creature, else
    /// defender-as-player — mirrors `DealDamageAnyTarget`'s target
    /// selection shape). If source isn't on battlefield (e.g. spell
    /// resolving and source is on stack), effective power is 0 → no
    /// damage dealt. Source with effective power 0 is a legal no-op.
    /// Source with negative effective power is treated as 0 damage
    /// (defensive — Python clamps at 0).
    DealDamageEqualToSourcePowerAnyTarget,
    /// **Round 28 coverage extension.** Tap target artifact or
    /// creature. Mirrors Python's `TapTargetArtifactOrCreature(Tap)`
    /// (`tap.py:324` — 2 EoE cards).
    ///
    /// **First-slice deterministic target choice.** Same shape as
    /// the existing `Effect::TapTarget { target: AnyCreature }` arm
    /// (defender's first eligible permanent), but the filter
    /// includes Artifact OR Creature instead of just Creature.
    /// Idempotent on already-tapped target (silent no-op). Empty /
    /// no-eligible defender bf → silent fizzle.
    TapTargetArtifactOrCreature,
    /// **Round 28 coverage extension.** Run `effect` only if the
    /// source's controller has at least `min_count` tapped creatures
    /// on their battlefield. Mirrors Python's
    /// `ConditionalOnTappedCreatures(effect, min_count=2)`
    /// (`combinators.py:1007` — Flight-Deck-Coordinator-shape
    /// intervening-if clause, 6 EoE cards).
    ///
    /// **Mechanism.** At resolve time, locate source controller;
    /// count tapped creatures on that player's battlefield; if
    /// `count >= min_count`, recursively call `apply_effect` on the
    /// nested effect with the same source_obj_id. Otherwise silent
    /// no-op (matches Python's "skipped" log line).
    ///
    /// **Recursion.** Box<Effect> for the nested effect — Effect is
    /// heap-allocated so the recursion is safe (same shape as
    /// Sequence's Vec<Effect>).
    ///
    /// **Schema.** `effect` required; `min_count` defaults to 2.
    /// Negative min_count is legal (always-fires) but ill-formed
    /// from a parity perspective; min_count=0 always fires.
    ConditionalOnTappedCreatures { effect: Box<Effect>, min_count: i32 },
    /// **Round 28 coverage extension.** Put a +1/+1 counter on each
    /// of up to `max_n` target creatures. Mirrors Python's
    /// `PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)`
    /// (`counters.py:179` — Weftblade-Enhancer-shape, 2 EoE cards).
    ///
    /// **First-slice deterministic target choice.** Scans
    /// battlefields in player order (source controller first, then
    /// opponent); picks the first min(max_n, eligible_count)
    /// creatures encountered. Real MTG lets the player pick ANY
    /// creature (either side); deferred until decision callbacks.
    /// Empty / no-eligible-creatures fizzles silently.
    ///
    /// **Schema.** `max_n` defaults to 2. Negative max_n is illegal
    /// and raises at parse. max_n=0 is a legal no-op.
    PutPlusOneCounterOnEachOfUpToNTargetCreatures { max_n: i32 },
    /// **Round 28 coverage extension.** Put `amount` charge counters
    /// on the resolving source. Mirrors Python's
    /// `PutChargeCountersOnSelf(amount=1, amount_from_x=False)`
    /// (`counters.py:549` — Blast-Zone-shape, 2 EoE cards).
    ///
    /// **Single-counter-slot simplification.** Rust's per-object
    /// `counters` scalar doesn't distinguish +1/+1 vs charge vs
    /// loyalty (G8 multi-kind counter map is future work). For
    /// gameplay purposes today, charge counters route to the same
    /// counter slot as +1/+1. Future G8 closure will split these.
    ///
    /// **`amount_from_x` deferred.** Python's flag reads
    /// `state.resolving_x_value` (X-cost spell pattern). Rust
    /// doesn't track X values today; the flag is preserved on the
    /// variant for round-trip but `amount_from_x=true` resolves to
    /// 0 (silent no-op). Future X-cost work flips this.
    ///
    /// **Schema.** `amount` defaults to 1; negative raises at parse;
    /// `amount_from_x` defaults to false.
    PutChargeCountersOnSelf { amount: i32, amount_from_x: bool },
    /// **Round 28 coverage extension.** Create a token that's a copy
    /// of a target creature the source's controller controls. Mirrors
    /// Python's `CreateTokenCopyOfTargetCreatureYouControl`
    /// (`tokens.py:316` — Mirrorpool-shape, 2 EoE cards).
    ///
    /// **First-slice copy semantics.** New GameObject allocated with
    /// the SAME `printing_id` as the target. zone=BATTLEFIELD,
    /// controller = source-controller, summoning_sick=true (token
    /// ETBs sick), other per-object state zeroed. Future slices add
    /// the Token supertype + additional_subtype injection once Rust
    /// has supertype/subtype tracking.
    ///
    /// **First-slice deterministic target.** First creature on
    /// source-controller's bf (same shape as PumpTargetCreatureUntilEOT
    /// et al.). Empty / no eligible target = silent fizzle.
    ///
    /// **Python field drop.** Python's `additional_subtype` field is
    /// deferred (Rust has no subtypes on registry yet).
    CreateTokenCopyOfTargetCreatureYouControl,
    /// **Round 28 coverage extension.** "You may sacrifice an
    /// artifact. If you do, [inner_effect]." Mirrors Python's
    /// `OptionalSacArtifactForEffect` (`combinators.py:299` —
    /// Lithobraking-shape, 2 EoE cards).
    ///
    /// **First-slice deterministic-yes.** Python's default
    /// base-Agent behavior is "yes" (always sac if able). Rust
    /// mirrors that: if source's controller controls at least one
    /// artifact on the battlefield, sacrifice the FIRST one (move
    /// to controller's graveyard with CR 400.7 zone-change reset)
    /// AND apply the inner effect with the same source_obj_id.
    /// If no artifact is available, no-op (no inner effect either —
    /// matches Python's "if not options: return").
    ///
    /// **Recursion.** Box<Effect> for inner; recursive apply_effect.
    OptionalSacArtifactForEffect { inner_effect: Box<Effect> },
    /// **Round 28 coverage extension.** "Target artifact or
    /// creature's owner puts it on top or bottom of their library."
    /// Python class:
    /// `OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`
    /// (`effects/generic/zone_moves.py:30`). 2 EoE cards.
    ///
    /// **First-slice deterministic-bottom.** Python's resolve calls
    /// `owner.agent.choose_mode("top", "bottom")`. Rust has no
    /// decision-callback substrate yet; we deterministically pick
    /// BOTTOM. A reasonable first-slice mirror because
    /// decision-callback agents typically default-pick the bottom
    /// option when offered top/bottom (least disruptive). Future
    /// slice with `pending_decisions` can promote this to a real
    /// choice.
    ///
    /// **Owner-as-controller simplification.** Python tracks
    /// `owner_id` separately from controller. Rust currently has
    /// no owner field on GameObject; we treat the target's
    /// `controller` as the owner. First-slice synthetic states
    /// never split owner from controller, so this is exact for the
    /// test universe.
    ///
    /// **Target selection.** First defender (= 1 - active_player)
    /// permanent whose printing's card_types contains "Artifact"
    /// OR "Creature". No eligible target = silent fizzle.
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    /// **Round 28 coverage extension.** "Attach this Equipment to
    /// target creature you control." Mirrors Python's
    /// `AttachToTargetCreatureYouControl`
    /// (`effects/generic/attach.py`), the EoE-Equipment ETB shape
    /// (Atomic Microsizer, Illvoi Light Jammer, Squire's Lightblade,
    /// etc. — 5 EoE cards).
    ///
    /// **First-slice deterministic target.** First creature on the
    /// source-controller's battlefield. Same shape as
    /// PumpTargetCreatureUntilEOT and friends. Empty bf / no
    /// eligible creature → silent fizzle (matches Python's
    /// `if target is None: return`).
    ///
    /// **First-slice scope.** Drops Python's `granted_keywords_ueot`
    /// rider (Squire's Lightblade-style "...and target creature
    /// gains first strike UEOT") — Rust doesn't yet need the rider
    /// for the parity rounds the orchestrator is closing. Drops
    /// Python's "is Equipment" subtype gate too: Rust doesn't track
    /// subtypes on the registry yet, so the effect is gated solely
    /// by what cards print it (only Equipment cards print
    /// `AttachToTargetCreatureYouControl` in EoE).
    ///
    /// **Sets source's `attached_to`.** Looks the source up on the
    /// source-controller's battlefield (an Equipment ETB resolution
    /// happens AFTER the Equipment is on the bf — CR 603.6a), finds
    /// the first creature on that same battlefield, and stamps
    /// `source.attached_to = Some(target_id)`.
    AttachToTargetCreatureYouControl,
    /// **Round 29 coverage extension.** "Equip [cost]:" activated-
    /// ability resolution per CR 702.6. Mirrors Python's
    /// `EquipToTargetCreatureYouControl`
    /// (`effects/generic/attach.py:117`), the activated-ability
    /// sibling of `AttachToTargetCreatureYouControl` (Atomic
    /// Microsizer family — 14 EoE cards, the highest-frequency
    /// in-pool Effect class still missing from Rust).
    ///
    /// **Semantics identical to `AttachToTargetCreatureYouControl`.**
    /// Re-targets the source Equipment onto a creature the
    /// controller controls, replacing any prior attachment by
    /// overwriting `source.attached_to`. The distinct variant exists
    /// for logging/diagnostics parity with Python (`describe`
    /// returns "equip: ..." vs the ETB attach's "attach this
    /// Equipment to ..."): a tooling consumer reading
    /// `effect_to_pydict` can tell ETB-attach from a paid Equip
    /// activation. The resolve mutation itself is identical.
    ///
    /// **First-slice deterministic target.** First creature on the
    /// source-controller's battlefield that isn't the source
    /// itself. Same shape as the Attach variant.
    ///
    /// **First-slice scope.** Drops the granted-keywords rider
    /// (the Python parent class accepts one, but `EquipToTargetCreatureYouControl`
    /// passes the default empty frozenset — equip activations
    /// don't carry UEOT keyword grants on EoE cards).
    EquipToTargetCreatureYouControl,
    /// **Round 28 coverage extension.** Destroy the permanent that
    /// the resolving aura is enchanting. Mirrors Python's
    /// `DestroyEnchantedPermanent` (`destroy.py:213` — Cryoshatter
    /// shape, 4 EoE cards).
    ///
    /// **Reads source's `attached_to`.** The source (typically an
    /// aura/enchantment with a triggered ability) must be on a
    /// battlefield with `attached_to = Some(target_id)`. Source not
    /// on bf, or `attached_to` is None, or the target isn't on a
    /// battlefield → silent fizzle.
    ///
    /// **Mechanism.** Find target by id across both battlefields;
    /// remove from its zone; CR 400.7 zone-change reset (tapped,
    /// summoning_sick, damage, counters, attached_to); push to its
    /// controller's graveyard.
    DestroyEnchantedPermanent,
    /// **Round 28 coverage extension.** Tap the permanent the
    /// resolving aura is attached to. Mirror of
    /// `DestroyEnchantedPermanent` (same target lookup via
    /// `attached_to`) but uses the tap mutation instead of zone
    /// change. 2 EoE cards. Idempotent on already-tapped target.
    /// Source not on bf / no host / target untracked → silent
    /// fizzle.
    TapEnchantedPermanent,
    /// **Round-30 stun-counter substrate.** Put a stun counter on
    /// up to one target tapped creature. Mirrors Python's
    /// `PutStunCounterOnTappedCreature` (`counters.py:592` — Cryogen
    /// Relic activated half, 1 EoE card).
    ///
    /// **First-slice deterministic target.** Walks both players'
    /// battlefield in ETB-timestamp order and picks the FIRST
    /// already-tapped creature it finds (regardless of controller —
    /// the Python class places no controller restriction; "up to one
    /// target tapped creature"). No eligible target (empty bf or no
    /// tapped creatures) → silent fizzle. Real MTG lets the controller
    /// pick any tapped creature; deferred until decision callbacks
    /// extend to this Effect.
    ///
    /// **Mechanism.** On the matched object, increment
    /// `stun_counters` by 1 via `Arc::make_mut` on the target's
    /// battlefield Vec. The CR 701.20 untap-step gate is wired in
    /// `state_ops_steps.rs:untap_all_for_player_inline` (decrement
    /// instead of untap when `stun_counters > 0`).
    PutStunCounterOnTappedCreature,
    /// **Round-30 stun-counter substrate.** Tap target artifact or
    /// creature an opponent controls and put a stun counter on it.
    /// Both effects apply to the SAME chosen target. Mirrors Python's
    /// `TapTargetOpponentPermanentAndStunIt` (`tap.py:217` —
    /// Mechanozoa ETB, 1 EoE card).
    ///
    /// **First-slice deterministic target.** Walks both players'
    /// battlefield in ETB-timestamp order and picks the FIRST
    /// (Artifact OR Creature) permanent NOT controlled by the
    /// source's controller. No eligible target → silent fizzle.
    ///
    /// **Mechanism.** Tap the target (idempotent on already-tapped)
    /// and increment `stun_counters` by 1. Same target for both
    /// mutations — the Python class's docstring is explicit that
    /// "both effects apply to the same chosen target".
    TapTargetOpponentPermanentAndStunIt,
    /// **Round 28 coverage extension.** Exile target creature until
    /// the source leaves the battlefield. Mirrors Python's
    /// `ExileTargetCreatureUntilSourceLeaves` (`effects/generic/exile.py:504`
    /// — All-Fates Stalker / Hardlight Containment ETB, 3 EoE cards).
    ///
    /// **First-slice deterministic target.** First creature on the
    /// defender's (= 1 - active_player) battlefield. Real MTG lets
    /// the controller pick any creature; deferred until decision
    /// callbacks exist. Drops Python's `excluded_subtypes` /
    /// `opponents_only` / `yours_only` filter knobs.
    ///
    /// **Mechanism.** Stamp target's `exiled_with_source =
    /// Some(source_id)` before moving to exile (CR 400.7 zone-change
    /// reset for all other per-object state). The link is consumed
    /// by `return_paired_exiles_for(source_id)` — a manual pymethod
    /// for the harness/Effect to call when the source leaves bf.
    /// Auto-firing the return is a follow-up slice; for now the
    /// link is stamped but the return must be triggered manually.
    ExileTargetCreatureUntilSourceLeaves,
    /// **Round 28 coverage extension.** Exile a non-land permanent
    /// an opponent controls until source leaves the battlefield.
    /// Mirrors Python's `ExileOpponentsNonlandPermanentUntilLeaves`
    /// (`effects/generic/exile.py:588` — 4 EoE cards).
    ///
    /// **First-slice deterministic target.** First permanent on the
    /// defender's bf whose card_types do NOT contain "Land".
    /// Defender = 1 - active_player (first-slice owner-as-controller
    /// shape). No eligible target → silent fizzle.
    ///
    /// **Mechanism** is the same as ExileTargetCreatureUntilSourceLeaves:
    /// stamp target's `exiled_with_source = Some(source_id)` and move
    /// to owner's exile. Manual return via
    /// `return_paired_exiles_for(source_id)`.
    ExileOpponentsNonlandPermanentUntilLeaves,
    /// **Round 14 rider-widened "until leaves" exile (additive
    /// sibling variant — Option B).** Same shape as
    /// `ExileOpponentsNonlandPermanentUntilLeaves` but admits a
    /// `max_mv` mana-value cap on the target permanent. Mirrors
    /// Python's
    /// `ExileOpponentsNonlandPermanentUntilLeaves(max_mv=N)` rider
    /// (`effects/generic/exile.py:587`) — `max_mv > 0` restricts
    /// the legal-target pool to permanents with mana value ≤
    /// `max_mv`; the bare-shape sibling above (no `max_mv`) handles
    /// the no-cap case.
    ///
    /// **EoE consumer (audit).** Seam Rip (EoE) — "When this
    /// enchantment enters, exile target nonland permanent an
    /// opponent controls with mana value 2 or less until this
    /// enchantment leaves the battlefield." Carrier Enchantment
    /// at `{W}`. The capped variant differs from the bare-shape
    /// Banishing Light / Hardlight Containment shape only in the
    /// per-permanent MV cap on the legal-target pool.
    ///
    /// **First-slice deterministic target.** First permanent on the
    /// defender's bf whose `card_types` does NOT contain "Land" AND
    /// whose printing's mana value is ≤ `max_mv`. CR 117.x: mana
    /// value reads off the printing's static mana cost (Rust:
    /// `printing.mana_cost.total()`); X-cost cards count X as 0
    /// while in exile / graveyard / library / hand, matching the
    /// printed-cost reading. No eligible permanent → silent fizzle
    /// (e.g. defender's bf is empty, all bf permanents are lands,
    /// or all non-land permanents have MV > max_mv).
    ///
    /// **Mechanism.** Identical to the bare sibling: stamp
    /// `exiled_with_source = Some(source_obj_id)` on the moved
    /// object, push to owner's exile zone, queue
    /// `pending_leaves_dispatches` for LTB fan-out. Manual return
    /// via `return_paired_exiles_for(source_id)`. CR 400.7
    /// zone-change reset (tapped, summoning_sick=true per r28 CE1,
    /// damage, counters, attached_to) preserved.
    ///
    /// **Controller-of-effect.** Mirrors the I80 fix on the bare
    /// sibling: `controller = current_resolve_source_controller`
    /// (with `active_player` fallback); `defender = 1 - controller`.
    /// On p0's turn, p1's controlled trigger exiles a P0 permanent
    /// with MV ≤ max_mv.
    ///
    /// **Schema simplification vs Python.** Carries `max_mv: i32`
    /// only. Other Python-side riders that would naturally extend
    /// here (cross-controller widening, source-leaves auto-fire) are
    /// out of scope of this variant; the schema mirror is
    /// intentionally minimal, additive widenings get separate
    /// variants per the round-12 / round-13 / this-round precedent.
    ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves { max_mv: i32 },
    /// **Round 28 may-do decision wrapper.** "You may [inner effect]."
    /// Mirrors Python's `MayDo(Effect, prompt)` family (the
    /// `effects/generic/may_do.py` umbrella — "you may sacrifice a
    /// creature; if you do, ..." cards and similar may-pay riders).
    ///
    /// **Resolve semantics.** Pushes a `PendingDecision::MayDoChoice`
    /// onto `state.pending_decisions` and short-circuits the resolve.
    /// The controller either calls `submit_may_do_decision(yes)` to
    /// resolve manually, or `auto_resolve_pending_decisions(strategy)`
    /// to resolve via a strategy. "Yes" recursively applies the inner
    /// effect (with the same `source_obj_id` so "if you do" follow-on
    /// effects retain the resolving spell's identity); "no" drops the
    /// decision and the inner effect is never applied.
    ///
    /// **Prompt.** A free-form string surfaced to the agent via the
    /// `pending_decisions()` snapshot dict. Empty by default
    /// (registrations that omit `prompt`). Not used for any game-
    /// state mutation — purely informational.
    MayDo {
        inner_effect: Box<Effect>,
        prompt: String,
    },
    /// **Round 28 "look at top N, put one in hand, rest to graveyard"
    /// wrapper.** Mirrors Python's
    /// `LookTopNPutOneInHandRestToGraveyard` (Commune-with-Evil
    /// family, 4 EoE cards). Examines the top `n` cards of the
    /// controller's library; controller picks ONE to put into hand,
    /// the rest go to graveyard.
    ///
    /// **Resolve semantics.** Pops `min(n, library_len)` cards off
    /// library top and packages them into a
    /// `PendingDecision::PickCardFromExaminedChoice`. The Effect arm
    /// short-circuits — cards are NOT yet in graveyard or hand. The
    /// controller drains via `submit_pick_card_decision(chosen_id)`
    /// (manual) or `auto_resolve_pending_decisions("default" |
    /// "pick_top")` (deterministic). The auto-resolve / no-agent
    /// default picks the topmost card (cards[0]) — matches Python's
    /// fallback in `LookTopNPutOneInHandRestToGraveyard.resolve`.
    ///
    /// **Empty library short-circuit.** `n=0` or library_len=0 emits
    /// a PendingDecision with an empty `cards` Vec. Drains as an O(1)
    /// no-op via auto-resolve. Mirrors Python's `if not examined:
    /// return` short-circuit.
    LookTopNPutOneInHandRestToGraveyard { n: i32 },
    /// **BLOCKED-RUST-EFFECT slice (round 54) — Famished Worldsire ETB.**
    /// "When this creature enters, look at the top X cards of your
    /// library, where X is this creature's power. Put any number of
    /// land cards from among them onto the battlefield tapped, then
    /// shuffle." Mirrors Python's `FamishedWorldsireETBEffect`
    /// (`effects/bespoke.py:94`) — the ONLY EoE card with this shape,
    /// 2,324 17lands decks.
    ///
    /// **Unit variant; no payload.** X is dynamic (read from the
    /// source's CURRENT effective power at resolve, post-Devour +1/+1
    /// counters), and the "put any number" land selection is a
    /// DETERMINISTIC greedy-all (the Python source-of-truth picks ALL
    /// land cards from the examined set — `bespoke.py:121` — a
    /// documented "any number" → greedy-land simplification that is
    /// strictly ramp-positive; both engines mirror it so NO
    /// PendingDecision is plumbed and there is no §2
    /// silent-mistranslation surface from the choice). Extra dict
    /// fields silently ignored for round-trip dict-shape consistency
    /// (mirrors every other unit-variant parse arm — round-49
    /// `gain_life_equal_to_your_life_total` precedent).
    ///
    /// **Resolve semantics (mirrors `FamishedWorldsireETBEffect`).**
    /// 1. Source-controller resolution via the transient
    ///    `current_resolve_source_controller` (fallback
    ///    `active_player`) — CR 119.5 / 608.2; "your library" is the
    ///    source's controller's library, same shape as
    ///    `SearchLibraryForBasicLandTapped` (round-23/I69).
    /// 2. `X = effective_power(source)` = base (UEOT-SetBasePT
    ///    override / manland) + `ueot_power_bonus()` + signed
    ///    `obj.counters` — the SAME composition Python's
    ///    `_compute_effective_pt` folds in (round-53
    ///    `read_doubling_power` §2 precedent). `X <= 0` → silent
    ///    no-op (matches Python's `if x <= 0: return`; the oracle's
    ///    look-at-top-0 is a degenerate no-op — Famished Worldsire is
    ///    never X<=0 in practice because Devour seeds +1/+1 counters,
    ///    but the clamp mirrors Python for parity on edge inputs).
    /// 3. Examine the top `min(X, library_len)` cards (top = lib[0]
    ///    post-CE3). Remove every LAND card (printing
    ///    `card_types` contains "Land" — Python's `printing.is_land`)
    ///    from the examined window, in top-to-bottom order; put each
    ///    onto the source-controller's battlefield TAPPED, not
    ///    summoning-sick (CR 302.1 is creature-only; a land entering
    ///    via this effect has no summoning sickness regardless),
    ///    controller-stamped to the source's controller. Non-land
    ///    examined cards stay in the library in place (Python's
    ///    `rest` list is never removed — `bespoke.py:122`).
    /// 4. Fan out `Event::Enters` (landfall) for each entered land —
    ///    queued in `pending_etb_dispatches`, drained by the caller
    ///    after the resolving stack item pops, same as
    ///    `SearchLibraryForBasicLandTapped`. Mirrors Python's
    ///    `fire_landfall_triggers(state, land)` per-land call.
    /// 5. Shuffle the WHOLE remaining library (CR 701.19 / 701.22):
    ///    external `state.rng_ref()` Fisher-Yates (byte-identical to
    ///    Python's `random.Random.shuffle` via
    ///    `external_rng::next_below`) when a Python rng is installed,
    ///    xorshift64 fallback otherwise — the exact dual-path block
    ///    `SearchLibraryForBasicLandTapped` uses. Mirrors Python's
    ///    `shuffle_library(state, controller_id)`.
    FamishedWorldsireLookTopXByPowerPutLandsTapped,
    /// **Round 28 modal choose-one wrapper.** "Choose one — [mode_0];
    /// [mode_1]; ..." Mirrors Python's `ModalChooseOne(modes=...)`
    /// (combinators.py:1112, 13 EoE cards) in its first-slice shape:
    /// resolve-time mode picking via the decision-callback substrate.
    ///
    /// **Resolve semantics.** Pushes a
    /// `PendingDecision::ChooseModeChoice` onto the queue and short-
    /// circuits. The controller drains via
    /// `submit_choose_mode_decision(chosen_idx)` (manual) or
    /// `auto_resolve_pending_decisions("default" | "choose_mode_0")`
    /// (deterministic). The chosen mode is recursively applied via
    /// `apply_effect` with the same `source_obj_id`.
    ///
    /// **First-slice scope.** Resolve-time pick only; cast-time mode
    /// routing through `state.resolving_modes` and `or_both=True`
    /// (the "choose one or both" Charm variant) are deferred. The
    /// mode list is bounded by parse rejection — `modes.is_empty()`
    /// raises at register time so the resolve arm always has at least
    /// one mode to fall through to.
    ChooseOneMode { modes: Vec<Effect> },
    /// **Round 28 if-you-do wrapper.** "[do_action]; if you do,
    /// [then_action]." Mirrors Python's `IfYouDo(do_action,
    /// then_action)` (combinators.py:560, 7+ EoE cards) in its
    /// first-slice shape: do_action assumed implicitly success-on-
    /// yes (i.e. `IfYouDo(MayDo(X), Y)` "looter" form).
    ///
    /// **Resolve semantics.** Pushes a
    /// `PendingDecision::IfYouDoChoice` carrying both nested Effects.
    /// The controller drains via `submit_if_you_do_decision(yes)`
    /// (manual) or `auto_resolve_pending_decisions("default" |
    /// "if_you_do_yes" | "if_you_do_no")` (deterministic). On "yes"
    /// both `do_action` and `then_action` are applied in order via
    /// `apply_effect` with the original `source_obj_id`. On "no"
    /// neither is applied.
    ///
    /// **First-slice limitation.** General IfYouDo with do_actions
    /// that can signal failure (e.g. SacrificeACreature returning
    /// False on empty bf) is deferred — would require apply_effect
    /// to return `Result<bool>` so the IfYouDo arm can branch on
    /// do_action's success. The PyDict shape (`do_action` /
    /// `then_action`) is forward-compatible.
    IfYouDo {
        do_action: Box<Effect>,
        then_action: Box<Effect>,
    },
    /// Each opponent of the source's controller mills `count` cards
    /// (CR 701.13b — the per-opponent variant of `Mill`). Mirrors
    /// Python's `EachOpponentMillsCards(count: int = 1)` (3+ EoE
    /// cards target family). Same source-finder + opponent-as-target
    /// shape as `EachOpponentDiscards` / `EachOpponentLosesLife`.
    ///
    /// **Two-player simplification.** opponent_id = 1 - controller.
    /// The single opponent's library is milled `count` cards (top to
    /// graveyard); empty library stops the inner loop silently (CR
    /// 704.5b applies to *drawing*, not milling — same shape as
    /// `Effect::Mill`).
    ///
    /// **Source not found = silent fizzle** (lost-track-of-source
    /// tolerance, mirrors `EachOpponentDiscards`).
    ///
    /// **Negative `count` raises.** `count=0` is a legal no-op.
    /// Missing `count` defaults to 1 (Python parity).
    EachOpponentMillsCards { count: i32 },
    /// Move every card in each opponent's graveyard to that player's
    /// exile zone (untargeted graveyard wipe). Mirrors Python's
    /// `ExileEachOpponentsGraveyard`
    /// (`effects/generic/exile.py:260`) — the ETB-compound first half
    /// of Dauntless Scrapbot ("When this creature enters, exile each
    /// opponent's graveyard. Create a Lander token."). Structural twin
    /// of `EachOpponentMillsCards` (same source-controller finder +
    /// per-opponent loop), differing only in the inner op:
    /// graveyard → exile (the opponent's own exile zone, CR 406 /
    /// 400.7 zone-change reset) instead of library → graveyard.
    ///
    /// **Two-player simplification.** opponent_id = 1 - controller.
    /// Python iterates `state.players` skipping the controller AND
    /// any `has_lost` player; the Rust 2-player mirror exiles the
    /// single opponent's whole graveyard. (`has_lost` parity: in the
    /// 2-player engine a lost player ends the game, so the gate is a
    /// no-op in practice; the loop short-circuits an empty graveyard
    /// silently either way.)
    ///
    /// **Source not found = silent fizzle** (lost-track-of-source
    /// tolerance, mirrors `EachOpponentMillsCards` /
    /// `EachOpponentDiscards`).
    ///
    /// Unit variant — no parameters (Python class is field-free).
    ExileEachOpponentsGraveyard,
    /// **Round 28 UEOT coverage extension (broader pump filter).**
    /// Target artifact OR creature gets `+power/+toughness` until end
    /// of turn. Mirrors Python's
    /// `PumpTargetArtifactOrCreatureUntilEOT` (3+ EoE cards target
    /// family — Skitterclaw-Augur-shape "boost your robot or your
    /// dude" instants).
    ///
    /// **Target semantics.** Same first-slice deterministic pattern
    /// as `PumpTargetCreatureUntilEOT` but with a broader filter:
    /// pick the FIRST permanent on the source's controller's
    /// battlefield whose `card_types` contains "Artifact" OR
    /// "Creature". No legal target → silent fizzle.
    ///
    /// **Mechanism.** Same UEOT-modifier push as
    /// `PumpTargetCreatureUntilEOT` (modifier auto-expires on the
    /// next cleanup step via the r27 CR 514.3 UEOT-clear pass).
    /// `(0, 0)` short-circuits as a no-op. Negative bonuses are
    /// legal (debuff-shaped).
    PumpTargetArtifactOrCreatureUntilEOT { power_bonus: i32, toughness_bonus: i32 },
    /// **Round 28 each-opponent sacrifice.** Each opponent of the
    /// source's controller sacrifices a creature (CR 701.16). Mirrors
    /// Python's `EachOpponentSacrificesCreature` (3+ EoE cards target
    /// family — Cruel-Edict-shape symmetric sacrifice effects).
    ///
    /// **2-player simplification.** opponent_id = 1 - controller. The
    /// single opponent's FIRST creature on battlefield (zone-iteration
    /// order, mirrors PumpTargetCreatureUntilEOT target-pick) goes to
    /// the opponent's graveyard with CR 400.7 zone-change reset.
    ///
    /// **No eligible creature on opponent's bf** → silent fizzle
    /// (mirrors PumpTargetCreatureUntilEOT no-target fizzle).
    ///
    /// **Source not found anywhere** → silent fizzle (mirrors
    /// EachOpponentDiscards / EachOpponentMillsCards).
    EachOpponentSacrificesCreature,
    /// **Round 28 grant-keyword-UEOT family.** Target creature gains a
    /// keyword until end of turn. Mirrors Python's
    /// `GrantUnblockableUEOT` (3+ EoE cards) and forward-compatibly
    /// covers any future `GrantHasteUEOT` / `GrantFlyingUEOT` /
    /// `GrantTrampleUEOT` cards via the same dispatch — just a
    /// different `keyword` string.
    ///
    /// **Mechanism.** Push a `UeotModifier::GrantKeyword { keyword }`
    /// onto the target's `ueot_modifiers` Vec. The modifier auto-
    /// expires at the next cleanup step via the r27 CR 514.3 UEOT-
    /// clear pass. The existing `has_keyword_via_ueot(keyword)`
    /// accessor on `GameObject` surfaces the granted keyword for
    /// combat / blocking checks.
    ///
    /// **Target semantics — first-slice deterministic.** Pick the
    /// FIRST creature on source-controller's battlefield (zone-
    /// iteration order, mirrors PumpTargetCreatureUntilEOT). No
    /// eligible creature → silent fizzle. Python's
    /// `GrantUnblockableUEOT` carries `attacking_only` /
    /// `exclude_self` / `power_at_most` flags; this Rust first slice
    /// does NOT carry any of them (the no-flag form is by far the
    /// most common in real cards — "target creature is unblockable
    /// this turn").
    ///
    /// **Keyword convention.** Lowercase, matches
    /// `has_keyword_via_ueot` lookup. Common values: `"unblockable"`
    /// (Python's "can't be blocked"), `"haste"`, `"flying"`,
    /// `"trample"`, etc. Empty string rejected at parse time.
    GrantKeywordToTargetCreatureUntilEOT { keyword: String },
    /// **Round-15 (post-r14) rider-widened sibling of
    /// `GrantKeywordToTargetCreatureUntilEOT`.** Same shape, but admits
    /// a LIST of keywords plus an `exclude_source` flag for the
    /// "another target creature" variant. Mirrors Python's
    /// `PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
    /// granted_keywords=frozenset({...}), you_control_only=True,
    /// exclude_self=<bool>)` (the keyword-grant-only sub-shape with
    /// no P/T pump) — the bridge constructs the bare-creature-target
    /// Python class with `granted_keywords` populated and the
    /// `exclude_self` flag forwarded.
    ///
    /// **EoE consumer.** Blooming Stinger (1G Plant Scorpion, EoE) is
    /// the unique EoE source for the `exclude_source=true` shape:
    /// "When this creature enters, another target creature you control
    /// gains deathtouch until end of turn." Single-keyword grant
    /// (`["deathtouch"]`) on another target creature you control;
    /// `exclude_source=true` to exclude the resolving Stinger itself
    /// from the legal-target pool. Forward-compatible with future
    /// multi-keyword grants (e.g. "another target creature gains
    /// flying and trample UEOT") via the `Vec<String>` field.
    ///
    /// **Mechanism.** Push one
    /// `UeotModifier::GrantKeyword { keyword }` entry per keyword in
    /// the list onto the target's `ueot_modifiers` Vec. All entries
    /// auto-expire at the next cleanup step via the r27 CR 514.3
    /// UEOT-clear pass. The existing `has_keyword_via_ueot(keyword)`
    /// accessor on `GameObject` surfaces each granted keyword for
    /// combat / blocking checks.
    ///
    /// **Target semantics — first-slice deterministic.** Pick the
    /// FIRST creature on source-controller's battlefield (zone-
    /// iteration order, mirrors `PumpTargetCreatureUntilEOT` /
    /// `GrantKeywordToTargetCreatureUntilEOT`); when
    /// `exclude_source=true`, skip the resolving source itself.
    /// No eligible creature → silent fizzle.
    ///
    /// **Empty `keywords` list.** A pure no-op — no modifiers pushed,
    /// resolution still proceeds (mirrors Python's `if not
    /// self.granted_keywords: <skip grant body>` short-circuit). Parser
    /// arm rejects empty list to keep the dict shape honest.
    ///
    /// **Schema simplification vs Python.** Python's
    /// `PumpTargetCreatureUntilEOT` carries many other riders
    /// (`attacking_only`, `legendary_only`, `power_at_most`, etc.);
    /// this Rust slice carries `granted_keywords` + `exclude_source`
    /// only. Future filter narrowings re-enter as separate Rust
    /// variants per the round-12 / round-13 / round-14 additive-
    /// variant precedent.
    GrantKeywordsToTargetCreatureUntilEOT {
        keywords: Vec<String>,
        exclude_source: bool,
    },
    /// **Round 28 "untap another target permanent".** Mirrors Python's
    /// `UntapTargetOtherPermanent` (Nanoform-Sentinel trigger, 3+ EoE
    /// cards). Distinct from the existing `UntapTarget { target }` arm
    /// — adds an "other than source" filter.
    ///
    /// **Target semantics — first-slice deterministic.** Scan both
    /// players' battlefields in order (p0 first, then p1); pick the
    /// FIRST tapped permanent whose id != source_obj_id. Untap it.
    /// Mirrors Python's `[o for o in state.battlefield if o.id !=
    /// source_id and o.tapped]` filter + pick-first.
    ///
    /// **No eligible permanent** (everything untapped, or only the
    /// source itself is tapped) → silent fizzle.
    UntapTargetOtherPermanent,
    /// **Round 28 "tap another target creature".** Mirrors Python's
    /// `TapAnotherTargetCreature` (Starport-Security activated-ability
    /// family, 2+ EoE cards). Distinct from the existing
    /// `TapTarget { target: AnyCreature }` arm — adds an "other than
    /// source" filter so the resolving source can't tap itself.
    ///
    /// **Target semantics — first-slice deterministic.** Scan both
    /// players' battlefields in zone-iteration order (p0 first); pick
    /// the FIRST creature whose id != source_obj_id. Tap it. Already-
    /// tapped target is a silent no-op (matches the existing
    /// `TapTarget` contract).
    ///
    /// **No eligible creature** → silent fizzle.
    TapAnotherTargetCreature,
    /// **Round 28 mass reanimation.** Mirrors Python's
    /// `ReturnAllCreaturesFromYourGraveyardToBattlefield` (Awakening-
    /// Hall-style "return all creature cards from your graveyard to
    /// the battlefield", 2+ EoE cards). Distinct from the existing
    /// single-target `ReturnCreatureFromYourGraveyardToBattlefield`
    /// arm — returns EVERY creature in the source-controller's
    /// graveyard, not just the first.
    ///
    /// **Resolve semantics.** Iterate source-controller's graveyard in
    /// the stored order (oldest first — Vec.iter from the front);
    /// every object whose printing.card_types contains "Creature" is
    /// moved to the controller's battlefield with the standard ETB
    /// state reset (summoning_sick=true, tapped=false, damage=0,
    /// counters=0, attached_to=None, exiled_with_source=None). Non-
    /// creature graveyard objects stay in graveyard.
    ///
    /// **Empty graveyard / no creatures** → silent no-op (no state
    /// mutation).
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    /// **Round 28 base-P/T UEOT override (CR 613.4 layer 7b).** Target
    /// creature has base power and toughness `power/toughness` until
    /// end of turn. Mirrors Python's `SetBasePTUntilEOT(power,
    /// toughness)` (Genemorph-Imago-shape "has base P/T N/N this
    /// turn", 2+ EoE cards).
    ///
    /// **Mechanism.** Push a `UeotModifier::SetBasePT` onto the
    /// target's `ueot_modifiers` Vec. The composer
    /// (`battlefield_creature_power` / `_toughness`) reads the LAST
    /// `SetBasePT` and uses its values as the base instead of the
    /// printing's printed P/T. Counters + layer-7c additive bonuses
    /// (`PowerToughnessBonus`) still stack on top (CR 613.7c).
    ///
    /// **Target semantics.** Same first-slice deterministic pattern
    /// as `PumpTargetCreatureUntilEOT`: pick the FIRST creature on
    /// source-controller's battlefield. No eligible creature → silent
    /// fizzle.
    ///
    /// **Negative values are legal.** "Has base 0/0" is meaningful
    /// (the creature dies to SBA toughness <= 0). No guard.
    SetBasePTUntilEOT { power: i32, toughness: i32 },
    /// **Round 28 manifest-dread first-slice.** CR 701.55 — "Look at
    /// the top two cards of your library, manifest one of them, then
    /// put the other into your graveyard." Mirrors Python's
    /// `ManifestDread(count: int = 1)` (Bashful-Beastie family, 10
    /// EoE cards — the highest-frequency unported class).
    ///
    /// **Resolve semantics (count = 1).** Pop `min(2, library_len)`
    /// cards off library top and package them into a
    /// `PendingDecision::ManifestDreadChoice`. The Effect arm short-
    /// circuits — cards are NOT yet on battlefield or in graveyard.
    /// The controller drains via
    /// `submit_manifest_dread_decision(chosen_id)` (manual) or
    /// `auto_resolve_pending_decisions("default" | "manifest_top")`
    /// (deterministic — picks the topmost = cards[0]).
    ///
    /// **Empty / 1-card library partials.** library_len=0 emits a
    /// PendingDecision with an empty `cards` Vec. Drains as an O(1)
    /// no-op. library_len=1 emits a PendingDecision with cards = [top
    /// card]; on submit, the lone card is manifested and there's no
    /// graveyard-bound card. Mirrors Python's
    /// `if not p.library: return` and `if len(examined) == 1:`
    /// partials.
    ///
    /// **Face-down semantics — first-slice simplification.** The
    /// "manifested" card is moved to the controller's battlefield
    /// AS-IS — its original printing remains visible (name, types,
    /// P/T, abilities). Real MTG would set the permanent to a 2/2
    /// vanilla face-down creature with no abilities (CR 701.34 +
    /// 707.2), with the original printing tracked underneath for the
    /// face-up turn (CR 707.4). Modeling face-down state requires
    /// either a face-down flag on GameObject (forces fingerprint
    /// baseline rebuilding) or a face-down-placeholder-printing
    /// design — both deferred. See `docs/SEARCH_LIMITATIONS.md` for
    /// the full scope notice.
    ///
    /// **First-slice scope.** `count = 1` ONLY. Python supports
    /// `count = N` ("manifest dread N times") for Slimy Aquarium /
    /// Weight Room rider effects, and `count = None` (X-times) for
    /// Valgavoth's Onslaught. The Rust resolve arm raises on
    /// `count != 1`; the parse layer accepts any non-negative
    /// `count` so the Effect-enum round-trip is forward-compatible
    /// with a follow-up multi-iter slice.
    ///
    /// **Controller convention.** `state.active_player` — first-
    /// slice shape consistent with Surveil / LookTopN / MayDo /
    /// IfYouDo / ChooseOneMode. Real MTG plumbs the spell controller
    /// through `StackItem.controller`; deferred.
    ManifestDread { count: i32 },
    /// **Round-29 manifest-then-attach composition.** Mirrors Python's
    /// `ManifestDreadThenAttachSelf` (`effects/generic/library_lookat.py:510`
    /// — Conductive-Machete / Killer's-Mask / Cursed-Windbreaker /
    /// Dissection-Tools Duskmourn Equipment ETB family, freq 3 in
    /// the EoE-adjacent pool — included via the duskmourn pool the
    /// coverage script loads). Oracle text: *"When this Equipment
    /// enters, manifest dread, then attach this Equipment to that
    /// creature."*
    ///
    /// **Composition strategy (Option A).** Stitches the round-28
    /// `Effect::ManifestDread` substrate with the round-28 attach
    /// foundation (the `attached_to: Option<u32>` slot on
    /// `GameObject` + the `attach(aura_id, target_id)` pymethod).
    /// Adds NO new `PendingDecision` variant — instead extends
    /// `PendingDecision::ManifestDreadChoice` with a
    /// `then_attach_to_source: bool` field (`false` for the existing
    /// `Effect::ManifestDread` arm, `true` for this one). The submit
    /// dispatcher reads the flag and runs the attach as a follow-up.
    ///
    /// **Resolve.** Pop top `min(2, library_len)` cards into a
    /// `ManifestDreadChoice` with `then_attach_to_source: true`. The
    /// controller is the SOURCE'S controller (not `state.active_player`):
    /// this variant is always an Equipment ETB, so the source lives on
    /// a bf at resolve time and its controller field is authoritative.
    /// Source NOT on a bf → silent fizzle (no pending pushed). Mirrors
    /// Python's `if "Equipment" not in source.printing.subtypes: return`
    /// gate (which fires when there's no Equipment-typed source — same
    /// observable behavior as "no source on bf").
    ///
    /// **Submit + attach.** After the existing manifest-dread routing
    /// runs (chosen → bf with ETB reset, rest → graveyard), if
    /// `then_attach_to_source` is true the dispatcher locates the
    /// source on its controller's bf and stamps
    /// `source.attached_to = manifested_id`. If the source has LTB
    /// during the decision window (destroyed / returned to hand /
    /// bounced), the attach step is a silent partial — the manifest
    /// completes but the attach is skipped. Mirrors Python's
    /// `if manifested is None: return` and the implicit "Equipment
    /// gone" fall-through.
    ///
    /// **Empty / 1-card library partials.** Same as `ManifestDread`:
    /// empty library → pending with empty cards → drain as O(1) no-op
    /// (no manifest, no attach). 1-card library → manifest the lone
    /// card; if `then_attach_to_source` is true, attach to it.
    ///
    /// **First-slice scope.** `count = 1` ONLY (no Python printing of
    /// this class emits other values; the count field is reserved for
    /// schema parity with `ManifestDread`). Count != 1 raises with
    /// the same "deferred — see SEARCH_LIMITATIONS.md" message as
    /// the `Effect::ManifestDread` arm.
    ///
    /// **Schema.** Identical to `ManifestDread`: `count: i32` only,
    /// defaults to 1, parse-accepts any non-negative integer for
    /// forward-compat round-trip.
    ManifestDreadThenAttachSelf { count: i32 },
    /// **Round-29 manifest-then-counter composition (Moldering-Gym /
    /// Weight-Room family).** Mirrors Python's
    /// `ManifestDreadThenPutPlusOneCountersOnIt`
    /// (`effects/generic/library_lookat.py:451` — Duskmourn Room door
    /// triggers Slimy Aquarium (`counter_amount = 1`) and Weight Room
    /// (`counter_amount = 3`)). Oracle text: *"manifest dread, then
    /// put a +1/+1 counter on that creature"* / *"manifest dread,
    /// then put three +1/+1 counters on that creature"*.
    ///
    /// **Composition strategy (Option A — precedent from
    /// `ManifestDreadThenAttachSelf`).** Stitches the round-28
    /// `Effect::ManifestDread` substrate with the existing +1/+1
    /// counter scalar (`GameObject.counters: i32`). Adds NO new
    /// `PendingDecision` variant — instead extends
    /// `PendingDecision::ManifestDreadChoice` with a
    /// `then_plus_one_counter_on_manifested: bool` flag and a
    /// `counter_amount: i32` rider. The submit dispatcher reads the
    /// flag and stamps `obj.counters += counter_amount` on the
    /// manifested creature as a follow-up.
    ///
    /// **Resolve.** Pop top `min(2, library_len)` cards into a
    /// `ManifestDreadChoice` with `then_plus_one_counter_on_manifested
    /// = true` and `counter_amount = self.counter_amount`. Controller
    /// convention matches plain `Effect::ManifestDread`:
    /// `state.active_player` — these are Room-door triggers cast
    /// during the controller's turn, so `active_player` is the
    /// resolving controller. (Differs from `ManifestDreadThenAttachSelf`,
    /// which has to read the source's bf controller because it's an
    /// Equipment ETB; this variant doesn't need the source on a bf at
    /// all — the counter target is the just-manifested face-down, not
    /// the source.)
    ///
    /// **Submit + counter add.** After the existing manifest-dread
    /// routing completes (chosen → bf with ETB reset, rest →
    /// graveyard), if `then_plus_one_counter_on_manifested` is true
    /// AND a card was actually manifested (cards Vec was non-empty
    /// and a chosen card landed on bf), locate the manifested
    /// permanent by id and stamp `obj.counters += counter_amount`.
    /// If the cards Vec was empty (library was exhausted at resolve),
    /// no manifest happened and the counter step is naturally a no-op
    /// — mirrors Python's `if not new_ids: return` early-exit. (The
    /// manifested-id is captured locally inside the submit helper
    /// rather than searched globally, so an LTB-during-decision-window
    /// has nothing to defend against here: the helper just-routed the
    /// chosen card to bf moments earlier, so it's reachable.)
    ///
    /// **Empty / 1-card library partials.** Same as `ManifestDread`:
    /// empty library → pending with empty cards → drain as O(1) no-op
    /// (no manifest, no counter add — matches Python's "no new_ids →
    /// return" path). 1-card library → manifest the lone card and
    /// stamp the counter.
    ///
    /// **First-slice scope.** `count = 1` ONLY at the manifest-dread
    /// iteration level (inherits the `ManifestDread` gate — count > 1
    /// is the multi-iter shape; no Python printing of this class
    /// emits count != 1). `counter_amount` accepts arbitrary
    /// non-negative integers — Slimy Aquarium emits 1, Weight Room
    /// emits 3, future printings may pick other values.
    ///
    /// **Schema.** `count: i32` (manifest-dread iteration count,
    /// defaults to 1) and `counter_amount: i32` (defaults to 1).
    /// Both parse-accept any non-negative integer for forward-compat
    /// round-trip; non-negative gate fires at parse.
    ManifestDreadThenPutPlusOneCountersOnIt { count: i32, counter_amount: i32 },
    /// **Round-29 coverage extension.** Intervening-if effect keyed
    /// on the EoE "Void" condition. At resolve time, if Void is
    /// active (a nonland permanent left the battlefield this turn
    /// OR a spell was warped this turn), apply `then_effect`;
    /// otherwise apply `else_effect` (or no-op if `else_effect` is
    /// None). Mirrors Python's `ConditionalIfVoid(then_effect,
    /// else_effect=None)` (`combinators.py:1409` — Decode-
    /// Transmissions-shape "Void —" rider, 4 EoE cards).
    ///
    /// **Predicate.** Reads `state.permanent_left_battlefield_this_turn`
    /// or `state.spell_warped_this_turn`. Both substrate flags
    /// default to false and have no Rust call sites that set them
    /// yet — until the LTB-tracking / warp-tracking call sites land,
    /// the predicate always evaluates to false and the resolver
    /// always falls through to `else_effect`. This is a deliberate
    /// substrate stub: Python's `is_void_active(state)` reads the
    /// same two fields, and Rust will pick up Void-true behavior
    /// for free once those flags get wired by a future slice.
    ///
    /// **Recursion.** Both branches are `Box<Effect>` so nested
    /// effects (Sequence, other Conditionals) work. `else_effect`
    /// is `Option<Box<Effect>>` to mirror Python's optional second
    /// branch.
    ///
    /// **Schema.** `then_effect` required; `else_effect` optional
    /// (omitted dict key = None on the Rust side).
    ConditionalIfVoid {
        then_effect: Box<Effect>,
        else_effect: Option<Box<Effect>>,
    },
    /// Deal `amount` damage to target creature an opponent controls.
    /// Mirrors Python's `DealDamageToOpponentCreature(DealDamage)`
    /// sugar in `effects/generic/damage.py` — same `DealDamage` arm
    /// as `DealDamageToTargetCreature`, with the target restricted to
    /// `IsCreature() & ControlledByOpponent()` (the source's
    /// caster cannot pick their own creature). 2 EoE cards (Glassworks
    /// // Shattered Yard family).
    ///
    /// **Distinction from `Effect::DealDamage { target: AnyCreature }`** —
    /// that arm picks the FIRST creature on the defender's battlefield
    /// (= `1 - state.active_player`'s bf[0]) without a card-type filter.
    /// `DealDamageToOpponentCreature` filters the same battlefield to
    /// CREATURES ONLY (skipping lands / artifacts / non-creature
    /// permanents) AND scopes the search to OPPONENTS OF THE SOURCE'S
    /// CONTROLLER (rather than the defender of the active player). In
    /// 2-player land, these collapse to the same player when the
    /// source's controller is the active player, but a source whose
    /// controller is `state.players[1]` while `active_player == 1`
    /// (e.g. an instant cast on the opponent's turn) inverts the
    /// target direction — this slice gets that right via the
    /// 5-zone source-controller walk shape (mirrors `LoseLife` /
    /// `TargetOpponentLosesLife` / `EachOpponentDiscards`).
    ///
    /// **First-slice deterministic target choice.** Scan the source-
    /// controller's opponents in player order; for each opponent,
    /// scan their battlefield top-to-bottom and pick the FIRST
    /// `Creature` printing. In 2-player land that's exactly the
    /// opponent's battlefield[0]-that-is-a-creature. Real MTG lets
    /// the controller choose; deferred to the same decision-callback
    /// follow-up as the rest of the `DealDamage` family.
    ///
    /// **Source itself is excluded** — the predicate
    /// `ControlledByOpponent` filters by the printing's `controller`
    /// field, and the source's controller (= caster) is never an
    /// opponent of itself. A source on the opponent's battlefield
    /// is therefore eligible (its `controller` is the opponent),
    /// matching the Python filter's `controller != resolving_controller`
    /// shape. No explicit `id != source_obj_id` guard is needed in
    /// the loop because the predicate already excludes the
    /// resolving-controller side of the battlefield.
    ///
    /// **Negative amount raises** at register time AND at resolve
    /// time (defense-in-depth — mirrors round-3 `DealDamage` and
    /// `DealDamageAnyTarget` shape).
    ///
    /// **No eligible creature** (opponent's bf empty, or holds only
    /// non-creatures) → silent fizzle. Mirrors Python's
    /// `if not legal_targets: return` short-circuit and the
    /// `DealDamage { target: AnyCreature }` fizzle behavior.
    ///
    /// **SBA fires post-resolve.** `resolve_top_of_stack` calls
    /// `auto_resolve_pending` after the effect resolves and SBAs run
    /// via the dispatcher's standard pass; lethal damage (damage >=
    /// effective toughness) flips the creature to graveyard the same
    /// way the existing damage paths do (CR 704.5g).
    DealDamageToOpponentCreature { amount: i32 },
    /// **Round-28 look-at-top-N-reveal-or-counter wrapper.** Mirrors
    /// Python's `LookAtTopNRevealOrCounter(n, filter_name, max_power,
    /// counter_on_miss)` (Pulsar-Squadron-Ace + Living-Phone family,
    /// freq 2 in the EoE pool). Examines the top `n` cards of the
    /// CONTROLLER's library; controller MAY reveal one matching the
    /// filter and put it into hand; the rest go to the bottom of the
    /// library in a "random" order. If no card was revealed (because
    /// none matched, the agent declined, or the library was too small)
    /// AND `counter_on_miss` is true, a +1/+1 counter lands on the
    /// resolving source if it's currently on the battlefield.
    ///
    /// **Resolve semantics.** Pops `min(n, library_len)` cards off
    /// library top and packages them into a
    /// `PendingDecision::LookAtTopNRevealOrCounterChoice`. The Effect
    /// arm short-circuits — examined cards are NOT yet routed. The
    /// controller drains via `submit_look_at_top_n_decision(reveal,
    /// chosen_id)` (manual) or `auto_resolve_pending_decisions("default"
    /// | "reveal_no")` (deterministic, no-reveal — matches Python's
    /// no-agent-seated fallback because the Python class only reveals
    /// when an agent is seated AND the agent picks something).
    ///
    /// **Filter / max_power.** `filter_name` is one of `"spacecraft"`,
    /// `"creature"`, `"artifact"`; `max_power` (default 0 = no cap)
    /// gates the `"creature"` filter — Living Phone uses
    /// `filter_name="creature"`, `max_power=2`. Other `filter_name`
    /// values are rejected at parse. The reveal-side dispatcher
    /// validates the picked card matches the filter (it must be in
    /// the examined set AND match `_matches` semantics); a mismatch
    /// raises `ValueError` transactionally.
    ///
    /// **Bottom-the-rest is "random order".** First-slice
    /// simplification: we route the remainder to the BOTTOM of the
    /// library in popped order (cards[0] — the topmost popped — goes
    /// to the bottom first, then cards[1], etc.). Real MTG asks for a
    /// random order; we use a deterministic popped-order. Documented
    /// in SEARCH_LIMITATIONS as deferred — re-routes via the engine's
    /// rng once the rng-externalization work lands.
    ///
    /// **Empty library short-circuit.** `n=0` or library_len=0 emits a
    /// PendingDecision with an empty `cards` Vec. Drains as an O(1)
    /// no-op via auto-resolve (also triggers the counter rider IF
    /// `counter_on_miss=true` and the source is on bf — matches
    /// Python: no reveal happened, so the miss rider fires).
    ///
    /// **Controller convention.** `state.active_player` — first-slice
    /// shape consistent with Surveil / LookTopN / MayDo / IfYouDo /
    /// ChooseOneMode / ManifestDread.
    LookAtTopNRevealOrCounter {
        n: i32,
        filter_name: String,
        max_power: i32,
        counter_on_miss: bool,
    },
    /// **Round 28 manland animation (CR 613.4 + 613.6 + 613.7b).**
    /// Source land becomes a `power/toughness` creature until end of
    /// turn, optionally gaining a subtype (e.g., "Blinkmoth",
    /// "Elemental"). Mirrors Python's `BecomeLandCreatureUEOT(power,
    /// toughness, granted_subtype, ...)` (13 cards in the EoE pool —
    /// Blinkmoth Nexus / Lavaclaw Reaches / Wandering Fumarole
    /// manland-animate activated abilities).
    ///
    /// **"Self" semantics — manland animation always targets the
    /// activator's own land.** The recipient is the source GameObject
    /// itself (the activated-ability source). Same shape as
    /// `PumpSelfUntilEOT`. If the source has left the battlefield
    /// between activation and resolve, the effect is a silent no-op.
    ///
    /// **The land stays a land.** Per CR 305.3, an animated land is
    /// BOTH a land and a creature for the duration. The `card_types`
    /// of the printing remains unchanged (still contains "Land"); the
    /// `BecomesLandCreature` modifier conceptually adds "Creature" to
    /// the effective type set. Effective-P/T readers
    /// (`battlefield_creature_power` / `_toughness`,
    /// `effective_power` / `effective_toughness`) honor the modifier:
    /// when present, they treat the object as a creature with base
    /// `power`/`toughness` (layer 7b override). Layer 7c additive
    /// bonuses (`PowerToughnessBonus`) still stack on top.
    ///
    /// **Mechanism.** Pushes a `UeotModifier::BecomesLandCreature {
    /// power, toughness, color_or_subtype }` entry onto the source's
    /// `ueot_modifiers` Vec. Auto-expires at the next CR 514.3
    /// UEOT-clear pass (cleanup step), reverting the land to its
    /// non-creature state.
    ///
    /// **Schema simplification vs Python.** Python's
    /// `BecomeLandCreatureUEOT` carries `granted_keywords`,
    /// `unblockable`, `granted_activated_abilities`, and
    /// `granted_triggered_abilities`. The Rust first slice carries
    /// only `power`, `toughness`, and optional `granted_subtype` —
    /// the keyword / unblockable / granted-ability riders compose
    /// via separate effect chains or wait for follow-up slices.
    /// `(0, 0)` with no subtype is a legal no-op for parity edge
    /// cases.
    BecomeLandCreatureUEOT {
        power: i32,
        toughness: i32,
        granted_subtype: Option<String>,
    },
    /// **Round 29 optional-mana-cost wrapper.** "You may pay {cost}. If
    /// you do, [inner_effect]." Mirrors Python's
    /// `OptionalManaCostThenEffect(cost_str, inner_effect)`
    /// (`effects/combinators.py:1469` — Kavaron-Harrier / Oreplate-
    /// Pangolin "may pay {1}; if you do, ..." trigger family, freq 2
    /// in the EoE pool).
    ///
    /// **Resolve semantics.** Pushes a
    /// `PendingDecision::OptionalManaCostChoice` onto the queue and
    /// short-circuits. The controller drains via
    /// `submit_optional_mana_cost_decision(pay)` (manual) or
    /// `auto_resolve_pending_decisions("default" | "optional_pay_yes"
    /// | "optional_pay_no")`. On a `pay=true` submit, the dispatcher
    /// validates the controller can pay the cost from their mana
    /// pool; if so, the cost is deducted atomically and the inner
    /// effect is applied via `apply_effect` (with the original
    /// `source_obj_id` so identity-coupled riders retain identity).
    /// If the pool can't afford the cost, `pay=true` raises
    /// `ValueError` transactionally — no mutation. On `pay=false`,
    /// the decision is dropped.
    ///
    /// **Python parity for the no-agent default.** Python's
    /// `OptionalManaCostThenEffect.resolve` is auto-resolving: it
    /// pays whenever the controller can afford, otherwise the trigger
    /// does nothing. The Rust `"default"` strategy mirrors this — if
    /// the pool can afford the cost, pay it and apply the inner; if
    /// not, drop the decision silently.
    OptionalManaCostThenEffect {
        cost: ManaCost,
        inner_effect: Box<Effect>,
    },
    /// **Round 28 freq-2 closure — Starwinder / Fear-of-Failed-Tests
    /// shape.** "When a creature you control deals combat damage to
    /// a player, you may draw that many cards." Mirrors Python's
    /// `DrawCardsEqualToResolvingCombatDamage`
    /// (`effects/generic/draw_mill.py:89` — 2 EoE cards). The "may"
    /// is engine-flattened to always-yes (same precedent as other
    /// OptionalXyz simplifications elsewhere — see the Python class
    /// docstring).
    ///
    /// **Mechanism.** Reads
    /// `state.resolving_combat_damage_amount` (i32 slot on
    /// GameState), then draws that many cards for the source's
    /// controller (zone-scan + stack-scan fallback, same pattern as
    /// DiscardSelf et al.). `amount <= 0` is a silent no-op.
    /// Negative library length is handled by the standard CR 704.5b
    /// path (player flagged for empty-library loss).
    ///
    /// **Write site (I32, this slice closes the deferral).** The
    /// `resolving_combat_damage_amount` slot is now written
    /// per-event inside
    /// `state_ops_combat.rs::GameState::apply_damage_pass` — set
    /// to `entry.amount` before the per-entry mutations fire, reset
    /// to 0 after. Mirrors Python's per-event set/reset boundary
    /// (`combat.py:618,623` granted dealt-damage trigger resolve,
    /// `actions.py:2684,2699` stack-pushed trigger resolve). The
    /// Effect arm reads the slot; under normal combat the slot is
    /// the dealt amount for whichever event is in flight. The
    /// `set_resolving_combat_damage_amount` test setter remains
    /// available for synthetic / cross-engine harness tests that
    /// emulate the apply-loop write outside a real combat flow.
    /// RUST_PARITY_GAPS.md I32 documents the lifecycle.
    DrawCardsEqualToResolvingCombatDamage,
}

// --- ETB trigger substrate (Slice 1) -----------------------------
//
// Mirrors Python's `src/mtg_bot/effects/predicates.py:Event` +
// `effects/base.py:TriggeredAbility`. First-slice scope (per
// `docs/RUST_ETB_TRIGGER_AUDIT.md` §6.1):
//
// - **Event::Enters only** is wired today. Other variants land in
//   later slices (Slice 3+); listing them here lets the parser /
//   matcher fail loud on out-of-scope events at register time
//   without expanding scope.
// - **Predicate algebra is minimal**: `Always`, `SourceIsSelf`,
//   `SourceIsCreature`, `Not(Box<Predicate>)`, `And(Box<Predicate>,
//   Box<Predicate>)`. Enough to express the smoke-probe shape
//   ("when ANOTHER creature enters under your control" — see
//   audit §5.4 Example A) and the canonical IsSelf shape ("when
//   ~ enters"). Richer predicates (HasSubtype, IsLand, IsArtifact,
//   Controlled, Subject) follow in Slice 3+.
// - **TriggeredAbility carries `event`, `predicate`, `effect`, and
//   `once_per_turn`.** The Python shape also carries `requires_void`
//   / `tier_threshold` / `room_half`; the Rust mirror omits those
//   gates in Slice 1 (they default to "always fire") because the
//   Slice 1 smoke probe doesn't need them. Slice 3+ adds them in
//   lockstep with the Predicate expansion.
//
/// Event taxonomy for the trigger dispatcher (mirror of
/// Python's `Event` enum at `src/mtg_bot/effects/predicates.py`).
/// First-slice scope wires only `Enters`; later slices add the
/// rest. Listed here so the parser can validate the registry-dict
/// `event` key at register time rather than at dispatch time.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Event {
    /// "When/whenever X enters the battlefield" — fires from
    /// `dispatch_event(Event::Enters, source_id)` walks. Today's
    /// only wired event (Slice 1).
    Enters,
    /// "When X dies" / "When X is put into a graveyard from
    /// the battlefield". Stub for Slice 4+; no dispatch site yet.
    Dies,
    /// "When you cast a spell" / "When X is cast". Stub for
    /// Slice 5+; no dispatch site yet.
    Cast,
    /// "When X attacks". Slice 7 wires this — dispatched inline at
    /// the `declare_attacker` site after the per-attacker push to
    /// `state.attackers`. SourceIsSelf matches naturally via
    /// `source_id == subject_id` on the bf-snapshot observer set.
    Attacks,
    /// "When X blocks". Slice 9 wires this — dispatched inline at
    /// the `declare_blocker` site after the per-pair push to
    /// `state.blockers`. Single-subject shape: subject = blocker
    /// (multi-subject blocker + attacked-creature predicates are
    /// out of scope until `Predicate::Subject(slot, inner)` lands
    /// alongside Event::DealsCombatDamage). SourceIsSelf
    /// ("whenever this creature blocks") matches naturally via
    /// `source_id == subject_id`.
    Blocks,
    /// "When X deals damage" / combat-damage triggers. Stub for
    /// Slice 12+; no dispatch site yet.
    DealsDamage,
    /// "When X leaves the battlefield". Fires from
    /// `dispatch_event(Event::LeavesBattlefield, leaving_id)` on
    /// every bf-exit primitive (move_object off-bf + SBA destroy).
    /// Slice 8 wires this — see RUST_ETB_TRIGGER_AUDIT.md "Slice 8
    /// completion notice".
    ///
    /// **Relationship to DIES:** every creature death is also a bf
    /// exit, so SBA-destroyed creatures fire BOTH DIES and LEAVES
    /// (push order: DIES first via `pending_dies_dispatches`,
    /// LEAVES second via `pending_leaves_dispatches`). Mirrors
    /// Python's `move_off_battlefield` (turn.py:280-289) which
    /// invokes both `dispatch_event(DIES)` and
    /// `_fire_leaves_battlefield_triggers` in sequence.
    LeavesBattlefield,
    /// "Whenever X becomes tapped". Fires from
    /// `dispatch_event(Event::BecomesTapped, tapped_id)` at every
    /// production tap-the-permanent site that mirrors Python's
    /// `turn.tap_permanent` callers — round-58 BECOMES_TAPPED event
    /// bridge. Mirrors Python's `Event.BECOMES_TAPPED` enum member
    /// (`src/mtg_bot/effects/predicates.py:60` — string value
    /// `"becomes_tapped"`) and its single firing chokepoint
    /// `turn.tap_permanent` (`src/mtg_bot/turn.py:542-571`).
    ///
    /// **Firing-set parity (CR 701.21a + §2 bridge-correctness).**
    /// Python fires this ONLY through `tap_permanent` (the no-op-if-
    /// already-tapped chokepoint), which is called from: tap-for-mana
    /// (`actions.py:auto_tap_for_cost`), the `{T}` activated-ability
    /// `tap_self` cost (`actions.py:_activate_ability`),
    /// `tap_permanent_you_control` activated cost
    /// (`actions.py:2258`), convoke (`actions.py:673`), crew
    /// (`actions.py:2402`), attack-tap of a non-vigilance attacker
    /// (`combat.py:104`, fired BEFORE the per-attacker ATTACKS
    /// dispatch at `combat.py:115`), and the tapper-effect family
    /// (`effects/generic/tap.py`, `effects/combinators.py:163`,
    /// `effects/bespoke.py:496`). Python deliberately does NOT fire
    /// it for permanents that ENTER tapped (`_play_land`'s
    /// `card.tapped = True`, search-land-tapped, reanimate-tapped,
    /// token-created-tapped) nor for regeneration's replacement tap
    /// (`turn.py:1268`) — those are direct `obj.tapped = True`
    /// assignments, not `tap_permanent` calls (CR 701.21a: a
    /// permanent entering tapped never "becomes tapped"). Rust's
    /// emission set matches this exactly; the entering-tapped /
    /// regeneration-tap Rust sites stay raw `obj.tapped = true`.
    BecomesTapped,
}

/// Predicate algebra over the trigger subject (the GameObject the
/// event happened to) and source (the GameObject carrying the
/// ability). First-slice closed-enum minimal surface; mirrors a
/// strict subset of Python's predicate algebra at
/// `src/mtg_bot/effects/predicates.py`.
///
/// **Evaluation contract.** `matches(state, source_id, subject_id)`
/// returns `true` when the predicate is satisfied for this firing.
/// `Always` always matches; `SourceIsSelf` checks that the source
/// IS the subject (canonical "when ~ enters" shape);
/// `SourceIsCreature` checks the source's printing carries the
/// "Creature" card_type; `Not(p)` inverts; `And(a, b)` is logical
/// AND with short-circuit.
#[derive(Clone, Debug)]
pub enum Predicate {
    /// Always matches. Equivalent to no filter.
    Always,
    /// Matches when the source object IS the subject of the event
    /// (canonical "this creature enters" / "when ~ enters" shape).
    SourceIsSelf,
    /// Matches when the source object's printing has "Creature" in
    /// its card_types. Building block for shapes like "when ANOTHER
    /// creature enters — your creature has this ability".
    SourceIsCreature,
    /// Matches when the **subject's** printing has "Land" in its
    /// card_types. Mirrors Python's `Subject(None, IsLand())` —
    /// the canonical "a land enters" filter used by landfall-shape
    /// triggers (`cards/parser/triggers.py:603-1266`).
    SubjectIsLand,
    /// Matches when the **subject's** printing has "Artifact" in its
    /// card_types. Mirrors Python's `Subject(None, IsArtifact())` —
    /// "an artifact enters" filter for artifact-enters triggers.
    SubjectIsArtifact,
    /// Matches when the **subject's** printing has "Creature" in its
    /// card_types. Mirrors Python's `Subject(None, IsCreature())` —
    /// the canonical "a creature enters" filter for
    /// Panharmonicon-shape triggers. Subject-anchored sibling of
    /// `SourceIsCreature`.
    SubjectIsCreature,
    /// Matches when the **subject** is controlled by the source's
    /// controller. Mirrors Python's `Controlled(YOU)` — the
    /// canonical "under your control" qualifier on ETB triggers
    /// like "whenever a creature enters under your control" and
    /// "whenever a land enters under your control".
    ControlledByYou,
    /// Matches when the **subject's** printing carries the given
    /// subtype string. Mirrors Python's `Subject(None, HasSubtype(s))`
    /// — the canonical Kavu/Sliver/Equipment-enters predicate from
    /// `src/mtg_bot/cards/parser/triggers.py:1198`. Case-sensitive
    /// Title Case match against the subject's
    /// `CardPrinting.subtypes` Vec.
    ///
    /// **Effective-subtypes scope.** Python's `HasSubtype` reads
    /// through `effective_subtypes` (CR 613 layer-3/4 — Conspiracy
    /// granting "Sliver", Magus / Dryad layering on lands, etc.).
    /// The Rust mirror reads the printing's static `subtypes`
    /// directly — there's no Rust effective-subtypes layer yet,
    /// and none of the existing card-type predicates
    /// (`SubjectIsLand` / `SubjectIsCreature` / etc.) compute
    /// effective types either. The same upgrade-when-layers-land
    /// note applies symmetrically. EoE pool has no Conspiracy-shape
    /// subtype-granting effects today, so the direct read is
    /// observably equivalent.
    SubjectHasSubtype(String),
    /// Logical negation.
    Not(Box<Predicate>),
    /// Logical AND (short-circuits on the left operand's `false`).
    And(Box<Predicate>, Box<Predicate>),
    /// Logical OR (short-circuits on the left operand's `true`).
    ///
    /// Mirrors Python's `Or(left, right)` from
    /// `src/mtg_bot/effects/predicates.py:300`. Unlocks predicate
    /// shapes like Weftstalker Ardent / Haliya Guided by Light's
    /// "whenever a creature or artifact you control enters"
    /// (`(SubjectIsCreature OR SubjectIsArtifact) AND ControlledByYou
    /// AND NOT SourceIsSelf`), where Slice 4's `And`-only algebra
    /// couldn't express the disjunction.
    Or(Box<Predicate>, Box<Predicate>),
}

impl Predicate {
    /// Evaluate the predicate against the firing context.
    ///
    /// `source_id` is the GameObject carrying the ability;
    /// `subject_id` is the GameObject the event happened to (the
    /// creature that just entered the battlefield, for Enters).
    /// Both ids are u32-keyed object ids resolved at dispatch time.
    pub(crate) fn matches(
        &self,
        state: &crate::state::GameState,
        source_id: u32,
        subject_id: u32,
    ) -> bool {
        match self {
            Predicate::Always => true,
            Predicate::SourceIsSelf => source_id == subject_id,
            Predicate::SourceIsCreature => {
                source_has_card_type(state, source_id, "Creature")
            }
            Predicate::SubjectIsLand => {
                subject_has_card_type(state, subject_id, "Land")
            }
            Predicate::SubjectIsArtifact => {
                subject_has_card_type(state, subject_id, "Artifact")
            }
            Predicate::SubjectIsCreature => {
                subject_has_card_type(state, subject_id, "Creature")
            }
            Predicate::ControlledByYou => {
                // Subject's controller == source's controller. Mirrors
                // Python's `Controlled(by=YOU)` on a permanent subject:
                // ``obj.controller_id == source.controller_id``.
                // Each id is resolved by walking the four tracked zones
                // on both players; the helper returns `None` when the
                // id isn't present (the same loud-but-safe shape as
                // `find_source_printing_id`).
                let source_controller =
                    find_object_controller(state, source_id);
                let subject_controller =
                    find_object_controller(state, subject_id);
                match (source_controller, subject_controller) {
                    (Some(sc), Some(jc)) => sc == jc,
                    // Either id missing — never match (e.g. the
                    // subject has already left the battlefield, or
                    // the source was evicted mid-dispatch).
                    _ => false,
                }
            }
            Predicate::SubjectHasSubtype(subtype) => {
                subject_has_subtype(state, subject_id, subtype)
            }
            Predicate::Not(inner) => !inner.matches(state, source_id, subject_id),
            Predicate::And(a, b) => {
                a.matches(state, source_id, subject_id)
                    && b.matches(state, source_id, subject_id)
            }
            Predicate::Or(a, b) => {
                a.matches(state, source_id, subject_id)
                    || b.matches(state, source_id, subject_id)
            }
        }
    }
}

/// Look up an object by id across all four tracked zones of both
/// players and return whether its printing's `card_types` contains
/// the given type. Returns `false` when the object id isn't present
/// or its printing is unregistered (the loud-but-safe shape used by
/// `Predicate::SourceIsCreature`'s original inline lookup).
fn source_has_card_type(
    state: &crate::state::GameState,
    obj_id: u32,
    card_type: &str,
) -> bool {
    object_has_card_type(state, obj_id, card_type)
}

/// Subject-anchored sibling of `source_has_card_type`. Same shape;
/// the distinct entry point keeps the predicate-arm bodies tidy and
/// the intent self-documenting at the call site.
fn subject_has_card_type(
    state: &crate::state::GameState,
    obj_id: u32,
    card_type: &str,
) -> bool {
    object_has_card_type(state, obj_id, card_type)
}

/// Shared body for `source_has_card_type` / `subject_has_card_type`.
fn object_has_card_type(
    state: &crate::state::GameState,
    obj_id: u32,
    card_type: &str,
) -> bool {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    if let Some(printing) =
                        state.registry.lookup(obj.printing_id)
                    {
                        return printing
                            .card_types
                            .iter()
                            .any(|t| t == card_type);
                    }
                    return false;
                }
            }
        }
    }
    false
}

/// Look up an object by id across all four tracked zones of both
/// players and return whether its printing's `subtypes` contains the
/// given subtype string. Case-sensitive Title Case match (mirrors the
/// stored shape from the registry-dict parser). Returns `false` when
/// the object id isn't present or its printing is unregistered (the
/// same loud-but-safe shape as `object_has_card_type`).
///
/// **Effective subtypes scope.** Same caveat as `Predicate::SubjectHasSubtype`'s
/// doc comment: reads the printing's static `subtypes` directly,
/// not an `effective_subtypes` layer (which doesn't exist on the
/// Rust side yet — see Python's `mtg_bot.game.effective_subtypes`
/// for the CR 613 layer-3/4 reading the rules-correct path uses).
/// Symmetric with how `object_has_card_type` reads `card_types`
/// directly.
fn subject_has_subtype(
    state: &crate::state::GameState,
    obj_id: u32,
    subtype: &str,
) -> bool {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    if let Some(printing) =
                        state.registry.lookup(obj.printing_id)
                    {
                        return printing
                            .subtypes
                            .iter()
                            .any(|s| s == subtype);
                    }
                    return false;
                }
            }
        }
    }
    false
}

/// Look up an object by id across all four tracked zones of both
/// players and return its controller id. Returns `None` when the
/// object isn't found in any of those zones (already moved off-bf
/// in a way the dispatch caller didn't expect, or an id mismatch).
fn find_object_controller(
    state: &crate::state::GameState,
    obj_id: u32,
) -> Option<u8> {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    return Some(obj.controller);
                }
            }
        }
    }
    None
}

/// A triggered ability on a `CardPrinting`. Mirrors Python's
/// `TriggeredAbility` dataclass at
/// `src/mtg_bot/effects/base.py:680`.
///
/// **Slice 1 scope.** Only the predicate-style path is wired
/// (`event` is required and never `None` on the Rust side; Python's
/// optional shape is the legacy string-key path Slice 1 doesn't
/// mirror). `requires_void`, `tier_threshold`, `room_half` from
/// Python are omitted here — defaults of "always fire" suffice for
/// the smoke probe; they land alongside their gates in Slice 3+.
#[derive(Clone, Debug)]
pub struct TriggeredAbility {
    /// The event family this ability listens for (today only
    /// `Event::Enters`).
    pub event: Event,
    /// Filter over the firing context (source object, subject
    /// object, game state). Slice 1 minimum: `Always`,
    /// `SourceIsSelf`, `SourceIsCreature`, with `And` / `Not`
    /// compositions.
    pub predicate: Predicate,
    /// The payload effect to push as a `StackItem::TriggeredAbility`
    /// when this ability fires. Same closed `Effect` vocabulary the
    /// spell-resolve path consumes; the trigger resolver hands the
    /// effect to `apply_effect` exactly the way spell resolution
    /// does.
    pub effect: Effect,
    /// "This ability triggers only once each turn." When true the
    /// dispatcher records `(source_id, ability_index)` in
    /// `GameState.triggered_this_turn` on push and suppresses repeat
    /// fires within the same turn. Reset at cleanup step. Slice 1
    /// wires the ledger but no SLICE-1 test exercises the gate (the
    /// canonical IsSelf-enters trigger fires at most once per
    /// permanent's life anyway).
    pub once_per_turn: bool,
}

// --- Activated-ability substrate (CE20 Slice 1) ------------------
//
// Mirrors Python's `src/mtg_bot/effects/base.py::ActivationCost` +
// `ActivatedAbility`. **First-slice minimal field set** — covers the
// load-bearing closure surface (a mana-cost-paying activated ability
// like Bear Caster's "{1}{G}, T: Draw a card"). Other cost shapes
// from the Python class (sacrifice_self, exile_self, pay_life,
// requires_*, etc.) are deferred to follow-up slices that bring
// their dispatch primitives along — listing them here without a
// dispatch site would let registry-dict callers stamp activations
// that silently no-op the cost portion. The Slice 1 surface:
//
//   * `mana: ManaCost` — payable from the controller's mana pool.
//   * `tap_self: bool` — implicit `{T}` cost; sets `obj.tapped = true`
//     before the effect dispatches.
//   * `is_mana_ability: bool` — when `true` the effect resolves
//     immediately (CR 605.3a — mana abilities bypass the stack); when
//     `false` the ability pushes a `StackItem::TriggeredAbility`-shaped
//     stack slot whose payload effect resolves on the next
//     `resolve_top_of_stack` (mirrors Python's `_activate_ability`
//     stack-push at `actions.py:1928-2002`).
//
// **Deferred to follow-up slices** (each lands with its dispatch
// counterpart, lockstep):
// - Sacrifice-as-cost (`sacrifice_self`, `sacrifice_another_*`,
//   `sacrifice_a_land`, `sacrifice_food`, `sacrifice_a_desert`).
// - Counter-as-cost (`remove_plus_one_counter_from_your_creature`)
//   and planeswalker loyalty-as-cost (`pay_loyalty`).
// - Tap-an-untapped-permanent-you-control (Gene Pollinator shape).
// - Activation-gate predicates (`requires_*` Bonders' Enclave shape).
// - Sorcery-speed gate (`sorcery_speed`) — already implicit in the
//   Slice 1 emission position INSIDE the sorcery-timing block; the
//   per-ability field is a more granular over-ride.
// - Spacecraft tier / Rooms `room_half` / activate_only_once gates.
//
/// Cost composition for an `ActivatedAbility`. First-slice minimal —
/// payable from the controller's mana pool, plus an optional implicit
/// `{T}` tap-self.
#[derive(Clone, Debug, Default)]
pub struct ActivationCost {
    /// Mana portion of the cost. An all-zero `ManaCost` (the
    /// `Default::default()` shape) is a "free" cost — payable with no
    /// pool requirement. The cost-pay primitive consumes mana from the
    /// controller's pool via the same `pay_mana_cost` shape spell casts
    /// use (`state_ops_cast.rs::pay_mana_cost`).
    pub mana: ManaCost,
    /// Implicit `{T}` portion of the cost. When `true`, the
    /// dispatcher sets `obj.tapped = true` on the source after the
    /// affordability check passes; an already-tapped source rejects
    /// the activation. Mirrors Python's
    /// `ActivationCost.tap_self`.
    pub tap_self: bool,
    /// "Sacrifice this permanent" portion of the cost. When `true`,
    /// the dispatcher moves the source from its current battlefield
    /// to its controller's graveyard AFTER mana + tap costs commit
    /// successfully. Mirrors Python's
    /// `ActivationCost.sacrifice_self`. 35 EoE printings carry this
    /// shape — `Honored Knight-Captain`, `Illvoi Galeblade`,
    /// `Cryogen Relic`, every Lander token, etc.
    ///
    /// **Composes with `tap_self`.** `tap_self=true` AND
    /// `sacrifice_self=true` is legal — the source taps before it
    /// dies (observable for triggers that fire on tap state if any).
    /// The dispatch commits in order: mana → tap → sacrifice.
    ///
    /// **Self-only Slice 1 scope.** Targeted sacrifice shapes
    /// (`sacrifice_another_creature`, `sacrifice_a_land`,
    /// `sacrifice_food`, etc.) need target fan-out at
    /// `legal_decisions` emission and a new optional
    /// `target_creature_id` key on the ActivateAbility dict; deferred
    /// to a follow-up slice once Equipment-equip ships the target
    /// substrate.
    ///
    /// **LTB void-flag** (CE13 / I29 closure): the dispatch routes
    /// the sacrificed object through `mark_left_battlefield_if_nonland`
    /// so the existing void-tracking flag stamps correctly. No new
    /// wiring needed — sacrifice rides on the same LTB primitive
    /// every other bf-exit uses.
    pub sacrifice_self: bool,
    /// **CE20 follow-up — Equipment-equip Slice 4.** When `true`, the
    /// activated ability requires the activator to pick a target
    /// creature they control (CR 702.6c — equip targets a creature
    /// you control). Flows into emission as a fan-out (one
    /// `ActivateAbility` dict per legal target creature on the
    /// activator's bf) and into apply as a required
    /// `target_creature_id` key on the action dict.
    ///
    /// Default `false` keeps every pre-Slice-4 caller working: the
    /// dict shape stays {kind, source_id, ability_index} for
    /// non-target activations, and the emission walk emits one
    /// dict-per-source as before.
    ///
    /// **Eligibility** (mirrors Python's `EquipTargetSelector` at
    /// `effects/generic/attach.py` + CR 702.6c):
    ///   - target must be a creature on the activator's battlefield,
    ///   - target must NOT be the source itself (an Equipment can't
    ///     equip itself),
    ///   - target's summoning sickness is NOT a barrier (CR 702.6
    ///     gates the activator's source — equip is a tap-cost-free
    ///     ability so the target's sickness is irrelevant).
    ///
    /// **Retarget shape** (CR 702.6c): activating equip on an
    /// already-attached Equipment with a new target re-stamps
    /// `attached_to`. The dispatch fires the underlying
    /// `Effect::EquipToTargetCreatureYouControl` arm which reads the
    /// payload `target_id` and stamps it (overwriting any prior
    /// `attached_to`). Mana cost paid both times — the activation is
    /// a valid game action even when its observable mutation is a
    /// no-op (idempotent retarget to the same creature is legal).
    ///
    /// **EoE printings affected**: 7 (Auxiliary Boosters, Squire's
    /// Lightblade, Atomic Microsizer, Illvoi Light Jammer, Hylderblade,
    /// Meltstrider's Gear, The Dominion Bracelet).
    pub requires_target_creature_you_control: bool,
    /// **CE20 follow-up Slice 6 — targeted-sacrifice variants.**
    /// "Sacrifice another creature or artifact" — the activator picks
    /// any non-source creature OR artifact on their bf. Mirrors
    /// Python's `ActivationCost.sacrifice_another_creature_or_artifact`
    /// at `effects/base.py:358`. Default `false`.
    ///
    /// Rides on the Slice 4 target-pick substrate: emission fans out
    /// one `ActivateAbility` dict per legal sac target (eligible target
    /// = on activator's bf, NOT the source itself, has `Creature` OR
    /// `Artifact` card_type). Apply arm validates the chosen target,
    /// then commits in Phase 5b — moves the chosen target to its
    /// controller's graveyard (in practice the activator's gy because
    /// you can only choose permanents you control). Same field-reset +
    /// LTB-void-flag + LEAVES queue plumbing as the Slice 2
    /// `sacrifice_self` commit.
    ///
    /// **Composes with `tap_self` + `mana`.** Order:
    /// mana → tap → sac-another → effect.
    pub sacrifice_another_creature_or_artifact: bool,
    /// **CE20 follow-up Slice 6 — targeted-sacrifice variants.**
    /// "Sacrifice a land" — the activator picks any land they
    /// control (Dust Bowl shape). Mirrors Python's
    /// `ActivationCost.sacrifice_a_land` at `effects/base.py:388`.
    /// Default `false`.
    ///
    /// Eligibility: target on activator's bf with `Land` card_type.
    /// The printed text reads "Sacrifice a land" (no "another"
    /// qualifier), so when the source IS a land the source itself is
    /// eligible as the sacrifice target. Python mirrors this lenient
    /// reading.
    pub sacrifice_a_land: bool,
    /// **CE20 follow-up Slice 6 — targeted-sacrifice variants.**
    /// "Sacrifice another artifact" — strict artifact-only filter
    /// (Memorial Vault shape). Mirrors Python's
    /// `ActivationCost.sacrifice_another_artifact` at
    /// `effects/base.py:364`. Default `false`.
    ///
    /// Eligibility: target on activator's bf with `Artifact` card_type,
    /// NOT the source itself ("another" qualifier).
    pub sacrifice_another_artifact: bool,
    /// **CE20 follow-up Slice 7 — subtype-filtered sacrifice variants.**
    /// "Sacrifice a Food" — the activator picks any permanent they
    /// control whose `subtypes` contains "Food". Mirrors Python's
    /// `ActivationCost.sacrifice_food` at `effects/base.py`. Default
    /// `false`. Rides on the subtypes substrate (`CardPrinting.subtypes`)
    /// landed at commit `03aebefb` / `dd15d7ed`.
    ///
    /// Eligibility: target on activator's bf with `subtypes.contains(
    /// "Food")`. Title Case subtype string per CR 205.3 / Scryfall
    /// convention. The source itself IS eligible iff its own subtypes
    /// include "Food" — "a Food" carries no "another" qualifier (matches
    /// the `sacrifice_a_land` lenient reading from Slice 6).
    ///
    /// **EoE printing affected**: 1 (Ragost, Deft Gastronaut —
    /// `{1}, {T}, Sacrifice a Food: Ragost deals 3 damage to each
    /// opponent.`). Ragost's static ability ALSO confers the "Food"
    /// subtype on every artifact the activator controls, but the static
    /// subtype-conferral layer is out of scope; the test fixture uses
    /// pre-stamped Food subtypes on synthetic printings.
    ///
    /// **Composes with `tap_self` + `mana`.** Order:
    /// mana → tap → sac-food → effect.
    pub sacrifice_food: bool,
    /// **CE20 follow-up Slice 7 — subtype-filtered sacrifice variants.**
    /// "Sacrifice a Desert" — the activator picks any permanent they
    /// control whose `subtypes` contains "Desert". Mirrors Python's
    /// `ActivationCost.sacrifice_a_desert` at `effects/base.py`. Default
    /// `false`. Rides on the subtypes substrate.
    ///
    /// Eligibility: target on activator's bf with `subtypes.contains(
    /// "Desert")`. The printed text reads "Sacrifice a Desert" with no
    /// "another" qualifier, so when the source IS a Desert the source
    /// itself is eligible (mirrors `sacrifice_a_land` / `sacrifice_food`
    /// lenient reading).
    ///
    /// **EoE printings affected**: 0 in EoE today; the substrate ships
    /// without a real-card probe — tests use synthetic Desert printings.
    /// Closes the symmetric pair with `sacrifice_food` and unblocks any
    /// future Desert-cost printing without a structural change.
    pub sacrifice_a_desert: bool,
    /// **CE20 follow-up Slice 5 — Planeswalker loyalty (Slice A).**
    /// Signed loyalty cost (CR 606). Positive values are PAY costs
    /// (the walker LOSES N loyalty counters); negative values are
    /// ADD costs (the walker GAINS |N| loyalty counters). Defaults
    /// to `0` (no loyalty cost). Convention: a printed "+2" ability
    /// stamps `loyalty: -2`; a printed "-3" ability stamps
    /// `loyalty: 3`; a printed "0" ability stamps `loyalty: 0`.
    ///
    /// **Emission gate**: positive `loyalty` values gate
    /// `legal_decisions` emission on the source's `loyalty_counters`
    /// — the walker must have at least `cost.loyalty` counters to
    /// afford the activation. Negative values are always affordable
    /// (a +N ability can fire at any loyalty value).
    ///
    /// **Apply commit** (Phase 5d): `obj.loyalty_counters -=
    /// cost.loyalty`. Signed subtraction handles both directions
    /// uniformly. SBA pass at state_ops_sba.rs catches the
    /// `loyalty_counters <= 0` case and moves the walker to its
    /// controller's graveyard (CR 704.5i).
    ///
    /// **EoE printing affected**: 1 (Tezzeret, Cruel Captain — sole
    /// walker in EoE).
    ///
    /// **Out of scope** of Slice A: combat-damage redirect to
    /// planeswalkers (CR 119.5 / Slice B), once-per-turn-per-walker
    /// ledger (CR 606.3 / Slice C).
    pub loyalty: i32,
}

/// An activated ability on a `CardPrinting`. Mirrors a strict subset
/// of Python's `ActivatedAbility` dataclass at
/// `src/mtg_bot/effects/base.py:447`.
///
/// **Slice 1 scope.** The dispatcher reads `cost` (pays it), `effect`
/// (applies it), and `is_mana_ability` (short-circuits the stack push
/// when true). The richer Python fields — `sorcery_speed`,
/// `cost_reductions`, `room_half`, `tier_threshold`,
/// `activate_only_once` — are deferred to follow-up slices that bring
/// their gates along.
#[derive(Clone, Debug)]
pub struct ActivatedAbility {
    /// Cost to activate the ability. The dispatcher checks
    /// affordability (mana-pool side) then commits the cost (tap +
    /// mana drain) before pushing/applying the effect.
    pub cost: ActivationCost,
    /// Effect to fire when the ability resolves. For
    /// `is_mana_ability=true` abilities the effect fires immediately
    /// on activation (CR 605.3a); for `is_mana_ability=false`
    /// abilities the effect is wrapped in a `StackItem` and fires
    /// on the next `resolve_top_of_stack` pop.
    pub effect: Effect,
    /// `true` when this is a mana ability (CR 605.1 — produces mana
    /// AND doesn't target). Mana abilities bypass the stack and
    /// resolve their effect immediately on activation. For Slice 1
    /// the load-bearing case is `false` (Bear Caster's draw goes
    /// through the stack); a future slice will bridge the legacy
    /// `mana_produced` field into a synthesized `is_mana_ability=true`
    /// ActivatedAbility, retiring the separate `mana_produced` path.
    pub is_mana_ability: bool,
    /// **CE20 follow-up — Spacecraft station-charge.** Minimum
    /// `GameObject.charge_counters` the source must have for this
    /// ability to be activatable. Defaults to `0` (no tier gate);
    /// Spacecraft printings stamp this to their printed tier value
    /// (e.g. Lumen-Class Frigate's level-3 station ability stamps
    /// `tier_threshold: 3`).
    ///
    /// **Usability gate, not a cost.** The source's
    /// `charge_counters` is COMPARED against this value at
    /// `legal_decisions` emission AND at apply-time precheck; the
    /// activation does NOT decrement charge counters (sub-tier
    /// activations are simply unavailable). The cost-pay charge-
    /// counter shape (`Pay N charge counters: ...`) has no EoE
    /// printings and is deferred — search the EoE pool's oracle
    /// text for `Pay [0-9]+ charge counter` returns zero hits.
    ///
    /// Mirrors Python's `ActivatedAbility.tier_threshold: int = 0`
    /// at `effects/base.py:447`.
    pub tier_threshold: i32,
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
    /// MTG card subtypes (the post-em-dash portion of the type line):
    /// creature subtypes ("Bear", "Goblin", "Kavu"), basic-land subtypes
    /// ("Forest", "Island", "Plains"), artifact subtypes ("Equipment",
    /// "Food"), enchantment subtypes ("Aura", "Saga"), etc.
    ///
    /// **Mixed semantics by design.** MTG conflates basic-land subtypes
    /// (Forest, Mountain, ...) with creature/artifact/enchantment
    /// subtypes into a single comprehensive-rules "subtype" namespace
    /// (CR 205.3). The Rust mirror follows Python's
    /// `CardPrinting.subtypes: tuple[str, ...]` — one flat field
    /// holding every subtype regardless of which card-type slot it
    /// belongs to. Consumers that need land-type-only semantics gate
    /// on `card_types.contains("Land")` first.
    ///
    /// Empty Vec when the type line has no subtypes (vanilla
    /// instants/sorceries, generic artifacts). Stored exactly as
    /// printed — Title Case, ASCII (the EoE pool has no
    /// non-ASCII-named subtypes). Case-sensitive comparison via
    /// `subtypes.iter().any(|s| s == "Forest")` is the canonical
    /// consumer pattern.
    ///
    /// Mirrors Python's `CardPrinting.subtypes: tuple[str, ...]` at
    /// `src/mtg_bot/cards/base.py:501`. Registry-dict input under the
    /// `subtypes` key; missing key parses to empty Vec (the
    /// `#[serde(default)]`-equivalent shape — keeps every pre-substrate
    /// registry-dict caller working without modification).
    pub subtypes: Vec<String>,
    /// MTG card supertypes: "Basic", "Legendary", "Snow", "World",
    /// "Token". Empty Vec when the type line has no supertype prefix
    /// (most cards). Stored as Title Case strings exactly as printed
    /// — case-sensitive comparison via
    /// `supertypes.iter().any(|s| s == "Legendary")` is the canonical
    /// consumer pattern.
    ///
    /// **Use cases.** Distinguishes basic vs non-basic lands
    /// (`is_basic_land` = `card_types contains "Land"` AND
    /// `supertypes contains "Basic"`); legendary-rule processing
    /// (`is_legendary` = `supertypes contains "Legendary"`); tutor
    /// filters that scope by supertype (`legendary_creature` filter
    /// in `Effect::SearchLibraryForCard`).
    ///
    /// Mirrors Python's `CardPrinting.supertypes: tuple[str, ...]`
    /// at `src/mtg_bot/cards/base.py:499`. Registry-dict input under
    /// the `supertypes` key; missing key parses to empty Vec
    /// (back-compat — every pre-supertypes registry dict implicitly
    /// omits the key, matches the `subtypes` substrate's parse shape).
    ///
    /// **Round 30 substrate.** Added to unblock the
    /// `legendary_creature` filter on `Effect::SearchLibraryForCard`
    /// (round-21 bridge slice's deferred filter list — see
    /// state_ops_resolve.rs `SearchLibraryForCard` arm). Pre-Round-30
    /// the field didn't exist; the legacy `is_basic_land` proxy in
    /// `SearchLibraryForBasicLandTapped`'s arm comment is now
    /// historical (it still uses `card_types contains "Land"` because
    /// every EoE basic land has card_types=["Land"] and no compound
    /// non-basic land routes through that arm — keeping the proxy
    /// avoids a behavior change for any in-flight fixture without
    /// `supertypes` set).
    pub supertypes: Vec<String>,
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
    ///
    /// **Legacy in flight.** Slice 1 of the ETB-trigger closure
    /// (`docs/RUST_ETB_TRIGGER_AUDIT.md`) introduces
    /// `triggered_abilities` (predicate-path) — the audit's "fix
    /// 4 Python-incompatible properties of the inline `etb_effects`
    /// hatch" plan. The cast-and-resolve site still consults
    /// `etb_effects` as a back-compat shim so existing test fixtures
    /// keep working; new fixtures should use `triggered_abilities`.
    /// Slice 2 fans out the predicate path to every ETB-stamping
    /// site, retiring the inline path.
    pub etb_effects: Vec<Effect>,
    /// **ETB-trigger substrate (Slice 1).** Predicate-style
    /// triggered abilities on this printing. Empty Vec = no
    /// predicate-style triggers (back-compat default — every
    /// pre-Slice-1 registry dict implicitly has this empty).
    /// Future slices add more dispatch sites; today only the
    /// cast-and-resolve path consumes this via
    /// `state_ops_resolve::dispatch_event(Event::Enters, ...)`.
    ///
    /// Mirrors Python's `CardPrinting.triggered_abilities` tuple at
    /// `src/mtg_bot/cards/base.py`. Registry dict input under the
    /// `triggered_abilities` key is parsed by
    /// `parse_triggered_ability` (see this file). Missing key in
    /// the dict = empty Vec (the `#[serde(default)]`-equivalent
    /// shape — keeps every existing registry-dict caller working
    /// without modification).
    pub triggered_abilities: Vec<TriggeredAbility>,
    /// **Activated-ability substrate (CE20 Slice 1).** Cost-paying
    /// activated abilities on this printing. Empty Vec = no activated
    /// abilities of this shape (back-compat default — every
    /// pre-CE20-Slice-1 registry dict implicitly has this empty).
    ///
    /// Mirrors Python's `CardPrinting.activated_abilities` tuple at
    /// `src/mtg_bot/cards/base.py`.
    ///
    /// **Post-bridge invariant (CE20 follow-up).** The legacy
    /// `mana_produced` field is now SYNTHESIZED into a prepended
    /// `ActivatedAbility { is_mana_ability: true, cost: tap_self+free,
    /// effect: AddManaToPool(...) }` entry at parse time (see
    /// `apply_mana_produced_bridge`). Both the registry dict-input
    /// path (`parse_printing`) and the synthetic-state direct-construction
    /// path (`state.rs`) route through the shared helper. The legacy
    /// emission block in `state_ops_legal.rs` and the legacy
    /// `is_legacy_mana_produced` branch in `state_ops_actions.rs` are
    /// gone — single unified path through `activated_abilities`.
    ///
    /// Missing key in the registry dict = empty Vec (no special
    /// serde tag needed; the parser's `dict.get_item` returns
    /// `None`-of-PyAny which the same `match` we use for
    /// `triggered_abilities` maps to `Vec::new()`).
    pub activated_abilities: Vec<ActivatedAbility>,
    /// **CE20 Slice 5 (Walker loyalty — `starting_loyalty` ETB seeding).**
    /// Printed starting loyalty for Planeswalker printings (CR 606.5b
    /// — "as a planeswalker enters the battlefield, its controller
    /// puts a number of loyalty counters on it equal to the number
    /// printed in its lower right corner"). Non-walker printings
    /// carry `0` (the default — no observable effect since the
    /// loyalty-counter slot is only read by the walker SBA pass and
    /// the loyalty cost gate, both gated on `card_types.contains(
    /// "Planeswalker")`).
    ///
    /// **Stamped at ETB time** (every bf-entry call site) — see
    /// `crate::state::seed_starting_loyalty_for_etb`. For non-walker
    /// printings the helper is a no-op; for walker printings whose
    /// `loyalty_counters` is 0 (the freshly-cast shape) the helper
    /// stamps the printed value.
    ///
    /// **EoE pool**: 1 walker printing (Tezzeret, Cruel Captain).
    /// Tezzeret's printed loyalty is 4.
    ///
    /// Mirrors Python's `CardPrinting.starting_loyalty: int = 0`.
    pub starting_loyalty: i32,
    /// **warp_cost substrate (Phase 1, round-63).** EoE "warp"
    /// alternative cast cost. `Some(cost)` when the printing has a
    /// pure fixed-`ManaCost` warp (Red Tiger Mechan {1}{R}, Bygone
    /// Colossus {3}); `None` otherwise (back-compat default — every
    /// pre-Phase-1 registry dict omits the `warp_cost` key, which the
    /// parser maps to `None`, identical to the `mana_produced` /
    /// `power` Option-parse shape). Phase 1 carries ONLY the pure
    /// fixed-cost shape; `warp_additional_life_cost` /
    /// `warp_castable_from_graveyard` are Phase 2 (the bridge filter
    /// `_printing_is_bridge_pure_warp_creature` positively rejects
    /// them so they never reach this field in a Phase-1 deckspec).
    ///
    /// Mirrors Python's `CardPrinting.warp_cost: ManaCost | None`
    /// at `src/mtg_bot/cards/base.py:515`. The cast pipeline
    /// (`state_ops_cast.rs::cast_creature_warp`) pays THIS instead of
    /// `mana_cost` when `Action::CastSpell{use_warp:true}`; the
    /// legal emitter (`state_ops_legal.rs`) offers the
    /// `use_warp=true` CastSpell variant iff this is `Some`.
    pub warp_cost: Option<ManaCost>,
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

    /// Round-55 token-identity bit. Mirrors Python's
    /// `CardPrinting.is_token` (`cards/base.py:1036`), which is
    /// `"Token" in self.supertypes`. Rust's `CardPrinting` already
    /// carries the Round-30 `supertypes: Vec<String>` substrate, and
    /// the cross-engine bridge round-trips a token printing's
    /// `("Token",)` supertype tuple verbatim through
    /// `build_rust_state`'s `printing_dict["supertypes"]` (so a token
    /// registered cross-engine is `is_token` on BOTH sides). No new
    /// per-printing field is needed — token-ness is a pure derivation
    /// of the existing supertypes Vec, exactly as on the Python side.
    ///
    /// An unknown printing id (registry miss) is treated as
    /// non-token, matching the fail-open convention used by
    /// `mark_left_battlefield_if_nonland` for the LTB void flag.
    /// Token-creation arms (`CreateToken` / `CreateTokenTapped` /
    /// `CreateTokenEachPlayer`) reference a `token_printing_id` that
    /// was registered with the `("Token",)` supertype tuple, so the
    /// freshly-minted GameObjects resolve as tokens here without any
    /// per-object flag.
    pub fn is_token(&self, id: u32) -> bool {
        self.lookup(id)
            .map(|p| p.supertypes.iter().any(|s| s == "Token"))
            .unwrap_or(false)
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
        "mill_target_player" => {
            // Python's `MillTargetPlayer(amount: int = 1)` carries a
            // default amount. The Rust bridge uses `count` (mirrors the
            // `mill` arm's field name + the Mill / ScryN / Surveil /
            // DrawCards / DamageEachOpponent count-field convention)
            // and requires the field — missing `count` is a KeyError
            // at register time. Negative `count` surfaces at register
            // time (defense-in-depth; `apply_effect` re-checks).
            let count: i32 = require(dict, "count")?.extract()?;
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "mill_target_player: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::MillTargetPlayer { count })
        }
        "mill_target_player_equal_to_your_life_total" => {
            // BLOCKED-RUST-EFFECT slice (round 42) — mill an opponent
            // a number of cards equal to the source-controller's
            // current life total. Unit variant; no fields beyond
            // `kind` (the count is dynamic — read from state at
            // resolve time). Extra dict fields silently ignored for
            // round-trip dict-shape consistency (mirrors every other
            // unit-variant parse arm — round 30 / 31 / 33 / 34 / 35 /
            // 36 / 37 precedent). Mirrors Python's
            // `MillTargetPlayer(use_controller_life=True)`
            // (`draw_mill.py:151` — Space-Time Anomaly's instant
            // resolution).
            Ok(Effect::MillTargetPlayerEqualToYourLifeTotal)
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
        "destroy_target_creature_then_draw_if_undamaged" => {
            // BLOCKED-RUST-EFFECT slice — Faller's Faithful ETB.
            // Payload variant: `draw_amount` (cards the destroyed
            // creature's controller draws iff it carried no marked
            // damage). Missing `draw_amount` defaults to 0 (Python
            // parity: `draw_if_undamaged_amount: int = 0` — a 0 rider
            // is a legal "destroy with no draw" shape). Negative
            // `draw_amount` clamps to 0 at resolve (matching the
            // X-from-count zero short-circuit convention).
            let draw_amount: i32 = match dict.get_item("draw_amount")? {
                Some(v) => v.extract()?,
                None => 0,
            };
            Ok(Effect::DestroyTargetCreatureThenDrawIfUndamaged { draw_amount })
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
        "create_token_each_player" => {
            // BLOCKED-RUST-EFFECT slice (round 43) -- each living
            // player creates `count` tokens of the given printing
            // under their own control. Sister of the static
            // `create_token` arm above; same field schema (`count`
            // + `token_printing_id`), distinguished by variant
            // (closed-vocab convention -- the each-player vs
            // self-only choice rides on the variant name, not a
            // boolean field, mirroring round-19/30/31/.. sister-
            // variant precedent). Mirrors Python's
            // `CreateToken(token_printing=..., count=N,
            // each_player=True)` (`tokens.py:198`).
            let count: i32 = require(dict, "count")?.extract()?;
            let token_printing_id: u32 = require(dict, "token_printing_id")?.extract()?;
            Ok(Effect::CreateTokenEachPlayer { count, token_printing_id })
        }
        "create_token_tapped" => {
            // Phase 6 token-printing substrate -- Phase 4 (round 50).
            // Sister of the static `create_token` arm above; same
            // two-field schema (`count` + `token_printing_id`),
            // distinguished by variant (closed-vocab convention -- the
            // tapped-vs-untapped choice rides on the variant name, not
            // a boolean field, mirroring the round-43
            // `create_token_each_player` sister + round-19/30/31/..
            // sister-variant precedent). Mirrors Python's
            // `CreateToken(token_printing=..., count=N, tapped=True)`
            // (`tokens.py:286-287`). EoE consumer: Gravpack Monoist
            // ("When this creature dies, create a tapped 2/2 Robot
            // token." -- 25,252 17lands decks).
            let count: i32 = require(dict, "count")?.extract()?;
            let token_printing_id: u32 = require(dict, "token_printing_id")?.extract()?;
            Ok(Effect::CreateTokenTapped { count, token_printing_id })
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
        "surveil" => {
            // Python's `Surveil(amount: int = 1)` dataclass has an
            // `amount` field defaulting to 1. The Rust bridge mirrors
            // ScryN's shape (sibling effect: same look-at-top-N pattern,
            // different destination zone) and uses `count` here to stay
            // consistent with ScryN's parser arm. Missing `count` is a
            // KeyError at register time — there's no first-slice
            // default since Surveil's printed value is always present
            // on real cards. Negative `count` surfaces at register time
            // (defense-in-depth; `apply_effect` re-checks).
            let count: i32 = require(dict, "count")?.extract()?;
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "surveil: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::Surveil { count })
        }
        "counter_target_spell" => {
            // Unit variant — no required fields. Python's
            // `CounterTargetSpell.filter_types` is intentionally
            // dropped from the Rust first slice (see the variant's
            // docstring). Any extra keys on the dict are ignored,
            // matching the silent-drop convention for unrecognized
            // keys elsewhere in the parser.
            Ok(Effect::CounterTargetSpell)
        }
        "return_creature_from_your_graveyard_to_battlefield" => {
            // Unit variant — no required fields. Python's unified
            // `ReturnFromGraveyard` carries optional widening / capping
            // fields (`or_enchantment`, `or_spacecraft`, `or_artifact`,
            // `max_mv`, `max_n`, ...) that the Rust first slice
            // intentionally drops (see the variant's docstring). Any
            // extra keys on the dict are ignored, matching the silent-
            // drop convention elsewhere in the parser.
            Ok(Effect::ReturnCreatureFromYourGraveyardToBattlefield)
        }
        "return_enchantment_or_creature_from_your_graveyard_to_battlefield" => {
            // **Phase 5 rider-widened parse arm.** Unit variant; the
            // disjunction (enchantment OR creature) is baked into the
            // variant identity itself, so no fields beyond `kind`.
            // Mirrors Python's
            // `ReturnCreatureFromYourGraveyardToBattlefield(or_enchantment=True)`
            // — extra dict fields are silently ignored for round-trip
            // dict-shape consistency. This is the to-BATTLEFIELD
            // sibling of the existing
            // `return_enchantment_or_creature_from_your_graveyard_to_hand`
            // arm; the destination delta is the load-bearing difference.
            // EoE consumer: Rescue Skiff (real-EoE).
            Ok(Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield)
        }
        "discard_self" => {
            // Python's `DiscardSelf(amount: int = 1)` dataclass has
            // an `amount` field defaulting to 1. Mirror that here:
            // missing `amount` defaults to 1, present `amount`
            // extracts as i32. Negative `amount` surfaces at register
            // time (defense-in-depth; `apply_effect` re-checks).
            // Mirrors PutPlusOneCounterOnSelf's default-handling
            // shape.
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "discard_self.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "discard_self: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::DiscardSelf { amount })
        }
        "each_opponent_loses_life" => {
            // Python's `EachOpponentLosesLife(amount: int)` carries
            // a required `amount` field with no default. Mirror that
            // here: missing `amount` is a KeyError at register time;
            // negative amount surfaces at register time (defense-in-
            // depth; `apply_effect` re-checks).
            let amount: i32 = require(dict, "amount")?.extract()?;
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "each_opponent_loses_life: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::EachOpponentLosesLife { amount })
        }
        "each_opponent_loses_life_equal_to_artifact_count" => {
            // BLOCKED-RUST-EFFECT slice (round 44) -- each opponent of
            // the source-controller loses life equal to the
            // source-controller's artifact count. Unit variant; no
            // fields beyond `kind` (the count is dynamic -- read from
            // state at resolve time). Extra dict fields silently
            // ignored for round-trip dict-shape consistency (mirrors
            // every other unit-variant parse arm; particularly the
            // round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`, the
            // round-34 sister `surveil_x_equal_to_artifact_count`, and
            // the round-37 sister
            // `deal_damage_to_opponent_creature_by_creatures_you_control`
            // which share the X-from-count plumbing with this arm but
            // use a different apply substrate). Mirrors Python's
            // `EachOpponentLosesLifeEqualToArtifactCount` (`life.py` --
            // shipped in this slice as the FIFTH apply substrate to
            // pick up the X-from-count plumbing; 0 EoE consumers today,
            // slice ships per round-27/31/37 round-trip-surface-coverage
            // rule and to extend the X-from-count substrate axis to a
            // FIFTH entry, confirming the round-35 bidirectionally-
            // extensible plumbing generalizes across both axes).
            Ok(Effect::EachOpponentLosesLifeEqualToArtifactCount)
        }
        "each_opponent_loses_life_equal_to_your_life_total" => {
            // BLOCKED-RUST-EFFECT slice (round 48) -- each opponent of
            // the source-controller loses life equal to the
            // source-controller's CURRENT LIFE TOTAL. Unit variant; no
            // fields beyond `kind` (the count is dynamic -- read from
            // state at resolve time, clamped to >= 0). Extra dict
            // fields silently ignored for round-trip dict-shape
            // consistency (mirrors every other unit-variant parse arm;
            // particularly the round-44 sister
            // `each_opponent_loses_life_equal_to_artifact_count` -- same
            // apply substrate, only the denominator read differs -- and
            // the round-42 `mill_target_player_equal_to_your_life_total`
            // / round-47 `deal_damage_to_opponent_creature_by_life_total`
            // life-total-denominator precedents on OTHER substrates).
            // Mirrors Python's `EachOpponentLosesLifeEqualToYourLifeTotal`
            // (`life.py` -- shipped in this slice as the SECOND
            // denominator on the life-loss-each-opponent apply
            // substrate; 0 EoE consumers today, slice ships per
            // round-27/31/37 round-trip-surface-coverage rule and to
            // extend the X-from-count matrix to a third (substrate,
            // life-total) cell, confirming the round-35 bidirectionally-
            // extensible plumbing generalizes across both axes).
            Ok(Effect::EachOpponentLosesLifeEqualToYourLifeTotal)
        }
        "gain_life_equal_to_artifact_count" => {
            // BLOCKED-RUST-EFFECT slice (round 45) -- the source's
            // controller GAINS life equal to the source-controller's
            // artifact count. Unit variant; no fields beyond `kind`
            // (the count is dynamic -- read from state at resolve
            // time). Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-variant
            // parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`,
            // the round-34 sister `surveil_x_equal_to_artifact_count`,
            // the round-37 sister
            // `deal_damage_to_opponent_creature_by_creatures_you_control`,
            // and the round-44 sister
            // `each_opponent_loses_life_equal_to_artifact_count`
            // which share the X-from-count plumbing with this arm but
            // use a different apply substrate). Mirrors Python's
            // `GainLifeEqualToArtifactCount` (`life.py` -- shipped in
            // this slice as the SIXTH apply substrate to pick up the
            // X-from-count plumbing; 0 EoE consumers today, slice
            // ships per round-27/31/37 round-trip-surface-coverage rule
            // and to extend the X-from-count substrate axis to a SIXTH
            // entry, confirming the round-35 bidirectionally-extensible
            // plumbing generalizes across both axes). This arm is the
            // controller-self MIRROR of round-44's each-opponent-life-
            // loss arm: same denominator (artifact-count), same
            // dispatch shape, inverted recipient (controller-self) AND
            // inverted sign (gain vs loss).
            Ok(Effect::GainLifeEqualToArtifactCount)
        }
        "gain_life_equal_to_your_life_total" => {
            // BLOCKED-RUST-EFFECT slice (round 49) -- the source's
            // controller GAINS life equal to the source-controller's
            // CURRENT LIFE TOTAL. Unit variant; no fields beyond `kind`
            // (the count is dynamic -- read from state at resolve time,
            // clamped to >= 0). Extra dict fields silently ignored for
            // round-trip dict-shape consistency (mirrors every other
            // unit-variant parse arm; particularly the round-45 sister
            // `gain_life_equal_to_artifact_count` -- SAME apply
            // substrate (gain-life-controller-self), only the
            // denominator read differs -- and the round-42
            // `mill_target_player_equal_to_your_life_total` / round-47
            // `deal_damage_to_opponent_creature_by_life_total` /
            // round-48 `each_opponent_loses_life_equal_to_your_life_total`
            // life-total-denominator precedents on OTHER substrates).
            // Mirrors Python's `GainLifeEqualToYourLifeTotal`
            // (`life.py` -- shipped in this slice as the SECOND
            // denominator on the gain-life-controller-self apply
            // substrate; 0 EoE consumers today, slice ships per
            // round-27/31/37 round-trip-surface-coverage rule and to
            // extend the X-from-count matrix to a FOURTH (substrate,
            // life-total) cell, confirming the round-35 bidirectionally-
            // extensible plumbing generalizes across both axes).
            Ok(Effect::GainLifeEqualToYourLifeTotal)
        }
        "lose_life" => {
            // Python's `LoseLife(amount: int)` carries a required
            // `amount` field with no default. Mirror that here: missing
            // `amount` is a KeyError at register time; negative amount
            // surfaces at register time (defense-in-depth;
            // `apply_effect` re-checks). Distinct from
            // `each_opponent_loses_life` — same shape but the
            // dispatch subtracts from the source's CONTROLLER's life
            // (not the opponent's).
            let amount: i32 = require(dict, "amount")?.extract()?;
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "lose_life: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::LoseLife { amount })
        }
        "target_opponent_loses_life" => {
            // Python's `TargetOpponentLosesLife(amount: int = 1)` has
            // an `amount` field defaulting to 1. Mirror that here:
            // missing `amount` defaults to 1, present `amount` extracts
            // as i32. Negative `amount` surfaces at register time
            // (defense-in-depth; `apply_effect` re-checks). Distinct
            // from `each_opponent_loses_life` — same round-26 source-
            // finder dispatch shape in 2-player land, but the variant
            // stays separate to mirror Python's closed Effect
            // vocabulary (targeted vs each-opponent semantics).
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "target_opponent_loses_life.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "target_opponent_loses_life: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::TargetOpponentLosesLife { amount })
        }
        "each_opponent_discards" => {
            // Python's `EachOpponentDiscards(count: int = 1)` dataclass
            // has a `count` field defaulting to 1. Mirror that here:
            // missing `count` defaults to 1, present `count` extracts as
            // i32. Negative `count` surfaces at register time (defense-
            // in-depth; `apply_effect` re-checks). Mirrors DiscardSelf /
            // TargetOpponentLosesLife default-handling shape rather than
            // EachOpponentLosesLife's required-amount shape.
            let count: i32 = match dict.get_item("count")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "each_opponent_discards.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "each_opponent_discards: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::EachOpponentDiscards { count })
        }
        "destroy_all_creatures" => {
            // Unit variant — no required fields. Python's
            // `DestroyAllCreatures` carries optional narrowing fields
            // (`tapped_only`, `untapped_only`, `min_power`) that the
            // Rust first slice intentionally drops (see the variant's
            // docstring). Any extra keys on the dict are ignored,
            // matching the silent-drop convention for unrecognized
            // keys elsewhere in the parser.
            Ok(Effect::DestroyAllCreatures)
        }
        "destroy_target_nonland_permanent" => {
            // Unit variant — no required fields. Filter is intrinsic
            // ("non-Land, non-indestructible"). Extra keys ignored.
            Ok(Effect::DestroyTargetNonlandPermanent)
        }
        "destroy_target_artifact" => {
            // Unit variant — no required fields. Filter is intrinsic
            // ("Artifact, non-indestructible"). Extra keys ignored.
            // Mirrors `destroy_target_nonland_permanent` parser arm
            // shape (silent-drop convention for unrecognized keys).
            Ok(Effect::DestroyTargetArtifact)
        }
        "destroy_target_land" => {
            // Unit variant — no required fields. Filter is intrinsic
            // ("Land, non-indestructible"). Extra keys ignored.
            // Mirrors `destroy_target_artifact` parser arm shape
            // (silent-drop convention for unrecognized keys); only the
            // intrinsic filter differs.
            Ok(Effect::DestroyTargetLand)
        }
        "destroy_target_noncreature_permanent" => {
            // Round-52 — Extinguisher Battleship ETB head. Unit
            // variant — no required fields. Filter is intrinsic
            // ("non-Creature, non-indestructible"). Extra keys
            // ignored. Mirrors `destroy_target_nonland_permanent`
            // parser arm shape (silent-drop convention for
            // unrecognized keys); only the intrinsic filter differs
            // (Creature-exclude vs Land-exclude).
            Ok(Effect::DestroyTargetNoncreaturePermanent)
        }
        "destroy_target_artifact_or_tapped_creature" => {
            // Effect-uncovered Tier-A — Radiant Strike inner half.
            // Unit variant — no required fields. Filter is intrinsic
            // ("Artifact OR (Creature AND tapped), non-indestructible").
            // Extra keys ignored. Mirrors `destroy_target_artifact`
            // parser arm shape (silent-drop convention for
            // unrecognized keys); only the intrinsic filter differs
            // (artifact-OR-tapped-creature vs artifact-only).
            Ok(Effect::DestroyTargetArtifactOrTappedCreature)
        }
        "seedship_impact_effect" => {
            // Effect-uncovered Tier-A — Seedship Impact (Lander-rider).
            // Single-field payload: the Lander's `token_printing_id`
            // (registry index). Mirrors the `create_token` parse arm's
            // `require(dict, "token_printing_id")` shape — the bespoke
            // arm needs the pid to mint the Lander (Rust has no
            // intrinsic Lander). Python's `SeedshipImpactEffect` is
            // field-free; the pid is a Rust-side carrier dropped at
            // the bridge.
            let token_printing_id: u32 =
                require(dict, "token_printing_id")?.extract()?;
            Ok(Effect::SeedshipImpactEffect { token_printing_id })
        }
        "deal_damage_any_target" => {
            // Python's `DealDamageAnyTarget(DealDamage)` carries the
            // inherited `amount` field plus an `optional: bool` slot
            // flag (added for Pinnacle Kill-Ship's "up to one target
            // creature" shape — flips Python's slot count_min to 0).
            // The "any target" filter is intrinsic to the variant
            // (no `target` dict to parse — distinct from
            // `deal_damage`'s required `target` field). Missing
            // `amount` is a KeyError at register time; negative
            // amount surfaces at register time (defense-in-depth;
            // `apply_effect` re-checks). The `optional` key is
            // tolerated as an ignored extra field — Rust's
            // deterministic at-apply-time target pick (scan
            // defender's bf for first creature, fall back to
            // defender-player) is observably equivalent to Python's
            // optional-target "no-target fizzle" only on probes that
            // drive a single opponent creature on bf, but the dict-
            // shape round-trip needs both sides to accept the same
            // keyset for a clean register-on-both-engines contract
            // (silent-drop convention matches the broader parser).
            let amount: i32 = require(dict, "amount")?.extract()?;
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "deal_damage_any_target: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::DealDamageAnyTarget { amount })
        }
        "pump_self_until_eot" => {
            // Round-27 UEOT-framework proof. Python's
            // `PumpSelfUntilEOT(power_bonus: int = 0,
            // toughness_bonus: int = 0)` defaults each field to 0;
            // the Rust bridge mirrors the default-handling shape used
            // by `DiscardSelf` / `PutPlusOneCounterOnSelf` /
            // `EachOpponentDiscards` (`dict.get_item` with explicit
            // default rather than `require`). Either field absent =
            // 0; both absent registers a 0/0 no-op (legal for parity
            // edge cases). NEGATIVES are deliberately allowed —
            // Python's PumpSelfUntilEOT accepts negative bonuses for
            // debuff-shaped self-pumps (e.g. cards that shrink
            // themselves for a beneficial side-effect). Mirrors the
            // schema's `int` annotation (no non-negative guard) so a
            // future pool card with a negative self-pump doesn't fail
            // registration here.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_self_until_eot.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_self_until_eot.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus })
        }
        "pump_target_creature_until_eot" => {
            // Round-28 UEOT-coverage extension. Mirrors the
            // `pump_self_until_eot` schema: `power_bonus` and
            // `toughness_bonus` default to 0; negatives allowed for
            // debuff-shaped target effects.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_creature_until_eot.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_creature_until_eot.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpTargetCreatureUntilEOT { power_bonus, toughness_bonus })
        }
        "pump_target_creature_until_eot_grant_dies_return_tapped" => {
            // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner
            // ETB. Same `power_bonus` / `toughness_bonus` schema as
            // `pump_target_creature_until_eot` (both default to 0;
            // negatives allowed for symmetry, though Perigee is +2/+0).
            // The "another / you-control" target restriction and the
            // granted dies-return-tapped rider are baked into the
            // variant identity — no extra dict fields (the rider is
            // the fixed Perigee shape, not a generic ability payload;
            // the general nested-trigger-grant subsystem is the
            // deferred half — see the variant doc-comment + round-60
            // SEARCH_LIMITATIONS). Extra keys silently ignored for
            // round-trip dict-shape consistency.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_creature_until_eot_grant_dies_return_tapped.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_creature_until_eot_grant_dies_return_tapped.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpTargetCreatureUntilEotGrantDiesReturnTapped {
                power_bonus,
                toughness_bonus,
            })
        }
        "fight_target_creature_with_target_creature" => {
            // BLOCKED-RUST-EFFECT slice — Fight effect arm. Unit
            // variant; the bilateral source-creature-fights-opponent-
            // creature shape is baked into the variant identity, so
            // no fields beyond `kind`. Extra dict fields are silently
            // ignored for round-trip dict-shape consistency (mirrors
            // every other unit-variant parse arm).
            //
            // Mirrors Python's `FightTargetCreatureWithTargetCreature`
            // generic-fight class shipped on the bridge in the same
            // slice.
            Ok(Effect::FightTargetCreatureWithTargetCreature)
        }
        "double_target_creatures_power_ueot" => {
            // BLOCKED-RUST-EFFECT slice (round 31) — double target
            // creature's power UEOT. Unit variant; no fields beyond
            // `kind`. Extra dict fields silently ignored for round-
            // trip dict-shape consistency (mirrors every other unit-
            // variant parse arm). Mirrors Python's
            // `DoubleTargetCreaturesPowerUEOT` (`pump.py:194` —
            // Mightform Harmonizer's landfall trigger).
            Ok(Effect::DoubleTargetCreaturesPowerUEOT)
        }
        "deal_damage_to_opponent_creature_by_artifact_count" => {
            // BLOCKED-RUST-EFFECT slice (round 32) — deal damage to
            // an opponent's creature equal to the source-controller's
            // artifact count. Unit variant; no fields beyond `kind`
            // (the count is dynamic — read from state at resolve
            // time). Extra dict fields silently ignored for round-
            // trip dict-shape consistency (mirrors every other unit-
            // variant parse arm). Mirrors Python's
            // `DealDamageToOpponentCreatureByArtifactCount`
            // (`damage.py:406` — Warmaker Gunship's ETB).
            Ok(Effect::DealDamageToOpponentCreatureByArtifactCount)
        }
        "two_subject_pump_and_debuff_by_artifact_count" => {
            // BLOCKED-RUST-EFFECT slice (round 51) — Monoist
            // Circuit-Feeder ETB (real EoE card; 14,727 17lands
            // decks). Until EOT: source-controller's first creature
            // gets +X/+0, an opponent's first creature gets -0/-X,
            // X = source-controller's artifact count. Unit variant;
            // no fields beyond `kind` (X is dynamic — read from
            // state at resolve time, clamped >= 0). Extra dict
            // fields silently ignored for round-trip dict-shape
            // consistency (mirrors every other unit-variant parse
            // arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`
            // — SAME artifact-count denominator read, NEW two-
            // subject until-EOT pump+debuff apply substrate).
            // Mirrors Python's deterministic-pick bridge sibling
            // `PumpYoursAndDebuffOpponentByArtifactCountUntilEOT`
            // (`pump.py`). NOT loader-admitted — the real card's
            // agent-driven `PairedTargetPumpDebuffUEOT` would
            // silently degrade through the deterministic bridge
            // (§2; see the variant docstring + SEARCH_LIMITATIONS).
            Ok(Effect::TwoSubjectPumpAndDebuffByArtifactCount)
        }
        "deal_damage_to_opponent_creature_by_cards_in_hand" => {
            // BLOCKED-RUST-EFFECT slice (round 35) — deal damage to
            // an opponent's creature equal to the source-controller's
            // hand size. Unit variant; no fields beyond `kind` (the
            // count is dynamic — read from state at resolve time).
            // Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-
            // variant parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`
            // which shares the apply substrate with this arm but
            // uses an artifact-count denominator instead). Mirrors
            // Python's `DealDamageToOpponentCreatureByCardsInHand`
            // (`damage.py:464` — Roaring Furnace's door trigger,
            // 1 EoE consumer).
            Ok(Effect::DealDamageToOpponentCreatureByCardsInHand)
        }
        "deal_damage_to_opponent_creature_by_lands_controlled" => {
            // BLOCKED-RUST-EFFECT slice (round 36) — deal damage to
            // an opponent's creature equal to the source-controller's
            // lands count. Unit variant; no fields beyond `kind` (the
            // count is dynamic — read from state at resolve time).
            // Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-
            // variant parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`
            // and the round-35 sister
            // `deal_damage_to_opponent_creature_by_cards_in_hand`
            // which share the apply substrate with this arm but use
            // an artifact-count / hand-size denominator instead).
            // Mirrors Python's
            // `DealDamageToOpponentCreatureByLandsControlled`
            // (`damage.py` -- shipped in this slice as a sister of
            // the round-32/35 classes; 0 EoE consumers today, slice
            // ships per round-27/31 round-trip-surface-coverage rule
            // and to complete the THIRD orthogonal denominator on the
            // round-32 damage-to-opponent-creature substrate).
            Ok(Effect::DealDamageToOpponentCreatureByLandsControlled)
        }
        "deal_damage_to_opponent_creature_by_creatures_you_control" => {
            // BLOCKED-RUST-EFFECT slice (round 37) -- deal damage to
            // an opponent's creature equal to the source-controller's
            // creatures count. Unit variant; no fields beyond `kind`
            // (the count is dynamic -- read from state at resolve
            // time). Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-variant
            // parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`, the
            // round-35 sister
            // `deal_damage_to_opponent_creature_by_cards_in_hand`, and
            // the round-36 sister
            // `deal_damage_to_opponent_creature_by_lands_controlled`
            // which share the apply substrate with this arm but use an
            // artifact-count / hand-size / lands-controlled denominator
            // instead). Mirrors Python's
            // `DealDamageToOpponentCreatureByCreaturesYouControl`
            // (`damage.py` -- shipped in this slice as a sister of the
            // round-32/35/36 classes; 0 EoE consumers today, slice
            // ships per round-27/31 round-trip-surface-coverage rule
            // and to complete the FOURTH orthogonal denominator on the
            // round-32 damage-to-opponent-creature substrate).
            Ok(Effect::DealDamageToOpponentCreatureByCreaturesYouControl)
        }
        "deal_damage_to_opponent_creature_by_cards_in_graveyard" => {
            // BLOCKED-RUST-EFFECT slice (round 46) -- deal damage to
            // an opponent's creature equal to the source-controller's
            // graveyard size. Unit variant; no fields beyond `kind`
            // (the count is dynamic -- read from state at resolve
            // time). Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-variant
            // parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`,
            // the round-35 sister
            // `deal_damage_to_opponent_creature_by_cards_in_hand`, the
            // round-36 sister
            // `deal_damage_to_opponent_creature_by_lands_controlled`,
            // and the round-37 sister
            // `deal_damage_to_opponent_creature_by_creatures_you_control`
            // which share the apply substrate with this arm but use an
            // artifact-count / hand-size / lands-controlled /
            // creatures-controlled denominator instead). Mirrors
            // Python's `DealDamageToOpponentCreatureByCardsInGraveyard`
            // (`damage.py` -- shipped in this slice as a sister of the
            // round-32/35/36/37 classes; 0 EoE consumers today, slice
            // ships per round-27/31 round-trip-surface-coverage rule
            // and to complete the FIFTH orthogonal denominator on the
            // round-32 damage-to-opponent-creature substrate. SIXTH
            // overall X-from-count denominator across the substrate
            // matrix -- prior five: artifact / hand / lands / creatures
            // / life-total; this slice adds GRAVEYARD as the first
            // zone-size denominator pulled from a non-battlefield,
            // non-hand source).
            Ok(Effect::DealDamageToOpponentCreatureByCardsInGraveyard)
        }
        "deal_damage_to_opponent_creature_by_life_total" => {
            // BLOCKED-RUST-EFFECT slice (round 47) -- deal damage to
            // an opponent's creature equal to the source-controller's
            // life total. Unit variant; no fields beyond `kind` (the
            // count is dynamic -- read from state at resolve time).
            // Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors every other unit-variant
            // parse arm; particularly the round-32 sister
            // `deal_damage_to_opponent_creature_by_artifact_count`,
            // the round-35 sister
            // `deal_damage_to_opponent_creature_by_cards_in_hand`, the
            // round-36 sister
            // `deal_damage_to_opponent_creature_by_lands_controlled`,
            // the round-37 sister
            // `deal_damage_to_opponent_creature_by_creatures_you_control`,
            // and the round-46 sister
            // `deal_damage_to_opponent_creature_by_cards_in_graveyard`
            // which share the apply substrate with this arm but use an
            // artifact-count / hand-size / lands-controlled /
            // creatures-controlled / graveyard-size denominator
            // instead). Mirrors Python's
            // `DealDamageToOpponentCreatureByLifeTotal` (`damage.py`
            // -- shipped in this slice as a sister of the
            // round-32/35/36/37/46 classes; 0 EoE consumers today,
            // slice ships per round-27/31 round-trip-surface-coverage
            // rule and to COMPLETE the SIXTH (final) orthogonal
            // denominator on the round-32 damage-to-opponent-creature
            // substrate -- the damage substrate row is now fully
            // saturated across the artifact / hand / lands / creatures
            // / graveyard / life-total denominator axis).
            Ok(Effect::DealDamageToOpponentCreatureByLifeTotal)
        }
        "put_plus_one_counters_on_self_per_other_creature_or_artifact" => {
            // BLOCKED-RUST-EFFECT slice (round 33) — put a +1/+1
            // counter on this creature for each OTHER creature and/or
            // artifact you control. Unit variant; no fields beyond
            // `kind` (the count is dynamic — read from state at
            // resolve time). Extra dict fields silently ignored for
            // round-trip dict-shape consistency (mirrors every other
            // unit-variant parse arm). Mirrors Python's
            // `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`
            // (`counters.py:394` — Luxknight Breacher's ETB).
            Ok(Effect::PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact)
        }
        "surveil_x_equal_to_artifact_count" => {
            // BLOCKED-RUST-EFFECT slice (round 34) — surveil X, where
            // X is the source-controller's artifact count. Unit
            // variant; no fields beyond `kind` (the count is dynamic —
            // read from state at resolve time). Extra dict fields
            // silently ignored for round-trip dict-shape consistency
            // (mirrors every other unit-variant parse arm). Mirrors
            // Python's `Surveil(use_artifact_count=True)`
            // (`library_lookat.py:569` — Cerebral Download's
            // surveil-X clause).
            Ok(Effect::SurveilXEqualToArtifactCount)
        }
        "return_creature_from_your_graveyard_to_hand" => {
            // Unit variant; no fields beyond `kind`.
            Ok(Effect::ReturnCreatureFromYourGraveyardToHand)
        }
        "return_artifact_or_creature_from_your_graveyard_to_hand" => {
            // **Phase 5 rider-widened parse arm.** Unit variant; the
            // disjunction (artifact OR creature) is baked into the
            // variant identity itself, so no fields beyond `kind`.
            // Mirrors Python's
            // `ReturnCreatureFromYourGraveyardToHand(or_artifact=True)`
            // — extra dict fields are silently ignored for round-trip
            // dict-shape consistency.
            Ok(Effect::ReturnArtifactOrCreatureFromYourGraveyardToHand)
        }
        "return_creature_or_spacecraft_from_your_graveyard_to_hand" => {
            // **Phase 5 rider-widened parse arm.** Unit variant; the
            // disjunction (creature OR Spacecraft subtype) is baked
            // into the variant identity itself, so no fields beyond
            // `kind`. Mirrors Python's
            // `ReturnCreatureFromYourGraveyardToHand(or_spacecraft=True)`
            // — extra dict fields are silently ignored.
            Ok(Effect::ReturnCreatureOrSpacecraftFromYourGraveyardToHand)
        }
        "return_enchantment_or_creature_from_your_graveyard_to_hand" => {
            // **Phase 5 rider-widened parse arm.** Unit variant; the
            // disjunction (enchantment OR creature) is baked into the
            // variant identity itself, so no fields beyond `kind`.
            // Mirrors Python's
            // `ReturnCreatureFromYourGraveyardToHand(or_enchantment=True)`
            // — extra dict fields are silently ignored for round-trip
            // dict-shape consistency.
            Ok(Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToHand)
        }
        "put_plus_one_counter_on_each_creature_you_control" => {
            // Python's PutPlusOneCounterOnEachCreatureYouControl
            // dataclass has amount: int = 1. Mirror that.
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_plus_one_counter_on_each_creature_you_control.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "put_plus_one_counter_on_each_creature_you_control: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::PutPlusOneCounterOnEachCreatureYouControl { amount })
        }
        "put_card_from_graveyard_on_bottom_of_library" => {
            // Unit variant; no fields.
            Ok(Effect::PutCardFromGraveyardOnBottomOfLibrary)
        }
        "move_self_counters_to_target_creature_you_control" => {
            Ok(Effect::MoveSelfCountersToTargetCreatureYouControl)
        }
        "deal_damage_equal_to_source_power_any_target" => {
            Ok(Effect::DealDamageEqualToSourcePowerAnyTarget)
        }
        "tap_target_artifact_or_creature" => {
            Ok(Effect::TapTargetArtifactOrCreature)
        }
        "create_token_copy_of_target_creature_you_control" => {
            Ok(Effect::CreateTokenCopyOfTargetCreatureYouControl)
        }
        "optional_sac_artifact_for_effect" => {
            let nested = dict.get_item("inner_effect")?.ok_or_else(|| {
                PyValueError::new_err(
                    "optional_sac_artifact_for_effect: missing required 'inner_effect' field",
                )
            })?;
            let nested_dict = nested.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "optional_sac_artifact_for_effect.inner_effect must be a dict",
                )
            })?;
            let inner = parse_effect(nested_dict)?;
            Ok(Effect::OptionalSacArtifactForEffect {
                inner_effect: Box::new(inner),
            })
        }
        "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library" => {
            // Unit variant; no fields.
            Ok(Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary)
        }
        "attach_to_target_creature_you_control" => {
            Ok(Effect::AttachToTargetCreatureYouControl)
        }
        "equip_to_target_creature_you_control" => {
            Ok(Effect::EquipToTargetCreatureYouControl)
        }
        "destroy_enchanted_permanent" => {
            Ok(Effect::DestroyEnchantedPermanent)
        }
        "tap_enchanted_permanent" => {
            Ok(Effect::TapEnchantedPermanent)
        }
        "put_stun_counter_on_tapped_creature" => {
            // Unit variant; no fields. Mirrors Python's
            // PutStunCounterOnTappedCreature with no constructor args.
            Ok(Effect::PutStunCounterOnTappedCreature)
        }
        "tap_target_opponent_permanent_and_stun_it" => {
            // Unit variant; no fields. Mirrors Python's
            // TapTargetOpponentPermanentAndStunIt with no constructor
            // args. Both the tap and the stun-counter increment apply
            // to the same chosen target.
            Ok(Effect::TapTargetOpponentPermanentAndStunIt)
        }
        "exile_target_creature_until_source_leaves" => {
            Ok(Effect::ExileTargetCreatureUntilSourceLeaves)
        }
        "exile_opponents_nonland_permanent_until_leaves" => {
            Ok(Effect::ExileOpponentsNonlandPermanentUntilLeaves)
        }
        "exile_opponents_nonland_permanent_with_max_mv_until_leaves" => {
            // **Round 14 rider-widened parse arm.** Carries
            // `max_mv: i32` (required, non-negative). Mirrors
            // Python's `ExileOpponentsNonlandPermanentUntilLeaves(max_mv=N)`
            // (`effects/generic/exile.py:587`). max_mv=0 would mean
            // "no cap" but the bare sibling already covers that
            // case; the rider variant requires max_mv > 0 by
            // convention to keep the two shapes disjoint at the
            // dict-shape layer.
            let max_mv: i32 = match dict.get_item("max_mv")? {
                Some(v) => v.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "exile_opponents_nonland_permanent_with_max_mv_until_leaves.max_mv must be an integer (got: {e})"
                    ))
                })?,
                None => {
                    return Err(PyValueError::new_err(
                        "exile_opponents_nonland_permanent_with_max_mv_until_leaves: missing required 'max_mv' field",
                    ));
                }
            };
            if max_mv < 0 {
                return Err(PyValueError::new_err(format!(
                    "exile_opponents_nonland_permanent_with_max_mv_until_leaves: max_mv must be non-negative, got {max_mv}"
                )));
            }
            Ok(Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves { max_mv })
        }
        "may_do" => {
            let nested = dict.get_item("inner_effect")?.ok_or_else(|| {
                PyValueError::new_err(
                    "may_do: missing required 'inner_effect' field",
                )
            })?;
            let nested_dict = nested.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "may_do.inner_effect must be a dict",
                )
            })?;
            let inner = parse_effect(nested_dict)?;
            let prompt: String = match dict.get_item("prompt")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "may_do.prompt must be a string (got: {e})"
                    ))
                })?,
                None => String::new(),
            };
            Ok(Effect::MayDo {
                inner_effect: Box::new(inner),
                prompt,
            })
        }
        "look_top_n_put_one_in_hand_rest_to_graveyard" => {
            let n: i32 = match dict.get_item("n")? {
                Some(v) => v.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "look_top_n_put_one_in_hand_rest_to_graveyard.n must be an integer (got: {e})"
                    ))
                })?,
                None => 4, // Python's class default (Commune with Evil n=4)
            };
            if n < 0 {
                return Err(PyValueError::new_err(format!(
                    "look_top_n_put_one_in_hand_rest_to_graveyard: n must be non-negative, got {n}"
                )));
            }
            Ok(Effect::LookTopNPutOneInHandRestToGraveyard { n })
        }
        "famished_worldsire_look_top_x_by_power_put_lands_tapped" => {
            // BLOCKED-RUST-EFFECT slice (round 54) — Famished
            // Worldsire ETB. Unit variant; no payload fields beyond
            // `kind` (X is dynamic — read from the source's effective
            // power at resolve, clamped >= 0; land selection is a
            // deterministic greedy-all mirroring Python's
            // `FamishedWorldsireETBEffect`, no decision plumbed).
            // Extra dict fields silently ignored for round-trip
            // dict-shape consistency (mirrors the round-49
            // `gain_life_equal_to_your_life_total` unit-variant parse
            // arm shape verbatim, swapping the literal).
            Ok(Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped)
        }
        "pump_target_artifact_or_creature_until_eot" => {
            // Round-28 broader-filter pump. Same schema as
            // pump_target_creature_until_eot — power_bonus +
            // toughness_bonus default to 0; negatives allowed.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_artifact_or_creature_until_eot.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_target_artifact_or_creature_until_eot.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpTargetArtifactOrCreatureUntilEOT { power_bonus, toughness_bonus })
        }
        "each_opponent_sacrifices_creature" => {
            // Unit variant; no fields.
            Ok(Effect::EachOpponentSacrificesCreature)
        }
        "untap_target_other_permanent" => {
            Ok(Effect::UntapTargetOtherPermanent)
        }
        "tap_another_target_creature" => {
            Ok(Effect::TapAnotherTargetCreature)
        }
        "return_all_creatures_from_your_graveyard_to_battlefield" => {
            Ok(Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield)
        }
        "manifest_dread" => {
            // Round-28 ManifestDread first-slice. Python's
            // `ManifestDread(count: int = 1)` defaults to 1; we
            // mirror that. Negative count raises at parse time.
            // count != 1 is allowed at parse (so dict round-trip
            // works) but resolve-time-raises with a clear "deferred"
            // error so a typo doesn't silently no-op.
            let count: i32 = match dict.get_item("count")? {
                Some(c) => c.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "manifest_dread.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "manifest_dread: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::ManifestDread { count })
        }
        "manifest_dread_then_attach_self" => {
            // Round-29 ManifestDreadThenAttachSelf composition.
            // Schema mirrors `manifest_dread` exactly: optional `count`
            // field defaulting to 1, non-negative required. The
            // resolve arm gates count != 1 to deferred at the same
            // place as `Effect::ManifestDread`.
            let count: i32 = match dict.get_item("count")? {
                Some(c) => c.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "manifest_dread_then_attach_self.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "manifest_dread_then_attach_self: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::ManifestDreadThenAttachSelf { count })
        }
        "manifest_dread_then_put_plus_one_counters_on_it" => {
            // Round-29 ManifestDreadThenPutPlusOneCountersOnIt
            // (Moldering-Gym / Weight-Room family) composition.
            // Schema mirrors `manifest_dread`'s `count` plus a new
            // `counter_amount` rider — both default to 1, both must
            // be non-negative. Slimy Aquarium emits counter_amount=1,
            // Weight Room emits counter_amount=3.
            let count: i32 = match dict.get_item("count")? {
                Some(c) => c.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "manifest_dread_then_put_plus_one_counters_on_it.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "manifest_dread_then_put_plus_one_counters_on_it: count must be non-negative, got {count}"
                )));
            }
            let counter_amount: i32 = match dict.get_item("counter_amount")? {
                Some(c) => c.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "manifest_dread_then_put_plus_one_counters_on_it.counter_amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if counter_amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "manifest_dread_then_put_plus_one_counters_on_it: counter_amount must be non-negative, got {counter_amount}"
                )));
            }
            Ok(Effect::ManifestDreadThenPutPlusOneCountersOnIt {
                count,
                counter_amount,
            })
        }
        "set_base_pt_until_eot" => {
            // Required `power` and `toughness` integer fields. No
            // defaults — every Python card emission spells both out.
            let power: i32 = dict
                .get_item("power")?
                .ok_or_else(|| {
                    PyValueError::new_err(
                        "set_base_pt_until_eot: missing required 'power' field",
                    )
                })?
                .extract()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "set_base_pt_until_eot.power must be an integer (got: {e})"
                    ))
                })?;
            let toughness: i32 = dict
                .get_item("toughness")?
                .ok_or_else(|| {
                    PyValueError::new_err(
                        "set_base_pt_until_eot: missing required 'toughness' field",
                    )
                })?
                .extract()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "set_base_pt_until_eot.toughness must be an integer (got: {e})"
                    ))
                })?;
            Ok(Effect::SetBasePTUntilEOT { power, toughness })
        }
        "become_land_creature_ueot" => {
            // Round-28 manland animation. Required `power` and
            // `toughness` integer fields — every Python emission of
            // BecomeLandCreatureUEOT spells both out. Optional
            // `granted_subtype` is `None` when absent (matches
            // Python's `granted_subtype: str | None = None` default).
            // Negative power/toughness are accepted (no guard) — the
            // Python dataclass has no raise-on-negative either, and
            // a debuff-shaped manland would still register cleanly.
            let power: i32 = dict
                .get_item("power")?
                .ok_or_else(|| {
                    PyValueError::new_err(
                        "become_land_creature_ueot: missing required 'power' field",
                    )
                })?
                .extract()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "become_land_creature_ueot.power must be an integer (got: {e})"
                    ))
                })?;
            let toughness: i32 = dict
                .get_item("toughness")?
                .ok_or_else(|| {
                    PyValueError::new_err(
                        "become_land_creature_ueot: missing required 'toughness' field",
                    )
                })?
                .extract()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "become_land_creature_ueot.toughness must be an integer (got: {e})"
                    ))
                })?;
            let granted_subtype: Option<String> = match dict.get_item("granted_subtype")? {
                Some(v) if v.is_none() => None,
                Some(v) => {
                    let s: String = v.extract().map_err(|e| {
                        PyValueError::new_err(format!(
                            "become_land_creature_ueot.granted_subtype must be a string or None (got: {e})"
                        ))
                    })?;
                    if s.is_empty() {
                        None
                    } else {
                        Some(s)
                    }
                }
                None => None,
            };
            Ok(Effect::BecomeLandCreatureUEOT {
                power,
                toughness,
                granted_subtype,
            })
        }
        "grant_keyword_to_target_creature_until_eot" => {
            // Required `keyword` field: non-empty lowercase string.
            let keyword_raw = dict.get_item("keyword")?.ok_or_else(|| {
                PyValueError::new_err(
                    "grant_keyword_to_target_creature_until_eot: missing required 'keyword' field",
                )
            })?;
            let keyword: String = keyword_raw.extract().map_err(|e| {
                PyValueError::new_err(format!(
                    "grant_keyword_to_target_creature_until_eot.keyword must be a string (got: {e})"
                ))
            })?;
            if keyword.is_empty() {
                return Err(PyValueError::new_err(
                    "grant_keyword_to_target_creature_until_eot.keyword must be non-empty",
                ));
            }
            Ok(Effect::GrantKeywordToTargetCreatureUntilEOT { keyword })
        }
        "grant_keywords_to_target_creature_until_eot" => {
            // Round-15 (post-r14) rider-widened sibling of
            // `grant_keyword_to_target_creature_until_eot`. Required
            // `keywords` field: non-empty list of non-empty lowercase
            // strings. Optional `exclude_source` flag (default false)
            // for the "another target creature" sub-shape.
            let keywords_raw = dict.get_item("keywords")?.ok_or_else(|| {
                PyValueError::new_err(
                    "grant_keywords_to_target_creature_until_eot: missing required 'keywords' field",
                )
            })?;
            let keywords: Vec<String> = keywords_raw.extract().map_err(|e| {
                PyValueError::new_err(format!(
                    "grant_keywords_to_target_creature_until_eot.keywords must be a list of strings (got: {e})"
                ))
            })?;
            if keywords.is_empty() {
                return Err(PyValueError::new_err(
                    "grant_keywords_to_target_creature_until_eot.keywords must be non-empty",
                ));
            }
            for kw in &keywords {
                if kw.is_empty() {
                    return Err(PyValueError::new_err(
                        "grant_keywords_to_target_creature_until_eot.keywords entries must be non-empty strings",
                    ));
                }
            }
            let exclude_source: bool = match dict.get_item("exclude_source")? {
                Some(v) => v.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "grant_keywords_to_target_creature_until_eot.exclude_source must be a bool (got: {e})"
                    ))
                })?,
                None => false,
            };
            Ok(Effect::GrantKeywordsToTargetCreatureUntilEOT {
                keywords,
                exclude_source,
            })
        }
        "each_opponent_mills_cards" => {
            // Python's `EachOpponentMillsCards(count: int = 1)` dataclass.
            // Missing `count` defaults to 1; negative count raises.
            let count: i32 = match dict.get_item("count")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "each_opponent_mills_cards.count must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if count < 0 {
                return Err(PyValueError::new_err(format!(
                    "each_opponent_mills_cards: count must be non-negative, got {count}"
                )));
            }
            Ok(Effect::EachOpponentMillsCards { count })
        }
        "exile_each_opponents_graveyard" => {
            // Python's `ExileEachOpponentsGraveyard` dataclass —
            // field-free unit effect (exile.py:260). No keys to read.
            Ok(Effect::ExileEachOpponentsGraveyard)
        }
        "if_you_do" => {
            // Round-28 IfYouDo first-slice: do_action implicitly
            // success-on-yes (i.e. IfYouDo(MayDo(X), Y) form). Both
            // nested effects required; no defaulting.
            let do_raw = dict.get_item("do_action")?.ok_or_else(|| {
                PyValueError::new_err(
                    "if_you_do: missing required 'do_action' field",
                )
            })?;
            let then_raw = dict.get_item("then_action")?.ok_or_else(|| {
                PyValueError::new_err(
                    "if_you_do: missing required 'then_action' field",
                )
            })?;
            let do_dict = do_raw.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "if_you_do.do_action must be a dict (effect-shape)",
                )
            })?;
            let then_dict = then_raw.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "if_you_do.then_action must be a dict (effect-shape)",
                )
            })?;
            let do_action = parse_effect(do_dict)?;
            let then_action = parse_effect(then_dict)?;
            Ok(Effect::IfYouDo {
                do_action: Box::new(do_action),
                then_action: Box::new(then_action),
            })
        }
        "choose_one_mode" => {
            // Round-28 ModalChooseOne first-slice: resolve-time pick
            // only. Required nested 'modes' field is a list of effect
            // dicts; recursively parse each. Empty modes list is
            // rejected at parse time so the resolve arm always has at
            // least one mode to fall through to.
            let nested = dict.get_item("modes")?.ok_or_else(|| {
                PyValueError::new_err(
                    "choose_one_mode: missing required 'modes' field (list of nested effect dicts)",
                )
            })?;
            let items: Vec<Bound<'_, PyAny>> = nested
                .try_iter()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "choose_one_mode.modes must be iterable (got: {e})"
                    ))
                })?
                .collect::<PyResult<Vec<_>>>()?;
            if items.is_empty() {
                return Err(PyValueError::new_err(
                    "choose_one_mode.modes must be non-empty (at least one mode required)",
                ));
            }
            let mut parsed_modes: Vec<Effect> = Vec::with_capacity(items.len());
            for item in items {
                let mode_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err(
                        "choose_one_mode.modes entries must be dicts (effect-shape)",
                    )
                })?;
                parsed_modes.push(parse_effect(mode_dict)?);
            }
            Ok(Effect::ChooseOneMode { modes: parsed_modes })
        }
        "put_charge_counters_on_self" => {
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_charge_counters_on_self.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "put_charge_counters_on_self: amount must be non-negative, got {amount}"
                )));
            }
            let amount_from_x: bool = match dict.get_item("amount_from_x")? {
                Some(b) => b.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_charge_counters_on_self.amount_from_x must be a bool (got: {e})"
                    ))
                })?,
                None => false,
            };
            Ok(Effect::PutChargeCountersOnSelf { amount, amount_from_x })
        }
        "put_plus_one_counter_on_each_of_up_to_n_target_creatures" => {
            let max_n: i32 = match dict.get_item("max_n")? {
                Some(m) => m.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_plus_one_counter_on_each_of_up_to_n_target_creatures.max_n must be an integer (got: {e})"
                    ))
                })?,
                None => 2,
            };
            if max_n < 0 {
                return Err(PyValueError::new_err(format!(
                    "put_plus_one_counter_on_each_of_up_to_n_target_creatures: max_n must be non-negative, got {max_n}"
                )));
            }
            Ok(Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures { max_n })
        }
        "conditional_on_tapped_creatures" => {
            // Required nested effect.
            let nested = dict.get_item("effect")?.ok_or_else(|| {
                PyValueError::new_err(
                    "conditional_on_tapped_creatures: missing required 'effect' field",
                )
            })?;
            let nested_dict = nested.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "conditional_on_tapped_creatures.effect must be a dict (effect-shape)",
                )
            })?;
            let inner = parse_effect(nested_dict)?;
            let min_count: i32 = match dict.get_item("min_count")? {
                Some(m) => m.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "conditional_on_tapped_creatures.min_count must be an integer (got: {e})"
                    ))
                })?,
                None => 2,
            };
            Ok(Effect::ConditionalOnTappedCreatures {
                effect: Box::new(inner),
                min_count,
            })
        }
        "conditional_if_void" => {
            // Required then-branch.
            let then_any = dict.get_item("then_effect")?.ok_or_else(|| {
                PyValueError::new_err(
                    "conditional_if_void: missing required 'then_effect' field",
                )
            })?;
            let then_dict = then_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "conditional_if_void.then_effect must be a dict (effect-shape)",
                )
            })?;
            let then_inner = parse_effect(then_dict)?;
            // Optional else-branch — None when key absent OR explicit Python None.
            let else_inner: Option<Effect> = match dict.get_item("else_effect")? {
                None => None,
                Some(v) if v.is_none() => None,
                Some(v) => {
                    let else_dict = v.downcast::<PyDict>().map_err(|_| {
                        PyValueError::new_err(
                            "conditional_if_void.else_effect must be a dict or None",
                        )
                    })?;
                    Some(parse_effect(else_dict)?)
                }
            };
            Ok(Effect::ConditionalIfVoid {
                then_effect: Box::new(then_inner),
                else_effect: else_inner.map(Box::new),
            })
        }
        "look_at_top_n_reveal_or_counter" => {
            // Round-28 Living-Phone family. Required `n` (Python's class
            // default is 5 for Pulsar Squadron Ace but we make it
            // required at parse to match the every-card-emits-it
            // convention — registrations omit only when the printed
            // body literally says "top 5", which they spell explicitly).
            //
            // Actually — Python's class HAS a default of n=5. Mirror
            // that so dict round-trip with omitted `n` works.
            let n: i32 = match dict.get_item("n")? {
                Some(v) => v.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "look_at_top_n_reveal_or_counter.n must be an integer (got: {e})"
                    ))
                })?,
                None => {
                    return Err(PyValueError::new_err(
                        "look_at_top_n_reveal_or_counter: missing required 'n' field",
                    ));
                }
            };
            if n < 0 {
                return Err(PyValueError::new_err(format!(
                    "look_at_top_n_reveal_or_counter: n must be non-negative, got {n}"
                )));
            }
            let filter_name: String = match dict.get_item("filter_name")? {
                Some(s) => s.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "look_at_top_n_reveal_or_counter.filter_name must be a string (got: {e})"
                    ))
                })?,
                None => "spacecraft".to_string(), // Python class default
            };
            match filter_name.as_str() {
                "spacecraft" | "creature" | "artifact" => {}
                other => {
                    return Err(PyValueError::new_err(format!(
                        "look_at_top_n_reveal_or_counter: filter_name must be one of \
                         'spacecraft', 'creature', 'artifact' (got: {other:?})"
                    )));
                }
            }
            let max_power: i32 = match dict.get_item("max_power")? {
                Some(m) => m.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "look_at_top_n_reveal_or_counter.max_power must be an integer (got: {e})"
                    ))
                })?,
                None => 0, // Python class default — 0 means "no power cap"
            };
            if max_power < 0 {
                return Err(PyValueError::new_err(format!(
                    "look_at_top_n_reveal_or_counter: max_power must be non-negative, got {max_power}"
                )));
            }
            let counter_on_miss: bool = match dict.get_item("counter_on_miss")? {
                Some(b) => b.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "look_at_top_n_reveal_or_counter.counter_on_miss must be a bool (got: {e})"
                    ))
                })?,
                None => true, // Python class default — Pulsar Squadron Ace shape
            };
            Ok(Effect::LookAtTopNRevealOrCounter {
                n,
                filter_name,
                max_power,
                counter_on_miss,
            })
        }
        "pump_creatures_opponents_control_until_eot" => {
            // Mirror schema of pump_creatures_you_control_until_eot.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_opponents_control_until_eot.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_opponents_control_until_eot.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpCreaturesOpponentsControlUntilEOT { power_bonus, toughness_bonus })
        }
        "pump_creatures_opponents_control_until_caster_next_turn" => {
            // Mouth-of-the-Storm sibling — same field shape as the
            // bare-EOT arm above; the discriminator alone carries
            // the extended-duration distinction (Python translates
            // it to `until_caster_next_turn=True`). The cleanup-
            // gate divergence is documented on the variant + in
            // SEARCH_LIMITATIONS.md.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_opponents_control_until_caster_next_turn.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_opponents_control_until_caster_next_turn.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn {
                power_bonus,
                toughness_bonus,
            })
        }
        "search_library_for_card" => {
            // Python's SearchLibraryForCard(filter_name, max_mv=0,
            // may_fail=True).
            let filter_name: String = match dict.get_item("filter_name")? {
                Some(s) => s.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "search_library_for_card.filter_name must be a string (got: {e})"
                    ))
                })?,
                None => {
                    return Err(PyValueError::new_err(
                        "search_library_for_card: missing required 'filter_name' field",
                    ));
                }
            };
            let max_mv: i32 = match dict.get_item("max_mv")? {
                Some(m) => m.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "search_library_for_card.max_mv must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let may_fail: bool = match dict.get_item("may_fail")? {
                Some(m) => m.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "search_library_for_card.may_fail must be a bool (got: {e})"
                    ))
                })?,
                None => true,
            };
            Ok(Effect::SearchLibraryForCard {
                filter_name,
                max_mv,
                may_fail,
            })
        }
        "add_n_mana_of_chosen_color" => {
            // Python's AddNManaOfChosenColor(amount: int,
            // options: tuple[str, ...] = ("W","U","B","R","G")).
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "add_n_mana_of_chosen_color.amount must be an integer (got: {e})"
                    ))
                })?,
                None => {
                    return Err(PyValueError::new_err(
                        "add_n_mana_of_chosen_color: missing required 'amount' field",
                    ));
                }
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "add_n_mana_of_chosen_color: amount must be non-negative, got {amount}"
                )));
            }
            let options: Vec<String> = match dict.get_item("options")? {
                Some(items) => {
                    let raw: Vec<String> = items.extract().map_err(|e| {
                        PyValueError::new_err(format!(
                            "add_n_mana_of_chosen_color.options must be a list of color strings (got: {e})"
                        ))
                    })?;
                    if raw.is_empty() {
                        return Err(PyValueError::new_err(
                            "add_n_mana_of_chosen_color: options must be non-empty",
                        ));
                    }
                    for c in &raw {
                        if !matches!(c.as_str(), "W" | "U" | "B" | "R" | "G" | "C") {
                            return Err(PyValueError::new_err(format!(
                                "add_n_mana_of_chosen_color: unknown color {c:?}; valid: W, U, B, R, G, C"
                            )));
                        }
                    }
                    raw
                }
                None => vec![
                    "W".into(),
                    "U".into(),
                    "B".into(),
                    "R".into(),
                    "G".into(),
                ],
            };
            Ok(Effect::AddNManaOfChosenColor { amount, options })
        }
        "put_plus_one_counter_on_creature_you_control" => {
            // Python's PutPlusOneCounterOnCreatureYouControl uses
            // PutPlusOneCounters base default of amount=1.
            let amount: i32 = match dict.get_item("amount")? {
                Some(a) => a.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "put_plus_one_counter_on_creature_you_control.amount must be an integer (got: {e})"
                    ))
                })?,
                None => 1,
            };
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "put_plus_one_counter_on_creature_you_control: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::PutPlusOneCounterOnCreatureYouControl { amount })
        }
        "pump_creatures_you_control_until_eot" => {
            // Round-28 anthem-shape UEOT effect. Mirrors the
            // PumpSelfUntilEOT / PumpTargetCreatureUntilEOT schema:
            // power_bonus + toughness_bonus default to 0, negatives
            // allowed.
            let power_bonus: i32 = match dict.get_item("power_bonus")? {
                Some(p) => p.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_you_control_until_eot.power_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            let toughness_bonus: i32 = match dict.get_item("toughness_bonus")? {
                Some(t) => t.extract().map_err(|e| {
                    PyValueError::new_err(format!(
                        "pump_creatures_you_control_until_eot.toughness_bonus must be an integer (got: {e})"
                    ))
                })?,
                None => 0,
            };
            Ok(Effect::PumpCreaturesYouControlUntilEOT { power_bonus, toughness_bonus })
        }
        "deal_damage_to_opponent_creature" => {
            // Mirrors Python's `DealDamageToOpponentCreature(DealDamage)`
            // (effects/generic/damage.py) — same shape as
            // `deal_damage_any_target` but the target filter is
            // `IsCreature & ControlledByOpponent`. Negative `amount`
            // surfaces at register time (defense-in-depth; the resolve
            // arm re-checks).
            let amount: i32 = require(dict, "amount")?.extract()?;
            if amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "deal_damage_to_opponent_creature: amount must be non-negative, got {amount}"
                )));
            }
            Ok(Effect::DealDamageToOpponentCreature { amount })
        }
        "optional_mana_cost_then_effect" => {
            // Round-29 OptionalManaCostThenEffect — Kavaron-Harrier /
            // Oreplate-Pangolin family. Required `cost` (mana cost
            // dict) and `inner_effect` (nested effect dict).
            let cost_any = dict.get_item("cost")?.ok_or_else(|| {
                PyValueError::new_err(
                    "optional_mana_cost_then_effect: missing required 'cost' field",
                )
            })?;
            let cost_dict = cost_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "optional_mana_cost_then_effect.cost must be a dict",
                )
            })?;
            let cost = parse_mana_cost(cost_dict)?;
            let inner_any = dict.get_item("inner_effect")?.ok_or_else(|| {
                PyValueError::new_err(
                    "optional_mana_cost_then_effect: missing required 'inner_effect' field",
                )
            })?;
            let inner_dict = inner_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(
                    "optional_mana_cost_then_effect.inner_effect must be a dict (effect-shape)",
                )
            })?;
            let inner = parse_effect(inner_dict)?;
            Ok(Effect::OptionalManaCostThenEffect {
                cost,
                inner_effect: Box::new(inner),
            })
        }
        "draw_cards_equal_to_resolving_combat_damage" => {
            // Round-28 freq-2 closure — Starwinder / Fear-of-Failed-
            // Tests shape. Unit variant; reads
            // state.resolving_combat_damage_amount at resolve time.
            // No fields to parse.
            Ok(Effect::DrawCardsEqualToResolvingCombatDamage)
        }
        "sequence" => {
            // Round-28 highest-frequency-class coverage. Mirrors
            // Python's Sequence(effects: tuple[Effect, ...]).
            // Field `effects` is a list of nested effect dicts;
            // recursively parse each via this same parse_effect
            // function. Empty list is legal (no-op Sequence).
            let nested = dict.get_item("effects")?.ok_or_else(|| {
                PyValueError::new_err(
                    "sequence: missing required 'effects' field (list of nested effect dicts)",
                )
            })?;
            let items: Vec<Bound<'_, PyAny>> = nested
                .try_iter()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "sequence.effects must be iterable (got: {e})"
                    ))
                })?
                .collect::<PyResult<Vec<_>>>()?;
            let mut children: Vec<Effect> = Vec::with_capacity(items.len());
            for item in items {
                let child_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err(
                        "sequence.effects entries must be dicts (effect-shape)",
                    )
                })?;
                children.push(parse_effect(child_dict)?);
            }
            Ok(Effect::Sequence { effects: children })
        }
        other => Err(PyValueError::new_err(format!(
            "unknown effect kind {other:?}; valid: deal_damage, draw_cards, gain_life, return_to_hand, mill, mill_target_player, exile_target, tap_target, untap_target, sacrifice, add_counters, discard_card, scry_n, destroy_target, damage_each_opponent, damage_each_creature, create_token, add_mana_to_pool, search_library_for_basic_land_tapped, put_plus_one_counter_on_self, surveil, counter_target_spell, return_creature_from_your_graveyard_to_battlefield, discard_self, each_opponent_loses_life, lose_life, target_opponent_loses_life, each_opponent_discards, destroy_all_creatures, destroy_target_nonland_permanent, destroy_target_artifact, destroy_target_land, deal_damage_any_target, pump_self_until_eot, pump_target_creature_until_eot, sequence, pump_creatures_you_control_until_eot, return_creature_from_your_graveyard_to_hand, put_plus_one_counter_on_each_creature_you_control, put_plus_one_counter_on_creature_you_control, add_n_mana_of_chosen_color, search_library_for_card, pump_creatures_opponents_control_until_eot, put_card_from_graveyard_on_bottom_of_library, move_self_counters_to_target_creature_you_control, deal_damage_equal_to_source_power_any_target, tap_target_artifact_or_creature, conditional_on_tapped_creatures, put_plus_one_counter_on_each_of_up_to_n_target_creatures, put_charge_counters_on_self, create_token_copy_of_target_creature_you_control, optional_sac_artifact_for_effect, owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library, attach_to_target_creature_you_control, destroy_enchanted_permanent, tap_enchanted_permanent, put_stun_counter_on_tapped_creature, tap_target_opponent_permanent_and_stun_it, exile_target_creature_until_source_leaves, exile_opponents_nonland_permanent_until_leaves, exile_opponents_nonland_permanent_with_max_mv_until_leaves, may_do, look_top_n_put_one_in_hand_rest_to_graveyard, choose_one_mode, if_you_do, each_opponent_mills_cards, pump_target_artifact_or_creature_until_eot, each_opponent_sacrifices_creature, grant_keyword_to_target_creature_until_eot, grant_keywords_to_target_creature_until_eot, untap_target_other_permanent, tap_another_target_creature, return_all_creatures_from_your_graveyard_to_battlefield, set_base_pt_until_eot, manifest_dread, manifest_dread_then_attach_self, manifest_dread_then_put_plus_one_counters_on_it, conditional_if_void, deal_damage_to_opponent_creature, optional_mana_cost_then_effect, draw_cards_equal_to_resolving_combat_damage, double_target_creatures_power_ueot, deal_damage_to_opponent_creature_by_artifact_count, put_plus_one_counters_on_self_per_other_creature_or_artifact, surveil_x_equal_to_artifact_count, deal_damage_to_opponent_creature_by_cards_in_hand, deal_damage_to_opponent_creature_by_lands_controlled, deal_damage_to_opponent_creature_by_creatures_you_control, mill_target_player_equal_to_your_life_total, create_token_each_player, each_opponent_loses_life_equal_to_artifact_count, gain_life_equal_to_artifact_count, deal_damage_to_opponent_creature_by_cards_in_graveyard, deal_damage_to_opponent_creature_by_life_total, exile_each_opponents_graveyard"
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

/// CE20 follow-up — bridge legacy `mana_produced` into synthesized
/// `ActivatedAbility` entries on the printing's `activated_abilities`
/// Vec. When `mana_produced.is_some()`, prepend **one synthesized
/// `is_mana_ability` entry PER produced color**, in the SAME order
/// the symbols appear in `mana_produced`:
///
///   cost:   ManaCost::default() (free) + tap_self=true
///   effect: AddManaToPool { color: <c>, amount: 1 } — one entry per
///           color symbol, NOT aggregated.
///   is_mana_ability: true (CR 605.1 — produces mana, doesn't target).
///
/// `ability_index=0` = first color, `ability_index=1` = second, …
/// (then any explicit registry-supplied entries at indices >= N).
///
/// **Round-62 N1 — per-color shape (the cross-engine fix).** Before
/// round-62 this synthesized ONE ability whose effect aggregated ALL
/// colors (a flat `AddManaToPool` for a single color, a
/// `Sequence(Add c1, Add c2, …)` for multi-color). That disagreed
/// with the Python bridge `cross_engine._card_def_to_python_printing`,
/// which builds **one `ActivatedAbility` per color** in
/// `mana_produced` order (idx0=Add c1, idx1=Add c2). For a
/// single-color land (every basic) the two shapes were bit-equal
/// (one ability adding the one color), so the divergence was
/// invisible — until round-60 admitted the 5 EoE pay-life shocklands
/// (2-color `mana_produced`) into the production bench. Round-61 N3's
/// post-admit sweep caught it: `activate_ability(dual_land, 0)` made
/// Python add 1 color but Rust add BOTH (the whole `Sequence`) → a
/// spurious extra mana in the Rust pool (4 FAIL_DIVERGENCE / 112
/// games, every divergent land a 2-color shockland including U). The
/// CR-correct shape is one mana ability per color (the player chooses
/// which color by picking the ability index); Python was already
/// correct. This rewrite makes Rust emit the same per-color shape so
/// `activate_ability(land, k)` adds exactly the k-th color on BOTH
/// engines. Documented: `SEARCH_LIMITATIONS.md` shockland entry
/// (CLOSED round-62). Single-color lands stay bit-identical (one
/// ability, one color) — verified by the Forest/Llanowar synthetic
/// callers in `state.rs` and the round-62 Rust regression pins.
///
/// Note: `mana_produced=["G","G"]` now yields TWO `{T}: Add G`
/// abilities (one per entry — matches Python's
/// `for color in card.mana_produced`), not one `Add G amount=2`.
/// No real bridge printing carries a duplicate-color `mana_produced`
/// (`_printing_to_card_def` builds it from a `frozenset.produces`,
/// so entries are distinct), but per-entry emission is the
/// Python-exact shape and is the contract both engines now share.
///
/// Shared between `parse_printing` (dict-input registry path) and
/// `make_synthetic_state` (the test-fixture path in `state.rs`) so
/// both surfaces get the same bridge synthesis without duplicating
/// the per-color logic.
pub fn apply_mana_produced_bridge(
    mana_produced: &Option<Vec<String>>,
    existing: Vec<ActivatedAbility>,
) -> PyResult<Vec<ActivatedAbility>> {
    let Some(symbols) = mana_produced else {
        return Ok(existing);
    };
    // One synthesized is_mana_ability ability PER color symbol, in
    // input order — matching Python's
    // `_card_def_to_python_printing` `for color in card.mana_produced`
    // loop exactly (idx0=Add c1, idx1=Add c2, …). For shocklands
    // `trajectory._printing_to_card_def` passes
    // `tuple(sorted(printing.produces))`, so both engines iterate the
    // alphabetically-sorted dual (Watery Grave → idx0=Add B,
    // idx1=Add U); the order parity is the input-order parity.
    let mut bridge_abilities: Vec<ActivatedAbility> =
        Vec::with_capacity(symbols.len());
    for sym in symbols {
        match sym.as_str() {
            "W" | "U" | "B" | "R" | "G" | "C" => {}
            other => {
                // `parse_mana_produced` already rejected unknown
                // symbols at parse time; raise loud as a paranoid
                // double-check that also catches direct callers from
                // `state.rs` that bypass `parse_mana_produced`.
                return Err(PyValueError::new_err(format!(
                    "bridge synth: unknown mana_produced symbol \
                     {other:?}; expected W/U/B/R/G/C"
                )));
            }
        }
        bridge_abilities.push(ActivatedAbility {
            cost: ActivationCost {
                mana: ManaCost::default(),
                tap_self: true,
                sacrifice_self: false,
                requires_target_creature_you_control: false,
                sacrifice_another_creature_or_artifact: false,
                sacrifice_a_land: false,
                sacrifice_another_artifact: false,
                sacrifice_food: false,
                sacrifice_a_desert: false,
                loyalty: 0,
            },
            effect: Effect::AddManaToPool {
                color: sym.clone(),
                amount: 1,
            },
            is_mana_ability: true,
            tier_threshold: 0,
        });
    }
    // Prepend so ability_index=0..N-1 refer to the per-color bridged
    // mana abilities (Python's idx0/idx1 ordering); any explicit
    // registry-supplied entries follow at indices >= N. Every
    // pre-bridge ActivateAbility(forest, 0) caller keeps working
    // bit-equal (single-color → exactly one ability at index 0).
    let mut bridged =
        Vec::with_capacity(existing.len() + bridge_abilities.len());
    bridged.append(&mut bridge_abilities);
    let mut existing = existing;
    bridged.append(&mut existing);
    Ok(bridged)
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
    // warp_cost substrate (Phase 1, round-63). Same dict shape as
    // `mana_cost` (`{"generic":N,"R":1}`). Missing key -> `None`
    // (back-compat — every pre-Phase-1 registry dict omits it). This
    // `match dict.get_item(...)? { Some => ..., None => default }`
    // shape IS the `#[serde(default)]`-equivalent the existing
    // optional fields all use; no serde derive needed (CardPrinting
    // is built via parse_printing from a PyDict, not deserialized).
    let warp_cost = match dict.get_item("warp_cost")? {
        Some(wc_any) => {
            let wc_dict = wc_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("warp_cost must be a dict")
            })?;
            Some(parse_mana_cost(wc_dict)?)
        }
        None => None,
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
    // Subtypes substrate (Slice 1): `subtypes` defaults to empty Vec
    // when absent (back-compat — every pre-substrate registry dict
    // implicitly omits the key). Stored as Title Case strings exactly
    // as printed; the consumer side does case-sensitive `contains`.
    let subtypes = match dict.get_item("subtypes")? {
        Some(st_any) => {
            let iter = st_any.try_iter().map_err(|_| {
                PyValueError::new_err(
                    "subtypes must be an iterable of subtype strings",
                )
            })?;
            let mut out = Vec::new();
            for item in iter {
                let s: String = item?.extract().map_err(|_| {
                    PyValueError::new_err("subtypes entries must be strings")
                })?;
                out.push(s);
            }
            out
        }
        None => Vec::new(),
    };
    // Supertypes substrate (Round 30): `supertypes` defaults to empty
    // Vec when absent (back-compat — every pre-Round-30 registry dict
    // implicitly omits the key). Same parse shape as `subtypes`.
    // Stored as Title Case strings exactly as printed ("Basic",
    // "Legendary", "Snow", "World", "Token"); consumers do
    // case-sensitive `contains`.
    let supertypes = match dict.get_item("supertypes")? {
        Some(st_any) => {
            let iter = st_any.try_iter().map_err(|_| {
                PyValueError::new_err(
                    "supertypes must be an iterable of supertype strings",
                )
            })?;
            let mut out = Vec::new();
            for item in iter {
                let s: String = item?.extract().map_err(|_| {
                    PyValueError::new_err("supertypes entries must be strings")
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
    // Slice 1 ETB-trigger substrate: `triggered_abilities` defaults
    // to empty Vec when absent (back-compat for every pre-Slice-1
    // registry dict).
    let mut triggered_abilities = match dict.get_item("triggered_abilities")? {
        Some(ta_any) => {
            let mut out = Vec::new();
            for item in ta_any.try_iter()? {
                let item = item?;
                let ta_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err("each triggered_ability must be a dict")
                })?;
                out.push(parse_triggered_ability(ta_dict)?);
            }
            out
        }
        None => Vec::new(),
    };
    // ETB-trigger Slice 3: bridge legacy `etb_effects: Vec<Effect>`
    // into the predicate path. Each `etb_effects` entry is the
    // shape "when this enters, apply effect" — i.e. an IsSelf-only
    // ENTERS trigger. Synthesize that as a TriggeredAbility and
    // append to triggered_abilities so the predicate-path dispatch
    // walker (state_ops_resolve::dispatch_event) handles it via the
    // same substrate as every other ENTERS trigger.
    //
    // Synthesis is APPENDED (not prepended) so explicit
    // `triggered_abilities` entries fire in declaration order BEFORE
    // the synthesized self-ETB shim. This preserves the same
    // dispatcher walk order that Slice 1/2's tests pin on (ability
    // index iteration is left-to-right; synthesized entries get
    // higher indices). For printings that DON'T also carry an
    // explicit `triggered_abilities` entry the order doesn't matter.
    //
    // Audit pins (`docs/RUST_ETB_TRIGGER_AUDIT.md` §3.1) the legacy
    // hatch as "the synthesis source, not the runtime path"
    // post-Slice-3 — the `etb_effects` field is still parsed for
    // back-compat with pre-Slice-3 fixtures, but the resolver no
    // longer iterates it directly (Slice 3 retires the inline loop
    // in `resolve_top_of_stack` + `_pause`).
    for effect in &etb_effects {
        triggered_abilities.push(TriggeredAbility {
            event: Event::Enters,
            predicate: Predicate::SourceIsSelf,
            effect: effect.clone(),
            once_per_turn: false,
        });
    }
    // CE20 Slice 1 substrate: `activated_abilities` defaults to empty
    // Vec when absent (back-compat for every pre-CE20-Slice-1 registry
    // dict). Same parse shape as `triggered_abilities`.
    let mut activated_abilities = match dict.get_item("activated_abilities")? {
        Some(aa_any) => {
            let mut out = Vec::new();
            for item in aa_any.try_iter()? {
                let item = item?;
                let aa_dict = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err("each activated_ability must be a dict")
                })?;
                out.push(parse_activated_ability(aa_dict)?);
            }
            out
        }
        None => Vec::new(),
    };
    // CE20 follow-up — bridge `mana_produced` into
    // `activated_abilities`. See `apply_mana_produced_bridge` for the
    // synthesis details. The bridge prepends one synthesized
    // ActivatedAbility at `ability_index=0` so every pre-bridge
    // caller of `ActivateAbility(forest_id, 0)` keeps working.
    activated_abilities = apply_mana_produced_bridge(
        &mana_produced,
        activated_abilities,
    )?;
    // CE20 Slice 5 (Walker loyalty — starting_loyalty ETB seeding).
    // `starting_loyalty` is optional; defaults to 0 when the key is
    // absent. Stored as i32 (matches `GameObject.loyalty_counters`
    // shape). Negative values are accepted but observable only if a
    // pathological registry dict supplies one — production walkers
    // always print a non-negative starting loyalty.
    let starting_loyalty: i32 = match dict.get_item("starting_loyalty")? {
        Some(sl) => sl.extract::<i32>().map_err(|e| {
            PyValueError::new_err(format!(
                "starting_loyalty must be an integer (got: {e})"
            ))
        })?,
        None => 0,
    };
    Ok(CardPrinting {
        name: Arc::from(name),
        mana_cost,
        effects,
        power,
        toughness,
        mana_produced,
        card_types,
        subtypes,
        supertypes,
        keywords,
        etb_effects,
        triggered_abilities,
        activated_abilities,
        starting_loyalty,
        warp_cost,
    })
}

/// Parse one `ActivatedAbility` from a registry dict. Dict shape:
///
/// ```python
/// {
///     "cost": {                         # required; ActivationCost shape
///         "mana": {"generic": 1, "G": 1},  # optional; default = zero cost
///         "tap_self": True,                # optional; default = False
///     },
///     "effect": {...},                  # required; same shape as parse_effect input
///     "is_mana_ability": False,         # optional; default = False
/// }
/// ```
///
/// Slice 1 minimum surface; future slices add richer cost shapes
/// (sacrifice_self, pay_life, requires_*) in lockstep with their
/// dispatch counterparts.
fn parse_activated_ability(
    dict: &Bound<'_, PyDict>,
) -> PyResult<ActivatedAbility> {
    let cost_any = require(dict, "cost")?;
    let cost_dict = cost_any.downcast::<PyDict>().map_err(|_| {
        PyValueError::new_err("activated_ability.cost must be a dict")
    })?;
    let cost = parse_activation_cost(cost_dict)?;
    let effect_any = require(dict, "effect")?;
    let effect_dict = effect_any.downcast::<PyDict>().map_err(|_| {
        PyValueError::new_err("activated_ability.effect must be a dict")
    })?;
    let effect = parse_effect(effect_dict)?;
    let is_mana_ability = match dict.get_item("is_mana_ability")? {
        Some(v) => v.extract::<bool>().map_err(|_| {
            PyValueError::new_err(
                "activated_ability.is_mana_ability must be a bool",
            )
        })?,
        None => false,
    };
    // CE20 follow-up — Spacecraft station-charge. Optional
    // `tier_threshold: int >= 0`. Missing key defaults to 0 (no
    // gate — back-compat with every pre-Slice-3 caller).
    let tier_threshold = match dict.get_item("tier_threshold")? {
        Some(v) => {
            let n: i32 = v.extract().map_err(|_| {
                PyValueError::new_err(
                    "activated_ability.tier_threshold must be a non-negative int",
                )
            })?;
            if n < 0 {
                return Err(PyValueError::new_err(format!(
                    "activated_ability.tier_threshold must be \
                     non-negative, got {n}"
                )));
            }
            n
        }
        None => 0,
    };
    Ok(ActivatedAbility {
        cost,
        effect,
        is_mana_ability,
        tier_threshold,
    })
}

/// Parse one `ActivationCost` from a registry dict. Slice 1 supports
/// `mana` (optional ManaCost dict) + `tap_self` (optional bool).
/// CE20 follow-up Slice 2 adds `sacrifice_self` (optional bool).
/// CE20 follow-up Slice 4 adds `requires_target_creature_you_control`
/// (optional bool — flags target fan-out at emission + a required
/// `target_creature_id` key on the apply dict). CE20 follow-up Slice 6
/// adds `sacrifice_another_creature_or_artifact`, `sacrifice_a_land`,
/// `sacrifice_another_artifact` (optional bools — targeted-sacrifice
/// variants via `sacrifice_target_id`). CE20 follow-up Slice 7 adds
/// `sacrifice_food` and `sacrifice_a_desert` (optional bools —
/// subtype-filtered sacrifice variants riding on `CardPrinting.subtypes`
/// from the subtypes substrate). Unknown keys raise so future field
/// additions surface as parser errors rather than silent drops.
fn parse_activation_cost(
    dict: &Bound<'_, PyDict>,
) -> PyResult<ActivationCost> {
    let mut cost = ActivationCost::default();
    for (key_obj, _) in dict.iter() {
        let key: String = key_obj.extract()?;
        match key.as_str() {
            "mana"
            | "tap_self"
            | "sacrifice_self"
            | "requires_target_creature_you_control"
            | "sacrifice_another_creature_or_artifact"
            | "sacrifice_a_land"
            | "sacrifice_another_artifact"
            | "sacrifice_food"
            | "sacrifice_a_desert"
            | "loyalty" => {}
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown activation_cost key {other:?}; \
                     valid: mana, tap_self, sacrifice_self, \
                     requires_target_creature_you_control, \
                     sacrifice_another_creature_or_artifact, \
                     sacrifice_a_land, sacrifice_another_artifact, \
                     sacrifice_food, sacrifice_a_desert, \
                     loyalty"
                )));
            }
        }
    }
    if let Some(mana_any) = dict.get_item("mana")? {
        let mana_dict = mana_any.downcast::<PyDict>().map_err(|_| {
            PyValueError::new_err("activation_cost.mana must be a dict")
        })?;
        cost.mana = parse_mana_cost(mana_dict)?;
    }
    if let Some(tap_any) = dict.get_item("tap_self")? {
        cost.tap_self = tap_any.extract::<bool>().map_err(|_| {
            PyValueError::new_err("activation_cost.tap_self must be a bool")
        })?;
    }
    if let Some(sac_any) = dict.get_item("sacrifice_self")? {
        cost.sacrifice_self = sac_any.extract::<bool>().map_err(|_| {
            PyValueError::new_err(
                "activation_cost.sacrifice_self must be a bool",
            )
        })?;
    }
    if let Some(req_any) =
        dict.get_item("requires_target_creature_you_control")?
    {
        cost.requires_target_creature_you_control =
            req_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.requires_target_creature_you_control \
                     must be a bool",
                )
            })?;
    }
    if let Some(sac_another_any) =
        dict.get_item("sacrifice_another_creature_or_artifact")?
    {
        cost.sacrifice_another_creature_or_artifact =
            sac_another_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.sacrifice_another_creature_or_artifact \
                     must be a bool",
                )
            })?;
    }
    if let Some(sac_land_any) = dict.get_item("sacrifice_a_land")? {
        cost.sacrifice_a_land =
            sac_land_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.sacrifice_a_land must be a bool",
                )
            })?;
    }
    if let Some(sac_artifact_any) =
        dict.get_item("sacrifice_another_artifact")?
    {
        cost.sacrifice_another_artifact =
            sac_artifact_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.sacrifice_another_artifact \
                     must be a bool",
                )
            })?;
    }
    // CE20 follow-up Slice 7 — subtype-filtered sacrifice variants.
    // Both fields default `false`; missing keys are back-compat-OK.
    if let Some(sac_food_any) = dict.get_item("sacrifice_food")? {
        cost.sacrifice_food =
            sac_food_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.sacrifice_food must be a bool",
                )
            })?;
    }
    if let Some(sac_desert_any) = dict.get_item("sacrifice_a_desert")? {
        cost.sacrifice_a_desert =
            sac_desert_any.extract::<bool>().map_err(|_| {
                PyValueError::new_err(
                    "activation_cost.sacrifice_a_desert must be a bool",
                )
            })?;
    }
    if let Some(loy_any) = dict.get_item("loyalty")? {
        cost.loyalty = loy_any.extract::<i32>().map_err(|_| {
            PyValueError::new_err(
                "activation_cost.loyalty must be an int (signed; \
                 positive = pay-loyalty, negative = add-loyalty)",
            )
        })?;
    }
    Ok(cost)
}

/// Parse one `TriggeredAbility` from a registry dict. Dict shape:
///
/// ```python
/// {
///     "event": "enters",            # required; lowercase string
///     "effect": {...},              # required; same shape as parse_effect input
///     "predicate": {...},           # optional; defaults to {"kind": "always"}
///     "once_per_turn": False,       # optional; defaults to False
/// }
/// ```
///
/// Slice 1 wired `"enters"`; Slice 5 added `"dies"`; Slice 6 added
/// `"cast"`; Slice 7 added `"attacks"`; Slice 8 added
/// `"leaves_battlefield"`; Slice 9 adds `"blocks"`. Remaining
/// variants (`deals_damage`) still raise because their dispatch
/// sites don't exist yet — allowing them through would let
/// registry-dict callers stamp triggers that never fire, masking
/// the missing-fanout bug.
fn parse_triggered_ability(
    dict: &Bound<'_, PyDict>,
) -> PyResult<TriggeredAbility> {
    let event_str: String = require(dict, "event")?.extract().map_err(|_| {
        PyValueError::new_err("triggered_ability.event must be a string")
    })?;
    let event = match event_str.as_str() {
        "enters" => Event::Enters,
        "dies" => Event::Dies,
        "cast" => Event::Cast,
        "attacks" => Event::Attacks,
        "blocks" => Event::Blocks,
        "leaves_battlefield" => Event::LeavesBattlefield,
        // Round-58 BECOMES_TAPPED event bridge: "becomes_tapped"
        // round-trips the SAME way enters/dies/attacks do. Python's
        // `Event.BECOMES_TAPPED` string value is `"becomes_tapped"`
        // (`src/mtg_bot/effects/predicates.py:60`); the dispatcher
        // (`state_ops_resolve::dispatch_event`) and every production
        // tap site emit it in lockstep with Python's `tap_permanent`
        // chokepoint.
        "becomes_tapped" => Event::BecomesTapped,
        // Out-of-scope events stay raise-on-register. Each lands
        // alongside its dispatch fan-out so the parser surface stays
        // consistent with the dispatcher's coverage.
        "deals_damage" => {
            return Err(PyValueError::new_err(format!(
                "triggered_ability.event {event_str:?} is not yet wired in Slice 9; \
                 only \"enters\", \"dies\", \"cast\", \"attacks\", \"blocks\", \
                 \"leaves_battlefield\", and \"becomes_tapped\" dispatch today"
            )));
        }
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown triggered_ability.event {other:?}; \
                 valid: enters, dies, cast, attacks, blocks, \
                 leaves_battlefield, becomes_tapped (Slice 9 + r58)"
            )));
        }
    };
    let effect_any = require(dict, "effect")?;
    let effect_dict = effect_any.downcast::<PyDict>().map_err(|_| {
        PyValueError::new_err("triggered_ability.effect must be a dict")
    })?;
    let effect = parse_effect(effect_dict)?;
    let predicate = match dict.get_item("predicate")? {
        Some(pred_any) => {
            let pred_dict = pred_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("triggered_ability.predicate must be a dict")
            })?;
            parse_predicate(pred_dict)?
        }
        None => Predicate::Always,
    };
    let once_per_turn = match dict.get_item("once_per_turn")? {
        Some(v) => v.extract::<bool>().map_err(|_| {
            PyValueError::new_err(
                "triggered_ability.once_per_turn must be a bool",
            )
        })?,
        None => false,
    };
    Ok(TriggeredAbility {
        event,
        predicate,
        effect,
        once_per_turn,
    })
}

/// Parse one `Predicate` from a registry dict. Dict shape:
///
/// ```python
/// {"kind": "always"}
/// {"kind": "source_is_self"}
/// {"kind": "source_is_creature"}
/// {"kind": "subject_is_land"}        # Slice 4
/// {"kind": "subject_is_artifact"}    # Slice 4
/// {"kind": "subject_is_creature"}    # Slice 4
/// {"kind": "controlled_by_you"}      # Slice 4
/// {"kind": "subject_has_subtype",    # Subtypes Slice 2
///  "subtype": "Kavu"}
/// {"kind": "not", "inner": {...}}
/// {"kind": "and", "left": {...}, "right": {...}}
/// {"kind": "or", "left": {...}, "right": {...}}     # Or-substrate slice
/// ```
///
/// Slice 1 introduced the base algebra (`always`, `source_is_self`,
/// `source_is_creature`, `not`, `and`). Slice 4 added the subject-
/// anchored type filters + `controlled_by_you` to unlock landfall /
/// artifact-enters / "under your control" trigger shapes from
/// `cards/parser/triggers.py:603-1266`. Subtypes Slice 2 added
/// `subject_has_subtype` for Kavu/Sliver/Equipment-enters shapes
/// (`cards/parser/triggers.py:1198`). The Or-substrate slice added
/// `or` for shapes like Weftstalker Ardent's "whenever a creature
/// or artifact you control enters"
/// (`(subject_is_creature OR subject_is_artifact) AND
/// controlled_by_you`).
fn parse_predicate(dict: &Bound<'_, PyDict>) -> PyResult<Predicate> {
    let kind: String = require(dict, "kind")?.extract()?;
    match kind.as_str() {
        "always" => Ok(Predicate::Always),
        "source_is_self" => Ok(Predicate::SourceIsSelf),
        "source_is_creature" => Ok(Predicate::SourceIsCreature),
        "subject_is_land" => Ok(Predicate::SubjectIsLand),
        "subject_is_artifact" => Ok(Predicate::SubjectIsArtifact),
        "subject_is_creature" => Ok(Predicate::SubjectIsCreature),
        "controlled_by_you" => Ok(Predicate::ControlledByYou),
        // Subtypes substrate Slice 2 — subject-anchored HasSubtype.
        // Dict shape: `{"kind": "subject_has_subtype", "subtype": "Kavu"}`.
        // The `subtype` payload is the canonical Title Case string
        // that lives in `CardPrinting.subtypes`.
        "subject_has_subtype" => {
            let subtype: String = require(dict, "subtype")?
                .extract()
                .map_err(|e| {
                    PyValueError::new_err(format!(
                        "predicate.subject_has_subtype.subtype must be a \
                         string (got: {e})"
                    ))
                })?;
            Ok(Predicate::SubjectHasSubtype(subtype))
        }
        "not" => {
            let inner_any = require(dict, "inner")?;
            let inner_dict = inner_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("predicate.not.inner must be a dict")
            })?;
            Ok(Predicate::Not(Box::new(parse_predicate(inner_dict)?)))
        }
        "and" => {
            let left_any = require(dict, "left")?;
            let right_any = require(dict, "right")?;
            let left_dict = left_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("predicate.and.left must be a dict")
            })?;
            let right_dict = right_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("predicate.and.right must be a dict")
            })?;
            Ok(Predicate::And(
                Box::new(parse_predicate(left_dict)?),
                Box::new(parse_predicate(right_dict)?),
            ))
        }
        // Or-substrate slice — logical disjunction over two sub-
        // predicates. Mirrors the `and` arm's shape exactly. Unlocks
        // "creature OR artifact" / "Kavu OR Sliver" predicate shapes
        // from `cards/parser/triggers.py`.
        "or" => {
            let left_any = require(dict, "left")?;
            let right_any = require(dict, "right")?;
            let left_dict = left_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("predicate.or.left must be a dict")
            })?;
            let right_dict = right_any.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("predicate.or.right must be a dict")
            })?;
            Ok(Predicate::Or(
                Box::new(parse_predicate(left_dict)?),
                Box::new(parse_predicate(right_dict)?),
            ))
        }
        other => Err(PyValueError::new_err(format!(
            "unknown predicate kind {other:?}; \
             valid: always, source_is_self, source_is_creature, \
             subject_is_land, subject_is_artifact, subject_is_creature, \
             controlled_by_you, subject_has_subtype, not, and, or"
        ))),
    }
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

pub(crate) fn effect_to_pydict<'py>(
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
        Effect::MillTargetPlayer { count } => {
            d.set_item("kind", "mill_target_player")?;
            d.set_item("count", *count)?;
        }
        Effect::MillTargetPlayerEqualToYourLifeTotal => {
            // BLOCKED-RUST-EFFECT slice (round 42). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // current life total). Mirrors Python's
            // `MillTargetPlayer(use_controller_life=True)` dict shape
            // — the `amount` field is ignored on the dynamic lane
            // (the count comes from life total, not the static
            // amount). Sister of round-32 / 35 / 36 / 37 (damage
            // substrate), round-33 (counters substrate), round-34
            // (surveil substrate) — FOURTH apply substrate and FIFTH
            // denominator on the X-from-count plumbing.
            d.set_item(
                "kind",
                "mill_target_player_equal_to_your_life_total",
            )?;
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
        Effect::DestroyTargetCreatureThenDrawIfUndamaged { draw_amount } => {
            // BLOCKED-RUST-EFFECT slice — Faller's Faithful ETB.
            // Round-trip dict-shape: kind + draw_amount only (no
            // target key — the defender-bf first-slice picker derives
            // its target deterministically, mirroring the
            // ExileEachOpponentsGraveyard / EachOpponentMillsCards
            // unit-shape convention).
            d.set_item("kind", "destroy_target_creature_then_draw_if_undamaged")?;
            d.set_item("draw_amount", *draw_amount)?;
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
        Effect::CreateTokenEachPlayer { count, token_printing_id } => {
            // BLOCKED-RUST-EFFECT slice (round 43). Two-field schema
            // mirrors the sister `CreateToken` arm above; the
            // each-player vs self-only choice rides on the variant
            // name (and thus on the dict `kind` string), not on a
            // boolean field. Mirrors Python's
            // `CreateToken(each_player=True)` -- the Python class
            // has a single `each_player: bool` field, but the bridge
            // dict-shape uses a distinct `kind` for round-trip
            // clarity.
            d.set_item("kind", "create_token_each_player")?;
            d.set_item("count", *count)?;
            d.set_item("token_printing_id", *token_printing_id)?;
        }
        Effect::CreateTokenTapped { count, token_printing_id } => {
            // Phase 6 token-printing substrate -- Phase 4 (round 50).
            // Two-field schema mirrors the sister `CreateToken` arm
            // above; the tapped-vs-untapped choice rides on the
            // variant name (and thus on the dict `kind` string), not
            // on a boolean field. Mirrors Python's
            // `CreateToken(tapped=True)` -- the Python class has a
            // single `tapped: bool` field, but the bridge dict-shape
            // uses a distinct `kind` for round-trip clarity.
            d.set_item("kind", "create_token_tapped")?;
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
        Effect::Surveil { count } => {
            d.set_item("kind", "surveil")?;
            d.set_item("count", *count)?;
        }
        Effect::CounterTargetSpell => {
            d.set_item("kind", "counter_target_spell")?;
        }
        Effect::ReturnCreatureFromYourGraveyardToBattlefield => {
            d.set_item("kind", "return_creature_from_your_graveyard_to_battlefield")?;
        }
        Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield => {
            d.set_item(
                "kind",
                "return_enchantment_or_creature_from_your_graveyard_to_battlefield",
            )?;
        }
        Effect::DiscardSelf { amount } => {
            d.set_item("kind", "discard_self")?;
            d.set_item("amount", *amount)?;
        }
        Effect::EachOpponentLosesLife { amount } => {
            d.set_item("kind", "each_opponent_loses_life")?;
            d.set_item("amount", *amount)?;
        }
        Effect::EachOpponentLosesLifeEqualToArtifactCount => {
            // BLOCKED-RUST-EFFECT slice (round 44). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // battlefield artifact count). Mirrors Python's
            // EachOpponentLosesLifeEqualToArtifactCount dict shape (no
            // static `amount` field on the @dataclass). Sister of
            // round-26 EachOpponentLosesLife with the same recipient
            // set and apply step but a dynamic-X amount via the
            // artifact-count denominator (FIFTH apply substrate to
            // pick up the round-32 X-from-count plumbing).
            d.set_item(
                "kind",
                "each_opponent_loses_life_equal_to_artifact_count",
            )?;
        }
        Effect::EachOpponentLosesLifeEqualToYourLifeTotal => {
            // BLOCKED-RUST-EFFECT slice (round 48). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // current life total, clamped to >= 0). Mirrors Python's
            // EachOpponentLosesLifeEqualToYourLifeTotal dict shape (no
            // static `amount` field on the @dataclass). Sister of
            // round-44 EachOpponentLosesLifeEqualToArtifactCount with
            // the same recipient set and apply step but a life-total
            // denominator (SECOND denominator on the life-loss-each-
            // opponent apply substrate; life-total precedent set by
            // round-42 mill / round-47 damage on other substrates).
            d.set_item(
                "kind",
                "each_opponent_loses_life_equal_to_your_life_total",
            )?;
        }
        Effect::GainLifeEqualToArtifactCount => {
            // BLOCKED-RUST-EFFECT slice (round 45). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // battlefield artifact count). Mirrors Python's
            // GainLifeEqualToArtifactCount dict shape (no static
            // `amount` field on the @dataclass). Sister of round-26
            // GainLife with the SAME recipient (the source's
            // controller) and the SAME apply step (direct life
            // addition) but a dynamic-X amount via the artifact-count
            // denominator (SIXTH apply substrate to pick up the
            // round-32 X-from-count plumbing). Controller-self mirror
            // of round-44 EachOpponentLosesLifeEqualToArtifactCount
            // (same denominator, inverted recipient + sign).
            d.set_item(
                "kind",
                "gain_life_equal_to_artifact_count",
            )?;
        }
        Effect::GainLifeEqualToYourLifeTotal => {
            // BLOCKED-RUST-EFFECT slice (round 49). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // current life total, clamped to >= 0). Mirrors Python's
            // GainLifeEqualToYourLifeTotal dict shape (no static
            // `amount` field on the @dataclass). Sister of round-45
            // GainLifeEqualToArtifactCount with the SAME recipient
            // (the source's controller) and the SAME apply step
            // (direct life addition via gain_life) but a life-total
            // denominator (SECOND denominator on the gain-life-
            // controller-self apply substrate; life-total precedent
            // set by round-42 mill / round-47 damage / round-48
            // each-opponent-loses on other substrates).
            d.set_item(
                "kind",
                "gain_life_equal_to_your_life_total",
            )?;
        }
        Effect::LoseLife { amount } => {
            d.set_item("kind", "lose_life")?;
            d.set_item("amount", *amount)?;
        }
        Effect::TargetOpponentLosesLife { amount } => {
            d.set_item("kind", "target_opponent_loses_life")?;
            d.set_item("amount", *amount)?;
        }
        Effect::EachOpponentDiscards { count } => {
            d.set_item("kind", "each_opponent_discards")?;
            d.set_item("count", *count)?;
        }
        Effect::DestroyAllCreatures => {
            d.set_item("kind", "destroy_all_creatures")?;
        }
        Effect::DestroyTargetNonlandPermanent => {
            d.set_item("kind", "destroy_target_nonland_permanent")?;
        }
        Effect::DestroyTargetArtifact => {
            d.set_item("kind", "destroy_target_artifact")?;
        }
        Effect::DestroyTargetLand => {
            d.set_item("kind", "destroy_target_land")?;
        }
        Effect::DestroyTargetNoncreaturePermanent => {
            d.set_item("kind", "destroy_target_noncreature_permanent")?;
        }
        Effect::DestroyTargetArtifactOrTappedCreature => {
            d.set_item("kind", "destroy_target_artifact_or_tapped_creature")?;
        }
        Effect::SeedshipImpactEffect { token_printing_id } => {
            d.set_item("kind", "seedship_impact_effect")?;
            d.set_item("token_printing_id", *token_printing_id)?;
        }
        Effect::DealDamageAnyTarget { amount } => {
            d.set_item("kind", "deal_damage_any_target")?;
            d.set_item("amount", *amount)?;
        }
        Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus } => {
            d.set_item("kind", "pump_self_until_eot")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::PumpTargetCreatureUntilEOT { power_bonus, toughness_bonus } => {
            d.set_item("kind", "pump_target_creature_until_eot")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::PumpTargetCreatureUntilEotGrantDiesReturnTapped {
            power_bonus,
            toughness_bonus,
        } => {
            // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner.
            // Round-trips the same two fields the parse arm reads; the
            // another/you-control restriction + dies-return-tapped
            // rider are variant-intrinsic (no extra keys).
            d.set_item(
                "kind",
                "pump_target_creature_until_eot_grant_dies_return_tapped",
            )?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::FightTargetCreatureWithTargetCreature => {
            d.set_item("kind", "fight_target_creature_with_target_creature")?;
        }
        Effect::DoubleTargetCreaturesPowerUEOT => {
            // BLOCKED-RUST-EFFECT slice (round 31). Unit variant; no
            // payload fields beyond `kind`. Mirrors Python's
            // DoubleTargetCreaturesPowerUEOT dict shape.
            d.set_item("kind", "double_target_creatures_power_ueot")?;
        }
        Effect::DealDamageToOpponentCreatureByArtifactCount => {
            // BLOCKED-RUST-EFFECT slice (round 32). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // battlefield artifact count). Mirrors Python's
            // DealDamageToOpponentCreatureByArtifactCount dict shape
            // (no static `amount` field on the @dataclass).
            d.set_item("kind", "deal_damage_to_opponent_creature_by_artifact_count")?;
        }
        Effect::TwoSubjectPumpAndDebuffByArtifactCount => {
            // BLOCKED-RUST-EFFECT slice (round 51). Unit variant; no
            // payload fields beyond `kind` (X is dynamic — computed
            // at resolve time from the source-controller's
            // battlefield artifact count, clamped >= 0). Mirrors
            // Python's PumpYoursAndDebuffOpponentByArtifactCount
            // UntilEOT dict shape (no static field on the
            // @dataclass). Sister of round-32
            // DealDamageToOpponentCreatureByArtifactCount with the
            // SAME artifact-count denominator read but a two-subject
            // until-EOT pump+debuff apply substrate.
            d.set_item(
                "kind",
                "two_subject_pump_and_debuff_by_artifact_count",
            )?;
        }
        Effect::DealDamageToOpponentCreatureByCardsInHand => {
            // BLOCKED-RUST-EFFECT slice (round 35). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // hand size). Mirrors Python's
            // DealDamageToOpponentCreatureByCardsInHand dict shape
            // (no static `amount` field on the @dataclass). Sister of
            // round-32 with the same target shape but a different
            // dynamic-X denominator.
            d.set_item("kind", "deal_damage_to_opponent_creature_by_cards_in_hand")?;
        }
        Effect::DealDamageToOpponentCreatureByLandsControlled => {
            // BLOCKED-RUST-EFFECT slice (round 36). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // battlefield lands count). Mirrors Python's
            // DealDamageToOpponentCreatureByLandsControlled dict shape
            // (no static `amount` field on the @dataclass). Sister of
            // round-32 / round-35 with the same target shape but a
            // different dynamic-X denominator (lands-controlled in
            // place of artifact-count / hand-size).
            d.set_item(
                "kind",
                "deal_damage_to_opponent_creature_by_lands_controlled",
            )?;
        }
        Effect::DealDamageToOpponentCreatureByCreaturesYouControl => {
            // BLOCKED-RUST-EFFECT slice (round 37). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // battlefield creatures count). Mirrors Python's
            // DealDamageToOpponentCreatureByCreaturesYouControl dict
            // shape (no static `amount` field on the @dataclass).
            // Sister of round-32 / round-35 / round-36 with the same
            // target shape but a different dynamic-X denominator
            // (creatures-controlled in place of artifact-count /
            // hand-size / lands-controlled).
            d.set_item(
                "kind",
                "deal_damage_to_opponent_creature_by_creatures_you_control",
            )?;
        }
        Effect::DealDamageToOpponentCreatureByCardsInGraveyard => {
            // BLOCKED-RUST-EFFECT slice (round 46). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // graveyard size). Mirrors Python's
            // DealDamageToOpponentCreatureByCardsInGraveyard dict shape
            // (no static `amount` field on the @dataclass). Sister of
            // round-32 / round-35 / round-36 / round-37 with the same
            // target shape but a different dynamic-X denominator
            // (cards-in-graveyard in place of artifact-count /
            // hand-size / lands-controlled / creatures-controlled).
            // FIFTH denominator on the damage substrate; sixth overall
            // X-from-count denominator across the substrate matrix.
            d.set_item(
                "kind",
                "deal_damage_to_opponent_creature_by_cards_in_graveyard",
            )?;
        }
        Effect::DealDamageToOpponentCreatureByLifeTotal => {
            // BLOCKED-RUST-EFFECT slice (round 47). Unit variant; no
            // payload fields beyond `kind` (count is dynamic --
            // computed at resolve time from the source-controller's
            // clamped life total). Mirrors Python's
            // DealDamageToOpponentCreatureByLifeTotal dict shape (no
            // static `amount` field on the @dataclass). Sister of
            // round-32 / round-35 / round-36 / round-37 / round-46
            // with the same target shape but a different dynamic-X
            // denominator (life-total in place of artifact-count /
            // hand-size / lands-controlled / creatures-controlled /
            // cards-in-graveyard). SIXTH (final) denominator on the
            // damage substrate -- the damage substrate row of the
            // X-from-count matrix is now fully saturated.
            d.set_item(
                "kind",
                "deal_damage_to_opponent_creature_by_life_total",
            )?;
        }
        Effect::PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact => {
            // BLOCKED-RUST-EFFECT slice (round 33). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // battlefield other-creature-or-artifact count). Mirrors
            // Python's PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact
            // dict shape (no static `amount` field on the @dataclass).
            d.set_item(
                "kind",
                "put_plus_one_counters_on_self_per_other_creature_or_artifact",
            )?;
        }
        Effect::SurveilXEqualToArtifactCount => {
            // BLOCKED-RUST-EFFECT slice (round 34). Unit variant; no
            // payload fields beyond `kind` (count is dynamic —
            // computed at resolve time from the source-controller's
            // battlefield artifact count). Mirrors Python's
            // Surveil(use_artifact_count=True) dict shape — the
            // `amount` field is ignored on the dynamic lane (the
            // dispatch happens on the variant tag, not a runtime
            // flag).
            d.set_item("kind", "surveil_x_equal_to_artifact_count")?;
        }
        Effect::PumpCreaturesYouControlUntilEOT { power_bonus, toughness_bonus } => {
            d.set_item("kind", "pump_creatures_you_control_until_eot")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::ReturnCreatureFromYourGraveyardToHand => {
            d.set_item("kind", "return_creature_from_your_graveyard_to_hand")?;
        }
        Effect::ReturnArtifactOrCreatureFromYourGraveyardToHand => {
            d.set_item(
                "kind",
                "return_artifact_or_creature_from_your_graveyard_to_hand",
            )?;
        }
        Effect::ReturnCreatureOrSpacecraftFromYourGraveyardToHand => {
            d.set_item(
                "kind",
                "return_creature_or_spacecraft_from_your_graveyard_to_hand",
            )?;
        }
        Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToHand => {
            d.set_item(
                "kind",
                "return_enchantment_or_creature_from_your_graveyard_to_hand",
            )?;
        }
        Effect::PutPlusOneCounterOnEachCreatureYouControl { amount } => {
            d.set_item("kind", "put_plus_one_counter_on_each_creature_you_control")?;
            d.set_item("amount", *amount)?;
        }
        Effect::PutPlusOneCounterOnCreatureYouControl { amount } => {
            d.set_item("kind", "put_plus_one_counter_on_creature_you_control")?;
            d.set_item("amount", *amount)?;
        }
        Effect::AddNManaOfChosenColor { amount, options } => {
            d.set_item("kind", "add_n_mana_of_chosen_color")?;
            d.set_item("amount", *amount)?;
            d.set_item("options", options.clone())?;
        }
        Effect::SearchLibraryForCard {
            filter_name,
            max_mv,
            may_fail,
        } => {
            d.set_item("kind", "search_library_for_card")?;
            d.set_item("filter_name", filter_name.clone())?;
            d.set_item("max_mv", *max_mv)?;
            d.set_item("may_fail", *may_fail)?;
        }
        Effect::PumpCreaturesOpponentsControlUntilEOT { power_bonus, toughness_bonus } => {
            d.set_item("kind", "pump_creatures_opponents_control_until_eot")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn {
            power_bonus,
            toughness_bonus,
        } => {
            d.set_item("kind", "pump_creatures_opponents_control_until_caster_next_turn")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::PutCardFromGraveyardOnBottomOfLibrary => {
            d.set_item("kind", "put_card_from_graveyard_on_bottom_of_library")?;
        }
        Effect::MoveSelfCountersToTargetCreatureYouControl => {
            d.set_item("kind", "move_self_counters_to_target_creature_you_control")?;
        }
        Effect::DealDamageEqualToSourcePowerAnyTarget => {
            d.set_item("kind", "deal_damage_equal_to_source_power_any_target")?;
        }
        Effect::TapTargetArtifactOrCreature => {
            d.set_item("kind", "tap_target_artifact_or_creature")?;
        }
        Effect::ConditionalOnTappedCreatures { effect, min_count } => {
            d.set_item("kind", "conditional_on_tapped_creatures")?;
            d.set_item("effect", effect_to_pydict(py, effect)?)?;
            d.set_item("min_count", *min_count)?;
        }
        Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures { max_n } => {
            d.set_item("kind", "put_plus_one_counter_on_each_of_up_to_n_target_creatures")?;
            d.set_item("max_n", *max_n)?;
        }
        Effect::PutChargeCountersOnSelf { amount, amount_from_x } => {
            d.set_item("kind", "put_charge_counters_on_self")?;
            d.set_item("amount", *amount)?;
            d.set_item("amount_from_x", *amount_from_x)?;
        }
        Effect::CreateTokenCopyOfTargetCreatureYouControl => {
            d.set_item("kind", "create_token_copy_of_target_creature_you_control")?;
        }
        Effect::OptionalSacArtifactForEffect { inner_effect } => {
            d.set_item("kind", "optional_sac_artifact_for_effect")?;
            d.set_item("inner_effect", effect_to_pydict(py, inner_effect)?)?;
        }
        Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary => {
            d.set_item("kind", "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library")?;
        }
        Effect::AttachToTargetCreatureYouControl => {
            d.set_item("kind", "attach_to_target_creature_you_control")?;
        }
        Effect::EquipToTargetCreatureYouControl => {
            d.set_item("kind", "equip_to_target_creature_you_control")?;
        }
        Effect::DestroyEnchantedPermanent => {
            d.set_item("kind", "destroy_enchanted_permanent")?;
        }
        Effect::TapEnchantedPermanent => {
            d.set_item("kind", "tap_enchanted_permanent")?;
        }
        Effect::PutStunCounterOnTappedCreature => {
            // Round-30 stun-counter substrate. Unit variant; no
            // payload fields beyond `kind`. Mirrors Python's
            // PutStunCounterOnTappedCreature dict shape.
            d.set_item("kind", "put_stun_counter_on_tapped_creature")?;
        }
        Effect::TapTargetOpponentPermanentAndStunIt => {
            // Round-30 stun-counter substrate. Unit variant; no
            // payload fields beyond `kind`. Mirrors Python's
            // TapTargetOpponentPermanentAndStunIt dict shape.
            d.set_item("kind", "tap_target_opponent_permanent_and_stun_it")?;
        }
        Effect::ExileTargetCreatureUntilSourceLeaves => {
            d.set_item("kind", "exile_target_creature_until_source_leaves")?;
        }
        Effect::ExileOpponentsNonlandPermanentUntilLeaves => {
            d.set_item("kind", "exile_opponents_nonland_permanent_until_leaves")?;
        }
        Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves { max_mv } => {
            d.set_item(
                "kind",
                "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
            )?;
            d.set_item("max_mv", *max_mv)?;
        }
        Effect::MayDo { inner_effect, prompt } => {
            d.set_item("kind", "may_do")?;
            d.set_item("inner_effect", effect_to_pydict(py, inner_effect)?)?;
            d.set_item("prompt", prompt.as_str())?;
        }
        Effect::LookTopNPutOneInHandRestToGraveyard { n } => {
            d.set_item("kind", "look_top_n_put_one_in_hand_rest_to_graveyard")?;
            d.set_item("n", *n)?;
        }
        Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped => {
            // BLOCKED-RUST-EFFECT slice (round 54). Unit variant; no
            // payload fields beyond `kind` (X dynamic — source
            // effective power at resolve; greedy-all land selection).
            // Mirrors Python's `FamishedWorldsireETBEffect` dict shape
            // (no static fields on the @dataclass). No other keys
            // emitted (round-trip dict-shape consistency convention —
            // round-49 `gain_life_equal_to_your_life_total` precedent).
            d.set_item(
                "kind",
                "famished_worldsire_look_top_x_by_power_put_lands_tapped",
            )?;
        }
        Effect::ChooseOneMode { modes } => {
            d.set_item("kind", "choose_one_mode")?;
            let mode_dicts: Vec<Bound<'_, PyDict>> = modes
                .iter()
                .map(|m| effect_to_pydict(py, m))
                .collect::<PyResult<Vec<_>>>()?;
            d.set_item("modes", mode_dicts)?;
        }
        Effect::IfYouDo { do_action, then_action } => {
            d.set_item("kind", "if_you_do")?;
            d.set_item("do_action", effect_to_pydict(py, do_action)?)?;
            d.set_item("then_action", effect_to_pydict(py, then_action)?)?;
        }
        Effect::EachOpponentMillsCards { count } => {
            d.set_item("kind", "each_opponent_mills_cards")?;
            d.set_item("count", *count)?;
        }
        Effect::ExileEachOpponentsGraveyard => {
            d.set_item("kind", "exile_each_opponents_graveyard")?;
        }
        Effect::PumpTargetArtifactOrCreatureUntilEOT { power_bonus, toughness_bonus } => {
            d.set_item("kind", "pump_target_artifact_or_creature_until_eot")?;
            d.set_item("power_bonus", *power_bonus)?;
            d.set_item("toughness_bonus", *toughness_bonus)?;
        }
        Effect::EachOpponentSacrificesCreature => {
            d.set_item("kind", "each_opponent_sacrifices_creature")?;
        }
        Effect::GrantKeywordToTargetCreatureUntilEOT { keyword } => {
            d.set_item("kind", "grant_keyword_to_target_creature_until_eot")?;
            d.set_item("keyword", keyword.as_str())?;
        }
        Effect::GrantKeywordsToTargetCreatureUntilEOT { keywords, exclude_source } => {
            d.set_item("kind", "grant_keywords_to_target_creature_until_eot")?;
            // Round-trip the keyword list as a Python list-of-strings.
            let kw_list: Vec<&str> = keywords.iter().map(|s| s.as_str()).collect();
            d.set_item("keywords", kw_list)?;
            d.set_item("exclude_source", *exclude_source)?;
        }
        Effect::UntapTargetOtherPermanent => {
            d.set_item("kind", "untap_target_other_permanent")?;
        }
        Effect::TapAnotherTargetCreature => {
            d.set_item("kind", "tap_another_target_creature")?;
        }
        Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield => {
            d.set_item("kind", "return_all_creatures_from_your_graveyard_to_battlefield")?;
        }
        Effect::SetBasePTUntilEOT { power, toughness } => {
            d.set_item("kind", "set_base_pt_until_eot")?;
            d.set_item("power", *power)?;
            d.set_item("toughness", *toughness)?;
        }
        Effect::ManifestDread { count } => {
            d.set_item("kind", "manifest_dread")?;
            d.set_item("count", *count)?;
        }
        Effect::ManifestDreadThenAttachSelf { count } => {
            d.set_item("kind", "manifest_dread_then_attach_self")?;
            d.set_item("count", *count)?;
        }
        Effect::ManifestDreadThenPutPlusOneCountersOnIt { count, counter_amount } => {
            d.set_item("kind", "manifest_dread_then_put_plus_one_counters_on_it")?;
            d.set_item("count", *count)?;
            d.set_item("counter_amount", *counter_amount)?;
        }
        Effect::ConditionalIfVoid { then_effect, else_effect } => {
            d.set_item("kind", "conditional_if_void")?;
            d.set_item("then_effect", effect_to_pydict(py, then_effect)?)?;
            match else_effect {
                Some(inner) => {
                    d.set_item("else_effect", effect_to_pydict(py, inner)?)?;
                }
                None => {
                    d.set_item("else_effect", py.None())?;
                }
            }
        }
        Effect::DealDamageToOpponentCreature { amount } => {
            d.set_item("kind", "deal_damage_to_opponent_creature")?;
            d.set_item("amount", *amount)?;
        }
        Effect::LookAtTopNRevealOrCounter {
            n,
            filter_name,
            max_power,
            counter_on_miss,
        } => {
            d.set_item("kind", "look_at_top_n_reveal_or_counter")?;
            d.set_item("n", *n)?;
            d.set_item("filter_name", filter_name.as_str())?;
            d.set_item("max_power", *max_power)?;
            d.set_item("counter_on_miss", *counter_on_miss)?;
        }
        Effect::BecomeLandCreatureUEOT {
            power,
            toughness,
            granted_subtype,
        } => {
            d.set_item("kind", "become_land_creature_ueot")?;
            d.set_item("power", *power)?;
            d.set_item("toughness", *toughness)?;
            // Emit `granted_subtype` as the string when set, None
            // otherwise — round-trip preserves the optionality.
            match granted_subtype {
                Some(s) => d.set_item("granted_subtype", s.as_str())?,
                None => d.set_item("granted_subtype", py.None())?,
            }
        }
        Effect::Sequence { effects } => {
            d.set_item("kind", "sequence")?;
            // Recursively serialize each child via effect_to_pydict
            // (same function recurses safely — Effect is heap-
            // allocated via Vec<Effect>).
            let children: Vec<Bound<'_, PyDict>> = effects
                .iter()
                .map(|child| effect_to_pydict(py, child))
                .collect::<PyResult<Vec<_>>>()?;
            d.set_item("effects", children)?;
        }
        Effect::OptionalManaCostThenEffect { cost, inner_effect } => {
            d.set_item("kind", "optional_mana_cost_then_effect")?;
            d.set_item("cost", mana_cost_to_pydict(py, cost)?)?;
            d.set_item("inner_effect", effect_to_pydict(py, inner_effect)?)?;
        }
        Effect::DrawCardsEqualToResolvingCombatDamage => {
            d.set_item("kind", "draw_cards_equal_to_resolving_combat_damage")?;
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

    /// MTG card subtypes: "Forest", "Bear", "Equipment", "Aura", etc.
    /// Empty when the type line has no subtypes (vanilla
    /// instants/sorceries). Mirrors Python's
    /// `CardPrinting.subtypes: tuple[str, ...]`.
    fn get_printing_subtypes(&self, id: u32) -> PyResult<Vec<String>> {
        Ok(self.lookup(id)?.subtypes.clone())
    }

    /// MTG card supertypes: "Basic", "Legendary", "Snow", "World",
    /// "Token". Empty when the type line has no supertype prefix.
    /// Mirrors Python's `CardPrinting.supertypes: tuple[str, ...]`.
    /// Round-30 substrate addition.
    fn get_printing_supertypes(&self, id: u32) -> PyResult<Vec<String>> {
        Ok(self.lookup(id)?.supertypes.clone())
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
