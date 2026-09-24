#!/usr/bin/env python3
"""Energia isolada nao pode reprovar uma emenda."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import qc_evidencia  # noqa: E402
import qc  # noqa: E402


casos = [
    ("energia no fim", ["CLIP-FIM (fala a -31dB depois do corte)"], "revisao"),
    ("energia no inicio", ["CLIP-INICIO (fala a -30dB antes do corte)"], "revisao"),
    ("energia sem token", ["SEM PALAVRAS mas COM ENERGIA (estrangeirismo?)"], "revisao"),
    ("vazamento lexical", ["VAZA-PROX ('marca' comeca em 53.94)"], "falha"),
    ("segmento mudo", ["SEM PALAVRAS e sem energia (segmento mudo?)"], "falha"),
    ("sem evidencia", [], "aprovado"),
]

falhas = 0
for nome, flags, esperado in casos:
    r = qc_evidencia.classificar(flags)
    passou = r["estado"] == esperado
    print("  %s %s: %s" % ("OK" if passou else "FALHA", nome, r["estado"]))
    falhas += 0 if passou else 1

# Controle negativo: se CLIP voltasse a lista dura, este caso reprovaria.
r = qc_evidencia.classificar(["CLIP-FIM (controle)"])
controle = not r["falhas"] and bool(r["alertas"])
print("  %s controle negativo: energia continua sem poder de veto" %
      ("OK" if controle else "FALHA"))
falhas += 0 if controle else 1

# Integração com o portão oficial. O exit cru do detector não decide a classe:
# o catálogo precisa manter energia como achado e promover só evidência dura.
item = next(x for x in qc.carregar_catalogo()["itens"] if x["id"] == "audit-emendas")
energia = qc.ad_audit_emendas(
    "seg00 [0.00-1.00] 'a…b' CLIP-FIM (fala depois do corte)\n", "", 1, {"n_segmentos": 1})
estado, achados, duras = qc.classificar(item, energia)
passou = estado == "achado" and len(achados) == 1 and not duras
print("  %s portao oficial: energia isolada = achado" % ("OK" if passou else "FALHA"))
falhas += 0 if passou else 1

vazamento = qc.ad_audit_emendas(
    "seg00 [0.00-1.00] 'a…b' VAZA-PROX ('intrusa' começa em 0.90)\n",
    "", 1, {"n_segmentos": 1})
estado, achados, duras = qc.classificar(item, vazamento)
passou = estado == "falha" and not achados and len(duras) == 1
print("  %s portao oficial: vazamento lexical = falha" % ("OK" if passou else "FALHA"))
falhas += 0 if passou else 1

palavras = [(0.10, 0.30, "uma"), (0.31, 0.55, "coisa"),
            (0.70, 0.92, "marca")]
vazaram = qc_evidencia.vazamentos_apos_fala("uma coisa", palavras, 0.90)
passou = [p[2] for p in vazaram] == ["marca"]
print("  %s gerador lexical produz VAZA-PROX alcançavel" %
      ("OK" if passou else "FALHA"))
falhas += 0 if passou else 1

repetidas = [(0.10, 0.20, "casa"), (0.21, 0.35, "bonita"),
             (0.36, 0.48, "casa"), (0.50, 0.62, "casa")]
vazaram = qc_evidencia.vazamentos_apos_fala(
    "casa bonita casa", repetidas, 0.62)
passou = len(vazaram) == 1 and vazaram[0][0] == 0.50
print("  %s repeticao nao mascara vazamento posterior" %
      ("OK" if passou else "FALHA"))
falhas += 0 if passou else 1

print("\n%d casos, %d falhas" % (len(casos) + 5, falhas))
sys.exit(1 if falhas else 0)
