"""Predicate-based trigger model.

Triggered abilities are evolving from per-key string triggers
(``trigger="landfall"``) toward an ``(event, predicate)`` shape:

  ``TriggeredAbility(event=Event.ENTERS, predicate=IsLand() & Controlled(YOU))``

The event identifies an abstract MTG event (a permanent enters the
battlefield, a permanent dies, a creature attacks, …). The predicate
filters which firings of that event the ability cares about — the
firing object's properties (type, controller, counters, keywords)
plus optional game-state checks (your life total, your artifact
count, void status). One vocabulary, three call sites: trigger
predicates (this module), static-ability scope predicates (future),
and effect-conditional predicates (future).

Predicates compose via ``&`` / ``|`` / ``~``. They evaluate against a
mapping of named event subjects (each event declares its subject
slots; ``Enters`` and ``Dies`` use ``"obj"``; ``Blocks`` uses
``"blocker"`` and ``"attacker"``; ``DealsCombatDamage`` uses
``"source"`` and ``"target"``). Subject-scoped predicates pick a
slot via the ``Subject(name)`` namespace; bare predicates target the
default subject (``"obj"`` for single-subject events).

Phase 1 keeps the surface intentionally small — just the primitives
needed to model the existing ``etb`` / ``landfall`` /
``artifact_enters_you_control`` triggers in the new shape. Other
event families (dies, attacks, combat damage, etc.) will land in
subsequent phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


class Event(str, Enum):
    """Abstract MTG event names. Each event has a fixed set of
    subject-slot names (see ``EVENT_SUBJECTS``). Engine dispatch
    fires every triggered ability whose ``event`` matches and whose
    predicate evaluates true against the event's subject mapping.
    """

    ENTERS = "enters"
    DIES = "dies"
    LEAVES_BATTLEFIELD = "leaves_battlefield"
    BECOMES_TAPPED = "becomes_tapped"
    ATTACKS = "attacks"
    BLOCKS = "blocks"
    DEALS_COMBAT_DAMAGE = "deals_combat_damage"
    # A permanent has just been dealt damage (combat damage from an
    # attacker/blocker hitting a creature, or non-combat damage from a
    # spell/ability). Subject is the damaged permanent. The amount is
    # threaded through ``dispatch_event``'s ``combat_damage_amount``
    # parameter so resolving effects can read
    # ``state.resolving_combat_damage_amount``. Models the
    # aura/Equipment "Whenever enchanted creature is dealt damage"
    # observer family — the dispatcher fires once per
    # source-target damage application, mirroring the per-event
    # invocation of the legacy
    # ``_fire_enchanted_dealt_damage_triggers`` helper.
    DEALT_DAMAGE = "dealt_damage"
    # A spell has just been cast. Subjects are the spell ``GameObject``
    # being cast (``"spell"``) and the casting Player (``"controller"``).
    # Models the spell-cast observer family — ``IsArtifact(subject=
    # "spell")`` for artifact-spell triggers (Pinnacle Emissary),
    # ``Controlled(YOU, subject="controller")`` to gate "you cast" vs
    # opponent. The dispatcher fires once per cast; the
    # ``second_spell_each_turn`` trigger layers
    # ``SpellsCastThisTurn(eq=2)`` on top to catch the 2nd spell.
    IS_CAST = "is_cast"
    # A permanent has just been sacrificed. Subject is the sacrificed
    # ``GameObject`` (``"obj"``); the dispatcher fires AFTER the object
    # has been moved to the graveyard and includes the dearly-departed
    # via ``extra_observers`` so a self-trigger ``IsSelf()`` can match
    # though the object has left the battlefield. Predicates layer
    # ``IsArtifact()`` / ``IsCreature()`` on the subject and ``~IsSelf()``
    # to limit firing to "another" sacrifices.
    IS_SACRIFICED = "is_sacrificed"
    # A player has just played a land (the land-drop action of CR 305.1,
    # NOT effects that put a land onto the battlefield like Burgeoning).
    # Subjects are the land permanent (``"land"``) and the player who
    # played it (``"controller"``). Predicates use ``Controlled(by=
    # OPPONENT, subject="controller")`` for Burgeoning's "an opponent
    # plays a land" gate.
    PLAYS_LAND = "plays_land"
    # A player has just discarded a single card. Subject is the
    # discarding Player (``"player"``). Predicates use ``Controlled(by=
    # OPPONENT, subject="player")`` for "an opponent discards a card"
    # observers (Entropic Battlecruiser). The discarding player's id is
    # also threaded through to the resulting StackItem as a fixed target
    # ``("player", id)`` so the resolving effect can damage them.
    DISCARDS_CARD = "discards_card"
    # One or more +1/+1 counters have just been put on a creature.
    # Subject is the creature receiving the counters (``"obj"``); the
    # effective amount (post-doubling) is threaded via ``counter_amount``
    # so resolving effects can read ``state.resolving_counter_amount``
    # (Terrasymbiosis's "draw that many cards"). Predicate
    # ``IsCreature() & Controlled(YOU)`` gates "a creature you control".
    COUNTERS_ADDED = "counters_added"
    # Turn-structure events. Subject is a Player (the player whose
    # phase/step is beginning), not a permanent — so the
    # ``Controlled(YOU)`` predicate matches a player subject by
    # ``player.id == source.controller_id`` rather than the
    # ``obj.controller_id == source.controller_id`` rule used for
    # permanent subjects. ``Always()`` paired with
    # ``BEGINNING_OF_END_STEP`` models the "each end step" variant
    # (Ragost) that fires regardless of whose end step it is.
    BEGINNING_OF_UPKEEP = "beginning_of_upkeep"
    BEGINNING_OF_COMBAT = "beginning_of_combat"
    BEGINNING_OF_END_STEP = "beginning_of_end_step"
    # Beginning of the active player's second (post-combat) main phase.
    # Subject is the active Player. Models the DSK Survival ability-word
    # trigger ("Survival — At the beginning of your second main phase,
    # if this creature is tapped, …") — the Player subject pairs with
    # ``Controlled(YOU)`` for the "your" qualifier exactly like the
    # other turn-structure events. The intervening-if "this creature is
    # tapped" gate is encoded via the ``IsTapped`` predicate below
    # AND-ed onto the source-self ``IsSelf()`` arm.
    BEGINNING_OF_POSTCOMBAT_MAIN = "beginning_of_postcombat_main"
    # A Room has just had its second / final door unlocked, transitioning
    # ``unlocked_halves`` from a single-half set to the full set
    # (``len(unlocked_halves) == len(printing.room_halves)``). Subject is
    # the Room ``GameObject`` (``"room"``). Models the Duskmourn "Eerie"
    # ability-word trigger arm: ``Eerie — Whenever an enchantment you
    # control enters or you fully unlock a Room, …``. Distinct from the
    # per-half "When you unlock this door, …" triggers (which fire via
    # ``_fire_unlock_door_triggers`` in ``actions.py`` against
    # ``Event.ENTERS`` so an enters-with-half-unlocked Room and a later
    # unlock action share the same self-target trigger code path) — the
    # ROOM_FULLY_UNLOCKED event fires only on the transition into the
    # all-halves-unlocked state, observable by ANY permanent on the
    # battlefield (not just the Room itself), and only fires once even
    # if the Room enters with both halves pre-unlocked (the ENTERS path
    # handles per-half triggers; the FULLY_UNLOCKED dispatch fires from
    # the unlock-action site at the transition moment).
    ROOM_FULLY_UNLOCKED = "room_fully_unlocked"
    # The active player has just declared one or more attackers in this
    # combat phase. Subject is the attacking Player (the active player —
    # ``"player"``). Distinct from ``ATTACKS`` (per-attacker, fires once
    # for each declared attacker): ``YOU_ATTACK`` fires exactly ONCE per
    # declare-attackers pass when at least one creature attacked, with
    # the attacking player as the subject. Models the DSK "Whenever you
    # attack" trigger family (Razorkin Hordecaller, Most Valuable Slayer,
    # Lionheart Glimmer) — the trigger doesn't multiply with attacker
    # count, so the per-pass dispatch is the right semantic. The Player
    # subject pairs with ``Controlled(YOU)`` for the "you" qualifier
    # exactly like the turn-structure events.
    YOU_ATTACK = "you_attack"


# Subject-slot names per event. Used by the engine to validate that a
# dispatch call provides every required subject and by predicates to
# resolve the default subject when one isn't named explicitly.
EVENT_SUBJECTS: dict[Event, tuple[str, ...]] = {
    Event.ENTERS: ("obj",),
    Event.DIES: ("obj",),
    Event.LEAVES_BATTLEFIELD: ("obj",),
    Event.BECOMES_TAPPED: ("obj",),
    Event.ATTACKS: ("attacker",),
    Event.BLOCKS: ("blocker", "attacker"),
    Event.DEALS_COMBAT_DAMAGE: ("source", "target"),
    Event.DEALT_DAMAGE: ("obj",),
    Event.IS_CAST: ("spell", "controller"),
    Event.IS_SACRIFICED: ("obj",),
    Event.PLAYS_LAND: ("land", "controller"),
    Event.DISCARDS_CARD: ("player",),
    Event.COUNTERS_ADDED: ("obj",),
    Event.BEGINNING_OF_UPKEEP: ("player",),
    Event.BEGINNING_OF_COMBAT: ("player",),
    Event.BEGINNING_OF_END_STEP: ("player",),
    Event.BEGINNING_OF_POSTCOMBAT_MAIN: ("player",),
    Event.ROOM_FULLY_UNLOCKED: ("room",),
    Event.YOU_ATTACK: ("player",),
}


class _Controller(Enum):
    """Symbolic reference to a player relative to the firing source.

    ``YOU`` resolves to the source ability's controller at predicate
    evaluation time. ``OPPONENT`` resolves to "any player who is NOT the
    source's controller" — for two-player games this is the natural
    encoding of "an opponent <does X>" trigger qualifiers (Burgeoning's
    "an opponent plays a land", Entropic Battlecruiser's "an opponent
    discards a card"). Future expansion: ``ANY``.
    """

    YOU = "you"
    OPPONENT = "opponent"


YOU = _Controller.YOU
OPPONENT = _Controller.OPPONENT


class Predicate(ABC):
    """A boolean over (event subjects, game state, source object).

    Subclasses implement :meth:`matches`. Combine with ``&`` / ``|`` /
    ``~``; the operators return ``And`` / ``Or`` / ``Not`` instances
    that delegate evaluation to their operands.
    """

    @abstractmethod
    def matches(
        self,
        state: "GameState",
        subjects: Mapping[str, Any],
        source: "GameObject",
    ) -> bool:
        ...

    def __and__(self, other: "Predicate") -> "Predicate":
        return And(self, other)

    def __or__(self, other: "Predicate") -> "Predicate":
        return Or(self, other)

    def __invert__(self) -> "Predicate":
        return Not(self)


@dataclass(frozen=True)
class And(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, state, subjects, source):
        return (
            self.left.matches(state, subjects, source)
            and self.right.matches(state, subjects, source)
        )


@dataclass(frozen=True)
class Or(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, state, subjects, source):
        return (
            self.left.matches(state, subjects, source)
            or self.right.matches(state, subjects, source)
        )


@dataclass(frozen=True)
class Not(Predicate):
    inner: Predicate

    def matches(self, state, subjects, source):
        return not self.inner.matches(state, subjects, source)


@dataclass(frozen=True)
class Always(Predicate):
    """Tautology — fires for every event matching the trigger's
    event type. Useful as a default and in tests."""

    def matches(self, state, subjects, source):
        return True


@dataclass(frozen=True)
class Never(Predicate):
    """Contradiction — never fires. Useful for tests and as an
    explicit 'disabled' marker."""

    def matches(self, state, subjects, source):
        return False


# ---------- subject-scoped predicates ----------
#
# Each subject-scoped predicate carries an optional ``subject``
# slot name. ``None`` means "use the event's default subject"
# (the first entry in ``EVENT_SUBJECTS[event]``). The engine
# resolves ``subject`` against the dispatched subjects mapping
# at evaluation time.


def _resolve_subject(
    subjects: Mapping[str, Any], slot: str | None
) -> Any:
    """Look up the named subject slot; if ``slot`` is ``None`` and
    the event has exactly one subject, use that. Returns ``None`` when
    the slot isn't present (predicate then evaluates false)."""
    if slot is not None:
        return subjects.get(slot)
    if len(subjects) == 1:
        return next(iter(subjects.values()))
    return None


@dataclass(frozen=True)
class IsSelf(Predicate):
    """The named subject IS the firing source object (object identity).

    Models "this creature/permanent <event>" — the event subject
    being the same permanent that hosts the triggered ability.

    On turn-structure events (``BEGINNING_OF_POSTCOMBAT_MAIN`` etc.)
    whose only subject is a Player rather than a permanent, the
    no-subject ``IsSelf()`` reads as "the source IS itself" and
    evaluates true: the dispatcher already iterates one source at a
    time, so the predicate is tautological for those events. This
    keeps the Survival idiom ``IsSelf() & IsTapped()`` readable as
    "the source permanent is tapped" without needing a special
    ``"source"`` subject slot. Detection mirrors ``Controlled``'s
    permanent-vs-player branch: a Player exposes ``id`` but no
    ``printing`` attribute, so ``not hasattr(obj, "printing")`` is the
    cheapest reliable distinguisher.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        # Turn-structure events expose a Player subject; ``IsSelf()``
        # against a Player has no useful identity check, so treat
        # subject=None on a Player-only event as a tautology — the
        # source-self check is what the surface text means.
        if (
            self.subject is None
            and obj is not None
            and not hasattr(obj, "printing")
        ):
            return True
        return obj is source


@dataclass(frozen=True)
class IsHost(Predicate):
    """The named subject IS the permanent this source is attached to.

    Models the aura/equipment relational triggers — "Whenever
    enchanted creature attacks", "Whenever enchanted permanent
    becomes tapped", "Whenever equipped creature attacks",
    "Whenever enchanted creature is dealt damage" — where the
    *source* of the trigger is the aura/Equipment and the firing
    subject is its host (the enchanted/equipped permanent it's
    attached to).

    The match keys off ``source.attached_to == subject.id``. When
    the source isn't attached to anything (``attached_to is None``)
    or the named subject isn't a permanent with an ``id``, the
    predicate evaluates false — auras that have lost their host
    via SBA cleanup never spuriously fire.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        host_id = getattr(source, "attached_to", None)
        if host_id is None:
            return False
        return getattr(obj, "id", None) == host_id


@dataclass(frozen=True)
class IsLand(Predicate):
    """The named subject is a land (``"Land"`` in its card_types)."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Land" in obj.printing.card_types


@dataclass(frozen=True)
class IsCreature(Predicate):
    """The named subject is a creature."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Creature" in obj.printing.card_types


@dataclass(frozen=True)
class IsArtifact(Predicate):
    """The named subject is an artifact."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Artifact" in obj.printing.card_types


@dataclass(frozen=True)
class IsEnchantment(Predicate):
    """The named subject is an enchantment.

    Models the "an enchantment you control enters" qualifier on the
    Duskmourn "Eerie" ability-word trigger family. Mirrors the
    ``IsArtifact`` / ``IsCreature`` siblings — checks the printing's
    ``card_types`` for the ``"Enchantment"`` type. Rooms (which print
    as ``Enchantment — Room``) carry ``"Enchantment"`` in their
    ``card_types`` so a Room entering ALSO satisfies this predicate;
    that's the printed Eerie semantics — both arms are independent
    fires, an enters-as-Room event would observe both the
    ENTERS-as-enchantment arm AND, on its later transition to
    fully-unlocked, the ROOM_FULLY_UNLOCKED arm.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        if not hasattr(obj, "printing"):
            return False
        return "Enchantment" in obj.printing.card_types


@dataclass(frozen=True)
class IsPlayer(Predicate):
    """The named subject is a Player (not a permanent).

    Distinguishes the player vs. permanent target slot in multi-subject
    events like ``DEALS_COMBAT_DAMAGE`` whose ``"target"`` slot can be
    either a creature or a player. Models the "deals combat damage to a
    player" qualifier in triggers like Illvoi Infiltrator's
    ``IsSelf(subject="source") & IsPlayer(subject="target")`` and
    Starwinder's ``IsCreature(subject="source") & Controlled(YOU,
    subject="source") & IsPlayer(subject="target")``.

    Detection mirrors ``Controlled``'s permanent-vs-player branch:
    Players expose ``id`` but lack ``controller_id`` and ``printing``,
    while ``GameObject`` exposes both ``controller_id`` and
    ``printing``. Checking for the absence of ``printing`` is the
    cheapest reliable distinguisher and avoids the import cycle into
    ``mtg_bot.game`` for an isinstance check.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        # Players have ``id`` but no ``printing``; permanents have both.
        return not hasattr(obj, "printing")


@dataclass(frozen=True)
class Controlled(Predicate):
    """The named subject is controlled by the indicated player.

    ``by`` of ``YOU`` resolves to the source ability's controller at
    evaluation time; ``OPPONENT`` resolves to "any non-controller"
    (which in two-player games is exactly "the other player"). Future
    expansion: ``ANY`` / explicit player ids.

    Two subject shapes are supported:

    - **Permanent subject** (``GameObject``): match by
      ``obj.controller_id == source.controller_id`` — the standard
      "you control this permanent" check used by ENTERS / DIES /
      ATTACKS / etc.
    - **Player subject** (``Player``, no ``controller_id`` attribute
      because a player isn't controlled by another player): match by
      ``player.id == source.controller_id``. This is the path used by
      turn-structure events (``BEGINNING_OF_UPKEEP``,
      ``BEGINNING_OF_COMBAT``, ``BEGINNING_OF_END_STEP``) whose subject
      is a ``Player`` — ``Controlled(YOU)`` then reads as "this is
      MY phase/step", which is the natural mapping for the oracle
      phrasing "at the beginning of YOUR upkeep". The same branch
      handles the "discarding player" / "land-playing player" subjects
      threaded by ``DISCARDS_CARD`` / ``PLAYS_LAND`` dispatch — paired
      with ``OPPONENT`` it gates Burgeoning's "an opponent plays a
      land" and Entropic Battlecruiser's "an opponent discards" cleanly.

    The branch is selected by the presence of ``controller_id`` on the
    subject (``GameObject`` has it, ``Player`` does not), keeping the
    predicate identifier-stable across both event families instead of
    introducing a separate ``IsControllerOfSource`` for the player case.
    """

    by: _Controller = YOU
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        # Player subjects expose ``id`` (no ``controller_id``);
        # permanent subjects expose ``controller_id``. Distinguish on
        # attribute presence rather than isinstance to avoid an
        # import cycle into ``mtg_bot.game``.
        if hasattr(obj, "controller_id"):
            controller = obj.controller_id
        else:
            controller = getattr(obj, "id", None)
        if controller is None:
            return False
        if self.by == YOU:
            return controller == source.controller_id
        if self.by == OPPONENT:
            return controller != source.controller_id
        raise NotImplementedError(f"unsupported controller ref: {self.by!r}")


@dataclass(frozen=True)
class IsNontoken(Predicate):
    """The named subject is NOT a token.

    Token-ness lives on the printing (``CardPrinting.is_token`` checks
    for the ``"Token"`` supertype). Models the "nontoken" qualifier in
    triggers like ``"Whenever a nontoken artifact you control enters"``
    — cards spawned by token-creator effects must be excluded from the
    firing pool.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return not obj.printing.is_token


@dataclass(frozen=True)
class HasSubtype(Predicate):
    """The named subject's printing has the given subtype string.

    Models the type-line subtype check used by triggers that gate on a
    creature subtype (e.g. ``"Whenever a Kavu you control enters"``).
    Compares against ``obj.printing.subtypes`` directly — runtime
    subtype grants (``temp_subtype``, ``effective_subtypes``) are not
    consulted here because every existing in-scope trigger keys off
    the printed subtype.
    """

    name: str
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return self.name in obj.printing.subtypes


@dataclass(frozen=True)
class IsTapped(Predicate):
    """The named subject is currently tapped.

    Models the intervening-if "if this creature is tapped" gate on the
    DSK Survival ability-word trigger ("Survival — At the beginning of
    your second main phase, if this creature is tapped, …"). Composes
    with ``IsSelf()`` on the source so the gate reads "the source
    permanent is tapped right now" — the standard Survival shape on
    every printed Survival creature in DSK.

    Default subject (``subject=None``) on a turn-structure event
    whose only subject is a Player resolves to checking the source's
    own tapped state — Players have no ``tapped`` attribute, so the
    naive ``getattr(player, "tapped", False)`` would always be False
    and the predicate would never fire. Detecting that case here and
    falling back to ``source.tapped`` matches the surface meaning of
    "this creature is tapped" on Survival cards (the source permanent
    IS the creature the oracle text refers to). Mirrors the
    ``IsSelf`` Player-subject branch above structurally.

    Named subjects (``subject="attacker"`` etc.) read straight from
    the named slot; if that subject lacks a ``tapped`` attribute (a
    Player) the predicate evaluates false rather than raising, the
    same way ``HasKeyword`` / ``HasCounter`` handle player-only
    subject slots.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        # Turn-structure events expose a Player subject (no ``tapped``
        # attribute); the surface text "this creature is tapped" then
        # refers to the source itself, not the player. Fall back to
        # source.tapped so the Survival idiom resolves naturally.
        if (
            self.subject is None
            and obj is not None
            and not hasattr(obj, "printing")
        ):
            return bool(getattr(source, "tapped", False))
        if obj is None:
            return False
        # Player subjects have ``id`` but no ``tapped`` attribute.
        return bool(getattr(obj, "tapped", False))


@dataclass(frozen=True)
class HasKeyword(Predicate):
    """The named subject currently has the given keyword.

    Models the keyword-qualifier check used by triggers that gate on a
    runtime keyword presence on the firing subject — Skystinger's
    ``HasKeyword("flying", subject="attacker")`` for "Whenever this
    creature blocks a creature with flying" matches when the BLOCKS
    event's ``"attacker"`` subject has flying right now (printed
    keyword, granted keyword via aura/equipment, or temp keyword via
    UEOT pump).

    Reads through ``effective_keywords(state, obj)`` rather than the
    raw ``obj.printing.keywords`` set — the legacy
    ``_fire_blocks_creature_with_flying`` walk in ``combat.py`` keys
    off ``effective_keywords`` so a creature granted flying by an aura
    qualifies; preserving that behavior in the predicate path keeps
    parity with the legacy fire path.
    """

    name: str
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        if not hasattr(obj, "printing"):
            # Players don't have keywords.
            return False
        from mtg_bot.game import effective_keywords

        return self.name in effective_keywords(state, obj)


# Map a counter "kind" string to the ``GameObject`` attribute that
# holds its current count. Engine stores counters as separate scalar
# fields on ``GameObject`` (not a single dict) — the predicate maps
# the canonical printed names (``"+1/+1"``, ``"charge"``, ``"stun"``,
# ``"loyalty"``) onto those fields. New counter kinds must extend
# this table when they get added engine-side.
_COUNTER_ATTRS: dict[str, str] = {
    "+1/+1": "plus_one_counters",
    "charge": "charge_counters",
    "stun": "stun_counters",
    "loyalty": "loyalty_counters",
}


@dataclass(frozen=True)
class HasCounter(Predicate):
    """The named subject has at least one counter of ``kind`` on it.

    Models the "with a +1/+1 counter on it" qualifier in triggers like
    ``"Whenever a creature you control with a +1/+1 counter on it
    dies"`` (Meltstrider Eulogist) and ``"Whenever a nontoken creature
    you control with a +1/+1 counter on it dies"`` (Rayblade Trooper).

    ``kind`` is the printed counter name (``"+1/+1"``, ``"charge"``,
    ``"stun"``, ``"loyalty"``) — the predicate looks up the
    corresponding scalar field on ``GameObject`` via ``_COUNTER_ATTRS``
    and tests for ``> 0``. Unknown counter kinds raise ``KeyError`` at
    evaluation time so a typo surfaces immediately rather than
    silently never matching.
    """

    kind: str
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        attr = _COUNTER_ATTRS[self.kind]
        return getattr(obj, attr, 0) > 0


@dataclass(frozen=True)
class VoidActive(Predicate):
    """Game-state predicate: Void is active right now — i.e. a nonland
    permanent left the battlefield this turn or a spell was warped this
    turn. Subject-independent (the predicate ignores ``subjects``).

    Models the EoE "Void —" intervening-if gate that appears on
    triggered-ability lines like ``Void — Whenever <X>, if a nonland
    permanent left the battlefield this turn or a spell was warped this
    turn, <effect>.`` (Alpharael Stonechosen, Roving Actuator). The
    static-side equivalent today is ``TriggeredAbility(...,
    requires_void=True)`` checked in ``should_fire_trigger``; the
    predicate path expresses the same gate as a regular AND clause on
    the trigger's predicate so the dispatcher's existing predicate
    evaluation handles it without a separate flag.
    """

    def matches(self, state, subjects, source):
        from mtg_bot.game import is_void_active

        return is_void_active(state)


@dataclass(frozen=True)
class OpponentControlsMoreLandsThanYou(Predicate):
    """Game-state predicate: at least one opponent of the source's
    controller controls strictly more lands than the source's controller.
    Subject-independent.

    Models the "if an opponent controls more lands than you"
    intervening-if gate on Sunstar Expansionist's ETB. The static-side
    equivalent is ``ConditionalIfOpponentHasMoreLands`` (an effect
    combinator that gates resolution); this predicate is the
    trigger-time analogue used by the predicate-style trigger path.
    """

    def matches(self, state, subjects, source):
        my_id = source.controller_id
        my_lands = sum(
            1 for o in state.battlefield
            if o.controller_id == my_id and o.printing.is_land
        )
        for p in state.players:
            if p.id == my_id or getattr(p, "has_lost", False):
                continue
            count = sum(
                1 for o in state.battlefield
                if o.controller_id == p.id and o.printing.is_land
            )
            if count > my_lands:
                return True
        return False


# The Duskmourn "Delirium" mechanic counts distinct *card types* in the
# source controller's graveyard — Creature, Land, Sorcery, Instant,
# Enchantment, Artifact, Planeswalker, Battle, Tribal. The threshold is
# the printed "four or more" gate on every Delirium card; any future
# threshold variant would warrant a parameter rather than a new class
# (no such variant exists in DSK). The set of types counted is fixed by
# the comprehensive rules' card-type taxonomy — supertypes (Legendary,
# Snow, Basic) and subtypes (Goblin, Forest, Equipment) don't count.
_DELIRIUM_CARD_TYPES: frozenset[str] = frozenset({
    "Creature",
    "Land",
    "Sorcery",
    "Instant",
    "Enchantment",
    "Artifact",
    "Planeswalker",
    "Battle",
    "Tribal",
})


@dataclass(frozen=True)
class Delirium(Predicate):
    """Game-state predicate: the source's controller has at least four
    distinct card types among cards in their graveyard. Subject-
    independent (the predicate ignores ``subjects``).

    Models the Duskmourn "Delirium" mechanic — every card that prints
    a ``Delirium —`` ability word or the ``if there are four or more
    card types among cards in your graveyard`` intervening-if gate
    delegates to this predicate. The trigger-time check matches the
    printed gate exactly; the matching resolve-time recheck is not
    yet wired through the resolve pipeline (same gap as the Void /
    OpponentControlsMoreLandsThanYou siblings — those single-point
    intervening-if gates rely on trigger-time-only checks today).

    The card-type set is fixed by the comprehensive rules' card-type
    taxonomy (CR 205.2a) — supertypes and subtypes don't count. We
    walk the controller's graveyard once and short-circuit as soon
    as the running set hits four distinct types.
    """

    def matches(self, state, subjects, source):
        ctrl_id = source.controller_id
        try:
            player = state.player_by_id(ctrl_id)
        except (KeyError, AttributeError):
            return False
        seen: set[str] = set()
        for card in player.graveyard:
            for t in card.printing.card_types:
                if t in _DELIRIUM_CARD_TYPES:
                    seen.add(t)
                    if len(seen) >= 4:
                        return True
        return False


@dataclass(frozen=True)
class HasPowerAtMost(Predicate):
    """The named subject's effective power is less than or equal to ``n``.

    Models the "with power N or less" qualifier in triggers like
    Vicious Clown's ``Whenever another creature you control with power
    2 or less enters, …`` and Irreverent Gremlin's same condition.
    Reads through ``effective_power(state, obj)`` so a creature whose
    base power is reduced or boosted by counters / pump / anthems is
    measured by its current power, matching the printed surface.

    Non-creature subjects (lands, players) and subjects without a
    measurable power evaluate false — the qualifier only makes sense
    on a creature subject and the parser composes ``IsCreature() &
    HasPowerAtMost(n=2)`` to gate the trigger to creatures specifically.
    """

    n: int
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        if not hasattr(obj, "printing"):
            # Players don't have a power.
            return False
        from mtg_bot.game import effective_power

        try:
            power = effective_power(state, obj)
        except Exception:
            return False
        return power <= self.n


@dataclass(frozen=True)
class SpellsCastThisTurn(Predicate):
    """Game-state predicate: the named subject's controller has cast
    exactly ``n`` spells this turn (counted via
    ``Player.spells_cast_this_turn``).

    Models the "second spell each turn" trigger family (Illvoi
    Operative, Sunstar Lightsmith, Cosmogrand Zenith, Station Monitor):
    when the subject is the cast spell itself (``"spell"``) and ``n=2``
    the predicate latches the moment the controller's running total
    flips to 2, mirroring the legacy
    ``p.spells_cast_this_turn == 2`` gate at the
    ``actions._fire_second_spell_triggers`` call site.

    The predicate reads the spell-subject's controller (post-increment
    of ``spells_cast_this_turn``, since the dispatcher fires AFTER
    ``actions._cast_spell`` has bumped the counter). Layered with
    ``Controlled(YOU, subject="controller")`` the trigger fires only
    when the source's own controller casts their nth spell.
    """

    n: int
    subject: str = "controller"

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        # Subject may be either a Player (``id`` attribute, no
        # ``controller_id``) or a GameObject (cast spell). Resolve to
        # the controlling player either way.
        if hasattr(obj, "controller_id"):
            pid = obj.controller_id
        else:
            pid = getattr(obj, "id", None)
        if pid is None:
            return False
        try:
            player = state.player_by_id(pid)
        except (KeyError, AttributeError):
            return False
        return getattr(player, "spells_cast_this_turn", 0) == self.n
