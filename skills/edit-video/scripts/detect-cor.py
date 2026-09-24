#!/usr/bin/env python3
# Partes deste arquivo derivam de um projeto de terceiro,
# MIT License, Copyright (c) 2026 Creator Factory.
# Cópia integral da licença em LICENSES/edvid-MIT.txt.
"""detect-cor.py — que perfil de cor é este arquivo, e qual das NOSSAS curvas se aplica.

    detect-cor.py <video> [--json]
    detect-cor.py resolver <dir-producao> [--bruto input/x.MP4]
    detect-cor.py candidatos <video> --spec "nome=cadeia;nome2=cadeia" [--em 3,12,28]
                  [--regiao x0,y0,x1,y1] [-o folha.png]

flags comuns: --amostras N (24) · --sem-metadados · --altura N (desligado)

═══ A DIVISÃO QUE GOVERNA O ARQUIVO ═══════════════════════════════════════════
A DETECÇÃO é deles. A CURVA é nossa.

Este script responde "o que é este arquivo" e "qual das nossas grades/LUTs se
aplica". Ele NUNCA inventa curva de conversão. Onde não temos curva medida, ele
RECUSA (`calibrado: false`, exit 3) e devolve o caminho para medir uma.

E a segunda divisão: `detect-cor.py` resolve a CONVERSÃO (de onde o arquivo vem
até Rec.709). O perfil de peça (perfil.py) resolve o LOOK (grade do creator,
punch). Grade de creator não entra aqui — é o que mantém a ilha vendável fora
desta máquina: um cliente do produto tem perfis de cor, não tem `creators/`.

═══ POR QUE ISTO EXISTE ═══════════════════════════════════════════════════════
Até hoje a decisão mais cara da cadeia de cor era tomada por um humano lendo
prosa: "se o bruto é HDR (iPhone: BT.2020/HLG — conferir com ffprobe): LUT
hlg2sdr.cube". Nenhum script conferia. O que sustentava o acerto é que todo
bruto até hoje foi iPhone HLG. Um take de Sony em S-Log3, um DJI em D-Log, um
ProRes Apple Log ou um MP4 que voltou do WhatsApp fazem a cadeia aplicar a
inversa da OETF HLG sobre um sinal que não é HLG, sem avisar ninguém.

⚠️ LIMITAÇÃO DECLARADA, não escondida: o Tier 1 (metadado) é a ÚNICA camada
capaz de reconhecer HDR. Se as tags foram raspadas (transcode, remux, bsf), o
Tier 2 devolve `rec709` com confiança ALTA sobre pixels HLG. Medido nos dois
brutos HLG deste repo: `black_floor` 0,051 · `white_ceiling` 0,937 ·
`sat_mean` 0,080 → score 0 → rec709, alta. HLG é retrocompatível por desenho:
preto no lugar, branco no lugar, saturação normal. Resposta errada com confiança
máxima. Por isso o `cor.json` grava `tier`, o Tier 2 escreve esse aviso na
`evidencia`, e o `qc-cor.py` não confia no detector sozinho — ele cruza rótulo
contra PIXEL, comparando com o bruto.

🔴 ESTE É O ÚNICO ARQUIVO DO PACOTE COM CÓDIGO DE TERCEIRO. A atribuição está no
cabeçalho de 3 linhas no topo, a licença integral em LICENSES/, e a entrada
correspondente em AVISOS-DE-TERCEIROS.md — as três, porque a licença pede as três
e porque o Portão 6 do exportador confere que elas existem juntas.

DERIVADO: `_probe`, `VENDOR_LOG_HINTS`, a assinatura Apple Log, `_sample_stats`,
a pontuação do Tier 2, `_measured_log_expansion` e `wide_gamut_chain` — 43 de
1.045 linhas, medidas.
NÃO derivado, de propósito: a `TONEMAP_CHAIN` — a nossa curva HDR→SDR é MEDIDA do
avconvert da Apple (luts/curva-apple-hlg2sdr.json), não derivada de standard.

Reescrever esses 43 a partir da especificação zera a obrigação e tira este
arquivo de `portados`; enquanto não for feito, a atribuição fica.
"""
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile

CONTRATO = "benchmark.cor/v1.1"
VERSAO = "1.1"
# realpath, NÃO abspath: `.claude/skills/edit-video` é symlink para `ilha/skills/
# edit-video` (SPEC-000 §3.3). Com abspath o `../../..` sobe pela árvore do
# symlink e o catálogo é procurado em `.claude/tools/…`, que não existe.
DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))

# ---------------------------------------------------------------------------
# 🔬 FÍSICA, não formato. Estes números não descrevem aspecto, resolução nem fps
# — descrevem o sinal. Por isso ficam no script e não no perfil de peça.
#   TV_BLACK: a âncora de preto do range limitado, 16/255 normalizado.
#   PCT_PISO/PCT_TETO: percentis de YMIN/YMAX. Um frame com pixel morto não pode
#   decidir o piso de preto do clipe inteiro.
# ---------------------------------------------------------------------------
TV_BLACK = 16 / 255
PCT_PISO = 0.10
PCT_TETO = 0.90
FPS_AMOSTRA_MIN = 0.2
FPS_AMOSTRA_MAX = 8.0

# dados portados literalmente de detect_color.py:44-50
VENDOR_LOG_HINTS = {
    "slog3": "sony_slog3", "s-log3": "sony_slog3", "sgamut": "sony_slog3",
    "s-gamut": "sony_slog3", "vlog": "panasonic_vlog", "v-log": "panasonic_vlog",
    "clog": "canon_clog3", "c-log": "canon_clog3", "logc": "arri_logc",
    "n-log": "nikon_nlog", "nlog": "nikon_nlog", "f-log": "fuji_flog",
    "flog": "fuji_flog", "dlog": "dji_dlog", "d-log": "dji_dlog",
}

# render.py:157-158 — gamut largo em SDR. NÃO é HDR, e é o buraco do contrato
# deles: o detect_color.py não trata gamut (a lógica vive no render.py, fora do
# detector), então um H.264 BT.2020 SDR cai no Tier 2, mede pretos e brancos
# normais e volta rec709 com confiança alta. Aqui a regra mora DENTRO do detector,
# porque o nosso cor.json é a única fonte da cadeia.
PRIMARIAS_LARGAS = {"bt2020"}
MATRIZES_LARGAS = {"bt2020nc", "bt2020_ncl", "bt2020c", "bt2020_cl"}

TRANSFERS_SDR = {"bt709", "bt470bg", "smpte170m", "iec61966-2-1"}
# 🔑 UM DONO SÓ. Quais transfers são HDR é conhecimento de CLASSIFICAÇÃO DE COR, e
# este arquivo é quem classifica. Antes da SPEC-25 a mesma lista vivia solta no
# `qc-cor.py`; uma terceira cópia no `montar.sh` seriam três réguas para a mesma
# pergunta — que é como a régua de um dos lados envelhece sem ninguém ver.
TRANSFERS_HDR = {"arib-std-b67", "smpte2084"}
PRIMARIAS_SDR = {"bt709", "smpte170m", "bt470bg"}

# vocabulário do perfil de peça (perfil.json → cor.entrada_esperada)
EQUIV_PERFIL = {"hlg": "hlg", "rec709": "sdr", "bt2020_sdr": "sdr"}
ENTRADAS_ESPERADAS = {"hlg", "sdr"}

SAI_OK = 0
SAI_ERRO = 1
SAI_DIVERGE = 2
SAI_HUMANO = 3


def normalizar_entrada_esperada(declarada):
    """Forma canônica do contrato de entrada para comparação e fingerprint.

    A lista é um conjunto de perfis aceitos: trocar ``["hlg", "sdr"]`` por
    ``["sdr", "hlg"]`` não muda a decisão e, portanto, não pode envelhecer um
    ``cor.json``. Duplicatas também não mudam a semântica. Valores inválidos são
    preservados de forma determinística para que ainda produzam um hash e sejam
    recusados por :func:`avaliar_expectativa`.
    """
    if declarada is None:
        return "auto"
    if not isinstance(declarada, list):
        return declarada
    unicos = {}
    for item in declarada:
        chave = json.dumps(item, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
        unicos[chave] = item
    return [unicos[chave] for chave in sorted(unicos)]


def hash_entrada_esperada(declarada):
    """SHA-256 da semântica de ``cor.entrada_esperada``."""
    canonico = json.dumps(normalizar_entrada_esperada(declarada), sort_keys=True,
                          ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def avaliar_expectativa(perfil_detectado, declarada):
    """Compara detecção e contrato da peça sem alterar perfil, pixels ou tags."""
    visto = EQUIV_PERFIL.get(perfil_detectado, perfil_detectado)
    if declarada is None or declarada == "auto":
        return {"declarada": "auto", "aceitos": [], "detectado": visto,
                "estado": "auto", "decisao": "usar-deteccao-sem-relabel"}
    aceitos = list(declarada) if isinstance(declarada, list) else [declarada]
    invalidos = [x for x in aceitos
                 if not isinstance(x, str) or x not in ENTRADAS_ESPERADAS]
    if not aceitos or invalidos:
        return {"declarada": declarada, "aceitos": aceitos, "detectado": visto,
                "estado": "invalida", "invalidos": invalidos,
                "decisao": "bloquear-sem-converter"}
    compativel = visto in aceitos
    return {"declarada": declarada, "aceitos": aceitos, "detectado": visto,
            "estado": "compativel" if compativel else "divergente",
            "decisao": ("usar-deteccao-sem-relabel" if compativel
                        else "bloquear-sem-converter")}


def avaliar_expectativa_fontes(perfil_principal, fontes, declarada):
    """Avalia o contrato contra TODAS as fontes usadas, não só a principal.

    Os campos históricos de topo continuam descrevendo a fonte principal. O
    estado e a decisão, porém, são agregados: uma única fonte divergente ou uma
    declaração inválida bloqueia a produção inteira. ``por_fonte`` deixa o
    motivo auditável sem obrigar o consumidor a refazer a detecção.
    """
    resultado = avaliar_expectativa(perfil_principal, declarada)
    por_fonte = {}
    for src, info in fontes.items():
        por_fonte[src] = avaliar_expectativa(info.get("perfil"), declarada)

    estados = [resultado["estado"]] + [x["estado"] for x in por_fonte.values()]
    bloqueadas = [src for src, x in por_fonte.items()
                  if x["estado"] in ("divergente", "invalida")]
    if "invalida" in estados:
        resultado["estado"] = "invalida"
        resultado["decisao"] = "bloquear-sem-converter"
    elif "divergente" in estados:
        resultado["estado"] = "divergente"
        resultado["decisao"] = "bloquear-sem-converter"
    resultado["por_fonte"] = por_fonte
    resultado["fontes_bloqueadas"] = bloqueadas
    return resultado


# ═══════════════════════════════════════════════════════════ catálogo (a curva)
def dir_luts():
    """$BENCH_LUTS_DIR → o `tools/remotion-compositor/luts` do ancestral que o tem.

    🔴 MEDIDO NO PACOTE, 2026-08-12 (o zip da v0.11 rodado num container Ubuntu).
    Aqui estava um `../../..` a partir de `DIR_SCRIPT`, que é uma AFIRMAÇÃO sobre
    onde a skill mora: na nossa árvore o realpath dá `ilha/skills/edit-video/
    scripts`, três níveis acima é `ilha/`, e `ilha/tools/remotion-compositor/luts`
    existe. Na instalação do cliente a skill É `<raiz>/.claude/skills/edit-video/
    scripts` de verdade (não symlink), os mesmos três níveis dão `<raiz>/.claude/`,
    e o catálogo de cor foi procurado em `.claude/tools/…`, que não existe.
    Efeito medido: `detect-cor.py` estourava `FileNotFoundError` em
    `carregar_catalogo()`, o `montar.sh` morria com ele, e `test_contrato_ui.py`
    reprovava numa instalação correta.

    A saída é a mesma de `gerar-previews.py:_base_das_skills()` e
    `previews-peca.py:_raiz_por_marcador()`: subir até um MARCADOR, nunca contar
    níveis. O marcador é o próprio diretório de luts.
    """
    env = os.environ.get("BENCH_LUTS_DIR")
    if env:
        return env
    d = DIR_SCRIPT
    while True:
        cand = os.path.join(d, "tools", "remotion-compositor", "luts")
        if os.path.isdir(cand):
            return cand
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    # sem marcador: devolve o palpite histórico em vez de estourar aqui, e quem
    # abrir o arquivo falha nomeando o caminho que tentou.
    return os.path.normpath(os.path.join(DIR_SCRIPT, "..", "..", "..",
                                         "tools", "remotion-compositor", "luts"))


def raiz_repo():
    """A raiz a partir da qual `cadeia[].arquivo` é relativo (§9.11: relativo no
    dado, absoluto só no `vf`, que é efêmero)."""
    return os.path.normpath(os.path.join(dir_luts(), "..", "..", ".."))


def carregar_catalogo(caminho=None):
    c = caminho or os.path.join(dir_luts(), "catalogo-cor.json")
    with open(c, encoding="utf-8") as fh:
        d = json.load(fh)
    d["_caminho"] = c
    return d


def entrada_catalogo(cat, perfil):
    """Exato primeiro; depois os padrões fnmatch declarados em `casa`.

    É assim que `sony_slog3` chega em `log_*` sem o script carregar uma segunda
    cópia da lista de fabricantes."""
    ent = cat.get("entradas") or {}
    if perfil in ent:
        return perfil, ent[perfil]
    for chave, val in ent.items():
        for pad in (val.get("casa") or []):
            if fnmatch.fnmatch(perfil, pad):
                return chave, val
    return None, None


# ═════════════════════════════════════════════════════════════ Tier 1 (metadado)
def _probe(video):
    """Porte de detect_color.py:53-70. UM ffprobe, com stream_tags e format_tags
    fundidos — é esse merge que torna a busca por assinatura de fabricante
    trivial."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,profile,pix_fmt,color_transfer,color_primaries,"
         "color_space,color_range,bits_per_raw_sample,width,height",
         "-show_entries", "stream_tags", "-show_entries", "format_tags",
         "-of", "json", str(video)],
        capture_output=True, text=True)
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}, {}
    fluxos = d.get("streams") or []
    if not fluxos:
        return {}, {}
    st = fluxos[0]
    tags = {**(d.get("format", {}).get("tags") or {}), **(st.get("tags") or {})}
    return st, tags


def classificar_tier1(st, tags):
    """FUNÇÃO PURA sobre dicionário: (st, tags) -> dict | None.

    É pura de propósito. As oito ramificações abaixo só são testáveis sem
    fabricar oito arquivos de mídia se a classificação não tocar em disco — e
    duas delas (Apple Log em ProRes, LOG de fabricante) NÃO se sintetizam de
    forma confiável nesta máquina: com -c:v prores_ks e setparams o arquivo sai
    com as três tags `unknown`, o que não reproduz a assinatura (que exige
    primaries=bt2020 COM transfer vazio).

    Devolve None quando o metadado é mudo — aí o chamador vai para o Tier 2."""
    trc = (st.get("color_transfer") or "").lower()
    prim = (st.get("color_primaries") or "").lower()
    mat = (st.get("color_space") or "").lower()
    codec = (st.get("codec_name") or "").lower()
    pix = (st.get("pix_fmt") or "").lower()
    blob = " ".join("%s=%s" % (k, v) for k, v in tags.items()).lower()

    # 1 — HLG (detect_color.py:176-180)
    if trc == "arib-std-b67":
        return {"perfil": "hlg", "confianca": "alta",
                "evidencia": ["color_transfer=arib-std-b67"]}
    # 2 — PQ (:182-186)
    if trc == "smpte2084":
        return {"perfil": "pq", "confianca": "alta",
                "evidencia": ["color_transfer=smpte2084"]}
    # 3 — Apple Log nomeado em tag (:187-192)
    nomeado = tags.get("com.apple.proapps.logprofile")
    if nomeado:
        return {"perfil": "apple_log", "confianca": "alta",
                "evidencia": ["tag com.apple.proapps.logprofile=%s" % nomeado]}
    # 4 — LOG de fabricante pela assinatura no blob de tags (:44-50, :194-201)
    for dica, prof in VENDOR_LOG_HINTS.items():
        if dica in blob:
            return {"perfil": prof, "confianca": "alta",
                    "evidencia": ["blob de tags contém '%s'" % dica],
                    "precisa_stats": True}
    # 5 — Apple Log pela assinatura real (:203-210). O comentário deles merece vir
    # junto com o código: "Nothing in the file spells out 'Apple Log' — if you
    # wait for a tag that names it you will never find one."
    if codec == "prores" and "422p10" in pix and prim == "bt2020" \
            and trc in ("", "unknown"):
        return {"perfil": "apple_log", "confianca": "alta",
                "evidencia": ["prores 10-bit 4:2:2 + primaries bt2020 + transfer vazio"]}
    # 6 🆕 — gamut largo em SDR. NOSSA, não deles (a deles vive no render.py,
    # fora do contrato do detector — e é por isso que o contrato deles mente
    # exatamente no caso que confunde).
    if prim in PRIMARIAS_LARGAS or mat in MATRIZES_LARGAS:
        return {"perfil": "bt2020_sdr", "confianca": "alta",
                "evidencia": ["primaries=%s / color_space=%s com transferência "
                              "ordinária (%s)" % (prim or "?", mat or "?", trc or "vazio")]}
    # 7 — Rec.709 declarado
    if trc in TRANSFERS_SDR and (prim in PRIMARIAS_SDR or not prim or prim == "unknown"):
        return {"perfil": "rec709", "confianca": "alta",
                "evidencia": ["color_transfer=%s / color_primaries=%s"
                              % (trc, prim or "vazio")]}
    # 8 — metadado mudo
    return None


# ═══════════════════════════════════════════════════════ Tier 2 (estatística)
def stats8(video, n=24, altura=None):
    """Porte de _sample_stats() (detect_color.py:73-136), com DUAS decisões
    nossas, as duas medidas.

    (a) `format=yuv420p` antes do signalstats — GUARDA DE INVARIÂNCIA, não
        conserto de bug. Medido nos dois brutos HLG 10-bit do repo: a
        normalização por 2^depth−1 deles funciona, a diferença 10-bit vs 8-bit
        fica em ~1,4% relativo no sat_mean e NÃO flipa bucket em nenhum arquivo
        deste repo. Forçar 8 bits trava a métrica no domínio em que os limiares
        deles foram calibrados (detect_color.py:247-252). Quem escrever no commit
        que "o 10-bit fabricava LOG falso" está inventando número.

    (b) 🔴 SEM downscale de amostragem. Medido e reprovado por dois motivos:
        YMIN/YMAX são EXTREMOS por frame, e qualquer subamostragem joga os
        extremos fora — no bruto 4K o `white_ceiling` anda 0,039 com
        scale=-2:480:flags=neighbor, quase o dobro do limiar que separa "teto
        baixo" de "teto normal". E não acelera: 12,3 s sem × 12,7 s com, no mesmo
        arquivo de 79 s. O decode domina. `--altura` fica como escape manual,
        desligado por default e com aviso."""
    try:
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)]).decode().strip())
    except Exception:
        dur = 10.0
    fps = max(FPS_AMOSTRA_MIN, min(n / max(dur, 0.1), FPS_AMOSTRA_MAX))

    filtros = ["fps=%.3f" % fps]
    if altura:
        print("⚠️ --altura %s: subamostragem espacial DESLOCA os extremos "
              "(YMIN/YMAX são extremos por frame). Medido no bruto 4K: o "
              "white_ceiling anda ≈0,039. Use só para diagnóstico." % altura,
              file=sys.stderr)
        filtros.append("scale=-2:%d:flags=neighbor" % int(altura))
    filtros += ["format=yuv420p", "signalstats"]

    fh = tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False)
    meta = fh.name
    fh.close()
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-nostats", "-nostdin", "-i", str(video),
             "-vf", ",".join(filtros) + ",metadata=print:file=%s" % meta,
             "-an", "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return None
        ymin, ymax, yavg, sat = [], [], [], []
        prof = 8
        with open(meta, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if "=" not in linha:
                    continue
                chave, _, val = linha.rpartition("=")
                try:
                    v = float(val)
                except ValueError:
                    continue
                if chave.endswith("YBITDEPTH"):
                    prof = int(v)
                elif chave.endswith("YMIN"):
                    ymin.append(v)
                elif chave.endswith("YMAX"):
                    ymax.append(v)
                elif chave.endswith("YAVG"):
                    yavg.append(v)
                elif chave.endswith("SATAVG"):
                    sat.append(v)
        if not ymin or not ymax:
            return None
        mx = (2 ** prof) - 1

        def pct(xs, p):
            s = sorted(xs)
            return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))] / mx

        return {"black_floor": pct(ymin, PCT_PISO),
                "white_ceiling": pct(ymax, PCT_TETO),
                "y_mean": (sum(yavg) / len(yavg) / mx) if yavg else 0.5,
                "sat_mean": (sum(sat) / len(sat) / mx) if sat else 0.25,
                "frames": len(ymin), "bit_depth": prof}
    finally:
        try:
            os.unlink(meta)
        except OSError:
            pass


def pontuar_tier2(s):
    """Pontuação IDÊNTICA à deles (detect_color.py:224-272), e é para ficar
    idêntica: são limiares calibrados em material real 8-bit.

    ⚠️ NÃO subir os limiares de saturação "para parecerem porcentagem". SATAVG é
    magnitude de croma na profundidade nativa, não saturação 0..1; subir os
    números adiciona ponto a TODO clipe e fabrica detecção de LOG. O que se
    corrige é o domínio (8 bits), não os limiares."""
    bf, wc, sat = s["black_floor"], s["white_ceiling"], s["sat_mean"]
    faixa = wc - bf
    ev, score = [], 0

    if bf > TV_BLACK + 0.045:
        score += 2
        ev.append("piso de preto alto (%.3f, TV black=%.3f)" % (bf, TV_BLACK))
    elif bf > TV_BLACK + 0.02:
        score += 1
        ev.append("piso de preto levemente alto (%.3f)" % bf)
    else:
        ev.append("piso de preto normal (%.3f) — chega ao preto real" % bf)

    if wc < 0.80:
        score += 1
        ev.append("teto de branco baixo (%.3f)" % wc)
    else:
        ev.append("teto de branco normal (%.3f)" % wc)

    if faixa < 0.62:
        score += 2
        ev.append("faixa comprimida (%.3f)" % faixa)
    else:
        ev.append("faixa normal (%.3f)" % faixa)

    if sat < 0.025:
        score += 2
        ev.append("saturação muito baixa (%.3f)" % sat)
    elif sat < 0.040:
        score += 1
        ev.append("saturação baixa (%.3f)" % sat)
    else:
        ev.append("saturação normal (%.3f)" % sat)

    if score >= 5:
        perfil, conf = "log_desconhecido", "alta"
    elif score >= 3:
        # cena clara sem sombras (fundo branco de produto, janela estourada atrás
        # do sujeito) levanta o piso de preto e imita LOG. Não "melhore" isto
        # baixando o limiar.
        perfil, conf = "log_desconhecido", "baixa"
        ev.append("ambíguo — cena clara e sem sombras dá a mesma assinatura")
    else:
        perfil, conf = "rec709", "alta"

    ev.append("⚠️ o Tier 2 NÃO reconhece HDR: HLG é retrocompatível por desenho "
              "(preto no lugar, branco no lugar, saturação normal), então um "
              "arquivo HLG com as tags raspadas sai daqui como rec709 com "
              "confiança alta. Medido nos dois brutos HLG deste repo.")
    return perfil, conf, score, ev


def expansao_medida(s):
    """Porte de _measured_log_expansion() (detect_color.py:143-159).

    Vale portar porque é expansão derivada da MEDIÇÃO da própria imagem, não
    curva de fabricante chutada — compatível com a doutrina deste repo. Mas sai
    `calibrado: false`: é ponto de partida para o `candidatos`, não entregável."""
    bf = max(0.0, min(0.30, s["black_floor"] - 0.01))
    wc = max(0.55, min(1.0, s["white_ceiling"] + 0.01))
    faixa = wc - bf
    contraste = max(1.0, min(1.45, 0.72 / max(faixa, 0.2)))
    sat = max(1.0, min(1.35, 0.22 / max(s["sat_mean"], 0.06)))
    return ("colorlevels=rimin=%.3f:gimin=%.3f:bimin=%.3f:"
            "rimax=%.3f:gimax=%.3f:bimax=%.3f,"
            "eq=contrast=%.2f:saturation=%.2f"
            % (bf, bf, bf, wc, wc, wc, contraste, sat))


# ═══════════════════════════════════════════════════════════════════ detecção
def _filtro_colorspace(modelo, st):
    mat = (st.get("color_space") or "").lower() or "bt2020nc"
    prim = (st.get("color_primaries") or "").lower() or "bt2020"
    rng = "pc" if (st.get("color_range") or "").lower() == "pc" else "tv"
    return modelo.replace("{matriz}", mat).replace("{primarias}", prim) \
                 .replace("{range}", rng)


def montar_cadeia(cat, perfil, st, stats):
    """Perfil detectado -> (cadeia, calibrado, acao_humana, chave_catalogo)."""
    chave, ent = entrada_catalogo(cat, perfil)
    if ent is None:
        return None, False, ("perfil '%s' não está no catálogo %s — acrescente a "
                             "entrada antes de converter." % (perfil, cat["_caminho"])), None
    bruta = ent.get("cadeia")
    calibrado = bool(ent.get("calibrado"))
    if bruta is None:
        return None, calibrado, ent.get("acao"), chave
    if bruta == "expansao-medida":
        if not stats:
            return None, False, ("expansão medida exige estatística de imagem e "
                                 "ela falhou neste arquivo."), chave
        return ([{"tipo": "expansao-medida", "filtro": expansao_medida(stats)}],
                calibrado, ent.get("acao"), chave)
    cadeia = []
    for passo in bruta:
        p = dict(passo)
        if p.get("tipo") == "lut3d":
            rel = p["arquivo"]
            absoluto = os.path.join(raiz_repo(), rel)
            if not os.path.isfile(absoluto):
                return None, False, ("a LUT %s do catálogo não existe em %s"
                                     % (rel, absoluto)), chave
            p["filtro"] = "lut3d=%s" % absoluto
        elif p.get("tipo") == "colorspace":
            p["filtro"] = _filtro_colorspace(p["filtro"], st)
        cadeia.append(p)
    return cadeia, calibrado, ent.get("acao"), chave


def setparams_de(cat):
    t = (cat.get("saida") or {}).get("tags") or {}
    itens = ["%s=%s" % (k, t[k]) for k in ("color_primaries", "color_trc", "colorspace")
             if t.get(k)]
    return ("setparams=" + ":".join(itens)) if itens else ""


def fragmento_de(cadeia):
    """SPEC-25 §3.4(a) — SÓ a conversão, sem a tag e sem geometria, e com o
    caminho da `.cube` RELATIVO à raiz do repo.

    É o par do `vf`, e a diferença entre os dois não é cosmética:

      `vf`            é de ARQUIVO INTEIRO. Carrega o `setparams` junto e caminho
                      absoluto, porque quem o consome (`candidatos`, os scripts de
                      amostragem, o modo `aplicar_em: "passe"`) monta um ffmpeg de
                      um passo só, e ali a tag tem que ir no mesmo filtergraph.
      `fragmento_vf`  é de SEGMENTO. Entra NO MEIO do `vf` que o perfil de peça
                      produz — depois do `scale`, antes do `setparams` que já está
                      lá. Colar o `vf` no lugar dele mete um segundo `setparams`
                      ANTES da conversão, e isso NÃO é cosmético: medido em
                      2026-08-09 no seg000 da `peca-01`, `setparams` antes
                      do `lut3d` move a luminância média **+0,42%** (|d| médio
                      1,62/255, máx 35), porque o yuv→rgb que o ffmpeg insere
                      sozinho na frente do `lut3d` usa a matriz que o `setparams`
                      acabou de escrever.

    Por isso `uso_do_vf: "arquivo-inteiro"` também é gravado: um leitor que não
    saiba a diferença tem como descobrir sem medir de novo.
    """
    if not cadeia:
        return ""
    partes = []
    for p in cadeia:
        if p.get("tipo") == "lut3d" and p.get("arquivo"):
            partes.append("lut3d=%s" % p["arquivo"])       # RELATIVO à raiz do repo
        elif p.get("filtro"):
            partes.append(p["filtro"])
    return ",".join(partes)


def detectar(video, amostras=24, sem_metadados=False, altura=None, cat=None):
    """Devolve o dicionário `benchmark.cor/v1.1` (sem os campos de produção)."""
    cat = cat or carregar_catalogo()
    st, tags = _probe(video)
    if not st:
        return None
    fonte = {"codec": st.get("codec_name"), "pix_fmt": st.get("pix_fmt"),
             "color_space": st.get("color_space"),
             "color_transfer": st.get("color_transfer"),
             "color_primaries": st.get("color_primaries"),
             "color_range": st.get("color_range")}

    t1 = None if sem_metadados else classificar_tier1(st, tags)
    stats = score = None
    if t1:
        tier, perfil, conf = "metadados", t1["perfil"], t1["confianca"]
        ev = list(t1["evidencia"])
        if t1.get("precisa_stats"):
            stats = stats8(video, amostras, altura)
    else:
        tier = "estatistica"
        stats = stats8(video, amostras, altura)
        if not stats:
            perfil, conf, ev = "rec709", "baixa", ["análise de imagem falhou"]
        else:
            perfil, conf, score, ev = pontuar_tier2(stats)
        if sem_metadados:
            ev.insert(0, "--sem-metadados: Tier 1 pulado à força")

    # expansão medida precisa da estatística mesmo quando o Tier 1 resolveu
    if perfil in ("apple_log",) or "log" in perfil:
        if stats is None:
            stats = stats8(video, amostras, altura)

    cadeia, calibrado, acao, chave = montar_cadeia(cat, perfil, st, stats)
    filtros = [p["filtro"] for p in (cadeia or []) if p.get("filtro")]
    sp = setparams_de(cat)
    vf = None
    if cadeia is not None and calibrado:
        vf = ",".join(filtros + ([sp] if sp else [])) or sp or None

    frag = fragmento_de(cadeia) if (cadeia is not None and calibrado) else ""

    saida = (cat.get("saida") or {})
    return {
        "contrato": CONTRATO,
        "arquivo": str(video),
        "perfil": perfil,
        "confianca": conf,
        "calibrado": calibrado,
        "tier": tier,
        "catalogo_entrada": chave,
        "evidencia": ev,
        "stats": stats,
        "score": score,
        "fonte": fonte,
        "cadeia": cadeia,
        "tags_saida": saida.get("tags"),
        "aplicar_tags_por": saida.get("aplicar_por"),
        "vf": vf,
        "uso_do_vf": "arquivo-inteiro",   # SPEC-25 §3.4(a)
        "fragmento_vf": frag,             # SPEC-25 §3.4(a) — só conversão, relativo
        # SPEC-25 §3.4(c): quem DETECTA nunca escreve isto. Quem APLICA promove
        # para "extracao" (montar.sh) ou "passe". `null` = ninguém aplicou ainda,
        # e é o que faz o qc-cor.py cair no comportamento da SPEC-11 nas 13
        # produções antigas, que é exatamente o que se quer delas.
        "aplicada_em": None,
        "acao_humana": None if (calibrado and conf == "alta") else (
            acao or "confiança baixa — confirme com um humano antes de aplicar."),
    }


def codigo_de(r):
    if r is None:
        return SAI_ERRO
    return SAI_OK if (r["calibrado"] and r["confianca"] == "alta") else SAI_HUMANO


# ══════════════════════════════════════════════════════════════════ impressão
def imprimir(r):
    print("perfil: %s   (confiança %s, via %s)" % (r["perfil"], r["confianca"], r["tier"]))
    for e in r["evidencia"]:
        print("  · %s" % e)
    if r.get("stats"):
        s = r["stats"]
        print("  amostras: %d frames, %d-bit  ·  bf %.4f · wc %.4f · sat %.4f"
              % (s["frames"], s["bit_depth"], s["black_floor"],
                 s["white_ceiling"], s["sat_mean"]))
    if r.get("score") is not None:
        print("  score Tier 2: %d" % r["score"])
    print("calibrado: %s" % ("sim" if r["calibrado"] else "NÃO"))
    if r["cadeia"] is None:
        print("cadeia: (nenhuma — não convertemos este perfil)")
    elif not r["cadeia"]:
        print("cadeia: (vazia — já está no destino)")
    else:
        for p in r["cadeia"]:
            print("cadeia: %s → %s" % (p["tipo"], p.get("filtro", "?")))
    if r["vf"]:
        print("vf: %s   (uso: %s)" % (r["vf"], r.get("uso_do_vf") or "?"))
    print("fragmento_vf (segmento): %s" % (r.get("fragmento_vf") or "(vazio)"))
    fontes = r.get("fontes") or {}
    if fontes:
        print("fontes da EDL: %d" % len(fontes))
        for src, f in fontes.items():
            print("  %s %-40s %-10s conf %-6s %s"
                  % ("✅" if (f["calibrado"] and f["confianca"] == "alta") else "🔴",
                     src, f["perfil"], f["confianca"],
                     ("%.1fs" % f["segundos"]) if f.get("segundos") is not None else ""))
    if r["acao_humana"]:
        print("\nAÇÃO HUMANA: %s" % r["acao_humana"])


# ═══════════════════════════════════════════════════════════════════ resolver
def cmd_resolver(argv):
    if not argv:
        return uso()
    d = argv[0]
    bruto = flag(argv, "--bruto")
    amostras = int(flag(argv, "--amostras", "24"))
    altura = flag(argv, "--altura")
    sem_meta = "--sem-metadados" in argv
    if not os.path.isdir(d):
        print("erro: %s não é diretório" % d, file=sys.stderr)
        return SAI_ERRO
    # ── SPEC-25 §3.4(b): SEM --bruto, a unidade é a EDL, não "o bruto" ─────────
    # A conversão passa a ser POR SEGMENTO, e cada segmento conhece a sua `src`.
    # Um timeline com um take de iPhone HLG e um screencast BT.709 precisa de uma
    # resolução por fonte — depois do concat existe um arquivo só, e não há LUT
    # única que sirva para os dois. Os campos de TOPO continuam descrevendo a
    # fonte PRINCIPAL (a de maior tempo somado), que é o que mantém o contrato
    # legível por quem já lia `cor.perfil`.
    fontes_edl = [] if bruto else srcs_da_edl(d)
    alvo = os.path.join(d, bruto) if bruto and not os.path.isabs(bruto) else bruto
    if not alvo and fontes_edl:
        alvo = os.path.join(d, fontes_edl[0][0])
    if not alvo:
        alvo = achar_bruto(d)
    if not alvo or not os.path.isfile(alvo):
        print("erro: bruto não encontrado (%s). Passe --bruto <caminho>."
              % (alvo or "nenhum candidato em input/"), file=sys.stderr)
        return SAI_ERRO

    cat = carregar_catalogo()
    r = detectar(alvo, amostras, sem_meta, int(altura) if altura else None, cat)
    if r is None:
        print("erro: ffprobe não devolveu stream de vídeo em %s" % alvo, file=sys.stderr)
        return SAI_ERRO
    try:
        r["arquivo"] = os.path.relpath(alvo, d)
    except ValueError:
        pass

    # uma entrada por `src` distinto. Com --bruto a lista tem um item só — o
    # bloco `fontes` existe SEMPRE, para que o consumidor não precise de dois
    # caminhos de leitura (e é ele que o montar.sh consulta por segmento).
    fontes, faltando = {}, []
    lista = fontes_edl or [(r["arquivo"], None)]
    for src, segundos in lista:
        cam = os.path.join(d, src) if not os.path.isabs(src) else src
        if not os.path.isfile(cam):
            faltando.append(src)
            continue
        rf = r if os.path.normpath(cam) == os.path.normpath(alvo) else \
            detectar(cam, amostras, sem_meta, int(altura) if altura else None, cat)
        if rf is None:
            faltando.append(src)
            continue
        fontes[src] = {
            "perfil": rf["perfil"], "confianca": rf["confianca"],
            "calibrado": rf["calibrado"], "tier": rf["tier"],
            "catalogo_entrada": rf["catalogo_entrada"],
            "fragmento_vf": rf["fragmento_vf"],
            "fonte": rf["fonte"], "tags_saida": rf["tags_saida"],
            "acao_humana": rf["acao_humana"],
            "segundos": None if segundos is None else round(segundos, 3),
        }
    r["fontes"] = fontes
    if faltando:
        # 🔴 nunca em silêncio: um `src` que não abre é EDL apontando para arquivo
        # que não existe, e o montar.sh vai morrer nele de qualquer forma. Melhor
        # saber aqui, com o nome.
        print("⚠️ %d src da EDL sem arquivo legível (não entraram em `fontes`): %s"
              % (len(faltando), ", ".join(faltando)), file=sys.stderr)

    import datetime
    with open(cat["_caminho"], "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    r["_procedencia"] = {
        "resolvido_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "catalogo": os.path.relpath(cat["_caminho"], raiz_repo()),
        "catalogo_sha256": sha,
        "detect_cor_versao": VERSAO,
    }

    code = codigo_de(r)
    # o veredito é da PEÇA, não só da fonte principal: uma segunda fonte não
    # calibrada trava a montagem (§3.7) e teria saído 0 aqui se o código olhasse
    # só o topo.
    for src, f in fontes.items():
        if not (f["calibrado"] and f["confianca"] == "alta") and code == SAI_OK:
            code = SAI_HUMANO
    # ---- divergência com o perfil de peça (perfil.json), se ele existir -------
    # NUNCA escrevemos em perfil.json. E não obedecemos nem sobrescrevemos: se a
    # produção declarou um valor e o arquivo é outro, alguém trocou o bruto, e
    # adivinhar aqui é como se entrega defeito.
    pj = os.path.join(d, "perfil.json")
    if os.path.isfile(pj):
        try:
            with open(pj, encoding="utf-8") as fh:
                valor = (json.load(fh).get("cor") or {}).get("entrada_esperada", "auto")
                esperado = "auto" if valor is None else valor
        except (ValueError, OSError):
            esperado = "auto"
        expectativa = avaliar_expectativa_fontes(r["perfil"], fontes, esperado)
        r["perfil_esperado"] = esperado
        r["perfil_esperado_sha256"] = hash_entrada_esperada(esperado)
        r["expectativa_cor"] = expectativa
        if expectativa["estado"] in ("divergente", "invalida"):
            print("🔴 DIVERGÊNCIA: perfil.json declara cor.entrada_esperada=%s; "
                  "%d fonte(s) usada(s) pela EDL violam o contrato. Não obedeço, "
                  "não relabelo e não converto em silêncio."
                  % (json.dumps(esperado, ensure_ascii=False),
                     len(expectativa.get("fontes_bloqueadas") or [r["arquivo"]])),
                  file=sys.stderr)
            for src in expectativa.get("fontes_bloqueadas") or []:
                ef = expectativa["por_fonte"][src]
                print("   · %s: detectado=%s · estado=%s"
                      % (src, ef["detectado"], ef["estado"]), file=sys.stderr)
            code = SAI_DIVERGE
        else:
            print("expectativa de cor: %s · detectado=%s · decisão=%s"
                  % (expectativa["estado"], expectativa["detectado"],
                     expectativa["decisao"]), file=sys.stderr)

    destino = os.path.join(d, "cor.json")
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    imprimir(r)
    print(destino)
    return code


def srcs_da_edl(d):
    """Os `src` DISTINTOS da EDL, com os segundos somados de cada um, do maior
    para o menor (SPEC-25 §3.4(b)).

    Devolve `[]` quando não há `edl.json` — resolver um bruto solto continua
    sendo o caminho de sempre, e é o que a `--bruto` pede explicitamente."""
    if not os.path.isfile(os.path.join(d, "edl.json")):
        return []
    if DIR_SCRIPT not in sys.path:
        sys.path.insert(0, DIR_SCRIPT)
    import edl_io
    soma = {}
    for s in edl_io.segmentos(d):
        src = s.get("src")
        if not src:
            continue
        try:
            dur = float(s["end"]) - float(s["start"])
        except (KeyError, TypeError, ValueError):
            dur = 0.0
        soma[src] = soma.get(src, 0.0) + max(0.0, dur)
    return sorted(soma.items(), key=lambda kv: (-kv[1], kv[0]))


def achar_bruto(d):
    ind = os.path.join(d, "input")
    if not os.path.isdir(ind):
        return None
    cands = sorted(f for f in os.listdir(ind)
                   if os.path.splitext(f)[1].lower() in
                   (".mov", ".mp4", ".m4v", ".mxf", ".mkv"))
    return os.path.join(ind, cands[0]) if cands else None


# ═════════════════════════════════════════════════════════════════ candidatos
# Mecanismo de grade.py:325-401. O que acrescentamos vem, item a item, de um
# defeito nosso já medido: vários instantes, número embaixo de cada tile, e o
# guarda anti-HDR.
FOLHA_LARGURA_ALVO = 1600     # largura da FOLHA de diagnóstico (um PNG), não da
FOLHA_TILE_MIN = 360          # peça. Nenhum destes números entra em vídeo.
FOLHA_TILE_MAX = 760
FOLHA_ROTULO_H = 78
FOLHA_GAP = 8


def regiao_default(w, h):
    """Fração do quadro onde tipicamente vive o rosto. Derivada do ASPECTO do
    arquivo, não de constante de formato: em retrato é o terço central superior;
    em paisagem, o miolo. Devolve frações — o script é agnóstico a resolução."""
    if h > w:
        return (1.0 / 3, 0.15, 2.0 / 3, 0.45)
    return (1.0 / 3, 0.25, 2.0 / 3, 0.75)


def medir_regiao(img, reg):
    import numpy as np
    x = np.asarray(img, dtype=np.float64)
    h, w = x.shape[0], x.shape[1]
    x0, y0, x1, y1 = reg
    sub = x[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)),
            int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
    r, b = sub[:, :, 0].mean(), sub[:, :, 2].mean()
    return (sub.mean(), (sub.max(axis=2) - sub.min(axis=2)).mean(), r / max(b, 1e-6))


def cmd_candidatos(argv):
    from PIL import Image, ImageDraw, ImageFont

    if not argv:
        return uso()
    video = argv[0]
    spec = flag(argv, "--spec")
    saida = flag(argv, "-o") or flag(argv, "--saida") or "cor-candidatas.png"
    em = flag(argv, "--em")
    reg_txt = flag(argv, "--regiao")
    if not os.path.isfile(video):
        print("erro: %s não existe" % video, file=sys.stderr)
        return SAI_ERRO
    if not spec:
        print("erro: --spec é obrigatório "
              '(ex.: "apple=hlg2sdr.cube;quente=hlg2sdr.cube+peca-12-quente-35.cube;original=")',
              file=sys.stderr)
        return SAI_ERRO

    st, _ = _probe(video)
    # 🔴 GUARDA ANTI-HDR. O macOS comprime HDR a ~73% do range no screenshot: uma
    # folha com um tile HDR ao lado de tiles SDR mente 15–20% a favor do lado SDR.
    # Folha é sempre SDR contra SDR.
    trc = (st.get("color_transfer") or "").lower()
    hdr_na_fonte = trc in ("arib-std-b67", "smpte2084")

    dur = 0.0
    try:
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video]).decode().strip())
    except Exception:
        pass
    instantes = [float(x) for x in em.split(",")] if em else [dur / 2 if dur else 0.0]

    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    reg = tuple(float(x) for x in reg_txt.split(",")) if reg_txt else regiao_default(w, h)

    pares = []
    for parte in spec.split(";"):
        parte = parte.strip()
        if not parte:
            continue
        nome, _, filt = parte.partition("=")
        pares.append((nome.strip() or "cand%d" % (len(pares) + 1),
                      resolver_filtro(filt.strip())))
    if not pares:
        print("erro: --spec não produziu candidato nenhum", file=sys.stderr)
        return SAI_ERRO

    recusados = []
    if hdr_na_fonte:
        vivos = [(n, f) for n, f in pares if f]
        recusados = [n for n, f in pares if not f]
        if recusados:
            print("⚠️ fonte HDR (%s): %d tile(s) SEM conversão recusado(s) — %s. "
                  "O macOS comprime HDR a ~73%% do range no screenshot; a folha "
                  "mentiria 15–20%% a favor do lado SDR. Folha é SDR contra SDR."
                  % (trc, len(recusados), ", ".join(recusados)), file=sys.stderr)
        pares = vivos
    if not pares:
        print("erro: todos os candidatos foram recusados pelo guarda anti-HDR.",
              file=sys.stderr)
        return SAI_ERRO

    tmp = tempfile.mkdtemp(prefix="cand-cor-")
    tiles = []
    for t in instantes:
        base = os.path.join(tmp, "base-%.3f.png" % t)
        # 🔑 -pix_fmt rgb24 (grade.py:358-363): sem isso um fonte 10-bit escreve
        # PNG 16-bit e os candidatos são graduados numa profundidade que o render
        # nunca usa — "the montage the user approves would not be what ships".
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", "%.3f" % t,
                        "-i", video, "-frames:v", "1", "-pix_fmt", "rgb24", base],
                       check=True)
        for i, (nome, filt) in enumerate(pares):
            p = base
            if filt:
                p = os.path.join(tmp, "c%.3f-%d.png" % (t, i))
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", base,
                                "-vf", filt, "-frames:v", "1", p], check=True)
            img = Image.open(p).convert("RGB")
            lum, sat, rb = medir_regiao(img, reg)
            tiles.append(("%s @%.1fs" % (nome, t),
                          "lum %.1f · sat %.1f · R/B %.3f" % (lum, sat, rb), img))

    cols = max(1, min(len(pares), len(tiles)))
    linhas = (len(tiles) + cols - 1) // cols
    tw = max(FOLHA_TILE_MIN, min(FOLHA_TILE_MAX, FOLHA_LARGURA_ALVO // cols))
    th = int(tw * tiles[0][2].height / tiles[0][2].width)
    folha = Image.new("RGB", (cols * tw + (cols - 1) * FOLHA_GAP,
                              linhas * (th + FOLHA_ROTULO_H) + (linhas - 1) * FOLHA_GAP),
                      (12, 12, 14))
    dr = ImageDraw.Draw(folha)
    try:
        fonte = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
        peq = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except OSError:
        fonte = peq = ImageFont.load_default()
    for i, (nome, num, img) in enumerate(tiles):
        cx = (i % cols) * (tw + FOLHA_GAP)
        cy = (i // cols) * (th + FOLHA_ROTULO_H + FOLHA_GAP)
        dr.text((cx + 12, cy + 6), nome, fill=(255, 255, 255), font=fonte)
        dr.text((cx + 12, cy + 42), num, fill=(170, 210, 255), font=peq)
        folha.paste(img.resize((tw, th)), (cx, cy + FOLHA_ROTULO_H))
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    folha.save(saida)
    print("%d tiles · %d instantes · região %s do quadro · %dx%d"
          % (len(tiles), len(instantes),
             ",".join("%.3f" % x for x in reg), folha.width, folha.height),
          file=sys.stderr)
    print(saida)
    return SAI_OK


def resolver_filtro(txt):
    """`--spec` aceita, nessa ordem: nome do catálogo · caminho .cube (podem ser
    encadeados com `+`) · filtro cru. Vazio = tile original intocado."""
    if not txt:
        return ""
    cat = carregar_catalogo()
    _, ent = entrada_catalogo(cat, txt)
    if ent and isinstance(ent.get("cadeia"), list):
        return ",".join(
            "lut3d=%s" % os.path.join(raiz_repo(), p["arquivo"])
            if p.get("tipo") == "lut3d" else p.get("filtro", "")
            for p in ent["cadeia"])
    partes = []
    for pedaco in txt.split("+"):
        pedaco = pedaco.strip()
        cand = pedaco if os.path.isfile(pedaco) else os.path.join(dir_luts(), pedaco)
        if pedaco.endswith(".cube") and os.path.isfile(cand):
            partes.append("lut3d=%s" % os.path.abspath(cand))
        else:
            partes.append(pedaco)
    return ",".join(p for p in partes if p)


# ══════════════════════════════════════════════════════════ autoteste (Tier 1)
# A tabela das 8 ramificações do Tier 1, como DADO. Roda sem mídia nenhuma e sem
# fixture nenhuma — quem depende de fixture é o teste, não a ferramenta.
#
# Duas das oito NÃO se sintetizam de forma confiável nesta máquina: Apple Log em
# ProRes (com -c:v prores_ks e setparams o arquivo sai com as TRÊS tags
# `unknown`, o que não reproduz a assinatura, que exige primaries=bt2020 COM
# transfer vazio) e LOG de fabricante (a tag do fabricante não se forja). Por
# isso a classificação é função pura: é o único jeito de testar as oito.
CASOS_TIER1 = [
    ("HLG", {"color_transfer": "arib-std-b67"}, {}, "hlg", "alta"),
    ("PQ", {"color_transfer": "smpte2084"}, {}, "pq", "alta"),
    ("Apple Log nomeado", {}, {"com.apple.proapps.logprofile": "AppleLog"},
     "apple_log", "alta"),
    ("Sony S-Log3 por tag", {}, {"encoder": "Sony XAVC S-Log3 SGamut3.Cine"},
     "sony_slog3", "alta"),
    ("Apple Log por assinatura",
     {"codec_name": "prores", "pix_fmt": "yuv422p10le",
      "color_primaries": "bt2020", "color_transfer": ""}, {}, "apple_log", "alta"),
    ("BT.2020 SDR",
     {"color_primaries": "bt2020", "color_space": "bt2020nc",
      "color_transfer": "bt709"}, {}, "bt2020_sdr", "alta"),
    ("Rec.709",
     {"color_primaries": "bt709", "color_transfer": "bt709",
      "color_space": "bt709"}, {}, "rec709", "alta"),
    ("tudo unknown",
     {"color_primaries": "unknown", "color_transfer": "unknown",
      "color_space": "unknown", "codec_name": "h264", "pix_fmt": "yuv420p"},
     {}, None, None),
]


def cmd_autoteste(argv):
    falhas = 0
    for i, (nome, st, tags, esp_perfil, esp_conf) in enumerate(CASOS_TIER1, 1):
        r = classificar_tier1(st, tags)
        got_p = r["perfil"] if r else None
        got_c = r["confianca"] if r else None
        ok = (got_p == esp_perfil and got_c == esp_conf)
        falhas += 0 if ok else 1
        print("  %s %d/%d %-26s → %-16s %s"
              % ("✅" if ok else "❌", i, len(CASOS_TIER1), nome,
                 got_p if got_p else "None (→ Tier 2)",
                 "" if ok else "ESPERADO %s/%s" % (esp_perfil, esp_conf)))
    print("Tier 1: %d/%d casos" % (len(CASOS_TIER1) - falhas, len(CASOS_TIER1)))

    # controle negativo do próprio autoteste: um caso que ele TEM que reprovar.
    # Sem isto, "8/8 verde" e "o teste não roda" são indistinguíveis.
    if "--controle" in argv:
        mau = classificar_tier1({"color_transfer": "arib-std-b67"}, {})
        acusou = mau is not None and mau["perfil"] != "pq"
        print("  controle negativo (HLG afirmado como pq): %s"
              % ("✅ a régua reprova" if acusou else "❌ a régua aprovou o errado"))
        if not acusou:
            falhas += 1

    # o catálogo é o outro lado do contrato: sem entrada, o perfil detectado não
    # vira cadeia nenhuma.
    cat = carregar_catalogo()
    ent = cat.get("entradas") or {}
    print("catálogo: %d entradas — %s" % (len(ent), ", ".join(sorted(ent))))
    for chave, val in sorted(ent.items()):
        if not isinstance(val.get("calibrado"), bool):
            print("  ❌ %s sem `calibrado` booleano" % chave)
            falhas += 1
    perfis = ["hlg", "pq", "apple_log", "rec709", "bt2020_sdr", "log_desconhecido"]
    perfis += sorted(set(VENDOR_LOG_HINTS.values()))
    resolvem = 0
    for perfil in perfis:
        chave, _ = entrada_catalogo(cat, perfil)
        if chave is None:
            print("  ❌ perfil '%s' não resolve entrada nenhuma no catálogo" % perfil)
            falhas += 1
        else:
            resolvem += 1
    print("catálogo: %d/%d perfis detectáveis resolvem entrada" % (resolvem, len(perfis)))
    return 0 if falhas == 0 else 1


# ═════════════════════════════════════════════════════════════════════════ CLI
def flag(argv, nome, default=None):
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def uso(code=64):
    print(__doc__.split("═══ A DIVISÃO")[0].strip(), file=sys.stderr)
    return code


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        return uso(0 if argv else 64)
    if argv[0] == "resolver":
        return cmd_resolver(argv[1:])
    if argv[0] == "candidatos":
        return cmd_candidatos(argv[1:])
    if argv[0] == "autoteste":
        return cmd_autoteste(argv[1:])

    video = argv[0]
    if not os.path.isfile(video):
        print("erro: não encontrado: %s" % video, file=sys.stderr)
        return SAI_ERRO
    altura = flag(argv, "--altura")
    r = detectar(video, int(flag(argv, "--amostras", "24")),
                 "--sem-metadados" in argv, int(altura) if altura else None)
    if r is None:
        print("erro: ffprobe não devolveu stream de vídeo em %s" % video, file=sys.stderr)
        return SAI_ERRO
    if "--json" in argv:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        imprimir(r)
    return codigo_de(r)


if __name__ == "__main__":
    sys.exit(main())
