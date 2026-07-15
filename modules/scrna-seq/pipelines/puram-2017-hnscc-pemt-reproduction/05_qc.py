#!/usr/bin/env python
"""05_qc.py — QC and filtering for Puram 2017 HNSCC (GSE103322, Smart-seq2).

Reads adata_raw.h5ad, computes QC metrics (n_genes, total counts, mito%),
applies Smart-seq2-appropriate filtering, and writes adata_qc.h5ad plus
a self-contained qc_report.html.

Idempotent: if outputs already exist, skips work.
run: python 05_qc.py
"""
import base64
import io
import os
import sys
from pathlib import Path

import numpy as np


def get_results_dir() -> Path:
    d = os.environ.get("GHBIO_RESULTS")
    if not d:
        d = os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> None:
    results = get_results_dir()
    in_h5ad = results / "adata_raw.h5ad"
    out_h5ad = results / "adata_qc.h5ad"
    out_html = results / "qc_report.html"

    if out_h5ad.exists() and out_html.exists():
        print(f"[05_qc] outputs already exist, skipping: {out_h5ad}, {out_html}")
        return

    if not in_h5ad.exists():
        sys.exit(f"[05_qc] ERROR: required input not found: {in_h5ad}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import scanpy as sc

    sc.settings.verbosity = 1

    print(f"[05_qc] reading {in_h5ad}")
    adata = sc.read_h5ad(in_h5ad)
    n_cells_start, n_genes_start = adata.shape
    print(f"[05_qc] loaded shape: {n_cells_start} cells x {n_genes_start} genes")

    # --- annotate mito genes (human, GRCh38) ---
    var_names_upper = adata.var_names.str.upper()
    adata.var["mt"] = var_names_upper.str.startswith("MT-")
    # ribosomal proteins (informative for Smart-seq2 QC)
    adata.var["ribo"] = var_names_upper.str.startswith(("RPS", "RPL"))

    sc.pp.calculate_qc_metrics(
        adata,
        qc_vars=["mt", "ribo"],
        percent_top=None,
        log1p=False,
        inplace=True,
    )

    # --- Smart-seq2-appropriate thresholds ---
    # Smart-seq2 full-length: no UMI, high gene detection expected.
    # These are sensible defaults for TPM-derived pseudo-counts.
    MIN_GENES = int(os.environ.get("GHBIO_QC_MIN_GENES", "1000"))  # TODO: 확인 필요
    MAX_PCT_MT = float(os.environ.get("GHBIO_QC_MAX_PCT_MT", "20.0"))  # TODO: 확인 필요
    MIN_CELLS = int(os.environ.get("GHBIO_QC_MIN_CELLS", "3"))  # gene detected in >=N cells

    # keep pre-filter snapshot of metrics for the report
    pre = {
        "n_genes_by_counts": np.asarray(adata.obs["n_genes_by_counts"]).astype(float),
        "total_counts": np.asarray(adata.obs["total_counts"]).astype(float),
        "pct_counts_mt": np.asarray(adata.obs["pct_counts_mt"]).astype(float),
    }

    # --- apply cell filters ---
    cell_mask = (
        (adata.obs["n_genes_by_counts"] >= MIN_GENES)
        & (adata.obs["pct_counts_mt"] <= MAX_PCT_MT)
    )
    n_removed_cells = int((~cell_mask).sum())
    adata = adata[cell_mask.values].copy()

    # --- gene filter ---
    sc.pp.filter_genes(adata, min_cells=MIN_CELLS)

    n_cells_end, n_genes_end = adata.shape
    print(f"[05_qc] after filtering: {n_cells_end} cells x {n_genes_end} genes "
          f"(removed {n_removed_cells} cells by cell filters)")

    adata.uns["qc_params"] = {
        "min_genes": MIN_GENES,
        "max_pct_mt": MAX_PCT_MT,
        "min_cells_per_gene": MIN_CELLS,
        "n_cells_start": n_cells_start,
        "n_genes_start": n_genes_start,
        "n_cells_end": int(n_cells_end),
        "n_genes_end": int(n_genes_end),
    }

    # --- build QC plots for the HTML report ---
    def fig_to_b64(fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")

    imgs = {}

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].hist(pre["n_genes_by_counts"], bins=60, color="#4C78A8")
    axes[0].axvline(MIN_GENES, color="red", ls="--")
    axes[0].set_title("Genes detected per cell")
    axes[0].set_xlabel("n_genes_by_counts")
    axes[1].hist(np.log10(pre["total_counts"] + 1), bins=60, color="#54A24B")
    axes[1].set_title("Total counts per cell (log10)")
    axes[1].set_xlabel("log10(total_counts+1)")
    axes[2].hist(pre["pct_counts_mt"], bins=60, color="#E45756")
    axes[2].axvline(MAX_PCT_MT, color="red", ls="--")
    axes[2].set_title("Mitochondrial %")
    axes[2].set_xlabel("pct_counts_mt")
    fig.suptitle("Pre-filter QC distributions")
    imgs["dist"] = fig_to_b64(fig)

    fig, ax = plt.subplots(figsize=(6, 5))
    sc_col = pre["pct_counts_mt"]
    scv = ax.scatter(
        pre["total_counts"], pre["n_genes_by_counts"],
        c=sc_col, cmap="viridis", s=6, alpha=0.6,
    )
    ax.set_xscale("log")
    ax.set_xlabel("total_counts (log)")
    ax.set_ylabel("n_genes_by_counts")
    ax.axhline(MIN_GENES, color="red", ls="--")
    ax.set_title("Counts vs genes (color = pct_mt)")
    fig.colorbar(scv, ax=ax, label="pct_counts_mt")
    imgs["scatter"] = fig_to_b64(fig)

    # --- write HTML report ---
    p = adata.uns["qc_params"]
    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>QC Report — GSE103322 HNSCC (Smart-seq2)</title>
<style>
body{{font-family:sans-serif;margin:2em;color:#222;max-width:1100px}}
h1{{color:#333}} table{{border-collapse:collapse;margin:1em 0}}
td,th{{border:1px solid #ccc;padding:6px 12px;text-align:left}}
th{{background:#f0f0f0}} img{{max-width:100%;border:1px solid #ddd;margin:1em 0}}
.note{{color:#666;font-size:0.9em}}
</style></head><body>
<h1>QC and filtering report</h1>
<p class="note">Dataset: GSE103322 — HNSCC Smart-seq2 scRNA-seq (Puram et al. 2017).
Smart-seq2 full-length (no UMI); metrics computed on pseudo-count reverse-transformed matrix.</p>

<h2>QC parameters</h2>
<table>
<tr><th>Parameter</th><th>Value</th></tr>
<tr><td>min genes per cell</td><td>{p['min_genes']}</td></tr>
<tr><td>max pct mitochondrial</td><td>{p['max_pct_mt']}</td></tr>
<tr><td>min cells per gene</td><td>{p['min_cells_per_gene']}</td></tr>
</table>

<h2>Filtering summary</h2>
<table>
<tr><th></th><th>Cells</th><th>Genes</th></tr>
<tr><td>Before</td><td>{p['n_cells_start']}</td><td>{p['n_genes_start']}</td></tr>
<tr><td>After</td><td>{p['n_cells_end']}</td><td>{p['n_genes_end']}</td></tr>
<tr><td>Removed</td><td>{p['n_cells_start']-p['n_cells_end']}</td><td>{p['n_genes_start']-p['n_genes_end']}</td></tr>
</table>

<h2>Pre-filter distributions</h2>
<img src="data:image/png;base64,{imgs['dist']}" alt="QC distributions">

<h2>Counts vs genes</h2>
<img src="data:image/png;base64,{imgs['scatter']}" alt="Counts vs genes scatter">

<p class="note">Note: ambient RNA correction is not applicable for plate-based Smart-seq2
(no droplet ambient pool); mito% and gene-detection filtering are used instead.</p>
</body></html>
"""

    tmp_html = out_html.with_suffix(".html.tmp")
    tmp_html.write_text(html, encoding="utf-8")
    tmp_html.replace(out_html)
    print(f"[05_qc] wrote {out_html}")

    tmp_h5ad = out_h5ad.with_suffix(".h5ad.tmp")
    adata.write_h5ad(tmp_h5ad)
    tmp_h5ad.replace(out_h5ad)
    print(f"[05_qc] wrote {out_h5ad}")


if __name__ == "__main__":
    main()
