#!/usr/bin/env python3
"""Testes de `nivel.py` (SPEC-08) — 100 % sintético, sem ffmpeg e sem creator.

    python3 tests/test_nivel.py        (sai 0 se tudo passa)

Os critérios [gate] da §7 da SPEC-08, na ordem em que ela os numera:

  §7.2  INÉRCIA          max|y| <= teto → o MESMO array, bit a bit, atuou=False
  §7.3  TETO GARANTIDO   500 sinais × 3 tetos, zero exceção (não é estatística:
                         a garantia é da construção do envelope)
  §7.4  DISTORÇÃO        o número que separa limitar de clipar — THD do np.clip
                         contra THD do limitador, com o MESMO pico de saída
  §7.8  VALIDAÇÃO FATAL  gain_db fora de faixa · string · chave parecida

Mais três que a spec não numera e que existem porque portão verde sem prova de
dentes é indistinguível de portão quebrado:

  D1  DEFEITO PLANTADO   um limitador que só faz np.clip PASSA no §7.3 e tem que
      REPROVAR no §7.4 — é o controle negativo do teste de distorção
  D2  DEFEITO PLANTADO   um limitador sem a trava anti-overshoot da interpolação
      FURA o teto; o teste tem que acusar
  D3  LATÊNCIA ZERO      o pico do envelope não desloca o sinal: a correlação
      cruzada entrada×saída tem máximo em lag 0
"""
import os
import sys

import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DIR))
import nivel   # noqa: E402

SR = 48000            # física do teste: o sinal é nosso, não é peça
falhas = []
checagens = [0]


def ok(cond, msg):
    checagens[0] += 1
    print(("  ok    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def thd(x, f0=1000.0, sr=SR, nh=10):
    """THD % — Hann, harmônicos 2..nh sobre a fundamental, 3 bins por raia."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    w = np.hanning(n)
    X = np.abs(np.fft.rfft(x * w))
    df = sr / n

    def energia(f):
        k = int(round(f / df))
        lo, hi = max(0, k - 1), min(len(X), k + 2)
        return float((X[lo:hi] ** 2).sum())

    fund = energia(f0)
    harm = sum(energia(f0 * h) for h in range(2, nh + 1) if f0 * h < sr / 2)
    return 100.0 * np.sqrt(harm / fund) if fund > 0 else float("inf")


# ─────────────────────────────────────────────────────── §7.2 · inércia
print("§7.2 — inércia: abaixo do teto o limitador não existe")
t = np.arange(int(2.0 * SR)) / SR
y = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
o, r = nivel.limitar(y, 0.0, SR)
ok(np.array_equal(o, y), "0,4 de pico, teto 0 dBFS → array bit-idêntico")
ok(r["atuou"] is False, "  relatorio['atuou'] is False (identidade, não valor)")
ok(o is y, "  é o MESMO objeto — nem cópia foi feita")

# a borda exata: int16 mínimo é −32768/32768 = −1,0 CRAVADO, e o material real
# deste repo encosta lá (5 das 8 trilhas do disco têm amostra em ±32767).
y1 = np.array([1.0, -1.0, 0.5, 0.0], dtype=np.float32)
o1, r1 = nivel.limitar(y1, 0.0, SR)
ok(np.array_equal(o1, y1) and not r1["atuou"],
   "pico EXATAMENTE 1,0 com teto 0 dBFS → inerte (<=, não <)")

o2, r2 = nivel.limitar(y1, -1.0, SR)
ok(r2["atuou"] is True, "o mesmo sinal com teto −1 dBFS → atua")

# estéreo: o envelope é linkado entre canais
ys = np.stack([0.3 * np.sin(2 * np.pi * 300 * t),
               0.2 * np.sin(2 * np.pi * 700 * t)], axis=1).astype(np.float32)
os_, rs = nivel.limitar(ys, 0.0, SR)
ok(np.array_equal(os_, ys) and not rs["atuou"], "estéreo (n,2) abaixo do teto → inerte")

# estéreo ATUANDO — o caminho que a inércia sozinha não exercita. O envelope é
# LINKADO (máximo entre canais, mesmo ganho nos dois): canal a canal, a imagem
# estéreo se desloca no ataque. O perfil `vsl` pede `canais: 2`, então este
# caminho é produção, não hipótese.
yL = (0.30 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
yR = (1.60 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)   # só o direito estoura
ye = np.stack([yL, yR], axis=1)
oe, re_ = nivel.limitar(ye, 0.0, SR)
ok(re_["atuou"] and float(np.abs(oe).max()) <= 1.0 + 1e-6,
   "estéreo atuando: pico %.6f <= 1,0" % float(np.abs(oe).max()))
razao_in = float(np.abs(yL).max() / np.abs(yR).max())
razao_out = float(np.abs(oe[:, 0]).max() / np.abs(oe[:, 1]).max())
ok(abs(razao_in - razao_out) < 1e-5,
   "  ganho LINKADO: razão L/R %.6f → %.6f (a imagem estéreo não se move)"
   % (razao_in, razao_out))
ok(oe.shape == ye.shape and oe.dtype == ye.dtype,
   "  forma e dtype preservados: %s %s" % (oe.shape, oe.dtype))

# ─────────────────────────────────────────── §7.3 · teto garantido, 500 sorteios
print("§7.3 — teto garantido em 500 sinais aleatórios × 3 tetos")
rng = np.random.default_rng(20260808)


def ruido_com_rajadas():
    n = rng.integers(int(0.05 * SR), int(0.4 * SR))
    x = rng.standard_normal(n).astype(np.float32) * rng.uniform(0.02, 0.3)
    for _ in range(int(rng.integers(1, 5))):
        i0 = int(rng.integers(0, max(1, n - 200)))
        L = int(rng.integers(20, 200))
        x[i0:i0 + L] += (rng.standard_normal(len(x[i0:i0 + L]))
                         .astype(np.float32) * rng.uniform(0.5, 3.0))
    alvo = rng.uniform(0.5, 8.0)
    return (x / max(float(np.abs(x).max()), 1e-9) * alvo).astype(np.float32)


estouros, casos, maior_folga = 0, 0, 0.0
for _ in range(500):
    s = ruido_com_rajadas()
    for teto_db in (0.0, -1.0, -3.0):
        casos += 1
        o, r = nivel.limitar(s, teto_db, SR)
        teto = 10 ** (teto_db / 20)
        excesso = float(np.abs(o).max()) - teto
        maior_folga = max(maior_folga, excesso)
        if excesso > 1e-6:
            estouros += 1
ok(estouros == 0, "%d casos (500 sinais × 3 tetos) · %d estouros · maior excesso %.2e"
   % (casos, estouros, maior_folga))

# ──────────────────────────────────────────────────────── §7.4 · distorção
print("§7.4 — THD: o número que separa limitar de clipar")
t2 = np.arange(int(2.0 * SR)) / SR
x = (1.4125 * np.sin(2 * np.pi * 1000 * t2)).astype(np.float32)   # +3 dB do teto
clipado = np.clip(x, -1, 1)
limitado, rl = nivel.limitar(x, 0.0, SR)
thd_clip, thd_lim = thd(clipado), thd(limitado)
ok(thd_clip > 10.0, "np.clip: THD = %.2f %% (a spec mediu 13,47 %%)" % thd_clip)
ok(thd_lim < 0.01, "nivel.limitar: THD = %.4f %% (< 0,01 %%)" % thd_lim)
ok(abs(float(np.abs(clipado).max()) - 1.0) < 1e-6
   and abs(float(np.abs(limitado).max()) - 1.0) < 1e-6,
   "os dois com pico de saída 1,000000 — a diferença é só timbre")
ok(rl["atuou"] and abs(rl["reducao_max_db"] - 3.0) < 0.2,
   "relatorio: reducao_max_db = %.2f dB (esperado ~3,0)" % rl["reducao_max_db"])

# ───────────────────────────── D1 · controle negativo do teste de distorção
print("D1 — defeito plantado: um 'limitador' que só clipa")


def limitador_falso(y, teto_dbfs):
    teto = 10 ** (teto_dbfs / 20)
    return np.clip(y, -teto, teto)


falso = limitador_falso(x, 0.0)
ok(float(np.abs(falso).max()) <= 1.0 + 1e-6,
   "o falso PASSA no §7.3 (teto respeitado) — é por isso que §7.3 sozinho não basta")
ok(thd(falso) > 10.0, "e REPROVA no §7.4: THD = %.2f %% — o teste tem dentes"
   % thd(falso))

# ───────────────────────── D2 · defeito plantado: sem a trava anti-overshoot
print("D2 — defeito plantado: interpolação sem a trava anti-overshoot")
# 🔎 ONDE a trava morde, medido: o look-ahead já cobre o lado da DESCIDA (gr[j-1]
# <= gl[j-1] <= g[j]), então um pico no começo do bloco nunca fura. Quem fura é o
# lado do RELEASE: gr[j+1] sobe acima de g[j] pelo one-pole, e a reta entre os
# centros j e j+1 leva as amostras da SEGUNDA metade do bloco j junto. Por isso o
# transiente vai na ÚLTIMA amostra de um bloco — um pico no início do bloco
# passaria e o portão ficaria verde sem ter medido nada.
z = (0.05 * rng.standard_normal(SR // 10)).astype(np.float32)
B_ = int(round(SR * nivel.BLOCO_MS / 1000.0))
z[(len(z) // 2 // B_) * B_ + B_ - 1] = 6.0
o_bom, _ = nivel.limitar(z, 0.0, SR)


def limitar_sem_trava(y, teto_dbfs, sr):
    teto = 10 ** (teto_dbfs / 20)
    B = int(round(sr * nivel.BLOCO_MS / 1000.0))
    p = nivel._picos_por_bloco(y, B)
    g = np.where(p > 0, np.minimum(1.0, teto / np.where(p > 0, p, 1.0)), 1.0)
    gl = nivel._min_janela_adiante(g, int(round(nivel.LOOKAHEAD_FALLBACK_MS
                                                / nivel.BLOCO_MS)))
    alfa = float(np.exp(-B / (nivel.RELEASE_FALLBACK_MS / 1000.0 * sr)))
    gr, ant = np.empty_like(gl), 1.0
    for k in range(len(gl)):
        ant = min(gl[k], 1.0 - (1.0 - ant) * alfa)
        gr[k] = ant
    centros = np.arange(len(gl)) * B + (B - 1) / 2.0
    gs = np.interp(np.arange(len(y)), centros, gr)       # ← SEM o min(gs, gl[bloco])
    return (y * gs).astype(y.dtype)


o_ruim = limitar_sem_trava(z, 0.0, SR)
ok(float(np.abs(o_bom).max()) <= 1.0 + 1e-6,
   "com a trava: pico %.6f <= 1,0" % float(np.abs(o_bom).max()))
ok(float(np.abs(o_ruim).max()) > 1.0 + 1e-6,
   "SEM a trava: pico %.6f FURA o teto — a trava não é decorativa"
   % float(np.abs(o_ruim).max()))

# ─────────────────────────────────────────────── D3 · latência zero, medida
print("D3 — latência: o envelope não desloca o sinal (o pecado do alimiter)")
pulsos = np.zeros(int(0.5 * SR), dtype=np.float32)
for i0 in range(2000, len(pulsos) - 2000, 6000):
    pulsos[i0:i0 + 40] = 2.0 * np.hanning(40).astype(np.float32)
saida, _ = nivel.limitar(pulsos, 0.0, SR)
n = 1 << 16
c = np.fft.irfft(np.fft.rfft(saida[:n], n) * np.conj(np.fft.rfft(pulsos[:n], n)), n)
lag = int(np.argmax(np.abs(c)))
lag = lag if lag <= n // 2 else lag - n
ok(lag == 0, "lag da correlação cruzada = %d amostra(s) (o alimiter dá +239)" % lag)
ok(len(saida) == len(pulsos),
   "contagem de amostras preservada: %d → %d" % (len(pulsos), len(saida)))

# ──────────────────────────────────────────────────── §7.8 · validação fatal
print("§7.8 — validação do gain_db é fatal, não decorativa")


def recusa(seg, i, marca):
    try:
        nivel.ler_gain_db(seg, i)
    except nivel.ErroNivel as e:
        texto = str(e)
        ok(marca in texto, "recusou %r · a mensagem cita %r" % (seg, marca))
        return
    ok(False, "ACEITOU %r — devia ter recusado" % seg)


recusa({"beat": "dor", "gain_db": 120}, 7, "[-24, +12]".replace("[-24, +12]", "-24"))
recusa({"beat": "dor", "gain_db": 120}, 7, "dor")
recusa({"beat": "dor", "gain_db": -40}, 7, "-24")
recusa({"beat": "gancho", "gain_db": "3"}, 2, "NÚMERO")
recusa({"beat": "gancho", "gaindb": 3}, 2, "gain_db")
recusa({"beat": "gancho", "ganho_db": 3}, 2, "gain_db")
recusa({"beat": "gancho", "gain_dB": 3}, 2, "gain_db")
recusa({"beat": "gancho", "ganho": 3}, 2, "gain_db")
recusa({"beat": "gancho", "gain_db": True}, 2, "NÚMERO")

ok(nivel.ler_gain_db({"beat": "x"}, 0) == 0.0, "campo ausente → 0,0 (não é erro)")
ok(nivel.ler_gain_db({"beat": "x", "gain_db": 12}, 0) == 12.0, "+12 dB é o teto, aceita")
ok(nivel.ler_gain_db({"beat": "x", "gain_db": -24.0}, 0) == -24.0, "−24 dB é o piso, aceita")
ok(nivel.ganho_linear(0.0) == 1.0, "ganho_linear(0) == 1,0 EXATO (não 0,9999…)")
ok(abs(nivel.ganho_linear(-6.0) - 0.5011872) < 1e-6, "ganho_linear(−6) = 0,50119")
ok(abs(20 * np.log10(nivel.ganho_linear(3.5)) - 3.5) < 1e-9, "ida e volta de 3,5 dB")

# o ganho é EXATO no sinal, que é o que o critério §7.5 mede no material real
seg_x = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
depois = seg_x * nivel.ganho_linear(-6.0)
rms = lambda a: float(np.sqrt(np.mean(np.asarray(a, dtype=np.float64) ** 2)))
ok(abs(20 * np.log10(rms(depois) / rms(seg_x)) + 6.0) < 0.001,
   "RMS cai 6,000 dB com gain_db −6,0")

# ──────────────────────────────────────────────────────────── config e teto
print("config / faixa do teto")
cfg = nivel.config(p={"audio": {"sr": SR}})
ok(cfg["origem"] == "fallback" and cfg["teto_dbfs"] == 0.0,
   "perfil sem `audio.limiter` → fallback, teto 0 dBFS")
cfg2 = nivel.config(p={"audio": {"limiter": {"teto_dbfs": -1.0, "release_ms": 90.0}}})
ok(cfg2["origem"] == "perfil" and cfg2["teto_dbfs"] == -1.0
   and cfg2["lookahead_ms"] == nivel.LOOKAHEAD_FALLBACK_MS,
   "perfil com `audio.limiter` parcial → sobrescreve só o que declara")
for ruim in (1.0, -20.0):
    try:
        nivel.limitar(np.zeros(10, dtype=np.float32), ruim, SR)
        ok(False, "teto %+g ACEITO — devia recusar" % ruim)
    except nivel.ErroNivel:
        ok(True, "teto %+g recusado (faixa [-12, 0])" % ruim)

print("\n%d checagens · %d falha(s)" % (checagens[0], len(falhas)))
for f in falhas:
    print("  ✗ " + f)
sys.exit(1 if falhas else 0)
