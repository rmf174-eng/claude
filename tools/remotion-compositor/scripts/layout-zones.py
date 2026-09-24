#!/usr/bin/env python3
"""Detector de zonas livres pra posicionamento de overlays.

Pra cada janela de tempo, amostra frames do vídeo, segmenta a pessoa (rembg),
faz a UNIÃO das máscaras (pessoa se move ao longo da janela) e devolve:
  - mapa de ocupação em grade (ASCII no stderr, pra inspeção)
  - retângulos livres sugeridos em px da resolução da peça (JSON no stdout)

Uso (dentro do venv com rembg+onnxruntime+pillow — ver layout-zones.sh):
  layout-zones.py <video.mp4> <ini-fim> [<ini-fim> ...] [--samples 5] [--dir <producao>]

Exemplo:
  layout-zones.py v1-sdr.mp4 2.0-8.4 31.0-39.2 --samples 6

📐 A grade e as zonas de UI saem do perfil de peça (SPEC-00), não deste arquivo:
a resolução e o aspecto vêm de `video.*`, e as zonas proibidas de `zonas_ui`, em
FRAÇÕES do quadro. Num perfil com `zonas_ui: null` — VSL, longform, screencast —
não existe UI de feed nenhuma e o bloqueio simplesmente não roda. Era esse o D6:
as zonas eram do Instagram e nenhum código sabia que uma VSL não tem essa UI.
"""
import json
import subprocess
import sys
import tempfile
import os

from PIL import Image
from rembg import new_session, remove

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", ".claude", "skills",
                                "edit-video", "scripts"))
import perfil as perfil_mod   # noqa: E402

OCCUPIED_FRAC = 0.12  # FÍSICA: fração de pixels de pessoa que marca a célula
MARGIN = 24  # respiro nas bordas dos retângulos sugeridos

# preenchidos em main() a partir do perfil
GRID_COLS, GRID_ROWS = 9, 16
CELL = 120
UI_SAFE = None


def grade_de(P):
    """Grade que segue o aspecto da peça, com célula de ~120 px.

    A célula é o que importa (é o grão da ocupação); o nº de colunas e de linhas é
    consequência da resolução."""
    # procedência: em vertical Full HD isto devolve a grade 9x16 histórica; em
    # horizontal, 16x9. A célula de 120 px é a mesma nos dois.
    W, H = int(P["video"]["largura"]), int(P["video"]["altura"])
    cell = 120
    cols = max(1, round(W / cell))
    rows = max(1, round(H / cell))
    return cols, rows, cell


def ui_blocked(r, c):
    """"Quadrado proibido" (guia do creator-1 2026-07-22): zonas da UI do Instagram +
    corte do feed. Elemento gráfico NUNCA entra aqui (a pessoa pode).
      topo    — corte 4:5 do feed + status bar
      fundo   — legenda do post, perfil, áudio
      direita — coluna de botões (like/comentário/share)
    Desativar à mão: --no-ui-safe. Perfil sem `zonas_ui` já não chama esta função."""
    if not UI_SAFE:
        return False
    y0, y1 = r * CELL, (r + 1) * CELL
    x1 = (c + 1) * CELL
    meia = CELL // 2
    if y0 < UI_SAFE["top"] - meia:  # célula majoritariamente acima da linha
        return True
    if y1 > UI_SAFE["bottom"] + meia:
        return True
    if x1 > UI_SAFE["right"] + meia:
        return True
    return False


def sample_frames(video: str, start: float, end: float, n: int, outdir: str):
    paths = []
    for i in range(n):
        t = start + (end - start) * i / max(n - 1, 1)
        p = os.path.join(outdir, f"s{i}.png")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", video,
             "-frames:v", "1", "-y", p],
            check=True,
        )
        # timestamp além do fim do vídeo não gera frame e o ffmpeg sai 0 —
        # sem esta guarda o script morria com FileNotFoundError no Image.open
        # (janela 62.2-66.0 num vídeo de 66.26s, produção peca-03 2026-07-25)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            print(f"  (aviso: sem frame em {t:.2f}s — janela passa do fim do vídeo?)",
                  file=sys.stderr)
            continue
        paths.append(p)
    if not paths:
        sys.exit(f"nenhum frame extraído em {start}-{end}: janela fora do vídeo")
    return paths


def occupancy_grid(session, paths):
    grid = [[0.0] * GRID_COLS for _ in range(GRID_ROWS)]
    for p in paths:
        im = Image.open(p).convert("RGB")
        alpha = remove(im, session=session).split()[-1]
        alpha = alpha.resize((GRID_COLS * 8, GRID_ROWS * 8))
        px = alpha.load()
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                s = sum(
                    1
                    for y in range(r * 8, r * 8 + 8)
                    for x in range(c * 8, c * 8 + 8)
                    if px[x, y] > 128
                )
                grid[r][c] = max(grid[r][c], s / 64.0)
    return [[cell >= OCCUPIED_FRAC for cell in row] for row in grid]


def largest_free_rects(occ, top_k=4):
    """Maiores retângulos livres (método do histograma), sem sobreposição."""
    rects = []
    blocked = [row[:] for row in occ]
    for _ in range(top_k):
        best = None  # (area, r0, c0, r1, c1)
        heights = [0] * GRID_COLS
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                heights[c] = 0 if blocked[r][c] else heights[c] + 1
            stack = []
            for c in range(GRID_COLS + 1):
                h = heights[c] if c < GRID_COLS else 0
                start = c
                while stack and stack[-1][1] >= h:
                    s, sh = stack.pop()
                    area = sh * (c - s)
                    cand = (area, r - sh + 1, s, r, c - 1)
                    if best is None or area > best[0]:
                        best = cand
                    start = s
                stack.append((start, h))
        if not best or best[0] < 4:  # ignora migalhas (<4 células)
            break
        _, r0, c0, r1, c1 = best
        rects.append(
            {
                "x": c0 * CELL + MARGIN,
                "y": r0 * CELL + MARGIN,
                "w": (c1 - c0 + 1) * CELL - 2 * MARGIN,
                "h": (r1 - r0 + 1) * CELL - 2 * MARGIN,
                "cells": best[0],
            }
        )
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                blocked[r][c] = True
    return rects


def main():
    global GRID_COLS, GRID_ROWS, CELL, UI_SAFE
    argv = sys.argv[1:]
    n = 5
    if "--samples" in argv:
        i = argv.index("--samples")
        n = int(argv[i + 1])
        del argv[i : i + 2]
    ui_safe = True
    if "--no-ui-safe" in argv:
        ui_safe = False
        argv.remove("--no-ui-safe")
    dir_prod = None
    if "--dir" in argv:
        i = argv.index("--dir")
        dir_prod = argv[i + 1]
        del argv[i : i + 2]
    video, windows = argv[0], argv[1:]

    P = perfil_mod.carregar(dir_prod or os.path.dirname(os.path.abspath(video)),
                            quieto=True)
    GRID_COLS, GRID_ROWS, CELL = grade_de(P)
    UI_SAFE = perfil_mod.zonas_ui(P) if ui_safe else None
    print(f"perfil {P.get('nome','?')}: {P['video']['largura']}x{P['video']['altura']} → "
          f"grade {GRID_COLS}x{GRID_ROWS} (célula {CELL}px) · "
          f"zonas de UI: {UI_SAFE or 'nenhuma (peça fora de feed)'}", file=sys.stderr)
    session = new_session("u2net_human_seg")
    result = []
    for w in windows:
        start, end = (float(x) for x in w.split("-"))
        with tempfile.TemporaryDirectory() as td:
            paths = sample_frames(video, start, end, n, td)
            occ = occupancy_grid(session, paths)
        if UI_SAFE:
            for r in range(GRID_ROWS):
                for c in range(GRID_COLS):
                    if ui_blocked(r, c):
                        occ[r][c] = True
        print(f"\n== janela {w} (X = pessoa/UI, . = livre)", file=sys.stderr)
        for row in occ:
            print("  " + "".join("X" if c else "." for c in row), file=sys.stderr)
        rects = largest_free_rects(occ)
        result.append({"window": w, "free_rects": rects})
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
