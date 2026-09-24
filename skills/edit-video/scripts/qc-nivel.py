#!/usr/bin/env python3
"""QC de NÍVEL DE FALA: o trecho que ninguém consegue ouvir (SPEC-10).

    qc-nivel.py achado  <dir-producao> [--src ARQ] [--drop-db N] [--transcript ARQ]
                                       [--exigir N] [--json] [--gravar]
    qc-nivel.py balanco <dir-producao> [--video ARQ] [--balanco-db N]
                                       [--mascara auto|palavras|piso]
                                       [--transcript ARQ] [--json] [--gravar]

POR QUE ISTO EXISTE
Existe uma classe de defeito de áudio invisível para TODOS os nossos QCs e que
chega ao espectador: um trecho de fala que a pessoa não consegue ouvir.
O transcript está perfeito (a palavra foi dita, o Deepgram ouviu), a emenda está
limpa, o corte não cai em rampa de ataque, não há sílaba vazada — e o LUFS é
integrado, então 0,7 s a −20 dB não move o número do arquivo.

O caso que originou o script está ENTREGUE: `creator-2/peca-01/v-final.mp4`,
segmento 3 da EDL (`"vamos"`), 12,567–13,300 s na saída. Medido com janelas RMS
de 20 ms: **−34,1 dBFS** contra uma mediana de −13,4 dos outros 28 ranges —
**−20,7 dB**, enquanto o segundo pior range da mesma peça está a −2,7 dB.
Nenhum QC acusou.

OS DOIS SUBCOMANDOS, E POR QUE SÃO DOIS
    achado   detector, roda no BRUTO. NÃO aprova, e sai sempre 0.
    balanco  teste de convergência, roda no RENDER. É o gate.

`achado` seleciona trechos por estarem abaixo da mediana e mede o mesmo delta que
usou para selecionar: todo item que ele lista está abaixo do limiar POR
CONSTRUÇÃO, e perseguir esse número até zero só levanta ruído de sala. É o mesmo
erro que fez o `audit-emendas.py` acusar 16 de 20 segmentos na `peca-03`, todos
falso-positivo. `balanco` compara cada range contra a mediana dos OUTROS
(leave-one-out): a referência independe do critério de seleção, então um range
corrigido PARA de ser sinalizado. Só isso pode ser critério de aprovação.

O QUE ESTE SCRIPT NÃO FAZ
Não escreve `edl.json`, não aplica ganho, não renderiza, não remuxa e não toca em
produção histórica. `--gravar` escreve um único `qc-nivel-<modo>.json`; sem ele
nada é gravado. A aplicação do `gain_db` é da SPEC-08.
"""
# Mecanismo derivado de helpers/voice_levels.py e helpers/verify_cut.py de uma ferramenta de edição de terceiro
#.
# Nenhum código foi copiado: a estimativa de piso, a máscara de fala pelo transcript
# e o leave-one-out são nossos, e as razões estão em
# docs/specs/SPEC-10-qcnivelpy-o-trecho-que-ninguém-consegue-ouvir.md §10.
import json
import os
import subprocess
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

SCHEMA = "benchmark.qc-nivel/v1"

# ─────────────────────────────────────────────────────────────────────────────
# FÍSICA — descreve como se MEDE, não como a peça É. Fica no script (SPEC-00).
# ─────────────────────────────────────────────────────────────────────────────
GAP_FRASE_S = 0.50     # silêncio entre palavras que separa duas frases
PONTE_S = 0.30         # silêncio que um run atravessa sem se partir
DB_MIN = -120.0        # chão do log; abaixo disto é silêncio digital, não nível
RUNS_NO_TEXTO = 10     # quantos runs o relatório de TEXTO lista (o JSON leva todos)

# ─────────────────────────────────────────────────────────────────────────────
# FORMATO — vem do PERFIL DE PEÇA (SPEC-00). Os valores abaixo são o FALLBACK que
# vale enquanto o bloco `audio.nivel` não existir no catálogo de perfis: o nome de
# cada constante é o caminho dela no perfil, para a migração ser mecânica e para
# não existir um segundo mecanismo de configuração. `audio.sr` já existe hoje e é
# lido do perfil sempre — não há literal de sample rate neste arquivo.
# ─────────────────────────────────────────────────────────────────────────────
JANELA_RMS_S = 0.020      # perfil: audio.janela_rms_s
DROP_DB = 5.0             # perfil: audio.nivel.drop_db
BALANCO_DB = 5.0          # perfil: audio.nivel.balanco_db
MIN_RUN_S = 0.25          # perfil: audio.nivel.min_run_s
MIN_AMOSTRA_S = 0.40      # perfil: audio.nivel.min_amostra_s
MARGEM_MASCARA_DB = 6.0   # perfil: audio.nivel.margem_mascara_db
PISO_PERCENTIL = 15       # perfil: audio.nivel.piso_percentil
HEADROOM_DB = 1.5         # perfil: audio.nivel.headroom_db
GANHO_MAX_DB = 12.0       # perfil: audio.nivel.ganho_max_db


def config(P):
    """O perfil manda; as constantes acima são o fallback nomeado."""
    a = P.get("audio") or {}
    n = a.get("nivel") or {}
    def v(chave, padrao):
        x = n.get(chave)
        return padrao if x is None else float(x)
    return {
        "sr": int(a["sr"]),
        "janela_rms_s": float(a.get("janela_rms_s") or JANELA_RMS_S),
        "drop_db": v("drop_db", DROP_DB),
        "balanco_db": v("balanco_db", BALANCO_DB),
        "min_run_s": v("min_run_s", MIN_RUN_S),
        "min_amostra_s": v("min_amostra_s", MIN_AMOSTRA_S),
        "margem_mascara_db": v("margem_mascara_db", MARGEM_MASCARA_DB),
        "piso_percentil": v("piso_percentil", PISO_PERCENTIL),
        "headroom_db": v("headroom_db", HEADROOM_DB),
        "ganho_max_db": v("ganho_max_db", GANHO_MAX_DB),
        "perfil_do_catalogo": bool(n),
    }


# ═══════════════════════════════════════════════════════ primitivas de medição

def envelope_db(caminho, *, sr, janela_s):
    """(t, db) em janelas FIXAS. Uma passada de decode, RMS em numpy.

    `-ac 1 -ar {sr}` são OBRIGATÓRIOS. Sem eles a janela de análise deixa de ser
    a declarada e vira o frame do DECODER, e a taxa de análise vira a do arquivo.
    Medido nos nossos arquivos com `astats=reset=1` (que é como o
    `voice_levels.py:72-76` do ref-A lê): 21,33 ms no `take-inicio.MOV` (aac
    48 kHz) e 36,0 ms no `peca-03/take-A/audio.mp3` (mp3 16 kHz, mais um
    primeiro frame parcial de 2,9 ms). O `FRAME = 1024` / `SR = 48 kHz` deles
    (`:48-49`) são constantes MORTAS. Este é o bug latente que o `-ar/-ac` mata.

    É a mesma primitiva que já existe quatro vezes neste repo, todas já forçando
    `-ac 1 -ar <sr>`: audit-emendas.py:38-49, qc-ataque.py:34-40,
    audio-exato.py:60-68, qc-fonemas.py:163-170. Copiada de propósito em vez de
    refatorada para um módulo comum — o módulo comum é escopo da SPEC-05.

    20 ms é inteiro em toda taxa que suportamos (960 amostras a 48k, 882 a 44,1k)
    e preserva o argumento contra o LUFS: uma cláusula sussurrada de 0,6 s ainda
    é resolvida por 30 janelas, enquanto o LUFS integrado de 400 ms a apaga.
    """
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", caminho, "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True).stdout
    if not raw:
        sys.exit("não consegui decodificar áudio de %s" % caminho)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(round(sr * janela_s))
    m = len(a) // n
    if m < 1:
        sys.exit("áudio curto demais em %s (%d amostras)" % (caminho, len(a)))
    rms = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1))
    db = np.maximum(20 * np.log10(np.maximum(rms, 1e-9)), DB_MIN)
    return np.arange(m, dtype=np.float64) * janela_s, db


def piso_de_sala(db, *, p=PISO_PERCENTIL):
    """Piso da sala: percentil `p` do arquivo INTEIRO. Nada de Ridler-Calvard.

    Mesmo estimador de bordas.py:123-126 (`piso_local`, percentil 15); a
    diferença é o raio — aqui o arquivo todo, porque a referência é a sala e não
    o instante.

    ⚠️ Os 10 dB de `bordas.py:92` NÃO entram aqui, e isto é decisão medida, não
    esquecimento. Lá eles existem para decidir ONDE CORTAR; somá-los aqui poria o
    piso do `take-conteudo.MOV` em −33,3 dB — a duas casas do −32,1 que o clamp
    `med−12` do ref-A produz no mesmo arquivo, que é exatamente o número que o
    critério A6 da SPEC-10 manda REPROVAR. O piso reportado é o p15 cru (−43,3
    naquele arquivo); a margem de fala é `margem_mascara_db`, aplicada na máscara.

    Por que não portamos o Ridler-Calvard (`voice_levels.py:105-138`), medido nos
    4 materiais reais: ele cai 10–13 dB ACIMA do ruído de sala nos quatro, em 2
    deles quem decide o número é o clamp `[med−32, med−12]` e não o algoritmo, e
    o clamp limita a janela de detecção a 5–12 dB — o que faz o detector PERDER
    os defeitos graves (a −20 dB ele acha 0,00 s; a −12 dB acha 2,24 s).
    """
    return float(np.percentile(db, p))


def nivel_p75(db, mascara, *, min_janelas):
    """P75 das janelas de fala do span. (valor|None, n_janelas_mascaradas)

    P75 e não média (a média rastreia o quão esburacado é o trecho) e não pico
    (uma plosiva define). É a MESMA escolha, pelo mesmo motivo, do nosso
    `qc-fonemas.py:127` e do `voice_levels.py:141-146` do ref-A — dois times
    chegaram nela de forma independente. O que NÃO é compartilhado é o gate:
    lá é `percentile(rms, 40)` de uma janela local de 700 ms, que é a régua certa
    para comparar uma consoante com o corpo da palavra ao lado; aqui é o piso da
    SALA no arquivo inteiro, porque num bruto 90 % falado o percentil 40 cai
    dentro da fala. Os dois convivem, de propósito (SPEC-10 §3.7).
    """
    n = int(mascara.sum())
    if n < min_janelas:
        return None, n
    return float(np.percentile(db[mascara], 75)), n


def ganho_sugerido(delta_db, *, headroom_db, teto_db):
    """Levanta o trecho na direção da mediana, de propósito SEM fechar o buraco.

    Os últimos 1–2 dB custam mais em ruído de sala levantado do que compram em
    inteligibilidade, e a entrega era mais baixa de propósito. Teto de 12 dB:
    acima disso o piso sobe junto com a voz e soa como outro microfone.
    """
    return round(min(max(-delta_db - headroom_db, 0.0), teto_db), 1)


def resto_apos_ganho(delta_db, *, headroom_db, teto_db):
    """Quanto AINDA falta depois de aplicar o ganho sugerido. 0,0 = fecha.

    🔴 A SUGESTÃO DE UM PASSO NÃO FECHAVA, E NÃO DIZIA ISSO. O defeito canônico
    do repo — o trecho que ninguém consegue ouvir — mede −20,7 dB abaixo da
    mediana. O teto do campo é +12, então a sugestão saía CAPADA em 12,0; quem
    aplicasse ficaria em −10,3 dB, o range continuaria sinalizado, e o QC pediria
    +12 de novo. Só fechava na 2ª iteração, sem nenhum aviso de que haveria uma.
    O encanamento estava certo: a receita de um passo é que não fechava.

    O teto de +12 dB NÃO muda — ele é medido e defensável (acima disso o piso de
    sala sobe junto com a voz). O que muda é o relatório dizer a verdade: quando
    sobra, sobra, e o humano decide entre uma segunda passada, regravar o take ou
    aceitar o trecho como está.
    """
    falta = max(-delta_db - headroom_db, 0.0)
    return round(max(falta - teto_db, 0.0), 1)


# ═══════════════════════════════════════════════════════ máscara e agrupamento

def mascara_de_fala(t, db, palavras, piso_db, *, janela_s, margem_db, so_palavras=False,
                    so_piso=False):
    """União de dois critérios. Uma janela é FALA se:
       (a) intersecta o intervalo [start,end] de uma palavra do transcript  — OU
       (b) db > piso_db + margem_db

    (a) é a virada de chave desta spec e é o que a arquitetura do ref-A não tem.
        Lá, `is_speech = levels > floor_db` (`voice_levels.py:216`) — a definição
        de fala É o nível, e o que se quer medir é o nível: fala baixa demais
        deixa de ser fala e some do relatório. Nós já temos timestamp por palavra
        de todo bruto; um sussurro a −20 dB da mediana foi TRANSCRITO, então é
        fala, ponto, e a curva não-monotônica desaparece por construção.
    (b) cobre o buraco conhecido do ASR — estrangeirismo/nome próprio que o
        Deepgram não reconhece e vira vão no transcript (o caso "peca-10" do
        criativo do creator-3). Vão no transcript é fala NÃO RECONHECIDA, não
        silêncio: por isso a máscara é uma união, não só os intervalos.
    """
    m_pal = np.zeros(len(t), dtype=bool)
    for a, b in palavras:
        m_pal |= (t + janela_s > a) & (t < b)
    if so_palavras:
        return m_pal
    m_piso = db > piso_db + margem_db
    if so_piso:
        return m_piso
    return m_pal | m_piso


def agrupar_frases(palavras, *, gap_s=GAP_FRASE_S):
    """Palavras → frases, por silêncio ≥ gap_s entre elas.

    Mecanismo de `voice_levels.py:179-192`; o critério de vizinhança é o mesmo
    que o `bordas.py` já usa para resolver janelas."""
    frases = []
    for w in sorted(palavras, key=lambda x: x[0]):
        if frases and w[0] - frases[-1][-1][1] < gap_s:
            frases[-1].append(w)
        else:
            frases.append([w])
    return frases


def achar_runs(t, db, mascara, limiar_db, *, janela_s, min_run_s, ponte_s=PONTE_S):
    """Trechos contíguos de FALA abaixo de `limiar_db`, atravessando silêncio curto.

    Mecanismo de `voice_levels.py:198-244` (a ponte em `:234`). Pega o falante que
    desliga no último terço da frase e a cláusula sussurrada dentro de uma frase
    normal — casos que o agrupamento por frase não vê porque a média da frase
    fica "ok".

    ⚠️ Este seletor é CIRCULAR por construção (seleciona por estar abaixo, e
    mede o mesmo delta). É o motivo de o `achado` não aprovar nada.

    🐛 A PONTE É SOBRE SILÊNCIO, NUNCA SOBRE FALA. Medido na primeira versão
    deste script, na `peca-01`: atravessando qualquer vão de até 0,30 s, o
    detector fundiu os dips isolados num único run de 13,5 s a 18,6 s cujo P75
    (−19,7 dB) ficava ACIMA do limiar que o selecionou (−23,3) — um run que se
    reporta acima do próprio critério é a assinatura de que a ponte comeu a fala
    entre dois vales. A ponte só atravessa janelas FORA da máscara.
    """
    cand = mascara & (db < limiar_db)
    idx = np.flatnonzero(cand)
    if not len(idx):
        return []
    ponte_j = int(round(ponte_s / janela_s))
    grupos, ini, ant = [], idx[0], idx[0]
    for k in idx[1:]:
        vao = k - ant - 1
        if vao <= ponte_j and (vao == 0 or not mascara[ant + 1:k].any()):
            ant = k
        else:
            grupos.append((ini, ant))
            ini, ant = k, k
    grupos.append((ini, ant))
    runs = []
    for a, b in grupos:
        t0, t1 = float(t[a]), float(t[b] + janela_s)
        if t1 - t0 + 1e-9 < min_run_s:
            continue
        sel = mascara & (t + janela_s > t0) & (t < t1)
        if not sel.any():
            continue
        runs.append({"start": round(t0, 3), "end": round(t1, 3),
                     "nivel_db": round(float(np.percentile(db[sel], 75)), 1),
                     "n_janelas": int(sel.sum())})
    return runs


# ═══════════════════════════════════════════════════════════ transcript / EDL

def palavras_de(caminho):
    """Deepgram → [(start, end, texto)]. Aceita o JSON completo ou uma lista."""
    d = json.load(open(caminho))
    if isinstance(d, list):
        ws = d
    else:
        try:
            ws = d["results"]["channels"][0]["alternatives"][0]["words"]
        except (KeyError, IndexError, TypeError):
            sys.exit("%s não parece um transcript do Deepgram (sem "
                     "results.channels[0].alternatives[0].words)" % caminho)
    return [(float(w["start"]), float(w["end"]),
             w.get("punctuated_word") or w.get("word") or "") for w in ws]


def transcript_do_src(dirp, src):
    """`input/take-conteudo.MOV` → `<dir>/take-conteudo/transcript.json`.

    A convenção do repo é o diretório do take levar o STEM do arquivo do bruto.
    Quando não bater (a `peca-03` grava `input/IMG_6700.MOV` em `take-A/`), o
    chamador cai no critério (b) da máscara e AVISA — nunca em silêncio.
    """
    stem = os.path.splitext(os.path.basename(src))[0]
    for cand in (os.path.join(dirp, stem, "transcript.json"),
                 os.path.join(dirp, stem + "-transcript.json")):
        if os.path.isfile(cand):
            return cand
    return None


def _fmt(v, larg=6, casas=1):
    return " " * larg if v is None else ("%*.*f" % (larg, casas, v))


def medianas_por_quem(segs, niveis):
    """§9.3.16: duas pessoas em quadro são dois níveis. O relatório imprime a
    mediana POR `quem` ao lado da global; o veredito continua usando a global.
    Segmentar o veredito por falante é trabalho futuro — e a decisão sobreviveu
    ao caso de teste: o `"vamos"` é `quem: "creator-2"` e o delta contra a mediana só
    da creator-2 continua grande."""
    por = {}
    for s, v in zip(segs, niveis):
        q = s.get("quem")
        if q and v is not None:
            por.setdefault(q, []).append(v)
    return {q: round(float(np.median(vs)), 1) for q, vs in por.items() if len(vs) >= 2}


# ═══════════════════════════════════════════════════════════════════ subcomando: achado

def rodar_achado(dirp, args):
    P = perfil_mod.carregar(dirp)
    C = config(P)
    segs = edl_io.segmentos(dirp)
    drop_db = float(args["drop_db"]) if args.get("drop_db") is not None else C["drop_db"]
    min_janelas = max(1, int(round(C["min_amostra_s"] / C["janela_rms_s"])))

    srcs = [args["src"]] if args.get("src") else []
    if not srcs:
        vistos = []
        for s in segs:
            if s.get("src") and s["src"] not in vistos:
                vistos.append(s["src"])
        srcs = vistos
    if not srcs:
        sys.exit("nenhum `src` na EDL e nenhum --src: não há o que medir")

    saidas, n_low_total, varrido = [], 0, {"janelas": 0, "mascaradas": 0, "srcs": 0}
    for src in srcs:
        caminho = src if os.path.isabs(src) else os.path.join(dirp, src)
        if not os.path.isfile(caminho):
            print("aviso: %s não existe (bruto fora do repo?) — pulado" % caminho,
                  file=sys.stderr)
            continue
        varrido["srcs"] += 1
        t, db = envelope_db(caminho, sr=C["sr"], janela_s=C["janela_rms_s"])
        piso = piso_de_sala(db, p=C["piso_percentil"])

        tp = args.get("transcript") or transcript_do_src(dirp, src)
        if tp and os.path.isfile(tp):
            pal = palavras_de(tp)
            modo_mascara = "transcript+piso"
        else:
            pal, modo_mascara = [], "piso"
            print("aviso: sem transcript para %s — a máscara cai só no critério de "
                  "piso e o detector volta a ter o TETO DE DETECÇÃO do ref-A "
                  "(fala muito abaixo do piso vira silêncio). Passe --transcript."
                  % src, file=sys.stderr)
        masc = mascara_de_fala(t, db, [(a, b) for a, b, _ in pal], piso,
                               janela_s=C["janela_rms_s"],
                               margem_db=C["margem_mascara_db"])
        varrido["janelas"] += len(t)
        varrido["mascaradas"] += int(masc.sum())
        if not masc.any():
            sys.exit("máscara VAZIA em %s: nenhuma janela classificada como fala. "
                     "Isto é auto-neutralização, não 'varredura limpa' — confira o "
                     "transcript e o piso." % src)

        # ── frases ────────────────────────────────────────────────────────────
        frases_out, niveis_frase = [], []
        for f in agrupar_frases(pal):
            a, b = f[0][0], f[-1][1]
            sel = masc & (t + C["janela_rms_s"] > a) & (t < b)
            v, n = nivel_p75(db, sel, min_janelas=min_janelas)
            txt = " ".join(w[2] for w in f)
            item = {"start": round(a, 3), "end": round(b, 3),
                    "texto": txt[:120], "n_janelas": n}
            if v is None:
                item["flag"] = "amostra-curta"
            else:
                item["nivel_db"] = round(v, 1)
                niveis_frase.append(v)
            frases_out.append(item)

        if len(niveis_frase) >= 5:
            mediana = float(np.median(niveis_frase))
            met = "mediana-das-frases"
        else:
            mediana = float(np.percentile(db[masc], 50))
            met = "p50-janelas"

        for item in frases_out:
            if "nivel_db" in item:
                d = item["nivel_db"] - mediana
                item["delta_db"] = round(d, 1)
                item["flag"] = "LOW" if d <= -drop_db else "ok"
                if item["flag"] == "LOW":
                    item["ganho_sugerido_db"] = ganho_sugerido(
                        d, headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])

        # ── runs sub-frase ────────────────────────────────────────────────────
        runs = achar_runs(t, db, masc, mediana - drop_db,
                          janela_s=C["janela_rms_s"], min_run_s=C["min_run_s"])
        for r in runs:
            r["delta_db"] = round(r["nivel_db"] - mediana, 1)
            r["texto"] = " ".join(w[2] for w in pal
                                  if w[1] > r["start"] and w[0] < r["end"])[:80]
            r["ganho_sugerido_db"] = ganho_sugerido(
                r["delta_db"], headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])
            r["resto_apos_ganho_db"] = resto_apos_ganho(
                r["delta_db"], headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])

        # ── segmentos da EDL ──────────────────────────────────────────────────
        segs_out, niveis_seg = [], []
        for i, s in enumerate(segs):
            if s.get("src") != src:
                continue
            a, b = float(s["start"]), float(s["end"])
            sel = masc & (t + C["janela_rms_s"] > a) & (t < b)
            v, n = nivel_p75(db, sel, min_janelas=min_janelas)
            item = {"i": i, "beat": s.get("beat"), "src": src,
                    "start": round(a, 3), "end": round(b, 3),
                    "quem": s.get("quem"), "n_janelas": n,
                    "gain_db_atual": float(s.get("gain_db") or 0.0)}
            dentro = [r for r in runs if r["end"] > a and r["start"] < b]
            if dentro:
                item["pior_delta_db"] = min(r["delta_db"] for r in dentro)
            if v is None:
                item["flag"] = "amostra-curta"
            else:
                d = v - mediana
                item["nivel_db"] = round(v, 1)
                item["delta_db"] = round(d, 1)
                item["flag"] = "LOW" if d <= -drop_db else "ok"
                niveis_seg.append(v)
                if item["flag"] == "LOW":
                    # o ganho é dimensionado pelo PIOR RUN dentro do segmento, não
                    # pela média dele: um segmento com uma cláusula sussurrada
                    # seguida de uma normal tem média "ok" enquanto o sussurro
                    # continua inaudível (voice_levels.py:307-316). `min` porque a
                    # evidência que vale é a PIOR das duas — um run que atravessa a
                    # borda do segmento pode ser menos grave que o segmento inteiro,
                    # e nesse caso quem manda é o segmento.
                    base = min(d, item.get("pior_delta_db", d))
                    item["ganho_sugerido_db"] = ganho_sugerido(
                        base, headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])
                    # quanto SOBRA depois de aplicar o que foi sugerido. > 0
                    # significa que uma passada só não fecha, e quem lê precisa
                    # saber disso ANTES de aplicar e ver o range voltar.
                    item["resto_apos_ganho_db"] = resto_apos_ganho(
                        base, headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])
            segs_out.append(item)

        n_low = sum(1 for x in segs_out if x.get("flag") == "LOW")
        n_low_total += n_low
        saidas.append({
            "schema": SCHEMA, "modo": "achado",
            "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fonte": src,
            "medicao": {
                "sample_rate": C["sr"], "janela_rms_s": C["janela_rms_s"],
                "mascara": modo_mascara,
                "piso_db": round(piso, 1), "piso_metodo": "p%g" % C["piso_percentil"],
                "mediana_falante_db": round(mediana, 1), "mediana_metodo": met,
                "n_frases": len(frases_out), "drop_db": drop_db,
                "n_janelas": len(t), "n_janelas_mascaradas": int(masc.sum()),
                "min_janelas_por_span": min_janelas,
                "mediana_por_quem": medianas_por_quem(
                    [s for s in segs if s.get("src") == src],
                    [x.get("nivel_db") for x in segs_out]),
            },
            "frases": frases_out, "runs": runs, "segmentos": segs_out,
            "veredito": {"n_low": n_low, "aprovado": None,
                         "nota": "achado não aprova — ver modo balanco"},
        })

    if not saidas:
        sys.exit("nenhum src legível: nada foi medido (isto NÃO é aprovação)")

    doc = saidas[0] if len(saidas) == 1 else {"schema": SCHEMA, "modo": "achado",
                                              "fontes": saidas}
    if args.get("json"):
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for o in saidas:
            m = o["medicao"]
            print("== %s" % o["fonte"])
            print("   varrido: %d janelas de %g s (%d s de áudio), %d na máscara (%s)"
                  % (m["n_janelas"], m["janela_rms_s"],
                     round(m["n_janelas"] * m["janela_rms_s"]),
                     m["n_janelas_mascaradas"], m["mascara"]))
            print("   piso de sala %.1f dB (%s) · mediana do falante %.1f dB (%s, %d frases)"
                  % (m["piso_db"], m["piso_metodo"], m["mediana_falante_db"],
                     m["mediana_metodo"], m["n_frases"]))
            if m["mediana_por_quem"]:
                print("   mediana por quem: " + " · ".join(
                    "%s %.1f" % (k, v) for k, v in sorted(m["mediana_por_quem"].items()))
                    + "   (o veredito usa a global — §9.3.16)")
            for f in o["frases"]:
                if f.get("flag") == "LOW":
                    print("   frase  %7.3f–%7.3f  %s dB  Δ%s  +%.1f dB  %s"
                          % (f["start"], f["end"], _fmt(f["nivel_db"]),
                             _fmt(f["delta_db"], 5), f["ganho_sugerido_db"], f["texto"]))
            # ⚠️ O relatório de texto lista só os RUNS_NO_TEXTO piores. O JSON leva
            # todos. Motivo: 3 dos 8 QCs deste repo já despejaram 5.624 chars
            # (~1.400 tokens) para UM defeito real, e o run é o item mais
            # over-trigger daqui — o intervalo de palavra do Deepgram é generoso e
            # a pausa DENTRO dele entra na máscara. A lista acionável é a de
            # `segmentos`, que é a que casa com a EDL.
            piores = sorted(o["runs"], key=lambda r: r["delta_db"])
            for r in piores[:RUNS_NO_TEXTO]:
                print("   run    %7.3f–%7.3f  %6.1f dB  Δ%5.1f  +%.1f dB  %s"
                      % (r["start"], r["end"], r["nivel_db"], r["delta_db"],
                         r["ganho_sugerido_db"], r["texto"]))
            if len(piores) > RUNS_NO_TEXTO:
                print("   (+%d run(s) sub-frase menos graves — todos no --json/--gravar)"
                      % (len(piores) - RUNS_NO_TEXTO))
            for s in o["segmentos"]:
                if s.get("flag") == "LOW":
                    print("   seg%02d  %7.3f–%7.3f  %s dB  Δ%s  +%.1f dB  %s"
                          % (s["i"], s["start"], s["end"], _fmt(s["nivel_db"]),
                             _fmt(s["delta_db"], 5), s["ganho_sugerido_db"],
                             s.get("beat") or ""))
                    if s["ganho_sugerido_db"] >= 10.0 and m["piso_db"] > -45.0:
                        print("          ⚠️ ganho de %.1f dB sobre um piso de %.1f dB leva o "
                              "ruído de sala para %.1f dB e ele fica audível na virada: "
                              "aqui a resposta certa costuma ser REGRAVAR ou trocar o take."
                              % (s["ganho_sugerido_db"], m["piso_db"],
                                 m["piso_db"] + s["ganho_sugerido_db"]))
        n_curta = sum(1 for o in saidas for f in o["frases"] + o["segmentos"]
                      if f.get("flag") == "amostra-curta")
        print("\nACHADO — isto NÃO é aprovação. %d ponto(s) sinalizado(s)." % n_low_total)
        print("Todo run aqui está abaixo do limiar POR CONSTRUÇÃO (foi selecionado por isso):")
        print("perseguir este número até zero só levanta ruído de sala.")
        print("A aprovação é `qc-nivel.py balanco <dir>`, que compara cada range contra os OUTROS.")
        if n_curta:
            print("(%d span(s) com menos de %g ms de fala mascarada saíram como "
                  "`amostra-curta` e NÃO contam no veredito.)"
                  % (n_curta, C["min_amostra_s"] * 1000))

    if args.get("gravar"):
        p = os.path.join(dirp, "qc-nivel-achado.json")
        with open(p, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(p, file=sys.stderr)

    if args.get("exigir") is not None:
        lim = int(args["exigir"])
        print("\n⚠️ --exigir %d: você está pendurando o DETECTOR num gate. Ele "
              "over-triggera por construção (seleciona pelo mesmo delta que mede) "
              "e é quase sempre a coisa errada — o `audit-emendas.py` acusou 16 de "
              "20 segmentos na `peca-03`, todos falso-positivo, exatamente assim. "
              "O gate de aprovação é o `balanco`." % lim, file=sys.stderr)
        return 1 if n_low_total > lim else 0
    return 0


# ══════════════════════════════════════════════════════════ subcomando: balanco

def _fronteiras(dirp):
    """[start_s de cada segmento] + [total_s], da TIMELINE REAL.

    🔴 NUNCA `Σ(end−start)` da EDL. A soma nominal é sempre MENOR que a saída
    (o render arredonda para frame e o erro acumula sempre no mesmo sentido):
    353 ms no fim da `peca-03`, 317 ms na `peca-01`, 352 ms no
    `peca-10-27-07`. Com 353 ms de erro, o range 3 da `peca-01` (0,73 s de
    duração) seria medido meio segmento fora.
    """
    tl = edl_io.timeline(dirp, exigir=False)
    if tl is not None:
        return edl_io.fronteiras(tl), "timeline_real"
    print("aviso: sem timeline_real — medindo as fronteiras com "
          "`ffprobe -count_frames` nos segs/ (mais lento, mesmo resultado). "
          "`montar.sh <dir>` grava a timeline.", file=sys.stderr)
    return edl_io.fronteiras(edl_io.medir_timeline(dirp)), "ffprobe-segs"


def _palavras_da_saida(dirp, segs, fr, args):
    """Palavras no tempo DA SAÍDA. Três origens, nesta ordem."""
    tp = args.get("transcript")
    if tp:
        return palavras_de(tp), "--transcript"
    ft = os.path.join(dirp, "final-transcript", "transcript.json")
    if os.path.isfile(ft):
        return palavras_de(ft), "final-transcript"
    # derivado: as palavras do BRUTO mapeadas pela timeline real, segmento a
    # segmento. É o que dá máscara de transcript a uma produção que nunca
    # retranscreveu o montado (a `peca-01` é exatamente esse caso).
    out, cache, faltou = [], {}, set()
    for i, s in enumerate(segs):
        src = s.get("src")
        tpp = transcript_do_src(dirp, src) if src else None
        if not tpp:
            faltou.add(src)
            continue
        if tpp not in cache:
            cache[tpp] = palavras_de(tpp)
        a0, b0 = float(s["start"]), float(s["end"])
        for w0, w1, txt in cache[tpp]:
            if w1 > a0 and w0 < b0:
                out.append((fr[i] + (max(w0, a0) - a0),
                            fr[i] + (min(w1, b0) - a0), txt))
    if faltou:
        print("aviso: sem transcript para %s — esses segmentos ficam sem máscara "
              "de palavra" % ", ".join(sorted(x or "?" for x in faltou)), file=sys.stderr)
    if out:
        return out, "derivado-do-bruto"
    return [], "nenhuma"


def rodar_balanco(dirp, args):
    P = perfil_mod.carregar(dirp)
    C = config(P)
    segs = edl_io.segmentos(dirp)
    balanco_db = (float(args["balanco_db"]) if args.get("balanco_db") is not None
                  else C["balanco_db"])
    min_janelas = max(1, int(round(C["min_amostra_s"] / C["janela_rms_s"])))
    video = args.get("video") or "v1-montado.mp4"
    caminho = video if os.path.isabs(video) else os.path.join(dirp, video)
    if not os.path.isfile(caminho):
        sys.exit("%s não existe. Passe --video <arquivo>." % caminho)

    fr, origem_fr = _fronteiras(dirp)
    if len(fr) != len(segs) + 1:
        sys.exit("timeline com %d fronteiras para %d segmentos" % (len(fr), len(segs)))

    t, db = envelope_db(caminho, sr=C["sr"], janela_s=C["janela_rms_s"])
    piso = piso_de_sala(db, p=C["piso_percentil"])
    pal, origem_pal = _palavras_da_saida(dirp, segs, fr, args)
    modo = args.get("mascara") or "auto"
    masc = mascara_de_fala(t, db, [(a, b) for a, b, _ in pal], piso,
                           janela_s=C["janela_rms_s"], margem_db=C["margem_mascara_db"],
                           so_palavras=(modo == "palavras"), so_piso=(modo == "piso"))
    nome_masc = {"auto": "transcript+piso" if pal else "piso",
                 "palavras": "palavras", "piso": "piso"}[modo]
    if modo != "piso" and not pal:
        print("aviso: nenhuma palavra para a máscara — o `balanco` cai no gate de "
              "piso, que é o modo em que este QC se auto-neutraliza (§3.6d). "
              "Range com fala e sem janela medível sai como SEM-NIVEL.",
              file=sys.stderr)

    # ── nível por range ───────────────────────────────────────────────────────
    linhas = []
    for i, s in enumerate(segs):
        a, b = fr[i], fr[i + 1]
        sel_span = (t + C["janela_rms_s"] > a) & (t < b)
        sel = masc & sel_span
        dentro = [w for w in pal if w[1] > a and w[0] < b]
        dur_pal = sum(min(w[1], b) - max(w[0], a) for w in dentro)
        item = {"i": i, "beat": s.get("beat"), "quem": s.get("quem"),
                "inicio_s": round(float(a), 3), "fim_s": round(float(b), 3),
                "n_janelas": int(sel_span.sum()), "n_janelas_mascaradas": int(sel.sum()),
                "n_palavras": len(dentro), "dur_palavras_s": round(float(dur_pal), 3)}
        v, n = nivel_p75(db, sel, min_janelas=min_janelas)
        if v is not None:
            item["nivel_db"] = round(v, 1)
            item["_nivel"] = v
        elif pal and not dentro:
            # payoff mudo com som ambiente é desenho, não defeito (§9.3.15).
            item["flag"] = "sem-fala"
        elif dur_pal + 1e-9 >= C["min_amostra_s"] or (not pal and (b - a) >= C["min_amostra_s"]):
            # 🔴 A REGRA QUE IMPEDE O QC DE SE AUTO-NEUTRALIZAR (§3.6d).
            # Há fala suficiente aqui (ou não há transcript para provar que não
            # há) e NENHUMA janela mascarada sobreviveu. Isso não é "amostra
            # pequena", é o defeito grave: medido na `peca-01`, com um
            # gate de nível o range 3 fica com ZERO janelas, some do relatório e
            # o veredito volta VERDE — a §1.3 acontecendo de novo, no render.
            item["flag"] = "SEM-NIVEL"
        else:
            item["flag"] = "amostra-curta"
        linhas.append(item)

    # ── leave-one-out ─────────────────────────────────────────────────────────
    # O verify_cut.py:234-235 usa a mediana de TODOS os ranges, incluindo o que
    # está sendo julgado. Com 3 ranges (a `nao-perdeu-a-peca-06` tem 3) e um deles
    # defeituoso, o defeito puxa a própria referência. LOO custa uma linha.
    medidos = [(x["i"], x["_nivel"]) for x in linhas if "_nivel" in x]
    for x in linhas:
        if "_nivel" not in x:
            continue
        outros = [v for j, v in medidos if j != x["i"]]
        ref = float(np.median(outros)) if outros else x["_nivel"]
        d = x["_nivel"] - ref
        x["referencia_db"] = round(ref, 1)
        x["delta_db"] = round(d, 1)
        x["flag"] = "LOW-LEVEL" if d <= -balanco_db else "ok"
        if x["flag"] == "LOW-LEVEL":
            x["ganho_sugerido_db"] = ganho_sugerido(
                d, headroom_db=C["headroom_db"], teto_db=C["ganho_max_db"])
    for x in linhas:
        x.pop("_nivel", None)

    n_low = sum(1 for x in linhas if x["flag"] == "LOW-LEVEL")
    n_sem = sum(1 for x in linhas if x["flag"] == "SEM-NIVEL")
    flags = n_low + n_sem
    doc = {
        "schema": SCHEMA, "modo": "balanco",
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "video": video,
        "medicao": {
            "referencia": "mediana-dos-outros (leave-one-out)",
            "balanco_db": balanco_db, "mascara": nome_masc,
            "palavras_origem": origem_pal, "n_palavras": len(pal),
            "sample_rate": C["sr"], "janela_rms_s": C["janela_rms_s"],
            "piso_db": round(piso, 1), "piso_metodo": "p%g" % C["piso_percentil"],
            "n_ranges": len(linhas), "fronteiras": origem_fr,
            "n_janelas": len(t), "n_janelas_mascaradas": int(masc.sum()),
            "min_janelas_por_range": min_janelas,
            "mediana_por_quem": medianas_por_quem(segs, [x.get("nivel_db") for x in linhas]),
        },
        "ranges": linhas,
        "veredito": {"flags": flags, "n_low_level": n_low, "n_sem_nivel": n_sem,
                     "aprovado": flags == 0},
    }

    if args.get("json"):
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        m = doc["medicao"]
        print("balanço de nível · %s · %d ranges · fronteiras: %s"
              % (video, m["n_ranges"], m["fronteiras"]))
        print("   varrido: %d janelas de %g s (%d s), %d na máscara `%s` "
              "(%d palavras, origem %s)"
              % (m["n_janelas"], m["janela_rms_s"], round(m["n_janelas"] * m["janela_rms_s"]),
                 m["n_janelas_mascaradas"], m["mascara"], m["n_palavras"],
                 m["palavras_origem"]))
        print("   piso de sala %.1f dB (%s) · limiar %.1f dB abaixo da mediana dos OUTROS"
              % (m["piso_db"], m["piso_metodo"], m["balanco_db"]))
        if m["mediana_por_quem"]:
            print("   mediana por quem: " + " · ".join(
                "%s %.1f" % (k, v) for k, v in sorted(m["mediana_por_quem"].items()))
                + "   (o veredito usa a global — §9.3.16)")
        for x in linhas:
            if x["flag"] in ("ok",):
                continue
            print("   [%-13s] range %2d  %7.3f–%7.3f  %s dB  ref %s  Δ%s  %s (%d jan., %d pal.)"
                  % (x["flag"], x["i"], x["inicio_s"], x["fim_s"],
                     _fmt(x.get("nivel_db")), _fmt(x.get("referencia_db")),
                     _fmt(x.get("delta_db"), 5), x.get("beat") or "",
                     x["n_janelas_mascaradas"], x["n_palavras"]))
        n_ok = sum(1 for x in linhas if x["flag"] == "ok")
        print("\n%s — %d flag(s) em %d range(s) (%d ok, %d sem-fala, %d amostra-curta)"
              % ("APROVADO" if flags == 0 else "REPROVADO", flags, len(linhas), n_ok,
                 sum(1 for x in linhas if x["flag"] == "sem-fala"),
                 sum(1 for x in linhas if x["flag"] == "amostra-curta")))

    if args.get("gravar"):
        p = os.path.join(dirp, "qc-nivel-balanco.json")
        with open(p, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(p, file=sys.stderr)
    return 1 if flags else 0


# ══════════════════════════════════════════════════════════════════════════ CLI

FLAGS_VALOR = {"--src", "--drop-db", "--transcript", "--exigir", "--video",
               "--balanco-db", "--mascara"}


def _parse(argv):
    a = {}
    i = 0
    while i < len(argv):
        x = argv[i]
        if x in ("--json", "--gravar"):
            a[x[2:]] = True
        elif x in FLAGS_VALOR:
            if i + 1 >= len(argv):
                sys.exit("%s exige um valor" % x)
            a[x[2:].replace("-", "_")] = argv[i + 1]
            i += 1
        else:
            sys.exit("opção desconhecida: %s\n%s" % (x, __doc__.split("\n\n")[0]))
        i += 1
    return a


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    modo, dirp, args = argv[0], argv[1], _parse(argv[2:])
    if not os.path.isdir(dirp):
        sys.exit("%s não é um diretório de produção" % dirp)
    if args.get("mascara") not in (None, "auto", "palavras", "piso"):
        sys.exit("--mascara aceita auto|palavras|piso")
    if modo == "achado":
        return rodar_achado(dirp, args)
    if modo == "balanco":
        return rodar_balanco(dirp, args)
    sys.exit("subcomando desconhecido: %s (use `achado` ou `balanco`)" % modo)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
