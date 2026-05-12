# Pending CE filings — 2026-05-11

Staging doc for follow-up application to `docs/RUST_PARITY_GAPS.md`.
Written on 2026-05-11 while two parallel agents were still in flight
on `RUST_PARITY_GAPS.md` (CE5 cast-vs-resolve closure + a separate
CE-is_over closure). To avoid merge conflicts, this doc enumerates
the formal CE entries we propose ADDING and the renumbering audit
we propose APPLYING, so a future operator (or the next session) can
land them cleanly in one pass once the parallel work has merged.

**Executive summary**: **3 informal findings need formal CE
numbering** (CE-pure-derivation-is_over, CE-draw_card-inline-vs-
pymethod [already CLOSED today], CE-shuffle-prng-mismatch). **0
renumberings are needed at the time this doc was written** —
the SBA-closure / cast-vs-resolve CE5 conflict that the retro doc
flagged was already resolved on origin/main by the
`feature/ce6-renumber` slice (commit `57cdbee8` / merge
`ef61210e`) BEFORE this staging doc was written. The renumbering
audit section below is preserved as a postmortem of the conflict
and a checklist in case any straggling references to the old
CE5-SBA numbering survive in non-`RUST_PARITY_GAPS.md` files.

---

## Section 0: Verified current state of CE numbering on origin/main

`git log --oneline -20 origin/main` and a fresh read of
`docs/RUST_PARITY_GAPS.md` at HEAD `ef61210e` confirm the CE
section currently lists exactly six CE entries:

| Doc line | Header                                                                                                                            | Status |
| ---      | ---                                                                                                                               | ---    |
| L865     | `### ~~CE1.~~ CLOSED in round 28: summoning_sick default aligned to Python's universal True`                                       | CLOSED |
| L889     | `### ~~CE2.~~ CLOSED: apply_action(PassPriority) is now a no-op matching Python`                                                   | CLOSED |
| L913     | `### ~~CE3.~~ CLOSED: Library orientation aligned to Python's index 0 = top convention`                                            | CLOSED |
| L971     | `### ~~CE4.~~ CLOSED: battlefield_snapshot emits in etb_timestamp order (matching Python's centralized append order)`              | CLOSED |
| L1061    | `### ~~CE6.~~ CLOSED: collect_sba_victims walks the battlefield in ETB-timestamp order (via shared bf_iter_etb_sorted helper)`     | CLOSED |
| L1207    | `### CE5. cast_spell resolves immediately on Rust (no stack) — Python pushes a StackItem and defers resolve`                       | OPEN   |

**Implication.** The next available formal CE number is **CE7**.
The retro doc's preview (Section 4 of
`docs/SESSION_RETRO_2026_05_11.md`) named the three pending
findings as CE10 / CE11 / CE12, but that preview implicitly
reserved CE7 / CE8 / CE9 for the playbook's predicted
divergences (combat damage / cross-player find-first /
trigger emitter) that have NOT yet been surfaced by any probe
and therefore should NOT be pre-allocated. The
`docs/RUST_PARITY_GAPS.md` numbering policy (lines 1317-1334
"Maintenance" block) is monotonic-on-surface: a CE number is
assigned WHEN the divergence is surfaced + pinned by a test,
not predictively. Pre-allocating CE numbers for predicted-but-
not-surfaced gaps risks doc-numbering churn the next time the
playbook reorders (which already happened once today —
the cast_bears probe surfaced the cast-vs-resolve gap before
the playbook's SBA-collection prediction; the retro doc flags
this same churn risk in §4's playbook-caveat paragraph).

**Recommendation.** File the three informal findings at the
next monotonic numbers: **CE7 / CE8 / CE9** (mappings in
Section 1 below). The two in-flight parallel agents that
mention CE10/CE11/CE12 in their task briefs may have inherited
the retro doc's stale numbering; that should be reconciled at
merge time per the checklist in Section 3.

---

## Section 1: Informal findings that need formal numbering

Three informal CE-style findings surfaced today in
`tests/test_parity_smoke_edge_cases.py` (commit `c4dd5d5a`) and
its follow-up (`1673e582`). Each needs a formal `CE<n>` entry in
`docs/RUST_PARITY_GAPS.md` mirroring the shape of CE2 / CE3 / CE4
(see "Existing CE entry format" subsection at the bottom of this
section for the template).

### Finding 1.1 — CE-pure-derivation-is_over

- **Informal name**: `CE-pure-derivation-is_over`
- **Status**: still-open (today); MAY be closed by the CE-is_over
  in-flight agent. If that agent files it as CE7, drop this
  proposal (Section 1.1) at merge time and renumber 1.2 / 1.3
  down by one.
- **Surfacing tests**:
  * `tests/test_parity_smoke_edge_cases.py:67-120`
    `test_cross_engine_empty_library_side_channel_draw_walks_clean`
    (strict-xfail) — drives `play_a_land_selector` for 2 decisions
    on a deck with empty libraries. Step-0 side-channel `draw_card`
    fires on both engines; Rust sets `attempted_draw_on_empty=True`
    and its pure-derivation `is_over` flips to True with
    `winner_id=1`, while Python's `has_lost=True` on p0 leaves
    `is_over=False` / `winner_id=None` (no SBA fired by harness).
  * `tests/test_parity_smoke_edge_cases.py:299-377`
    `test_cross_engine_single_card_libraries_multi_turn_walks_clean`
    (strict-xfail) — same divergence surfaced via the
    `advance_phase` auto-draw path after
    `feature/draw-card-inline-flag` (`1673e582`) closed the
    inline-vs-pymethod asymmetry sub-finding. Step 39 surfaces
    `[('is_over', False, True), ('winner_id', None, 0)]`.
- **Companion symptom-pin tests** (passing, will need to flip /
  remove when CE-is_over closes per closure-pair contract):
  * `tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_surfaces_is_over_divergence`
    (around L123).
- **Proposed CE number**: **CE7** (or whatever the next-available
  monotonic number is at the time of application — verify
  against `docs/RUST_PARITY_GAPS.md` HEAD before filing).
- **Proposed entry text** (paste as a new `### CE7.` subsection
  under the existing `### CE5.` open entry at L1207, mirroring
  the format of the CE5 entry):

> ### CE7. `is_over` derivation is eager on Rust, SBA-gated on Python
>
> - **Pinned by**:
>   `tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_walks_clean`
>   (strict-xfail; side-channel `draw_card` variant) AND
>   `tests/test_parity_smoke_edge_cases.py::test_cross_engine_single_card_libraries_multi_turn_walks_clean`
>   (strict-xfail; `advance_phase` auto-draw variant, surfaced
>   by `feature/draw-card-inline-flag` `1673e582`). Companion
>   passing pin
>   `test_cross_engine_empty_library_side_channel_draw_surfaces_is_over_divergence`
>   fixes the exact symptom values at step 0.
> - **Surfaced by**: Phase-5 edge-case hardening probes
>   (`c4dd5d5a`, refined by `1673e582`). The empty-library
>   variant drives a step-0 side-channel draw; the multi-turn
>   variant drives 100 decisions of `multi_turn_selector` and
>   surfaces the divergence at step 39 when p0 decks out via
>   the auto-draw step on turn 3.
> - **Rust today**: `is_over` is a pure derivation over the
>   loss-cause fields:
>   `has_lost || attempted_draw_on_empty || life<=0`. The
>   predicate is checked in `state.rs::GameState::is_over` and
>   in `state.rs::GameState::losers` without requiring an SBA
>   pass. Per I19, `attempted_draw_on_empty` is flipped by all
>   three draw entrypoints (`state_ops_zones.rs::draw_card`
>   pymethod, `state_ops_steps.rs::draw_card_inline` auto-draw
>   path, and `state_ops_resolve.rs::Effect::DrawCards`
>   resolution arm), so any empty-library draw eagerly flips
>   `is_over` to True without SBA bookkeeping.
> - **CR / Python expected**: Python's `state.is_game_over` reads
>   `state.winner_id`, which is only WRITTEN by an SBA pass
>   (`turn.py:_state_based_actions_pass` finalizes losers and
>   writes `state.winner_id = the_other_player`). CR 704 has SBAs
>   as the bridging mechanism between cause-signals and the
>   game-over predicate; the harness's walk does NOT fire SBAs
>   between steps so Python's `is_over` stays `False` and
>   `winner_id` stays `None` even after both cause-signals are
>   set.
> - **Impact**: medium-to-high. Blocks two cross-engine smoke
>   edge-case tests today; will block any future smoke spec
>   that drives a player into empty-library territory. Does
>   NOT cascade into mid-game divergence because the predicate
>   only matters once at game-end; both engines agree on the
>   cause-signals (`has_lost` / `attempted_draw_on_empty`),
>   they just disagree on when those signals become observable
>   via `is_over` / `winner_id`.
> - **Closeable**: yes — three-option closure:
>   1. **Python grows pure-derivation `is_over`.** Replace
>      `state.is_game_over` with the same predicate Rust uses
>      (`has_lost || attempted_draw_on_empty || life<=0`),
>      bypassing the SBA writeback step. Cleanest semantic
>      match, but requires audit of every consumer that reads
>      `state.winner_id` because the bridge field stays SBA-
>      written today; either (a) those consumers also flip to
>      pure derivation, or (b) `winner_id` gets a pure-deriv
>      computed-property mirror.
>   2. **Harness fires SBAs between steps.** Mirror the
>      `advance_phase_python` pattern (`cross_engine.py`): after
>      every Python `apply_action`, call
>      `apply_sbas_until_quiescent(py_state)` so Python's SBA
>      pass writes `winner_id` and `is_over` flips. Harness-only;
>      production Python unchanged. Lowest-cost.
>   3. **Mark `is_over` / `winner_id` as known-gap fields.**
>      Extend `cross_engine.py`'s field view normalizer to
>      skip these two fields when both engines agree on the
>      cause-signal fields (`has_lost`, `attempted_draw_on_empty`,
>      `life`). Preserves the symptom-pin shape for future
>      re-derivation. Smallest surface; defers the architectural
>      choice between (1) and (2).
>
>   Per the retro doc's Priority 2 recommendation, Option 2 is
>   the smallest closure slice that keeps the probe cadence
>   moving.

### Finding 1.2 — CE-draw_card-inline-vs-pymethod (CLOSED today)

- **Informal name**: `CE-draw_card-inline-vs-pymethod`
- **Status**: closed-but-not-formally-numbered. Closed by
  `feature/draw-card-inline-flag` (feature commit `1673e582`,
  merge `63f03067`) today. Should be filed as a CLOSED entry in
  `RUST_PARITY_GAPS.md` for the historical record (mirroring the
  CE2 / CE3 / CE4 / CE6 closed-entry shape).
- **Surfacing test**: surfaced as a sub-finding in the
  `c4dd5d5a` edge-case probe round-up docstring (then-untested
  asymmetry called out alongside CE-pure-derivation-is_over).
- **Closure test**:
  `tests_rust/test_steps.py::test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw`
  — pins the closure: synthetic state with `num_library=0`,
  walk UNTAP → UPKEEP → DRAW, assert `state.losers() == [0]`
  eagerly + `apply_sbas` locks the loss into sticky `has_lost`.
- **Proposed CE number**: **CE8** (or CE7 if CE-is_over closes
  in flight and takes a different number; verify at merge
  time).
- **Proposed entry text** (paste as a new `### ~~CE8.~~ CLOSED:`
  subsection alongside the other closed entries, ideally
  immediately before CE6 at L1061 so the closed-entry block is
  contiguous):

> ### ~~CE8.~~ CLOSED: `draw_card_inline` mirror flags `attempted_draw_on_empty` matching the pymethod and `Effect::DrawCards` arms
>
> Closed by `feature/draw-card-inline-flag` (feature `1673e582`,
> merge `63f03067`). Pre-closure, Rust had two `draw_card`
> paths with diverging empty-library behavior:
>
> - `state_ops_zones.rs::draw_card` (pymethod) flagged
>   `Player.attempted_draw_on_empty = true` on empty pop.
> - `state_ops_steps.rs::draw_card_inline` (the
>   `advance_phase` auto-draw mirror used on entry to
>   PHASE_DRAW per CR 504.1) was a silent no-op on empty
>   libraries.
> - `state_ops_resolve.rs::Effect::DrawCards` (the resolution
>   arm) flagged correctly.
>
> Result: a player who decked out via the DRAW step (the
> common case in real games) was un-flagged on Rust side,
> even though deck-out via cast-spell-resolves-DrawCards or
> side-channel pymethod call was correctly flagged.
>
> **Closure shape.** Option B per the closure brief —
> mirror the flag-set into the inline path directly
> rather than delegating to the pymethod (Option A would
> have required `pub(crate)` visibility on the pymethod,
> outside the slice scope). The inline mirror also picks up
> the pymethod's defensive `attached_to` /
> `exiled_with_source` reset on the drawn object (CR 400.7
> round-28 attach foundation), so the two paths now match
> bit-for-bit.
>
> Pinned by
> `tests_rust/test_steps.py::test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw`
> — synthetic state with `num_battlefield=0, num_hand=0,
> num_library=0`, seeds `turn_number=5` so the CR 103.7c
> first-turn-skip gate is open, walks UNTAP → UPKEEP →
> DRAW, asserts `state.losers() == [0]` eagerly +
> `state.is_game_over() is True` + `state.winner_id == 1`
> + `apply_sbas` locks the loss into the sticky `has_lost`.
> `docs/RUST_PARITY_GAPS.md` I19 invariant bullet was
> extended (in the same closure slice) to list
> `advance_phase`'s auto-draw step as the third entrypoint
> that flips the cause-signal.
>
> The closure SURFACED the SAME CE-pure-derivation-is_over
> divergence pinned by CE7 above:
> `test_cross_engine_single_card_libraries_multi_turn_walks_clean`
> flipped from passing to strict-xfailed at step 39 once
> the (newly fixed) auto-draw path made Rust's
> `attempted_draw_on_empty` flip observable on the multi-
> turn path; Python's SBA-gated `is_over` stays False.
> See CE7's closure plan.

### Finding 1.3 — CE-shuffle-prng-mismatch

- **Informal name**: `CE-shuffle-prng-mismatch`
- **Status**: still-open. Also overlaps with G19 (search-library-
  for-basic-land-tapped does not shuffle); the two are
  independent shuffle-related divergences but share the same
  RNG-externalization closure path.
- **Surfacing test**:
  `tests/test_parity_smoke_edge_cases.py:405-428`
  `test_cross_engine_shuffle_seed_walks_clean` (strict-xfail) —
  builds matched states with `shuffle_seed=42` and asserts
  initial libraries match; today they don't because Python
  uses Mersenne Twister and Rust uses xorshift64.
- **Companion symptom-pin test**:
  `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds`
  (L431) — confirms the shape across seeds 1, 7, 42, 100.
- **Proposed CE number**: **CE9** (or CE8 if Finding 1.1 closes
  in flight; verify at merge time).
- **Proposed entry text** (paste as a new `### CE9.` subsection
  under the existing CE5 / CE7 open-entry block — open entries
  cluster after the closed-entry block per the L1207 / L1188
  precedent):

> ### CE9. `shuffle_deck` PRNG diverges — Python uses Mersenne Twister, Rust uses xorshift64
>
> - **Pinned by**:
>   `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_walks_clean`
>   (strict-xfail) for the clean-walk pin at step 0.
>   Companion passing pin
>   `test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds`
>   confirms the divergence shape across seeds 1, 7, 42, 100.
> - **Surfaced by**: Phase-5 edge-case probe round (`c4dd5d5a`).
>   `slightly_bigger_deckspec` with `shuffle_seed=42` builds
>   matched states; the initial-state field view diverges on
>   `library_p0` and `library_p1` at step 0 (before any
>   decision is applied). Reproducible per-seed: the same seed
>   produces the same Python permutation and the same Rust
>   permutation, just different from each other.
> - **Rust today**: Rust's shuffle (in the engine; called
>   internally during `make_state` when `shuffle_seed` is set
>   plus in `Effect::ShuffleLibrary` and friends) uses a
>   xorshift64 PRNG, chosen for its small footprint and
>   reproducibility within Rust's own gate. The same seed
>   that produces permutation P_py on Python's `random.Random`
>   produces permutation P_rust on Rust's xorshift64; P_py
>   ≠ P_rust except by birthday-style accident.
> - **CR / Python expected**: CR 103.4 / 701.20 mandate that
>   the library is randomized; the CR is silent on WHICH PRNG
>   the engine uses. The parity reference is "Python's
>   Mersenne Twister output for any given seed" because the
>   cross-engine smoke contract pins Python as the parity
>   source-of-truth for observable state (per `RUST_PARITY_PLAN`
>   Decision 1).
> - **Impact**: medium. Does NOT block real-game play (each
>   engine's internal randomization is sound). DOES block
>   cross-engine smoke at any spec that sets a non-`None`
>   `shuffle_seed`. The harness sidesteps this today by
>   defaulting `shuffle_seed=None` (no initial shuffle); every
>   other Phase-5 cross-engine test relies on that default.
>   Also blocks closure of G19 (the
>   SearchLibraryForBasicLandTapped no-shuffle gap) because
>   both gaps share the RNG-externalization closure path.
> - **Closeable**: yes — three-option closure (mirrors the
>   `RUST_PARITY_PLAN.md` Decision 1 options):
>   1. **Rust adopts Mersenne Twister.** Port MT19937 into Rust
>      (existing crate `rand_mt` or a vendored impl) and route
>      every `shuffle_deck` site through it. Largest surface;
>      ties Rust to a specific Python implementation detail.
>   2. **Both engines accept an external RNG stream.** Add a
>      `seed_bytes` (or `pre_shuffled_indices`) parameter to
>      `make_state` on both sides; the harness pre-computes
>      the shuffle on one side (e.g. Python) and feeds the
>      result to the other (via the parameter). Decouples
>      engines from PRNG choice; matches the
>      `RUST_PARITY_PLAN` Decision 1 option (b). Medium
>      surface. Also closes G19 because the
>      SearchLibraryForBasicLandTapped Rust arm can consume
>      the same external stream to mirror Python's shuffle
>      behavior.
>   3. **Harness disables shuffle entirely.** Force
>      `shuffle_seed=None` on every cross-engine spec; the
>      strict-xfail flips by removing the test. Lowest cost
>      but does not close G19 and leaves real shuffles
>      untested cross-engine.
>
>   Recommendation per the retro doc's "Honorable mentions"
>   (RNG externalization gates CE-shuffle-prng-mismatch + G19
>   + many search-library Effects): Option 2 is the
>   architecturally correct shape but is a substrate slice;
>   schedule when CE-cast-vs-resolve closure (CE5) lands and
>   the cadence has room for substrate work.

### Existing CE entry format (template)

The three proposed entries above follow the shape established
by the existing closed-and-open CE entries in
`docs/RUST_PARITY_GAPS.md` (verified against CE2 at L889, CE3 at
L913, CE4 at L971, CE5-OPEN at L1207, and CE6 at L1061). The
template is:

```markdown
### CE<n>. <one-line short name>

- **Pinned by**: <test_file>::<test_name> (strict-xfail) + companion symptom-pin <test_name>.
- **Surfaced by**: <probe / commit / brief reference>.
- **Rust today**: <current Rust behavior, file:line of the diverging primitive>.
- **CR / Python expected**: <CR ref + Python reference path>.
- **Impact**: <low / med / high> + one-line cascade explanation.
- **Closeable**: yes/no + closure plan summary (multiple options OK).
```

When the entry is closed by a later slice, the heading flips to
`### ~~CE<n>.~~ CLOSED: <closure summary>` and the body is
rewritten in the closed-entry style established by CE2/CE3/CE4/CE6
— prose paragraphs describing the closure shape rather than the
bulleted divergence list above.

---

## Section 2: CE numbering audit

### 2.1: Predicted vs actual CE assignments

Per the `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` (merged
`2a7221b1`), the playbook predicted CE5-CE9 as:

| Predicted CE | Predicted subject                                 |
| ---          | ---                                               |
| CE5          | SBA victim collection (HIGH)                      |
| CE6          | combat damage assignment (HIGH)                   |
| CE7          | cross-player find-first arms (MED)                |
| CE8          | trigger emitter substrate                         |
| CE9          | `play_land` etb_timestamp asymmetry (cosmetic)    |

Actual on origin/main as of HEAD `ef61210e`:

| Filed CE   | Actual subject                                        | Status                                         |
| ---        | ---                                                   | ---                                            |
| CE5        | cast-vs-resolve (`cast_creature` fuses)               | OPEN (in-flight closure)                       |
| CE6        | SBA victim collection (playbook's predicted CE5)      | CLOSED today (renumbered from CE5 via `57cdbee8`) |

### 2.2: Was there a real numbering conflict, and was it resolved?

**Yes — and yes.** Briefly:

- `87ac8bd8` (`feature/phase5-cast-bears`, merged `64e08bb0`)
  filed the cast-vs-resolve divergence as **CE5** at 22:37:56.
- `cdb01fcd` (`feature/ce5-sba-order`, merged `7961d792`) ALSO
  filed the SBA-collection closure as **CE5** at 22:43:25 (six
  minutes later), per the playbook's pre-staged numbering.
- Git auto-merge succeeded silently because the two entries
  landed in different doc sections (L1061 vs L1207). The
  numbering was wrong on main.
- `57cdbee8` (`feature/ce6-renumber`, merged `ef61210e`)
  renumbered the SBA closure entry to **CE6** and added a
  coordination preamble pointing back at the playbook.

The retro doc (`794b1a8b`) was written BEFORE the
`feature/ce6-renumber` slice landed, which is why its Section 4
shows the SBA closure as CE5 with a footnote about the
upcoming renumber. The retro doc's CE10/CE11/CE12 preview was
correct as of its drafting (when CE5/CE6/CE7/CE8/CE9 were
implicitly reserved for the cast-vs-resolve open + the playbook's
SBA/damage/find-first/triggers predictions); after the
`feature/ce6-renumber` slice landed, the actually-next-available
number became CE7.

### 2.3: Are there any straggling references to the old CE5-SBA numbering?

**Check at merge time.** The `feature/ce6-renumber` slice was
scoped to `docs/RUST_PARITY_GAPS.md` only and explicitly LEFT
the `tests_rust/test_sba.py` "CE5 closure" section comment as-is
(per its commit message — "the comment documents what the test
code targets, not the doc numbering; re-renaming would churn the
test file for no semantic gain"). The renumber slice also did not
touch:

- `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` (the playbook itself —
  named for the predicted CE5/CE6/CE7, now misnamed since the
  predicted CE5 was filed as CE6 and the predicted CE6/CE7
  remain unsurfaced and will get whatever numbers come next).
- Worklog entries pre-dating the renumber.

Action items for the merge-time renumbering pass:

1. Search `tests_rust/test_sba.py` for the literal `CE5
   closure` comment. Confirm the slice author's decision to
   leave it as-is — it's a test-file structural comment, not
   doc-numbering-bearing.
2. Search the entire repo for any `pre-CE5` / `post-CE5` /
   `CE5 closure` / `CE5 cast` / `CE5 SBA` references and
   classify each as (a) refers to the OPEN cast-vs-resolve
   CE5 (correct, leave), (b) refers to the now-CE6 SBA
   closure (rename to CE6), or (c) refers to the
   playbook's predicted CE5 (rename to "playbook-CE5" /
   add a coordination note).
3. The playbook file itself (`docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`)
   keeps its filename — renaming would invalidate every
   cross-reference. The body text should clarify that its
   predicted CE5 closed as CE6 / predicted CE6 → CE7 /
   predicted CE7 → CE8 (paragraph header at top, no
   per-line rewrites needed).

---

## Section 3: Proposed renumbering action (checklist)

At the time of writing, **the SBA / cast-vs-resolve CE5 conflict
is already resolved on origin/main**. The checklist below is a
defense-in-depth pass: verify the resolution stuck and clean up
any straggling references the renumber slice intentionally
deferred.

```text
[ ] 1. Re-read docs/RUST_PARITY_GAPS.md HEAD and confirm the CE
       headers match Section 0 of this doc (CE1/CE2/CE3/CE4 closed,
       CE5 open with cast-vs-resolve, CE6 closed with SBA-collection).
       If anything has moved since `ef61210e`, re-derive the
       next-available CE number for Section 1 entries.
[ ] 2. Grep the repo for the pattern `\bCE5\b` and classify each
       hit:
       - In tests_rust/test_sba.py: per renumber slice decision,
         the "CE5 closure" section comment is intentionally kept
         (test-file structural, not doc-numbering). Leave.
       - In hub/data/mtg_bot/worklog.json: pre-renumber worklog
         entries reference CE5/CE6/CE7 in the playbook predictions
         sense. Append a clarifying bullet to the next worklog
         entry if needed; do NOT rewrite history.
       - Anywhere else: classify (open cast-vs-resolve / closed
         SBA / playbook-prediction) and apply the rename mapping
         from Section 2.3.
[ ] 3. Grep the repo for `\bCE6\b` and confirm hits refer to the
       (now-filed) SBA-collection closure or the (still-predicted)
       combat-damage-assignment finding. Both are valid uses; only
       flag hits that refer to the playbook's OLD predicted CE6
       (combat damage) and clarify which numbering basis they're
       using.
[ ] 4. Cross-reference docs/SESSION_RETRO_2026_05_11.md Section 4's
       CE10/CE11/CE12 preview. If the retro doc gets a follow-up
       edit-pass after the in-flight CE-is_over agent merges,
       update Section 4 to show the actually-filed numbers
       (CE7/CE8/CE9 per Section 1 of this doc, or whatever the
       verified-monotonic numbers are at merge time). If the
       retro doc is treated as historical (snapshot of the
       2026-05-11 state), leave it alone; the discrepancy
       documents the churn.
[ ] 5. Update docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md with a
       coordination paragraph at the top (one-time, low churn)
       stating: "Subsequent to drafting, the playbook's predicted
       CE5 was filed as CE6 (the cast-vs-resolve probe surfaced
       a different divergence first and claimed CE5). Predicted
       CE6 (combat damage) and CE7 (find-first targets) will get
       whatever numbers come next when they surface; do not
       pre-allocate." Keep the filename; downstream cross-refs
       depend on it.
```

---

## Section 4: Action plan (in order, after all in-flight agents land)

```text
[ ] STEP 1. Confirm the CE5 cast-vs-resolve closure is on main.
            Look for a merge commit titled `Merge feature/ce5-cast-resolve-...`
            or similar; the CE5 entry header in
            docs/RUST_PARITY_GAPS.md should flip from
            `### CE5. cast_spell resolves immediately...`
            to `### ~~CE5.~~ CLOSED: ...`. If yes, proceed.
            If the in-flight closure used a different CE number
            (unlikely; the slice brief reserved CE5), reconcile
            per Section 2.

[ ] STEP 2. Confirm the CE-pure-derivation-is_over closure on main.
            Look for a merge commit titled `Merge feature/ce-is-over-...`
            (or similar). Two outcomes possible:
              (a) The slice filed it as CE7 — most likely, since
                  the slice brief reserves the next-available
                  number. In that case: Section 1's Finding 1.1
                  is REDUNDANT (drop it from the application
                  pass) and Findings 1.2 / 1.3 file as CE8 / CE9.
              (b) The slice filed it under a different number
                  (CE10 etc. per stale retro-doc numbering). In
                  that case: leave the filed entry, AND map
                  Section 1's Findings 1.2 / 1.3 to whatever
                  next-available numbers come after.

[ ] STEP 3. Verify there is no second renumbering conflict.
            Re-grep docs/RUST_PARITY_GAPS.md headers for `### CE`
            and confirm monotonicity. If a duplicate CE number
            survived a merge, apply the CE5→CE6 renumber pattern
            (`57cdbee8`) again.

[ ] STEP 4. Apply Section 1 entries to docs/RUST_PARITY_GAPS.md.
            - Finding 1.1 (if still needed): paste as `### CE<n>.`
              under the open-entry block (currently L1207 area).
            - Finding 1.2 (CLOSED): paste as `### ~~CE<n>.~~ CLOSED:`
              in the closed-entry block (currently L865-L1187 area),
              keeping closed entries chronologically contiguous.
            - Finding 1.3 (open): paste as `### CE<n>.` under the
              open-entry block, after Finding 1.1 if both land.

[ ] STEP 5. Update docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md per
            Section 3 checklist item 5 (one-time coordination
            paragraph at top).

[ ] STEP 6. Re-grep the repo for the now-stale "CE10 / CE11 /
            CE12" labels (likely only in
            docs/SESSION_RETRO_2026_05_11.md Section 4 and in
            this staging doc's own task brief). Per Section 3
            checklist item 4, either reconcile the retro doc or
            leave it as a historical snapshot.

[ ] STEP 7. Delete docs/PENDING_CE_FILINGS_2026_05_11.md (this
            staging doc) once its proposals are applied. The doc
            is intentionally scoped to a single follow-up pass;
            leaving it in the repo long-term creates two
            sources-of-truth for CE numbering, which is exactly
            the churn this slice is meant to prevent.
```

---

## Section 5: Test-suite cross-references (file:line work-items)

Tests that will need flipping / removing when the proposed CE
entries close (per the closure-pair contract established by
CE3 / CE4):

| Test path                                                                                                                  | Today    | Closure action                                                                              |
| ---                                                                                                                        | ---      | ---                                                                                         |
| `tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_walks_clean` (L83)                | xfail    | flip to xpass when CE7 closes; remove marker                                                |
| `tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_surfaces_is_over_divergence` (L123) | passing  | remove / invert when CE7 closes per closure-pair contract                                   |
| `tests/test_parity_smoke_edge_cases.py::test_cross_engine_single_card_libraries_multi_turn_walks_clean` (L319)              | xfail    | flip to xpass when CE7 closes; remove marker                                                |
| `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_walks_clean` (L405)                                  | xfail    | flip to xpass when CE9 closes; remove marker                                                |
| `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds` (L431) | passing  | remove / invert when CE9 closes per closure-pair contract                                   |
| `tests_rust/test_steps.py::test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw`                              | passing  | regression pin for the already-closed CE8; keep                                              |

---

## Section 6: Audit summary

- **Informal findings with proposed formal entries**: 3
  (CE-pure-derivation-is_over, CE-draw_card-inline-vs-pymethod
  [closed], CE-shuffle-prng-mismatch).
- **Renumberings required at the time of writing**: 0 (the
  CE5 SBA / cast-vs-resolve conflict was resolved on main by
  `feature/ce6-renumber` BEFORE this doc was written; see
  Section 2.2).
- **Verified next-available CE number**: CE7 (could become CE8
  by merge time if the in-flight CE-is_over agent files first).
- **Doc-numbering-policy recommendation**: file CEs at the
  next monotonic available number when a divergence is
  SURFACED + PINNED; do not pre-allocate numbers for predicted-
  but-unsurfaced gaps (this prevented avoidable renumbering
  today and will again).
