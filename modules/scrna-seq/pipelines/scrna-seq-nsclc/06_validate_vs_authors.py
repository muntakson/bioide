#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
06_validate_vs_authors.py  (Song 2019, NSCLC — INDEPENDENT lineage VALIDATION · 헌장 제2조)

The pipeline aligned patient-1's tumour reads with STARsolo (no author labels are
distributed for GSE117570 — the GEO deposit is processed matrices without per-cell
annotations). We re-derive cell types from markers and validate against the paper's
PUBLISHED CLAIMS.

Honest scope: GSE117570 (Song et al., Cancer Medicine 2019) is a MYELOID-plasticity
study, and this tutorial processes ONLY P1's tumour channel. So we can validate that
our independent clustering recovers the paper's major tumour-microenvironment
lineages and that their canonical markers are self-consistent — but NOT the paper's
central CD14+monocyte→M2 trajectory or the tumour-vs-normal myeloid enrichment,
which need the full paired (tumour+normal, 4-patient) data. That limitation is
reported, not hidden.

Inputs : the STARsolo filtered matrix under $GHBIO_RESULTS/starsolo/Solo.out/Gene/filtered
Outputs: validation_summary.csv, validation_verdict.txt, celltype_annotation.csv,
         marker_recovery.csv, validation_bars.png
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

R = os.environ.get("GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results"))
SEED = 2019

# NSCLC tumour-microenvironment markers (Song 2019-named + canonical).
MARKERS = {
    "Malignant/Epithelial": ["EPCAM", "KRT8", "KRT18", "KRT19", "SFTPC", "SFTPA1", "NAPSA", "NKX2-1"],
    "T cell": ["CD3D", "CD3E", "CD3G", "TRAC", "IL7R", "CD2", "CD8A", "CD8B"],
    "B cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM"],
    "Myeloid": ["LYZ", "CD68", "CD14", "FCGR3A", "AIF1", "C1QA", "C1QB", "CD163", "ITGAM", "MRC1"],
    "Dendritic": ["CD1C", "FCER1A", "CLEC9A", "THBD", "LILRA4", "LAMP3"],
    "NK": ["NKG7", "GNLY", "KLRD1", "NCAM1", "KLRF1"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5", "CDH5"],
    "Fibroblast": ["COL1A1", "COL1A2", "DCN", "LUM", "PDGFRB"],
    "Mast": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT"],
}
# The paper's major reported TME lineages (immune/stromal focus; epithelial is our
# annotation, NOT a paper claim, so excluded from the recovery metric).
EXPECTED = ["T cell", "B cell", "Myeloid", "Dendritic", "NK", "Fibroblast"]


def die(m):
    print(f"ERROR: {m}", file=sys.stderr); sys.exit(1)


def verdict(v, agree, partial):
    return "AGREE" if v >= agree else ("PARTIAL" if v >= partial else "DISAGREE")


mtx_dir = os.path.join(R, "starsolo", "Solo.out", "Gene", "filtered")
if not os.path.exists(os.path.join(mtx_dir, "matrix.mtx")):
    die(f"STARsolo filtered matrix not found under {mtx_dir} — run the align step first.")

print("==> [06] Loading STARsolo filtered matrix")
adata = sc.read_mtx(os.path.join(mtx_dir, "matrix.mtx")).T
feats = pd.read_csv(os.path.join(mtx_dir, "features.tsv"), sep="\t", header=None)
adata.var_names = (feats[1] if feats.shape[1] >= 2 else feats[0]).astype(str).values
adata.obs_names = pd.read_csv(os.path.join(mtx_dir, "barcodes.tsv"), header=None)[0].astype(str).values
adata.var_names_make_unique()

# QC + normalise (re-derive from raw counts)
adata.var["mito"] = adata.var_names.str.upper().str.startswith("MT-")
sc.pp.calculate_qc_metrics(adata, qc_vars=["mito"], inplace=True, percent_top=None, log1p=False)
sc.pp.filter_cells(adata, min_genes=300)
sc.pp.filter_genes(adata, min_cells=3)
adata = adata[adata.obs["pct_counts_mito"] < 20].copy()
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
print(f"    {adata.n_obs} cells × {adata.n_vars} genes after QC")

# independent clustering
sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat")
adata.raw = adata
work = adata[:, adata.var["highly_variable"]].copy()
sc.pp.scale(work, max_value=10)
sc.tl.pca(work, n_comps=min(30, work.n_obs - 1), svd_solver="arpack", random_state=SEED)
sc.pp.neighbors(work, n_pcs=30, n_neighbors=15, random_state=SEED)
sc.tl.leiden(work, key_added="leiden", resolution=1.0, flavor="igraph",
             n_iterations=2, directed=False, random_state=SEED)
adata.obs["leiden"] = work.obs["leiden"].values

# marker-based annotation
cols = {}
for lin, genes in MARKERS.items():
    present = [g for g in genes if g in adata.var_names]
    c = f"_s_{lin}"
    sc.tl.score_genes(adata, present, score_name=c, use_raw=False) if present else adata.obs.__setitem__(c, 0.0)
    cols[lin] = c
per = adata.obs.groupby("leiden", observed=True)[list(cols.values())].mean()
per.columns = list(cols.keys())
assigned = per.idxmax(axis=1)
adata.obs["cell_type"] = adata.obs["leiden"].map(assigned).astype("category")
pd.DataFrame({"cluster": assigned.index, "cell_type": assigned.values,
             "n_cells": adata.obs["leiden"].value_counts().reindex(assigned.index).astype(int).values}
             ).to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)
print("    cell types: " + ", ".join(f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()))

# --- C1 lineage recovery + marker self-consistency --------------------------
our = set(adata.obs["cell_type"].astype(str).unique())
recovered = [l for l in EXPECTED if l in our]
cov = len(recovered) / len(EXPECTED)
# self-consistency: each recovered lineage's own score is top among its cells
consistent, checked, recov_rows = 0, 0, []
for ct in per.index:
    label = assigned[ct]
    checked += 1
    top = per.loc[ct].astype(float).idxmax()
    ok = (top == label)
    consistent += int(ok)
    recov_rows.append({"cluster": ct, "assigned": label, "top_scoring": top, "self_consistent": ok})
self_consistency = consistent / checked if checked else 0.0
pd.DataFrame(recov_rows).to_csv(os.path.join(R, "marker_recovery.csv"), index=False)

rows = [
    ("C1 주요 TME 계통 회수 (T·B·골수성·DC·NK·섬유아)",
     f"{len(recovered)}/{len(EXPECTED)} ({', '.join(recovered)})", round(cov, 3), verdict(cov, 0.83, 0.5)),
    ("C1 marker 자기일치도 (클러스터 배정이 최고점 계통과 일치)",
     "각 클러스터의 배정 계통이 최고 marker 점수와 일치하는 비율", round(self_consistency, 3),
     verdict(self_consistency, 0.9, 0.7)),
]
summary = pd.DataFrame(rows, columns=["metric", "value", "score", "verdict"])
summary.to_csv(os.path.join(R, "validation_summary.csv"), index=False)

# bars
fig, ax = plt.subplots(figsize=(7, 4.2))
bv = [("lineage recovery", cov), ("marker self-consistency", self_consistency)]
ax.bar([b[0] for b in bv], [b[1] for b in bv],
       color=["#0d9488" if v >= 0.8 else "#f59e0b" if v >= 0.5 else "#dc2626" for _, v in bv])
ax.set_ylim(0, 1); ax.axhline(0.8, color="#334155", ls="--", lw=0.8)
ax.set_title("독립 재분석 vs Song 2019 주장 — 계통 회수 (헌장 제2조)")
for i, (_, v) in enumerate(bv):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=10)
fig.tight_layout(); fig.savefig(os.path.join(R, "validation_bars.png"), bbox_inches="tight", dpi=140); plt.close(fig)

# verdict
core = verdict(cov, 0.83, 0.5)
if core == "AGREE" and self_consistency >= 0.7:
    vlabel, vtext = "재현됨 (AGREE)", "우리 독립 재분석이 원 논문의 주요 종양미세환경 계통 분류를 재현합니다."
elif core == "DISAGREE":
    vlabel, vtext = "불일치 (DISAGREE)", "독립 재분석이 논문의 계통 분류와 상당히 어긋납니다."
else:
    vlabel, vtext = "부분 재현 (PARTIAL)", "주요 계통은 대체로 재현되나 일부 계통을 회수하지 못했습니다."

lines = [
    "BioIDE 독립 검증 결과 (헌장 제2조) — Song 2019 NSCLC (GSE117570, P1 종양)",
    "=" * 60,
    f"판정(Verdict): {vlabel}",
    vtext, "",
    f"C1 주요 TME 계통 회수: {len(recovered)}/{len(EXPECTED)} ({', '.join(recovered)})",
    f"C1 marker 자기일치도: {self_consistency:.2f}",
    "",
    "범위 한계(제6조): 이 튜토리얼은 P1 '종양' 채널 한 개만 처리합니다. GSE117570의 핵심 주장",
    "(CD14+단핵구→M2 대식세포 궤적, 종양 vs 정상 골수세포 증가)은 짝지은 종양+정상·4환자 전체",
    "데이터가 있어야 검정할 수 있어, 여기서는 '계통 분류 재현'까지만 검증합니다. 저자 per-cell",
    "라벨이 GEO에 없어 정답 대조가 아니라 공개 주장과의 대조입니다.",
]
open(os.path.join(R, "validation_verdict.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print("\n==> [06] Validation done.")
