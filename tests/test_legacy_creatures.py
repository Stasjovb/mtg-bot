"""The ``legacy`` pool (the Legacy Izzet Delver 75's cards outside the cube:
Murktide Regent, Prismari Charm) in the parser and the card IR, and the
shared-schema export (``mtg_bot cards export-ir --pool cube legacy``) that
mtg-zero's ``card_ir`` crate reads."""

from __future__ import annotations

import json

import pytest

from mtg_bot.cards import ir
from mtg_bot.cards.parser.legacy_creatures import parse_legacy_creature_line
from mtg_bot.cards.pools import load_pool_cards, pool_card_names
from mtg_bot.cli.cards import export_ir
from mtg_bot.effects.base import TriggeredAbility
from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
from mtg_bot.effects.generic.cube_walkers import HasPrintedCardType
from mtg_bot.effects.object_predicates import ObjectOr
from mtg_bot.effects.predicates import EVENT_SUBJECTS, And, Controlled, Event, Subject

INSTANT_OR_SORCERY = ObjectOr(HasPrintedCardType("Instant"), HasPrintedCardType("Sorcery"))


@pytest.fixture(scope="module")
def legacy():
    return ir.pool_printings("legacy")


def test_the_pool_is_the_two_maindeck_cards():
    assert pool_card_names("legacy") == {"Murktide Regent", "Prismari Charm"}
    # Scryfall records, no basic lands.
    assert all(c["object"] == "card" for c in load_pool_cards("legacy"))


def test_both_cards_are_claimed(legacy):
    assert sorted(legacy) == ["Murktide Regent", "Prismari Charm"]


def test_murktide_regent(legacy):
    m = legacy["Murktide Regent"]
    assert (m.mana_cost_str, m.power, m.toughness, m.subtypes) == ("{5}{U}{U}", 3, 3, ("Dragon",))
    # Delve (CR 702.66) and flying.
    assert m.has_delve and m.keywords == frozenset({"flying"})
    # CR 607.2q, 614.1c: a +1/+1 counter for each instant and sorcery card
    # exiled to pay its cost.
    assert m.enters_with_counter_per_card_exiled_with_it == INSTANT_OR_SORCERY
    # "Whenever an instant or sorcery card leaves your graveyard, put a +1/+1
    # counter on this creature." (one trigger per card, CR 603.10a).
    assert m.triggered_abilities == (
        TriggeredAbility(
            event=Event.LEAVES_GRAVEYARD,
            predicate=And(Subject(slot="card", inner=INSTANT_OR_SORCERY), Controlled(subject="player")),
            effect=PutPlusOneCounterOnSelf(),
        ),
    )
    assert EVENT_SUBJECTS[Event.LEAVES_GRAVEYARD] == ("player", "card")


def test_prismari_charm(legacy):
    from mtg_bot.effects import ModalChooseOne

    p = legacy["Prismari Charm"]
    assert p.mana_cost_str == "{U}{R}" and p.card_types == ("Instant",)
    eff = p.spell_effect
    assert isinstance(eff, ModalChooseOne) and not eff.or_both
    surveil_draw, damage, bounce = eff.modes
    assert surveil_draw.describe().lower().startswith("surveil 2")
    # "deals 1 damage to each of one or two targets": any target, 1..2.
    assert type(damage).__name__ == "DealDamageToEachTarget" and damage.amount == 1
    (spec,) = damage.targets
    assert (spec.count_min, spec.count_max) == (1, 2)
    # "Return target nonland permanent to its owner's hand."
    assert type(bounce).__name__ == "Bounce"


@pytest.mark.parametrize("line", [
    "Delve",
    "This creature enters with a +1/+1 counter on it for each instant and sorcery card exiled with it.",
    "Murktide Regent enters with a +1/+1 counter on it for each instant and sorcery card exiled with it.",
    "Whenever an instant or sorcery card leaves your graveyard, put a +1/+1 counter on this creature.",
])
def test_the_recognizers(line):
    assert parse_legacy_creature_line(line, "Murktide Regent") is not None


@pytest.mark.parametrize("line", [
    "Delve, flying",
    "This creature enters with a +1/+1 counter on it for each instant and instant card exiled with it.",
    "This creature enters with a +1/+1 counter on it for each spell card exiled with it.",
    "Whenever a card leaves your graveyard during your turn, draw a card.",
    "Whenever an instant or sorcery card leaves your graveyard, draw a card.",
])
def test_lines_it_does_not_claim(line):
    assert parse_legacy_creature_line(line, "Murktide Regent") is None


def test_shared_schema_export(tmp_path):
    summary = export_ir(["cube", "legacy"], tmp_path)
    cube = json.loads((tmp_path / "powerlsv.ir.json").read_text(encoding="utf-8"))
    leg = json.loads((tmp_path / "legacy.ir.json").read_text(encoding="utf-8"))
    assert cube["schema_sha256"] == leg["schema_sha256"] == summary["schema_sha256"]
    assert not (tmp_path / "legacy.schema.json").exists()
    both = [pr[n] for pr in (ir.pool_printings("cube"), ir.pool_printings("legacy")) for n in sorted(pr)]
    schema = ir.build_schema(both)
    assert schema.sha256() == cube["schema_sha256"]
    written = json.loads((tmp_path / "powerlsv.schema.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(schema.to_json()))
    # Each document decodes with the one schema; the cube's cards are those
    # of the cube-only export (only the schema hash differs).
    assert sorted(ir.decode_document(leg, schema)) == ["Murktide Regent", "Prismari Charm"]
    alone, _ = ir.build_document("cube")
    assert cube["cards"] == alone["cards"]
    assert [d["pool"] for d in summary["documents"]] == ["cube", "legacy"]
    with pytest.raises(ValueError):
        export_ir(["cube", "cube"], tmp_path)
    with pytest.raises(ValueError):
        export_ir(["cube", "legacy"], tmp_path, name="x")


def test_the_python_engine_refuses_to_play_murktide(legacy):
    # Its two abilities are card-IR data only (SEARCH_LIMITATIONS, "Legacy
    # pool" 1): entering the battlefield fails loudly, never silently
    # without its counters or trigger.
    from mtg_bot.actions import put_into_battlefield
    from tests._rmc_helpers import make_state

    from mtg_bot.game import Zone

    state = make_state()
    obj = state.new_object(legacy["Murktide Regent"], owner_id=0, zone=Zone.HAND)
    with pytest.raises(NotImplementedError, match="card-IR data only"):
        put_into_battlefield(state, obj, 0)
