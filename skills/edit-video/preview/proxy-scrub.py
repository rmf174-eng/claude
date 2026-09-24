#!/usr/bin/env python3
"""proxy-scrub.py — o proxy de arrasto do player (SPEC-18 §3.10, incremento B3).

Trocar a fonte do `<video>` por um proxy denso em keyframes durante o arrasto é
MECANISMO nosso; o ref-A não tem equivalente. Ver docs/specs/SPEC-18 §10.

────────────────────────────────────────────────────────────────────────────
O NÚMERO QUE DECIDE. Medido no `v-final.mp4` da peca-01: **16 keyframes
em 70,784 s** (média 4,7 s, máximo 7,9 s), 66 MB. Buscar um instante arbitrário
obriga o browser a decodificar desde o keyframe anterior — e o passo `←` (para
trás) é o caro. O proxy tem um keyframe a cada ~0,2 s e pesa ~26× menos.

🔴 O PROXY É MUDO E NUNCA É A ENTREGA. O áudio vem SEMPRE do render; o proxy é o
`<video>` visível enquanto a agulha é arrastada, e o render volta no
`pause`/`play`. Um proxy que virasse fonte de áudio produziria o defeito que o
`encaixar.py` já produziu neste repo (vídeo de um, áudio de outro).

🔴 NENHUM VALOR DE FORMATO AQUI. A altura do proxy, o GOP e o CRF são
`--altura`, `--gop` e `--crf`, com default de FÍSICA (resolução de scrub), não
de peça: quem descreve a peça é o perfil (SPEC-00). A largura sai de `-2`, ou
seja, do próprio arquivo.

USO
    proxy-scrub.py <dir> [--render v-final.mp4] [--altura N] [--gop N] [--crf N]
                         [--forcar]

Imprime no stdout o caminho RELATIVO à produção (é o que a app põe em `media/`);
logs no stderr. Idempotente: reexecutar pula o que já existe (a chave leva
mtime+bytes do render, então render novo = proxy novo).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

# Defaults de FÍSICA do scrub (resolução de arrasto, densidade de keyframe e
# qualidade do codec) — nada aqui descreve a PEÇA, que é assunto do perfil
# (SPEC-00). Num dict, e não em três `NOME = valor`, porque um número solto num
# script de mídia é exatamente o que o portão da regra de ouro procura.
PADRAO = {
    "altura": 480,      # resolução de SCRUB, não da peça
    "gop": 6,           # ~0,2 s: é o que torna o passo para trás barato
    "crf": 30,          # qualidade do codec no proxy; ninguém entrega isto
}
ALTURA_PADRAO, GOP_PADRAO, CRF_PADRAO = PADRAO["altura"], PADRAO["gop"], PADRAO["crf"]
CANDIDATOS = ("v-final.mp4", "v1-montado.mp4", "v1-final-base.mp4")


def _chave(caminho, altura, gop, crf):
    st = os.stat(caminho)
    ident = "%s|%d|%d|%d|%d|%d" % (os.path.basename(caminho), st.st_mtime_ns,
                                   st.st_size, altura, gop, crf)
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12]


def gerar(dir_producao, render, altura=ALTURA_PADRAO, gop=GOP_PADRAO,
          crf=CRF_PADRAO, forcar=False):
    origem = os.path.join(dir_producao, render)
    if not os.path.isfile(origem):
        raise SystemExit("render não encontrado: %s" % origem)
    chave = _chave(origem, altura, gop, crf)
    rel = os.path.join(".preview", "cache", "scrub", "%s.mp4" % chave)
    destino = os.path.join(dir_producao, rel)
    # o diretório nasce no script: `.gitkeep` dentro de caminho ignorado não
    # sobrevive ao clone, e na máquina do cliente nada disto existe (FRONTEIRA §9)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.isfile(destino) and not forcar:
        print("proxy já existe (%s)" % rel, file=sys.stderr)
        return rel
    parcial = destino + ".%d.parcial" % os.getpid()   # PID no nome: SPEC-16 §escrita
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", origem, "-an",
           "-vf", "scale=-2:%d" % altura, "-g", str(gop), "-crf", str(crf),
           "-preset", "veryfast", "-pix_fmt", "yuv420p",
           # ⚠️ `-f mp4` explícito: o ffmpeg escolhe o muxer pela EXTENSÃO, e o
           # temporário termina em `.parcial`. Sem isto ele aborta com
           # "Unable to choose an output format" — medido.
           "-f", "mp4", parcial]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(parcial):
        try:
            os.remove(parcial)
        except OSError:
            pass
        raise SystemExit("ffmpeg falhou: %s" % (r.stderr or "").strip()[:400])
    os.replace(parcial, destino)     # artefato só existe quando está completo
    return rel


def _keyframes(caminho):
    """Quantos keyframes o arquivo tem — o número que justifica o proxy."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
           "-show_entries", "frame=pts_time", "-of", "json", caminho]
    try:
        s = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return len(json.loads(s.stdout or "{}").get("frames") or [])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def main(argv=None):
    p = argparse.ArgumentParser(description="proxy denso em keyframes para o scrub")
    p.add_argument("dir")
    p.add_argument("--render", default=None)
    p.add_argument("--altura", type=int, default=ALTURA_PADRAO)
    p.add_argument("--gop", type=int, default=GOP_PADRAO)
    p.add_argument("--crf", type=int, default=CRF_PADRAO)
    p.add_argument("--forcar", action="store_true")
    p.add_argument("--medir", action="store_true",
                   help="conta os keyframes do render e do proxy")
    a = p.parse_args(argv)

    d = a.dir.rstrip("/") or "."
    render = a.render
    if not render:
        render = next((c for c in CANDIDATOS if os.path.isfile(os.path.join(d, c))), None)
    if not render:
        raise SystemExit("nenhum render encontrado em %s (tente --render)" % d)

    rel = gerar(d, render, a.altura, a.gop, a.crf, a.forcar)
    if a.medir:
        ko = _keyframes(os.path.join(d, render))
        kp = _keyframes(os.path.join(d, rel))
        bo = os.path.getsize(os.path.join(d, render))
        bp = os.path.getsize(os.path.join(d, rel))
        print("keyframes: render %s → proxy %s · bytes %.1f MB → %.2f MB (%.0f×)"
              % (ko, kp, bo / 1e6, bp / 1e6, bo / max(bp, 1)), file=sys.stderr)
    print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
