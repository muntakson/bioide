#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_validate_vs_authors.py  (Pu 2021, PTC — INDEPENDENT VALIDATION · 헌장 제2조)

Step 2 re-derived cell types and a malignant/normal thyrocyte split WITHOUT any
author labels — none are distributed on GEO for GSE184362. THIS step is where we
check whether our independent GPU reanalysis reaches the SAME conclusions as the
paper. Because there is no per-cell "answer key", we validate against the paper's
PUBLISHED CLAIMS and quantify agreement:

  C1. Lineage / marker recovery — did we recover the paper's major lineages
      (thyrocyte, T/NK, B, plasma, myeloid, endothelial, fibroblast), and are each
      lineage's canonical markers most enriched in the cells we labelled that
      lineage (marker self-consistency / diagonal dominance)?
  C2. Malignant thyrocytes have a LOWER thyroid-differentiation score (TDS) than
      normal follicular cells (Pu 2021, Fig. on normal→malignant axis).
  C3. TMSB4X rises along the progression axis (primary → LN-met → distant met).
  C4. Malignant thyrocytes are enriched in tumour / metastatic sites vs paratumor.

Inputs  (from $GHBIO_RESULTS, written by step 2):
  gpu_reanalysis.h5ad, celltype_composition.csv, thyrocyte_summary.csv,
  malignant_by_site.csv
Outputs (into $GHBIO_RESULTS):
  validation_summary.csv    claim · metric · value · verdict
  validation_verdict.txt    human-readable overall verdict (folded into report/AI)
  marker_recovery.csv/.png  per-lineage marker self-consistency
  validation_bars.png       claim-agreement summary bars
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
from scipy.stats import spearmanr  # noqa: E402

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))

# The paper's major reported lineages that an independent reanalysis should recover.
EXPECTED_LINEAGES = ["Thyrocyte", "T-NK cell", "B cell", "Plasma cell",
                     "Myeloid", "Endothelial", "Fibroblast"]
# Canonical marker sets (mirror of step 2's, used here to score self-consistency).
LINEAGE_MARKERS = {
    "Thyrocyte": ["TG", "EPCAM", "KRT18", "KRT19", "TFF3", "TPO", "DIO2", "TSHR", "PAX8", "NKX2-1"],
    "T-NK cell": ["CD3D", "CD3E", "CD3G", "CD247", "CD8A", "IL7R", "NKG7", "KLRD1", "GNLY"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "IGHM", "IGHD", "CD19"],
    "Plasma cell": ["MZB1", "SDC1", "XBP1", "IGHG1", "PRDM1", "DERL3"],
    "Myeloid": ["LYZ", "S100A8", "S100A9", "CD14", "CD68", "CD163", "C1QA", "C1QB", "FCGR3A"],
    "Dendritic cell": ["CD1C", "FCER1A", "CLEC9A", "LILRA4", "LAMP3"],
    "Mast cell": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT"],
    "Endothelial": ["PECAM1", "CDH5", "VWF", "CD34", "EGFL7", "RAMP2"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "ACTA2", "TAGLN", "DCN", "PDGFRB", "RGS5"],
}
TUMOR_SITES = ["Primary tumor", "LN metastasis", "Distant metastasis"]


def die(m):
    print(f"ERROR: {m}", file=sys.stderr)
    sys.exit(1)


def verdict(value, agree, partial):
    return "AGREE" if value >= agree else ("PARTIAL" if value >= partial else "DISAGREE")


h5 = os.path.join(R, "gpu_reanalysis.h5ad")
if not os.path.exists(h5):
    die(f"{h5} not found — run step 2 (02_gpu_reanalysis.py) first.")

print("==> [03] Loading our reanalysis")
adata = sc.read_h5ad(h5)
rows = []  # (claim, metric, value, verdict)

# --- C1. lineage / marker recovery (self-consistency) -----------------------
print("==> C1: lineage & marker recovery")
score_cols = {}
for lin, genes in LINEAGE_MARKERS.items():
    present = [g for g in genes if g in adata.var_names]
    col = f"_s_{lin}"
    if present:
        sc.tl.score_genes(adata, present, score_name=col, use_raw=False)
    else:
        adata.obs[col] = np.nan
    score_cols[lin] = col

our_types = [t for t in adata.obs["cell_type"].astype(str).unique()]
recovered = [t for t in EXPECTED_LINEAGES if t in our_types]
coverage = len(recovered) / len(EXPECTED_LINEAGES)

# marker self-consistency: for each cell type we assigned, is its OWN lineage
# marker score the highest (on average over its cells) among all lineage scores?
per = adata.obs.groupby("cell_type", observed=True)[list(score_cols.values())].mean()
per.columns = list(score_cols.keys())
consistent = 0
checked = 0
recov_rows = []
for ct in per.index:
    if ct not in LINEAGE_MARKERS:
        continue
    checked += 1
    top = per.loc[ct].astype(float).idxmax()
    ok = (top == ct)
    consistent += int(ok)
    recov_rows.append({"our_cell_type": ct, "own_marker_score": round(float(per.loc[ct, ct]), 4),
                       "best_scoring_lineage": top, "self_consistent": ok})
self_consistency = consistent / checked if checked else 0.0
pd.DataFrame(recov_rows).to_csv(os.path.join(R, "marker_recovery.csv"), index=False)
rows += [
    ("C1 세포계통 재현 (lineage recovery)",
     f"{len(recovered)}/{len(EXPECTED_LINEAGES)} lineages ({', '.join(recovered)})",
     round(coverage, 3), verdict(coverage, 0.85, 0.6)),
    ("C1 marker 자기일치도 (marker self-consistency)",
     "각 세포유형의 자기 marker 점수가 최대인 비율", round(self_consistency, 3),
     verdict(self_consistency, 0.8, 0.6)),
]
adata.obs.drop(columns=list(score_cols.values()), inplace=True)

# --- C2. malignant thyrocytes have LOWER thyroid-differentiation score ------
print("==> C2: malignant TDS drop")
tds_delta = None
tds_ok = "N/A"
tsum_path = os.path.join(R, "thyrocyte_summary.csv")
if os.path.exists(tsum_path):
    ts = pd.read_csv(tsum_path).set_index("malignant_call")
    if {"malignant thyrocyte", "normal thyrocyte"}.issubset(ts.index) and "mean_tds" in ts.columns:
        tds_delta = float(ts.loc["normal thyrocyte", "mean_tds"] - ts.loc["malignant thyrocyte", "mean_tds"])
        # claim reproduced if malignant TDS is clearly lower (positive delta)
        tds_ok = "AGREE" if tds_delta > 0.05 else ("PARTIAL" if tds_delta > 0 else "DISAGREE")
        rows.append(("C2 악성 TDS 감소 (normal − malignant TDS)",
                     "정상 대비 악성 갑상선세포의 분화점수 하락폭 (>0 이면 주장 방향 일치)",
                     round(tds_delta, 4), tds_ok))
    else:
        rows.append(("C2 악성 TDS 감소", "thyrocyte_summary.csv 에 두 그룹이 없어 평가 불가", "n/a", "N/A"))
else:
    rows.append(("C2 악성 TDS 감소", "thyrocyte_summary.csv 없음", "n/a", "N/A"))

# --- C3. TMSB4X rises along the progression axis ----------------------------
print("==> C3: TMSB4X progression gradient")
tmsb_rho = None
tmsb_ok = "N/A"
enrich_ok = "N/A"
mbs_path = os.path.join(R, "malignant_by_site.csv")
if os.path.exists(mbs_path):
    mbs = pd.read_csv(mbs_path, index_col=0)
    tum = mbs[mbs["site_rank"] >= 1].dropna(subset=["mean_TMSB4X"])
    if len(tum) >= 3 and tum["mean_TMSB4X"].nunique() > 1:
        tmsb_rho, _ = spearmanr(tum["site_rank"], tum["mean_TMSB4X"])
        tmsb_ok = verdict(tmsb_rho, 0.7, 0.3)
        rows.append(("C3 TMSB4X 진행 구배 (Spearman ρ vs site rank)",
                     "원발→림프절→원격 전이로 갈수록 TMSB4X 상승 (ρ>0 이면 방향 일치)",
                     round(float(tmsb_rho), 3), tmsb_ok))
    else:
        rows.append(("C3 TMSB4X 진행 구배", "종양/전이 site가 3개 미만이라 평가 불가", "n/a", "N/A"))

    # --- C4. malignant thyrocyte enrichment in tumour/metastasis vs paratumor ---
    print("==> C4: malignant enrichment by site")
    if "Paratumor" in mbs.index and "pct_malignant" in mbs.columns:
        para = float(mbs.loc["Paratumor", "pct_malignant"])
        tumor_sites = mbs[mbs.index.isin(TUMOR_SITES)]
        if len(tumor_sites):
            tumor_mean = float(tumor_sites["pct_malignant"].mean())
            enrich_delta = tumor_mean - para
            enrich_ok = "AGREE" if enrich_delta > 15 else ("PARTIAL" if enrich_delta > 0 else "DISAGREE")
            rows.append(("C4 악성 조직 편중 (tumor − paratumor 악성%)",
                         f"paratumor {para:.1f}% → tumor/metastasis {tumor_mean:.1f}% (양수면 주장 일치)",
                         round(enrich_delta, 2), enrich_ok))
    else:
        rows.append(("C4 악성 조직 편중", "Paratumor site가 없어 평가 불가", "n/a", "N/A"))
else:
    rows.append(("C3 TMSB4X 진행 구배", "malignant_by_site.csv 없음", "n/a", "N/A"))
    rows.append(("C4 악성 조직 편중", "malignant_by_site.csv 없음", "n/a", "N/A"))

summary = pd.DataFrame(rows, columns=["claim", "metric", "value", "verdict"])
summary.to_csv(os.path.join(R, "validation_summary.csv"), index=False)

# --- marker-recovery figure --------------------------------------------------
fig, ax = plt.subplots(figsize=(max(7, 0.9 * len(per.index) + 2), 4.6))
diag = [float(per.loc[ct, ct]) if ct in per.columns else 0.0 for ct in per.index]
colors = ["#0d9488" if (ct in LINEAGE_MARKERS and per.loc[ct].astype(float).idxmax() == ct)
          else "#f59e0b" for ct in per.index]
ax.bar([str(c) for c in per.index], diag, color=colors)
ax.set_ylabel("own-lineage marker score")
ax.set_title("C1 marker 자기일치 — 각 세포유형에서 자기 계통 marker 발현 (초록=최대)")
ax.tick_params(axis="x", rotation=25)
fig.tight_layout(); fig.savefig(os.path.join(R, "marker_recovery.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# --- claim-agreement summary bars -------------------------------------------
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan

barvals = [("C1 lineage", coverage), ("C1 marker", self_consistency)]
if tds_delta is not None:
    barvals.append(("C2 TDS↓", min(max(tds_delta * 4, 0), 1)))     # scale delta into 0–1 for display
if tmsb_rho is not None:
    barvals.append(("C3 TMSB4X↑", max(float(tmsb_rho), 0)))
if enrich_ok not in ("N/A",):
    m = num(summary.loc[summary["claim"].str.startswith("C4"), "value"].iloc[0])
    barvals.append(("C4 enrich", min(max(m / 50, 0), 1) if not np.isnan(m) else 0))
fig, ax = plt.subplots(figsize=(8, 4.5))
names = [b[0] for b in barvals]; vals = [b[1] for b in barvals]
colors = ["#0d9488" if v >= 0.7 else "#f59e0b" if v >= 0.4 else "#dc2626" for v in vals]
ax.bar(names, vals, color=colors)
ax.axhline(0.7, color="#334155", ls="--", lw=0.8)
ax.set_ylim(0, 1); ax.set_ylabel("agreement (0–1, 표시용 정규화)")
ax.set_title("독립 재분석 vs 원 논문 주장 — 일치도 (헌장 제2조)")
ax.tick_params(axis="x", rotation=15)
for i, v in enumerate(vals):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(R, "validation_bars.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# --- overall verdict ---------------------------------------------------------
verds = [r[3] for r in rows if r[3] in ("AGREE", "PARTIAL", "DISAGREE")]
n_agree = verds.count("AGREE")
n_dis = verds.count("DISAGREE")
if verds and n_dis == 0 and n_agree >= max(2, len(verds) - 1):
    vlabel = "재현됨 (AGREE)"
    vtext = "우리 독립 GPU 재분석이 원 논문(Pu 2021)의 핵심 주장(세포계통·악성 갑상선세포 특징·진행 구배)을 재현합니다."
elif n_dis >= 2:
    vlabel = "불일치 (DISAGREE)"
    vtext = "독립 재분석이 원 논문 주장과 여러 지점에서 어긋납니다 — 파라미터/주석 재검토가 필요합니다."
else:
    vlabel = "부분 일치 (PARTIAL)"
    vtext = "핵심 주장은 대체로 재현되나 일부 주장(구배/편중)에서 차이가 있습니다."

lines = [
    "BioIDE 독립 검증 결과 (헌장 제2조) — Pu 2021 PTC (저자 라벨 미배포 → 논문 주장과 대조)",
    "=" * 64,
    f"판정(Verdict): {vlabel}",
    vtext,
    "",
    f"C1 세포계통 재현: {len(recovered)}/{len(EXPECTED_LINEAGES)} (coverage {coverage:.2f}), "
    f"marker 자기일치 {self_consistency:.2f}",
]
if tds_delta is not None:
    lines.append(f"C2 악성 TDS 하락폭(정상−악성): {tds_delta:.3f} → {tds_ok}")
if tmsb_rho is not None:
    lines.append(f"C3 TMSB4X 진행 구배 Spearman ρ: {tmsb_rho:.3f} → {tmsb_ok}")
c4 = summary[summary["claim"].str.startswith("C4")]
if len(c4) and c4["verdict"].iloc[0] not in ("N/A",):
    lines.append(f"C4 악성 조직 편중(tumor−paratumor %): {c4['value'].iloc[0]} → {c4['verdict'].iloc[0]}")
lines += [
    "",
    "주의(제6조): 저자 라벨이 없어 '정답 대조'가 아니라 논문이 보고한 주장을 우리 독립 결과가",
    "정성·정량적으로 재현하는지 확인한 것입니다. 저자는 TCGA 학습 KNN 분류기로 악성세포를",
    "판정했고, 우리는 의도적으로 다른 비지도 GMM을 썼으므로 일치는 두 독립 경로의 수렴을 뜻합니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")

print("\n".join(lines))
print("\n==> [03] Validation done. Wrote validation_summary.csv / validation_verdict.txt / figures.")
print("    Next: 4. AI 해석, 5. 리포트.")
