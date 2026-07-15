import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import * as os from "os"
import { loadModules, Module } from "./modules"
import { Pipeline, stageComplete, stageTracked, DataSource } from "./pipeline"
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
      // The download-status box polls us; reply with the current tar size (fs.stat) for the
      // active pipeline. Everything else is a command relay from a dashboard button.
      if (m?.type === "dlstatus") {
        panel?.webview.postMessage({ type: "dlstatus", ...currentDownloadStatus() })
        return
      }
      if (m?.type === "alignstatus") {
        panel?.webview.postMessage({ type: "alignstatus", ...currentAlignStatus() })
        return
      }
      if (m?.type === "setupstatus") {
        panel?.webview.postMessage({ type: "setupstatus", ...currentSetupStatus() })
        return
      }
      if (m?.type === "runstatus") {
        panel?.webview.postMessage({ type: "runstatus", ...currentRunStatus() })
        return
      }
      if (m?.type === "steplog" && typeof m.id === "string") {
        panel?.webview.postMessage({ type: "steplog", id: m.id, ...currentStepLog(m.id) })
        return
      }
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
  kind?: string
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
  codelab?: { label: string; subtitle?: string }
  dataSource?: DataSource
  // True while the WHOLE-pipeline auto-run task (`GHBIO: <name>`) is executing. Distinct from a
  // per-step task (`GHBIO: <step title>`), so the ▶▶ 전체 분석 실행 button can show "running".
  running?: boolean
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
    kind: s.kind,
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
    codelab: p.codelab?.cells?.length ? { label: p.codelab.label || "BioIDE codelab", subtitle: p.codelab.subtitle } : undefined,
    dataSource: p.dataSource,
    running: runningNames.has(`GHBIO: ${p.name}`),
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

// Live download status for the currently-open dashboard's pipeline, read straight off disk
// (the .tar grows as curl downloads; `extracted` appears once the tar is unpacked). The webview
// polls this and appends a line to the collapsible log under Step 1.
function currentDownloadStatus(): {
  phase: "none" | "download" | "convert" | "done"
  bytes: number
  total: number
  convBytes: number
} {
  const empty = { phase: "none" as const, bytes: 0, total: 0, convBytes: 0 }
  if (!last) return empty
  const dl = resolve(loadModules(last.context), last.target).dataSource?.download
  if (!dl) return empty
  const total = dl.totalBytes ?? 0
  let bytes = 0
  try {
    bytes = fs.statSync(expand(dl.tar)).size
  } catch {
    /* not started */
  }
  if (!dl.convert) {
    // Simple tar download: done once the extracted marker exists.
    const done = !!(dl.extracted && fs.existsSync(expand(dl.extracted)))
    return { phase: done ? "done" : bytes > 0 ? "download" : "none", bytes, total, convBytes: 0 }
  }
  // Download + conversion (e.g. BAM→FASTQ). Still downloading while the .bam is below its total.
  if (total > 0 && bytes < total - 2 * 1024 * 1024) return { phase: "download", bytes, total, convBytes: 0 }
  // BAM complete → converting vs done, judged by the output file's mtime (recent = being written).
  const w = expand(dl.convert.watch)
  for (const cand of [w, w + ".partial"]) {
    try {
      const ws = fs.statSync(cand)
      if (Date.now() - ws.mtimeMs < 15000) return { phase: "convert", bytes, total, convBytes: ws.size }
      if (cand === w) return { phase: "done", bytes, total, convBytes: ws.size } // final, stable ⇒ done
    } catch {
      /* candidate absent */
    }
  }
  return { phase: "convert", bytes, total, convBytes: 0 } // BAM done, conversion just starting
}

// Live STARsolo (count-matrix) status for the align step: the latest line of Log.progress.out, and
// whether the filtered matrix.mtx has been written. The webview polls this and appends new lines.
function currentAlignStatus(): { done: boolean; hasLog: boolean; running: boolean; line: string } {
  const empty = { done: false, hasLog: false, running: false, line: "" }
  if (!last) return empty
  const view = resolve(loadModules(last.context), last.target)
  const starsolo = path.join(view.dir, "results", "starsolo")
  const done = fs.existsSync(path.join(starsolo, "Solo.out", "Gene", "filtered", "matrix.mtx"))
  let line = ""
  let running = false
  try {
    const p = path.join(starsolo, "Log.progress.out")
    const st = fs.statSync(p)
    const prog = fs.readFileSync(p, "utf8").trim().split("\n")
    line = (prog[prog.length - 1] || "").replace(/\s+/g, " ").trim()
    // The log is rewritten every ~20 s while STAR maps; a recent mtime ⇒ actively running, an old
    // one (with no matrix) ⇒ a previous run stopped/failed and this line is stale.
    running = Date.now() - st.mtimeMs < 25000
  } catch {
    /* STARsolo not started yet */
  }
  return { done, hasLog: !!line, running, line }
}

// Whether the WHOLE-pipeline auto-run (▶▶ 전체 분석 실행) task is currently executing, plus a
// coarse label of what it is doing right now. The full-run task is named `GHBIO: <pipeline name>`
// (a per-step task is `GHBIO: <step title>`), and it lives server-side in the code-server backend,
// so this stays accurate after the browser tab is closed and reopened — the whole point of this box.
function currentRunStatus(): { running: boolean; label: string } {
  if (!last) return { running: false, label: "" }
  const view = resolve(loadModules(last.context), last.target)
  const running = vscode.tasks.taskExecutions.some((e) => e.task.name === `GHBIO: ${view.name}`)
  if (!running) return { running: false, label: "" }
  // Best-effort "current phase", read from the same on-disk signals the step boxes poll.
  const dl = currentDownloadStatus()
  if (dl.phase === "download") {
    const pct = dl.total > 0 ? Math.floor((dl.bytes / dl.total) * 100) : 0
    return { running, label: `1단계 다운로드 중… ${pct}%` }
  }
  if (dl.phase === "convert") return { running, label: "1단계 BAM→FASTQ 변환 중…" }
  if (currentAlignStatus().running) return { running, label: "2c STARsolo 정렬 중…" }
  return { running, label: "분석 자동 실행 중…" }
}

// The Maynard reproduction needs a large, one-time legacy R installation. Its setup script
// mirrors terminal output into setup.log; this compact status lets the dashboard make duplicate
// clicks visibly unnecessary without exposing a full terminal transcript.
function currentSetupStatus(): { applicable: boolean; phase: "idle" | "running" | "done" | "stopped"; lines: string[] } {
  const empty = { applicable: false, phase: "idle" as const, lines: [] as string[] }
  if (!last) return empty
  const view = resolve(loadModules(last.context), last.target)
  if (view.pipelineId !== "scrna-seq-therapy-induced-evolution") return empty

  const root = path.join(os.homedir(), "ghbio-venv-r", "maynard-2020")
  const ready = path.join(root, ".ready")
  if (fs.existsSync(ready)) return { applicable: true, phase: "done", lines: ["✓ Setup completed — legacy R/Seurat environment is ready."] }

  let lines: string[] = []
  try {
    lines = fs
      .readFileSync(path.join(root, "setup.log"), "utf8")
      .split("\n")
      .map((line) => line.replace(/\x1b\[[0-9;]*m/g, "").trim())
      .filter(Boolean)
      .slice(-3)
  } catch {
    /* setup has not emitted a log yet */
  }
  const activeTask = vscode.tasks.taskExecutions.some((e) => e.task.name === "GHBIO: 0. Set up legacy R / Seurat environment")
  let hasLock = false
  try {
    hasLock = fs.readdirSync(root, { withFileTypes: true }).some((e) => e.isDirectory() && e.name.startsWith("00LOCK"))
  } catch {
    /* library has not been created */
  }
  if (activeTask || hasLock) {
    return {
      applicable: true,
      phase: "running",
      lines: lines.length ? lines : ["⏳ Installing R packages — please wait; do not run Step 0 again."],
    }
  }
  if (lines.length) return { applicable: true, phase: "stopped", lines: ["⚠ Setup is not active; inspect the last installer messages below.", ...lines].slice(-3) }
  return { applicable: true, phase: "idle", lines: ["· Setup has not started. Click Step 0 once to install the legacy R environment."] }
}

// Tail of a step's debug log (`<results>/.logs/<stepId>.log`, written by stepLogTee) plus
// whether that step's per-step task is currently running. The dashboard's collapsible debug
// console polls this and shows the last ~40 lines so a long step (e.g. rendering the Seurat
// notebooks) is visibly making progress instead of looking frozen.
function currentStepLog(stepId: string): { hasLog: boolean; running: boolean; lines: string[] } {
  const empty = { hasLog: false, running: false, lines: [] as string[] }
  if (!last) return empty
  const view = resolve(loadModules(last.context), last.target)
  const step = view.steps.find((s) => s.id === stepId)
  // "Running" covers both a per-step task and the whole-pipeline auto-run (which drives the
  // same per-step log through stageBlock), so the console keeps polling in either mode.
  const running = !!step?.running || !!view.running
  let lines: string[] = []
  try {
    lines = fs
      .readFileSync(path.join(view.dir, "results", ".logs", `${stepId}.log`), "utf8")
      .split("\n")
      .map((l) => l.replace(/\x1b\[[0-9;]*m/g, "").replace(/\r/g, "").replace(/\s+$/, ""))
      .filter((l) => l.length)
      .slice(-40)
  } catch {
    /* step has not run yet — no log */
  }
  return { hasLog: lines.length > 0, running, lines }
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

// Is this project's folder the currently-open workspace root? (i.e. has the user already clicked
// "프로젝트 폴더 열기", which reloads the workbench with `dir` as the root). Used to make that button
// status-aware: disabled when already open, a warning call-to-action when not.
function isProjectFolderOpen(dir: string): boolean {
  const norm = (p: string) => path.resolve(p).replace(/\/+$/, "")
  const target = norm(dir)
  return (vscode.workspace.workspaceFolders ?? []).some((f) => norm(f.uri.fsPath) === target)
}

function html(v: DashboardView): string {
  const isTut = v.kind === "tutorial"
  const pct = v.total ? Math.round((v.done / v.total) * 100) : 0
  const dirOpen = isProjectFolderOpen(v.dir)
  // Render the first setup state server-side as well as polling it below. This avoids a blank
  // "checking" console if a webview was restored while its first message is still in flight.
  const setupInitial = v.pipelineId === "scrna-seq-therapy-induced-evolution" ? currentSetupStatus() : undefined
  const setupLabel =
    setupInitial?.phase === "done"
      ? "✓ completed"
      : setupInitial?.phase === "running"
        ? "⏳ running — do not click Step 0 again"
        : setupInitial?.phase === "stopped"
          ? "⚠ stopped/failed"
          : "· not started"
  const setupText = setupInitial?.lines?.length ? esc(setupInitial.lines.join("\n")) : "상태 확인 중…"
  // First button in the row: open the project folder. Disabled once it's the open workspace root;
  // otherwise a pulsing warning telling the user to open it before proceeding.
  const openBtn = dirOpen
    ? `<button class="open-ok" disabled title="이 프로젝트 폴더가 이미 열려 있습니다">📁 프로젝트 폴더 열림 ✓ (Opened)</button>`
    : `<button class="open-warn" onclick="send('ghbio.openProject','${esc(v.dir)}')" title="분석을 진행하기 전에 먼저 이 프로젝트 폴더를 여세요">⚠ 먼저 프로젝트 폴더 열기 (Open project folder first!)</button>`

  // Last card in the list: project info with a "data source" section (declared in pipeline.json).
  const ds = v.dataSource
  const dsCard = ds
    ? `<div class="card">
        <h2>프로젝트 정보 (Project info)</h2>
        <div class="ds-sub">데이터 출처 (Data source)</div>
        <dl class="ds">
          ${ds.provider ? `<dt>제공 (Provider)</dt><dd><span class="pill">${esc(ds.provider)}</span></dd>` : ""}
          ${ds.dataset ? `<dt>데이터셋 (Dataset)</dt><dd>${esc(ds.dataset)}</dd>` : ""}
          ${ds.size ? `<dt>크기 (Size)</dt><dd>${esc(ds.size)}</dd>` : ""}
          ${ds.datasetUrl ? `<dt>데이터셋 페이지</dt><dd><a href="${esc(ds.datasetUrl)}">${esc(ds.datasetUrl)}</a></dd>` : ""}
          ${ds.fastqUrl ? `<dt>FASTQ 다운로드</dt><dd><a href="${esc(ds.fastqUrl)}">${esc(ds.fastqUrl)}</a></dd>` : ""}
          <dt>작업 폴더 (Work folder)</dt><dd>${esc(v.dir)}</dd>
          ${ds.note ? `<dt>비고 (Note)</dt><dd>${esc(ds.note)}</dd>` : ""}
        </dl>
        ${
          ds.rationale
            ? `<div class="ds-sub" style="margin-top:16px">선정 이유 (Why this paper)</div>
               <div class="ds-why">${esc(ds.rationale)}</div>`
            : ""
        }
      </div>`
    : ""

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
      const stepDiv =
        `<div class="step ${cls}"${clickable}>` +
        `<span class="mark">${icon}</span>` +
        `<span class="badge">${esc(s.badge)}</span>` +
        `<span class="lbl">${label}</span>${tag}` +
        `</div>`
      // Collapsible live download log, directly under the download step (only when this pipeline
      // declares a download target). The <pre> is filled by the polling script below.
      const dlBox =
        s.id === "download" && v.dataSource?.download
          ? `<details id="dlbox" class="dlbox" open>
               <summary>⬇ 다운로드 상태 (Download status) — 자동 새로고침 <span class="qmark" onclick="event.preventDefault()">?<span class="qtip" id="dltip">불러오는 중…</span></span></summary>
               <pre id="dllog">상태 확인 중…</pre>
             </details>`
          : ""
      // Collapsible live STARsolo progress log, directly under the count-matrix (align) step.
      const alignBox =
        s.id === "align"
          ? `<details id="alignbox" class="dlbox" open>
               <summary>⏳ count matrix 진행 상태 (STARsolo) — 자동 새로고침</summary>
               <pre id="alignlog">상태 확인 중…</pre>
             </details>`
          : ""
      const setupBox =
        s.id === "setup" && v.pipelineId === "scrna-seq-therapy-induced-evolution"
          ? `<details id="setupbox" class="dlbox setupbox" open>
               <summary>${setupLabel} — 환경 설정 상태 (Setup debug) · 자동 새로고침</summary>
               <pre id="setuplog">${setupText}</pre>
             </details>`
          : ""
      // Generic per-step debug console for every runnable step that lacks a specialised box
      // (the download/align/setup boxes above already show their own progress). It tails the
      // step's .logs/<id>.log so a long-running step shows live output. Opens automatically
      // while the step is running; otherwise collapsed to keep the checklist tidy.
      const hasSpecialBox = !!dlBox || !!alignBox || !!setupBox
      const debugBox =
        v.pipelineId && s.kind !== "ai" && !hasSpecialBox
          ? `<details id="debugbox-${esc(s.id)}" class="dlbox debugbox" data-step="${esc(s.id)}"${s.running ? " open" : ""}>
               <summary>🐞 디버그 콘솔 (progress log) · 자동 새로고침</summary>
               <pre id="debuglog-${esc(s.id)}">${s.running ? "실행 로그를 불러오는 중…" : "이 단계를 실행하면 진행 로그가 여기에 표시됩니다."}</pre>
             </details>`
          : ""
      return stepDiv + setupBox + dlBox + alignBox + debugBox
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
  .row > div { min-width: 0; } /* let grid tracks shrink below content so a long line can't widen them */
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
  button.paperbtn { margin-top:12px; width:100%; justify-content:center; background:linear-gradient(135deg,#7c3aed,#2563eb); color:#fff; font-weight:700; padding:9px 14px; }
  button.paperbtn.pdf { margin-top:8px; background:linear-gradient(135deg,#be123c,#7c3aed); }
  button.paperbtn.hs { margin-top:8px; background:linear-gradient(135deg,#f59e0b,#eab308); color:#3a2a00; }
  button.paperbtn:hover { filter:brightness(1.08); }
  /* BioIDE codelab card — Colab-flavored amber */
  .codelab-card { border-color:#3a3320; background:linear-gradient(180deg,#171410,#12181f); }
  button.codelabbtn { margin-top:12px; width:100%; justify-content:center; padding:9px 14px;
    background:linear-gradient(135deg,#f9ab00,#f57c00); color:#201400; font-weight:800; }
  button.codelabbtn:hover { filter:brightness(1.06); }
  button[disabled] { cursor:default; opacity:.6; }
  /* Open-project button, status-aware */
  button.open-warn { background: linear-gradient(135deg,#f5b73d,#f0883e); color:#2a1705; font-weight:800;
    box-shadow:0 0 0 0 rgba(240,136,62,.5); animation: pulse 1.8s ease-out infinite; }
  button.open-warn:hover { filter:brightness(1.06); }
  button.open-ok { background:#12312b; color:#7ee7d6; border:1px solid #1f5a4f; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(240,136,62,.5)} 70%{box-shadow:0 0 0 8px rgba(240,136,62,0)} 100%{box-shadow:0 0 0 0 rgba(240,136,62,0)} }
  /* ▶▶ 전체 분석 실행 while the whole-pipeline task is running: keep it visibly "alive" (animated
     gradient sweep + glow) even though it's disabled, so a returning user sees work is in progress. */
  button.running { background:linear-gradient(110deg,#f59e0b,#f0883e,#f59e0b); background-size:200% 100%;
    color:#2a1705; font-weight:800; opacity:1; cursor:default;
    animation: runsweep 1.4s linear infinite, pulse 1.8s ease-out infinite; }
  @keyframes runsweep { 0%{background-position:0% 0} 100%{background-position:200% 0} }
  .runlabel { display:flex; align-items:center; gap:8px; margin:-14px 0 20px; font-size:12.5px; color:#f0b458; font-weight:600; }
  .runlabel .spin { width:13px; height:13px; border-radius:50%; border:2px solid rgba(240,180,88,.35);
    border-top-color:#f0b458; display:inline-block; flex:none; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg) } }
  .path { color:#6e7b8a; font-size:12px; margin-top:4px; word-break:break-all; }
  a { color:#2dd4bf; }
  /* Download status box (under Step 1) */
  .dlbox { margin:2px 0 8px 30px; border:1px solid #253039; border-radius:8px; background:#0b0f14; overflow:hidden; }
  .dlbox > summary { cursor:pointer; padding:6px 10px; font-size:12.5px; color:#7ee7d6; user-select:none; list-style:none; }
  .dlbox > summary::-webkit-details-marker { display:none; }
  .dlbox[open] > summary { border-bottom:1px solid #253039; }
  /* Fixed ~4-line viewport that never grows: keeps full history, new lines append at the bottom,
     scroll up to see older. overflow-x hidden + wrap so a long line can't widen the box. */
  .dlbox pre { margin:0; padding:8px 10px; height:6em; overflow-y:auto; overflow-x:hidden; font-size:12px;
    line-height:1.5; color:#b6c2cf; font-family:Menlo,Monaco,"Courier New",monospace;
    white-space:pre-wrap; overflow-wrap:anywhere; }
  /* The legacy-R setup box is deliberately only three lines tall: enough to show progress while
     preserving the tutorial checklist as the primary interface. */
  .setupbox pre { height:4.5em; }
  /* The generic debug console gets a taller viewport (≈10 lines) since it streams a full step's
     stdout, and a distinct summary tint so it reads as "developer detail", not a required step. */
  .debugbox > summary { color:#c8923a; }
  .debugbox pre { height:15em; }
  /* "?" help icon with a hover popup explaining the current step + time estimate */
  .qmark { display:inline-block; width:15px; height:15px; line-height:15px; text-align:center; border-radius:50%;
    background:#21313a; color:#7ee7d6; font-size:11px; font-weight:700; cursor:help; position:relative; }
  .qmark > .qtip { visibility:hidden; opacity:0; position:absolute; z-index:20; left:20px; top:-6px; width:290px;
    background:#0d1117; border:1px solid #30516e; border-radius:8px; padding:9px 11px; color:#e6edf3; font-size:12px;
    font-weight:400; line-height:1.55; text-align:left; white-space:normal; box-shadow:0 6px 20px rgba(0,0,0,.55);
    transition:opacity .12s; pointer-events:none; }
  .qmark:hover > .qtip { visibility:visible; opacity:1; }
  .qtip b { color:#7ee7d6; }
  /* Project info card */
  .ds-sub { font-size:12px; font-weight:800; letter-spacing:.02em; color:#7ee7d6; text-transform:uppercase; margin:2px 0 8px; }
  .ds-why { font-size:13px; line-height:1.65; color:#c9d4de; white-space:pre-line; }
  .ds { display:grid; grid-template-columns:auto 1fr; gap:5px 12px; font-size:13px; align-items:baseline; }
  .ds dt { color:#8b98a5; white-space:nowrap; }
  .ds dd { margin:0; color:#e6edf3; word-break:break-all; }
  .ds dd a { word-break:break-all; }
  .ds .pill { display:inline-block; font-size:11px; font-weight:700; color:#06121a; background:#2dd4bf; border-radius:10px; padding:1px 8px; }
</style></head><body>
  <div class="top">
    <span class="kind">${isTut ? "TUTORIAL" : "PROJECT"}</span>
    <h1>${esc(v.name)}</h1>
  </div>
  <div class="sum">${esc(v.summary ?? (isTut ? "GHBIO 예제 분석" : "GHBIO 분석 프로젝트"))}</div>

  <div class="btns">
    ${openBtn}
    ${
      isTut
        ? `<button id="runbtn" class="${v.running ? "running" : ""}"${v.running ? " disabled" : ""} onclick="send('ghbio.runPipeline','${esc(v.pipelineId)}')">${v.running ? "⏳ 전체 분석 실행 중…" : "▶▶ 전체 분석 실행"}</button>`
        : ""
    }
    ${isTut && v.hasHelp ? `<button class="ghost" onclick="send('ghbio.openHelp')">❓ 사용설명서</button>` : ""}
    <button class="ghost" onclick="send('ghbio.openHome')">← 대시보드 홈</button>
  </div>
  ${
    isTut
      ? `<div id="runlabel" class="runlabel"${v.running ? "" : ' style="display:none"'}>
           <span class="spin"></span>
           <span id="runlabeltext">자동 실행 중… 창을 닫아도 서버에서 계속 진행됩니다. 아래 단계 로그에서 진행 상황을 확인하세요.</span>
         </div>`
      : ""
  }

  <div class="row">
    <div>
      ${
        isTut
          ? `<div class="card">
        <h2>파이프라인 진행 <span class="pcount">${v.done} / ${v.total} 결과 단계 완료</span></h2>
        <div class="bar"><i></i></div>
        ${stepRows}
        <div class="path"><b>✓</b> 완료(파일 있음) · <b>○</b> 아직 안 함 · <b>·</b> 확인 대상 아님(예: AI 단계) · <b>⏳</b> 실행 중. 각 줄을 누르면 그 단계를 실행합니다.</div>
        <button class="paperbtn" onclick="send('ghbio.writePaper','${esc(v.pipelineId)}','edu')" title="BioIDE의 교육적 가치에 초점을 둔 한국생물교육학회 제출용 과학교육 논문을 AI로 작성 (파일: ${esc(v.pipelineId)}_edu_paper.md/.pdf)">📝 과학교육 논문 (한국생물교육학회 제출용)</button>
        <button class="paperbtn pdf" onclick="send('ghbio.writePaper','${esc(v.pipelineId)}','research')" title="동일 공개 원자료를 BioIDE로 독립 재처리한 결과(그림·표·수치)와 원 저자 결론 비교를 담은 생물정보학 재현 연구 논문을 AI로 작성 (파일: ${esc(v.pipelineId)}_research_paper.md/.pdf)">🔬 생물정보학 재현 논문 · PDF (그림·데이터·원논문 비교)</button>
        <button class="paperbtn hs" onclick="send('ghbio.writePaper','${esc(v.pipelineId)}','research_hs')" title="생물정보학 재현 논문을 고등학생도 이해할 수 있게 비유를 써서 다시 씁니다. 모든 표·그림(Figure 1B~5)을 포함하고 각 표·그림마다 자세한 설명을 붙입니다 (파일: ${esc(v.pipelineId)}_research_hs_paper.md/.pdf)">🎓 생물정보학 재현 논문 · 고등학생용 (비유·모든 그림·표 설명)</button>
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
      ${
        isTut && v.codelab
          ? `<div class="card codelab-card">
        <h2>💻 ${esc(v.codelab.label)}</h2>
        <div class="empty" style="color:#c9d4de">${esc(v.codelab.subtitle || "이 튜토리얼의 실제 분석 코드를 단계별로 보고, 이 서버(또는 Google Colab)에서 직접 실행해 보세요.")}</div>
        <button class="codelabbtn" onclick="send('ghbio.openCodelab','${esc(v.pipelineId)}')">코드랩 열기 · 서버/Colab에서 실행 →</button>
      </div>`
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

  ${dsCard}

  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }

    // ---- Download-status poller (Step 1 collapsible log) --------------------
    // Every few seconds we ask the extension for the .tar size on disk and append a timestamped
    // line. State is persisted (getState/setState) so the log survives dashboard re-renders and
    // tab reloads. Polling continues while collapsed so history accumulates; it stops when done.
    (function(){
      const box = document.getElementById('dlbox')
      const logEl = document.getElementById('dllog')
      if (!box || !logEl) return
      const GB = 1073741824
      const fmt = b => (b/GB).toFixed(2) + ' GB'
      const st = vscode.getState() || {}
      let lines = st.dlLines || []
      let last = st.dlLast || 0
      let stopped = false
      // Show the full log; append newest at the bottom. Auto-scroll to the bottom only when the
      // user is already there, so scrolling up to read history isn't yanked back down.
      function paint(){
        const stick = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 20
        logEl.textContent = lines.length ? lines.join('\\n') : '상태 확인 중…'
        if (stick) logEl.scrollTop = logEl.scrollHeight
      }
      function save(){ vscode.setState(Object.assign(vscode.getState()||{}, { dlLines: lines, dlLast: last })) }
      function push(line){ lines.push(line); if(lines.length>500) lines = lines.slice(-500); save(); paint() }
      paint()

      // Hover-popup ("?" icon): explain the phase + estimate remaining time from the observed rate.
      const tip = document.getElementById('dltip')
      let dlPB=null, dlPT=null, cvPB=null, cvPT=null
      function estMin(remBytes, rateBps){ return rateBps>0 ? Math.max(1, Math.round(remBytes/rateBps/60)) : null }
      function updateTip(m){
        if (!tip) return
        const now = Date.now()
        let h = '<b>1단계: 다운로드 + FASTQ 변환</b><br>공개 폐암 10x <b>BAM(약 8.6GB)</b>을 내려받은 뒤, 그 안의 세포 바코드로 <b>원본 FASTQ를 복원</b>합니다.<br><br>'
        if (m.phase === 'done'){ h += '✓ <b>완료</b> — 이제 2c(count matrix)를 실행할 수 있습니다.' }
        else if (m.phase === 'convert'){
          let eta = '수십 분'
          if (cvPB!==null && now>cvPT && m.convBytes>cvPB){
            const rate=(m.convBytes-cvPB)/((now-cvPT)/1000)
            const mm=estMin(Math.max(0, 3.3*GB - m.convBytes), rate); if(mm) eta='약 '+mm+'분'
          }
          cvPB=m.convBytes; cvPT=now
          h += '🔄 <b>FASTQ 변환 중</b>: 약 '+(m.convBytes/GB).toFixed(2)+' GB 생성됨<br>남은 예상 시간: <b>'+eta+'</b><br><span style="color:#8b98a5">ARM에서는 빠른 변환 도구(Cell Ranger)를 못 써서 순수 파이썬으로 처리해 다소 느립니다.</span>'
        }
        else if (m.phase === 'download'){
          const pct=m.total?(100*m.bytes/m.total).toFixed(0):'?'
          let eta='계산 중…', spd=''
          if (dlPB!==null && now>dlPT && m.bytes>dlPB){
            const rate=(m.bytes-dlPB)/((now-dlPT)/1000)
            const mm=estMin(m.total-m.bytes, rate); if(mm) eta='약 '+mm+'분'
            spd=' ('+(rate/1048576).toFixed(1)+' MB/s)'
          }
          dlPB=m.bytes; dlPT=now
          h += '⏳ <b>다운로드 중</b>: '+(m.bytes/GB).toFixed(2)+' / '+(m.total/GB).toFixed(1)+' GB ('+pct+'%)<br>남은 예상 시간: <b>'+eta+'</b>'+spd+'<br>그다음 <b>FASTQ 변환</b>(보통 20~40분)이 이어집니다.'
        }
        else { h += '· 아직 시작 전입니다. 2c를 실행하려면 이 단계가 먼저 끝나야 합니다.' }
        tip.innerHTML = h
      }

      let lastKind = st.dlKind || null
      function onStatus(m){
        updateTip(m)
        const t = new Date().toLocaleTimeString()
        const kind = m.phase
        let line
        if (kind === 'done'){ line = t + '  ✓ 완료 (다운로드' + (m.convBytes? '·변환':'·압축 해제') + ' 끝)' }
        else if (kind === 'convert'){ line = t + '  🔄 FASTQ 변환 중 (BAM→FASTQ)… ' + (m.convBytes ? fmt(m.convBytes) + ' 생성됨' : '시작하는 중') }
        else if (kind === 'none'){ line = t + '  · 아직 시작 전 (not started)' }
        else { // download
          const pctv = m.total ? (100*m.bytes/m.total).toFixed(1)+'%' : '?'
          const grew = m.bytes > last
          const tail = last ? (grew ? '  (+'+fmt(m.bytes-last)+')' : '  · 변화 없음(정지?)') : ''
          line = t + '  ⏳ ' + fmt(m.bytes) + ' / ' + (m.total?fmt(m.total):'?') + '  ' + pctv + tail
        }
        last = m.bytes
        // Collapse consecutive same-phase updates into ONE live line (no endless spam); a phase
        // change (download→convert→done) starts a new line so you keep the milestones.
        if (lines.length && lastKind === kind && kind !== 'done'){ lines[lines.length-1] = line }
        else { lines.push(line); if (lines.length>500) lines = lines.slice(-500) }
        lastKind = kind
        vscode.setState(Object.assign(vscode.getState()||{}, { dlLines: lines, dlLast: last, dlKind: lastKind }))
        paint()
        if (kind === 'done') stop()
      }
      window.addEventListener('message', ev => { if (ev.data && ev.data.type==='dlstatus') onStatus(ev.data) })

      let timer = null
      function poll(){ vscode.postMessage({ type:'dlstatus' }) }
      function start(){ if(!timer && !stopped){ poll(); timer = setInterval(poll, 5000) } }
      function stop(){ stopped = true; if(timer){ clearInterval(timer); timer = null } }
      start()
    })();

    // ---- STARsolo (count-matrix) progress poller (Step 2c collapsible log) ---
    // Polls the latest Log.progress.out line + matrix.mtx existence; appends each new progress line.
    (function(){
      const box = document.getElementById('alignbox')
      const logEl = document.getElementById('alignlog')
      if (!box || !logEl) return
      const st = vscode.getState() || {}
      let lines = st.alLines || []
      let lastLine = st.alLast || ''
      let stopped = false
      function paint(){
        const stick = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 20
        logEl.textContent = lines.length ? lines.join('\\n') : '상태 확인 중…'
        if (stick) logEl.scrollTop = logEl.scrollHeight
      }
      function save(){ vscode.setState(Object.assign(vscode.getState()||{}, { alLines: lines, alLast: lastLine })) }
      function push(line){ lines.push(line); if(lines.length>500) lines = lines.slice(-500); save(); paint() }
      paint()
      function onStatus(m){
        const t = new Date().toLocaleTimeString()
        if (m.done){ if(lastLine!=='__done__'){ push(t + '  ✓ 완료: count matrix 생성됨 (done)'); lastLine='__done__'; save() } stop(); return }
        if (!m.hasLog){ if(lastLine!=='__wait__'){ push(t + '  · STARsolo 시작 전/대기 중 (아직 시작 안 함)'); lastLine='__wait__'; save() } return }
        if (m.running){
          if (m.line && m.line !== lastLine){ push(t + '  ' + m.line); lastLine = m.line; save() }
        } else {
          // Log exists but isn't updating and no matrix yet ⇒ a prior run stopped/failed.
          if (lastLine!=='__stale__'){ push(t + '  ⚠ STARsolo가 실행 중이 아닙니다 (이전 실행 중단/실패) — 준비되면 2c를 다시 실행하세요'); lastLine='__stale__'; save() }
        }
      }
      window.addEventListener('message', ev => { if (ev.data && ev.data.type==='alignstatus') onStatus(ev.data) })
      let timer = null
      function poll(){ vscode.postMessage({ type:'alignstatus' }) }
      function start(){ if(!timer && !stopped){ poll(); timer = setInterval(poll, 5000) } }
      function stop(){ stopped = true; if(timer){ clearInterval(timer); timer = null } }
      start()
    })()

    // ---- Legacy R setup status (Step 0) -------------------------------------
    // Shows only the three newest installer lines. Its explicit running state prevents users
    // from starting a second package installation while the first owns R's library lock.
    (function(){
      const box = document.getElementById('setupbox')
      const logEl = document.getElementById('setuplog')
      if (!box || !logEl) return
      let stopped = false
      function onStatus(m){
        if (!m.applicable) return
        const prefix = m.phase === 'done' ? '✓ completed' : m.phase === 'running' ? '⏳ running — do not click Step 0 again' : m.phase === 'stopped' ? '⚠ stopped/failed' : '· not started'
        box.querySelector('summary').firstChild.textContent = prefix + ' — '
        logEl.textContent = (m.lines && m.lines.length) ? m.lines.join('\\n') : '상태 확인 중…'
        if (m.phase === 'done') stop()
      }
      window.addEventListener('message', ev => { if (ev.data && ev.data.type==='setupstatus') onStatus(ev.data) })
      let timer = null
      function poll(){ vscode.postMessage({ type:'setupstatus' }) }
      function start(){ if(!timer && !stopped){ poll(); timer = setInterval(poll, 5000) } }
      function stop(){ stopped=true; if(timer){ clearInterval(timer); timer=null } }
      start()
    })()

    // ---- Whole-pipeline auto-run indicator (the ▶▶ 전체 분석 실행 button) --------
    // Server-side the full run is a persistent Task, so it keeps going after the browser closes.
    // We poll every few seconds and reflect its live state on the button: while it runs the button
    // animates + is disabled (a re-click would only harmlessly abort at the download lock), and a
    // subtitle shows the current phase. This is how a returning user knows "it's running — just wait".
    (function(){
      const btn = document.getElementById('runbtn')
      const label = document.getElementById('runlabel')
      const labelText = document.getElementById('runlabeltext')
      if (!btn) return
      const IDLE = '▶▶ 전체 분석 실행'
      const TAIL = ' · 창을 닫아도 서버에서 계속 진행됩니다.'
      function onStatus(m){
        if (m.running){
          btn.classList.add('running'); btn.disabled = true; btn.textContent = '⏳ 전체 분석 실행 중…'
          if (label) label.style.display = ''
          if (labelText) labelText.textContent = (m.label || '분석 자동 실행 중…') + TAIL
        } else {
          btn.classList.remove('running'); btn.disabled = false; btn.textContent = IDLE
          if (label) label.style.display = 'none'
        }
      }
      window.addEventListener('message', ev => { if (ev.data && ev.data.type==='runstatus') onStatus(ev.data) })
      function poll(){ vscode.postMessage({ type:'runstatus' }) }
      poll(); setInterval(poll, 4000)
    })()

    // ---- Generic per-step debug console -------------------------------------
    // One poller drives every 🐞 debug console. Each poll asks the extension for the tail of that
    // step's .logs/<id>.log; the extension is the source of truth (tail -40), so we just replace the
    // <pre>. Polls only OPEN consoles (collapsed ones stay quiet), plus an immediate poll on expand.
    (function(){
      const boxes = Array.from(document.querySelectorAll('.debugbox'))
      if (!boxes.length) return
      function pollBox(box){ if (box.open) vscode.postMessage({ type:'steplog', id: box.dataset.step }) }
      function pollAll(){ boxes.forEach(pollBox) }
      window.addEventListener('message', ev => {
        const m = ev.data
        if (!m || m.type !== 'steplog') return
        const pre = document.getElementById('debuglog-' + m.id)
        if (!pre) return
        const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24
        pre.textContent = (m.lines && m.lines.length)
          ? m.lines.join('\\n')
          : (m.running ? '실행 중… (아직 출력이 없습니다)' : '아직 실행 로그가 없습니다. 이 단계를 실행해 보세요.')
        if (stick) pre.scrollTop = pre.scrollHeight
      })
      boxes.forEach(b => b.addEventListener('toggle', () => pollBox(b)))
      pollAll(); setInterval(pollAll, 3000)
    })()
  </script>
</body></html>`
}
