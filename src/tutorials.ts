import * as vscode from "vscode"
import { runShellTask } from "./util"
import { Module, loadModules } from "./modules"
import { Pipeline, Stage, ensureProject, isStageDone } from "./pipeline"

// Tree over the module registry:
//   (Module →)? Pipeline → Stage
// The Module level is shown only when more than one module is installed, so a
// single-domain install stays flat and simple for non-technical users.
type Node =
  | { kind: "module"; m: Module }
  | { kind: "pipeline"; m: Module; p: Pipeline }
  | { kind: "stage"; m: Module; p: Pipeline; s: Stage; index: number }

export class TutorialProvider implements vscode.TreeDataProvider<Node> {
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
  getModules() {
    return this.modules
  }

  getTreeItem(n: Node): vscode.TreeItem {
    if (n.kind === "module") {
      const it = new vscode.TreeItem(n.m.name, vscode.TreeItemCollapsibleState.Expanded)
      it.description = n.m.description
      it.iconPath = new vscode.ThemeIcon(n.m.icon ?? "package")
      it.contextValue = "module"
      return it
    }
    if (n.kind === "pipeline") {
      const it = new vscode.TreeItem(n.p.name, vscode.TreeItemCollapsibleState.Expanded)
      it.description = n.p.summary
      it.iconPath = new vscode.ThemeIcon("beaker")
      it.contextValue = "pipeline"
      it.command = { command: "ghbio.runPipeline", title: "Run full analysis", arguments: [n.p.id] }
      return it
    }
    const s = n.s
    const it = new vscode.TreeItem(s.title, vscode.TreeItemCollapsibleState.None)
    const done = isStageDone(n.p.id, s.produces)
    it.description = done ? `✓ ${s.ko ?? ""}`.trim() : s.ko
    it.tooltip = s.desc ?? s.ko
    it.iconPath = new vscode.ThemeIcon(
      done ? "pass-filled" : s.kind === "ai" ? "sparkle" : "play-circle",
      done ? new vscode.ThemeColor("charts.green") : undefined,
    )
    it.contextValue = "step"
    it.command = { command: "ghbio.runStep", title: "Run", arguments: [n] }
    return it
  }

  getChildren(n?: Node): Node[] {
    if (!n) {
      // Root: modules if >1, otherwise jump straight to the single module's pipelines.
      if (this.modules.length > 1) return this.modules.map((m) => ({ kind: "module", m }) as Node)
      const m = this.modules[0]
      return m ? m.pipelines.map((p) => ({ kind: "pipeline", m, p }) as Node) : []
    }
    if (n.kind === "module") return n.m.pipelines.map((p) => ({ kind: "pipeline", m: n.m, p }) as Node)
    if (n.kind === "pipeline")
      return n.p.stages.map((s, i) => ({ kind: "stage", m: n.m, p: n.p, s, index: i }) as Node)
    return []
  }
}

// Run one pipeline stage: kind:"ai" opens the AI panel (for that pipeline);
// otherwise the stage's shell command runs as a banner-wrapped VS Code task.
export async function runStep(node: Node, openAI: (pipelineId: string) => void) {
  if (node.kind !== "stage") return
  const { p, s } = node
  if (s.kind === "ai") {
    openAI(p.id)
    return
  }
  if (!s.run) {
    vscode.window.showWarningMessage(`GHBIO: step "${s.title}" has no command.`)
    return
  }
  // Outputs are first-class files in Projects/<pipeline>/; the pipeline module owns
  // this scaffolding and per-step runs reuse it.
  const resultsDir = ensureProject(p)

  const title = s.title.replace(/"/g, "")
  const header =
    `printf "\\n\\033[1;36m▶ %s\\033[0m\\n" "${title}"; ` +
    `echo "  실행 중입니다… 끝나면 ✅ 표시가 나옵니다. (Running — watch for the ✅ line.)"; echo "";`
  const footer =
    `__rc=$?; echo ""; ` +
    `if [ "$__rc" -eq 0 ]; then printf "\\033[1;32m✅ 완료: %s\\033[0m\\n" "${title}"; ` +
    `else printf "\\033[1;31m⚠ 오류(exit %s): %s\\033[0m\\n" "$__rc" "${title}"; fi; ` +
    `echo "→ 다음 단계는 왼쪽 GHBIO → Pipelines 에서 이어서 누르세요."; echo "";`
  const full = `${header} { ${s.run}; }; ${footer}`
  await runShellTask(`GHBIO: ${title}`, full, p.dir, { GHBIO_RESULTS: resultsDir })
}
