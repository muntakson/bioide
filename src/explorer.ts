import * as vscode from "vscode"
import { workspaceRootDir } from "./util"

// =============================================================================
// Explorer (side-bar folder view) navigation.
//
// The folder view is rooted at ONE folder. code-server opens ~/ghbio-workspace on
// startup, but opening an individual project (vscode.openFolder) narrows the root to
// that project dir — which then hides sibling folders like pipeline-drafts/. These
// helpers keep the Explorer pointed where the user is working:
//   • Home  → reset the root back to ~/ghbio-workspace (so projects/ + pipeline-drafts/
//             are both visible), collapsed to the top.
//   • Create-pipeline → reveal the pipeline-drafts/ folder (and the saved *_plan.md).
//
// Re-rooting means vscode.openFolder, which RELOADS the whole workbench — so we only do
// it when necessary (root is currently narrowed) and stash any reveal target to finish
// after activate() runs again. Revealing a path already inside the current root is cheap
// (no reload), so callers that must NOT lose in-progress webview state (Create-pipeline)
// pass reRoot:false and simply best-effort reveal.
// =============================================================================

const REVEAL_AFTER_RELOAD_KEY = "ghbio.revealAfterReload"

function currentRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
}

async function revealPath(p: string): Promise<void> {
  try {
    await vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(p))
  } catch {
    /* Explorer may not be ready / target may be outside the root — best effort. */
  }
}

// Reset the Explorer to ~/ghbio-workspace and show it collapsed at the top. If the root is
// already there, just collapse + focus (no reload). Otherwise re-open the workspace-root
// folder, which reloads the workbench; activate() reopens Home afterward (openHomeOnStartup).
export async function resetExplorerToWorkspaceRoot(context: vscode.ExtensionContext): Promise<void> {
  const root = workspaceRootDir()
  if (currentRoot() === root) {
    try {
      await vscode.commands.executeCommand("workbench.files.action.collapseExplorerFolders")
      await vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(root))
    } catch {
      /* best effort */
    }
    return
  }
  // Re-root needed: stash the root as the post-reload reveal target, then open it (reloads).
  await context.globalState.update(REVEAL_AFTER_RELOAD_KEY, root)
  await vscode.commands.executeCommand("vscode.openFolder", vscode.Uri.file(root), { forceNewWindow: false })
}

// Reveal `target` (a folder or file) in the Explorer WITHOUT ever reloading the workbench —
// safe to call while a webview panel (e.g. Create-pipeline) is open. Reveals only work when the
// target is inside the current root; if the root is narrowed the call quietly no-ops.
export async function revealInExplorerNoReload(target: string): Promise<void> {
  await revealPath(target)
}

// Called from activate() after a folder-reload to finish a pending reveal (root or file).
export function consumePendingReveal(context: vscode.ExtensionContext): void {
  const target = context.globalState.get<string>(REVEAL_AFTER_RELOAD_KEY)
  if (!target) return
  context.globalState.update(REVEAL_AFTER_RELOAD_KEY, undefined)
  const root = workspaceRootDir()
  setTimeout(() => {
    if (target === root) {
      vscode.commands
        .executeCommand("workbench.files.action.collapseExplorerFolders")
        .then(undefined, () => {})
    }
    revealPath(target)
  }, 600)
}
