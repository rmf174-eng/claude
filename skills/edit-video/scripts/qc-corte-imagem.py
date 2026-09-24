#!/usr/bin/env python3
"""qc-corte-imagem.py — a fronteira que a EDL AFIRMA existe na IMAGEM? (SPEC-26)

    qc-corte-imagem.py <dir-producao> [--video v1-montado.mp4]
                       [--tol-frames 1] [--janela-s 1.5]
                       [--razao-min 11.5] [--razao-cega 3.0]
                       [--altura-analise N] [--cortes-bruto <json>]
                       [--orfao-prefixo] [--sem-filtro-edl] [--json]

    exit 0  nenhuma falha
         1  ao menos uma falha (FRONTEIRA-SEM-IMAGEM, DESLOCAMENTO-SISTEMATICO,
            EDL-VS-SEGS, SEM-CORRESPONDENCIA)
         2  erro de uso
         3  NÃO VERIFICADO — não deu para medir (e isso NUNCA é aprovação)

────────────────────────────────────────────────────────────────────────────
POR QUE ISTO EXISTE

Auditávamos emenda de quatro maneiras (`audit-emendas`, `qc-ataque`,
`qc-fonemas`, `qc-emendas-asr`) e AS QUATRO SÃO PELO ÁUDIO. Nenhum QC deste repo
olhava a fronteira na imagem. Isso deixa em aberto a classe do SEGMENTO ÓRFÃO —
6,25 s de vídeo errado com todos os QCs verdes, porque a trilha de áudio é
montada a partir dos frames reais e sincroniza perfeitamente com a imagem errada.
Uma pergunta ("a imagem muda onde a EDL diz que muda?") pega isso em 5 segundos.

E não é hipótese: `creators/creator-2/producao/ovo-de-pascoa/segs/` tem 22 arquivos
para 21 segmentos na EDL. Um órfão vivo em disco, nesta árvore.

────────────────────────────────────────────────────────────────────────────
AS TRÊS DECISÕES QUE FORAM MEDIDAS, NÃO SUPOSTAS

1. 🔴 LIMIAR ABSOLUTO DE `scdet` NÃO SEPARA. Medido em `ovo-de-pascoa`: o maior
   score FORA de fronteira (2,612) é MAIOR que o menor score EM fronteira
   (2,267). Qualquer `scdet=threshold=X` global produz falso positivo e falso
   negativo na mesma peça. O que separa é a razão contra a VIZINHANÇA LOCAL —
   mesma família do piso local do `bordas.py`. Medido em 4 produções, 8.035
   frames, 83 fronteiras: 81 confirmadas, 0 falso positivo, 0 deslocamento.

2. 🔴 O ÍNDICE É DE DECODIFICAÇÃO, NÃO `round(PTS × fps)`. Em `peca-01`
   (`start_time=0.000000`) as 28 fronteiras caem em F exato pelos dois métodos;
   em `peca-04` (`start_time=0.021029`) `round(t × fps)` desloca as 16 para
   F+1. O `scdet` emite UMA LINHA POR FRAME em ordem de decodificação: enumerar
   as linhas elimina o problema. A checagem `len(linhas) == nb_read_frames` é o
   que torna a enumeração legítima — e é a prova de dentes desta sonda.

3. 🔴 O SILÊNCIO DA SONDA PODE SER O RESULTADO CERTO. Um corte contíguo sem
   reenquadramento não tem mudança de imagem a detectar (controle negativo
   sintético: razão 0,41). Por isso a expectativa é derivada da EDL ANTES de
   olhar o score, e só `esperado_visivel == "sim"` pode virar FALHA. Jump cut de
   mesmo enquadramento é CONFIRMAÇÃO, não detector: 51 de 53 passam do limiar, e
   os 2 que não passam são cortes de 0,56 s e 3,9 s com a pessoa quase parada.

NUNCA SOME `end − start` DA EDL para achar a fronteira. A soma nominal é sempre
MENOR que o render (316,7 ms no fim da `peca-01`). A fonte é a
`timeline_real` (SPEC-05); sem ela, `ffprobe -count_frames` sobre `segs/segNNN`
NA ORDEM DA EDL. E nunca um `glob` de `segs/*.mp4` sem cruzar com a EDL.

Mecanismo modelado de uma ferramenta de edição de terceiro,
references/shortform.md:132-143 (scdet como prova pela imagem) — cópia de leitura
em tools/referencias/. Implementação nossa: razão contra a vizinhança local em vez
de limiar absoluto, expectativa de visibilidade derivada da EDL, e índice por
ordem de decodificação em vez de round(PTS x fps).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                                                        # noqa: E402

CONTRATO = "benchmark.qc-corte-imagem/v1"

# ─── constantes ADIMENSIONAIS (nenhuma descreve o formato da peça) ────────────
# fração da altura do PRÓPRIO vídeo usada na análise. O `scdet` opera sobre o
# quadro reduzido só por custo: a decisão é de tempo de CPU, não de formato.
FRACAO_ANALISE = 0.25
# piso do denominador da razão local: impede razão explosiva em trecho parado,
# onde o p95 da vizinhança tende a zero.
PISO_VIZINHANCA = 0.30
RAZAO_MIN = 11.5          # ≥ → CONFIRMADA          (medido: 81/83 acima)
RAZAO_CEGA = 3.0          # < → a imagem não mudou onde a física garantia sinal
JANELA_S = 1.5            # vizinhança local, em SEGUNDOS (resolvida contra fps)
TOL_FRAMES = 1            # fronteira é índice de frame: não existe meia fronteira
TOL_HERDADO_S = 0.05      # coincidência com corte já existente no bruto

# tolerância de contiguidade: importada do `jcut.py`, que é a definição canônica.
try:
    from jcut import contiguo as _contiguo_jcut, TOL_CONTIGUO
except Exception:                                                    # noqa: BLE001
    TOL_CONTIGUO = 0.002
    _contiguo_jcut = None


class NaoVerificado(Exception):
    """Não deu para medir. NUNCA é aprovação — é exit 3 e bloco próprio."""

    def __init__(self, tag, msg):
        super().__init__(msg)
        self.tag = tag
        self.msg = msg


# ══════════════════════════════════════════ funções PURAS (testáveis sem ffmpeg)

_RE_SCORE = re.compile(r"lavfi\.scd\.score:\s*([-\d.]+)")


def parse_scores(texto):
    """As linhas do `scdet`, POR ORDEM DE APARIÇÃO (§3.3).

    ⚠️ Uma linha por frame, em ordem de decodificação. Nada de converter
    `lavfi.scd.time` para frame: é onde mora o off-by-one de `start_time != 0`.
    Percorre linha a linha de propósito — `re.findall` com `^` e sem `re.M` já
    custou "1 achado de 21 impressos" neste repo."""
    out = []
    for ln in texto.splitlines():
        m = _RE_SCORE.search(ln)
        if m:
            out.append(float(m.group(1)))
    return out


def p95(valores):
    """Percentil 95 por interpolação linear. [] → 0,0."""
    if not valores:
        return 0.0
    s = sorted(valores)
    k = 0.95 * (len(s) - 1)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def razoes(scores, fronteiras, *, w, tol=TOL_FRAMES, piso=PISO_VIZINHANCA):
    """`score[i] / max(p95(vizinhança), piso)` para todo frame.

    A vizinhança é `[i−w, i+w]` EXCLUINDO o próprio `i` e todos os frames a
    ±(tol+1) de QUALQUER fronteira declarada — senão a própria fronteira infla o
    p95 dela e a razão desaba justamente onde ela deveria ser alta."""
    excluidos = set()
    for f in fronteiras:
        for j in range(f - (tol + 1), f + (tol + 1) + 1):
            excluidos.add(j)
    n = len(scores)
    out = []
    for i in range(n):
        viz = [scores[j] for j in range(max(0, i - w), min(n, i + w + 1))
               if j != i and j not in excluidos]
        out.append(scores[i] / max(p95(viz), piso))
    return out


def casar(razs, fronteiras, tol=TOL_FRAMES):
    """Para cada fronteira F: `j = argmax(razao)` em [F−tol, F+tol]."""
    out = []
    for f in fronteiras:
        cand = [(razs[j], j) for j in range(max(0, f - tol),
                                            min(len(razs), f + tol + 1))]
        if not cand:
            out.append({"frame": f, "j": f, "razao": 0.0, "desloc": 0})
            continue
        r, j = max(cand)
        out.append({"frame": f, "j": j, "razao": r, "desloc": j - f})
    return out


def contiguo(a, b):
    """`b` começa onde `a` termina, no mesmo bruto. Importado do `jcut.py`."""
    if _contiguo_jcut is not None:
        try:
            return _contiguo_jcut(a, b)
        except (KeyError, TypeError, ValueError):
            return False
    try:
        return b.get("src") == a.get("src") and \
            abs(float(b["start"]) - float(a["end"])) < TOL_CONTIGUO
    except (KeyError, TypeError, ValueError):
        return False


def _enquadramento(s):
    return (s.get("zoom"), s.get("cx"), s.get("cy"))


def expectativa(anterior, atual):
    """(esperado_visivel, motivo) — classificado ANTES de olhar o score (§3.2).

    É o que separa uma sonda útil de uma máquina de ruído: onde não há mudança de
    imagem a detectar, silêncio é o resultado CERTO."""
    if atual.get("src") != anterior.get("src"):
        return "sim", "src %s → %s" % (anterior.get("src"), atual.get("src"))
    ea, eb = _enquadramento(anterior), _enquadramento(atual)
    if ea != eb:
        return "sim", "reenquadramento %s → %s" % (
            "/".join("%g" % v if isinstance(v, (int, float)) else str(v) for v in ea),
            "/".join("%g" % v if isinstance(v, (int, float)) else str(v) for v in eb))
    if contiguo(anterior, atual):
        return "nao", "contíguo no bruto e mesmo enquadramento"
    return "provavel", "jump cut (mesmo src, mesmo enquadramento)"


def veredito(esperado, razao, *, razao_min=RAZAO_MIN, razao_cega=RAZAO_CEGA):
    """A tabela de §3.2. Só `esperado_visivel == "sim"` pode virar FALHA."""
    if esperado == "nao":
        return "ESPERADO-INVISIVEL"
    if razao >= razao_min:
        return "CONFIRMADA"
    if esperado == "sim":
        return "DUVIDOSA" if razao >= razao_cega else "FRONTEIRA-SEM-IMAGEM"
    return "SEM-MARCADOR"


def tendencia(casamentos):
    """Deslocamento SISTEMÁTICO ou None.

    Uma linha `DESLOCAMENTO-SISTEMATICO +1 (28/28)` em vez de 28 achados:
    deslocamento uniforme é bug de CADEIA (re-encode, timebase, OffthreadVideo);
    deslocamento de uma fronteira só é bug daquela fronteira. Confundir os dois é
    o que faz relatório de QC virar despejo."""
    if not casamentos:
        return None
    ds = {c["desloc"] for c in casamentos}
    if len(ds) == 1:
        d = ds.pop()
        return d if d != 0 else None
    return None


def achados_sem_fronteira(razs, fronteiras, *, razao_min=RAZAO_MIN,
                          tol=TOL_FRAMES):
    """Frames com razão alta FORA de qualquer janela de fronteira declarada."""
    jan = set()
    for f in fronteiras:
        for j in range(f - tol, f + tol + 1):
            jan.add(j)
    return [{"frame": i, "razao": razs[i]}
            for i in range(len(razs)) if razs[i] >= razao_min and i not in jan]


def marcar_herdados(achados, cortes_saida_s, fps, tol_s=TOL_HERDADO_S):
    """Marca `[HERDADO]` o achado que coincide com corte JÁ EXISTENTE no bruto.

    Mesmo mecanismo do `qc-fonemas.py:203-207`: um corte que a creator já tinha
    na câmera dela não é defeito nosso. Sem este cruzamento a sonda acusaria a
    edição de câmera dela como emenda fantasma nossa."""
    for a in achados:
        t = a["frame"] / float(fps)
        perto = [c for c in (cortes_saida_s or []) if abs(c - t) <= tol_s]
        if perto:
            d = min(perto, key=lambda c: abs(c - t))
            a["herdado"] = True
            a["detalhe"] = "coincide com corte do bruto (Δ %.3f s)" % abs(d - t)
        else:
            a.setdefault("herdado", False)
    return achados


# ══════════════════════════════════════════════════════════ medição (com ffmpeg)

def _ffprobe(caminho, campos, contar=False):
    cmd = ["ffprobe", "-v", "error"]
    if contar:
        cmd += ["-count_frames"]
    cmd += ["-select_streams", "v:0", "-show_entries", "stream=" + campos,
            "-of", "default=nw=1:nk=1", caminho]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def probe_video(caminho):
    vals = _ffprobe(caminho, "height,r_frame_rate")
    if len(vals) < 2:
        raise NaoVerificado("SEM-VIDEO", "ffprobe não leu stream de vídeo em %s"
                            % caminho)
    altura = int(vals[0])
    num, den = (vals[1].split("/") + ["1"])[:2]
    fps = int(num) / int(den)
    frames = _ffprobe(caminho, "nb_read_frames", contar=True)
    n = int(frames[0]) if frames and frames[0].isdigit() else 0
    if n <= 0:
        raise NaoVerificado("SEM-VIDEO", "nb_read_frames = 0 em %s" % caminho)
    return {"altura": altura, "fps": fps, "frames": n}


def rodar_scdet(caminho, altura_analise):
    """Uma passada. `threshold=0` serve para EMITIR TODOS OS FRAMES, nunca para
    decidir — a decisão é a razão local. Medimos no domínio do arquivo que o
    consumidor recebe (o mp4 já encodado), reduzido só em escala: comparar pixel
    por igualdade exata depois de um encoder mediria o encoder, e é por isso que
    a régua daqui é RAZÃO contra a vizinhança do próprio arquivo."""
    cmd = ["ffmpeg", "-v", "info", "-nostdin", "-i", caminho, "-an",
           "-vf", "scale=-2:%d,scdet=threshold=0" % altura_analise,
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return parse_scores(r.stderr + "\n" + r.stdout)


def frames_dos_segs(d, segs_esperados, *, permitir_prefixo=False,
                    filtrar_edl=True):
    """`nb_read_frames` de cada `segs/segNNN.mp4` NA ORDEM DA EDL.

    🔴 Nunca `glob` sem cruzar com a EDL, e nunca Σ(end−start)."""
    arquivos = edl_io.segs_ordenados(d)
    if not arquivos:
        raise NaoVerificado("SEM-SEGS", "não há segs/segNNN.mp4 em %s" % d)
    if len(arquivos) != segs_esperados:
        msg = ("%d arquivo(s) em segs/ para %d segmento(s) na EDL"
               % (len(arquivos), segs_esperados))
        if not permitir_prefixo or not filtrar_edl:
            raise NaoVerificado("EDL-VS-SEGS", msg)
        if len(arquivos) < segs_esperados:
            raise NaoVerificado("EDL-VS-SEGS", msg + " — faltam segmentos")
        arquivos = arquivos[:segs_esperados]
    fr = []
    for p in arquivos:
        v = _ffprobe(p, "nb_read_frames", contar=True)
        if not v or not v[0].isdigit() or int(v[0]) <= 0:
            raise NaoVerificado("SEM-SEGS", "segmento sem frames: %s" % p)
        fr.append(int(v[0]))
    return fr


def fronteiras_declaradas(d, video_frames, args):
    """(fronteiras, fonte, aviso) — timeline_real primeiro, segs depois.

    Devolve os índices de frame em que cada segmento a partir do segundo COMEÇA
    na saída. `fronteiras[k−1]` é a emenda entre o segmento k−1 e o k."""
    segs = edl_io.segmentos(d)
    aviso = None
    tl = None
    try:
        tl = edl_io.timeline(d, exigir=False)
    except SystemExit as e:
        raise NaoVerificado("TIMELINE-VELHA", str(e).splitlines()[0])
    if tl is not None:
        f = [s["start_frame"] for s in tl["segments"][1:]]
        if tl["total_frames"] != video_frames:
            aviso = ("timeline_real diz %d frames, o vídeo tem %d"
                     % (tl["total_frames"], video_frames))
        return f, "timeline_real", segs, aviso
    fr = frames_dos_segs(d, len(segs), permitir_prefixo=args.orfao_prefixo,
                         filtrar_edl=not args.sem_filtro_edl)
    if sum(fr) != video_frames:
        # A hipótese "os N primeiros segs são o vídeo" é CONFERIDA contra o
        # próprio arquivo. Sem essa conferência, filtrar pela EDL seria adivinhar.
        raise NaoVerificado(
            "SEM-CORRESPONDENCIA",
            "Σ frames dos segs (%d) != frames do vídeo (%d)" % (sum(fr),
                                                                video_frames))
    acc, out = 0, []
    for n in fr[:-1]:
        acc += n
        out.append(acc)
    return out, "segs-ffprobe", segs, aviso


def cortes_do_bruto_na_saida(caminho_json):
    """Lê a saída do `cortes-do-bruto.py` e devolve os instantes NA SAÍDA.

    Aceita uma lista de números (segundos na saída) ou um objeto com a chave
    `cortes_saida_s`. Formato explícito de propósito: adivinhar em que eixo
    de tempo o número do outro script está é como se marca herdado o que não é."""
    if not caminho_json:
        return None
    with open(caminho_json) as fh:
        doc = json.load(fh)
    if isinstance(doc, list):
        return [float(x) for x in doc]
    for chave in ("cortes_saida_s", "cortes_s", "cortes"):
        if isinstance(doc.get(chave), list):
            return [float(x) for x in doc[chave]]
    raise NaoVerificado("CORTES-ILEGIVEL",
                        "%s não traz lista nem `cortes_saida_s`" % caminho_json)


# ═════════════════════════════════════════════════════════════════════ o comando

def analisar(d, args):
    # `--video` aceita nome relativo à produção OU caminho já resolvido: o
    # catálogo da bateria passa `{video}`, que vem expandido como `{dir}/<nome>`
    # e é RELATIVO quando o `{dir}` é relativo — testar `isabs` não basta.
    video = args.video if os.path.exists(args.video) else os.path.join(d, args.video)
    video_rel = os.path.basename(video)
    if not os.path.exists(video):
        raise NaoVerificado("SEM-VIDEO", "%s não existe" % video)
    info = probe_video(video)
    fps = info["fps"]

    fronteiras, fonte, segs, aviso = fronteiras_declaradas(d, info["frames"], args)

    altura = args.altura_analise or max(2, 2 * int(
        round(info["altura"] * FRACAO_ANALISE / 2)))
    scores = rodar_scdet(video, altura)
    if not scores:
        raise NaoVerificado("SEM-CORRESPONDENCIA",
                            "o scdet não emitiu uma linha sequer")
    if len(scores) != info["frames"]:
        # 🔴 A prova de dentes desta sonda: sem esta igualdade a enumeração das
        # linhas não é índice de frame, e todo o casamento vira ficção.
        raise NaoVerificado(
            "SEM-CORRESPONDENCIA",
            "%d linha(s) do scdet para %d frame(s) do vídeo — a enumeração não é "
            "índice de frame" % (len(scores), info["frames"]))

    w = max(1, int(round(args.janela_s * fps)))
    razs = razoes(scores, fronteiras, w=w, tol=args.tol_frames,
                  piso=PISO_VIZINHANCA)
    cas = casar(razs, fronteiras, tol=args.tol_frames)

    linhas = []
    for k, c in enumerate(cas, start=1):
        esp, motivo = expectativa(segs[k - 1], segs[k])
        est = veredito(esp, c["razao"], razao_min=args.razao_min,
                       razao_cega=args.razao_cega)
        linhas.append({"k": k, "frame": c["frame"],
                       "t_s": round(c["frame"] / fps, 4),
                       "esperado_visivel": esp, "motivo": motivo,
                       "score": round(scores[c["j"]], 3),
                       "razao": round(c["razao"], 2), "desloc": c["desloc"],
                       "estado": est})

    desloc_sist = tendencia(cas)
    sf = achados_sem_fronteira(razs, fronteiras, razao_min=args.razao_min,
                               tol=args.tol_frames)
    for a in sf:
        a["t_s"] = round(a["frame"] / fps, 4)
        a["razao"] = round(a["razao"], 2)
    marcar_herdados(sf, cortes_do_bruto_na_saida(args.cortes_bruto), fps)

    resumo = {
        "esperadas": len(linhas),
        "esperado_visivel_sim": sum(1 for l in linhas
                                    if l["esperado_visivel"] == "sim"),
        "confirmadas": sum(1 for l in linhas if l["estado"] == "CONFIRMADA"),
        "duvidosas": sum(1 for l in linhas if l["estado"] == "DUVIDOSA"),
        "sem_imagem": sum(1 for l in linhas
                          if l["estado"] == "FRONTEIRA-SEM-IMAGEM"),
        "sem_marcador": sum(1 for l in linhas if l["estado"] == "SEM-MARCADOR"),
        "esperado_invisivel": sum(1 for l in linhas
                                  if l["estado"] == "ESPERADO-INVISIVEL"),
        "imagem_sem_fronteira": sum(1 for a in sf if not a.get("herdado")),
        "imagem_sem_fronteira_herdada": sum(1 for a in sf if a.get("herdado")),
        "desloc_sistematico": desloc_sist or 0,
    }
    return {
        "schema": CONTRATO,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "video": video_rel,
        "fonte_fronteiras": fonte,
        "fps": fps, "frames": info["frames"],
        "params": {"razao_min": args.razao_min, "razao_cega": args.razao_cega,
                   "tol_frames": args.tol_frames, "janela_s": args.janela_s,
                   "piso": PISO_VIZINHANCA, "altura_analise": altura,
                   "janela_frames": w},
        "aviso": aviso,
        "resumo": resumo,
        "fronteiras": linhas,
        "achados_sem_fronteira": sf,
    }


def imprimir(doc, aviso_extra=None):
    """Saída curta — o orçamento é da SPEC-12, aqui é só não estourá-lo."""
    r = doc["resumo"]
    print("qc-corte-imagem · %s · %d frames @ %g fps · fronteiras: %s"
          % (doc["video"], doc["frames"], doc["fps"], doc["fonte_fronteiras"]))
    print("varrido: %d frames, %d fronteira(s) declarada(s), %d esperado_visivel=sim"
          % (doc["frames"], r["esperadas"], r["esperado_visivel_sim"]))
    print("%d/%d confirmadas · %d duvidosa(s) · %d sem-imagem · %d sem-marcador · "
          "%d invisível(is) · %d imagem-sem-fronteira · desloc %+d"
          % (r["confirmadas"], r["esperadas"], r["duvidosas"], r["sem_imagem"],
             r["sem_marcador"], r["esperado_invisivel"],
             r["imagem_sem_fronteira"], r["desloc_sistematico"]))
    falhas = 0
    if r["desloc_sistematico"]:
        # tendência ANTES de item: uma linha, não N achados.
        print("DESLOCAMENTO-SISTEMATICO %+d frame (%d/%d) — bug de cadeia, não de "
              "fronteira" % (r["desloc_sistematico"], r["esperadas"],
                             r["esperadas"]))
        falhas += 1
    for l in doc["fronteiras"]:
        if l["estado"] in ("CONFIRMADA", "ESPERADO-INVISIVEL"):
            continue
        print("%s k=%d frame=%d t=%.3f razao=%.2f (%s: %s)"
              % (l["estado"], l["k"], l["frame"], l["t_s"], l["razao"],
                 l["esperado_visivel"], l["motivo"]))
        if l["estado"] == "FRONTEIRA-SEM-IMAGEM":
            falhas += 1
    for a in doc["achados_sem_fronteira"]:
        print("IMAGEM-SEM-FRONTEIRA%s frame=%d t=%.3f razao=%.2f%s"
              % (" [HERDADO]" if a.get("herdado") else "", a["frame"], a["t_s"],
                 a["razao"], " — " + a["detalhe"] if a.get("detalhe") else ""))
    if doc.get("aviso"):
        print("aviso: %s" % doc["aviso"])
    if aviso_extra:
        print("aviso: %s" % aviso_extra)
    return falhas


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.splitlines()[0])
    ap.add_argument("dir")
    ap.add_argument("--video", default="v1-montado.mp4")
    ap.add_argument("--tol-frames", type=int, default=TOL_FRAMES)
    ap.add_argument("--janela-s", type=float, default=JANELA_S)
    ap.add_argument("--razao-min", type=float, default=RAZAO_MIN)
    ap.add_argument("--razao-cega", type=float, default=RAZAO_CEGA)
    ap.add_argument("--altura-analise", type=int, default=None,
                    help="px de altura na análise; sem isto, fração da altura "
                         "medida do próprio vídeo")
    ap.add_argument("--cortes-bruto", default=None,
                    help="JSON com os cortes já existentes no bruto, em segundos "
                         "NA SAÍDA (marca [HERDADO])")
    ap.add_argument("--orfao-prefixo", action="store_true",
                    help="com mais segs/ que segmentos na EDL, mede os N "
                         "primeiros SE a soma dos frames bater com o vídeo. Sem "
                         "isto, órfão é NÃO VERIFICADO.")
    ap.add_argument("--sem-filtro-edl", action="store_true",
                    help="recusa qualquer divergência segs/×EDL (é o default; a "
                         "flag existe para tornar a recusa explícita no comando)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--saida", default=None,
                    help="onde gravar o relatório (default <dir>/qc/corte-imagem.json)")
    args = ap.parse_args(argv)

    d = args.dir
    if not os.path.isdir(d):
        print("não é diretório: %s" % d, file=sys.stderr)
        return 2

    try:
        doc = analisar(d, args)
    except NaoVerificado as e:
        print("qc-corte-imagem · %s" % os.path.basename(os.path.abspath(d)))
        print("varrido: 0 frames, 0 fronteira(s) declarada(s), 0 esperado_visivel=sim")
        print("%s: %s" % (e.tag, e.msg))
        print("NÃO VERIFICADO — isto não é aprovação")
        return 3
    except SystemExit as e:                     # edl_io aborta com sys.exit(msg)
        print("qc-corte-imagem · %s" % os.path.basename(os.path.abspath(d)))
        print("varrido: 0 frames, 0 fronteira(s) declarada(s), 0 esperado_visivel=sim")
        print("EDL-ILEGIVEL: %s" % str(e).splitlines()[0])
        print("NÃO VERIFICADO — isto não é aprovação")
        return 3

    saida = args.saida or os.path.join(d, "qc", "corte-imagem.json")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    with open(saida, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 1 if (doc["resumo"]["sem_imagem"]
                     or doc["resumo"]["desloc_sistematico"]) else 0
    falhas = imprimir(doc)
    print("relatório: %s" % os.path.relpath(saida, d), file=sys.stderr)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
