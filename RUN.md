# GHBIO Co-Scientist — Operations Guide (code-server + extension)

A **VS Code IDE in the browser** (code-server) at **https://ghbiocosci.iotok.org**, with the
**GHBIO Co-Scientist** extension (PlatformIO-style: Tutorials / Projects / Libraries + a reliable
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
