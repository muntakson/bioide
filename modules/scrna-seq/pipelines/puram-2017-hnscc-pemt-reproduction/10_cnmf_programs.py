#!/usr/bin/env python
"""
10_cnmf_programs.py
[programs] Derive malignant expression programs (NMF / cNMF)

악성세포만 추려 비음수 행렬분해(NMF)로 재현성 높은 발현 프로그램을 도출한다.
원 논문은 세포주기·스트레스·저산소·상피분화·p-EMT 등의 프로그램을 보고했다.

# TODO: 확인 필요 — 이상적으로는 consensus NMF(cNMF, Kotliar 2019)로 여러 seed의
#   합의 프로그램을 구해야 한다. 여기서는 이 장비에서 항상 도는 sklearn NMF를
#   기본 구현으로 쓰고, K와 반복수는 보수적으로 잡았다. cNMF 설치 시 교체 권장.

산출물 (GHBIO_RESULTS 기준):
  - programs.csv          (program × top genes, usage 요약)
  - program_heatmap.png   (program 사용도 히트맵)

run: python 10_cnmf_programs.py
"""
import os
import sys
import json
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scanpy as sc
from sklearn.decomposition import NMF

RESULTS = os.environ.get(
    "GHBIO_RESULTS", os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
)
os.makedirs(RESULTS, exist_ok=True)

IN_H5AD = os.path.join(RESULTS, "adata_annotated.h5ad")
OUT_PROGRAMS = os.path.join(RESULTS, "programs.csv")
OUT_HEATMAP = os.path.join(RESULTS, "program_heatmap.png")

# TODO: 확인 필요 — 프로그램 개수 K. 원 논문은 대략 6~10개 프로그램을 논했다.
K_PROGRAMS = 8
TOP_GENES = 30


def _all_outputs_exist():
    return all(os.path.exists(p) for p in (OUT_PROGRAMS, OUT_HEATMAP))


def _pick_malignant(adata):
    """악성세포 subset 선택 — 09단계가 남긴 라벨을 우선 사용, 없으면 전체."""
    for col in ("malignant", "is_malignant", "malignant_call", "cnv_call"):
        if col in adata.obs.columns:
            s = adata.obs[col].astype(str).str.lower()
            mask = s.isin(["true", "1", "malignant", "yes", "tumor", "aneuploid"])
            if mask.sum() >= 50:
                return adata[mask].copy()
    sys.stderr.write("[10] 악성 라벨을 찾지 못해 전체 세포로 진행합니다 (# TODO: 확인 필요)\n")
    return adata.copy()


def main():
    if _all_outputs_exist():
        print("[10] 출력이 이미 있습니다 — 건너뜁니다.")
        return
    if not os.path.exists(IN_H5AD):
        sys.stderr.write(f"입력 파일 없음: {IN_H5AD} — 09_malignant_cnv.py 먼저 실행\n")
        sys.exit(1)

    adata = sc.read_h5ad(IN_H5AD)
    mal = _pick_malignant(adata)

    # 고변동 유전자에 한정하고 비음수 입력을 보장 (log-normalized X 사용).
    if "highly_variable" in mal.var.columns:
        mal = mal[:, mal.var["highly_variable"].values].copy()
    X = mal.X
    X = np.asarray(X.todense() if hasattr(X, "todense") else X, dtype=np.float64)
    X[X < 0] = 0.0

    model = NMF(n_components=K_PROGRAMS, init="nndsvda", random_state=0, max_iter=400)
    W = model.fit_transform(X)   # cells × programs (usage)
    H = model.components_        # programs × genes (spectra)

    genes = np.asarray(mal.var_names)
    rows = []
    for k in range(K_PROGRAMS):
        order = np.argsort(H[k])[::-1][:TOP_GENES]
        for rank, gi in enumerate(order, start=1):
            rows.append(
                {"program": f"program_{k+1}", "rank": rank, "gene": genes[gi], "weight": float(H[k, gi])}
            )
    pd.DataFrame(rows).to_csv(OUT_PROGRAMS, index=False)

    # program 사용도(평균) 히트맵.
    usage = pd.DataFrame(W, columns=[f"program_{k+1}" for k in range(K_PROGRAMS)])
    mean_usage = usage.mean(axis=0).to_frame("mean_usage")
    fig, ax = plt.subplots(figsize=(4, 0.5 * K_PROGRAMS + 1))
    ax.imshow(mean_usage.values, aspect="auto", cmap="magma")
    ax.set_yticks(range(K_PROGRAMS))
    ax.set_yticklabels(mean_usage.index)
    ax.set_xticks([])
    ax.set_title("NMF program mean usage")
    fig.tight_layout()
    fig.savefig(OUT_HEATMAP, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[10] 프로그램 {K_PROGRAMS}개 도출 완료 → {OUT_PROGRAMS}")


if __name__ == "__main__":
    main()
