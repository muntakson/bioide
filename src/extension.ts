import * as vscode from "vscode"
import * as path from "path"
import { TutorialProvider, runStep, runStepById } from "./tutorials"
import { ProjectProvider, newProject, openProject } from "./projects"
import { LibraryProvider, installLibrary } from "./libraries"
import { openHome } from "./home"
import { openHelp } from "./help"
import { openDashboard, refreshDashboard, DashboardTarget } from "./dashboard"
import { openAI } from "./ai/panel"
import { runPipeline } from "./pipeline"
import { loadModules, findPipeline, defaultPipeline } from "./modules"
import { confirmRun, cfg } from "./util"

export function activate(context: vscode.ExtensionContext) {
  const tutorials = new TutorialProvider(context)
  const projects = new ProjectProvider()
  const libraries = new LibraryProvider(context)

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

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("ghbio.tutorials", tutorials),
    vscode.window.registerTreeDataProvider("ghbio.projects", projects),
    vscode.window.registerTreeDataProvider("ghbio.libraries", libraries),

    vscode.commands.registerCommand("ghbio.openHome", () => openHome(context, tutorials)),
    vscode.commands.registerCommand("ghbio.openHelp", () => openHelp(context, activePipelineId)),
    vscode.commands.registerCommand("ghbio.openAI", () => openAI(context)),

    // Dashboard: accepts a pipelineId (from webview), a tutorials-tree Node, a project
    // dir path (from the projects tree), or a {kind,id,dir} card payload from Home.
    vscode.commands.registerCommand("ghbio.openDashboard", (arg) => {
      const target = toDashboardTarget(arg)
      if (typeof target === "string") setActive(target)
      else if (target && target.kind === "tutorial") setActive(target.id)
      openDashboard(context, target)
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
    vscode.commands.registerCommand("ghbio.openProject", (dir) => openProject(dir)),
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

  // Like PlatformIO Home: greet with the dashboard landing on startup (opt-out via
  // ghbio.openHomeOnStartup) so novices see the tutorial/project overview first.
  if (cfg<boolean>("openHomeOnStartup", true)) {
    setTimeout(() => vscode.commands.executeCommand("ghbio.openHome"), 400)
  }
}

export function deactivate() {}
