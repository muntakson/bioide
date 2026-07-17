#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_validate_vs_authors.py  (Lu 2022 HCC / TLS — INDEPENDENT VALIDATION · 헌장 제2조)

Step 2 re-derived cell types, a malignant/normal hepatocyte split and a TLS module
WITHOUT ever reading the authors' `celltype` labels. THIS step is the only place
those labels are used — to check whether our independent GPU reanalysis reaches the
SAME conclusions as Lu et al. (Nat Commun 2022). We quantify agreement and issue an
honest verdict, and additionally test the paper's claims about (a) the normal→
tumour→metastasis axis and (b) intratumoral tertiary lymphoid structures (TLS).

Metrics:
  - ARI / NMI between our Leiden clusters (and our cell types) and the authors'
    `celltype` — do we partition the cells the same way?
  - Cell-type confusion matrix + label-agreement accuracy (author celltype mapped
    onto our lineage names; the six coarse types map 1:1).
  - Progression claim: from malignant_by_site.csv, is the malignant-hepatocyte
    fraction enriched in tumour/metastatic sites (Tumor/PVTT/Lymph) vs normal liver?
    (The authors' metadata has no malignant sub-label, so this is validated by
    site-enrichment self-consistency, NOT an author F1 — stated openly.)
  - TLS claim: from tls_module_by_site.csv, are B cells + CXCL13⁺ Tfh + the TLS
    chemokine milieu (CXCL13) enriched in tumour tissue vs normal liver — i.e. do
    lymphoid aggregates form intratumorally, as the paper (and TLS biology) predict?

Inputs  (from $GHBIO_RESULTS, written by step 2):
  gpu_reanalysis.h5ad, author_labels.csv, malignant_by_site.csv,
  composition_by_site.csv, tls_module_by_site.csv
Outputs (into $GHBIO_RESULTS):
  validation_summary.csv    metric · value · verdict
  validation_verdict.txt     human-readable overall verdict (folded into report/AI)
  confusion_celltype.csv/.png   our cell_type × authors' celltype
  progression_malignant.png     malignant-hepatocyte % per site (the paper's claim)
  tls_validation.png            TLS module (B / Tfh / CXCL13) tumour vs normal
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
    adjusted_rand_score, normalized_mutual_info_score, accuracy_score,
)

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))

# The authors' six coarse `celltype` values already match our lineage names 1:1.
AUTHOR_MAP = {
    "Hepatocyte": "Hepatocyte", "T/NK": "T/NK", "B": "B", "Myeloid": "Myeloid",
    "Endothelial": "Endothelial", "Fibroblast": "Fibroblast",
}
SITE_RANK = {"Normal": 0, "Tumor": 1, "PVTT": 2, "Lymph": 3}
TUMOR_SITES = {"Tumor", "PVTT", "Lymph"}
NORMAL_SITES = {"Normal"}


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
obs["author_lineage"] = obs["author_cell_type"].map(AUTHOR_MAP).fillna("other")
labelled = obs[obs["author_cell_type"].isin(AUTHOR_MAP.keys())]
print(f"    aligned {len(common):,} cells ({len(labelled):,} with a definite author label)")

rows = []  # (metric, value, verdict)

# --- 1. clustering agreement (ARI / NMI) ------------------------------------
ari_clusters = adjusted_rand_score(labelled["author_cell_type"], labelled["leiden_gpu"])
ari_types = adjusted_rand_score(labelled["author_cell_type"], labelled["cell_type"])
nmi_types = normalized_mutual_info_score(labelled["author_cell_type"], labelled["cell_type"])
rows += [
    ("ARI (our Leiden clusters vs authors' celltype)", round(ari_clusters, 3), verdict(ari_clusters, 0.5, 0.3)),
    ("ARI (our cell types vs authors' celltype)", round(ari_types, 3), verdict(ari_types, 0.5, 0.3)),
    ("NMI (our cell types vs authors' celltype)", round(nmi_types, 3), verdict(nmi_types, 0.6, 0.4)),
]

# --- 2. cell-type label agreement (after lineage mapping) -------------------
mapped = obs[obs["author_lineage"] != "other"]
celltype_acc = accuracy_score(mapped["author_lineage"], mapped["cell_type"].astype(str))
rows.append(("Cell-type label agreement (accuracy vs authors)", round(celltype_acc, 3),
             verdict(celltype_acc, 0.8, 0.6)))

# confusion matrix: our cell_type (rows) × authors' celltype (cols), column-normalised
ct_our = sorted(obs["cell_type"].astype(str).unique())
ct_auth = [t for t in AUTHOR_MAP if t in set(obs["author_cell_type"])]
cm = pd.crosstab(obs["cell_type"].astype(str), obs["author_cell_type"])
cm = cm.reindex(index=ct_our, columns=ct_auth, fill_value=0)
cm_norm = (cm / cm.sum(axis=0).replace(0, 1) * 100).round(1)
cm.to_csv(os.path.join(R, "confusion_celltype.csv"))

fig, ax = plt.subplots(figsize=(max(8, 0.8 * len(ct_auth) + 3), max(5, 0.5 * len(ct_our) + 2)))
im = ax.imshow(cm_norm.values, cmap="viridis", aspect="auto")
ax.set_xticks(range(len(ct_auth))); ax.set_xticklabels(ct_auth, rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(len(ct_our))); ax.set_yticklabels(ct_our, fontsize=8)
ax.set_xlabel("저자 라벨 (authors' celltype)"); ax.set_ylabel("우리 독립 세포유형")
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

# --- 3. the progression claim (malignant hepatocyte enriched in tumour) ------
# NOTE: the authors' metadata has NO malignant sub-label (celltype is just
# "Hepatocyte"), so we cannot compute an author malignant F1. Instead we test the
# paper's claim by site-enrichment self-consistency: our unsupervised malignant
# hepatocytes should concentrate in tumour/metastatic sites vs normal liver.
prog_rows, prog_ok = None, None
mbs = os.path.join(R, "malignant_by_site.csv")
if os.path.exists(mbs):
    prog = pd.read_csv(mbs, index_col=0)
    prog = prog.reindex([o for o in sorted(prog.index, key=lambda s: SITE_RANK.get(s, 99))])
    prog_rows = prog
    pct = {o: float(prog.loc[o, "pct_malignant"]) for o in prog.index}
    norm_vals = [pct[o] for o in NORMAL_SITES if o in pct]
    tum_vals = [pct[o] for o in TUMOR_SITES if o in pct]
    norm_mean = float(np.mean(norm_vals)) if norm_vals else float("nan")
    tum_mean = float(np.mean(tum_vals)) if tum_vals else float("nan")
    enrich = tum_mean - norm_mean
    if enrich >= 20 and tum_mean >= 2 * max(norm_mean, 1e-6):
        prog_ok = "AGREE"
    elif enrich > 5:
        prog_ok = "PARTIAL"
    else:
        prog_ok = "DISAGREE"
    detail = " · ".join(f"{o}:{pct[o]:.0f}%" for o in prog.index)
    rows.append((f"Progression: malignant hepatocyte % by site ({detail})",
                 f"tumour {tum_mean:.0f}% vs normal {norm_mean:.0f}%", prog_ok))

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    xs = list(prog.index); ys = [pct[o] for o in xs]
    colors = ["#dc2626" if o in TUMOR_SITES else "#64748b" for o in xs]
    ax.bar(xs, ys, color=colors)
    ax.set_ylabel("악성 간세포 비율 (%)")
    ax.set_title("조직 부위별 악성 간세포 비율 (빨강=종양/전이, 회색=정상) — 논문 주장 (헌장 제2조)")
    for i, v in enumerate(ys):
        ax.text(i, v + max(ys) * 0.02 + 0.3, f"{v:.0f}%", ha="center", fontsize=8)
    ax.tick_params(axis="x", rotation=10)
    fig.tight_layout(); fig.savefig(os.path.join(R, "progression_malignant.png"), bbox_inches="tight", dpi=140)
    plt.close(fig)

# --- 4. the TLS claim (intratumoral tertiary lymphoid structures) ------------
# Fridman-school TLS biology + Lu et al.: lymphoid aggregates (B cells, CXCL13⁺
# Tfh, CXCL13 chemokine) form INSIDE tumour tissue. We test whether the B-cell
# fraction, the CXCL13⁺ Tfh fraction and mean CXCL13 are higher in tumour tissue
# than in normal liver.
tls_ok = None
tls_df = None
tms = os.path.join(R, "tls_module_by_site.csv")
if os.path.exists(tms):
    tls_df = pd.read_csv(tms, index_col=0)
    if {"Tumor", "Normal"} <= set(tls_df.index):
        b_t, b_n = float(tls_df.loc["Tumor", "pct_B"]), float(tls_df.loc["Normal", "pct_B"])
        cx_t = float(tls_df.loc["Tumor", "mean_CXCL13"]); cx_n = float(tls_df.loc["Normal", "mean_CXCL13"])
        tfh_t = float(tls_df.loc["Tumor", "pct_Tfh_of_TNK"]); tfh_n = float(tls_df.loc["Normal", "pct_Tfh_of_TNK"])
        # count how many of the three TLS signals are higher in tumour than normal
        signals = [(b_t > b_n + 1), (cx_t > cx_n), (tfh_t > tfh_n)]
        n_up = sum(signals)
        tls_ok = "AGREE" if n_up == 3 else ("PARTIAL" if n_up == 2 else "DISAGREE")
        rows.append((f"TLS intratumoral enrichment "
                     f"(B% T{b_t:.1f}/N{b_n:.1f} · CXCL13 T{cx_t:.2f}/N{cx_n:.2f} · Tfh% T{tfh_t:.0f}/N{tfh_n:.0f})",
                     f"{n_up}/3 TLS signals ↑ in tumour", tls_ok))

        fig, ax = plt.subplots(figsize=(7.5, 4.5))
        sites = [s for s in ["Normal", "Tumor", "PVTT", "Lymph"] if s in tls_df.index]
        x = np.arange(len(sites)); w = 0.38
        ax.bar(x - w / 2, [float(tls_df.loc[s, "pct_B"]) for s in sites], w, label="B세포 %", color="#2563eb")
        ax.bar(x + w / 2, [float(tls_df.loc[s, "pct_Tfh_of_TNK"]) for s in sites], w,
               label="CXCL13+ Tfh % (T/NK 중)", color="#dc2626")
        ax.set_xticks(x); ax.set_xticklabels(sites)
        ax.set_ylabel("비율 (%)"); ax.set_title("TLS 세포 부위별 분포 — 종양 내 림프구조 (헌장 제2조)")
        ax.legend(fontsize=8, loc="upper left")
        ax2 = ax.twinx()
        ax2.plot(x, [float(tls_df.loc[s, "mean_CXCL13"]) for s in sites], "o-",
                 color="#0d9488", label="평균 CXCL13")
        ax2.set_ylabel("평균 CXCL13", color="#0d9488")
        fig.tight_layout(); fig.savefig(os.path.join(R, "tls_validation.png"), bbox_inches="tight", dpi=140)
        plt.close(fig)

summary = pd.DataFrame(rows, columns=["metric", "value", "verdict"])
summary.to_csv(os.path.join(R, "validation_summary.csv"), index=False)

# --- 5. summary bar figure ---------------------------------------------------
barvals = [("ARI clusters", ari_clusters), ("ARI cell types", ari_types),
           ("NMI cell types", nmi_types), ("cell-type acc", celltype_acc)]
fig, ax = plt.subplots(figsize=(8, 4.5))
names = [b[0] for b in barvals]; vals = [b[1] for b in barvals]
colors = ["#0d9488" if v >= 0.7 else "#f59e0b" if v >= 0.45 else "#dc2626" for v in vals]
ax.bar(names, vals, color=colors)
ax.axhline(0.7, color="#334155", ls="--", lw=0.8)
ax.set_ylim(0, 1); ax.set_ylabel("agreement (0–1)")
ax.set_title("독립 재분석 vs 원 논문 저자 라벨 — 일치도 (헌장 제2조)")
ax.tick_params(axis="x", rotation=15)
for i, v in enumerate(vals):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(R, "validation_bars.png"), bbox_inches="tight", dpi=140)
plt.close(fig)

# --- 6. overall verdict ------------------------------------------------------
def _overall():
    ct = verdict(celltype_acc, 0.8, 0.6)
    pr = prog_ok or "N/A"
    tl = tls_ok or "N/A"
    if ct == "AGREE" and pr in ("AGREE", "PARTIAL", "N/A") and tl in ("AGREE", "PARTIAL", "N/A"):
        return "재현됨 (AGREE)", "우리 독립 GPU 재분석이 원 논문의 세포유형 구성, 정상→종양→전이 축의 악성세포 편중, 그리고 종양 내 TLS(B세포·CXCL13⁺ Tfh) 형성 주장을 재현합니다."
    if "DISAGREE" in (ct, pr, tl):
        return "불일치 (DISAGREE)", "독립 재분석이 원 논문 결론과 상당히 어긋납니다 — 추가 검토가 필요합니다."
    return "부분 일치 (PARTIAL)", "핵심 결론은 대체로 재현되나 일부 세포유형/경계 또는 진행·TLS 추세에서 차이가 있습니다."

vlabel, vtext = _overall()
lines = [
    "BioIDE 독립 검증 결과 (헌장 제2조) — Lu 2022 간세포암 HCC / TLS (GSE149614)",
    "=" * 66,
    f"판정(Verdict): {vlabel}",
    vtext,
    "",
    f"세포유형 ARI(클러스터): {ari_clusters:.3f} | ARI(유형): {ari_types:.3f} | NMI: {nmi_types:.3f}",
    f"세포유형 라벨 일치 정확도: {celltype_acc:.3f}  (저자 6개 coarse 유형 대비)",
]
if prog_rows is not None:
    pct = {o: float(prog_rows.loc[o, "pct_malignant"]) for o in prog_rows.index}
    lines.append("조직 부위별 악성 간세포 비율: " + " · ".join(f"{o} {pct[o]:.0f}%" for o in prog_rows.index)
                 + f"  → 진행 축 주장 판정: {prog_ok}")
if tls_df is not None and {"Tumor", "Normal"} <= set(tls_df.index):
    lines.append(
        f"종양 내 TLS(B세포·CXCL13⁺ Tfh·CXCL13): "
        f"B% 종양 {tls_df.loc['Tumor','pct_B']:.1f} vs 정상 {tls_df.loc['Normal','pct_B']:.1f} · "
        f"CXCL13 종양 {tls_df.loc['Tumor','mean_CXCL13']:.2f} vs 정상 {tls_df.loc['Normal','mean_CXCL13']:.2f}"
        f"  → TLS 주장 판정: {tls_ok}")
lines += [
    "",
    "주의(제6조): 이 검증은 저자의 라벨을 '정답'으로 간주해 우리 독립 결과와 비교한 것입니다.",
    "저자 라벨 자체의 절대적 정당성을 증명하는 것이 아니라, 서로 다른 두 독립 분석이 같은",
    "세포 분할·판정에 수렴하는지를 봅니다. 저자 메타데이터에는 악성/정상 간세포 구분 라벨이",
    "없어, 악성 판정은 저자 F1이 아니라 '종양 부위 편중'의 자기일관성으로 검증했습니다.",
    "정상 간세포와 HCC 악성세포는 간 유전자를 공유해 경계가 본질적으로 애매합니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")

print("\n".join(lines))
print("\n==> [03] Validation done. Wrote validation_summary.csv / validation_verdict.txt / figures.")
print("    Next: 4. AI 해석, 5. 리포트.")
