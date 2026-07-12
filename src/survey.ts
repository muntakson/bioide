import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import { tutorialResultsDir } from "./util"
import { loadModules, findPipeline, defaultPipeline } from "./modules"

// =============================================================================
// Comprehension survey ("이해도 테스트") for the 고등학생버전 report.
//
// A self-contained instrument for biology-education research (생물교육학회): a
// webview form of N multiple-choice knowledge items + M Likert attitude items,
// plus student name / grade / email. Submissions are scored server-side (the
// answer key never reaches the browser) and appended to a per-pipeline "backend
// table" — a JSONL file (source of truth) mirrored to a CSV for easy import into
// R / SPSS / Excel. A separate stats view aggregates all responses (score
// distribution, per-item difficulty, Likert means, by-grade breakdown).
//
// Questions live in the pipeline dir's survey.json, so the instrument is data —
// no TypeScript edit to revise the test. Enabled per-pipeline via ai.survey.
// =============================================================================

interface McQuestion {
  id: string
  q: string
  choices: string[]
  answer: number // index of the correct choice — server-side only
}
interface LikertQuestion {
  id: string
  q: string
}
interface SurveySpec {
  title?: string
  intro?: string
  likertScale?: string[]
  mc: McQuestion[]
  likert: LikertQuestion[]
}

interface SurveyResponse {
  ts: string
  pipeline: string
  name: string
  grade: string
  email: string
  score: number
  total: number
  mc: Record<string, number> // questionId -> chosen index (-1 = skipped)
  correct: Record<string, boolean>
  likert: Record<string, number> // questionId -> 1..5
  comment: string
}

const DEFAULT_SCALE = ["전혀 그렇지 않다", "그렇지 않다", "보통이다", "그렇다", "매우 그렇다"]

let surveyPanel: vscode.WebviewPanel | undefined
let statsPanel: vscode.WebviewPanel | undefined

function resolvePipeline(context: vscode.ExtensionContext, pipelineId?: string) {
  const modules = loadModules(context)
  return (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
}

function loadSurvey(pipelineDir: string): SurveySpec | undefined {
  const f = path.join(pipelineDir, "survey.json")
  if (!fs.existsSync(f)) return undefined
  try {
    const s = JSON.parse(fs.readFileSync(f, "utf8")) as SurveySpec
    if (!Array.isArray(s.mc) || !Array.isArray(s.likert)) return undefined
    return s
  } catch (e) {
    vscode.window.showErrorMessage(`GHBIO: bad survey.json — ${e}`)
    return undefined
  }
}

function surveyDir(pipelineId: string): string {
  return path.join(tutorialResultsDir(pipelineId), "survey")
}
function responsesJsonl(pipelineId: string): string {
  return path.join(surveyDir(pipelineId), "responses.jsonl")
}
function responsesCsv(pipelineId: string): string {
  return path.join(surveyDir(pipelineId), "responses.csv")
}

function readResponses(pipelineId: string): SurveyResponse[] {
  const f = responsesJsonl(pipelineId)
  if (!fs.existsSync(f)) return []
  const out: SurveyResponse[] = []
  for (const line of fs.readFileSync(f, "utf8").split("\n")) {
    const t = line.trim()
    if (!t) continue
    try {
      out.push(JSON.parse(t))
    } catch {
      /* skip a corrupt line rather than lose the whole table */
    }
  }
  return out
}

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!))
const csvCell = (s: unknown) => {
  const v = String(s ?? "")
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
}

// Rewrite the CSV mirror from the full JSONL table. Columns are stable so repeated
// exports diff cleanly and load straight into stats software.
function writeCsv(pipelineId: string, spec: SurveySpec, rows: SurveyResponse[]) {
  const mcIds = spec.mc.map((m) => m.id)
  const lkIds = spec.likert.map((l) => l.id)
  const header = [
    "timestamp",
    "name",
    "grade",
    "email",
    "score",
    "total",
    ...mcIds.map((id) => `${id}_choice`),
    ...mcIds.map((id) => `${id}_correct`),
    ...lkIds,
    "comment",
  ]
  const lines = [header.join(",")]
  for (const r of rows) {
    lines.push(
      [
        r.ts,
        csvCell(r.name),
        csvCell(r.grade),
        csvCell(r.email),
        r.score,
        r.total,
        ...mcIds.map((id) => (r.mc[id] ?? -1) + 1 || ""), // 1-based choice, blank if skipped
        ...mcIds.map((id) => (r.correct[id] ? 1 : 0)),
        ...lkIds.map((id) => r.likert[id] ?? ""),
        csvCell(r.comment),
      ].join(","),
    )
  }
  fs.writeFileSync(responsesCsv(pipelineId), lines.join("\n") + "\n", "utf8")
}

// ---------------------------------------------------------------------------
// Survey form
// ---------------------------------------------------------------------------
export function openSurvey(context: vscode.ExtensionContext, pipelineId?: string) {
  const resolved = resolvePipeline(context, pipelineId)
  if (!resolved) {
    vscode.window.showErrorMessage("GHBIO: no pipeline found for the survey.")
    return
  }
  const spec = loadSurvey(resolved.pipeline.dir)
  if (!spec) {
    vscode.window.showErrorMessage("GHBIO: 이 파이프라인에는 설문(survey.json)이 없습니다.")
    return
  }
  const pid = resolved.pipeline.id

  if (surveyPanel) {
    surveyPanel.reveal()
    return
  }
  surveyPanel = vscode.window.createWebviewPanel("ghbioSurvey", "이해도 테스트", vscode.ViewColumn.Active, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  surveyPanel.onDidDispose(() => (surveyPanel = undefined))
  surveyPanel.webview.html = surveyHtml(spec)

  surveyPanel.webview.onDidReceiveMessage((m) => {
    if (m.type !== "submit" || !surveyPanel) return
    const name = String(m.name ?? "").trim()
    const grade = String(m.grade ?? "").trim()
    const email = String(m.email ?? "").trim()
    const mc: Record<string, number> = m.mc ?? {}
    const likert: Record<string, number> = m.likert ?? {}
    const comment = String(m.comment ?? "").trim()

    // Score against the answer key HERE (never in the browser).
    const correct: Record<string, boolean> = {}
    let score = 0
    for (const q of spec.mc) {
      const ok = mc[q.id] === q.answer
      correct[q.id] = ok
      if (ok) score++
    }
    const rec: SurveyResponse = {
      ts: new Date().toISOString(),
      pipeline: pid,
      name,
      grade,
      email,
      score,
      total: spec.mc.length,
      mc,
      correct,
      likert,
      comment,
    }
    try {
      fs.mkdirSync(surveyDir(pid), { recursive: true })
      fs.appendFileSync(responsesJsonl(pid), JSON.stringify(rec) + "\n", "utf8")
      writeCsv(pid, spec, readResponses(pid))
      surveyPanel.webview.postMessage({ type: "saved", score, total: spec.mc.length })
    } catch (e: any) {
      surveyPanel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
    }
  })
}

function surveyHtml(spec: SurveySpec): string {
  const scale = spec.likertScale?.length === 5 ? spec.likertScale : DEFAULT_SCALE
  // Choices are shuffled? No — keep order stable so item analysis is comparable.
  const mcHtml = spec.mc
    .map((q, i) => {
      const opts = q.choices
        .map(
          (c, ci) =>
            `<label class="opt"><input type="radio" name="${q.id}" value="${ci}"> <span>${esc(c)}</span></label>`,
        )
        .join("")
      return `<div class="q" data-mc="${q.id}"><div class="qt"><b>${i + 1}.</b> ${esc(q.q)}</div>${opts}</div>`
    })
    .join("")
  const scaleHead = scale.map((s, i) => `<th>${i + 1}<br><span class="sc">${esc(s)}</span></th>`).join("")
  const likertHtml = spec.likert
    .map((q, i) => {
      const cells = scale
        .map((_, ci) => `<td><input type="radio" name="${q.id}" value="${ci + 1}"></td>`)
        .join("")
      return `<tr data-lk="${q.id}"><td class="lkq"><b>${spec.mc.length + i + 1}.</b> ${esc(q.q)}</td>${cells}</tr>`
    })
    .join("")

  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
  :root{color-scheme:dark}
  body{font-family:-apple-system,"Segoe UI",system-ui,sans-serif;color:#e6edf3;background:#0d1117;margin:0;padding:20px 22px;max-width:860px}
  h1{font-size:20px;margin:0 0 6px}.a{color:#2dd4bf}
  .intro{color:#9fb0bd;font-size:13px;line-height:1.6;background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:12px 14px;margin-bottom:16px}
  h2{font-size:15px;color:#7ee7d6;margin:22px 0 8px;border-left:4px solid #2dd4bf;padding-left:9px}
  .fields{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:8px}
  .field{display:flex;flex-direction:column;gap:4px}
  .field label{font-size:12px;color:#9fb0bd}
  .field input,.field select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px;font:inherit;min-width:150px}
  .q{background:#0b0f14;border:1px solid #22272e;border-radius:9px;padding:11px 13px;margin-bottom:10px}
  .qt{font-size:13.5px;line-height:1.5;margin-bottom:7px}
  .opt{display:flex;align-items:flex-start;gap:7px;font-size:13px;padding:4px 6px;border-radius:6px;cursor:pointer}
  .opt:hover{background:#161b22}
  table.likert{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}
  table.likert th,table.likert td{border:1px solid #30363d;padding:6px 5px;text-align:center;vertical-align:middle}
  table.likert td.lkq{text-align:left;line-height:1.45}
  table.likert th{background:#12312b;color:#bdeee3;font-weight:600}
  .sc{font-size:10px;color:#8b98a5;font-weight:400}
  textarea{width:100%;box-sizing:border-box;background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:8px;padding:8px;min-height:60px;font:inherit}
  .bar{position:sticky;bottom:0;background:#0d1117;padding:14px 0 4px;margin-top:16px;border-top:1px solid #22272e;display:flex;align-items:center;gap:12px}
  button#submit{background:#12312b;color:#7ee7d6;border:1px solid #1f5a4f;border-radius:8px;padding:9px 18px;font:inherit;font-weight:600;cursor:pointer}
  button#submit:hover{border-color:#2dd4bf}
  #msg{font-size:13px}
  .err{color:#ffb4b4}.ok{color:#7ee7d6}
  .done{background:#0b0f14;border:1px solid #1f5a4f;border-radius:12px;padding:26px;text-align:center;font-size:15px;line-height:1.7}
  .req{color:#ff9d9d}
</style></head><body>
  <h1>🔬 <span class="a">${esc(spec.title ?? "이해도 테스트")}</span></h1>
  <div class="intro">${esc(spec.intro ?? "")}</div>
  <div id="form">
    <h2>학생 정보</h2>
    <div class="fields">
      <div class="field"><label>이름 <span class="req">*</span></label><input id="name" type="text" placeholder="홍길동"></div>
      <div class="field"><label>학년 <span class="req">*</span></label>
        <select id="grade"><option value="">선택</option><option>고1</option><option>고2</option><option>고3</option><option>중3</option><option>기타</option></select></div>
      <div class="field"><label>이메일 <span class="req">*</span></label><input id="email" type="email" placeholder="student@example.com"></div>
    </div>
    <h2>객관식 문항 (${spec.mc.length}문항)</h2>
    ${mcHtml}
    <h2>설문 문항 (${spec.likert.length}문항)</h2>
    <table class="likert"><thead><tr><th style="text-align:left">문항</th>${scaleHead}</tr></thead><tbody>${likertHtml}</tbody></table>
    <h2>자유 의견 (선택)</h2>
    <textarea id="comment" placeholder="어려웠던 점, 좋았던 점, 더 알고 싶은 점 등을 자유롭게 적어 주세요."></textarea>
    <div class="bar"><button id="submit">제출하기</button><span id="msg"></span></div>
  </div>
  <script>
    const vscode = acquireVsCodeApi()
    const MC = ${JSON.stringify(spec.mc.map((q) => q.id))}
    const LK = ${JSON.stringify(spec.likert.map((q) => q.id))}
    const $ = (id) => document.getElementById(id)
    function val(name){ const el = document.querySelector('input[name="'+name+'"]:checked'); return el ? Number(el.value) : null }
    $('submit').onclick = () => {
      const msg = $('msg'); msg.className=''; msg.textContent=''
      const name=$('name').value.trim(), grade=$('grade').value.trim(), email=$('email').value.trim()
      if(!name||!grade||!email){ msg.className='err'; msg.textContent='이름·학년·이메일을 모두 입력해 주세요.'; return }
      if(!/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)){ msg.className='err'; msg.textContent='이메일 형식을 확인해 주세요.'; return }
      const mc={}; let answered=0
      MC.forEach(id=>{ const v=val(id); mc[id]= v==null? -1 : v; if(v!=null) answered++ })
      const likert={}; let lkAns=0
      LK.forEach(id=>{ const v=val(id); if(v!=null){ likert[id]=v; lkAns++ } })
      if(answered < MC.length || lkAns < LK.length){
        if(!confirm('아직 답하지 않은 문항이 있습니다. 그래도 제출할까요?')) return
      }
      $('submit').disabled=true; msg.className='ok'; msg.textContent='제출 중…'
      vscode.postMessage({ type:'submit', name, grade, email, mc, likert, comment:$('comment').value.trim() })
    }
    window.addEventListener('message', ev=>{
      const m=ev.data
      if(m.type==='saved'){
        $('form').outerHTML = '<div class="done">✅ 제출이 완료되었습니다. 참여해 주셔서 감사합니다!<br><br>'
          + '이번 객관식 점수: <b style="color:#7ee7d6">'+m.score+' / '+m.total+'</b><br>'
          + '<span style="font-size:13px;color:#9fb0bd">결과는 연구용 통계로만 활용됩니다.</span></div>'
      } else if(m.type==='saveError'){
        $('submit').disabled=false; const msg=$('msg'); msg.className='err'; msg.textContent='저장 실패: '+m.msg
      }
    })
  </script>
</body></html>`
}

// ---------------------------------------------------------------------------
// Statistics view
// ---------------------------------------------------------------------------
export function openSurveyStats(context: vscode.ExtensionContext, pipelineId?: string) {
  const resolved = resolvePipeline(context, pipelineId)
  if (!resolved) {
    vscode.window.showErrorMessage("GHBIO: no pipeline found for the survey stats.")
    return
  }
  const spec = loadSurvey(resolved.pipeline.dir)
  if (!spec) {
    vscode.window.showErrorMessage("GHBIO: 이 파이프라인에는 설문(survey.json)이 없습니다.")
    return
  }
  const pid = resolved.pipeline.id
  const rows = readResponses(pid)

  if (statsPanel) {
    statsPanel.reveal()
  } else {
    statsPanel = vscode.window.createWebviewPanel("ghbioSurveyStats", "이해도 테스트 · 결과 통계", vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    statsPanel.onDidDispose(() => (statsPanel = undefined))
    statsPanel.webview.onDidReceiveMessage((m) => {
      if (m?.type === "openCsv") vscode.commands.executeCommand("vscode.open", vscode.Uri.file(responsesCsv(pid)))
    })
  }
  statsPanel.webview.html = statsHtml(spec, rows, responsesCsv(pid))
}

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
}
function stddev(xs: number[]): number {
  if (xs.length < 2) return 0
  const m = mean(xs)
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1))
}
function median(xs: number[]): number {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}
function bar(fracRaw: number, label: string): string {
  const frac = Math.max(0, Math.min(1, fracRaw))
  const pct = (frac * 100).toFixed(0)
  return `<div class="brow"><div class="blab">${label}</div><div class="btrack"><div class="bfill" style="width:${
    frac * 100
  }%"></div></div><div class="bval">${pct}%</div></div>`
}

function statsHtml(spec: SurveySpec, rows: SurveyResponse[], csvPath: string): string {
  const n = rows.length
  const scale = spec.likertScale?.length === 5 ? spec.likertScale : DEFAULT_SCALE

  if (n === 0) {
    return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><style>
      body{font-family:system-ui,sans-serif;color:#e6edf3;background:#0d1117;padding:40px;text-align:center}
      .a{color:#2dd4bf}</style></head><body>
      <h1>📊 이해도 테스트 <span class="a">결과 통계</span></h1>
      <p style="color:#9fb0bd">아직 제출된 응답이 없습니다. '이해도 테스트' 버튼으로 설문을 먼저 진행해 주세요.</p>
      </body></html>`
  }

  const scores = rows.map((r) => r.score)
  const total = spec.mc.length
  const scMean = mean(scores)
  const scSd = stddev(scores)
  const scMed = median(scores)
  const pct = (scMean / total) * 100

  // Score distribution histogram (per-point buckets 0..total).
  const hist = new Array(total + 1).fill(0)
  scores.forEach((s) => hist[s]++)
  const maxHist = Math.max(...hist, 1)
  const histHtml = hist
    .map((c, s) => {
      const h = (c / maxHist) * 100
      return `<div class="hcol"><div class="hbarwrap"><div class="hbar" style="height:${h}%" title="${c}명"></div></div><div class="hx">${s}</div><div class="hn">${
        c || ""
      }</div></div>`
    })
    .join("")

  // Item difficulty: correct rate per MC question (low = hard).
  const itemHtml = spec.mc
    .map((q, i) => {
      const answered = rows.filter((r) => (r.mc[q.id] ?? -1) >= 0).length
      const nCorrect = rows.filter((r) => r.correct[q.id]).length
      const rate = n ? nCorrect / n : 0
      const cls = rate < 0.5 ? "hard" : rate < 0.75 ? "mid" : "easy"
      return `<tr class="${cls}"><td>${i + 1}</td><td class="ql">${esc(q.q)}</td><td>${nCorrect}/${n}</td><td>${(
        rate * 100
      ).toFixed(0)}%</td><td>${answered}</td></tr>`
    })
    .join("")

  // Likert item means + distribution.
  const likertHtml = spec.likert
    .map((q, i) => {
      const vals = rows.map((r) => r.likert[q.id]).filter((v): v is number => typeof v === "number" && v >= 1 && v <= 5)
      const m = mean(vals)
      const dist = [1, 2, 3, 4, 5].map((k) => vals.filter((v) => v === k).length)
      const distStr = dist.map((c, k) => `${k + 1}점:${c}`).join(" · ")
      return `<tr><td>${spec.mc.length + i + 1}</td><td class="ql">${esc(q.q)}</td><td><b>${m.toFixed(
        2,
      )}</b> / 5</td><td>${vals.length}</td><td class="dist">${distStr}</td></tr>`
    })
    .join("")

  // By-grade breakdown.
  const grades = Array.from(new Set(rows.map((r) => r.grade || "미기입")))
  const gradeHtml = grades
    .map((g) => {
      const sub = rows.filter((r) => (r.grade || "미기입") === g)
      const gm = mean(sub.map((r) => r.score))
      return `<tr><td>${esc(g)}</td><td>${sub.length}</td><td>${gm.toFixed(1)} / ${total}</td><td>${(
        (gm / total) *
        100
      ).toFixed(0)}%</td></tr>`
    })
    .join("")

  const scaleLegend = scale.map((s, i) => `${i + 1}=${esc(s)}`).join(" · ")

  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
  body{font-family:-apple-system,"Segoe UI",system-ui,sans-serif;color:#e6edf3;background:#0d1117;margin:0;padding:20px 24px;max-width:960px}
  h1{font-size:20px;margin:0 0 4px}.a{color:#2dd4bf}
  h2{font-size:15px;color:#7ee7d6;margin:24px 0 10px;border-left:4px solid #2dd4bf;padding-left:9px}
  .cards{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0}
  .card{background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:12px 16px;min-width:130px}
  .card .big{font-size:24px;font-weight:700;color:#7ee7d6}
  .card .lab{font-size:12px;color:#9fb0bd;margin-top:2px}
  table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}
  th,td{border:1px solid #30363d;padding:6px 8px;text-align:center;vertical-align:middle}
  th{background:#12312b;color:#bdeee3}
  td.ql{text-align:left;line-height:1.4;max-width:420px}
  td.dist{text-align:left;color:#9fb0bd;font-size:11.5px}
  tr.hard td{background:#3a1a1a}tr.mid td{background:#332a12}tr.easy td{background:#0e2620}
  .hist{display:flex;align-items:flex-end;gap:4px;height:140px;padding:6px 4px;background:#0b0f14;border:1px solid #30363d;border-radius:10px;overflow-x:auto}
  .hcol{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:26px;flex:1}
  .hbarwrap{height:100px;display:flex;align-items:flex-end;width:70%}
  .hbar{width:100%;background:linear-gradient(180deg,#2dd4bf,#0d9488);border-radius:4px 4px 0 0;min-height:2px}
  .hx{font-size:10.5px;color:#9fb0bd;margin-top:3px}.hn{font-size:10px;color:#7ee7d6}
  .legend{font-size:11.5px;color:#8b98a5;margin:6px 0}
  .foot{margin-top:22px;font-size:12px;color:#8b98a5;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
  button:hover{border-color:#2dd4bf}
  code{background:#161b22;padding:1px 5px;border-radius:4px;font-size:11.5px}
</style></head><body>
  <h1>📊 이해도 테스트 <span class="a">결과 통계</span> · N=${n}</h1>
  <div class="cards">
    <div class="card"><div class="big">${n}</div><div class="lab">응답자 수</div></div>
    <div class="card"><div class="big">${scMean.toFixed(1)}</div><div class="lab">평균 점수 / ${total}</div></div>
    <div class="card"><div class="big">${pct.toFixed(0)}%</div><div class="lab">평균 정답률</div></div>
    <div class="card"><div class="big">${scMed}</div><div class="lab">중앙값</div></div>
    <div class="card"><div class="big">±${scSd.toFixed(1)}</div><div class="lab">표준편차(SD)</div></div>
  </div>

  <h2>점수 분포 (0 – ${total})</h2>
  <div class="hist">${histHtml}</div>

  <h2>문항별 정답률 (문항 난이도)</h2>
  <p class="legend">낮을수록 어려운 문항입니다. <span style="color:#ff9d9d">■</span> &lt;50% · <span style="color:#e2b341">■</span> 50–75% · <span style="color:#5fd0b6">■</span> ≥75%</p>
  <table><thead><tr><th>#</th><th>문항</th><th>정답 수</th><th>정답률</th><th>응답 수</th></tr></thead><tbody>${itemHtml}</tbody></table>

  <h2>설문(Likert) 문항 평균</h2>
  <p class="legend">${scaleLegend}</p>
  <table><thead><tr><th>#</th><th>문항</th><th>평균</th><th>응답 수</th><th>분포</th></tr></thead><tbody>${likertHtml}</tbody></table>

  <h2>학년별 요약</h2>
  <table><thead><tr><th>학년</th><th>응답자</th><th>평균 점수</th><th>정답률</th></tr></thead><tbody>${gradeHtml}</tbody></table>

  <div class="foot">
    <button id="csv">📄 원자료 CSV 열기</button>
    <span>원자료(백엔드 테이블): <code>${esc(csvPath)}</code> · JSONL 원본도 같은 폴더에 있습니다.</span>
  </div>
  <script>
    const vscode = acquireVsCodeApi()
    document.getElementById('csv').onclick = () => vscode.postMessage({type:'openCsv'})
  </script>
</body></html>`
}
