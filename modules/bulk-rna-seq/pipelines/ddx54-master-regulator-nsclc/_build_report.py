#!/usr/bin/env python3
"""
_build_report.py — assemble the DDX54-KD independent-reproduction results into a
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
            out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
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
.cover h1 { font-size: 26pt; border: none; margin: 12px 0 4px; }
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
      <h1>🧬 면역회피 스위치 DDX54 이야기</h1>
      <div class="sub">고등학생 쉬운 리포트 · BioIDE 독립재현</div>
      <div class="rule"></div>
      <div class="meta">DDX54 녹다운 폐암세포 전사체 (GSE285342)<br/>{date} · GHBIO Co-Scientist</div>
    </div>
    <div class="pagebreak"></div>
    {body}
    {img('validation_bars.png','86%')}
    {img('gsea_hallmark.png','92%')}
    </body></html>"""
else:
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
    <div class="cover">{logo_svg}
      <h1>DDX54 — 면역회피 마스터조절자</h1>
      <div class="sub">논문 독립재현 보고서 · BioIDE</div>
      <div class="rule"></div>
      <div class="meta">
        논문: Gong, Lee, Han &amp; Cho, PNAS 122(14) e2412310122 (2025)<br/>
        "DDX54 downregulation enhances anti-PD1 therapy in immune-desert lung tumors"<br/>
        재현: GHBIO Co-Scientist (BioIDE) · GSE285342 raw counts 독립 재도출<br/>
        {date}
      </div>
      <div style="margin-top:22px"><span class="badge" style="background:{badge_color}">독립재현 판정: {verdict}</span></div>
    </div>
    <div class="pagebreak"></div>

    <h1>1. 독립재현 판정 요약</h1>
    <p>Gong 등(PNAS 2025)은 TCGA LUAD의 유전자조절네트워크에서 <strong>DDX54</strong>를 면역-사막(immune-desert)
    TMB-H 폐암의 <strong>면역회피 마스터조절자</strong>로 지목하고(Fig 1-2), LLC1 세포에서 <strong>Ddx54 녹다운</strong>이
    발암·면역회피 프로그램을 되돌린다는 것으로 이를 검증했다(Fig 6). 본 재현은 그 검증(Fig 6)을 공개 raw counts
    (GSE285342)에서 저자의 fold change·padj를 <strong>쓰지 않고</strong> 정규화·차등발현·GSEA를 다시 수행해 확인한다
    (BioIDE 헌장 §1·2).</p>
    {img('validation_bars.png','78%')}
    <h3>claim 판정</h3>
    {csv_table('validation_summary.csv')}
    <pre>{html.escape(verdict_txt)}</pre>

    <div class="pagebreak"></div>
    <h1>2. 데이터·설계 & 품질관리</h1>
    <p>GSE285342: LLC1 마우스 폐암세포의 <strong>WT-Ddx54 (대조, n=4)</strong> vs <strong>Ddx54 녹다운 (n=3)</strong>
    bulk RNA-seq. 핵심 대비는 <strong>KD vs WT</strong>(Ddx54 제거의 효과). 먼저 녹다운이 실제로 일어났는지
    Ddx54 자체 발현으로 확인한다.</p>
    {csv_table('samples.csv')}
    {img('ddx54_knockdown.png','70%')}
    {img('qc_pca.png','96%')}

    <div class="pagebreak"></div>
    <h1>3. 녹다운 차등발현 (KD vs WT)</h1>
    {img('volcano_kd_vs_wt.png','74%')}
    {img('immune_evasion_genes.png','80%')}
    <h3>상위 차등발현 유전자 (|moderated t| 순)</h3>
    {csv_table('de_kd_vs_wt.csv', max_rows=25, cols=['gene','logFC','t','p','q'])}

    <div class="pagebreak"></div>
    <h1>4. 프로그램 방향 (Hallmark GSEA)</h1>
    <p>논문 Fig 6의 핵심 주장은 Ddx54 녹다운이 <strong>EMT·Myc·Jak-Stat3·NF-κB</strong> 프로그램을 하향한다는 것.
    KD-vs-WT 순위 리스트에 대한 preranked GSEA로 그 방향을 재현한다(음수 NES = KD에서 하향).</p>
    {img('gsea_hallmark.png','92%')}
    {csv_table('gsea_hallmark.csv')}

    <div class="pagebreak"></div>
    <h1>5. 재현 범위 & 한계</h1>
    <div class="note">이 재현은 <strong>Fig 6(발견의 기능적 검증)</strong>만 다룬다. 논문의 <strong>발견 그 자체</strong>인
    TCGA LUAD 유전자조절네트워크 마스터조절자 추론(ARACNe→VIPER→DIGGIT, Fig 1-2)은 통제접근 TCGA 데이터와
    별도 파이프라인을 요구해 범위 밖이다. microRNA 레귤론(Fig 3, GSE289119), in-vivo 종양·생존·공간전사체·scRNA
    (Fig 4-8, GSE268555/GSE285341)도 별도 assay·데이터라 재현 대상이 아니다. 또한 β-catenin·p-Jak1/2·p-Stat3·
    p-p65·Cd47/Cd38 <strong>단백질/인산화</strong> 확인은 전사체로 검증할 수 없다(Ccnd1·Ctnnb1은 mRNA가 단백질을
    추적하지 않음). n(WT 4 / KD 3)이 작아 q-value는 보수적이다.</div>
    {"<h2>AI 해석 (저장된 초안)</h2>" + md(read_text('step4_ai_report.md')) if read_text('step4_ai_report.md') else ""}
    </body></html>"""

with open(out_html, "w", encoding="utf-8") as f:
    f.write(doc)
print(f"==> wrote {out_html} (verdict={verdict}, easy={easy})")
