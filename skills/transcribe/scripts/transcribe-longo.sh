#!/usr/bin/env bash
# transcribe-longo — transcreve áudio LONGO em partes COM OVERLAP e remonta
# costurando num vale de silêncio.
#
# ⚠️ POR QUE ISSO EXISTE (medido em 2026-08-05): o Deepgram aceita o upload de um
# mp3 de 2h sem erro nenhum, responde 200, e devolve a transcrição de **apenas
# parte** do arquivo. No caso medido, um mp3 de 7.240s (2h00m40s, íntegro)
# voltou com `metadata.duration = 3726` e a fala parava aos 62 min.
# ⚠️ E é INTERMITENTE: `aula-longa-01` (8.181s, 2h16) passou completo em passe
# único. Por isso a proteção tem que ser automática — "olhar o número quando
# lembrar" não funciona.
#
# ⚠️ A CHECAGEM ANTIGA DESTE SCRIPT ERA CIRCULAR e nunca acusou nada: a linha 95
# gravava o ffprobe dentro de `metadata.duration` e a linha 111 conferia
# `metadata.duration` contra o mesmo ffprobe (`abs(x-x)/x < 0.02`). Hoje quem
# confere é o `verificar-transcricao.py`, que compara o número DECLARADO PELO
# ENGINE em cada parte contra o ffprobe daquele chunk, e ainda cruza com o áudio.
#
# Uso:
#   transcribe-longo.sh <audio|dir> [outdir]
#       [--parte 3000] [--overlap 30] [--remontar] [--sem-verificar]
#
# Env (o gancho por onde o perfil de peça preenche isto sem conhecer perfil):
#   BENCH_TRANSCRIBE_PARTE     default do --parte     (3000)
#   BENCH_TRANSCRIBE_OVERLAP   default do --overlap   (30)
#   BENCH_TRANSCRIBE_SEM_VERIFICAR=1  desliga o verificador
#
# --parte 3000 e não 3600: 3.600s está do lado errado do único truncamento que
# medimos (o retorno veio com 3.726s). 3.000s é o valor que passou completo.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
IN="${1:?uso: transcribe-longo.sh <audio|dir> [outdir] [--parte N] [--overlap N]}"
PARTE="${BENCH_TRANSCRIBE_PARTE:-3000}"
OVERLAP="${BENCH_TRANSCRIBE_OVERLAP:-30}"
OUTDIR=""
SO_REMONTAR=false
VERIFICAR=true
# ⚠️ `[ x ] && VAR=y` solto sob `set -e` MATA o script quando o teste é falso —
# a AND-list vira o comando e seu exit 1 dispara o errexit. Sempre `if`.
if [ "${BENCH_TRANSCRIBE_SEM_VERIFICAR:-}" = "1" ]; then VERIFICAR=false; fi
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --parte) PARTE="$2"; shift 2 ;;
    --overlap) OVERLAP="$2"; shift 2 ;;
    --remontar) SO_REMONTAR=true; shift ;;
    --sem-verificar) VERIFICAR=false; shift ;;
    *) OUTDIR="$1"; shift ;;
  esac
done

if [ -d "$IN" ]; then
  for c in audio.mp3 audio.m4a video.mp4; do
    [ -f "$IN/$c" ] && { AUDIO="$IN/$c"; break; }
  done
  : "${AUDIO:?não achei audio.mp3/audio.m4a/video.mp4 em $IN}"
  OUTDIR="${OUTDIR:-$IN}"
else
  AUDIO="$IN"
  OUTDIR="${OUTDIR:-$(dirname "$AUDIO")}"
fi
mkdir -p "$OUTDIR"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO")
N=$(python3 -c "import math;print(max(1,math.ceil($DUR/$PARTE)))")

if ! $SO_REMONTAR; then
  echo ">> $AUDIO — ${DUR%.*}s em $N parte(s) de ${PARTE}s (overlap ${OVERLAP}s)" >&2

  # As partes ficam em <outdir>/.partes/pN/ — NÃO em mktemp. Uma call de 2h que
  # falha na parte 3 de 3 evaporava ≈US$0,40 de API com o `trap rm -rf` antigo.
  for i in $(seq 0 $((N - 1))); do
    SS=$((i * PARTE))
    P="$OUTDIR/.partes/p$i"
    mkdir -p "$P"
    if [ ! -s "$P/transcript.json" ]; then
      # a parte i cobre [i*PARTE, min(DUR, (i+1)*PARTE + OVERLAP)] — o overlap é
      # o que dá margem para escolher a costura num silêncio.
      # ⚠️ nada de `-c copy`: o corte tem que ser exato, senão o offset não bate
      # e os timestamps derivam ao longo da peça.
      if [ "$i" -eq $((N - 1)) ]; then
        ffmpeg -nostdin -v error -ss "$SS" -i "$AUDIO" \
          -ac 1 -ar 16000 -b:a 64k -y "$P/audio.mp3"
      else
        ffmpeg -nostdin -v error -ss "$SS" -i "$AUDIO" -t "$((PARTE + OVERLAP))" \
          -ac 1 -ar 16000 -b:a 64k -y "$P/audio.mp3"
      fi
      echo ">> parte $((i + 1))/$N (offset ${SS}s)" >&2
      "$AQUI/transcribe.sh" "$P/audio.mp3" "$P" >/dev/null
    else
      echo ">> parte $((i + 1))/$N em cache, pulando" >&2
    fi
    DP=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$P/audio.mp3")
    python3 -c "
import json,sys
json.dump({'i':$i,'inicio':float($SS),'duracao_arquivo_s':float($DP),
           'parte_s':float($PARTE),'overlap_s':float($OVERLAP)},
          open('$P/fatia.json','w'))"
  done
fi

python3 "$AQUI/remontar.py" "$OUTDIR" --audio "$AUDIO" >/dev/null

if $VERIFICAR; then
  python3 "$AQUI/verificar-transcricao.py" "$OUTDIR" --audio "$AUDIO"
else
  echo "$OUTDIR/transcript.json"
fi
