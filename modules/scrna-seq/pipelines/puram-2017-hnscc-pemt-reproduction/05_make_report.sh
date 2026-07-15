#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (Puram 2017 HNSCC p-EMT 재현)
# Assemble the full reproduction report PDF from whatever the pipeline produced:
#   - all result figures (*.png) present in the results dir
#   - the reproduction verdict tables (pEMT_overlap / stats / celltype_ari)
#   - the expert AI write-up (step4_ai_report.md) when the AI panel saved one
#
# Output: <results>/final_report.pdf   (matches pipeline.json steps[report].produces)
# Requires: pandoc, wkhtmltopdf.  QC/figures are optional — the report degrades gracefully.
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-workspace/projects/puram-2017-hnscc-pemt-reproduction/results}"
OUT="${RESULTS}/final_report.pdf"
REPORT_DATE="$(date +%Y-%m-%d)"

echo "==> [05] 재현 리포트 PDF 생성"
for tool in pandoc wkhtmltopdf; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' 이(가) 없습니다." >&2; exit 1; }
done
mkdir -p "$RESULTS"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/style.html" <<'CSS'
<style>
@page { size: A4; margin: 18mm 16mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK KR","Noto Color Emoji",sans-serif; font-size: 11pt; line-height: 1.6; color: #1f2933; margin: 0; }
h1 { font-size: 21pt; color: #0f766e; border-bottom: 3px solid #2dd4bf; padding-bottom: 8px; }
h2 { font-size: 15pt; color: #0d9488; margin: 20px 0 8px; border-left: 5px solid #2dd4bf; padding-left: 10px; }
h3 { font-size: 12.5pt; color: #0f766e; }
code { font-family: "DejaVu Sans Mono",monospace; font-size: 9pt; background: #f0fdfa; color: #0f766e; padding: 0.5px 4px; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 6px 8px; }
td { border: 1px solid #cfe8e3; padding: 5px 8px; }
tr:nth-child(even) td { background: #f6fffd; }
figure { margin: 12px 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #cfe8e3; border-radius: 8px; }
figcaption { font-size: 9pt; color: #475569; }
.foot { margin-top: 22px; font-size: 9pt; color: #64748b; border-top: 1px solid #d1e7e3; padding-top: 8px; }
</style>
CSS

MD="$TMP/report.md"
{
  printf '# Puram 2017 두경부암(HNSCC) p-EMT 프로그램 — 독립 재현 리포트\n\n'
  printf '원 논문의 워크플로를 Python·GPU·AI 스택(Scanpy·scVI·NMF·inferCNVpy)으로 독립 재현하고, '
  printf '네 개 핵심 결론(세포유형 분리·p-EMT 프로그램·전이 연관·TCGA 아형)의 재현 여부를 정량 대조합니다.\n\n'

  # --- CSV → Markdown table helper (header + up to 20 rows) ---
  emit_csv () {  # $1 file, $2 heading
    [[ -f "$1" ]] || return 0
    printf '\n## %s\n\n' "$2"
    awk -F, 'NR==1{n=NF; printf "|"; for(i=1;i<=n;i++)printf " %s |",$i; printf "\n|"; for(i=1;i<=n;i++)printf " --- |"; printf "\n"; next}
             NR<=21{printf "|"; for(i=1;i<=n;i++)printf " %s |",$i; printf "\n"}' "$1"
  }

  emit_csv "${RESULTS}/celltype_ari.csv" "세포유형 지정 일치율 (ARI) — 결론 C1"
  if [[ -f "${RESULTS}/pEMT_overlap.json" ]]; then
    printf '\n## p-EMT 프로그램 판정 — 결론 C2\n\n```\n'; cat "${RESULTS}/pEMT_overlap.json"; printf '\n```\n'
  fi
  emit_csv "${RESULTS}/pEMT_overlap.csv" "프로그램별 p-EMT overlap (Jaccard·Spearman)"
  emit_csv "${RESULTS}/stats.csv" "p-EMT 점수 vs 전이·등급 통계 — 결론 C3"
  if [[ -f "${RESULTS}/stats.json" ]]; then
    printf '\n```\n'; cat "${RESULTS}/stats.json"; printf '\n```\n'
  fi
  emit_csv "${RESULTS}/subtype_map.csv" "TCGA 분자 아형 매핑 — 결론 C4"

  # --- Figures (any present) ---
  shopt -s nullglob
  figs=("${RESULTS}"/*.png)
  if (( ${#figs[@]} )); then
    printf '\n## 그림\n\n'
    for f in "${figs[@]}"; do
      printf '![%s](%s)\n\n' "$(basename "$f")" "$f"
    done
  fi

  # --- Expert AI verdict, if the AI panel saved one ---
  if [[ -f "${RESULTS}/step4_ai_report.md" ]]; then
    printf '\n## AI 해석 및 결론 판정\n\n'
    cat "${RESULTS}/step4_ai_report.md"
  fi

  printf '\n\n<div class="foot">GHBIO Co-Scientist · Puram 2017 HNSCC p-EMT 독립 재현 · 작성일 %s · 교육용 재현이며 임상적 증거가 아닙니다.</div>\n' "$REPORT_DATE"
} > "$MD"

pandoc "$MD" -f gfm -t html5 -s \
  --metadata title="HNSCC p-EMT 재현 리포트" \
  --include-in-header "$TMP/style.html" \
  -o "$TMP/report.html"

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/report.html" "$OUT"

echo "==> [05] 완료: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
