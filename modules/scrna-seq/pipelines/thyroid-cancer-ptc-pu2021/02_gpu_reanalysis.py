#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Pu 2021, PTC — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we start from the authors' RAW
count matrices (GSE184362, 23 samples, no cell-type labels are distributed) and
RE-DERIVE the whole analysis with our own, freshly-written, GPU-accelerated code:

  1. load every per-sample 10x triplet (barcodes/features/matrix) and merge on
     the COMMON gene set (the samples use two different feature references),
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p) — the deposit is raw counts,
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony batch-integration across the 11 patients (harmonypy),
  7. neighbours → Leiden clustering → UMAP (Scanpy),
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical thyroid-ecosystem signatures),
 10. an INDEPENDENT malignant-vs-normal thyrocyte split (unsupervised GMM on a
     PTC malignancy − thyroid-differentiation signature) — the authors used a
     TCGA-trained KNN classifier; we deliberately use a different, unsupervised
     method so agreement in step 3 means two independent routes converge (제6조).

No author cell-type labels exist to consume; the validation step (03) instead
compares our independent result against the paper's PUBLISHED CLAIMS (marker
recovery, malignant thyroid-differentiation-score drop, the TMSB4X progression
gradient, and malignant enrichment by tissue site).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_thyrocyte.csv      DE (our malignant vs our normal thyrocyte)
  thyrocyte_summary.csv         our thyrocyte split counts + mean scores (TDS etc.)
  composition_by_site.csv      cell-type % per tissue site
  malignant_by_site.csv        malignant-thyrocyte % among thyrocytes per site + mean TMSB4X
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, composition.png
  qc_summary.csv, provenance.json, run_summary.txt
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager  # noqa: E402  (needed before pyplot to pick a CJK font)
for _f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
    if any(_f == f.name for f in matplotlib.font_manager.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scanpy as sc  # noqa: E402
import scipy.io  # noqa: E402
import torch  # noqa: E402
from scipy import sparse  # noqa: E402


@contextmanager
def progress(label: str):
    started = time.monotonic()
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(30):
            print(f"⏳ {label} — still running ({(time.monotonic()-started)/60:.1f} min)", flush=True)

    print(f"▶ {label}", flush=True)
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join(timeout=1)
        print(f"✓ {label} — done ({(time.monotonic()-started)/60:.1f} min)", flush=True)


# ---- GPU (PyTorch) dense linear algebra --------------------------------------
def gpu_scale(matrix: np.ndarray, device: torch.device, scale_max: float) -> torch.Tensor:
    """z-score each gene to mean 0 / unit variance, clip at scale_max (Seurat ScaleData)."""
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    return torch.clamp((x - mean) / std, max=scale_max)


def gpu_pca(scaled: torch.Tensor, n_comps: int) -> np.ndarray:
    """PCA scores via SVD on centered, scaled data: scores = U*S (top n_comps)."""
    scaled = scaled - scaled.mean(dim=0, keepdim=True)
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    return (u[:, :n_comps] * s[:n_comps]).cpu().numpy()


# ---- canonical thyroid-ecosystem markers (for INDEPENDENT annotation) --------
# Markers named by Pu et al. 2021 + standard canonical lineage markers.
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Thyrocyte": ["TG", "EPCAM", "KRT18", "KRT19", "TFF3", "TPO", "DIO2", "TSHR", "PAX8", "NKX2-1"],
    "T-NK cell": ["CD3D", "CD3E", "CD3G", "CD247", "CD8A", "IL7R", "NKG7", "KLRD1", "GNLY"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "IGHM", "IGHD", "CD19"],
    "Plasma cell": ["MZB1", "SDC1", "XBP1", "IGHG1", "PRDM1", "DERL3"],
    "Myeloid": ["LYZ", "S100A8", "S100A9", "CD14", "CD68", "CD163", "C1QA", "C1QB", "FCGR3A"],
    "Dendritic cell": ["CD1C", "FCER1A", "CLEC9A", "LILRA4", "LAMP3"],
    "Mast cell": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT"],
    "Endothelial": ["PECAM1", "CDH5", "VWF", "CD34", "EGFL7", "RAMP2"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "ACTA2", "TAGLN", "DCN", "PDGFRB", "RGS5"],
}
# PTC malignant thyrocyte signature (up) vs thyroid-differentiation signature (down),
# from Pu et al. 2021 (malignant clusters c03–c09 vs normal follicular c01).
MALIGNANT_SIG = ["S100A4", "FN1", "IGFBP6", "KRT19", "TMSB4X", "LGALS1", "HMGA2",
                 "SDC4", "ECM1", "EGR1", "MYC", "SOX4"]
# Thyroid Differentiation Score (TDS) genes — high in normal follicular cells.
DIFFERENTIATION_SIG = ["TG", "TPO", "IYD", "TFF3", "DIO2", "SLC5A5", "TSHR", "PAX8", "FOXE1"]
THYROCYTE_TYPES = {"Thyrocyte"}

# tissue-site canonicalisation + a normal→malignant severity rank (for the TMSB4X gradient claim)
SITE_RANK = {"Paratumor": 0, "Primary tumor": 1, "LN metastasis": 2, "Distant metastasis": 3}


def map_site(site_raw: str) -> str:
    """Map a sample's site token to a canonical tissue. Check 'LN' BEFORE 'T' —
    'LeftLN'/'RightLN' both contain a 'T', so substring-matching 'T' first would
    mislabel every lymph-node sample as a primary tumour (a real bug)."""
    s = site_raw.upper()
    if "LN" in s:
        return "LN metastasis"
    if s == "SC" or "SC" in s:
        return "Distant metastasis"
    if s == "P" or s.startswith("PARA"):
        return "Paratumor"
    if s == "T" or "TUMOR" in s or "TUMOUR" in s:
        return "Primary tumor"
    return "Other"


def read_triplet(matrix_path: str) -> ad.AnnData | None:
    """Read one prefixed 10x triplet (…_matrix.mtx.gz / _barcodes.tsv.gz / _features.tsv.gz)."""
    prefix = re.sub(r"matrix\.mtx(\.gz)?$", "", matrix_path)
    bc = prefix + "barcodes.tsv.gz"
    ft = prefix + "features.tsv.gz"
    if not (os.path.exists(bc) and os.path.exists(ft)):
        # some deposits use "genes.tsv" instead of "features.tsv"
        alt = prefix + "genes.tsv.gz"
        ft = ft if os.path.exists(ft) else alt
    if not (os.path.exists(bc) and os.path.exists(ft)):
        print(f"    WARNING: missing barcodes/features for {os.path.basename(matrix_path)} — skipping.", file=sys.stderr)
        return None
    with gzip.open(matrix_path, "rb") as fh:
        m = scipy.io.mmread(fh).T.tocsr()          # 10x mtx is genes×cells → transpose to cells×genes
    barcodes = pd.read_csv(bc, header=None, sep="\t")[0].astype(str).tolist()
    feats = pd.read_csv(ft, header=None, sep="\t")
    symbols = (feats[1] if feats.shape[1] >= 2 else feats[0]).astype(str).tolist()
    a = ad.AnnData(X=m)
    a.obs_names = barcodes
    a.var_names = symbols
    a.var_names_make_unique()
    return a


def sample_meta(matrix_path: str) -> tuple[str, str, str]:
    """From GSM5585102_PTC1_T_matrix.mtx.gz → (sample='PTC1_T', patient='PTC1', site='Primary tumor')."""
    base = os.path.basename(matrix_path)
    stem = re.sub(r"_?matrix\.mtx(\.gz)?$", "", base)
    tokens = stem.split("_")
    # drop a leading GSM accession token if present
    if tokens and re.match(r"^GSM\d+$", tokens[0]):
        tokens = tokens[1:]
    patient = tokens[0] if tokens else "NA"
    site_raw = "".join(tokens[1:]).upper() if len(tokens) > 1 else ""
    site = map_site(site_raw)
    return "_".join(tokens), patient, site


def annotate(adata: ad.AnnData, groupby: str) -> pd.DataFrame:
    score_cols = {}
    for sig, genes in CELL_TYPE_MARKERS.items():
        present = [g for g in genes if g in adata.var_names]
        col = f"_s_{sig}"
        if present:
            sc.tl.score_genes(adata, present, score_name=col, use_raw=False)
        else:
            adata.obs[col] = 0.0
        score_cols[sig] = col
    per = adata.obs.groupby(groupby, observed=True)[list(score_cols.values())].mean()
    per.columns = list(score_cols.keys())
    assigned = per.idxmax(axis=1)
    adata.obs["cell_type"] = adata.obs[groupby].map(assigned).astype("category")
    table = per.copy()
    table.insert(0, "n_cells", adata.obs[groupby].value_counts().reindex(table.index).astype(int))
    table.insert(1, "cell_type", assigned.values)
    table.index.name = "cluster"
    adata.obs.drop(columns=list(score_cols.values()), inplace=True)
    return table.reset_index()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=os.path.expanduser(
        "~/ghbio-tutorial/data/ptc-pu2021/unpacked"))
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--n-comps", type=int, default=50)
    ap.add_argument("--n-pcs", type=int, default=30)
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--scale-max", type=float, default=10.0)
    ap.add_argument("--min-genes", type=int, default=300)
    ap.add_argument("--min-cells", type=int, default=10)
    ap.add_argument("--max-mito", type=float, default=20.0)
    ap.add_argument("--batch-key", default="patient")
    ap.add_argument("--seed", type=int, default=2021)
    ap.add_argument("--no-harmony", action="store_true", help="skip Harmony batch integration")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable; this GPU reanalysis refuses CPU fallback.", file=sys.stderr)
        sys.exit(2)
    device = torch.device("cuda")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    sc.settings.verbosity = 1
    R = args.results
    os.makedirs(R, exist_ok=True)
    print(f"GPU: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}", flush=True)

    matrices = sorted(glob.glob(os.path.join(args.source, "**", "*matrix.mtx*"), recursive=True))
    if not matrices:
        print(f"ERROR: no *matrix.mtx* under {args.source} (run step 1 first).", file=sys.stderr)
        sys.exit(1)

    # --- load + merge every per-sample matrix on the COMMON gene set -----------
    with progress(f"Loading {len(matrices)} per-sample 10x matrices"):
        adatas = []
        for mp in matrices:
            a = read_triplet(mp)
            if a is None or a.n_obs == 0:
                continue
            sample, patient, site = sample_meta(mp)
            a.obs["sample"] = sample
            a.obs["patient"] = patient
            a.obs["site"] = site
            a.obs_names = [f"{sample}_{bc}" for bc in a.obs_names]
            adatas.append(a)
        if not adatas:
            print("ERROR: no readable samples.", file=sys.stderr)
            sys.exit(1)
        # inner join keeps only genes present in every sample (feature refs differ across batches)
        adata = ad.concat(adatas, join="inner", index_unique=None, merge="same")
        adata.obs_names_make_unique()
        del adatas
    print(f"    merged: {adata.n_obs:,} cells × {adata.n_vars:,} common genes "
          f"from {adata.obs['sample'].nunique()} samples / {adata.obs['patient'].nunique()} patients", flush=True)

    # --- QC ---------------------------------------------------------------------
    with progress("QC filtering (min genes/cells, mitochondrial %)"):
        adata.var["mito"] = adata.var_names.str.upper().str.startswith("MT-")
        sc.pp.calculate_qc_metrics(adata, qc_vars=["mito"], inplace=True, percent_top=None, log1p=False)
        sc.pp.filter_cells(adata, min_genes=args.min_genes)
        sc.pp.filter_genes(adata, min_cells=args.min_cells)
        adata = adata[adata.obs["pct_counts_mito"] < args.max_mito].copy()
    n_after = adata.n_obs
    pd.DataFrame({
        "metric": ["cells_after_qc", "genes_after_qc", "median_genes_per_cell", "median_pct_mito"],
        "value": [n_after, adata.n_vars,
                  float(np.median(adata.obs["n_genes_by_counts"])),
                  round(float(np.median(adata.obs["pct_counts_mito"])), 3)],
    }).to_csv(os.path.join(R, "qc_summary.csv"), index=False)
    print(f"    after QC: {n_after:,} cells × {adata.n_vars:,} genes", flush=True)

    # --- our own normalisation (deposit is raw counts) --------------------------
    adata.layers["counts"] = adata.X.copy()
    with progress("Normalise (normalize_total 1e4 + log1p)"):
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)

    # --- HVG on the log-normalised values ---------------------------------------
    with progress("Highly-variable genes (seurat, batch-aware)"):
        sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=args.n_hvg,
                                    batch_key=args.batch_key if args.batch_key in adata.obs else None)
    hvg = np.where(adata.var["highly_variable"].to_numpy())[0]

    # --- GPU: ScaleData + PCA(SVD) on the HVGs ----------------------------------
    with progress(f"GPU z-score scaling + PCA(SVD) on {len(hvg)} HVGs (PyTorch)"):
        X = adata[:, hvg].X
        dense = np.asarray(X.todense()) if sparse.issparse(X) else np.asarray(X)
        scaled = gpu_scale(dense, device, args.scale_max)
        adata.obsm["X_pca"] = gpu_pca(scaled, args.n_comps)
        del dense, scaled
        torch.cuda.empty_cache()

    # --- Harmony batch integration across patients ------------------------------
    rep = "X_pca"
    if not args.no_harmony and args.batch_key in adata.obs and adata.obs[args.batch_key].nunique() > 1:
        try:
            import harmonypy
            with progress(f"Harmony integration across {adata.obs[args.batch_key].nunique()} patients"):
                ho = harmonypy.run_harmony(adata.obsm["X_pca"][:, : args.n_pcs],
                                           adata.obs, [args.batch_key])
                # harmonypy >=2.0 returns Z_corr as (cells, pcs); older as (pcs, cells).
                Z = np.asarray(ho.Z_corr)
                if Z.shape[0] != adata.n_obs and Z.shape[1] == adata.n_obs:
                    Z = Z.T
                adata.obsm["X_pca_harmony"] = np.ascontiguousarray(Z, dtype=np.float32)
            rep = "X_pca_harmony"
        except Exception as e:  # keep going on un-integrated PCA if Harmony fails
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.", file=sys.stderr)
    n_use = adata.obsm[rep].shape[1] if rep == "X_pca_harmony" else args.n_pcs

    # --- neighbours → Leiden → UMAP ---------------------------------------------
    with progress("Neighbours + Leiden + UMAP (Scanpy)"):
        sc.pp.neighbors(adata, use_rep=rep, n_pcs=n_use, n_neighbors=args.n_neighbors,
                        random_state=args.seed)
        sc.tl.leiden(adata, key_added="leiden_gpu", resolution=args.resolution,
                     flavor="igraph", n_iterations=2, directed=False, random_state=args.seed)
        sc.tl.umap(adata, random_state=args.seed)
    n_clusters = adata.obs["leiden_gpu"].nunique()
    print(f"    {n_clusters} Leiden clusters (resolution {args.resolution})", flush=True)

    # --- canonicalise X + checkpoint (guards the marker step) -------------------
    # The MTX→transpose→CSR merge path can leave X with unsorted/duplicate indices
    # or float64; rank_genes_groups reads X column-wise and is sensitive to that,
    # which crashed a native routine (SIGSEGV) on the real data. Force canonical
    # CSR float32, free the unused counts layer, and checkpoint so the (expensive)
    # embedding work isn't lost if anything downstream fails.
    if "counts" in adata.layers:
        del adata.layers["counts"]
    if sparse.issparse(adata.X):
        adata.X = adata.X.tocsr()
        adata.X.sort_indices()
        adata.X.sum_duplicates()
        adata.X.eliminate_zeros()
    adata.X = adata.X.astype(np.float32)
    ckpt = os.path.join(R, "_checkpoint_pre_markers.h5ad")
    with progress("Checkpoint before markers"):
        adata.write_h5ad(ckpt, compression="gzip")

    # --- Wilcoxon markers per cluster -------------------------------------------
    # Exclude tiny clusters (<3 cells) — singleton groups can crash wilcoxon.
    vc = adata.obs["leiden_gpu"].value_counts()
    mk_groups = [str(g) for g in vc[vc >= 3].index.tolist()]
    with progress("Wilcoxon markers per cluster"):
        sc.tl.rank_genes_groups(adata, "leiden_gpu", groups=mk_groups,
                                method="wilcoxon", use_raw=False, n_genes=30)
    mk = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "logfoldchanges": "log2fc"})
    mk["rank"] = mk.groupby("cluster", observed=True).cumcount() + 1
    mk = mk[mk["rank"] <= 30][["cluster", "rank", "gene", "scores", "log2fc", "pvals_adj"]]
    mk.to_csv(os.path.join(R, "markers_by_cluster.csv"), index=False)

    # --- INDEPENDENT marker-based cell-type annotation --------------------------
    with progress("Marker-based cell-type annotation (independent — no author labels exist)"):
        annotation = annotate(adata, "leiden_gpu")
    annotation.to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)
    print("    cell types: " + ", ".join(
        f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)

    # --- INDEPENDENT malignant vs normal thyrocyte split (unsupervised GMM) ------
    sig_mal = [g for g in MALIGNANT_SIG if g in adata.var_names]
    sig_dif = [g for g in DIFFERENTIATION_SIG if g in adata.var_names]
    sc.tl.score_genes(adata, sig_mal, score_name="malignancy_score", use_raw=False)
    sc.tl.score_genes(adata, sig_dif, score_name="tds_score", use_raw=False)   # thyroid differentiation score
    adata.obs["malignant_call"] = "n/a"
    thy_mask = adata.obs["cell_type"].astype(str).isin(THYROCYTE_TYPES).to_numpy()
    n_thy = int(thy_mask.sum())
    if n_thy > 20:
        from sklearn.mixture import GaussianMixture
        score = (adata.obs.loc[thy_mask, "malignancy_score"]
                 - adata.obs.loc[thy_mask, "tds_score"]).to_numpy().reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=args.seed).fit(score)
        comp = gm.predict(score)
        mal_comp = int(np.argmax(gm.means_.ravel()))   # higher (malignancy − differentiation) = malignant
        call = np.where(comp == mal_comp, "malignant thyrocyte", "normal thyrocyte")
        idx = adata.obs_names[thy_mask]
        adata.obs.loc[idx, "malignant_call"] = call
    print("    thyrocyte split: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["malignant_call"].value_counts().items()), flush=True)

    # --- DE: our malignant vs our normal thyrocyte ------------------------------
    two = adata[adata.obs["malignant_call"].isin(["malignant thyrocyte", "normal thyrocyte"])].copy()
    if two.obs["malignant_call"].nunique() == 2:
        sc.tl.rank_genes_groups(two, "malignant_call", groups=["malignant thyrocyte"],
                                reference="normal thyrocyte", method="wilcoxon", use_raw=False, n_genes=40)
        de = sc.get.rank_genes_groups_df(two, group="malignant thyrocyte").rename(
            columns={"names": "gene", "logfoldchanges": "log2fc"})
        de.insert(0, "rank", range(1, len(de) + 1))
        de[["rank", "gene", "log2fc", "pvals_adj"]].to_csv(
            os.path.join(R, "malignant_thyrocyte.csv"), index=False)

    # --- composition tables + CSVs ----------------------------------------------
    counts = adata.obs["cell_type"].value_counts()
    markers_by_type: dict[str, list[str]] = {}
    for ct in counts.index:
        clusters = annotation.loc[annotation["cell_type"] == ct, "cluster"].tolist()
        genes: list[str] = []
        for cl in clusters:
            genes += mk.loc[mk["cluster"].astype(str) == str(cl), "gene"].head(5).tolist()
        markers_by_type[ct] = list(dict.fromkeys(genes))[:5]
    total = int(adata.n_obs)
    pd.DataFrame([
        {"celltype": ct, "n_cells": int(n), "pct_of_cells": round(100 * n / total, 2),
         "top5_markers": ", ".join(markers_by_type.get(ct, []))}
        for ct, n in counts.items()
    ]).to_csv(os.path.join(R, "celltype_composition.csv"), index=False)

    comp_site = None
    if "site" in adata.obs:
        comp_site = (pd.crosstab(adata.obs["site"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp_site.to_csv(os.path.join(R, "composition_by_site.csv"))

    # thyrocyte split summary + malignant enrichment / TMSB4X gradient by site
    dsum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean"),
                 mean_tds=("tds_score", "mean")).round(4).reset_index())
    dsum.to_csv(os.path.join(R, "thyrocyte_summary.csv"), index=False)

    if n_thy > 20 and "site" in adata.obs:
        thy = adata[thy_mask].copy()
        tmsb4x = (np.asarray(thy[:, "TMSB4X"].X.todense()).ravel()
                  if "TMSB4X" in thy.var_names else np.full(thy.n_obs, np.nan))
        by = pd.DataFrame({
            "site": thy.obs["site"].values,
            "is_mal": (thy.obs["malignant_call"] == "malignant thyrocyte").astype(int).values,
            "tmsb4x": tmsb4x,
        })
        agg = by.groupby("site").agg(n_thyrocytes=("is_mal", "size"),
                                     pct_malignant=("is_mal", lambda s: round(100 * s.mean(), 2)),
                                     mean_TMSB4X=("tmsb4x", "mean")).round(4)
        agg["site_rank"] = [SITE_RANK.get(s, -1) for s in agg.index]
        agg = agg.sort_values("site_rank")
        agg.to_csv(os.path.join(R, "malignant_by_site.csv"))

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/정상 갑상선세포 판정"),
        ]:
            fig, ax = plt.subplots(figsize=(7.5, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=3, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if comp_site is not None:
            fig, ax = plt.subplots(figsize=(7.5, 5))
            comp_site.reindex(sorted(comp_site.index, key=lambda s: SITE_RANK.get(s, 99))) \
                     .plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.7)
            ax.set_ylabel("% of cells"); ax.set_title("조직별 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=6, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=20)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

    # --- summary / provenance ---------------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant thyrocyte").sum())
    n_norm = int((adata.obs["malignant_call"] == "normal thyrocyte").sum())
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs['sample'].nunique()}\n")
        fh.write(f"patients={adata.obs['patient'].nunique()}\n")
        fh.write(f"malignant_thyrocyte_cells={n_mal}\nnormal_thyrocyte_cells={n_norm}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; NO author cell-type labels exist on GEO, so none consumed.",
        "method": "per-sample MTX merge (common genes) + QC + normalize + HVG + GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant thyrocyte split",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "differentiation_signature_used": sig_dif,
        "params": vars(args),
        "cell_type_counts": {str(k): int(v) for k, v in counts.items()},
    }
    adata.uns["gpu_reanalysis"] = prov
    with progress("Writing gpu_reanalysis.h5ad + provenance"):
        adata.write_h5ad(os.path.join(R, "gpu_reanalysis.h5ad"), compression="gzip")
    with open(os.path.join(R, "provenance.json"), "w") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=2, default=str)
    # the pre-marker checkpoint was crash-insurance for this run; drop it on success.
    if os.path.exists(ckpt):
        os.remove(ckpt)

    print(f"\n==> [02] Independent GPU reanalysis done: {total:,} cells, {n_clusters} clusters, "
          f"{adata.obs['cell_type'].nunique()} cell types; malignant-thyrocyte={n_mal} / normal-thyrocyte={n_norm}.",
          flush=True)
    print("    Next: 3. Validate vs the paper's published claims (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
