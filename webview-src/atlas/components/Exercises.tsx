"use client";

import { useState } from "react";
import type { ColorMode } from "@/lib/types";
import type { LearnAction } from "@/lib/learn";
import { UI, useLang, tr, type Loc } from "@/lib/i18n";

export interface LiveState {
  colorMode: ColorMode;
  gene: string | null;
  highlight: number | null;
}

interface Props {
  state: LiveState;
  cellTypeIdByName: Record<string, number>;
  onApply: (a: LearnAction) => void;
}

interface Exercise {
  id: string;
  prompt: Loc;
  hint: Loc;
  explanation: Loc;
  // live check against app state; undefined = reveal-only (self-graded)
  check?: (s: LiveState, ids: Record<string, number>) => boolean;
  answer?: LearnAction; // "show me" action
}

const EXERCISES: Exercise[] = [
  {
    id: "cd8",
    prompt: {
      ko: "세포독성 T세포 구획을 찾으세요: CD8+ T세포의 대표 마커로 UMAP을 색칠하세요.",
      en: "Locate the cytotoxic T-cell compartment: color the UMAP by a canonical marker of CD8+ T cells.",
    },
    hint: {
      ko: "CD8 계통을 규정하는 공동수용체나 세포독성 과립 유전자를 떠올리세요 (CD8A, CD8B, GZMK).",
      en: "Think of the co-receptor that defines the CD8 lineage, or a cytotoxic granule gene (CD8A, CD8B, GZMK).",
    },
    explanation: {
      ko: "CD8A/CD8B는 CD8 공동수용체를, GZMK는 세포독성 효과기를 부호화합니다. 이들의 발현은 CD8+ T 클러스터에 국한되며, 이는 항종양 세포독성 활성과 소진 분석에서 게이팅하게 되는 바로 그 영역입니다.",
      en: "CD8A/CD8B encode the CD8 co-receptor; GZMK is a cytotoxic effector. Their expression is confined to the CD8+ T cluster — the exact region you'd gate for anti-tumor cytotoxic activity and exhaustion analysis.",
    },
    check: (s) => s.colorMode === "gene" && ["CD8A", "CD8B", "GZMK"].includes(s.gene ?? ""),
    answer: { kind: "gene", gene: "CD8A" },
  },
  {
    id: "treg",
    prompt: {
      ko: "Treg는 면역억제성이며 NSCLC에서 임상적으로 중요합니다. 조절 T세포의 계통 결정 전사인자로 색칠하세요.",
      en: "Tregs are immunosuppressive and clinically important in NSCLC. Color by the lineage-defining transcription factor of regulatory T cells.",
    },
    hint: {
      ko: "forkhead-box 전사인자입니다 — Treg 프로그램의 master regulator.",
      en: "It's a forkhead-box transcription factor — the master regulator of the Treg program.",
    },
    explanation: {
      ko: "FOXP3는 Treg의 master 전사인자입니다. 완전히 분리된 섬이 아니라 CD4+ T 영역 안의 작은 부분집단을 표시한다는 점에 주목하세요 — 관련된 상태를 분해하려면 sub-clustering이 자주 필요한 이유의 좋은 예입니다.",
      en: "FOXP3 is the master transcription factor of Tregs. Note it marks a small subset within the CD4+ T region, not a fully separate island — a good example of why sub-clustering is often needed to resolve related states.",
    },
    check: (s) => s.colorMode === "gene" && s.gene === "FOXP3",
    answer: { kind: "gene", gene: "FOXP3" },
  },
  {
    id: "prolif",
    prompt: {
      ko: "어느 구획이 활발히 증식하고 있나요? 세포주기/증식 마커로 색칠하고 어디에 집중되는지 보세요.",
      en: "Which compartment is actively proliferating? Color by a cell-cycle / proliferation marker and see where it concentrates.",
    },
    hint: {
      ko: "대표적인 증식 마커로 MKI67(Ki-67)과 TOP2A가 있습니다.",
      en: "Classic proliferation markers include MKI67 (Ki-67) and TOP2A.",
    },
    explanation: {
      ko: "MKI67과 TOP2A는 분열 중인 세포를 표시합니다. 이 아틀라스에서 신호는 악성 상피 클러스터에 집중됩니다 — 통제되지 않은 증식은 종양 구획의 대표적 특징이며, 추정 CNV로 이들이 이수성 세포임을 확인할 수 있습니다.",
      en: "MKI67 and TOP2A mark cycling cells. In this atlas the signal concentrates in the malignant epithelial cluster — uncontrolled proliferation is a defining hallmark of the tumor compartment, and inferred CNV would confirm these are the aneuploid cells.",
    },
    check: (s) => s.colorMode === "gene" && ["MKI67", "TOP2A"].includes(s.gene ?? ""),
    answer: { kind: "gene", gene: "MKI67" },
  },
  {
    id: "immune",
    prompt: {
      ko: "면역 구획을 상피+기질 세포와 가장 잘 분리하는 단일 유전자를 찾으세요.",
      en: "Find the single gene that best separates the immune compartment from the epithelial + stromal cells.",
    },
    hint: {
      ko: "CD45로 더 잘 알려진, 범-백혈구 표면 phosphatase를 부호화합니다.",
      en: "It encodes the pan-leukocyte surface phosphatase, better known as CD45.",
    },
    explanation: {
      ko: "PTPRC(CD45)는 사실상 모든 백혈구에서 발현되고 상피·섬유아·내피 세포에는 없습니다. 대부분의 주석 전략이 처음으로 하는 분할입니다: 면역 대 비면역.",
      en: "PTPRC (CD45) is expressed across essentially all leukocytes and absent from epithelial, fibroblast, and endothelial cells. It's the first split most annotation strategies make: immune vs. non-immune.",
    },
    check: (s) => s.colorMode === "gene" && s.gene === "PTPRC",
    answer: { kind: "gene", gene: "PTPRC" },
  },
  {
    id: "isolate",
    prompt: {
      ko: "범례를 사용해 악성 상피세포를 강조하고, 정상 폐포 상피세포에 대해 어디에 위치하는지 관찰하세요.",
      en: "Isolate the malignant epithelial cells using the legend, and observe where they sit relative to normal alveolar epithelial cells.",
    },
    hint: {
      ko: "사이드바 범례에서 세포 유형을 클릭하면 나머지가 흐려집니다.",
      en: "Click a cell type in the sidebar legend to dim everything else.",
    },
    explanation: {
      ko: "악성 및 폐포 상피세포는 둘 다 EPCAM+이고 서로 가까이 있지만 뚜렷한 클러스터를 형성합니다 — 악성 형질전환(및 CNV)이 만드는 전사체 거리가 이들을 분리합니다. 이 둘을 구별하는 것이 바로 악성세포 판별 문제(inferCNV / CopyKAT)입니다.",
      en: "Malignant and alveolar epithelial cells are both EPCAM+ and sit near each other, yet form distinct clusters — the transcriptional distance driven by malignant transformation (and CNV) is what separates them. Distinguishing the two is exactly the malignant-cell-calling problem (inferCNV / CopyKAT).",
    },
    check: (s, ids) => s.highlight === ids["Malignant epithelial"],
    answer: { kind: "highlight", cellType: "Malignant epithelial" },
  },
  {
    id: "composition",
    prompt: {
      ko: "개념 문제: 조성 막대는 종양 조직에서 악성세포가 확장됨을 보여줍니다. 겉보기 세포 유형 비율을 부풀리거나 줄일 수 있는 기술적 아티팩트를 하나 드세요.",
      en: "Conceptual: the composition bars show malignant cells expanding in tumor tissue. Name one technical artifact that could inflate or deflate an apparent cell-type proportion.",
    },
    hint: {
      ko: "조직 해리 과정에서 세포가 물리적으로 어떻게 되는지 생각해 보세요.",
      en: "Think about what happens to cells physically during tissue dissociation.",
    },
    explanation: {
      ko: "해리 편향(호중구·상피 같은 취약 세포는 손실되고 강인한 세포는 농축됨), 단일세포 대 단일핵 프로토콜 차이, 주변 RNA, doublet이 모두 비율을 왜곡합니다. 그래서 조성 변화는 가설로 다루고 scCODA나 Milo 같은 방법으로 분석해야 합니다.",
      en: "Dissociation bias (fragile cells like neutrophils/epithelium are lost, robust cells enriched), single-cell vs single-nucleus protocol differences, ambient RNA, and doublets all distort proportions. This is why compositional shifts should be treated as hypotheses and analyzed with methods like scCODA or Milo.",
    },
  },
  {
    id: "umap-trap",
    prompt: {
      ko: "개념 문제: 한 학생이 UMAP 양 끝의 두 클러스터가 인접한 두 클러스터보다 ‘두 배 더 다르다’고 주장합니다. 이 추론이 왜 잘못되었나요?",
      en: "Conceptual: a student claims two clusters on opposite sides of the UMAP are 'twice as different' as two adjacent clusters. Why is this reasoning flawed?",
    },
    hint: {
      ko: "UMAP이 보존하는 것 — 그리고 보존하지 않는 것 — 을 생각해 보세요.",
      en: "Consider what UMAP preserves — and what it does not.",
    },
    explanation: {
      ko: "UMAP은 전역 거리가 아니라 국소 이웃을 보존합니다. 클러스터 사이 공간과 축 단위는 정량적이지 않으므로 레이아웃에서 차이의 크기를 읽어낼 수 없습니다. 대신 발현 통계나 PCA 공간에서의 거리로 차이를 정량화하세요.",
      en: "UMAP preserves local neighborhoods, not global distances. The space between clusters and the axis units are not quantitative, so you cannot read magnitude of difference off the layout. Quantify differences with expression statistics or distances in PCA space instead.",
    },
  },
];

export default function Exercises({ state, cellTypeIdByName, onApply }: Props) {
  const { lang } = useLang();
  const [openHint, setOpenHint] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  const solvedCount = EXERCISES.filter(
    (e) => e.check && e.check(state, cellTypeIdByName),
  ).length;
  const checkable = EXERCISES.filter((e) => e.check).length;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-slate-500">{tr(UI.exIntro, lang)}</p>
        <span className="rounded-full bg-slate-800 px-2.5 py-1 text-[11px] font-mono text-slate-300">
          {solvedCount}/{checkable} {tr(UI.solved, lang)}
        </span>
      </div>

      <ol className="flex flex-col gap-2.5">
        {EXERCISES.map((e, i) => {
          const solved = e.check ? e.check(state, cellTypeIdByName) : false;
          const isReveal = !e.check;
          return (
            <li
              key={e.id}
              className={`rounded-lg border p-3 transition ${
                solved
                  ? "border-emerald-600/60 bg-emerald-950/20"
                  : "border-slate-800 bg-slate-900/50"
              }`}
            >
              <div className="flex items-start gap-2.5">
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                    solved
                      ? "bg-emerald-500 text-white"
                      : "bg-slate-700 text-slate-300"
                  }`}
                >
                  {solved ? "✓" : i + 1}
                </span>
                <div className="flex-1">
                  <p className="text-sm text-slate-200">{tr(e.prompt, lang)}</p>

                  <div className="mt-2 flex flex-wrap gap-3 text-[11px]">
                    <button
                      onClick={() =>
                        setOpenHint((h) => ({ ...h, [e.id]: !h[e.id] }))
                      }
                      className="text-slate-400 hover:text-slate-200"
                    >
                      {openHint[e.id] ? tr(UI.hideHint, lang) : tr(UI.hint, lang)}
                    </button>
                    {e.answer && (
                      <button
                        onClick={() => onApply(e.answer!)}
                        className="text-sky-400 hover:text-sky-300"
                      >
                        {tr(UI.showMe, lang)}
                      </button>
                    )}
                    {isReveal && (
                      <button
                        onClick={() =>
                          setRevealed((r) => ({ ...r, [e.id]: !r[e.id] }))
                        }
                        className="text-sky-400 hover:text-sky-300"
                      >
                        {revealed[e.id] ? tr(UI.hideAnswer, lang) : tr(UI.revealAnswer, lang)}
                      </button>
                    )}
                  </div>

                  {openHint[e.id] && (
                    <p className="mt-2 text-[11px] italic text-slate-500">{tr(e.hint, lang)}</p>
                  )}

                  {(solved || (isReveal && revealed[e.id])) && (
                    <p className="mt-2 rounded bg-slate-800/60 p-2 text-[11px] leading-relaxed text-slate-300">
                      {tr(e.explanation, lang)}
                    </p>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
