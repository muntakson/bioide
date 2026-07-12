#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_figures4_5_microenvironment.py  —  Tirosh 2016, Figures 4 & 5
================================================================
Analyze the NON-malignant tumor microenvironment (authors' labels / step 2):

  Fig 4  Cell-type-specific expression + CAF-to-T-cell interaction candidates.
         The paper deconvolves bulk TCGA melanoma with single-cell signatures
         (Fig 4A, needs external TCGA data) and finds complement/chemokine
         genes preferentially expressed by CAFs (Fig 4B). We reproduce the
         single-cell portion: cell-type signature heatmap + CAF-enriched
         complement/chemokine program (C1S/C1R/C3/C4A/CFB/SERPING1/CXCL12/CCL19…).

  Fig 5  Tumor-infiltrating T cells: CD4/CD8 stratification and variation along
         cytotoxic vs exhaustion programs (activation-dependent exhaustion).

Reads  melanoma_processed.h5ad  (written by step 2).
Writes fig4_caf_tcell.png, fig5_tcell_exhaustion.png, tcell_states.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import scanpy as sc
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy.stats import pearsonr  # noqa: E402

HOME = os.path.expanduser("~")
RESULTS_DIR = os.environ.get("GHBIO_RESULTS", os.path.join(HOME, "ghbio-tutorial", "results"))
H5AD = os.path.join(RESULTS_DIR, "melanoma_processed.h5ad")

# Canonical markers per non-malignant lineage (Fig 4A cell-type signatures).
LINEAGE_MARKERS = {
    "T cell": ["CD3D", "CD3E", "CD2", "CD8A", "IL7R"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "MZB1", "IGHG1"],
    "Macrophage": ["LYZ", "CD68", "CD14", "AIF1", "C1QA"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5", "CLEC14A", "A2M"],
    "CAF": ["COL1A1", "COL1A2", "DCN", "LUM", "PDGFRB"],
    "NK": ["NKG7", "GNLY", "KLRD1", "KLRF1", "NCAM1"],
}
# CAF-expressed complement + chemokine / immune-modulator genes (Fig 4B).
CAF_COMPLEMENT = ["C1S", "C1R", "C3", "C4A", "CFB", "SERPING1", "C1QA", "C2",
                  "CXCL12", "CCL19", "CCL2", "PDCD1LG2", "CD274"]

# T-cell state programs (Fig 5).
CYTOTOXIC = ["GZMA", "GZMB", "GZMH", "GZMK", "PRF1", "NKG7", "GNLY", "IFNG", "CST7", "CCL5", "KLRG1"]
EXHAUSTION = ["PDCD1", "TIGIT", "HAVCR2", "LAG3", "CTLA4", "CD27", "TNFRSF9", "BTLA", "CD160", "ENTPD1"]
NAIVE = ["TCF7", "LEF1", "SELL", "CCR7", "IL7R"]


def present(adata, genes):
    return [g for g in genes if g in adata.var_names]


def mean_expr(adata, gene):
    if gene not in adata.var_names:
        return np.nan
    v = adata[:, gene].X
    v = np.asarray(v.todense()).ravel() if hasattr(v, "todense") else np.asarray(v).ravel()
    return float(v.mean())


def score(adata, genes, name):
    g = present(adata, genes)
    if not g:
        adata.obs[name] = 0.0
        return
    sc.tl.score_genes(adata, g, score_name=name, ctrl_size=min(50, adata.n_vars - 1))


def figure4(adata):
    print("==> Figure 4: cell-type signatures + CAF complement program…")
    types = [t for t in ["T cell", "B cell", "Macrophage", "Endothelial", "CAF", "NK"]
             if (adata.obs["celltype"] == t).sum() >= 5]
    sub = {t: adata[adata.obs["celltype"] == t] for t in types}

    # (Left) cell-type signature heatmap: mean expression of each lineage's markers.
    sig_genes, ylabels = [], []
    for t in types:
        for g in LINEAGE_MARKERS[t]:
            if g in adata.var_names:
                sig_genes.append(g); ylabels.append(g)
    mat = np.array([[mean_expr(sub[t], g) for t in types] for g in sig_genes])
    # z-score each gene across cell types for visibility.
    mat_z = (mat - np.nanmean(mat, axis=1, keepdims=True)) / (np.nanstd(mat, axis=1, keepdims=True) + 1e-9)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 7), gridspec_kw={"width_ratios": [1, 1.05]})
    im = a1.imshow(mat_z, aspect="auto", cmap="RdBu_r", vmin=-1.5, vmax=1.5)
    a1.set_xticks(range(len(types))); a1.set_xticklabels(types, rotation=40, ha="right", fontsize=8)
    a1.set_yticks(range(len(ylabels))); a1.set_yticklabels(ylabels, fontsize=6.5)
    a1.set_title("Fig 4A — Cell-type-specific signatures\n(z-scored mean expression)")
    fig.colorbar(im, ax=a1, fraction=0.03, pad=0.02, label="z-score")

    # (Right) CAF complement/chemokine program: expression across cell types.
    cg = [g for g in CAF_COMPLEMENT if g in adata.var_names]
    cmat = np.array([[mean_expr(sub[t], g) for t in types] for g in cg])
    im2 = a2.imshow(cmat, aspect="auto", cmap="magma",
                    vmin=0, vmax=np.nanpercentile(cmat, 98) if np.isfinite(cmat).any() else 1)
    a2.set_xticks(range(len(types))); a2.set_xticklabels(types, rotation=40, ha="right", fontsize=8)
    a2.set_yticks(range(len(cg))); a2.set_yticklabels(cg, fontsize=7)
    a2.set_title("Fig 4B — Complement/chemokine genes\npreferentially expressed by CAFs")
    fig.colorbar(im2, ax=a2, fraction=0.03, pad=0.02, label="mean log2(TPM/10+1)")
    if "CAF" in types:
        a2.axvline(types.index("CAF"), color="#2dd4bf", lw=2.2, alpha=0.7)
    fig.suptitle("Figure 4 — Microenvironment: cell-type signatures & CAF–T-cell interaction candidates "
                 "(Tirosh 2016, single-cell portion)", fontsize=11.5)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = os.path.join(RESULTS_DIR, "fig4_caf_tcell.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"==> Saved {out}  (TCGA bulk deconvolution of Fig 4A/C is out of scope — single-cell part shown.)")


def figure5(adata):
    print("==> Figure 5: T-cell cytotoxic vs exhaustion states…")
    tcells = adata[adata.obs["celltype"] == "T cell"].copy()
    if tcells.n_obs < 30:
        print("==> Not enough T cells for Figure 5 — skipping.")
        return None
    score(tcells, CYTOTOXIC, "cytotoxic")
    score(tcells, EXHAUSTION, "exhaustion")
    score(tcells, NAIVE, "naive")

    # CD8 vs CD4 stratification from lineage-defining markers.
    cd8 = np.zeros(tcells.n_obs); n8 = 0
    for g in ["CD8A", "CD8B"]:
        if g in tcells.var_names:
            v = tcells[:, g].X
            cd8 += np.asarray(v.todense()).ravel() if hasattr(v, "todense") else np.asarray(v).ravel()
            n8 += 1
    cd8 = cd8 / max(n8, 1)
    cd4 = np.zeros(tcells.n_obs)
    if "CD4" in tcells.var_names:
        v = tcells[:, "CD4"].X
        cd4 = np.asarray(v.todense()).ravel() if hasattr(v, "todense") else np.asarray(v).ravel()
    subset = np.where(cd8 > cd4, "CD8", "CD4")
    tcells.obs["Tsubset"] = subset

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.4))
    for s, col in [("CD8", "#b2182b"), ("CD4", "#2166ac")]:
        m = subset == s
        a1.scatter(cd4[m], cd8[m], s=12, color=col, label=f"{s} ({m.sum()})", linewidths=0, alpha=0.7)
    a1.set_xlabel("CD4 expression"); a1.set_ylabel("CD8 expression (CD8A/CD8B)")
    a1.set_title("Fig 5A — T-cell CD4/CD8 stratification")
    a1.legend(fontsize=8, frameon=False)

    cx = tcells.obs["cytotoxic"].values
    ex = tcells.obs["exhaustion"].values
    r, _ = pearsonr(cx, ex) if len(cx) > 2 else (np.nan, np.nan)
    sca = a2.scatter(cx, ex, c=ex, cmap="RdYlGn_r", s=16, linewidths=0)
    # Binned trend (stand-in for the paper's LOWESS fit).
    order = np.argsort(cx)
    xs, ys = cx[order], ex[order]
    nb = 12
    edges = np.linspace(xs.min(), xs.max(), nb + 1)
    bx, by = [], []
    for i in range(nb):
        m = (xs >= edges[i]) & (xs <= edges[i + 1])
        if m.sum() >= 3:
            bx.append(xs[m].mean()); by.append(ys[m].mean())
    a2.plot(bx, by, color="black", lw=1.8)
    a2.set_xlabel("Cytotoxic score"); a2.set_ylabel("Exhaustion score")
    a2.set_title(f"Fig 5D — Cytotoxic vs exhaustion in CD8 T cells  (R = {r:.2f})")
    fig.colorbar(sca, ax=a2, fraction=0.03, pad=0.02, label="Exhaustion")
    fig.suptitle("Figure 5 — Tumor-infiltrating T cells: activation-dependent exhaustion (Tirosh 2016, reproduced)",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = os.path.join(RESULTS_DIR, "fig5_tcell_exhaustion.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"==> Saved {out}")

    pd.DataFrame([{
        "n_Tcells": int(tcells.n_obs),
        "n_CD8": int((subset == "CD8").sum()),
        "n_CD4": int((subset == "CD4").sum()),
        "mean_cytotoxic": round(float(cx.mean()), 3),
        "mean_exhaustion": round(float(ex.mean()), 3),
        "pearson_cytotoxic_exhaustion": round(float(r), 3),
    }]).to_csv(os.path.join(RESULTS_DIR, "tcell_states.csv"), index=False)
    print("==> Saved tcell_states.csv")


def main():
    if not os.path.exists(H5AD):
        sys.exit(f"ERROR: {H5AD} not found. Run step 2 (02_figure1_infercnv.py) first.")
    adata = sc.read_h5ad(H5AD)
    n_non = int((adata.obs["celltype"] != "—").sum())
    print(f"==> {n_non} non-malignant cells across {adata.obs['celltype'].nunique()} labeled types.")
    figure4(adata)
    figure5(adata)
    print("==> [04] Figures 4–5 complete. Next: 5. AI analysis, then 6. PDF report.")


if __name__ == "__main__":
    main()
