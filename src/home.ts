import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { TutorialProvider } from "./tutorials"
import { pipelineProgress } from "./pipeline"
import { projectsDir } from "./util"
import { missionHtml } from "./mission"

let panel: vscode.WebviewPanel | undefined

export function openHome(context: vscode.ExtensionContext, tutorials: TutorialProvider) {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioHome", "GHBIO Home", vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    panel.onDidDispose(() => (panel = undefined))
    panel.webview.onDidReceiveMessage((m) => {
      if (m?.cmd) vscode.commands.executeCommand(m.cmd, ...(m.args ?? []))
    })
  }
  render(panel, tutorials)
  panel.reveal()
}

function tutorialCards(tutorials: TutorialProvider): { html: string; ids: Set<string> } {
  const ids = new Set<string>()
  const cards = tutorials
    .getModules()
    .flatMap((m) =>
      m.pipelines.map((pl) => {
        ids.add(pl.id)
        const { done, total } = pipelineProgress(pl)
        const pct = total ? Math.round((done / total) * 100) : 0
        return `<div class="card tut">
          <div class="ctop"><span class="chip">TUTORIAL</span><h3>${esc(pl.name)}</h3></div>
          <p>${esc(pl.summary ?? "")}</p>
          <div class="bar"><i style="width:${pct}%"></i></div>
          <div class="meta">진행: ${done} / ${total} 결과 단계</div>
          <div class="cbtns">
            <button onclick="send('ghbio.openDashboard','${esc(pl.id)}')">대시보드 열기</button>
          </div>
        </div>`
      }),
    )
    .join("")
  return { html: cards, ids }
}

function projectCards(tutorialIds: Set<string>): string {
  const root = projectsDir()
  if (!fs.existsSync(root)) return ""
  const dirs = fs
    .readdirSync(root, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !tutorialIds.has(e.name)) // tutorials shown above
    .map((e) => path.join(root, e.name))
  if (!dirs.length) return `<div class="empty">아직 만든 프로젝트가 없습니다. 위 <b>새 프로젝트</b>로 시작하거나 튜토리얼을 열어보세요.</div>`
  return dirs
    .map((dir) => {
      const results = path.join(dir, "results")
      const n = fs.existsSync(results) ? fs.readdirSync(results).filter((f) => !f.startsWith(".")).length : 0
      return `<div class="card proj">
        <div class="ctop"><span class="chip gray">PROJECT</span><h3>${esc(path.basename(dir))}</h3></div>
        <p>결과 파일 ${n}개</p>
        <div class="cbtns">
          <button class="ghost" onclick="send('ghbio.openDashboard','${esc(dir)}')">대시보드 열기</button>
        </div>
      </div>`
    })
    .join("")
}

// Deterministic seeded PRNG (mulberry32) so the hero UMAP renders identically every time.
function makeRng(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// A freshly-generated single-cell UMAP cluster plot, drawn as inline SVG (neon teal /
// violet / orange / cyan / pink cells) — the "central panel" of the hero IDE mock.
function umapSvg(): string {
  const rnd = makeRng(20260715)
  const clusters = [
    { cx: 120, cy: 96, n: 78, color: "#2dd4bf" },
    { cx: 258, cy: 150, n: 88, color: "#a78bfa" },
    { cx: 172, cy: 214, n: 64, color: "#fb923c" },
    { cx: 306, cy: 74, n: 46, color: "#22d3ee" },
    { cx: 86, cy: 186, n: 40, color: "#f472b6" },
    { cx: 232, cy: 236, n: 34, color: "#fbbf24" },
  ]
  let dots = ""
  for (const c of clusters) {
    for (let i = 0; i < c.n; i++) {
      const a = rnd() * Math.PI * 2
      const r = ((rnd() + rnd() + rnd()) / 3) * 40
      const x = c.cx + Math.cos(a) * r
      const y = c.cy + Math.sin(a) * r * 0.9
      const op = (0.5 + rnd() * 0.5).toFixed(2)
      const rad = (1.5 + rnd() * 1.5).toFixed(1)
      dots += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rad}" fill="${c.color}" opacity="${op}"/>`
    }
  }
  return `<svg viewBox="0 0 390 290" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">${dots}</svg>`
}

// The hero: a modern dark landing that explains what BioIDE does, with a mock IDE window
// (AI chat log · newly generated UMAP · reproduction report) and glassmorphic metric cards.
function heroHtml(): string {
  const chatLines = [
    ["▸", "Analyzing scRNA-seq paper… (Peng 2019, PDAC)"],
    ["✓", "Public raw data verified — Zenodo / GEO"],
    ["▸", "Rewriting legacy R/Seurat → Python + GPU"],
    ["⚡", "GPU reanalysis on CUDA (scVI / rapids)…"],
    ["✓", "Clusters + cell types re-derived independently"],
    ["▸", "Validating authors' claims (ARI, markers)…"],
  ]
    .map(
      ([g, t]) =>
        `<div class="log"><span class="glyph ${g === "✓" ? "ok" : g === "⚡" ? "zap" : "run"}">${g}</span>${esc(t)}</div>`,
    )
    .join("")
  const report =
    '<div class="rl h1"># Reproduction Report</div>' +
    '<div class="rl">독립 GPU·Python 재분석 결과</div>' +
    '<div class="rl h2">## 악성 도관세포 (malignant ductal)</div>' +
    '<div class="rl ok">✓ 저자 주장: <b>재현됨 (confirmed)</b></div>' +
    '<div class="rl code">markers: KRT19, MUC1, S100P, LGALS3</div>' +
    '<div class="rl code">malignancy score: 0.93 vs 0.03</div>' +
    '<div class="rl">ARI vs 저자 라벨: <b>0.86</b></div>'
  return (
    '<div class="hero">' +
    '<div class="hero-left">' +
    '<div class="badge">⚡ GPU-accelerated bioinformatics IDE · VS Code</div>' +
    '<h1 class="hero-title" id="brand" title="클릭하면 BioIDE 헌장이 열립니다">Bio<span>IDE</span></h1>' +
    '<div class="hero-tag">From Paper to Pipeline — in seconds.</div>' +
    '<p class="hero-lead">암 연구 <b>scRNA-seq 기념비적 논문</b>을 AI가 찾고, 저자의 분석을 ' +
    '<b>우리가 새로 짠 GPU·Python 코드</b>로 처음부터 다시 도출해 결론을 <b>독립 검증</b>합니다. ' +
    '느린 R/Seurat를 Python·GPU로 대체하고, 개선된 소스코드를 커뮤니티에 남깁니다.</p>' +
    '<div class="hero-cta">' +
    '<button onclick="send(\'ghbio.openCreatePipeline\')">🔎 논문 찾기 → 파이프라인 설계</button>' +
    '<button class="ghost" id="showMission">📜 BioIDE 헌장</button>' +
    "</div>" +
    '<div class="metrics">' +
    '<div class="glass"><b>100×</b><span>GPU 가속 재분석</span></div>' +
    '<div class="glass"><b>Paper → Pipeline</b><span>AI 자동 설계</span></div>' +
    '<div class="glass"><b>Independent</b><span>저자 주장 검증</span></div>' +
    "</div>" +
    "</div>" +
    '<div class="hero-right">' +
    '<div class="ide">' +
    '<div class="ide-bar"><span class="tdot r"></span><span class="tdot y"></span><span class="tdot g"></span>' +
    '<span class="ide-title">BioIDE — reproduction.ipynb</span></div>' +
    '<div class="ide-body">' +
    `<div class="ide-panel chat"><div class="ptag">AI</div>${chatLines}<div class="caret">▍</div></div>` +
    `<div class="ide-panel plot"><div class="ptag">UMAP</div><div class="umap">${umapSvg()}</div></div>` +
    `<div class="ide-panel report"><div class="ptag">REPORT</div>${report}</div>` +
    "</div></div></div>" +
    "</div>"
  )
}

export function render(p: vscode.WebviewPanel, tutorials: TutorialProvider) {
  const { html: tuts, ids } = tutorialCards(tutorials)
  const projs = projectCards(ids)
  p.webview.html = /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif; color: #e6edf3;
    margin: 0; padding: 26px 32px 70px; line-height: 1.6; background-color: #0b0f1a;
    background-image:
      radial-gradient(1200px 500px at 80% -10%, rgba(124,58,237,.18), transparent 60%),
      radial-gradient(900px 500px at 0% 0%, rgba(45,212,191,.12), transparent 55%),
      linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size: auto, auto, 34px 34px, 34px 34px;
    background-attachment: fixed; }
  h2 { font-size: 16px; margin: 30px 0 12px; color: #7ee7d6; }

  /* ---------- Hero ---------- */
  .hero { display: grid; grid-template-columns: 1.02fr 1.1fr; gap: 26px; align-items: center;
    margin: 6px 0 10px; }
  .badge { display:inline-block; font-size: 11.5px; font-weight: 700; color: #c4b5fd;
    background: rgba(124,58,237,.14); border: 1px solid #4c327e; padding: 4px 11px; border-radius: 999px; }
  .hero-title { font-size: 58px; font-weight: 800; letter-spacing: -1.5px; margin: 12px 0 2px; cursor: pointer;
    line-height: 1.02; }
  .hero-title span { background: linear-gradient(120deg,#2dd4bf,#22d3ee 40%,#a78bfa); -webkit-background-clip: text;
    background-clip: text; color: transparent; }
  .hero-title:hover { filter: brightness(1.12); }
  .hero-tag { font-size: 21px; font-weight: 700; color: #eef2f7; margin-bottom: 10px; }
  .hero-lead { font-size: 14px; color: #b6c2cf; max-width: 560px; margin: 0 0 16px; }
  .hero-cta { display:flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
  .metrics { display:flex; flex-wrap: wrap; gap: 10px; }
  .glass { background: rgba(255,255,255,.045); border: 1px solid rgba(255,255,255,.1); border-radius: 12px;
    padding: 10px 14px; backdrop-filter: blur(6px); min-width: 118px; }
  .glass b { display:block; font-size: 17px; color: #eafffb; }
  .glass span { font-size: 11.5px; color: #93a1b0; }

  /* ---------- IDE mock window ---------- */
  .ide { border: 1px solid #26303c; border-radius: 14px; overflow: hidden;
    background: linear-gradient(180deg,#111722,#0c1119); box-shadow: 0 24px 60px -24px rgba(0,0,0,.8), 0 0 0 1px rgba(124,58,237,.08); }
  .ide-bar { display:flex; align-items:center; gap:7px; padding: 9px 12px; background: #0e141d; border-bottom: 1px solid #1c2430; }
  .tdot { width:11px; height:11px; border-radius:50%; display:inline-block; }
  .tdot.r{background:#ff5f57} .tdot.y{background:#febc2e} .tdot.g{background:#28c840}
  .ide-title { margin-left: 8px; font-size: 12px; color: #7d8b9a; font-family: ui-monospace,Consolas,monospace; }
  .ide-body { display:grid; grid-template-columns: 1.05fr 1.15fr .95fr; gap: 1px; background:#1c2430; height: 300px; }
  .ide-panel { background:#0c1119; padding: 10px; overflow: hidden; position: relative; }
  .ptag { font-size: 9.5px; font-weight: 800; letter-spacing: .8px; color: #6b7684; margin-bottom: 8px; }
  .chat .log { font-family: ui-monospace,Consolas,monospace; font-size: 11px; color: #c2ccd6; margin: 5px 0; line-height: 1.35; }
  .chat .glyph { display:inline-block; width: 15px; }
  .chat .glyph.ok{color:#34d399} .chat .glyph.run{color:#38bdf8} .chat .glyph.zap{color:#fbbf24}
  .chat .caret { color:#2dd4bf; animation: blink 1s steps(1) infinite; font-size: 12px; }
  @keyframes blink { 50% { opacity: 0; } }
  .plot .umap { position:absolute; inset: 26px 8px 8px; }
  .plot { background: radial-gradient(circle at 50% 45%, #0f1622, #0a0e16); }
  .report .rl { font-family: ui-monospace,Consolas,monospace; font-size: 10.5px; color: #aeb9c6; margin: 4px 0; line-height: 1.4; }
  .report .rl.h1 { color:#eef2f7; font-weight: 700; font-size: 12px; }
  .report .rl.h2 { color:#7ee7d6; }
  .report .rl.ok { color:#34d399; }
  .report .rl.code { color:#c4b5fd; }

  /* ---------- cards ---------- */
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px,1fr)); gap: 14px; }
  .card { background: #12181f; border: 1px solid #253039; border-radius: 12px; padding: 15px 17px; }
  .card.tut { border-color: #1f6f57; }
  .card.cat { border-color: #30506e; cursor: pointer; }
  .card.cat:hover { border-color: #2dd4bf; }
  .card.create { border-color: #7c3aed; cursor: pointer; background: linear-gradient(135deg,#141024,#12181f); }
  .card.create:hover { border-color: #a78bfa; }
  .chip.create { background:#1e1233; color:#c4b5fd; border:1px solid #7c3aed; }
  .ctop { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
  .chip { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 12px;
    background: #10261f; color: #2dd4bf; border: 1px solid #1f6f57; }
  .chip.gray { background:#161e27; color:#8b98a5; border-color:#30363d; }
  .card h3 { margin: 0; font-size: 15px; }
  .card p { margin: 0 0 10px; color: #8b98a5; font-size: 13px; }
  .bar { height: 7px; background: #21313a; border-radius: 6px; overflow: hidden; margin: 8px 0 6px; }
  .bar > i { display:block; height:100%; background: linear-gradient(90deg,#2dd4bf,#22d3ee); }
  .meta { font-size: 12px; color: #b6c2cf; margin-bottom: 10px; }
  .cbtns { display:flex; gap:8px; }
  button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a; font-weight: 700;
    padding: 8px 15px; border-radius: 8px; font-size: 13px; }
  button.ghost { background: rgba(33,38,45,.6); color: #e6edf3; border: 1px solid #30363d; }
  .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
  .empty { color:#6e7b8a; font-size:13px; }
  a { color: #2dd4bf; }

  /* ---------- constitution (mission) — shared classes from src/mission.ts ---------- */
  .mission { margin: 12px 0; border: 1px solid #3b2f6e; border-left: 4px solid #7c3aed; border-radius: 12px;
    background: linear-gradient(135deg,#161029,#0f1626); padding: 14px 18px; }
  .mission-h { font-weight: 700; font-size: 15px; color: #c4b5fd; }
  .mission-h span { font-weight: 400; font-size: 12px; color: #8b98a5; }
  .mission-lead { margin: 8px 0 10px; font-size: 13px; color: #cbd5e1; }
  .mission-list { margin: 0; padding-left: 20px; font-size: 12.5px; color: #aeb9c6; line-height: 1.6; }
  .mission-list li { margin: 5px 0; }
  .mission-list b { color: #ddd6fe; }

  /* ---------- footer ---------- */
  .foot { margin-top: 34px; border-top: 1px solid #1c2430; padding-top: 16px; }
  .foot-h { font-size: 14px; color: #7ee7d6; font-weight: 700; margin-bottom: 8px; }
  .foot-copy { margin-top: 14px; color: #6e7b8a; font-size: 12px; }

  /* ---------- mission modal ---------- */
  .overlay { position: fixed; inset: 0; background: rgba(4,6,12,.72); backdrop-filter: blur(3px);
    display: none; align-items: flex-start; justify-content: center; padding: 6vh 18px; z-index: 50; overflow:auto; }
  .overlay.on { display: flex; }
  .modal { max-width: 760px; width: 100%; background: #0e1420; border: 1px solid #2a3446; border-radius: 16px;
    padding: 22px 24px 26px; box-shadow: 0 30px 80px -20px rgba(0,0,0,.9); position: relative; }
  .modal h3 { margin: 0 0 4px; font-size: 20px; color: #c4b5fd; }
  .modal .close { position: absolute; top: 12px; right: 14px; background: #21262d; color:#e6edf3; border:1px solid #30363d;
    padding: 4px 10px; border-radius: 8px; font-weight: 700; }

  @media (max-width: 900px) {
    .hero { grid-template-columns: 1fr; }
    .hero-title { font-size: 46px; }
    .ide-body { grid-template-columns: 1fr; height: auto; }
    .plot { height: 220px; }
    .plot .umap { inset: 26px 8px 8px; height: 190px; }
  }
</style></head><body>
  ${heroHtml()}

  <div class="actions">
    <button class="ghost" onclick="send('ghbio.newProject')">📁 새 프로젝트</button>
    <button class="ghost" onclick="send('ghbio.openHelp')">❓ 사용설명서</button>
    <button class="ghost" onclick="send('ghbio.openAI')">🤖 AI 분석</button>
  </div>

  <h2>튜토리얼 (예제 분석)</h2>
  <div class="grid">
    <div class="card create" onclick="send('ghbio.openCreatePipeline')" title="논문으로 파이프라인 만들기">
      <div class="ctop"><span class="chip create">CREATE</span><h3>➕ 파이프라인 만들기 (Create pipeline)</h3></div>
      <p>암 연구에서 scRNA-seq로 <b>의미 있는 발견</b>을 한 논문을 AI가 찾아 줍니다(원본 데이터 공개가 필수, 코드 공개면 가점). 마음에 드는 논문에서 <b>design pipeline</b>을 누르면, 그 워크플로를 <b>최신 AI·GPU·Python(R 대신)</b>으로 재현하고 <b>독립적 데이터 처리로 결론을 검증</b>하는 튜토리얼 계획을 만들어 줍니다.</p>
      <div class="cbtns"><button>🔎 논문 찾기 → 설계 (Find paper → design)</button></div>
    </div>${tuts}
    <div class="card cat" onclick="send('ghbio.openDatasetCatalog')" title="목록 보기">
      <div class="ctop"><span class="chip gray">DATASETS</span><h3>Human Single Cell 3′ Gene Expression FASTQ datasets</h3></div>
      <p>공개 10x Genomics 사람 3′ scRNA-seq FASTQ 데이터셋 목록 — 크기·chemistry·다운로드 링크를 표로 보여줍니다.</p>
      <div class="cbtns"><button class="ghost">📋 목록 보기 (View list)</button></div>
    </div>
    <div class="card cat" onclick="send('ghbio.openAtlas','synthetic')" title="아틀라스 열기">
      <div class="ctop"><span class="chip gray">ATLAS</span><h3>NSCLC 세포 아틀라스 · 합성 데이터 (Synthetic)</h3></div>
      <p>비소세포폐암 종양미세환경의 단일세포 아틀라스 (합성 교육용 데이터) — UMAP·유전자 발현·마커 dot plot·조성 비교를 직접 탐색하고, 가이드 투어·개념 카드·실습 문제로 scRNA-seq 분석을 배웁니다.</p>
      <div class="cbtns"><button class="ghost">🔬 아틀라스 열기 (Open explorer)</button></div>
    </div>
    <div class="card cat" onclick="send('ghbio.openAtlas','maynard')" title="아틀라스 열기">
      <div class="ctop"><span class="chip gray">ATLAS · REAL</span><h3>NSCLC 아틀라스 · Maynard 2020 실제 데이터</h3></div>
      <p>표적치료 중 폐선암(lung adenocarcinoma)의 실제 단일세포 데이터 (Maynard et al., Cell 2020) — scVI 재분석 21,620개 세포, Leiden 클러스터를 대표 마커로 명명, 조직축은 biopsy 부위. 실제 종양 데이터로 세포 유형·마커·조성을 탐색합니다.</p>
      <div class="cbtns"><button class="ghost">🧬 실제 데이터 열기 (Open real data)</button></div>
    </div>
  </div>

  <h2>내 프로젝트</h2>
  <div class="grid">${projs}</div>

  <div class="foot">
    <div class="foot-h">📜 BioIDE 헌장 (Central Dogma)</div>
    ${missionHtml()}
    <div class="foot-copy">BioIDE · <a href="https://ghbio.co.kr/ghbio/sub0401.php">ghbio.co.kr</a> · 헌장 전문은 상단 <b>BioIDE</b> 제목을 클릭하세요.</div>
  </div>

  <div class="overlay" id="missionOverlay">
    <div class="modal">
      <button class="close" id="missionClose">✕ 닫기</button>
      <h3>📜 BioIDE 헌장</h3>
      ${missionHtml()}
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
    var ov = document.getElementById('missionOverlay')
    function openMission(){ ov.classList.add('on') }
    function closeMission(){ ov.classList.remove('on') }
    var brand = document.getElementById('brand'); if (brand) brand.onclick = openMission
    var sm = document.getElementById('showMission'); if (sm) sm.onclick = openMission
    var mc = document.getElementById('missionClose'); if (mc) mc.onclick = closeMission
    ov.addEventListener('click', function(e){ if (e.target === ov) closeMission() })
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeMission() })
  </script>
</body></html>`
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
}
