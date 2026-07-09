import * as vscode from "vscode"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { runShellTask, tutorialsDir } from "./util"

// The bioinformatics "libraries" (tools/refs) the scRNA-seq pipeline needs.
// Each has a presence check and an install/build action (runs a tutorial script).
interface Lib {
  id: string
  name: string
  desc: string
  present: () => boolean
  install: { script: string; label: string } // script relative to the pbmc tutorial dir
}

function home(...p: string[]) {
  return path.join(os.homedir(), ...p)
}

const LIBS: Lib[] = [
  {
    id: "venv",
    name: "Python / Scanpy",
    desc: "~/ghbio-venv (scanpy, anndata, leiden, umap)",
    present: () => fs.existsSync(home("ghbio-venv", "bin", "python")),
    install: { script: "00_setup_env.sh", label: "Install Python stack" },
  },
  {
    id: "star",
    name: "STAR / STARsolo",
    desc: "~/bin/STAR (aligner, built from source)",
    present: () => fs.existsSync(home("bin", "STAR")),
    install: { script: "02a_build_starsolo.sh", label: "Build STAR" },
  },
  {
    id: "reference",
    name: "GRCh38 reference + index",
    desc: "~/ghbio-tutorial/ref/star_index (~30 GB, one-time)",
    present: () => fs.existsSync(home("ghbio-tutorial", "ref", "star_index", "SAindex")),
    install: { script: "02b_reference.sh", label: "Download + build index" },
  },
]

export class LibraryProvider implements vscode.TreeDataProvider<Lib> {
  private _onDidChange = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this._onDidChange.event
  constructor(private context: vscode.ExtensionContext) {}
  refresh() {
    this._onDidChange.fire()
  }
  getTreeItem(l: Lib): vscode.TreeItem {
    const ok = l.present()
    const it = new vscode.TreeItem(l.name, vscode.TreeItemCollapsibleState.None)
    it.description = ok ? "installed" : "not installed"
    it.tooltip = l.desc
    it.iconPath = new vscode.ThemeIcon(
      ok ? "pass-filled" : "circle-large-outline",
      ok ? new vscode.ThemeColor("charts.green") : undefined,
    )
    it.contextValue = "library"
    return it
  }
  getChildren(): Lib[] {
    return LIBS
  }
  libFor(id: string) {
    return LIBS.find((l) => l.id === id)
  }
}

export async function installLibrary(context: vscode.ExtensionContext, l: Lib) {
  // Libraries install via the scrna-seq-pbmc tutorial scripts.
  const dir = path.join(tutorialsDir(context), "scrna-seq-pbmc")
  await runShellTask(`GHBIO: ${l.install.label}`, `bash ${l.install.script}`, dir)
}
