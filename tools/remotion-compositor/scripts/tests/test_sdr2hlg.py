#!/usr/bin/env python3
"""Bateria da LUT sRGB->HLG (gen-sdr2hlg-lut.py) — a pré-compensação da OOTF.

    python3 tests/test_sdr2hlg.py                (sai 0 se tudo passa)
    python3 tests/test_sdr2hlg.py --com-cadeia   (+ a volta real pelo avconvert)

Sem `pytest`: a bateria é autocontida e roda com `python3`, como as irmãs.

O que ela fecha:

  1  ÂNCORA           branco sRGB -> sinal 0,75 (branco de papel HLG); preto -> 0
  2  NÍVEL            erro de luz ≤1% em 25 patches, sob o modelo de display BT.2100
  3  CROMA            a forma `luz` preserva cromaticidade; a `canal` não
  4  INVARIANTES      monotônica em neutro · sem NaN · cena nunca satura
  5  GRADE            o erro de interpolação trilinear de 45³ cabe no que se promete
  6  γ POR PICO       BT.2100: γ(1000)=1,2 · γ(500)=1,0736 · γ(4000)=1,4529
  7  [gate] EM DISCO  luts/sdr2hlg.cube é reproduzível e declara `ootf luz`
  8  CADEIA REAL      (--com-cadeia) SDR → LUT → HEVC HLG → avconvert → SDR:
                      a forma `luz` tem que ganhar em cromaticidade

E os controles negativos, porque portão verde sem prova de dentes é
indistinguível de portão quebrado:

  D1  `--ootf nenhuma` (a LUT v1) TEM que reprovar o teste de nível, e no valor
      medido pelo relatório: −27,4% no código 128
  D2  `--ootf canal` TEM que reprovar o teste de cromaticidade
  D3  um branco-difuso fora de 0,265 TEM que reprovar o teste de âncora
"""
import importlib.util
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
GERADOR = os.path.join(SCRIPTS, "gen-sdr2hlg-lut.py")
LUT_DISCO = os.path.join(os.path.dirname(SCRIPTS), "luts", "sdr2hlg.cube")

_spec = importlib.util.spec_from_file_location("gen_sdr2hlg", GERADOR)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

falhas = []
checagens = [0]
COM_CADEIA = "--com-cadeia" in sys.argv


def ok(cond, msg):
    checagens[0] += 1
    if not cond:
        falhas.append(msg)
    print(("  ok  " if cond else "  ✗   ") + msg)


# ── o modelo de display, que é o que a LUT inverte ────────────────────────────
def display(cena, gamma=1.2):
    """luz de CENA HLG -> luz de EXIBIÇÃO normalizada (1,0 = pico). BT.2100."""
    Y = np.clip(cena @ G.YW_2020, 0.0, 1.0)
    return (Y[:, None] ** (gamma - 1.0)) * cena


def cena_de(sig, ootf="luz", bd=0.265, gamma=1.2):
    lin = np.clip(G.srgb_eotf(sig) @ G.M709_2020.T, 0.0, 1.0)
    return np.clip(G.cena_hlg(lin, bd, ootf, gamma), 0.0, 1.0), lin


def erro_luz_pct(sig, ootf="luz", bd=0.265, gamma=1.2):
    """quanto a luz exibida se afasta do que o mesmo gráfico daria em SDR."""
    cena, lin = cena_de(sig, ootf, bd, gamma)
    alvo = lin * (bd ** gamma)
    m = alvo > 1e-9
    e = np.zeros_like(alvo)
    e[m] = (display(cena, gamma)[m] / alvo[m] - 1.0) * 100.0
    return e


NEUTROS = np.repeat(
    (np.array([255, 224, 192, 160, 128, 96, 64, 32, 16.0]) / 255.0)[:, None], 3, axis=1)
CORES = np.array([
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 214, 0), (0, 200, 255),
    (255, 0, 180), (255, 140, 20), (120, 60, 220), (180, 40, 40), (40, 160, 70),
    (40, 80, 200), (200, 180, 60), (226, 170, 140), (170, 120, 95),
    (240, 150, 190), (60, 190, 175)], dtype=float) / 255.0
TODOS = np.vstack([NEUTROS, CORES])

print("\n1 · ÂNCORA — o branco de papel e o preto")
cena, _ = cena_de(np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]))
sinal = G.hlg_oetf(cena)
ok(abs(sinal[0].mean() - 0.75) < 5e-4,
   "branco sRGB → sinal HLG %.5f (alvo 0,75, o branco difuso do BT.2100)"
   % sinal[0].mean())
ok(float(np.abs(sinal[1]).max()) < 1e-9,
   "preto sRGB → sinal HLG 0,0 exato (sem 0×inf na guarda da OOTF)")
# D3: a âncora tem que morder se o branco-difuso sair do lugar
c3, _ = cena_de(np.array([[1.0, 1.0, 1.0]]), bd=0.40)
ok(abs(G.hlg_oetf(c3)[0].mean() - 0.75) > 0.05,
   "D3 · branco-difuso 0,40 desloca a âncora para %.3f — o teste morde"
   % G.hlg_oetf(c3)[0].mean())

print("\n2 · NÍVEL — erro de luz sob o display BT.2100")
e = np.abs(erro_luz_pct(TODOS))
ok(e.max() < 1.0,
   "25 patches (9 neutros + 16 cores): pior erro %.4f%% (< 1%%)" % e.max())
# D1: a LUT v1 tem que reprovar aqui, e no número que o relatório mediu
e1 = erro_luz_pct(NEUTROS, ootf="nenhuma")
m128 = e1[4].mean()
ok(np.abs(e1).max() > 10.0,
   "D1 · `--ootf nenhuma` (a LUT v1) reprova: pior erro %.1f%%" % np.abs(e1).max())
# a forma fechada dá l^0,2−1 = −26,4% no código 128; a §2.1 mediu −27,4% na
# cadeia real, com quantização de 8 bits e a matriz 709→2020 no meio. A faixa
# cobre as duas: o que importa é que o defeito apareça NA ORDEM certa, não que
# um número de papel bata com um de encoder.
ok(-28.5 < m128 < -25.0,
   "D1 · e reprova na ordem medida: código 128 a %.1f%% (forma fechada −26,4%%, "
   "a §2.1 mediu −27,4%% na cadeia real)" % m128)

print("\n3 · CROMA — quem preserva a cor do gráfico")


def desvio_croma(ootf):
    cena, lin = cena_de(CORES, ootf)
    d = display(cena)
    s_d, s_a = d.sum(axis=1, keepdims=True), lin.sum(axis=1, keepdims=True)
    return float(np.abs(d[:, :2] / np.maximum(s_d, 1e-12)
                        - lin[:, :2] / np.maximum(s_a, 1e-12)).max() * 1000)


dl, dc = desvio_croma("luz"), desvio_croma("canal")
ok(dl < 0.1, "`luz` preserva cromaticidade: pior desvio %.4f milésimos" % dl)
ok(dc > 5.0, "D2 · `canal` reprova: pior desvio %.1f milésimos" % dc)

print("\n4 · INVARIANTES")
cena, _ = cena_de(NEUTROS)
s = G.hlg_oetf(cena)[:, 1]
ok(bool(np.all(np.diff(s) < 0)),
   "monotônica em neutro (255→16 desce sem inversão): %s"
   % np.round(s, 3).tolist())
g = np.linspace(0, 1, 21)
rr, gg, bb = np.meshgrid(g, g, g, indexing="ij")
grade = np.stack([rr.ravel(), gg.ravel(), bb.ravel()], axis=1)
cena_g, _ = cena_de(grade)
bruta = G.cena_hlg(np.clip(G.srgb_eotf(grade) @ G.M709_2020.T, 0, 1), 0.265, "luz", 1.2)
ok(bool(np.isfinite(bruta).all()), "sem NaN/inf em 9261 cores")
ok(float(bruta.max()) <= 1.0,
   "a cena nunca satura antes do clip: máximo %.4f (o clip não está escondendo "
   "nada)" % bruta.max())
ok(float(G.hlg_oetf(cena_g).max()) <= 1.0 and float(G.hlg_oetf(cena_g).min()) >= 0.0,
   "sinal HLG dentro de [0,1] nas 9261")

print("\n5 · GRADE — o custo de interpolar 45³")


def trilinear(tab, n, sig):
    x = np.clip(sig, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(x).astype(int), n - 2)
    f = x - i0
    out = np.zeros((len(sig), 3))
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = ((f[:, 0] if dr else 1 - f[:, 0])
                     * (f[:, 1] if dg else 1 - f[:, 1])
                     * (f[:, 2] if db else 1 - f[:, 2]))
                out += w[:, None] * tab[i0[:, 0] + dr, i0[:, 1] + dg, i0[:, 2] + db]
    return out


n = 45
gr = np.linspace(0.0, 1.0, n)
r3, g3, b3 = np.meshgrid(gr, gr, gr, indexing="ij")
tab = G.hlg_oetf(cena_de(np.stack([r3.ravel(), g3.ravel(), b3.ravel()], axis=1))[0]
                 ).reshape(n, n, n, 3)
gg2 = (np.arange(20) + 0.5) / 20.0          # fora dos nós, de propósito
r2, g2, b2 = np.meshgrid(gg2, gg2, gg2, indexing="ij")
s2 = np.stack([r2.ravel(), g2.ravel(), b2.ravel()], axis=1)
lin2 = np.clip(G.srgb_eotf(s2) @ G.M709_2020.T, 0.0, 1.0)
alvo2 = lin2 * (0.265 ** 1.2)
cena_i = np.clip(np.where(trilinear(tab, n, s2) <= 0.5,
                          trilinear(tab, n, s2) ** 2 / 3.0,
                          (np.exp((trilinear(tab, n, s2) - G.C) / G.A) + G.B) / 12.0),
                 0, 1)
m = alvo2.max(axis=1) > 0.02
ei = np.abs((display(cena_i)[m] / np.maximum(alvo2[m], 1e-12) - 1.0) * 100.0)
ok(ei.mean() < 0.5 and np.percentile(ei, 95) < 1.0,
   "8000 cores FORA dos nós: erro médio %.3f%% · p95 %.3f%% · pior %.2f%%"
   % (ei.mean(), np.percentile(ei, 95), ei.max()))

print("\n6 · γ POR PICO — BT.2100")
for pico, alvo in ((1000, 1.2), (500, 1.0736), (4000, 1.4529)):
    got = G.gamma_ootf(pico)
    ok(abs(got - alvo) < 5e-4, "γ(%d nits) = %.4f" % (pico, got))

print("\n7 · [gate] A LUT EM DISCO")
if not os.path.exists(LUT_DISCO):
    ok(False, "luts/sdr2hlg.cube não existe")
else:
    with open(LUT_DISCO, encoding="utf-8") as fh:
        disco = fh.read()
    ok("--ootf luz" in disco.splitlines()[1],
       "o cabeçalho declara o comando que a reproduz: %s"
       % disco.splitlines()[1][2:].strip())
    novo = subprocess.run([sys.executable, GERADOR], capture_output=True,
                          text=True).stdout
    ok(novo == disco, "regenerar dá byte a byte o mesmo arquivo (%d linhas)"
       % len(disco.splitlines()))
    corpo = np.array([[float(v) for v in ln.split()]
                      for ln in disco.splitlines() if ln and ln[0].isdigit()])
    ok(len(corpo) == 45 ** 3, "%d nós (45³)" % len(corpo))
    ok(abs(corpo[-1].mean() - 0.75) < 5e-4,
       "o último nó (branco) está em %.5f — a âncora sobreviveu ao arquivo"
       % corpo[-1].mean())

print("\n8 · CADEIA REAL — SDR → LUT → HEVC HLG → avconvert → SDR")
TEM = all(shutil.which(b) for b in ("ffmpeg", "ffprobe", "avconvert"))
if not COM_CADEIA:
    print("  ⏭️  pulado (rode com --com-cadeia; leva ~30 s e usa x265 + avconvert)")
elif not TEM:
    print("  ⏭️  pulado: ffmpeg/ffprobe/avconvert não estão no PATH "
          "(avconvert é AVFoundation, só macOS)")
else:
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="sdr2hlg-")
    try:
        COLS, PW, PH = 5, 384, 216
        carta = np.zeros((PH * 5, PW * COLS, 3), dtype=np.uint8)
        pat = np.vstack([NEUTROS, CORES])[:25]
        for i, rgb in enumerate(pat):
            r, c = divmod(i, COLS)
            carta[r * PH:(r + 1) * PH, c * PW:(c + 1) * PW] = np.round(rgb * 255)
        png = os.path.join(tmp, "carta.png")
        Image.fromarray(carta).save(png)

        def sh(*a):
            subprocess.run(a, check=True, capture_output=True)

        ref = os.path.join(tmp, "ref.mp4")
        sh("ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", png, "-t", "1",
           "-r", "30", "-vf",
           "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p,"
           "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
           "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", ref)

        def amostra(v):
            p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "0.5",
                                "-i", v, "-frames:v", "1", "-pix_fmt", "rgb24",
                                "-f", "image2pipe", "-vcodec", "png", "-"],
                               capture_output=True).stdout
            x = np.array(Image.open(io.BytesIO(p)).convert("RGB"), dtype=np.float64)
            out = []
            for i in range(25):
                r, c = divmod(i, COLS)
                my, mx = int(PH * .25), int(PW * .25)
                out.append(x[r * PH + my:(r + 1) * PH - my,
                             c * PW + mx:(c + 1) * PW - mx].reshape(-1, 3).mean(0))
            return G.srgb_eotf(np.array(out) / 255.0)

        def croma(x):
            return x[:, :2] / np.maximum(x.sum(axis=1, keepdims=True), 1e-9)

        c_ref = croma(amostra(ref))
        res = {}
        for modo in ("nenhuma", "canal", "luz"):
            cube = os.path.join(tmp, modo + ".cube")
            with open(cube, "w") as fh:
                fh.write(subprocess.run([sys.executable, GERADOR, "--ootf", modo],
                                        capture_output=True, text=True).stdout)
            hlg = os.path.join(tmp, modo + ".mp4")
            sh("ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", png, "-t", "1",
               "-r", "30", "-vf",
               "format=gbrp,lut3d=file=%s,scale=in_range=full:out_range=tv:"
               "out_color_matrix=bt2020,format=yuv420p10le,setparams="
               "color_primaries=bt2020:color_trc=arib-std-b67:"
               "colorspace=bt2020nc:range=tv" % cube,
               "-c:v", "libx265", "-crf", "12", "-pix_fmt", "yuv420p10le",
               "-tag:v", "hvc1", "-x265-params",
               "log-level=none:colorprim=bt2020:transfer=arib-std-b67:"
               "colormatrix=bt2020nc:range=limited", hlg)
            volta = os.path.join(tmp, modo + "-volta.mov")
            sh("avconvert", "--source", hlg, "--output", volta,
               "--preset", "Preset1920x1080", "--replace")
            d = np.linalg.norm(croma(amostra(volta))[9:] - c_ref[9:], axis=1) * 1000
            res[modo] = (d.mean(), d.max())
            print("      %-8s desvio de croma nas 16 cores: médio %5.1f · pior %5.1f"
                  % (modo, d.mean(), d.max()))
        ctrl = os.path.join(tmp, "ctrl.mov")
        sh("avconvert", "--source", ref, "--output", ctrl,
           "--preset", "Preset1920x1080", "--replace")
        piso = float(np.linalg.norm(croma(amostra(ctrl))[9:] - c_ref[9:],
                                    axis=1).max() * 1000)
        ok(piso < 1.0, "piso de ruído da régua (SDR→avconvert→SDR): %.2f" % piso)
        ok(res["canal"][1] > 5 * max(piso, 0.2),
           "D2 · o defeito plantado (`canal`) acusa: pior %.1f" % res["canal"][1])
        ok(res["luz"][0] < res["canal"][0] and res["luz"][0] < res["nenhuma"][0],
           "`luz` preserva a cor melhor que as duas outras na cadeia REAL "
           "(%.1f < %.1f e < %.1f)"
           % (res["luz"][0], res["canal"][0], res["nenhuma"][0]))
        print("      varreu 3 candidatas + 1 controle × 25 patches, 1 instante cada")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print("\n%d checagens · %d falha(s)" % (checagens[0], len(falhas)))
for f in falhas:
    print("  ✗ " + f)
sys.exit(1 if falhas else 0)
