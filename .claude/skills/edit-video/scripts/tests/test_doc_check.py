#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bateria do doc-check.py — material 100% sintético, sem rede, sem creator.

    python3 .claude/skills/edit-video/scripts/tests/test_doc_check.py

Cada mecanismo é testado DUAS vezes: o caso bom e o **defeito plantado** que ele TEM
que acusar. Portão que não acusa o defeito plantado é indistinguível de portão
quebrado — e esta bateria existe porque o `--sem-perda` é a única prova de que a
partição de doc não perdeu lição.

Os defeitos plantados foram escolhidos onde o portão é FRACO, não onde ele já
protege:
  · bloco removido com número medido dentro          (a perda que importa)
  · `**` dentro de crase, que dessincroniza o arquivo (o defeito real de 2026-08-09)
  · RD sem uma única ocorrência no corpo             (a regra que virou enfeite)
  · RD cujo arquivo de evidência NÃO tem o marcador  (a âncora que sumiu)
  · RD cuja evidência não nomeia arquivo nenhum      (a coluna vazia disfarçada)
  · 🦷 e o CONTROLE DO CORTE (SPEC-50 §3.4): inserir um parágrafo acima da
    evidência NÃO pode reprovar — era exatamente o que a âncora por número de
    linha fazia, em silêncio e com o portão verde
  · substituto de contexto que não existe no disco   (a promessa que não resolve)
  · C5 sem a frase do frame PNG                      (o port literal que mata o QC visual)
"""

import json
import os
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
DOC_CHECK = os.path.normpath(os.path.join(AQUI, "..", "doc-check.py"))

ok, falhas, varridos = 0, [], {"casos": 0}


def checa(nome, cond, detalhe=""):
    global ok
    varridos["casos"] += 1
    if cond:
        ok += 1
    else:
        falhas.append("%s %s" % (nome, detalhe))
    print("  %s %s%s" % ("ok  " if cond else "FALHA", nome, ("  — " + detalhe) if detalhe and not cond else ""))


def roda(*args):
    p = subprocess.run([sys.executable, DOC_CHECK] + list(args),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


DOC_A = """# Doc A

Fluxo medido. O corte perdeu **0,28 s em 20 emendas**, e a deriva era progressiva.  → RD-1

- 🐛 **SEGMENTO SINTETICO — o bloco que a bateria remove de propósito.** Mediu
  **6,25 s** de vídeo errado com todos os QCs verdes. Script: `montar.sh`.
- ⚠️ A régua é `±3 ms` sem tendência.  → RD-3

## Regras Duras (RD)

| # | regra | evidência |
|---|---|---|
| **RD-1** | **A regra um.** | `doc-a.md` → RD-1 |
| **RD-3** | **A regra três.** | `doc-a.md` → RD-3 |

## Contexto — o que NUNCA entra por `Read`

| # | não leia com `Read` | o número | leia no lugar | veredito |
|---|---|---|---|---|
| **C1** | `transcript.json` | 4.604.681 B | `doc-b.md` | ✅ com exceção escrita |
| **C5** | binário | não decodifica | `doc-b.md` | 🔴 exceção: frame em PNG/JPG É lido com `Read` |
"""

DOC_B = """# Doc B

Outro documento. Ele carrega **1,82 s de cauda** e o caminho `bordas.py`.
"""


def escreve(dirp, nome, txt):
    p = os.path.join(dirp, nome)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return p


def main():
    print("test_doc_check — material sintético, sem rede")
    with tempfile.TemporaryDirectory() as d:
        a = escreve(d, "doc-a.md", DOC_A)
        b = escreve(d, "doc-b.md", DOC_B)

        # ── 1 · inventário
        cod, out, err = roda("--inventario", a, b)
        snap = json.loads(out)
        checa("inventario sai 0", cod == 0)
        checa("inventario acha o número medido", "6,25 s" in snap["numeros"],
              str(snap["numeros"]))
        checa("inventario acha o caminho", "montar.sh" in snap["caminhos"])
        checa("inventario imprime QUANTO varreu", "INVENTARIO" in err)
        snap_p = escreve(d, "snap.json", out)

        # ── 2 · sem-perda: caso bom
        cod, out, _ = roda("--sem-perda", "--antes", snap_p, "--depois", a, b)
        checa("sem-perda verde quando nada mudou", cod == 0 and "0 ausentes" in out, out)

        # ── 2b · 🔴 DEFEITO PLANTADO: some o bloco com o número medido
        linhas = DOC_A.splitlines(keepends=True)
        sem_bloco = "".join(l for l in linhas if "SEGMENTO SINTETICO" not in l
                            and "6,25 s" not in l)
        a2 = escreve(d, "doc-a.md", sem_bloco)
        cod, out, _ = roda("--sem-perda", "--antes", snap_p, "--depois", a2, b)
        checa("sem-perda ACUSA o bloco removido", cod == 1, out)
        checa("sem-perda NOMEIA o número perdido", "6,25 s" in out, out)
        escreve(d, "doc-a.md", DOC_A)

        # ── 3 · 🔴 DEFEITO PLANTADO: `**` dentro de crase dessincroniza o arquivo
        #      É o defeito real medido em 2026-08-09 (`10**(alvo_tp/20)`).
        com_potencia = DOC_A.replace("O corte perdeu", "O limite sai de `10**(alvo/20)`. O corte perdeu")
        a3 = escreve(d, "doc-a-pot.md", com_potencia)
        cod, out, _ = roda("--inventario", a3)
        neg = json.loads(out)["negritos"]
        checa("negrito imune a ** dentro de crase",
              "0,28 s em 20 emendas" in neg and not any("**" in n for n in neg),
              str(neg[:4]))
        fantasma = [n for n in neg if "\n\n" in n]
        checa("nenhum negrito atravessa parágrafo", not fantasma, str(fantasma[:2]))

        # ── 4 · duplicatas
        cod, out, _ = roda("--duplicatas", a, b, "--teto", "0")
        checa("duplicatas verde entre docs disjuntos", cod == 0 and " 0 shingles" in out, out)
        checa("duplicatas imprime quantos shingles varreu", "varridos" in out, out)
        # 🔴 DEFEITO PLANTADO: copia 12 palavras de A para dentro de B
        trecho = " ".join(DOC_A.split()[:14])
        b2 = escreve(d, "doc-b.md", DOC_B + "\n" + trecho + "\n")
        cod, out, _ = roda("--duplicatas", a, b2, "--teto", "0")
        checa("duplicatas ACUSA texto copiado entre arquivos", cod == 1, out)
        escreve(d, "doc-b.md", DOC_B)

        # ── 5 · índice das RD
        cod, out, _ = roda("--indice", a, b)
        checa("indice verde com RD ancorada", cod == 0 and "0 órfãs" in out, out)
        # 🔴 DEFEITO PLANTADO: RD sem nenhuma ocorrência no corpo
        orfa = DOC_A.replace("| **RD-3** |", "| **RD-9** |")
        a4 = escreve(d, "doc-a-orfa.md", orfa)
        cod, out, _ = roda("--indice", a4, b)
        checa("indice ACUSA RD órfã", cod == 1 and "ORFA" in out, out)
        # 🔴 DEFEITO PLANTADO: o marcador `→ RD-3` sumiu do arquivo de evidência.
        # É a evidência DE FATO ausente — o único jeito de a âncora de texto
        # deixar de resolver, e o que a SPEC-50 quer que continue reprovando.
        # ⚠️ O DEFEITO TEM QUE SER PLANTADO NO ARQUIVO QUE A EVIDÊNCIA NOMEIA.
        # Primeira tentativa (medida): gravei a variante como `doc-a-sem-marca.md`
        # e a evidência continuava apontando `doc-a.md`, que estava intacto ao
        # lado — o teste saiu VERDE achando que tinha plantado um defeito.
        # A variante vai para um diretório PRÓPRIO, onde `doc-a.md` é a variante.
        # A MENÇÃO fica (senão a RD viraria órfã e o teste mediria outra coisa);
        # o que some é o MARCADOR, que é a âncora.
        d5 = os.path.join(d, "sem-marca")
        os.makedirs(d5, exist_ok=True)
        sem_marca = DOC_A.replace("  → RD-3", "  (ver RD-3)")
        a5 = escreve(d5, "doc-a.md", sem_marca)
        escreve(d5, "doc-b.md", DOC_B)
        cod, out, _ = roda("--indice", a5, os.path.join(d5, "doc-b.md"))
        checa("indice ACUSA arquivo sem o marcador → RD-N",
              cod == 1 and "EVID" in out and "não tem o marcador" in out, out)
        # 🔴 DEFEITO PLANTADO: a coluna evidência não nomeia arquivo nenhum
        vazia = DOC_A.replace("`doc-a.md` → RD-3 |", "ver a reference |")
        a6 = escreve(d, "doc-a-vazia.md", vazia)
        cod, out, _ = roda("--indice", a6, b)
        checa("indice ACUSA evidência que não nomeia arquivo",
              cod == 1 and "EVID" in out, out)
        # 🦷 CONTROLE DO CORTE (SPEC-50 §3.4): um parágrafo inserido ACIMA da
        # evidência desloca todas as linhas abaixo. Com a âncora por número isso
        # passava a apontar para outra frase e o portão continuava VERDE (medido
        # na v0.13: 9 das 15 RD reais já tinham derivado assim). Com a âncora de
        # texto tem que continuar verde por acerto, não por sorte.
        movido = DOC_A.replace("# Doc A\n",
                               "# Doc A\n\nParágrafo inserido depois, que empurra "
                               "tudo abaixo em duas linhas.\n")
        a7 = escreve(d, "doc-a-movido.md", movido)
        cod, out, _ = roda("--indice", a7, b)
        checa("parágrafo inserido NÃO quebra a âncora (o corte da SPEC-50)",
              cod == 0 and "0 sem evidência" in out, out)

        # ── 6 · contrato de contexto
        cod, out, _ = roda("--contexto", a)
        checa("contexto verde com substituto que resolve", cod == 0, out)
        checa("contexto imprime quantos itens varreu", "8 itens" in out or "2 itens" in out, out)
        # 🔴 DEFEITO PLANTADO: substituto que não existe no disco
        quebrado = DOC_A.replace("| `doc-b.md` | ✅ com exceção", "| `nao-existe-nenhum.md` | ✅ com exceção")
        a7 = escreve(d, "doc-a-quebrado.md", quebrado)
        cod, out, _ = roda("--contexto", a7)
        checa("contexto ACUSA substituto que não resolve", cod == 1 and "FALTA" in out, out)
        # 🔴 DEFEITO PLANTADO: C5 sem a frase do frame PNG — o port literal da HR13 deles
        sem_c5 = DOC_A.replace("🔴 exceção: frame em PNG/JPG É lido com `Read`", "🔴 nunca leia binário")
        a8 = escreve(d, "doc-a-sem-c5.md", sem_c5)
        cod, out, _ = roda("--contexto", a8)
        checa("contexto ACUSA C5 sem a frase do frame PNG", cod == 1, out)

    print("\n%d checagens · %d ok · %d falhas" % (varridos["casos"], ok, len(falhas)))
    for f in falhas:
        print("  FALHOU: %s" % f)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
