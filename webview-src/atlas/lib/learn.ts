// Educational content for the NSCLC Atlas, written for bioinformatics /
// graduate-level students. Kept as data so components stay presentational.
// Every human-facing string is bilingual (Korean / English); see lib/i18n.

import type { ColorMode } from "./types";
import type { Loc, LocArr } from "./i18n";

/** An action the walkthrough can apply to the live app to demonstrate a point. */
export type LearnAction =
  | { kind: "mode"; mode: ColorMode }
  | { kind: "gene"; gene: string }
  | { kind: "highlight"; cellType: string }
  | { kind: "clear" };

export interface TourStep {
  title: Loc;
  body: Loc;
  action?: LearnAction;
}

export const TOUR: TourStep[] = [
  {
    title: { ko: "NSCLC 아틀라스에 오신 것을 환영합니다", en: "Welcome to the NSCLC Atlas" },
    body: {
      ko: "이것은 비소세포폐암(NSCLC) 종양미세환경의 인터랙티브 단일세포 RNA-seq 아틀라스입니다. 다음 몇 단계에서 Scanpy나 Seurat로 만들게 되는 표준 분석 결과물을 하나씩 살펴봅니다. 이 투어는 “?” 버튼으로 언제든 다시 열 수 있습니다.",
      en: "This is an interactive single-cell RNA-seq atlas of the non-small cell lung cancer tumor microenvironment. In the next few steps we'll walk through the standard analysis outputs you'd produce in Scanpy or Seurat. You can reopen this tour any time from the “?” button.",
    },
  },
  {
    title: { ko: "UMAP 임베딩", en: "The UMAP embedding" },
    body: {
      ko: "각 점은 하나의 세포이며, 상위 주성분(PC)의 UMAP 임베딩으로 배치됩니다. 전사체가 유사한 세포는 함께 모여 지금 보이는 클러스터를 형성합니다. 여기서는 주석된 세포 유형 — 종양의 면역·기질·악성 구획 — 으로 색칠했습니다.",
      en: "Every point is one cell, positioned by a UMAP embedding of its top principal components. Transcriptionally similar cells sit together, forming the clusters you see. We've colored them by annotated cell type — the immune, stromal, and malignant compartments of the tumor.",
    },
    action: { kind: "mode", mode: "cellType" },
  },
  {
    title: { ko: "Feature plot (유전자 발현)", en: "Feature plots (gene expression)" },
    body: {
      ko: "단일 유전자의 발현을 임베딩 위에 겹쳐 그린 것이 “feature plot”입니다. 여기 상피세포 마커인 EPCAM은 악성 및 폐포 상피 클러스터에서 밝게 켜지고 면역세포에서는 꺼져 있습니다. 사이드바의 유전자 검색으로 어떤 마커든 시험해 보세요.",
      en: "Overlaying a single gene's expression onto the embedding is a “feature plot”. Here is EPCAM, an epithelial marker — it lights up the malignant and alveolar epithelial clusters and is silent in immune cells. Use the gene search in the sidebar to try any marker.",
    },
    action: { kind: "gene", gene: "EPCAM" },
  },
  {
    title: { ko: "마커를 통한 세포 유형 주석", en: "Cell-type annotation via markers" },
    body: {
      ko: "CD8A는 세포독성 CD8+ T세포를 표시합니다. EPCAM의 feature plot과 비교해 보세요 — 신호가 완전히 다른 영역으로 이동합니다. 이렇게 클러스터는 발현하는 대표 마커로 라벨을 얻습니다(rank_genes_groups → 수동 또는 자동 주석).",
      en: "CD8A marks cytotoxic CD8+ T cells. Compare its feature plot to EPCAM: the signal has moved to a completely different region. This is how clusters get their labels — by the canonical markers they express (rank_genes_groups → manual or automated annotation).",
    },
    action: { kind: "gene", gene: "CD8A" },
  },
  {
    title: { ko: "조성과 dot plot", en: "Composition & the dot plot" },
    body: {
      ko: "지도 아래의 조성 막대는 종양 대 인접 정상 조직에서 세포 유형 비율을 비교하고, dot plot은 모든 마커를 한눈에 요약합니다(크기 = 발현 세포 비율, 색 = 스케일된 평균 발현). 이 둘은 모든 아틀라스 논문의 핵심 그림입니다.",
      en: "Below the map, the composition bars compare cell-type proportions across tumor vs. adjacent-normal tissue, and the dot plot summarizes every marker at once (size = % of cells expressing, color = scaled mean expression). Together these are the core figures of any atlas paper.",
    },
    action: { kind: "clear" },
  },
  {
    title: { ko: "이제 직접 해보세요", en: "Now try it yourself" },
    body: {
      ko: "각 화면의 분석 방법은 개념 탭에서, 여러분의 추론을 실시간 아틀라스와 대조해 확인하는 가이드형 문제는 실습 문제 탭에서 만나보세요. 즐거운 탐색 되세요!",
      en: "Head to the Concepts tab for the methods behind each view, and the Exercises tab for guided challenges that check your reasoning against the live atlas. Happy exploring!",
    },
  },
];

export interface Concept {
  id: string;
  title: Loc;
  summary: Loc;
  body: LocArr; // paragraphs
}

export const CONCEPTS: Concept[] = [
  {
    id: "workflow",
    title: { ko: "scRNA-seq 분석 워크플로", en: "The scRNA-seq analysis workflow" },
    summary: {
      ko: "원시 카운트에서 주석된 아틀라스까지 — 표준 파이프라인.",
      en: "From raw counts to an annotated atlas — the canonical pipeline.",
    },
    body: {
      ko: [
        "표준적인 droplet 기반(예: 10x) 분석은 세포 × 유전자 카운트 행렬에서 시작합니다. 품질 관리(QC)는 총 카운트, 검출 유전자 수, 미토콘드리아 read 비율(용해·사멸 세포의 지표)에 대한 임계값으로 빈 droplet과 저품질 세포를 제거합니다.",
        "이후 카운트는 라이브러리 크기로 정규화(normalize_total, 보통 1e4)하고 log1p 변환하여 분산을 안정화합니다. 고변동 유전자(HVG, ~2,000개)를 선택하고 데이터를 스케일한 뒤, PCA로 변동의 주요 축을 담는 ~30–50개 성분으로 축소합니다.",
        "PCA 공간에서 k-최근접이웃(kNN) 그래프를 만들고 Leiden(또는 Louvain)으로 클러스터링하며, 시각화를 위해 UMAP으로 2D 임베딩합니다. 클러스터는 대표 마커에 대한 차등발현(rank_genes_groups, Wilcoxon)으로, 또는 CellTypist 같은 자동 도구로 주석합니다.",
        "암 연구에서는 악성 세포와 비악성 세포를 구분하는 단계가 추가됩니다 — 종양세포는 이수성(aneuploid)이므로 발현만이 아니라 추정 복제수 변이(inferCNV / CopyKAT)로 판별하는 경우가 많습니다.",
      ],
      en: [
        "A standard droplet-based (e.g. 10x) analysis starts from a cell × gene count matrix. Quality control removes empty droplets and low-quality cells using thresholds on total counts, number of detected genes, and mitochondrial read fraction (a proxy for lysed/dying cells).",
        "Counts are then library-size normalized (normalize_total, typically to 1e4) and log1p-transformed to stabilize variance. Highly variable genes (HVGs, ~2,000) are selected, the data is scaled, and PCA reduces it to ~30–50 components that capture the dominant axes of variation.",
        "A k-nearest-neighbor graph is built in PCA space, clustered with Leiden (or Louvain), and embedded in 2D with UMAP for visualization. Clusters are annotated by differential expression (rank_genes_groups, Wilcoxon) against canonical markers, or with automated tools such as CellTypist.",
        "In cancer studies, an extra step distinguishes malignant from non-malignant cells — often via inferred copy-number variation (inferCNV / CopyKAT) rather than expression alone, since tumor cells are aneuploid.",
      ],
    },
  },
  {
    id: "umap",
    title: { ko: "UMAP 읽기 (그리고 함정)", en: "Reading a UMAP (and its traps)" },
    summary: {
      ko: "국소 구조는 의미가 있지만, 전역 기하는 대체로 그렇지 않습니다.",
      en: "Local structure is meaningful; global geometry mostly is not.",
    },
    body: {
      ko: [
        "UMAP은 비선형 다양체 임베딩입니다. 국소 이웃을 보존하도록 조정되므로 서로 가까운 세포는 실제로 유사합니다. 그러나 전역 거리는 충실히 보존하지 않습니다 — 멀리 떨어진 두 클러스터 사이의 간격은 전사체 차이에 비례하지 않습니다.",
        "가르칠 가치가 있는 결론: 축 단위는 의미가 없고, 클러스터 면적은 존재비나 중요도를 나타내지 않으며, 클러스터 사이에 보이는 “다리(bridge)”는 진짜 중간 상태가 아니라 임베딩 아티팩트일 수 있습니다.",
        "레이아웃은 초매개변수(n_neighbors는 국소 대 전역 구조를 절충, min_dist는 밀집도를 조절)와 상류의 PCA·배치 보정에 의존합니다. UMAP은 항상 정량적 근거 — 마커 발현, 클러스터 통계, 존재비 검정 — 와 함께 해석하고, 절대 단독으로 해석하지 마세요.",
      ],
      en: [
        "UMAP is a non-linear manifold embedding. It is tuned to preserve local neighborhoods, so cells near each other are genuinely similar. It does not faithfully preserve global distances: the gap between two far-apart clusters is not proportional to their transcriptional difference.",
        "Consequences worth teaching: axis units are meaningless, cluster area does not indicate abundance or importance, and apparent “bridges” between clusters can be embedding artifacts rather than true intermediate states.",
        "The layout depends on hyperparameters (n_neighbors trades local vs. global structure; min_dist controls packing) and on the upstream PCA and batch correction. Always interpret UMAP alongside quantitative evidence — marker expression, cluster statistics, and abundance tests — never on its own.",
      ],
    },
  },
  {
    id: "markers",
    title: { ko: "마커 유전자와 dot plot", en: "Marker genes & the dot plot" },
    summary: {
      ko: "주석이 어떻게 정당화되고 시각화되는가.",
      en: "How annotation is justified and visualized.",
    },
    body: {
      ko: [
        "마커는 한 집단에서 나머지에 비해 농축된 유전자입니다. 클러스터별 차등발현(Scanpy 기본값은 Wilcoxon 순위합)이 후보 마커 순위를 냅니다. 세포가 매우 많아 거의 모든 것이 “유의”해지는 단일세포 규모에서는 p-값 단독보다 효과 크기와 발현 세포 비율이 더 중요합니다.",
        "dot plot은 두 양을 동시에 부호화합니다: 점 크기 = 해당 집단에서 유전자를 발현하는 세포 비율(검출), 색 = 집단 내 평균 발현으로, 보통 유전자별 min-max 또는 z-스케일하여 계통 패턴을 유전자 간 비교할 수 있게 합니다.",
        "읽는 법: 크고 밝은 점은 그 유형의 대부분 세포가 유전자를 강하게 발현한다는 뜻으로 좋은 마커입니다. 작거나 어두운 점은 드물거나 낮은 발현을 나타냅니다. 보이는 블록 대각선 구조는 잘 분리되고 올바르게 주석된 세포 유형의 signature입니다.",
      ],
      en: [
        "A marker is a gene enriched in one population relative to the rest. Differential expression per cluster (Wilcoxon rank-sum is the Scanpy default) yields ranked candidate markers; effect size and fraction-expressing matter more than p-value alone at single-cell scale, where n is huge and everything is “significant”.",
        "The dot plot encodes two quantities simultaneously: dot size = fraction of cells in the group expressing the gene (detection), and color = mean expression among the group, usually min-max or z-scaled per gene so lineage patterns are comparable across genes.",
        "Reading it: a large, bright dot means most cells of that type express the gene strongly — a good marker. Small or dark dots indicate rare or low expression. The block-diagonal structure you see is the signature of well-separated, correctly annotated cell types.",
      ],
    },
  },
  {
    id: "dropout",
    title: { ko: "Dropout, 희소성, 그리고 0", en: "Dropout, sparsity & zeros" },
    summary: {
      ko: "scRNA-seq 행렬이 약 90% 0인 이유.",
      en: "Why scRNA-seq matrices are ~90% zero.",
    },
    body: {
      ko: [
        "단일세포 행렬은 극도로 희소합니다. 0은 생물학적 0(유전자가 실제로 꺼짐)과 기술적 0 / “dropout”(전사체가 존재했으나 세포당 낮은 mRNA 포획 효율 때문에 잡히지 않음)의 혼합입니다.",
        "좋은 마커조차 세포별 feature plot이 거칠어 보이는 이유가 이것입니다 — 많은 양성 세포가 단지 샘플링 때문에 0으로 읽힙니다. 이는 또한 log1p 변환, 신중한 정규화, 그리고 (논쟁적이지만) 유사 세포 간 정보를 빌려오는 imputation 방법(MAGIC, scVI)의 동기가 됩니다.",
        "모델링 선택도 여기서 따라옵니다: 카운트 모델(음이항 / 영과잉 NB, scVI에서 사용)은 log-정규화 값을 가우시안으로 다루는 것보다 데이터의 이산적·과분산·0 과다 특성을 더 잘 존중합니다.",
      ],
      en: [
        "Single-cell matrices are extremely sparse. Zeros are a mix of biological zeros (the gene is truly off) and technical zeros / “dropout” (the transcript was present but not captured, due to low mRNA capture efficiency per cell).",
        "This is why per-cell feature plots look grainy even for good markers: many positive cells read zero simply by sampling. It also motivates the log1p transform, careful normalization, and — controversially — imputation methods (MAGIC, scVI) that borrow information across similar cells.",
        "Modeling choices follow from this: count models (negative binomial / zero-inflated NB, as in scVI) respect the discrete, over-dispersed, zero-heavy nature of the data better than treating log-normalized values as Gaussian.",
      ],
    },
  },
  {
    id: "tme",
    title: { ko: "NSCLC 종양미세환경", en: "The NSCLC tumor microenvironment" },
    summary: {
      ko: "누가 있는지, 그리고 왜 임상적으로 중요한지.",
      en: "Who's who, and why it's clinically important.",
    },
    body: {
      ko: [
        "종양은 하나의 생태계입니다. 악성 상피세포 외에도 림프계 구획(CD8+ 세포독성 T세포, CD4+ 보조 T세포, 면역억제성 FOXP3+ Treg, NK세포, B세포·형질세포), 골수계 구획(종양관련 대식세포, 단핵구, 수지상세포, 비만세포), 그리고 기질(암관련 섬유아세포, 내피세포)이 있습니다.",
        "종양과 짝지어진 인접 정상 조직을 비교하면 재구성이 드러납니다: 악성·골수계 집단의 확장, 그리고 T세포 상태가 소진(exhaustion; PDCD1, HAVCR2, LAG3, TOX) 쪽으로 이동. 이러한 상태는 현대 NSCLC 면역치료의 근간인 면역관문 차단(anti-PD-1/PD-L1)에 대한 반응과 저항의 기반이 됩니다.",
        "단일세포 아틀라스가 임상적으로 중요한 이유가 이것입니다: 벌크 시퀀싱이 평균화로 지워버리는 세포 표적과 바이오마커를 지도로 만들어냅니다.",
      ],
      en: [
        "The tumor is an ecosystem. Beyond malignant epithelial cells you find a lymphoid compartment (CD8+ cytotoxic T cells, CD4+ helper T cells, immunosuppressive FOXP3+ Tregs, NK cells, B and plasma cells), a myeloid compartment (tumor-associated macrophages, monocytes, dendritic cells, mast cells), and stroma (cancer-associated fibroblasts, endothelial cells).",
        "Comparing tumor to matched adjacent-normal tissue reveals remodeling: expansion of malignant and myeloid populations, and shifts in T-cell state toward exhaustion (PDCD1, HAVCR2, LAG3, TOX). These states underpin response and resistance to immune-checkpoint blockade (anti-PD-1/PD-L1), the backbone of modern NSCLC immunotherapy.",
        "This is why single-cell atlases matter clinically: they map the cellular targets and biomarkers that bulk sequencing averages away.",
      ],
    },
  },
  {
    id: "composition",
    title: { ko: "조성 분석과 주의점", en: "Compositional analysis & its caveats" },
    summary: {
      ko: "비율은 유익하지만 — 오독하기 쉽습니다.",
      en: "Proportions are informative — and easy to misread.",
    },
    body: {
      ko: [
        "세포 유형 비율은 조성 데이터입니다: 합이 1이므로 한 집단이 늘면 다른 집단은 기계적으로 줄어듭니다. 단순한 세포 유형별 비율 검정은 위양성을 부풀립니다 — 조성을 고려하는 방법(scCODA)이나 이웃 기반 차등 존재비(Milo)를 사용하세요.",
        "비율은 프로토콜에 의해서도 편향됩니다. 조직 해리는 취약한 세포 유형(호중구, 일부 상피세포)을 우선적으로 잃고 강인한 유형을 농축합니다. 단일핵 대 단일세포 프로토콜은 서로 다른 분율을 회수합니다. 주변 RNA(ambient RNA)와 doublet도 카운트를 왜곡합니다.",
        "학생을 위한 실용 규칙: 조성 변화는 검증해야 할 가설로 다루고(예: 이미징/유세포분석), 항상 프로토콜을 보고하세요. 여기 보이는 종양 대 정상에서의 악성세포 확장은 실제 생물학이지만, 그 정확한 크기는 프로토콜에 의존합니다.",
      ],
      en: [
        "Cell-type proportions are compositional: they sum to 1, so an increase in one population mechanically decreases the others. Naive per-cell-type proportion tests inflate false positives; use compositional-aware methods (scCODA) or neighborhood-based differential abundance (Milo).",
        "Proportions are also biased by the protocol. Tissue dissociation preferentially loses fragile cell types (neutrophils, some epithelial cells) and enriches robust ones; single-nucleus vs. single-cell protocols recover different fractions. Ambient RNA and doublets further distort counts.",
        "Practical rule for students: treat composition shifts as hypotheses to validate (e.g. with imaging/flow), and always report the protocol. The tumor-vs-normal expansion of malignant cells shown here is real biology, but its exact magnitude is protocol-dependent.",
      ],
    },
  },
];
