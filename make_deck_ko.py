#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate 'IDE for Omics Researcher' pptx deck."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---- palette ----
NAVY   = RGBColor(0x0F, 0x2A, 0x43)
NAVY2  = RGBColor(0x16, 0x3B, 0x5C)
TEAL   = RGBColor(0x0F, 0xB5, 0xA9)
GREEN  = RGBColor(0x36, 0xB3, 0x7E)
AMBER  = RGBColor(0xF2, 0xA6, 0x2E)
CORAL  = RGBColor(0xE8, 0x6A, 0x5C)
LIGHT  = RGBColor(0xF4, 0xF7, 0xFA)
CARD   = RGBColor(0xFF, 0xFF, 0xFF)
INK    = RGBColor(0x23, 0x33, 0x42)
GRAY   = RGBColor(0x5A, 0x6B, 0x7B)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LINE   = RGBColor(0xD8, 0xE0, 0xE8)

FONT = "Malgun Gothic"

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]

def slide():
    return prs.slides.add_slide(BLANK)

def _set_font(run, size, color, bold, italic=False, font=FONT):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {})
            rPr.append(e)
        e.set("typeface", font)

def rect(s, x, y, w, h, fill, line=None, line_w=None, shape=MSO_SHAPE.RECTANGLE):
    sp = s.shapes.add_shape(shape, x, y, w, h)
    sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w or 1)
    sp.shadow.inherit = False
    return sp

def txt(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        space_after=6, line_spacing=1.05, wrap=True):
    """runs: list of paragraphs; each paragraph is list of (text,size,color,bold,italic)."""
    tb = s.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0
    tf.margin_top = 0; tf.margin_bottom = 0
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        p.space_before = Pt(0)
        p.line_spacing = line_spacing
        for (t, sz, col, bold, *rest) in para:
            it = rest[0] if rest else False
            r = p.add_run(); r.text = t
            _set_font(r, sz, col, bold, it)
    return tb

def bg(s, color=LIGHT):
    rect(s, 0, 0, SW, SH, color)

def kicker_bar(s):
    rect(s, 0, 0, SW, Inches(0.14), TEAL)

def header(s, num, title, kicker=None):
    """standard content-slide header."""
    kicker_bar(s)
    # slide number chip
    rect(s, Inches(0.55), Inches(0.5), Inches(0.62), Inches(0.62), NAVY,
         shape=MSO_SHAPE.OVAL)
    txt(s, Inches(0.55), Inches(0.5), Inches(0.62), Inches(0.62),
        [[(f"{num:02d}", 20, WHITE, True)]], align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE)
    paras = []
    if kicker:
        paras.append([(kicker, 12, TEAL, True)])
    paras.append([(title, 26, NAVY, True)])
    txt(s, Inches(1.4), Inches(0.42), Inches(11.3), Inches(0.95), paras,
        space_after=1, line_spacing=1.0, anchor=MSO_ANCHOR.MIDDLE)
    # underline
    rect(s, Inches(1.42), Inches(1.32), Inches(2.2), Pt(3), TEAL)

def footer(s):
    txt(s, Inches(0.55), Inches(7.02), Inches(9), Inches(0.35),
        [[("IDE for Omics Researcher  ·  오믹스 연구자를 위한 AI IDE", 9, GRAY, False)]])
    txt(s, Inches(10.3), Inches(7.02), Inches(2.5), Inches(0.35),
        [[("GHBio Co-Scientist", 9, GRAY, True)]], align=PP_ALIGN.RIGHT)

def bullets(s, x, y, w, items, size=15, gap=10, color=INK, marker="—", mcolor=TEAL):
    tb = s.shapes.add_textbox(x, y, w, Inches(4.5))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left=0; tf.margin_top=0; tf.margin_right=0
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.space_after = Pt(gap); p.line_spacing = 1.08
        if isinstance(it, tuple):
            lead, rest = it
        else:
            lead, rest = None, it
        rm = p.add_run(); rm.text = f"{marker}  "
        _set_font(rm, size, mcolor, True)
        if lead:
            r1 = p.add_run(); r1.text = lead + "  "
            _set_font(r1, size, NAVY, True)
        r2 = p.add_run(); r2.text = rest
        _set_font(r2, size, color, False)
    return tb

def flow(s, steps, y=Inches(2.7), h=Inches(1.7), colors=None):
    """Horizontal box→arrow→box chain. steps: list of (line1,line2)."""
    n = len(steps)
    margin = Inches(0.7)
    arrow_w = Inches(0.55)
    total = SW - 2*margin
    box_w = (total - (n-1)*arrow_w) / n
    x = margin
    palette = colors or [NAVY, NAVY2, TEAL, GREEN, AMBER, CORAL, NAVY, TEAL]
    for i,(l1,l2) in enumerate(steps):
        col = palette[i % len(palette)]
        rect(s, x, y, box_w, h, col, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        paras = [[(l1, 15, WHITE, True)]]
        if l2:
            paras.append([(l2, 11, RGBColor(0xDF,0xEC,0xF0), False)])
        txt(s, x+Inches(0.12), y, box_w-Inches(0.24), h, paras,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, space_after=3,
            line_spacing=1.0)
        if i < n-1:
            ax = x + box_w + Emu(int(arrow_w*0.08))
            ar = rect(s, x+box_w, y+h/2-Inches(0.18), arrow_w, Inches(0.36),
                      AMBER, shape=MSO_SHAPE.RIGHT_ARROW)
        x += box_w + arrow_w

def note(s, text, y=Inches(4.9), color=NAVY):
    box = rect(s, Inches(0.7), y, SW-Inches(1.4), Inches(1.0), CARD,
               line=LINE, line_w=1, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    rect(s, Inches(0.7), y, Inches(0.12), Inches(1.0), color)
    txt(s, Inches(1.0), y, SW-Inches(2.0), Inches(1.0),
        [[("▸  ", 14, color, True),(text, 14, INK, False)]],
        anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.1)

def cards(s, items, y=Inches(2.0), h=Inches(4.2), cols=None, top_colors=None):
    """Grid of cards. items: list of (title, body)."""
    n = len(items); cols = cols or n
    rows = (n + cols - 1)//cols
    margin = Inches(0.6); gap = Inches(0.35)
    cw = (SW - 2*margin - (cols-1)*gap)/cols
    ch = (h - (rows-1)*gap)/rows
    pal = top_colors or [TEAL, GREEN, AMBER, CORAL, NAVY2, TEAL, GREEN, AMBER, CORAL]
    for idx,(t,b) in enumerate(items):
        r = idx//cols; c = idx%cols
        x = margin + c*(cw+gap); yy = y + r*(ch+gap)
        rect(s, x, yy, cw, ch, CARD, line=LINE, line_w=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        rect(s, x, yy, cw, Inches(0.12), pal[idx%len(pal)])
        txt(s, x+Inches(0.22), yy+Inches(0.28), cw-Inches(0.44), ch-Inches(0.4),
            [[(t, 15, NAVY, True)], [(b, 12, GRAY, False)]],
            space_after=6, line_spacing=1.08)

# =========================================================
# SLIDE 1 — What is an IDE?
# =========================================================
s = slide(); bg(s); kicker_bar(s)
header(s, 1, "What is an IDE in software development?", "1990s–2000s  ·  The desktop era")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.0), [
    ("IDE = Integrated Development Environment.", "Editor + compiler + debugger + build tools in one program."),
    ("It turns raw code into a workbench —", "write, run, debug, and ship from a single window."),
    ("The classic:  Microsoft Visual Studio", "the reference IDE that defined the category."),
], size=15, gap=14)
# right column flow
txt(s, Inches(7.1), Inches(1.75), Inches(5.5), Inches(0.4),
    [[("The Visual Studio stack", 14, TEAL, True)]])
sub = [("Visual Studio","IDE"),("C++ / C#","Languages"),("Windows OS","Target platform")]
n=len(sub); yv=Inches(2.35)
for i,(a,b) in enumerate(sub):
    yy = yv + Inches(i*1.25)
    rect(s, Inches(7.1), yy, Inches(5.3), Inches(1.0), NAVY if i==0 else NAVY2,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s, Inches(7.4), yy, Inches(5.0), Inches(1.0),
        [[(a, 18, WHITE, True),("   "+b, 12, RGBColor(0xBF,0xD6,0xE0), False)]],
        anchor=MSO_ANCHOR.MIDDLE)
    if i<n-1:
        rect(s, Inches(9.5), yy+Inches(1.0)-Inches(0.02), Inches(0.36), Inches(0.28),
             AMBER, shape=MSO_SHAPE.DOWN_ARROW)
note(s, "한 시대의 개발은 'IDE + 언어 + OS'의 조합으로 정의되었습니다 — Visual Studio + C++/C# + Windows.", y=Inches(6.05))
footer(s)

# =========================================================
# SLIDE 2 — VS Code -> Python -> ML
# =========================================================
s = slide(); bg(s); header(s, 2, "VS Code arrives — lightweight, cross-platform", "2015→  ·  The editor that ate the world")
flow(s, [("VS Code","Free, extensible editor"),
         ("Python","Data & scripting"),
         ("Machine Learning","NumPy · PyTorch · scikit-learn")],
     y=Inches(2.5), h=Inches(1.9), colors=[NAVY, TEAL, GREEN])
bullets(s, Inches(0.7), Inches(4.7), Inches(11.8), [
    ("Not a heavy IDE — a fast editor made powerful by extensions.", ""),
    ("Python + Jupyter turned VS Code into the default home for data science and ML.", ""),
], size=15, gap=12)
note(s, "가볍고 무료이며 확장(extension)으로 무한히 커지는 구조 — VS Code가 사실상의 표준 에디터가 됩니다.", y=Inches(5.9))
footer(s)

# =========================================================
# SLIDE 3 — Remote SSH -> Ubuntu -> multi-language
# =========================================================
s = slide(); bg(s); header(s, 3, "Remote development — your laptop drives a server", "Remote-SSH  ·  One editor, any machine")
flow(s, [("VS Code","Local UI"),
         ("Remote / SSH","Secure tunnel"),
         ("Ubuntu OS","Powerful Linux server")],
     y=Inches(1.85), h=Inches(1.55), colors=[NAVY, TEAL, GREEN])
txt(s, Inches(0.7), Inches(3.7), Inches(11.8), Inches(0.4),
    [[("One remote editor, three kinds of software:", 15, NAVY, True)]])
cards(s, [
    ("C / C++","Native, high-performance applications"),
    ("Python","Machine learning & data pipelines"),
    ("HTML / JavaScript","Web applications & dashboards"),
], y=Inches(4.15), h=Inches(2.2), cols=3, top_colors=[CORAL, GREEN, AMBER])
footer(s)

# =========================================================
# SLIDE 4 — VS Code + Copilot -> AI development
# =========================================================
s = slide(); bg(s); header(s, 4, "VS Code + Copilot — the first AI pair-programmer", "2021→  ·  AI enters the editor")
flow(s, [("VS Code","Editor"),
         ("GitHub Copilot","LLM autocomplete"),
         ("AI-assisted development","Code suggested as you type")],
     y=Inches(2.5), h=Inches(1.9), colors=[NAVY, TEAL, AMBER])
bullets(s, Inches(0.7), Inches(4.7), Inches(11.8), [
    ("Inline completions from a large language model — the first mainstream 'AI in the editor'.", ""),
    ("Developers stop typing boilerplate; the model drafts, the human reviews.", ""),
], size=15, gap=12)
note(s, "Copilot은 'AI가 코드를 제안하는' 시대의 문을 열었습니다 — 개발의 무게중심이 타이핑에서 검토로 이동.", y=Inches(5.9))
footer(s)

# =========================================================
# SLIDE 5 — VS Code + multi LLM -> Cursor
# =========================================================
s = slide(); bg(s); header(s, 5, "Cursor — VS Code reborn around multiple LLMs", "2023→  ·  The AI-native fork by Anysphere")
flow(s, [("VS Code base","Open-source core"),
         ("Multi-LLM","Claude · GPT · Gemini"),
         ("Cursor (Anysphere)","AI-native IDE")],
     y=Inches(1.65), h=Inches(1.35), colors=[NAVY, TEAL, GREEN])
txt(s, Inches(0.7), Inches(3.2), Inches(11.8), Inches(0.4),
    [[("A meteoric commercial hit — one of the fastest-growing software companies ever:", 15, NAVY, True)]])
# valuation timeline chips
tl = [
    ("$9.9B","Jun 2025 · >$500M ARR", TEAL),
    ("$29.3B","Nov 2025 · Series D, $2.3B raised", GREEN),
    ("$2B ARR","Feb 2026 · reached in ~3 years", AMBER),
    ("$60B","Jun 2026 · acquired by SpaceX", CORAL),
]
tmargin=Inches(0.7); tgap=Inches(0.3); tcw=(SW-2*tmargin-3*tgap)/4; tch=Inches(1.35); ty=Inches(3.75)
for i,(big,sub,col) in enumerate(tl):
    x=tmargin+i*(tcw+tgap)
    rect(s,x,ty,tcw,tch,CARD,line=LINE,line_w=1,shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    rect(s,x,ty,tcw,Inches(0.12),col)
    txt(s,x+Inches(0.15),ty+Inches(0.22),tcw-Inches(0.3),tch-Inches(0.3),
        [[(big,26,col,True)],[(sub,11,GRAY,False)]],align=PP_ALIGN.CENTER,
        space_after=6,line_spacing=1.05)
    if i<3:
        rect(s,x+tcw+Inches(0.02),ty+tch/2-Inches(0.12),Inches(0.26),Inches(0.24),
             col,shape=MSO_SHAPE.RIGHT_ARROW)
note(s, "SpaceX가 Cursor(Anysphere)를 $60B에 인수해 xAI 산하로 편입 — 'AI 네이티브' IDE가 하나의 거대 산업이 되었습니다.", y=Inches(5.55))
footer(s)

# =========================================================
# SLIDE 6 — Agentic AI -> autonomous coding
# =========================================================
s = slide(); bg(s); header(s, 6, "Agentic AI — Claude Code & Codex run the tools", "2024–2025  ·  Era of autonomous coding")
flow(s, [("VS Code / terminal","Host"),
         ("Agentic AI","Claude Code · Codex"),
         ("Autonomous coding","Plans · edits · tests · ships")],
     y=Inches(2.5), h=Inches(1.9), colors=[NAVY, TEAL, CORAL])
bullets(s, Inches(0.7), Inches(4.7), Inches(11.8), [
    ("The AI no longer just suggests — it reads files, runs commands, edits code, and verifies results.", ""),
    ("A single instruction becomes many autonomous steps: the agent owns the loop.", ""),
], size=15, gap=12)
note(s, "제안(suggest)을 넘어 실행(act)으로 — 에이전트가 파일을 읽고, 명령을 실행하고, 코드를 고치는 '자율 코딩' 시대.", y=Inches(5.9))
footer(s)

# =========================================================
# SLIDE 7 — AntiGravity (Google)
# =========================================================
s = slide(); bg(s); header(s, 7, "Antigravity — Google's branded agentic IDE", "2025  ·  The platform vendors move in")
flow(s, [("VS Code lineage","Familiar base"),
         ("Google Antigravity","Branded & customized"),
         ("Agent-first IDE","Tuned for Google's models")],
     y=Inches(2.35), h=Inches(1.75), colors=[NAVY, GREEN, TEAL])
bullets(s, Inches(0.7), Inches(4.45), Inches(11.8), [
    ("Big vendors now ship their own opinionated, branded AI IDEs on top of the VS Code lineage.", ""),
    ("The pattern is set:  take VS Code as a template, then customize it for a specific audience.", ""),
], size=15, gap=11)
note(s, "핵심 흐름: VS Code를 '템플릿'으로 삼아 특정 목적에 맞게 브랜딩·커스터마이즈한다 — 다음은 '연구자'입니다.", y=Inches(5.75))
footer(s)

# =========================================================
# SLIDE 8 — GHBIO: IDE for Omics researcher
# =========================================================
s = slide(); bg(s, NAVY)
kicker_bar(s)
rect(s, 0, Inches(2.0), SW, Inches(3.5), NAVY2)
txt(s, Inches(0.8), Inches(0.9), Inches(11.8), Inches(0.5),
    [[("THE NEXT STEP", 15, TEAL, True)]])
txt(s, Inches(0.8), Inches(1.4), Inches(11.8), Inches(1.6),
    [[("GHBio opens up the IDE for Omics researchers", 34, WHITE, True)],
     [("오믹스 연구자를 위한 AI IDE — VS Code를 템플릿으로", 18, RGBColor(0xBF,0xD6,0xE0), False)]],
    space_after=8)
flow(s, [("VS Code / code-server","Proven template"),
         ("+ Omics pipelines","scRNA-seq, and beyond"),
         ("GHBio Co-Scientist","IDE for biologists")],
     y=Inches(3.5), h=Inches(1.55), colors=[TEAL, GREEN, AMBER])
txt(s, Inches(0.8), Inches(5.5), Inches(11.8), Inches(1.2),
    [[("Same idea as Cursor and Antigravity — but the audience is the wet-lab biologist, ", 15, WHITE, False),
      ("not the software engineer.", 15, TEAL, True)]],
    anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.15)
footer(s)

# =========================================================
# SLIDE 9 — GHBio Co-Scientist overview
# =========================================================
s = slide(); bg(s); header(s, 9, "GHBio Co-Scientist — a workbench for omics", "The product  ·  PlatformIO-style, for biology")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.2), [
    ("A VS Code / code-server extension", "— runs in the browser, nothing to install."),
    ("A PlatformIO-style bioinformatics workbench", "for biologists, not programmers."),
    ("Tree views + a reliable AI Analysis panel", "guide the whole analysis end-to-end."),
    ("Bilingual UI (Korean primary)", "built for wet-lab researchers with no coding."),
], size=14, gap=13)
# right-half stacked cards
rc = [
    ("Runs in the browser","code-server at ghbiocosci.iotok.org — open a tab, start analyzing."),
    ("No coding required","Click a pipeline stage; the extension runs the tools for you."),
    ("AI Co-Scientist built in","One-click biological interpretation of your results."),
]
rx = Inches(7.15); rw = Inches(5.5); ry = Inches(1.75); rh = Inches(1.35); rgap = Inches(0.22)
for i,(t,b) in enumerate(rc):
    yy = ry + i*(rh+rgap)
    rect(s, rx, yy, rw, rh, CARD, line=LINE, line_w=1, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    rect(s, rx, yy, Inches(0.12), rh, [TEAL, GREEN, AMBER][i])
    txt(s, rx+Inches(0.3), yy+Inches(0.16), rw-Inches(0.5), rh-Inches(0.3),
        [[(t, 15, NAVY, True)], [(b, 12, GRAY, False)]], space_after=5, line_spacing=1.06)
footer(s)

# =========================================================
# SLIDE 10 — Who it's for / the problem
# =========================================================
s = slide(); bg(s); header(s, 10, "The problem it solves", "Users  ·  Korean biologists, no Copilot")
cards(s, [
    ("The gap","Modern omics analysis lives in the command line — alignment, Python, clustering. Most biologists don't code."),
    ("The barrier","Setting up STAR, references, Scanpy and a GPU box is days of DevOps before any biology happens."),
    ("The answer","Co-Scientist hides all of it behind click-to-run stages and an AI that explains the results in Korean."),
], y=Inches(1.75), h=Inches(2.5), cols=3, top_colors=[CORAL, AMBER, GREEN])
bullets(s, Inches(0.7), Inches(4.6), Inches(11.8), [
    ("Bilingual UI strings (Korean primary); the AI panel replies in Korean by default.", ""),
    ("Heavy inputs (FASTQ, ~30–40 GB GRCh38 index) are set up once and reused — no repeat downloads.", ""),
], size=14, gap=11)
footer(s)

# =========================================================
# SLIDE 11 — Architecture: data-driven registry
# =========================================================
s = slide(); bg(s); header(s, 11, "Architecture — a data-driven registry", "Design goal  ·  Add a domain by dropping in files")
txt(s, Inches(0.7), Inches(1.6), Inches(11.8), Inches(0.5),
    [[("New analysis domains are added with JSON manifests — ", 15, INK, False),
      ("no TypeScript changes.", 15, CORAL, True)]])
flow(s, [("module.json","Domain identity + libraries + AI config"),
         ("pipeline.json","Ordered stages per pipeline"),
         ("Tree + AI panel","Rendered at runtime from manifests")],
     y=Inches(2.3), h=Inches(1.7), colors=[NAVY, TEAL, GREEN])
cards(s, [
    ("modules/<id>/module.json","Identity, installable libraries (with presentPath existence check), and AI config."),
    ("modules/<id>/pipelines/<pid>/pipeline.json","A pipeline's ordered stages (task / ai kinds)."),
    ("_ prefix = ignored","Dirs like _template / _wip-* are skipped by the loader."),
], y=Inches(4.3), h=Inches(2.1), cols=3, top_colors=[TEAL, GREEN, AMBER])
footer(s)

# =========================================================
# SLIDE 12 — Module registry
# =========================================================
s = slide(); bg(s); header(s, 12, "The module registry (src/modules.ts)", "One module = one analysis domain")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.1), [
    ("A module is a whole analysis domain", "— scRNA-seq today; protein modeling tomorrow."),
    ("Everything domain-specific is JSON", "read at runtime, not hard-coded."),
    ("Declares its libraries", "installable tools + an existence check (presentPath)."),
    ("Declares its AI config", "system prompt, preset prompts, result-file context."),
], size=14, gap=12)
# code-ish card
rect(s, Inches(7.05), Inches(1.7), Inches(5.6), Inches(4.4), NAVY,
     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s, Inches(7.05), Inches(1.75), Inches(5.6), Inches(0.4),
    [[("modules/scrna-seq/module.json", 12, TEAL, True)]], align=PP_ALIGN.CENTER)
code_lines = [
    '"id": "scrna-seq",',
    '"name": "Single-cell RNA-seq",',
    '"libraries": [',
    '   Python / Scanpy   (~/ghbio-venv)',
    '   STAR / STARsolo   (~/bin/STAR)',
    '   GRCh38 index      (~30 GB)',
    '],',
    '"ai": { system, prompts,',
    '        context, readyFile }',
]
txt(s, Inches(7.35), Inches(2.25), Inches(5.1), Inches(3.7),
    [[(l, 13, RGBColor(0xCF,0xE8,0xE4), False)] for l in code_lines],
    space_after=6, line_spacing=1.1)
footer(s)

# =========================================================
# SLIDE 13 — Three tree views
# =========================================================
s = slide(); bg(s); header(s, 13, "Three tree views drive the whole app", "Pipelines · Projects · Libraries")
cards(s, [
    ("🧪  Pipelines","Pick an analysis and run its stages in order, each with ▶ / ✅ banners in the terminal."),
    ("📁  Projects","Every pipeline gets its own project dir; results are first-class files you can browse."),
    ("📦  Libraries","Installable tools (Scanpy, STAR, GRCh38 index) with a live 'installed?' check."),
], y=Inches(1.9), h=Inches(3.3), cols=3, top_colors=[TEAL, GREEN, AMBER])
note(s, "세 개의 트리 뷰가 UI의 전부입니다 — 파이프라인 실행, 결과 탐색, 도구 설치가 클릭 한 번으로.", y=Inches(5.5))
footer(s)

# =========================================================
# SLIDE 14 — Pipeline engine
# =========================================================
s = slide(); bg(s); header(s, 14, "The pipeline engine (src/pipeline.ts)", "The core 'deep module'")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.1), [
    ("A narrow interface over a rich engine", "runPipeline · stageStatus · isStageDone · ensureProject."),
    ("Hides the hard parts", "stage ordering, project scaffolding, idempotency, AI hand-off."),
    ("No UI concerns inside", "so it can also back a future headless 'AI-as-a-webservice'."),
], size=14, gap=13)
cards(s, [
    ('kind: "task"','Runs a shell command as a VS Code Task in the terminal, with ▶ / ✅ / → next banners.'),
    ('kind: "ai"','Opens the AI Analysis panel to interpret results.'),
    ('produces: [...]','Declared artifacts → the stage auto-marks ✓ complete (idempotent re-runs).'),
], y=Inches(1.75), h=Inches(4.3), cols=1, top_colors=[TEAL, AMBER, GREEN])
footer(s)

# =========================================================
# SLIDE 15 — GHBIO_RESULTS
# =========================================================
s = slide(); bg(s); header(s, 15, "GHBIO_RESULTS — results are project files", "Load-bearing convention")
txt(s, Inches(0.7), Inches(1.65), Inches(11.8), Inches(0.5),
    [[("Every stage runs with ", 15, INK, False),
      ("GHBIO_RESULTS", 15, CORAL, True),
      (" pointing at that pipeline's own results dir:", 15, INK, False)]])
rect(s, Inches(0.7), Inches(2.25), Inches(11.9), Inches(0.7), NAVY,
     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s, Inches(0.9), Inches(2.25), Inches(11.5), Inches(0.7),
    [[("~/ghbio-workspace/projects/<pipelineId>/results/", 17, TEAL, True)]],
    anchor=MSO_ANCHOR.MIDDLE)
bullets(s, Inches(0.7), Inches(3.35), Inches(11.8), [
    ("Any script a pipeline runs MUST read GHBIO_RESULTS — hard-coding a path writes into the wrong project.", ""),
    ("Results become first-class files, surfaced in the Projects view and fed to the AI panel.", ""),
    ("Heavy shared inputs (FASTQ, GRCh38 index, ~40 GB) stay under ~/ghbio-tutorial/ and are reused idempotently.", ""),
], size=14, gap=13)
note(s, "결과물이 곧 프로젝트 파일입니다 — 이 규칙 덕분에 AI 분석과 리포트 단계가 항상 올바른 출력을 찾습니다.", y=Inches(5.85))
footer(s)

# =========================================================
# SLIDE 16 — scRNA-seq module libraries
# =========================================================
s = slide(); bg(s); header(s, 16, "The scRNA-seq module — tools it installs", "Single-cell RNA-seq  ·  built for aarch64")
cards(s, [
    ("Python / Scanpy","~/ghbio-venv — scanpy, anndata, leiden, umap. One-click env setup."),
    ("STAR / STARsolo","~/bin/STAR — the aligner, compiled from source (no Cell Ranger on ARM)."),
    ("GRCh38 reference","~/ghbio-tutorial/ref/star_index — ~30 GB index, built once and reused."),
], y=Inches(1.85), h=Inches(2.6), cols=3, top_colors=[GREEN, TEAL, AMBER])
bullets(s, Inches(0.7), Inches(4.75), Inches(11.8), [
    ("Each library declares a presentPath — the Libraries view shows installed vs. not, live.", ""),
    ("Two datasets ship as pipelines: PBMC (10x) and Glioblastoma (10x); plus 'bring your own matrix'.", ""),
], size=14, gap=11)
footer(s)

# =========================================================
# SLIDE 17 — pipeline stages
# =========================================================
s = slide(); bg(s); header(s, 17, "One pipeline: FASTQ → matrix → clustering → AI", "scRNA-seq PBMC / Glioblastoma  ·  8 stages")
stages = [
    ("0 · Setup","Python env"),
    ("1 · Download","FASTQ data"),
    ("2a · Build STAR","Compile aligner"),
    ("2b · Reference","GRCh38 index"),
    ("2c · STARsolo","Align → matrix"),
    ("3 · Scanpy","QC & clustering"),
    ("4 · AI","Hypotheses"),
    ("5 · Report","PDF"),
]
# two rows of 4
margin=Inches(0.6); gap=Inches(0.3); cw=(SW-2*margin-3*gap)/4; ch=Inches(1.25)
pal=[NAVY,NAVY2,TEAL,TEAL,GREEN,GREEN,AMBER,CORAL]
for i,(a,b) in enumerate(stages):
    r=i//4; c=i%4
    x=margin+c*(cw+gap); y=Inches(1.9)+r*(ch+Inches(0.55))
    rect(s,x,y,cw,ch,pal[i],shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s,x+Inches(0.1),y,cw-Inches(0.2),ch,
        [[(a,15,WHITE,True)],[(b,11,RGBColor(0xDF,0xEC,0xF0),False)]],
        align=PP_ALIGN.CENTER,anchor=MSO_ANCHOR.MIDDLE,space_after=3,line_spacing=1.0)
    if c<3:
        rect(s,x+cw+Inches(0.02),y+ch/2-Inches(0.14),Inches(0.26),Inches(0.28),
             AMBER,shape=MSO_SHAPE.RIGHT_ARROW)
note(s, "'Bring your own matrix' 파이프라인은 정렬 단계를 건너뛰고 사용자의 count matrix에서 바로 시작합니다.", y=Inches(5.65))
footer(s)

# =========================================================
# SLIDE 18 — AI Analysis panel
# =========================================================
s = slide(); bg(s); header(s, 18, "The AI Analysis panel — reliable by design", "src/ai/panel.ts  ·  one shot, no agent loop")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.2), [
    ("One streaming request → render the answer.", "No agent, no tools, no file edits."),
    ("Cancelable with Stop.", "The 'reliability fix' is the whole point."),
    ("Result CSVs read into the prompt", "markers_by_cluster.csv, celltype_draft.csv."),
    ("Answers in Korean by default.", "A careful single-cell analyst persona."),
], size=14, gap=12)
cards(s, [
    ("Providers","anthropic · groq · openrouter · deepseek (OpenAI-compatible). Keys live outside the repo."),
    ("Preset vs. free-form","Presets need result files; free-form questions answered anytime."),
    ("Deliberately simple","No tool/agent loop here — that's what makes it dependable."),
], y=Inches(1.75), h=Inches(4.3), cols=1, top_colors=[TEAL, GREEN, AMBER])
footer(s)

# =========================================================
# SLIDE 19 — Preset prompts & save to report
# =========================================================
s = slide(); bg(s); header(s, 19, "Preset prompts & save-to-report", "From markers to hypotheses in one click")
cards(s, [
    ("Interpret clusters","Cell identity & activation state per cluster, with confidence and doublet flags."),
    ("Refine annotation","Canonical PBMC markers → tidy per-cluster cell-type table."),
    ("Pathways","Group markers into biological programs; suggest gene sets to test."),
    ("Testable hypotheses","3–5 hypotheses with rationale, prediction, and how to validate."),
    ("Question list","8–10 prioritized follow-up analyses, each with a one-line method."),
    ("📘 Easy report","A high-schooler-friendly report full of everyday analogies (Korean)."),
], y=Inches(1.75), h=Inches(3.1), cols=3, top_colors=[TEAL,GREEN,AMBER,CORAL,NAVY2,TEAL])
note(s, "'Save to report' → step4_ai_report.md / step4_ai_report_easy.md 를 결과 폴더에 저장하고, 05_make_report.sh 가 PDF에 선택적으로 포함합니다.", y=Inches(5.35))
footer(s)

# =========================================================
# SLIDE 20 — Deployment
# =========================================================
s = slide(); bg(s); header(s, 20, "How it ships — code-server on ARM", "Deployment  ·  browser-native, self-hosted")
cards(s, [
    ("code-server","Runs in the browser at ghbiocosci.iotok.org — VS Code, no local install."),
    ("aarch64 box","ARM server: STAR built from source, no Cell Ranger. Python venv at ~/ghbio-venv."),
    ("build.sh deploy","esbuild bundle → .vsix zipped by hand → installed → ghbio-code service restart."),
], y=Inches(1.85), h=Inches(2.6), cols=3, top_colors=[TEAL, GREEN, AMBER])
bullets(s, Inches(0.7), Inches(4.75), Inches(11.8), [
    ("code-server settings disable built-in Copilot/chat and exclude huge *.fastq / *.bam files from the Explorer.", ""),
    ("Version bump + browser hard-refresh needed on each deploy — the AI panel is the single point of contact.", ""),
], size=14, gap=11)
footer(s)

# =========================================================
# SLIDE 21 — Conclusion
# =========================================================
s = slide(); bg(s, NAVY); kicker_bar(s)
rect(s, 0, Inches(1.7), SW, Inches(0.06), TEAL)
txt(s, Inches(0.8), Inches(0.8), Inches(11.8), Inches(0.9),
    [[("Conclusion", 15, TEAL, True)],
     [("The IDE meets the wet lab", 34, WHITE, True)]], space_after=6)
cards2 = [
    ("Same lineage","VS Code → Copilot → Cursor → agentic IDEs. Co-Scientist stands on that proven path."),
    ("New audience","Not software engineers — biologists. Click-to-run pipelines, AI that explains results."),
    ("Data-driven","Drop in a module.json + pipeline.json and a whole new omics domain appears. No code."),
]
margin=Inches(0.8); gap=Inches(0.4); cw=(SW-2*margin-2*gap)/3
for i,(t,b) in enumerate(cards2):
    x=margin+i*(cw+gap); y=Inches(2.1)
    rect(s,x,y,cw,Inches(2.5),NAVY2,shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    rect(s,x,y,cw,Inches(0.12),[TEAL,GREEN,AMBER][i])
    txt(s,x+Inches(0.25),y+Inches(0.3),cw-Inches(0.5),Inches(2.0),
        [[(t,17,WHITE,True)],[(b,13,RGBColor(0xC7,0xDA,0xE2),False)]],
        space_after=8,line_spacing=1.12)
txt(s, Inches(0.8), Inches(5.1), Inches(11.8), Inches(1.4),
    [[("“IDE for Omics Researcher” — ", 20, WHITE, True),
      ("오믹스 연구자를 위한 AI IDE", 20, TEAL, True)],
     [("Bringing the autonomous-coding revolution to the people who ask the biological questions.", 14, RGBColor(0xBF,0xD6,0xE0), False)]],
    space_after=10, line_spacing=1.2)
footer(s)

# =========================================================
# SLIDE 22 — About Us
# =========================================================
s = slide(); bg(s); header(s, 22, "About Us — 지에이치바이오(주) / GHBio", "Company  ·  ghbio.co.kr")
bullets(s, Inches(0.7), Inches(1.7), Inches(6.3), [
    ("지에이치바이오(주) (GHBio)", "innovative mouse models for drug-development research."),
    ("Preclinical efficacy & safety", "in-vivo efficacy, non-GLP tox & pharmacology, PK, bioluminescence imaging."),
    ("Gene-editing & humanized models", "metabolic disease, viral infection, immunodeficient, humanized-liver."),
    ("Immune-checkpoint humanized mice", "PD-1, CTLA-4, TIGIT, TIM-3, 4-1BB, CD3E — for cancer immunotherapy."),
], size=13.5, gap=12)
# contact card
rect(s, Inches(7.35), Inches(1.7), Inches(5.3), Inches(4.4), CARD, line=LINE, line_w=1,
     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
rect(s, Inches(7.35), Inches(1.7), Inches(5.3), Inches(0.12), TEAL)
txt(s, Inches(7.65), Inches(2.0), Inches(4.7), Inches(4.0),
    [[("Contact", 16, NAVY, True)],
     [("Representative", 12, TEAL, True),("   유경원 (Yoo Kyung-won)", 13, INK, False)],
     [("Location", 12, TEAL, True),("   대전 유성구 테크노4로 17, D217", 13, INK, False)],
     [("", 12, TEAL, True),("   Daejeon, South Korea", 12, GRAY, False)],
     [("Phone", 12, TEAL, True),("   042-716-2177", 13, INK, False)],
     [("Email", 12, TEAL, True),("   ghbio@gh-bio.com", 13, INK, False)],
     [("Web", 12, TEAL, True),("   ghbio.co.kr", 13, INK, False)],
     [("Biz reg.", 12, TEAL, True),("   318-81-03789", 13, INK, False)],
    ], space_after=11, line_spacing=1.1)
note(s, "신약개발용 마우스 모델과 전임상 유효성·안전성 평가 서비스 전문기업 — 그 데이터 과학 역량이 GHBio Co-Scientist로 이어집니다.", y=Inches(6.2))
footer(s)

out = "/home/jit/ghbio-coscientist/IDE_for_Omics_Researcher.pptx"
prs.save(out)
print("SAVED", out, "slides:", len(prs.slides._sldIdLst))
