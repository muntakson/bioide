"use client";

// Lightweight bilingual (Korean / English) layer for the atlas. Korean is the
// default; the choice is persisted in localStorage and toggled from the header.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Lang = "ko" | "en";

/** A single localized string. */
export interface Loc {
  ko: string;
  en: string;
}
/** A localized list of paragraphs. */
export interface LocArr {
  ko: string[];
  en: string[];
}

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: "ko",
  setLang: () => {},
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ko");
  useEffect(() => {
    try {
      const saved = localStorage.getItem("nsclc-lang");
      if (saved === "ko" || saved === "en") setLangState(saved);
    } catch {
      /* localStorage unavailable */
    }
  }, []);
  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("nsclc-lang", l);
    } catch {
      /* ignore */
    }
  };
  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

/** Pick the active-language string from a Loc. */
export function tr(loc: Loc, lang: Lang): string {
  return loc[lang];
}

// --- UI chrome strings -------------------------------------------------------
export const UI: Record<string, Loc> = {
  subtitle: {
    ko: "비소세포폐암(NSCLC) 종양미세환경의 단일세포 RNA-seq",
    en: "Single-cell RNA-seq of the non-small cell lung cancer tumor microenvironment",
  },
  cells: { ko: "세포", en: "cells" },
  cellTypesStat: { ko: "세포 유형", en: "cell types" },
  genes: { ko: "유전자", en: "genes" },
  guidedTour: { ko: "가이드 투어", en: "Guided tour" },

  colorCellsBy: { ko: "세포 색상 기준", en: "Color cells by" },
  geneExpr: { ko: "유전자 발현 (feature plot)", en: "Gene expression (feature plot)" },
  cellTypesTitle: { ko: "세포 유형", en: "Cell types" },
  clickToIsolate: { ko: "(클릭하여 강조)", en: "(click to isolate)" },

  tabAnalysis: { ko: "분석 패널", en: "Analysis panels" },
  tabConcepts: { ko: "개념", en: "Concepts" },
  tabExercises: { ko: "실습 문제", en: "Exercises" },

  loading: { ko: "NSCLC 단일세포 아틀라스를 불러오는 중…", en: "Loading NSCLC single-cell atlas…" },
  loadFail: { ko: "아틀라스 데이터를 불러오지 못했습니다: ", en: "Failed to load atlas data: " },
  footer: {
    ko: "NSCLC 아틀라스 · 교육용 도구 · 데모 데이터는 합성 데이터이며 scripts/convert_h5ad.py로 실제 데이터로 교체할 수 있습니다",
    en: "NSCLC Atlas · a teaching tool · demo data is synthetic — swap in real data with scripts/convert_h5ad.py",
  },

  // color-mode buttons
  modeCellType: { ko: "세포 유형", en: "Cell type" },
  modeTissue: { ko: "조직", en: "Tissue" },
  modePatient: { ko: "환자", en: "Patient" },
  modeSample: { ko: "샘플", en: "Sample" },

  // "UMAP colored by <gene> expression."
  umapColoredPre: { ko: "UMAP을 ", en: "UMAP colored by " },
  umapColoredPost: { ko: " 발현으로 색칠했습니다.", en: " expression." },

  // interpretation notes
  noteHowToRead: { ko: "읽는 방법", en: "How to read this" },
  umapNote: {
    ko: "각 점은 하나의 세포이며, 위치는 상위 주성분(PC)의 UMAP 임베딩에서 나옵니다. 따라서 가까운 세포는 전사체가 유사합니다. 거리와 축은 정량적이지 않습니다 — 클러스터 간 간격이나 면적은 차이의 크기나 존재비를 나타내지 않습니다. 배치는 마커·조성 패널과 함께 해석해야 하며, 단독으로 해석하면 안 됩니다.",
    en: "Each point is one cell; position comes from a UMAP embedding of the top principal components, so nearby cells are transcriptionally similar. Distances and axes are not quantitative — cluster separation and area do not encode magnitude or abundance. Interpret the layout together with the marker and composition panels, never alone.",
  },
  compositionNote: {
    ko: "막대는 조성 데이터(합이 100%)라서 한 집단이 늘면 다른 집단은 기계적으로 줄어듭니다. 비율은 조직 해리와 프로토콜에 의해서도 편향됩니다 — 생물학적 결론을 내리기 전에 scCODA나 Milo 같은 방법으로 변화를 검증하세요.",
    en: "Bars are compositional (they sum to 100%), so one population rising forces others down. Proportions are also biased by dissociation and protocol — validate shifts with methods like scCODA or Milo before claiming biology.",
  },
  dotplotNote: {
    ko: "점 크기 = 발현 세포 비율, 색 = 유전자별 스케일된 평균 발현. 크고 밝은 점은 강하고 특이적인 마커입니다. 블록 대각선 패턴은 잘 분리되고 올바르게 주석된 세포 유형의 특징입니다.",
    en: "Dot size = fraction of cells expressing; color = per-gene scaled mean expression. A large bright dot is a strong, specific marker. The block-diagonal pattern is the signature of well-separated, correctly annotated cell types.",
  },

  // GeneSearch
  searchPlaceholder: { ko: "유전자 검색 (예: EPCAM, CD8A)", en: "Search a gene (e.g. EPCAM, CD8A)" },
  clear: { ko: "지우기", en: "Clear" },

  // CompositionChart
  compTitle: { ko: "세포 유형 구성", en: "Cell-type composition" },
  compFooterTissue: {
    ko: "각 막대는 하나의 조직 유형이며 세포 유형 비율로 나뉩니다. 종양 조직에서 악성 상피세포와 골수계 세포가 증가하는 것에 주목하세요 — NSCLC 미세환경의 특징입니다.",
    en: "Each bar is one tissue type, split by cell-type proportion. Note the expansion of malignant epithelial and myeloid cells in tumor tissue — a hallmark of the NSCLC microenvironment.",
  },
  compFooterPatient: {
    ko: "각 막대는 한 명의 환자이며 세포 유형 비율로 나뉩니다. 종양 조직에서 악성 상피세포와 골수계 세포가 증가하는 것에 주목하세요 — NSCLC 미세환경의 특징입니다.",
    en: "Each bar is one patient, split by cell-type proportion. Note the expansion of malignant epithelial and myeloid cells in tumor tissue — a hallmark of the NSCLC microenvironment.",
  },

  // DotPlot
  dotTitle: { ko: "마커 유전자 dot plot", en: "Marker gene dot plot" },
  meanExpr: { ko: "평균 발현", en: "mean expr" },
  pctExpressing: { ko: "발현 세포 %", en: "% expressing" },
  dotFooter: {
    ko: "유전자 라벨을 클릭하면 UMAP을 해당 유전자로 색칠합니다. 크고 밝은 점은 계통을 규정하는 유전자입니다 — 예: 상피세포의 EPCAM, CD8+ T세포의 CD8A.",
    en: "Click a gene label to color the UMAP by that gene. Large bright dots mark lineage-defining genes — e.g. EPCAM in epithelial cells, CD8A in CD8+ T cells.",
  },

  // Walkthrough
  skipTour: { ko: "건너뛰기", en: "Skip tour" },
  back: { ko: "이전", en: "Back" },
  next: { ko: "다음", en: "Next" },
  startExploring: { ko: "탐색 시작", en: "Start exploring" },
  closeTour: { ko: "투어 닫기", en: "Close tour" },

  // ConceptCards
  conceptsIntro: {
    ko: "각 화면 뒤에 있는 분석 방법 — 대학원·생물정보학 수준으로 작성했습니다. 클릭하면 펼쳐집니다.",
    en: "The methods behind each view, written for graduate / bioinformatics students. Click to expand.",
  },

  // Exercises
  exIntro: {
    ko: "인터랙티브 문제 — 위의 아틀라스를 조작하면 체크 표시가 실시간으로 갱신됩니다.",
    en: "Interactive challenges — the checkmarks update live as you drive the atlas above.",
  },
  solved: { ko: "완료", en: "solved" },
  hint: { ko: "힌트", en: "Hint" },
  hideHint: { ko: "힌트 숨기기", en: "Hide hint" },
  showMe: { ko: "보여주기", en: "Show me" },
  revealAnswer: { ko: "정답 보기", en: "Reveal answer" },
  hideAnswer: { ko: "정답 숨기기", en: "Hide answer" },

  // UmapPlot
  hoverSample: { ko: "샘플", en: "Sample" },
  hoverTissue: { ko: "조직", en: "Tissue" },
  zoomHint: { ko: "스크롤 = 확대 · 드래그 = 이동", en: "scroll = zoom · drag = pan" },
  exprWord: { ko: "발현", en: "expression" },
  low: { ko: "낮음", en: "low" },
  high: { ko: "높음", en: "high" },
  zoomIn: { ko: "확대", en: "Zoom in" },
  zoomOut: { ko: "축소", en: "Zoom out" },
  resetView: { ko: "보기 초기화", en: "Reset view" },
};
