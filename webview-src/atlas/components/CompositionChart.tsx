"use client";

import { useState } from "react";
import type { AtlasMeta } from "@/lib/types";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  meta: AtlasMeta;
}

export default function CompositionChart({ meta }: Props) {
  const { lang } = useLang();
  const [mode, setMode] = useState<"condition" | "patient">("condition");

  const rows =
    mode === "condition"
      ? meta.conditions.map((label, i) => ({ label, counts: meta.composition.byCondition[i] }))
      : meta.patients.map((label, i) => ({ label, counts: meta.composition.byPatient[i] }));

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{tr(UI.compTitle, lang)}</h3>
        <div className="flex overflow-hidden rounded-md border border-slate-700 text-xs">
          {(["condition", "patient"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-2.5 py-1 ${
                mode === m ? "bg-sky-600 text-white" : "bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              {m === "condition" ? tr(UI.modeTissue, lang) : tr(UI.modePatient, lang)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {rows.map((row) => {
          const total = row.counts.reduce((a, b) => a + b, 0) || 1;
          return (
            <div key={row.label} className="flex items-center gap-2">
              <span className="w-24 shrink-0 truncate text-xs text-slate-400">{row.label}</span>
              <div className="flex h-5 flex-1 overflow-hidden rounded bg-slate-800">
                {meta.cellTypes.map((ct) => {
                  const pct = (row.counts[ct.id] / total) * 100;
                  if (pct < 0.01) return null;
                  return (
                    <div
                      key={ct.id}
                      title={`${ct.name}: ${pct.toFixed(1)}%`}
                      style={{ width: `${pct}%`, backgroundColor: ct.color }}
                    />
                  );
                })}
              </div>
              <span className="w-14 shrink-0 text-right font-mono text-[10px] text-slate-500">
                {total.toLocaleString()}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        {mode === "condition" ? tr(UI.compFooterTissue, lang) : tr(UI.compFooterPatient, lang)}
      </p>
    </div>
  );
}
