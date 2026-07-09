import * as vscode from "vscode"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { loadProviders, streamChat } from "./providers"

const RESULTS = path.join(os.homedir(), "ghbio-tutorial", "results")

const DEFAULT_MODELS: Record<string, string[]> = {
  anthropic: ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5-20251001"],
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
  openrouter: ["anthropic/claude-sonnet-4", "deepseek/deepseek-chat", "google/gemini-2.0-flash-001"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
}

const PROMPTS: { key: string; label: string; q: string }[] = [
  { key: "interpret", label: "Interpret each cluster", q: "각 cluster의 세포 정체성과 활성화 상태를 top marker로 해석하고 confidence와 애매/doublet 의심 cluster를 표시해줘." },
  { key: "annotate", label: "Refine cell-type annotation", q: "PBMC canonical marker(CD3D/CD3E, CD8A, IL7R, MS4A1/CD79A, NKG7/GNLY, CD14/LYZ, FCGR3A/MS4A7, FCER1A, PPBP)를 이용해 cluster별 cell type을 다듬고 근거 유전자와 함께 최종 표를 만들어줘." },
  { key: "pathway", label: "Pathway / functional", q: "관심 cluster의 marker들을 주요 pathway/생물학적 프로그램으로 묶어 기능적 의미를 설명하고 enrichment로 검증할 gene set을 제안해줘." },
  { key: "hypothesis", label: "Testable hypotheses", q: "marker·annotation·pathway를 근거로 검증 가능한 가설 3~5개를 제시하고 각 가설의 근거·예측·검증 방법을 알려줘." },
  { key: "questions", label: "Analysis question list", q: "이 데이터로 이어서 수행할 후속 분석 질문 약 8~10개를 과학적 가치·실행가능성 순으로 우선순위를 매겨 목록으로 만들고 각 항목에 한 줄 방법 메모를 붙여줘." },
]

const SYSTEM =
  "You are the GHBIO AI Co-Scientist, a careful single-cell RNA-seq analyst. Answer the user's ONE question " +
  "directly using the provided cluster markers and draft cell types. Be concise, structured (headings, tables, " +
  "short lists), and rigorous. Do NOT run code or ask to; just interpret. Reply in Korean unless asked otherwise."

let panel: vscode.WebviewPanel | undefined
let controller: AbortController | undefined

function readResults(): string | undefined {
  const draft = path.join(RESULTS, "celltype_draft.csv")
  const markers = path.join(RESULTS, "markers_by_cluster.csv")
  if (!fs.existsSync(draft) && !fs.existsSync(markers)) return undefined
  let ctx = ""
  if (fs.existsSync(draft)) ctx += "## Draft cell-type annotation (celltype_draft.csv)\n" + fs.readFileSync(draft, "utf8") + "\n"
  if (fs.existsSync(markers)) {
    // top 10 markers per cluster to keep the prompt tight
    const lines = fs.readFileSync(markers, "utf8").split("\n")
    const head = lines[0]
    const kept = lines.slice(1).filter((l) => {
      const rank = Number(l.split(",")[1])
      return rank >= 1 && rank <= 10
    })
    ctx += "\n## Top markers per cluster (markers_by_cluster.csv, top10)\n" + head + "\n" + kept.join("\n") + "\n"
  }
  return ctx
}

export function openAI(context: vscode.ExtensionContext) {
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
  for (const p of available) modelMap[p] = providers[p].models?.length ? providers[p].models! : DEFAULT_MODELS[p] ?? []

  panel.webview.html = html(available, modelMap, PROMPTS)

  panel.webview.onDidReceiveMessage(async (m) => {
    if (m.type === "stop") {
      controller?.abort()
      return
    }
    if (m.type !== "run" || !panel) return
    const question = m.promptKey === "free" ? m.text : PROMPTS.find((p) => p.key === m.promptKey)?.q
    if (!question) return
    const ctx = readResults()
    if (!ctx) {
      panel.webview.postMessage({ type: "error", msg: "결과 파일이 없습니다. 먼저 Tutorial의 Step 3(Scanpy QC/clustering)를 실행해 markers_by_cluster.csv / celltype_draft.csv 를 만들어 주세요." })
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
    const user = `Cluster results:\n\n${ctx}\n\n---\nQuestion: ${question}`
    try {
      await streamChat({
        provider: m.provider,
        model: m.model,
        apiKey: key,
        system: SYSTEM,
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

function html(providers: string[], modelMap: Record<string, string[]>, prompts: typeof PROMPTS): string {
  const noKeys = providers.length === 0
  const provOpts = providers.map((p) => `<option value="${p}">${p}</option>`).join("")
  const promptBtns = prompts.map((p) => `<button class="p" data-k="${p.key}">${p.label}</button>`).join("")
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
</style></head><body>
  <h2>GHBIO <span class="a">AI Analysis</span></h2>
  <div class="sub">클러스터 마커·세포타입을 LLM에 보내 해석·가설을 받습니다. 단발성 요청이라 파일을 수정하거나 배회하지 않습니다.</div>
  ${noKeys ? `<div class="warn">API 키가 설정되지 않았습니다. <code>~/.config/ghbio/providers.json</code> 를 확인하세요.</div>` : `
  <div class="bar">
    <label>Provider <select id="prov">${provOpts}</select></label>
    <label>Model <select id="model"></select></label>
    <button id="stop">■ Stop</button>
  </div>
  <div class="prompts">${promptBtns}</div>
  <textarea id="free" placeholder="또는 직접 질문을 입력하고 Ctrl+Enter…"></textarea>
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
    function run(promptKey, text){ raw=''; out.innerHTML='…'; stop.style.display='inline-block'
      vscode.postMessage({ type:'run', provider:prov.value, model:model.value, promptKey, text }) }
    document.querySelectorAll('button.p').forEach(b=> b.onclick=()=>run(b.dataset.k))
    if(stop) stop.onclick=()=>vscode.postMessage({type:'stop'})
    const free = document.getElementById('free')
    if(free) free.addEventListener('keydown',e=>{ if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&free.value.trim()) run('free',free.value.trim()) })
    window.addEventListener('message',ev=>{ const m=ev.data
      if(m.type==='start'){ raw=''; out.innerHTML='…' }
      else if(m.type==='delta'){ raw+=m.text; out.innerHTML=md(raw) }
      else if(m.type==='done'){ stop.style.display='none'; if(m.aborted) out.innerHTML+=' <i>(중지됨)</i>' }
      else if(m.type==='error'){ stop.style.display='none'; out.innerHTML='<div class="warn">'+m.msg+'</div>' }
    })
  </script>
</body></html>`
}
