import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { TutorialProvider } from "./tutorials"
import { pipelineProgress } from "./pipeline"
import { projectsDir } from "./util"

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

function render(p: vscode.WebviewPanel, tutorials: TutorialProvider) {
  const { html: tuts, ids } = tutorialCards(tutorials)
  const projs = projectCards(ids)
  p.webview.html = /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif; color: #e6edf3;
    background: #0d1117; margin: 0; padding: 26px 32px 70px; line-height: 1.6; }
  h1 { font-size: 26px; margin: 0 0 2px; }
  h1 .a { color: #2dd4bf; }
  .sub { color: #8b98a5; margin-bottom: 8px; }
  h2 { font-size: 16px; margin: 26px 0 12px; color: #7ee7d6; }
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
    padding: 7px 13px; border-radius: 8px; font-size: 13px; }
  button.ghost { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
  .empty { color:#6e7b8a; font-size:13px; }
  .foot { margin-top: 30px; color: #6e7b8a; font-size: 12px; }
  a { color: #2dd4bf; }
</style></head><body>
  <h1>Bio<span class="a">IDE</span></h1>
  <div class="sub">단일세포 RNA 분석 작업실 · 튜토리얼을 열어 시작하거나, 내 프로젝트를 이어가세요.</div>
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

  <div class="foot">BioIDE · <a href="https://ghbio.co.kr/ghbio/sub0401.php">ghbio.co.kr</a></div>
  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
  </script>
</body></html>`
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
}
