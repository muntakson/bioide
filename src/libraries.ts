import * as vscode from "vscode"
import * as fs from "fs"
import { runShellTask, expandHome } from "./util"
import { Module, LibrarySpec, loadModules, findPipeline } from "./modules"

// The tools/refs each module needs, read from module.json (no hardcoding). Each
// library has a presence check (presentPath exists?) and an install action that
// runs one of the module's pipeline scripts.
type LibNode =
  | { kind: "moduleHeader"; m: Module }
  | { kind: "lib"; m: Module; lib: LibrarySpec }

function present(lib: LibrarySpec): boolean {
  return fs.existsSync(expandHome(lib.presentPath))
}

export class LibraryProvider implements vscode.TreeDataProvider<LibNode> {
  private _onDidChange = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this._onDidChange.event
  private modules: Module[] = []
  constructor(private context: vscode.ExtensionContext) {
    this.refresh()
  }
  refresh() {
    this.modules = loadModules(this.context)
    this._onDidChange.fire()
  }

  getTreeItem(n: LibNode): vscode.TreeItem {
    if (n.kind === "moduleHeader") {
      const it = new vscode.TreeItem(n.m.name, vscode.TreeItemCollapsibleState.Expanded)
      it.iconPath = new vscode.ThemeIcon(n.m.icon ?? "package")
      it.contextValue = "moduleHeader"
      return it
    }
    const ok = present(n.lib)
    const it = new vscode.TreeItem(n.lib.name, vscode.TreeItemCollapsibleState.None)
    it.description = ok ? "installed" : "not installed"
    it.tooltip = n.lib.desc
    it.iconPath = new vscode.ThemeIcon(
      ok ? "pass-filled" : "circle-large-outline",
      ok ? new vscode.ThemeColor("charts.green") : undefined,
    )
    it.contextValue = "library"
    it.id = `${n.m.id}/${n.lib.id}`
    return it
  }

  getChildren(n?: LibNode): LibNode[] {
    const withLibs = this.modules.filter((m) => m.libraries?.length)
    if (!n) {
      if (withLibs.length > 1) return withLibs.map((m) => ({ kind: "moduleHeader", m }) as LibNode)
      const m = withLibs[0]
      return m ? m.libraries!.map((lib) => ({ kind: "lib", m, lib }) as LibNode) : []
    }
    if (n.kind === "moduleHeader") return n.m.libraries!.map((lib) => ({ kind: "lib", m: n.m, lib }) as LibNode)
    return []
  }

  // Resolve a tree item id ("<moduleId>/<libId>") back to its module + library.
  find(id: string): { m: Module; lib: LibrarySpec } | undefined {
    const [mid, lid] = id.split("/")
    const m = this.modules.find((x) => x.id === mid)
    const lib = m?.libraries?.find((l) => l.id === lid)
    return m && lib ? { m, lib } : undefined
  }
}

export async function installLibrary(context: vscode.ExtensionContext, m: Module, lib: LibrarySpec) {
  // The install script lives in one of the module's pipeline folders.
  const found = findPipeline([m], lib.install.pipeline)
  if (!found) {
    vscode.window.showErrorMessage(`GHBIO: install pipeline "${lib.install.pipeline}" not found in module ${m.id}.`)
    return
  }
  await runShellTask(`GHBIO: ${lib.install.label}`, `bash ${lib.install.script}`, found.pipeline.dir)
}
