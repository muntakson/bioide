import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { runShellTask, tutorialProjectDir, tutorialResultsDir, expandHome, stepLogTee } from "./util"
import type { AiConfig } from "./modules"

// =============================================================================
// A pipeline as a DEEP MODULE engine.
//
// Design (Ousterhout): a *narrow* interface — run a pipeline end-to-end, resume
// from a stage, query which stages are done, scaffold its project — over a *deep*
// implementation that hides stage ordering, GHBIO_RESULTS injection, idempotency,
// error-stop chaining, and the hand-off to AI. This engine is domain-agnostic: it
// operates on a Pipeline value it is handed. The module registry (modules.ts)
// decides WHICH pipelines exist; this file knows only how to RUN one.
// =============================================================================

export type StageKind = "env" | "data" | "build" | "compute" | "ai" | "report" | "task"

export interface Stage {
  id: string
  title: string
  ko?: string
  kind: StageKind | "task" | "ai"
  run?: string // shell command, relative to the pipeline dir
  produces?: string[] // artifacts (relative to results/) that mark this stage complete
  presentPath?: string // ~-expanded ABSOLUTE path; exists ⇒ complete. For outputs that live
  // outside results/ (e.g. downloaded FASTQ under the shared ~/ghbio-tutorial/ input dir).
  desc?: string
}

// Optional, data-driven help content for the context-aware 사용설명서 (help.ts).
// Everything domain-specific about a tutorial's help lives here, not in TypeScript,
// so a new pipeline gets its own tailored help by dropping JSON into pipeline.json.
export interface PipelineHelp {
  intro?: string // ko paragraph: what this dataset is and what you'll experience
  steps?: Record<string, string> // stageId → friendly ko description shown in the walkthrough
  glossary?: { term: string; def: string }[] // domain-specific terms appended to the shared glossary
}

// Provenance for the "프로젝트 정보 (Project info)" dashboard card — declared in pipeline.json so
// each dataset documents where its raw data came from without any TypeScript change.
export interface DataSource {
  provider?: string // e.g. "10x Genomics"
  dataset?: string // human dataset name
  datasetUrl?: string // dataset landing page
  fastqUrl?: string // the actual FASTQ download (tar) URL
  size?: string // e.g. "~19 GB"
  note?: string // any extra ko note
  rationale?: string // why THIS paper/dataset was chosen for the tutorial (shown on the info card)
  // Local download target, so the dashboard can show a live download-progress log.
  download?: {
    tar: string // path to the downloading .tar/.bam (supports leading ~)
    totalBytes?: number // expected final size, for a % readout
    extracted?: string // a path that exists once extraction is done (marks "complete")
    // Optional post-download conversion phase (e.g. BAM→FASTQ): `watch` is an output file whose
    // growth shows conversion progress; while it's being actively written the box shows "converting".
    convert?: { watch: string }
  }
}

// A single step of a "BioIDE codelab": either a prose cell (markdown) or a code cell
// (Python shown on the codelab page AND emitted into a runnable Colab .ipynb). Declared in
// pipeline.json so the code the user sees is the same code that ends up in the notebook.
export interface CodelabCell {
  title?: string // short heading above this step
  desc?: string // ko explanation (minimal markdown) — becomes a markdown cell before the code
  code?: string // Python source; when present, emitted as a code cell
}

// The "BioIDE codelab" card/page for a pipeline: shows the pipeline's actual code as a
// sequence of cells and offers a runnable Google Colab notebook (generated from `cells`).
export interface Codelab {
  label?: string // dashboard-card / button text (default "BioIDE codelab")
  title?: string // page H1
  subtitle?: string // one-line page subtitle
  intro?: string // markdown paragraph above the cells
  colabUrl?: string // a hosted Colab notebook to open directly (one-click). When absent, the
  // page generates a local .ipynb and opens Colab's upload flow instead.
  notebook?: string // filename for the generated .ipynb (default "<pipelineId>_codelab.ipynb")
  cells: CodelabCell[]
}

// One output figure a paper can embed, declared in pipeline.json ("figures": [...]) so the
// paper writer is data-driven — no per-pipeline hardcoding. `file` is relative to the results
// dir; only figures that actually exist there are embedded. easy/detailed are Korean captions.
export interface Figure {
  file: string
  title: string
  easy: string
  detailed: string
}

// A first-run setup step shown as a live checklist on the Home card (home.ts). `check`
// is an optional path (~ or absolute) whose existence marks the item done — so the card
// ticks items off as the user completes setup (e.g. writing ~/.config/ghbio/gcp.json).
// Declared per-pipeline in pipeline.json ("todo": [...]) — no TypeScript change to add one.
export interface TodoItem {
  label: string
  check?: string
}

export interface Pipeline {
  id: string
  name: string
  summary?: string
  dir: string
  stages: Stage[]
  help?: PipelineHelp
  dataSource?: DataSource
  codelab?: Codelab
  todo?: TodoItem[]
  // Figures this pipeline produces, for the paper writer (src/paper.ts). Declared per-pipeline
  // in pipeline.json; generic QC figures (umap_clusters/qc_violin) come from a shared fallback.
  figures?: Figure[]
  // A pipeline can replace a module-wide AI prompt set when its biology differs
  // materially (e.g. lung cancer rather than PBMC), while reusing the module UI.
  ai?: Partial<AiConfig>
}

// Parse a pipeline folder. Accepts pipeline.json (preferred) or the legacy
// tutorial.json, and steps under either "stages" or the legacy "steps" key.
export function loadPipelineFromDir(dir: string): Pipeline | undefined {
  for (const fn of ["pipeline.json", "tutorial.json"]) {
    const f = path.join(dir, fn)
    if (!fs.existsSync(f)) continue
    try {
      const m = JSON.parse(fs.readFileSync(f, "utf8"))
      return {
        id: m.id,
        name: m.name,
        summary: m.summary,
        dir,
        stages: m.stages ?? m.steps ?? [],
        help: m.help,
        dataSource: m.dataSource,
        codelab: m.codelab,
        todo: m.todo,
        figures: m.figures,
        ai: m.ai,
      }
    } catch (e) {
      vscode.window.showErrorMessage(`GHBIO: bad ${fn} in ${path.basename(dir)}: ${e}`)
      return undefined
    }
  }
  return undefined
}

// A stage is "done" when every artifact it declares exists in the project results dir.
// Stages without declared artifacts (env/download/build) are untracked → undefined.
export function isStageDone(pipelineId: string, produces?: string[]): boolean | undefined {
  if (!produces?.length) return undefined
  const results = tutorialResultsDir(pipelineId)
  return produces.every((rel) => fs.existsSync(path.join(results, rel)))
}

// True when a stage's `presentPath` (absolute output outside results/) exists.
export function isStagePresent(s: Stage): boolean | undefined {
  if (!s.presentPath) return undefined
  return fs.existsSync(expandHome(s.presentPath))
}

// Whether the app can track this stage's completion at all (produces OR presentPath).
export function stageTracked(s: Stage): boolean {
  return !!(s.produces?.length || s.presentPath)
}

// Combined completion across both mechanisms. undefined ⇒ untracked (can't tell).
export function stageComplete(pipelineId: string, s: Stage): boolean | undefined {
  const a = isStageDone(pipelineId, s.produces)
  const b = isStagePresent(s)
  if (a === undefined && b === undefined) return undefined
  return a === true || b === true
}

// done/total over the stages whose completion we can actually track.
export function pipelineProgress(p: Pipeline): { done: number; total: number } {
  const tracked = p.stages.filter(stageTracked)
  return { done: tracked.filter((s) => stageComplete(p.id, s) === true).length, total: tracked.length }
}

export function stageStatus(p: Pipeline): Record<string, boolean | undefined> {
  const out: Record<string, boolean | undefined> = {}
  for (const s of p.stages) out[s.id] = isStageDone(p.id, s.produces)
  return out
}

// Ensure the pipeline's project exists (results dir + notes) so its outputs are
// first-class files under Projects/<id>/. Returns the results dir to write into.
export function ensureProject(p: { id: string; name: string; summary?: string }): string {
  const projectDir = tutorialProjectDir(p.id)
  const resultsDir = tutorialResultsDir(p.id)
  fs.mkdirSync(resultsDir, { recursive: true })
  // Per-step debug logs (tailed by the Dashboard console) live here; pre-create so
  // the tee redirect in `stepLogTee` can open its file immediately.
  fs.mkdirSync(path.join(resultsDir, ".logs"), { recursive: true })
  const notes = path.join(projectDir, "notes.md")
  if (!fs.existsSync(notes)) {
    fs.writeFileSync(
      notes,
      `# ${p.name}\n\n${p.summary ?? "GHBIO analysis project."}\n\n` +
        `- \`results/\` — figures, tables, reports (the pipeline writes here)\n` +
        `- Shared heavy inputs are reused across projects under \`~/ghbio-tutorial/\`.\n`,
    )
  }
  return resultsDir
}

// Wrap one shell stage with the same ▶ banner the per-step runner uses.
function stageBlock(s: Stage): string {
  const title = s.title.replace(/"/g, "")
  return (
    `printf "\\n\\033[1;36m▶ %s\\033[0m\\n" "${title}"; ` +
    `echo "  실행 중… 끝나면 ✅ 표시가 나옵니다."; ` +
    `{ ${s.run}; } ${stepLogTee(s.id)}`
  )
}

/**
 * The narrow interface: run a pipeline end-to-end (or resume from a stage) with ONE
 * call. Runs every shell stage sequentially in a single integrated-terminal task —
 * stopping on the first failure — then hands off to AI once results exist.
 */
export async function runPipeline(
  context: vscode.ExtensionContext,
  p: Pipeline,
  opts: { from?: string; openAI?: () => void; readyFile?: string } = {},
) {
  const resultsDir = ensureProject(p)

  // Select the shell stages to run: from `from` (or the start) up to the AI stage.
  let start = 0
  if (opts.from) {
    const i = p.stages.findIndex((s) => s.id === opts.from)
    if (i >= 0) start = i
  }
  const chain: Stage[] = []
  let hasAI = false
  for (const s of p.stages.slice(start)) {
    if (s.kind === "ai") {
      hasAI = true
      break // the AI stage is interactive — stop the shell chain here
    }
    if (s.run) chain.push(s)
  }
  if (chain.length === 0) {
    if (hasAI) opts.openAI?.()
    return
  }

  const body =
    chain.map(stageBlock).join(" && \\\n") +
    ` && printf "\\n\\033[1;32m✅ 전체 분석 완료 — 결과는 Projects/${p.id}/results 에 있습니다.\\033[0m\\n"` +
    ` || printf "\\n\\033[1;31m⚠ 파이프라인이 중간에 멈췄습니다. 위의 마지막 메시지를 확인하세요.\\033[0m\\n"`

  const exec = await runShellTask(`GHBIO: ${p.name}`, body, p.dir, { GHBIO_RESULTS: resultsDir })

  // When the analysis has produced its "ready" artifact, hand off to the AI panel.
  const readyFile = opts.readyFile ?? "markers_by_cluster.csv"
  if (hasAI && opts.openAI) {
    const done = vscode.tasks.onDidEndTask((e) => {
      if (e.execution !== exec) return
      done.dispose()
      if (fs.existsSync(path.join(resultsDir, readyFile))) opts.openAI!()
    })
    context.subscriptions.push(done)
  }
}
