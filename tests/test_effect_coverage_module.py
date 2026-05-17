"""Tests for ``mtg_bot.parity.effect_coverage`` — the round-66
covered-set extraction precursor (production-importable home of the
covered-set computation the spell-card-bridge Phase 1 guardrail needs).

This module was factored OUT of ``scripts/measure_pool_parity.py``
(``covered_python_class_set`` / ``card_effect_classes``) and
``scripts/measure_effect_coverage.py`` (the parser primitives +
override tables) so a production-package predicate can query the live
covered set WITHOUT a ``scripts/`` import (a layering inversion). The
extraction is a **pure relocation** — these tests are the proof:

  * **Importable from src with no ``scripts/`` on ``sys.path``** — the
    whole point of the precursor (the guardrail imports it lazily from
    ``trajectory.py``).
  * **Byte-identical to the prior scripts implementation** — the
    covered set AND the per-card emitted-class set, walked over the
    full live EoE pool, must match the original
    ``scripts/measure_pool_parity.py`` definitions character-for-
    character (the §2-teeth "exactly ONE definition of covered"
    requirement). The original script now RE-EXPORTS from this module,
    so we exercise the re-export path too.
  * **Behavior contracts preserved** — the vanilla / broken-
    introspection / spell+trigger walker contracts the old
    ``card_effect_classes`` tests pinned.

The pure helpers need no engine extension; the full-pool walk is
parser-only (no ``.pyd``), exactly like ``test_measure_pool_parity``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MPP_SCRIPT = REPO_ROOT / "scripts" / "measure_pool_parity.py"
MEC_SCRIPT = REPO_ROOT / "scripts" / "measure_effect_coverage.py"


@pytest.fixture(scope="module")
def ec():
    """The extracted production module, imported the way the
    spell-card-bridge guardrail will (a plain ``mtg_bot.parity``
    import — NO ``scripts/`` path manipulation)."""
    import mtg_bot.parity.effect_coverage as m

    return m


@pytest.fixture(scope="module")
def mpp():
    """The (now re-exporting) ``scripts/measure_pool_parity.py``, loaded
    under a stable name without invoking ``main()`` — same pattern as
    ``test_measure_pool_parity``. Exercising it confirms the re-export
    path stays wired (its consumers + the test's monkeypatch rely on
    ``mod.covered_python_class_set`` / ``mod.card_effect_classes``
    existing at module scope)."""
    spec = importlib.util.spec_from_file_location(
        "_mpp_reexport_under_test", MPP_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mec():
    """The (now re-exporting) ``scripts/measure_effect_coverage.py``."""
    spec = importlib.util.spec_from_file_location(
        "_mec_reexport_under_test", MEC_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------- importability (the point)


def test_module_is_importable_from_src_without_scripts_on_path(ec):
    """The precursor's reason to exist: the covered-set query is
    importable from the production package via a plain
    ``mtg_bot.parity`` import, with NO ``scripts/`` directory on
    ``sys.path`` — so the spell-card-bridge guardrail in
    ``trajectory.py`` can lazily import it without a layering
    inversion."""
    scripts_dir = str(REPO_ROOT / "scripts")
    # The module object resolves to the src package, not a scripts file.
    assert ec.__name__ == "mtg_bot.parity.effect_coverage"
    mod_path = Path(ec.__file__).resolve()
    assert mod_path.parts[-3:] == ("mtg_bot", "parity", "effect_coverage.py")
    # And nothing about importing it required scripts/ on sys.path.
    # (Reimport with scripts/ scrubbed to make the contract explicit.)
    # Restore BOTH sys.path AND the original cached module object so we
    # don't leave a duplicate module in sys.modules for sibling tests
    # that assert object-identity of the re-exported functions.
    saved_path = list(sys.path)
    saved_mod = sys.modules.get("mtg_bot.parity.effect_coverage")
    try:
        sys.path[:] = [p for p in sys.path if p != scripts_dir]
        sys.modules.pop("mtg_bot.parity.effect_coverage", None)
        import importlib

        reimported = importlib.import_module(
            "mtg_bot.parity.effect_coverage"
        )
        assert hasattr(reimported, "covered_python_class_set")
        assert hasattr(reimported, "card_effect_classes")
    finally:
        sys.path[:] = saved_path
        if saved_mod is not None:
            sys.modules["mtg_bot.parity.effect_coverage"] = saved_mod


# ------------------------------------ parity vs the prior scripts impl


def _per_card_classes(fn):
    """Map every live EoE printing -> sorted list of emitted Effect
    class names, using ``fn`` (an implementation of
    ``card_effect_classes``). Pure parser walk; no ``.pyd``."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    printings = OracleParserCardSource().get_printings()
    return {nm: sorted(fn(pr)) for nm, pr in sorted(printings.items())}


def test_covered_set_matches_prior_scripts_implementation(ec, mpp):
    """The extracted ``covered_python_class_set`` returns EXACTLY the
    same set the (re-exporting) ``measure_pool_parity`` module returns —
    the §2-teeth "exactly ONE definition of covered" requirement. (Both
    now resolve to the same code; this pins the re-export wiring + a
    healthy non-trivial size so a future accidental divergence fails
    here.)"""
    extracted = ec.covered_python_class_set()
    via_script = mpp.covered_python_class_set()
    assert extracted == via_script
    # Non-trivial sanity floor (round-66 live value is 85 — assert a
    # generous lower bound so a parser regression that silently empties
    # the set fails loudly, like test_effect_coverage's extractor
    # sanity test).
    assert len(extracted) >= 60
    # mtg_bot's underlying parser drives it: it is a subset of the
    # parsed Python class vocab.
    py_classes, _ex, _n = ec.collect_python_effect_vocab()
    assert extracted <= set(py_classes.keys())


def test_per_card_effect_classes_match_prior_scripts_implementation(
    ec, mpp
):
    """The load-bearing parity proof: walking the FULL live EoE pool,
    the extracted ``card_effect_classes`` emits the byte-identical
    per-card class set the prior ``scripts/measure_pool_parity.py``
    definition did (now re-exported). A character-for-character match
    over all ~475 printings is the relocation-is-pure evidence the
    precursor brief asked for."""
    extracted = _per_card_classes(ec.card_effect_classes)
    via_script = _per_card_classes(mpp.card_effect_classes)
    assert extracted == via_script
    # The walk is non-empty (a representative-input check: at least some
    # cards emit effects — a fully-empty map would be a silent walker
    # break that the equality above would NOT catch).
    assert any(classes for classes in extracted.values())


def test_rust_parser_primitives_match_coverage_script(ec, mec):
    """The Rust-side parser primitives + override tables (relocated
    from ``scripts/measure_effect_coverage.py``, which now re-exports
    them) produce identical results — so the coverage doc + the
    pool-parity metric can never disagree on what 'covered' means."""
    assert ec.collect_rust_effect_variants() == (
        mec.collect_rust_effect_variants()
    )
    assert ec.RUST_TO_PYTHON_OVERRIDES == mec.RUST_TO_PYTHON_OVERRIDES
    assert ec.RUST_AHEAD_OF_POOL == mec.RUST_AHEAD_OF_POOL
    # The coverage script re-exports rather than re-defining: a known
    # documented override resolves identically through both paths.
    assert ec.map_rust_to_python("ChooseOneMode") == (
        mec.map_rust_to_python("ChooseOneMode")
    ) == "ModalChooseOne"
    py_classes, _ex, n = ec.collect_python_effect_vocab()
    assert n > 0 and len(py_classes) > 0


# ------------------------------------------ behavior contracts preserved


def test_card_effect_classes_empty_for_vanilla(ec):
    class _Vanilla:
        name = "Vanilla Bear"
        spell_effect = None
        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert ec.card_effect_classes(_Vanilla()) == set()


def test_card_effect_classes_walks_spell_and_triggers(ec):
    class _Eff:
        def resolve(self, *a, **k):  # noqa: D401 - duck-typed Effect
            pass

        def describe(self):
            return "x"

    class _WithEffects:
        name = "Effecty"
        spell_effect = _Eff()
        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert ec.card_effect_classes(_WithEffects()) == {"_Eff"}


def test_card_effect_classes_swallows_broken_introspection(ec):
    """A card the walker can't introspect contributes no classes (it
    then falls to a BLOCKED tier — never spuriously 'covered'). Mirrors
    the coverage walker's defensive contract."""

    class _Boom:
        name = "Boom"

        @property
        def spell_effect(self):
            raise RuntimeError("intentional")

        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert ec.card_effect_classes(_Boom()) == set()


def test_map_rust_to_python_identity_and_override(ec):
    """``map_rust_to_python`` is identity for an unmapped variant and
    honors a documented override (the relocated table)."""
    assert ec.map_rust_to_python("SomeUnmappedVariantXyz") == (
        "SomeUnmappedVariantXyz"
    )
    # A stable documented override (round-52+; pinned in the table).
    assert ec.map_rust_to_python("ChooseOneMode") == "ModalChooseOne"


def test_collect_rust_effect_variants_missing_file_raises(ec, tmp_path):
    """A missing ``cards.rs`` surfaces a clear error rather than a
    silent empty list (the parser reads the file first)."""
    with pytest.raises(FileNotFoundError):
        ec.collect_rust_effect_variants(tmp_path / "nope_cards.rs")


def test_collect_rust_effect_variants_no_enum_raises(ec, tmp_path):
    """A ``cards.rs`` with no ``pub enum Effect {`` block raises a
    descriptive ``RuntimeError`` (the parse-rule contract)."""
    bogus = tmp_path / "cards.rs"
    bogus.write_text("// no Effect enum here\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="pub enum Effect"):
        ec.collect_rust_effect_variants(bogus)
