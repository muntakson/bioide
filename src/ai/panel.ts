import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { loadProviders, streamChat } from "./providers"
import { tutorialResultsDir } from "../util"
import { AiConfig, AiPromptSpec, loadModules, findPipeline, defaultPipeline } from "../modules"

// Fallback models when a module doesn't pin its own.
const DEFAULT_MODELS: Record<string, string[]> = {
  anthropic: ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5-20251001"],
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
  openrouter: ["anthropic/claude-sonnet-4", "deepseek/deepseek-chat", "google/gemini-2.0-flash-001"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
}

const DEFAULT_SYSTEM =
  "You are the GHBIO AI Co-Scientist. Answer the user's ONE question directly using the provided " +
  "results context. Be concise, structured (headings, tables, short lists), and rigorous. Do NOT run " +
  "code or ask to; just interpret. Reply in Korean unless asked otherwise."

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

export function openAI(context: vscode.ExtensionContext, pipelineId?: string) {
  const modules = loadModules(context)
  const resolved = (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
  if (!resolved) {
    vscode.window.showErrorMessage("GHBIO: no analysis module found.")
    return
  }
  const ai: AiConfig = resolved.module.ai ?? {}
  const resultsDir = tutorialResultsDir(resolved.pipeline.id)
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

  panel.webview.html = html(available, modelMap, prompts, resolved.module.name, ai.intro)

  panel.webview.onDidReceiveMessage(async (m) => {
    if (m.type === "stop") {
      controller?.abort()
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
    if (m.type !== "run" || !panel) return
    const isFree = m.promptKey === "free"
    const question = isFree ? m.text : prompts.find((p) => p.key === m.promptKey)?.q
    if (!question) return
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
    try {
      await streamChat({
        provider: m.provider,
        model: m.model,
        apiKey: key,
        system: ai.system ?? DEFAULT_SYSTEM,
        user,
        signal: controller.signal,
        onDelta: (t) => t && panel?.webview.postMessage({ type: "delta", text: t }),
      })
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
): string {
  const noKeys = providers.length === 0
  const provOpts = providers.map((p) => `<option value="${p}">${p}</option>`).join("")
  const promptBtns = prompts.map((p) => `<button class="p" data-k="${p.key}">${p.label}</button>`).join("")
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
  .savehint{color:#8b98a5;font-size:12px}
  #saveMsg{font-size:12px;color:#2dd4bf}
</style></head><body>
  <h2>GHBIO <span class="a">AI Analysis</span> · ${moduleName}</h2>
  <div class="sub">${sub}</div>
  ${noKeys ? `<div class="warn">API 키가 설정되지 않았습니다. <code>~/.config/ghbio/providers.json</code> 를 확인하세요.</div>` : `
  <div class="bar">
    <label>Provider <select id="prov">${provOpts}</select></label>
    <label>Model <select id="model"></select></label>
    <button id="stop">■ Stop</button>
  </div>
  <div class="prompts">${promptBtns}</div>
  <textarea id="free" placeholder="아무 질문이나 입력하고 Ctrl+Enter — 예: FASTQ 포맷이 뭐야? (분석 결과가 없어도 바로 답합니다)"></textarea>
  <div id="save-bar">
    <span class="savehint">이 답변을 리포트에 저장:</span>
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
    let lastWasPreset=false
    function run(promptKey, text){ raw=''; out.innerHTML='…'; stop.style.display='inline-block'
      lastWasPreset = promptKey!=='free'
      if(typeof hideSave==='function') hideSave()
      vscode.postMessage({ type:'run', provider:prov.value, model:model.value, promptKey, text }) }
    document.querySelectorAll('button.p').forEach(b=> b.onclick=()=>run(b.dataset.k))
    if(stop) stop.onclick=()=>vscode.postMessage({type:'stop'})
    const free = document.getElementById('free')
    if(free) free.addEventListener('keydown',e=>{ if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&free.value.trim()) run('free',free.value.trim()) })
    const saveBar=document.getElementById('save-bar'), saveMsg=document.getElementById('saveMsg')
    const saveEasy=document.getElementById('saveEasy'), saveExpert=document.getElementById('saveExpert')
    function hideSave(){ if(saveBar){ saveBar.style.display='none'; saveMsg.textContent='' } }
    if(saveEasy) saveEasy.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'save',target:'easy',text:raw}) }
    if(saveExpert) saveExpert.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'save',target:'expert',text:raw}) }
    window.addEventListener('message',ev=>{ const m=ev.data
      if(m.type==='start'){ raw=''; out.innerHTML='…'; hideSave() }
      else if(m.type==='delta'){ raw+=m.text; out.innerHTML=md(raw) }
      else if(m.type==='done'){ stop.style.display='none'; if(m.aborted) out.innerHTML+=' <i>(중지됨)</i>'
        if(saveBar && lastWasPreset && !m.aborted && raw.trim()) saveBar.style.display='flex' }
      else if(m.type==='error'){ stop.style.display='none'; hideSave(); out.innerHTML='<div class="warn">'+m.msg+'</div>' }
      else if(m.type==='saved'){ if(saveMsg) saveMsg.textContent='저장됨: '+m.file }
      else if(m.type==='saveError'){ if(saveMsg) saveMsg.textContent='저장 실패: '+m.msg }
    })
  </script>
</body></html>`
}
