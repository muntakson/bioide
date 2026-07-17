#!/usr/bin/env python
"""
02_tme_annotate.py  —  Use 1 · annotate TME cell states + shared/tissue-specific analysis.

Scores canonical immune/stroma cell-STATE signatures on the integrated atlas
(tme_atlas.h5ad), assigns each Leiden cluster its dominant state, then builds the
key deliverable: a cell-state x cancer OCCURRENCE matrix (in how many tumour types
does each state appear) that separates pan-cancer "hallmark" states from
tissue-specific ones.

Outputs ($GHBIO_RESULTS):
  tme_cellstate_scores.csv     per-cluster mean signature scores
  tme_cellstate_occurrence.csv state x cancer presence matrix
  tme_cellstate_occurrence.png heatmap
  tme_atlas.h5ad               (updated in place with `cell_state`)
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
import numpy as np, pandas as pd, scanpy as sc
import anndata as _adcfg
try: _adcfg.settings.allow_write_nullable_strings=True
except Exception: pass
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

# minimal, extend as needed — canonical cross-cancer TME states
SIGNATURES = {
    "CD8_cytotoxic":  ["CD8A", "GZMB", "GZMK", "NKG7", "PRF1", "IFNG"],
    "CD8_exhausted":  ["PDCD1", "HAVCR2", "LAG3", "TIGIT", "CTLA4", "TOX"],
    "CD4_Treg":       ["FOXP3", "IL2RA", "IKZF2", "CTLA4"],
    "T_naive_memory": ["CCR7", "SELL", "TCF7", "IL7R"],
    "NK":             ["NCAM1", "KLRD1", "GNLY", "NKG7", "FCGR3A"],
    "B":              ["MS4A1", "CD79A", "CD19", "CD79B"],
    "Plasma":         ["MZB1", "IGHG1", "JCHAIN", "XBP1"],
    "TAM_SPP1":       ["SPP1", "MARCO", "TREM2", "APOE"],
    "TAM_C1Q":        ["C1QA", "C1QB", "C1QC", "CD68"],
    "Monocyte":       ["FCN1", "S100A8", "S100A9", "VCAN"],
    "cDC":            ["CLEC9A", "CD1C", "FCER1A", "LAMP3"],
    "myCAF":          ["ACTA2", "TAGLN", "MYH11", "COL1A1"],
    "iCAF":           ["IL6", "CXCL12", "PDGFRA", "CFD"],
    "Endo_tip":       ["PECAM1", "VWF", "ESM1", "ANGPT2"],
    "Endo_lymphatic": ["PROX1", "LYVE1", "CCL21", "PDPN"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--min-frac", type=float, default=0.01,
                    help="min cluster-fraction within a cancer to count as 'present'")
    args = ap.parse_args()
    R = Path(args.results)
    adata = sc.read_h5ad(R / "tme_atlas.h5ad")
    if adata.raw is not None:
        adata = adata.raw.to_adata()

    for name, genes in SIGNATURES.items():
        present = [g for g in genes if g in adata.var_names]
        if present:
            sc.tl.score_genes(adata, present, score_name=f"sig_{name}")

    sig_cols = [c for c in adata.obs.columns if c.startswith("sig_")]
    per_clu = adata.obs.groupby("leiden", observed=True)[sig_cols].mean()
    per_clu.to_csv(R / "tme_cellstate_scores.csv")
    clu_state = per_clu.idxmax(axis=1).str.replace("sig_", "", regex=False)
    adata.obs["cell_state"] = adata.obs["leiden"].map(clu_state).astype(str)

    # occurrence: for each state, in how many cancers does it exceed min-frac
    ct = pd.crosstab(adata.obs["cell_state"], adata.obs["cancer"], normalize="columns")
    occ = (ct >= args.min_frac).astype(int)
    occ["n_cancers"] = occ.sum(axis=1)
    occ.sort_values("n_cancers", ascending=False).to_csv(R / "tme_cellstate_occurrence.csv")

    plt.figure(figsize=(1.2 + 0.5 * ct.shape[1], 0.4 * ct.shape[0] + 1))
    plt.imshow(ct.values, aspect="auto", cmap="viridis")
    plt.xticks(range(ct.shape[1]), ct.columns, rotation=90, fontsize=7)
    plt.yticks(range(ct.shape[0]), ct.index, fontsize=7)
    plt.colorbar(label="fraction of cancer's TME"); plt.title("Cell state x cancer")
    plt.savefig(R / "tme_cellstate_occurrence.png", dpi=130, bbox_inches="tight"); plt.close()

    adata.write_h5ad(R / "tme_atlas.h5ad")
    print("==> [02] Done. cell_state assigned; occurrence matrix written. Next: 3. malignant NMF.")


if __name__ == "__main__":
    main()
