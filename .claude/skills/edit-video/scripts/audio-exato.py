#!/usr/bin/env python3
"""Trilha de áudio TRAVADA no timeline do vídeo, amostra a amostra.

Uso: audio-exato.py [dir-da-producao]   → grava <dir>/audio-exato.wav
Lê `edl.json` + os `segs/segNNN.mp4` já renderizados (usa o nº REAL de frames de
cada um) e corta o áudio do bruto com duração EXATA de frames_k/fps.

📐 Sample rate, nº de canais, duração do micro-fade e MODO de fade vêm do perfil
de peça (SPEC-00), não daqui. Sem `<dir>/perfil.json` vale o FALLBACK, que é o
comportamento histórico: 48 kHz, mono, fade de 15 ms em toda borda.

🔀 J-CUT (SPEC-07): com `<dir>/jcut.json` presente, a trilha deixa de ser
concatenação e passa a ser POSICIONAMENTO com soma. Cada take é lido do bruto a
partir do `start` da EDL (a cabeça INTEIRA, sem descarte) e escrito na saída
começando `lead` amostras ANTES de onde a imagem dele entra — porque a imagem
descartou `lead` frames da própria cabeça no `montar.sh`.

    n_audio_k = n_video_k + lead_k        v_off_k = Σ_{j<k} n_video_j
    a_off_k   = v_off_k − lead_k          (lead_0 = 0)

Por indução, no primeiro frame de imagem do take k o áudio está exatamente
`lead_k` amostras dentro dele — o tempo de bruto que a imagem mostra. E o total
fecha sozinho: `a_off_{n−1} + n_audio_{n−1} = Σ n_video_k`. Ou seja
`soma_audio == soma_video` continua valendo POR CONSTRUÇÃO, e nada aqui depende
de `-shortest`, de `-t` de trava nem de sorte de encoder.

SEM `jcut.json` todo lead é 0, o acumulador vira a concatenação de sempre e a
saída é BYTE A BYTE a de antes desta spec.

🔊 NÍVEL (SPEC-08): `gain_db` é campo de SEGMENTO da EDL e entra aqui, sobre o
slice do bruto e ANTES dos micro-fades — assim a amostra da borda é exatamente
0.0 seja qual for o ganho, e o invariante anti-click não passa a depender de um
número que o operador digita. O TETO é da trilha e entra uma vez só, depois da
soma, por `nivel.limitar_cfg` (que é INERTE quando ninguém passou do teto — daí
a saída continuar bit a bit a de antes numa produção sem `gain_db`). O `np.clip`
que havia aqui era um clipper duro: hoje ele nunca atuava, e disparava
exatamente no dia em que alguém introduzisse ganho positivo. Medido: 13,47 % de
THD numa senoide 3 dB acima do teto, contra 0,0000 % do limitador, os dois com
pico de saída 1,000000. Sobrou UM `np.clip`, em `escreve_takes` — ele é da
representação (s16 não guarda |x| > 1), não uma escolha, e desde a SPEC-06 ele
DIZ quantas amostras ceifou e em qual take. Ver o docstring de lá.

⚠️ O BUG QUE ISTO EXISTE PRA IMPEDIR (achado na produção peca-03, 2026-07-25):
quando cada segmento carregava sua própria trilha AAC e o concat juntava as 20,
o delay de encoder + a quantização de frame (1024 amostras) ACUMULAVAM — no fim
do vídeo o áudio atrasava 0,28s em relação à imagem (medido na boca da creator-2:
lábios em 60,77s, som do "Comente" em 61,01s). Aqui soma_audio == soma_video
por construção, então a deriva é zero e não depende de sorte de encoder.

Endurecido por auditoria em 2026-07-25 (5 achados, todos latentes menos o 1º):
 1. PROVENIÊNCIA: `segs/` é cache de VÍDEO e o áudio sai da EDL corrente. Se a EDL
    for regerada depois dos segs (fluxo normal do bordas.py), dava vídeo de uma
    geração com áudio de outra — silenciosamente, com o invariante intacto e o QC
    de deriva carimbando OK. Agora cada seg carrega um sidecar `segNNN.json` com
    {src,start,end} e divergência é ERRO, não aviso. Validar por CONTAGEM não basta.
 2. `fadeOut` por segmento voltou a ser honrado (o script antigo lia o campo; a 1ª
    versão daqui fixou 15ms e quebrou o contrato — e a própria SKILL prescreve
    fade de 40ms no ponto coarticulado).
 3. `start` negativo colapsava o slice do numpy e o segmento saía 100% MUDO
    (o ffmpeg clampa em 0 e renderiza o vídeo normal → desync mudo).
 4. Ordenação lexicográfica de `segs/` embaralhava o áudio acima de 99 segmentos.
 5. FPS era constante hard-coded sem conferir o `r_frame_rate` real do segmento.
"""
import glob
import json
import os
import subprocess
import sys
import wave
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import jcut as jcut_mod       # noqa: E402
import nivel                  # noqa: E402
import perfil as perfil_mod   # noqa: E402


def _ffprobe(p: str, campo: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         f"stream={campo}", "-of", "csv=p=0", p],
        capture_output=True, text=True).stdout.strip().rstrip(",")


def frames_e_fps(p: str):
    """nº REAL de frames do segmento + fps declarado (não confiar em constante)"""
    n = int(_ffprobe(p, "nb_read_frames") if False else subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", p],
        capture_output=True, text=True).stdout.strip().rstrip(","))
    fr = _ffprobe(p, "r_frame_rate")
    num, den = (fr.split("/") + ["1"])[:2]
    return n, int(num) / int(den)


def audio_do_bruto(src: str, cache: dict, sr: int, canais: int) -> np.ndarray:
    """decodifica o bruto UMA vez por arquivo e guarda em memória.

    Com `canais: 2` o array é (n, 2). A VSL provou que forçar mono joga fora
    informação real: os canais medem correlação 0,9989 mas diferem 4,6 % em RMS."""
    if src not in cache:
        raw = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vn",
             "-ac", str(canais), "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
        cache[src] = a.reshape(-1, canais) if canais > 1 else a
    return cache[src]


def borda_com_fade(edl, i, lado, modo):
    """Esta borda leva micro-fade?

    `por-segmento` (histórico): sempre. `so-descontinuidade`: só quando o vizinho
    NÃO é contíguo no mesmo `src`.

    🔴 POR QUE O MODO EXISTE — a EDL da VSL do produto-1 tem 18 trocas de plano com
    áudio contínuo e 1 corte de áudio real. O fade canônico de 15 ms em toda borda
    cria 18 dips audíveis num áudio que devia atravessar inteiro
    (docs/EDICAO-CAPACIDADES.md:200-205)."""
    if modo != "so-descontinuidade":
        return True
    j = i - 1 if lado == "inicio" else i + 1
    if j < 0 or j >= len(edl):
        return True                      # extremidade da peça: sempre
    viz, seg = edl[j], edl[i]
    if viz.get("src") != seg.get("src"):
        return True
    t_viz = viz["end"] if lado == "inicio" else viz["start"]
    t_seg = seg["start"] if lado == "inicio" else seg["end"]
    return abs(t_viz - t_seg) > 1e-6


def confere_procedencia(seg_mp4: str, seg: dict, skip_planejado: int = 0):
    """o segmento renderizado veio DESTA linha da EDL E DESTE plano de J-cut?

    🔴 `video_skip_frames` é tão obrigatório aqui quanto `start`/`end` — é o
    risco nº 1 da SPEC-07. Se o lead mudar e a comparação não olhar o campo, os
    `segs/` velhos são reusados e o vídeo sai de uma geração com o áudio de
    outra, **com todos os QCs verdes**: a trilha é montada a partir dos frames
    REAIS, então ela sincroniza perfeitamente com o vídeo errado. É a mesma
    classe do órfão que deixou o `c-completo` do creator-3 6,25 s mais longo.

    Sidecar antigo sem o campo é lido como 0 (§4.3): produção anterior à
    SPEC-07 não tinha J-cut, e 0 é literalmente o que ela renderizou."""
    side = os.path.splitext(seg_mp4)[0] + ".json"
    if not os.path.exists(side):
        print("  aviso: %s sem sidecar de procedência (produção anterior ao guard) — "
              "conferindo só a contagem" % os.path.basename(seg_mp4), file=sys.stderr)
        return
    g = json.load(open(side))
    for k in ("src", "start", "end"):
        a, b = g.get(k), seg.get(k)
        if (round(a, 4) if isinstance(a, (int, float)) else a) != \
           (round(b, 4) if isinstance(b, (int, float)) else b):
            sys.exit("ERRO de procedência em %s: o segmento foi renderizado com %s=%r "
                     "mas a edl.json atual diz %r.\n"
                     "A EDL mudou depois dos segmentos: apague segs/ (ou só os segmentos "
                     "afetados) e remonte — senão o vídeo sai de uma geração e o áudio de outra."
                     % (os.path.basename(seg_mp4), k, a, b))
    renderizado = int(g.get("video_skip_frames", 0))
    if renderizado != int(skip_planejado):
        sys.exit("ERRO de procedência em %s: a imagem foi renderizada descartando %d "
                 "frame(s) de cabeça e o jcut.json atual planeja %d.\n"
                 "Apague segs/ e remonte. Montar a trilha com o lead novo sobre a "
                 "imagem antiga produz A/V dessincronizado COM TODOS OS QCs VERDES — "
                 "a trilha se trava nos frames reais e sincroniza com o vídeo errado."
                 % (os.path.basename(seg_mp4), renderizado, skip_planejado))


def confere_picos(y, leads, nfs, spf, edl):
    """A janela de sobreposição de cada junção pode estourar? ABORTA se sim.

    🔴 NÃO deixar o estágio seguinte lidar com isto. Até a SPEC-08 o estágio
    seguinte era um `np.clip`, que cortava em SILÊNCIO; hoje é o limitador do
    `nivel.py`, que não distorce mas ABAIXA a janela inteira da junção — o que
    na emenda vira um degrau de nível audível, exatamente onde este pipeline não
    pode ter artefato. A soma de dois takes é flat (não é crossfade), então o
    pico da janela é literalmente `|a + b|` — se passar de 1,0 o remédio é baixar
    o `lead_max_ms`, pôr um override na junção, ou reduzir o `gain_db` de um dos
    dois takes; nunca deixar o estágio de teto decidir.

    ⚠️ Esta medição roda DEPOIS do ganho por segmento e ANTES do limitador, e é
    de propósito: com `gain_db` na EDL o estouro da junção passou a ter uma
    causa nova, e o operador precisa ver o pico que o ganho dele produziu."""
    v_off, estouros = 0, []
    for i, nf in enumerate(nfs):
        lead = int(leads[i])
        if lead > 0:
            lo, hi = v_off - lead * spf, v_off
            pico = float(np.abs(y[lo:hi]).max()) if hi > lo else 0.0
            if pico >= 1.0:
                estouros.append((i - 1, i, pico, lead))
        v_off += nf * spf
    if estouros:
        linhas = "\n  ".join(
            "junção %d→%d (%s → %s): pico %.3f na sobreposição de %d frames"
            % (a, b, edl[a].get("beat", "?"), edl[b].get("beat", "?"), pk, lf)
            for a, b, pk, lf in estouros)
        sys.exit("ERRO: a soma do J-cut ESTOURA em %d junção(ões):\n  %s\n"
                 "Baixe `jcut.lead_max_ms`, ponha {\"<i>\": {\"lead_ms\": 0, "
                 "\"motivo\": \"…\"}} no jcut-override.json, ou reduza o `gain_db` "
                 "de um dos dois takes — o limitador seguraria o teto, mas ao preço "
                 "de um degrau de nível bem em cima da emenda."
                 % (len(estouros), linhas))


def escreve_takes(out, sr, canais, niveis=None):
    """`audio-takes/segNNN.wav`: cada take PÓS-fade e PRÉ-soma.

    Existe por um consumidor só, e é um consumidor obrigatório: com J-cut, a
    janela de 60 ms antes da fronteira NO MONTADO contém os DOIS takes somados,
    e o `qc-ataque.py` acusaria ATAQUE em toda junção por construção. Medindo a
    cauda no wav do próprio take, a régua volta a medir o que ela mede.

    🔴 O `np.clip` ABAIXO NÃO SAI, E POR ISSO É BARULHENTO (pendência herdada da
    SPEC-08, fechada aqui com medição). Ele foi tornado ALCANÇÁVEL quando a
    SPEC-08 removeu o `np.clip` pós-soma: com `gain_db` na EDL, um take pode
    passar de 1,0 e este é o único ponto que ainda corta.

    Medido em 2026-08-09, com um controle plantado: `gain_db +6` num take cujo
    pico está no MEIO (longe de qualquer junção) — `confere_picos` mede 0,000 na
    janela de sobreposição e deixa passar, e aqui 4.000 de 48.000 amostras
    (8,3 %) eram ceifadas SEM UMA LINHA de aviso.

    Por que não trocar por limitador: este WAV é, por contrato, o take PRÉ-SOMA.
    Passá-lo pelo `nivel.limitar_cfg` mudaria o envelope que o `qc-ataque.py`
    mede e a régua deixaria de descrever o take. E s16 não guarda |x| > 1: o
    clamp é da representação, não uma escolha de gosto. O que era defeito é o
    SILÊNCIO — o arquivo que o QC lê saía ceifado e ele media o clipper.
    A saída em bytes é IDÊNTICA à de antes desta mudança, sempre."""
    os.makedirs("audio-takes", exist_ok=True)
    # 🐛 mesma classe do segmento órfão: um wav de uma EDL MAIOR que sobrasse aqui
    # faria o qc-ataque.py medir a cauda de um take que não existe mais.
    for velho in glob.glob(os.path.join("audio-takes", "seg*.wav")):
        os.remove(velho)
    ceifados = []
    for i, x in enumerate(out):
        n_alto = int(np.count_nonzero(np.abs(x) > 1.0))
        if n_alto:
            ceifados.append((i, n_alto, x.size, float(np.abs(x).max())))
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
        with wave.open(os.path.join("audio-takes", "seg%03d.wav" % i), "wb") as w:
            w.setnchannels(canais)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
    print("  audio-takes/: %d take(s) pré-soma (o qc-ataque.py mede a cauda ali, "
          "não no montado)" % len(out), file=sys.stderr)
    for i, n_alto, tam, pico in ceifados:
        g = ""
        if niveis and i < len(niveis) and niveis[i].get("gain_db"):
            g = " · gain_db %+.1f nesta linha da EDL" % niveis[i]["gain_db"]
        print("  ⚠️ audio-takes/seg%03d.wav CEIFADO: %d de %d amostras (%.2f %%) "
              "acima de 1,0, pico %.3f%s.\n"
              "     A TRILHA entregue não é afetada (o limitador da SPEC-08 cuida "
              "do teto depois da soma) — quem lê este wav é o qc-ataque.py, e "
              "sobre um take ceifado ele mede o clipper, não a cauda. Baixe o "
              "`gain_db` deste segmento se a medição de cauda importar."
              % (i, n_alto, tam, 100.0 * n_alto / tam, pico, g), file=sys.stderr)


def main(d: str) -> str:
    P = perfil_mod.carregar(d)
    SR = int(P["audio"]["sr"])
    CANAIS = int(P["audio"]["canais"])
    FADE_PADRAO = float(P["ritmo"]["fade_borda_s"])
    FADE_MODO = P["ritmo"].get("fade_modo", "por-segmento")
    LIM = nivel.config(d, p=P)             # teto/lookahead/release do DESTINO
    os.chdir(d)
    edl = edl_io.segmentos(".")
    # Enumeração canônica e ESTRITA: só `segNNN.mp4`. O glob amplo também
    # aceitava temporários como `seg003.mp4.tmp-22.mp4`, duplicando um take
    # parcial na trilha e fazendo a contagem divergir da EDL.
    segs = edl_io.segs_ordenados(".")
    if len(segs) != len(edl):
        sys.exit("segmentos (%d) != EDL (%d) — renderize a montagem primeiro"
                 % (len(segs), len(edl)))

    # 🔀 o plano de J-cut, quando existe. `carregar` confere o `edl_fingerprint`:
    # plano que sobreviveu à EDL que descrevia é fatal, não aviso.
    plano = jcut_mod.carregar(".", edl)
    leads = jcut_mod.skips(plano, len(edl))
    fades_do_plano = bool(plano) and plano.get("fades") == "jcut"

    cache: dict = {}
    out, offs, niveis = [], [], []
    fps_ref = None
    spf = None
    # 📐 TIMELINE REAL (SPEC-05): estes dois vetores são a timeline. `nfs` são os
    # frames REAIS de cada segmento — os mesmos que travam o áudio abaixo — e
    # `amostras` é o que de fato foi escrito no WAV. Nenhum número novo é
    # calculado aqui: só se guarda o que este script já media e jogava fora.
    nfs, amostras = [], []
    v_off = 0                              # offset de VÍDEO acumulado, em amostras
    for i, (seg, p) in enumerate(zip(edl, segs)):
        lead = int(leads[i])
        confere_procedencia(p, seg, lead)
        nf, fps = frames_e_fps(p)
        if fps_ref is None:
            fps_ref = fps
            # 🔴 A restrição REAL é `sr % fps == 0`, não `fps == 30`. O abort antigo
            # era 5× mais estreito que a física: 24 (spf 2000), 25 (1920), 50 (960),
            # 60 (800) e 100 (480) dividem 48000 tão exatamente quanto 30 (1600).
            # O que NÃO se pode fazer é arredondar/interpolar para aceitar 29,97 —
            # é assim que a deriva progressiva de A/V volta.
            if abs(fps - round(fps)) > 1e-6 or SR % int(round(fps)):
                sys.exit(perfil_mod.msg_fps(
                    ("%g" % fps), SR) + "\n(fps medido no segmento %s)" % p)
            fps_esperado = P["video"]["fps"]
            if abs(fps - fps_esperado) > 1e-6:
                sys.exit("fps do segmento = %g, mas o perfil (%s) declara %s.\n"
                         "Os segs/ foram renderizados com outro formato: apague segs/ "
                         "e remonte." % (fps, P.get("nome", "?"), fps_esperado))
            spf = SR // int(round(fps))       # amostras por frame de vídeo
        elif abs(fps - fps_ref) > 1e-6:
            sys.exit("fps inconsistente entre segmentos (%g vs %g)" % (fps, fps_ref))

        # Uma única conta inteira manda na montagem e no qc-jcut. Antes, estas
        # quatro expressões também existiam em jcut.py e no QC; qualquer mudança
        # parcial recriaria uma deriva que o sidecar pareceria legitimar.
        geo = jcut_mod.geometria_take(
            start_s=seg["start"], video_offset_frames=v_off // spf,
            video_frames=nf, lead_frames=lead, sr=SR, spf=spf)
        n_video = geo["video_samples"]          # duração EXATA do vídeo do segmento
        n = geo["audio_samples"]                # leva a cabeça que a imagem descartou
        a = audio_do_bruto(seg["src"], cache, SR, CANAIS)
        i0 = geo["src_start_samples"]           # start da EDL, SEM skip: cabeça inteira
        if i0 < 0:
            sys.exit("start negativo (%.3f) em %s: o slice do numpy colapsaria e o "
                     "segmento sairia MUDO. Corrija a EDL." % (seg["start"], p))
        x = a[i0:i0 + n].copy()
        if len(x) < n:                        # fim do bruto: completa com silêncio
            falta = (n - len(x),) + x.shape[1:]
            x = np.concatenate([x, np.zeros(falta, dtype=np.float32)])

        # 🔊 GANHO POR SEGMENTO (SPEC-08), ANTES dos micro-fades. Em numpy as duas
        # multiplicações comutam, então a ordem é neutra no VALOR — ela é fixada
        # por três razões que não são numéricas: (1) o fade tem que ser a última
        # coisa que toca a borda, para a amostra da borda ser 0.0 seja qual for o
        # gain_db; (2) quando a borda virar crossfade de J-cut, a soma tem que ser
        # de dois sinais JÁ nivelados; (3) o pico que o log reporta é o pós-ganho,
        # que é o número que decide se o valor foi longe demais.
        try:
            g_db = nivel.ler_gain_db(seg, i)
        except nivel.ErroNivel as e:
            sys.exit("ERRO de nível na EDL: %s" % e)
        if g_db:
            x *= nivel.ganho_linear(g_db)   # in-place: `x` já é cópia, e o dtype fica
        niveis.append({"i": i, "beat": seg.get("beat", ""), "gain_db": g_db,
                       "pico_pos_ganho": round(float(np.abs(x).max()), 6)})

        # o campo explícito da EDL SEMPRE vence (a SKILL prescreve fade de 40 ms no
        # ponto coarticulado); o modo do perfil só decide o DEFAULT desta borda.
        d_in = FADE_PADRAO if borda_com_fade(edl, i, "inicio", FADE_MODO) else 0.0
        d_out = FADE_PADRAO if borda_com_fade(edl, i, "fim", FADE_MODO) else 0.0
        if fades_do_plano:
            # o plano só escreve onde a GUARDA dele decidiu (borda contígua → 0);
            # onde ele não opina, o perfil continua mandando. É o fix dos 18 dips
            # da VSL (EDICAO-CAPACIDADES.md:200-205) explícito por borda.
            fi = plano["segmentos"][i].get("fade_in_s")
            fo = plano["segmentos"][i].get("fade_out_s")
            if fi is not None:
                d_in = float(fi)
            if fo is not None:
                d_out = float(fo)
        f_in = min(int(seg.get("fadeIn", d_in) * SR), n // 2)
        f_out = min(int(seg.get("fadeOut", d_out) * SR), n // 2)
        if f_in > 0:
            r = np.linspace(0, 1, f_in)
            x[:f_in] *= r[:, None] if x.ndim > 1 else r
        if f_out > 0:
            r = np.linspace(1, 0, f_out)
            x[-f_out:] *= r[:, None] if x.ndim > 1 else r
        out.append(x)
        offs.append(geo["audio_offset_samples"])  # a_off_k = v_off_k − lead_k
        v_off += n_video
        nfs.append(nf)
        # 📐 o que entra na TIMELINE é a pegada de VÍDEO do segmento (n_video), não
        # o comprimento do buffer de áudio: os buffers se SOBREPÕEM e a soma deles
        # é maior que o WAV. A timeline descreve posição na saída, e a posição da
        # imagem do segmento k na saída é exatamente `n_video` amostras. É também
        # o que mantém as invariantes do `edl_io.conferir_invariantes` verdadeiras.
        amostras.append(int(n_video))

    # ───────── POSICIONAMENTO (não concatenação) ─────────
    # Com todo lead 0 isto é `np.concatenate(out)` bit a bit: as fatias são
    # disjuntas, contíguas e somadas sobre zero. É o que faz a retrocompatibilidade
    # do §7.1 ser por construção, e não por sorte.
    total = v_off
    forma = (total,) + out[0].shape[1:]
    y = np.zeros(forma, dtype=np.float32)
    for i, (x, off) in enumerate(zip(out, offs)):
        if off < 0:
            sys.exit("ERRO interno: offset negativo no segmento %d (lead > offset "
                     "acumulado). lead_0 tem que ser 0 por definição." % i)
        y[off:off + x.shape[0]] += x
    if any(lead for lead in leads):
        confere_picos(y, leads, nfs, spf, edl)
        escreve_takes(out, SR, CANAIS, niveis)

    # 🔊 TETO DA TRILHA (SPEC-08), no lugar exato onde estava `np.clip(y, -1, 1)`.
    # Aqui não é escolha de gosto: o `np.clip` cortava em SILÊNCIO e nenhum QC
    # deste repo distingue um arquivo clipado de um limitado — os dois saem com
    # pico 1,000000. Com o teto default de 0 dBFS e material que não passa do
    # fundo de escala, `limitar_cfg` devolve o MESMO array e a saída é bit a bit
    # a de antes. O limitador é por TRILHA e não por segmento de propósito:
    # limitar segmento a segmento cria degrau de nível percebido exatamente na
    # emenda, que é a costura que este pipeline inteiro existe para esconder.
    y, lim = nivel.limitar_cfg(y, LIM, SR)
    tmp = "audio-exato.raw"
    open(tmp, "wb").write((y * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(SR),
                    "-ac", str(CANAIS), "-i", tmp, "-c:a", "pcm_s16le",
                    "audio-exato.wav", "-y"], check=True)
    os.remove(tmp)
    n_amostras = y.shape[0]
    print("audio-exato.wav: %.4fs (%d amostras × %d canal(is)) = %d frames de vídeo "
          "a %g fps · spf = %d — deriva zero"
          % (n_amostras / SR, n_amostras, CANAIS, n_amostras // spf, fps_ref, spf),
          file=sys.stderr)

    # ───────── o que foi APLICADO de nível vira dado (SPEC-08) ─────────
    # `nivel-aplicado.json` responde "o que exatamente foi aplicado nesta trilha"
    # e é o que o qc-nivel.py (SPEC-10) lê no modo `balanco`: sem ele, o teste de
    # convergência dele mede o material corrigido sem saber quanto de correção
    # entrou. Escrito SEMPRE, inclusive quando nada aconteceu — sidecar que só
    # aparece quando há novidade é sidecar que ninguém sabe interpretar quando
    # falta. Idempotente: reescrito junto com o WAV que descreve.
    json.dump({"schema": nivel.CONTRATO, "gerado_por": "audio-exato.py",
               "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
               "limitador": lim, "segmentos": niveis},
              open("nivel-aplicado.json", "w"), indent=1, ensure_ascii=False)
    com_ganho = [s for s in niveis if s["gain_db"]]
    for s in com_ganho:
        print("  seg %02d [%s]  gain_db %+.1f  → pico %.3f"
              % (s["i"], s["beat"], s["gain_db"], s["pico_pos_ganho"]),
              file=sys.stderr)
    if lim["atuou"]:
        print("limitador: teto %.1f dBFS · atuou em %d/%d blocos · redução máx %.1f dB "
              "· pico %.4f → %.4f"
              % (lim["teto_dbfs"], lim["blocos_reduzidos"], lim["blocos_total"],
                 lim["reducao_max_db"], lim["pico_entrada"], lim["pico_saida"]),
              file=sys.stderr)

    # ───────── a TIMELINE REAL vira dado (SPEC-05) ─────────
    # Gravada AQUI, e não no montar.sh, por uma razão só: este é o único ponto do
    # pipeline onde `total_samples == len(audio-exato.wav)` é afirmável com
    # diferença EXATAMENTE zero, porque o WAV acabou de ser escrito com estas
    # amostras. A timeline não é uma estimativa da saída: é a saída.
    tl = edl_io.medir_timeline(".", sr=SR, frames=nfs, amostras=amostras,
                               gerado_por="audio-exato.py")
    if tl["total_samples"] != n_amostras:
        sys.exit("ERRO interno: timeline diz %d amostras, o WAV tem %d"
                 % (tl["total_samples"], n_amostras))
    edl_io.gravar_timeline(".", tl)
    print("timeline_real: %d frames · %.6fs · %d amostras (fingerprint %s)"
          % (tl["total_frames"], tl["total_s"], tl["total_samples"],
             tl["edl_fingerprint"][:13]), file=sys.stderr)
    return os.path.abspath("audio-exato.wav")


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "."))
