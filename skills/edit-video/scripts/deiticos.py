#!/usr/bin/env python3
"""deiticos.py — onde o roteiro PEDE apoio visual, lido do texto e não da imagem.

Quando o creator diz "olha isso", "presta atenção", "vou te mostrar", ele está
apontando para alguma coisa. É ali que entra b-roll, cartão, zoom ou split. E é
ali que NENHUM detector de imagem acha nada: a pessoa continua parada falando
para a câmera, o frame anterior é igual ao próximo, o `scdet` e o filtro `scene`
do ffmpeg devolvem zero. O sinal não está na imagem, está no texto — e o texto
nós já temos, palavra a palavra, em toda produção.

Este script é PURO TEXTO. Não abre vídeo, não decodifica áudio, não roda ffmpeg,
não escreve edl.json/janelas.json/captions.json/partitura.json. Ele lê um
transcript.json do Deepgram e devolve JANELAS CANDIDATAS no formato posicional
que o layout-zones.sh já aceita (`ini-fim ini-fim …`).

    deiticos.py <dir-producao-ou-transcript.json>
          [--base montado|bruto]     # default montado (final-transcript/)
          [--por-take]               # com --base bruto: varre todos os take-*/
          [--creator <nome>]         # <creators>/<nome>/lexico-deitico.json
          [--lexico <arquivo.json>]  # mescla por slug, o de fora vence
          [--janela-s N] [--pre-s N] [--max-por-min N] [--classes-off a,b]
          [--janelas]                # só "ini-fim ini-fim …" pro layout-zones.sh
          [--json] [--gravar]

    deiticos.py --frequencia "<regex>" --corpus <dir> [<dir> …]
          # ocorrências, nº de arquivos e 15 contextos. É a ferramenta de
          # extensão do léxico: uma expressão nova entra medida, não achada.

🔴 NÃO É UM PLANEJADOR DE OVERLAYS, e não é QC. Ele responde uma pergunta
estreita — "onde o roteiro pede EXPLICITAMENTE apoio visual?" — e alimenta o
PLANO-EDICAO.md. Zero achados quer dizer "nenhum apoio pedido explicitamente",
não "nenhum overlay nesta peça". Medido: nos 10 brutos da creator-2 (monólogo
frase-na-tela, sem prop) o número certo é ~0, e as produções dela têm 12 grupos
de overlay cada — que nascem de ênfase e de estrutura de roteiro, não de dêixis.

🔴 A JANELA É CANDIDATA, NÃO CORTE. `edit-video/SKILL.md`: o start/end do ASR não
é verdade acústica. Quem acha borda de corte é o bordas.py, no envelope.

Ideia modelada de uma ferramenta de edição de terceiro: helpers/watch_video.py:18-22 (momento dêitico como insumo de decisão
visual) e helpers/pack_transcripts.py:1-14 (view de leitura em nível de frase).
Cópia de leitura em tools/referencias/. Implementação nossa e diferente: léxico
pt-BR medido no corpus deste repo, ancoragem por palavra, antipadrão por token
com guarda de pontuação, e quebra de frase por gap OU pontuação — o Deepgram não
emite as entradas `spacing` que a segmentação por silêncio deles pressupõe. Zero
linha de código portada; o `grab_cues` deles inclusive tem um bug que nós não
herdamos (cue além da duração some em silêncio: watch_video.py:166,178-180).
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import perfil as perfil_mod   # noqa: E402

CONTRATO = "benchmark.deiticos/v1"
CONTRATO_LEXICO = "benchmark.lexico-deitico/v1"

DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))
DIR_REFS = os.environ.get("BENCH_DEITICOS_REFS") or \
    os.path.join(os.path.dirname(DIR_SCRIPT), "references")

# ---------------------------------------------------------------------------
# 🔒 FALLBACK — cada chave tem o NOME FINAL do campo do perfil de peça, para que
# migrar não seja renomear. Quando existe perfil.json na produção, ele manda.
# Nenhum destes é valor de formato (dimensão, fps, sample rate): são parâmetros
# do detector, e mesmo assim vivem no perfil, porque quanto apoio visual uma peça
# pede é propriedade DO TIPO DE PEÇA — screencast pede o tempo todo, reels quase
# nunca.
# ---------------------------------------------------------------------------
FALLBACK = {
    "lexico": "lexico-deitico-pt.json",   # perfil: apoio_visual.lexico
    "janela_s": 2.5,                      # perfil: apoio_visual.janela_s
    "pre_s": 0.15,                        # perfil: apoio_visual.pre_s
    "max_por_min": 2.0,                   # perfil: apoio_visual.max_por_min
    "classes_off": [],                    # perfil: apoio_visual.classes_off
    "antes_nao_k": 3,                     # perfil: apoio_visual.antes_nao_k
}
FALLBACK_GAP_MIN = 0.35                   # perfil: ritmo.gap_min

# derivação fixa, NÃO medição — medir zona é do layout-zones.py, e a SPEC-14 é
# explícita sobre não chutar posição. Isto é só a dica que a partitura consome.
ZONA_DE = {
    "broll": "pleno",           # o b-roll ocupa o quadro (ou a faixa do split)
    "cartao": "lateral",        # é o bloco livre que o layout-zones procura
    "zoom": "pleno",            # punch-in não tem zona, tem enquadramento
    "split": "faixa-legenda",   # a máscara do split-broll cobre ~51% da altura
}
SUGESTOES = tuple(ZONA_DE)
CLASSES = ("ostensivo", "exemplo", "anuncio", "enfase", "projecao", "enumeracao")

FIM_DE_FRASE = ".?!"
PONTUACAO_CORTA = ",.;:!?"
BORDA_CHARS = 10          # "borda" = ≤ 10 caracteres de cada ponta da frase
MIN_PALAVRAS_BORDA = 3    # frase curta não recebe o teste de posição (ruído de ASR)


# ---------------------------------------------------------------------------
# frases() — a unidade de leitura. CÓPIA de
# .claude/skills/transcribe/scripts/timestamped.py (ver o comentário longo lá).
# A skill `transcribe` não pode depender de `edit-video`, então a função existe
# nos dois lugares de propósito. Mudou aqui, mude lá.
# ---------------------------------------------------------------------------
def frases(words, *, gap_min, usar_pontuacao=True):
    """Quebra words[] em gap >= gap_min OU pontuacao final (.?!) OU troca de speaker."""
    grupos, motivos, buf = [], [], []
    for i, w in enumerate(words):
        if buf:
            ant = words[i - 1]
            motivo = None
            if usar_pontuacao:
                pw = (ant.get("punctuated_word") or ant.get("word") or "").rstrip()
                if pw[-1:] and pw[-1:] in FIM_DE_FRASE:
                    motivo = "pontuacao"
            sa, sb = ant.get("speaker"), w.get("speaker")
            if sa is not None and sb is not None and sa != sb:
                motivo = "falante"
            if float(w.get("start") or 0.0) - float(ant.get("end") or 0.0) >= gap_min:
                motivo = "gap"
            if motivo:
                grupos.append(buf)
                motivos.append(motivo)
                buf = []
        buf.append(w)
    if buf:
        grupos.append(buf)
    return grupos, motivos


def normaliza(s):
    """minúsculo, sem acento (NFD + descarte de Mn), pontuação colapsada em espaço.

    É contra ESTE texto que o `padrao` do léxico casa. Escrever acento no padrão
    nunca casa — a regra está escrita dentro do próprio arquivo do léxico.
    """
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


def norm_map(palavras):
    """(texto_normalizado, mapa char->índice da palavra).

    O mapa é o que transforma um match de regex em TIMESTAMP. Sem ele a janela
    vira a frase inteira, e frase de 69,4 s existe no nosso material
    (peca-11/take-A, [349,93-419,32]) — uma janela de 69 s não é candidata
    a nada.
    """
    partes, mapa = [], []
    for i, w in enumerate(palavras):
        t = normaliza(w.get("punctuated_word") or w.get("word") or "")
        if not t:
            continue
        if partes:
            partes.append(" ")
            mapa.append(i)
        partes.append(t)
        mapa.extend([i] * len(t))
    return "".join(partes), mapa


def antipadrao_bate(palavras, iw, tokens, k):
    """Devolve (token, j) se uma das K palavras anteriores é antipadrão.

    🔴 Duas armadilhas medidas, e as duas estão AQUI:

    1. A comparação é POR TOKEN, não por substring. A primeira versão usava
       `(voce|ele|ela|…)\\s*$` sobre a string anterior e o `ele` casou dentro de
       `nele`, matando "…de funil nele, olha isso aqui", que é dêitico legítimo.
    2. Qualquer `,.;:!?` entre o token e o gatilho CANCELA o antipadrão. Sem
       essa guarda o vocativo vira indicativo: "…ia atrás de você, olha, tivemos
       quatro…" é imperativo com vocativo antes, e morria.
    """
    for j in range(iw - 1, max(-1, iw - 1 - k), -1):
        pw = (palavras[j].get("punctuated_word") or palavras[j].get("word") or "").rstrip()
        if pw[-1:] and pw[-1:] in PONTUACAO_CORTA:
            return None
        if normaliza(pw) in tokens:
            return normaliza(pw), j
    return None


# ------------------------------------------------------------------- léxico
def _compila(pad):
    p = dict(pad)
    p["_re"] = re.compile(pad["padrao"])
    p.setdefault("posicao", "qualquer")
    p.setdefault("peso", 1)
    p.setdefault("classe", "ostensivo")
    p.setdefault("sugestao", "broll")
    p.setdefault("antes_nao", [])
    p.setdefault("status", "ativo")
    return p


def carregar_lexico(arquivo, extras=(), creator=None, dir_producao=None):
    """Léxico canônico + merges por slug (o de fora vence).

    Ordem: references/<lexico> → <creators>/<creator>/lexico-deitico.json →
    --lexico <arquivo>. A camada de creator é OPCIONAL e a ausência é SILÊNCIO
    (um cliente do produto tem léxico e não tem creators/).
    """
    base = arquivo if os.path.isabs(arquivo) else os.path.join(DIR_REFS, arquivo)
    if not os.path.isfile(base):
        sys.exit("não achei o léxico: %s" % base)
    with open(base) as fh:
        lex = json.load(fh)
    if lex.get("schema") != CONTRATO_LEXICO:
        sys.exit("léxico com schema inesperado: %r (esperado %s)"
                 % (lex.get("schema"), CONTRATO_LEXICO))
    por_slug = {p["slug"]: p for p in lex.get("padroes", [])}
    fontes = []
    if creator:
        d = perfil_mod.dir_creators(dir_producao)
        cand = os.path.join(d, creator, "lexico-deitico.json") if d else None
        if cand and os.path.isfile(cand):
            fontes.append(cand)
    fontes += list(extras)
    for f in fontes:
        with open(f) as fh:
            outro = json.load(fh)
        for p in outro.get("padroes", []):
            por_slug[p["slug"]] = p
    padroes = [_compila(p) for p in por_slug.values()]
    return lex, padroes, fontes


# ------------------------------------------------------------------- detecção
def achados_da_frase(g, padroes, classes_off, k, base_idx=0):
    """Todos os spans casados numa frase, já com longest-match e antipadrão."""
    texto, mapa = norm_map(g)
    if not texto:
        return [], []
    curtos = len(g) < MIN_PALAVRAS_BORDA
    brutos = []
    for p in padroes:
        if p["status"] != "ativo" or p["classe"] in classes_off:
            continue
        if p["posicao"] != "qualquer" and curtos:
            continue          # amostra mínima: "Olha" em fragmento de 2 palavras é ruído
        for m in p["_re"].finditer(texto):
            if p["posicao"] in ("inicio", "borda") and m.start() <= BORDA_CHARS:
                pass
            elif p["posicao"] in ("fim", "borda") and len(texto) - m.end() <= BORDA_CHARS:
                pass
            elif p["posicao"] == "qualquer":
                pass
            else:
                continue
            brutos.append((m.start(), m.end(), p, m.group(0)))

    # longest-match-wins: `olha só` casa `olha-ostensivo` E `olha-solto`; sem esta
    # guarda o mesmo instante emite dois achados (medido: 88 viram 120 na imersão).
    brutos.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    fica, ocupado = [], []
    for a, b, p, txt in brutos:
        if any(a < y and x < b for x, y in ocupado):
            continue
        ocupado.append((a, b))
        fica.append((a, b, p, txt))
    fica.sort(key=lambda x: x[0])

    achados, mortos = [], []
    for a, _b, p, txt in fica:
        iw = mapa[a]
        anti = antipadrao_bate(g, iw, set(p["antes_nao"]), k)
        w = g[iw]
        if anti:
            tok, j = anti
            trecho = " ".join((x.get("punctuated_word") or x.get("word") or "")
                              for x in g[max(0, j):iw + 1])
            mortos.append({"ini": round(float(w.get("start") or 0.0), 3),
                           "slug": p["slug"], "token": tok, "trecho": trecho})
            continue
        achados.append({"t": float(w.get("start") or 0.0), "pad": p, "gatilho": txt,
                        "frase": [round(float(g[0].get("start") or 0.0), 3),
                                  round(float(g[-1].get("end") or 0.0), 3)],
                        "texto": " ".join((x.get("punctuated_word") or x.get("word") or "")
                                          for x in g).strip(),
                        "i_frase": base_idx})
    return achados, mortos


def funde(janelas):
    """Janelas que se tocam viram uma. Três `isso aqui` em 10 s não são três beats."""
    if not janelas:
        return []
    janelas = sorted(janelas, key=lambda j: (j["ini"], j["fim"]))
    out = [dict(janelas[0])]
    for j in janelas[1:]:
        c = out[-1]
        if j["ini"] <= c["fim"]:
            c["fim"] = max(c["fim"], j["fim"])
            if j["slug"] not in c["slug"].split("+"):
                c["slug"] = c["slug"] + "+" + j["slug"]
            c["gatilho"] = c["gatilho"] + " / " + j["gatilho"]
            if j["peso"] > c["peso"]:
                c["peso"], c["classe"] = j["peso"], j["classe"]
                c["sugestao"], c["dica_zona"] = j["sugestao"], j["dica_zona"]
        else:
            out.append(dict(j))
    return out


def analisar(path, cfg, padroes, rotulo=None):
    with open(path) as fh:
        j = json.load(fh)
    alt = j["results"]["channels"][0]["alternatives"][0]
    words = alt.get("words") or []
    dur = float(j.get("metadata", {}).get("duration") or 0.0)
    if not dur and words:
        dur = float(words[-1].get("end") or 0.0)
    grupos, _ = frases(words, gap_min=cfg["gap_min"])

    achados, mortos = [], []
    for i, g in enumerate(grupos):
        a, m = achados_da_frase(g, padroes, set(cfg["classes_off"]),
                                int(cfg["antes_nao_k"]), base_idx=i)
        achados += a
        mortos += m

    cruas = []
    for a in achados:
        p = a["pad"]
        ini = max(0.0, a["t"] - float(cfg["pre_s"]))
        cruas.append({"ini": round(ini, 3), "fim": round(ini + float(cfg["janela_s"]), 3),
                      "gatilho": a["gatilho"], "slug": p["slug"], "classe": p["classe"],
                      "peso": int(p["peso"]), "sugestao": p["sugestao"],
                      "dica_zona": ZONA_DE.get(p["sugestao"], "pleno"),
                      "frase": a["frase"], "texto": a["texto"], "aparada": False})
    janelas = funde(cruas)

    # teto de densidade: um relatório que acende sempre não é informação. Corta
    # por peso, mas GRAVA o que cortou.
    descartados = []
    limite = int(math.floor(float(cfg["max_por_min"]) * dur / 60.0))
    if janelas and limite < 1:
        limite = 1
    if len(janelas) > limite:
        ordem = sorted(janelas, key=lambda w: (-w["peso"], w["ini"]))
        mantidas = sorted(ordem[:limite], key=lambda w: w["ini"])
        for w in sorted(ordem[limite:], key=lambda w: w["ini"]):
            descartados.append({"ini": w["ini"], "fim": w["fim"], "slug": w["slug"],
                                "motivo": "teto-densidade"})
        janelas = mantidas

    # clamp de duração — é o bug do grab_cues (watch_video.py:166,178-180): lá o
    # cue além do fim SOME em silêncio. Aqui ele é aparado e CONTADO.
    zeradas = []
    for w in janelas:
        if dur and w["fim"] > dur:
            w["fim"] = round(dur, 3)
            w["aparada"] = True
        if w["fim"] - w["ini"] <= 0:
            zeradas.append(w)

    if rotulo:
        for w in janelas:
            w["take"] = rotulo
        for w in descartados:
            w["take"] = rotulo
        for w in mortos:
            w["take"] = rotulo

    return {"janelas": janelas, "descartados": descartados, "antipadrao": mortos,
            "duracao_s": round(dur, 3), "n_frases": len(grupos), "zeradas": zeradas,
            "fonte": path}


# ------------------------------------------------------------------- entrada
def fontes_de(alvo, base, por_take):
    if os.path.isfile(alvo):
        return [(alvo, None)]
    if not os.path.isdir(alvo):
        sys.exit("não achei: %s" % alvo)
    if base == "bruto":
        takes = sorted(glob.glob(os.path.join(alvo, "take-*", "transcript.json")))
        if por_take and takes:
            return [(t, os.path.basename(os.path.dirname(t))) for t in takes]
        p = os.path.join(alvo, "transcript.json")
        if os.path.isfile(p):
            return [(p, None)]
        if takes:
            return [(takes[0], os.path.basename(os.path.dirname(takes[0])))]
        sys.exit("--base bruto: nem %s/transcript.json nem %s/take-*/transcript.json"
                 % (alvo, alvo))
    for cand in ("final-transcript/transcript.json", "transcript.json"):
        p = os.path.join(alvo, cand)
        if os.path.isfile(p):
            return [(p, None)]
    sys.exit("--base montado: não achei %s/final-transcript/transcript.json "
             "(a etapa 5 da edit-video/SKILL.md transcreve o v1 final; use --base bruto "
             "para ler os takes)" % alvo)


def configura(args, dir_perfil):
    p = perfil_mod.carregar(dir_perfil, quieto=True) if dir_perfil else {}
    av = (p.get("apoio_visual") or {}) if isinstance(p, dict) else {}
    origem_av = "perfil:%s" % p.get("nome") if av else "FALLBACK"
    cfg = dict(FALLBACK)
    cfg.update({k: v for k, v in av.items() if k in FALLBACK})
    gap = ((p.get("ritmo") or {}).get("gap_min")) if isinstance(p, dict) else None
    if isinstance(gap, (int, float)) and not isinstance(gap, bool):
        cfg["gap_min"], cfg["origem_gap_min"] = float(gap), "perfil:%s" % p.get("nome")
    else:
        cfg["gap_min"], cfg["origem_gap_min"] = FALLBACK_GAP_MIN, "FALLBACK"
    cfg["origem_apoio_visual"] = origem_av
    if args.janela_s is not None:
        cfg["janela_s"] = args.janela_s
        cfg["origem_apoio_visual"] = "flag"
    if args.pre_s is not None:
        cfg["pre_s"] = args.pre_s
    if args.max_por_min is not None:
        cfg["max_por_min"] = args.max_por_min
    if args.classes_off is not None:
        cfg["classes_off"] = [c for c in args.classes_off.split(",") if c]
    if args.antes_nao_k is not None:
        cfg["antes_nao_k"] = args.antes_nao_k
    return cfg


def relatorio(doc):
    L = []
    r = doc["resumo"]
    L.append("# Momentos dêiticos — %s" % doc["fonte"])
    L.append("base: %s · duração %.1f s · %d frases · léxico %s (%d padrões ativos)"
             % (doc["base"], doc["duracao_s"], doc["medicao"]["n_frases"],
                doc["medicao"]["lexico"], doc["medicao"]["n_padroes"]))
    L.append("gap_min %.2f s (%s) · janela %.2f s · pre %.2f s · teto %.1f/min%s"
             % (doc["medicao"]["gap_min_s"], doc["medicao"]["origem_gap_min"],
                doc["medicao"]["janela_s"], doc["medicao"]["pre_s"],
                doc["medicao"]["max_por_min"],
                (" · classes off: " + ",".join(doc["medicao"]["classes_off"]))
                if doc["medicao"]["classes_off"] else ""))
    L.append("")
    L.append("⚠️ FRONTEIRA CANDIDATA, não ponto de corte. Quem acha borda é o bordas.py.")
    L.append("⚠️ Insumo de decisão, não QC: 0 janelas = 'nenhum apoio PEDIDO', "
             "não 'nenhum overlay'.")
    L.append("")
    if not doc["janelas"]:
        L.append("nenhuma janela (%d achados mortos pelo antipadrão)" % r["n_antipadrao"])
    for w in doc["janelas"]:
        L.append("[%7.2f-%7.2f] %-14s %-11s peso %d → %-6s (%s)%s%s"
                 % (w["ini"], w["fim"], w["slug"], w["classe"], w["peso"],
                    w["sugestao"], w["dica_zona"],
                    "  APARADA" if w.get("aparada") else "",
                    ("  [%s]" % w["take"]) if w.get("take") else ""))
        L.append("            «%s»" % w["gatilho"])
    L.append("")
    L.append("janelas %d · descartados por teto %d · mortos pelo antipadrão %d · "
             "aparadas %d · densidade %.2f/min"
             % (r["n_janelas"], r["n_descartados"], r["n_antipadrao"],
                r["n_aparadas"], r["densidade_por_min"]))
    L.append("")
    L.append("→ layout-zones.sh <v1-sdr.mp4> $(deiticos.py <dir> --janelas)")
    return "\n".join(L)


def frequencia(regex, corpus):
    """A ferramenta de extensão do léxico: uma expressão nova entra MEDIDA.

    Critério (§3.5.2 da SPEC-27): ≥5 ocorrências em ≥3 arquivos distintos, e a
    leitura dos 15 contextos tem que mostrar uso ostensivo em ≥10 deles. Abaixo
    disso a entrada vai para o léxico como `"status": "candidata"` e não conta
    para o veredito.
    """
    rx = re.compile(regex)
    alvos = []
    for d in corpus:
        if os.path.isfile(d):
            alvos.append(d)
        else:
            alvos += glob.glob(os.path.join(d, "**", "transcript.json"), recursive=True)
    alvos = sorted(set(alvos))
    n, arquivos, ctx, palavras = 0, 0, [], 0
    for p in alvos:
        try:
            with open(p) as fh:
                j = json.load(fh)
            ws = j["results"]["channels"][0]["alternatives"][0].get("words") or []
        except (OSError, ValueError, KeyError, IndexError):
            continue
        if not ws:
            continue
        palavras += len(ws)
        t, _ = norm_map(ws)
        k = 0
        for m in rx.finditer(t):
            k += 1
            if len(ctx) < 15:
                ctx.append("%-28s …%s…" % (os.path.basename(os.path.dirname(p)),
                                           t[max(0, m.start() - 30):m.end() + 30]))
        if k:
            arquivos += 1
            n += k
    return {"regex": regex, "ocorrencias": n, "arquivos": arquivos,
            "transcripts_varridos": len(alvos), "palavras_varridas": palavras,
            "contextos": ctx}


def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--base", choices=("montado", "bruto"), default="montado")
    ap.add_argument("--por-take", action="store_true")
    ap.add_argument("--creator")
    ap.add_argument("--lexico", action="append", default=[])
    ap.add_argument("--janela-s", type=float)
    ap.add_argument("--pre-s", type=float)
    ap.add_argument("--max-por-min", type=float)
    ap.add_argument("--antes-nao-k", type=int)
    ap.add_argument("--classes-off")
    ap.add_argument("--janelas", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--frequencia")
    ap.add_argument("--corpus", nargs="*", default=[])
    a = ap.parse_args()

    if a.frequencia:
        r = frequencia(a.frequencia, a.corpus or ["."])
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            print("padrão %r → %d ocorrências em %d de %d transcripts (%d palavras)"
                  % (r["regex"], r["ocorrencias"], r["arquivos"],
                     r["transcripts_varridos"], r["palavras_varridas"]))
            for c in r["contextos"]:
                print("  " + c)
        return 0

    if not a.alvo:
        ap.error("falta o <dir-producao-ou-transcript.json>")

    dir_perfil = a.alvo if os.path.isdir(a.alvo) else os.path.dirname(os.path.abspath(a.alvo))
    cfg = configura(a, dir_perfil)
    lex, padroes, merges = carregar_lexico(cfg["lexico"], a.lexico, a.creator, dir_perfil)
    ativos = [p for p in padroes if p["status"] == "ativo"]

    fontes = fontes_de(a.alvo, a.base, a.por_take)
    partes = [analisar(p, cfg, padroes, rot) for p, rot in fontes]

    janelas = [w for p in partes for w in p["janelas"]]
    descartados = [w for p in partes for w in p["descartados"]]
    mortos = [w for p in partes for w in p["antipadrao"]]
    zeradas = [w for p in partes for w in p["zeradas"]]
    dur = sum(p["duracao_s"] for p in partes)
    n_frases = sum(p["n_frases"] for p in partes)
    n_apar = sum(1 for w in janelas if w.get("aparada"))

    doc = {
        "schema": CONTRATO,
        "gerado_em": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "fonte": partes[0]["fonte"] if len(partes) == 1 else
                 "%d takes em %s" % (len(partes), a.alvo),
        "base": a.base,
        "duracao_s": round(dur, 3),
        "fronteira": "candidata",
        "medicao": {
            "gap_min_s": cfg["gap_min"], "origem_gap_min": cfg["origem_gap_min"],
            "pontuacao": True, "n_frases": n_frases,
            "lexico": os.path.basename(cfg["lexico"]),
            "lexico_versao": lex.get("versao"), "n_padroes": len(ativos),
            "lexico_merges": merges,
            "janela_s": float(cfg["janela_s"]), "pre_s": float(cfg["pre_s"]),
            "max_por_min": float(cfg["max_por_min"]),
            "classes_off": list(cfg["classes_off"]),
            "antes_nao_k": int(cfg["antes_nao_k"]),
            "origem_apoio_visual": cfg["origem_apoio_visual"],
        },
        "janelas": janelas,
        "descartados": descartados,
        "antipadrao": mortos,
        "resumo": {"n_janelas": len(janelas), "n_descartados": len(descartados),
                   "n_antipadrao": len(mortos), "n_aparadas": n_apar,
                   "densidade_por_min": round(len(janelas) / (dur / 60.0), 3) if dur else 0.0},
    }

    if a.janelas:
        if a.base == "bruto":
            print("recusado: as janelas do BRUTO não servem para o layout-zones.sh, que "
                  "roda sobre o v1-sdr.mp4. Rode a etapa 5 (transcribe no v1 final → "
                  "final-transcript/) e chame com --base montado. Não existe mapeamento "
                  "bruto→montado neste repo, de propósito.", file=sys.stderr)
            return 2
        print(" ".join("%.2f-%.2f" % (w["ini"], w["fim"]) for w in janelas))
    elif a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(relatorio(doc))

    if a.gravar:
        alvo_dir = a.alvo if os.path.isdir(a.alvo) else os.path.dirname(os.path.abspath(a.alvo))
        out = os.path.join(alvo_dir, "deiticos.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(out, file=sys.stderr)

    if zeradas:
        print("ERRO: %d janela(s) zeradas pelo clamp (gatilho além da duração de %.2f s). "
              "Isto é o bug do grab_cues do ref-A — aqui ele reprova em vez de sumir."
              % (len(zeradas), dur), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
