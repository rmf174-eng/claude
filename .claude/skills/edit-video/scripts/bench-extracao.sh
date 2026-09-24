#!/bin/bash
# bench-extracao.sh — quanto a extração de segmentos ganha com paralelismo, NESTA máquina.
#
# Uso: bench-extracao.sh <dir-producao> [--n 8] [--jobs 1,2,3,4,6] [--limiar 1.8]
#      stdout: a tabela (markdown) + o veredito
#      stderr: progresso
#      sai 1 se o hash do 1º segmento divergir entre rodadas (guarda de determinismo)
#
# ─────────────────────────────────────────────────────────────────────────────
# POR QUE ISTO EXISTE, E POR QUE O `montar.sh` CONTINUA SERIAL
#
# O ref-A extrai em paralelo com `ThreadPoolExecutor` e a heurística
# `jobs = max(1, min(4, cpu_count // 3))` (`render.py:439-440`) — que numa máquina
# de 10 núcleos lógicos dá 3. Eles **não têm benchmark nenhum** disso; o
# comentário em `render.py:417-419` é uma justificativa, não uma medição.
#
# Nós medimos, e a premissa não sobreviveu (SPEC-09 §1.1):
#
#   8 segs HD vertical HEVC  1 job 16,50 s · 2 → 13,22 · 3 → 14,54 · 4 → 13,05 · 6 → 14,67
#   8 segs 4K HEVC           1 job 43,23 s · 2 → 40,35 · 4 → 47,83  (MAIS LENTO)
#
# A causa está no `user/real`: **5,9 no HD e 7,25 no 4K já no modo serial**. O
# `libx264 -preset medium` com threads automáticas já ocupa 6 a 7 dos 10 núcleos
# sozinho; rodar quatro deles ao mesmo tempo não acha CPU ociosa, acha contenção —
# e nos núcleos de eficiência do Apple Silicon o saldo fica NEGATIVO.
#
# Por isso o entregável desta spec é ESTE SCRIPT, e não um executor paralelo: a
# conclusão tem que poder ser REFEITA numa máquina futura (outro número de
# núcleos, outro encoder), não relembrada. O portão está escrito no veredito:
# só vale reabrir o assunto se alguma máquina medir ≥ `--limiar` (default 1,8×).
#
# ⚠️ NADA DE `xargs -P … -I`. Medido: o `xargs` da BSD (o do macOS) tem limite de
# **255 caracteres** por substituição de `-I` e aborta com "command line cannot be
# assembled, too long"; o comando de extração real do caso 4K mede **262**, e
# `-s 65536` NÃO levanta o limite. Funciona ou não conforme o comprimento do
# caminho — a pior forma de bug. Aqui o paralelismo é job de background + `wait`.
#
# ⚠️ E o número que sair daqui é wall-clock: se houver outra coisa pesada rodando
# na máquina, o ganho medido não é o ganho real. Declare a contenção junto do
# número.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
DIR_SCRIPT="$(cd "$(dirname "$0")" && pwd)"
PERFIL="$DIR_SCRIPT/perfil.py"
[ -f "$PERFIL" ] || { echo "perfil.py não encontrado ao lado de $0" >&2; exit 1; }

DIR="${1:-}"
[ -n "$DIR" ] || { sed -n '3,6p' "$0" >&2; exit 64; }
shift
N=8
JOBS_LISTA="1,2,3,4,6"
LIMIAR="1.8"
while [ $# -gt 0 ]; do
  case "$1" in
    --n)      N="$2"; shift 2 ;;
    --jobs)   JOBS_LISTA="$2"; shift 2 ;;
    --limiar) LIMIAR="$2"; shift 2 ;;
    *) echo "flag desconhecida: $1" >&2; exit 64 ;;
  esac
done

cd "$DIR"
# 📐 TODO valor de formato vem do perfil de peça — este script não conhece
# resolução, fps, crf nem pix_fmt. `perfil.py sh` imprime KEY=VALUE; `perfil.py vf`
# monta o filtro de cada segmento. É o MESMO caminho do montar.sh, e é o que faz o
# benchmark medir o comando REAL e não uma aproximação dele.
eval "$(python3 "$PERFIL" sh . 2>/dev/null)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/cmd"

# ── monta um runner por segmento (nunca escreve em segs/ da produção) ─────────
# Um script por segmento em vez de uma linha de comando guardada numa variável:
# o `printf %q` resolve o aspeamento de uma vez e o job de background vira
# `bash cmd/NNN.sh <saida>`, sem eval e sem limite de comprimento.
NSEG=0
while IFS=$'\t' read -r src start end zoom cx cy; do
  [ "$NSEG" -lt "$N" ] || break
  dur="$(python3 -c "print($end-$start)")"
  if [ "$(python3 -c "print(1 if float('$zoom')>1.0001 else 0)")" = "1" ]; then
    SW=$(ffprobe -v error -select_streams v -show_entries stream=width  -of default=nk=1:nw=1 "$src" | head -1)
    SH=$(ffprobe -v error -select_streams v -show_entries stream=height -of default=nk=1:nw=1 "$src" | head -1)
    # bruto de celular: o ffmpeg autorota no decode, o ffprobe reporta o stream
    ROT=$(ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation \
            -of default=nk=1:nw=1 "$src" 2>/dev/null | head -1)
    case "${ROT:-0}" in
      90|-90|270|-270) T="$SW"; SW="$SH"; SH="$T" ;;
    esac
    VF=$(python3 "$PERFIL" vf . --sw "$SW" --sh "$SH" --zoom "$zoom" --cx "$cx" --cy "$cy" --quieto)
  else
    VF=$(python3 "$PERFIL" vf . --quieto)
  fi
  {
    printf '#!/bin/bash\nset -e\n'
    printf 'ffmpeg -nostdin -v error -y -ss %s -t %s -i %s -an -vf %s \\\n' \
      "$(printf '%q' "$start")" "$(printf '%q' "$dur")" \
      "$(printf '%q' "$src")" "$(printf '%q' "$VF")"
    printf '  -c:v libx264 -crf %s -preset %s -pix_fmt %s %s "$1"\n' \
      "$(printf '%q' "$PERFIL_CRF")" "$(printf '%q' "$PERFIL_PRESET")" \
      "$(printf '%q' "$PERFIL_PIXFMT")" "${PERFIL_COLOR_OPTS:-}"
  } > "$TMP/cmd/$NSEG.sh"
  NSEG=$((NSEG+1))
done < <(jq -r 'if type=="array" then . else .segments end
                | .[] | [.src, (.start|tostring), (.end|tostring),
                         ((.zoom // 1)|tostring), ((.cx // 0.5)|tostring),
                         ((.cy // 0.5)|tostring)] | @tsv' edl.json)

[ "$NSEG" -gt 0 ] || { echo "edl.json não rendeu segmento nenhum" >&2; exit 1; }
echo "perfil $PERFIL_NOME · $NSEG segmento(s) de $(basename "$PWD") · saída em $TMP" >&2

_hash() {
  if command -v md5 >/dev/null 2>&1; then md5 -q "$1"
  elif command -v md5sum >/dev/null 2>&1; then md5sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# Tempo de CPU dos FILHOS (2ª linha do `times`: user sys).
# 🐛 SUCESSO SILENCIOSO, medido nesta entrega: `c=$(times | tail -1)` devolve
# **0,00 sempre**. A substituição de comando roda num SUBSHELL, e o `times` de lá
# contabiliza os filhos DAQUELE subshell — que são zero. O número saía zerado, a
# tabela ficava bonita e a coluna `user/real` (que é a explicação inteira do
# porquê o paralelismo não rende) virava enfeite. Por isso o `times` roda no shell
# ATUAL, redirecionado para arquivo, e só a LEITURA é que pode ser subshell.
_marcar_cpu() { times > "$TMP/times.txt"; }
_ler_cpu() {
  awk 'NR==2{ split($1,a,"m"); sub("s","",a[2]); print a[1]*60 + a[2] }' "$TMP/times.txt"
}

_agora() { python3 -c 'import time; print("%.3f" % time.time())'; }

# ── uma rodada com J jobs simultâneos ────────────────────────────────────────
# JANELA DESLIZANTE, não lote: lançar J, esperar TODOS e lançar mais J deixa a
# máquina ociosa no fim de cada lote e mede o segmento mais lento, não o
# paralelismo. `wait -n` resolveria isso em uma linha e NÃO EXISTE no bash 3.2
# (o do macOS) — por isso a espera é por `jobs -pr`, que é o que há em todo lugar.
rodar() {
  local j="$1" out="$2" i
  mkdir -p "$out"
  for i in $(seq 0 $((NSEG-1))); do
    while [ "$(jobs -pr | wc -l | tr -d ' ')" -ge "$j" ]; do sleep 0.05; done
    bash "$TMP/cmd/$i.sh" "$out/$(printf 'seg%03d.mp4' "$i")" &
  done
  wait
}

LINHAS=""
BASE=""
HASH0=""
MELHOR=""
MELHOR_J=""
IFS=',' read -r -a JOBS <<< "$JOBS_LISTA"
for J in "${JOBS[@]}"; do
  OUT="$TMP/j$J"
  rm -rf "$OUT"
  _marcar_cpu; c0="$(_ler_cpu)"; t0="$(_agora)"
  rodar "$J" "$OUT"
  t1="$(_agora)"; _marcar_cpu; c1="$(_ler_cpu)"
  real="$(python3 -c "print('%.2f' % ($t1-$t0))")"
  user="$(python3 -c "print('%.2f' % ($c1-$c0))")"
  h="$(_hash "$OUT/seg000.mp4")"
  if [ -z "$HASH0" ]; then HASH0="$h"; else
    if [ "$h" != "$HASH0" ]; then
      echo "🔴 DETERMINISMO QUEBRADO: seg000 da rodada --jobs $J tem hash $h," >&2
      echo "   a primeira rodada tinha $HASH0. O paralelismo mudou o PIXEL —" >&2
      echo "   qualquer número de tempo abaixo disso não vale nada." >&2
      exit 1
    fi
  fi
  if [ -z "$BASE" ]; then BASE="$real"; fi
  ganho="$(python3 -c "print('%.2f' % ($BASE/$real))")"
  ratio="$(python3 -c "print('%.2f' % ($user/$real if $real>0 else 0))")"
  if [ -z "$MELHOR" ] || [ "$(python3 -c "print(1 if $ganho>$MELHOR else 0)")" = "1" ]; then
    MELHOR="$ganho"; MELHOR_J="$J"
  fi
  echo "  --jobs $J: ${real}s (user ${user}s, user/real $ratio, ganho ${ganho}x)" >&2
  LINHAS="$LINHAS| $J | ${real} s | ${ganho}× | ${user} s | $ratio |
"
  rm -rf "$OUT"
done

NUCLEOS="$(python3 -c 'import os; print(os.cpu_count())')"
echo
echo "### extração de $NSEG segmentos — $(basename "$PWD") ($PERFIL_NOME), $NUCLEOS núcleos lógicos"
echo
echo "| jobs | wall-clock | ganho | user time | user/real |"
echo "|---|---|---|---|---|"
printf '%s' "$LINHAS"
echo
if [ "$(python3 -c "print(1 if $MELHOR>=$LIMIAR else 0)")" = "1" ]; then
  echo "**veredito: paralelizar rende ${MELHOR}× com --jobs $MELHOR_J (≥ ${LIMIAR}×) → COMPENSA.**"
  echo "O desenho do executor paralelo (e as 13 guardas que ele tem que preservar) está na SPEC-09 §3.3."
else
  echo "**veredito: paralelizar rende ${MELHOR}× no melhor caso (--jobs $MELHOR_J), abaixo de ${LIMIAR}× → NÃO compensa nesta máquina.**"
  echo "O \`montar.sh\` continua serial. Reabrir só com um número desta tabela ≥ ${LIMIAR}×."
fi
echo
echo "> hash do seg000 idêntico nas ${#JOBS[@]} rodadas: \`$HASH0\`"
