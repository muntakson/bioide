import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import * as os from "os"
import { loadModules, Module } from "./modules"
import { Pipeline, stageComplete, stageTracked } from "./pipeline"
import { tutorialProjectDir, tutorialResultsDir, projectsDir } from "./util"

// =============================================================================
// The DASHBOARD — a PlatformIO-Home-style overview, rendered as a webview editor
// tab (NOT a sidebar replacement, which VS Code doesn't support cleanly).
//
// A tutorial IS a project (a pipeline scaffolds ~/…/projects/<id>/ via ensureProject),
// so ONE renderer serves both: a tutorial adds a step checklist, library status, and
// context-aware Help on top of the plain project view (files + folder).
// =============================================================================

let panel: vscode.WebviewPanel | undefined
let last: { context: vscode.ExtensionContext; target?: DashboardTarget } | undefined

export type DashboardTarget = string | { kind: "tutorial" | "project"; id: string; dir?: string }

export function openDashboard(context: vscode.ExtensionContext, target?: DashboardTarget) {
  last = { context, target }
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioDashboard", "GHBIO · Dashboard", vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    panel.onDidDispose(() => (panel = undefined))
    panel.webview.onDidReceiveMessage((m) => {
      if (m?.cmd) vscode.commands.executeCommand(m.cmd, ...(m.args ?? []))
    })
  }
  renderInto(panel)
  panel.reveal()
}

// Re-render the open dashboard in place (no focus steal) so step status —
// especially "실행 중…" / "완료" — reflects tasks starting and finishing.
export function refreshDashboard() {
  if (panel) renderInto(panel)
}

function renderInto(p: vscode.WebviewPanel) {
  if (!last) return
  const view = resolve(loadModules(last.context), last.target)
  p.title = `GHBIO · ${view.name}`
  p.webview.html = html(view)
}

// ---- view model -------------------------------------------------------------

interface StepView {
  id: string
  badge: string
  title: string
  ko?: string
  tracked: boolean
  done: boolean
  running: boolean
}
interface FileView {
  name: string
  path: string
  size: number
}
interface LibView {
  id: string
  name: string
  desc?: string
  installed: boolean
}
interface DashboardView {
  kind: "tutorial" | "project"
  id: string
  name: string
  summary?: string
  dir: string
  pipelineId?: string
  steps: StepView[]
  done: number
  total: number
  results: FileView[]
  libraries: LibView[]
  hasHelp: boolean
}

function resolve(modules: Module[], target?: DashboardTarget): DashboardView {
  // Normalize target → a pipeline (tutorial) or a project dir.
  let pipelineId: string | undefined
  let projectDir: string | undefined
  if (typeof target === "string") pipelineId = target
  else if (target?.kind === "project") projectDir = target.dir ?? path.join(projectsDir(), target.id)
  else if (target?.kind === "tutorial") pipelineId = target.id

  if (pipelineId) {
    for (const m of modules) {
      const p = m.pipelines.find((pl) => pl.id === pipelineId)
      if (p) return tutorialView(m, p)
    }
  }
  if (projectDir) return projectView(projectDir)

  // Fallback: first tutorial, else an empty prompt.
  const first = modules.find((m) => m.pipelines.length)
  if (first) return tutorialView(first, first.pipelines[0])
  return {
    kind: "project",
    id: "-",
    name: "GHBIO",
    dir: projectsDir(),
    steps: [],
    done: 0,
    total: 0,
    results: [],
    libraries: [],
    hasHelp: false,
  }
}

function tutorialView(m: Module, p: Pipeline): DashboardView {
  const runningNames = new Set(vscode.tasks.taskExecutions.map((e) => e.task.name))
  const steps: StepView[] = p.stages.map((s) => ({
    id: s.id,
    badge: (s.title.split(".")[0] || "•").trim(),
    title: s.title,
    ko: s.ko,
    tracked: stageTracked(s),
    done: stageComplete(p.id, s) === true,
    running: runningNames.has(`GHBIO: ${s.title.replace(/"/g, "")}`),
  }))
  const trackedSteps = steps.filter((s) => s.tracked)
  const libraries: LibView[] = (m.libraries ?? []).map((l) => ({
    id: l.id,
    name: l.name,
    desc: l.desc,
    installed: fs.existsSync(expand(l.presentPath)),
  }))
  return {
    kind: "tutorial",
    id: p.id,
    name: p.name,
    summary: p.summary,
    dir: tutorialProjectDir(p.id),
    pipelineId: p.id,
    steps,
    done: trackedSteps.filter((s) => s.done).length,
    total: trackedSteps.length,
    results: listFiles(tutorialResultsDir(p.id)),
    libraries,
    hasHelp: !!p.help,
  }
}

function projectView(dir: string): DashboardView {
  return {
    kind: "project",
    id: path.basename(dir),
    name: path.basename(dir),
    summary: readSummary(dir),
    dir,
    steps: [],
    done: 0,
    total: 0,
    results: listFiles(path.join(dir, "results")),
    libraries: [],
    hasHelp: false,
  }
}

function listFiles(dir: string): FileView[] {
  if (!fs.existsSync(dir)) return []
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => {
      const full = path.join(dir, e.name)
      return { name: e.name, path: full, size: safeSize(full) }
    })
    .sort((a, b) => a.name.localeCompare(b.name))
}

function safeSize(f: string): number {
  try {
    return fs.statSync(f).size
  } catch {
    return 0
  }
}

function readSummary(dir: string): string | undefined {
  const notes = path.join(dir, "notes.md")
  if (!fs.existsSync(notes)) return undefined
  const lines = fs.readFileSync(notes, "utf8").split("\n")
  return lines.find((l) => l.trim() && !l.startsWith("#"))?.trim()
}

function expand(p: string): string {
  if (p === "~") return os.homedir()
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2))
  return p
}

// ---- rendering --------------------------------------------------------------

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)

function humanSize(n: number): string {
  if (n >= 1 << 30) return (n / (1 << 30)).toFixed(1) + " GB"
  if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + " MB"
  if (n >= 1 << 10) return (n / (1 << 10)).toFixed(0) + " KB"
  return n + " B"
}

function html(v: DashboardView): string {
  const isTut = v.kind === "tutorial"
  const pct = v.total ? Math.round((v.done / v.total) * 100) : 0

  const stepRows = v.steps
    .map((s) => {
      const icon = s.running ? "⏳" : s.done ? "✓" : s.tracked ? "○" : "·"
      const cls = s.running ? "running" : s.done ? "done" : s.tracked ? "todo" : "untracked"
      const label = esc(s.ko || s.title)
      const tag = s.running
        ? `<span class="tag run">실행 중…</span>`
        : s.done
          ? `<span class="tag ok">완료</span>`
          : ""
      const clickable = v.pipelineId
        ? ` onclick="send('ghbio.runStepById','${esc(v.pipelineId)}','${esc(s.id)}')" title="${s.running ? "실행 중 — 끝날 때까지 기다리세요" : "이 단계 실행"}"`
        : ""
      return (
        `<div class="step ${cls}"${clickable}>` +
        `<span class="mark">${icon}</span>` +
        `<span class="badge">${esc(s.badge)}</span>` +
        `<span class="lbl">${label}</span>${tag}` +
        `</div>`
      )
    })
    .join("\n")

  const fileRows = v.results.length
    ? v.results
        .map(
          (f) =>
            `<div class="file" onclick="send('ghbio.openResult','${esc(f.path)}')" title="열기">` +
            `<span class="fn">${esc(f.name)}</span><span class="fs">${humanSize(f.size)}</span></div>`,
        )
        .join("\n")
    : `<div class="empty">아직 생성된 결과 파일이 없습니다. 파이프라인 단계를 실행하면 여기에 나타납니다.</div>`

  const libRows = v.libraries.length
    ? v.libraries
        .map(
          (l) =>
            `<div class="lib"><span class="dot ${l.installed ? "on" : "off"}"></span>` +
            `<span class="ln">${esc(l.name)}</span>` +
            `<span class="ld">${esc(l.desc ?? "")}</span>` +
            (l.installed
              ? `<span class="ok">설치됨</span>`
              : `<button class="mini" onclick="send('ghbio.installLibrary',{id:'${esc(l.id)}'})">설치</button>`) +
            `</div>`,
        )
        .join("\n")
    : ""

  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif;
    color: #e6edf3; background: #0d1117; margin: 0; padding: 26px 30px 70px; line-height: 1.6; }
  .top { display: flex; align-items: center; gap: 12px; }
  .kind { font-size: 12px; font-weight: 800; padding: 3px 10px; border-radius: 20px;
    background: ${isTut ? "#10261f" : "#161e27"}; color: ${isTut ? "#2dd4bf" : "#8b98a5"};
    border: 1px solid ${isTut ? "#1f6f57" : "#30363d"}; }
  h1 { font-size: 25px; margin: 0; }
  .sum { color: #8b98a5; margin: 6px 0 20px; font-size: 14px; }
  .row { display: grid; grid-template-columns: 1.15fr 1fr; gap: 18px; align-items: start; }
  @media (max-width: 760px){ .row { grid-template-columns: 1fr; } }
  .card { background: #12181f; border: 1px solid #253039; border-radius: 12px; padding: 16px 18px; margin-bottom: 18px; }
  .card h2 { font-size: 15px; margin: 0 0 12px; color: #7ee7d6; display:flex; justify-content:space-between; align-items:center; }
  .bar { height: 8px; background: #21313a; border-radius: 6px; overflow: hidden; margin: 2px 0 12px; }
  .bar > i { display:block; height:100%; width:${pct}%; background: linear-gradient(90deg,#2dd4bf,#22d3ee); }
  .pcount { font-size: 13px; color: #b6c2cf; font-weight: 600; }
  .step { display:flex; align-items:center; gap:10px; padding:7px 8px; border-radius:8px; cursor:pointer; }
  .step:hover { background:#182029; }
  .step .mark { width:16px; text-align:center; font-weight:800; }
  .step.done .mark { color:#3fb950; }
  .step.todo .mark { color:#6e7b8a; }
  .step.untracked { cursor:pointer; }
  .step.untracked .mark { color:#3a4650; }
  .step.running { background:#1b2a20; }
  .step.running .mark { color:#e2b341; }
  .step .badge { min-width:26px; text-align:center; font-size:11px; font-weight:800; color:#06121a;
    background:#2dd4bf; border-radius:6px; padding:1px 4px; }
  .step .lbl { font-size:13.5px; flex:1; }
  .tag { font-size:11px; font-weight:700; padding:1px 8px; border-radius:10px; }
  .tag.run { color:#e2b341; background:#2e2311; border:1px solid #6b5320; }
  .tag.ok { color:#3fb950; background:#10261a; border:1px solid #1f5c39; }
  .file { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:7px 9px;
    border-radius:8px; cursor:pointer; font-size:13px; }
  .file:hover { background:#182029; }
  .file .fn { color:#9fe6d6; } .file .fs { color:#6e7b8a; font-size:12px; }
  .empty { color:#6e7b8a; font-size:13px; padding:6px 2px; }
  .lib { display:flex; align-items:center; gap:9px; padding:7px 4px; font-size:13px; border-top:1px solid #1b232c; }
  .lib:first-child { border-top:none; }
  .dot { width:9px; height:9px; border-radius:50%; flex:none; }
  .dot.on { background:#3fb950; } .dot.off { background:#f0883e; }
  .lib .ln { font-weight:600; } .lib .ld { color:#6e7b8a; flex:1; font-size:12px; }
  .lib .ok { color:#3fb950; font-size:12px; }
  .btns { display:flex; flex-wrap:wrap; gap:10px; margin: 4px 0 22px; }
  button { all:unset; cursor:pointer; display:inline-flex; align-items:center; gap:6px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color:#06121a; font-weight:700;
    padding:8px 15px; border-radius:8px; font-size:13.5px; }
  button.ghost { background:#21262d; color:#e6edf3; border:1px solid #30363d; }
  button.mini { padding:3px 10px; font-size:12px; }
  .path { color:#6e7b8a; font-size:12px; margin-top:4px; word-break:break-all; }
  a { color:#2dd4bf; }
</style></head><body>
  <div class="top">
    <span class="kind">${isTut ? "TUTORIAL" : "PROJECT"}</span>
    <h1>${esc(v.name)}</h1>
  </div>
  <div class="sum">${esc(v.summary ?? (isTut ? "GHBIO 예제 분석" : "GHBIO 분석 프로젝트"))}</div>

  <div class="btns">
    ${isTut ? `<button onclick="send('ghbio.runPipeline','${esc(v.pipelineId)}')">▶▶ 전체 분석 실행</button>` : ""}
    ${isTut && v.hasHelp ? `<button class="ghost" onclick="send('ghbio.openHelp')">❓ 사용설명서</button>` : ""}
    <button class="ghost" onclick="send('ghbio.openProject','${esc(v.dir)}')">📁 프로젝트 폴더 열기</button>
    <button class="ghost" onclick="send('ghbio.openHome')">← 대시보드 홈</button>
  </div>

  <div class="row">
    <div>
      ${
        isTut
          ? `<div class="card">
        <h2>파이프라인 진행 <span class="pcount">${v.done} / ${v.total} 결과 단계 완료</span></h2>
        <div class="bar"><i></i></div>
        ${stepRows}
        <div class="path"><b>✓</b> 완료(파일 있음) · <b>○</b> 아직 안 함 · <b>·</b> 확인 대상 아님(예: AI 단계) · <b>⏳</b> 실행 중. 각 줄을 누르면 그 단계를 실행합니다.</div>
      </div>`
          : ""
      }
      <div class="card">
        <h2>생성된 결과 파일 <span class="pcount">${v.results.length}</span></h2>
        ${fileRows}
        <div class="path">${esc(v.dir)}/results</div>
      </div>
    </div>
    <div>
      ${
        isTut
          ? `<div class="card"><h2>라이브러리(도구) 상태</h2>${libRows || '<div class="empty">이 모듈에 등록된 라이브러리가 없습니다.</div>'}</div>`
          : ""
      }
      <div class="card">
        <h2>다음에 할 일</h2>
        <div class="empty" style="color:#b6c2cf">
          ${
            isTut
              ? "왼쪽 GHBIO → Pipelines 에서 다음 단계를 누르거나, 위의 <b>전체 분석 실행</b>을 눌러 이어서 진행하세요. 처음이라면 <b>사용설명서</b>부터 보세요."
              : "이 프로젝트 폴더를 열어 분석을 진행하세요. 예제부터 익히려면 대시보드 홈에서 튜토리얼을 선택하세요."
          }
        </div>
      </div>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
  </script>
</body></html>`
}
