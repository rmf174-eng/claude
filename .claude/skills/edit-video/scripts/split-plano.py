#!/usr/bin/env python3
"""split-plano.py — onde a cabeça DEVE cair no split-screen, medido por segmento.

    split-plano.py <dir> --janela T0 T1 [--base v1-montado.mp4]
                         [--saida split-plano.json] [--cabeca-y PX ...]
                         [--queixo-y PX ...] [--percentil N] [--escala-max Z]
                         [--forcar] [--sem-encaixe] [--simular-falha-seg N|todos]

    stdout: caminho do plano gravado          stderr: log
    exit 0 plano gravado · 1 não resolvido / teto / janela errada · 64 uso

────────────────────────────────────────────────────────────────────────────
O DEFEITO QUE ISTO CONSERTA

`split-broll.py` empurrava a base para baixo por uma CONSTANTE (`--desloca-base
25`), copiada de uma única referência. `pad`+`crop` é translação pura: onde a
cabeça aterrissa é efeito colateral de um número. Medido nas duas produções
reais deste repo, o topo da cabeça caía DENTRO da rampa de alpha do b-roll —
mediana de 10,7 % de b-roll sobre a cabeça no estudo entregue (máx 31,1 %) e
20,2 % na `peca-01`. O b-roll atravessava o cabelo.

Aqui o par vira uma CONTA, com a cabeça MEDIDA:

    cabeça_saida = topo_da_cabeça_na_base · escala + deslocamento

resolvida preferindo `escala = 1` (deslocar é de graça; escalar é upscale de um
vídeo que já está na largura de saída), com cinco guardas, e por SEGMENTO — o
topo da cabeça anda 96 px na janela de 8 s do estudo e só 4–55 px dentro de cada
segmento, porque o que muda entre segmentos é o enquadramento inteiro.

────────────────────────────────────────────────────────────────────────────
PROVENIÊNCIA

Mecanismo modelado de uma ferramenta de edição de terceiro, assets/shortform/src/CustomGraphics.tsx:42-59 e
references/shortform.md:366-391 — cópia de leitura em tools/referencias/.
Implementação nossa: o par vira (deslocamento, escala) resolvido em forma
fechada a partir da máscara do perfil e da cabeça MEDIDA por segmento, com cinco
guardas e rejeição nomeada — o original usa duas constantes de layout.

────────────────────────────────────────────────────────────────────────────
O QUE ESTE SCRIPT NÃO FAZ, DE PROPÓSITO

  * não escreve `zoom`/`cx`/`cy` na `edl.json`. Os números daqui vivem no
    sistema de coordenadas do MONTADO; a EDL vive no do BRUTO. Levar um para o
    outro é a transformação dupla de 2026-07-27, que mandou o creator-3 para o
    canto inferior direito do quadro (SKILL.md:51).
  * não interpola (S, z) dentro do segmento. Isso vira travelling que ninguém
    pediu — o `reframe.py` chega a inventar tendência de zoom (docstring :22).
  * não contém valor de formato. Altura, largura e fps vêm do perfil de peça
    (SPEC-00) e da própria base.
  * não decide sozinho quando a medição falha: rejeita com nome, herda a mediana
    dos que passaram, e se ninguém passou sai 1 sem gravar nada.
"""
import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import perfil as perfil_mod   # noqa: E402

SCHEMA = "benchmark.split-plano/v1"

# ── FÍSICA DA MEDIÇÃO, não formato de peça ──────────────────────────────────
# Tudo aqui é fração ou limiar de escala de cinza: sobrevive a qualquer
# dimensão. O que descreve COMO A PEÇA É (faixa opaca, folga, tetos) vive no
# perfil, nunca aqui — é a regra de ouro da SPEC-00.
PESSOA_LIM = 128            # meio da escala do alpha: pessoa × fundo
FRACAO_LARGURA_CABECA = 0.01   # 1 % da largura já é fio de cabelo sustentado
LINHAS_SUSTENTADAS = 3      # 3 linhas seguidas: mata pixel solto de compressão
FAIXA_LARGURA_CABECA = (0.02, 0.08)   # da altura, abaixo do topo: testa/olhos
FATOR_OMBRO = 2.0           # a linha em que a silhueta dobra de largura
REJ_AREA_MIN, REJ_AREA_MAX = 0.03, 0.70
REJ_TOPO_MIN, REJ_TOPO_MAX = 0.01, 0.55
REJ_SALTO = 0.08            # da altura, contra a mediana móvel de 5
REJ_FRACAO_SEGMENTO = 0.25  # acima disto o segmento é NÃO RESOLVIDO
ENCAIXE_MAX_S = 0.5         # meio segundo não é arredondamento, é janela errada

# Cópia congelada dos defaults de hoje (split-broll.py): perfil antigo sem o
# bloco `split` continua produzindo o comportamento de hoje. `folga_topo_pct`
# nulo é o que faz este script AVISAR em vez de fingir que sabe o alvo.
FALLBACK_SPLIT = {
    "opaco_pct": 0.34,
    "fim_pct": 0.51,
    "curva": "smooth",
    "folga_topo_pct": None,
    "percentil_cabeca": 5,
    "amostras_por_s": 4,
    "escala_max": 1.08,
    "margem_queixo_pct": 0.05,
    "perda_base_max_pct": 0.36,
    "encaixar_no_corte": True,
}

MOTIVOS = ("cabeca-ja-baixa", "deslocamento", "deslocamento+escala", "herdado",
           "manual", "janela-unica", "nao-resolvido")


def log(m):
    print(m, file=sys.stderr)


# ───────────────────────────────────────────────────────── a máscara e a conta

def alpha_broll(y, y_op, y_fim, curva="smooth"):
    """Alpha do b-roll na linha `y`, 0..1. A MESMA rampa do split-broll.py."""
    t = (y - y_op) / max(y_fim - y_op, 1e-6)
    t = min(max(t, 0.0), 1.0)
    if curva == "smooth":
        t = t * t * (3 - 2 * t)
    return 1.0 - t


def geometria(altura, split):
    """As quatro alturas em px de saída derivadas da máscara do perfil."""
    y_op = altura * float(split["opaco_pct"])
    y_fim = altura * float(split["fim_pct"])
    folga_pct = split.get("folga_topo_pct")
    folga = None if folga_pct is None else altura * float(folga_pct)
    return {"y_op": y_op, "y_fim": y_fim,
            "folga": folga,
            "alvo": None if folga is None else y_fim + folga}


def resolver_par(c, q, altura, geo, split, escala_max=None):
    """A forma fechada do §3.2, com os cinco guardas. Não lê disco, não roda
    ffmpeg: é a função que o teste exercita com tabela.

    `c` = topo da cabeça na base (px, o percentil da cabeça MAIS ALTA)
    `q` = queixo/ombro na base (px) ou None (guarda 4 fica NÃO VERIFICADO)
    """
    y_op, alvo = geo["y_op"], geo["alvo"]
    z_max = float(split["escala_max"] if escala_max is None else escala_max)
    out = {"avisos": [], "guardas": {}}

    s_ideal = alvo - c
    if s_ideal <= 0:
        S, z, motivo = 0.0, 1.0, "cabeca-ja-baixa"
    elif s_ideal <= y_op:
        S, z, motivo = s_ideal, 1.0, "deslocamento"
    else:
        # guarda 1: S nunca passa de y_op — acima disso sobraria preto onde a
        # máscara já deixa a base aparecer. É a checagem que já existia em
        # split-broll.py:65-68, agora como restrição do solver.
        S, z, motivo = y_op, (alvo - y_op) / max(c, 1e-6), "deslocamento+escala"

    # guarda 3: teto de escala. NUNCA `min(z, z_max)` em silêncio: isso é o clamp
    # que transforma medição-lixo em recorte plausível e errado (SKILL.md:52).
    out["guardas"]["escala"] = {"z": z, "teto": z_max, "ok": z <= z_max + 1e-9}

    # guarda 4: o queixo não pode encostar no pé do quadro.
    if q is None:
        out["guardas"]["queixo"] = {"ok": None, "por_que": "queixo não medido"}
    else:
        limite = altura * (1.0 - float(split["margem_queixo_pct"]))
        while q * z + S > limite and S > 0:
            S = max(0.0, S - 1.0)
        out["guardas"]["queixo"] = {"queixo_saida": q * z + S, "limite": limite,
                                    "ok": q * z + S <= limite + 1e-9}

    cabeca_saida = c * z + S
    # guarda 2: o objetivo. Depois do guarda 4 mexer em S ele pode não fechar.
    out["guardas"]["alvo"] = {"cabeca_saida": cabeca_saida, "alvo": alvo,
                              "ok": cabeca_saida >= alvo - 1.0}

    # guarda 5: quanto da base se joga fora pelo pé.
    perda = 1.0 - (altura - S) / (altura * z)
    teto_perda = float(split["perda_base_max_pct"])
    out["guardas"]["perda_base"] = {"perda": perda, "teto": teto_perda,
                                    "ok": perda <= teto_perda + 1e-9}

    out.update({"deslocamento_px": S, "escala": z, "motivo": motivo,
                "cabeca_saida": cabeca_saida, "perda_base_pct": perda,
                "alpha_broll_previsto": alpha_broll(
                    cabeca_saida, geo["y_op"], geo["y_fim"], split.get("curva", "smooth"))})
    return out


def fim_pct_que_cabe(c, altura, split, teto_perda):
    """Que `fim_pct` traria a perda de base para dentro do teto — a curva de
    troca que o guarda 5 imprime em vez de decidir sozinho. Bisseção porque a
    relação passa por dois ramos (deslocamento puro × deslocamento+escala)."""
    lo, hi = float(split["opaco_pct"]), float(split["fim_pct"])
    for _ in range(40):
        meio = (lo + hi) / 2
        s2 = dict(split); s2["fim_pct"] = meio
        r = resolver_par(c, None, altura, geometria(altura, s2), s2)
        if r["perda_base_pct"] <= teto_perda:
            lo = meio
        else:
            hi = meio
    return lo


# ────────────────────────────────────────────────────────────────── a medição

def _probe(caminho, campos, contar=False):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if contar:
        cmd.append("-count_frames")
    cmd += ["-show_entries", "stream=" + campos, "-of", "default=nk=1:nw=1", caminho]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()


def sha1_8(caminho):
    h = hashlib.sha1()
    with open(caminho, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:8]


def ler_frames_cinza(video, indices, larg, alt):
    """Lê SÓ os frames pedidos (filtro select), como numpy uint8 HxW."""
    import numpy as np
    if not indices:
        return []
    sel = "+".join("eq(n\\,%d)" % i for i in indices)
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", video,
         "-vf", "select='%s'" % sel, "-vsync", "0",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = larg * alt
    return [np.frombuffer(raw[k * n:(k + 1) * n], dtype="uint8").reshape(alt, larg)
            for k in range(len(raw) // n)]


def medir_quadro(alpha, larg, alt):
    """topo da cabeça, queixo/ombro e área, de UM frame de matte alpha.

    Devolve `None` no topo quando não há pessoa sustentada — quem decide o que
    fazer com isso é a regra de rejeição, nunca esta função.
    """
    import numpy as np
    linhas = (alpha >= PESSOA_LIM).sum(1)
    area = float(linhas.sum()) / (larg * alt)
    lim = max(1, int(FRACAO_LARGURA_CABECA * larg))
    topo, seguidas = None, 0
    for y in range(alt):
        if linhas[y] >= lim:
            seguidas += 1
            if seguidas >= LINHAS_SUSTENTADAS:
                topo = y - LINHAS_SUSTENTADAS + 1
                break
        else:
            seguidas = 0
    queixo = None
    if topo is not None:
        r1 = topo + int(FAIXA_LARGURA_CABECA[0] * alt)
        r2 = topo + int(FAIXA_LARGURA_CABECA[1] * alt)
        if r2 < alt and r2 > r1:
            w_cab = float(np.median(linhas[r1:r2]))
            alvo_w = FATOR_OMBRO * w_cab
            achou = np.nonzero(linhas[r2:] >= alvo_w)[0]
            queixo = int(r2 + achou[0]) if len(achou) else None
        if queixo is None:
            nz = np.nonzero(linhas >= lim)[0]
            queixo = int(nz[-1]) if len(nz) else None
    return {"topo": None if topo is None else int(topo),
            "queixo": queixo, "area": area}


def rodar_matte(base, t0, t1, dir_saida, forcar=False):
    """Chama o matte.py da SPEC-03. Sem ele, não se adivinha: exige --cabeca-y."""
    matte = os.path.join(AQUI, "matte.py")
    if not os.path.isfile(matte):
        sys.exit("matte.py não existe em %s — o medidor desta spec é ele (SPEC-03).\n"
                 "Enquanto não aterrissar, passe `--cabeca-y <px>` por segmento: o "
                 "plano grava medidor \"manual\" e ninguém finge medição." % AQUI)
    os.makedirs(dir_saida, exist_ok=True)
    cmd = [sys.executable, matte, base, "--ini", "%.6f" % t0, "--fim", "%.6f" % t1,
           "--saida", dir_saida, "--formato", "alpha"]
    if forcar:
        cmd.append("--forcar")
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode:
        sys.exit("matte.py falhou (%d). Sem medição não há plano: use `--cabeca-y`."
                 % r.returncode)
    art = r.stdout.strip().splitlines()[-1]
    with open(os.path.join(dir_saida, "matte.json")) as fh:
        meta = json.load(fh)
    return art, meta


# ───────────────────────────────────────────────────── a janela e os segmentos

def fronteiras_reais(dir_prod):
    """[start_s de cada segmento] + [total_s], contadas em FRAMES dos segs/.

    Nunca `Σ(end−start)` da EDL: no material do estudo isso erra 37 ms no começo
    e 97 ms no fim — o suficiente para o layout trocar num frame em que a imagem
    ainda é do take anterior. É o mesmo anti-pattern do qc-emendas-asr.py:57-61.
    """
    try:
        import edl_io
    except ImportError:
        return None, None, "sem-edl_io"
    if not os.path.isfile(edl_io.caminho(dir_prod)):
        return None, None, "sem-edl"
    tl = edl_io.timeline(dir_prod, exigir=False)
    fonte = "timeline_real"
    if not tl:
        try:
            tl = edl_io.medir_timeline(dir_prod)
            fonte = "timeline_real(medida-agora)"
        except SystemExit as e:
            log(">> timeline real indisponível (%s) — janela única" % e)
            return None, None, "sem-timeline"
    return edl_io.fronteiras(tl), tl, fonte


def encaixar(t, fronteiras, fps):
    """A fronteira de segmento mais próxima e a distância até ela."""
    melhor = min(fronteiras, key=lambda f: abs(f - t))
    return melhor, abs(melhor - t)


# ──────────────────────────────────────────────────────────────────────── main

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("dir")
    ap.add_argument("--janela", nargs=2, type=float, required=True, metavar=("T0", "T1"))
    ap.add_argument("--base", default="v1-montado.mp4")
    ap.add_argument("--saida", default="split-plano.json")
    ap.add_argument("--cabeca-y", type=float, action="append", default=None,
                    help="topo da cabeça em px (medidor manual). 1 valor = todos "
                         "os segmentos; N valores = um por segmento na ordem")
    ap.add_argument("--queixo-y", type=float, action="append", default=None)
    ap.add_argument("--percentil", type=int, default=None)
    ap.add_argument("--escala-max", type=float, default=None)
    ap.add_argument("--forcar", action="store_true",
                    help="aceita perda de base acima do teto do perfil (guarda 5)")
    ap.add_argument("--sem-encaixe", action="store_true")
    ap.add_argument("--simular-falha-seg", action="append", default=None,
                    help="TESTE: zera a medição do segmento i (ou `todos`) para "
                         "exercitar a regra de rejeição sem esperar um matte ruim")
    ap.add_argument("--refazer-matte", action="store_true")
    a = ap.parse_args()

    d = os.path.abspath(a.dir)
    base = a.base if os.path.isabs(a.base) else os.path.join(d, a.base)
    if not os.path.isfile(base):
        sys.exit("base não existe: %s" % base)

    P = perfil_mod.carregar(d, quieto=True)
    largura, altura = int(P["video"]["largura"]), int(P["video"]["altura"])
    bw, bh = (int(x) for x in _probe(base, "width,height")[:2])
    if (bw, bh) != (largura, altura):
        log(">> a base é %dx%d e o perfil diz %dx%d — adotando a BASE (é sobre ela "
            "que a máscara vai cair, pixel a pixel)" % (bw, bh, largura, altura))
        largura, altura = bw, bh
    taxa = (_probe(base, "r_frame_rate") or ["0/1"])[0]
    num, den = (taxa.split("/") + ["1"])[:2]
    fps = float(num) / float(den)

    split = dict(FALLBACK_SPLIT)
    bruto = P.get("split", "ausente")
    if bruto is None:
        sys.exit("o perfil %r tem `split: null` — este tipo de peça não usa "
                 "split-screen de propósito (cobrir o topo de um screencast é "
                 "esconder a demonstração)." % P.get("nome"))
    if bruto == "ausente":
        log(">> perfil sem bloco `split` — usando o FALLBACK congelado (o "
            "comportamento de hoje). Rode `perfil.py patch --bloco split`.")
    else:
        split.update({k: v for k, v in bruto.items() if not k.startswith("_")})
    if a.percentil is not None:
        split["percentil_cabeca"] = a.percentil

    geo = geometria(altura, split)
    if geo["alvo"] is None:
        sys.exit("`split.folga_topo_pct` não está no perfil: sem ela não existe alvo "
                 "e o deslocamento voltaria a ser um número escolhido a dedo — que é "
                 "exatamente o defeito. Rode `perfil.py patch --bloco split`.")
    log(">> máscara: opaca até y=%.1f · alpha zero em y=%.1f · alvo da cabeça y=%.1f "
        "(folga %.1f px)" % (geo["y_op"], geo["y_fim"], geo["alvo"], geo["folga"]))

    # ── a janela encaixa no corte REAL ───────────────────────────────────────
    t0_ped, t1_ped = float(a.janela[0]), float(a.janela[1])
    if t1_ped <= t0_ped:
        sys.exit("janela vazia: t1 (%.3f) <= t0 (%.3f)" % (t1_ped, t0_ped))
    fr, tl, fonte = fronteiras_reais(d)
    t0, t1 = t0_ped, t1_ped
    fonte_encaixe = "pedido"
    if fr and split.get("encaixar_no_corte", True) and not a.sem_encaixe:
        um_frame = 1.0 / fps
        for rotulo, t in (("t0", t0_ped), ("t1", t1_ped)):
            alvo_f, dist = encaixar(t, fr, fps)
            if dist > ENCAIXE_MAX_S:
                sys.exit(
                    "JANELA ERRADA: %s pedido em %.3f s está a %.3f s da fronteira de "
                    "segmento mais próxima (%.5f s). Meio segundo não é arredondamento "
                    "— é a janela errada.\nFronteiras reais (frames dos segs/): %s"
                    % (rotulo, t, dist, alvo_f,
                       ", ".join("%.5f" % f for f in fr)))
            if rotulo == "t0":
                t0 = alvo_f
            else:
                t1 = alvo_f
            if dist > um_frame:
                log(">> %s: %.3f → %.5f (%.0f ms, %.1f frames) — encaixado na fronteira "
                    "real" % (rotulo, t, alvo_f, dist * 1000, dist * fps))
        fonte_encaixe = fonte
    elif not fr:
        log(">> sem timeline real (%s) — a janela fica como foi pedida" % fonte)

    # ── quais segmentos a janela cobre ───────────────────────────────────────
    janela_unica = fr is None
    if janela_unica:
        blocos = [{"i": 0, "t0": t0, "t1": t1}]
    else:
        blocos = []
        for i in range(len(fr) - 1):
            a0, a1 = max(fr[i], t0), min(fr[i + 1], t1)
            if a1 - a0 > 0.5 / fps:
                blocos.append({"i": i, "t0": a0, "t1": a1})
        if not blocos:
            sys.exit("a janela %.3f–%.3f não cobre segmento nenhum" % (t0, t1))
    log(">> janela %.5f–%.5f s · %d segmento(s): %s"
        % (t0, t1, len(blocos), ", ".join("seg%d" % b["i"] for b in blocos)))

    # ── medição ──────────────────────────────────────────────────────────────
    falhar = set()
    if a.simular_falha_seg:
        for s in a.simular_falha_seg:
            if str(s).lower() == "todos":
                falhar = {b["i"] for b in blocos}
            else:
                falhar.add(int(s))
        log(">> SIMULAÇÃO: medição zerada em %s"
            % ", ".join("seg%d" % i for i in sorted(falhar)))

    passo = 1.0 / float(split["amostras_por_s"])
    medidor = {"amostras_por_s": split["amostras_por_s"]}
    if a.cabeca_y:
        medidor.update({"nome": "manual", "engine": None})
        log(">> medidor MANUAL: %s px" % ", ".join("%.0f" % v for v in a.cabeca_y))
        for k, b in enumerate(blocos):
            v = a.cabeca_y[min(k, len(a.cabeca_y) - 1)]
            q = a.queixo_y[min(k, len(a.queixo_y) - 1)] if a.queixo_y else None
            b["amostras"] = [{"t": (b["t0"] + b["t1"]) / 2, "topo": v,
                              "queixo": q, "area": None}]
    else:
        art, meta = rodar_matte(base, t0, t1, os.path.join(d, ".split-matte"),
                                forcar=a.refazer_matte)
        medidor.update({"nome": "matte", "engine": meta["engine"]["nome"],
                        "artefato": os.path.basename(art),
                        "fonte_sha1_8": meta["fonte_sha1_8"]})
        ini_frame, n_frames = meta["janela"]["ini_frame"], meta["janela"]["n_frames"]
        mw = int(meta["formato"]["largura"]); mh = int(meta["formato"]["altura"])
        pedidos, mapa = [], []
        for b in blocos:
            t = b["t0"]
            b["_idx"] = []
            while t < b["t1"] - 1e-9:
                k = int(round(t * fps)) - ini_frame
                if 0 <= k < n_frames and k not in b["_idx"]:
                    b["_idx"].append(k)
                    pedidos.append(k)
                    mapa.append((b, k, (ini_frame + k) / fps))
                t += passo
        pedidos_ord = sorted(set(pedidos))
        log(">> lendo %d frames do matte (de %d na janela) — %.1f amostras/s"
            % (len(pedidos_ord), n_frames, split["amostras_por_s"]))
        quadros = ler_frames_cinza(art, pedidos_ord, mw, mh)
        if len(quadros) != len(pedidos_ord):
            sys.exit("o matte devolveu %d frames para %d pedidos — não dá para medir "
                     "com um mapa furado" % (len(quadros), len(pedidos_ord)))
        por_indice = dict(zip(pedidos_ord, quadros))
        for b in blocos:
            b["amostras"] = []
            for k in b["_idx"]:
                m = medir_quadro(por_indice[k], mw, mh)
                m["t"] = round((ini_frame + k) / fps, 6)
                b["amostras"].append(m)
            b.pop("_idx", None)

    # A simulação zera a MEDIÇÃO, nunca o resultado: o defeito plantado tem que
    # entrar pela mesma porta por onde entra um matte ruim de verdade, senão o
    # teste prova só que a flag existe.
    for b in blocos:
        if b["i"] in falhar:
            b["amostras"] = [{"t": s["t"], "topo": None, "queixo": None, "area": 0.0}
                             for s in b["amostras"]]

    # ── rejeição, com nome ───────────────────────────────────────────────────
    for b in blocos:
        aceitos, rejeitados = [], []
        topos = [s["topo"] for s in b["amostras"]]
        for j, s in enumerate(b["amostras"]):
            razao = None
            # a área vem ANTES do "não achou cabeça": quando o matte zera, as duas
            # coisas são verdade e a razão útil é a que diz POR QUE não achou.
            if s["area"] is not None and s["area"] < REJ_AREA_MIN:
                razao = "area<%d%%" % round(REJ_AREA_MIN * 100)
            elif s["area"] is not None and s["area"] > REJ_AREA_MAX:
                razao = "area>%d%%" % round(REJ_AREA_MAX * 100)
            elif s["topo"] is None:
                razao = "sem-pessoa"
            elif s["topo"] < REJ_TOPO_MIN * altura:
                razao = "topo-na-borda"
            elif s["topo"] > REJ_TOPO_MAX * altura:
                razao = "topo-abaixo-do-meio"
            else:
                viz = [t for t in topos[max(0, j - 2):j + 3] if t is not None]
                if len(viz) >= 3 and abs(s["topo"] - statistics.median(viz)) > REJ_SALTO * altura:
                    razao = "salto>%d%%" % round(REJ_SALTO * 100)
            if razao:
                rejeitados.append({"t": s["t"], "razao": razao})
            else:
                aceitos.append(s)
        b["aceitos"], b["rejeitados"] = aceitos, rejeitados

    # ── solver por segmento ──────────────────────────────────────────────────
    p = int(split["percentil_cabeca"])
    resolvidos, pendentes = [], []
    for b in blocos:
        n = len(b["amostras"])
        nrej = len(b["rejeitados"])
        if not b["aceitos"] or (n and nrej / n > REJ_FRACAO_SEGMENTO):
            razoes = {}
            for r in b["rejeitados"]:
                razoes[r["razao"]] = razoes.get(r["razao"], 0) + 1
            b["_falhou"] = "%d/%d samples rejeitados (%s)" % (
                nrej, n, ", ".join("%s×%d" % (k, v) for k, v in sorted(razoes.items())))
            pendentes.append(b)
            continue
        topos = sorted(s["topo"] for s in b["aceitos"])
        queixos = sorted(s["queixo"] for s in b["aceitos"] if s["queixo"] is not None)
        c = _percentil(topos, p)
        q = _percentil(queixos, 100 - p) if queixos else None
        r = resolver_par(c, q, altura, geo, split, a.escala_max)
        r.update({"cabeca_p%d" % p: c, "cabeca_mediana": statistics.median(topos),
                  "queixo_p%d" % (100 - p): q})
        b["res"] = r
        b["c"], b["q"] = c, q
        resolvidos.append(b)

    if not resolvidos:
        nomes = "; ".join("seg%d: %s" % (b["i"], b["_falhou"]) for b in pendentes)
        log("NENHUM segmento resolveu — %s" % nomes)
        sys.exit("nenhum (S, z) tem medição por trás. O plano NÃO foi escrito: um "
                 "deslocamento inventado é pior que nenhum. Caminhos reais: "
                 "`--cabeca-y <px>` por segmento (vira medidor \"manual\") ou refazer "
                 "o matte com --refazer-matte.")

    # guarda 3 — teto de escala. Exit 1, e nada é gravado.
    estourou = [b for b in resolvidos if not b["res"]["guardas"]["escala"]["ok"]]
    if estourou:
        b = estourou[0]
        g = b["res"]["guardas"]["escala"]
        sys.exit(
            "TETO DE ESCALA (motivo: \"teto\"): seg%d exige escala %.3f e o teto é "
            "%.3f.\nO dispositivo não serve para este plano do jeito que está. Duas "
            "saídas REAIS:\n"
            "  1. faixa de b-roll mais fina — `split.fim_pct` menor que %.3f (hoje o "
            "alvo da cabeça é y=%.0f; cada 1%% da altura a menos no `fim_pct` desce o "
            "alvo em %.0f px);\n"
            "  2. reenquadrar o segmento na EDL (zoom/cx/cy) e remontar, para a cabeça "
            "já nascer mais baixa no montado.\n"
            "Nenhum frame foi renderizado e o plano não foi escrito."
            % (b["i"], g["z"], g["teto"], float(split["fim_pct"]), geo["alvo"],
               altura * 0.01))

    # herança: os pendentes ficam com a MEDIANA dos que resolveram.
    if pendentes:
        med_s = statistics.median([b["res"]["deslocamento_px"] for b in resolvidos])
        med_z = statistics.median([b["res"]["escala"] for b in resolvidos])
        de = ",".join("seg%d" % b["i"] for b in resolvidos)
        for b in pendentes:
            log("seg%d: %s — herdou S=%.0f z=%.3f da mediana de %s"
                % (b["i"], b["_falhou"], med_s, med_z, de))
            b["res"] = {"deslocamento_px": med_s, "escala": med_z, "motivo": "herdado",
                        "cabeca_saida": None, "perda_base_pct":
                        1.0 - (altura - med_s) / (altura * med_z),
                        "alpha_broll_previsto": None, "avisos": [],
                        "guardas": {"herdado_de": de}}
            b["c"] = b["q"] = None

    ordem = sorted(resolvidos + pendentes, key=lambda b: b["t0"])

    # guarda 5 — perda de base. Avisa SEMPRE; bloqueia sem --forcar.
    avisos = []
    acima = []
    for b in ordem:
        pb = b["res"]["perda_base_pct"]
        teto = float(split["perda_base_max_pct"])
        if pb > teto + 1e-9:
            avisos.append("seg%d: perda_base %.1f%% acima do teto do perfil (%.1f%%) — "
                          "é essa fração do pé do quadro que sai de cena"
                          % (b["i"], pb * 100, teto * 100))
            acima.append(b)
        elif pb > teto - 0.01:
            avisos.append("seg%d: perda_base %.1f%% encosta no teto do perfil (%.1f%%)"
                          % (b["i"], pb * 100, teto * 100))
    if acima and not a.forcar:
        c_ruim = min(b["c"] for b in acima if b.get("c") is not None) \
            if any(b.get("c") is not None for b in acima) else None
        sugestao = ""
        if c_ruim is not None:
            novo = fim_pct_que_cabe(c_ruim, altura, split,
                                    float(split["perda_base_max_pct"]))
            sugestao = ("\nA troca, medida: com `split.fim_pct` = %.3f (hoje %.3f) a "
                        "perda cabe no teto — a faixa de b-roll fica %.0f px mais fina."
                        % (novo, float(split["fim_pct"]),
                           altura * (float(split["fim_pct"]) - novo)))
        log("\n".join(avisos))
        sys.exit(
            "PERDA DE BASE acima do teto em %d segmento(s). Isto é decisão EDITORIAL, "
            "não detalhe técnico: ir de 25%% para %.0f%% joga fora mais pé de quadro "
            "(na peca-01, a mesa inteira).%s\n"
            "Se a peça aguenta, rode de novo com --forcar. O script avisa; quem decide "
            "é você." % (len(acima), max(b["res"]["perda_base_pct"] for b in acima) * 100,
                         sugestao))
    for m in avisos:
        log(">> " + m)

    # ── o artefato ───────────────────────────────────────────────────────────
    segmentos = []
    for b in ordem:
        r = b["res"]
        item = {
            "i": b["i"], "t0": round(b["t0"], 6), "t1": round(b["t1"], 6),
            "samples": len(b.get("aceitos", [])),
            "samples_rejeitados": b["rejeitados"],
            "cabeca_p%d" % p: b.get("c"),
            "cabeca_mediana": r.get("cabeca_mediana"),
            "queixo_p%d" % (100 - p): b.get("q"),
            "deslocamento_px": int(round(r["deslocamento_px"])),
            "deslocamento_pct": round(r["deslocamento_px"] / altura, 4),
            "escala": round(r["escala"], 4),
            "cabeca_saida": None if r["cabeca_saida"] is None else round(r["cabeca_saida"], 1),
            "alpha_broll_previsto": None if r["alpha_broll_previsto"] is None
            else round(r["alpha_broll_previsto"], 5),
            "perda_base_pct": round(r["perda_base_pct"], 4),
            "motivo": ("janela-unica" if (janela_unica and r["motivo"] != "herdado")
                       else ("manual" if medidor["nome"] == "manual"
                             and r["motivo"] != "herdado" else r["motivo"])),
            "motivo_solver": r["motivo"],
            "guardas": r["guardas"],
        }
        segmentos.append(item)

    plano = {
        "schema": SCHEMA,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base": os.path.basename(base),
        "base_sha1_8": sha1_8(base),
        "formato": {"largura": largura, "altura": altura, "fps": taxa},
        "perfil": P.get("nome"),
        "mascara": {"opaco_pct": float(split["opaco_pct"]),
                    "fim_pct": float(split["fim_pct"]),
                    "curva": split.get("curva", "smooth"),
                    "y_op": round(geo["y_op"], 1), "y_fim": round(geo["y_fim"], 1),
                    "alvo": round(geo["alvo"], 1)},
        "medidor": medidor,
        "janela": {"t0_pedido": t0_ped, "t1_pedido": t1_ped,
                   "t0": round(t0, 6), "t1": round(t1, 6),
                   "fonte_do_encaixe": fonte_encaixe},
        "segmentos": segmentos,
        "avisos": avisos,
    }
    saida = a.saida if os.path.isabs(a.saida) else os.path.join(d, a.saida)
    with open(saida, "w", encoding="utf-8") as fh:
        json.dump(plano, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for s in segmentos:
        log(">> seg%d: S=%d px (%.1f%%) z=%.3f cabeça→%s motivo %s%s"
            % (s["i"], s["deslocamento_px"], s["deslocamento_pct"] * 100, s["escala"],
               "?" if s["cabeca_saida"] is None else "%.0f" % s["cabeca_saida"],
               s["motivo"],
               "" if not s["samples_rejeitados"] else
               " (%d rejeitado(s))" % len(s["samples_rejeitados"])))
    print(os.path.abspath(saida))
    return 0


def _percentil(vals, p):
    """Percentil por interpolação linear, sem numpy (o solver roda sem ele)."""
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return float(v[0])
    k = (len(v) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(v[int(k)])
    return float(v[lo]) * (hi - k) + float(v[hi]) * (k - lo)


if __name__ == "__main__":
    sys.exit(main())
