import * as vscode from "vscode"
import * as os from "os"
import * as path from "path"

export function expandHome(p: string): string {
  if (!p) return p
  if (p === "~") return os.homedir()
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2))
  return p
}

export function cfg<T>(key: string, fallback: T): T {
  return vscode.workspace.getConfiguration("ghbio").get<T>(key, fallback)
}

// Root of the module registry: each modules/<id>/ is a self-contained domain
// (its own module.json, libraries, AI config, and pipelines/).
export function modulesDir(context: vscode.ExtensionContext): string {
  const configured = cfg<string>("modulesDir", "")
  if (configured) return expandHome(configured)
  return path.join(context.extensionPath, "modules")
}

// Legacy: some setups still ship a flat tutorials/ dir. Kept for back-compat.
export function tutorialsDir(context: vscode.ExtensionContext): string {
  const configured = cfg<string>("tutorialsDir", "")
  if (configured) return expandHome(configured)
  return path.join(context.extensionPath, "tutorials")
}

export function projectsDir(): string {
  return expandHome(cfg<string>("projectsDir", "~/ghbio-workspace/projects"))
}

// Each tutorial owns a project under projectsDir(); its outputs are first-class files
// that live in that project's results/ folder (shown in the Projects view).
export function tutorialProjectDir(tutorialId: string): string {
  return path.join(projectsDir(), tutorialId)
}
export function tutorialResultsDir(tutorialId: string): string {
  return path.join(tutorialProjectDir(tutorialId), "results")
}

export function providersConfigPath(): string {
  return expandHome(cfg<string>("providersConfig", "~/.config/ghbio/providers.json"))
}

// Run a shell command as a VS Code Task in the integrated terminal — reliable,
// visible, and user-stoppable (the whole point of moving off the old agent).
export async function runShellTask(name: string, command: string, cwd?: string, env?: Record<string, string>) {
  const options = cwd || env ? { cwd, env } : undefined
  const exec = new vscode.ShellExecution(command, options)
  const task = new vscode.Task(
    { type: "ghbio", id: name },
    vscode.TaskScope.Workspace,
    name,
    "GHBIO",
    exec,
  )
  task.presentationOptions = {
    reveal: vscode.TaskRevealKind.Always,
    panel: vscode.TaskPanelKind.Dedicated,
    focus: true,
    clear: false,
  }
  return vscode.tasks.executeTask(task)
}
