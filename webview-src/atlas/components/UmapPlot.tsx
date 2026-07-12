"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Atlas, ColorMode } from "@/lib/types";
import {
  conditionColor,
  categoricalColor,
  hexToRgb,
  viridis,
} from "@/lib/colors";
import { UI, useLang, tr } from "@/lib/i18n";

interface Props {
  atlas: Atlas;
  colorMode: ColorMode;
  geneIndex: number | null;
  highlightCellType: number | null;
}

interface Hover {
  screenX: number;
  screenY: number;
  cell: number;
}

interface View {
  zoom: number;
  panX: number;
  panY: number;
}

// Per-cell RGB for the current color mode (recomputed only when mode/gene changes).
function useColors(atlas: Atlas, colorMode: ColorMode, geneIndex: number | null) {
  return useMemo(() => {
    const { meta } = atlas;
    const n = meta.dataset.nCells;
    const rgb = new Uint8Array(n * 3);
    const put = (i: number, c: [number, number, number]) => {
      rgb[i * 3] = c[0];
      rgb[i * 3 + 1] = c[1];
      rgb[i * 3 + 2] = c[2];
    };
    if (colorMode === "gene" && geneIndex !== null) {
      for (let i = 0; i < n; i++) put(i, viridis(atlas.exprAt(i, geneIndex)));
    } else if (colorMode === "condition") {
      const cols = meta.conditions.map((_, i) => hexToRgb(conditionColor(i)));
      for (let i = 0; i < n; i++) put(i, cols[meta.condition[i]]);
    } else if (colorMode === "sample") {
      const cols = meta.samples.map((_, i) => hexToRgb(categoricalColor(i)));
      for (let i = 0; i < n; i++) put(i, cols[meta.sample[i]]);
    } else if (colorMode === "patient") {
      const cols = meta.patients.map((_, i) => hexToRgb(categoricalColor(i)));
      for (let i = 0; i < n; i++) put(i, cols[meta.patient[i]]);
    } else {
      const cols = meta.cellTypes.map((c) => hexToRgb(c.color));
      for (let i = 0; i < n; i++) put(i, cols[meta.cellType[i]]);
    }
    return rgb;
  }, [atlas, colorMode, geneIndex]);
}

export default function UmapPlot({
  atlas,
  colorMode,
  geneIndex,
  highlightCellType,
}: Props) {
  const { lang } = useLang();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState<View>({ zoom: 1, panX: 0, panY: 0 });
  const [hover, setHover] = useState<Hover | null>(null);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);

  const colors = useColors(atlas, colorMode, geneIndex);

  // world-space bounds
  const bounds = useMemo(() => {
    const { x, y } = atlas.meta;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < x.length; i++) {
      if (x[i] < minX) minX = x[i];
      if (x[i] > maxX) maxX = x[i];
      if (y[i] < minY) minY = y[i];
      if (y[i] > maxY) maxY = y[i];
    }
    const padX = (maxX - minX) * 0.05;
    const padY = (maxY - minY) * 0.05;
    return { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY };
  }, [atlas]);

  // world -> screen transform for current size + view
  const transform = useMemo(() => {
    const { minX, maxX, minY, maxY } = bounds;
    const wWorld = maxX - minX;
    const hWorld = maxY - minY;
    const base = Math.min(size.w / wWorld, size.h / hWorld);
    const scale = base * view.zoom;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    // note: screen y is flipped (world up = screen up)
    const toScreen = (wx: number, wy: number): [number, number] => [
      (wx - cx) * scale + size.w / 2 + view.panX,
      -(wy - cy) * scale + size.h / 2 + view.panY,
    ];
    return { scale, cx, cy, toScreen };
  }, [bounds, size, view]);

  // responsive sizing
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setSize({ w: Math.max(200, r.width), h: Math.max(200, r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);

    const { x, y, cellType } = atlas.meta;
    const n = x.length;
    const r = Math.max(1.1, 1.6 * Math.sqrt(view.zoom));
    const d = r * 2;
    const dim = highlightCellType !== null;

    // draw dimmed background points first, highlighted on top
    for (let pass = 0; pass < (dim ? 2 : 1); pass++) {
      for (let i = 0; i < n; i++) {
        const isHi = !dim || cellType[i] === highlightCellType;
        if (dim && ((pass === 0 && isHi) || (pass === 1 && !isHi))) continue;
        const [sx, sy] = transform.toScreen(x[i], y[i]);
        if (sx < -5 || sx > size.w + 5 || sy < -5 || sy > size.h + 5) continue;
        if (dim && !isHi) {
          ctx.fillStyle = "rgba(100,116,139,0.10)";
        } else {
          ctx.fillStyle = `rgb(${colors[i * 3]},${colors[i * 3 + 1]},${colors[i * 3 + 2]})`;
        }
        ctx.fillRect(sx - r, sy - r, d, d);
      }
    }

    // hover ring
    if (hover) {
      const [sx, sy] = transform.toScreen(x[hover.cell], y[hover.cell]);
      ctx.strokeStyle = "#f8fafc";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(sx, sy, r + 3, 0, Math.PI * 2);
      ctx.stroke();
    }
  }, [atlas, colors, transform, size, view.zoom, highlightCellType, hover]);

  // nearest-point pick
  const pick = useCallback(
    (mx: number, my: number): number | null => {
      const { x, y } = atlas.meta;
      let best = -1;
      let bestD = 100; // px^2 threshold
      for (let i = 0; i < x.length; i++) {
        const [sx, sy] = transform.toScreen(x[i], y[i]);
        const dx = sx - mx;
        const dy = sy - my;
        const dd = dx * dx + dy * dy;
        if (dd < bestD) {
          bestD = dd;
          best = i;
        }
      }
      return best === -1 ? null : best;
    },
    [atlas, transform],
  );

  const onMouseMove = (e: React.MouseEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    if (drag.current) {
      setView((v) => ({
        ...v,
        panX: drag.current!.panX + (e.clientX - drag.current!.x),
        panY: drag.current!.panY + (e.clientY - drag.current!.y),
      }));
      return;
    }
    const cell = pick(mx, my);
    setHover(cell === null ? null : { screenX: mx, screenY: my, cell });
  };

  const onWheel = (e: React.WheelEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    setView((v) => {
      const newZoom = Math.max(0.5, Math.min(40, v.zoom * factor));
      const k = newZoom / v.zoom;
      // keep the point under the cursor fixed
      return {
        zoom: newZoom,
        panX: mx - (mx - (size.w / 2 + v.panX)) * k - size.w / 2,
        panY: my - (my - (size.h / 2 + v.panY)) * k - size.h / 2,
      };
    });
  };

  const onMouseDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, panX: view.panX, panY: view.panY };
    setHover(null);
  };
  const endDrag = () => (drag.current = null);
  const reset = () => setView({ zoom: 1, panX: 0, panY: 0 });

  const m = atlas.meta;
  const hoverCell = hover?.cell ?? null;

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden rounded-lg bg-slate-950">
      <canvas
        ref={canvasRef}
        style={{ width: size.w, height: size.h, cursor: drag.current ? "grabbing" : "crosshair" }}
        onMouseMove={onMouseMove}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseUp={endDrag}
        onMouseLeave={() => {
          endDrag();
          setHover(null);
        }}
      />

      {/* controls */}
      <div className="absolute right-3 top-3 flex flex-col gap-1">
        <button
          onClick={() => setView((v) => ({ ...v, zoom: Math.min(40, v.zoom * 1.3) }))}
          className="h-8 w-8 rounded bg-slate-800/90 text-lg text-slate-100 hover:bg-slate-700"
          aria-label={tr(UI.zoomIn, lang)}
        >
          +
        </button>
        <button
          onClick={() => setView((v) => ({ ...v, zoom: Math.max(0.5, v.zoom / 1.3) }))}
          className="h-8 w-8 rounded bg-slate-800/90 text-lg text-slate-100 hover:bg-slate-700"
          aria-label={tr(UI.zoomOut, lang)}
        >
          −
        </button>
        <button
          onClick={reset}
          className="h-8 w-8 rounded bg-slate-800/90 text-xs text-slate-100 hover:bg-slate-700"
          aria-label={tr(UI.resetView, lang)}
        >
          ⟳
        </button>
      </div>

      {/* gene colorbar */}
      {colorMode === "gene" && geneIndex !== null && (
        <div className="absolute bottom-3 left-3 rounded bg-slate-900/80 p-2 text-[10px] text-slate-200">
          <div className="mb-1 font-mono">{m.genes[geneIndex]} {tr(UI.exprWord, lang)}</div>
          <div className="flex items-center gap-2">
            <span>{tr(UI.low, lang)}</span>
            <div
              className="h-2 w-28 rounded"
              style={{
                background:
                  "linear-gradient(to right, rgb(68,1,84), rgb(49,104,142), rgb(31,158,137), rgb(181,222,43), rgb(253,231,37))",
              }}
            />
            <span>{tr(UI.high, lang)}</span>
          </div>
        </div>
      )}

      {/* tooltip */}
      {hoverCell !== null && (
        <div
          className="pointer-events-none absolute z-10 max-w-[220px] rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs text-slate-100 shadow-lg"
          style={{
            left: Math.min(hover!.screenX + 12, size.w - 200),
            top: Math.min(hover!.screenY + 12, size.h - 90),
          }}
        >
          <div className="flex items-center gap-1.5 font-semibold">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: m.cellTypes[m.cellType[hoverCell]].color }}
            />
            {m.cellTypes[m.cellType[hoverCell]].name}
          </div>
          <div className="mt-1 text-slate-400">
            {tr(UI.hoverSample, lang)}: <span className="text-slate-200">{m.samples[m.sample[hoverCell]]}</span>
          </div>
          <div className="text-slate-400">
            {tr(UI.hoverTissue, lang)}: <span className="text-slate-200">{m.conditions[m.condition[hoverCell]]}</span>
          </div>
          {colorMode === "gene" && geneIndex !== null && (
            <div className="text-slate-400">
              {m.genes[geneIndex]}:{" "}
              <span className="font-mono text-slate-200">
                {atlas.exprAt(hoverCell, geneIndex).toFixed(2)}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="pointer-events-none absolute bottom-2 right-3 text-[10px] text-slate-500">
        {tr(UI.zoomHint, lang)} · {m.dataset.nCells.toLocaleString()} {tr(UI.cells, lang)}
      </div>
    </div>
  );
}
