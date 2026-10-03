# Vintage Roto coverage plan

Planning doc for claiming the rest of **Retireddevil's Vintage Roto 1.1** (`roto` pool) in the oracle parser. Written 2026-10-02 on `feature/cube-roto-coverage`; the numbers come from `scripts/measure_cube_coverage.py --pool roto` ([`ROTO_POOL_COVERAGE.md`](ROTO_POOL_COVERAGE.md)) and the live bot draft's `state.json` at 382 picks.

## Where things stand

- **578 of 865 pool cards claimed (66.8%)**: 860 Scryfall cards from the draft sheet plus the five basics. All 504 cards shared with the PowerLSV cube are claimed; 74 of the 361 roto-only cards are.
- **287 unclaimed**, of which **89 are already in a drafted pool** of the live draft (marked **(drafted)** below). Those come first inside every package. Drafted = every pick in `roto-bot-draft/state.json` mapped through the sheet list's `scryfall_name`, minus cards sent back by I've Made a Huge Mistake; the draft is still running, so re-derive this before prioritizing.
- 4 custom conspiracies on the sheet have no Scryfall record (Meddling Wizard, Quanitity Over Quality, I've Made a Huge Mistake, ANOTHER HEAD?!). They are listed in `data/cube_roto.meta.json` and the coverage doc, not faked into the pool; see P6.
- Every unclaimed card's failing oracle lines are in [`ROTO_POOL_COVERAGE.md`](ROTO_POOL_COVERAGE.md) (per-line probe, `mtg_bot.cards.unclaimed_lines`): 278 cards are `lines` (the listed lines are the whole blocker, confirmed by building the card without them) and 9 are `unconfirmed` (multi-face layouts, Conspiracy and Kindred types, snow cost: the card's frame may block too).
- Enchantments are probed with the `cube_enchantments.CUBE_ENCHANTMENT_NAMES` gate opened: a roto enchantment also needs its name opted in when its lines land. Eleven roto cards are EoE-era printings outside the cube (`is_eoe_only_printing` pins them off the cube-creature grammar); the pin changes no roto claim today.

## Package summary

Card lists are separated by semicolons (card names contain commas). Ordered by drafted-card count. Families are sized S (grammar on existing engine support, about a day), M (grammar plus a contained engine extension) or L (a new engine subsystem).

| # | Package | Cards | Drafted | Families (S/M/L) | New subsystems |
|---|---|---:|---:|---|---|
| 1 | P1 Stack & restrictions | 40 | 26 | 7 (1/5/1) | Name a card + named restrictions; Activation prohibitions; Counter triggered abilities |
| 2 | P2 Library, graveyard & hand | 70 | 20 | 9 (1/7/1) | Graveyard hate & exile-instead replacement; Draw replacement: dredge & Chains; Library-search hooks & tracking |
| 3 | P5 Board-state prison & layers | 65 | 16 | 8 (5/2/1) | Combat restrictions; Untap & upkeep prison |
| 4 | P3 Mana, costs & cast permissions | 45 | 10 | 9 (4/4/1) | Cast permissions & free casts; Snow |
| 5 | P4 Planeswalkers, copies, control & turns | 36 | 9 | 6 (0/2/4) | Wish (outside the game); Turn structure: draw skips, extra/ended turns; Borrowed activated abilities |
| 6 | P6 Keyword mechanics, face-changing & pregame | 31 | 8 | 7 (1/5/1) | Split second; Keyword mechanics (one-card keywords); Opening hand, pregame & conspiracies |

## Working rules for the parallel branches

- Branch each package off `feature/cube-roto-coverage` as `feature/roto-<package>` in its own worktree; commit as you go; don't merge to `main`.
- Put new grammar in the package's own parser module and new effects in its own `effects/generic/` module (names below), the way the cube buckets did (`creature_wg_lines.py`, `cube_glue_grammar.py`, ...). Shared dispatchers (`effects.py`, `triggers.py`, `statics.py`, builders) get one import-and-call hook per package; that keeps conflicts to trivially mergeable appends.
- Known shared hot spots: `cards/base.py` (`CardPrinting` fields), `cube_enchantments.CUBE_ENCHANTMENT_NAMES` (keep it alphabetical; on conflict take the union), `legal.py` (P1 prohibitions, P3 permissions, P6 split second), `turn.py` (P4 draw/extra turns, P5 untap/upkeep), `game.py` (P2 zone/draw replacements, P4 sideboard, P5 layers), `land_lines.py` (P2, P3, P5), `docs/SEARCH_LIMITATIONS.md` (everyone).
- Roto-only cards were not in the default `all` pool while the packages ran (they are since 2026-10-03). Test them through `tests/_roto_helpers.py` (`roto_card`, `printing`) or `OracleParserCardSource(pool="roto")`.
- Oracle-text fidelity: no no-op recognizers, no partial claims, no name-keyed literals unless the parser CLAUDE.md's single-card exception applies. If a clause isn't modeled, the card stays unclaimed. Every deliberate shortcut gets a `docs/SEARCH_LIMITATIONS.md` entry.
- Before each commit: refresh `docs/ROTO_POOL_COVERAGE.md` (`scripts/measure_cube_coverage.py --pool roto`; `tests/test_pool_coverage.py::test_committed_roto_doc_is_fresh` enforces it). On a merge conflict in that doc, re-run the script instead of hand-merging. `docs/CUBE_POOL_COVERAGE.md` must stay byte-identical (cube claims must not move).

## Packages

### 1. P1: Stack & restrictions (40 cards, 26 drafted)

Model the effects that police the stack: spell and ability taxes (Sphere/Thorn/Defense Grid/Trinisphere, Aven Interrupter), casting and activation prohibitions (Null Rod, Stony Silence, Silence, Orim's Chant, Ranger-Captain, High Noon, Lavinia), the as-enters 'choose a card name' family (Pithing Needle, Revoker, Disruptor Flute, Meddling Mage), counterspell variants (MV-N counters, type-restricted counters that hand the controller a Bird, Spellstutter's X, Glen Elendra, Venser's spell-or-permanent bounce, Long Goodbye's uncounterability line, Mindbreak Trap) and cast triggers (Chalice, Eidolon, Vexing Bauble, Mystic Remora's cumulative upkeep + 'unless that player pays', Esper Sentinel, Nether Void, Chancellor of the Annex -- its opening-hand reveal uses the same hook P6 builds; coordinate or add the minimal hook in `opening_hand.py`). Countering *triggered abilities* (Consign to Memory, Strict Proctor) is the one L item: triggered abilities must become targetable/counterable stack objects. Start from `creature_statics_wg.spell_cost_increase` / `opponents_cant_cast_spells_during_your_turn` and the existing counterspell effects; the name choice must be a real decision the search enumerates over (names in the opponent's known card pool), not a fixed pick.

- **New modules:** `cards/parser/roto_stack.py`, `effects/generic/roto_stack.py`, `roto_restrictions.py` (engine statics, modeled on `creature_statics_wg.py`)
- **Parser files:** `counter_phrases.py`, `cost_reduction.py` (tax table), hooks in `effects.py` / `triggers.py` / `statics.py`; `cube_enchantments.py` name gate (Mystic Remora, Nether Void, High Noon)
- **Engine files:** `legal.py` (can't-cast / can't-activate), `creature_statics_wg.py` (`spell_cost_increase`), `effects/generic/counterspells.py`, `effects/generic/stack_control.py`, `actions.py` (as-enters name choice, countering triggers), `game.py` (per-turn spell counts), `cards/base.py` (fields)

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F05 Counterspell variants | M | grammar on existing support | **Glen Elendra Guardian** (drafted); **Long Goodbye** (drafted); **Mental Misstep** (drafted); **Mindbreak Trap** (drafted); **Mystical Dispute** (drafted); **Spell Snare** (drafted); **Spellstutter Sprite** (drafted); **Strix Serenade** (drafted); **Stubborn Denial** (drafted); **Swan Song** (drafted); **Venser, Shaper Savant** (drafted) |
| F07 Cast triggers: unless-pays, counters, spell counts | M | partial: 'unless pays' exists for some spells; needs it on triggers, first-spell-each-turn, spells-cast-this-turn count, no-mana-spent check | **Chalice of the Void** (drafted); **Eidolon of the Great Revel** (drafted); **Esper Sentinel** (drafted); **Mystic Remora** (drafted); **Vexing Bauble** (drafted); Aetherflux Reservoir; Chancellor of the Annex; Harsh Mentor; Jeskai Ascendancy; Nether Void; The Queen of Dale |
| F01 Cost taxes | M | partial: extend spell_cost_increases (Thalia-style) with turn condition, zone-of-cast filter and Trinisphere's minimum-cost floor | **Defense Grid** (drafted); **Sphere of Resistance** (drafted); **Thorn of Amethyst** (drafted); **Trinisphere** (drafted); Aven Interrupter |
| F02 Name a card + named restrictions | M | NEW: as-enters 'choose a card name' choice stored on the permanent; can't-cast / can't-activate / tax keyed on it (search must enumerate legal names) | **Phyrexian Revoker** (drafted); **Pithing Needle** (drafted); Disruptor Flute; Meddling Mage |
| F03 Activation prohibitions | S | NEW (small): static 'activated abilities of <filter> can't be activated' consulted by legal.py | **Null Rod** (drafted); **Stony Silence** (drafted) |
| F04 Can't-cast restrictions | M | partial: opponents_cant_cast exists; needs UEOT player-scoped emblems, one-spell-per-turn, MV-vs-lands cap | **Orim's Chant** (drafted); High Noon; Lavinia, Azorius Renegade; Ranger-Captain of Eos; Silence |
| F06 Counter triggered abilities | L | NEW: triggered abilities as counterable stack objects (Consign) + intercepting ETB-caused triggers (Strict Proctor) | **Consign to Memory** (drafted); Strict Proctor |

### 2. P2: Library, graveyard & hand (70 cards, 20 drafted)

Everything that moves cards between library, graveyard and hand. Most of it is grammar on existing search / mill / reanimate / discard effects: tutor filters (power/toughness/MV bounds, 'MV equal to 1 plus the sacrificed', 'total MV 6 or less', to-graveyard, discard-at-random, opponent-chooses for Gifts), look-at-top-N and reveal-until loops, recursion and graveyard-zone triggers (Narcomoeba, Bridge from Below, Gaea's Blessing, 'a card left your graveyard this turn'), hand disruption (Cabal Therapy's named discard and flashback by sacrifice, Freebooter's exile-until, Clique, Kroxa, Pox). Three pieces are new engine: the exile-instead replacement on graveyard-bound zone moves (Rest in Peace, Leyline of the Void, Sanctifier en-Vec), a draw replacement offered on every draw (Dredge; Chains of Mephistopheles), and library-search hooks (Opposition Agent controlling the searcher, Wan Shi Tong's trigger, Archive Trap's 'searched this turn'). Leyline's opening-hand clause should reuse P6's opening-hand hook if it lands first; otherwise add the hook here and tell P6.

- **New modules:** `cards/parser/roto_zones.py`, `effects/generic/roto_zones.py`
- **Parser files:** hooks in `effects.py` / `triggers.py`; `card_flow_grammar.py`, `land_lines.py` (Fabled Passage, Ghost Quarter, Bojuka Bog), `spell_cost_lines.py` (Archive Trap only); `cube_enchantments.py` name gate (Rest in Peace, Leyline of the Void, Survival of the Fittest, Recurring Nightmare, Bridge from Below, Chains of Mephistopheles)
- **Engine files:** `effects/generic/search.py`, `library_lookat.py`, `graveyard.py`, `reanimation.py`, `discard.py`, `draw_mill.py`, `cheat_into_play.py`; `game.py` (exile-instead zone-move replacement, draw replacement, searched-this-turn tracking), `actions.py` (draw path)

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F10 Tutors (search variants) | M | grammar on existing support | **Beseech the Mirror** (drafted); **Fabled Passage** (drafted); **Gamble** (drafted); **Ghost Quarter** (drafted); **Imperial Recruiter** (drafted); **Protean Hulk** (drafted); **Unmarked Grave** (drafted); Academy Rector; Arena Rector; Birthing Pod; Doomsday; Finale of Devastation; Gifts Ungiven; Oswald Fiddlebender; Recruiter of the Guard; Scapeshift; Survival of the Fittest |
| F16 Hand disruption & symmetric attrition | M | partial: name-a-card discard exists in card_flow; reveal/choose-from-hand variants | **Cabal Therapy** (drafted); **Kitesail Freebooter** (drafted); **Smallpox** (drafted); **Vendilion Clique** (drafted); Cabal Therapist; Dread Fugue; Dreams of Steel and Oil; Kroxa, Titan of Death's Hunger; Pox; Sire of Insanity |
| F12 Graveyard hate & exile-instead replacement | M | NEW: 'would be put into a graveyard -> exile instead' replacement on zone moves (with color/owner filters) | **Bojuka Bog** (drafted); **Leyline of the Void** (drafted); **Rest in Peace** (drafted); Sanctifier en-Vec |
| F13 Recursion & reanimation | M | grammar on existing support | **Recurring Nightmare** (drafted); **Takenuma, Abandoned Mire** (drafted); Cling to Dust; Deathrite Shaman; Dread Return; Memory's Journey; Noxious Revival; Persist; Pre-War Formalwear; Reveillark; Sevinne's Reclamation |
| F15 Draw replacement: dredge & Chains | M | NEW: replacement offered on every draw (dredge N; Chains' discard-or-mill) | **Chains of Mephistopheles** (drafted); **Stinkweed Imp** (drafted); Golgari Grave-Troll; Life from the Loam |
| F11 Look at / reveal-until / library order | M | grammar on existing support | **Goblin Guide** (drafted); Collected Company; Deem Inferior; Flow State; Helm of Obedience; Hermit Druid; Scroll Rack; Tainted Pact; Tasha's Hideous Laughter; Triumph of Saint Katherine; Ulamog, the Ceaseless Hunger; Winota, Joiner of Forces |
| F18 Library-search hooks & tracking | L | NEW: 'searched their library this turn' tracking, search triggers, and Opposition Agent's control of the searcher | **Opposition Agent** (drafted); Archive Trap; Wan Shi Tong, Librarian |
| F14 Graveyard-zone triggers & tracking | M | partial: triggers on cards in graveyard / from library to graveyard / 'a card left your graveyard this turn' | Bridge from Below; Gaea's Blessing; Gau, Feral Youth; Kishla Skimmer; Narcomoeba; Slogurk, the Overslime |
| F17 Put permanents from hand (each player) | S | grammar on existing support | Eureka; Show and Tell; Stronghold Gambit |

### 3. P5: Board-state prison & layers (65 cards, 16 drafted)

Permanents that change the board's rules: combat restrictions (Moat, Ensnaring Bridge, can't-block, 'creature it's blocking'), untap and upkeep prison (Winter Orb, Back to Basics, Tangle Wire's Fading on an artifact, Smokestack, the Tabernacle's granted upkeep tax, Drop of Honey), type and ability changes across layers 4-6 (Blood Moon, Urborg, Yavimaya, Mycosynth Lattice, Dress Down, Liquimetal Coating, Unable to Scream, Heliod's devotion clause, Scale Up, Tarmogoyf Nest's Kindred Aura), static and dynamic P/T, tap/untap effects and new cost atoms ('tap an untapped creature you control', 'put a -1/-1 counter on this', 'sacrifice a permanent'), mass removal keyed on mana value or counters (Pernicious Deed, Engineered Explosives, Filigree Sylex, Aether Vial's put-onto-battlefield, Temporary Lockdown), the charm/command modal spells, and a tail of one-off effects. Most enchantments here also need their name added to `cube_enchantments.CUBE_ENCHANTMENT_NAMES`.

- **New modules:** `cards/parser/roto_board.py`, `effects/generic/roto_board.py`
- **Parser files:** `statics.py`, `artifact_builder.py` / `artifact_effects.py` (Fading on artifacts, Smokestack, Winter Orb), `modal_spells.py` (charms), `land_lines.py` (Urborg, Yavimaya, Minamo, Pendelhaven, Mistrise Village, Talon Gates); `cube_enchantments.py` name gate (Moat, Back to Basics, Blood Moon, Dress Down, Opposition, Earthcraft, Pernicious Deed, Seal of Cleansing, Temporary Lockdown, Aang's Iceberg, Drop of Honey, Unable to Scream, Tarmogoyf Nest)
- **Engine files:** `combat.py` (attack/block legality), `turn.py` (untap-step limits, upkeep triggers), `game.py` (layer 4-6 characteristics: land types, colors, lost abilities), `effects/generic/become_type.py`, `mass_effects.py`, `tap.py`, `pump.py`, `multi_modal.py`

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F47 Misc. one-off effects | M | partial: Role tokens (Monstrous Rage) and Discover (Zoyowa's Justice) are new keyword actions | **Argentum Masticore** (drafted); **Paradoxical Outcome** (drafted); **Price of Progress** (drafted); **Veil of Summer** (drafted); Mistrise Village; Monstrous Rage; Omnath, Locus of Creation; Shrieking Drake; Talon Gates of Madara; Thief of Existence; Vines of Vastwood; Zoyowa's Justice |
| F41 Untap & upkeep prison | M | NEW: untap-step limits and per-player upkeep sacrifice/tap/tax triggers | **Smokestack** (drafted); **Tangle Wire** (drafted); **The Tabernacle at Pendrell Vale** (drafted); Back to Basics; Drop of Honey; Winter Orb |
| F40 Combat restrictions | S | NEW (small): static attack/block legality filters | **Carrion Feeder** (drafted); **Ensnaring Bridge** (drafted); Moat; Tinder Wall |
| F42 Type & ability changing (layers 4-6) | L | partial: lose-all-abilities exists; land-type setting (Blood Moon) / adding (Urborg), global type/color changes | **Mycosynth Lattice** (drafted); **Urborg, Tomb of Yawgmoth** (drafted); Blood Moon; Dress Down; Heliod, Sun-Crowned; Liquimetal Coating; Scale Up; Tarmogoyf Nest; Unable to Scream; Yavimaya, Cradle of Growth |
| F46 Modal spells (charms & commands) | S | grammar on existing support | **Cryptic Command** (drafted); **Kozilek's Command** (drafted); Boros Charm; Emerald Charm; Prismari Charm |
| F43 Static & dynamic P/T | S | grammar on existing support | **Nethergoyf** (drafted); Berserk; Craterhoof Behemoth; Elvish Reclaimer; Embiggen; Kaheera, the Orphanguard; Knight of the Reliquary; Might of Old Krosa |
| F44 Tap/untap effects & cost atoms | S | grammar on existing support | **Umezawa's Jitte** (drafted); Claws of Gix; Deceiver Exarch; Devoted Druid; Earthcraft; Hawkeye's Bow; Ichorclaw Myr; Lavaspur Boots; Minamo, School at Water's Edge; Opposition; Pendelhaven; Turnabout |
| F45 Mass removal & MV/counter-keyed permanents | S | grammar on existing support | **Engineered Explosives** (drafted); Aang's Iceberg; Aether Vial; Pernicious Deed; Seal of Cleansing; Temporary Lockdown; Terastodon; The Filigree Sylex |

### 4. P3: Mana, costs & cast permissions (45 cards, 10 drafted)

Mana production and the ways to pay (or not pay) for spells. Rituals and dynamic mana (Rite of Flame, Burnt Offering, Culling Ritual, Jeska's Will -- its commander clause is honestly false in this format -- Carpet of Flowers, Vivi, Spire of Industry, the Simic karoo), mana triggers and spend restrictions (High Tide, Kinnan, Utopia Sprawl, Forbidden Orchard, Jegantha, Mightstone, Cavern of Souls), alternative costs (Gush, Fireblast, Force of Despair, Invigorate), cost modifiers and additional costs (Artist's Talent, Grim Reaper's Sprint, Rottenmouth Viper, Firestorm, Phyrexian Dreadnought), mana-spent conditions (Wistfulness, Together as One, Opus), energy, suspend (Lotus Bloom, Greater Gargadon) and extra land plays. Two subsystems are new: static cast permissions and free-cast windows (Omniscience, Dream Halls, Aluren, Mind's Desire, Hex Magic, Mystic Forge, Isochron Scepter, Dreadhorde Arcanist), and snow: the Snow supertype alone stops the land builder (Dark Depths), and `{S}` in a cost is declined by `parse_mana_cost`, so Arcum's Astrolabe stays unclaimed until snow sources exist.

- **New modules:** `cards/parser/roto_mana.py`, `effects/generic/roto_mana.py`
- **Parser files:** `spell_cost_lines.py`, `cost_reduction.py`, `activated.py` (mana abilities), `land_lines.py` (Spire of Industry, Simic Growth Chamber, Cavern of Souls, Dark Depths), `cards/base.py:parse_mana_cost` (`{S}`); `cube_enchantments.py` name gate (Omniscience, Dream Halls, Aluren, Carpet of Flowers, Utopia Sprawl, Exploration, Grim Reaper's Sprint, Chthonian Nightmare)
- **Engine files:** `effects/generic/mana.py`, `actions.py` (payment, restricted mana, snow sources), `legal.py` (cast permissions from hand / library / exile), `effects/generic/graveyard_casting.py`, `cast_conditionals.py`, `cards/spell_costs.py`

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F20 Rituals & dynamic mana | M | grammar on existing support | **Jeska's Will** (drafted); **Rite of Flame** (drafted); **Spire of Industry** (drafted); Burnt Offering; Carpet of Flowers; Channel; Culling Ritual; Simic Growth Chamber; Vivi Ornitier |
| F21 Mana triggers & restricted mana | M | partial: 'tapped for mana' triggers + spend restrictions on pool mana | **Cavern of Souls** (drafted); **The Mightstone and Weakstone** (drafted); Forbidden Orchard; High Tide; Jegantha, the Wellspring; Kinnan, Bonder Prodigy; Utopia Sprawl |
| F23 Cast permissions & free casts | L | NEW: static cast permissions (Omniscience / Dream Halls / Aluren) + cast-from-library / exile-and-play windows | **Dreadhorde Arcanist** (drafted); **Mystic Forge** (drafted); Aluren; Dream Halls; Hex Magic; Isochron Scepter; Mind's Desire; Omniscience |
| F22 Alternative costs | S | grammar on existing support | **Force of Despair** (drafted); Fireblast; Gush; Invigorate |
| F27 Suspend & extra land plays | S | grammar on existing support | **Lotus Bloom** (drafted); Azusa, Lost but Seeking; Exploration; Greater Gargadon |
| F28 Snow | M | NEW: the Snow supertype (it alone blocks the land builder: Dark Depths, whose three ice-counter lines also fail) + snow mana sources and the {S} cost symbol (parse_mana_cost raises; Arcum's Astrolabe is declined) | **Dark Depths** (drafted); Arcum's Astrolabe |
| F24 Mana-spent conditions | S | partial: track mana spent (amount / colors / which symbols) on the spell | Exhibition Tidecaller; Together as One; Wistfulness |
| F25 Cost modifiers & additional costs | M | grammar on existing support | Artist's Talent; Firestorm; Grim Reaper's Sprint; Phyrexian Dreadnought; Rottenmouth Viper |
| F26 Energy | S | grammar on existing support | Amped Raptor; Chthonian Nightmare; Wrath of the Skies |

### 5. P4: Planeswalkers, copies, control & turns (36 cards, 9 drafted)

The 14 unclaimed planeswalkers plus the machinery several of them share with other cards: clones and copies (Phantasmal Image's granted sacrifice trigger, Mockingbird's mana-spent cap, Shuri's artifact copy, Sin's random token copy, Chain of Vapor and Return the Favor copying spells/abilities), control change and flicker (Gilded Drake, Zealous Conscripts, Bilbo's adventure, Commandeer taking control of a *spell*, Felidar Guardian, Ephemerate), turn structure (Necropotence / Yawgmoth's Bargain skip the draw step, Sundial and Day's Undoing end the turn, Final Fortune, Emrakul controlling the opponent's turn) and borrowed activated abilities (Scheming Fence, Agatha's Soul Cauldron). Wish (Burning Wish, Karn's -2) needs a sideboard zone the engine doesn't have: in roto the sideboard is the drafter's unused picks, so agree the semantics with the user before building it. Jace and Nissa also need Compleated.

- **New modules:** `cards/parser/roto_walkers.py`, `effects/generic/roto_walkers.py`
- **Parser files:** `planeswalker_builder.py`, `effects_ext.py` (emblems), the clone recognizer in `cube_creatures_ub.py`; `cube_enchantments.py` name gate (Necropotence, Yawgmoth's Bargain)
- **Engine files:** `effects/generic/cube_walkers.py`, `spell_copies.py`, `control.py`, `emblem.py`; `turn.py` (skip draw, end the turn, extra turns, controlled turns), `game.py` + `decks.py` (a sideboard zone for Wish / Karn)

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F30 Planeswalker loyalty lines | L | partial: per-walker effects; Karn's -2 needs Wish (F31); Jace/Nissa need Compleated | **Jace, the Perfected Mind** (drafted); **Karn, the Great Creator** (drafted); **Liliana of the Veil** (drafted); **Ugin, the Spirit Dragon** (drafted); Chandra, Hope's Beacon; Dihada, Binder of Wills; Gideon of the Trials; Grist, the Hunger Tide; Kaya, Intangible Slayer; Kiora, Behemoth Beckoner; Nicol Bolas, God-Pharaoh; Nissa, Ascended Animist; Professor Dellian Fel; Saheeli Rai |
| F34 Turn structure: draw skips, extra/ended turns | L | NEW: skip-draw-step static, end-the-turn, extra turn with a delayed loss, controlling another player's turn (Emrakul) | **Necropotence** (drafted); **Yawgmoth's Bargain** (drafted); Day's Undoing; Emrakul, the Promised End; Enter the Infinite; Final Fortune; Sundial of the Infinite |
| F31 Wish (outside the game) | M | NEW: per-player sideboard zone (decks carry one) + 'from outside the game' fetch | **Burning Wish** (drafted) |
| F32 Clones & copies | L | partial: copy effects exist; enter-as-copy with exceptions, copy spells/abilities, random token copies | **Phantasmal Image** (drafted); Chain of Vapor; Mockingbird; Return the Favor; Shuri, Wakandan Inventor; Sin, Spira's Punishment |
| F33 Control change & flicker | M | partial: exchange-control exists (cube glue); spell-control (Commandeer) is new | **Gilded Drake** (drafted); Bilbo, Luckwearer // Burglar's Plot; Commandeer; Ephemerate; Felidar Guardian; Zealous Conscripts |
| F35 Borrowed activated abilities | L | NEW: a permanent gaining all activated abilities of another object/card | Agatha's Soul Cauldron; Scheming Fence |

### 6. P6: Keyword mechanics, face-changing & pregame (31 cards, 8 drafted)

Keyword mechanics and pregame rules. Split second (Angel's Grace, Legolas's Quick Reflexes) restricts what players may do while the spell is on the stack. Damage prevention / redirection (Maze of Ith, Cephalid Illusionist, Nomads en-Kor, Black Panther, Impractical Joke's 'can't be prevented') and Vizier of Remedies' counter replacement; becomes-the-target triggers; face-down / transform / flip (Morph on Aphetto Alchemist, cloak on Cryptic Coat, Delver, Erayo's flip layout, the Hidetsugu saga); one-card keywords (Echo, Cipher, Transmute, Cleave, Spree modes, Plot on a creature, Swampwalk, cycling paid in life, Start your engines!/speed, Regenerate); designations (monarch, the Ring tempts you, venture); and the opening-hand / conspiracy pregame (Chancellor of the Tangle, Serum Powder, Power Play, Advantageous Proclamation). The four custom conspiracies have no Scryfall record and sit outside the pool; only Meddling Wizard (opponent reveals their hand after mulligans) affects a game, and modeling it needs the user's go-ahead on a hand-authored record.

- **New modules:** `cards/parser/roto_keywords.py`, `effects/generic/roto_keywords.py`
- **Parser files:** `keywords.py`, `printing_keywords.py`, `keyword_actions.py`, `dfc_builder.py` / `layout_builder.py` (flip), `opening_hand_lines.py`, `type_line.py` (Conspiracy)
- **Engine files:** priority / stack in `actions.py` (split second), `designations.py` (the Ring), `opening_hand.py`, `simulate.py` (starting player), `decks.py` (deck-size rules), `effects/generic/keyword_actions.py`, `effects/generic/damage.py` (prevention, redirection), `effects/generic/layout_face_effects.py` (transform / flip)

| Family | Size | Engine work | Cards |
|---|---|---|---|
| F51 Damage prevention, redirection & replacement | M | partial: prevention exists; redirection, 'can't be prevented', +N damage, -1/-1-counter replacement | **Cephalid Illusionist** (drafted); **Maze of Ith** (drafted); **Nomads en-Kor** (drafted); Impractical Joke; King T'Challa // Black Panther, Hope Enduring; Vizier of Remedies |
| F54 Keyword mechanics (one-card keywords) | L | NEW per keyword: Echo, Cipher, Transmute (tutor exists), Cleave, Plot on creatures, Swampwalk + Cycling with a life cost, Start your engines!/speed; Regenerate and Spree need only grammar (the regeneration shield and Spree casting exist; Requisition Raid's '+ {1} --' modes don't parse) | **Muddle the Mixture** (drafted); **Tolaria West** (drafted); Blight Mamba; Hidden Strings; Karmic Guide; Momentum Breaker; Requisition Raid; Slickshot Show-Off; Street Wraith |
| F56 Opening hand, pregame & conspiracies | M | NEW: opening-hand actions (reveal / put onto battlefield / mulligan exile) + conspiracy command zone (starting player, deck-size rules) | **Advantageous Proclamation** (drafted); **Power Play** (drafted); Chancellor of the Tangle; Serum Powder |
| F53 Face-down, transform & flip | M | partial: morph/cloak exist; flip layout and Delver/Erayo transform conditions | **Delver of Secrets // Insectile Aberration** (drafted); Aphetto Alchemist; Cryptic Coat; Erayo, Soratami Ascendant // Erayo's Essence; Hidetsugu Consumes All // Vessel of the All-Consuming |
| F50 Split second | M | NEW: while a split-second spell is on the stack, only mana abilities / special actions | Angel's Grace; Legolas's Quick Reflexes |
| F52 Becomes-the-target triggers | S | grammar on existing support | Loki, God of Mischief; Venerated Rotpriest |
| F55 Designations & keyword actions | M | partial: monarch/venture exist; the Ring tempts you is NEW | Acererak the Archlich; Emberwilde Captain; Samwise the Stouthearted |

## Drafted unclaimed cards

As of 382 picks, 89 unclaimed cards are in drafted pools:

- **P1:** Chalice of the Void (F07); Consign to Memory (F06); Defense Grid (F01); Eidolon of the Great Revel (F07); Esper Sentinel (F07); Glen Elendra Guardian (F05); Long Goodbye (F05); Mental Misstep (F05); Mindbreak Trap (F05); Mystic Remora (F07); Mystical Dispute (F05); Null Rod (F03); Orim's Chant (F04); Phyrexian Revoker (F02); Pithing Needle (F02); Spell Snare (F05); Spellstutter Sprite (F05); Sphere of Resistance (F01); Stony Silence (F03); Strix Serenade (F05); Stubborn Denial (F05); Swan Song (F05); Thorn of Amethyst (F01); Trinisphere (F01); Venser, Shaper Savant (F05); Vexing Bauble (F07)
- **P2:** Beseech the Mirror (F10); Bojuka Bog (F12); Cabal Therapy (F16); Chains of Mephistopheles (F15); Fabled Passage (F10); Gamble (F10); Ghost Quarter (F10); Goblin Guide (F11); Imperial Recruiter (F10); Kitesail Freebooter (F16); Leyline of the Void (F12); Opposition Agent (F18); Protean Hulk (F10); Recurring Nightmare (F13); Rest in Peace (F12); Smallpox (F16); Stinkweed Imp (F15); Takenuma, Abandoned Mire (F13); Unmarked Grave (F10); Vendilion Clique (F16)
- **P5:** Argentum Masticore (F47); Carrion Feeder (F40); Cryptic Command (F46); Engineered Explosives (F45); Ensnaring Bridge (F40); Kozilek's Command (F46); Mycosynth Lattice (F42); Nethergoyf (F43); Paradoxical Outcome (F47); Price of Progress (F47); Smokestack (F41); Tangle Wire (F41); The Tabernacle at Pendrell Vale (F41); Umezawa's Jitte (F44); Urborg, Tomb of Yawgmoth (F42); Veil of Summer (F47)
- **P3:** Cavern of Souls (F21); Dark Depths (F28); Dreadhorde Arcanist (F23); Force of Despair (F22); Jeska's Will (F20); Lotus Bloom (F27); Mystic Forge (F23); Rite of Flame (F20); Spire of Industry (F20); The Mightstone and Weakstone (F21)
- **P4:** Burning Wish (F31); Gilded Drake (F33); Jace, the Perfected Mind (F30); Karn, the Great Creator (F30); Liliana of the Veil (F30); Necropotence (F34); Phantasmal Image (F32); Ugin, the Spirit Dragon (F30); Yawgmoth's Bargain (F34)
- **P6:** Advantageous Proclamation (F56); Cephalid Illusionist (F51); Delver of Secrets // Insectile Aberration (F53); Maze of Ith (F51); Muddle the Mixture (F54); Nomads en-Kor (F51); Power Play (F56); Tolaria West (F54)

Drafted custom conspiracies (no Scryfall record, outside the pool): ANOTHER HEAD?!, I've Made a Huge Mistake, Meddling Wizard, Quanitity Over Quality.

## Open decisions for the user

1. **Fold `roto` into the default pool?** Decided 2026-10-03: yes -- `all` is the EoE-era dumps + cube + roto (`feature/roto-default-pool-leyline-wizard`); no printing already in `all` changed. Self-play on the roto cube still needs a deck pool; `scripts/build_cube_deck_pool.py` is cube-only and would need a pool parameter.
2. **Wish / sideboard semantics** (Burning Wish, Karn's -2): in a roto draft the sideboard is the drafter's unused picks.
3. **Custom conspiracies**: whether to hand-author records for them (only Meddling Wizard changes a game; Quanitity Over Quality changes deck size; ANOTHER HEAD?! lets a deck run two copies of a card).

