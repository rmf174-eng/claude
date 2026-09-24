#!/usr/bin/env python3
"""matte.py — recorte de pessoa: vídeo + janela -> canal alpha.

    matte.py <video> --ini S --fim S [opções]

      --ini S              início da janela em segundos (obrigatório)
      --fim S              fim da janela em segundos (obrigatório)
      --saida DIR          diretório de saída            [dir do vídeo]
      --formato F          alpha | rgba | webm           [alpha]
      --qualidade Q        accurate | balanced           [accurate]
      --suavizacao N       média móvel do alpha, frames  [3]  (0 desliga)
      --engine E           vision                        [vision]
      --forcar             refaz mesmo com artefato válido

    stdout: caminho do artefato final
    stderr: progresso

O que este script NÃO faz, de propósito (SPEC-03 §4.1):

  * não aceita NENHUM valor de formato por argumento. Largura, altura e fps vêm
    da fonte, sempre. Um `--fps` aqui seria o mesmo defeito de `montar.sh:118`,
    que carrega escala e fps cravados e é a razão de existir a SPEC-00.
  * não conhece caminho de creator. Recebe um arquivo e uma janela. É a condição
    pra esta ilha virar produto.
  * não depende de pacote de terceiro: stdlib + ffmpeg + o binário Swift que ele
    mesmo compila sob demanda. A receita anterior (rembg + onnxruntime + 176 MB
    de modelo) morreu justamente porque a dependência evaporou da máquina.

Artefatos, por --formato:

  alpha  matte-alpha.mp4   x264 -crf 0, pix_fmt gray   <- padrão. Só o alpha.
  rgba   matte-rgba.mov    ProRes 4444, yuva444p10le
  webm   matte.webm        VP9 yuva420p (pilha Remotion antiga)

O padrão é só o alpha porque o recorte quase sempre é composto SOBRE a mesma
base de onde saiu: aí o RGB do artefato é redundante e só adiciona perda de
geração. Na composição, `alphamerge` entre a base e o matte devolve os pixels da
pessoa bit a bit iguais aos da base — costura impossível por construção.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction

AQUI = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(AQUI, ".bin")
BIN = os.path.join(BIN_DIR, "matte-vision")
FONTE_SWIFT = os.path.join(AQUI, "matte-vision.swift")

SAIDAS = {
    "alpha": "matte-alpha.mp4",
    "rgba": "matte-rgba.mov",
    "webm": "matte.webm",
}
ENCODE = {
    "alpha": ["-c:v", "libx264", "-crf", "0", "-pix_fmt", "gray"],
    "rgba": ["-c:v", "prores_ks", "-profile:v", "4444",
             "-pix_fmt", "yuva444p10le", "-qscale:v", "6"],
    "webm": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
             "-auto-alt-ref", "0", "-b:v", "0", "-crf", "20"],
}


def log(msg):
    print(msg, file=sys.stderr)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ---------------------------------------------------------------- sonda a fonte

def ffprobe(campos, arquivo, stream="v:0"):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=" + ",".join(campos),
         "-of", "default=nw=1:nk=0", arquivo],
        capture_output=True, text=True, check=True).stdout
    d = {}
    for linha in out.splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            d[k] = v
    return d


def sondar(video):
    """largura, altura, fps racional, rotação, total de frames.

    O cuidado de montar.sh:106-111: o ffprobe reporta as dimensões do STREAM
    (pré-rotação), mas o ffmpeg AUTOROTA no decode. Num bruto de celular vertical
    o stream é deitado com rotation=-90 e todo cálculo feito sobre ele sai
    trocado. Aqui a consequência seria uma máscara com o eixo errado.
    """
    d = ffprobe(["width", "height", "r_frame_rate", "nb_frames", "duration"], video)
    larg, alt = int(d["width"]), int(d["height"])
    rot = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream_side_data=rotation",
         "-of", "default=nk=1:nw=1", video],
        capture_output=True, text=True).stdout.strip().splitlines()
    rot = rot[0] if rot else "0"
    try:
        rot_i = int(float(rot))
    except ValueError:
        rot_i = 0
    if rot_i % 180 != 0:
        larg, alt = alt, larg
        log(f"  (rotation={rot_i} -> dimensões trocadas: {larg}x{alt})")
    fps = Fraction(d["r_frame_rate"])
    if fps <= 0:
        raise SystemExit("matte.py: fonte sem taxa de quadros utilizável")
    total = None
    nbf = d.get("nb_frames", "")
    if nbf.isdigit():
        total = int(nbf)
    elif d.get("duration"):
        try:
            total = int(Fraction(d["duration"]) * fps)
        except (ValueError, ZeroDivisionError):
            total = None
    return larg, alt, fps, rot_i, total


def png_dim(caminho):
    """Largura/altura direto do IHDR. É a verdade sobre o que o ffmpeg entregou,
    já autorrotacionado — vale mais que o probe do container."""
    with open(caminho, "rb") as f:
        cab = f.read(24)
    if cab[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"matte.py: {caminho} não é PNG")
    return int.from_bytes(cab[16:20], "big"), int.from_bytes(cab[20:24], "big")


def sha1_8(caminho):
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()[:8]


# ------------------------------------------------------------------- o binário

def garantir_binario():
    """Compila sob demanda em scripts/.bin/ e reusa. ~12 s uma vez."""
    os.makedirs(BIN_DIR, exist_ok=True)
    if os.path.exists(BIN) and os.path.getmtime(BIN) >= os.path.getmtime(FONTE_SWIFT):
        return BIN
    if not shutil.which("swiftc"):
        raise SystemExit(
            "matte.py: swiftc não encontrado. O engine 'vision' é macOS "
            "(Xcode Command Line Tools). Ver SPEC-03 §9.9.")
    log("  compilando matte-vision (uma vez)…")
    run(["swiftc", "-O", "-o", BIN, FONTE_SWIFT])
    return BIN


# ------------------------------------------------------------ medição do alpha

# Mesma definição de cobertura do qc-alpha.py: opaco >= 98% da escala,
# transparente <= 2%. Sem esse corte a medição responde pelo CODEC e não pela
# máscara — o ProRes 4444 devolve o opaco em 254 e infla a "borda suave"
# (medido 2026-08-08: máscara dura lida como 21,2% de borda).
TOL = 5


def medir_alpha(artefato, formato, larg, alt, amostras=6):
    """opaco/transparente/borda do artefato recém-gravado.

    Conta em C (`bytes.count`), não em laço Python: são larg*alt bytes por frame.
    """
    dec = []
    vf = []
    if formato == "webm":
        dec = ["-c:v", "libvpx-vp9"]
        vf = ["alphaextract"]
    elif formato == "rgba":
        vf = ["alphaextract"]
    cmd = ["ffmpeg", "-v", "error"] + dec + ["-i", artefato]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-pix_fmt", "gray", "-frames:v", str(amostras), "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = larg * alt
    if len(raw) < n:
        return None
    raw = raw[: (len(raw) // n) * n]
    tot = len(raw)
    op = sum(raw.count(v) for v in range(255 - TOL, 256))
    tr = sum(raw.count(v) for v in range(0, TOL + 1))
    return {
        "opaco_pct": round(100.0 * op / tot, 2),
        "transparente_pct": round(100.0 * tr / tot, 2),
        "borda_pct": round(100.0 * (tot - op - tr) / tot, 2),
    }


# ------------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser(add_help=True, description="recorte de pessoa -> alpha")
    ap.add_argument("video")
    ap.add_argument("--ini", type=float, required=True)
    ap.add_argument("--fim", type=float, required=True)
    ap.add_argument("--saida")
    ap.add_argument("--formato", choices=list(SAIDAS), default="alpha")
    ap.add_argument("--qualidade", choices=["accurate", "balanced"], default="accurate")
    ap.add_argument("--suavizacao", type=int, default=3)
    ap.add_argument("--engine", choices=["vision"], default="vision")
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args()

    video = os.path.abspath(a.video)
    if not os.path.exists(video):
        raise SystemExit(f"matte.py: não existe: {video}")
    if a.fim <= a.ini:
        raise SystemExit("matte.py: --fim tem que ser maior que --ini")
    if a.suavizacao < 0:
        raise SystemExit("matte.py: --suavizacao não pode ser negativa")

    saida_dir = os.path.abspath(a.saida) if a.saida else os.path.dirname(video)
    os.makedirs(saida_dir, exist_ok=True)
    artefato = os.path.join(saida_dir, SAIDAS[a.formato])
    sidecar = os.path.join(saida_dir, "matte.json")

    larg, alt, fps, rot, total = sondar(video)

    # A janela vira FRAMES aqui, e daqui pra frente ninguém mais fala em segundo.
    # O repo já pagou 0,28 s de deriva por confiar em valor nominal
    # (docs/EDICAO-CAPACIDADES.md:18-24).
    ini_frame = int(round(a.ini * fps))
    n_frames = int(round((a.fim - a.ini) * fps))
    if n_frames < 1:
        raise SystemExit("matte.py: a janela não cobre nem um frame")
    if ini_frame < 0:
        raise SystemExit("matte.py: --ini negativo")

    fonte_hash = sha1_8(video)

    # idempotência: mesmo artefato, mesma fonte, mesma janela -> não refaz.
    if not a.forcar and os.path.exists(artefato) and os.path.exists(sidecar):
        try:
            with open(sidecar) as f:
                velho = json.load(f)
            j = velho.get("janela", {})
            if (velho.get("fonte_sha1_8") == fonte_hash
                    and velho.get("saida") == os.path.basename(artefato)
                    and j.get("ini_frame") == ini_frame
                    and j.get("n_frames") == n_frames):
                log("  artefato válido já existe (use --forcar pra refazer)")
                print(artefato)
                return 0
        except (json.JSONDecodeError, OSError):
            pass

    binario = garantir_binario()

    # pad da média móvel: pra suavizar CENTRADO é preciso pad de cada lado.
    # tmix do ffmpeg é causal (média dos N últimos), o que atrasaria a máscara em
    # (N-1)/2 frames em relação ao vídeo — deriva, exatamente o que não se quer
    # num matte que vai casar pixel a pixel com a base.
    suav = a.suavizacao if a.suavizacao > 1 else 0
    pad = suav // 2 if suav else 0

    ini_ext = max(0, ini_frame - pad)
    fim_ext = ini_frame + n_frames + pad
    if total:
        fim_ext = min(fim_ext, total)
    n_ext = max(fim_ext - ini_ext, n_frames)
    apl = ini_frame - ini_ext            # pad realmente disponível à esquerda

    tmp = tempfile.mkdtemp(prefix="matte-")
    d_src, d_msk, d_seq = (os.path.join(tmp, x) for x in ("src", "msk", "seq"))
    for d in (d_src, d_msk, d_seq):
        os.makedirs(d)

    try:
        # 1) extrai os frames da janela (+pad) em PNG.
        #    -ss um quarto de frame antes do alvo: o ffmpeg entrega o primeiro
        #    frame com pts >= t, e um quarto de frame é folga suficiente pra que
        #    arredondamento binário não devolva o frame anterior nem o seguinte.
        t0 = float(Fraction(ini_ext * 4 - 1, 4) / fps) if ini_ext else 0.0
        t0 = max(0.0, t0)
        log(f"  janela: frames {ini_frame}..{ini_frame + n_frames - 1} "
            f"({n_frames} frames @ {fps} fps), extraindo {n_ext} (+pad {apl}/{n_ext - apl - n_frames})")
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t0:.6f}", "-i", video,
             "-frames:v", str(n_ext), "-fps_mode", "passthrough",
             "-start_number", "0", os.path.join(d_src, "f%06d.png")])
        extraidos = sorted(os.listdir(d_src))
        if len(extraidos) < apl + n_frames:
            raise SystemExit(
                f"matte.py: a fonte só entregou {len(extraidos)} frames a partir de "
                f"{ini_ext}; a janela pede {apl + n_frames}")
        # a verdade sobre o formato vem do PNG, já autorrotacionado
        plarg, palt = png_dim(os.path.join(d_src, extraidos[0]))
        if (plarg, palt) != (larg, alt):
            log(f"  (probe dizia {larg}x{alt}, o frame veio {plarg}x{palt} — vale o frame)")
            larg, alt = plarg, palt

        # 2) Vision em lote
        t_ini = time.time()
        p = subprocess.run([binario, d_src, d_msk, a.qualidade],
                           capture_output=True, text=True)
        if p.returncode != 0:
            sys.stderr.write(p.stderr)
            raise SystemExit("matte.py: matte-vision falhou")
        sys.stderr.write(p.stderr)
        mascaras = sorted(os.listdir(d_msk))
        if len(mascaras) != len(extraidos):
            raise SystemExit(
                f"matte.py: {len(extraidos)} frames entraram e {len(mascaras)} máscaras "
                "saíram — o lote não fechou")
        ms_frame = round(1000.0 * (time.time() - t_ini) / len(mascaras), 1)
        log(f"  Vision {a.qualidade}: {ms_frame} ms/frame")

        # 3) sequência de máscaras pra suavização centrada:
        #    seq[j] = msk[clamp(j - pad + apl)], j em [0, n_frames + 2*pad)
        #    tmix causal de N=2*pad+1 em seq dá, no índice t + 2*pad, exatamente a
        #    média centrada no frame-alvo t.
        n_seq = n_frames + 2 * pad
        for j in range(n_seq):
            k = min(max(j - pad + apl, 0), len(mascaras) - 1)
            os.link(os.path.join(d_msk, mascaras[k]),
                    os.path.join(d_seq, "f%06d.png" % j))

        # 4) encode
        vf_m = []
        if suav:
            vf_m.append("tmix=frames=%d" % suav)
            vf_m.append("trim=start_frame=%d:end_frame=%d" % (2 * pad, 2 * pad + n_frames))
            vf_m.append("setpts=PTS-STARTPTS")
        taxa = f"{fps.numerator}/{fps.denominator}"

        if a.formato == "alpha":
            cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
                   "-framerate", taxa, "-start_number", "0",
                   "-i", os.path.join(d_seq, "f%06d.png")]
            if vf_m:
                cmd += ["-vf", ",".join(vf_m)]
            cmd += ["-frames:v", str(n_frames)] + ENCODE[a.formato] + [artefato]
        else:
            filtro = ("[1:v]format=gray" + ("," + ",".join(vf_m) if vf_m else "")
                      + "[al];[0:v]format=rgba[rg];[rg][al]alphamerge[v]")
            cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
                   "-framerate", taxa, "-start_number", str(apl),
                   "-i", os.path.join(d_src, "f%06d.png"),
                   "-framerate", taxa, "-start_number", "0",
                   "-i", os.path.join(d_seq, "f%06d.png"),
                   "-filter_complex", filtro, "-map", "[v]",
                   "-frames:v", str(n_frames)] + ENCODE[a.formato] + [artefato]
        run(cmd)

        stat = medir_alpha(artefato, a.formato, larg, alt) or {}
        meta = {
            "schema": "benchmark.matte/v1",
            "fonte": os.path.basename(video),
            "fonte_sha1_8": fonte_hash,
            "janela": {"ini_s": a.ini, "fim_s": a.fim,
                       "ini_frame": ini_frame, "n_frames": n_frames},
            "formato": {"largura": larg, "altura": alt, "fps": taxa},
            "engine": {"nome": a.engine, "qualidade": a.qualidade,
                       "so": platform.mac_ver()[0] or platform.system()},
            "suavizacao_frames": suav,
            "saida": os.path.basename(artefato),
            "alpha": stat,
            "ms_por_frame": ms_frame,
        }
        with open(sidecar, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            f.write("\n")
        log(f"  alpha: opaco {stat.get('opaco_pct')}% · transparente "
            f"{stat.get('transparente_pct')}% · borda {stat.get('borda_pct')}%")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(artefato)
    return 0


if __name__ == "__main__":
    sys.exit(main())
