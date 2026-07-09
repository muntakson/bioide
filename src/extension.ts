import * as vscode from "vscode"
import { TutorialProvider, runStep } from "./tutorials"
import { ProjectProvider, newProject, openProject } from "./projects"
import { LibraryProvider, installLibrary } from "./libraries"
import { openHome } from "./home"
import { openAI } from "./ai/panel"

export function activate(context: vscode.ExtensionContext) {
  const tutorials = new TutorialProvider(context)
  const projects = new ProjectProvider()
  const libraries = new LibraryProvider(context)

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("ghbio.tutorials", tutorials),
    vscode.window.registerTreeDataProvider("ghbio.projects", projects),
    vscode.window.registerTreeDataProvider("ghbio.libraries", libraries),

    vscode.commands.registerCommand("ghbio.openHome", () => openHome(context, tutorials)),
    vscode.commands.registerCommand("ghbio.openAI", () => openAI(context)),
    vscode.commands.registerCommand("ghbio.refresh", () => {
      tutorials.refresh()
      projects.refresh()
      libraries.refresh()
    }),
    vscode.commands.registerCommand("ghbio.runStep", (node) => runStep(node, () => openAI(context))),
    vscode.commands.registerCommand("ghbio.newProject", () => newProject().then(() => projects.refresh())),
    vscode.commands.registerCommand("ghbio.openProject", (dir) => openProject(dir)),
    vscode.commands.registerCommand("ghbio.installLibrary", (item) => {
      const lib = libraries.libFor(item?.id ?? "")
      if (lib) installLibrary(context, lib)
    }),
  )

  // Refresh library status whenever a task finishes (installs flip the status).
  context.subscriptions.push(vscode.tasks.onDidEndTask(() => libraries.refresh()))
}

export function deactivate() {}
