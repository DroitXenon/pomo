#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if ! command -v conda >/dev/null 2>&1; then
  printf '%s\n' 'Conda is required. Install Miniconda or Miniforge and make conda available in this terminal.' >&2
  exit 1
fi
conda env update --name pomo --file environment.yml --format cep-24 --prune
conda run --name pomo python scripts/setup_model.py
