#!/usr/bin/env python3
"""Bateria do pré-passo de tracking de rosto (`rastrear-rosto.py`).

    python3 tests/test_track_rosto.py

As partes que dependem de Vision/ffmpeg se auto-pulam com aviso; o que este
arquivo trava sempre é a MATEMÁTICA — preencher, suavizar e a guarda de
cobertura —, que é onde um defeito sai liso, plausível e errado.
"""
import importlib.util
import os
import shutil
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
ALVO = os.path.join(os.path.dirname(DIR), "rastrear-rosto.py")
_spec = importlib.util.spec_from_file_location("rastrear_rosto", ALVO)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

falhas, checagens = [], [0]


def ok(cond, msg):
    checagens[0] += 1
    if not cond:
        falhas.append(msg)
    print(("  ok  " if cond else "  ✗   ") + msg)


print("\n1 · PREENCHER — o buraco vira o último ponto conhecido")
p = R.preencher([None, (0.4, 0.3), None, None, (0.6, 0.5), None])
ok(p is not None and len(p) == 6, "devolve o mesmo número de pontos (%d)" % len(p or []))
ok(p[0] == (0.4, 0.3), "buraco no COMEÇO vira o primeiro conhecido: %s" % (p[0],))
ok(p[2] == (0.4, 0.3) and p[3] == (0.4, 0.3),
   "buraco no meio PARA no último conhecido, não interpola para o futuro")
ok(p[5] == (0.6, 0.5), "buraco no fim mantém o último")
ok(R.preencher([None, None]) is None,
   "sem NENHUMA detecção devolve None — e quem chama decide, em vez de receber "
   "um centro inventado")

print("\n2 · SUAVIZAR — média móvel centrada")
degrau = [(0.0, 0.0)] * 5 + [(1.0, 1.0)] * 5
s = R.suavizar(degrau, 2)
ok(len(s) == 10, "preserva o comprimento")
ok(s[0][0] < 0.35 and s[-1][0] > 0.65, "as pontas continuam nos extremos")
ok(all(s[i][0] <= s[i + 1][0] + 1e-9 for i in range(9)),
   "monotônica num degrau monotônico — a suavização não inventa oscilação")
meio = [abs(s[i][0] - s[i + 1][0]) for i in range(9)]
ok(max(meio) < 0.45,
   "o degrau de 0→1 vira rampa: maior salto entre frames = %.3f (era 1,000)"
   % max(meio))
# ⚠️ janela 0 tem que ser recusada pelo chamador (max(1, …)); aqui só provo que
# janela 1 não é identidade.
ok(R.suavizar(degrau, 1) != degrau, "janela 1 já suaviza (não é identidade)")

print("\n3 · A GUARDA DE COBERTURA — e por que ela existe")
# 12 detecções em 480 frames: o `preencher` devolve 480 pontos, o `suavizar`
# devolve uma curva lisa, e TUDO parece certo. É o defeito mais caro deste
# arquivo, e por isso a recusa é do script, não do humano.
brutos = [(0.5, 0.42)] * 12 + [None] * 468
cheio = R.preencher(brutos)
ok(cheio is not None and len(cheio) == 480,
   "com 12 de 480 detecções o preenchimento ainda devolve 480 pontos válidos")
liso = R.suavizar(cheio, 4)
ok(all(abs(a[0] - b[0]) < 1e-9 for a, b in zip(liso, liso[1:])),
   "…e a curva sai PERFEITAMENTE lisa — plausível e errada, que é o ponto")
ok(12 / 480 < 0.35,
   "a cobertura (%.1f%%) fica abaixo do mínimo de 35%% e o script RECUSA"
   % (100 * 12 / 480))

print("\n4 · O BINÁRIO E O CONTRATO")
ok(os.path.isfile(os.path.join(os.path.dirname(DIR), "rosto-vision.swift")),
   "o detector Swift está ao lado do script")
ok(R.CONTRATO == "benchmark.track-rosto/v1", "contrato: %s" % R.CONTRATO)
tem = shutil.which("swiftc") and shutil.which("ffmpeg")
if not tem:
    print("  ⏭️  ponta a ponta pulado: falta swiftc ou ffmpeg")
else:
    p = subprocess.run([sys.executable, ALVO, "--help"], capture_output=True, text=True)
    ok(p.returncode == 0 and "--minimo-cobertura" in p.stdout,
       "a CLI expõe --minimo-cobertura (a guarda é ajustável, não escondida)")

print("\n%d checagens · %d falha(s)" % (checagens[0], len(falhas)))
for f in falhas:
    print("  ✗ " + f)
sys.exit(1 if falhas else 0)
