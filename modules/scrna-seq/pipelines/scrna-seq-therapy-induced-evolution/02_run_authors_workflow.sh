#!/usr/bin/env bash
set -euo pipefail

stage="${1:-}"
ROOT="${GHBIO_MAYNARD_DIR:-$HOME/ghbio-tutorial/maynard-2020}"
SOURCE="$ROOT/scell_lung_adenocarcinoma"
RESULTS="${GHBIO_RESULTS:?BioIDE must provide GHBIO_RESULTS}"
LIB_ROOT="${GHBIO_MAYNARD_R_LIB:-$HOME/ghbio-venv-r/maynard-2020}"
export R_LIBS_USER="$LIB_ROOT"

[[ -d "$SOURCE/Data_input" ]] || { echo "Run step 1 first: authors' Data_input is missing." >&2; exit 1; }
[[ -f "$LIB_ROOT/.ready" ]] || { echo "Run step 0 first: legacy R environment is not ready." >&2; exit 1; }
mkdir -p "$RESULTS"

# The published notebooks contain a hard-coded /home/ubuntu checkout path. Patch
# only the local clone, preserving its original revision in git, so Rmd files use
# the portable tutorial location.
find "$SOURCE/scripts" -name '*.Rmd' -print0 | xargs -0 sed -i "s|/home/ubuntu/scell_lung_adenocarcinoma/|$SOURCE/|g"

# The notebooks mix a Seurat v2 plotting argument (do.label=) into DimPlot/TSNEPlot calls;
# Seurat v4 renamed it to label= and rejects the old name ("unused argument"). Same meaning,
# safe global rename, idempotent (no do.label remains after the first pass).
find "$SOURCE/scripts" -name '*.Rmd' -print0 | xargs -0 sed -i "s|do\.label|label|g"

# 03.1 reproducibility patches. The authors ran these notebooks interactively, so
# two chunks assume state a fresh, deterministic batch render cannot reproduce.
# Guarded by a marker so re-runs are idempotent.
nb31="$SOURCE/scripts/03.1_Subset_and_general_annotations.Rmd"
if ! grep -q 'BioIDE-df-rename' "$nb31"; then
  # (1) DoubletFinder names its pANN_/DF.classifications_ columns with the run's own
  #     data-driven nExp; the authors then hard-code nExp=218 (their exact cell count)
  #     in 6 downstream references, incl. the load-bearing singlet subset. On any fresh
  #     clustering nExp differs, so those columns are NULL and hist()/subset() fail.
  #     Rename the produced columns to the fixed _0.25_0.09_218 suffix the notebook uses.
  sed -i '/tiss_subset <- doubletFinder_v3(/a\
.bioide_pann <- tail(grep("^pANN_", colnames(tiss_subset@meta.data), value = TRUE), 1) # BioIDE-df-rename\
.bioide_dfcl <- tail(grep("^DF.classifications_", colnames(tiss_subset@meta.data), value = TRUE), 1)\
if (length(.bioide_pann) == 1) colnames(tiss_subset@meta.data)[colnames(tiss_subset@meta.data) == .bioide_pann] <- "pANN_0.25_0.09_218"\
if (length(.bioide_dfcl) == 1) colnames(tiss_subset@meta.data)[colnames(tiss_subset@meta.data) == .bioide_dfcl] <- "DF.classifications_0.25_0.09_218"' "$nb31"
  # (2) A diagnostic cross-tab references tiss_subset1 (never defined in this notebook)
  #     and immune_annotation (assigned only later, at cluster-annotation time). It cannot
  #     run in a fresh render; drop it (diagnostic only, produces nothing downstream).
  sed -i 's|^table(tiss_subset@meta.data\$DF.classifications_0.25_0.09_218, tiss_subset1@meta.data\$immune_annotation)|# BioIDE: dropped non-reproducible cross-tab (tiss_subset1 undefined in a fresh batch render)|' "$nb31"
fi

# (3) The authors hand-labeled each of their 26 clusters immune/non-immune (a fixed
#     26-element vector) after inspecting the CD45(PTPRC)/EPCAM dot plot just above. A
#     fresh clustering yields a different cluster count, so plyr::mapvalues() dies on a
#     from/to length mismatch. Reproduce their INTENT data-drivenly: label each cluster
#     "immune" iff mean CD45(PTPRC) dominates mean EPCAM and CD45 is actually expressed.
#     (This is a documented deviation — the authors' manual per-cluster calls cannot be
#     reproduced headlessly on a different partition.) Separate self-guarding block (its own
#     marker) so it also applies to clones that already have patches (1)/(2). Python does the
#     multi-line replace so R's $/@ are treated literally.
if grep -q 'immune_annotation <- c(' "$nb31"; then
  python3 - "$nb31" <<'PYEOF'
import re, sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
if "BioIDE-immune-annotation" not in src:
    repl = (
        'immune_annotation <- { # BioIDE-immune-annotation: data-driven CD45/EPCAM labeling\n'
        '  .expr <- Seurat::GetAssayData(tiss_subset, slot = "data")\n'
        '  .cl <- as.character(tiss_subset@meta.data$RNA_snn_res.0.5)\n'
        '  .ptprc <- if ("PTPRC" %in% rownames(.expr)) .expr["PTPRC", ] else rep(0, ncol(.expr))\n'
        '  .epcam <- if ("EPCAM" %in% rownames(.expr)) .expr["EPCAM", ] else rep(0, ncol(.expr))\n'
        '  vapply(as.character(cluster.ids), function(cid) {\n'
        '    m <- .cl == cid\n'
        '    if (mean(.ptprc[m]) > mean(.epcam[m]) && mean(.ptprc[m] > 0) > 0.25) "immune" else "non-immune"\n'
        '  }, character(1))\n'
        '}'
    )
    out = re.sub(r'immune_annotation <- c\(.*?\)', repl, src, count=1, flags=re.S)
    if out != src:
        open(path, "w", encoding="utf-8").write(out)
PYEOF
fi

case "$stage" in
  core)
    notebooks=(01_Import_data_and_metadata.Rmd 02_Create_Seurat_object.Rmd 02.1_Create_Seurat_object_neo_osi.Rmd 03_Merge_in_NeoOsi.Rmd 03.1_Subset_and_general_annotations.Rmd)
    ;;
  immune)
    notebooks=(IM01_Subset_cluster_annotate_immune_cells.Rmd IM02_immune_cell_changes_with_response_to_treatment.Rmd IM03_Subset_cluster_annotate_MFs-monocytes_LUNG.Rmd IM04_Subset_cluster_annotate_T-cells_LUNG.Rmd IM05_Immune_cells_across_pats_with_multiple_biopsies.Rmd IM06_Combine_Immune_and_nonImmune_annotations.Rmd)
    ;;
  cancer)
    notebooks=(NI01_General_annotation_of_nonimmune_cells.Rmd NI02_epi_subset_and_cluster.Rmd)
    ;;
  *) echo "Usage: $0 {core|immune|cancer}" >&2; exit 2 ;;
esac

for notebook in "${notebooks[@]}"; do
  echo "Rendering authors' scripts/$notebook"
  Rscript --vanilla -e 'rmarkdown::render(commandArgs(TRUE)[1], quiet = FALSE)' "$SOURCE/scripts/$notebook"
done

if [[ "$stage" == "cancer" ]]; then
  cat > "$RESULTS/maynard-2020-infercnv-manual-step.txt" <<EOF
The authors' repository prepares inferCNV input in scripts/NI03_inferCNV.Rmd,
but its actual inferCNV execution (NI03.1_Running_inferCNV_R3_4_4.Rmd) is not
present in the public repository. NI03 expects its annotation output at:
  $SOURCE/data_out/NI03/results/inferCNV_annotation.csv

After recreating that legacy-R inferCNV step and producing this file, continue
with the authors' NI03–NI17 notebooks manually. This tutorial does not invent a
replacement analysis or label downstream cancer results as reproduced.
EOF
fi

printf 'author_repository=https://github.com/czbiohub/scell_lung_adenocarcinoma\ncommit=de138c79bcfc2fa3a28c8a039a28ab560da78099\nstage=%s\ncompleted_at=%s\n' "$stage" "$(date --iso-8601=seconds)" > "$RESULTS/maynard-2020-$stage.complete"
ln -sfn "$SOURCE" "$RESULTS/maynard-2020-author-source"
echo "Completed $stage. Source outputs: $SOURCE/{Data_input,data_out,plot_out}"
