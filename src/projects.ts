import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { projectsDir } from "./util"

export class ProjectProvider implements vscode.TreeDataProvider<string> {
  private _onDidChange = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this._onDidChange.event
  refresh() {
    this._onDidChange.fire()
  }
  getTreeItem(dir: string): vscode.TreeItem {
    const it = new vscode.TreeItem(path.basename(dir), vscode.TreeItemCollapsibleState.None)
    it.resourceUri = vscode.Uri.file(dir)
    it.iconPath = new vscode.ThemeIcon("folder")
    it.contextValue = "project"
    it.description = dir.replace(require("os").homedir(), "~")
    it.command = { command: "ghbio.openProject", title: "Open", arguments: [dir] }
    return it
  }
  getChildren(): string[] {
    const root = projectsDir()
    if (!fs.existsSync(root)) return []
    return fs
      .readdirSync(root, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => path.join(root, e.name))
  }
}

export async function newProject() {
  const name = await vscode.window.showInputBox({
    prompt: "New GHBIO project name",
    placeHolder: "my-pbmc-analysis",
    validateInput: (v) => (/^[A-Za-z0-9._-]+$/.test(v) ? null : "letters, numbers, . _ - only"),
  })
  if (!name) return
  const root = projectsDir()
  const dir = path.join(root, name)
  if (fs.existsSync(dir)) {
    vscode.window.showErrorMessage(`GHBIO: project "${name}" already exists.`)
    return
  }
  fs.mkdirSync(path.join(dir, "data"), { recursive: true })
  fs.mkdirSync(path.join(dir, "results"), { recursive: true })
  fs.writeFileSync(
    path.join(dir, "notes.md"),
    `# ${name}\n\nscRNA-seq analysis project.\n\n- data/ — inputs\n- results/ — matrices, figures, tables\n`,
  )
  await openProject(dir)
}

export async function openProject(dir: string) {
  await vscode.commands.executeCommand("vscode.openFolder", vscode.Uri.file(dir), { forceNewWindow: false })
}
