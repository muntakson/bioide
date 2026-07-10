# GHBIO modules — how to add an analysis domain

The app is organized as a **registry of modules**. Each module is a self-contained
analysis domain (single-cell RNA-seq today; protein 3D modeling, spatial, variant
calling, … next). Adding a domain is **drop-in files — no TypeScript changes.**

## Layout

```
modules/
  scrna-seq/                 # a module = one domain
    module.json              # identity + libraries + AI config
    pipelines/
      scrna-seq-pbmc/        # a pipeline = one runnable workflow
        pipeline.json        # ordered stages (+ produces artifacts)
        00_setup_env.sh …    # the stage scripts
      scanpy-byo-matrix/
        pipeline.json …
  protein-3d/                # add a new domain by copying _template →
    module.json
    pipelines/…
  _template/                 # copy me; the leading "_" hides me from the app
```

Folders starting with `_` are ignored by the loader (templates/drafts).

## Add a new domain in 3 steps

1. `cp -r modules/_template modules/protein-3d` and edit `module.json`
   (`id`, `name`, `icon`, `description`, its `libraries`, and its `ai` prompts/system).
2. Add one or more `pipelines/<id>/pipeline.json`, each with ordered `stages`.
   Put the stage scripts next to it. Stage `kind`: `task` (runs `run` in the terminal)
   or `ai` (opens the AI panel). List each stage's outputs in `produces` so it shows ✓.
3. `bash build.sh` and reload the browser tab. The new domain appears automatically in
   **Pipelines** and **Libraries**, and its AI panel uses its own prompts.

## Contracts the app relies on

- **Results are first-class project files.** Scripts must write into `$GHBIO_RESULTS`
  (injected by the app; points at `~/ghbio-workspace/projects/<pipeline-id>/results`).
  A `produces` path is checked relative to that dir.
- **`module.json > ai.readyFile`** is the artifact whose presence means "analysis ready";
  the one-click *Run full analysis* opens the AI panel once it appears.
- **`module.json > ai.context`** lists the result files fed to the LLM as context
  (`topByRank: N` keeps only CSV rows whose 2nd column is 1..N — e.g. top-N markers).

Everything domain-specific lives in these manifests. The TypeScript engine
(`src/modules.ts`, `src/pipeline.ts`) stays generic, so the app scales as you add domains.
