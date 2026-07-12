# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **VS Code / code-server extension** ("GHBIO Co-Scientist", branded **BioIDE**) — a PlatformIO-style
bioinformatics workbench for biologists. It runs inside browser-based code-server at
https://ghbiocosci.iotok.org. The UX is **GHBIO Home → a tutorial's Dashboard**, plus a reliable
single-shot **AI Analysis** panel and AI-drafted reports/papers. Users are Korean biologists with no
Copilot; UI strings are bilingual (Korean primary), and AI replies in Korean by default.

`RUN.md` is the operations guide (services, hosting, the code-server config that lives outside this
repo). Read it before touching anything deployment-related.

## Build / develop / deploy

There is **no test suite and no linter** configured — don't invent commands for them.

- **Bundle only:** `npm run build` (runs `node esbuild.mjs`; entry `src/extension.ts` → `dist/extension.js`, CJS, `vscode` external). `npm run watch` for incremental. Also bundles the atlas React app (see below).
- **Typecheck:** `npx tsc --noEmit -p .` — esbuild does NOT type-check, so run this before shipping. The atlas webview has its own project: `npx tsc --noEmit -p webview-src/atlas/tsconfig.json`.
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
- `modules/<id>/module.json` — identity, `libraries[]` (installable tools + `presentPath` existence check), and default `ai` config (system prompt, preset `prompts`, result-file `context`, `readyFile`).
- `modules/<id>/pipelines/<pid>/pipeline.json` — a pipeline's stages, `dataSource`, per-pipeline `help`, and an optional per-pipeline `ai` block.
- **AI config resolves as `{ ...module.ai, ...pipeline.ai }` (shallow, per-key).** A pipeline overrides only the keys it sets (e.g. a domain-specific `system`/`prompts`) and inherits the rest. `module.json`'s default `ai` is PBMC-flavored, so lung/T-cell pipelines override `system`+`prompts`.
- Directories prefixed with `_` (e.g. `_template`, `_wip-*`) are **ignored** by the loader.
- Back-compat: a legacy flat `tutorials/` dir loads as one default module when `modules/` is absent.

Adding a domain/pipeline requires **no TypeScript changes** — every surface reads these manifests.

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
project dir: `~/ghbio-workspace/projects/<pipelineId>/results/` (surfaced on the Dashboard). **Any
script a pipeline runs MUST read `GHBIO_RESULTS`** (falling back to the legacy
`~/ghbio-tutorial/results`, which is a symlink). A script that hardcodes the legacy path writes into
the wrong project and the AI/report steps won't find its output — this has been a real bug. Heavy
shared inputs (FASTQ, GRCh38 index, ~40 GB) stay under `~/ghbio-tutorial/` and are reused idempotently.

### AI Analysis panel (`src/ai/panel.ts`, `src/ai/providers.ts`)
A webview that makes **one streaming request** to an LLM and renders the answer — **no agent, no
tools, no file edits**, cancelable with Stop. This "reliability fix" is the whole point; do not
reintroduce tool/agent loops here.
- Providers: `anthropic`, `groq`, `openrouter`, `deepseek` (OpenAI-compatible). Keys in `~/.config/ghbio/providers.json` (chmod 600) — outside the repo.
- The resolved `ai.context` result CSVs are read into the prompt. **Preset prompts** require result files to exist and are cached under `<results>/.ai_cache/`; **free-form questions** are answered anytime (results attached only when present).

### Report & paper generation (a cross-cutting concern — keep it consistent)
Turning results into human-readable documents happens in three layered ways; when adding/editing a
pipeline, mirror the **melanoma-tirosh** and **gpu-modern-reanalysis** pipelines (the reference impls):
- **Save-to-report buttons** in the AI panel write `step4_ai_report_easy.md` / `step4_ai_report.md` into the results dir. The pipeline's `05_make_report.sh` folds these in **optionally** — the QC PDF builds from figures alone when absent.
- **`ai.easyReport` (the "🎓 고등학생 버전 보고서" one-click button).** Spec fields (`EasyReportSpec` in `modules.ts`): `label, makeReport, paperClaim, title, datasetLabel`. It fuses three inputs — the monumental paper's conclusion (`paperClaim`), the result CSVs, and saved AI drafts — into a metaphor-rich easy Korean report, then runs `makeReport` to build a PDF. **Filename contract:** the panel opens a fixed path `<results>/GHBIO_고등학생_리포트.pdf`, so `makeReport` MUST emit exactly that name (the self-contained `05_make_easy_report.sh` per pipeline does this; melanoma instead reuses its figure-rich `05_make_report.sh` with a different name). `title`/`datasetLabel` exist because the handler used to hardcode lung-cancer text — always set them per pipeline.
- **Science-paper writer (`src/paper.ts`, `ghbio.writePaper`).** A separate webview that drafts a full paper grounded in real results, in three modes writing distinctly-named files: `edu` (교육 논문), `research` (bioinformatics reproduction), `research_hs` (high-school storytelling of the research paper) → `<pipelineId>_{edu,research,research_hs}_paper.{md,pdf}`.

### UI surfaces (all plain-HTML webviews unless noted)
`activate()` (`src/extension.ts`) tracks an **`activePipelineId`** (workspaceState, persisted) — the
last pipeline the user touched — and context-aware surfaces follow it.
- **Home (`src/home.ts`, `ghbio.openHome`)** — the landing card grid; opens on startup.
- **Dashboard (`src/dashboard.ts`, `ghbio.openDashboard`)** — PlatformIO-Home-style per-tutorial/project view: step checklist, library status, context Help, and live download/align/setup **status boxes** that poll the extension (`dlstatus`/`alignstatus`/`setupstatus` messages). One renderer serves both tutorials and plain projects (a tutorial *is* a project scaffolded by `ensureProject`).
- **Help (`src/help.ts`, `ghbio.openHelp`)** — walkthrough + glossary tailored to `activePipelineId`, read from the pipeline's `help` block.
- **Survey (`src/survey.ts`, `ghbio.openSurvey`/`openSurveyStats`)** — 이해도 테스트: form + aggregated stats, questions in the pipeline's `survey.json`, JSONL+CSV backend under `<results>/survey/`, server-side scoring. Surfaced via `ai.survey` in the manifest.
- **Dataset catalog (`src/catalog.ts`, `ghbio.openDatasetCatalog`)** — reference list of verified public 10x 3′ FASTQ datasets + tar sizes; entries with `inApp` already ship as a pipeline.
- **Sidebar SSH terminal (`src/terminal.ts`, view `ghbio.terminal`)** — the ONE registered `WebviewViewProvider`; a persistent PTY (util-linux `script`, no node-pty) kept alive for the whole code-server session, `retainContextWhenHidden` so a tab reload repaints instead of dropping the shell. **`src/workterminal.ts`** is a separate *panel* terminal that follows the Dashboard into each project's work folder (the sidebar terminal stays on the codebase).

> The old Pipelines/Projects/Libraries **activity-bar trees were removed** (redundant with Home→Dashboard). `TutorialProvider`/`ProjectProvider`/`LibraryProvider` still exist as data sources for Home and the `newProject`/`installLibrary` commands, but are no longer surfaced as trees.

### NSCLC Atlas explorer (`src/atlas.ts`, `webview-src/atlas/`)
A **React** teaching webview (interactive UMAP / gene feature plot / marker dot plot / composition +
guided tour, concept cards, live-checking exercises) — opened by `ghbio.openAtlas` from a Home card.
Unlike every other panel (which builds a plain HTML string), this one is a bundled React app:
- **Source** lives in `webview-src/atlas/` (vendored from the standalone Next.js `nsclc-atlas` app, Next stripped — every component is a pure client component). `esbuild.mjs` has a **second context** that bundles `webview-src/atlas/main.tsx` → `media/atlas/atlas.bundle.js` (browser/IIFE). `@/…` path aliases resolve via `webview-src/atlas/tsconfig.json`.
- **Tailwind** classes are compiled to a **static** `media/atlas/atlas.css` at build time (the webview can't run PostCSS) — `esbuild.mjs` shells out to the `tailwindcss` CLI with `tailwind.atlas.config.js`.
- **Data**: the synthetic dataset ships as `media/atlas/{meta.json,expr.bin}` (uint8 cell-major expr, ≈0.6 MB). `src/atlas.ts` injects their `asWebviewUri`s on `window.__ATLAS__`; `lib/data.ts` fetches those (falling back to Next's `/data/*` so the standalone app still runs). Swap in real published data by regenerating those two files with `media/atlas/scripts/convert_h5ad.py` — no frontend change.

## Deployment context (code-server, outside this repo)
The extension runs in code-server, whose user settings/config live **outside the repo** and must be
re-applied after a code-server upgrade (see `RUN.md`). Notably:
- `~/.local/share/code-server/User/settings.json` disables the built-in Copilot/chat, excludes large sequence files (`*.fastq*`, `*.bam`) from the Explorer/watcher/search, and uses `remote.extensionKind` to force `extensionKind:["ui"]` extensions (e.g. the PDF viewer) to run server-side so code-server doesn't auto-disable them.
- This box is **aarch64** (STARsolo is built from source; no Cell Ranger). Python venv at `~/ghbio-venv`.
