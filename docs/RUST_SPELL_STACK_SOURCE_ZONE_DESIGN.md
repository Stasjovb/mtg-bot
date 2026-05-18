# G7 S5 — Rust spell-stack source-zone re-homing: verify-first sub-design (the CE5-removal linchpin)

> **STATUS UPDATE — S5a LANDED (engine, Option β) on branch
> `feature/g7-s5a-spellstack-zone`.** Implemented exactly as the
> §6 recommendation: Option β `GameState.stack_objects: Vec<GameObject>`
> store (`ZONE_STACK=4` now live), `StackItem` kept id-only, the 3
> source-resolution walks (`find_source_printing_id` / `take_source` /
> the `dispatch_event` CAST observer walk) extended with a 5th/6th
> stack-store zone, cast moves the spell hand→store / resolve takes it
> back. **One verify-first ADDITION beyond the surface map:** the
> §5.2-risk-3 silent-CAST-trigger regression *did* materialize — the
> `cards.rs` predicate subject/controller helpers (`object_has_card_
> type` / `subject_has_subtype` / `find_object_controller`, used by
> `SubjectIsCreature`/`SubjectIsLand`/`SubjectIsArtifact`/
> `SubjectHasSubtype`/`ControlledByYou`) walked only the 4 per-player
> zones and silently stopped resolving an on-stack cast-spell subject,
> so CAST-event triggers stopped firing. Fixed IN S5a (NOT deferred,
> per §5.2-risk-3 + `feedback_silent_noop_pipelines`) by extending
> those 3 `cards.rs` helpers with the same 5th stack-store zone —
> new-code-is-right: Python's CAST dispatch passes the live `card`
> reference (`actions.py:1795`, off-hand on the stack) as the subject,
> so the Rust subject lookup must reach the stack store. **§5.3
> baseline-rebase executed & audited:** parent `c2c9c624` →
> `eb0fd0ca`+fix delta is EXACTLY +0 net after re-pin — 8 `tests_rust`
> S1/S4 pins closure-flipped `find_object_zone==ZONE_HAND`→`ZONE_STACK`
> (byte-Python `actions.py:1403`/`:1751`), the cycle-25 honest-stop
> bake-in pin flipped surfaced→closure (`hand_p0` CLOSED; the
> predicted-next C1-class combat-blocker `LEGAL_SET_EQ` surfaced at the
> new boundary arch2/s1 step 312 / arch5/s0 step 344, `('blocker',
> 9/12, None)` Rust-extra). **4-file core gate 1534 UNMOVED** (the
> doc's "1532" was stale main-drift +2 pre-resync;
> `decision_source="python"` dormant w.r.t. Rust cast internals,
> verified — NOT 1532). 30 pre-existing `tests_rust` reds (factored-
> combat / observer drift, NOT spell-stack) untouched. S5b/S5c +
> the unmasked blocker-LEGAL_SET axis are follow-ups (ledger). The
> remaining text below is the original verify-first design (kept as
> the as-built record; "Status: DESIGN/SCOPING" superseded by this).

> **STATUS UPDATE — S5b LANDED (pure-Python VERIFY, no engine /
> `rust/src/` / `.pyd` change) on branch
> `feature/g7-s5b-codec-determinizer-verify`.** The §6 "the
> codec-slot / determinizer / legal-emit / fingerprint divergences
> are **all fixed for free by the single hand-membership
> correction** … **v1/v2-action-encoding-agnostic** … no v-chain
> break, no retraining" claim is **PROVEN — all S5b byte-equality
> pins genuinely GREEN; S5a's "fixed for free" claim HOLDS, no
> hole.** Added `tests/test_g7_s5b_codec_determinizer_verify.py`
> (9 pins). The pins drive a Grizzly Bears cast onto the stack on
> BOTH engines and compare at the same per-apply moment the
> role-swapped `rust_shadow` bake-in uses (apply-to-both then
> compare, **NO CE5-style post-cast drain** — the cast→on-stack→
> resolve window S5a re-homed):
> 1. **codec hand-slot byte-equality (§1.6), v1 AND v2** — the Rust
>    `hand_snapshot`-sourced codec hand slots byte-match Python's
>    `p.hand` exclusion of the on-stack spell; the on-stack spell is
>    in NEITHER engine's codec hand projection; every surviving
>    in-hand card encodes to the IDENTICAL policy slot from both
>    data sources under `positional_v1` AND `canonical_v2`.
> 2. **determinizer pool + end-to-end byte-equality (§1.7)** —
>    `determinize` (Python source) and `rust_determinize` (Rust
>    source) over the mid-stack state produce byte-identical hidden
>    pools AND byte-identical determinized per-owner hand+library
>    sequences under the same RNG seed; the on-stack spell is in
>    NEITHER pool. Exercised with ≥2 hidden library cards so the
>    `rng.shuffle` is a real permutation (NOT a degenerate ≤1-card
>    no-op); CoW source-pristine verified.
> 3. **fingerprint hand-slot byte-equality (§1.10)** — the
>    per-player `hand_p0`/`hand_p1` fingerprint slot is byte-equal
>    Python↔Rust mid-stack; the **stack slot is byte-equal AND
>    byte-unchanged** Python↔Rust (Python has no separate
>    stack-object zone signature — the spell rides the stack slot
>    via `source.id`, matching Rust's `source_obj_id`, per the S5a
>    `state.rs` design comment); Rust native `fingerprint()` ==
>    Rust-via-snapshot recipe (intra-engine determinism unaffected).
> 4. **NOT a v-chain break** — the same surviving in-hand card maps
>    correctly under BOTH v1 and v2 from BOTH data sources; the
>    correction is hand-membership, NOT intra-hand ordering — no
>    retraining implied.
> Negative control verified (a simulated S5a hole — on-stack spell
> injected into a hand pool — makes the determinizer pin fail loud,
> so the pins genuinely discriminate; not trivially-passing).
> **4-file core gate 1534 UNMOVED** (verified — S5b adds one
> pure-Python test file, touches zero `src/`/`rust/src/`/
> `parity_smoke.py`; `decision_source="python"` dormant w.r.t. Rust
> cast internals exactly as designed). Broader codec/determinizer/
> fingerprint/snapshot suites green (242 passed + 1 pre-existing
> xpass). `scripts/check_audit_coverage_staleness.py` exits 1 from a
> **pre-existing** S5a `rust/src/cards.rs`-touch residue-stamp drift
> (orchestrator-owned STALENESS-SENTINEL — verified present at base
> `302a5fc5` independent of the S5b file; S5b changes zero Rust so
> the structural arm is unaffected by S5b — the `.pyd`-rebuild +
> cron-resync this implies is the orchestrator-owed follow-up the
> SOT_FLIP §4 G7 row already notes). Recommended NEXT: **S5c**
> (dead-code/`ZONE_STACK` attr cleanup + SL note flip) and, per the
> S5a ledger, the orchestrator's `.pyd`-rebuild-on-main + the
> separate unmasked combat-blocker LEGAL_SET follow-up.

> **STATUS UPDATE — S5c LANDED (dead-code attr cleanup + SL note
> flip; NO engine / `.pyd` / behavior change) on branch
> `feature/g7-s5c-deadcode-sl-flip`.** The §3 / §5.1 S5c slice is
> complete and is a **small, clean, parity-neutral slice** (not
> padded — the design correctly predicted S5c is the thin
> cleanup tail). What S5c did, exactly:
> 1. **Dead-code attribute cleanup.** Removed the now-obsolete
>    S1/S4-era `#[allow(dead_code)]` on
>    `rust/src/state_ops_zones.rs` `ZONE_STACK` (the §3 / Part-6
>    "Drop `#[allow(dead_code)]` on `ZONE_STACK` if Option β
>    lands" item — Option β DID land in S5a). **Proven genuinely
>    obsolete (not a silent removal):** `cargo build --lib` is
>    warning-clean (0/0) and clippy total warnings are
>    byte-identical before→after (79→79, all the pre-existing
>    `doc list item without indentation` style lint), with **zero
>    `dead_code` diagnostic anywhere** and `ZONE_STACK` in no
>    clippy diagnostic — confirming the constant is genuinely used
>    post-S5a (`find_object_zone` → `ZONE_STACK` at
>    `state_ops_zones.rs:263`, `take_source` reports it
>    `state_ops_resolve.rs:263`, `use`-imported as a source-
>    resolution zone `state_ops_resolve.rs:176`). S5a left nothing
>    unwired — no honest-stop finding. The sibling
>    `#[allow(dead_code)]` on `ZONE_EXILE` was deliberately LEFT
>    (out of S5c's design-doc scope — `ZONE_EXILE` went live at
>    round-14, long pre-S5a; its stale allow is a separate
>    non-blocking cleanup, NOT an S5a-created obsolescence, so
>    force-folding it would over-scope S5c).
> 2. **SL "honest-stopped" → CLOSED flip.** Flipped the
>    `docs/SEARCH_LIMITATIONS.md` G7 mid-game note header from
>    "S1 spell-stack-source-zone honest-stopped" → "spell-stack-
>    source-zone `hand_p0` axis S5a/S5b CLOSED", and appended a
>    `[G7 S5c LANDED ...]` block; the SEPARATE unmasked C1-class
>    combat-blocker `LEGAL_SET_EQ` follow-up + S4b + warp-cast
>    legal-EMISSION axis are kept explicitly STILL-OPEN (S5/S5c do
>    NOT close those — no overclaim).
> Gate: **4-file core 1534 UNMOVED**; `tests_rust` zero-newly-
> failing vs `dba2ff5b` (S5c removes one attribute line — no
> behavior change); `check_audit_coverage_staleness.py` counts
> unchanged (a zone-id `const`, not an `Effect` — no variant-
> inventory shift). `rust/src/` WAS touched (one attribute line in
> `state_ops_zones.rs`) so the orchestrator owes a `.pyd` rebuild
> at merge (functionally a no-op — the only Rust delta is removing
> a compile-time lint allow; identical generated code). NOT
> merged / NOT pushed (orchestrator owns the merge + `.pyd`
> rebuild + cron resync). Recommended NEXT per the G7 owner doc:
> S5 triggers-verify → S6 → S7 (S5a is the satisfied hard
> prerequisite for S7 CE5-removal).

> **Status: DESIGN / SCOPING (verify-first). Docs-only.** This is the
> canonical owner doc for the **S5 spell-stack-source-zone
> re-homing** — the single residual `hand_p0` divergence the
> post-auto-tap `rust_shadow` bake-in trips on (arch2/s1 step 273,
> arch5/s0 step 322), and the explicit linchpin for the S7 CE5-removal
> + CE5-free re-proof. It proposes **no** engine / `rust/` / `src/`
> behavior change; it specifies the slices a future implementation
> lane will land. The 4-file parity gate is unaffected by construction
> (this lane edits only docs). Lineage / cross-refs:
> `docs/RUST_STACK_RESOLUTION_DESIGN.md` (the G7 owner doc — S5 section
> points here), `docs/G7_MIDGAME_STATEEQ_VERIFY_FINDING.md` §5/§6 (the
> immediately-prior verify-finding that pinned this), `docs/SEARCH_
> LIMITATIONS.md` G7 / mid-game note, `docs/SOT_FLIP_CUTOVER_PLAN.md`
> §4 ledger row G7.

> **DECISION (this doc's headline): NOT cleanly sliceable into N
> independent each-byte-equal slices. It is a SMALL IRREDUCIBLE ATOMIC
> serialization-core change (one slice, S5a) followed by genuinely
> independent verification/cleanup slices (S5b, S5c).** The atomic core
> is small and low-LOC but it is *irreducibly atomic* because the
> serialization shape, the fingerprint, the snapshot codec, the
> 4-file/CE field view, the codec slot source, the determinizer pool,
> and the 3 legal-emit sites **all read the one hand-residency
> invariant** and must flip together in a single commit or the parity
> baseline moves mid-slice. The honest recommendation is **(B): a
> single carefully-gated atomic lane (S5a) with a pre-agreed
> baseline-move justification**, then thin independent verify slices.
> The reasoning + the full evidence is below; a manufactured
> "3 independent slices" framing would be dishonest (`feedback_no_
> fallback_hybrids` / verify-first discipline).

---

## Part 0 — The one-paragraph diagnosis (most decision-relevant)

Python's `StackItem` **owns the card object by reference**
(`actions.py:1759-1767` — `StackItem(source=card, …)`); at cast time
the card is `p.hand.remove(card)`'d (`actions.py:1403`; graveyard
`:1450`; exile `:1501`) and `card.zone = Zone.STACK`
(`actions.py:1751`). The card lives in **no zone list** while on the
stack — it is reachable only via `state.stack[i].source`, and
`resolve_top_of_stack` reads it directly: `card = item.source`
(`actions.py:2708`). Rust's `StackItem` carries **only**
`source_obj_id: u32` (`rust/src/state.rs:648-694`) — NOT the
GameObject — and **every** resolve-time source operation finds the
source **by id, walking the 4 Player zone Vecs**:
`find_source_printing_id` (`state_ops_resolve.rs:205-221`, walks
hand/library/battlefield/graveyard), `take_source`
(`:230-246`, same 4 zones), `move_source_post_resolve` (`:285-332`,
calls both), and the `dispatch_event` CAST/ENTERS observer walk
(`:453-503`). There is **no stack-object storage** in Rust: `Player`
has only `hand/library/battlefield/graveyard/exile` Vecs
(`state.rs:518-573`); `GameState` has `stack: Vec<StackItem>`
(`state.rs:1208`) which is id-only. The `ZONE_STACK: u8 = 4` constant
exists but is `#[allow(dead_code)]` and **wired to nothing**
(`state_ops_zones.rs:44-45`). So S1/S4 deliberately keep the cast
spell physically in the owner's `hand` Vec with `zone=ZONE_HAND`
(verified `state_ops_cast.rs:858-874` S1; `:1131-1144` S4;
exile/graveyard arms *normalize into hand* `:830-844` / `:1075-1089`)
purely so the id-keyed 4-zone source-finders still locate it at
resolve. Python's hand-field-view therefore excludes the cast spell;
Rust's includes it ⇒ the residual `hand_p0` divergence. **Re-homing =
giving Rust a place to hold the stack-resident GameObject that is NOT
a hand Vec, while keeping every id-keyed source-finder able to reach
it.** That single invariant is read by 7 surfaces simultaneously,
which is why the core is atomic.

---

## Part 1 — Verify-first surface map (every dependency, file:line)

For each surface: the live-source evidence, and **what breaks if the
spell leaves Rust's hand** (the failure mode a naive "just remove it
from hand" would produce — i.e. what the re-homing must
*simultaneously* fix).

### 1.1 `find_source_printing_id` — `rust/src/state_ops_resolve.rs:205-221`

Walks `[&player.hand, &player.library, &player.battlefield,
&player.graveyard]` for `obj.id == obj_id`, returns `obj.printing_id`.
Called by `move_source_post_resolve` (`:288`) and the spell-effect
fan-out (`resolve_top_of_stack` `:12095`, `:12305`) to discover what
effects the resolving spell has.
**Breaks if spell leaves hand:** returns `None` → `move_source_post_
resolve` early-returns (`:288` `?`) → the resolved permanent is **never
placed on the battlefield** and **no effects fire**. Total resolution
failure. The re-homing MUST make this find the stack-resident object.

### 1.2 `take_source` — `rust/src/state_ops_resolve.rs:230-246`

Walks the same 4 zones (with `ZONE_*` tags), `Arc::make_mut` +
`v.remove(pos)`, returns the owned `(GameObject, pidx, zone_const)`.
Called by `move_source_post_resolve` (`:299`).
**Breaks if spell leaves hand:** returns `None` → `move_source_post_
resolve` early-returns (`:299` `?`) → permanent never lands on bf;
the owned GameObject (carrying `warp_exile_pending`, counters, etc.)
is lost. The re-homing MUST make this take the object from its new
home.

### 1.3 `move_source_post_resolve` — `rust/src/state_ops_resolve.rs:285-332`

`find_source_printing_id` → registry `card_types` →
`post_resolve_destination` (Instant/Sorcery→GY, permanent→BF) →
`take_source` → `obj.zone = dest_zone` → summoning-sick stamp
(`:301-303`) → fresh ETB timestamp + `seed_starting_loyalty_for_etb`
(`:311-318`) → push to dest Player zone. The S1/S4 byte-equality of
`put_into_battlefield` (`actions.py:2969`) was *already proven* by S2
(`RUST_STACK_RESOLUTION_DESIGN.md` S2 status) — **the resolution
SHAPE is correct; only the SOURCE LOOKUP is hand-coupled.**
**Breaks if spell leaves hand:** the two `?` early-returns above. Plus:
the `take_source` return's `zone_const` is observability-only today,
but a future reader keying off "source was in HAND" would now see a
different zone — verify no consumer keys on it (it does not; `_src_
zone` is bound `_`-prefixed at `:299`).

### 1.4 The `dispatch_event` CAST / ENTERS / LEAVES observer walk — `rust/src/state_ops_resolve.rs:453-503`

For `Event::Cast` / `Dies` / `LeavesBattlefield` the observer set is
`bf permanents + an extra-observer multi-zone walk`
(`hand/library/battlefield/graveyard/exile`, `:482-501`) to find the
subject by id. The comment at `:446-452` is explicit: *"For CAST
events, the spell-being-cast is still in the hand zone at dispatch
time."* The `cast_creature` CAST dispatch (`state_ops_cast.rs:853-857`)
fires while the spell is hand-resident; the matcher relies on the
5-zone walk locating it.
**Breaks if spell leaves hand:** the extra-observer walk (`:482-501`)
must include the new stack-home or `SourceIsSelf`-shape "when you cast
this" CAST triggers (and respond-to-cast) silently stop matching —
a *silent* correctness regression (no raise; the trigger just never
fires). The re-homing MUST add the new home to this 5-zone walk.

### 1.5 Rust `StackItem` shape — `rust/src/state.rs:588-823`

`enum StackItemKind {Spell, TriggeredAbility}`; `struct StackItem
{source_obj_id: u32, controller: u8, kind, trigger_payload:
Option<TriggerPayload>, target_obj_id, target_obj_id_2}`. **Carries an
id, not a GameObject.** `new_spell(source_obj_id, controller)`
(`:700`). Contrast Python `StackItem.source` = the live card object
(`actions.py:1761`). The doc comment at `:580-587` explicitly chose
the lower-churn id-struct over an owning enum.
**Relevance:** this is the **serialization shape**. Option α (below)
grows this struct by a `GameObject` (or an `Option<GameObject>` for
the spell kind) — a `state.rs` struct change ⇒ the fingerprint and
every snapshot/field-view that projects the stack must move in the
SAME commit (Part 3). This is the irreducible-atomic core.

### 1.6 The hand-snapshot codec slot source — `rust/src/state_ops_snapshot.rs:103-114` ⇒ `src/mtg_bot/search/rust_zone_view.py:199-217`

`hand_snapshot(pid)` = `players[idx].hand.iter()` → per-object dicts
in zone-insertion order. `RustZoneView._build()` (`rust_zone_view.py:
202-203`) does `for d in self._rust.hand_snapshot(pid): pv.hand.
append(...)`. This `RustZoneView` IS the codec's `_engine_state`
(`rust_engine_adapter.py:663-678` `engine_state` property →
`RustZoneView`). The codec maps a hand-cast `Decision` to a policy
slot by **position within `eng.player_by_id(viewer).hand`**
(`action_encoding.py:47`, `:383`; v1 raw order, v2
`_canonical_zone_sort_key` sort — both operate on the **set** of hand
cards). Python's codec reads the **Python** engine's `p.hand`, which
excludes the cast spell.
**Breaks if spell stays in hand (the CURRENT post-flip latent bug):**
Rust-sourced hand has N cards (incl. the on-stack spell), Python-
sourced has N−1 ⇒ **every subsequent hand card's `SLOT_CAST_FROM_HAND`
/ `SLOT_LAND_FROM_HAND` slot is shifted** whenever a spell is on the
stack. A v17[v2] policy head trained on Python-sourced slots is fed
mis-aligned priors post-flip. Re-homing the spell out of Rust's hand
makes `hand_snapshot` byte-match Python ⇒ codec slot mapping is
byte-identical. **This is a v1/v2-AGNOSTIC fix** — it changes WHICH
cards are in the hand list, not the v1-raw-vs-v2-canonical ordering
*within* it, so it does NOT touch the `positional_v1` /
`canonical_v2` axis (it makes both correct simultaneously). It is
**not a v-chain break** (no retraining needed; the slot semantics are
unchanged — the data source is corrected to match what the weights
were trained against).

### 1.7 The determinizer pool — `src/mtg_bot/search/rust_determinize.py:115-154`

`_determinize_player` pools `for d in rust_state.hand_snapshot(owner_
pid)` then `library_snapshot`, filters `_rust_viewer_knows`, shuffles
`printing_id`s via `set_object_printing_id`. It mirrors Python
`determinize._determinize_player` (`determinize.py:139-145`) which
pools `player.hand` + `player.library` **only** — Python's stack-
resident cast spell is NOT in `player.hand` so it is never in the
pool. `set_object_printing_id` (`state_ops_zones.rs:641-666`) walks
the 5 Player zones, NOT the stack.
**Breaks if spell stays in hand:** Rust pools the on-stack spell into
the hidden set (Python does not) ⇒ pool composition differs by one
object ⇒ `rng.shuffle` permutation differs ⇒ **determinization
diverges** (different hidden-info samples → different ISMCTS/PIMC
search). Re-homing out of hand fixes the pool composition for free.
**Caveat the re-homing must honor:** if the new home is a separate
stack-object store NOT walked by `set_object_printing_id`, that is
*correct* (the determinizer must never re-printing a public on-stack
spell, and Python doesn't) — but the new home MUST be excluded from
the pool the same way Python's stack is, i.e. by simply not being a
hand/library zone. Option β (stack Vec) gets this right by
construction; Option α (StackItem-owned) gets it right because the
object is no longer in any snapshot the pool reads.

### 1.8 The 4-file / CE cross-engine field view — `scripts/parity_smoke.py:1041` + `src/mtg_bot/parity/cross_engine.py:9728`

Rust side: `hand_p0 = tuple(_rust_zone_obj_sig(d) for d in state.hand_
snapshot(0))` (`parity_smoke.py:1041`). Python side:
`view[f"hand_p{pid}"] = ps._zone_signature(p.hand)`
(`cross_engine.py:9728`). `_zone_signature` (`parity_smoke.py:78-136`)
projects `(printing.name, tapped, summoning_sick, damage, net_counters,
attached_to, controller_id, id)` per object in zone order; the `stack`
field is `_zone_signature` over `state.stack` whose entries are
`StackItem`s (the id rides via `obj.source.id`, `:118-123`, matching
Rust's `_rust_stack_obj_sig` over `source_obj_id`).
**Why CE5 masks it today** (`cross_engine.py:10362-10375`): `step_both`
snapshots pre-cast stack floors, applies the `cast_spell` to BOTH,
then (for `kind in _RUST_AUTO_RESOLVE_ACTION_KINDS = {"cast_spell"}`)
drains BOTH stacks to the floor *before* `build_python_field_view` /
`_build_field_view`. Post-drain BOTH engines have the spell **off-hand
and on-bf** (Python via `put_into_battlefield` → `card.zone=BATTLE
FIELD`; Rust via `move_source_post_resolve` → bf). So the
hand-residency *window* is never compared. **WITHOUT CE5 (the bake-in,
and the S7 requirement): the compare is mid-stack, immediately
post-apply** (`rust_shadow.py:461-472` applies to both then
`_assert_state_eq()`), so Python's hand excludes the cast spell, Rust's
includes it ⇒ `hand_p0` diverges. **This is THE S7 linchpin** — see
Part 4.

### 1.9 The 3 legal-emit sites — `rust/src/state_ops_legal.rs:1488, 1650, 1696`

All three are `for obj in self.players[idx].hand.iter()` CastSpell-
emit loops (instant-speed `:1488`, sorcery-speed `:1650`, warp
`:1696`). There is **no stack-membership guard** in them
(verified — no `stack`/`source_obj_id` filter in the loop bodies;
the only `stack` checks are the `stack.is_empty()` sorcery-timing
gates `:1452`). Python's emitters iterate `for card in p.hand`
(`legal.py:246, 323, 365`) which excludes the stack-resident spell.
**Breaks if spell stays in hand:** Rust **re-emits a CastSpell for a
spell already on the stack** (the printing is still a creature/instant
and the mana may be re-payable) → a phantom legal decision Python's
set lacks → **LEGAL_SET_EQ divergence**. *This is currently invisible
only because* STATE_EQ trips first: `rust_shadow.apply()` runs
`_assert_state_eq()` immediately post-apply (`rust_shadow.py:471-472`),
*before* the next `legal_decisions()` LEGAL_SET_EQ check
(`:439-450`), so the `hand_p0` STATE_EQ fires at step 273 and the
legal-set re-emission never gets evaluated. This is exactly the
`G7_MIDGAME_STATEEQ_VERIFY_FINDING.md` §5 diagnostic: with `hand_p0`
hypothetically resolved the games run 273→281 / 322→344 *then* hit
LEGAL_SET_EQ. **Key design consequence: the 3 legal-emit sites are
NOT a separate slice — re-homing the spell OUT of `players[idx].hand`
fixes them for free** (the loops simply no longer see it), byte-
matching Python. If the re-homing kept it in hand and added a guard
instead, that would be 3 separate edits *and* a divergence-risk; the
clean re-home eliminates them structurally.

### 1.10 Fingerprint — `rust/src/state_ops_fingerprint.rs:208, 335-346`

`fingerprint()` emits `zone_signature(state, &p.hand)` (`:208`) and a
separate stack slot built from `si.source_obj_id` (`:335-346`,
8-tuple with most fields Null/0). Python's parity recipe mirrors this
(`parity_smoke.py:_zone_signature` over `p.hand` + `state.stack`).
**Breaks if spell stays in hand:** the Rust fingerprint's hand slot
includes the on-stack spell, Python's does not ⇒ cross-engine
fingerprint divergence (same root as 1.8). STATE_EQ also asserts
*intra-engine fingerprint determinism* (`rust_shadow._assert_state_
eq`) — that is unaffected (same engine, repeated). Re-homing fixes the
cross-engine fingerprint by the same hand-membership correction.
**Atomicity note:** the fingerprint format is a *pinned baseline*
(many `tests_rust`/parity pins hash specific states). Moving a spell
out of hand changes the fingerprint of every mid-stack state — so the
fingerprint change, the snapshot change, and the StackItem/zone change
MUST land in ONE commit with a baseline-rebase (Part 3, Part 5).

### 1.11 Python SoT exact contract (the byte-target) — `src/mtg_bot/actions.py`

- Cast: `p.hand.remove(card)` (`:1403`) | `p.graveyard.remove(card)`
  (`:1450`) | `p.exile.remove(card)` (`:1501`); provenance stamped on
  the **card** (`cast_via_warp :1406`, `cast_via_impending :1415`,
  cast-from-hand flag region `:1416-1424`); `card.zone = Zone.STACK`
  (`:1751`); `card.controller_id = player_id` (`:1752`);
  `state.stack.append(StackItem(source=card, controller_id=…,
  targets=…, countered=…, x_value=…, kicked=…, additional_cost_
  choice_id=…, chosen_modes=…, cast_room_half=…))` (`:1759-1767`).
  **The card is in NO zone list; it is owned by the StackItem.**
- Resolve: `item = state.stack.pop()` (`:2655`); `card = item.source`
  (`:2708`) — **direct reference, no zone lookup**;
  `put_into_battlefield(state, card, item.controller_id)`
  (`:2779`-region) → `obj.zone = Zone.BATTLEFIELD`
  (`actions.py:2981`), `obj.summoning_sick = True` (`:2993`),
  impending/timestamp init (`:3004-3007` …).
- Hand field-view exclusion: because `card` is not in `p.hand`,
  `_zone_signature(p.hand)` (the SoT side of `hand_pX`) never includes
  it; the determinizer pool (`determinize.py:139-145`) never pools it;
  Python `legal.py` `for card in p.hand` never re-emits it. **All
  three Python exclusions follow from the single `p.hand.remove(card)`
  + own-it-on-the-StackItem fact.** The Rust re-home must reproduce
  exactly this: spell not in any hand Vec, reachable for resolve by
  id, gone from every hand-derived projection.

---

## Part 2 — The two architectural options (both touch the serialization core)

The invariant to satisfy: *the stack-resident spell's GameObject must
be (a) findable by `source_obj_id` at resolve, (b) absent from every
hand-derived projection (snapshot/codec/determinizer/legal-emit/
fingerprint/field-view), (c) carrying its mutable fields
(`warp_exile_pending`, counters, provenance) through to bf entry.*

### Option α — `StackItem` owns the `GameObject` (mirror Python exactly)

Add a `source: Option<GameObject>` (or a kind-specific owning variant)
to Rust's `StackItem` (`state.rs:648`). Cast removes the object from
hand/gy/exile and moves it **into the StackItem** (Python's
`StackItem(source=card)`). Resolve reads it off `item` (Python's
`card = item.source`); `move_source_post_resolve` takes it from the
popped StackItem instead of a zone walk; `find_source_printing_id` /
the CAST-observer walk consult the stack's StackItems for spell-kind
sources.
- **Pro:** byte-exact mirror of the Python SoT data model; the spell
  is in literally no zone (exactly Python); determinizer/codec/legal/
  field-view exclusions are automatic (it's not in any snapshot zone).
- **Con:** `StackItem` is `#[derive(Clone, Debug)]` and is the
  serialization/fingerprint stack slot — embedding a `GameObject`
  changes the stack fingerprint shape (today id-only 8-tuple) unless
  the fingerprint stack projection is *deliberately kept id-only*
  (it can be — the fingerprint reads `si.source_obj_id`; an owned
  GameObject doesn't change that field). Still: every `find_source_
  printing_id` / `take_source` / CAST-observer site must learn to
  look in `state.stack[*].source` as a 5th "zone". ~4-6 source-finder
  sites.

### Option β — a stack-object store with `zone = ZONE_STACK`

Add `GameState.stack_objects: Vec<GameObject>` (or `Player.stack: Zone`
per-owner). Cast moves hand/gy/exile → `stack_objects` with
`obj.zone = ZONE_STACK` (the dead `ZONE_STACK=4` constant becomes
live). Extend `find_source_printing_id` / `take_source` / the
CAST-observer walk / `set_object_printing_id` to include the stack
store as a 5th/6th zone. Resolve's `take_source` removes from
`stack_objects`.
- **Pro:** keeps `StackItem` id-only (no struct-shape churn there);
  the `move_source_post_resolve` "take from a zone Vec, push to dest
  Vec" shape is unchanged (just one more source zone); reuses the
  existing zone-walk idiom.
- **Con:** a new `GameState` field IS a serialization-shape change;
  every multi-zone walk that should NOT see a stack spell (the ~50
  effect-arm target finders) must be audited to confirm they don't
  accidentally pick it up (most take `&player.hand,…` explicitly so
  they won't — but it's an audit surface); `hand_snapshot` etc. are
  unaffected (they read `players[idx].hand`), so the
  codec/determinizer/legal/field-view exclusions are automatic and
  byte-clean.

**Recommendation: Option β.** It localizes the change to "add one
zone store + extend the 3 *source-resolution* walks", keeps the
`StackItem` (and thus the stack fingerprint slot) byte-unchanged, and
keeps `move_source_post_resolve`'s proven-byte-equal shape intact —
the S2 byte-equality re-proof stays valid. Option α's StackItem-owns-
GameObject is the *purest* Python mirror but spreads the
`item.source`-vs-zone-walk fork across more resolve arms and risks the
stack fingerprint slot. β's only real cost is the "audit the ~50
effect-arm zone walks don't grab a stack spell" sweep — and those
walks pass explicit zone lists (`&player.hand, &player.library, …`)
that simply won't include the new store unless deliberately added, so
the audit is bounded and mostly confirmatory. **Either way the
serialization core is one atomic commit; β minimizes its blast
radius.**

---

## Part 3 — The decision: NOT cleanly sliceable; ONE atomic core + thin verify slices

### Why the core is irreducibly atomic

The seven surfaces in Part 1 (resolve source-finders 1.1-1.4;
StackItem/zone shape 1.5; snapshot/codec 1.6; determinizer 1.7;
field-view 1.8; legal-emit 1.9; fingerprint 1.10) **all read the same
hand-residency fact**. There is no ordering of sub-changes where each
intermediate state is *both* byte-equal to Python *and* leaves the
4-file/CE baseline unmoved:

- You cannot "remove the spell from hand" first and "make resolve find
  it" second — between those two commits resolution is **broken**
  (1.1/1.2 `?`-early-return → permanent never enters bf). Not
  byte-equal; catastrophically divergent.
- You cannot "add the stack store + make resolve find it" first and
  "exclude it from hand-snapshot/fingerprint" second — between those
  the spell is in BOTH hand and the stack store (double-counted) →
  worse divergence than today.
- The fingerprint/snapshot baseline (1.10) is pinned by existing
  `tests_rust`/parity baselines; the moment the spell's zone changes,
  every mid-stack state's fingerprint changes. That baseline move
  **must** be co-committed with the behavior change and its rebase
  justified — it cannot be a separate "slice" because a half-applied
  state has a fingerprint that matches neither old nor new baseline.

Therefore the re-homing core is **one slice, S5a, irreducibly
atomic**. This is the honest **option (B)** outcome the brief
explicitly sanctions: *"An honest 'this is atomic and here's why +
here's the safest path' is a SUCCESSFUL outcome."* A "3 independent
byte-equal slices" claim would be manufactured — the surfaces are not
separable.

### What IS independently sliceable (the thin verify/cleanup slices)

After S5a lands and is green, two genuinely-independent verification
slices remain (each clean-verify-class, no serialization touch):

- **S5b — codec/determinizer cross-source byte-equality verify
  (pure-Python, no `.pyd`).** With S5a making `hand_snapshot` exclude
  the on-stack spell, prove `RustZoneView`-sourced codec slots ==
  Python-`_engine_state`-sourced codec slots for mid-stack states, and
  `rust_determinize` pool == `determinize` pool. Likely a
  verify-confirm-pins slice (the exclusion is automatic from S5a);
  honest-stop if a residual v1/v2 ordering asymmetry surfaces (it
  should not — S5a doesn't touch ordering). No `rust/src/`, no `.pyd`.
- **S5c — the dead-code / `ZONE_STACK` constant cleanup +
  `SEARCH_LIMITATIONS.md` note flip (docs + Rust dead-code attrs
  only).** Drop `#[allow(dead_code)]` on `ZONE_STACK` if Option β
  lands; retire any S1/S4 "stays in hand" comments that S5a
  invalidates; flip the SL G7/mid-game note from "honest-stopped" to
  "S5a closed". `.pyd`-touching only if it removes a now-dead helper;
  otherwise docs-only and foldable into S5a's lane.

S5b/S5c do **not** make S5a "sliced" — they are *post*-atomic-core
verification, exactly the S2/S3 clean-verify pattern this campaign
already established. The core itself does not decompose.

### Recommended sequencing for the orchestrator

`S5a (single atomic Rust lane, baseline-rebase pre-authorized) →
S5b (pure-Python verify) → S5c (cleanup/docs) → [then S6/S7 per the
G7 owner doc]`.

- **S5a is a single carefully-gated Rust lane.** It is one `.pyd`-
  touching commit. It deliberately moves the cross-engine /
  fingerprint baseline for **mid-stack states** (the whole point —
  the old baseline encoded the bug). The lane MUST ship with a
  **pre-agreed baseline-rebase protocol** (Part 5): the old pins that
  hash mid-stack hand-with-spell states are *expected* to change; the
  rebase is justified by "new code is right — it now byte-matches the
  Python SoT" and re-pinned in the same commit, with a one-line
  ledger entry. This is NOT a silent baseline move; it is an
  announced, justified, single-commit rebase — the same discipline
  G4/G5/G6 closure-flips used for `tests_rust` pins, scaled to the
  fingerprint baseline.
- The 4-file **core 1532** gate is `decision_source="python"` and does
  **not** exercise Rust cast internals or CE5; it is **UNMOVED by
  construction** (verify post-S5a, do not assume — a 4-file-counted
  test that moves is a real regression, not a baseline move).

---

## Part 4 — The CE5-must-hold-WITHOUT-it analysis (the S7 linchpin)

This residual is *the* reason S7 (CE5 removal) cannot proceed without
S5a. The chain:

1. CE5 (`cross_engine.py:10367-10375`) drains BOTH stacks after every
   `cast_spell` *before* the field-view compare. Post-drain both
   engines have the spell off-hand + on-bf, so `hand_pX` matches
   **only because the hand-residency window is never observed**.
2. S7 removes CE5 (empties `_RUST_AUTO_RESOLVE_ACTION_KINDS` /
   deletes the block) so the evidence base is regenerated through the
   honest path. After S7, `step_both` compares **mid-stack**,
   immediately post-apply — exactly like the role-swapped bake-in
   already does (`rust_shadow.py:471-472`, no CE5 equivalent, by
   design per `feedback_no_fallback_hybrids`).
3. Mid-stack, Python's `hand_pX` excludes the cast spell
   (`p.hand.remove(card)` + StackItem-owned, Part 1.11); Rust's
   includes it (S1/S4 "stays in hand"). **Without S5a, removing CE5
   re-exposes the exact `hand_p0` divergence the bake-in already trips
   on — at scale, across the entire probe + trajectory base.** S7
   would regress 307/475 + the trajectory sweep instead of re-proving
   them.
4. **Therefore S7 is gated on S5a.** S5a makes Rust and Python
   *both* "spell on stack, not in hand, awaiting priority passes" at
   every per-apply compare point — they then resolve in lockstep
   through the same decision sequence, and CE5's drain becomes a true
   no-op that S7 can delete with the evidence base re-proving
   byte-equal CE5-free. This is precisely the
   `RUST_STACK_RESOLUTION_DESIGN.md` Part 3 "green WITHOUT CE5"
   requirement; S5a is its missing precondition. **Acceptance for the
   flip still requires all of: S1–S5 (incl. S5a) landed, CE5 removed
   (S7), probe + trajectory re-proven CE5-free, C4 re-sweep
   divergence-clean CE5-free — S5a unblocks the last three.**

Non-acceptance (restated for this slice): a bake-in/`step_both` that
is green only because CE5 (or any CE5-equivalent drain) is present is
NOT acceptance evidence; a `_DOCUMENTED_ACCEPTED_FIELDS` carve-out for
`hand_pX` is NOT acceptance evidence (the frozenset stays empty for
the G7 axis — same false-green the user decision closed).

---

## Part 5 — Risk, magnitude, baseline-rebase protocol

### 5.1 Magnitude (honest)

| Slice | Nature | `.pyd`? | Likely cycles |
|---|---|---|---|
| **S5a** | Single atomic Rust lane: add stack-object store (Option β) / extend 3 source-finders / cast moves hand→stack-store / resolve takes from it / **co-committed fingerprint+snapshot baseline rebase** + closure-flip the S1/S4 "stays in hand" `tests_rust` pins | YES (Rust; single serialized lane) | **2–3** |
| S5b | Pure-Python verify: codec-slot + determinizer cross-source byte-equality pins | NO | 1 |
| S5c | Dead-code/`ZONE_STACK` cleanup + SL note flip | only if removing a dead helper; else docs-only | 0–1 |
| **Total** | | | **~3–5 cycles** |

Low-LOC but **high-blast-radius and irreducibly atomic at the core** —
the cycle count is dominated by the baseline rebase + the bake-in
re-verify, not the engine LOC. This is materially smaller than S1
(S1 was the load-bearing rewire); it is closer to S4's rider-deferral
class plus a baseline rebase.

### 5.2 Biggest risks

1. **Baseline-rebase blast radius (the defining risk).** Every pinned
   fingerprint/snapshot baseline that hashes a mid-stack
   hand-with-cast-spell state changes. Mitigation: the
   **baseline-rebase protocol** (5.3) — enumerate the moved pins,
   re-pin in the SAME commit with the new-code-is-right justification,
   one ledger line. NOT a silent move.
2. **Effect-arm zone-walk false-grab (Option β only).** A ~50-site
   audit that no effect-arm target finder accidentally treats a
   stack-store object as a hand/bf target. Bounded: the walks pass
   explicit zone-lists; confirmatory. Mitigation: a targeted pin that
   a Doom-Blade-shape spell on the stack is not itself a legal target
   of another spell on the stack.
3. **Silent CAST-trigger regression (Part 1.4).** If the
   `dispatch_event` extra-observer walk isn't extended to the new
   home, "when you cast this" triggers silently stop firing — no
   raise. Mitigation: a cross-engine respond-to-cast / cast-trigger
   pin in S5a (not deferred), per `feedback_silent_noop_pipelines`.
4. **Determinizer pool exactness.** The new home must be excluded from
   the hidden pool exactly as Python excludes its stack. Option β: the
   pool reads `hand_snapshot`/`library_snapshot` which won't include
   the stack store — correct by construction. Verify in S5b, don't
   assume.
5. **The S7 dependency is now hard, not soft.** S5a is a strict
   prerequisite for S7; sequencing S7 before S5a re-opens the
   divergence at scale (Part 4). Flag in the cutover ledger.

### 5.3 The baseline-rebase protocol (S5a's required gating)

Because S5a deliberately moves the mid-stack cross-engine /
fingerprint baseline (the old baseline encoded the bug), the
implementation lane MUST, in the single S5a commit:

1. Run the pin/baseline suite, capture every baseline that changed.
2. Confirm each change is *exactly* "the cast spell moved out of the
   hand projection / into the stack projection" — i.e. **new code is
   right, it now byte-matches the Python SoT** (`feedback_parity_new_
   code_is_right`). Any baseline change that is NOT this shape is a
   real bug — fix Rust, do not re-pin.
3. Re-pin the confirmed-correct baselines in the SAME commit.
4. One ledger line in `SEARCH_LIMITATIONS.md` (the G7/mid-game note)
   + `SOT_FLIP_CUTOVER_PLAN.md` §4: "S5a moved the mid-stack
   fingerprint baseline; justification = byte-match to Python SoT
   (`actions.py:1403`/`:1751`); 4-file core 1532 UNMOVED (verified)."
5. Verify the **4-file core 1532** gate is UNMOVED (it is
   `decision_source="python"`, dormant w.r.t. Rust cast internals) —
   a move there is a regression, not a baseline rebase.

This is the same announced-justified-single-commit discipline the
G4/G5/G6 closure-flips used for `tests_rust` pins, escalated to the
fingerprint baseline because S5a's correctness *is* the baseline
move.

---

## Part 6 — Summary recommendation

- **Decision: (B) — not cleanly sliceable into independent byte-equal
  slices. ONE irreducibly-atomic Rust core lane (S5a) + thin
  post-core verify/cleanup slices (S5b/S5c).**
- **Architecture: Option β** (a `ZONE_STACK` stack-object store; keep
  `StackItem` id-only; extend the 3 *source-resolution* walks only),
  for minimum serialization blast radius and to preserve S2's
  proven-byte-equal `move_source_post_resolve` shape.
- **S5a ships with the Part 5.3 baseline-rebase protocol pre-agreed**;
  the mid-stack fingerprint/cross-engine baseline move is expected,
  announced, single-commit, new-code-is-right-justified.
- **S5a is a hard prerequisite for S7** (CE5 removal) — it is the
  linchpin that lets parity hold WITHOUT CE5. Sequence: S5a → S5b →
  S5c → S6 → S7 (per the G7 owner doc).
- The codec-slot / determinizer / legal-emit / fingerprint divergences
  are **all fixed for free by the single hand-membership correction**
  — they are not separate slices; this is *why* the core is atomic and
  *why* the fix is high-value (one correct change closes seven
  surfaces). It is **v1/v2-action-encoding-agnostic** (corrects WHICH
  cards are in the hand list, not the ordering within it; no v-chain
  break, no retraining).
