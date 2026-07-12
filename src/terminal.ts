import * as vscode from "vscode"
import * as cp from "child_process"
import * as fs from "fs"
import * as os from "os"
import { cfg, expandHome } from "./util"

// A persistent, project-independent shell in the side bar.
//
// Why this exists: pipeline stages run as VS Code Tasks in the *panel* terminal, which is
// recycled/re-titled as the user moves between projects. Users wanted ONE stable shell — to work on
// the ghbio-coscientist codebase and drive the `claude` agentic-LLM CLI — that opens with the
// workbench and lives for the whole code-server session, NEVER changing with the active pipeline.
// (Following the selected pipeline into its work folder is the *panel* terminal's job — see
// workterminal.ts; this side-bar shell deliberately stays put in the codebase dir.)
//
// The extension host runs server-side on the box (code-server), so "SSH into the remote desktop"
// is just a login shell on this same machine as the current user — the same environment the
// browser IDE already gives. We back it with util-linux `script` to get a real PTY (colors,
// arrow keys, TUIs like `claude`) WITHOUT shipping a native node-pty binary. The shell command is
// configurable via `ghbio.terminalCommand`, so it can be pointed at a real `ssh host` if ever needed.
//
// The backend process is owned by the extension host, not the webview, so it survives the webview
// being hidden AND a browser tab reload — it only dies when code-server itself stops (i.e. the
// "remote desktop" disconnects) or the user restarts it.

const MAX_REPLAY = 256 * 1024 // bytes of recent output replayed into a freshly-loaded webview

class ShellSession {
  private child?: cp.ChildProcess
  private ptsPath?: string
  private replay = "" // tail of recent output, to restore the screen after a tab reload
  private cols = 80
  private rows = 24
  private onData?: (s: string) => void
  private onExit?: (code: number | null) => void

  alive(): boolean {
    return !!this.child && this.child.exitCode === null && !this.child.killed
  }

  bind(onData: (s: string) => void, onExit: (code: number | null) => void) {
    this.onData = onData
    this.onExit = onExit
  }

  /** Recent output, so a reconnecting webview can repaint the screen. */
  snapshot(): string {
    return this.replay
  }

  start() {
    if (this.alive()) return
    const shellCmd = (cfg<string>("terminalCommand", "") || "bash -il").trim()
    // Stable working dir: the configured codebase dir (defaults to ~/ghbio-coscientist), then home.
    const cwdCfg = cfg<string>("terminalCwd", "")
    let cwd = cwdCfg ? expandHome(cwdCfg) : os.homedir()
    if (!cwd || !fs.existsSync(cwd)) cwd = os.homedir()

    // Set the initial PTY size before exec'ing the shell so the first paint matches the panel.
    const inner = `stty rows ${this.rows} cols ${this.cols} 2>/dev/null; exec ${shellCmd}`
    this.child = cp.spawn("script", ["-q", "-c", inner, "/dev/null"], {
      cwd,
      env: { ...process.env, TERM: "xterm-256color", GHBIO_TERMINAL: "1" },
    })
    this.ptsPath = undefined
    this.replay = ""

    const pump = (buf: Buffer) => {
      const s = buf.toString("utf8")
      this.replay += s
      if (this.replay.length > MAX_REPLAY) this.replay = this.replay.slice(-MAX_REPLAY)
      this.onData?.(s)
    }
    this.child.stdout?.on("data", pump)
    this.child.stderr?.on("data", pump)
    this.child.on("exit", (code) => {
      this.child = undefined
      this.ptsPath = undefined
      this.onExit?.(code)
    })
  }

  write(data: string) {
    if (this.alive()) this.child!.stdin?.write(data)
  }

  resize(cols: number, rows: number) {
    if (cols > 0) this.cols = cols
    if (rows > 0) this.rows = rows
    const pts = this.findPts()
    if (!pts) return
    // ioctl(TIOCSWINSZ) via stty; the kernel then delivers SIGWINCH to the shell/app so it reflows.
    cp.execFile("stty", ["-F", pts, "cols", String(this.cols), "rows", String(this.rows)], () => {})
  }

  // Locate the login shell's controlling tty (a /dev/pts/N) by walking from `script` to its child.
  private findPts(): string | undefined {
    if (this.ptsPath) return this.ptsPath
    const pid = this.child?.pid
    if (!pid) return undefined
    try {
      const kids = fs
        .readFileSync(`/proc/${pid}/task/${pid}/children`, "utf8")
        .trim()
        .split(/\s+/)
        .filter(Boolean)
      for (const k of kids) {
        try {
          const tty = fs.readlinkSync(`/proc/${k}/fd/0`)
          if (tty.startsWith("/dev/pts/")) {
            this.ptsPath = tty
            return tty
          }
        } catch {
          /* child may have exited between read and readlink */
        }
      }
    } catch {
      /* /proc children not available yet */
    }
    return undefined
  }

  dispose() {
    // SIGHUP so the shell and any child (e.g. claude) tear down like a real logout.
    this.child?.kill("SIGHUP")
    this.child = undefined
    this.ptsPath = undefined
  }
}

export class TerminalViewProvider implements vscode.WebviewViewProvider {
  static readonly viewId = "ghbio.terminal"
  private session = new ShellSession()
  private view?: vscode.WebviewView

  constructor(private readonly extUri: vscode.Uri) {}

  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extUri, "media")],
    }

    this.session.bind(
      (s) => view.webview.postMessage({ type: "data", data: s }),
      (code) => view.webview.postMessage({ type: "exit", code }),
    )

    view.webview.html = this.html(view.webview)

    view.webview.onDidReceiveMessage((m) => {
      switch (m?.type) {
        case "ready":
          // The webview (re)loaded — after a tab reload the backend shell is still alive, so
          // repaint its recent output; otherwise start a fresh session.
          if (this.session.alive()) {
            const snap = this.session.snapshot()
            if (snap) view.webview.postMessage({ type: "data", data: snap })
          } else {
            this.session.start()
          }
          return
        case "input":
          this.session.write(String(m.data ?? ""))
          return
        case "resize":
          this.session.resize(Number(m.cols) || 0, Number(m.rows) || 0)
          return
        case "restart":
          this.session.dispose()
          view.webview.postMessage({ type: "clear" })
          this.session.start()
          return
      }
    })
  }

  /** Tear down the shell and start a fresh one (also driven by the webview's ↻ button). */
  restart() {
    this.session.dispose()
    this.view?.webview.postMessage({ type: "clear" })
    this.session.start()
  }

  dispose() {
    this.session.dispose()
  }

  private html(webview: vscode.Webview): string {
    const uri = (...p: string[]) =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extUri, "media", "vendor", ...p))
    const xtermJs = uri("xterm.js")
    const xtermCss = uri("xterm.css")
    const fitJs = uri("addon-fit.js")
    let nonce = ""
    for (let i = 0; i < 24; i++) nonce += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".charAt(Math.floor(Math.random() * 62))
    const csp =
      `default-src 'none'; ` +
      `style-src ${webview.cspSource} 'unsafe-inline'; ` +
      `font-src ${webview.cspSource}; ` +
      `img-src ${webview.cspSource} data:; ` +
      `script-src 'nonce-${nonce}' ${webview.cspSource};`
    return /* html */ `<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<link rel="stylesheet" href="${xtermCss}">
<style>
  html,body{height:100%;margin:0;background:#0b0f14}
  #bar{display:flex;align-items:center;gap:8px;padding:5px 8px;background:#0d1117;border-bottom:1px solid #21262d;
       font:12px -apple-system,"Segoe UI",system-ui,sans-serif;color:#8b98a5}
  #bar b{color:#2dd4bf;font-weight:600}
  #bar .sp{flex:1}
  #bar button{cursor:pointer;background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;
       padding:3px 9px;font:inherit}
  #bar button:hover{border-color:#2dd4bf}
  #term{position:absolute;top:31px;left:0;right:0;bottom:0;padding:4px 6px;box-sizing:border-box}
  .xterm{height:100%}
</style></head>
<body>
  <div id="bar"><b>GHBIO</b> SSH Terminal <span style="color:#5b6672">· ${os.hostname()}</span>
    <span class="sp"></span>
    <button id="claude" title="claude 실행">▶ claude</button>
    <button id="restart" title="세션 재시작">↻</button>
  </div>
  <div id="term"></div>
  <script nonce="${nonce}" src="${xtermJs}"></script>
  <script nonce="${nonce}" src="${fitJs}"></script>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi()
    const FitAddonCtor = (window.FitAddon && window.FitAddon.FitAddon) || window.FitAddon
    const term = new Terminal({
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      cursorBlink: true,
      scrollback: 5000,
      theme: { background: '#0b0f14', foreground: '#e6edf3', cursor: '#2dd4bf' },
    })
    const fit = new FitAddonCtor()
    term.loadAddon(fit)
    term.open(document.getElementById('term'))

    function doFit(){
      try { fit.fit() } catch (e) {}
      vscode.postMessage({ type: 'resize', cols: term.cols, rows: term.rows })
    }
    // Fit after layout settles, then whenever the view is resized.
    setTimeout(doFit, 40)
    new ResizeObserver(() => doFit()).observe(document.getElementById('term'))

    term.onData(d => vscode.postMessage({ type: 'input', data: d }))
    document.getElementById('restart').onclick = () => vscode.postMessage({ type: 'restart' })
    document.getElementById('claude').onclick = () => { term.focus(); vscode.postMessage({ type: 'input', data: 'claude\\r' }) }

    window.addEventListener('message', ev => {
      const m = ev.data
      if (m.type === 'data') term.write(m.data)
      else if (m.type === 'clear') term.reset()
      else if (m.type === 'exit') term.write('\\r\\n\\x1b[2m[프로세스 종료됨 — ↻ 로 재시작] (session ended)\\x1b[0m\\r\\n')
    })

    // Tell the extension we're mounted; it starts (or reattaches to) the shell and syncs size.
    doFit()
    vscode.postMessage({ type: 'ready' })
  </script>
</body></html>`
  }
}
