import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { TutorialProvider, runStep, runStepById } from "./tutorials"
import { ProjectProvider, newProject, openProject } from "./projects"
import { LibraryProvider, installLibrary } from "./libraries"
import { openHome } from "./home"
import { openLanding } from "./landing"
import { openHelp } from "./help"
import { openDashboard, refreshDashboard, DashboardTarget } from "./dashboard"
import { openAI } from "./ai/panel"
import { openSurvey, openSurveyStats } from "./survey"
import { openPaperWriter } from "./paper"
import { TerminalViewProvider } from "./terminal"
import { registerWorkTerminal, showWorkFolder } from "./workterminal"
import { openDatasetCatalog } from "./catalog"
import { openCreatePipeline } from "./createPipeline"
import { openCodelab } from "./codelab"
import { openAtlas } from "./atlas"
import { runPipeline } from "./pipeline"
import { loadModules, findPipeline, defaultPipeline } from "./modules"
import { confirmRun, cfg, tutorialProjectDir, projectsDir, pipelineDraftsDir } from "./util"
import { resetExplorerToWorkspaceRoot, revealInExplorerNoReload, consumePendingReveal } from "./explorer"

// globalState key: the project folder to reopen a dashboard for after a "open folder" reload.
const RETURN_TO_DASHBOARD_KEY = "ghbio.returnToDashboard"

export function activate(context: vscode.ExtensionContext) {
  const tutorials = new TutorialProvider(context)
  const projects = new ProjectProvider()
  const libraries = new LibraryProvider(context)
  const terminal = new TerminalViewProvider(context.extensionUri)
  registerWorkTerminal(context)

  // The "currently open" tutorial — the last pipeline the user interacted with
  // (ran a step, ran the whole pipeline, or opened its AI panel). The context-aware
  // Help (help.ts) tailors its walkthrough/glossary to this pipeline. Persisted so it
  // survives a window reload.
  let activePipelineId = context.workspaceState.get<string>("ghbio.activePipeline")
  const setActive = (id?: string) => {
    if (!id || id === activePipelineId) return
    activePipelineId = id
    context.workspaceState.update("ghbio.activePipeline", id)
  }

  // Normalize the many shapes an "open dashboard" request can arrive in into a
  // DashboardTarget the dashboard understands.
  const toDashboardTarget = (arg: unknown): DashboardTarget | undefined => {
    if (!arg) return activePipelineId
    if (typeof arg === "string") {
      return arg.includes("/") ? { kind: "project", id: path.basename(arg), dir: arg } : arg
    }
    const a = arg as { kind?: string; id?: string; dir?: string; p?: { id?: string } }
    if (a.p?.id) return a.p.id // tutorials-tree Node (pipeline/stage)
    if (a.kind === "project" || a.kind === "tutorial") return a as DashboardTarget
    return activePipelineId
  }

  // The on-disk work folder for a dashboard target: a tutorial/pipeline id maps to its project
  // dir (~/ghbio-workspace/projects/<id>); a project card carries its own dir.
  const projectDirOf = (t: DashboardTarget | undefined): string | undefined => {
    if (!t) return undefined
    if (typeof t === "string") return tutorialProjectDir(t)
    if (t.kind === "tutorial") return tutorialProjectDir(t.id)
    if (t.kind === "project") return t.dir ?? path.join(projectsDir(), t.id)
    return undefined
  }

  // Resolve a pipeline by id (or the default) and run it, handing off to its module's AI.
  const runPipelineCmd = async (pipelineId?: string) => {
    const modules = loadModules(context)
    const resolved = (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
    if (!resolved) {
      vscode.window.showErrorMessage("GHBIO: no pipeline found to run.")
      return
    }
    const p = resolved.pipeline
    // Clicking a tutorial title auto-runs the WHOLE pipeline (incl. a large download).
    // Set it as the current tutorial (so Help follows) and ask before starting — this
    // is the guard against an accidental click kicking off a 19 GB re-download.
    setActive(p.id)
    const steps = p.stages.map((s) => `  • ${s.ko || s.title}`).join("\n")
    const detail =
      `튜토리얼: ${p.name}\n\n` +
      `아래 단계가 위에서부터 순서대로 자동 실행됩니다:\n${steps}\n\n` +
      `⚠ 데이터 다운로드와 유전체 색인은 대용량이라 수십 분 이상 걸릴 수 있고, ` +
      `이미 진행 중인 작업이 있으면 중복 실행될 수 있습니다.\n\n` +
      `지금 전체 분석을 시작할까요? (개별 단계만 실행하려면 '아니오'를 누르고 원하는 단계를 클릭하세요.)`
    if (!(await confirmRun("▶▶ 전체 분석을 처음부터 끝까지 실행할까요?", detail))) return
    return runPipeline(context, resolved.pipeline, {
      openAI: () => openAI(context, resolved.pipeline.id),
      readyFile: resolved.module.ai?.readyFile,
    })
  }

  // The Pipelines / Projects / Libraries sidebar trees were removed as redundant — everything
  // is managed from GHBIO Home → Tutorials → Dashboard. The provider instances are kept because
  // Home reads pipeline data from `tutorials`, and the newProject / installLibrary commands still
  // drive `projects` and `libraries`; they're simply no longer surfaced as activity-bar trees.
  // Persistent side-bar shell. The webview is kept alive when hidden so a browser-tab reload
  // repaints the existing session instead of dropping it; the backend shell (owned by the
  // provider) lives for the whole code-server session — see terminal.ts.
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(TerminalViewProvider.viewId, terminal, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    terminal,

    vscode.commands.registerCommand("ghbio.openTerminal", () =>
      vscode.commands.executeCommand("ghbio.terminal.focus"),
    ),
    vscode.commands.registerCommand("ghbio.restartTerminal", () => terminal.restart()),

    vscode.commands.registerCommand("ghbio.openHome", async () => {
      // Clicking Home resets the folder view to ~/ghbio-workspace (the last opened project may
      // have narrowed it). If a re-root is needed this reloads the workbench and activate()
      // reopens Home; otherwise openHome renders now.
      await resetExplorerToWorkspaceRoot(context)
      openHome(context, tutorials)
    }),
    vscode.commands.registerCommand("ghbio.openLanding", () => openLanding(context, tutorials)),
    vscode.commands.registerCommand("ghbio.openDatasetCatalog", () => openDatasetCatalog()),
    vscode.commands.registerCommand("ghbio.openCreatePipeline", () => {
      openCreatePipeline(context)
      // Point the folder view at pipeline-drafts/ so the AI-drafted *_plan.md is easy to find.
      // No reload (would destroy the just-opened panel) — best-effort reveal within the current root.
      revealInExplorerNoReload(pipelineDraftsDir())
    }),
    vscode.commands.registerCommand("ghbio.openAtlas", (key?: string) => openAtlas(context, key)),
    vscode.commands.registerCommand("ghbio.openCodelab", (arg) => {
      const id = typeof arg === "string" ? arg : undefined
      if (id) setActive(id)
      openCodelab(context, id ?? activePipelineId)
    }),
    vscode.commands.registerCommand("ghbio.openHelp", () => openHelp(context, activePipelineId)),
    vscode.commands.registerCommand("ghbio.openAI", () => openAI(context)),
    vscode.commands.registerCommand("ghbio.openSurvey", (arg) => {
      const id = typeof arg === "string" ? arg : undefined
      if (id) setActive(id)
      openSurvey(context, id)
    }),
    vscode.commands.registerCommand("ghbio.openSurveyStats", (arg) => {
      const id = typeof arg === "string" ? arg : undefined
      if (id) setActive(id)
      openSurveyStats(context, id)
    }),
    vscode.commands.registerCommand("ghbio.writePaper", (arg, mode) =>
      openPaperWriter(
        context,
        typeof arg === "string" ? arg : undefined,
        mode === "research" || mode === "research_hs" ? mode : "edu",
      ),
    ),

    // Dashboard: accepts a pipelineId (from webview), a tutorials-tree Node, a project
    // dir path (from the projects tree), or a {kind,id,dir} card payload from Home.
    vscode.commands.registerCommand("ghbio.openDashboard", (arg) => {
      const target = toDashboardTarget(arg)
      if (typeof target === "string") setActive(target)
      else if (target && target.kind === "tutorial") setActive(target.id)
      openDashboard(context, target)
      // Follow the selected pipeline/project into its work folder — in the PANEL work terminal
      // (the side-bar SSH terminal stays put on the codebase).
      const dir = projectDirOf(target)
      showWorkFolder(dir)
      // Point the folder view at this project's results/ folder (where its outputs land). Best-effort,
      // no reload; reveals only when the workspace root contains it (the ~/ghbio-workspace default).
      if (dir) {
        const results = path.join(dir, "results")
        try {
          fs.mkdirSync(results, { recursive: true })
        } catch {
          /* pipeline may not have run yet — reveal falls back to a no-op */
        }
        revealInExplorerNoReload(results)
      }
    }),
    vscode.commands.registerCommand("ghbio.openResult", (p?: string) => {
      if (p) vscode.commands.executeCommand("vscode.open", vscode.Uri.file(p))
    }),
    vscode.commands.registerCommand("ghbio.runStepById", (pipelineId?: string, stageId?: string) => {
      if (!pipelineId || !stageId) return
      setActive(pipelineId)
      return runStepById(loadModules(context), pipelineId, stageId, (pid) => {
        setActive(pid)
        openAI(context, pid)
      })
    }),
    vscode.commands.registerCommand("ghbio.runPipeline", (arg) =>
      runPipelineCmd(typeof arg === "string" ? arg : undefined),
    ),
    vscode.commands.registerCommand("ghbio.refresh", () => {
      tutorials.refresh()
      projects.refresh()
      libraries.refresh()
    }),
    vscode.commands.registerCommand("ghbio.runStep", (node) => {
      setActive(node?.p?.id)
      return runStep(node, (pid) => {
        setActive(pid)
        openAI(context, pid)
      })
    }),
    vscode.commands.registerCommand("ghbio.newProject", () => newProject().then(() => projects.refresh())),
    vscode.commands.registerCommand("ghbio.openProject", async (dir) => {
      // Opening a project folder reloads the whole workbench (vscode.openFolder). Remember which
      // folder we're heading into so activate() can reopen ITS dashboard after the reload, instead
      // of dumping the user back on GHBIO Home. globalState survives the reload/workspace change.
      if (typeof dir === "string") await context.globalState.update(RETURN_TO_DASHBOARD_KEY, dir)
      return openProject(dir)
    }),
    vscode.commands.registerCommand("ghbio.installLibrary", (item) => {
      const found = libraries.find(item?.id ?? "")
      if (found) installLibrary(context, found.m, found.lib)
    }),
  )

  // Refresh status whenever a task finishes: installs flip library status, and pipeline
  // stages flip to ✓ done as their result artifacts appear.
  // Refresh status when a task starts or ends: dashboards flip steps to "실행 중…" on
  // start and "완료"/✓ on end, library status updates, and pipeline stages flip to done.
  const refreshAll = () => {
    libraries.refresh()
    tutorials.refresh()
    refreshDashboard()
  }
  context.subscriptions.push(
    vscode.tasks.onDidStartTask(refreshAll),
    vscode.tasks.onDidEndTask(refreshAll),
  )

  // If we just reloaded because the user clicked "프로젝트 폴더 열기", return them to THAT project's
  // dashboard (not Home). We stored the folder before reloading; resolve it back to a dashboard
  // target — a known pipeline id → its tutorial dashboard, otherwise a plain project view.
  // Finish any Explorer reveal that was deferred across a folder-reload (e.g. Home re-rooting).
  consumePendingReveal(context)

  const returnDir = context.globalState.get<string>(RETURN_TO_DASHBOARD_KEY)
  if (returnDir) {
    context.globalState.update(RETURN_TO_DASHBOARD_KEY, undefined)
    setTimeout(() => {
      const id = path.basename(returnDir)
      const isPipeline = loadModules(context).some((m) => m.pipelines.some((p) => p.id === id))
      const target = isPipeline ? id : { kind: "project" as const, id, dir: returnDir }
      vscode.commands.executeCommand("ghbio.openDashboard", target)
    }, 400)
  } else if (cfg<boolean>("openHomeOnStartup", true)) {
    // The public BioIDE landing page is served at the bare URL by the nginx front proxy
    // (see RUN.md) BEFORE code-server login, so once we're inside the authenticated workbench
    // we go straight to Home. The in-IDE landing (ghbio.openLanding) remains available from the
    // command palette but is not auto-opened, to avoid showing a second landing after sign-in.
    setTimeout(() => vscode.commands.executeCommand("ghbio.openHome"), 400)
  }

  // Reveal the persistent side-bar shell on startup so it's warm and ready. Revealing the view
  // instantiates the webview, which starts the backing shell; it then stays alive for the session.
  if (cfg<boolean>("openTerminalOnStartup", true)) {
    setTimeout(() => vscode.commands.executeCommand("ghbio.terminal.focus"), 700)
  }
}

export function deactivate() {}
