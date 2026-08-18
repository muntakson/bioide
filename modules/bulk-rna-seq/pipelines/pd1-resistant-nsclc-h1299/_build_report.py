#!/usr/bin/env python3
"""
_build_report.py — assemble the H1299-P3 independent-reproduction results into a
branded GHBIO HTML (figures embedded as base64, verdict + tables from the CSVs,
plus any saved AI markdown drafts). Emitted HTML is handed to wkhtmltopdf by the
shell wrapper. Usage: _build_report.py <results_dir> <out.html> [--easy]
--easy renders the high-school AI draft (step4_ai_report_easy.md) as the body.
"""
import os, sys, base64, csv, html, re

results = sys.argv[1]
out_html = sys.argv[2]
easy = "--easy" in sys.argv[3:]
HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "ghbio-logo.svg")


def img(fname, width="100%"):
    p = os.path.join(results, fname)
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f'<img style="width:{width};max-width:100%;margin:8px 0;border:1px solid #cfe8e3;border-radius:6px" src="data:image/png;base64,{b64}"/>'


def read_text(fname):
    p = os.path.join(results, fname)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def csv_table(fname, max_rows=None, cols=None):
    p = os.path.join(results, fname)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    if cols:
        keep = [head.index(c) for c in cols if c in head]
        head = [head[i] for i in keep]
        body = [[r[i] for i in keep] for r in body]
    if max_rows:
        body = body[:max_rows]
    th = "".join(f"<th>{html.escape(c)}</th>" for c in head)
    trs = ""
    for r in body:
        tds = "".join(f"<td>{html.escape(str(c))}</td>" for c in r)
        trs += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def md(text):
    """Minimal markdown -> HTML (headings, bold, lists, tables, hr, para)."""
    if not text:
        return ""
    out, in_ul, in_tbl = [], False, False
    for ln in text.split("\n"):
        s = ln.rstrip()
        if re.match(r"^\|.*\|$", s):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_tbl:
                out.append("<table>"); in_tbl = True
            tag = "td"
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_tbl:
            out.append("</table>"); in_tbl = False
        if re.match(r"^\s*[-*]\s+", s):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            item = re.sub(r"^\s*[-*]\s+", "", s)
            out.append(f"<li>{_inline(item)}</li>")
            continue
        if in_ul:
            out.append("</ul>"); in_ul = False
        if s.startswith("### "):
            out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s.strip() in ("---", "***"):
            out.append("<hr/>")
        elif s.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{_inline(s)}</p>")
    if in_ul:
        out.append("</ul>")
    if in_tbl:
        out.append("</table>")
    return "\n".join(out)


def _inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK KR","Noto Color Emoji",sans-serif; font-size: 11pt; line-height: 1.6; color: #1f2933; margin: 0; }
h1 { font-size: 20pt; font-weight: 700; color: #0f766e; border-bottom: 3px solid #2dd4bf; padding-bottom: 8px; margin: 0 0 6px; }
h2 { font-size: 15pt; font-weight: 700; color: #0d9488; margin: 20px 0 8px; border-left: 5px solid #2dd4bf; padding-left: 10px; }
h3 { font-size: 12.5pt; font-weight: 700; color: #0f766e; margin: 14px 0 6px; }
p { margin: 6px 0; } strong { color: #0f172a; }
pre { background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 6px; padding: 10px 12px; font-family: "DejaVu Sans Mono",monospace; font-size: 8.6pt; white-space: pre-wrap; color: #134e4a; }
code { font-family: "DejaVu Sans Mono",monospace; font-size: 9.5pt; background: #f0fdfa; color: #0f766e; border-radius: 4px; padding: 0.5px 4px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 5px 7px; }
td { border: 1px solid #cfe8e3; padding: 4px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f6fffd; }
ul, ol { margin: 6px 0 6px 4px; padding-left: 20px; } li { margin: 2px 0; }
.pagebreak { page-break-before: always; }
.cover { text-align: center; padding: 40mm 0 10mm; }
.cover h1 { font-size: 27pt; border: none; margin: 12px 0 4px; }
.cover .sub { font-size: 13pt; color: #0d9488; font-weight: 700; }
.cover .rule { width: 120px; height: 4px; background: #2dd4bf; margin: 16px auto; border-radius: 2px; }
.cover .meta { font-size: 10.5pt; color: #64748b; margin-top: 18px; line-height: 1.9; }
.badge { display:inline-block; padding:4px 14px; border-radius:14px; font-weight:700; font-size:13pt; color:#fff; }
.note { background:#fffbeb; border-left:4px solid #f59e0b; padding:8px 12px; border-radius:0 6px 6px 0; color:#78350f; font-size:10pt; }
"""

logo_svg = open(LOGO, encoding="utf-8").read() if os.path.exists(LOGO) else ""
import datetime
date = datetime.date.today().isoformat()

verdict_txt = read_text("validation_verdict.txt")
mverd = re.search(r"종합 판정:\s*(\w+)", verdict_txt)
verdict = mverd.group(1) if mverd else "—"
badge_color = {"AGREE": "#2c8a4a", "PARTIAL": "#d68a2c", "DISAGREE": "#c0392b"}.get(verdict, "#64748b")

if easy:
    body = md(read_text("step4_ai_report_easy.md") or read_text("step4_ai_report.md"))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
    <div class="cover">{logo_svg}
      <h1>🔬 내성 암세포 이야기</h1>
      <div class="sub">고등학생 쉬운 리포트 · BioIDE 독립재현</div>
      <div class="rule"></div>
      <div class="meta">H1299-P3 anti-PD-1 내성 폐암 세포주 전사체<br/>{date} · GHBIO Co-Scientist</div>
    </div>
    <div class="pagebreak"></div>
    {body}
    {img('validation_bars.png','86%')}
    {img('gsea_hallmark.png','92%')}
    </body></html>"""
else:
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
    <div class="cover">{logo_svg}
      <h1>PD-1 내성 폐암 세포주 (H1299-P3)</h1>
      <div class="sub">제출 보고서 독립재현 보고서 · BioIDE</div>
      <div class="rule"></div>
      <div class="meta">
        제출: 충남대학교 박상민 교수 — H1299-P3 PD-1 내성 통합분석<br/>
        재현: GHBIO Co-Scientist (BioIDE) · count matrix 독립 재도출<br/>
        {date}
      </div>
      <div style="margin-top:22px"><span class="badge" style="background:{badge_color}">독립재현 판정: {verdict}</span></div>
    </div>
    <div class="pagebreak"></div>

    <h1>1. 독립재현 판정 요약</h1>
    <p>충남대 박상민 교수가 GHBIO에 제출한 H1299-P3 anti-PD-1 내성 통합분석 보고서를, 저자의 fold change·padj를
    <strong>사용하지 않고</strong> 제공된 count matrix에서 정규화·차등발현·GSEA를 처음부터 다시 수행해 재현성을 검증했다
    (BioIDE 헌장 §1·2).</p>
    {img('validation_bars.png','78%')}
    <pre>{html.escape(verdict_txt)}</pre>

    <div class="pagebreak"></div>
    <h1>2. 데이터·설계 & 품질관리</h1>
    <p>NIG-ΔMHC(MHC-tKO NIG) 마우스 + 인간화 PBMC 이식 H1299 종양의 mRNA-Seq(GRCh38). P0=민감(parental),
    P3=옵디보 3회 반복 선별 내성. TC=vehicle, TD=anti-PD-1. 핵심 비교는 <strong>P3C/P0C</strong>(내성 획득).</p>
    {csv_table('samples.csv')}
    {img('qc_pca.png','96%')}

    <div class="pagebreak"></div>
    <h1>3. 내성 획득 차등발현 (P3C vs P0C)</h1>
    {img('volcano_p3c_vs_p0c.png','74%')}
    <h3>상위 차등발현 유전자 (|moderated t| 순)</h3>
    {csv_table('de_p3c_vs_p0c.csv', max_rows=25, cols=['gene','logFC','t','p','q'])}

    <div class="pagebreak"></div>
    <h1>4. 핵심 타깃 재현 — 보고서 vs 독립재현</h1>
    {img('targets_vs_report.png','98%')}
    <h3>Tier1·Tier2 타깃</h3>
    {csv_table('target_reproduction.csv', cols=['gene','tier','report_logFC','our_logFC','our_q','sign_match','our_sig'])}
    {img('cat_a_heatmap.png','62%')}

    <div class="pagebreak"></div>
    <h1>5. 프로그램 방향 (Hallmark GSEA)</h1>
    {img('gsea_hallmark.png','92%')}
    {csv_table('gsea_hallmark.csv')}
    <h3>약물반응 패턴</h3>
    {img('drug_response_patterns.png','66%')}

    <div class="pagebreak"></div>
    <h1>6. 재현 범위 & 한계</h1>
    <div class="note">이 재현은 제공된 <strong>조직(tissue) count matrix</strong>만 사용한다. 보고서의 4-Category
    분류(A 종양세포-내재적 / B TME / C 세포주고유 / D 혼합)는 <strong>PacBio 세포주 전사체</strong>와의 교차검증을
    전제로 하며, 그 데이터가 없어 여기서는 재현 대상이 아니다. 또한 S100A16→ZO-2 분해, GALNT6→PD-L1 안정화,
    NOXA 단백질 등 <strong>단백질 수준(WB/flow)</strong> 주장과 progressive(P0→P1→P2→P3) 단계적 상승은
    본 데이터의 범위를 벗어난다. 반복수가 작아(대조 2/2, 약물 1/1) q-value는 보고서의 NB 모델보다 보수적이다.</div>
    {"<h2>AI 해석 (저장된 초안)</h2>" + md(read_text('step4_ai_report.md')) if read_text('step4_ai_report.md') else ""}
    </body></html>"""

with open(out_html, "w", encoding="utf-8") as f:
    f.write(doc)
print(f"==> wrote {out_html} (verdict={verdict}, easy={easy})")
