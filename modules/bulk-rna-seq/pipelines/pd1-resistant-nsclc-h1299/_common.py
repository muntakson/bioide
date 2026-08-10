"""
Shared helpers + the submitted report's reference values for the H1299-P3
independent reproduction. Everything the pipeline needs to (a) locate the vendor
xlsx from the LLMwiki, (b) run a self-contained limma-style moderated t-test, and
(c) score reproduction against Prof. 박상민's report lives here — no TypeScript,
no internet, no author fold-change/padj is consumed as ground truth.

BioIDE constitution §1·2: we re-derive from the count matrix; the report values
below are used ONLY to CHECK agreement, never fed into the analysis.
"""
from __future__ import annotations
import os, glob
import numpy as np

# Korean-capable figures: the system Noto CJK .ttc registers under a single
# family name (often "Noto Sans CJK JP") but its glyph set covers Hangul, so we
# pick whichever CJK family matplotlib actually has. Applied on import; scripts
# import _common after pyplot, so this takes effect for all subsequent plotting.
try:
    import matplotlib
    from matplotlib import font_manager as _fm
    for _p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        try:
            _fm.fontManager.addfont(_p)
        except Exception:
            pass
    _have = {f.name for f in _fm.fontManager.ttflist}
    for _f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic", "Noto Sans CJK SC"):
        if _f in _have:
            matplotlib.rcParams["font.family"] = _f
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
except Exception:
    pass

# ---------------------------------------------------------------------------
# Results dir (GHBIO_RESULTS is load-bearing — see CLAUDE.md)
# ---------------------------------------------------------------------------
RESULTS = os.environ.get("GHBIO_RESULTS") or os.path.expanduser("~/ghbio-tutorial/results")
os.makedirs(RESULTS, exist_ok=True)

# Heavy shared input (the 78 MB xlsx + its gene-level cache) lives under
# ~/ghbio-tutorial/data so it is fetched/parsed once and reused idempotently.
DATA_DIR = os.path.expanduser("~/ghbio-tutorial/data/pd1-h1299")
os.makedirs(DATA_DIR, exist_ok=True)
XLSX_CACHE = os.path.join(DATA_DIR, "mRNA-Seq_isoform_report.xlsx")
COUNTS_CACHE = os.path.join(DATA_DIR, "counts_gene.csv")

# ---------------------------------------------------------------------------
# Sample / group design (already labeled in the vendor "Group" sheet)
#   raw-count columns are, in order: P0_TC1, P0_TC2, P0_TD, P3_TC1, P3_TC2, P3_TD
# ---------------------------------------------------------------------------
SAMPLES = ["P0_TC1", "P0_TC2", "P0_TD", "P3_TC1", "P3_TC2", "P3_TD"]
GROUPS = {  # group -> column indices into SAMPLES
    "P0C": [0, 1],  # parental, vehicle   (sensitive control)
    "P0D": [2],     # parental, anti-PD-1 (sensitive drug)
    "P3C": [3, 4],  # resistant, vehicle  (resistant control)
    "P3D": [5],     # resistant, anti-PD-1(resistant drug)
}
SAMPLE_GROUP = {"P0_TC1": "P0C", "P0_TC2": "P0C", "P0_TD": "P0D",
                "P3_TC1": "P3C", "P3_TC2": "P3C", "P3_TD": "P3D"}


def find_xlsx() -> str:
    """Locate the vendor isoform xlsx. Priority: env override, on-disk cache,
    then a glob sweep of the LLMwiki PD-1 folder and other likely locations."""
    env = os.environ.get("PD1_XLSX")
    if env and os.path.exists(os.path.expanduser(env)):
        return os.path.expanduser(env)
    if os.path.exists(XLSX_CACHE):
        return XLSX_CACHE
    roots = [
        "~/ghbio-coscientist/PD-1", "~/llmwiki/PD-1", "~/llmwiki/data/PD-1",
        "~/llmwiki", "~/ghbio-coscientist", "~/PD-1",
    ]
    pats = ["mRNA-Seq_Report_isoform*.xlsx", "mRNA-Seq*isoform*.xlsx", "*isoform*.xlsx"]
    for r in roots:
        rr = os.path.expanduser(r)
        for pat in pats:
            hits = sorted(glob.glob(os.path.join(rr, "**", pat), recursive=True))
            if hits:
                return hits[0]
    raise FileNotFoundError(
        "vendor isoform xlsx를 찾지 못했습니다. 환경변수 PD1_XLSX 로 경로를 지정하거나 "
        "LLMwiki PD-1 폴더에 mRNA-Seq_Report_isoform*.xlsx 를 두세요.")


# ---------------------------------------------------------------------------
# limma-style empirical-Bayes moderated t-test (Smyth 2004), two groups.
# Self-contained; no rpy2/limma. Gives usable p-values at n=2 by borrowing
# variance strength across genes — the honest way to test tiny-replicate DE.
# ---------------------------------------------------------------------------
def moderated_ttest(logmat: np.ndarray, cols_a, cols_b):
    """Return (log2FC=b-a, t_moderated, p, s2_post, df_total). logmat = genes x samples."""
    from scipy import stats
    from scipy.special import digamma, polygamma
    from scipy.optimize import brentq
    a = logmat[:, cols_a]; b = logmat[:, cols_b]
    na, nb = a.shape[1], b.shape[1]
    lfc = b.mean(1) - a.mean(1)
    d = (na - 1) + (nb - 1)
    s2 = (a.var(1, ddof=1) * (na - 1) + b.var(1, ddof=1) * (nb - 1)) / d
    s2 = np.maximum(s2, 1e-8)
    # fit inverse-chisq prior (d0, s0^2) on the observed variances
    z = np.log(s2)
    e = z - digamma(d / 2) + np.log(d / 2)
    evar = np.var(e, ddof=1)
    tri = evar - polygamma(1, d / 2)
    if tri <= 0:
        d0, s0_2 = np.inf, np.exp(e.mean())
    else:
        d0 = brentq(lambda x: polygamma(1, x / 2) - tri, 1e-3, 1e6)
        s0_2 = np.exp(e.mean() + digamma(d0 / 2) - np.log(d0 / 2))
    if np.isinf(d0):
        s2_post = np.full_like(s2, s0_2); df_tot = np.full_like(s2, 1e6)
    else:
        s2_post = (d0 * s0_2 + d * s2) / (d0 + d); df_tot = np.full_like(s2, d0 + d)
    se = np.sqrt(s2_post * (1.0 / na + 1.0 / nb))
    tmod = lfc / se
    p = 2 * stats.t.sf(np.abs(tmod), df_tot)
    return lfc, tmod, p, s2_post, df_tot


def bh_fdr(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float); n = len(p)
    order = np.argsort(p)
    q = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty_like(q); out[order] = np.clip(q, 0, 1)
    return out


# ===========================================================================
# The submitted report's stated TISSUE fold-changes (조직 P3C/P0C, log2) and
# GSEA NES. Used only to score agreement in step 5. Source: 박상민 통합분석 v8.1.
# ===========================================================================
REPORT_TISSUE_FC = {  # gene -> log2FC (조직)
    # Cat.A ECM/GAG/adhesion
    "XYLT1": 3.46, "FGF5": 1.73, "ITGA6": 1.71, "LAMB3": 2.05, "ITGBL1": 2.13,
    "EMILIN2": 1.16, "FLRT2": 1.04,
    # Cat.A glycosylation
    "GALNT6": 1.53, "GCNT2": 1.20, "FKBP11": 1.24,
    # Cat.A plasticity
    "S100A16": 2.00, "NDRG1": 3.30, "TM4SF18": 1.58, "TUBB6": 1.12, "VEPH1": 1.30,
    "KRT15": 2.23, "KRT8": 1.09,
    # Cat.A metabolism/transport
    "SLCO1B3": 4.52, "ARG2": 1.17, "CA2": 1.76, "G0S2": 2.44, "COX7B2": 1.07,
    "ATP8B3": 1.08, "SLCO4A1": 1.47,
    # Cat.A signaling/TF
    "MST1R": 2.47, "LPAR3": 1.49, "RPS6KA1": 1.38, "PTPRG": 1.85, "TSHZ3": 1.86,
    "HIC1": 1.65, "NPAS2": 2.83, "ZNF385D": 1.37,
    # Cat.A apoptosis/stress
    "PMAIP1": 0.94, "CRACR2A": 2.76, "BACE2": 3.33,
    # Cat.A immune
    "TNFSF15": 2.51, "OSCAR": 5.16, "THBD": 2.58, "VSTM1": 5.08, "SP100": 1.67,
    # Cat.B immune-cell markers
    "HLA-DMB": 3.88, "NCKAP1L": 2.79, "IL15RA": 2.01, "BATF2": 1.91, "NLRP3": 1.59,
    "PSMB9": 1.54, "CD163L1": 1.47, "OAS3": 1.29, "CASP4": 1.19, "RFTN1": 1.15,
    "BTN3A2": 1.04, "COTL1": 1.04, "SP140L": 1.02,
    # Cat.B death receptors
    "TNFRSF6B": 1.82, "TNFRSF10A": 1.27, "MLKL": 1.63, "NFKBIZ": 1.31,
    # Cat.B hypoxia/endothelial
    "EPAS1": 2.06, "ESM1": 6.14, "ENG": 1.44, "HEG1": 1.09, "KLF2": 1.09,
    # Cat.B ECM/CAF
    "LAMC2": 1.66, "FGF2": 1.57, "HBEGF": 1.56, "BMP6": 1.96, "CHST11": 1.07,
    "DSE": 1.01, "TGM2": 1.25, "CRIM1": 1.24,
    # Cat.B other
    "PTPN2": 1.08, "ADRB2": 2.17, "GAS6": 1.43, "UAP1": 1.47, "ETS2": 1.30, "CD274": 2.59,
    # Cat.C completely-opposite (tissue DOWN)
    "SPP1": -0.93, "TUBB3": -1.11, "PTHLH": -0.87, "ID2": -1.11, "RGS4": -5.12,
    # Cat.D mixed
    "HS3ST3B1": 1.01, "GSPT1": 1.01, "BCL2A1": 2.73, "NCR3LG1": 1.00,
    # down-regulated developmental / EMT-TF (background for lineage-plasticity claim)
    "ZEB2": -0.88, "SNAI2": -1.02, "FN1": -1.68, "LUM": -4.36,
    "DTX1": -7.53, "NOTCH3": -4.24, "JAG2": -3.11, "GLI1": -2.62, "SMO": -1.76, "SHH": -1.79,
    # compensatory epithelial up (KRT8 above); TJP2 mRNA up despite ZO-2 protein loss
    "KRT18": 1.66, "OCLN": 0.97, "TJP2": 2.32, "KLF4": 1.06,
}

# Tier-1/2 targets the report prioritizes (checked explicitly in step 3/5).
TIER1_TARGETS = ["XYLT1", "S100A16", "GALNT6"]
TIER2_TARGETS = ["ARG2", "PMAIP1", "TNFRSF6B"]

# Cat.A candidate targets grouped by the report's 7 functional axes (for the heatmap).
CAT_A_AXES = {
    "ECM/GAG/접착": ["XYLT1", "FGF5", "ITGA6", "LAMB3", "ITGBL1", "EMILIN2", "FLRT2"],
    "Glycosylation": ["GALNT6", "GCNT2", "FKBP11"],
    "Plasticity": ["S100A16", "NDRG1", "TM4SF18", "TUBB6", "VEPH1", "KRT15", "KRT8"],
    "대사/수송": ["SLCO1B3", "ARG2", "CA2", "G0S2", "COX7B2", "SLCO4A1"],
    "신호/전사": ["MST1R", "LPAR3", "RPS6KA1", "PTPRG", "TSHZ3", "HIC1", "NPAS2"],
    "사멸/스트레스": ["PMAIP1", "CRACR2A", "BACE2"],
    "면역": ["TNFSF15", "THBD", "SP100"],
}

# Report GSEA Hallmark NES (P3 vs P0). Direction is the reproduction target.
REPORT_GSEA = {
    "HALLMARK_INTERFERON_GAMMA_RESPONSE": 1.77,
    "HALLMARK_INTERFERON_ALPHA_RESPONSE": 1.78,
    "HALLMARK_E2F_TARGETS": 2.49,
    "HALLMARK_G2M_CHECKPOINT": 2.12,
    "HALLMARK_EPITHELIAL_MESENCHYMAL_TRANSITION": -2.26,
    "HALLMARK_NOTCH_SIGNALING": -1.95,
    "HALLMARK_HEDGEHOG_SIGNALING": -2.07,
}

# Report drug-response patterns (P0 drug effect vs P3 drug effect).
REPORT_DRUG_PATTERN = {
    "XYLT1": "REVERSED", "KRT15": "REVERSED",
    "S100A16": "CONSTITUTIVE", "FGF5": "CONSTITUTIVE", "ITGA6": "CONSTITUTIVE",
    "NDRG1": "CONSTITUTIVE", "MST1R": "CONSTITUTIVE",
    "THBD": "PARADOXICAL",
    "SP100": "LOST-INDUCTION", "RPS6KA1": "LOST-INDUCTION", "HLA-DMB": "LOST-INDUCTION",
    "PSMB9": "LOST-INDUCTION", "NLRP3": "LOST-INDUCTION", "BATF2": "LOST-INDUCTION",
}
