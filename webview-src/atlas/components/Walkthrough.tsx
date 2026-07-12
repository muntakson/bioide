"use client";

import { useEffect, useState } from "react";
import { TOUR, type LearnAction } from "@/lib/learn";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  open: boolean;
  onClose: () => void;
  onAction: (a: LearnAction) => void;
}

export default function Walkthrough({ open, onClose, onAction }: Props) {
  const { lang } = useLang();
  const [step, setStep] = useState(0);

  // apply the step's demo action whenever the visible step changes
  useEffect(() => {
    if (!open) return;
    const a = TOUR[step].action;
    if (a) onAction(a);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, step]);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!open) return null;
  const s = TOUR[step];
  const last = step === TOUR.length - 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-sky-400">
            {tr(UI.guidedTour, lang)} · {step + 1} / {TOUR.length}
          </span>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-200"
            aria-label={tr(UI.closeTour, lang)}
          >
            ✕
          </button>
        </div>

        <h2 className="mb-2 text-lg font-bold text-slate-50">{tr(s.title, lang)}</h2>
        <p className="text-sm leading-relaxed text-slate-300">{tr(s.body, lang)}</p>

        {/* progress dots */}
        <div className="mt-5 flex items-center gap-1.5">
          {TOUR.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-6 bg-sky-500" : "w-1.5 bg-slate-600 hover:bg-slate-500"
              }`}
              aria-label={`Go to step ${i + 1}`}
            />
          ))}
        </div>

        <div className="mt-5 flex items-center justify-between">
          <button
            onClick={onClose}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            {tr(UI.skipTour, lang)}
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep((s) => s - 1)}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
              >
                {tr(UI.back, lang)}
              </button>
            )}
            <button
              onClick={() => (last ? onClose() : setStep((s) => s + 1))}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500"
            >
              {last ? tr(UI.startExploring, lang) : tr(UI.next, lang)}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
