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
  <h1>GHBIO <span class="a">Co-Scientist</span></h1>
  <div class="sub">단일세포 RNA 분석 작업실 · 튜토리얼을 열어 시작하거나, 내 프로젝트를 이어가세요.</div>
  <div class="actions">
    <button class="ghost" onclick="send('ghbio.newProject')">📁 새 프로젝트</button>
    <button class="ghost" onclick="send('ghbio.openHelp')">❓ 사용설명서</button>
    <button class="ghost" onclick="send('ghbio.openAI')">🤖 AI 분석</button>
  </div>

  <h2>튜토리얼 (예제 분석)</h2>
  <div class="grid">${tuts || '<div class="empty">설치된 튜토리얼이 없습니다.</div>'}</div>

  <h2>내 프로젝트</h2>
  <div class="grid">${projs}</div>

  <div class="foot">GHBIO AI Co-Scientist · <a href="https://ghbio.co.kr/ghbio/sub0401.php">ghbio.co.kr</a></div>
  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
  </script>
</body></html>`
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
}
