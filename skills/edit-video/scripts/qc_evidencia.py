#!/usr/bin/env python3
"""Politica de severidade para evidencias de emenda.

Energia sozinha e um detector, nao um veredito. Vazamento confirmado pelo
contexto lexical ou segmento mudo continuam sendo falhas duras.
"""

from __future__ import annotations

import asr_compare


FALHAS_DURAS = ("VAZA-PROX", "SEM PALAVRAS e sem energia")
ALERTAS = ("CLIP-FIM", "CLIP-INICIO", "SEM PALAVRAS mas COM ENERGIA")


def classificar(flags: list[str]) -> dict:
    duras = [f for f in flags if f.startswith(FALHAS_DURAS)]
    alertas = [f for f in flags if f.startswith(ALERTAS)]
    outras = [f for f in flags if f not in duras and f not in alertas]
    return {
        "estado": "falha" if duras else ("revisao" if alertas or outras else "aprovado"),
        "falhas": duras,
        "alertas": alertas + outras,
    }


def vazamentos_apos_fala(fala: str, palavras: list[tuple], fim_corte: float) -> list[tuple]:
    """Palavras posteriores ao fim lexical esperado que ainda entram no corte.

    `palavras` contem tuplas `(start, end, texto)` já sobrepostas ao segmento.
    Escolhemos a ocorrência que melhor casa o sufixo completo de `fala`, não a
    última palavra sobreposta. Assim a palavra vazada não vira parte do esperado
    por construção, que era o falso verde anterior.
    """
    esperado = asr_compare.tokens(fala)
    ouvidas = []
    for _ini, _fim, texto in palavras:
        ts = asr_compare.tokens(texto)
        ouvidas.append(ts[0] if ts else "")
    if not esperado or not ouvidas:
        return []
    candidatos = []
    for i, palavra in enumerate(ouvidas):
        if palavra != esperado[-1]:
            continue
        pontos = 0
        a, e = i, len(esperado) - 1
        while a >= 0 and e >= 0 and ouvidas[a] == esperado[e]:
            pontos += 1
            a -= 1
            e -= 1
        candidatos.append((pontos, -i, i))
    if not candidatos:
        return []
    _pontos, _menos_i, limite = max(candidatos)
    return [p for p in palavras[limite + 1:] if float(p[0]) < float(fim_corte) - 0.02]
