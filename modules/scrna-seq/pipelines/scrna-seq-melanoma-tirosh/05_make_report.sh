#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (Tirosh 2016 melanoma reproduction)
# Merge Figures 1–5 + any saved AI write-ups + a marker appendix into ONE
# branded GHBIO PDF. Builds from the figures alone; AI sections fold in if present.
# Figure 1~5 + (있으면) AI 해석 + marker 부록을 하나의 PDF로 합칩니다.
#
# Options (all optional):
#   --results DIR   results folder (default: $GHBIO_RESULTS or ~/ghbio-tutorial/results)
#   --author NAME   cover author  (default: $GHBIO_REPORT_AUTHOR or "GHBIO Bioinformatics")
#   --out FILE      output PDF     (default: <results>/GHBIO_melanoma_tirosh_report.pdf)
# Requires: pandoc, wkhtmltopdf, venv python (~/ghbio-venv).
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
AUTHOR="${GHBIO_REPORT_AUTHOR:-GHBIO Bioinformatics}"
SAMPLE="Tirosh et al., Science 2016 — Metastatic melanoma (GSE72056, 4,645 cells / 19 patients)"
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2;;
    --author)  AUTHOR="$2";  shift 2;;
    --out)     OUT="$2";     shift 2;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done
OUT="${OUT:-${RESULTS}/GHBIO_melanoma_tirosh_report.pdf}"
PY="${HOME}/ghbio-venv/bin/python"
LOGO="$(cd "$(dirname "$0")" && pwd)/ghbio-logo.svg"

echo "==> [05] Building melanoma reproduction report PDF"
for tool in pandoc wkhtmltopdf; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found." >&2; exit 1; }
done
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
# Figure 1 outputs are required; Figures 2–5 fold in when present.
for f in fig1B_infercnv_heatmap.png markers_by_cluster.csv celltype_draft.csv; do
  [[ -f "${RESULTS}/${f}" ]] || { echo "ERROR: missing ${RESULTS}/${f} (run step 2 first)." >&2; exit 1; }
done

REPORT_DATE="$(date +%Y-%m-%d)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# --- 1. Stylesheet (shared GHBIO look) ---------------------------------------
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

# --- 2. AI write-ups (optional) ----------------------------------------------
EASY_HTML=""; EXP_HTML=""
[[ -f "${RESULTS}/step4_ai_report_easy.md" ]] && { pandoc "${RESULTS}/step4_ai_report_easy.md" -f gfm -t html5 -o "$TMP/easy.html"; EASY_HTML="$TMP/easy.html"; }
[[ -f "${RESULTS}/step4_ai_report.md" ]] && { pandoc "${RESULTS}/step4_ai_report.md" -f gfm -t html5 -o "$TMP/expert.html"; EXP_HTML="$TMP/expert.html"; }
AI_AUTO=""
CACHE_DIR="${RESULTS}/.ai_cache"
if compgen -G "${CACHE_DIR}/*.md" > /dev/null 2>&1; then
  AI_AUTO="$TMP/ai_auto.html"; : > "$AI_AUTO"
  for f in "${CACHE_DIR}"/*.md; do
    label="$(sed -n 's/^<!--[[:space:]]*GHBIO_AI_LABEL:[[:space:]]*\(.*\)[[:space:]]*-->.*$/\1/p' "$f" | head -1)"
    [[ -z "$label" ]] && label="$(basename "${f%.md}")"
    grep -v 'GHBIO_AI_LABEL' "$f" | pandoc -f gfm -t html5 -o "$TMP/one.html"
    { printf '<h2>%s</h2>\n' "$label"; cat "$TMP/one.html"; } >> "$AI_AUTO"
  done
fi

# --- 3. Assemble + render -----------------------------------------------------
RESULTS="$RESULTS" AUTHOR="$AUTHOR" SAMPLE="$SAMPLE" REPORT_DATE="$REPORT_DATE" \
LOGO="$LOGO" TMP="$TMP" EASY_HTML="$EASY_HTML" EXP_HTML="$EXP_HTML" AI_AUTO_HTML="$AI_AUTO" "$PY" - <<'PY'
import os, base64, csv, html
R, TMP = os.environ["RESULTS"], os.environ["TMP"]
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
def exists(fn): return os.path.exists(os.path.join(R, fn))

meta = {}
rs = os.path.join(R, "run_summary.txt")
if os.path.exists(rs):
    for line in open(rs):
        k,_,v = line.strip().partition("="); meta[k]=v
cells = meta.get("cells","4645"); tumors = meta.get("tumors","19")
n_mal = meta.get("malignant_cells","?"); n_norm = meta.get("normal_cells","?")

logo = b64(os.environ["LOGO"])
cover = f"""<div class="cover">
  <img class="logo" src="data:image/svg+xml;base64,{logo}">
  <h1>GHBIO AI Co-Scientist</h1>
  <div class="sub">전이성 흑색종 단일세포 분석 — Tirosh 2016 재현 리포트</div>
  <div class="rule"></div>
  <div class="meta">
    데이터셋: {html.escape(os.environ['SAMPLE'])}<br>
    <b>{cells} cells</b> · <b>{tumors} tumors</b> · malignant <b>{n_mal}</b> / normal <b>{n_norm}</b><br>
    파이프라인: 공개 발현행렬(GSE72056) → inferCNV → 세포상태/미세환경 → AI 해석
  </div>
  <div class="fields">
    <b>작성자 (Author):</b> {html.escape(os.environ['AUTHOR'])}<br>
    <b>작성일 (Date):</b> {os.environ['REPORT_DATE']}
  </div>
  <div class="meta"><span class="badge">GHBIO · ghbio.co.kr</span></div>
</div>"""

# Figures 1–5, each included only if produced. (caption, explanation)
FIGS = [
  ("fig1B_infercnv_heatmap.png", "Figure 1B — inferCNV: 암세포 vs 정상세포",
   "유전자를 <b>염색체 위치 순서</b>로 늘어놓고 100-유전자 창으로 이동평균을 낸 <b>추론 복제수 변이</b> 히트맵입니다. 행=세포, 열=유전체 위치, 색=CNV log-ratio(파랑=결실, 빨강=증폭). 아래쪽 <b>malignant 세포</b>는 넓은 구간이 통째로 증폭/결실되는 비정상 패턴을 보이고, 위쪽 <b>정상 면역/기질 세포</b>는 밋밋합니다 — 발현만으로 암세포를 가려낼 수 있음을 보여줍니다."),
  ("fig1C_tsne_malignant.png", "Figure 1C — 암세포 tSNE (종양별 색)",
   "암세포만의 tSNE입니다. 점=세포, 색=<b>종양(환자)</b>. 암세포는 대체로 <b>종양별로 따로 모입니다</b>(종양 간 이질성) — 각 환자의 암은 저마다 다른 발현 정체성을 가집니다."),
  ("fig1D_tsne_nonmalignant.png", "Figure 1D — 정상세포 tSNE (세포유형별 색)",
   "정상 세포만의 tSNE입니다. 색=<b>세포유형</b>(T·B·대식세포·내피·CAF·NK). 정상 세포는 종양이 아니라 <b>세포유형별로 모입니다</b> — 여러 환자의 같은 면역세포가 서로 섞입니다."),
  ("fig2_cell_cycle.png", "Figure 2 — 암세포의 세포주기 상태",
   "암세포의 <b>G1/S vs G2/M</b> 신호 점수 산점도(빨강=분열 중, 회색=휴지)와 종양별 <b>분열 세포 비율</b> 막대입니다. 종양마다 분열 세포 비율이 크게 다릅니다."),
  ("fig3_mitf_axl.png", "Figure 3 — MITF vs AXL 상태",
   "왼쪽: 암세포별 <b>MITF 프로그램(분화)</b> vs <b>AXL 프로그램(미분화·내성)</b> 점수(음의 상관). 오른쪽: 종양별 상관계수(대개 음수). 한 종양 안에서도 두 상태가 <b>연속선</b>으로 공존해, 치료 전에도 내성 씨앗 세포가 존재함을 시사합니다."),
  ("fig4_caf_tcell.png", "Figure 4 — 미세환경: 세포유형 서명과 CAF 보체 프로그램",
   "왼쪽: 세포유형별 대표 marker의 z-score 서명. 오른쪽: <b>보체·케모카인 유전자</b>(C1S/C1R/C3/CFB/SERPING1/CXCL12/CCL19 등)가 <b>CAF</b>에서 특히 높게 발현되는 양상(청록 선=CAF 열) — CAF–T세포 상호작용 후보입니다. (원 논문 Fig 4A/C의 TCGA bulk 디컨볼루션은 외부 데이터가 필요해 단일세포 부분만 재현.)"),
  ("fig5_tcell_exhaustion.png", "Figure 5 — 종양 침윤 T세포: 세포독성 vs 소진",
   "왼쪽: T세포의 <b>CD4/CD8 구분</b>. 오른쪽: CD8 T세포의 <b>세포독성 점수 vs 소진 점수</b> 산점도(검은 선=추세). 세포독성이 오르며 소진도 함께 오르는 <b>활성화 의존적 소진</b> 경향을 보여줍니다."),
]
figs_html = ['<div class="pagebreak"></div><h1>분석 결과 그림 (Figures 1–5)</h1>',
             '<p>Tirosh et al. (Science 2016)의 핵심 그림을 저자 공개 발현행렬에서 재현했습니다. 각 그림 아래에 <b>무엇을 보여주는지·읽는 법</b>을 함께 설명했습니다.</p>']
for fn, cap, expl in FIGS:
    if exists(fn):
        figs_html.append(f'<figure><img src="data:image/png;base64,{b64(os.path.join(R,fn))}">'
                         f'<figcaption>{cap}</figcaption></figure><p><b>설명.</b> {expl}</p>')
figs = "".join(figs_html)

# Marker appendix from celltype_draft.csv (cluster,n_cells,pct_of_cells,top5_markers)
# + top-15 markers per group from markers_by_cluster.csv.
top15 = {}
for r in csv.DictReader(open(os.path.join(R,"markers_by_cluster.csv"))):
    if int(r["rank"]) <= 15:
        top15.setdefault(r["cluster"], []).append(r["gene"])
comp_rows = list(csv.DictReader(open(os.path.join(R,"celltype_draft.csv"))))
rows = "".join(
    f"<tr><td>{html.escape(c['cluster'])}</td><td>{c.get('n_cells','')}</td>"
    f"<td>{c.get('pct_of_cells','')}</td>"
    f"<td class='mono'>{html.escape(', '.join(top15.get(c['cluster'], [])))}</td></tr>"
    for c in sorted(comp_rows, key=lambda x:-int(x.get('n_cells',0) or 0)))
appendix = ("<div class='pagebreak'></div><h1>부록 A. 세포유형별 Marker 유전자</h1>"
    "<p>저자 라벨 기준 각 그룹의 세포 수·비율과 상위 15개 marker 유전자(Wilcoxon). "
    "전체는 <code>markers_by_cluster.csv</code> 참조.</p>"
    "<table><tr><th>세포유형 (그룹)</th><th>세포 수</th><th>%</th><th>Top 15 markers</th></tr>"
    f"{rows}</table>")

css = open(os.path.join(TMP,"ghbio.css")).read()
def _read(k):
    p = os.environ.get(k); return open(p).read() if (p and os.path.exists(p)) else ""
ai = []
if _read("EASY_HTML"): ai.append("<div class='pagebreak'></div><h1>AI 해석 (쉬운 설명)</h1>" + _read("EASY_HTML"))
if _read("EXP_HTML"):  ai.append("<div class='pagebreak'></div><h1>AI 해석 (전문가)</h1>" + _read("EXP_HTML"))
if _read("AI_AUTO_HTML"):
    ai.append("<div class='pagebreak'></div><h1>AI 해석 (프리셋 질문별)</h1>"
              "<p>AI 분석 패널에서 실행한 프리셋 질문들의 저장된 답변입니다.</p>" + _read("AI_AUTO_HTML"))
if not ai:
    ai.append("<div class='pagebreak'></div><h1>AI 해석</h1><blockquote>AI 해석이 아직 없습니다. "
              "AI 분석 단계에서 프리셋 질문을 실행하면 자동 저장되어 다음 리포트에 포함됩니다.</blockquote>")

html_doc = (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
    f'<style>{css}</style></head><body>{cover}{figs}{"".join(ai)}{appendix}</body></html>')
open(os.path.join(TMP,"merged.html"),"w").write(html_doc)
print(f"   metadata: {cells} cells, {tumors} tumors, malignant {n_mal}/normal {n_norm}")
PY

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/merged.html" "$OUT"
echo "==> [05] Done. Report: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
