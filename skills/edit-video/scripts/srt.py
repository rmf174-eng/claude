#!/usr/bin/env python3
"""srt.py — `captions.srt` / `.vtt` a partir das palavras do BRUTO (SPEC-21).

    srt.py <dir> [-o captions.srt] [--formatos srt,vtt] [--perfil-off]
           [--max-chars N --linhas N --cps N --dur-min S --dur-max S --gap S]
           [--verificar] [--verificar-audio [--amostras N] [--offset-teste S]
                          [--janelas-json]]

    stdout: o caminho do artefato · stderr: o resumo
    exit 0 ok · 1 regra violada · 2 declarado e não produzido (ou não verificado)

────────────────────────────────────────────────────────────────────────────
O QUE ESTE ARQUIVO NÃO FAZ, E POR QUÊ

  · NÃO transcreve o montado. As palavras vêm do `palavras.py`, que as tira do
    transcript do BRUTO. O ASR do montado lê a emenda como fala contínua e
    inventa palavra — defeito já entregue ("Você manda as empresas com o seu
    sócio" onde o creator-3 fala "uma das empresas que eu sou sócio").
  · NÃO soma `end−start` da EDL para achar posição. Sem `timeline_real` ele
    aborta; não existe fallback.
  · NÃO antecipa o início de um cue para atingir duração mínima. Texto na tela
    antes da palavra ser dita é erro de sincronia; cue curto é só desconforto.
  · NÃO tem piso mágico de 0,4 s no clamp de sobreposição (é o que faz o
    `captions_srt.py:58` do ref-A prometer `min_dur` e o `:77-80` violá-lo em
    silêncio). Aqui a violação é CONTADA e vai para o sidecar.
  · NÃO põe a legenda em caixa alta (`render.py:806` deles). `caixa: original`.

AS RÉGUAS SÃO DADO, NÃO CÓDIGO. `max_chars_linha`, `linhas`, `cps_max`,
`dur_min_s`, `dur_max_s`, `gap_quebra_s` e `gap_entre_cues_frames` vêm do bloco
`publicacao.srt` do perfil de peça; `fps` e `sample_rate` vêm do `timeline_real`.
Nenhum valor de formato mora neste arquivo.
"""
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io      # noqa: E402
import palavras as palavras_mod   # noqa: E402

SCHEMA = "benchmark.publicacao/v1"
ENDERS = ".!?…"


# ────────────────────────────────────────────────────────── quebra de linha

def _dp_quebra(tokens, n_linhas):
    """Reparte `tokens` em até `n_linhas` linhas minimizando a linha mais longa.

    Empate desfeito pelo menor desequilíbrio — é o "caractere do meio" do
    `captions_srt.py:84-97` generalizado para n linhas, com a guarda que eles
    não têm: quando a melhor partição ainda estoura, o chamador vê e quebra o
    cue em vez de aceitar linha comprida."""
    n = len(tokens)
    if n == 0:
        return []
    larg = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        acc = 0
        for j in range(i, n):
            acc += len(tokens[j]) + (1 if j > i else 0)
            larg[i][j + 1] = acc
    INF = float("inf")
    melhor = {(0, 0): (0, 0, None)}
    for linhas_usadas in range(1, n_linhas + 1):
        for j in range(1, n + 1):
            best = None
            for i in range(0, j):
                ant = melhor.get((i, linhas_usadas - 1))
                if ant is None:
                    continue
                w = larg[i][j]
                cand = (max(ant[0], w), ant[1] + w * w, i)
                if best is None or (cand[0], cand[1]) < (best[0], best[1]):
                    best = cand
            if best is not None:
                atual = melhor.get((j, linhas_usadas))
                if atual is None or (best[0], best[1]) < (atual[0], atual[1]):
                    melhor[(j, linhas_usadas)] = best
    alvo = None
    for linhas_usadas in range(1, n_linhas + 1):
        c = melhor.get((n, linhas_usadas))
        if c is not None and (alvo is None or (c[0], c[1]) < (alvo[0], alvo[1])):
            alvo, alvo_l = c, linhas_usadas
    if alvo is None:
        return None
    corte, l = [], alvo_l
    j = n
    while l > 0:
        i = melhor[(j, l)][2]
        corte.append((i, j))
        j, l = i, l - 1
    corte.reverse()
    return [" ".join(tokens[i:j]) for i, j in corte]


def quebrar(texto, max_chars, n_linhas):
    """[linhas] se cabe em `n_linhas` de até `max_chars`; None se não cabe.

    Usa o MENOR número de linhas que cabe, e só então equilibra. Minimizar a
    linha mais longa sem esse teto quebraria "e na verdade" em duas linhas de 4 e
    7 caracteres — equilíbrio perfeito e legenda ridícula."""
    tokens = texto.split()
    for n in range(1, n_linhas + 1):
        ls = _dp_quebra(tokens, n)
        if ls is not None and len(ls) <= n and all(len(x) <= max_chars for x in ls):
            return ls
    return None


# ───────────────────────────────────────────────────────────── agrupamento

def _texto(ws, caixa="original"):
    t = " ".join(w["texto"].strip() for w in ws if w["texto"].strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t.upper() if caixa == "maiuscula" else t


def _cue(ws, regra):
    t = _texto(ws, regra.get("caixa", "original"))
    linhas = quebrar(t, regra["max_chars_linha"], regra["linhas"]) or [t]
    return {"palavras": list(ws), "texto": t, "linhas": linhas,
            "ini": ws[0]["ini"], "fim": ws[-1]["fim"]}


def agrupar(ws, regra, desc):
    """Acumula palavra a palavra e fecha no PRIMEIRO gatilho (§3.3 da SPEC-21)."""
    cues, cur = [], []
    for w in ws:
        if cur:
            prev = cur[-1]
            # 1. descontinuidade REAL (troca de src ou emenda de verdade).
            #    Plano contíguo do `dividir-planos.py` NÃO quebra cue: é a mesma
            #    frase com dois enquadramentos.
            quebra = (w["i_seg"] != prev["i_seg"]
                      and w["i_seg"] < len(desc) and desc[w["i_seg"]])
            # 2. pontuação de fim de frase
            if not quebra and prev["texto"].rstrip().endswith(tuple(ENDERS)):
                quebra = True
            # 3. gap de silêncio
            if not quebra and (w["ini"] - prev["fim"]) >= regra["gap_quebra_s"]:
                quebra = True
            # 4. orçamento de caracteres, medido no texto JÁ QUEBRADO
            if not quebra:
                t = _texto(cur + [w], regra.get("caixa", "original"))
                if quebrar(t, regra["max_chars_linha"], regra["linhas"]) is None:
                    quebra = True
            # 5. teto de duração
            if not quebra and (w["fim"] - cur[0]["ini"]) > regra["dur_max_s"]:
                quebra = True
            if quebra:
                cues.append(_cue(cur, regra))
                cur = []
        cur.append(w)
    if cur:
        cues.append(_cue(cur, regra))
    return cues


def _maior_gap(ws):
    """(índice de corte, tamanho do gap) do maior silêncio INTERNO do cue."""
    melhor, tam = None, -1.0
    for i in range(1, len(ws)):
        g = ws[i]["ini"] - ws[i - 1]["fim"]
        if g > tam:
            melhor, tam = i, g
    return melhor, tam


def _corte_por_virgula(ws):
    alvo, dist = None, None
    meio = len(ws) / 2.0
    for i in range(1, len(ws)):
        if re.search(r"[,;:]$", ws[i - 1]["texto"].strip()):
            d = abs(i - meio)
            if dist is None or d < dist:
                alvo, dist = i, d
    return alvo


def passe_cps(cues, regra, gap_cues, total_s):
    """Velocidade de leitura — a régua que o ref-A não tem (`captions_srt.py` mede
    caracteres e duração INDEPENDENTEMENTE, e a razão entre os dois, que é o que
    decide se dá para ler, não é medida em lugar nenhum).

    Ordem, e ela importa: (b) primeiro ESTICA o fim para dentro do silêncio que já
    existe até o próximo cue; (a) se ainda estoura, parte o cue no maior gap
    interno (ou numa vírgula) e estica de novo — partir só ajuda porque cada
    metade passa a poder ocupar o silêncio que era do vizinho; (c) se ainda assim
    estoura, NÃO mente: mantém o tempo real e conta a ocorrência.

    Partir sem gap interno nem vírgula deixaria as duas metades PIORES que o
    original (mesmos caracteres, menos tempo), então nesse caso não parte."""
    cps_max = regra["cps_max"]

    def esticar(lst):
        for k, c in enumerate(lst):
            teto = (lst[k + 1]["ini"] - gap_cues) if k + 1 < len(lst) else total_s
            alvo = min(c["ini"] + len(c["texto"]) / cps_max, teto, total_s)
            if alvo > c["fim"]:
                c["fim"] = alvo
        return lst

    def cps_de(c):
        return len(c["texto"]) / max(c["fim"] - c["ini"], 1e-6)

    cues = esticar(cues)
    for _ in range(len(cues) + 4):
        saida, mudou = [], False
        for k, c in enumerate(cues):
            if cps_de(c) <= cps_max or len(c["palavras"]) < 2:
                saida.append(c)
                continue
            j, tam = _maior_gap(c["palavras"])
            if tam <= 0:
                j = _corte_por_virgula(c["palavras"])
            if not j:
                saida.append(c)
                continue
            # 🔴 PARTIR SÓ VALE SE MELHORAR, e é preciso MEDIR isso, não supor.
            # Partir não cria tempo: as duas metades dividem a mesma janela. O
            # ganho vem do silêncio interno que a segunda metade passa a poder
            # ocupar. Sem essa conferência, partir "estou aqui otimizando algumas
            # coisas enquanto eu trabalho, e na verdade" produzia um cue de
            # "e na verdade" com 29 cps — PIOR que o original de 19.
            teto = (cues[k + 1]["ini"] - gap_cues) if k + 1 < len(cues) else total_s
            a, b = _cue(c["palavras"][:j], regra), _cue(c["palavras"][j:], regra)
            a["fim"] = min(max(a["fim"], a["ini"] + len(a["texto"]) / cps_max),
                           b["ini"] - gap_cues)
            b["fim"] = min(max(b["fim"], b["ini"] + len(b["texto"]) / cps_max),
                           teto, total_s)
            if max(cps_de(a), cps_de(b)) < cps_de(c) - 1e-9:
                saida.extend([a, b])
                mudou = True
            else:
                saida.append(c)
        cues = esticar(saida)
        if not mudou:
            break
    return cues


def passe_dur_min(cues, regra, gap_cues, total_s):
    """Estende o FIM até `dur_min_s`. NUNCA antecipa o início."""
    for k, c in enumerate(cues):
        if c["fim"] - c["ini"] >= regra["dur_min_s"]:
            continue
        teto = (cues[k + 1]["ini"] - gap_cues) if k + 1 < len(cues) else total_s
        c["fim"] = min(c["ini"] + regra["dur_min_s"], teto, total_s)
        if c["fim"] <= c["ini"]:
            c["fim"] = min(c["ini"] + 1e-3, total_s)
    return cues


def passe_sobreposicao(cues, gap_cues, regra):
    """`cue[i].fim <= cue[i+1].ini − gap`. Sem piso mágico; a violação é CONTADA."""
    clampados, sobrep_max = 0, 0.0
    for k in range(len(cues) - 1):
        limite = cues[k + 1]["ini"] - gap_cues
        if cues[k]["fim"] > limite + 1e-9:
            sobrep_max = max(sobrep_max, cues[k]["fim"] - limite)
            cues[k]["fim"] = max(limite, cues[k]["ini"] + 1e-3)
            clampados += 1
    curtos = sum(1 for c in cues if c["fim"] - c["ini"] < regra["dur_min_s"] - 1e-9)
    return clampados, curtos, sobrep_max


def snap_ms(cues, gap_cues, total_s):
    """Leva ini/fim para a grade de 1 ms DO FORMATO e refaz o clamp lá.

    🔴 Sem isto o arquivo escrito viola o invariante que a memória satisfazia: o
    clamp punha `fim` exatamente em `próximo.ini − gap`, mas `gap = 2/30 s` não
    cai na grade de milissegundo, e `HH:MM:SS,mmm` arredonda — 16 cues do
    `c-completo` saíram 0,7 ms sobrepostos, e o `--verificar` (que lê o ARQUIVO,
    não a memória) acusou os 16. É por isso que a verificação relê o disco."""
    tot = int(round(total_s * 1000))
    for c in cues:
        c["ini"] = max(0, min(tot, int(round(c["ini"] * 1000))))
        c["fim"] = max(c["ini"] + 1, min(tot, int(round(c["fim"] * 1000))))
    gap = gap_cues * 1000
    for k in range(len(cues) - 1):
        limite = int(math.floor(cues[k + 1]["ini"] - gap))
        if cues[k]["fim"] > limite:
            cues[k]["fim"] = max(limite, cues[k]["ini"] + 1)
    for c in cues:
        c["ini"] /= 1000.0
        c["fim"] /= 1000.0
    return cues


# ──────────────────────────────────────────────────────────────── escrita

def ts_srt(t):
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def ts_vtt(t):
    return ts_srt(t).replace(",", ".")


def render_srt(cues):
    """UTF-8 sem BOM, LF, e COM newline final (o `captions_srt.py:137` deles fecha sem)."""
    out = []
    for i, c in enumerate(cues, 1):
        out.append("%d\n%s --> %s\n%s\n"
                   % (i, ts_srt(c["ini"]), ts_srt(c["fim"]), "\n".join(c["linhas"])))
    return "\n".join(out) + ("\n" if out else "")


def render_vtt(cues):
    out = ["WEBVTT\n"]
    for c in cues:
        out.append("%s --> %s\n%s\n" % (ts_vtt(c["ini"]), ts_vtt(c["fim"]),
                                        "\n".join(c["linhas"])))
    return "\n".join(out) + ("\n" if len(out) > 1 else "")


# ─────────────────────────────────────────────────────────── leitura do .srt

_RE_TS = re.compile(r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)")


def ler_srt(path):
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    if txt.startswith("﻿"):
        raise ValueError("%s começa com BOM — o contrato é UTF-8 SEM BOM" % path)
    if "\r" in txt:
        raise ValueError("%s tem CR — o contrato é LF" % path)
    cues = []
    for bloco in [b for b in txt.split("\n\n") if b.strip()]:
        linhas = bloco.strip("\n").split("\n")
        if len(linhas) < 3:
            raise ValueError("bloco malformado em %s: %r" % (path, bloco[:60]))
        m = _RE_TS.search(linhas[1])
        if not m:
            raise ValueError("timestamp malformado em %s: %r" % (path, linhas[1]))
        g = [int(x) for x in m.groups()]
        ini = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        fim = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        cues.append({"i": int(linhas[0]), "ini": ini, "fim": fim,
                     "linhas": linhas[2:], "texto": " ".join(linhas[2:])})
    return cues


# ───────────────────────────────────────────────────────────────── geração

def gerar(d, *, regra=None, saida=None, formatos=None, transcritos=None,
          mapa_arq=None, orto_arq=None, alinhamento=None, perfil_off=False):
    """Devolve (caminhos, sidecar, cues). Não decide se DEVE rodar — quem decide é o perfil."""
    tl = edl_io.timeline(d, exigir=True)
    fps = tl["video"]["fps"]
    total_s = tl["total_s"]
    bloco, origem = palavras_mod.publicacao(d, ignorar_perfil=perfil_off)
    r = dict(bloco["srt"])
    r.update(regra or {})
    if r.get("fonte_palavras") not in (None, "edl-bruto"):
        raise palavras_mod.ErroPublicacao(
            "publicacao.srt.fonte_palavras=%r não é aceito: a legenda sai do "
            "transcript do BRUTO. Transcrever o montado faz o ASR inventar palavra "
            "na emenda (defeito já entregue)." % r.get("fonte_palavras"))

    ws, info = palavras_mod.palavras_no_montado(
        d, tl=tl, transcritos=transcritos, mapa_arq=mapa_arq,
        alinhamento=alinhamento, orto_arq=orto_arq)
    if not ws:
        raise palavras_mod.ErroPublicacao("nenhuma palavra mapeada — transcript vazio?")

    gap_cues = r["gap_entre_cues_frames"] / float(fps)
    cues = agrupar(ws, r, info["descontinuidades"])
    cues = passe_cps(cues, r, gap_cues, total_s)
    cues = passe_dur_min(cues, r, gap_cues, total_s)
    clampados, _, sobrep_max = passe_sobreposicao(cues, gap_cues, r)
    cues = snap_ms(cues, gap_cues, total_s)
    # as estatísticas do sidecar saem dos MESMOS números que vão para o arquivo
    curtos = sum(1 for c in cues if c["fim"] - c["ini"] < r["dur_min_s"] - 5e-4)
    cps = sorted(len(c["texto"]) / max(c["fim"] - c["ini"], 1e-6) for c in cues)
    excedidos = sum(1 for x in cps if x > r["cps_max"] + 1e-9)

    fmts = [f.strip() for f in (formatos or r.get("formatos") or ["srt"]) if f.strip()]
    nome = saida or r["arquivo"]
    base = nome if os.path.isabs(nome) else os.path.join(d, nome)
    raiz = os.path.splitext(base)[0]
    caminhos = []
    for f in fmts:
        p = base if f == "srt" else raiz + "." + f
        texto = render_srt(cues) if f == "srt" else render_vtt(cues)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(texto)
        caminhos.append(p)

    side = {
        "schema": SCHEMA, "gerado_por": "srt.py",
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "edl_fingerprint": tl.get("edl_fingerprint"),
        "perfil": origem, "fonte_palavras": "edl-bruto",
        "fonte_tempo": info["fonte_tempo"],
        "transcritos": info["transcritos"],
        "ortografia": info["ortografia"],
        "regra": r,
        "formatos": fmts,
        "cues": len(cues), "palavras": len(ws),
        "cps_p50": round(_pct(cps, 0.50), 2), "cps_p95": round(_pct(cps, 0.95), 2),
        "cps_excedidos": excedidos,
        "dur_min_violada": curtos,
        "sobreposicoes_clampadas": clampados,
        "sobreposicao_max_ms": round(sobrep_max * 1000, 1),
        "cauda_clampada": info["cauda_clampada"],
        "total_s": total_s, "fps": fps,
    }
    with open(base + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(side, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return caminhos, side, cues


def _pct(ordenados, q):
    if not ordenados:
        return 0.0
    i = min(len(ordenados) - 1, max(0, int(round(q * (len(ordenados) - 1)))))
    return ordenados[i]


# ─────────────────────────────────────────────────────────────── verificação

def verificar(d, path, side):
    """Relê o ARQUIVO e afirma os invariantes. Pega erro de escrita/formatação."""
    r = side["regra"]
    fps, total_s = side["fps"], side["total_s"]
    gap = r["gap_entre_cues_frames"] / float(fps)
    problemas = []
    cues = ler_srt(path)
    if len(cues) != side["cues"]:
        problemas.append("o arquivo tem %d cues, o sidecar declara %d"
                         % (len(cues), side["cues"]))
    for k, c in enumerate(cues):
        if c["i"] != k + 1:
            problemas.append("cue %d: índice %d fora de ordem" % (k + 1, c["i"]))
        if c["fim"] <= c["ini"]:
            problemas.append("cue %d: fim <= ini (%.3f, %.3f)" % (c["i"], c["ini"], c["fim"]))
        if c["ini"] < -1e-9 or c["fim"] > total_s + 5e-4:
            problemas.append("cue %d: [%.3f, %.3f] fora de [0, %.3f]"
                             % (c["i"], c["ini"], c["fim"], total_s))
        if len(c["linhas"]) > r["linhas"]:
            problemas.append("cue %d: %d linhas (máx %d)" % (c["i"], len(c["linhas"]), r["linhas"]))
        for ln in c["linhas"]:
            if len(ln) > r["max_chars_linha"]:
                problemas.append("cue %d: linha de %d chars (máx %d): %r"
                                 % (c["i"], len(ln), r["max_chars_linha"], ln[:50]))
        if k + 1 < len(cues) and c["fim"] > cues[k + 1]["ini"] - gap + 5e-4:
            problemas.append("cue %d: fim %.3f > próximo.ini %.3f − gap %.3f"
                             % (c["i"], c["fim"], cues[k + 1]["ini"], gap))
    cps = sorted(len(c["texto"]) / max(c["fim"] - c["ini"], 1e-6) for c in cues)
    p95 = _pct(cps, 0.95)
    excedidos = sum(1 for x in cps if x > r["cps_max"] + 1e-9)
    curtos = [c["i"] for c in cues if c["fim"] - c["ini"] < r["dur_min_s"] - 5e-4]
    # 🔴 O QUE REPROVA AQUI É O ARTEFATO MENTIR, NÃO O ORADOR FALAR RÁPIDO.
    # `cps` e `dur_min` são réguas de conforto que o material pode tornar
    # fisicamente inalcançáveis: em `peca-10-27-07/c-completo` a fala tem 17,2 cps
    # de média GLOBAL e 23,2 no p95 de janelas de 5 s — nenhum agrupamento chega a
    # 17 sem apagar texto ou mentir no tempo, que é o que a §3.3 proíbe. O
    # invariante verificável é o outro: o sidecar tem que declarar exatamente
    # quantos cues estouram, para quem revisa ver o número em vez de um verde.
    if len(curtos) != side["dur_min_violada"]:
        problemas.append("%d cue(s) abaixo de dur_min no arquivo, o sidecar declara "
                         "%d — cue curto pode existir; NÃO reportado, não"
                         % (len(curtos), side["dur_min_violada"]))
    if excedidos != side["cps_excedidos"]:
        problemas.append("%d cue(s) acima de cps_max no arquivo, o sidecar declara "
                         "%d — cue rápido pode existir; NÃO reportado, não"
                         % (excedidos, side["cps_excedidos"]))
    print("--verificar: %d cues · %d linhas · cps_p50 %.1f · cps_p95 %.1f (teto %.1f) · "
          "%d abaixo de dur_min · %d acima do teto de cps"
          % (len(cues), sum(len(c["linhas"]) for c in cues), _pct(cps, 0.5), p95,
             r["cps_max"], len(curtos), excedidos), file=sys.stderr)
    return problemas


# ───────────────────────────────────────────── régua independente (áudio)

def _tokens(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return [t for t in re.findall(r"[a-z0-9%]+", s) if t]


def verificar_audio(d, path, side, amostras=5, offset_teste=0.0, janelas_json=False):
    """A régua INDEPENDENTE: corta a janela do cue no montado, transcreve só ela e
    compara os tokens. Sem controle negativo (`--offset-teste`) um verde aqui não
    vale nada — é a regra "QC verde sem prova de dentes" da SKILL.md."""
    cues = ler_srt(path)
    if not cues:
        return 2, []
    passo = max(1, len(cues) // max(1, amostras))
    escolhidos = cues[::passo][:amostras]
    janelas = [{"i": c["i"], "ini": round(c["ini"] + offset_teste, 3),
                "fim": round(c["fim"] + offset_teste, 3), "texto": c["texto"]}
               for c in escolhidos]
    if janelas_json:
        json.dump({"offset_teste": offset_teste, "janelas": janelas},
                  sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0, janelas
    video = os.path.join(d, "v1-montado.mp4")
    if not os.path.isfile(video):
        print("--verificar-audio: %s não existe — NÃO verifiquei (não é verde)"
              % video, file=sys.stderr)
        return 2, janelas
    chave = os.environ.get("DEEPGRAM_API_KEY")
    if not chave:
        print("--verificar-audio: DEEPGRAM_API_KEY ausente — NÃO verifiquei",
              file=sys.stderr)
        return 2, janelas
    resultados = []
    for j in janelas:
        wav = os.path.join(d, ".srt-verif-%d.wav" % j["i"])
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % max(0.0, j["ini"]),
                        "-t", "%.3f" % max(0.05, j["fim"] - j["ini"]), "-i", video,
                        "-vn", "-ac", "1", wav], check=True)
        with open(wav, "rb") as fh:
            dados = fh.read()
        os.remove(wav)
        # nova-3/multi: o nova-2 pt-BR devolveu transcrição VAZIA em 3 de 16
        # janelas curtas (SKILL.md, etapa 2) — o que leria como "sumiu tudo".
        proc = subprocess.run(
            ["curl", "-sS", "-X", "POST",
             "https://api.deepgram.com/v1/listen?model=nova-3&language=multi&punctuate=true",
             "-H", "Authorization: Token %s" % chave,
             "-H", "Content-Type: audio/wav", "--data-binary", "@-"],
            input=dados, capture_output=True)
        try:
            doc = json.loads(proc.stdout)
            ouvido = doc["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (ValueError, KeyError, IndexError):
            ouvido = ""
        esperado, obtido = _tokens(j["texto"]), _tokens(ouvido)
        comuns = 0
        pool = list(obtido)
        for t in esperado:
            if t in pool:
                pool.remove(t)
                comuns += 1
        cob = comuns / len(esperado) if esperado else 0.0
        resultados.append({"i": j["i"], "cobertura": round(cob, 3),
                           "esperado": j["texto"], "ouvido": ouvido})
        print("  cue %-4d cobertura %5.1f%%  esperado=%r ouvido=%r"
              % (j["i"], cob * 100, j["texto"][:48], ouvido[:48]), file=sys.stderr)
    ok = sum(1 for r in resultados if r["cobertura"] >= 0.80)
    print("--verificar-audio: %d/%d janelas com sobreposição >= 80%% (offset_teste=%.3f)"
          % (ok, len(resultados), offset_teste), file=sys.stderr)
    return (0 if ok == len(resultados) else 1), resultados


# ────────────────────────────────────────────────────────────────────── CLI

def _cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("────")[0].strip(), file=sys.stderr)
        return 64
    d = argv.pop(0)
    saida = None
    over, transcritos, mapa_arq, orto_arq, align = {}, {}, None, None, None
    ver = ver_audio = janelas_json = perfil_off = False
    amostras, offset_teste = 5, 0.0
    mapa_flags = {"--max-chars": ("max_chars_linha", int), "--linhas": ("linhas", int),
                  "--cps": ("cps_max", float), "--dur-min": ("dur_min_s", float),
                  "--dur-max": ("dur_max_s", float), "--gap": ("gap_quebra_s", float)}
    while argv:
        a = argv.pop(0)
        if a in ("-o", "--saida"):
            saida = argv.pop(0)
        elif a == "--formatos":
            # flag de formato É régua: entra em `over` para valer na idempotência
            # e aparecer no sidecar, não num parâmetro paralelo.
            over["formatos"] = [x.strip() for x in argv.pop(0).split(",") if x.strip()]
        elif a == "--perfil-off":
            perfil_off = True
        elif a == "--verificar":
            ver = True
        elif a == "--verificar-audio":
            ver_audio = True
        elif a == "--janelas-json":
            janelas_json = True
        elif a == "--amostras":
            amostras = int(argv.pop(0))
        elif a == "--offset-teste":
            offset_teste = float(argv.pop(0))
        elif a == "--transcript":
            k, _, p = argv.pop(0).partition("=")
            transcritos[k] = p
        elif a == "--transcritos":
            mapa_arq = argv.pop(0)
        elif a == "--ortografia":
            orto_arq = argv.pop(0)
        elif a == "--alinhamento":
            align = argv.pop(0)
        elif a in mapa_flags:
            k, conv = mapa_flags[a]
            over[k] = conv(argv.pop(0))
        else:
            print("flag desconhecida: %s" % a, file=sys.stderr)
            return 64

    try:
        bloco, origem = palavras_mod.publicacao(d, ignorar_perfil=perfil_off)
    except palavras_mod.ErroPublicacao as e:
        print("ERRO: %s" % e, file=sys.stderr)
        return 2
    alvo = os.path.join(d, saida or bloco["srt"]["arquivo"])

    if ver or ver_audio:
        # verificar opera sobre o ARQUIVO que está no disco
        if not os.path.isfile(alvo) or not os.path.isfile(alvo + ".meta.json"):
            print("ERRO: %s (ou o sidecar) não existe — gere antes de verificar" % alvo,
                  file=sys.stderr)
            return 2
        with open(alvo + ".meta.json") as fh:
            side = json.load(fh)
        code = 0
        if ver:
            problemas = verificar(d, alvo, side)
            for p in problemas:
                print("  ✗ %s" % p, file=sys.stderr)
            code = 1 if problemas else 0
        if ver_audio:
            c2, _ = verificar_audio(d, alvo, side, amostras=amostras,
                                    offset_teste=offset_teste, janelas_json=janelas_json)
            if janelas_json:      # stdout já é o JSON das janelas: não sujar
                return c2
            code = code or c2
        print(alvo)
        return code

    if not bloco["srt"].get("gerar", True):
        print("perfil %s: srt desligado (publicacao.srt.gerar=false)" % origem,
              file=sys.stderr)
        return 0

    # idempotência: mesmo corte, MESMA RÉGUA e TODOS os formatos no disco.
    # ⚠️ As três condições, não duas. A versão que conferia só corte+régua
    # imprimia "pulando", saía 0 e NÃO produzia o `.vtt` que a chamada pediu —
    # sucesso silencioso, a pior classe de defeito deste repo. Mudança de flag é
    # mudança de régua (`--formatos` entra em `over` no CLI); ausência de arquivo
    # esperado invalida o pulo.
    if os.path.isfile(alvo) and os.path.isfile(alvo + ".meta.json"):
        try:
            with open(alvo + ".meta.json") as fh:
                antigo = json.load(fh)
            tl = edl_io.timeline(d, exigir=True)
            r = dict(bloco["srt"])
            r.update(over)
            raiz = os.path.splitext(alvo)[0]
            faltando = [f for f in (r.get("formatos") or ["srt"])
                        if not os.path.isfile(alvo if f == "srt" else raiz + "." + f)]
            if antigo.get("edl_fingerprint") == tl.get("edl_fingerprint") \
                    and antigo.get("regra") == r and not faltando:
                print("já existe e descreve este corte (edl_fingerprint igual, mesma "
                      "régua, %d formato(s) no disco) — pulando"
                      % len(r.get("formatos") or ["srt"]), file=sys.stderr)
                print(alvo)
                return 0
        except (ValueError, OSError):
            pass

    try:
        caminhos, side, _ = gerar(d, regra=over, saida=saida,
                                  transcritos=transcritos, mapa_arq=mapa_arq,
                                  orto_arq=orto_arq, alinhamento=align,
                                  perfil_off=perfil_off)
    except (palavras_mod.ErroPublicacao, palavras_mod.ErroPalavras) as e:
        print("ERRO: %s" % e, file=sys.stderr)
        return 2
    print("%d cues · %d palavras · cps p50 %.1f p95 %.1f · %d acima do teto · "
          "%d abaixo de dur_min · %d sobreposições clampadas (máx %.0f ms)"
          % (side["cues"], side["palavras"], side["cps_p50"], side["cps_p95"],
             side["cps_excedidos"], side["dur_min_violada"],
             side["sobreposicoes_clampadas"], side["sobreposicao_max_ms"]),
          file=sys.stderr)
    for p in caminhos[1:]:
        print("  + %s" % p, file=sys.stderr)
    print(caminhos[0])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
