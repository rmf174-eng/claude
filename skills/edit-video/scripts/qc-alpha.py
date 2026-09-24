#!/usr/bin/env python3
"""qc-alpha.py — prova que um arquivo TEM alpha, e que o alpha vale alguma coisa.

    qc-alpha.py <arquivo> [--frames N] [--json]
    exit 0 = alpha íntegro · exit 1 = reprovado

Aceita `.mov`, `.webm` e o `.mp4` cinza do `matte.py`, e responde sempre por
VARREDURA DO CANAL — nunca por `ffprobe` sozinho.

───────────────────────────────────────────────────────────────────────────────
POR QUE ISTO EXISTE (SPEC-03 §1.2, medido em 2026-08-08)

O guard de alpha que existia antes deste script era, na íntegra:

    PIX=$(ffprobe … stream=pix_fmt …); case "$PIX" in yuva*) … esac

Ele está CERTO pro `.mov` do Remotion e é ESTRUTURALMENTE CEGO pro WebM. O alpha
do WebM VP9 não mora no plano de pixel: mora em `BlockAdditional` do Matroska,
sinalizado por `alpha_mode=1`. O decoder nativo do ffmpeg ignora esse anexo, o
decoder do libvpx lê. Medido no MESMO arquivo:

    decoder default (vp9)      pix_fmt=yuv420p   alphaextract: planes not available
    -c:v libvpx-vp9            pix_fmt=yuva420p  alphaextract: plano completo

E `ffprobe` NÃO ACEITA escolher decoder:

    $ ffprobe -c:v libvpx-vp9 … → Failed to set value 'libvpx-vp9' for option 'c:v'

Logo, nenhum guard escrito com `ffprobe … stream=pix_fmt | grep yuva` consegue
ver alpha de WebM. Custou três leituras independentes concluírem que um arquivo
CORRETO estava quebrado (analista, verificação adversarial e a própria SPEC-03).
Guard de alpha = `alphaextract` com o decoder certo, e só.
───────────────────────────────────────────────────────────────────────────────

O que reprova:

  * o plano não vem com largura*altura bytes por frame
  * opaco == 100% ou transparente == 100%  (recorte degenerado — foi isso, ou
    o alpha não existe de verdade, ou não sobrou pessoa nenhuma)
  * borda suave (0 < a < 255) < 0,2%  — máscara binária, que denuncia colagem

E reporta, sem reprovar, se o RGB está premultiplicado: premultiplicado tem
RGB <= alpha por construção; straight pode ter RGB > alpha. As camadas do
Remotion voltam premultiplicadas (é a causa do "vídeo piscando" da peca-04) e
exigem `unpremultiply` na composição; a camada da pessoa é STRAIGHT e aplicar
`unpremultiply` nela estoura a borda do cabelo.
"""

import argparse
import json
import os
import subprocess
import sys

BORDA_MIN_PCT = 0.2          # abaixo disto é máscara binária
FRAC_STRAIGHT = 0.02         # fração de amostras com RGB>alpha que já diz "straight"

# Cobertura: opaco = alpha >= 98% da escala · transparente = alpha <= 2%.
# NÃO é fudge de codec — é a definição de "borda suave" que interessa. Um pixel a
# 98% de cobertura não é antialias, é lasca. E a alternativa ingênua (a==255 e
# a==0) mede o CODEC, não a máscara: medido em 2026-08-08, uma máscara DURA
# (retângulo 0/255, sem antialias nenhum) sai do ProRes 4444 com o opaco em 254 e
# é lida como 21,2% de "borda suave" — ou seja, o teste que existe pra denunciar
# máscara binária APROVAVA a máscara binária. Com o corte em 2% ela mede 0,00% e
# reprova, e o opaco bate a geometria (28,23% medido / 27,78% do retângulo).
TOL = 5                      # 5/255 ≈ 2% da escala

PIX_COM_ALPHA = ("yuva", "rgba", "bgra", "argb", "abgr", "ya8", "ya16", "gbrap", "rgba64", "bgra64")
PIX_CINZA = ("gray", "gray8", "gray10", "gray12", "gray16", "ya8")


def contar_faixas(raw, tol):
    """(opacos, transparentes) com `bytes.count`, que roda em C.

    Um histograma em laço Python sobre 16 MB de plano custa segundos; 2*(tol+1)
    passadas de `count` sobre o mesmo buffer custam milissegundos.
    """
    op = sum(raw.count(v) for v in range(255 - tol, 256))
    tr = sum(raw.count(v) for v in range(0, tol + 1))
    return op, tr


def ffprobe_stream(arquivo):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,width,height,nb_frames,duration,r_frame_rate",
         "-of", "default=nw=1:nk=0", arquivo],
        capture_output=True, text=True).stdout
    d = {}
    for linha in out.splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            d[k] = v
    return d


def decoder_para(codec):
    """O ponto inteiro do script. VP9/VP8 só entregam alpha pelo libvpx."""
    if codec == "vp9":
        return ["-c:v", "libvpx-vp9"], "libvpx-vp9"
    if codec == "vp8":
        return ["-c:v", "libvpx"], "libvpx"
    return [], "nativo"


def crua(arquivo, dec, filtros, n_frames, salto):
    cmd = ["ffmpeg", "-nostdin", "-v", "error"] + dec + ["-i", arquivo]
    vf = list(filtros)
    if salto > 1:
        vf.append("select=not(mod(n\\,%d))" % salto)
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-fps_mode", "passthrough", "-pix_fmt", "gray",
            "-frames:v", str(n_frames), "-f", "rawvideo", "-"]
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout, p.stderr.decode("utf-8", "replace")


def monocromatico(arquivo, dec):
    """O `-pix_fmt gray` do x264 volta rotulado yuvj420p nesta build (medido).
    A pergunta honesta não é o rótulo, é se os planos de croma são constantes."""
    for plano in ("u", "v"):
        raw, _ = crua(arquivo, dec, ["extractplanes=" + plano], 1, 1)
        if not raw:
            return False
        neutro = sum(raw.count(v) for v in range(128 - TOL, 128 + TOL + 1))
        if (len(raw) - neutro) > len(raw) // 1000:   # >0,1% de croma real
            return False
    return True


def amostra_premultiplicado(arquivo, dec, larg, alt):
    """Amostra pixels de borda e compara RGB com alpha.

    premultiplicado: RGB = cor*alpha  ->  RGB <= alpha sempre
    straight:        RGB independente ->  RGB pode passar do alpha
    """
    a_raw, _ = crua(arquivo, dec, ["alphaextract"], 1, 1)
    cmd = (["ffmpeg", "-nostdin", "-v", "error"] + dec + ["-i", arquivo]
           + ["-fps_mode", "passthrough", "-pix_fmt", "rgb24",
              "-frames:v", "1", "-f", "rawvideo", "-"])
    rgb = subprocess.run(cmd, capture_output=True).stdout
    n = larg * alt
    if len(a_raw) < n or len(rgb) < n * 3:
        return None
    acima = total = 0
    passo = max(1, n // 4000)
    for i in range(0, n, passo):
        a = a_raw[i]
        if not (51 <= a <= 204):          # só a faixa 0,2 < alpha < 0,8
            continue
        total += 1
        m = max(rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2])
        if m > a + 2:
            acima += 1
    if total < 20:
        return None
    return (acima / total) < FRAC_STRAIGHT   # True = premultiplicado


def main():
    ap = argparse.ArgumentParser(description="prova de alpha por varredura de canal")
    ap.add_argument("arquivo")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--json", action="store_true",
                    help="explícito; a saída padrão já é JSON no stdout")
    a = ap.parse_args()

    arq = a.arquivo
    if not os.path.exists(arq):
        print(json.dumps({"arquivo": arq, "veredito": "reprovado",
                          "motivo": "arquivo não existe"}, ensure_ascii=False))
        return 1

    s = ffprobe_stream(arq)
    if not s.get("width"):
        print(json.dumps({"arquivo": arq, "veredito": "reprovado",
                          "motivo": "sem stream de vídeo legível"}, ensure_ascii=False))
        return 1
    larg, alt = int(s["width"]), int(s["height"])
    codec = s.get("codec_name", "")
    pix = s.get("pix_fmt", "")
    dec, dec_nome = decoder_para(codec)

    total_frames = None
    if s.get("nb_frames", "").isdigit():
        total_frames = int(s["nb_frames"])
    elif s.get("duration") and s.get("r_frame_rate", "0/1") != "0/0":
        try:
            num, den = s["r_frame_rate"].split("/")
            total_frames = int(float(s["duration"]) * float(num) / float(den))
        except (ValueError, ZeroDivisionError):
            total_frames = None
    salto = max(1, (total_frames // a.frames)) if total_frames and total_frames > a.frames else 1

    # --- que tipo de arquivo é, e de onde sai o alpha -------------------------
    tipo = None
    filtros = []
    if pix.startswith(PIX_COM_ALPHA):
        tipo, filtros = "alpha", ["alphaextract"]
    elif codec in ("vp9", "vp8"):
        # ffprobe mentiu (não sabe trocar decoder). Pergunta ao libvpx.
        teste, err = crua(arq, dec, ["alphaextract"], 1, 1)
        if len(teste) >= larg * alt:
            tipo, filtros = "alpha", ["alphaextract"]
        elif monocromatico(arq, dec):
            tipo, filtros = "gray", []
        else:
            print(json.dumps({
                "arquivo": arq, "tipo": "sem-alpha", "decoder": dec_nome,
                "pix_fmt": pix, "veredito": "reprovado",
                "motivo": "nenhum plano alpha, mesmo com o decoder do libvpx"},
                ensure_ascii=False))
            return 1
    elif pix.startswith(PIX_CINZA) or monocromatico(arq, dec):
        # o próprio plano é o alpha (matte-alpha.mp4). O x264 rotula o gray dele
        # como yuvj420p nesta build, por isso a pergunta é medida, não lida.
        tipo, filtros = "gray", []
    else:
        print(json.dumps({
            "arquivo": arq, "tipo": "sem-alpha", "decoder": dec_nome,
            "pix_fmt": pix, "veredito": "reprovado",
            "motivo": f"pix_fmt '{pix}' não tem alpha e o vídeo não é monocromático"},
            ensure_ascii=False))
        return 1

    # --- varredura ------------------------------------------------------------
    raw, err = crua(arq, dec, filtros, a.frames, salto)
    n = larg * alt
    lidos = len(raw) // n if n else 0
    res = {"arquivo": arq, "tipo": tipo, "decoder": dec_nome, "pix_fmt": pix,
           "largura": larg, "altura": alt, "frames_lidos": lidos,
           "bytes_varridos": lidos * n}
    if lidos == 0:
        res.update(veredito="reprovado",
                   motivo=f"o plano não veio com {larg}x{alt} bytes por frame"
                          + (f" — ffmpeg: {err.strip().splitlines()[0]}" if err.strip() else ""))
        print(json.dumps(res, ensure_ascii=False))
        return 1
    raw = raw[: lidos * n]

    tot = len(raw)
    op, tr = contar_faixas(raw, TOL)
    borda = tot - op - tr
    res["opaco_pct"] = round(100.0 * op / tot, 2)
    res["transparente_pct"] = round(100.0 * tr / tot, 2)
    res["borda_pct"] = round(100.0 * borda / tot, 2)
    res["premultiplicado"] = (amostra_premultiplicado(arq, dec, larg, alt)
                              if tipo == "alpha" else False)

    if op == tot:
        res.update(veredito="reprovado", motivo="alpha 100% opaco — recorte degenerado")
    elif tr == tot:
        res.update(veredito="reprovado", motivo="alpha 100% transparente — recorte degenerado")
    elif res["borda_pct"] < BORDA_MIN_PCT:
        res.update(veredito="reprovado",
                   motivo=f"borda suave {res['borda_pct']}% < {BORDA_MIN_PCT}% — "
                          "máscara binária, a colagem vai aparecer")
    else:
        res["veredito"] = "ok"

    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["veredito"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
