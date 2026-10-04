# Effective card types and colors (CR 613 layers 4 and 5) — design note

Branch `feature/roto-karn-lattice` (off `feature/roto-instant-activations`
@ `aafcc5dc`), 2026-10-04. Written before the code change; the
"Status" section at the end records what landed.

## Why

Two roto cards keep Magnum Opus's bot-draft deck (Colorless Workshop
Prison) from being playable:

* **Mycosynth Lattice** — "All permanents are artifacts in addition to
  their other types." (layer 4) / "All cards that aren't on the
  battlefield, spells, and permanents are colorless." (layer 5) /
  "Players may spend mana as though it were mana of any color." (a rule
  modification, not a layer).
* **Karn, the Great Creator** — "Activated abilities of artifacts your
  opponents control can't be activated." / "+1: Until your next turn, up
  to one target noncreature artifact becomes an artifact creature with
  power and toughness each equal to its mana value." / "−2: You may reveal
  an artifact card you own from outside the game or choose a face-up
  artifact card you own in exile. Put that card into your hand."

Liquimetal Coating ("{T}: Target permanent becomes an artifact in addition
to its other types until end of turn.") and Unable to Scream (an Aura:
"Enchanted creature loses all abilities and is a Toy artifact creature
with base power and toughness 0/2 in addition to its other types." / "As
long as enchanted creature is face down, it can't be turned face up.") ride
on the same layers.

The engine has a layered registry (`GameState.continuous_effects`,
`ContinuousEffect` with `layer`/`timestamp`/`kind`) and effective reads for
subtypes (`game.effective_subtypes`, layers 3–4), colors of permanents and
spells (`game.effective_colors`, layer 5), abilities (layer 6), P/T (layer
7) and creature-ness (`game.is_creature_now`, a write-through cache of the
layer-4 `add_type "creature"` entries). What it lacks is a read for the
*other* card types: every "is this an artifact?" and every generic
"does it have card type T?" question reads `obj.printing` directly, and so
does every color question about a card outside the battlefield. Routing
only the reads a Lattice game happens to hit would be an approximation; the
fix is one effective path that every read goes through.

## Inventory (base `aafcc5dc`)

Counted with a tokenizer over `src/mtg_bot` (code only — comments and
docstrings excluded), outside `cards/parser/` (which builds printings and
legitimately reads printed characteristics), `parity/` (the cross-engine
harness reads printings to build the Rust registry) and
`cards/review_render.py` (an offline HTML report):

| Read | Sites | Notes |
|---|---:|---|
| `printing.is_artifact` | 69 | sacrifice / tap / target candidates, affinity and improvise counts, "artifact enters" and artifact-death bookkeeping, mana-spend contexts (`artifact_spell`, `artifact_activation`), cost reductions for artifact abilities, Aura "enchant artifact", sideboard / library / graveyard artifact-card filters |
| `printing.card_types` | 96 | generic predicates (`IsArtifact`, `IsLand`, `IsEnchantment`, `IsPlaneswalker`, `IsBattle`, `HasCardType` ×2), anthem scope `CARD_TYPE:<T>` (`StaticAbility.applies_to`), protection from a card type (`keyword_rules`), `CardFilter` / `HandCardFilter`, activation locks (`creature_statics_wg._card_types_now`), "shares a card type", equipment "+N/+N for each <type> you control", delirium / card-type counts (`effects/card_types.py`), copy-effect type additions (printing construction, not reads) |
| `printing.is_permanent` | 14 | cards in hand / graveyard / library (permanent cards) |
| `printing.is_enchantment` / `"Enchantment" in` / `is_planeswalker` / `"Planeswalker" in` / `"Battle" in` | 3 + 12 + ~10 | fixed non-artifact types |
| `printing.is_land` / `is_instant` / `is_sorcery` | 157 / 27 / 9 | fixed non-artifact types |
| `printing.is_creature` | 150 | creature-ness; see "Creature reads" below |
| `is_creature_now(...)` | 94 | the existing effective creature read |
| colors: `mana_cost.colors`, `color_indicator`, `face_colors`, and the "colorless" proxy `not mana_cost.colored` | 11 + 4 | `CardFilter.color` (library / hand / graveyard searches), `HandCardFilter` (Tannuk), "multicolored permanent" counts, imprinted-card colors, "share a color", "colors among permanents you control", the colorless-Eldrazi mana contexts, the green-creature library search |
| `effective_colors(...)` | 16 | already layered: protection, Painter's Servant, P5/P2 color checks, Veil of Summer |

Zones matter: Lattice's type change applies to **permanents** only
(battlefield), its color change to **every object** (library, hand,
graveyard, exile, stack, battlefield, command zone). Cards outside the game
(`Player.sideboard`, printings, not objects — CR 400.11) are unaffected.

## Design

### One read per characteristic

```python
# game.py
effective_card_types(state, obj) -> tuple[str, ...]   # CR 205.2a types after layer 4
has_card_type(state, obj, card_type) -> bool          # membership, fast path
is_artifact_now(state, obj) -> bool                   # has_card_type(..., "Artifact")
effective_colors(state, obj) -> frozenset[str]        # existing; now covers every zone
```

`effective_card_types`:

* **Not on the battlefield** (hand, library, graveyard, exile, stack,
  command): the printed `card_types`, except (a) a card exiled face down
  has no characteristics (CR 406.3 — returns `()`) [not adopted, see
  Status], (b) an object that is
  leaving the battlefield right now reports its last-known types (below).
  No effect in any pool changes the card types of a card outside the
  battlefield (Grist's "it's a 1/1 Insect creature in every other zone" is
  unclaimed), so this is exact.
* **On the battlefield**: the printed types — or just `Creature` for a
  face-down permanent (CR 708.2a; the engine already reports face-down
  permanents as 2/2 creatures without subtypes) — then layer 4:
  * creature-ness is `is_creature_now(obj)` (the existing cache, which
    covers `add_type "creature"` registry entries, Spacecraft stations,
    impending / enduring / reconfigure / bestow suppression, face-down);
  * every other added card type comes from layer-4 `add_type` registry
    entries targeting the object (Liquimetal Coating, Karn's +1, Unable to
    Scream's attach-time entries) and from **synthesized** entries of
    battlefield sources whose printing says "All permanents are
    <type>s in addition to their other types" (Mycosynth Lattice). The
    synthesis follows the Magus of the Moon / Dryad / Painter's Servant
    precedent in `effective_subtypes` / `effective_colors`: computed per
    read from the sources on the battlefield, so entering, leaving,
    control changes and copies (a Phyrexian Metamorph copying Lattice) need
    no lifecycle code. A phased-out source contributes nothing (CR
    702.26b).

Layer-4 type *additions* commute (each only adds), and no effect in any
pool *removes* the artifact type, so within the card-type part of layer 4
timestamps don't change the result; the creature part keeps its existing
cache semantics. Subtype effects that apply to "artifacts" (Ragost's
"Artifacts you control are Foods") are **dependent** on Lattice's type
change (CR 613.8a: applying Lattice changes what Ragost applies to), so
they must see the post-Lattice card types — `effective_subtypes` reads
`is_artifact_now` instead of `printing.is_artifact`, which applies the
type additions first regardless of timestamp. Nothing in the pools depends
the other way (a subtype change altering what a card-type effect applies
to).

**Invariant (enforced):** the only card types an effect may add are
`Artifact` and `Creature`. `effective_card_types` raises on an `add_type`
entry naming another type, and the parser grammar only produces those two.
Consequently the printed reads of `Land`, `Enchantment`, `Planeswalker`,
`Battle`, `Instant`, `Sorcery` and `Kindred` stay exact and are left as
they are (≈230 sites); a future card that adds one of those types must
first route that type's reads (the raise makes the omission loud instead
of silent). Jump Scare's dropped "becomes a Horror enchantment creature"
rider (Duskmourn; `cards/parser/effects.py`) is the one existing card this
blocks, and it is out of scope here.

### Colors (layer 5)

`effective_colors` keeps its timestamp walk (registry `set_colors` /
`add_colors`, synthesized Painter's Servant `add_colors`) and gains:

* base colors of a face-down permanent / face-down exiled card: none
  (CR 708.2a / 406.3) [the exiled half was not adopted, see Status];
* a synthesized `set_colors(∅)` entry from every battlefield source whose
  printing says "All cards that aren't on the battlefield, spells, and
  permanents are colorless." (Lattice), timestamp = the source's
  `etb_timestamp`. It applies to objects in every zone, exactly like
  Painter's Servant's entry, so Lattice + Painter's Servant resolves by
  timestamp (the later one wins), which is the printed interaction.

Every color read of a game object is routed through it — including the
`CardFilter` / `HandCardFilter` color checks on cards in hand, library and
graveyard (which take the object, not the printing, from now on), and the
"colorless Eldrazi" mana contexts (`not mana_cost.colored` was a printed
proxy that also mis-read devoid; Sowing Mycospawn is the cube's devoid
Eldrazi).

### Layer 6 and rule modifications

Strict layer order, as `effective_subtypes` already documents for Magus /
Dryad: a Lattice that has lost its abilities (layer 6 — an animated
Lattice under Unable to Scream or a Humility-style effect) still made every
permanent an artifact (layer 4) and every object colorless (layer 5) before
layer 6 ran. Its third ability is a rule modification, not a layered
effect, so it stops: `mana_spendable_as_any_color(state)` skips a source
with a `lose_all_abilities` entry (`_source_layer6_wiped`). Blood Moon's
basic-land-type rewrite (P5, layer 4 subtypes) and the land-types work
(`effective_land_produces`) are untouched: Lattice adds no land type and
removes nothing.

### Last-known information

Leaving the battlefield, an object stops being a permanent, so Lattice no
longer makes it an artifact — but "whenever an artifact is put into a
graveyard from the battlefield" and "whenever you sacrifice an artifact"
look back in time (CR 603.10a). `turn.move_off_battlefield` (and
`turn.sacrifice`, whose `IS_SACRIFICED` dispatch runs after the move)
snapshot the effective types into `GameObject.lki_card_types` before the
object moves (only when they differ from the printed ones) and clear the
snapshot once the departure triggers have been dispatched;
`effective_card_types` returns the snapshot for an object off the
battlefield while it is set. Registry entries targeting the departing
object already survive until after that dispatch (existing behavior), and
colors need no snapshot (Lattice's color change follows the card into
every zone).

### "Spend mana as though it were mana of any color"

`actions.mana_spendable_as_any_color(state)`: any battlefield source with
the rule (not wiped by layer 6). While it holds, cost payment and
affordability fold every colored pip (and the color part of hybrid pips,
already generic in the payment model) into generic **at payment time** —
the cost itself (mana value, Trinisphere's total, Phyrexian life options,
{S} snow pips) is unchanged. This is the same transformation the engine
already uses for "you may spend mana as though it were mana of any color to
cast that spell" (Robber of the Rich / Opposition Agent,
`exile_permission_cast_cost`), applied engine-wide and after Phyrexian
pips are settled so their 2-life option survives. Colorless mana can pay a
colored pip under Lattice (it is "mana", spent as though it were a color).
Spend restrictions (Mishra's Workshop's "only to cast artifact spells") are
a separate axis and still apply.

### Karn, the Great Creator

* **Static.** Clarion Conqueror / Null Rod / Stony Silence already lock
  "activated abilities of <types>" through
  `CardPrinting.locks_activated_abilities_of` and
  `creature_statics_wg.activation_locked` (consumed by
  `filter_activation_locks`, `actions._untapped_lands` — lands' mana
  abilities — the sac-for-mana sources and the activation itself). Karn
  adds a controller scope: `locks_opponents_activated_abilities_of`
  (types), checked by the same `activation_locked` against the lock
  source's controller; the lock's type test reads `has_card_type`, so
  under Lattice it reaches lands (their mana abilities ride automatic
  payment, which `_untapped_lands` filters) and planeswalkers (loyalty
  abilities). The planeswalker builder accepts the line through the same
  parameterized "Activated abilities of <types>[ your opponents control]
  can't be activated." recognizer. P1's named-card locks
  (`roto_restrictions.ActivationProhibition`) are a different shape
  (Pithing Needle) and are untouched.
* **+1.** `ApplyEffect(BecomeType(types_to_add=("artifact", "creature"),
  base_pt_from_mana_value=True), EndOfYourNextTurn())` targeting "up to one
  target noncreature artifact" (`IsArtifact() & ~IsCreature()`, both
  effective — so under Lattice a land or a planeswalker can be animated).
  The base P/T is the target's mana value on resolution (CR 608.2h).
  `EndOfYourNextTurn` already maps to `expires_at="controller_untap"`;
  what was missing is that `run_untap_step` didn't rebuild the
  `permanent_is_creature` cache after expiring those entries (only
  cleanup did). A single `sync_creature_type_cache(state, ids)` helper now
  runs after every registry removal that can drop an `add_type
  "creature"` entry (cleanup, untap, a source leaving the battlefield).
* **−2.** Options: each artifact card name in the controller's sideboard
  (P4's `Player.sideboard`, taken with `roto_turns.take_from_outside_the_
  game`) and each **face-up** artifact card the controller owns in exile,
  plus "nothing" ("You may"); one `choose_mode` decision. Face-up needs a
  marker: `GameObject.exiled_face_down`, set by every face-down exile site
  (Necropotence, Memory Jar, the "exile ... face down" effects) and cleared
  whenever a card leaves exile; `effective_card_types` /
  `effective_colors` treat such a card as characteristic-less [not
  adopted, see Status].

### Unable to Scream

The Lignify precedent (`apply_aura_static_grants_on_attach`): the Aura's
printing carries `attached_grants_lose_all_abilities`,
`attached_grants_subtype="Toy"`, `attached_sets_base_pt=(0, 2)` and a new
`attached_grants_card_types=("Artifact", "Creature")` (layer-4 `add_type`
entries, `expires_at=None`, dropped when the Aura leaves), plus
`attached_prevents_turning_face_up` — `legal` drops `TurnFaceUp` for a
face-down permanent with such an Aura attached.

### Search caching and hashing

No new cache. Every effective read is derived from state the search keys
already hash: battlefield objects (printing names, controllers,
`etb_timestamp`, tapped / face-down state) and the registry content
(`_canonical_continuous_effect` hashes kind, params and lifetime).
Synthesized entries are never stored. New per-object fields:
`exiled_face_down` (persistent while the card sits in exile — **not** in
the canonical-state / info-set hashes, like P4's `Player.sideboard`; search
code and the Rust fingerprint recipe are out of scope here) and
`lki_card_types` (transient: set and cleared inside one departure, never
visible between actions). Perf: the fast path of `has_card_type` is the
printed membership test plus, only for a type the printing lacks, one
registry scan (usually empty) and one battlefield scan for type-granting
sources — measured below.

### Rust

The roto-only cards (Lattice, Coating, Unable to Scream, Karn) aren't in
the Rust parity pool (the Rust deck loader rejects them). Every routed
read returns the printed value whenever no type- or color-changing effect
is present, so the Rust engine's mirrors of EoE effects see identical
behavior; the cross-engine parity suites are part of the gate.

### Creature reads

`is_creature_now` is the effective creature read and stays the one
`effective_card_types` uses. The 150 `printing.is_creature` sites split
into reads of cards in hand / library / graveyard / on the stack (exact)
and reads of permanents. The latter are the documented pre-existing gap
("Reconfigure / Bestow type changes are read through `game.is_creature_now`
only" in `docs/SEARCH_LIMITATIONS.md`); Karn's +1 animates through the same
cache as manlands and Haunted Screen. See the Status section for how that
gap was handled.

## Status

Landed on `feature/roto-karn-lattice` (2026-10-04). Shortcuts and the
remaining gaps are in `docs/SEARCH_LIMITATIONS.md`, "Card types and colors:
CR 613 layers 4 and 5".

**API** (`game.py`): `effective_card_types`, `has_card_type`,
`is_artifact_now`, `LAYER4_ADDABLE_CARD_TYPES` / `normalize_added_card_type`
(the invariant, raised from `GameState.add_continuous_effect`),
`snapshot_departure_card_types` / `clear_departure_card_types`
(`GameObject.lki_card_types`), `sync_creature_type_cache`; `effective_colors`
gained the face-down base and Lattice's synthesized entry. All four are
closure-free and pinned in `tests/test_layered_read_closure_free.py`.

**Routed reads** (tokenizer inventory, outside `cards/parser/`, `parity/`,
`cards/review_render.py`):

| Read | Base | Branch | What's left and why it is exact |
|---|---:|---:|---|
| `printing.is_artifact` | 69 | 5 | library / graveyard card filters on a bare printing (`search.py` ×2, `library_lookat.py`, `graveyard.py` ×2): card types off the battlefield are printed |
| `printing.card_types` | 96 | 68 | fixed card types the invariant keeps printed (Enchantment / Planeswalker / Battle), cards off the battlefield (graveyard counts, spells on the stack, `HasPrintedCardType`, `effects/card_types.py`), printing construction (copy effects), the printing properties themselves, imports of the `card_types` module, and `game.py`'s own reader |
| color reads of a game object (`mana_cost.colors` in filters and effects, the colorless-Eldrazi proxy `not mana_cost.colored`) | 12 | 0 | (the remaining `colors` tokens are effects' own `self.colors` parameters and the printing-level defaults inside the card filters) |
| new `is_artifact_now` / `has_card_type` / `effective_card_types` calls | 0 | 100 | |
| `effective_colors` calls | 16 | 29 | |
| card-filter call sites now matching the game object (`matches_card`) | 0 | 58 | |

**Deviations from the plan above:**

* A card exiled face down keeps its characteristics: `exiled_face_down` only
  answers Karn's "face-up artifact card in exile" (and who may look at it
  stays `publicly_known_to`'s job). Making it characteristic-less would have
  stripped, for example, a face-down exiled artifact of its artifact-ness in
  the cast-affordability probe that runs before it reaches the stack.
* Face-down status counts only on the battlefield (a manifested card that
  dies keeps a stale `face_down` flag in a public zone).
* Spell-cost increases ("<Filter> spells cost {N} more") take the spell's
  game object (`spell_cost_increase(..., card=)`, threaded through
  `apply_cost_reductions`), so a color filter reads the spell's effective
  colors.
* Activation-lock sources that lost their abilities stop locking (all of
  them, not only Karn).
* **Unable to Scream** is not claimed: it is also a Duskmourn printing, and
  the roto grammar is switched off for EoE-era printings. Its two lines
  parse and its engine support (`attached_grants_card_types`,
  `attached_prevents_turning_face_up`) is pinned by tests.
* Printed creature reads were left as they were (see "Creature reads"); the
  remaining gap is documented with its effect on Karn's +1.

**Behaviour unchanged without a type- or color-changing effect:** every
claimed printing of the `all`, `cube` and `eoe` pools has the same repr
(new default-valued fields aside) and the same claimed set as on
`aafcc5dc`; the roto pool gains exactly Mycosynth Lattice, Karn, the Great
Creator and Liquimetal Coating. `docs/CUBE_POOL_COVERAGE.md` regenerates
byte-identical. Seeded random-agent games produce identical full game logs
on base and branch: 60 on the 17lands EoE deck pool and 30 on the PowerLSV
cube deck pool.

**Performance** (`docs/BENCHMARKING_FINDINGS.md` §8E): profiled, the routed
reads cost ~3% over the base on EoE games. That needed one addition to the
design: `GameState.layered_statics_possible`, computed by
`simulate.setup_game` from the game's cards (decks and sideboards), lets
the reads skip the battlefield scan for Lattice-style sources when no card
of the game carries one (without it the profile was +6%). The existing tests changed only in their test doubles
(the fake objects gained `zone` / `lki_card_types`, a fake state its
registry and battlefield lists) and in one private helper's new `state`
parameter (`legal._spell_kinds_for_card`).

**Claimed cards:** Mycosynth Lattice, Karn, the Great Creator, Liquimetal
Coating (roto pool 842 → 845 of 865).
