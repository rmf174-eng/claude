#!/usr/bin/env python3
"""qc.py — UM comando, UM veredito. A bateria de QC da ilha de edição (SPEC-12).

    qc.py <dir-producao> [--estagio auto|montado|compositado|final]
                         [--so id,id] [--pular id,id] [--jobs 3]
                         [--json] [--completo]
    qc.py --autoteste [--desligar-regra <nome>]
    qc.py --catalogo

    exit 0  nenhuma FALHA (com ou sem achados)
         1  ao menos uma FALHA — ou um sub-QC anormal (veredito `anormal`)
         2  erro de uso
         3  bateria vazia — nenhum QC do estágio pôde rodar

O DESPEJO NÃO É O PROBLEMA; A ORQUESTRAÇÃO É
Medido em 2026-08-08, produção `creator-2/peca-01`, 29 segmentos, entregue e
aprovada: TRÊS dos QCs somam **5.624 chars (~1.400 tokens)** para UM defeito real
— `audit-emendas` 3.475 chars com 29× CLIP-FIM + 29× CLIP-INICIO e exit 1;
`qc-ataque` 1.893 chars com 0 flags; `qc-fonemas` 256 chars com o único defeito.
Com os outros a saída passa de 10 mil chars. O que faltava não era medição: era a
camada que escolhe o que roda, em que estágio, e traduz N saídas numa decisão.

AS TRÊS REGRAS QUE ESTE ARQUIVO EXECUTA (não cita)

1. 🔴 `unidades == 0` NUNCA vira `ok`. Vira NÃO VERIFICADO.
   Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado. Já houve
   um QC neste repo que mediu uma faixa vazia, não testou nada e imprimiu verde.
   Por isso todo item em OK carrega a CONTAGEM do que varreu, e nenhum item sem
   contagem pode ser aprovado.

2. 🔴 DETECTOR ≠ TESTE DE CONVERGÊNCIA, e a diferença não é opinião: é a natureza
   da referência.
     · `convergencia` — a régua é INDEPENDENTE do critério que selecionou o item
       (os pares, o corpo da palavra vizinha, a fronteira de frames, um alvo do
       contrato). Só ela pode produzir FALHA.
     · `detector` — o item foi selecionado por estar de um lado de um limiar. Ele
       está do lado errado POR CONSTRUÇÃO. Vira ACHADO: aponta onde ouvir, nunca
       bloqueia. Um detector nunca converge a zero; perseguir o número dele até
       zero levanta ruído de sala.
   Quem classifica é o catálogo (`tipo`, `promove_falha`, `rebaixa_achado`), não
   este código e muito menos quem executa.

3. 🔴 SILÊNCIO NÃO É APROVAÇÃO. Existe um bloco NÃO VERIFICADO e um exit 3, para
   que "não verifiquei nada" nunca se confunda com "está tudo bem".

4. 🔴 SUB-QC QUE MORRE NÃO VERIFICA NADA (2026-08-12, H47-1). Medido em campo por
   um agente externo rodando a v0.12 no Linux: `qc-cor.py` estourou `TypeError` em
   `os.path.exists(bruto)` DEPOIS de imprimir "varreu 17" — o adaptador leu as 17
   unidades da parte que rodou, não achou nenhum ❌, e o item foi para o relatório
   como **`ok` com `exec.exit=1`**. O crash de um verificador virou aprovação: a
   pior classe de defeito desta casa, porque quem lê o relatório para de olhar.
   Agora `_saida_anormal()` observa a saída de FORA do adaptador — traceback,
   morte por sinal, e exit ≠ 0 que o adaptador não soube explicar em nenhum item —
   e o item nunca pode ser `ok`/`achado`: vira NÃO VERIFICADO com motivo `crash`
   ou `exit-inesperado`, o veredito da bateria vira `anormal` e o exit vira 1. A
   única coisa que o guarda NÃO faz é apagar falha: se o sub-QC morreu depois de
   acusar um defeito real, o defeito continua sendo FALHA (senão o conserto de um
   verificador mentiroso esconderia o defeito que ele achou).

ZERO VALOR DE FORMATO AQUI DENTRO (SPEC-00)
Nenhuma resolução, fps, aspecto ou zona entra neste arquivo nem no catálogo. O que
se lê do perfil é `qc.*` e `ritmo.*`, e só para AVALIAR predicado — nunca para
gerar comando. O gate é um `grep` e ele tem que dar zero.

NUNCA SOME `end − start` DA EDL para saber onde algo cai na saída. A soma nominal
é sempre menor que o render (353 ms no fim de `creator-2/peca-03`) e o consumidor lê a
palavra errada dos dois lados do corte. Quem sabe é a `timeline_real`.
"""
import argparse
import fnmatch
import glob
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CONTRATO = "benchmark.qc-bateria/v1"
CONTRATO_CATALOGO = "benchmark.qc-catalogo/v1"
CONTRATO_LOCAL = "benchmark.qc-local/v1"

# Orçamento de saída, em chars. Não é decoração: é o contrato com o agente que lê.
ORCAMENTO_LIMPO = 1400
ORCAMENTO_COM_FALHA = 2000
MAX_LINHAS_POR_QC = 2
MAX_DETALHE = 120
MAX_RESUMO = 90

ESTADOS = ("ok", "achado", "falha", "nao_verificado", "erro")
MOTIVOS = ("estagio", "insumo", "ambiente", "perfil", "sem-script",
           "sem-saida-parseavel", "sem-prova-de-dentes", "pulado", "timeout",
           "crash", "exit-inesperado")


# ───────────────────────────────────────────────────────── resolução de caminhos

def dir_scripts():
    """Onde moram os scripts de QC. Variável com default, nunca caminho cravado."""
    return os.environ.get("BENCH_EDIT_SCRIPTS") or os.path.dirname(
        os.path.abspath(__file__))


def dir_skill():
    return os.path.dirname(dir_scripts())


def dir_skills():
    """A pasta que contém as skills — para alcançar `omni-insert` sem hardcode."""
    return os.path.dirname(dir_skill())


def caminho_catalogo():
    return os.environ.get("BENCH_QC_BATERIA") or os.path.join(
        dir_skill(), "qc", "bateria.json")


_CHAVES_MOD = None
_CHAVES_TENTADO = False


def _modulo_chaves():
    """Resolvedor central no layout fonte ou produto, sem contar níveis fixos."""
    global _CHAVES_MOD, _CHAVES_TENTADO
    if _CHAVES_TENTADO:
        return _CHAVES_MOD
    _CHAVES_TENTADO = True
    inicios = [Path(dir_scripts()).resolve(), Path(__file__).resolve().parent]
    vistos = set()
    for inicio in inicios:
        for d in (inicio, *inicio.parents):
            if d in vistos:
                continue
            vistos.add(d)
            alvo = d / "tools" / "pacote" / "chaves.py"
            if not alvo.is_file():
                continue
            spec = importlib.util.spec_from_file_location("ilha_chaves_qc", alvo)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _CHAVES_MOD = mod
            return mod
    return None


def resolver_credencial(nome):
    """(valor, origem) sem imprimir valor; ambiente sempre vence o arquivo."""
    valor = os.environ.get(nome)
    if valor:
        return valor, "env"
    mod = _modulo_chaves()
    if mod is None:
        return None, "ausente"
    declaradas = {chave for recurso in mod.RECURSOS.values()
                  for chave in recurso.get("chaves", [])}
    if nome not in declaradas:
        # Um extra local não pode usar `env:NOME` para pescar qualquer entrada
        # arbitrária do arquivo privado. Resolução automática é só para o
        # contrato de credenciais declarado no manifesto.
        return None, "ausente"
    return mod.resolver_com_origem(nome)


def ambiente_do_item(item):
    """Cópia do ambiente com as credenciais requeridas resolvidas localmente."""
    ambiente = dict(os.environ)
    for req in item.get("requer", []):
        if not req.startswith("env:"):
            continue
        nome = req[4:]
        if ambiente.get(nome):
            continue
        valor, _origem = resolver_credencial(nome)
        if valor:
            ambiente[nome] = valor
    return ambiente


# ──────────────────────────────────────────────────────────────────── o catálogo

class ErroUso(Exception):
    pass


def carregar_catalogo(caminho=None):
    """bateria.json + os fragmentos de `qc/bateria.d/*.json`, mesclados por `id`.

    O diretório de fragmentos existe por um motivo concreto e medido: specs
    paralelas que precisam REGISTRAR uma sonda nova não deveriam ter que editar o
    mesmo arquivo ao mesmo tempo — dois patches no mesmo JSON é como se perde
    trabalho num merge. Um arquivo por registro, e o `id` decide quem vence
    (fragmento sobrescreve o catálogo base, campo a campo)."""
    caminho = caminho or caminho_catalogo()
    if not os.path.exists(caminho):
        raise ErroUso("catálogo não encontrado: %s" % caminho)
    with open(caminho) as fh:
        cat = json.load(fh)
    if cat.get("schema") != CONTRATO_CATALOGO:
        raise ErroUso("%s: schema %r, esperado %r"
                      % (caminho, cat.get("schema"), CONTRATO_CATALOGO))
    por_id = {}
    ordem = []
    for it in cat.get("itens", []):
        por_id[it["id"]] = it
        ordem.append(it["id"])
    frag_dir = os.path.join(os.path.dirname(caminho), "bateria.d")
    fragmentos = sorted(glob.glob(os.path.join(frag_dir, "*.json")))
    for f in fragmentos:
        with open(f) as fh:
            doc = json.load(fh)
        itens = doc["itens"] if isinstance(doc, dict) else doc
        for it in itens:
            if it["id"] in por_id:
                por_id[it["id"]] = {**por_id[it["id"]], **it}
            else:
                por_id[it["id"]] = it
                ordem.append(it["id"])
    cat["itens"] = [por_id[i] for i in ordem]
    cat["_fragmentos"] = [os.path.basename(f) for f in fragmentos]
    cat["_caminho"] = caminho
    validar_catalogo(cat)
    return cat


def validar_catalogo(cat):
    vistos = set()
    for it in cat["itens"]:
        for k in ("id", "tipo", "estagios", "adaptador", "unidade"):
            if k not in it:
                raise ErroUso("item %r sem campo obrigatório %r"
                              % (it.get("id"), k))
        if it["id"] in vistos:
            raise ErroUso("id duplicado no catálogo: %r" % it["id"])
        vistos.add(it["id"])
        if it["tipo"] not in ("detector", "convergencia", "misto"):
            raise ErroUso("%s: tipo %r inválido" % (it["id"], it["tipo"]))
        if it["adaptador"] not in ADAPTADORES:
            raise ErroUso("%s: adaptador %r não existe" % (it["id"], it["adaptador"]))
        for e in it["estagios"]:
            if e not in cat["estagios"]:
                raise ErroUso("%s: estágio %r não está declarado" % (it["id"], e))
    return cat


# ───────────────────────────────────────────────────────── predicado declarativo

_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}
_RE_TERMO = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")


def _valor_literal(s):
    s = s.strip()
    if s.lower() in ("null", "none"):
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def no_do_perfil(p, caminho):
    cur = p
    for parte in caminho.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            raise KeyError(caminho)
        cur = cur[parte]
    return cur


def avaliar_predicado(expr, perfil):
    """`video.largura == 256 && video.fps >= 24` → (bool, motivo).

    Parser de brinquedo de propósito: sem `eval`, sem parênteses, sem precedência
    misturada. Um predicado de catálogo que precise de mais do que isto é sinal de
    que a decisão devia estar em código, não em dado."""
    if not expr:
        return True, ""
    if "||" in expr and "&&" in expr:
        raise ErroUso("predicado %r mistura && e || — separe em dois itens" % expr)
    conj = "||" if "||" in expr else "&&"
    termos = [t for t in expr.split(conj) if t.strip()]
    resultados, motivos = [], []
    for t in termos:
        m = _RE_TERMO.match(t)
        if not m:
            raise ErroUso("termo de predicado ilegível: %r" % t)
        caminho, op, lit = m.group(1), m.group(2), _valor_literal(m.group(3))
        try:
            atual = no_do_perfil(perfil, caminho)
        except KeyError:
            resultados.append(False)
            motivos.append("%s ausente no perfil" % caminho)
            continue
        r = _OPS[op](atual, lit)
        resultados.append(r)
        if not r:
            motivos.append("%s=%r, pedia %s %r" % (caminho, atual, op, lit))
    ok = any(resultados) if conj == "||" else all(resultados)
    return ok, "; ".join(motivos)


# ─────────────────────────────────────────────────────────── ADAPTADORES (§3.3)
#
# Um adaptador é uma FUNÇÃO PURA sobre string: nada de ffmpeg, nada de disco.
# Assinatura:  adaptar(stdout, stderr, exit_code, ctx) -> dict
#
#   {"unidades": int,          quantas linhas de medição foram DE FATO lidas
#    "esperadas": int|None,    quantas deveriam ser (nº de emendas, de segmentos)
#    "itens": [ {onde, tag, detalhe} ],
#    "resumo": str,            <= 90 chars, é o que vai pro stdout
#    "estado_forcado": str|None,   quando o próprio script já deu o veredito
#    "motivo": str|None}
#
# Por que parsear stdout em vez de dar `--json` aos 19 QCs: (1) cinco deles são
# editados por outras specs — uma terceira mexendo nos mesmos arquivos é o jeito
# mais rápido de perder trabalho num merge; (2) cada um é um DOCUMENTO, o
# docstring do `qc-fonemas.py` carrega a fonética que custou um defeito entregue;
# (3) o orquestrador tem que sobreviver a QC que ele não escreveu — script local
# de produção hoje, de cliente amanhã. O preço do parse frágil é pago pela regra
# `unidades == 0` nunca vira ok.


def _corta(s, n=MAX_DETALHE):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _int1(padrao, texto, default=None):
    m = re.search(padrao, texto)
    return int(m.group(1)) if m else default


_RE_AE = re.compile(r"^seg(\d+) \[([\d.]+)-([\d.]+)\]\s+(.*)$")
_TAGS_AE = [
    ("SEM PALAVRAS mas COM ENERGIA", "SEM-PALAVRAS-COM-ENERGIA"),
    ("SEM PALAVRAS e sem energia", "SEM-PALAVRAS-MUDO"),
    ("CLIP-FIM", "CLIP-FIM"),
    ("CLIP-INICIO", "CLIP-INICIO"),
    ("VAZA-PROX", "VAZA-PROX"),
]


def ad_audit_emendas(so, se, code, ctx):
    itens, n = [], 0
    for ln in so.splitlines():
        m = _RE_AE.match(ln)
        if not m:
            continue
        n += 1
        cauda = m.group(4)
        for literal, tag in _TAGS_AE:
            if literal in cauda:
                itens.append({"onde": "seg%s" % m.group(1), "tag": tag,
                              "detalhe": _corta(cauda)})
    return {"unidades": n, "esperadas": ctx.get("n_segmentos"), "itens": itens,
            "resumo": "%d segmento(s)" % n}


_RE_ATQ = re.compile(r"^\s+(⚠️ ATAQUE|ok)\s+(\S+)\s+t=\s*([-\d.]+)\s+pico\s+"
                     r"([-\d.]+)\s+piso\s+([-\d.]+)\s+incl\s+([-+\d.]+)")


def ad_qc_ataque(so, se, code, ctx):
    itens, n = [], 0
    for ln in so.splitlines():
        m = _RE_ATQ.match(ln)
        if not m:
            continue
        n += 1
        if m.group(1) != "ok":
            itens.append({"onde": "%s t=%s" % (m.group(2), m.group(3)),
                          "tag": "ATAQUE",
                          "detalhe": _corta("pico %s piso %s incl %s dB/100ms"
                                            % (m.group(4), m.group(5), m.group(6)))})
    esperadas = _int1(r"(\d+) emendas", se)
    # ⚠️ `n < esperadas` NÃO é buraco: o script pula junção contígua no mesmo src
    # (split de plano). Foi assim que ele imprimiu 22 linhas para 28 emendas na
    # `peca-01`. Registre `22/28` e a razão, não um alerta.
    return {"unidades": n, "esperadas": esperadas, "itens": itens,
            "resumo": "%s emenda(s) medida(s)" % n}


_RE_FON = re.compile(r"^seg(\d+) (fim|inicio)\s+([\d.]+)\s+\[([A-Z\-ÁÂÃÇÉÊÍÓÔÕÚ]+)\](.*)$")


def ad_qc_fonemas(so, se, code, ctx):
    itens = []
    linhas = so.splitlines()
    for i, ln in enumerate(linhas):
        m = _RE_FON.match(ln)
        if not m:
            continue
        herdado = "[HERDADO" in m.group(5)
        # a explicação fonética vem na linha SEGUINTE, indentada. É ela que diz
        # onde ouvir — repetir a tag no `detalhe` seria jogar fora o único texto
        # útil que este QC produz.
        msg = (linhas[i + 1].strip()
               if i + 1 < len(linhas) and linhas[i + 1].startswith("    ") else "")
        itens.append({"onde": "seg%s %s %s" % (m.group(1), m.group(2), m.group(3)),
                      "tag": "HERDADO" if herdado else m.group(4),
                      "detalhe": _corta(("%s: %s" % (m.group(4), msg)) if msg
                                        else m.group(4))})
    n = _int1(r"·\s*(\d+) segmentos", se, 0)
    return {"unidades": n, "esperadas": ctx.get("n_segmentos"), "itens": itens,
            "resumo": "%d segmento(s), %s alerta(s)"
                      % (n, _int1(r"(\d+) alerta", se, 0))}


_RE_ASR = re.compile(r"^\[(\d+)→(\d+)\]\s+([\d.]+)s")


def ad_qc_emendas_asr(so, se, code, ctx):
    itens, n, onde = [], 0, None
    for ln in so.splitlines():
        m = _RE_ASR.match(ln)
        if m:
            n += 1
            onde = "%s→%s %ss" % (m.group(1), m.group(2), m.group(3))
            continue
        if "⚠️ SUMIU" in ln:
            itens.append({"onde": onde or "?", "tag": "SUMIU",
                          "detalhe": _corta(ln.split("⚠️ SUMIU", 1)[1])})
        if "⚠️ VAZOU" in ln:
            itens.append({"onde": onde or "?", "tag": "VAZOU",
                          "detalhe": _corta(ln.split("⚠️ VAZOU", 1)[1])})
        if "⚠️ ORDEM-BORDA" in ln:
            itens.append({"onde": onde or "?", "tag": "ORDEM-BORDA",
                          "detalhe": _corta(ln.split("⚠️ ORDEM-BORDA", 1)[1])})
        if "⚠️ REVISAO" in ln:
            itens.append({"onde": onde or "?", "tag": "REVISAO-ASR",
                          "detalhe": _corta(ln.split("⚠️ REVISAO", 1)[1])})
    return {"unidades": n, "esperadas": _int1(r"(\d+) emendas", se),
            "itens": itens, "resumo": "%d emenda(s) transcrita(s)" % n}


_RE_CDB_CURTO = re.compile(r"^seg(\d+) \[PLANO-CURTO\]\s+(.*)$")
_RE_CDB_SRC = re.compile(r"^(\S+): (\d+) cortes já existentes")
_RE_CDB_COIN = re.compile(r"^seg(\d+) ✔ (\w+) ([\d.]+)")


def ad_cortes_do_bruto(so, se, code, ctx):
    itens, n = [], 0
    for ln in so.splitlines():
        m = _RE_CDB_CURTO.match(ln)
        if m:
            itens.append({"onde": "seg%s" % m.group(1), "tag": "PLANO-CURTO",
                          "detalhe": _corta(m.group(2))})
    for ln in se.splitlines():
        m = _RE_CDB_SRC.match(ln)
        if m:
            n += 1
        m = _RE_CDB_COIN.match(ln)
        if m:
            itens.append({"onde": "seg%s %s %s" % m.groups(), "tag": "COINCIDE",
                          "detalhe": "corte meu coincide com corte do bruto"})
    if "take contínuo" in se and n == 0:
        n = len(ctx.get("srcs") or []) or 1
    return {"unidades": n, "esperadas": len(ctx.get("srcs") or []) or None,
            "itens": itens, "resumo": "%d bruto(s) varrido(s)" % n}


_RE_CAUDA_VARR = re.compile(r"varredura: (\d+) segmento\(s\), (\d+) janela")
_RE_CAUDA_SEG = re.compile(r"↳ seg(\d+)\s+(\S+)\s+.*cauda (\d+) ms")


def ad_qc_cauda(so, se, code, ctx):
    txt = so + "\n" + se
    m = _RE_CAUDA_VARR.search(txt)
    n = int(m.group(1)) if m else 0
    janelas = int(m.group(2)) if m else 0
    itens = [{"onde": "seg%s %s" % (a, b), "tag": "CAUDA-LONGA",
              "detalhe": "cauda %s ms" % c}
             for a, b, c in _RE_CAUDA_SEG.findall(txt)]
    if "MEDIÇÃO INVÁLIDA" in txt or code == 3:
        return {"unidades": 0, "esperadas": n, "itens": [],
                "resumo": "medição inválida (piso abaixo do ruído da sala)",
                "estado_forcado": "nao_verificado", "motivo": "insumo"}
    if "CONTROLE FALHOU" in txt or code == 2:
        itens.append({"onde": "--controle", "tag": "CONTROLE-FALHOU",
                      "detalhe": "o defeito plantado NÃO foi acusado: o defeito "
                                 "está no QC, não na peça"})
    if "REPROVADO" in txt:
        m2 = re.search(r"REPROVADO: p90 (\d+) ms > ([\d.]+) ms", txt)
        itens.append({"onde": "peça", "tag": "CAUDA-REPROVADA",
                      "detalhe": _corta(m2.group(0) if m2 else "p90 acima do teto")})
    return {"unidades": n, "esperadas": ctx.get("n_segmentos"), "itens": itens,
            "resumo": "%d segmento(s), %d janela(s) de envelope" % (n, janelas)}


_RE_RESP_VARR = re.compile(r"varredura: (\d+) segmento\(s\), (\d+) janela")
_RE_RESP_ITEM = re.compile(
    r"↳ seg(\d+)\s+(\S+)\s+([\d.]+)-\s*([\d.]+)\s+respiro (\d+) ms a ([-\d]+) dB")
_RE_RESP_TOT = re.compile(r"respiro: (\d+) banda\(s\).*?(\d+) SOBRANDO.*?(\d+) descartada")


def ad_qc_respiro(so, se, code, ctx):
    """A sonda de respiro (SPEC-48/H48-2). `unidades` = segmentos varridos.

    ⚠️ `MEDIÇÃO INVÁLIDA` e o exit 3 do script viram NÃO VERIFICADO, nunca ok: sem
    EDL ou sem transcript ele não sabe separar respiro de fala fraca, e um verde
    ali seria o mesmo silêncio que a bateria existe para não deixar passar."""
    txt = so + "\n" + se
    m = _RE_RESP_VARR.search(txt)
    n = int(m.group(1)) if m else 0
    janelas = int(m.group(2)) if m else 0
    if "MEDIÇÃO INVÁLIDA" in txt or code == 3:
        return {"unidades": 0, "esperadas": ctx.get("n_segmentos"), "itens": [],
                "resumo": _corta([l for l in txt.splitlines()
                                  if "MEDIÇÃO INVÁLIDA" in l] or ["sem medição"],
                                 MAX_RESUMO),
                "estado_forcado": "nao_verificado", "motivo": "insumo"}
    itens = [{"onde": "seg%s %s (%s–%ss)" % (a, b, c, d), "tag": "RESPIRO",
              "detalhe": "%s ms a %s dB" % (e, f)}
             for a, b, c, d, e, f in _RE_RESP_ITEM.findall(txt)]
    if "CONTROLE FALHOU" in txt or code == 2:
        itens.append({"onde": "--controle", "tag": "CONTROLE-FALHOU",
                      "detalhe": "o defeito plantado NÃO foi acusado (ou fala "
                                 "foi): o defeito está no QC, não na peça"})
    t = _RE_RESP_TOT.search(txt)
    resumo = ("%d segmento(s), %d janela(s); %s banda(s), %s sobrando, %s "
              "descartada(s) por fala" % (n, janelas, t.group(1), t.group(2),
                                          t.group(3))) if t else \
        "%d segmento(s), %d janela(s) de envelope" % (n, janelas)
    return {"unidades": n, "esperadas": ctx.get("n_segmentos"), "itens": itens,
            "resumo": _corta(resumo, MAX_RESUMO)}


def ad_qc_nivel(so, se, code, ctx):
    try:
        doc = json.loads(so)
    except ValueError:
        return {"unidades": 0, "esperadas": None, "itens": [],
                "resumo": "saída não é o JSON de benchmark.qc-nivel/v1",
                "estado_forcado": "nao_verificado", "motivo": "sem-saida-parseavel"}
    med, ver = doc.get("medicao", {}), doc.get("veredito", {})
    itens = []
    if doc.get("modo") == "balanco":
        n = med.get("n_ranges", 0)
        for r in doc.get("ranges", []):
            estado = str(r.get("estado", ""))
            if estado in ("ok", ""):
                continue
            tag = {"sem-nivel": "SEM-NIVEL", "amostra-curta": "AMOSTRA-CURTA"}.get(
                estado, "NIVEL-BAIXO")
            itens.append({"onde": "range %s" % r.get("i", r.get("range", "?")),
                          "tag": tag,
                          "detalhe": _corta("%s dB vs ref %s"
                                            % (r.get("nivel_db"), r.get("ref_db")))})
        resumo = "%d range(s), máscara %s" % (n, med.get("mascara"))
    else:
        n = med.get("n_janelas", 0)
        for r in (doc.get("runs") or doc.get("achados") or [])[:5]:
            itens.append({"onde": "%.3f–%.3f" % (r.get("ini", 0.0), r.get("fim", 0.0)),
                          "tag": "NIVEL-RUN",
                          "detalhe": _corta("%s dB (Δ%s)"
                                            % (r.get("nivel_db"), r.get("delta_db")))})
        resumo = "%d janela(s) varrida(s)" % n
    if ver.get("aprovado") is False and not itens:
        itens.append({"onde": "peça", "tag": "NIVEL-BAIXO",
                      "detalhe": "%s flag(s)" % ver.get("flags")})
    return {"unidades": n, "esperadas": None, "itens": itens, "resumo": resumo}


_RE_AVS_ITEM = re.compile(r"")


def ad_avsync(so, se, code, ctx):
    try:
        doc = json.loads(so)
    except ValueError:
        return {"unidades": 0, "esperadas": None, "itens": [],
                "resumo": "saída não é o JSON de benchmark.qc-avsync/v1",
                "estado_forcado": "nao_verificado", "motivo": "sem-saida-parseavel"}
    n = doc.get("n_com_marcador", 0)
    sem = doc.get("n_sem_marcador", 0)
    itens = [{"onde": f.get("onde", "?"), "tag": f["tag"],
              "detalhe": _corta(f.get("detalhe", ""))}
             for f in doc.get("flags", [])]
    if n == 0 and sem:
        return {"unidades": 0, "esperadas": n + sem, "itens": itens,
                "resumo": "%d/%d fronteira(s) sem marcador de áudio" % (sem, n + sem),
                "estado_forcado": "nao_verificado", "motivo": "insumo"}
    return {"unidades": n, "esperadas": n + sem, "itens": itens,
            "resumo": _corta(doc.get("resumo", "%d fronteira(s) com marcador" % n),
                             MAX_RESUMO)}


def ad_qc_cor(so, se, code, ctx):
    txt = so + "\n" + se
    n = sum(int(x) for x in re.findall(r"varreu (\d+)", txt))
    itens = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("❌"):
            itens.append({"onde": _corta(s[1:].strip(), 40), "tag": "COR-ROTULO",
                          "detalhe": _corta(s)})
        elif s.startswith("🔴 PIXELS"):
            itens.append({"onde": "cadeia", "tag": "COR-ESTAGIO", "detalhe": _corta(s)})
        elif s.startswith("⏭️ SKIP"):
            itens.append({"onde": "seção", "tag": "SECAO-NAO-MEDIDA",
                          "detalhe": _corta(s)})
    pulos = sum(1 for i in itens if i["tag"] == "SECAO-NAO-MEDIDA")
    # 🔴 o `qc-cor.py` sai 0 mesmo pulando 2 das 4 seções. Sem esta contagem, um
    # SKIP viraria aprovação silenciosa — que é exatamente o defeito que a bateria
    # existe para não deixar acontecer.
    return {"unidades": n, "esperadas": None, "itens": itens,
            "resumo": "%d arquivo(s), %d seção(ões) não medida(s)" % (n, pulos)}


# ⚠️ `re.M` NÃO é decoração: sem ele, um `^` dentro de `findall` casa SÓ no início
# da string inteira. Medido na fixture: 1 achado lido de 21 impressos. Um
# adaptador que subconta achados é o mesmo defeito de sempre — verde por cegueira.
_RE_FLK = re.compile(r"^t=([\d.]+) \[(\w+)\] Δ=([-+\d.]+)", re.M)


def ad_flicker(so, se, code, ctx):
    n = _int1(r"varrendo (\d+) frames", se, 0)
    itens = [{"onde": "t=%s [%s]" % (a, b), "tag": "SALTO", "detalhe": "Δ=%s" % c}
             for a, b, c in _RE_FLK.findall(so)]
    return {"unidades": n, "esperadas": None, "itens": itens,
            "resumo": "%d frame(s), %s salto(s)"
                      % (n, _int1(r"(\d+) salto", se, len(itens)))}


_RE_PRETO = re.compile(r"black_start:(\S+) black_end:(\S+) black_duration:(\S+)")


def ad_preto(so, se, code, ctx):
    txt = so + "\n" + se
    frames = 0
    for m in re.finditer(r"frame=\s*(\d+)", txt):
        frames = max(frames, int(m.group(1)))
    itens = [{"onde": "%s–%ss" % (a, b), "tag": "PRETO",
              "detalhe": "duração %ss" % c} for a, b, c in _RE_PRETO.findall(txt)]
    return {"unidades": frames, "esperadas": None, "itens": itens,
            "resumo": "%d frame(s) varrido(s)" % frames}


def ad_qc_alpha(so, se, code, ctx):
    try:
        doc = json.loads(so)
    except ValueError:
        return {"unidades": 0, "esperadas": None, "itens": [],
                "resumo": "saída não é JSON", "estado_forcado": "nao_verificado",
                "motivo": "sem-saida-parseavel"}
    n = doc.get("frames_lidos") or doc.get("frames") or 0
    itens = []
    if code != 0:
        itens.append({"onde": os.path.basename(str(doc.get("arquivo", "?"))),
                      "tag": "ALPHA-REPROVADO",
                      "detalhe": _corta(doc.get("motivo") or doc.get("veredito", ""))})
    return {"unidades": n, "esperadas": None, "itens": itens,
            "resumo": "%d frame(s) de alpha" % n}


def ad_qc_fala(so, se, code, ctx):
    txt = so + "\n" + se
    n = len(re.findall(r"^\s*\d\.", txt, re.M)) or (1 if txt.strip() else 0)
    itens = []
    if code != 0:
        itens.append({"onde": ctx.get("rotulo", "par"), "tag": "ACUSTICA",
                      "detalhe": _corta([l for l in txt.splitlines() if l.strip()][-1]
                                        if txt.strip() else "acústica reprovou")})
    if re.search(r"diff|difere", txt, re.I):
        itens.append({"onde": ctx.get("rotulo", "par"), "tag": "ASR-DIFF",
                      "detalhe": "o ASR divergiu — indício de onde ouvir, não prova"})
    return {"unidades": n, "esperadas": None, "itens": itens,
            "resumo": "1 par original/editado"}


_RE_JCUT_TESTE = re.compile(r"^\s+\[(\d)\]", re.M)   # re.M: ver a nota em _RE_FLK


def ad_qc_jcut(so, se, code, ctx):
    txt = so + "\n" + se
    n = len(set(_RE_JCUT_TESTE.findall(txt)))
    itens = [{"onde": "jcut", "tag": "JCUT-REPROVA", "detalhe": _corta(ln.strip()[2:])}
             for ln in txt.splitlines() if ln.strip().startswith("✗")]
    return {"unidades": n, "esperadas": 5, "itens": itens,
            "resumo": "%d/5 teste(s) de J-cut" % n}


_RE_LOUD = re.compile(r"→ (OK|REPROVA)(?::\s*(.*))?$")


def ad_loudness(so, se, code, ctx):
    m = None
    for ln in so.splitlines():
        mm = _RE_LOUD.search(ln)
        if mm:
            m = mm
            linha = ln
    if not m:
        return {"unidades": 0, "esperadas": 1, "itens": [],
                "resumo": "sem linha de veredito de loudness",
                "estado_forcado": "nao_verificado", "motivo": "sem-saida-parseavel"}
    itens = []
    if m.group(1) == "REPROVA":
        itens.append({"onde": "entregável", "tag": "LOUDNESS",
                      "detalhe": _corta(m.group(2) or "fora da tolerância")})
    med = re.search(r"(I=[-\d.]+ TP=[-\d.]+ LRA=[-\d.]+)", linha)
    return {"unidades": 1, "esperadas": 1, "itens": itens,
            "resumo": _corta(med.group(1) if med else "medido", MAX_RESUMO)}


def ad_generico(so, se, code, ctx):
    """Para script que este orquestrador não escreveu (extras de `qc/local.json`).

    Conta linhas e usa o exit code, SEM interpretar. É o contrato que funciona
    para qualquer QC — inclusive de cliente."""
    linhas = [l for l in (so + "\n" + se).splitlines() if l.strip()]
    n = len(linhas)
    itens = []
    if code != 0:
        itens.append({"onde": ctx.get("rotulo", ctx.get("id", "?")),
                      "tag": (ctx.get("promove_falha") or ["EXIT"])[0],
                      "detalhe": _corta(linhas[-1] if linhas else "exit %d" % code)})
    return {"unidades": n, "esperadas": None, "itens": itens,
            "resumo": "%d linha(s) de saída" % n}


def ad_edl_ver(so, se, code, ctx):
    txt = (so + se).strip()
    n = _int1(r"·\s*(\d+) segmentos", txt, 0)
    if "ausente" in txt:
        return {"unidades": 0, "esperadas": n, "itens": [],
                "resumo": "timeline_real ausente — rode montar.sh",
                "estado_forcado": "nao_verificado", "motivo": "insumo"}
    itens = []
    if "VELHA" in txt:
        itens.append({"onde": "edl.json", "tag": "TIMELINE-VELHA",
                      "detalhe": "a EDL mudou depois do render — todo QC de emenda "
                                 "está medindo o vídeo errado"})
    m = re.search(r"fresca \([^,]+, (\d+) frames, ([\d.]+)s\)", txt)
    return {"unidades": n, "esperadas": ctx.get("n_segmentos"), "itens": itens,
            "resumo": ("%d seg · %s frames · %ss" % (n, m.group(1), m.group(2))
                       if m else _corta(txt, MAX_RESUMO))}


_RE_CI_VARR = re.compile(
    r"varrido:\s*(\d+) frames?,\s*(\d+) fronteira\(s\) declarada\(s\),\s*"
    r"(\d+) esperado_visivel=sim")
_RE_CI_ITEM = re.compile(
    r"^(FRONTEIRA-SEM-IMAGEM|DUVIDOSA|SEM-MARCADOR)\s+k=(\d+)\s+frame=(\d+)\s+"
    r"t=([\d.]+)\s+razao=([\d.]+)")
_RE_CI_SF = re.compile(
    r"^IMAGEM-SEM-FRONTEIRA(\s+\[HERDADO\])?\s+frame=(\d+)\s+t=([\d.]+)\s+"
    r"razao=([\d.]+)")
_RE_CI_DESL = re.compile(r"^DESLOCAMENTO-SISTEMATICO\s+([-+]\d+)\s+frame\s+\((\d+)/(\d+)\)")
_RE_CI_NV = re.compile(
    r"^(EDL-VS-SEGS|SEM-CORRESPONDENCIA|SEM-VIDEO|SEM-SEGS|TIMELINE-VELHA|"
    r"EDL-ILEGIVEL|CORTES-ILEGIVEL):\s*(.+)$")


def ad_corte_imagem(so, se, code, ctx):
    """A sonda de imagem (SPEC-26). `unidades` = fronteiras DECLARADAS.

    ⚠️ Percorre linha a linha em vez de `re.findall` com `^`: sem `re.M` o
    findall lê o primeiro achado e joga o resto fora — foi medido, "1 de 21"."""
    txt = so + "\n" + se
    m = _RE_CI_VARR.search(txt)
    n = int(m.group(2)) if m else 0
    frames = int(m.group(1)) if m else 0
    itens, forcado, motivo = [], None, None
    for ln in txt.splitlines():
        ln = ln.strip()
        mv = _RE_CI_NV.match(ln)
        if mv:
            # 🔴 EDL-VS-SEGS e SEM-CORRESPONDENCIA são promovidos a FALHA pelo
            # catálogo, MAS a sonda não mediu nada — então o item é o achado E o
            # estado é `nao_verificado`. Silêncio aqui seria aprovar um órfão.
            itens.append({"onde": ctx.get("rotulo", "corte-imagem"),
                          "tag": mv.group(1), "detalhe": _corta(mv.group(2))})
            forcado, motivo = "nao_verificado", "insumo"
            continue
        md = _RE_CI_DESL.match(ln)
        if md:
            itens.append({"onde": "peça", "tag": "DESLOCAMENTO-SISTEMATICO",
                          "detalhe": _corta("%s frame em %s/%s fronteiras — bug de "
                                            "cadeia, não de fronteira"
                                            % md.groups())})
            continue
        mi = _RE_CI_ITEM.match(ln)
        if mi:
            itens.append({"onde": "k=%s frame %s (t=%s)"
                                  % (mi.group(2), mi.group(3), mi.group(4)),
                          "tag": mi.group(1),
                          "detalhe": _corta("razao %s" % mi.group(5))})
            continue
        ms = _RE_CI_SF.match(ln)
        if ms:
            itens.append({"onde": "frame %s (t=%s)" % (ms.group(2), ms.group(3)),
                          "tag": ("IMAGEM-SEM-FRONTEIRA-HERDADA" if ms.group(1)
                                  else "IMAGEM-SEM-FRONTEIRA"),
                          "detalhe": _corta("razao %s" % ms.group(4))})
    conf = re.search(r"(\d+)/(\d+) confirmadas", txt)
    resumo = ("%s/%s confirmadas em %d frames" % (conf.group(1), conf.group(2), frames)
              if conf else _corta(txt.splitlines()[-1] if txt.strip() else "sem saída",
                                  MAX_RESUMO))
    if forcado and itens:
        # o `prova_de_dentes` do catálogo troca o motivo por `sem-prova-de-dentes`
        # e o que sobrevive para o leitor é o RESUMO: a causa tem que estar nele,
        # senão o NÃO VERIFICADO chega sem dizer o que faltou.
        resumo = _corta("%s: %s" % (itens[0]["tag"], itens[0]["detalhe"]), MAX_RESUMO)
    out = {"unidades": n, "esperadas": (ctx.get("n_segmentos") or 1) - 1,
           "itens": itens, "resumo": resumo}
    if forcado:
        out["estado_forcado"] = forcado
        out["motivo"] = motivo
    return out


_RE_SFX_VARR = re.compile(
    r"arquivos_medidos:\s*(\d+)(?:\s*·\s*(\d+) ok\s*·\s*(\d+) achado)?")
_RE_SFX_ITEM = re.compile(r"^([A-ZÁ-Ú/-]+)\s+(\S+)\s+onset=([\d.]+)ms\s+"
                          r"corpo=([\d.]+)ms\s+\((\w+)\)")
_RE_SFX_AUS = re.compile(r"^SFX-AUSENTE\s+(\S+)")
_RE_SFX_NV = re.compile(r"^(SEM-BIBLIOTECA|SEM-ARQUIVOS|SEM-PERFIL|SEM-MEDICAO):\s*(.+)$")


def ad_qc_sfx(so, se, code, ctx):
    """A sonda de SFX (SPEC-26). `unidades` = arquivos de áudio medidos."""
    txt = so + "\n" + se
    m = _RE_SFX_VARR.search(txt)
    n = int(m.group(1)) if m else 0
    itens, forcado, motivo = [], None, None
    for ln in txt.splitlines():
        ln = ln.strip()
        mv = _RE_SFX_NV.match(ln)
        if mv:
            itens.append({"onde": "biblioteca", "tag": mv.group(1),
                          "detalhe": _corta(mv.group(2))})
            forcado, motivo = "nao_verificado", "insumo"
            continue
        ma = _RE_SFX_AUS.match(ln)
        if ma:
            itens.append({"onde": ma.group(1), "tag": "SFX-AUSENTE",
                          "detalhe": "referenciado e ausente da biblioteca"})
            continue
        mi = _RE_SFX_ITEM.match(ln)
        if mi:
            for tag in mi.group(1).split("/"):
                itens.append({"onde": mi.group(2), "tag": tag,
                              "detalhe": _corta("onset %s ms, corpo %s ms (%s)"
                                                % (mi.group(3), mi.group(4),
                                                   mi.group(5)))})
    ok_n = m.group(2) if (m and m.group(2)) else None
    resumo = ("%d arquivo(s), %s ok" % (n, ok_n)) if ok_n else "%d arquivo(s)" % n
    if forcado and itens:
        resumo = _corta("%s: %s" % (itens[0]["tag"], itens[0]["detalhe"]), MAX_RESUMO)
    out = {"unidades": n, "esperadas": None, "itens": itens, "resumo": resumo}
    if forcado:
        out["estado_forcado"] = forcado
        out["motivo"] = motivo
    return out


ADAPTADORES = {
    "audit_emendas": ad_audit_emendas,
    "corte_imagem": ad_corte_imagem,
    "qc_sfx": ad_qc_sfx,
    "qc_ataque": ad_qc_ataque,
    "qc_fonemas": ad_qc_fonemas,
    "qc_emendas_asr": ad_qc_emendas_asr,
    "cortes_do_bruto": ad_cortes_do_bruto,
    "qc_cauda": ad_qc_cauda,
    "qc_respiro": ad_qc_respiro,
    "qc_nivel": ad_qc_nivel,
    "avsync": ad_avsync,
    "qc_cor": ad_qc_cor,
    "flicker": ad_flicker,
    "preto": ad_preto,
    "qc_alpha": ad_qc_alpha,
    "qc_fala": ad_qc_fala,
    "qc_jcut": ad_qc_jcut,
    "loudness": ad_loudness,
    "edl_ver": ad_edl_ver,
    "generico": ad_generico,
}


# ─────────────────────────────────────────────────────────────── classificação
#
# REGRAS NOMEADAS. Elas têm nome porque o `--autoteste` precisa DESLIGAR uma para
# provar que o portão tem dentes: um portão que não muda de cor quando você quebra
# uma regra dele é indistinguível de um portão que nunca testou nada.

REGRAS = ("convergencia-falha", "promove-falha", "rebaixa-achado", "unidade-zero")


def classificar(item, res, desligadas=()):
    """(estado, achados, falhas) — quem decide é o CATÁLOGO, não este código."""
    if res.get("estado_forcado"):
        return res["estado_forcado"], [], []
    promove = set(item.get("promove_falha") or [])
    rebaixa = set(item.get("rebaixa_achado") or [])
    if "promove-falha" in desligadas:
        promove = set()
    if "rebaixa-achado" in desligadas:
        rebaixa = set()
    achados, falhas = [], []
    for a in res["itens"]:
        tag = a["tag"]
        if tag in promove:
            alvo = falhas
        elif tag in rebaixa:
            alvo = achados
        elif item["tipo"] == "convergencia":
            alvo = achados if "convergencia-falha" in desligadas else falhas
        else:                       # detector, e misto sem promoção explícita
            alvo = achados
        alvo.append(a)
    if res["unidades"] == 0 and "unidade-zero" not in desligadas:
        # 🔴 A regra 1. Não negociável: sem contagem não há aprovação.
        return "nao_verificado", achados, falhas
    if falhas:
        return "falha", achados, falhas
    return ("achado" if achados else "ok"), achados, falhas


# ─────────────────────────────────────────────────────── contexto da produção

def _listar_raiz(d, *, listar=None):
    listar = listar or os.listdir
    try:
        return list(listar(d))
    except OSError as exc:
        raise ErroUso("não foi possível listar a raiz da produção: %s" % exc) from exc


def _glob1(d, padroes, nomes=None):
    nomes = _listar_raiz(d) if nomes is None else nomes
    for p in padroes:
        achados = sorted(os.path.join(d, nome) for nome in nomes
                          if fnmatch.fnmatchcase(nome, p))
        if achados:
            return os.path.relpath(achados[0], d)
    return None


def _nome_final_reconhecido(nome):
    if not nome.isascii():
        return False
    return re.fullmatch(r"(?:v-final|v2-final).*\.mp4", nome,
                        flags=re.ASCII | re.IGNORECASE) is not None


def _final1(d, nomes=None, *, listar=None):
    """Resolve o estágio final com a mesma política case-insensitive do gate."""
    nomes = _listar_raiz(d, listar=listar) if nomes is None else nomes
    nomes = sorted(nomes,
                   key=lambda n: (unicodedata.normalize("NFKC", n).casefold(), n))
    candidatos = []
    for nome in nomes:
        if not _nome_final_reconhecido(nome):
            continue
        caminho = os.path.join(d, nome)
        try:
            modo = os.lstat(caminho).st_mode
        except OSError as exc:
            raise ErroUso("não foi possível inspecionar final %s: %s"
                          % (nome, exc)) from exc
        if not (stat.S_ISREG(modo) or stat.S_ISLNK(modo)):
            raise ErroUso("entrada final reconhecida não é arquivo regular: %s" % nome)
        candidatos.append(nome)
    return candidatos[0] if candidatos else None


def carregar_perfil(d):
    sys.path.insert(0, dir_scripts())
    try:
        import perfil as perfil_mod
        p = perfil_mod.carregar(d, quieto=True)
        # o `perfil.py` marca o fallback histórico no próprio nome; sem perfil.json
        # no disco também é fallback, e o cabeçalho tem que dizer isso.
        fallback = (str(p.get("nome", "")).endswith("-fallback")
                    or not os.path.exists(os.path.join(d, "perfil.json")))
        return p, fallback
    except Exception:                                      # noqa: BLE001
        return {}, True


def carregar_local(d):
    p = os.path.join(d, "qc", "local.json")
    if not os.path.exists(p):
        return {}
    with open(p) as fh:
        doc = json.load(fh)
    if doc.get("schema") != CONTRATO_LOCAL:
        raise ErroUso("%s: schema %r, esperado %r"
                      % (p, doc.get("schema"), CONTRATO_LOCAL))
    return doc


def contexto(d, cat):
    ctx = {"dir": d, "srcs": [], "n_segmentos": None}
    nomes_raiz = _listar_raiz(d)
    ctx["perfil"], ctx["perfil_fallback"] = carregar_perfil(d)
    ctx["local"] = carregar_local(d)
    if os.path.exists(os.path.join(d, "edl.json")):
        try:
            sys.path.insert(0, dir_scripts())
            import edl_io
            segs = edl_io.segmentos(d)
            ctx["n_segmentos"] = len(segs)
            ctx["srcs"] = sorted({s["src"] for s in segs if "src" in s})
        except SystemExit:
            ctx["edl_quebrada"] = True
        except Exception:                                  # noqa: BLE001
            ctx["edl_quebrada"] = True
    ctx["_estagios"] = cat["estagios"]
    for nome, bloco in cat["estagios"].items():
        ctx["artefato_" + nome] = (_final1(d, nomes_raiz) if nome == "final"
                                   else _glob1(d, bloco["artefato"], nomes_raiz))
    return ctx


def resolver_estagio(cat, ctx, pedido):
    """O mais AVANÇADO cujo artefato primário existe. Determinístico, e diz por quê."""
    ordem = list(cat["estagios"].keys())
    if pedido and pedido != "auto":
        if pedido not in cat["estagios"]:
            raise ErroUso("estágio %r não existe (tem: %s)"
                          % (pedido, ", ".join(ordem)))
        return pedido, "pedido explicitamente"
    for nome in reversed(ordem):
        if ctx.get("artefato_" + nome):
            faltando = [n for n in ordem if ordem.index(n) < ordem.index(nome)
                        and not ctx.get("artefato_" + n)]
            return nome, ("auto: %s presente%s" % (
                ctx["artefato_" + nome],
                "; %s ausente(s)" % ", ".join(faltando) if faltando else ""))
    return ordem[0], "auto: nenhum artefato primário encontrado — %s ausente" % (
        ", ".join(cat["estagios"][ordem[0]]["artefato"]))


# ─────────────────────────────────────────────────────────────────── execução

def _expandir(tok, ctx, estagio, extra=None):
    extra = extra or {}
    if tok == "{srcs}":
        return ctx["srcs"]
    out = tok
    for k, v in extra.items():
        out = out.replace("{%s}" % k, str(v))
    out = out.replace("{dir}", ctx["dir"])
    out = out.replace("{scripts}", dir_scripts())
    out = out.replace("{python}", sys.executable)
    out = out.replace("{video}", os.path.join(
        ctx["dir"], ctx.get("artefato_" + estagio) or ""))
    out = out.replace("{artefato}", os.path.join(
        ctx["dir"], ctx.get("artefato_" + estagio) or ""))
    for m in re.finditer(r"\{perfil\.([\w.]+)\}", out):
        try:
            v = no_do_perfil(ctx["perfil"], m.group(1))
        except KeyError:
            v = ""
        out = out.replace(m.group(0), str(v))
    return [out]


def montar_argv(item, ctx, estagio, extra=None):
    ex = item.get("exec") or {}
    if "sem_script" in ex:
        return None, "sem-script", ex["sem_script"]
    if "cmd" in ex:
        argv = []
        for t in ex["cmd"]:
            argv += _expandir(t, ctx, estagio, extra)
        return argv, None, None
    script = ex.get("script")
    if not script:
        return None, "sem-script", "o item não declara `script` nem `cmd`"
    if ex.get("skill"):
        alvo = os.path.join(dir_skills(), ex["skill"], "scripts", script)
    else:
        alvo = os.path.join(dir_scripts(), script)
    if not os.path.exists(alvo):
        return None, "sem-script", "%s não existe" % alvo
    argv = [sys.executable, alvo]
    for t in ex.get("argv", []):
        argv += _expandir(t, ctx, estagio, extra)
    for pred, args in ex.get("argv_se", []):
        ok, _ = avaliar_predicado(pred, ctx["perfil"])
        if ok:
            for t in args:
                argv += _expandir(t, ctx, estagio, extra)
    return argv, None, None


def checar_insumos(item, ctx, estagio, ambiente=None):
    faltando = []
    for req in item.get("requer", []):
        if req == "{transcritos}":
            # O auditor usa exatamente este resolvedor. Repetir aqui um glob
            # mais estreito fazia a bateria pular layouts que o próprio script
            # aceita, como transcript.json na raiz ou transcritos.json.
            try:
                sys.path.insert(0, dir_scripts())
                import palavras
                palavras.resolver_transcritos(ctx["dir"], ctx["srcs"])
            except (palavras.ErroPalavras, OSError, ValueError) as e:
                faltando.append("transcritos (%s)" % _corta(str(e), 80))
            continue
        if req == "{srcs}":
            for s in ctx["srcs"]:
                if not os.path.exists(os.path.join(ctx["dir"], s)) \
                        and not os.path.exists(s):
                    faltando.append(s)
            if not ctx["srcs"]:
                faltando.append("src da EDL")
            continue
        if req.startswith("env:"):
            nome = req[4:]
            valor = (ambiente or {}).get(nome) if ambiente is not None else \
                resolver_credencial(nome)[0]
            if not valor:
                return "ambiente", ("%s não foi resolvida no ambiente nem em "
                                     "$ILHA_HOME/.env" % nome)
            continue
        if req.startswith("local:"):
            if not ctx["local"].get(req[6:]):
                return "insumo", "nada declarado em qc/local.json → %s" % req[6:]
            continue
        alvo = req
        if req in ("{video}", "{artefato}"):
            alvo = ctx.get("artefato_" + estagio) or ""
            if not alvo:
                # nomeie o ARTEFATO que falta, nunca o placeholder: quem lê a
                # mensagem precisa saber o que renderizar, não como o catálogo
                # escreveu a variável.
                faltando.append(" ou ".join(ctx["_artefatos_do_estagio"]))
                continue
        if not glob.glob(os.path.join(ctx["dir"], alvo)):
            faltando.append(req)
    if faltando:
        return "insumo", "falta " + ", ".join(sorted(set(faltando))[:4])
    return None, None


def executar_item(item, ctx, estagio, extra=None, rotulo=None):
    """Devolve o dict do item já classificado (mas ainda sem cor de estado final)."""
    t0 = time.time()
    ctx = {**ctx, "_artefatos_do_estagio": ctx["_estagios"][estagio]["artefato"]}
    base = {"id": rotulo or item["id"], "titulo": item.get("titulo", ""),
            "tipo": item["tipo"], "classe": item.get("classe", "qc"),
            "unidade": item["unidade"], "nota_classe": item.get("nota_classe", "")}

    pred = item.get("requer_perfil")
    if pred:
        ok, motivo = avaliar_predicado(pred, ctx["perfil"])
        if not ok:
            return {**base, "estado": "nao_verificado", "motivo": "perfil",
                    "detalhe": motivo, "unidades": 0, "esperadas": None,
                    "achados": [], "falhas": [], "resumo": "", "exec": None}

    ambiente = ambiente_do_item(item)
    motivo, detalhe = checar_insumos(item, ctx, estagio, ambiente)
    if motivo:
        return {**base, "estado": "nao_verificado", "motivo": motivo,
                "detalhe": detalhe, "unidades": 0, "esperadas": None,
                "achados": [], "falhas": [], "resumo": "", "exec": None}

    argv, motivo, detalhe = montar_argv(item, ctx, estagio, extra)
    if argv is None:
        return {**base, "estado": "nao_verificado", "motivo": motivo,
                "detalhe": detalhe, "unidades": 0, "esperadas": None,
                "achados": [], "falhas": [], "resumo": "", "exec": None}

    timeout = max(120, int(item.get("custo_s", 30)) * 20)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           cwd=ctx["dir"] if item.get("cwd_producao") else None,
                           env=ambiente)
        so, se, code = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return {**base, "estado": "nao_verificado", "motivo": "timeout",
                "detalhe": "estourou %ds (custo_s %s × 20)"
                           % (timeout, item.get("custo_s")),
                "unidades": 0, "esperadas": None, "achados": [], "falhas": [],
                "resumo": "", "exec": {"argv": argv, "exit": None,
                                       "duracao_s": round(time.time() - t0, 1)}}
    except OSError as e:
        return {**base, "estado": "erro", "motivo": "ambiente", "detalhe": str(e),
                "unidades": 0, "esperadas": None, "achados": [], "falhas": [],
                "resumo": "", "exec": {"argv": argv, "exit": None, "duracao_s": 0.0}}

    ctx_ad = {**ctx, "id": item["id"], "rotulo": rotulo or item["id"],
              "promove_falha": item.get("promove_falha")}
    res = ADAPTADORES[item["adaptador"]](so, se, code, ctx_ad)
    anormal, anormal_detalhe = _saida_anormal(so, se, code, res)

    if item.get("prova_de_dentes") and res["unidades"] == 0:
        estado, motivo = "nao_verificado", "sem-prova-de-dentes"
        achados = falhas = []
    else:
        estado, achados, falhas = classificar(item, res, ctx.get("_desligadas", ()))
        motivo = res.get("motivo") if estado == "nao_verificado" else None
        if estado == "nao_verificado" and not motivo:
            motivo = "sem-saida-parseavel"
    detalhe = res.get("resumo", "")
    if anormal:
        # 🔴 regra 4 do topo. A ordem importa: FALHA sobrevive (não se esconde o
        # defeito que o QC achou antes de morrer), tudo o mais desce para NÃO
        # VERIFICADO. `ok` e `achado` não podem existir aqui.
        if estado == "falha":
            detalhe = _corta("%s ⚠️ %s: %s" % (detalhe, anormal, anormal_detalhe),
                             MAX_RESUMO)
        else:
            estado, motivo = "nao_verificado", anormal
            achados, falhas = [], []
            detalhe = _corta(anormal_detalhe, MAX_RESUMO)
    return {**base, "estado": estado, "motivo": motivo,
            "detalhe": detalhe,
            "unidades": res["unidades"], "esperadas": res.get("esperadas"),
            "achados": achados, "falhas": falhas, "resumo": detalhe,
            "anormal": ({"motivo": anormal, "detalhe": anormal_detalhe}
                        if anormal else None),
            "exec": {"argv": [os.path.basename(argv[1]) if len(argv) > 1 else argv[0]]
                             + argv[2:], "exit": code,
                     "duracao_s": round(time.time() - t0, 1)},
            "_log": (so, se)}


# ────────────────────────────────────────── o guarda de saída anormal (H47-1)
#
# Ele olha a saída do sub-QC de FORA do adaptador, e é de propósito que ele não
# consulte o catálogo: um item pode declarar mal o próprio contrato de exit, e a
# regra tem que valer inclusive para o QC de cliente que ninguém daqui escreveu.

_RE_TRACEBACK = re.compile(r"^Traceback \(most recent call last\):", re.M)
_RE_ULTIMA_EXC = re.compile(r"^(\w+(?:Error|Exception|Exit)\b.*)$", re.M)


def _saida_anormal(so, se, code, res):
    """(motivo, detalhe) quando a saída não sustenta veredito. (None, None) se ok.

    Três sinais, todos observados de fora do que o programa afirma sobre si:

    · **traceback** — o script morreu no meio. O que ele imprimiu antes pode ter
      contagem (foi assim que 17 unidades viraram `ok`), mas metade de uma
      varredura não é uma varredura.
    · **morte por sinal / exec impossível** — `code < 0` (POSIX: -SIGSEGV etc. no
      subprocess do Python) ou `code >= 126` (127 = não achou o binário, 126 =
      não é executável, 128+n = sinal quando o shell está no meio).
    · **exit ≠ 0 sem nenhum item** — o script disse "algo está errado" e o
      adaptador não traduziu isso em NADA. Ou o parse quebrou, ou o modo de
      falha é novo. Nos dois casos o honesto é "não verificado".
      ⚠️ Só vale quando o adaptador não forçou estado: `estado_forcado` é o
      adaptador dizendo "eu ENTENDI este exit" (o exit 3 do qc-cauda, o JSON
      ilegível do qc-nivel), e essa leitura é mais específica que este guarda.
    """
    txt = "%s\n%s" % (se or "", so or "")
    if _RE_TRACEBACK.search(txt):
        linhas = [l.strip() for l in txt.splitlines() if l.strip()]
        exc = ""
        for l in reversed(linhas):
            if _RE_ULTIMA_EXC.match(l):
                exc = l
                break
        return "crash", _corta(exc or "traceback sem linha de exceção legível", 90)
    if code is not None and (code < 0 or code >= 126):
        return "crash", ("morto por sinal %d" % -code if code < 0
                         else "exit %d (binário ausente ou não executável)" % code)
    if code not in (0, None) and not res["itens"] and not res.get("estado_forcado"):
        return "exit-inesperado", ("exit %d e nenhum item extraído — o adaptador "
                                   "não soube explicar a saída" % code)
    return None, None


def ordenar(itens):
    """Ordem de EXECUÇÃO respeita `depois_de`; a de IMPRESSÃO é a do catálogo."""
    feitos, fila, saida = set(), list(itens), []
    while fila:
        avancou = False
        for it in list(fila):
            if all(d in feitos or d not in {x["id"] for x in itens}
                   for d in it.get("depois_de", [])):
                saida.append(it)
                feitos.add(it["id"])
                fila.remove(it)
                avancou = True
        if not avancou:                     # ciclo: roda na ordem do catálogo
            saida += fila
            break
    return saida


def rodar(d, cat, estagio, so=None, pular=(), jobs=3, desligadas=(),
          motivo_pular=None):
    ctx = contexto(d, cat)
    ctx["_desligadas"] = desligadas
    aplicaveis = [it for it in cat["itens"] if estagio in it["estagios"]]
    if so:
        aplicaveis = [it for it in aplicaveis if it["id"] in so]
    # 🔴 `--pular` DEIXA RASTRO (achado A16). Até 2026-08-10 o item sumia da
    # lista e sumia do relatório: `relatorio.json` saía com o veredito `limpo`
    # afirmando um verde que ninguém mediu, e o único jeito de descobrir era
    # lembrar da linha de comando. O estado `nao_verificado` e o motivo
    # `"pulado"` já estavam DECLARADOS em ESTADOS/MOTIVOS desde a SPEC-12 —
    # nunca eram atribuídos a ninguém. Agora são.
    pulados = [it for it in aplicaveis if it["id"] in pular]
    aplicaveis = [it for it in aplicaveis if it["id"] not in pular]
    # 🔴 E O PULO GANHOU DONO (achado R-20d, 2026-08-11). Faltava a metade que o
    # `jcut.py --nao-aplicar` já cobrava: o PORQUÊ. Pular sem motivo é a mesma
    # classe de silêncio que `rm jcut.json` — deixa "decidi não verificar isto,
    # e aqui está a razão" e "não pensei no assunto" idênticos no relatório. E o
    # campo `resumo` desta entrada era ÓRFÃO: escrito, e nenhum leitor. Agora ele
    # é o lugar onde o motivo declarado (ou a falta dele) aparece.
    _pulo = (motivo_pular or "").strip()
    _resumo_pulo = ("pulado — %s" % _pulo) if _pulo else \
        "pulado por --pular na linha de comando, SEM MOTIVO DECLARADO"
    ctx["_pulados"] = [
        {"id": it["id"], "titulo": it["titulo"], "classe": it["classe"],
         "tipo": it["tipo"], "estado": "nao_verificado", "motivo": "pulado",
         "motivo_declarado": _pulo or None,
         "resumo": _resumo_pulo[:MAX_RESUMO],
         "achados": [], "falhas": [], "n": 0, "unidade": it["unidade"],
         "duracao_s": 0.0}
        for it in pulados]

    extras = []
    for ex in ctx["local"].get("extras", []):
        it = {"id": ex["id"], "titulo": ex.get("titulo", "extra da produção"),
              "classe": ex.get("classe", "qc"), "tipo": ex.get("tipo", "detector"),
              "estagios": ex.get("estagios", [estagio]),
              "exec": {"script": ex["script"], "argv": ex.get("argv", ["{dir}"]),
                       "local": True},
              "requer": ex.get("requer", []), "requer_perfil": None,
              "unidade": ex.get("unidade", "linha"),
              "adaptador": ex.get("adaptador", "generico"),
              "promove_falha": ex.get("promove_falha", []),
              "rebaixa_achado": ex.get("rebaixa_achado", []),
              "depois_de": [], "custo_s": ex.get("custo_s", 30),
              "prova_de_dentes": ex.get("prova_de_dentes", False),
              "nota_classe": ex.get("nota_classe", "declarado em qc/local.json")}
        if estagio in it["estagios"]:
            extras.append(it)
    # o script de um extra mora na PRODUÇÃO, não na skill
    for it in extras:
        alvo = os.path.join(d, it["exec"]["script"])
        it["exec"] = {"cmd": [sys.executable, alvo] + it["exec"]["argv"]}
    # substitui o item de catálogo homônimo (é para isso que `extras` existe)
    ids_extras = {it["id"] for it in extras}
    aplicaveis = [it for it in aplicaveis if it["id"] not in ids_extras] + extras

    ordem_impressao = [it["id"] for it in aplicaveis]
    fila = ordenar(aplicaveis)

    # `qc-fala` vira N itens, um por par declarado
    tarefas = []
    for it in fila:
        if it["id"] == "qc-fala" and ctx["local"].get("inserts"):
            for k, ins in enumerate(ctx["local"]["inserts"]):
                tarefas.append((it, {"insert.base": os.path.join(d, ins["base"]),
                                     "insert.editado": os.path.join(d, ins["editado"])},
                                "qc-fala[%d]" % k))
        else:
            tarefas.append((it, None, None))

    # `depois_de` é barreira: os que dependem de alguém só começam depois dele.
    resultados = {}
    barreira = [t for t in tarefas if t[0].get("depois_de")]
    livres = [t for t in tarefas if not t[0].get("depois_de")]
    for lote in (livres, barreira):
        if not lote:
            continue
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            futs = [(rot or it["id"],
                     pool.submit(executar_item, it, ctx, estagio, extra, rot))
                    for it, extra, rot in lote]
            for rot, f in futs:
                resultados[rot] = f.result()

    ordenados = []
    for i in ordem_impressao:
        for k in sorted(resultados):
            if k == i or k.startswith(i + "["):
                ordenados.append(resultados[k])
    # os pulados entram na saída como `nao_verificado / pulado` — no fim, para
    # não embaralhar a ordem do catálogo, e visíveis, que é o ponto do A16.
    return ctx, ordenados + ctx.get("_pulados", [])


# ────────────────────────────────────────────────────────────────── a saída

def _agrupar(itens):
    """≥3 achados da mesma tag viram `N× TAG`."""
    cont = {}
    for a in itens:
        cont[a["tag"]] = cont.get(a["tag"], 0) + 1
    partes = []
    for tag, n in cont.items():
        if n >= 3:
            partes.append("%d× %s" % (n, tag))
        else:
            amostra = [a for a in itens if a["tag"] == tag][:2]
            partes.append(" · ".join("%s %s" % (a["onde"], a["tag"]) for a in amostra))
    return " · ".join(partes)


def formatar(ctx, estagio, motivo_estagio, itens, cat, duracao):
    perfil = ctx["perfil"].get("nome", "?")
    cab = "QC %s · %s · perfil %s%s · %s segs · %.0fs" % (
        estagio, os.path.basename(os.path.abspath(ctx["dir"])), perfil,
        "[fallback]" if ctx["perfil_fallback"] else "",
        ctx["n_segmentos"] if ctx["n_segmentos"] is not None else "?", duracao)

    falhas = [i for i in itens if i["estado"] == "falha"]
    achados = [i for i in itens if i["estado"] == "achado"]
    revisoes = []
    achados_operacionais = []
    for item in achados:
        rev = [a for a in item["achados"] if a["tag"].startswith("REVISAO")]
        outros = [a for a in item["achados"] if not a["tag"].startswith("REVISAO")]
        if rev:
            revisoes.append({**item, "achados": rev})
        if outros:
            achados_operacionais.append({**item, "achados": outros})
    oks = [i for i in itens if i["estado"] == "ok"]
    nvs = [i for i in itens if i["estado"] in ("nao_verificado", "erro")]
    # largura da coluna de id derivada dos ids que EXISTEM: com número fixo, um id
    # novo no catálogo desalinha a saída inteira e o diff entre rodadas vira ruído.
    w = min(16, max([13] + [len(i["id"]) for i in itens])) if itens else 13

    def bloco_falha():
        ls = ["FALHA %d" % sum(len(i["falhas"]) for i in falhas)]
        for i in falhas:
            for a in i["falhas"][:MAX_LINHAS_POR_QC]:
                ls.append("  %-*s %s %s (%s)"
                          % (w, i["id"], a["onde"], a["tag"],
                             _corta(a["detalhe"], 70)))
            if len(i["falhas"]) > MAX_LINHAS_POR_QC:
                ls.append("  %-*s (+%d em qc/relatorio.json)"
                          % (w, "", len(i["falhas"]) - MAX_LINHAS_POR_QC))
        return ls

    def bloco_achado(colapsa=False):
        n = sum(len(i["achados"]) for i in achados_operacionais)
        ls = ["ACHADO %d  (esperado por construção — não bloqueia)" % n]
        if colapsa:
            ls.append("  " + " · ".join("%s(%d)" % (i["id"], len(i["achados"]))
                                        for i in achados_operacionais)
                      + "  (+detalhe em qc/relatorio.json)")
            return ls
        for i in achados_operacionais:
            ls.append("  %-*s %s" % (w, i["id"], _corta(_agrupar(i["achados"]), 95)))
        return ls

    def bloco_revisao(colapsa=False):
        n = sum(len(i["achados"]) for i in revisoes)
        ls = ["REVISÃO HUMANA %d  (escute antes de aprovar)" % n]
        if colapsa:
            ls.append("  " + " · ".join("%s(%d)" % (i["id"], len(i["achados"]))
                                        for i in revisoes)
                      + "  (+detalhe em qc/relatorio.json)")
            return ls
        for i in revisoes:
            ls.append("  %-*s %s" % (w, i["id"], _corta(_agrupar(i["achados"]), 95)))
        return ls

    def bloco_ok():
        return ["OK %d  %s" % (len(oks), " · ".join(
            "%s(%s)" % (i["id"], ("%d/%d" % (i["unidades"], i["esperadas"]))
                        if i["esperadas"] else i["unidades"]) for i in oks))]

    def bloco_nv():
        ls = ["NÃO VERIFICADO %d" % len(nvs)]
        for i in nvs:
            # 🔴 no item ANORMAL (H47-1) a marca vem antes do id: "não medi porque
            # o insumo não existe" e "não medi porque o verificador morreu" pedem
            # ações diferentes de quem lê, e a segunda é urgente.
            marca = "🔴 " if i.get("anormal") else ""
            ls.append("  %s%-*s %s" % (marca, w - (2 if marca else 0), i["id"],
                                       _corta("%s — %s"
                                              % (i.get("motivo") or i["estado"],
                                                 i.get("detalhe") or ""), 92)))
        return ls

    def render(colapsa):
        p = [cab, ""]
        if falhas:
            p += bloco_falha() + [""]
        if revisoes:
            p += bloco_revisao(colapsa) + [""]
        if achados_operacionais:
            p += bloco_achado(colapsa) + [""]
        if oks:
            p += bloco_ok() + [""]
        if nvs:
            p += bloco_nv() + [""]
        p.append("CEGO SEMPRE: " + ", ".join(cat.get("cegos", []))
                 + ". Assista antes de entregar.")
        p.append("detalhe: qc/relatorio.json · logs: qc/*.log")
        return "\n".join(p) + "\n"

    txt = render(False)
    limite = ORCAMENTO_COM_FALHA if falhas else ORCAMENTO_LIMPO
    if len(txt) > limite:
        txt = render(True)
    return txt


def relatorio(ctx, cat, estagio, motivo_estagio, itens, duracao, veredito):
    return {
        "schema": CONTRATO,
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dir": ctx["dir"],
        "estagio": estagio,
        "estagio_motivo": motivo_estagio,
        "catalogo": {"caminho": cat["_caminho"], "fragmentos": cat["_fragmentos"],
                     "n_itens": len(cat["itens"])},
        "perfil": {"nome": ctx["perfil"].get("nome"),
                   "fallback": ctx["perfil_fallback"], "sha256": None},
        "veredito": veredito,
        "duracao_s": round(duracao, 1),
        "itens": [{k: v for k, v in i.items() if k != "_log"}
                  for i in itens if i["estado"] != "nao_verificado"],
        # 🔴 O `detalhe` DO PULO É O MOTIVO DECLARADO (achado R-20d, 2026-08-11).
        # Antes o `resumo` do item pulado era escrito e nunca lido: o relatório
        # gravava `{"id": "…", "motivo": "pulado", "detalhe": null}` e quem lesse
        # o arquivo depois não tinha como saber POR QUE. Agora o `--motivo` chega
        # aqui, e a falta dele chega em voz alta.
        "nao_verificado": [{"id": i["id"], "motivo": i.get("motivo"),
                            "detalhe": (i.get("detalhe")
                                        or (i.get("resumo")
                                            if i.get("motivo") == "pulado" else None)),
                            # H47-1: o exit e o argv do sub-QC que morreu ficam no
                            # relatório. Sem eles, "crash" manda quem lê procurar
                            # o log de cabeça.
                            "anormal": i.get("anormal"),
                            "exec": i.get("exec") if i.get("anormal") else None}
                           for i in itens if i["estado"] == "nao_verificado"],
        "cegos": cat.get("cegos", []),
    }


def gravar(d, rel, itens):
    qc = os.path.join(d, "qc")
    os.makedirs(qc, exist_ok=True)
    with open(os.path.join(qc, "relatorio.json"), "w") as fh:
        json.dump(rel, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for i in itens:
        so, se = i.get("_log", ("", ""))
        if not (so or se):
            continue
        with open(os.path.join(qc, "%s.log" % i["id"]), "w") as fh:
            fh.write("$ %s\n\n--- stdout\n%s\n--- stderr\n%s"
                     % (" ".join(str(x) for x in (i["exec"] or {}).get("argv", [])),
                        so, se))


# ─────────────────────────────────────────────────────── autoteste (prova de dentes)

def dir_fixtures():
    return os.path.join(dir_scripts(), "tests", "fixtures", "qc")


def autoteste(desligar=()):
    """Roda os adaptadores contra as fixtures e EXIGE que os defeitos sintéticos
    sejam classificados como FALHA.

    🔴 Isto existe porque verde não é prova. Um portão que varre 0 e sai 0 é
    indistinguível de um quebrado — então aqui se planta o defeito e se confere
    que ele é ACUSADO. `--desligar-regra` é o controle negativo: com uma regra de
    classificação desligada, este comando TEM que sair 1."""
    fx = dir_fixtures()
    esperado_p = os.path.join(fx, "esperado.json")
    if not os.path.exists(esperado_p):
        print("autoteste: sem fixtures em %s" % fx, file=sys.stderr)
        return 1
    with open(esperado_p) as fh:
        esperado = json.load(fh)
    cat = carregar_catalogo()
    por_id = {i["id"]: i for i in cat["itens"]}
    falhou, n = [], 0
    print("autoteste · %d caso(s) · fixtures em %s"
          % (len(esperado["casos"]), os.path.relpath(fx, dir_scripts())))
    for caso in esperado["casos"]:
        n += 1
        arq = os.path.join(fx, caso["arquivo"])
        if not os.path.exists(arq):
            falhou.append("%s: fixture ausente" % caso["arquivo"])
            continue
        with open(arq) as fh:
            bruto = fh.read()
        so, se = bruto.split("\n--- stderr\n") if "\n--- stderr\n" in bruto \
            else (bruto, "")
        so = so.replace("--- stdout\n", "", 1)
        item = por_id.get(caso["item"])
        if item is None:
            falhou.append("%s: item %r fora do catálogo" % (caso["arquivo"], caso["item"]))
            continue
        res = ADAPTADORES[item["adaptador"]](so, se, caso.get("exit", 0),
                                             caso.get("ctx", {}))
        estado, achados, falhas = classificar(item, res, desligar)
        got = {"unidades": res["unidades"], "esperadas": res.get("esperadas"),
               "achados": len(achados), "falhas": len(falhas), "estado": estado}
        quer = caso["esperado"]
        ruim = [k for k in quer if got.get(k) != quer[k]]
        marca = "✅" if not ruim else "❌"
        print("  %s %-26s %-16s unidades=%-4s achados=%-3s falhas=%-3s estado=%s"
              % (marca, caso["arquivo"], caso["item"], got["unidades"],
                 got["achados"], got["falhas"], got["estado"]))
        if ruim:
            falhou.append("%s: %s" % (caso["arquivo"], ", ".join(
                "%s=%s (esperado %s)" % (k, got.get(k), quer[k]) for k in ruim)))
    print("\n── o que o autoteste varreu ──")
    print("   casos              %d" % n)
    print("   adaptadores        %d de %d no catálogo"
          % (len({c["item"] for c in esperado["casos"]}), len(cat["itens"])))
    print("   casos que TÊM que reprovar  %d (estado esperado = falha)"
          % sum(1 for c in esperado["casos"]
                if c["esperado"].get("estado") == "falha"))
    print("   defeitos PLANTADOS de propósito  %d"
          % sum(1 for c in esperado["casos"]
                if c["arquivo"].startswith(("defeito-", "cego-"))))
    if desligar:
        print("   regras desligadas  %s" % ", ".join(desligar))
    if falhou:
        print("\n❌ %d caso(s) fora do esperado:" % len(falhou))
        for f in falhou:
            print("   " + f)
        return 1
    print("\n✅ autoteste OK")
    return 0


# ────────────────────────────────────────────────────────────────────── CLI

def main(argv):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--estagio", default="auto")
    ap.add_argument("--so", default="")
    ap.add_argument("--pular", default="")
    ap.add_argument("--motivo", default=None,
                    help="por que este item foi pulado. Vai para o relatorio.json "
                         "junto do item; sem ele o relatório diz, em voz alta, "
                         "'SEM MOTIVO DECLARADO'.")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--autoteste", action="store_true")
    ap.add_argument("--desligar-regra", action="append", default=[],
                    choices=list(REGRAS))
    ap.add_argument("--catalogo", action="store_true")
    a = ap.parse_args(argv)

    if a.autoteste:
        return autoteste(tuple(a.desligar_regra))

    cat = carregar_catalogo()
    if a.catalogo:
        json.dump({"schema": cat["schema"], "itens": cat["itens"],
                   "estagios": cat["estagios"], "fragmentos": cat["_fragmentos"]},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 0
    if not a.dir:
        raise ErroUso("falta <dir-producao>")
    if not os.path.isdir(a.dir):
        raise ErroUso("%s não é um diretório" % a.dir)

    so = {x for x in a.so.split(",") if x}
    pular = {x for x in a.pular.split(",") if x}
    ctx0 = contexto(a.dir, cat)
    estagios = ([e for e in cat["estagios"] if ctx0.get("artefato_" + e)]
                if a.completo else None)
    if a.completo and not estagios:
        estagios = [list(cat["estagios"])[0]]

    codigo, saida_total, rels = 0, [], []
    for estagio in (estagios or [None]):
        est, motivo = resolver_estagio(cat, ctx0, estagio or a.estagio)
        t0 = time.time()
        ctx, itens = rodar(a.dir, cat, est, so, pular, a.jobs,
                           tuple(a.desligar_regra), motivo_pular=a.motivo)
        dur = time.time() - t0
        rodou = [i for i in itens if i["estado"] not in ("nao_verificado", "erro")]
        # 🔴 `limpo` afirma "a bateria varreu e não achou nada". Um item PULADO
        # não foi varrido: o veredito passa a `incompleto` (achado A16). Sem
        # isto, `qc.py --pular qc-cor` devolvia `limpo` sobre um verde que não
        # houve, e o relatório no disco repetia a afirmação para quem o lesse
        # depois, sem a linha de comando por perto.
        pulados = [i for i in itens if i.get("motivo") == "pulado"]
        # 🔴 H47-1: um sub-QC que morreu não deixa a bateria dizer `limpo` nem
        # `achados`. `anormal` vem ANTES de `achados` na precedência porque um
        # verificador quebrado invalida a leitura do conjunto — e sai 1, senão a
        # automação que só olha o exit continua vendo verde (foi o que aconteceu).
        # E `anormal` vem antes de `vazio`: quando o único item da bateria é o que
        # morreu, "vazio" (nada pôde rodar) descreve o sintoma e esconde a causa.
        anormais = [i for i in itens if i.get("anormal")]
        veredito = ("falha" if any(i["estado"] == "falha" for i in itens) else
                    "anormal" if anormais else
                    "vazio" if not rodou else
                    "achados" if any(i["estado"] == "achado" for i in itens) else
                    "incompleto" if pulados else
                    "limpo")
        rel = relatorio(ctx, cat, est, motivo, itens, dur, veredito)
        rels.append(rel)
        gravar(a.dir, rel, itens)
        saida_total.append(formatar(ctx, est, motivo, itens, cat, dur))
        if veredito in ("falha", "anormal"):
            codigo = 1
        elif veredito == "vazio" and codigo == 0:
            codigo = 3
    if a.json:
        json.dump(rels[0] if len(rels) == 1 else rels, sys.stdout,
                  ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        sys.stdout.write("\n".join(saida_total))
    return codigo


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ErroUso as e:
        print("erro: %s" % e, file=sys.stderr)
        sys.exit(2)
