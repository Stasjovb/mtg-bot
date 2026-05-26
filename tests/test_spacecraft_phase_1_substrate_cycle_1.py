"""Spacecraft Station substrate Phase 1 — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/spacecraft-phase-1-cycle-1-substrate-p1``
(2026-05-25).

Cycle 1 of the Spacecraft Station substrate Phase 1 campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md`` (1,230 lines,
2026-05-25, merge ``35be45bb``).

Phase 1 admits ONLY sub-shape A — Galvanizing Sawship (1 card / 5,938
17lands decks; the sole single-gated AND zero-ability Spacecraft in
the EoE pool). Every other Spacecraft (Lumen-Class Frigate /
Larval Scoutlander / Sledge-Class Seedship / Synthesizer Labship /
Entropic Battlecruiser / Infinite Guideline Station / The Eternity
Elevator) carries at least one co-gate that Phase 1 explicitly
defers to Phase 2 / 3 / 4.

The campaign cadence is calibrated against the cost-reduction +
Carrier-AA campaigns (1 substrate Part A + 1 substrate Part B + 1
bridge + 1 admit + 1 probe per scenario).

Substrate breakdown (sibling mirror of cost-reduction Phase 1's
multi-cycle landings):

* **Cycle 1 (this slice — Substrate Part A — fields + parse +
  predicate).** New ``CardPrinting.station_threshold:
  Option<i32>`` field; new ``CardPrinting.stationed_keywords:
  Vec<String>`` field; new ``parse_printing`` arms for both
  (back-compat default — absent keys parse to ``None`` /
  ``Vec::new()``; an explicit Python ``None`` for
  ``station_threshold`` also maps to Rust ``None``; non-positive
  thresholds hard-error per the §2 teeth); new ``is_stationed``
  Rust predicate (folds ``charge_counters`` vs ``station_threshold``,
  exposed to Python via the thin ``is_stationed_check``
  ``#[pyfunction]`` shim at ``rust/src/lib.rs``). Cycle 1 does NOT
  add the ``Action::ActivateStation`` action / resolver / legal-
  action emitter (Cycle 2 owns that). Cycle 1 does NOT add the
  Python bridge round-trip arms (Cycle 3 owns that). Cycle 1 does
  NOT widen the admit predicate (Cycle 3 owns that).
  **Galvanizing Sawship STAYS DECLINED at the admit gate post-
  Cycle-1** — the sibling guard
  ``if printing.station_threshold: return False`` in
  ``trajectory.py:4698`` remains in place.

* **Cycle 2 (after — Substrate Part B — action + resolver +
  emitter + folds).** New ``Action::ActivateStation`` action; new
  ``apply_activate_station`` resolver; new sorcery-speed legal-
  action emitter (``state_ops_legal.rs``); new ``is_creature_now``
  predicate extension that calls into ``is_stationed`` from Cycle
  1; new effective-keyword fold extension that merges
  ``stationed_keywords`` into the layer-6 read site. Admit set
  STILL unchanged post-Cycle-2 — Galvanizing Sawship remains
  DECLINED.

* **Cycle 3 (after — bridge round-trip + admit widen).** Python
  bridge emit + reverse arms for ``station_threshold`` /
  ``stationed_keywords`` keys; new
  ``_printing_is_bridge_pure_station_spacecraft`` admit predicate;
  registration in the deck-level OR-chain filter. **FLIPS
  Galvanizing Sawship DECLINED → ADMITTED**.

* **Cycle 4 (after — Galvanizing Sawship real-EoE probes:
  un-stationed Scenario A + partial-station Scenario B).** Per-
  card real-EoE cross-engine byte-equality probes; subsystem-
  attribution decline-set bench check.

* **Cycle 5 (after — Galvanizing Sawship real-EoE probe Scenario C
  + Tapestry-Warden no-silent-auto-grow pin).** The
  fully-stationed-and-haste-attacking trajectory; the no-grow
  pin against any future Tapestry-Warden-shape printing.

* **Cycle 6 (rolling).** SEARCH_LIMITATIONS.md entries +
  POOL_PARITY.md regen.

**What this module pins (substrate-only invariants).**

1. **Python-side parser SoT.** Galvanizing Sawship's Python
   ``CardPrinting`` carries ``station_threshold == 3`` and
   ``stationed_keywords == frozenset({"flying", "haste"})`` — the
   same payload ``test_parser_spacecraft_builder.py`` already
   pins, asserted directly here to guard against parser drift
   while the new Rust substrate lands.
2. **Rust parse round-trip — Galvanizing Sawship payload.** A
   synthetic Galvanizing-Sawship-shaped registry dict — an
   ``Artifact`` with ``card_types=["Artifact"]``,
   ``subtypes=["Spacecraft"]``, ``power=6``, ``toughness=5``,
   ``station_threshold=3``, ``stationed_keywords=["flying",
   "haste"]`` — registers on
   ``mtg_bot_engine.Registry.register_printing`` with no panic
   and no Err.
3. **Rust ``is_stationed`` predicate pin.** With
   ``station_threshold=3``, ``charge_counters`` ∈ {0, 1, 2}
   returns False; ``charge_counters`` ∈ {3, 4, 100} returns True.
   With ``station_threshold=None``, every ``charge_counters``
   value (including 0 and 100) returns False (non-Spacecraft AND
   non-animating Spacecraft path — both share the ``None``
   shape).
4. **Back-compat parse — absent keys.** A registry dict without
   either ``station_threshold`` or ``stationed_keywords`` parses
   unchanged (the absent-key → default arm — every pre-Phase-1
   registry dict omits both, matching the
   ``warp_cost`` / ``cost_reductions`` parse precedent).
5. **Back-compat parse — explicit None station_threshold.** A
   registry dict with ``station_threshold=None`` (the explicit-
   None Python shape the bridge emit may pass for non-Spacecraft
   printings) parses unchanged — maps to Rust ``Option::None``,
   sibling of the absent-key arm.
6. **§2 Rust-side teeth — non-positive station_threshold hard-
   errors.** ``station_threshold=0`` and ``station_threshold=-1``
   both fail registration with a ``ValueError`` whose message
   names the offending value — the
   ``silent no-op pipeline runs are pipeline bugs`` discipline
   applied to the new field. Likewise ``stationed_keywords`` with
   a non-list payload or a non-string element loudly rejects.
7. **Substrate-only invariant — Galvanizing Sawship STAYS
   DECLINED at the admit gate post-Cycle-1.** The sibling
   ``if printing.station_threshold: return False`` guard in
   ``trajectory.py:4698`` is load-bearing this cycle: admitting
   Galvanizing Sawship without the C2 bridge round-trip + C2
   action would ship a guaranteed game-state divergence (Python
   sees a Spacecraft with a Station action; Rust would have no
   way to ActivateStation). Cycle 3 inverts this pin when the
   bridge round-trip + new admit predicate land.
8. **Live admit set unchanged — no auto-grow.** The
   number of bridge-admitted EoE printings under
   ``_printing_is_bridge_simple_creature`` is identical post-
   Cycle-1 to pre-Cycle-1 (zero auto-grow) — the substrate-only
   invariant's bench-aggregate sibling.

The Cycle 2 / Cycle 3 / Cycle 4 deliverables call out the
inversion points so reviewers tracking the cadence know exactly
which pins flip when.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Python-side parser SoT (Galvanizing Sawship)
# ---------------------------------------------------------------------------


def test_parser_sot_galvanizing_sawship_carries_phase1_station_payload():
    """Pin #1 — Galvanizing Sawship Python-side parser SoT.

    Galvanizing Sawship's printed surface form parses to a Spacecraft
    ``Artifact`` with ``station_threshold == 3`` and
    ``stationed_keywords == frozenset({"flying", "haste"})``. Pre-
    existing on main; pinned here to guard against parser drift while
    the new Rust substrate lands.
    """
    from mtg_bot.cards.source import get_active_source

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    assert "Spacecraft" in sawship.subtypes
    assert "Artifact" in sawship.card_types
    assert sawship.power == 6
    assert sawship.toughness == 5
    assert sawship.station_threshold == 3
    assert sawship.stationed_keywords == frozenset({"flying", "haste"})
    # And NO other ability shapes — Phase 1's "zero-ability" axis.
    assert not sawship.static_abilities
    assert not sawship.triggered_abilities
    assert not sawship.activated_abilities
    assert sawship.spell_effect is None
    assert sawship.warp_cost is None
    assert sawship.cost_reductions == ()
    assert sawship.external_cost_reductions == ()
    # Baseline (un-stationed) keywords are empty — Phase 1 pilot only
    # gets flying+haste *after* stationing.
    assert sawship.keywords == frozenset()


# ---------------------------------------------------------------------------
# Pin 2 — Rust parse round-trip (Galvanizing Sawship synthetic dict)
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_galvanizing_sawship_station_payload():
    """Pin #2 — Rust ``parse_printing`` accepts the Galvanizing
    Sawship shape.

    A synthetic Sawship-shaped registry dict — an ``Artifact`` with
    ``subtypes=["Spacecraft"]``, ``power=6``, ``toughness=5``,
    ``station_threshold=3``, ``stationed_keywords=["flying", "haste"]``
    — registers on ``mtg_bot_engine.Registry.register_printing`` with
    no panic and no Err.

    Round-trip-shape parity discipline (sibling of every prior
    substrate-only C1 — cost-reduction Phase 1 Cycle 1 / Phase 2
    Cycle 1 / Phase 3 Cycle 1 / Coordinated Clobbering /
    Anticausal Vestige / Weftwalking).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Spacecraft Phase 1 Cycle 1 Substrate Pin -- "
            "Galvanizing-Sawship-shaped carrier"
        ),
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"R": 1, "generic": 5},
        "power": 6,
        "toughness": 5,
        "station_threshold": 3,
        "stationed_keywords": ["flying", "haste"],
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 3 — Rust is_stationed predicate (charge-counter axis sweep)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("threshold", "charge_counters", "expected"),
    [
        # Below-threshold un-stationed cases (threshold=3).
        (3, 0, False),
        (3, 1, False),
        (3, 2, False),
        # At / above-threshold stationed cases (threshold=3).
        (3, 3, True),
        (3, 4, True),
        (3, 100, True),
        # threshold=None — non-Spacecraft AND non-animating
        # Spacecraft (The Eternity Elevator — Phase 4 only) BOTH
        # use the same `None` shape. Every charge-counter value
        # returns False.
        (None, 0, False),
        (None, 3, False),
        (None, 100, False),
        # Other thresholds — defense-in-depth that the predicate is
        # the literal `>=` fold, not a hardcoded 3-compare.
        (1, 0, False),
        (1, 1, True),
        (12, 11, False),
        (12, 12, True),
        (12, 13, True),
    ],
)
def test_rust_is_stationed_predicate_pins_threshold_axis(
    threshold, charge_counters, expected,
):
    """Pin #3 — ``is_stationed`` predicate pin.

    The thin ``mtg_bot_engine.is_stationed_check`` shim folds the
    pure-Rust ``state_ops_combat::is_stationed_predicate``. Pinned
    here for the threshold-axis sweep ({None, 1, 3, 12}) × the
    charge-counter axis ({0, 1, 2, 3, 4, 11, 12, 13, 100}). The
    predicate is the substrate's fundamental gate — every Cycle-2+
    consumer (``is_creature_now``, the legal-action emitter, the
    effective-keyword fold) reads through it.
    """
    import mtg_bot_engine

    assert mtg_bot_engine.is_stationed_check(threshold, charge_counters) == expected


# ---------------------------------------------------------------------------
# Pin 4 — Back-compat: absent keys parse to None / empty Vec
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_absent_station_keys_back_compat():
    """Pin #4 — back-compat: a registry dict without the
    ``station_threshold`` or ``stationed_keywords`` keys parses
    unchanged (the absent-key → default arm — the same pattern every
    other optional field uses; mirrors the back-compat regression-
    tripwire across the substrate landings)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Spacecraft Phase 1 Cycle 1 Substrate Pin -- "
            "absent station keys (back-compat)"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 5 — Back-compat: explicit None station_threshold parses
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_explicit_none_station_threshold():
    """Pin #5 — back-compat: a registry dict with
    ``station_threshold=None`` (the explicit-None shape the Python
    bridge emit may pass for non-Spacecraft printings) parses
    unchanged — maps to Rust ``Option::None``, sibling of the
    absent-key arm.

    This is the symmetric pin to #4: BOTH absent-key and
    explicit-``None`` shapes parse cleanly, so a Cycle-3 bridge emit
    that uses either shape (the design doc §5.1 currently scopes
    ``if printing.station_threshold is not None`` — i.e., emits only
    when non-default — but the parser tolerates either) works."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Spacecraft Phase 1 Cycle 1 Substrate Pin -- "
            "explicit-None station_threshold"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
        "station_threshold": None,
        # Empty list also tolerated.
        "stationed_keywords": [],
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 6 — §2 Rust-side teeth (non-positive threshold / bad keywords)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload_extra", "expected_fragment"),
    [
        # Zero threshold — not allowed (a Spacecraft with threshold=0
        # would be "always stationed" which violates the Phase-1
        # semantics and matches no real EoE printing). Hard-error.
        ({"station_threshold": 0}, "positive"),
        # Negative threshold — also rejected.
        ({"station_threshold": -1}, "positive"),
        # stationed_keywords as a non-list — type error.
        (
            {
                "station_threshold": 3,
                "stationed_keywords": "flying,haste",
            },
            "list",
        ),
        # stationed_keywords with a non-string element.
        (
            {
                "station_threshold": 3,
                "stationed_keywords": ["flying", 42],
            },
            "string",
        ),
    ],
)
def test_rust_parser_rejects_invalid_station_payload(
    payload_extra, expected_fragment,
):
    """Pin #6 — §2 Rust-side teeth.

    Non-positive ``station_threshold``, non-list
    ``stationed_keywords``, or a non-string element all hard-error
    at ``register_printing`` time with a ``ValueError`` whose
    message names the offending shape. The ``silent no-op pipeline
    runs are pipeline bugs`` discipline applied to the new field.
    """
    import mtg_bot_engine

    base = {
        "name": (
            "Spacecraft Phase 1 Cycle 1 Substrate Pin -- "
            "negative-path teeth"
        ),
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"R": 1, "generic": 5},
        "power": 6,
        "toughness": 5,
    }
    base.update(payload_extra)
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError) as excinfo:
        reg.register_printing(base)
    assert expected_fragment in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Pin 7 — Substrate-only invariant (load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_now_admits_at_admit_gate_post_cycle_3():
    """Pin #7 — **INVERTED IN-PLACE BY CYCLE 3 (2026-05-25).**

    Original C1 pin (substrate-only invariant) asserted Galvanizing
    Sawship STAYS DECLINED post-Cycle-1+2. Cycle 3 landed the Python
    bridge round-trip + new admit predicate
    :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_station_
    spacecraft` + OR-chain disjunct registration — Sawship now
    ADMITS at the deck-level filter through the new dedicated
    disjunct. The load-bearing
    ``if printing.station_threshold: return False`` guard at
    :func:`_printing_is_bridge_simple_creature` STAYS — the new
    predicate is the routing site, not a widen of the simple-creature
    predicate. THE FLIP.

    Post-C3 admit-set count for Spacecraft = 1 (Galvanizing Sawship);
    5,938 17lands decks newly bridge-admitted.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    # The simple-creature predicate must STILL reject the Sawship —
    # the load-bearing ``station_threshold`` guard at
    # ``trajectory.py:4698`` is unchanged by C3. (Sawship is also
    # rejected by the ``"Creature" not in printing.card_types`` gate
    # — Sawship is an Artifact.) The C3 FLIP does NOT widen the
    # simple-creature predicate; it adds a sibling dedicated
    # predicate routed in parallel through
    # ``_filter_deck_to_bridge_supported``'s OR-chain.
    assert trajectory._printing_is_bridge_simple_creature(sawship) is False, (
        "Galvanizing Sawship must STILL be declined at the simple-"
        "creature admit gate post-C3 — the new dedicated disjunct "
        "is the routing site, not a widen of the simple-creature "
        "predicate. The load-bearing ``station_threshold`` guard "
        "stays in place."
    )
    # The new C3 predicate ADMITS the Sawship.
    assert trajectory._printing_is_bridge_pure_station_spacecraft(sawship), (
        "Galvanizing Sawship must ADMIT through the C3 dedicated "
        "Spacecraft admit predicate post-FLIP."
    )
    # And the deck-level filter NOW admits the Sawship — a 1-card
    # deck containing only Galvanizing Sawship filters to
    # (1-name, 1-CardDef-list).
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Galvanizing Sawship"], src,
    )
    assert filtered_names == ["Galvanizing Sawship"], (
        "THE FLIP — Galvanizing Sawship must ADMIT at the deck-level "
        f"filter post-C3. Got filtered_names={filtered_names!r}."
    )
    assert len(card_defs) == 1
    assert card_defs[0].name == "Galvanizing Sawship"
    assert card_defs[0].station_threshold == 3


# ---------------------------------------------------------------------------
# Pin 8 — Bench-aggregate sibling: live admit-set count unchanged
# ---------------------------------------------------------------------------


def test_admit_set_size_bumps_post_cycle_3():
    """Pin #8 — **INVERTED IN-PLACE BY CYCLE 3 (2026-05-25).**

    Original C1 pin asserted ZERO Spacecraft printings admit through
    any disjunct of the deck-level filter (the bench-aggregate
    sibling of pin #7 holding the substrate-only invariant). Cycle 3
    landed the FLIP — the bench-aggregate count for Spacecraft is
    now exactly 1 (Galvanizing Sawship). Any OTHER Spacecraft
    admitting is a silent auto-grow honest-stop.

    The simple-creature predicate STILL declines every Spacecraft
    (the load-bearing ``station_threshold`` guard at
    ``trajectory.py:4698`` is unchanged by C3); the new dedicated
    disjunct ``_printing_is_bridge_pure_station_spacecraft`` is the
    sole routing site for the Phase-1 admit.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    # Walk every printing; count Spacecraft that admit under EITHER
    # the simple-creature predicate (must be zero — unchanged by C3)
    # OR the new C3 dedicated predicate (must be 1 — Sawship).
    admitted_via_simple_creature = []
    admitted_via_station_predicate = []
    for name, printing in src.items():
        if "Spacecraft" not in printing.subtypes:
            continue
        if trajectory._printing_is_bridge_simple_creature(printing):
            admitted_via_simple_creature.append(name)
        if trajectory._printing_is_bridge_pure_station_spacecraft(printing):
            admitted_via_station_predicate.append(name)
    assert admitted_via_simple_creature == [], (
        "Post-C3 no Spacecraft printing should admit through the "
        "simple-creature predicate — C3 routes through the dedicated "
        f"disjunct, not via widening the simple-creature gate. Got: "
        f"{admitted_via_simple_creature!r}."
    )
    assert admitted_via_station_predicate == ["Galvanizing Sawship"], (
        "Post-C3 EXACTLY ONE Spacecraft printing admits through the "
        "new dedicated predicate — Galvanizing Sawship (admit-set "
        f"count +1 vs Cycle 1/2). Got: {admitted_via_station_predicate!r}."
    )
