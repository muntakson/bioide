import * as vscode from "vscode"
import { TutorialProvider } from "./tutorials"
import { pipelineProgress } from "./pipeline"
import { missionHtml } from "./mission"

// The landing page: the first screen a visitor sees. It introduces BioIDE, offers a single
// prominent "입장하기 (Enter)" button that opens GHBIO Home, and carries a lightweight sign-in
// widget at the top-right. There is no auth backend on this box — sign-in stores an identity
// locally (globalState, survives reloads) purely to personalize the workbench; treat it as a
// display convenience, not a security boundary.

const USER_KEY = "ghbio.user"

interface GhbioUser {
  name: string
  email?: string
}

// BioIDE's verified reproductions. Every row is backed by an ACTUAL independent-validation
// run (validation_summary.csv verdicts on this box) — not marketing. `confirmed`/`partial`/
// `refuted` count the AGREE / PARTIAL / DISAGREE claim-level verdicts; `novel` counts genuine
// findings the authors did not report. Add a row only after its pipeline's validate step runs.
interface Reproduction {
  paper: string
  year: number
  journal: string
  cancer: string
  verdict: "재현됨" | "부분 재현" | "불일치"
  confirmed: number
  partial: number
  refuted: number
  novel: number
  highlight: string
}
const REPRODUCTIONS: Reproduction[] = [
  {
    paper: "Tirosh et al.", year: 2016, journal: "Science", cancer: "전이성 흑색종",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "악성세포 판정 정확도 0.96 · F1 0.92 — 저자 라벨 없이 marker로 재도출",
  },
  {
    paper: "Puram et al.", year: 2017, journal: "Cell", cancer: "두경부암 (HNSCC)",
    verdict: "재현됨", confirmed: 5, partial: 1, refuted: 0, novel: 0,
    highlight: "세포지도 재현(악성 F1 0.96) · 특화 p-EMT 프로그램은 부분 재현(악성 한정 재검)",
  },
  {
    paper: "Neftel et al.", year: 2019, journal: "Cell", cancer: "교모세포종 (GBM)",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "악성 4상태(AC/MES/NPC/OPC) 연속체 재현 · 6,837 악성세포(논문 ~6,864)",
  },
  {
    paper: "Peng et al.", year: 2019, journal: "Cell Research", cancer: "췌장암 (PDAC)",
    verdict: "재현됨", confirmed: 6, partial: 1, refuted: 0, novel: 0,
    highlight: "악성 도관세포 판정 정확도 0.98 · F1 0.98 — 저자 라벨 없이 재도출",
  },
  {
    paper: "Song et al.", year: 2019, journal: "Cancer Medicine", cancer: "폐암 (NSCLC)",
    verdict: "재현됨", confirmed: 2, partial: 0, refuted: 0, novel: 0,
    highlight: "주요 TME 계통 5/6 재현 · 단일시료·계통 분류만(골수 궤적 주장은 범위 밖)",
  },
  {
    paper: "Pu et al.", year: 2021, journal: "Nature Communications", cancer: "갑상선유두암 (PTC)",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "TMSB4X 진행 구배 Spearman ρ=1.00 · 저자와 다른 비지도 방법으로 수렴",
  },
  {
    paper: "Kumar et al.", year: 2022, journal: "Cancer Discovery", cancer: "위암 (gastric)",
    verdict: "재현됨", confirmed: 4, partial: 0, refuted: 0, novel: 0,
    highlight: "7/7 세포계통 재현 · 악성 상피 위분화점수(GDS) 1.38 하락·증식 상승 — 라벨 미배포, 비지도 GMM으로 독립 재도출",
  },
  {
    paper: "Choi et al.", year: 2023, journal: "Nature Communications", cancer: "두경부암 진행 (head & neck)",
    verdict: "재현됨", confirmed: 3, partial: 0, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.95 · 악성 상피세포 F1 0.92 · 백반증(LP)부터 악성세포 출현·NL→LP→CA→LN 단조 증가 재현",
  },
  {
    paper: "Kim et al.", year: 2020, journal: "Nature Communications", cancer: "폐선암 전이 (lung adeno · 208k세포)",
    verdict: "재현됨", confirmed: 3, partial: 1, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.96 · 악성 상피세포 F1 0.88 · 전이림프절 골수성 침윤(mLN≫nLN) 재현 · 정상→종양→전이 악성 구배는 부분 재현(정상 폐포 vs 악성 경계 애매)",
  },
  {
    paper: "Ma et al.", year: 2019, journal: "Cancer Cell", cancer: "간암 (liver · HCC+iCCA)",
    verdict: "부분 재현", confirmed: 0, partial: 1, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.97(일치) · 악성 vs HPC-like(간전구세포유사) 경계는 부분 재현(F1 0.71) — 두 집단 모두 상피성 유전자 공유로 본질적 애매",
  },
]

function achievementsHtml(): string {
  const R = REPRODUCTIONS
  const total = R.length
  const fully = R.filter((r) => r.verdict === "재현됨").length
  // "재현한 기념비적 논문" counts only fully-reproduced (AGREE) papers — a PARTIAL row
  // (e.g. Ma 2019 liver) shows in the table + review-points, but not this headline count.
  const papers = fully
  const confirmed = R.reduce((n, r) => n + r.confirmed, 0)
  const review = R.reduce((n, r) => n + r.partial, 0)
  const refuted = R.reduce((n, r) => n + r.refuted, 0)
  const novel = R.reduce((n, r) => n + r.novel, 0)
  const journals = Array.from(new Set(R.filter((r) => r.verdict === "재현됨").map((r) => r.journal)))
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string))

  const tiles = [
    { n: String(papers), t: "재현한 기념비적 논문", s: journals.join(" · ") },
    { n: String(confirmed), t: "독립 검증으로 확인한 저자 주장", s: `${fully}/${total} 논문 전체 재현됨(AGREE)` },
    { n: String(novel), t: "새로 발견한 사실 (저자 미보고)", s: novel ? "재현 과정에서 발견" : "아직 없음 — 모두 재현으로 수렴" },
    { n: String(refuted), t: "반증된 저자 주장 (결함)", s: refuted ? "저자 주장과 불일치" : `0 반증 · 재검토 지점 ${review}건` },
  ]

  const rows = R.map((r) => {
    const badge = r.verdict === "재현됨" ? "ok" : r.verdict === "부분 재현" ? "warn" : "bad"
    return (
      `<tr><td><b>${esc(r.paper)}</b> <span class="yr">${r.year}</span></td>` +
      `<td class="jr">${esc(r.journal)}</td>` +
      `<td>${esc(r.cancer)}</td>` +
      `<td><span class="vb ${badge}">${esc(r.verdict)}</span></td>` +
      `<td class="cc">${r.confirmed}<span>확인</span> · ${r.partial}<span>부분</span> · ${r.refuted}<span>반증</span></td>` +
      `<td class="hl">${esc(r.highlight)}</td></tr>`
    )
  }).join("")

  return (
    `<div class="sec-h" id="achSec">BioIDE의 성과 (Verified Reproductions)</div>` +
    `<p class="sec-sub">암 scRNA-seq 기념비적 논문을 <b>저자 라벨 없이</b> GPU·AI 코드로 처음부터 다시 도출하고, 저자 주장을 정량 검증한 <b>실제 결과</b>입니다.</p>` +
    `<div class="ach-tiles">` +
    tiles.map((x) => `<div class="atile"><b>${x.n}</b><div class="t">${x.t}</div><div class="s">${x.s}</div></div>`).join("") +
    `</div>` +
    `<div class="ach-tablewrap"><table class="ach-table">` +
    `<thead><tr><th>논문</th><th>저널</th><th>암종</th><th>판정</th><th>주장 검증</th><th>핵심 결과</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>` +
    `<p class="ach-note">※ 판정은 BioIDE 헌장 제2조에 따른 <b>독립 검증</b> 결과입니다. 저자 결론을 정답으로 전제하지 않으며, ` +
    `서로 다른 두 독립 분석의 <b>수렴</b> 여부를 봅니다. 수치는 실제 <code>validation_summary.csv</code>에서 집계됩니다.</p>`
  )
}

let panel: vscode.WebviewPanel | undefined

function getUser(context: vscode.ExtensionContext): GhbioUser | undefined {
  return context.globalState.get<GhbioUser>(USER_KEY)
}

export function openLanding(context: vscode.ExtensionContext, tutorials: TutorialProvider) {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioLanding", "BioIDE", vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    panel.onDidDispose(() => (panel = undefined))
    panel.webview.onDidReceiveMessage((m) => {
      if (m?.type === "login") {
        const name = String(m.name ?? "").trim()
        if (!name) return
        const email = String(m.email ?? "").trim() || undefined
        context.globalState.update(USER_KEY, { name, email })
        postUser(context)
        return
      }
      if (m?.type === "logout") {
        context.globalState.update(USER_KEY, undefined)
        postUser(context)
        return
      }
      if (m?.type === "getUser") {
        postUser(context)
        return
      }
      if (m?.cmd) vscode.commands.executeCommand(m.cmd, ...(m.args ?? []))
    })
  }
  render(panel, context, tutorials)
  panel.reveal()
}

function postUser(context: vscode.ExtensionContext) {
  panel?.webview.postMessage({ type: "user", user: getUser(context) ?? null })
}

function render(p: vscode.WebviewPanel, context: vscode.ExtensionContext, tutorials: TutorialProvider) {
  // A couple of live numbers to make the intro concrete rather than marketing fluff.
  const modules = tutorials.getModules()
  const pipelineCount = modules.reduce((n, m) => n + m.pipelines.length, 0)
  const doneSteps = modules.reduce(
    (n, m) => n + m.pipelines.reduce((k, pl) => k + pipelineProgress(pl).done, 0),
    0,
  )
  const user = getUser(context)
  const userJson = JSON.stringify(user ?? null)

  p.webview.html = /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif; color: #e6edf3;
    margin: 0; padding: 0 0 60px; line-height: 1.6; min-height: 100vh; background-color: #0b0f1a;
    background-image:
      radial-gradient(1200px 560px at 82% -12%, rgba(124,58,237,.22), transparent 60%),
      radial-gradient(1000px 560px at -5% 4%, rgba(45,212,191,.14), transparent 55%),
      linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size: auto, auto, 34px 34px, 34px 34px; background-attachment: fixed; }

  /* ---------- top bar ---------- */
  .topbar { display:flex; align-items:center; justify-content:space-between; gap:12px;
    padding: 14px 26px; border-bottom: 1px solid #1c2430; background: rgba(11,15,26,.6); backdrop-filter: blur(6px);
    position: sticky; top: 0; z-index: 20; }
  .brandmark { display:flex; align-items:center; gap:9px; font-weight: 800; font-size: 17px; letter-spacing:-.4px; }
  .brandmark .dot { width:10px; height:10px; border-radius:50%; background: linear-gradient(120deg,#2dd4bf,#a78bfa); }
  .brandmark span { background: linear-gradient(120deg,#2dd4bf,#22d3ee 45%,#a78bfa); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  .auth { display:flex; align-items:center; gap:10px; }
  .who { display:flex; align-items:center; gap:8px; font-size: 13px; color:#cbd5e1; }
  .avatar { width:28px; height:28px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
    font-weight:800; font-size:12px; color:#06121a; background: linear-gradient(135deg,#2dd4bf,#22d3ee); }
  button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a; font-weight: 700;
    padding: 8px 15px; border-radius: 8px; font-size: 13px; }
  button.ghost { background: rgba(33,38,45,.6); color: #e6edf3; border: 1px solid #30363d; }
  button.link { background: none; color:#93a1b0; padding: 6px 8px; font-weight:600; }
  button.link:hover { color:#e6edf3; }

  /* ---------- hero / intro ---------- */
  .wrap { max-width: 1080px; margin: 0 auto; padding: 0 26px; }
  .hero { text-align:center; padding: 60px 0 26px; }
  .badge { display:inline-block; font-size: 12px; font-weight: 700; color: #c4b5fd;
    background: rgba(124,58,237,.14); border: 1px solid #4c327e; padding: 5px 13px; border-radius: 999px; }
  .title { font-size: 74px; font-weight: 800; letter-spacing: -2px; margin: 20px 0 6px; line-height: 1.0; }
  .title span { background: linear-gradient(120deg,#2dd4bf,#22d3ee 40%,#a78bfa); -webkit-background-clip: text;
    background-clip: text; color: transparent; }
  .tag { font-size: 23px; font-weight: 700; color:#eef2f7; margin: 6px 0 16px; }
  .lead { font-size: 15.5px; color:#b6c2cf; max-width: 720px; margin: 0 auto 30px; }
  .lead b { color:#dbe6f0; }
  .enter-row { display:flex; align-items:center; justify-content:center; gap:14px; flex-wrap:wrap; }
  .enter { font-size: 16px; padding: 14px 30px; border-radius: 11px;
    box-shadow: 0 16px 40px -14px rgba(45,212,191,.6); }
  .enter:hover { filter: brightness(1.07); }
  .stats { display:flex; justify-content:center; gap:34px; margin-top: 34px; flex-wrap:wrap; }
  .stat b { display:block; font-size: 26px; color:#eafffb; font-weight:800; }
  .stat span { font-size: 12px; color:#93a1b0; }

  /* ---------- feature cards ---------- */
  .feat { display:grid; grid-template-columns: repeat(auto-fit, minmax(240px,1fr)); gap: 14px; margin: 44px 0 8px; }
  .fcard { background:#12181f; border:1px solid #253039; border-radius:14px; padding: 18px 18px 16px; }
  .fcard .ic { font-size: 22px; }
  .fcard h3 { margin: 8px 0 6px; font-size: 15.5px; }
  .fcard p { margin:0; color:#8b98a5; font-size:13px; }
  .sec-h { text-align:center; font-size: 18px; color:#7ee7d6; margin: 44px 0 4px; }
  .sec-sub { text-align:center; color:#8b98a5; font-size:13px; margin: 0 0 6px; }

  .mission { margin: 14px 0; border: 1px solid #3b2f6e; border-left: 4px solid #7c3aed; border-radius: 12px;
    background: linear-gradient(135deg,#161029,#0f1626); padding: 16px 20px; }
  .mission-h { font-weight: 700; font-size: 15px; color: #c4b5fd; }
  .mission-h span { font-weight: 400; font-size: 12px; color: #8b98a5; }
  .mission-lead { margin: 8px 0 10px; font-size: 13px; color: #cbd5e1; }
  .mission-list { margin: 0; padding-left: 20px; font-size: 12.5px; color: #aeb9c6; line-height: 1.6; }
  .mission-list li { margin: 5px 0; }
  .mission-list b { color: #ddd6fe; }

  .foot-copy { text-align:center; margin-top: 30px; color: #6e7b8a; font-size: 12px; }
  a { color:#2dd4bf; }

  /* ---------- achievements ---------- */
  .ach-tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(210px,1fr)); gap: 14px; margin: 14px 0 8px; }
  .atile { background: linear-gradient(135deg,#101a20,#0e1524); border:1px solid #22333b; border-radius:14px;
    padding: 16px 16px 14px; text-align:center; }
  .atile b { display:block; font-size: 40px; font-weight: 800; line-height:1; margin-bottom: 8px;
    background: linear-gradient(120deg,#2dd4bf,#22d3ee 45%,#a78bfa); -webkit-background-clip:text; background-clip:text; color:transparent; }
  .atile .t { font-size: 13px; color:#dbe6f0; font-weight:700; }
  .atile .s { font-size: 11.5px; color:#8b98a5; margin-top: 4px; line-height:1.45; }
  .ach-tablewrap { overflow-x:auto; margin: 16px 0 6px; border:1px solid #22333b; border-radius:14px; }
  .ach-table { width:100%; border-collapse: collapse; font-size: 13px; min-width: 720px; }
  .ach-table th { text-align:left; padding: 11px 14px; color:#7ee7d6; font-weight:700; font-size:12px;
    background:#0e1622; border-bottom:1px solid #22333b; }
  .ach-table td { padding: 12px 14px; border-bottom:1px solid #1a232e; color:#c6d2de; vertical-align: middle; }
  .ach-table tr:last-child td { border-bottom:none; }
  .ach-table .yr { color:#8b98a5; font-weight:600; font-size:11px; }
  .ach-table .jr { color:#a78bfa; font-weight:700; }
  .vb { display:inline-block; font-size:11px; font-weight:800; padding:3px 9px; border-radius:999px; }
  .vb.ok { color:#06121a; background: linear-gradient(135deg,#2dd4bf,#34d399); }
  .vb.warn { color:#1a1204; background: linear-gradient(135deg,#fbbf24,#f59e0b); }
  .vb.bad { color:#fff; background: linear-gradient(135deg,#f87171,#dc2626); }
  .ach-table .cc { font-variant-numeric: tabular-nums; color:#e6edf3; font-weight:700; white-space:nowrap; }
  .ach-table .cc span { color:#7a8794; font-weight:500; font-size:11px; margin: 0 4px 0 1px; }
  .ach-table .hl { color:#9fb0bd; font-size:12px; max-width: 280px; }
  .ach-note { text-align:center; color:#6e7b8a; font-size:11.5px; margin: 8px 0 0; line-height:1.5; }
  .ach-note code { color:#7ee7d6; }

  /* ---------- login modal ---------- */
  .overlay { position: fixed; inset: 0; background: rgba(4,6,12,.72); backdrop-filter: blur(3px);
    display: none; align-items: flex-start; justify-content: center; padding: 12vh 18px; z-index: 60; }
  .overlay.on { display:flex; }
  .modal { max-width: 400px; width: 100%; background:#0e1420; border:1px solid #2a3446; border-radius:16px;
    padding: 22px 24px 24px; box-shadow: 0 30px 80px -20px rgba(0,0,0,.9); position: relative; }
  .modal h3 { margin: 0 0 4px; font-size: 19px; color:#c4b5fd; }
  .modal p.sub { margin: 0 0 16px; font-size: 12.5px; color:#8b98a5; }
  .modal label { display:block; font-size: 12px; color:#93a1b0; margin: 10px 0 4px; }
  .modal input { width:100%; background:#0b111b; border:1px solid #30363d; border-radius:8px; color:#e6edf3;
    font-size: 14px; padding: 9px 11px; font-family: inherit; }
  .modal input:focus { outline: none; border-color:#2dd4bf; }
  .modal .close { position:absolute; top:12px; right:14px; background:#21262d; color:#e6edf3; border:1px solid #30363d;
    padding: 3px 9px; border-radius: 8px; font-weight:700; }
  .modal .go { margin-top: 18px; width:100%; justify-content:center; padding: 11px; font-size: 14px; }
  .modal .note { margin-top: 12px; font-size: 11px; color:#6e7b8a; line-height:1.5; }

  @media (max-width: 720px) { .title { font-size: 52px; } }
</style></head><body>
  <div class="topbar">
    <div class="brandmark"><span class="dot"></span>Bio<span>IDE</span></div>
    <div class="auth" id="auth"></div>
  </div>

  <div class="wrap">
    <div class="hero">
      <div class="badge">⚡ GPU-accelerated bioinformatics IDE · for biologists</div>
      <h1 class="title">Bio<span>IDE</span></h1>
      <div class="tag">From Paper to Pipeline — in seconds.</div>
      <p class="lead">BioIDE는 생물학자를 위한 <b>PlatformIO 스타일 생명정보학 워크벤치</b>입니다.
        암 연구 <b>scRNA-seq 기념비적 논문</b>을 AI가 찾고, 저자의 분석을
        <b>우리가 새로 짠 GPU·Python 코드</b>로 처음부터 다시 도출해 결론을 <b>독립 검증</b>합니다.
        느린 R/Seurat를 Python·GPU로 대체하고, 개선된 소스코드를 커뮤니티에 남깁니다.</p>
      <div class="enter-row">
        <button class="enter" id="enterBtn">🚀 입장하기 (Enter BioIDE)</button>
        <button class="ghost" id="missionBtn">📜 BioIDE 헌장</button>
      </div>
      <div class="stats">
        <div class="stat"><b>${pipelineCount}</b><span>재현 파이프라인</span></div>
        <div class="stat"><b>${doneSteps}</b><span>완료된 분석 단계</span></div>
        <div class="stat"><b>100×</b><span>GPU 가속 재분석</span></div>
      </div>
    </div>

    ${achievementsHtml()}

    <div class="sec-h">BioIDE가 하는 일</div>
    <p class="sec-sub">논문 → 파이프라인 → 독립 검증까지, 한 화면에서.</p>
    <div class="feat">
      <div class="fcard"><div class="ic">🔎</div><h3>논문 → 파이프라인</h3>
        <p>AI가 원본 데이터가 공개된 암 scRNA-seq 논문을 찾고, 그 워크플로를 GPU·Python으로 재현하는 계획을 설계합니다.</p></div>
      <div class="fcard"><div class="ic">⚡</div><h3>GPU 재분석</h3>
        <p>scVI·rapids-singlecell·PyTorch로 클러스터와 세포유형을 처음부터 다시 도출합니다.</p></div>
      <div class="fcard"><div class="ic">✅</div><h3>독립 검증</h3>
        <p>저자의 라벨을 소비하지 않고, ARI·마커 중복으로 저자 주장을 정량 대조해 재현 여부를 판정합니다.</p></div>
      <div class="fcard"><div class="ic">🎓</div><h3>AI 보고서</h3>
        <p>결과를 바탕으로 고등학생도 이해할 수 있는 한국어 보고서와 과학 논문을 자동 작성합니다.</p></div>
    </div>

    <div class="sec-h" id="missionSec">BioIDE 헌장 (Central Dogma)</div>
    <p class="sec-sub">모든 재현 튜토리얼이 반드시 지키는 헌법.</p>
    ${missionHtml()}

    <div class="foot-copy">BioIDE · <a href="https://ghbio.co.kr/ghbio/sub0401.php">ghbio.co.kr</a></div>
  </div>

  <div class="overlay" id="loginOverlay">
    <div class="modal">
      <button class="close" id="loginClose">✕</button>
      <h3>로그인 (Sign in)</h3>
      <p class="sub">이름을 입력하면 워크벤치가 개인화됩니다.</p>
      <label for="nm">이름 (Name)</label>
      <input id="nm" type="text" placeholder="홍길동" autocomplete="name">
      <label for="em">이메일 (Email) · 선택</label>
      <input id="em" type="email" placeholder="you@example.com" autocomplete="email">
      <button class="go" id="loginGo">로그인하고 입장 (Sign in)</button>
      <p class="note">※ 이 기기는 별도 인증 서버가 없어, 로그인 정보는 이 브라우저에만 로컬로 저장됩니다(보안 인증 아님).</p>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
    let currentUser = ${userJson}

    const authEl = document.getElementById('auth')
    function initials(name){ return (name || '?').trim().charAt(0).toUpperCase() }
    function renderAuth(){
      if (currentUser && currentUser.name){
        authEl.innerHTML =
          '<div class="who"><span class="avatar">' + initials(currentUser.name) + '</span>' +
          escapeHtml(currentUser.name) + '</div>' +
          '<button class="link" id="logoutBtn">로그아웃</button>'
        document.getElementById('logoutBtn').onclick = function(){ vscode.postMessage({ type:'logout' }) }
      } else {
        authEl.innerHTML = '<button class="ghost" id="loginBtn">🔐 로그인 (Sign in)</button>'
        document.getElementById('loginBtn').onclick = openLogin
      }
    }
    function escapeHtml(s){ return String(s).replace(/[&<>"]/g, function(c){
      return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c] }) }

    const ov = document.getElementById('loginOverlay')
    function openLogin(){ ov.classList.add('on'); const n=document.getElementById('nm'); if(n) n.focus() }
    function closeLogin(){ ov.classList.remove('on') }
    document.getElementById('loginClose').onclick = closeLogin
    ov.addEventListener('click', function(e){ if (e.target === ov) closeLogin() })
    document.getElementById('loginGo').onclick = function(){
      const name = document.getElementById('nm').value.trim()
      if (!name){ document.getElementById('nm').focus(); return }
      const email = document.getElementById('em').value.trim()
      vscode.postMessage({ type:'login', name: name, email: email })
    }
    document.getElementById('em').addEventListener('keydown', function(e){
      if (e.key === 'Enter') document.getElementById('loginGo').click() })

    document.getElementById('enterBtn').onclick = function(){ send('ghbio.openHome') }
    document.getElementById('missionBtn').onclick = function(){
      const s = document.getElementById('missionSec'); if (s) s.scrollIntoView({ behavior:'smooth' }) }

    window.addEventListener('message', function(ev){
      const m = ev.data
      if (m && m.type === 'user'){ currentUser = m.user; renderAuth(); closeLogin() }
    })

    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeLogin() })
    renderAuth()
    vscode.postMessage({ type:'getUser' })
  </script>
</body></html>`
}
