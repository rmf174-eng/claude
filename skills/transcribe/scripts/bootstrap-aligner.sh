#!/usr/bin/env bash
# bootstrap-aligner — prepara o venv do alinhador forçado local (SPEC-04).
#
# Uso:
#   bootstrap-aligner.sh [--baixar-modelo] [--quiet]
#
# O que faz:
#   1. resolve o diretório do venv (ver "Onde o venv mora", abaixo)
#   2. cria o venv (uv se existir, senão python3 -m venv)
#   3. instala torch + torchaudio + numpy
#   4. imprime no stderr o device disponível (mps/cuda/cpu)
#   5. com --baixar-modelo, puxa os pesos do MMS_FA (1,26 GB) pro cache do torch
#
# stdout = caminho do python do venv.  logs = stderr.  Idempotente:
# se `python -c "import torchaudio"` já passa, sai em <2 s.
#
# Onde o venv mora (ordem fixa, sem caminho absoluto cravado):
#   1. $BENCH_ALIGNER_DIR
#   2. o primeiro diretório com `tools/` subindo a partir deste script → <ele>/tools/aligner
#   3. ${ILHA_HOME:-$HOME/.ilha}/aligner
#
# Espaço em disco: venv ~575 MB + modelo 1,26 GB = ~1,8 GB, uma vez só.
set -euo pipefail

QUIET=0
BAIXAR_MODELO=0
for a in "$@"; do
  case "$a" in
    --baixar-modelo) BAIXAR_MODELO=1 ;;
    --quiet)         QUIET=1 ;;
    -h|--help)       sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $a" >&2; exit 2 ;;
  esac
done
log() { [ "$QUIET" = 1 ] || echo "$@" >&2; }

# --- 1. onde o venv mora -----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -L)"

resolver_dir() {
  if [ -n "${BENCH_ALIGNER_DIR:-}" ]; then
    printf '%s' "$BENCH_ALIGNER_DIR"; return
  fi
  local d="$SCRIPT_DIR" i=0 primeiro=""
  while [ "$i" -lt 8 ] && [ "$d" != "/" ]; do
    # venv já pronto ganha de qualquer candidato mais acima
    if [ -x "$d/tools/aligner/venv/bin/python" ]; then printf '%s' "$d/tools/aligner"; return; fi
    if [ -z "$primeiro" ] && [ -d "$d/tools" ]; then primeiro="$d/tools/aligner"; fi
    d="$(dirname "$d")"; i=$((i + 1))
  done
  if [ -n "$primeiro" ]; then printf '%s' "$primeiro"; return; fi
  printf '%s' "${ILHA_HOME:-$HOME/.ilha}/aligner"
}

ALIGNER_DIR="$(resolver_dir)"
VENV="$ALIGNER_DIR/venv"
PY="$VENV/bin/python"

baixar_modelo() {
  log ">> baixando pesos do MMS_FA (1,26 GB) pro cache do torch..."
  "$PY" - <<'PY' >&2
from torchaudio.pipelines import MMS_FA as bundle
bundle.get_model()
print(">> modelo MMS_FA pronto (sample_rate=%d)" % bundle.sample_rate)
PY
}

# --- 2. atalho de idempotência ------------------------------------------------
if [ -x "$PY" ] && "$PY" -c "import torchaudio" >/dev/null 2>&1; then
  log ">> venv já pronto: $VENV"
  if [ "$BAIXAR_MODELO" = 1 ]; then baixar_modelo; fi
  "$PY" - <<'PY' >&2 || true
import torch
dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
print(f">> torch {torch.__version__} · device disponível: {dev}")
PY
  printf '%s\n' "$PY"
  exit 0
fi

# --- 3. criar o venv ----------------------------------------------------------
log ">> criando venv em $VENV"
log ">> ATENÇÃO: torch + torchaudio ocupam ~575 MB; o modelo MMS_FA, mais 1,26 GB."
mkdir -p "$ALIGNER_DIR"

# .gitignore do diretório: o venv e os pesos nunca entram em git.
if [ ! -f "$ALIGNER_DIR/.gitignore" ]; then
  cat > "$ALIGNER_DIR/.gitignore" <<'EOF'
# O venv do alinhador (~575 MB) e qualquer peso baixado não entram em git.
venv/
*.pt
__pycache__/
EOF
fi

if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.14 "$VENV" >&2
  VIRTUAL_ENV="$VENV" uv pip install --python "$PY" torch torchaudio numpy >&2
else
  python3 -m venv "$VENV" >&2
  "$PY" -m pip install --upgrade pip >&2
  "$PY" -m pip install torch torchaudio numpy >&2
fi

"$PY" - <<'PY' >&2
import torch, torchaudio
dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
print(f">> torch {torch.__version__} · torchaudio {torchaudio.__version__} · device disponível: {dev}")
PY

# --- 4. modelo (opcional) -----------------------------------------------------
if [ "$BAIXAR_MODELO" = 1 ]; then baixar_modelo; fi

printf '%s\n' "$PY"
