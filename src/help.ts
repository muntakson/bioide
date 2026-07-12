import * as vscode from "vscode"
import { Pipeline } from "./pipeline"
import { loadModules, findPipeline, defaultPipeline } from "./modules"

let panel: vscode.WebviewPanel | undefined

// The help is CONTEXT-AWARE: the shared "basic help" chrome is always shown, and
// the tutorial-specific parts (dataset blurb, step walkthrough, glossary, result
// folder) are rendered from whichever pipeline is currently active. Passing a new
// activePipelineId re-renders an already-open panel so switching tutorials updates it.
export function openHelp(context: vscode.ExtensionContext, activePipelineId?: string) {
  const modules = loadModules(context)
  const resolved = (activePipelineId && findPipeline(modules, activePipelineId)) || defaultPipeline(modules)
  const pipe = resolved?.pipeline

  if (panel) {
    panel.webview.html = html(pipe)
    panel.reveal()
    return
  }
  panel = vscode.window.createWebviewPanel("ghbioHelp", "GHBIO · 사용설명서", vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  panel.onDidDispose(() => (panel = undefined))
  panel.webview.onDidReceiveMessage((m) => {
    if (m?.cmd) vscode.commands.executeCommand(m.cmd, ...(m.args ?? []))
  })
  panel.webview.html = html(pipe)
}

const esc = (t: unknown) =>
  String(t ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")

// Badge = the leading token of a step title ("2a. Build STARsolo" → "2a").
const badgeOf = (title: string) => (title.split(".")[0] || "•").trim()

// Build section 4's step walkthrough from the active pipeline's stages. Step
// descriptions come from pipeline.json `help.steps` (friendly ko, may contain HTML),
// falling back to the stage's own `desc`. Titles use the stage's Korean label.
function stepCards(pipe?: Pipeline): string {
  if (!pipe?.stages?.length) return ""
  return pipe.stages
    .map((s) => {
      const badge = esc(badgeOf(s.title))
      const title = esc(s.ko || s.title)
      const desc = pipe.help?.steps?.[s.id] ?? s.desc ?? "" // trusted HTML from our own manifest
      return (
        `<div class="step"><div class="head"><div class="badge">${badge}</div>` +
        `<div class="title">${title}</div></div>${desc ? `<p>${desc}</p>` : ""}</div>`
      )
    })
    .join("\n")
}

function html(pipe?: Pipeline): string {
  const tutName = esc(pipe?.name ?? "scRNA-seq")
  const projectId = esc(pipe?.id ?? "scrna-seq")
  const intro =
    pipe?.help?.intro ??
    "<b>왼쪽 Pipelines 목록에서 각 단계를 위에서부터 하나씩 누르기만</b> 하면 됩니다."
  const cards = stepCards(pipe)
  const extraGlossary = (pipe?.help?.glossary ?? [])
    .map((g) => `<dt>${esc(g.term)}</dt>\n    <dd>${g.def}</dd>`)
    .join("\n    ")
  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif;
    color: #e6edf3; background: #0d1117; margin: 0; padding: 0; line-height: 1.75; }
  .wrap { max-width: 900px; margin: 0 auto; padding: 32px 28px 80px; }
  h1 { font-size: 28px; margin: 0 0 4px; }
  h1 .a { color: #2dd4bf; }
  .lead { color: #8b98a5; font-size: 15px; margin: 0 0 8px; }
  .note-top { background: #10261f; border: 1px solid #1f6f57; border-radius: 10px;
    padding: 12px 16px; color: #b7f0df; font-size: 14px; margin: 18px 0 26px; }
  h2 { font-size: 21px; margin: 40px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #22303c; }
  h2 .num { display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px; border-radius: 8px; background: #2dd4bf; color: #06121a;
    font-size: 15px; font-weight: 800; margin-right: 10px; vertical-align: middle; }
  h3 { font-size: 16px; margin: 24px 0 8px; color: #7ee7d6; }
  p { margin: 8px 0; font-size: 15px; }
  ul, ol { font-size: 15px; padding-left: 22px; }
  li { margin: 6px 0; }
  .step { background: #12181f; border: 1px solid #253039; border-radius: 12px;
    padding: 4px 20px 14px; margin: 14px 0; }
  .step .head { display: flex; align-items: center; gap: 10px; margin: 14px 0 4px; }
  .step .badge { flex: none; width: 34px; height: 34px; border-radius: 9px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a;
    font-weight: 800; font-size: 16px; display: flex; align-items: center; justify-content: center; }
  .step .title { font-size: 16px; font-weight: 700; }
  .tip { background: #1c2634; border-left: 3px solid #2dd4bf; padding: 8px 14px;
    border-radius: 0 8px 8px 0; margin: 10px 0; font-size: 14px; color: #cdd9e5; }
  .warn { background: #2e2311; border-left: 3px solid #e2b341; padding: 8px 14px;
    border-radius: 0 8px 8px 0; margin: 10px 0; font-size: 14px; color: #f0dca0; }
  code, .kbd { background: #1b2430; border: 1px solid #2c3846; border-radius: 5px;
    padding: 1px 6px; font-family: "SF Mono", ui-monospace, Consolas, monospace; font-size: 13px; color: #9fe6d6; }
  .kbd { color: #e6edf3; }
  b { color: #f0f6fc; }
  .icon { display: inline-block; font-weight: 800; color: #2dd4bf; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }
  th, td { border: 1px solid #2c3846; padding: 8px 12px; text-align: left; vertical-align: top; }
  th { background: #161e27; color: #7ee7d6; }
  td b { color: #7ee7d6; }
  .toc { background: #12181f; border: 1px solid #253039; border-radius: 12px; padding: 14px 20px; margin: 22px 0; }
  .toc a { color: #79d0c2; text-decoration: none; display: block; padding: 3px 0; font-size: 14.5px; }
  .toc a:hover { color: #2dd4bf; text-decoration: underline; }
  .glossary dt { color: #7ee7d6; font-weight: 700; margin-top: 14px; font-size: 15px; }
  .glossary dd { margin: 4px 0 0; padding-left: 0; font-size: 14.5px; color: #cdd9e5; }
  .btn { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    background: linear-gradient(135deg,#2dd4bf,#22d3ee); color: #06121a; font-weight: 700;
    padding: 7px 14px; border-radius: 8px; font-size: 14px; margin: 6px 8px 6px 0; }
  .btn.ghost { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  .foot { margin-top: 46px; padding-top: 16px; border-top: 1px solid #22303c; color: #6e7b8a; font-size: 13px; }
  a { color: #2dd4bf; }
  .qa { margin: 10px 0; }
  .qa .q { color: #f0f6fc; font-weight: 700; }
  .qa .ans { color: #cdd9e5; margin-top: 2px; }
</style></head><body>
<div class="wrap">

  <h1>Bio<span class="a">IDE</span> 사용설명서</h1>
  <p class="lead">생물학 연구자를 위한 단일세포 RNA 분석 도우미 · 처음 쓰는 분을 위한 쉬운 안내서</p>
  <p class="lead" style="margin-top:6px">현재 튜토리얼: <b style="color:#2dd4bf">${tutName}</b> — 이 안내서의 <b>4번</b>과 <b>용어 사전</b>은 이 튜토리얼에 맞춰 표시됩니다.</p>

  <div class="note-top">
    이 프로그램은 <b>인터넷 브라우저(크롬 등) 안에서 열리는 분석 작업실</b>입니다.
    프로그램을 새로 설치할 필요가 없고, 주소만 열면 바로 쓸 수 있어요.
    화면이 조금 복잡해 보여도 걱정하지 마세요. <b>왼쪽에 있는 GHBIO 메뉴만 순서대로 눌러도</b> 분석이 끝납니다.
    이 안내서는 <b>처음부터 끝까지</b> 하나하나 짚어 드립니다.
  </div>

  <div class="toc">
    <b style="color:#7ee7d6">목차</b>
    <a href="#s0">0. 이 프로그램은 무엇인가요?</a>
    <a href="#s1">1. 로그인하기 (접속하기)</a>
    <a href="#s2">2. 화면 살펴보기 (어디에 무엇이 있나요)</a>
    <a href="#s3">3. 새 프로젝트 만들기</a>
    <a href="#s4">4. 튜토리얼(예제) 따라 하기 — 처음부터 끝까지</a>
    <a href="#s5">5. AI 분석 사용하기</a>
    <a href="#s6">6. 아래쪽 창들 설명 (터미널 · 문제 · 출력 등)</a>
    <a href="#s7">7. 자주 나오는 용어 사전</a>
    <a href="#s8">8. 자주 묻는 질문 (문제 해결)</a>
  </div>

  <!-- ============ 0 ============ -->
  <h2 id="s0"><span class="num">0</span>이 프로그램은 무엇인가요?</h2>
  <p>
    <b>BioIDE</b>는 단일세포 RNA 시퀀싱(scRNA-seq) 데이터를 분석하는 작업실입니다.
    유전자 서열 원본 파일(FASTQ)에서 시작해서, 세포별 유전자 개수 표를 만들고,
    비슷한 세포끼리 묶고(클러스터링), 각 세포가 어떤 종류인지 이름을 붙이고,
    마지막으로 <b>AI가 결과를 해석하고 연구 가설까지 제안</b>하는 것까지 한 번에 도와줍니다.
  </p>
  <div class="tip">
    쉽게 말해 — <b>“버튼을 순서대로 누르면 컴퓨터가 알아서 분석해 주는 프로그램”</b>이라고 생각하시면 됩니다.
    명령어를 직접 외우거나 타이핑할 필요가 없습니다.
  </div>

  <!-- ============ 1 ============ -->
  <h2 id="s1"><span class="num">1</span>로그인하기 (접속하기)</h2>
  <div class="step">
    <div class="head"><div class="badge">1</div><div class="title">인터넷 주소 열기</div></div>
    <p>크롬(Chrome) 같은 브라우저를 켜고, 받으신 <b>인터넷 주소(URL)</b>를 주소창에 입력합니다.</p>
    <p>예: <code>https://ghbiocosci.iotok.org</code></p>
  </div>
  <div class="step">
    <div class="head"><div class="badge">2</div><div class="title">비밀번호 입력하기</div></div>
    <p>
      주소를 열면 <b>비밀번호를 물어보는 화면</b>이 나옵니다.
      관리자에게 받은 비밀번호를 입력하고 <b>Enter</b> 키를 누르거나 <b>Submit</b>(제출) 버튼을 누릅니다.
    </p>
    <div class="tip">이 비밀번호 한 개가 이 작업실 전체의 열쇠입니다. 다른 사람과 공유하지 마세요.</div>
  </div>
  <div class="step">
    <div class="head"><div class="badge">3</div><div class="title">작업실이 열립니다</div></div>
    <p>
      로그인에 성공하면 <b>검은색 화면의 작업 프로그램</b>이 나타납니다. 이것이 여러분의 분석 작업실입니다.
      (이 프로그램의 정식 이름은 “VS Code”이지만, 이름은 몰라도 됩니다.)
    </p>
    <div class="warn">
      처음 열면 여러 안내 창이나 알림이 뜰 수 있어요. 읽어보고 <b>×</b> 표시나 닫기 버튼을 눌러 닫으면 됩니다.
      실수로 무언가 눌러도 데이터가 사라지지 않으니 안심하세요.
    </div>
  </div>

  <!-- ============ 2 ============ -->
  <h2 id="s2"><span class="num">2</span>화면 살펴보기 (어디에 무엇이 있나요)</h2>
  <p>화면은 크게 세 부분으로 나뉩니다.</p>
  <table>
    <tr><th>위치</th><th>이름</th><th>하는 일</th></tr>
    <tr><td><b>맨 왼쪽 세로줄</b></td><td>활동 막대<br>(아이콘 줄)</td>
      <td>여러 기능을 켜고 끄는 아이콘들이 세로로 있습니다. <b>두 가닥이 X자로 꼬인 DNA 모양의 GHBIO 아이콘</b>을 누르면 우리 분석 메뉴가 열립니다.</td></tr>
    <tr><td><b>왼쪽 넓은 칸</b></td><td>사이드 패널</td>
      <td>GHBIO 아이콘을 누르면 여기에 <b>Pipelines(분석 순서) · Projects(프로젝트) · Libraries(라이브러리)</b> 목록이 보입니다. 여기서 대부분의 작업을 합니다.</td></tr>
    <tr><td><b>가운데 넓은 칸</b></td><td>편집 영역</td>
      <td>파일 내용, 안내 화면, AI 분석 창이 여기에 열립니다.</td></tr>
    <tr><td><b>아래쪽 칸</b></td><td>패널</td>
      <td>분석이 실제로 돌아가는 <b>터미널</b>과 결과·오류 메시지가 나오는 곳입니다. (6번 항목에서 자세히 설명)</td></tr>
  </table>

  <h3>왼쪽 GHBIO 메뉴 세 가지</h3>
  <ul>
    <li><b>Pipelines (분석 순서)</b> — 미리 준비된 <b>분석 과정</b>입니다. 순서대로 버튼만 누르면 분석이 진행됩니다. 처음엔 여기부터 하세요.
      분석 종류가 여러 개(예: 단일세포 RNA, 단백질 3D 모델링)면 종류별로 묶여서 보입니다.</li>
    <li><b>Projects (프로젝트)</b> — <b>내 분석 작업</b>을 담는 폴더입니다. 새 분석을 시작할 때 여기서 만듭니다.</li>
    <li><b>Libraries (라이브러리)</b> — 분석에 필요한 <b>도구(프로그램) 설치 상태</b>를 보여줍니다. 초록불이면 준비 완료, 설치가 필요하면 버튼으로 설치합니다.</li>
  </ul>
  <div class="tip">
    이 <b>❓ 도움말(사용설명서)</b>은 왼쪽 GHBIO 메뉴 <b>맨 위 오른쪽의 물음표(?) 아이콘</b>을 누르면 언제든 다시 볼 수 있습니다.
  </div>

  <p style="margin-top:14px">지금 바로 열어보기:</p>
  <button class="btn" onclick="send('workbench.view.extension.ghbio')">GHBIO 메뉴 열기</button>
  <button class="btn ghost" onclick="send('ghbio.openHome')">GHBIO 홈 화면 열기</button>

  <!-- ============ 3 ============ -->
  <h2 id="s3"><span class="num">3</span>새 프로젝트 만들기</h2>
  <p>
    <b>프로젝트</b>는 한 가지 분석에 필요한 파일들을 모아두는 <b>전용 폴더</b>입니다.
    실험 하나에 실험 노트 한 권을 쓰듯이, 분석 하나에 프로젝트 하나를 만듭니다.
    (예제만 해볼 거라면 이 단계를 건너뛰고 바로 4번으로 가도 됩니다.)
  </p>
  <div class="step">
    <div class="head"><div class="badge">1</div><div class="title">Projects 옆의 + 버튼 누르기</div></div>
    <p>왼쪽 <b>Projects</b> 글자 위에 마우스를 올리면 오른쪽에 <b>＋ (더하기)</b> 아이콘이 나타납니다. 그것을 누릅니다.</p>
  </div>
  <div class="step">
    <div class="head"><div class="badge">2</div><div class="title">프로젝트 이름 정하기</div></div>
    <p>
      위쪽에 이름을 입력하는 칸이 나옵니다. 예: <code>my-pbmc-analysis</code> 처럼 입력하고 <b>Enter</b>를 누릅니다.
    </p>
    <div class="warn">이름에는 <b>영어 글자·숫자·. _ -</b> 만 쓸 수 있어요. 한글이나 띄어쓰기는 넣지 마세요.</div>
  </div>
  <div class="step">
    <div class="head"><div class="badge">3</div><div class="title">프로젝트 폴더가 자동으로 만들어집니다</div></div>
    <p>안에 <code>data</code>(입력 자료), <code>results</code>(결과), <code>notes.md</code>(메모) 가 자동으로 생깁니다. 그리고 그 폴더가 열립니다.</p>
  </div>
  <div style="margin-top:8px">
    <button class="btn" onclick="send('ghbio.newProject')">지금 새 프로젝트 만들기</button>
  </div>

  <!-- ============ 4 ============ -->
  <h2 id="s4"><span class="num">4</span>튜토리얼(예제) 따라 하기 — 처음부터 끝까지 <span style="font-size:15px;color:#7ee7d6">· ${tutName}</span></h2>
  <p>${intro}</p>
  <div class="tip">
    <b>한 번에 다 돌리고 싶다면?</b> Pipelines 창 <b>맨 위 왼쪽의 ▶▶ (전체 실행) 버튼</b>을 누르세요.
    설치·다운로드·정렬·클러스터링까지 <b>순서대로 알아서 진행</b>하고, 끝나면 AI 분석 창이 자동으로 열립니다.
    (이것이 이 프로그램의 핵심 기능 — <b>“버튼 하나로 scRNA-seq 분석 전체”</b> 입니다.)
    이미 끝난 단계 옆에는 <b>초록색 ✓</b> 표시가 붙어, 어디까지 됐는지 한눈에 보입니다.
  </div>
  <div class="tip">
    각 단계를 누르면 <b>아래쪽 터미널 창</b>에서 컴퓨터가 일을 시작합니다.
    화면에 글자가 주르륵 올라가는 것은 <b>정상</b>입니다 — 컴퓨터가 열심히 일하는 중이라는 뜻이에요.
    <b>“✅ 완료”</b> 라는 초록색 글자가 보이면 그 단계가 끝난 것입니다. 그때 <b>다음 단계</b>를 누르세요.
  </div>
  <div class="warn">
    일부 단계(데이터 내려받기, 유전체 색인 만들기)는 <b>수십 분 이상</b> 걸릴 수 있습니다.
    오래 걸려도 고장이 아니니 <b>기다려 주세요.</b> 창을 닫지 말고 그대로 두면 됩니다.
  </div>

  ${cards}
  <div class="tip">
    이 튜토리얼의 <b>모든 결과 파일(그림·표·리포트)</b>은 왼쪽 <b>Projects</b> 안의
    <code>${projectId}</code> 프로젝트 <code>results</code> 폴더에 <b>실제 파일로</b> 저장됩니다.
    Projects에서 그 프로젝트를 열면 결과를 바로 볼 수 있어요. (용량이 큰 원본 데이터·유전체는 공유 폴더에 따로 보관됩니다.)
  </div>

  <div style="margin-top:10px">
    <button class="btn" onclick="send('workbench.view.extension.ghbio')">Pipelines 열기</button>
  </div>

  <!-- ============ 5 ============ -->
  <h2 id="s5"><span class="num">5</span>AI 분석 사용하기</h2>
  <p>
    AI 분석 창은 위에서 만든 <b>세포 무리의 대표 유전자와 예상 세포 종류</b>를 AI에게 보내
    <b>해석과 연구 가설</b>을 받아오는 곳입니다.
  </p>
  <div class="tip">
    이 AI는 <b>“한 번 물어보면 한 번 대답”</b>하는 방식입니다.
    스스로 파일을 고치거나 이리저리 돌아다니지 않으니 <b>안전하고 예측 가능</b>합니다.
    답이 마음에 안 들면 <b>Stop(정지)</b> 버튼으로 언제든 멈출 수 있습니다.
  </div>
  <div class="step">
    <div class="head"><div class="badge">1</div><div class="title">AI 창 열기</div></div>
    <p>튜토리얼의 <b>“4. AI 분석”</b> 단계를 누르거나, GHBIO 메뉴 위쪽의 <b>반짝이(✨) 아이콘</b>을 누릅니다.</p>
  </div>
  <div class="step">
    <div class="head"><div class="badge">2</div><div class="title">AI 종류와 모델 고르기</div></div>
    <p>위쪽에서 <b>Provider(제공사)</b>와 <b>Model(모델)</b>을 고릅니다. 잘 모르겠으면 <b>기본으로 나온 것을 그대로</b> 두면 됩니다.</p>
    <div class="warn">
      만약 <b>“API 키가 설정되지 않았습니다”</b> 라는 노란 안내가 뜨면, 아직 AI 사용 열쇠(키)가 등록되지 않은 것입니다.
      관리자에게 요청하세요.
    </div>
  </div>
  <div class="step">
    <div class="head"><div class="badge">3</div><div class="title">질문 버튼 누르기</div></div>
    <p>미리 만들어 둔 질문 버튼들이 있습니다. 원하는 것을 누르면 바로 분석이 시작됩니다.</p>
    <ul>
      <li><b>Interpret each cluster</b> — 세포 무리마다 정체와 상태를 해석</li>
      <li><b>Refine cell-type annotation</b> — 세포 종류 이름을 근거와 함께 정리</li>
      <li><b>Pathway / functional</b> — 유전자들이 담당하는 기능·경로 설명</li>
      <li><b>Testable hypotheses</b> — 검증 가능한 연구 가설 제안</li>
      <li><b>Analysis question list</b> — 이어서 해볼 후속 분석 질문 목록</li>
    </ul>
    <p>또는 아래 입력칸에 <b>직접 질문을 적고</b> <span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> 를 눌러도 됩니다.</p>
  </div>
  <div class="step">
    <div class="head"><div class="badge">4</div><div class="title">답 읽기</div></div>
    <p>답이 아래쪽에 <b>실시간으로 한 글자씩 나타납니다.</b> 다 나오면 완료입니다. 필요하면 다른 질문을 또 눌러도 됩니다.</p>
  </div>
  <div style="margin-top:8px">
    <button class="btn" onclick="send('ghbio.openAI')">AI 분석 창 열기</button>
  </div>

  <!-- ============ 6 ============ -->
  <h2 id="s6"><span class="num">6</span>아래쪽 창들 설명 (터미널 · 문제 · 출력 등)</h2>
  <p>
    화면 <b>아래쪽</b>에는 여러 개의 탭이 있습니다.
    생물학 연구자분들께는 낯선 이름들이지만, <b>대부분 직접 만질 필요가 없습니다.</b>
    각각이 무슨 뜻인지만 알아두면 충분합니다.
  </p>
  <table>
    <tr><th>이름</th><th>쉬운 설명</th><th>직접 써야 하나요?</th></tr>
    <tr>
      <td><b>터미널<br>(Terminal)</b></td>
      <td>컴퓨터에게 <b>글자 명령으로 일을 시키는 검은 창</b>입니다. 튜토리얼 단계를 누르면 여기서 분석이 실제로 돌아가고, 진행 상황과 <b>✅ 완료</b> 표시가 여기에 나옵니다.</td>
      <td>버튼이 대신 명령을 넣어주니 <b>직접 타이핑할 필요는 없어요.</b> 진행 상황을 지켜보는 용도로 보면 됩니다.</td>
    </tr>
    <tr>
      <td><b>문제<br>(Problems)</b></td>
      <td>파일 속 <b>문법 오류나 경고</b>를 모아 보여줍니다. 주로 프로그램 코드를 직접 고칠 때 쓰입니다.</td>
      <td>보통 <b>신경 쓰지 않아도 됩니다.</b></td>
    </tr>
    <tr>
      <td><b>출력<br>(Output)</b></td>
      <td>프로그램이 뒤에서 남기는 <b>기록(로그)</b>을 보여줍니다. 문제가 생겼을 때 원인을 찾는 용도입니다.</td>
      <td>평소엔 <b>볼 필요 없어요.</b> 관리자가 확인을 부탁할 때만 열면 됩니다.</td>
    </tr>
    <tr>
      <td><b>디버그 콘솔<br>(Debug Console)</b></td>
      <td>프로그램을 <b>한 줄씩 멈춰가며 점검</b>할 때(디버깅) 쓰는 창입니다. 개발자용 기능입니다.</td>
      <td><b>쓸 일이 없습니다.</b></td>
    </tr>
    <tr>
      <td><b>포트<br>(Ports)</b></td>
      <td>이 작업실 안에서 켠 <b>웹 주소(예: 미리보기 화면)</b>를 바깥에서 열 수 있게 연결해 주는 목록입니다.</td>
      <td><b>거의 쓰지 않아요.</b> 특별한 안내가 있을 때만 사용합니다.</td>
    </tr>
    <tr>
      <td><b>에이전트<br>(Agent)</b></td>
      <td><b>스스로 여러 일을 알아서 하는 AI</b>를 뜻합니다. 이 프로그램의 AI 분석은 일부러 이 방식을 쓰지 <b>않고</b>, 대신 <b>“한 번 묻고 한 번 답하는”</b> 안전한 방식(5번)을 씁니다.</td>
      <td>이 작업실의 <b>GHBIO AI 분석 창(5번)만 쓰면 됩니다.</b></td>
    </tr>
  </table>
  <div class="tip">
    한 줄 요약 — <b>여러분이 주로 볼 것은 “터미널”뿐</b>입니다. 거기서 초록색 <b>✅ 완료</b>만 확인하면 됩니다. 나머지는 몰라도 분석에 지장이 없습니다.
  </div>

  <!-- ============ 7 ============ -->
  <h2 id="s7"><span class="num">7</span>자주 나오는 용어 사전</h2>
  <dl class="glossary">
    <dt>FASTQ</dt>
    <dd>시퀀싱 장비가 내놓는 <b>유전자 서열 원본 파일</b>입니다. 분석의 시작 재료예요.</dd>
    <dt>count matrix (카운트 행렬)</dt>
    <dd><b>어떤 세포에서 어떤 유전자가 몇 개 나왔는지</b>를 적은 큰 표입니다.</dd>
    <dt>클러스터링 (clustering)</dt>
    <dd>성질이 비슷한 세포끼리 <b>무리로 묶는 것</b>입니다. 한 무리 = 비슷한 세포 집단.</dd>
    <dt>UMAP</dt>
    <dd>수많은 세포를 <b>2차원 그림</b> 위에 점으로 흩뿌려, 무리들이 어떻게 나뉘는지 한눈에 보게 해주는 그림입니다.</dd>
    <dt>marker (마커 유전자)</dt>
    <dd>특정 세포 무리에서 <b>유난히 많이 나오는 대표 유전자</b>입니다. 세포 종류를 알아맞히는 단서예요.</dd>
    <dt>cell type annotation (세포 종류 이름 붙이기)</dt>
    <dd>마커를 근거로 각 무리가 <b>어떤 세포(T세포·B세포 등)인지 이름을 붙이는 것</b>입니다.</dd>
    <dt>QC (품질 검사)</dt>
    <dd>죽었거나 이상한 세포를 걸러내어 <b>믿을 만한 세포만 남기는 정리 과정</b>입니다.</dd>
    ${extraGlossary}
    <dt>확장 프로그램 (Extension)</dt>
    <dd>기본 작업실에 <b>기능을 더해주는 추가 부품</b>입니다. 이 <b>BioIDE</b> 자체가 그런 부품이며, 이미 설치되어 있으니 <b>따로 신경 쓸 필요가 없습니다.</b></dd>
  </dl>

  <!-- ============ 8 ============ -->
  <h2 id="s8"><span class="num">8</span>자주 묻는 질문 (문제 해결)</h2>
  <div class="qa"><div class="q">Q. 왼쪽에 GHBIO 메뉴가 안 보여요.</div>
    <div class="ans">맨 왼쪽 세로 아이콘 줄에서 <b>두 가닥이 X자로 꼬인 DNA 모양의 GHBIO 아이콘</b>을 눌러보세요.
    아이콘이 아예 없으면: (1) 브라우저 탭을 <b>새로고침(F5)</b> 하거나, (2) 아이콘 줄 맨 아래의 <b>… (점 세 개)</b> 안에 숨어 있을 수 있으니 눌러보세요.
    그래도 없으면 위쪽 메뉴에서 <b>보기(View) → 명령 팔레트</b>를 열고 <code>GHBIO: Open Home</code> 을 입력해 실행할 수도 있습니다.</div></div>
  <div class="qa"><div class="q">Q. 단계를 눌렀는데 아무 반응이 없어요.</div>
    <div class="ans">아래쪽 <b>터미널</b> 창을 보세요. 글자가 올라가고 있다면 정상적으로 일하는 중입니다. 잠시 기다려 주세요.</div></div>
  <div class="qa"><div class="q">Q. 빨간 글씨 오류(⚠ 오류)가 나왔어요.</div>
    <div class="ans">보통 앞 단계를 건너뛰었거나 도구 설치가 덜 된 경우입니다. <b>위 단계부터 순서대로 다시</b> 눌러보시고, 그래도 안 되면 오류 글자를 복사해 관리자에게 보여주세요.</div></div>
  <div class="qa"><div class="q">Q. AI 분석에서 “결과 파일이 없습니다”라고 나와요.</div>
    <div class="ans">튜토리얼 <b>3번(품질 검사·세포 묶기)</b>을 먼저 끝내야 합니다. 그 단계가 AI가 읽을 결과 파일을 만들어 줍니다.</div></div>
  <div class="qa"><div class="q">Q. 실수로 무언가 눌렀는데 데이터가 사라졌을까 걱정돼요.</div>
    <div class="ans">대부분 안전합니다. 분석 데이터는 큰 용량으로 따로 저장되어 있어, 화면을 잘못 눌러도 쉽게 지워지지 않습니다.</div></div>
  <div class="qa"><div class="q">Q. 오래 걸리는데 멈춘 건가요?</div>
    <div class="ans">데이터 내려받기와 유전체 색인 만들기는 <b>수십 분</b> 걸릴 수 있습니다. 터미널에 글자 움직임이 있으면 정상입니다. 창을 닫지 마세요.</div></div>

  <div class="foot">
    BioIDE · 도움이 더 필요하시면 관리자에게 문의하세요 ·
    <a href="https://ghbio.co.kr/ghbio/sub0401.php">ghbio.co.kr</a>
  </div>

</div>
<script>
  const vscode = acquireVsCodeApi()
  function send(cmd, ...args){ vscode.postMessage({ cmd, args }) }
</script>
</body></html>`
}
