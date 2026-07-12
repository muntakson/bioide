// Shared types for the NSCLC Atlas.

export interface CellType {
  id: number;
  name: string;
  color: string;
}

export interface AtlasMeta {
  dataset: {
    name: string;
    description: string;
    nCells: number;
    nGenes: number;
  };
  cellTypes: CellType[];
  conditions: string[]; // ["Normal", "Tumor"]
  patients: string[];
  samples: string[];
  genes: string[];
  markerGenes: Record<string, string[]>; // cellTypeName -> [gene]
  x: number[];
  y: number[];
  cellType: number[]; // per-cell index into cellTypes
  condition: number[]; // per-cell 0/1
  sample: number[]; // per-cell index into samples
  patient: number[]; // per-cell index into patients
  dotPlot: {
    mean: number[][]; // [cellType][gene]
    pct: number[][]; // [cellType][gene] percent expressing
  };
  composition: {
    byCondition: number[][]; // [condition][cellType] counts
    byPatient: number[][]; // [patient][cellType] counts
  };
}

export interface Atlas {
  meta: AtlasMeta;
  /** per-gene min-max normalized expression, uint8, row-major (cell*nGenes+gene) */
  expr: Uint8Array;
  /** normalized expression value in [0,1] for a cell/gene */
  exprAt(cellIndex: number, geneIndex: number): number;
}

export type ColorMode = "cellType" | "condition" | "sample" | "patient" | "gene";
