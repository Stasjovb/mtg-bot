"""Tests for ``mtg_bot.training.structured_model``.

Skeleton-level coverage. The model has no engine dependency — every
test builds a random integer + float batch via
``make_dummy_batch`` and confirms:

- forward runs without crashing on representative input shapes,
- output shapes match the documented value / policy / aux-head contracts,
- gradients flow through a representative dummy loss,
- variable-length input with attention masks works (padded rows
  contribute zero gradient w.r.t. embeddings only the padded
  positions touched).
"""

from __future__ import annotations

import pytest
import torch
import torch.nn as nn

from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.structured_model import (
    ACTION_KIND_VOCAB_SIZE,
    CONTROLLER_VOCAB_SIZE,
    EMB_FIELD_PRINTING,
    N_EMB_FIELDS,
    N_SCALAR_FIELDS,
    N_TOKEN_TYPES,
    StructuredModel,
    StructuredModelConfig,
    TARGET_KIND_VOCAB_SIZE,
    VARIANT_VOCAB_SIZE,
    make_dummy_batch,
)


# A small config for fast unit tests. The production scale is set on
# the dataclass defaults; we shrink hyperparams here so the test suite
# doesn't pay the full-model cost.
SMALL_CONFIG = StructuredModelConfig(
    emb_dim=16,
    n_heads=2,
    n_layers=2,
    hidden_dim=32,
    action_history_n=8,
    n_printings=32,
)


# ---------------------------------------------------------------------
# Construction / config
# ---------------------------------------------------------------------


def test_default_config_action_vocab_matches_codec() -> None:
    """The skeleton's policy head must produce exactly
    ``ACTION_VOCAB_SIZE`` logits — the action-encoding codec is the
    source of truth and any drift would silently break the loss."""
    cfg = StructuredModelConfig()
    assert cfg.action_vocab_size == ACTION_VOCAB_SIZE


def test_emb_dim_must_be_divisible_by_n_heads() -> None:
    """Multihead attention requires ``emb_dim % n_heads == 0``. We
    surface the constraint with a useful error rather than the PyTorch
    one (which is less obviously about our config)."""
    bad_cfg = StructuredModelConfig(emb_dim=17, n_heads=4)
    with pytest.raises(ValueError, match="must be divisible"):
        StructuredModel(bad_cfg)


def test_model_constructs_with_default_config() -> None:
    """Default config (production-sized) instantiates without
    blowing up. Doesn't run forward — just confirms parameter
    construction is well-formed for production-default shapes."""
    model = StructuredModel()
    # Spot-check a few load-bearing parameters exist.
    assert model.cls_token.shape == (1, 1, model.config.emb_dim)
    assert model.policy_slot_queries.shape == (
        ACTION_VOCAB_SIZE, model.config.emb_dim,
    )


# ---------------------------------------------------------------------
# Forward pass shape contracts
# ---------------------------------------------------------------------


def test_forward_produces_value_in_tanh_range() -> None:
    """Value head is tanh-activated. The output should lie within
    [-1, +1] for any input."""
    torch.manual_seed(0)
    model = StructuredModel(SMALL_CONFIG)
    model.eval()
    batch = make_dummy_batch(
        batch_size=4, seq_len=12, config=SMALL_CONFIG, seed=42,
    )
    with torch.no_grad():
        out = model(batch)
    assert out["value"].shape == (4,)
    assert torch.all(out["value"] >= -1.0)
    assert torch.all(out["value"] <= 1.0)


def test_forward_policy_logits_shape_matches_vocab() -> None:
    """Policy head emits one logit per action-vocab slot."""
    torch.manual_seed(0)
    model = StructuredModel(SMALL_CONFIG)
    model.eval()
    batch = make_dummy_batch(
        batch_size=3, seq_len=6, config=SMALL_CONFIG, seed=1,
    )
    with torch.no_grad():
        out = model(batch)
    assert out["policy_logits"].shape == (
        3, SMALL_CONFIG.action_vocab_size,
    )


def test_forward_omits_hand_belief_by_default() -> None:
    """The aux-head is off by default (Step 4 lights it up). The
    forward dict should NOT contain ``hand_belief_logits`` so a
    consumer that opts in vs. doesn't never sees a stale tensor."""
    model = StructuredModel(SMALL_CONFIG)
    model.eval()
    batch = make_dummy_batch(
        batch_size=2, seq_len=5, config=SMALL_CONFIG, seed=2,
    )
    with torch.no_grad():
        out = model(batch)
    assert "hand_belief_logits" not in out


def test_forward_emits_hand_belief_when_enabled() -> None:
    """With the aux head enabled, ``hand_belief_logits`` appears
    with one logit per printing in the vocab."""
    cfg = StructuredModelConfig(
        emb_dim=16, n_heads=2, n_layers=2, hidden_dim=32,
        n_printings=32, enable_hand_belief_head=True,
    )
    model = StructuredModel(cfg)
    model.eval()
    batch = make_dummy_batch(
        batch_size=2, seq_len=5, config=cfg, seed=3,
    )
    with torch.no_grad():
        out = model(batch)
    assert out["hand_belief_logits"].shape == (2, cfg.n_printings)


# ---------------------------------------------------------------------
# Gradient flow
# ---------------------------------------------------------------------


def test_gradient_flows_through_dummy_loss() -> None:
    """A simple MSE-on-value + CE-on-policy combined loss produces
    finite gradients on every trainable parameter."""
    torch.manual_seed(0)
    model = StructuredModel(SMALL_CONFIG)
    model.train()
    batch = make_dummy_batch(
        batch_size=4, seq_len=12, config=SMALL_CONFIG, seed=7,
    )
    target_value = torch.rand(4) * 2 - 1
    target_policy = torch.randint(
        0, SMALL_CONFIG.action_vocab_size, (4,),
    )

    out = model(batch)
    value_loss = nn.functional.mse_loss(out["value"], target_value)
    policy_loss = nn.functional.cross_entropy(
        out["policy_logits"], target_policy,
    )
    loss = value_loss + policy_loss
    loss.backward()

    # Every trainable parameter should have a finite gradient. We
    # accept zero gradients on the hand-belief subgraph because the
    # default config keeps that head disabled — but everything else
    # must have nonzero gradient somewhere.
    name_has_grad: dict[str, bool] = {}
    for name, p in model.named_parameters():
        if p.grad is None:
            name_has_grad[name] = False
            continue
        assert torch.isfinite(p.grad).all(), f"non-finite grad in {name}"
        name_has_grad[name] = bool(p.grad.abs().sum() > 0)

    # Trunk + value + policy parameters must receive gradient signal.
    for name, has_grad in name_has_grad.items():
        if name.startswith(("hand_belief_",)):
            continue
        if name.endswith(".weight") or name.endswith(".bias"):
            assert has_grad, f"parameter {name!r} got zero gradient"


def test_gradient_flows_through_hand_belief_head() -> None:
    """When the aux head is on, its parameters get gradient signal
    from a hand-belief BCE loss."""
    torch.manual_seed(0)
    cfg = StructuredModelConfig(
        emb_dim=16, n_heads=2, n_layers=2, hidden_dim=32,
        n_printings=32, enable_hand_belief_head=True,
    )
    model = StructuredModel(cfg)
    model.train()
    batch = make_dummy_batch(
        batch_size=4, seq_len=10, config=cfg, seed=11,
    )
    targets = torch.randint(
        0, 2, (4, cfg.n_printings),
    ).float()
    out = model(batch)
    loss = nn.functional.binary_cross_entropy_with_logits(
        out["hand_belief_logits"], targets,
    )
    loss.backward()
    # hand_belief_queries should have a nonzero gradient.
    assert model.hand_belief_queries.grad is not None
    assert torch.isfinite(model.hand_belief_queries.grad).all()
    assert model.hand_belief_queries.grad.abs().sum() > 0


# ---------------------------------------------------------------------
# Variable-length input + attention mask
# ---------------------------------------------------------------------


def test_variable_length_input_with_padding() -> None:
    """Mixed-length sequences with attention masks should produce
    finite outputs identical to running each row independently at
    its real length.

    The test packs three rows with lengths 1, 4, 7 into a (3, 8)
    batch with masked-padding tails, then re-runs each row alone
    (using its valid prefix only) and compares forward outputs.
    Equality (within a small tolerance) confirms the padding mask
    actually suppresses padded positions.
    """
    torch.manual_seed(0)
    model = StructuredModel(SMALL_CONFIG)
    model.eval()

    seq_len = 8
    pad_lengths = [1, 4, 7]
    batch = make_dummy_batch(
        batch_size=3, seq_len=seq_len, config=SMALL_CONFIG,
        pad_lengths=pad_lengths, seed=99,
    )

    with torch.no_grad():
        packed_out = model(batch)

    # Re-run each row independently, sliced to its valid prefix.
    per_row_values: list[float] = []
    per_row_logits: list[torch.Tensor] = []
    for row_idx, length in enumerate(pad_lengths):
        # ``make_dummy_batch`` already guards against zero-length
        # rows. The slice still respects whatever it produced.
        eff_length = int(batch["attention_mask"][row_idx].sum().item())
        single_batch = {
            "token_type": batch["token_type"][row_idx : row_idx + 1, :eff_length],
            "token_emb_ids": batch["token_emb_ids"][
                row_idx : row_idx + 1, :eff_length, :
            ],
            "token_scalars": batch["token_scalars"][
                row_idx : row_idx + 1, :eff_length, :
            ],
            "attention_mask": torch.ones(
                (1, eff_length), dtype=torch.bool,
            ),
        }
        with torch.no_grad():
            single_out = model(single_batch)
        per_row_values.append(single_out["value"].item())
        per_row_logits.append(single_out["policy_logits"][0])

    packed_values = packed_out["value"].tolist()
    for got, expected in zip(packed_values, per_row_values):
        assert got == pytest.approx(expected, abs=1e-4), (
            f"value mismatch: packed={got} single={expected}"
        )
    for row_idx, expected in enumerate(per_row_logits):
        assert torch.allclose(
            packed_out["policy_logits"][row_idx], expected, atol=1e-4,
        ), f"policy logits mismatch on row {row_idx}"


def test_fully_padded_row_does_not_crash() -> None:
    """If a row ends up with only its CLS token valid (everything
    else masked), forward must still produce a finite result. The
    CLS row stays valid because ``_prepend_cls`` adds a True mask
    entry up front."""
    torch.manual_seed(0)
    model = StructuredModel(SMALL_CONFIG)
    model.eval()
    # Construct manually so we can force a fully-padded body row.
    batch = make_dummy_batch(
        batch_size=2, seq_len=4, config=SMALL_CONFIG, seed=5,
        # ``make_dummy_batch`` forces at least one valid position per
        # row — set length=1 to keep one token visible. The CLS prefix
        # adds another, so the trunk sees a 2-valid + 3-padded sequence.
        pad_lengths=[1, 4],
    )
    with torch.no_grad():
        out = model(batch)
    assert torch.isfinite(out["value"]).all()
    assert torch.isfinite(out["policy_logits"]).all()


# ---------------------------------------------------------------------
# make_dummy_batch sanity
# ---------------------------------------------------------------------


def test_make_dummy_batch_shapes() -> None:
    """The helper produces tensors with the documented shapes
    and dtypes."""
    batch = make_dummy_batch(
        batch_size=3, seq_len=5, config=SMALL_CONFIG, seed=0,
    )
    assert batch["token_type"].shape == (3, 5)
    assert batch["token_type"].dtype == torch.long
    assert batch["token_emb_ids"].shape == (3, 5, N_EMB_FIELDS)
    assert batch["token_emb_ids"].dtype == torch.long
    # Width follows the config's scalar schema (v2 by default).
    assert batch["token_scalars"].shape == (3, 5, SMALL_CONFIG.scalar_width)
    assert batch["token_scalars"].dtype == torch.float32
    assert batch["attention_mask"].shape == (3, 5)
    assert batch["attention_mask"].dtype == torch.bool


def test_make_dummy_batch_pad_lengths_validation() -> None:
    """Bad ``pad_lengths`` arguments fail fast with ValueError."""
    with pytest.raises(ValueError, match="pad_lengths must be length"):
        make_dummy_batch(
            batch_size=2, seq_len=4, config=SMALL_CONFIG,
            pad_lengths=[1],  # wrong length
        )
    with pytest.raises(ValueError, match="outside"):
        make_dummy_batch(
            batch_size=2, seq_len=4, config=SMALL_CONFIG,
            pad_lengths=[1, 5],  # 5 > seq_len=4
        )
    with pytest.raises(ValueError, match="outside"):
        make_dummy_batch(
            batch_size=2, seq_len=4, config=SMALL_CONFIG,
            pad_lengths=[1, -1],
        )


def test_make_dummy_batch_respects_vocab_caps() -> None:
    """Every integer field must be inside its embedding's vocab. A
    drift here would silently push an out-of-range id past
    ``padding_idx=0`` and break gradient flow."""
    batch = make_dummy_batch(
        batch_size=5, seq_len=7, config=SMALL_CONFIG, seed=4,
    )
    ids = batch["token_emb_ids"]
    assert ids[..., 0].max() < SMALL_CONFIG.n_printings
    assert ids[..., 1].max() < ACTION_KIND_VOCAB_SIZE
    assert ids[..., 2].max() < CONTROLLER_VOCAB_SIZE
    assert ids[..., 3].max() < SMALL_CONFIG.n_printings
    assert ids[..., 4].max() < TARGET_KIND_VOCAB_SIZE
    assert ids[..., 5].max() < VARIANT_VOCAB_SIZE
    # Step field is independently bounded by STEP_VOCAB_SIZE = 13.
    assert ids[..., 6].max() < 13
    assert batch["token_type"].max() < N_TOKEN_TYPES


def test_make_dummy_batch_pad_zero_length_safeguard() -> None:
    """If a caller passes pad_lengths=[0, ...] the helper must
    backfill at least one valid position so attention layers
    don't see a fully-padded row (which yields NaN inside
    MultiheadAttention)."""
    batch = make_dummy_batch(
        batch_size=2, seq_len=4, config=SMALL_CONFIG,
        pad_lengths=[0, 2], seed=7,
    )
    # Even though length=0 was requested, at least one position
    # should be valid in the first row.
    assert batch["attention_mask"][0].sum() >= 1


def test_make_dummy_batch_respects_device() -> None:
    """When ``device`` is provided, every output tensor lives on
    that device. We use the CPU device for the test (works on any
    host); the code path itself is what we need to exercise so the
    GPU path doesn't carry untested branches."""
    cpu = torch.device("cpu")
    batch = make_dummy_batch(
        batch_size=2, seq_len=3, config=SMALL_CONFIG,
        device=cpu, seed=8,
    )
    for value in batch.values():
        assert value.device == cpu


def test_printing_padding_idx_yields_zero_embedding() -> None:
    """``padding_idx=0`` on the printing table guarantees the NA
    printing maps to the zero vector. The model relies on this
    invariant for "no source printing" tokens."""
    model = StructuredModel(SMALL_CONFIG)
    e = model.printing_embed(torch.tensor([0]))
    assert torch.all(e == 0)


# ---------------------------------------------------------------------
# Scalar schema versions: projection width + forward on both widths
# ---------------------------------------------------------------------


def _cfg_for_schema(version: int) -> StructuredModelConfig:
    return StructuredModelConfig(
        emb_dim=SMALL_CONFIG.emb_dim, n_heads=SMALL_CONFIG.n_heads,
        n_layers=SMALL_CONFIG.n_layers, hidden_dim=SMALL_CONFIG.hidden_dim,
        n_printings=SMALL_CONFIG.n_printings,
        scalar_schema_version=version,
    )


def test_scalar_width_for_schema_constants() -> None:
    from mtg_bot.training.structured_model import (
        DEFAULT_SCALAR_SCHEMA_VERSION, N_SCALAR_FIELDS_V2,
        SUPPORTED_SCALAR_SCHEMA_VERSIONS, scalar_width_for_schema,
    )
    assert scalar_width_for_schema(1) == N_SCALAR_FIELDS == 3
    assert scalar_width_for_schema(2) == N_SCALAR_FIELDS_V2
    assert N_SCALAR_FIELDS_V2 > N_SCALAR_FIELDS
    assert DEFAULT_SCALAR_SCHEMA_VERSION == 2
    assert SUPPORTED_SCALAR_SCHEMA_VERSIONS == (1, 2)
    with pytest.raises(ValueError, match="scalar_schema_version"):
        scalar_width_for_schema(3)


def test_v2_slot_indices_are_unique_and_cover_the_row() -> None:
    """Every SCALAR_FIELD_* constant claims a distinct slot and the
    v2 width is exactly the number of slots (no gaps, no overlap)."""
    import mtg_bot.training.structured_model as sm
    slots = {
        name: getattr(sm, name)
        for name in dir(sm) if name.startswith("SCALAR_FIELD_")
    }
    values = sorted(slots.values())
    assert values == list(range(sm.N_SCALAR_FIELDS_V2)), slots
    # v1 slots are the first three.
    assert sm.SCALAR_FIELD_TURN_OFFSET == 0
    assert sm.SCALAR_FIELD_MANA_COST_PAID == 1
    assert sm.SCALAR_FIELD_PUBLIC_MASK == 2


def test_config_default_schema_is_v2_and_width_property() -> None:
    from mtg_bot.training.structured_model import N_SCALAR_FIELDS_V2
    cfg = StructuredModelConfig()
    assert cfg.scalar_schema_version == 2
    assert cfg.scalar_width == N_SCALAR_FIELDS_V2
    assert _cfg_for_schema(1).scalar_width == 3
    with pytest.raises(ValueError, match="scalar_schema_version"):
        StructuredModelConfig(scalar_schema_version=7)


@pytest.mark.parametrize("version", [1, 2])
def test_scalar_proj_width_follows_schema(version: int) -> None:
    from mtg_bot.training.structured_model import scalar_width_for_schema
    model = StructuredModel(_cfg_for_schema(version))
    assert model.scalar_proj.in_features == scalar_width_for_schema(version)


@pytest.mark.parametrize("version", [1, 2])
def test_forward_works_for_each_schema_width(version: int) -> None:
    cfg = _cfg_for_schema(version)
    model = StructuredModel(cfg)
    model.eval()
    batch = make_dummy_batch(batch_size=2, seq_len=6, config=cfg, seed=1)
    assert batch["token_scalars"].shape[-1] == cfg.scalar_width
    with torch.no_grad():
        out = model(batch)
    assert out["value"].shape == (2,)
    assert out["policy_logits"].shape == (2, cfg.action_vocab_size)
    assert torch.isfinite(out["value"]).all()


def test_forward_rejects_mismatched_scalar_width() -> None:
    cfg_v2 = _cfg_for_schema(2)
    model = StructuredModel(cfg_v2)
    batch_v1 = make_dummy_batch(
        batch_size=2, seq_len=4, config=_cfg_for_schema(1), seed=0,
    )
    with pytest.raises(ValueError, match="scalar schema"):
        model(batch_v1)


def test_v1_and_v2_models_have_different_state_dict_shapes() -> None:
    """A v2 checkpoint can't be silently loaded into a v1 model (and
    vice versa) — the projection weight shapes differ."""
    m1 = StructuredModel(_cfg_for_schema(1))
    m2 = StructuredModel(_cfg_for_schema(2))
    with pytest.raises(RuntimeError, match="size mismatch"):
        m1.load_state_dict(m2.state_dict())
