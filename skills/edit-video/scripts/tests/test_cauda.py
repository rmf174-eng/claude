#!/usr/bin/env python3
"""Testes de `cauda.py` — sinal 100 % sintético, cauda CONHECIDA em cada caso.

    python3 tests/test_cauda.py        (sai 0 se tudo passa)

Não precisa de bruto nenhum: o sinal é gerado com numpy e escrito num `.wav`
temporário. O que se testa:

  1. `medir()` acerta a cauda dentro de UMA janela do envelope (10 ms) em
     0 / 60 / 200 / 450 ms — inclusive o caso 0, que é o que separa "mede" de
     "sempre devolve alguma coisa".
  2. `medir()` NÃO atravessa fala: um burst no meio da sala encurta a cauda.
  3. G5 pega a FRICATIVA que o envelope RMS lê como silêncio — e o teste prova
     que sem G5 o corte decepava o fonema (senão o portão seria verde por não
     ter nada para achar).
  4. G1..G4 por caso de tabela.
  5. A guarda de tipo: chiado de sala com nível ALTO não é fonema (é o falso
     positivo que derrubou as versões anteriores de G5 no bruto de café).
"""
import os
import sys
import tempfile
import wave

import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DIR))
import bordas   # noqa: E402
import cauda    # noqa: E402

SR = 48000            # física do teste, não formato de peça: o sinal é nosso
WIN = 0.01
falhas = []
checagens = [0]


def ok(cond, msg):
    checagens[0] += 1
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def _ruido(dur, dbfs, banda=None, rng=None):
    rng = rng or np.random.default_rng(7)
    n = int(dur * SR)
    x = rng.standard_normal(n)
    if banda:
        f = np.fft.rfftfreq(n, 1 / SR)
        X = np.fft.rfft(x)
        X[(f < banda[0]) | (f >= banda[1])] = 0
        x = np.fft.irfft(X, n)
    r = np.sqrt((x ** 2).mean()) or 1.0
    return x / r * (10 ** (dbfs / 20))


def _envelope(x):
    """mesma conta do bordas.envelope, sobre um array em memória."""
    w = int(WIN * SR)
    n = len(x) // w
    rms = np.sqrt((x[: n * w].reshape(n, w) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def _wav(x, caminho):
    a = np.clip(x, -1.0, 1.0)
    with wave.open(caminho, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes((a * 32767).astype("<i2").tobytes())
    return caminho


# ─────────────────────────────────────────────── 1. medir() com cauda conhecida
print("1. medir() com cauda conhecida (fala 200–1000 Hz a −18 dBFS, sala a −45)")
for esperado in (0.0, 0.06, 0.20, 0.45):
    x = np.concatenate([_ruido(2.0, -18, (200, 1000)),
                        _ruido(esperado, -45) if esperado else np.zeros(0)])
    db = _envelope(x)
    got = cauda.medir(db, 0.0, len(x) / SR, -35.0, WIN)
    ok(abs(got - esperado) <= WIN + 1e-9,
       "cauda de %.0f ms → medida %.0f ms (tolerância 1 janela = 10 ms)"
       % (esperado * 1000, got * 1000))

# ─────────────────────────────── 2. um burst DENTRO da cauda encurta a medição
print("2. burst dentro da cauda encurta a cauda (o oposto do que o decay faz)")
x = np.concatenate([_ruido(2.0, -18, (200, 1000)), _ruido(0.20, -45),
                    _ruido(0.05, -18, (200, 1000)), _ruido(0.20, -45)])
db = _envelope(x)
got = cauda.medir(db, 0.0, len(x) / SR, -35.0, WIN)
ok(abs(got - 0.20) <= 2 * WIN,
   "burst a 200 ms do fim → cauda %.0f ms (esperado ~200, não 450)" % (got * 1000))

# ─────────────────────────────────────────── 3. G5: a fricativa abaixo do gate
print("3. G5 — fricativa que o envelope RMS lê como silêncio")
tmp = tempfile.mkdtemp(prefix="test-cauda-")
FRIC_DUR, CAUDA_DUR, ALVO = 0.08, 0.40, 0.06
x = np.concatenate([_ruido(1.0, -45),                       # sala antes
                    _ruido(1.0, -18, (200, 1000)),          # fala
                    _ruido(FRIC_DUR, -33, (3000, 9000)),    # /s/ final
                    _ruido(CAUDA_DUR, -45)])                # sala depois
p = _wav(x, os.path.join(tmp, "fricativa.wav"))
db = _envelope(x)
e = len(x) / SR
fim_fricativa = 2.0 + FRIC_DUR
PISO = -30.0        # piso ALTO de propósito: a −33 dBFS a fricativa fica ABAIXO
#                     dele, que é exatamente a cegueira do RMS de banda larga.
disp = cauda.medir(db, 0.0, e, PISO, WIN)
ok(disp >= CAUDA_DUR + FRIC_DUR - 2 * WIN,
   "o RMS sozinho atravessa a fricativa: mede %.0f ms de 'silêncio' (a sala tem "
   "só %.0f) — sem G5 o corte de %.0f ms decepava o fonema"
   % (disp * 1000, CAUDA_DUR * 1000, (disp - ALVO) * 1000))
novo_e, corte, motivo = cauda.aparar(db, p, 0.0, e, PISO, ALVO, sr=SR)
ok(motivo == "FONEMA", "G5 acionou (motivo=%s)" % motivo)
ok(novo_e >= fim_fricativa,
   "o corte para DEPOIS da fricativa: novo end %.3f ≥ fim do fonema %.3f"
   % (novo_e, fim_fricativa))
ok(corte < disp - ALVO,
   "o corte encolheu de %.0f ms para %.0f ms por causa de G5"
   % ((disp - ALVO) * 1000, corte * 1000))

# ───────────────────────── 5. chiado de sala ALTO não é fonema (falso positivo)
print("5. chiado de sala alto NÃO aciona G5 (é o falso positivo do bruto de café)")
x2 = np.concatenate([_ruido(1.0, -45), _ruido(1.0, -18, (200, 1000)),
                     _ruido(0.45, -38)])       # sala 7 dB acima do piso_local
p2 = _wav(x2, os.path.join(tmp, "chiado.wav"))
db2 = _envelope(x2)
e2 = len(x2) / SR
novo2, corte2, motivo2 = cauda.aparar(db2, p2, 0.0, e2, -30.0, ALVO, sr=SR)
ok(motivo2 != "FONEMA",
   "chiado de banda larga não vira fonema (motivo=%s, corte %.0f ms)"
   % (motivo2, corte2 * 1000))

# ───────────────────────────────────────────────────── 4. G1..G4 por tabela
print("4. guardas G1–G4")
for kw, esperado in (({"contiguo_com_proximo": True}, "CONTIGUO"),
                     ({"ultimo": True}, "ULTIMO"),
                     ({"fixo": True}, "END_FIXO")):
    _, c, m = cauda.aparar(db, p, 0.0, e, PISO, ALVO, sr=SR, **kw)
    ok(m == esperado and c == 0.0,
       "guarda %-9s → motivo %s, corte %.0f ms (tem que ser 0)"
       % (esperado, m, c * 1000))
# G2 é a única guarda com escape: `--cauda-final` libera o último segmento.
_, c, m = cauda.aparar(db, p, 0.0, e, PISO, ALVO, sr=SR, ultimo=True, cauda_final=True)
ok(c > 0 and m != "ULTIMO",
   "cauda_final=True libera o último segmento (motivo %s, corte %.0f ms)"
   % (m, c * 1000))

# G4: segmento curto — o corte não pode deixá-lo abaixo de DUR_MIN
xs = np.concatenate([_ruido(0.05, -18, (200, 1000)), _ruido(0.40, -45)])
dbs = _envelope(xs)
es = len(xs) / SR
novo_s, corte_s, motivo_s = cauda.aparar(dbs, p, 0.0, es, -35.0, 0.0, sr=SR)
ok(novo_s - 0.0 >= cauda.DUR_MIN - 1e-9,
   "G4: segmento de %.0f ms sobra com %.0f ms (DUR_MIN = %.0f ms), motivo %s"
   % (es * 1000, novo_s * 1000, cauda.DUR_MIN * 1000, motivo_s))

# ─────────────────────────────────────────────────────────── 6. resumo()
print("6. resumo()")
med, p90, mx, acima = cauda.resumo([0.06, 0.06, 0.42, 0.46, 0.0], 0.06)
ok((med, mx, acima) == (60, 460, 2),
   "mediana %d · p90 %d · máx %d · acima do alvo %d" % (med, p90, mx, acima))

for nome in os.listdir(tmp):
    os.remove(os.path.join(tmp, nome))
os.rmdir(tmp)
print("\n%d checagens" % checagens[0])
if falhas:
    print("%d FALHA(S):\n  - %s" % (len(falhas), "\n  - ".join(falhas)))
    sys.exit(1)
print("todas passaram")
sys.exit(0)
