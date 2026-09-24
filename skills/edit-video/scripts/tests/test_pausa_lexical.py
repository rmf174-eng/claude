#!/usr/bin/env python3
"""Regressão do orçamento lexical de pausa, sem mídia e com controle negativo."""
import copy
import json
import os
import sys
import tempfile

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
import bordas                    # noqa: E402
import edl_io                    # noqa: E402


CFG = {
    "ativo": True,
    "min_s": 0.20,
    "alvo_s": 0.25,
    "max_s": 0.30,
    "protecao_fim_s": 0.10,
    "protecao_inicio_s": 0.10,
    "min_frames_corte_herdado": 8,
}
FALHAS = []
N = 0

# Evidência acústica medida no bruto real. O ASR estendeu "coisa" até 53.305,
# mas o envelope útil terminou perto de 52.870. Estes valores explicam por que o
# perfil não pode ativar automaticamente um orçamento baseado só em ASR.
FIM_ACUSTICO = 52.870
INICIO_ACUSTICO = 53.895
CORTE_FIM_MEDIDO = 53.066667
CORTE_INICIO_MEDIDO = 53.833333


def ok(cond, nome, detalhe=""):
    global N
    N += 1
    print("  [%s] %s%s" % ("PASSOU" if cond else "FALHOU", nome,
                            " — " + detalhe if detalhe else ""))
    if not cond:
        FALHAS.append(nome)


def fixture_sintetica(fixos=True):
    """Gap lexical controlado, sem fingir que timestamps ASR são acústicos."""
    herdados = [5.13, 7.60, 10.77, 13.73, 17.80, 20.43, 25.47,
                29.50, 31.87, 34.47, 36.87, 49.93, 51.43]
    j = [
        {"src": "bruto.mp4", "asr_ini": 0.600, "asr_fim": 1.000,
         "beat": "coisa", "fala": "coisa", "cortes_herdados_s": herdados},
        {"src": "bruto.mp4", "asr_ini": 1.640, "asr_fim": 2.040,
         "beat": "marca", "fala": "Marca", "cortes_herdados_s": herdados},
    ]
    if fixos:
        j[0]["end_fixo"] = 1.115
        j[1]["start_fixo"] = 1.525
        edl = [
            {"src": "bruto.mp4", "start": 0.400, "end": 1.115,
             "beat": "coisa", "fala": "coisa"},
            {"src": "bruto.mp4", "start": 1.525, "end": 2.200,
             "beat": "marca", "fala": "Marca"},
        ]
    else:
        edl = [
            {"src": "bruto.mp4", "start": 0.400, "end": 1.350,
             "beat": "coisa", "fala": "coisa"},
            {"src": "bruto.mp4", "start": 1.525, "end": 2.200,
             "beat": "marca", "fala": "Marca"},
        ]
    return edl, j


print("0. orçamento ASR não é default sem calibração acústica")
reels_path = os.path.abspath(os.path.join(SCRIPTS, "..", "perfis", "reels.json"))
reels = json.load(open(reels_path, encoding="utf-8"))
ok(reels["ritmo"]["orcamento_pausa"]["ativo"] is False,
   "perfil reels mantém ajuste automático desligado")
pausa_medida = ((CORTE_FIM_MEDIDO - FIM_ACUSTICO)
                + (INICIO_ACUSTICO - CORTE_INICIO_MEDIDO))
ok(0.20 <= pausa_medida <= 0.30,
   "cortes acústicos reais preservam a pausa-alvo", "%.0f ms" % (pausa_medida * 1000))
ok(CORTE_FIM_MEDIDO < 53.305 and CORTE_FIM_MEDIDO < 53.42,
   "controle prova que fim ASR e antigo 53.42 não são autoridade acústica")


print("\n1. fixture sintética: pontos fixos vencem o heurístico")
edl, janelas = fixture_sintetica(fixos=True)
medidas_ok = [
    {"onset_s": 0.600, "decay_s": 1.000},
    {"onset_s": 1.640, "decay_s": 2.040},
]
rels = bordas.limitar_pausas_lexicais(
    edl, janelas, CFG, 30, medidas_acusticas=medidas_ok)
r = rels[0]
ok(edl[0]["end"] == 1.115 and edl[1]["start"] == 1.525,
   "pontos fixos sintéticos preservados")
ok(r["gap_lexical_bruto_ms"] == 640, "gap lexical bruto = 640 ms")
ok(r["tempo_removido_ms"] == 410, "tempo removido = 410 ms")
ok(200 <= r["gap_final_ms"] <= 300,
   "montagem fica no orçamento de 0,20–0,30 s", "%d ms" % r["gap_final_ms"])
ok(r["deslocamento_fim_ms"] == 0 and r["deslocamento_inicio_ms"] == 0,
   "o orçamento não desloca pontos medidos")
ok(1.115 > 1.000 and 1.525 < 1.640,
   "fim e ataque permanecem protegidos no controle sintético")
ok(r["gap_acustico_final_ms"] == 230 and r["estado"] == "medida",
   "relatório usa envelope acústico e não pede decisão quando está no teto",
   "%d ms" % r["gap_acustico_final_ms"])


print("\n2. caso automático e controle negativo sintéticos")
edl_auto, j_auto = fixture_sintetica(fixos=False)
rels_auto = bordas.limitar_pausas_lexicais(edl_auto, j_auto, CFG, 30)
ra = rels_auto[0]
ok(200 <= ra["gap_final_ms"] <= 300 and ra["gap_final_ms"] == 250,
   "mecanismo genérico reduz 465 ms sintéticos para o alvo", "%d ms" % ra["gap_final_ms"])
ok(edl_auto[0]["end"] >= j_auto[0]["asr_fim"] + CFG["protecao_fim_s"] - 1e-9,
   "proteção fonética do fim é independente")
ok(edl_auto[1]["start"] <= j_auto[1]["asr_ini"] - CFG["protecao_inicio_s"] + 1e-9,
   "proteção fonética do início é independente")

edl_off, j_off = fixture_sintetica(fixos=False)
cfg_off = dict(CFG, ativo=False)
medidas_longa = [
    {"onset_s": 0.600, "decay_s": 0.950},
    {"onset_s": 1.740, "decay_s": 2.040},
]
ro = bordas.limitar_pausas_lexicais(
    edl_off, j_off, cfg_off, 30, medidas_acusticas=medidas_longa)[0]
ok(ro["gap_final_ms"] == 465 and ro["gap_final_ms"] > CFG["max_s"] * 1000,
   "controle negativo: guarda desligada mantém 465 ms sintéticos")
ok(ro["gap_acustico_final_ms"] == 615
   and ro["estado"] == "decisao-pendente"
   and ro["motivo"] == "DESATIVADO+ALERTA-PAUSA-ACUSTICA",
   "615 ms acústicos ficam intactos, mas exigem decisão explícita", ro["motivo"])


print("\n3. fim fixo força ajuste só no início, sem cortar o ataque")
edl_ini, j_ini = fixture_sintetica(fixos=True)
j_ini[1].pop("start_fixo")
edl_ini[1]["start"] = 1.400
ri = bordas.limitar_pausas_lexicais(edl_ini, j_ini, CFG, 30)[0]
ok(edl_ini[0]["end"] == 1.115 and edl_ini[1]["start"] > 1.400,
   "end_fixo preservado e início move sozinho")
ok(edl_ini[1]["start"] <= 1.640 - 0.10 + 1e-9,
   "avanço para antes do limite fonético do /m/", "start %.3f" % edl_ini[1]["start"])
ok(200 <= ri["gap_final_ms"] <= 300, "ajuste pelo início também fecha o orçamento")


print("\n4. proteção de corte herdado: menos de 8 frames alinha, não cria flash")
edl_h = [
    {"src": "x.mp4", "start": 0.0, "end": 1.60, "beat": "a"},
    {"src": "x.mp4", "start": 1.65, "end": 2.30, "beat": "b"},
]
j_h = [
    {"src": "x.mp4", "asr_ini": 0.30, "asr_fim": 1.0, "beat": "a",
     "cortes_herdados_s": [1.25]},
    {"src": "x.mp4", "asr_ini": 1.70, "asr_fim": 2.10, "beat": "b",
     "start_fixo": 1.65, "cortes_herdados_s": [1.25]},
]
rh = bordas.limitar_pausas_lexicais(edl_h, j_h, CFG, 30)[0]
margem = CFG["min_frames_corte_herdado"] / 30.0
dist = abs(edl_h[0]["end"] - 1.25)
ok(dist <= 0.001 or dist >= margem - 1e-9,
   "novo corte alinha ou fica a pelo menos 8 frames", "distância %.3f s" % dist)
ok(abs(edl_h[0]["end"] - 1.25) <= 0.001,
   "candidato perto foi alinhado ao corte herdado")
ok("ALINHADO-CORTE-HERDADO" in rh["motivo"],
   "alinhamento aparece no motivo", rh["motivo"])
ok(200 <= rh["gap_final_ms"] <= 300,
   "alinhamento continua dentro do orçamento", "%d ms" % rh["gap_final_ms"])


print("\n5. integração de bordas.main sem decodificar mídia")
with tempfile.TemporaryDirectory(prefix="pausa-lexical-") as d:
    edl_i, j_i = fixture_sintetica(fixos=True)
    with open(os.path.join(d, "janelas.json"), "w", encoding="utf-8") as fh:
        json.dump(j_i, fh)
    base = os.path.abspath(os.path.join(SCRIPTS, "..", "perfis", "_base.json"))
    perfil = json.load(open(base, encoding="utf-8"))
    perfil["nome"] = "fixture-pausa"
    perfil["ritmo"]["orcamento_pausa"]["ativo"] = True
    with open(os.path.join(d, "perfil.json"), "w", encoding="utf-8") as fh:
        json.dump(perfil, fh)
    antigo_envelope = bordas.envelope
    antigo_argv = sys.argv
    antigo_cwd = os.getcwd()
    try:
        # Duas palavras sintéticas em torno dos timestamps ASR, com silêncio
        # real entre elas. Um envelope totalmente vazio faria o clamp de busca
        # virar a própria evidência e criaria um alerta artificial no teste.
        fixture_db = np.full(6000, -60.0)
        fixture_db[98:101] = -20.0
        fixture_db[202:205] = -20.0
        bordas.envelope = lambda src, cache, sr: fixture_db
        sys.argv = ["bordas.py", d]
        bordas.main()
    finally:
        bordas.envelope = antigo_envelope
        sys.argv = antigo_argv
        os.chdir(antigo_cwd)
    saida = edl_io.carregar(d)
    rel_path = os.path.join(d, bordas.ARQ_RELATORIO_BORDAS)
    rel_doc = json.load(open(rel_path, encoding="utf-8"))
    pr = rel_doc["pausas_lexicais"][0]
    ok(saida["segments"][0]["end"] == 1.115
       and saida["segments"][1]["start"] == 1.525,
       "bordas.main grava os pontos da fixture na EDL")
    ok(pr["gap_final_ms"] == 230 and pr["gap_lexical_bruto_ms"] == 640,
       "relatório de montagem registra a emenda completa")
    ok(saida["segments"][0]["pausa_lexical"]["motivo"] == pr["motivo"],
       "decisão por emenda também acompanha o segmento")
    ok(rel_doc["decisoes_pendentes"] == [],
       "relatório separa decisões pendentes sem inventar alerta")


print("\n%d checagens" % N)
if FALHAS:
    print("%d FALHA(S):\n  - %s" % (len(FALHAS), "\n  - ".join(FALHAS)))
    sys.exit(1)
print("todas passaram")
