import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { modulesDir, tutorialsDir } from "./util"
import { Pipeline, loadPipelineFromDir } from "./pipeline"

// =============================================================================
// The MODULE REGISTRY — the scaffolding that lets the app grow.
//
// A "module" is a self-contained analysis domain (single-cell RNA-seq today;
// protein 3D modeling tomorrow). Everything domain-specific lives in data, not
// code: modules/<id>/module.json declares the domain's identity, its libraries
// (tools to install), and its AI config (prompts/system/result files); its
// pipelines live under modules/<id>/pipelines/<pid>/pipeline.json.
//
// Adding a whole new domain = drop in a modules/<id>/ folder. No TypeScript edits:
// the tree, libraries view, and AI panel all read from these manifests.
// =============================================================================

export interface LibrarySpec {
  id: string
  name: string
  desc?: string
  presentPath: string // ~-expanded; exists() ⇒ installed
  install: { pipeline: string; script: string; label: string }
}

export interface AiPromptSpec {
  key: string
  label: string
  q: string
}

export interface AiContextFile {
  file: string // relative to the project results dir
  heading: string
  topByRank?: number // keep only rows whose 2nd CSV column ∈ [1, N]
}

// A pipeline-scoped "one-click high-school report" action. When present, the AI panel
// shows an extra button after the preset prompts that rewrites the analysis into a
// 고등학생-level Korean report (heavy on metaphors, with a dedicated section comparing the
// original paper's conclusions against what THIS tutorial computed) and builds a PDF.
export interface EasyReportSpec {
  label: string // button text
  makeReport?: string // shell script (relative to the pipeline dir) that turns the report md into a PDF
  paperClaim?: string // the original paper's published conclusion, so the model can judge agreement
  title?: string // report H1 (e.g. "# 🔬 흑색종 세포 이야기 — 고등학생 리포트"); falls back to a generic title
  datasetLabel?: string // short phrase naming what THIS tutorial computed (e.g. "PBMC 면역세포 scRNA-seq 분석")
}

// A pipeline-scoped comprehension survey ("이해도 테스트") for education research.
// When present, the AI panel shows a button to open the survey form and one to open
// the aggregated statistics. Questions live in the pipeline dir's survey.json.
export interface SurveySpec {
  testLabel?: string // survey-open button text
  resultLabel?: string // stats-open button text
}

export interface AiConfig {
  intro?: string
  system?: string
  readyFile?: string // presence ⇒ analysis ready (pipeline → AI hand-off)
  readyHint?: string // shown when results are missing
  context?: AiContextFile[]
  models?: Record<string, string[]>
  prompts?: AiPromptSpec[]
  easyReport?: EasyReportSpec
  survey?: SurveySpec
}

export interface ModuleManifest {
  id: string
  name: string
  icon?: string
  description?: string
  libraries?: LibrarySpec[]
  ai?: AiConfig
}

export interface Module extends ModuleManifest {
  dir: string
  pipelines: Pipeline[]
}

function readModule(dir: string): Module | undefined {
  const manifest = path.join(dir, "module.json")
  if (!fs.existsSync(manifest)) return undefined
  let man: ModuleManifest
  try {
    man = JSON.parse(fs.readFileSync(manifest, "utf8"))
  } catch (e) {
    vscode.window.showErrorMessage(`GHBIO: bad module.json in ${path.basename(dir)}: ${e}`)
    return undefined
  }
  const pdir = path.join(dir, "pipelines")
  const pipelines: Pipeline[] = []
  if (fs.existsSync(pdir)) {
    for (const e of fs.readdirSync(pdir, { withFileTypes: true })) {
      if (!e.isDirectory() || e.name.startsWith("_")) continue
      const p = loadPipelineFromDir(path.join(pdir, e.name))
      if (p) pipelines.push(p)
    }
  }
  pipelines.sort((a, b) => a.name.localeCompare(b.name))
  return { ...man, dir, pipelines }
}

export function loadModules(context: vscode.ExtensionContext): Module[] {
  const root = modulesDir(context)
  const out: Module[] = []
  if (fs.existsSync(root)) {
    for (const e of fs.readdirSync(root, { withFileTypes: true })) {
      if (!e.isDirectory() || e.name.startsWith("_")) continue // "_"-prefixed = templates/drafts
      const m = readModule(path.join(root, e.name))
      if (m) out.push(m)
    }
  }

  // Back-compat: a legacy flat tutorials/ dir becomes a single default module so
  // older installs keep working without a modules/ tree.
  if (out.length === 0) {
    const legacy = tutorialsDir(context)
    if (fs.existsSync(legacy)) {
      const pipelines: Pipeline[] = []
      for (const e of fs.readdirSync(legacy, { withFileTypes: true })) {
        if (!e.isDirectory() || e.name.startsWith("_")) continue
        const p = loadPipelineFromDir(path.join(legacy, e.name))
        if (p) pipelines.push(p)
      }
      if (pipelines.length) {
        out.push({ id: "ghbio", name: "GHBIO", dir: legacy, pipelines, icon: "beaker" })
      }
    }
  }

  return out.sort((a, b) => a.name.localeCompare(b.name))
}

export function allPipelines(mods: Module[]): Pipeline[] {
  return mods.flatMap((m) => m.pipelines)
}

export function findPipeline(mods: Module[], pipelineId: string): { module: Module; pipeline: Pipeline } | undefined {
  for (const m of mods) {
    const p = m.pipelines.find((pl) => pl.id === pipelineId)
    if (p) return { module: m, pipeline: p }
  }
  return undefined
}

// The default pipeline to run when no context is given (toolbar button, welcome
// link): the first pipeline of the first module. Most users are doing scRNA-seq,
// which sorts first today, but this stays correct as modules are added/removed.
export function defaultPipeline(mods: Module[]): { module: Module; pipeline: Pipeline } | undefined {
  for (const m of mods) if (m.pipelines.length) return { module: m, pipeline: m.pipelines[0] }
  return undefined
}
