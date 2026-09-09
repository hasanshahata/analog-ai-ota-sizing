"""Dataset loading, joins, and normalization for the surrogate models.

Normalization rules (frozen into every checkpoint):
- request features: [Gain_min, log10 GBW_min, log10 CL_pF, log10 Power_max],
  min-max scaled with ranges fit on the TRAIN split only (a small pad keeps
  val/test points inside [0, 1] instead of clipping information away);
- design targets: min-max scaled by `config.DESIGN_BOUNDS` — the contract, so
  a sigmoid output unit maps exactly onto the legal design domain.
"""

from __future__ import annotations

import numpy as np

from .. import config
from ..dataset.io import rows_of

FEATURES = ("req_Gain_min", "req_GBW_min", "req_CL_pF", "req_Power_max")
LOG_FEATURES = ("req_GBW_min", "req_CL_pF", "req_Power_max")
TARGETS = ("L1", "gmid1", "L3", "gmid3", "Itail")

POSITIVE_LABELS = ("feasible", "near_boundary")
RISK_EXCLUDED = ("polish_failed",)  # ambiguous: derived-feasible but DE missed


def feature_matrix(request_rows: list[dict]) -> np.ndarray:
    cols = []
    for name in FEATURES:
        v = np.array([float(r[name]) for r in request_rows], dtype=np.float64)
        if name in LOG_FEATURES:
            v = np.log10(np.maximum(v, 1e-12))
        cols.append(v)
    return np.stack(cols, axis=1)


def fit_feature_ranges(x_train: np.ndarray, pad: float = 0.05) -> tuple:
    lo = x_train.min(axis=0)
    hi = x_train.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    return lo - pad * span, hi + pad * span


def normalize(x: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return (x - lo) / (hi - lo)


def denormalize(n: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return n * (hi - lo) + lo


def denormalize_features(n: np.ndarray, lo: np.ndarray,
                         hi: np.ndarray) -> np.ndarray:
    """Inverse of normalize + log10 for the log features -> physical units."""
    x = denormalize(n, lo, hi)
    x = x.copy()
    for j, name in enumerate(FEATURES):
        if name in LOG_FEATURES:
            x[:, j] = 10.0 ** x[:, j]
    return x


_DESIGN_LO = np.array([b[0] for b in config.DESIGN_BOUNDS])
_DESIGN_HI = np.array([b[1] for b in config.DESIGN_BOUNDS])


def normalize_designs(d: np.ndarray) -> np.ndarray:
    return (d - _DESIGN_LO) / (_DESIGN_HI - _DESIGN_LO)


def denormalize_designs(n: np.ndarray) -> np.ndarray:
    return n * (_DESIGN_HI - _DESIGN_LO) + _DESIGN_LO


def load_dataset(data_dir: str):
    """(request_rows, {design_row_id: design_row}).

    Prefers the consolidated parquet files (requests carry their assigned
    split there; shards keep split=None by design) and falls back to shards.
    """
    import os

    import pyarrow.parquet as pq

    requests_path = os.path.join(data_dir, "requests.parquet")
    designs_path = os.path.join(data_dir, "designs.parquet")
    if os.path.exists(requests_path):
        requests = pq.read_table(requests_path).to_pylist()
    else:
        requests = rows_of(data_dir, "request")
    if os.path.exists(designs_path):
        design_rows = pq.read_table(designs_path).to_pylist()
    else:
        design_rows = rows_of(data_dir, "design")
    designs = {r["row_id"]: r for r in design_rows}
    return requests, designs


def risk_label(row: dict) -> int | None:
    """1 = achievable-looking request, 0 = negative evidence, None = skip."""
    if row["label"] in RISK_EXCLUDED:
        return None
    return 1 if row["label"] in POSITIVE_LABELS else 0


def build_split(requests: list[dict], designs: dict, split: str,
                feat_lo: np.ndarray, feat_hi: np.ndarray,
                positive_only: bool = False):
    """Tensors for one split: (X_n [N,4], D_n [N,5], risk y [N], rows).

    Keeps only request rows whose design row exists and evaluated valid.
    `positive_only` restricts to feasible/near-boundary rows — the proposal
    regressor trains only on designs that actually satisfy their request;
    negative rows are the risk head's data, never its regression targets.
    """
    rows = [r for r in requests
            if r["split"] == split
            and r["design_row_id"] in designs
            and designs[r["design_row_id"]]["valid"]]
    if positive_only:
        rows = [r for r in rows if r["label"] in POSITIVE_LABELS]
    if not rows:
        empty = lambda n: np.zeros((0, n))  # noqa: E731
        return empty(4), empty(5), np.zeros(0), []
    x = normalize(feature_matrix(rows), feat_lo, feat_hi)
    d = normalize_designs(design_matrix([designs[r["design_row_id"]]
                                         for r in rows]))
    y = np.array([risk_label(r) for r in rows], dtype=np.float64)
    keep = np.array([v is not None for v in
                     (risk_label(r) for r in rows)])
    return (x.astype(np.float32), d.astype(np.float32),
            y[keep].astype(np.float32), [r for r, k in zip(rows, keep) if k])


def design_matrix(design_rows: list[dict]) -> np.ndarray:
    for row in design_rows:
        if (row.get("tail_device") == "finite" or
                "finite" in str(row.get("schema_version", "")) or
                "L5" in row or "gmid5" in row):
            raise ValueError(
                "five-output surrogate data cannot consume finite seven-field designs")
    return np.array([[float(r[t]) for t in TARGETS] for r in design_rows],
                    dtype=np.float64)
