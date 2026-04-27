"""Test helpers for the predicate-trigger migration.

Phase 2 migrated the ETB-event family (``"etb"``, ``"landfall"``,
``"artifact_enters_you_control"``, etc.) from string-key
``trigger=`` to the predicate-style ``event=Event.ENTERS,
predicate=...`` shape. Existing tests that scan trigger-key strings
(``ab.trigger == "etb"``, ``"landfall" in {ab.trigger ...}``) need
to recognize either the legacy or the migrated shape, since some
abilities on a printing may be on the predicate path while others
are still on the string-key path (DIES, ATTACKS, etc.).

These helpers paper over the difference for assertion code only —
production code never calls back into them. They are intentionally
narrow: they map a predicate-style ENTERS ability back to the
legacy string key its predicate is structurally equivalent to,
and otherwise return the literal ``ability.trigger`` field.
"""

from __future__ import annotations

from mtg_bot.effects.predicates import (
    And,
    Controlled,
    Event,
    HasSubtype,
    IsArtifact,
    IsCreature,
    IsLand,
    IsNontoken,
    IsSelf,
    Not,
    Or,
)


def _flatten_and(pred):
    """Flatten a left-associated And tree into a list of leaves."""
    if isinstance(pred, And):
        return _flatten_and(pred.left) + _flatten_and(pred.right)
    return [pred]


def _legacy_key_for_predicate(ability) -> str | None:
    """Return the legacy string key a predicate-style ENTERS ability
    is structurally equivalent to, or ``None`` if no mapping applies.

    The mapping mirrors the rewriting done in
    ``src/mtg_bot/cards/parser/triggers.py``'s
    ``_PREDICATE_TRIGGER_PHRASES`` table and the static-card
    migrations from phase 2.
    """
    if ability.event is not Event.ENTERS or ability.predicate is None:
        return None
    leaves = _flatten_and(ability.predicate)
    types = {type(leaf) for leaf in leaves}
    has_self = IsSelf in types
    has_not_self = any(
        isinstance(leaf, Not) and isinstance(leaf.inner, IsSelf)
        for leaf in leaves
    )
    has_land = IsLand in types
    has_artifact = IsArtifact in types
    has_creature = IsCreature in types
    has_nontoken = IsNontoken in types
    has_controlled = Controlled in types
    kavu_subtype = any(
        isinstance(leaf, HasSubtype) and leaf.name == "Kavu"
        for leaf in leaves
    )
    has_or = any(isinstance(leaf, Or) for leaf in leaves)
    # Self ETB.
    if has_self and len(leaves) == 1:
        return "etb"
    # Landfall.
    if has_land and has_controlled and not has_artifact:
        return "landfall"
    # Kavu observer.
    if kavu_subtype and has_controlled and has_not_self:
        return "kavu_you_control_enters"
    # Nontoken artifact.
    if has_artifact and has_nontoken and has_controlled and has_not_self:
        return "nontoken_artifact_enters_you_control"
    # Creature-or-artifact (Or in the predicate tree).
    if has_or and has_controlled and has_not_self:
        for leaf in leaves:
            if isinstance(leaf, Or):
                inner_types = {type(leaf.left), type(leaf.right)}
                if {IsCreature, IsArtifact} == inner_types:
                    return "creature_or_artifact_enters_you_control"
    # Plain artifact.
    if has_artifact and has_controlled and has_not_self and not has_nontoken:
        return "artifact_enters_you_control"
    return None


def _legacy_or_inferred_key(ability) -> str:
    """Return ``ability.trigger`` if non-empty, else infer the legacy
    key from the predicate-style fields. Tests that built sets of
    trigger keys for membership checks use this so the assertion logic
    survives the predicate migration intact."""
    if ability.trigger:
        return ability.trigger
    inferred = _legacy_key_for_predicate(ability)
    return inferred or ""


def _matches_legacy_key(ability, key: str) -> bool:
    """Equivalent to ``ability.trigger == key`` pre-migration; after
    migration also matches the predicate-style ENTERS shape that
    corresponds to ``key``."""
    return _legacy_or_inferred_key(ability) == key
