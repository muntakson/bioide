#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh
# Merge the Step-3 figures + Step-4 reports (easy + expert) + a marker-gene
# APPENDIX into ONE branded GHBIO PDF, with author/date on the cover.
# Step 3 그림 + Step 4 보고서(쉬운/전문가) + marker 부록을 하나의 GHBIO PDF로 합칩니다.
#
# Reusable: run it after any sample's Step 3/4. Cover metadata (cells, clusters)
# is read from results/run_summary.txt (written by 03_scanpy_qc.py) when present.
#
# Options (all optional):
#   --results DIR   results folder            (default: ~/ghbio-tutorial/results)
#   --author NAME   author shown on the cover (default: $GHBIO_REPORT_AUTHOR or "GHBIO Bioinformatics")
#   --sample NAME   sample label on the cover (default: "10x Genomics 1k PBMC (v3)")
#   --out FILE      output PDF path           (default: <results>/GHBIO_scRNAseq_tutorial_report.pdf)
#
# Requires: pandoc, wkhtmltopdf, and the venv python (~/ghbio-venv).
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
AUTHOR="${GHBIO_REPORT_AUTHOR:-GHBIO Bioinformatics}"
SAMPLE="10x Genomics 1k PBMC (v3)"
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2;;
    --author)  AUTHOR="$2";  shift 2;;
    --sample)  SAMPLE="$2";  shift 2;;
    --out)     OUT="$2";     shift 2;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done
OUT="${OUT:-${RESULTS}/GHBIO_scRNAseq_tutorial_report.pdf}"
PY="${HOME}/ghbio-venv/bin/python"
LOGO="$(cd "$(dirname "$0")" && pwd)/ghbio-logo.svg"

echo "==> [05] Building merged GHBIO report PDF"

# --- 0. Dependency + input checks --------------------------------------------
for tool in pandoc wkhtmltopdf; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found." >&2; exit 1; }
done
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
# QC-derived artifacts are required (produced by 03_scanpy_qc.py).
for f in markers_by_cluster.csv celltype_draft.csv umap_clusters.png qc_violin.png; do
  [[ -f "${RESULTS}/${f}" ]] || { echo "ERROR: missing ${RESULTS}/${f} (run the QC/clustering step first)." >&2; exit 1; }
done
# The Step-4 AI write-ups are OPTIONAL: the AI panel doesn't auto-save them, so the
# report builds from the QC outputs and folds the AI sections in only when present.
# (Save an AI answer as step4_ai_report_easy.md / step4_ai_report.md to include it.)

REPORT_DATE="$(date +%Y-%m-%d)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 1. Stylesheet ------------------------------------------------------------
cat > "$TMP/ghbio.css" <<'CSS'
@page { size: A4; margin: 18mm 16mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK KR","Noto Color Emoji",sans-serif; font-size: 11pt; line-height: 1.65; color: #1f2933; margin: 0; }
h1 { font-size: 21pt; font-weight: 700; color: #0f766e; border-bottom: 3px solid #2dd4bf; padding-bottom: 8px; margin: 0 0 6px; }
h2 { font-size: 15.5pt; font-weight: 700; color: #0d9488; margin: 22px 0 8px; border-left: 5px solid #2dd4bf; padding-left: 10px; }
h3 { font-size: 13pt; font-weight: 700; color: #0f766e; margin: 16px 0 6px; }
p { margin: 7px 0; } strong { color: #0f172a; } em { color: #475569; }
code { font-family: "DejaVu Sans Mono",monospace; font-size: 9.5pt; background: #f0fdfa; color: #0f766e; border: 1px solid #99f6e4; border-radius: 4px; padding: 0.5px 4px; }
blockquote { margin: 12px 0; padding: 10px 14px; background: #f0fdfa; border-left: 4px solid #14b8a6; border-radius: 0 6px 6px 0; color: #134e4a; }
hr { border: none; border-top: 1px solid #d1e7e3; margin: 18px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 7px 9px; }
td { border: 1px solid #cfe8e3; padding: 6px 9px; vertical-align: top; }
tr:nth-child(even) td { background: #f6fffd; }
ul, ol { margin: 6px 0 6px 4px; padding-left: 20px; } li { margin: 3px 0; }
.pagebreak { page-break-before: always; }
.cover { text-align: center; padding: 38mm 0 10mm; }
.cover .logo { width: 76px; height: 76px; }
.cover h1 { font-size: 30pt; border: none; margin: 14px 0 4px; }
.cover .sub { font-size: 13pt; color: #0d9488; font-weight: 700; }
.cover .rule { width: 120px; height: 4px; background: #2dd4bf; margin: 16px auto; border-radius: 2px; }
.cover .meta { font-size: 10.5pt; color: #64748b; margin-top: 18px; line-height: 1.9; }
.cover .fields { margin-top: 22px; font-size: 11pt; color: #334155; }
.cover .fields b { color: #0f766e; }
.badge { display: inline-block; font-size: 9pt; font-weight: 700; color: #fff; background: #0d9488; padding: 3px 10px; border-radius: 999px; }
figure { margin: 14px 0 20px; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #cfe8e3; border-radius: 8px; }
figcaption { font-size: 9.5pt; color: #475569; margin-top: 6px; }
td.mono { font-family: "DejaVu Sans Mono",monospace; font-size: 9pt; }
CSS

# --- 2. Markdown -> HTML fragments (only for the AI write-ups that exist) -----
EASY_HTML=""; EXP_HTML=""
if [[ -f "${RESULTS}/step4_ai_report_easy.md" ]]; then
  pandoc "${RESULTS}/step4_ai_report_easy.md" -f gfm -t html5 -o "$TMP/easy.html"; EASY_HTML="$TMP/easy.html"
fi
if [[ -f "${RESULTS}/step4_ai_report.md" ]]; then
  pandoc "${RESULTS}/step4_ai_report.md"      -f gfm -t html5 -o "$TMP/expert.html"; EXP_HTML="$TMP/expert.html"
fi

# --- 3. Assemble full HTML (cover + figures + reports + appendix) + render ----
RESULTS="$RESULTS" AUTHOR="$AUTHOR" SAMPLE="$SAMPLE" REPORT_DATE="$REPORT_DATE" \
LOGO="$LOGO" TMP="$TMP" EASY_HTML="$EASY_HTML" EXP_HTML="$EXP_HTML" "$PY" - <<'PY'
import os, base64, csv, html, collections
R, TMP = os.environ["RESULTS"], os.environ["TMP"]
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()

# metadata (dynamic; run_summary.txt written by 03_scanpy_qc.py)
meta = {}
rs = os.path.join(R, "run_summary.txt")
if os.path.exists(rs):
    for line in open(rs):
        k,_,v = line.strip().partition(","); meta[k]=v
n_clusters = meta.get("n_clusters") or str(sum(1 for _ in open(os.path.join(R,"celltype_draft.csv")))-1)
cells = meta.get("cells_after_qc", "?")
genes = meta.get("genes_detected", "?")

# marker appendix: top-15 genes per cluster + its draft cell type
draft = {r["cluster"]: r["draft_celltype"] for r in csv.DictReader(open(os.path.join(R,"celltype_draft.csv")))}
topg = collections.defaultdict(list)
for r in csv.DictReader(open(os.path.join(R,"markers_by_cluster.csv"))):
    if int(r["rank"]) <= 15: topg[r["cluster"]].append(r["gene"])
rows = "".join(
    f"<tr><td>{html.escape(c)}</td><td>{html.escape(draft.get(c,''))}</td>"
    f"<td class='mono'>{html.escape(', '.join(topg[c]))}</td></tr>"
    for c in sorted(topg, key=lambda x:int(x)))
appendix = ("<div class='pagebreak'></div><h1>부록 A. 클러스터별 Marker 유전자</h1>"
    "<p>각 Leiden 클러스터의 상위 15개 marker 유전자(Wilcoxon)와 draft cell type. "
    "전체 통계는 <code>markers_by_cluster.csv</code> 참조.</p>"
    "<table><tr><th>Cluster</th><th>Draft cell type</th><th>Top 15 markers</th></tr>"
    f"{rows}</table>")

logo = b64(os.environ["LOGO"])
cover = f"""<div class="cover">
  <img class="logo" src="data:image/svg+xml;base64,{logo}">
  <h1>GHBIO AI Co-Scientist</h1>
  <div class="sub">scRNA-seq 분석 통합 리포트</div>
  <div class="rule"></div>
  <div class="meta">
    데이터셋: {html.escape(os.environ['SAMPLE'])}<br>
    QC 후 <b>{cells} cells</b> · <b>{n_clusters} clusters</b> · {genes} detected genes<br>
    파이프라인: FASTQ → STARsolo → Scanpy → AI 해석·가설
  </div>
  <div class="fields">
    <b>작성자 (Author):</b> {html.escape(os.environ['AUTHOR'])}<br>
    <b>작성일 (Date):</b> {os.environ['REPORT_DATE']}
  </div>
  <div class="meta"><span class="badge">GHBIO · ghbio.co.kr</span></div>
</div>"""

figs = f"""<div class="pagebreak"></div><h1>분석 결과 그림 (Figures)</h1>
<figure><img src="data:image/png;base64,{b64(os.path.join(R,'umap_clusters.png'))}">
<figcaption>Figure 1. UMAP — {cells}개 세포의 {n_clusters}개 Leiden 클러스터 (세포 타입별 그룹화)</figcaption></figure>
<figure><img src="data:image/png;base64,{b64(os.path.join(R,'qc_violin.png'))}">
<figcaption>Figure 2. QC 지표 — 세포당 유전자 수 / 총 UMI / 미토콘드리아 비율(%)</figcaption></figure>"""

css  = open(os.path.join(TMP,"ghbio.css")).read()
def _ai_section(env_key, title):
    p = os.environ.get(env_key)
    if p and os.path.exists(p):
        return open(p).read()
    return (f"<h1>{title}</h1><blockquote>AI 해석 리포트가 아직 저장되지 않았습니다. "
            "AI 분석 단계에서 답변을 <code>step4_ai_report_easy.md</code> / "
            "<code>step4_ai_report.md</code> 로 저장한 뒤 리포트를 다시 생성하면 이 섹션이 채워집니다."
            "</blockquote>")
easy = _ai_section("EASY_HTML", "AI 해석 (쉬운 설명)")
exp  = _ai_section("EXP_HTML", "AI 해석 (전문가)")
html_doc = (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
    f'<style>{css}</style></head><body>{cover}{figs}'
    f'<div class="pagebreak"></div>{easy}'
    f'<div class="pagebreak"></div>{exp}{appendix}</body></html>')
open(os.path.join(TMP,"merged.html"),"w").write(html_doc)
print(f"   metadata: {cells} cells, {n_clusters} clusters, {genes} genes")
PY

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/merged.html" "$OUT"

echo "==> [05] Done. Report: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
