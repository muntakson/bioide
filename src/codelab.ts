import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { loadModules } from "./modules"
import { Pipeline, Codelab, CodelabCell } from "./pipeline"
import { tutorialResultsDir } from "./util"

// =============================================================================
// BioIDE codelab — a webview editor tab that shows a pipeline's ACTUAL code as a
// sequence of cells and hands the user a runnable Google Colab notebook. The cells
// are declared in pipeline.json (`codelab.cells`), so the code on this page is the
// same code emitted into the generated .ipynb (single source of truth).
//
// Colab hand-off: if `codelab.colabUrl` is set the "Open in Colab" button opens that
// hosted notebook directly (one-click). Otherwise we generate the notebook into the
// project's results dir, reveal it, and open Colab's upload page so the user can run
// it there — no hosting required to ship the feature.
// =============================================================================

let panel: vscode.WebviewPanel | undefined

export function openCodelab(context: vscode.ExtensionContext, pipelineId?: string) {
  const found = resolve(context, pipelineId)
  if (!found) {
    vscode.window.showErrorMessage("GHBIO: 이 파이프라인에는 코드랩이 없습니다.")
    return
  }
  const { pipeline } = found
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioCodelab", "GHBIO · Codelab", vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    panel.onDidDispose(() => (panel = undefined))
    panel.webview.onDidReceiveMessage((m) => {
      if (m?.cmd === "openIde") return openInIde(context, m.id)
      if (m?.cmd === "openColab") return openInColab(context, m.id)
      if (m?.cmd === "saveNotebook") return saveAndOpenNotebook(context, m.id)
    })
  }
  panel.title = `GHBIO · ${pipeline.codelab?.title || "Codelab"}`
  panel.webview.html = html(pipeline, pipeline.codelab!)
  panel.reveal()
}

function resolve(
  context: vscode.ExtensionContext,
  pipelineId?: string,
): { pipeline: Pipeline } | undefined {
  const modules = loadModules(context)
  for (const m of modules) {
    const p = m.pipelines.find((pl) => pl.id === pipelineId && pl.codelab?.cells?.length)
    if (p) return { pipeline: p }
  }
  // Fallback: first pipeline that actually declares a codelab.
  for (const m of modules) {
    const p = m.pipelines.find((pl) => pl.codelab?.cells?.length)
    if (p) return { pipeline: p }
  }
  return undefined
}

// ---- Colab hand-off ---------------------------------------------------------

function notebookName(p: Pipeline): string {
  return p.codelab?.notebook || `${p.id}_codelab.ipynb`
}

// Write the generated .ipynb into the project's results dir and return its path.
function writeNotebook(p: Pipeline): string {
  const dir = tutorialResultsDir(p.id)
  fs.mkdirSync(dir, { recursive: true })
  const file = path.join(dir, notebookName(p))
  fs.writeFileSync(file, JSON.stringify(buildIpynb(p.codelab!, p), null, 1))
  return file
}

// The primary "run locally" path: write the notebook into the project and open it in code-server's
// OWN native notebook editor. The user runs it right here — on this box's GPU + ghbio-venv kernel —
// without any Colab round-trip. This reuses the single shared code-server the user is already in
// (same access model as the existing pipeline runner), so it adds no new multi-user surface.
async function openInIde(context: vscode.ExtensionContext, pipelineId?: string) {
  const found = resolve(context, pipelineId)
  if (!found) return
  const file = writeNotebook(found.pipeline)
  const uri = vscode.Uri.file(file)
  try {
    // Prefer the native notebook editor (built-in ipynb type + ms-toolsai.jupyter for execution).
    await vscode.commands.executeCommand("vscode.openWith", uri, "jupyter-notebook")
  } catch {
    await vscode.commands.executeCommand("vscode.open", uri)
  }
  vscode.window.showInformationMessage(
    "노트북이 열렸습니다. 오른쪽 위 '커널 선택(Select Kernel)'에서 'BioIDE (GPU · ghbio-venv)'을 고른 뒤, 각 셀의 ▶ 를 눌러 이 서버에서 직접 실행하세요.",
  )
}

async function openInColab(context: vscode.ExtensionContext, pipelineId?: string) {
  const found = resolve(context, pipelineId)
  if (!found) return
  const p = found.pipeline
  const url = p.codelab?.colabUrl?.trim()
  if (url) {
    // A hosted notebook is configured → one-click open in Colab.
    await vscode.env.openExternal(vscode.Uri.parse(url))
    return
  }
  // No hosted notebook: generate it locally, reveal it, and open Colab's upload flow.
  const file = writeNotebook(p)
  await vscode.commands.executeCommand("vscode.open", vscode.Uri.file(file))
  await vscode.env.openExternal(vscode.Uri.parse("https://colab.research.google.com/#create=true"))
  vscode.window.showInformationMessage(
    `Colab이 열렸습니다 → '업로드(Upload)' 탭에서 방금 생성된 노트북 파일 '${notebookName(p)}' 을 선택하세요. (파일 위치: ${file})`,
  )
}

async function saveAndOpenNotebook(context: vscode.ExtensionContext, pipelineId?: string) {
  const found = resolve(context, pipelineId)
  if (!found) return
  const file = writeNotebook(found.pipeline)
  await vscode.commands.executeCommand("vscode.open", vscode.Uri.file(file))
  vscode.window.showInformationMessage(`노트북을 저장했습니다: ${file}`)
}

// ---- .ipynb generation (nbformat 4) -----------------------------------------

// Split text into an nbformat "source" array: a list of lines each keeping its trailing "\n"
// (except the last). This is the shape Jupyter/Colab expect.
function toSource(text: string): string[] {
  const lines = text.replace(/\n+$/, "").split("\n")
  return lines.map((l, i) => (i < lines.length - 1 ? l + "\n" : l))
}

function buildIpynb(cl: Codelab, p: Pipeline): unknown {
  const cells: unknown[] = []
  const header = [
    `# ${cl.title || p.name} — BioIDE Codelab`,
    "",
    cl.subtitle || "",
    "",
    cl.intro || "",
  ]
    .filter((l, i, a) => !(l === "" && a[i - 1] === "")) // squash double blanks
    .join("\n")
  cells.push({ cell_type: "markdown", metadata: {}, source: toSource(header) })

  for (const c of cl.cells) {
    const md = [c.title ? `## ${c.title}` : "", c.desc || ""].filter(Boolean).join("\n\n")
    if (md) cells.push({ cell_type: "markdown", metadata: {}, source: toSource(md) })
    if (c.code) {
      cells.push({
        cell_type: "code",
        metadata: {},
        execution_count: null,
        outputs: [],
        source: toSource(c.code),
      })
    }
  }

  return {
    nbformat: 4,
    nbformat_minor: 0,
    metadata: {
      colab: { provenance: [], toc_visible: true },
      accelerator: "GPU",
      kernelspec: { name: "python3", display_name: "Python 3" },
      language_info: { name: "python" },
    },
    cells,
  }
}

// ---- rendering --------------------------------------------------------------

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)

// Tiny, dependency-free markdown for the cell descriptions (bold / inline-code / links).
// Server-side (TS), so it dodges the webview template-literal backtick trap entirely.
function mdInline(s: string): string {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2">$1</a>')
}

function cellsHtml(cells: CodelabCell[]): string {
  return cells
    .map((c, i) => {
      const head = c.title ? `<div class="ctitle"><span class="cnum">${i + 1}</span>${esc(c.title)}</div>` : ""
      const desc = c.desc ? `<div class="cdesc">${mdInline(c.desc)}</div>` : ""
      const code = c.code
        ? `<div class="cell"><button class="copy" onclick="copyCode(this)">복사</button><pre><code>${esc(c.code)}</code></pre></div>`
        : ""
      return `<section class="step">${head}${desc}${code}</section>`
    })
    .join("\n")
}

function html(p: Pipeline, cl: Codelab): string {
  const hosted = !!cl.colabUrl?.trim()
  const nb = cl.notebook || `${p.id}_codelab.ipynb`
  const ideHint =
    "권장: 노트북이 <b>BioIDE 안에서 바로</b> 열립니다. 오른쪽 위 <b>커널 선택</b>에서 " +
    "<code>BioIDE (GPU · ghbio-venv)</code> 을 고른 뒤 각 셀의 ▶ 를 눌러 이 서버의 GPU로 실행하세요."
  const colabHint = hosted
    ? "또는 Google Colab에서 열기 — 준비된 Colab 노트북이 새 탭에서 바로 열립니다."
    : `또는 Google Colab에서 실행 — 노트북(<code>${esc(nb)}</code>)이 <code>results/</code> 폴더에 생성되고 Colab이 새 탭에서 열립니다. Colab의 <b>업로드(Upload)</b> 탭에서 그 파일을 선택하세요.`

  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif;
    color: #e6edf3; background: #0d1117; margin: 0; padding: 28px 32px 80px; line-height: 1.65; }
  .wrap { max-width: 900px; margin: 0 auto; }
  .kicker { font-size: 12px; font-weight: 800; letter-spacing: .04em; color: #f0b45a; text-transform: uppercase; }
  h1 { font-size: 26px; margin: 6px 0 6px; }
  .sub { color: #8b98a5; font-size: 14.5px; margin: 0 0 18px; }
  .intro { background: #12181f; border: 1px solid #253039; border-radius: 12px; padding: 14px 18px;
    color: #c9d4de; font-size: 14px; margin-bottom: 20px; }
  .cta { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 4px 0 8px; }
  button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 8px;
    font-weight: 700; padding: 11px 18px; border-radius: 10px; font-size: 14px; }
  .runhere { background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a; box-shadow: 0 2px 12px rgba(45,212,191,.3); }
  .runhere:hover { filter: brightness(1.06); }
  .colab { background: linear-gradient(135deg,#f9ab00,#f57c00); color: #201400; box-shadow: 0 2px 12px rgba(245,124,0,.3); }
  .colab:hover { filter: brightness(1.06); }
  .ghost { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  .colabnote { font-size: 12.5px; color: #8b98a5; margin: 2px 0 26px; }
  .colabnote code { background: #1b232c; padding: 1px 5px; border-radius: 5px; color: #9fe6d6; }
  .step { margin: 0 0 22px; }
  .ctitle { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700; color: #7ee7d6; margin-bottom: 6px; }
  .cnum { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px;
    background: #10261f; border: 1px solid #1f6f57; color: #2dd4bf; border-radius: 50%; font-size: 12.5px; font-weight: 800; flex: none; }
  .cdesc { color: #c9d4de; font-size: 14px; margin: 0 0 8px 34px; }
  .cdesc code { background: #1b232c; padding: 1px 5px; border-radius: 5px; color: #9fe6d6; font-size: 13px; }
  .cdesc a { color: #2dd4bf; }
  .cell { position: relative; margin-left: 34px; }
  .cell pre { margin: 0; background: #0b0f14; border: 1px solid #253039; border-radius: 10px; padding: 14px 16px;
    overflow-x: auto; font-size: 13px; line-height: 1.55; }
  .cell code { font-family: Menlo, Monaco, "Courier New", monospace; color: #d6e2ea; white-space: pre; }
  .copy { position: absolute; top: 8px; right: 10px; background: #1b232c; color: #9fb3c0; border: 1px solid #30363d;
    padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 6px; }
  .copy:hover { background: #232d38; color: #e6edf3; }
  .foot { margin-top: 30px; color: #6e7b8a; font-size: 12.5px; border-top: 1px solid #1b232c; padding-top: 14px; }
</style></head><body><div class="wrap">
  <div class="kicker">BioIDE Codelab</div>
  <h1>${esc(cl.title || p.name)}</h1>
  <div class="sub">${esc(cl.subtitle || "이 튜토리얼의 실제 분석 코드를 단계별로 보고, Google Colab에서 직접 실행해 보세요.")}</div>
  ${cl.intro ? `<div class="intro">${mdInline(cl.intro)}</div>` : ""}

  <div class="cta">
    <button class="runhere" onclick="send('openIde')">🚀 이 서버에서 바로 실행 (BioIDE 노트북 열기)</button>
    <button class="colab" onclick="send('openColab')">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#F9AB00"/><circle cx="12" cy="12" r="4.4" fill="#0d1117"/></svg>
      Google Colab에서 열기
    </button>
  </div>
  <div class="colabnote">${ideHint}<br>${colabHint}</div>

  ${cellsHtml(cl.cells)}

  <div class="foot">이 코드는 이 파이프라인의 실제 분석과 동일한 알고리즘입니다. 큰 원본 데이터 대신 Colab에서 바로 받을 수 있는 공개 데이터로 동작하도록 구성되어, 노트북을 그대로 실행할 수 있습니다.</div>
</div>
<script>
  var vscode = acquireVsCodeApi()
  var PID = ${JSON.stringify(p.id)}
  function send(cmd){ vscode.postMessage({ cmd: cmd, id: PID }) }
  function copyCode(btn){
    var code = btn.parentElement.querySelector('code').innerText
    navigator.clipboard.writeText(code).then(function(){
      var old = btn.innerText; btn.innerText = '복사됨 ✓'
      setTimeout(function(){ btn.innerText = old }, 1400)
    })
  }
</script>
</body></html>`
}
