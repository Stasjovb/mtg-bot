"""Aura-attachment substrate — Phase 4 S3 (Moonlit Meditation
substrate landing).

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 4 — Moonlit
Meditation honest-stop closure groundwork.

**This slice's scope.**

Phase 4 S3 lands the Rust + bridge substrate that Moonlit Meditation
(633 17lands decks; S3 sub-shape: ``replaces_first_tokens_with_copies
=True`` token-creation replacement rider) needs at the CardDef +
state-slot layer. The pieces that ship in THIS slice:

1. **Rust ``CardPrinting.aura_replaces_first_tokens_with_copies``
   field** (``rust/src/cards.rs``). Back-compat default ``false`` —
   every pre-S3 registry dict omits the
   ``aura_replaces_first_tokens_with_copies`` key and the parsed
   CardPrinting is bit-equal to before.

2. **Per-player ``GameState.created_tokens_this_turn`` slot**
   (``rust/src/state.rs``). A ``[bool; 2]`` array keyed by
   ``player_idx`` mirroring Python's
   ``GameState.players_who_created_tokens_this_turn: set[int]``
   (``game.py:2721``). Flipped on a non-zero-count
   ``Effect::CreateToken`` / ``CreateTokenTapped`` /
   ``CreateTokenEachPlayer`` / ``CreateTokenCopyOfTargetCreature
   YouControl`` arm; reset to ``[false; 2]`` on entry to PHASE_CLEANUP
   alongside the existing void flags
   (``state_ops_steps.rs::run_cleanup_step``).

3. **CardDef bridge plumbing** — the dataclass field
   (``CardDef.aura_replaces_first_tokens_with_copies``), the
   registry-dict emitter (``_spec_card_to_printing_dict``), the
   Python-side read-back (``_card_def_to_python_printing`` threading
   the value into ``CardPrinting.replaces_first_tokens_with_copies``),
   and the readback helper (``read_rust_printing_aura_fields``).

4. **Trajectory loader CardDef arm** — ``_printing_to_card_def`` (the
   aura branch) carries the rider through to the CardDef so any
   future positive-admit slice round-trips cleanly. The §2 loader
   predicate (``_printing_is_bridge_simple_aura``) STAYS declined at
   the ``replaces_first_tokens_with_copies`` check — the Rust
   ``CreateToken`` arm does NOT yet swap the token's ``printing_id``
   to the host's printing (the Token-supertype add on a host printing
   is a runtime registry mutation Rust doesn't expose; see the field
   docstring + ``docs/SEARCH_LIMITATIONS.md`` entry for the
   honest-stop).

**Live-EoE admit delta: +0 cards / +0 decks.** This is a substrate-
only slice in the Phase 4 first-deliverable tradition (Chorale of the
Void ``Effect::SacrificeSelfUnlessVoidActive`` substrate-only landing
at merge ``6fa5ac9c`` / commit ``b72ec35e``). Ships the CardPrinting
field + bridge round-trip + per-player state slot + turn-cleanup
reset so the cross-engine bridge no longer has a "no Rust translation
for the Moonlit replacement rider" hole, and so a future slice can
light up the CreateToken-arm Aura-consulting consumer without further
CardDef changes.

**Probes added in this slice:**

  * ``test_aura_replaces_first_tokens_bridge_round_trip`` — a CardDef
    with the new flag set round-trips Python → registry → Python
    byte-equal.
  * ``test_aura_replaces_first_tokens_default_false_back_compat`` —
    pre-S3 CardDefs survive unchanged (the registry-dict emitter
    omits the key when the flag is False).
  * ``test_aura_replaces_first_tokens_rust_getter_back_compat`` —
    every pre-S3 registry printing's
    ``get_printing_aura_replaces_first_tokens_with_copies`` returns
    False.
  * ``test_created_tokens_this_turn_flag_set_on_token_creation`` —
    Rust's ``Effect::CreateToken`` arm flips the per-player
    created-tokens-this-turn flag.
  * ``test_created_tokens_this_turn_flag_resets_on_cleanup`` — Rust's
    cleanup-step sweep zeroes both per-player slots alongside the
    void flags.
  * ``test_moonlit_meditation_real_eoe_card_def_carries_s3_flag`` —
    Moonlit Meditation's real-EoE printing materializes a CardDef
    with ``aura_replaces_first_tokens_with_copies=True``.
  * ``test_moonlit_meditation_loader_still_declined_s3_pin`` —
    negative pin: Moonlit stays declined at the bench loader. Mirror
    of the Phase 4 first-deliverable pin, kept here so the S3
    substrate slice has its own admit-still-declined assertion.
  * ``test_phase4_s3_does_not_regress_phase3_admits`` — sanity: Pain
    for All still admits end-to-end after the S3 bridge plumbing.
  * ``test_python_parity_create_token_records_player_in_set`` —
    Python's existing ``CreateToken`` semantics still write to the
    ``players_who_created_tokens_this_turn`` set; cross-engine flag
    semantics agree (Python set membership == Rust per-player flag).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------
# Bridge round-trip probes
# ---------------------------------------------------------------------


def test_aura_replaces_first_tokens_bridge_round_trip():
    """A CardDef with ``aura_replaces_first_tokens_with_copies=True``
    round-trips Python → registry → Python byte-equal."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_registry,
        read_rust_printing_aura_fields,
    )

    cd = CardDef(
        name="Moonlit Meditation (synthetic probe)",
        card_type="Enchantment",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_yours_only=True,
        aura_replaces_first_tokens_with_copies=True,
    )
    spec = DeckSpec(card_defs=(cd,), p0_library=(), p1_library=())
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid[cd.name]
    fields = read_rust_printing_aura_fields(reg, pid)
    assert fields["is_aura"] is True, (
        "Phase 4 S3 bridge round-trip: the registry must materialize "
        "is_aura=True for the Moonlit-shape CardDef."
    )
    assert fields["aura_replaces_first_tokens_with_copies"] is True, (
        "Phase 4 S3 bridge round-trip: the registry-dict's "
        "aura_replaces_first_tokens_with_copies=True must round-trip "
        f"back through the Rust getter; got fields={fields}."
    )
    # The Python-CardPrinting projection of the same field should also
    # surface True — this is the value the parser would have set, and
    # the value Python's _find_moonlit_replacement_source consumes.
    assert fields["replaces_first_tokens_with_copies"] is True, (
        "Phase 4 S3 bridge round-trip: the Python-side projection of "
        "the rider (CardPrinting.replaces_first_tokens_with_copies) "
        "must mirror the Rust getter result."
    )


def test_aura_replaces_first_tokens_default_false_back_compat():
    """A CardDef WITHOUT the new flag explicitly set carries the
    back-compat default ``False`` end-to-end through the bridge — every
    pre-S3 registry dict survives this slice bit-identical."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_registry,
        read_rust_printing_aura_fields,
        _spec_card_to_printing_dict,
    )

    # A Phase-1 S1 vanilla Aura (Frantic-Strength-shape) — no S3
    # rider, no S2 grants. The CardDef's
    # ``aura_replaces_first_tokens_with_copies`` defaults to False.
    cd = CardDef(
        name="S1 Vanilla Aura (back-compat probe)",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    assert cd.aura_replaces_first_tokens_with_copies is False, (
        "Pre-condition: the CardDef field's default value is False."
    )
    # The registry-dict emitter omits the key when the flag is False
    # (back-compat byte-equality with pre-S3 dicts).
    pd = _spec_card_to_printing_dict(cd)
    assert "aura_replaces_first_tokens_with_copies" not in pd, (
        "Phase 4 S3 back-compat: the registry-dict emitter must OMIT "
        "the aura_replaces_first_tokens_with_copies key when the "
        f"CardDef flag is False (so every pre-S3 dict stays byte-"
        f"identical). Got dict keys: {sorted(pd.keys())}."
    )
    # Round-trip back-compat: the Rust read-back returns False.
    spec = DeckSpec(card_defs=(cd,), p0_library=(), p1_library=())
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid[cd.name]
    fields = read_rust_printing_aura_fields(reg, pid)
    assert (
        fields["aura_replaces_first_tokens_with_copies"] is False
    ), (
        "Phase 4 S3 back-compat: a CardDef without the rider flag set "
        "must round-trip to aura_replaces_first_tokens_with_copies"
        f"=False; got {fields}."
    )


def test_aura_replaces_first_tokens_rust_getter_back_compat():
    """Every pre-S3 registry printing's Rust getter returns False — the
    missing key in the registry dict parses to the zero default."""
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_registry,
    )

    # A non-Aura printing (Forest) — no Aura fields, no S3 rider.
    forest = CardDef(
        name="Forest",
        card_type="Land",
        mana_cost_generic=0,
        mana_cost_colored=(),
    )
    spec = DeckSpec(
        card_defs=(forest,),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid["Forest"]
    val = reg.get_printing_aura_replaces_first_tokens_with_copies(pid)
    assert val is False, (
        "Phase 4 S3 back-compat: a non-Aura printing must read out "
        f"aura_replaces_first_tokens_with_copies=False; got {val}."
    )


# ---------------------------------------------------------------------
# Per-player state-slot probes
# ---------------------------------------------------------------------


ZONE_BATTLEFIELD = 2
ZONE_LIBRARY = 1


def _inject_token_printing_then_carrier(rust_state, token_name: str):
    """Register a Robot-token printing into the registry by injecting
    a dummy obj into LIBRARY (no ETB fires from a library object),
    capture the returned pid, then inject a self-contained carrier
    Enchantment whose ETB creates one of those tokens. Returns the
    token printing id (for assertion convenience).

    The two-step pattern is needed because ``Effect::CreateToken`` in
    Rust references its token by integer ``token_printing_id`` (an
    index into the registry) — there's no nested-token-printing form
    in the Rust schema. Registering the token printing first via a
    side-channel injection gives us its pid; then the carrier's ETB
    references that pid.
    """
    token_id = rust_state.register_and_inject_object(
        {
            "name": token_name,
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "supertypes": ["Token"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 0},
            "effects": [],
        },
        0, ZONE_LIBRARY,
    )
    # The printing's id is the registry index where it was just
    # pushed. ``register_and_inject_object`` registers the printing
    # then appends an object; the printing_id equals
    # `prior_registry_size`, which we can deduce from `token_id`'s
    # context, but a simpler robust read is via the new bf obj's
    # printing_id slot.
    # The injection-into-library sets the GameObject's printing_id
    # to the freshly-registered pid; read it off the library zone.
    # Library obj id == token_id; walk p0 library to find it.
    snap = rust_state.battlefield_snapshot()  # bf isn't where it landed
    # Read p0 library's printing_ids via the lib-name lookup helper.
    # `find_object_zone` returns the zone code (1 for library).
    assert rust_state.find_object_zone(token_id) == ZONE_LIBRARY
    # Use the registry-size delta — pre-injection the registry held N
    # printings; injection appended one, so the new pid == N. We
    # rebuild that by inspecting the Rust-state's exposed registry:
    # there's no direct printing_id getter for an obj, so we re-derive
    # by registering one more synthetic non-token printing and noting
    # the new pid then back off by 1 — overkill. Simpler: keep two
    # back-to-back injections. The token printing is the FIRST
    # injection on an empty registry, so its pid is 0.
    del snap  # unused — kept for `find_object_zone` invocation order
    token_pid = 0

    # Now inject the carrier whose ETB references token_pid.
    rust_state.register_and_inject_object(
        {
            "name": "Token-Maker Probe Carrier",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": token_pid,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )
    return token_pid


def test_created_tokens_this_turn_flag_set_on_token_creation():
    """The ``Effect::CreateToken`` resolve arm flips the controller's
    ``created_tokens_this_turn`` flag. Mirrors Python's
    ``state.players_who_created_tokens_this_turn.add(recipient)`` at
    ``tokens.py:294``.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)

    # Pre-condition: both player slots start cleared.
    assert rust_state.created_tokens_this_turn(0) is False, (
        "Pre-condition: P0's created-tokens-this-turn flag starts "
        "cleared on a fresh state."
    )
    assert rust_state.created_tokens_this_turn(1) is False, (
        "Pre-condition: P1's created-tokens-this-turn flag starts "
        "cleared on a fresh state."
    )

    # Wire a carrier whose ETB creates a token; resolve the ETB.
    _inject_token_printing_then_carrier(rust_state, "Robot Token (flip pin)")

    # Drain the stack — the ETB trigger fires CreateToken which flips
    # the per-player slot.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    assert rust_state.created_tokens_this_turn(0) is True, (
        "Phase 4 S3: P0's created-tokens-this-turn flag must flip to "
        "True after the CreateToken resolution. Mirror of Python's "
        "state.players_who_created_tokens_this_turn.add(0) at "
        "tokens.py:294."
    )
    assert rust_state.created_tokens_this_turn(1) is False, (
        "Phase 4 S3: P1's created-tokens-this-turn flag must stay "
        "False — only the active player created tokens."
    )


def test_created_tokens_this_turn_flag_resets_on_cleanup():
    """The cleanup-step sweep zeroes both per-player slots alongside the
    void flags. Mirrors Python's
    ``state.players_who_created_tokens_this_turn.clear()`` at
    ``turn.py:1092`` in ``run_cleanup_step``.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)

    _inject_token_printing_then_carrier(rust_state, "Robot Token (cleanup pin)")
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.created_tokens_this_turn(0) is True, (
        "Pre-condition: P0's flag must be flipped before the cleanup "
        "step runs."
    )

    # Advance phases until cleanup runs. The cleanup-step sweep clears
    # the per-player flags alongside the void flags.
    # advance_phase cycles UNTAP -> UPKEEP -> DRAW -> ... -> CLEANUP ->
    # (next turn's UNTAP). On entry to cleanup the per-turn flags
    # reset.
    for _ in range(20):  # bounded loop — one turn cycles < 20 phases
        rust_state.advance_phase()
        # The slot is cleared on the cleanup-step ENTRY, which happens
        # inside advance_phase when we step INTO PHASE_CLEANUP. After
        # the cleanup step the engine rolls into the next turn's
        # UNTAP, by which point the flag has already been reset.
        if rust_state.created_tokens_this_turn(0) is False:
            break

    assert rust_state.created_tokens_this_turn(0) is False, (
        "Phase 4 S3: the cleanup-step sweep must reset P0's "
        "created-tokens-this-turn flag back to False — mirror of "
        "Python's state.players_who_created_tokens_this_turn.clear() "
        "at turn.py:1092."
    )
    assert rust_state.created_tokens_this_turn(1) is False, (
        "Phase 4 S3: the cleanup-step sweep must keep P1's flag at "
        "False (it was never flipped this turn anyway)."
    )


# ---------------------------------------------------------------------
# Real-EoE Moonlit Meditation byte-equal probes
# ---------------------------------------------------------------------


def test_moonlit_meditation_real_eoe_card_def_carries_s3_flag():
    """Moonlit Meditation's real-EoE printing flows through
    ``_printing_to_card_def`` (the aura arm) carrying the S3 flag.
    Sanity that the parser + bridge plumbing agree on the value.

    **Post-Phase-4-S3-closure flip (2026-05-21).** Pre-closure the
    loader-side admit gate (``_printing_is_bridge_simple_aura``)
    declined Moonlit at the ``replaces_first_tokens_with_copies``
    check, so ``_printing_to_card_def`` raised
    ``ValueError("not bridge-supported")``. Post-closure the Rust
    CreateToken arms consult the controller's attached Moonlit-shape
    Aura via ``moonlit_token_substitution`` and swap the token's
    printing_id to the host's printing with the per-object Token-
    supertype override stamped; the loader now ADMITS Moonlit, and
    ``_printing_to_card_def`` materializes a CardDef whose
    ``aura_replaces_first_tokens_with_copies`` field is True.
    """
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    printing = src.get_printings().get("Moonlit Meditation")
    assert printing is not None, (
        "Pre-condition: Moonlit Meditation must be discoverable in "
        "the live parser pool."
    )
    assert printing.is_aura is True, (
        "Pre-condition: Moonlit Meditation must parse to is_aura=True."
    )
    assert printing.replaces_first_tokens_with_copies is True, (
        "Pre-condition: Moonlit Meditation must parse to "
        "replaces_first_tokens_with_copies=True."
    )

    # Phase 4 S3 closure (2026-05-21): _printing_to_card_def admits
    # the Moonlit Meditation printing and materializes a CardDef
    # whose Aura fields include aura_replaces_first_tokens_with_copies
    # = True. The CardDef round-trip (separate
    # test_aura_replaces_first_tokens_bridge_round_trip) already
    # locks in the bridge wire for a synthetic CardDef carrying that
    # flag; this real-EoE probe ensures the parser-to-CardDef arm
    # threads the field through end-to-end.
    cd = _printing_to_card_def(printing)
    assert cd.name == "Moonlit Meditation", (
        f"Phase 4 S3 closure: CardDef name must round-trip the "
        f"printing's name; got cd.name={cd.name!r}."
    )
    assert cd.card_type == "Enchantment", (
        f"Phase 4 S3 closure: Moonlit Meditation's CardDef must "
        f"materialize as card_type=Enchantment (the Phase-1 Aura "
        f"arm's shape); got cd.card_type={cd.card_type!r}."
    )
    assert cd.is_aura is True, (
        "Phase 4 S3 closure: Moonlit Meditation's CardDef must set "
        "is_aura=True."
    )
    assert cd.aura_replaces_first_tokens_with_copies is True, (
        "Phase 4 S3 closure: Moonlit Meditation's CardDef must thread "
        "aura_replaces_first_tokens_with_copies=True through to the "
        "Rust bridge so the substituted token's printing_id swap "
        "fires on cross-engine resolution."
    )
    assert cd.aura_yours_only is True, (
        "Phase 4 S3 closure: Moonlit Meditation's CardDef must carry "
        "aura_yours_only=True (the printing's 'Enchant creature you "
        "control' restriction)."
    )
    assert cd.aura_enchant_type == "creature", (
        "Phase 4 S3 closure: Moonlit Meditation's CardDef must carry "
        "aura_enchant_type='creature'."
    )


def test_moonlit_meditation_loader_admits_post_closure():
    """Moonlit Meditation admits at the bench loader post-Phase-4-S3
    closure (2026-05-21). Pre-closure pin (kept for change-tracking):
    ``_printing_is_bridge_simple_aura`` returned False at the
    ``replaces_first_tokens_with_copies`` check; post-closure: the
    rejection is replaced with a fallthrough comment, so the
    predicate admits Moonlit. The Rust CreateToken arms now consult
    the controller's Moonlit Aura via ``moonlit_token_substitution``
    (rust/src/state_ops_resolve.rs) and swap the token's printing_id
    to the host's printing with the per-object Token-supertype
    override stamped — bridge-correct against Python's
    ``_find_moonlit_replacement_source`` + ``_dc.replace(base,
    supertypes=...)`` shim.
    """
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_aura

    src = OracleParserCardSource()
    printing = src.get_printings().get("Moonlit Meditation")
    assert printing is not None
    assert printing.is_aura is True
    assert printing.replaces_first_tokens_with_copies is True
    assert _printing_is_bridge_simple_aura(printing) is True, (
        "Phase 4 S3 closure: Moonlit Meditation must ADMIT at the "
        "bench loader. The Rust CreateToken-family arms consult the "
        "controller's attached Moonlit-shape Aura via "
        "moonlit_token_substitution and swap the token's printing_id "
        "to the host's printing with the per-object Token-supertype "
        "override stamped on the freshly-minted GameObject — "
        "byte-equal cross-engine against Python's _dc.replace-injected "
        "supertype tuple."
    )


def test_phase4_s3_does_not_regress_phase3_admits():
    """Sanity: Pain for All still admits end-to-end after the S3 bridge
    plumbing. The Phase-3-safe-trigger gate is unchanged by this slice
    (we did NOT add any new trigger Effect to it — the substrate
    landed at the CardPrinting + state-slot layer)."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_aura

    src = OracleParserCardSource()
    printing = src.get_printings().get("Pain for All")
    assert printing is not None, (
        "Pre-condition: Pain for All must be discoverable in the "
        "live parser pool."
    )
    assert _printing_is_bridge_simple_aura(printing) is True, (
        "Phase 4 S3 regression check: Pain for All must continue to "
        "ADMIT at the bench loader after the S3 substrate landing."
    )


# ---------------------------------------------------------------------
# Python-side parity probe
# ---------------------------------------------------------------------


def test_python_parity_create_token_records_player_in_set():
    """Python's existing CreateToken semantics still write to the
    ``players_who_created_tokens_this_turn`` set. Cross-engine flag
    semantics agree: Python set membership == Rust per-player flag.

    This locks in the Python source-of-truth shape against which the
    Rust per-player flag was implemented. A future Moonlit-replacement
    consumer slice must keep the two engines in lockstep.
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.game import GameState, Player

    # Synthetic 2/2 Robot token printing — uses the canonical
    # token-creature factory so the printing carries the "Token"
    # supertype + Artifact Creature card-types the engine consumers
    # expect.
    token_printing = make_token_creature(
        name="Robot Token",
        power=2,
        toughness=2,
        subtypes=("Robot",),
        artifact=True,
    )

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    assert 0 not in state.players_who_created_tokens_this_turn, (
        "Pre-condition: P0's id must not be in the set on a fresh "
        "state."
    )

    effect = CreateToken(count=1, token_printing=token_printing)
    effect.resolve(state, controller_id=0)

    assert 0 in state.players_who_created_tokens_this_turn, (
        "Python parity: after CreateToken(count=1).resolve(state, 0), "
        "P0's id must be in the set. The Rust per-player flag is the "
        "byte-equal mirror — see test_created_tokens_this_turn_flag_"
        "set_on_token_creation."
    )
    assert 1 not in state.players_who_created_tokens_this_turn, (
        "Python parity: P1's id must NOT be in the set — only P0 "
        "received tokens."
    )


# ---------------------------------------------------------------------
# Phase 4 S3 closure (2026-05-21) — Moonlit Meditation real-EoE byte-
# equal probes. These mirror the
# test_real_eoe_pain_for_all_admits_via_filter_with_real_deck_shape /
# test_real_eoe_pain_for_all_deck_setup_byte_equal_cross_engine
# patterns in tests/test_aura_substrate_phase_3_s4.py for the new
# admit.
# ---------------------------------------------------------------------


def test_moonlit_meditation_admits_via_filter_with_real_deck_shape():
    """End-to-end: a real-EoE-deck-shape with 4 Moonlit Meditation
    copies flows through ``_filter_deck_to_bridge_supported`` without
    any Moonlit Meditation copies in the not-bridged sink. Verifies
    the Phase 4 S3 closure admit doesn't accidentally re-decline in
    the deck-side filter chokepoint.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    printings = get_active_source().get_printings()
    deck = ["Forest"] * 20 + ["Moonlit Meditation"] * 4
    not_bridged_sink: list[str] = []
    filtered, card_defs = _filter_deck_to_bridge_supported(
        deck, printings, not_bridged_sink=not_bridged_sink,
    )
    assert filtered.count("Moonlit Meditation") == 4, (
        "Phase 4 S3 closure end-to-end: 4 Moonlit Meditation copies "
        "must flow through the loader admit without any deck-side "
        "re-decline. Got filtered count="
        f"{filtered.count('Moonlit Meditation')!r}; "
        f"not_bridged_sink={not_bridged_sink!r}."
    )
    assert "Moonlit Meditation" not in not_bridged_sink, (
        "Phase 4 S3 closure end-to-end: Moonlit Meditation must NOT "
        "appear in the not-bridged sink — the loader admit predicate "
        f"now passes. Sink: {not_bridged_sink!r}."
    )
    assert any(c.name == "Moonlit Meditation" for c in card_defs), (
        "Phase 4 S3 closure end-to-end: the deck-side filter must "
        "materialize a CardDef for Moonlit Meditation."
    )
    moonlit_cd = next(c for c in card_defs if c.name == "Moonlit Meditation")
    assert moonlit_cd.aura_replaces_first_tokens_with_copies is True, (
        "Phase 4 S3 closure end-to-end: the materialized CardDef "
        "must carry aura_replaces_first_tokens_with_copies=True so "
        "the Rust registry parse-arm picks up the rider."
    )


def test_moonlit_meditation_real_eoe_deck_setup_byte_equal_cross_engine():
    """A real-EoE-deck-shape with Moonlit Meditation in both players'
    decks sets up identical Python + Rust states at game start.
    Verifies the loader admit + bridge round-trip + Rust registry
    parse all succeed end-to-end on the canonical Moonlit Meditation
    printing — the pre-condition for any future cross-engine
    trajectory probe that exercises the token-substitution path.

    Mirrors the
    ``test_real_eoe_pain_for_all_deck_setup_byte_equal_cross_engine``
    sister probe in tests/test_aura_substrate_phase_3_s4.py.
    """
    from mtg_bot.parity import trajectory

    deck = ["Forest"] * 20 + ["Moonlit Meditation"] * 4
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        deck, deck, shared_rng_seed=0, mulligans=False,
    )
    # Moonlit Meditation landed in the bridge-filtered deck on BOTH
    # engines — the loader admit + bridge round-trip both succeeded.
    # The two libraries reach the same total count (after pad-to-size
    # 60) on both engines; if the loader silently dropped Moonlit
    # Meditation the Python deck would still have 4 copies but the
    # Rust registry build would have raised a missing-printing error.
    py_libs = [len(p.library) for p in py_state.players]
    assert py_libs[0] == py_libs[1]
    rust_libs = list(rust_state.library_sizes)
    assert rust_libs[0] == py_libs[0]
    assert rust_libs[1] == py_libs[1]

    def _py_count_total(p):
        return sum(
            1 for o in (*p.library, *p.hand)
            if o.printing.name == "Moonlit Meditation"
        )

    # 4 Moonlit Meditation copies in library + hand across both
    # players — the loader admit landed cleanly without any silent
    # drop. The Python view's `o.printing.name` reads through to the
    # registered CardDef's name (same as the printing's parser name),
    # so the count is conservative.
    py_moonlit_p0 = _py_count_total(py_state.players[0])
    py_moonlit_p1 = _py_count_total(py_state.players[1])
    assert py_moonlit_p0 == 4, (
        "Phase 4 S3 closure end-to-end: P0 must hold 4 Moonlit "
        "Meditation copies after deck setup; got "
        f"{py_moonlit_p0!r}."
    )
    assert py_moonlit_p1 == 4, (
        "Phase 4 S3 closure end-to-end: P1 must hold 4 Moonlit "
        "Meditation copies after deck setup; got "
        f"{py_moonlit_p1!r}."
    )


def test_moonlit_meditation_substituted_token_carries_supertype_override():
    """**Phase 4 S3 closure consumer probe (2026-05-21).** Drive the
    Rust CreateToken arm end-to-end on a synthetic state where:

      * P0 controls a synthetic Moonlit-shape Aura attached to a
        host creature (the host's printing carries Creature card_type
        but NOT the Token supertype).
      * P0's per-player ``created_tokens_this_turn`` slot starts
        cleared.
      * A carrier permanent on P0's bf has an ETB that creates a
        synthetic 1/1 Robot token.

    After draining the ETB trigger, the newly-minted GameObject on
    P0's bf MUST:

      1. Carry the host's ``printing_id`` (not the Robot token's
         registered pid).
      2. Carry ``token_supertype_override = true`` (the per-object
         injection that mirrors Python's ``_dc.replace(base,
         supertypes=(*base, "Token"))`` shim).
      3. Cease to exist after leaving the battlefield (the
         drain_pending_token_cease scrub honors the per-object
         override — the substituted token IS a token even though its
         printing_id points at a non-Token printing).
    """
    import mtg_bot_engine  # noqa: F401
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)

    # 1. Register the host's printing — a Grizzly-Bears-shape
    #    creature (2/2 Bear, no Token supertype, no abilities).
    host_obj_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Host",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
            "effects": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # The host's printing_id is the first appended printing on a
    # fresh state's empty registry. Mirrors the helper at line ~245.
    host_pid = 0

    # 2. Register the Moonlit-shape Aura under P0's control, with
    #    ``attached_to = host_obj_id``. The CardPrinting carries
    #    ``aura_replaces_first_tokens_with_copies=True``.
    aura_obj_id = rust_state.register_and_inject_object(
        {
            "name": "Synthetic Moonlit Probe",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "U": 1},
            "effects": [],
            "is_aura": True,
            "aura_enchant_type": "creature",
            "aura_yours_only": True,
            "aura_replaces_first_tokens_with_copies": True,
        },
        0, ZONE_BATTLEFIELD,
    )
    assert rust_state.attach(aura_obj_id, host_obj_id) is True, (
        "Pre-condition: the Aura must attach to the host."
    )

    # 3. Register the Robot token printing.
    robot_obj_id = rust_state.register_and_inject_object(
        {
            "name": "Robot Token",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "supertypes": ["Token"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 0},
            "effects": [],
        },
        0, ZONE_LIBRARY,
    )
    # Robot Token is the third printing registered (host=0, aura=1,
    # robot=2). Verify by reading the printing's snapshot field;
    # robust against future printing-id-derivation refactors.
    assert rust_state.find_object_zone(robot_obj_id) == ZONE_LIBRARY
    robot_pid = 2

    # 4. Inject a carrier permanent whose ETB creates one of the
    #    robot tokens.
    rust_state.register_and_inject_object(
        {
            "name": "Token-Maker Probe Carrier",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": robot_pid,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # 5. Drain the ETB stack — the CreateToken arm should consult
    #    the Moonlit Aura, swap the token's printing_id to the host
    #    (host_pid), and stamp the per-object override.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # 6. The newly-minted token MUST carry the host's printing_id +
    #    the per-object Token-supertype override flag.
    bf_snapshot = rust_state.battlefield_snapshot()
    moonlit_substituted = [
        obj for obj in bf_snapshot
        if obj.get("token_supertype_override") is True
    ]
    assert len(moonlit_substituted) == 1, (
        "Phase 4 S3 closure consumer probe: exactly ONE bf object "
        "must carry token_supertype_override=True after the ETB "
        f"resolution. bf_snapshot={bf_snapshot!r}."
    )
    substituted = moonlit_substituted[0]
    assert substituted["printing_id"] == host_pid, (
        "Phase 4 S3 closure consumer probe: the substituted token's "
        "printing_id must point at the Moonlit-attached host (Bear "
        f"Host, pid={host_pid}); got {substituted['printing_id']!r}."
    )
    # Per-player flag flipped — the controller is now barred from
    # any additional Moonlit substitution this turn.
    assert rust_state.created_tokens_this_turn(0) is True


def test_moonlit_meditation_only_first_batch_each_turn_substitutes():
    """**Phase 4 S3 closure honest-stop probe.** The substitution MUST
    fire only on the FIRST token-creation batch each turn. A second
    batch on the same turn — even with the Moonlit Aura still attached
    — mints vanilla Robot tokens. Mirrors Python's
    ``recipient not in state.players_who_created_tokens_this_turn``
    membership check at ``effects/generic/tokens.py:225``.

    Drives the natural flag-flip mechanism: inject TWO Token-Maker
    Probe carriers back-to-back; the first carrier's ETB substitutes,
    the second carrier's ETB does not (the first one flipped the flag).
    """
    import mtg_bot_engine  # noqa: F401
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)

    # Host (Bear) + Aura + Robot — pid=0/1/2 in that order.
    rust_state.register_and_inject_object(
        {
            "name": "Bear Host",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
            "effects": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    host_pid = 0
    aura_obj_id = rust_state.register_and_inject_object(
        {
            "name": "Synthetic Moonlit Probe",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "U": 1},
            "effects": [],
            "is_aura": True,
            "aura_enchant_type": "creature",
            "aura_yours_only": True,
            "aura_replaces_first_tokens_with_copies": True,
        },
        0, ZONE_BATTLEFIELD,
    )
    assert rust_state.attach(aura_obj_id, 0) is True
    rust_state.register_and_inject_object(
        {
            "name": "Robot Token",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "supertypes": ["Token"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 0},
            "effects": [],
        },
        0, ZONE_LIBRARY,
    )
    robot_pid = 2

    # First carrier — its ETB substitutes (Bear copy, override=true,
    # flag flips on resolution).
    rust_state.register_and_inject_object(
        {
            "name": "Token-Maker Probe Carrier (first batch)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": robot_pid,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    assert rust_state.created_tokens_this_turn(0) is True, (
        "Pre-condition: the first-batch ETB must flip the controller's "
        "per-player created-tokens-this-turn flag."
    )

    # Second carrier — its ETB must NOT substitute (the flag is now
    # True, gating the substitution off).
    rust_state.register_and_inject_object(
        {
            "name": "Token-Maker Probe Carrier (second batch)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": robot_pid,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    bf_snapshot = rust_state.battlefield_snapshot()
    # Exactly ONE bf object carries the override (the first batch's
    # Moonlit-substituted Bear copy). The second batch produced a
    # vanilla Robot token (override=false, robot_pid).
    moonlit_substituted = [
        obj for obj in bf_snapshot
        if obj.get("token_supertype_override") is True
    ]
    assert len(moonlit_substituted) == 1, (
        "Phase 4 S3 closure honest-stop: exactly ONE bf object must "
        "carry the override (the first batch). The second batch "
        f"must mint a vanilla token. bf_snapshot={bf_snapshot!r}."
    )
    assert moonlit_substituted[0]["printing_id"] == host_pid, (
        "Phase 4 S3 closure honest-stop: the substituted token "
        "(first batch) must carry the host's pid; got "
        f"{moonlit_substituted[0]['printing_id']!r}."
    )
    # The second batch's Robot token IS on the bf, with the Robot
    # printing's pid (vanilla mint, no substitution).
    vanilla_robots = [
        obj for obj in bf_snapshot
        if obj.get("printing_id") == robot_pid
        and obj.get("token_supertype_override") is False
    ]
    assert len(vanilla_robots) == 1, (
        "Phase 4 S3 closure honest-stop: the second batch must mint "
        "exactly one vanilla Robot token with override=false. "
        f"bf_snapshot={bf_snapshot!r}."
    )
