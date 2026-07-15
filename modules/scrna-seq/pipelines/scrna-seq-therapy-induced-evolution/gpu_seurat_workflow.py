#!/usr/bin/env python3
"""GPU (PyTorch) reimplementation of the authors' standard Seurat workflow.

The Maynard et al. notebooks build a Seurat object and run the canonical
NormalizeData -> FindVariableFeatures(vst) -> ScaleData -> RunPCA ->
FindNeighbors -> FindClusters -> RunUMAP -> FindAllMarkers pipeline. This script
reproduces those SAME steps on the authors' published S01 count matrix, moving the
heavy dense linear algebra (log-normalization, z-score scaling, and the PCA SVD)
onto the GPU with PyTorch. The graph steps (neighbors/Leiden/UMAP/markers) use
Scanpy's optimized routines, which are the modern equivalents of Seurat's.

Unlike the scVI reanalysis in scrna-seq-gpu-modern-reanalysis, this is a faithful
port of the Seurat algorithm, not a different model: same thresholds, same
LogNormalize(1e4), same vst HVG method, same PCA-on-scaled-data definition.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import torch
from scipy import sparse


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


def gpu_lognormalize(counts: sparse.csr_matrix, device: torch.device, scale_factor: float) -> sparse.csr_matrix:
    """Seurat NormalizeData(LogNormalize): log1p(count / cell_total * scale_factor).

    log1p(0) == 0, so the operation preserves sparsity: we only transform the stored
    non-zero values on the GPU, keyed by their row (cell) totals.
    """
    counts = counts.tocsr().astype(np.float32)
    totals = np.asarray(counts.sum(axis=1)).ravel()
    totals[totals == 0] = 1.0
    row_of_nnz = np.repeat(np.arange(counts.shape[0]), np.diff(counts.indptr))
    data = torch.from_numpy(counts.data).to(device)
    factor = torch.from_numpy((scale_factor / totals).astype(np.float32)).to(device)
    normalized = torch.log1p(data * factor[torch.from_numpy(row_of_nnz).to(device)])
    out = counts.copy()
    out.data = normalized.cpu().numpy()
    return out


def gpu_scale(matrix: np.ndarray, device: torch.device, scale_max: float) -> torch.Tensor:
    """Seurat ScaleData: center to mean 0, scale to unit variance (sample sd), clip at scale_max."""
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    scaled = (x - mean) / std
    return torch.clamp(scaled, max=scale_max)


def gpu_pca(scaled: torch.Tensor, n_comps: int) -> np.ndarray:
    """RunPCA on already-centered, scaled data via SVD: scores = U * S (top n_comps)."""
    scaled = scaled - scaled.mean(dim=0, keepdim=True)  # guard: ensure exact centering
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    scores = u[:, :n_comps] * s[:n_comps]
    return scores.cpu().numpy()


# Canonical lineage markers used to label each cluster. The authors annotated clusters
# manually; this reproduces that INTENT deterministically — each cluster is scored against
# every signature (mean scaled expression of the genes present) and takes the argmax. The
# immune/non-immune split (the authors' first cut, via CD45/EPCAM) falls out of the label.
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "T cell": ["CD3D", "CD3E", "CD3G", "CD2", "TRAC", "CD8A", "CD4", "IL7R"],
    "B_Plasma": ["CD79A", "CD79B", "MS4A1", "MZB1", "IGHG1", "IGKC", "CD19"],
    "NK": ["NKG7", "GNLY", "KLRD1", "KLRF1", "NCAM1", "NCR1"],
    "Myeloid": ["LYZ", "CD68", "CD14", "FCGR3A", "ITGAX", "MARCO", "AIF1", "C1QA"],
    "Mast": ["TPSAB1", "TPSB2", "CPA3", "MS4A2"],
    "Epithelial": ["EPCAM", "KRT19", "KRT18", "KRT8", "CDH1", "SFTPC", "SFTPB", "SCGB1A1"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5", "CLEC14A", "CDH5"],
    "Fibroblast": ["COL1A1", "COL1A2", "DCN", "LUM", "PDGFRB", "ACTA2"],
}
IMMUNE_TYPES = {"T cell", "B_Plasma", "NK", "Myeloid", "Mast"}

# The authors' processed metadata groups every cell into the paper's three treatment stages
# in the `analysis` column. Map it to the paper's TN / RD / PD labels.
STAGE_MAP = {"naive": "TN", "grouped_pr": "RD", "grouped_pd": "PD"}
STAGE_ORDER = ["TN", "RD", "PD"]


def annotate_clusters(adata: ad.AnnData) -> pd.DataFrame:
    """Score each cluster against the lineage signatures and assign the argmax cell type.

    Returns a per-cluster table (cluster, n_cells, cell_type, compartment, per-signature score)
    and writes `cell_type` + `compartment` back onto adata.obs (per cell, by cluster).
    """
    score_cols: dict[str, str] = {}
    for sig, genes in CELL_TYPE_MARKERS.items():
        present = [g for g in genes if g in adata.var_names]
        col = f"_score_{sig}"
        if present:
            sc.tl.score_genes(adata, present, score_name=col, use_raw=False)
        else:
            adata.obs[col] = 0.0
        score_cols[sig] = col

    per_cluster = adata.obs.groupby("seurat_clusters", observed=True)[list(score_cols.values())].mean()
    per_cluster.columns = list(score_cols.keys())
    assigned = per_cluster.idxmax(axis=1)
    compartment = assigned.map(lambda t: "immune" if t in IMMUNE_TYPES else "non-immune")

    adata.obs["cell_type"] = adata.obs["seurat_clusters"].map(assigned).astype("category")
    adata.obs["compartment"] = adata.obs["seurat_clusters"].map(compartment).astype("category")

    table = per_cluster.copy()
    table.insert(0, "n_cells", adata.obs["seurat_clusters"].value_counts().reindex(table.index).astype(int))
    table.insert(1, "cell_type", assigned)
    table.insert(2, "compartment", compartment)
    table.index.name = "cluster"
    # Drop the transient per-cell score columns so they don't bloat the saved AnnData.
    adata.obs.drop(columns=list(score_cols.values()), inplace=True)
    return table.reset_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="scell_lung_adenocarcinoma dir")
    parser.add_argument("--results", type=Path, required=True, help="GHBIO_RESULTS output dir")
    parser.add_argument("--min-counts", type=float, default=50_000, help="Seurat nCount_RNA filter (authors' value)")
    parser.add_argument("--min-genes", type=int, default=500, help="Seurat nFeature_RNA filter (authors' value)")
    parser.add_argument("--scale-factor", type=float, default=1e4, help="NormalizeData scale.factor")
    parser.add_argument("--n-hvg", type=int, default=2000, help="FindVariableFeatures nfeatures")
    parser.add_argument("--scale-max", type=float, default=10.0, help="ScaleData scale.max clip")
    parser.add_argument("--n-pcs", type=int, default=30, help="PCs used for neighbors/UMAP")
    parser.add_argument("--n-comps", type=int, default=50, help="RunPCA npcs computed")
    parser.add_argument("--n-neighbors", type=int, default=20, help="FindNeighbors k.param")
    parser.add_argument("--resolution", type=float, default=0.8, help="FindClusters resolution (Seurat default)")
    parser.add_argument("--seed", type=int, default=2020)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; this GPU workflow intentionally refuses CPU fallback.")
    device = torch.device("cuda")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    sc.settings.verbosity = 1
    print(f"GPU detected: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}", flush=True)

    data = args.source / "Data_input" / "csv_files"
    counts_path, meta_path = data / "S01_datafinal.csv", data / "S01_metacells.csv"
    if not counts_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError("Authors' S01 count matrix/metadata missing; run the data step first.")
    args.results.mkdir(parents=True, exist_ok=True)

    # The published CSV is genes x cells (as Seurat's raw.data). Align to author metadata by cell_id.
    with progress("Reading authors' Smart-seq2 count matrix (1.5 GB CSV)"):
        counts = pd.read_csv(counts_path, index_col=0)
    with progress("Reading and aligning author metadata"):
        meta = pd.read_csv(meta_path, index_col=0)
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

    # Seurat 02_Create_Seurat_object.Rmd: compute percent.ercc, then drop ERCC spike-ins.
    genes = counts.index.to_numpy()
    ercc_mask = pd.Index(genes).str.startswith("ERCC-")
    cell_totals = counts.to_numpy().sum(axis=0)
    ercc_frac = counts.to_numpy()[ercc_mask].sum(axis=0) / np.where(cell_totals == 0, 1, cell_totals)
    counts = counts.loc[~ercc_mask]

    with progress("Converting counts to a sparse AnnData matrix (cells x genes)"):
        matrix = sparse.csr_matrix(counts.to_numpy(dtype=np.int32, copy=False).T)
    adata = ad.AnnData(matrix, obs=meta, var=pd.DataFrame(index=counts.index))
    adata.obs["percent.ercc"] = ercc_frac
    ribo = adata.var_names.str.contains(r"^RP[SL]\d", regex=True)
    adata.obs["percent.ribo"] = np.asarray(adata.X[:, ribo].sum(axis=1)).ravel() / np.asarray(adata.X.sum(axis=1)).ravel()
    adata.layers["counts"] = adata.X.copy()
    del counts

    # Seurat QC filter: nCount_RNA > min-counts & nFeature_RNA > min-genes.
    adata.obs["nCount_RNA"] = np.asarray(adata.X.sum(axis=1)).ravel()
    adata.obs["nFeature_RNA"] = np.asarray((adata.X > 0).sum(axis=1)).ravel()
    n_before = adata.n_obs
    adata = adata[(adata.obs.nCount_RNA > args.min_counts) & (adata.obs.nFeature_RNA > args.min_genes)].copy()
    print(f"QC: {adata.n_obs:,} / {n_before:,} cells pass (nCount>{args.min_counts:g}, nFeature>{args.min_genes})", flush=True)

    # --- GPU: NormalizeData (LogNormalize) -------------------------------------------------
    with progress("GPU NormalizeData (LogNormalize, sparsity-preserving)"):
        adata.X = gpu_lognormalize(adata.layers["counts"], device, args.scale_factor)

    # --- FindVariableFeatures (vst == Scanpy 'seurat_v3', computed from raw counts) ---------
    with progress("FindVariableFeatures (vst / seurat_v3, top HVGs)"):
        sc.pp.highly_variable_genes(adata, flavor="seurat_v3", n_top_genes=args.n_hvg, layer="counts")
    hvg = np.where(adata.var["highly_variable"].to_numpy())[0]

    # --- GPU: ScaleData + RunPCA (on the variable features, as Seurat does by default) ------
    with progress("GPU ScaleData + RunPCA (SVD on GPU)"):
        dense_hvg = np.asarray(adata.X[:, hvg].todense())
        scaled = gpu_scale(dense_hvg, device, args.scale_max)
        adata.obsm["X_pca"] = gpu_pca(scaled, args.n_comps)
        del dense_hvg, scaled
        torch.cuda.empty_cache()

    # --- FindNeighbors -> FindClusters -> RunUMAP (Scanpy; Seurat's modern equivalents) -----
    with progress("FindNeighbors + FindClusters (Leiden) + RunUMAP"):
        sc.pp.neighbors(adata, use_rep="X_pca", n_pcs=args.n_pcs, n_neighbors=args.n_neighbors, random_state=args.seed)
        sc.tl.leiden(adata, key_added="seurat_clusters", resolution=args.resolution,
                     flavor="igraph", n_iterations=2, random_state=args.seed, directed=False)
        sc.tl.umap(adata, random_state=args.seed)
    n_clusters = adata.obs["seurat_clusters"].nunique()
    print(f"Found {n_clusters} clusters at resolution {args.resolution}", flush=True)

    # --- FindAllMarkers (Wilcoxon) on the log-normalized matrix -----------------------------
    with progress("FindAllMarkers (Wilcoxon rank-sum)"):
        sc.tl.rank_genes_groups(adata, groupby="seurat_clusters", method="wilcoxon", use_raw=False)
    markers = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "scores": "score", "logfoldchanges": "logfoldchange"}
    )
    # Same compact schema the BioIDE AI hand-off expects (cluster, rank, gene, ...).
    markers["rank"] = markers.groupby("cluster", observed=True).cumcount() + 1
    markers = markers[["cluster", "rank", "gene", "score", "logfoldchange", "pvals", "pvals_adj"]]
    markers.to_csv(args.results / "markers_by_cluster.csv", index=False)

    # --- Cell-type annotation (reproduces the authors' manual cluster labeling) --------------
    with progress("Annotating clusters by canonical lineage markers"):
        annotation = annotate_clusters(adata)
    annotation.to_csv(args.results / "celltype_annotation.csv", index=False)
    print("Cell types: " + ", ".join(f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)

    # --- Treatment-stage (TN/RD/PD) composition — the paper's headline ------------------------
    stage_col = "analysis" if "analysis" in adata.obs.columns else None
    if stage_col is not None:
        adata.obs["treatment_stage"] = (
            adata.obs[stage_col].astype(str).map(STAGE_MAP).fillna("other")
        )
        present_stages = [s for s in STAGE_ORDER if s in set(adata.obs["treatment_stage"])]
        adata.obs["treatment_stage"] = pd.Categorical(
            adata.obs["treatment_stage"], categories=present_stages + (["other"] if "other" in set(adata.obs["treatment_stage"]) else []), ordered=True
        )
        with progress("Composition shift across TN → RD → PD"):
            # Cell-type % within each stage (rows sum to 100), and the immune/non-immune split.
            comp = pd.crosstab(adata.obs["treatment_stage"], adata.obs["cell_type"], normalize="index").mul(100).round(2)
            comp.reindex(present_stages).to_csv(args.results / "composition_by_stage.csv")
            compartment = pd.crosstab(adata.obs["treatment_stage"], adata.obs["compartment"], normalize="index").mul(100).round(2)
            compartment.reindex(present_stages).to_csv(args.results / "compartment_by_stage.csv")

            fig, ax = plt.subplots(figsize=(8, 5))
            comp.reindex(present_stages).plot(kind="bar", stacked=True, ax=ax, colormap="tab20", width=0.8)
            ax.set_ylabel("cells within stage (%)")
            ax.set_xlabel("treatment stage")
            ax.set_title("Cell-type composition across treatment stages (Maynard et al. reanalysis)")
            ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8, title="cell type")
            plt.xticks(rotation=0)
            plt.savefig(args.results / "composition_barplot.png", dpi=180, bbox_inches="tight")
            plt.close("all")
        print("Stage sizes: " + ", ".join(f"{s}×{int((adata.obs['treatment_stage']==s).sum())}" for s in present_stages), flush=True)
    else:
        present_stages = []
        print("No `analysis` stage column found — skipping TN/RD/PD composition.", flush=True)

    # UMAP colored by the assigned cell type (alongside the cluster UMAP below).
    sc.pl.umap(adata, color=["cell_type"], show=False, frameon=False, legend_loc="right margin", title="Cell types")
    plt.savefig(args.results / "umap_celltypes.png", dpi=180, bbox_inches="tight")
    plt.close("all")

    sizes = adata.obs["seurat_clusters"].value_counts().rename("n_cells").reset_index()
    sizes.columns = ["cluster", "n_cells"]
    sizes.sort_values("cluster").to_csv(args.results / "cluster_sizes.csv", index=False)

    # QC summary CSV mirrors the numbers a reader would read off the Seurat object.
    pd.DataFrame(
        {
            "metric": ["cells_input", "cells_pass_qc", "genes", "n_hvg", "n_clusters",
                       "median_nCount_RNA", "median_nFeature_RNA", "mean_percent_ercc"],
            "value": [n_before, adata.n_obs, adata.n_vars, len(hvg), n_clusters,
                      float(np.median(adata.obs.nCount_RNA)), float(np.median(adata.obs.nFeature_RNA)),
                      float(adata.obs["percent.ercc"].mean())],
        }
    ).to_csv(args.results / "qc_summary.csv", index=False)

    sc.pl.umap(adata, color=["seurat_clusters"], show=False, frameon=False, legend_loc="on data")
    plt.savefig(args.results / "umap_seurat_gpu.png", dpi=180, bbox_inches="tight")
    plt.close("all")

    provenance = {
        "method": "GPU (PyTorch) reanalysis of the Maynard et al. Smart-seq2 data",
        "pipeline": ["QC", "LogNormalize", "seurat_v3 HVG", "ScaleData", "RunPCA(SVD)",
                     "neighbors", "Leiden", "UMAP", "Wilcoxon markers",
                     "marker-based cell-type annotation", "TN/RD/PD composition"],
        "gpu_accelerated_steps": ["LogNormalize", "ScaleData", "RunPCA(SVD)"],
        "cell_type_markers": CELL_TYPE_MARKERS,
        "treatment_stage_map": STAGE_MAP,
        "treatment_stages_found": present_stages,
        "cell_type_counts": {str(k): int(v) for k, v in adata.obs["cell_type"].value_counts().items()},
        "params": {
            "min_counts": args.min_counts, "min_genes": args.min_genes, "scale_factor": args.scale_factor,
            "n_hvg": args.n_hvg, "scale_max": args.scale_max, "n_comps": args.n_comps, "n_pcs": args.n_pcs,
            "n_neighbors": args.n_neighbors, "resolution": args.resolution, "seed": args.seed,
        },
        "gpu": torch.cuda.get_device_name(0),
        "cuda": torch.version.cuda,
    }
    adata.uns["gpu_seurat_workflow"] = provenance
    with progress("Writing compressed AnnData and result files"):
        adata.write_h5ad(args.results / "gpu_seurat_workflow.h5ad", compression="gzip")
    (args.results / "gpu_seurat_workflow_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Completed GPU reanalysis: {adata.n_obs:,} cells, {adata.n_vars:,} genes, {n_clusters} clusters, "
          f"{adata.obs['cell_type'].nunique()} cell types across {len(present_stages)} treatment stages "
          f"on {torch.cuda.get_device_name(0)}", flush=True)


if __name__ == "__main__":
    main()
