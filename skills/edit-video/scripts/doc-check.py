#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-check.py — a prova de que reorganizar doc não perdeu lição.

A forma do contrato numerado e a lista do que não entra no contexto são modeladas
de uma ferramenta de edição de terceiro, SKILL.md:19-33
e :33 — cópia de leitura em tools/referencias/. O conteúdo é nosso: cada regra vem de
uma lição medida neste repo, e a lista de contexto foi verificada item a item contra
os arquivos daqui (3 dos 8 itens exigiram exceção que o original não tem).

Cinco modos, todos SOMENTE LEITURA — nenhum deles escreve um byte:

  doc-check.py --inventario <arq...>
        JSON no stdout (é o snapshot), resumo no stderr.
  doc-check.py --sem-perda --antes <snap.json> --depois <arq...>
        tudo que existia antes existe depois, na união dos destinos.
  doc-check.py --duplicatas <arq...> [--teto N]
        shingles de 12 palavras repetidos ENTRE arquivos.
  doc-check.py --indice <skill.md> <refs...>
        RD-N -> ocorrências ancoradas; RD órfã ou sem evidência resolvível reprova.
  doc-check.py --contexto <skill.md>
        cada "leia Y no lugar" da tabela C1..CN resolve no disco. É a lista
        fechada C1–C8 de dado de máquina que NÃO entra por `Read`.  → RD-13
  doc-check.py --tudo --antes <snap.json> --skill <skill.md> <arq...>
        os cinco, no formato de veredito curto (orçamento de saída da SPEC-12).

Toda checagem imprime QUANTO varreu. Um verificador que varre zero e sai zero é
indistinguível de um verificador quebrado — é a lição de 2026-07-31 aplicada a
esta ferramenta.
"""

import argparse
import json
import os
import re
import sys

# ── o inventário: três conjuntos, todos extraíveis por regex ──────────────────
# número com unidade = a assinatura de uma lição verificada. Apagar "-21,7 dB"
# apaga a prova, e a lição vira opinião.
RE_NUM = re.compile(r'\b\d[\d.,]*\s?(?:ms|s|dB|dBFS|fps|px|kHz|Hz|%|frames?|MB|KB)\b')
# 🔴 UM `**` DENTRO DE CRASE DESSINCRONIZA O ARQUIVO INTEIRO, e isso foi medido.
# A forma ingênua `\*\*(.{4,120}?)\*\*` não é um parser de markdown: ela conta como
# delimitador de negrito o `**` de `10**(alvo_tp/20)` — potenciação de Python dentro
# de um code span, um único caso no repo (bloco da SPEC-02). Basta ele para o total
# de delimitadores da `edit-video/SKILL.md` ficar ÍMPAR (1.869) e, dali para baixo,
# todo par abre onde deveria fechar: o que o regex captura como "negrito" passa a
# ser o texto ENTRE dois negritos.
#
# O fantasma é sensível a PARIDADE — partir o arquivo re-sincroniza cada destino, e
# foi exatamente assim que a primeira rodada de `--sem-perda` acusou "2 ausentes":
# os dois eram fantasma, os dois sem um único número com unidade dentro. Um
# verificador de não-perda que reprova por artefato do próprio regex mede o regex,
# não a perda.
#
# Duas guardas, e as duas são regra real de markdown: `**` dentro de crase não é
# delimitador, e negrito não atravessa linha em branco.
RE_CODESPAN = re.compile(r'`[^`\n]*`')
RE_BOLD = re.compile(r'\*\*((?:(?!\*\*)(?!\n[ \t]*\n).){4,120}?)\*\*', re.S)


def _mascarar_crases(texto):
    """Neutraliza o miolo dos code spans preservando OFFSET — o casamento roda no
    texto mascarado e o conteúdo sai do texto original."""
    return RE_CODESPAN.sub(lambda m: "`" + " " * (len(m.group(0)) - 2) + "`", texto)


def _negritos(texto):
    mascara = _mascarar_crases(texto)
    return [texto[m.start(1):m.end(1)] for m in RE_BOLD.finditer(mascara)]


RE_PATH = re.compile(r'`([\w./-]+\.(?:py|sh|json|tsx|ts|md|mp4|mov|wav))`')
# SPEC-50 §3.4 — a evidência de uma RD é o ARQUIVO entre crases; a âncora dentro
# dele é o marcador `→ RD-N`. O `:linha` saiu: ele derivava em silêncio (nove das
# quinze já tinham derivado quando isto foi medido) e o verificador ficava verde.
RE_ANCORA = re.compile(r'`([\w./-]+\.(?:py|sh|json|tsx|ts|md))`')

SHINGLE = 12
ORCAMENTO_CHARS = 1400          # a régua da SPEC-12: ~350 tokens no caminho verde


def _ler(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return fh.read()


def inventario_de(texto):
    return {
        "numeros": sorted(set(m.strip() for m in RE_NUM.findall(texto))),
        "negritos": sorted(set(_negritos(texto))),
        "caminhos": sorted(set(RE_PATH.findall(texto))),
    }


def uniao(arquivos):
    acc = {"numeros": set(), "negritos": set(), "caminhos": set()}
    por_arquivo = {}
    for p in arquivos:
        inv = inventario_de(_ler(p))
        por_arquivo[p] = {k: len(v) for k, v in inv.items()}
        for k in acc:
            acc[k] |= set(inv[k])
    return acc, por_arquivo


def _resumo(acc):
    return "%d números · %d negritos · %d caminhos" % (
        len(acc["numeros"]), len(acc["negritos"]), len(acc["caminhos"]))


# ── modo 1: inventário ────────────────────────────────────────────────────────
def cmd_inventario(args):
    acc, por = uniao(args.arquivos)
    snap = {"schema": "benchmark.doc-inventario/v1",
            "arquivos": args.arquivos,
            "por_arquivo": por,
            "numeros": sorted(acc["numeros"]),
            "negritos": sorted(acc["negritos"]),
            "caminhos": sorted(acc["caminhos"])}
    sys.stdout.write(json.dumps(snap, ensure_ascii=False, indent=1))
    sys.stdout.write("\n")
    for p, n in por.items():
        sys.stderr.write("  %-58s num %4d · neg %4d · cam %4d\n"
                         % (p[-58:], n["numeros"], n["negritos"], n["caminhos"]))
    sys.stderr.write("INVENTARIO  %d arquivos · %s\n" % (len(args.arquivos), _resumo(acc)))
    return 0


# ── modo 2: sem-perda ─────────────────────────────────────────────────────────
def _sem_perda(snap, depois_arqs):
    acc, _ = uniao(depois_arqs)
    faltas = {}
    for k in ("numeros", "negritos", "caminhos"):
        antes = set(snap.get(k) or [])
        faltas[k] = sorted(antes - acc[k])
    totais = {k: (len(set(snap.get(k) or [])) - len(faltas[k]), len(set(snap.get(k) or [])))
              for k in faltas}
    return faltas, totais


def cmd_sem_perda(args):
    snap = json.loads(_ler(args.antes))
    faltas, tot = _sem_perda(snap, args.depois)
    n_faltas = sum(len(v) for v in faltas.values())
    linha = "SEM-PERDA   %s — %d ausentes (%d/%d · %d/%d · %d/%d) em %d arquivos" % (
        "OK" if n_faltas == 0 else "FALHA", n_faltas,
        tot["numeros"][0], tot["numeros"][1],
        tot["negritos"][0], tot["negritos"][1],
        tot["caminhos"][0], tot["caminhos"][1], len(args.depois))
    print(linha)
    if n_faltas:
        for k, v in faltas.items():
            for item in v[:20]:
                print("   AUSENTE %-9s %s" % (k, item.replace("\n", " ")[:110]))
            if len(v) > 20:
                print("   AUSENTE %-9s ... +%d" % (k, len(v) - 20))
        return 1
    return 0


# ── modo 3: duplicatas ────────────────────────────────────────────────────────
def _shingles(texto, n=SHINGLE):
    w = re.findall(r'\S+', texto)
    return set(tuple(w[i:i + n]) for i in range(len(w) - n + 1))


def _duplicatas(arquivos):
    porarq = {p: _shingles(_ler(p)) for p in arquivos}
    visto, repetido = {}, set()
    for p, S in porarq.items():
        for s in S:
            if s in visto and visto[s] != p:
                repetido.add(s)
            visto.setdefault(s, p)
    varridos = sum(len(v) for v in porarq.values())
    return repetido, varridos, porarq


def cmd_duplicatas(args):
    rep, varridos, porarq = _duplicatas(args.arquivos)
    ok = args.teto is None or len(rep) <= args.teto
    print("DUPLICATAS  %d shingles entre arquivos (teto %s) — varridos %d de %d arquivos — %s"
          % (len(rep), args.teto if args.teto is not None else "livre",
             varridos, len(arquivos_reais(args.arquivos)), "OK" if ok else "FALHA"))
    if args.listar:
        for s in sorted(rep)[:args.listar]:
            print("   DUP %s" % (" ".join(s)[:120]))
    return 0 if ok else 1


def arquivos_reais(lista):
    return [p for p in lista if os.path.isfile(p)]


# ── modo 4: índice das Regras Duras ───────────────────────────────────────────
RE_RD_DEF = re.compile(r'^\|\s*\*\*RD-(\d+)\*\*\s*\|(.*)\|(.*)\|\s*$', re.M)
RE_RD_USO = re.compile(r'(?<!\*\*)(?<!-)\bRD-(\d+)\b')


def _resolver_ancora(arq, n, bases):
    """A evidência é ARQUIVO + o marcador `→ RD-N` dentro dele. NUNCA linha.

    🔴 SPEC-50 §3.4 — por que o número de linha saiu, e a medição que decidiu.

    Até aqui a evidência era `arquivo:linha`, e a checagem era "a linha existe e
    não está em branco". Isso reprova quando alguém APAGA o fim do arquivo, e só.
    Inserir um parágrafo acima desloca o número, a linha continua existindo e
    continua não-branca, e a evidência passa a apontar para outra frase — em
    silêncio, com o portão verde.

    Não é hipótese. Medido nesta árvore, na v0.13, com o `--indice` dizendo
    "0 sem evidência resolvível — OK": RD-10 apontava para uma régua horizontal
    (`---`), RD-9 para a palavra solta "monitores.", RD-14 para um parágrafo
    sobre scripts de produção, RD-6 e RD-12 para o meio de outro assunto. **Nove
    das quinze já tinham derivado**, e o verificador dizia que estavam todas de pé.

    O marcador `→ RD-N` já existia no arquivo-alvo das quinze (é a convenção que
    quem escreveu as references usou). Ele viaja COM o parágrafo: mover o bloco
    move a âncora junto. A evidência passa a ser ele.
    """
    marca = re.compile(r"(?:→|->)\s*RD-%d\b" % n)
    existe_em = None
    for base in bases:
        p = os.path.normpath(os.path.join(base, arq))
        if os.path.isfile(p):
            existe_em = p
            for linha in open(p, encoding="utf-8", errors="replace"):
                # 🔴 A PRÓPRIA LINHA DA TABELA NÃO CONTA COMO EVIDÊNCIA, e isto
                # foi medido: quando a evidência aponta para o arquivo que HOSPEDA
                # a tabela, a célula ``doc-a.md` → RD-3` casa o marcador que
                # ela mesma exige. A âncora se auto-satisfaz e o portão fica verde
                # sobre nada. É a mesma exclusão que `cmd_indice` já aplica ao
                # contar ocorrências — agora as duas leituras concordam.
                if linha.lstrip().startswith("|") and "**RD-" in linha:
                    continue
                if marca.search(linha):
                    return p, None
    if existe_em is None:
        return None, "arquivo não existe"
    return None, "existe, mas não tem o marcador `→ RD-%d` dentro" % n


def cmd_indice(args):
    skill = args.skill
    corpus = [skill] + list(args.refs)
    texto_skill = _ler(skill)
    defs = {}
    for m in RE_RD_DEF.finditer(texto_skill):
        defs[int(m.group(1))] = {"regra": m.group(2).strip(), "evidencia": m.group(3).strip()}
    if not defs:
        print("INDICE      FALHA — nenhuma RD encontrada em %s" % skill)
        return 1

    bases = [os.path.dirname(os.path.abspath(skill)),
             os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(skill)), "..", "..", "..")),
             os.getcwd()]
    ocorrencias = {n: [] for n in defs}
    for p in corpus:
        for i, linha in enumerate(_ler(p).splitlines(), 1):
            desnudo = linha.lstrip()
            if desnudo.startswith("#"):
                continue                      # título não é ocorrência ancorada
            if desnudo.startswith("|") and "**RD-" in linha:
                continue                      # a própria linha da tabela não conta
            for m in RE_RD_USO.finditer(linha):
                n = int(m.group(1))
                if n in ocorrencias:
                    ocorrencias[n].append("%s:%d" % (os.path.basename(p), i))

    orfas, sem_evidencia = [], []
    for n, d in sorted(defs.items()):
        if not ocorrencias[n]:
            orfas.append(n)
        ancoras = RE_ANCORA.findall(d["evidencia"])
        if not ancoras:
            sem_evidencia.append((n, "a coluna evidência não nomeia arquivo "
                                     "entre crases"))
            continue
        motivos = []
        for a in ancoras:
            achou, porque = _resolver_ancora(a, n, bases)
            if achou:
                break
            motivos.append("%s (%s)" % (a, porque))
        else:
            sem_evidencia.append((n, "; ".join(motivos)))

    total = sum(len(v) for v in ocorrencias.values())
    ok = not orfas and not sem_evidencia
    print("INDICE      %d RD · %d órfãs · %d sem evidência resolvível · %d ocorrências ancoradas — %s"
          % (len(defs), len(orfas), len(sem_evidencia), total, "OK" if ok else "FALHA"))
    if args.listar:
        for n in sorted(defs):
            print("   RD-%-2d %s" % (n, ", ".join(ocorrencias[n][:6]) or "(órfã)"))
    if orfas:
        print("   ORFA  RD sem uma única ocorrência no corpo: %s"
              % ", ".join("RD-%d" % n for n in orfas))
    if sem_evidencia:
        print("   EVID  RD cuja evidência não resolve (arquivo + marcador `→ RD-N`):")
        for n, porque in sem_evidencia:
            print("         RD-%-2d %s" % (n, porque))
    return 0 if ok else 1


# ── modo 5: contrato de contexto ──────────────────────────────────────────────
RE_C_LINHA = re.compile(r'^\|\s*\*\*(C\d+)\*\*\s*\|(.*)$', re.M)
# o que a coluna "leia no lugar" pode prometer, e que tem de existir no disco
RE_SUBSTITUTO = re.compile(r'`([\w./-]+\.(?:py|sh|json|md))`|`(jq)`|`([\w./-]+/)`')


def cmd_contexto(args):
    texto = _ler(args.skill)
    base_skill = os.path.dirname(os.path.abspath(args.skill))
    raiz = os.path.abspath(os.path.join(base_skill, "..", "..", ".."))
    itens, faltas, sem_excecao = [], [], []
    for m in RE_C_LINHA.finditer(texto):
        cid = m.group(1)
        celulas = [c.strip() for c in m.group(2).split("|")]
        itens.append(cid)
        # coluna 3 (índice 2) é "leia no lugar" no layout da tabela
        lugar = celulas[2] if len(celulas) > 2 else ""
        veredito = celulas[3] if len(celulas) > 3 else ""
        alvos = []
        for g in RE_SUBSTITUTO.findall(lugar):
            alvos.append(next(x for x in g if x))
        if not alvos:
            faltas.append("%s sem substituto nomeado" % cid)
            continue
        achou = False
        for alvo in alvos:
            if alvo == "jq":
                achou = achou or _tem_jq()
                continue
            for base in (raiz, base_skill, os.path.join(raiz, ".claude", "skills")):
                if _existe_por_sufixo(base, alvo):
                    achou = True
                    break
        if not achou:
            faltas.append("%s: nenhum substituto resolve no disco (%s)" % (cid, ", ".join(alvos)))
        if cid in ("C1", "C2", "C5") and "xceção" not in (lugar + veredito):
            sem_excecao.append(cid)

    # C5 é a exceção que um port literal da Hard Rule 13 deles mataria
    c5 = next((m.group(0) for m in RE_C_LINHA.finditer(texto) if m.group(1) == "C5"), "")
    c5_ok = bool(re.search(r'(PNG|JPG).{0,80}`Read`|`Read`.{0,80}(PNG|JPG)', c5, re.S))
    ok = not faltas and not sem_excecao and c5_ok and len(itens) > 0
    print("CONTEXTO    %d itens · %d substitutos resolvem · %d com exceção escrita · C5-frame-lido=%s — %s"
          % (len(itens), len(itens) - len(faltas), 3 - len(sem_excecao),
             "sim" if c5_ok else "NAO", "OK" if ok else "FALHA"))
    for f in faltas:
        print("   FALTA %s" % f)
    for c in sem_excecao:
        print("   EXCECAO %s deveria carregar a exceção escrita" % c)
    if not c5_ok:
        print("   C5 tem que dizer explicitamente que frame PNG/JPG É lido com `Read`")
    return 0 if ok else 1


def _existe_por_sufixo(base, alvo):
    p = os.path.normpath(os.path.join(base, alvo))
    if os.path.exists(p):
        return True
    # nome solto: procura em profundidade curta
    nome = alvo.rstrip("/").split("/")[-1]
    for raiz, dirs, arqs in os.walk(base):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in ("node_modules", "__pycache__", "data")]
        if raiz.count(os.sep) - base.count(os.sep) > 4:
            dirs[:] = []
            continue
        if nome in arqs or nome in dirs:
            return True
    return False


def _tem_jq():
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isfile(os.path.join(d, "jq")):
            return True
    return False


# ── modo 6: tudo, no orçamento ────────────────────────────────────────────────
def cmd_tudo(args):
    import io
    saida, cods = io.StringIO(), []

    class _Tee:
        def write(self, s):
            saida.write(s)
            return len(s)

        def flush(self):
            pass

    real = sys.stdout
    sys.stdout = _Tee()
    try:
        acc, _ = uniao(args.arquivos)
        print("INVENTARIO  %d arquivos · %s" % (len(args.arquivos), _resumo(acc)))
        cods.append(cmd_sem_perda(argparse.Namespace(antes=args.antes, depois=args.arquivos)))
        cods.append(cmd_duplicatas(argparse.Namespace(
            arquivos=args.arquivos, teto=args.teto, listar=0)))
        cods.append(cmd_indice(argparse.Namespace(
            skill=args.skill, refs=[p for p in args.arquivos if p != args.skill], listar=0)))
        cods.append(cmd_contexto(argparse.Namespace(skill=args.skill)))
    finally:
        sys.stdout = real
    texto = saida.getvalue()
    real.write(texto)
    n = len(texto)
    estouro = n > ORCAMENTO_CHARS
    real.write("ORCAMENTO   %d chars (teto %d) — %s\n"
               % (n, ORCAMENTO_CHARS, "FALHA" if estouro else "OK"))
    return 1 if (any(cods) or estouro) else 0


RE_CONTRATO = re.compile(r"benchmark\.[a-z0-9-]+/v[0-9]+(?:\.[0-9]+)?")


def cmd_contratos(args):
    """Toda string `benchmark.*/vN` declarada em CÓDIGO existe no contrato .md?

    🔴 ACHADO A23. `detect-cor.py:65` declara `benchmark.cor/v1.1`, a docstring
    do próprio arquivo diz `v1`, e `references/contrato-cor.md` não contém a
    string `v1.1` em lugar nenhum. Quem lê o doc para escrever um consumidor
    implementa contra a versão errada — e o dado ainda vai bater nas
    contra-amostras (EDL, gain_db), porque o drift está na VERSÃO, não no
    conteúdo. Isso é o pior tipo de divergência: silenciosa e plausível.

    A régua é modesta de propósito: só confere as famílias que TÊM um
    `contrato-*.md`. Contrato sem doc é decisão de outra spec — dizer isso é
    mais honesto que reprovar 40 famílias e ninguém rodar o comando de novo."""
    docs = {}
    for arq in args.docs:
        nome = os.path.basename(arq)
        fam = nome[len("contrato-"):-len(".md")] if nome.startswith("contrato-") else nome
        docs[fam] = (arq, _ler(arq))
    # 🔴 CONJUNTO VAZIO NÃO É VERDE (achado R-20a, 2026-08-11). Sem entrada, este
    # comando imprimia "0 string(s) … OK" e saía 0 — e nenhum doc fixa QUAL é o
    # conjunto de arquivos a varrer, então o "10 conferidas" do registro só se
    # reproduz adivinhando o glob. Um verificador que varre zero e sai zero é
    # indistinguível de um quebrado; é a régua deste repo aplicada a ele mesmo.
    arqs = arquivos_reais(args.codigo)
    if not arqs:
        print("CONTRATOS   0 arquivo(s) de código na entrada — FALHA")
        print("   nada foi varrido, e varrer nada não é conferir nada. A invocação "
              "canônica está no SKILL.md do edit-video, § Contratos.")
        return 2
    if not docs:
        print("CONTRATOS   %d arquivo(s) de código e 0 `contrato-*.md` — FALHA"
              % len(arqs))
        print("   sem `--docs <contrato-*.md>…` não há contra o que conferir.")
        return 2

    declarados = {}
    for arq in arqs:
        try:
            with open(arq, encoding="utf-8") as fh:
                txt = fh.read()
        except (OSError, UnicodeError):
            continue
        for i, linha in enumerate(txt.splitlines(), 1):
            for s in RE_CONTRATO.findall(linha):
                declarados.setdefault(s, []).append("%s:%d" % (arq, i))

    faltas, conferidos, sem_doc = [], 0, set()
    for s, ondes in sorted(declarados.items()):
        familia = s.split("/")[0].split(".", 1)[1]
        alvo = next((f for f in docs if familia == f or familia.startswith(f)), None)
        if alvo is None:
            sem_doc.add(familia)
            continue
        conferidos += 1
        if s not in docs[alvo][1]:
            faltas.append("%s declarado em %s e AUSENTE de %s"
                          % (s, ondes[0], os.path.basename(docs[alvo][0])))

    print("CONTRATOS   %d string(s) `benchmark.*/vN` em código · %d conferida(s) "
          "contra %d doc(s) · %d família(s) sem contrato-*.md · %s"
          % (len(declarados), conferidos, len(docs), len(sem_doc),
             "OK" if not faltas else "FALHA"))
    for f in faltas:
        print("   DRIFT  %s" % f)
    if sem_doc and args.listar:
        print("   (sem contrato-*.md: %s)" % ", ".join(sorted(sem_doc)))
    return 1 if faltas else 0


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    ap.add_argument("--inventario", nargs="+", metavar="ARQ")
    ap.add_argument("--sem-perda", action="store_true")
    ap.add_argument("--antes", metavar="SNAP.JSON")
    ap.add_argument("--depois", nargs="+", metavar="ARQ")
    ap.add_argument("--duplicatas", nargs="+", metavar="ARQ")
    ap.add_argument("--teto", type=int, default=None)
    ap.add_argument("--listar", type=int, default=0)
    ap.add_argument("--indice", nargs="+", metavar="ARQ")
    ap.add_argument("--contexto", metavar="SKILL.MD")
    ap.add_argument("--tudo", nargs="+", metavar="ARQ")
    ap.add_argument("--skill", metavar="SKILL.MD")
    ap.add_argument("--contratos", nargs="+", metavar="ARQ",
                    help="arquivos de CÓDIGO a varrer atrás de `benchmark.*/vN`")
    ap.add_argument("--docs", nargs="+", metavar="CONTRATO.MD", default=[],
                    help="os contrato-*.md contra os quais conferir")
    a = ap.parse_args(argv)

    if a.inventario:
        return cmd_inventario(argparse.Namespace(arquivos=a.inventario))
    if a.sem_perda:
        if not a.antes or not a.depois:
            ap.error("--sem-perda exige --antes e --depois")
        return cmd_sem_perda(a)
    if a.duplicatas:
        return cmd_duplicatas(argparse.Namespace(
            arquivos=a.duplicatas, teto=a.teto, listar=a.listar))
    if a.indice:
        return cmd_indice(argparse.Namespace(
            skill=a.indice[0], refs=a.indice[1:], listar=a.listar))
    if a.contexto:
        return cmd_contexto(argparse.Namespace(skill=a.contexto))
    if a.contratos:
        if not a.docs:
            ap.error("--contratos exige --docs <contrato-*.md ...>")
        return cmd_contratos(argparse.Namespace(
            codigo=a.contratos, docs=a.docs, listar=a.listar))
    if a.tudo:
        if not a.antes or not a.skill:
            ap.error("--tudo exige --antes e --skill")
        return cmd_tudo(argparse.Namespace(
            arquivos=a.tudo, antes=a.antes, skill=a.skill, teto=a.teto))
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
