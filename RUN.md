# BioIDE — Operations Guide (code-server + extension)

A **VS Code IDE in the browser** (code-server) at **https://ghbiocosci.iotok.org**, with the
**BioIDE** extension (PlatformIO-style: Tutorials / Projects / Libraries + a reliable
single-shot **AI Analysis** panel). Replaces the retired OpenScience app.

## Access
- URL: **https://ghbiocosci.iotok.org** · password auth (code-server).
- Password: in `~/.config/code-server/config.yaml` (`password:`). Change it there + `systemctl --user restart ghbio-code`.
- ⚠️ The IDE gives a full terminal/shell on this box. The password gate is the access control; add
  Cloudflare Access (Zero Trust) in front for stronger auth if needed.

## Services (systemd --user, lingering on)
| Service | Role |
|---|---|
| **ghbio-code** | code-server (VS Code) on `127.0.0.1:8080`, opens `~/ghbio-workspace` |
| **ghbio-tunnel** | cloudflared → `ghbiocosci.iotok.org` → `127.0.0.1:8080` |
| ~~ghbio-app~~ | old OpenScience app — **disabled/retired** |

```bash
systemctl --user status|restart ghbio-code ghbio-tunnel
journalctl --user -u ghbio-code -n 50 --no-pager
```

## The extension
- Source: **`~/ghbio-coscientist/`** (TypeScript, esbuild). Installed copy lives under
  `~/.local/share/code-server/extensions/ghbio.ghbio-coscientist-*`.
- **Rebuild + reinstall after editing:** `bash ~/ghbio-coscientist/build.sh` then reload the browser tab.
  (Note: the upstream `@vscode/vsce` is broken on this box's Node 18 — `build.sh` builds the `.vsix`
  manually with `zip`, no `vsce` needed.)
- Structure: `src/extension.ts` (activate) · `src/tutorials.ts` · `src/projects.ts` · `src/libraries.ts`
  · `src/home.ts` · `src/ai/{panel,providers}.ts`. Tutorial modules in `tutorials/<id>/tutorial.json`.

## AI Analysis (the reliability fix)
- A webview panel that makes **one streaming request** to the LLM (Anthropic/Groq/OpenRouter/DeepSeek)
  and renders the answer. **No agent, no tools, no file edits, no wandering** — cancelable with Stop.
- Keys: **`~/.config/ghbio/providers.json`** (`{ "anthropic": {"apiKey": "..."}, ... }`, chmod 600).
- It reads `~/ghbio-tutorial/results/{markers_by_cluster,celltype_draft}.csv`, so run tutorial Step 3 first.

## The scRNA-seq pipeline as a Deep Module (`src/pipeline.ts`)
- The scRNA-seq analysis is the app's **core deep module**: a narrow interface —
  `runPipeline()` (run all / resume `from` a stage), `stageStatus()`/`isStageDone()`,
  `loadPipeline()`, `ensureProject()` — over a deep implementation that hides stage
  ordering, project scaffolding, `GHBIO_RESULTS` injection, idempotency, and the AI hand-off.
- Every surface builds on this one interface: the **Tutorials tree** (per-step runs +
  ✓ done markers via `isStageDone`), the **▶▶ Run-full button** (`ghbio.runPipeline`),
  Home, and the welcome view. A future **HTTP endpoint** should call the same functions —
  it is the intended skeleton for "AI-as-a-webservice", so keep UI (vscode) out of the core.
- Pipeline spec = `tutorials/<id>/tutorial.json`; each stage may declare `produces: [...]`
  (result artifacts, relative to `results/`) that mark it complete. `CORE_PIPELINE_ID`
  designates the default pipeline (`scrna-seq-pbmc`); drop in more via `loadPipeline(id)`.
- **Results are first-class project files:** outputs live in
  `~/ghbio-workspace/projects/<id>/results/` (shown in the Projects view). The legacy
  `~/ghbio-tutorial/results` is a **symlink** to the project; scripts honor `GHBIO_RESULTS`
  and fall back to that path. Heavy inputs (FASTQ, GRCh38 index) stay shared under
  `~/ghbio-tutorial/` and are surfaced in the project via `inputs-fastq`/`reference-grch38` symlinks.

## Disabling the built-in Copilot / "Build with Agent" chat
Users are biologists with no Copilot subscription, and Copilot can't run on code-server anyway —
the native chat only produced a "Sign in to use GitHub Copilot" wall. It's disabled two ways
(both **outside the repo**, so re-apply after a code-server upgrade):
- **User settings** `~/.local/share/code-server/User/settings.json` (backup: `settings.json.bak`):
  `"chat.disableAIFeatures": true`, `"chat.agent.enabled": false`, `"chat.commandCenter.enabled": false`.
- **product.json** `~/.local/lib/code-server-<ver>/lib/vscode/product.json` (backup: `product.json.ghbio-bak`):
  removed the `defaultChatAgent` key (pointed at `GitHub.copilot`), so the setup flow has no agent.

All AI goes through the GHBIO **AI Analysis** panel instead (the user's own GROQ/Anthropic key).
The panel answers **free-form questions anytime** (e.g. "what is FASTQ?") — results are attached as
context only for the preset prompts / when present.

## Add a new tutorial (PlatformIO-library style)
1. `mkdir ~/ghbio-coscientist/tutorials/<id>/`; add `tutorial.json`
   (`{ id, name, summary, steps:[{ id, title, ko, kind:"task"|"ai", run }] }`) + any scripts.
2. `kind:"task"` steps run their `run` command as a VS Code Task in the integrated terminal (with
   ▶/✅/→next banners); `kind:"ai"` opens the AI panel.
3. `bash ~/ghbio-coscientist/build.sh`, reload the tab.

## scRNA-seq pipeline (preserved)
- Tutorial module `tutorials/scrna-seq-pbmc/` wraps the validated scripts (00–05). Steps are **idempotent**
  — they reuse the ~40 GB data/index under `~/ghbio-tutorial/` (no re-download/re-index).
- Libraries view shows STAR / Python-Scanpy / GRCh38-index status with one-click install/build.
- Python venv: `~/ghbio-venv`. This box is **aarch64** (STARsolo built from source; no Cell Ranger).

## Notes
- `~/openscience` is **archived, not deleted** (original source of the reused scripts). Safe to remove
  once you're happy with the new module.
