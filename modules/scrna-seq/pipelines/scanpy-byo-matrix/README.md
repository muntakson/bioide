# Tutorial module: Scanpy — bring your own matrix

A short pipeline for when you **already have a 10x count matrix** (e.g. from Cell Ranger or a
previous STARsolo run) and just want QC → clustering → AI interpretation → report. It skips the
heavy STARsolo/reference steps.

## Use it
1. Put your 10x **filtered** matrix directory (containing `matrix.mtx`(.gz), `barcodes.tsv`(.gz),
   `features.tsv`(.gz)) at **`~/ghbio-workspace/my_matrix`** — or edit the `--matrix` path in
   `tutorial.json` step `qc`.
2. In the GHBIO **Tutorials** view, open *"Scanpy — bring your own matrix"* and run the steps top-down.
3. Outputs go to `~/ghbio-tutorial/results/` (same as the PBMC tutorial).

---

## This folder doubles as a TEMPLATE for new tutorials

To author a new GHBIO tutorial module for your team:

1. Copy this folder: `cp -r scanpy-byo-matrix ~/ghbio-coscientist/tutorials/<my-id>`
2. Edit **`tutorial.json`**:
   - `id` (unique), `name`, `summary`
   - `steps[]` — each step is:
     - `kind: "task"` → runs `run` (a shell command) in the integrated terminal as a VS Code Task,
       with the ▶/✅/→next banners. `run` is relative to this folder (scripts live here).
     - `kind: "ai"` → opens the AI Analysis panel (reads `~/ghbio-tutorial/results/*.csv`).
3. Drop any scripts the steps call into the folder.
4. Rebuild + install: `bash ~/ghbio-coscientist/build.sh`, then reload the browser tab.

Folders whose name starts with `_` are ignored by the loader (use `_wip-*` for drafts).
