#!/usr/bin/env python3
"""Flicker-scan: mede Δ de luminância frame a frame por região e acusa saltos.
Salto >limiar fora de jump cut = investigar (legenda sumindo seco, alpha
premultiplicado sem unpremultiply, elemento entrando semi-transparente...).
Padrões: dip-e-recover em 1 frame = buraco de opacidade; queda grande única
alinhada a corte da EDL = jump cut (inerente); rampa suave = movimento de cena.
Uso: flicker-scan.py <video> [ini=0] [dur=15] [limiar=2.0] [--dir <producao>]
Regiões: legenda (y 70–88%) e meio (y 35–55%).

📐 O raster de amostragem e o fps saem do perfil de peça (SPEC-00); as REGIÕES são
frações do quadro, não px — em px elas apontam para o lugar errado assim que a
resolução muda. O perfil vem de `--dir`, ou da pasta do próprio vídeo."""
# procedência: em vertical Full HD o raster e o fps caem exatamente nos valores
# históricos deste script (a resolução da peça sobre 4, e o fps da entrega).
import subprocess, sys, os, shutil, glob
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perfil as perfil_mod   # noqa: E402

args = sys.argv[1:]
dir_prod = args[args.index("--dir") + 1] if "--dir" in args else None
if "--dir" in args:
    i = args.index("--dir"); del args[i:i + 2]
v = args[0]
ini = float(args[1]) if len(args) > 1 else 0.0
dur = float(args[2]) if len(args) > 2 else 15.0
lim = float(args[3]) if len(args) > 3 else 2.0

P = perfil_mod.carregar(dir_prod or os.path.dirname(os.path.abspath(v)), quieto=True)
FPS = P["video"]["fps"]
EW, EH = perfil_mod.escala_amostragem(P)

tmp = f"/tmp/flickscan-{os.getpid()}"; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(ini), '-t', str(dur),
                '-i', v, '-vf', f'fps={FPS},scale={EW}:{EH}', f'{tmp}/f%04d.png'], check=True)


def lum(im, box):
    px = list(im.crop(box).getdata()); return sum(px) / len(px)


# frações do quadro: (x0, y0, x1, y1). Os números vêm dos px históricos sobre o
# raster 270x480 — 30/270, 336/480, 240/270, 422/480 e 30/270, 168/480, 240/270, 264/480.
REGS_PCT = {'legenda': (0.1111, 0.7000, 0.8889, 0.8792),
            'meio':    (0.1111, 0.3500, 0.8889, 0.5500)}
regs = {r: (int(a * EW), int(b * EH), int(c * EW), int(d * EH))
        for r, (a, b, c, d) in REGS_PCT.items()}
prev = {}
files = sorted(glob.glob(f'{tmp}/f*.png'))
print(f"varrendo {len(files)} frames a {FPS}fps em {EW}x{EH} · regiões {regs} · limiar {lim}",
      file=sys.stderr)
saltos = 0
for n, f in enumerate(files):
    im = Image.open(f).convert('L')
    for r, box in regs.items():
        m = lum(im, box)
        if r in prev and abs(m - prev[r]) > lim:
            saltos += 1
            print(f"t={ini + (n+1)/FPS:.2f} [{r}] Δ={m - prev[r]:+.1f}")
        prev[r] = m
print(f"{saltos} salto(s) acima de {lim} em {len(files)} frames", file=sys.stderr)
shutil.rmtree(tmp)
