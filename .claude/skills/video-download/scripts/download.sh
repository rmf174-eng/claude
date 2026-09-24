#!/usr/bin/env bash
# video-download — baixa vídeo + metadados normalizados (Instagram, TikTok, YouTube, etc.)
#
# Uso:
#   download.sh <url> [outdir]
#
# Saída (no outdir):
#   video.mp4        — vídeo pronto pra transcrição/análise
#   video.info.json  — dump bruto do yt-dlp
#   video.jpg        — thumbnail
#   meta.json        — metadados normalizados (schema benchmark.post.meta/v1)
#
# Env:
#   BENCH_DATA_DIR   — base de dados (default: $PWD/data). Usado só quando outdir não é passado.
#   BENCH_COOKIES    — caminho pra cookies.txt (formato Netscape). É o caminho RECOMENDADO
#                      pra conteúdo que exige login: não depende do Keychain nem de sessão
#                      interativa, que é onde o --cookies-from-browser quebra num agente.
#   BENCH_BROWSER    — browser pro fallback de cookies (default: chrome)
#
# Sem outdir, salva em $BENCH_DATA_DIR/adhoc/<plataforma>-<id>/.
#
# Autenticação: a maioria dos posts é pública e sai anonimamente. Quando não sair, o script
# tenta, nesta ordem: (1) BENCH_COOKIES, (2) cada perfil do browser que tenha cookie do
# domínio alvo. Se tudo falhar, ele diz QUAL das condições faltou em vez de despejar os
# warnings crípticos do yt-dlp. Ver `diagnose_auth` no fim do arquivo.
set -euo pipefail

URL="${1:?Uso: download.sh <url> [outdir]}"
OUTDIR="${2:-}"
BASE_DIR="${BENCH_DATA_DIR:-$PWD/data}"
BROWSER="${BENCH_BROWSER:-chrome}"
COOKIE_FILE="${BENCH_COOKIES:-}"

# domínio registrável do alvo (instagram.com, tiktok.com...) — usado pra procurar sessão
HOST="$(printf '%s' "$URL" | sed -E 's#^[a-z]+://##i; s#/.*##; s#^www\.##')"

CHROME_DIR="$HOME/Library/Application Support/Google/Chrome"

COOKIE_ARGS=()

# ${arr[@]+...} — expansão segura de array vazio no bash 3.2 do macOS (set -u)
ydl() {
  yt-dlp --no-playlist --no-progress ${COOKIE_ARGS[@]+"${COOKIE_ARGS[@]}"} "$@"
}

probe() {
  ydl -J --no-download "$URL"
}

# Perfis do Chrome que têm cookie do domínio alvo. O yt-dlp assume "Default", que nem sempre
# existe (nesta máquina os perfis são "Profile 1"/"Profile 3") — então achamos na mão.
# O DB fica travado com o Chrome aberto: copiar antes de consultar.
profiles_with_session() {
  [[ -d "$CHROME_DIR" ]] || return 0
  command -v sqlite3 >/dev/null || return 0
  local db tmp n
  for db in "$CHROME_DIR"/*/Cookies; do
    [[ -f "$db" ]] || continue
    tmp="$(mktemp)"
    cp "$db" "$tmp" 2>/dev/null || { rm -f "$tmp"; continue; }
    n="$(sqlite3 "$tmp" "select count(*) from cookies where host_key like '%${HOST}';" 2>/dev/null || echo 0)"
    rm -f "$tmp"
    if [[ "${n:-0}" -gt 0 ]]; then basename "$(dirname "$db")"; fi
  done
  # return explícito: sem isso a função herda o status do último teste e, quando nenhum
  # perfil casa, devolve 1 — o que com `set -e` abortaria o diagnóstico no meio.
  return 0
}

# Só chamado quando TODAS as tentativas falharam. O objetivo é dizer o que falta,
# porque os três motivos possíveis exigem correções diferentes.
diagnose_auth() {
  echo >&2
  echo "!! Não consegui acessar $URL nem anonimamente nem autenticado." >&2
  echo "   O post provavelmente exige login. Estado da autenticação aqui:" >&2

  if [[ -n "$COOKIE_FILE" ]]; then
    if [[ -s "$COOKIE_FILE" ]]; then
      echo "   · BENCH_COOKIES: arquivo existe mas não autenticou (cookies expirados?)." >&2
      echo "     Reexporte o cookies.txt com a sessão logada e tente de novo." >&2
    else
      echo "   · BENCH_COOKIES aponta pra '$COOKIE_FILE', que não existe ou está vazio." >&2
    fi
  else
    echo "   · BENCH_COOKIES não está setada (é o caminho recomendado)." >&2
  fi

  local profs; profs="$(profiles_with_session | paste -sd', ' -)"
  if [[ -n "$profs" ]]; then
    echo "   · Perfis do Chrome com sessão em $HOST: $profs" >&2
    if ! security find-generic-password -w -s "Chrome Safe Storage" >/dev/null 2>&1; then
      echo "     Mas o Keychain negou a chave de descriptografia ('User interaction is not" >&2
      echo "     allowed'): o macOS exige aprovação num diálogo que não aparece em sessão de" >&2
      echo "     agente. Rode uma vez no seu terminal e escolha 'Sempre Permitir':" >&2
      echo "       security find-generic-password -w -s \"Chrome Safe Storage\" >/dev/null" >&2
    fi
  else
    echo "   · Nenhum perfil do Chrome tem cookie de $HOST — não há sessão logada pra usar." >&2
    echo "     Faça login em $HOST no Chrome, ou exporte um cookies.txt e use BENCH_COOKIES." >&2
  fi
  echo >&2
}

# --- 1. Metadados (anônimo → cookies) --------------------------------------
if INFO="$(probe 2>/dev/null)"; then
  :
else
  echo ">> Acesso anônimo falhou; tentando autenticado..." >&2
  INFO=""

  if [[ -n "$COOKIE_FILE" && -s "$COOKIE_FILE" ]]; then
    echo ">> Tentando com BENCH_COOKIES ($COOKIE_FILE)..." >&2
    COOKIE_ARGS=(--cookies "$COOKIE_FILE")
    INFO="$(probe 2>/dev/null)" || INFO=""
  fi

  if [[ -z "$INFO" ]]; then
    while read -r prof; do
      [[ -n "$prof" ]] || continue
      echo ">> Tentando com cookies do $BROWSER:$prof..." >&2
      COOKIE_ARGS=(--cookies-from-browser "$BROWSER:$prof")
      if INFO="$(probe 2>/dev/null)"; then break; else INFO=""; fi
    done <<< "$(profiles_with_session)"
  fi

  if [[ -z "$INFO" ]]; then
    COOKIE_ARGS=()
    diagnose_auth
    exit 1
  fi
fi

PLATFORM="$(jq -r '(.extractor_key // .extractor // "unknown") | ascii_downcase' <<<"$INFO")"
VIDEO_ID="$(jq -r '.id' <<<"$INFO")"

if [[ -z "$OUTDIR" ]]; then
  OUTDIR="$BASE_DIR/adhoc/${PLATFORM}-${VIDEO_ID}"
fi
mkdir -p "$OUTDIR"

# --- 2. Download do vídeo + thumbnail --------------------------------------
if [[ ! -s "$OUTDIR/video.mp4" ]]; then
  ydl \
    -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" \
    --merge-output-format mp4 \
    --write-thumbnail --convert-thumbnails jpg \
    -o "$OUTDIR/video.%(ext)s" \
    "$URL" >&2
else
  echo ">> video.mp4 já existe, pulando download." >&2
fi

printf '%s' "$INFO" > "$OUTDIR/video.info.json"

# --- 3. meta.json normalizado ----------------------------------------------
jq --arg fetched_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
  schema: "benchmark.post.meta/v1",
  platform: ((.extractor_key // .extractor // "unknown") | ascii_downcase),
  id: .id,
  url: (.webpage_url // .original_url),
  title: (.title // null),
  caption: (.description // null),
  author: {
    handle: (.uploader_id // .channel_id // null),
    name: (.uploader // .channel // null)
  },
  upload_date: (
    (.upload_date // "") as $d
    | if ($d | length) == 8
      then $d[0:4] + "-" + $d[4:6] + "-" + $d[6:8]
      else null end
  ),
  duration_s: (.duration // null),
  metrics: {
    views: (.view_count // null),
    likes: (.like_count // null),
    comments: (.comment_count // null),
    shares: (.repost_count // null)
  },
  files: {
    video: "video.mp4",
    thumbnail: "video.jpg",
    info: "video.info.json"
  },
  fetched_at: $fetched_at
}' <<<"$INFO" > "$OUTDIR/meta.json"

echo "$OUTDIR"
