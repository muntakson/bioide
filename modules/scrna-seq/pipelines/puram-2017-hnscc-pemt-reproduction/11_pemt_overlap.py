#!/usr/bin/env python
"""
11_pemt_overlap.py
[pemt_overlap] Compare derived programs against the original p-EMT signature

10단계에서 도출한 발현 프로그램과 원 논문 p-EMT 시그니처의 겹침을 정량화한다.
각 프로그램에 대해 Jaccard(상위 유전자 집합 겹침)와 가중치 Spearman 상관을 구하고,
p-EMT에 가장 잘 대응하는 프로그램을 고른다.

산출물 (GHBIO_RESULTS 기준):
  - pEMT_overlap.csv   (program × Jaccard/Spearman/겹친 유전자수)
  - pEMT_overlap.json  (best program + 판정 지표)

run: python 11_pemt_overlap.py
"""
import os
import sys
import json
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

RESULTS = os.environ.get(
    "GHBIO_RESULTS", os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
)
os.makedirs(RESULTS, exist_ok=True)

IN_PROGRAMS = os.path.join(RESULTS, "programs.csv")
OUT_CSV = os.path.join(RESULTS, "pEMT_overlap.csv")
OUT_JSON = os.path.join(RESULTS, "pEMT_overlap.json")

# 원 논문(Puram et al. 2017, Cell) p-EMT 대표 시그니처.
# TODO: 확인 필요 — 논문 Table S4의 전체 p-EMT 유전자 목록으로 확장하면 정밀도가 오른다.
PEMT_SIGNATURE = [
    "PDPN", "LAMC2", "LAMB3", "LAMA3", "MMP10", "MMP1", "TGFBI",
    "ITGA5", "ITGB1", "SEMA3C", "PTHLH", "INHBA", "COL17A1", "VIM",
]

# 판정 임계값 (pipeline.json ai.system과 일치).
JACCARD_CONCORDANT = 0.30
SPEARMAN_CONCORDANT = 0.50


def main():
    if os.path.exists(OUT_CSV) and os.path.exists(OUT_JSON):
        print("[11] 출력이 이미 있습니다 — 건너뜁니다.")
        return
    if not os.path.exists(IN_PROGRAMS):
        sys.stderr.write(f"입력 파일 없음: {IN_PROGRAMS} — 10_cnmf_programs.py 먼저 실행\n")
        sys.exit(1)

    prog = pd.read_csv(IN_PROGRAMS)
    sig = set(g.upper() for g in PEMT_SIGNATURE)

    rows = []
    for name, grp in prog.groupby("program"):
        top_genes = [g.upper() for g in grp.sort_values("rank")["gene"].tolist()]
        top_set = set(top_genes)
        inter = top_set & sig
        union = top_set | sig
        jaccard = len(inter) / len(union) if union else 0.0

        # 가중치 Spearman: 시그니처 유전자에 1, 그 외 0 벡터 vs 프로그램 weight 순위.
        w = grp.set_index(grp["gene"].str.upper())["weight"]
        labels = np.array([1.0 if g in sig else 0.0 for g in w.index])
        rho = 0.0
        if labels.sum() > 0 and labels.sum() < len(labels):
            rho, _ = spearmanr(w.values, labels)
            rho = float(rho) if rho == rho else 0.0  # NaN guard

        rows.append(
            {
                "program": name,
                "n_overlap": len(inter),
                "jaccard": round(jaccard, 4),
                "spearman": round(rho, 4),
                "overlap_genes": ",".join(sorted(inter)),
            }
        )

    df = pd.DataFrame(rows).sort_values("jaccard", ascending=False).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False)

    best = df.iloc[0].to_dict()
    verdict = "일치" if (best["jaccard"] >= JACCARD_CONCORDANT and best["spearman"] >= SPEARMAN_CONCORDANT) else (
        "부분일치" if best["jaccard"] >= JACCARD_CONCORDANT or best["spearman"] >= SPEARMAN_CONCORDANT else "불일치"
    )
    summary = {
        "best_program": best["program"],
        "best_jaccard": best["jaccard"],
        "best_spearman": best["spearman"],
        "thresholds": {"jaccard": JACCARD_CONCORDANT, "spearman": SPEARMAN_CONCORDANT},
        "verdict_C2_pEMT": verdict,
        "signature_size": len(sig),
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print(f"[11] p-EMT 대응 프로그램 = {best['program']} (Jaccard={best['jaccard']}, ρ={best['spearman']}) → {verdict}")


if __name__ == "__main__":
    main()
