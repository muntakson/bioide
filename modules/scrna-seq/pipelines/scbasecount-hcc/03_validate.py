#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_validate.py  (scBaseCount HCC — independent validation, 헌장 제2조)

The ONLY step allowed to touch scBaseCount's per-cell `cell_type` labels. It compares
our INDEPENDENT re-derivation (02) against those labels and checks the biology:

  1. cell-type agreement — ARI / NMI between our marker-based `cell_type` and
     scBaseCount's `author_cell_type`, plus a confusion matrix and label-agreement
     accuracy on a coarse-lineage mapping,
  2. cross-study reproducibility — is the malignant-hepatocyte call and the TLS
     module CONSISTENT across independent samples/studies (the payoff of a uniformly
     processed atlas)? We report per-sample dispersion,
  3. TLS enrichment — are B cells + CXCL13⁺ Tfh + TLS chemokines enriched in tumour
     tissue vs any normal/adjacent tissue present,
and writes validation_summary.csv + a verdict + figures.

Reads only files written by step 2 (in $GHBIO_RESULTS). No bucket access needed.
"""
from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scanpy as sc  # noqa: E402
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score  # noqa: E402

# map scBaseCount free-text / ontology cell types onto our coarse lineages for a fair
# apples-to-apples agreement score.
LINEAGE_MAP = {
    "hepatocyte": "Hepatocyte", "malignant": "Hepatocyte", "epithelial": "Hepatocyte",
    "t cell": "T/NK", "t-cell": "T/NK", "nk": "T/NK", "natural killer": "T/NK", "lymphocyte": "T/NK",
    "b cell": "B", "b-cell": "B", "plasma": "B",
    "myeloid": "Myeloid", "macrophage": "Myeloid", "monocyte": "Myeloid", "dendritic": "Myeloid",
    "kupffer": "Myeloid", "neutrophil": "Myeloid",
    "endothelial": "Endothelial",
    "fibroblast": "Fibroblast", "stellate": "Fibroblast", "stromal": "Fibroblast", "mesenchymal": "Fibroblast",
}


def coarse(label: str) -> str:
    s = str(label).lower()
    for k, v in LINEAGE_MAP.items():
        if k in s:
            return v
    return "Other"


def savefig(path):
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    args = ap.parse_args()
    R = args.results
    metrics = {}

    adata = sc.read_h5ad(os.path.join(R, "gpu_reanalysis.h5ad"))
    auth = pd.read_csv(os.path.join(R, "author_labels.csv"), index_col=0)
    auth = auth.reindex(adata.obs_names)

    # ---- 1. cell-type agreement vs scBaseCount labels ------------------------
    ours = adata.obs["cell_type"].astype(str)
    theirs_fine = auth["author_cell_type"].astype(str)
    valid = theirs_fine.notna() & (theirs_fine.str.lower() != "unknown")
    if valid.sum() > 10:
        our_c = ours[valid].map(lambda s: s)  # already coarse lineages
        their_c = theirs_fine[valid].map(coarse)
        metrics["celltype_ARI"] = float(adjusted_rand_score(their_c, our_c))
        metrics["celltype_NMI"] = float(normalized_mutual_info_score(their_c, our_c))
        metrics["celltype_accuracy"] = float((their_c.values == our_c.values).mean())
        conf = pd.crosstab(our_c, their_c)
        conf.to_csv(os.path.join(R, "confusion_celltype.csv"))
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(conf.values, cmap="Blues", aspect="auto")
        ax.set_xticks(range(len(conf.columns))); ax.set_xticklabels(conf.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(conf.index))); ax.set_yticklabels(conf.index)
        ax.set_xlabel("scBaseCount cell_type (coarse)"); ax.set_ylabel("our cell_type")
        ax.set_title("Cell-type confusion (ours vs scBaseCount)")
        fig.colorbar(im); savefig(os.path.join(R, "confusion_celltype.png"))

    # ---- 2. cross-study reproducibility --------------------------------------
    if os.path.exists(os.path.join(R, "composition_by_sample.csv")):
        cs = pd.read_csv(os.path.join(R, "composition_by_sample.csv"))
        for c in ("pct_malignant_of_hep", "pct_B", "pct_cxcl13_tfh"):
            if c in cs:
                metrics[f"cross_study_mean_{c}"] = float(cs[c].mean(skipna=True))
                metrics[f"cross_study_sd_{c}"] = float(cs[c].std(skipna=True))
        metrics["n_samples"] = int(cs["srx"].nunique()) if "srx" in cs else len(cs)

    # ---- 3. TLS enrichment: tumour vs normal ---------------------------------
    verdict_lines = []
    if os.path.exists(os.path.join(R, "tls_module_by_tissue.csv")):
        tt = pd.read_csv(os.path.join(R, "tls_module_by_tissue.csv"))
        gcol = "tissue" if "tissue" in tt else tt.columns[0]
        low = tt[gcol].astype(str).str.lower()
        tumor = tt[low.str.contains("tumor|tumour|carcinoma|hcc|malig")]
        normal = tt[low.str.contains("normal|adjacent|healthy|non-tumor|nontumor")]
        if not tumor.empty:
            for c, lbl in [("pct_B", "B%"), ("pct_cxcl13_tfh", "CXCL13+Tfh%"),
                           ("mean_tls_chemokine", "TLSchemokine")]:
                tv = tumor[c].mean()
                metrics[f"tumor_{c}"] = float(tv)
                if not normal.empty:
                    nv = normal[c].mean()
                    metrics[f"normal_{c}"] = float(nv)
                    verdict_lines.append(f"{lbl}: tumour {tv:.2f} vs normal {nv:.2f} "
                                         f"({'↑' if tv > nv else '↓'})")

        fig, ax = plt.subplots(figsize=(7, 4))
        x = np.arange(len(tt))
        ax.bar(x - 0.2, tt["pct_B"], width=0.4, label="% B")
        ax.bar(x + 0.2, tt["pct_cxcl13_tfh"], width=0.4, label="% CXCL13⁺ Tfh")
        ax.set_xticks(x); ax.set_xticklabels(tt[gcol].astype(str), rotation=30, ha="right")
        ax.set_ylabel("% of cells"); ax.set_title("TLS components by tissue"); ax.legend()
        savefig(os.path.join(R, "tls_validation.png"))

    # ---- verdict --------------------------------------------------------------
    ari = metrics.get("celltype_ARI", np.nan)
    acc = metrics.get("celltype_accuracy", np.nan)
    if not np.isnan(acc):
        if acc >= 0.8 and ari >= 0.5:
            verdict = "AGREE"
        elif acc >= 0.6:
            verdict = "PARTIAL"
        else:
            verdict = "DISAGREE"
    else:
        verdict = "INCONCLUSIVE"
    metrics["verdict"] = verdict

    pd.DataFrame([metrics]).T.rename(columns={0: "value"}).to_csv(
        os.path.join(R, "validation_summary.csv"))
    with open(os.path.join(R, "validation_verdict.txt"), "w") as fh:
        fh.write(f"VERDICT: {verdict}\n")
        fh.write(f"cell-type accuracy={acc:.3f} ARI={ari:.3f} NMI={metrics.get('celltype_NMI', float('nan')):.3f}\n")
        for ln in verdict_lines:
            fh.write("TLS " + ln + "\n")

    # validation bars
    keys = [k for k in ("celltype_ARI", "celltype_NMI", "celltype_accuracy") if k in metrics]
    if keys:
        plt.figure(figsize=(5, 4))
        plt.bar(keys, [metrics[k] for k in keys])
        plt.ylim(0, 1); plt.title(f"Validation vs scBaseCount labels — {verdict}")
        plt.xticks(rotation=20, ha="right"); savefig(os.path.join(R, "validation_bars.png"))

    print(f"==> [03] validation verdict: {verdict}")
    print(pd.DataFrame([metrics]).T.rename(columns={0: "value"}).to_string())


if __name__ == "__main__":
    main()
