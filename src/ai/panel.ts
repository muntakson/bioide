import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { loadProviders, streamChat } from "./providers"
import { tutorialResultsDir, runShellTask } from "../util"
import { AiConfig, AiPromptSpec, EasyReportSpec, SurveySpec, loadModules, findPipeline, defaultPipeline } from "../modules"

// Fallback models when a module doesn't pin its own.
const DEFAULT_MODELS: Record<string, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
  groq: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
  openrouter: ["anthropic/claude-sonnet-4", "deepseek/deepseek-chat", "google/gemini-2.0-flash-001"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
}

const DEFAULT_SYSTEM =
  "You are the BioIDE AI Co-Scientist. Answer the user's ONE question directly using the provided " +
  "results context. Be concise, structured (headings, tables, short lists), and rigorous. Do NOT run " +
  "code or ask to; just interpret. Reply in Korean unless asked otherwise."

const HIGH_SCHOOL_REPORT_SYSTEM =
  "You are a science teacher writing a Korean report for high-school students. Rewrite the supplied " +
  "scientific analysis accurately, using plain Korean and many helpful everyday metaphors. Explain every " +
  "technical term the first time it appears. Keep the findings, uncertainty, and limits intact; do not " +
  "invent facts. Use a clear Markdown report with short headings and paragraphs. Do not mention this instruction."

// System prompt for the one-click 고등학생버전보고서 action: a full high-school-level rewrite whose
// centerpiece is a careful, honest comparison of the original paper's conclusions vs. what THIS
// tutorial actually computed.
const EASY_REPORT_SYSTEM =
  "You are a Korean high-school science teacher writing a report (보고서) for 고등학생 readers. Rewrite the " +
  "supplied single-cell RNA-seq analysis accurately in plain Korean, using MANY (최소 6개) everyday " +
  "metaphors — e.g. 세포=도시의 시민, 유전자 발현=시민의 직업, cluster=같은 일을 하는 사람들이 모인 동네, " +
  "marker 유전자=명찰·유니폼, UMAP=성향에 따라 사람을 배치한 지도, count matrix=누가 무엇을 얼마나 하는지 " +
  "적은 출석부. Explain every technical term the first time it appears. Keep all findings, " +
  "uncertainty, and limits intact; never invent data. The report MUST contain a dedicated, detailed section " +
  "titled '## 논문의 결론 vs 우리가 계산한 결과 — 얼마나 일치할까?' that: (1) restates the original paper's " +
  "published conclusion in plain words, (2) states what THIS tutorial actually measured, (3) judges — point by " +
  "point — where they AGREE and where they DIFFER, using a simple 일치/부분일치/불일치 verdict, and (4) explains " +
  "that this tutorial may differ from the original paper in methods and dataset scale, so method differences can " +
  "themselves cause differences, and that agreement here is supportive evidence, not clinical proof. Output " +
  "clean GitHub-flavored Markdown with short headings and a final '💡 한 줄 요약'. Do not mention this instruction."

let panel: vscode.WebviewPanel | undefined
let controller: AbortController | undefined

// Read the pipeline's result files (as declared by the module's AI config) into a
// single prompt context string. Returns undefined if none of them exist yet.
function readResults(resultsDir: string, ai: AiConfig): string | undefined {
  const files = ai.context ?? []
  const existing = files.filter((c) => fs.existsSync(path.join(resultsDir, c.file)))
  if (existing.length === 0) return undefined
  let ctx = ""
  for (const c of existing) {
    const raw = fs.readFileSync(path.join(resultsDir, c.file), "utf8")
    if (c.topByRank) {
      const lines = raw.split("\n")
      const head = lines[0]
      const kept = lines.slice(1).filter((l) => {
        const rank = Number(l.split(",")[1])
        return rank >= 1 && rank <= c.topByRank!
      })
      ctx += `\n## ${c.heading}\n${head}\n${kept.join("\n")}\n`
    } else {
      ctx += `\n## ${c.heading}\n${raw}\n`
    }
  }
  return ctx
}

// Preset-prompt answers are cached to disk so clicking the same button again reuses the answer
// instead of re-hitting the LLM. The cache auto-invalidates when the underlying result files change
// (any context file newer than the cache ⇒ stale ⇒ regenerate).
function aiCacheFile(resultsDir: string, promptKey: string): string {
  return path.join(resultsDir, ".ai_cache", `${promptKey.replace(/[^a-zA-Z0-9_-]/g, "_")}.md`)
}
function newestContextMtime(resultsDir: string, ai: AiConfig): number {
  let newest = 0
  for (const c of ai.context ?? []) {
    try {
      newest = Math.max(newest, fs.statSync(path.join(resultsDir, c.file)).mtimeMs)
    } catch {
      /* missing file */
    }
  }
  return newest
}
const LABEL_RE = /^<!--\s*GHBIO_AI_LABEL:[^\n]*-->\r?\n\r?\n?/
function readFreshCache(resultsDir: string, ai: AiConfig, promptKey: string): string | undefined {
  try {
    const f = aiCacheFile(resultsDir, promptKey)
    const st = fs.statSync(f)
    // Strip the label header line so the panel shows just the answer.
    if (st.mtimeMs >= newestContextMtime(resultsDir, ai)) return fs.readFileSync(f, "utf8").replace(LABEL_RE, "")
  } catch {
    /* no cache yet */
  }
  return undefined
}
// Persist with a label header so 05_make_report.sh can title each cached answer's report section.
function writeCache(resultsDir: string, promptKey: string, label: string, text: string) {
  try {
    const f = aiCacheFile(resultsDir, promptKey)
    fs.mkdirSync(path.dirname(f), { recursive: true })
    fs.writeFileSync(f, `<!-- GHBIO_AI_LABEL: ${label} -->\n\n${text}`, "utf8")
  } catch {
    /* best effort */
  }
}

export function openAI(context: vscode.ExtensionContext, pipelineId?: string) {
  const modules = loadModules(context)
  const resolved = (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
  if (!resolved) {
    vscode.window.showErrorMessage("GHBIO: no analysis module found.")
    return
  }
  // Module defaults cover a domain; an individual pipeline may override prompts/system
  // when it has different biology (for example, a lung-cancer atlas vs PBMC).
  const ai: AiConfig = { ...(resolved.module.ai ?? {}), ...(resolved.pipeline.ai ?? {}) }
  const resultsDir = tutorialResultsDir(resolved.pipeline.id)
  const pipelineDir = resolved.pipeline.dir
  const prompts: AiPromptSpec[] = ai.prompts ?? []

  if (panel) {
    panel.reveal()
    return
  }
  panel = vscode.window.createWebviewPanel("ghbioAI", "GHBIO · AI Analysis", vscode.ViewColumn.Active, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  panel.onDidDispose(() => {
    controller?.abort()
    panel = undefined
  })

  const providers = loadProviders()
  const available = Object.keys(providers).filter((p) => providers[p]?.apiKey)
  const modelMap: Record<string, string[]> = {}
  for (const p of available)
    modelMap[p] = providers[p].models?.length ? providers[p].models! : ai.models?.[p] ?? DEFAULT_MODELS[p] ?? []

  panel.webview.html = html(available, modelMap, prompts, resolved.module.name, ai.intro, ai.easyReport, ai.survey)

  panel.webview.onDidReceiveMessage(async (m) => {
    if (m.type === "stop") {
      controller?.abort()
      return
    }
    // The comprehension-survey buttons open their own webview panels (form / stats),
    // scoped to this pipeline. Delegated to commands so the survey module owns them.
    if (m.type === "openSurvey") {
      vscode.commands.executeCommand("ghbio.openSurvey", resolved.pipeline.id)
      return
    }
    if (m.type === "openSurveyStats") {
      vscode.commands.executeCommand("ghbio.openSurveyStats", resolved.pipeline.id)
      return
    }
    // Save the current answer into one of the report's AI write-up files so
    // 05_make_report.sh folds it into the PDF. easy -> plain-language section,
    // expert -> expert section. The report treats both as optional.
    if (m.type === "save" && panel) {
      const file = m.target === "easy" ? "step4_ai_report_easy.md" : "step4_ai_report.md"
      const heading = m.target === "easy" ? "# AI 해석 (쉬운 설명)\n\n" : "# AI 해석 (전문가)\n\n"
      try {
        fs.mkdirSync(resultsDir, { recursive: true })
        fs.writeFileSync(path.join(resultsDir, file), heading + String(m.text ?? ""), "utf8")
        panel.webview.postMessage({ type: "saved", file })
      } catch (e: any) {
        panel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
      }
      return
    }
    // Turn the answer currently shown in the panel into a report that a high-school
    // reader can follow. This deliberately overwrites the easy-report file: that is
    // the report section users selected, and 05_make_report.sh already consumes it.
    if (m.type === "highSchoolReport" && panel) {
      const source = String(m.text ?? "").trim()
      const key = providers[m.provider]?.apiKey
      if (!source) {
        panel.webview.postMessage({ type: "error", msg: "먼저 AI 분석 결과를 생성해 주세요." })
        return
      }
      if (!key) {
        panel.webview.postMessage({ type: "error", msg: `${m.provider} API key가 설정되지 않았습니다.` })
        return
      }
      controller?.abort()
      controller = new AbortController()
      panel.webview.postMessage({ type: "highSchoolStart" })
      let full = ""
      try {
        await streamChat({
          provider: m.provider,
          model: m.model,
          apiKey: key,
          system: HIGH_SCHOOL_REPORT_SYSTEM,
          user: `다음 AI 분석을 고등학생 독자를 위한 보고서로 다시 작성해 주세요. 비유를 충분히 사용하세요.\n\n${source}`,
          signal: controller.signal,
          onDelta: (t) => {
            if (!t) return
            full += t
            panel?.webview.postMessage({ type: "delta", text: t })
          },
        })
        if (full.trim()) {
          fs.mkdirSync(resultsDir, { recursive: true })
          fs.writeFileSync(path.join(resultsDir, "step4_ai_report_easy.md"), "# AI 해석 (고등학생 버전)\n\n" + full, "utf8")
          panel?.webview.postMessage({ type: "highSchoolSaved", file: "step4_ai_report_easy.md" })
        }
        panel?.webview.postMessage({ type: "done" })
      } catch (e: any) {
        if (e?.name === "AbortError") panel?.webview.postMessage({ type: "done", aborted: true })
        else panel?.webview.postMessage({ type: "error", msg: String(e?.message ?? e) })
      }
      return
    }
    // One-click 고등학생버전보고서: rewrite the analysis (its step4 report files + saved AI answers +
    // result tables) into a metaphor-rich high-school report whose centerpiece is a paper-vs-tutorial
    // agreement check, overwrite BOTH step4 report files with it, then build and open a PDF.
    if (m.type === "easyReport" && panel) {
      const spec = ai.easyReport
      if (!spec) return
      const key = providers[m.provider]?.apiKey
      if (!key) {
        panel.webview.postMessage({ type: "error", msg: `${m.provider} API key가 설정되지 않았습니다.` })
        return
      }
      const ctx = readResults(resultsDir, ai)
      const readMd = (f: string): string => {
        try {
          return fs.readFileSync(path.join(resultsDir, f), "utf8")
        } catch {
          return ""
        }
      }
      const easyMd = readMd("step4_ai_report_easy.md")
      const expertMd = readMd("step4_ai_report.md")
      // Fold in every preset answer the user has generated (interpret / annotate / RD-vs-PD / hypotheses).
      let cachedAll = ""
      try {
        const cacheDir = path.join(resultsDir, ".ai_cache")
        for (const f of fs.readdirSync(cacheDir)) {
          if (f.endsWith(".md")) cachedAll += `\n\n${fs.readFileSync(path.join(cacheDir, f), "utf8").replace(LABEL_RE, "")}`
        }
      } catch {
        /* no cached answers yet */
      }
      if (!ctx && !easyMd && !expertMd && !cachedAll.trim()) {
        panel.webview.postMessage({
          type: "error",
          msg: ai.readyHint ?? "아직 분석 결과가 없습니다. 먼저 분석 단계와 AI 해석을 실행해 주세요.",
        })
        return
      }
      const reportTitle = spec.title ?? "# 🔬 세포 이야기 — 고등학생 리포트"
      const datasetLabel = spec.datasetLabel ?? "이 scRNA-seq 튜토리얼"
      const user =
        (spec.paperClaim ? `[원 논문의 주장]\n${spec.paperClaim}\n\n` : "") +
        `아래는 ${datasetLabel}의 결과 표와, 지금까지 생성된 AI 해석·보고서 초안입니다. ` +
        "이것을 고등학생 독자를 위한 하나의 보고서로 다시 써 주세요. 비유를 아주 많이 사용하고, 특히 " +
        "'원 논문이 주장한 결론'과 '이 튜토리얼로 실제 계산한 결과'가 얼마나 일치하는지를 별도 섹션에서 " +
        `항목별로 자세히 비교해 주세요. 제목은 '${reportTitle}'로 시작하세요.\n\n` +
        (ctx ? `=== 결과 표(계산 결과) ===\n${ctx}\n\n` : "") +
        (easyMd ? `=== 쉬운 설명 초안 (step4_ai_report_easy.md) ===\n${easyMd}\n\n` : "") +
        (expertMd ? `=== 전문가 해석 (step4_ai_report.md) ===\n${expertMd}\n\n` : "") +
        (cachedAll.trim() ? `=== 저장된 AI 해석들 ===\n${cachedAll}\n` : "")
      controller?.abort()
      controller = new AbortController()
      panel.webview.postMessage({ type: "highSchoolStart" })
      let full = ""
      try {
        await streamChat({
          provider: m.provider,
          model: m.model,
          apiKey: key,
          system: EASY_REPORT_SYSTEM,
          user,
          signal: controller.signal,
          onDelta: (t) => {
            if (!t) return
            full += t
            panel?.webview.postMessage({ type: "delta", text: t })
          },
        })
        if (!full.trim()) {
          panel?.webview.postMessage({ type: "done", aborted: true })
          return
        }
        // The high-school rewrite IS the report: land it in both step4 files so any report
        // stage folds it in, and drive the dedicated PDF from the easy file.
        fs.mkdirSync(resultsDir, { recursive: true })
        fs.writeFileSync(path.join(resultsDir, "step4_ai_report_easy.md"), full, "utf8")
        fs.writeFileSync(path.join(resultsDir, "step4_ai_report.md"), full, "utf8")
        panel?.webview.postMessage({ type: "highSchoolSaved", file: "step4_ai_report_easy.md" })
        // Build the PDF (if the pipeline ships a report script) and open it when it finishes.
        if (spec.makeReport) {
          panel?.webview.postMessage({ type: "pdfBuilding" })
          const outPdf = path.join(resultsDir, "GHBIO_고등학생_리포트.pdf")
          const exec = await runShellTask(
            "GHBIO: 고등학생버전보고서 PDF",
            `bash ${spec.makeReport}`,
            pipelineDir,
            { GHBIO_RESULTS: resultsDir },
          )
          const done = vscode.tasks.onDidEndTask((e) => {
            if (e.execution !== exec) return
            done.dispose()
            if (fs.existsSync(outPdf)) {
              panel?.webview.postMessage({ type: "pdfDone", file: "GHBIO_고등학생_리포트.pdf" })
              vscode.commands.executeCommand("vscode.open", vscode.Uri.file(outPdf))
            } else {
              panel?.webview.postMessage({ type: "pdfError" })
            }
          })
          context.subscriptions.push(done)
        }
        panel?.webview.postMessage({ type: "done" })
      } catch (e: any) {
        if (e?.name === "AbortError") panel?.webview.postMessage({ type: "done", aborted: true })
        else panel?.webview.postMessage({ type: "error", msg: String(e?.message ?? e) })
      }
      return
    }
    if (m.type !== "run" || !panel) return
    const isFree = m.promptKey === "free"
    const question = isFree ? m.text : prompts.find((p) => p.key === m.promptKey)?.q
    if (!question) return

    // Reuse a cached preset answer (unless the user asked to regenerate) so repeated clicks don't
    // re-run the LLM. Free-form questions are never cached (they're arbitrary one-offs).
    if (!isFree && !m.force) {
      const cached = readFreshCache(resultsDir, ai, m.promptKey)
      if (cached) {
        panel.webview.postMessage({ type: "start" })
        panel.webview.postMessage({ type: "delta", text: cached })
        panel.webview.postMessage({ type: "done", cached: true })
        return
      }
    }

    const ctx = readResults(resultsDir, ai)
    // Preset prompts interpret analysis results, so they need result files. A free-form
    // question (e.g. "what is FASTQ format?") is answered anytime — with the results
    // attached as context when they exist, without them otherwise.
    if (!ctx && !isFree) {
      panel.webview.postMessage({
        type: "error",
        msg: ai.readyHint ?? "결과 파일이 아직 없습니다. 먼저 분석 단계를 실행해 주세요.",
      })
      return
    }
    const key = providers[m.provider]?.apiKey
    if (!key) {
      panel.webview.postMessage({ type: "error", msg: `${m.provider} API key가 설정되지 않았습니다.` })
      return
    }
    controller?.abort()
    controller = new AbortController()
    panel.webview.postMessage({ type: "start" })
    const user = ctx ? `Results context:\n\n${ctx}\n\n---\nQuestion: ${question}` : question
    let full = ""
    try {
      await streamChat({
        provider: m.provider,
        model: m.model,
        apiKey: key,
        system: ai.system ?? DEFAULT_SYSTEM,
        user,
        signal: controller.signal,
        onDelta: (t) => {
          if (!t) return
          full += t
          panel?.webview.postMessage({ type: "delta", text: t })
        },
      })
      // Persist preset answers so future clicks reuse them instead of re-calling the LLM,
      // and so the report can fold them in automatically. Tag with the prompt's label.
      if (!isFree && full.trim()) {
        const label = prompts.find((p) => p.key === m.promptKey)?.label ?? m.promptKey
        writeCache(resultsDir, m.promptKey, label, full)
        // The dedicated high-school-report prompt is an output action, not just a
        // preview: make it immediately available to the PDF-report stage.
        if (m.promptKey === "easy_report") {
          fs.mkdirSync(resultsDir, { recursive: true })
          fs.writeFileSync(path.join(resultsDir, "step4_ai_report_easy.md"), "# AI 해석 (고등학생 버전)\n\n" + full, "utf8")
          panel?.webview.postMessage({ type: "highSchoolSaved", file: "step4_ai_report_easy.md" })
        }
      }
      panel?.webview.postMessage({ type: "done" })
    } catch (e: any) {
      if (e?.name === "AbortError") panel?.webview.postMessage({ type: "done", aborted: true })
      else panel?.webview.postMessage({ type: "error", msg: String(e?.message ?? e) })
    }
  })
}

function html(
  providers: string[],
  modelMap: Record<string, string[]>,
  prompts: AiPromptSpec[],
  moduleName: string,
  intro?: string,
  easyReport?: EasyReportSpec,
  survey?: SurveySpec,
): string {
  const noKeys = providers.length === 0
  const provOpts = providers.map((p) => `<option value="${p}">${p}</option>`).join("")
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!))
  const promptBtns = prompts.map((p) => `<button class="p" data-k="${p.key}">${p.label}</button>`).join("")
  // The 고등학생버전보고서 action button sits right after the preset prompts (i.e. after
  // "Testable treatment hypotheses"), visually distinct so it reads as an output action.
  const easyBtn = easyReport
    ? `<button class="p easyrep" id="easyReportBtn" title="논문 결론 vs 이 튜토리얼 계산 결과의 일치 여부까지 담은 고등학생용 보고서를 다시 작성하고 PDF로 만듭니다">${esc(
        easyReport.label,
      )}</button>`
    : ""
  // Survey (이해도 테스트) + its aggregated results, for education research.
  const surveyBtns = survey
    ? `<button class="p survey" id="surveyBtn" title="학생 대상 이해도 설문(객관식+설문 문항)을 엽니다">${esc(
        survey.testLabel ?? "📝 이해도테스트",
      )}</button><button class="p surveystat" id="surveyStatsBtn" title="제출된 응답의 통계(점수 분포·문항 정답률·학년별)를 봅니다">${esc(
        survey.resultLabel ?? "📊 결과 통계",
      )}</button>`
    : ""
  const sub = intro ?? "결과를 LLM에 보내 해석·가설을 받습니다. 단발성 요청이라 파일을 수정하거나 배회하지 않습니다."
  return /* html */ `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  :root{color-scheme:dark}
  body{font-family:-apple-system,"Segoe UI",system-ui,sans-serif;color:#e6edf3;background:#0d1117;margin:0;padding:16px 20px}
  h2{margin:0 0 4px;font-size:18px}.a{color:#2dd4bf}
  .sub{color:#8b98a5;font-size:12.5px;margin-bottom:14px}
  select,button{font:inherit}
  .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
  select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:5px 8px}
  button{cursor:pointer;border:none;border-radius:7px;padding:6px 11px;font-size:12.5px}
  button.p{background:#21262d;color:#e6edf3;border:1px solid #30363d}
  button.p:hover{border-color:#2dd4bf}
  button.p.easyrep{background:#31224d;color:#dfccff;border:1px solid #7555a8}
  button.p.easyrep:hover{border-color:#b99aff}
  button.p.survey{background:#13314d;color:#bfe0ff;border:1px solid #2f6ea8}
  button.p.survey:hover{border-color:#6bb6ff}
  button.p.surveystat{background:#1a3a2a;color:#bff0d0;border:1px solid #2f8a5a}
  button.p.surveystat:hover{border-color:#5fd08a}
  #stop{background:#3d1418;color:#ffb4b4;border:1px solid #6e2b2b;display:none}
  .prompts{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px}
  #free{width:100%;box-sizing:border-box;background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:8px;padding:8px;min-height:44px;margin-bottom:8px}
  #out{background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:14px 16px;min-height:120px;
    white-space:pre-wrap;line-height:1.6;font-size:13.5px}
  #out h1,#out h2,#out h3{color:#7ee7d6} #out code{background:#161b22;padding:1px 4px;border-radius:4px}
  #out table{border-collapse:collapse} #out td,#out th{border:1px solid #30363d;padding:3px 7px}
  .warn{background:#3a2a12;border:1px solid #7a5a1e;color:#f0d090;padding:10px;border-radius:8px;font-size:13px}
  #save-bar{display:none;align-items:center;gap:8px;margin-bottom:8px}
  #save-bar button.save{background:#12312b;color:#7ee7d6;border:1px solid #1f5a4f}
  #save-bar button.save:hover{border-color:#2dd4bf}
  #save-bar button#highSchool{background:#31224d;color:#dfccff;border:1px solid #7555a8}
  #save-bar button#highSchool:hover{border-color:#b99aff}
  .savehint{color:#8b98a5;font-size:12px}
  #saveMsg{font-size:12px;color:#2dd4bf}
  .cachedtag{font-size:12px;color:#e2b341}
  #save-bar button#regen{background:#21262d;color:#e6edf3;border:1px solid #30363d}
  #save-bar button#regen:hover{border-color:#e2b341}
</style></head><body>
  <h2>GHBIO <span class="a">AI Analysis</span> · ${moduleName}</h2>
  <div class="sub">${sub}</div>
  ${noKeys ? `<div class="warn">API 키가 설정되지 않았습니다. <code>~/.config/ghbio/providers.json</code> 를 확인하세요.</div>` : `
  <div class="bar">
    <label>Provider <select id="prov">${provOpts}</select></label>
    <label>Model <select id="model"></select></label>
    <button id="stop">■ Stop</button>
  </div>
  <div class="prompts">${promptBtns}${easyBtn}${surveyBtns}</div>
  <textarea id="free" placeholder="아무 질문이나 입력하고 Ctrl+Enter — 예: FASTQ 포맷이 뭐야? (분석 결과가 없어도 바로 답합니다)"></textarea>
  <div id="save-bar">
    <span id="cachedTag" class="cachedtag"></span>
    <button id="regen" class="save" title="LLM을 다시 호출해 새로 생성합니다">🔄 다시 생성</button>
    <span class="savehint">이 답변을 리포트에 저장:</span>
    <button id="highSchool" class="save" title="비유를 많이 사용한 고등학생용 보고서로 다시 작성해 step4_ai_report_easy.md에 저장합니다">🎓 고등학생 버전 보고서</button>
    <button id="saveEasy" class="save">💾 쉬운 설명</button>
    <button id="saveExpert" class="save">💾 전문가용</button>
    <span id="saveMsg"></span>
  </div>
  <div id="out">결과가 여기에 표시됩니다.</div>`}
  <script>
    const vscode = acquireVsCodeApi()
    const MODELS = ${JSON.stringify(modelMap)}
    const prov = document.getElementById('prov'), model = document.getElementById('model')
    const out = document.getElementById('out'), stop = document.getElementById('stop')
    function fillModels(){ if(!prov) return; model.innerHTML = (MODELS[prov.value]||[]).map(m=>'<option>'+m+'</option>').join('') }
    if(prov){ prov.onchange = fillModels; fillModels() }
    let raw = ''
    function md(t){ return t
      .replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))
      .replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>')
      .replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>').replace(/\`(.+?)\`/g,'<code>$1</code>') }
    let lastWasPreset=false, lastPromptKey=null
    function run(promptKey, text, force){ raw=''; out.innerHTML='…'; stop.style.display='inline-block'
      lastWasPreset = promptKey!=='free'; lastPromptKey = promptKey
      if(typeof hideSave==='function') hideSave()
      vscode.postMessage({ type:'run', provider:prov.value, model:model.value, promptKey, text, force: !!force }) }
    document.querySelectorAll('button.p[data-k]').forEach(b=> b.onclick=()=>run(b.dataset.k))
    const easyReportBtn = document.getElementById('easyReportBtn')
    if(easyReportBtn) easyReportBtn.onclick=()=>{ raw=''; out.innerHTML='🎓 고등학생 버전 보고서를 작성하는 중…'; stop.style.display='inline-block'
      lastWasPreset=false; lastPromptKey=null; if(typeof hideSave==='function') hideSave()
      vscode.postMessage({ type:'easyReport', provider:prov.value, model:model.value }) }
    const surveyBtn=document.getElementById('surveyBtn'), surveyStatsBtn=document.getElementById('surveyStatsBtn')
    if(surveyBtn) surveyBtn.onclick=()=>vscode.postMessage({type:'openSurvey'})
    if(surveyStatsBtn) surveyStatsBtn.onclick=()=>vscode.postMessage({type:'openSurveyStats'})
    if(stop) stop.onclick=()=>vscode.postMessage({type:'stop'})
    const free = document.getElementById('free')
    if(free) free.addEventListener('keydown',e=>{ if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&free.value.trim()) run('free',free.value.trim()) })
    const saveBar=document.getElementById('save-bar'), saveMsg=document.getElementById('saveMsg')
    const saveEasy=document.getElementById('saveEasy'), saveExpert=document.getElementById('saveExpert'), highSchool=document.getElementById('highSchool')
    const regen=document.getElementById('regen'), cachedTag=document.getElementById('cachedTag')
    function hideSave(){ if(saveBar){ saveBar.style.display='none'; saveMsg.textContent='' } if(cachedTag) cachedTag.textContent='' }
    if(saveEasy) saveEasy.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'save',target:'easy',text:raw}) }
    if(saveExpert) saveExpert.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'save',target:'expert',text:raw}) }
    if(highSchool) highSchool.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'highSchoolReport',provider:prov.value,model:model.value,text:raw}) }
    if(regen) regen.onclick=()=>{ if(lastPromptKey && lastPromptKey!=='free') run(lastPromptKey, null, true) }
    window.addEventListener('message',ev=>{ const m=ev.data
      if(m.type==='start'){ raw=''; out.innerHTML='…'; hideSave() }
      else if(m.type==='highSchoolStart'){ raw=''; out.innerHTML='…'; stop.style.display='inline-block'; hideSave() }
      else if(m.type==='delta'){ raw+=m.text; out.innerHTML=md(raw) }
      else if(m.type==='done'){ stop.style.display='none'; if(m.aborted) out.innerHTML+=' <i>(중지됨)</i>'
        if(saveBar && lastWasPreset && !m.aborted && raw.trim()){ saveBar.style.display='flex'
          if(cachedTag) cachedTag.textContent = m.cached ? '💾 저장된 결과 (LLM 재호출 안 함)' : '' } }
      else if(m.type==='error'){ stop.style.display='none'; hideSave(); out.innerHTML='<div class="warn">'+m.msg+'</div>' }
      else if(m.type==='saved'){ if(saveMsg) saveMsg.textContent='저장됨: '+m.file }
      else if(m.type==='highSchoolSaved'){ if(saveMsg) saveMsg.textContent='고등학생 버전 저장됨: '+m.file }
      else if(m.type==='pdfBuilding'){ out.innerHTML+='<div class="warn">📄 PDF를 만드는 중입니다… 완료되면 자동으로 열립니다.</div>' }
      else if(m.type==='pdfDone'){ out.innerHTML+='<div class="warn" style="background:#12312b;border-color:#1f5a4f;color:#7ee7d6">✅ PDF 생성 완료: '+m.file+' — Projects 결과 폴더에 저장되었습니다.</div>' }
      else if(m.type==='pdfError'){ out.innerHTML+='<div class="warn">PDF 생성에 실패했습니다. 터미널의 오류 메시지를 확인하세요 (pandoc·wkhtmltopdf 필요).</div>' }
      else if(m.type==='saveError'){ if(saveMsg) saveMsg.textContent='저장 실패: '+m.msg }
    })
  </script>
</body></html>`
}
