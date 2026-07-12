import * as vscode from "vscode"
import * as fs from "fs"
import * as path from "path"
import * as os from "os"
import * as cp from "child_process"
import { loadProviders, streamChat } from "./ai/providers"
import { loadModules, findPipeline, defaultPipeline } from "./modules"
import { tutorialResultsDir } from "./util"
import type { Pipeline } from "./pipeline"

// "과학논문 작성" — a webview that collects author/affiliation, then has the AI draft a paper
// (Markdown) grounded in the pipeline's REAL results. Single-shot streaming (same reliable
// no-agent design as the AI panel). TWO distinct modes, opened by two different dashboard buttons:
//
//   "edu"      — a science-EDUCATION paper for the (imaginary) 한국생물교육학회: the focus is the
//                educational value of BioIDE as a teaching tool, with this tutorial as the storyline.
//   "research" — a BIOINFORMATICS reproduction paper: BioIDE independently re-processed the SAME
//                published raw data, presents figure-by-figure quantitative findings, and compares
//                our results against the original authors' conclusions.
//
//   "research_hs" — a high-school STORYTELLING explainer of the already-generated bioinformatics
//                    research paper: reads that paper's .md and retells it (no academic format needed),
//                    with heavy metaphors and a comprehensive walkthrough of every figure and table.
//
// The three modes write DIFFERENTLY NAMED files, prefixed with the pipeline id, so they never collide:
//   <pipelineId>_edu_paper.{md,pdf} · <pipelineId>_research_paper.{md,pdf} · <pipelineId>_research_hs_paper.{md,pdf}

export type PaperMode = "edu" | "research" | "research_hs"

const DEFAULT_MODELS: Record<string, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
  groq: ["llama-3.3-70b-versatile"],
  openrouter: ["anthropic/claude-sonnet-4", "deepseek/deepseek-chat"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
}

// What BioIDE is — kept accurate so the AI never invents features. The edu paper leans on the
// teaching angle; the research paper leans on the reproducible-pipeline angle.
const APP_DESC = `**BioIDE** — 생물학자를 위한 생물정보학 통합개발환경(IDE).
- 브라우저에서 도는 VS Code(code-server) 위에, 생물정보학 기능을 **PlatformIO처럼 확장(extension)** 으로 추가.
- 활동막대 아이콘 → 사이드바(파이프라인 트리)·에디터의 GHBIO Home·대시보드로 구성.
- **데이터 기반 레지스트리**: modules/<id>/module.json + pipelines/<pid>/pipeline.json(JSON)만 추가하면 새 분석 도메인/파이프라인이 등록됨(코드 수정 불필요).
- **단계별·상호작용형 튜토리얼**: 각 단계 버튼을 누르면 셸 Task로 실행(▶/✅ 배너), 결과 아티팩트가 생기면 자동으로 ✓ 표시. 다운로드/변환/정렬 진행 상태를 대시보드 접이식 상자에 실시간 표시.
- **신뢰성 있는 단발성 AI 분석 패널**: LLM에 한 번 요청해 해석·가설을 스트리밍(도구/에이전트 루프 없음). 프리셋 질문 답변은 캐시되어 통합 리포트에 자동 포함.
- **결과는 1급 프로젝트 파일**(GHBIO_RESULTS): ~/ghbio-workspace/projects/<id>/results/ 에 그림·표·리포트 저장.
- **한국인 생물학자 대상**: UI·설명·AI 답변이 한국어 우선(이중언어).
- **경량 하드웨어 대응**: aarch64에서 STARsolo를 소스 컴파일. 공개 데이터가 처리 완료 행렬로만 배포될 때는 그 행렬에서 시작해 동일한 Scanpy 파이프라인으로 분석.`

// ---- Two system prompts -----------------------------------------------------
const EDU_SYSTEM =
  "당신은 학술 논문 작성 도우미입니다. (가상의) **한국생물교육학회** 학술지에 제출할, 완성도 높은 " +
  "**과학교육 논문**을 한국어로, **Markdown 형식**으로 작성하세요. 논문 주제는 '생물학자를 위한 " +
  "생물정보학 통합개발환경(IDE)'이라는 교육용 도구와 그 교육적 활용입니다. 다음 구성을 따르세요: " +
  "제목 / 저자·소속 / 국문초록 / Abstract(영문) / 주제어(Keywords, 국·영문) / 1. 서론 / " +
  "2. 시스템 설계 및 구현 / 3. 교육용 튜토리얼 사례 / 4. 결과 및 교육적 활용 / " +
  "5. 논의 / 6. 결론 / 참고문헌. **제공된 실제 분석 수치를 반드시 인용**하고, 학술적이고 구체적으로, " +
  "표와 목록을 적절히 사용해 작성하세요. 초점은 이 도구의 **교육적 의의**입니다. 과장 없이 사실에 근거하되 " +
  "교육적 가치를 분명히 하세요. 분량은 학술지 기준 충분히(대략 3000~4500자 이상). Markdown 외의 머리말/맺음말은 넣지 마세요."

const RESEARCH_SYSTEM =
  "당신은 생물정보학 연구 논문 작성 도우미입니다. 아래 정보를 바탕으로 **단일세포 RNA-seq 재현(reproduction) 연구 논문**을 " +
  "한국어 **Markdown**으로 작성하세요. 이 논문의 초점은 교육 도구 홍보가 아니라 **과학적 재현과 발견**입니다. " +
  "핵심 프레이밍: 우리는 원 논문과 **동일한 공개 원자료를 BioIDE 파이프라인으로 독립적으로 재처리**했습니다(저자 코드를 그대로 재실행한 것이 아님). " +
  "다음 구성을 따르세요: 제목 / 저자·소속 / 국문초록 / Abstract(영문) / 주제어(국·영문) / " +
  "1. 서론(원 논문 소개와 연구 배경) / 2. 데이터와 방법(공개 원자료의 독립적 재처리 과정, BioIDE 파이프라인 단계, inferCNV·유전자 프로그램 점수 등 구체적 방법) / " +
  "3. 결과(**그림별 정량 결과** — 표와 수치를 풍부하게) / 4. 원 논문과의 비교(우리 재현 결과 vs 저자 결론을 **항목별로 일치/부분일치/불일치**로 정리하고 그 이유·한계 설명) / " +
  "5. 논의(재현의 한계와 방법 차이) / 6. 결론 / 참고문헌. **제공된 실제 수치를 반드시 정량 인용**하고, 그림·표를 적극 사용하세요. " +
  "과장 없이 사실에 근거하되 발견을 분명히 서술하세요. 분량은 충분히(대략 3500~5000자 이상). Markdown 외의 머리말/맺음말은 넣지 마세요."

const RESEARCH_HS_SYSTEM =
  "당신은 어려운 과학 논문을 청소년에게 재미있게 풀어주는 이야기꾼입니다. 아래에 주어진 **생물정보학 재현 논문**을 " +
  "고등학생도 이해할 수 있게 **이야기하듯(storytelling)** 한국어 Markdown으로 다시 설명해 주세요. " +
  "이것은 새 논문을 쓰는 것이 아니라, 주어진 그 논문을 쉽게 풀어 설명하는 글입니다. " +
  "규칙: (1) 딱딱한 논문 형식(초록·서론·방법·참고문헌 같은 정형 구조)은 따를 필요가 없다 — 흥미로운 이야기 흐름으로 쓴다. " +
  "(2) 모든 전문용어는 반드시 쉬운 말로 풀고 **일상 비유를 아주 많이(최소 8개 이상)** 자연스럽게 녹여 쓴다. " +
  "(3) 그 논문에 나오는 **모든 표(table)와 그림(figure/chart)을 하나도 빠짐없이 그대로 가져와 보여준다** — 표는 Markdown 표로 다시 그리고, " +
  "각 표와 그림(Figure 1B/1C/1D/2/3/4/5) **바로 아래에 '이것이 무엇을 보여주는지·어떻게 읽는지·왜 흥미로운지'를 비유를 곁들여 아주 자세하고 친절하게** 설명한다. 그림 설명을 절대 건너뛰지 않는다. " +
  "(4) 실제 수치를 인용하되, 숫자만 나열하지 말고 비유로 감을 잡게 한다. " +
  "(5) 이 연구가 원 논문(Tirosh 2016)을 BioIDE로 **독립적으로 다시 분석해 재현**했다는 점과, 우리 결과가 원 저자들의 결론과 얼마나 맞는지를 이야기 속에 자연스럽게 녹인다. " +
  "(6) 친근하고 격려하는 말투로 순수 한국어. 맨 끝에 '💡 한 줄 요약'을 넣는다. Markdown 외의 머리말/맺음말은 넣지 마세요."

// -----------------------------------------------------------------------------
// Figure registry — each figure with an easy + a detailed Korean explanation. Only figures that
// actually exist in a given results dir are embedded, in this order. Keyed by output filename, so
// the SAME registry serves every pipeline; existence-filtering naturally selects the right set.
// -----------------------------------------------------------------------------
const FIGURES: { file: string; title: string; easy: string; detailed: string }[] = [
  // --- Metastatic melanoma (Tirosh et al., Science 2016; GSE72056) ---
  { file: "fig1B_infercnv_heatmap.png", title: "Figure 1B. inferCNV — 악성 vs 정상 세포 분리",
    easy: "유전자를 염색체 위치 순서로 늘어놓고 발현의 이동평균을 낸 그림입니다. 아래쪽 악성세포는 넓은 구간이 통째로 증폭/결실되는 비정상 패턴을 보입니다.",
    detailed: "발현값을 염색체 위치 순으로 정렬하고 100-유전자 창으로 이동평균을 낸 뒤 정상세포를 기준선으로 뺀 추론 CNV(log-ratio) 히트맵입니다(원 논문 방법을 GRCh38 GTF 좌표로 직접 재구현). 행=세포, 열=유전체 위치. 악성세포는 큰 규모의 aneuploidy를, 정상 면역/기질 세포는 밋밋한 패턴을 보여 발현만으로 악성세포를 분리할 수 있음을 재현합니다." },
  { file: "fig1C_tsne_malignant.png", title: "Figure 1C. 악성세포 tSNE (종양별 색)",
    easy: "악성세포만 2차원 지도에 찍은 그림입니다. 색은 환자(종양). 같은 환자의 암세포끼리 모입니다.",
    detailed: "악성세포의 tSNE 임베딩. 악성세포는 대체로 종양(환자)별로 분리되어(종양 간 이질성) 각 환자의 암이 고유한 발현 정체성을 가짐을 보여줍니다." },
  { file: "fig1D_tsne_nonmalignant.png", title: "Figure 1D. 정상세포 tSNE (세포유형별 색)",
    easy: "정상세포만의 지도입니다. 색은 세포유형(T·B·대식·내피·CAF·NK). 여러 환자의 같은 면역세포가 섞여 모입니다.",
    detailed: "비악성세포의 tSNE. 종양이 아니라 세포유형별로 군집화되어, 정상세포는 환자와 무관하게 계통(lineage)이 좌표를 결정함을 보여줍니다." },
  { file: "fig2_cell_cycle.png", title: "Figure 2. 악성세포의 세포주기 상태",
    easy: "암세포가 분열 중인지(빨강) 쉬는 중인지(회색)를 G1/S·G2/M 신호로 나눈 산점도와, 종양별 분열세포 비율 막대입니다.",
    detailed: "악성세포의 G1/S 및 G2/M 서명 점수 산점도(cycling/non-cycling 분류)와 종양별 분열세포 비율. 종양마다 순환 세포 비율이 크게 다름을 재현합니다." },
  { file: "fig3_mitf_axl.png", title: "Figure 3. MITF vs AXL 상태",
    easy: "잘 분화된 상태(MITF)와 약에 잘 안 듣는 미분화 상태(AXL)를 세포마다 점수화한 그림. 두 상태는 반대로 움직입니다.",
    detailed: "악성세포별 MITF 프로그램(분화) vs AXL 프로그램(미분화·내성) 점수(음의 상관)와 종양별 Pearson R(대부분 음수). 한 종양 안에서도 두 상태가 연속선으로 공존해 치료 전에도 내성 씨앗 세포가 존재함을 시사합니다." },
  { file: "fig4_caf_tcell.png", title: "Figure 4. 미세환경 — 세포유형 서명과 CAF 보체 프로그램",
    easy: "세포유형별 대표 유전자 서명과, 보체·케모카인 유전자가 CAF에서 특히 높게 켜지는 양상을 보여줍니다.",
    detailed: "왼쪽: 세포유형별 marker의 z-score 서명. 오른쪽: 보체·케모카인 유전자(C1S/C1R/C3/CFB/SERPING1/CXCL12/CCL19 등)의 세포유형별 발현으로 CAF 우세를 강조 — CAF–T세포 상호작용 후보. (원 논문 Fig 4A/C의 TCGA bulk 디컨볼루션은 외부 데이터가 필요해 단일세포 부분만 재현.)" },
  { file: "fig5_tcell_exhaustion.png", title: "Figure 5. T세포 — 세포독성 vs 소진",
    easy: "T세포를 CD4/CD8로 나누고, CD8 T세포가 얼마나 공격적인지(세포독성)와 얼마나 지쳤는지(소진)를 비교한 그림입니다.",
    detailed: "T세포의 CD4/CD8 분류와, CD8 T세포의 세포독성 점수 vs 소진 점수 산점도(추세선 포함). 세포독성이 오르며 소진도 함께 오르는 활성화 의존적 소진 경향을 재현합니다." },
  // --- Modern GPU reanalysis (Maynard et al.) ---
  { file: "umap_scvi.png", title: "Figure 1. GPU scVI UMAP — modern lung-cancer reanalysis",
    easy: "GPU로 학습한 세포 지도입니다. 점은 세포, 색은 유전자 발현이 비슷해 묶인 Leiden cluster입니다.",
    detailed: "저자 공개 Smart-seq2 count와 metadata를 이용해 sample을 batch로 고려한 scVI latent representation을 GPU에서 학습하고 UMAP으로 시각화했습니다. 이는 2020년 Seurat 분석의 재현이 아니라, 방법론적으로 구분된 현대 재분석입니다." },
  { file: "treatment_stage_cluster_composition.png", title: "Figure 2. Treatment-stage cluster composition",
    easy: "치료 전(TN), 잔존질환(RD), 진행질환(PD)에서 어떤 세포 cluster가 상대적으로 많은지 보여줍니다.",
    detailed: "저자 metadata의 naive→TN, grouped_pr→RD, grouped_pd→PD 매핑을 사용한 stage 내 cluster 비율입니다. 환자·샘플 불균형과 암세포 여부를 통제하지 않은 기술통계이므로, 인과성이나 임상 효과의 증거가 아니라 후속 검증을 위한 supportive reanalysis입니다." },
  { file: "rd_vs_pd_program_summary.png", title: "Figure 3. RD/PD gene-program scores by sample",
    easy: "논문에서 중요했던 RD 관련 폐포/손상-회복 신호와 PD 관련 저항성 신호를 샘플마다 비교한 그림입니다.",
    detailed: "AQP4·SFTPB/C/D·CLDN18·NKX2-1·SUSD2·CAV1 등의 RD 관련 프로그램과 IDO1·PLAU/PLAUR·SERPINE1·GJA1 등의 PD 관련 프로그램을 log-normalized expression으로 계산한 뒤 cell이 아닌 sample 단위로 평균화했습니다. cancer-cell-only CNV/driver 검증과 독립 cohort 검증 전에는 논문 결론을 확증하는 증거로 해석할 수 없습니다." },
  // --- Generic Scanpy QC pipelines (PBMC / NSCLC / glioblastoma) ---
  { file: "umap_clusters.png", title: "Figure 1. UMAP — Leiden 클러스터",
    easy: "세포 하나하나를 2차원 지도에 점으로 찍은 그림입니다. 서로 <b>가까운 점일수록 유전자 발현이 비슷</b>하고, 색은 비슷한 세포끼리 묶은 무리(클러스터)입니다.",
    detailed: "UMAP은 각 세포의 수천 개 유전자 발현을 2차원으로 압축한 임베딩입니다. 점=세포, 색=Leiden 클러스터. 서로 떨어진 덩어리는 대체로 다른 세포 유형·상태이며, 좌표축 값 자체엔 의미가 없고 무리가 몇 개로 나뉘고 얼마나 뚜렷이 떨어져 있는지를 봅니다." },
  { file: "qc_violin.png", title: "Figure 2. QC 지표 분포",
    easy: "분석 전에 <b>품질이 낮은 세포를 골라내기 위한</b> 세 가지 값의 분포입니다.",
    detailed: "① 세포당 유전자 수(n_genes): 너무 적으면 빈 방울·죽은 세포, 너무 많으면 두 세포가 겹친 doublet 의심. ② 총 UMI(total_counts): 세포가 잡아낸 mRNA 총량. ③ 미토콘드리아 비율(pct_mito): 높으면 손상·죽어가는 세포. 이 기준으로 이상치 세포를 제거한 뒤 클러스터링했습니다." },
  { file: "nsclc_chart.png", title: "Figure 3. 종양 미세환경 세포 유형 구성",
    easy: "이 종양에서 <b>어떤 세포가 얼마나 많은지</b>를 막대그래프로 나타낸 것입니다.",
    detailed: "각 클러스터를 대표 marker로 폐암 세포 유형에 배정한 뒤 유형별 세포 수·비율을 집계했습니다. Lambrechts 등(Nat Med 2018)의 폐 종양 미세환경(TME) 세포 카탈로그와 같은 관점입니다." },
  { file: "nsclc_stromal_distribution.webp", title: "Figure 4. 간질(비종양) 세포 분포",
    easy: "종양세포를 뺀 <b>주변(간질) 세포들</b>의 구성입니다.",
    detailed: "면역·내피·섬유아세포 등 미세환경 세포의 분포입니다. 논문은 이 간질 세포 구성이 환자 생존과 연관됨을 TCGA(1,572명)로 보였으나, 생존 분석 자체는 임상정보가 필요해 단일 샘플에서는 분포만 제시합니다." },
  { file: "nsclc_endothelial.webp", title: "Figure 5. 내피세포(Endothelial) 클러스터",
    easy: "혈관을 이루는 <b>내피세포</b>가 어디에 있고 어떤 유전자를 켜는지 보여줍니다.",
    detailed: "왼쪽: 내피세포(CLDN5·PECAM1+) 클러스터 강조. 오른쪽: 내피 관련 유전자의 클러스터별 z-score. 종양 내피는 혈관신생(HSPG2·ANGPT2·HIF1A)↑, 면역세포 유인(ICAM1·CCL2)↓ 경향을 보입니다(Lambrechts Fig.2)." },
  { file: "nsclc_fibroblast.webp", title: "Figure 6. 섬유아세포(Fibroblast) 클러스터",
    easy: "조직의 뼈대(세포외기질)를 만드는 <b>섬유아세포</b>의 종류를 보여줍니다.",
    detailed: "섬유아세포 클러스터와 콜라겐 세트·근섬유아세포(ACTA2)·주변세포(RGS5) 등 아형 marker 발현입니다. 논문은 섬유아세포가 서로 다른 콜라겐을 내는 여러 아형으로 나뉨을 보였습니다(Fig.3)." },
  { file: "nsclc_bcell_myeloid.webp", title: "Figure 7. B세포·골수성세포 클러스터",
    easy: "항체를 만드는 <b>B세포</b>와 청소·면역을 담당하는 <b>골수성세포</b> 무리입니다.",
    detailed: "B/형질세포(MS4A1·MZB1·IGHG1)와 골수성세포(대식세포·수지상세포·비만세포) 클러스터입니다. 종양 대식세포는 M2 성향으로 치우치는 경향이 있습니다(Fig.4)." },
  { file: "nsclc_tcell.webp", title: "Figure 8. T세포(T cell) 클러스터",
    easy: "면역의 핵심인 <b>T세포</b>의 하위 종류와 활성 상태를 보여줍니다.",
    detailed: "T세포 아형(CD4/CD8·조절 T세포·세포독성)과 면역관문 유전자(PDCD1·CTLA4·LAG3·TIGIT) 발현입니다. 종양 T세포는 활성화와 함께 관문 분자가 오릅니다(Fig.5)." },
]

const PDF_CSS = `
@page { size: A4; margin: 20mm 18mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK KR","Noto Color Emoji",sans-serif; font-size: 11pt; line-height: 1.7; color: #1f2933; }
h1 { font-size: 19pt; color: #0f766e; border-bottom: 2px solid #2dd4bf; padding-bottom: 6px; margin: 18px 0 8px; }
h2 { font-size: 14pt; color: #0d9488; border-left: 5px solid #2dd4bf; padding-left: 9px; margin: 18px 0 6px; }
h3 { font-size: 12pt; color: #0f766e; }
p { margin: 6px 0; } strong,b { color: #0f172a; }
code { font-family: monospace; font-size: 9.5pt; background: #f0fdfa; color: #0f766e; border: 1px solid #99f6e4; border-radius: 4px; padding: 0.5px 4px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 10pt; }
th { background: #0d9488; color: #fff; text-align: left; padding: 6px 8px; }
td { border: 1px solid #cfe8e3; padding: 5px 8px; vertical-align: top; }
tr:nth-child(even) td { background: #f6fffd; }
blockquote { margin: 10px 0; padding: 8px 12px; background: #f0fdfa; border-left: 4px solid #14b8a6; }
.pagebreak { page-break-before: always; }
figure { margin: 14px 0 8px; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #cfe8e3; border-radius: 8px; }
figcaption { font-size: 10pt; color: #0f766e; font-weight: 700; margin-top: 6px; }
.figexpl { font-size: 10pt; color: #334155; margin: 3px 0 16px; }
`

const escHtml = (s: string) =>
  s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!)

// Pull the pipeline's real results into a grounding block so the paper cites true numbers.
// Reads whatever exists — generic across pipelines (melanoma / NSCLC / GPU reanalysis).
function resultsContext(resultsDir: string): string {
  const parts: string[] = []
  const read = (rel: string) => {
    try {
      return fs.readFileSync(path.join(resultsDir, rel), "utf8")
    } catch {
      return ""
    }
  }
  const summary = read("run_summary.txt")
  if (summary) parts.push("### run_summary\n" + summary.trim())
  const solo = read(path.join("starsolo", "Solo.out", "Gene", "Summary.csv"))
  if (solo) parts.push("### STARsolo Summary.csv\n" + solo.trim())
  // Tables shared by many pipelines; melanoma-specific ones (mitf_axl, tcell_states) included too.
  // Kept compact (head N lines) so the whole prompt stays within model limits.
  for (const [file, title, maxLines] of [
    ["celltype_draft.csv", "세포유형/그룹 구성 (celltype_draft.csv)", 40],
    ["markers_by_cluster.csv", "그룹별 top marker (markers_by_cluster.csv)", 80],
    ["mitf_axl_by_cell.csv", "종양별 MITF vs AXL 프로그램 요약 (mitf_axl_by_cell.csv)", 40],
    ["tcell_states.csv", "T세포 세포독성/소진 요약 (tcell_states.csv)", 10],
    ["cluster_sizes.csv", "scVI/Leiden cluster sizes", 60],
    ["treatment_stage_cluster_composition.csv", "Treatment-stage cluster composition (descriptive)", 60],
    ["rd_vs_pd_program_by_sample.csv", "RD/PD program scores by sample (descriptive)", 60],
    ["evidence_focused_summary.md", "Evidence-focused reanalysis limitations", 160],
  ] as const) {
    const text = read(file)
    if (text) parts.push(`### ${title}\n${text.split("\n").slice(0, maxLines).join("\n").trim()}`)
  }
  const figs = FIGURES.map((f) => f.file).filter((f) => fs.existsSync(path.join(resultsDir, f)))
  if (figs.length) parts.push("### 생성된 그림 파일\n" + figs.join(", "))
  return parts.length ? parts.join("\n\n") : "(아직 생성된 결과 파일이 없습니다. 그래도 앱과 파이프라인 설명 중심으로 작성하세요.)"
}

// Render the AI-written paper (Markdown) + a figures appendix into one branded PDF.
function buildPaperPdf(paperMd: string, resultsDir: string, outName: string): string {
  for (const tool of ["pandoc", "wkhtmltopdf"]) {
    try {
      cp.execFileSync("bash", ["-lc", `command -v ${tool}`], { stdio: "ignore" })
    } catch {
      throw new Error(`'${tool}' 가 설치되어 있지 않습니다.`)
    }
  }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ghbio-paper-"))
  try {
    const mdPath = path.join(tmp, "paper.md")
    fs.writeFileSync(mdPath, paperMd, "utf8")
    const paperHtmlPath = path.join(tmp, "paper.html")
    cp.execFileSync("pandoc", [mdPath, "-f", "gfm", "-t", "html5", "-o", paperHtmlPath])
    const paperHtml = fs.readFileSync(paperHtmlPath, "utf8")

    const figHtml = FIGURES.filter((f) => fs.existsSync(path.join(resultsDir, f.file)))
      .map((f) => {
        const p = path.join(resultsDir, f.file)
        const mime = f.file.endsWith(".webp") ? "image/webp" : "image/png"
        const b64 = fs.readFileSync(p).toString("base64")
        return (
          `<figure><img src="data:${mime};base64,${b64}"><figcaption>${escHtml(f.title)}</figcaption></figure>` +
          `<p class="figexpl"><b>쉬운 설명.</b> ${f.easy}</p>` +
          `<p class="figexpl"><b>자세한 설명.</b> ${f.detailed}</p>`
        )
      })
      .join("\n")

    const full =
      `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><style>${PDF_CSS}</style></head><body>` +
      paperHtml +
      (figHtml ? `<div class="pagebreak"></div><h1>그림 및 설명 (Figures)</h1>${figHtml}` : "") +
      `</body></html>`
    const fullPath = path.join(tmp, "full.html")
    fs.writeFileSync(fullPath, full, "utf8")

    const out = path.join(resultsDir, outName)
    cp.execFileSync("wkhtmltopdf", ["--enable-local-file-access", "--encoding", "utf-8", "-s", "A4", "-q", fullPath, out])
    return out
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
}

// Build the user prompt for each mode, grounded in real dataset metadata + results.
function buildUserPrompt(mode: PaperMode, pipeline: Pipeline | undefined, resultsDir: string, m: any): string {
  const ds = pipeline?.dataSource
  const dsBlock = ds
    ? `제공처: ${ds.provider ?? ""}\n데이터셋: ${ds.dataset ?? ""}\nGEO/URL: ${ds.datasetUrl ?? ""}\n원자료: ${ds.fastqUrl ?? ""}\n크기: ${ds.size ?? ""}\n비고: ${ds.note ?? ""}`
    : "(데이터셋 메타데이터 없음)"
  const authorBlock =
    `## 저자 정보\n저자: ${m.author || "(미기재)"}\n소속: ${m.affiliation || "(미기재)"}` +
    `${m.email ? `\n이메일: ${m.email}` : ""}${m.coauthors ? `\n공동저자: ${m.coauthors}` : ""}` +
    `${m.keywords ? `\n주제어(참고): ${m.keywords}` : ""}`
  const name = pipeline?.name ?? "scRNA-seq"

  // Roster of the figures that actually exist, with their reference explanations, so the model can
  // write a comprehensive per-figure walkthrough even though it cannot see the images.
  const figRoster = FIGURES.filter((f) => fs.existsSync(path.join(resultsDir, f.file)))
    .map((f) => `- **${f.title}**\n  - 요지: ${f.easy}\n  - 상세: ${f.detailed}`)
    .join("\n") || "(생성된 그림 없음)"

  // High-school STORYTELLING explainer of the ALREADY-GENERATED bioinformatics research paper.
  // It reads that paper's markdown as its source and retells it — no academic paper format needed.
  if (mode === "research_hs") {
    let paperMd = ""
    try {
      paperMd = fs.readFileSync(path.join(resultsDir, `${pipeline?.id ?? "paper"}_research_paper.md`), "utf8")
    } catch {
      paperMd = ""
    }
    const source = paperMd
      ? `## 설명할 원본 논문 (이 생물정보학 논문을 고등학생용 이야기로 풀어 설명하세요)\n${paperMd}`
      : `## 원본 논문 아직 없음\n'생물정보학 재현 논문'(${pipeline?.id ?? "paper"}_research_paper.md)이 아직 생성되지 않았습니다. ` +
        `먼저 🔬 버튼으로 그 논문을 만드는 것이 가장 좋지만, 없다면 아래 결과 자료만으로 이야기하듯 설명하세요.`
    return (
      `${source}\n\n` +
      `## 원 논문 배경\n파이프라인: ${name}\n${dsBlock}\n\n` +
      `## 그림별 설명 자료 (모든 그림을 반드시 다루세요)\n${figRoster}\n\n` +
      `## 실제 결과 수치 (인용용)\n${resultsContext(resultsDir)}\n\n` +
      `${authorBlock}\n\n` +
      `## 작성 지침\n위 '생물정보학 재현 논문'의 내용을 **고등학생도 이해할 수 있게 이야기하듯(storytelling)** 다시 설명하라. ` +
      `딱딱한 논문 형식(초록/서론/참고문헌 등)은 필요 없고, 흥미로운 이야기 흐름으로 쓴다. ` +
      `그 논문에 나오는 **모든 표와 그림(Figure 1B, 1C, 1D, 2, 3, 4, 5)을 하나도 빠짐없이 포함**하고, 각 표·그림 바로 아래에 ` +
      `**비유를 곁들여 아주 자세히** '무엇을 보여주는지·어떻게 읽는지·왜 흥미로운지'를 설명하라(그림 설명을 절대 건너뛰지 말 것). ` +
      `이 연구가 원 논문(Tirosh 2016)을 BioIDE로 독립적으로 다시 분석해 재현했다는 점과, 우리 결과가 원 저자 결론과 얼마나 맞는지도 이야기에 자연스럽게 녹여라. ` +
      `맨 끝에 '💡 한 줄 요약'을 넣고, 완성본(Markdown)만 출력하라.`
    )
  }

  if (mode === "research") {
    const claim = pipeline?.ai?.easyReport?.paperClaim
    const stages = (pipeline?.stages ?? [])
      .filter((s) => s.kind === "task")
      .map((s) => `- ${s.title}${s.ko ? ` — ${s.ko}` : ""}`)
      .join("\n") || "(파이프라인 단계 메타데이터 없음)"
    return (
      `## 분석 플랫폼(방법)\n${APP_DESC}\n\n` +
      `## 재현 대상 원 논문 / 공개 데이터\n파이프라인: ${name}\n${dsBlock}\n\n` +
      `## 원 저자들의 핵심 결론 (비교 기준)\n${claim ?? "(원 논문 결론 메타데이터 없음 — 위 데이터셋 설명과 실제 결과를 근거로 서술하라.)"}\n\n` +
      `## BioIDE 재현 파이프라인 단계 (방법 섹션 근거)\n${stages}\n\n` +
      `## 우리의 실제 재현 결과 (반드시 정량 인용)\n${resultsContext(resultsDir)}\n\n` +
      `## 생성된 그림별 설명 자료 (본문에서 각 그림을 반드시 다루세요)\n${figRoster}\n\n` +
      `${authorBlock}\n\n` +
      `## 작성 지침\n이 논문은 **생물정보학 재현 연구 논문**이다(교육 도구 홍보가 아님). 우리는 동일한 공개 원자료를 ` +
      `BioIDE로 **독립적으로 재처리**했다(저자 코드를 그대로 재실행한 것이 아님). 위의 실제 수치를 인용해 ` +
      `**그림 1~5의 정량 결과**를 제시하고, 우리 결과와 **원 저자 결론을 항목별로(일치/부분일치/불일치와 그 이유·한계) 비교**하라. ` +
      `그림·표·수치를 풍부하게 사용하라. 위 내용으로 완성된 논문(Markdown)을 작성하세요.`
    )
  }

  // mode === "edu"
  return (
    `## 개발한 웹앱(교육환경) 설명\n${APP_DESC}\n\n` +
    `## 주요 사례: ${name} 튜토리얼\n파이프라인 이름: ${name}\n${dsBlock}\n\n` +
    `## 실제 분석 결과(반드시 인용)\n${resultsContext(resultsDir)}\n\n` +
    `${authorBlock}\n\n` +
    `## 스토리라인\n나는 생물학자를 위한 생물정보학 통합개발환경을 만들었다. VS Code 기반이라 쓰기 쉽고, ` +
    `PlatformIO처럼 생물정보학이 VS Code 확장으로 추가된다. 학생이 scRNA-seq 데이터 처리 파이프라인을 ` +
    `단계별로 직접 체험할 수 있는 종합적·상호작용적·쉬운 튜토리얼을 갖췄다. 위 웹앱과 데이터셋을 설명하고, ` +
    `**${name} 튜토리얼을 주요 사례(main storyline)** 로 삼아 **교육적 의의**를 논하라.\n\n` +
    `위 내용으로 완성된 논문(Markdown)을 작성하세요.`
  )
}

let panel: vscode.WebviewPanel | undefined
let controller: AbortController | undefined
let currentKey = "" // `${pipelineId}|${mode}` — reuse the panel only when this matches

export function openPaperWriter(context: vscode.ExtensionContext, pipelineId?: string, mode: PaperMode = "edu") {
  const modules = loadModules(context)
  const resolved = (pipelineId && findPipeline(modules, pipelineId)) || defaultPipeline(modules)
  const pipeline = resolved?.pipeline
  const resultsDir = pipeline ? tutorialResultsDir(pipeline.id) : ""
  const key = `${pipeline?.id ?? ""}|${mode}`

  // A single reusable panel. If the mode/pipeline changed, rebuild it so the message-handler
  // closure (which captures mode + filenames) is rebound correctly.
  if (panel && currentKey === key) {
    panel.reveal()
    return
  }
  if (panel) {
    panel.dispose()
    panel = undefined
  }
  currentKey = key

  // Distinct, pipeline-prefixed output names so the modes never collide.
  const suffix =
    mode === "research" ? "research_paper" : mode === "research_hs" ? "research_hs_paper" : "edu_paper"
  const baseName = `${pipeline?.id ?? "paper"}_${suffix}`
  const mdName = `${baseName}.md`
  const pdfName = `${baseName}.pdf`

  panel = vscode.window.createWebviewPanel(
    "ghbioPaper",
    mode === "research"
      ? "GHBIO · 생물정보학 재현 논문"
      : mode === "research_hs"
        ? "GHBIO · 생물정보학 재현 논문 (고등학생용)"
        : "GHBIO · 과학교육 논문",
    vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true },
  )
  const thePanel = panel
  thePanel.onDidDispose(() => {
    controller?.abort()
    if (panel === thePanel) panel = undefined
    currentKey = ""
  })

  const providers = loadProviders()
  const available = Object.keys(providers).filter((p) => providers[p]?.apiKey)
  const modelMap: Record<string, string[]> = {}
  for (const p of available) modelMap[p] = providers[p].models?.length ? providers[p].models! : DEFAULT_MODELS[p] ?? []

  thePanel.webview.html = html(available, modelMap, pipeline?.name ?? "scRNA-seq", mode, pdfName)

  thePanel.webview.onDidReceiveMessage(async (msg) => {
    if (msg.type === "stop") {
      controller?.abort()
      return
    }
    if (msg.type === "save") {
      try {
        fs.mkdirSync(resultsDir || ".", { recursive: true })
        const out = path.join(resultsDir || ".", mdName)
        fs.writeFileSync(out, String(msg.text ?? ""), "utf8")
        thePanel.webview.postMessage({ type: "saved", file: out })
        vscode.commands.executeCommand("vscode.open", vscode.Uri.file(out))
      } catch (e: any) {
        thePanel.webview.postMessage({ type: "saveError", msg: String(e?.message ?? e) })
      }
      return
    }
    if (msg.type === "savePdf") {
      try {
        fs.mkdirSync(resultsDir || ".", { recursive: true })
        fs.writeFileSync(path.join(resultsDir || ".", mdName), String(msg.text ?? ""), "utf8")
        const out = buildPaperPdf(String(msg.text ?? ""), resultsDir || ".", pdfName)
        thePanel.webview.postMessage({ type: "savedPdf", file: out })
        vscode.commands.executeCommand("vscode.open", vscode.Uri.file(out))
      } catch (e: any) {
        thePanel.webview.postMessage({ type: "saveError", msg: "PDF 생성 실패: " + String(e?.message ?? e) })
      }
      return
    }
    if (msg.type !== "generate") return
    const apiKey = providers[msg.provider]?.apiKey
    if (!apiKey) {
      thePanel.webview.postMessage({ type: "error", msg: `${msg.provider} API key가 설정되지 않았습니다.` })
      return
    }
    controller?.abort()
    controller = new AbortController()
    thePanel.webview.postMessage({ type: "start" })
    try {
      await streamChat({
        provider: msg.provider,
        model: msg.model,
        apiKey,
        system:
          mode === "research" ? RESEARCH_SYSTEM : mode === "research_hs" ? RESEARCH_HS_SYSTEM : EDU_SYSTEM,
        user: buildUserPrompt(mode, pipeline, resultsDir, msg),
        signal: controller.signal,
        // The figure-by-figure reproduction papers (research + its high-school rewrite) run long;
        // give them plenty of room. Anthropic honors this; OpenAI-compatible providers are clamped.
        maxTokens: mode === "research" || mode === "research_hs" ? 32000 : 20000,
        onDelta: (t) => t && thePanel.webview.postMessage({ type: "delta", text: t }),
      })
      thePanel.webview.postMessage({ type: "done" })
    } catch (e: any) {
      if (e?.name === "AbortError") thePanel.webview.postMessage({ type: "done", aborted: true })
      else thePanel.webview.postMessage({ type: "error", msg: String(e?.message ?? e) })
    }
  })
}

function html(
  providers: string[],
  modelMap: Record<string, string[]>,
  pipelineName: string,
  mode: PaperMode,
  pdfName: string,
): string {
  const noKeys = providers.length === 0
  const provOpts = providers.map((p) => `<option value="${p}">${p}</option>`).join("")
  const heading =
    mode === "research"
      ? `GHBIO <span class="a">생물정보학 재현 논문</span> · 그림·데이터·원논문 비교`
      : mode === "research_hs"
        ? `GHBIO <span class="a">생물정보학 재현 논문</span> · 고등학생용 (비유·그림설명)`
        : `GHBIO <span class="a">과학교육 논문</span> · 한국생물교육학회 제출용`
  const sub =
    mode === "research"
      ? `저자 정보를 입력하고 <b>📝 논문 생성</b>을 누르면, <b>${pipelineName}</b>의 실제 재현 결과(그림 1~5·정량 표)를 바탕으로 ` +
        `AI가 <b>생물정보학 재현 연구 논문</b>을 작성합니다. 동일 공개 원자료를 BioIDE로 독립 재처리한 결과를 제시하고 ` +
        `<b>원 저자 결론과 비교</b>합니다. 완료 후 <b>📄 PDF (그림·설명 포함)</b>로 저장하세요.`
      : mode === "research_hs"
        ? `<b>먼저 🔬 생물정보학 재현 논문을 만든 뒤</b> 이 버튼을 누르세요. 그 논문을 <b>고등학생도 이해할 수 있게 비유를 많이 써서 이야기로 풀어 설명</b>합니다. ` +
          `<b>모든 표와 그림(Figure 1B~5)</b>을 포함하고 각 표·그림마다 자세한 설명을 붙입니다. 완료 후 <b>📄 PDF (그림·설명 포함)</b>로 저장하세요.`
        : `저자 정보를 입력하고 <b>📝 논문 생성</b>을 누르면, 이 웹앱과 <b>${pipelineName}</b> 튜토리얼의 실제 결과를 바탕으로 ` +
          `AI가 <b>교육적 의의</b>에 초점을 둔 논문을 작성합니다. 완료 후 <b>💾 .md</b> 또는 <b>📄 PDF</b>로 저장하세요.`
  // Match each mode's dashboard button color: research=red/purple, research_hs=yellow, edu=teal.
  const genBtnGrad =
    mode === "research" ? "#be123c,#7c3aed" : mode === "research_hs" ? "#f59e0b,#eab308" : "#2dd4bf,#22d3ee"
  const genBtnColor = mode === "research" ? "#fff" : "#06121a"
  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
  :root{color-scheme:dark}
  body{font-family:-apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif;color:#e6edf3;background:#0d1117;margin:0;padding:18px 22px}
  h2{margin:0 0 2px;font-size:19px}.a{color:#2dd4bf}
  .sub{color:#8b98a5;font-size:12.5px;margin-bottom:14px}
  .form{display:grid;grid-template-columns:110px 1fr;gap:9px 12px;align-items:center;max-width:680px;margin-bottom:12px}
  label{color:#b6c2cf;font-size:13px}
  input,select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px;font:inherit;width:100%;box-sizing:border-box}
  .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0 12px}
  button{cursor:pointer;border:none;border-radius:7px;padding:7px 13px;font-size:13px;font-weight:600}
  #gen{background:linear-gradient(135deg,${genBtnGrad});color:${genBtnColor}}
  #stop{background:#3d1418;color:#ffb4b4;border:1px solid #6e2b2b;display:none}
  #save{background:#12312b;color:#7ee7d6;border:1px solid #1f5a4f;display:none}
  #savePdf{background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;display:none}
  .warn{background:#3a2a12;border:1px solid #7a5a1e;color:#f0d090;padding:10px;border-radius:8px;font-size:13px}
  #out{background:#0b0f14;border:1px solid #30363d;border-radius:10px;padding:16px 18px;min-height:160px;
    white-space:pre-wrap;line-height:1.65;font-size:13.5px;margin-top:10px}
  #out h1,#out h2,#out h3{color:#7ee7d6} #out code{background:#161b22;padding:1px 4px;border-radius:4px}
  #out table{border-collapse:collapse}#out td,#out th{border:1px solid #30363d;padding:3px 7px}
  #saveMsg{font-size:12px;color:#2dd4bf}
  .fn{font-size:11.5px;color:#6e7b8a;margin-bottom:10px}
</style></head><body>
  <h2>${heading}</h2>
  <div class="sub">${sub}</div>
  <div class="fn">저장 파일명: <code>${pdfName}</code></div>
  ${noKeys ? `<div class="warn">API 키가 설정되지 않았습니다. <code>~/.config/ghbio/providers.json</code> 를 확인하세요.</div>` : `
  <div class="form">
    <label>저자 (Author)</label><input id="author" placeholder="예: 홍길동">
    <label>소속 (Affiliation)</label><input id="affiliation" placeholder="예: OO대학교 생물교육과">
    <label>이메일 (선택)</label><input id="email" placeholder="예: hong@univ.ac.kr">
    <label>공동저자 (선택)</label><input id="coauthors" placeholder="예: 김철수, 이영희">
    <label>주제어 (선택)</label><input id="keywords" placeholder="${mode === "edu" ? "예: 생물정보학 교육, 단일세포 RNA-seq, VS Code" : "예: 단일세포 RNA-seq, 흑색종, inferCNV, 재현연구"}">
    <label>Provider</label><select id="prov">${provOpts}</select>
    <label>Model</label><select id="model"></select>
  </div>
  <div class="bar">
    <button id="gen">📝 논문 생성</button>
    <button id="stop">■ Stop</button>
    <button id="save">💾 .md 저장</button>
    <button id="savePdf">📄 PDF 저장 (그림·설명 포함)</button>
    <span id="saveMsg"></span>
  </div>
  <div id="out">여기에 논문이 표시됩니다.</div>`}
  <script>
    const vscode = acquireVsCodeApi()
    const MODELS = ${JSON.stringify(modelMap)}
    const prov=document.getElementById('prov'), model=document.getElementById('model')
    const out=document.getElementById('out'), gen=document.getElementById('gen'), stop=document.getElementById('stop'), save=document.getElementById('save'), savePdf=document.getElementById('savePdf')
    function fillModels(){ if(!prov)return; model.innerHTML=(MODELS[prov.value]||[]).map(m=>'<option>'+m+'</option>').join('') }
    if(prov){ prov.onchange=fillModels; fillModels() }
    let raw=''
    function md(t){ return t
      .replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))
      .replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>')
      .replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>').replace(/\`(.+?)\`/g,'<code>$1</code>') }
    const v=id=>{ const e=document.getElementById(id); return e?e.value.trim():'' }
    function hideSaves(){ save.style.display='none'; savePdf.style.display='none' }
    if(gen) gen.onclick=()=>{ raw=''; out.innerHTML='…'; stop.style.display='inline-block'; hideSaves(); document.getElementById('saveMsg').textContent=''
      vscode.postMessage({ type:'generate', provider:prov.value, model:model.value,
        author:v('author'), affiliation:v('affiliation'), email:v('email'), coauthors:v('coauthors'), keywords:v('keywords') }) }
    if(stop) stop.onclick=()=>vscode.postMessage({type:'stop'})
    if(save) save.onclick=()=>{ if(raw.trim()) vscode.postMessage({type:'save',text:raw}) }
    if(savePdf) savePdf.onclick=()=>{ if(raw.trim()){ document.getElementById('saveMsg').textContent='PDF 생성 중…'; vscode.postMessage({type:'savePdf',text:raw}) } }
    window.addEventListener('message',ev=>{ const m=ev.data
      if(m.type==='start'){ raw=''; out.innerHTML='…' }
      else if(m.type==='delta'){ raw+=m.text; out.innerHTML=md(raw) }
      else if(m.type==='done'){ stop.style.display='none'; if(m.aborted) out.innerHTML+=' <i>(중지됨)</i>'; if(raw.trim()){ save.style.display='inline-block'; savePdf.style.display='inline-block' } }
      else if(m.type==='error'){ stop.style.display='none'; out.innerHTML='<div class="warn">'+m.msg+'</div>' }
      else if(m.type==='saved'){ document.getElementById('saveMsg').textContent='저장됨: '+m.file }
      else if(m.type==='savedPdf'){ document.getElementById('saveMsg').textContent='PDF 저장됨: '+m.file }
      else if(m.type==='saveError'){ document.getElementById('saveMsg').textContent=m.msg }
    })
  </script>
</body></html>`
}
