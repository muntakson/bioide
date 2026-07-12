#!/usr/bin/env python3
"""GPU-native, explicitly non-identical reanalysis of Maynard et al. Smart-seq2 data."""
from __future__ import annotations

import argparse
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import scvi
import torch
from scipy import sparse


def first_column(frame: pd.DataFrame, choices: list[str]) -> str | None:
    lowered = {str(c).lower(): str(c) for c in frame.columns}
    for choice in choices:
        if choice.lower() in lowered:
            return lowered[choice.lower()]
    return None


@contextmanager
def progress(label: str):
    """Print a terminal heartbeat while a long blocking operation is in progress."""
    started = time.monotonic()
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(30):
            print(f"⏳ {label} — still running ({(time.monotonic() - started) / 60:.1f} min elapsed)", flush=True)

    print(f"▶ {label}", flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=1)
        print(f"✓ {label} — finished ({(time.monotonic() - started) / 60:.1f} min)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; this GPU tutorial intentionally refuses CPU fallback.")
    print(f"GPU detected: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}", flush=True)

    data = args.source / "Data_input" / "csv_files"
    counts_path, meta_path = data / "S01_datafinal.csv", data / "S01_metacells.csv"
    if not counts_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError("Authors' S01 count matrix/metadata missing; rerun data verification.")
    args.results.mkdir(parents=True, exist_ok=True)

    # The published CSV is genes × cells. Preserve integer counts in a sparse AnnData layer.
    with progress("Reading authors' Smart-seq2 count matrix (large CSV)"):
        counts = pd.read_csv(counts_path, index_col=0)
    with progress("Reading and aligning author metadata"):
        meta = pd.read_csv(meta_path, index_col=0)
        # The authors' own Seurat notebook explicitly replaces the CSV row-number index
        # with this column before adding metadata to the count matrix.
        if "cell_id" in meta.columns:
            meta.index = meta["cell_id"].astype(str)
    counts.index = counts.index.astype(str)
    counts.columns = counts.columns.astype(str)
    meta.index = meta.index.astype(str)
    common = counts.columns.intersection(meta.index)
    if len(common) < 100:
        raise ValueError("Could not align count-matrix cell IDs with author metadata.")
    counts = counts.loc[:, common]
    meta = meta.loc[common].copy()
    with progress("Converting counts to a sparse AnnData matrix"):
        matrix = sparse.csr_matrix(counts.to_numpy(dtype=np.int32, copy=False).T)
    adata = ad.AnnData(matrix, obs=meta, var=pd.DataFrame(index=counts.index))
    adata.layers["counts"] = adata.X.copy()
    del counts

    # Retain the paper's published high-depth QC thresholds before modern modeling.
    adata.obs["n_counts_author"] = np.asarray(adata.X.sum(axis=1)).ravel()
    adata.obs["n_genes_author"] = np.asarray((adata.X > 0).sum(axis=1)).ravel()
    adata = adata[(adata.obs.n_counts_author > 50_000) & (adata.obs.n_genes_author > 500)].copy()
    print(f"QC retained {adata.n_obs:,} cells × {adata.n_vars:,} genes", flush=True)
    batch_key = first_column(adata.obs, ["sample_name", "sample", "sample_id"])
    if batch_key is None:
        adata.obs["sample_name"] = "all_samples"
        batch_key = "sample_name"
    adata.obs[batch_key] = adata.obs[batch_key].astype(str).astype("category")

    scvi.settings.seed = 2020
    torch.set_float32_matmul_precision("high")
    scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key=batch_key)
    model = scvi.model.SCVI(adata, n_latent=30, n_layers=2, gene_likelihood="nb")
    with progress("Training GPU scVI model (up to 200 epochs; early stopping enabled)"):
        model.train(max_epochs=200, early_stopping=True, accelerator="gpu", devices=1, enable_progress_bar=False)
    adata.obsm["X_scVI"] = model.get_latent_representation()
    model.save(args.results / "scvi_model", overwrite=True, save_anndata=False)

    # Optional semi-supervised annotation: only use a published label column if supplied.
    label_key = first_column(adata.obs, ["cell_type", "celltype", "general_annotation", "broad_cell_type"])
    if label_key and adata.obs[label_key].notna().sum() > 50:
        adata.obs["author_label"] = adata.obs[label_key].fillna("Unknown").astype(str).astype("category")
        scanvi = scvi.model.SCANVI.from_scvi_model(model, labels_key="author_label", unlabeled_category="Unknown")
        with progress("Training GPU scANVI annotation model (up to 100 epochs)"):
            scanvi.train(max_epochs=100, early_stopping=True, accelerator="gpu", devices=1, enable_progress_bar=False)
        adata.obs["scanvi_label"] = scanvi.predict(adata)
        scanvi.save(args.results / "scanvi_model", overwrite=True, save_anndata=False)

    with progress("Building scVI-neighbor graph, UMAP, Leiden clusters, and markers"):
        sc.pp.neighbors(adata, use_rep="X_scVI", n_neighbors=15)
        sc.tl.umap(adata, random_state=2020)
        sc.tl.leiden(adata, key_added="leiden_scvi", resolution=0.6, flavor="igraph", n_iterations=2)
    # Keep raw integer counts in layers["counts"] for pseudobulk, but use a conventional
    # log-normalized expression matrix for human-readable marker ranking.
    adata.X = adata.layers["counts"].copy()
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.tl.rank_genes_groups(adata, groupby="leiden_scvi", method="wilcoxon", use_raw=False)
    markers = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "scores": "score", "logfoldchanges": "logfoldchange"}
    )
    # BioIDE's AI hand-off intentionally uses column 2 as a rank filter. Export this
    # compact, stable schema instead of Scanpy's default group,names,... ordering.
    markers["rank"] = markers.groupby("cluster", observed=True).cumcount() + 1
    markers = markers[["cluster", "rank", "gene", "score", "logfoldchange", "pvals", "pvals_adj"]]
    markers.to_csv(args.results / "markers_by_cluster.csv", index=False)
    pd.DataFrame({"cluster": adata.obs["leiden_scvi"].astype(str)}).value_counts().rename("n_cells").reset_index().to_csv(
        args.results / "cluster_sizes.csv", index=False
    )
    sc.pl.umap(adata, color=["leiden_scvi"], show=False, frameon=False)
    plt.savefig(args.results / "umap_scvi.png", dpi=180, bbox_inches="tight")
    plt.close("all")
    adata.uns["modern_reanalysis"] = {
        "method": "GPU scVI latent representation + Leiden",
        "not_a_faithful_reproduction": True,
        "batch_key": batch_key,
        "gpu": torch.cuda.get_device_name(0),
        "seed": 2020,
    }
    with progress("Writing compressed AnnData and final result files"):
        adata.write_h5ad(args.results / "modern_reanalysis.h5ad", compression="gzip")
    (args.results / "modern_reanalysis_provenance.json").write_text(json.dumps(adata.uns["modern_reanalysis"], indent=2) + "\n")
    print(f"Completed GPU scVI reanalysis: {adata.n_obs:,} cells, {adata.n_vars:,} genes on {torch.cuda.get_device_name(0)}")


if __name__ == "__main__":
    main()
