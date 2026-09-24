#!/usr/bin/env python3
"""largura-fonte.py — tabela de advance widths de uma Google Font (SPEC-13 §3.6).

Grava `src/data/larguras/<Familia>-<peso>[-italic].json`, contrato
`benchmark.larguras-fonte/v1`. É o MEDIDOR de fora do browser: o `measureText` do
`@remotion/layout-utils` só roda no Chrome (`dist/cjs/layouts/measure-text.js`
lança `'measureText() can only be called in a browser.'` quando
`typeof document === 'undefined'`), e sem uma tabela o agrupamento por largura
não teria como ser testado em Node nem em Python.

    largura-fonte.py --familia Montserrat --peso 700
    largura-fonte.py --familia "Playfair Display" --peso 700 --italico
    largura-fonte.py --familia Anton --peso 400 --saida /outro/lugar

stdout = caminho do artefato · stderr = o que foi conferido.

O QUE ESTA TABELA NÃO TEM, e por que isso é honesto
---------------------------------------------------
1. **Kerning (GPOS).** A soma de advances ignora o par kerning. A divergência
   contra o `measureText` do Chrome é o critério de aceite nº 6 da SPEC-13 e é
   [verif] — exige render. Enquanto não for medida, `correcao` fica `null` e o
   consumidor multiplica por 1,0. `null` quer dizer "não medido", não "1,0
   confirmado": não troque por 1.0 sem rodar o critério 6.
2. **Ligaduras e shaping.** Mesma razão.
3. **Fallback de fonte.** Codepoint fora do `cmap` cai em `fallback`, que é
   medido (ver `fallback_origem`), não chutado.

⚠️ WOFF2 NÃO ABRE nesta máquina: o decodificador do fontTools exige o módulo
`brotli`, que não está instalado e o `pip3 --user` está bloqueado por PEP 668.
Por isso a fonte vem do `.ttf` estático que a CSS API do Google devolve para um
User-Agent antigo — não do `.woff2` que o `@remotion/google-fonts` embarca.

PRODUTO, NÃO INSTALAÇÃO: este script conhece dois caminhos — o dele próprio e o
`--saida`. Nada de `creators/`, nada absoluto.
"""
import argparse
import json
import os
import re
import statistics
import sys
import urllib.request

CONTRATO = "benchmark.larguras-fonte/v1"
CSS_API = "https://fonts.googleapis.com/css?family="
# UA antigo: é o que faz a CSS API do Google devolver `format('truetype')` em vez
# de woff2. Trocar por um UA moderno devolve .woff2 e o fontTools não abre (ver
# docstring).
UA_TTF = "Mozilla/4.0"

DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))
DIR_SAIDA_PADRAO = os.path.join(DIR_SCRIPT, "..", "src", "data", "larguras")


def _baixar(url, ua=UA_TTF):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _css_query(familia, peso, italico):
    """`Playfair Display` + 700 + italic → `Playfair+Display:700italic`."""
    q = familia.replace(" ", "+")
    if italico:
        return "%s:%ditalic" % (q, peso)
    return "%s:%d" % (q, peso) if peso != 400 else q


def _face(css, peso, italico):
    """Acha o @font-face que casa com estilo E peso pedidos, e devolve a URL .ttf.

    Conferir o bloco importa: a CSS API silenciosamente devolve o peso mais
    próximo quando o pedido não existe. Medir 600 achando que é 700 dá uma tabela
    errada que nada acusa depois."""
    blocos = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
    estilo_quer = "italic" if italico else "normal"
    for b in blocos:
        m_st = re.search(r"font-style:\s*([a-z]+)", b)
        m_wt = re.search(r"font-weight:\s*(\d+)", b)
        m_url = re.search(r"url\((https://[^)]*\.ttf)\)", b)
        if not (m_st and m_wt and m_url):
            continue
        if m_st.group(1) == estilo_quer and int(m_wt.group(1)) == peso:
            return m_url.group(1)
    achados = [(re.search(r"font-style:\s*([a-z]+)", b), re.search(r"font-weight:\s*(\d+)", b))
               for b in blocos]
    resumo = ", ".join("%s/%s" % (s.group(1) if s else "?", w.group(1) if w else "?")
                       for s, w in achados) or "(nenhum @font-face)"
    raise SystemExit("erro: a CSS API não devolveu %s %d; devolveu: %s"
                     % (estilo_quer, peso, resumo))


def tabela(familia, peso, italico):
    from fontTools.ttLib import TTFont
    import io

    css = _baixar(CSS_API + _css_query(familia, peso, italico)).decode("utf-8")
    url = _face(css, peso, italico)
    print("ttf: %s" % url, file=sys.stderr)
    tt = TTFont(io.BytesIO(_baixar(url)), lazy=True)

    upem = tt["head"].unitsPerEm
    usw = tt["OS/2"].usWeightClass
    tem_fvar = "fvar" in tt
    print("unitsPerEm=%d  OS/2.usWeightClass=%d  fvar=%s"
          % (upem, usw, "SIM" if tem_fvar else "nao"), file=sys.stderr)
    # ⚠️ O gate do §6 passo 2 da spec: usWeightClass TEM que bater com o peso
    # pedido. Sem isto, medir "Montserrat 700" e receber 400 passa em silêncio.
    if usw != peso:
        raise SystemExit("erro: OS/2.usWeightClass=%d != peso pedido %d — a CSS API "
                         "entregou outro corte" % (usw, peso))
    if tem_fvar:
        raise SystemExit("erro: fonte variável (tem tabela fvar). A instância default "
                         "pode não ser o peso pedido; use o .ttf estático.")

    hmtx = tt["hmtx"]
    cmap = tt.getBestCmap()
    advance = {}
    for cp, glifo in cmap.items():
        try:
            advance[str(cp)] = int(hmtx[glifo][0])
        except KeyError:
            continue

    # `fallback`: largura de um codepoint fora do cmap. MEDIDA, não chutada — e o
    # arquivo registra de onde veio, porque as duas origens têm significados
    # diferentes (.notdef é o glifo que a própria fonte reserva; a mediana é uma
    # aproximação quando .notdef é zero-width).
    notdef = 0
    try:
        notdef = int(hmtx[".notdef"][0])
    except KeyError:
        pass
    if notdef > 0:
        fallback, origem = notdef, ".notdef"
    else:
        fallback, origem = int(round(statistics.median(advance.values()))), "mediana"

    return {
        "contrato": CONTRATO,
        "familia": familia,
        "peso": peso,
        "italico": bool(italico),
        "unitsPerEm": upem,
        "fonte": url,
        "kerning": False,
        "correcao": None,
        "fallback": fallback,
        "fallback_origem": origem,
        "advance": advance,
    }


def nome_arquivo(familia, peso, italico):
    return "%s-%d%s.json" % (familia.replace(" ", ""), peso, "-italic" if italico else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--familia", required=True)
    ap.add_argument("--peso", type=int, default=400)
    ap.add_argument("--italico", action="store_true")
    ap.add_argument("--saida", default=DIR_SAIDA_PADRAO)
    ap.add_argument("--forcar", action="store_true",
                    help="regrava mesmo se o arquivo já existe (default: idempotente)")
    a = ap.parse_args()

    # FRONTEIRA orientação 9: o diretório é criado pelo script. Não dependa de um
    # .gitkeep, que não sobrevive ao clone quando o conteúdo é ignorado.
    os.makedirs(a.saida, exist_ok=True)
    destino = os.path.join(a.saida, nome_arquivo(a.familia, a.peso, a.italico))
    if os.path.exists(destino) and not a.forcar:
        print("já existe (use --forcar para regravar): %s" % destino, file=sys.stderr)
        print(os.path.abspath(destino))
        return 0

    t = tabela(a.familia, a.peso, a.italico)
    print("glifos com advance: %d  fallback=%d (%s)"
          % (len(t["advance"]), t["fallback"], t["fallback_origem"]), file=sys.stderr)
    tmp = destino + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(t, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        fh.write("\n")
    os.replace(tmp, destino)
    print(os.path.abspath(destino))
    return 0


if __name__ == "__main__":
    sys.exit(main())
