"use client";

import { useState } from "react";
import { CONCEPTS } from "@/lib/learn";
import { UI, useLang, tr } from "@/lib/i18n";

export default function ConceptCards() {
  const { lang } = useLang();
  const [open, setOpen] = useState<string | null>(CONCEPTS[0].id);

  return (
    <div className="flex flex-col gap-2">
      <p className="mb-1 text-xs text-slate-500">{tr(UI.conceptsIntro, lang)}</p>
      {CONCEPTS.map((c) => {
        const isOpen = open === c.id;
        return (
          <div
            key={c.id}
            className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50"
          >
            <button
              onClick={() => setOpen(isOpen ? null : c.id)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-800/50"
            >
              <span>
                <span className="block text-sm font-semibold text-slate-100">{tr(c.title, lang)}</span>
                <span className="block text-xs text-slate-500">{tr(c.summary, lang)}</span>
              </span>
              <span
                className={`shrink-0 text-slate-500 transition-transform ${
                  isOpen ? "rotate-180" : ""
                }`}
              >
                ▾
              </span>
            </button>
            {isOpen && (
              <div className="space-y-3 border-t border-slate-800 px-4 py-3 text-sm leading-relaxed text-slate-300">
                {c.body[lang].map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
