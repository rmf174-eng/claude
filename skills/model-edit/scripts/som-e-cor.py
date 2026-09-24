#!/usr/bin/env python3
"""som-e-cor — mede o tratamento de ÁUDIO e de COR de uma edição.

ÁUDIO. A métrica que importa é **piso vs fala**, não a LRA.
⚠️ Armadilha medida na primeira modelagem: comparar a LRA do bruto (41s, 58% de
pausa → LRA 24) com a do editado (23s sem pausa → LRA 5) sugere "compressão
pesadíssima". É falso — cortar pausa já colapsa a LRA sozinho. Medindo a MESMA
janela, a montagem crua deu LRA 4,4 e a referência 4,3. O que denuncia compressão
de verdade é o PISO subir com a fala parada no mesmo nível (a LRA é gated e não vê
o que está baixo).

COR. Compara regiões equivalentes entre dois vídeos. Só vale se os dois mostram a
MESMA cena (par bruto↔editado, ou dois renders do mesmo material).

Uso:
    som-e-cor.py audio <video-a> <video-b> [--t SEGUNDOS]   # janela igual nos dois!
    som-e-cor.py cor   <frame-a.jpg> <frame-b.jpg> [regiao=y0:y1:x0:x1 ...]
    som-e-cor.py paleta <frame.jpg> [--n 5]                 # cor de destaque da cena
"""
import subprocess, sys
import numpy as np


def envelope(src, t=None):
    cmd = ["ffmpeg", "-nostdin", "-v", "error"] + (["-t", str(t)] if t else []) + \
          ["-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.int16).astype(float) / 32768
    if not len(a):
        sys.exit(f"sem áudio em {src}")
    w = int(16000 * 0.02)
    rms = np.sqrt(np.convolve(a ** 2, np.ones(w) / w, mode="same"))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def lufs(src, t=None):
    cmd = ["ffmpeg", "-nostdin"] + (["-t", str(t)] if t else []) + \
          ["-i", src, "-af", "ebur128", "-f", "null", "-"]
    o = subprocess.run(cmd, capture_output=True, text=True).stderr
    bloco = o.split("Summary:")[-1] if "Summary:" in o else ""
    # ⚠️ o prefixo precisa do ":" — "I" sozinho casa antes com "Integrated loudness:"
    # e devolve string vazia (bug pego no smoke test da skill).
    g = lambda k: next((l.split(":", 1)[1].strip() for l in bloco.splitlines()
                        if l.strip().startswith(k + ":")), "?")
    return g("I"), g("LRA")


def cmd_audio(argv):
    t = float(argv[argv.index("--t") + 1]) if "--t" in argv else None
    if t is None:
        print("⚠️ sem --t: os vídeos têm durações diferentes e a LRA NÃO é comparável.\n"
              "   Use --t com a duração do mais curto pra uma comparação honesta.\n")
    print(f"{'arquivo':<34} {'LUFS':>10} {'LRA':>10} {'piso(p5)':>9} {'fala(p80)':>10} {'dinâmica':>9}")
    for p in [a for a in argv[:2]]:
        d = envelope(p, t)
        I, L = lufs(p, t)
        p5, p80 = np.percentile(d, 5), np.percentile(d, 80)
        print(f"{p[-34:]:<34} {I:>10} {L:>10} {p5:8.1f}dB {p80:9.1f}dB {p80-p5:8.1f}dB")
    print("\nleitura: fala no MESMO nível + piso muito mais alto = compressão.")
    print("         dinâmica ~20dB = 'voz de podcast' · ~38dB = voz crua sem tratamento.")


def cmd_cor(argv):
    from PIL import Image
    A = np.asarray(Image.open(argv[0]).convert("RGB"), float)
    B = np.asarray(Image.open(argv[1]).convert("RGB"), float)
    if A.shape != B.shape:
        B = np.asarray(Image.open(argv[1]).convert("RGB").resize((A.shape[1], A.shape[0])), float)
    regs = [r for r in argv[2:] if ":" in r] or [f"0:{A.shape[0]}:0:{A.shape[1]}"]
    sat = lambda x: np.where(x.max(axis=2) > 0, (x.max(axis=2) - x.min(axis=2)) / np.maximum(x.max(axis=2), 1), 0)
    print(f"{'região':<22} {'A lum':>7} {'A sat':>7} {'B lum':>7} {'B sat':>7} {'Δlum':>7} {'Δsat':>7}")
    for r in regs:
        y0, y1, x0, x1 = map(int, r.split(":"))
        a, b = A[y0:y1, x0:x1], B[y0:y1, x0:x1]
        print(f"{r:<22} {a.mean():7.1f} {sat(a).mean():7.3f} {b.mean():7.1f} {sat(b).mean():7.3f} "
              f"{(b.mean()-a.mean())/max(a.mean(),1)*100:+6.1f}% {(sat(b).mean()-sat(a).mean())/max(sat(a).mean(),1e-6)*100:+6.1f}%")
    print("\npro grade: eq=saturation=<1+Δsat> e gamma≈<1+Δlum> (validar medindo de novo).")


def cmd_paleta(argv):
    """Cor de destaque harmonizada com a cena: mesma matiz do fundo, mais clara e mais saturada.
    Foi o que a referência fez (parede #6e4227 → destaque #c0603c)."""
    from PIL import Image
    import colorsys
    im = Image.open(argv[0]).convert("RGB").resize((160, 284))
    a = np.asarray(im, float).reshape(-1, 3) / 255
    q = (a * 8).astype(int)
    chaves, cont = np.unique(q, axis=0, return_counts=True)
    ordem = np.argsort(-cont)[: int(argv[argv.index("--n") + 1]) if "--n" in argv else 5]
    print("cores dominantes da cena → sugestão de destaque (mesma matiz, +luz +saturação):")
    for i in ordem:
        r, g, b = (chaves[i] + 0.5) / 8
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        R, G, B = colorsys.hls_to_rgb(h, min(0.62, l * 1.7), min(1.0, s * 1.1))
        print(f"  fundo #{int(r*255):02x}{int(g*255):02x}{int(b*255):02x} ({cont[i]/len(a)*100:4.1f}%)"
              f"  →  destaque #{int(R*255):02x}{int(G*255):02x}{int(B*255):02x}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    {"audio": cmd_audio, "cor": cmd_cor, "paleta": cmd_paleta}[sys.argv[1]](sys.argv[2:])
