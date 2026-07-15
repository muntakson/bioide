#!/usr/bin/env python
"""04_build_adata.py — [build_adata] Parse matrix and build AnnData.

GSE103322_HNSCC_all_data.txt is a genes x cells matrix in log2(TPM/10+1) units.
We reverse-transform to a pseudo-count scale: X = round(10 * (2**logTPM - 1)),
attach the embedded metadata rows as obs, and build an AnnData saved as
adata_raw.h5ad under $GHBIO_RESULTS.

Idempotent: skips rebuild if adata_raw.h5ad already exists and is readable.
"""
import os
import sys
import gzip
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
import anndata as ad

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RESULTS = Path(os.environ.get(
    "GHBIO_RESULTS",
    str(Path.home() / "ghbio-tutorial" / "results"),
))
RESULTS.mkdir(parents=True, exist_ok=True)

OUT = RESULTS / "adata_raw.h5ad"

# Processed matrix produced by 02_download_matrix.sh
CANDIDATES = [
    RESULTS / "raw" / "GSE103322_HNSCC_all_data.txt",
    RESULTS / "raw" / "GSE103322_HNSCC_all_data.txt.gz",
]


def find_matrix() -> Path:
    for c in CANDIDATES:
        if c.exists():
            return c
    sys.exit(
        f"[04_build_adata] processed matrix not found; looked for: "
        f"{', '.join(str(c) for c in CANDIDATES)}"
    )


def open_maybe_gzip(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt")
    return open(path, "rt")


# Metadata rows embedded at the top of GSE103322_HNSCC_all_data.txt.
# The first columns of the file are non-numeric header/annotation rows whose
# first-column label identifies them. Everything else is gene expression.
# TODO: 확인 필요 — exact set/labels of embedded metadata rows in GSE103322.
META_ROW_LABELS = {
    "cell": "cell",
    "tumor": "patient",
    "lymph node": "lymph_node",
    "processed by maxima enzyme": "processed_maxima",
    "non-cancer cell type": "noncancer_celltype",
    "classified  as cancer cell": "malignant",
    "classified as cancer cell": "malignant",
}


def main() -> None:
    if OUT.exists():
        try:
            _ = ad.read_h5ad(OUT, backed="r")
            print(f"[04_build_adata] {OUT} already exists; skipping.")
            return
        except Exception:
            print(f"[04_build_adata] existing {OUT} unreadable; rebuilding.")

    matrix_path = find_matrix()
    print(f"[04_build_adata] reading matrix: {matrix_path}")

    # Read whole table with genes/metadata-rows as index, cells as columns.
    with open_maybe_gzip(matrix_path) as fh:
        df = pd.read_csv(fh, sep="\t", header=0, index_col=0, low_memory=False)

    df.index = df.index.astype(str).str.strip()

    # ------------------------------------------------------------------
    # Separate embedded metadata rows from expression rows.
    # ------------------------------------------------------------------
    lowered = {i.lower(): i for i in df.index}
    meta_rows = {}
    for label_lc, obs_name in META_ROW_LABELS.items():
        if label_lc in lowered:
            meta_rows[obs_name] = lowered[label_lc]

    meta_index = list(meta_rows.values())
    expr_df = df.drop(index=meta_index, errors="ignore")

    # Any residual non-numeric expression rows are dropped defensively.
    expr_df = expr_df.apply(pd.to_numeric, errors="coerce")
    n_before = expr_df.shape[0]
    expr_df = expr_df.dropna(how="all")
    # Rows that are still entirely NaN after coercion were non-numeric.
    dropped = n_before - expr_df.shape[0]
    if dropped:
        print(f"[04_build_adata] dropped {dropped} non-numeric rows.")

    # Fill any remaining sporadic NaNs with 0 (missing = not detected).
    expr_df = expr_df.fillna(0.0)

    genes = expr_df.index.astype(str).tolist()
    cells = expr_df.columns.astype(str).tolist()

    # ------------------------------------------------------------------
    # Reverse transform log2(TPM/10 + 1) -> pseudo-count.
    #   X = round(10 * (2**logTPM - 1))
    # Matrix orientation: rows=genes, cols=cells  ->  transpose to cells x genes.
    # ------------------------------------------------------------------
    logtpm = expr_df.to_numpy(dtype=np.float64)
    pseudo = np.rint(10.0 * (np.power(2.0, logtpm) - 1.0))
    pseudo[pseudo < 0] = 0.0

    X = sp.csr_matrix(pseudo.T.astype(np.float32))  # cells x genes

    # ------------------------------------------------------------------
    # Assemble obs metadata from embedded rows.
    # ------------------------------------------------------------------
    obs = pd.DataFrame(index=pd.Index(cells, name="cell_id"))
    for obs_name, row_label in meta_rows.items():
        vals = df.loc[row_label, cells].astype(str).str.strip().values
        obs[obs_name] = vals

    # Normalize malignant flag to boolean if present.
    if "malignant" in obs.columns:
        obs["malignant"] = (
            obs["malignant"].str.strip().isin({"1", "1.0", "True", "true", "yes"})
        )

    var = pd.DataFrame(index=pd.Index(genes, name="gene_symbol"))
    var.index = var.index.str.replace("'", "", regex=False)

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.layers["logtpm"] = sp.csr_matrix(logtpm.T.astype(np.float32))
    adata.uns["build_adata"] = {
        "source_file": str(matrix_path),
        "reverse_transform": "X = round(10 * (2**logTPM - 1))",
        "units_X": "pseudo_count",
        "units_layer_logtpm": "log2(TPM/10+1)",
        "n_metadata_rows": len(meta_rows),
    }

    print(f"[04_build_adata] AnnData: {adata.n_obs} cells x {adata.n_vars} genes")
    print(f"[04_build_adata] obs columns: {list(adata.obs.columns)}")

    tmp = OUT.with_suffix(".h5ad.tmp")
    adata.write_h5ad(tmp)
    os.replace(tmp, OUT)
    print(f"[04_build_adata] wrote {OUT}")


if __name__ == "__main__":
    main()
