#!/usr/bin/env python3
"""complexidade — o índice de complexidade (IC) de uma edição, 0 a 100.

"Edição simples" e "edição complexa" viram um número com escala declarada, em vez
de adjetivo. Cinco componentes, cada um saturando numa âncora; a soma ponderada é
o IC. As faixas: enxuto < 30 · médio 30–59 · denso >= 60.

⚠️ IC é ORDINAL DENTRO DE UMA ESCALA. Dois estilos só são comparáveis se a
`versao_escala` bate. Não existe "esta edição é 44% complexa".

A escala (âncoras, pesos, faixas) mora em UM lugar só: o bloco
`x_escala_complexidade` de `references/_schema.json`. Este script LÊ de lá — não
tem número de escala no fonte. É a lição do ACHADOS-DO-CODIGO §3.4 (bordas.py
tinha 0.02/0.06 e a doc afirmava 0.12/0.20 — divergência doc↔código que obrigou
a congelar o valor do código).

Uso:
    complexidade.py <medicao.json|estilo.json> [--json]
    complexidade.py --avulso --elem10s 7.4 --simultaneos 3 --recursos 8 \
                    --cortes-min 5.1 --texto-pct 34.1 [--json]

Saída: IC, faixa, os 5 componentes saturados e as entradas que os produziram.
Se QUALQUER componente falta, `ic` sai `null` e `componentes_faltando` nomeia
quais — renormalizar peso em silêncio seria concluir com amostra parcial, que é
a armadilha mais cara deste repo.

exit 0 ok · 2 erro de uso
"""
import argparse
import json
import os
import sys

AQUI = os.path.dirname(os.path.realpath(__file__))
SCHEMA = os.path.join(os.path.dirname(AQUI), "references", "_schema.json")


def carregar_escala(caminho=SCHEMA):
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)["x_escala_complexidade"]


def faixa_de(ic, escala):
    for f in escala["faixas"]:
        if ic < f["max"]:
            return f["nome"]
    return escala["faixas"][-1]["nome"]


def calcular(entradas, escala=None):
    """entradas: {campo: valor|None} com os 5 campos da escala.

    Devolve {versao_escala, ic, faixa, componentes, entradas, componentes_faltando}.
    """
    escala = escala or carregar_escala()
    comp, faltando, total = {}, [], 0.0
    for nome, cfg in escala["componentes"].items():
        x = entradas.get(cfg["campo"])
        if x is None:
            faltando.append(nome)
            comp[nome] = None
            continue
        s = min(1.0, max(0.0, float(x) / cfg["ancora"]))
        comp[nome] = round(s, 4)
        total += cfg["peso"] * s
    ic = None if faltando else int(round(100 * total))
    return {
        "versao_escala": escala["versao"],
        "ic": ic,
        "faixa": None if ic is None else faixa_de(ic, escala),
        "componentes": comp,
        "componentes_faltando": faltando,
        "entradas": {k: entradas.get(k) for cfg in escala["componentes"].values()
                     for k in [cfg["campo"]]},
    }


# --------------------------------------------------------------- extratores
def de_medicao(med):
    """Entradas do IC a partir de um benchmark.medicao-ref/v1."""
    m = med.get("medido", {})
    g, mo, le = m.get("grafismo", {}), m.get("montagem", {}), m.get("legenda", {})
    rec = g.get("recursos")
    return {
        "elementos_por_10s": g.get("elementos_por_10s"),
        "max_simultaneos": g.get("max_simultaneos"),
        "recursos_distintos": None if rec is None else len(rec),
        "cortes_por_min": mo.get("cortes_por_min"),
        "texto_fracao": (None if le.get("presente_pct_do_tempo") is None
                         else le["presente_pct_do_tempo"] / 100.0),
    }


def _v(eixos, grupo, chave):
    p = (eixos.get(grupo) or {}).get(chave)
    return p.get("v") if isinstance(p, dict) else None


def de_estilo(est):
    """Entradas do IC a partir de um benchmark.estilo-edicao/v1 (os `v` dos Param)."""
    eixos = est.get("eixos", {})
    rec = _v(eixos, "grafismo", "recursos")
    texto = _v(eixos, "legenda", "presente_pct")
    return {
        "elementos_por_10s": _v(eixos, "grafismo", "elementos_por_10s"),
        "max_simultaneos": _v(eixos, "grafismo", "max_simultaneos"),
        "recursos_distintos": None if rec is None else len(rec),
        "cortes_por_min": _v(eixos, "montagem", "cortes_por_min"),
        "texto_fracao": None if texto is None else texto / 100.0,
    }


def de_arquivo(caminho):
    with open(caminho, encoding="utf-8") as fh:
        d = json.load(fh)
    c = d.get("contrato", "")
    if c.startswith("benchmark.medicao-ref"):
        return calcular(de_medicao(d)), "medicao"
    if c.startswith("benchmark.estilo-edicao"):
        return calcular(de_estilo(d)), "estilo"
    sys.exit(f"contrato desconhecido em {caminho}: {c!r}")


# ---------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("arquivo", nargs="?")
    ap.add_argument("--avulso", action="store_true",
                    help="calcula a partir dos 5 números na linha de comando")
    ap.add_argument("--elem10s", type=float)
    ap.add_argument("--simultaneos", type=float)
    ap.add_argument("--recursos", type=float)
    ap.add_argument("--cortes-min", type=float, dest="cortes_min")
    ap.add_argument("--texto-pct", type=float, dest="texto_pct")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.avulso:
        r = calcular({
            "elementos_por_10s": a.elem10s,
            "max_simultaneos": a.simultaneos,
            "recursos_distintos": a.recursos,
            "cortes_por_min": a.cortes_min,
            "texto_fracao": None if a.texto_pct is None else a.texto_pct / 100.0,
        })
        origem = "avulso"
    elif a.arquivo:
        r, origem = de_arquivo(a.arquivo)
    else:
        ap.error("passe um arquivo ou --avulso com os 5 números")
        return

    if a.json:
        print(json.dumps(r, ensure_ascii=False))
        return

    print(f"IC {r['ic'] if r['ic'] is not None else '—'}"
          f"  ({r['faixa'] or 'indefinido'})  escala v{r['versao_escala']}  [{origem}]")
    escala = carregar_escala()
    for nome, cfg in escala["componentes"].items():
        s = r["componentes"][nome]
        x = r["entradas"].get(cfg["campo"])
        barra = "" if s is None else "█" * int(round(s * 20))
        print(f"  {nome:<11} peso {cfg['peso']:.2f}  x={x if x is not None else '—':<8}"
              f" /{cfg['ancora']:<5} s={s if s is not None else '—':<7} {barra}")
    if r["componentes_faltando"]:
        print("  ⚠️ sem IC: falta " + ", ".join(r["componentes_faltando"]))


if __name__ == "__main__":
    main()
