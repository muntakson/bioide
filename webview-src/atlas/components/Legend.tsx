"use client";

import type { CellType } from "@/lib/types";

interface Props {
  cellTypes: CellType[];
  counts: number[]; // per cell type
  highlight: number | null;
  onHighlight: (id: number | null) => void;
}

export default function Legend({ cellTypes, counts, highlight, onHighlight }: Props) {
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="flex flex-col gap-0.5">
      {cellTypes.map((ct) => {
        const active = highlight === ct.id;
        const dim = highlight !== null && !active;
        return (
          <button
            key={ct.id}
            onClick={() => onHighlight(active ? null : ct.id)}
            className={`flex items-center justify-between rounded px-2 py-1 text-left text-xs transition ${
              active ? "bg-slate-700" : "hover:bg-slate-800"
            } ${dim ? "opacity-40" : ""}`}
          >
            <span className="flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 shrink-0 rounded-sm"
                style={{ backgroundColor: ct.color }}
              />
              <span className="text-slate-200">{ct.name}</span>
            </span>
            <span className="font-mono text-[10px] text-slate-500">
              {((counts[ct.id] / total) * 100).toFixed(1)}%
            </span>
          </button>
        );
      })}
    </div>
  );
}
