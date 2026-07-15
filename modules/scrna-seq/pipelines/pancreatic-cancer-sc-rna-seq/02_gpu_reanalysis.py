#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Peng 2019, PDAC — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT read the authors'
`Cell_type` labels (ductal type 1/2, etc.) as an input. We start from the
published expression matrix and RE-DERIVE the whole analysis with our own,
freshly-written, GPU-accelerated code:

  1. take the authors' log-normalised gene matrix (adata.raw, ~17k genes),
  2. select highly-variable genes,
  3. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  4. Harmony batch-integration across the 35 patients (harmonypy),
  5. neighbours → Leiden clustering → UMAP (Scanpy),
  6. Wilcoxon markers per cluster,
  7. marker-based cell-type annotation (canonical PDAC lineage signatures),
  8. an INDEPENDENT malignant-vs-normal ductal split (unsupervised GMM on a
     PDAC malignancy signature) — never using the authors' type-1/type-2 label.

The authors' `Cell_type` is stripped from the working object and saved verbatim
to `author_labels.csv` for the SEPARATE validation step (03), which is the only
place it is allowed to be touched (헌장 제2조).

Why PyTorch+Harmony and not scVI: scVI needs raw integer counts, and the public
object ships only scaled / log-normalised values (no counts). We therefore GPU-
accelerate the classic scale+PCA path (as in the therapy-induced-evolution
reference pipeline) and integrate with Harmony. This is stated openly (제6조).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_ductal.csv         DE (our malignant vs our normal ductal) + which markers
  ductal_summary.csv           our ductal split counts + mean malignancy score
  composition_by_condition.csv cell-type % in tumour vs normal tissue
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, composition.png
  author_labels.csv            authors' Cell_type per cell (for step 3 validation ONLY)
  qc_summary.csv, provenance.json, run_summary.txt
"""
from __future__ import annotations

import argparse
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
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import torch
from scipy import sparse


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


# ---- canonical PDAC lineage markers (for INDEPENDENT annotation) -------------
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Ductal": ["KRT19", "KRT8", "KRT18", "EPCAM", "CDH1", "KRT7", "MUC1", "TSPAN8", "ELF3", "SPP1"],
    "Acinar": ["PRSS1", "CTRB2", "CTRB1", "CPA1", "CPB1", "CELA3A", "PLA2G1B", "CTRC"],
    "Endocrine": ["INS", "GCG", "SST", "PPY", "CHGA", "CHGB", "PCSK1N", "TTR"],
    "Endothelial": ["VWF", "CLDN5", "PLVAP", "RAMP2", "CDH5", "EGFL7", "A2M", "GNG11"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "DCN", "LUM", "PDGFRA", "FN1", "C1S"],
    "Stellate": ["RGS5", "ACTA2", "PDGFRB", "NOTCH3", "MYL9", "TAGLN", "ADIRF"],
    "Macrophage": ["LYZ", "CD68", "AIF1", "C1QA", "C1QB", "TYROBP", "FCGR3A", "ITGAX", "HLA-DRA"],
    "T cell": ["CD3D", "CD3E", "CD2", "CD8A", "IL7R", "TRAC", "CD52"],
    "B cell": ["MS4A1", "CD79A", "CD79B", "MZB1", "IGKC", "CD37"],
}
# PDAC malignant ductal signature vs a normal-duct signature (Peng 2019 / canonical).
MALIGNANT_SIG = ["KRT19", "EPCAM", "MUC1", "S100P", "TM4SF1", "LAMC2", "LAMB3", "CEACAM5",
                 "CEACAM6", "LGALS4", "TSPAN8", "MMP7", "SLPI", "AGR2", "KRT7", "S100A6",
                 "FXYD3", "CLDN18", "TSPAN1", "LGALS3"]
NORMAL_DUCT_SIG = ["FXYD2", "SLC4A4", "CLDN10", "CFTR", "AMBP", "ANXA4", "SPP1", "MMP7"]
DUCTAL_TYPES = {"Ductal"}


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
        "~/ghbio-tutorial/data/pdac-peng2019/StdWf1_PRJCA001063_CRC_besca2.annotated.h5ad"))
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--n-comps", type=int, default=50)
    ap.add_argument("--n-pcs", type=int, default=30)
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--scale-max", type=float, default=10.0)
    ap.add_argument("--batch-key", default="Patient")
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

    if not os.path.exists(args.source):
        print(f"ERROR: source not found: {args.source} (run step 1 first).", file=sys.stderr)
        sys.exit(1)

    # --- load, then take the log-normalised full-gene matrix from .raw ----------
    with progress("Loading authors' published matrix (.raw = ~17k log-norm genes)"):
        full = sc.read_h5ad(args.source)
    if full.raw is None:
        print("ERROR: object has no .raw; cannot get the full gene matrix.", file=sys.stderr)
        sys.exit(1)
    adata = full.raw.to_adata()           # 17k genes, log-normalised, var_names = symbols
    adata.var_names_make_unique()
    # carry only the *experimental* metadata (patient / tissue) — NOT the authors' labels.
    for c in ("Patient", "Type", "n_counts", "n_genes", "percent_mito"):
        if c in full.obs.columns:
            adata.obs[c] = full.obs[c].values
    adata.obs["condition"] = (
        adata.obs["Type"].astype(str).str.upper().map({"T": "Tumor", "N": "Normal"})
        if "Type" in adata.obs else "Unknown"
    )

    # 헌장 제1조: stash the authors' Cell_type for validation ONLY, then forget it.
    author = pd.DataFrame(index=adata.obs_names)
    author["author_cell_type"] = full.obs["Cell_type"].astype(str).values if "Cell_type" in full.obs else "NA"
    if "leiden" in full.obs:
        author["author_leiden"] = full.obs["leiden"].astype(str).values
    author.to_csv(os.path.join(R, "author_labels.csv"))
    del full
    print(f"    working matrix: {adata.n_obs:,} cells x {adata.n_vars:,} genes "
          "(authors' Cell_type withheld → author_labels.csv)", flush=True)

    # --- HVG on the log-normalised values (flavor='seurat') --------------------
    with progress("Highly-variable genes (seurat, on log-norm)"):
        sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=args.n_hvg)
    hvg = np.where(adata.var["highly_variable"].to_numpy())[0]

    # --- GPU: ScaleData + PCA(SVD) on the HVGs ---------------------------------
    with progress(f"GPU z-score scaling + PCA(SVD) on {len(hvg)} HVGs (PyTorch)"):
        X = adata[:, hvg].X
        dense = np.asarray(X.todense()) if sparse.issparse(X) else np.asarray(X)
        scaled = gpu_scale(dense, device, args.scale_max)
        adata.obsm["X_pca"] = gpu_pca(scaled, args.n_comps)
        del dense, scaled
        torch.cuda.empty_cache()

    # --- Harmony batch integration across patients -----------------------------
    rep = "X_pca"
    if not args.no_harmony and args.batch_key in adata.obs and adata.obs[args.batch_key].nunique() > 1:
        try:
            import harmonypy
            with progress(f"Harmony integration across {adata.obs[args.batch_key].nunique()} patients"):
                ho = harmonypy.run_harmony(adata.obsm["X_pca"][:, : args.n_pcs],
                                           adata.obs, [args.batch_key])
                adata.obsm["X_pca_harmony"] = ho.Z_corr.T
            rep = "X_pca_harmony"
        except Exception as e:  # keep going on un-integrated PCA if Harmony fails
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.", file=sys.stderr)
    n_use = adata.obsm[rep].shape[1] if rep == "X_pca_harmony" else args.n_pcs

    # --- neighbours → Leiden → UMAP --------------------------------------------
    with progress("Neighbours + Leiden + UMAP (Scanpy)"):
        sc.pp.neighbors(adata, use_rep=rep, n_pcs=n_use, n_neighbors=args.n_neighbors,
                        random_state=args.seed)
        sc.tl.leiden(adata, key_added="leiden_gpu", resolution=args.resolution,
                     flavor="igraph", n_iterations=2, directed=False, random_state=args.seed)
        sc.tl.umap(adata, random_state=args.seed)
    n_clusters = adata.obs["leiden_gpu"].nunique()
    print(f"    {n_clusters} Leiden clusters (resolution {args.resolution})", flush=True)

    # --- Wilcoxon markers per cluster ------------------------------------------
    with progress("Wilcoxon markers per cluster"):
        sc.tl.rank_genes_groups(adata, "leiden_gpu", method="wilcoxon", use_raw=False, n_genes=30)
    mk = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "logfoldchanges": "log2fc"})
    mk["rank"] = mk.groupby("cluster", observed=True).cumcount() + 1
    mk = mk[mk["rank"] <= 30][["cluster", "rank", "gene", "scores", "log2fc", "pvals_adj"]]
    mk.to_csv(os.path.join(R, "markers_by_cluster.csv"), index=False)

    # --- INDEPENDENT marker-based cell-type annotation -------------------------
    with progress("Marker-based cell-type annotation (independent of authors)"):
        annotation = annotate(adata, "leiden_gpu")
    annotation.to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)
    print("    cell types: " + ", ".join(
        f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)

    # --- INDEPENDENT malignant vs normal ductal split (unsupervised GMM) -------
    sig_mal = [g for g in MALIGNANT_SIG if g in adata.var_names]
    sig_norm = [g for g in NORMAL_DUCT_SIG if g in adata.var_names]
    sc.tl.score_genes(adata, sig_mal, score_name="malignancy_score", use_raw=False)
    sc.tl.score_genes(adata, sig_norm, score_name="normalduct_score", use_raw=False)
    adata.obs["malignant_call"] = "n/a"
    ductal_mask = adata.obs["cell_type"].astype(str).isin(DUCTAL_TYPES).to_numpy()
    n_ductal = int(ductal_mask.sum())
    if n_ductal > 20:
        from sklearn.mixture import GaussianMixture
        score = (adata.obs.loc[ductal_mask, "malignancy_score"]
                 - adata.obs.loc[ductal_mask, "normalduct_score"]).to_numpy().reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=args.seed).fit(score)
        comp = gm.predict(score)
        mal_comp = int(np.argmax(gm.means_.ravel()))   # higher (malignant − normal) = malignant
        call = np.where(comp == mal_comp, "malignant ductal", "normal ductal")
        idx = adata.obs_names[ductal_mask]
        adata.obs.loc[idx, "malignant_call"] = call
    print("    ductal split: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["malignant_call"].value_counts().items()), flush=True)

    # --- DE: our malignant vs our normal ductal --------------------------------
    two = adata[adata.obs["malignant_call"].isin(["malignant ductal", "normal ductal"])].copy()
    if two.obs["malignant_call"].nunique() == 2:
        sc.tl.rank_genes_groups(two, "malignant_call", groups=["malignant ductal"],
                                reference="normal ductal", method="wilcoxon", use_raw=False, n_genes=40)
        de = sc.get.rank_genes_groups_df(two, group="malignant ductal").rename(
            columns={"names": "gene", "logfoldchanges": "log2fc"})
        de.insert(0, "rank", range(1, len(de) + 1))
        de[["rank", "gene", "log2fc", "pvals_adj"]].to_csv(
            os.path.join(R, "malignant_ductal.csv"), index=False)

    # --- composition tables + CSVs ---------------------------------------------
    counts = adata.obs["cell_type"].value_counts()
    top5 = {r["cluster"]: [] for _, r in annotation.iterrows()}  # placeholder
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

    if "condition" in adata.obs:
        comp = (pd.crosstab(adata.obs["condition"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp.to_csv(os.path.join(R, "composition_by_condition.csv"))

    dsum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean")).round(4).reset_index())
    dsum.to_csv(os.path.join(R, "ductal_summary.csv"), index=False)

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/정상 도관 판정"),
        ]:
            fig, ax = plt.subplots(figsize=(7.5, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=5, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if "condition" in adata.obs:
            fig, ax = plt.subplots(figsize=(7, 5))
            comp.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.7)
            ax.set_ylabel("% of cells"); ax.set_title("종양 vs 정상 — 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=6, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=0)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

    # --- QC / summary / provenance ---------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant ductal").sum())
    n_norm = int((adata.obs["malignant_call"] == "normal ductal").sum())
    vc = adata.obs["condition"].value_counts() if "condition" in adata.obs else {}
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs.get('Patient', pd.Series()).nunique()}\n")
        fh.write(f"tumor_cells={int(vc.get('Tumor',0))}\nnormal_cells={int(vc.get('Normal',0))}\n")
        fh.write(f"malignant_ductal_cells={n_mal}\nnormal_ductal_cells={n_norm}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; authors' Cell_type NOT used as input.",
        "method": "GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant split",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "normal_duct_signature_used": sig_norm,
        "params": vars(args),
        "cell_type_counts": {str(k): int(v) for k, v in counts.items()},
    }
    adata.uns["gpu_reanalysis"] = prov
    with progress("Writing gpu_reanalysis.h5ad + provenance"):
        adata.write_h5ad(os.path.join(R, "gpu_reanalysis.h5ad"), compression="gzip")
    with open(os.path.join(R, "provenance.json"), "w") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=2, default=str)

    print(f"\n==> [02] Independent GPU reanalysis done: {total:,} cells, {n_clusters} clusters, "
          f"{adata.obs['cell_type'].nunique()} cell types; malignant-ductal={n_mal} / normal-ductal={n_norm}.",
          flush=True)
    print("    Next: 3. Validate vs authors' claims (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
