#!/usr/bin/env python3
"""cortes — lista os CORTES de um vídeo editado, por FAIXA horizontal.

Diferença frame a frame em faixas horizontais separadas. A separação por faixa é
o que importa: num vídeo com b-roll em split-screen, um corte no talking-head
mexe só nas faixas de baixo e um corte no b-roll só nas de cima. Olhando o frame
inteiro, os dois viram "um pico" e a leitura da montagem se perde.

Uso:
    cortes.py <video> [--fps 30] [--faixas 4] [--sigma 8]

Saída (stdout): tabela de candidatos a corte com o perfil por faixa.
Leitura:
  • pico ALTO em TODAS as faixas          → corte duro (troca de plano)
  • pico alto só nas faixas de cima/baixo → troca de camada (b-roll entrando/saindo)
  • pico MÉDIO só onde está a pessoa      → jump cut no mesmo enquadramento
  • rampa espalhada por vários frames     → transição animada (dissolve/whip), não corte
"""
import argparse, subprocess, sys
import numpy as np

W, H = 180, 320


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--faixas", type=int, default=4)
    ap.add_argument("--sigma", type=float, default=8.0,
                    help="quantos MAD acima da mediana contam como candidato")
    a = ap.parse_args()

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", a.video, "-vf",
         f"fps={a.fps},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (W * H)
    if n < 2:
        sys.exit("vídeo curto demais ou ilegível")
    F = np.frombuffer(raw, dtype=np.uint8)[: n * W * H].reshape(n, H, W).astype(np.int16)
    print(f"{n} frames @ {a.fps}fps ({n/a.fps:.2f}s)", file=sys.stderr)

    bandas = np.array_split(np.arange(H), a.faixas)
    d = np.zeros((n - 1, a.faixas))
    for i, idx in enumerate(bandas):
        d[:, i] = np.abs(np.diff(F[:, idx, :], axis=0)).mean(axis=(1, 2))
    dtot = np.abs(np.diff(F, axis=0)).mean(axis=(1, 2))

    med = float(np.median(dtot))
    mad = float(np.median(np.abs(dtot - med))) + 1e-6
    thr = med + a.sigma * mad
    print(f"limiar {thr:.2f} (mediana {med:.2f} · MAD {mad:.2f})")
    hdr = "  t(s)  frame | total | " + " | ".join(
        f"f{i}(y{b[0]*100//H:>2}-{b[-1]*100//H:>2}%)" for i, b in enumerate(bandas))
    print(hdr); print("-" * len(hdr))
    # ⚠️ Um CORTE é um pico ISOLADO. Movimento rápido (mão entrando no quadro, whip)
    # levanta o diff por vários frames seguidos e passava o limiar como "corte duro" —
    # no smoke test isto reportou 9 cortes falsos nos 0,3s iniciais. Exigir que o frame
    # seja pelo menos 2× a mediana da vizinhança separa corte de movimento.
    achados = 0
    for k in np.where(dtot > thr)[0]:
        viz = np.concatenate([dtot[max(0, k - 6):k], dtot[k + 1:k + 7]])
        if len(viz) and dtot[k] < 2.0 * np.median(viz):
            continue
        perfil = d[k]
        tipo = ("corte duro" if perfil.min() > thr * 0.4 else
                "troca de camada" if perfil.max() > thr and perfil.min() < thr * 0.15 else
                "corte parcial/jump cut")
        print(f"{(k+1)/a.fps:6.3f} {k+1:6d} | {dtot[k]:5.1f} | "
              + " | ".join(f"{perfil[i]:11.1f}" for i in range(a.faixas))
              + f"  ← {tipo}")
        achados += 1
    if not achados:
        print("(nenhum pico isolado — vídeo de plano único, ou baixe --sigma)")


if __name__ == "__main__":
    main()
