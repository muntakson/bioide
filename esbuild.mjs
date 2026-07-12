import esbuild from "esbuild"
import { execSync, spawn } from "node:child_process"

const watch = process.argv.includes("--watch")

// --- NSCLC Atlas webview CSS (Tailwind, compiled to a static file) ----------
// The webview can't run PostCSS at runtime, so we precompile the utility CSS the
// atlas components use into media/atlas/atlas.css.
const TW = "node_modules/.bin/tailwindcss"
const TW_ARGS = "-c tailwind.atlas.config.js -i webview-src/atlas/globals.css -o media/atlas/atlas.css --minify"
function buildAtlasCss() {
  execSync(`${TW} ${TW_ARGS}`, { stdio: "inherit" })
}

// --- extension host bundle (Node / CJS) -------------------------------------
const extCtx = await esbuild.context({
  entryPoints: ["src/extension.ts"],
  bundle: true,
  platform: "node",
  target: "node18",
  format: "cjs",
  outfile: "dist/extension.js",
  external: ["vscode"],
  sourcemap: true,
  logLevel: "info",
})

// --- NSCLC Atlas webview bundle (browser / IIFE, React) ---------------------
const atlasCtx = await esbuild.context({
  entryPoints: ["webview-src/atlas/main.tsx"],
  bundle: true,
  platform: "browser",
  target: ["chrome100"],
  format: "iife",
  outfile: "media/atlas/atlas.bundle.js",
  jsx: "automatic",
  tsconfig: "webview-src/atlas/tsconfig.json",
  define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"' },
  minify: !watch,
  sourcemap: true,
  logLevel: "info",
})

if (watch) {
  buildAtlasCss()
  // keep the atlas CSS in sync while developing
  spawn(TW, [...TW_ARGS.split(" "), "--watch"], { stdio: "inherit" })
  await Promise.all([extCtx.watch(), atlasCtx.watch()])
} else {
  buildAtlasCss()
  await Promise.all([extCtx.rebuild(), atlasCtx.rebuild()])
  await Promise.all([extCtx.dispose(), atlasCtx.dispose()])
}
