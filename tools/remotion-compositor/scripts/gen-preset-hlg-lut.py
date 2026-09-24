#!/usr/bin/env python3
"""Traduz o preset de cor SDR de um creator para o domínio HLG/BT.2020, preservando o HDR.

Uso: gen-preset-hlg-lut.py [--creator creator-2] > ../luts/preset-creator-2-hlg.cube

POR QUE EXISTE (2026-08-08)
Desde que a entrega passou a ter versão HDR (`v-final-hdr.mp4`), o preset oficial
do creator ficou de fora dela — ele foi calibrado no domínio SDR e **aplicá-lo cru
sobre um sinal HLG está errado**: os pontos de controle da curva (0,10 · 0,45 ·
0,78) representam luminâncias completamente diferentes nas duas curvas. Em HLG o
BRANCO DE PAPEL já está em 0,75 do sinal, então o ponto "0,78" do preset — que no
SDR é destaque — cai praticamente no branco difuso, e tudo acima (o headroom HDR,
que é ~29% do quadro no bruto da creator-2) receberia a parte da curva feita pra
super-brancos. O resultado seria escurecer justamente o que faz o HDR valer.

O QUE ESTE SCRIPT FAZ
Aplica o preset na luminância RELATIVA AO BRANCO DE PAPEL, que é o espaço em que
ele foi pensado, e devolve pro sinal HLG:

  s (sinal HLG) -> L = HLG_EOTF⁻¹(s)          luz linear, 1,0 = pico
                -> x = (L / 0,265) ^ (1/2,2)  código "como se fosse SDR"
                                              (0,265 = branco de papel em HLG)
                -> x' = preset(x)             a curva do creator, estendida > 1
                -> L' = x'^2,2 · 0,265
                -> s' = HLG_OETF(L')

A EXTENSÃO ACIMA DE 1 é a decisão de design: `curves` do ffmpeg só define [0,1], e
o headroom HDR vive acima disso. Aqui o ganho multiplicativo que a curva aplica em
x=1 (no preset da creator-2: 0,90, o "destaques −19") é mantido constante acima do
branco de papel. Isso escurece os destaques na MESMA proporção que o SDR — coerente
com a intenção do preset — em vez de clipar tudo.

⚠️ A VINHETA NÃO ENTRA AQUI. Ela é espacial, não pontual, então não cabe numa LUT
3D. Aplique depois, e **recalibre a força**: em HLG o `vignette` multiplica código
de sinal, que não é proporcional à luz. Medir no rosto e bater com o alvo do SDR.
"""
import argparse
import sys

import numpy as np

N = 45
A, B, C = 0.17883277, 0.28466892, 0.55991073
BRANCO_DIFUSO = 0.265  # luz linear (1,0 = pico HLG) que corresponde ao sinal 0,75

# presets oficiais, na forma em que foram calibrados no SDR
PRESETS = {
    # creator-2 (creator-2): tradução ffmpeg do preset que ela usa no app —
    # iluminação −5, destaques −19, sombras +5. A vinheta (PI/12) fica de fora.
    "creator-2": {
        "pontos": [(0.0, 0.0), (0.10, 0.115), (0.45, 0.452), (0.78, 0.727), (1.0, 0.90)],
        "brightness": -0.018,
    },
}


def hlg_oetf(L):
    L = np.clip(L, 0.0, 1.0)
    return np.where(L <= 1.0 / 12.0, np.sqrt(np.maximum(3.0 * L, 0.0)),
                    A * np.log(np.maximum(12.0 * L - B, 1e-9)) + C)


def hlg_inv_oetf(e):
    e = np.clip(e, 0.0, 1.0)
    return np.where(e <= 0.5, (e * e) / 3.0, (np.exp((e - C) / A) + B) / 12.0)


def spline_natural(pts):
    """spline cúbica natural — é o que o filtro `curves` do ffmpeg usa entre os
    pontos de controle. Sem scipy nesta máquina, então é resolvido na mão
    (sistema tridiagonal por eliminação de Thomas)."""
    x = np.array([p[0] for p in pts], dtype=float)
    y = np.array([p[1] for p in pts], dtype=float)
    n = len(x)
    h = np.diff(x)
    alpha = np.zeros(n)
    for i in range(1, n - 1):
        alpha[i] = 3.0 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
    l = np.ones(n)
    mu = np.zeros(n)
    z = np.zeros(n)
    for i in range(1, n - 1):
        l[i] = 2.0 * (x[i + 1] - x[i - 1]) - h[i - 1] * mu[i - 1]
        mu[i] = h[i] / l[i]
        z[i] = (alpha[i] - h[i - 1] * z[i - 1]) / l[i]
    b = np.zeros(n)
    c = np.zeros(n)
    d = np.zeros(n)
    for j in range(n - 2, -1, -1):
        c[j] = z[j] - mu[j] * c[j + 1]
        b[j] = (y[j + 1] - y[j]) / h[j] - h[j] * (c[j + 1] + 2.0 * c[j]) / 3.0
        d[j] = (c[j + 1] - c[j]) / (3.0 * h[j])

    def f(t):
        t = np.asarray(t, dtype=float)
        i = np.clip(np.searchsorted(x, t) - 1, 0, n - 2)
        dt = t - x[i]
        return y[i] + b[i] * dt + c[i] * dt * dt + d[i] * dt ** 3
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--creator", default="creator-2", choices=sorted(PRESETS))
    ap.add_argument("--size", type=int, default=N)
    ap.add_argument("--branco-difuso", type=float, default=BRANCO_DIFUSO)
    a = ap.parse_args()
    P = PRESETS[a.creator]
    curva = spline_natural(P["pontos"])

    def preset(x):
        """a curva do creator, definida em [0,1] e ESTENDIDA acima de 1 pelo ganho
        que ela aplica no branco de papel (ver docstring)."""
        x = np.asarray(x, dtype=float)
        g1 = float(curva(np.array([1.0]))[0])           # 0,90 no preset da creator-2
        dentro = np.clip(curva(np.clip(x, 0.0, 1.0)) + P["brightness"], 0.0, None)
        fora = (x * g1) + P["brightness"]
        return np.where(x <= 1.0, dentro, fora)

    n = a.size
    grid = np.linspace(0.0, 1.0, n)
    rr, gg, bb = np.meshgrid(grid, grid, grid, indexing="ij")
    sig = np.stack([rr.transpose(2, 1, 0).ravel(),
                    gg.transpose(2, 1, 0).ravel(),
                    bb.transpose(2, 1, 0).ravel()], axis=1)

    L = hlg_inv_oetf(sig)                       # luz linear (1,0 = pico)
    x = (L / a.branco_difuso) ** (1.0 / 2.2)    # código relativo ao branco de papel
    xl = preset(x)
    Ll = np.clip(np.maximum(xl, 0.0) ** 2.2 * a.branco_difuso, 0.0, 1.0)
    out = np.clip(hlg_oetf(Ll), 0.0, 1.0)

    w = sys.stdout.write
    w("# preset %s traduzido pra HLG (branco de papel %.3f) — reproduz com:\n"
      % (a.creator, a.branco_difuso))
    w("# gen-preset-hlg-lut.py --creator %s --branco-difuso %s --size %d\n"
      % (a.creator, ("%.3f" % a.branco_difuso).rstrip("0").rstrip("."), n))
    w("# ATENCAO: a vinheta do preset NAO esta aqui (e espacial) — aplicar depois\n")
    w("LUT_3D_SIZE %d\n" % n)
    for px in out:
        w("%.6f %.6f %.6f\n" % (px[0], px[1], px[2]))


if __name__ == "__main__":
    main()
