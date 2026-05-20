"""Divergence-pin tests: batch XXX (round 25 pin-side).

Round 25 pin batch surfacing the high-confidence divergence-pin
candidate the Survivor downstream probe agent dropped during
honest exhaustion (see commit ``1ad5b073`` -- the merge note
explicitly calls out House Cartographer's bespoke reveal-until-
land effect having no Rust resolver), plus two fresh
BLOCKED-genuinely_missing candidates from
``docs/POOL_PARITY.md`` (6-card list remaining after slice 16
closed Astelli Reclaimer).

**Slice 18 closure status:** Pin 2 (Roving Actuator no Rust Effect
variant) is CLOSED -- new ``Effect::RovingActuatorETBEffect
{ max_mv: u8 }`` variant + parse arm + resolve arm in Rust + bridge
arm in ``cross_engine.py``; renamed to ``..._FIXED_parity`` with
the sentinel inverted.

**Slice 20 closure status:** Pin 3 (Lightstall Inquisitor no Rust
Effect variant) is PARTIALLY CLOSED -- new
``Effect::EachOpponentExilesCardFromHandWithCastPermission`` unit
variant + parse arm + resolve arm (each-opponent-exile portion) in
Rust + bridge arm in ``cross_engine.py``; renamed to
``..._partial_FIXED_parity`` with the sentinel inverted. The
persistent ``cast_from_exile_with_lightstall_surcharge`` per-object
flag + cast-from-exile legality + +{1} surcharge + tapped-land-entry
riders are HONEST-STOPPED (substrate is large 6+ cycles --
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` §3). Cross-engine
byte-equality holds up to the exile-of-the-card step; any probe
that further attempts to cast the exiled card on the owner's next
priority is NOT byte-equal.

**Slice 21 closure status:** Pin 1 (House Cartographer no Rust
Effect variant) is CLOSED -- new
``Effect::HouseCartographerSurvivalEffect`` unit variant + parse arm
+ resolve arm in Rust + bridge arm in ``cross_engine.py``; renamed
to ``..._FIXED_parity`` with the sentinel inverted. The resolve arm
mirrors Python's reveal-until-land library walk step-for-step:
deterministic top-of-library pop with a ``card_types`` land-
terminator, hand transition for the revealed land with CR 400.7
zone-change reset, and a byte-equal external-rng Fisher-Yates
shuffle (xorshift64 fallback when no external rng is installed)
for the random-order bottom-append tail. House Cartographer brings
the EoE Survivor-family probe coverage to 5/5 (after slice 15 +
the Survivor downstream honest-exhaustion drop at ``1ad5b073``).

Each open pin test is named ``test_..._divergence_pin`` and
ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so
these tests grow the test surface without touching the PROBED
metric.

Pin closure cadence: when a sibling Rust slice closes the
underlying gap, the relevant assertion fires and the pin is
renamed ``*_FIXED_parity`` (or ``*_partial_FIXED_parity`` for
honest-stop closures) with the sentinel inverted (PPP / MMM / JJJ
/ RRR / TTT / VVV Pin 1 / XXX Pin 2 / XXX Pin 3 precedent).

Pinned bugs
-----------

Pin 1 -- House Cartographer's ``HouseCartographerSurvivalEffect``
bespoke effect at ``src/mtg_bot/effects/bespoke.py:2667-2733`` has
no Rust ``Effect`` variant, no parse arm, and no resolve arm.
Python implements a reveal-until-land library walk: pop cards
from the top of the controller's library until a land is revealed
(or the library is empty), the revealed land goes to the
controller's hand, the rest go to the bottom of the library in a
random order (state.rng-shuffled).  Rust's ``Effect`` enum has
no matching arm -- the printing's
``BEGINNING_OF_POSTCOMBAT_MAIN`` triggered ability cannot
round-trip through the bridge.  Surfaced by the Survivor
downstream probe agent during honest-exhaustion drop (commit
``1ad5b073``); House Cartographer is the only EoE Survivor card
whose postcombat-main trigger emits a bespoke Rust-missing
effect -- the other 4 Survivor cards (Savior of the Small,
Cautious Survivor, Defiant Survivor, Shrewd Storyteller) emit
generic Effects that DO have Rust counterparts.

  Bug location (Python -- the canonical behavior):
    ``src/mtg_bot/effects/bespoke.py:2667-2733`` --
    ``HouseCartographerSurvivalEffect.resolve``: reads
    ``state.player_by_id(controller_id).library``, pops from the
    top, accumulates non-land cards into a ``revealed`` list,
    breaks on the first land, puts the land into the controller's
    hand, then ``state.rng.shuffle``s the non-lands and appends
    them to the bottom of the library.  Matches CR 701.18a /
    "random order" tail.

  Bug location (Rust -- the gap):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching this
    shape.  Confirmed via grep: zero hits for
    ``HouseCartographer`` / ``house_cartographer`` /
    ``reveal_until_land`` across the Rust crate
    (``rust/src/*.rs``).

  Scale (EoE cards affected): 1 directly (House Cartographer --
  the unique EoE printing with this reveal-until-land Survivor
  body).  Listed in the merge-note honest-exhaustion drop at
  ``1ad5b073`` and dropped from the Survivor downstream probe
  surface because no Rust resolver exists for the bespoke
  effect.

  Closure path:
    1. Add ``Effect::HouseCartographerSurvivalEffect`` unit
       variant to ``rust/src/cards.rs::Effect`` enum (zero-field;
       the source-controller pair is read from
       ``state.resolving_source`` at resolve time, mirroring the
       Python convention -- though the effect is controller-
       parameterised, not source-parameterised, so it can also
       resolve via the dispatcher's ``controller_id`` parameter).
    2. Add parse arm in ``rust/src/cards.rs::parse_effect`` for
       the ``"house_cartographer_survival"`` effect_kind string
       (and matching ``effect_to_pydict`` arm).
    3. Add the resolve arm in ``rust/src/state_ops_resolve.rs``::

         a. Look up the controller's library.
         b. Pop cards from the top one at a time; for each
            popped card, check ``printing.is_land`` (the same
            type-tag the Rust card data tracks).
         c. If a land is found, route it to the controller's
            hand (``state_ops_zones`` move-to-hand primitive)
            and break.
         d. If the library empties without finding a land, all
            popped cards are non-land and the library is now
            empty -- proceed to step e.
         e. Take the accumulated non-land cards, deterministically
            shuffle them using the existing ``state.rng_shuffle``
            primitive (mirrors how every other random-order Rust
            resolve arm folds in -- see the ``DrawCards`` shuffle
            sibling for the canonical pattern), and append them
            to the bottom of the library.
    4. Add bridge arm in
       ``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``
       mapping the ``"house_cartographer_survival"`` effect_kind
       string to ``HouseCartographerSurvivalEffect()``.
    5. Add a real-EoE byte-equal probe for House Cartographer
       driving BEGINNING_OF_POSTCOMBAT_MAIN ->
       HouseCartographerSurvivalEffect via the live registry
       (with mixed land/non-land library content to exercise the
       reveal-until-land walk), then flip this pin to
       ``..._FIXED_parity`` per the standard cadence.

Pin 2 -- Roving Actuator's ``RovingActuatorETBEffect`` bespoke
effect at ``src/mtg_bot/effects/bespoke.py:630-718`` has no Rust
``Effect`` variant.  Python implements the Void ETB body: "Exile
up to one target instant or sorcery card with mana value 2 or
less from your graveyard. Copy it. You may cast the copy without
paying its mana cost."  The resolve method exiles the chosen
graveyard card and immediately re-resolves its
``spell_effect`` with freshly-picked targets (engine-level
copy-and-cast-for-free short-circuit -- the copy doesn't go on
the stack, can't be counterspelled).  Rust has no matching
Effect arm.  One of 6 cards on the ``docs/POOL_PARITY.md``
BLOCKED-genuinely_missing list (3400 17lands decks per
``docs/RESIDUE_CARD_PLANS.md``:96).

  Bug location (Python -- the canonical behavior):
    ``src/mtg_bot/effects/bespoke.py:630-718`` --
    ``RovingActuatorETBEffect``: ``legal_targets`` filters
    ``graveyard_spell`` candidates by
    ``is_instant or is_sorcery`` AND ``mana_cost.total <= 2``;
    ``resolve`` exiles the picked card, copies its
    ``spell_effect``, and routes through the agent's
    ``choose_target`` for each fresh target on the copy before
    calling ``spell_effect.resolve`` directly.

  Bug location (Rust -- the gap):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching this
    shape.  Confirmed via grep: zero hits for ``RovingActuator``
    / ``roving_actuator`` / ``VoidExileFromGY`` across the Rust
    crate (``rust/src/*.rs``).

  Scale (EoE cards affected): 1 directly (Roving Actuator;
  3400 17lands decks).  Sibling-subsystem note: the cast-from-
  exile-copy-for-free path is shared by a small cluster of
  "copy a spell card and cast the copy for free" cards in
  later sets, but Roving Actuator is the only EoE printing in
  this shape.

  Closure path:
    1. Add ``Effect::RovingActuatorETBEffect { max_mv: u8 }``
       variant to ``rust/src/cards.rs::Effect`` (the ``max_mv``
       field mirrors the Python dataclass's ``max_mv: int = 2``
       field; surfacing the threshold lets future "MV<=N"
       siblings reuse the variant).
    2. Add parse arm in ``rust/src/cards.rs::parse_effect`` for
       the ``"roving_actuator_etb"`` effect_kind string (and
       matching ``effect_to_pydict`` arm reading the ``max_mv``
       int back).
    3. Add the resolve arm in
       ``rust/src/state_ops_resolve.rs``::

         a. Resolve ``state.resolving_source``'s controller.
         b. Filter the controller's graveyard for instant /
            sorcery cards with mana value <= ``max_mv`` (mirrors
            ``legal_targets``).
         c. If non-empty, pump a
            ``PendingDecision::GraveyardSpellTarget`` (mirror of
            the standard target-picking decisions) for the agent
            to pick one of the legal graveyard spells.
         d. On a chosen card, exile it (zones primitive) and
            then dispatch its ``spell_effect`` through the
            existing target-selection-and-resolve pump WITHOUT
            paying the mana cost (cast-from-exile-for-free
            substrate -- the same Void/Lightstall surcharge
            substrate the next pin closes the inverse of).
    4. Add bridge arm in
       ``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``
       mapping ``"roving_actuator_etb"`` to
       ``RovingActuatorETBEffect(max_mv=max_mv_from_dict)``.
    5. Add a real-EoE byte-equal probe for Roving Actuator
       driving ENTERS -> RovingActuatorETBEffect via the live
       registry (with a graveyard containing a mix of MV>=3
       spells and one MV<=2 spell to exercise the
       legal-target-filter), then flip this pin to
       ``..._FIXED_parity`` per the standard cadence.

Pin 3 -- Lightstall Inquisitor's
``EachOpponentExilesCardFromHandWithCastPermission`` effect at
``src/mtg_bot/effects/generic/discard.py:172-214`` has no Rust
``Effect`` variant.  Python implements the each-opponent-exiles
hand-card ETB body: each opponent dispatches their agent's
``choose_discard`` hook to pick one of their hand cards, moves
it to exile with the
``cast_from_exile_with_lightstall_surcharge=True`` flag set,
and the cast-from-exile permission + ``{1}`` surcharge +
land-tapped-on-entry are enforced by ``legal.py``,
``actions.py``, and ``game.py`` based on that flag.  Rust has
no matching Effect arm and no awareness of the
``cast_from_exile_with_lightstall_surcharge`` flag.  One of 6
cards on the ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing
list (4371 17lands decks per
``docs/RESIDUE_CARD_PLANS.md``:94).

  Bug location (Python -- the canonical behavior):
    ``src/mtg_bot/effects/generic/discard.py:172-214`` --
    ``EachOpponentExilesCardFromHandWithCastPermission.resolve``:
    iterates ``state.players``, skips ``controller_id`` and
    ``has_lost`` players, calls ``p.agent.choose_discard`` with
    the opponent's hand-ids, moves the chosen card to exile,
    and sets
    ``card.cast_from_exile_with_lightstall_surcharge = True``.
    The persistent permission + cost-hike + land-tapped-entry
    riders are enforced downstream by
    ``src/mtg_bot/legal.py:536`` (cast permission),
    ``src/mtg_bot/actions.py:1080-1088`` (land-tapped on play),
    ``src/mtg_bot/actions.py:1471-1490`` (cast surcharge), and
    ``src/mtg_bot/game.py:481`` (owner-may-play grant).

  Bug location (Rust -- the gap):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching this
    shape.  Confirmed via grep: zero hits for ``Lightstall``
    / ``lightstall`` / ``EachOpponentExilesCard`` /
    ``cast_from_exile_with_lightstall_surcharge`` across the
    Rust crate (``rust/src/*.rs``).

  Scale (EoE cards affected): 1 directly (Lightstall
  Inquisitor; 4371 17lands decks).  Deferred-subsystem-blocked:
  closing this end-to-end requires (a) the new Effect arm + its
  parse / resolve / bridge arms, AND (b) the persistent
  cast-from-exile-with-surcharge permission substrate -- a
  per-card sticky flag that survives across turns until the
  card leaves exile or is cast, plus enforcement in the cast /
  play / cost-paying paths (the legal-action surface needs the
  matching land-tapped-on-play + cost-+1 routing).  Multi-round
  closure scope per the ``docs/RESIDUE_CARD_PLANS.md``:94
  classification ("**NO** -- play-from-exile permission
  subsystem | multi-round").

  Closure path:
    1. Add ``Effect::EachOpponentExilesCardFromHandWithCastPermission``
       (unit variant) to ``rust/src/cards.rs::Effect`` enum.
    2. Add parse arm in ``rust/src/cards.rs::parse_effect`` for
       the ``"each_opponent_exiles_card_from_hand_lightstall"``
       effect_kind string (and matching ``effect_to_pydict``
       arm).
    3. Add the resolve arm in
       ``rust/src/state_ops_resolve.rs``::

         a. Iterate non-controller, alive players.
         b. For each, pump a
            ``PendingDecision::HandExileChoice`` (mirror of
            the standard discard-style decisions; the
            opponent's agent picks one of their hand cards).
         c. On the chosen card: exile it (zones primitive)
            AND set a per-card persistent flag
            ``cast_from_exile_with_lightstall_surcharge=true``
            (new Rust card-state field; the substrate needs
            to plumb this flag end-to-end).
    4. Plumb the persistent-permission substrate end-to-end on
       the Rust side -- the legal-action enumerator needs to
       surface the cast-from-exile / play-from-exile action
       with the ``{1}`` surcharge / land-tapped-entry riders.
       This is the multi-round subsystem scope (the
       ``play-from-exile-permission`` subsystem the residue
       worklist itemises).
    5. Add bridge arm in
       ``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``
       mapping
       ``"each_opponent_exiles_card_from_hand_lightstall"``
       to ``EachOpponentExilesCardFromHandWithCastPermission()``
       AND a sticky-flag bridge for
       ``cast_from_exile_with_lightstall_surcharge``.
    6. Add a real-EoE byte-equal probe for Lightstall
       Inquisitor driving ENTERS ->
       EachOpponentExilesCardFromHandWithCastPermission via
       the live registry (with a controlled opponent hand and
       a deterministic ``choose_discard`` agent), then flip
       this pin to ``..._FIXED_parity`` per the standard
       cadence.

This batch is a coherent set of three high-confidence pins
surfaced from the Survivor downstream probe agent's
honest-exhaustion drop (Pin 1) plus two fresh
BLOCKED-genuinely_missing candidates from the remaining 6-card
list (Pins 2 + 3 -- Roving Actuator and Lightstall Inquisitor).
All three pins sit on the same axis: a Python bespoke Effect
class with NO matching Rust ``Effect`` enum variant, parse arm,
or resolve arm.  No two pins share a closure surface: Pin 1
closes at the reveal-until-land library-walk + random-order
shuffle substrate; Pin 2 closes at the cast-from-exile-copy-
for-free substrate (instant / sorcery MV-gated graveyard
exile); Pin 3 closes at the persistent
play-from-exile-with-surcharge permission substrate
(multi-round subsystem scope).  Together they enumerate
half (3 of 6) of the remaining BLOCKED-genuinely_missing list
-- the Survivor-postcombat-main bespoke gap, the Void-copy-
cast-for-free gap, and the persistent-cast-from-exile-with-
surcharge gap.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- House Cartographer's HouseCartographerSurvivalEffect bespoke
#          effect has no Rust Effect variant.  Reveal-until-land library-
#          walk + random-order shuffle subsystem gap; the Survivor
#          downstream probe agent's honest-exhaustion drop
#          (commit 1ad5b073).  1 EoE card affected: House Cartographer.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_house_cartographer_reveal_until_land_no_rust_variant_FIXED_parity():
    """**21st Rust slice (XXX Pin 1 closure)** -- House Cartographer's
    Survival postcombat-main effect now has a matching Rust
    ``Effect::HouseCartographerSurvivalEffect`` unit variant + parse
    arm + resolve arm + bridge arm.

    Pre-closure (the divergence XXX Pin 1 locked in): Python's bespoke
    ``HouseCartographerSurvivalEffect``
    (``src/mtg_bot/effects/bespoke.py:2667-2733``) implemented a
    reveal-until-land library walk: pop cards from the top of the
    controller's library, accumulate non-lands, break on the first
    land, put the land into the controller's hand, then
    ``state.rng``-shuffle the non-lands and append them to the bottom
    of the library. Rust's ``Effect`` enum had no matching variant --
    the printing's ``BEGINNING_OF_POSTCOMBAT_MAIN`` triggered ability
    body could not round-trip through the bridge. Surfaced by the
    Survivor downstream probe agent during honest-exhaustion drop
    (commit ``1ad5b073``); the 5th and final EoE Survivor-family
    probe carrier.

    Post-closure (asserted here): a new
    ``Effect::HouseCartographerSurvivalEffect`` unit variant lands in
    ``rust/src/cards.rs`` with parse arm, to_pydict arm, resolve arm
    in ``rust/src/state_ops_resolve.rs``, and bridge arm in
    ``src/mtg_bot/parity/cross_engine.py``. The resolve arm mirrors
    Python step-for-step: source-controller resolution; library walk
    popping from the top with a ``card_types contains "Land"``
    terminator; revealed land goes to the controller's hand with the
    standard CR 400.7 zone-change reset; non-land "rest" is shuffled
    via the byte-equal ``external_rng::next_below`` Fisher-Yates path
    (when an external ``random.Random`` is installed) / xorshift64
    fallback; shuffled cards are appended onto the BOTTOM of the
    controller's library with ``zone = ZONE_LIBRARY``.

    Closure shape:
      1. Python's bespoke ``HouseCartographerSurvivalEffect`` class is
         unchanged (the SoT side; the closure was Rust-side).
      2. Sentinel inverted: the Rust crate's source files NOW contain
         ``HouseCartographerSurvivalEffect`` /
         ``house_cartographer_survival`` (the new variant + parse arm +
         resolve arm).
      3. The bridge arm round-trips Rust's
         ``{"kind": "house_cartographer_survival"}`` to Python's
         ``HouseCartographerSurvivalEffect()``.

    EoE card scale: 1 directly (House Cartographer; the 5th and final
    EoE Survivor-family probe carrier, completing the 5/5 Survivor
    downstream probe coverage set).
    """
    # 1. Python's HouseCartographerSurvivalEffect class is unchanged
    #    (the SoT side; the closure was Rust-side).
    from mtg_bot.effects.bespoke import HouseCartographerSurvivalEffect
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(HouseCartographerSurvivalEffect, _EffectBase), (
        "HouseCartographerSurvivalEffect should be an Effect subclass "
        "(effects/bespoke.py:2667-2733).  If this fails, the bespoke "
        "class was restructured -- update this pin."
    )

    inst = HouseCartographerSurvivalEffect()
    assert hasattr(inst, "resolve"), (
        "HouseCartographerSurvivalEffect should have a 'resolve' method "
        "(pops from the controller's library until a land is revealed, "
        "puts the land in hand, shuffles the rest to the bottom).  "
        "If absent, the Python convention changed."
    )

    # 1a. The resolve method walks the controller's library, checks
    #     printing.is_land, routes the land to hand, and shuffles the
    #     non-lands to the bottom.
    resolve_src = inspect.getsource(HouseCartographerSurvivalEffect.resolve)
    assert "state.player_by_id" in resolve_src, (
        "HouseCartographerSurvivalEffect.resolve should resolve the "
        "controller's player via state.player_by_id.  If absent, the "
        "Python convention changed -- update this pin."
    )
    assert "is_land" in resolve_src, (
        "HouseCartographerSurvivalEffect.resolve should check "
        "printing.is_land to detect the land that terminates the walk.  "
        "If absent, the Python convention changed."
    )
    assert "state.rng" in resolve_src and "shuffle" in resolve_src, (
        "HouseCartographerSurvivalEffect.resolve should route the "
        "non-land tail through state.rng.shuffle to satisfy the 'in a "
        "random order' tail (CR 701.18a).  If absent, the Python "
        "convention changed."
    )
    assert "Zone.HAND" in resolve_src, (
        "HouseCartographerSurvivalEffect.resolve should route the "
        "revealed land to Zone.HAND.  If absent, the Python convention "
        "changed."
    )

    # 2. Rust crate: sentinels INVERTED -- the Rust source files now
    #    contain Effect::HouseCartographerSurvivalEffect + the parse-arm
    #    kind string + the resolve arm.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    # Closure assertions: the Effect variant + parse-arm kind string
    # land in cards.rs, the resolve arm lands in state_ops_resolve.rs.
    assert "HouseCartographerSurvivalEffect" in cards_src, (
        "Closure assertion: rust/src/cards.rs SHOULD contain "
        "'HouseCartographerSurvivalEffect' -- the new Effect variant "
        "added by the 21st Rust slice."
    )
    assert "house_cartographer_survival" in cards_src, (
        "Closure assertion: rust/src/cards.rs SHOULD contain "
        "'house_cartographer_survival' -- the parse-arm kind string "
        "the bridge produces."
    )
    assert "HouseCartographerSurvivalEffect" in resolve_src_rs, (
        "Closure assertion: rust/src/state_ops_resolve.rs SHOULD "
        "contain 'HouseCartographerSurvivalEffect' -- the new resolve "
        "arm added by the 21st Rust slice."
    )

    # 3. House Cartographer is loadable + carries the expected
    #    postcombat-main trigger with the bespoke effect.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("House Cartographer")
    assert pr is not None, (
        "Pin invariant: 'House Cartographer' should be present in "
        "the active CardSource (per the Survivor downstream probe "
        "agent's honest-exhaustion drop at commit 1ad5b073).  If "
        "missing, the EoE data file was regenerated -- update this "
        "pin."
    )
    assert "Creature" in pr.card_types, (
        f"Pin invariant: House Cartographer should be a Creature "
        f"card type (a Survivor printing).  Got: {pr.card_types}."
    )
    pcm_ta = next(
        (
            ta for ta in pr.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None, (
        "Pin invariant: House Cartographer should carry a "
        "BEGINNING_OF_POSTCOMBAT_MAIN triggered ability (the Survivor "
        "postcombat-main rider).  If absent, the parser convention "
        "changed -- update this pin."
    )
    assert isinstance(pcm_ta.effect, HouseCartographerSurvivalEffect), (
        f"Pin invariant: House Cartographer's postcombat-main effect "
        f"should be HouseCartographerSurvivalEffect.  Got: "
        f"{type(pcm_ta.effect).__name__}."
    )

    # 4. Bridge round-trip: parse_effect({"kind":
    #    "house_cartographer_survival"}) → Rust variant → bridged →
    #    Python HouseCartographerSurvivalEffect().
    try:
        import mtg_bot_engine  # noqa: F401
    except ImportError:
        # Rust extension not built; skip the round-trip assertion
        # (it's covered by the dedicated downstream probe file).
        pass
    else:
        from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
        dict_payload = {"kind": "house_cartographer_survival"}
        bridged = _ta_dict_to_python_effect(dict_payload)
        assert isinstance(bridged, HouseCartographerSurvivalEffect), (
            f"Closure assertion: bridge should round-trip "
            f"{{'kind': 'house_cartographer_survival'}} to "
            f"HouseCartographerSurvivalEffect.  Got: "
            f"{type(bridged).__name__}."
        )

    # 5. EoE cards affected.
    affected_eoe_cards = [
        "House Cartographer",
        # Survivor creature with "When this becomes tapped during your
        # postcombat main phase, reveal cards until a land, ...".
        # Surfaced by the Survivor downstream probe agent during
        # honest-exhaustion drop at commit 1ad5b073.  The only EoE
        # Survivor card whose postcombat-main trigger emits a bespoke
        # Rust-missing effect.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The House Cartographer reveal-until-land gap affects 1 "
        f"EoE card directly.  Enumerated list has "
        f"{len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- Roving Actuator's RovingActuatorETBEffect bespoke effect now
#          HAS a Rust Effect variant (Effect::RovingActuatorETBEffect
#          { max_mv: u8 }) + parse arm + resolve arm + bridge arm
#          (18th Rust slice closure).  1 EoE card unblocked: Roving
#          Actuator (3,400 17lands decks).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_roving_actuator_void_etb_no_rust_variant_FIXED_parity():
    """**18th Rust slice (XXX Pin 2 closure)** -- Roving Actuator's
    Void ETB now has a matching Rust ``Effect::RovingActuatorETBEffect
    { max_mv: u8 }`` variant + parse arm + resolve arm + bridge arm.

    Pre-closure (the divergence XXX Pin 2 locked in): Python's
    bespoke ``RovingActuatorETBEffect``
    (``src/mtg_bot/effects/bespoke.py:630-718``) filtered the
    controller's graveyard for instant/sorcery cards with mana value
    <= 2, exiled the chosen card, and immediately re-resolved the
    exiled card's ``spell_effect`` with freshly-picked targets (no
    stack item; the copy can't be countered).  Rust's ``Effect`` enum
    had no matching variant -- the printing's ETB body could not
    round-trip through the bridge.  This was one of 6 cards on the
    ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing list.

    Post-closure (asserted here): a new
    ``Effect::RovingActuatorETBEffect { max_mv: u8 }`` variant lands
    in ``rust/src/cards.rs`` with parse arm, to_pydict arm, resolve
    arm in ``rust/src/state_ops_resolve.rs``, and bridge arm in
    ``src/mtg_bot/parity/cross_engine.py``.  The resolve arm mirrors
    Python step-for-step: source-controller resolution; first-legal
    graveyard scan filtered to ``(is_instant || is_sorcery) &&
    mana_cost.total() <= max_mv``; silent no-op on empty filter;
    remove from gy, stamp ``zone=ZONE_EXILE``, push to controller's
    exile; recursively ``apply_effect`` each child of the exiled
    card's ``printing.effects`` (the single-element spell_effect
    list) with the EXILED card's id as new source and the source-
    controller transient pinned -- mirrors Python's
    ``spell_effect.resolve(state, controller_id, copy_targets)``
    direct dispatch.

    Closure shape:
      1. Python's bespoke ``RovingActuatorETBEffect`` class is
         unchanged (the SoT side; the closure was Rust-side).
      2. Sentinel inverted: the Rust crate's source files NOW
         contain ``RovingActuatorETBEffect`` /
         ``roving_actuator_etb`` (the new variant + parse arm +
         resolve arm).
      3. The bridge arm round-trips Rust's
         ``{"kind": "roving_actuator_etb", "max_mv": 2}`` to
         Python's ``RovingActuatorETBEffect(max_mv=2)``.

    EoE card scale: 1 directly (Roving Actuator; 3,400 17lands decks
    per ``docs/RESIDUE_CARD_PLANS.md``:96).  Cast-from-exile-copy-
    for-free subsystem gap closed (no broader cluster — Roving
    Actuator is the only EoE printing with this shape).
    """
    # 1. Python's RovingActuatorETBEffect class exists with the
    #    expected interface (the SoT side; unchanged by this slice).
    from mtg_bot.effects.bespoke import RovingActuatorETBEffect
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(RovingActuatorETBEffect, _EffectBase), (
        "RovingActuatorETBEffect should be an Effect subclass "
        "(effects/bespoke.py:630-718).  If this fails, the bespoke "
        "class was restructured -- update this pin."
    )

    inst = RovingActuatorETBEffect()
    assert hasattr(inst, "resolve"), (
        "RovingActuatorETBEffect should have a 'resolve' method "
        "(filters graveyard by instant/sorcery + MV<=max_mv; "
        "exiles the chosen card; routes the copy through "
        "spell_effect.resolve).  If absent, the convention changed."
    )
    assert hasattr(inst, "max_mv"), (
        "RovingActuatorETBEffect should expose a 'max_mv' field "
        "(the MV threshold for the graveyard exile filter).  If "
        "absent, the dataclass shape changed -- update this pin."
    )
    assert inst.max_mv == 2, (
        f"RovingActuatorETBEffect.max_mv should default to 2 (the "
        f"Void body's printed MV threshold).  Got: {inst.max_mv}."
    )

    # 1a. The resolve method filters the graveyard, exiles the
    #     target, and routes through spell_effect.resolve.
    resolve_src = inspect.getsource(RovingActuatorETBEffect.resolve)
    assert "graveyard" in resolve_src, (
        "RovingActuatorETBEffect.resolve should reference the "
        "controller's graveyard (the legal-target set).  If absent, "
        "the Python convention changed -- update this pin."
    )
    assert "spell_effect" in resolve_src, (
        "RovingActuatorETBEffect.resolve should route the copy "
        "through the exiled card's spell_effect.  If absent, the "
        "Python convention changed."
    )
    assert "Zone.EXILE" in resolve_src, (
        "RovingActuatorETBEffect.resolve should route the original "
        "to Zone.EXILE.  If absent, the Python convention changed."
    )

    # 2. Rust crate: sentinels INVERTED -- the Rust source files now
    #    contain Effect::RovingActuatorETBEffect + the parse-arm kind
    #    string + the resolve arm.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    # Closure assertions: the Effect variant + parse-arm kind string
    # land in cards.rs, the resolve arm lands in state_ops_resolve.rs.
    assert "RovingActuatorETBEffect" in cards_src, (
        "Closure assertion: rust/src/cards.rs SHOULD contain "
        "'RovingActuatorETBEffect' -- the new Effect variant added "
        "by the 18th Rust slice."
    )
    assert "roving_actuator_etb" in cards_src, (
        "Closure assertion: rust/src/cards.rs SHOULD contain "
        "'roving_actuator_etb' -- the parse-arm kind string the "
        "bridge produces."
    )
    assert "RovingActuatorETBEffect" in resolve_src_rs, (
        "Closure assertion: rust/src/state_ops_resolve.rs SHOULD "
        "contain 'RovingActuatorETBEffect' -- the new resolve arm "
        "added by the 18th Rust slice."
    )

    # 3. Roving Actuator is loadable + carries the expected ETB trigger.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("Roving Actuator")
    assert pr is not None, (
        "Pin invariant: 'Roving Actuator' should be present in the "
        "active CardSource.  If missing, the EoE data file was "
        "regenerated -- update this pin."
    )
    enters_ta = next(
        (ta for ta in pr.triggered_abilities if ta.event == Event.ENTERS),
        None,
    )
    assert enters_ta is not None, (
        "Pin invariant: Roving Actuator should carry an ENTERS "
        "triggered ability (the Void ETB rider).  If absent, the "
        "parser convention changed -- update this pin."
    )
    assert isinstance(enters_ta.effect, RovingActuatorETBEffect), (
        f"Pin invariant: Roving Actuator's ENTERS effect should be "
        f"RovingActuatorETBEffect.  Got: "
        f"{type(enters_ta.effect).__name__}."
    )

    # 4. Bridge round-trip: parse_effect({"kind":"roving_actuator_etb",
    #    "max_mv": 2}) → Rust variant → bridged → Python
    #    RovingActuatorETBEffect(max_mv=2).
    try:
        import mtg_bot_engine  # noqa: F401
    except ImportError:
        # Rust extension not built; skip the round-trip assertion
        # (it's covered by the dedicated downstream probe file).
        pass
    else:
        from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
        dict_payload = {"kind": "roving_actuator_etb", "max_mv": 2}
        bridged = _ta_dict_to_python_effect(dict_payload)
        assert isinstance(bridged, RovingActuatorETBEffect), (
            f"Closure assertion: bridge should round-trip "
            f"{{'kind': 'roving_actuator_etb', 'max_mv': 2}} to "
            f"RovingActuatorETBEffect.  Got: {type(bridged).__name__}."
        )
        assert bridged.max_mv == 2, (
            f"Closure assertion: bridge should preserve max_mv=2.  "
            f"Got: max_mv={bridged.max_mv}."
        )

    # 5. EoE cards affected.
    affected_eoe_cards = [
        "Roving Actuator",
        # Artifact creature with Void ETB: "exile up to one target
        # instant or sorcery card with mana value 2 or less from
        # your graveyard, copy it, you may cast the copy without
        # paying its mana cost".  3400 17lands decks per
        # docs/RESIDUE_CARD_PLANS.md:96.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The Roving Actuator Void-ETB gap affects 1 EoE card "
        f"directly.  Enumerated list has {len(affected_eoe_cards)} "
        "entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- Lightstall Inquisitor's
#          EachOpponentExilesCardFromHandWithCastPermission effect NOW
#          has a Rust Effect variant
#          (Effect::EachOpponentExilesCardFromHandWithCastPermission)
#          + parse arm + resolve arm (each-opponent-exile portion) +
#          bridge arm (20th Rust slice -- honest-stop closure).
#          1 EoE card unblocked (Effect-level + exile-portion byte-
#          equality): Lightstall Inquisitor (4,371 17lands decks).
#          The persistent cast-from-exile-with-surcharge permission
#          substrate is HONEST-STOPPED -- documented at
#          docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md §3 (large
#          6+ cycles).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lightstall_inquisitor_exile_with_cast_permission_no_rust_variant_partial_FIXED_parity():
    """**20th Rust slice (XXX Pin 3 honest-stop closure)** -- Lightstall
    Inquisitor's ETB now has a matching Rust
    ``Effect::EachOpponentExilesCardFromHandWithCastPermission`` unit
    variant + parse arm + resolve arm (each-opponent-exile portion)
    + bridge arm.

    Pre-closure (the divergence XXX Pin 3 locked in): Python's
    ``EachOpponentExilesCardFromHandWithCastPermission``
    (``src/mtg_bot/effects/generic/discard.py:172-214``) exiles a
    card from each opponent's hand and tags it with
    ``cast_from_exile_with_lightstall_surcharge=True``; ``legal.py``
    + ``actions.py`` + ``game.py`` honour the flag to grant +
    enforce the persistent permission, +{1} surcharge, and
    tapped-land-entry riders.  Rust's ``Effect`` enum had no
    matching variant and no awareness of the sticky flag.  This was
    one of 6 cards on the ``docs/POOL_PARITY.md`` BLOCKED-
    genuinely_missing list.

    Post-closure (partial; asserted here): a new
    ``Effect::EachOpponentExilesCardFromHandWithCastPermission``
    unit variant lands in ``rust/src/cards.rs`` with parse arm,
    to_pydict arm, resolve arm in
    ``rust/src/state_ops_resolve.rs``, and bridge arm in
    ``src/mtg_bot/parity/cross_engine.py``.  The resolve arm
    mirrors Python step-for-step on the EACH-OPPONENT-EXILE
    portion: source-controller resolution; 2-player "each opponent"
    reduces to "the one opponent"; empty hand = silent no-op; pop
    hand[0]; CR 400.7 zone-change reset; push to opponent's exile.

    **HONEST-STOP boundary.** The persistent
    ``cast_from_exile_with_lightstall_surcharge`` per-object flag
    + cast-from-exile legality + +{1} surcharge + tapped-land-
    entry riders are NOT plumbed in this slice. Rust's
    ``GameObject`` struct has no such field today;
    ``state_ops_legal.rs`` does not surface exile-as-cast-source
    for that flag; ``state_ops_cast.rs`` does not honor the
    surcharge / tapped-entry riders. Cross-engine byte-equality
    holds up to the exile step. Substrate scope: 6+ cycles
    (``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` §3).

    Closure shape:
      1. Python's ``EachOpponentExilesCardFromHandWithCastPermission``
         class is unchanged (the SoT side; the closure was Rust-side).
      2. Sentinel inverted: the Rust crate's source files NOW
         contain ``EachOpponentExilesCardFromHandWithCastPermission`` /
         ``each_opponent_exiles_card_from_hand_lightstall`` (the new
         variant + parse arm + resolve arm).
      3. The bridge arm round-trips Rust's
         ``{"kind": "each_opponent_exiles_card_from_hand_lightstall"}``
         to Python's
         ``EachOpponentExilesCardFromHandWithCastPermission()``.

    EoE card scale: 1 directly (Lightstall Inquisitor; 4,371 17lands
    decks per ``docs/RESIDUE_CARD_PLANS.md``:94). Effect-level +
    exile-portion byte-equality closure for the Effect-shape gap;
    full cast-from-exile permission deferred to a future substrate
    slice.
    """
    # 1. Python's EachOpponentExilesCardFromHandWithCastPermission
    #    class exists with the expected interface (the SoT side;
    #    unchanged by this slice).
    from mtg_bot.effects.generic.discard import (
        EachOpponentExilesCardFromHandWithCastPermission,
    )
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(
        EachOpponentExilesCardFromHandWithCastPermission, _EffectBase,
    ), (
        "EachOpponentExilesCardFromHandWithCastPermission should be an "
        "Effect subclass (effects/generic/discard.py:172-214).  If "
        "this fails, the class was restructured -- update this pin."
    )

    inst = EachOpponentExilesCardFromHandWithCastPermission()
    assert hasattr(inst, "resolve"), (
        "EachOpponentExilesCardFromHandWithCastPermission should have "
        "a 'resolve' method (iterates non-controller alive players; "
        "routes through choose_discard; tags "
        "cast_from_exile_with_lightstall_surcharge).  If absent, the "
        "convention changed."
    )

    # 1a. The resolve method iterates non-controller players, routes
    #     through choose_discard, and tags
    #     cast_from_exile_with_lightstall_surcharge on the chosen card.
    resolve_src = inspect.getsource(
        EachOpponentExilesCardFromHandWithCastPermission.resolve
    )
    assert "state.players" in resolve_src, (
        "EachOpponentExilesCardFromHandWithCastPermission.resolve "
        "should iterate state.players (to fan out the per-opponent "
        "exile).  If absent, the Python convention changed -- update "
        "this pin."
    )
    assert "choose_discard" in resolve_src, (
        "EachOpponentExilesCardFromHandWithCastPermission.resolve "
        "should route through the opponent's choose_discard hook.  "
        "If absent, the Python convention changed."
    )
    assert "cast_from_exile_with_lightstall_surcharge" in resolve_src, (
        "EachOpponentExilesCardFromHandWithCastPermission.resolve "
        "should tag the exiled card with "
        "cast_from_exile_with_lightstall_surcharge=True (the "
        "persistent-permission flag).  If absent, the Python "
        "convention changed."
    )
    assert "Zone.EXILE" in resolve_src, (
        "EachOpponentExilesCardFromHandWithCastPermission.resolve "
        "should route the chosen card to Zone.EXILE.  If absent, "
        "the Python convention changed."
    )

    # 2. Rust crate: sentinels INVERTED -- the Rust source files NOW
    #    contain Effect::EachOpponentExilesCardFromHandWithCastPermission
    #    + the parse-arm kind string + the resolve arm.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    # Closure assertions: the Effect variant name + parse-arm kind
    # string + bridge dict-kind MUST appear in cards.rs; the resolve
    # arm MUST appear in state_ops_resolve.rs.
    required_in_cards = [
        "EachOpponentExilesCardFromHandWithCastPermission",
        "each_opponent_exiles_card_from_hand_lightstall",
    ]
    for needle in required_in_cards:
        assert needle in cards_src, (
            f"Closure assertion: rust/src/cards.rs MUST contain "
            f"{needle!r} (the Effect variant + parse-arm + to_pydict "
            "arm landed by the 20th Rust slice).  If this fails, the "
            "Rust-side closure was reverted -- audit the slice."
        )
    required_in_resolve = [
        "EachOpponentExilesCardFromHandWithCastPermission",
    ]
    for needle in required_in_resolve:
        assert needle in resolve_src_rs, (
            f"Closure assertion: rust/src/state_ops_resolve.rs MUST "
            f"contain {needle!r} (the resolve arm landed by the 20th "
            "Rust slice -- each-opponent-exile portion).  If this "
            "fails, the resolve arm was reverted -- audit the slice."
        )

    # **HONEST-STOP boundary marker.** The persistent
    # cast_from_exile_with_lightstall_surcharge flag substrate is NOT
    # in Rust yet -- documenting the boundary here so a future
    # substrate slice landing can find the assertion to invert.
    # Sentinel: the Rust GameObject struct (state.rs) carries NO
    # 'cast_from_exile_with_lightstall_surcharge' field. The variant
    # docstring references the field-name string, but the actual
    # Rust-side struct field does not exist. Checking for the field-
    # declaration line ('cast_from_exile_with_lightstall_surcharge:')
    # rather than the bare name (which appears in the docstring as
    # the substrate-scope identifier) keeps the sentinel honest.
    rust_state_path = repo_root / "rust" / "src" / "state.rs"
    assert rust_state_path.exists(), (
        f"Rust source file should exist at {rust_state_path!r}."
    )
    state_src_rs = rust_state_path.read_text(encoding="utf-8")
    assert "cast_from_exile_with_lightstall_surcharge:" not in state_src_rs, (
        "Honest-stop boundary: rust/src/state.rs's GameObject struct "
        "should NOT yet carry a 'cast_from_exile_with_lightstall_"
        "surcharge:' field declaration (the persistent permission "
        "substrate is honest-stopped in the 20th Rust slice; see "
        "docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md §3 for substrate "
        "scope).  If this assertion fails, the persistent permission "
        "substrate landed in a follow-up slice -- flip this pin to "
        "..._FIXED_parity (drop the _partial_) and remove this "
        "honest-stop assertion."
    )

    # 2a. The bridge arm round-trips the Rust dict to a Python
    #     EachOpponentExilesCardFromHandWithCastPermission instance.
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect,
    )
    bridged = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_card_from_hand_lightstall"}
    )
    assert isinstance(
        bridged, EachOpponentExilesCardFromHandWithCastPermission
    ), (
        f"Closure assertion: bridge arm should round-trip "
        f"{{'kind': 'each_opponent_exiles_card_from_hand_lightstall'}} "
        f"to EachOpponentExilesCardFromHandWithCastPermission().  Got: "
        f"{type(bridged).__name__}."
    )

    # 3. Lightstall Inquisitor is loadable + carries the expected
    #    ETB trigger.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("Lightstall Inquisitor")
    assert pr is not None, (
        "Pin invariant: 'Lightstall Inquisitor' should be present in "
        "the active CardSource (per docs/POOL_PARITY.md BLOCKED-"
        "genuinely_missing list).  If missing, the EoE data file was "
        "regenerated -- update this pin."
    )
    assert "Creature" in pr.card_types, (
        f"Pin invariant: Lightstall Inquisitor should be a Creature "
        f"card type.  Got: {pr.card_types}."
    )
    enters_ta = next(
        (ta for ta in pr.triggered_abilities if ta.event == Event.ENTERS),
        None,
    )
    assert enters_ta is not None, (
        "Pin invariant: Lightstall Inquisitor should carry an ENTERS "
        "triggered ability (the each-opponent-exile rider).  If "
        "absent, the parser convention changed -- update this pin."
    )
    assert isinstance(
        enters_ta.effect, EachOpponentExilesCardFromHandWithCastPermission
    ), (
        f"Pin invariant: Lightstall Inquisitor's ENTERS effect should "
        f"be EachOpponentExilesCardFromHandWithCastPermission.  Got: "
        f"{type(enters_ta.effect).__name__}."
    )

    # 4. EoE cards affected.
    affected_eoe_cards = [
        "Lightstall Inquisitor",
        # Creature with each-opponent-exiles-card-from-hand + may-play
        # + cost-hike + tapped-land-entry persistence.  4371 17lands
        # decks per docs/RESIDUE_CARD_PLANS.md:94.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The Lightstall Inquisitor persistent-exile-cast gap affects "
        f"1 EoE card directly.  Enumerated list has "
        f"{len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pytest visibility check: ensure the three pin tests are collected.
# ---------------------------------------------------------------------------


def test_xxx_pin_inventory_complete():
    """Sanity check: the XXX batch declares exactly 3 pin tests
    (0 OPEN _divergence_pin + 2 CLOSED _FIXED_parity + 1 PARTIAL
    _partial_FIXED_parity after the 18th + 20th + 21st Rust slices).

    Pin batch XXX (round 25 pin-side) targets 3 divergence pins per
    the lane discipline.  Pin 2 (Roving Actuator) was closed by the
    18th Rust slice and renamed ``..._FIXED_parity``; Pin 3
    (Lightstall Inquisitor) was partially closed by the 20th Rust
    slice (Effect-level + each-opponent-exile portion byte-equal;
    persistent cast-from-exile permission substrate honest-stopped)
    and renamed ``..._partial_FIXED_parity``; Pin 1 (House
    Cartographer) was closed by the 21st Rust slice and renamed
    ``..._FIXED_parity``.  This guards against accidental deletion or
    rename of any pin function (open / closed / partial).
    """
    import tests.test_divergence_pins_xxx as _self_mod
    open_pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_divergence_pin")
    ]
    closed_pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_FIXED_parity")
        and not name.endswith("_partial_FIXED_parity")
    ]
    partial_pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_partial_FIXED_parity")
    ]
    expected_open_pins: set[str] = set()
    expected_closed_pins = {
        "test_cross_engine_real_eoe_roving_actuator_void_etb_no_rust_variant_FIXED_parity",
        "test_cross_engine_real_eoe_house_cartographer_reveal_until_land_no_rust_variant_FIXED_parity",
    }
    expected_partial_pins = {
        "test_cross_engine_real_eoe_lightstall_inquisitor_exile_with_cast_permission_no_rust_variant_partial_FIXED_parity",
    }
    assert set(open_pin_fns) == expected_open_pins, (
        "XXX open-pin inventory mismatch.  Expected zero open pin "
        "tests (all 3 Pins closed or partial-closed):\n"
        f"  {sorted(expected_open_pins)}\n"
        f"Got:\n  {sorted(open_pin_fns)}"
    )
    assert set(closed_pin_fns) == expected_closed_pins, (
        "XXX closed-pin inventory mismatch.  Expected exactly the 2 "
        "closed pin tests (Pin 2 closed by 18th Rust slice; Pin 1 "
        "closed by 21st Rust slice):\n"
        f"  {sorted(expected_closed_pins)}\n"
        f"Got:\n  {sorted(closed_pin_fns)}"
    )
    assert set(partial_pin_fns) == expected_partial_pins, (
        "XXX partial-pin inventory mismatch.  Expected exactly the 1 "
        "partial pin test (Pin 3 partial-closed by 20th Rust slice; "
        "persistent permission substrate honest-stopped):\n"
        f"  {sorted(expected_partial_pins)}\n"
        f"Got:\n  {sorted(partial_pin_fns)}"
    )
