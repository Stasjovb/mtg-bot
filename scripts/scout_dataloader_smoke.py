"""Smoke test: does DataLoader(num_workers=2) work on a small
StructuredDataset on Windows? Tells us whether share_memory_() is
sufficient to avoid the [Errno 22] pipe-pickle crash."""
import numpy as np
from torch.utils.data import DataLoader
from mtg_bot.training.structured_dataset import StructuredDataset, structured_collate
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.structured_model import N_EMB_FIELDS, N_SCALAR_FIELDS

n = 1000
max_len = 50
rng = np.random.default_rng(0)
tt = rng.integers(1, 10, (n, max_len), dtype=np.int64)
emb = rng.integers(0, 5, (n, max_len, N_EMB_FIELDS), dtype=np.int64)
sca = rng.standard_normal((n, max_len, N_SCALAR_FIELDS)).astype(np.float32)
mask = np.ones((n, max_len), dtype=bool)
outcomes = rng.choice([-1.0, 0.0, 1.0], n).astype(np.float32)
pol = rng.random((n, ACTION_VOCAB_SIZE)).astype(np.float32)
am = rng.random((n, ACTION_VOCAB_SIZE)) > 0.5

ds = StructuredDataset(
    token_type=tt, token_emb_ids=emb, token_scalars=sca,
    attention_mask=mask, outcomes=outcomes, policy_targets=pol, action_masks=am,
)
print(f"dataset size: {len(ds)}")
print(f"memmap_dir: {ds._memmap_dir}")
import pickle as _pickle
print(f"pickle size: {len(_pickle.dumps(ds, protocol=4))} bytes")

if __name__ == "__main__":
    print("Trying num_workers=2 + persistent_workers=True...")
    loader = DataLoader(
        ds, batch_size=16, num_workers=2,
        persistent_workers=True,
        collate_fn=structured_collate,
    )
    for i, batch in enumerate(loader):
        print(f"  batch {i}: token_type shape {batch['token_type'].shape}")
        if i >= 2:
            break
    print("OK — num_workers=2 works on small dataset")
