"""Secluded Starforge — VERIFY-FIRST characterization (HONEST-STOP).

Secluded Starforge is a real EoE ``Land`` (``mana_cost == ""``) with
three printed activated abilities:

  1. ``{T}: Add {C}.``
  2. ``{2}, {T}, Tap X untapped artifacts you control: Target creature
     gets +X/+0 until end of turn. Activate only as a sorcery.``
  3. ``{5}, {T}: Create a 2/2 colorless Robot artifact creature token.``

The pool-parity scout's original framing was "the parser drops its
activated abilities — the parsed printing comes out EMPTY (a parser-side
gap)." This module's VERIFY-FIRST pass **corrects** that framing and
freezes the corrected facts so a future worker starts from the verified
map (see the matching ``docs/SEARCH_LIMITATIONS.md`` entry, 2026-05-31):

  * **AAs 1 and 3 are NOT a parser gap** — both ALREADY parse cleanly
    through the live activated-ability grammar
    (``_parse_activated_ability_line``). The whole-card claim
    (``land_builder._try_build_colorless_utility_land``) emits an *empty*
    ``make_colorless_land`` and never routes the trailing lines through
    the AA grammar — that ordering, not a missing recognizer, is why the
    live printing is empty.
  * **AA2 is the sole real blocker** — it needs a genuinely-new
    variable-tap-cost X-channel substrate on BOTH engines (a
    ``Tap X untapped artifacts you control`` cost atom, a legal-actions
    enumeration of the chosen X, a non-mana → ``resolving_x_value``
    channel, and a pump-by-X effect). That is out of scope for a
    parser-only pass, so this slice HONEST-STOPS at the map level — no
    live-source change, no unfaithful partial (AAs-1+3-only) printing.

These tests are characterization pins, NOT a PROBED-tier flip. The card
stays BLOCKED-SG (empty land on both static + parser). This module is
intentionally NOT registered in ``scripts/measure_pool_parity.PROBE_
MODULES`` — there is no faithful byte-equal probe to credit yet.
"""

from __future__ import annotations

import pytest


def _starforge_card_record():
    """Return the raw Scryfall record for Secluded Starforge, or skip."""
    import json
    import os

    data_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "edge_of_eternities.json",
    )
    if not os.path.exists(data_path):
        pytest.skip("data/edge_of_eternities.json absent")
    with open(data_path, encoding="utf-8") as fh:
        data = json.load(fh)
    cards = data if isinstance(data, list) else data.get("cards", [])
    for c in cards:
        if isinstance(c, dict) and c.get("name") == "Secluded Starforge":
            return c
    pytest.skip("Secluded Starforge absent from edge_of_eternities.json")


# ---------------------------------------------------------------------------
# (1) Raw oracle text: the three printed activated abilities are present.
# ---------------------------------------------------------------------------


def test_secluded_starforge_raw_oracle_has_three_activated_abilities():
    """Freeze the raw printed surface: a plain ``Land`` with three
    activated-ability lines (mana / tap-X-artifacts pump / Robot token)."""
    rec = _starforge_card_record()
    assert rec.get("type_line") == "Land"
    oracle = rec.get("oracle_text", "")
    lines = [ln.strip() for ln in oracle.split("\n") if ln.strip()]
    assert len(lines) == 3
    assert lines[0] == "{T}: Add {C}."
    assert lines[1] == (
        "{2}, {T}, Tap X untapped artifacts you control: Target creature "
        "gets +X/+0 until end of turn. Activate only as a sorcery."
    )
    assert lines[2] == (
        "{5}, {T}: Create a 2/2 colorless Robot artifact creature token."
    )


# ---------------------------------------------------------------------------
# (2) AA1 (tap-for-C mana) parses through the live grammar.
# ---------------------------------------------------------------------------


def test_aa1_tap_for_colorless_parses_through_grammar():
    """AA1 ``{T}: Add {C}.`` is a recognized mana ability — NOT a gap."""
    from mtg_bot.cards.base import AddManaToPool
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line("{T}: Add {C}.")
    assert ab is not None
    assert isinstance(ab.effect, AddManaToPool)
    assert ab.effect.produces == (("C", 1),)
    assert ab.is_mana_ability is True
    assert ab.cost.tap_self is True


# ---------------------------------------------------------------------------
# (3) AA3 (Robot token) parses through the live grammar.
# ---------------------------------------------------------------------------


def test_aa3_robot_token_creation_parses_through_grammar():
    """AA3 ``{5}, {T}: Create a 2/2 colorless Robot artifact creature
    token.`` is fully recognized by the live grammar — NOT a gap.

    Cost classifies as mana ``{5}`` + tap; the effect body is the
    already-recognized Robot-token ``CreateToken`` arm."""
    from mtg_bot.effects.generic import CreateToken
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line(
        "{5}, {T}: Create a 2/2 colorless Robot artifact creature token."
    )
    assert ab is not None
    assert isinstance(ab.effect, CreateToken)
    assert ab.effect.count == 1
    assert ab.effect.token_printing.power == 2
    assert ab.effect.token_printing.toughness == 2
    assert "Robot" in ab.effect.token_printing.subtypes
    # Cost: {5} mana + tap-self.
    assert ab.cost.tap_self is True
    assert ab.cost.mana is not None
    assert ab.cost.mana.generic == 5


# ---------------------------------------------------------------------------
# (4) AA2 (tap-X-artifacts → +X/+0) is the SOLE unparsed ability.
# ---------------------------------------------------------------------------


def test_aa2_tap_x_artifacts_pump_is_unparsed_today():
    """AA2's variable tap-X-artifacts cost + +X/+0 pump has no grammar
    arm — the cost atom ``Tap X untapped artifacts you control`` and the
    cost-determined X-channel are the genuinely-new substrate this card
    is blocked on. The line must NOT parse today (a future parse means
    the substrate landed; update this pin to the byte-equal probe)."""
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line(
        "{2}, {T}, Tap X untapped artifacts you control: Target creature "
        "gets +X/+0 until end of turn. Activate only as a sorcery."
    )
    assert ab is None


# ---------------------------------------------------------------------------
# (5) The live whole-card printing is EMPTY (BLOCKED-SG; not yet PROBED).
# ---------------------------------------------------------------------------


def test_live_printing_is_empty_colorless_land():
    """The live parser claims Secluded Starforge via the colorless-
    utility-land arm and emits an empty land (no produces, no abilities),
    mirroring the static-side ``make_colorless_land`` simplification.
    This is the BLOCKED-SG state; flipping to PROBED requires the AA2
    substrate + a faithful full-3-AA byte-equal probe (see
    ``docs/SEARCH_LIMITATIONS.md``)."""
    from mtg_bot.cards.source import get_active_source

    p = get_active_source().get_printings().get("Secluded Starforge")
    if p is None:
        pytest.skip("Secluded Starforge absent from active CardSource")
    assert "Land" in p.card_types
    assert p.produces == frozenset()
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
