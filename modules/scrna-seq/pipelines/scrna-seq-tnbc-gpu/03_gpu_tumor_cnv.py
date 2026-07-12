#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
03_gpu_tumor_cnv.py  —  Gao et al., Nature Biotechnology 2021 (GSE148673), copyKAT
==================================================================================
Modern GPU reproduction of the central copyKAT result on a raw TNBC 10x sample:

  "You can read genome-wide copy-number aberrations (CNAs) straight out of the
   single-cell TRANSCRIPTOME, and use them to separate ANEUPLOID tumor cells from
   DIPLOID normal (immune/stromal) cells — and to resolve tumor SUBCLONES."

Pipeline / 파이프라인:
    STARsolo count matrix
      -> QC + filtering
      -> GPU scVI latent space (PyTorch/CUDA) -> neighbors -> UMAP -> Leiden
      -> Wilcoxon markers + breast tumor-ecosystem cell-type annotation
      -> inferCNV: order genes along the genome, smooth over windows, baseline against
         immune/stromal (diploid) reference cells  ->  per-cell aneuploidy score
      -> classify each cell tumor(aneuploid) / normal(diploid)   [copyKAT reproduction]
      -> cluster the tumor cells' CNV profiles into SUBCLONES
      -> figures + tables + h5ad for the AI hand-off / report.

This is a MODERN REANALYSIS from raw reads, not a bit-for-bit rerun of the authors'
copyKAT R package. It reproduces the *finding* (CNV separates tumor from normal),
with different, GPU-accelerated tooling. Malignancy is inferred, not proven.

Runs in the GPU venv from 00b_setup_gpu.sh:
    ~/ghbio-venv-gpu/tnbc-copykat/bin/python 03_gpu_tumor_cnv.py
"""

import argparse
import os
import re
import sys

import numpy as np
import pandas as pd
import scanpy as sc
import matplotlib

matplotlib.use("Agg")  # headless: write figures without a display
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# -----------------------------------------------------------------------------
# Paths / 경로.  GHBIO_RESULTS points at THIS pipeline's project dir (injected by
# the extension); falls back to the legacy path for manual runs.
# -----------------------------------------------------------------------------
HOME = os.path.expanduser("~")
RESULTS_DIR = os.environ.get("GHBIO_RESULTS", os.path.join(HOME, "ghbio-tutorial", "results"))
DEFAULT_MATRIX = os.path.join(RESULTS_DIR, "starsolo", "Solo.out", "Gene", "filtered")
REF_DIR = os.path.join(HOME, "ghbio-tutorial", "ref")
GTF = os.path.join(REF_DIR, "refdata-gex-GRCh38-2020-A", "genes", "genes.gtf")
GENEPOS_CACHE = os.path.join(REF_DIR, "gene_positions_grch38.tsv")

# Blue-white-red diverging map for the CNV log-ratio (copyKAT / inferCNV palette).
CNV_CMAP = LinearSegmentedColormap.from_list(
    "cnv", ["#2166ac", "#4393c3", "#f7f7f7", "#d6604d", "#b2182b"])

# -----------------------------------------------------------------------------
# Breast tumor-ecosystem marker dictionary. A dissociated TNBC tumor contains
# malignant epithelial cells plus the tumor microenvironment (immune + stroma).
# Immune/stromal lineages are DIPLOID and serve as the inferCNV baseline.
# -----------------------------------------------------------------------------
BREAST_TUMOR_MARKERS = {
    "Epithelial/Tumor":   ["EPCAM", "KRT8", "KRT18", "KRT19", "KRT7", "ELF3"],
    "Basal/Myoepithelial": ["KRT5", "KRT14", "KRT17", "TP63", "MYLK"],
    "Luminal":            ["ESR1", "FOXA1", "GATA3", "XBP1", "AGR2"],
    "Proliferating":      ["MKI67", "TOP2A", "CENPF", "UBE2C"],
    "T cell":             ["CD3D", "CD3E", "CD2", "CD8A", "IL7R"],
    "NK cell":            ["NKG7", "GNLY", "KLRD1"],
    "B / Plasma":         ["CD79A", "MS4A1", "MZB1", "IGHG1", "JCHAIN"],
    "Myeloid/Macrophage": ["LYZ", "CD68", "CD14", "C1QC", "AIF1", "FCGR3A"],
    "Mast cell":          ["TPSAB1", "CPA3", "MS4A2"],
    "Dendritic":          ["CLEC9A", "FCER1A", "LILRA4"],
    "Endothelial":        ["PECAM1", "VWF", "CLDN5", "CLEC14A"],
    "Fibroblast/CAF":     ["COL1A1", "DCN", "LUM", "PDGFRB", "FAP"],
}
# Lineages treated as the DIPLOID reference for inferCNV (never epithelial/tumor).
DIPLOID_REFERENCE_TYPES = {
    "T cell", "NK cell", "B / Plasma", "Myeloid/Macrophage",
    "Mast cell", "Dendritic", "Endothelial", "Fibroblast/CAF",
}
# Lineages that CAN be malignant (epithelial-derived).
EPITHELIAL_TYPES = {"Epithelial/Tumor", "Basal/Myoepithelial", "Luminal", "Proliferating"}


def parse_args():
    p = argparse.ArgumentParser(description="GPU scVI + inferCNV tumor calling (copyKAT reproduction).")
    p.add_argument("--matrix", default=DEFAULT_MATRIX,
                   help="10x filtered matrix dir (STARsolo Solo.out/Gene/filtered).")
    p.add_argument("--min-genes", type=int, default=200)
    p.add_argument("--min-cells", type=int, default=3)
    p.add_argument("--max-pct-mito", type=float, default=20.0)
    p.add_argument("--max-genes", type=int, default=7000)
    p.add_argument("--resolution", type=float, default=1.0)
    p.add_argument("--n-latent", type=int, default=30)
    p.add_argument("--max-epochs", type=int, default=200)
    return p.parse_args()


# -----------------------------------------------------------------------------
# 1. Load the STARsolo matrix (plain MEX, like the other tutorials)
# -----------------------------------------------------------------------------
def load_matrix(matrix_path):
    if not os.path.isdir(matrix_path):
        sys.exit(f"ERROR: matrix directory not found: {matrix_path}\n"
                 "Run 02c_run_starsolo.sh first, or pass --matrix <dir>.")
    print(f"==> Loading 10x matrix from: {matrix_path}")
    if os.path.exists(os.path.join(matrix_path, "matrix.mtx.gz")):
        adata = sc.read_10x_mtx(matrix_path, var_names="gene_symbols", cache=False)
    else:
        adata = sc.read_mtx(os.path.join(matrix_path, "matrix.mtx")).T
        feat = pd.read_csv(os.path.join(matrix_path, "features.tsv"), sep="\t", header=None)
        bcs = pd.read_csv(os.path.join(matrix_path, "barcodes.tsv"), sep="\t", header=None)
        adata.var_names = feat[1].astype(str).values
        adata.var["gene_ids"] = feat[0].astype(str).values
        adata.obs_names = bcs[0].astype(str).values
    adata.var_names_make_unique()
    print(f"==> Loaded AnnData: {adata.n_obs} cells x {adata.n_vars} genes")
    return adata


def run_qc(adata, args):
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)
    adata.obs["pct_mito"] = adata.obs["pct_counts_mt"]
    os.makedirs(RESULTS_DIR, exist_ok=True)
    sc.pl.violin(adata, ["n_genes_by_counts", "total_counts", "pct_mito"],
                 jitter=0.4, multi_panel=True, show=False)
    plt.savefig(os.path.join(RESULTS_DIR, "qc_violin.png"), dpi=150, bbox_inches="tight")
    plt.close()
    n_before = adata.n_obs
    sc.pp.filter_cells(adata, min_genes=args.min_genes)
    sc.pp.filter_genes(adata, min_cells=args.min_cells)
    adata = adata[adata.obs["pct_mito"] < args.max_pct_mito].copy()
    adata = adata[adata.obs["n_genes_by_counts"] < args.max_genes].copy()
    print(f"==> QC filtering: {n_before} -> {adata.n_obs} cells")
    return adata


# -----------------------------------------------------------------------------
# 2. GPU scVI latent space -> neighbors -> UMAP -> Leiden
# -----------------------------------------------------------------------------
def gpu_cluster(adata, args):
    import scvi
    import torch
    if not torch.cuda.is_available():
        sys.exit("ERROR: CUDA is unavailable. This GPU tutorial refuses a silent CPU fallback.\n"
                 "Run 00b_setup_gpu.sh and check the NVIDIA driver / PyTorch wheel.")
    print(f"==> GPU detected: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}")

    adata.layers["counts"] = adata.X.copy()  # keep raw integer counts for scVI
    # Single 10x sample -> one batch. scVI still gives a denoised latent space.
    adata.obs["sample"] = "TNBC1"
    adata.obs["sample"] = adata.obs["sample"].astype("category")

    scvi.settings.seed = 2021
    torch.set_float32_matmul_precision("high")
    scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="sample")
    model = scvi.model.SCVI(adata, n_latent=args.n_latent, n_layers=2, gene_likelihood="nb")
    print(f"==> Training GPU scVI (up to {args.max_epochs} epochs, early stopping)...")
    model.train(max_epochs=args.max_epochs, early_stopping=True,
                accelerator="gpu", devices=1, enable_progress_bar=False)
    adata.obsm["X_scVI"] = model.get_latent_representation()

    sc.pp.neighbors(adata, use_rep="X_scVI", n_neighbors=15)
    sc.tl.umap(adata, random_state=2021)
    sc.tl.leiden(adata, resolution=args.resolution, key_added="leiden",
                 flavor="igraph", n_iterations=2, directed=False)
    print(f"==> Leiden found {adata.obs['leiden'].nunique()} clusters on the scVI latent space.")

    # Log-normalized expression for human-readable markers (keep counts in the layer).
    adata.X = adata.layers["counts"].copy()
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    adata.raw = adata

    sc.pl.umap(adata, color="leiden", legend_loc="on data", show=False)
    plt.savefig(os.path.join(RESULTS_DIR, "umap_clusters.png"), dpi=150, bbox_inches="tight")
    plt.close()

    sc.tl.rank_genes_groups(adata, groupby="leiden", method="wilcoxon")
    return adata


def export_markers(adata, top_n=25):
    res = adata.uns["rank_genes_groups"]
    groups = res["names"].dtype.names
    rows, top_by_cluster = [], {}
    for grp in groups:
        names = res["names"][grp][:top_n]
        lfc = res["logfoldchanges"][grp][:top_n]
        padj = res["pvals_adj"][grp][:top_n]
        top_by_cluster[grp] = list(names)
        for rank, (g, l, p) in enumerate(zip(names, lfc, padj), start=1):
            rows.append({"cluster": grp, "rank": rank, "gene": g,
                         "log2FC": float(l), "pval_adj": float(p)})
    pd.DataFrame(rows).to_csv(os.path.join(RESULTS_DIR, "markers_by_cluster.csv"), index=False)
    print("==> Saved markers_by_cluster.csv")
    return top_by_cluster


def annotate_celltypes(top_by_cluster):
    rows = []
    for cluster, top_genes in top_by_cluster.items():
        rank_weight = {g: (len(top_genes) - i) for i, g in enumerate(top_genes)}
        best_type, best_score, hits = "Unknown", 0.0, []
        for celltype, markers in BREAST_TUMOR_MARKERS.items():
            hit = [m for m in markers if m in rank_weight]
            score = sum(rank_weight[m] for m in hit)
            if score > best_score:
                best_type, best_score, hits = celltype, score, hit
        rows.append({"cluster": cluster,
                     "draft_celltype": best_type if best_score > 0 else "Unknown",
                     "matched_markers": ";".join(hits), "score": best_score,
                     "top5_genes": ";".join(top_genes[:5])})
    df = pd.DataFrame(rows).sort_values("cluster", key=lambda s: s.astype(int)).reset_index(drop=True)
    df.to_csv(os.path.join(RESULTS_DIR, "celltype_draft.csv"), index=False)
    print("==> Saved celltype_draft.csv")
    return df


# -----------------------------------------------------------------------------
# 3. inferCNV: gene positions, genome-ordered smoothing, diploid baseline
# -----------------------------------------------------------------------------
def gene_positions():
    if os.path.exists(GENEPOS_CACHE):
        print(f"==> Using cached gene positions: {GENEPOS_CACHE}")
        return pd.read_csv(GENEPOS_CACHE, sep="\t")
    if not os.path.exists(GTF):
        sys.exit(f"ERROR: GTF not found: {GTF}\nThe GRCh38 reference (step 2b) is required for inferCNV.")
    print(f"==> Building gene-position cache from GTF (first run only): {GTF}")
    name_re = re.compile(r'gene_name "([^"]+)"')
    rows, seen = [], set()
    with open(GTF) as fh:
        for line in fh:
            if "\tgene\t" not in line:
                continue
            f = line.split("\t")
            if len(f) < 9 or f[2] != "gene":
                continue
            m = name_re.search(f[8])
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            rows.append((m.group(1), f[0], int(f[3])))
    df = pd.DataFrame(rows, columns=["gene", "chrom", "start"])
    os.makedirs(REF_DIR, exist_ok=True)
    df.to_csv(GENEPOS_CACHE, sep="\t", index=False)
    print(f"==> Cached {len(df)} gene positions -> {GENEPOS_CACHE}")
    return df


def chrom_order(chrom):
    c = str(chrom).replace("chr", "")
    if c == "X":
        return 23
    if c == "Y":
        return 24
    try:
        return int(c)
    except ValueError:
        return 99  # scaffolds / MT -> dropped


def _sliding_mean(block, k):
    """Fast per-cell sliding-window mean along genes (axis=1) via cumulative sum."""
    if block.shape[1] <= 1 or k <= 1:
        return block
    k = min(k, block.shape[1])
    csum = np.cumsum(block, axis=1)
    out = np.empty_like(block)
    half = k // 2
    n = block.shape[1]
    for j in range(n):
        lo = max(0, j - half)
        hi = min(n, lo + k)
        lo = max(0, hi - k)
        s = csum[:, hi - 1] - (csum[:, lo - 1] if lo > 0 else 0.0)
        out[:, j] = s / (hi - lo)
    return out


def infer_cnv(adata, celltype_df):
    """Reproduce the copyKAT idea: infer genome-wide CNV per cell, baselined against a
    diploid (immune/stromal) reference, then score aneuploidy and call tumor vs normal."""
    print("==> inferCNV: ordering genes along the genome and smoothing...")
    pos = gene_positions()
    pos["ord"] = pos["chrom"].map(chrom_order)
    pos = pos[pos["ord"] < 99].copy()

    raw = adata.raw if adata.raw is not None else adata
    expr_mean = np.asarray(raw.X.mean(axis=0)).ravel()
    expressed = set(np.array(raw.var_names)[expr_mean > 0.05])
    pos = pos[pos["gene"].isin(expressed) & pos["gene"].isin(set(raw.var_names))]
    pos = pos.sort_values(["ord", "start"]).drop_duplicates("gene")
    genes = pos["gene"].tolist()
    if len(genes) < 500:
        sys.exit("ERROR: too few positioned genes for inferCNV — check GTF/matrix gene symbols.")
    print(f"==> {len(genes)} positioned, expressed genes ordered along the genome.")

    E = raw[:, genes].X
    E = np.asarray(E.todense()) if hasattr(E, "todense") else np.asarray(E, dtype=np.float32)
    E = E.astype(np.float32)
    # Relative expression: center each gene across cells, clip to [-3, 3] (inferCNV style).
    E -= E.mean(axis=0, keepdims=True)
    np.clip(E, -3.0, 3.0, out=E)

    ords = pos["ord"].values
    cnv = np.zeros_like(E)
    for ch in np.unique(ords):
        cols = np.where(ords == ch)[0]
        cnv[:, cols] = _sliding_mean(E[:, cols], k=100)

    # ---- Diploid reference: immune/stromal clusters (never epithelial) -------
    draft_by_cluster = dict(zip(celltype_df["cluster"].astype(str),
                                celltype_df["draft_celltype"]))
    leiden = adata.obs["leiden"].astype(str).values
    cell_type = np.array([draft_by_cluster.get(c, "Unknown") for c in leiden])
    ref_mask = np.isin(cell_type, list(DIPLOID_REFERENCE_TYPES))
    if ref_mask.sum() < 20:
        # Fallback: use the lowest-aneuploidy 30% of cells as a pseudo-diploid baseline.
        print("==> WARNING: few immune/stromal reference cells; using low-CNV cells as baseline.")
        prelim = (cnv ** 2).mean(axis=1)
        ref_mask = prelim <= np.quantile(prelim, 0.30)
    print(f"==> Diploid reference cells: {int(ref_mask.sum())} "
          f"({100*ref_mask.mean():.1f}% of cells)")
    cnv -= cnv[ref_mask].mean(axis=0, keepdims=True)

    # ---- Per-cell aneuploidy score + tumor/normal call -----------------------
    cnv_signal = (cnv ** 2).mean(axis=1)
    adata.obs["cnv_signal"] = cnv_signal
    ref_scores = cnv_signal[ref_mask]
    threshold = float(ref_scores.mean() + 2.0 * ref_scores.std())
    is_epi = np.isin(cell_type, list(EPITHELIAL_TYPES))
    # A cell is called tumor if its aneuploidy clearly exceeds the diploid baseline.
    # Epithelial identity reinforces the call but is not required (some tumor cells lose EPCAM).
    call = np.where(cnv_signal > threshold, "tumor", "normal")
    adata.obs["tumor_call"] = pd.Categorical(call, categories=["normal", "tumor"])
    adata.obs["is_epithelial"] = is_epi

    n_tumor = int((call == "tumor").sum())
    print(f"==> Aneuploidy threshold (ref mean + 2sd): {threshold:.4f}")
    print(f"==> Tumor (aneuploid) cells: {n_tumor} / {adata.n_obs} "
          f"({100.0*n_tumor/adata.n_obs:.1f}%)")

    _plot_cnv_heatmap(adata, cnv, ords, pos)
    _plot_umap_tumor(adata)

    # Save per-cell calls for the report.
    pd.DataFrame({
        "barcode": adata.obs_names,
        "leiden": leiden,
        "draft_celltype": cell_type,
        "cnv_signal": np.round(cnv_signal, 5),
        "call": call,
    }).to_csv(os.path.join(RESULTS_DIR, "tumor_normal_calls.csv"), index=False)
    print("==> Saved tumor_normal_calls.csv")

    # Compact per-cluster CNV summary — small enough to feed the AI panel as context.
    df = pd.DataFrame({"leiden": leiden, "draft_celltype": cell_type,
                       "cnv_signal": cnv_signal, "is_tumor": (call == "tumor")})
    summ = (df.groupby("leiden")
              .agg(n_cells=("leiden", "size"),
                   draft_celltype=("draft_celltype", "first"),
                   median_cnv_signal=("cnv_signal", "median"),
                   pct_tumor_calls=("is_tumor", lambda s: round(100.0 * s.mean(), 1)))
              .reset_index()
              .sort_values("leiden", key=lambda s: s.astype(int)))
    summ["median_cnv_signal"] = summ["median_cnv_signal"].round(4)
    summ["cluster_call"] = np.where(summ["pct_tumor_calls"] >= 50.0, "tumor", "normal")
    summ.to_csv(os.path.join(RESULTS_DIR, "cnv_cluster_summary.csv"), index=False)
    print("==> Saved cnv_cluster_summary.csv")
    return adata, cnv, ords, pos, ref_mask


def _plot_cnv_heatmap(adata, cnv, ords, pos):
    call = adata.obs["tumor_call"].values
    order = np.lexsort((adata.obs["cnv_signal"].values, (call == "tumor").astype(int)))
    M = cnv[order]
    is_tumor = (call[order] == "tumor")
    fig, ax = plt.subplots(figsize=(13, 8))
    im = ax.imshow(M, aspect="auto", cmap=CNV_CMAP, vmin=-0.5, vmax=0.5, interpolation="nearest")
    # Chromosome boundaries + labels.
    bounds, labels_pos, prev, startc = [], [], None, 0
    for i, ch in enumerate(ords):
        if ch != prev:
            if prev is not None:
                bounds.append(i)
                labels_pos.append(((startc + i) / 2, prev))
                startc = i
            prev = ch
    labels_pos.append(((startc + len(ords)) / 2, prev))
    for b in bounds:
        ax.axvline(b, color="#333", lw=0.4)
    lab = {23: "X", 24: "Y"}
    ax.set_xticks([p for p, _ in labels_pos])
    ax.set_xticklabels([lab.get(int(c), str(int(c))) for _, c in labels_pos], fontsize=7)
    split = int(np.searchsorted(is_tumor, True))
    ax.axhline(split, color="black", lw=1.2)
    ax.text(-0.01, split / 2, "Normal (diploid)", rotation=90, va="center", ha="right",
            transform=ax.get_yaxis_transform(), fontsize=9, color="#555")
    ax.text(-0.01, (split + len(is_tumor)) / 2, "Tumor (aneuploid)", rotation=90, va="center",
            ha="right", transform=ax.get_yaxis_transform(), fontsize=9, color="#b2182b")
    ax.set_yticks([])
    ax.set_xlabel("Chromosomal position (genes ordered along the genome)")
    ax.set_title("Inferred copy-number aberrations separate tumor from normal cells\n"
                 "Gao et al., Nat Biotechnol 2021 (copyKAT), reproduced from raw TNBC 10x")
    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
    cbar.set_label("Inferred CNV (log-ratio vs diploid baseline)")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "cnv_heatmap.png"), dpi=150)
    plt.close(fig)
    print("==> Saved cnv_heatmap.png")


def _plot_umap_tumor(adata):
    um = adata.obsm["X_umap"]
    is_t = (adata.obs["tumor_call"].values == "tumor")
    fig, ax = plt.subplots(figsize=(7.2, 6))
    ax.scatter(um[~is_t, 0], um[~is_t, 1], s=6, c="#4393c3", linewidths=0,
               label=f"Normal / diploid ({int((~is_t).sum())})")
    ax.scatter(um[is_t, 0], um[is_t, 1], s=6, c="#b2182b", linewidths=0,
               label=f"Tumor / aneuploid ({int(is_t.sum())})")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel("UMAP1"); ax.set_ylabel("UMAP2")
    ax.set_title("UMAP colored by inferred CNV status (tumor vs normal)")
    ax.legend(loc="best", fontsize=8, markerscale=2, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "umap_tumor_normal.png"), dpi=150)
    plt.close(fig)
    print("==> Saved umap_tumor_normal.png")


# -----------------------------------------------------------------------------
# 4. Tumor subclones: cluster the aneuploid cells' CNV profiles
# -----------------------------------------------------------------------------
def find_subclones(adata, cnv, max_k=3):
    is_t = (adata.obs["tumor_call"].values == "tumor")
    adata.obs["subclone"] = "—"
    if is_t.sum() < 60:
        print("==> Too few tumor cells for subclone analysis — skipping.")
        return adata
    from sklearn.cluster import KMeans
    Xt = cnv[is_t]
    k = min(max_k, max(2, is_t.sum() // 80))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xt)
    labels = np.array([f"S{c+1}" for c in km.labels_])
    sub = np.array(["—"] * adata.n_obs, dtype=object)
    sub[np.where(is_t)[0]] = labels
    adata.obs["subclone"] = pd.Categorical(sub)
    print(f"==> Found {k} tumor subclones (KMeans on CNV profiles): "
          f"{dict(pd.Series(labels).value_counts())}")

    # Mean CNV profile per subclone (shows the distinct aberration patterns).
    fig, ax = plt.subplots(figsize=(13, 3.2 + 0.5 * k))
    for i, s in enumerate(sorted(set(labels))):
        prof = cnv[is_t][labels == s].mean(axis=0)
        ax.plot(prof + i * 0.6, lw=0.7, label=f"{s} (n={int((labels==s).sum())})")
    ax.set_yticks([]); ax.set_xlabel("Chromosomal position (genes ordered along the genome)")
    ax.set_title("Tumor subclones — mean inferred-CNV profile per subclone (offset for clarity)")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "tumor_subclones.png"), dpi=150)
    plt.close(fig)
    print("==> Saved tumor_subclones.png")

    pd.DataFrame({"subclone": labels}).value_counts().rename("n_cells").reset_index().to_csv(
        os.path.join(RESULTS_DIR, "subclone_composition.csv"), index=False)
    return adata


# -----------------------------------------------------------------------------
# 5. Composition chart + run summary
# -----------------------------------------------------------------------------
def plot_composition(adata, celltype_df):
    draft_by_cluster = dict(zip(celltype_df["cluster"].astype(str), celltype_df["draft_celltype"]))
    leiden = adata.obs["leiden"].astype(str).values
    cell_type = pd.Series([draft_by_cluster.get(c, "Unknown") for c in leiden])
    by_type = cell_type.value_counts()
    order = [t for t in BREAST_TUMOR_MARKERS if t in by_type.index]
    order += [t for t in by_type.index if t not in order]
    by_type = by_type.reindex(order).dropna()
    total = int(by_type.sum()) or 1
    labels = list(by_type.index)[::-1]
    vals = [int(v) for v in by_type.values][::-1]
    colors = plt.cm.tab20(np.linspace(0, 1, max(len(labels), 1)))
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.55 * len(labels) + 1)))
    bars = ax.barh(labels, vals, color=colors)
    for b, v in zip(bars, vals):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {v} ({100.0*v/total:.1f}%)",
                va="center", ha="left", fontsize=9)
    ax.set_xlabel("Number of cells")
    ax.set_title("TNBC tumor ecosystem — cell-type composition (draft)\n"
                 "malignant epithelial + immune/stromal microenvironment")
    ax.margins(x=0.18)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "tnbc_composition.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("==> Saved tnbc_composition.png")


def write_summary(adata):
    n_tumor = int((adata.obs["tumor_call"] == "tumor").sum())
    n_normal = int((adata.obs["tumor_call"] == "normal").sum())
    n_sub = adata.obs["subclone"].nunique() - (1 if "—" in set(adata.obs["subclone"]) else 0)
    with open(os.path.join(RESULTS_DIR, "run_summary.txt"), "w") as fh:
        fh.write(f"cells_after_qc,{adata.n_obs}\n")
        fh.write(f"n_clusters,{adata.obs['leiden'].nunique()}\n")
        fh.write(f"genes_detected,{int((adata.layers['counts'].sum(axis=0) > 0).sum())}\n")
        fh.write(f"tumor_cells,{n_tumor}\n")
        fh.write(f"normal_cells,{n_normal}\n")
        fh.write(f"subclones,{max(n_sub, 0)}\n")
    print(f"==> {adata.n_obs} cells | {n_tumor} tumor | {n_normal} normal | {max(n_sub,0)} subclones")


def main():
    args = parse_args()
    sc.settings.verbosity = 1
    sc.settings.figdir = RESULTS_DIR
    os.makedirs(RESULTS_DIR, exist_ok=True)

    adata = load_matrix(args.matrix)
    adata = run_qc(adata, args)
    adata = gpu_cluster(adata, args)
    top_by_cluster = export_markers(adata, top_n=25)
    celltype_df = annotate_celltypes(top_by_cluster)
    plot_composition(adata, celltype_df)
    adata, cnv, ords, pos, ref_mask = infer_cnv(adata, celltype_df)
    adata = find_subclones(adata, cnv)
    write_summary(adata)

    adata.write(os.path.join(RESULTS_DIR, "tnbc_processed.h5ad"))
    print("==> Saved tnbc_processed.h5ad")
    print("\nNext: open the AI Analysis step for interpretation & hypotheses.")


if __name__ == "__main__":
    main()
