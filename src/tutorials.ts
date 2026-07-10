import * as vscode from "vscode"
import { runShellTask, confirmRun } from "./util"
import { Module, loadModules } from "./modules"
import { Pipeline, Stage, ensureProject, stageComplete } from "./pipeline"

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
    const done = stageComplete(n.p.id, s)
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

// Run a stage by (pipelineId, stageId) — used by the dashboard's step checklist.
// Builds the same Node runStep expects, so it shares the confirmation dialog.
export async function runStepById(
  modules: Module[],
  pipelineId: string,
  stageId: string,
  openAI: (pipelineId: string) => void,
) {
  for (const m of modules) {
    const p = m.pipelines.find((pl) => pl.id === pipelineId)
    if (!p) continue
    const index = p.stages.findIndex((s) => s.id === stageId)
    if (index < 0) return
    return runStep({ kind: "stage", m, p, s: p.stages[index], index }, openAI)
  }
}

// Run one pipeline stage: kind:"ai" opens the AI panel (for that pipeline);
// otherwise the stage's shell command runs as a banner-wrapped VS Code task.
export async function runStep(node: Node, openAI: (pipelineId: string) => void) {
  if (node.kind !== "stage") return
  const { p, s } = node
  if (s.kind !== "ai" && !s.run) {
    vscode.window.showWarningMessage(`GHBIO: step "${s.title}" has no command.`)
    return
  }

  // Novice-friendly, STATE-AWARE confirmation: a stateless "run this?" prompt misleads
  // users on long steps — they can't tell if it's already done or still downloading.
  // We detect both (completion via produces/presentPath; running via active tasks) and
  // say so plainly, and reassure that re-running never deletes/corrupts existing files.
  const raw = p.help?.steps?.[s.id] ?? s.desc ?? s.ko ?? "이 단계를 실행합니다."
  const plain = raw.replace(/<[^>]+>/g, "")

  const taskName = `GHBIO: ${s.title.replace(/"/g, "")}`
  const running = vscode.tasks.taskExecutions.some((e) => e.task.name === taskName)
  const complete = stageComplete(p.id, s) === true

  let status: string
  if (s.kind === "ai") {
    status = "\n\nAI 분석 창을 열까요?"
  } else if (running) {
    status =
      "\n\n⏳ 지금 이 단계가 이미 실행/다운로드 중입니다. 중복 실행하면 파일이 충돌·손상될 수 있어요. " +
      "끝날 때까지 기다리시길 권합니다. 그래도 다시 시작할까요?  (권장: 아니오)"
  } else if (complete) {
    status =
      "\n\n✅ 이 단계는 이미 완료되었습니다 — 필요한 파일이 이미 준비되어 있습니다. 다시 하지 않아도 됩니다. " +
      "다시 실행해도 기존 파일은 지워지지 않고, 이미 있으면 건너뜁니다. 그래도 다시 실행할까요?  (권장: 아니오)"
  } else {
    status =
      "\n\n이 단계를 지금 실행할까요? 이미 받은 부분이 있으면 이어받고, 완료돼 있으면 건너뜁니다 " +
      "— 기존 파일을 지우거나 손상시키지 않습니다."
  }
  if (!(await confirmRun(`▶ ${s.title}`, plain + status))) return

  if (s.kind === "ai") {
    openAI(p.id)
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
