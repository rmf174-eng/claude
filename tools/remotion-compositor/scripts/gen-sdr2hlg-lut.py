#!/usr/bin/env python3
"""LUT 3D sRGB/BT.709 (SDR) -> sinal HLG/BT.2020, pra compor camada gráfica em HDR.

Uso: gen-sdr2hlg-lut.py [--branco-difuso 0.265] [--ootf luz|canal|nenhuma]
                        [--pico-nits 1000] [--ootf-gamma 1.2]
                        > ../luts/sdr2hlg.cube

POR QUE EXISTE (2026-08-07)
O Instagram no iOS passa a suportar Dolby Vision/HLG nativamente (Meta, nov/2025,
profile 8.4 — exatamente o que o iPhone grava). Então o bruto da creator PODE ser
entregue em HDR, e converter pra SDR joga fora brilho de verdade: medido no bruto
de referência, **29% do quadro está acima do branco difuso HLG**, ou seja, quase um
terço da imagem é destaque que a tela HDR mostra e o SDR não tem como.

Mas a camada gráfica do Remotion é sRGB. Compor ela CRUA sobre um sinal HLG faria
o branco do texto (255) virar o **pico** do HLG em vez do branco de papel — legenda
brilhando ~4x mais que o rosto, cegando. Esta LUT põe o branco do gráfico no lugar
certo da escala.

A CONTA
  branco difuso em HLG = 0,75 do código de sinal (BT.2100). Invertendo a OETF HLG:
     0,75 = a·ln(12L − b) + c   ->   L = 0,265
  ou seja, o branco de papel é **26,5% da luz de pico** do HLG. Então:
     sRGB -> luz linear -> pré-compensa a OOTF -> ×0,265 -> BT.709→BT.2020 -> OETF HLG

## 🔴 A OOTF, QUE A PRIMEIRA VERSÃO ESQUECEU (achado de 2026-08-09)

A v1 desta LUT parava em "luz linear × 0,265" e mandava isso para a OETF HLG. Só que
0,265 é luz de **CENA**, e o display HLG aplica **por cima** a OOTF de sistema γ=1,2.
O gráfico saía a `l^1,2 × 203,6` no lugar de `l × 203` — erro `l^0,2 − 1`, que é
**zero no branco puro** (foi lá que a LUT foi ancorada e conferida, por isso passou)
e cresce descendo: **−27,4% no meio-tom, −58,6% no código 32**. É a causa medida dos
"efeitos escurecidos" — no entregável real, o núcleo branco da legenda estava a +1,4%
e todo o antialias perdia de 15 a 31% de luz, o que aparece como borda escura e dura.
Medição completa em `docs/pos-leva/05-poc-cor.md` §2.

**O conserto é pré-compensar a OOTF antes de escalar.** E aqui a forma importa mais
do que parece: a OOTF do BT.2100 é um ganho de **LUMINÂNCIA** (`RGB_d = Y_cena^(γ−1)
× RGB_cena`), não um expoente por canal. Invertê-la por canal acerta o cinza — onde
os três canais coincidem — e erra a cor. As três formas, medidas:

| pré-compensação            | erro de luz, 4883 cores | desvio de croma na volta pelo avconvert |
|----------------------------|-------------------------|------------------------------------------|
| nenhuma (a LUT v1)         | 24,2% médio · 70,8% pior | 6,6 · pior 17,3                         |
| por canal (`--ootf canal`) | 11,1% médio · 50,8% pior | 51,6 · pior 144,4                       |
| **por luz (DEFAULT)**      | **0,00% · 0,00%**        | **4,6 · pior 11,9**                     |

A coluna da esquerda é forma fechada contra o modelo de display do BT.2100 — e o
0,00% dela é tautológico, é o modelo que esta forma inverte. Quem decide de verdade é
a coluna da direita, que é **medição**: carta de 24 patches → LUT → HEVC 10-bit HLG →
`avconvert --preset Preset1920x1080` → SDR, comparando a cromaticidade rg com o
original (milésimos; o controle SDR→avconvert→SDR mede 0,0, e a forma por canal, que
é o defeito plantado, acusa 144,4). O avconvert **não** reproduz a exibição HLG — ele
a substitui por um tonemap que derruba o branco de 253 para 152 —, então ele não serve
de régua de nível; serve de régua de **cor**, que é onde as candidatas diferem.

⚠️ **γ=1,2 é o valor de BT.2100 para Lw = 1000 nits**, que é o pico do iPhone/XDR e o
destino real das peças. Noutro pico a OOTF muda (`γ = 1,2 + 0,42·log₁₀(Lw/1000)`) —
por isso `--pico-nits` existe. É premissa declarada, não medição do display.
E isto é matemática de transferência fechada, do mesmo tipo que o catálogo já aceita
como calibrada para `bt2020_sdr`: **o olho de quem edita ainda decide.**
"""
import argparse
import math
import sys

import numpy as np

N = 45

# BT.709 -> BT.2020 em luz LINEAR
M709_2020 = np.array([
    [0.6274039, 0.3292830, 0.0433131],
    [0.0690973, 0.9195404, 0.0113623],
    [0.0163914, 0.0880133, 0.8955953],
])

# luminância BT.2020 — é ela que a OOTF do BT.2100 usa, e é por isso que a
# pré-compensação por luz preserva cromaticidade e a por canal não.
YW_2020 = np.array([0.2627, 0.6780, 0.0593])

A, B, C = 0.17883277, 0.28466892, 0.55991073


def hlg_oetf(L):
    """luz linear normalizada (1,0 = pico) -> sinal HLG 0..1"""
    L = np.clip(L, 0.0, 1.0)
    return np.where(L <= 1.0 / 12.0, np.sqrt(3.0 * L),
                    A * np.log(np.maximum(12.0 * L - B, 1e-12)) + C)


def srgb_eotf(v):
    """código sRGB 0..1 -> luz linear 0..1 (curva sRGB de verdade, não γ2.2 puro)"""
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def gamma_ootf(pico_nits):
    """BT.2100: γ = 1,2 para Lw = 1000 nits, corrigido pelo pico real."""
    return 1.2 + 0.42 * math.log10(max(pico_nits, 1.0) / 1000.0)


def cena_hlg(lin2020, branco_difuso, ootf, gamma):
    """luz de EXIBIÇÃO desejada (relativa ao branco SDR) -> luz de CENA HLG.

    O gráfico é referenciado a DISPLAY: ele foi feito para ser visto como está.
    Quem escreve na cena tem que desfazer a OOTF que o display vai aplicar.
    """
    if ootf == "nenhuma":
        # v1: ancora em luz de cena e deixa a OOTF do display escurecer tudo
        # abaixo do branco. Fica para bissecção e para regenerar a LUT antiga.
        return lin2020 * branco_difuso
    if ootf == "canal":
        # inversa exata de um display que aplicasse a OOTF por canal. Acerta o
        # cinza e desvia a cor; medido acima.
        return (lin2020 ** (1.0 / gamma)) * branco_difuso
    # "luz" — inversa exata da OOTF do BT.2100. `branco_difuso` continua sendo a
    # CENA do branco (o que ancora o sinal em 0,75), então a luz de exibição que
    # ele representa é branco_difuso^γ.
    disp = lin2020 * (branco_difuso ** gamma)
    Yd = np.clip(disp @ YW_2020, 0.0, 1.0)
    # Y_d = Y_cena^γ  =>  cena = disp × Y_d^((1−γ)/γ). Em preto puro o fator
    # diverge, mas `disp` já é 0 — a guarda evita o 0×inf, não corrige nada.
    ganho = np.where(Yd > 0.0,
                     np.power(np.maximum(Yd, 1e-12), (1.0 - gamma) / gamma), 0.0)
    return disp * ganho[:, None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=N)
    # 0,265 = branco de papel em HLG (código 0,75). Baixar deixa o gráfico mais
    # discreto contra o vídeo; subir aproxima do pico e começa a cegar.
    ap.add_argument("--branco-difuso", type=float, default=0.265)
    ap.add_argument("--ootf", choices=("luz", "canal", "nenhuma"), default="luz",
                    help="como pré-compensar a OOTF do display HLG "
                         "(luz = BT.2100, o default; nenhuma = a LUT v1)")
    ap.add_argument("--pico-nits", type=float, default=1000.0,
                    help="pico do display de destino; define γ pelo BT.2100")
    ap.add_argument("--ootf-gamma", type=float, default=None,
                    help="γ explícito, sobrescreve --pico-nits")
    a = ap.parse_args()

    gamma = a.ootf_gamma if a.ootf_gamma else gamma_ootf(a.pico_nits)

    n = a.size
    grid = np.linspace(0.0, 1.0, n)
    rr, gg, bb = np.meshgrid(grid, grid, grid, indexing="ij")
    sig = np.stack([rr.transpose(2, 1, 0).ravel(),
                    gg.transpose(2, 1, 0).ravel(),
                    bb.transpose(2, 1, 0).ravel()], axis=1)

    lin2020 = np.clip(srgb_eotf(sig) @ M709_2020.T, 0.0, 1.0)
    cena = np.clip(cena_hlg(lin2020, a.branco_difuso, a.ootf, gamma), 0.0, 1.0)
    out = np.clip(hlg_oetf(cena), 0.0, 1.0)

    bd = ("%.3f" % a.branco_difuso).rstrip("0").rstrip(".")
    w = sys.stdout.write
    w("# sdr2hlg branco-difuso %s · ootf %s (γ=%.4f, pico %.0f nits) — reproduz com:\n"
      % (bd, a.ootf, gamma, a.pico_nits))
    w("# gen-sdr2hlg-lut.py --branco-difuso %s --ootf %s --pico-nits %.0f --size %d\n"
      % (bd, a.ootf, a.pico_nits, n))
    w("LUT_3D_SIZE %d\n" % n)
    for px in out:
        w("%.6f %.6f %.6f\n" % (px[0], px[1], px[2]))


if __name__ == "__main__":
    main()
