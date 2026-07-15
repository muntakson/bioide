#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_validate_vs_authors.py  (Ma 2019, liver — INDEPENDENT VALIDATION · 헌장 제2조)

Step 2 re-derived cell types and a malignant/HPC-like epithelial split WITHOUT
ever reading the authors' `Type` labels. THIS step is the only place those labels
are used — to check whether our independent GPU reanalysis reaches the SAME
conclusions as Ma et al. We quantify agreement and issue an honest verdict.

Metrics:
  - ARI / NMI between our Leiden clusters (and our cell types) and the authors'
    `Type` — do we partition the cells the same way?
  - Cell-type confusion matrix + label-agreement accuracy (after mapping the
    authors' labels onto our lineage names; the authors' "Malignant cell" and
    "HPC-like" both map to our epithelial lineage, as ductal type1/type2 → Ductal).
  - Malignant concordance: our unsupervised malignant/HPC-like epithelial call vs
    the authors' "Malignant cell" / "HPC-like" — precision / recall / F1 /
    accuracy / ARI on the epithelial compartment.

Inputs  (from $GHBIO_RESULTS, written by step 2):
  gpu_reanalysis.h5ad, author_labels.csv
Outputs (into $GHBIO_RESULTS):
  validation_summary.csv    metric · value · verdict
  validation_verdict.txt     human-readable overall verdict (folded into report/AI)
  confusion_celltype.csv/.png   our cell_type × authors' Type
  confusion_malignant.csv       epithelial malignant/HPC-like concordance
  validation_bars.png           ARI/NMI/accuracy summary bars
"""
import os
import sys

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
from sklearn.metrics import (  # noqa: E402
    adjusted_rand_score, normalized_mutual_info_score, confusion_matrix,
    precision_score, recall_score, f1_score, accuracy_score,
)

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))

# Map the authors' published labels onto our independent lineage names.
# "Malignant cell" + "HPC-like" are both tumour epithelial → our epithelial lineage.
AUTHOR_MAP = {
    "Malignant cell": "Epithelial", "HPC-like": "Epithelial",
    "T cell": "T cell", "B cell": "B cell",
    "TAM": "TAM", "CAF": "CAF", "TEC": "TEC",
}


def die(m):
    print(f"ERROR: {m}", file=sys.stderr)
    sys.exit(1)


def verdict(value, agree, partial):
    return "AGREE" if value >= agree else ("PARTIAL" if value >= partial else "DISAGREE")


h5 = os.path.join(R, "gpu_reanalysis.h5ad")
al = os.path.join(R, "author_labels.csv")
if not os.path.exists(h5):
    die(f"{h5} not found — run step 2 (02_gpu_reanalysis.py) first.")
if not os.path.exists(al):
    die(f"{al} not found — run step 2 first.")

print("==> [03] Loading our reanalysis + authors' labels")
adata = sc.read_h5ad(h5)
author = pd.read_csv(al, index_col=0)
author.index = author.index.astype(str)
adata.obs_names = adata.obs_names.astype(str)
common = adata.obs_names.intersection(author.index)
if len(common) < 100:
    die("could not align our cells with author_labels.csv by cell id.")
obs = adata.obs.loc[common].copy()
obs["author_cell_type"] = author.loc[common, "author_cell_type"].values
# drop the authors' "unclassified" cells from the label-agreement metrics
obs["author_lineage"] = obs["author_cell_type"].map(AUTHOR_MAP).fillna("other")
labelled = obs[obs["author_cell_type"] != "unclassified"]
print(f"    aligned {len(common):,} cells ({len(labelled):,} with a definite author label)")

rows = []  # (metric, value, verdict)

# --- 1. clustering agreement (ARI / NMI) ------------------------------------
ari_clusters = adjusted_rand_score(labelled["author_cell_type"], labelled["leiden_gpu"])
ari_types = adjusted_rand_score(labelled["author_cell_type"], labelled["cell_type"])
nmi_types = normalized_mutual_info_score(labelled["author_cell_type"], labelled["cell_type"])
rows += [
    ("ARI (our Leiden clusters vs authors' Type)", round(ari_clusters, 3), verdict(ari_clusters, 0.5, 0.3)),
    ("ARI (our cell types vs authors' Type)", round(ari_types, 3), verdict(ari_types, 0.5, 0.3)),
    ("NMI (our cell types vs authors' Type)", round(nmi_types, 3), verdict(nmi_types, 0.6, 0.4)),
]

# --- 2. cell-type label agreement (after lineage mapping) -------------------
mapped = obs[obs["author_lineage"] != "other"]
celltype_acc = accuracy_score(mapped["author_lineage"], mapped["cell_type"].astype(str))
rows.append(("Cell-type label agreement (accuracy vs authors)", round(celltype_acc, 3),
             verdict(celltype_acc, 0.8, 0.6)))

# confusion matrix: our cell_type (rows) × authors' Type (cols), column-normalised
ct_our = sorted(obs["cell_type"].astype(str).unique())
ct_auth = [t for t in AUTHOR_MAP if t in set(obs["author_cell_type"])]
cm = pd.crosstab(obs["cell_type"].astype(str), obs["author_cell_type"])
cm = cm.reindex(index=ct_our, columns=ct_auth, fill_value=0)
cm_norm = (cm / cm.sum(axis=0).replace(0, 1) * 100).round(1)
cm.to_csv(os.path.join(R, "confusion_celltype.csv"))

fig, ax = plt.subplots(figsize=(max(7, 0.7 * len(ct_auth) + 3), max(5, 0.5 * len(ct_our) + 2)))
im = ax.imshow(cm_norm.values, cmap="viridis", aspect="auto")
ax.set_xticks(range(len(ct_auth))); ax.set_xticklabels(ct_auth, rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(len(ct_our))); ax.set_yticklabels(ct_our, fontsize=8)
ax.set_xlabel("저자 라벨 (authors' Type)"); ax.set_ylabel("우리 독립 세포유형")
ax.set_title("세포유형 일치 (열=저자 라벨의 %가 우리 어느 유형으로)")
for i in range(len(ct_our)):
    for j in range(len(ct_auth)):
        v = cm_norm.values[i, j]
        if v >= 8:
            ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                    color="white" if v < 60 else "black", fontsize=7)
fig.colorbar(im, ax=ax, fraction=0.04, label="% of author label")
fig.tight_layout(); fig.savefig(os.path.join(R, "confusion_celltype.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# --- 3. malignant vs HPC-like epithelial concordance ------------------------
epi = obs[(obs["malignant_call"].isin(["malignant epithelial", "HPC-like epithelial"]))
          & (obs["author_cell_type"].isin(["Malignant cell", "HPC-like"]))].copy()
mal_metrics = {}
if len(epi) > 50:
    y_true = (epi["author_cell_type"] == "Malignant cell").astype(int).to_numpy()   # authors: malignant
    y_pred = (epi["malignant_call"] == "malignant epithelial").astype(int).to_numpy()
    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    ari_mal = adjusted_rand_score(y_true, y_pred)
    cmm = confusion_matrix(y_true, y_pred, labels=[1, 0])
    pd.DataFrame(cmm, index=["author malignant", "author HPC-like"],
                 columns=["our malignant", "our HPC-like"]).to_csv(os.path.join(R, "confusion_malignant.csv"))
    mal_metrics = {"accuracy": acc, "precision": prec, "recall": rec, "f1": f1, "ari": ari_mal, "n": len(epi)}
    rows += [
        ("Malignant-epithelial accuracy (ours vs authors' malignant/HPC-like)", round(acc, 3), verdict(acc, 0.8, 0.6)),
        ("Malignant-epithelial F1", round(f1, 3), verdict(f1, 0.8, 0.6)),
        ("Malignant-epithelial ARI", round(ari_mal, 3), verdict(ari_mal, 0.5, 0.3)),
    ]
else:
    rows.append(("Malignant-epithelial concordance", "n/a (too few overlapping epithelial cells)", "N/A"))

summary = pd.DataFrame(rows, columns=["metric", "value", "verdict"])
summary.to_csv(os.path.join(R, "validation_summary.csv"), index=False)

# --- 4. summary bar figure ---------------------------------------------------
barvals = [("ARI clusters", ari_clusters), ("ARI cell types", ari_types),
           ("NMI cell types", nmi_types), ("cell-type acc", celltype_acc)]
if mal_metrics:
    barvals += [("malignant acc", mal_metrics["accuracy"]), ("malignant F1", mal_metrics["f1"])]
fig, ax = plt.subplots(figsize=(8, 4.5))
names = [b[0] for b in barvals]; vals = [b[1] for b in barvals]
colors = ["#0d9488" if v >= 0.7 else "#f59e0b" if v >= 0.45 else "#dc2626" for v in vals]
ax.bar(names, vals, color=colors)
ax.axhline(0.7, color="#334155", ls="--", lw=0.8)
ax.set_ylim(0, 1); ax.set_ylabel("agreement (0–1)")
ax.set_title("독립 재분석 vs 원 논문 저자 라벨 — 일치도 (헌장 제2조)")
ax.tick_params(axis="x", rotation=20)
for i, v in enumerate(vals):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(R, "validation_bars.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# --- 5. overall verdict ------------------------------------------------------
def _overall():
    ct = verdict(celltype_acc, 0.8, 0.6)
    ml = verdict(mal_metrics["accuracy"], 0.8, 0.6) if mal_metrics else "N/A"
    if ct == "AGREE" and ml in ("AGREE", "N/A"):
        return "재현됨 (AGREE)", "우리 독립 GPU 재분석이 원 논문의 세포유형 구성과 악성 종양세포 결론을 재현합니다."
    if "DISAGREE" in (ct, ml):
        return "불일치 (DISAGREE)", "독립 재분석이 원 논문 결론과 상당히 어긋납니다 — 추가 검토가 필요합니다."
    return "부분 일치 (PARTIAL)", "핵심 결론은 대체로 재현되나 일부 세포유형/경계에서 차이가 있습니다."

vlabel, vtext = _overall()
lines = [
    "BioIDE 독립 검증 결과 (헌장 제2조) — Ma 2019 간암 (liver cancer)",
    "=" * 56,
    f"판정(Verdict): {vlabel}",
    vtext,
    "",
    f"세포유형 ARI(클러스터): {ari_clusters:.3f} | ARI(유형): {ari_types:.3f} | NMI: {nmi_types:.3f}",
    f"세포유형 라벨 일치 정확도: {celltype_acc:.3f}",
]
if mal_metrics:
    lines.append(
        f"악성/HPC-like 상피세포 판정: accuracy {mal_metrics['accuracy']:.3f} · precision {mal_metrics['precision']:.3f} · "
        f"recall {mal_metrics['recall']:.3f} · F1 {mal_metrics['f1']:.3f} (n={mal_metrics['n']:,} 상피세포)")
lines += [
    "",
    "주의(제6조): 이 검증은 저자의 라벨을 '정답'으로 간주해 우리 독립 결과와 비교한 것입니다.",
    "저자 라벨 자체의 절대적 정당성을 증명하는 것이 아니라, 서로 다른 두 독립 분석이",
    "같은 세포 분할·악성 판정에 수렴하는지를 봅니다. 특히 악성세포 vs HPC-like(간 전구세포",
    "유사) 경계는 두 집단 모두 상피성 유전자를 공유해 본질적으로 애매합니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")

print("\n".join(lines))
print("\n==> [03] Validation done. Wrote validation_summary.csv / validation_verdict.txt / figures.")
print("    Next: 4. AI 해석, 5. 리포트.")
