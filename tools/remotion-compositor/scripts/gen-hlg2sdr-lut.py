#!/usr/bin/env python3
"""Gera a LUT 3D hlg2sdr.cube (HDR HLG BT.2020 -> SDR BT.709).

Uso: gen-hlg2sdr-lut.py [--alvo apple|neutro|punch|v1] [--croma luz|canal]
                        [--croma-ganho 1.16] > ../luts/hlg2sdr.cube

## A REFERÊNCIA é o conversor da Apple — não a teoria (descoberto em 2026-07-25)

O caminho pra chegar aqui, porque as duas primeiras tentativas erraram:

- **v1 (`--alvo v1`)**: cadeia "de manual" — OOTF γ1.2 + Reinhard com white point
  no PICO (1000 nits). Levantava os pretos ~12% e mandava o branco difuso pra
  196/255. Custo medido no rosto: faixa de contraste -21%, pele lavada, cabelo
  preto virando castanho-avermelhado. **Reprovada pelo creator-1.**
- **`--alvo neutro`** (T(s)=s): a tese era "HLG é retrocompatível, então preservar
  os números do sinal preserva a aparência". **Também errado** — fica ~38% mais
  CLARO que o arquivo do iPhone como a Apple o exibe. A aparência do sinal HLG cru
  NÃO é a referência.
- **`--alvo apple` (DEFAULT, o certo)**: a referência foi MEDIDA do conversor da
  Apple (AVFoundation via `avconvert --preset Preset1920x1080`, que é o mesmo motor
  do app **Edits** do Instagram — e o creator-1 reconhece essa cor como "a do original").
  Curva tabelada em `luts/curva-apple-hlg2sdr.json` (10 frames, 1,2M pixels
  quase-neutros). Ela bate com o gamma de sistema HLG pra display de 100 nits
  (BT.2100 nota 5e, γ≈1,08) com leve levante nos meios: **a conversão correta pra
  SDR é ~22% MAIS ESCURA que o sinal.**
  A Apple também aplica **compensação de croma** (efeito Hunt: baixar luminância
  derruba a saturação percebida) — sem isso a nossa saída ficava 12% menos saturada
  que a dela. Calibrado em `--croma-ganho 1.16`.
  **Erro final vs Apple: pele lum +0,5% · saturação -0,2% · R/B +0,9%.**

Como recalibrar se aparecer footage nova: converter um clipe de 3s com
`avconvert --source x.mov --output y.mov --preset Preset1920x1080 --replace`,
amostrar pixels quase-neutros (sat<0,16) do sinal vs da saída, tabelar a mediana
por bin e ajustar o `--croma-ganho` até o erro de saturação zerar.
(⚠️ Os presets ProRes/HEVC do avconvert **preservam HDR** — só os H.264 tonemapeiam.)

## Cadeia

1. inv-OETF HLG: sinal -> luz de cena (linear)
2. matriz BT.2020 -> BT.709 em LUZ LINEAR (linhas somam 1: neutro segue neutro)
3. tom pelo ganho de LUMINÂNCIA (`--croma luz`, preserva cromaticidade) ou por
   canal (`--croma canal`, desatura quando a curva é compressiva)
4. compensação de croma (`--croma-ganho`)

`--alvo punch` = identidade + S-curve, se algum creator quiser mais contraste.
"""
import argparse
import sys

import numpy as np

N = 45  # 45³ pontos

M = np.array([  # BT.2020 -> BT.709 (linear)
    [1.6605, -0.5876, -0.0728],
    [-0.1246, 1.1329, -0.0083],
    [-0.0182, -0.1006, 1.1187],
])

A, B, C_ = 0.17883277, 0.28466892, 0.55991073


def hlg_inv_oetf(v):
    """sinal -> luz de cena [0..1] (BT.2100)"""
    v = np.asarray(v, dtype=float)
    return np.where(v <= 0.5, (v * v) / 3.0, (np.exp((v - C_) / A) + B) / 12.0)


def alvo_neutro(s):
    """preserva a aparência do sinal (HLG é retrocompatível com SDR)"""
    return s


def alvo_apple(s):
    """curva MEDIDA do conversor da Apple (AVFoundation/avconvert) na footage real.

    É o que o app Edits do Instagram produz (mesmo motor) e o que o creator-1 reconhece
    como "a cor do original". Bate com o gamma de sistema HLG pra display de 100 nits
    (BT.2100 nota 5e, γ≈1.08) com um leve levante nos meios — ou seja: a conversão
    correta pra SDR é MAIS ESCURA que o sinal, não igual a ele. Tabelada em
    `luts/curva-apple-hlg2sdr.json` (10 frames, pixels quase-neutros, 1,2M amostras).
    """
    import json, os
    j = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "luts", "curva-apple-hlg2sdr.json")))
    return np.interp(s, j["sinal"], j["saida"])


def alvo_punch(s):
    """identidade + S-curve suave (pivô 0,42) + branco difuso mais alto"""
    piv, k = 0.42, 0.08
    s_curve = s + k * np.sin(np.pi * np.clip(s, 0, 1)) * (s - piv) / max(piv, 1 - piv)
    # branco difuso (sinal 0,75) sobe de 0,75 pra ~0,84, com 1,0 preservado
    lift = 0.09 * np.clip((s - 0.45) / 0.55, 0, 1) * np.clip((1.0 - s) / 0.25, 0, 1)
    return np.clip(s_curve + lift, 0, 1)


def curva_v1():
    """cadeia da v1 (OOTF 1000 nits + Reinhard no pico) — só pra comparar"""
    PEAK, WHITE, G = 1000.0, 203.0, 1.2
    P = PEAK / WHITE

    def f(s):
        E = hlg_inv_oetf(s)
        d = E * np.where(E > 0, E ** (G - 1.0), 0.0) * P
        tm = d * (1.0 + d / (P * P)) / (1.0 + d)
        return np.clip(tm, 0, 1) ** (1.0 / 2.4)

    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alvo", default="apple", choices=["apple", "neutro", "punch", "v1"])
    ap.add_argument("--size", type=int, default=N)
    # Como a curva é aplicada: 'luz' escala o RGB linear pelo ganho de LUMINÂNCIA
    # (preserva a cromaticidade — é o que a Apple faz); 'canal' aplica por canal
    # (desatura quando a curva é compressiva: medido -11% de saturação vs Apple).
    ap.add_argument("--croma", default="luz", choices=["luz", "canal"])
    # Ganho de croma depois do tom. A Apple aplica compensação perceptual (efeito
    # Hunt: baixar luminância derruba a saturação percebida), e sem isso a nossa
    # conversão fica ~12% menos saturada que a dela. 1.0 = só colorimetria.
    ap.add_argument("--croma-ganho", type=float, default=1.0)
    # 🔴 ROLLOFF do ganho de croma (2026-08-07). O --croma-ganho foi calibrado
    # "amostrando pixels quase-neutros (sat<0,16)" — ver docstring — e depois
    # aplicado LINEARMENTE a TODOS os cromas. Nos croma altos ele extrapola: a
    # Apple comprime o croma alto (rolloff de gamut) e nós multiplicávamos.
    # Erro medido vs avconvert na footage creator-2/peca-02, por faixa de croma:
    #    0-35 -> -0,4 a -1,5   |   35-55 -> 0,0   |   55-110 -> +3,6 a +5,7
    #    110-150 -> +9,9
    # A PELE cai em 55-110, então a cara dela saía +8,5% mais saturada que no app
    # dela — o "avermelhada" que o creator-1 viu. A luma sempre esteve certa (<0,5%).
    # Com rolloff: ganho cheio no croma baixo, caindo a 1.0 conforme o croma sobe.
    #   g(c) = 1 + (ganho-1) / (1 + (c/c0)^2),  c = croma normalizado (max-min)
    # c0=0 desliga o rolloff (comportamento antigo, reproduz as LUTs existentes).
    ap.add_argument("--croma-c0", type=float, default=0.0)
    # Expoente do rolloff. 2 = joelho baixo (começa a cortar cedo, no croma médio
    # — piorou a cena de quarto branco do peca-05). 4+ = joelho alto: quase
    # não toca no croma médio e corta só o extremo, que é onde a Apple comprime.
    ap.add_argument("--croma-exp", type=float, default=2.0)
    a = ap.parse_args()

    n = a.size
    grid = np.linspace(0.0, 1.0, n)

    # curva de re-encode C = T∘E⁻¹ tabelada (luz de cena -> código de saída)
    s_fino = np.linspace(0.0, 1.0, 4097)
    e_fino = hlg_inv_oetf(s_fino)
    t_fino = {"v1": lambda x: curva_v1()(x), "apple": alvo_apple,
              "neutro": alvo_neutro, "punch": alvo_punch}[a.alvo](s_fino)

    # ordem do formato .cube: r varia mais rápido, depois g, depois b
    rr, gg, bb = np.meshgrid(grid, grid, grid, indexing="ij")
    sig = np.stack([rr.transpose(2, 1, 0).ravel(),
                    gg.transpose(2, 1, 0).ravel(),
                    bb.transpose(2, 1, 0).ravel()], axis=1)

    lin = hlg_inv_oetf(sig)                       # luz de cena BT.2020
    lin709 = np.clip(lin @ M.T, 0.0, None)        # gamut em luz linear

    if a.croma == "canal":
        out = np.interp(lin709, e_fino, t_fino)   # curva por canal (desatura)
    else:
        # ganho de luminância: Y -> T(Y), aplicado igual nos 3 canais lineares.
        # Preserva a razão R:G:B, então a cromaticidade não muda com o tom.
        Y = lin709 @ np.array([0.2126, 0.7152, 0.0722])
        Yout = np.interp(Y, e_fino, t_fino) ** 2.4          # alvo em luz linear
        gain = np.where(Y > 1e-6, Yout / np.maximum(Y, 1e-6), 0.0)
        out = (np.clip(lin709 * gain[:, None], 0.0, 1.0)) ** (1.0 / 2.4)
    if a.croma_ganho != 1.0:
        luma = out @ np.array([0.2126, 0.7152, 0.0722])
        if a.croma_c0 > 0:
            c = out.max(axis=1) - out.min(axis=1)          # croma normalizado 0..1
            g = 1.0 + (a.croma_ganho - 1.0) / (1.0 + (c / a.croma_c0) ** a.croma_exp)
            g = g[:, None]
        else:
            g = a.croma_ganho
        out = np.clip(luma[:, None] + (out - luma[:, None]) * g, 0.0, 1.0)
    out = np.clip(out, 0.0, 1.0)

    w = sys.stdout.write
    # cabeçalho = comando COMPLETO que reproduz este arquivo (o parcial anterior
    # omitia --croma-ganho e rendia uma LUT 11% menos saturada — auditoria 2026-07-25)
    w("# hlg2sdr %s/%s ganho %.2f c0 %.2f exp %.1f — reproduz com:\n"
      % (a.alvo, a.croma, a.croma_ganho, a.croma_c0, a.croma_exp))
    w("# gen-hlg2sdr-lut.py --alvo %s --croma %s --croma-ganho %s --croma-c0 %s "
      "--croma-exp %s --size %d\n"
      % (a.alvo, a.croma, ("%.2f" % a.croma_ganho).rstrip("0").rstrip("."),
         ("%.2f" % a.croma_c0).rstrip("0").rstrip("."),
         ("%.1f" % a.croma_exp).rstrip("0").rstrip("."), n))
    w("LUT_3D_SIZE %d\n" % n)
    for px in out:
        w("%.6f %.6f %.6f\n" % (px[0], px[1], px[2]))


if __name__ == "__main__":
    main()
