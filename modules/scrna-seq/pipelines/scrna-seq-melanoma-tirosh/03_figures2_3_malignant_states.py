#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
03_figures2_3_malignant_states.py  —  Tirosh 2016, Figures 2 & 3
================================================================
Analyze the MALIGNANT melanoma cells (as labeled by the authors / step 2):

  Fig 2  Cell-cycle state of individual malignant cells — G1/S vs G2/M
         signature scores, per-cell cycling calls, and the fraction of
         cycling cells per tumor (variability across tumors).
  Fig 3  The MITF program (differentiated) vs the AXL program
         (dedifferentiated, drug-resistant) — their negative correlation
         across single malignant cells, within and between tumors.

Reads  melanoma_processed.h5ad  (written by step 2).
Writes fig2_cell_cycle.png, fig3_mitf_axl.png, mitf_axl_by_cell.csv
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

# Standard S / G2M cell-cycle gene lists (Tirosh et al. 2016 — the very paper
# these lists come from), as used by Seurat / Scanpy.
S_GENES = ["MCM5","PCNA","TYMS","FEN1","MCM2","MCM4","RRM1","UNG","GINS2","MCM6",
           "CDCA7","DTL","PRIM1","UHRF1","HELLS","RFC2","RPA2","NASP","RAD51AP1","GMNN",
           "WDR76","SLBP","CCNE2","UBR7","POLD3","MSH2","ATAD2","RAD51","RRM2","CDC45",
           "CDC6","EXO1","TIPIN","DSCC1","BLM","CASP8AP2","USP1","CLSPN","POLA1","CHAF1B",
           "BRIP1","E2F8"]
G2M_GENES = ["HMGB2","CDK1","NUSAP1","UBE2C","BIRC5","TPX2","TOP2A","NDC80","CKS2","NUF2",
             "CKS1B","MKI67","TMPO","CENPF","TACC3","FAM64A","SMC4","CCNB2","CKAP2L","CKAP2",
             "AURKB","BUB1","KIF11","ANP32E","TUBB4B","GTSE1","KIF20B","HJURP","CDCA3","HN1",
             "CDC20","TTK","CDC25C","KIF2C","RANGAP1","NCAPD2","DLGAP5","CDCA2","CDCA8","ECT2",
             "KIF23","HMMR","AURKA","PSRC1","ANLN","LBR","CKAP5","CENPE","CTCF","NEK2",
             "G2E3","GAS2L3","CBX5","CENPA"]

# MITF (melanocytic, differentiated) program — MITF + canonical targets (Tirosh S7).
MITF_PROGRAM = ["MITF","TYR","TYRP1","DCT","PMEL","MLANA","SLC45A2","SLC24A5","MLPH",
                "RAB27A","GPR143","TRPM1","GPNMB","CDH1","APOE","SLC24A4","CDK2","ERBB3"]
# AXL (dedifferentiated, drug-resistant) program — AXL, NGFR + associated genes (Tirosh S8).
AXL_PROGRAM = ["AXL","NGFR","WNT5A","TGFBI","EGFR","NRG1","LOXL2","FN1","SERPINE1","INHBA",
               "FOSL1","AKT3","TNC","ANXA1","CD44","NT5E","PDGFRB","LGALS1"]


def present(adata, genes):
    return [g for g in genes if g in adata.var_names]


def score(adata, genes, name):
    g = present(adata, genes)
    if not g:
        adata.obs[name] = 0.0
        return
    sc.tl.score_genes(adata, g, score_name=name, ctrl_size=min(50, adata.n_vars - 1))


def figure2(mal):
    print("==> Figure 2: cell-cycle state of malignant cells…")
    sc.tl.score_genes_cell_cycle(mal, s_genes=present(mal, S_GENES),
                                 g2m_genes=present(mal, G2M_GENES))
    # Signature-based cycling call: a cell is cycling if either phase score is high.
    cyc = (mal.obs["S_score"].values > 0.1) | (mal.obs["G2M_score"].values > 0.1)
    mal.obs["cycling"] = np.where(cyc, "cycling", "non-cycling")

    # Two most-represented tumors (à la Fig 2A: one low-cycling, one high-cycling).
    top_tum = mal.obs["tumor"].value_counts().head(2).index.tolist()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, tum in zip(axes[:2], top_tum):
        sub = mal[mal.obs["tumor"] == tum]
        c = sub.obs["cycling"].values
        for state, col in [("non-cycling", "#9aa5b1"), ("cycling", "#e02424")]:
            m = c == state
            ax.scatter(sub.obs["S_score"].values[m], sub.obs["G2M_score"].values[m],
                       s=14, color=col, label=state, linewidths=0, alpha=0.8)
        pct = 100 * (c == "cycling").mean()
        ax.axhline(0.1, color="#bbb", lw=0.6, ls="--"); ax.axvline(0.1, color="#bbb", lw=0.6, ls="--")
        ax.set_xlabel("G1/S score"); ax.set_ylabel("G2/M score")
        ax.set_title(f"{tum}  (N={sub.n_obs}, {pct:.0f}% cycling)")
        ax.legend(fontsize=7, frameon=False)

    # Fraction cycling per tumor (variability across tumors).
    frac = mal.obs.groupby("tumor", observed=True)["cycling"].apply(
        lambda s: 100 * (s == "cycling").mean()).sort_values()
    ax = axes[2]
    ax.barh(range(len(frac)), frac.values, color="#0d9488")
    ax.set_yticks(range(len(frac))); ax.set_yticklabels(frac.index, fontsize=7)
    ax.set_xlabel("% cycling cells"); ax.set_title("Cycling fraction per tumor")
    fig.suptitle("Figure 2 — Cell-cycle state among malignant melanoma cells (Tirosh 2016, reproduced)",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = os.path.join(RESULTS_DIR, "fig2_cell_cycle.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"==> Saved {out}")


def figure3(mal):
    print("==> Figure 3: MITF vs AXL programs…")
    score(mal, MITF_PROGRAM, "MITF_program")
    score(mal, AXL_PROGRAM, "AXL_program")
    x = mal.obs["MITF_program"].values
    y = mal.obs["AXL_program"].values
    r_all, _ = pearsonr(x, y) if len(x) > 2 else (np.nan, np.nan)

    # Per-tumor Pearson R (paper: negative correlation within each tumor).
    rows = []
    for tum, idx in mal.obs.groupby("tumor", observed=True).groups.items():
        sub = mal.obs.loc[idx]
        if len(sub) >= 20:
            r, _ = pearsonr(sub["MITF_program"], sub["AXL_program"])
            rows.append({"tumor": tum, "n_malignant": int(len(sub)),
                         "mean_MITF": round(float(sub["MITF_program"].mean()), 3),
                         "mean_AXL": round(float(sub["AXL_program"].mean()), 3),
                         "pearson_R": round(float(r), 3)})
    summ = pd.DataFrame(rows).sort_values("pearson_R")
    summ.to_csv(os.path.join(RESULTS_DIR, "mitf_axl_by_cell.csv"), index=False)
    print("==> Saved mitf_axl_by_cell.csv (per-tumor MITF/AXL summary)")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.4))
    tums = sorted(mal.obs["tumor"].unique())
    cmap = plt.get_cmap("tab20")
    for i, t in enumerate(tums):
        m = mal.obs["tumor"].values == t
        a1.scatter(x[m], y[m], s=12, color=cmap(i % 20), label=t, linewidths=0, alpha=0.75)
    a1.set_xlabel("MITF program score"); a1.set_ylabel("AXL program score")
    a1.set_title(f"Malignant cells: AXL vs MITF  (overall R = {r_all:.2f})")
    a1.legend(fontsize=6, ncol=2, frameon=False, loc="upper right")

    if len(summ):
        a2.barh(range(len(summ)), summ["pearson_R"].values,
                color=np.where(summ["pearson_R"] < 0, "#b2182b", "#2166ac"))
        a2.set_yticks(range(len(summ))); a2.set_yticklabels(summ["tumor"], fontsize=7)
        a2.axvline(0, color="#333", lw=0.6)
        a2.set_xlabel("Pearson R (MITF vs AXL)")
        a2.set_title("Within-tumor MITF–AXL correlation\n(negative = the two states anticorrelate)")
    fig.suptitle("Figure 3 — MITF-high (differentiated) vs AXL-high (resistant) states (Tirosh 2016, reproduced)",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = os.path.join(RESULTS_DIR, "fig3_mitf_axl.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"==> Saved {out}")


def main():
    if not os.path.exists(H5AD):
        sys.exit(f"ERROR: {H5AD} not found. Run step 2 (02_figure1_infercnv.py) first.")
    adata = sc.read_h5ad(H5AD)
    mal = adata[adata.obs["malignant"] == "malignant"].copy()
    if mal.n_obs < 30:
        sys.exit("ERROR: too few malignant cells to analyze.")
    print(f"==> {mal.n_obs} malignant cells across {mal.obs['tumor'].nunique()} tumors.")
    figure2(mal)
    figure3(mal)
    print("==> [03] Figures 2–3 complete. Next: 04_figures4_5_microenvironment.py")


if __name__ == "__main__":
    main()
