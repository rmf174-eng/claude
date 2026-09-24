#!/usr/bin/env bash
# Instalador da Ilha de edição — roda na MÁQUINA DE QUEM TEM OS BRUTOS.
#
#   ./tools/pacote/instalar.sh            instala o que é do projeto e confere o resto
#   ./tools/pacote/instalar.sh --deps     também instala ffmpeg/ffprobe/jq/node/python (brew ou apt)
#   ./tools/pacote/instalar.sh --web      modo Claude Code na nuvem: pula o navegador do Remotion
#
# É idempotente: rodar de novo não estraga nada, só reconfere.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

COM_DEPS=0; MODO_WEB=0
for arg in "$@"; do
  case "$arg" in
    --deps) COM_DEPS=1 ;;
    --web)  MODO_WEB=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $arg" >&2; exit 2 ;;
  esac
done

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "🔴 Windows não é suportado pela Ilha. Use WSL2 (Ubuntu) com os brutos dentro do WSL." >&2; exit 1 ;;
esac

SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && SUDO="sudo"

falta() { ! command -v "$1" >/dev/null 2>&1; }

# ── 1. binários que a Ilha não consegue substituir ───────────────────────────
FALTANDO=()
for bin in ffmpeg ffprobe jq node python3; do falta "$bin" && FALTANDO+=("$bin"); done

if [ "${#FALTANDO[@]}" -gt 0 ]; then
  if [ "$COM_DEPS" -eq 1 ]; then
    echo "→ instalando: ${FALTANDO[*]}"
    if command -v brew >/dev/null; then
      brew install ffmpeg jq node python@3.11
    elif command -v apt-get >/dev/null; then
      $SUDO apt-get update -qq
      DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq ffmpeg jq nodejs npm python3 python3-pip
    else
      echo "🔴 sem brew nem apt-get aqui. Instale à mão: ${FALTANDO[*]}" >&2; exit 1
    fi
  else
    echo "🔴 faltam binários: ${FALTANDO[*]}"
    echo "   macOS:  brew install ffmpeg jq node python@3.11"
    echo "   Ubuntu: sudo apt install ffmpeg jq nodejs npm python3 python3-pip"
    echo "   ou rode de novo com --deps para eu instalar."
    exit 1
  fi
fi

# versões mínimas declaradas pelo pacote: Node 22+, Python 3.11+
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 22 ] || { echo "🔴 Node $NODE_MAJOR — o Remotion 4.x pede 22+."; exit 1; }
python3 - <<'PY' || exit 1
import sys
if sys.version_info < (3, 11):
    sys.exit(f"🔴 Python {sys.version.split()[0]} — o pacote pede 3.11+.")
PY

# ffmpeg slim passa no -version e falha no render: confere os encoders que importam
for enc in libx264 aac; do
  ffmpeg -hide_banner -encoders 2>/dev/null | grep -q " $enc " || echo "⚠️  ffmpeg sem $enc — build slim quebra no render. Troque por um build completo."
done

# ── 2. dependências Python (numpy e Pillow são obrigatórias) ─────────────────
echo "→ pip install -r requirements.txt"
python3 -m pip install -q -r requirements.txt

# ── 3. painel de aprovação do Claude Code ────────────────────────────────────
cp -n .claude/skills/edit-video/preview/launch.exemplo.json .claude/launch.json 2>/dev/null \
  && echo "→ .claude/launch.json criado (ajuste <DIR-DA-PRODUCAO> se abrir o painel à mão)" \
  || echo "→ .claude/launch.json já existe, mantido"

# ── 4. projeto de render ─────────────────────────────────────────────────────
echo "→ npm install em tools/remotion-compositor"
( cd tools/remotion-compositor && npm install --no-audit --no-fund --silent )

if [ "$MODO_WEB" -eq 0 ]; then
  echo "→ baixando o chrome-headless-shell do Remotion (~193 MB, uma vez só)"
  ( cd tools/remotion-compositor && npx --yes remotion browser ensure ) \
    || echo "⚠️  o navegador não baixou. Sem ele o render falha — rode este passo com rede liberada para remotion.media."
else
  echo "→ modo --web: pulando o navegador do Remotion (o render acontece na sua máquina)"
fi

# ── 5. o que ficou de pé ─────────────────────────────────────────────────────
echo
python3 tools/pacote/chaves.py --status || true
echo
echo "Falta a chave da Deepgram? Configure uma vez, fora da instalação:"
echo "    python3 tools/pacote/chaves.py --pedir DEEPGRAM_API_KEY"
