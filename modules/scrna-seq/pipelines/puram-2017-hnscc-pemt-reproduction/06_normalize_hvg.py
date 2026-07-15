#!/usr/bin/env python
"""06_normalize_hvg.py

Stage [normalize]: Normalization and HVG selection.

Reads adata_qc.h5ad, performs normalize_total + log1p, then selects
highly variable genes with the seurat_v3 flavor (which requires raw
count-like data). Writes adata_norm.h5ad.

Idempotent: skips work if the output already exists and is valid.
"""

import os
import sys

import numpy as np
import scanpy as sc


def results_dir() -> str:
    d = os.environ.get("GHBIO_RESULTS")
    if not d:
        d = os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
    os.makedirs(d, exist_ok=True)
    return d


def main() -> int:
    RESULTS = results_dir()

    in_path = os.path.join(RESULTS, "adata_qc.h5ad")
    out_path = os.path.join(RESULTS, "adata_norm.h5ad")

    # Idempotency: if output exists and loads, skip.
    if os.path.exists(out_path):
        try:
            _ = sc.read_h5ad(out_path)
            print(f"[06_normalize_hvg] Output already exists, skipping: {out_path}")
            return 0
        except Exception as e:
            print(f"[06_normalize_hvg] Existing output unreadable ({e}); regenerating.")

    if not os.path.exists(in_path):
        print(
            f"[06_normalize_hvg] ERROR: required input not found: {in_path}\n"
            "Run 05_qc.py first.",
            file=sys.stderr,
        )
        return 1

    print(f"[06_normalize_hvg] Reading {in_path}")
    adata = sc.read_h5ad(in_path)

    # seurat_v3 flavor expects count-like (raw) data. Our build_adata step
    # produced pseudo-counts via X = round(10*(2**logTPM - 1)); QC keeps X
    # on that scale. Preserve those counts for seurat_v3 HVG selection.
    # Store raw counts in a dedicated layer before normalization.
    if "counts" not in adata.layers:
        adata.layers["counts"] = adata.X.copy()

    # Number of HVGs to select.
    n_top_genes = 2000  # TODO: 확인 필요

    # --- HVG selection (seurat_v3) uses the raw count layer ---
    print(f"[06_normalize_hvg] Selecting {n_top_genes} HVGs (flavor=seurat_v3)")
    try:
        sc.pp.highly_variable_genes(
            adata,
            flavor="seurat_v3",
            n_top_genes=n_top_genes,
            layer="counts",
        )
    except Exception as e:
        # seurat_v3 requires integer-like counts; fall back gracefully.
        print(
            f"[06_normalize_hvg] seurat_v3 HVG failed ({e}); "
            "falling back to rounding counts.",
            file=sys.stderr,
        )
        cnt = adata.layers["counts"]
        cnt = np.rint(cnt.toarray()) if hasattr(cnt, "toarray") else np.rint(cnt)
        adata.layers["counts"] = cnt
        sc.pp.highly_variable_genes(
            adata,
            flavor="seurat_v3",
            n_top_genes=n_top_genes,
            layer="counts",
        )

    n_hvg = int(adata.var["highly_variable"].sum())
    print(f"[06_normalize_hvg] Selected {n_hvg} highly variable genes")

    # --- Normalization: normalize_total + log1p on X ---
    print("[06_normalize_hvg] normalize_total(target_sum=1e4) + log1p")
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)

    # Keep normalized log data available as a layer for downstream use.
    adata.layers["lognorm"] = adata.X.copy()

    adata.uns["normalize_hvg"] = {
        "normalize_total_target_sum": 1e4,
        "log1p": True,
        "hvg_flavor": "seurat_v3",
        "n_top_genes": n_top_genes,
        "n_highly_variable": n_hvg,
    }

    # Atomic write to avoid partial output on interruption.
    tmp_path = out_path + ".tmp"
    print(f"[06_normalize_hvg] Writing {out_path}")
    adata.write_h5ad(tmp_path)
    os.replace(tmp_path, out_path)

    print("[06_normalize_hvg] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
