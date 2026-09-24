#!/usr/bin/env python3
"""Gera uma LUT 3D que DOMA a faixa quente (pele/laranja) sem tocar no resto.

Uso: gen-peca-12-quente-lut.py --forca 0.35 [--hue 0.35] > ../luts/peca-12-quente-35.cube
     e aplica-se DEPOIS da hlg2sdr:  -vf "lut3d=hlg2sdr.cube,lut3d=peca-12-quente-35.cube"

## POR QUE ISTO EXISTE, e por que NÃO é conserto de bug

Pedido do creator-1 em 2026-07-28: "ficou um pouco estourado no laranja... acho que ajustou
assim por causa do sol no fundo". Antes de mexer, medi: convertendo o MESMO trecho com a
nossa `hlg2sdr.cube` e com o conversor da Apple (`avconvert`, o motor do app Edits do
Instagram, que é a referência de cor deste projeto), a diferença é de 1 a 2%:

    saturação no quente +0,9% · calor (R−B) +1,6% · luminância −1,6%

Ou seja: **a conversão está certa.** O laranja é do próprio pôr do sol batendo no
escritório — o Instagram entregaria a mesma coisa. peca-12 isso é decisão de GRADE, não
correção de erro, e por isso vive numa LUT separada e opcional em vez de virar mudança na
`hlg2sdr.cube` (que precisa continuar fiel).

## O que a medição mostrou sobre ONDE está o laranja

Contra a intuição ("é o sol na janela"), no frame mais saturado o quente está na PELE, e
a janela estava fria:

| região | lum | sat | R−B |
|---|---|---|---|
| rosto | 108 | 0,39 | **+66** |
| janela/céu | 183 | 0,09 | −16 |
| prédios | 152 | 0,24 | −42 |

Por isso a correção não pode ser balanço de branco global: esfriar tudo jogaria os
prédios (já frios) pro ciano. A ação é seletiva por MATIZ.

## Cadeia

1. matiz e saturação do ponto (HSV)
2. peso = janela suave no matiz (vermelho→amarelo) × saturação acima de um piso
3. dessatura em direção à PRÓPRIA luminância (Rec.709) — brilho não muda
4. gira o matiz levemente pro amarelo (`--hue`), que é o que tira o "vermelhão"
   sem apagar o bronzeado

`--forca 0` devolve identidade, então dá pra medir a régua contra ela.
"""
import argparse
import sys

import numpy as np

N = 33
# janela de matiz em graus: 0=vermelho, 30=laranja, 60=amarelo. Pega vermelho-alaranjado
# e solta antes do amarelo-verde (senão mexe em vegetação e no verde da legenda).
H0, H1, H2, H3 = 342.0, 8.0, 45.0, 68.0     # sobe de H0→H1, platô até H2, cai até H3
SAT_PISO = 0.12                              # abaixo disso é quase-neutro: não tocar


def peso_matiz(h):
    """rampa suave 0→1→0 sobre o matiz, com H0 dando a volta em 360."""
    hh = np.where(h >= H0, h - 360.0, h)      # −18..342 → contínuo em torno do vermelho
    w = np.zeros_like(hh)
    sub = (hh >= H0 - 360.0) & (hh < H1)
    w[sub] = (hh[sub] - (H0 - 360.0)) / (H1 - (H0 - 360.0))
    w[(hh >= H1) & (hh <= H2)] = 1.0
    des = (hh > H2) & (hh <= H3)
    w[des] = 1.0 - (hh[des] - H2) / (H3 - H2)
    return np.clip(w, 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forca", type=float, default=0.35,
                    help="quanto dessaturar a faixa quente (0=identidade, 0.5=metade)")
    ap.add_argument("--hue", type=float, default=0.35,
                    help="fração da força usada pra girar o matiz pro amarelo")
    ap.add_argument("--graus", type=float, default=6.0,
                    help="giro máximo de matiz em graus, no pico do peso")
    a = ap.parse_args()

    g = np.linspace(0.0, 1.0, N)
    b, gr, r = np.meshgrid(g, g, g, indexing="ij")   # ordem do .cube: R varia primeiro
    rgb = np.stack([r.ravel(), gr.ravel(), b.ravel()], axis=1)

    mx = rgb.max(1)
    mn = rgb.min(1)
    dif = mx - mn
    sat = np.where(mx > 1e-6, dif / np.maximum(mx, 1e-6), 0.0)

    # matiz em graus
    R, G, B = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    h = np.zeros_like(mx)
    nz = dif > 1e-6
    imax = rgb.argmax(1)
    sel = nz & (imax == 0)
    h[sel] = 60.0 * (((G - B)[sel] / dif[sel]) % 6.0)
    sel = nz & (imax == 1)
    h[sel] = 60.0 * (((B - R)[sel] / dif[sel]) + 2.0)
    sel = nz & (imax == 2)
    h[sel] = 60.0 * (((R - G)[sel] / dif[sel]) + 4.0)
    h %= 360.0

    w = peso_matiz(h) * np.clip((sat - SAT_PISO) / 0.25, 0, 1)

    out = rgb.copy()
    # 1) giro de matiz pro amarelo, proporcional ao peso
    if a.graus > 0 and a.hue > 0:
        ang = np.radians(a.graus * a.forca * a.hue * w)
        # rotação de croma em torno do eixo neutro (aproximação YUV, barata e estável)
        Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
        U, V = B - Y, R - Y
        c, s = np.cos(ang), np.sin(ang)
        U2, V2 = U * c - V * s, U * s + V * c
        out[:, 0] = Y + V2
        out[:, 2] = Y + U2
        out[:, 1] = (Y - 0.2126 * out[:, 0] - 0.0722 * out[:, 2]) / 0.7152

    # 2) dessatura em direção à própria luminância (não muda brilho)
    Y2 = 0.2126 * out[:, 0] + 0.7152 * out[:, 1] + 0.0722 * out[:, 2]
    k = (a.forca * w)[:, None]
    out = out * (1 - k) + Y2[:, None] * k
    out = np.clip(out, 0.0, 1.0)

    print("# LUT de GRADE (opcional) — doma a faixa quente sem tocar no fundo frio.")
    print(f"# gerada por gen-peca-12-quente-lut.py --forca {a.forca} --hue {a.hue} --graus {a.graus}")
    print("# aplicar DEPOIS da hlg2sdr.cube. Ver o cabeçalho do gerador pro porquê.")
    print(f"LUT_3D_SIZE {N}")
    print("DOMAIN_MIN 0.0 0.0 0.0")
    print("DOMAIN_MAX 1.0 1.0 1.0")
    for p in out:
        print(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
    print(f"pontos: {len(out)} · peso>0 em {(w>0).mean()*100:.1f}% do cubo",
          file=sys.stderr)


if __name__ == "__main__":
    main()
