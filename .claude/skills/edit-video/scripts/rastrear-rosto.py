#!/usr/bin/env python3
"""rastrear-rosto.py — a linha dos olhos, frame a frame, para a câmera dinâmica.

    rastrear-rosto.py <video> [-o track.json] [--suavizar 0.5] [--fps-amostra N]

Saída: `benchmark.track-rosto/v1` — um ponto normalizado por frame de AMOSTRA,
que o Remotion interpola para manter os olhos num alvo fixo enquanto o punch-in
está aplicado. Um seguimento lento, sem borda preta.

═══════════════════════════════════════════════════════════════════════════
O QUE FOI MODELADO, E O QUE NÃO FOI

O pré-passo de tracking é ideia de uma ferramenta de referência, e o que vale
dela NÃO é o detector — é ANCORAR NOS OLHOS. Enquadrar pelo centro da caixa do
rosto deixa o olhar alto demais no quadro; a linha dos olhos fica a ~42% da
altura da caixa, contada do topo. Esse número é o insight, e ele fica.

O detector é NOSSO e é outro. Lá é `haarcascade_frontalface_default` do OpenCV;
aqui é Apple Vision, por duas razões medidas:

  1. OpenCV é ~90 MB de dependência nova, e pode não estar instalado — num repo
     cuja regra é não depender do que pode sumir, e onde uma receita já morreu
     exatamente assim (SPEC-03 §3.1).
  2. Haar é frontal e de 2001. Rosto de perfil, inclinado ou com metade fora do
     quadro não é detectado, e num talking-head de mão solta isso é metade da
     peça. Vision detecta perfil E devolve LANDMARKS: os olhos medidos, não
     estimados. Os 42% viram o FALLBACK, não a conta principal.

Zero linha portada. O que atravessa é o mecanismo: âncora nos olhos, preencher
os buracos, suavizar com janela em SEGUNDOS.

═══════════════════════════════════════════════════════════════════════════
TRÊS DECISÕES DE DESENHO

1. AMOSTRA, NÃO TODO FRAME. Uma peça de 60 s a 30 fps são 1.800 frames; a 8 fps
   de amostra são 480, e o olho não vê a diferença num movimento cuja janela de
   suavização é de meio segundo. O `fps` de amostra vai no JSON e o consumidor
   interpola — quem decide a resolução do movimento é este arquivo, não o render.

2. A JANELA DE SUAVIZAÇÃO É EM SEGUNDOS, nunca em frames. Em frames, a mesma
   receita fica duas vezes mais brusca a 60 fps do que a 30 — e o que o olho
   percebe é tempo, não contagem.

3. O ARQUIVO DIZ QUANTOS FRAMES TINHAM ROSTO. Um track de 480 pontos com 12
   detecções é um arquivo válido e inútil: o `fill` propaga o último ponto
   conhecido e a saída fica lisa, plausível e errada. `detectados` e
   `cobertura` estão no JSON, e abaixo de `--minimo-cobertura` o script RECUSA
   em vez de entregar um movimento inventado.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

CONTRATO = "benchmark.track-rosto/v1"
AQUI = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(AQUI, ".bin")
BIN = os.path.join(BIN_DIR, "rosto-vision")
FONTE_SWIFT = os.path.join(AQUI, "rosto-vision.swift")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def garantir_binario():
    """Compila sob demanda em scripts/.bin/ e reusa — mesmo padrão do matte.py."""
    os.makedirs(BIN_DIR, exist_ok=True)
    if os.path.exists(BIN) and os.path.getmtime(BIN) >= os.path.getmtime(FONTE_SWIFT):
        return BIN
    if not shutil.which("swiftc"):
        raise SystemExit(
            "rastrear-rosto.py: swiftc não encontrado. O detector é Apple Vision "
            "(macOS + Xcode Command Line Tools).")
    log("  compilando rosto-vision (uma vez)…")
    subprocess.run(["swiftc", "-O", "-o", BIN, FONTE_SWIFT], check=True)
    return BIN


def extrair(video, dir_saida, fps_amostra):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", video,
         "-vf", "fps=%g,scale=640:-2" % fps_amostra,
         os.path.join(dir_saida, "f%06d.png")], check=True)
    return sorted(f for f in os.listdir(dir_saida) if f.endswith(".png"))


def preencher(pontos):
    """Buraco vira o último ponto conhecido; buraco no começo vira o primeiro.

    Sem isto o track tem descontinuidade e o punch-in salta. Com isto ele PARA
    no último lugar conhecido, que é o comportamento certo: a câmera não sabe
    para onde ir, então não vai a lugar nenhum.
    """
    conhecidos = [p for p in pontos if p is not None]
    if not conhecidos:
        return None
    saida, ultimo = [], conhecidos[0]
    for p in pontos:
        if p is not None:
            ultimo = p
        saida.append(ultimo)
    return saida


def suavizar(pontos, janela):
    """Média móvel centrada, janela em FRAMES DE AMOSTRA (derivada de segundos)."""
    n = len(pontos)
    saida = []
    for i in range(n):
        a, b = max(0, i - janela), min(n, i + janela + 1)
        seg = pontos[a:b]
        saida.append([round(sum(s[0] for s in seg) / len(seg), 4),
                      round(sum(s[1] for s in seg) / len(seg), 4)])
    return saida


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("-o", "--saida", default=None)
    ap.add_argument("--suavizar", type=float, default=0.5,
                    help="janela de suavização em SEGUNDOS (default 0,5)")
    ap.add_argument("--fps-amostra", type=float, default=8.0)
    ap.add_argument("--minimo-cobertura", type=float, default=0.35,
                    help="fração mínima de frames com rosto; abaixo disso RECUSA")
    a = ap.parse_args()

    if not os.path.isfile(a.video):
        raise SystemExit("vídeo inexistente: %s" % a.video)
    binario = garantir_binario()

    tmp = tempfile.mkdtemp(prefix="track-rosto-")
    try:
        nomes = extrair(a.video, tmp, a.fps_amostra)
        log("  %d frame(s) de amostra a %g fps" % (len(nomes), a.fps_amostra))
        p = subprocess.run([binario, tmp], capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit("rosto-vision falhou:\n" + (p.stderr or "")[-800:])
        brutos, conf = [], []
        for linha in p.stdout.splitlines():
            partes = linha.split()
            if len(partes) < 5 or partes[1] == "-":
                brutos.append(None)
                continue
            brutos.append((float(partes[1]), float(partes[2])))
            conf.append(float(partes[4]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    detectados = sum(1 for x in brutos if x is not None)
    cobertura = detectados / max(1, len(brutos))
    log("  rosto em %d de %d (%.0f%%)" % (detectados, len(brutos), 100 * cobertura))
    if cobertura < a.minimo_cobertura:
        raise SystemExit(
            "rastrear-rosto.py: cobertura %.0f%% abaixo do mínimo de %.0f%%. "
            "Um track preenchido a partir de tão pouca detecção sai LISO e "
            "PLAUSÍVEL, e erra o tempo todo — é pior que não ter track. Baixe o "
            "--minimo-cobertura conscientemente se quiser assim mesmo."
            % (100 * cobertura, 100 * a.minimo_cobertura))

    preenchidos = preencher(brutos)
    janela = max(1, int(a.fps_amostra * a.suavizar))
    pontos = suavizar(preenchidos, janela)

    saida = a.saida or os.path.join(os.path.dirname(a.video) or ".", "track.json")
    obj = {
        "contrato": CONTRATO,
        "fps": a.fps_amostra,
        "count": len(pontos),
        "detectados": detectados,
        "cobertura": round(cobertura, 4),
        "confianca_media": round(sum(conf) / len(conf), 4) if conf else None,
        "suavizacao_s": a.suavizar,
        "detector": "apple-vision:VNDetectFaceLandmarksRequest",
        "pontos": pontos,
    }
    with open(saida, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    print(saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
