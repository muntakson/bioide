import type { Atlas, AtlasMeta } from "./types";

let cached: Promise<Atlas> | null = null;

// In the VS Code / code-server webview the atlas is served from extension media
// URIs injected on `window.__ATLAS__`, not from a web root. Fall back to the
// Next.js `/data/*` paths so `npm run dev` on the standalone app still works.
declare global {
  interface Window {
    __ATLAS__?: { metaUri: string; exprUri: string };
  }
}

/** Load meta.json + expr.bin once and cache the result. */
export function loadAtlas(): Promise<Atlas> {
  if (cached) return cached;
  const cfg = typeof window !== "undefined" ? window.__ATLAS__ : undefined;
  const metaUrl = cfg?.metaUri ?? "/data/meta.json";
  const exprUrl = cfg?.exprUri ?? "/data/expr.bin";
  cached = (async () => {
    const [metaRes, exprRes] = await Promise.all([
      fetch(metaUrl),
      fetch(exprUrl),
    ]);
    if (!metaRes.ok) throw new Error("Failed to load meta.json");
    if (!exprRes.ok) throw new Error("Failed to load expr.bin");
    const meta = (await metaRes.json()) as AtlasMeta;
    const buf = await exprRes.arrayBuffer();
    const expr = new Uint8Array(buf);
    const nGenes = meta.dataset.nGenes;
    return {
      meta,
      expr,
      exprAt: (cell: number, gene: number) => expr[cell * nGenes + gene] / 255,
    } satisfies Atlas;
  })();
  return cached;
}
