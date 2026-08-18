import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { loadProviders, streamChat } from "./ai/providers"
import { BIOIDE_MISSION, missionHtml } from "./mission"

// Every AI step that helps create a tutorial is bound by the BioIDE constitution.
const withMission = (prompt: string): string => `${BIOIDE_MISSION}\n\n${prompt}`
import { pipelineDraftsDir } from "./util"

// =============================================================================
// "Create pipeline" — a Home card that helps a user turn a published cancer
// scRNA-seq paper into a NEW BioIDE reproduction pipeline, in two AI steps:
//
//   1) 논문 찾기 (Find paper): the AI proposes cancer-research scRNA-seq papers that
//      (a) report a significant discovery, (b) [REQUIRED] have their ORIGINAL raw
//      dataset publicly available (GEO/SRA/ENA/Zenodo), and (c) [BONUS] publish code.
//      With the Anthropic provider, an optional server-side web_search verifies
//      accessions live; otherwise the model uses its training knowledge (and is told
//      to flag any accession it isn't sure about).
//
//   2) design pipeline: for a chosen paper, the AI drafts a reproduction TUTORIAL
//      PLAN — reimplementing the paper's workflow with a modern AI/GPU/Python stack
//      (Scanpy/scVI instead of R/Seurat) and validating the paper's conclusion with
//      INDEPENDENT data processing. The plan renders as collapsible Markdown.
//
// Same single-shot streaming design as the AI panel / paper writer (no agent loop).
// The plan is a DRAFT the user reviews; it is NOT auto-scaffolded into modules/.
// =============================================================================

const DEFAULT_MODELS: Record<string, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
  groq: ["openai/gpt-oss-120b"],
  openrouter: ["anthropic/claude-sonnet-4", "deepseek/deepseek-chat"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
}

export interface Candidate {
  title?: string
  authors?: string
  year?: string
  journal?: string
  discovery?: string
  dataset?: string
  accession?: string
  code?: string
  fit?: string
}

const SEARCH_SYSTEM =
  "당신은 암(cancer) 연구 단일세포 RNA-seq(scRNA-seq) 분야의 생물정보학 큐레이터입니다. " +
  "사용자는 어떤 논문의 분석 워크플로를 '최신 AI·GPU·Python 스택으로 독립 재현(reproduce)하고, " +
  "다른 방식의 데이터 처리로 그 결론을 검증(validate)'하고자 합니다. 그런 재현·검증 대상으로 좋은 논문 후보를 찾아 주세요. " +
  "반드시 지킬 기준:\n" +
  "① 암 연구에서 scRNA-seq로 '의미 있는 발견'을 한 논문일 것.\n" +
  "② [필수] 저자들이 실제로 사용한 원본 데이터셋이 공개되어 있어야 함 — GEO/SRA/ENA/Zenodo 등의 접근번호(accession)를 함께 제시. " +
  "원본 데이터가 공개되지 않은 논문은 절대 넣지 마세요(가장 중요한 기준).\n" +
  "③ [가점] 원 저자의 소스코드(GitHub 등)가 공개되어 있으면 더 좋음.\n" +
  "④ [가점] 원 분석이 R/Seurat 등 구식 스택이라 Python(Scanpy)·GPU(scVI)·AI로 더 빠르게·다르게 재현·검증하기에 적합할 것.\n" +
  "후보 3~5개를 한국어로, 각 후보마다 제목·저자·연도·저널 / 핵심 발견 / 공개 데이터 접근번호와 규모 / 코드 공개 여부 / " +
  "왜 GPU·Python·AI 재현에 적합한지 / 독립 재처리로 검증할 결론을 서술하세요. " +
  "접근번호가 불확실하면 반드시 '확인 필요'라고 명시하고 절대 지어내지 마세요. " +
  "본문 설명을 마친 뒤, 맨 끝에 반드시 아래 형식의 기계가 읽을 수 있는 JSON 블록을 정확히 하나 덧붙이세요(코드펜스 포함, 그 뒤엔 아무것도 쓰지 말 것):\n" +
  "```json\n" +
  '[{"title":"","authors":"","year":"","journal":"","discovery":"","dataset":"","accession":"","code":"","fit":""}]\n' +
  "```"

const DESIGN_SYSTEM =
  "당신은 BioIDE(생물학자를 위한 생물정보학 IDE)의 파이프라인 설계자입니다. 주어진 암 연구 scRNA-seq 논문을 " +
  "'최신 AI·GPU·Python 스택으로 독립 재현하고 결론을 검증'하는 BioIDE 튜토리얼 계획을 한국어 **Markdown**으로 작성하세요. " +
  "BioIDE 특성: 데이터 기반 파이프라인으로 각 단계가 셸 Task(kind:\"task\")나 AI 패널(kind:\"ai\")로 실행되고, 결과는 프로젝트 파일로 저장됩니다. " +
  "aarch64 장비라 Cell Ranger 대신 STARsolo를 소스 컴파일해 씁니다. 공개 데이터가 BAM만 있으면 pysam으로 FASTQ를 복원하고, " +
  "공개 데이터가 처리 완료 행렬뿐이어도 그 행렬에서 QC·정규화·클러스터링·세포유형 주석·악성세포 식별을 우리 코드로 처음부터 다시 수행하고, " +
  "저자가 붙인 라벨·주석은 분석 입력으로 절대 소비하지 말고 오직 검증 대조용으로만 사용합니다(헌장 제1조). " +
  "원 논문이 R/Seurat를 썼다면 Python(Scanpy)·GPU(scVI/rapids-singlecell/PyTorch)·AI 해석으로 대체해, " +
  "'우리가 독립적으로 새로 짠 데이터 처리가 원 논문과 같은 결론에 이르는지'를 정량적으로 검증하는 것이 핵심 목표입니다. " +
  "다음 구성을 반드시 포함하세요:\n" +
  "1. 개요 — 원 논문과 검증 대상이 되는 핵심 결론\n" +
  "2. 데이터 — 공개 접근번호·규모·획득 방법(FASTQ/BAM→FASTQ/처리행렬 중 무엇으로 시작할지)\n" +
  "3. 현대 스택 — 원 R 스택 대비 왜 GPU·Python·AI로 바꾸는지\n" +
  "4. 파이프라인 단계 — **Markdown 표**로(열: 단계 id · 제목 · kind · 실행 도구/명령 · 산출물)\n" +
  "5. 독립 검증 전략 — 어떤 정량 결과로 원 논문 결론의 일치/부분일치/불일치를 판정하는지\n" +
  "6. 기여 — 재현이 성공/실패할 때 각각의 과학적 의미(원 논문 지지 여부, 그리고 빠른 AI 중심 알고리즘이 같은 결론을 주는지)\n" +
  "7. 위험·한계\n" +
  "구체적이고 실행 가능하게 쓰되 데이터가 공개돼 있음을 전제로만 계획하세요. Markdown 외의 머리말/맺음말은 넣지 마세요."

// Pull the last ```json fenced block out of the search answer and parse it into candidate cards.
// Robust to the model wrapping it in ```json or plain ``` — returns [] if nothing parses.
function extractCandidates(text: string): Candidate[] {
  const fences = [...text.matchAll(/```(?:json)?\s*([\s\S]*?)```/g)]
  for (let i = fences.length - 1; i >= 0; i--) {
    try {
      const parsed = JSON.parse(fences[i][1].trim())
      if (Array.isArray(parsed)) return parsed.filter((c) => c && typeof c === "object")
    } catch {
      /* try an earlier fence */
    }
  }
  return []
}

function buildDesignPrompt(c: Candidate, focus: string): string {
  const f = (label: string, v?: string) => (v ? `${label}: ${v}\n` : "")
  return (
    "## 재현·검증 대상 논문\n" +
    f("제목", c.title) +
    f("저자", c.authors) +
    f("연도", c.year) +
    f("저널", c.journal) +
    f("핵심 발견(검증 대상 결론)", c.discovery) +
    f("공개 데이터셋", c.dataset) +
    f("데이터 접근번호(accession)", c.accession) +
    f("코드 공개", c.code) +
    f("재현 적합성 메모", c.fit) +
    (focus ? `\n## 사용자 관심/제약\n${focus}\n` : "") +
    "\n## 작성 지침\n위 논문을 BioIDE에서 최신 AI·GPU·Python 스택으로 독립 재현·검증하는 튜토리얼 계획을 작성하라. " +
    "원 논문의 핵심 결론을 '다른 독립적 데이터 처리'로 검증하는 전략을 반드시 포함하고, 파이프라인 단계는 Markdown 표로 제시하라. " +
    "데이터 접근번호가 '확인 필요'로 표시돼 있으면, 계획에 그 검증(데이터 실제 존재 확인)을 첫 단계로 넣어라."
  )
}

const escHtml = (s: string) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)

// =============================================================================
// Draft → scaffold: turn a saved reproduction PLAN (.md) into a full pipeline
// scaffold (pipeline.json + one draft shell/python script per stage) written to a
// STAGING folder pipeline-drafts/<id>/ for the user to review and later promote into
// modules/. Orchestrated by deterministic code over several single-shot streamChat
// calls (one for the manifest, one per script) — no agent loop.
// =============================================================================

const MANIFEST_SYSTEM =
  "You convert a Korean scRNA-seq reproduction PLAN into a BioIDE `pipeline.json` manifest, output as PURE JSON " +
  "(no code fence, no prose — the whole reply must be one JSON object). Match this schema exactly:\n" +
  "{\n" +
  '  "id": "kebab-case-id", "name": "한국어 파이프라인 이름", "summary": "한 줄 요약",\n' +
  '  "dataSource": { "provider": "GEO/SRA 등", "dataset": "이름·accession·chemistry", "datasetUrl": "", "fastqUrl": "", "size": "", "note": "" },\n' +
  '  "steps": [ { "id": "짧은id", "title": "English step title", "ko": "한국어 설명", "kind": "task", "run": "bash NN_name.sh", "presentPath": "선택: 존재하면 완료로 표시할 파일", "produces": ["선택: results 기준 상대경로"] } ],\n' +
  '  "ai": { "system": "English system prompt describing the biology", "readyHint": "한국어", "context": [ {"file":"x.csv","heading":"한국어 제목"} ], "prompts": [ {"key":"","label":"버튼 라벨","q":"한국어 질문"} ], "easyReport": {"label":"🎓 고등학생 버전 보고서","makeReport":"05_make_easy_report.sh","title":"# ...","datasetLabel":"...","paperClaim":"원 논문의 핵심 결론"} },\n' +
  '  "help": { "intro": "HTML 허용 한국어 소개", "steps": {"stepId":"한국어 설명"}, "glossary": [ {"term":"","def":"HTML 허용"} ] }\n' +
  "}\n" +
  "Rules: order steps top→bottom (환경설치 → 다운로드 → STAR 색인/정렬 → 분석 → ai → 리포트). Each task step runs a script " +
  "named `NN_name.sh` (two-digit prefix) or a python file `NN_name.py`. EXACTLY ONE step has kind:\"ai\" (no run). The final " +
  "step builds a PDF (bash 05_make_report.sh, produces a .pdf). Target hardware: aarch64 (no Cell Ranger; STARsolo compiled " +
  "from source), Python venv ~/ghbio-venv. Base ai.context filenames on the CSVs the analyze step will produce. Use Korean for " +
  "the fields the schema marks 한국어. Output ONLY the JSON object."

const SCRIPT_SYSTEM =
  "You write ONE file for a BioIDE scRNA-seq pipeline stage. Output RAW file contents ONLY — no code fence, no prose, no " +
  "explanation before or after. Environment: aarch64 Linux, NO Cell Ranger, STARsolo compiled from source at ~/bin/STAR, a " +
  "Python venv at ~/ghbio-venv (call ~/ghbio-venv/bin/python). CRITICAL: the script MUST write all outputs into the directory " +
  'given by env var $GHBIO_RESULTS (fallback: "${HOME}/ghbio-tutorial/results"); never hardcode a project path. Make it ' +
  "idempotent (safe to re-run — skip work already done). For any download use `flock` to avoid duplicate runs and " +
  "`curl -C - --retry 5 --speed-limit 1024 --speed-time 60` so a stalled connection times out instead of hanging. Heavy shared " +
  "inputs (FASTQ, GRCh38 index) live under ~/ghbio-tutorial and are reused. Where you must GUESS a URL, accession, parameter, or " +
  "command the plan does not pin down, write your best guess AND add a `# TODO: 확인 필요` comment on that line. Start .sh files " +
  "with `#!/usr/bin/env bash` and `set -euo pipefail`. Output ONLY the file body."

const slug = (s: string): string =>
  String(s)
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "pipeline"

function manifestUser(plan: string): string {
  return "다음은 재현 계획서(Markdown)입니다. 이를 BioIDE pipeline.json 매니페스트(순수 JSON)로 변환하세요.\n\n=== 계획서 ===\n" + plan
}

function scriptUser(plan: string, manifest: any, step: any, fn: string): string {
  return (
    `아래 계획서와 pipeline.json 매니페스트를 참고하여, '${fn}' 파일의 내용을 작성하세요.\n` +
    `이 파일은 단계 [${step.id}] "${step.title}"${step.ko ? ` (${step.ko})` : ""} 를 실행합니다. run: ${step.run}\n` +
    (step.produces ? `이 단계는 다음 산출물을 만들어야 합니다(GHBIO_RESULTS 기준 상대경로): ${JSON.stringify(step.produces)}\n` : "") +
    `\n=== pipeline.json ===\n${JSON.stringify(manifest).slice(0, 4000)}\n\n=== 계획서 ===\n${plan}`
  )
}

// Extract the first balanced {...} object text and parse it (models sometimes wrap JSON in prose/fences).
function extractJson(s: string): any {
  const a = s.indexOf("{")
  const b = s.lastIndexOf("}")
  if (a < 0 || b <= a) throw new Error("모델이 JSON 매니페스트를 반환하지 않았습니다.")
  return JSON.parse(s.slice(a, b + 1))
}

// Strip a single surrounding ```lang ... ``` fence if the model added one despite instructions.
function stripFence(s: string): string {
  const t = s.trim()
  const m = /^```[a-zA-Z]*\s*\n([\s\S]*?)\n```$/.exec(t)
  return (m ? m[1] : t).trim() + "\n"
}

// The script filename a task step runs, e.g. "bash 01_download.sh" → "01_download.sh",
// "~/ghbio-venv/bin/python 03_analyze.py" → "03_analyze.py". undefined if none.
function scriptFileOf(run?: string): string | undefined {
  if (!run) return undefined
  const m = /([\w.\-/]+\.(?:sh|py))(?:\s|$)/.exec(run)
  return m ? m[1].replace(/^.*\//, "") : undefined
}

function scaffoldReadme(manifest: any, id: string, files: string[]): string {
  const list = files.map((f) => "`" + f + "`").join(", ")
  return (
    `# ${manifest.name || id} — 스캐폴드 초안 (검토용)\n\n` +
    `이 폴더는 **"파이프라인 만들기"** 카드가 초안 계획서(.md)로부터 AI로 자동 생성한 **검토용 스캐폴드**입니다. ` +
    `아직 실제 튜토리얼이 아니며, 검토·수정 후 \`modules/\`로 **승격(promote)** 해야 합니다.\n\n` +
    `- 스테이징 위치: \`pipeline-drafts/${id}/\`\n` +
    `- 생성 파일: ${list}\n\n` +
    `## ⚠ 반드시 검토하세요\n` +
    `AI가 생성한 스크립트에는 **추측한 URL·accession·파라미터**가 들어 있을 수 있습니다. 각 파일에서 ` +
    `\`# TODO: 확인 필요\` 주석을 찾아 데이터 접근번호와 명령을 검증하세요. 스크립트는 \`$GHBIO_RESULTS\`에 결과를 씁니다.\n\n` +
    `## 실제 튜토리얼로 승격(promote)\n` +
    "```bash\n" +
    `cp -r ~/ghbio-workspace/pipeline-drafts/${id} ~/ghbio-coscientist/modules/scrna-seq/pipelines/${id}\n` +
    `# package.json 의 version 을 올린 뒤\n` +
    `cd ~/ghbio-coscientist && bash build.sh\n` +
    "```\n\n" +
    `그런 다음 브라우저 탭을 **Ctrl+Shift+R** 로 새로고침하면 새 튜토리얼 카드가 GHBIO Home 에 나타납니다.\n`
  )
}

interface DraftInfo {
  file: string
  name: string
  mtime: number
}
function listDrafts(): DraftInfo[] {
  const dir = pipelineDraftsDir()
  try {
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith(".md"))
      .map((f) => ({ file: f, name: f.replace(/_plan\.md$/, "").replace(/\.md$/, ""), mtime: fs.statSync(path.join(dir, f)).mtimeMs }))
      .sort((a, b) => b.mtime - a.mtime)
  } catch {
    return []
  }
}

// Orchestrate the multi-file scaffold. Streams per-file progress to the panel; obeys the shared
// AbortController so the Stop button cancels it. Writes into pipeline-drafts/<id>/ (staging).
async function runScaffold(
  panel: vscode.WebviewPanel,
  providers: ReturnType<typeof loadProviders>,
  msg: any,
): Promise<void> {
  const apiKey = providers[msg.provider]?.apiKey
  if (!apiKey) {
    panel.webview.postMessage({ type: "scaffoldError", msg: `${msg.provider} API key가 설정되지 않았습니다.` })
    return
  }
  const draftsRoot = pipelineDraftsDir()
  const planPath = path.join(draftsRoot, path.basename(String(msg.file)))
  let plan = ""
  try {
    plan = fs.readFileSync(planPath, "utf8")
  } catch {
    panel.webview.postMessage({ type: "scaffoldError", msg: "초안 파일을 읽을 수 없습니다." })
    return
  }

  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const common = { provider: msg.provider, model: msg.model, apiKey, signal }
  panel.webview.postMessage({ type: "scaffoldStart" })
  try {
    // 1) Manifest (pipeline.json)
    panel.webview.postMessage({ type: "scaffoldProgress", file: "pipeline.json", msg: "매니페스트(pipeline.json) 생성 중…" })
    let manifestRaw = ""
    await streamChat({
      ...common,
      system: withMission(MANIFEST_SYSTEM),
      user: manifestUser(plan),
      maxTokens: 8000,
      onDelta: (t) => {
        if (!t) return
        manifestRaw += t
        panel.webview.postMessage({ type: "scaffoldDelta", text: t })
      },
    })
    const manifest = extractJson(manifestRaw)
    const id = slug(manifest.id || manifest.name || "pipeline")
    manifest.id = id
    const outDir = path.join(draftsRoot, id)
    fs.mkdirSync(outDir, { recursive: true })
    fs.writeFileSync(path.join(outDir, "pipeline.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8")
    const written = ["pipeline.json"]
    panel.webview.postMessage({ type: "scaffoldFile", file: "pipeline.json" })

    // 2) One script per task step (capped so a malformed manifest can't fan out forever).
    const steps: any[] = Array.isArray(manifest.steps) ? manifest.steps : manifest.stages ?? []
    const scripts: { fn: string; st: any }[] = []
    for (const st of steps) {
      if (st?.kind !== "task") continue
      const fn = scriptFileOf(st.run)
      if (fn && !scripts.some((s) => s.fn === fn)) scripts.push({ fn, st })
    }
    // Backstop against a malformed manifest fanning out forever — but high enough that a real
    // multi-stage pipeline (env→download→align→QC→norm→latent→cluster→CNV→programs→overlap→stats→report)
    // is generated in full rather than silently truncated.
    const MAX = 24
    const n = Math.min(scripts.length, MAX)
    for (let i = 0; i < n; i++) {
      if (signal.aborted) break
      const { fn, st } = scripts[i]
      panel.webview.postMessage({ type: "scaffoldProgress", file: fn, msg: `스크립트 생성 중 (${i + 1}/${n}): ${fn}` })
      let body = ""
      await streamChat({
        ...common,
        system: withMission(SCRIPT_SYSTEM),
        user: scriptUser(plan, manifest, st, fn),
        maxTokens: 6000,
        onDelta: (t) => {
          if (!t) return
          body += t
          panel.webview.postMessage({ type: "scaffoldDelta", text: t })
        },
      })
      if (signal.aborted) break
      fs.writeFileSync(path.join(outDir, fn), stripFence(body), "utf8")
      written.push(fn)
      panel.webview.postMessage({ type: "scaffoldFile", file: fn })
    }
    if (scripts.length > MAX) written.push(`… (+${scripts.length - MAX}개 스크립트 생략됨)`)

    fs.writeFileSync(path.join(outDir, "README.md"), scaffoldReadme(manifest, id, written), "utf8")
    written.push("README.md")
    panel.webview.postMessage({ type: "scaffoldDone", dir: outDir, id, files: written })
    vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(path.join(outDir, "pipeline.json")))
    vscode.commands.executeCommand("vscode.open", vscode.Uri.file(path.join(outDir, "pipeline.json")))
  } catch (e: any) {
    if (e?.name === "AbortError") panel.webview.postMessage({ type: "scaffoldDone", aborted: true })
    else panel.webview.postMessage({ type: "scaffoldError", msg: String(e?.message ?? e) })
  }
}

let panel: vscode.WebviewPanel | undefined
let controller: AbortController | undefined

export function openCreatePipeline(context: vscode.ExtensionContext) {
  if (panel) {
    panel.reveal()
    return
  }
  panel = vscode.window.createWebviewPanel("ghbioCreatePipeline", "GHBIO · 파이프라인 만들기", vscode.ViewColumn.Active, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  const thePanel = panel
  thePanel.onDidDispose(() => {
    controller?.abort()
    if (panel === thePanel) panel = undefined
  })

  const providers = loadProviders()
  // Default the dropdown to Groq (free/fast) rather than Anthropic — the Anthropic
  // key often has no credit balance, and web search (Anthropic-only) isn't required here.
  const PROVIDER_PREF = ["groq", "deepseek", "openrouter", "anthropic"]
  const available = Object.keys(providers)
    .filter((p) => providers[p]?.apiKey)
    .sort((a, b) => {
      const ia = PROVIDER_PREF.indexOf(a), ib = PROVIDER_PREF.indexOf(b)
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
    })
  const modelMap: Record<string, string[]> = {}
  for (const p of available) modelMap[p] = providers[p].models?.length ? providers[p].models! : DEFAULT_MODELS[p] ?? []

  thePanel.webview.html = html(available, modelMap)

  // Accumulates the current search stream so we can parse candidates once it finishes.
  let searchBuf = ""

  thePanel.webview.onDidReceiveMessage(async (msg) => {
    if (msg?.type === "stop") {
      controller?.abort()
      return
    }

    if (msg?.type === "savePlan") {
      try {
        const dir = pipelineDraftsDir()
        fs.mkdirSync(dir, { recursive: true })
        const out = path.join(dir, `${slug(String(msg.title || "pipeline"))}_plan.md`)
        fs.writeFileSync(out, String(msg.text ?? ""), "utf8")
        thePanel.webview.postMessage({ type: "planSaved", file: out })
        vscode.commands.executeCommand("vscode.open", vscode.Uri.file(out))
        // Also reveal it in the folder view so the user can see where drafts land.
        vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(out))
      } catch (e: any) {
        thePanel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
      }
      return
    }

    // ---- Drafts list / edit / scaffold ------------------------------------
    if (msg?.type === "listDrafts") {
      thePanel.webview.postMessage({ type: "drafts", list: listDrafts() })
      return
    }
    if (msg?.type === "openDraft") {
      try {
        const p = path.join(pipelineDraftsDir(), path.basename(String(msg.file)))
        thePanel.webview.postMessage({ type: "draftContent", file: path.basename(p), text: fs.readFileSync(p, "utf8") })
      } catch (e: any) {
        thePanel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
      }
      return
    }
    if (msg?.type === "saveDraft") {
      try {
        const p = path.join(pipelineDraftsDir(), path.basename(String(msg.file)))
        fs.writeFileSync(p, String(msg.text ?? ""), "utf8")
        thePanel.webview.postMessage({ type: "draftSaved", file: path.basename(p) })
      } catch (e: any) {
        thePanel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
      }
      return
    }
    if (msg?.type === "scaffold") {
      await runScaffold(thePanel, providers, msg)
      return
    }

    if (msg?.type === "search" || msg?.type === "design") {
      const apiKey = providers[msg.provider]?.apiKey
      if (!apiKey) {
        thePanel.webview.postMessage({ type: "error", phase: msg.type, msg: `${msg.provider} API key가 설정되지 않았습니다.` })
        return
      }
      const isSearch = msg.type === "search"
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      if (isSearch) searchBuf = ""

      const user = isSearch
        ? `## 사용자 관심 분야/제약\n${String(msg.focus || "암 연구에서 scRNA-seq로 의미 있는 발견을 한 논문 (분야 무관)")}\n\n` +
          "위 기준에 맞는 후보 논문 3~5개를 찾아 제시하고, 맨 끝에 JSON 블록을 붙여라." +
          (msg.webSearch ? " 웹 검색으로 데이터 접근번호와 코드 공개 여부를 실제로 확인하라." : " 접근번호가 불확실하면 반드시 '확인 필요'로 표기하라.")
        : buildDesignPrompt((msg.candidate ?? {}) as Candidate, String(msg.focus || ""))

      thePanel.webview.postMessage({ type: isSearch ? "searchStart" : "designStart", title: msg?.candidate?.title })
      try {
        await streamChat({
          provider: msg.provider,
          model: msg.model,
          apiKey,
          webSearch: !!msg.webSearch,
          system: withMission(isSearch ? SEARCH_SYSTEM : DESIGN_SYSTEM),
          user,
          signal,
          maxTokens: isSearch ? 5000 : 9000,
          onDelta: (t) => {
            if (!t) return
            if (isSearch) searchBuf += t
            thePanel.webview.postMessage({ type: isSearch ? "searchDelta" : "designDelta", text: t })
          },
        })
        if (isSearch) thePanel.webview.postMessage({ type: "candidates", list: extractCandidates(searchBuf) })
        thePanel.webview.postMessage({ type: isSearch ? "searchDone" : "designDone" })
      } catch (e: any) {
        if (e?.name === "AbortError") {
          if (isSearch) thePanel.webview.postMessage({ type: "candidates", list: extractCandidates(searchBuf) })
          thePanel.webview.postMessage({ type: isSearch ? "searchDone" : "designDone", aborted: true })
        } else {
          thePanel.webview.postMessage({ type: "error", phase: msg.type, msg: String(e?.message ?? e) })
        }
      }
      return
    }
  })
}


// The webview logic lives in a String.raw block so single backslashes in regexes survive verbatim
// (no template-literal cooking) and backticks are written as ` (String.raw keeps them raw, the
// browser then decodes them). It reads dynamic data off window.__MODELS__, injected separately.
const UI_SCRIPT = String.raw`
  const vscode = acquireVsCodeApi()
  const MODELS = window.__MODELS__ || {}
  const PROVS = Object.keys(MODELS)
  function $(id){ return document.getElementById(id) }
  function post(o){ vscode.postMessage(o) }

  function esc(s){ return String(s).replace(/[&<>]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c] }) }
  function inline(s){ return esc(s)
    .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')
    .replace(/\*(.+?)\*/g,'<i>$1</i>')
    .replace(/\u0060(.+?)\u0060/g,'<code>$1</code>')
    .replace(/\[(.+?)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank">$1</a>') }
  function md(src){
    var FENCE='\u0060\u0060\u0060'
    var lines=String(src).split('\n'), out='', i=0
    while(i<lines.length){
      var ln=lines[i]
      if(ln.indexOf(FENCE)===0){ i++; var code=''
        while(i<lines.length && lines[i].indexOf(FENCE)!==0){ code+=lines[i]+'\n'; i++ }
        i++; out+='<pre>'+esc(code)+'</pre>'; continue }
      if(/^\s*\|.*\|\s*$/.test(ln) && i+1<lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i+1])){
        var head=ln.trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim()})
        i+=2; var rows=[]
        while(i<lines.length && /^\s*\|.*\|\s*$/.test(lines[i])){ rows.push(lines[i].trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim()})); i++ }
        out+='<table><thead><tr>'+head.map(function(h){return '<th>'+inline(h)+'</th>'}).join('')+'</tr></thead><tbody>'+rows.map(function(r){return '<tr>'+r.map(function(c){return '<td>'+inline(c)+'</td>'}).join('')+'</tr>'}).join('')+'</tbody></table>'
        continue }
      var hm=/^(#{1,4})\s+(.*)$/.exec(ln)
      if(hm){ var lvl=hm[1].length; out+='<h'+lvl+'>'+inline(hm[2])+'</h'+lvl+'>'; i++; continue }
      if(/^\s*---+\s*$/.test(ln)){ out+='<hr>'; i++; continue }
      if(/^\s*[-*]\s+/.test(ln)){ out+='<ul>'
        while(i<lines.length && /^\s*[-*]\s+/.test(lines[i])){ out+='<li>'+inline(lines[i].replace(/^\s*[-*]\s+/,''))+'</li>'; i++ }
        out+='</ul>'; continue }
      if(/^\s*\d+\.\s+/.test(ln)){ out+='<ol>'
        while(i<lines.length && /^\s*\d+\.\s+/.test(lines[i])){ out+='<li>'+inline(lines[i].replace(/^\s*\d+\.\s+/,''))+'</li>'; i++ }
        out+='</ol>'; continue }
      if(/^\s*$/.test(ln)){ i++; continue }
      out+='<p>'+inline(ln)+'</p>'; i++
    }
    return out
  }

  function fillModels(){ var mp=$('model'); var pv=$('prov'); if(!mp||!pv)return
    mp.innerHTML=(MODELS[pv.value]||[]).map(function(m){return '<option>'+esc(m)+'</option>'}).join('')
    var ws=$('ws'), hint=$('wshint')
    var isA = pv.value==='anthropic'
    if(ws){ ws.disabled=!isA; if(!isA) ws.checked=false; else if(!ws.dataset.touched) ws.checked=true }
    if(hint) hint.textContent = isA ? '(Anthropic 웹검색으로 접근번호를 실제 확인)' : '(웹검색은 Anthropic 전용 · 지금은 모델 지식으로 검색)'
  }

  var CANDS=[]
  var searchRaw='', planRaw='', planTitle=''

  function candCard(c, idx){
    var acc = c.accession ? esc(c.accession) : ''
    var accCls = /확인|unknown|미상|필요|\?/i.test(c.accession||'') ? ' class="warnacc"' : ''
    var rows=''
    if(c.discovery) rows+='<div class="crow"><b>핵심 발견</b> '+esc(c.discovery)+'</div>'
    if(c.dataset||acc) rows+='<div class="crow"><b>공개 데이터</b> '+esc(c.dataset||'')+(acc?(' · <span'+accCls+'>'+acc+'</span>'):'')+'</div>'
    if(c.code) rows+='<div class="crow"><b>코드</b> '+esc(c.code)+'</div>'
    if(c.fit) rows+='<div class="crow"><b>재현 적합성</b> '+esc(c.fit)+'</div>'
    var meta=[c.authors,c.year,c.journal].filter(Boolean).map(esc).join(' · ')
    return '<div class="cand"><div class="ctitle">'+esc(c.title||'(제목 없음)')+'</div>'+
      (meta?'<div class="cmeta">'+meta+'</div>':'')+rows+
      '<button class="designbtn" data-idx="'+idx+'">🛠 이 논문으로 파이프라인 설계 (design pipeline)</button></div>'
  }
  function renderCands(){
    var box=$('cands')
    if(!CANDS.length){ box.innerHTML='<div class="muted">후보를 구조화하지 못했습니다. 위 검색 결과에서 논문을 하나 고른 뒤 아래에 직접 붙여넣어 설계할 수 있어요.</div>'+
      '<div class="manual"><input id="mtitle" placeholder="논문 제목/설명 (직접 입력)"><button id="mdesign" class="designbtn">🛠 이 논문으로 설계</button></div>'
      var mb=$('mdesign'); if(mb) mb.onclick=function(){ startDesign({title:$('mtitle').value, discovery:$('mtitle').value}) }
      return }
    box.innerHTML=CANDS.map(candCard).join('')
    var btns=box.querySelectorAll('.designbtn')
    for(var i=0;i<btns.length;i++){ btns[i].addEventListener('click', function(e){ startDesign(CANDS[+e.currentTarget.dataset.idx]) }) }
  }

  function startSearch(){
    if(!$('prov')) return
    searchRaw=''; $('searchOut').innerHTML='…'; $('cands').innerHTML=''
    $('stop').style.display='inline-block'
    post({ type:'search', provider:$('prov').value, model:$('model').value,
      focus:$('focus').value.trim(), webSearch: !!($('ws')&&$('ws').checked) })
  }
  function startDesign(c){
    planTitle=(c&&c.title)||'pipeline'; planRaw=''
    $('planWrap').style.display='block'; $('planDetails').open=true
    $('planTitle').textContent=planTitle
    $('planOut').innerHTML='…'; $('savePlan').style.display='none'; $('planMsg').textContent=''
    $('stop').style.display='inline-block'
    post({ type:'design', provider:$('prov').value, model:$('model').value,
      focus:$('focus').value.trim(), webSearch: !!($('ws')&&$('ws').checked), candidate:c })
    $('planWrap').scrollIntoView({behavior:'smooth'})
  }

  window.addEventListener('message', function(ev){
    var m=ev.data
    if(m.type==='searchStart'){ searchRaw=''; $('searchOut').innerHTML='…' }
    else if(m.type==='searchDelta'){ searchRaw+=m.text; $('searchOut').innerHTML=md(searchRaw) }
    else if(m.type==='candidates'){ CANDS=m.list||[]; renderCands() }
    else if(m.type==='searchDone'){ $('stop').style.display='none'; if(m.aborted) $('searchOut').innerHTML+='<p><i>(중지됨)</i></p>' }
    else if(m.type==='designStart'){ planRaw=''; $('planOut').innerHTML='…' }
    else if(m.type==='designDelta'){ planRaw+=m.text; $('planOut').innerHTML=md(planRaw) }
    else if(m.type==='designDone'){ $('stop').style.display='none'; if(m.aborted) $('planOut').innerHTML+='<p><i>(중지됨)</i></p>'; if(planRaw.trim()) $('savePlan').style.display='inline-block' }
    else if(m.type==='error'){ $('stop').style.display='none'; var box=(m.phase==='design')?$('planOut'):$('searchOut'); if(box) box.innerHTML='<div class="warn">'+esc(m.msg)+'</div>' }
    else if(m.type==='planSaved'){ $('planMsg').textContent='저장됨: '+m.file; reqDrafts() }
    else if(m.type==='saveError'){ $('planMsg').textContent=m.msg; if($('draftMsg')) $('draftMsg').textContent=m.msg }
    else if(m.type==='drafts'){ renderDrafts(m.list) }
    else if(m.type==='draftContent'){ showDraft(m.file, m.text) }
    else if(m.type==='draftSaved'){ if($('draftMsg')) $('draftMsg').textContent='저장됨: '+m.file; reqDrafts() }
    else if(m.type==='scaffoldStart'){ scaffRaw=''; if($('scaffoldWrap')){ $('scaffoldWrap').style.display='block'; $('scaffoldWrap').open=true } if($('scaffoldFiles')) $('scaffoldFiles').innerHTML=''; if($('scaffoldOut')) $('scaffoldOut').textContent='매니페스트 생성 준비 중…'; if($('draftMsg')) $('draftMsg').textContent='🏗 튜토리얼 생성 중…'; if($('stop')) $('stop').style.display='inline-block' }
    else if(m.type==='scaffoldProgress'){ scaffRaw=''; addScaffFile(m.file,'run'); if($('scaffoldOut')) $('scaffoldOut').textContent=m.msg||'' }
    else if(m.type==='scaffoldDelta'){ scaffRaw+=m.text; var so=$('scaffoldOut'); if(so) so.textContent=scaffRaw.slice(-3000) }
    else if(m.type==='scaffoldFile'){ addScaffFile(m.file,'done') }
    else if(m.type==='scaffoldDone'){ if($('stop')) $('stop').style.display='none'
      if(m.aborted){ if($('draftMsg')) $('draftMsg').textContent='중지됨' }
      else if($('draftMsg')) $('draftMsg').textContent='✅ 완료: pipeline-drafts/'+m.id+'/  ('+((m.files||[]).length)+'개 파일) — 검토 후 modules/ 로 승격하세요 (README 참고)'
      reqDrafts() }
    else if(m.type==='scaffoldError'){ if($('stop')) $('stop').style.display='none'; if($('draftMsg')) $('draftMsg').textContent='오류: '+m.msg }
  })

  // ---- Drafts (이전 작업 이어가기) --------------------------------------------
  var curDraft=null, scaffRaw=''
  function reqDrafts(){ post({type:'listDrafts'}) }
  function renderDrafts(list){
    var box=$('draftsList'); if(!box) return
    if(!list||!list.length){ box.innerHTML='<div class="muted">저장된 초안이 없습니다. 아래에서 논문을 찾아 설계한 뒤 <b>계획 저장(.md)</b>을 누르면 여기에 나타납니다.</div>'; return }
    box.innerHTML=list.map(function(d){ return '<div class="draftitem" data-f="'+esc(d.file)+'"><span class="di-name">📄 '+esc(d.name)+'</span><span class="di-file">'+esc(d.file)+'</span></div>' }).join('')
    var its=box.querySelectorAll('.draftitem')
    for(var i=0;i<its.length;i++){ its[i].addEventListener('click', function(e){ post({type:'openDraft', file:e.currentTarget.dataset.f}) }) }
  }
  function renderDraftPreview(){ var p=$('draftPreview'); if(p) p.innerHTML=md($('draftText').value) }
  function showDraft(file, text){
    curDraft=file
    $('draftEditor').style.display='block'
    $('draftName').textContent=file
    $('draftText').value=text
    if($('draftMsg')) $('draftMsg').textContent=''
    if($('scaffoldWrap')){ $('scaffoldWrap').style.display='none' }
    if($('scaffoldFiles')) $('scaffoldFiles').innerHTML=''
    renderDraftPreview()
    $('draftEditor').scrollIntoView({behavior:'smooth'})
  }
  function addScaffFile(file, state){ var box=$('scaffoldFiles'); if(!box) return
    var id='sf_'+String(file).replace(/[^a-zA-Z0-9]/g,'_')
    var el=document.getElementById(id)
    if(!el){ el=document.createElement('span'); el.id=id; el.className='sfile'; box.appendChild(el) }
    el.textContent=(state==='done'?'✅ ':'⏳ ')+file
    el.className='sfile '+(state==='done'?'sf-done':'sf-run')
  }

  if($('prov')){ $('prov').onchange=fillModels; fillModels() }
  if($('ws')){ $('ws').addEventListener('change', function(){ $('ws').dataset.touched='1' }) }
  if($('search')) $('search').onclick=startSearch
  if($('stop')) $('stop').onclick=function(){ post({type:'stop'}) }
  if($('savePlan')) $('savePlan').onclick=function(){ if(planRaw.trim()) post({type:'savePlan', text:planRaw, title:planTitle}) }
  if($('draftText')) $('draftText').addEventListener('input', renderDraftPreview)
  if($('saveDraft')) $('saveDraft').onclick=function(){ if(curDraft) post({type:'saveDraft', file:curDraft, text:$('draftText').value}) }
  if($('closeDraft')) $('closeDraft').onclick=function(){ $('draftEditor').style.display='none'; curDraft=null }
  if($('scaffoldBtn')) $('scaffoldBtn').onclick=function(){
    if(!curDraft) return
    if(!$('prov')){ if($('draftMsg')) $('draftMsg').textContent='API 키가 필요합니다. providers.json 을 확인하세요.'; return }
    if($('draftText').value.trim()) post({type:'saveDraft', file:curDraft, text:$('draftText').value})
    post({type:'scaffold', file:curDraft, provider:$('prov').value, model:$('model').value })
  }
  reqDrafts()
`

function html(providers: string[], modelMap: Record<string, string[]>): string {
  const noKeys = providers.length === 0
  const provOpts = providers.map((p) => `<option value="${escHtml(p)}">${escHtml(p)}</option>`).join("")
  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{font-family:-apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif;color:#e6edf3;background:#0d1117;margin:0;padding:20px 24px 60px;line-height:1.6}
  h2{margin:0 0 2px;font-size:20px}.a{color:#2dd4bf}
  .sub{color:#8b98a5;font-size:12.5px;margin-bottom:14px;max-width:820px}
  .form{display:grid;grid-template-columns:110px 1fr;gap:9px 12px;align-items:center;max-width:720px;margin-bottom:12px}
  label{color:#b6c2cf;font-size:13px}
  input,select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px;font:inherit;width:100%}
  .wsline{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#b6c2cf}
  .wsline input{width:auto}
  #wshint{color:#6e7b8a;font-size:11.5px}
  .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0 14px}
  button{cursor:pointer;border:none;border-radius:7px;padding:7px 13px;font-size:13px;font-weight:600}
  #search{background:linear-gradient(135deg,#2dd4bf,#22d3ee);color:#06121a}
  #stop{background:#3d1418;color:#ffb4b4;border:1px solid #6e2b2b;display:none}
  .box{background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:14px 16px;min-height:60px;line-height:1.65;font-size:13.5px}
  .box h1,.box h2,.box h3{color:#7ee7d6;margin:12px 0 6px}
  .box table{border-collapse:collapse;margin:8px 0}.box td,.box th{border:1px solid #30363d;padding:3px 8px;font-size:12.5px}
  .box th{background:#12312b;color:#7ee7d6}.box code{background:#161b22;padding:1px 5px;border-radius:4px}
  .box pre{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 10px;overflow:auto;font-size:12px}
  h3.sec{font-size:14px;color:#7ee7d6;margin:20px 0 8px}
  .cand{background:#12181f;border:1px solid #253039;border-left:3px solid #2dd4bf;border-radius:10px;padding:12px 14px;margin:10px 0}
  .ctitle{font-size:14.5px;font-weight:700;color:#e6edf3}
  .cmeta{color:#8b98a5;font-size:12px;margin:2px 0 6px}
  .crow{font-size:12.8px;margin:3px 0}.crow b{color:#7ee7d6;font-weight:600;margin-right:4px}
  .warnacc{color:#f0b458;font-weight:700}
  .designbtn{margin-top:10px;background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff}
  .manual{display:flex;gap:8px;margin-top:10px}.manual input{flex:1}
  #planWrap{display:none;margin-top:8px}
  details{background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:4px 6px}
  summary{cursor:pointer;font-weight:700;color:#7ee7d6;padding:8px 10px;font-size:14px}
  #planTitle{color:#e6edf3;font-weight:600}
  #planOut{padding:6px 12px 14px}
  #savePlan{background:#12312b;color:#7ee7d6;border:1px solid #1f5a4f;display:none;margin:6px 0 4px 10px}
  #planMsg{font-size:12px;color:#2dd4bf;margin-left:10px}
  .warn{background:#3a2a12;border:1px solid #7a5a1e;color:#f0d090;padding:10px;border-radius:8px;font-size:13px}
  .muted{color:#6e7b8a;font-size:12.5px}
  /* Drafts (이전 작업 이어가기) */
  .drafts{display:flex;flex-direction:column;gap:6px;max-width:820px}
  .draftitem{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#12181f;border:1px solid #253039;border-left:3px solid #f0b458;border-radius:9px;padding:9px 12px;cursor:pointer}
  .draftitem:hover{border-color:#2dd4bf}
  .di-name{font-size:13.5px;font-weight:600;color:#e6edf3}
  .di-file{font-size:11px;color:#6e7b8a}
  #draftEditor{display:none;margin:10px 0 4px;max-width:1000px}
  .dehead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
  #draftName{color:#f0b458;font-size:13.5px}
  #draftText{width:100%;min-height:220px;background:#0b0f14;color:#cfe6df;border:1px solid #30363d;border-radius:8px;padding:10px 12px;font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;font-size:12.5px;line-height:1.55;resize:vertical}
  .ghostbtn{background:#21262d;color:#e6edf3;border:1px solid #30363d}
  .ghostbtn:hover{border-color:#2dd4bf}
  #scaffoldBtn{background:linear-gradient(135deg,#f0932b,#eb4d4b);color:#1a0e05}
  #draftMsg{font-size:12px;color:#2dd4bf}
  #scaffoldFiles{display:flex;flex-wrap:wrap;gap:6px;padding:6px 10px}
  .sfile{font-size:11.5px;padding:2px 8px;border-radius:12px;border:1px solid #30363d}
  .sfile.sf-run{background:#2a2410;color:#f0d090;border-color:#7a5a1e}
  .sfile.sf-done{background:#12312b;color:#7ee7d6;border-color:#1f5a4f}
  #scaffoldOut{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:#8b98a5;padding:6px 10px;max-height:180px;overflow:auto}
  #draftPreview{margin-top:10px}
  .mission{margin:14px 0 18px;border:1px solid #3b2f6e;border-left:4px solid #7c3aed;border-radius:10px;background:linear-gradient(135deg,#161029,#0f1626);padding:12px 16px}
  .mission-h{font-weight:700;font-size:14px;color:#c4b5fd}
  .mission-h span{font-weight:400;font-size:11.5px;color:#8b98a5}
  .mission-lead{margin:6px 0 8px;font-size:12.5px;color:#cbd5e1}
  .mission-list{margin:0;padding-left:20px;font-size:12px;color:#aeb9c6;line-height:1.55}
  .mission-list li{margin:4px 0}
  .mission-list b{color:#ddd6fe}
</style></head><body>
  <h2>파이프라인 <span class="a">만들기</span> · 논문 → 재현 튜토리얼</h2>
  <div class="sub">암 연구에서 <b>scRNA-seq로 의미 있는 발견</b>을 한 논문을 AI가 찾아 줍니다. 조건: <b>원본 데이터가 공개</b>되어 있을 것(필수), 가능하면 <b>소스코드도 공개</b>. 
  마음에 드는 논문에서 <b>design pipeline</b>을 누르면, 그 워크플로를 <b>최신 AI·GPU·Python(R 대신)</b>으로 재현하고 <b>다른 독립적 데이터 처리로 결론을 검증</b>하는 튜토리얼 계획을 만들어 접이식 상자에 보여줍니다.</div>

  ${missionHtml()}

  <h3 class="sec">📁 저장된 초안 (이전 작업 이어가기)</h3>
  <div id="draftsList" class="drafts"><div class="muted">불러오는 중…</div></div>
  <div id="draftEditor">
    <div class="dehead">
      <b id="draftName"></b>
      <button id="saveDraft" class="ghostbtn">💾 초안 저장</button>
      <button id="scaffoldBtn" title="이 초안(계획서)으로부터 pipeline.json + 단계별 스크립트를 AI가 생성해 pipeline-drafts/&lt;id&gt;/ 에 만듭니다 (검토 후 modules/ 로 승격)">🛠 이 초안으로 튜토리얼 만들기 (Proceed)</button>
      <button id="closeDraft" class="ghostbtn">✕ 닫기</button>
      <span id="draftMsg"></span>
    </div>
    <textarea id="draftText" spellcheck="false"></textarea>
    <details id="scaffoldWrap" style="display:none">
      <summary>🏗 생성 로그 (파일별)</summary>
      <div id="scaffoldFiles"></div>
      <div id="scaffoldOut"></div>
    </details>
    <div id="draftPreview" class="box"></div>
  </div>
  ${
    noKeys
      ? `<div class="warn">API 키가 설정되지 않았습니다. <code>~/.config/ghbio/providers.json</code> 를 확인하세요.</div>`
      : `<div class="form">
    <label>Provider</label><select id="prov">${provOpts}</select>
    <label>Model</label><select id="model"></select>
    <label>관심 분야</label><input id="focus" placeholder="예: 삼중음성 유방암, 교모세포종, 면역치료 저항성 … (비우면 암 전반)">
    <label>웹 검색</label><div class="wsline"><input type="checkbox" id="ws"><span id="wshint"></span></div>
  </div>
  <div class="bar">
    <button id="search">🔎 논문 찾기 (Find paper)</button>
    <button id="stop">■ Stop</button>
  </div>
  <h3 class="sec">검색 결과</h3>
  <div id="searchOut" class="box">관심 분야를 입력하고 <b>논문 찾기</b>를 누르세요.</div>
  <h3 class="sec">후보 논문 (design pipeline 선택)</h3>
  <div id="cands"></div>
  <div id="planWrap">
    <h3 class="sec">재현 튜토리얼 계획</h3>
    <details id="planDetails" open>
      <summary>🧬 <span id="planTitle"></span> — 재현·검증 계획 (클릭해 접기/펼치기)</summary>
      <div id="planOut" class="box" style="border:none"></div>
    </details>
    <button id="savePlan">💾 계획 저장 (.md)</button><span id="planMsg"></span>
  </div>`
  }
  <script>
    window.__MODELS__ = ${JSON.stringify(modelMap)};
  </script>
  <script>${UI_SCRIPT}</script>
</body></html>`
}
