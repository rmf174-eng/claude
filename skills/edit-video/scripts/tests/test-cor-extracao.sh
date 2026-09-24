#!/usr/bin/env bash
# test-cor-extracao.sh — a bateria da SPEC-25 §8.
#
#   bash .claude/skills/edit-video/scripts/tests/test-cor-extracao.sh [--rapido]
#
# AUTOCONTIDA de propósito. Ela sintetiza a própria fonte HLG com `testsrc2` e não
# lê `creators/`, `data/` nem `intelligence/` — um cliente do produto não tem nenhum
# dos três, e um teste que precisa da nossa instalação não é teste do mecanismo
# (FRONTEIRA §2). Onde o material real do repo existe, ele é usado só para conferir
# os NÚMEROS medidos; onde não existe, o teste diz SKIP e conta o skip.
#
# 🔴 Todo teste imprime QUANTO varreu, e cinco dos oito plantam um defeito que a
# ferramenta TEM que acusar. Um verificador que varre 0 e sai 0 é indistinguível de
# um quebrado — e a `peca-01` já teve um QC que se auto-neutralizou e imprimiu
# "varredura limpa".
set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$(dirname "$AQUI")"
# Na árvore canônica, três níveis chegam ao pacote. Na instalação Claude,
# existe o prefixo extra `.claude/`, então são quatro. Resolver pela presença da
# LUT faz a mesma bateria realmente rodar nos dois caminhos exportados.
RAIZ="$(cd "$S/../../.." && pwd)"
if [ ! -f "$RAIZ/tools/remotion-compositor/luts/hlg2sdr.cube" ]; then
  RAIZ="$(cd "$S/../../../.." && pwd)"
fi
RAPIDO=""
[ "${1:-}" = "--rapido" ] && RAPIDO=1

T="$(mktemp -d)"
OK=0; FALHOU=0; PULOU=0
declare -a NOMES_FALHOS=()
# contadores do "o que este teste varreu"
N_CADEIAS=0; N_GUARDAS=0; N_SEGS=0; N_DEFEITOS=0; N_ACUSADOS=0

ok()    { OK=$((OK+1));    printf '   ✅ %s\n' "$1"; }
falha() { FALHOU=$((FALHOU+1)); NOMES_FALHOS+=("$1"); printf '   ❌ %s\n' "$1"; [ $# -gt 1 ] && printf '      %s\n' "$2"; }
pula()  { PULOU=$((PULOU+1)); printf '   ⏭️  %s\n' "$1"; }
md5rgb(){ ffmpeg -nostdin -v error -i "$1" -f rawvideo -pix_fmt rgb24 - 2>/dev/null | md5 2>/dev/null || \
          ffmpeg -nostdin -v error -i "$1" -f rawvideo -pix_fmt rgb24 - 2>/dev/null | md5sum | cut -d' ' -f1; }
# ⚠️ `csv=p=0` às vezes emite uma vírgula sobrando no fim (depende do build e do
# número de campos que o stream declara). Comparar a string crua dá falso negativo
# — foi o primeiro defeito desta própria bateria.
tags()  { ffprobe -v error -select_streams v:0 -show_entries stream=color_space,color_transfer,color_primaries -of csv=p=0 "$1" 2>/dev/null | tr -d '\n' | sed 's/,*$//'; }
e709()  { [ "$(tags "$1")" = "bt709,bt709,bt709" ]; }

LUT="$RAIZ/tools/remotion-compositor/luts/hlg2sdr.cube"
[ -f "$LUT" ] || { echo "sem $LUT — a bateria de cor não roda"; exit 64; }

# ── a fonte sintética: HLG declarada, 10 bits, retrato ────────────────────────
FONTE="$T/hlg.mp4"
ffmpeg -nostdin -v error -y -f lavfi -i "testsrc2=size=1080x1920:rate=30:duration=3" \
  -vf "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc" \
  -c:v libx264 -crf 16 -preset ultrafast -pix_fmt yuv420p10le "$FONTE" || exit 1
# ⚠️ a fonte SDR nasce NO ASPECTO DO ALVO de propósito. A guarda de aspecto da
# SPEC-06 aborta uma fonte 16:9 num perfil 9:16 (r = 3,16 > 2,00) — e ela está
# certa. Esta bateria é de COR; misturar o teste de enquadramento aqui faria a
# falha do aspecto parecer falha de cor.
FONTE_SDR="$T/sdr.mp4"
ffmpeg -nostdin -v error -y -f lavfi -i "testsrc2=size=1080x1920:rate=30:duration=3" \
  -vf "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
  -c:v libx264 -crf 18 -preset ultrafast -pix_fmt yuv420p "$FONTE_SDR" || exit 1

echo "══════════════════════════════════════════════════════════════════════════"
echo " SPEC-25 · cor na extração — bateria"
echo " fonte sintética: $(tags "$FONTE") 1080x1920 10-bit · sandbox $T"
echo "══════════════════════════════════════════════════════════════════════════"

# ═══ 1. A ORDEM DO FILTERGRAPH É CARREGADA — as variantes TÊM que divergir ════
echo
echo "1 · a ordem do filtergraph carrega sinal (4 cadeias, md5 do rawvideo rgb24)"
TAG="setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
enc(){ ffmpeg -nostdin -v error -y -i "$FONTE" -an -vf "$2" \
         -c:v libx264 -crf 16 -preset ultrafast -pix_fmt yuv420p "$T/$1.mp4"; N_CADEIAS=$((N_CADEIAS+1)); }
enc certa   "scale=1080:1920,setsar=1,fps=30,format=yuv420p,lut3d=$LUT,$TAG"
enc sem8    "scale=1080:1920,setsar=1,fps=30,lut3d=$LUT,$TAG"
enc antes   "format=yuv420p,lut3d=$LUT,scale=1080:1920,setsar=1,fps=30,$TAG"
enc potag   "scale=1080:1920,setsar=1,fps=30,$TAG,format=yuv420p,lut3d=$LUT"
M_CERTA=$(md5rgb "$T/certa.mp4")
for v in sem8 antes potag; do
  N_DEFEITOS=$((N_DEFEITOS+1))
  if [ "$(md5rgb "$T/$v.mp4")" = "$M_CERTA" ]; then
    falha "variante '$v' é idêntica à cadeia certa" \
          "se a ordem não muda a imagem, uma das travas do contrato-cor.md §3 não existe mais"
  else
    N_ACUSADOS=$((N_ACUSADOS+1)); ok "variante '$v' diverge da cadeia certa (a trava tem efeito)"
  fi
done

# ═══ 2. O montar.sh REPRODUZ a cadeia certa, bit a bit ════════════════════════
echo
echo "2 · o montar.sh reproduz a cadeia certa BIT A BIT (a costura não inventa nada)"
D="$T/p1"; mkdir -p "$D/input"; cp "$FONTE" "$D/input/hlg.mp4"
printf '[{"src":"input/hlg.mp4","start":0.0,"end":2.0,"beat":"a"}]\n' > "$D/edl.json"
python3 "$S/detect-cor.py" resolver "$D" >/dev/null 2>&1
bash "$S/montar.sh" "$D" --perfil reels >/dev/null 2>"$T/p1.err"
N_SEGS=$((N_SEGS+$(ls "$D"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')))
if [ -f "$D/segs/seg000.mp4" ]; then
  ffmpeg -nostdin -v error -y -ss 0.0 -t 2.0 -i "$FONTE" -an \
    -vf "scale=1080:1920,setsar=1,fps=30,format=yuv420p,lut3d=$LUT,$TAG" \
    -c:v libx264 -crf 16 -preset medium -pix_fmt yuv420p "$T/mao.mp4"
  if [ "$(md5rgb "$D/segs/seg000.mp4")" = "$(md5rgb "$T/mao.mp4")" ]; then
    ok "seg000 == cadeia calibrada montada à mão"
  else
    falha "seg000 difere da cadeia calibrada" "vf usado: $(grep -m1 'seg0 ' "$T/p1.err")"
  fi
  e709 "$D/v1-montado.mp4" \
    && ok "v1-montado sai bt709 ×3" || falha "v1-montado saiu $(tags "$D/v1-montado.mp4")"
  [ "$(python3 -c "import json;print(json.load(open('$D/cor.json'))['aplicada_em'])")" = "extracao" ] \
    && ok "cor.json promovido a aplicada_em=extracao" || falha "cor.json não foi promovido"
else
  falha "montar.sh não produziu segs/seg000.mp4" "$(tail -3 "$T/p1.err")"
fi

# ═══ 3. AS GUARDAS DA COSTURA ═════════════════════════════════════════════════
echo
echo "3 · guardas da costura (defeito plantado em cada uma)"
# 3a — aplicar_em inválido
python3 - "$D" <<'PY'
import json,sys,os
p=json.load(open(os.path.join(sys.argv[1],"perfil.json")))
p.setdefault("cor",{})["aplicar_em"]="bananinha"
json.dump(p,open(os.path.join(sys.argv[1],"perfil.json"),"w"),indent=1,ensure_ascii=False)
PY
N_GUARDAS=$((N_GUARDAS+1)); N_DEFEITOS=$((N_DEFEITOS+1))
bash "$S/montar.sh" "$D" >/dev/null 2>"$T/inv.err"
if [ $? -ne 0 ] && grep -q "aplicar_em" "$T/inv.err"; then
  N_ACUSADOS=$((N_ACUSADOS+1)); ok "aplicar_em inválido aborta a montagem (o _schema.json não pega isto — ver contrato-cor.md §9)"
else
  falha "aplicar_em='bananinha' NÃO abortou" "$(tail -2 "$T/inv.err")"
fi
rm -f "$D/perfil.json"

# 3b — unsharp antes da conversão (só existe com AMPLIAÇÃO real)
DU="$T/p-unsharp"; mkdir -p "$DU/input"
ffmpeg -nostdin -v error -y -i "$FONTE" -vf "scale=540:960" -c:v libx264 -crf 18 \
  -preset ultrafast -pix_fmt yuv420p "$DU/input/pequeno.mp4"
printf '[{"src":"input/pequeno.mp4","start":0.0,"end":1.5,"beat":"a"}]\n' > "$DU/edl.json"
python3 "$S/detect-cor.py" resolver "$DU" >/dev/null 2>&1
python3 "$S/perfil.py" resolver "$DU" --perfil reels >/dev/null 2>&1
python3 - "$DU" <<'PY'
import json,sys,os
c=os.path.join(sys.argv[1],"perfil.json"); p=json.load(open(c))
p["video"]["unsharp"]="unsharp=5:5:0.55:5:5:0.0"; p.pop("_procedencia",None)
json.dump(p,open(c,"w"),indent=1,ensure_ascii=False)
PY
N_GUARDAS=$((N_GUARDAS+1)); N_DEFEITOS=$((N_DEFEITOS+1))
bash "$S/montar.sh" "$DU" >/dev/null 2>"$T/uns.err"; EC=$?
NS=$(ls "$DU"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')
if [ "$EC" -ne 0 ] && [ "$NS" = "0" ] && grep -q "unsharp" "$T/uns.err"; then
  N_ACUSADOS=$((N_ACUSADOS+1)); ok "unsharp antes da conversão aborta (−1,53% medido), 0 segmento renderizado"
else
  falha "unsharp antes da conversão não abortou (exit $EC, $NS segs)"
fi
bash "$S/montar.sh" "$DU" --permitir-unsharp-antes-da-cor >/dev/null 2>"$T/uns2.err"
grep -q "autorizado por flag" "$T/uns2.err" \
  && ok "--permitir-unsharp-antes-da-cor libera E avisa" \
  || falha "a flag de escape não avisou"
N_SEGS=$((N_SEGS+$(ls "$DU"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')))

# ═══ 4. O PORTÃO MORDE — fonte PQ aborta antes de renderizar ══════════════════
echo
echo "4 · o portão de cor (calibrado:false) aborta ANTES do primeiro ffmpeg"
DP="$T/pq"; mkdir -p "$DP/input"
ffmpeg -nostdin -v error -y -i "$FONTE" \
  -vf "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc" \
  -c:v libx264 -crf 20 -preset ultrafast -pix_fmt yuv420p10le "$DP/input/pq.mp4"
printf '[{"src":"input/pq.mp4","start":0.0,"end":1.5,"beat":"a"}]\n' > "$DP/edl.json"
python3 "$S/detect-cor.py" resolver "$DP" >/dev/null 2>&1
N_GUARDAS=$((N_GUARDAS+1)); N_DEFEITOS=$((N_DEFEITOS+1))
bash "$S/montar.sh" "$DP" --perfil reels >"$T/pq.out" 2>"$T/pq.err"; EC=$?
NS=$(ls "$DP"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')
if [ "$EC" -ne 0 ] && [ "$NS" = "0" ] && grep -q "calibrado: false" "$T/pq.err"; then
  N_ACUSADOS=$((N_ACUSADOS+1)); ok "PQ aborta com 'calibrado: false' e 0 segmento renderizado"
else
  falha "o portão não mordeu (exit $EC, $NS segs)" "$(tail -3 "$T/pq.err")"
fi
NTM=$(cat "$T/pq.out" "$T/pq.err" | grep -c "tonemap=" || true)
[ "$NTM" = "0" ] && ok "nenhum filtro 'tonemap=' foi proposto ou executado" \
                 || falha "vazou um tonemapper na saída do portão ($NTM)"
bash "$S/montar.sh" "$DP" --perfil reels --sem-cor >/dev/null 2>"$T/pqsem.err"
grep -q "ATENÇÃO" "$T/pqsem.err" \
  && ok "--sem-cor sobre fonte HDR grita o rótulo mentiroso antes de produzi-lo" \
  || falha "--sem-cor não avisou sobre pixels HDR com rótulo de saída"

# ═══ 5. EDL DE FONTES MISTAS ══════════════════════════════════════════════════
echo
echo "5 · EDL de fontes mistas (HLG + BT.709 no mesmo timeline)"
DM="$T/misto"; mkdir -p "$DM/input"
cp "$FONTE" "$DM/input/hlg.mp4"; cp "$FONTE_SDR" "$DM/input/sdr.mp4"
cat > "$DM/edl.json" <<'JSON'
[{"src":"input/hlg.mp4","start":0.0,"end":1.0,"beat":"a"},
 {"src":"input/sdr.mp4","start":0.0,"end":1.0,"beat":"b"},
 {"src":"input/hlg.mp4","start":1.2,"end":2.2,"beat":"c"}]
JSON
python3 "$S/detect-cor.py" resolver "$DM" >/dev/null 2>&1
NF=$(python3 -c "import json;print(len(json.load(open('$DM/cor.json'))['fontes']))")
[ "$NF" = "2" ] && ok "cor.json resolveu 2 fontes distintas da EDL" || falha "fontes{} tem $NF entradas"
bash "$S/montar.sh" "$DM" --perfil reels >/dev/null 2>"$T/misto.err"
N_SEGS=$((N_SEGS+$(ls "$DM"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')))
grep -q "mistura %d perfis\|mistura 2 perfis" "$T/misto.err" \
  && ok "o aviso de mistura de perfis foi impresso com a contagem" \
  || falha "não avisou a mistura de perfis" "$(grep -m1 'cor:' "$T/misto.err")"
V0=$(grep -m1 "seg0 " "$T/misto.err"); V1=$(grep -m1 "seg1 " "$T/misto.err")
case "$V0" in *lut3d*) ok "o segmento HLG carrega lut3d no vf" ;; *) falha "o segmento HLG NÃO carrega lut3d" ;; esac
case "$V1" in *lut3d*) falha "o segmento BT.709 carrega lut3d (conversão indevida)" ;; *) ok "o segmento BT.709 não carrega lut3d" ;; esac
e709 "$DM/v1-montado.mp4" \
  && ok "o montado de fontes mistas sai bt709 ×3" || falha "montado misto saiu $(tags "$DM/v1-montado.mp4")"

# ═══ 6. CACHE: cor_sha invalida quando a CURVA muda ═══════════════════════════
echo
echo "6 · cache por cor_sha (a .cube regravada NO LUGAR tem que refazer)"
bash "$S/montar.sh" "$DM" --perfil reels >/dev/null 2>"$T/c1.err"
R1=$(grep -c "refazendo\|segmento mudou" "$T/c1.err" || true)
[ "$R1" = "0" ] && ok "remontar sem mudar nada re-renderiza 0 segmentos" \
                || falha "remontagem idempotente re-renderizou $R1"
SHA_ANTES=$(python3 -c "import json;print(json.load(open('$DM/segs/seg000.json'))['cor_sha'])")
# 🔴 A .cube REAL não se toca (regravar `luts/hlg2sdr.cube` mudaria a curva de
# todas as produções). O teste monta um repo FALSO com a mesma estrutura relativa
# — `raiz_repo()` é `dir_luts()/../../..`, então o espelho precisa ter os três
# níveis, senão o caminho relativo do catálogo não resolve e o portão aborta por
# "LUT não existe" em vez de exercitar o cache.
ESP="$T/repo-espelho/tools/remotion-compositor/luts"; mkdir -p "$ESP"
cp "$RAIZ/tools/remotion-compositor/luts/"*.cube "$ESP/" 2>/dev/null
cp "$RAIZ/tools/remotion-compositor/luts/catalogo-cor.json" "$ESP/" 2>/dev/null
printf '\n# curva trocada pelo teste (mesmo NOME, bytes diferentes)\n' >> "$ESP/hlg2sdr.cube"
N_DEFEITOS=$((N_DEFEITOS+1))
BENCH_LUTS_DIR="$ESP" python3 "$S/detect-cor.py" resolver "$DM" >/dev/null 2>&1
BENCH_LUTS_DIR="$ESP" bash "$S/montar.sh" "$DM" --perfil reels >/dev/null 2>"$T/c2.err"
SHA_DEPOIS=$(python3 -c "import json;print(json.load(open('$DM/segs/seg000.json'))['cor_sha'])")
R2=$(grep -c "a COR de .* mudou (cor_sha" "$T/c2.err" || true)
if [ "$SHA_ANTES" != "$SHA_DEPOIS" ] && [ "$R2" -gt 0 ]; then
  N_ACUSADOS=$((N_ACUSADOS+1)); ok "curva regravada com o mesmo nome muda o cor_sha, refaz e NOMEIA a causa ($R2 segmento(s))"
else
  falha "cor_sha não invalidou o cache" "antes=$SHA_ANTES depois=$SHA_DEPOIS avisos=$R2"
fi
N_SEGS=$((N_SEGS+$(ls "$DM"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')))

# ═══ 7. qc-cor: estágio declarado + LUT dupla + rótulo mentiroso ══════════════
echo
echo "7 · qc-cor.py — estágio por aplicada_em, LUT dupla e rótulo mentiroso"
if ! command -v avconvert >/dev/null 2>&1; then
  pula "avconvert ausente — a seção 5 do qc-cor (LUT dupla) exige a referência Apple"
else
  cp "$D/v1-montado.mp4" "$D/v1-sdr.mp4" 2>/dev/null
  # ⚠️ O DEFEITO PLANTADO NÃO É A LUT DE VERDADE, e isso é deliberado.
  # A assinatura −23,7% é uma propriedade da curva hlg2sdr APLICADA A CONTEÚDO
  # REAL. Sobre `testsrc2` a mesma LUT dupla move só −4,0% (medido) — a carta de
  # cores sintética não vive na parte da curva que morde. Plantar a LUT aqui
  # testaria a FÍSICA da curva, que não é o assunto; o assunto é se o detector
  # acusa um alvo sem look que caiu abaixo do limiar. Por isso o defeito é uma
  # queda calibrada de ~24% (o mesmo fator 0,763 medido em §2.5.7), aplicada por
  # `eq`, que é reprodutível em qualquer conteúdo e em qualquer máquina.
  ffmpeg -nostdin -v error -y -i "$D/v1-montado.mp4" -vf "eq=brightness=-0.12:contrast=0.90" \
    -c:v libx264 -crf 20 -preset ultrafast -pix_fmt yuv420p -an "$D/v1-sdr-dupla.mp4"
  # e a LUT de verdade fica ao lado, como informação — sem asserção sobre ela
  ffmpeg -nostdin -v error -y -i "$D/v1-montado.mp4" -vf "lut3d=$LUT" \
    -c:v libx264 -crf 20 -preset ultrafast -pix_fmt yuv420p -an "$T/lut-dupla-real.mp4"
  N_DEFEITOS=$((N_DEFEITOS+1))
  python3 "$S/qc-cor.py" "$D" --bruto input/hlg.mp4 --amostras 8 >"$T/qc.out" 2>&1
  if grep -q "CONVERSÃO APLICADA DUAS VEZES" "$T/qc.out"; then
    N_ACUSADOS=$((N_ACUSADOS+1)); ok "o qc-cor acusa o alvo sem look que caiu abaixo do limiar"
  else
    falha "o qc-cor NÃO acusou a queda de ~24% num alvo sem look" \
          "$(sed -n '/═══ 5/,$p' "$T/qc.out" | head -5)"
  fi
  # controle POSITIVO: o montado correto NÃO pode ser acusado
  grep -qE "✅ v1-montado\.mp4" "$T/qc.out" \
    && ok "o v1-montado correto passa (o detector não acusa o caso bom)" \
    || falha "o detector acusou o v1-montado correto (falso positivo)"
  grep -q "estágio pos (declarado)" "$T/qc.out" \
    && ok "segs/* foram julgados pelo estágio DECLARADO (aplicada_em=extracao)" \
    || falha "o estágio declarado não chegou aos segs/*"
  # e o rótulo mentiroso, o defeito de 2026-08-06 sintetizado
  ffmpeg -nostdin -v error -y -i "$D/v1-montado.mp4" -c copy \
    -bsf:v h264_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9 \
    "$D/v1-graded-mentiroso.mp4" 2>/dev/null
  N_DEFEITOS=$((N_DEFEITOS+1))
  python3 "$S/qc-cor.py" "$D" --bruto input/hlg.mp4 --amostras 8 >"$T/qc2.out" 2>&1
  if grep -q "v1-graded-mentiroso.mp4" "$T/qc2.out" && grep -q "❌ v1-graded-mentiroso" "$T/qc2.out"; then
    N_ACUSADOS=$((N_ACUSADOS+1)); ok "o qc-cor acusa o rótulo mentiroso (pixels SDR marcados HLG)"
  else
    falha "o rótulo mentiroso passou" "$(grep -m2 mentiroso "$T/qc2.out")"
  fi
fi

# ═══ 8. O FALLBACK continua congelado ═════════════════════════════════════════
echo
echo "8 · produção SEM perfil.json não converte nada (byte a byte igual ao passado)"
DF="$T/fallback"; mkdir -p "$DF/input"; cp "$FONTE" "$DF/input/hlg.mp4"
printf '[{"src":"input/hlg.mp4","start":0.0,"end":1.0,"beat":"a"}]\n' > "$DF/edl.json"
python3 "$S/detect-cor.py" resolver "$DF" >/dev/null 2>&1
bash "$S/montar.sh" "$DF" >/dev/null 2>"$T/fb.err"
N_SEGS=$((N_SEGS+$(ls "$DF"/segs/seg*.mp4 2>/dev/null | wc -l | tr -d ' ')))
V=$(grep -m1 "seg0 " "$T/fb.err")
case "$V" in
  *lut3d*) falha "o FALLBACK converteu — isso muda os bytes de toda remontagem antiga" ;;
  *)       ok "o FALLBACK (aplicar_tags_por=opcoes-de-saida) não converte nada" ;;
esac
grep -q "aplicar_tags_por\|opcoes-de-saida" "$T/fb.err" \
  && ok "e diz por que não converteu, em voz alta" \
  || falha "o FALLBACK não converteu e não explicou (silêncio é o defeito)"

# ═══ o que este teste varreu ══════════════════════════════════════════════════
echo
echo "── o que este teste varreu ──"
printf '   %-42s %d\n' "cadeias de filtro comparadas por md5"  "$N_CADEIAS"
printf '   %-42s %d\n' "guardas exercitadas"                   "$N_GUARDAS"
printf '   %-42s %d\n' "segmentos realmente renderizados"      "$N_SEGS"
printf '   %-42s %d\n' "defeitos PLANTADOS"                    "$N_DEFEITOS"
printf '   %-42s %d\n' "defeitos plantados que foram ACUSADOS" "$N_ACUSADOS"
printf '   %-42s %d / %d / %d\n' "ok / falhou / pulou"         "$OK" "$FALHOU" "$PULOU"
echo "   sandbox preservado em $T (nada é apagado — /tmp é efêmero)"
if [ "$N_DEFEITOS" -ne "$N_ACUSADOS" ]; then
  echo
  echo "🔴 $((N_DEFEITOS - N_ACUSADOS)) defeito(s) plantado(s) NÃO foram acusados."
fi
if [ "$FALHOU" -gt 0 ]; then
  echo
  echo "FALHOU ($FALHOU): ${NOMES_FALHOS[*]}"
  exit 1
fi
echo
echo "tudo verde ($OK asserções, $PULOU pulada(s))"
