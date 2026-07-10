# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **VS Code / code-server extension** ("GHBIO Co-Scientist") — a PlatformIO-style bioinformatics
workbench for biologists. It runs inside browser-based code-server at https://ghbiocosci.iotok.org.
The extension provides tree views (Pipelines / Projects / Libraries) and a reliable single-shot
**AI Analysis** panel. Users are Korean biologists with no Copilot; UI strings are bilingual
(Korean primary), and the AI panel replies in Korean by default.

`RUN.md` is the operations guide (services, hosting, the code-server config that lives outside this
repo). Read it before touching anything deployment-related.

## Build / develop / deploy

There is **no test suite and no linter** configured — don't invent commands for them.

- **Bundle only:** `npm run build` (runs `node esbuild.mjs`; entry `src/extension.ts` → `dist/extension.js`, CJS, `vscode` external). `npm run watch` for incremental.
- **Typecheck:** `npx tsc --noEmit -p .` — esbuild does NOT type-check, so run this to catch type errors before shipping.
- **Full deploy:** `bash build.sh` — bundles, packages the `.vsix` **manually with `zip`** (upstream `@vscode/vsce` is broken on this box's Node 18), installs into code-server, and restarts the `ghbio-code` systemd service.

### Deploy gotchas (these bite silently)
- **Bump `package.json` "version" before reinstalling.** code-server serves a *stale* copy when reinstalling over the same version. After install, remove the old dir: `rm -rf ~/.local/share/code-server/extensions/ghbio.ghbio-coscientist-<OLD>` then `systemctl --user restart ghbio-code`.
- The user must **hard-refresh the browser tab (Ctrl+Shift+R)** to pick up a new bundle.
- esbuild escapes Korean strings to `\uXXXX` in `dist/extension.js`, so grepping the bundle for literal Hangul returns 0 hits. **Grep the source, not the bundle.**

## Architecture

The design goal is a **data-driven registry** so new analysis domains are added by dropping in files,
not editing TypeScript.

### Module registry (`src/modules.ts`)
A *module* = one analysis domain (scRNA-seq today; protein modeling tomorrow). Everything
domain-specific is declared in JSON, read at runtime:
- `modules/<id>/module.json` — identity, `libraries[]` (installable tools + `presentPath` existence check), and `ai` config (system prompt, preset `prompts`, result-file `context`, `readyFile`).
- `modules/<id>/pipelines/<pid>/pipeline.json` — a pipeline's stages.
- Directories prefixed with `_` (e.g. `_template`, `_wip-*`) are **ignored** by the loader.
- Back-compat: a legacy flat `tutorials/` dir loads as one default module when `modules/` is absent.

Adding a domain requires **no TypeScript changes** — the tree, Libraries view, and AI panel all read these manifests.

### Pipeline engine (`src/pipeline.ts`) — the core "deep module"
A narrow interface (`runPipeline` / `stageStatus` / `isStageDone` / `loadPipelineFromDir` /
`ensureProject`) over an implementation that hides stage ordering, project scaffolding,
`GHBIO_RESULTS` injection, idempotency, and the AI hand-off. **Keep `vscode` UI concerns out of this
file** — it is intended to also back a future headless HTTP "AI-as-a-webservice", so it operates on
plain `Pipeline` values handed to it.
- A stage has `kind: "task"` (runs `run` as a VS Code shell Task in the terminal, with ▶/✅/→next banners) or `kind: "ai"` (opens the AI panel). A stage may declare `produces: [...]` (artifacts relative to the results dir) → `isStageDone` marks it ✓ complete.
- `pipeline.json` is preferred; legacy `tutorial.json` and a `steps` key are still parsed.

### Results are first-class project files — `GHBIO_RESULTS` is load-bearing
Every stage/step is launched with the env var **`GHBIO_RESULTS`** pointing at that pipeline's OWN
project dir: `~/ghbio-workspace/projects/<pipelineId>/results/` (surfaced in the Projects view).
**Any script a pipeline runs MUST read `GHBIO_RESULTS`** (falling back to the legacy
`~/ghbio-tutorial/results`, which is a symlink). A script that hardcodes the legacy path writes into
the wrong project and the AI/report steps won't find its output — this has been a real bug. Heavy
shared inputs (FASTQ, GRCh38 index, ~40 GB) stay under `~/ghbio-tutorial/` and are reused idempotently.

### AI Analysis panel (`src/ai/panel.ts`, `src/ai/providers.ts`)
A webview that makes **one streaming request** to an LLM and renders the answer — **no agent, no
tools, no file edits**, cancelable with Stop. This "reliability fix" is the whole point; do not
reintroduce tool/agent loops here.
- Providers: `anthropic`, `groq`, `openrouter`, `deepseek` (OpenAI-compatible). Keys in `~/.config/ghbio/providers.json` (chmod 600) — outside the repo.
- The module's `ai.context` result CSVs are read into the prompt. **Preset prompts** require result files to exist; **free-form questions** are answered anytime (results attached only when present).
- "Save answer to report" buttons write `step4_ai_report_easy.md` / `step4_ai_report.md` into the results dir (shown only after a preset prompt). `05_make_report.sh` folds these in **optionally** — the PDF builds from QC outputs alone when they're absent.

### Entry point (`src/extension.ts`)
`activate()` registers the three tree providers and the `ghbio.*` commands. Command IDs and view
contributions live in `package.json` under `contributes`.

## Deployment context (code-server, outside this repo)
The extension runs in code-server, whose user settings/config live **outside the repo** and must be
re-applied after a code-server upgrade (see `RUN.md`). Notably:
- `~/.local/share/code-server/User/settings.json` disables the built-in Copilot/chat, excludes large sequence files (`*.fastq*`, `*.bam`) from the Explorer/watcher/search, and uses `remote.extensionKind` to force `extensionKind:["ui"]` extensions (e.g. the PDF viewer) to run server-side so code-server doesn't auto-disable them.
- This box is **aarch64** (STARsolo is built from source; no Cell Ranger). Python venv at `~/ghbio-venv`.
