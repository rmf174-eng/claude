#!/usr/bin/env python3
"""QC DO RESPIRO: a inspiração audível que passa por TODOS os outros (SPEC-48).

Uso: qc-respiro.py <dir-producao> [--floor-baixo -58] [--floor-alto -40]
                                  [--min-ms 150] [--controle]
     stdout: nada (é QC)   ·   stderr: varredura + achados
     0  nenhum respiro sobrando
     1  ACHOU respiro (é DETECTOR: aponta onde ouvir, não bloqueia) — e no
        `--controle` acusar é o resultado ESPERADO
     2  o `--controle` não acusou o defeito plantado, ou acusou fala: o defeito
        está no QC
     3  medição inválida (sem EDL legível, sem transcript, sem áudio)

🔴 POR QUE ELE EXISTE — E POR QUE NENHUM DOS OUTROS 20 O SUBSTITUI

Achado A-4 do teste de campo da v0.12 (2026-08-12), e achado **DE OUVIDO pelo
creator**, não por medição: entre "coletivo." e "uma" ficaram ~300 ms de
inspiração a ~−46 dB. A peça foi entregue com seis verificações verdes em cima
daquilo.

O motivo é aritmético, e é a razão de este arquivo existir:

    piso de silêncio da casa   −52 dB     ← o respiro está ACIMA: não é cauda
    a inspiração medida        −46 dB
    fala normal                −20 dB     ← o respiro está ABAIXO: não é fala

Ele mora na FAIXA CEGA entre os dois limiares. `qc-cauda` procura silêncio e não
o vê (o nível está alto demais); `audit-emendas` e `qc-ataque` procuram fala e não
o veem (baixo demais); `qc-emendas-asr` procura PALAVRA e ali não há nenhuma; o
`bordas.py` corta pelo envelope e o considera "conteúdo".

A ASSINATURA, então, é a própria faixa: **banda sustentada** entre −58 e −40 dB,
por 150 ms ou mais, **com silêncio de um lado** (é o que separa respiro de sala
constante: ruído de ar-condicionado não tem borda), e que **não coincide com
palavra do ASR** (o que coincide é fala fraca — final de frase, sussurro — e essa
é decisão editorial, não defeito).

⚠️ ISTO É UM DETECTOR, NÃO CONVERGÊNCIA. Ele nunca vai a zero: respirar é o que
uma pessoa faz. Perseguir o número dele até zero corta fala. O veredito é a
orelha de quem aprova; este script diz ONDE ouvir, com o timestamp.

🦷 `--controle` planta uma banda de 300 ms a −46 dB numa região silenciosa e
EXIGE que ela seja acusada — e, no mesmo passe, exige que NENHUM trecho com
palavra do ASR seja acusado. Um detector que acusa fala é pior que nenhum.
"""
import importlib.util
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
import bordas                 # noqa: E402
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

_esp = importlib.util.spec_from_file_location(
    "palavras", os.path.join(_AQUI, "palavras.py"))
palavras = importlib.util.module_from_spec(_esp)
_esp.loader.exec_module(palavras)

# ─────────────────────────────────────────────────────────────────────── FÍSICA
# Estes números descrevem a ASSINATURA ACÚSTICA de uma inspiração, não o formato
# da peça (SPEC-00 / RD-5): eles não mudam com resolução, fps ou aspecto.
#
# −58 / −40 dB: a faixa medida no A-4 (300 ms a ~−46 dB), alargada para os dois
# lados até encostar no piso de silêncio da casa (−52) e ficar bem abaixo da fala
# (−20). O intervalo COBRE o piso de propósito: um respiro de 6 dB acima do piso
# é audível, e é justamente o que o QC de cauda descarta.
FLOOR_BAIXO = -58.0
FLOOR_ALTO = -40.0
# 150 ms: abaixo disso a banda é transiente (clique de boca, roupa, um passo).
# A inspiração medida tinha 300 ms; 150 dá metade de folga.
MIN_MS = 150.0
# a borda de silêncio: quanto tem que cair, e por quanto tempo, de um dos lados.
BORDA_MS = 60.0
BORDA_QUEDA_DB = 4.0
# 🔴 O `end` DO ASR NÃO É O FIM DO SOM (A-4b, e foi o controle deste QC que me
# obrigou a implementar isto). O Deepgram marcou o fim de "coletivo." **450 ms
# depois** do fim acústico real: o timestamp caiu DENTRO da inspiração. Se a
# coincidência com palavra usar o `end` cru, o respiro fica escondido justamente
# no caso que motivou este script — a palavra "cobre" o defeito.
#
# Então a régua de fim é ACÚSTICA: caminha para trás a partir do `end` do ASR
# enquanto o envelope estiver ABAIXO do nível de fala (`FLOOR_ALTO`), e o fim real
# é a última janela que passou dele. Mesma família do `bordas.decay`, mesma
# unidade, mesmo envelope — e uma tolerância simétrica não resolveria: o erro do
# ASR aqui é assimétrico por construção (ele atrasa o fim, não o adianta).
#
# Medido no controle: com tolerância de 150 ms, a banda plantada 100 ms depois da
# palavra era DESCARTADA como fala e o controle reprovava o QC (0 de 2). Com a
# régua acústica, 2 de 2.
TOL_PALAVRA_S = 0.0


def _runs(mascara):
    """Índices [i, j) de cada corrida contígua de True."""
    saida, i = [], None
    for k, v in enumerate(mascara):
        if v and i is None:
            i = k
        elif not v and i is not None:
            saida.append((i, k))
            i = None
    if i is not None:
        saida.append((i, len(mascara)))
    return saida


def achar_respiros(db, t0, t1, win, baixo=FLOOR_BAIXO, alto=FLOOR_ALTO,
                   min_ms=MIN_MS):
    """As bandas sustentadas na faixa cega dentro de [t0, t1), em segundos."""
    i0, i1 = max(0, int(t0 / win)), min(len(db), int(t1 / win))
    if i1 - i0 < 2:
        return []
    trecho = db[i0:i1]
    na_faixa = (trecho >= baixo) & (trecho <= alto)
    minimo = max(1, int(round((min_ms / 1000.0) / win)))
    achados = []
    for a, b in _runs(na_faixa):
        if b - a < minimo:
            continue
        # a borda de silêncio: um dos lados tem que CAIR, e não só ser menor
        n_borda = max(1, int(round((BORDA_MS / 1000.0) / win)))
        nivel = float(trecho[a:b].mean())
        antes = trecho[max(0, a - n_borda):a]
        depois = trecho[b:b + n_borda]
        cai_antes = antes.size and float(antes.max()) < nivel - BORDA_QUEDA_DB
        cai_depois = depois.size and float(depois.max()) < nivel - BORDA_QUEDA_DB
        # nas pontas do segmento o lado que falta conta como silêncio: o corte
        # ESTÁ ali, e é exatamente onde o respiro fica exposto
        if a == 0:
            cai_antes = True
        if b == len(trecho):
            cai_depois = True
        if not (cai_antes or cai_depois):
            continue
        achados.append({"ini": t0 + a * win, "fim": t0 + b * win,
                        "dur_ms": (b - a) * win * 1000.0,
                        "nivel_db": nivel,
                        "borda": "antes" if cai_antes else "depois"})
    return achados


def fim_acustico(db, ini, fim, win, alto=FLOOR_ALTO):
    """O fim REAL da fala: recua do `end` do ASR enquanto o envelope não é fala.

    Devolve `fim` quando a última janela já é fala (o caso normal) e um instante
    ANTERIOR quando o ASR passou do ponto — o erro de até 450 ms do A-4b. Nunca
    recua além de `ini`: uma palavra não pode ter duração negativa."""
    i0, i1 = max(0, int(ini / win)), min(len(db), int(fim / win))
    k = i1
    while k > i0 and float(db[k - 1]) < alto:
        k -= 1
    return max(ini, k * win)


def coincide_com_palavra(a, ws, db=None, win=None, tol=TOL_PALAVRA_S):
    """A banda cai dentro de alguma palavra do ASR — com o fim ACÚSTICO dela?"""
    for ini, fim, _w in ws:
        fim_real = fim if db is None else fim_acustico(db, ini, fim, win)
        if a["fim"] > ini - tol and a["ini"] < fim_real + tol:
            return True
    return False


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    args = sys.argv[2:]

    def opt(nome, default):
        return float(args[args.index(nome) + 1]) if nome in args else default

    controle = "--controle" in args
    baixo = opt("--floor-baixo", FLOOR_BAIXO)
    alto = opt("--floor-alto", FLOOR_ALTO)
    min_ms = opt("--min-ms", MIN_MS)

    P = perfil_mod.carregar(d, quieto=True)
    SR = int(P["audio"]["sr"])
    try:
        edl = edl_io.segmentos(d)
    except SystemExit:
        print("MEDIÇÃO INVÁLIDA: EDL ilegível em %s" % d, file=sys.stderr)
        return 3
    if not edl:
        print("MEDIÇÃO INVÁLIDA: EDL sem segmentos", file=sys.stderr)
        return 3

    srcs = sorted({s["src"] for s in edl})
    try:
        mapa, _como = palavras.resolver_transcritos(d, srcs)
    except Exception as e:                                     # noqa: BLE001
        print("MEDIÇÃO INVÁLIDA: sem transcript para casar os achados com fala "
              "(%s). Um respiro que coincide com palavra é fala fraca, não "
              "defeito — sem o ASR este QC só sabe gritar." % str(e)[:120],
              file=sys.stderr)
        return 3

    cwd = os.getcwd()
    os.chdir(d)
    try:
        words = {}
        for src in srcs:
            import json
            tr = json.load(open(os.path.relpath(mapa[src], d)
                                if os.path.isabs(mapa[src]) else mapa[src]))
            words[src] = [(w["start"], w["end"], w["word"]) for w in
                          tr["results"]["channels"][0]["alternatives"][0]["words"]]

        cache = {}
        for s in edl:
            bordas.envelope(s["src"], cache, SR)

        plantados = []
        if controle:
            # 🦷 planta a banda NUMA REGIÃO SILENCIOSA de cada segmento: procura a
            # corrida de silêncio mais longa dentro da janela e escreve −46 dB por
            # 300 ms nela. Plantar sobre fala mediria outra coisa.
            for k, s in enumerate(edl):
                db = cache[s["src"]]
                i0, i1 = int(s["start"] / bordas.WIN), int(s["end"] / bordas.WIN)
                trecho = db[i0:i1]
                mudo = trecho < baixo
                corridas = sorted(_runs(mudo), key=lambda ab: ab[0] - ab[1])
                if not corridas:
                    continue
                a, b = corridas[0]
                n = int((0.300 / bordas.WIN))
                if b - a < n + 4:
                    continue
                meio = a + (b - a - n) // 2
                db[i0 + meio:i0 + meio + n] = -46.0
                plantados.append((k, (i0 + meio) * bordas.WIN,
                                  (i0 + meio + n) * bordas.WIN))

        n_janelas = 0
        achados = []
        for k, s in enumerate(edl):
            db = cache[s["src"]]
            n_janelas += max(0, int(s["end"] / bordas.WIN)
                             - int(s["start"] / bordas.WIN))
            for a in achar_respiros(db, s["start"], s["end"], bordas.WIN,
                                    baixo, alto, min_ms):
                a["seg"] = k
                a["beat"] = str(s.get("beat", "?"))[:14]
                a["fala"] = coincide_com_palavra(a, words.get(s["src"], []),
                                                 db, bordas.WIN)
                achados.append(a)

        # ⚠️ o formato desta linha é lido pelo adaptador `qc_respiro` do qc.py.
        print("varredura: %d segmento(s), %d janela(s) de envelope de %.0f ms, "
              "%d bruto(s)%s"
              % (len(edl), n_janelas, bordas.WIN * 1000, len(cache),
                 "  [CONTROLE: %d banda(s) de 300 ms a −46 dB plantada(s)]"
                 % len(plantados) if controle else ""), file=sys.stderr)
        print("faixa cega: %.0f a %.0f dB · mínimo %.0f ms · borda %.0f ms com "
              "queda de %.0f dB" % (baixo, alto, min_ms, BORDA_MS, BORDA_QUEDA_DB),
              file=sys.stderr)

        sobrando = [a for a in achados if not a["fala"]]
        com_fala = [a for a in achados if a["fala"]]
        for a in sorted(sobrando, key=lambda x: -x["dur_ms"])[:8]:
            print("   ↳ seg%02d %-14s %7.3f-%7.3f  respiro %.0f ms a %.0f dB "
                  "(silêncio %s)"
                  % (a["seg"], a["beat"], a["ini"], a["fim"], a["dur_ms"],
                     a["nivel_db"], a["borda"]), file=sys.stderr)
        print("respiro: %d banda(s) na faixa cega · %d SOBRANDO · %d descartada(s) "
              "por coincidir com palavra do ASR"
              % (len(achados), len(sobrando), len(com_fala)), file=sys.stderr)

        if controle:
            # o defeito plantado tem que aparecer, e fala não pode ser acusada
            pegos = 0
            for k, t0, t1 in plantados:
                if any(a["seg"] == k and a["ini"] <= t1 and a["fim"] >= t0
                       for a in sobrando):
                    pegos += 1
            acusou_fala = len([a for a in sobrando if a["fala"]])
            print("CONTROLE: %d de %d banda(s) plantada(s) acusada(s) · "
                  "%d achado(s) sobre palavra do ASR"
                  % (pegos, len(plantados), acusou_fala), file=sys.stderr)
            if not plantados:
                print("🔴 CONTROLE INVÁLIDO: não achei silêncio longo o bastante "
                      "para plantar. Sem defeito plantado não há prova de dentes.",
                      file=sys.stderr)
                return 2
            if pegos < len(plantados) or acusou_fala:
                print("🔴 CONTROLE FALHOU: o defeito plantado não foi acusado (ou "
                      "fala foi). O defeito está no QC, não na peça.",
                      file=sys.stderr)
                return 2
            print("CONTROLE OK: o QC tem dentes.", file=sys.stderr)
            return 1
        return 1 if sobrando else 0
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(main())
