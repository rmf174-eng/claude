#!/usr/bin/env bash
# Extrai a(s) VSL(s) de uma página que usa player VTurb / ConverteAI.
# Resolve teste A/B: descobre todas as variantes, os pesos e baixa cada uma.
#
# Uso: vturb-extract.sh <url-da-pagina> <outdir> [--probe-only]
#
# --probe-only: só mapeia (variantes, pesos, CTAs, tempos) sem baixar o vídeo.
#
# Medido em 2026-08-01 (caso ref-E.com.br): 3 variantes de 33,3% na home,
# convergindo no mesmo corpo — o teste era só da abertura.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "uso: $0 <url-da-pagina> <outdir> [--probe-only]" >&2
  exit 1
fi

PAGE="$1"; OUTDIR="$2"; PROBE="${3:-}"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
mkdir -p "$OUTDIR"

echo ">> baixando a página: $PAGE" >&2
curl -sL --max-time 30 -A "$UA" "$PAGE" -o "$OUTDIR/_page.html"

# A conta é o UUID; o player pode vir como ab-test/<id> (teste) ou players/<id> (único).
ACC=$(grep -oE 'converteai\.net/[0-9a-f-]{36}' "$OUTDIR/_page.html" | head -1 | cut -d/ -f2 || true)
if [ -z "$ACC" ]; then
  echo "!! nenhuma referência ConverteAI/VTurb nesta página" >&2
  exit 1
fi
AB=$(grep -oE 'ab-test/[0-9a-f]{24}' "$OUTDIR/_page.html" | head -1 | cut -d/ -f2 || true)
SINGLE=$(grep -oE 'players/[0-9a-f]{24}' "$OUTDIR/_page.html" | head -1 | cut -d/ -f2 || true)

echo ">> conta ConverteAI: $ACC" >&2

if [ -n "$AB" ]; then
  echo ">> teste A/B detectado: $AB" >&2
  SRC="https://scripts.converteai.net/$ACC/ab-test/$AB/player.js"
else
  echo ">> player único: $SINGLE (sem teste A/B)" >&2
  SRC="https://scripts.converteai.net/$ACC/players/$SINGLE/player.js"
fi

curl -sL --max-time 30 -A "$UA" -e "$PAGE" "$SRC" -o "$OUTDIR/_player.js"

# Achar o media_id. Existem DUAS estruturas de player em produção e elas diferem:
#
#   (a) smartplayer-wc/v4 + ab-test  → os media_id aparecem em .../<media_id>/poster.jpg
#   (b) smartplayer.min.js (player único, versão antiga) → NÃO tem poster por mídia;
#       o único ObjectId útil está solto no bundle, junto com o do player e o do thumb.
#
# Por isso: tenta o poster primeiro (barato e inequívoco) e, se não achar, cai pra sonda —
# testa cada ObjectId do bundle contra o endpoint de mídia e fica com quem responde 200.
grep -oE 'cdn\.converteai\.net/[0-9a-f-]{36}/[0-9a-f]{24}/poster' "$OUTDIR/_player.js" \
  | cut -d/ -f3 | sort -u > "$OUTDIR/_medias.txt" || true

if [ ! -s "$OUTDIR/_medias.txt" ]; then
  echo ">> sem poster por mídia (player antigo?) — sondando os ObjectIds do bundle" >&2
  : > "$OUTDIR/_medias.txt"
  for CAND in $(grep -oE '[0-9a-f]{24}' "$OUTDIR/_player.js" | sort -u); do
    code=$(curl -sL -o /dev/null -w '%{http_code}' --max-time 12 -A "$UA" -e "$PAGE" \
      "https://cdn.converteai.net/$ACC/$CAND/main.m3u8")
    if [ "$code" = "200" ]; then
      echo "   ✓ $CAND é mídia" >&2
      echo "$CAND" >> "$OUTDIR/_medias.txt"
    fi
  done
fi

N=$(wc -l < "$OUTDIR/_medias.txt" | tr -d ' ')
if [ "$N" = "0" ]; then
  echo "!! nenhum media_id encontrado — inspecione $OUTDIR/_player.js à mão" >&2
  exit 1
fi
echo ">> $N mídia(s) encontrada(s)" >&2

# Pesos, CTAs, comportamento e DATAÇÃO — o que o teste está realmente testando.
{
  echo "# Mapa do player — $PAGE"
  echo
  echo "conta: $ACC"
  [ -n "$AB" ] && echo "ab-test: $AB" || echo "player único: $SINGLE"
  echo
  # ---- Estrutura v1 (smartplayer antigo): a config vem num objeto JSON inteiro,
  # não nos campos soltos que os greps abaixo procuram. Medido no Tintim (2026-08-01):
  # sem isto, TODAS as seções seguintes saem vazias e a leitura parece "não tem config".
  python3 - "$OUTDIR/_player.js" <<'PYV1' || true
import json, re, sys
js = open(sys.argv[1], encoding='utf-8', errors='ignore').read()

def grab(var):
    m = re.search(re.escape(var) + r'\s*=\s*\{', js)
    if not m: return None
    i = m.end() - 1; depth = 0
    for j in range(i, len(js)):
        if js[j] == '{': depth += 1
        elif js[j] == '}':
            depth -= 1
            if depth == 0:
                raw = js[i:j+1]; break
    else: return None
    raw = raw.replace('!0', 'true').replace('!1', 'false')
    # escapes hex do JS (\xNN) não são JSON válido
    raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), raw)
    try: return json.loads(raw)
    except Exception: return None

achou = False
for var in ('vTurbOriginalPlayer', 'vTurbAlternativePlayer'):
    p = grab(var)
    if not p: continue
    if not achou:
        print("## Config do player (estrutura v1 — JSON embutido)\n")
        achou = True
    o = p.get('options', {}) or {}
    d = o.get('displays', {}) or {}
    sa = (o.get('smart_autoplays') or [{}])[0]
    rot = 'mobile' if var.endswith('AlternativePlayer') else 'principal'
    print(f"### {rot} — `{p.get('name')}`\n")
    print(f"- device `{p.get('device_type')}` · aspect `{p.get('video_aspect_ratio')}` · "
          f"{o.get('video',{}).get('width')}x{o.get('video',{}).get('height')}")
    print(f"- player `{p.get('id')}` · mídia `{p.get('video_id')}`")
    print(f"- autoplay `{o.get('autoplay')}` · legenda `{o.get('subtitle_active')}` · tema `{o.get('theme')}`")
    print(f"- CTAs no player: **{len(o.get('callAction') or [])}** · pixels: {len(o.get('pixels') or [])}")
    if sa.get('bottom_text'):
        print(f"- smartplay: topo \"{sa.get('top_text')}\" · base \"{sa.get('bottom_text')}\" "
              f"· preview {sa.get('video_start_at')}s→{sa.get('video_end_at')}s")
    ctrl = ['seekbar','seekbar_time','time','play_pause','backward','forward',
            'fullscreen','speed_control','big_play','volume']
    print("- controles: " + ', '.join(f"`{k}`={d.get(k)}" for k in ctrl if k in d))
    for ca in (o.get('callAction') or []):
        print(f"- CTA \"{ca.get('name')}\" @ {ca.get('range',{}).get('start')}s → {ca.get('url')}")
    print()
if achou:
    print("> `seekbar: false` é o equivalente v1 do `progressBar: false` da estrutura nova.\n")
PYV1
  echo "## Variantes (id + peso)"
  grep -oE '\{id:"[0-9a-f]{24}",step:[0-9]+,weight:[0-9.]+' "$OUTDIR/_player.js" | sed 's/{//' | sort -u || true
  echo
  echo "## CTAs e quando aparecem (segundo do vídeo)"
  grep -oE 'content:"[^"]{3,90}"' "$OUTDIR/_player.js" | sort -u | head -20 || true
  grep -oE 'range:\{start:[0-9]+,finish:[^}]*\}' "$OUTDIR/_player.js" | sort -u || true
  echo
  echo "## Comportamento do player (a receita de VSL)"
  grep -oE '(mute|progressBar|verticalVideo|persist_on_video_end|show_to_returning_viewer|disablePause|smartPause):[!]?[01a-z]+' "$OUTDIR/_player.js" | sort -u || true
  echo
  echo "### turbo (velocidade de reprodução — pode ser um SEGUNDO teste A/B)"
  grep -oE 'turbo:\{[^{}]*(\{[^{}]*\}[^{}]*)*\}' "$OUTDIR/_player.js" | head -1 || echo "(sem turbo)"
  echo
  echo "### resume / subtitles"
  grep -oE 'resume:\{[^{}]*\}|subtitles:\{[^{}]*\}' "$OUTDIR/_player.js" | head -2 || true
  echo
  echo "## Destinos dos botões"
  grep -oE 'url:"https?://[^"]+"' "$OUTDIR/_player.js" | sed 's/url://' | sort -u | head -10 || true
  echo
  echo "## Linha do tempo da operação (ObjectId → data de criação)"
  echo
  echo "Os IDs do VTurb são ObjectId do MongoDB: os 4 primeiros bytes são o timestamp Unix."
  echo "Isso data players, mídias, testes e CTAs sem acesso nenhum à conta."
  echo
  grep -oE '[0-9a-f]{24}' "$OUTDIR/_player.js" | sort -u | python3 -c '
import sys
from datetime import datetime, timezone, timedelta
rows=[]
for line in sys.stdin:
    oid=line.strip()
    if len(oid)!=24: continue
    try: ts=int(oid[:8],16)
    except ValueError: continue
    # descarta o que não cai numa janela plausível (2015..2035)
    if not (1420070400 < ts < 2051222400): continue
    rows.append((ts,oid))
rows.sort()
print("| criado em (UTC-3) | ObjectId |")
print("|---|---|")
for ts,oid in rows:
    dt=datetime.fromtimestamp(ts,timezone.utc)-timedelta(hours=3)
    print(f"| {dt:%Y-%m-%d %H:%M:%S} | `{oid}` |")
' || true
} > "$OUTDIR/player-map.md"

if [ "$PROBE" = "--probe-only" ]; then
  cat "$OUTDIR/player-map.md" >&2
  echo "$OUTDIR/player-map.md"
  exit 0
fi

i=0
while read -r M; do
  [ -z "$M" ] && continue
  i=$((i+1))
  D="$OUTDIR/var$i-$M"; mkdir -p "$D"
  if [ -s "$D/video.mp4" ]; then
    echo ">> var$i já baixada, pulando" >&2; continue
  fi
  # main.m3u8 é o que responde 200. master.m3u8 e playlist.m3u8 dão 403 no cdn.
  echo ">> baixando var$i ($M)" >&2
  yt-dlp --no-warnings --user-agent "$UA" --referer "$PAGE" -f "b" -o "$D/video.mp4" \
    "https://cdn.converteai.net/$ACC/$M/main.m3u8" >&2 2>&1 || {
      echo "   !! falhou; tentando m3u8.vturb.net" >&2
      yt-dlp --no-warnings --user-agent "$UA" --referer "$PAGE" -f "b" -o "$D/video.mp4" \
        "https://m3u8.vturb.net/$ACC/$M/playlist.m3u8" >&2 2>&1 || echo "   !! var$i indisponível" >&2
    }
  [ -s "$D/video.mp4" ] && ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$D/video.mp4" \
    | xargs -I{} echo "   var$i: {}s" >&2
done < "$OUTDIR/_medias.txt"

echo "$OUTDIR/player-map.md"
