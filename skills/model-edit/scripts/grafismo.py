#!/usr/bin/env python3
"""grafismo — ISOLA a camada gráfica de um frame por DIFERENÇA e mede tudo dela.

A ideia: um overlay (título, legenda, cartão) é a única coisa que muda entre dois
frames do MESMO plano com fundo estático. Diferença entre eles = o grafismo, limpo,
sem depender de threshold de cor (que sempre pega a parede/a pele junto).

Duas fontes de "frame sem o grafismo":
  • outro frame do MESMO plano do editado, antes do elemento entrar (preferível);
  • o frame correspondente do BRUTO, quando existe o par e o plano é z=1.

Uso:
    grafismo.py <frame-com.jpg> <frame-sem.jpg> [--limiar 60] [--faixas y0:y1:rotulo ...]
                [--png saida.png]

Saída: bbox em coords do arquivo E em 1080x1920 (o espaço em que a gente edita),
cor do núcleo do elemento, e conferência das zonas seguras de UI do projeto.

⚠️ Escolha um "frame-sem" do MESMO plano. Frame de outro plano = enquadramento
diferente = a diferença acende a imagem inteira e a medição não vale nada.
"""
import argparse
import numpy as np
from PIL import Image

# zonas proibidas do projeto, em 1080x1920 (docs: skill remotion-compositor)
UI_TOPO, UI_BASE, UI_DIR = 290, 1500, 924


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("com"); ap.add_argument("sem")
    ap.add_argument("--limiar", type=float, default=60)
    ap.add_argument("--faixas", nargs="*", default=[],
                    help="y0:y1:rotulo (em coords do arquivo). Sem isso, mede o frame inteiro.")
    ap.add_argument("--png", help="salva o mapa de diferença pra você OLHAR")
    a = ap.parse_args()

    A = np.asarray(Image.open(a.com).convert("RGB"), float)
    B = np.asarray(Image.open(a.sem).convert("RGB"), float)
    if A.shape != B.shape:
        B = np.asarray(Image.open(a.sem).convert("RGB").resize(
            (A.shape[1], A.shape[0])), float)
    H, W, _ = A.shape
    d = np.abs(A - B).mean(axis=2)
    m = d > a.limiar
    esc = 1080 / W   # fator pra coords 1080x1920

    faixas = ([tuple(f.split(":")) for f in a.faixas] or [("0", str(H), "elemento")])
    for y0, y1, lbl in faixas:
        y0, y1 = int(y0), int(y1)
        mm = m[y0:y1]
        ys, xs = np.where(mm)
        if len(ys) < 30:
            print(f"{lbl}: nada acima do limiar ({mm.sum()} px)"); continue
        X0, X1 = xs.min() * esc, xs.max() * esc
        Y0, Y1 = (ys.min() + y0) * esc, (ys.max() + y0) * esc
        print(f"\n{lbl}: {mm.sum()} px")
        print(f"  arquivo   : x {xs.min()}–{xs.max()} · y {ys.min()+y0}–{ys.max()+y0}")
        print(f"  1080x1920 : x {X0:.0f}–{X1:.0f} (larg {X1-X0:.0f}) · y {Y0:.0f}–{Y1:.0f} (alt {Y1-Y0:.0f})")
        print(f"  centro    : x {(X0+X1)/2/1080*100:.1f}%  ·  y {(Y0+Y1)/2/1920*100:.1f}%")
        px = A[y0:y1][mm]
        idx = np.argsort(d[y0:y1][mm])[-max(1, len(px) // 5):]
        c = px[idx]
        print(f"  cor núcleo: #{int(c[:,0].mean()):02x}{int(c[:,1].mean()):02x}{int(c[:,2].mean()):02x}"
              f"  RGB({c[:,0].mean():.0f},{c[:,1].mean():.0f},{c[:,2].mean():.0f})")
        prob = []
        if Y0 < UI_TOPO: prob.append(f"y<{UI_TOPO} (corte 4:5 do feed) por {UI_TOPO-Y0:.0f}px")
        if Y1 > UI_BASE: prob.append(f"y>{UI_BASE} (legenda/perfil) por {Y1-UI_BASE:.0f}px")
        if X1 > UI_DIR:  prob.append(f"x>{UI_DIR} (coluna de botões) por {X1-UI_DIR:.0f}px")
        print("  zonas UI  : " + (" · ".join(prob) if prob else "dentro das zonas seguras"))

    if a.png:
        Image.fromarray(np.clip(d * 2, 0, 255).astype("uint8")).save(a.png)
        print(f"\nmapa de diferença: {a.png}  (OLHE a imagem — número não substitui olho)")


if __name__ == "__main__":
    main()
