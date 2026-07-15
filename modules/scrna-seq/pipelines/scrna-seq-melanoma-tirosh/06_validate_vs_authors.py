#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
06_validate_vs_authors.py  (Tirosh 2016, melanoma — INDEPENDENT re-derivation + VALIDATION)

The figure steps (02–04) reproduce the paper's panels but LEAN ON the authors'
embedded labels (GSE72056 header: malignant flag + cell type). Per the BioIDE
constitution (제1조), this step instead RE-DERIVES cell types and the malignant
call from scratch — using only the expression matrix, never the authors' labels —
and THEN (제2조) compares our independent result to the authors' labels to judge
reproduction.

Independent pipeline (author labels withheld to author_labels.csv):
  log2(TPM/10+1) matrix → HVG → scale → PCA → neighbours → Leiden → UMAP
  → Wilcoxon markers → marker-based cell-type annotation (melanoma ecosystem)
  → malignant call = cells assigned the melanocytic "Malignant" lineage
    (MLANA/PMEL/MITF/TYR/DCT…), cross-checked against the independent inferCNV
    aneuploidy signal (cnv_signal) already in the object.

Validation vs the authors' labels:
  - Malignant concordance: our malignant/normal vs authors' malignant flag
    (accuracy / precision / recall / F1 / ARI).
  - Cell-type agreement: our lineage vs authors' cell type on the non-malignant
    compartment (accuracy, ARI, confusion matrix).

Outputs (into $GHBIO_RESULTS):
  validation_summary.csv, validation_verdict.txt,
  celltype_annotation.csv, confusion_celltype.csv/.png, validation_bars.png,
  author_labels.csv
"""
import os
import sys

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
from sklearn.metrics import (  # noqa: E402
    adjusted_rand_score, accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix,
)

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))
SEED = 2016

# Canonical melanoma-ecosystem markers (Tirosh 2016). "Malignant" = melanocytic lineage.
MARKERS = {
    "Malignant": ["MLANA", "PMEL", "MITF", "TYR", "DCT", "TYRP1", "SLC45A2", "S100B", "GPNMB", "PLP1"],
    "T cell": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "IL7R", "IL32", "TRAC"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGKC"],
    "Macrophage": ["LYZ", "CD68", "AIF1", "FCER1G", "TYROBP", "CD14", "C1QA", "C1QB"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5", "CDH5", "CALCRL", "EGFL7", "IGFBP7"],
    "CAF": ["COL1A1", "COL1A2", "COL3A1", "COL6A3", "PCOLCE", "FAP", "PDGFRB", "DCN"],
    "NK": ["NKG7", "GNLY", "KLRD1", "PRF1", "IL2RB", "KLRF1"],
}
# authors' non-malignant cell types (their header categories) for the cell-type comparison
AUTHOR_CT = ["T cell", "B cell", "Macrophage", "Endothelial", "CAF", "NK"]


def die(m):
    print(f"ERROR: {m}", file=sys.stderr)
    sys.exit(1)


def verdict(v, agree, partial):
    return "AGREE" if v >= agree else ("PARTIAL" if v >= partial else "DISAGREE")


def annotate(adata, groupby):
    cols = {}
    for lin, genes in MARKERS.items():
        present = [g for g in genes if g in adata.var_names]
        c = f"_s_{lin}"
        if present:
            sc.tl.score_genes(adata, present, score_name=c, use_raw=False)
        else:
            adata.obs[c] = 0.0
        cols[lin] = c
    per = adata.obs.groupby(groupby, observed=True)[list(cols.values())].mean()
    per.columns = list(cols.keys())
    assigned = per.idxmax(axis=1)
    adata.obs["cell_type"] = adata.obs[groupby].map(assigned).astype("category")
    adata.obs.drop(columns=list(cols.values()), inplace=True)
    return assigned


h5 = os.path.join(R, "melanoma_processed.h5ad")
if not os.path.exists(h5):
    die(f"{h5} not found — run step 2 (02_figure1_infercnv.py) first.")

print("==> [06] Loading processed melanoma object")
full = sc.read_h5ad(h5)

# 헌장 제1조: stash the authors' labels, then withhold them from the analysis.
author = pd.DataFrame(index=full.obs_names)
author["author_malignant"] = full.obs["malignant"].astype(str).values
author["author_celltype"] = full.obs["celltype"].astype(str).values
author.to_csv(os.path.join(R, "author_labels.csv"))

adata = full.copy()
cnv = full.obs["cnv_signal"].values if "cnv_signal" in full.obs else None
for c in ("malignant", "celltype", "group"):
    if c in adata.obs:
        del adata.obs[c]

# --- independent re-derivation (no author labels) ---------------------------
print("==> Independent clustering + marker annotation (author labels withheld)")
sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=2000)
adata.raw = adata
work = adata[:, adata.var["highly_variable"]].copy()
sc.pp.scale(work, max_value=10)
sc.tl.pca(work, n_comps=min(30, work.n_obs - 1, work.n_vars - 1), svd_solver="arpack", random_state=SEED)
sc.pp.neighbors(work, n_pcs=min(30, work.obsm["X_pca"].shape[1]), n_neighbors=15, random_state=SEED)
sc.tl.leiden(work, key_added="leiden", resolution=1.0, flavor="igraph",
             n_iterations=2, directed=False, random_state=SEED)
adata.obs["leiden"] = work.obs["leiden"].values
sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon", use_raw=False, n_genes=25)
assigned = annotate(adata, "leiden")
n_clusters = adata.obs["leiden"].nunique()
print(f"    {n_clusters} clusters → cell types: "
      + ", ".join(f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()))

# independent malignant call: melanocytic ("Malignant") lineage, cross-checked with CNV
adata.obs["malignant_call"] = np.where(
    adata.obs["cell_type"].astype(str) == "Malignant", "malignant", "normal")
if cnv is not None:
    # a cluster called Malignant should also carry elevated aneuploidy; report the check
    mal_cnv = float(np.mean(cnv[adata.obs["malignant_call"].values == "malignant"]))
    norm_cnv = float(np.mean(cnv[adata.obs["malignant_call"].values == "normal"]))
    print(f"    CNV cross-check — malignant {mal_cnv:.4f} vs normal {norm_cnv:.4f} aneuploidy")

pd.DataFrame({
    "cluster": assigned.index, "cell_type": assigned.values,
    "n_cells": adata.obs["leiden"].value_counts().reindex(assigned.index).astype(int).values,
}).to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)

# --- validation vs authors' labels (제2조) ----------------------------------
obs = adata.obs.join(author)
rows = []

# 1) malignant concordance (cells the authors resolved as normal/malignant)
resolved = obs[obs["author_malignant"].isin(["normal", "malignant"])].copy()
y_true = (resolved["author_malignant"] == "malignant").astype(int).to_numpy()
y_pred = (resolved["malignant_call"] == "malignant").astype(int).to_numpy()
mal_acc = accuracy_score(y_true, y_pred)
mal_prec = precision_score(y_true, y_pred, zero_division=0)
mal_rec = recall_score(y_true, y_pred, zero_division=0)
mal_f1 = f1_score(y_true, y_pred, zero_division=0)
mal_ari = adjusted_rand_score(y_true, y_pred)
rows += [
    ("악성세포 판정 정확도 (ours vs authors' malignant)", round(mal_acc, 3), verdict(mal_acc, 0.85, 0.65)),
    ("악성세포 판정 F1", round(mal_f1, 3), verdict(mal_f1, 0.85, 0.65)),
    ("악성세포 판정 ARI", round(mal_ari, 3), verdict(mal_ari, 0.5, 0.3)),
]

# 2) cell-type agreement on the non-malignant compartment
nm = obs[obs["author_celltype"].isin(AUTHOR_CT)].copy()
ct_acc = accuracy_score(nm["author_celltype"], nm["cell_type"].astype(str))
ct_ari = adjusted_rand_score(nm["author_celltype"], nm["cell_type"].astype(str))
rows += [
    ("세포유형 일치 정확도 (비악성, ours vs authors)", round(ct_acc, 3), verdict(ct_acc, 0.8, 0.6)),
    ("세포유형 ARI (비악성)", round(ct_ari, 3), verdict(ct_ari, 0.5, 0.3)),
]

# confusion matrix (our cell_type × authors' cell type), column-normalised
ct_our = sorted(nm["cell_type"].astype(str).unique())
cm = pd.crosstab(nm["cell_type"].astype(str), nm["author_celltype"]).reindex(
    index=ct_our, columns=AUTHOR_CT, fill_value=0)
cm.to_csv(os.path.join(R, "confusion_celltype.csv"))
cm_norm = (cm / cm.sum(axis=0).replace(0, 1) * 100).round(1)
fig, ax = plt.subplots(figsize=(max(7, 0.8 * len(AUTHOR_CT) + 3), max(4.5, 0.5 * len(ct_our) + 2)))
im = ax.imshow(cm_norm.values, cmap="viridis", aspect="auto")
ax.set_xticks(range(len(AUTHOR_CT))); ax.set_xticklabels(AUTHOR_CT, rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(len(ct_our))); ax.set_yticklabels(ct_our, fontsize=8)
ax.set_xlabel("저자 라벨 (authors' cell type)"); ax.set_ylabel("우리 독립 세포유형")
ax.set_title("세포유형 일치 (열=저자 라벨의 %가 우리 어느 유형으로)")
for i in range(len(ct_our)):
    for j in range(len(AUTHOR_CT)):
        v = cm_norm.values[i, j]
        if v >= 8:
            ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                    color="white" if v < 60 else "black", fontsize=7)
fig.colorbar(im, ax=ax, fraction=0.04, label="% of author label")
fig.tight_layout(); fig.savefig(os.path.join(R, "confusion_celltype.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

summary = pd.DataFrame(rows, columns=["metric", "value", "verdict"])
summary.to_csv(os.path.join(R, "validation_summary.csv"), index=False)

# summary bars
barvals = [("malignant acc", mal_acc), ("malignant F1", mal_f1),
           ("celltype acc", ct_acc), ("celltype ARI", ct_ari)]
fig, ax = plt.subplots(figsize=(8, 4.5))
names = [b[0] for b in barvals]; vals = [b[1] for b in barvals]
colors = ["#0d9488" if v >= 0.7 else "#f59e0b" if v >= 0.45 else "#dc2626" for v in vals]
ax.bar(names, vals, color=colors); ax.axhline(0.7, color="#334155", ls="--", lw=0.8)
ax.set_ylim(0, 1); ax.set_ylabel("agreement (0–1)")
ax.set_title("독립 재분석 vs 원 논문 저자 라벨 — 일치도 (헌장 제2조)")
for i, v in enumerate(vals):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(R, "validation_bars.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# overall verdict
ml = verdict(mal_acc, 0.85, 0.65)
ct = verdict(ct_acc, 0.8, 0.6)
if ml == "AGREE" and ct in ("AGREE", "PARTIAL"):
    vlabel, vtext = "재현됨 (AGREE)", "우리 독립 재분석이 원 논문의 악성세포 판정과 세포유형 구성을 재현합니다."
elif "DISAGREE" in (ml, ct):
    vlabel, vtext = "불일치 (DISAGREE)", "독립 재분석이 원 논문 결론과 상당히 어긋납니다 — 추가 검토가 필요합니다."
else:
    vlabel, vtext = "부분 일치 (PARTIAL)", "핵심 결론은 대체로 재현되나 일부 세포유형에서 차이가 있습니다."

lines = [
    "BioIDE 독립 검증 결과 (헌장 제2조) — Tirosh 2016 melanoma (GSE72056)",
    "=" * 60,
    f"판정(Verdict): {vlabel}",
    vtext,
    "",
    f"악성세포 판정: accuracy {mal_acc:.3f} · precision {mal_prec:.3f} · recall {mal_rec:.3f} · "
    f"F1 {mal_f1:.3f} · ARI {mal_ari:.3f} (n={len(resolved):,})",
    f"세포유형 일치(비악성): accuracy {ct_acc:.3f} · ARI {ct_ari:.3f} (n={len(nm):,})",
    "",
    "주의(제6조): 저자 라벨을 '정답'으로 간주해 우리 독립 결과와 비교했습니다. 저자 라벨 자체의",
    "절대적 정당성이 아니라, 서로 다른 두 독립 분석이 같은 악성 판정·세포유형에 수렴하는지를 봅니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print("\n==> [06] Validation done. Wrote validation_summary.csv / validation_verdict.txt / figures.")
