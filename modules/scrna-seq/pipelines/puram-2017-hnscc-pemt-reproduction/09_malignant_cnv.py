#!/usr/bin/env python
"""
09_malignant_cnv.py
[malignant] Malignant / non-malignant separation

inferCNVpy로 CNV를 추론해 악성세포를 판정하고, 원 메타데이터의 악성 flag와
교차검증한다. 세포유형(클러스터/원 라벨) 간 ARI를 계산해 재현성 지표를 남긴다.

산출물 (GHBIO_RESULTS 기준):
  - adata_annotated.h5ad
  - cnv_heatmap.png
  - celltype_ari.csv

run: python 09_malignant_cnv.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scanpy as sc
import anndata as ad

try:
    import infercnvpy as cnv
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "infercnvpy import 실패 — ~/ghbio-venv 활성화 및 설치 확인 필요\n"
    )
    raise

from sklearn.metrics import adjusted_rand_score

# --------------------------------------------------------------------------
# 경로 설정 (프로젝트 경로 하드코딩 금지)
# --------------------------------------------------------------------------
RESULTS = os.environ.get(
    "GHBIO_RESULTS", os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
)
os.makedirs(RESULTS, exist_ok=True)

IN_H5AD = os.path.join(RESULTS, "adata_clustered.h5ad")
OUT_H5AD = os.path.join(RESULTS, "adata_annotated.h5ad")
OUT_HEATMAP = os.path.join(RESULTS, "cnv_heatmap.png")
OUT_ARI = os.path.join(RESULTS, "celltype_ari.csv")

# 유전자 위치 주석 소스 (GRCh38). infercnvpy가 요구하는
# chromosome / start / end 를 var에 채우기 위한 GTF 캐시.
SHARED = os.path.join(os.path.expanduser("~"), "ghbio-tutorial")
GENE_POS_CACHE = os.path.join(SHARED, "ref", "gene_pos_grch38.tsv")
# TODO: 확인 필요 — GRCh38 유전자 좌표 GTF URL (Ensembl release 110 가정)
GTF_URL = (
    "https://ftp.ensembl.org/pub/release-110/gtf/homo_sapiens/"
    "Homo_sapiens.GRCh38.110.gtf.gz"
)
GTF_CACHE = os.path.join(SHARED, "ref", "Homo_sapiens.GRCh38.110.gtf.gz")

# --------------------------------------------------------------------------
# 멱등성: 이미 완성된 산출물이 모두 있으면 종료
# --------------------------------------------------------------------------
def _all_outputs_exist():
    return all(
        os.path.exists(p) and os.path.getsize(p) > 0
        for p in (OUT_H5AD, OUT_HEATMAP, OUT_ARI)
    )


if _all_outputs_exist():
    print("[09] 산출물이 이미 존재합니다. 스킵합니다.")
    sys.exit(0)


# --------------------------------------------------------------------------
# 유전자 좌표 주석 준비
# --------------------------------------------------------------------------
def _download_with_flock(url, dest):
    import subprocess

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    lock = dest + ".lock"
    with open(lock, "w") as lf:
        import fcntl

        fcntl.flock(lf, fcntl.LOCK_EX)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest
        tmp = dest + ".part"
        cmd = [
            "curl", "-L", "-C", "-", "--retry", "5",
            "--speed-limit", "1024", "--speed-time", "60",
            "-o", tmp, url,
        ]
        print("[09] downloading:", url)
        subprocess.run(cmd, check=True)
        os.replace(tmp, dest)
    return dest


def _build_gene_pos_table():
    """GTF에서 유전자별 (chromosome, start, end) TSV를 만들어 캐시."""
    if os.path.exists(GENE_POS_CACHE) and os.path.getsize(GENE_POS_CACHE) > 0:
        return pd.read_csv(GENE_POS_CACHE, sep="\t", index_col=0)

    _download_with_flock(GTF_URL, GTF_CACHE)

    import gzip

    rows = {}
    with gzip.open(GTF_CACHE, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 9 or f[2] != "gene":
                continue
            chrom, start, end, attrs = f[0], int(f[3]), int(f[4]), f[8]
            name = None
            for a in attrs.split(";"):
                a = a.strip()
                if a.startswith("gene_name"):
                    name = a.split('"')[1]
                    break
            if name is None:
                continue
            chrom_norm = "chr" + chrom if not str(chrom).startswith("chr") else chrom
            # 표준 염색체만
            if chrom_norm.replace("chr", "") not in [str(i) for i in range(1, 23)] + [
                "X", "Y", "MT", "M",
            ]:
                continue
            # 동일 유전자명 중복 시 최초 항목 유지
            if name not in rows:
                rows[name] = (chrom_norm, start, end)

    df = pd.DataFrame.from_dict(
        rows, orient="index", columns=["chromosome", "start", "end"]
    )
    os.makedirs(os.path.dirname(GENE_POS_CACHE), exist_ok=True)
    df.to_csv(GENE_POS_CACHE, sep="\t")
    print(f"[09] gene position table 저장: {len(df)} genes")
    return df


# --------------------------------------------------------------------------
# 메인
# --------------------------------------------------------------------------
def main():
    if not os.path.exists(IN_H5AD):
        sys.stderr.write(f"입력 파일 없음: {IN_H5AD} — 08_cluster_umap.py 먼저 실행\n")
        sys.exit(1)

    print("[09] loading:", IN_H5AD)
    adata = sc.read_h5ad(IN_H5AD)

    # ---- 유전자 좌표 var에 주입 ----
    gene_pos = _build_gene_pos_table()
    gp = gene_pos.reindex(adata.var_names)
    adata.var["chromosome"] = gp["chromosome"].values
    adata.var["start"] = gp["start"].values
    adata.var["end"] = gp["end"].values
    n_mapped = adata.var["chromosome"].notna().sum()
    print(f"[09] 좌표 매핑된 유전자: {n_mapped}/{adata.n_vars}")

    # ---- 참조(정상) 세포군 결정 ----
    # 원 메타데이터의 악성 flag 컬럼 후보 탐색
    flag_col = None
    for c in ["malignant", "non-malignant", "classified as cancer cell",
              "malignant_flag", "is_malignant", "cell_type"]:
        if c in adata.obs.columns:
            flag_col = c
            break
    # TODO: 확인 필요 — 원 메타데이터의 악성 flag 컬럼명

    ref_key = None
    ref_cats = None
    immune_terms = ("T cell", "B cell", "Macrophage", "Fibroblast", "Endothelial",
                    "Myocyte", "myocyte", "Dendritic", "Mast", "myeloid",
                    "Myofibroblast", "NK")
    # 원 메타데이터의 비암성 세포유형 컬럼을 CNV reference(정상 기준)로 사용한다. 후보
    # 이름을 폭넓게 탐색하되, 실제 면역/기질 카테고리가 존재할 때만 채택해 비관련 컬럼이나
    # leiden 클러스터 번호가 잘못 선택되는 것을 막는다. (이 데이터셋의 컬럼은 noncancer_celltype)
    for ct_col in ["noncancer_celltype", "non_cancer_celltype", "non-cancer cell type",
                   "cell_type", "celltype", "cell type"]:
        if ct_col in adata.obs.columns:
            cats = [str(x) for x in pd.unique(adata.obs[ct_col].astype(str))]
            cand = [c for c in cats if any(t.lower() in c.lower() for t in immune_terms)]
            if cand:
                ref_key, ref_cats = ct_col, cand
                break

    if ref_cats:
        n_ref = int(adata.obs[ref_key].astype(str).isin(ref_cats).sum())
        print(f"[09] reference key={ref_key}, {len(ref_cats)} normal cats, {n_ref} reference cells")
    else:
        print("[09] 경고: 정상 참조 세포유형을 찾지 못함 — referenceless CNV로 진행 (임계값 신뢰도 낮음)")

    # ---- CNV 추론 ----
    cnv_kwargs = dict(window_size=100, step=10)
    if ref_key is not None and ref_cats:
        cnv_kwargs.update(reference_key=ref_key, reference_cat=ref_cats)

    cnv.tl.infercnv(adata, **cnv_kwargs)
    cnv.tl.pca(adata, n_comps=min(50, adata.n_obs - 1))
    cnv.pp.neighbors(adata)
    cnv.tl.leiden(adata)
    cnv.tl.cnv_score(adata)

    # ---- 악성 판정: cnv_score 기반 ----
    scores = adata.obs["cnv_score"].astype(float)
    # 참조군(정상)의 상위 분위수를 임계값으로 사용
    if ref_key is not None and ref_cats:
        ref_mask = adata.obs[ref_key].astype(str).isin(ref_cats)
        thr = np.nanquantile(scores[ref_mask.values], 0.95)
    else:
        thr = np.nanmedian(scores)  # TODO: 확인 필요 — 참조군 없을 때 임계값 전략
    adata.obs["cnv_malignant_pred"] = np.where(
        scores > thr, "malignant", "non-malignant"
    )
    adata.obs["cnv_malignant_pred"] = adata.obs["cnv_malignant_pred"].astype("category")
    print("[09] CNV 악성 판정 분포:\n",
          adata.obs["cnv_malignant_pred"].value_counts())

    # ---- 원 flag와 교차검증 + ARI 계산 ----
    ari_rows = []

    def _binarize_flag(series):
        # 원 flag는 데이터셋에 따라 bool / 0·1·2 코딩 / 문자열일 수 있다. 이 데이터셋의
        # `malignant`는 bool이며, 이전에는 str 변환 후 "malig" 부분일치만 검사해 모든 셀이
        # non-malignant로 붕괴되어 ARI가 0이 되는 버그가 있었다.
        if pd.api.types.is_bool_dtype(series):
            return np.where(series.to_numpy(), "malignant", "non-malignant")
        num = pd.to_numeric(series, errors="coerce")
        if num.notna().mean() > 0.8:
            uniq = set(np.unique(num.dropna().to_numpy()))
            if uniq <= {0.0, 1.0, 2.0} and 2.0 in uniq:  # GSE 코딩(1=no, 2=yes)
                return np.where(num.to_numpy() == 2.0, "malignant", "non-malignant")
            return np.where(num.to_numpy() >= 1.0, "malignant", "non-malignant")
        s = series.astype(str).str.lower()
        return np.where(s.str.contains("malig") & ~s.str.contains("non"),
                        "malignant", "non-malignant")

    if flag_col is not None:
        orig = _binarize_flag(adata.obs[flag_col])
        adata.obs["orig_malignant"] = pd.Categorical(orig)
        ari_mal = adjusted_rand_score(
            adata.obs["orig_malignant"].astype(str),
            adata.obs["cnv_malignant_pred"].astype(str),
        )
        agree = float((adata.obs["orig_malignant"].astype(str)
                       == adata.obs["cnv_malignant_pred"].astype(str)).mean())
        ari_rows.append({
            "comparison": "orig_malignant_flag_vs_cnv_pred",
            "metric": "ARI", "value": ari_mal,
        })
        ari_rows.append({
            "comparison": "orig_malignant_flag_vs_cnv_pred",
            "metric": "agreement_fraction", "value": agree,
        })
        print(f"[09] 악성 flag vs CNV 예측 ARI={ari_mal:.4f}, agree={agree:.4f}")

    # 클러스터(leiden) vs 원 세포유형 ARI
    if "leiden" in adata.obs.columns and ref_key not in (None, "leiden"):
        ari_ct = adjusted_rand_score(
            adata.obs[ref_key].astype(str),
            adata.obs["leiden"].astype(str),
        )
        ari_rows.append({
            "comparison": f"{ref_key}_vs_leiden",
            "metric": "ARI", "value": ari_ct,
        })
        print(f"[09] {ref_key} vs leiden ARI={ari_ct:.4f}")

    if not ari_rows:
        ari_rows.append({
            "comparison": "none_available",
            "metric": "ARI", "value": float("nan"),
        })

    pd.DataFrame(ari_rows).to_csv(OUT_ARI, index=False)
    print("[09] wrote:", OUT_ARI)

    # ---- CNV heatmap ----
    try:
        groupby = "cnv_leiden" if "cnv_leiden" in adata.obs.columns else None
        if groupby is None and ref_key is not None:
            groupby = ref_key
        cnv.pl.chromosome_heatmap(
            adata, groupby=groupby, show=False, save=None
        )
        fig = plt.gcf()
        fig.savefig(OUT_HEATMAP, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print("[09] wrote:", OUT_HEATMAP)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[09] chromosome_heatmap 실패, fallback 사용: {e}\n")
        fig, axarr = plt.subplots(1, 1, figsize=(8, 4))
        axarr.hist(scores.dropna(), bins=50)
        axarr.axvline(thr, color="red", linestyle="--", label=f"thr={thr:.3f}")
        axarr.set_xlabel("CNV score")
        axarr.set_ylabel("cells")
        axarr.legend()
        fig.savefig(OUT_HEATMAP, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print("[09] wrote (fallback):", OUT_HEATMAP)

    # ---- 저장 (원자적) ----
    tmp_h5ad = OUT_H5AD + ".tmp"
    adata.write_h5ad(tmp_h5ad)
    os.replace(tmp_h5ad, OUT_H5AD)
    print("[09] wrote:", OUT_H5AD)


if __name__ == "__main__":
    main()
