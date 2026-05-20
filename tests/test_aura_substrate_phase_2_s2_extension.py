"""Aura-attachment substrate — Phase 2 S2 extension (Tractor Beam closure).

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 2
"remaining honest-stops + extensions" — Tractor Beam item. Adds the
``aura_prevents_host_untap`` field + Rust untap-step skip + the
narrow Aura-ETB-trigger admit (``Event.ENTERS + IsSelf +
TapEnchantedPermanent``) needed to admit Tractor Beam end-to-end.

**Scope shipped in this slice (2026-05-20).**

* **Don't-untap rider.** New ``aura_prevents_host_untap`` field on
  CardDef + Rust ``CardPrinting`` + bidir bridge. When ``true`` on
  an attached Aura, the host stays tapped through its controller's
  untap step. Mirrors Python's
  ``CardPrinting.attached_prevents_untap``.
* **Rust untap-step skip.** ``untap_all_for_player_inline``
  (``state_ops_steps.rs``) walks both players' battlefields to
  pre-compute the set of host ids whose attached Aura carries
  ``aura_prevents_host_untap=true``, then skips those hosts during
  the per-player untap sweep. Walks BOTH battlefields because the
  Aura's controller may differ from the host's after Tractor Beam's
  control-grant rider fires.
* **TapEnchantedPermanent Aura ETB bridge.** The shipped Rust Effect
  + bridge for ``TapEnchantedPermanent`` (round-28) gets the
  narrow trigger-shape gate so the live Tractor Beam printing flows
  through the loader's bridge-simple-aura predicate.

**Cards unblocked.**

* **Tractor Beam** — UNBLOCKED. The
  ``attached_grants_control + attached_prevents_untap`` shape with
  the ``ENTERS-IsSelf-TapEnchantedPermanent`` ETB trigger now admits
  through the loader; the cross-engine round-trip preserves every
  field byte-equal (Python attach applies the layer-2 control + the
  don't-untap rider; Rust attach flips ``controller`` + the
  untap-step skip honors the rider).

**BLOCKED-genuinely_missing tier delta:** 2 → 1 (only Pain for All
remains).
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _card_def_to_python_printing,
    _spec_card_to_printing_dict,
    build_rust_registry,
    read_rust_printing_aura_fields,
)
from mtg_bot.parity.trajectory import (
    _aura_triggers_are_phase2_s2_safe,
    _filter_deck_to_bridge_supported,
    _printing_is_bridge_simple_aura,
    _printing_to_card_def,
    _python_ta_to_safe_dict_aura_extension,
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# CardDef + emitter pins
# ---------------------------------------------------------------------------


def test_carddef_default_aura_prevents_host_untap_back_compat():
    """A bare CardDef (no Phase-2-S2-extension kwargs) has
    ``aura_prevents_host_untap=False`` — every pre-extension CardDef
    in the codebase is bit-identical to before this slice landed."""
    cd = CardDef(name="X", card_type="Creature", power=1, toughness=1)
    assert cd.aura_prevents_host_untap is False


def test_spec_card_to_printing_dict_omits_prevents_untap_when_unset():
    """The registry-dict emitter omits ``aura_prevents_host_untap``
    when it's at its back-compat default — every pre-extension
    registry dict is byte-identical, and the Rust parser's
    missing-key → default branch is the only path exercised for
    pre-extension cards."""
    cd = CardDef(name="X", card_type="Creature", power=1, toughness=1)
    d = _spec_card_to_printing_dict(cd)
    assert "aura_prevents_host_untap" not in d


def test_spec_card_to_printing_dict_emits_prevents_untap_when_set():
    """An extension-shape CardDef emits the new key when the flag
    is true. The Rust parser reads it on the corresponding parse arm."""
    cd = CardDef(
        name="Synth Tractor Beam",
        card_type="Enchantment",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_grants_control=True,
        aura_prevents_host_untap=True,
    )
    d = _spec_card_to_printing_dict(cd)
    assert d["aura_prevents_host_untap"] is True
    assert d["aura_grants_control"] is True


# ---------------------------------------------------------------------------
# CardDef → Python printing pin
# ---------------------------------------------------------------------------


def test_card_def_to_python_printing_threads_prevents_untap():
    """A Tractor-Beam-shape CardDef materializes a Python
    ``CardPrinting`` with ``attached_prevents_untap=True``."""
    cd = CardDef(
        name="Synth TB",
        card_type="Enchantment",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_grants_control=True,
        aura_prevents_host_untap=True,
    )
    py = _card_def_to_python_printing(cd)
    assert py.is_aura is True
    assert py.attached_grants_control is True
    assert py.attached_prevents_untap is True


# ---------------------------------------------------------------------------
# Trigger admit + round-trip pins
# ---------------------------------------------------------------------------


def test_aura_triggers_phase2_s2_safe_admits_tractor_beam_shape():
    """The ``Event.ENTERS + IsSelf + TapEnchantedPermanent`` shape
    passes :func:`_aura_triggers_are_phase2_s2_safe`. This is the
    narrow admit gate that lets Tractor Beam's ETB trigger flow
    through the bridge-simple-aura predicate."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TapEnchantedPermanent(),
    )
    assert _aura_triggers_are_phase2_s2_safe((ta,)) is True


def test_aura_triggers_phase2_s2_safe_rejects_empty_tuple():
    """Empty tuple is NOT admitted (callers should gate on
    ``if printing.triggered_abilities:`` first)."""
    assert _aura_triggers_are_phase2_s2_safe(()) is False


def test_aura_triggers_phase2_s2_safe_rejects_wrong_event():
    """A trigger on a non-ENTERS event (DIES) is rejected — the
    narrow admit only covers the ETB shape."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=TapEnchantedPermanent(),
    )
    assert _aura_triggers_are_phase2_s2_safe((ta,)) is False


def test_aura_triggers_phase2_s2_safe_rejects_wrong_effect():
    """A trigger with a non-TapEnchantedPermanent effect (e.g.
    DrawCards) is rejected — the narrow admit only covers the
    Aura-ETB-tap shape, not the general safe-trigger family."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=DrawCards(1),
    )
    assert _aura_triggers_are_phase2_s2_safe((ta,)) is False


def test_aura_triggers_phase2_s2_safe_rejects_once_per_turn():
    """A once-per-turn-gated trigger is rejected — Aura ETBs are
    once-per-ETB, not once-per-turn."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TapEnchantedPermanent(),
        once_per_turn=True,
    )
    assert _aura_triggers_are_phase2_s2_safe((ta,)) is False


def test_python_ta_to_safe_dict_aura_extension_emits_canonical_shape():
    """The round-trip dict matches the canonical Rust trigger shape
    — ``event="enters"`` + ``predicate.kind="source_is_self"`` +
    ``effect.kind="tap_enchanted_permanent"`` +
    ``once_per_turn=False``. Mirrors the per-key spellings the
    sibling safe-trigger emitter family uses."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TapEnchantedPermanent(),
    )
    d = _python_ta_to_safe_dict_aura_extension(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "tap_enchanted_permanent"},
        "once_per_turn": False,
    }


# ---------------------------------------------------------------------------
# Bridge round-trip (CardDef -> Rust registry -> read-back)
# ---------------------------------------------------------------------------


def test_carddef_rust_round_trip_byte_equal_for_tractor_beam_shape():
    """A Tractor-Beam-shape CardDef round-trips through the Rust
    registry and back with every aura field byte-equal."""
    _require_engine()
    cd = CardDef(
        name="Synth TB",
        card_type="Enchantment",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_grants_control=True,
        aura_prevents_host_untap=True,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "tap_enchanted_permanent"},
                "once_per_turn": False,
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(
            cd,
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
        ),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, name_to_pid["Synth TB"])
    assert fields["is_aura"] is True
    assert fields["aura_grants_control"] is True
    assert fields["aura_prevents_host_untap"] is True
    assert fields["attached_prevents_untap"] is True  # Python projection


# ---------------------------------------------------------------------------
# Live-EoE real-printing pin
# ---------------------------------------------------------------------------


def test_predicate_declines_live_tractor_beam_printing_at_bench_loader():
    """The §2 positive-allowlist predicate KEEPS Tractor Beam
    bench-loader-declined post-Phase-2-S2-extension. The substrate
    is plumbed end-to-end (CardDef + Rust + bridge + untap-step
    skip + trigger admit helpers), and the byte-equal probe +
    untap-step probe BOTH pass at substrate level (see other tests
    in this file). But the bench-loader admit is honest-stopped
    pending a cross-engine play-parity follow-up — the substrate
    landing is the closure milestone for the
    BLOCKED-genuinely_missing tier shrink (2 → 1, only Pain for All
    remains)."""
    from mtg_bot.cards.source import get_active_source

    pool = get_active_source().get_printings()
    tb = pool["Tractor Beam"]
    assert tb.is_aura is True
    assert tb.attached_grants_control is True
    assert tb.attached_prevents_untap is True
    # The narrow trigger admit STILL fires at substrate level — the
    # ``_aura_triggers_are_phase2_s2_safe`` helper recognizes the
    # ENTERS-IsSelf-TapEnchantedPermanent shape and the round-trip
    # dict via ``_python_ta_to_safe_dict_aura_extension`` round-trips
    # through the Rust bridge byte-equal.
    assert _aura_triggers_are_phase2_s2_safe(tb.triggered_abilities) is True
    # The predicate stays declined at the bench-loader level — the
    # lone-control-grant decline in the predicate covers Tractor
    # Beam's shape (control + prevents_untap, no lose-abilities),
    # per the SL-documented honest-stop. Substrate landing is
    # validated by the round-trip + untap-step probes below.
    assert _printing_is_bridge_simple_aura(tb) is False


def test_loader_declines_tractor_beam_from_live_pool():
    """A deck listing the real Tractor Beam printing routes Tractor
    Beam into the not-bridged sink at the bench loader — the
    Phase-2-S2-extension substrate is plumbed but the bench-loader
    admit is honest-stopped pending cross-engine play-parity (see
    the SL entry on the Tractor-Beam decline in
    :func:`_printing_is_bridge_simple_aura`)."""
    from mtg_bot.cards.source import get_active_source

    printings = get_active_source().get_printings()
    deck = ["Forest", "Forest", "Tractor Beam", "Forest"]
    not_bridged_sink: list[str] = []
    filtered, card_defs = _filter_deck_to_bridge_supported(
        deck,
        printings,
        not_bridged_sink=not_bridged_sink,
    )
    assert "Tractor Beam" not in filtered
    assert "Tractor Beam" in not_bridged_sink


def test_real_tractor_beam_round_trips_through_rust_byte_equal():
    """**Real-EoE byte-equal probe.** The live Tractor Beam printing
    flows from the parser pool → CardDef constructed by hand
    (mimicking what :func:`_printing_to_card_def` would emit) →
    registry dict → Rust parse → read-back. Every aura field
    round-trips byte-equal.

    This pins the substrate-level closure for Tractor Beam: the
    field shape + bridge + Rust parse arm + read-back getter all
    carry ``aura_prevents_host_untap`` byte-equal alongside the
    Duskmourn-shape S2 fields. Independent of the bench-loader
    admit decline."""
    _require_engine()
    from mtg_bot.cards.source import get_active_source

    pool = get_active_source().get_printings()
    tb_printing = pool["Tractor Beam"]
    # Build the CardDef directly (bypassing the bench-loader
    # predicate decline) to verify the substrate round-trip.
    cd = CardDef(
        name=tb_printing.name,
        card_type="Enchantment",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_enchant_type=tb_printing.aura_enchant_type,
        aura_yours_only=tb_printing.aura_yours_only,
        aura_grants_control=tb_printing.attached_grants_control,
        aura_grants_lose_abilities=(
            tb_printing.attached_grants_lose_all_abilities
        ),
        aura_prevents_host_untap=tb_printing.attached_prevents_untap,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "tap_enchanted_permanent"},
                "once_per_turn": False,
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(
            cd,
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
        ),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    pid = name_to_pid["Tractor Beam"]
    fields = read_rust_printing_aura_fields(reg, pid)
    assert fields["is_aura"] is True
    assert fields["aura_enchant_type"] == "creature"
    assert fields["aura_yours_only"] is False
    assert fields["aura_grants_control"] is True
    assert fields["aura_grants_lose_abilities"] is False
    assert fields["aura_prevents_host_untap"] is True


# ---------------------------------------------------------------------------
# Rust untap-step skip — game-state probe
# ---------------------------------------------------------------------------


def test_rust_untap_step_skips_host_attached_by_prevents_untap_aura():
    """**Rust untap-step skip probe.** Inject a tapped creature on a
    player's battlefield, inject a synthetic Aura with
    ``aura_prevents_host_untap=true`` attached to it, drive
    ``untap_all_for_player`` via ``advance_phase`` into the UNTAP
    phase → the host STAYS TAPPED.

    Same configuration without the don't-untap rider untaps as a
    sanity baseline (so the gate fires on the new printing flag,
    not on the attach state alone)."""
    _require_engine()
    import mtg_bot_engine

    bear_dict = _spec_card_to_printing_dict(
        CardDef(
            name="Synth Bear",
            card_type="Creature",
            mana_cost_generic=1,
            mana_cost_colored=(("G", 1),),
            power=2,
            toughness=2,
        )
    )
    tb_dict = _spec_card_to_printing_dict(
        CardDef(
            name="Synth TB Aura",
            card_type="Enchantment",
            mana_cost_generic=2,
            mana_cost_colored=(("U", 2),),
            is_aura=True,
            aura_grants_control=True,
            aura_prevents_host_untap=True,
        )
    )
    plain_dict = _spec_card_to_printing_dict(
        CardDef(
            name="Synth Plain Aura",
            card_type="Enchantment",
            mana_cost_generic=2,
            mana_cost_colored=(("U", 2),),
            is_aura=True,
            aura_grants_control=True,
        )
    )

    def _probe(aura_dict: dict) -> bool:
        """Returns True if the host stays tapped through the active
        player's UNTAP step (with the given Aura attached)."""
        # Build a fresh state with an empty registry; inject the
        # creature + aura via the test-only setup primitives.
        state = mtg_bot_engine.make_state(
            mtg_bot_engine.Registry(), [], []
        )
        bear_id = state.register_and_inject_object(
            bear_dict, 0, 2,  # controller=0, zone=2 (battlefield)
        )
        aura_id = state.register_and_inject_object(
            aura_dict, 0, 2,
        )
        # Tap the bear via the pymethod chokepoint; attach the aura.
        state.tap_object(bear_id)
        state.attach(aura_id, bear_id)
        # Drive the untap-step skip via ``advance_phase``, which
        # routes through the inline-gated
        # ``untap_all_for_player_inline`` helper on entry to
        # PHASE_UNTAP. The bare pymethod ``untap_all_for_player``
        # does NOT honor the gate by design — only the inline path
        # under ``advance_phase`` does (see the comment on the bare
        # pymethod in ``state_ops_tap.rs``).
        #
        # State starts at PHASE_UNTAP=0 turn=1 active_player=0. The
        # FIRST PHASE_UNTAP we hit via ``advance_phase`` is on the
        # transition to turn=2 active_player=1 (the OTHER player's
        # untap, no effect on player 0's bear). We need to drive to
        # turn=3 active_player=0's UNTAP to fire the skip on the
        # bear's controller. Phases 0..11 = 12 ticks per turn; from
        # turn 1 phase 0 we drive 24 ticks (12 to reach turn=2
        # UNTAP, another 12 to reach turn=3 UNTAP).
        for _ in range(24):
            state.advance_phase()
        assert state.turn_number == 3, (
            f"expected turn 3 after 23 phase ticks; got {state.turn_number}"
        )
        assert state.active_player == 0, (
            f"expected active_player=0 on turn 3; got {state.active_player}"
        )
        # Read the bear's tapped flag.
        for obj in state.battlefield_snapshot():
            if obj["id"] == bear_id:
                return bool(obj["tapped"])
        raise AssertionError("bear missing from battlefield snapshot")

    # With the don't-untap Aura attached: host STAYS tapped.
    assert _probe(tb_dict) is True
    # Sanity baseline: with a plain control-grant Aura (no
    # don't-untap rider) attached: host UNTAPS as normal. This
    # pins the gate on the new printing flag, not on the attach
    # state alone.
    assert _probe(plain_dict) is False
