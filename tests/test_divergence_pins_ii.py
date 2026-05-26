"""Divergence-pin tests: batch II (probe-batch-ii).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity. The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 — ``ExileAllGraveyards`` vs ``ExileEachOpponentsGraveyard`` semantic
mismatch (Scavenger Grounds vs Dauntless Scrapbot / bridge lane).

    Python's Scavenger Grounds parser (``land_builder.py:1148-1154``)
    constructs ``ExileAllGraveyards()`` for the "Exile all graveyards."
    oracle text.  ``ExileAllGraveyards.resolve``
    (``effects/generic/exile.py:667-680``) iterates over ALL
    ``state.players`` — including the controller — and moves every card in
    every player's graveyard to that player's exile.  The controller's
    own graveyard is exiled along with all opponents'.

    The bridge (``cross_engine.py:8059-8091``) maps the Rust kind
    ``exile_each_opponents_graveyard`` to Python's
    ``ExileEachOpponentsGraveyard()``
    (``effects/generic/exile.py:260-284``).
    ``ExileEachOpponentsGraveyard.resolve`` skips any player whose
    ``p.id == controller_id`` (line 271), so the CONTROLLER's graveyard
    is NOT exiled.

    The two Python classes are therefore semantically distinct:
      - ``ExileAllGraveyards`` — exiles controller's + opponents' GYs.
      - ``ExileEachOpponentsGraveyard`` — exiles opponents' GYs ONLY.

    This is a Python-only divergence (no Rust extension required): the
    same oracle intent ("exile graveyards") is implemented two different
    ways depending on which path produced the card.

    CR reference: CR 800.4g (a player's "opponents" are the other players
    in the game; the controller of an effect is not their own "opponent").
    Oracle text "Exile all graveyards." (Scavenger Grounds) should exile
    every player's graveyard including the controller's.  Oracle text
    "Exile each opponent's graveyard." (Dauntless Scrapbot) should skip
    the controller's.  The bug is that the Scavenger Grounds parser uses
    a class whose effect exactly matches the "exile ALL" oracle text, while
    the bridge lane maps to a class with "exile OPPONENTS' ONLY" semantics.
    The two paths produce different in-game results for the same controller.

    Verified observable divergence (controller_id=0, one card in each GY):
      * ``ExileAllGraveyards().resolve(state, controller_id=0)``:
          p0 exile = 1, p0 graveyard = 0 (controller's GY exiled).
      * ``ExileEachOpponentsGraveyard().resolve(state, controller_id=0)``:
          p0 exile = 0, p0 graveyard = 1 (controller's GY preserved).

Pin 2 — ``put_basic_land_from_hand_onto_battlefield_tapped`` bridge gap
(Terrain Generator).

    The cross-engine bridge function ``_ta_dict_to_python_effect`` at
    ``parity/cross_engine.py`` has no arm for the effect kind
    ``put_basic_land_from_hand_onto_battlefield_tapped``.  Calling
    ``_ta_dict_to_python_effect({"kind":
    "put_basic_land_from_hand_onto_battlefield_tapped"})`` raises
    ``ValueError: cross_engine triggered_abilities bridge: unsupported
    effect kind 'put_basic_land_from_hand_onto_battlefield_tapped' ...``.

    The Python effect class ``PutBasicLandFromHandOntoBattlefieldTapped``
    exists (``effects/generic/zone_moves.py:360``), is exported, and is
    used by Terrain Generator's activated ability (``land_builder.py:1635``).
    The missing bridge arm prevents any Rust-sourced card that emits this
    effect kind from being routed to Python's resolve implementation.

    Closure path: add an arm to ``_ta_dict_to_python_effect`` that imports
    and returns ``PutBasicLandFromHandOntoBattlefieldTapped()``.  When the
    bridge is fixed, the ``ValueError`` will no longer be raised, causing
    this sentinel assertion to fail — that is the signal to update this pin
    to a parity probe.

Pin 3 — ``SearchLibraryForCard`` with ``may_fail=True`` silent-decline in
Python vs Rust always-fetches-first-match (Sliver Overlord).

    Python's ``SearchLibraryForCard.resolve``
    (``effects/generic/search.py:98-110``) with ``may_fail=True`` and NO
    agent installed on the controller returns early at line 104-109 with a
    "P{N} declines to fetch" log entry, leaving the matching card in the
    library.  This is Python's simulation of the interactive "you MAY
    search" choice when no decision-making agent is present.

    Rust's ``Effect::SearchLibraryForCard`` resolve arm
    (``rust/src/state_ops_resolve.rs:9180-9312``) ignores the ``may_fail``
    field entirely (annotated ``may_fail: _`` at line 9183) — there is no
    interactive "decline" path in Rust.  Rust always locates the first
    matching card in the library (top-to-bottom scan) and moves it to the
    controller's hand unconditionally (line 9300-9310).

    Observable divergence: with a Sliver in p0's library, a Sliver
    Overlord-shaped activated ability resolving via Python (no agent) leaves
    the Sliver in the library (hand size unchanged), while the same ability
    resolved via the Rust engine moves the Sliver to p0's hand (library
    shrinks by 1, hand grows by 1).

    CR reference: CR 701.18a ("search your library" — the player may choose
    not to find a card even if one exists, when the text says "may"; Rust's
    current arm does not implement this choice).

    This pin requires the Rust PyO3 extension (mtg_bot_engine); it is
    automatically skipped when the extension is absent.

Dropped pins
------------

  * ``IS_CAST`` predicate-bridge ``subject_is_artifact`` (batch AA):
    Previously dropped by GG batch as too fragile (requires a real
    game trajectory; no stable single-observable). Not retried here.

  * ``MovePlusOneCounterBetweenPermanentsYouControl`` 2-target false
    positive (Nesting Grounds, batch EE): Both Python and Rust fizzle
    silently when no-agent + no self-counters, producing ``diffs=[]`` as
    a false-positive probe.  The false-positive is already documented in
    ``test_probe_activated_abilities_ee.py:76-84``.  A pin for it would
    document the same documented non-behavior.  Dropped.

  * Equip lane Rust ``_zone_signature`` ``attached_to=None`` (batch EE):
    The field-view discrepancy requires detailed Rust internal API calls
    that the current PyO3 extension does not expose directly via
    ``battlefield_snapshot()``; the pin surface is fragile.  Dropped.
"""

from __future__ import annotations

import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Rust-engine guard (Pin 3 requires PyO3 extension; skipped otherwise).
# ---------------------------------------------------------------------------

_RUST_ENGINE_AVAILABLE = importlib.util.find_spec("mtg_bot_engine") is not None

pytestmark_rust = pytest.mark.skipif(
    not _RUST_ENGINE_AVAILABLE,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_base_state():
    """Minimal two-player GameState for Python-only pins."""
    from mtg_bot.game import GameState, Player
    from mtg_bot.turn import Step

    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _make_sorcery_printing(name="Bait Sorcery"):
    """Return a minimal Sorcery CardPrinting."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Sorcery",
        supertypes=(),
        card_types=("Sorcery",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )


def _make_creature_printing(name="Sliver Bait", subtypes=("Sliver",)):
    """Return a minimal Creature CardPrinting with given subtypes."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line=f"Creature — {' '.join(subtypes)}" if subtypes else "Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=subtypes,
        power=1,
        toughness=1,
        produces=frozenset(),
    )


# ---------------------------------------------------------------------------
# Pin 1 — ExileAllGraveyards vs ExileEachOpponentsGraveyard semantic mismatch
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_exile_all_graveyards_vs_opponents_only_controller_gy_divergence_pin():
    """Pin the Python-internal semantic divergence between
    ``ExileAllGraveyards`` (Scavenger Grounds parser path) and
    ``ExileEachOpponentsGraveyard`` (cross-engine bridge path).

    Bug location:
      ``src/mtg_bot/cards/parser/land_builder.py:1148-1150`` —
      ``_exile_all_graveyards()`` returns ``ExileAllGraveyards()``.

      ``src/mtg_bot/parity/cross_engine.py:8059-8091`` — the bridge arm
      for ``exile_each_opponents_graveyard`` returns
      ``ExileEachOpponentsGraveyard()``.

    What's wrong:
      Both paths claim to model "exile graveyard(s)" but disagree on
      whether the CONTROLLER's graveyard is included.
      ``ExileAllGraveyards`` iterates ALL players (including controller);
      ``ExileEachOpponentsGraveyard`` skips any player whose
      ``p.id == controller_id``.  A card parsed by the land_builder
      (Scavenger Grounds) exiles the controller's GY too; a card arriving
      through the bridge lane (Dauntless Scrapbot style) does not.

    What's right:
      Determined by oracle text.  "Exile all graveyards." (Scavenger
      Grounds) correctly uses ``ExileAllGraveyards`` — the controller's
      GY should be exiled.  "Exile each opponent's graveyard." (Dauntless
      Scrapbot) correctly uses ``ExileEachOpponentsGraveyard`` — the
      controller's GY should be preserved.  The divergence is not a bug
      in either class in isolation; it is a surface where two distinct
      oracle shapes share a confusingly-similar name, and cross-engine
      probes that conflate them produce misleading results.

    CR reference: CR 800.4g — "opponent" means another player in the
    game, not oneself.

    Verified observable divergence (controller_id=0; one card in each GY):
      * ``ExileAllGraveyards().resolve(state, controller_id=0)``:
          p0 exile = 1 (controller's own GY card exiled),
          p0 graveyard = 0.
      * ``ExileEachOpponentsGraveyard().resolve(state, controller_id=0)``:
          p0 exile = 0 (controller's GY card preserved),
          p0 graveyard = 1.

    Probe shape:
      1. Build two separate minimal GameState instances, each with one
         card in p0's graveyard and one card in p1's graveyard.
      2. State A: resolve ``ExileAllGraveyards()`` with controller_id=0.
         Assert p0's GY is empty (p0's card was exiled).
      3. State B: resolve ``ExileEachOpponentsGraveyard()`` with
         controller_id=0.
         Assert p0's GY still contains the card (controller is skipped).
      4. Assert the two paths produce different p0 exile counts.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.generic.exile import (
        ExileAllGraveyards,
        ExileEachOpponentsGraveyard,
    )
    from mtg_bot.game import Zone

    sorcery_printing = _make_sorcery_printing("Graveyard Bait")

    def _make_state_with_gy_cards():
        """Return a state with one card in each player's graveyard."""
        state = _new_base_state()
        p0_card = state.new_object(sorcery_printing, owner_id=0, zone=Zone.GRAVEYARD)
        p1_card = state.new_object(sorcery_printing, owner_id=1, zone=Zone.GRAVEYARD)
        state.players[0].graveyard.append(p0_card)
        state.players[1].graveyard.append(p1_card)
        return state

    # ------------------------------------------------------------------
    # Path A: ExileAllGraveyards — all players' GYs exiled (including
    # controller p0).
    # ------------------------------------------------------------------
    state_a = _make_state_with_gy_cards()

    p0_gy_before_a = len(state_a.players[0].graveyard)
    p1_gy_before_a = len(state_a.players[1].graveyard)
    assert p0_gy_before_a == 1, "State A: p0 GY should have 1 card before resolve"
    assert p1_gy_before_a == 1, "State A: p1 GY should have 1 card before resolve"

    ExileAllGraveyards().resolve(state_a, controller_id=0)

    p0_gy_after_a = len(state_a.players[0].graveyard)
    p0_exile_after_a = len(state_a.players[0].exile)

    # ExileAllGraveyards exiles EVERYONE including controller.
    assert p0_gy_after_a == 0, (
        "Path A (ExileAllGraveyards): p0's graveyard should be empty — "
        "ExileAllGraveyards iterates all players including the controller. "
        f"Got graveyard size={p0_gy_after_a}"
    )
    assert p0_exile_after_a == 1, (
        "Path A (ExileAllGraveyards): p0's exile should contain the "
        "controller's own GY card. "
        f"Got exile size={p0_exile_after_a}"
    )

    # ------------------------------------------------------------------
    # Path B: ExileEachOpponentsGraveyard — controller's GY preserved.
    # ------------------------------------------------------------------
    state_b = _make_state_with_gy_cards()

    p0_gy_before_b = len(state_b.players[0].graveyard)
    assert p0_gy_before_b == 1, "State B: p0 GY should have 1 card before resolve"

    ExileEachOpponentsGraveyard().resolve(state_b, controller_id=0)

    p0_gy_after_b = len(state_b.players[0].graveyard)
    p0_exile_after_b = len(state_b.players[0].exile)

    # ExileEachOpponentsGraveyard skips the controller; p0's GY is preserved.
    assert p0_gy_after_b == 1, (
        "Path B (ExileEachOpponentsGraveyard): p0's graveyard should still "
        "contain the controller's card — ExileEachOpponentsGraveyard skips "
        "any player whose id == controller_id (exile.py:271). "
        f"Got graveyard size={p0_gy_after_b}"
    )
    assert p0_exile_after_b == 0, (
        "Path B (ExileEachOpponentsGraveyard): p0's exile should be empty — "
        "the controller's card was not exiled. "
        f"Got exile size={p0_exile_after_b}"
    )

    # ------------------------------------------------------------------
    # Cross-path divergence: the two effects MUST differ on p0's exile.
    # ------------------------------------------------------------------
    assert p0_exile_after_a != p0_exile_after_b, (
        "Cross-path divergence: ExileAllGraveyards (p0 exile=1) must NOT "
        "equal ExileEachOpponentsGraveyard (p0 exile=0) until one of the "
        "classes is renamed, refactored, or the bridge arm is corrected to "
        "route 'exile_all_graveyards' dict kind to ExileAllGraveyards. "
        f"ExileAllGraveyards p0_exile={p0_exile_after_a}, "
        f"ExileEachOpponentsGraveyard p0_exile={p0_exile_after_b}"
    )


# ---------------------------------------------------------------------------
# Pin 2 — put_basic_land_from_hand_onto_battlefield_tapped bridge gap
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_terrain_generator_put_basic_land_bridge_gap_closed():
    """**INVERTED — Carrier-AA substrate Phase 2b (2026-05-25).** The
    bridge gap for effect kind
    ``put_basic_land_from_hand_onto_battlefield_tapped`` (Terrain
    Generator activated ability) is CLOSED. The Phase 2b cycle landed
    the Rust ``Effect::PutBasicLandFromHandOntoBattlefieldTapped``
    variant + parse / resolve / to_pydict arms + cross-engine bridge
    arms + Python admit-gate widen in lockstep per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §4.2/§5.2/§6.4 #15.

    Closure observable:
      * ``_ta_dict_to_python_effect({"kind": "put_basic_land_from_hand_
        onto_battlefield_tapped"})`` now returns a fresh
        ``PutBasicLandFromHandOntoBattlefieldTapped()`` instance (no
        ValueError).
      * The Python effect class is unchanged — still an ``Effect``
        subclass at ``effects/generic/zone_moves.py:360``.

    Promotion target — the dedicated per-card real-EoE byte-equal
    probe at ``tests/test_terrain_generator_parity.py`` (Phase 2b
    deliverable §6.4 #15). This pin remains as a closure marker — if
    a future refactor removes the bridge arm or breaks the class, this
    pin fires.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.zone_moves import PutBasicLandFromHandOntoBattlefieldTapped
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # The Python class exists and is a valid Effect subclass.
    assert issubclass(PutBasicLandFromHandOntoBattlefieldTapped, Effect), (
        "PutBasicLandFromHandOntoBattlefieldTapped should be an Effect "
        "subclass; if this fails the class itself was removed or "
        "rebased."
    )

    effect_dict = {"kind": "put_basic_land_from_hand_onto_battlefield_tapped"}

    # The bridge now ROUND-TRIPS the kind — Phase 2b closure.
    bridged = _ta_dict_to_python_effect(effect_dict)
    assert isinstance(bridged, PutBasicLandFromHandOntoBattlefieldTapped), (
        "Bridge gap closed: ``_ta_dict_to_python_effect`` must return "
        "a fresh ``PutBasicLandFromHandOntoBattlefieldTapped`` instance "
        "for the ``put_basic_land_from_hand_onto_battlefield_tapped`` "
        "kind post-Phase-2b. If this fails the bridge arm was reverted "
        "or never landed."
    )

    # Sanity: the class is instantiable and resolves without TypeError.
    effect_instance = PutBasicLandFromHandOntoBattlefieldTapped()
    assert effect_instance is not None, (
        "PutBasicLandFromHandOntoBattlefieldTapped() should be "
        "instantiable; if this fails the class itself is broken."
    )


# ---------------------------------------------------------------------------
# Pin 3 — SearchLibraryForCard may_fail=True: Python declines, Rust always fetches
# ---------------------------------------------------------------------------


@pytestmark_rust
def test_cross_engine_real_eoe_sliver_overlord_search_library_may_fail_silent_decline_vs_rust_fetch_divergence_pin():
    """Pin the Rust-vs-Python divergence for ``SearchLibraryForCard`` with
    ``may_fail=True`` when no agent is installed.

    Bug location:
      Python: ``src/mtg_bot/effects/generic/search.py:98-109`` —
        ``SearchLibraryForCard.resolve`` checks ``if chosen_id is None:``
        (line 103) after ``p.agent is None`` produces ``chosen_id = None``
        (lines 99-102).  With ``self.may_fail is True`` the early-return
        path (lines 104-109) fires: the library is shuffled and the
        function returns without moving any card to hand.
        Log message: "P{N} declines to fetch".

      Rust: ``rust/src/state_ops_resolve.rs:9183`` —
        ``may_fail: _`` — the field is IGNORED at the pattern-match
        level; there is no "decline to fetch" branch.  The resolve arm
        always scans the library top-to-bottom for the first matching card
        (lines 9217-9295) and unconditionally moves it to hand
        (lines 9299-9310).  Comment at 9167-9168: "(G19), may_fail
        interactive choice (no decision callback yet for 'decline fetch')."

    What's right:
      CR 701.18a: "To search, a player looks at all cards in the
      specified zone and may choose one."  When a spell or ability says
      "you may search", the player is allowed to decline.  Python's
      silent-decline path correctly models the no-agent "decline" case
      (the agent would supply a ``choose_card_from_library`` choice if
      fetching were desired).  Rust's mandatory-fetch behavior deviates
      from CR 701.18a when ``may_fail=True``.

    CR reference: CR 701.18a ("may choose one"), CR 101.2 (if a player
    has a choice, that player makes it; "may" = optional).

    Verified observable divergence:
      Setup: one Test Sliver in p0's library; no agent on p0; a
      Sliver-Overlord-shaped Sliver (SearchLibraryForCard filter_name=
      "sliver", may_fail=True) on p0's battlefield whose body is pushed
      to the stack and resolved.

      * Python (no agent, may_fail=True):
          p0 library size stays at 1 (Sliver not fetched; declined).
          p0 hand size stays at 0.
          log contains "P0 declines to fetch".
      * Rust (may_fail ignored):
          p0 library size drops to 0 (Sliver fetched unconditionally).
          p0 hand size rises to 1.

    Probe shape:
      1. Build separate Python and Rust states; add a Test Sliver to
         p0's library on each side.
      2. Python side: register p0 with no agent (default); push a
         SearchLibraryForCard(filter_name="sliver", may_fail=True)
         StackItem; resolve it.
      3. Rust side: register a Sliver Overlord-shaped creature on p0's
         battlefield whose effect dict is
         ``{"kind": "search_library_for_card", "filter_name": "sliver",
            "max_mv": 0, "may_fail": True}``; push it to the stack;
         call resolve_top_of_stack().
      4. Assert Python p0 library size == 1 (no change; declined).
      5. Assert Rust p0 library snapshot size == 0 (Sliver fetched).
      6. Assert the two engines disagree on library size.

    This pin requires the Rust PyO3 extension (mtg_bot_engine).
    """
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state, build_rust_state

    ZONE_LIBRARY = 1
    ZONE_BATTLEFIELD = 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())

    # ---- Python side ----
    py_state = build_python_state(spec)

    # Ensure p0 has no agent — Python will use the may_fail=True decline path.
    assert py_state.players[0].agent is None, (
        "Python: p0 must have no agent for the may_fail=True silent-decline "
        "path to be exercised."
    )

    sliver_printing = _make_creature_printing("Test Sliver", subtypes=("Sliver",))
    py_sliver = py_state.new_object(sliver_printing, owner_id=0, zone=Zone.LIBRARY)
    py_state.players[0].library.append(py_sliver)

    py_lib_before = len(py_state.players[0].library)
    py_hand_before = len(py_state.players[0].hand)
    assert py_lib_before == 1, "Python: p0 library should have 1 card before resolve"
    assert py_hand_before == 0, "Python: p0 hand should be empty before resolve"

    # Push a fake StackItem for the search effect (direct resolve path —
    # same pattern as the DD/GG pins for Python-side effect resolution).
    search_effect = SearchLibraryForCard(filter_name="sliver", max_mv=0, may_fail=True)
    search_effect.resolve(py_state, controller_id=0)

    py_lib_after = len(py_state.players[0].library)
    py_hand_after = len(py_state.players[0].hand)

    # ---- Rust side ----
    rust_state = build_rust_state(spec)

    # Put a Sliver in p0's library.
    rust_sliver_id = rust_state.register_and_inject_object(
        {
            "name": "Test Sliver",
            "card_types": ["Creature"],
            "subtypes": ["Sliver"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "power": 1,
            "toughness": 1,
        },
        0,            # owner = p0
        ZONE_LIBRARY,
    )

    # Register a Sliver Overlord-shaped permanent on p0's battlefield whose
    # activated-ability effect is search_library_for_card with may_fail=True.
    rust_spell_id = rust_state.register_and_inject_object(
        {
            "name": "Sliver Overlord",
            "card_types": ["Creature"],
            "subtypes": ["Sliver"],
            "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
            "effects": [
                {
                    "kind": "search_library_for_card",
                    "filter_name": "sliver",
                    "max_mv": 0,
                    "may_fail": True,
                }
            ],
        },
        0,            # controller = p0
        ZONE_BATTLEFIELD,
    )

    rust_lib_before = rust_state.library_snapshot(0)
    rust_hand_before = rust_state.hand_snapshot(0)
    assert len(rust_lib_before) == 1, (
        "Rust: p0 library should have 1 card before resolve"
    )
    assert len(rust_hand_before) == 0, (
        "Rust: p0 hand should be empty before resolve"
    )

    # Push the Sliver Overlord body to the stack and resolve.
    rust_state.push_to_stack(rust_spell_id, 0)
    assert rust_state.stack_size() == 1, (
        f"Rust: stack should have 1 item; got {rust_state.stack_size()}"
    )
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty after resolve; got {rust_state.stack_size()}"
    )

    rust_lib_after = rust_state.library_snapshot(0)
    rust_hand_after = rust_state.hand_snapshot(0)

    # ---- Per-engine divergence assertions ----

    # Python: no agent + may_fail=True → silent decline → library unchanged.
    assert py_lib_after == py_lib_before, (
        "Python: SearchLibraryForCard with may_fail=True and no agent should "
        "leave the library unchanged (silent decline path at search.py:104-109). "
        f"before={py_lib_before} after={py_lib_after}"
    )
    assert py_hand_after == py_hand_before, (
        "Python: SearchLibraryForCard with may_fail=True and no agent should "
        "leave the hand unchanged (no card fetched). "
        f"before={py_hand_before} after={py_hand_after}"
    )

    # Rust: may_fail ignored → always fetches first match → Sliver moves to hand.
    assert len(rust_lib_after) == 0, (
        "Rust: SearchLibraryForCard resolve arm ignores may_fail (annotated "
        "'may_fail: _' at state_ops_resolve.rs:9183) and always fetches the "
        "first matching card.  p0 library should be empty after resolve. "
        "Pinned divergent behavior — will flip to FAIL when Rust implements "
        "the may_fail=True / no-decision-callback path (G19 deferral). "
        f"Got library size={len(rust_lib_after)}"
    )
    assert len(rust_hand_after) == 1, (
        "Rust: SearchLibraryForCard should have moved the Test Sliver to p0's "
        "hand (unconditional fetch). "
        f"Got hand size={len(rust_hand_after)}"
    )

    # Cross-engine non-parity: library sizes MUST differ.
    assert py_lib_after != len(rust_lib_after), (
        "Cross-engine non-parity: Python library size (unchanged, "
        f"{py_lib_after}) should NOT equal Rust library size "
        f"({len(rust_lib_after)}) until Rust implements the may_fail=True "
        "interactive-decline path (G19 deferral note at "
        "state_ops_resolve.rs:9167-9168). "
        f"Python lib={py_lib_after}, Rust lib={len(rust_lib_after)}"
    )
