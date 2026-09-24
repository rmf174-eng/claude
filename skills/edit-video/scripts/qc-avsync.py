#!/usr/bin/env python3
"""qc-avsync.py — o vale de energia do áudio cai NA fronteira de frames do vídeo?

    qc-avsync.py <dir-producao> [--video v1-montado.mp4] [--alvo-ms N]
                                [--janela-ms 80] [--json]

    exit 0  dentro do alvo, sem tendência
         1  FALHA (mediana fora do alvo, tendência, ou GAP em junção J-cut)
         2  uso / insumo
         3  nenhuma fronteira com marcador — NÃO VERIFICADO, jamais "ok"

POR QUE ISTO EXISTE
A `edit-video/SKILL.md` declara esta medição OBRIGATÓRIA em toda produção de
talking-head — "vale de energia do áudio em cada emenda vs a fronteira de frames
do vídeo → ±3 ms sem tendência" — e ela **não existia em código**. Na prática o
teste era refeito à mão, ou não era feito. É o buraco que a bateria de QC
(SPEC-12) tornou visível: um item obrigatório sem script é silêncio, e silêncio
não é aprovação.

O QUE ELE PEGA, E QUE NENHUM OUTRO QC PEGA
O bug de 2026-07-25 (produção `peca-03`): o áudio chegava progressivamente
atrasado porque cada segmento carregava sua própria trilha AAC e o `concat`
acumulava delay de encoder. O sintoma não é um offset grande; é um offset que
CRESCE — +0,04 s na primeira metade, +0,17 s na segunda. Por isso o veredito tem
duas pernas: a mediana E a tendência (regressão do offset contra o índice da
emenda). Um vídeo com offset constante de 2 ms está certo; um com mediana 1 ms e
slope crescente está quebrado.

DUAS ARMADILHAS, AS DUAS JÁ MEDIDAS NESTE REPO

1. 🔴 **Nunca some `end − start` da EDL para achar a fronteira.** O render
   arredonda cada segmento para frame e o erro acumula sempre no mesmo sentido:
   medido em `creator-2/peca-03`, a última fronteira fica **353 ms** curta. Amostrar
   ali é medir o segmento seguinte e inventar um vale que não existe. As
   fronteiras vêm de `edl_io.fronteiras()` — frames REAIS / fps.
2. 🔴 **Fronteira sem marcador não é fronteira aprovada.** Junção contígua no
   mesmo `src` não tem descontinuidade de áudio; com `ritmo.fade_modo =
   so-descontinuidade` a maioria das junções não tem micro-fade nenhum. Ali não
   existe vale para achar, e o mínimo da janela seria a sílaba que estiver
   passando. Essas fronteiras entram em `sem_marcador`, NUNCA em `ok`. Se
   nenhuma tiver marcador, o exit é 3.

RESOLUÇÃO DA MEDIÇÃO, E O ESTIMADOR QUE FOI DESCARTADO (medido em 2026-08-08)
Envelope RMS com **hop de 1 ms** (não de 10): sem hop fino não dá para afirmar
nada sobre ±3 ms.

🔴 O jeito óbvio — `argmin` do envelope, refinado por parábola — é um estimador
**ENVIESADO**, e o viés é grande o bastante para tornar o alvo de ±3 ms
estruturalmente inalcançável. Quando os dois lados do corte têm níveis
diferentes (o normal: fala de um lado, ar do outro), a janela de RMS borra a
energia do lado alto para dentro do vale e o mínimo é PUXADO para o lado
silencioso. Medido numa peça sintética, nas duas únicas junções não-contíguas,
variando só a largura da janela:

    janela 10 ms → offsets +5,37 / −5,50 ms   (mediana |.| 5,44)
    janela  5 ms → offsets +2,81 / −2,98 ms   (mediana |.| 2,90)
    janela  3 ms → offsets +1,84 / −2,44 ms   (mediana |.| 2,14)
    janela  1 ms → offsets +0,91 / −1,93 ms   (mediana |.| 1,42)

O viés escala com a largura da janela — ou seja, ele é do MEDIDOR, não do render.
Um QC assim reprovaria montagem correta e, pior, o número que ele imprime não
mede sincronia: mede assimetria de nível.

O estimador que ficou é o **cruzamento dos dois lados**: o micro-fade de
`ritmo.fade_borda_s` é simétrico por construção (`audio-exato.py` aplica o mesmo
nas duas bordas), então a última vez em que o lado ESQUERDO está a menos de
`--queda-db` do platô DELE e a primeira vez em que o lado DIREITO está a menos de
`--queda-db` do platô DELE são simétricas em torno da junção — cada lado
normalizado pelo próprio nível. O ponto médio das duas é a estimativa. Nas mesmas
duas junções: **−0,02 / −0,02 ms** com janela de 5 ms.

O `offset_vale_ms` (o estimador antigo) continua no JSON, ao lado do que vale, de
propósito: a diferença entre os dois é a assimetria de nível daquele corte, e é
melhor tê-la à vista do que escondida. E `largura_vale_ms` denuncia fade
assimétrico, que é a única premissa do estimador novo.

# Mecanismo derivado de uma verificação de corte lida em ferramenta de
# terceiro (junção sob J-cut: quando há
# encavalamento não existe corte de áudio, e o teste vira a continuidade do
# encavalamento — o que entra tem que começar antes de o que sai terminar).
# Cópia de leitura em tools/referencias/.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

CONTRATO = "benchmark.qc-avsync/v1"
WIN_S = 0.005          # FÍSICA: janela de RMS de 5 ms (ver o bloco do docstring)
HOP_S = 0.001          # FÍSICA: hop de 1 ms — a resolução de ±3 ms depende disto
CONTRASTE_MIN_DB = 6.0  # abaixo disto não há vale: não há marcador
QUEDA_DB = 20.0        # quanto o lado precisa cair do próprio platô para "entrou no fade"
R2_TENDENCIA = 0.5


def audio_mono(caminho, sr):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", caminho, "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True).stdout
    if not raw:
        sys.exit("não consegui extrair áudio de %s" % caminho)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def envelope(a, sr, t0, t1):
    """(tempos, dB) do envelope RMS na banda [t0,t1], hop de 1 ms."""
    w = int(WIN_S * sr)
    h = int(HOP_S * sr)
    i0 = max(0, int(t0 * sr))
    i1 = min(len(a), int(t1 * sr) + w)
    if i1 - i0 < w * 2:
        return np.array([]), np.array([])
    n = (i1 - i0 - w) // h + 1
    idx = i0 + np.arange(n) * h
    janelas = np.lib.stride_tricks.sliding_window_view(a[i0:i1], w)[::h][:n]
    rms = np.sqrt((janelas ** 2).mean(axis=1))
    return idx / float(sr) + WIN_S / 2.0, 20 * np.log10(np.maximum(rms, 1e-7))


def vale_parabola(ts, db):
    """O estimador ENVIESADO, mantido só como número de comparação (ver docstring).

    Mínimo do envelope com interpolação parabólica nos 3 pontos em volta. Não é
    ele que decide nada: quando os lados do corte têm níveis diferentes, ele é
    puxado para o lado silencioso em ≈ metade da janela de RMS."""
    k = int(np.argmin(db))
    if k == 0 or k == len(db) - 1:
        return float(ts[k])
    y0, y1, y2 = float(db[k - 1]), float(db[k]), float(db[k + 1])
    den = (y0 - 2 * y1 + y2)
    d = 0.0 if abs(den) < 1e-12 else 0.5 * (y0 - y2) / den
    d = max(-1.0, min(1.0, d))
    return float(ts[k] + d * HOP_S)


def cruzamento(ts, db, queda_db=QUEDA_DB):
    """O estimador QUE DECIDE: ponto médio dos dois cruzamentos, cada lado
    normalizado pelo PRÓPRIO platô.

    🔴 A ÂNCORA É O VALE OBSERVADO, NUNCA A FRONTEIRA NOMINAL. A primeira versão
    deste código partia a janela no `t` esperado e procurava os cruzamentos de lá
    para fora — e era ESTRUTURALMENTE CEGA ao defeito que este QC existe para
    achar. Medido: com 20 ms de atraso plantado (`adelay=20|20`) numa junção, o
    vale inteiro migra para o lado direito de `t`, o lado esquerdo vira platô puro,
    os dois cruzamentos colapsam em `t` e a estimativa saía **−0,02 ms** — verde,
    para um defeito de 20 ms. (O `offset_vale_ms`, o estimador enviesado que este
    substitui, dizia +22,81 ms na mesma junção: quem estava errado era o novo.)
    Ancorado no `argmin`, a mesma medição dá +20,0 ms e reprova.

    Devolve `(t_estimado, largura_do_vale_s)` ou `(None, None)`. A `largura` é o
    que denuncia a única premissa do método: fade simétrico dos dois lados. Fade
    assimétrico enviesa a estimativa em metade da diferença — e aparece aqui como
    uma largura fora de `2×fade_borda_s + janela`."""
    k = int(np.argmin(db))
    esq, dire = db[:k], db[k:]
    if len(esq) < 3 or len(dire) < 3:
        return None, None
    plato_e = float(np.median(esq[: max(3, len(esq) // 2)]))
    plato_d = float(np.median(dire[-max(3, len(dire) // 2):]))
    acima_e = np.nonzero(esq > plato_e - queda_db)[0]
    acima_d = np.nonzero(dire > plato_d - queda_db)[0]
    if not len(acima_e) or not len(acima_d):
        return None, None
    tE = float(ts[int(acima_e[-1])])
    tD = float(ts[k + int(acima_d[0])])
    return (tE + tD) / 2.0, tD - tE


def regressao(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0, 0.0
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    sx, sy = x.mean(), y.mean()
    den = ((x - sx) ** 2).sum()
    if den < 1e-12:
        return 0.0, 0.0
    slope = ((x - sx) * (y - sy)).sum() / den
    pred = sy + slope * (x - sx)
    ss_res = ((y - pred) ** 2).sum()
    ss_tot = ((y - sy) ** 2).sum()
    r2 = 0.0 if ss_tot < 1e-12 else 1.0 - ss_res / ss_tot
    return float(slope), float(max(0.0, r2))


def plano_jcut(d):
    p = os.path.join(d, "jcut.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as fh:
            return json.load(fh)
    except ValueError:
        return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", default=".")
    ap.add_argument("--video", default=None)
    ap.add_argument("--alvo-ms", type=float, default=None)
    ap.add_argument("--janela-ms", type=float, default=80.0)
    ap.add_argument("--queda-db", type=float, default=QUEDA_DB)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    d = a.dir
    P = perfil_mod.carregar(d, quieto=True)
    sr = int(P["audio"]["sr"])
    alvo = a.alvo_ms if a.alvo_ms is not None else float(
        P.get("qc", {}).get("av_sync_ms", 3.0))
    fade_modo = P.get("ritmo", {}).get("fade_modo")

    segs = edl_io.segmentos(d)
    tl = edl_io.timeline(d, exigir=False)
    if tl is not None:
        fr = edl_io.fronteiras(tl)
        origem = "timeline_real"
    else:
        # sem timeline persistida: MEDE (nunca soma a EDL)
        tl = edl_io.medir_timeline(d)
        fr = edl_io.fronteiras(tl)
        origem = "medida agora (ffprobe -count_frames)"

    video = a.video or "v1-montado.mp4"
    vpath = video if os.path.isabs(video) else os.path.join(d, video)
    if not os.path.exists(vpath):
        print("qc-avsync: %s não existe" % vpath, file=sys.stderr)
        return 2
    sinal = audio_mono(vpath, sr)

    jc = plano_jcut(d)
    jseg = (jc or {}).get("segmentos") or []
    jan = a.janela_ms / 1000.0

    medidas, sem_marcador, flags = [], [], []
    for k in range(len(segs) - 1):
        t = fr[k + 1]
        rot = "%d→%d" % (k, k + 1)
        contigua = (segs[k]["src"] == segs[k + 1]["src"]
                    and abs(segs[k]["end"] - segs[k + 1]["start"]) < 1e-4)
        lead_f = 0
        if k + 1 < len(jseg):
            lead_f = int(jseg[k + 1].get("lead_frames_in", 0) or 0)

        if lead_f > 0:
            # 🔀 J-CUT: não existe corte de áudio aqui. Procurar vale seria medir a
            # sílaba que estiver passando. O teste vira o do ref-A: o áudio que
            # entra tem que começar ANTES de o que sai terminar.
            fps = float(P["video"]["fps"])
            lead_ms = lead_f / fps * 1000.0
            if lead_ms <= 0:
                flags.append({"onde": rot, "tag": "JCUT-GAP",
                              "detalhe": "junção declarada J-cut com lead 0"})
            else:
                medidas.append({"onde": rot, "t": t, "offset_ms": 0.0,
                                "modo": "jcut", "encavalado_ms": round(lead_ms, 1)})
            continue

        if contigua:
            sem_marcador.append({"onde": rot, "t": t, "por_que": "junção contígua"})
            continue

        ts, db = envelope(sinal, sr, t - jan, t + jan)
        if len(db) < 5:
            sem_marcador.append({"onde": rot, "t": t, "por_que": "janela curta"})
            continue
        contraste = float(db.max() - db.min())
        if contraste < CONTRASTE_MIN_DB:
            sem_marcador.append({
                "onde": rot, "t": t,
                "por_que": "contraste %.1f dB < %.0f%s" % (
                    contraste, CONTRASTE_MIN_DB,
                    " (fade_modo %s)" % fade_modo if fade_modo else "")})
            continue
        tc, largura = cruzamento(ts, db, a.queda_db)
        if tc is None:
            sem_marcador.append({"onde": rot, "t": t,
                                 "por_que": "sem platô dos dois lados"})
            continue
        tv = vale_parabola(ts, db)
        off = (tc - t) * 1000.0
        m = {"onde": rot, "t": round(t, 4), "offset_ms": round(off, 2),
             "offset_vale_ms": round((tv - t) * 1000.0, 2),
             "largura_vale_ms": round(largura * 1000.0, 1),
             "modo": "vale", "contraste_db": round(contraste, 1)}
        if abs(off) > a.janela_ms * 0.75:
            # o vale encostou na borda da janela: o offset real pode ser MAIOR do
            # que o medido. Isso é achado, não medição — alargue com --janela-ms.
            m["borda_da_janela"] = True
            flags.append({"onde": rot, "tag": "AVSYNC-FORA-DA-JANELA",
                          "detalhe": "vale a %.1f ms da fronteira, com janela de "
                                     "±%.0f ms — o offset real pode ser maior"
                                     % (off, a.janela_ms)})
        medidas.append(m)

    com = [m for m in medidas if m["modo"] == "vale"]
    offs = [m["offset_ms"] for m in com]
    mediana = float(np.median(np.abs(offs))) if offs else None
    slope, r2 = regressao(list(range(len(offs))), offs) if len(offs) >= 3 else (0.0, 0.0)
    deriva = abs(slope) * max(1, len(offs))

    if mediana is not None and mediana > alvo:
        flags.append({"onde": "peça", "tag": "AVSYNC-MEDIANA",
                      "detalhe": "mediana |offset| %.2f ms > alvo %.1f ms"
                                 % (mediana, alvo)})
    if len(offs) >= 3 and deriva > alvo and r2 > R2_TENDENCIA:
        flags.append({"onde": "peça", "tag": "AVSYNC-TENDENCIA",
                      "detalhe": "slope %+.3f ms/emenda × %d = %.2f ms (r² %.2f) — "
                                 "o offset CRESCE ao longo da peça"
                                 % (slope, len(offs), deriva, r2)})

    resumo = ("%d/%d fronteira(s) com marcador · mediana %s ms · deriva %.2f ms "
              "(r² %.2f)" % (len(com), len(com) + len(sem_marcador) +
                             sum(1 for m in medidas if m["modo"] == "jcut"),
                             "%.2f" % mediana if mediana is not None else "—",
                             deriva, r2))

    doc = {"schema": CONTRATO, "dir": d, "video": video,
           "fronteiras_origem": origem, "alvo_ms": alvo,
           "n_fronteiras": len(segs) - 1,
           "n_com_marcador": len(com),
           "n_jcut": sum(1 for m in medidas if m["modo"] == "jcut"),
           "n_sem_marcador": len(sem_marcador),
           "mediana_abs_ms": None if mediana is None else round(mediana, 2),
           "slope_ms_por_emenda": round(slope, 4), "r2": round(r2, 3),
           "deriva_ms": round(deriva, 2),
           "medidas": medidas, "sem_marcador": sem_marcador, "flags": flags,
           "resumo": resumo}

    if a.json:
        json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        # no máximo 6 linhas: é um QC, não um relatório
        print("qc-avsync · %s · fronteiras: %s · alvo %.1f ms" % (video, origem, alvo))
        print("  varrido: %d fronteira(s) — %d com marcador, %d sem, %d sob J-cut"
              % (len(segs) - 1, len(com), len(sem_marcador), doc["n_jcut"]))
        if com:
            print("  mediana |offset| %.2f ms · slope %+.3f ms/emenda · "
                  "deriva %.2f ms · r² %.2f" % (mediana, slope, deriva, r2))
        for s in sem_marcador[:2]:
            print("  sem marcador %s em %.3fs — %s" % (s["onde"], s["t"], s["por_que"]))
        for f in flags:
            print("  ⚠️ %s %s" % (f["tag"], f["detalhe"]))
        if not com and not doc["n_jcut"]:
            print("  NÃO VERIFICADO: nenhuma fronteira tem marcador de áudio. "
                  "Isto NÃO é aprovação.")

    if flags:
        return 1
    if not com and not doc["n_jcut"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
