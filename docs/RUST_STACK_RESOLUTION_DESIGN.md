# Rust real stack-and-priority `CastSpell` resolution — verify-first, sliced, parity-safe design (the dominant G7 flip blocker)

> **Status: DESIGN (verify-first). Docs-only.** This is the canonical
> owner doc for **G7** — the dominant remaining SoT-flip blocker
> surfaced by the C4 scaled re-sweep (0/300 PASS @ `e87a6ebe`). It is
> in the lineage of `docs/RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`
> (C1) and `docs/NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md` (B3). It
> proposes **no** engine / `rust/` / `src/` behavior change; it
> specifies the slices a future implementation lane will land. The 4-file
> parity gate is unaffected by construction (this lane edits only docs).
> Cross-refs: `docs/C4_RESWEEP_EVIDENCE.md`, `docs/SEARCH_LIMITATIONS.md`
> G7 OPEN section, `docs/SOT_FLIP_CUTOVER_PLAN.md` §4 ledger row G7,
> `docs/HANDOFF_CONTINUOUS_PIPELINE.md` cycle-18 ⚠ block.

> **USER DECISION (settled — recorded, not re-litigated here).** Rust
> **MUST implement real stack-and-priority `CastSpell` resolution**, not
> accept-atomic-and-reconcile-in-harness. The CE5 cast-vs-resolve mirror
> (`cross_engine.py:10313`) must eventually be **REMOVED** and parity
> must hold **WITHOUT it**. The G7-section "Fix scope estimate" in
> `SEARCH_LIMITATIONS.md` and the §4 G7 ledger row both currently
> recommend *porting CE5 into the bake-in* — that recommendation is
> **superseded by this doc** per the user decision (porting CE5 in is
> the false-green path the decision explicitly rejects). This doc owns
> the real fix.

---

## Part 1 — Verify-first current state (quote file:line)

**Headline diagnosis (the single most decision-relevant output):**

> **Atomic resolution is a NARROW, REMOVABLE short-circuit on exactly
> ONE of three cast primitives, sitting on top of a substantially-
> complete, already-wired Rust stack + resolution + priority-loop
> stack.** It is **NOT** a deep architectural absence. Rust already
> has: a real `stack: Vec<StackItem>` on `GameState`; a full
> effect-dispatching `resolve_top_of_stack` (ETB/DIES/LEAVES trigger
> fan-out, CR 608.2m post-resolve source movement to battlefield *or*
> graveyard, pending-decision auto-resolve); a non-creature
> instant/sorcery cast primitive (`cast_spell_noncreature`) that
> **already pushes a `StackItem` and does NOT auto-resolve**; and a
> Rust-driver adapter (`RustGameStateAdapter._run_priority_action`)
> that **already runs a real CR-117.4 priority loop calling the
> effect-dispatching `resolve_top_of_stack`**. The ONE hole is
> `cast_creature` (and its sibling `cast_creature_warp`): a permanent
> spell is moved hand→battlefield *inside the cast primitive*,
> skipping the stack entirely. Closing G7 the real way is therefore a
> **rewire-not-rebuild** effort: make the permanent-spell cast push a
> `StackItem` like `cast_spell_noncreature` already does, extend
> `resolve_top_of_stack`/`move_source_post_resolve` to carry the
> permanent-spell provenance (summoning-sickness, warp/impending/room
> riders, ETB), and let the already-present priority loop drain it.

### 1.1 How Rust currently handles a `CastSpell` apply (the exact short-circuit)

`apply_action`'s dispatch arm (`rust/src/state_ops_actions.rs:287-380`)
routes `Action::CastSpell` as a thin delegator:

```
rust/src/state_ops_actions.rs:360-379
  let player_id = slf.borrow().priority_player;
  if use_warp {
      slf.call_method1("cast_creature_warp", (card_id, player_id))?;
  } else {
      let cast_spell_ok: bool = slf
          .call_method1("cast_spell_noncreature", (card_id, player_id))?
          .extract()?;
      if !cast_spell_ok {
          slf.call_method1("cast_creature", (card_id, player_id))?;
      }
  }
```

Three primitives, **two distinct stack disciplines**:

- **`cast_spell_noncreature`** (`state_ops_cast.rs:800-963`) — the
  round-70 spell-card-bridge lever. **Already stack-correct:**
  `self.stack.push(crate::state::StackItem::new_spell_with_targets(...))`
  at `state_ops_cast.rs:952-957`; the card **stays in hand**; the
  primitive **returns without resolving** (Delta 7, docstring
  `:789-794`: "Resolve is NOT fused. The primitive pushes the
  StackItem and returns; the harness drives `resolve_top_of_stack`
  separately"). This is the proof-of-pattern for the whole G7 fix —
  the desired shape already exists for instants/sorceries.

- **`cast_creature`** (`state_ops_cast.rs:449-566`) — **the G7 hole.**
  Docstring `:444-448` is explicit: *"No-stack semantics. The Python
  pipeline pushes a `StackItem`, settles priority, then resolves;
  this primitive short-circuits to the resolved state."* Concretely it
  pays mana (`:508-512`), fires `Event::Cast` (`:525-529`), then calls
  `move_from_hand_to_battlefield(self, idx, obj_id)`
  (`:540`) — the card goes **hand→battlefield in the cast call**,
  stamps `summoning_sick = true` (`:544-545`), and resets priority
  (`:563-564`). The stack is **never touched**.

- **`cast_creature_warp`** (`state_ops_cast.rs:621-743`) — same
  no-stack short-circuit as `cast_creature` with warp/graveyard/life
  riders; `move_from_hand_to_battlefield` / `move_from_graveyard_to_
  battlefield` at `:716-720`, no stack push.

So: **Rust pushes the spell to a real stack for instants/sorceries and
never stacks it at all for permanents.** The atomic resolution is the
permanent-spell short-circuit only.

### 1.2 The stack / priority / resolution machinery Rust ALREADY has

This inventory is the load-bearing half of the verify-first finding.

| Machinery | Location | State |
|---|---|---|
| `stack: Vec<StackItem>` on `GameState` | `rust/src/state.rs` (foundation commit); manipulated throughout `state_ops_stack.rs` | **Present.** Top = last element (`state_ops_stack.rs:7-8`). `StackItem` carries `source_obj_id`, `controller`, `kind` (Spell / TriggeredAbility), `target_obj_id`, `target_obj_id_2`, `trigger_payload`. |
| `push_to_stack` / `peek` / `pop` / `remove_from_stack` / `stack_snapshot` / `stack_size` / `is_stack_empty` | `state_ops_stack.rs:35-225` | **Present.** `StackItem::new_spell` / `new_spell_with_targets` / `new_trigger` constructors used. |
| `resolve_top_of_stack` (the pymethod CE5 calls as `resolve_top_of_stack_rust`) | `rust/src/state_ops_resolve.rs:12011-12247` | **Present + FULL.** Triggered-ability branch (`:12028-12090`), spell branch: effect fan-out loop (`:12149-12158`), **`move_source_post_resolve`** (`:12168`), ETB dispatch (`:12201-12203`), DIES/LEAVES drains (`:12212-12235`), `auto_resolve_pending` (`:12245`). Carries payload targets via the `current_resolve_payload_target_id[_2]` save/set/restore bracket (`:12137-12156`). |
| `move_source_post_resolve` — CR 608.2m | `state_ops_resolve.rs:285-332` | **Present + permanent-aware.** `post_resolve_destination(&card_types)` → instants/sorceries to **graveyard**, permanents to **battlefield**; `if dest_zone == BATTLEFIELD && creature { obj.summoning_sick = true; }` (`:301-303`); fresh ETB timestamp + walker `starting_loyalty` seed (`:311-318`). **This already knows how to land a resolving creature spell on the battlefield with summoning sickness.** |
| `resolve_top_of_stack_pause` (no auto-resolve variant) | `state_ops_resolve.rs:12261+` | **Present.** For harnesses that introspect mid-resolution. |
| `process_stack_until_empty` (greedy drain, 1000-cap) | `state_ops_stack.rs:133-157` | **Present.** Composes pop+resolve; does NOT model priority hand-off (docstring `:104-110`). |
| `dispatch_event` / `drain_pending_etb_dispatches` / DIES / LEAVES | `state_ops_resolve.rs:406 / :903 / drain_pending_dies/leaves` | **Present.** Trigger fan-out substrate the resolver and the cast primitives both use. |
| Priority primitives: `pass_priority` (bumps `consecutive_passes`), `give_priority_to`, `get_priority_player`, `get_consecutive_passes` | `state_ops_priority.rs:145-168 / 98-128` | **Present.** |
| **G3 composer** `complete_step_via_priority_round` | `state_ops_priority.rs:260-296` | **Present but POP-ONLY.** Non-empty-stack leg does `state.stack.pop()` (`:284`) with **NO `resolve_top_of_stack`** — docstring `:228-231` + module note `:52-73` flag it as a "pop-only stepping-stone … real effect dispatch lives in `state_ops_resolve.rs::resolve_top_of_stack`". Pinned by `RUST_PARITY_GAPS.md` I25 `:688-754`. **The composer is NOT the resolution path** in production — see next row. |
| The REAL Rust-driver priority loop | `src/mtg_bot/search/rust_engine_adapter.py:421-511` `_run_priority_action` | **Present + effect-dispatching.** `PassPriority` → on a completed pass round with non-empty stack it calls **`self._rust.resolve_top_of_stack()` + `apply_sbas()` + `_reset_priority_to_active()`** (`:434-444`), explicitly *"NOT the pop-only complete_step_via_priority_round — that does not fire effects"* (`:436-437`). Empty stack → `advance_phase()` + `_run_step_enter_sbas()` (G6 closure). This is the loop the bake-in's Rust adapter runs. |
| `legal_decisions` instant-speed `CastSpell` emission + flash | `state_ops_legal.rs` (per `RUST_PARITY_GAPS.md` I46 `:3231-3300`) | **Present.** Two-pass emission sharing a `seen_castspell` HashSet: an instant-speed pass ABOVE the sorcery-timing short-circuit (`is_instant || keywords.contains("flash")`), then sorcery-speed pass after PlayLand. Honors flash; emits at instant-speed windows. **This means once `cast_creature` stacks the spell, the response-window emission substrate already exists.** |

**Diagnosis conclusion:** the stack model, the resolver, the
post-resolve permanent mover, the trigger fan-out, the instant-speed
legal emission, and a real effect-dispatching priority loop are **all
already present and exercised**. `cast_spell_noncreature` proves the
exact target shape works end-to-end today. The G7 gap is a **single
short-circuit on the permanent-spell cast primitive(s)** plus the
provenance plumbing a stacked permanent spell needs (summoning-sick,
warp/impending/room riders, cast-from-X flags) that today is applied
inside the atomic primitive and must move to resolution time. This is
**tractable rewire**, not a ground-up build.

### 1.3 The exact Python SoT semantics Rust must byte-mirror

The source of truth (`decision_source="python"`, never modified —
Phase 5 "converge Rust toward Python"):

- **`apply_action(CastSpell)`** → `actions.py:995-1003` → `_cast_spell`
  (`actions.py:1361-1798`). `_cast_spell` selects cost (room/impending/
  warp/normal — `:1385-1402`), removes the card from its source zone
  (`p.hand.remove(card)` `:1403`; graveyard/exile branches
  `:1437-1480`), stamps provenance on the **card** (`cast_via_warp`
  `:1406`, `cast_via_impending` `:1415`, `cast_via_hand` `:1425`),
  selects targets up-front (`_select_spell_targets`, `:1576`), sets
  `card.zone = Zone.STACK` / `card.controller_id` (`:1751-1752`),
  applies ward (`:1758`), and **pushes `StackItem(source=card,
  controller_id=…, targets=…, countered=…, x_value=…, kicked=…,
  additional_cost_choice_id=…, chosen_modes=…, cast_room_half=…)`**
  onto `state.stack` (`actions.py:1759-1767`). It increments
  `spells_cast_this_turn` (`:1777`) and fires `Event.IS_CAST`
  (`:1795-1798`). **The spell is now ON THE STACK; nothing is on the
  battlefield yet.**

- **The priority pass loop** → `simulate.py:priority_loop`
  (`:222-282`). After a non-pass action it runs `state_based_actions`,
  resets `pass_count=0`, `priority_idx=_next_alive(active)` (`:274-282`).
  On `PassPriority`: `pass_count += 1`; when `pass_count >=
  alive_count()` **and `state.stack` is non-empty** →
  `resolve_top_of_stack(state)` + `state_based_actions(state)` +
  `pass_count=0` + `priority_idx=_next_alive(active)` (`:251-267`);
  empty stack → return (step ends). This is the CR 117.4 loop the
  Rust-driver adapter's `_run_priority_action` already ports
  (`rust_engine_adapter.py:421-511`).

- **`resolve_top_of_stack`** → `actions.py:2654-2793`. `item =
  state.stack.pop()`. Countered → graveyard (`:2659-2662`). Ability →
  `item.ability.effect.resolve(...)` (`:2667-2705`). **Spell**: if
  permanent & not instant/sorcery → aura attach OR
  `state.log(... resolves onto the battlefield)` then
  `put_into_battlefield(state, card, item.controller_id)`
  (`:2714-2779`); if instant/sorcery → `spell_effect.resolve(...)`
  then `_send_to_graveyard_or_library(state, card)` (`:2780-2790`).
  `put_into_battlefield` (`actions.py:2969+`) is where the permanent
  actually enters bf, time-counters / impending init, summoning
  sickness, ETB triggers go on the stack — **all at resolution time,
  not at cast time.** This is the contract Rust's
  `move_source_post_resolve` + the ETB-dispatch tail at
  `state_ops_resolve.rs:12168-12245` must byte-mirror for the
  permanent-spell case (it already does for the instant/sorcery case
  that `cast_spell_noncreature` feeds it).

- **Response / instant windows.** Because the spell sits on the stack
  through ≥1 full priority round, the opponent gets priority with the
  spell on the stack and `legal_actions` emits instant-speed
  `CastSpell` (counterspells/instants) — Python `legal.py:339-366`;
  Rust's mirror is the I46 two-pass emission
  (`RUST_PARITY_GAPS.md:3231-3300`). **Once Rust stacks the permanent
  spell, the response window is created automatically by the
  already-present loop + legal emission** — no new window machinery.

- **The CE5 cast-vs-resolve mirror** (`cross_engine.py:10305-10387`,
  `_RUST_AUTO_RESOLVE_ACTION_KINDS = {"cast_spell"}` `:10247`). After
  `step_both` applies a `cast_spell` to both engines it calls
  `resolve_top_of_stack_python(py_state, floor=py_stack_floor)` +
  `resolve_top_of_stack_rust(rust_state, floor=rust_stack_floor)`
  (`:10373-10375`) — draining BOTH stacks to the pre-cast floor so the
  field compare sees Python's spell **resolved off the stack** to
  match Rust's atomic post-state. `resolve_top_of_stack_python`
  (`:10181-10238`) drains Python's stack; `resolve_top_of_stack_rust`
  (`:10250-10302`) drains Rust's (it exists *because* Rust's no-stack
  `cast_creature` can still push ETB triggers via
  `move_from_hand_to_battlefield`). **This is the masking layer the
  entire prior parity evidence base was generated through, and it must
  be removed for the flip — see Part 3.**

- **The bake-in (no CE5 equivalent — the G7 trip).**
  `rust_shadow.py:ShadowCheckedRustAdapter.apply()` (`:455-472`)
  applies the decision to `self._rust` then `self._py`, then — if not
  terminal — immediately calls `_assert_state_eq()` (`:471-472`).
  `_assert_state_eq` (`:361-407`) does `compare_fields(py_view,
  rust_view)` with `_DOCUMENTED_ACCEPTED_FIELDS = frozenset()`
  (`:359`, empty post-G4). **No post-`CastSpell` stack drain.** So on
  the first permanent-spell cast: Rust has resolved atomically
  (battlefield carries the permanent, stack empty), Python has the
  spell on `state.stack` (not on bf) → STATE_EQ raises on
  `[('battlefield', …), ('stack', …)]` + caster `hand_pX`/
  `mana_pool_pX`. 238/300 C4 games (`C4_RESWEEP_EVIDENCE.md:91-124`).

**New-code-is-right contract:** every slice below makes **Rust** match
the Python SoT (stack-then-resolve). Python is never modified; no
tripwire is weakened; no Python quirk is mirrored. A parity failure
during implementation is a Rust bug to fix, not a signal to reconcile
in the harness.

---

## Part 2 — Sliced, parity-safe implementation design

Ordering principle: land the **stack push** before removing CE5, so
the existing `resolve_top_of_stack`/priority-loop machinery resolves
the now-stacked spell and the gate stays green WITH CE5 (CE5 just
becomes a no-op drain since both stacks already drain via the loop);
then prove green WITHOUT CE5 (Part 3). Every slice is independently
mergeable and keeps the 4-file core gate at the **1532** baseline
(no `src/`/Python SoT change; Rust-only behavior changes are tested by
`tests_rust/` + the rust-adapter / rust_shadow suites — the 4-file
1532 gate is `decision_source="python"` and is dormant w.r.t. Rust
cast internals, so it is UNMOVED by construction; any byte-shift in a
4-file-counted test is a real regression to fix, not a baseline move).

> **`.pyd`-touching note (applies to S1–S4).** Every slice below edits
> `rust/src/*.rs` ⇒ each is a **single Rust lane**; the orchestrator
> serializes Rust lanes (one in-flight `.pyd` rebuild at a time). Each
> Rust merge fires the residue cadence + a `.pyd` rebuild + the
> post-merge resync per `feedback_mtg_bot_merge_as_you_go` Cadence
> rules — flagged here per slice; the orchestrator owns the actual
> resync (HARD STOP for any implementation lane).

### Slice S1 — `cast_creature` pushes a permanent `StackItem`, does NOT auto-resolve

- **Scope.** Rewrite `cast_creature` (`state_ops_cast.rs:449-566`) to
  the `cast_spell_noncreature` shape: pay mana, fire `Event::Cast`,
  push a permanent-flavored `StackItem` (card **stays in hand**, NOT
  moved to bf), reset priority/passes, return `true`. **Delete** the
  `move_from_hand_to_battlefield` call + the post-push
  `summoning_sick`/priority stamps that belong at resolution time.
- **Rust files touched.** `state_ops_cast.rs` (rewrite `cast_creature`);
  `state.rs` IF `StackItem` needs a `summoning_sick_on_resolve` / cast
  provenance discriminant the spell path lacks (verify: `new_spell`
  already exists; a permanent-spell may need a flag so
  `move_source_post_resolve` knows to stamp summoning sickness — but
  `move_source_post_resolve:301-303` ALREADY stamps `summoning_sick`
  for creature-typed sources, so likely **no `state.rs` change** — the
  resolver infers it from `card_types`. Confirm during impl;
  state.rs-touch is a serialized-lane escalation if needed).
- **Python SoT contract.** `_cast_spell` `actions.py:1403/1751-1767`
  (remove from hand → `zone=STACK` → `state.stack.append(StackItem(...))`).
  Provenance stamped on the card at cast (`cast_via_hand` `:1425`,
  etc.) — for S1 the synthetic-deck cards have no riders so a bare
  `new_spell` push is byte-equal; riders are S4.
- **Parity-verification.** `tests_rust/test_cast.py` (rewrite the
  no-stack pins to stack-push pins — closure-flip pattern per
  G4/G5/G6); `tests_rust/test_stack.py` (a permanent spell on the
  stack resolves to bf via `resolve_top_of_stack`); the rust-adapter
  suite (the `_run_priority_action` loop now drains it). Bake-in smoke
  stays green WITH CE5 (CE5's `resolve_top_of_stack_rust` now drains
  the just-pushed permanent spell instead of being a near-no-op).
- **`.pyd`-touching:** YES (Rust). Single Rust lane; residue + rebuild
  + resync cadence (orchestrator-owned).
- **Risk.** MEDIUM. The summoning-sickness timestamp + ETB ordering
  must come out byte-identical when deferred from cast-time to
  resolve-time. `move_source_post_resolve` already does the bf-entry +
  ETB-timestamp + ENTERS dispatch (`:311-318`, `:12201-12203`) — the
  risk is residual ordering (ETB timestamp counter advance moves from
  the cast call to the resolve call; any other action between cast and
  resolve that reserves a timestamp will shift it). New-code-is-right:
  fix Rust ordering to match Python `put_into_battlefield`.

### Slice S2 — `resolve_top_of_stack` byte-equal with Python for the permanent-spell path

> **STATUS: S2 LANDED — CLEAN-VERIFY NO-OP (no resolver code change).**
> Verify-first read against live source @ `d59970c9` concluded the
> resolver is **already byte-equal** with Python `put_into_battlefield`
> (`src/mtg_bot/actions.py:2969`; NOTE the brief's
> `src/mtg_bot/engine/actions.py` path is stale — the SoT lives at
> `src/mtg_bot/actions.py`) on all THREE S2 axes for the **only
> permanent-spell type S1 can stack**: a CREATURE spell via
> `cast_creature` (`state_ops_cast.rs:492`, hard `Creature` gate
> `:541-542`). **Axis 1 (ETB-timestamp monotonicity):** byte-equal —
> the parity contract reads bf ORDER (`battlefield_snapshot`
> stable-sort by `etb_timestamp`, `state_ops_snapshot.rs:211`), never
> absolute counter values, so Rust's separate-but-monotonic
> `next_etb_timestamp` (CE4-era design, predates S2) is byte-equal to
> Python's shared `next_timestamp` for relative bf ordering; the
> `&& creature` summoning-sick guard at
> `state_ops_resolve.rs:301-303` agrees with Python's unconditional
> `actions.py:2993` set for the creature case. **Axis 2 (ENTERS
> push-ordering):** byte-equal — both engines dispatch ENTERS only
> after the resolving spell's StackItem is popped AND the object is on
> bf. **Axis 3 (aura/attach):** UNREACHABLE via the S1 primitives —
> bare Enchantment/Artifact/Planeswalker/Aura fall through BOTH
> `cast_spell_noncreature` (Instant|Sorcery only) and `cast_creature`
> (Creature only), so the latent `&& creature` non-creature-permanent
> divergence and the missing resolve-time aura attach
> (`actions.py:2720-2758`) are S4+ territory (as this slice's scope
> note already anticipated: "auras may be S4/out-of-scope first cut").
> S2 added **no `rust/src/` change**; it landed 4 verify-confirm pins
> in `tests_rust/test_resolve.py` (`test_s2_*`) locking the byte-equal
> conclusion + the non-creature-permanent boundary tripwire (a future
> S4 that opens non-creature-permanent casting trips the boundary pin
> and is forced to fix the guard + aura attach — new-code-is-right).
> 4-file core gate **1532 UNMOVED**. **S3/S4 note surfaced:** the
> `&& creature` summoning-sick guard and the absent resolve-time
> aura-attach are S4's, NOT S3's — and S3 must NOT assume the
> non-creature-permanent resolve path exists yet (it does not until
> S4). The 2 pre-existing `tests_rust/test_triggers.py` land-search /
> landfall failures (`test_rs2_search_library_for_basic_land_tapped_
> fires_etb`, `test_landfall_observer_fires_on_land_arrival`) are
> **pre-existing on `main` @ `d59970c9`** (fail identically on the
> shared venv with zero code change), NOT in the 4-file gate, and
> outside S2 scope — flagged for the orchestrator.

- **Scope.** Verify/extend `move_source_post_resolve` +
  `resolve_top_of_stack`'s spell branch so a stacked permanent spell
  lands on bf **byte-identical to Python `put_into_battlefield`**:
  summoning sickness, ETB-timestamp monotonicity, ENTERS trigger
  push-ordering, aura attach (if a permanent-spell is an aura — verify
  scope; auras may be S4/out-of-scope first cut). Mostly a
  **verification + targeted-fix** slice — the resolver already handles
  the instant/sorcery + permanent destinations (`:289-303`).
- **Rust files touched.** `state_ops_resolve.rs` (resolver spell
  branch / `move_source_post_resolve` only if a byte-shift is found).
- **Python SoT contract.** `actions.py:2707-2779` + `put_into_battlefield`
  (`actions.py:2969+`) — bf entry, time-counter/impending init,
  summoning sickness, ETB-on-stack ordering.
- **Parity-verification.** `tests_rust/test_resolve.py` /
  `test_stack.py` permanent-spell-resolution pins; cross-engine
  Effect-half probes for a permanent spell with an ETB trigger; the
  rust-adapter loop end-to-end.
- **`.pyd`-touching:** YES (Rust) — only if a fix is needed; a
  pure-verification S2 with no code change is docs-noted and folded
  into S1's lane. Single Rust lane otherwise.
- **Risk.** LOW–MEDIUM. The machinery is present; risk is an
  ETB-ordering byte-shift that the synthetic deck doesn't exercise but
  a real deck does.

### Slice S3 — priority / response windows + `legal_decisions` + the B1/C1 keystone interaction

- **Scope.** With S1/S2 landed, a cast permanent spell now sits on the
  stack across ≥1 priority round, so the opponent gets a real response
  window. Verify the already-present pieces compose: the Rust-driver
  loop (`rust_engine_adapter.py:_run_priority_action:421-511`) drains
  it via the effect-dispatching `resolve_top_of_stack`; `legal_
  decisions` emits instant-speed `CastSpell` correctly with the
  permanent spell on the stack (I46 two-pass, `RUST_PARITY_GAPS.md:
  3231-3300`); priority resets at CR-117.1c moments byte-equal with
  Python.
- **EXPLICIT B1/C1 INTERACTION — this slice is NOT independent of C1
  Slices 2/3.** With a real response window, Rust's `legal_decisions`
  is now the *authoritative decision source at instant speed too*. The
  C1 keystone (`RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md` —
  `legal_decisions == legal_actions` mana/target/additional-cost
  asymmetry; Slice 1 mana DONE `f1f09bbb`, Slices 2 target-
  satisfiability / 3 additional-cost NOT landed) governs whether the
  response-window emission is byte-equal. The C4 re-sweep already
  surfaced this as the **secondary** 22/300 LEGAL_SET_EQ shape
  (`C4_RESWEEP_EVIDENCE.md:126-147`). **S3 and C1 Slices 2/3
  co-evolve:** stacking the permanent spell *creates* the very
  instant-speed legal-set comparison surface C1 Slices 2/3 must be
  correct on. Sequencing (Part 4): C1 Slices 2/3 should land in
  parallel with / just before S3 so S3's response-window LEGAL_SET_EQ
  isn't tripping on a known-open C1 axis. This is the B1 keystone
  named in `SOT_FLIP_CUTOVER_PLAN.md` §4 — flag the dependency, do not
  fold C1 into this lane.
- **Rust files touched.** Likely **none new** (verification slice over
  S1/S2 + the present loop/emission) — unless a priority-reset
  byte-shift is found in `state_ops_priority.rs` / `state_ops_cast.rs`.
  If `cast_creature`'s `priority_player = active_player` reset
  (`state_ops_cast.rs:563`) is now wrong (it should reset *after
  resolution*, not after the cast push — Python resets via the
  priority loop post-resolution `simulate.py:266-267`), this slice
  fixes that ordering. **High-probability small Rust fix:** the
  cast-time priority reset that made sense for no-stack semantics is
  wrong for stack semantics (the docstring at `state_ops_cast.rs:
  551-562` explicitly anticipates this: *"A future stack-using cast
  slice will need to re-think when the reset fires"*).
- **Python SoT contract.** `simulate.py:priority_loop:251-282` (reset
  to `_next_alive(active)` after resolution / after non-pass action);
  `legal.py:339-366` (instant-speed emission) vs I46.
- **Parity-verification.** Rust-adapter + rust_shadow suites; a
  cross-engine counterspell/instant-response pin (opponent casts an
  instant in response to a permanent spell, both engines agree on the
  legal set + the resolved order). This is the first test of real
  nested response windows.
- **`.pyd`-touching:** YES if the priority-reset fix lands (Rust);
  single Rust lane.
- **Risk.** MEDIUM–HIGH. This is where the "Rust priority-round
  composer doesn't support nested response windows" risk lives (Part
  4). The production loop is the *adapter* loop, not the pop-only G3
  composer — that is good (the adapter loop already dispatches
  effects) — but nested windows (response to a response) have never
  been exercised cross-engine because no spell ever sat on the Rust
  stack long enough. New surface area.
- **S3 LANDED — VERIFY-FIRST OUTCOME: CLEAN-VERIFY NO-OP (this
  section's "high-probability Rust fix" hypothesis is CONTRADICTED
  by live source @ `9e884681`).** The hypothesized cast-time
  priority-reset fix was **already landed by S1** (`5803aea7`).
  The quoted anticipating docstring (*"a future stack-using cast
  slice will need to re-think when the reset fires"*) existed ONLY
  pre-S1 (`6b3e5565^`) — S1 deleted it and resolved the question;
  the post-S1 `state_ops_cast.rs:621-630` definitively states the
  cast-push reset matches Python. The cast-push
  `priority_player = active_player` (`:633`) is REDUNDANT (the
  adapter loop's `_reset_priority_to_active()` overwrites it with
  the byte-exact Python `_next_alive(active)` at `:511`/`:444`
  before any compare point), NOT divergent. The response-window
  machinery composes byte-equal (I46 instant-speed pass + the
  Python-faithful `legal.py:180-181` priority gate + LIFO + the
  post-resolution reset). NO `rust/src/` change; 3 verify-confirm
  pins (`tests_rust/test_priority.py::test_s3_*`) + status note +
  `G7_S3_VERIFY_FINDING.md`. 4-file core gate **1532 UNMOVED**.
  This is a valid S3 outcome (S2/B1 clean-verify class — no diff
  manufactured). S3 did NOT honest-stop-unmask a new divergence;
  S4 (`cast_creature_warp` stack-push + rider deferral) is the
  next owed slice, unaffected.

### Slice S4 — `cast_creature_warp` + permanent-spell riders (warp / impending / room / cast-from-X provenance)

- **Scope.** Apply the S1 stack-push shape to `cast_creature_warp`
  (`state_ops_cast.rs:621-743`) and carry the rider/provenance state
  Python stamps on the **card** at cast time (`cast_via_warp`,
  `cast_via_impending`, `cast_via_hand`, `spell_warped_this_turn`,
  warp life cost, `warp_exile_pending`, room-half) so it survives on
  the `StackItem`/card until **resolution** and is applied in
  `put_into_battlefield`-equivalent order. Today these are applied
  *inside the atomic primitive* (`state_ops_cast.rs:689-741`); they
  must move to resolve-time to match Python (`actions.py:1406-1464`
  stamps at cast, `put_into_battlefield` consumes at resolve).
- **Rust files touched.** `state_ops_cast.rs` (`cast_creature_warp`),
  `state_ops_resolve.rs` (rider consumption at resolve), possibly
  `state.rs` (StackItem/GameObject rider fields if not already
  present — `state_ops_cast.rs:736` already sets `warp_exile_pending`
  on the object so the field exists; verify the others). state.rs
  touch = serialized-lane escalation if needed.
- **Python SoT contract.** `_cast_spell:1393-1464` (rider selection +
  card stamps), `put_into_battlefield` (rider consumption / impending
  time-counter init).
- **Parity-verification.** `tests_rust/test_cast.py` warp pins
  (closure-flip to stack-push); cross-engine warp-creature + impending
  + room probes; rust_shadow on a warp-deck spec.
- **`.pyd`-touching:** YES (Rust). Single Rust lane.
- **Risk.** MEDIUM. Rider provenance moving from cast-time to
  resolve-time is the same class of deferral risk as S1's
  summoning-sickness, multiplied by the rider count. The
  `warp_exile_pending` end-step sweep
  (`state_ops_steps.rs::warp_exile_sweep_on_end_step`) keys off the
  bf object — must still see the right object post-resolution.

### Slice S5 — triggered-abilities-on-stack (in-scope confirmation)

> **S5 SPELL-STACK SOURCE-ZONE RE-HOMING — dedicated owner doc.** The
> post-auto-tap bake-in residual `hand_p0` divergence (Rust keeps the
> cast spell hand-resident while on the stack; Python removes it +
> `card.zone=Zone.STACK`) is scoped in
> **`docs/RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md`**. Verdict there:
> NOT cleanly sliceable — ONE irreducibly-atomic Rust core lane (S5a,
> Option β stack-object store) + thin post-core verify/cleanup
> (S5b/S5c); S5a is the hard prerequisite for S7 (CE5 removal). That
> doc is the single owner for the implementation lane; read it before
> S5a/S7.

- **Scope.** Largely **already present** — `resolve_top_of_stack`'s
  TriggeredAbility branch (`state_ops_resolve.rs:12028-12090`) +
  `push_triggered_ability` + the ETB/DIES/LEAVES drains already model
  triggered abilities going on the stack and resolving LIFO. The only
  G7-specific delta: with S1, a permanent spell's ETB triggers now
  fire at **resolution** (off `move_source_post_resolve` →
  `dispatch_event(Enters)` `:12201-12203`) instead of inside the
  atomic cast — verify the trigger push-ordering vs Python
  `put_into_battlefield` ETB-on-stack ordering, and that an opponent
  can respond to a *triggered ability* on the stack (nested window,
  shares S3's risk). Mostly verification; a fix only if ordering
  byte-shifts.
- **Rust files touched.** `state_ops_resolve.rs` only if an
  ETB-on-stack ordering fix is needed.
- **Python SoT contract.** `put_into_battlefield` ETB push +
  `resolve_top_of_stack` ability branch (`actions.py:2667-2705`).
- **Parity-verification.** Cross-engine ETB-trigger-on-stack +
  respond-to-trigger pins; rust_shadow on an ETB-heavy deck.
- **`.pyd`-touching:** YES if a fix lands. Single Rust lane.
- **Risk.** LOW (machinery present) — folds into S2/S3's risk surface.

### Slice S6 — the `rust_shadow` bake-in driver decision-loop (NO new masking; CE5 removal lives in Part 3)

- **Scope.** With S1–S5 landed, the role-swapped
  `ShadowCheckedRustAdapter` already drives Rust through the real
  stack/priority loop **for free**: `apply()` calls
  `self._rust.apply(decision)` → `RustGameStateAdapter.apply`
  (`rust_engine_adapter.py:626-632`) → `_run_priority_action` (the
  real effect-dispatching loop). A `cast_spell` decision now pushes a
  `StackItem`; the subsequent `PassPriority` decisions the random
  driver picks drive the pass-round that calls `resolve_top_of_stack`.
  So the bake-in's decision loop **needs no structural change** — the
  permanent spell resolves through the same loop the instant/sorcery
  path already uses. The ONLY change is **NOT adding** any
  post-`CastSpell` reconciliation (the G7-doc/§4 "port CE5 in"
  recommendation is rejected). `test_rust_shadow_bakein.py` pins drive
  the adapter exactly as `drive_shadow_game_to_terminal` does
  (`rust_shadow.py:589-680`) — uniform-random over
  `adapter.legal_decisions()`, apply until terminal; that contract is
  unchanged.
- **Verify-first caveat.** Confirm during impl that the random driver,
  after a `cast_spell`, actually *picks the PassPriority sequence* that
  drains the stack before the next STATE_EQ-bearing apply. It does:
  STATE_EQ runs *per apply*, and the apply right after a cast is
  whatever the random agent picks from the now-stack-bearing legal set
  (which includes PassPriority and instant-speed responses) — Python's
  state at that compare point ALSO has the spell on the stack (Python
  didn't resolve either; the priority loop is driven decision-by-
  decision through the adapter on both sides). **This is the crux of
  why the real fix makes the bake-in green WITHOUT CE5: once Rust
  stacks the spell, Rust and Python are BOTH "spell on stack, awaiting
  priority passes" at every per-apply compare point — they resolve in
  lockstep through the same decision sequence, so no harness drain is
  needed.** S6 is the verification that this holds at scale.
- **Rust files touched.** None. `src/` touched: none (the bake-in
  driver is unchanged; Part 3 removes CE5 from `cross_engine.py`).
- **Risk.** The load-bearing assumption above. If the Rust adapter's
  `_run_priority_action` resets priority or advances differently than
  Python's `priority_loop` *with a non-empty stack* (it was only ever
  validated with the synthetic deck that never stacks a spell), S3's
  nested-window risk resurfaces here at scale. This slice is the C4
  re-sweep gate (Part 3).

---

## Part 3 — THE CRITICAL PROOF PLAN (CE5 removal + CE5-free re-proof)

> **A "green WITH CE5" result is NOT acceptance evidence anymore. Only
> "green WITHOUT CE5" counts.** This is the real proof the flip needs.

### 3.1 Where CE5 is removed

CE5 = the cast-vs-resolve mirror in `cross_engine.step_both`
(`cross_engine.py:10367-10375`) gated by
`_RUST_AUTO_RESOLVE_ACTION_KINDS = {"cast_spell"}` (`:10247`), plus the
two drain helpers `resolve_top_of_stack_python` (`:10181-10238`) and
`resolve_top_of_stack_rust` (`:10250-10302`).

**Removal slice: S7 (after S1–S5 land and S6 verifies the bake-in is
green WITH CE5 a no-op).** S7 edits `cross_engine.py`:
empty `_RUST_AUTO_RESOLVE_ACTION_KINDS` to `frozenset()` (or delete
the CE5 block + the two helpers entirely once nothing references
them — verify `resolve_top_of_stack_rust` has no other caller; the
rust_shadow G7-fix path must NOT have grown a dependency on it).
**Order matters:** CE5 must be removed *only after* S1 makes Rust
stack the spell — removing CE5 before S1 would simply re-expose the
atomic divergence in `step_both` too. After S1, CE5's drain is already
a no-op for the resolved-in-lockstep path; S7 deletes the now-dead
reconciliation so the evidence base is regenerated through the honest
path.

> **Orchestrator-resync implication (flag, do not action).** S7 touches
> `cross_engine.py` — per the established residue cadence rule
> (`feedback_mtg_bot_merge_as_you_go`), touching `cross_engine.py`
> fires the residue cadence + a post-merge resync. S7 is a `src/`
> Python lane (no `.pyd`), but it invalidates the prior parity
> evidence base (3.2) so the resync is mandatory. The orchestrator
> owns the resync; the implementation lane HARD-STOPs after merge.

### 3.2 Re-proving the existing parity evidence base WITHOUT CE5

Every headline parity number was generated **with CE5 active** and is
**invalidated** by S7:

- The **307/475 byte-equal** headline + **PROBED 106** — these
  cross-engine Effect/bridge probes ran `step_both`, which drained
  both stacks after every `cast_spell` via CE5. They must be **re-run
  CE5-free** on the post-S7 commit. Expected: still byte-equal,
  because S1–S5 made Rust resolve through the real stack/priority loop
  the same way Python does — but this must be *demonstrated*, not
  assumed (new-code-is-right: a probe that now fails is a Rust bug to
  fix, not a reason to restore CE5).
- The **parity-smoke / trajectory-parity gate** (`scripts/bench_
  trajectory_parity.py` step_both path, the round-74/76 sweeps) —
  re-run CE5-free; the bench's `step_both` driver no longer drains, so
  the per-step compare now compares stack-bearing states on both sides
  (they should match decision-for-decision).
- The **4-file core gate (1532)** — `decision_source="python"`, does
  not exercise CE5 or Rust cast internals; UNMOVED. Confirm post-S7.

Re-proof artifact: a CE5-free re-run of the cross-engine probe suite +
the trajectory-parity sweep on the post-S7 commit, with a delta table
vs the pre-S7 (with-CE5) numbers. Any regression is a Rust fidelity
bug to close before the flip (it is exactly the kind of hole CE5 was
papering).

### 3.3 The fresh C4 `--driver rust_shadow` scaled re-sweep (the final flip-gate)

The terminal acceptance evidence: re-run the C4 scaled re-sweep
`PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/bench_
trajectory_parity.py --archetypes 0-59 --seeds 0,1,2,3,4 --max-turns
120 --driver rust_shadow --json-out c4_resweep_postG7.json --verbose`
on the post-S7 commit (the same 300-game round-76-class grid, real
17lands decks, role-swapped bake-in). **Acceptance = divergence-clean
(PASS on the games that reach terminal; the residual land-only
FAIL_TIMEOUTs are acceptable iff they are demonstrably the same
degenerate random-walk class, NOT new divergences — see
`C4_RESWEEP_EVIDENCE.md:79-87`).** This run has **no CE5** (removed in
S7) and **no CE5-equivalent in the bake-in** (rejected) — it is the
honest "green WITHOUT CE5" the flip is gated on. A new
`docs/C4_RESWEEP_EVIDENCE.md`-class evidence doc + committed
`c4_resweep_postG7.json` is the artifact; the GO/NO-GO decision itself
remains the USER's (orchestrator-sequenced, out of scope of any
implementation lane).

### 3.4 Explicit non-acceptance criteria

- A bake-in run that is green **only because CE5 (or any
  CE5-equivalent reconciliation in `rust_shadow.py`) is present** is
  **NOT** acceptance evidence. Per the user decision this path is
  closed.
- A `_DOCUMENTED_ACCEPTED_FIELDS` carve-out for `stack`/`battlefield`
  to "accept" the atomic axis is **NOT** acceptance evidence (it would
  be the same false-green; the frozenset must stay empty for the
  G7 axis).
- Acceptance requires: S1–S5 landed; CE5 removed (S7); the probe +
  trajectory base re-proven CE5-free; the C4 re-sweep divergence-clean
  CE5-free. All four.

---

## Part 4 — Honest magnitude / risk / interaction / sequencing

### 4.1 Effort estimate (honest — this materially resets the flip timeline)

| Slice | Nature | Likely cycles |
|---|---|---|
| S1 `cast_creature` → stack push | Rust rewrite (rewire, pattern exists in `cast_spell_noncreature`) | 1–2 |
| S2 resolver permanent-spell byte-equality | Verify + targeted fix | 1 |
| S3 priority/response windows + B1/C1 interaction | Verify + likely priority-reset fix; co-evolves with C1 S2/3 | 1–2 (gated on C1) |
| S4 `cast_creature_warp` + riders | Rust rewrite (rider deferral) | 1–2 |
| S5 triggers-on-stack | Verify (machinery present) | 0–1 |
| S6 bake-in loop (no new masking) | Verify at scale | 1 |
| S7 CE5 removal + CE5-free re-proof + C4 re-sweep | `cross_engine.py` edit + full evidence regeneration | 1–2 |
| **Total** | | **~6–11 cycles** |

This is a **multi-cycle build-out, not a single lane.** It materially
resets the flip timeline (the flip was gated on a clean C4 re-sweep;
that re-sweep cannot be clean until S1–S7 land and the evidence base
is regenerated CE5-free). The user has accepted this; it is not
minimized here. The mitigating reality (the verify-first payoff): it
is **rewire over present machinery**, not a ground-up stack build —
`cast_spell_noncreature` + the real adapter priority loop + the
permanent-aware `move_source_post_resolve` are the proof the pieces
exist and compose. A from-scratch stack model would have been
materially larger; this is closer to the lower end of the estimate
than the upper for S1/S2/S5.

### 4.2 Dependency / interaction with B1 (C1 Slices 2/3) — they co-evolve

S3 is **not independent of C1**. Stacking the permanent spell creates
the instant-speed response window where Rust's `legal_decisions` is
the authoritative source — exactly the surface C1 Slices 2/3
(target-satisfiability / additional-cost legal-set parity) must be
correct on. The C4 re-sweep already shows B1 as the secondary 22/300
LEGAL_SET_EQ blocker (`C4_RESWEEP_EVIDENCE.md:126-147`). **Recommended
coupling:** C1 Slices 2/3 land in parallel with / just before S3 so
S3's response-window LEGAL_SET_EQ does not trip on a known-open C1
axis. C1 stays its own lane (`RUST_LEGAL_DECISIONS_MANA_AWARENESS_
DESIGN.md`); this doc only flags the sequencing dependency. **The flip
GO requires BOTH G7 (this doc, S1–S7) AND B1 (C1 S2/3) closed** — they
are co-blockers, confirmed by the C4 re-sweep's two divergence shapes.

### 4.3 What existing parity evidence is invalidated / needs regeneration

- 307/475 byte-equal headline + PROBED 106 → re-prove CE5-free (3.2).
- parity-smoke / trajectory-parity (round-74/76) → re-prove CE5-free.
- The C4 re-sweep (0/300 @ `e87a6ebe`) → superseded by the post-S7
  CE5-free re-sweep (3.3).
- `tests_rust/test_cast.py` no-stack pins → closure-flip to stack-push
  pins (the G4/G5/G6 closure-flip pattern).
- 4-file 1532 gate → UNMOVED (verify, do not assume).

### 4.4 Biggest risks

1. **Nested response windows never exercised cross-engine (S3/S5/S6).**
   No spell ever sat on the Rust stack across a priority round before,
   so respond-to-spell and respond-to-trigger are brand-new
   cross-engine surface. The production loop is the *adapter* loop
   (`rust_engine_adapter.py:_run_priority_action`), which already
   dispatches effects (good) — but it was only validated on a
   synthetic deck that never stacks a spell. **Highest residual risk.**
   Mitigation: dedicated cross-engine counterspell/instant-response
   pins land in S3 before the C4 re-sweep.
2. **The pop-only G3 composer is a trap, not the path.**
   `complete_step_via_priority_round` (`state_ops_priority.rs:260-296`)
   does NOT dispatch effects (pop-only, `:284`). Any implementer who
   wires the permanent-spell resolution through the G3 composer instead
   of `resolve_top_of_stack` reintroduces the no-effect bug. The
   contract is: the resolution path is the **adapter loop calling
   `resolve_top_of_stack`**, period. Documented here so the
   implementation lane does not regress into the composer.
3. **Cast-time vs resolve-time provenance deferral (S1/S4).** Summoning
   sickness, ETB timestamps, warp/impending/room riders are applied
   inside the atomic primitive today; deferring them to resolution
   risks byte-shifts the synthetic deck won't catch but real decks
   will. New-code-is-right: fix Rust ordering to Python
   `put_into_battlefield`.
4. **Performance of real stack resolution in the bake-in sweep.** Every
   permanent cast now adds ≥1 priority round + a `resolve_top_of_stack`
   per game-spell vs the old single atomic mutation. The C4 grid is
   300 games; the prior atomic sweep was ~3.2 s/game
   (`C4_RESWEEP_EVIDENCE.md:46-53`). Real stack resolution will raise
   per-game wall (more decision steps to terminal). Likely still a
   single-run-feasible sweep, but flag a re-time before assuming the
   round-76 grid completes in ~16 min. Not a correctness risk; a
   throughput one.
5. **CE5 has no other consumer assumption (S7).** `resolve_top_of_
   stack_rust`/`_python` may have grown a non-CE5 caller; verify
   before deleting (vs just emptying the kinds frozenset).

### 4.5 Recommended slice ordering

`S1 → S2 → (C1 S2/3 in parallel) → S3 → S4 → S5 → S6 → S7`

S1 first (the load-bearing rewire; everything downstream verifies it).
S2 immediately after (resolver must be byte-equal before priority
windows mean anything). C1 S2/3 land in parallel so S3's response
window has a correct legal set. S3 (response windows — the new-surface
risk gate). S4 (riders — independent of S3, can interleave). S5 (mostly
verify). S6 (scale verify, green WITH CE5 a no-op). **S7 LAST** —
remove CE5, regenerate the entire evidence base CE5-free, run the
final C4 re-sweep. The flip GO is gated on S7's CE5-free C4 re-sweep
being divergence-clean **and** B1 (C1 S2/3) closed; the GO decision is
the USER's.

---

## Feasibility note on the USER decision (reported honestly; the decision itself is settled)

Nothing found contradicts or weakens the feasibility of "Rust must
implement the stack." On the contrary, the verify-first read makes the
decision **more** feasible than a worst-case reading of the brief
would suggest: this is **not** a deep architectural absence. Rust
already has a real stack, a full effect-dispatching resolver, a
permanent-aware post-resolve mover, an instant-speed legal emission,
and a real effect-dispatching priority loop in the production Rust-
driver adapter — and `cast_spell_noncreature` already demonstrates the
exact target shape (push a `StackItem`, don't resolve, let the loop
drain it) working end-to-end for instants/sorceries today. The G7 hole
is the single no-stack short-circuit on the permanent-spell cast
primitive(s) plus resolve-time provenance plumbing. It is a tractable
multi-cycle rewire, not a rebuild. The user's decision stands and is
the correct one; the only honest caveat is the timeline reset (Part
4.1) and the genuinely-new nested-response-window cross-engine surface
(Part 4.4 risk 1), both of which the user has accepted.
