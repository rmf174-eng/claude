#!/usr/bin/env python3
"""diretor-legenda.py — transcript + perfil de peça + tema → `partitura.json` (SPEC-14).

A decisão de ONDE APLICAR ÊNFASE TIPOGRÁFICA era 100% manual neste repo: 21
elementos escritos à mão em 1.202 linhas de TSX na `peca-02`, zero
decisões automatizadas, e nenhum QC capaz de perguntar "a palavra certa recebeu
o destaque?". Este script é o artefato que faltava — a PARTITURA, dado
auditável e editável, consumido por um componente imutável.

    captions.json ─┐
    áudio montado  ├→ [1] medir → [2] paginar → [3] pontuar → [4] eleger → [5] serializar
    perfil.json    │                                    │
    tema + léxico ─┘                          partitura.json + PARTITURA.md

O QUE ISTO TEM QUE O DIRETOR DO ref-A NÃO TEM
    Eles decidem por TEXTO: 60 palavras cravadas no script
    (`caption_style.py:25-35`), incluindo nomes de produtos do autor. Nós
    decidimos também por PROSÓDIA MEDIDA — realce, alongamento e pausa saem do
    envelope RMS de 10 ms que já roda em toda montagem. O peso é configuração:
    `--so-texto` desliga o eixo e é exatamente esse par que o critério 1 compara.

O QUE A PARTITURA **NÃO** DECIDE: POSIÇÃO (x/y).
    Posição depende de zona livre medida por janela, luminância do bolso e
    enquadramento — três medições que já têm dono e que erraram caro quando
    foram chutadas. A partitura carrega uma DICA DE ZONA e o resolvedor de
    posição continua sendo o passo seguinte.

🔴 O INVARIANTE: UM CANAL DE TEXTO POR VEZ
    "cada elemento começa só quando o anterior TERMINOU"
    (`references/sistema-ref-C.md:66`, feedback do creator-1) e "um canal de
    texto por vez — legenda ligada só 34,1% do tempo"
    (`intelligence/edicao/ref-C-oferta.md:27`). Dois itens do mesmo canal
    nunca se sobrepõem, e a janela de um `HandText` é a duração da ESCRITA
    (`writeDurationS`), não a da palavra.

    A LEGENDA entra nesse invariante **pela ZONA, não pelo canal** — ver
    `ZONAS_DA_LEGENDA` mais abaixo, onde está a medição que corrige a §3.3 da
    spec. Item que de fato disputa espaço com ela gera uma janela em
    `legenda_off[]`, e essa janela nasce ANCORADA EM FRONTEIRA DE PÁGINA, porque
    quem gerou as páginas foi este script. É a correção estrutural dos dois
    buracos de legenda já entregues (3,9 s e 2,1 s): quem escrevia a janela à
    mão não tinha como saber onde ficavam as fronteiras, porque as páginas
    nasciam dentro do componente React.

CLI
    diretor-legenda.py <dir-producao>
          [--captions <arq>] [--audio <arq>] [--perfil <arq>] [--tema <nome>]
          [--lexico <arq>] [--usuario <n>] [--so-texto] [--densidade N]
          [--forcar] [-o <arq>]
      → stdout: caminho absoluto de partitura.json
      → stderr: tabela de eleição
    diretor-legenda.py validar <partitura.json> [--paginas]
    diretor-legenda.py md      <partitura.json>
"""
import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import prosodia  # noqa: E402

CONTRATO = "benchmark.partitura/v1"
DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))
DIR_REFS = os.path.join(os.path.dirname(DIR_SCRIPT), "references")

# —————————————————————————————————————————————————————————— produto, não instalação
# Nenhum caminho absoluto, nenhum diretório obrigatório. Um cliente do produto
# tem perfil e tema; não tem `creators/`, não tem `estilos/`, não tem `data/`.


def dir_remotion() -> str | None:
    """$BENCH_REMOTION_DIR → o `tools/remotion-compositor` do ancestral que o tem.
    `None` = pular.

    Env primeiro, e nunca absoluto no fonte. A busca é por MARCADOR e não por
    nível contado: o `../../..` que estava aqui resolvia para `ilha/` na nossa
    árvore e para `<raiz>/.claude/` na instalação do cliente, onde não há
    `tools/` — e como a ausência vira `None`, que significa "pular", o defeito
    saía SEM ERRO NENHUM. É a mesma família do achado do `detect-cor.py`
    (2026-08-12), com o agravante do silêncio.
    """
    env = os.environ.get("BENCH_REMOTION_DIR")
    if env:
        return env if os.path.isdir(env) else None
    d = DIR_SCRIPT
    while True:
        cand = os.path.join(d, "tools", "remotion-compositor")
        if os.path.isdir(cand):
            return cand
        if d == os.path.dirname(d):
            return None
        d = os.path.dirname(d)


def lexico_do_usuario(usuario: str | None, dir_producao: str | None,
                      explicito: str | None = None) -> tuple[dict, str | None]:
    """O vocabulário de marca do creator. ORDEM FIXA, e a ausência é SILÊNCIO.

        1. --lexico (explícito)
        2. $BENCH_LEXICO
        3. <estilos>/<usuario>/_lexico.json     (SPEC-24 — pode não existir ainda)
        4. <creators>/<usuario>/lexico-creator.json
        5. léxico vazio embutido

    🔴 O léxico é MECANISMO DE PRODUTO instanciado por nós. Se ele só existisse
    em `creators/`, a feature seria inalcançável para um cliente — que não tem
    esse diretório. Por isso a cadeia começa em variável de ambiente e termina
    num dicionário vazio, e NENHUM degrau ausente imprime aviso.
    """
    vazio = {"marca": [], "evitar": []}
    for cand in _candidatos_lexico(usuario, dir_producao, explicito):
        if cand and os.path.isfile(cand):
            d = json.load(open(cand))
            return {"marca": d.get("marca", []), "evitar": d.get("evitar", [])}, cand
    return vazio, None


def _candidatos_lexico(usuario, dir_producao, explicito):
    yield explicito
    yield os.environ.get("BENCH_LEXICO")
    if not usuario:
        return
    est = os.environ.get("BENCH_ESTILOS_DIR") or _subindo("estilos", dir_producao)
    if est:
        yield os.path.join(est, usuario, "_lexico.json")
    cre = os.environ.get("BENCH_CREATORS_DIR") or _subindo("creators", dir_producao)
    if cre:
        yield os.path.join(cre, usuario, "lexico-creator.json")


def _subindo(nome: str, base: str | None) -> str | None:
    """Procura `nome/` a partir de `base` (ou do cwd) subindo até a raiz."""
    d = os.path.abspath(base or ".")
    if os.path.isfile(d):
        d = os.path.dirname(d)
    while True:
        cand = os.path.join(d, nome)
        if os.path.isdir(cand):
            return cand
        pai = os.path.dirname(d)
        if pai == d:
            return None
        d = pai


def usuario_do_caminho(dir_producao: str) -> str | None:
    """`<qualquer>/creators/<n>/producao/<slug>` → `<n>`. Fora disso, `None`."""
    partes = os.path.abspath(dir_producao).split(os.sep)
    if "creators" in partes:
        i = partes.index("creators")
        if i + 1 < len(partes):
            return partes[i + 1]
    return None


# ————————————————————————————————————————————————————————————— normalização
def norma(s: str) -> str:
    """minúscula, sem acento, sem pontuação. É a chave de todo léxico."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum() or c in "$%.,")


def so_letras(s: str) -> str:
    return "".join(c for c in norma(s) if c.isalnum())


# ═══════════════════════════════════════════════════ PASSO 2 — paginar
#
# 🔁 PORT LINHA A LINHA de `tools/remotion-compositor/src/texto/agrupar.ts`
# (SPEC-13). Não é reimplementação livre: o critério 11 exige que as fronteiras
# da partitura e as do `CaptionLayer` batam em 0 ms, e a única forma de provar
# isso sem render é rodar os dois algoritmos sobre a mesma tabela de larguras e
# comparar. O gate `--paginas` faz exatamente isso.
#
# A tabela de advance widths (`src/data/larguras/*.json`) é a MESMA que o
# `medidorDeTabela` do TS usa. O que ela não faz — kerning, ligadura, shaping —
# não faz nos dois lados, então a divergência é zero por construção.

PONTUACAO = re.compile(r"[.,!?…;:][\"'”’)]*$")


def medidor_de_tabela(tab: dict):
    k = tab.get("correcao") or 1
    fallback = tab["fallback"]
    upem = tab["unitsPerEm"]
    adv = tab["advance"]

    def medir(texto: str, m: dict) -> float:
        t = texto.upper() if m.get("caixa") == "uppercase" else texto
        unidades = 0.0
        n = 0
        for ch in t:
            unidades += adv.get(str(ord(ch)), fallback)
            n += 1
        return ((unidades / upem) * m["tamanho"] + (m.get("entreletras") or 0) * n) * k

    return medir


def carrega_tabela(medida: dict) -> dict:
    base = dir_remotion()
    if not base:
        raise SystemExit("diretor: não achei tools/remotion-compositor (BENCH_REMOTION_DIR)")
    nome = "%s-%s%s.json" % (medida["familia"], medida.get("peso") or 400,
                             "-italic" if medida.get("italico") else "")
    arq = os.path.join(base, "src", "data", "larguras", nome)
    if not os.path.isfile(arq):
        raise SystemExit(
            f"diretor: sem tabela de larguras {nome}. "
            f"Rode tools/remotion-compositor/scripts/largura-fonte.py.")
    return json.load(open(arq))


def agrupamento_do_perfil(p: dict, largura_canvas: float) -> dict | None:
    """Espelho de `agrupar.ts:agrupamentoDoPerfil`."""
    leg = p.get("legenda") or {}
    ag = leg.get("agrupamento")
    if not leg or not ag:
        return None
    est = leg.get("estilo")
    if not est:
        raise SystemExit("perfil com legenda.agrupamento mas sem legenda.estilo")
    if ag.get("min_solo_ms") is None:
        raise SystemExit("legenda.agrupamento.min_solo_ms está null (SPEC-13)")
    return {
        "medida": {
            "familia": est["familia"], "peso": est.get("peso"),
            "italico": est.get("italico"),
            "tamanho": est["tamanho_pct"] * largura_canvas,
            "entreletras": (est.get("entreletras_pct") or 0) * largura_canvas,
            "caixa": est.get("caixa"),
        },
        "larguraMaxPx": ag["largura_max_pct"] * largura_canvas,
        "linhasMax": ag["linhas_max"],
        "maxPalavras": leg.get("max_palavras_pagina", 6),
        "pausaQuebraMs": ag["pausa_quebra_ms"],
        "quebraEmPontuacao": ag["quebra_em_pontuacao"],
        "minSoloMs": ag["min_solo_ms"],
        "penalidadeOrfaPx": ag["penalidade_orfa_px"],
        "orfas": ag["orfas"],
    }


# a ponte anti-piscada mora em `CaptionLayer.tsx`; `agrupar.ts` guarda uma cópia
# e tem gate de espelho. Aqui é a TERCEIRA cópia, e por isso `validar --paginas`
# relê os dois arquivos TS e reprova se divergirem.
PONTE_MS = 500
CAUDA_MS = 280


def _texto(tokens):
    return "".join(t["text"] for t in tokens)


def _fim(tokens):
    return max(t["toMs"] for t in tokens)


def duracao_efetiva(paginas, i, fim_ms=float("inf")):
    p = paginas[i]
    prox = paginas[i + 1] if i + 1 < len(paginas) else None
    ultimo = _fim(p["tokens"])
    if prox and prox["startMs"] - ultimo < PONTE_MS:
        fim = prox["startMs"]
    else:
        fim = min(ultimo + CAUDA_MS, fim_ms)
    return fim - p["startMs"]


def melhor_quebra(itens, larg, penalidade_orfa, orfas):
    orfas_set = {so_letras(o) for o in orfas}
    melhor, custo_min = 1, float("inf")
    for i in range(1, len(itens)):
        cima, baixo = itens[:i], itens[i:]
        ultima = so_letras(cima[-1]["text"])
        custo = abs(larg(cima) - larg(baixo)) + (penalidade_orfa if ultima in orfas_set else 0)
        if custo < custo_min:
            custo_min, melhor = custo, i
    return melhor


def monta_linhas(tokens, a, medir):
    if a["linhasMax"] < 2 or len(tokens) < 2:
        return [tokens]
    corte = melhor_quebra(tokens, lambda xs: medir(_texto(xs).lstrip(), a["medida"]),
                          a["penalidadeOrfaPx"], a["orfas"])
    cima, baixo = tokens[:corte], list(tokens[corte:])
    baixo[0] = {**baixo[0], "text": baixo[0]["text"].lstrip()}
    return [cima, baixo]


def agrupar(captions, a, medir, fim_ms=float("inf"), rebalancear=True):
    """Espelho de `agrupar.ts:agruparComRelatorio`, mais o passe de REBALANCEAMENTO.

    🔴 O PASSE NOVO, E POR QUE ELE É DESTA SPEC E NÃO DA 13.
    A SPEC-13 entregou o agrupamento por largura e deixou 5 páginas de 1 token
    com duração efetiva abaixo do piso, registradas em `avisos[]`. Ela não podia
    resolvê-las: a única ferramenta dela era FUNDIR a página inteira com a
    vizinha, e as vizinhas estavam em 885–921 px de um orçamento de 900 — fundir
    estouraria a largura, que é exatamente o defeito que ela conserta.

    O diretor tem uma ferramenta a mais: MOVER A FRONTEIRA. Em vez de fundir as
    duas páginas, doa-se a palavra da ponta da vizinha para a página curta. A
    página curta começa antes (ou termina depois) e passa do piso; a vizinha
    perde uma palavra e continua dentro do orçamento. Nenhuma das duas estoura.

    Guardas, todos necessários e todos medidos contra o mesmo material:
      • nunca atravessar PAUSA REAL (a fronteira existe porque houve silêncio);
      • a doadora não pode ficar vazia nem virar solo curto;
      • as duas têm que caber no orçamento DEPOIS da doação;
      • a receptora respeita `maxPalavras`.
    """
    orcamento = a["larguraMaxPx"] * a["linhasMax"]
    itens = [c for c in captions if c["text"].strip() != ""]

    def cabe(tokens):
        if medir(_texto(tokens), a["medida"]) > orcamento:
            return False
        if a["linhasMax"] < 2 or len(tokens) < 2:
            return True
        return all(medir(_texto(ln).lstrip(), a["medida"]) <= a["larguraMaxPx"]
                   for ln in monta_linhas(tokens, a, medir))

    fechamentos = {"largura": 0, "palavras": 0, "semantica": 0, "fim": 0}
    avisos = []
    cruas = []
    atual = []

    def fecha(motivo):
        nonlocal atual
        if not atual:
            return
        cruas.append({"tokens": atual, "motivo": motivo})
        fechamentos[motivo] += 1
        atual = []

    def como_primeiro(t):
        return {**t, "text": t["text"].lstrip()}

    for i, c in enumerate(itens):
        tk = {"text": c["text"], "fromMs": c["startMs"], "toMs": c["endMs"]}
        if atual:
            tentativa = atual + [tk]
            excede_l = not cabe(tentativa)
            excede_p = len(tentativa) > a["maxPalavras"]
            if excede_l or excede_p:
                fecha("largura" if excede_l else "palavras")
                atual = [como_primeiro(tk)]
            else:
                atual = tentativa
        else:
            atual = [como_primeiro(tk)]
        prox = itens[i + 1] if i + 1 < len(itens) else None
        gap = (prox["startMs"] - c["endMs"]) if prox else float("inf")
        pontua = a["quebraEmPontuacao"] and bool(PONTUACAO.search(c["text"].rstrip()))
        if prox and (pontua or gap > a["pausaQuebraMs"]):
            fecha("semantica")
    fecha("fim")

    fundidas = {"tras": 0, "frente": 0}
    com_espaco = lambda t: t if t["text"].startswith(" ") else {**t, "text": " " + t["text"]}  # noqa: E731
    sem_espaco = lambda t: {**t, "text": t["text"].lstrip()}                                    # noqa: E731

    def pausa_real(i):
        return i + 1 < len(cruas) and \
            cruas[i + 1]["tokens"][0]["fromMs"] - _fim(cruas[i]["tokens"]) > a["pausaQuebraMs"]

    def com_start(cs):
        return [{"startMs": c["tokens"][0]["fromMs"], "tokens": c["tokens"]} for c in cs]

    def solo_curto(i, cs):
        if len(cs[i]["tokens"]) != 1:
            return False
        return duracao_efetiva(com_start(cs), i, fim_ms) < a["minSoloMs"]

    mudou = True
    while mudou:
        mudou = False
        for i in range(len(cruas)):
            if not solo_curto(i, cruas):
                continue
            solo = cruas[i]["tokens"][0]
            tras = cruas[i - 1] if i > 0 and not pausa_real(i - 1) else None
            if tras and cabe(tras["tokens"] + [com_espaco(solo)]):
                tras["tokens"] = tras["tokens"] + [com_espaco(solo)]
                cruas.pop(i)
                fundidas["tras"] += 1
                mudou = True
                break
            frente = cruas[i + 1] if i + 1 < len(cruas) and not pausa_real(i) else None
            if frente and cabe([sem_espaco(solo)] + [com_espaco(t) for t in frente["tokens"]]):
                frente["tokens"] = [sem_espaco(solo)] + [com_espaco(t) for t in frente["tokens"]]
                cruas.pop(i)
                fundidas["frente"] += 1
                mudou = True
                break

    # ————————————————————————————— o passe NOVO: mover a fronteira (SPEC-14)
    movidas = {"tras": 0, "frente": 0}
    if rebalancear:
        mudou = True
        while mudou:
            mudou = False
            for i in range(len(cruas)):
                if not solo_curto(i, cruas):
                    continue
                if _doar_de_tras(cruas, i, a, medir, cabe, pausa_real, com_start, fim_ms):
                    movidas["tras"] += 1
                    mudou = True
                    break
                if _doar_da_frente(cruas, i, a, medir, cabe, pausa_real, com_start, fim_ms):
                    movidas["frente"] += 1
                    mudou = True
                    break

    for i in range(len(cruas)):
        if solo_curto(i, cruas):
            avisos.append({
                "tipo": "solo-nao-fundido",
                "startMs": cruas[i]["tokens"][0]["fromMs"],
                "texto": cruas[i]["tokens"][0]["text"].strip(),
                "detalhe": "duração efetiva %dms < min_solo %dms; nem fusão nem doação couberam"
                           % (duracao_efetiva(com_start(cruas), i, fim_ms), a["minSoloMs"]),
            })

    paginas = []
    for c in cruas:
        paginas.append({
            "text": _texto(c["tokens"]).lstrip(),
            "startMs": c["tokens"][0]["fromMs"],
            "durationMs": 0,
            "tokens": c["tokens"],
            "linhas": monta_linhas(c["tokens"], a, medir),
            "motivo": c["motivo"],
        })
    for i, pg in enumerate(paginas):
        pg["durationMs"] = duracao_efetiva(paginas, i, fim_ms)
        pg["larguraEstimada"] = round(medir(_texto(pg["tokens"]), a["medida"]))
        for ln in pg["linhas"]:
            w = medir(_texto(ln).lstrip(), a["medida"])
            if w > a["larguraMaxPx"]:
                avisos.append({"tipo": "linha-estourada", "startMs": pg["startMs"],
                               "texto": _texto(ln).strip(),
                               "detalhe": "%dpx > %dpx" % (round(w), round(a["larguraMaxPx"]))})
    return {"paginas": paginas, "avisos": avisos, "fechamentos": fechamentos,
            "fundidas": fundidas, "movidas": movidas}


def _doar_de_tras(cruas, i, a, medir, cabe, pausa_real, com_start, fim_ms):
    """A página anterior doa palavras do FIM para a página curta `i`."""
    if i == 0 or pausa_real(i - 1):
        return False
    doadora, receptora = cruas[i - 1], cruas[i]
    for n in range(1, len(doadora["tokens"])):
        movidos = doadora["tokens"][-n:]
        resto = doadora["tokens"][:-n]
        novos_rec = [{**movidos[0], "text": movidos[0]["text"].lstrip()}] + \
                    [{**t, "text": t["text"] if t["text"].startswith(" ") else " " + t["text"]}
                     for t in movidos[1:] + receptora["tokens"]]
        if len(novos_rec) > a["maxPalavras"] or not cabe(novos_rec) or not cabe(resto):
            continue
        teste = [dict(c) for c in cruas]
        teste[i - 1] = {**doadora, "tokens": resto}
        teste[i] = {**receptora, "tokens": novos_rec}
        if _piso_ok(teste, i - 1, a, com_start, fim_ms) and _piso_ok(teste, i, a, com_start, fim_ms):
            cruas[i - 1] = teste[i - 1]
            cruas[i] = teste[i]
            return True
    return False


def _doar_da_frente(cruas, i, a, medir, cabe, pausa_real, com_start, fim_ms):
    """A próxima página doa palavras do COMEÇO para a página curta `i`."""
    if i + 1 >= len(cruas) or pausa_real(i):
        return False
    receptora, doadora = cruas[i], cruas[i + 1]
    for n in range(1, len(doadora["tokens"])):
        movidos = doadora["tokens"][:n]
        resto = list(doadora["tokens"][n:])
        resto[0] = {**resto[0], "text": resto[0]["text"].lstrip()}
        novos_rec = receptora["tokens"] + \
            [{**t, "text": t["text"] if t["text"].startswith(" ") else " " + t["text"]}
             for t in movidos]
        if len(novos_rec) > a["maxPalavras"] or not cabe(novos_rec) or not cabe(resto):
            continue
        teste = [dict(c) for c in cruas]
        teste[i] = {**receptora, "tokens": novos_rec}
        teste[i + 1] = {**doadora, "tokens": resto}
        if _piso_ok(teste, i, a, com_start, fim_ms) and _piso_ok(teste, i + 1, a, com_start, fim_ms):
            cruas[i] = teste[i]
            cruas[i + 1] = teste[i + 1]
            return True
    return False


def _piso_ok(cs, i, a, com_start, fim_ms):
    """A página `i` de `cs` respeita o piso de solo? (só solo tem piso)"""
    if len(cs[i]["tokens"]) != 1:
        return True
    return duracao_efetiva(com_start(cs), i, fim_ms) >= a["minSoloMs"]


# ═══════════════════════════════════════════════════ PASSO 3 — pontuar
def _clamp01(x):
    return max(0.0, min(1.0, x))


def classe_lexica(palavra: str, lex: dict) -> str:
    p = norma(palavra).strip(".,")
    letras = so_letras(palavra)
    if re.match(lex["regex_numero"], p):
        return "numero"
    if letras in lex["_neg"]:
        return "negacao"
    if letras in lex["_enumeracao"]:
        return "enumeracao"
    if letras in lex["_contraste"]:
        return "contraste"
    if letras in lex["_stop"]:
        return "stop"
    return "conteudo"


PESO_LEXICO = {"conteudo": 1.0, "numero": 1.0, "negacao": 0.8,
               "enumeracao": 0.8, "contraste": 0.6, "stop": 0.0}


def pontuar(tab_prosodia, palavras, lex, cfg, modo_texto=False):
    """Score em [0,1] por palavra: soma ponderada de 4 eixos. Pesos vêm do perfil."""
    ref = cfg["prosodia_ref"]
    pesos = cfg["pesos"]

    # repetição: conta ocorrências de palavra de conteúdo na peça inteira
    ocorr = {}
    for w in palavras:
        k = so_letras(w["text"])
        if k and classe_lexica(w["text"], lex) != "stop":
            ocorr[k] = ocorr.get(k, 0) + 1

    # posição: última palavra de CONTEÚDO da frase carrega o núcleo prosódico do pt
    ult_conteudo, primeira = {}, {}
    for r in tab_prosodia:
        f = r["frase"]
        primeira.setdefault(f, r["idx"])
        if classe_lexica(r["text"], lex) != "stop":
            ult_conteudo[f] = r["idx"]

    marca = {so_letras(x) for x in lex.get("_marca", [])}
    evitar = {so_letras(x) for x in lex.get("_evitar", [])}

    saida = []
    for r in tab_prosodia:
        cls = classe_lexica(r["text"], lex)
        if modo_texto:
            e_pros = 0.0
        else:
            e_pros = (
                0.5 * _clamp01(r["realce_db"] / ref["realce_db"])
                + 0.3 * _clamp01((r["alongamento"] - 1.0) / max(1e-9, ref["alongamento"] - 1.0))
                + 0.2 * _clamp01((r["pausa_depois_ms"] or 0) / ref["pausa_ms"])
            )
        e_lex = PESO_LEXICO[cls]
        if r["idx"] == ult_conteudo.get(r["frase"]):
            e_pos = 1.0
        elif r["idx"] == primeira.get(r["frase"]):
            e_pos = 0.6
        else:
            e_pos = 0.2
        n = ocorr.get(so_letras(r["text"]), 0)
        e_rep = min(1.0, (n - 1) / 3.0) if n > 1 else 0.0

        eixos = {"prosodia": round(pesos["prosodia"] * e_pros, 4),
                 "lexico": round(pesos["lexico"] * e_lex, 4),
                 "posicao": round(pesos["posicao"] * e_pos, 4),
                 "repeticao": round(pesos["repeticao"] * e_rep, 4)}
        score = sum(eixos.values())
        k = so_letras(r["text"])
        if k in marca:
            score *= (1 + cfg["bonus_creator"])
        if k in evitar:
            score *= (1 - cfg["bonus_creator"])
        saida.append({**r, "classe": cls, "eixos": eixos, "score": round(min(1.0, score), 4)})
    return saida


# ═══════════════════════════════════════════════════ PASSO 4 — eleger
#
# O canal de um item é propriedade do COMPONENTE (o que ele desenha na tela),
# não da peça — por isso a tabela mora aqui e não no perfil. Componente
# desconhecido cai em `texto`, que é o canal mais restritivo: errar para o lado
# de bloquear é o único erro barato aqui.
CANAL_POR_COMPONENTE = {
    "HandText": "texto", "SwapText": "texto", "AccentWord": "texto",
    "StepTitleFlat": "texto", "StepTitle": "texto", "Palavra": "texto",
    "MarkerHighlight": "marca",
    "PostItCard": "cartao", "StampSticker": "cartao",
}
# componentes que ESCREVEM: a janela deles é a duração da escrita
# (`writeDurationS`), não a da palavra.
ESCREVE = {"HandText", "SwapText", "StepTitleFlat", "StepTitle", "Palavra", "AccentWord"}

# 🔴 ONDE A LEGENDA MORA. Só item que cai NESTAS zonas disputa espaço com ela.
#
# MEDIDO, e é uma correção da premissa da spec. A §3.3 diz "a legenda conta como
# ocupação do canal `texto`", o que lido ao pé da letra faz TODO item de texto
# desligar a legenda. Implementado assim, o diretor produziu na `peca-02`
# uma janela de 17,3 s sem legenda — o defeito que esta spec existe para
# consertar, pela porta nova.
#
# As duas produções aprovadas dizem o contrário, e dizem o mesmo:
#   peca-02.tsx:1165-1172       `CAPTION_OFF: [] ` — "a supressão nem se
#                              justifica: o cartão está na faixa y372–800 e a
#                              legenda em y~1400, não há colisão geométrica"
#   MaeDoMarido.tsx:901-909    `CAPTION_OFF: [] ` — "O que precisava mudar era a
#                              GEOMETRIA: a seta descia até y1468 e batia na
#                              legenda (y1413–1464). Subi o bloco."
#
# É a regra que a §9 já enunciava sem tirar a consequência: "se a fronteira não
# couber, o certo é MOVER O ELEMENTO GRÁFICO, não apagar mais legenda". Então a
# ocupação é por ZONA: elemento em `topo`/`lateral` convive com a legenda;
# elemento em `faixa-legenda`/`pleno` não, e só esse desliga.
ZONAS_DA_LEGENDA = {"faixa-legenda", "pleno"}


def canal_de(componente: str) -> str:
    base = componente.split(":")[0]
    if base == "DrawStroke":
        return "traco"
    return CANAL_POR_COMPONENTE.get(base, "texto")


def papel_de(r, lex, frase_tem_ponto):
    cls = r["classe"]
    if cls == "numero":
        return "numero"
    if cls == "negacao":
        return "negacao"
    if cls == "enumeracao":
        return "enumeracao"
    if cls == "contraste":
        return "contraste"
    if r.get("_tese") and frase_tem_ponto:
        return "tese"
    return "destaque"


def eleger(pontuadas, paginas, frases_txt, cfg, perfil, orcamento, travados, duracao_s,
           medir=None, medida=None):
    fps = perfil["video"]["fps"]
    fpc = cfg["fpc_manuscrito"]
    min_solo_s = cfg["min_solo_ms"] / 1000.0
    max_chars = cfg["max_chars_manuscrito"]
    p2c = cfg["papel_para_componente"]
    cor = cfg["cor_por_papel"]
    zona = cfg["zona_por_papel"]
    sfx = cfg["sfx_por_papel"]

    # marca a maior score de cada frase (candidata a `tese`)
    melhor_da_frase = {}
    for r in pontuadas:
        f = r["frase"]
        if f not in melhor_da_frase or r["score"] > melhor_da_frase[f]["score"]:
            melhor_da_frase[f] = r
    for r in melhor_da_frase.values():
        r["_tese"] = True

    def monta(r):
        frase_txt, tem_ponto = frases_txt[r["frase"]]
        papel = papel_de(r, None, tem_ponto)
        comp = p2c.get(papel, "HandText")
        canal = canal_de(comp)
        texto = frase_txt if papel == "tese" else r["text"].strip(" .,!?;:")
        in_s = r["startMs"] / 1000.0
        if comp.split(":")[0] in ESCREVE:
            dur = prosodia.write_duration_s(texto, fpc, fps)
        else:
            dur = (r["endMs"] - r["startMs"]) / 1000.0
        out_s = round(in_s + max(dur, 1.0 / fps), 3)
        z = zona.get(papel, "topo")
        # largura do texto EM PX na tipografia da legenda, pela mesma tabela de
        # advance widths do agrupamento. Não é posição — é o TAMANHO do elemento,
        # e sem ele o consumidor desenha um traço do tamanho da zona inteira
        # (uma "elipse" de 929×115 px vira uma reta, visto no still).
        larg_px = round(medir(texto, medida)) if (medir and medida) else None
        return {
            "id": "%03d-%s" % (r["idx"], so_letras(r["text"]) or "x"),
            "papel": papel, "componente": comp, "canal": canal,
            "texto": texto,
            "parafrasear": bool(papel == "tese" and len(texto) > max_chars),
            "palavra": {"text": r["text"], "idx": r["idx"],
                        "fromMs": r["startMs"], "toMs": r["endMs"]},
            "inS": round(in_s, 3), "outS": out_s,
            "zona": z, "larguraEstimadaPx": larg_px, "cor": cor.get(papel, "ink"),
            "sfx": sfx.get(papel),
            "suprime_legenda": canal == "texto" and z in ZONAS_DA_LEGENDA,
            "score": r["score"],
            "por_que": {**r["eixos"],
                        "medido": {"realce_db": r["realce_db"],
                                   "alongamento": r["alongamento"],
                                   "pausa_depois_ms": r["pausa_depois_ms"],
                                   "piso_local_db": r["piso_local_db"]}},
            "travado": False,
        }

    eleitos, descartados = [], []
    ocupado = {}

    def colide(it):
        for j in ocupado.get(it["canal"], []):
            if it["inS"] < j["outS"] and it["outS"] > j["inS"]:
                return True
        return False

    def registra(it):
        ocupado.setdefault(it["canal"], []).append(it)
        eleitos.append(it)

    # 1) os TRAVADOS entram primeiro, byte a byte, e o orçamento é gasto ao redor
    for it in travados:
        if colide(it):
            descartados.append({"id": it["id"], "score": it.get("score", 1.0),
                                "motivo": "travado-colide", "medido": {}})
            continue
        registra(it)

    ids_travados = {it["id"] for it in eleitos}
    ordem = sorted(pontuadas, key=lambda r: (-r["score"], r["idx"]))
    # depois que o orçamento fecha, os próximos `SOBRAS` candidatos ainda entram
    # em `descartados[]` com motivo `orcamento`. Sem isso a pergunta que a
    # partitura existe para responder — "por que essa palavra e não aquela?" —
    # fica sem resposta justamente para quem ficou logo abaixo da linha de corte.
    SOBRAS = 10
    sobrando = 0
    for r in ordem:
        if len(eleitos) >= orcamento:
            if sobrando >= SOBRAS or r["classe"] == "stop":
                continue
            sobrando += 1
            descartados.append({"id": "%03d-%s" % (r["idx"], so_letras(r["text"]) or "x"),
                                "score": r["score"], "motivo": "orcamento",
                                "medido": {"realce_db": r["realce_db"],
                                           "alongamento": r["alongamento"]}})
            continue
        it = monta(r)
        if it["id"] in ids_travados:
            continue
        medido = {"realce_db": r["realce_db"], "alongamento": r["alongamento"]}
        if r["classe"] == "stop" and it["papel"] == "destaque":
            descartados.append({"id": it["id"], "score": r["score"],
                                "motivo": "conectivo", "medido": medido})
            continue
        if colide(it):
            descartados.append({"id": it["id"], "score": r["score"],
                                "motivo": "colisao-canal", "medido": medido})
            continue
        dur_palavra = (r["endMs"] - r["startMs"]) / 1000.0
        if it["componente"].split(":")[0] in ESCREVE and it["papel"] != "tese" \
                and dur_palavra < min_solo_s:
            descartados.append({"id": it["id"], "score": r["score"],
                                "motivo": "curta-demais", "medido": medido})
            continue
        if eleitos and min(abs(it["inS"] - j["inS"]) for j in eleitos) < cfg["espacamento_min_s"]:
            descartados.append({"id": it["id"], "score": r["score"],
                                "motivo": "espacamento", "medido": medido})
            continue
        # a janela não pode passar do fim da peça: um HandText que começa a
        # escrever a 1,2 s do fim promete uma escrita que a timeline não tem.
        if it["outS"] > duracao_s:
            descartados.append({"id": it["id"], "score": r["score"],
                                "motivo": "nao-cabe-no-fim", "medido": medido})
            continue
        registra(it)

    eleitos.sort(key=lambda x: x["inS"])
    descartados.sort(key=lambda x: -x["score"])
    return eleitos, descartados


# ═════════════════════════════ legenda_off ancorado em fronteira de página
def legenda_off(eleitos, paginas):
    """Uma janela por item de canal `texto`, SNAPADA na fronteira de página.

    🔴 A janela vai de `startMs` da PRIMEIRA página que o item intersecta até o
    `toMs` da ÚLTIMA — nem um ms além. A regra de supressão do `CaptionLayer`
    é INTERSEÇÃO (`ini < b && fim > a`); com as bordas exatamente nesses dois
    valores, a página anterior (que termina em `a`) e a seguinte (que começa em
    `b`) não são pegas, porque as duas comparações são estritas.

    Ampliar "para garantir" é como nasceram os dois buracos de 3,9 s e 2,1 s.
    """
    janelas = []
    for it in eleitos:
        if not it.get("suprime_legenda"):
            continue
        a_ms, b_ms = it["inS"] * 1000, it["outS"] * 1000
        atinge = [i for i, p in enumerate(paginas)
                  if p["startMs"] < b_ms and _fim(p["tokens"]) > a_ms]
        if not atinge:
            continue
        ini = paginas[atinge[0]]["startMs"] / 1000.0
        fim = _fim(paginas[atinge[-1]]["tokens"]) / 1000.0
        janelas.append({"ini": round(ini, 3), "fim": round(fim, 3),
                        "por": it["id"], "paginas": atinge})
    janelas.sort(key=lambda j: j["ini"])
    # fundir janelas que se tocam (duas ocupações consecutivas do mesmo canal)
    fundidas = []
    for j in janelas:
        if fundidas and j["ini"] <= fundidas[-1]["fim"]:
            u = fundidas[-1]
            u["fim"] = max(u["fim"], j["fim"])
            u["por"] += "+" + j["por"]
            u["paginas"] = sorted(set(u["paginas"]) | set(j["paginas"]))
        else:
            fundidas.append(dict(j))
    return fundidas


def aparar_por_fracao(eleitos, descartados, paginas, duracao_s, alvo):
    """`fracao_legenda_alvo` é RESTRIÇÃO, não decoração.

    O perfil declara quanto tempo a legenda tem que ficar no ar (reels 1,0 —
    a legenda nunca sai; vsl 0,34 — medido no vídeo de oferta da ref-C).
    Se a eleição desligar mais do que isso, o item de MENOR score que suprime é
    descartado, e assim por diante, até caber. Sem este passe, o número está no
    perfil e não decide nada — que é o pior tipo de configuração.
    """
    while True:
        off = legenda_off(eleitos, paginas)
        no_ar = duracao_s - sum(j["fim"] - j["ini"] for j in off)
        frac = no_ar / duracao_s if duracao_s else 1.0
        if frac >= alvo - 1e-9:
            return eleitos, descartados, off, round(frac, 4)
        candidatos = [it for it in eleitos if it.get("suprime_legenda")]
        if not candidatos:
            return eleitos, descartados, off, round(frac, 4)
        pior = min(candidatos, key=lambda x: x["score"])
        eleitos = [x for x in eleitos if x is not pior]
        descartados.insert(0, {"id": pior["id"], "score": pior["score"],
                               "motivo": "fracao-legenda",
                               "medido": {"fracao_medida": round(frac, 4),
                                          "alvo": alvo}})


def buraco_real(paginas, janela, fim_ms=None):
    """Quanto tempo a tela fica REALMENTE sem legenda, pela regra do componente.

    Com a próxima página suprimida, o `prox` do `CaptionLayer` vira `null` e a
    página anterior sai em `ultimoFim + CAUDA_MS` com fade — não estica até a
    próxima visível. O buraco é daí até o `startMs` da próxima visível.

    ⚠️ Quando a supressão vai até o FIM da peça não existe "próxima visível", e o
    buraco vai até `fim_ms`. Sem esse ramo a função devolvia 0 justamente no caso
    pior — um portão que mede 0 no fim do vídeo é um portão cego.
    """
    sup = set(janela["paginas"])
    if not sup:
        return 0
    antes = [i for i in range(len(paginas)) if i < min(sup) and i not in sup]
    depois = [i for i in range(len(paginas)) if i > max(sup) and i not in sup]
    ini = (_fim(paginas[antes[-1]]["tokens"]) + CAUDA_MS) if antes else 0
    if depois:
        fim = paginas[depois[0]]["startMs"]
    elif fim_ms is not None:
        fim = fim_ms
    else:
        fim = _fim(paginas[max(sup)]["tokens"])
    return max(0, fim - ini)


# ═══════════════════════════════════════════════════ PASSO 5 — serializar
def _cfg_do_perfil(p, quieto=False):
    """`legenda.diretor` do perfil, com fallback embutido e aviso no stderr."""
    leg = p.get("legenda") or {}
    d = dict(leg.get("diretor") or {})
    if not d and not quieto:
        print("aviso: perfil sem legenda.diretor — usando DIRETOR_FALLBACK "
              "(valores do reels). `perfil.py patch` grava o bloco.", file=sys.stderr)
    cfg = json.loads(json.dumps(DIRETOR_FALLBACK))
    for k, v in d.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    # min_solo_ms HERDA de legenda.agrupamento (SPEC-13) quando não declarado:
    # dois números para o mesmo limiar é como a legenda e a partitura passam a
    # discordar sobre o que é solo.
    if "min_solo_ms" not in d:
        herdado = (leg.get("agrupamento") or {}).get("min_solo_ms") or leg.get("min_solo_ms")
        if herdado:
            cfg["min_solo_ms"] = herdado
    return cfg


DIRETOR_FALLBACK = {
    "densidade_alvo_10s": 2.7,
    "espacamento_min_s": 1.2,
    "min_solo_ms": 340,
    "pausa_frase_ms": 700,
    "max_chars_manuscrito": 28,
    "fpc_manuscrito": 0.9,
    "bonus_creator": 0.15,
    "pesos": {"prosodia": 0.45, "lexico": 0.30, "posicao": 0.15, "repeticao": 0.10},
    "prosodia_ref": {"realce_db": 2.5, "alongamento": 2.0, "pausa_ms": 350},
    "fracao_legenda_alvo": 1.0,
    "papel_para_componente": {
        "numero": "AccentWord", "negacao": "DrawStroke:strikePath",
        "enumeracao": "StepTitleFlat", "tese": "HandText",
        "contraste": "MarkerHighlight", "destaque": "DrawStroke:loopCirclePath",
    },
    "cor_por_papel": {"numero": "highlight", "tese": "ink", "contraste": "highlight",
                      "enumeracao": "highlight", "negacao": "ink", "destaque": "highlight"},
    "zona_por_papel": {"numero": "topo", "tese": "topo", "contraste": "faixa-legenda",
                       "enumeracao": "lateral", "negacao": "faixa-legenda",
                       "destaque": "faixa-legenda"},
    # 🔴 `contraste` era `whoosh-soft`, que NÃO VEM NO PACOTE (2026-08-11): a
    # licença dele é a única não conferida, e ele fica fora do git do produto.
    # O papel `contraste` é o mais comum depois da tese, então uma peça do
    # cliente caía em SFX ausente pelo caminho default — falha silenciosa no
    # `staticFile`. `pop-lo` é o pop dois semitons abaixo: vem no pacote, deriva
    # do nosso sample e continua distinto de `pop` (enumeracao) e `pop-hi`
    # (numero), que é o que o papel precisa.
    "sfx_por_papel": {"numero": "pop-hi", "tese": "pencil", "contraste": "pop-lo",
                      "enumeracao": "pop", "negacao": "scratch", "destaque": "scratch"},
}


def _lexico_completo(arq_pt, lex_creator):
    d = json.load(open(arq_pt))
    return {
        "regex_numero": d["regex_numero"],
        "_stop": {so_letras(x) for x in d["stop"]},
        "_neg": {so_letras(x) for x in d["neg"]},
        "_enumeracao": {so_letras(x) for x in d["enumeracao"]},
        "_contraste": {so_letras(x) for x in d["contraste"]},
        "_marca": lex_creator.get("marca", []),
        "_evitar": lex_creator.get("evitar", []),
    }


def _resolver(dirp, nomes):
    for n in nomes:
        c = os.path.join(dirp, n)
        if os.path.isfile(c):
            return c
    return None


def gerar(args):
    dirp = args.dir
    if not os.path.isdir(dirp):
        raise SystemExit(f"diretor: {dirp} não é diretório de produção")
    cap = args.captions or _resolver(dirp, ["captions.json"])
    if not cap:
        base = dir_remotion()
        cand = os.path.join(base, "src", "data", "captions.json") if base else None
        cap = cand if cand and os.path.isfile(cand) else None
    if not cap:
        raise SystemExit("diretor: sem captions.json (use --captions)")
    aud = args.audio or _resolver(dirp, ["v1-graded.mp4", "v1-montado.mp4", "v-final.mp4"])
    if not aud:
        raise SystemExit("diretor: sem áudio (use --audio)")
    arq_perfil = args.perfil or _resolver(dirp, ["perfil.json"])
    if not arq_perfil:
        raise SystemExit("diretor: sem perfil de peça (use --perfil)")
    perfil = prosodia.carrega_perfil(arq_perfil)

    cfg = _cfg_do_perfil(perfil)
    if args.densidade is not None:
        cfg["densidade_alvo_10s"] = args.densidade

    usuario = args.usuario or usuario_do_caminho(dirp)
    lex_creator, arq_lex_creator = lexico_do_usuario(usuario, dirp, args.lexico)
    arq_pt = os.path.join(DIR_REFS, "lexico-pt.json")
    lex = _lexico_completo(arq_pt, lex_creator)

    palavras = prosodia.carrega_captions(cap)

    # ---- passo 1: medir prosódia (antes de paginar, porque é o áudio que diz
    #      qual é a DURAÇÃO da peça — e `fimMs` entra na duração efetiva da
    #      última página, que por sua vez decide se ela é um solo curto)
    sr = perfil["audio"]["sr"]
    db = prosodia.envelope(aud, sr)
    fim_ms = len(db) * prosodia.WIN * 1000
    entregavel = os.path.basename(aud).startswith("v-final")
    if entregavel:
        print("aviso: medindo prosódia no ENTREGÁVEL (%s) — o alimiter e o loudnorm "
              "de 2 passes comprimem exatamente a dinâmica que estamos medindo."
              % os.path.basename(aud), file=sys.stderr)
    tabela = prosodia.medir(db, palavras, cfg["pausa_frase_ms"])

    # ---- passo 2: paginar
    largura = perfil["video"]["largura"]
    a = agrupamento_do_perfil(perfil, largura)
    if a is None:
        raise SystemExit("diretor: legenda.agrupamento é null neste perfil — "
                         "esta peça não usa o CaptionLayer, e sem página não há partitura")
    tab = carrega_tabela(a["medida"])
    medir = medidor_de_tabela(tab)
    rel = agrupar(palavras, a, medir, fim_ms, rebalancear=not args.sem_rebalanceamento)
    paginas = rel["paginas"]

    # ---- passo 3: pontuar
    pontuadas = pontuar(tabela, palavras, lex, cfg, modo_texto=args.so_texto)

    # frases como texto (o `tese` escreve a frase, não a palavra)
    grupos = prosodia.frases(palavras, cfg["pausa_frase_ms"])
    frases_txt = {}
    for gi, g in enumerate(grupos):
        txt = "".join(palavras[i]["text"] for i in g).strip()
        frases_txt[gi] = (txt.rstrip(" .,;:"),
                          txt.endswith((".", "!", "?", "…")))

    # ---- passo 4: eleger
    duracao_s = fim_ms / 1000.0
    orcamento = round(duracao_s / 10 * cfg["densidade_alvo_10s"])
    saida = args.o or os.path.join(dirp, "partitura.json")
    travados, removidos, antigos = _antigos(saida, args.forcar)
    eleitos, descartados = eleger(pontuadas, paginas, frases_txt, cfg, perfil,
                                  orcamento, travados, duracao_s, medir, a["medida"])
    eleitos = [it for it in eleitos if it["id"] not in removidos]
    ids_agora = {it["id"] for it in eleitos}
    for it in antigos:
        if it["id"] not in ids_agora and not it.get("travado") and not it.get("removido"):
            descartados.insert(0, {"id": it["id"], "score": it.get("score", 0),
                                   "motivo": "reeleicao", "medido": {}})

    eleitos, descartados, off, frac_legenda = aparar_por_fracao(
        eleitos, descartados, paginas, duracao_s, cfg["fracao_legenda_alvo"])

    part = {
        "contrato": CONTRATO,
        "_procedencia": {
            "captions": os.path.relpath(cap),
            "audio": os.path.relpath(aud),
            "audio_e_entregavel": entregavel,
            # o formato viaja COM a partitura: assim o entry point do Remotion
            # não depende de nenhum arquivo de perfil compartilhado. ⚠️ O
            # comentário anterior dizia que `src/data/perfil.json` "pertence à
            # última produção que rodou o perfil.py resolver" — isso deixou de ser
            # verdade na SPEC-31 (A6): aquele arquivo virou FIXTURE do produto, e o
            # snapshot da peça mora em `<dir-producao>/remotion/perfil.json`. A
            # razão de o formato viajar aqui continua valendo; a descrição do
            # vizinho é que envelheceu (R-20e, 2026-08-11).
            "perfil": {"nome": perfil.get("nome"), "arquivo": os.path.relpath(arq_perfil),
                       "video": {"largura": perfil["video"]["largura"],
                                 "altura": perfil["video"]["altura"],
                                 "fps": perfil["video"]["fps"]}},
            "tema": args.tema,
            "lexico_creator": os.path.relpath(arq_lex_creator) if arq_lex_creator else None,
            "usuario": usuario,
            "pesos": cfg["pesos"],
            "prosodia_ref": cfg["prosodia_ref"],
            "orcamento": {"alvo_elem_10s": cfg["densidade_alvo_10s"],
                          "duracao_s": round(duracao_s, 3), "cota": orcamento,
                          "candidatos": len(pontuadas), "eleitos": len(eleitos)},
            "paginacao": {"paginas": len(paginas), "fechamentos": rel["fechamentos"],
                          "fundidas": rel["fundidas"], "movidas": rel["movidas"],
                          "avisos": rel["avisos"]},
            "legenda": {"fracao_alvo": cfg["fracao_legenda_alvo"],
                        "fracao_medida": frac_legenda,
                        "janelas_off": len(off)},
            "modo": "so-texto" if args.so_texto else "prosodia",
        },
        "paginas": [{"i": i, "startMs": p["startMs"], "endMs": _fim(p["tokens"]),
                     "duracaoEfetivaMs": p["durationMs"],
                     "larguraEstimada": p["larguraEstimada"], "motivo": p["motivo"],
                     "text": p["text"],
                     "tokens": p["tokens"],
                     # ⚠️ TOKENS, não strings. O `CaptionLayer` faz
                     # `ln.map(pinta)` e `pinta` lê `tk.text`, `tk.fromMs` e
                     # `tk.toMs`; com uma string, `tk.text` é `undefined` e o
                     # componente renderiza NADA — 0 px de tinta, com o DOM
                     # inteiro montado e sem erro nenhum. Medido em 39/39 páginas
                     # do perfil vsl e 63/63 do reels antes de 2026-08-09. Custa
                     # duplicar o token no JSON, e é o preço de a quebra de linha
                     # existir sem um segundo contrato.
                     "linhas": p["linhas"]}
                    for i, p in enumerate(paginas)],
        "legenda_off": [[j["ini"], j["fim"]] for j in off],
        "legenda_off_detalhe": off,
        "itens": eleitos,
        "descartados": descartados,
    }

    with open(saida, "w", encoding="utf-8") as fh:
        json.dump(part, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    base = dir_remotion()
    if base and os.path.isdir(os.path.join(base, "src", "data")):
        with open(os.path.join(base, "src", "data", "partitura.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(part, fh, ensure_ascii=False, indent=1, sort_keys=False)
            fh.write("\n")
    _tabela_stderr(part)
    print(os.path.abspath(saida))
    return 0


def _antigos(saida, forcar):
    if forcar or not os.path.isfile(saida):
        return [], set(), []
    d = json.load(open(saida))
    itens = d.get("itens", [])
    travados = [it for it in itens if it.get("travado")]
    removidos = {it["id"] for it in itens if it.get("removido")}
    removidos |= {x["id"] for x in d.get("descartados", []) if x.get("removido")}
    return travados, removidos, itens


def _tabela_stderr(part):
    pr = part["_procedencia"]
    o = pr["orcamento"]
    print("partitura: %.2fs · %d páginas · orçamento %d · eleitos %d · candidatos %d · modo %s"
          % (o["duracao_s"], len(part["paginas"]), o["cota"], o["eleitos"],
             o["candidatos"], pr["modo"]), file=sys.stderr)
    pg = pr["paginacao"]
    print("paginação: fecha por %s · fundidas %s · movidas %s · avisos %d"
          % (pg["fechamentos"], pg["fundidas"], pg["movidas"], len(pg["avisos"])),
          file=sys.stderr)
    print("%6s %-16s %-11s %-22s %-6s %6s %8s" %
          ("t", "palavra", "papel", "componente", "canal", "score", "realce"), file=sys.stderr)
    for it in part["itens"]:
        print("%6.2f %-16s %-11s %-22s %-6s %6.3f %+7.1f" % (
            it["inS"], it["palavra"]["text"].strip()[:16], it["papel"],
            it["componente"], it["canal"], it["score"],
            it["por_que"]["medido"]["realce_db"]), file=sys.stderr)


# ═══════════════════════════════════════════════════ validar
def validar(argv):
    ap = argparse.ArgumentParser(prog="diretor-legenda.py validar")
    ap.add_argument("arquivo")
    ap.add_argument("--paginas", action="store_true",
                    help="confere também o espelho da ponte contra os arquivos TS")
    a = ap.parse_args(argv)
    d = json.load(open(a.arquivo))
    erros = []
    if d.get("contrato") != CONTRATO:
        erros.append("contrato %r != %r" % (d.get("contrato"), CONTRATO))
    for campo in ("paginas", "itens", "descartados", "legenda_off", "_procedencia"):
        if campo not in d:
            erros.append("falta o campo %r" % campo)
    if erros:
        for e in erros:
            print("ERRO " + e, file=sys.stderr)
        return 1

    itens = d["itens"]
    paginas = d["paginas"]

    # ---- 1. sequencialidade estrita POR CANAL, com a legenda ocupando `texto`
    pares = 0
    por_canal = {}
    for it in itens:
        por_canal.setdefault(it["canal"], []).append(it)
    for canal, xs in por_canal.items():
        xs = sorted(xs, key=lambda x: x["inS"])
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                if xs[j]["inS"] >= xs[i]["outS"]:
                    break
                pares += 1
                print("ERRO canal %s: %s [%.3f,%.3f] × %s [%.3f,%.3f]"
                      % (canal, xs[i]["id"], xs[i]["inS"], xs[i]["outS"],
                         xs[j]["id"], xs[j]["inS"], xs[j]["outS"]), file=sys.stderr)

    # ---- 2. quem DISPUTA espaço com a legenda tem que ter a janela de off
    # 🔴 Só item marcado `suprime_legenda` — e essa marca é por ZONA, não por
    # canal (ver ZONAS_DA_LEGENDA). Exigir off de todo item de texto foi o que
    # produziu uma janela de 17,3 s sem legenda na primeira versão deste script.
    off = [(a0, b0) for a0, b0 in d["legenda_off"]]
    sem_off = 0
    for it in itens:
        if not it.get("suprime_legenda"):
            continue
        coberto = any(a0 <= it["inS"] + 1e-9 and b0 >= it["outS"] - 1e-9 for a0, b0 in off)
        if not coberto:
            sem_off += 1
            print("ERRO item %s ocupa o canal texto em [%.3f,%.3f] e a legenda NÃO está "
                  "desligada ali (legenda_off não cobre)" % (it["id"], it["inS"], it["outS"]),
                  file=sys.stderr)

    # ---- 3. as janelas de off caem em FRONTEIRA DE PÁGINA
    inicios = {p["startMs"] / 1000.0 for p in paginas}
    fins = {p["endMs"] / 1000.0 for p in paginas}
    fora = 0
    for a0, b0 in off:
        if round(a0, 3) not in {round(x, 3) for x in inicios} or \
           round(b0, 3) not in {round(x, 3) for x in fins}:
            fora += 1
            print("ERRO janela [%.3f,%.3f] não cai em fronteira de página" % (a0, b0),
                  file=sys.stderr)

    # ---- 4. ordem das páginas
    # ⚠️ Sobreposição entre páginas vizinhas é HERDADA do captions.json quando os
    # timestamps de duas palavras consecutivas se cruzam (o Deepgram faz isso: na
    # peca-02, " tudo." termina em 29105 e " O" começa em 28950). Como a
    # página nasce de tokens consecutivos, esse caso é sempre herdado — conta-se
    # e nomeia-se, mas não reprova, senão o validador acusa o ASR e não a gente.
    desordem = herdada = 0
    for i in range(len(paginas) - 1):
        if paginas[i]["endMs"] > paginas[i + 1]["startMs"]:
            ult = max(paginas[i]["tokens"], key=lambda t: t["toMs"])
            prim = paginas[i + 1]["tokens"][0]
            if ult["toMs"] > prim["fromMs"]:
                herdada += 1
                print("nota: páginas %d/%d se cruzam por %d ms — herdado do captions "
                      "(%r termina em %d, %r começa em %d)"
                      % (i, i + 1, ult["toMs"] - prim["fromMs"], ult["text"], ult["toMs"],
                         prim["text"], prim["fromMs"]), file=sys.stderr)
            else:
                desordem += 1

    print("validar: %d itens em %d canais · %d páginas · %d janelas de off"
          % (len(itens), len(por_canal), len(paginas), len(off)), file=sys.stderr)
    print("validar: pares com interseção %d · itens que suprimem sem off %d · janelas fora "
          "de fronteira %d · páginas desordenadas %d (+%d cruzamentos herdados do ASR)"
          % (pares, sem_off, fora, desordem, herdada), file=sys.stderr)

    if a.paginas:
        rc = _espelho_ponte()
        if rc:
            return rc
    return 0 if (pares == 0 and sem_off == 0 and fora == 0 and desordem == 0) else 1


def _espelho_ponte():
    """PONTE_MS/CAUDA_MS aqui × `CaptionLayer.tsx` × `agrupar.ts`.

    Terceira cópia dos mesmos dois números. Cópia sem gate vira divergência
    silenciosa — este é o gate (o mesmo mecanismo do `--espelho` da SPEC-13).
    """
    base = dir_remotion()
    if not base:
        print("espelho: sem tools/remotion-compositor — pulado", file=sys.stderr)
        return 0
    arq = os.path.join(base, "src", "CaptionLayer.tsx")
    src = open(arq).read()
    m1 = re.search(r"prox\.startMs\s*-\s*ultimoFim\s*<\s*(\d+)", src)
    m2 = re.search(r"ultimoFim\s*\+\s*(\d+)", src)
    print("espelho: varri %d linhas de CaptionLayer.tsx, casei %d/2 padrões"
          % (src.count("\n") + 1, sum(1 for m in (m1, m2) if m)), file=sys.stderr)
    if not m1 or not m2:
        print("ERRO espelho: não achei a ponte no CaptionLayer.tsx", file=sys.stderr)
        return 1
    if int(m1.group(1)) != PONTE_MS or int(m2.group(1)) != CAUDA_MS:
        print("ERRO espelho: CaptionLayer %s/%s × diretor %s/%s"
              % (m1.group(1), m2.group(1), PONTE_MS, CAUDA_MS), file=sys.stderr)
        return 1
    return 0


# ═══════════════════════════════════════════════════ PARTITURA.md
def md(argv):
    ap = argparse.ArgumentParser(prog="diretor-legenda.py md")
    ap.add_argument("arquivo")
    ap.add_argument("-o", dest="o")
    a = ap.parse_args(argv)
    d = json.load(open(a.arquivo))
    pr = d["_procedencia"]
    o = pr["orcamento"]
    L = []
    nome = os.path.basename(os.path.dirname(os.path.abspath(a.arquivo)))
    L.append("# Partitura — %s (%s · %s)" % (nome, pr["perfil"]["nome"], pr["tema"]))
    L.append("")
    L.append("%.2f s · %d palavras em %d páginas · orçamento %d · eleitos %d · "
             "candidatos %d · modo %s"
             % (o["duracao_s"], sum(len(p["tokens"]) for p in d["paginas"]),
                len(d["paginas"]), o["cota"], o["eleitos"], o["candidatos"], pr["modo"]))
    L.append("")
    L.append("Prosódia medida em `%s`%s · pesos %s · referência %s"
             % (pr["audio"], " ⚠️ ENTREGÁVEL (dinâmica comprimida)"
                if pr["audio_e_entregavel"] else "", pr["pesos"], pr["prosodia_ref"]))
    L.append("")
    L.append("| t | palavra | papel | componente | SFX | cor | score | prosódia | léxico | posição | repet. | realce | along | pausa | canal |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for it in d["itens"]:
        q, m = it["por_que"], it["por_que"]["medido"]
        L.append("| %.2f | %s | %s | %s | %s | %s | %.3f | %.3f | %.3f | %.3f | %.3f | %+.1f dB | %.2f× | %s ms | %s %.2f→%.2f |"
                 % (it["inS"], it["palavra"]["text"].strip(), it["papel"], it["componente"],
                    it.get("sfx") or "sem SFX", it["cor"], it["score"], q["prosodia"], q["lexico"], q["posicao"],
                    q["repeticao"], m["realce_db"], m["alongamento"],
                    m["pausa_depois_ms"], it["canal"], it["inS"], it["outS"]))
    L.append("")
    L.append("## Legenda fora do ar")
    L.append("")
    L.append("| janela | s sem legenda | motivo | páginas suprimidas |")
    L.append("|---|---|---|---|")
    paginas = d["paginas"]
    for j in d.get("legenda_off_detalhe", []):
        pg = [{"startMs": p["startMs"], "tokens": p["tokens"]} for p in paginas]
        L.append("| %.2f–%.2f | %.2f | %s | %s |"
                 % (j["ini"], j["fim"], buraco_real(pg, j, pr["orcamento"]["duracao_s"] * 1000) / 1000.0, j["por"],
                    ", ".join(str(x) for x in j["paginas"])))
    L.append("")
    L.append("## Quase entraram (10 maiores descartados)")
    L.append("")
    L.append("| id | score | motivo | realce | along |")
    L.append("|---|---|---|---|---|")
    for x in d["descartados"][:10]:
        m = x.get("medido") or {}
        L.append("| %s | %.3f | %s | %s | %s |"
                 % (x["id"], x["score"], x["motivo"],
                    ("%+.1f dB" % m["realce_db"]) if "realce_db" in m else "—",
                    ("%.2f×" % m["alongamento"]) if "alongamento" in m else "—"))
    L.append("")
    pg = pr["paginacao"]
    L.append("## Paginação")
    L.append("")
    L.append("Fecha por %s · fundidas %s · **movidas (rebalanceamento SPEC-14) %s** · "
             "avisos %d" % (pg["fechamentos"], pg["fundidas"], pg["movidas"],
                            len(pg["avisos"])))
    for av in pg["avisos"]:
        L.append("- ⚠️ %s: %r — %s" % (av["tipo"], av["texto"], av["detalhe"]))
    L.append("")
    destino = a.o or os.path.join(os.path.dirname(os.path.abspath(a.arquivo)), "PARTITURA.md")
    open(destino, "w", encoding="utf-8").write("\n".join(L))
    print(os.path.abspath(destino))
    return 0


# ═══════════════════════════════════════════════════ main
def main(argv):
    if argv and argv[0] == "validar":
        return validar(argv[1:])
    if argv and argv[0] == "md":
        return md(argv[1:])
    ap = argparse.ArgumentParser(prog="diretor-legenda.py")
    ap.add_argument("dir")
    ap.add_argument("--captions")
    ap.add_argument("--audio")
    ap.add_argument("--perfil")
    ap.add_argument("--tema", default="neutralTheme")
    ap.add_argument("--lexico")
    ap.add_argument("--usuario")
    ap.add_argument("--so-texto", action="store_true", dest="so_texto")
    ap.add_argument("--densidade", type=float)
    ap.add_argument("--sem-rebalanceamento", action="store_true",
                    dest="sem_rebalanceamento",
                    help="desliga o passe de doação de fronteira (para medir o que ele fez)")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("-o")
    return gerar(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
