use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;

use crate::cards::{CardPrinting, ManaCost, Registry, RegistryData};

/// **POD-shaped** game object referencing card data by `printing_id`.
///
/// Pre-registry: the object inlined `name: String`, `power: i16`,
/// `toughness: i16` per copy — so each per-zone Vec carried a
/// heap-allocated String per card, and cloning a zone (when CoW
/// fired on first mutation) had to clone every String. With this
/// migration, all card-data (name, p/t once we wire it through,
/// mana cost, effects, ...) lives in the shared
/// `Arc<RegistryData>` on the `GameState`; the GameObject keeps
/// only the per-instance state (id, controller, zone, tapped,
/// summoning sick, damage, counters) plus a `printing_id: u32`
/// pointer into the registry.
///
/// The struct is now POD (Plain Old Data) — every field is `Copy`,
/// so a Vec of GameObjects is a single contiguous block of `memcpy`-
/// able bytes. With `repr(C)` the layout is 16 bytes per object on
/// 64-bit (4+4+1+1+1+1+2+4 = 18 bytes payload, padded to 20 then
/// rounded for alignment — actual `size_of::<GameObject>()` is
/// 20 bytes; if we want it tighter we'd reorder + pack, but 20 vs
/// the prior ~40 (header + ptr + len + cap + bools + ints) is
/// already a 2x shrink).
#[derive(Clone, Copy, Debug)]
pub struct GameObject {
    pub id: u32,
    pub printing_id: u32,
    pub controller: u8,
    pub zone: u8,
    pub tapped: bool,
    pub summoning_sick: bool,
    pub damage: i16,
    pub counters: i32,
}

// Zones are `Arc<Vec<GameObject>>` so cloning a `Player` (and therefore
// a `GameState`) is an atomic refcount bump per zone instead of a full
// copy. Mutating a zone goes through `Arc::make_mut`, which clones the
// inner Vec only if any other clone is observing it — same shape as
// the Python side's `_CowList`.
pub type Zone = Arc<Vec<GameObject>>;

/// Mana pool for one player. Five colors + colorless; capped at u8
/// per color (255 of any color is more than any real game produces).
/// Hybrid / X / snow mana are not yet modeled; future slices add
/// them when a card needs them.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ManaPool {
    pub white: u8,
    pub blue: u8,
    pub black: u8,
    pub red: u8,
    pub green: u8,
    pub colorless: u8,
}

#[derive(Clone, Debug)]
pub struct Player {
    pub id: u8,
    pub life: i32,
    pub mana_pool: ManaPool,
    pub hand: Zone,
    pub library: Zone,
    pub battlefield: Zone,
    pub graveyard: Zone,
    /// Exile zone (CR 406). Cards exiled by effects land here.
    /// Round-11 foundation addition — round-1 zone primitives
    /// (find_object_zone / move_object) iterate the four pre-r11
    /// zones and don't yet search exile; that's a future-slice
    /// upgrade once anything is read FROM exile (today exile is
    /// write-only via Effect::ExileTarget).
    pub exile: Zone,
    /// Sticky loss flag (CR 104.2). Once `true`, the player has
    /// lost the game and the loss is permanent — subsequent
    /// `gain_life` or other mutations cannot revive them. Mirrors
    /// Python's `Player.has_lost`. Read by `losers()` /
    /// `winner()` / `is_game_over()` / `apply_sbas()`. Written by
    /// `apply_sbas()` (transitions `attempted_draw_on_empty` ->
    /// `has_lost` and the existing `life <= 0` predicate). Round-26
    /// G11 closure. (No explicit `lose_game(p)` primitive yet — the
    /// skipped `test_explicit_lose_game_marks_player` un-skip lands when
    /// the dispatch hook for Phage / Bargain / deck-out effect arms is
    /// wired; this slice only adds the field + SBA transition.)
    pub has_lost: bool,
    /// Cause-signal flag set by the empty-library draw path (CR
    /// 704.5b — a player who attempted to draw from an empty library
    /// loses on the next SBA pass). Written by `draw_card` and the
    /// `Effect::DrawCards` resolution arm when the library pop returns
    /// None; read by `apply_sbas` which then transitions this flag
    /// into the sticky `has_lost`. `losers()` ALSO OR's this flag
    /// in directly so the loss is observable BEFORE the next SBA pass
    /// runs (mirrors Python's eager `has_lost = True` in
    /// `turn.draw_card`, where the loss is visible to the very next
    /// `losers()` read). Round-26 G10 closure.
    pub attempted_draw_on_empty: bool,
    /// Per-player count of `mulligan` / `mulligan_to_n` calls taken on
    /// this state. Incremented at the START of each call; if it
    /// exceeds the practical London-mulligan cap (7 — mirrors Python
    /// `simulate.setup_game(max_mulligans=7)`), the call raises
    /// instead of performing the shuffle. Round-26 G23 closure.
    /// Per CR 103.4 the 8th mulligan would draw a hand of -1 cards,
    /// which is nonsensical; Python guards it by capping the loop at
    /// 7 mulligans before forcing keep. The Rust primitive raises so
    /// callers can't silently exceed the cap.
    ///
    /// NOT serialized into the fingerprint — this is a per-call
    /// safety counter, not part of the gameplay-relevant state digest.
    /// Same `(state, seed)` pre- and post-mulligan must produce the
    /// same fingerprint regardless of how many mulligans were taken
    /// to get there.
    pub mulligan_count: u32,
}

/// One pending entry on the stack. First-slice shape: just an obj_id
/// (the source spell or activated-ability source) + controller. Real
/// stack items will need more (target list, choices, modal mode);
/// future slices extend.
#[derive(Clone, Debug)]
pub struct StackItem {
    pub source_obj_id: u32,
    pub controller: u8,
}

/// A choice the engine is waiting on. Pushed onto
/// `GameState.pending_decisions` by an effect whose resolution
/// requires a controller-provided choice (e.g. Surveil — which of
/// the observed cards to send to graveyard, which to keep on top).
///
/// Round-27 G20 closure introduces the substrate. First variant:
/// `SurveilChoice` — the cards looked at, the controller, and the
/// source obj id (for log-correlation). The dispatcher
/// `submit_surveil_decision` consumes this variant; future variants
/// (`LondonBottomN` for G22, `ScryOnKeep` for G24, `ModalChooseOne`,
/// `ManifestDread`, ...) follow the same `apply_effect` → push →
/// pause / caller pops → submit shape.
///
/// **State-affecting**: a pending decision IS part of the gameplay-
/// relevant digest. A state with a pending decision differs from
/// one without (the observed cards are off-library-top but not yet
/// in graveyard; the next decision shapes the library + graveyard
/// final shape). `Clone` clones the Vec, so a cloned state carries
/// its pending decisions; CoW is not needed (the Vec is owned per
/// `GameState`, not shared across clones).
#[derive(Clone, Debug)]
pub enum PendingDecision {
    /// Surveil N (CR 701.43). The controller has just looked at
    /// `cards` (popped off library top, top-most first). For each
    /// one they choose either "top of library" (preserving the
    /// caller's submitted order) or "graveyard". Until the caller
    /// submits a decision the cards live in this variant — NOT in
    /// the library, NOT in the graveyard.
    ///
    /// `cards` carries the full `GameObject` payload (POD `Copy`),
    /// not just the id — the submit dispatcher needs the printing_id
    /// + controller + counters when re-pushing into library or
    /// graveyard. Order matches the order popped off library top:
    /// `cards[0]` was the topmost card, `cards[1]` was second-from-
    /// top, etc.
    SurveilChoice {
        source_obj_id: u32,
        controller: u8,
        cards: Vec<GameObject>,
    },
}

/// `GameState` carries an `Arc<RegistryData>` so every clone shares
/// the printings catalogue at refcount-bump cost. Per-instance
/// state — players, zones, turn counter — clones via the `Player`
/// struct's CoW zones (see `Zone` doc).
#[derive(Clone, Debug)]
#[pyclass(name = "GameState")]
pub struct GameState {
    pub players: [Player; 2],
    pub registry: Arc<RegistryData>,
    pub active_player: u8,
    pub priority_player: u8,
    pub turn_number: u32,
    pub phase: u8,
    /// Combat: ids of creatures currently declared as attackers.
    pub attackers: Vec<u32>,
    /// Combat: (attacker_id, blocker_id) pairs declared this combat.
    /// One attacker can be blocked by multiple blockers (multi-block);
    /// represented as multiple entries with the same attacker_id.
    pub blockers: Vec<(u32, u32)>,
    /// The stack — top is the LAST element of the Vec for O(1) pop.
    pub stack: Vec<StackItem>,
    /// Decisions the engine is waiting on. Round-27 G20 closure —
    /// effects whose resolution needs a controller-provided choice
    /// (Surveil, future London bottom-N, future scry-on-keep,
    /// future modal-choose) push a `PendingDecision` here and
    /// short-circuit their `apply_effect` arm. The caller (MCTS,
    /// parity_smoke, test harness) inspects via
    /// `pending_decisions()` / `has_pending_decision()`, resolves
    /// via the variant-specific `submit_*_decision` dispatcher
    /// (e.g. `submit_surveil_decision`).
    ///
    /// **State-affecting** (mirrors Python's pause-and-resume
    /// decision shape — see `mtg_bot.search.resolution_channel` /
    /// `ResolutionSurveilDecision`): a pending decision is part of
    /// the gameplay-relevant digest. The fingerprint serializes
    /// this slot; baselines shifted in r27 (this round) and the
    /// pinned digests have been refreshed.
    ///
    /// FIFO: the dispatcher consumes index 0 first. Typically only
    /// one decision is pending at a time (a single Effect arm
    /// short-circuited mid-resolution); the Vec shape lets future
    /// modal-on-cast / staged-decision flows queue several without
    /// re-architecting.
    pub pending_decisions: Vec<PendingDecision>,
}

#[pymethods]
impl GameState {
    #[getter]
    fn turn_number(&self) -> u32 {
        self.turn_number
    }

    #[getter]
    fn battlefield_sizes(&self) -> [usize; 2] {
        [self.players[0].battlefield.len(), self.players[1].battlefield.len()]
    }

    #[getter]
    fn hand_sizes(&self) -> [usize; 2] {
        [self.players[0].hand.len(), self.players[1].hand.len()]
    }

    #[getter]
    fn library_sizes(&self) -> [usize; 2] {
        [self.players[0].library.len(), self.players[1].library.len()]
    }

    #[getter]
    fn life_totals(&self) -> [i32; 2] {
        [self.players[0].life, self.players[1].life]
    }

    #[getter]
    fn registry_size(&self) -> usize {
        self.registry.len()
    }

    fn clone_once(&self) -> GameState {
        self.clone()
    }

    fn clone_n_times_micros(&self, n: usize) -> f64 {
        let start = Instant::now();
        for _ in 0..n {
            let cloned = self.clone();
            std::hint::black_box(cloned);
        }
        let elapsed = start.elapsed();
        (elapsed.as_secs_f64() * 1_000_000.0) / n as f64
    }

    /// Resolve a GameObject id (searched across both players' four
    /// zones) to its printing's name. Returns `None` (Python `None`)
    /// if no object with that id exists in any zone.
    ///
    /// This is the smallest end-to-end test of the Registry wiring:
    /// it walks every zone, finds the object with matching `id`,
    /// looks up its `printing_id` in `self.registry`, and returns
    /// the printing's name. A failure anywhere in the chain — wrong
    /// id, wrong printing_id, registry not threaded through — shows
    /// up here.
    fn printing_name_of(&self, obj_id: u32) -> Option<String> {
        for player in &self.players {
            for zone in [
                &player.hand,
                &player.library,
                &player.battlefield,
                &player.graveyard,
            ] {
                for obj in zone.iter() {
                    if obj.id == obj_id {
                        return self
                            .registry
                            .lookup(obj.printing_id)
                            .map(|p| p.name.to_string());
                    }
                }
            }
        }
        None
    }

    /// Same as `printing_name_of` but raises KeyError on miss —
    /// useful when Python code wants the loud-fail variant.
    fn require_printing_name_of(&self, obj_id: u32) -> PyResult<String> {
        self.printing_name_of(obj_id).ok_or_else(|| {
            PyKeyError::new_err(format!("no game object with id {obj_id}"))
        })
    }
}

fn make_object(id: u32, controller: u8, printing_id: u32) -> GameObject {
    GameObject {
        id,
        printing_id,
        controller,
        zone: 1,
        tapped: false,
        summoning_sick: false,
        damage: 0,
        counters: 0,
    }
}

fn make_player(
    id: u8,
    num_battlefield: usize,
    num_hand: usize,
    num_library: usize,
    base_id: u32,
    forest_pid: u32,
    bears_pid: u32,
    elves_pid: u32,
) -> Player {
    let mut next = base_id;
    let mut battlefield = Vec::with_capacity(num_battlefield);
    let half = num_battlefield / 2;
    for _ in 0..half {
        battlefield.push(make_object(next, id, forest_pid));
        next += 1;
    }
    for _ in half..num_battlefield {
        battlefield.push(make_object(next, id, bears_pid));
        next += 1;
    }
    let mut hand = Vec::with_capacity(num_hand);
    for _ in 0..num_hand {
        hand.push(make_object(next, id, elves_pid));
        next += 1;
    }
    let mut library = Vec::with_capacity(num_library);
    for _ in 0..num_library {
        library.push(make_object(next, id, forest_pid));
        next += 1;
    }
    Player {
        id,
        life: 20,
        mana_pool: ManaPool::default(),
        hand: Arc::new(hand),
        library: Arc::new(library),
        battlefield: Arc::new(battlefield),
        graveyard: Arc::new(Vec::new()),
        exile: Arc::new(Vec::new()),
        has_lost: false,
        attempted_draw_on_empty: false,
        mulligan_count: 0,
    }
}

/// Build a synthetic GameState with a small in-process registry of
/// 3 vanilla printings (Forest, Grizzly Bears, Llanowar Elves).
/// Each GameObject in the resulting state references one of those
/// printings by id — no per-object name/p/t/cost duplication.
///
/// The `make_player` placement loop puts elves in hand first (so
/// the first hand object resolves to "Llanowar Elves"), forests +
/// bears split on the battlefield, and forests in the library.
/// The Python smoke tests rely on that ordering to verify the
/// printing-name lookup chain.
#[pyfunction]
#[pyo3(signature = (num_battlefield = 10, num_hand = 7, num_library = 50))]
pub fn make_synthetic_state(
    num_battlefield: usize,
    num_hand: usize,
    num_library: usize,
) -> GameState {
    // Build the registry up-front, snapshot it, share the Arc.
    //
    // Round-3 bridge extension: each printing now carries optional
    // `power` / `toughness` / `mana_produced`. Forest is non-creature
    // (no P/T) but produces {G}; Grizzly Bears is a 2/2 with no
    // mana production; Llanowar Elves is a 1/1 that for first-slice
    // we model as if `mana_produced` were intrinsic (the real card's
    // "{T}: Add {G}" is an activated ability, but the abilities
    // schema doesn't exist yet — see the docstring on `tap_for_mana`
    // in state_ops_mana.rs and the `SEARCH_LIMITATIONS.md` entry
    // referenced from this slice's commit).
    let mut builder = Registry::default();
    let forest_pid = builder.push_printing(CardPrinting {
        name: Arc::from("Forest"),
        mana_cost: ManaCost::default(),
        effects: Vec::new(),
        power: None,
        toughness: None,
        mana_produced: Some(vec!["G".to_string()]),
        card_types: vec!["Land".to_string()],
        keywords: Vec::new(),
        etb_effects: Vec::new(),
    });
    let bears_pid = builder.push_printing(CardPrinting {
        name: Arc::from("Grizzly Bears"),
        mana_cost: ManaCost {
            generic: 1,
            green: 1,
            ..ManaCost::default()
        },
        effects: Vec::new(),
        power: Some(2),
        toughness: Some(2),
        mana_produced: None,
        card_types: vec!["Creature".to_string()],
        keywords: Vec::new(),
        etb_effects: Vec::new(),
    });
    let elves_pid = builder.push_printing(CardPrinting {
        name: Arc::from("Llanowar Elves"),
        mana_cost: ManaCost {
            green: 1,
            ..ManaCost::default()
        },
        effects: Vec::new(),
        power: Some(1),
        toughness: Some(1),
        // Oversimplification: real Llanowar Elves has the activated
        // ability "{T}: Add {G}". Until the ability schema lands
        // we treat `mana_produced` on a creature the same way we
        // treat it on a land — `tap_for_mana` succeeds for either.
        // The cast slice will use card_types to correctly reject
        // play_land(llanowar) — the previous mana_produced.is_some()
        // check produced a documented false-positive.
        mana_produced: Some(vec!["G".to_string()]),
        card_types: vec!["Creature".to_string()],
        keywords: Vec::new(),
        etb_effects: Vec::new(),
    });
    let registry = builder.snapshot();

    let p0 = make_player(
        0,
        num_battlefield,
        num_hand,
        num_library,
        0,
        forest_pid,
        bears_pid,
        elves_pid,
    );
    let id_offset = (num_battlefield + num_hand + num_library) as u32;
    let p1 = make_player(
        1,
        num_battlefield,
        num_hand,
        num_library,
        id_offset,
        forest_pid,
        bears_pid,
        elves_pid,
    );
    GameState {
        players: [p0, p1],
        registry,
        active_player: 0,
        priority_player: 0,
        turn_number: 5,
        phase: 0,
        attackers: Vec::new(),
        blockers: Vec::new(),
        stack: Vec::new(),
        pending_decisions: Vec::new(),
    }
}
