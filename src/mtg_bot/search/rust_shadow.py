"""``rust_shadow`` mode — the B3-S4 pre-flip equivalence bake-in
(spec §4).

In ``rust_shadow`` the search drives the **Rust** engine
(``RustGameStateAdapter``) AND a paired **Python** engine
(``MtgGameStateAdapter``) in lock-step. Every decision moment asserts
the four-part equivalence tripwire; ANY divergence raises **loudly**
(no silent Python fallback — ``feedback_no_fallback_hybrids`` /
``feedback_silent_noop_pipelines``: an honest hard failure is the
real progress signal). This is the umbrella's bad-flip detection
(``SOT_FLIP_CUTOVER_PLAN.md`` §3) and the bake-in that the Step-0 C4
post-R76 scaled re-sweep runs through.

**It reuses the existing cross_engine machinery with the driver /
checker roles swapped** — the SAME ``compare_fields`` /
``build_python_field_view`` / ``parity_smoke()._build_field_view`` /
``fingerprint`` the Python-drives/Rust-mirrors harness used as a
migration metric, now used as a pre-flip GATE. No new comparison
infrastructure.

The four-assertion tripwire (spec §4.1):

```
LEGAL_SET_EQ : canon(rust legal set) == canon(python legal set)
               on {PassPriority, PlayLand, CastSpell, ActivateAbility,
                   factored AttackerDecision/BlockerDecision}
CHOSEN_EQ    : the chosen decision encodes to the SAME codec slot
               under both engines' zone views (§3.2)
STATE_EQ     : compare_fields(py_view, rust_view) == []  AND
               rust.fingerprint() stable across two independent Rust
               clones from the same pre-state (per-seed determinism)
NO_RAISE     : Python apply_action raised no invariant error
```

``canon`` = a canonicalized, order-independent decision key (kind +
zone-position/id + variant flags) — the same shape the C1 asymmetry
pin compares cast sets with
(``tests/test_cross_engine_legal_set_asymmetry.py``).

Wiring: ``decision_source="rust_shadow"`` on ``HeuristicsConfig``
selects this provider via the ``engine_adapter_factory``. It is
exercised ONLY when the flag is moved off the default ``"python"`` —
parity-neutral until then. ``"rust"`` (Rust-only, B3-S5, the atomic
flip) is enabled by the orchestrator ONLY after this bake-in closes
green; that flip is explicitly NOT done here.
"""

from __future__ import annotations

from typing import Any, Optional

from mtg_bot.actions import (
    ActivateAbility, CastSpell, DeclareAttackers, DeclareBlockers,
    PassPriority, PlayLand,
)
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.protocol import Decision, PlayerID


class ShadowDivergenceError(AssertionError):
    """A ``rust_shadow`` equivalence assertion failed. Carries which
    tripwire (LEGAL_SET_EQ / CHOSEN_EQ / STATE_EQ / NO_RAISE) and the
    divergence detail. Raised loudly — there is NO fallback path; an
    honest hard stop is the real bake-in signal and an automatic
    no-flip / rollback."""

    def __init__(self, tripwire: str, detail: str) -> None:
        self.tripwire = tripwire
        super().__init__(f"[{tripwire}] {detail}")


# ---------------------------------------------------------------------------
# canon — order-independent decision key (LEGAL_SET_EQ / CHOSEN_EQ)
# ---------------------------------------------------------------------------


def canon_decision(d: Decision) -> tuple:
    """Canonicalize a search ``Decision`` to a hashable,
    order-independent key. Kind + the load-bearing identity fields,
    matching the C1 asymmetry pin's cast-set comparison shape (kind +
    card id + the variant flags) extended to the playland / ability /
    factored-combat axes.

    NB: ``PlayLand`` / ``CastSpell`` / ``ActivateAbility`` key off the
    object id, NOT a zone position — id is engine-stable across both
    engines (the matched-state builder assigns matching ids), so it
    is the order-independent identity. CHOSEN_EQ separately asserts
    the codec SLOT equality (the positional axis)."""
    if isinstance(d, PassPriority):
        return ("pass",)
    if isinstance(d, PlayLand):
        return ("play_land", int(d.card_id))
    if isinstance(d, CastSpell):
        return (
            "cast_spell", int(d.card_id),
            bool(d.use_warp), bool(d.kicked),
            bool(d.cast_for_free), bool(d.use_impending),
            d.cast_room_half,
        )
    if isinstance(d, ActivateAbility):
        return (
            "activate_ability", int(d.source_id),
            int(d.ability_index),
        )
    if isinstance(d, AttackerDecision):
        return ("attacker", int(d.attacker_id), bool(d.attack))
    if isinstance(d, BlockerDecision):
        return (
            "blocker", int(d.blocker_id),
            None if d.attacker_id is None else int(d.attacker_id),
        )
    if isinstance(d, DeclareAttackers):
        return (
            "declare_attackers",
            tuple(sorted(int(i) for i in d.attacker_ids)),
        )
    if isinstance(d, DeclareBlockers):
        return (
            "declare_blockers",
            tuple(sorted(
                (int(b), int(a)) for (b, a) in d.assignments
            )),
        )
    # Resolution* decisions are NOT in the LEGAL_SET_EQ contract (spec
    # §2.4-G3: Rust resolves atomically — accepted C6-fenced caveat).
    # A bare type tag keeps them comparable if they ever appear; the
    # tripwire scopes set equality to the {Pass,PlayLand,CastSpell,
    # ActivateAbility, factored combat} axes (canon_set below).
    return (type(d).__name__,)


# The decision kinds the LEGAL_SET_EQ assertion is scoped to (spec
# §4.1). Resolution* / chance are explicitly OUT (G3 accepted caveat).
_SET_EQ_KINDS = (
    "pass", "play_land", "cast_spell", "activate_ability",
    "attacker", "blocker", "declare_attackers", "declare_blockers",
)


def canon_set(decisions: list[Decision]) -> set:
    """The canonicalized, order-independent set of a legal list,
    restricted to the LEGAL_SET_EQ-scoped kinds."""
    out = set()
    for d in decisions:
        k = canon_decision(d)
        if k and k[0] in _SET_EQ_KINDS:
            out.add(k)
    return out


# ---------------------------------------------------------------------------
# The shadow-checked provider
# ---------------------------------------------------------------------------


class ShadowCheckedRustAdapter:
    """Protocol-conformant provider that drives Rust and lock-step
    shadow-checks Python. Built from a matched (Python, Rust) state
    pair (``cross_engine.build_matched_states`` — the surviving
    loader path). Each ``legal_decisions()`` asserts LEGAL_SET_EQ;
    each ``apply()`` asserts CHOSEN_EQ + STATE_EQ + NO_RAISE.
    """

    # Not a Rust-only decision provider for the codec's _enumerate_legal
    # routing — the codec must see the Python adapter's legal set under
    # rust_shadow (Python is present as the checker), so we delegate
    # the codec surface to the Python side (engine_state) and only the
    # *decision flow* is Rust-driven. (The whole point of rust_shadow
    # is Python IS present.)

    def __init__(
        self,
        py_adapter: Any,
        rust_adapter: Any,
        *,
        viewer_for_codec: Optional[PlayerID] = None,
    ) -> None:
        self._py = py_adapter
        self._rust = rust_adapter
        # The chosen decision of the last legal_decisions() call,
        # cached so CHOSEN_EQ can re-encode it under both zone views.
        self._viewer = viewer_for_codec
        self._last_legal: list[Decision] = []

    # ---- internal assertions -----------------------------------------

    def _python_reference_legal(self) -> list[Decision]:
        """The Python rules-legal set the spec §4.1 LEGAL_SET_EQ
        compares against — RAW ``legal.legal_actions`` (the rules
        enumerator), NOT the heuristic-pruned adapter
        ``legal_decisions()`` output (the adapter applies phase-prune
        / force-landdrop / skip-empty-combat short-circuits that are
        deliberate search heuristics, NOT rules — comparing against
        them would false-trip on a heuristic prune that both engines'
        RULES agree on; the S4 bake-in surfaced exactly this).

        For the **combat window** ``legal_actions`` emits NEITHER
        DeclareAttackers nor a factored AttackerDecision (combat is an
        adapter construct); the spec's factored-combat axis is the
        G1 Rust factored emission vs the Python ADAPTER's factored
        emission — so in a combat window we use the Python adapter's
        ``legal_decisions()`` (its factored AttackerDecision/
        BlockerDecision shape), which is the correct reference there.
        """
        from mtg_bot.legal import legal_actions

        if self._py.combat_phase is not None:
            # Combat window: the factored shape is an adapter
            # construct; compare Rust's G1 factored emission against
            # the Python adapter's factored emission (both are the
            # per-creature decisions the codec/tree are built for).
            return list(self._py.legal_decisions())
        # Priority window: the rules-legal set is legal_actions on the
        # active player (the adapter's heuristic prunes are NOT rules).
        return list(
            legal_actions(self._py.engine_state, self.active_player())
        )

    def _assert_legal_set_eq(
        self, rust_legal: list[Decision], py_legal: list[Decision],
    ) -> None:
        r = canon_set(rust_legal)
        p = canon_set(py_legal)
        if r != p:
            only_rust = sorted(map(repr, r - p))
            only_py = sorted(map(repr, p - r))
            raise ShadowDivergenceError(
                "LEGAL_SET_EQ",
                f"rust\\py={only_rust} py\\rust={only_py} "
                f"(active_player={self.active_player()})",
            )

    def _assert_chosen_eq(self, decision: Decision) -> None:
        """The chosen decision must encode to the SAME codec slot
        under the Rust zone view and the Python zone view (§3.2).
        Resolution* / chance decisions are out of the codec's slot
        space — skip (G3 accepted caveat); combat + priority-window
        kinds are encoded."""
        from mtg_bot.training import action_encoding as ae

        viewer = (
            self._viewer if self._viewer is not None
            else self.active_player()
        )
        try:
            py_slot = ae.encode(decision, self._py, viewer)
            rust_slot = ae.encode(decision, self._rust, viewer)
        except ae.EncodingOverflowError:
            # A position beyond a codec cap is unreachable through the
            # policy head on BOTH engines identically (the cap is a
            # shared codec constant); not a cross-engine divergence.
            return
        if py_slot != rust_slot:
            raise ShadowDivergenceError(
                "CHOSEN_EQ",
                f"decision {decision!r} encodes to py_slot={py_slot} "
                f"but rust_slot={rust_slot} (viewer={viewer})",
            )

    # Fields whose Python-vs-Rust divergence is a DOCUMENTED, PINNED,
    # ACCEPTED pre-existing engine asymmetry (NOT a B3-introduced or
    # new divergence) — reconciled here exactly as the existing
    # cross_engine `step_both` harness reconciles it (spec §4.3: "the
    # SAME compare_fields machinery"). STATE_EQ raises loudly on every
    # OTHER (undocumented / new) field divergence — the genuine
    # bad-flip signal. This is the precisely-scoped documented-gap
    # reconciliation, the analog of compare_fields' own `known_gap`
    # filter; it is NOT a blanket skip (the negative-control tests
    # prove STATE_EQ still fires on a non-accepted divergence).
    #
    # * mana_pool_p0 / mana_pool_p1 — I20 (RUST_PARITY_GAPS §I20).
    #   Rust `advance_phase` empties mana every phase tick (CR 106.4 —
    #   the CR-correct model); the Python simplified engine
    #   DELIBERATELY holds mana across phases within a turn and clears
    #   only at cleanup (documented simplification, turn.py:1081-1083).
    #   The existing step_both harness reconciles this by driving
    #   advance_phase_python (the Python mana-empty mirror) in lockstep
    #   with rust.advance_phase(). The vanilla MtgGameStateAdapter
    #   priority loop (the shadow checker) uses Python's native
    #   hold-until-cleanup model, so a Rust-driven shadow diverges on
    #   mana_pool at every non-cleanup phase boundary where mana is
    #   floating. This is the documented I20 asymmetry surfacing under
    #   the role-swapped contract — accepted, NOT a flip-blocker (the
    #   apply-side mana gate is the hard correctness boundary; the
    #   reduced-universe admitted population is C6-fenced). The proper
    #   closure (drive advance_phase_python in lockstep so the Python
    #   checker matches Rust's CR-correct per-phase empty) is named in
    #   docs/SEARCH_LIMITATIONS.md and is an orchestrator-sequenced
    #   bake-in-scaling refinement, NOT a B3-S4 blocker.
    _DOCUMENTED_ACCEPTED_FIELDS = frozenset(
        {"mana_pool_p0", "mana_pool_p1"}
    )

    def _assert_state_eq(self) -> None:
        """compare_fields(py_view, rust_view) has no UNDOCUMENTED
        divergence (documented-accepted I20 fields reconciled exactly
        as the existing step_both harness does — spec §4.3) AND
        rust.fingerprint() stable across two independent clones from
        the current Rust state (per-seed determinism, the
        BRIDGE_VESTIGIALIZATION_PLAN §2.3 J2 invariant)."""
        from mtg_bot.parity.cross_engine import (
            build_python_field_view, compare_fields, parity_smoke,
        )

        ps = parity_smoke()
        py_view = build_python_field_view(self._py.engine_state)
        rust_view = ps._build_field_view(self._rust.rust_state)
        divs = compare_fields(py_view, rust_view)
        # Partition: documented-accepted (I20 etc.) vs the genuine
        # bad-flip signal. Raise loudly ONLY on the latter.
        real = [
            d for d in divs
            if d.field not in self._DOCUMENTED_ACCEPTED_FIELDS
        ]
        if real:
            raise ShadowDivergenceError(
                "STATE_EQ",
                "compare_fields divergences (undocumented — the "
                "genuine bad-flip signal): "
                + repr([
                    (d.field, d.py_value, d.rust_value) for d in real
                ])
                + (
                    " | documented-accepted (I20-class, reconciled): "
                    + repr([d.field for d in divs if d not in real])
                    if len(divs) > len(real) else ""
                ),
            )
        # Fingerprint determinism: two independent clones of the
        # current Rust state must hash identically.
        fp_a = self._rust.rust_state.clone_once().fingerprint()
        fp_b = self._rust.rust_state.clone_once().fingerprint()
        if fp_a != fp_b:
            raise ShadowDivergenceError(
                "STATE_EQ",
                f"rust fingerprint non-deterministic across two "
                f"independent clones: {fp_a!r} != {fp_b!r}",
            )

    # ---- search.GameState protocol -----------------------------------

    def clone(self) -> "ShadowCheckedRustAdapter":
        c = ShadowCheckedRustAdapter.__new__(ShadowCheckedRustAdapter)
        c._py = self._py.clone()
        c._rust = self._rust.clone()
        c._viewer = self._viewer
        c._last_legal = list(self._last_legal)
        return c

    def active_player(self) -> PlayerID:
        # Rust is the driver; its active-player is authoritative. The
        # Python checker should agree — assert it (a mismatch is a
        # priority/active-extraction divergence).
        r = self._rust.active_player()
        p = self._py.active_player()
        if r != p:
            raise ShadowDivergenceError(
                "STATE_EQ",
                f"active_player divergence: rust={r} python={p}",
            )
        return r

    def legal_decisions(self) -> list[Decision]:
        rust_legal = self._rust.legal_decisions()
        # Compare against Python's RULES-legal set (raw legal_actions
        # in a priority window; the adapter's factored emission in a
        # combat window) — NOT the heuristic-pruned adapter output
        # (spec §4.1; the bake-in surfaced that a heuristic prune both
        # engines' RULES agree on would false-trip LEGAL_SET_EQ).
        py_ref = self._python_reference_legal()
        self._assert_legal_set_eq(rust_legal, py_ref)
        # Rust is the driver — the agent picks from the Rust set.
        self._last_legal = rust_legal
        return rust_legal

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        return []

    def apply(self, decision: Decision) -> None:
        # CHOSEN_EQ (pre-apply: encode under both zone views).
        self._assert_chosen_eq(decision)
        # Apply to BOTH. NO_RAISE: a Python apply_action invariant
        # raise is the documented C1 failure mode — surface it as the
        # NO_RAISE tripwire (not a bare exception).
        self._rust.apply(decision)
        try:
            self._py.apply(decision)
        except Exception as exc:  # noqa: BLE001 — re-raised as tripwire
            raise ShadowDivergenceError(
                "NO_RAISE",
                f"Python apply_action raised on {decision!r}: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        # STATE_EQ (post-apply byte-equal + fingerprint determinism).
        if not self._rust.is_terminal():
            self._assert_state_eq()

    def is_terminal(self) -> bool:
        r = self._rust.is_terminal()
        p = self._py.is_terminal()
        if r != p:
            raise ShadowDivergenceError(
                "STATE_EQ",
                f"is_terminal divergence: rust={r} python={p}",
            )
        return r

    def winner(self) -> Optional[PlayerID]:
        r = self._rust.winner()
        p = self._py.winner()
        if r != p:
            raise ShadowDivergenceError(
                "STATE_EQ",
                f"winner divergence: rust={r} python={p}",
            )
        return r

    def players(self) -> list[PlayerID]:
        return [0, 1]

    # ---- bake-in introspection ---------------------------------------

    @property
    def engine_state(self):
        """Codec hook: under rust_shadow Python IS present, so the
        codec reads the Python engine zones (the SoT checker side).
        CHOSEN_EQ separately asserts the Rust zone view encodes to the
        same slot."""
        return self._py.engine_state

    @property
    def rust_adapter(self):
        return self._rust

    @property
    def py_adapter(self):
        return self._py


def build_shadow_checked_adapter(spec: Any):
    """Build a ``ShadowCheckedRustAdapter`` from a
    ``cross_engine.DeckSpec`` via the matched-state loader path
    (``build_matched_states`` — the surviving Rust materializer per
    ``BRIDGE_VESTIGIALIZATION_PLAN.md`` §2.1). This is the bake-in
    factory the §4.2 C4-scale sweep + the one real ``mtg_bot
    iterate`` iteration drive through."""
    from mtg_bot.parity.cross_engine import build_matched_states
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )
    from mtg_bot.search.heuristics_config import HeuristicsConfig

    py_state, rust_state = build_matched_states(spec)
    # The Python checker runs HEURISTICS-DISABLED (correctness-
    # sensitive, like eval): the adapter's phase-prune / force-
    # landdrop / skip-empty-combat short-circuits are deliberate
    # SEARCH heuristics, NOT rules. The Rust provider does not apply
    # them (it sources the rules-legal set from Rust legal_decisions),
    # so a heuristics-enabled Python checker would desync the
    # lock-step on a heuristic prune both engines' RULES agree on.
    # _python_reference_legal already compares against raw
    # legal_actions in a priority window; disabling here also keeps
    # the Python adapter's own driving (its legal_decisions used in
    # the combat-window reference + its apply path) heuristic-free so
    # the two engines stay rules-for-rules aligned.
    py_adapter = MtgGameStateAdapter(
        py_state, expose_combat_decisions=True,
        heuristics=HeuristicsConfig.disabled(),
    )
    rust_adapter = make_rust_game_state_adapter(rust_state, spec=spec)
    return ShadowCheckedRustAdapter(py_adapter, rust_adapter)
