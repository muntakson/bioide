import * as vscode from "vscode"
import * as fs from "fs"

// The "work folder" terminal — a single, reused VS Code *integrated* terminal (bottom panel) that
// follows the pipeline/project selected in the dashboard by `cd`-ing into its work folder, e.g.
//   jit@ghbio:~/ghbio-workspace/projects/scrna-seq-pbmc$
//
// This is deliberately the PANEL terminal (not the side-bar SSH terminal, which stays put on the
// codebase). It's a normal integrated terminal, so it's a real login shell with a real PTY — we
// just send it a `cd` when the selection changes. Pipeline "Run" tasks keep using their own
// dedicated task terminals; this one is the plain "where am I working" shell.

const TERM_NAME = "GHBIO 작업 폴더 (Work)"
let workTerm: vscode.Terminal | undefined

export function registerWorkTerminal(context: vscode.ExtensionContext) {
  // If the user closes it, forget it so the next follow re-creates it.
  context.subscriptions.push(
    vscode.window.onDidCloseTerminal((t) => {
      if (t === workTerm) workTerm = undefined
    }),
  )
}

// Reveal the work-folder terminal in `dir`, creating it there or `cd`-ing an existing one.
export function showWorkFolder(dir?: string) {
  if (!dir) return
  try {
    fs.mkdirSync(dir, { recursive: true }) // pipeline may not have been run yet
  } catch {
    /* best effort */
  }

  const alive = workTerm && workTerm.exitStatus === undefined
  if (!alive) {
    workTerm = vscode.window.createTerminal({ name: TERM_NAME, cwd: dir })
  } else {
    // Single-quote the path (escaping any embedded quote) so spaces/specials are safe.
    const quoted = "'" + dir.replace(/'/g, "'\\''") + "'"
    workTerm!.sendText(`cd ${quoted}`, true)
  }
  workTerm!.show(true) // reveal the panel without stealing focus from the dashboard
}
