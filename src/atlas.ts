import * as vscode from "vscode"

// The NSCLC Atlas explorer: an interactive single-cell RNA-seq teaching atlas
// (UMAP / gene feature plot / marker dot plot / composition + a guided tour,
// concept cards and live-checking exercises). It's a React app bundled by
// esbuild into media/atlas/atlas.bundle.js and rendered in a webview panel; the
// per-dataset {meta.json,expr.bin} live under media/atlas/<dir>/.
//
// Multiple datasets share the one bundle + CSS — only the injected data URIs
// differ. `window.__ATLAS__` tells the app which files to fetch.

interface AtlasDataset {
  title: string // webview tab title
  dir: string // media/atlas/<dir>/ holding meta.json + expr.bin
}

const ATLASES: Record<string, AtlasDataset> = {
  // synthetic teaching dataset (bundled) — the default
  synthetic: { title: "NSCLC 세포 아틀라스 (합성 · Synthetic)", dir: "." },
  // real Maynard 2020 lung adenocarcinoma data (scVI reanalysis, 21,620 cells)
  maynard: { title: "NSCLC 아틀라스 · Maynard 2020 (실제 · Real)", dir: "maynard" },
}

const panels = new Map<string, vscode.WebviewPanel>()

export function openAtlas(context: vscode.ExtensionContext, key = "synthetic") {
  const ds = ATLASES[key] ?? ATLASES.synthetic
  let panel = panels.get(key)
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioAtlas", ds.title, vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")],
    })
    panel.onDidDispose(() => panels.delete(key))
    panels.set(key, panel)
    panel.webview.html = html(panel.webview, context.extensionUri, ds)
  }
  panel.reveal()
}

function html(webview: vscode.Webview, extUri: vscode.Uri, ds: AtlasDataset): string {
  const atlas = (...p: string[]) => webview.asWebviewUri(vscode.Uri.joinPath(extUri, "media", "atlas", ...p))
  const bundle = atlas("atlas.bundle.js")
  const css = atlas("atlas.css")
  // ds.dir === "." keeps the synthetic files at media/atlas/{meta.json,expr.bin}
  const dataDir = ds.dir === "." ? [] : [ds.dir]
  const metaUri = atlas(...dataDir, "meta.json")
  const exprUri = atlas(...dataDir, "expr.bin")

  let nonce = ""
  for (let i = 0; i < 24; i++)
    nonce += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".charAt(Math.floor(Math.random() * 62))

  const csp =
    `default-src 'none'; ` +
    `style-src ${webview.cspSource} 'unsafe-inline'; ` +
    `font-src ${webview.cspSource}; ` +
    `img-src ${webview.cspSource} data:; ` +
    `connect-src ${webview.cspSource}; ` +
    `script-src 'nonce-${nonce}' ${webview.cspSource};`

  return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="${css}" />
  <style>html,body,#root{height:100%;margin:0;background:#020617;}</style>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">window.__ATLAS__ = { metaUri: "${metaUri}", exprUri: "${exprUri}" };</script>
  <script nonce="${nonce}" src="${bundle}"></script>
</body>
</html>`
}
