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
        "deal_damage_any_target" => {
            // Python's `DealDamageAnyTarget(DealDamage)` carries only
            // the inherited `amount` field; the "any target" filter is
            // intrinsic to the variant (no `target` dict to parse —
            // distinct from `deal_damage`'s required `target` field).
            // Missing `amount` is a KeyError at register time;
            // negative amount surfaces at register time (defense-in-
            // depth; `apply_effect` re-checks).
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
            "unknown effect kind {other:?}; valid: deal_damage, draw_cards, gain_life, return_to_hand, mill, mill_target_player, exile_target, tap_target, untap_target, sacrifice, add_counters, discard_card, scry_n, destroy_target, damage_each_opponent, damage_each_creature, create_token, add_mana_to_pool, search_library_for_basic_land_tapped, put_plus_one_counter_on_self, surveil, counter_target_spell, return_creature_from_your_graveyard_to_battlefield, discard_self, each_opponent_loses_life, lose_life, target_opponent_loses_life, each_opponent_discards, destroy_all_creatures, destroy_target_nonland_permanent, destroy_target_artifact, destroy_target_land, deal_damage_any_target, pump_self_until_eot, pump_target_creature_until_eot, sequence"
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
        Effect::MillTargetPlayer { count } => {
            d.set_item("kind", "mill_target_player")?;
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
        Effect::DiscardSelf { amount } => {
            d.set_item("kind", "discard_self")?;
            d.set_item("amount", *amount)?;
        }
        Effect::EachOpponentLosesLife { amount } => {
            d.set_item("kind", "each_opponent_loses_life")?;
            d.set_item("amount", *amount)?;
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
