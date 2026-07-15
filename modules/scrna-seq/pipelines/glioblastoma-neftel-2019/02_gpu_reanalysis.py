#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Neftel 2019, GBM — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조: the authors' per-cell STATE labels are NOT distributed on GEO
(they live on Broad SCP behind a login), so we re-derive everything from the
published Smart-seq2 TPM matrix with our own GPU code and validate against the
paper's published claims (제2조):

  1. load the Smart-seq2 TPM matrix (23,686 genes × 7,930 cells), log2(TPM/10+1),
  2. HVG → GPU (PyTorch) scale + PCA(SVD) → Harmony (tumour batch) → Leiden → UMAP,
  3. score the four malignant meta-modules (AC / MES / NPC / OPC-like) and the
     non-malignant lineages (macrophage/microglia, T cell, oligodendrocyte),
  4. call malignant vs non-malignant from lineage scores, assign each malignant
     cell to its top state, and place it on Neftel's 2-axis "butterfly":
        y = max(OPC,NPC) − max(AC,MES)        (progenitor ↔ differentiated)
        x = NPC−OPC  (upper half)  /  MES−AC  (lower half),
  5. score the cell cycle (G1/S, G2/M) to test the cycling-in-NPC/OPC claim.

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad, celltype_composition.csv, state_composition.csv,
  state_cells.csv (per-cell 4 scores + state + 2D coords + cycling),
  markers_by_cluster.csv, umap_celltypes.png, umap_state.png, butterfly.png,
  run_summary.txt, provenance.json
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
import matplotlib.font_manager  # noqa: E402
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


@contextmanager
def progress(label: str):
    started = time.monotonic()
    done = threading.Event()

    def heartbeat():
        while not done.wait(30):
            print(f"⏳ {label} — still running ({(time.monotonic()-started)/60:.1f} min)", flush=True)

    print(f"▶ {label}", flush=True)
    t = threading.Thread(target=heartbeat, daemon=True); t.start()
    try:
        yield
    finally:
        done.set(); t.join(timeout=1)
        print(f"✓ {label} — done ({(time.monotonic()-started)/60:.1f} min)", flush=True)


def gpu_scale(matrix, device, scale_max):
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    return torch.clamp((x - mean) / std, max=scale_max)


def gpu_pca(scaled, n_comps):
    scaled = scaled - scaled.mean(dim=0, keepdim=True)
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    return (u[:, :n_comps] * s[:n_comps]).cpu().numpy()


# ---- Neftel four malignant meta-modules (Table S2 approximations) ------------
STATES = {
    "AC-like": ["AQP4", "GFAP", "S100B", "SLC1A3", "MLC1", "HOPX", "GJA1", "CST3", "CLU",
                "SPARCL1", "FABP7", "AGT", "CRYAB", "ATP1A2", "ALDOC", "TTYH1", "NTRK2", "GATM"],
    "MES-like": ["VIM", "CD44", "CHI3L1", "ANXA1", "ANXA2", "LGALS1", "LGALS3", "TIMP1", "EMP1",
                 "EMP3", "VEGFA", "ADM", "HILPDA", "NDRG1", "LDHA", "SERPINE1", "IGFBP7", "CLIC1"],
    "NPC-like": ["SOX4", "SOX11", "DCX", "CD24", "STMN1", "STMN2", "STMN4", "TUBB3", "DLL3", "TCF4",
                 "MLLT11", "NREP", "CD200", "ELAVL4", "MAP1B", "DPYSL3", "RND3", "TAGLN3"],
    "OPC-like": ["OLIG1", "OMG", "PLP1", "PLLP", "TNR", "ALCAM", "BCAN", "PDGFRA", "CSPG4", "SOX8",
                 "SCRG1", "OLIG2", "APOD", "PTPRZ1", "GPR17", "NKX2-2", "SIRT2", "DBI"],
}
# non-malignant lineages of the GBM microenvironment
NONMAL = {
    "Macrophage": ["CD14", "AIF1", "FCER1G", "TYROBP", "CSF1R", "C1QA", "C1QB", "C1QC", "CD163",
                   "ITGAM", "PTPRC", "LYZ", "CD68"],
    "T cell": ["CD2", "CD3D", "CD3E", "CD3G", "CD8A", "IL7R", "CCL5", "CD247"],
    "Oligodendrocyte": ["MBP", "MAG", "MOG", "CLDN11", "MOBP", "CNP", "ERMN", "ST18", "PLP1"],
}
G1S = ["MCM5", "PCNA", "TYMS", "FEN1", "MCM2", "MCM4", "RRM1", "UNG", "GINS2", "MCM6", "CDCA7",
       "DTL", "PRIM1", "UHRF1", "MLF1IP", "HELLS", "RFC2", "RPA2", "NASP", "RAD51AP1", "GMNN",
       "WDR76", "SLBP", "CCNE2", "UBR7", "POLD3", "MSH2", "ATAD2", "RAD51", "RRM2", "CDC45", "CDC6"]
G2M = ["HMGB2", "CDK1", "NUSAP1", "UBE2C", "BIRC5", "TPX2", "TOP2A", "NDC80", "CKS2", "NUF2",
       "CKS1B", "MKI67", "TMPO", "CENPF", "TACC3", "SMC4", "CCNB2", "CKAP2", "AURKB", "BUB1",
       "KIF11", "ANP32E", "TUBB4B", "GTSE1", "KIF20B", "HJURP", "CDCA3", "CDC20", "TTK", "CDC25C"]

ALL_PROGRAMS = {**STATES, **NONMAL}


def score(adata, sigs, prefix):
    cols = {}
    for name, genes in sigs.items():
        present = [g for g in genes if g in adata.var_names]
        c = f"{prefix}{name}"
        if present:
            sc.tl.score_genes(adata, present, score_name=c, use_raw=False)
        else:
            adata.obs[c] = 0.0
        cols[name] = c
    return cols


def load_tpm(path):
    """Load a dense gene×cell TPM .tsv.gz → cells×genes AnnData with log2(TPM/10+1)."""
    op = gzip.open(path, "rt") if path.endswith(".gz") else open(path)
    with op as fh:
        df = pd.read_csv(fh, sep="\t", index_col=0, low_memory=False)
    df = df[~df.index.duplicated(keep="first")]
    X = np.log2(df.values.astype(np.float32).T / 10.0 + 1.0)
    a = ad.AnnData(X=X)
    a.obs_names = [str(c) for c in df.columns]
    a.var_names = [str(g) for g in df.index]
    a.var_names_make_unique()
    return a


def load_tumor_meta(path, cell_names):
    """Best-effort per-cell tumour-of-origin (batch key). Falls back to cell-name prefix."""
    tumor = pd.Series("NA", index=cell_names)
    if path and os.path.exists(path):
        try:
            m = pd.read_excel(path)
            m.columns = [str(c).strip().lower() for c in m.columns]
            cell_col = next((c for c in m.columns if "cell" in c or c in ("name", "id")), m.columns[0])
            tum_col = next((c for c in m.columns if "tumor" in c or "tumour" in c or "sample" in c), None)
            if tum_col:
                mp = dict(zip(m[cell_col].astype(str), m[tum_col].astype(str)))
                tumor = pd.Series([mp.get(c, "NA") for c in cell_names], index=cell_names)
        except Exception as e:  # openpyxl missing / format差 — fall back below
            print(f"    WARNING: could not read tumour metadata ({e}); parsing from cell names.", file=sys.stderr)
    if (tumor == "NA").all():
        import re
        tumor = pd.Series([re.match(r"^([A-Za-z]+\d+)", c).group(1) if re.match(r"^([A-Za-z]+\d+)", c) else "NA"
                           for c in cell_names], index=cell_names)
    return tumor.values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=os.path.expanduser(
        "~/ghbio-tutorial/data/gbm-neftel2019/GSM3828672_Smartseq2_GBM_IDHwt_processed_TPM.tsv.gz"))
    ap.add_argument("--meta", default=os.path.expanduser(
        "~/ghbio-tutorial/data/gbm-neftel2019/GSE131928_single_cells_tumor_name_and_adult_or_peidatric.xlsx"))
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--n-comps", type=int, default=50)
    ap.add_argument("--n-pcs", type=int, default=30)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--scale-max", type=float, default=10.0)
    ap.add_argument("--min-genes", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=2019)
    args = ap.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable; this GPU reanalysis refuses CPU fallback.", file=sys.stderr)
        sys.exit(2)
    device = torch.device("cuda")
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    sc.settings.verbosity = 1
    R = args.results
    os.makedirs(R, exist_ok=True)
    print(f"GPU: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}", flush=True)
    if not os.path.exists(args.source):
        print(f"ERROR: source not found: {args.source} (run step 1).", file=sys.stderr); sys.exit(1)

    with progress("Loading Smart-seq2 TPM matrix (log2(TPM/10+1))"):
        adata = load_tpm(args.source)
        adata.obs["tumor"] = load_tumor_meta(args.meta, adata.obs_names)
    print(f"    {adata.n_obs:,} cells × {adata.n_vars:,} genes; {adata.obs['tumor'].nunique()} tumours", flush=True)

    # light QC (SS2 already quality-controlled by the authors)
    sc.pp.filter_cells(adata, min_genes=args.min_genes)
    sc.pp.filter_genes(adata, min_cells=5)

    # HVG → GPU scale + PCA
    with progress("HVG + GPU scale/PCA (PyTorch)"):
        sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=args.n_hvg)
        hvg = np.where(adata.var["highly_variable"].to_numpy())[0]
        X = adata[:, hvg].X
        dense = np.asarray(X.todense()) if sparse.issparse(X) else np.asarray(X)
        adata.obsm["X_pca"] = gpu_pca(gpu_scale(dense, device, args.scale_max), args.n_comps)
        del dense; torch.cuda.empty_cache()

    rep = "X_pca"
    if adata.obs["tumor"].nunique() > 1:
        try:
            import harmonypy
            with progress(f"Harmony across {adata.obs['tumor'].nunique()} tumours"):
                ho = harmonypy.run_harmony(adata.obsm["X_pca"][:, : args.n_pcs], adata.obs, ["tumor"])
                Z = np.asarray(ho.Z_corr)
                if Z.shape[0] != adata.n_obs and Z.shape[1] == adata.n_obs:
                    Z = Z.T
                adata.obsm["X_pca_harmony"] = np.ascontiguousarray(Z, dtype=np.float32)
            rep = "X_pca_harmony"
        except Exception as e:
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.", file=sys.stderr)
    n_use = adata.obsm[rep].shape[1] if rep == "X_pca_harmony" else args.n_pcs

    with progress("Neighbours + Leiden + UMAP"):
        sc.pp.neighbors(adata, use_rep=rep, n_pcs=n_use, random_state=args.seed)
        sc.tl.leiden(adata, key_added="leiden", resolution=args.resolution,
                     flavor="igraph", n_iterations=2, directed=False, random_state=args.seed)
        sc.tl.umap(adata, random_state=args.seed)

    # canonicalise X for the marker/rank routines (avoid the aarch64 wilcoxon segfault)
    if sparse.issparse(adata.X):
        adata.X = adata.X.tocsr(); adata.X.sort_indices(); adata.X.sum_duplicates()
    adata.X = adata.X.astype(np.float32)
    with progress("Wilcoxon markers per cluster"):
        vc = adata.obs["leiden"].value_counts(); big = [str(g) for g in vc[vc >= 3].index]
        sc.tl.rank_genes_groups(adata, "leiden", groups=big, method="wilcoxon", use_raw=False, n_genes=25)
    mk = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "logfoldchanges": "log2fc"})
    mk["rank"] = mk.groupby("cluster", observed=True).cumcount() + 1
    mk[mk["rank"] <= 25].to_csv(os.path.join(R, "markers_by_cluster.csv"), index=False)

    # --- score all programs + cell cycle --------------------------------------
    with progress("Scoring 4 states + non-malignant lineages + cell cycle"):
        scols = score(adata, ALL_PROGRAMS, "sc_")
        sc.tl.score_genes(adata, [g for g in G1S if g in adata.var_names], score_name="G1S", use_raw=False)
        sc.tl.score_genes(adata, [g for g in G2M if g in adata.var_names], score_name="G2M", use_raw=False)
        adata.obs["cycling_score"] = adata.obs[["G1S", "G2M"]].max(axis=1)
        adata.obs["cycling"] = adata.obs["cycling_score"] > 0.0

    # per-cell top program across ALL programs → coarse cell type
    prog_mat = adata.obs[[scols[k] for k in ALL_PROGRAMS]].to_numpy()
    prog_names = list(ALL_PROGRAMS.keys())
    top = np.array(prog_names)[prog_mat.argmax(axis=1)]
    adata.obs["cell_type"] = np.where(np.isin(top, list(NONMAL)), top, "Malignant")
    malignant = adata.obs["cell_type"].values == "Malignant"

    # malignant state = argmax of the 4 state scores; 2D Neftel butterfly coords
    st = adata.obs[[scols[k] for k in STATES]].to_numpy()
    st_names = list(STATES.keys())
    adata.obs["state"] = "n/a"
    adata.obs.loc[malignant, "state"] = np.array(st_names)[st[malignant].argmax(axis=1)]
    SCac, SCmes, SCnpc, SCopc = (adata.obs[scols[s]].to_numpy() for s in st_names)
    y = np.maximum(SCopc, SCnpc) - np.maximum(SCac, SCmes)
    x = np.where(y > 0, SCnpc - SCopc, SCmes - SCac)
    adata.obs["neftel_x"] = x
    adata.obs["neftel_y"] = y

    n_mal = int(malignant.sum())
    print("    cell types: " + ", ".join(f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)
    print("    states(malignant): " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs.loc[malignant, "state"].value_counts().items()), flush=True)

    # --- tables ---------------------------------------------------------------
    total = adata.n_obs
    ct_counts = adata.obs["cell_type"].value_counts()
    pd.DataFrame([{"celltype": t, "n_cells": int(n), "pct_of_cells": round(100 * n / total, 2)}
                  for t, n in ct_counts.items()]).to_csv(os.path.join(R, "celltype_composition.csv"), index=False)
    stc = adata.obs.loc[malignant, "state"].value_counts()
    pd.DataFrame([{"state": s, "n_cells": int(n), "pct_of_malignant": round(100 * n / max(n_mal, 1), 2)}
                  for s, n in stc.items()]).to_csv(os.path.join(R, "state_composition.csv"), index=False)
    cell_cols = {scols[k]: f"score_{k}" for k in ALL_PROGRAMS}
    adata.obs.rename(columns=cell_cols)[
        [f"score_{k}" for k in ALL_PROGRAMS] + ["cell_type", "state", "neftel_x", "neftel_y",
                                               "G1S", "G2M", "cycling_score", "cycling", "tumor"]
    ].to_csv(os.path.join(R, "state_cells.csv"))

    # --- figures --------------------------------------------------------------
    sc.settings.figdir = R
    with progress("Figures (UMAP + butterfly)"):
        for color, fn, title in [("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형"),
                                 ("state", "umap_state.png", "독립 재분석 — 악성 4상태 (AC/MES/NPC/OPC)")]:
            fig, axf = plt.subplots(figsize=(7.5, 6))
            sc.pl.umap(adata, color=color, ax=axf, show=False, size=8, frameon=False, title=title)
            fig.tight_layout(); fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130); plt.close(fig)
        # butterfly
        fig, axf = plt.subplots(figsize=(7, 6.5))
        cmap = {"AC-like": "#2ca02c", "MES-like": "#d62728", "NPC-like": "#1f77b4", "OPC-like": "#9467bd"}
        for s in st_names:
            m = (adata.obs["state"].values == s)
            axf.scatter(x[m], y[m], s=7, c=cmap[s], label=s, linewidths=0, alpha=0.7)
        axf.axhline(0, color="#888", lw=0.6); axf.axvline(0, color="#888", lw=0.6)
        axf.set_xlabel("← MES    |    OPC → (하단 AC/MES · 상단 NPC/OPC)")
        axf.set_ylabel("differentiated (AC/MES) ↓   |   progenitor (NPC/OPC) ↑")
        axf.set_title("Neftel 2D 상태 지도 (butterfly) — 독립 재현")
        axf.legend(fontsize=8, loc="upper right")
        fig.tight_layout(); fig.savefig(os.path.join(R, "butterfly.png"), bbox_inches="tight", dpi=140); plt.close(fig)

    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ntumors={adata.obs['tumor'].nunique()}\n")
        fh.write(f"malignant_cells={n_mal}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        for s in st_names:
            fh.write(f"state_{s}={int((adata.obs['state']==s).sum())}\n")
    prov = {"mission": "BioIDE 헌장 제1조 — states re-derived from TPM; author state labels (Broad SCP) NOT used.",
            "method": "log2(TPM/10+1) + HVG + GPU PyTorch scale/PCA + Harmony + Leiden + module scoring + Neftel 2D",
            "gpu": torch.cuda.get_device_name(0), "state_signatures": STATES, "nonmalignant": NONMAL,
            "params": vars(args)}
    adata.uns["gpu_reanalysis"] = prov
    with progress("Writing gpu_reanalysis.h5ad"):
        adata.write_h5ad(os.path.join(R, "gpu_reanalysis.h5ad"), compression="gzip")
    json.dump(prov, open(os.path.join(R, "provenance.json"), "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n==> [02] Done: {total:,} cells, {n_mal:,} malignant, 4 states scored. "
          "Next: 3. 독립 검증 (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
