#!/bin/bash
# SessionStart — deixa a Ilha utilizável numa sessão do Claude Code na nuvem.
# Só roda no ambiente remoto; na sua máquina a instalação é o instalar.sh.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# ffmpeg/ffprobe: o container vem sem eles e a Ilha não os substitui.
if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update -qq >/dev/null 2>&1 || true
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg >/dev/null 2>&1 || true
fi

# numpy e Pillow: import de topo de vários scripts do caminho bruto → entregue.
python3 -c 'import numpy, PIL' 2>/dev/null || python3 -m pip install -q -r requirements.txt || true

# projeto de render (o navegador do Remotion não baixa aqui — egress bloqueado).
if [ ! -d tools/remotion-compositor/node_modules ]; then
  ( cd tools/remotion-compositor && npm install --no-audit --no-fund --silent ) || true
fi

echo "Ilha de edição pronta: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3), jq $(jq --version 2>/dev/null), node $(node --version 2>/dev/null). Render e painel de aprovação só rodam na máquina local."
