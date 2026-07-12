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
#   --sample NAME   sample label on the cover (default: "10x Genomics Human TNBC Tumor — TNBC1 (GSE148673, Gao et al. 2021)")
#   --out FILE      output PDF path           (default: <results>/GHBIO_scRNAseq_tutorial_report.pdf)
#
# Requires: pandoc, wkhtmltopdf, and the venv python (~/ghbio-venv).
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
AUTHOR="${GHBIO_REPORT_AUTHOR:-GHBIO Bioinformatics}"
SAMPLE="10x Genomics Human TNBC Tumor — TNBC1 (GSE148673, Gao et al. 2021)"
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

# --- 2b. Auto-fold the cached AI answers (results/.ai_cache/*.md) -------------
# The AI panel caches each preset answer here (with a label header), so the report includes
# them automatically — no need to manually 저장 each one. Each becomes a titled subsection.
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

# --- 3. Assemble full HTML (cover + figures + reports + appendix) + render ----
RESULTS="$RESULTS" AUTHOR="$AUTHOR" SAMPLE="$SAMPLE" REPORT_DATE="$REPORT_DATE" \
LOGO="$LOGO" TMP="$TMP" EASY_HTML="$EASY_HTML" EXP_HTML="$EXP_HTML" AI_AUTO_HTML="$AI_AUTO" "$PY" - <<'PY'
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
    파이프라인: FASTQ → STARsolo → GPU scVI → inferCNV(종양세포 분리) → AI 해석·가설
  </div>
  <div class="fields">
    <b>작성자 (Author):</b> {html.escape(os.environ['AUTHOR'])}<br>
    <b>작성일 (Date):</b> {os.environ['REPORT_DATE']}
  </div>
  <div class="meta"><span class="badge">GHBIO · ghbio.co.kr</span></div>
</div>"""

figs = f"""<div class="pagebreak"></div><h1>분석 결과 그림 (Figures)</h1>
<p>이번 분석의 핵심 결과 그림입니다. 각 그림 아래에 <b>무엇을 보여주는지</b>와 <b>읽는 법</b>을 함께 설명했습니다.</p>
<figure><img src="data:image/png;base64,{b64(os.path.join(R,'umap_clusters.png'))}">
<figcaption>Figure 1. UMAP — {cells}개 세포의 {n_clusters}개 Leiden 클러스터 (세포 타입별 그룹화)</figcaption></figure>
<p><b>Figure 1 · UMAP 읽는 법.</b> UMAP은 각 세포의 수천 개 유전자 발현을 2차원 점 하나로 압축한 지도입니다. <b>점 하나 = 세포 하나</b>, <b>색 = Leiden 클러스터</b>(발현 패턴이 비슷해 한 무리로 묶인 세포들)입니다. 서로 <b>가까운 점일수록 유전자 발현이 비슷</b>하고, 멀리 떨어진 덩어리는 대체로 <b>다른 세포 유형·상태</b>입니다. 가로·세로 축 숫자 자체에는 의미가 없으며, <b>무리가 몇 개로 나뉘고 얼마나 뚜렷이 떨어져 있는지</b>를 봅니다. 각 무리가 실제로 어떤 세포인지는 <b>부록 A의 marker 유전자</b>와 아래 AI 해석으로 판단합니다.</p>
<figure><img src="data:image/png;base64,{b64(os.path.join(R,'qc_violin.png'))}">
<figcaption>Figure 2. QC 지표 — 세포당 유전자 수 / 총 UMI / 미토콘드리아 비율(%)</figcaption></figure>
<p><b>Figure 2 · QC 지표 읽는 법.</b> 분석 전에 <b>품질이 낮은 세포를 걸러내기 위한</b> 세 가지 분포입니다(바이올린이 넓을수록 그 값을 가진 세포가 많음). <b>① 세포당 유전자 수(n_genes)</b>: 너무 적으면 빈 방울·죽은 세포, 너무 많으면 두 세포가 한 방울에 잡힌 <b>doublet</b> 의심. <b>② 총 UMI(total_counts)</b>: 세포가 잡아낸 mRNA 분자 총량으로 세포 크기·품질을 반영합니다. <b>③ 미토콘드리아 비율(pct_mito)</b>: 값이 <b>높으면 손상되었거나 죽어가는 세포</b>일 가능성이 큽니다. 이 기준으로 정상 범위를 벗어난 세포를 제거한 뒤 클러스터링했습니다.</p>"""

# Extra TNBC figures (in order); each included only if step 3 produced it. Numbers continue after Fig 2.
_extra = [
    ("tnbc_composition.png", "image/png",
     "TNBC 종양 생태계 세포 유형 구성 (draft)",
     "각 클러스터를 대표 marker로 유방암 세포 유형에 배정한 뒤 유형별 <b>세포 수·비율</b>을 나타낸 막대그래프입니다. 악성 상피세포와 함께 <b>T/NK·B/형질·골수성·섬유아세포·내피</b> 등 종양 미세환경 세포가 섞여 있습니다."),
    ("cnv_heatmap.png", "image/png",
     "추론된 대규모 CNV 히트맵 — 종양(이배수성) vs 정상(정배수성) 분리 (copyKAT 재현)",
     "유전자를 <b>염색체 위치 순서</b>로 늘어놓고 발현을 이동평균으로 부드럽게 만든 뒤, 면역/기질 <b>정상세포를 기준선</b>으로 빼서 그린 세포×유전체 지도입니다. 위쪽 정상세포는 밋밋하고, 아래쪽 <b>종양세포는 염색체 구간이 통째로 붉게(증폭)·푸르게(결손)</b> 물들어 <b>이배수성(aneuploidy)</b>을 보입니다. 이것이 copyKAT 논문의 핵심 관찰입니다."),
    ("umap_tumor_normal.png", "image/png",
     "UMAP — 추론 CNV 상태(종양 vs 정상)로 색칠",
     "같은 UMAP을 <b>CNV로 판정한 종양/정상</b>으로 색칠한 그림입니다. 붉은 점(이배수성 종양세포)이 한쪽에 모이면, 발현 기반 클러스터와 <b>유전체 이상 기반 판정이 서로 뒷받침</b>함을 뜻합니다."),
    ("tumor_subclones.png", "image/png",
     "종양 아클론(subclone) — 아클론별 평균 CNV 프로파일",
     "종양세포만 골라 <b>CNV 패턴으로 다시 나눈 아집단(subclone)</b>들의 평균 프로파일입니다. 한 종양 안에서도 서로 다른 염색체 이상을 가진 <b>여러 클론이 공존</b>할 수 있음을 보여줍니다(clonal substructure)."),
]
_fign = 3
for _fn, _mime, _cap, _expl in _extra:
    _p = os.path.join(R, _fn)
    if os.path.exists(_p):
        figs += (f'<figure><img src="data:{_mime};base64,{b64(_p)}">'
                 f'<figcaption>Figure {_fign}. {_cap}</figcaption></figure>'
                 f'<p><b>Figure {_fign} 설명.</b> {_expl}</p>')
        _fign += 1

css  = open(os.path.join(TMP,"ghbio.css")).read()
def _read(env_key):
    p = os.environ.get(env_key)
    return open(p).read() if (p and os.path.exists(p)) else ""
ai_blocks = []
if _read("EASY_HTML"):
    ai_blocks.append("<div class='pagebreak'></div><h1>AI 해석 (쉬운 설명)</h1>" + _read("EASY_HTML"))
if _read("EXP_HTML"):
    ai_blocks.append("<div class='pagebreak'></div><h1>AI 해석 (전문가)</h1>" + _read("EXP_HTML"))
if _read("AI_AUTO_HTML"):
    ai_blocks.append("<div class='pagebreak'></div><h1>AI 해석 (프리셋 질문별)</h1>"
                     "<p>AI 분석 패널에서 실행한 프리셋 질문들의 저장된 답변입니다.</p>" + _read("AI_AUTO_HTML"))
if not ai_blocks:
    ai_blocks.append("<div class='pagebreak'></div><h1>AI 해석</h1><blockquote>AI 해석이 아직 없습니다. "
                     "AI 분석 단계에서 프리셋 질문을 실행하면 자동으로 저장되어 다음 리포트에 포함됩니다.</blockquote>")
ai_html = "".join(ai_blocks)
html_doc = (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
    f'<style>{css}</style></head><body>{cover}{figs}{ai_html}{appendix}</body></html>')
open(os.path.join(TMP,"merged.html"),"w").write(html_doc)
print(f"   metadata: {cells} cells, {n_clusters} clusters, {genes} genes")
PY

wkhtmltopdf --enable-local-file-access --encoding utf-8 -s A4 -q "$TMP/merged.html" "$OUT"

echo "==> [05] Done. Report: $OUT"
command -v pdfinfo >/dev/null 2>&1 && pdfinfo "$OUT" | awk '/^Pages/{print "    pages: "$2}'
ls -lh "$OUT" | awk '{print "    size:  "$5}'
