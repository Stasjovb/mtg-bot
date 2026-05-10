use pyo3::prelude::*;
use std::time::Instant;

#[derive(Clone, Debug)]
pub struct GameObject {
    pub id: u32,
    pub name: String,
    pub power: i16,
    pub toughness: i16,
    pub damage: i16,
    pub controller: u8,
    pub zone: u8,
    pub tapped: bool,
    pub summoning_sick: bool,
}

#[derive(Clone, Debug)]
pub struct Player {
    pub id: u8,
    pub life: i32,
    pub hand: Vec<GameObject>,
    pub library: Vec<GameObject>,
    pub battlefield: Vec<GameObject>,
    pub graveyard: Vec<GameObject>,
}

#[derive(Clone, Debug)]
#[pyclass(name = "GameState")]
pub struct GameState {
    pub players: [Player; 2],
    pub active_player: u8,
    pub priority_player: u8,
    pub turn_number: u32,
    pub phase: u8,
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
}

fn make_creature(id: u32, controller: u8, name: &str, power: i16, toughness: i16) -> GameObject {
    GameObject {
        id,
        name: name.to_string(),
        power,
        toughness,
        damage: 0,
        controller,
        zone: 1,
        tapped: false,
        summoning_sick: false,
    }
}

fn make_land(id: u32, controller: u8, name: &str) -> GameObject {
    GameObject {
        id,
        name: name.to_string(),
        power: 0,
        toughness: 0,
        damage: 0,
        controller,
        zone: 1,
        tapped: false,
        summoning_sick: false,
    }
}

fn make_player(id: u8, num_battlefield: usize, num_hand: usize, num_library: usize, base_id: u32) -> Player {
    let mut next = base_id;
    let mut battlefield = Vec::with_capacity(num_battlefield);
    let half = num_battlefield / 2;
    for _ in 0..half {
        battlefield.push(make_land(next, id, "Forest"));
        next += 1;
    }
    for _ in half..num_battlefield {
        battlefield.push(make_creature(next, id, "Grizzly Bears", 2, 2));
        next += 1;
    }
    let mut hand = Vec::with_capacity(num_hand);
    for _ in 0..num_hand {
        hand.push(make_creature(next, id, "Llanowar Elves", 1, 1));
        next += 1;
    }
    let mut library = Vec::with_capacity(num_library);
    for _ in 0..num_library {
        library.push(make_land(next, id, "Forest"));
        next += 1;
    }
    Player {
        id,
        life: 20,
        hand,
        library,
        battlefield,
        graveyard: Vec::new(),
    }
}

#[pyfunction]
#[pyo3(signature = (num_battlefield = 10, num_hand = 7, num_library = 50))]
fn make_synthetic_state(
    num_battlefield: usize,
    num_hand: usize,
    num_library: usize,
) -> GameState {
    let p0 = make_player(0, num_battlefield, num_hand, num_library, 0);
    let id_offset = (num_battlefield + num_hand + num_library) as u32;
    let p1 = make_player(1, num_battlefield, num_hand, num_library, id_offset);
    GameState {
        players: [p0, p1],
        active_player: 0,
        priority_player: 0,
        turn_number: 5,
        phase: 0,
    }
}

#[pymodule]
fn mtg_bot_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<GameState>()?;
    m.add_function(wrap_pyfunction!(make_synthetic_state, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
