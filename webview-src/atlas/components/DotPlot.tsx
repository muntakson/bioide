"use client";

import { useMemo } from "react";
import type { AtlasMeta } from "@/lib/types";
import { viridisCss } from "@/lib/colors";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  meta: AtlasMeta;
  onPickGene?: (geneIndex: number) => void;
}

/**
 * Marker dot plot: rows = cell types, columns = genes.
 * Dot size = % of cells expressing; dot color = mean expression
 * (min-max scaled per gene across cell types, the standard scanpy dotplot).
 */
export default function DotPlot({ meta, onPickGene }: Props) {
  const { lang } = useLang();
  const { mean, pct } = meta.dotPlot;
  const genes = meta.genes;

  // per-gene (column) min-max scaling of mean expression for color
  const scaled = useMemo(() => {
    const nCT = meta.cellTypes.length;
    const out: number[][] = mean.map((r) => r.slice());
    for (let g = 0; g < genes.length; g++) {
      let lo = Infinity, hi = -Infinity;
      for (let c = 0; c < nCT; c++) {
        const v = mean[c][g];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      const span = hi - lo || 1;
      for (let c = 0; c < nCT; c++) out[c][g] = (mean[c][g] - lo) / span;
    }
    return out;
  }, [mean, genes.length, meta.cellTypes.length]);

  const cell = 22; // px per column
  const rowH = 26;
  const labelW = 140;
  const width = labelW + genes.length * cell + 10;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{tr(UI.dotTitle, lang)}</h3>
        <div className="flex items-center gap-3 text-[10px] text-slate-400">
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-16 rounded"
              style={{
                background:
                  "linear-gradient(to right, rgb(68,1,84), rgb(31,158,137), rgb(253,231,37))",
              }}
            />
            {tr(UI.meanExpr, lang)}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-400" />
            <span className="inline-block h-3 w-3 rounded-full bg-slate-400" />
            {tr(UI.pctExpressing, lang)}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <svg width={width} height={meta.cellTypes.length * rowH + 70} className="select-none">
          {/* gene labels (rotated) */}
          {genes.map((g, gi) => (
            <text
              key={g}
              x={labelW + gi * cell + cell / 2}
              y={54}
              transform={`rotate(-55 ${labelW + gi * cell + cell / 2} 54)`}
              className="cursor-pointer fill-slate-400 text-[9px] font-mono hover:fill-sky-400"
              textAnchor="start"
              onClick={() => onPickGene?.(gi)}
            >
              {g}
            </text>
          ))}
          {/* rows */}
          {meta.cellTypes.map((ct, ci) => {
            const y = 70 + ci * rowH;
            return (
              <g key={ct.id}>
                <text x={labelW - 8} y={y + 4} textAnchor="end" className="fill-slate-300 text-[10px]">
                  {ct.name}
                </text>
                <circle cx={labelW - labelW + 6} cy={y} r={0} />
                {genes.map((g, gi) => {
                  const p = pct[ci][gi];
                  const r = Math.max(0.5, (p / 100) * (cell / 2 - 1));
                  return (
                    <circle
                      key={g}
                      cx={labelW + gi * cell + cell / 2}
                      cy={y}
                      r={r}
                      fill={viridisCss(scaled[ci][gi])}
                    >
                      <title>
                        {ct.name} · {g}: {mean[ci][gi].toFixed(2)} mean, {p.toFixed(0)}% expressing
                      </title>
                    </circle>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{tr(UI.dotFooter, lang)}</p>
    </div>
  );
}
