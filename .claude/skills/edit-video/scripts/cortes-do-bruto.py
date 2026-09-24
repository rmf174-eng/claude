#!/usr/bin/env python3
"""Detecta os cortes que JÁ EXISTEM no bruto e avisa onde a EDL cria plano curto.

Uso: cortes-do-bruto.py <dir-da-producao> [--edl edl.json] [--min-frames 8]
     cortes-do-bruto.py <arquivo.mp4>          (só lista os cortes)

POR QUE ISTO EXISTE (2026-07-28, produção creator-2/nao-perdeu-a-peca-06)
A skill inteira assume que o bruto é UM TAKE CONTÍNUO — todo o pipeline (bordas
acústicas, pads, EDL) foi construído em cima disso. Mas o creator pode mandar o
vídeo **já montado**: a creator-2 entregou este com **20 jump cuts** feitos por ela,
um no fim de cada frase.

O defeito que isso produziu, e que o creator-1 viu: ela tinha um corte em **5,200** e
eu pus o meu em **5,310** (o fim acústico da palavra "ela"). Sobraram **3 frames**
de um plano intermediário — 110 ms de imagem que entra e sai. O olho lê como
flash/glitch, e nenhum QC de áudio pega, porque o áudio está perfeito.

Duas regras que ficam:
  • **Antes de montar, detectar os cortes do bruto.** Se existirem, o material
    não é take contínuo e cada corte dele é uma emenda que você não fez.
  • **Corte meu a menos de ~8 frames de um corte dele = flash.** A saída certa
    quase sempre é ALINHAR o meu ao dele (de graça: o corte já está lá, e vira
    troca de plano legítima) ou desistir do meu corte. Reverter o corte da muleta
    "Resumindo" custou 0,57 s e resolveu o defeito.

Bônus: um corte do bruto é o melhor lugar do mundo pra trocar o enquadramento
(`zoom`/`cx`/`cy`), porque a troca cai num corte que já existe.
"""
import argparse
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

# 📐 O raster de medição e o fps de entrega saem do perfil de peça (SPEC-00):
#    W,H            = perfil.raster_de_medicao(P)   — 96x171 em 9:16, 304x171 em 16:9
#    FPS_ENTREGA    = P["video"]["fps"]             — a timeline em que o flash é visto
# O `--min-frames` continua sendo física de percepção (8 frames lêem como flash).


def fps_de(src):
    """fps REAL do bruto — não assumir 30.

    (2026-07-29) O bruto da creator-2 veio a 60fps e o FPS fixo em 30 devolvia todo
    corte no DOBRO do tempo: o último saía em '50,000s' num vídeo de 46,8s.
    Os tempos aqui são comparados contra a EDL, que está no tempo do BRUTO —
    então quem manda é o fps do arquivo medido, não o fps da entrega."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", src],
        capture_output=True, text=True).stdout
    # o csv pode vir com linha extra/vírgula sobrando (streams de dados do iPhone)
    r = r.splitlines()[0].strip().strip(",")
    num, _, den = r.partition("/")
    return float(num) / float(den or 1)


def detectar(src, W, H, sigma=4.0, piso=8.0):
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vf", f"scale={W}:{H}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(p) // (W * H)
    a = np.frombuffer(p, dtype=np.uint8)[: n * W * H].reshape(n, H, W).astype(np.float32)
    d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    thr = max(float(d.mean() + sigma * d.std()), piso)
    brutos = [i + 1 for i in range(len(d)) if d[i] > thr]
    out, prev = [], -9
    for c in brutos:
        if c - prev > 2:
            out.append(c)
        prev = c
    return out, thr, n


def argumentos(argv=None):
    ap = argparse.ArgumentParser(
        description="detecta cortes existentes no bruto e planos curtos na EDL")
    ap.add_argument("alvo", help="arquivo de vídeo ou diretório da produção")
    ap.add_argument("--edl", default="edl.json", metavar="ARQUIVO",
                    help="EDL da produção (default: edl.json)")
    ap.add_argument("--min-frames", type=int, default=8, metavar="N",
                    help="menor plano aceitável junto a um corte do bruto")
    ns = ap.parse_args(argv)
    if not os.path.exists(ns.alvo):
        ap.error("caminho não existe: %s" % ns.alvo)
    if ns.min_frames < 1:
        ap.error("--min-frames precisa ser um inteiro positivo")
    if os.path.isdir(ns.alvo):
        edl = ns.edl if os.path.isabs(ns.edl) else os.path.join(ns.alvo, ns.edl)
        if not os.path.isfile(edl):
            ap.error("EDL não encontrada: %s" % edl)
    elif not os.path.isfile(ns.alvo):
        ap.error("o alvo precisa ser arquivo regular ou diretório: %s" % ns.alvo)
    return ns


def main(argv=None):
    cli = argumentos(argv)
    alvo = cli.alvo
    min_frames = cli.min_frames

    if os.path.isfile(alvo):
        # modo arquivo solto: não há produção, logo não há perfil.json — o FALLBACK
        # dá o raster, e o fps de comparação é o do PRÓPRIO arquivo (que é o certo:
        # aqui só se lista o que existe no bruto).
        P = perfil_mod.carregar(os.path.dirname(os.path.abspath(alvo)), quieto=True)
        W, H = perfil_mod.raster_de_medicao(P)
        fps = fps_de(alvo)
        cortes, thr, n = detectar(alvo, W, H)
        print(f"{len(cortes)} cortes em {n} frames a {fps:g}fps "
              f"(raster {W}x{H}, limiar {thr:.1f})")
        for f in cortes:
            print(f"  frame {f:5d}  {f/fps:8.3f}s")
        return 0

    edl_nome = cli.edl
    P = perfil_mod.carregar(alvo)
    W, H = perfil_mod.raster_de_medicao(P)
    FPS_ENTREGA = float(P["video"]["fps"])
    os.chdir(alvo)
    # cruza cortes do BRUTO com os cortes da EDL (ambos no tempo do arquivo
    # original), então não usa timeline_real — só os segmentos, em v1 ou v2.
    edl = edl_io.segmentos(edl_nome)
    srcs = sorted({s["src"] for s in edl})
    mapa, fps_src = {}, {}
    for s in srcs:
        fps_src[s] = fps_de(s)
        cortes, thr, n = detectar(s, W, H)
        mapa[s] = cortes
        print(f"{s}: {len(cortes)} cortes já existentes no bruto "
              f"({fps_src[s]:g}fps, raster {W}x{H}, limiar {thr:.1f})", file=sys.stderr)
        if cortes:
            print("   " + " ".join(f"{c/fps_src[s]:.2f}" for c in cortes), file=sys.stderr)

    if not any(mapa.values()):
        print("bruto é take contínuo — nada a cruzar", file=sys.stderr)
        return 0

    print(file=sys.stderr)
    alertas = 0
    for i, seg in enumerate(edl):
        cortes = [c / fps_src[seg["src"]] for c in mapa[seg["src"]]]
        dentro = [c for c in cortes if seg["start"] < c < seg["end"]]
        for c in dentro:
            # o "plano curto" é sentido na ENTREGA (30fps), não no fps do bruto
            do_inicio = (c - seg["start"]) * FPS_ENTREGA
            do_fim = (seg["end"] - c) * FPS_ENTREGA
            if do_inicio < min_frames:
                alertas += 1
                print(f"seg{i:02d} [PLANO-CURTO] corte do bruto em {c:.3f} está a "
                      f"{do_inicio:.0f} frames DEPOIS do início do segmento ({seg['start']:.3f}): "
                      f"sobra um plano de {do_inicio:.0f} frames, que lê como flash. "
                      f"Alinhe o seu corte em {c:.3f} ou desista dele.")
            if do_fim < min_frames:
                alertas += 1
                print(f"seg{i:02d} [PLANO-CURTO] corte do bruto em {c:.3f} está a "
                      f"{do_fim:.0f} frames ANTES do fim do segmento ({seg['end']:.3f}): "
                      f"sobra um plano de {do_fim:.0f} frames, que lê como flash. "
                      f"Alinhe o seu corte em {c:.3f} ou desista dele.")
        # o corte da EDL coincidindo com um do bruto é BOM — registra
        for lado, t in (("start", seg["start"]), ("end", seg["end"])):
            perto = [c for c in cortes if abs(c - t) < 0.02]
            if perto:
                print(f"seg{i:02d} ✔ {lado} {t:.3f} coincide com corte do bruto "
                      f"({perto[0]:.3f}) — troca de plano de graça", file=sys.stderr)
    print(f"\n{alertas} alerta(s) de plano curto"
          + ("" if alertas else " — nenhum corte meu perto de corte do bruto"), file=sys.stderr)
    return 1 if alertas else 0


if __name__ == "__main__":
    sys.exit(main())
