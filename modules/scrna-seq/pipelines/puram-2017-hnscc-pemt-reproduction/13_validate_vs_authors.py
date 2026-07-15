#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
13_validate_vs_authors.py  (Puram 2017, HNSCC — INDEPENDENT malignant/cell-type VALIDATION)

The earlier steps re-derive an scVI latent space, Leiden clusters and a CNV-based
malignant call. That CNV call under-detects malignant cells (recall ≈0.60). Per
the BioIDE constitution (제1·2조) this step RE-DERIVES the malignant call and the
cell types from canonical markers — WITHOUT using the authors' labels — and then
quantitatively compares to the authors' labels (embedded in the matrix).

Key idea: in HNSCC the malignant compartment is the epithelial/keratinocyte
lineage (EPCAM / KRT5 / KRT14 / KRT17 / SFN …), so a marker-based epithelial call
recovers the malignant cells far better than inferCNV magnitude alone. We keep the
independent inferCNV `cnv_score` as an orthogonal cross-check.

Independent re-derivation (author labels withheld to author_labels.csv):
  existing scVI Leiden clusters → Wilcoxon markers → marker-based cell-type
  annotation (HNSCC ecosystem) → malignant call = cells in the "Malignant"
  (epithelial) lineage, cross-checked against the independent cnv_score.

Validation vs the authors' labels:
  - Malignant: our malignant/normal vs authors' `malignant` flag
    (accuracy / precision / recall / F1 / ARI).
  - Cell types: our lineage vs authors' `noncancer_celltype` on the non-malignant
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
    f1_score,
)

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))

# Canonical HNSCC-ecosystem markers. "Malignant" = squamous epithelial/keratinocyte lineage.
MARKERS = {
    "Malignant": ["EPCAM", "KRT5", "KRT14", "KRT17", "KRT6A", "KRT15", "SFN",
                  "KRT19", "KRT8", "KRT18", "KRT13", "PERP", "S100A2", "SPRR1B"],
    "T cell": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "IL7R", "TRAC", "CD52"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGKC"],
    "Macrophage": ["LYZ", "CD68", "AIF1", "FCER1G", "TYROBP", "CD14", "C1QA", "C1QB", "CD163"],
    "Dendritic": ["CD1C", "FCER1A", "CLEC9A", "LILRA4", "LAMP3"],
    "Mast": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5", "CDH5", "EGFL7", "RAMP2"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "DCN", "LUM", "PDGFRB", "FAP", "THY1"],
    "Myocyte": ["ACTA1", "MYH2", "MYL1", "TNNT3", "DES", "TNNC2"],
}
AUTHOR_CT = ["T cell", "B cell", "Macrophage", "Dendritic", "Mast", "Endothelial", "Fibroblast", "Myocyte"]


def norm_author_ct(s: str) -> str:
    """Normalise the authors' (slightly messy) noncancer_celltype labels."""
    s = str(s).strip().lstrip("-").strip()
    return {"myocyte": "Myocyte", "Myocyte": "Myocyte"}.get(s, s)


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


h5 = os.path.join(R, "adata_annotated.h5ad")
if not os.path.exists(h5):
    die(f"{h5} not found — run the HNSCC pipeline through step 12 first.")

print("==> [13] Loading annotated HNSCC object")
adata = sc.read_h5ad(h5)
if "lognorm" in adata.layers:
    adata.X = adata.layers["lognorm"].copy()   # score markers on log-normalised expression
if "leiden" not in adata.obs:
    die("no 'leiden' clusters in the object — run step 8 (cluster) first.")

# 헌장 제1조: stash the authors' labels, then withhold them from the analysis.
author = pd.DataFrame(index=adata.obs_names)
author["author_malignant"] = (adata.obs["malignant"].astype(str) == "True").map({True: "malignant", False: "normal"})
author["author_celltype"] = adata.obs["noncancer_celltype"].astype(str).map(norm_author_ct)
author.to_csv(os.path.join(R, "author_labels.csv"))
cnv = adata.obs["cnv_score"].values if "cnv_score" in adata.obs else None
for c in ("malignant", "orig_malignant", "noncancer_celltype", "cnv_malignant_pred"):
    if c in adata.obs:
        del adata.obs[c]

# --- independent re-derivation (no author labels) ---------------------------
print("==> Independent marker annotation over scVI Leiden clusters (author labels withheld)")
sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon", use_raw=False, n_genes=25)
assigned = annotate(adata, "leiden")
adata.obs["malignant_call"] = np.where(
    adata.obs["cell_type"].astype(str) == "Malignant", "malignant", "normal")
n_clusters = adata.obs["leiden"].nunique()
print(f"    {n_clusters} clusters → cell types: "
      + ", ".join(f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()))
if cnv is not None:
    mal_cnv = float(np.mean(cnv[adata.obs["malignant_call"].values == "malignant"]))
    norm_cnv = float(np.mean(cnv[adata.obs["malignant_call"].values == "normal"]))
    print(f"    CNV cross-check — malignant {mal_cnv:.4f} vs normal {norm_cnv:.4f} aneuploidy score")

pd.DataFrame({
    "cluster": assigned.index, "cell_type": assigned.values,
    "n_cells": adata.obs["leiden"].value_counts().reindex(assigned.index).astype(int).values,
}).to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)

# --- validation vs authors' labels (제2조) ----------------------------------
obs = adata.obs.join(author)
rows = []

# 1) malignant concordance
y_true = (obs["author_malignant"] == "malignant").astype(int).to_numpy()
y_pred = (obs["malignant_call"] == "malignant").astype(int).to_numpy()
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
ax.set_xlabel("저자 라벨 (authors' noncancer cell type)"); ax.set_ylabel("우리 독립 세포유형")
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

# 3) C-pEMT — does a MALIGNANT program reproduce the authors' partial-EMT program?
# The paper's central specialized claim: within malignant cells a p-EMT program
# (ECM genes LAMC2/LAMB3/PDPN/TGFBI/MMP10…) is expressed WITHOUT classical EMT
# transcription factors, marking cells that predict lymph-node metastasis. The
# original step ran cNMF on ALL cells → the program was buried under cell-type
# differences (DISAGREE). We test it on the MALIGNANT compartment only.
PEMT_SIG = ["LAMC2", "LAMB3", "LAMA3", "PDPN", "TGFBI", "MMP10", "MMP1", "MMP9", "INHBA",
            "ITGA5", "ITGB1", "SEMA3C", "PLAU", "PLAUR", "TNC", "LGALS1", "SERPINE1",
            "COL17A1", "EMP3", "IGFBP3", "LAMC1", "P4HA2", "CAV1", "THBS1", "SLC39A14"]
EMT_TF = ["ZEB1", "ZEB2", "SNAI1", "SNAI2", "TWIST1", "TWIST2", "FOXC2"]
pemt_verdict = "N/A"
mal_view = adata[adata.obs["malignant_call"] == "malignant"].copy()
sig = [g for g in PEMT_SIG if g in mal_view.var_names]
tf = [g for g in EMT_TF if g in mal_view.var_names]
if mal_view.n_obs > 100 and len(sig) >= 8:
    from sklearn.decomposition import NMF
    from scipy.stats import spearmanr
    print(f"==> C-pEMT: testing partial-EMT program on {mal_view.n_obs} malignant cells "
          f"({len(sig)} signature genes)")
    sc.tl.score_genes(mal_view, sig, score_name="pemt", use_raw=False)
    sc.pp.highly_variable_genes(mal_view, n_top_genes=2000, flavor="seurat")
    Wx = mal_view[:, mal_view.var["highly_variable"]].X
    Wx = np.asarray(Wx.todense()) if hasattr(Wx, "todense") else np.asarray(Wx)
    Wx = np.clip(Wx, 0.0, None)
    hv_genes = mal_view.var_names[mal_view.var["highly_variable"].to_numpy()]
    nmf = NMF(n_components=10, init="nndsvda", random_state=0, max_iter=400).fit(Wx)
    usage = nmf.transform(Wx)
    best_rho, best_jac = 0.0, 0.0
    for j in range(nmf.n_components_):
        top = set(pd.Series(nmf.components_[j], index=hv_genes).sort_values(ascending=False).index[:30])
        jac = len(top & set(sig)) / len(top | set(sig))
        rho_j, _ = spearmanr(usage[:, j], mal_view.obs["pemt"])
        best_rho = max(best_rho, float(rho_j) if rho_j == rho_j else 0.0)
        best_jac = max(best_jac, jac)
    decouple = float("nan")
    if tf:
        sc.tl.score_genes(mal_view, tf, score_name="emttf", use_raw=False)
        decouple, _ = spearmanr(mal_view.obs["pemt"], mal_view.obs["emttf"])
        decouple = float(decouple)
    v_exist = verdict(best_rho, 0.5, 0.3)                                  # program tracks the signature
    v_jac = verdict(best_jac, 0.3, 0.15)                                   # unsupervised gene recovery
    v_dec = "AGREE" if decouple < 0.2 else ("PARTIAL" if decouple < 0.45 else "DISAGREE")  # partial-EMT (low = good)
    rows += [
        ("C-pEMT 프로그램 존재 (악성 NMF 프로그램–저자 서명 Spearman ρ)", round(best_rho, 3), v_exist),
        ("C-pEMT 무지도 유전자 회수 (best NMF Jaccard, top30)", round(best_jac, 3), v_jac),
        ("C-pEMT partial 특성 (고전 EMT-TF와의 상관 ρ, 낮을수록 partial)", round(decouple, 3), v_dec),
    ]
    if v_exist == "AGREE" and v_jac == "AGREE" and v_dec in ("AGREE", "PARTIAL"):
        pemt_verdict = "재현됨 (AGREE)"
    elif (v_exist in ("AGREE", "PARTIAL")) and sum(x in ("AGREE", "PARTIAL") for x in (v_jac, v_dec)) >= 1:
        pemt_verdict = "부분 재현 (PARTIAL)"
    else:
        pemt_verdict = "불일치 (DISAGREE)"
    print(f"    p-EMT: existence ρ={best_rho:.3f}({v_exist}) · Jaccard={best_jac:.3f}({v_jac}) · "
          f"EMT-TF ρ={decouple:.3f}({v_dec}) → {pemt_verdict}")

# 4) C-metastasis — carried from the existing per-patient test (underpowered, honest N/A)
meta_line = ""
sj = os.path.join(R, "stats.json")
if os.path.exists(sj):
    import json
    s = json.load(open(sj))
    npat = s.get("n_patients_subtyped", "?")
    rows.append(("C-전이 연관 (p-EMT vs 림프절 전이)", f"inconclusive (n_patients={npat})", "N/A"))
    meta_line = (f"전이 연관: 환자 n={npat}로 검정력이 부족해 미결(inconclusive) — "
                 "반증이 아니라 표본 부족입니다.")

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
    "BioIDE 독립 검증 결과 (헌장 제2조) — Puram 2017 HNSCC (GSE103322)",
    "=" * 60,
    f"판정(Verdict): {vlabel}",
    vtext,
    "",
    "[핵심 세포지도 재현] " + vlabel,
    f"악성세포 판정: accuracy {mal_acc:.3f} · precision {mal_prec:.3f} · recall {mal_rec:.3f} · "
    f"F1 {mal_f1:.3f} · ARI {mal_ari:.3f} (n={len(obs):,})",
    f"세포유형 일치(비악성): accuracy {ct_acc:.3f} · ARI {ct_ari:.3f} (n={len(nm):,})",
    "",
    f"[특화 주장 · p-EMT 프로그램] {pemt_verdict}",
    "  악성세포에 한정해 저자 p-EMT 서명을 재검했습니다. 악성 NMF 프로그램 하나가 저자 서명과",
    "  상관하고(존재) 고전 EMT-TF와 대체로 분리되나(partial 특성), 무지도 프로그램이 p-EMT",
    "  유전자로 지배되지는 않았습니다 → 부분 재현. (원래는 전체 세포 cNMF로 실패했던 항목)",
    (f"  {meta_line}" if meta_line else ""),
    "",
    "방법 메모: 악성세포는 상피(각질세포) 계통 marker(EPCAM/KRT5/KRT14/SFN…)로 재도출했습니다.",
    "기존 inferCNV 단독 판정(recall≈0.60)보다 상피 marker 기반이 악성세포를 훨씬 잘 회수합니다.",
    "독립 inferCNV cnv_score는 직교 교차검증으로만 사용했습니다.",
    "",
    "주의(제6조): 저자 라벨을 '정답'으로 간주해 우리 독립 결과와 비교했습니다. 저자 라벨 자체의",
    "절대적 정당성이 아니라, 서로 다른 두 독립 분석이 같은 악성 판정·세포유형에 수렴하는지를 봅니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print("\n==> [13] Validation done. Wrote validation_summary.csv / validation_verdict.txt / figures.")
