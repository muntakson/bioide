// =============================================================================
// BioIDE 헌장 (Central Dogma / Constitution) — the single source of truth for
// what a BioIDE tutorial IS. Every surface that lets someone create a new
// tutorial (the Create-pipeline panel and each AI prompt it runs) imports this,
// so the mission is exposed to — and binding on — all tutorial creators.
//
// The core mandate, learned the hard way: REPRODUCE, don't CONSUME. A tutorial
// must RE-DERIVE the paper's analysis with our own freshly-written GPU-centric
// Python code and treat the authors' processed labels/annotations as CLAIMS to
// independently validate — never as inputs to be trusted and copied through.
// =============================================================================

export interface MissionArticle {
  n: number
  title: string
  body: string
}

export const BIOIDE_MISSION_ARTICLES: MissionArticle[] = [
  {
    n: 1,
    title: "독립 재현, 소비 금지 (Reproduce, don't consume)",
    body:
      "원 논문의 분석을 우리가 새로 작성한 GPU 중심 Python 코드로 처음부터 다시 도출한다. " +
      "저자가 제공한 처리·주석 결과(세포유형 라벨, 악성세포 판정, 클러스터, 임베딩)를 분석의 입력으로 " +
      "소비하지 않는다 — 그것들은 우리가 독립적으로 재현·검증해야 할 저자의 '주장(claim)'이다. " +
      "공개 데이터가 처리 완료 행렬뿐이어도, 그 행렬에서 QC·클러스터링·세포유형 주석·악성세포 식별을 " +
      "우리 코드로 다시 수행하고 저자 라벨은 오직 검증 대조용으로만 쓴다.",
  },
  {
    n: 2,
    title: "독립 검증 (Independent validation)",
    body:
      "우리의 독립 결과를 저자 주장과 정량적으로 대조한다(예: ARI, marker 중복, 세포유형/조성 일치, " +
      "CNV 농도). 일치·부분일치·불일치를 정직하게 판정해 보고하고, 원 논문 결론을 지지하는지 분명히 밝힌다.",
  },
  {
    n: 3,
    title: "공개 원자료 필수 (Public raw data only)",
    body:
      "저자가 실제로 사용한 원본 데이터가 공개(GEO/SRA/ENA/Zenodo 등)된 논문만 대상으로 한다. " +
      "접근번호(accession)는 실제 존재를 확인하고, 불확실하면 '확인 필요'로 표기하며 절대 지어내지 않는다.",
  },
  {
    n: 4,
    title: "현대 스택 (Modern GPU-Python stack)",
    body:
      "구식 R/Seurat 워크플로를 Python(Scanpy)·GPU(scVI·rapids-singlecell·PyTorch)·AI 해석으로 대체해, " +
      "같은 결론에 더 빠르고 재현 가능하게 도달하는지 보인다.",
  },
  {
    n: 5,
    title: "커뮤니티 기여 (Contribute upgraded code)",
    body:
      "새로 작성한, 재사용 가능한 GPU 중심 소스코드를 커뮤니티에 개선된 형태로 남긴다. " +
      "다른 암+scRNA-seq 연구자가 그대로 가져다 쓸 수 있어야 한다.",
  },
  {
    n: 6,
    title: "정직 (Honesty about the level of reproduction)",
    body:
      "'재현'의 층위를 구분한다 — 원시 리드(FASTQ)부터의 독립 복제, 저자 코드로의 정밀 재현, 처리 데이터로부터의 " +
      "계산 재현은 서로 다른 주장이다. 무엇을 했고 무엇은 하지 않았는지, 한계를 명시하고 과장하지 않는다.",
  },
]

/** Plain-text constitution, prepended to every AI prompt that creates a tutorial. */
export const BIOIDE_MISSION: string =
  "=== BioIDE 헌장 (Central Dogma · 모든 재현 튜토리얼이 반드시 준수) ===\n" +
  "BioIDE의 사명: 암+scRNA-seq 분야의 기념비적 논문을, 우리가 독립적으로 새로 작성한 GPU 중심 Python 코드로 " +
  "재현해 저자의 주장을 검증하고, 개선된 소스코드를 커뮤니티에 기여한다.\n" +
  BIOIDE_MISSION_ARTICLES.map((a) => `제${a.n}조 (${a.title}) — ${a.body}`).join("\n")

/** HTML banner for creator-facing panels (Create-pipeline, Home). */
export function missionHtml(): string {
  const items = BIOIDE_MISSION_ARTICLES.map(
    (a) => `<li><b>제${a.n}조 · ${a.title}</b> — ${a.body}</li>`,
  ).join("")
  return (
    '<div class="mission">' +
    '<div class="mission-h">📜 BioIDE 헌장 <span>(Central Dogma · 모든 재현 튜토리얼의 헌법)</span></div>' +
    '<div class="mission-lead">암+scRNA-seq 기념비적 논문을 <b>우리가 새로 짠 GPU·Python 코드로 독립 재현</b>해 ' +
    '저자 주장을 검증하고, 개선된 소스코드를 커뮤니티에 기여한다. ' +
    '<b>핵심: 저자의 라벨·주석을 소비하지 말고, 처음부터 다시 도출해 검증하라.</b></div>' +
    `<ol class="mission-list">${items}</ol>` +
    "</div>"
  )
}
