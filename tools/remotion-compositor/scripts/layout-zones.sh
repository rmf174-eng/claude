#!/bin/bash
# Bootstrap do venv (rembg/onnxruntime/pillow) + roda layout-zones.py.
# Uso: layout-zones.sh <video.mp4> <ini-fim> [<ini-fim> ...] [--samples N]
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$DIR/.venv-rembg"
if [ ! -x "$VENV/bin/python" ]; then
  echo "criando venv rembg em $VENV..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet rembg onnxruntime pillow
fi
exec "$VENV/bin/python" "$DIR/scripts/layout-zones.py" "$@"
