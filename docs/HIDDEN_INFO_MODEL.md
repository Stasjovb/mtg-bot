# Hidden information model

## Why we need this

The MCTS search currently sees every card in every zone, including face-down
zones (libraries, opponent hands, exile face-down). When the search picks an
action, it can implicitly use information that the agent in a real game would
not have — for example, knowing the top card of its own library or the
contents of its opponent's hand. That's "cheating": it inflates measured
strength in self-play and makes the bot brittle in real games.

The fix is **determinization** (PR 2): before each search, sample a possible
world that's consistent with what the searching player actually knows, then
search that world. To sample a consistent world we need to know, at each card,
who has seen it. That's what this PR adds.

## What we're tracking

A single per-card flag: `publicly_known_to: frozenset[PlayerID]`. The set
contains every player who has been shown the card's identity in a way that
gives them perfect knowledge of where it is right now.

Concretely, a card is in `publicly_known_to` for player P when:

- P owns it and it's in a public zone (battlefield, graveyard, exile face-up,
  command, stack) — these are derivable from zone, but tracking explicitly is
  cheap and uniform.
- P was shown the card as part of a resolution (tutor reveal, look-at-hand
  effect like Temporal Intervention, cast-from-exile-revealed effect).
- P drew or otherwise saw the card themselves, and the card hasn't moved to a
  zone where its identity becomes ambiguous again.

When a card moves into a zone where its position is no longer tracked
distinctly (most importantly, hand → library shuffle, library shuffle in
general), `publicly_known_to` is reset to the empty set and the card becomes
fully hidden again.

## The chosen design (Option A): lossy reset on disturbance

We picked the simplest model that supports determinization for the EoE card
pool:

- **Per-card flag, no per-zone-position knowledge.** Either P knows what this
  card is, or P doesn't.
- **Reset to empty on disturbance.** Anything that mixes a known card into an
  unordered hidden zone (Brainstorm putting cards back, library shuffles,
  scry-then-shuffle) resets the flag.

This is *under-informed*, not *misinformed*. The bot will sometimes act as if
the opponent has forgotten something the opponent really still knows — but it
will never act as if the opponent knows something the opponent does not.
Under-informed determinization gives a sound but slightly conservative search;
misinformed determinization gives an unsound search.

## Known shortcomings (these are real, and we are accepting them)

### 1. Multi-zone positional uncertainty is collapsed

Example: opponent knows you have an Island in hand. You cast Brainstorm, draw
3, put 2 back on top of your library. The opponent's true epistemic state is:

> "The Island is somewhere in {your hand, top 2 of your library} — I don't
> know which."

Our model can't represent this. The flag is per-card: the Island is either
"known to opponent" (in which case we'd have to pick one of the zones to put
it in, which is a lie either way) or "not known" (which throws away the
real information).

We resolve this by **resetting the flag** on the Brainstorm-style disturbance.
The opponent loses the partial knowledge entirely. Acceptable because:

- The EoE card pool has no Brainstorm. Hand-mixing-into-library effects are
  vanishingly rare.
- When they do show up, the opponent ends up under-informed (they still know
  some Island exists somewhere in your deck, which the public deck list
  already tells them) rather than misinformed.

### 2. Cardinality knowledge is collapsed

Example: opponent has seen you draw three Islands into your hand. They know
"≥3 Islands are in your hand." You cast Brainstorm. They now know "≥1 Island
is somewhere in {your hand, top 2 of your library}."

Our model can't represent "≥N copies of card X" knowledge in any zone, with
or without the disturbance. We track per-card identity, not cardinality
constraints over multisets.

Acceptable because:

- Same EoE-specific reasoning: hand-mixing is rare.
- Opponents ranking actions over a public deck list already know the count
  of every card in your deck. They lose only the *positional* refinement of
  that count, which the search treats as "could be anywhere in your hidden
  zones."

### 3. Memory of revealed-then-shuffled cards

Example: you cast a tutor (Demonic Tutor style), reveal the searched card,
put it in your hand. Opponent now knows you have card X. Later, you cast a
shuffle effect on your hand (real or virtual). Opponent's true knowledge is
"you still own card X, it's somewhere in your library or hand." Our model
resets the flag to empty.

Same shape as #1 and #2. Same reasoning: the deck list already tells the
opponent the card exists somewhere in your 60; they lose the location
refinement, which is mild.

## Why not a richer model

We considered two richer alternatives:

### Option B: position-set per card

Track each card's possible positions as a set of (zone, slot) tuples.
Brainstorm becomes "this Island is in {hand[i], library[0], library[1]}",
which the determinizer samples from.

**Pros:** captures #1 above exactly.

**Cons:** still doesn't capture #2 (cardinality over multiple unidentified
copies of the same card). The bookkeeping is intricate — every zone
transition has to update overlapping position sets across many cards. Bugs
here would silently corrupt determinization, which is the worst failure mode
because the search would produce confident-but-wrong play.

### Option C: full information-set / belief-state representation

Track the opponent's full belief state as a distribution (or constraint set)
over possible worlds. Captures #1 and #2 cleanly.

**Pros:** the only sound way to handle hand-mixing rigorously.

**Cons:** large engineering investment. Wrong abstraction for our card pool.
Worth revisiting only if we expand beyond EoE into formats with serious
hidden-information manipulation (Vintage, Legacy, EDH with cantrip suites).

## When we'd revisit this

Move to Option B or C if any of these become true:

- We expand the card pool to include hand-mixing effects (Brainstorm, Jace,
  the Mind Sculptor's #2 ability, top-of-library tutors followed by shuffle
  triggers).
- Self-play data shows the search consistently mispredicting opponent knowledge
  in measurable ways (e.g., bot plays around cards the opponent has already
  forgotten about, or fails to play around cards the opponent still
  remembers).
- We add an opponent model that explicitly reasons about what we know that
  they know — the lossy reset becomes a much bigger deal in
  recursive-belief reasoning.

Until then: per-card flag, reset on disturbance, accept the under-informed
edge cases.
