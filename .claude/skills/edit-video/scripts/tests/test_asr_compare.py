#!/usr/bin/env python3
"""Regressoes da classificacao conservadora do QC ASR."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

import asr_compare  # noqa: E402

import importlib.util
_SPEC = importlib.util.spec_from_file_location(
    "qc_emendas_asr", os.path.join(SCRIPTS, "qc-emendas-asr.py"))
qc_emendas_asr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qc_emendas_asr)

_SPEC_QC = importlib.util.spec_from_file_location(
    "qc_bateria", os.path.join(SCRIPTS, "qc.py"))
qc_bateria = importlib.util.module_from_spec(_SPEC_QC)
_SPEC_QC.loader.exec_module(qc_bateria)


falhas = []
executados = 0


def meta_multi(*palavras):
    """Payload coerente do Nova-3 multi; confidence e da transcricao."""
    return {
        "languages": ["es", "pt"], "confidence": 0.71,
        "words": [
            {"word": palavra, "language": idioma, "confidence": confianca}
            for palavra, idioma, confianca in palavras
        ],
    }


META_TROCA_INCERTA = meta_multi(
    ("estoy", "es", 0.42), ("y", "es", 0.41), ("sigo", "pt", 0.93))
META_TROCA_COM_INTRUSO = meta_multi(
    ("estoy", "es", 0.42), ("y", "es", 0.41),
    ("intruso", "es", 0.39), ("sigo", "pt", 0.93))
META_TROCA_SEM_Y = meta_multi(
    ("estoy", "es", 0.42), ("sigo", "pt", 0.93))


def ok(nome, cond, detalhe=""):
    global executados
    executados += 1
    print("  %s %s%s" % ("OK" if cond else "FALHA", nome,
                          (": " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(nome)


def caso(nome, esq, dir_, ouvido, estado, meta=None):
    r = asr_compare.comparar(esq, dir_, ouvido, meta)
    passou = r["estado"] == estado
    ok(nome, passou, repr(r) if passou else "%s != %s; %r" % (r["estado"], estado, r))
    return r


print("comparador ASR: equivalencias, bordas e controles negativos")
caso("dois e 2 sao equivalentes", "eu tenho dois", "motivos agora", "tenho 2 motivos", "aprovado")
caso("um e 1 continuam equivalentes", "eu tenho um", "motivo agora",
     "tenho 1 motivo", "aprovado")
genero = caso("um e uma nao colapsam em 1", "eu vi uma", "coisa agora",
              "eu vi um coisa agora", "revisao")
ok("troca de genero fica explicita",
   any(x["codigo"] == "FLEXAO" and x["esperado"] == "uma"
       and x["ouvido"] == "um" for x in genero["revisoes"]), repr(genero))
caso("plural leve vira revisao", "esse sonho", "continua vivo", "esses sonhos continua", "revisao")
troca = caso("troca PT/ES com palavra incerta vira revisao", "eu estou", "e sigo",
             "estoy y sigo", "revisao", META_TROCA_INCERTA)
ok("revisao PT/ES nomeia a evidencia real",
   {x["codigo"] for x in troca["revisoes"]}
   == {"TROCA_IDIOMA_PALAVRA_INCERTA"}
   and {x["confianca_palavra"] for x in troca["revisoes"]} == {0.41, 0.42},
   repr(troca))
caso("PT/ES incerto nao mascara vazamento", "eu estou", "e sigo",
     "estoy y intruso sigo", "falha",
     META_TROCA_COM_INTRUSO)
caso("PT/ES incerto nao mascara palavra ausente", "eu estou", "e sigo",
     "estoy sigo", "falha", META_TROCA_SEM_Y)
caso("palavra genuinamente ausente falha", "uma coisa", "marca cafe", "uma cafe", "falha")
caso("vazamento real falha", "uma coisa", "marca cafe", "uma coisa intrusa marca cafe", "falha")
caso("emenda exata aprova", "uma coisa", "marca cafe", "uma coisa marca cafe", "aprovado")
duplicada = caso("palavra tolerada duplicada nao aprova", "uma coisa", "marca cafe",
                 "uma coisa coisa marca cafe", "falha")
ok("multiplicidade excedente vira vazamento",
   [x["palavra"] for x in duplicada["falhas"] if x["codigo"] == "VAZOU"]
   == ["coisa"], repr(duplicada))
caso("repeticao prevista no contexto continua valida", "uma coisa coisa",
     "marca cafe", "uma coisa coisa marca cafe", "aprovado")
caso("repeticao anterior nao vira aprovacao", "casa bonita casa",
     "abre agora", "casa abre agora", "revisao")
ambigua = caso("sufixo repetido alem do bigrama nao vira aprovacao",
               "bonita casa e bonita casa", "abre agora",
               "bonita casa abre agora", "revisao")
ok("ambiguidade pede o contexto discriminante",
   any(x["codigo"] == "BORDA_AMBIGUA"
       and x["contexto_necessario"] == ["e", "bonita", "casa"]
       for x in ambigua["revisoes"]), repr(ambigua))
caso("contexto unico mais longo comprova a borda repetida", "bonita casa e bonita casa",
     "abre agora", "e bonita casa abre agora", "aprovado")
ordem = caso("borda fora de ordem falha", "uma coisa", "marca cafe",
             "marca uma coisa cafe", "falha")

linha_ordem = ("[00→01]    2.00s esquerda | direita\n"
               "         ouvido: marca uma coisa cafe"
               + qc_emendas_asr.alertas_comparacao(ordem))
adaptado = qc_bateria.ad_qc_emendas_asr(
    linha_ordem, "1 fronteiras · 1 emendas de verdade", 1, {})
item_asr = next(x for x in qc_bateria.carregar_catalogo()["itens"]
                if x["id"] == "qc-emendas-asr")
estado_portao, achados_portao, falhas_portao = qc_bateria.classificar(
    item_asr, adaptado)
ok("ordem invertida de ASR chega ao portao como revisao, nao prova acustica",
   estado_portao == "achado" and not falhas_portao
   and [x["tag"] for x in achados_portao] == ["VAZOU", "ORDEM-BORDA"],
   repr((linha_ordem, adaptado, estado_portao,
         achados_portao, falhas_portao)))

texto, meta = qc_emendas_asr.extrair_resposta({
    "results": {"channels": [{"alternatives": [{
        "transcript": "estoy y sigo", "confidence": 0.71,
        "languages": ["es", "pt"], "words": META_TROCA_INCERTA["words"]
    }]}]}})
ok("metadata real chega ao classificador",
   texto == "estoy y sigo" and meta["languages"] == ["es", "pt"]
   and meta["confidence"] == 0.71 and len(meta["words"]) == 3
   and meta["words"][0]["language"] == "es"
   and meta["words"][0]["confidence"] == 0.42, repr((texto, meta)))

oficial = asr_compare.comparar("eu estou", "e sigo", texto, meta)
ok("shape oficial multi vira revisao", oficial["estado"] == "revisao", repr(oficial))

# Controle negativo: confusao espanhola com alta confianca nao pode ser rebaixada.
neg = asr_compare.comparar("eu estou", "e sigo", "estoy intruso sigo",
                           meta_multi(("estoy", "es", 0.99),
                                      ("intruso", "es", 0.99),
                                      ("sigo", "pt", 0.93)))
ok("controle negativo tem dentes", neg["estado"] == "falha", repr(neg))

global_so_baixa = asr_compare.comparar(
    "eu estou", "e sigo", "estoy y sigo",
    {"languages": ["es", "pt"], "confidence": 0.20})
ok("confidence global nao finge incerteza por palavra",
   global_so_baixa["estado"] == "falha", repr(global_so_baixa))

print("\ncredencial direta do QC usa o resolvedor central")
segredo_fixture = "dg-fixture-nao-logar-123456"
with tempfile.TemporaryDirectory(prefix="ilha-chave-asr-") as d:
    with open(os.path.join(d, ".env"), "w", encoding="utf-8") as fh:
        fh.write("DEEPGRAM_API_KEY=%s\n" % segredo_fixture)
    saida_chave, erro_chave = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"ILHA_HOME": d}, clear=False), \
            contextlib.redirect_stdout(saida_chave), contextlib.redirect_stderr(erro_chave):
        os.environ.pop("DEEPGRAM_API_KEY", None)
        resolvida = qc_emendas_asr.resolver_chave_deepgram()
    vazou = segredo_fixture in (saida_chave.getvalue() + erro_chave.getvalue())
    ok("shell limpo resolve $ILHA_HOME/.env sem logar o valor",
       resolvida == segredo_fixture and not vazou,
       repr((saida_chave.getvalue(), erro_chave.getvalue())))

with tempfile.TemporaryDirectory(prefix="ilha-chave-asr-ausente-") as d:
    with mock.patch.dict(os.environ, {"ILHA_HOME": d}, clear=False):
        os.environ.pop("DEEPGRAM_API_KEY", None)
        try:
            qc_emendas_asr.resolver_chave_deepgram()
        except SystemExit as exc:
            msg_ausente = str(exc)
        else:
            msg_ausente = ""
    ok("ausência orienta sem traceback nem segredo",
       "--pedir DEEPGRAM_API_KEY" in msg_ausente
       and segredo_fixture not in msg_ausente, msg_ausente)


def executar_produtor(esquerda, direita, ouvido, meta_asr=None, respostas=None):
    """Executa o produtor real sem rede/disco e entrega sua saida ao adaptador."""
    edl = [
        {"start": 0.0, "end": 1.0, "src": "a.mp4", "beat": "esquerda",
         "fala": esquerda},
        {"start": 0.0, "end": 1.0, "src": "b.mp4", "beat": "direita",
         "fala": direita},
    ]
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(qc_emendas_asr.edl_io, "segmentos", return_value=edl), \
            mock.patch.object(qc_emendas_asr.edl_io, "timeline",
                              return_value={"fixture": True}), \
            mock.patch.object(qc_emendas_asr.edl_io, "fronteiras",
                              return_value=[0.0, 1.0, 2.0]), \
            mock.patch.object(qc_emendas_asr.jcut_mod, "carregar", return_value=None), \
            mock.patch.object(qc_emendas_asr.subprocess, "run",
                              return_value=SimpleNamespace(stdout=b"mp3")), \
            mock.patch.object(
                qc_emendas_asr, "asr",
                side_effect=(respostas if respostas is not None else
                             (lambda _raw: (ouvido, meta_asr or {})))), \
            mock.patch.object(qc_emendas_asr.os, "chdir"), \
            mock.patch.object(qc_emendas_asr.sys, "argv",
                              ["qc-emendas-asr.py", "/producao-fixture"]), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            qc_emendas_asr.main()
        except SystemExit as exc:
            codigo = int(exc.code or 0)
        else:
            codigo = 0
    saida, erros = stdout.getvalue(), stderr.getvalue()
    adaptado = qc_bateria.ad_qc_emendas_asr(saida, erros, codigo, {})
    item = next(x for x in qc_bateria.carregar_catalogo()["itens"]
                if x["id"] == "qc-emendas-asr")
    estado, achados, falhas_gate = qc_bateria.classificar(item, adaptado)
    return codigo, saida, erros, adaptado, estado, achados, falhas_gate


print("\nprodutor real -> adaptador oficial, sem rede")
integracoes = [
    ("aprovado", ("eu tenho dois", "motivos agora", "tenho 2 motivos", None),
     0, "ok", []),
    ("revisao", ("bonita casa e bonita casa", "abre agora",
                  "bonita casa abre agora", None),
     0, "achado", ["REVISAO-ASR"]),
    ("divergencia ASR", ("uma coisa", "marca cafe", "uma cafe", None),
     0, "achado", ["REVISAO-ASR"]),
]
for nome, args, exit_esperado, estado_esperado, tags_esperadas in integracoes:
    produzido = executar_produtor(*args)
    codigo, saida, erros, adaptado, estado, achados, falhas_gate = produzido
    tags = [x["tag"] for x in achados + falhas_gate]
    ok("produtor %s chega ao portao como %s" % (nome, estado_esperado),
       codigo == exit_esperado and estado == estado_esperado
       and adaptado["unidades"] == adaptado["esperadas"] == 1
       and tags == tags_esperadas,
       repr((codigo, saida, erros, adaptado, estado, achados, falhas_gate)))

instavel = executar_produtor(
    "testa essa semana uma coisa", "marca o cafe", "manda 1 coisa marca o cafe",
    respostas=[
        ("manda 1 coisa marca o cafe", {}),
        ("testa essa semana uma coisa marca o cafe", {}),
    ])
codigo, saida, erros, adaptado, estado, achados, falhas_gate = instavel
ok("alucinacao curta ganha reescuta maior e nunca vira bloqueio",
   codigo == 0 and estado == "achado" and not falhas_gate
   and [x["tag"] for x in achados] == ["REVISAO-ASR"]
   and "ASR_INSTAVEL" in saida and "reescuta com contexto" in saida,
   repr(instavel))

print("\n%d caso(s), %d falha(s)" % (executados, len(falhas)))
sys.exit(1 if falhas else 0)
