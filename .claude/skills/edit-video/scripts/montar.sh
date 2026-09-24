#!/bin/bash
# Montagem: edl.json → segs/ → v1-montado.mp4
# Uso: montar.sh [dir-da-producao] [--perfil <nome|caminho.json>]
#                                  [--permitir-aspecto-agressivo]
#                                  [--cor-como <entrada-do-catalogo>] [--sem-cor]
#                                  [--permitir-unsharp-antes-da-cor]
#      (default: cwd; precisa de edl.json com {src,start,end})
# Idempotente por segmento (apaga segs/segNN.mp4 pra refazer um). Pads já embutidos na EDL.
#
# 📐 O FORMATO VEM DO PERFIL DE PEÇA, não daqui (SPEC-00). Resolução, fps, crf,
# preset, pix_fmt, tags de cor, codec e bitrate de áudio saem de <dir>/perfil.json
# via `perfil.py sh`; o filtro de vídeo de cada segmento sai de `perfil.py vf`.
# Sem perfil.json o script cai no FALLBACK, que é 1080x1920@30 com as tags HLG e
# o encode de sempre — ou seja, produção antiga remontada sai igual, byte a byte.
# Pra fixar outro formato:  montar.sh <dir> --perfil vsl   (ou `perfil.py resolver`)
#
# 📐 A JANELA DE ASPECTO (SPEC-06). O bruto é sondado em TODO segmento que vai ser
# renderizado — não só nos com zoom > 1 — porque a janela que o `perfil.py vf`
# recorta precisa ter o aspecto do ALVO antes de qualquer escala. Sem isso uma
# fonte 16:9 num perfil 9:16 saía com 1080x1920 pixels e SAR 256:81 (o ffmpeg
# compensa a deformação no SAR em vez de deformar o conteúdo), e NENHUM QC deste
# repo mede SAR — a peça saía espremida com tudo verde. Fonte cujo aspecto está
# longe demais do alvo ABORTA aqui, em vez de virar a tira do meio em silêncio;
# `--permitir-aspecto-agressivo` é a saída consciente.
#
# 🎨 A COR ENTRA AQUI, NA EXTRAÇÃO (SPEC-25). Da fronteira do primeiro
# segs/segNNN.mp4 até o entregável existe UM espaço de cor: Rec.709. O bruto é o
# único arquivo HDR da produção. O que isso mata é uma CLASSE de defeito, não uma
# ocorrência: enquanto a conversão era um passe à parte sobre o montado, o
# segmento e o montado ficavam HLG e todo re-encode a jusante herdava HLG — foi
# assim que 6 entregáveis saíram da casa dizendo "eu sou HLG em BT.2020" com
# pixels já convertidos (SPEC-25 §1.2). Com o segmento já em bt709, a HERANÇA
# joga a favor: grade, composição e remux saem certos SEM FLAG NENHUMA (§2.5.5).
#
# 🔒 A ORDEM DO FILTERGRAPH NÃO É PREFERÊNCIA — cada trava tem um número medido
# no seg000 da peca-01:
#     …,scale,  format=yuv420p, <conversão>, [setsar,fps,] setparams
#                    ↑ sem ele          ↑ antes do scale        ↑ antes da conversão
#                    +1,8%              +1,5%                   +0,42%
# Os três movem a imagem para longe da única referência calibrada que temos (o
# avconvert da Apple, erro de pele +0,5%). Por isso a costura abaixo INSERE o
# fragmento antes do `setparams` que o perfil.py já pôs no fim do `vf`, e ABORTA
# quando não acha onde inserir — em vez de colar no fim e mover 0,42% em silêncio.
#
# ⚠️ Os segmentos são renderizados SEM ÁUDIO (-an) de propósito, e a trilha é
# montada depois amostra a amostra por audio-exato.py (que também aplica o
# micro-fade de 15ms nas bordas). Motivo: quando cada segmento carregava sua
# própria trilha AAC, o concat ACUMULAVA delay de encoder + quantização de frame
# e o áudio chegava ~0,28s ATRASADO no fim do vídeo — deriva progressiva medida
# na produção peca-03 (2026-07-25): lábios da creator-2 em 60,77s, som do "Comente"
# em 61,01s. Agora soma_audio == soma_video por construção.
# Se mexer aqui, o teste é: vale de energia do áudio em cada emenda vs fronteira
# de frames do vídeo — tem que dar ±3ms SEM tendência ao longo do vídeo.
set -euo pipefail
DIR_SCRIPT="$(cd "$(dirname "$0")" && pwd)"
# acha o audio-exato.py: ao lado deste script OU na skill (a cópia deste .sh na
# pasta da produção é só registro histórico — ela não leva o .py junto)
EXATO="$DIR_SCRIPT/audio-exato.py"
PERFIL="$DIR_SCRIPT/perfil.py"
if [ ! -f "$EXATO" ]; then
  D="$DIR_SCRIPT"
  while [ "$D" != "/" ]; do
    if [ -f "$D/.claude/skills/edit-video/scripts/audio-exato.py" ]; then
      EXATO="$D/.claude/skills/edit-video/scripts/audio-exato.py"
      PERFIL="$D/.claude/skills/edit-video/scripts/perfil.py"
      break
    fi
    D="$(dirname "$D")"
  done
fi
[ -f "$EXATO" ] || { echo "audio-exato.py não encontrado (skill edit-video/scripts)" >&2; exit 1; }
[ -f "$PERFIL" ] || { echo "perfil.py não encontrado (skill edit-video/scripts)" >&2; exit 1; }
# 📐 Os heredocs `python3 - <<'PY'` deste script NÃO conseguem `import edl_io`
# sozinhos: sem arquivo de script, `sys.path[0]` é o CWD (a pasta da produção), e
# não a pasta da skill. Nos .py irmãos o import funciona porque `sys.path[0]` é o
# diretório do próprio script. Daí esta variável — os heredocs abaixo fazem
# `sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])`.
export BENCH_EDIT_SCRIPTS="$(cd "$(dirname "$EXATO")" && pwd)"

# ───────── argumentos ─────────
# `montar.sh` e `montar.sh <dir>` continuam idênticos ao de sempre. As duas flags
# são aditivas e o caminho do --perfil é resolvido para ABSOLUTO antes do `cd`.
DIR_PROD="."
PERFIL_PEDIDO=""
AGRESSIVO=""
COR_COMO=""
SEM_COR=""
COR_UNSHARP_OK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --perfil)
      [ $# -ge 2 ] || { echo "--perfil espera <nome|caminho.json>" >&2; exit 64; }
      PERFIL_PEDIDO="$2"
      case "$PERFIL_PEDIDO" in
        *.json) [ -f "$PERFIL_PEDIDO" ] || { echo "perfil não encontrado: $PERFIL_PEDIDO" >&2; exit 64; }
                PERFIL_PEDIDO="$(cd "$(dirname "$PERFIL_PEDIDO")" && pwd)/$(basename "$PERFIL_PEDIDO")" ;;
      esac
      shift 2 ;;
    --permitir-aspecto-agressivo) AGRESSIVO="--permitir-aspecto-agressivo"; shift ;;
    --cor-como)
      [ $# -ge 2 ] || { echo "--cor-como espera <entrada-do-catalogo>" >&2; exit 64; }
      COR_COMO="$2"; shift 2 ;;
    --sem-cor) SEM_COR="1"; shift ;;
    --permitir-unsharp-antes-da-cor) COR_UNSHARP_OK="1"; shift ;;
    -h|--help) sed -n '2,8p' "$0" >&2; exit 0 ;;
    -*) echo "flag desconhecida: $1 (use --perfil, --permitir-aspecto-agressivo, --cor-como, --sem-cor, --permitir-unsharp-antes-da-cor)" >&2; exit 64 ;;
    *) DIR_PROD="$1"; shift ;;
  esac
done
[ -z "$COR_COMO" ] || [ -z "$SEM_COR" ] || {
  echo "--cor-como e --sem-cor se contradizem: um força uma cadeia, o outro desliga a conversão." >&2
  exit 64; }
cd "$DIR_PROD"
mkdir -p segs

# ───────── --perfil: materializa <dir>/perfil.json ANTES de qualquer render ─────────
# Não há guarda de "perfil divergente" aqui de propósito: quem invalida segmento
# renderizado em outro formato é o `perfil_video_sha` do sidecar (mais abaixo),
# que refaz SÓ o que mudou em vez de exigir `rm -rf segs/` na mão.
if [ -n "$PERFIL_PEDIDO" ]; then
  case "$PERFIL_PEDIDO" in
    *.json)
      python3 "$PERFIL" validar "$PERFIL_PEDIDO" >&2
      cp "$PERFIL_PEDIDO" ./perfil.json
      echo "  perfil fixado a partir de $PERFIL_PEDIDO" >&2 ;;
    *)
      python3 "$PERFIL" resolver . --perfil "$PERFIL_PEDIDO" >/dev/null ;;
  esac
fi

# ───────── perfil de peça: TODO valor de formato entra por aqui ─────────
# `perfil.py sh` imprime KEY=VALUE já com aspas onde precisa. Se não houver
# perfil.json, ele avisa no stderr UMA vez e devolve o FALLBACK histórico.
# ⚠️ em DUAS linhas de propósito: `eval "$(cmd)"` engole o exit code do `cmd` —
# um perfil com fps inválido saía daqui em silêncio e só quebrava depois, no
# `set -u` de uma variável não definida. Assim o abort é aqui, com a mensagem do
# perfil.py na tela e ZERO segmento renderizado.
PERFIL_SH="$(python3 "$PERFIL" sh .)" || exit 1
eval "$PERFIL_SH"
echo "  perfil: $PERFIL_NOME ${PERFIL_W}x${PERFIL_H}@${PERFIL_FPS} crf=$PERFIL_CRF" \
     "áudio ${PERFIL_SR}Hz/${PERFIL_CANAIS}ch spf=$PERFIL_SPF (video_sha $PERFIL_VIDEO_SHA)" >&2

# Produção nova não pode chegar ao primeiro segmento sem um contrato de cor.
# Antes isto era apenas um aviso e uma fonte HDR podia seguir com pixels da
# origem sob tags Rec.709. A ausência agora aciona o resolvedor oficial; qualquer
# baixa confiança, curva não calibrada ou divergência do perfil aborta pelo exit
# code do detector. `--sem-cor` e `--cor-como` continuam sendo escapes explícitos
# e auditáveis, nunca defaults silenciosos.
if [ ! -f cor.json ] && [ -z "$SEM_COR" ] && [ -z "$COR_COMO" ]; then
  echo "  cor.json ausente: resolvendo automaticamente antes da montagem" >&2
  python3 "$BENCH_EDIT_SCRIPTS/detect-cor.py" resolver . >/dev/null || {
    rc=$?
    echo "MONTAGEM ABORTADA: o resolvedor de cor não liberou a produção (exit $rc)." >&2
    echo "Revise cor.json ou use um override explícito; ZERO segmento foi renderizado." >&2
    exit "$rc"
  }
fi

# ───────── PLANO DE COR (SPEC-25): decidido AQUI, antes de qualquer render ─────
# Este bloco é o PORTÃO. Ele roda antes do primeiro ffmpeg de propósito: uma fonte
# não calibrada (PQ, Apple Log) ou detectada com confiança baixa aborta a montagem
# INTEIRA em vez de virar 29 segmentos convertidos por uma curva que ninguém mediu.
# O princípio é o da SPEC-11 um nível acima: "não converta o que você não mediu"
# deixa de ser exit code de detector e vira abort de montagem, que é onde a decisão
# vira pixel.
#
# 📐 Ele NÃO decide formato. O `vf` continua saindo inteiro do `perfil.py vf`
# (SPEC-00) — este plano só diz QUAL fragmento de conversão entra e ONDE.
COR_PLANO="$(pwd)/.cor-plano.json"
BENCH_COR_COMO="$COR_COMO" BENCH_SEM_COR="$SEM_COR" \
python3 - "$COR_PLANO" <<'PY' || exit 1
import hashlib, json, os, sys
sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])
import importlib.util
import edl_io
import perfil as perfil_mod

def _mod(nome, arquivo):
    esp = importlib.util.spec_from_file_location(
        nome, os.path.join(os.environ["BENCH_EDIT_SCRIPTS"], arquivo))
    m = importlib.util.module_from_spec(esp)
    esp.loader.exec_module(m)
    return m

detect_cor = _mod("detect_cor", "detect-cor.py")
destino = sys.argv[1]
forcado = os.environ.get("BENCH_COR_COMO") or ""
sem_cor = bool(os.environ.get("BENCH_SEM_COR"))

P = perfil_mod.carregar(".", quieto=True)
cor_perfil = P.get("cor") or {}
aplicar_em = cor_perfil.get("aplicar_em") or "extracao"
VALIDOS = ("extracao", "passe", "nunca")
if aplicar_em not in VALIDOS:
    sys.exit("perfil.cor.aplicar_em = %r não é um dos %s.\n"
             "Este campo decide se a conversão HDR→SDR acontece na extração; um "
             "valor que ninguém lê é a mesma coisa que um `if` escondido. "
             "Conserte o perfil antes de montar." % (aplicar_em, list(VALIDOS)))

# 🔴 A conversão na extração EXIGE que a tag saia por `setparams`. Motivo medido,
# não estético: com `aplicar_tags_por: "opcoes-de-saida"` (o FALLBACK histórico) a
# tag vai por `-color_primaries/-color_trc/-colorspace`, e neste build 2 das 3 são
# SILENCIOSAMENTE ignoradas — o segmento sairia com pixels bt709 e rótulo
# bt2020nc. Seria fabricar o Frankenstein do §1.2 com as nossas mãos. E é também
# o que mantém a promessa do FALLBACK: produção SEM perfil.json remonta byte a
# byte igual, porque aqui ela não converte nada.
modo_tags = cor_perfil.get("aplicar_tags_por")
soma = {}                       # src distinto → segundos somados (ordem da EDL)
for s in edl_io.segmentos("."):
    if not s.get("src"):
        continue
    try:
        soma[s["src"]] = soma.get(s["src"], 0.0) + (float(s["end"]) - float(s["start"]))
    except (KeyError, TypeError, ValueError):
        soma.setdefault(s["src"], 0.0)

plano = {"aplicada_em": None, "origem": "ausente", "perfis_distintos": [],
         "catalogo_sha256": None, "modo_tags": modo_tags, "por_src": {}}
decisao_path = "cor-decisao.json"

HDR = detect_cor.TRANSFERS_HDR   # um dono só: quem classifica cor é o detector

def sair_sem_cor(motivo, alto=False):
    for src in soma:
        plano["por_src"][src] = {"fragmento": "", "cor_sha": _sha("", []),
                                 "perfil": None, "motivo": motivo}
    if alto:
        print("🔴 " + motivo, file=sys.stderr)
    else:
        print("  cor: " + motivo, file=sys.stderr)
    # 🔴 O RÓTULO MENTIROSO, ACUSADO NA HORA EM QUE NASCE.
    # Sem conversão + perfil que escreve `bt709` por setparams + fonte HDR = o
    # segmento sai com PIXELS HLG e RÓTULO Rec.709. É literalmente o defeito de
    # 2026-08-06 22:59 (13 arquivos), e ele nasce em silêncio: nenhum QC roda
    # dentro do montar.sh. Avisar aqui custa um ffprobe por fonte.
    trc_alvo = ((cor_perfil.get("tags_saida") or {}).get("color_trc") or "").lower()
    if modo_tags == "setparams" and trc_alvo and trc_alvo not in HDR:
        hdr = []
        for src in soma:
            cam = src if os.path.isabs(src) else os.path.join(".", src)
            try:
                st, _t = detect_cor._probe(cam)
            except Exception:
                st = None
            if st and (st.get("color_transfer") or "").lower() in HDR:
                hdr.append((src, st.get("color_transfer")))
        if hdr:
            print("🔴 ATENÇÃO: %d fonte(s) HDR sem conversão, e o perfil escreve "
                  "`color_trc=%s` por setparams. Os segmentos vão sair com PIXELS "
                  "da fonte e RÓTULO de saída — o defeito de 2026-08-06, em que 13 "
                  "arquivos deste repo ainda estão." % (len(hdr), trc_alvo),
                  file=sys.stderr)
            for src, t in hdr:
                print("   · %-38s color_trc=%s" % (src, t), file=sys.stderr)
            print("   Isto NÃO é o caminho normal: converta na extração "
                  "(`detect-cor.py resolver .` e um perfil com "
                  "`cor.aplicar_em: \"extracao\"`) ou use um perfil cujo "
                  "`tags_saida` descreva a fonte.", file=sys.stderr)
    _gravar()
    _gravar_decisao(motivo)
    sys.exit(0)

def _sha(frag_rel, cubes):
    """sha256 do que decide a COR daquele segmento: o fragmento COMO ESCRITO
    (relativo, para não depender do caminho da máquina) + os BYTES de cada .cube.
    O nome não basta: `gen-hlg2sdr-lut.py` regrava `luts/hlg2sdr.cube` no lugar,
    e sem os bytes trocar a curva deixaria 29 segmentos da curva antiga no disco
    com o sidecar válido — a quinta porta do segmento órfão."""
    h = hashlib.sha256()
    h.update(frag_rel.encode())
    for c in cubes:
        try:
            with open(c, "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
        except OSError:
            h.update(b"<ausente>")
    return h.hexdigest()[:16]

def _gravar():
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(plano, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

def _gravar_decisao(motivo=None):
    """Persiste a decisão observável depois que o plano temporário é removido."""
    modo = "sem-cor" if sem_cor else ("cor-como" if forcado else "cor-json")
    doc = {
        "schema": "benchmark.cor-decisao/v1",
        "modo": modo,
        "override_explicito": bool(sem_cor or forcado),
        "perfil": P.get("nome"),
        "edl_fingerprint": edl_io.fingerprint(edl_io.segmentos(".")),
        "fontes": sorted(soma),
        "motivo": motivo,
    }
    tmp = "%s.tmp-%d" % (decisao_path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, decisao_path)

# ── vínculo global perfil ↔ decisão de cor ───────────────────────────────────
# A expectativa descreve quais fontes a PEÇA aceita, não onde a conversão roda.
# Portanto este portão vem antes de --sem-cor, aplicar_em=nunca/passe e da guarda
# de tags. Só --cor-como é um override consciente e permanece acima dele.
cj = None
erro_cor_json = None
cor_json_existe = os.path.isfile("cor.json")
if cor_json_existe:
    try:
        with open("cor.json", encoding="utf-8") as fh:
            lido = json.load(fh)
        if isinstance(lido, dict):
            cj = lido
        else:
            erro_cor_json = "a raiz precisa ser objeto JSON, não %s" % type(lido).__name__
    except (ValueError, OSError) as e:
        erro_cor_json = str(e)
        cj = None
fontes_lidas = (cj or {}).get("fontes") or {}
if not isinstance(fontes_lidas, dict):
    erro_cor_json = "`fontes` precisa ser objeto JSON, não %s" % type(fontes_lidas).__name__
    fontes_cj = {}
else:
    fontes_cj = fontes_lidas

def abortar_expectativa(motivo):
    sys.exit(
        "MONTAGEM ABORTADA: %s\n"
        "O cor.json ficou stale ou não prova qual contrato de entrada foi "
        "resolvido. Rerode `detect-cor.py resolver %s` antes de montar. ZERO "
        "segmento foi renderizado. Escape consciente: "
        "--cor-como <entrada-do-catalogo>."
        % (motivo, os.getcwd()))

def conferir_expectativa_atual(legado_sem_vinculo=False):
    """Prende a decisão persistida ao contrato de entrada que a produziu.

    O valor legível e o hash são conferidos entre si e contra o perfil atual.
    Cor.json anterior ao hash continua seguro quando traz `perfil_esperado` ou
    `expectativa_cor.declarada`. Arquivo sem expectativa persistida é anterior a
    esse contrato e segue pelas guardas históricas de detecção/calibração.
    """
    atual = cor_perfil.get("entrada_esperada", "auto")
    atual = detect_cor.normalizar_entrada_esperada(atual)
    atual_sha = detect_cor.hash_entrada_esperada(atual)
    exp = cj.get("expectativa_cor") or {}
    persistidos = []
    if "perfil_esperado" in cj:
        persistidos.append(("perfil_esperado", cj.get("perfil_esperado")))
    if isinstance(exp, dict) and "declarada" in exp:
        persistidos.append(("expectativa_cor.declarada", exp.get("declarada")))
    sha_presente = "perfil_esperado_sha256" in cj
    sha_salvo = cj.get("perfil_esperado_sha256")
    if sha_presente and (not isinstance(sha_salvo, str) or
                         len(sha_salvo) != 64 or
                         any(c not in "0123456789abcdef" for c in sha_salvo)):
        abortar_expectativa(
            "`perfil_esperado_sha256` existe, mas não é um SHA-256 hexadecimal válido.")

    normalizados = [(nome, detect_cor.normalizar_entrada_esperada(valor))
                    for nome, valor in persistidos]
    if normalizados:
        primeiro = normalizados[0][1]
        contradiz = [(nome, valor) for nome, valor in normalizados[1:]
                     if valor != primeiro]
        if contradiz:
            abortar_expectativa(
                "cor.json é internamente inconsistente: os valores persistidos "
                "de `cor.entrada_esperada` não concordam (%s)."
                % ", ".join("%s=%r" % x for x in normalizados))
        if sha_presente and detect_cor.hash_entrada_esperada(primeiro) != sha_salvo:
            abortar_expectativa(
                "`perfil_esperado_sha256` não corresponde ao valor esperado "
                "persistido no próprio cor.json.")
        if primeiro != atual:
            abortar_expectativa(
                "perfil.json mudou depois do `detect-cor.py resolver`: "
                "cor.entrada_esperada persistida=%r, atual=%r."
                % (primeiro, atual))
    if sha_presente and sha_salvo != atual_sha:
        abortar_expectativa(
            "perfil.json mudou depois do `detect-cor.py resolver`: "
            "o hash de cor.entrada_esperada persistido não corresponde ao atual "
            "(%s != %s)." % (sha_salvo, atual_sha))

    # Defesa para cor.json escrito pelo detector antigo, que avaliava somente a
    # fonte principal. A unidade do contrato é a EDL: TODA fonte usada precisa
    # caber na expectativa atual, mesmo que o estado persistido diga compatível.
    bloqueadas = []
    for src in soma:
        info = fontes_cj.get(src)
        if info is None:
            continue                    # a guarda de procedência abaixo o nomeia
        perfil_detectado = info.get("perfil")
        # O contrato antigo não persistia expectativa. Ainda assim conseguimos
        # provar SDR↔HLG a partir do perfil detectado salvo e fechar o falso verde
        # de upgrade. PQ/Log ficam no portão histórico de calibração/confiança,
        # que dá a ação humana específica em vez de mascará-la como stale.
        if legado_sem_vinculo and perfil_detectado not in detect_cor.EQUIV_PERFIL:
            continue
        aval = detect_cor.avaliar_expectativa(perfil_detectado, atual)
        if aval["estado"] in ("divergente", "invalida"):
            bloqueadas.append((src, aval["detectado"], aval["estado"]))
    if bloqueadas:
        linhas = "; ".join("%s detectado=%s (%s)" % x for x in bloqueadas)
        abortar_expectativa(
            "cor.entrada_esperada=%r rejeita %d fonte(s) usada(s) pela EDL, "
            "apesar do estado persistido: %s."
            % (atual, len(bloqueadas), linhas))

if not forcado and cor_json_existe:
    if erro_cor_json or cj is None:
        abortar_expectativa("cor.json é inválido: %s." %
                            (erro_cor_json or "conteúdo ilegível"))
    if "expectativa_cor" in cj and not isinstance(cj.get("expectativa_cor"), dict):
        abortar_expectativa("`expectativa_cor` precisa ser objeto JSON.")
    exp_persistida = cj.get("expectativa_cor") or {}
    if isinstance(exp_persistida, dict) and \
            exp_persistida.get("estado") in ("divergente", "invalida"):
        sys.exit(
            "MONTAGEM ABORTADA: cor.json registra expectativa de entrada %s "
            "(declarada=%r, detectado=%r). O resultado persistido continua "
            "bloqueante; ajuste perfil.json e reresolva a cor, ou use o escape "
            "explícito --cor-como <entrada>."
            % (exp_persistida.get("estado"), exp_persistida.get("declarada"),
               exp_persistida.get("detectado")))
    tem_vinculo = ("perfil_esperado" in cj or "perfil_esperado_sha256" in cj or
                   (isinstance(exp_persistida, dict) and
                    "declarada" in exp_persistida))
    # Sem vínculo, reavaliamos os perfis comparáveis salvos (SDR/HLG) contra a
    # expectativa atual. Isso fecha o upgrade stale sem exigir que um artefato
    # legado invente um hash que nunca teve. Com vínculo, valor e hash também são
    # conferidos e qualquer inconsistência fecha a porta.
    conferir_expectativa_atual(legado_sem_vinculo=not tem_vinculo)

if sem_cor:
    plano["origem"] = "ausente"
    sair_sem_cor("--sem-cor: nenhuma conversão entra na extração (bisseção).")
if aplicar_em == "nunca":
    sair_sem_cor("perfil.cor.aplicar_em = nunca — a peça é entregue no espaço da fonte.")
if aplicar_em == "passe":
    plano["aplicada_em"] = "passe"
    plano["origem"] = "cor.json" if os.path.isfile("cor.json") else "ausente"
    sair_sem_cor("perfil.cor.aplicar_em = passe — a conversão é um passe separado "
                 "sobre o montado, e o qc-cor.py vai esperar `segs/*` no espaço da fonte.")
if modo_tags != "setparams":
    sair_sem_cor(
        "perfil aplica tags de cor por %r, e a conversão na extração EXIGE "
        "`setparams`.\n"
        "   Neste build `-color_primaries` e `-color_trc` de saída são "
        "silenciosamente ignoradas (qc-cor.py:24-30): converter aqui produziria "
        "pixels Rec.709 com rótulo da fonte — o defeito de 2026-07-28, fabricado "
        "por nós.\n"
        "   NADA foi convertido. Para converter, use um perfil com "
        "`cor.aplicar_tags_por: \"setparams\"`." % modo_tags, alto=True)

# ── a partir daqui, aplicar_em == "extracao" ──────────────────────────────────
cat = detect_cor.carregar_catalogo()
with open(cat["_caminho"], "rb") as fh:
    plano["catalogo_sha256"] = hashlib.sha256(fh.read()).hexdigest()
raiz = detect_cor.raiz_repo()

if forcado:
    chave, ent = detect_cor.entrada_catalogo(cat, forcado)
    if ent is None:
        sys.exit("--cor-como %r não existe no catálogo %s." % (forcado, cat["_caminho"]))
    plano["origem"] = "forcado_por_operador"
    print("⚠️ --cor-como %s: a cadeia do catálogo foi FORÇADA em todas as fontes, "
          "por cima do que o detector diria. Fica no plano de cor como "
          "`forcado_por_operador`." % forcado, file=sys.stderr)
elif cj is None:
    sair_sem_cor(
        "sem cor.json nesta produção — NADA foi convertido, e os segmentos vão "
        "sair no espaço da fonte (é o comportamento de antes da SPEC-25, byte a "
        "byte).\n"
        "   Para converter na extração, rode antes:\n"
        "       python3 %s/detect-cor.py resolver %s"
        % (os.environ["BENCH_EDIT_SCRIPTS"], os.getcwd()), alto=True)
elif "fragmento_vf" not in cj:
    sair_sem_cor(
        "o cor.json desta produção é anterior à SPEC-25 (contrato %s, sem "
        "`fragmento_vf`) — NADA foi convertido.\n"
        "   Reresolva com `detect-cor.py resolver %s` para converter na extração."
        % (cj.get("contrato", "?"), os.getcwd()), alto=True)
else:
    plano["origem"] = "cor.json"

travas, perfis = [], {}
for src in soma:
    if forcado:
        cam = src if os.path.isabs(src) else os.path.join(".", src)
        st, _tags = detect_cor._probe(cam)
        if not st:
            sys.exit("--cor-como: não consegui sondar %s" % src)
        cadeia, calibrado, acao, chave = detect_cor.montar_cadeia(cat, forcado, st, None)
        info = {"perfil": forcado, "confianca": "alta", "calibrado": calibrado,
                "fragmento_vf": detect_cor.fragmento_de(cadeia) if (cadeia and calibrado) else "",
                "acao_humana": acao}
    else:
        info = fontes_cj.get(src)
        if info is None:
            sys.exit(
                "cor.json não tem entrada para o src %r da EDL (tem %d: %s).\n"
                "A EDL mudou depois do `detect-cor.py resolver`, e montar assim "
                "converteria um segmento pela cadeia de outro arquivo. Reresolva:\n"
                "    python3 %s/detect-cor.py resolver %s"
                % (src, len(fontes_cj), ", ".join(sorted(fontes_cj)) or "nenhuma",
                   os.environ["BENCH_EDIT_SCRIPTS"], os.getcwd()))
    perfis.setdefault(info.get("perfil") or "?", []).append(src)
    if not info.get("calibrado"):
        travas.append((src, "calibrado: false",
                       info.get("acao_humana") or
                       "não temos curva MEDIDA para este perfil de cor."))
        continue
    if (info.get("confianca") or "baixa") != "alta":
        travas.append((src, "confiança: %s" % info.get("confianca"),
                       "rode `detect-cor.py candidatos %s --spec ...` e escolha a "
                       "cadeia olhando a folha." % src))
        continue
    frag_rel = info.get("fragmento_vf") or ""
    cubes, frag_abs = [], []
    for f in frag_rel.split(",") if frag_rel else []:
        if f.startswith("lut3d="):
            rel = f[len("lut3d="):]
            ab = rel if os.path.isabs(rel) else os.path.join(raiz, rel)
            if not os.path.isfile(ab):
                sys.exit("a LUT %s do cor.json não existe em %s" % (rel, ab))
            cubes.append(ab)
            frag_abs.append("lut3d=%s" % ab)
        else:
            frag_abs.append(f)
    plano["por_src"][src] = {
        "fragmento": ",".join(frag_abs),
        "fragmento_relativo": frag_rel,
        "cor_sha": _sha(frag_rel, cubes),
        "perfil": info.get("perfil"),
        "calibrado": True, "confianca": info.get("confianca"),
    }

if travas:
    print("🔴 MONTAGEM ABORTADA pelo portão de cor (SPEC-25 §3.7). ZERO segmento "
          "renderizado.", file=sys.stderr)
    for src, o_que, saida in travas:
        print("   · %-38s %s" % (src, o_que), file=sys.stderr)
        print("     → %s" % saida, file=sys.stderr)
    # ⚠️ a saída NÃO é somar uma curva de manual (hable/reinhard/mobius). A cadeia
    # derivada do standard já foi percorrida aqui: −21% de faixa de contraste no
    # rosto, reprovada pelo creator-1; a segunda tentativa saiu +38% mais clara.
    print("   A saída é MEDIR o avconvert (receita em gen-hlg2sdr-lut.py:32-36) e "
          "acrescentar a entrada ao catálogo — nunca derivar a curva do standard: "
          "a cadeia 'de manual' já custou −21% de faixa de contraste no rosto e foi "
          "reprovada.", file=sys.stderr)
    print("   Escape consciente, se você sabe o que o arquivo é e o detector não: "
          "`--cor-como <entrada-do-catalogo>`. Para montar sem converter: "
          "`--sem-cor`.", file=sys.stderr)
    sys.exit(1)

plano["perfis_distintos"] = sorted(perfis)
tem_conversao = any(v["fragmento"] for v in plano["por_src"].values())
plano["aplicada_em"] = "extracao" if tem_conversao else None
_gravar()
_gravar_decisao("contrato resolvido antes da extração")

n_conv = sum(1 for v in plano["por_src"].values() if v["fragmento"])
print("  cor: %d fonte(s) · perfis %s · %d com conversão na extração · origem %s"
      % (len(plano["por_src"]), "+".join(plano["perfis_distintos"]) or "?",
         n_conv, plano["origem"]), file=sys.stderr)
if len(plano["perfis_distintos"]) > 1:
    print("  ⚠️ a EDL mistura %d perfis de cor: %s"
          % (len(plano["perfis_distintos"]),
             " · ".join("%s (%d src)" % (p, len(v)) for p, v in sorted(perfis.items()))),
          file=sys.stderr)
    print("     Isso é legítimo — cada fonte é convertida pela SUA cadeia e o "
          "montado sai num espaço só. Mas mistura não declarada quase sempre é "
          "`src` errado na EDL: confira antes de aprovar.", file=sys.stderr)

# ── promove `aplicada_em` no cor.json ─────────────────────────────────────────
# Quem DETECTA grava `null`; quem APLICA promove. É este campo que o qc-cor.py lê
# para saber se `segs/*` e `v1-montado*` são PRÉ ou PÓS conversão — e é por isso
# que ele é escrito ANTES do laço, não depois: se o render morrer no meio, parte
# dos segmentos já está convertida, e o valor "extracao" descreve o disco melhor
# do que `null` descreveria.
if cj is not None and cj.get("aplicada_em") != plano["aplicada_em"]:
    cj["aplicada_em"] = plano["aplicada_em"]
    with open("cor.json", "w", encoding="utf-8") as fh:
        json.dump(cj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("  cor.json: aplicada_em = %s" % plano["aplicada_em"], file=sys.stderr)
PY
# 🐛 SEGMENTO ÓRFÃO POR EDL QUE ENCOLHEU — a outra porta de entrada do mesmo bug.
# O guard de sidecar logo abaixo pega o órfão de execução INTERROMPIDA, mas não este:
# quando a EDL passa de N pra M<N segmentos (juntei duas janelas numa só), os
# segs/segNNN.mp4 com índice >= M ficam no disco com sidecar VÁLIDO da geração
# anterior. O `concat.txt` é reescrito, então o VÍDEO sai certo — mas tudo que
# enumera `segs/*.mp4` por glob (audio-exato.py, legendas.py) enxerga os órfãos e
# monta trilha/legenda de um corte que não existe mais. Aconteceu em 2026-07-31
# (produção peca-11, r3: 2 janelas viraram 1).
python3 - <<'PY'
import glob, os, sys
sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])
import edl_io
n = len(edl_io.segmentos("."))
for p in sorted(glob.glob(os.path.join("segs", "seg*.mp4"))):
    try:
        idx = int(os.path.basename(p)[3:-4])
    except ValueError:
        continue
    if idx >= n:
        print(f"  {p} sobrou de uma EDL maior ({idx} >= {n} segmentos) — apagando",
              file=sys.stderr)
        os.remove(p)
        side = p[:-4] + ".json"
        if os.path.exists(side):
            os.remove(side)
PY
# ───── 🔴 JANELAS SOBREPOSTAS DA MESMA FONTE = SILÊNCIO DUPLICADO (H48-1) ─────
# Medido em campo em 2026-08-12, e achado DE OUVIDO pelo creator ("ouvi 'uma/uma'
# e depois dois respiros"): `cena-1` foi travada em `limite_pos: 19.055` e
# `cena-2` continuava começando em 18,785 s. As duas janelas reivindicavam o mesmo
# trecho do MESMO bruto, e os 270 ms de silêncio entre as falas tocavam DUAS
# VEZES. Passou por tudo: soma da EDL (a soma nominal não muda com sobreposição),
# integridade real (deriva 0,0 ms), `qc-emendas-asr` (nenhuma PALAVRA duplicou —
# o que duplicou foi o silêncio), `--cauda auto` (cada segmento, isolado, está
# correto). Seis verificações verdes sobre 270 ms de defeito audível.
#
# O `bordas.py` já DOCUMENTA o padrão certo ("duas janelas coladas viram corte na
# fronteira"); nada forçava. Agora força, e aqui — antes de qualquer render.
#
# ⚠️ `end == start` (janelas COLADAS) continua passando: é o caso normal, e é o
# que o próprio bordas.py produz quando duas janelas se encostam.
python3 - <<'PY' || exit 1
import os, sys
sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])
import edl_io
edl = edl_io.segmentos(".")
maus = []
for a, b in zip(edl, edl[1:]):
    if a.get("src") != b.get("src"):
        continue                      # fontes diferentes não compartilham tempo
    if a["end"] > b["start"] + 1e-9:
        maus.append((a, b, a["end"] - b["start"]))
if maus:
    print("ABORTA: %d par(es) de janelas SOBREPOSTAS da mesma fonte na EDL."
          % len(maus), file=sys.stderr)
    for a, b, dt in maus:
        print("  %s [%.3f–%.3f] invade %s [%.3f–%.3f] por %.0f ms"
              % (a.get("beat", "?"), a["start"], a["end"],
                 b.get("beat", "?"), b["start"], b["end"], dt * 1000),
              file=sys.stderr)
    print("  O trecho comum É MONTADO DUAS VEZES — o silêncio (ou a sílaba) entre\n"
          "  as duas falas toca em dobro, e NENHUM QC vê: a soma da EDL não muda,\n"
          "  a deriva de A/V fica zero e o ASR não acha palavra duplicada.\n"
          "  Conserto: encoste as janelas (`end` do primeiro == `start` do\n"
          "  segundo) ou refaça o limite que as fez se cruzarem.", file=sys.stderr)
    sys.exit(1)
PY

# ───────── plano de J-CUT (opcional): quantos frames a IMAGEM descarta ─────────
# Sem jcut.json todo skip é 0 e o -ss/-t abaixo são os de sempre, byte a byte.
# Com ele, o take que entra é renderizado a partir de `start + skip/fps`: a imagem
# aparece antes, e o audio-exato.py compensa lendo a cabeça inteira do bruto e
# posicionando o take `skip` amostras antes. O par é INDIVISÍVEL — mudar um lado
# sem o outro é o modo de falha mais caro deste repo, e é o que o
# `video_skip_frames` no sidecar existe pra impedir.
SKIPS_TXT="$(pwd)/.jcut-skips.txt"
PERFIL_FPS="$PERFIL_FPS" python3 - "$SKIPS_TXT" <<'PY' || exit 1
import os, sys
sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])
import edl_io, jcut
edl = edl_io.segmentos(".")
plano = jcut.carregar(".", edl)      # confere o edl_fingerprint; None se não há plano
plano_ativo = plano is not None and plano.get("aplicar") is not False
if plano_ativo and abs(plano["fps"] - float(os.environ["PERFIL_FPS"])) > 1e-9:
    sys.exit("jcut.json foi planejado a %g fps e o perfil desta produção diz %s.\n"
             "O lead em FRAMES sai errado num fps que não é o do plano — replaneje "
             "com `jcut.py . ` antes de montar."
             % (plano["fps"], os.environ["PERFIL_FPS"]))
sk = jcut.skips(plano, len(edl))
with open(sys.argv[1], "w") as fh:
    fh.write("".join("%d\n" % x for x in sk))
if plano_ativo:
    n = sum(1 for x in sk if x)
    print("  jcut: modo %s · teto %g ms · Σ skip = %d frames (%.0f ms de imagem "
          "antecipada em %d junção(ões))"
          % (plano["modo"], plano["lead_max_ms"], sum(sk),
             sum(sk) * 1000.0 / plano["fps"], n), file=sys.stderr)
PY
: > concat.txt
i=0
# Lê v2 (objeto com `segments`) e v1 (array nu) com a mesma linha.
# ⚠️ MEDIDO em 2026-08-08, e as duas formas "óbvias" estão ERRADAS neste jq (1.8.1):
#   `(.segments // .)[]`   → em array v1 dá **erro**: "Cannot index array with
#                            string". `//` NÃO captura erro, só null/false.
#   `(.segments? // .)[]`  → lê os dois, mas com `{"segments": null}` cai no
#                            objeto inteiro e itera os VALORES dele **em
#                            silêncio** — o montar.sh montaria lixo sem uma linha
#                            de erro. É exatamente o modo de falha que esta spec
#                            existe pra fechar.
# A forma explícita abaixo lê v1 e v2 e **grita** no null (Cannot iterate over
# null). A segunda defesa é o `edl_io.gravar`, que recusa gravar `segments: null`.
jq -c 'if type=="array" then . else .segments end | .[]' edl.json | while read -r seg; do
  src=$(jq -r .src <<<"$seg")
  start=$(jq -r .start <<<"$seg")
  end=$(jq -r .end <<<"$seg")
  # frames que a IMAGEM deste take descarta da própria cabeça (0 sem jcut.json)
  skip=$(sed -n "$((i+1))p" "$SKIPS_TXT"); skip=${skip:-0}
  if [ "$skip" = "0" ]; then
    # ⚠️ o caminho sem J-cut é ESTA linha, intocada de propósito: reformatar o
    # `-ss`/`-t` (por exemplo com %.6f) muda os bytes de toda remontagem antiga.
    ss="$start"
    dur=$(python3 -c "print($end-$start)")
  else
    SS_DUR=$(python3 -c "k=$skip/$PERFIL_FPS; print(repr($start+k), repr($end-$start-k))")
    ss=${SS_DUR%% *}
    dur=${SS_DUR##* }
  fi
  # REENQUADRAMENTO por segmento (opcional): campos zoom / cx / cy na linha da EDL.
  # zoom=1.25 recorta 1/1.25 do bruto e reescala pra 1080x1920 — o "punch-in" REAL,
  # feito nos pixels do 4K (não é escala de um 1080 já pronto, então não perde nitidez).
  # cx/cy = centro do recorte em fração do frame do bruto (0..1, default 0.5).
  # Alternar zoom 1.0 / ~1.25 entre segmentos é o que faz o jump cut LER como troca
  # de plano — gramática medida no ref-D (data/adhoc/modelagem-edicao/).
  zoom=$(jq -r '.zoom // 1' <<<"$seg")
  cx=$(jq -r '.cx // 0.5' <<<"$seg")
  cy=$(jq -r '.cy // 0.5' <<<"$seg")
  # 🎨 o fragmento de conversão DESTA fonte (vazio quando não há conversão) e o
  # sha do que decide a cor deste segmento. Vêm do plano — o laço não decide cor.
  FRAG_ATUAL=$(jq -r --arg s "$src" '.por_src[$s].fragmento // ""' "$COR_PLANO")
  COR_SHA_ATUAL=$(jq -r --arg s "$src" '.por_src[$s].cor_sha // "ausente"' "$COR_PLANO")
  out=$(printf 'segs/seg%03d.mp4' "$i")   # 3 dígitos: %02d embaralhava acima de 99
  side="${out%.mp4}.json"
  # cache inválido se QUALQUER campo do segmento mudou — corte (src/start/end) ou
  # enquadramento (zoom/cx/cy). ⚠️ Antes daqui só o enquadramento era comparado: ao
  # reeditar a EDL, os segs/ velhos ficavam e o `audio-exato.py` abortava com "ERRO de
  # procedência" (o guard funciona, mas obriga a apagar segs/ na mão — e quando os
  # índices deslocam, é o lote inteiro). Comparando o sidecar completo, o refazer é
  # automático e só nos segmentos que realmente mudaram.
  # 🐛 SEGMENTO ÓRFÃO: .mp4 sem sidecar = sobra de execução interrompida (o sidecar é
  # escrito DEPOIS do ffmpeg). A versão antiga só comparava quando os DOIS existiam, e
  # o `if [ ! -f "$out" ]` abaixo então REUSAVA o órfão em silêncio — com o corte da
  # geração anterior. Medido nos criativos do creator-3: o c-completo saiu **6,25s mais
  # longo** que a soma da EDL, e nenhum QC de deriva acusa (a trilha é montada a partir
  # dos frames REAIS, então fica sincronizada com o vídeo errado).
  if [ -f "$out" ] && [ ! -f "$side" ]; then
    echo "  $out sem sidecar (execução interrompida?) — refazendo" >&2
    rm -f "$out"
  fi
  # 🐛 SEGMENTO ÓRFÃO POR ARQUIVO ILEGÍVEL — a SEXTA porta, e a única em que o
  # sidecar está PERFEITO (2026-08-12, H47-8). Medido duas vezes em campo com a
  # v0.12, em máquinas diferentes: `.mp4` com `moov atom not found` em `segs/`,
  # sidecar válido ao lado, e o fluxo seguindo. As cinco portas acima comparam
  # PROCEDÊNCIA — nenhuma delas olha se o arquivo abre. A partir daqui o cache
  # também é conferido por DECODIFICAÇÃO: um frame de verdade, ~15 ms por
  # segmento, e só nos que o cache ia reusar.
  if [ -f "$out" ] && [ -f "$side" ]; then
    if ! ffmpeg -nostdin -v error -i "$out" -frames:v 1 -f null - >/dev/null 2>&1; then
      echo "  $out está ILEGÍVEL (não decodifica um frame — \`moov\` ausente ou" >&2
      echo "  stream truncado) apesar do sidecar válido — refazendo" >&2
      rm -f "$out" "$side"
    fi
  fi
  # 🐛 SEGMENTO ÓRFÃO POR TROCA DE PERFIL — a terceira porta de entrada do mesmo bug,
  # aberta pela SPEC-00. Antes dela o `vf` era constante, então comparar o CORTE bastava.
  # Agora o perfil decide fps, escala, unsharp, crf, pix_fmt e tags de cor: com a mesma
  # EDL e outro perfil, o corte não muda e o segmento renderizado no formato ANTERIOR
  # seria reusado — vídeo errado com todos os QCs verdes, que é exatamente o defeito de
  # 6,25s dos criativos do creator-3. Por isso `perfil_video_sha` entra no sidecar E na
  # comparação. Sidecar SEM o campo é de antes desta spec: não dá pra saber em que
  # formato aquele .mp4 saiu, e a resposta segura é REFAZER (custa render, não entrega
  # errado). Refeito uma vez, o cache volta a valer.
  # 🐛 SEGMENTO ÓRFÃO POR TROCA DE LEAD — a quarta porta de entrada, aberta pela
  # SPEC-07. Com o mesmo corte e outro `lead`, `src/start/end/zoom/perfil_video_sha`
  # são idênticos e só a CABEÇA DA IMAGEM muda. Sem `video_skip_frames` na
  # comparação, o seg antigo é reusado e o audio-exato.py posiciona a trilha do
  # lead NOVO sobre a imagem VELHA — dessincronia com todos os QCs verdes, porque
  # a trilha se trava nos frames reais do arquivo errado. Sidecar sem o campo é de
  # antes desta spec e vale 0, que é o que ele de fato renderizou (§4.3).
  # 🐛 SEGMENTO ÓRFÃO POR TROCA DE COR — a QUINTA porta de entrada, aberta pela
  # SPEC-25. Com a mesma EDL, o mesmo perfil e o mesmo lead, trocar a CURVA muda
  # os pixels e nada mais: `gen-hlg2sdr-lut.py` regrava `luts/hlg2sdr.cube` NO
  # LUGAR, então nem o nome do arquivo muda. Sem `cor_sha` na comparação, os 29
  # segmentos da curva ANTIGA ficariam no disco com sidecar válido e todos os QCs
  # verdes — a mesma família que custou 6,25s de vídeo errado nos criativos do
  # creator-3. Por isso o sha cobre os BYTES da .cube, não o nome. Sidecar sem o
  # campo é de antes desta spec: não dá para saber em que cor aquele .mp4 saiu, e
  # a resposta segura é REFAZER (custa CPU, não entrega errado).
  if [ -f "$out" ] && [ -f "$side" ]; then
    prev=$(jq -r '[(.src),(.start),(.end),(.zoom // 1),(.cx // 0.5),(.cy // 0.5),(.perfil_video_sha // "ausente"),(.video_skip_frames // 0),(.cor_sha // "ausente")]|@csv' "$side" 2>/dev/null || echo "x")
    now=$(jq -r --argjson z "$zoom" --argjson cx "$cx" --argjson cy "$cy" --arg vs "$PERFIL_VIDEO_SHA" --argjson sk "$skip" --arg cs "$COR_SHA_ATUAL" \
            '[(.src),(.start),(.end),$z,$cx,$cy,$vs,$sk,$cs]|@csv' <<<"$seg")
    if [ "$prev" != "$now" ]; then
      # a mensagem NOMEIA a causa. "segmento mudou" obriga quem lê a abrir o
      # sidecar para saber se foi o corte, o formato, o lead ou a cor — e quando a
      # causa é a cor, saber disso é a diferença entre "o cache funcionou" e "a
      # curva trocou debaixo de mim".
      prev_cs=$(jq -r '.cor_sha // "ausente"' "$side" 2>/dev/null || echo "ausente")
      prev_vs=$(jq -r '.perfil_video_sha // "ausente"' "$side" 2>/dev/null || echo "ausente")
      if [ "$prev_vs" = "ausente" ]; then
        echo "  $out é de antes do perfil de peça (sidecar sem perfil_video_sha) — refazendo" >&2
      elif [ "$prev_cs" = "ausente" ]; then
        echo "  $out é de antes da cor na extração (sidecar sem cor_sha) — refazendo" >&2
      elif [ "$prev_cs" != "$COR_SHA_ATUAL" ]; then
        echo "  a COR de $out mudou (cor_sha $prev_cs → $COR_SHA_ATUAL) — refazendo" >&2
      else
        echo "  segmento mudou em $out — refazendo" >&2
      fi
      rm -f "$out"
    fi
  fi
  if [ ! -f "$out" ]; then
    # 📐 A SONDAGEM É INCONDICIONAL desde a SPEC-06. Antes ela só rodava no ramo
    # `zoom > 1`, porque o único uso das dimensões era o crop do punch-in. Agora a
    # JANELA DE ASPECTO precisa delas em todo segmento: é ela que impede que uma
    # fonte de outro aspecto vire 1080x1920 com SAR 256:81. Custo: um ffprobe de
    # cabeçalho por segmento que vai ser renderizado (~30 ms), zero nos que o
    # cache reusa — o bloco inteiro está dentro do `if [ ! -f "$out" ]`.
    # (csv=s=' ' não é aceito por todo build; default=nk=1:nw=1 sai uma linha por campo)
    SW=$(ffprobe -v error -select_streams v -show_entries stream=width  -of default=nk=1:nw=1 "$src" | head -1)
    SH=$(ffprobe -v error -select_streams v -show_entries stream=height -of default=nk=1:nw=1 "$src" | head -1)
    if [ -z "$SW" ] || [ -z "$SH" ]; then
      echo "ERRO: não consegui sondar largura/altura de '$src' (seg $i)." >&2
      echo "Sem as dimensões do bruto não há janela de aspecto, e montar assim é" >&2
      echo "como a imagem espremida com SAR 256:81 saía sem ninguém ver." >&2
      exit 1
    fi
    # ⚠️ BRUTO DE CELULAR: o ffprobe reporta as dimensões do STREAM (pré-rotação), mas o
    # ffmpeg AUTOROTA no decode — o filtro vê o frame já girado. Num iPhone vertical o
    # stream é 3840x2160 com rotation=-90 e o crop tem que ser calculado sobre 2160x3840.
    # Sem isto o crop sai deitado, estoura o clamp e o punch-in recorta o lugar errado.
    # (achado nos criativos do creator-3, 2026-07-27)
    # 🔴 E agora a troca roda SEMPRE, não só com zoom: a janela de aspecto lê o
    # aspecto da fonte, e num take rotacionado o aspecto PRÉ-rotação é o inverso
    # do verdadeiro — 1920x1080 lido como paisagem quando o quadro é retrato.
    ROT=$(ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation \
            -of default=nk=1:nw=1 "$src" 2>/dev/null | head -1)
    case "${ROT:-0}" in
      90|-90|270|-270) T="$SW"; SW="$SH"; SH="$T"
                       echo "  (rotation=$ROT → dimensões trocadas: ${SW}x${SH})" >&2 ;;
    esac
    # o SAR do bruto não entra na conta — entra no AVISO. A janela de aspecto é
    # calculada em pixels, e numa fonte anamórfica isso daria recorte plausível e
    # errado. Das 11 fontes de produção deste repo, 11 têm SAR 1:1 ou ausente.
    SAR=$(ffprobe -v error -select_streams v -show_entries stream=sample_aspect_ratio \
            -of default=nk=1:nw=1 "$src" 2>/dev/null | head -1)
    # a janela e o crop precisam das dimensões do bruto; o resto do filtro
    # (escala, unsharp condicional, setsar, fps, tags por setparams) é decisão do
    # perfil — tudo em vf_montagem(), um produtor só.
    # A linha INTEIRA da EDL vai junto: a guarda de aspecto precisa saber se
    # `cx`/`cy` foram escritos ou são o default 0.5.
    # shellcheck disable=SC2086
    VF=$(python3 "$PERFIL" vf . --sw "$SW" --sh "$SH" --sar "${SAR:-}" --seg "$seg" $AGRESSIVO --quieto)
    # 🎨 A COSTURA DE COR (SPEC-25 §3.3). O `vf` acima é INTEIRO do perfil.py —
    # geometria, setsar, fps e a tag. Aqui entra o único fragmento que o perfil
    # não conhece: a conversão da FONTE. Ele é inserido IMEDIATAMENTE ANTES do
    # `setparams`, e não no fim, porque o ffmpeg insere um yuv→rgb sozinho na
    # frente do `lut3d` e essa conversão usa a matriz que o `setparams` acabou de
    # escrever. Medido no seg000 da peca-01, 2026-08-09:
    #     fragmento ANTES do setparams  →  md5 idêntico ao da cadeia calibrada
    #     fragmento DEPOIS do setparams →  +0,42% de luminância, |d| médio 1,62/255
    # Um erro de 0,42% que nenhum QC deste repo acusa é exatamente a classe de
    # defeito que esta spec existe para fechar. Por isso, quando não há onde
    # inserir, o script ABORTA em vez de colar no fim.
    if [ -n "$FRAG_ATUAL" ]; then
      case "$VF" in
        *unsharp*)
          if [ -z "$COR_UNSHARP_OK" ]; then
            echo "ERRO (seg $i): o perfil '$PERFIL_NOME' tem \`unsharp\` e esta fonte precisa de conversão de cor." >&2
            echo "  O \`vf\` do perfil.py põe o unsharp logo depois do \`scale\`, então a costura de cor" >&2
            echo "  cai DEPOIS dele — e a SPEC-25 §3.3 quer o look em espaço de EXIBIÇÃO, depois da" >&2
            echo "  conversão. Medido em 2026-08-09 no seg000 da peca-01: unsharp antes da" >&2
            echo "  conversão dá −1,53% de luminância média (|d| médio 2,1/255) contra unsharp depois." >&2
            echo "  Hoje nenhuma produção deste repo cai neste caso (vsl e screencast têm fonte SDR)." >&2
            echo "  Saídas: (a) perfil com \`video.unsharp: null\`; (b) \`--sem-cor\` e conversão em passe" >&2
            echo "  separado; (c) --permitir-unsharp-antes-da-cor, ciente do −1,53%." >&2
            exit 1
          fi
          echo "  ⚠️ seg$i: unsharp ANTES da conversão de cor (−1,53% de luminância medido) — autorizado por flag" >&2 ;;
      esac
      case "$VF" in
        *,setparams=*)
          VF="${VF%,setparams=*},format=yuv420p,${FRAG_ATUAL},setparams=${VF##*,setparams=}" ;;
        *)
          echo "ERRO (seg $i): o \`vf\` do perfil.py não termina em \`setparams=\`, e há conversão de cor a inserir." >&2
          echo "  vf: $VF" >&2
          echo "  A costura de cor precisa entrar ANTES da tag; colar no fim move a luminância +0,42%" >&2
          echo "  em silêncio (medido). Se o perfil.py mudou a ordem do filtergraph, esta costura tem" >&2
          echo "  que mudar junto — ela é o segundo autor da string \`vf\`, e é por isso que confere." >&2
          exit 1 ;;
      esac
    fi
    echo "  seg$i ${SW}x${SH} zoom=$zoom cx=$cx cy=$cy → $VF" >&2
    # 🔒 INVARIANTE: segmento CONVERTIDO nunca leva flag de cor de saída.
    # Por construção isto é impossível — o plano de cor recusa converter quando o
    # perfil não usa `setparams`, e `$PERFIL_COLOR_OPTS` só é não-vazia com
    # `opcoes-de-saida`. Mas "impossível por construção" é exatamente o que este
    # repo aprendeu a desconfiar, e o custo de conferir é uma linha. Se as duas
    # coisas se encontrarem, o segmento sairia com pixels Rec.709 e a tag da fonte
    # — o Frankenstein dos 6 entregáveis, fabricado por nós.
    # 📏 Medido em 2026-08-09: por isso as flags NÃO são simplesmente removidas do
    # script. Numa fonte SDR elas MUDAM o arquivo (`-colorspace` é a única que pega
    # neste build: bt709 → bt2020nc), e tirá-las mudaria os bytes de toda
    # remontagem antiga sem perfil.json. Numa fonte HLG elas são inertes —
    # arquivo byte a byte idêntico com e sem elas.
    if [ -n "$FRAG_ATUAL" ] && [ -n "${PERFIL_COLOR_OPTS:-}" ]; then
      echo "ERRO (seg $i): conversão de cor E flags de saída ($PERFIL_COLOR_OPTS) no mesmo encode." >&2
      echo "  Isto não deveria ser alcançável: o plano de cor só converte com \`aplicar_tags_por:" >&2
      echo "  setparams\`, e aí estas flags são vazias. Se você chegou aqui, uma das duas travas" >&2
      echo "  caiu — e o segmento sairia com pixels Rec.709 carregando a tag da fonte." >&2
      exit 1
    fi
    # -nostdin OBRIGATÓRIO: sem ele o ffmpeg come o stdin do while-read
    # $PERFIL_COLOR_OPTS é INTENCIONALMENTE sem aspas: são pares flag/valor sem
    # espaço interno, e no perfil novo (tags por setparams) a variável é vazia.
    # shellcheck disable=SC2086
    # 🔴 ESCREVE EM TEMPORÁRIO, CONFERE, E SÓ DEPOIS RENOMEIA (2026-08-12, H47-8).
    # Medido DUAS vezes em campo com a v0.12, em máquinas diferentes: segmentos
    # com `moov atom not found` ficaram em `segs/` COM sidecar válido, e o fluxo
    # seguiu — o cache passou a servir um arquivo que nenhum decoder abre, e o
    # guard de sidecar (que existe e funciona) não vê isso, porque ele compara
    # PROCEDÊNCIA, não integridade. Um `.mp4` sem `moov` é o mesmo defeito do
    # A-S1 da SPEC-45 visto de outro lado: artefato meio-escrito publicado no
    # lugar do bom. O `.tmp` + `ffprobe` + `mv` fecha a janela: se o ffmpeg morrer
    # no meio (disco cheio, kill, container sem memória), o que sobra é um `.tmp`
    # que ninguém lê, e a próxima rodada refaz.
    tmpout="$out.tmp-$$.mp4"
    rm -f "$tmpout"
    # shellcheck disable=SC2086
    ffmpeg -nostdin -v error -y -ss "$ss" -t "$dur" -i "$src" \
      -an -vf "$VF" \
      -c:v libx264 -crf "$PERFIL_CRF" -preset "$PERFIL_PRESET" -pix_fmt "$PERFIL_PIXFMT" \
      $PERFIL_COLOR_OPTS \
      "$tmpout" >&2
    # a conferência é DECODIFICAR o primeiro frame, não só ler o header: um `moov`
    # ausente já quebra o -show_entries, e um stream truncado quebra o -frames:v 1.
    if ! ffprobe -v error -select_streams v:0 -show_entries stream=nb_read_frames \
         -read_intervals "%+#1" -count_frames -of csv=p=0 "$tmpout" >/dev/null 2>&1 \
       || ! ffmpeg -nostdin -v error -i "$tmpout" -frames:v 1 -f null - >/dev/null 2>&1; then
      echo "ERRO (seg $i): o segmento recém-encodado não é legível — $tmpout" >&2
      echo "  O ffmpeg saiu 0 mas o arquivo não decodifica (o caso clássico é" >&2
      echo "  \`moov atom not found\`: escrita interrompida). NÃO gravei o sidecar," >&2
      echo "  então a próxima rodada refaz este segmento em vez de cachear o defeito." >&2
      rm -f "$tmpout"
      exit 1
    fi
    mv -f "$tmpout" "$out"
    # sidecar de PROCEDÊNCIA: audio-exato.py aborta se a EDL, o perfil OU o lead
    # mudaram depois do segmento (segs/ é cache de vídeo; sem isto o áudio vinha de
    # outra geração, em silêncio). `start`/`end` são os da EDL — a decisão editorial —
    # e `video_skip_frames` diz quanto da cabeça a IMAGEM descartou por cima dela.
    printf '{"src":%s,"start":%s,"end":%s,"zoom":%s,"cx":%s,"cy":%s,"perfil_video_sha":"%s","video_skip_frames":%s,"cor_sha":"%s"}\n' \
      "$(jq -c .src <<<"$seg")" "$start" "$end" "$zoom" "$cx" "$cy" "$PERFIL_VIDEO_SHA" "$skip" "$COR_SHA_ATUAL" > "$side"
  fi
  echo "file '$out'" >> concat.txt
  i=$((i+1))
done
# vídeo: concat sem re-encode
ffmpeg -nostdin -v error -y -f concat -safe 0 -i concat.txt -c copy -an v1-video.mp4 >&2
# áudio: cortado do bruto com a duração EXATA dos frames de cada segmento
WAV=$(python3 "$EXATO" .)
# Publicação atômica: o caminho final nunca é aberto pelo muxer. O diretório
# exclusivo evita colisão entre montagens concorrentes e dá ao temporário a
# extensão .mp4 de que o ffmpeg precisa para escolher o contêiner.
MONTADO_TMP_DIR="$(mktemp -d "$(pwd)/.v1-montado.tmp.XXXXXX")"
MONTADO_TMP="$MONTADO_TMP_DIR/v1-montado.mp4"
limpar_montado_tmp() {
  rm -f "$MONTADO_TMP"
  rmdir "$MONTADO_TMP_DIR" 2>/dev/null || true
}
trap limpar_montado_tmp EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
ffmpeg -nostdin -v error -y -i v1-video.mp4 -i "$WAV" -map 0:v -map 1:a \
  -c:v copy -c:a "$PERFIL_ACODEC" -b:a "$PERFIL_ABITRATE" -ar "$PERFIL_SR" \
  "$MONTADO_TMP" >&2
rm -f v1-video.mp4
# Ler o cabeçalho não basta: um stream truncado pode ter `moov` e ainda não
# decodificar. O primeiro frame precisa existir antes de qualquer publicação.
if ! ffmpeg -nostdin -v error -i "$MONTADO_TMP" -frames:v 1 -f null - \
     >/dev/null 2>&1; then
  echo "ERRO: o MP4 montado não decodifica o primeiro frame; final anterior preservado." >&2
  exit 1
fi
# ✅ CONFERÊNCIA DE INTEGRIDADE, DUPLA — as duas medem coisas diferentes e as duas ficam:
#
#   NOMINAL (Σ da EDL vs render, tolerância de 1 frame por segmento)
#     é o único detector de SEGMENTO ÓRFÃO — o bug que deixou o `c-completo` do
#     creator-3 6,25s mais longo com todos os outros QCs verdes. Frouxa de propósito:
#     ela precisa absorver os ~350 ms de arredondamento pra frame que a soma
#     nominal sempre acumula.
#
#   REAL (timeline_real vs render, ± 2 frames)
#     é o detector de erro de ENCODER/CONTAINER: frame que não saiu, frame que o
#     muxer inventou. Só ela pode ser apertada, porque a timeline é medida dos
#     frames que existem. E ela NÃO substitui a nominal: um segmento órfão passa
#     na real POR CONSTRUÇÃO — a timeline foi medida dos próprios segs errados.
PERFIL_FPS="$PERFIL_FPS" BENCH_SKIPS_TXT="$SKIPS_TXT" \
BENCH_MONTADO_TMP="$MONTADO_TMP" python3 - <<'PY' || exit 1
import math, os, subprocess, sys
sys.path.insert(0, os.environ["BENCH_EDIT_SCRIPTS"])
import edl_io
edl = edl_io.segmentos(".")
soma = sum(s["end"] - s["start"] for s in edl if "start" in s and "end" in s)
# 🔀 com J-cut a soma NOMINAL da EDL deixa de ser o alvo: cada take que entra
# perde `skip` frames de cabeça na IMAGEM. Sem descontar isso, a peça sai mais
# curta que a soma e o detector de segmento órfão vira alarme falso em toda
# montagem J-cut — que é como um QC bom morre.
skips = [int(x) for x in open(os.environ["BENCH_SKIPS_TXT"]).read().split()]
fps_nom = float(os.environ.get("PERFIL_FPS") or 0) or None
if fps_nom and any(skips):
    descontado = sum(skips) / fps_nom
    soma -= descontado
    print("  jcut: Σ(end−start) menos %d frames de cabeça (%.3fs) = %.3fs"
          % (sum(skips), descontado, soma), file=sys.stderr)
montado_tmp = os.environ["BENCH_MONTADO_TMP"]
probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", montado_tmp],
                       capture_output=True, text=True)
try:
    d = float(probe.stdout)
except ValueError:
    sys.exit("ERRO: ffprobe não devolveu duração válida para o MP4 temporário; "
             "final anterior preservado.\n" + probe.stderr.strip())
if probe.returncode != 0 or not math.isfinite(d) or d <= 0:
    sys.exit("ERRO: duração inválida no MP4 temporário (%r); final anterior preservado."
             % probe.stdout.strip())
# a tolerância é UM FRAME POR SEGMENTO — que depende do fps da peça, não de 1/30.
# O ×1,02 reproduz o 0,034 histórico a 30 fps sem mudar o limiar de nenhuma
# produção existente.
fps = float(os.environ.get("PERFIL_FPS") or 30)
tol = max(0.15, len(edl) * (1.02 / fps))
if abs(d - soma) > tol:
    print(f"ERRO: render {d:.3f}s vs soma da EDL {soma:.3f}s "
          f"(delta {abs(d-soma)*1000:.0f}ms > tolerância {tol*1000:.0f}ms).\n"
          f"Quase sempre é segmento reusado de outra geração — apague segs/ e remonte.",
          file=sys.stderr)
    sys.exit(1)
print(f"integridade nominal: render {d:.3f}s ≈ soma da EDL {soma:.3f}s "
      f"(delta {abs(d-soma)*1000:.0f}ms, tolerância {tol*1000:.0f}ms — folgada de "
      f"propósito: ela absorve o arredondamento pra frame)", file=sys.stderr)

tl = edl_io.timeline(".", exigir=False)
if tl is None:
    print("integridade real: timeline_real ausente (audio-exato.py não gravou?) — "
          "só a nominal rodou", file=sys.stderr)
else:
    fps_tl = tl["video"]["fps"]
    tol2 = 2.0 / fps_tl
    delta = abs(d - tl["total_s"])
    if delta > tol2:
        print(f"ERRO: render {d:.3f}s vs timeline real {tl['total_s']:.3f}s "
              f"(delta {delta*1000:.1f}ms > 2 frames = {tol2*1000:.1f}ms).\n"
              f"A timeline é medida dos frames que EXISTEM em segs/, então isto não é "
              f"arredondamento: é frame perdido/inventado no concat ou no mux.",
              file=sys.stderr)
        sys.exit(1)
    print(f"integridade real: render {d:.3f}s ≈ timeline {tl['total_s']:.3f}s "
          f"({tl['total_frames']} frames · delta {delta*1000:.1f}ms ≤ 2 frames)",
          file=sys.stderr)
PY
# Só este rename torna a nova versão observável. Qualquer falha acima sai pelo
# trap, remove apenas o temporário exclusivo e mantém o último final intacto.
mv -f "$MONTADO_TMP" v1-montado.mp4
rmdir "$MONTADO_TMP_DIR"
trap - EXIT HUP INT TERM
rm -f "$SKIPS_TXT" "$COR_PLANO"
echo "$(pwd)/v1-montado.mp4"
