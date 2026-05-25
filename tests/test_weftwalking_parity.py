"""Weftwalking Cycle 3 -- per-card real-EoE cross-engine byte-
equality probe (PROBED tier flip).

Weftwalking is a ``{4}{U}{U}`` Enchantment (EoE -- sourced from
``data/edge_of_eternities.json``) with an ENTERS+IsSelf triggered
ability::

    "When this enchantment enters, if you cast it, shuffle your hand
    and graveyard into your library, then draw seven cards."

Parsed composite at HEAD (pinned by the C1 substrate)::

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

This module is the **load-bearing PROBED-tier flip evidence** for
Weftwalking after the multi-cycle DECLINED -> ADMITTED transition
(sibling mirror of Codecracker Hound C3 commit ``6f99bf45`` +
Anticausal Vestige C3 commit ``a9001390``):

  * **Cycle 1 (substrate, commits ``61f04bef`` + ``d18bb3a4``,
    2026-05-23/24)** wired the two new Rust Effect variants --
    ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
    (recursive combinator) + ``Effect::ShuffleZonesIntoLibrary
    { zones: Vec<String> }`` (flat leaf) -- with parse / to_pydict /
    resolve arms + cross-engine bridge arms in
    ``cross_engine._ta_dict_to_python_effect`` + reverse-serializer
    leaves in ``parity/trajectory.py`` (incl. the nested-Sequence-
    as-leaf arm so the composer-wrapping-Sequence shape round-trips).
    Weftwalking STAYED DECLINED at the admit gate post-Cycle-1 --
    the safe-trigger recognizer ``_python_ta_to_safe_dict`` rejected
    the ``ConditionalIfCastFromHand`` effect (not in the safe-effect
    allowlist; the wrap was new vocabulary).
  * **Cycle 2 (admit widen, commit ``0017d9c1``, 2026-05-24)** wired
    the 10th ``ENTERS+IsSelf`` safe-trigger leaf
    (``conditional_if_cast_from_hand``) with the EXACT canonical
    Weftwalking inner gate (``Sequence(ShuffleZonesIntoLibrary(
    zones=('hand','graveyard')), DrawCards(amount=7))``) -- the
    surgical-widen Sec-2 teeth. Added the ``("enters",
    "source_is_self", "conditional_if_cast_from_hand")``
    ``_SAFE_TRIGGERS`` triple + the
    ``_SAFE_EFFECT_KEYS["conditional_if_cast_from_hand"]
    = frozenset({"kind","inner"})`` whitelist + a new
    ``_printing_is_bridge_simple_enchantment`` admit arm (the
    Enchantment-side sibling of ``_printing_is_bridge_simple_creature``
    -- a fresh arm rather than extending the Creature arm because
    the latter cascades through Creature-specific downstream
    assumptions). Weftwalking flipped DECLINED -> ADMITTED at the
    new Enchantment-side admit gate (single-card FLIP, no silent
    auto-grows -- Weftwalking is the SOLE
    ``ConditionalIfCastFromHand`` carrier system-wide).
  * **Cycle 3 (this lane)** ships the GENUINE real-EoE cross-engine
    byte-equality probe that flips Weftwalking
    ``covered_by_construction`` -> PROBED in the pool-parity metric.
    Same shape + same strength bar as the recent per-card parity
    probes (``test_codecracker_hound_parity.py``,
    ``test_anticausal_vestige_parity.py``,
    ``test_memorial_team_leader_parity.py``,
    ``test_possibility_technician_parity.py``,
    ``test_boilerbilges_ripper_parity.py``).

**Normal-cast lifecycle ONLY -- no warp-cast lifecycle.** Weftwalking
has ``warp_cost_str == ""`` (verify-first pinned by the C1 substrate
module's ``test_weftwalking_verify_first_warp_cost_absent``); the
warp-cast lifecycle is STRUCTURALLY INAPPLICABLE. The AV C3
``_WARP_CARDS`` bump pattern is intentionally NOT followed here.

**Probe avoids the no-real-cast-path-for-Enchantments gap.** Rust's
high-level ``Action::CastSpell`` dispatch (state_ops_actions.rs)
routes non-Creature Enchantments through a cascade of cast
primitives -- ``cast_aura`` (false, no aura subtype),
``cast_spell_noncreature`` (false, "is_spell" gate requires
Instant/Sorcery -- see state_ops_cast.rs:1646-1657), then
``cast_creature`` (false, not Creature). A live ``cast_spell``
dispatch on Weftwalking silently no-ops on Rust. To exercise the
ETB trigger body byte-equal we therefore mirror the established
Warp-keyword-card-probe convention (Possibility Technician /
Boilerbilges Ripper / Codecracker Hound): pre-seat Weftwalking
directly on the battlefield via ``register_and_inject_object``
(Rust) and the matching ``new_object(zone=BATTLEFIELD)`` +
``battlefield.append`` (Python) -- bypassing the cost-payment +
type-dispatch machinery -- then fire the ETB trigger explicitly
(``push_to_stack`` -> ``resolve_top_of_stack`` on Rust;
``dispatch_event(Event.ENTERS, obj=ww)`` + ``resolve_top_of_stack``
on Python). Both engines reach the SAME post-resolve state under
the documented degradation.

**Documented ConditionalIfCastFromHand always-run-inner resolve
degradation (combinators.py:1518-1536).** ``state.resolving_source.
cast_via_hand`` is consulted at resolve time, BUT that flag is
cleared in ``put_into_battlefield`` after the cast-from-hand-only
ETB replacements but BEFORE ETB triggers fire. The trigger fires
after the flag is consumed; both engines degrade to "always run the
inner effect" (matching the bespoke ``WeftwalkingETBEffect`` it
replaces). Python's
``ConditionalIfCastFromHand.resolve`` (combinators.py:1549-1559)
unconditionally calls ``self.inner_effect.resolve(...)``; Rust's
``Effect::ConditionalIfCastFromHand`` arm at
state_ops_resolve.rs:17061-17063 unconditionally calls
``apply_effect(state, inner, source_obj_id)``. This probe exercises
both engines through that documented-degradation path; the gate is
structurally a no-op today (and will continue to be until a future
engine grows a persistent "this-permanent-was-cast-as-a-spell"
provenance flag -- a future-engine concern, not a parity-divergence
this probe needs to defend against).

**Resolve semantics -- Sequence(ShuffleZonesIntoLibrary(hand+
graveyard), DrawCards(7)) cross-engine.** Both engines:

  * Python: ``ShuffleZonesIntoLibrary.resolve`` at
    ``effects/generic/zone_moves.py:423-448`` moves every card in
    p0's hand into p0's library (zone-stamping each), clears the
    hand, then moves every card in p0's graveyard into p0's
    library, clears the graveyard, then calls ``shuffle_library``
    (which delegates to ``state.rng.shuffle``). Then the next
    ``Sequence`` step ``DrawCards(amount=7)`` draws 7 cards from
    the top of the now-shuffled library.
  * Rust: ``Effect::ShuffleZonesIntoLibrary`` at
    ``state_ops_resolve.rs:17108-17170`` does the same step-for-
    step (mirror documented at the resolve arm), then ``DrawCards``
    draws 7. When an external Python ``random.Random`` is installed
    via ``set_external_rng``, Rust's xorshift64 fallback is
    bypassed in favor of the shared Python RNG, producing
    byte-identical Fisher-Yates shuffle output to Python's
    ``state.rng.shuffle`` (the established ``set_external_rng`` ->
    ``_randbelow`` Fisher-Yates parity pattern -- mirrors round-54's
    cross-engine shuffle harness shape).

**Library setup.** p0 starts with 2 cards in hand + 3 cards in
graveyard + 12 vanilla-instant filler cards in library (top-to-
bottom). After the trigger fires + resolves: hand + graveyard
contents merge into the library (now 2+3+12=17 cards), library
shuffles under the shared Python RNG, then 7 cards are drawn into
hand. Post-state: hand has exactly 7 cards (same cards on both
engines under shared RNG), graveyard is empty, library has exactly
10 cards (same order on both engines). Weftwalking itself stays on
the battlefield.
"""

from __future__ import annotations

import importlib.util
import pathlib
import random
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import (
    ConditionalIfCastFromHand,
    Sequence,
)
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.effects.generic.zone_moves import ShuffleZonesIntoLibrary


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built -- mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    ``test_codecracker_hound_parity.py`` /
    ``test_possibility_technician_parity.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Zone constants (mirror Rust's u8 zone IDs used by
# ``register_and_inject_object``).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# Canonical Weftwalking dict shape consumed by Rust's
# ``register_and_inject_object`` to build a synthetic carrier with the
# same ENTERS+IsSelf+ConditionalIfCastFromHand(Sequence(...)) triggered
# ability as the real parsed printing. The ETB effect dict shape
# mirrors what the C1 substrate's reverse serializer emits + what the
# bridge round-trip pin asserts (see Pin #2 below).
_WW_PRINTING_DICT: dict = {
    "name": "Weftwalking (synthetic carrier)",
    "card_types": ["Enchantment"],
    "mana_cost": {"generic": 4, "U": 2},
    "triggered_abilities": [
        {
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
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Weftwalking is parser-claimed and emits the
# expected ENTERS+IsSelf+ConditionalIfCastFromHand(Sequence(
# ShuffleZonesIntoLibrary(hand+graveyard), DrawCards(7))) trigger
# shape. Sibling-mirror of CH C3 Pin (1) /AV C3 Pin (1) shape;
# duplicates the C1 substrate module's Pin #1 for self-containment.
# ---------------------------------------------------------------------------


def test_weftwalking_parser_claims_card():
    assert "Weftwalking" in _PRINTINGS, (
        "Weftwalking must be parser-claimed by the active CardSource"
    )


def test_weftwalking_printed_attrs():
    """Pins the basic printing surface (cost, type, no warp cost, no
    P/T -- Weftwalking is a non-Creature Enchantment).

    Verify-first against the live ``data/edge_of_eternities.json``:
    Weftwalking is a ``{4}{U}{U}`` Enchantment (NOT Creature, NOT
    Aura). The ``warp_cost_str == ""`` invariant is what makes the
    warp-cast lifecycle structurally inapplicable (the AV C3
    ``_WARP_CARDS`` bump pattern does not apply -- this probe ships
    the normal-cast lifecycle alone)."""
    p = _PRINTINGS["Weftwalking"]
    assert p.mana_cost_str == "{4}{U}{U}"
    # No warp cost -- warp-cast lifecycle structurally inapplicable.
    assert p.warp_cost_str == "", (
        "Verify-first: Weftwalking carries no warp_cost. If this "
        "regresses, the warp-cast lifecycle probe pattern (AV C3 "
        "``_WARP_CARDS`` bump) becomes structurally applicable and "
        "this module should be extended."
    )
    assert "Enchantment" in p.card_types
    assert "Creature" not in p.card_types
    assert "Aura" not in p.subtypes
    # Non-Creature Enchantments have no P/T -- the §2 gate the C2
    # ``_printing_is_bridge_simple_enchantment`` arm consults.
    assert p.power is None
    assert p.toughness is None


def test_weftwalking_etb_trigger_emits_canonical_composite():
    """The parser emits Weftwalking's parsed ENTERS+IsSelf trigger as
    the canonical
    ``ConditionalIfCastFromHand(inner_effect=Sequence(
    ShuffleZonesIntoLibrary(zones=('hand','graveyard')),
    DrawCards(amount=7)))`` composite -- the EXACT shape the C2
    safe-trigger recognizer admit gate accepts (any other inner
    shape stays declined under the surgical-widen §2 teeth). Pin
    the shape here so parser drift surfaces immediately rather than
    silently downstream in the cross-engine probe.
    """
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Weftwalking"]
    assert len(p.triggered_abilities) == 1, (
        f"Weftwalking must have exactly 1 triggered ability; got "
        f"{len(p.triggered_abilities)}"
    )
    (ta,) = p.triggered_abilities
    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, ConditionalIfCastFromHand), (
        f"ETB effect must be ConditionalIfCastFromHand; got "
        f"{type(ta.effect).__name__}"
    )
    inner = ta.effect.inner_effect
    assert isinstance(inner, Sequence), (
        f"ConditionalIfCastFromHand.inner_effect must be a Sequence; "
        f"got {type(inner).__name__}"
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


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the dict shape Weftwalking's safe-trigger
# recognizer emits round-trips to the matching Python composite. (C1
# substrate Pin #4a/b/#5 + C2 inverted Pin #6 are duplicated here so
# the per-card module is self-contained for the PROBED-tier evidence.)
# ---------------------------------------------------------------------------


def test_weftwalking_safe_trigger_bridge_round_trip():
    """The bridge dict shape emitted by ``_python_ta_to_safe_dict``
    for Weftwalking's ENTERS+IsSelf+ConditionalIfCastFromHand(
    Sequence(...)) trigger reconstructs the matching Python composite
    -- the load-bearing round-trip the C2 admit widen depends on."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = _PRINTINGS["Weftwalking"]
    (ta,) = p.triggered_abilities
    d = trajectory._python_ta_to_safe_dict(ta)
    assert d is not None, (
        "Weftwalking's ENTERS+IsSelf+ConditionalIfCastFromHand "
        "trigger must be classified as a safe-dict by "
        "_python_ta_to_safe_dict (the C2 widen)"
    )
    # The exact bare canonical safe-dict pinned at the C2 substrate's
    # recognizer admit pin (Pin #6 INVERTED).
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
        f"Weftwalking's safe-dict shape must be the canonical "
        f"composite; got {d!r}"
    )
    # Forward bridge dict -> Python: reconstructs the matching Python
    # composite (recursive into the inner Sequence and its two leaves).
    rt = _ta_dict_to_python_effect(d["effect"])
    assert rt == ConditionalIfCastFromHand(
        inner_effect=Sequence(effects=(
            ShuffleZonesIntoLibrary(zones=("hand", "graveyard")),
            DrawCards(amount=7),
        )),
    ), (
        f"Bridge dict->Python round-trip must yield the canonical "
        f"Weftwalking composite; got {rt!r}"
    )
    assert rt == ta.effect, (
        "Bridge round-trip must equal the parser-emitted effect "
        "(structural byte-equality contract)"
    )


# ---------------------------------------------------------------------------
# (3) Admit-gate flip pin -- Weftwalking passes the C2
# _printing_is_bridge_simple_enchantment arm at HEAD. Sibling to MTL
# C2's test_memorial_team_leader_phase4_admit_predicate_fires shape;
# duplicates the C2 substrate module's
# test_weftwalking_now_admits_at_loader_admit_gate_post_cycle_2 for
# self-containment in this per-card probe module.
# ---------------------------------------------------------------------------


def test_weftwalking_passes_c2_enchantment_admit_gate():
    """**Verify-first guard.** The genuine live Weftwalking printing
    at HEAD positively admits via the new C2
    ``_printing_is_bridge_simple_enchantment`` disjunct AND positively
    rejects under every other Enchantment-or-warp admit predicate.
    Catches predicate drift before any downstream byte-equal probe
    runs."""
    from mtg_bot.parity import trajectory

    w = _PRINTINGS["Weftwalking"]
    # The C2 Enchantment-side admit arm fires.
    assert trajectory._printing_is_bridge_simple_enchantment(w) is True, (
        "Weftwalking must be admitted by the new C2 "
        "_printing_is_bridge_simple_enchantment arm at HEAD."
    )
    # Defensive cross-checks -- the §2 mutual-exclusion teeth.
    assert trajectory._printing_is_bridge_simple_creature(w) is False, (
        "Weftwalking is an Enchantment (NOT a Creature) -- the "
        "Creature arm must still reject."
    )
    assert (
        trajectory._printing_is_bridge_simple_cast_restriction_enchantment(w)
        is False
    ), (
        "Weftwalking carries no restricts_noncreature_spells_to_one_"
        "per_turn flag -- the sibling cast-restriction-enchantment "
        "arm must still reject (the two Enchantment arms are mutually "
        "exclusive by construction)."
    )
    assert trajectory._printing_is_bridge_pure_warp_creature(w) is False, (
        "Weftwalking has no warp_cost -- the warp arm must still "
        "reject. If this regresses, the warp-cast lifecycle becomes "
        "structurally applicable and this module should be extended."
    )


# ---------------------------------------------------------------------------
# (4) Rust synthetic-carrier sanity -- the Rust parser accepts the
# bridged trigger dict shape for the synthetic carrier the cross-
# engine probe uses.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_weftwalking_synthetic_dict():
    """Lockstep pin: Rust's parse_effect arm accepts the canonical
    Weftwalking ETB dict shape on the synthetic carrier. Mirrors the
    C1 substrate module's
    ``test_rust_parser_accepts_conditional_if_cast_from_hand_in_
    triggered_ability`` + ``test_rust_parser_accepts_shuffle_zones_
    into_library_in_triggered_ability`` Pins, here in the full
    Weftwalking-shape printing the cross-engine probe uses."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_WW_PRINTING_DICT)
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- drives the
# ACTUAL parsed Weftwalking printing on Python and a bridged
# synthetic carrier on Rust. After firing the ENTERS+IsSelf ETB
# trigger, asserts the concrete zone observables (hand emptied to 0
# then drawn back to 7, graveyard 3 -> 0, library 12 -> 17 -> 10
# after the shuffle + draw) plus full ``compare_fields == []`` over
# the WHOLE cross-engine field view (which under shared external RNG
# implies byte-equal hand contents + byte-equal library order
# post-shuffle).
#
# Scenario: Weftwalking pre-seated on p0's battlefield on both
# engines (via push_to_stack on Rust + manual hand->bf move +
# dispatch_event on Python -- the established Warp-keyword-card-
# probe convention from Codecracker Hound / Possibility Technician
# / Boilerbilges Ripper, applied here to a non-Creature Enchantment
# because Rust's high-level cast dispatch has no cast_enchantment
# primitive). p0 has 2 cards in hand + 3 cards in graveyard + 12
# vanilla-instant fillers in library. ENTERS fires; both engines
# resolve the ConditionalIfCastFromHand always-run-inner gate,
# then the Sequence's ShuffleZonesIntoLibrary moves hand+graveyard
# into the library (17 cards total), shuffles under the shared
# Python RNG, then DrawCards(7) draws 7 cards.
# ---------------------------------------------------------------------------


_SHARED_SHUFFLE_SEED = 20260524  # Weftwalking C3 lane date.


@_rust_skip
def test_cross_engine_real_eoe_weftwalking_etb_parity(parity_smoke):
    """**GENUINE real-EoE cross-engine probe -- Weftwalking ETB
    ConditionalIfCastFromHand(Sequence(ShuffleZonesIntoLibrary(hand+
    graveyard), DrawCards(7))) path. PROBED tier flip (Cycle 3
    closure marker -- ``covered_by_construction`` -> PROBED).**

    Python: the ACTUAL parsed Weftwalking printing pre-seated on
    p0's battlefield (no cast path -- bypasses the no-cast-primitive-
    for-Enchantment gap on Rust + the documented
    ``ConditionalIfCastFromHand``-degradation gap on both engines).
    The ENTERS+IsSelf trigger is fired by an explicit
    ``dispatch_event(Event.ENTERS, obj=ww)`` after seating. p0's hand
    has 2 vanilla instants; p0's graveyard has 3 vanilla instants;
    p0's library has 12 vanilla instants (top-to-bottom, as appended).

    Rust: bridged synthetic carrier carrying the same canonical ETB
    trigger dict; p0's hand / graveyard / library seeded identically
    with the same printing names. The synthetic-test cast-without-cost
    ``push_to_stack`` path drives the trigger (lands the trigger on
    the stack + drains it under the shared Python RNG); since
    Weftwalking is already on the battlefield via direct injection,
    the resolve immediately fires the ConditionalIfCastFromHand
    always-run-inner gate -> ShuffleZonesIntoLibrary -> DrawCards(7).

    Shared shuffle determinism: both engines drive their shuffle via
    the SAME Python ``random.Random`` -- Python through
    ``state.rng.shuffle`` (the production shuffle path) and Rust
    through ``set_external_rng`` -> ``_randbelow`` Fisher-Yates
    (round-54 cross-engine shuffle harness pattern). Without this
    the post-shuffle library order would diverge (Rust's xorshift64
    fallback != Python's Mersenne Twister) and the full
    ``compare_fields`` byte-equality contract would fail.

    Assertion strength: **full ``compare_fields == []``** over the
    WHOLE cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (p0 hand 2 -> 7 (drew 7 after
    shuffle), p0 graveyard 3 -> 0, p0 library 12 -> 10 = 12 + 2 + 3
    - 7); Weftwalking itself stays on bf on BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import dispatch_event, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.effects.predicates import Event

    real = _PRINTINGS.get("Weftwalking")
    if real is None:
        pytest.skip("Weftwalking absent from active CardSource")
    assert "Enchantment" in real.card_types
    assert "Creature" not in real.card_types

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Synthetic vanilla filler printings on the Python side (matching
    # the Rust register_and_inject_object dicts byte-for-byte). Each
    # has a unique name so the field-view per-object comparison can
    # distinguish them; ``mana_cost`` is `{U}` to align with
    # Weftwalking's blue color identity (the cards never actually get
    # cast in this probe).
    def _instant_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=(("U", 1),)),
            type_line="Instant",
            supertypes=(),
            card_types=("Instant",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # ---- Library setup: 12 vanilla fillers on both engines, ordered
    # top-to-bottom = [Lib 1, Lib 2, ..., Lib 12].
    NUM_LIB = 12
    NUM_HAND = 2
    NUM_GY = 3

    # ---- Python: seat the genuine parsed Weftwalking in p0's HAND
    # (mirrors the CH probe's pre-cast convention -- the manual
    # hand->bf move below simulates the cast-resolution zone change).
    py_ww = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_ww)

    # Seed Python's hand (2 cards) + graveyard (3 cards) + library
    # (12 cards). Hand + graveyard appended in iteration order. The
    # library is BOTTOM-FIRST (reversed range) so the per-object ID
    # allocation order matches Rust's ``register_and_inject_object``
    # convention (which we also drive bottom-first below). After
    # allocation we reverse Python's library in place so the top-to-
    # bottom order matches Rust's lib[0]=top semantics. This mirrors
    # the CH parity probe's id-alignment idiom (CH's
    # ``rs_lib_deeper`` is allocated FIRST so it has the lower id,
    # matching Python's bottom-first allocation order).
    py_hand_objs = []
    for i in range(NUM_HAND):
        obj = py.new_object(
            _instant_printing(f"WW Hand {i + 1}"),
            owner_id=0, zone=Zone.HAND,
        )
        obj.summoning_sick = False
        py.players[0].hand.append(obj)
        py_hand_objs.append(obj)

    py_gy_objs = []
    for i in range(NUM_GY):
        obj = py.new_object(
            _instant_printing(f"WW GY {i + 1}"),
            owner_id=0, zone=Zone.GRAVEYARD,
        )
        obj.summoning_sick = False
        py.players[0].graveyard.append(obj)
        py_gy_objs.append(obj)

    py_lib_objs_bottom_to_top = []
    for i in reversed(range(NUM_LIB)):
        obj = py.new_object(
            _instant_printing(f"WW Lib {i + 1}"),
            owner_id=0, zone=Zone.LIBRARY,
        )
        obj.summoning_sick = False
        py.players[0].library.append(obj)
        py_lib_objs_bottom_to_top.append(obj)
    # Reverse so the top of the library is index 0 (matches
    # Rust's lib[0]=top convention).
    py.players[0].library.reverse()

    # ---- Rust: seat the bridged synthetic Weftwalking carrier in
    # p0's HAND (mirrors the CH probe -- the ``push_to_stack`` below
    # simulates the cast and the spell-resolve path will move
    # Weftwalking from hand to bf, fire ENTERS, and queue the trigger
    # naturally; see state_ops_resolve.rs:22903-22968 where
    # ``move_source_post_resolve`` lands a permanent on bf and the
    # following ``dispatch_event(Event::Enters, ...)`` fan-out fires
    # the IsSelf trigger). Use the REAL printing's name on the Rust
    # carrier so the battlefield field-view tuple's name slot agrees
    # byte-equal with Python's actual parsed Weftwalking (post-resolve
    # it'll be on the bf with the matching name).
    ww_carrier_for_probe = dict(_WW_PRINTING_DICT)
    ww_carrier_for_probe["name"] = real.name
    rs_ww = rs.register_and_inject_object(
        ww_carrier_for_probe, 0, ZONE_HAND,
    )

    # Seed Rust's hand (2) + graveyard (3) + library (12).
    rs_hand_ids = []
    for i in range(NUM_HAND):
        rs_id = rs.register_and_inject_object(
            {
                "name": f"WW Hand {i + 1}",
                "card_types": ["Instant"],
                "mana_cost": {"U": 1},
            },
            0, ZONE_HAND,
        )
        rs_hand_ids.append(rs_id)

    rs_gy_ids = []
    for i in range(NUM_GY):
        rs_id = rs.register_and_inject_object(
            {
                "name": f"WW GY {i + 1}",
                "card_types": ["Instant"],
                "mana_cost": {"U": 1},
            },
            0, ZONE_GRAVEYARD,
        )
        rs_gy_ids.append(rs_id)

    # Library: register bottom-first so the top-to-bottom order
    # matches Python's. ``register_and_inject_object(ZONE_LIBRARY)``
    # pushes onto lib[0] (the TOP), so to build a library with
    # top-to-bottom = [Lib 1, ..., Lib 12] we register Lib 12 FIRST
    # and Lib 1 LAST (the Codecracker Hound parity probe's
    # established library-injection convention).
    rs_lib_ids_bottom_to_top = []
    for i in reversed(range(NUM_LIB)):
        rs_id = rs.register_and_inject_object(
            {
                "name": f"WW Lib {i + 1}",
                "card_types": ["Instant"],
                "mana_cost": {"U": 1},
            },
            0, ZONE_LIBRARY,
        )
        rs_lib_ids_bottom_to_top.append(rs_id)
    rs.clear_summoning_sick_for_player(0)

    # Sanity: Rust library top-to-bottom matches Python's order
    # ([Lib 1, Lib 2, ..., Lib 12]).
    rs_lib_check = [
        e["printing_name"] for e in rs.library_snapshot(0)
    ]
    py_lib_check = [o.printing.name for o in py.players[0].library]
    assert rs_lib_check == py_lib_check, (
        f"Library top-to-bottom mismatch pre-trigger; "
        f"py={py_lib_check} rs={rs_lib_check}"
    )

    # Pre-cast sanity: no stack activity from seeding. Hand contains
    # Weftwalking + NUM_HAND fillers (Weftwalking goes from hand ->
    # stack -> bf via the synthetic cast push; after the spell
    # resolves Weftwalking is on bf and the 2 fillers remain in hand
    # for the Shuffle step to consume).
    assert rs.stack_size() == 0 and len(py.stack) == 0
    assert len(py.players[0].hand) == NUM_HAND + 1
    assert len(py.players[0].graveyard) == NUM_GY
    assert len(py.players[0].library) == NUM_LIB
    assert rs.hand_sizes[0] == NUM_HAND + 1
    assert len(rs.graveyard_snapshot(0)) == NUM_GY
    assert rs.library_sizes[0] == NUM_LIB

    # ---- Shared shuffle determinism. Install the SAME-seeded Python
    # ``random.Random`` on both engines so the post-shuffle library
    # order is byte-identical. Round-54 cross-engine shuffle harness
    # pattern (test_parity_smoke.py:60134-60148): Python's
    # ``state.rng.shuffle`` consumes ``state.rng`` directly; Rust's
    # ``set_external_rng`` redirects the shuffle from the xorshift64
    # fallback to ``external_rng::next_below`` -> ``_randbelow``
    # Fisher-Yates against the supplied Python RNG, producing
    # byte-identical output to Python's ``state.rng.shuffle`` on the
    # same seed.
    py.rng = random.Random(_SHARED_SHUFFLE_SEED)
    rs.set_external_rng(random.Random(_SHARED_SHUFFLE_SEED))

    # ---- Fire the cast on BOTH engines (synthetic-test cast-
    # without-cost path). ----
    #
    # **Python.** Move Weftwalking from hand -> bf manually (the
    # cast-resolution zone change). Fire ENTERS via
    # ``dispatch_event``; the IsSelf trigger queues on the stack with
    # the ConditionalIfCastFromHand(Sequence(...)) bound; drain the
    # stack to resolve. The ConditionalIfCastFromHand resolve degrades
    # to always-run-inner (per the documented degradation at
    # combinators.py:1518-1536 -- ``cast_via_hand`` is ephemeral,
    # cleared before ETB triggers fire); the Sequence then runs
    # Shuffle -> Draw(7) byte-equal with Rust's resolve under the
    # shared external RNG. Mirrors the Codecracker Hound / Possibility
    # Technician / Boilerbilges Ripper Python-side convention exactly.
    py.players[0].hand.remove(py_ww)
    py_ww.zone = Zone.BATTLEFIELD
    # CR 302.1 -- only creatures have summoning sickness. Rust's
    # cast-resolve path explicitly clears summoning_sick on non-
    # creature permanents (state_ops_resolve.rs:603-611 Aura branch;
    # ``move_source_post_resolve`` mirrors the same convention for
    # plain Enchantments). Python's ``put_into_battlefield``
    # (actions.py:3003-3006) sets summoning_sick=True ONLY for
    # creatures. Mirror Rust's non-creature False on the manual
    # hand->bf move for byte-equal field-view symmetry.
    py_ww.summoning_sick = False
    py_ww.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ww)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_ww)
    while py.stack:
        resolve_top_of_stack(py)
    from mtg_bot.turn import state_based_actions as py_sba
    py_sba(py)

    # **Rust.** Push Weftwalking onto the stack via ``push_to_stack``
    # (the cast-without-cost synthetic-test pipeline). Rust's
    # ``resolve_top_of_stack`` walks the empty effects list (Weftwalking
    # carries no spell effects -- only a triggered ability), then
    # ``move_source_post_resolve`` lands Weftwalking on bf (CR 608.2m
    # permanent -> battlefield), then the synthesized
    # ``dispatch_event(Event::Enters, top.source_obj_id)`` fan-out at
    # state_ops_resolve.rs:22968 fires the IsSelf trigger which queues
    # a ``StackItemKind::TriggeredAbility`` with the
    # ConditionalIfCastFromHand body. The next ``resolve_top_of_stack``
    # call resolves the trigger via ``apply_effect`` ->
    # ``Effect::ConditionalIfCastFromHand { inner }`` arm at
    # state_ops_resolve.rs:17061-17063 (always-run-inner per the
    # documented degradation) -> the Sequence -> Shuffle + Draw(7)
    # under the shared external RNG byte-equal with Python.
    rs.push_to_stack(rs_ww, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Python observables. ----
    # Hand has exactly 7 cards (drew 7 after the shuffle).
    py_hand_size = len(py.players[0].hand)
    assert py_hand_size == 7, (
        f"Python: hand must have exactly 7 cards post-resolve "
        f"(drew 7 after the shuffle); got {py_hand_size}"
    )
    # Graveyard must be empty (shuffled into library).
    py_gy_size = len(py.players[0].graveyard)
    assert py_gy_size == 0, (
        f"Python: graveyard must be empty post-shuffle; got {py_gy_size}"
    )
    # Library size = NUM_LIB + NUM_HAND + NUM_GY - 7 = 12 + 2 + 3 - 7 = 10.
    py_lib_size = len(py.players[0].library)
    assert py_lib_size == (NUM_LIB + NUM_HAND + NUM_GY - 7), (
        f"Python: library must shrink to "
        f"{NUM_LIB + NUM_HAND + NUM_GY - 7} cards "
        f"(orig {NUM_LIB} + hand {NUM_HAND} + gy {NUM_GY} - drew 7); "
        f"got {py_lib_size}"
    )
    # Weftwalking still on bf.
    assert py_ww in py.battlefield, (
        "Python: Weftwalking must remain on bf post-resolve"
    )

    # ---- Rust observables. ----
    rs_hand_size = rs.hand_sizes[0]
    assert rs_hand_size == 7, (
        f"Rust: hand must have exactly 7 cards post-resolve; got "
        f"{rs_hand_size}"
    )
    rs_gy_size = len(rs.graveyard_snapshot(0))
    assert rs_gy_size == 0, (
        f"Rust: graveyard must be empty post-shuffle; got {rs_gy_size}"
    )
    rs_lib_size = rs.library_sizes[0]
    assert rs_lib_size == (NUM_LIB + NUM_HAND + NUM_GY - 7), (
        f"Rust: library must shrink to "
        f"{NUM_LIB + NUM_HAND + NUM_GY - 7} cards; got {rs_lib_size}"
    )
    rs_bf_names = [e["printing_name"] for e in rs.battlefield_snapshot()]
    assert "Weftwalking" in rs_bf_names, (
        f"Rust: Weftwalking must remain on bf post-resolve; got "
        f"bf_names={rs_bf_names}"
    )

    # ---- Cross-engine deterministic-shuffle byte-equality. ----
    # Hand contents (by printing name) must match on both engines --
    # the shared external-RNG Fisher-Yates produced the same shuffle
    # output, so the same 7 cards drawn off the top of the library
    # ended up in the same order in hand.
    py_hand_names = [o.printing.name for o in py.players[0].hand]
    rs_hand_names = [e["printing_name"] for e in rs.hand_snapshot(0)]
    assert py_hand_names == rs_hand_names, (
        f"Cross-engine hand-contents divergence under shared external "
        f"RNG -- the shuffle parity contract failed. The documented "
        f"ConditionalIfCastFromHand resolve degradation does not "
        f"account for a Shuffle/Draw cross-engine divergence; STOP "
        f"and honest-stop. py_hand={py_hand_names} "
        f"rs_hand={rs_hand_names}"
    )
    # Library order must match too.
    py_lib_names = [o.printing.name for o in py.players[0].library]
    rs_lib_names = [
        e["printing_name"] for e in rs.library_snapshot(0)
    ]
    assert py_lib_names == rs_lib_names, (
        f"Cross-engine library-order divergence under shared external "
        f"RNG. py_lib={py_lib_names} rs_lib={rs_lib_names}"
    )

    # ---- Full field-view byte-equality over the WHOLE state. ----
    # The strongest tier of the parity contract -- mirrors Codecracker
    # Hound C3 Pin (4) / Anticausal Vestige C3 Pin (4) / Memorial
    # Team Leader C2 Pin (cross_engine_real_eoe).
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Weftwalking ETB ConditionalIfCastFromHand(Sequence("
        f"ShuffleZonesIntoLibrary(hand+graveyard), DrawCards(7))) "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines under the shared external RNG; diffs={diffs}"
    )
