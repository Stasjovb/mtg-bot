"""Genuine real-EoE cross-engine byte-equality probes -- wrath-admit-
widening lane (2026-05-21).

Two ManifestDread carriers from the ``covered_by_construction`` tier
are upgraded to the ``PROBED`` tier by this module's two probes. Both
share the SAME ``spell_effect = ManifestDread(count=1)`` shape Manifest
Dread (the eponymous Sorcery) carries — the existing
``test_cross_engine_real_eoe_manifest_dread_spell_empty_lib_parity``
probe in ``test_probe_remaining_sss.py`` pins Manifest Dread itself
through the empty-library no-op resolve. **The two new probes here
drive the SAME bridge arm through the OTHER two duskmourn.json EoE
ManifestDread carriers** (Break Down the Door — Instant, {2}{G}; Under
the Skin — Sorcery, {2}{G}) — each from the COVERED tier (every Effect
emitted has a live+bridged Rust counterpart but no genuine probe pins
that specific card).

This flips Break Down the Door + Under the Skin COVERED -> PROBED
(+2 PROBED), closing the measurement-attribution gap the wrath-admit-
widening lane opened: the
``_printing_is_bridge_simple_spell`` guardrail's Phase-3 ``(0, 0)``-
shape arm now ADMITS each card via the new ``ManifestDread`` reverse-
serializer leaf, but a genuine real-EoE byte-equal probe per card is
what credits each into the PROBED tier. **No engine change** — the
ManifestDread bridge arm + parse + resolve substrate all predate this
lane (the SSS-batch Manifest Dread probe established the round-trip
shape); this module just binds the OTHER two parsed printings carrying
the same effect class.

The ``test_cross_engine_real_eoe_pyroclasm_*`` family in
``test_probe_covered_unprobed_g.py`` already pins Pyroclasm via the
sibling ``damage_each_creature`` bridge arm (round-G), so no new
Pyroclasm probe is needed here — the wrath-admit-widening lane's
``DealNDamageToEachCreature`` reverse-serializer leaf simply makes
Pyroclasm AUTO-JOIN the spell-card-bridge admit set, no PROBED-tier
change (Pyroclasm was already PROBED at HEAD).

Honest-stop drops (out of lane scope at the wrath-admit-widening
landing; one resolved by the follow-on beyond-the-quiet-slice):
---------------------------------------

* **Beyond the Quiet** (4,698 17lands decks) — wrath shape ``(0, 0)``
  whose ``spell_effect = ExileAllCreaturesAndSpacecraft`` was NOT
  covered in Rust at the wrath-admit-widening landing. **RESOLVED by
  the follow-on beyond-the-quiet-slice (2026-05-21):** the
  ``Effect::ExileAllCreaturesAndSpacecraft`` Rust variant + bridge arm
  + reverse-serializer leaf shipped, Beyond the Quiet AUTO-JOINED the
  admit set (15 → 16; the §2 auto-grow teeth). The pre-substrate
  NEGATIVE pin here was renamed and flipped positive — see
  ``test_phase3_wrath_admit_arm_admits_beyond_the_quiet_post_substrate``.

* **Singularity Rupture** (5,046 decks) — wrath-flavored but its
  ``target_count_range = (0, 8)`` is the "destroy any number of target
  creatures" shape, NOT the ``(0, 0)`` no-target wrath shape this
  lane admits. Separate substrate (the Tier-A bespoke
  ``SingularityRuptureEffect``).

* **Mutinous Massacre** (4,671 decks) — wrath shape ``(0, 0)`` but
  emits the bespoke ``MutinousMassacreEffect`` not covered in Rust
  (BLOCKED — Effect-uncovered).

* **Zero Point Ballad** (6,041 decks) — wrath shape ``(0, 0)`` but
  emits the bespoke ``ZeroPointBalladEffect`` not covered in Rust
  (BLOCKED — Effect-uncovered).

* **Zealous Display** (3,224 decks) — wrath shape ``(0, 0)`` and
  emits the covered ``PumpCreaturesYouControlUntilEOT``, BUT carries
  the ``also_untap_if_not_your_turn=True`` rider the Rust variant
  does NOT represent (cross_engine.py:4738-4754 "Rider drops"
  paragraph). A serializer arm here would silently drop the rider,
  yielding cross-engine divergence at resolve — the no-fallback-
  hybrid discipline declines. Already PROBED via its dedicated
  effect-close probe regardless.

* **Hymn of the Faller / Decode Transmissions / Cerebral Download /
  Sami's Curiosity / Lithobraking / Glimmerburst / Commune with Evil**
  — wrath shape ``(0, 0)`` with complex Sequence / ConditionalIfVoid /
  CreateToken-with-Lander shapes the wrath-admit-widening's narrow
  serializer leaves don't claim (each is its own follow-on
  substrate). Most are already PROBED via their dedicated probes
  regardless.

* **Demonic Counsel / Midnight Mayhem / Darkness / Green Sun's
  Zenith / Consult the Star Charts / Nexus of Fate / Terminal
  Velocity** — wrath shape ``(0, 0)`` but each carries an Effect
  class whose covered/bridged status is mixed (some uncovered, some
  carry token / X / extra-turn substrate the bare bridge arms don't
  ship). Out of lane scope.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _drive_manifest_dread_empty_lib_probe(parity_smoke, card_name, ctype):
    """Drive the named ManifestDread carrier through the empty-library
    no-op resolve on BOTH engines and assert ``compare_fields == []``.

    Mirrors the
    ``test_cross_engine_real_eoe_manifest_dread_spell_empty_lib_parity``
    probe at ``tests/test_probe_remaining_sss.py:266``: empty libraries
    on both engines, ManifestDread spell on the stack, resolve →
    library still empty (short-circuit), hand still empty (no manifest),
    bf still empty, spell moves stack → caster's graveyard.

    Each named carrier (Break Down the Door — Instant; Under the Skin
    — Sorcery) MUST pass ``_printing_is_bridge_simple_spell`` (the
    wrath-admit-widening Phase-3 admit arm covers them) and MUST
    round-trip through ``_python_spell_effect_to_dict`` (the
    ManifestDread reverse-serializer leaf this lane added emits
    ``{"kind": "manifest_dread", "count": 1}`` — bit-identical to the
    bridge arm's input contract).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.library_lookat import ManifestDread

    real = get_active_source().get_printings().get(card_name)
    if real is None:
        pytest.skip(f"{card_name} absent from active CardSource")
    assert ctype in real.card_types, (
        f"{card_name} must be a {ctype}; got {real.card_types}"
    )
    se = real.spell_effect
    assert isinstance(se, ManifestDread), (
        f"genuine {card_name} spell_effect must be ManifestDread; "
        f"got {type(se).__name__}"
    )
    assert se.count == 1, (
        f"{card_name} ManifestDread count must be 1; got {se.count}"
    )

    # Wrath-admit-widening §2 teeth: the card MUST be admitted by
    # the production-deck loader's spell-card-bridge guardrail post-
    # this lane (the ``(0, 0)`` Phase-3 admit arm + ManifestDread
    # serializer leaf), AND the reverse serializer MUST emit the
    # bit-identical dict the bridge arm consumes.
    assert trajectory._printing_is_bridge_simple_spell(real) is True, (
        f"{card_name} must pass the spell-card-bridge guardrail "
        f"post-wrath-admit-widening (Phase-3 (0, 0)-shape admit arm + "
        f"ManifestDread serializer leaf)"
    )
    rt = trajectory._python_spell_effect_to_dict(se)
    assert rt == {"kind": "manifest_dread", "count": 1}, (
        f"{card_name} ManifestDread must round-trip the reverse "
        f"serializer to the bit-identical bridge-input dict; got {rt}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # Python: genuine parsed printing on the stack.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )
    assert len(py.players[0].library) == 0, (
        f"Python: p0 library must start empty for {card_name}"
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0, (
        f"Python: stack must be empty post-{card_name}-resolve; "
        f"got {len(py.stack)}"
    )
    assert len(py.players[0].library) == 0
    assert len(py.players[0].hand) == 0
    assert len(py.battlefield) == 0
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert py_gy_names == [card_name], (
        f"Python: p0 graveyard must contain {card_name}; "
        f"got {py_gy_names}"
    )

    # Rust: bridged manifest_dread synthetic carrier — type matches
    # the carrier (Instant for Break Down the Door, Sorcery for
    # Under the Skin).
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": card_name,
            "card_types": [ctype],
            "effects": [{"kind": "manifest_dread", "count": 1}],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 0
    assert rs.hand_sizes[0] == 0
    rs_bf = rs.battlefield_snapshot()
    assert len(rs_bf) == 0

    # Cross-engine byte-equality across the WHOLE field view.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"{card_name} ManifestDread spell empty-lib no-op must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


def test_cross_engine_real_eoe_break_down_the_door_manifest_dread_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Break Down the Door
    (Instant {2}{G}; spell_effect = ManifestDread(count=1)). Wrath-
    admit-widening lane covered → PROBED.**

    Sibling carrier of the SSS-batch Manifest Dread Sorcery probe
    (``test_probe_remaining_sss.py::test_cross_engine_real_eoe_
    manifest_dread_spell_empty_lib_parity``) — same ``ManifestDread
    (count=1)`` spell-effect, but driven through the INSTANT carrier
    type (flash speed; identical resolve mechanics — manifest dread is
    at-resolve, not at-cast). The wrath-admit-widening lane's Phase-3
    ``(0, 0)``-shape admit arm + the new ``ManifestDread`` reverse-
    serializer leaf admits Break Down the Door through the spell-card-
    bridge loader; this probe flips it COVERED → PROBED.

    Drives the empty-library no-op variant (Unsettling Twins N
    precedent generalized to the SPELL-EFFECT lane, then to the
    Instant carrier here): both engines fire the ManifestDread spell,
    find an empty library, short-circuit before any agent call or
    face-down manifest — byte-equal across the whole field view (the
    spell moves stack → caster's graveyard on both engines).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (hand, library, graveyard, exile,
    battlefield, stack, lives — everything byte-equal).
    """
    # Genuine-binding string-literal anchor for the slug-credit
    # detector (``scripts/measure_pool_parity.py::_PROBE_GET_PRINTING_RE``
    # matches the literal "Break Down the Door" inside this function
    # body — the credit hook the COVERED → PROBED tier flip rides on).
    from mtg_bot.cards.source import get_active_source
    real = get_active_source().get_printings().get("Break Down the Door")
    if real is None:
        pytest.skip("Break Down the Door absent from active CardSource")
    _drive_manifest_dread_empty_lib_probe(
        parity_smoke, "Break Down the Door", "Instant",
    )


def test_cross_engine_real_eoe_under_the_skin_manifest_dread_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Under the Skin
    (Sorcery {2}{G}; spell_effect = ManifestDread(count=1)). Wrath-
    admit-widening lane covered → PROBED.**

    Sibling carrier of the SSS-batch Manifest Dread Sorcery probe
    (``test_probe_remaining_sss.py::test_cross_engine_real_eoe_
    manifest_dread_spell_empty_lib_parity``) — same ``ManifestDread
    (count=1)`` spell-effect, same Sorcery carrier type, different
    printing. The wrath-admit-widening lane's Phase-3 ``(0, 0)``-shape
    admit arm + the new ``ManifestDread`` reverse-serializer leaf
    admits Under the Skin through the spell-card-bridge loader; this
    probe flips it COVERED → PROBED.

    Drives the empty-library no-op variant (Unsettling Twins N
    precedent generalized to the SPELL-EFFECT lane): both engines fire
    the ManifestDread spell, find an empty library, short-circuit
    before any agent call or face-down manifest — byte-equal across
    the whole field view (the spell moves stack → caster's graveyard
    on both engines).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (hand, library, graveyard, exile,
    battlefield, stack, lives — everything byte-equal).
    """
    # Genuine-binding string-literal anchor for the slug-credit
    # detector (``scripts/measure_pool_parity.py::_PROBE_GET_PRINTING_RE``
    # matches the literal "Under the Skin" inside this function body —
    # the credit hook the COVERED → PROBED tier flip rides on).
    from mtg_bot.cards.source import get_active_source
    real = get_active_source().get_printings().get("Under the Skin")
    if real is None:
        pytest.skip("Under the Skin absent from active CardSource")
    _drive_manifest_dread_empty_lib_probe(
        parity_smoke, "Under the Skin", "Sorcery",
    )


# ---------------------------------------------------------------------------
# Negative pin — DestroyAllCreatures bare-shape serializer declines
# narrowed variants (the wrath-admit-widening §2 teeth).
# ---------------------------------------------------------------------------


def test_destroy_all_creatures_narrowed_variant_serializer_declines():
    """**Negative pin (wrath-admit-widening §2 teeth).** The bare-shape
    ``DestroyAllCreatures()`` serializer leaf MUST bail with ``None``
    for any narrowed variant (``tapped_only`` / ``untapped_only`` /
    ``min_power``) — Rust's unit-variant ``Effect::DestroyAllCreatures``
    does NOT carry those narrowing fields, so serializing them would
    silently widen the destroy filter on Rust.

    The bare-shape narrowing-decline mirrors the ``Surveil``
    ``use_artifact_count`` decline-path in the same serializer (the
    no-fallback-hybrid discipline: a partially-translatable Effect is
    a positive bail, not a silent rider drop).

    Pinned NOT in
    ``test_cross_engine_real_eoe_<slug>_*_parity`` form because there
    is no EoE pool ``(0, 0)``-shape consumer of a narrowed
    ``DestroyAllCreatures`` (Singularity Rupture is ``(0, 8)``; Split
    Up is modal; Zero Point Ballad uses the ``min_power`` narrowing
    inside its bespoke ``ZeroPointBalladEffect`` Effect class which is
    itself uncovered, so the parent card never reaches the
    serializer). This pin guards the serializer arm directly so a
    future narrowed-shape consumer cannot be silently mis-bridged.
    """
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures

    # Bare shape: round-trips to the unit-variant dict.
    bare = DestroyAllCreatures()
    assert _python_spell_effect_to_dict(bare) == {
        "kind": "destroy_all_creatures",
    }, "bare DestroyAllCreatures must round-trip to the unit dict"

    # Any narrowing flag set → serializer bails. Rust's variant has
    # NO mirror for these fields; a serialized narrowed dict would
    # silently widen the destroy filter on Rust.
    assert _python_spell_effect_to_dict(
        DestroyAllCreatures(tapped_only=True)
    ) is None, "tapped_only=True must bail (no Rust mirror)"
    assert _python_spell_effect_to_dict(
        DestroyAllCreatures(untapped_only=True)
    ) is None, "untapped_only=True must bail (no Rust mirror)"
    assert _python_spell_effect_to_dict(
        DestroyAllCreatures(min_power=3)
    ) is None, "min_power>0 must bail (no Rust mirror)"


def test_manifest_dread_negative_count_serializer_declines():
    """**Negative pin (wrath-admit-widening §2 teeth).** The
    ``ManifestDread(count)`` serializer leaf MUST bail with ``None``
    for negative ``count`` — Rust's parse arm raises
    ``PyValueError`` on negative count at
    ``cards.rs::manifest_dread`` (mirrors the existing bridge arm's
    ``ValueError`` at ``cross_engine.py:6615+``).

    Bailing here keeps the parity surface symmetric — a negative
    count never reaches the bridge round-trip even if the printing's
    ``ManifestDread`` somehow carries one.
    """
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict
    from mtg_bot.effects.generic.library_lookat import ManifestDread

    # count=0 is a legal silent no-op (look at 0 cards = no-op) —
    # still round-trips.
    assert _python_spell_effect_to_dict(ManifestDread(count=0)) == {
        "kind": "manifest_dread", "count": 0,
    }
    # count=1 is the default printed shape — round-trips.
    assert _python_spell_effect_to_dict(ManifestDread(count=1)) == {
        "kind": "manifest_dread", "count": 1,
    }
    # Negative count — bail (mirrors Rust's parse-arm error contract).
    assert _python_spell_effect_to_dict(
        ManifestDread(count=-1)
    ) is None, "negative count must bail (mirrors Rust parse error)"


# ---------------------------------------------------------------------------
# Negative pin — Phase-3 (0, 0)-shape admit arm rejects non-wrath
# (0, 0) spells whose Effects are NOT bridged (the deferred-substrate
# bail path) AND rejects (0, 0) spells with deferred-substrate riders.
# ---------------------------------------------------------------------------


def test_phase3_wrath_admit_arm_admits_beyond_the_quiet_post_substrate():
    """**Positive pin re-anchored at the beyond-the-quiet-slice landing
    (2026-05-21).** Beyond the Quiet (4,698 17lands decks; the
    wrath-admit-widening lane's named honest-stop candidate) is a
    ``(0, 0)``-shape Sorcery whose
    ``spell_effect = ExileAllCreaturesAndSpacecraft`` is now bridged in
    Rust (the beyond-the-quiet-slice shipped
    ``Effect::ExileAllCreaturesAndSpacecraft`` + parse / to_dict /
    resolve + cross_engine.py bridge arm + the trajectory.py
    reverse-serializer leaf). The §2 auto-grow teeth fire: the printing
    is covered+bridged AND round-trips, so
    ``_printing_is_bridge_simple_spell`` admits it via the existing
    Phase-3 ``(0, 0)`` wrath admit arm — no further widening of the
    guardrail needed.

    Pre-substrate this same predicate was the wrath-admit-widening
    lane's NEGATIVE pin (the §2 teeth correctly DECLINED while the
    Effect was uncovered). The beyond-the-quiet-slice flips the three
    assertions positive — the prove-the-substrate-closed-the-gap
    invariant. The admit set grows 15 → 16 (auto-grow, no hardcoded
    list).
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.effect_coverage import covered_python_class_set
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.exile import (
        ExileAllCreaturesAndSpacecraft,
    )

    src = get_active_source().get_printings()
    btq = src.get("Beyond the Quiet")
    if btq is None:
        pytest.skip("Beyond the Quiet absent from active CardSource")
    # Sorcery, wrath shape (0, 0), no slot_kinds — the structural
    # shape the Phase-3 admit arm covers (unchanged from pre-substrate).
    assert "Sorcery" in btq.card_types
    assert btq.spell_effect.target_count_range() == (0, 0)
    assert btq.spell_effect.target_slot_kinds() == ()
    assert isinstance(btq.spell_effect, ExileAllCreaturesAndSpacecraft)
    # **Flipped POSITIVE post-substrate**: the §2 covered+bridged gate
    # now resolves positively (the Rust
    # ``Effect::ExileAllCreaturesAndSpacecraft`` variant makes the
    # Python class covered).
    assert "ExileAllCreaturesAndSpacecraft" in covered_python_class_set(), (
        "the Rust Effect::ExileAllCreaturesAndSpacecraft variant makes "
        "the Python class covered"
    )
    assert (
        trajectory._spell_effect_is_covered_and_bridged(btq) is True
    ), (
        "Beyond the Quiet's ExileAllCreaturesAndSpacecraft must be "
        "covered+bridged post-substrate"
    )
    # **Flipped POSITIVE post-substrate**: the serializer round-trips.
    rt = trajectory._python_spell_effect_to_dict(btq.spell_effect)
    assert rt == {"kind": "exile_all_creatures_and_spacecraft"}, (
        f"reverse serializer must emit the kind-only dict; got {rt}"
    )
    # Bridge round-trip back to Python (dict→Python direction).
    back = _ta_dict_to_python_effect(rt)
    assert isinstance(back, ExileAllCreaturesAndSpacecraft), (
        f"dict→Python bridge must round-trip to "
        f"ExileAllCreaturesAndSpacecraft; got {type(back).__name__}"
    )
    # **Flipped POSITIVE post-substrate**: the full guardrail admits.
    assert (
        trajectory._printing_is_bridge_simple_spell(btq) is True
    ), (
        "Beyond the Quiet must AUTO-JOIN the spell-card-bridge admit "
        "set now that ExileAllCreaturesAndSpacecraft is covered+bridged "
        "+ round-trips (§2 auto-grow teeth)"
    )


def test_phase3_wrath_admit_arm_rejects_pump_rider_zealous_display():
    """**Negative pin (wrath-admit-widening Phase-3 admit arm + §2
    teeth).** Zealous Display (3,224 17lands decks) is a ``(0, 0)``-
    shape Instant whose ``spell_effect = PumpCreaturesYouControlUntil
    EOT(power_bonus=2, also_untap_if_not_your_turn=True)`` carries
    the ``also_untap_if_not_your_turn`` rider Rust's variant does
    NOT represent.

    The §2 covered+bridged gate alone would PASS (the
    ``PumpCreaturesYouControlUntilEOT`` class IS in the live covered
    set — only its bridge arm DROPS the rider per
    ``cross_engine.py:4738-4754``). But the wrath-admit-widening lane
    deliberately does NOT add a ``PumpCreaturesYouControlUntilEOT``
    serializer leaf — adding one would silently strip the
    ``also_untap_if_not_your_turn`` rider on the round-trip, causing
    cross-engine divergence at resolve when Zealous Display's
    intrinsic "untap if not your turn" semantics no-op on Rust's
    bare 2-field variant.

    So the SECOND §2 tooth (serializer round-trip) STAYS the load-
    bearing decline — exactly the no-fallback-hybrid discipline:
    declining the card honestly rather than half-translating it.
    Zealous Display is already PROBED via its dedicated effect-close
    probe regardless.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )

    src = get_active_source().get_printings()
    zd = src.get("Zealous Display")
    if zd is None:
        pytest.skip("Zealous Display absent from active CardSource")
    assert "Instant" in zd.card_types
    assert zd.spell_effect.target_count_range() == (0, 0)
    assert zd.spell_effect.target_slot_kinds() == ()
    assert isinstance(
        zd.spell_effect, PumpCreaturesYouControlUntilEOT
    )
    # The covered+bridged check passes (the class IS covered) — only
    # the serializer leaf bail keeps the §2 teeth honest here.
    assert (
        trajectory._spell_effect_is_covered_and_bridged(zd) is True
    ), (
        "Zealous Display's PumpCreaturesYouControlUntilEOT class IS "
        "covered+bridged at the class level"
    )
    # No serializer leaf for PumpCreaturesYouControlUntilEOT → bail.
    assert (
        trajectory._python_spell_effect_to_dict(zd.spell_effect)
        is None
    ), (
        "Zealous Display must NOT serialize (no PumpCreaturesYouControl"
        "UntilEOT serializer leaf — the also_untap_if_not_your_turn "
        "rider would be silently dropped by the bare bridge arm)"
    )
    # And the full guardrail bails (the second §2 tooth fires).
    assert (
        trajectory._printing_is_bridge_simple_spell(zd) is False
    ), (
        "Zealous Display must NOT be admitted (no serializer leaf — "
        "the no-fallback-hybrid discipline)"
    )
