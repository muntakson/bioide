#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Ma 2019, liver cancer — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT read the authors'
per-cell `Type` labels (Malignant cell / HPC-like / T cell / …) as an input. We
start from the authors' RAW 10x UMI count matrices (GSE125449, Set1 + Set2) and
RE-DERIVE the whole analysis with our own, freshly-written, GPU-accelerated code:

  1. load both 10x Sets (matrix.mtx + genes.tsv + barcodes.tsv), attach each
     cell's Sample (patient) from samples.txt, and merge on the COMMON gene set,
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p) — the deposit is raw counts,
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony batch-integration across the samples (harmonypy),
  7. neighbours → Leiden clustering → UMAP (Scanpy),
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical liver-TME signatures),
 10. an INDEPENDENT malignant-vs-HPC-like EPITHELIAL split (unsupervised GMM on a
     HCC/iCCA malignancy − hepatic-progenitor signature) — the authors annotated
     malignant/HPC-like cells with their own pipeline; we deliberately use a
     different, unsupervised method so agreement in step 3 means two independent
     routes converge (제6조).

The authors' `Type` is stripped from the working object and saved verbatim to
`author_labels.csv` for the SEPARATE validation step (03), which is the only
place it is allowed to be touched (헌장 제2조).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_epithelial.csv     DE (our malignant vs our HPC-like epithelial)
  epithelial_summary.csv       our epithelial split counts + mean malignancy/hpc scores
  author_labels.csv            authors' Type per cell (for step 3 validation ONLY)
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, composition.png
  qc_summary.csv, provenance.json, run_summary.txt
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
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
import torch  # noqa: E402
from scipy import sparse  # noqa: E402
from scipy.io import mmread  # noqa: E402


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


# ---- canonical liver-TME markers (for INDEPENDENT annotation) ----------------
# Lineages reported by Ma et al. 2019: malignant cells (HCC hepatocyte-like +
# iCCA cholangiocyte-like), T cells, B cells, tumour-associated macrophages
# (TAM), cancer-associated fibroblasts (CAF), tumour endothelial cells (TEC),
# and hepatic-progenitor-cell-like (HPC-like) cells (folded into the epithelial
# compartment here and separated in the malignant split below).
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Epithelial": ["ALB", "APOA1", "APOA2", "APOC3", "APOB", "TF", "FGA", "FGB",
                   "SERPINA1", "TTR", "EPCAM", "KRT19", "KRT8", "KRT18", "KRT7",
                   "SPP1", "GPC3", "AFP", "MDK", "SPINK1", "S100P", "REG1A", "TM4SF1"],
    "T cell": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "CD8B", "IL7R", "TRAC", "CD7",
               "GZMK", "NKG7", "GNLY", "KLRD1"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1", "IGKC"],
    "TAM": ["CD68", "CD163", "LYZ", "C1QA", "C1QB", "C1QC", "AIF1", "CSF1R", "MARCO",
            "VSIG4", "FCGR3A", "APOC1", "S100A8", "S100A9"],
    "CAF": ["COL1A1", "COL1A2", "COL3A1", "ACTA2", "DCN", "PDGFRB", "TAGLN", "LUM",
            "BGN", "RGS5", "MYL9"],
    "TEC": ["PECAM1", "VWF", "CDH5", "ENG", "CLEC4G", "FLT1", "RAMP2", "EGFL7", "CLDN5",
            "STAB2", "FCN2", "OIT3", "AQP1"],
}
# HCC/iCCA malignant tumour-cell signature (up) vs a hepatic-progenitor (HPC-like)
# signature — Ma et al. 2019 separate malignant cells from a distinct HPC-like
# population within the tumour epithelial compartment.
MALIGNANT_SIG = ["GPC3", "AFP", "SPINK1", "AKR1B10", "S100P", "CEACAM6", "CEACAM5",
                 "MDK", "TM4SF1", "LGALS4", "REG1A", "REG3A", "MUC1", "SERPINB3",
                 "GOLM1", "AGR2", "LCN2"]
HPC_SIG = ["PROM1", "SOX9", "EPCAM", "KRT19", "KRT7", "CD24", "ANXA4", "TACSTD2",
           "SPP1", "DLK1", "CD44", "ELF3"]
# Cell-cycle / proliferation program (malignant epithelium is more proliferative).
PROLIF_SIG = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CCNB2", "CENPF", "UBE2C", "BIRC5", "TYMS"]
EPITHELIAL_TYPES = {"Epithelial"}


def _open(path: str):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def load_10x_set(set_dir: str, set_name: str) -> ad.AnnData | None:
    """Load one 10x Set (matrix.mtx + genes.tsv + barcodes.tsv, gzip) into a
    cells×genes AnnData, and attach each cell's Sample + authors' Type from
    samples.txt. The Type is metadata only here (stashed for validation); it is
    NEVER used as an analysis input."""
    mtx = os.path.join(set_dir, "matrix.mtx.gz")
    genes = os.path.join(set_dir, "genes.tsv.gz")
    barcodes = os.path.join(set_dir, "barcodes.tsv.gz")
    samples = os.path.join(set_dir, "samples.txt.gz")
    if not all(os.path.exists(p) for p in (mtx, genes, barcodes)):
        print(f"    WARNING: {set_name} is missing 10x files — skipping.", file=sys.stderr)
        return None

    with _open(mtx) as fh:
        m = mmread(fh)                       # genes × cells (MatrixMarket)
    X = sparse.csr_matrix(m.T.astype(np.float32))   # → cells × genes

    with _open(genes) as fh:
        gdf = pd.read_csv(fh, sep="\t", header=None)
    # genes.tsv is ENSEMBL_id <tab> symbol; use the symbol column when present.
    gene_syms = (gdf[1] if gdf.shape[1] > 1 else gdf[0]).astype(str).tolist()

    with _open(barcodes) as fh:
        bcs = [ln.strip() for ln in fh if ln.strip()]

    if X.shape[0] != len(bcs) or X.shape[1] != len(gene_syms):
        print(f"    WARNING: {set_name} shape {X.shape} != ({len(bcs)},{len(gene_syms)}) — skipping.",
              file=sys.stderr)
        return None

    a = ad.AnnData(X=X)
    a.var_names = gene_syms
    a.var_names_make_unique()

    # per-cell Sample (patient) + authors' Type from samples.txt (Sample, Cell Barcode, Type)
    sample_of = {bc: "unknown" for bc in bcs}
    type_of = {bc: "unclassified" for bc in bcs}
    if os.path.exists(samples):
        with _open(samples) as fh:
            sdf = pd.read_csv(fh, sep="\t")
        cols = {c.lower().strip(): c for c in sdf.columns}
        bc_col = cols.get("cell barcode") or cols.get("barcode") or sdf.columns[1]
        sm_col = cols.get("sample") or sdf.columns[0]
        ty_col = cols.get("type") or sdf.columns[-1]
        sample_of = dict(zip(sdf[bc_col].astype(str), sdf[sm_col].astype(str)))
        type_of = dict(zip(sdf[bc_col].astype(str), sdf[ty_col].astype(str)))

    a.obs["set"] = set_name
    a.obs["sample"] = [sample_of.get(bc, "unknown") for bc in bcs]
    a.obs["author_cell_type"] = [type_of.get(bc, "unclassified") for bc in bcs]
    # globally-unique cell ids: <set>_<sample>_<barcode>
    a.obs_names = [f"{set_name}_{s}_{bc}" for s, bc in zip(a.obs["sample"], bcs)]
    a.obs_names_make_unique()
    return a


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
        "~/ghbio-tutorial/data/liver-ma2019"))
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--n-comps", type=int, default=50)
    ap.add_argument("--n-pcs", type=int, default=30)
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--scale-max", type=float, default=10.0)
    ap.add_argument("--min-genes", type=int, default=300)
    ap.add_argument("--min-cells", type=int, default=3)
    ap.add_argument("--max-mito", type=float, default=20.0)
    ap.add_argument("--batch-key", default="sample")
    ap.add_argument("--seed", type=int, default=2019)
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

    # --- load + merge both 10x Sets on the COMMON gene set ----------------------
    with progress("Loading 10x Sets (Set1, Set2) + attaching Sample/Type"):
        parts = []
        for set_name in ("Set1", "Set2"):
            a = load_10x_set(os.path.join(args.source, set_name), set_name)
            if a is not None and a.n_obs > 0:
                parts.append(a)
        if not parts:
            print(f"ERROR: no readable 10x Sets under {args.source} (run step 1 first).", file=sys.stderr)
            sys.exit(1)
        adata = ad.concat(parts, join="inner", index_unique=None, merge="same")
        adata.obs_names_make_unique()
        del parts
    print(f"    merged: {adata.n_obs:,} cells × {adata.n_vars:,} common genes "
          f"from {adata.obs['sample'].nunique()} samples / {adata.obs['set'].nunique()} sets", flush=True)

    # 헌장 제1조: stash the authors' Type for validation ONLY, then forget it.
    author = pd.DataFrame(index=adata.obs_names)
    author["author_cell_type"] = adata.obs["author_cell_type"].astype(str).values
    author["sample"] = adata.obs["sample"].astype(str).values
    author["set"] = adata.obs["set"].astype(str).values
    author.to_csv(os.path.join(R, "author_labels.csv"))
    adata.obs.drop(columns=["author_cell_type"], inplace=True)
    print(f"    authors' Type withheld → author_labels.csv "
          f"({author['author_cell_type'].nunique()} label values)", flush=True)

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

    # --- Harmony batch integration across samples -------------------------------
    rep = "X_pca"
    if not args.no_harmony and args.batch_key in adata.obs and adata.obs[args.batch_key].nunique() > 1:
        try:
            import harmonypy
            with progress(f"Harmony integration across {adata.obs[args.batch_key].nunique()} samples"):
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
    with progress("Marker-based cell-type annotation (independent of authors)"):
        annotation = annotate(adata, "leiden_gpu")
    annotation.to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)
    print("    cell types: " + ", ".join(
        f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)

    # --- INDEPENDENT malignant vs HPC-like epithelial split (unsupervised GMM) ---
    sig_mal = [g for g in MALIGNANT_SIG if g in adata.var_names]
    sig_hpc = [g for g in HPC_SIG if g in adata.var_names]
    sig_pro = [g for g in PROLIF_SIG if g in adata.var_names]
    sc.tl.score_genes(adata, sig_mal, score_name="malignancy_score", use_raw=False)
    sc.tl.score_genes(adata, sig_hpc, score_name="hpc_score", use_raw=False)
    if sig_pro:
        sc.tl.score_genes(adata, sig_pro, score_name="prolif_score", use_raw=False)
    else:
        adata.obs["prolif_score"] = 0.0
    adata.obs["malignant_call"] = "n/a"
    epi_mask = adata.obs["cell_type"].astype(str).isin(EPITHELIAL_TYPES).to_numpy()
    n_epi = int(epi_mask.sum())
    if n_epi > 20:
        from sklearn.mixture import GaussianMixture
        score = (adata.obs.loc[epi_mask, "malignancy_score"]
                 - adata.obs.loc[epi_mask, "hpc_score"]).to_numpy().reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=args.seed).fit(score)
        comp = gm.predict(score)
        mal_comp = int(np.argmax(gm.means_.ravel()))   # higher (malignancy − hpc) = malignant
        call = np.where(comp == mal_comp, "malignant epithelial", "HPC-like epithelial")
        idx = adata.obs_names[epi_mask]
        adata.obs.loc[idx, "malignant_call"] = call
    print("    epithelial split: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["malignant_call"].value_counts().items()), flush=True)

    # --- DE: our malignant vs our HPC-like epithelial ---------------------------
    two = adata[adata.obs["malignant_call"].isin(["malignant epithelial", "HPC-like epithelial"])].copy()
    if two.obs["malignant_call"].nunique() == 2:
        sc.tl.rank_genes_groups(two, "malignant_call", groups=["malignant epithelial"],
                                reference="HPC-like epithelial", method="wilcoxon", use_raw=False, n_genes=40)
        de = sc.get.rank_genes_groups_df(two, group="malignant epithelial").rename(
            columns={"names": "gene", "logfoldchanges": "log2fc"})
        de.insert(0, "rank", range(1, len(de) + 1))
        de[["rank", "gene", "log2fc", "pvals_adj"]].to_csv(
            os.path.join(R, "malignant_epithelial.csv"), index=False)

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

    # cell-type composition per Set (batch) — a light composition view
    comp_set = None
    if adata.obs["set"].nunique() > 1:
        comp_set = (pd.crosstab(adata.obs["set"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp_set.to_csv(os.path.join(R, "composition_by_set.csv"))

    # epithelial split summary (malignant vs HPC-like: malignancy + proliferation)
    esum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean"),
                 mean_hpc=("hpc_score", "mean"),
                 mean_prolif=("prolif_score", "mean")).round(4).reset_index())
    esum.to_csv(os.path.join(R, "epithelial_summary.csv"), index=False)

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/HPC-like 상피세포 판정"),
        ]:
            fig, ax = plt.subplots(figsize=(7.5, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=6, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if comp_set is not None:
            fig, ax = plt.subplots(figsize=(7, 5))
            comp_set.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.7)
            ax.set_ylabel("% of cells"); ax.set_title("배치(Set)별 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=6, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=0)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

    # --- summary / provenance ---------------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant epithelial").sum())
    n_hpc = int((adata.obs["malignant_call"] == "HPC-like epithelial").sum())
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs['sample'].nunique()}\n")
        fh.write(f"malignant_epithelial_cells={n_mal}\nhpc_like_epithelial_cells={n_hpc}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; authors' Type NOT used as input.",
        "method": "two 10x Sets merged (common genes) + QC + normalize + HVG + GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant/HPC-like epithelial split",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "hpc_signature_used": sig_hpc,
        "proliferation_signature_used": sig_pro,
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
          f"{adata.obs['cell_type'].nunique()} cell types; malignant-epithelial={n_mal} / HPC-like={n_hpc}.",
          flush=True)
    print("    Next: 3. Validate vs the authors' labels (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
