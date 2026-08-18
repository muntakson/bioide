"""
Shared helpers + the published paper's Fig-6 reference DIRECTIONS for the DDX54
independent reproduction. Everything the pipeline needs to (a) fetch the public
GEO count matrix (GSE285342), (b) run a self-contained limma-style moderated
t-test, and (c) score reproduction against the paper's claims lives here — no
TypeScript, no author fold-change/padj consumed as ground truth.

Paper: Gong, Lee, Han & Cho, "DDX54 downregulation enhances anti-PD1 therapy in
immune-desert lung tumors with high tumor mutational burden", PNAS 122(14),
e2412310122 (2025). Data: GSE285342 (bulk RNA-seq, LLC1 WT-Ddx54 vs Ddx54-KD).

The paper's DISCOVERY is a systems-biology master-regulator analysis: from TCGA
LUAD it splits TMB-H tumors into immune-desert vs immune-inflamed, builds a gene
regulatory network (ARACNe -> VIPER -> DIGGIT), and finds DDX54 as the #1 master
regulator of immune escape (Fig 2). The FUNCTIONAL VALIDATION of that discovery
is Fig 6: knocking Ddx54 down in LLC1 lung-cancer cells REVERSES the oncogenic /
immune-evasion transcriptional programs it drives — EMT down, Myc down, Jak-Stat3
down, NF-kB down, and the immune-evasion surface molecules Cd38/Cd47 down.

Reproduction scope. This pipeline re-derives Fig 6 from the raw GEO counts (fresh
normalization + DE + GSEA, no author padj used). The upstream TCGA GRN inference
(Fig 1-2), the microRNA regulon (Fig 3, GSE289119), and the in-vivo / spatial /
scRNA experiments (Fig 4-8, GSE268555/GSE285341) are OUT of reproduction scope —
they need controlled-access TCGA data, a separate assay, or mouse/tissue not in
this matrix. BioIDE constitution §1·2: the paper's directions below are used ONLY
to CHECK agreement, never fed into the analysis.
"""
from __future__ import annotations
import os, glob, subprocess
import numpy as np

# Korean-capable figures (see the sibling PD-1 pipeline for the rationale).
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

# Heavy shared input (the GEO count matrix + its gene-level cache) lives under
# ~/ghbio-tutorial/data so it is fetched/parsed once and reused idempotently.
DATA_DIR = os.path.expanduser("~/ghbio-tutorial/data/ddx54-llc1")
os.makedirs(DATA_DIR, exist_ok=True)
TSV_GZ = os.path.join(DATA_DIR, "GSE285342_LLC1_cnt_DDX54.tsv.gz")
COUNTS_CACHE = os.path.join(DATA_DIR, "counts_gene.csv")

GEO_URL = ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE285nnn/GSE285342/suppl/"
           "GSE285342_LLC1_cnt_DDX54.tsv.gz")

# ---------------------------------------------------------------------------
# Sample / group design (columns of GSE285342_LLC1_cnt_DDX54.tsv):
#   WT_DDX54_1..4  = control (wild-type Ddx54)   n=4
#   KD_DDX54_1..3  = Ddx54 knockdown             n=3
# Core contrast is KD vs WT (the effect of removing Ddx54).
# ---------------------------------------------------------------------------
WT_COLS = ["WT_DDX54_1", "WT_DDX54_2", "WT_DDX54_3", "WT_DDX54_4"]
KD_COLS = ["KD_DDX54_1", "KD_DDX54_2", "KD_DDX54_3"]
SAMPLES = WT_COLS + KD_COLS
GROUPS = {  # group -> column indices into SAMPLES
    "WT": list(range(0, 4)),   # control
    "KD": list(range(4, 7)),   # Ddx54 knockdown
}
SAMPLE_GROUP = {s: ("WT" if s.startswith("WT") else "KD") for s in SAMPLES}


def fetch_counts() -> str:
    """Ensure the GEO count matrix is on disk; return its path. Resilient curl
    (flock lock + resume + stall timeout + retries), per CLAUDE.md. Idempotent."""
    env = os.environ.get("DDX54_TSV")
    if env and os.path.exists(os.path.expanduser(env)):
        return os.path.expanduser(env)
    if os.path.exists(TSV_GZ) and os.path.getsize(TSV_GZ) > 10000:
        return TSV_GZ
    # local drop-in fallback (e.g. someone pre-downloaded into the repo)
    for r in ("~/ghbio-coscientist", "~/Downloads", "~"):
        hits = glob.glob(os.path.join(os.path.expanduser(r), "GSE285342*DDX54*.tsv.gz"))
        if hits:
            return hits[0]
    lock = TSV_GZ + ".lock"
    print(f"==> fetching {GEO_URL}")
    cmd = ("flock '{lock}' curl -fL -C - "
           "--retry 5 --retry-delay 3 --speed-limit 1000 --speed-time 30 "
           "-o '{out}' '{url}'").format(lock=lock, out=TSV_GZ, url=GEO_URL)
    subprocess.run(["bash", "-c", cmd], check=True)
    if not (os.path.exists(TSV_GZ) and os.path.getsize(TSV_GZ) > 10000):
        raise RuntimeError("GEO 다운로드 실패 — 네트워크를 확인하거나 DDX54_TSV 로 경로를 지정하세요.")
    return TSV_GZ


# ---------------------------------------------------------------------------
# limma-style empirical-Bayes moderated t-test (Smyth 2004), two groups.
# Self-contained; no rpy2/limma. n=4/3 here, so this is honest DE with real
# replicates strengthened by cross-gene variance shrinkage. (Shared with the
# sibling PD-1 pipeline — kept independent so each pipeline is self-contained.)
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
# The published paper's Fig-6 claims, as DIRECTIONS in the Ddx54-KNOCKDOWN arm
# (KD vs WT). Used only to score agreement in step 4. We never feed these into
# the DE/GSEA — we compute our own and check the sign matches.
#   Fig 6C  cMyc protein DOWN in KD           -> Myc mRNA expected DOWN
#   Fig 6E  Cd47 mRNA DOWN in KD (**)         -> Cd47 DOWN
#   Fig 6G  Cd38 mRNA DOWN in KD (**)         -> Cd38 DOWN
#   Fig 6E  Ddx54 protein DOWN in KD          -> Ddx54 mRNA DOWN  (knockdown sanity)
# ===========================================================================
# gene -> expected direction of log2FC(KD/WT) at the TRANSCRIPTOME level.
PAPER_KD_GENE_DIR = {
    "Ddx54": "DOWN",   # knockdown target (sanity — must reproduce)
    "Cd47":  "DOWN",   # Fig 6E — "don't eat me" signal, mRNA down
    "Cd38":  "DOWN",   # Fig 6G — adenosine-producing ectoenzyme, mRNA down
    "Myc":   "DOWN",   # Fig 6C — cMyc (protein down; mRNA tracks here)
}

# Genes whose PROTEIN/PHOSPHO state the paper shows but whose mRNA is NOT a fair
# transcriptome test (regulated post-transcriptionally). Reported, not scored.
PROTEIN_LEVEL_ONLY = {
    "Ctnnb1": "β-catenin (Fig 6C, 단백질 안정화 — mRNA는 추적 안 함)",
    "Ccnd1":  "Cyclin D1 (Fig 6C, 단백질 — mRNA는 추적 안 함)",
    "Jak1":   "p-Jak1 (Fig 6D/E, 인산화 — 총 mRNA와 별개)",
    "Jak2":   "p-Jak2 (Fig 6E, 인산화)",
    "Stat3":  "p-Stat3 (Fig 6D/E, 인산화)",
    "Rela":   "p-p65 / NF-κB (Fig 6F/G, 인산화)",
}

# Program-level claims: Hallmark set -> expected NES sign in the KD-vs-WT ranking.
# Fig 6B: EMT & Myc-transformation enriched in WT-Ddx54 (i.e. DOWN in KD).
# Fig 6D: Jak-Stat3 signalling DOWN in KD.  Fig 6F: NF-κB targets DOWN in KD.
PAPER_GSEA_DIR = {
    "HALLMARK_EPITHELIAL_MESENCHYMAL_TRANSITION": "DOWN",  # Fig 6B (NES 2.26 in WT)
    "HALLMARK_MYC_TARGETS_V1":                    "DOWN",  # Fig 6B (Ccnd1/Myc transform.)
    "HALLMARK_IL6_JAK_STAT3_SIGNALING":           "DOWN",  # Fig 6D
    "HALLMARK_TNFA_SIGNALING_VIA_NFKB":           "DOWN",  # Fig 6F
}

# Genes highlighted on the DE volcano / immune-evasion panel figure.
FOCUS_GENES = ["Ddx54", "Cd47", "Cd38", "Myc", "Ctnnb1", "Ccnd1",
               "Jak1", "Jak2", "Stat3", "Cd274", "Nt5e", "Vim", "Fn1"]
