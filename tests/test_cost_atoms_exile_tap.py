"""Tests for three new activation cost atoms:

  1. exile_self        — Plaza of Heroes's "{3}, {T}, Exile this land: ..."
  2. tap_permanent_you_control — Gene Pollinator's "{T}, Tap an untapped
                                  permanent you control: Add one mana of
                                  any color."
  3. exile_artifact_from_graveyard — Rust Harvester's "{2}, {T}, Exile an
                                      artifact card from your graveyard: ..."

Each section tests:
  - Legality gate (activation illegal when condition not met)
  - Legality pass (activation legal when condition is met)
  - Payment: correct zone transitions and side-effects
  - describe() round-trip
"""

from __future__ import annotations

import pytest

import dataclasses

from mtg_bot.actions import (
    ActivateAbility,
    _activate_ability,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    DealDamageEqualToSourcePowerAnyTarget,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnSelf,
    Sequence,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.effects import ActivationCost as EffectsActivationCost
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


# ─── helpers ─────────────────────────────────────────────────────────────────

# Synthetic legendary creature for Plaza of Heroes tests.  Plaza's
# 4th ability targets "legendary creature" only; Wild Bear is non-
# legendary so we need a legendary printing for those tests.
_LEGENDARY_BEAR = dataclasses.replace(
    SYNTHETIC_CREATURES["Wild Bear"],
    supertypes=("Legendary",),
    type_line="Legendary Creature — Bear",
)


def _new_state(num_mountains: int = 3, num_plains: int = 0):
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    p1 = Player(id=1, agent=RandomAgent())
    state.players.append(p0)
    state.players.append(p1)
    for _ in range(num_mountains):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    for _ in range(num_plains):
        pl = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(pl)
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state: GameState, printing, controller_id: int = 0):
    obj = state.new_object(printing, controller_id, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _put_graveyard(state: GameState, printing, owner_id: int = 0):
    obj = state.new_object(printing, owner_id, Zone.GRAVEYARD)
    state.player_by_id(owner_id).graveyard.append(obj)
    return obj


# ═════════════════════════════════════════════════════════════════════════════
# 1. exile_self cost atom
# ═════════════════════════════════════════════════════════════════════════════


class TestExileSelf:
    """Tests for ActivationCost.exile_self (Plaza of Heroes's land-exile cost)."""

    def _make_exile_self_ability(self):
        """Minimal activated ability with exile_self cost."""
        return ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost("{3}"),
                mana_str="{3}",
                tap_self=True,
                exile_self=True,
            ),
            effect=PumpTargetCreatureUntilEOT(
                granted_keywords=frozenset({"hexproof", "indestructible"}),
            ),
        )

    def test_activation_cost_exile_self_field(self):
        cost = ActivationCost(exile_self=True)
        assert cost.exile_self is True
        assert cost.sacrifice_self is False

    def test_exile_self_describe(self):
        cost = ActivationCost(
            mana_str="{3}", tap_self=True, exile_self=True
        )
        desc = cost.describe()
        assert "Exile" in desc or "~" in desc

    def test_exile_self_describe_standalone(self):
        cost = ActivationCost(exile_self=True)
        assert "Exile ~" in cost.describe()

    def test_exile_self_mutual_exclusion_with_sacrifice_self(self):
        # Both fields can't both be True in a well-formed cost, but the
        # dataclass itself doesn't enforce it — parser does.
        cost = ActivationCost(exile_self=True, sacrifice_self=False)
        assert cost.exile_self is True
        assert cost.sacrifice_self is False

    def test_plaza_of_heroes_uses_exile_self(self):
        """The migrated bespoke entry must use exile_self, not sacrifice_self."""
        plaza = _PRINTINGS["Plaza of Heroes"]
        flagship = plaza.activated_abilities[3]
        assert flagship.cost.exile_self is True
        assert flagship.cost.sacrifice_self is False

    def test_plaza_of_heroes_activation_legal_on_battlefield(self):
        """Plaza's exile-self ability is legal when it's on the battlefield
        (mana available, untapped, legendary target creature exists).

        The ability targets "legendary creature" only — uses _LEGENDARY_BEAR
        (a synthetic creature with the Legendary supertype) rather than Wild
        Bear (non-legendary, not a legal target for Plaza's 4th ability).
        """
        state = _new_state(num_mountains=3)
        plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
        _put(state, _LEGENDARY_BEAR, controller_id=0)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == plaza.id
            and a.ability_index == 3
        ]
        assert acts, "Plaza's exile-self ability should be legal with a legendary target"

    def test_plaza_of_heroes_nonlegendary_creature_does_not_enable_activation(self):
        """Plaza's exile-self ability targets 'legendary creature' only —
        a non-legendary Wild Bear on the battlefield provides no legal
        targets, so the activation must NOT appear in legal_actions."""
        state = _new_state(num_mountains=3)
        plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
        _put(state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == plaza.id
            and a.ability_index == 3
        ]
        assert acts == [], (
            "Non-legendary creature should not enable Plaza's exile ability"
        )

    def test_plaza_of_heroes_exile_self_removes_from_battlefield(self):
        """Activating Plaza's exile ability puts Plaza in exile (not graveyard)."""
        state = _new_state(num_mountains=3)
        plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
        _put(state, _LEGENDARY_BEAR, controller_id=0)
        p0 = state.player_by_id(0)
        apply_action(
            state, 0, ActivateAbility(source_id=plaza.id, ability_index=3)
        )
        while state.stack:
            resolve_top_of_stack(state)
        # Plaza is exiled, not sacrificed.
        assert plaza not in state.battlefield
        assert plaza in p0.exile
        assert plaza not in p0.graveyard

    def test_plaza_of_heroes_exile_grants_keywords(self):
        """Plaza's exile-self ability grants hexproof and indestructible UEOT."""
        from mtg_bot.game import effective_keywords
        state = _new_state(num_mountains=3)
        plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
        _put(state, _LEGENDARY_BEAR, controller_id=0)
        apply_action(
            state, 0, ActivateAbility(source_id=plaza.id, ability_index=3)
        )
        while state.stack:
            resolve_top_of_stack(state)
        # At least one creature on the battlefield has hexproof (the
        # legendary bear chosen as target by RandomAgent).
        any_hexproof = any(
            "hexproof" in effective_keywords(state, o)
            for o in state.battlefield
            if o.printing.is_creature
        )
        assert any_hexproof

    def test_exile_self_target_exclusion(self):
        """When exile_self is set, the source itself is excluded from legal
        targets (same as sacrifice_self)."""
        state = _new_state()
        plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
        # Only target: the plaza itself (land, not creature) — no creature
        # means no legal targets, so the action isn't offered.
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == plaza.id
            and a.ability_index == 3
        ]
        assert acts == [], "No legal targets → exile ability not offered"


# ═════════════════════════════════════════════════════════════════════════════
# 2. tap_permanent_you_control cost atom
# ═════════════════════════════════════════════════════════════════════════════


class TestTapPermanentYouControl:
    """Tests for ActivationCost.tap_permanent_you_control (Gene Pollinator)."""

    def test_activation_cost_field(self):
        cost = ActivationCost(tap_permanent_you_control=True)
        assert cost.tap_permanent_you_control is True

    def test_describe_tap_permanent(self):
        cost = ActivationCost(
            tap_self=True, tap_permanent_you_control=True
        )
        desc = cost.describe()
        assert "Tap an untapped permanent you control" in desc

    def test_gene_pollinator_has_activated_ability(self):
        """Gene Pollinator should now have its mana ability, not be vanilla."""
        gp = _PRINTINGS["Gene Pollinator"]
        assert len(gp.activated_abilities) == 1
        ab = gp.activated_abilities[0]
        assert ab.cost.tap_self is True
        assert ab.cost.tap_permanent_you_control is True
        assert ab.is_mana_ability is True

    def test_gene_pollinator_alone_not_legal(self):
        """Gene Pollinator's ability requires another untapped permanent;
        when it's the only permanent, the activation is illegal."""
        state = _new_state(num_mountains=0)
        gp = _put(state, _PRINTINGS["Gene Pollinator"])
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == gp.id
        ]
        assert acts == [], "No other untapped permanent → activation illegal"

    def test_gene_pollinator_with_another_untapped_legal(self):
        """With another untapped permanent, the activation is legal."""
        state = _new_state(num_mountains=0)
        gp = _put(state, _PRINTINGS["Gene Pollinator"])
        land = _put(state, BASIC_LANDS["Forest"])
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == gp.id
        ]
        assert acts, "Another untapped permanent → activation legal"

    def test_gene_pollinator_with_only_tapped_other_illegal(self):
        """If the only other permanents are tapped, the activation is illegal."""
        state = _new_state(num_mountains=0)
        gp = _put(state, _PRINTINGS["Gene Pollinator"])
        land = _put(state, BASIC_LANDS["Forest"])
        land.tapped = True
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == gp.id
        ]
        assert acts == [], "Only tapped permanents → activation illegal"

    def test_gene_pollinator_activation_taps_other_permanent(self):
        """Activating Gene Pollinator taps another permanent as cost and
        produces one mana (mana ability, so immediate)."""
        state = _new_state(num_mountains=0)
        gp = _put(state, _PRINTINGS["Gene Pollinator"])
        forest = _put(state, BASIC_LANDS["Forest"])
        p0 = state.player_by_id(0)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == gp.id
        ]
        assert acts
        pre_pool = list(p0.mana_pool)
        apply_action(state, 0, acts[0])
        # Mana ability: resolves immediately (no stack entry).
        assert not state.stack, "Mana ability bypasses stack"
        # The forest (or gp) was tapped as cost; at least one non-gp
        # permanent the controller owned is now tapped.
        assert forest.tapped, "The other untapped permanent was tapped as cost"
        # Mana pool grew.
        assert len(p0.mana_pool) > len(pre_pool)

    def test_gene_pollinator_opponent_permanent_not_tappable(self):
        """Permanents controlled by opponents don't satisfy the cost."""
        state = _new_state(num_mountains=0)
        gp = _put(state, _PRINTINGS["Gene Pollinator"], controller_id=0)
        opp_land = _put(state, BASIC_LANDS["Forest"], controller_id=1)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == gp.id
        ]
        assert acts == [], "Opponent's untapped permanent doesn't count"


# ═════════════════════════════════════════════════════════════════════════════
# 3. exile_artifact_from_graveyard cost atom
# ═════════════════════════════════════════════════════════════════════════════


class TestExileArtifactFromGraveyard:
    """Tests for ActivationCost.exile_artifact_from_graveyard (Rust Harvester)."""

    def test_activation_cost_field(self):
        cost = ActivationCost(exile_artifact_from_graveyard=True)
        assert cost.exile_artifact_from_graveyard is True

    def test_describe_exile_artifact(self):
        cost = ActivationCost(
            mana_str="{2}", tap_self=True,
            exile_artifact_from_graveyard=True,
        )
        desc = cost.describe()
        assert "Exile an artifact card from your graveyard" in desc

    def test_rust_harvester_has_activated_ability(self):
        """Rust Harvester should now have its activated ability, not be menace-only."""
        rh = _PRINTINGS["Rust Harvester"]
        assert len(rh.activated_abilities) == 1
        ab = rh.activated_abilities[0]
        assert ab.cost.mana_str == "{2}"
        assert ab.cost.tap_self is True
        assert ab.cost.exile_artifact_from_graveyard is True

    def test_rust_harvester_no_artifact_in_gy_illegal(self):
        """Rust Harvester's ability is illegal with no artifact in graveyard."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        # Graveyard is empty → activation illegal.
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts == [], "Empty GY → activation illegal"

    def test_rust_harvester_non_artifact_in_gy_illegal(self):
        """A non-artifact card in the GY doesn't satisfy the cost."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        _put_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts == [], "Non-artifact in GY → activation illegal"

    def test_rust_harvester_artifact_in_gy_legal(self):
        """An artifact card in the graveyard makes the activation legal."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        # Use a printing that is_artifact. Get any artifact from printings.
        artifact_printing = None
        for name, p in _PRINTINGS.items():
            if p.is_artifact and not p.is_creature and not p.is_land:
                artifact_printing = p
                break
        if artifact_printing is None:
            pytest.skip("No non-creature artifact printing in pool")
        _put_graveyard(state, artifact_printing)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts, "Artifact in GY → activation legal"

    def test_rust_harvester_activation_exiles_artifact_from_gy(self):
        """Activating Rust Harvester removes the artifact from the graveyard
        and puts it in exile."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        # Find any artifact printing.
        artifact_printing = None
        for name, p in _PRINTINGS.items():
            if p.is_artifact and not p.is_creature and not p.is_land:
                artifact_printing = p
                break
        if artifact_printing is None:
            pytest.skip("No non-creature artifact printing in pool")
        art_card = _put_graveyard(state, artifact_printing)
        p0 = state.player_by_id(0)
        # Also put a creature on the battlefield as a target for the damage.
        bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts
        apply_action(state, 0, acts[0])
        while state.stack:
            resolve_top_of_stack(state)
        # Artifact should be exiled, not in graveyard.
        assert art_card not in p0.graveyard
        assert art_card in p0.exile

    def test_rust_harvester_activation_puts_counter_on_self(self):
        """Rust Harvester's ability puts a +1/+1 counter on itself."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        artifact_printing = None
        for name, p in _PRINTINGS.items():
            if p.is_artifact and not p.is_creature and not p.is_land:
                artifact_printing = p
                break
        if artifact_printing is None:
            pytest.skip("No non-creature artifact printing in pool")
        _put_graveyard(state, artifact_printing)
        # Need a target for the damage step.
        _put(state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1)
        initial_counters = rh.plus_one_counters
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts
        apply_action(state, 0, acts[0])
        while state.stack:
            resolve_top_of_stack(state)
        assert rh.plus_one_counters == initial_counters + 1

    def test_rust_harvester_opponent_artifact_in_gy_not_usable(self):
        """An artifact card in the OPPONENT's graveyard does not satisfy
        the cost — only the activating player's own graveyard counts."""
        state = _new_state(num_mountains=3)
        rh = _put(state, _PRINTINGS["Rust Harvester"])
        # Put an artifact in the OPPONENT's graveyard.
        artifact_printing = None
        for name, p in _PRINTINGS.items():
            if p.is_artifact and not p.is_creature and not p.is_land:
                artifact_printing = p
                break
        if artifact_printing is None:
            pytest.skip("No non-creature artifact printing in pool")
        _put_graveyard(state, artifact_printing, owner_id=1)
        acts = [
            a for a in legal_actions(state, 0)
            if isinstance(a, ActivateAbility)
            and a.source_id == rh.id
        ]
        assert acts == [], "Opponent GY artifact doesn't satisfy own cost"


# ═════════════════════════════════════════════════════════════════════════════
# Parser round-trip tests
# ═════════════════════════════════════════════════════════════════════════════


class TestParserRoundTrip:
    """The parser (activated.py) should now recognize the new cost atoms."""

    def test_parse_exile_self_cost_piece(self):
        from mtg_bot.cards.parser.activated import _classify_cost_piece
        piece = _classify_cost_piece("Exile this land")
        assert piece is not None
        assert piece.kind == "exile_self"

    def test_parse_exile_self_creature_piece(self):
        from mtg_bot.cards.parser.activated import _classify_cost_piece
        piece = _classify_cost_piece("Exile this creature")
        assert piece is not None
        assert piece.kind == "exile_self"

    def test_parse_tap_permanent_you_control_piece(self):
        from mtg_bot.cards.parser.activated import _classify_cost_piece
        piece = _classify_cost_piece("Tap an untapped permanent you control")
        assert piece is not None
        assert piece.kind == "tap_permanent_you_control"

    def test_parse_exile_artifact_from_graveyard_piece(self):
        from mtg_bot.cards.parser.activated import _classify_cost_piece
        piece = _classify_cost_piece("Exile an artifact card from your graveyard")
        assert piece is not None
        assert piece.kind == "exile_artifact_from_graveyard"

    def test_build_exile_self_cost(self):
        from mtg_bot.cards.parser.activated import _parse_activation_cost
        cost = _parse_activation_cost("{3}, {T}, Exile this land")
        assert cost is not None
        assert cost.exile_self is True
        assert cost.tap_self is True
        assert cost.mana_str == "{3}"

    def test_build_tap_permanent_you_control_cost(self):
        from mtg_bot.cards.parser.activated import _parse_activation_cost
        cost = _parse_activation_cost("{T}, Tap an untapped permanent you control")
        assert cost is not None
        assert cost.tap_self is True
        assert cost.tap_permanent_you_control is True

    def test_build_exile_artifact_from_graveyard_cost(self):
        from mtg_bot.cards.parser.activated import _parse_activation_cost
        cost = _parse_activation_cost(
            "{2}, {T}, Exile an artifact card from your graveyard"
        )
        assert cost is not None
        assert cost.mana_str == "{2}"
        assert cost.tap_self is True
        assert cost.exile_artifact_from_graveyard is True

    def test_exile_self_and_sacrifice_self_mutually_exclusive(self):
        """Classifying both exile_self and sacrifice_self in one cost returns
        None (duplicate sacrifice-flavor check)."""
        from mtg_bot.cards.parser.activated import _parse_activation_cost
        cost = _parse_activation_cost(
            "Sacrifice this creature, Exile this creature"
        )
        assert cost is None, "Dual sac/exile-self should be rejected"
