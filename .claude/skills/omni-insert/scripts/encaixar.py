#!/usr/bin/env python3
"""Encaixa um plano gerado (insert) numa janela da base, SEM alterar a timeline.

Regra de ouro herdada da correção de 2026-07-25 (deriva A/V): nada de concat.
O insert entra por OVERLAY numa janela [t_in, t_out] — a duração do vídeo e a
trilha de áudio ficam intocadas (áudio é copiado bit a bit).

Uso:
  encaixar.py --base v1-montado.mp4 --insert gerado.mp4 --in 2.5 --out 8.0 \
              --transicao dissolve --saida v-insert.mp4 [--dur-transicao 0.30]

Transições: corte | dissolve | flash
Imprime o caminho do artefato no stdout; logs no stderr.
"""
import argparse
import json
import math
import os
import subprocess
import sys


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], round(int(num) / int(den)), float(d["format"]["duration"])


def _frame_rgb(path, t):
    import io
    import numpy as np
    from PIL import Image
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-vframes", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    return np.asarray(Image.open(io.BytesIO(r)).convert("RGB"), dtype=float)


def ganhos_color_match(base, insert, t_in, t_out, idur):
    """Ganho por canal pra casar a mediana do insert com a da base VIZINHA à janela.

    Compara com os frames imediatamente antes e depois do corte — é ali que o olho
    faz a comparação. Clampado em ±40% pra não inventar cor quando a cena é
    legitimamente diferente (noite vs dia).
    """
    import numpy as np
    antes = max(0.0, t_in - 1.0)
    depois = t_out + 1.0
    amostras_base = [_frame_rgb(base, antes), _frame_rgb(base, depois)]
    ins = _frame_rgb(insert, min(idur / 2, 3.0))
    med = lambda a: np.array([np.percentile(a[:, :, i], 50) for i in range(3)])
    alvo = np.mean([med(x) for x in amostras_base], axis=0)
    atual = med(ins)
    g = np.clip(alvo / np.maximum(atual, 1.0), 0.6, 1.4)
    return [round(float(x), 3) for x in g]


FATIA_RT = 0.25  # segundos de room tone que serão repetidos em loop


def achar_room_tone(base):
    """Fatia curta e mais silenciosa do áudio da base — o 'som da sala'.

    Abertura em silêncio digital soa quebrada; o ambiente gerado pelo Omni
    costuma vir mudo de verdade (medido: 0,1% de fundo de escala). O leito certo
    é o room tone da PRÓPRIA gravação — mesma sala, mesmo ruído de fundo.

    Procura-se uma fatia curta (0,25s) e repete-se em loop: num talking-head o
    creator fala quase o tempo todo, e janelas longas de silêncio não existem —
    buscar 2s "mais silenciosos" devolve fala baixa, não ambiente (testado).
    """
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", base, "-f", "s16le",
                        "-ac", "1", "-ar", "8000", "-"], capture_output=True).stdout
    x = np.abs(np.frombuffer(r, dtype=np.int16).astype(float))
    w = int(8000 * FATIA_RT)
    if len(x) < w * 4:
        return None, 0.0
    n = len(x) // w
    blocos = x[:n * w].reshape(n, w).mean(1)
    pico = float(blocos.max())
    vivos = np.where(blocos > pico * 0.002)[0]  # descarta silêncio digital puro
    if not len(vivos):
        return None, 0.0
    idx = int(vivos[np.argmin(blocos[vivos])])
    nivel = blocos[idx] / pico
    return round(idx * FATIA_RT, 3), float(nivel)


def ganho_casado(base, insert, t1, t2, teto=3.0):
    """Ganho que iguala o RMS do insert ao da MESMA janela da base.

    Comparar contra a janela certa importa: usar o vídeo inteiro como referência
    puxaria o nível pra média de trechos com outra intensidade de fala.
    """
    import numpy as np

    def rms(path, ss, dur):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ss), "-i", path, "-t", str(dur),
                            "-vn", "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True).stdout
        x = np.frombuffer(r, dtype=np.int16).astype(float)
        return float(np.sqrt((x ** 2).mean())) if len(x) else 0.0

    dur = t2 - t1
    alvo, atual = rms(base, t1, dur), rms(insert, 0, dur)
    if atual < 1 or alvo < 1:
        return 1.0
    return float(min(max(alvo / atual, 1 / teto), teto))


# 🔴 RD-5: O SAMPLE RATE É DADO, NÃO CÓDIGO (achado A22 da auditoria de
# 2026-08-10). Este era o ÚNICO bloco da ilha que não lia perfil nenhum: 48000
# cravado, replicado em 5 usos. Hoje é inócuo — todos os perfis do catálogo têm
# `audio.sr = 48000`, medido — e é exatamente por isso que ele passou por
# quatro ondas sem ninguém ver. O primeiro perfil com sr ≠ 48000 faria o insert
# derivar do A/V em silêncio: a trilha seria montada numa grade e o vídeo
# noutra.
#
# O modelo do fallback é `buscar.py:297-302`, que a própria auditoria cita como
# "o RD-5 feito certo": o número existe, é DECLARADO, e o script diz de onde
# tirou o que usou.
SR_FALLBACK = 48000


def sr_do_perfil(dir_producao=None, quieto=False):
    """(sr, fonte). `fonte ∈ {perfil.json, env, fallback}` — nunca adivinha calado.

    A ordem: `<dir>/perfil.json` (o contrato `benchmark.perfil-peca/v1`, que é um
    ARQUIVO e não exige a skill que o escreveu) → `$BENCH_SR` → o fallback
    declarado acima."""
    cand = []
    if dir_producao:
        cand.append(os.path.join(dir_producao, "perfil.json"))
    cand.append(os.path.join(os.path.dirname(os.path.abspath(dir_producao or ".")),
                             "perfil.json"))
    for c in cand:
        try:
            with open(c, encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            continue
        sr = ((obj or {}).get("audio") or {}).get("sr")
        if sr:
            return int(sr), "perfil.json"
    env = os.environ.get("BENCH_SR")
    if env and env.isdigit():
        return int(env), "env"
    if not quieto:
        log(f"[audio] sr do perfil não encontrado — usando o FALLBACK declarado "
            f"({SR_FALLBACK} Hz). Passe --dir-producao <dir> com perfil.json, ou "
            f"BENCH_SR=<n>.")
    return SR_FALLBACK, "fallback"


def trilha_com_janela(base, insert, t1, t2, ganho, cross=0.06, sr=SR_FALLBACK):
    """Trilha da base com a janela [t1,t2] substituída pela do insert, em numpy.

    Amostra a amostra, com crossfade nas duas bordas. Determinístico: o que entra
    na janela é exatamente `insert × ganho`, e o resto é a base intocada — coisa
    que o `amix` do ffmpeg não entregou (ver comentário no chamador).
    """
    import wave
    import numpy as np

    def pcm(p):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vn", "-f", "s16le",
                            "-ac", "1", "-ar", str(sr), "-"], capture_output=True).stdout
        return np.frombuffer(r, dtype=np.int16).astype(np.float32)

    b, ins = pcm(base), pcm(insert) * ganho
    i1, i2 = int(round(t1 * sr)), int(round(t2 * sr))
    i2 = min(i2, len(b), i1 + len(ins))
    n = i2 - i1
    if n <= 0:
        raise SystemExit("janela vazia ao montar a trilha")
    out = b.copy()
    janela = ins[:n].copy()
    w = max(1, int(cross * sr))
    if n > 2 * w:                       # crossfade nas bordas, sem clique
        rampa = np.linspace(0, 1, w, dtype=np.float32)
        janela[:w] = janela[:w] * rampa + b[i1:i1 + w] * (1 - rampa)
        janela[-w:] = janela[-w:] * rampa[::-1] + b[i2 - w:i2] * rampa
    out[i1:i2] = janela
    out = np.clip(out, -32768, 32767).astype(np.int16)
    dest = os.path.join(os.path.dirname(os.path.abspath(insert)) or ".", "_trilha-encaixe.wav")
    with wave.open(dest, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(out.tobytes())
    return dest


def medir_deslocamento(base, saida, dur=12):
    """Offset real da fala entre base e saída, por correlação de envelope.

    ⚠️ Alinhar ANTES de comparar: 80ms de offset derrubam a correlação de 0,97
    para 0,15 em janela de 10ms — foi assim que um resultado íntegro passou por
    "fala alterada" uma vez.
    """
    import numpy as np

    def pcm(p, d):
        cmd = ["ffmpeg", "-v", "error", "-i", p, "-t", str(d),
               "-f", "s16le", "-ac", "1", "-ar", "8000", "-"]
        r = subprocess.run(cmd, capture_output=True).stdout
        return np.frombuffer(r, dtype=np.int16).astype(float)

    def env(x, w=40):
        n = len(x) // w * w
        return np.abs(x[:n]).reshape(-1, w).mean(1)

    ea, eb = env(pcm(base, dur)), env(pcm(saida, dur + 5))
    c = np.correlate(eb - eb.mean(), ea - ea.mean(), "valid")
    return int(c.argmax()) * 40 / 8000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--insert", required=True)
    p.add_argument("--in", dest="t_in", type=float, default=0)
    p.add_argument("--out", dest="t_out", type=float, default=0)
    p.add_argument("--saida", required=True)
    p.add_argument("--dir-producao", default=None,
                   help="de onde sai o sample rate da trilha (perfil.json). Sem ele, $BENCH_SR e depois o fallback declarado — e o script diz qual usou.")
    p.add_argument("--transicao", default="dissolve", choices=["corte", "dissolve", "flash"])
    p.add_argument("--dur-transicao", type=float, default=0.30)
    p.add_argument("--audio", default="base", choices=["base", "insert"],
                   help="'insert' usa a trilha devolvida pelo Omni na janela "
                        "(no modo edit ele preserva a voz do creator e o lip sync)")
    p.add_argument("--color-match", action="store_true",
                   help="casa a mediana de cor do insert com a da base vizinha à janela")
    p.add_argument("--cold-open", type=float, default=0,
                   help="segundos de plano ANTES da base (abertura); ignora --in/--out")
    p.add_argument("--jcut", type=float, default=0.5,
                   help="segundos que a VOZ da base entra antes do corte de imagem (0 desliga)")
    p.add_argument("--vol-ambiente", type=float, default=0.5,
                   help="volume da trilha do plano quando --leito plano")
    p.add_argument("--leito", default="room-tone", choices=["room-tone", "plano", "silencio"],
                   help="o que toca na abertura antes da voz entrar")
    p.add_argument("--nitidez", default="unsharp",
                   choices=["nenhum", "unsharp", "unsharp+grao"])
    p.add_argument("--flash-frames", type=int, default=2)
    p.add_argument("--flash-opacidade", type=float, default=0.7)
    p.add_argument("--crf", default="18")
    a = p.parse_args()

    bw, bh, bfps, bdur = probe(a.base)
    iw, ih, ifps, idur = probe(a.insert)
    janela = a.cold_open if a.cold_open else a.t_out - a.t_in
    log(f"[base] {bw}x{bh}@{bfps} {bdur:.2f}s | [insert] {iw}x{ih}@{ifps} {idur:.2f}s | janela {janela:.2f}s")
    if janela <= 0:
        sys.exit("informe --in/--out (janela) ou --cold-open <segundos>")
    if idur < janela - 0.05:
        sys.exit(f"insert curto demais: {idur:.2f}s < janela {janela:.2f}s")
    if not a.cold_open and a.t_out > bdur:
        sys.exit(f"janela termina em {a.t_out}s, além da base ({bdur:.2f}s)")

    d = a.dur_transicao
    # o insert é reamostrado pro canvas da base (lanczos + fps) dentro do mesmo grafo.
    # O upscale 1.5x (720p→1080p) custa nitidez: medido na base nativa da creator-2,
    # variância do laplaciano cai de 141 (base) pra 47 na região com detalhe;
    # unsharp recupera pra 97 sem inventar textura. Grão só por cima disso.
    trat = {"nenhum": "",
            "unsharp": ",unsharp=5:5:0.8:5:5:0.0",
            "unsharp+grao": ",unsharp=5:5:0.8:5:5:0.0,noise=alls=6:allf=t+u"}[a.nitidez]
    if a.color_match:
        gr, gg, gb = ganhos_color_match(a.base, a.insert, a.t_in, a.t_out, idur)
        log(f"[cor] ganhos medidos R={gr} G={gg} B={gb}")
        trat += f",colorchannelmixer=rr={gr}:gg={gg}:bb={gb}"
    norm = f"scale={bw}:{bh}:flags=lanczos{trat},fps={bfps},format=yuva420p"
    if a.transicao == "corte":
        ins = f"[1:v]{norm}[ins]"
        extra = ""
        chain = f"[0:v][ins]overlay=enable='between(t,{a.t_in},{a.t_out})':eof_action=pass[v]"
    elif a.transicao == "dissolve":
        ins = (f"[1:v]{norm},fade=t=in:st={a.t_in}:d={d}:alpha=1,"
               f"fade=t=out:st={a.t_out-d:.3f}:d={d}:alpha=1[ins]")
        extra = ""
        chain = f"[0:v][ins]overlay=enable='between(t,{a.t_in},{a.t_out})':eof_action=pass[v]"
    else:  # flash — N frames de branco em cada emenda, escondem a troca de textura
        meia = (a.flash_frames / 2) / bfps
        alpha = int(255 * a.flash_opacidade)
        ins = f"[1:v]{norm}[ins]"
        extra = (f"color=white:s={bw}x{bh}:r={bfps}:d={bdur}[w];"
                 f"[w]format=yuva420p,geq=r='r(X,Y)':a='{alpha}*("
                 f"between(T,{a.t_in-meia:.4f},{a.t_in+meia:.4f})"
                 f"+between(T,{a.t_out-meia:.4f},{a.t_out+meia:.4f}))'[fl];")
        chain = (f"[0:v][ins]overlay=enable='between(t,{a.t_in},{a.t_out})':eof_action=pass[vv];"
                 f"[vv][fl]overlay=0:0:eof_action=pass[v]")

    # 🔴 O `sr` É RESOLVIDO AQUI, ANTES DE QUALQUER RAMO (achado R-14, 2026-08-11).
    # A SPEC-33 trocou os literais de 48000 por `sr_do_perfil()` — e a chamada
    # ficou DEPOIS do `return` do ramo `--cold-open`, que continuou com dois
    # `48000` cravados: o `aloop` do room tone e o `anullsrc` do silêncio. Numa
    # peça a 44,1 kHz o leito de abertura saía com o tamanho errado, o que é a
    # RD-5 violada exatamente no caminho que ninguém tinha exercido.
    sr, fonte_sr = sr_do_perfil(a.dir_producao)

    if a.cold_open:
        # abertura: o plano entra ANTES do primeiro frame da base. Aqui a timeline
        # muda por definição — então é UMA emenda só, com os dois streams cortados
        # no mesmo grafo (nada de concat por segmento, que é o que gera deriva).
        n = a.cold_open
        j = min(a.jcut, n - 0.2) if a.jcut else 0.0
        desloc = n - j
        # J-cut: a VOZ da base entra `j` segundos antes do corte de imagem. Pra
        # isso o vídeo da base começa em `j` (esses frames ficam cobertos pelo
        # plano) — vídeo e áudio da base seguem sincronizados entre si.
        # Silêncio absoluto na abertura soa quebrado (feedback do creator-1): o
        # padrão é o ambiente do próprio plano, com fade antes da voz entrar.
        tem_audio = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", a.insert],
            capture_output=True, text=True).stdout.strip() != ""
        fade_ini = max(0.0, desloc - 0.5)
        rt, nivel = achar_room_tone(a.base) if a.leito == "room-tone" else (None, 0)
        if rt is not None:
            log(f"[cold-open] leito = room tone da gravação ({rt}s, {nivel*100:.1f}% do pico) em loop")
            amb = (f"[a1]atrim=start={rt}:end={rt + FATIA_RT:.3f},asetpts=N/SR/TB,"
                   f"aloop=loop=-1:size={int(FATIA_RT * sr)},atrim=0:{desloc},"
                   f"asetpts=PTS-STARTPTS,"
                   f"afade=t=in:st=0:d=0.3,afade=t=out:st={fade_ini:.3f}:d=0.5[amb]")
        elif a.leito == "plano" and tem_audio and a.vol_ambiente > 0:
            amb = (f"[1:a]atrim=0:{desloc},asetpts=PTS-STARTPTS,"
                   f"volume={a.vol_ambiente},"
                   f"afade=t=in:st=0:d=0.3,afade=t=out:st={fade_ini:.3f}:d=0.5[amb]")
        else:
            amb = (f"anullsrc=r={sr}:cl=stereo,atrim=0:{desloc},"
                   f"asetpts=PTS-STARTPTS[amb]")
            log("[cold-open] ⚠️ abertura em silêncio digital — costuma soar quebrado")
        atraso = int(round(desloc * 1000))
        # 🔴 O SPLIT SÓ EXISTE SE O LEITO USAR O SEGUNDO RAMO (2026-08-11).
        # `asplit=2[a1][a2]` era incondicional, e só o braço `room-tone` consome
        # o `[a1]`. Com `--leito plano|silencio` o `[a1]` ficava PENDURADO, e um
        # filtergraph com saída não consumida é inválido: o ffmpeg recusa com
        # "Error binding filtergraph inputs/outputs: Invalid argument", que não
        # nomeia nem o rótulo nem o motivo. Medido ao exercer o `--cold-open`
        # pela primeira vez, com um plano sem trilha de áudio — dois dos três
        # leitos estavam mortos.
        usa_a1 = "[a1]" in amb
        split = "[0:a]asplit=2[a1][a2];" if usa_a1 else "[0:a]acopy[a2];"
        fc = (f"[1:v]scale={bw}:{bh}:flags=lanczos{trat},fps={bfps},format=yuv420p,"
              f"trim=0:{n},setpts=PTS-STARTPTS[cold];"
              f"[0:v]trim=start={j},setpts=PTS-STARTPTS[bv];"
              f"[cold][bv]concat=n=2:v=1:a=0[v];"
              f"{split}{amb};"
              f"[a2]asetpts=PTS-STARTPTS,adelay={atraso}|{atraso}[voz];"
              f"[amb][voz]amix=inputs=2:duration=longest:normalize=0[a]")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", a.base, "-i", a.insert,
               "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-crf", a.crf, "-preset", "medium",
               "-c:a", "aac", "-b:a", "192k", a.saida]
        log(f"[cold-open] {n}s de plano + J-cut de {j}s (voz entra em {desloc:.2f}s)"
            f" · sr {sr} Hz (fonte: {fonte_sr})")
        subprocess.run(cmd, check=True)
        # QC: aqui o áudio é re-encodado, então md5 não serve. Mede-se o
        # deslocamento REAL por correlação de envelope — é o número que precisa
        # ser somado a todos os timestamps de legenda/overlay.
        lag = medir_deslocamento(a.base, a.saida)
        marca = "✅" if abs(lag - desloc) < 0.03 else "⚠️"
        log(f"[qc] deslocamento medido {lag:.4f}s (alvo {desloc:.4f}s) {marca}")
        log(f"[qc] some {desloc:.3f}s a TODOS os timestamps de legenda/overlay")
        print(a.saida)
        return

    fc = f"{ins};{extra}{chain}"
    if a.audio == "insert":
        # No modo `edit` o Omni DEVOLVE a voz do creator (medido: F0 177,8→174,9 Hz,
        # similaridade espectral 0,953, mesmas palavras) já casada com os lábios que
        # ele gerou. Nesse caso a trilha certa na janela é a DELE, não a da base.
        # ⚠️ Duas armadilhas do ffmpeg, ambas custaram um demo dessincronizado:
        #  1. `amix` NÃO respeita o `-itsoffset` do input — ele alinha pelo primeiro
        #     sample de cada entrada. A voz do insert caía em 0,00s. Posicionar
        #     sempre com `adelay` explícito.
        #  2. `afade=out` zera o sinal PARA SEMPRE; um `afade=in` em série depois
        #     multiplica zero por rampa e o resultado é silêncio (o trecho após a
        #     janela sumia). Para tirar-e-devolver o ganho, usar `volume` com
        #     expressão temporal, que é reversível.
        c = 0.06
        t1, t2 = a.t_in, a.t_out
        env = (f"if(lt(t,{t1 - c:.3f}),1,"
               f"if(lt(t,{t1:.3f}),({t1:.3f}-t)/{c},"
               f"if(lt(t,{t2:.3f}),0,"
               f"if(lt(t,{t2 + c:.3f}),(t-{t2:.3f})/{c},1))))")
        atraso = int(round(t1 * 1000))
        # A trilha é montada em NUMPY, amostra a amostra — não com amix.
        # ⚠️ O `amix` não é confiável aqui: medido neste grafo, os ramos isolados
        # davam 0 (base zerada na janela) e 2211 (insert), e o amix devolvia 3127
        # (= √2 × 2211) em vez de 2211. Com `amerge+pan` saía 4422 (= 2×). Somar
        # em numpy é determinístico e é o que o `audio-exato.py` já faz no projeto.
        g = ganho_casado(a.base, a.insert, t1, t2)
        log(f"[audio] nível do insert: ganho {20 * math.log10(max(g, 1e-6)):+.1f} dB pra casar com a base")
        log(f"[audio] sample rate {sr} Hz (fonte: {fonte_sr})")
        trilha = trilha_com_janela(a.base, a.insert, t1, t2, g, cross=c, sr=sr)
        amap, acodec = "2:a", ["-c:a", "aac", "-b:a", "192k"]
        extra_in = ["-i", trilha]
    else:
        amap, acodec = "0:a", ["-c:a", "copy"]
        extra_in = []
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", a.base,
           "-itsoffset", str(a.t_in), "-i", a.insert, *extra_in,
           "-filter_complex", fc, "-map", "[v]", "-map", amap,
           "-c:v", "libx264", "-crf", a.crf, "-preset", "medium",
           *acodec, a.saida]
    log(f"[encaixe] transição={a.transicao} janela={a.t_in}–{a.t_out}s áudio={a.audio}")
    subprocess.run(cmd, check=True)

    # QC obrigatório: a trilha tem que sair IDÊNTICA à da base (prova de não-deriva)
    def audio_md5(path):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", f"{bdur:.3f}",
                            "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True, check=True).stdout
        import hashlib
        return hashlib.md5(r).hexdigest()

    if a.audio == "insert":
        # A trilha muda DENTRO da janela por decisão. Provar duas coisas — foi a
        # ausência disto que deixou passar um demo com a voz do insert tocando em
        # 0,00s e silêncio total depois da janela:
        import numpy as np

        def pcm(p, ss, dur):
            c = ["ffmpeg", "-v", "error"] + (["-ss", str(ss)] if ss else [])
            c += ["-i", p, "-t", str(dur), "-f", "s16le", "-ac", "1", "-ar", "8000", "-"]
            return np.frombuffer(subprocess.run(c, capture_output=True).stdout,
                                 dtype=np.int16).astype(float)

        def envel(x, w=40):
            n = len(x) // w * w
            return np.abs(x[:n]).reshape(-1, w).mean(1) if n else np.array([])

        # 1) a voz do insert caiu EM CIMA da janela?
        ei = envel(pcm(a.insert, 0, min(idur, 4)))
        er = envel(pcm(a.saida, 0, min(bdur, a.t_out + 4)))
        if len(ei) > 4 and len(er) > len(ei):
            cc = np.correlate(er - er.mean(), ei - ei.mean(), "valid")
            pos = int(cc.argmax()) * 40 / 8000
            ok = abs(pos - a.t_in) < 0.15
            log(f"[qc] voz do insert posicionada em {pos:.2f}s (alvo {a.t_in:.2f}s) "
                f"{'✅' if ok else '❌ desalinhada'}")
        # 2) fora da janela a trilha continua sendo a da base?
        for rot, ss, dur in (("antes ", 0.0, max(0.0, a.t_in - 0.2)),
                             ("depois", a.t_out + 0.2, max(0.0, bdur - a.t_out - 0.4))):
            if dur < 0.5:
                continue
            eb = np.abs(pcm(a.base, ss, min(dur, 6))).mean()
            es = np.abs(pcm(a.saida, ss, min(dur, 6))).mean()
            ok = abs(es - eb) / max(eb, 1) < 0.05
            log(f"[qc] energia {rot} da janela: base {eb:.0f} · saída {es:.0f} "
                f"{'✅' if ok else '❌ trilha da base alterada fora da janela'}")
        log("[qc] rode qc-fala.py pra conferir que a fala saiu íntegra")
    elif audio_md5(a.base) == audio_md5(a.saida):
        log("[qc] áudio idêntico à base ✅ (sem deriva)")
    else:
        log("[qc] ⚠️ áudio DIFERENTE da base — investigar antes de aprovar")

    print(a.saida)


if __name__ == "__main__":
    main()
