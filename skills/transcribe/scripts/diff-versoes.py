#!/usr/bin/env python3
"""diff-versoes — alinha duas versões da MESMA peça e mostra o que mudou.

Quando um anunciante mantém duas versões de uma VSL no ar (um A/B vivo, ou a
versão nova no tráfego pago e a velha na bio), o diff entre elas é a evidência
mais limpa que existe do que ele considera resolvido e do que ele acha que é o
gargalo. O que sobrevive vale mais que o que saiu.

Alinha por SENTENÇA (não por parágrafo): o corte real costuma ser cirúrgico e
some se a unidade for grande demais.

⚠️ O modo sentença tem um falso positivo conhecido: quando o ASR quebra a MESMA
fala em pontos diferentes nas duas versões, o diff acusa "trocado" sem que uma
palavra tenha mudado. Em VSL isso é a maioria do ruído. Use --palavras para
comparar o fluxo de palavras e ver só a divergência real.

Uso:
    diff-versoes.py <dirA> <dirB> [--min-bloco 2] [--palavras]

Cada dir precisa ter transcript.json (dump do Deepgram).
Saída em stdout: ponto de divergência, blocos trocados com timestamp dos dois lados.
"""
import argparse
import difflib
import json
import os
import re
import sys

NORM = re.compile(r"[^a-z0-9áàâãéêíóôõúüç ]")


def mmss(s):
    s = int(round(s or 0))
    return f"{s//60:02d}:{s%60:02d}"


def sentencas(path):
    """[(start, end, texto), ...] por sentença do Deepgram."""
    with open(path) as fh:
        j = json.load(fh)
    alt = j["results"]["channels"][0]["alternatives"][0]
    out = []
    for p in (alt.get("paragraphs") or {}).get("paragraphs") or []:
        for s in p.get("sentences", []):
            if s.get("text", "").strip():
                out.append((s["start"], s["end"], s["text"].strip()))
    if not out:  # fallback
        for u in j["results"].get("utterances") or []:
            out.append((u["start"], u["end"], u["transcript"].strip()))
    return out


def chave(t):
    return NORM.sub("", t.lower()).strip()


def palavras(path):
    """[(start, end, palavra), ...] — unidade fina, imune a quebra de sentença."""
    with open(path) as fh:
        j = json.load(fh)
    alt = j["results"]["channels"][0]["alternatives"][0]
    out = []
    for w in alt.get("words") or []:
        t = (w.get("punctuated_word") or w.get("word") or "").strip()
        if t:
            out.append((w["start"], w["end"], t))
    return out


def diff_palavras(pa, pb, min_bloco):
    A, B = palavras(pa), palavras(pb)
    ka = [NORM.sub("", w.lower()) for _, _, w in A]
    kb = [NORM.sub("", w.lower()) for _, _, w in B]
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)

    print(f"A: {os.path.basename(os.path.dirname(pa))}  {len(A)} palavras ({mmss(A[-1][1])})")
    print(f"B: {os.path.basename(os.path.dirname(pb))}  {len(B)} palavras ({mmss(B[-1][1])})")
    print(f"similaridade (palavra a palavra): {sm.ratio()*100:.1f}%\n")

    blocos = [op for op in sm.get_opcodes()
              if op[0] != "equal" and max(op[2] - op[1], op[4] - op[3]) >= min_bloco]
    if not blocos:
        print(f"→ nenhuma divergência com {min_bloco}+ palavras: são a mesma fala.")
        return

    maior = max((op for op in sm.get_opcodes() if op[0] == "equal"),
                key=lambda o: o[2] - o[1], default=None)
    if maior:
        _, i1, i2, j1, j2 = maior
        print(f"→ maior trecho idêntico: {i2-i1} palavras · "
              f"A {mmss(A[i1][0])}–{mmss(A[i2-1][1])} · B {mmss(B[j1][0])}–{mmss(B[j2-1][1])}")
    tot = sum(max(o[2]-o[1], o[4]-o[3]) for o in blocos)
    print(f"→ {len(blocos)} trechos divergentes de {min_bloco}+ palavras "
          f"({tot} palavras no total)\n")
    print("=" * 78)
    for tag, i1, i2, j1, j2 in blocos:
        rot = {"replace": "TROCADO", "delete": "SÓ EM A", "insert": "SÓ EM B"}[tag]
        ta = mmss(A[i1][0]) if i1 < len(A) else "—"
        tb = mmss(B[j1][0]) if j1 < len(B) else "—"
        print(f"\n### {rot}   A@{ta}  B@{tb}   ({i2-i1}→{j2-j1} palavras)")
        if i2 > i1:
            print("  A− " + " ".join(w for _, _, w in A[i1:i2]))
        if j2 > j1:
            print("  B+ " + " ".join(w for _, _, w in B[j1:j2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirA")
    ap.add_argument("dirB")
    ap.add_argument("--min-bloco", type=int, default=1,
                    help="ignora trechos trocados menores que N sentenças (ou palavras, com --palavras)")
    ap.add_argument("--palavras", action="store_true",
                    help="compara o fluxo de palavras — imune a quebra de sentença do ASR")
    ap.add_argument("--contexto", type=int, default=1)
    a = ap.parse_args()

    pa = a.dirA if a.dirA.endswith(".json") else os.path.join(a.dirA, "transcript.json")
    pb = a.dirB if a.dirB.endswith(".json") else os.path.join(a.dirB, "transcript.json")
    for p in (pa, pb):
        if not os.path.exists(p):
            sys.exit(f"nao achei: {p}")

    if a.palavras:
        diff_palavras(pa, pb, max(a.min_bloco, 1))
        return

    A, B = sentencas(pa), sentencas(pb)
    ka, kb = [chave(t) for _, _, t in A], [chave(t) for _, _, t in B]

    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    ops = sm.get_opcodes()

    iguais = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
    print(f"A: {os.path.basename(os.path.dirname(pa))}  {len(A)} sentenças "
          f"({mmss(A[-1][1])})")
    print(f"B: {os.path.basename(os.path.dirname(pb))}  {len(B)} sentenças "
          f"({mmss(B[-1][1])})")
    print(f"similaridade: {sm.ratio()*100:.1f}%  ·  {iguais} sentenças idênticas "
          f"({iguais/max(len(A),1)*100:.0f}% de A)\n")

    # primeiro ponto em que as duas divergem
    prim = next((op for op in ops if op[0] != "equal"), None)
    if prim:
        tag, i1, i2, j1, j2 = prim
        ta = A[i1][0] if i1 < len(A) else None
        tb = B[j1][0] if j1 < len(B) else None
        print(f"→ primeira divergência: A em {mmss(ta)} · B em {mmss(tb)}\n")
    else:
        print("→ as duas são idênticas palavra a palavra\n")
        return

    # maior bloco contínuo idêntico (o "corpo comum")
    maior = max((op for op in ops if op[0] == "equal"),
                key=lambda o: o[2] - o[1], default=None)
    if maior:
        _, i1, i2, j1, j2 = maior
        print(f"→ maior trecho idêntico: {i2-i1} sentenças · "
              f"A {mmss(A[i1][0])}–{mmss(A[i2-1][1])} · "
              f"B {mmss(B[j1][0])}–{mmss(B[j2-1][1])}\n")

    print("=" * 78)
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if max(i2 - i1, j2 - j1) < a.min_bloco:
            continue
        rot = {"replace": "TROCADO", "delete": "SÓ EM A", "insert": "SÓ EM B"}[tag]
        ta = mmss(A[i1][0]) if i1 < len(A) else "—"
        tb = mmss(B[j1][0]) if j1 < len(B) else "—"
        print(f"\n### {rot}   A@{ta}  B@{tb}")
        for _, _, t in A[i1:i2]:
            print(f"  A− {t}")
        for _, _, t in B[j1:j2]:
            print(f"  B+ {t}")


if __name__ == "__main__":
    main()
