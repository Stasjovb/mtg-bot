"""Weftwalking — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/weftwalking-cycle-1-substrate-p1`` (2026-05-24).

Weftwalking is a ``{4}{U}{U}`` Enchantment with an ENTERS+IsSelf
triggered ability whose effect is the parsed composite::

    ConditionalIfCastFromHand(
        inner_effect=Sequence(
            ShuffleZonesIntoLibrary(zones=('hand', 'graveyard')),
            DrawCards(amount=7),
        )
    )

It is the **#1-ranked remaining multi-gated-tail candidate** from the
2026-05-24 multi-gated tractability **rescout** (commit ``02407af5``;
``docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md`` §
"#1 — Weftwalking (3,680 decks, ~3 cycles)") — ~3,680 17lands decks.

Substrate breakdown (sibling mirror of Anticausal Vestige multi-cycle
commits ``e148450a`` C1, ``c32f07f9`` C2, ``a9001390`` C3 — the same
substrate→admit-widen→probe cadence applied today):

* **Cycle 1 (this slice — substrate-only).** Two new Rust ``Effect``
  variants — ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
  (recursive combinator, sibling of ``MayDo`` / ``IfYouDo`` /
  ``OptionalSacAnotherForEffect`` shape) and
  ``Effect::ShuffleZonesIntoLibrary { zones: Vec<String> }`` (flat
  leaf, sibling of zone-move shapes). Parse arms + ``to_pydict`` arms
  + resolve arms in ``state_ops_resolve.rs`` + cross-engine bridge
  arms in ``cross_engine._ta_dict_to_python_effect`` (recursive on
  ``inner`` for the combinator; flat list-of-strings for the leaf)
  + reverse-serializer leaves in ``parity/trajectory.py`` (including
  the nested-``Sequence``-as-leaf arm so a ``Sequence`` appearing as a
  child of another composer round-trips). **Weftwalking STAYS
  DECLINED at the admit gate post-Cycle-1** — the safe-trigger
  recognizer ``_python_ta_to_safe_dict`` rejects the
  ``ConditionalIfCastFromHand`` effect (not in the safe-effect
  allowlist; the wrap is new vocabulary the recognizer hasn't been
  taught yet).

* **Cycle 2 (LANDED 2026-05-24 — admit widen).** Wired the 10th
  ``ENTERS+IsSelf`` safe-trigger leaf widen:
  ``conditional_if_cast_from_hand`` with the EXACT canonical
  Weftwalking inner gate (``Sequence(ShuffleZonesIntoLibrary(
  zones=('hand','graveyard')), DrawCards(amount=7))``) — the
  surgical-widen §2 teeth (any other inner shape stays declined).
  Added the matching ``_SAFE_TRIGGERS`` triple + the
  ``_SAFE_EFFECT_KEYS["conditional_if_cast_from_hand"] =
  frozenset({"kind","inner"})`` whitelist. Wired a NEW
  ``_printing_is_bridge_simple_enchantment`` admit arm (the
  Enchantment-side sibling of
  ``_printing_is_bridge_simple_creature`` — a fresh arm rather than
  extending the Creature arm because the latter cascades through
  Creature-specific downstream assumptions). The arm sits in the
  ``_filter_deck_to_bridge_supported`` disjunct chain immediately
  after ``_printing_is_bridge_simple_cast_restriction_enchantment``,
  with the two Enchantment arms mutually exclusive by construction
  (Weftwalking has triggers + the cast-restriction flag off;
  Deafening Silence has no triggers + the flag on). Single-card
  FLIP, no silent auto-grows (verified live: Weftwalking is the
  SOLE ``ConditionalIfCastFromHand`` carrier system-wide).
  Inverted Pin #6 from "STAYS DECLINED" to "NOW ADMITS" + added
  the printing-level sibling pin.

* **Cycle 3 (after — per-card probe + warp-cast lifecycle).** Per the
  rescout (§ "#1 — Weftwalking"), Cycle 3 ships the per-card real-
  EoE cross-engine byte-equality probe (``tests/
  test_weftwalking_parity.py``, mirror of
  ``test_codecracker_hound_parity.py`` /
  ``test_anticausal_vestige_parity.py`` shape) + the warp-cast
  lifecycle probe IF Weftwalking's printing carries a ``warp_cost``
  (verify-first against HEAD: at the time of this slice
  ``weftwalking.warp_cost_str == ""`` — no warp cost, so the warp-
  cast lifecycle probe is structurally inapplicable; Cycle 3 ships
  the normal-cast lifecycle probe alone). FLIPS Weftwalking
  covered_by_construction → PROBED.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** Weftwalking's printed surface form parses to the
   exact composite this substrate lands::

       TriggeredAbility(
           event=Event.ENTERS,
           predicate=IsSelf(),
           effect=ConditionalIfCastFromHand(
               inner_effect=Sequence(
                   ShuffleZonesIntoLibrary(zones=('hand', 'graveyard')),
                   DrawCards(amount=7),
               )
           ),
       )

   The phrase mapping (``"you cast it" -> lambda inner:
   ConditionalIfCastFromHand(inner_effect=inner)``) is at
   ``cards/parser/triggers.py:1462``; the inner ``ShuffleZonesIntoLibrary``
   builder is at ``cards/parser/effects.py:4823``. Pre-existing on
   main; pinned here to guard against parser drift while the new
   Rust substrate lands.

2. **Rust round-trip — ConditionalIfCastFromHand combinator.** A
   synthetic carrier with the recursive
   ``{"kind": "conditional_if_cast_from_hand", "inner": {"kind":
   "draw_cards", "amount": 7}}`` triggered-ability dict registers on
   Rust's ``parse_effect`` (the inner Effect is recursively parsed)
   and round-trips through ``Effect::ConditionalIfCastFromHand``
   (``Box<Effect>`` payload) → ``effect_to_pydict`` back to the SAME
   dict shape — the recursive-combinator parity discipline (sibling
   of ``MayDo`` / ``IfYouDo`` / ``OptionalSacAnotherForEffect`` /
   ``ConditionalIfSourcePowerAtLeast``).

3. **Rust round-trip — ShuffleZonesIntoLibrary leaf.** A synthetic
   carrier with the flat ``{"kind": "shuffle_zones_into_library",
   "zones": ["hand", "graveyard"]}`` dict registers on Rust's
   ``parse_effect`` and round-trips back to the SAME dict shape —
   the flat-leaf parity discipline (sibling of ``draw_cards`` /
   ``deal_damage`` flat shapes; the ``zones`` field is a tuple-of-
   strings list-of-strings payload, NOT a fixed enum).

4. **Cross-engine bridge round-trip (both variants).** Forward
   bridge arms in ``cross_engine._ta_dict_to_python_effect`` consume
   both dict shapes and reconstruct the Python classes:
   ``ConditionalIfCastFromHand(inner_effect=<recursed>)`` (recurses
   on the ``inner`` field; field-name translation seam — Rust
   ``inner`` ↔ Python ``inner_effect``) and
   ``ShuffleZonesIntoLibrary(zones=("hand", "graveyard"))`` (flat
   tuple). The load-bearing forward direction the Cycle-2 admit-set
   widen will exercise once the safe-trigger recognizer is widened
   to admit the wrap shape.

5. **Reverse-serializer leaves (both variants + nested-Sequence
   leaf).** ``trajectory._python_spell_effect_to_dict`` /
   ``trajectory._python_ta_effect_to_dict`` recognize both new
   Python classes and emit the dict shapes Rust consumes (recursive
   on ``inner_effect`` for the combinator; flat list-of-strings for
   the leaf). The nested-``Sequence``-as-leaf arm (sibling of the
   top-level ``Sequence`` dispatcher) ensures a ``Sequence``
   appearing as a child of another composer (the Weftwalking
   ``ConditionalIfCastFromHand.inner_effect`` shape) round-trips
   byte-equal — without it the composer-wrapping-Sequence shape
   would bail with ``None`` at the leaf walker.

6. **Cycle 2 INVERTED closure marker — Weftwalking NOW ADMITS at the
   safe-trigger recognizer.** Originally a substrate-only "stays
   declined" invariant; Cycle 2 (2026-05-24) inverted it to assert
   the structured safe-dict round-trip
   (``test_weftwalking_now_admits_at_safe_trigger_recognizer_post_
   cycle_2``). The recognizer's effect-class chain now admits the
   canonical Weftwalking ETB shape — ``ConditionalIfCastFromHand``
   whose ``inner_effect`` is the EXACT
   ``Sequence(ShuffleZonesIntoLibrary(zones=('hand','graveyard')),
   DrawCards(amount=7))`` composite. The surgical-widen §2 teeth
   keep the arm Weftwalking-scoped (any other inner shape stays
   declined). A sibling Cycle 2 pin
   (``test_weftwalking_now_admits_at_loader_admit_gate_post_
   cycle_2``) closes the printing-level admit gate via the new
   ``_printing_is_bridge_simple_enchantment`` arm. Inversion-
   discipline mirror of today's CH C2 pin
   ``test_codecracker_hound_now_admits_at_admit_gate_post_cycle_2``
   (commit ``278992d7``) + AV C2 pin
   ``test_anticausal_vestige_now_admits_at_admit_gate_post_cycle_2``
   (commit ``c32f07f9``).

7. **Covered-set membership.** Both ``conditional_if_cast_from_hand``
   and ``shuffle_zones_into_library`` kinds round-trip Rust's
   ``parse_effect`` for use within a triggered_ability — the per-
   trigger-kind smoke that the Rust parser knows the two new kinds
   (mirrors the BLOCKED-BRIDGE-ARM ``test_rust_parser_accepts_*``
   shape).

**Verify-first findings recorded in this module.**

* **Weftwalking is an Enchantment (``card_types == ('Enchantment',)``),
  NOT a Creature.** The admit gate Cycle 2 will need is therefore an
  enchantment-side admit path (or a generalized
  enchantment-safe-trigger gate), NOT the warp-creature arm AV C2
  widened. The exact gate is a cycle-2-verify-first question — at
  this slice's HEAD there is no ``_printing_is_bridge_simple_
  enchantment`` arm; the closest sibling is
  ``_printing_is_bridge_simple_cast_restriction_enchantment``
  (Phase-4 cast-restriction shape — does NOT match Weftwalking's
  ETB-trigger shape). Cycle 2 may need a fresh enchantment-side
  admit arm OR the safe-trigger gate may be type-agnostic at the
  per-trigger level (a sibling of CH/AV which both ride per-trigger
  gates on creature-typed sources). This invariant pin asserts the
  rejection at the per-trigger ``_python_ta_to_safe_dict`` level so
  Cycle 2's gate-arm choice stays open.

* **Weftwalking has NO warp_cost (``warp_cost_str == ""``).** The
  warp-arm admit gate ``_printing_is_bridge_pure_warp_creature``
  positively rejects Weftwalking by warp_cost absence — even if the
  recognizer were widened, the warp arm would not admit. Cycle 3's
  per-card probe is therefore the normal-cast lifecycle alone (no
  warp-cast lifecycle probe — the AV C3 ``_WARP_CARDS`` bump pattern
  is structurally inapplicable to Weftwalking).
"""

from __future__ import annotations

import pytest


def test_parser_weftwalking_printed_form_parses_to_composite():
    """Pin #1 — parser SoT.

    Weftwalking's printed ETB trigger parses to the exact composite::

        TriggeredAbility(
            event=Event.ENTERS,
            predicate=IsSelf(),
            effect=ConditionalIfCastFromHand(
                inner_effect=Sequence(
                    ShuffleZonesIntoLibrary(zones=('hand', 'graveyard')),
                    DrawCards(amount=7),
                )
            ),
        )

    Phrase mapping: ``"you cast it"`` ->
    ``ConditionalIfCastFromHand(inner_effect=inner)`` at
    ``cards/parser/triggers.py:1462``; the inner
    ``ShuffleZonesIntoLibrary`` builder at
    ``cards/parser/effects.py:4823``. Pre-existing on main; pinned
    here to guard against parser drift while the new Rust substrate
    lands.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ConditionalIfCastFromHand, Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.zone_moves import ShuffleZonesIntoLibrary
    from mtg_bot.effects.predicates import Event, IsSelf

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")

    assert len(w.triggered_abilities) == 1, (
        "Weftwalking must have exactly 1 triggered ability "
        "(the ENTERS+IsSelf+ConditionalIfCastFromHand(Sequence(...)) "
        "ETB)"
    )
    (ta,) = w.triggered_abilities
    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, ConditionalIfCastFromHand)
    inner = ta.effect.inner_effect
    assert isinstance(inner, Sequence), (
        f"Weftwalking's ConditionalIfCastFromHand.inner_effect must "
        f"be a Sequence; got {type(inner).__name__}"
    )
    assert len(inner.effects) == 2
    shuffle, draw = inner.effects
    assert isinstance(shuffle, ShuffleZonesIntoLibrary)
    assert tuple(shuffle.zones) == ("hand", "graveyard"), (
        f"ShuffleZonesIntoLibrary zones must be ('hand', 'graveyard'); "
        f"got {shuffle.zones!r}"
    )
    assert isinstance(draw, DrawCards)
    assert int(draw.amount) == 7


def test_rust_parser_accepts_conditional_if_cast_from_hand_in_triggered_ability():
    """Pin #2 — Rust round-trip — ConditionalIfCastFromHand combinator.

    A synthetic carrier with the recursive
    ``{"kind": "conditional_if_cast_from_hand", "inner": {"kind":
    "draw_cards", "amount": 7}}`` triggered-ability dict registers on
    Rust's ``parse_effect`` and round-trips through
    ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }`` —
    the recursive-combinator parity discipline (sibling of ``MayDo`` /
    ``IfYouDo`` / ``ConditionalIfSourcePowerAtLeast``).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Weftwalking Cycle 1 Substrate Pin -- "
            "ConditionalIfCastFromHand carrier"
        ),
        "card_types": ["Enchantment"],
        "mana_cost": {"U": 2, "generic": 4},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "conditional_if_cast_from_hand",
                    "inner": {"kind": "draw_cards", "count": 7},
                },
            }
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_shuffle_zones_into_library_in_triggered_ability():
    """Pin #3 — Rust round-trip — ShuffleZonesIntoLibrary leaf.

    A synthetic carrier with the flat ``{"kind":
    "shuffle_zones_into_library", "zones": ["hand", "graveyard"]}``
    triggered-ability dict registers on Rust's ``parse_effect`` and
    round-trips through ``Effect::ShuffleZonesIntoLibrary { zones:
    Vec<String> }`` — the flat-leaf parity discipline (sibling of
    ``draw_cards`` / ``deal_damage`` flat shapes).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Weftwalking Cycle 1 Substrate Pin -- "
            "ShuffleZonesIntoLibrary carrier"
        ),
        "card_types": ["Enchantment"],
        "mana_cost": {"U": 2, "generic": 4},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "shuffle_zones_into_library",
                    "zones": ["hand", "graveyard"],
                },
            }
        ],
    })
    assert isinstance(pid, int)


def test_bridge_arm_round_trips_conditional_if_cast_from_hand():
    """Pin #4a — cross-engine bridge round-trip (recursive combinator).

    The bridge arm ``cross_engine._ta_dict_to_python_effect`` consumes
    the recursive ``{"kind": "conditional_if_cast_from_hand", "inner":
    {...}}`` dict and yields the Python
    ``ConditionalIfCastFromHand(inner_effect=<recursed>)`` instance.
    Field-name translation seam: Rust ``inner`` <-> Python
    ``inner_effect``.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.combinators import ConditionalIfCastFromHand
    from mtg_bot.effects.generic.draw_mill import DrawCards

    rt = _ta_dict_to_python_effect({
        "kind": "conditional_if_cast_from_hand",
        "inner": {"kind": "draw_cards", "count": 7},
    })
    assert isinstance(rt, ConditionalIfCastFromHand), (
        f"Bridge round-trip must yield ConditionalIfCastFromHand; "
        f"got {type(rt).__name__}"
    )
    assert isinstance(rt.inner_effect, DrawCards)
    assert int(rt.inner_effect.amount) == 7


def test_bridge_arm_round_trips_shuffle_zones_into_library():
    """Pin #4b — cross-engine bridge round-trip (flat leaf).

    The bridge arm ``cross_engine._ta_dict_to_python_effect`` consumes
    the flat ``{"kind": "shuffle_zones_into_library", "zones": [...]}``
    dict and yields the Python ``ShuffleZonesIntoLibrary(zones=(...))``
    instance with the zone list converted to a tuple.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.zone_moves import ShuffleZonesIntoLibrary

    rt = _ta_dict_to_python_effect({
        "kind": "shuffle_zones_into_library",
        "zones": ["hand", "graveyard"],
    })
    assert isinstance(rt, ShuffleZonesIntoLibrary), (
        f"Bridge round-trip must yield ShuffleZonesIntoLibrary; "
        f"got {type(rt).__name__}"
    )
    assert tuple(rt.zones) == ("hand", "graveyard"), (
        f"Bridge round-trip zones must be ('hand', 'graveyard'); "
        f"got {rt.zones!r}"
    )


def test_reverse_serializer_round_trips_weftwalking_composite():
    """Pin #5 — reverse-serializer leaves + nested-Sequence-as-leaf.

    The full Weftwalking ETB composite (the parser SoT in Pin #1)
    round-trips through the reverse serializer leaves —
    ``ConditionalIfCastFromHand`` recurses on ``inner_effect``,
    nested ``Sequence`` recurses into each child via the
    nested-Sequence-as-leaf arm, ``ShuffleZonesIntoLibrary`` emits a
    flat list-of-strings, ``DrawCards`` emits the canonical flat
    leaf. The emitted dict is exactly the shape Rust consumes.
    """
    # Reuse the active source's parsed composite — verify-first.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")
    (ta,) = w.triggered_abilities
    # The reverse serializer's leaf walker is the same for both
    # spell-effect and triggered-ability-effect entry points (the
    # serializer's per-class arms gate on isinstance, not on the
    # callsite). Reuse _python_spell_effect_to_dict as the convenient
    # entry point — it dispatches to the same _leaf walker the new
    # ConditionalIfCastFromHand / ShuffleZonesIntoLibrary arms live
    # in.
    d = _python_spell_effect_to_dict(ta.effect)
    assert d == {
        "kind": "conditional_if_cast_from_hand",
        "inner": {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "shuffle_zones_into_library",
                    "zones": ["hand", "graveyard"],
                },
                {"kind": "draw_cards", "count": 7},
            ],
        },
    }, (
        f"Reverse serializer must emit the canonical Weftwalking "
        f"composite dict; got {d!r}"
    )


def test_weftwalking_now_admits_at_safe_trigger_recognizer_post_cycle_2():
    """Pin #6 — Cycle 2 INVERTED closure marker: Weftwalking NOW ADMITS.

    **INVERSION (Cycle 2 — 2026-05-24).** The Cycle-1 substrate landed
    with this pin asserting ``_python_ta_to_safe_dict(ta) is None``;
    Cycle 2 (this slice) widens the recognizer to admit the canonical
    Weftwalking ETB shape (the 10th ENTERS+IsSelf safe-trigger leaf —
    ``conditional_if_cast_from_hand`` with the narrow
    ``Sequence(ShuffleZonesIntoLibrary(zones=('hand','graveyard')),
    DrawCards(amount=7))`` inner). This inverted pin asserts the
    closure: the recognizer NOW returns the structured safe-dict for
    Weftwalking's parsed ETB trigger.

    **Inversion-discipline mirror.** Same INVERT-the-C1-substrate-pin
    pattern as today's CH C2 pin
    ``test_codecracker_hound_now_admits_at_admit_gate_post_cycle_2``
    (commit ``278992d7``) + AV C2 pin
    ``test_anticausal_vestige_now_admits_at_admit_gate_post_cycle_2``
    (commit ``c32f07f9``) — each multi-cycle closure inverts its C1
    substrate-only invariant into a C2 closure marker.

    **The structured safe-dict's exact shape** (the §2 round-trip
    teeth — any drift in field names or nesting catches here):
        ``{"event": "enters",
           "predicate": {"kind": "source_is_self"},
           "effect": {"kind": "conditional_if_cast_from_hand",
                      "inner": {
                          "kind": "sequence",
                          "effects": [
                              {"kind": "shuffle_zones_into_library",
                               "zones": ["hand", "graveyard"]},
                              {"kind": "draw_cards", "count": 7},
                          ],
                      }}}``

    The recognizer's effect-class arm gates on the EXACT canonical
    Weftwalking inner — any other ``ConditionalIfCastFromHand`` inner
    shape falls through to the filter drop path (the surgical-widen
    §2 silent-mistranslation teeth). The dict-shape round-trip
    (``_is_safe_trigger_dict``) is exercised by the same gate the
    Creature arm uses; the bridge round-trip (forward via
    ``cross_engine._ta_dict_to_python_effect`` + reverse via
    ``trajectory._python_ta_effect_to_dict``) is pinned by Pin #5
    (recursive + nested-Sequence-as-leaf round-trip).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")
    (ta,) = w.triggered_abilities
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "conditional_if_cast_from_hand",
            "inner": {
                "kind": "sequence",
                "effects": [
                    {
                        "kind": "shuffle_zones_into_library",
                        "zones": ["hand", "graveyard"],
                    },
                    {"kind": "draw_cards", "count": 7},
                ],
            },
        },
    }, (
        "Weftwalking's ENTERS+IsSelf+ConditionalIfCastFromHand "
        "trigger MUST be ADMITTED by the safe-trigger recognizer "
        "post-Cycle-2 (the recognizer's effect-class arm gates on "
        "the EXACT canonical Weftwalking inner shape and emits the "
        f"structured safe-dict). Got: {d!r}"
    )


def test_weftwalking_now_admits_at_loader_admit_gate_post_cycle_2():
    """**Cycle 2 admit-gate closure marker.** Weftwalking now passes
    the new ``_printing_is_bridge_simple_enchantment`` admit arm —
    the Enchantment-side sibling of the Creature admit arms wired in
    the same C2 slice. Sibling pin to the recognizer-flip pin above:
    this one pins the printing-level admit gate, the one above pins
    the per-trigger recognizer the admit arm consults.

    **Defensive cross-checks** (mirror the AV/CH C2 admit-pin shape):
      * ``_printing_is_bridge_simple_enchantment(w) is True`` — the
        new C2 arm admits.
      * ``_printing_is_bridge_simple_creature(w) is False`` — the
        Creature arm still rejects (Weftwalking is Enchantment-only,
        no power/toughness — the verify-first refinement from
        ``test_weftwalking_is_an_enchantment_not_a_creature``).
      * ``_printing_is_bridge_simple_cast_restriction_enchantment(w)
        is False`` — the sibling Enchantment arm still rejects
        (Weftwalking carries no ``restricts_noncreature_spells_to_
        one_per_turn`` flag; the two Enchantment-side arms are
        mutually exclusive by construction).
      * ``_printing_is_bridge_pure_warp_creature(w) is False`` — the
        warp arm still rejects (Weftwalking has no ``warp_cost`` —
        the verify-first refinement from
        ``test_weftwalking_verify_first_warp_cost_absent``).

    **Loader-end-to-end closure marker.** The
    ``_filter_deck_to_bridge_supported`` disjunct chain consulted by
    ``production_deck_to_deckspec`` now admits Weftwalking; a deck
    containing Weftwalking will materialize it as a CardDef on both
    engines instead of silently dropping it. The C3 per-card real-
    EoE byte-equality probe (normal-cast lifecycle only —
    Weftwalking has no warp_cost) will exercise the materialized
    CardDef end-to-end.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _printing_is_bridge_simple_enchantment,
        _printing_is_bridge_simple_cast_restriction_enchantment,
        _printing_is_bridge_pure_warp_creature,
    )

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")
    assert _printing_is_bridge_simple_enchantment(w) is True, (
        "Weftwalking must be ADMITTED by the new C2 "
        "_printing_is_bridge_simple_enchantment arm post-Cycle-2."
    )
    # Defensive cross-checks — the §2 mutual-exclusion teeth.
    assert _printing_is_bridge_simple_creature(w) is False, (
        "Weftwalking is an Enchantment (NOT a Creature) — the "
        "Creature admit arm must still reject; the C2 admit gate "
        "is the new Enchantment-side arm, NOT a Creature widen."
    )
    assert _printing_is_bridge_simple_cast_restriction_enchantment(w) is False, (
        "Weftwalking carries no restricts_noncreature_spells_to_one_"
        "per_turn flag — the sibling cast-restriction-enchantment "
        "arm must still reject (the two Enchantment-side arms are "
        "mutually exclusive by construction)."
    )
    assert _printing_is_bridge_pure_warp_creature(w) is False, (
        "Weftwalking has no warp_cost — the warp arm must still "
        "reject (the verify-first refinement was the load-bearing "
        "evidence that the C2 admit gate is the Enchantment-side "
        "arm, NOT the warp arm AV/CH/MTL rode)."
    )


def test_weftwalking_verify_first_warp_cost_absent():
    """Verify-first refinement pinned for the cycle-3 deliverable
    shape: Weftwalking has NO warp_cost (``warp_cost_str == ""``).

    The warp-arm admit gate ``_printing_is_bridge_pure_warp_creature``
    positively rejects Weftwalking by warp_cost absence. Cycle 3's
    per-card probe is therefore the normal-cast lifecycle alone — the
    AV C3 ``_WARP_CARDS`` bump pattern is STRUCTURALLY INAPPLICABLE
    to Weftwalking. Pinned here so the refined Cycle-3 deliverable
    shape (per the worker-report) is grounded in HEAD truth, not the
    rescout's hypothesized "warp-cast lifecycle" verb.
    """
    from mtg_bot.cards.source import get_active_source

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")
    assert w.warp_cost_str == "", (
        f"Verify-first: Weftwalking's warp_cost_str must be empty "
        f"(no warp cost — the rescout's hypothesized warp-cast "
        f"lifecycle probe is structurally inapplicable); got "
        f"{w.warp_cost_str!r}"
    )
    # The mana_cost stays the canonical {4}{U}{U}.
    assert w.mana_cost_str == "{4}{U}{U}", (
        f"Verify-first: Weftwalking's mana_cost_str must be "
        f"'{{4}}{{U}}{{U}}'; got {w.mana_cost_str!r}"
    )


def test_weftwalking_is_an_enchantment_not_a_creature():
    """Verify-first refinement pinned for the cycle-2 deliverable
    shape: Weftwalking is an Enchantment, NOT a Creature.

    The admit gate Cycle 2 will need is therefore an enchantment-side
    admit path (or a generalized enchantment-safe-trigger gate), NOT
    the warp-creature arm AV C2 widened. The exact gate is a
    cycle-2-verify-first question — at this slice's HEAD there is no
    ``_printing_is_bridge_simple_enchantment`` arm; the closest
    sibling is ``_printing_is_bridge_simple_cast_restriction_
    enchantment`` (Phase-4 cast-restriction shape — does NOT match
    Weftwalking's ETB-trigger shape). Pinned here so the refined
    Cycle-2 deliverable shape (per the worker-report) is grounded
    in HEAD truth, not the rescout's hypothesized "10th
    ENTERS+IsSelf safe-trigger leaf" verb (which would imply the
    creature-side gate AV/CH ride).
    """
    from mtg_bot.cards.source import get_active_source

    src = get_active_source().get_printings()
    w = src.get("Weftwalking")
    if w is None:
        pytest.skip("Weftwalking absent from active CardSource")
    assert "Enchantment" in w.card_types, (
        f"Weftwalking must carry 'Enchantment' in card_types; got "
        f"{w.card_types!r}"
    )
    assert "Creature" not in w.card_types, (
        f"Weftwalking must NOT carry 'Creature' in card_types — the "
        f"Cycle 2 admit gate must NOT be the creature-side warp arm; "
        f"got {w.card_types!r}"
    )


def test_unknown_effect_kind_error_includes_both_new_kinds():
    """Pin #7 — covered-set membership smoke. Both new effect kinds
    appear in Rust's ``parse_effect`` "unknown effect kind" error
    message (the per-kind enumerator). A negative test that registers
    a printing with a kind PRESENT in the enumerator but mis-spelled
    by one character lands a clear "unknown effect kind" with the
    enumerator including the two new spellings.
    """
    import mtg_bot_engine
    import pytest as _pytest

    reg = mtg_bot_engine.Registry()
    with _pytest.raises(Exception) as ei:
        reg.register_printing({
            "name": "weftwalking C1 substrate -- enumerator probe",
            "card_types": ["Enchantment"],
            "mana_cost": {"U": 2, "generic": 4},
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    # Deliberately misspelled — but the error message
                    # must list both new substrate kinds among the
                    # valid spellings (the per-kind enumerator).
                    "effect": {"kind": "conditional_if_cast_from_hands"},
                }
            ],
        })
    msg = str(ei.value)
    assert "conditional_if_cast_from_hand" in msg, (
        "parse_effect enumerator must include "
        "'conditional_if_cast_from_hand' (the new wrap kind)"
    )
    assert "shuffle_zones_into_library" in msg, (
        "parse_effect enumerator must include "
        "'shuffle_zones_into_library' (the new leaf kind)"
    )
