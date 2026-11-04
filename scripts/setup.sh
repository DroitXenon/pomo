#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if ! command -v conda >/dev/null 2>&1; then
  printf '%s\n' 'Conda is required. Install Miniconda or Miniforge and make conda available in this terminal.' >&2
  exit 1
fi
# Recent Conda interprets the Linux-only native-library selectors directly.
# Conda 25 can use the same source after omitting those entries off Linux.
if conda env update --help | grep -q -- '--format'; then
  conda env update --name pomo --file environment.yml --format cep-24 --prune
else
  pomo_environment_file=environment.yml
  case "$(uname -s)" in
    Linux) ;;
    *)
      pomo_setup_directory=$(mktemp -d "${TMPDIR:-/tmp}/pomo-setup.XXXXXX")
      pomo_environment_file="$pomo_setup_directory/environment.yml"
      trap 'rm -f "$pomo_environment_file"; rmdir "$pomo_setup_directory"' EXIT HUP INT TERM
      sed '/# \[linux\]/d' environment.yml > "$pomo_environment_file"
      ;;
  esac
  conda env update --name pomo --file "$pomo_environment_file" --prune
fi
conda run --name pomo python scripts/setup_model.py
