#!/usr/bin/env python3
"""Confere o elo entre as entradas do catálogo de estilos e as fichas de modelagem.

    conferir-fichas.py [--catalogo <catalogo.json>] [--fichas <dir>] [--json]

Uma entrada do catálogo pode declarar, em `medido.ficha`, o NOME do arquivo da
modelagem que a originou. Esse nome viaja no produto, então é um rótulo anônimo —
e o de-para para o arquivo real vive na instância de quem modelou
(`<fichas>/_catalogo-fichas.json`).

🔴 O DEFEITO QUE ISTO PEGA (achado do exame de UX/estilo, 2026-08-11): as três
constantes de ficha do catálogo apontavam para nomes que não existiam em lugar
nenhum — nem no produto (onde o campo é podado) nem na nossa instância (onde os
arquivos têm outros nomes). Ponteiro pendurado dos dois lados, e nenhum portão o
enxergava: o de doc varre `.md`, o de referências varre link e import, e este é
um valor de string dentro de um `.ts`.

🔴 A RÉGUA: sem `<fichas>/`, este comando sai **0 e em silêncio**. Um cliente não
tem `intelligence/` e não modelou ficha nenhuma; a ausência não é defeito. O que
é defeito é o catálogo prometer uma ficha que a instância não tem.

exit 0 = tudo que o catálogo promete resolve (ou não há o que conferir)
exit 1 = ficha prometida que não resolve, ou de-para apontando para o vazio
exit 2 = erro de uso (catálogo ilegível)
"""
import argparse
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))


def _ilha_home():
    return os.environ.get("ILHA_HOME") or os.path.dirname(os.path.dirname(
        os.path.dirname(AQUI)))


def catalogo_default():
    for c in (os.path.join(_ilha_home(), "tools", "remotion-compositor",
                           "catalogo", "catalogo.json"),
              os.path.join(os.getcwd(), "tools", "remotion-compositor",
                           "catalogo", "catalogo.json")):
        if os.path.isfile(c):
            return c
    return None


def fichas_default():
    return os.environ.get("BENCH_EDICAO_DIR") or os.path.join(
        os.getcwd(), "intelligence", "edicao")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogo", default=None)
    ap.add_argument("--fichas", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cat_path = a.catalogo or catalogo_default()
    if not cat_path or not os.path.isfile(cat_path):
        print("erro: catálogo não encontrado (--catalogo)", file=sys.stderr)
        return 2
    with open(cat_path, encoding="utf-8") as fh:
        cat = json.load(fh)

    prometidas = {}
    for e in cat.get("estilos") or []:
        f = (e.get("medido") or {}).get("ficha")
        if f:
            prometidas.setdefault(f, []).append(e["slug"])

    dir_fichas = a.fichas or fichas_default()
    if not os.path.isdir(dir_fichas):
        # silêncio: quem não modelou não tem o que conferir
        if a.json:
            print(json.dumps({"estado": "sem-instancia", "prometidas": len(prometidas)}))
        return 0

    depara_path = os.path.join(dir_fichas, "_catalogo-fichas.json")
    depara = {}
    if os.path.isfile(depara_path):
        # 🔴 O ÍNDICE MALFORMADO MORRIA EM TRACEBACK (achado A-F5, 2026-08-11).
        # Um `fichas` cujo valor é string em vez de objeto batia num
        # `AttributeError: 'str' object has no attribute 'get'` lá embaixo, no
        # laço — exit 1, sim, mas sem dizer QUAL arquivo nem O QUE está errado.
        # Este script é a única coisa que o cliente roda para saber se o elo
        # ficha↔catálogo está de pé; um stacktrace aqui manda ele ler o nosso
        # código para descobrir que faltou uma chave no JSON dele.
        try:
            with open(depara_path, encoding="utf-8") as fh:
                bruto = json.load(fh)
        except json.JSONDecodeError as erro:
            print("erro: %s não é JSON válido (linha %d, coluna %d): %s"
                  % (depara_path, erro.lineno, erro.colno, erro.msg),
                  file=sys.stderr)
            return 1
        if not isinstance(bruto, dict):
            print("erro: %s deveria ser um objeto com a chave `fichas`, e é %s"
                  % (depara_path, type(bruto).__name__), file=sys.stderr)
            return 1
        depara = bruto.get("fichas") or {}
        if not isinstance(depara, dict):
            print("erro: %s — `fichas` deveria ser um objeto "
                  "{rótulo: {\"arquivo\": \"...\"}}, e é %s"
                  % (depara_path, type(depara).__name__), file=sys.stderr)
            return 1
        malformados = [r for r, d in depara.items() if not isinstance(d, dict)]
        if malformados:
            print("erro: %s — %d rótulo(s) com valor que não é objeto: %s. "
                  "Cada entrada precisa ser {\"arquivo\": \"<nome>.md\"}, não "
                  "o nome solto." % (depara_path, len(malformados),
                                     ", ".join(sorted(malformados))),
                  file=sys.stderr)
            return 1

    problemas, ok = [], []
    for rotulo, slugs in sorted(prometidas.items()):
        # o rótulo pode ser o próprio nome do arquivo, ou passar pelo de-para
        real = (depara.get(rotulo) or {}).get("arquivo") or rotulo
        caminho = os.path.join(dir_fichas, os.path.basename(real))
        if os.path.isfile(caminho):
            ok.append((rotulo, real, slugs))
        else:
            problemas.append((rotulo, real, slugs,
                              "não existe em %s" % dir_fichas))

    # o outro sentido: de-para que aponta para arquivo inexistente, mesmo que o
    # catálogo não o cite — um índice que mente é pior que um índice ausente
    for rotulo, d in sorted(depara.items()):
        arq = d.get("arquivo")
        if arq and not os.path.isfile(os.path.join(dir_fichas, arq)):
            problemas.append((rotulo, arq, d.get("entradas") or [],
                              "de-para aponta para arquivo que não existe"))

    if a.json:
        print(json.dumps({"ok": [{"rotulo": r, "arquivo": f, "entradas": s} for r, f, s in ok],
                          "problemas": [{"rotulo": r, "arquivo": f, "entradas": s,
                                         "erro": m} for r, f, s, m in problemas]},
                         ensure_ascii=False, indent=1))
    else:
        for rotulo, real, slugs in ok:
            print("  ✓ %-22s → %-28s %d entrada(s)" % (rotulo, real, len(slugs)))
        for rotulo, real, slugs, motivo in problemas:
            print("  ✗ %-22s → %-28s %s" % (rotulo, real, motivo), file=sys.stderr)
        print("%d ficha(s) prometida(s) pelo catálogo · %d resolvem · %d não"
              % (len(prometidas), len(ok), len(problemas)), file=sys.stderr)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
