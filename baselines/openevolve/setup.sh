#!/usr/bin/env bash
# Set up the OpenEvolve baseline: clone OpenEvolve at a pinned commit into vendor/ (git-ignored)
# and install it into its own virtual environment, so the project's environment is not touched.
#
#   bash baselines/openevolve/setup.sh
#
# Makes no API calls.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="https://github.com/algorithmicsuperintelligence/openevolve.git"
COMMIT="4f4b0c4f40906f434d64fe5089aff24e927f7e24"   # main on 2026-09-29
VENDOR="$HERE/vendor"
SRC="$VENDOR/openevolve"
VENV="$VENDOR/venv"

mkdir -p "$VENDOR"
if [ ! -d "$SRC/.git" ]; then
  git clone --quiet "$REPO" "$SRC"
fi
if ! git -C "$SRC" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
  git -C "$SRC" fetch --quiet origin
fi
git -C "$SRC" -c advice.detachedHead=false checkout --quiet --detach "$COMMIT"

unset VIRTUAL_ENV   # an activated environment must not capture the install
if [ ! -x "$VENV/bin/python" ]; then
  uv venv --quiet --python 3.13 "$VENV"
fi
# OpenEvolve itself, plus what its circle-packing example asks for (scipy, matplotlib):
# evolved programs are free to import these, so leaving them out would handicap the baseline.
uv pip install --quiet --python "$VENV/bin/python" -e "$SRC" -r "$SRC/examples/circle_packing/requirements.txt"

echo "OpenEvolve $(git -C "$SRC" rev-parse --short HEAD) installed in $VENV"
"$VENV/bin/python" -c "import openevolve, numpy, scipy, openai; print('openevolve', getattr(openevolve, '__version__', '?'), '| numpy', numpy.__version__, '| scipy', scipy.__version__, '| openai', openai.__version__)"
