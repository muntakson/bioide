#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p "$HOME/ghbio-backups"
OUT="$HOME/ghbio-backups/ghbio-coscientist-$(date +%Y%m%d-%H%M%S).bundle"
git bundle create "$OUT" --all
git bundle verify "$OUT" >/dev/null && echo "backup OK: $OUT"
