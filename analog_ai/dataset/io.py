"""Parquet persistence for the Phase 3 dataset.

Layout of a dataset directory (`data/<name>/`):

    design_shards/   shard_00000.parquet ...   (append-only, resumable)
    request_shards/  shard_00000.parquet ...
    designs.parquet      <- written by `finalize`
    requests.parquet     <- written by `finalize` (with splits)
    manifest.json        <- seed, versions, counts, region map, checksums

Consumers read the consolidated files; the builder appends shards so an
interrupted run never loses completed work.
"""

from __future__ import annotations

import hashlib
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq

from .. import ORACLE_VERSION, __version__
from .build import METRIC_COLS, RESIDUAL_COLS

_F, _I, _B, _S = "f8", "i8", "bool", "str"

DESIGN_SCHEMA: dict[str, str] = {
    "row_id": _S, "source": _S, "cl_pf": _F,
    "L1": _F, "gmid1": _F, "L3": _F, "gmid3": _F, "Itail": _F,
    **{k: _F for k in METRIC_COLS},
    "W1": _F, "W3": _F,
    **{k: _F for k in RESIDUAL_COLS},
    "verdict": _B, "valid": _B,
    "invalid_reason": _S, "warnings": _S,
    "op_point": _S, "build_id": _S,
}

REQUEST_SCHEMA: dict[str, str] = {
    "row_id": _S, "design_row_id": _S, "source": _S, "label": _S,
    "req_Gain_min": _F, "req_GBW_min": _F, "req_CL_pF": _F,
    "req_Power_max": _F, "infeasible_dim": _S,
    **{k: _F for k in RESIDUAL_COLS},
    "worst_violation": _F, "verdict": _B, "split": _S,
    "de_objective": _F, "de_n_evals": _I, "de_runtime_s": _F,
    "cl_pf": _F, "op_point": _S, "build_id": _S,
}

_PA = {_F: pa.float64(), _I: pa.int64(), _B: pa.bool_(), _S: pa.string()}


def _arrow_schema(schema: dict[str, str]) -> pa.Schema:
    return pa.schema([(name, _PA[kind]) for name, kind in schema.items()])


def _shard_dir(out_dir: str, table: str) -> str:
    return os.path.join(out_dir, f"{table}_shards")


def append_rows(out_dir: str, table: str, rows: list[dict]) -> str:
    """Write one shard file; returns its path. Rows follow the table schema."""
    schema = DESIGN_SCHEMA if table == "design" else REQUEST_SCHEMA
    columns = {}
    for name, kind in schema.items():
        col = [r.get(name) for r in rows]
        if kind == _F:
            col = [None if v is None else float(v) for v in col]
        elif kind == _I:
            col = [None if v is None else int(v) for v in col]
        elif kind == _B:
            col = [None if v is None else bool(v) for v in col]
        else:
            col = [None if v is None else str(v) for v in col]
        columns[name] = pa.array(col, type=_PA[kind])
    t = pa.table(columns, schema=_arrow_schema(schema))

    d = _shard_dir(out_dir, table)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"shard_{len(os.listdir(d)):05d}.parquet")
    pq.write_table(t, path)
    return path


def read_table(out_dir: str, table: str) -> pa.Table | None:
    """Concatenate all shards of a table; None if nothing written yet."""
    d = _shard_dir(out_dir, table)
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.endswith(".parquet"))
    if not files:
        return None
    return pa.concat_tables(
        [pq.read_table(os.path.join(d, f)) for f in files])


def rows_of(out_dir: str, table: str) -> list[dict]:
    t = read_table(out_dir, table)
    return t.to_pylist() if t is not None else []


# ------------------------------------------------------------ finalize ----
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def finalize(out_dir: str, seed: int, config_summary: dict,
             request_rows: list[dict] | None = None,
             split_map: dict | None = None,
             lut_hashes: dict | None = None) -> dict:
    """Write consolidated designs/requests parquet + manifest; returns it.

    `request_rows` (e.g. split-assigned by `splits.assign_splits_by_design`)
    overrides the shard contents for the consolidated requests file; shards
    keep `split=None` by design. `lut_hashes` ({"nch": sha, "pch": sha})
    pins the source LUTs into the manifest.
    """
    t = read_table(out_dir, "design")
    if t is not None:
        pq.write_table(t, os.path.join(out_dir, "designs.parquet"))
    requests = request_rows if request_rows is not None \
        else rows_of(out_dir, "request")
    if requests:
        schema = _arrow_schema(REQUEST_SCHEMA)
        columns = {}
        for name, kind in REQUEST_SCHEMA.items():
            col = [r.get(name) for r in requests]
            if kind == _F:
                col = [None if v is None else float(v) for v in col]
            elif kind == _I:
                col = [None if v is None else int(v) for v in col]
            elif kind == _B:
                col = [None if v is None else bool(v) for v in col]
            else:
                col = [None if v is None else str(v) for v in col]
            columns[name] = pa.array(col, type=_PA[kind])
        pq.write_table(pa.table(columns, schema=schema),
                       os.path.join(out_dir, "requests.parquet"))
    counts = {"by_label": {}, "by_split": {}, "by_source": {}}
    for r in requests:
        counts["by_label"][r["label"]] = counts["by_label"].get(r["label"], 0) + 1
        counts["by_split"][r["split"]] = counts["by_split"].get(r["split"], 0) + 1
        counts["by_source"][r["source"]] = counts["by_source"].get(r["source"], 0) + 1
    designs = rows_of(out_dir, "design")
    counts["by_source_design"] = {}
    for r in designs:
        counts["by_source_design"][r["source"]] = \
            counts["by_source_design"].get(r["source"], 0) + 1
    counts["design_rows"] = len(designs)
    counts["request_rows"] = len(requests)

    manifest = {
        "oracle_version": ORACLE_VERSION,
        "package_version": __version__,
        "dataset_seed": seed,
        "label_schema": "v2",       # evidence-based negative labels
        "split_rule": "by_design_group_v2",
        "config": config_summary,
        "counts": counts,
        "split_map": {str(k): v for k, v in (split_map or {}).items()},
        "lut_sha256": lut_hashes or {},
        "files": {},
    }
    for name in ("designs.parquet", "requests.parquet"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            manifest["files"][name] = {"sha256": _sha256(p),
                                       "bytes": os.path.getsize(p)}
    import sys
    manifest["environment"] = {
        "python": sys.version.split()[0],
        "numpy": __import__("numpy").__version__,
        "scipy": __import__("scipy").__version__,
        "pyarrow": __import__("pyarrow").__version__,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, default=str)
    return manifest
