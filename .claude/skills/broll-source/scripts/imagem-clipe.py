#!/usr/bin/env python3
"""imagem-clipe — uma FOTO vira um plano de vídeo inserível, sem nenhum número de formato aqui dentro.

O `split-broll.py` recebe `<broll.mp4>` e entrega ao ffmpeg como input de vídeo: uma
JPEG passada ali produz um stream de 1 frame. Ou seja, **imagem não é inserível na
ilha sem um passo de conversão** — e esse passo não existia em lugar nenhum do repo.
É este script. Ele faz UM plano a partir de UMA imagem: sequência de stills é decisão
de EDL, não de conversor.

Uso:
    imagem-clipe.py <imagem> <saida.mp4>
        [--dur 4.0] [--movimento estatico|zoom-in|zoom-out|pan-e|pan-d]
        [--foco cima|centro|baixo]        # espelha o --broll-foco do split-broll.py
        [--perfil <nome|arquivo.json>] [--dir-producao DIR]
        [--fps N] [--tam LARGURAxALTURA] [--zoom-max 1.15] [--upscale 4]

📐 ZERO NÚMERO DE FORMATO. Dimensão, fps, pix_fmt, crf, preset e tags de cor saem do
   PERFIL DE PEÇA (SPEC-00). Movimento, duração default, zoom máximo e fator de
   upscale saem do bloco `broll.imagem` do perfil. As flags de linha de comando
   existem para sobrepor pontualmente — nunca para o script "saber" um formato.
   ⚠️ Fronteira com a SPEC-24: `movimento`, `dur_default_s` e `zoom_max` são
   look/ritmo, não formato, e são candidatos naturais a `estilos/_escopo.json`.
   Esta spec não escreve nesse arquivo; fica registrado como pendência nomeada.

🔑 O UPSCALE PRÉVIO É O QUE SEPARA KEN BURNS DE TREMOR.
   O `zoompan` calcula o retângulo de corte na grade de pixels DA ENTRADA. Numa fonte
   de ~2k de largura, um zoom lento faz o retângulo andar em passos inteiros e o
   movimento sai aos trancos. Medido (SPEC-29 §3.6b), mesma imagem, 4 s, mesma saída:
   coeficiente de variação da diferença interquadro 0,099 com upscale 4× contra 0,221
   sem upscale — 2,2× pior.
   ⚠️ A régua NÃO é o `mpdecimate`: ele devolve 120/120 frames nos DOIS casos, porque
   mede *frame repetido* e o defeito do zoompan é *passo desigual*. `mpdecimate` só
   serve para o controle negativo do movimento `estatico` (1/120).

Sidecar: `<saida>.json` com licença, autor e página da imagem de origem. Sem ele a
licença morreria na primeira transformação, e "licença sem procedência é licença que
ninguém consegue provar depois" valeria só para o primeiro passo do pipeline.
"""
import argparse
import json
import os
import subprocess
import sys

import perfil_do_bloco as perfil_mod   # noqa: E402  (SPEC-33 / achado A21)

RAIZ_BIB = os.environ.get("BROLL_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools", "broll-library")
RAIZ_BIB = os.path.abspath(RAIZ_BIB)

MOVIMENTOS = ("estatico", "zoom-in", "zoom-out", "pan-e", "pan-d")

# Look default de quando o perfil não traz o bloco `broll.imagem` (produção sem
# perfil.json, que cai no FALLBACK). NÃO é formato: é ritmo/look. Os perfis do
# catálogo trazem o bloco e mandam neste dicionário.
LOOK_PADRAO = {"movimento": "zoom-in", "dur_default_s": 4.0,
               "zoom_max": 1.15, "upscale_fator": 4}


def resolver_perfil(nome_ou_caminho, dir_producao):
    """<nome do catálogo> | <arquivo.json> | <dir da produção> → perfil resolvido."""
    if dir_producao:
        return perfil_mod.carregar(dir_producao, quieto=False)[0]
    alvo = nome_ou_caminho or os.environ.get("BENCH_PERFIL")
    if alvo and not os.path.exists(alvo):
        p, motivo = perfil_mod.por_nome(alvo)
        if p is None:
            sys.exit(motivo)
        return p
    return perfil_mod.carregar(alvo or ".", quieto=False)[0]


def cadeia(mov, n, zmax, W, H, up, foco, fps, tags):
    """O filtro completo, com TODO número vindo de variável.

    A ordem importa: `scale` cobre o quadro-alvo (nunca distorce), `crop` escolhe a
    faixa que sobrevive (é o `--foco`), e só então o `zoompan` trabalha — numa grade
    `up`× maior, que é o que tira o tremor.
    """
    SW, SH = W * up, H * up
    y_crop = {"cima": "0", "centro": "(in_h-out_h)/2", "baixo": "in_h-out_h"}[foco]
    passo = (zmax - 1.0) / max(n - 1, 1)
    centro = ("x='iw/2-(iw/zoom/2)'", "y='ih/2-(ih/zoom/2)'")
    if mov == "estatico":
        z, xy = "z='1'", ("x='0'", "y='0'")
    elif mov == "zoom-in":
        z, xy = f"z='min(zoom+{passo:.8f},{zmax})'", centro
    elif mov == "zoom-out":
        # `zoom` guarda o valor do frame anterior e começa abaixo de 1: a condição
        # dispara UMA vez, no primeiro frame. O piso 1.0001 (e não 1.0) é o que
        # impede a condição de disparar de novo no fim e o plano de saltar.
        z = f"z='if(lte(zoom,1.0),{zmax},max(zoom-{passo:.8f},1.0001))'"
        xy = centro
    else:                       # pan-e | pan-d: zoom fixo, o que anda é o quadro
        prog = f"on/{max(n - 1, 1)}"
        if mov == "pan-e":
            prog = f"(1-{prog})"
        z, xy = f"z='{zmax}'", (f"x='(iw-iw/zoom)*{prog}'", "y='ih/2-(ih/zoom/2)'")
    setp = ("setparams=color_primaries={color_primaries}:color_trc={color_trc}"
            ":colorspace={colorspace}").format(**tags)
    return (f"scale={SW}:{SH}:force_original_aspect_ratio=increase,"
            f"crop={SW}:{SH}:(in_w-out_w)/2:{y_crop},"
            f"zoompan={z}:{xy[0]}:{xy[1]}:d={n}:s={W}x{H}:fps={fps},"
            f"setsar=1,{setp}")


def procedencia(imagem):
    """A entrada do INDEX.json que corresponde a esta imagem (ou None)."""
    idx = os.path.join(RAIZ_BIB, "INDEX.json")
    if not os.path.isfile(idx):
        return None
    alvo = os.path.realpath(imagem)
    try:
        for e in json.load(open(idx)):
            if os.path.realpath(os.path.join(RAIZ_BIB, e.get("arquivo", ""))) == alvo:
                return e
    except (ValueError, OSError):
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("imagem")
    ap.add_argument("saida")
    ap.add_argument("--dur", type=float)
    ap.add_argument("--movimento", choices=MOVIMENTOS)
    ap.add_argument("--foco", choices=("cima", "centro", "baixo"), default="centro")
    ap.add_argument("--perfil", help="nome do catálogo (reels, vsl…), arquivo.json ou dir")
    ap.add_argument("--dir-producao", help="lê <dir>/perfil.json")
    ap.add_argument("--fps", type=int)
    ap.add_argument("--tam", help="LARGURAxALTURA — sobrepõe o perfil")
    ap.add_argument("--zoom-max", type=float)
    ap.add_argument("--upscale", type=int)
    a = ap.parse_args()

    if not os.path.isfile(a.imagem):
        sys.exit(f"imagem não existe: {a.imagem}")

    P = resolver_perfil(a.perfil, a.dir_producao)
    V = P["video"]
    look = dict(LOOK_PADRAO)
    bloco = ((P.get("broll") or {}).get("imagem") or {})
    if bloco:
        look.update(bloco)
    else:
        print(">> perfil sem bloco `broll.imagem`: usando o look padrão "
              f"({look['movimento']}, {look['dur_default_s']}s)", file=sys.stderr)

    W, H = int(V["largura"]), int(V["altura"])
    if a.tam:
        try:
            W, H = (int(x) for x in a.tam.lower().split("x"))
        except ValueError:
            sys.exit("--tam precisa ser LARGURAxALTURA")
    fps = int(a.fps or V["fps"])
    dur = float(a.dur if a.dur is not None else look["dur_default_s"])
    mov = a.movimento or look["movimento"]
    if mov not in MOVIMENTOS:
        sys.exit(f"movimento {mov!r} não existe (tem: {', '.join(MOVIMENTOS)})")
    zmax = float(a.zoom_max if a.zoom_max is not None else look["zoom_max"])
    up = int(a.upscale if a.upscale is not None else look["upscale_fator"])
    if mov == "estatico":
        zmax, up = 1.0, 1      # nada se move: upscale só gastaria CPU
    n = int(round(dur * fps))
    if n < 1:
        sys.exit("duração × fps dá menos de 1 frame")

    tags = dict({"color_primaries": "bt709", "color_trc": "bt709", "colorspace": "bt709"},
                **((P.get("cor") or {}).get("tags_saida") or {}))
    vf = cadeia(mov, n, zmax, W, H, up, a.foco, fps, tags)

    os.makedirs(os.path.dirname(os.path.abspath(a.saida)), exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", a.imagem,
           "-vf", vf, "-frames:v", str(n), "-r", str(fps), "-an",
           "-c:v", "libx264", "-crf", str(V.get("crf", 18)),
           "-preset", V.get("preset_x264", "medium"),
           "-pix_fmt", V.get("pix_fmt", "yuv420p"), a.saida]
    print(f">> {mov} · {n} frames · {W}x{H} @ {fps} · upscale {up}×", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1500:], file=sys.stderr)
        return r.returncode

    e = procedencia(a.imagem)
    if not e:
        print("⚠️ a imagem não está no INDEX.json da biblioteca: o sidecar sai SEM "
              "licença. Material de terceiro tem que entrar pelo `baixar.py`.",
              file=sys.stderr)
    side = {"schema": "benchmark.broll-derivado/v1",
            "origem": (e or {}).get("nome"),
            "arquivo_origem": (e or {}).get("arquivo", os.path.abspath(a.imagem)),
            "licenca": (e or {}).get("licenca"),
            "licenca_slug": (e or {}).get("licenca_slug"),
            "exige_atribuicao": (e or {}).get("exige_atribuicao"),
            "autor": (e or {}).get("autor"), "pagina": (e or {}).get("pagina"),
            "movimento": mov, "dur_s": round(n / fps, 4), "fps": fps,
            "tam": f"{W}x{H}", "foco": a.foco, "zoom_max": zmax, "upscale": up,
            "perfil": P.get("nome")}
    with open(a.saida + ".json", "w", encoding="utf-8") as f:
        json.dump(side, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if (e or {}).get("exige_atribuicao"):
        print(f"⚠️ ESTE PLANO EXIGE CRÉDITO: \"{e.get('autor')}\" — "
              f"`baixar.py --creditos --nomes {e.get('nome')}` imprime a linha pronta.",
              file=sys.stderr)
    print(a.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
