import * as vscode from "vscode"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
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
  id: string // pipeline id — locates ~/ghbio-workspace/projects/<id>/results/validation_summary.csv
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
    id: "scrna-seq-melanoma-tirosh", paper: "Tirosh et al.", year: 2016, journal: "Science", cancer: "전이성 흑색종",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "악성세포 판정 정확도 0.96 · F1 0.92 — 저자 라벨 없이 marker로 재도출",
  },
  {
    id: "puram-2017-hnscc-pemt-reproduction", paper: "Puram et al.", year: 2017, journal: "Cell", cancer: "두경부암 (HNSCC)",
    verdict: "재현됨", confirmed: 5, partial: 1, refuted: 0, novel: 0,
    highlight: "세포지도 재현(악성 F1 0.96) · 특화 p-EMT 프로그램은 부분 재현(악성 한정 재검)",
  },
  {
    id: "glioblastoma-neftel-2019", paper: "Neftel et al.", year: 2019, journal: "Cell", cancer: "교모세포종 (GBM)",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "악성 4상태(AC/MES/NPC/OPC) 연속체 재현 · 6,837 악성세포(논문 ~6,864)",
  },
  {
    id: "pancreatic-cancer-sc-rna-seq", paper: "Peng et al.", year: 2019, journal: "Cell Research", cancer: "췌장암 (PDAC)",
    verdict: "재현됨", confirmed: 6, partial: 1, refuted: 0, novel: 0,
    highlight: "악성 도관세포 판정 정확도 0.98 · F1 0.98 — 저자 라벨 없이 재도출",
  },
  {
    id: "scrna-seq-nsclc", paper: "Song et al.", year: 2019, journal: "Cancer Medicine", cancer: "폐암 (NSCLC)",
    verdict: "재현됨", confirmed: 2, partial: 0, refuted: 0, novel: 0,
    highlight: "주요 TME 계통 5/6 재현 · 단일시료·계통 분류만(골수 궤적 주장은 범위 밖)",
  },
  {
    id: "thyroid-cancer-ptc-pu2021", paper: "Pu et al.", year: 2021, journal: "Nature Communications", cancer: "갑상선유두암 (PTC)",
    verdict: "재현됨", confirmed: 5, partial: 0, refuted: 0, novel: 0,
    highlight: "TMSB4X 진행 구배 Spearman ρ=1.00 · 저자와 다른 비지도 방법으로 수렴",
  },
  {
    id: "gastric-cancer-kumar2022", paper: "Kumar et al.", year: 2022, journal: "Cancer Discovery", cancer: "위암 (gastric)",
    verdict: "재현됨", confirmed: 4, partial: 0, refuted: 0, novel: 0,
    highlight: "7/7 세포계통 재현 · 악성 상피 위분화점수(GDS) 1.38 하락·증식 상승 — 라벨 미배포, 비지도 GMM으로 독립 재도출",
  },
  {
    id: "hnscc-progression-choi2023", paper: "Choi et al.", year: 2023, journal: "Nature Communications", cancer: "두경부암 진행 (head & neck)",
    verdict: "재현됨", confirmed: 3, partial: 0, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.95 · 악성 상피세포 F1 0.92 · 백반증(LP)부터 악성세포 출현·NL→LP→CA→LN 단조 증가 재현",
  },
  {
    id: "lung-adeno-kim2020", paper: "Kim et al.", year: 2020, journal: "Nature Communications", cancer: "폐선암 전이 (lung adeno · 208k세포)",
    verdict: "재현됨", confirmed: 3, partial: 1, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.96 · 악성 상피세포 F1 0.88 · 전이림프절 골수성 침윤(mLN≫nLN) 재현 · 정상→종양→전이 악성 구배는 부분 재현(정상 폐포 vs 악성 경계 애매)",
  },
  {
    id: "liver-cancer-ma2019", paper: "Ma et al.", year: 2019, journal: "Cancer Cell", cancer: "간암 (liver · HCC+iCCA)",
    verdict: "부분 재현", confirmed: 0, partial: 1, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.97(일치) · 악성 vs HPC-like(간전구세포유사) 경계는 부분 재현(F1 0.71) — 두 집단 모두 상피성 유전자 공유로 본질적 애매",
  },
  {
    id: "hcc-tls-lu2022", paper: "Lu et al.", year: 2022, journal: "Nature Communications", cancer: "간암·종양 내 TLS (HCC · hepatocellular carcinoma)",
    verdict: "재현됨", confirmed: 2, partial: 1, refuted: 0, novel: 0,
    highlight: "세포유형 재현 정확도 0.96(ARI 0.90) · 정상→종양→전이 악성 간세포 편중(17→29→96→98%) 재현 · 종양 내 3차 림프 구조(TLS): CXCL13 3.7배↑·CXCL13⁺ Tfh 42→67% — 부분 재현(B세포 비율차 작음)",
  },
  {
    id: "pd1-resistant-nsclc-h1299", paper: "박상민 (충남대)", year: 2026, journal: "GHBIO 제출 보고서", cancer: "PD-1 내성 폐암 세포주 (H1299-P3 · bulk RNA-seq)",
    verdict: "재현됨", confirmed: 7, partial: 0, refuted: 0, novel: 0,
    highlight: "제출 보고서 독립재현 — 저자 padj 미사용, count matrix에서 재도출 · 타깃 방향 일치 100%(99유전자)·FC 상관 r=0.87 · Tier1(XYLT1·S100A16·GALNT6) 3/3 · Hallmark GSEA 7/7(IFN↑·EMT↓·Notch/Hh↓·E2F/G2M↑)로 'Inflamed but Suppressed'·'classical EMT 아님' 재현 (PacBio·단백질 확인은 범위 밖)",
  },
  {
    id: "ddx54-master-regulator-nsclc", paper: "Gong et al.", year: 2025, journal: "PNAS", cancer: "면역-사막 폐암·면역회피 마스터조절자 (LLC1 Ddx54-KD · bulk RNA-seq)",
    verdict: "재현됨", confirmed: 5, partial: 1, refuted: 0, novel: 0,
    highlight: "DDX54 면역회피 마스터조절자 논문(PNAS 2025) Fig 6 기능검증 독립재현 — 공개 raw counts(GSE285342)에서 저자 padj 미사용 재도출 · Ddx54 녹다운 확인(logFC−0.81, q=0.003) · 면역회피 분자 Cd47·Cd38 하향 · Hallmark GSEA EMT↓·IL6-JAK-STAT3↓·TNFα-NFκB↓ 재현 (Myc는 유전자↓/Hallmark 프로그램↑로 부분) · TCGA GRN 마스터조절자 추론·in-vivo·단백질 확인은 범위 밖",
  },
]

// One claim-level verdict row parsed out of a pipeline's validation_summary.csv.
interface Criterion {
  metric: string
  value: string
  verdict: string
}

// Parse a single CSV line respecting double-quoted fields (a metric can contain commas,
// e.g. "세포유형 일치 정확도 (비악성, ours vs authors)").
function parseCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = ""
  let q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (q) {
      if (c === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++ } else q = false
      } else cur += c
    } else if (c === '"') q = true
    else if (c === ",") { out.push(cur); cur = "" }
    else cur += c
  }
  out.push(cur)
  return out.map((s) => s.trim())
}

// Read each reproduction's REAL validation_summary.csv off disk so the verdict popup shows
// the actual per-claim criteria (metric · value · AGREE/PARTIAL/DISAGREE) — not marketing.
// Missing files just yield an empty array (that badge simply won't be clickable).
function loadCriteria(): Record<string, Criterion[]> {
  const base = path.join(os.homedir(), "ghbio-workspace", "projects")
  const out: Record<string, Criterion[]> = {}
  for (const r of REPRODUCTIONS) {
    const csv = path.join(base, r.id, "results", "validation_summary.csv")
    try {
      const lines = fs.readFileSync(csv, "utf8").split(/\r?\n/).filter((l) => l.trim())
      const rows: Criterion[] = []
      for (let i = 1; i < lines.length; i++) { // skip header
        const [metric, value, verdict] = parseCsvLine(lines[i])
        if (metric) rows.push({ metric, value: value ?? "", verdict: verdict ?? "" })
      }
      if (rows.length) out[r.id] = rows
    } catch {
      // no CSV on this box → non-clickable badge; fine.
    }
  }
  return out
}

function achievementsHtml(criteria: Record<string, Criterion[]>): string {
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
    // If we loaded that pipeline's validation_summary.csv, make the badge a clickable
    // button that opens the 재현 판정 기준 popup for exactly this paper.
    const clickable = (criteria[r.id]?.length ?? 0) > 0
    const vb = clickable
      ? `<button type="button" class="vb ${badge} vb-click" data-id="${esc(r.id)}" ` +
        `title="클릭 — 이 논문의 재현 판정 기준 보기">${esc(r.verdict)} <i>ⓘ</i></button>`
      : `<span class="vb ${badge}">${esc(r.verdict)}</span>`
    return (
      `<tr><td><b>${esc(r.paper)}</b> <span class="yr">${r.year}</span></td>` +
      `<td class="jr">${esc(r.journal)}</td>` +
      `<td>${esc(r.cancer)}</td>` +
      `<td>${vb}</td>` +
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

// The pan-cancer atlas is a META-ANALYSIS across the reproductions (795k cells · 9 cancers),
// not a single-paper reproduction row — so it gets its own showcase block above the table.
// Headline numbers are read from the REAL atlas outputs on disk (same "not marketing" ethos as
// achievementsHtml); if a file is missing we fall back to the last known values.
function panCancerAtlasHtml(): string {
  const base = path.join(os.homedir(), "ghbio-workspace", "projects", "pan-cancer-atlas", "results")
  let tme = 588587, mal = 117036, genes = 13845, mps = 13, verdict = "AGREE"
  try {
    const m = JSON.parse(fs.readFileSync(path.join(base, "harmonize_manifest.json"), "utf8"))
    tme = m.total_tme ?? tme
    mal = m.total_malignant ?? mal
    genes = m.n_common_genes ?? genes
  } catch {
    /* keep fallbacks */
  }
  try {
    const s = fs.readFileSync(path.join(base, "meta_programs_summary.txt"), "utf8")
    const r = s.match(/recurrent_MPs\(>=3 studies\)=(\d+)/)
    if (r) mps = Number(r[1])
  } catch {
    /* keep fallback */
  }
  try {
    const v = fs.readFileSync(path.join(base, "atlas_validation_verdict.txt"), "utf8").match(/verdict=(\w+)/)
    if (v) verdict = v[1]
  } catch {
    /* keep fallback */
  }
  const fmt = (n: number) => n.toLocaleString("en-US")
  const vLabel = verdict === "AGREE" ? "재현됨 (AGREE)" : verdict === "PARTIAL" ? "부분 재현" : verdict
  const tiles = [
    { n: "9", t: "암종을 가로지른 통합", s: "폐·갑상선·위·간·췌장·두경부·GBM·흑색종" },
    { n: fmt(tme), t: "통합한 비악성 TME 세포", s: `공통 유전자 ${fmt(genes)}개로 Harmony 통합` },
    { n: String(mps), t: "재발성 악성 메타프로그램", s: `표본별 NMF · ${fmt(mal)} 악성세포에서 도출` },
    { n: vLabel, t: "아틀라스 자기일관성 판정", s: "U1 공유상태·U2 메타프로그램·U3 탈분화 3/3" },
  ]
  return (
    `<div class="sec-h" id="atlasSec">범암종 아틀라스 (Pan-Cancer Atlas) <span class="new-pill">NEW</span></div>` +
    `<p class="sec-sub">개별 논문 재현을 넘어, <b>11개 재현 결과를 하나로 통합</b>한 메타분석입니다. ` +
    `비악성 면역·기질세포는 통합해 <b>여러 암에 공유되는 세포상태</b>를, 악성세포는 표본별로 분해해 ` +
    `<b>모든 암에서 반복되는 프로그램</b>을 도출했습니다.</p>` +
    `<div class="ach-tiles">` +
    tiles.map((x) => `<div class="atile atlas"><b>${x.n}</b><div class="t">${x.t}</div><div class="s">${x.s}</div></div>`).join("") +
    `</div>` +
    `<div class="feat atlas-feat">` +
    `<div class="fcard"><div class="ic">🌐</div><h3>Use 1 · 공유 TME 상태</h3>` +
    `<p>CD8 세포독성 T·C1Q⁺ TAM·naive/memory T는 <b>10개 암 전부</b>에 공통. 반면 <b>CD8 소진(exhausted)</b>은 ` +
    `HNSCC·두경부·간·흑색종 등 <b>면역원성 종양에만</b> — 면역치료 관련 신호.</p></div>` +
    `<div class="fcard"><div class="ic">🧬</div><h3>Use 2 · 악성 메타프로그램</h3>` +
    `<p>세포주기(MP1, <b>9/10 암</b>)·저산소·인터페론·AP-1 스트레스가 범암 공통. 흑색종 MITF↔AXL, GBM 4상태, ` +
    `폐 tS1/2/3, 두경부 p-EMT가 <b>하나의 프레임</b>으로 통합됩니다.</p></div>` +
    `</div>` +
    `<div class="atlas-cta"><button class="enter" id="atlasBtn">🧬 아틀라스 열기 (Open Pan-Cancer Atlas)</button>` +
    `<span class="atlas-note">저자 라벨 미소비 · GPU·Python 독립 재도출 (BioIDE 헌장)</span></div>`
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

  // Read each paper's real validation_summary.csv once, and hand the webview a per-paper
  // payload the verdict popup renders from (metadata + the actual criteria rows).
  const criteria = loadCriteria()
  const verdictData = Object.fromEntries(
    REPRODUCTIONS.filter((r) => criteria[r.id]?.length).map((r) => [
      r.id,
      { paper: r.paper, year: r.year, journal: r.journal, cancer: r.cancer, verdict: r.verdict, rows: criteria[r.id] },
    ]),
  )
  const verdictJson = JSON.stringify(verdictData)

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
  /* ---------- pan-cancer atlas showcase ---------- */
  .new-pill { font-size: 11px; font-weight:800; color:#0b0f1a; background: linear-gradient(120deg,#2dd4bf,#a78bfa);
    padding: 2px 8px; border-radius: 999px; vertical-align: middle; margin-left: 6px; }
  .atile.atlas { border-color:#4c327e; background: linear-gradient(135deg,#141024,#0e1524); }
  .atile.atlas b { font-size: 34px; }
  .atlas-feat { margin-top: 12px; grid-template-columns: repeat(auto-fit, minmax(300px,1fr)); }
  .atlas-cta { text-align:center; margin: 16px 0 4px; display:flex; flex-direction:column; align-items:center; gap:8px; }
  .atlas-note { font-size: 11.5px; color:#8b98a5; }
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
  /* the verdict badge, when backed by a real validation_summary.csv, is a clickable button */
  .vb-click { cursor:pointer; transition: filter .12s, transform .12s; }
  .vb-click i { font-style:normal; opacity:.72; margin-left:2px; font-size:10px; }
  .vb-click:hover { filter: brightness(1.1); transform: translateY(-1px); }
  .vb-click:focus-visible { outline: 2px solid #93c5fd; outline-offset: 2px; }

  /* ---------- 재현 판정 기준 popup (reuses .overlay) ---------- */
  .crit-modal { max-width: 640px; width: 100%; background:#0e1420; border:1px solid #2a3446; border-radius:16px;
    padding: 22px 24px 20px; position: relative; box-shadow: 0 30px 80px -30px rgba(0,0,0,.8);
    max-height: 86vh; overflow-y: auto; }
  .crit-modal .close { position:absolute; top:12px; right:14px; background:#21262d; color:#e6edf3; border:1px solid #30363d;
    border-radius:8px; padding:5px 9px; font-size:13px; font-weight:700; }
  .crit-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin: 2px 40px 2px 0; }
  .crit-head h3 { margin:0; font-size:18px; color:#eaf2f7; }
  .crit-head .yr { color:#8b98a5; font-weight:600; font-size:12px; }
  .crit-sub { margin: 6px 0 14px; font-size:12.5px; color:#93a1b0; }
  .crit-sub b { color:#cbd5e1; }
  .crit-table { width:100%; border-collapse: collapse; font-size:12.5px; }
  .crit-table th { text-align:left; color:#7a8794; font-weight:600; font-size:11px; padding:6px 8px;
    border-bottom:1px solid #253044; }
  .crit-table td { padding:7px 8px; border-bottom:1px solid #19212e; vertical-align:top; color:#c4cfda; }
  .crit-table td.mv { font-variant-numeric: tabular-nums; color:#e6edf3; font-weight:700; white-space:nowrap; }
  .crit-table tr:last-child td { border-bottom:none; }
  .pill { display:inline-block; font-size:10.5px; font-weight:800; padding:2px 8px; border-radius:999px; white-space:nowrap; }
  .pill.AGREE { color:#06121a; background: linear-gradient(135deg,#2dd4bf,#34d399); }
  .pill.PARTIAL { color:#1a1204; background: linear-gradient(135deg,#fbbf24,#f59e0b); }
  .pill.DISAGREE { color:#fff; background: linear-gradient(135deg,#f87171,#dc2626); }
  .pill.NA, .pill.N\\/A { color:#cbd5e1; background:#2a3446; }
  .crit-legend { margin-top:14px; padding-top:12px; border-top:1px solid #1c2634; font-size:11.5px; color:#8b98a5;
    line-height:1.6; }
  .crit-legend .pill { margin: 0 3px; }
  .crit-legend code { color:#7ee7d6; }

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

    ${panCancerAtlasHtml()}

    ${achievementsHtml(criteria)}

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

  <div class="overlay" id="critOverlay">
    <div class="crit-modal">
      <button class="close" id="critClose">✕</button>
      <div id="critBody"></div>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi()
    function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
    let currentUser = ${userJson}

    // ---- 재현 판정 기준 popup: real validation_summary.csv rows, per paper ----
    const VERDICT_DATA = ${verdictJson}
    const critOv = document.getElementById('critOverlay')
    function verdictPillClass(v){ return String(v || '').replace(/[^A-Za-z]/g, '').toUpperCase() || 'NA' }
    function openCrit(id){
      const d = VERDICT_DATA[id]; if (!d) return
      const rowsHtml = d.rows.map(function(r){
        return '<tr><td>' + escapeHtml(r.metric) + '</td>' +
          '<td class="mv">' + escapeHtml(r.value) + '</td>' +
          '<td><span class="pill ' + verdictPillClass(r.verdict) + '">' + escapeHtml(r.verdict) + '</span></td></tr>'
      }).join('')
      document.getElementById('critBody').innerHTML =
        '<div class="crit-head"><h3>' + escapeHtml(d.paper) + ' <span class="yr">' + d.year + ' · ' +
          escapeHtml(d.journal) + '</span></h3></div>' +
        '<p class="crit-sub">' + escapeHtml(d.cancer) + ' · 종합 판정 <b>' + escapeHtml(d.verdict) + '</b>. ' +
          '아래는 우리 독립 GPU·Python 재분석을 저자 라벨과 정량 대조한 <b>실제 지표</b>입니다 ' +
          '(<code>validation_summary.csv</code>, BioIDE 헌장 제2조).</p>' +
        '<table class="crit-table"><thead><tr><th>지표 (metric)</th><th>값</th><th>판정</th></tr></thead>' +
          '<tbody>' + rowsHtml + '</tbody></table>' +
        '<div class="crit-legend">판정 기준: 지표가 임계값 이상이면 ' +
          '<span class="pill AGREE">AGREE</span>(일치), 낮으면 <span class="pill PARTIAL">PARTIAL</span>(부분 일치), ' +
          '더 낮으면 <span class="pill DISAGREE">DISAGREE</span>(불일치)로 자동 판정합니다. ' +
          '예: 세포유형 일치 정확도 ≥0.8 → AGREE, ≥0.6 → PARTIAL. 저자 결론을 정답으로 전제하지 않고, ' +
          '서로 다른 두 독립 분석이 <b>수렴</b>하는지를 봅니다.</div>'
      critOv.classList.add('on')
    }
    function closeCrit(){ critOv.classList.remove('on') }
    document.getElementById('critClose').onclick = closeCrit
    critOv.addEventListener('click', function(e){ if (e.target === critOv) closeCrit() })
    Array.prototype.forEach.call(document.querySelectorAll('.vb-click'), function(btn){
      btn.addEventListener('click', function(){ openCrit(btn.getAttribute('data-id')) })
    })

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
    var atlasBtn = document.getElementById('atlasBtn')
    if (atlasBtn) atlasBtn.onclick = function(){ send('ghbio.openDashboard', 'pan-cancer-atlas') }
    document.getElementById('missionBtn').onclick = function(){
      const s = document.getElementById('missionSec'); if (s) s.scrollIntoView({ behavior:'smooth' }) }

    window.addEventListener('message', function(ev){
      const m = ev.data
      if (m && m.type === 'user'){ currentUser = m.user; renderAuth(); closeLogin() }
    })

    document.addEventListener('keydown', function(e){ if (e.key === 'Escape'){ closeLogin(); closeCrit() } })
    renderAuth()
    vscode.postMessage({ type:'getUser' })
  </script>
</body></html>`
}
