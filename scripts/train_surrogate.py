"""Phase 5 PoC training: best-of-K proposal net + OOD risk head.

Trains one proposal/risk pair per seed on the pilot dataset, saving
checkpoints that carry their full reproduction context (feature ranges fit
on the train split only, dataset manifest SHA, architecture, seed).

Example:
  python scripts/train_surrogate.py --data data/pilot \
      --out models/surrogate/poc --k 5 --seeds 0,1,2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.surrogate import data as sdata
from analog_ai.surrogate import train as strain


def _manifest_sha(data_dir: str) -> str:
    p = os.path.join(data_dir, "manifest.json")
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=os.path.join("data", "pilot"))
    ap.add_argument("--out", default=os.path.join("models", "surrogate", "poc"))
    ap.add_argument("--k", type=int, default=5, help="candidate heads")
    ap.add_argument("--hidden", default="256,256")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=30)
    args = ap.parse_args()
    hidden = tuple(int(h) for h in args.hidden.split(","))
    os.makedirs(args.out, exist_ok=True)

    print(f"Loading dataset {args.data} ...", flush=True)
    requests, designs = sdata.load_dataset(args.data)

    # Feature ranges fit on the TRAIN split only, positives and negatives.
    train_rows = [r for r in requests if r["split"] == "train"
                  and r["design_row_id"] in designs
                  and designs[r["design_row_id"]]["valid"]
                  and sdata.risk_label(r) is not None]
    x_all = sdata.feature_matrix(train_rows)
    feat_lo, feat_hi = sdata.fit_feature_ranges(x_all)
    print(f"train rows: {len(train_rows)}; "
          f"feat ranges: {np.round(feat_lo, 2).tolist()} .. "
          f"{np.round(feat_hi, 2).tolist()}", flush=True)

    x_tr, d_tr, y_tr, _ = sdata.build_split(requests, designs, "train",
                                            feat_lo, feat_hi)
    x_va, d_va, y_va, _ = sdata.build_split(requests, designs, "val",
                                            feat_lo, feat_hi)
    xp_tr, dp_tr, _, _ = sdata.build_split(requests, designs, "train",
                                           feat_lo, feat_hi,
                                           positive_only=True)
    xp_va, dp_va, _, _ = sdata.build_split(requests, designs, "val",
                                           feat_lo, feat_hi,
                                           positive_only=True)
    print(f"proposal: train {len(xp_tr)}, val {len(xp_va)} (positive only); "
          f"risk: train {len(x_tr)}, val {len(x_va)}", flush=True)

    manifest_sha = _manifest_sha(args.data)
    for seed in [int(s) for s in args.seeds.split(",")]:
        t0 = time.time()
        model, hist = strain.train_proposal(
            xp_tr, dp_tr, xp_va, dp_va, seed=seed, k_heads=args.k,
            hidden=hidden, epochs=args.epochs, batch=args.batch, lr=args.lr,
            patience=args.patience)
        risk, rhist = strain.train_risk(x_tr, y_tr, x_va, y_va, seed=seed,
                                        hidden=hidden, epochs=args.epochs,
                                        batch=args.batch, lr=args.lr,
                                        patience=args.patience)
        meta = {
            "k_heads": args.k, "hidden": list(hidden), "seed": seed,
            "feat_lo": feat_lo.tolist(), "feat_hi": feat_hi.tolist(),
            "dataset": args.data, "dataset_manifest_sha": manifest_sha,
            "proposal_best_val": hist["best_val"],
            "proposal_epochs_run": hist["epochs_run"],
            "risk_best_val": rhist["best_val"],
            "pos_train": len(xp_tr), "risk_train": len(x_tr),
        }
        ck_path = os.path.join(args.out, f"seed{seed}.pt")
        strain.save_checkpoint(ck_path, model, risk, meta)
        with open(os.path.join(args.out, f"history_seed{seed}.json"),
                  "w") as f:
            json.dump({"proposal": hist, "risk": rhist}, f, indent=2)
        print(f"[seed {seed}] proposal val loss {hist['best_val']:.5f} "
              f"({hist['epochs_run']} epochs), risk val {rhist['best_val']:.5f}"
              f", {time.time() - t0:.0f}s -> {ck_path}", flush=True)


if __name__ == "__main__":
    main()
