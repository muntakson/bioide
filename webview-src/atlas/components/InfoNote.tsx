"use client";

import { useState } from "react";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  title?: string;
  children: React.ReactNode;
}

/** Small collapsible "How to read this" note for interpretation guidance. */
export default function InfoNote({ title, children }: Props) {
  const { lang } = useLang();
  const [open, setOpen] = useState(false);
  const heading = title ?? tr(UI.noteHowToRead, lang);
  return (
    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] font-medium text-sky-400 hover:text-sky-300"
      >
        <span className="text-xs">{open ? "▾" : "▸"}</span>
        {heading}
      </button>
      {open && (
        <div className="px-3 pb-2 text-[11px] leading-relaxed text-slate-400">{children}</div>
      )}
    </div>
  );
}
