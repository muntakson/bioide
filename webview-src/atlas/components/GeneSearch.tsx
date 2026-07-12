"use client";

import { useMemo, useState } from "react";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  genes: string[];
  selected: number | null;
  onSelect: (geneIndex: number | null) => void;
}

export default function GeneSearch({ genes, selected, onSelect }: Props) {
  const { lang } = useLang();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return genes.map((g, i) => ({ g, i })).slice(0, 12);
    return genes
      .map((g, i) => ({ g, i }))
      .filter(({ g }) => g.toUpperCase().includes(q))
      .slice(0, 12);
  }, [query, genes]);

  const choose = (i: number) => {
    onSelect(i);
    setQuery(genes[i]);
    setOpen(false);
  };

  return (
    <div className="relative">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={tr(UI.searchPlaceholder, lang)}
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-sky-500"
        />
        {selected !== null && (
          <button
            onClick={() => {
              onSelect(null);
              setQuery("");
            }}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 text-xs text-slate-300 hover:bg-slate-700"
          >
            {tr(UI.clear, lang)}
          </button>
        )}
      </div>

      {open && matches.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-md border border-slate-700 bg-slate-900 py-1 text-sm shadow-xl">
          {matches.map(({ g, i }) => (
            <li key={g}>
              <button
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(i)}
                className={`block w-full px-3 py-1.5 text-left font-mono hover:bg-slate-800 ${
                  i === selected ? "text-sky-400" : "text-slate-200"
                }`}
              >
                {g}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
