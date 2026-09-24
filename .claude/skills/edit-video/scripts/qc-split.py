#!/usr/bin/env python3
"""qc-split.py — o split-screen enquadrou o rosto? (SPEC-28)

    qc-split.py <saida.mp4> --plano split-plano.json [--base B]
                [--folha folha-split.png] [--json] [--amostras-por-s N]

    exit 0 = nenhuma FALHA · 1 = ao menos uma · 2 = erro de uso

Quatro checagens, todas com número, todas medidas NO ARQUIVO FINAL:

  1. alpha de b-roll sobre o topo da cabeça — reprova acima de 0,5 %.
     É o defeito que motivou a spec: no estudo entregue a mediana era ~12 % e o
     pico passava de 30 %, com a jaqueta do b-roll atravessando o cabelo.
  2. o deslocamento APLICADO bate com o planejado, por correlação cruzada da
     base contra a saída (|Δ| <= 1 px, correlação >= 0,99).
  3. nenhum preto exposto: na linha y = S − 1 o b-roll tem que estar opaco, e
     nenhuma linha acima de S pode ser preto puro visível.
  4. A/V intacto: mesmos frames, mesma duração e o MESMO md5 do stream de áudio
     (o split-broll.py copia o áudio; qualquer diferença aqui é deriva).

🔴 POR QUE A CABEÇA É MEDIDA NA BASE E O DESLOCAMENTO NA SAÍDA
A primeira versão deste QC procurava a cabeça na SAÍDA com o mesmo matte de
pessoa. **Não funciona, e está medido**: o b-roll do estudo é um balcão de
fast-food *com gente dentro*, e o Vision segmenta o figurante do apoio junto. O
portão devolveu `alpha 100 %` em 35/35 amostras de uma composição CERTA — teria
reprovado a peça boa e, pior, aprovaria uma errada pelo mesmo motivo trocado.
Não existe, na imagem composta, informação que separe a cabeça do creator da
cabeça de quem está no b-roll.

A cadeia que sobrou é medida em três pedaços independentes, nenhum deles lido do
plano:

  cabeça      matte de pessoa na BASE (o vídeo antes do apoio), TODAS as amostras
  transforma  correlação cruzada da base contra a SAÍDA, dentro da janela
  máscara     a rampa do perfil de peça

e o veredito é `alpha_broll(cabeça_base · z + Δ_medido)`. O plano entra só para
dizer QUAIS segmentos e QUAL escala — se ele mentir sobre o deslocamento, a
checagem 2 acusa.

🔴 FRAME É ÍNDICE, NUNCA `-ss`
Medido aqui: `ffmpeg -ss 8.7` devolve frames DIFERENTES da base e da saída (GOPs
diferentes). Com `-ss`, a correlação caía para 0,981 e acusava Δ=−4 px de erro
inexistente; indexando por `select=eq(n,K)` ela dá 0,9997 e Δ=−1. Um portão que
mede o SEEK e chama de deslocamento é exatamente o falso positivo que faz
ninguém mais olhar para o portão.

🔴 A FOLHA AMOSTRA O VÍDEO COMO ELE É
`ffmpeg -ss` no arquivo final, `scale` para caber no mosaico, NENHUM `crop`. As
linhas de referência são DESENHADAS por cima, nunca aplicadas. A 1ª versão da
folha-enquadramento.py da peca-10-27-07 recortava de novo e inventou um defeito
que não existia, custando um ciclo de remontagem (comentário :31-35 dela).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import perfil as perfil_mod   # noqa: E402

_e = importlib.util.spec_from_file_location("split_plano",
                                            os.path.join(AQUI, "split-plano.py"))
sp = importlib.util.module_from_spec(_e)
_e.loader.exec_module(sp)

ALPHA_MAX = 0.005          # 0,5 % — o critério 2 da spec
CORR_MIN = 0.99
DESLOC_TOL = 1             # px
PASSO_GROSSO = 2           # px na varredura larga; o refino é ±PASSO_GROSSO
PRETO_LUMA = 4             # mediana de linha abaixo disto é preto puro visível
TIRA_INI = 0.02            # da altura, abaixo do fim da rampa: onde a tira começa
TIRA_ALT = 0.20            # da altura: espessura da tira correlacionada
COLUNAS = 48               # colunas amostradas; a correlação é sobre LINHAS


def log(m):
    print(m, file=sys.stderr)


def md5_audio(caminho):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", caminho,
                        "-map", "0:a?", "-c", "copy", "-f", "md5", "-"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def probe(caminho, campos, contar=False):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if contar:
        cmd.append("-count_frames")
    cmd += ["-show_entries", "stream=" + campos, "-of", "default=nk=1:nw=1", caminho]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()


def duracao(caminho):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", caminho], capture_output=True, text=True)
    return float(o.stdout.strip() or 0)


def frames_por_indice(video, indices, larg, alt):
    """Frames cinza por ÍNDICE. Nunca `-ss`: veja o cabeçalho — `-ss` no mesmo
    instante devolve frames diferentes de dois arquivos com GOPs diferentes, e a
    correlação passa a medir o seek."""
    import numpy as np
    if not indices:
        return {}
    sel = "+".join("eq(n\\,%d)" % i for i in sorted(set(indices)))
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", video,
         "-vf", "select='%s'" % sel, "-vsync", "0",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = larg * alt
    got = [np.frombuffer(raw[k * n:(k + 1) * n], dtype="uint8").reshape(alt, larg)
           for k in range(len(raw) // n)]
    return dict(zip(sorted(set(indices)), got))


def topo_abaixo_de(alpha, larg, alt, y0):
    """Primeira linha >= y0 com pessoa sustentada. `None` = não achou nada."""
    linhas = (alpha >= sp.PESSOA_LIM).sum(1)
    lim = max(1, int(sp.FRACAO_LARGURA_CABECA * larg))
    seguidas = 0
    for y in range(int(y0), alt):
        if linhas[y] >= lim:
            seguidas += 1
            if seguidas >= sp.LINHAS_SUSTENTADAS:
                return y - sp.LINHAS_SUSTENTADAS + 1
        else:
            seguidas = 0
    return None


def escalar_como_o_render(base_f, z, larg, alt, foco_x=0.5):
    """A MESMA geometria do split-broll.py: dimensões pares, crop em x pela
    âncora. Reproduzir a transformação é o que permite conferir o ramo
    `deslocamento+escala` — sem isso, o QC ficaria NÃO VERIFICADO exatamente no
    caminho mais arriscado."""
    import numpy as np
    from PIL import Image
    hz = 2 * int(round(alt * z / 2.0))
    wz = 2 * int(round(larg * hz / float(alt) / 2.0))
    xoff = int(round((wz - larg) * float(foco_x)))
    im = Image.fromarray(base_f).resize((wz, hz), Image.BICUBIC)
    return np.asarray(im)[:, xoff:xoff + larg]


def correlacao_deslocamento(base_f, saida_f, alt, larg, y_fim):
    """Δ vertical entre base e saída por correlação cruzada normalizada.

    🔴 A BUSCA É LARGA DE PROPÓSITO — de 0 até a tira, não ±8 px em torno do que
    o plano diz. A primeira versão procurava ancorada no `S` planejado, e com
    isso o arquivo ENTREGUE (deslocamento real 480 px) devolveu o extremo da
    janela (613 px) com correlação 0,26 — que a checagem seguinte usou como se
    fosse medida boa e aprovou a peça DEFEITUOSA. Portão ancorado no valor que
    ele deveria conferir mede a âncora. (Medido em 2026-08-09, SPEC-28.)

    A tira sai da SAÍDA, abaixo do fim da rampa: ali o alpha do b-roll é zero e
    os pixels são os da base, então a correlação mede translação e não mistura.
    """
    import numpy as np
    r0 = int(round(y_fim + TIRA_INI * alt))
    r1 = min(alt, r0 + int(TIRA_ALT * alt))
    if r1 - r0 < 8:
        return None, None
    passo = max(1, larg // COLUNAS)
    b = saida_f[r0:r1, ::passo].astype(float)
    b = b - b.mean()
    nb = float(np.sqrt((b * b).sum())) or 1e-9

    def score(d):
        if r0 - d < 0 or r1 - d > base_f.shape[0]:
            return -2.0
        a = base_f[r0 - d:r1 - d, ::passo].astype(float)
        a = a - a.mean()
        na = float(np.sqrt((a * a).sum())) or 1e-9
        return float((a * b).sum() / (na * nb))

    lim = min(r0, base_f.shape[0] - 1)
    melhor = max(((d, score(d)) for d in range(0, lim + 1, PASSO_GROSSO)),
                 key=lambda x: x[1])
    fino = range(max(0, melhor[0] - PASSO_GROSSO), min(lim, melhor[0] + PASSO_GROSSO) + 1)
    return max(((d, score(d)) for d in fino), key=lambda x: x[1])


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("saida")
    ap.add_argument("--plano", required=True)
    ap.add_argument("--base")
    ap.add_argument("--folha")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--amostras-por-s", type=float, default=None)
    a = ap.parse_args()

    if not os.path.isfile(a.saida):
        sys.exit(2)
    with open(a.plano, encoding="utf-8") as fh:
        plano = json.load(fh)
    if not str(plano.get("schema", "")).startswith("benchmark.split-plano/"):
        log("%s não é um split-plano (schema %r)" % (a.plano, plano.get("schema")))
        return 2

    dir_plano = os.path.dirname(os.path.abspath(a.plano))
    base = a.base or os.path.join(dir_plano, plano.get("base", ""))
    m = plano["mascara"]
    larg = int(plano["formato"]["largura"])
    alt = int(plano["formato"]["altura"])
    y_op, y_fim = float(m["y_op"]), float(m["y_fim"])
    curva = m.get("curva", "smooth")
    achados, falhas = [], []

    def falha(cod, msg):
        falhas.append(cod)
        achados.append({"nivel": "FALHA", "codigo": cod, "msg": msg})
        log("FALHA %s: %s" % (cod, msg))

    def ok(cod, msg):
        achados.append({"nivel": "ok", "codigo": cod, "msg": msg})
        log("ok    %s: %s" % (cod, msg))

    def nao_verificado(cod, msg):
        achados.append({"nivel": "NÃO VERIFICADO", "codigo": cod, "msg": msg})
        log("nver  %s: %s" % (cod, msg))

    # ── 0. procedência ───────────────────────────────────────────────────────
    if os.path.isfile(base):
        h = hashlib.sha1()
        with open(base, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        real = h.hexdigest()[:8]
        if plano.get("base_sha1_8") and plano["base_sha1_8"] != real:
            falha("PLANO-ORFAO", "o plano foi medido na base %s e o disco tem %s — "
                                 "medir a saída contra ele é comparar com outro vídeo"
                  % (plano["base_sha1_8"], real))
        else:
            ok("PROCEDENCIA", "plano e base batem (sha1_8 %s)" % real)
    else:
        nao_verificado("PROCEDENCIA", "base %r não encontrada; as checagens 2 e 4 "
                                      "não podem rodar" % base)

    segs = [s for s in plano["segmentos"] if s.get("motivo") != "nao-resolvido"]
    taxa = plano["formato"]["fps"]
    num, den = (str(taxa).split("/") + ["1"])[:2]
    fps = float(num) / float(den)
    aps = a.amostras_por_s or plano.get("medidor", {}).get("amostras_por_s") or 4
    por_seg = []
    for s in segs:
        ts, t = [], float(s["t0"])
        while t < float(s["t1"]) - 1e-9:
            ts.append(t)
            t += 1.0 / float(aps)
        por_seg.append(ts or [(float(s["t0"]) + float(s["t1"])) / 2])

    # ── 2. deslocamento aplicado × planejado (vem PRIMEIRO: é o Δ que a
    #      checagem 1 usa para levar a cabeça da base para a saída) ───────────
    import numpy as np
    desloc = {}
    if os.path.isfile(base):
        meios = [int(round((float(s["t0"]) + float(s["t1"])) / 2 * fps)) for s in segs]
        fb = frames_por_indice(base, meios, larg, alt)
        fs = frames_por_indice(a.saida, meios, larg, alt)
        conferidos = 0
        for k, s in enumerate(segs):
            bf, sf, S = fb.get(meios[k]), fs.get(meios[k]), int(s["deslocamento_px"])
            if bf is None or sf is None:
                nao_verificado("DESLOCAMENTO-seg%s" % s["i"], "frame %d não lido" % meios[k])
                continue
            z = float(s["escala"])
            bt = bf if abs(z - 1.0) <= 1e-6 else escalar_como_o_render(bf, z, larg, alt)
            d, c = correlacao_deslocamento(bt, sf, alt, larg, y_fim)
            if d is None:
                nao_verificado("DESLOCAMENTO-seg%s" % s["i"], "tira útil vazia")
                continue
            conferidos += 1
            # ⚠️ só entra no mapa da checagem 1 o Δ com correlação boa. Δ de
            # correlação baixa é ruído com cara de medida — foi assim que a
            # versão anterior aprovou o arquivo defeituoso.
            if c >= CORR_MIN:
                desloc[k] = (d, c)
            if abs(d - S) > DESLOC_TOL or c < CORR_MIN:
                falha("DESLOCAMENTO-seg%s" % s["i"],
                      "aplicado %d px, plano diz %d px (Δ=%+d), correlação %.4f"
                      % (d, S, d - S, c))
            else:
                ok("DESLOCAMENTO-seg%s" % s["i"],
                   "aplicado %d px = plano ±%d (Δ=%+d), correlação %.4f%s"
                   % (d, DESLOC_TOL, d - S, c,
                      "" if abs(z - 1.0) <= 1e-6 else
                      " (base pré-escalada por %.3f, a mesma geometria do render)" % z))
        if not conferidos:
            nao_verificado("DESLOCAMENTO", "nenhum segmento pôde ser correlacionado")

    # ── 1. alpha de b-roll sobre a cabeça ────────────────────────────────────
    j = plano["janela"]
    alphas, cabecas = [], {}
    if not os.path.isfile(base):
        nao_verificado("BROLL-SOBRE-A-CABECA",
                       "sem a base não há como separar a cabeça do creator da de quem "
                       "está DENTRO do b-roll — ver o cabeçalho deste script")
    else:
        dir_matte = os.path.join(os.path.dirname(os.path.abspath(a.saida)),
                                 ".qc-split-matte")
        art, meta = sp.rodar_matte(base, float(j["t0"]), float(j["t1"]), dir_matte)
        ini_frame, n_frames = meta["janela"]["ini_frame"], meta["janela"]["n_frames"]
        mw, mh = int(meta["formato"]["largura"]), int(meta["formato"]["altura"])
        idx, mapa = [], []
        for k, s in enumerate(segs):
            for t in por_seg[k]:
                i = int(round(t * fps)) - ini_frame
                if 0 <= i < n_frames:
                    idx.append(i)
                    mapa.append((k, t, i))
        quadros = dict(zip(sorted(set(idx)),
                           sp.ler_frames_cinza(art, sorted(set(idx)), mw, mh)))
        estimado = 0
        for k, t, i in mapa:
            q = quadros.get(i)
            if q is None:
                continue
            y = topo_abaixo_de(q, mw, mh, 0)
            if y is None:
                continue
            s = segs[k]
            if k in desloc:
                d = desloc[k][0]
            else:
                # sem Δ medido não se inventa: o plano NÃO é fonte aqui.
                estimado += 1
                continue
            y_out = y * float(s["escala"]) + d
            al = sp.alpha_broll(y_out, y_op, y_fim, curva)
            alphas.append(al)
            cabecas.setdefault(k, []).append((t, y_out, al))
        if not alphas and estimado >= len(mapa) and mapa:
            nao_verificado("BROLL-SOBRE-A-CABECA",
                           "%d/%d amostras sem Δ MEDIDO (nenhum segmento correlacionou): "
                           "sem a transformação medida não há como dizer onde a cabeça "
                           "aterrissou, e inventar com o número do plano seria conferir "
                           "o plano contra ele mesmo" % (estimado, len(mapa)))
        elif not alphas:
            falha("SEM-CABECA", "nenhuma pessoa encontrada na BASE em %d amostras — "
                                "ou o medidor está quebrado, ou não há talking-head "
                                "nesta janela. Verde aqui seria mentira." % len(mapa))
        else:
            pior = max(alphas)
            msg = ("%d/%d amostras com cabeça · alpha de b-roll sobre o topo: mediana "
                   "%.2f%% · máx %.2f%% (teto %.1f%%)%s"
                   % (len(alphas), len(mapa), statistics.median(alphas) * 100,
                      pior * 100, ALPHA_MAX * 100,
                      "" if not estimado else
                      " · %d amostra(s) PULADAS (sem Δ medido no segmento)"
                      % estimado))
            if pior > ALPHA_MAX:
                ruins = sum(1 for x in alphas if x > ALPHA_MAX)
                falha("BROLL-SOBRE-A-CABECA", msg + " — %d amostra(s) acima do teto"
                      % ruins)
            else:
                ok("BROLL-SOBRE-A-CABECA", msg)

    # ── 3. nenhum preto exposto ──────────────────────────────────────────────
    meios = [int(round((float(s["t0"]) + float(s["t1"])) / 2 * fps)) for s in segs]
    fsaida = frames_por_indice(a.saida, meios, larg, alt)
    for k, s in enumerate(segs):
        S = int(s["deslocamento_px"])
        al = sp.alpha_broll(S - 1, y_op, y_fim, curva)
        if al < 0.999:
            falha("PRETO-EXPOSTO-seg%s" % s["i"],
                  "na linha y=%d (S−1) o b-roll tem alpha %.4f: o topo preto da base "
                  "aparece" % (S - 1, al))
            continue
        t = (float(s["t0"]) + float(s["t1"])) / 2
        f = fsaida.get(meios[k])
        if f is None:
            nao_verificado("PRETO-EXPOSTO-seg%s" % s["i"], "frame não lido")
            continue
        med = np.median(f[:S, :], axis=1)
        pretas = int((med < PRETO_LUMA).sum())
        if pretas:
            falha("PRETO-EXPOSTO-seg%s" % s["i"],
                  "%d das %d linhas acima de S têm mediana de luma < %d"
                  % (pretas, S, PRETO_LUMA))
        else:
            ok("PRETO-EXPOSTO-seg%s" % s["i"],
               "alpha em S−1 = %.4f e 0/%d linhas pretas em t=%.2f s" % (al, S, t))

    # ── 4. A/V intacto ───────────────────────────────────────────────────────
    if os.path.isfile(base):
        nb_b = probe(base, "nb_read_frames", contar=True)
        nb_s = probe(a.saida, "nb_read_frames", contar=True)
        db, ds = duracao(base), duracao(a.saida)
        ab, asd = md5_audio(base), md5_audio(a.saida)
        if nb_b != nb_s:
            falha("AV-FRAMES", "base %s frames, saída %s" % (nb_b, nb_s))
        elif abs(db - ds) > 1.0 / max(fps, 1):
            falha("AV-DURACAO", "base %.4f s, saída %.4f s (mais de um frame)" % (db, ds))
        elif ab != asd:
            falha("AV-AUDIO", "md5 do stream de áudio mudou (%s → %s): o split-broll "
                              "copia o áudio, então isto é deriva" % (ab, asd))
        else:
            ok("AV-INTACTO", "%s frames, %.4f s, md5 do áudio idêntico" % (nb_s[0], ds))

    # ── a folha ──────────────────────────────────────────────────────────────
    if a.folha:
        _folha(a.saida, a.folha, segs, cabecas, larg, alt, y_op, y_fim,
               float(plano["mascara"]["alvo"]))
        log(">> folha: %s" % os.path.abspath(a.folha))

    rel = {"schema": "benchmark.qc-split/v1", "saida": os.path.basename(a.saida),
           "plano": os.path.basename(a.plano), "amostras": len(alphas),
           "alpha_mediana": None if not alphas else round(statistics.median(alphas), 5),
           "alpha_max": None if not alphas else round(max(alphas), 5),
           "achados": achados, "falhas": falhas}
    if a.json:
        json.dump(rel, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        print("qc-split: %d checagem(ns), %d FALHA(s), %d amostra(s) de cabeça varrida(s)"
              % (len(achados), len(falhas), len(alphas)))
    return 1 if falhas else 0


def _folha(video, destino, segs, cabecas, larg, alt, y_op, y_fim, alvo):
    """3 instantes por segmento. `-ss` + `scale`; NENHUM crop. As linhas são
    desenhadas por cima, nunca aplicadas."""
    from PIL import Image, ImageDraw
    tiles, rotulos = [], []
    for k, s in enumerate(segs):
        t0, t1 = float(s["t0"]), float(s["t1"])
        for frac in (1 / 6.0, 0.5, 5 / 6.0):
            t = t0 + (t1 - t0) * frac
            raw = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.6f" % t, "-i", video,
                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True).stdout
            if not raw:
                continue
            import io
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            esc = 360.0 / im.width
            im = im.resize((360, int(round(im.height * esc))))
            d = ImageDraw.Draw(im)
            d.line([(0, y_fim * esc), (im.width, y_fim * esc)], fill=(255, 90, 0), width=2)
            d.line([(0, alvo * esc), (im.width, alvo * esc)], fill=(0, 200, 255), width=2)
            prox = min(cabecas.get(k, []), key=lambda c: abs(c[0] - t), default=None)
            if prox:
                y = prox[1] * esc
                d.line([(0, y), (im.width, y)], fill=(0, 255, 0), width=2)
                d.text((6, max(0, y - 14)), "cabeça %d px (alpha %.2f%%)"
                       % (prox[1], prox[2] * 100), fill=(0, 255, 0))
            d.text((6, 6), "seg%s t=%.2fs S=%d z=%.3f"
                   % (s["i"], t, s["deslocamento_px"], s["escala"]), fill=(255, 255, 0))
            tiles.append(im)
            rotulos.append("seg%s" % s["i"])
    if not tiles:
        return
    cols = 3
    linhas = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].width, tiles[0].height
    folha = Image.new("RGB", (cols * w, linhas * h), (16, 16, 16))
    for i, im in enumerate(tiles):
        folha.paste(im, ((i % cols) * w, (i // cols) * h))
    folha.save(destino)


if __name__ == "__main__":
    sys.exit(main())
