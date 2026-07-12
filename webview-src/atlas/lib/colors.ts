// Color helpers for categorical labels and continuous (gene) overlays.

// A qualitative palette used for samples / patients (cell types carry their own).
export const CATEGORICAL_PALETTE = [
  "#4363d8", "#e6194B", "#3cb44b", "#f58231", "#911eb4", "#42d4f4",
  "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9A6324",
  "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
];

export function categoricalColor(index: number): string {
  return CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length];
}

// Two-condition palette (Normal vs Tumor). Real datasets may have more than two
// conditions (e.g. biopsy sites), so fall back to the categorical palette.
export const CONDITION_COLORS = ["#38bdf8", "#ef4444"];

export function conditionColor(index: number): string {
  return CONDITION_COLORS[index] ?? categoricalColor(index);
}

/**
 * Viridis-like sequential colormap for continuous gene expression.
 * t in [0,1] -> [r,g,b].
 */
const VIRIDIS: [number, number, number][] = [
  [68, 1, 84],
  [72, 40, 120],
  [62, 74, 137],
  [49, 104, 142],
  [38, 130, 142],
  [31, 158, 137],
  [53, 183, 121],
  [110, 206, 88],
  [181, 222, 43],
  [253, 231, 37],
];

export function viridis(t: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t)) * (VIRIDIS.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const a = VIRIDIS[i];
  const b = VIRIDIS[Math.min(i + 1, VIRIDIS.length - 1)];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

export function viridisCss(t: number): string {
  const [r, g, b] = viridis(t);
  return `rgb(${r},${g},${b})`;
}

// Parse "#rrggbb" -> [r,g,b].
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}
