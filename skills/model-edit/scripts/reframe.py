#!/usr/bin/env python3
"""reframe — mede o RECORTE (crop + zoom) de um frame editado contra um frame de referência.

`editado(x,y) = referencia(x0 + x/z, y0 + y/z)` — descobre z, x0, y0 por casamento
multiescala (correlação normalizada), em três passes cada vez mais finos.

Duas maneiras de usar:
  1. contra o BRUTO (quando existe o par): dá o zoom absoluto de cada plano.
  2. contra o PRIMEIRO PLANO do próprio editado: dá o zoom RELATIVO entre planos —
     funciona mesmo sem o bruto, desde que o fundo seja estático (talking-head).

Uso:
    reframe.py <ref.jpg> <editado.jpg> [--ybase Y0] [--yend Y1]

--ybase/--yend limitam a FAIXA do editado analisada. Obrigatório em split-screen:
sem isso o casamento tenta explicar o b-roll com pixels do bruto e não converge.

Interpretação:
  z ≈ 1.00 → enquadramento nativo · z ≈ 1.2–1.35 → punch-in típico de reels
  y0 muito negativo → a base foi EMPURRADA pra baixo (padrão de split-screen)
  correlação < 0.45 → não confie; a pessoa se moveu demais ou a faixa está errada
"""
import argparse
import numpy as np
from PIL import Image


def ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a * a).sum()) * np.sqrt((b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def match(ref, tmpl_im, zs, div=8, x0r=None, y0r=None, span=None):
    RW, RH = ref.size
    best = None
    for z in zs:
        cw, ch = tmpl_im.size[0] / z, tmpl_im.size[1] / z
        if cw > RW or ch > RH:
            continue
        tw, th = max(24, int(cw / div)), max(24, int(ch / div))
        t = np.asarray(tmpl_im.resize((tw, th), Image.BILINEAR), float)
        sw, sh = int(RW / div), int(RH / div)
        src = np.asarray(ref.resize((sw, sh), Image.BILINEAR), float)
        xs = (range(0, sw - tw + 1) if x0r is None else
              range(max(0, int(x0r / div) - span), min(sw - tw + 1, int(x0r / div) + span + 1)))
        ys = (range(0, sh - th + 1) if y0r is None else
              range(max(0, int(y0r / div) - span), min(sh - th + 1, int(y0r / div) + span + 1)))
        for yy in ys:
            for xx in xs:
                s = ncc(t, src[yy:yy + th, xx:xx + tw])
                if best is None or s > best[3]:
                    best = (z, xx * div, yy * div, s)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref"); ap.add_argument("editado")
    ap.add_argument("--ybase", type=int, default=None)
    ap.add_argument("--yend", type=int, default=None)
    ap.add_argument("--zmin", type=float, default=0.55)
    ap.add_argument("--zmax", type=float, default=1.45)
    a = ap.parse_args()

    ref = Image.open(a.ref).convert("L")
    full = Image.open(a.editado).convert("L")
    EW, EH = full.size
    box = (0, a.ybase or 0, EW, a.yend or EH)
    tmpl = full.crop(box)

    b = match(ref, tmpl, np.arange(a.zmin, a.zmax, 0.05), div=16)
    b = match(ref, tmpl, np.arange(max(0.3, b[0] - 0.06), b[0] + 0.061, 0.01), div=8,
              x0r=b[1], y0r=b[2], span=8)
    b = match(ref, tmpl, np.arange(b[0] - 0.012, b[0] + 0.0121, 0.003), div=4,
              x0r=b[1], y0r=b[2], span=6)
    z, x0, y0, s = b
    y0_frame = y0 - (box[1] / z)
    cw, ch = EW / z, EH / z
    RW, RH = ref.size
    print(f"arquivo    : {a.editado}  (faixa y {box[1]}–{box[3]})")
    print(f"zoom z     : {z:.3f}   (recorte {cw:.0f}x{ch:.0f} de {RW}x{RH})")
    print(f"origem     : x0={x0:.0f}  y0(frame)={y0_frame:.0f}")
    print(f"centro %   : cx={(x0+cw/2)/RW*100:.1f}%  cy={(y0_frame+ch/2)/RH*100:.1f}%")
    print(f"pro montar.sh → \"zoom\": {z:.3f}, \"cx\": {(x0+cw/2)/RW:.3f}, \"cy\": {(y0_frame+ch/2)/RH:.3f}")
    print(f"correlação : {s:.4f}" + ("   ⚠️ BAIXA — não confie" if s < 0.45 else ""))


if __name__ == "__main__":
    main()
