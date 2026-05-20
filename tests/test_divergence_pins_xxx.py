"""Divergence-pin tests: batch XXX (round 25 pin-side).

Round 25 pin batch surfacing the high-confidence divergence-pin
candidate the Survivor downstream probe agent dropped during
honest exhaustion (see commit ``1ad5b073`` -- the merge note
explicitly calls out House Cartographer's bespoke reveal-until-
land effect having no Rust resolver), plus two fresh
BLOCKED-genuinely_missing candidates from
``docs/POOL_PARITY.md`` (6-card list remaining after slice 16
closed Astelli Reclaimer).

Each pin test is named ``test_..._divergence_pin`` and ASSERTS the
CURRENT divergent behavior rather than parity.  The PROBED-tier
detector excludes ``*_divergence_pin`` functions, so these tests
grow the test surface without touching the PROBED metric.

Pin closure cadence: when a sibling Rust slice closes the
underlying gap, the relevant assertion fires and the pin is
renamed ``*_FIXED_parity`` with the sentinel inverted (PPP / MMM /
JJJ / RRR / TTT / VVV Pin 1 precedent).

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


def test_cross_engine_real_eoe_house_cartographer_reveal_until_land_no_rust_variant_divergence_pin():
    """Pin House Cartographer's Survival ETB effect lacking a Rust counterpart.

    House Cartographer's ``BEGINNING_OF_POSTCOMBAT_MAIN`` triggered
    ability resolves to ``HouseCartographerSurvivalEffect`` on the
    Python side (``src/mtg_bot/effects/bespoke.py:2667-2733``).  The
    effect's ``resolve`` implements a reveal-until-land library walk:
    pop cards from the top of the controller's library, accumulate
    non-lands, break on the first land, put the land into the
    controller's hand, then ``state.rng``-shuffle the non-lands and
    append them to the bottom of the library.  Rust's ``Effect`` enum
    has NO matching variant -- the printing's postcombat-main trigger
    body cannot round-trip through the bridge.

    Probe shape:
      1. Confirm Python's ``HouseCartographerSurvivalEffect`` class
         exists with the expected interface (``resolve`` method
         present; mutates the controller's library).
      2. Sentinel: the Rust crate's source files contain NO reference
         to ``HouseCartographerSurvivalEffect`` /
         ``house_cartographer_survival`` / ``HouseCartographer`` /
         ``house_cartographer`` / ``reveal_until_land`` -- the Rust
         side is silent on this effect today.
      3. Confirm House Cartographer is loadable + carries the
         postcombat-main triggered ability on the Python side, with
         the bespoke effect attached.

    Closure indicator:
    ``Effect::HouseCartographerSurvivalEffect`` (or a more general
    ``RevealUntilLandLibraryWalk`` shape) lands in
    ``rust/src/cards.rs``, with a parse arm + resolve arm in
    ``state_ops_resolve.rs`` + bridge arm in ``cross_engine.py``.
    Pin renames to ``..._FIXED_parity`` asserting the variant +
    parse arm + resolve arm are present.

    EoE card scale: 1 directly (House Cartographer).
    """
    # 1. Python's HouseCartographerSurvivalEffect class exists with
    #    the expected interface.
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

    # 2. Rust crate: NO reference to HouseCartographerSurvivalEffect /
    #    HouseCartographer / house_cartographer / reveal_until_land in
    #    cards.rs or state_ops_resolve.rs.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}.  "
        "If the file moved, update this test's path resolution."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    forbidden_substrings = [
        "HouseCartographer",
        "house_cartographer",
        "HouseCartographerSurvival",
        "house_cartographer_survival",
        "reveal_until_land",
        "RevealUntilLand",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no House Cartographer Effect variant exists).  "
            "If this assertion fails, the closure may have landed -- "
            "audit the Rust enum + parse arm + resolve arm and flip "
            "this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no House Cartographer resolve "
            "arm exists).  If this assertion fails, the resolve arm "
            "has landed -- flip to _FIXED_parity."
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

    # 4. EoE cards affected.
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
# Pin 2 -- Roving Actuator's RovingActuatorETBEffect bespoke effect has
#          no Rust Effect variant.  Cast-from-exile-copy-for-free
#          subsystem gap; one of 6 cards on docs/POOL_PARITY.md::BLOCKED
#          -- genuinely_missing.  1 EoE card affected: Roving Actuator.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_roving_actuator_void_etb_no_rust_variant_divergence_pin():
    """Pin Roving Actuator's Void ETB effect lacking a Rust counterpart.

    Roving Actuator's ENTERS triggered ability resolves to
    ``RovingActuatorETBEffect`` on the Python side
    (``src/mtg_bot/effects/bespoke.py:630-718``).  The effect's
    ``resolve`` implements the Void body: filter the controller's
    graveyard for instant / sorcery cards with mana value <= 2,
    exile the chosen card, copy its ``spell_effect``, and immediately
    re-resolve the copy with freshly-picked targets (without paying
    the mana cost; the copy doesn't go on the stack).  Rust's
    ``Effect`` enum has NO matching variant -- the printing's ETB
    body cannot round-trip through the bridge.  One of 6 cards on
    the ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing list; 3400
    17lands decks per ``docs/RESIDUE_CARD_PLANS.md``:96.

    Probe shape:
      1. Confirm Python's ``RovingActuatorETBEffect`` class exists
         with the expected interface (``resolve`` method present;
         filters graveyard by instant/sorcery + MV<=2; routes
         through ``spell_effect.resolve``).
      2. Sentinel: the Rust crate's source files contain NO
         reference to ``RovingActuator`` / ``roving_actuator`` /
         ``RovingActuatorETBEffect`` /
         ``VoidExileFromGYCopyAndCastForFree`` -- the Rust side is
         silent on this effect today.
      3. Confirm Roving Actuator is loadable + carries the ENTERS
         triggered ability on the Python side, with the bespoke
         effect attached.
      4. Confirm ``docs/POOL_PARITY.md``'s BLOCKED-genuinely_missing
         list contains Roving Actuator (the documented worklist
         entry for this gap).

    Closure indicator:
    ``Effect::RovingActuatorETBEffect { max_mv: u8 }`` (or a more
    general ``GraveyardExileCopyCastForFree`` shape) lands in
    ``rust/src/cards.rs``, with a parse arm + resolve arm in
    ``state_ops_resolve.rs`` + bridge arm in ``cross_engine.py``.
    Pin renames to ``..._FIXED_parity`` asserting the variant +
    parse arm + resolve arm are present.

    EoE card scale: 1 directly (Roving Actuator; 3400 17lands decks).
    """
    # 1. Python's RovingActuatorETBEffect class exists with the
    #    expected interface.
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

    # 2. Rust crate: NO reference to RovingActuator / roving_actuator
    #    / VoidExileFromGYCopyAndCastForFree in cards.rs or
    #    state_ops_resolve.rs.
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

    forbidden_substrings = [
        "RovingActuator",
        "roving_actuator",
        "RovingActuatorETBEffect",
        "roving_actuator_etb",
        "VoidExileFromGYCopyAndCastForFree",
        "void_exile_from_gy_copy_and_cast_for_free",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no Roving Actuator Effect variant exists).  "
            "If this assertion fails, the closure may have landed -- "
            "audit the Rust enum + parse arm + resolve arm and flip "
            "this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no Roving Actuator resolve arm "
            "exists)."
        )

    # 3. Roving Actuator is loadable + carries the expected ETB trigger.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("Roving Actuator")
    assert pr is not None, (
        "Pin invariant: 'Roving Actuator' should be present in the "
        "active CardSource (per docs/POOL_PARITY.md BLOCKED-"
        "genuinely_missing list).  If missing, the EoE data file "
        "was regenerated -- update this pin."
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

    # 4. POOL_PARITY's BLOCKED-genuinely_missing list contains Roving
    #    Actuator (the documented worklist entry for this gap).
    pool_parity_path = repo_root / "docs" / "POOL_PARITY.md"
    assert pool_parity_path.exists(), (
        f"docs/POOL_PARITY.md should exist at {pool_parity_path!r}."
    )
    pool_parity_src = pool_parity_path.read_text(encoding="utf-8")
    assert "Roving Actuator" in pool_parity_src, (
        "Pin invariant: docs/POOL_PARITY.md should list 'Roving "
        "Actuator' (the BLOCKED-genuinely_missing entry).  If "
        "absent, the worklist was updated -- audit this pin's "
        "BLOCKED status."
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
#          EachOpponentExilesCardFromHandWithCastPermission effect has
#          no Rust Effect variant.  Persistent
#          play-from-exile-with-surcharge permission subsystem gap;
#          one of 6 cards on docs/POOL_PARITY.md::BLOCKED --
#          genuinely_missing.  1 EoE card affected: Lightstall
#          Inquisitor.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lightstall_inquisitor_exile_with_cast_permission_no_rust_variant_divergence_pin():
    """Pin Lightstall Inquisitor's ETB effect lacking a Rust counterpart.

    Lightstall Inquisitor's ENTERS triggered ability resolves to
    ``EachOpponentExilesCardFromHandWithCastPermission`` on the
    Python side (``src/mtg_bot/effects/generic/discard.py:172-214``).
    Each opponent exiles a card from their hand and may play that
    card for as long as it remains exiled; each spell cast this way
    costs {1} more; each land played this way enters tapped.  The
    exiled card is tagged
    ``cast_from_exile_with_lightstall_surcharge=True``, and
    ``legal.py`` + ``actions.py`` + ``game.py`` honour the flag to
    grant + enforce the permission, surcharge, and tapped-entry
    riders.  Rust's ``Effect`` enum has NO matching variant and no
    awareness of the sticky flag.  One of 6 cards on the
    ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing list; 4371
    17lands decks per ``docs/RESIDUE_CARD_PLANS.md``:94.

    Probe shape:
      1. Confirm Python's
         ``EachOpponentExilesCardFromHandWithCastPermission`` class
         exists with the expected interface (``resolve`` method
         present; iterates non-controller alive players; routes
         through ``choose_discard``; tags
         ``cast_from_exile_with_lightstall_surcharge``).
      2. Sentinel: the Rust crate's source files contain NO
         reference to ``Lightstall`` / ``lightstall`` /
         ``EachOpponentExilesCardFromHand`` /
         ``cast_from_exile_with_lightstall_surcharge`` -- the Rust
         side is silent on this effect today.
      3. Confirm Lightstall Inquisitor is loadable + carries the
         ENTERS triggered ability on the Python side, with the
         expected effect attached.
      4. Confirm ``docs/POOL_PARITY.md``'s BLOCKED-genuinely_missing
         list contains Lightstall Inquisitor (the documented
         worklist entry for this gap).

    Closure indicator:
    ``Effect::EachOpponentExilesCardFromHandWithCastPermission`` (or
    a more general
    ``EachOpponentExilesFromHandMayPlayCostHike`` shape) lands in
    ``rust/src/cards.rs``, with a parse arm + resolve arm in
    ``state_ops_resolve.rs`` + bridge arm in ``cross_engine.py`` +
    the persistent-cast-from-exile-with-surcharge permission
    substrate.  Pin renames to ``..._FIXED_parity`` asserting the
    variant + parse arm + resolve arm are present.

    EoE card scale: 1 directly (Lightstall Inquisitor; 4371 17lands
    decks).
    """
    # 1. Python's EachOpponentExilesCardFromHandWithCastPermission
    #    class exists with the expected interface.
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

    # 2. Rust crate: NO reference to Lightstall / lightstall /
    #    EachOpponentExilesCard /
    #    cast_from_exile_with_lightstall_surcharge in cards.rs or
    #    state_ops_resolve.rs.
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

    forbidden_substrings = [
        "Lightstall",
        "lightstall",
        "LightstallInquisitor",
        "lightstall_inquisitor",
        "EachOpponentExilesCardFromHand",
        "each_opponent_exiles_card_from_hand",
        "cast_from_exile_with_lightstall_surcharge",
        "EachOpponentExilesFromHandMayPlayCostHike",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no Lightstall Inquisitor Effect variant "
            "exists).  If this assertion fails, the closure may have "
            "landed -- audit the Rust enum + parse arm + resolve arm "
            "and flip this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no Lightstall Inquisitor "
            "resolve arm exists)."
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

    # 4. POOL_PARITY's BLOCKED-genuinely_missing list contains
    #    Lightstall Inquisitor.
    pool_parity_path = repo_root / "docs" / "POOL_PARITY.md"
    assert pool_parity_path.exists(), (
        f"docs/POOL_PARITY.md should exist at {pool_parity_path!r}."
    )
    pool_parity_src = pool_parity_path.read_text(encoding="utf-8")
    assert "Lightstall Inquisitor" in pool_parity_src, (
        "Pin invariant: docs/POOL_PARITY.md should list 'Lightstall "
        "Inquisitor' (the BLOCKED-genuinely_missing entry).  If "
        "absent, the worklist was updated -- audit this pin's "
        "BLOCKED status."
    )

    # 5. EoE cards affected.
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
    """Sanity check: the XXX batch declares exactly 3 pin tests.

    Pin batch XXX (round 25 pin-side) targets 3 divergence pins per
    the lane discipline; this guards against accidental deletion or
    rename of any pin function.
    """
    import tests.test_divergence_pins_xxx as _self_mod
    pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_divergence_pin")
    ]
    expected_pins = {
        "test_cross_engine_real_eoe_house_cartographer_reveal_until_land_no_rust_variant_divergence_pin",
        "test_cross_engine_real_eoe_roving_actuator_void_etb_no_rust_variant_divergence_pin",
        "test_cross_engine_real_eoe_lightstall_inquisitor_exile_with_cast_permission_no_rust_variant_divergence_pin",
    }
    assert set(pin_fns) == expected_pins, (
        "XXX pin inventory mismatch.  Expected exactly the 3 pin tests:\n"
        f"  {sorted(expected_pins)}\n"
        f"Got:\n  {sorted(pin_fns)}"
    )
