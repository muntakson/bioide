#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_easy_report.sh
# Turn the high-school-level report markdown (written by the AI panel's
# "🎓 고등학생버전보고서" button) into ONE branded GHBIO PDF.
#
# Unlike the QC-based 05_make_report.sh in other pipelines, this one is
# self-contained: it needs ONLY the report markdown. The scVI UMAP figure is
# folded in when present, but nothing here depends on the Scanpy QC pngs.
#
# Reads GHBIO_RESULTS (the pipeline's own project results dir). Output:
#   <results>/GHBIO_고등학생_리포트.pdf
#
# Requires: pandoc, wkhtmltopdf.
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-workspace/projects/scrna-seq-gpu-modern-reanalysis/results}"
SRC="${RESULTS}/step4_ai_report_easy.md"
OUT="${RESULTS}/GHBIO_고등학생_리포트.pdf"
DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DATE="$(date +%Y-%m-%d)"

echo "==> [05] 고등학생버전보고서 PDF 생성"

for tool in pandoc wkhtmltopdf; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' 이(가) 없습니다." >&2; exit 1; }
done
[[ -f "$SRC" ]] || { echo "ERROR: ${SRC} 없음 — 먼저 AI 패널에서 '고등학생버전보고서' 버튼을 눌러 주세요." >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Stylesheet (shares the GHBIO teal brand with the main report) -----------
cat > "$TMP/style.html" <<'CSS'
<style>
@page { size: A4; margin: 18mm 16mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK KR","Noto Color Emoji",sans-serif; font-size: 11.5pt; line-height: 1.7; color: #1f2933; margin: 0; }
h1 { font-size: 22pt; font-weight: 700; color: #0f766e; border-bottom: 3px solid #2dd4bf; padding-bottom: 8px; margin: 0 0 10px; }
h2 { font-size: 15.5pt; font-weight: 700; color: #0d9488; margin: 22px 0 8px; border-left: 5px solid #2dd4bf; padding-left: 10px; }
h3 { font-size: 13pt; font-weight: 700; color: #0f766e; margin: 16px 0 6px; }
p { margin: 8px 0; } strong { color: #0f172a; } em { color: #475569; }
code { font-family: "DejaVu Sans Mono",monospace; font-size: 9.5pt; background: #f0fdfa; color: #0f766e; border: 1px solid #99f6e4; border-radius: 4px; padding: 0.5px 4px; }
blockquote { margin: 12px 0; padding: 10px 14px; background: #f0fdfa; border-left: 4px solid #14b8a6; border-radius: 0 6px 6px 0; color: #134e4a; }
hr { border: none; border-top: 1px solid #d1e7e3; margin: 18px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 7px 9px; }
td { border: 1px solid #cfe8e3; padding: 6px 9px; vertical-align: top; }
tr:nth-child(even) td { background: #f6fffd; }
ul, ol { margin: 6px 0 6px 4px; padding-left: 20px; } li { margin: 4px 0; }
figure { margin: 14px 0 20px; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #cfe8e3; border-radius: 8px; }
figcaption { font-size: 9.5pt; color: #475569; margin-top: 6px; }
.foot { margin-top: 24px; font-size: 9.5pt; color: #64748b; border-top: 1px solid #d1e7e3; padding-top: 8px; }
</style>
CSS

# --- Assemble the report markdown (report body + optional UMAP figure) --------
REPORT_MD="$TMP/report.md"
cat "$SRC" > "$REPORT_MD"
if [[ -f "${RESULTS}/umap_scvi.png" ]]; then
  {
    printf '\n\n## 분석 지도 (UMAP)\n\n'
    printf '![세포들을 성향에 따라 배치한 지도 — scVI 잠재공간의 Leiden 클러스터](%s)\n' "${RESULTS}/umap_scvi.png"
    printf '\n*그림: 점 하나가 세포 하나이고, 가까이 모인 점일수록 하는 일(유전자 발현)이 비슷합니다.*\n'
  } >> "$REPORT_MD"
fi
printf '\n\n<div class="foot">GHBIO Co-Scientist · 현대 GPU scVI 재분석 · 작성일 %s · 이 문서는 교육용 고등학생 버전 보고서이며 임상적 증거가 아닙니다.</div>\n' "$REPORT_DATE" >> "$REPORT_MD"

# --- Render --------------------------------------------------------------------
pandoc "$REPORT_MD" -f gfm -t html5 -s \
  --metadata title="GHBIO 고등학생 리포트" \
  --include-in-header "$TMP/style.html" \
  -o "$TMP/report.html"

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/report.html" "$OUT"

echo "==> [05] 완료: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
