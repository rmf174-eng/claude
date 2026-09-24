#!/usr/bin/env bash
# download-images — baixa os slides de um carrossel/foto do Instagram
# a partir do dump bruto do Apify (apify-posts.json do profile-extract).
#
# Uso:
#   download-images.sh <dir-do-perfil> <post-id> [outdir]
#
# Saída (no outdir, default <dir-do-perfil>/posts/<post-id>/):
#   slide-01.jpg, slide-02.mp4, ...  — slides na ordem do carrossel
#   meta.json                        — normalizado (schema benchmark.post.meta/v1)
#
# Atenção: as URLs de CDN do Instagram expiram em alguns dias — se o curl
# falhar com 403, rode o extract-apify-instagram.sh de novo pra renovar.
set -euo pipefail

PROFILE_DIR="${1:?Uso: download-images.sh <dir-do-perfil> <post-id> [outdir]}"
POST_ID="${2:?Uso: download-images.sh <dir-do-perfil> <post-id> [outdir]}"
OUTDIR="${3:-$PROFILE_DIR/posts/$POST_ID}"
RAW="$PROFILE_DIR/apify-posts.json"

[[ -s "$RAW" ]] || { echo "ERRO: $RAW não existe — rode extract-apify-instagram.sh antes." >&2; exit 1; }

ITEM="$(jq --arg id "$POST_ID" '[.[] | select(.shortCode == $id)][0]' "$RAW")"
[[ "$ITEM" != "null" ]] || { echo "ERRO: post $POST_ID não encontrado em $RAW." >&2; exit 1; }

PTYPE="$(jq -r '.type' <<<"$ITEM")"
case "$PTYPE" in
  Sidecar|Image) ;;
  *) echo "ERRO: post $POST_ID é do tipo $PTYPE — pra vídeo use o download.sh." >&2; exit 1 ;;
esac

mkdir -p "$OUTDIR"

# --- baixar slides na ordem -------------------------------------------------
jq -r '
  (if .type == "Sidecar"
   then [.childPosts[] | if .type == "Video"
                         then {url: .videoUrl, ext: "mp4"}
                         else {url: .displayUrl, ext: "jpg"} end]
   else [{url: .displayUrl, ext: "jpg"}]
   end)
  | to_entries[]
  | select(.value.url != null)
  | "\(.key + 1)\t\(.value.ext)\t\(.value.url)"
' <<<"$ITEM" | while IFS="$(printf '\t')" read -r n ext url; do
  f="$OUTDIR/slide-$(printf '%02d' "$n").$ext"
  if [[ -s "$f" ]]; then
    echo ">> $(basename "$f") já existe, pulando." >&2
    continue
  fi
  curl -sS -L --fail -o "$f" "$url" || {
    echo "ERRO baixando slide $n — URL de CDN provavelmente expirou; rode o extract de novo." >&2
    rm -f "$f"
    exit 1
  }
done

# --- meta.json normalizado ---------------------------------------------------
SLIDES_JSON="$(cd "$OUTDIR" && ls slide-* 2>/dev/null | sort | jq -R . | jq -s .)"

jq --arg fetched_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson slides "$SLIDES_JSON" '{
  schema: "benchmark.post.meta/v1",
  platform: "instagram",
  id: .shortCode,
  url: (.url // ("https://www.instagram.com/p/" + .shortCode + "/")),
  type: (if .type == "Sidecar" then "carousel" else "photo" end),
  title: null,
  caption: (.caption // null),
  author: {
    handle: (.ownerUsername // null),
    name: (.ownerFullName // null)
  },
  upload_date: ((.timestamp // "") | if length >= 10 then .[0:10] else null end),
  duration_s: null,
  metrics: {
    views: null,
    likes: (.likesCount // null),
    comments: (.commentsCount // null),
    shares: null
  },
  files: { slides: $slides },
  fetched_at: $fetched_at
}' <<<"$ITEM" > "$OUTDIR/meta.json"

echo "$OUTDIR"
