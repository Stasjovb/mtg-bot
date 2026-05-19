"""Genuine real-EoE cross-engine byte-equality probes — batch TT (round 14).

CONTINUOUS-PIPELINE phase: convert covered-by-construction EoE cards into
the strongest parity-evidence tier (``PROBED byte-equal`` per
``docs/POOL_PARITY.md`` / ``scripts/measure_pool_parity.py``) via genuine
real-EoE cross-engine probes.

Surface state at HEAD (b2c5756c): PROBED = 171 cards,
Covered-by-construction = 139.  The covered-but-unprobed surface is
structurally narrow (most blocked by Room-gated ETB, unbridged events,
non-bridged predicates, dropped riders with no observable PT delta, or
equipment/aura attachment mechanics).  This batch picks from the remaining
clean accessible substrate.

Probes in this module
---------------------

  1. **Come Back Wrong** — ``Sorcery {2}{B}``.  Parsed
     ``spell_effect = DestroyTargetCreature()``.  The ``destroy_target``
     bridge arm is already PROBED-level evidence via Murder (batch J).
     This probe moves the CARD itself from covered-by-construction to the
     stronger individually-PROBED tier.  Full ``compare_fields``.

  2. **Seized from Slumber** — ``Instant {1}{B}``.  Parsed
     ``spell_effect = DestroyTargetCreature()``.  Same ``destroy_target``
     arm as Come Back Wrong and Murder; this probe individually upgrades
     the card's evidence tier.  Full ``compare_fields``.

  3. **Glimmerlight** — ``Artifact {1}{W}``.  Parsed ETB trigger:
     ``(ENTERS, IsSelf, CreateToken(Glimmer 1/1 Enchantment+Creature,
     count=1))``.  The ``create_token`` bridge arm is proven via
     Tunnel Surveyor (batch H) which created the same Glimmer token.
     Glimmerlight is an Artifact (not a Creature), so this probe also
     verifies that the ETB create-token path fires correctly for
     non-Creature permanent types.  Full ``compare_fields``.

  4. **Fear of Surveillance** — ``Enchantment Creature {2}{U} 2/2``.
     Parsed ATTACKS trigger: ``(ATTACKS, IsSelf, Surveil(amount=1))``.
     The ``attacks/source_is_self/surveil`` triple is validated by
     ``test_audit_safe_trigger_attacks_self_surveil_byte_equal``
     (``test_trajectory_parity.py:6033``) and the Starbreach Whale
     ETB-surveil probe (batch Starbreach).  This probe moves Fear of
     Surveillance from covered-by-construction to individually-PROBED.
     Fear of Surveillance has ``vigilance`` (attacking doesn't tap it);
     the Rust synthetic carrier passes ``"keywords": ["vigilance"]`` so
     both engines skip the tap step.  No-agent surveil(1) keeps all cards
     on top; library size is unchanged.  Full ``compare_fields``.

DROPPED CANDIDATES
------------------

  * **Temporal Intervention** — ``TargetOpponentDiscardsCasterChoice``
    (caster picks which card opponent discards).  The ``discard_card``
    bridge arm maps to ``TargetOpponentDiscards`` (opponent's own agent
    picks) — a different resolution semantic.  Excluded per batch-P
    documentation.

  * **Innocuous Rat / Bashful Beastie** — ``dies/IsSelf/ManifestDread``.
    ManifestDread on the DIES path creates a face-down permanent from the
    top of the library.  The empty-library path (no card to manifest) is
    already probed by Unsettling Twins (batch N).  The non-empty-library
    path requires a ``choose_card_from_library`` agent hook cross-engine
    and faces the face-down ETB-trigger fan-out complexity documented in
    the ``manifest_dread`` bridge arm comment at ``cross_engine.py:6366``.
    Excluded pending a dedicated DIES-ManifestDread slice.

  * **Appendage Amalgam** — ``attacks/IsSelf/Surveil(1)``.  Same trigger
    shape as Fear of Surveillance (probe #4 above).  Adding a second probe
    with the identical bridge triple in the same batch adds no new bridge
    coverage; Appendage Amalgam remains covered-by-construction.

  * **Clammy Prowler** — ``attacks/IsSelf/GrantUnblockableUEOT`` with a
    complex 2-subject target filter (attacking-and-not-source creature).
    The ``grant_unblockable_ueot`` bridge arm carries no ``targets``
    narrowing; a clean byte-equal probe requires the two-subject predicate
    API that is out of scope for a non-Rust slice.  Excluded.

  * **Come Back Wrong / Seized from Slumber** — batch-P dropped these as
    "low marginal value" (same bridge arm as Murder).  This batch
    re-includes them because each card individually advances from the
    ``covered_by_construction`` tier to the stronger ``PROBED`` tier, per
    the Trial-of-Agony precedent in batch P (note at batch-P line 132:
    "the CARD gains PROBED status by being driven via its ACTUAL parsed
    printing").

ASSERTION STRENGTH
------------------
All four probes assert full ``compare_fields() == []`` (byte-equality
over the whole cross-engine field view — the strongest assertion the
harness supports).
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
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there).  Module-scoped fixture — identical pattern used
    in all other batch-probe files; copied here so this module is
    fully self-contained."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 — Come Back Wrong: DestroyTargetCreature (Sorcery)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_come_back_wrong_destroy_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Come Back Wrong.**

    Oracle: "[Sorcery] {2}{B} — Destroy target creature."

    Parser → ``spell_effect = DestroyTargetCreature()``.

    The ``destroy_target`` bridge arm is already PROBED via Murder (batch J).
    This probe individually upgrades Come Back Wrong from the
    ``covered_by_construction`` tier to the stronger ``PROBED`` tier, per
    the Trial-of-Agony precedent (same bridge arm as earlier probes, but
    the CARD gains PROBED status from its own genuine probe run).

    PROBE FLOW
    ----------
    1. Seat a single vanilla 2/2 Creature on p1's bf (the legal
       ``any_creature`` target on BOTH engines).
    2. Python: genuine parsed Come Back Wrong on a ``StackItem``, target =
       p1's creature.  Rust: synthetic Sorcery with ``destroy_target`` +
       ``any_creature`` filter.
    3. Drain both stacks.  p1's creature is destroyed (lands in graveyard)
       on BOTH engines.

    ASSERTION STRENGTH: full ``compare_fields`` over the whole cross-engine
    field view (p1's graveyard carries the destroyed 2/2; battlefield
    empty).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Come Back Wrong")
    if real is None:
        pytest.skip("Come Back Wrong absent from active CardSource")
    assert "Sorcery" in real.card_types, (
        "Come Back Wrong must be a Sorcery"
    )
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Come Back Wrong spell_effect must be DestroyTargetCreature;"
        f" got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- p1 has a single vanilla 2/2 creature — the legal target. ----
    py_vic = py.new_object(
        CardPrinting(
            name="CBW Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "CBW Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Come Back Wrong on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: synthetic Sorcery carrying the covered destroy_target arm. --
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Come Back Wrong", "card_types": ["Sorcery"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"CBW Victim must be destroyed on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Come Back Wrong destroy-creature arm must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Seized from Slumber: DestroyTargetCreature (Instant)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_seized_from_slumber_destroy_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Seized from Slumber.**

    Oracle: "[Instant] {1}{B} — Destroy target creature."

    Parser → ``spell_effect = DestroyTargetCreature()``.

    Same ``destroy_target`` bridge arm as Come Back Wrong (probe #1) and
    Murder (batch J).  This probe individually upgrades Seized from Slumber
    from ``covered_by_construction`` to ``PROBED``.

    PROBE FLOW
    ----------
    Mirrors probe #1 exactly: a single vanilla 2/2 on p1's bf is destroyed
    by the genuine Instant printing (Python) and the synthetic
    ``destroy_target`` carrier (Rust).

    ASSERTION STRENGTH: full ``compare_fields``.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Seized from Slumber")
    if real is None:
        pytest.skip("Seized from Slumber absent from active CardSource")
    assert "Instant" in real.card_types, (
        "Seized from Slumber must be an Instant"
    )
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Seized from Slumber spell_effect must be DestroyTargetCreature;"
        f" got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- p1 has a single vanilla 2/2 creature — the legal target. ----
    py_vic = py.new_object(
        CardPrinting(
            name="SFS Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "SFS Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Seized from Slumber on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: synthetic Instant carrying the covered destroy_target arm. --
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Seized from Slumber", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"SFS Victim must be destroyed on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Seized from Slumber destroy-creature arm must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Glimmerlight: ETB/IsSelf/CreateToken(Glimmer 1/1, count=1)
# (Artifact — not a Creature)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_glimmerlight_etb_create_glimmer_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Glimmerlight.**

    Oracle: "[Artifact — Equipment] {1}{W}
      When Glimmerlight enters, create a 1/1 white Glimmer enchantment
      creature token.
      Equip {2}."

    Parser → ETB trigger: ``(ENTERS, IsSelf, CreateToken(Glimmer 1/1
    Enchantment+Creature, count=1))``.

    The ``create_token`` bridge arm + Glimmer token are already proven by
    the Tunnel Surveyor probe (batch H).  Glimmerlight is an Artifact (not
    a Creature), making this the first real-EoE probe verifying that the
    ETB create-token path fires correctly for a non-Creature permanent type.

    INJECTION PATTERN (inject-to-bf, not push-to-stack)
    ----------------------------------------------------
    Non-Creature Artifacts entering via ``resolve_top_of_stack`` exhibit a
    known ``summoning_sick`` representation gap: Python's
    ``actions.py:2993`` sets ``obj.summoning_sick = True`` on ALL newly-
    landed permanents (including Artifacts), while Rust's
    ``register_and_inject_object`` leaves ``summoning_sick = False`` for
    non-Creature permanents (only Creatures are tracked as summoning-sick
    in Rust).  To avoid this gap, this probe uses the inject-to-bf idiom:

      * Rust: ``register_and_inject_object(dict, 0, ZONE_BATTLEFIELD)``
        injects directly and fires ``ENTERS`` via
        ``drain_pending_etb_dispatches`` (CE4 / RS8 Slice 2 — automatic
        ETB fan-out for bf injections).  The injected Artifact has
        ``summoning_sick = False`` by convention.
      * Python: ``new_object(real, 0, Zone.BATTLEFIELD)`` + manual
        ``summoning_sick = False`` + ``battlefield.append`` +
        ``_trigger_etb_abilities(py, py_obj)`` (the same ETB-dispatch
        path ``actions.py:3130`` calls after ``cast_creature`` lands).

    Both engines therefore have Glimmerlight with ``summoning_sick=False``
    on the battlefield after injection; the resulting field view is
    byte-equal for a full ``compare_fields`` assertion.

    PROBE FLOW
    ----------
    1. Pre-register the Glimmer token pid on Rust (established token-pid
       idiom).  Register the Python counterpart via
       ``register_token_printing``.
    2. Inject Glimmerlight directly to p0's bf on BOTH engines; the ENTERS
       event fires → IsSelf predicate matches → ``CreateToken(Glimmer, 1)``
       lands on the stack.
    3. Drain both stacks → 1 Glimmer token spawns on p0's bf on BOTH.

    ASSERTION STRENGTH: full ``compare_fields`` over the whole cross-engine
    field view (Glimmerlight + 1 Glimmer token on p0's bf on BOTH; lives
    unchanged; hands/libraries/graveyards unchanged except for the library
    pid-seed inert card removed below).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack, _trigger_etb_abilities
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.tokens import CreateToken

    real = get_active_source().get_printings().get("Glimmerlight")
    if real is None:
        pytest.skip("Glimmerlight absent from active CardSource")
    assert "Artifact" in real.card_types, (
        "Glimmerlight must be an Artifact"
    )
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Glimmerlight must have an ENTERS triggered ability"
    assert isinstance(etb.effect, CreateToken), (
        f"genuine Glimmerlight ETB must be CreateToken;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.token_printing.name == "Glimmer", (
        f"Glimmerlight ETB must create a Glimmer token;"
        f" got {etb.effect.token_printing.name!r}"
    )
    assert etb.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Pre-register the Glimmer token pid on Rust (established token-pid idiom).
    # Must be done BEFORE injecting the carrier so the create_token bridge arm
    # can look up the Python printing by pid at trigger-dict parse time.
    glimmer_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Glimmer", "card_types": ["Enchantment", "Creature"],
         "supertypes": ["Token"], "power": 1, "toughness": 1,
         "mana_cost": {"generic": 0}},
        0, 1,  # owner=0, ZONE_LIBRARY (inert pid seed — not used in play)
    )
    register_token_printing(glimmer_pid, TOKEN_PRINTINGS["Glimmer"])

    py_seed = py.new_object(
        TOKEN_PRINTINGS["Glimmer"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ---- Rust: inject Glimmerlight directly onto p0's bf (inject-to-bf
    # idiom: avoids the resolve_top_of_stack summoning_sick gap for
    # non-Creature Artifacts).  register_and_inject_object onto
    # ZONE_BATTLEFIELD fires ENTERS via drain_pending_etb_dispatches
    # (CE4 / RS8 Slice 2 — automatic ETB fan-out for bf injections). ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Glimmerlight",
            "card_types": ["Artifact"],
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token",
                        "count": 1,
                        "token_printing_id": glimmer_pid,
                    },
                }
            ],
        },
        0, ZB,  # inject directly to ZONE_BATTLEFIELD
    )
    assert rs.find_object_zone(rs_id) == ZB, (
        "Glimmerlight carrier must be on Rust battlefield after inject"
    )
    assert rs.stack_size() == 1, (
        "ETB trigger should be on the Rust stack after inject-to-bf"
    )

    # ---- Python: inject genuine Glimmerlight directly onto p0's bf.
    # Manual summoning_sick=False (Artifact, not sick) + ETB fire via
    # _trigger_etb_abilities (same path actions.py:3130 uses after
    # cast_creature). ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    _trigger_etb_abilities(py, py_obj)
    assert any(o.printing.name == "Glimmerlight"
               for o in py.battlefield), (
        "Glimmerlight should be on p0's Python battlefield after inject"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after inject-to-bf"
    )

    # ---- Drain both stacks (CreateToken resolves: 1 Glimmer spawns). ---
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # Concrete observable: exactly 1 Glimmer token on p0's bf on BOTH.
    rs_glimmer_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Glimmer"
    )
    py_glimmer_n = sum(
        1 for o in py.battlefield if o.printing.name == "Glimmer"
    )
    assert rs_glimmer_n == 1 == py_glimmer_n, (
        f"Glimmerlight ETB → exactly 1 Glimmer on BOTH; "
        f"rust={rs_glimmer_n} py={py_glimmer_n}"
    )

    # NOTE: both Python and Rust libraries each contain 1 Glimmer
    # pid-seed object (identical name/pt/state on both sides); these
    # match in the compare_fields assertion.  The Tunnel Surveyor probe
    # uses the exact same pattern (seed → both libs → seed matches).

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Glimmerlight ETB create-glimmer-token must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 4 — Fear of Surveillance: ATTACKS/IsSelf/Surveil(amount=1)
# (Enchantment Creature, vigilance)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_fear_of_surveillance_attacks_surveil_one_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Fear of Surveillance.**

    Oracle: "[Enchantment Creature — Nightmare] {2}{U} 2/2
      Vigilance
      Whenever Fear of Surveillance attacks, surveil 1."

    Parser → ATTACKS trigger: ``(ATTACKS, IsSelf, Surveil(amount=1))``.

    The ``attacks/source_is_self/surveil`` triple is validated by
    ``test_audit_safe_trigger_attacks_self_surveil_byte_equal``
    (``test_trajectory_parity.py:6033``) and the Starbreach Whale ETB-
    surveil probe (``test_parity_smoke.py:14453``).  This probe moves
    Fear of Surveillance from covered-by-construction to individually-
    PROBED.

    VIGILANCE HANDLING
    ------------------
    Fear of Surveillance has ``vigilance`` — attacking does not tap it.
    The Python side uses the real parsed printing pre-seated on p0's bf;
    ``declare_attackers`` skips the tap step for vigilance creatures.
    The Rust synthetic carrier passes ``"keywords": ["vigilance"]`` so
    ``declare_attacker`` (which reads ``battlefield_has_vigilance``) also
    skips the tap step.  Both engines leave Fear of Surveillance
    untapped after declaring it as an attacker, ensuring the tapped state
    does not diverge in the ``compare_fields`` assertion.

    SURVEIL DECISION CONTRACT
    -------------------------
    No-agent surveil(1): both engines default to "keep on top" when no
    agent is seated.  Python's ``Surveil.resolve`` short-circuits at
    ``if p.agent is None`` (``library_lookat.py:605``) and preserves
    the card on top.  Rust's ``auto_resolve_pending("keep_all_on_top")``
    does the same.  Net library shape: unchanged (1 bait card stays on
    top on both engines).

    PROBE FLOW
    ----------
    1. Seed p0's library with 1 bait card (so surveil(1) observes it,
       keeps it on top, and library size stays 1 on both engines).
    2. Python: pre-seat genuine Fear of Surveillance on p0's bf
       (unsick, untapped); call ``declare_attackers([fos_id])``.  The
       ATTACKS trigger fires: ``Surveil(1)`` is pushed onto the stack.
       Drain both stacks.
    3. Rust: inject synthetic Enchantment+Creature carrier with
       ``"keywords": ["vigilance"]`` and the ``attacks/source_is_self/
       surveil`` trigger dict onto p0's bf; call ``declare_attacker``.
       Same drain.

    ASSERTION STRENGTH: full ``compare_fields`` over the whole cross-engine
    field view (Fear of Surveillance untapped on p0's bf; library size
    unchanged; no graveyard changes; lives unchanged).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_triggered_ability, CardDef,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.library_lookat import Surveil

    real = get_active_source().get_printings().get("Fear of Surveillance")
    if real is None:
        pytest.skip("Fear of Surveillance absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Fear of Surveillance must be a Creature"
    )
    assert "Enchantment" in real.card_types, (
        "Fear of Surveillance must also be an Enchantment"
    )
    assert "vigilance" in (real.keywords or frozenset()), (
        "Fear of Surveillance must have vigilance"
    )
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Fear of Surveillance must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, Surveil), (
        f"Fear of Surveillance ATTACKS effect must be Surveil;"
        f" got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.amount == 1, (
        f"Fear of Surveillance ATTACKS surveil must be amount=1;"
        f" got {attacks_ta.effect.amount}"
    )

    # 1 bait card in p0's library — surveil(1) observes and keeps it on top.
    filler = CardDef(name="FOS Bait", card_type="Land", mana_produced=("U",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("FOS Bait",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ATTACKS trigger dict for synthetic carrier construction.
    fos_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }

    # ---- Rust: synthetic Enchantment+Creature carrier with vigilance. --
    rs_id = rs.register_and_inject_object(
        {
            "name": "Fear of Surveillance",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": ["vigilance"],
            "effects": [],
            "triggered_abilities": [fos_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for an unsick Fear of Surveillance"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger must be on the stack after declaring"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0, "Rust stack must be empty after drain"
    assert rs.library_sizes[0] == 1, (
        "Rust: FOS Bait must stay on top (no-agent surveil keeps it)"
    )

    # ---- Python: genuine Fear of Surveillance pre-seated on p0's bf. ---
    # Use the real parsed printing so the ATTACKS trigger fires from the
    # genuine printing's trigger_abilities (IsSelf → Surveil(1)).
    py_printing = CardPrinting(
        name="Fear of Surveillance",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Enchantment Creature",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset({"vigilance"}),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(fos_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be on the stack after declaring"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.players[0].library) == 1, (
        "Python: FOS Bait must stay on top (no-agent surveil keeps it)"
    )

    # Concrete observable: library size unchanged (bait card kept on top).
    assert rs.library_sizes[0] == len(py.players[0].library) == 1, (
        "Library size must be 1 on BOTH engines after no-agent surveil(1)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fear of Surveillance ATTACKS surveil-1 must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
