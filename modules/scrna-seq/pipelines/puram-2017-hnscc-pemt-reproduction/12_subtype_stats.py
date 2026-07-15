#!/usr/bin/env python
"""
12_subtype_stats.py
[subtype_stats] Subtype mapping and metastasis-association tests

프로그램을 세포 단위로 점수화(score_genes)하고, p-EMT 점수와 림프절(LN) 전이·
종양 등급의 연관을 통계 검정한다. 환자를 TCGA 분자 아형에 매핑한다.

산출물 (GHBIO_RESULTS 기준):
  - subtype_map.csv   (환자 → TCGA 아형)
  - stats.csv         (검정 항목별 통계량·p값)
  - stats.json        (C3 전이 결론 판정 요약)

run: python 12_subtype_stats.py
"""
import os
import re
import sys
import json
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr

import scanpy as sc

RESULTS = os.environ.get(
    "GHBIO_RESULTS", os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
)
os.makedirs(RESULTS, exist_ok=True)

IN_H5AD = os.path.join(RESULTS, "adata_annotated.h5ad")
OUT_SUBTYPE = os.path.join(RESULTS, "subtype_map.csv")
OUT_STATS = os.path.join(RESULTS, "stats.csv")
OUT_JSON = os.path.join(RESULTS, "stats.json")

PEMT_SIGNATURE = [
    "PDPN", "LAMC2", "LAMB3", "LAMA3", "MMP10", "MMP1", "TGFBI",
    "ITGA5", "ITGB1", "SEMA3C", "PTHLH", "INHBA", "COL17A1", "VIM",
]

PATIENT_KEYS = ["patient", "tumor", "sample", "donor", "orig.ident"]
LN_KEYS = ["lymph_node", "LN_metastasis", "node_status", "metastasis"]
GRADE_KEYS = ["grade", "tumor_grade", "histological_grade"]

# TCGA HNSC 분자 아형(Nature 2015; Walter 2013; Chung 2004)의 대표 마커 유전자.
# 정식 방법은 TCGA centroid에 pseudobulk를 최근접 매핑하는 것이지만, centroid 파일이
# 배포되지 않으므로 아형별 시그니처 점수의 최대값으로 근사 분류한다(approximate).
SUBTYPE_SIGNATURES = {
    "Classical": ["NQO1", "AKR1C1", "AKR1C2", "AKR1C3", "GPX2", "ALDH3A1",
                  "TXN", "PPARGC1A", "ME1", "FMO5", "CLCA2"],
    "Basal": ["TP63", "KRT5", "KRT14", "KRT6A", "KRT6B", "KRT17", "COL17A1",
              "ITGB4", "LAMB3", "LAMC2", "PTHLH", "TGFA", "SERPINE1"],
    "Mesenchymal": ["VIM", "FN1", "ZEB1", "ZEB2", "TWIST1", "SNAI2", "CDH2",
                    "SPARC", "COL1A1", "COL3A1", "DCN", "FBN1", "POSTN"],
    "Atypical": ["CDKN2A", "MICB", "CD74", "HLA-DRA", "IFI27", "STAT1",
                 "GBP1", "PSMB9", "TAP1", "RARRES1"],
}


def _first_col(df, keys):
    for k in keys:
        if k in df.columns:
            return k
    return None


def _derive_patient(adata):
    """환자 ID를 obs 컬럼에서 찾고, 없으면 세포 이름 접두사(HN## / HNSCC##)에서 유도한다.

    GSE103322 행렬에는 별도 tumor 행이 없어 환자 정보가 세포 이름에만 있다.
    'HN25_...'와 'HNSCC25_...'는 같은 환자(25)의 다른 plate이므로 숫자로 정규화해 병합한다.
    combo(다중화) plate 등 숫자를 못 얻는 세포는 'NA'로 두어 환자 단위 분석에서 제외한다.
    """
    col = _first_col(adata.obs, PATIENT_KEYS)
    if col is not None and adata.obs[col].astype(str).nunique() > 1:
        return adata.obs[col].astype(str).to_numpy(), col
    ids = []
    for name in adata.obs_names:
        m = re.search(r"HN(?:SCC)?_?0*(\d+)", str(name))
        ids.append(f"HN{m.group(1)}" if m else "NA")
    return np.array(ids), "patient(from cell name)"


def main():
    if all(os.path.exists(p) for p in (OUT_SUBTYPE, OUT_STATS, OUT_JSON)):
        print("[12] 출력이 이미 있습니다 — 건너뜁니다.")
        return
    if not os.path.exists(IN_H5AD):
        sys.stderr.write(f"입력 파일 없음: {IN_H5AD} — 09_malignant_cnv.py 먼저 실행\n")
        sys.exit(1)

    adata = sc.read_h5ad(IN_H5AD)

    # score_genes / pseudobulk 은 log-정규화 발현을 기대한다. 하류 단계에서 X가 바뀌었을
    # 경우에 대비해 counts처럼 보이면(최댓값이 큼) 복사본을 정규화한다.
    xmax = float(adata.X.max())
    if xmax > 30:
        adata = adata.copy()
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)

    present = [g for g in PEMT_SIGNATURE if g in adata.var_names]
    if not present:
        sys.stderr.write("[12] p-EMT 시그니처 유전자가 행렬에 없습니다\n")
    sc.tl.score_genes(adata, present, score_name="pEMT_score")

    obs = adata.obs
    patient, pat_src = _derive_patient(adata)
    obs["patient"] = patient
    ln_col = _first_col(obs, LN_KEYS)
    grade = _first_col(obs, GRADE_KEYS)
    # 악성 세포 마스크(원 flag). p-EMT는 악성 프로그램이므로 전이 검정은 악성 세포로 제한.
    mal_col = _first_col(obs, ["malignant", "orig_malignant", "cnv_malignant_pred"])
    if mal_col == "malignant" and pd.api.types.is_bool_dtype(obs["malignant"]):
        is_mal = obs["malignant"].to_numpy()
    elif mal_col is not None:
        is_mal = obs[mal_col].astype(str).str.lower().str.contains("malig").to_numpy()
        if not is_mal.any():
            is_mal = np.ones(adata.n_obs, dtype=bool)
    else:
        is_mal = np.ones(adata.n_obs, dtype=bool)
    print(f"[12] 환자 출처={pat_src}, 환자 수={pd.Series(patient[patient!='NA']).nunique()}, "
          f"악성 세포={int(is_mal.sum())}, LN 컬럼={ln_col}")

    stats_rows = []

    # C3 (전이): p-EMT가 림프절 전이(LN) 세포에서 더 높은가?
    # LN 은 세포/시료 수준 속성이므로(환자당 원발+LN 혼재), pseudoreplication을 피하려
    # (환자 × 부위) 단위로 악성 세포 평균 p-EMT를 집계한 뒤 LN+ vs LN- 단위를 검정한다.
    verdict_c3 = "판정불가"
    MIN_CELLS = 5
    if ln_col is not None:
        ln_num = pd.to_numeric(obs[ln_col].astype(str), errors="coerce").to_numpy()
        keep = is_mal & np.isfinite(ln_num) & (patient != "NA")
        unit = pd.DataFrame({
            "patient": patient[keep],
            "site": np.where(ln_num[keep] >= 0.5, "LN", "primary"),
            "pEMT": obs["pEMT_score"].to_numpy()[keep],
        })
        agg = (unit.groupby(["patient", "site"])
                   .agg(pEMT=("pEMT", "mean"), n=("pEMT", "size"))
                   .reset_index())
        agg = agg[agg["n"] >= MIN_CELLS]
        pos = agg[agg["site"] == "LN"]["pEMT"]
        neg = agg[agg["site"] == "primary"]["pEMT"]
        if len(pos) >= 3 and len(neg) >= 3:
            u, p = mannwhitneyu(pos, neg, alternative="greater")
            stats_rows.append({"test": "pEMT_LN_vs_primary(malignant, patient×site, Mann-Whitney greater)",
                               "statistic": float(u), "pvalue": float(p),
                               "n_pos": int(len(pos)), "n_neg": int(len(neg))})
            # 유의(<0.05)=일치, 경향(0.05~0.2)=부분일치, 그 외=불일치. p가 크면 재분석이
            # 논문의 전이-연관을 재현하지 못한 것이므로 '부분일치'로 과대표기하지 않는다.
            verdict_c3 = "일치" if p < 0.05 else ("부분일치" if p < 0.2 else "불일치")
        else:
            sys.stderr.write(f"[12] LN+/primary 단위가 부족합니다 (pos={len(pos)}, neg={len(neg)})\n")
    else:
        sys.stderr.write("[12] 전이(LN) 메타데이터가 없어 C3 검정을 건너뜁니다\n")

    # 등급 상관 (있으면).
    if grade:
        g = pd.to_numeric(obs[grade], errors="coerce")
        m = g.notna()
        if m.sum() > 10:
            rho, p = spearmanr(obs.loc[m, "pEMT_score"], g[m])
            stats_rows.append({"test": "pEMT_vs_grade(Spearman)", "statistic": float(rho), "pvalue": float(p),
                               "n_pos": int(m.sum()), "n_neg": 0})

    pd.DataFrame(stats_rows or [{"test": "none", "statistic": np.nan, "pvalue": np.nan, "n_pos": 0, "n_neg": 0}]).to_csv(
        OUT_STATS, index=False
    )

    # TCGA 아형 매핑: 환자별 악성 pseudobulk를 아형 시그니처 점수로 근사 분류(nearest-centroid).
    subtype_rows = _assign_subtypes(adata, patient, is_mal)
    pd.DataFrame(subtype_rows or [{"patient": "NA", "TCGA_subtype": "unassigned",
                                   "score": np.nan, "method": "none"}]).to_csv(OUT_SUBTYPE, index=False)
    n_assigned = sum(1 for r in subtype_rows if r["TCGA_subtype"] != "unassigned")

    with open(OUT_JSON, "w") as fh:
        json.dump({"verdict_C3_metastasis": verdict_c3, "n_tests": len(stats_rows),
                   "n_patients_subtyped": n_assigned}, fh, ensure_ascii=False, indent=2)

    print(f"[12] 통계 검정 {len(stats_rows)}건 · C3(전이) 판정={verdict_c3} · 아형배정 환자={n_assigned}")


def _assign_subtypes(adata, patient, is_mal):
    """환자별 악성 pseudobulk를 TCGA HNSC 아형 시그니처로 근사 분류한다.

    각 유전자를 환자 간 z-score 표준화한 뒤 아형별 시그니처 평균 z를 점수로 하고, 최댓값
    아형을 배정한다(nearest-centroid 근사). 악성 세포가 너무 적은 환자는 'unassigned'.
    """
    pats = [p for p in pd.unique(patient) if p != "NA"]
    if not pats:
        return []
    genes = sorted({g for sig in SUBTYPE_SIGNATURES.values() for g in sig if g in adata.var_names})
    if len(genes) < 8:
        sys.stderr.write("[12] 아형 시그니처 유전자가 행렬에 거의 없어 아형 매핑을 건너뜁니다\n")
        return [{"patient": p, "TCGA_subtype": "unassigned", "score": np.nan, "method": "insufficient_genes"} for p in pats]

    sub = adata[:, genes]
    X = sub.X.toarray() if hasattr(sub.X, "toarray") else np.asarray(sub.X)
    rows, used_pats = [], []
    for p in pats:
        m = (patient == p) & is_mal
        if m.sum() >= 10:  # 안정적 pseudobulk 를 위한 최소 악성 세포 수
            rows.append(X[m].mean(axis=0))
            used_pats.append(p)
    result = [{"patient": p, "TCGA_subtype": "unassigned", "score": np.nan,
               "method": "too_few_malignant_cells"} for p in pats if p not in used_pats]
    if len(used_pats) < 2:
        return result + [{"patient": p, "TCGA_subtype": "unassigned", "score": np.nan,
                          "method": "too_few_patients"} for p in used_pats]

    pb = pd.DataFrame(np.vstack(rows), index=used_pats, columns=genes)
    z = (pb - pb.mean(axis=0)) / pb.std(axis=0).replace(0, np.nan)
    z = z.fillna(0.0)
    for p in used_pats:
        scores = {st: float(z.loc[p, [g for g in sig if g in z.columns]].mean())
                  for st, sig in SUBTYPE_SIGNATURES.items()
                  if any(g in z.columns for g in sig)}
        best = max(scores, key=scores.get)
        result.append({"patient": p, "TCGA_subtype": best, "score": round(scores[best], 4),
                       "method": "signature_nearest_centroid(approx)"})
    return result


if __name__ == "__main__":
    main()
