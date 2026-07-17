#!/usr/bin/env python
"""
05_progression.py  —  Use 3 (bonus) · cross-cancer dedifferentiation trajectory.

Four source studies carry ordered normal->tumour->metastasis stage labels
(lung Kim origin_label, HCC Lu site, HNSCC Choi stage, thyroid Pu site). For the
malignant cells of each, we compute a proliferation signature and a "normal-tissue
identity" signature, then track how far the malignant program drifts from normal
identity along the progression axis — one shared hero figure across cancers.

Outputs ($GHBIO_RESULTS):
  progression_scores.csv        study x stage mean scores
  progression_dedifferentiation.png
"""
from __future__ import annotations
import argparse, os, glob
from pathlib import Path
import numpy as np, pandas as pd, scanpy as sc
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

PROLIF = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CDK1"]
# per-cancer "normal differentiation" markers (identity the malignant cells lose)
NORMAL_IDENTITY = {
    "Lung adeno":     ["SFTPC", "SFTPB", "NAPSA", "NKX2-1"],
    "Liver HCC":      ["ALB", "APOA1", "TTR", "CYP2E1"],
    "Liver HCC/iCCA": ["ALB", "APOA1", "TTR", "CYP2E1"],
    "Thyroid PTC":    ["TG", "TPO", "TSHR", "PAX8"],
    "Head & neck":    ["KRT5", "KRT14", "TP63", "SFN"],
}
# ordering of stage strings (best-effort; unknown stages keep input order)
STAGE_ORDER = ["Normal", "nLung", "NL", "Paratumor", "N", "Primary tumor", "tLung",
               "LP", "Tumor", "CA", "T", "PVTT", "LN metastasis", "mLN", "LN",
               "Lymph", "Distant metastasis", "mBrain"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    args = ap.parse_args()
    R = Path(args.results)

    rows = []
    for f in sorted(glob.glob(str(R / "harmonized" / "*.malignant.h5ad"))):
        a = sc.read_h5ad(f)
        if not a.n_obs:
            continue
        cancer = a.obs["cancer"].iloc[0]
        if cancer not in NORMAL_IDENTITY or a.obs["progression"].nunique() < 2:
            continue
        if "counts" in a.layers:
            a.X = a.layers["counts"].copy()
        sc.pp.normalize_total(a, target_sum=1e4); sc.pp.log1p(a)
        for name, genes in [("prolif", PROLIF), ("normal_identity", NORMAL_IDENTITY[cancer])]:
            g = [x for x in genes if x in a.var_names]
            sc.tl.score_genes(a, g, score_name=name) if g else a.obs.__setitem__(name, np.nan)
        m = a.obs.groupby("progression", observed=True)[["prolif", "normal_identity"]].mean()
        m["dediff"] = -m["normal_identity"]
        for stage, r in m.iterrows():
            rows.append({"cancer": cancer, "stage": str(stage),
                         "prolif": r["prolif"], "normal_identity": r["normal_identity"],
                         "dediff": r["dediff"]})

    df = pd.DataFrame(rows)
    df.to_csv(R / "progression_scores.csv", index=False)
    if len(df):
        order = {s: i for i, s in enumerate(STAGE_ORDER)}
        df["ord"] = df["stage"].map(lambda s: order.get(s, 99))
        plt.figure(figsize=(6, 4))
        for cancer, d in df.sort_values("ord").groupby("cancer"):
            plt.plot(range(len(d)), d["dediff"], marker="o", label=cancer)
            for x, s in enumerate(d["stage"]):
                plt.annotate(s, (x, list(d["dediff"])[x]), fontsize=6)
        plt.ylabel("dedifferentiation (−normal identity)")
        plt.xlabel("progression stage →"); plt.legend(fontsize=7)
        plt.title("Cross-cancer dedifferentiation along progression")
        plt.savefig(R / "progression_dedifferentiation.png", dpi=130, bbox_inches="tight")
        plt.close()
    print(f"==> [05] Done. {df['cancer'].nunique() if len(df) else 0} cancers plotted. Next: 6. validate.")


if __name__ == "__main__":
    main()
