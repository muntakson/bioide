"use client";

import { useEffect, useMemo, useState } from "react";
import type { Atlas, ColorMode } from "@/lib/types";
import type { LearnAction } from "@/lib/learn";
import { loadAtlas } from "@/lib/data";
import UmapPlot from "@/components/UmapPlot";
import GeneSearch from "@/components/GeneSearch";
import Legend from "@/components/Legend";
import CompositionChart from "@/components/CompositionChart";
import DotPlot from "@/components/DotPlot";
import Walkthrough from "@/components/Walkthrough";
import ConceptCards from "@/components/ConceptCards";
import Exercises from "@/components/Exercises";
import InfoNote from "@/components/InfoNote";
import { LangProvider, useLang, UI, tr } from "@/lib/i18n";

const CATEGORY_MODES: { id: ColorMode; key: keyof typeof UI }[] = [
  { id: "cellType", key: "modeCellType" },
  { id: "condition", key: "modeTissue" },
  { id: "patient", key: "modePatient" },
  { id: "sample", key: "modeSample" },
];

type Tab = "analysis" | "concepts" | "exercises";

export default function Home() {
  return (
    <LangProvider>
      <AtlasApp />
    </LangProvider>
  );
}

function AtlasApp() {
  const { lang, setLang } = useLang();
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [colorMode, setColorMode] = useState<ColorMode>("cellType");
  const [geneIndex, setGeneIndex] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("analysis");
  const [tourOpen, setTourOpen] = useState(false);

  useEffect(() => {
    loadAtlas().then(setAtlas).catch((e) => setError(String(e)));
  }, []);

  // open the guided tour automatically on first visit
  useEffect(() => {
    if (!atlas) return;
    try {
      if (!localStorage.getItem("nsclc-tour-seen")) {
        setTourOpen(true);
        localStorage.setItem("nsclc-tour-seen", "1");
      }
    } catch {
      /* localStorage unavailable — skip auto-open */
    }
  }, [atlas]);

  const counts = useMemo(() => {
    if (!atlas) return [];
    const n = atlas.meta.cellTypes.length;
    const out = new Array(n).fill(0);
    for (const row of atlas.meta.composition.byCondition)
      row.forEach((v, i) => (out[i] += v));
    return out;
  }, [atlas]);

  const cellTypeIdByName = useMemo(() => {
    const map: Record<string, number> = {};
    atlas?.meta.cellTypes.forEach((c) => (map[c.name] = c.id));
    return map;
  }, [atlas]);

  const pickGene = (i: number | null) => {
    if (i === null) {
      setGeneIndex(null);
      if (colorMode === "gene") setColorMode("cellType");
    } else {
      setGeneIndex(i);
      setColorMode("gene");
    }
  };

  const pickCategory = (mode: ColorMode) => {
    setColorMode(mode);
    setGeneIndex(null);
  };

  // apply an action from the tour / exercises to the live app
  const applyAction = (a: LearnAction) => {
    if (!atlas) return;
    if (a.kind === "mode") {
      setColorMode(a.mode);
      if (a.mode !== "gene") setGeneIndex(null);
    } else if (a.kind === "gene") {
      const idx = atlas.meta.genes.indexOf(a.gene);
      if (idx >= 0) {
        setGeneIndex(idx);
        setColorMode("gene");
      }
    } else if (a.kind === "highlight") {
      const id = cellTypeIdByName[a.cellType];
      if (id !== undefined) setHighlight(id);
    } else if (a.kind === "clear") {
      setColorMode("cellType");
      setGeneIndex(null);
      setHighlight(null);
    }
  };

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center p-6 text-center text-sm text-red-400">
        {tr(UI.loadFail, lang)}{error}
      </div>
    );
  }

  if (!atlas) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-slate-400">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-sky-500" />
        <p className="text-sm">{tr(UI.loading, lang)}</p>
      </div>
    );
  }

  const m = atlas.meta;
  const geneName = geneIndex !== null ? m.genes[geneIndex] : null;

  return (
    <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col">
      <Walkthrough open={tourOpen} onClose={() => setTourOpen(false)} onAction={applyAction} />

      {/* header */}
      <header className="border-b border-slate-800 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-50">
              NSCLC <span className="text-sky-400">Atlas</span>
            </h1>
            <p className="text-xs text-slate-400">{tr(UI.subtitle, lang)}</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex gap-4 text-right text-xs text-slate-400">
              <div>
                <div className="font-mono text-base text-slate-100">
                  {m.dataset.nCells.toLocaleString()}
                </div>
                {tr(UI.cells, lang)}
              </div>
              <div>
                <div className="font-mono text-base text-slate-100">{m.cellTypes.length}</div>
                {tr(UI.cellTypesStat, lang)}
              </div>
              <div>
                <div className="font-mono text-base text-slate-100">{m.genes.length}</div>
                {tr(UI.genes, lang)}
              </div>
            </div>
            {/* KR / EN language toggle (Korean default) */}
            <div className="flex overflow-hidden rounded-lg border border-slate-700 text-xs font-medium">
              {(["ko", "en"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-2.5 py-1.5 ${
                    lang === l
                      ? "bg-sky-600 text-white"
                      : "bg-slate-900 text-slate-400 hover:bg-slate-800"
                  }`}
                >
                  {l === "ko" ? "한국어" : "EN"}
                </button>
              ))}
            </div>
            <button
              onClick={() => setTourOpen(true)}
              className="flex h-9 items-center gap-1.5 rounded-lg border border-sky-700 bg-sky-600/20 px-3 text-sm font-medium text-sky-300 hover:bg-sky-600/30"
            >
              <span className="text-base leading-none">?</span> {tr(UI.guidedTour, lang)}
            </button>
          </div>
        </div>
      </header>

      {/* main grid */}
      <div className="grid flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* sidebar */}
        <aside className="flex flex-col gap-5">
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {tr(UI.colorCellsBy, lang)}
            </h2>
            <div className="grid grid-cols-2 gap-1.5">
              {CATEGORY_MODES.map((c) => (
                <button
                  key={c.id}
                  onClick={() => pickCategory(c.id)}
                  className={`rounded-md border px-2 py-1.5 text-xs transition ${
                    colorMode === c.id
                      ? "border-sky-500 bg-sky-600/20 text-sky-300"
                      : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {tr(UI[c.key], lang)}
                </button>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {tr(UI.geneExpr, lang)}
            </h2>
            <GeneSearch genes={m.genes} selected={geneIndex} onSelect={pickGene} />
            {geneName && (
              <p className="mt-2 text-[11px] text-slate-500">
                {tr(UI.umapColoredPre, lang)}
                <span className="font-mono text-sky-400">{geneName}</span>
                {tr(UI.umapColoredPost, lang)}
              </p>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {tr(UI.cellTypesTitle, lang)}{" "}
              <span className="normal-case text-slate-600">{tr(UI.clickToIsolate, lang)}</span>
            </h2>
            <Legend
              cellTypes={m.cellTypes}
              counts={counts}
              highlight={highlight}
              onHighlight={setHighlight}
            />
          </section>
        </aside>

        {/* plot + panels */}
        <main className="flex flex-col gap-4">
          <div>
            <div className="h-[52vh] min-h-[360px] rounded-xl border border-slate-800 bg-slate-950 p-1">
              <UmapPlot
                atlas={atlas}
                colorMode={colorMode}
                geneIndex={geneIndex}
                highlightCellType={highlight}
              />
            </div>
            <InfoNote>{tr(UI.umapNote, lang)}</InfoNote>
          </div>

          {/* tabs */}
          <div className="flex gap-1 border-b border-slate-800">
            {([
              ["analysis", tr(UI.tabAnalysis, lang)],
              ["concepts", tr(UI.tabConcepts, lang)],
              ["exercises", tr(UI.tabExercises, lang)],
            ] as [Tab, string][]).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
                  tab === id
                    ? "border-sky-500 text-sky-300"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "analysis" && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <CompositionChart meta={m} />
                <InfoNote>{tr(UI.compositionNote, lang)}</InfoNote>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <DotPlot meta={m} onPickGene={pickGene} />
                <InfoNote>{tr(UI.dotplotNote, lang)}</InfoNote>
              </div>
            </div>
          )}

          {tab === "concepts" && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <ConceptCards />
            </div>
          )}

          {tab === "exercises" && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <Exercises
                state={{ colorMode, gene: geneName, highlight }}
                cellTypeIdByName={cellTypeIdByName}
                onApply={applyAction}
              />
            </div>
          )}
        </main>
      </div>

      <footer className="border-t border-slate-800 px-5 py-3 text-center text-[11px] text-slate-600">
        {tr(UI.footer, lang)}
      </footer>
    </div>
  );
}
