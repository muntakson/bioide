#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (Peng 2019 PDAC — INDEPENDENT GPU reanalysis report)
# Merge the independent-reanalysis figures + the validation result + any saved
# AI write-ups + a marker/DE appendix into ONE branded GHBIO PDF.
# 독립 재분석 그림 + 검증 결과 + (있으면) AI 해석 + 부록을 하나의 PDF로 합칩니다.
#
# Options (all optional):
#   --results DIR / --author NAME / --out FILE
# Requires: pandoc, wkhtmltopdf, venv python (~/ghbio-venv).
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
AUTHOR="${GHBIO_REPORT_AUTHOR:-GHBIO Bioinformatics}"
SAMPLE="Peng et al., Cell Research 2019 — 췌장암(PDAC) 단일세포 (57,423 cells · 24 tumor + 11 normal)"
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2;;
    --author)  AUTHOR="$2";  shift 2;;
    --out)     OUT="$2";     shift 2;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done
OUT="${OUT:-${RESULTS}/GHBIO_pdac_peng2019_report.pdf}"
PY="${HOME}/ghbio-venv/bin/python"
LOGO="$(cd "$(dirname "$0")" && pwd)/ghbio-logo.svg"

echo "==> [05] Building PDAC independent-reanalysis report PDF"
for tool in pandoc wkhtmltopdf; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found." >&2; exit 1; }
done
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
# Step-2 outputs are required; validation + AI fold in when present.
for f in umap_celltypes.png markers_by_cluster.csv celltype_composition.csv; do
  [[ -f "${RESULTS}/${f}" ]] || { echo "ERROR: missing ${RESULTS}/${f} (run step 2 first)." >&2; exit 1; }
done

REPORT_DATE="$(date +%Y-%m-%d)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

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
pre { background:#0f172a; color:#e2e8f0; padding:12px 14px; border-radius:8px; font-size:9pt; white-space:pre-wrap; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 7px 9px; }
td { border: 1px solid #cfe8e3; padding: 6px 9px; vertical-align: top; }
tr:nth-child(even) td { background: #f6fffd; }
.pagebreak { page-break-before: always; }
.cover { text-align: center; padding: 34mm 0 10mm; }
.cover .logo { width: 76px; height: 76px; }
.cover h1 { font-size: 28pt; border: none; margin: 14px 0 4px; }
.cover .sub { font-size: 13pt; color: #0d9488; font-weight: 700; }
.cover .rule { width: 120px; height: 4px; background: #2dd4bf; margin: 16px auto; border-radius: 2px; }
.cover .meta { font-size: 10.5pt; color: #64748b; margin-top: 18px; line-height: 1.9; }
.cover .fields { margin-top: 20px; font-size: 11pt; color: #334155; }
.cover .fields b { color: #0f766e; }
.badge { display: inline-block; font-size: 9pt; font-weight: 700; color: #fff; background: #0d9488; padding: 3px 10px; border-radius: 999px; }
.verdict { text-align:center; font-size: 15pt; font-weight: 800; color:#0f766e; background:#ecfeff; border:2px solid #2dd4bf; border-radius: 12px; padding: 10px; margin: 10px 0; }
figure { margin: 14px 0 20px; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #cfe8e3; border-radius: 8px; }
figcaption { font-size: 9.5pt; color: #475569; margin-top: 6px; }
td.mono { font-family: "DejaVu Sans Mono",monospace; font-size: 9pt; }
CSS

# --- optional AI write-ups ----------------------------------------------------
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

RESULTS="$RESULTS" AUTHOR="$AUTHOR" SAMPLE="$SAMPLE" REPORT_DATE="$REPORT_DATE" \
LOGO="$LOGO" TMP="$TMP" EASY_HTML="$EASY_HTML" EXP_HTML="$EXP_HTML" AI_AUTO_HTML="$AI_AUTO" "$PY" - <<'PY'
import os, base64, csv, html
R, TMP = os.environ["RESULTS"], os.environ["TMP"]
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
def exists(fn): return os.path.exists(os.path.join(R, fn))

meta = {}
if os.path.exists(os.path.join(R,"run_summary.txt")):
    for line in open(os.path.join(R,"run_summary.txt")):
        k,_,v = line.strip().partition("="); meta[k]=v
cells=meta.get("cells","57423"); ntypes=meta.get("celltypes","?"); nclust=meta.get("clusters","?")
n_mal=meta.get("malignant_ductal_cells","?"); n_norm=meta.get("normal_ductal_cells","?")

logo = b64(os.environ["LOGO"])
cover = f"""<div class="cover">
  <img class="logo" src="data:image/svg+xml;base64,{logo}">
  <h1>GHBIO AI Co-Scientist</h1>
  <div class="sub">췌장암(PDAC) <b>독립 GPU 재현</b> 리포트 — Peng 2019</div>
  <div class="rule"></div>
  <div class="meta">
    데이터셋: {html.escape(os.environ['SAMPLE'])}<br>
    <b>{cells} cells</b> · 우리 세포유형 <b>{ntypes}</b> · Leiden 클러스터 <b>{nclust}</b> · 악성/정상 도관 <b>{n_mal}</b>/<b>{n_norm}</b><br>
    방법(헌장 제1조): 저자 라벨 미사용 · 저자 log-정규화 행렬 → GPU(PyTorch) 스케일·PCA → Harmony → Leiden → marker 주석 → 비지도 GMM 악성 분리 → 저자 대비 독립 검증
  </div>
  <div class="fields">
    <b>작성자 (Author):</b> {html.escape(os.environ['AUTHOR'])}<br>
    <b>작성일 (Date):</b> {os.environ['REPORT_DATE']}
  </div>
  <div class="meta"><span class="badge">GHBIO · ghbio.co.kr</span></div>
</div>"""

# --- validation section (verdict + bars + confusion + summary table) ----------
val = ['<div class="pagebreak"></div><h1>독립 검증 결과 (헌장 제2조)</h1>',
       '<p>저자 라벨을 전혀 쓰지 않고 얻은 우리 독립 결과를, 여기서 처음으로 저자 <code>Cell_type</code>과 '
       '대조했습니다. 아래는 두 독립 분석이 얼마나 수렴하는지에 대한 정량 지표와 판정입니다.</p>']
vtxt = os.path.join(R,"validation_verdict.txt")
if os.path.exists(vtxt):
    lines = open(vtxt).read().splitlines()
    verdict = next((l.split(":",1)[1].strip() for l in lines if l.startswith("판정")), "")
    if verdict: val.append(f'<div class="verdict">판정: {html.escape(verdict)}</div>')
    val.append("<pre>"+html.escape("\n".join(lines))+"</pre>")
for fn, cap in [("validation_bars.png","일치도 지표 (ARI/NMI/정확도/F1)"),
                ("confusion_celltype.png","세포유형 혼동행렬 — 우리 유형 × 저자 라벨")]:
    if exists(fn):
        val.append(f'<figure><img src="data:image/png;base64,{b64(os.path.join(R,fn))}"><figcaption>{cap}</figcaption></figure>')
if os.path.exists(os.path.join(R,"validation_summary.csv")):
    rows=list(csv.DictReader(open(os.path.join(R,"validation_summary.csv"))))
    trs="".join(f"<tr><td>{html.escape(r['metric'])}</td><td class='mono'>{html.escape(str(r['value']))}</td>"
                f"<td><b>{html.escape(r['verdict'])}</b></td></tr>" for r in rows)
    val.append(f"<table><tr><th>지표</th><th>값</th><th>판정</th></tr>{trs}</table>")
validation = "".join(val)

# --- independent-reanalysis figures ------------------------------------------
FIGS = [
  ("umap_celltypes.png","독립 재분석 — 세포유형 UMAP (marker 기반, 저자 라벨 미사용)",
   "우리가 저자 라벨 없이 Leiden 클러스터를 canonical marker로 명명한 세포유형 UMAP입니다. 점=세포, 색=우리 세포유형."),
  ("umap_clusters.png","독립 재분석 — Leiden 클러스터",
   "GPU PCA+Harmony 임베딩에서 얻은 Leiden 클러스터. 이 클러스터들을 marker로 세포유형에 매핑했습니다."),
  ("umap_malignant.png","독립 악성/정상 도관 판정 (비지도 GMM)",
   "도관세포를 PDAC 악성 서명 점수로 비지도 GMM 분리한 결과. 저자의 type1/type2 라벨을 참고하지 않았습니다."),
  ("composition.png","종양 vs 정상 — 세포유형 조성 (독립 재분석)",
   "우리 세포유형 기준, 종양 조직과 정상 췌장의 조성 비교(%)."),
]
figs_html=['<div class="pagebreak"></div><h1>독립 GPU 재분석 그림</h1>',
           '<p>저자 라벨을 소비하지 않고 우리 코드로 재도출한 결과입니다.</p>']
for fn,cap,expl in FIGS:
    if exists(fn):
        figs_html.append(f'<figure><img src="data:image/png;base64,{b64(os.path.join(R,fn))}"><figcaption>{cap}</figcaption></figure><p><b>설명.</b> {expl}</p>')
figs="".join(figs_html)

# --- appendix: cell-type composition + malignant DE ---------------------------
comp=list(csv.DictReader(open(os.path.join(R,"celltype_composition.csv"))))
rows="".join(f"<tr><td>{html.escape(c['celltype'])}</td><td>{c.get('n_cells','')}</td>"
             f"<td>{c.get('pct_of_cells','')}</td><td class='mono'>{html.escape(c.get('top5_markers',''))}</td></tr>"
             for c in sorted(comp,key=lambda x:-int(x.get('n_cells',0) or 0)))
appendix=("<div class='pagebreak'></div><h1>부록 A. 우리 세포유형 구성</h1>"
    "<p>marker 기반 독립 주석. 전체 클러스터별 marker는 <code>markers_by_cluster.csv</code> 참조.</p>"
    "<table><tr><th>세포유형</th><th>세포 수</th><th>%</th><th>Top5 markers</th></tr>"+rows+"</table>")
if os.path.exists(os.path.join(R,"malignant_ductal.csv")):
    de=list(csv.DictReader(open(os.path.join(R,"malignant_ductal.csv"))))[:20]
    der="".join(f"<tr><td>{d.get('rank','')}</td><td class='mono'>{html.escape(d.get('gene',''))}</td>"
                f"<td>{d.get('log2fc','')}</td></tr>" for d in de)
    appendix+=("<h2>부록 B. 악성 vs 정상 도관 DE (우리 판정 기준)</h2>"
        "<table><tr><th>rank</th><th>gene</th><th>log2FC</th></tr>"+der+"</table>")

css=open(os.path.join(TMP,"ghbio.css")).read()
def _read(k):
    p=os.environ.get(k); return open(p).read() if (p and os.path.exists(p)) else ""
ai=[]
if _read("EASY_HTML"): ai.append("<div class='pagebreak'></div><h1>AI 해석 (쉬운 설명)</h1>"+_read("EASY_HTML"))
if _read("EXP_HTML"):  ai.append("<div class='pagebreak'></div><h1>AI 해석 (전문가)</h1>"+_read("EXP_HTML"))
if _read("AI_AUTO_HTML"):
    ai.append("<div class='pagebreak'></div><h1>AI 해석 (프리셋 질문별)</h1>"+_read("AI_AUTO_HTML"))
if not ai:
    ai.append("<div class='pagebreak'></div><h1>AI 해석</h1><blockquote>AI 해석이 아직 없습니다. "
              "AI 분석 단계에서 프리셋 질문을 실행하면 자동 저장되어 다음 리포트에 포함됩니다.</blockquote>")

doc=(f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><style>{css}</style></head>'
     f'<body>{cover}{validation}{figs}{"".join(ai)}{appendix}</body></html>')
open(os.path.join(TMP,"merged.html"),"w").write(doc)
print(f"   cover: {cells} cells, {ntypes} cell types, {nclust} clusters, malignant {n_mal}/normal {n_norm}")
PY

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/merged.html" "$OUT"
echo "==> [05] Done. Report: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
