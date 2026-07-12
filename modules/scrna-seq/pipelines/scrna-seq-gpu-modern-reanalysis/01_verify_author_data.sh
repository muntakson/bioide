#!/usr/bin/env bash
set -euo pipefail

SOURCE="${GHBIO_MAYNARD_DIR:-$HOME/ghbio-tutorial/maynard-2020}/scell_lung_adenocarcinoma"
required=(
  "$SOURCE/Data_input/csv_files/S01_datafinal.csv"
  "$SOURCE/Data_input/csv_files/S01_metacells.csv"
  "$SOURCE/Data_input/csv_files/neo-osi_rawdata.csv"
  "$SOURCE/Data_input/csv_files/neo-osi_metadata.csv"
)
for file in "${required[@]}"; do
  [[ -s "$file" ]] || { echo "Missing or incomplete author data: $file" >&2; echo "Run the original Maynard tutorial's Step 1 again first." >&2; exit 1; }
done
echo "Authors' processed count matrix and metadata are ready at $SOURCE/Data_input"
