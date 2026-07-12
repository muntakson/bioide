#!/usr/bin/env bash
set -euo pipefail

ROOT="${GHBIO_MAYNARD_DIR:-$HOME/ghbio-tutorial/maynard-2020}"
SOURCE="$ROOT/scell_lung_adenocarcinoma"
COMMIT="de138c79bcfc2fa3a28c8a039a28ab560da78099"
DATA_FOLDER="https://drive.google.com/drive/folders/1sDzO0WOD4rnGC7QfTKwdcQTx3L36PFwX"
mkdir -p "$ROOT"

if [[ ! -d "$SOURCE/.git" ]]; then
  git clone https://github.com/czbiohub/scell_lung_adenocarcinoma.git "$SOURCE"
fi
git -C "$SOURCE" fetch --depth 1 origin "$COMMIT"
git -C "$SOURCE" checkout --detach "$COMMIT"

required_data=(
  "$SOURCE/Data_input/csv_files/S01_datafinal.csv"
  "$SOURCE/Data_input/csv_files/S01_metacells.csv"
  "$SOURCE/Data_input/csv_files/neo-osi_rawdata.csv"
  "$SOURCE/Data_input/csv_files/neo-osi_metadata.csv"
)
complete=true
for file in "${required_data[@]}"; do [[ -s "$file" ]] || complete=false; done
if [[ "$complete" == true ]]; then
  echo "Authors' required Data_input files already exist: $SOURCE/Data_input"
  exit 0
fi
if [[ -d "$SOURCE/Data_input" ]]; then
  echo "A previous Data_input download is incomplete; resuming the authors' Google Drive folder download…"
fi

# Ubuntu 24.04 protects its system Python (PEP 668). Keep the Google Drive client
# private to this tutorial instead of trying to modify the host Python installation.
GDOWN_VENV="$ROOT/.gdown-venv"
if [[ ! -x "$GDOWN_VENV/bin/gdown" ]]; then
  python3 -m venv "$GDOWN_VENV"
  "$GDOWN_VENV/bin/python" -m pip install --upgrade pip gdown
fi
cd "$SOURCE"
echo "Downloading the public Data_input folder supplied in the authors' README…"
"$GDOWN_VENV/bin/gdown" --folder "$DATA_FOLDER"

[[ -d "$SOURCE/Data_input" ]] || {
  echo "Download completed but Data_input was not found. Verify access to the public Google Drive folder and retry." >&2
  exit 1
}
for file in "${required_data[@]}"; do
  [[ -s "$file" ]] || { echo "Download is incomplete; required file missing: $file" >&2; exit 1; }
done
