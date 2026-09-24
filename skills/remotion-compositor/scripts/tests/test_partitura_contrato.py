#!/usr/bin/env python3
"""O contrato de `paginas[].linhas` da partitura, contra quem o consome.

    python3 tests/test_partitura_contrato.py

🔴 O DEFEITO QUE ISTO TRAVA (medido em 2026-08-09)

`diretor-legenda.py` gravava `linhas` como `string[][]`:

    "linhas": [[t["text"] for t in ln] for ln in p["linhas"]]

e `CaptionLayer.tsx` faz `ln.map(pinta)` com

    const pinta = (tk: TikTokToken) => { … tk.fromMs … tk.toMs … {tk.text} }

Passando uma string, `tk.text` é `undefined` e o `<span>` renderiza NADA. Não é
erro, não é exceção, não é warning: o DOM monta inteiro e o quadro sai com ZERO
pixel de tinta. Aconteceu em 39/39 páginas do perfil vsl e 63/63 do reels.

É a forma mais cara de defeito deste repo — sucesso silencioso — e ele não tinha
como ser pego por render, porque nenhuma composição de produção usa este caminho
ainda. O que dá para travar HOJE é o contrato, e é o que este arquivo faz.

Rodar sem `--partitura` usa a fixture do produto; com ela, mede um arquivo real.
"""
import json
import os
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))


def achar_raiz(d):
    """Sobe até o marcador. NUNCA conta níveis: um `../../../..` afirma em que
    profundidade a skill mora, e a skill se move."""
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "tools", "pacote", "MANIFESTO.json")) \
                or os.path.isfile(os.path.join(d, "ilha", "tools", "pacote",
                                               "MANIFESTO.json")):
            return d
        d = os.path.dirname(d)
    return None


RAIZ = achar_raiz(DIR) or os.getcwd()
FIXTURE = os.path.join(RAIZ, "tools", "remotion-compositor", "src", "data",
                       "partitura.exemplo.json")

falhas, checagens = [], [0]


def ok(cond, msg):
    checagens[0] += 1
    if not cond:
        falhas.append(msg)
    print(("  ok  " if cond else "  ✗   ") + msg)


# `pinta` lê exatamente estes três campos. Um a menos e o token some do quadro.
CAMPOS = ("text", "fromMs", "toMs")


def conferir(part, rotulo):
    paginas = part.get("paginas") or []
    ok(bool(paginas), "%s: tem páginas (%d)" % (rotulo, len(paginas)))
    n_tok = n_lin = 0
    for i, pg in enumerate(paginas):
        for j, ln in enumerate(pg.get("linhas") or []):
            n_lin += 1
            for k, tk in enumerate(ln):
                n_tok += 1
                if not isinstance(tk, dict):
                    falhas.append("%s: paginas[%d].linhas[%d][%d] é %s, não token "
                                  "— o CaptionLayer renderiza 0 px"
                                  % (rotulo, i, j, k, type(tk).__name__))
                    return n_lin, n_tok
                faltando = [c for c in CAMPOS if c not in tk]
                if faltando:
                    falhas.append("%s: paginas[%d].linhas[%d][%d] sem %s"
                                  % (rotulo, i, j, k, ", ".join(faltando)))
                    return n_lin, n_tok
    checagens[0] += 1
    print("  ok  %s: %d tokens em %d linhas, todos com %s"
          % (rotulo, n_tok, n_lin, "/".join(CAMPOS)))
    return n_lin, n_tok


print("\n1 · A FIXTURE DO PRODUTO")
if not os.path.isfile(FIXTURE):
    ok(False, "fixture não existe: %s" % FIXTURE)
else:
    with open(FIXTURE, encoding="utf-8") as fh:
        part = json.load(fh)
    n_lin, n_tok = conferir(part, "fixture")
    ok(n_tok > 0, "varreu %d token(s) — varredura de 0 não prova nada" % n_tok)
    # e o texto da linha tem que reconstruir o texto da página: se `linhas`
    # perder um token, o quadro perde uma palavra sem ninguém reclamar.
    for i, pg in enumerate(part.get("paginas") or []):
        das_linhas = "".join(t["text"] for ln in pg["linhas"] for t in ln)
        dos_tokens = "".join(t["text"] for t in pg["tokens"])
        ok(das_linhas.strip() == dos_tokens.strip(),
           "página %d: as linhas reconstroem o texto da página (%r)"
           % (i, das_linhas.strip()[:44]))

print("\n2 · CONTROLE NEGATIVO — a régua tem que morder")
antes = len(falhas)
ruim = {"paginas": [{"tokens": [{"text": "a", "fromMs": 0, "toMs": 1}],
                     "linhas": [["a"]]}]}
conferir(ruim, "defeito plantado")
ok(len(falhas) > antes,
   "D1 · `linhas` com string em vez de token REPROVA (foi o defeito real)")
# o defeito plantado JÁ cumpriu o papel dele na asserção acima; tirá-lo da
# lista é o que permite a bateria sair 0 com ele tendo reprovado.
falhas[:] = [f for f in falhas if "defeito plantado" not in f]

print("\n3 · O CONSUMIDOR NÃO MUDOU DE CONTRATO")
cl = os.path.join(RAIZ, "tools", "remotion-compositor", "src", "CaptionLayer.tsx")
with open(cl, encoding="utf-8") as fh:
    fonte = fh.read()
# ⚠️ A ÂNCORA É "pinta linha token a token", não a forma literal `ln.map(pinta)`.
# Quando o eixo de layout entrou, a chamada virou
# `ln.map(st.layout === "disperso" ? pintaDisperso : pinta)` — mesma semântica,
# string diferente, e a asserção literal reprovou uma mudança correta. Contrato
# de teste que trava sintaxe em vez de comportamento vira imposto sobre refactor.
import re as _re
ok(bool(_re.search(r"ln\.map\(", fonte)) and "pinta" in fonte,
   "CaptionLayer ainda pinta linha por token (`ln.map(…pinta…)`)")
for c in CAMPOS:
    ok("tk." + c in fonte, "`pinta` lê tk.%s" % c)

print("\n4 · PLANO VISUAL, NÃO O DIRETOR, TEM AUTORIDADE SOBRE SFX")
partitura_tsx = os.path.join(RAIZ, "tools", "remotion-compositor", "src",
                             "Partitura.tsx")
with open(partitura_tsx, encoding="utf-8") as fh:
    consumidor = fh.read()
ok("PlanoVisualLayer" in consumidor,
   "Partitura delega janela e som ao consumidor do plano visual")
ok("name={it.sfx}" not in consumidor and "atS={it.inS}" not in consumidor,
   "item.sfx/inS legado não volta a decidir som no render")
teste_arvore = os.path.join(RAIZ, "tools", "remotion-compositor", "scripts",
                            "teste-plano-visual.mjs")
node_modules = os.path.join(RAIZ, "tools", "remotion-compositor", "node_modules")
release_json = os.path.join(RAIZ, "RELEASE.json")


def release_extraida_sem_dependencias():
    if os.path.isdir(node_modules) or not os.path.isfile(release_json):
        return False
    try:
        with open(release_json, encoding="utf-8") as fh:
            release = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(release, dict) and release.get("schema") == "ilha.release/v1"


if os.path.isdir(node_modules):
    rodou = subprocess.run(["node", teste_arvore], text=True, capture_output=True)
    ok(rodou.returncode == 0,
       "árvore React confirma timing/SFX/ganho do plano (%s)"
       % ((rodou.stderr or rodou.stdout).strip().splitlines()[-1]
          if (rodou.stderr or rodou.stdout).strip() else "sem saída"))
    ok("item.sfx/inS legado do diretor não tem autoridade" in rodou.stdout,
       "controle negativo planta palpite do diretor e prova que ele é ignorado")
elif release_extraida_sem_dependencias():
    # A release deliberadamente não distribui node_modules. Não chamar esta
    # checagem de render verde: ela mede apenas o contrato estático embarcado e
    # registra, de forma visível, que a árvore React não foi executada.
    plano_tsx = os.path.join(RAIZ, "tools", "remotion-compositor", "src",
                             "PlanoVisual.tsx")
    try:
        with open(plano_tsx, encoding="utf-8") as fh:
            plano_fonte = fh.read()
        with open(teste_arvore, encoding="utf-8") as fh:
            teste_fonte = fh.read()
    except OSError as exc:
        ok(False, "fallback estático não conseguiu ler consumidor/teste: %s" % exc)
    else:
        print("  NÃO MEDIDO · árvore React: release sem node_modules; "
              "execute npm ci para a prova dinâmica")
        sinais_consumidor = (
            'plano.direcao_edicao.modo === "essencial"',
            'plano.direcao_edicao.sfx !== "automatico"',
            'evento.som.decisao !== "usar"',
            "evento.som.at_s * fps",
            "evento.som.ganho_db",
            "staticFile(som.assetPublico)",
            "volume={som.volume}",
        )
        ok(all(sinal in plano_fonte for sinal in sinais_consumidor),
           "fallback estático: modo/SFX/at_s/ganho/asset chegam ao consumidor")
        sinais_controle = (
            "PALPITE-DO-DIRETOR",
            "timing visual 1.0s, SFX 1.3s",
            "sem-sfx, silêncio intencional e essencial não renderizam Audio",
            "item.sfx/inS legado do diretor não tem autoridade",
        )
        ok(all(sinal in teste_fonte for sinal in sinais_controle),
           "fallback estático: prova dinâmica e controles negativos embarcaram")
else:
    ok(False,
       "árvore React NÃO MEDIDA: fonte sem node_modules; rode `npm ci` na "
       "pasta do compositor Remotion")

print("\n%d checagens · %d falha(s)" % (checagens[0], len(falhas)))
for f in falhas:
    print("  ✗ " + f)
sys.exit(1 if falhas else 0)
