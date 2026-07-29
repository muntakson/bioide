#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (Tahoe-100M drug-response — independent GPU reanalysis report)
# Assemble the reanalysis figures + validation into ONE branded PDF via matplotlib
# PdfPages (dependency-light — no pandoc/wkhtmltopdf for a draft).
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
OUT="${OUT:-${RESULTS}/GHBIO_tahoe100m_drug_report.pdf}"
PY="${HOME}/ghbio-venv/bin/python"

echo "==> [05] Building Tahoe-100M drug-response report PDF → ${OUT}"
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
[[ -f "${RESULTS}/umap_condition.png" ]] || { echo "ERROR: missing figures (run step 2 first)." >&2; exit 1; }

GHBIO_RESULTS="${RESULTS}" GHBIO_REPORT_OUT="${OUT}" "$PY" - <<'PY'
import os, json
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
def img(n): return os.path.join(R, n)
def csv(n):
    p = os.path.join(R, n); return pd.read_csv(p) if os.path.exists(p) else None

FIGS = [
    ("umap_condition.png", "Figure 1. UMAP — 약물 vs DMSO 대조"),
    ("umap_cellline.png",  "Figure 2. UMAP — 세포주(cell line)"),
    ("umap_clusters.png",  "Figure 3. UMAP — Leiden 클러스터"),
    ("volcano.png",        "Figure 4. 컨센서스 약물 서명 (volcano)"),
    ("de_top_heatmap.png", "Figure 5. 세포주별 top DE 유전자 히트맵"),
    ("reproducibility.png","Figure 6. 세포주 간 재현성 (logFC 상관)"),
    ("target_response.png","Figure 7. 알려진 표적 유전자 반응"),
    ("validation_bars.png","Figure 8. 독립 검증 지표"),
]
with PdfPages(OUT) as pdf:
    fig = plt.figure(figsize=(8.3, 11.7))
    fig.text(0.5, 0.72, "GHBIO · BioIDE", ha="center", fontsize=26, color="#0f766e", weight="bold")
    fig.text(0.5, 0.66, "Tahoe-100M 약물 반응 독립 GPU 재현 리포트", ha="center", fontsize=17, color="#0d9488")
    fig.text(0.5, 0.60, "Vevo × Arc Virtual Cell Atlas — 암 세포주 약물 섭동 아틀라스\n한 약물의 전사체 반응을 여러 세포주에서 재도출·재현성 검증 (헌장 제1조)",
             ha="center", fontsize=11, color="#334155")
    pj = os.path.join(R, "provenance.json")
    if os.path.exists(pj):
        p = json.load(open(pj))
        fig.text(0.5, 0.50, f"cells={p.get('n_cells')} · cell lines={len(p.get('cell_lines',[]))} · "
                            f"mean logFC corr={p.get('mean_cross_line_logfc_corr'):.2f}",
                 ha="center", fontsize=11, color="#475569")
    vv = os.path.join(R, "validation_verdict.txt")
    if os.path.exists(vv):
        fig.text(0.5, 0.44, open(vv).read().strip().split("\n")[0], ha="center", fontsize=13, color="#b91c1c", weight="bold")
    plt.axis("off"); pdf.savefig(fig); plt.close()

    for name, title in FIGS:
        if not os.path.exists(img(name)): continue
        fig = plt.figure(figsize=(8.3, 11.7))
        fig.text(0.08, 0.95, title, fontsize=14, color="#0d9488", weight="bold")
        ax = fig.add_axes([0.06, 0.08, 0.88, 0.82]); ax.axis("off")
        ax.imshow(plt.imread(img(name))); pdf.savefig(fig); plt.close()

    vs = csv("validation_summary.csv")
    if vs is not None:
        fig = plt.figure(figsize=(8.3, 11.7))
        fig.text(0.08, 0.95, "검증 지표 요약 (validation_summary.csv)", fontsize=14, color="#0d9488", weight="bold")
        ax = fig.add_axes([0.08, 0.1, 0.84, 0.8]); ax.axis("off")
        ax.table(cellText=vs.values.tolist(), colLabels=list(vs.columns), loc="upper left")
        pdf.savefig(fig); plt.close()
print("==> wrote", OUT)
PY

echo "==> [05] Done: ${OUT}"
