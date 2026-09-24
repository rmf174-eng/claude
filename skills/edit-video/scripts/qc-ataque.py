#!/usr/bin/env python3
"""QC de SÍLABA VAZADA na emenda — o que o QC por ASR estruturalmente não pega.

Motivo (defeitos entregues ao creator-1 em 2026-07-27): quando o corte cai dentro da rampa
de ataque da palavra seguinte, o segmento leva junto um fragmento de 40–90 ms. O ouvido
acusa na hora ("as IAs para trabalhar **pra**"), mas o `qc-emendas-asr.py` dá o corte
como limpo — fragmento curto não vira token. Quem denuncia é o envelope.

A régua NÃO é "termina alto": no ritmo colado o corte cai de propósito na soltura da
última palavra, que é alta. O que separa defeito de estilo é a **inclinação**:

    termina alto E SUBINDO  → ataque da palavra seguinte, defeito
    termina alto E DESCENDO → soltura da última palavra, é o estilo

⚠️ As fronteiras têm que ser calculadas em `frames/fps` dos segs, não somando
`end-start` da EDL: o render arredonda pra frame e a soma da EDL derrapa dezenas de ms
ao longo do vídeo — o suficiente pra amostrar dentro do segmento SEGUINTE e inventar um
"ataque" que não existe (aconteceu na 1ª versão desta checagem). Desde a SPEC-05 elas
vêm de `edl_io.fronteiras()`, que lê a `timeline_real` persistida (ou a mede, se a
produção é anterior) — este script não refaz mais a conta por conta própria.

🔀 J-CUT (SPEC-07): com `audio-takes/` presente, a cauda de cada take é medida no
WAV DO PRÓPRIO TAKE, não no montado. Motivo: com sobreposição, a janela de 60 ms
antes da fronteira NO MONTADO contém os DOIS takes somados — o ataque da primeira
palavra do que entra chega ali de propósito, e esta régua o leria como sílaba
vazada do que sai. Seria falso positivo em TODA junção J-cut, por construção. No
buffer do próprio take a cauda está limpa, e a régua volta a medir o que mede.
Sem `audio-takes/` nada muda: a saída é a mesma de antes desta spec.

Uso: qc-ataque.py <dir-da-producao> [--video v1-montado.mp4]
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import jcut as jcut_mod       # noqa: E402
import perfil as perfil_mod   # noqa: E402

# FÍSICA (não é formato): janela de RMS, margem de nível e inclinação de ataque.
# 📐 O sample rate vem do perfil de peça (SPEC-00) — ver SR em main().
WIN = 0.01
MARGEM = 14.0     # dB acima do piso local pra considerar "alto"
INCL = 3.0        # dB/100ms de subida pra considerar "rampa de ataque"
SR = None         # sample rate: vem do perfil em main(), antes de qualquer uso


def envelope(f):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", f, "-vn", "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    w = int(WIN * SR)
    n = len(a) // w
    return 20 * np.log10(np.maximum(np.sqrt((a[:n * w].reshape(n, w) ** 2).mean(1)), 1e-7))


def takes_do_jcut(d, edl):
    """`audio-takes/segNNN.wav` na ordem, ou None. Só existe quando houve J-cut.

    Três recusas, e as três são a mesma lição: medir a cauda no take ERRADO é
    pior do que medir no montado.
      • a lista tem que estar COMPLETA (um wav faltando desloca todo o loop);
      • o plano tem que descrever ESTE corte (`jcut.carregar` confere o
        `edl_fingerprint`);
      • o `video_skip_frames` de cada sidecar de `segs/` tem que bater com o
        plano — senão os wavs são de uma geração e os frames de outra, que é
        exatamente o defeito de procedência que a SPEC-07 existe para fechar.
    """
    dir_t = os.path.join(d, "audio-takes")
    if not os.path.isdir(dir_t):
        return None
    n = len(edl)
    ps = [os.path.join(dir_t, "seg%03d.wav" % i) for i in range(n)]
    faltando = [p for p in ps if not os.path.exists(p)]
    if faltando:
        print("  aviso: audio-takes/ existe mas faltam %d wav(s) — medindo no montado "
              "(com J-cut isso vira falso positivo em toda junção)" % len(faltando),
              file=sys.stderr)
        return None
    plano = jcut_mod.carregar(d, edl)
    if plano is None:
        print("  aviso: audio-takes/ sem jcut.json ao lado — takes órfãos de um plano "
              "que não existe mais; medindo no montado", file=sys.stderr)
        return None
    for i, s in enumerate(plano["segmentos"]):
        side = os.path.join(d, "segs", "seg%03d.json" % i)
        if not os.path.exists(side):
            continue
        with open(side) as fh:
            g = json.load(fh)
        if int(g.get("video_skip_frames", 0)) != int(s["video_skip_frames"]):
            sys.exit("seg%03d foi renderizado com video_skip_frames=%d e o jcut.json "
                     "planeja %d. Os wavs de audio-takes/ e os frames de segs/ são de "
                     "gerações diferentes: apague segs/ e remonte antes do QC."
                     % (i, int(g.get("video_skip_frames", 0)), s["video_skip_frames"]))
    com_lead = sum(1 for s in plano["segmentos"] if s["lead_frames_in"])
    print("  jcut: %d junção(ões) com sobreposição — a cauda é medida no wav do "
          "próprio take (no montado ela viria somada com o take seguinte)"
          % com_lead, file=sys.stderr)
    return ps


def main():
    global SR
    d = sys.argv[1]
    a = sys.argv[2:]
    vid = a[a.index("--video") + 1] if "--video" in a else "v1-montado.mp4"
    SR = int(perfil_mod.carregar(d)["audio"]["sr"])
    edl = edl_io.segmentos(d)
    takes = takes_do_jcut(d, edl)
    db = envelope(os.path.join(d, vid)) if takes is None else None
    # 📐 A 7ª reimplementação da mesma conta morreu aqui (SPEC-05). A versão antiga
    # refazia o ffprobe com `sorted(glob.glob(...))`, que é LEXICOGRÁFICO: acima de
    # 99 segmentos ela punha `seg100` entre `seg10` e `seg11` e este QC media o
    # vídeo embaralhado. A timeline persistida já vem ordenada por índice numérico
    # e conferida contra o corte atual.
    tl = edl_io.timeline(d, exigir=False) or edl_io.medir_timeline(d)
    fr = edl_io.fronteiras(tl)

    ruins = 0
    for i, s in enumerate(edl):
        t = fr[i + 1]          # fim do segmento i no montado
        if i == len(edl) - 1:
            break
        # ⚠️ Fronteira de PLANO (divisão contígua pra reenquadrar) não é corte de áudio:
        # o fim de um pedaço é o início do outro no bruto, então a fala atravessa inteira.
        # Medir "ataque" ali acusa a própria continuação da voz — falso positivo por
        # construção. Só emendas com descontinuidade no bruto entram.
        prox = edl[i + 1]
        if prox["src"] == s["src"] and abs(prox["start"] - s["end"]) < 0.002:
            continue
        if takes is None:
            cur = db
            k = min(len(cur) - 1, int(round(t / WIN)))
            # a vizinhança do piso é SIMÉTRICA aqui: no montado existe "depois"
            piso_lo, piso_hi = max(0, k - 60), min(len(cur), k + 60)
        else:
            # o buffer do take termina EXATAMENTE na fronteira de imagem
            # (a_off_i + n_audio_i == v_off_{i+1}), então a cauda é o fim dele.
            cur = envelope(takes[i])
            k = len(cur)
            # ⚠️ assimétrico de propósito: no wav do take não existe "depois" da
            # cauda. O piso sai dos 1,2 s ANTERIORES — mesma largura de janela,
            # de um lado só.
            piso_lo, piso_hi = max(0, k - 120), k
        jan = cur[max(0, k - 6):k]
        if len(jan) < 3:
            continue
        incl = float(np.polyfit(range(len(jan)), jan, 1)[0]) * 100
        piso = float(np.percentile(cur[piso_lo:piso_hi], 15))
        alto = float(jan.max()) > piso + MARGEM
        ruim = alto and incl > INCL
        if ruim:
            ruins += 1
        print(f"  {'⚠️ ATAQUE' if ruim else '        ok'} {s['beat']:16s} t={t:7.2f} "
              f"pico {jan.max():6.1f} piso {piso:6.1f} incl {incl:+7.1f} dB/100ms")
    print(f"\n{len(edl)-1} emendas · {ruins} com sílaba vazada", file=sys.stderr)
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
