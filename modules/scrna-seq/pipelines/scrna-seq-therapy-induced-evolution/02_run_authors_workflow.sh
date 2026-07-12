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
