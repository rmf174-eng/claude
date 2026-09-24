#!/usr/bin/env python3
"""mascara — mede o PERFIL DE ALPHA de uma camada sobreposta (o "feather" do split-screen).

Reconstrói a camada BASE aplicando a transformação medida (`reframe.py`) ao frame do
bruto, e compara linha a linha com o composto. Onde o composto ainda "é" a base, o
alpha do overlay é 0; onde não tem nada da base, alpha é 1; no meio está a rampa.

Uso:
    mascara.py <frame-bruto.jpg> <frame-composto.jpg> <z> <x0> <y0> [--passo 40]

(z/x0/y0 saem do reframe.py rodado na FAIXA de baixo do composto.)

⚠️ A correlação só é confiável onde a base tem TEXTURA. Parede lisa dá correlação
aleatória e o perfil vira ruído — por isso o script marca as linhas sem textura.
⚠️ Confirme sempre OLHANDO um recorte da fronteira: uma rampa longa sobre vegetação
tem silhueta irregular e parece "fumaça", mas continua sendo um gradiente.
"""
import argparse
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bruto"); ap.add_argument("composto")
    ap.add_argument("z", type=float); ap.add_argument("x0", type=float); ap.add_argument("y0", type=float)
    ap.add_argument("--passo", type=int, default=40)
    a = ap.parse_args()

    raw = Image.open(a.bruto).convert("RGB")
    comp = Image.open(a.composto).convert("RGB")
    EW, EH = comp.size
    base = raw.transform((EW, EH), Image.EXTENT,
                         (a.x0, a.y0, a.x0 + EW / a.z, a.y0 + EH / a.z), Image.BILINEAR)
    A = np.asarray(comp.convert("L"), float)
    B = np.asarray(base.convert("L"), float)

    print(f"{'y':>6} {'y%':>6} {'corr':>7} {'textura':>8}   perfil (0=overlay opaco · 20=base pura)")
    linhas = []
    for y in range(0, EH - a.passo, a.passo):
        x, b = A[y:y + a.passo].ravel(), B[y:y + a.passo].ravel()
        tex = float(b.std())
        c = 0.0 if tex < 6 or x.std() < 1 else float(np.corrcoef(x, b)[0, 1])
        linhas.append((y, c, tex))
        marca = "" if tex >= 6 else "  (base lisa — ignore)"
        print(f"{y:6d} {y/EH*100:5.1f}% {c:7.3f} {tex:8.1f}   "
              f"{'#'*int(max(0,c)*20):<20}{marca}")

    bons = [(y, c) for y, c, t in linhas if t >= 6]
    if not bons:
        print("\nsem linhas com textura suficiente — escolha outro frame"); return
    opaco = [y for y, c in bons if c < 0.15]
    limpa = [y for y, c in bons if c > 0.75]
    if opaco and limpa:
        yo, yl = max(opaco), min([y for y in limpa if y > max(opaco)] or [max(limpa)])
        print(f"\noverlay OPACO até y≈{yo} ({yo/EH*100:.0f}%) · base LIMPA a partir de y≈{yl} ({yl/EH*100:.0f}%)")
        print(f"FEATHER ≈ {yl-yo}px = {(yl-yo)/EH*100:.0f}% da altura")
        print(f"pro split-broll.py → --opaco {yo/EH*100:.0f} --fim {yl/EH*100:.0f}")


if __name__ == "__main__":
    main()
