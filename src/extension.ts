import * as vscode from "vscode"
import { TutorialProvider, runStep } from "./tutorials"
import { ProjectProvider, newProject, openProject } from "./projects"
import { LibraryProvider, installLibrary } from "./libraries"
import { openHome } from "./home"
import { openHelp } from "./help"
import { openAI } from "./ai/panel"
import { runPipeline } from "./pipeline"
import { loadModules, findPipeline, defaultPipeline } from "./modules"

export function activate(context: vscode.ExtensionContext) {
  const tutorials = new TutorialProvider(context)
  const projects = new ProjectProvider()
  const libraries = new LibraryProvider(context)

  // Resolve a pipeline by id (or the default) and run it, handing off to its module's AI.
  const runPipelineCmd = (pipelineId?: string) => {
    const modules = loadModules(context)
    const resolved = (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
    if (!resolved) {
      vscode.window.showErrorMessage("GHBIO: no pipeline found to run.")
      return
    }
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
    vscode.commands.registerCommand("ghbio.openHelp", () => openHelp(context)),
    vscode.commands.registerCommand("ghbio.openAI", () => openAI(context)),
    vscode.commands.registerCommand("ghbio.runPipeline", (arg) =>
      runPipelineCmd(typeof arg === "string" ? arg : undefined),
    ),
    vscode.commands.registerCommand("ghbio.refresh", () => {
      tutorials.refresh()
      projects.refresh()
      libraries.refresh()
    }),
    vscode.commands.registerCommand("ghbio.runStep", (node) => runStep(node, (pid) => openAI(context, pid))),
    vscode.commands.registerCommand("ghbio.newProject", () => newProject().then(() => projects.refresh())),
    vscode.commands.registerCommand("ghbio.openProject", (dir) => openProject(dir)),
    vscode.commands.registerCommand("ghbio.installLibrary", (item) => {
      const found = libraries.find(item?.id ?? "")
      if (found) installLibrary(context, found.m, found.lib)
    }),
  )

  // Refresh status whenever a task finishes: installs flip library status, and pipeline
  // stages flip to ✓ done as their result artifacts appear.
  context.subscriptions.push(
    vscode.tasks.onDidEndTask(() => {
      libraries.refresh()
      tutorials.refresh()
    }),
  )
}

export function deactivate() {}
