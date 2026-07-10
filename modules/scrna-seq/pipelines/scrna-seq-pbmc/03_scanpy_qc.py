#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
03_scanpy_qc.py
===============
Scanpy QC + clustering + marker detection for the STARsolo count matrix.
STARsolo 카운트 행렬에 대해 QC, 정규화, 클러스터링, 마커 유전자 검출을 수행합니다.

Pipeline / 파이프라인:
    load matrix -> QC metrics & filtering -> normalize+log1p -> HVG -> scale
    -> PCA -> neighbors -> UMAP -> Leiden clustering -> rank_genes_groups (Wilcoxon)
    -> draft PBMC cell-type annotation from a marker dictionary.

Outputs (to ~/ghbio-tutorial/results/):
    umap_clusters.png        UMAP colored by Leiden cluster
    qc_violin.png            QC violin plots (n_genes, total_counts, pct_mito)
    markers_by_cluster.csv   top 25 marker genes per cluster
    celltype_draft.csv       cluster -> draft PBMC cell type (from markers)

Run inside the venv from 00_setup_env.sh:
    source ~/ghbio-venv/bin/activate
    python 03_scanpy_qc.py                       # uses STARsolo output by default
    python 03_scanpy_qc.py --matrix /path/to/filtered_feature_bc_matrix
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import scanpy as sc
import matplotlib

matplotlib.use("Agg")  # headless: write PNGs without a display / 화면 없이 저장
import matplotlib.pyplot as plt  # noqa: E402


# -----------------------------------------------------------------------------
# Paths / 경로
# -----------------------------------------------------------------------------
HOME = os.path.expanduser("~")
# Results are first-class project files. GHBIO_RESULTS is injected by the extension and
# points at the project (~/ghbio-workspace/projects/<tutorial>/results). Falls back to the
# legacy path (a symlink to the project) for manual runs.
RESULTS_DIR = os.environ.get(
    "GHBIO_RESULTS", os.path.join(HOME, "ghbio-tutorial", "results")
)
DEFAULT_MATRIX = os.path.join(
    RESULTS_DIR, "starsolo", "Solo.out", "Gene", "filtered"
)


# -----------------------------------------------------------------------------
# Canonical PBMC marker dictionary / 대표적인 PBMC 마커 유전자 사전
# Used to turn cluster markers into a draft cell-type label.
# -----------------------------------------------------------------------------
PBMC_MARKERS = {
    "T cell (CD3+)":   ["CD3D", "CD3E", "CD3G"],
    "CD8 T":           ["CD8A", "CD8B"],
    "CD4 T":           ["IL7R", "CCR7"],
    "B":               ["MS4A1", "CD79A", "CD79B"],
    "NK":              ["NKG7", "GNLY", "KLRD1"],
    "CD14 Mono":       ["CD14", "LYZ"],
    "FCGR3A Mono":     ["FCGR3A", "MS4A7"],
    "DC":              ["FCER1A", "CST3"],
    "Platelet":        ["PPBP"],
}


def parse_args():
    p = argparse.ArgumentParser(description="Scanpy QC + clustering for scRNA-seq.")
    p.add_argument(
        "--matrix",
        default=DEFAULT_MATRIX,
        help="Path to a 10x filtered matrix dir (STARsolo Solo.out/Gene/filtered "
        "or a Cell Ranger filtered_feature_bc_matrix). "
        "STARsolo 출력 또는 10x 제공 filtered matrix 경로.",
    )
    p.add_argument("--min-genes", type=int, default=200,
                   help="Filter cells with fewer than this many genes.")
    p.add_argument("--min-cells", type=int, default=3,
                   help="Filter genes expressed in fewer than this many cells.")
    p.add_argument("--max-pct-mito", type=float, default=20.0,
                   help="Filter cells with mitochondrial %% above this threshold.")
    p.add_argument("--max-genes", type=int, default=6000,
                   help="Filter likely-doublet cells above this many genes.")
    p.add_argument("--n-top-genes", type=int, default=2000,
                   help="Number of highly variable genes to keep.")
    p.add_argument("--resolution", type=float, default=1.0,
                   help="Leiden clustering resolution.")
    return p.parse_args()


def load_matrix(matrix_path):
    """Load a 10x MEX matrix directory, tolerating gzipped/plain STARsolo output.
    STARsolo는 features/barcodes를 압축하지 않고 저장하므로 두 경우를 모두 처리합니다.
    """
    if not os.path.isdir(matrix_path):
        sys.exit(
            f"ERROR: matrix directory not found: {matrix_path}\n"
            "Run 02c_run_starsolo.sh first, or pass --matrix <dir>."
        )
    print(f"==> Loading 10x matrix from: {matrix_path}")
    # Newer scanpy's read_10x_mtx expects GZIPPED MEX (matrix.mtx.gz). STARsolo
    # writes them PLAIN (matrix.mtx / features.tsv / barcodes.tsv), so we read the
    # plain files directly when the .gz layout is absent. Both layouts supported.
    # STARsolo는 압축하지 않은 MEX를 저장하므로, .gz가 없으면 평문 파일을 직접 읽습니다.
    if os.path.exists(os.path.join(matrix_path, "matrix.mtx.gz")):
        adata = sc.read_10x_mtx(matrix_path, var_names="gene_symbols", cache=False)
    else:
        import pandas as pd

        adata = sc.read_mtx(os.path.join(matrix_path, "matrix.mtx")).T  # genes x cells -> cells x genes
        feat = pd.read_csv(os.path.join(matrix_path, "features.tsv"), sep="\t", header=None)
        bcs = pd.read_csv(os.path.join(matrix_path, "barcodes.tsv"), sep="\t", header=None)
        adata.var_names = feat[1].astype(str).values          # column 2 = gene symbol
        adata.var["gene_ids"] = feat[0].astype(str).values     # column 1 = Ensembl ID
        if feat.shape[1] > 2:
            adata.var["feature_types"] = feat[2].astype(str).values
        adata.obs_names = bcs[0].astype(str).values
    adata.var_names_make_unique()
    print(f"==> Loaded AnnData: {adata.n_obs} cells x {adata.n_vars} genes")
    return adata


def run_qc(adata, args):
    """Compute QC metrics and apply filtering thresholds. QC 지표 계산 및 필터링."""
    # Mitochondrial genes are prefixed 'MT-' in human GENCODE symbols.
    # 사람 유전자에서 미토콘드리아 유전자는 'MT-'로 시작합니다.
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(
        adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True
    )
    # scanpy names the mito percentage column 'pct_counts_mt'.
    adata.obs["pct_mito"] = adata.obs["pct_counts_mt"]

    # --- QC violin plots (before filtering) ---------------------------------
    os.makedirs(RESULTS_DIR, exist_ok=True)
    sc.pl.violin(
        adata,
        ["n_genes_by_counts", "total_counts", "pct_mito"],
        jitter=0.4, multi_panel=True, show=False,
    )
    qc_path = os.path.join(RESULTS_DIR, "qc_violin.png")
    plt.savefig(qc_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"==> Saved QC violin plot: {qc_path}")

    n_before = adata.n_obs
    # Gene/cell floor filters.
    sc.pp.filter_cells(adata, min_genes=args.min_genes)
    sc.pp.filter_genes(adata, min_cells=args.min_cells)
    # Remove high-mito (dying cells) and very-high-gene (likely doublets).
    adata = adata[adata.obs["pct_mito"] < args.max_pct_mito].copy()
    adata = adata[adata.obs["n_genes_by_counts"] < args.max_genes].copy()
    print(
        f"==> QC filtering: {n_before} -> {adata.n_obs} cells "
        f"(min_genes={args.min_genes}, max_pct_mito={args.max_pct_mito}, "
        f"max_genes={args.max_genes})"
    )
    return adata


def normalize_and_reduce(adata, args):
    """Normalize, find HVGs, scale, PCA, neighbors, UMAP. 정규화 및 차원축소."""
    # Keep raw counts before normalization for marker plotting later.
    adata.layers["counts"] = adata.X.copy()

    # Total-count normalize to 10k reads/cell, then log1p.
    # 세포당 총 카운트를 10,000으로 맞추고 log 변환합니다.
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    adata.raw = adata  # store log-normalized full matrix for rank_genes_groups

    # Highly variable genes (Seurat flavor on log data).
    sc.pp.highly_variable_genes(adata, n_top_genes=args.n_top_genes, flavor="seurat")
    adata = adata[:, adata.var["highly_variable"]].copy()

    # Scale (z-score), clip extreme values, then PCA.
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, svd_solver="arpack", n_comps=50)

    # Neighborhood graph -> UMAP embedding.
    sc.pp.neighbors(adata, n_neighbors=15, n_pcs=30)
    sc.tl.umap(adata)
    return adata


def cluster_and_markers(adata, args):
    """Leiden clustering + per-cluster Wilcoxon marker genes. 클러스터링 및 마커."""
    sc.tl.leiden(adata, resolution=args.resolution, key_added="leiden")
    n_clusters = adata.obs["leiden"].nunique()
    print(f"==> Leiden found {n_clusters} clusters (resolution={args.resolution}).")

    # UMAP colored by cluster.
    sc.pl.umap(adata, color="leiden", legend_loc="on data", show=False)
    umap_path = os.path.join(RESULTS_DIR, "umap_clusters.png")
    plt.savefig(umap_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"==> Saved UMAP: {umap_path}")

    # Rank marker genes per cluster with the Wilcoxon rank-sum test.
    # 각 클러스터의 마커 유전자를 Wilcoxon 검정으로 순위화합니다.
    sc.tl.rank_genes_groups(adata, groupby="leiden", method="wilcoxon")
    return adata


def export_markers(adata, top_n=25):
    """Write top-N markers per cluster to CSV. 클러스터별 상위 마커를 CSV로 저장."""
    result = adata.uns["rank_genes_groups"]
    groups = result["names"].dtype.names  # cluster labels
    rows = []
    top_genes_per_cluster = {}
    for grp in groups:
        names = result["names"][grp][:top_n]
        lfc = result["logfoldchanges"][grp][:top_n]
        pvals_adj = result["pvals_adj"][grp][:top_n]
        top_genes_per_cluster[grp] = list(names)
        for rank, (g, l, p) in enumerate(zip(names, lfc, pvals_adj), start=1):
            rows.append(
                {"cluster": grp, "rank": rank, "gene": g,
                 "log2FC": float(l), "pval_adj": float(p)}
            )
    df = pd.DataFrame(rows)
    out_path = os.path.join(RESULTS_DIR, "markers_by_cluster.csv")
    df.to_csv(out_path, index=False)
    print(f"==> Saved markers: {out_path}")
    return top_genes_per_cluster


def annotate_celltypes(top_genes_per_cluster):
    """Score each cluster against the PBMC marker dictionary -> draft label.
    각 클러스터의 상위 마커를 PBMC 마커 사전과 대조해 세포 유형 초안을 부여합니다.
    Scoring: count how many of a cell type's markers appear in a cluster's top genes,
    weighted by rank (earlier = stronger).
    """
    rows = []
    for cluster, top_genes in top_genes_per_cluster.items():
        # rank weight: gene at position i contributes (len - i).
        rank_weight = {g: (len(top_genes) - i) for i, g in enumerate(top_genes)}
        best_type, best_score, hits_for_best = "Unknown", 0.0, []
        scores = {}
        for celltype, markers in PBMC_MARKERS.items():
            hit_genes = [m for m in markers if m in rank_weight]
            score = sum(rank_weight[m] for m in hit_genes)
            scores[celltype] = score
            if score > best_score:
                best_type, best_score, hits_for_best = celltype, score, hit_genes
        rows.append(
            {
                "cluster": cluster,
                "draft_celltype": best_type if best_score > 0 else "Unknown",
                "matched_markers": ";".join(hits_for_best),
                "score": best_score,
                "top5_genes": ";".join(top_genes[:5]),
            }
        )
    df = pd.DataFrame(rows).sort_values("cluster", key=lambda s: s.astype(int))
    out_path = os.path.join(RESULTS_DIR, "celltype_draft.csv")
    df.to_csv(out_path, index=False)
    print(f"==> Saved draft cell-type annotation: {out_path}")
    return df


def main():
    args = parse_args()
    sc.settings.verbosity = 1
    sc.settings.figdir = RESULTS_DIR
    os.makedirs(RESULTS_DIR, exist_ok=True)

    adata = load_matrix(args.matrix)
    adata = run_qc(adata, args)
    adata = normalize_and_reduce(adata, args)
    adata = cluster_and_markers(adata, args)
    top_genes = export_markers(adata, top_n=25)
    celltype_df = annotate_celltypes(top_genes)

    # --- Summary table to stdout / 요약 표 출력 ------------------------------
    counts = adata.obs["leiden"].value_counts().sort_index()
    summary = celltype_df.copy()
    summary["n_cells"] = summary["cluster"].map(lambda c: int(counts.get(c, 0)))
    print("\n=========================== SUMMARY ===========================")
    print(f"Cells after QC : {adata.n_obs}")
    print(f"Clusters       : {adata.obs['leiden'].nunique()}")
    print("---------------------------------------------------------------")
    print(
        summary[["cluster", "n_cells", "draft_celltype",
                 "matched_markers", "top5_genes"]].to_string(index=False)
    )
    print("===============================================================")

    # Persist a tiny run summary so 05_make_report.sh can label the PDF exactly.
    # 05_make_report.sh가 PDF 표지에 정확한 수치를 넣도록 요약을 저장합니다.
    with open(os.path.join(RESULTS_DIR, "run_summary.txt"), "w") as fh:
        fh.write(f"cells_after_qc,{adata.n_obs}\n")
        fh.write(f"n_clusters,{adata.obs['leiden'].nunique()}\n")
        fh.write(f"genes_detected,{int((adata.X.sum(axis=0) > 0).sum())}\n")

    print("\nNext: open 04_ai_coscientist_prompts.md and paste these results")
    print("into the GHBIO AI Co-Scientist for hypothesis generation.")


if __name__ == "__main__":
    main()
