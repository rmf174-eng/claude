#!/usr/bin/env python3
"""QC do J-cut: a sobreposição de takes fez o que o plano disse que faria?

Uso: qc-jcut.py <dir-da-producao> [--video v1-montado.mp4] [--wav audio-exato.wav]
                                  [--min-dur 3.0] [--busca-ms 25]
Sai 0 quando tudo passa, 1 quando algum teste reprova.

Os cinco testes, e por que cada um existe:

  1 ESTRUTURA      o plano é internamente coerente, os sidecars dos `segs/`
                   registram o mesmo skip que o plano manda, e TODA junção
                   contígua tem lead 0 / skip 0 / fades 0. Com lead ativo,
                   confere também presença e extensão dos PCM em `audio-takes/`.
  2 DURAÇÃO        `|dur(montado) − Σ frames/fps| ≤ 1 frame`, e o WAV tem
                   EXATAMENTE `Σ frames × spf` amostras. Zero tolerância no
                   áudio: ali a conta é inteira por construção.
  3 CONTÍGUA       nas junções contíguas o montado tem que ser o bruto, sem
                   emenda: a fatia de fala não pode tocar duas vezes nem levar
                   um dip de fade no meio de uma frase que atravessa.
  4 SINCRONIA      correlação cruzada take a take contra o bruto: |lag| ≤ 1
                   amostra e SEM tendência ao longo da peça. A janela mantém
                   padding fora do bruto e exclui a sobreposição do take seguinte.
  5 PICO           nenhuma janela de sobreposição chega a 1,0 na soma.

────────────────────────────────────────────────────────────────────────────
🔴 DUAS DECISÕES DE MEDIÇÃO QUE ESTE REPO JÁ PAGOU PARA APRENDER

(a) O VEREDITO ACÚSTICO É MEDIDO NO `audio-exato.wav`, NÃO NO `v1-montado.mp4`.
    O montado carrega áudio AAC. Comparar AAC decodificado contra o PCM do
    bruto e exigir "diferença ≤ −60 dB" mede o CODEC, não a emenda — é a mesma
    armadilha do portão que procurava máscara binária depois de um encoder e
    aprovou uma máscara dura relatando 21% de borda suave que o codec inventou.
    O `audio-exato.wav` é PCM e é literalmente o que este pipeline decidiu.

(b) O TESTE 3 JULGA POR CONTRASTE, NÃO POR CONSTANTE ABSOLUTA. A diferença
    montado−bruto nunca é zero (o round-trip float→int16 já custa ~1 LSB), e
    quanto ela vale depende do nível da peça. Então a janela da emenda é
    comparada com uma JANELA DE CONTROLE do mesmo take, longe de qualquer
    junção: o que reprova é a emenda destoar do próprio piso de diferença dela.
    Somar eixos de escalas diferentes e comparar com um número fixo é como a
    régua de cor media 0,76 onde a spec previa 0,26 e deixava o defeito passar.
"""
import glob
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import jcut as jcut_mod       # noqa: E402

# FÍSICA / MEDIÇÃO (nada aqui descreve a peça)
MIN_DUR_S = 3.0        # janela de correlação: 2–3 s trava na sílaba errada (§9)
BUSCA_MS = 25.0        # faixa de busca ESTREITA: é ela que remove a periodicidade
LAG_MAX_AMOSTRAS = 1   # |lag| aceitável por take
TEND_MAX = 0.1         # inclinação de lag × índice do take, em amostras/take
CONTRASTE_MAX_DB = 12.0  # quanto a emenda pode destoar do controle do mesmo take
JANELA_EMENDA_S = 0.5
AMBIGUO = 0.9          # concorrente acima disto × o pico → veredito inconclusivo


def le_wav(p, sr, canais=1):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", p, "-vn",
                          "-ac", str(canais), "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def fatia_amostras(a, i0, n):
    """Fatia `[i0, i0+n)` preservando o eixo, inclusive fora do arquivo.

    O clamp antigo fazia `max(0, i0)` sem recolocar as amostras negativas como
    silêncio. Quando a busca do primeiro take pedia 25 ms antes da amostra zero,
    a referência inteira era deslocada 25 ms para a esquerda. A correlação
    devolvia exatamente `-BUSCA_MS` e esse único ponto fabricava uma tendência
    progressiva ao longo da peça.
    """
    i0 = int(i0)
    n = max(0, int(n))
    forma = (n,) + a.shape[1:]
    out = np.zeros(forma, dtype=a.dtype)
    src_lo = max(0, i0)
    src_hi = min(len(a), i0 + n)
    if src_hi > src_lo:
        dst_lo = src_lo - i0
        out[dst_lo:dst_lo + (src_hi - src_lo)] = a[src_lo:src_hi]
    return out


def fatia_bruto_amostras(src, i0, n, sr, cache):
    if src not in cache:
        cache[src] = le_wav(src, sr)
    return fatia_amostras(cache[src], i0, n)


def fatia_bruto(src, t0, dur, sr, cache):
    i0 = int(round(t0 * sr))
    n = int(round(dur * sr))
    return fatia_bruto_amostras(src, i0, n, sr, cache)


def src_offset_samples(s_saida, sr):
    """Offset do bruto na fronteira visual, preferencialmente inteiro.

    Planos antigos só têm `src_offset_s`; continuam legíveis. Planos novos
    carregam `src_offset_samples`, que evita reconstituir uma amostra a partir
    de um decimal arredondado para seis casas.
    """
    if "src_offset_samples" in s_saida:
        return int(s_saida["src_offset_samples"])
    return int(round(float(s_saida["src_offset_s"]) * sr))


def rms_db(x):
    return 20 * math.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-12))


def correlacionar(x, y, L, guarda_amostras):
    """x contra y (y começa L amostras ANTES do esperado) → (lag, pico, ambíguo).

    FFT, não `np.correlate`: com 3 s a 48 kHz e ±25 ms de busca a versão direta
    é 3,5e8 multiplicações por take.

    🔴 O TERCEIRO RETORNO É O QUE IMPEDE UM VERDE SEM SIGNIFICADO. Num sinal
    periódico (tom puro, zumbido de rede, vogal sustentada) a correlação tem
    picos quase iguais a cada período, e o `argmax` escolhe um deles por sorte —
    "lag 0" ali não é sincronia, é acaso. Se existe concorrente a mais de 1 ms do
    escolhido com ≥ 90% da altura dele, o veredito é INCONCLUSIVO, e um
    inconclusivo é reportado como tal em vez de virar linha verde."""
    n = len(x) + len(y)
    nfft = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(y, nfft) * np.conj(np.fft.rfft(x, nfft)), nfft)
    c = c[:2 * L + 1]
    if not len(c):
        return None, 0.0, True
    k = int(np.argmax(c))
    pico = float(c[k])
    if pico <= 0:
        return None, 0.0, True
    viz = np.array(c, dtype=np.float64)
    g = max(1, int(guarda_amostras))
    viz[max(0, k - g):min(len(c), k + g + 1)] = -np.inf
    conc = float(viz.max()) if np.isfinite(viz).any() else 0.0
    return k - L, pico, conc >= AMBIGUO * pico


# ────────────────────────────────────────────────────────────────────── testes

def teste_estrutura(d, plano, edl, tl):
    """Sem mídia. É o que pega o §8(d) — lead forçado numa junção contígua."""
    falhas = []
    contiguas = jcut_mod.junções_contiguas(edl)
    for k in contiguas:
        ent, sai = plano["segmentos"][k + 1], plano["segmentos"][k]
        if ent["lead_frames_in"] or ent["video_skip_frames"]:
            falhas.append(
                "junção %d→%d é CONTÍGUA no bruto (%s: %.3f == %.3f) e o plano manda "
                "lead=%d / skip=%d. Sobrepor aqui faz a MESMA fatia de fala tocar duas "
                "vezes, somada consigo mesma (+6 dB e eco de flanger)."
                % (k, k + 1, os.path.basename(str(edl[k]["src"])), edl[k]["end"],
                   edl[k + 1]["start"], ent["lead_frames_in"], ent["video_skip_frames"]))
        # com `modo: off` ninguém sobrepõe nada e o motivo de TODA junção é `off` —
        # exigir `contiguo` ali reprovaria o plano que está certo por outro caminho.
        if plano.get("modo") != "off" and ent["motivo_lead"] != "contiguo":
            falhas.append("junção %d→%d contígua com motivo_lead=%r (esperado 'contiguo')"
                          % (k, k + 1, ent["motivo_lead"]))
        if plano.get("fades") == "jcut":
            if ent.get("fade_in_s") != 0.0 or sai.get("fade_out_s") != 0.0:
                falhas.append("junção %d→%d contígua com fade (in=%r out=%r): é o dip "
                              "audível numa emenda que não existe"
                              % (k, k + 1, ent.get("fade_in_s"), sai.get("fade_out_s")))
    if plano["segmentos"][0]["lead_frames_in"]:
        falhas.append("o segmento 0 tem lead %d — não há junção antes dele"
                      % plano["segmentos"][0]["lead_frames_in"])
    # o sidecar diz o que foi RENDERIZADO; o plano diz o que se quer
    for i, s in enumerate(plano["segmentos"]):
        side = os.path.join(d, "segs", "seg%03d.json" % i)
        if not os.path.exists(side):
            continue
        with open(side) as fh:
            g = json.load(fh)
        if int(g.get("video_skip_frames", 0)) != int(s["video_skip_frames"]):
            falhas.append("seg%03d: renderizado com skip=%d, plano diz %d — apague "
                          "segs/ e remonte (trilha nova sobre imagem velha sincroniza "
                          "com o vídeo ERRADO e nenhum outro QC acusa)"
                          % (i, int(g.get("video_skip_frames", 0)), s["video_skip_frames"]))
    # o encadeamento do bloco `saida`, quando ele existe
    if plano.get("saida"):
        spf = plano["samples_por_frame"]
        for s, pl in zip(plano["saida"], plano["segmentos"]):
            geo = jcut_mod.geometria_take(
                start_s=pl["start"], video_offset_frames=s["video_offset_frames"],
                video_frames=s["video_frames"], lead_frames=pl["lead_frames_in"],
                sr=plano["sr"], spf=spf)
            esperado = geo["audio_offset_samples"]
            if s["audio_offset_samples"] != esperado:
                falhas.append("saida[%d]: audio_offset %d != v_off−lead = %d"
                              % (s["i"], s["audio_offset_samples"], esperado))
            if s["audio_samples"] != geo["audio_samples"]:
                falhas.append("saida[%d]: audio_samples %d != (frames+lead)×spf"
                              % (s["i"], s["audio_samples"]))
            try:
                src_gravado = src_offset_samples(s, plano["sr"])
            except (KeyError, TypeError, ValueError):
                src_gravado = None
                falhas.append("saida[%d]: falta src_offset_samples/src_offset_s válido"
                              % s["i"])
            if src_gravado is not None and src_gravado != geo["src_visual_samples"]:
                falhas.append("saida[%d]: src_offset_samples %d != start+lead = %d"
                              % (s["i"], src_gravado, geo["src_visual_samples"]))

        # Com ao menos um lead, audio-exato.py publica TODOS os PCM pré-soma.
        # Eles não decidem o lag do mix final, mas provam que cada take foi
        # extraído com a extensão inteira que a geometria acima exige.
        if any(int(x["lead_frames_in"]) for x in plano["segmentos"]):
            esperados = {"seg%03d.wav" % i for i in range(len(plano["segmentos"]))}
            achados = {os.path.basename(p) for p in
                       glob.glob(os.path.join(d, "audio-takes", "seg*.wav"))}
            for nome in sorted(esperados - achados):
                falhas.append("audio-takes/%s ausente: PCM pré-soma do J-cut não "
                              "foi publicado" % nome)
            for nome in sorted(achados - esperados):
                falhas.append("audio-takes/%s órfão: não corresponde à EDL atual"
                              % nome)
            for i, s in enumerate(plano["saida"]):
                p = os.path.join(d, "audio-takes", "seg%03d.wav" % i)
                if not os.path.exists(p):
                    continue
                try:
                    with wave.open(p, "rb") as w:
                        taxa, n_pcm = w.getframerate(), w.getnframes()
                except (OSError, wave.Error) as e:
                    falhas.append("audio-takes/seg%03d.wav inválido: %s" % (i, e))
                    continue
                if taxa != int(plano["sr"]):
                    falhas.append("audio-takes/seg%03d.wav: sr %d != plano %d"
                                  % (i, taxa, plano["sr"]))
                if n_pcm != int(s["audio_samples"]):
                    falhas.append("audio-takes/seg%03d.wav: %d amostras != plano %d"
                                  % (i, n_pcm, s["audio_samples"]))
    print("  [1] estrutura: %d junções (%d contíguas), %d segmentos conferidos"
          % (len(edl) - 1, len(contiguas), len(plano["segmentos"])))
    return falhas


def teste_duracao(d, plano, tl, wav, vid):
    falhas = []
    spf = plano["samples_por_frame"]
    fps = plano["fps"]
    esperado = tl["total_frames"] * spf
    if len(wav) != esperado:
        falhas.append("audio-exato.wav tem %d amostras e Σ frames × spf = %d "
                      "(diferença de %d). A conta é INTEIRA: qualquer delta aqui é "
                      "deriva de A/V esperando para acontecer."
                      % (len(wav), esperado, len(wav) - esperado))
    if os.path.exists(vid):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", vid],
                             capture_output=True, text=True).stdout.strip()
        dur = float(out) if out else 0.0
        delta = abs(dur - tl["total_s"])
        if delta > 1.0 / fps:
            falhas.append("render %.3fs vs Σ frames/fps %.3fs (delta %.1f ms > 1 frame)"
                          % (dur, tl["total_s"], delta * 1000))
        print("  [2] duração: render %.3fs · timeline %.3fs · WAV %d amostras "
              "(esperado %d)" % (dur, tl["total_s"], len(wav), esperado))
    else:
        print("  [2] duração: %s ausente — só o WAV foi conferido (%d amostras, "
              "esperado %d)" % (os.path.basename(vid), len(wav), esperado))
    return falhas


def _ref_do_take(s_saida, lo, hi, src, sr, spf, cache):
    """A fatia de bruto que o take `s_saida` põe no intervalo de saída [lo, hi).

    🔴 Cada lado da fronteira é mapeado pelo SEU take, nunca pelo do vizinho.
    A versão anterior desta função assumia que numa junção contígua o bruto
    atravessava a fronteira sem salto — e não atravessa: `frames/fps` quase
    nunca é igual a `end−start`, então sobra ou falta um pedaço sub-frame. Isso
    é propriedade do render (existe hoje, sem J-cut), não defeito de emenda, e
    medi-lo como se fosse desalinhamento produzia +69 dB de falso positivo. O
    tamanho desse pedaço é reportado à parte, em ms."""
    i0 = (src_offset_samples(s_saida, sr)
          + lo - s_saida["video_offset_frames"] * spf)
    return fatia_bruto_amostras(src, i0, hi - lo, sr, cache)


def teste_contiguas(plano, edl, wav, sr, cache):
    """Nas junções contíguas o montado TEM que ser o bruto, sem emenda.

    O veredito é o contraste contra uma janela de controle do mesmo take (ver
    o cabeçalho, (b)): duplicação de fatia e dip de fade destoam do piso de
    diferença da peça; o round-trip de quantização não."""
    falhas = []
    spf = plano["samples_por_frame"]
    fps = plano["fps"]
    contiguas = jcut_mod.junções_contiguas(edl)
    saida = {s["i"]: s for s in (plano.get("saida") or [])}
    if not contiguas:
        print("  [3] contíguas: nenhuma junção contígua nesta EDL — nada a afirmar")
        return falhas
    if not saida:
        print("  [3] contíguas: bloco `saida` ausente — rode `jcut.py <dir> --medir`")
        return ["bloco `saida` ausente: sem ele não dá para mapear saída → bruto"]
    n_jan = int(JANELA_EMENDA_S * sr)
    for k in contiguas:
        s_ant, s_pos = saida[k], saida[k + 1]
        v0 = s_ant["video_offset_frames"] * spf
        b = v0 + s_ant["video_frames"] * spf          # fronteira de IMAGEM
        v1 = s_pos["video_offset_frames"] * spf
        lo = max(v0, b - n_jan)
        hi = min(v1 + s_pos["video_frames"] * spf, b + n_jan, len(wav))
        src = edl[k]["src"]
        ref = np.concatenate([
            _ref_do_take(s_ant, lo, b, src, sr, spf, cache),
            _ref_do_take(s_pos, b, hi, src, sr, spf, cache)])
        emenda = rms_db(wav[lo:hi] - ref)
        # controle: MESMA largura, dentro do mesmo take, longe da fronteira
        c_hi = lo
        c_lo = max(v0, c_hi - (hi - lo))
        lado, s_ctl = "antes", s_ant
        if c_hi - c_lo < n_jan // 2:
            c_lo = hi
            c_hi = min(v1 + s_pos["video_frames"] * spf, c_lo + (hi - lo), len(wav))
            lado, s_ctl = "depois", s_pos
        if c_hi - c_lo < n_jan // 2:
            controle = None
        else:
            refc = _ref_do_take(s_ctl, c_lo, c_hi, src, sr, spf, cache)
            controle = rms_db(wav[c_lo:c_hi] - refc)
        # o pedaço sub-frame: quanto de bruto o take que sai repete (ou pula)
        sobra_amostras = (src_offset_samples(s_ant, sr)
                           + s_ant["video_frames"] * spf
                           - src_offset_samples(s_pos, sr))
        sobra_ms = sobra_amostras * 1000.0 / sr
        print("  [3] contígua %2d→%2d: emenda %7.1f dBFS · controle(%s) %s · Δ %s · "
              "quantização %+.1f ms"
              % (k, k + 1, emenda, lado,
                 "%7.1f dBFS" % controle if controle is not None else "  n/d  ",
                 "%+6.1f dB" % (emenda - controle) if controle is not None else " n/d ",
                 sobra_ms))
        if controle is not None and emenda - controle > CONTRASTE_MAX_DB:
            falhas.append("junção contígua %d→%d: a diferença montado−bruto na emenda "
                          "está %.1f dB acima do controle do mesmo take (%.1f vs %.1f "
                          "dBFS, limite %.0f dB). Ou a fatia tocou duas vezes (J-cut "
                          "sobre junção contígua) ou há um micro-fade no meio de uma "
                          "frase que atravessa."
                          % (k, k + 1, emenda - controle, emenda, controle,
                             CONTRASTE_MAX_DB))
        if abs(sobra_ms) > 1000.0 / fps + 1e-6:
            falhas.append("junção contígua %d→%d: o take que sai cobre %+.1f ms de "
                          "bruto além do que o que entra começa — mais de 1 frame. "
                          "`frames` e `video_skip_frames` não fecham com a EDL."
                          % (k, k + 1, sobra_ms))
    return falhas


def teste_sincronia(plano, edl, wav, sr, cache, min_dur, busca_ms):
    falhas = []
    spf = plano["samples_por_frame"]
    fps = plano["fps"]
    saida = {s["i"]: s for s in (plano.get("saida") or [])}
    if not saida:
        return ["bloco `saida` ausente: sem ele não dá para medir sincronia"]
    L = int(round(busca_ms / 1000.0 * sr))
    lags, idx, ambiguos, curtos, aparados = [], [], 0, 0, 0
    for s in plano["saida"]:
        i = int(s["i"])
        pl = plano["segmentos"][i]
        geo = jcut_mod.geometria_take(
            start_s=edl[i]["start"], video_offset_frames=s["video_offset_frames"],
            video_frames=s["video_frames"], lead_frames=pl["lead_frames_in"],
            sr=sr, spf=spf)

        # O final do take k contém o take k+1 somado durante o próximo lead.
        # Correlação contra uma única fonte nessa região mede interferência,
        # não sincronia. Retiramos EXATAMENTE a sobreposição declarada seguinte;
        # a região avaliada continua começando na fronteira visual e permanece
        # no WAV final, portanto um erro real de posicionamento ainda aparece.
        prox_lead = 0
        if i + 1 < len(plano["segmentos"]):
            prox_lead = int(plano["segmentos"][i + 1]["lead_frames_in"]) * spf
        n = geo["video_samples"] - prox_lead
        if prox_lead:
            aparados += 1
        dur = n / sr
        if dur < min_dur:
            curtos += 1
            continue
        lo = geo["video_offset_samples"]
        x = fatia_amostras(wav, lo, n)
        y = fatia_bruto_amostras(edl[i]["src"],
                                 geo["src_visual_samples"] - L,
                                 n + 2 * L, sr, cache)
        lag, pico, ambiguo = correlacionar(x, y, L, int(0.001 * sr))
        if lag is None or ambiguo:
            ambiguos += 1
            print("  [4] take %2d: correlação AMBÍGUA (sinal periódico na faixa de "
                  "±%.0f ms) — sem veredito" % (i, busca_ms))
            continue
        lags.append(lag)
        idx.append(i)
        marca = "ok" if abs(lag) <= LAG_MAX_AMOSTRAS else "⚠️"
        print("  [4] take %2d: lag %+4d amostra(s) (%+.3f ms) %s  [%.1fs]"
              % (i, lag, lag * 1000.0 / sr, marca, dur))
        if abs(lag) > LAG_MAX_AMOSTRAS:
            falhas.append("take %d: lag de %d amostras (%.3f ms) contra o bruto "
                          "(limite %d)" % (i, lag, lag * 1000.0 / sr, LAG_MAX_AMOSTRAS))
    if len(lags) >= 3:
        incl = float(np.polyfit(idx, lags, 1)[0])
        print("  [4] tendência: %+.4f amostra por take (limite %.2f) — %d take(s) "
              "medido(s), %d curto(s) (< %.1fs), %d ambíguo(s), %d cauda(s) "
              "aparada(s) pelo lead seguinte"
              % (incl, TEND_MAX, len(lags), curtos, min_dur, ambiguos, aparados))
        if abs(incl) > TEND_MAX:
            falhas.append("deriva progressiva: %+.3f amostra por take. Constante é "
                          "offset; com tendência é a quantização acumulando de novo "
                          "(o bug de 2026-07-25)." % incl)
    else:
        print("  [4] sincronia: só %d take(s) com ≥ %.1fs — sem regressão de "
              "tendência (%d curtos, %d ambíguos)"
              % (len(lags), min_dur, curtos, ambiguos))
    return falhas


def teste_pico(plano, wav, sr):
    falhas = []
    spf = plano["samples_por_frame"]
    saida = {s["i"]: s for s in (plano.get("saida") or [])}
    n_sobre = 0
    pior = 0.0
    for i, s in enumerate(plano["segmentos"]):
        lead = int(s["lead_frames_in"])
        if lead <= 0 or i not in saida:
            continue
        n_sobre += 1
        b = saida[i]["video_offset_frames"] * spf
        lo, hi = max(0, b - lead * spf), b
        pico = float(np.abs(wav[lo:hi]).max()) if hi > lo else 0.0
        pior = max(pior, pico)
        if pico >= 1.0:
            falhas.append("junção %d→%d: pico %.3f na janela de sobreposição — o "
                          "np.clip cortaria isso em silêncio" % (i - 1, i, pico))
    print("  [5] pico: %d janela(s) de sobreposição · maior pico %.3f (limite 1,0)"
          % (n_sobre, pior))
    return falhas


# ────────────────────────────────────────────────────────────────────────── CLI

def main(argv):
    d = ([a for a in argv if not a.startswith("--")] or ["."])[0]

    def flag(nome, default=None):
        return argv[argv.index(nome) + 1] if nome in argv else default

    vid = os.path.join(d, flag("--video", "v1-montado.mp4"))
    wavp = os.path.join(d, flag("--wav", "audio-exato.wav"))
    min_dur = float(flag("--min-dur", MIN_DUR_S))
    busca_ms = float(flag("--busca-ms", BUSCA_MS))

    edl = edl_io.segmentos(d)
    # 🔴 `exigir=True` FAZ A AUSÊNCIA REPROVAR (achado A15). O item de bateria
    # declarava `requer: jcut.json`, então sem o arquivo este script nem era
    # chamado: saía `nao_verificado/insumo` — a MESMA cara de "o creator decidiu
    # não aplicar" e de "ninguém pensou no assunto". A decisão de NÃO aplicar
    # agora é um artefato (`jcut.py <dir> --nao-aplicar --motivo "..."`), e a
    # falta dele é falta de decisão, que é o defeito.
    plano = jcut_mod.carregar(d, edl, exigir=True)
    if plano.get("aplicar") is False:
        print("qc-jcut · J-CUT NÃO APLICADO nesta peça, por decisão registrada\n"
              "  por %s em %s\n  motivo: %s\n"
              "  (a EDL confere: o fingerprint gravado descreve ESTE corte)"
              % (plano.get("decidido_por") or "?", plano.get("decidido_em") or "?",
                 plano.get("motivo") or "—"))
        print("\nqc-jcut OK — decisão negativa registrada, nada a medir",
              file=sys.stderr)
        return 0
    tl = edl_io.timeline(d, exigir=True)
    sr = plano["sr"]
    if not os.path.exists(wavp):
        sys.exit("%s não existe — rode `montar.sh %s` antes do QC" % (wavp, d))
    wav = le_wav(wavp, sr)
    cache = {}
    os.chdir(d)          # os `src` da EDL são relativos à pasta da produção

    print("qc-jcut · modo %s · teto %g ms · %d fps · %d segmentos · %d junção(ões) "
          "com lead" % (plano["modo"], plano["lead_max_ms"], plano["fps"], len(edl),
                        sum(1 for s in plano["segmentos"] if s["lead_frames_in"])))
    falhas = []
    falhas += teste_estrutura(".", plano, edl, tl)
    falhas += teste_duracao(".", plano, tl, wav, os.path.basename(vid))
    falhas += teste_contiguas(plano, edl, wav, sr, cache)
    falhas += teste_sincronia(plano, edl, wav, sr, cache, min_dur, busca_ms)
    falhas += teste_pico(plano, wav, sr)

    if falhas:
        print("\n%d REPROVAÇÃO(ÕES):" % len(falhas), file=sys.stderr)
        for f in falhas:
            print("  ✗ " + f, file=sys.stderr)
        return 1
    print("\nqc-jcut OK — 5 testes, %d junção(ões) contígua(s) e %d com lead"
          % (len(jcut_mod.junções_contiguas(edl)),
             sum(1 for s in plano["segmentos"] if s["lead_frames_in"])), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
