#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (scBaseCount HCC — independent GPU reanalysis report)
# Assemble the reanalysis figures + validation summary into ONE branded PDF using
# matplotlib's PdfPages (dependency-light — no pandoc/wkhtmltopdf needed for a
# draft). If this pipeline is promoted, swap in the figure-rich pandoc report used
# by hcc-tls-lu2022 / melanoma-tirosh for parity.
#
# Options:  --results DIR / --out FILE
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2;;
    --out)     OUT="$2";     shift 2;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done
OUT="${OUT:-${RESULTS}/GHBIO_scbasecount_hcc_report.pdf}"
PY="${HOME}/ghbio-venv/bin/python"

echo "==> [05] Building scBaseCount HCC report PDF → ${OUT}"
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
[[ -f "${RESULTS}/umap_celltypes.png" ]] || { echo "ERROR: missing figures (run step 2 first)." >&2; exit 1; }

GHBIO_RESULTS="${RESULTS}" GHBIO_REPORT_OUT="${OUT}" "$PY" - <<'PY'
import os, glob
import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager
for _f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
    if any(_f == f.name for f in matplotlib.font_manager.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f; break
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

R = os.environ["GHBIO_RESULTS"]; OUT = os.environ["GHBIO_REPORT_OUT"]
def img(name): return os.path.join(R, name)
def csv(name):
    p = os.path.join(R, name)
    return pd.read_csv(p) if os.path.exists(p) else None

FIGS = [
    ("umap_clusters.png", "Figure 1. Leiden 클러스터"),
    ("umap_celltypes.png", "Figure 2. 세포유형 (마커 기반, 저자 라벨 미사용)"),
    ("umap_malignant.png", "Figure 3. 악성 간세포 판정 (비지도 GMM)"),
    ("umap_sample.png", "Figure 4. 시료(SRX) — 교차연구 통합 점검"),
    ("umap_tls.png", "Figure 5. TLS 니치 점수"),
    ("composition.png", "Figure 6. 세포유형 조성 (통합 HCC 아틀라스)"),
    ("tls_by_tissue.png", "Figure 7. 조직별 TLS 구성 요소"),
    ("confusion_celltype.png", "Figure 8. scBaseCount 라벨 대비 혼동행렬"),
    ("tls_validation.png", "Figure 9. TLS 종양 vs 정상 검증"),
    ("validation_bars.png", "Figure 10. 독립 검증 지표"),
]

with PdfPages(OUT) as pdf:
    # cover
    fig = plt.figure(figsize=(8.3, 11.7)); fig.text(0.5, 0.72, "GHBIO · BioIDE", ha="center", fontsize=26, color="#0f766e", weight="bold")
    fig.text(0.5, 0.66, "scBaseCount HCC 독립 GPU 재현 리포트", ha="center", fontsize=18, color="#0d9488")
    fig.text(0.5, 0.60, "Arc Virtual Cell Atlas (SRAgent·STARsolo 균일 재정량) 기반\n간세포암 다연구 통합 재분석 · 헌장 제1조 독립 재도출",
             ha="center", fontsize=12, color="#334155")
    prov = csv("provenance.json") is None
    pj = os.path.join(R, "provenance.json")
    if os.path.exists(pj):
        import json; p = json.load(open(pj))
        fig.text(0.5, 0.50, f"cells={p.get('n_cells')} · genes={p.get('n_genes')} · samples={p.get('n_samples')} · {p.get('integration')}",
                 ha="center", fontsize=11, color="#475569")
    vv = os.path.join(R, "validation_verdict.txt")
    if os.path.exists(vv):
        fig.text(0.5, 0.44, open(vv).read().strip().split("\n")[0], ha="center", fontsize=13, color="#b91c1c", weight="bold")
    plt.axis("off"); pdf.savefig(fig); plt.close()

    # figure pages
    for name, title in FIGS:
        if not os.path.exists(img(name)): continue
        fig = plt.figure(figsize=(8.3, 11.7))
        fig.text(0.08, 0.95, title, fontsize=14, color="#0d9488", weight="bold")
        ax = fig.add_axes([0.06, 0.08, 0.88, 0.82]); ax.axis("off")
        ax.imshow(plt.imread(img(name)))
        pdf.savefig(fig); plt.close()

    # validation table page
    vs = csv("validation_summary.csv")
    if vs is not None:
        fig = plt.figure(figsize=(8.3, 11.7)); fig.text(0.08, 0.95, "검증 지표 요약 (validation_summary.csv)", fontsize=14, color="#0d9488", weight="bold")
        ax = fig.add_axes([0.08, 0.1, 0.84, 0.8]); ax.axis("off")
        tbl = vs.values.tolist()
        ax.table(cellText=tbl, colLabels=list(vs.columns), loc="upper left")
        pdf.savefig(fig); plt.close()

print("==> wrote", OUT)
PY

echo "==> [05] Done: ${OUT}"
