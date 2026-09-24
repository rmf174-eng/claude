#!/usr/bin/env bash
# transcribe — transcreve vídeo/áudio via Deepgram com timestamps
#
# Uso:
#   transcribe.sh <video.mp4 | audio.mp3 | dir-do-post> [outdir]
#
# Se receber um diretório, usa <dir>/video.mp4 e grava a saída no próprio dir.
# Saída (no outdir):
#   audio.mp3        — áudio extraído (mono 16kHz, só se input era vídeo)
#   transcript.json  — resposta bruta da Deepgram (palavras + timestamps + confiança)
#   transcript.md    — texto completo + utterances com timestamps [mm:ss]
#
# Credencial:
#   DEEPGRAM_API_KEY — obrigatória; ambiente vence $ILHA_HOME/.env
#   BENCH_DG_MODEL   — default: nova-3
#   BENCH_DG_LANG    — default: multi (PT/EN misturado). Pra forçar pt puro:
#                      BENCH_DG_MODEL=nova-2 BENCH_DG_LANG=pt-BR
set -euo pipefail

INPUT="${1:?Uso: transcribe.sh <midia|dir> [outdir]}"
MODEL="${BENCH_DG_MODEL:-nova-3}"
LANG_PARAM="${BENCH_DG_LANG:-multi}"
AQUI="$(cd "$(dirname "$0")" && pwd)"

# O resolvedor central não imprime a chave: ele substitui o processo atual e
# injeta a credencial somente neste transcritor. Funciona tanto na fonte
# (`skills/...`) quanto no pacote (`.claude/skills/...`), pois sobe até achar o
# marcador `tools/pacote/chaves.py` em vez de contar níveis fixos.
achar_chaves() {
  local d="$AQUI"
  while [ "$d" != "/" ]; do
    if [ -f "$d/tools/pacote/chaves.py" ]; then
      printf '%s\n' "$d/tools/pacote/chaves.py"
      return 0
    fi
    d="$(dirname "$d")"
  done
  return 1
}

if [ -z "${DEEPGRAM_API_KEY:-}" ]; then
  CHAVES="$(achar_chaves || true)"
  if [ -n "$CHAVES" ] && [ "${ILHA_CHAVES_REEXEC:-}" != "1" ]; then
    export ILHA_CHAVES_REEXEC=1
    exec python3 "$CHAVES" --executar-com DEEPGRAM_API_KEY -- \
      "$AQUI/transcribe.sh" "$@"
  fi
  echo "ERRO: DEEPGRAM_API_KEY não configurada no ambiente nem em \${ILHA_HOME:-~/.config/ilha-de-edicao}/.env" >&2
  exit 1
fi

# --- resolver input/outdir --------------------------------------------------
if [[ -d "$INPUT" ]]; then
  OUTDIR="${2:-$INPUT}"
  INPUT="$INPUT/video.mp4"
else
  OUTDIR="${2:-$(dirname "$INPUT")}"
fi
[[ -s "$INPUT" ]] || { echo "ERRO: arquivo não encontrado: $INPUT" >&2; exit 1; }
mkdir -p "$OUTDIR"

# --- verificador --------------------------------------------------------------
# ⚠️ MUDANÇA DE COMPORTAMENTO (SPEC-01): até 2026-08-08 este script gravava a
# resposta e seguia, sem conferir nada — a verificação existia só como trecho
# copiável na SKILL.md, pro operador rodar na mão. Um vídeo de 50 min que voltasse
# truncado em 30 passava liso, e é por aqui que entram as VSLs longas e as aulas.
# Agora um transcript truncado FAZ O PIPELINE PARAR com exit 1. É o objetivo.
# Escape: BENCH_TRANSCRIBE_SEM_VERIFICAR=1 (o verificador decodifica o áudio, e há
# chamada em lote onde isso pesa).
verificar() {  # $1 = flags extras
  # ⚠️ `[ x ] && return 0` solto sob `set -e` mata o script quando o teste é
  # falso — a AND-list vira o comando e seu exit 1 dispara o errexit. Sempre `if`.
  if [ "${BENCH_TRANSCRIBE_SEM_VERIFICAR:-}" = "1" ]; then return 0; fi
  # shellcheck disable=SC2086  # $1 são flags, têm que separar em palavras
  python3 "$AQUI/verificar-transcricao.py" "$OUTDIR" ${1:-} >/dev/null
}

if [[ -s "$OUTDIR/transcript.json" && -s "$OUTDIR/transcript.md" ]]; then
  echo ">> transcript já existe, pulando (apague pra refazer)." >&2
  # --rapido: só C1+C4, sem decodificar áudio. --nao-gravar porque o artefato já
  # existe e o atalho de idempotência não é hora de reescrevê-lo.
  verificar "--rapido --nao-gravar"
  echo "$OUTDIR/transcript.md"
  exit 0
fi

# --- extrair áudio (se necessário) -------------------------------------------
case "$INPUT" in
  *.mp3|*.wav|*.m4a|*.ogg|*.flac|*.aac)
    AUDIO="$INPUT"
    ;;
  *)
    AUDIO="$OUTDIR/audio.mp3"
    if [[ ! -s "$AUDIO" ]]; then
      # escreve em .part e move no fim — execução interrompida não deixa parcial
      ffmpeg -y -loglevel error -i "$INPUT" -vn -ac 1 -ar 16000 -b:a 48k -f mp3 "$AUDIO.part"
      mv "$AUDIO.part" "$AUDIO"
    fi
    ;;
esac

# --- Deepgram ----------------------------------------------------------------
case "$AUDIO" in
  *.wav) CTYPE="audio/wav" ;;
  *.m4a|*.aac) CTYPE="audio/mp4" ;;
  *.ogg) CTYPE="audio/ogg" ;;
  *.flac) CTYPE="audio/flac" ;;
  *) CTYPE="audio/mpeg" ;;
esac

# --- keyterms (nova-3) -------------------------------------------------------
# Jargão, marca e nome próprio somem ou saem deturpados sem boost (caso medido:
# "peca-04" virou buraco; "VTurb" virou "Veturdo"; "Távora" virou "Tapa").
# BENCH_DG_KEYTERMS aceita termos separados por `;` — vira &keyterm= repetido.
KEYTERM_QS=""
if [ -n "${BENCH_DG_KEYTERMS:-}" ]; then
  OLDIFS="$IFS"; IFS=';'
  for t in $BENCH_DG_KEYTERMS; do
    t="$(printf '%s' "$t" | sed 's/^ *//; s/ *$//')"
    [ -z "$t" ] && continue
    KEYTERM_QS="${KEYTERM_QS}&keyterm=$(printf '%s' "$t" | jq -sRr @uri)"
  done
  IFS="$OLDIFS"
  echo ">> keyterms ativos: $(printf '%s' "$BENCH_DG_KEYTERMS" | tr ';' ',')" >&2
fi

RESPONSE="$(curl -sS -X POST \
  "https://api.deepgram.com/v1/listen?model=${MODEL}&language=${LANG_PARAM}&smart_format=true&paragraphs=true&utterances=true${KEYTERM_QS}" \
  -H "Authorization: Token ${DEEPGRAM_API_KEY}" \
  -H "Content-Type: ${CTYPE}" \
  --data-binary @"$AUDIO")"

if ! jq -e '.results.channels[0].alternatives[0]' <<<"$RESPONSE" >/dev/null 2>&1; then
  echo "ERRO Deepgram:" >&2
  jq -r '.err_msg // .error // .' <<<"$RESPONSE" >&2
  exit 1
fi

printf '%s' "$RESPONSE" > "$OUTDIR/transcript.json"

# --- transcript.md -----------------------------------------------------------
jq -r '
  def pad2: tostring | if length < 2 then "0" + . else . end;
  def ts: floor | "\((. / 60 | floor) | pad2):\((. % 60) | pad2)";
  .results.channels[0].alternatives[0] as $alt
  | .metadata.duration as $dur
  | "# Transcrição",
    "",
    "- Duração: \($dur | floor)s",
    "- Modelo: \(.metadata.model_info[.metadata.models[0]].name // .metadata.models[0] // "?") (\($alt.confidence * 100 | floor)% confiança)",
    "",
    "## Texto completo",
    "",
    ($alt.paragraphs.transcript // $alt.transcript),
    "",
    "## Utterances (timestamps)",
    "",
    (.results.utterances[]? | "- **[\(.start | ts)–\(.end | ts)]** \(.transcript)")
' <<<"$RESPONSE" > "$OUTDIR/transcript.md"

# C1 aqui NÃO é circular: no passe único `metadata.duration` vem do ENGINE, e o
# ffprobe do arquivo é referência independente. (Era no caminho longo que a conta
# virava abs(x-x)/x, porque o script sobrescrevia o campo antes de conferir.)
verificar

echo "$OUTDIR/transcript.md"
