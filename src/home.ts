import * as vscode from "vscode"
import { TutorialProvider } from "./tutorials"

let panel: vscode.WebviewPanel | undefined

export function openHome(context: vscode.ExtensionContext, tutorials: TutorialProvider) {
  if (panel) {
    panel.reveal()
    return
  }
  panel = vscode.window.createWebviewPanel("ghbioHome", "GHBIO Home", vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  panel.onDidDispose(() => (panel = undefined))
  panel.webview.onDidReceiveMessage((m) => {
    if (m?.cmd) vscode.commands.executeCommand(m.cmd, ...(m.args ?? []))
  })
  render(panel, tutorials)
}

function render(p: vscode.WebviewPanel, tutorials: TutorialProvider) {
  const items = tutorials
    .getModules()
    .flatMap((m) =>
      m.pipelines.map((pl) => `<li><b>${esc(m.name)}</b> · ${esc(pl.name)} — ${esc(pl.summary ?? "")}</li>`),
    )
    .join("")
  p.webview.html = /* html */ `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; color: #e6edf3;
    background: #0d1117; margin: 0; padding: 28px 32px; }
  h1 { font-size: 26px; margin: 0 0 2px; }
  h1 .a { color: #2dd4bf; }
  .sub { color: #8b98a5; margin-bottom: 22px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 14px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px 18px; }
  .card h3 { margin: 0 0 6px; font-size: 15px; }
  .card p { margin: 0 0 12px; color: #8b98a5; font-size: 13px; line-height: 1.5; }
  button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a; font-weight: 700;
    padding: 8px 14px; border-radius: 8px; font-size: 13px; }
  button.ghost { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  ul { color: #b6c2cf; font-size: 13px; line-height: 1.7; }
  .foot { margin-top: 26px; color: #6e7b8a; font-size: 12px; }
  a { color: #2dd4bf; }
</style></head><body>
  <h1>GHBIO <span class="a">Co-Scientist</span></h1>
  <div class="sub">scRNA-seq bioinformatics workbench · projects · libraries · tutorials · AI analysis</div>
  <div class="grid">
    <div class="card"><h3>🚀 Run full scRNA-seq analysis</h3>
      <p>One click runs the whole pipeline — FASTQ → count matrix → clustering — then opens AI analysis. Results land in your project.</p>
      <button onclick="send('ghbio.runPipeline')">전체 분석 실행</button></div>
    <div class="card"><h3>🧬 Run step by step</h3>
      <p>Prefer to learn each stage? Run the pipeline one step at a time in the terminal.</p>
      <button class="ghost" onclick="send('workbench.view.extension.ghbio')">Open Tutorials</button></div>
    <div class="card"><h3>🤖 AI Analysis</h3>
      <p>Send your cluster markers &amp; cell types to the LLM and get interpretation + hypotheses. One shot, no wandering.</p>
      <button onclick="send('ghbio.openAI')">Open AI panel</button></div>
    <div class="card"><h3>📁 New project</h3>
      <p>Scaffold a fresh analysis project (data/, results/, notes).</p>
      <button class="ghost" onclick="send('ghbio.newProject')">New project</button></div>
    <div class="card"><h3>❓ 사용설명서</h3>
      <p>처음 쓰시나요? 로그인부터 예제 분석까지 쉬운 한국어로 하나하나 설명합니다.</p>
      <button onclick="send('ghbio.openHelp')">사용설명서 열기</button></div>
  </div>
  <h3 style="margin-top:26px">Installed modules &amp; pipelines</h3>
  <ul>${items || "<li>(none found)</li>"}</ul>
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
