import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { tutorialsDir, runShellTask } from "./util"

export interface Step {
  id: string
  title: string
  ko?: string
  kind: "task" | "ai"
  run?: string // shell command for kind:"task" (relative to the tutorial dir)
  desc?: string
}
export interface Tutorial {
  id: string
  name: string
  summary?: string
  dir: string
  steps: Step[]
}

export function loadTutorials(context: vscode.ExtensionContext): Tutorial[] {
  const root = tutorialsDir(context)
  const out: Tutorial[] = []
  if (!fs.existsSync(root)) return out
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const manifest = path.join(root, entry.name, "tutorial.json")
    if (!fs.existsSync(manifest)) continue
    try {
      const m = JSON.parse(fs.readFileSync(manifest, "utf8"))
      out.push({ ...m, dir: path.join(root, entry.name), steps: m.steps ?? [] })
    } catch (e) {
      vscode.window.showErrorMessage(`GHBIO: bad tutorial.json in ${entry.name}: ${e}`)
    }
  }
  return out
}

type Node = { kind: "tutorial"; t: Tutorial } | { kind: "step"; t: Tutorial; s: Step; index: number }

export class TutorialProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this._onDidChange.event
  private tutorials: Tutorial[] = []

  constructor(private context: vscode.ExtensionContext) {
    this.refresh()
  }
  refresh() {
    this.tutorials = loadTutorials(this.context)
    this._onDidChange.fire()
  }
  getTutorials() {
    return this.tutorials
  }

  getTreeItem(n: Node): vscode.TreeItem {
    if (n.kind === "tutorial") {
      const it = new vscode.TreeItem(n.t.name, vscode.TreeItemCollapsibleState.Expanded)
      it.description = n.t.summary
      it.iconPath = new vscode.ThemeIcon("beaker")
      it.contextValue = "tutorial"
      return it
    }
    const s = n.s
    const it = new vscode.TreeItem(s.title, vscode.TreeItemCollapsibleState.None)
    it.description = s.ko
    it.tooltip = s.desc ?? s.ko
    it.iconPath = new vscode.ThemeIcon(s.kind === "ai" ? "sparkle" : "play-circle")
    it.contextValue = "step"
    it.command = { command: "ghbio.runStep", title: "Run", arguments: [n] }
    return it
  }
  getChildren(n?: Node): Node[] {
    if (!n) return this.tutorials.map((t) => ({ kind: "tutorial", t }) as Node)
    if (n.kind === "tutorial") return n.t.steps.map((s, i) => ({ kind: "step", t: n.t, s, index: i }) as Node)
    return []
  }
}

// Run a tutorial step: kind:"task" → wrapped shell task with guidance banners;
// kind:"ai" → open the AI Analysis panel.
export async function runStep(node: Node, openAI: () => void) {
  if (node.kind !== "step") return
  const { t, s } = node
  if (s.kind === "ai") {
    openAI()
    return
  }
  if (!s.run) {
    vscode.window.showWarningMessage(`GHBIO: step "${s.title}" has no command.`)
    return
  }
  const title = s.title.replace(/"/g, "")
  const header =
    `printf "\\n\\033[1;36m▶ %s\\033[0m\\n" "${title}"; ` +
    `echo "  실행 중입니다… 끝나면 ✅ 표시가 나옵니다. (Running — watch for the ✅ line.)"; echo "";`
  const footer =
    `__rc=$?; echo ""; ` +
    `if [ "$__rc" -eq 0 ]; then printf "\\033[1;32m✅ 완료: %s\\033[0m\\n" "${title}"; ` +
    `else printf "\\033[1;31m⚠ 오류(exit %s): %s\\033[0m\\n" "$__rc" "${title}"; fi; ` +
    `echo "→ 다음 단계는 왼쪽 GHBIO → Tutorials 에서 이어서 누르세요."; echo "";`
  const full = `${header} { ${s.run}; }; ${footer}`
  await runShellTask(`GHBIO: ${title}`, full, t.dir)
}
