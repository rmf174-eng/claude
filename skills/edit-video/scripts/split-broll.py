#!/usr/bin/env python3
"""split-broll — insere b-roll em SPLIT-SCREEN com borda esfumaçada numa janela do vídeo.

O efeito medido no ref-D (data/adhoc/modelagem-edicao/RECEITA-EDICAO.md):
b-roll ocupa o topo, o talking-head é EMPURRADO PRA BAIXO (sem zoom), e a fronteira
entre os dois não é uma linha — é uma rampa de alpha longa (~17% da altura do frame),
o que dá a sensação de "fumaçado". Serve pra duas coisas ao mesmo tempo:
mostrar a prova visual E esconder os jump cuts do trecho mais remendado.

Uso:
    split-broll.py <base.mp4> <broll.mp4> <t0> <t1> <saida.mp4> [opções]

Opções:
    --plano P            split-plano.json (SPEC-28): (deslocamento, escala) MEDIDOS
                         por segmento. É o caminho normal.
    --escala Z           escape manual da escala da base; vence o plano       [1.0]
    --foco-x F           âncora horizontal do recorte da base, 0..1 (só com z>1) [0.5]
    --desloca-base PCT   quanto a base desce, em % da altura   [25]
    --opaco PCT          até onde o b-roll é 100% opaco        [perfil.split, 34]
    --fim PCT            onde o b-roll chega a 0% (fim da rampa) [perfil.split, 51]
    --broll-ini S        de que ponto do b-roll começar a usar  [0]
    --curva NOME         linear | smooth (smoothstep)           [perfil.split, smooth]
    --sem-audio-copy     re-encoda o áudio (default é -c:a copy)

Notas:
  - A base é deslocada só DENTRO da janela; fora dela o vídeo passa intacto.
  - O topo que "esvazia" com o deslocamento fica preto e é coberto pelo b-roll opaco;
    por isso `--opaco` tem que ser >= o topo do vídeo deslocado (o script confere).
  - Áudio: `-c:a copy` por padrão — a trilha NÃO é tocada (nada de deriva de A/V).

🔴 SEM `--plano` E SEM `--escala` O COMPORTAMENTO É O DE HOJE, byte a byte — a base
desce uma CONSTANTE e onde a cabeça aterrissa é efeito colateral. Medido nas duas
produções reais do repo, isso põe o topo da cabeça dentro da rampa de alpha
(mediana 10,7 % de b-roll sobre a cabeça no estudo entregue, máx 31,1 %). Por isso
o caminho sem plano AVISA. Quem resolve é o `split-plano.py`, que MEDE a cabeça.
"""
import argparse, json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perfil as perfil_mod   # noqa: E402

# 📐 W, H e o fps saem do perfil de peça (SPEC-00) — e são CONFERIDOS contra as
# dimensões reais da base. A máscara é overlaida pixel a pixel sobre ela: se o
# perfil disser 1080x1920 e a base for 1920x1080, o resultado é lixo silencioso.
# Quem manda no fim é a base (mesmo princípio do omni-insert/encaixar.py, que já
# se adapta ao canvas); o perfil dá o default e a divergência é avisada.
W = H = None


def gerar_mascara(caminho, opaco_pct, fim_pct, curva):
    """PNG cinza W×H: branco = b-roll visível, preto = base visível."""
    from PIL import Image
    import numpy as np

    y_op = H * opaco_pct / 100.0
    y_fim = H * fim_pct / 100.0
    y = np.arange(H, dtype=float)
    t = np.clip((y - y_op) / max(y_fim - y_op, 1e-6), 0, 1)
    if curva == "smooth":
        t = t * t * (3 - 2 * t)           # smoothstep — sem quina no início/fim da rampa
    a = ((1 - t) * 255).astype("uint8")
    Image.fromarray(np.repeat(a[:, None], W, axis=1), "L").save(caminho)
    return y_op, y_fim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("broll")
    ap.add_argument("t0", type=float); ap.add_argument("t1", type=float)
    ap.add_argument("saida")
    ap.add_argument("--desloca-base", type=float, default=25.0)
    ap.add_argument("--opaco", type=float, default=None)
    ap.add_argument("--fim", type=float, default=None)
    ap.add_argument("--broll-ini", type=float, default=0.0)
    ap.add_argument("--broll-foco", choices=["cima", "centro", "baixo"], default="centro",
                    help="âncora vertical do recorte do b-roll (o que sobrevive ao crop)")
    ap.add_argument("--curva", choices=["linear", "smooth"], default=None)
    ap.add_argument("--sem-audio-copy", action="store_true")
    ap.add_argument("--mascara", help="PNG de máscara próprio (ignora --opaco/--fim)")
    ap.add_argument("--plano", help="split-plano.json (SPEC-28): o (deslocamento, escala) "
                                    "MEDIDO por segmento")
    ap.add_argument("--escala", type=float, default=None,
                    help="escape manual: uma escala para a janela inteira; vence o plano")
    ap.add_argument("--foco-x", type=float, default=0.5,
                    help="âncora horizontal do recorte da base quando a escala > 1")
    a = ap.parse_args()

    global W, H
    P = perfil_mod.carregar(os.path.dirname(os.path.abspath(a.base)), quieto=True)
    W, H = int(P["video"]["largura"]), int(P["video"]["altura"])
    FPS = P["video"]["fps"]
    bw_base, bh_base = _dim(a.base)
    if (bw_base, bh_base) != (W, H):
        print(f">> a base é {bw_base}x{bh_base} e o perfil diz {W}x{H} — adotando a BASE "
              f"(a máscara tem que casar pixel a pixel com ela)", file=sys.stderr)
        W, H = bw_base, bh_base

    # 📐 A FAIXA sai do perfil (SPEC-28 §3.7): `opaco_pct`/`fim_pct`/`curva` descrevem
    # COMO A PEÇA É. `desloca_base` NÃO entra aqui de propósito — ele é medido por
    # peça, e um perfil que carregasse "desloca_base: 25 %" seria o defeito de hoje
    # com outro nome. Sem bloco no perfil, valem os mesmos números de sempre.
    plano = _ler_plano(a) if a.plano else None
    # 🔴 COM PLANO, A MÁSCARA VEM DO PLANO. O alvo da cabeça foi resolvido CONTRA
    # aquela rampa; compor com outra (porque o perfil mudou depois) põe a cabeça
    # no lugar errado com o plano aparentemente certo. O perfil só entra quando
    # não há plano.
    sp = (plano or {}).get("mascara") or P.get("split") or {}
    if a.opaco is None:
        a.opaco = _pct(sp.get("opaco_pct"), 34.0)
    if a.fim is None:
        a.fim = _pct(sp.get("fim_pct"), 51.0)
    if a.curva is None:
        a.curva = sp.get("curva") or "smooth"

    S = round(H * a.desloca_base / 100.0)
    if plano is None and a.escala is None:
        print(">> sem plano de enquadramento — a base só desce; rode split-plano.py. "
              "O topo da cabeça pode cair dentro da rampa de alpha (medido: mediana "
              "10,7% de b-roll sobre a cabeça no estudo entregue).", file=sys.stderr)
    if a.opaco < a.desloca_base and plano is None:
        print(f"ERRO: --opaco ({a.opaco}%) menor que --desloca-base ({a.desloca_base}%): "
              f"ia sobrar preto entre o fim do b-roll opaco e o topo da base.", file=sys.stderr)
        sys.exit(1)

    # ⚠️ O b-roll NÃO precisa cobrir o frame inteiro — só até onde a máscara ainda deixa
    # passar alguma coisa (`--fim`). Abaixo disso o alpha é 0 e o que houver é irrelevante.
    # Isso importa muito: a maioria do stock é LANDSCAPE, e forçar 16:9 a cobrir 9:16
    # inteiro é zoom de 3,16× (vira close de nada). Cobrir só até 51% da altura é 1,61× —
    # quase metade do zoom, e o plano continua legível.
    BH = min(H, int(H * a.fim / 100) + 4)
    bw, bh = _dim(a.broll)
    esc = max(W / bw, BH / bh)                    # escala de "cover" da faixa
    perda_x, perda_y = bw * esc / W, bh * esc / BH  # quanto da fonte é descartado em cada eixo
    print(f">> b-roll {bw}x{bh} → camada {W}x{BH} (cobre até {BH/H*100:.0f}% da altura), "
          f"foco '{a.broll_foco}' · sobra {perda_x:.2f}× em x e {perda_y:.2f}× em y "
          f"(cobrir o frame INTEIRO custaria {max(W/bw, H/bh)*bw/W:.2f}× em x)", file=sys.stderr)
    # deslocamento vertical do crop dentro do frame já escalado
    foco = {"cima": "0", "centro": "(ih-oh)/2", "baixo": "ih-oh"}[a.broll_foco]

    tmp = tempfile.mkdtemp(prefix="splitbroll-")
    mask = a.mascara or os.path.join(tmp, "mask.png")
    if not a.mascara:
        y_op, y_fim = gerar_mascara(mask, a.opaco, a.fim, a.curva)
        print(f">> máscara: opaca até y={y_op:.0f}px ({a.opaco}%), zero em y={y_fim:.0f}px "
              f"({a.fim}%), feather {y_fim-y_op:.0f}px ({a.fim-a.opaco:.0f}% da altura), curva {a.curva}",
              file=sys.stderr)
    en = f"between(t,{a.t0},{a.t1})"
    blocos = _blocos(a, plano, S, H, FPS)
    if len(blocos) == 1 and blocos[0]["z"] == 1.0 and blocos[0]["S"] == S \
            and blocos[0]["enable"] == en:
        # 🔴 O CAMINHO DE HOJE, byte a byte: uma cadeia só, sem `scale`, com a mesma
        # string de filtro de sempre. Nada de `scale=iw*1:ih*1` — é reamostragem
        # inútil que custa nitidez de graça e quebraria o md5 do baseline.
        print(f">> base desce {S}px ({a.desloca_base}%) na janela "
              f"{a.t0:.2f}–{a.t1:.2f}s", file=sys.stderr)
        cadeia = (f"[0:v]split=2[b0][b1];"
                  f"[b1]pad={W}:{H+S}:0:{S}:black,crop={W}:{H}:0:0[shift];"
                  f"[b0][shift]overlay=0:0:enable='{en}'[stage];")
    else:
        cadeia = _cadeia_por_segmento(blocos, P, a.foco_x)
    fc = (
        cadeia +
        # b-roll: cobre só a FAIXA útil (W x BH) e é padeado até o frame inteiro —
        # o pad preto cai onde a máscara já é 0. Atrasado até t0.
        f"[1:v]scale={W}:{BH}:force_original_aspect_ratio=increase,"
        f"crop={W}:{BH}:(iw-ow)/2:{foco},"
        f"pad={W}:{H}:0:0:black,"
        f"fps={FPS},tpad=start_duration={a.t0}:start_mode=add:color=black,"
        f"format=rgba[bl];"
        f"[2:v]format=gray,scale={W}:{H}[m];"
        f"[bl][m]alphamerge[bla];"
        f"[stage][bla]overlay=0:0:enable='{en}':eof_action=pass[v]"
    )

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
           "-i", a.base,
           "-ss", str(a.broll_ini), "-i", a.broll,
           "-loop", "1", "-i", mask,
           "-filter_complex", fc,
           "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-crf", str(P["video"].get("crf", 16)),
           "-preset", P["video"].get("preset_x264", "medium"),
           "-pix_fmt", P["video"].get("pix_fmt", "yuv420p")]
    cmd += (["-c:a", P["audio"].get("codec", "aac"), "-b:a", P["audio"].get("bitrate", "192k")]
            if a.sem_audio_copy else ["-c:a", "copy"])
    # a duração é PINADA na da base (nunca `-shortest`): o b-roll acaba antes e o
    # `-shortest` cortaria o vídeo no fim do apoio. Não trocar.
    cmd += ["-t", str(_dur(a.base)), a.saida]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:], file=sys.stderr); sys.exit(r.returncode)
    print(os.path.abspath(a.saida))


# ───────────────────────────────────────── o plano de enquadramento (SPEC-28)

def _pct(fracao, padrao):
    """Fração do perfil → porcentagem da CLI, sem lixo de ponto flutuante.

    `0.34 * 100` é 34.000000000000004 em IEEE754, e isso vaza para a máscara: a
    rampa nasce um epsilon diferente e o md5 do baseline muda sem nada ter
    mudado. O `round(..., 9)` é o que mantém o caminho sem plano byte a byte."""
    return padrao if fracao is None else round(float(fracao) * 100.0, 9)


def _ler_plano(a):
    """Lê o `split-plano.json` e RECUSA plano que não descreve esta base.

    Sem esse par de checagens, um plano medido numa geração anterior da base
    compõe em silêncio e o rosto sai no lugar errado com todos os QCs verdes —
    é a família do "segmento órfão" (SKILL.md:69)."""
    import hashlib
    with open(a.plano, encoding="utf-8") as fh:
        p = json.load(fh)
    if not str(p.get("schema", "")).startswith("benchmark.split-plano/"):
        sys.exit("%s não é um split-plano (schema %r)" % (a.plano, p.get("schema")))
    h = hashlib.sha1()
    with open(a.base, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    if p.get("base_sha1_8") and p["base_sha1_8"] != h.hexdigest()[:8]:
        sys.exit("PLANO ÓRFÃO: %s foi medido na base %s e esta é %s.\n"
                 "Remeça com `split-plano.py` — compor com um plano de outra geração "
                 "da base põe o rosto no lugar errado e nenhum QC de cor, fonema ou "
                 "emenda acusa." % (a.plano, p["base_sha1_8"], h.hexdigest()[:8]))
    j = p.get("janela", {})
    for rot, pedido, no_plano in (("t0", a.t0, j.get("t0")), ("t1", a.t1, j.get("t1"))):
        if no_plano is not None and abs(float(no_plano) - float(pedido)) > 0.05:
            sys.exit("janela divergente: %s da linha de comando é %.5f e o plano diz "
                     "%.5f. O plano encaixa a janela no corte REAL — use os números "
                     "dele (`jq .janela %s`)." % (rot, pedido, no_plano, a.plano))
    return p


def _blocos(a, plano, S, H, fps):
    """A lista de (deslocamento, escala, janela de tempo) que a cadeia aplica.

    Sem plano é UM bloco com a constante de hoje — o caminho que preserva o md5.
    """
    en = f"between(t,{a.t0},{a.t1})"
    if plano is None:
        return [{"S": S, "z": float(a.escala or 1.0), "enable": en,
                 "t0": a.t0, "t1": a.t1, "i": None}]
    segs = sorted(plano["segmentos"], key=lambda s: s["t0"])
    meio = 0.5 / float(fps)
    out = []
    for k, s in enumerate(segs):
        # ⚠️ `between` é fechado nos DOIS lados: sem recuar meio frame no fim, o
        # frame da fronteira casaria em dois blocos e o último a entrar venceria.
        fim = float(s["t1"]) if k == len(segs) - 1 else float(s["t1"]) - meio
        out.append({"S": int(round(float(s["deslocamento_px"]))),
                    "z": float(a.escala) if a.escala is not None else float(s["escala"]),
                    "enable": "between(t,%.6f,%.6f)" % (float(s["t0"]), fim),
                    "t0": float(s["t0"]), "t1": float(s["t1"]), "i": s.get("i")})
    return out


def _cadeia_por_segmento(blocos, P, foco_x):
    """Um par [shift]/overlay por segmento. Cresce linear no nº de segmentos."""
    flags = P["video"].get("escala_flags") or "bicubic"
    n = len(blocos)
    rot = ["c%d" % i for i in range(n)]
    partes = ["[0:v]split=%d[b0]%s;" % (n + 1, "".join("[%s]" % r for r in rot))]
    prev = "b0"
    for i, (b, r) in enumerate(zip(blocos, rot)):
        S, z = b["S"], b["z"]
        # 📐 as dimensões escaladas são calculadas AQUI, em inteiros PARES.
        # Duas armadilhas medidas, as duas com a mesma mensagem de erro:
        #   `scale=iw*1.038` deixa o arredondamento para o ffmpeg e o `pad`
        #   seguinte falha com "Padded dimensions cannot be smaller than input
        #   dimensions"; e `scale=1145:2035` (ímpar) em yuv420p sai 1146 de
        #   largura pelo mesmo motivo. Par resolve os dois.
        hz = 2 * int(round(H * z / 2.0))
        wz = 2 * int(round(W * hz / float(H) / 2.0))
        xoff = int(round((wz - W) * float(foco_x)))
        f = []
        if abs(z - 1.0) > 1e-9:
            f.append(f"scale={wz}:{hz}:flags={flags}")
        f.append(f"pad={wz}:{hz+S}:0:{S}:black")
        f.append(f"crop={W}:{H}:{xoff}:0")
        partes.append(f"[{r}]{','.join(f)}[sh{i}];")
        alvo = "stage" if i == n - 1 else "st%d" % i
        partes.append(f"[{prev}][sh{i}]overlay=0:0:enable='{b['enable']}'[{alvo}];")
        prev = alvo
        print(">> seg%s: base desce %d px, escala %.3f -> %.4f efetiva (%dx%d), "
              "x_off %d — janela %s"
              % (b["i"], S, z, hz / float(H), wz, hz, xoff, b["enable"]),
              file=sys.stderr)
    return "".join(partes)


def _dur(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip()
    return float(o)


def _dim(p):
    g = lambda k: int(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", f"stream={k}",
         "-of", "default=nk=1:nw=1", p], capture_output=True, text=True).stdout.split()[0])
    return g("width"), g("height")


if __name__ == "__main__":
    main()
