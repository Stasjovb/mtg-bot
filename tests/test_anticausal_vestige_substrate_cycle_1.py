"""Anticausal Vestige — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/anticausal-vestige-cycle-1-substrate-p1``
(2026-05-24).

Anticausal Vestige is a {2}{B} 2/2 Creature with ``warp_cost {4}`` and
a LEAVES_BATTLEFIELD triggered ability: "When this creature leaves the
battlefield, draw a card, then you may put a permanent card with mana
value less than or equal to the number of lands you control from your
hand onto the battlefield tapped." It is the #3-ranked multi-gated-
tail candidate from the 2026-05-24 multi-gated tractability scout
(``docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-24.md``, commit
``fdc3b8d6``) — ~6,900 17lands decks.

Substrate breakdown (sibling mirror of Codecracker Hound multi-cycle
commits ``bd37cca0`` C1, ``278992d7`` C2, ``6f99bf45`` C3):

* **Cycle 1 (this slice — substrate-only).** New Rust
  ``Effect::AnticausalVestigeLeavesEffect`` unit variant + parse_effect
  arm + to_pydict arm + resolve arm in ``state_ops_resolve.rs`` +
  Python bridge arm in
  ``cross_engine._ta_dict_to_python_effect``. AV STAYS DECLINED at the
  admit gate (``_printing_is_bridge_pure_warp_creature``) because its
  LEAVES_BATTLEFIELD trigger is rejected by
  ``_python_ta_to_safe_dict``'s event gate (gated to ``(ENTERS, DIES,
  ATTACKS, BECOMES_TAPPED)`` at ``trajectory.py:3437-3440`` — LEAVES
  is the 5th event the safe set will admit, shipped in Cycle 2).
* **Cycle 2 (this slice — admit widen, FLIPPED AV DECLINED →
  ADMITTED).** Widened ``_python_ta_to_safe_dict``'s event
  vocabulary to admit LEAVES_BATTLEFIELD (the genuinely new event
  for the safe-trigger admit set; DIES exists but DIES != LEAVES
  semantically — DIES is the bf→graveyard subset, LEAVES covers
  every bf→{anywhere} zone change). Added the
  ``("leaves_battlefield", "source_is_self",
  "anticausal_vestige_leaves_effect")`` ``_SAFE_TRIGGERS`` entry +
  the matching ``_SAFE_EFFECT_KEYS`` whitelist entry (bare
  ``{"kind"}`` — unit shape, no payload keys) + the new
  ``AnticausalVestigeLeavesEffect`` dispatch arm in the recognizer's
  effect-class chain. Bumped the warp-arm admit set 7→8 (the C2
  delta vs the post-CH-C2 count: AV inserted alphabetically before
  Bygone Colossus) + flipped the per-card admit parametrize entry
  ``("Anticausal Vestige", False)`` → ``("Anticausal Vestige",
  True)`` in ``tests/test_trajectory.py``. Verify-first scan of
  HEAD confirmed only 4 OTHER cards carry LEAVES_BATTLEFIELD
  triggered abilities (Cryogen Relic, Broodguard Elite, Syr Vondam,
  Nutrient Block); none silently auto-grow under the widen (their
  effect classes are not in the LEAVES ``safe_effect_kinds`` tuple,
  and / or their predicates are not ``IsSelf``).
* **Cycle 3 (after).** Per-card real-EoE cross-engine byte-equality
  probe under both warp-cast and normal-cast lifecycles (mirror of
  ``test_codecracker_hound_parity.py`` shape; ``test_probe_warp_
  admitted.py`` ``_WARP_CARDS`` bump to add AV). FLIPS AV
  covered_by_construction → PROBED.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** The printed surface form parses to
   ``AnticausalVestigeLeavesEffect()`` via the existing literal-phrase
   recognizer at ``cards/parser/effects.py:3445-3450``. Pre-existing
   on main; pinned here to guard against parser drift while the new
   Rust substrate lands.
2. **Rust round-trip — parse + to_pydict.** A synthetic carrier with
   the ``{"kind": "anticausal_vestige_leaves_effect"}`` triggered-
   ability dict registers on Rust's ``parse_effect`` and round-trips
   through ``Effect::AnticausalVestigeLeavesEffect`` →
   ``effect_to_pydict`` back to the SAME dict shape (the unit-variant
   substrate parity discipline established by the round-49 /
   round-54 / 16th-slice precedents).
3. **Cross-engine bridge round-trip.** The bridge arm
   ``cross_engine._ta_dict_to_python_effect`` consumes the
   ``{"kind": "anticausal_vestige_leaves_effect"}`` dict and yields
   the Python ``AnticausalVestigeLeavesEffect()`` instance — the
   forward direction the Cycle-2 admit-set widen will lean on.
4. **Rust resolve smoke (deterministic-first contract).** The Rust
   resolve arm, exercised on a minimal synthetic state with a seated
   controller + a hand of land+permanent cards + the source on the
   battlefield, performs the SAME post-resolve mutation as Python's
   ``AnticausalVestigeLeavesEffect.resolve`` along the seated-agent
   ``candidates[0]`` fallback path: library shrinks by one (draw),
   one legal permanent leaves hand and lands on battlefield TAPPED
   with ``summoning_sick=True`` (CR 302.1), and the entered card's
   ``Event::Enters`` is queued for the post-pop dispatch sweep.
5. **Cycle-2 closure marker — AV NOW ADMITS at the admit gate
   (INVERTED from the C1 substrate-only pin).**
   ``_printing_is_bridge_pure_warp_creature(Anticausal Vestige) is
   True`` post-Cycle-2; the load-bearing closure marker that the
   admit-widen + recognizer extensions all landed correctly. The C1
   pin (``test_anticausal_vestige_stays_declined_post_cycle_1``,
   asserting ``is False``) was the inversion-discipline mirror of
   Codecracker Hound's C1 pin; this slice flips it (mirror of
   ``test_codecracker_hound_now_admits_at_admit_gate_post_cycle_2``
   from CH C2 commit ``278992d7``). If this assertion FLIPS False
   post-Cycle-2, the widen has regressed — verify the event-gate
   widen, the LEAVES ``safe_effect_kinds`` tuple, the
   ``AnticausalVestigeLeavesEffect`` dispatch arm, the
   ``_SAFE_TRIGGERS`` triple, and the ``_SAFE_EFFECT_KEYS`` whitelist
   entry are all present.
6. **Covered-set membership.** The ``anticausal_vestige_leaves_effect``
   kind round-trips Rust's ``parse_effect`` for use within a
   triggered_ability — the per-trigger-kind smoke that the Rust
   parser knows the new kind (mirrors the BLOCKED-BRIDGE-ARM
   smoke test pattern from ``test_rust_parser_accepts_*``).
"""

from __future__ import annotations

import pytest


def test_parser_anticausal_vestige_surface_parses_to_unit_effect():
    """Pin #1 — parser SoT. The printed surface form (the literal
    phrase recognized at ``cards/parser/effects.py:3445-3450``)
    parses to a unit-variant ``AnticausalVestigeLeavesEffect()``."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect

    parsed = _parse_effect(
        "draw a card, then you may put a permanent card with mana "
        "value less than or equal to the number of lands you control "
        "from your hand onto the battlefield tapped"
    )
    assert parsed == AnticausalVestigeLeavesEffect(), (
        f"Anticausal Vestige surface form must parse to "
        f"AnticausalVestigeLeavesEffect(); got {parsed!r}"
    )


def test_rust_parser_accepts_anticausal_vestige_leaves_effect_in_triggered_ability():
    """Pin #2 — Rust round-trip — parse + to_pydict. A synthetic
    carrier with the ``{"kind": "anticausal_vestige_leaves_effect"}``
    triggered-ability dict registers on Rust's parse_effect (no
    ``ValueError`` raised); the to_pydict round-trip lands on the
    same minimal unit-shape ``{"kind":
    "anticausal_vestige_leaves_effect"}``. Mirrors the BLOCKED-
    BRIDGE-ARM ``test_rust_parser_accepts_*`` shape.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": (
            "Anticausal Vestige Cycle 1 Substrate Pin -- carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "anticausal_vestige_leaves_effect",
                },
            }
        ],
    }
    # Rust accepts the kind — no PyValueError on register_printing.
    pid = reg.register_printing(d)
    assert isinstance(pid, int)


def test_bridge_arm_round_trips_anticausal_vestige_leaves_effect():
    """Pin #3 — cross-engine bridge round-trip. The bridge arm
    ``cross_engine._ta_dict_to_python_effect`` consumes the
    unit-shape ``{"kind": "anticausal_vestige_leaves_effect"}`` dict
    and yields the Python ``AnticausalVestigeLeavesEffect()``
    instance — the load-bearing forward direction the Cycle-2 admit-
    set widen will exercise once the safe-trigger recognizer is
    widened to admit LEAVES_BATTLEFIELD.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect

    rt = _ta_dict_to_python_effect({
        "kind": "anticausal_vestige_leaves_effect",
    })
    assert rt == AnticausalVestigeLeavesEffect(), (
        f"Bridge round-trip must yield AnticausalVestigeLeavesEffect(); "
        f"got {rt!r}"
    )
    # Defensive: extra dict fields are ignored (unit-variant
    # round-trip-consistency convention).
    rt_extra = _ta_dict_to_python_effect({
        "kind": "anticausal_vestige_leaves_effect", "ignored_extra": 42,
    })
    assert rt_extra == AnticausalVestigeLeavesEffect()


def test_anticausal_vestige_now_admits_at_admit_gate_post_cycle_2():
    """Pin #5 — Cycle-2 closure marker: AV NOW ADMITS at the
    warp-arm admit gate (INVERTED from the C1 substrate-only pin
    ``test_anticausal_vestige_stays_declined_post_cycle_1``).

    The Cycle-2 widen lands three coordinated changes in
    ``src/mtg_bot/parity/trajectory.py``:

      * ``_python_ta_to_safe_dict`` event vocabulary widened from
        ``(ENTERS, DIES, ATTACKS, BECOMES_TAPPED)`` to also include
        ``LEAVES_BATTLEFIELD`` (the FIFTH event in the safe set; the
        genuinely-new event vocabulary — ``DIES`` is the strict bf→
        graveyard subset whereas ``LEAVES_BATTLEFIELD`` covers every
        bf→{anywhere} zone change).
      * New ``LEAVES_BATTLEFIELD`` arm in the IsSelf branch with
        ``safe_effect_kinds = ("anticausal_vestige_leaves_effect",)``
        + new dispatch arm for ``AnticausalVestigeLeavesEffect`` that
        emits the bare unit-shape dict ``{"kind":
        "anticausal_vestige_leaves_effect"}``.
      * Matching ``("leaves_battlefield", "source_is_self",
        "anticausal_vestige_leaves_effect")`` entry in
        ``_SAFE_TRIGGERS`` + ``"anticausal_vestige_leaves_effect":
        frozenset({"kind"})`` entry in ``_SAFE_EFFECT_KEYS`` (the
        round-trip dict-side backstops).

    Net effect: AV's only triggered_ability now round-trips through
    the safe-trigger recognizer, so the per-trigger gate in
    ``_printing_is_bridge_pure_warp_creature`` accepts AV. AV is
    ADMITTED at the warp creature admit gate post-Cycle-2.

    Mirror of the Codecracker Hound Cycle-2 inversion pin
    ``test_codecracker_hound_now_admits_at_admit_gate_post_cycle_2``
    (commit ``278992d7``).

    Defensive cross-checks: the spell-card-bridge gate stays False
    (AV is a Creature → spell-card gate filters by construction);
    the plain simple-creature arm stays False (AV has ``warp_cost``
    → the plain creature arm positively rejects, so the warp arm
    remains the load-bearing admit path).

    If this assertion FLIPS False post-Cycle-2, the widen has
    regressed: either the event-gate widen, the LEAVES arm
    ``safe_effect_kinds`` tuple, the dispatch arm, the
    ``_SAFE_TRIGGERS`` triple, or the ``_SAFE_EFFECT_KEYS`` whitelist
    was reverted.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    av = src.get("Anticausal Vestige")
    if av is None:
        pytest.skip("Anticausal Vestige absent from active CardSource")

    # The load-bearing Cycle-2 closure marker — AV now ADMITS at the
    # structural admit gate (the warp creature arm).
    assert trajectory._printing_is_bridge_pure_warp_creature(av) is True, (
        "Anticausal Vestige MUST ADMIT at the warp creature admit "
        "gate post-Cycle-2. A False here means the Cycle-2 widen has "
        "regressed — verify the event-gate widen, the LEAVES "
        "safe_effect_kinds tuple, the AnticausalVestigeLeavesEffect "
        "dispatch arm, the _SAFE_TRIGGERS triple, and the "
        "_SAFE_EFFECT_KEYS whitelist entry are all present."
    )
    # Defensive cross-check: the spell-card-bridge gate stays False
    # (AV is a Creature; this gate filters creatures by construction —
    # the spell arm is NOT the load-bearing admit path).
    assert trajectory._printing_is_bridge_simple_spell(av) is False, (
        "Anticausal Vestige is a Creature — the spell-card-bridge "
        "gate must continue to filter it out at the creature-type "
        "check; if this asserts True, the spell arm has accidentally "
        "widened."
    )
    # Defensive cross-check: the plain simple-creature arm stays False
    # (AV has warp_cost, which that arm positively rejects — the warp
    # arm remains the load-bearing admit path post-C2).
    assert trajectory._printing_is_bridge_simple_creature(av) is False, (
        "The plain simple-creature arm must continue to reject "
        "Anticausal Vestige (warp_cost trips it); the warp arm is "
        "the load-bearing admit path AV admits at post-Cycle-2."
    )
    # Verify-first refinement: AV's warp_cost is genuinely present
    # (the warp-arm gate is the load-bearing one).
    assert av.warp_cost_str == "{4}", (
        f"Verify-first: AV's warp_cost_str must be '{{4}}'; got "
        f"{av.warp_cost_str!r}"
    )


def test_anticausal_vestige_safe_dict_recognizer_admits_leaves_event_post_cycle_2():
    """Pin #5b — Cycle-2 closure marker: the safe-trigger recognizer
    ``_python_ta_to_safe_dict`` ADMITS AV's parsed LEAVES_BATTLEFIELD
    trigger (INVERTED from the C1 substrate-only pin
    ``test_anticausal_vestige_safe_dict_recognizer_rejects_leaves_event``).

    AV's parsed triggered ability is
    ``TriggeredAbility(event=Event.LEAVES_BATTLEFIELD,
    predicate=IsSelf(), effect=AnticausalVestigeLeavesEffect())``.
    Post-Cycle-2 the recognizer's event gate admits
    ``LEAVES_BATTLEFIELD``, the IsSelf branch's LEAVES arm carries
    ``safe_effect_kinds = ("anticausal_vestige_leaves_effect",)``,
    and the dispatch arm for ``AnticausalVestigeLeavesEffect`` emits
    the bare unit-shape dict. The recognizer returns a structured
    safe-dict — the structural reason AV now admits at the warp-arm
    admit gate (Pin #5).

    The exact safe-dict shape pinned here:
      ``{"event": "leaves_battlefield",
         "predicate": {"kind": "source_is_self"},
         "effect": {"kind": "anticausal_vestige_leaves_effect"}}``
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    src = get_active_source().get_printings()
    av = src.get("Anticausal Vestige")
    if av is None:
        pytest.skip("Anticausal Vestige absent from active CardSource")
    (ta,) = av.triggered_abilities
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "leaves_battlefield",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "anticausal_vestige_leaves_effect"},
    }, (
        f"AV's LEAVES_BATTLEFIELD trigger MUST round-trip through "
        f"the safe-trigger recognizer post-Cycle-2 to the bare "
        f"unit-shape dict; got {d!r}. A None or shape-mismatch here "
        f"means the Cycle-2 widen has regressed at one of the three "
        f"coordinated edits (event-gate widen / LEAVES "
        f"safe_effect_kinds tuple / AnticausalVestigeLeavesEffect "
        f"dispatch arm)."
    )


def test_python_resolve_smoke_seated_agent_path():
    """Pin #4 — Python resolve contract (seated-agent deterministic-
    first path).

    Exercises the Python-side ``AnticausalVestigeLeavesEffect.resolve``
    along the SAME seated-agent ``candidates[0]`` fallback path the
    Rust resolve arm mirrors step-for-step. With 4 Mountains on the
    controller's battlefield (X=4), Memorial Vault (MV 4) in hand,
    and a 2-card library, the resolve must: (a) draw 1 (library
    shrinks); (b) pick Memorial Vault (the first MV-≤-4 permanent in
    hand); (c) put it onto the battlefield tapped.

    Pre-existing ``test_anticausal_vestige.py`` covers the full
    Python contract; this pin is a minimal redundant invariant
    co-located with the Cycle-1 substrate landing so a regression
    here (e.g., a Python class refactor that diverges from the Rust
    arm's mirror) surfaces alongside the substrate pins.

    The cross-engine byte-equality probe (the genuine "both engines
    produce the SAME post-resolve state") is Cycle-3 work, gated on
    Cycle 2 admitting AV through the bridge.
    """
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.agents import Agent
    from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect

    class _PickFirstAgent(Agent):
        def choose_sacrifice(self, state, player_id, legal_ids):
            return legal_ids[0] if legal_ids else None

    printings = get_active_source().get_printings()
    if "Memorial Vault" not in printings:
        pytest.skip("Memorial Vault absent from active CardSource")
    vault_printing = printings["Memorial Vault"]

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    # 2-card library on P0 (top draws — basic Plains).
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    # 4 Mountains on P0's battlefield → X=4.
    for _ in range(4):
        land = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(land)
    # Memorial Vault (MV 4) in P0's hand — the legal pick at X=4.
    vault = state.new_object(vault_printing, 0, Zone.HAND)
    state.players[0].hand.append(vault)

    lib_before = len(state.players[0].library)
    bf_before = len(state.battlefield)

    AnticausalVestigeLeavesEffect().resolve(state, 0, ())

    # (a) Drew 1 card.
    assert len(state.players[0].library) == lib_before - 1, (
        f"Library must shrink by 1 (draw step); was {lib_before}, "
        f"now {len(state.players[0].library)}"
    )
    # (b/c) Vault left hand and entered battlefield tapped.
    assert vault not in state.players[0].hand, (
        "Memorial Vault must have left hand (chosen by "
        "_PickFirstAgent's candidates[0] equivalent path)"
    )
    assert vault in state.battlefield, (
        "Memorial Vault must be on the battlefield post-resolve"
    )
    assert vault.tapped is True, (
        "Memorial Vault must enter TAPPED (printed text: "
        "'onto the battlefield tapped')"
    )
    # bf grew by exactly 1 (the Vault).
    assert len(state.battlefield) == bf_before + 1


def test_rust_unit_variant_round_trips_through_effect_dict():
    """Pin #6 — covered-set membership smoke. A unit-shape dict
    ``{"kind": "anticausal_vestige_leaves_effect"}`` round-trips
    through Rust's ``parse_effect`` → ``Effect::
    AnticausalVestigeLeavesEffect`` → ``effect_to_pydict`` back to
    the SAME minimal unit-shape dict. This is the per-Effect-kind
    Rust-side smoke that the parse + to_pydict arms are wired
    (mirrors the round-49 / round-54 / 16th-slice unit-variant
    round-trip discipline).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Register a minimal carrier — the LEAVES_BATTLEFIELD triggered
    # ability is the canonical surface that exercises the new
    # parse_effect arm (the C2 ``leaves_battlefield`` event widen
    # WILL exercise this same kind on a real-card path; for C1 the
    # smoke is a unit-shape registration).
    pid = reg.register_printing({
        "name": (
            "AV-C1-Substrate Pin -- AnticausalVestigeLeavesEffect "
            "unit round-trip"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "anticausal_vestige_leaves_effect",
                },
            }
        ],
    })
    assert isinstance(pid, int)
    # Round-trip the printing's triggered_abilities to_dict view back
    # through the bridge — yields the same Python class instance.
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect

    rt = _ta_dict_to_python_effect({
        "kind": "anticausal_vestige_leaves_effect",
    })
    assert isinstance(rt, AnticausalVestigeLeavesEffect)
    assert rt == AnticausalVestigeLeavesEffect()
