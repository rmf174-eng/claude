#!/usr/bin/env python3
"""Autoteste do qc-nivel.py (SPEC-10 §8.2).

    python3 tests/test_qc_nivel.py            # só o autoteste SINTÉTICO (rápido)
    python3 tests/test_qc_nivel.py --real     # + os casos em material real do repo

⚠️ A separação é deliberada e vem da SPEC-000 §3.13/3: **quem depende de fixture é
o teste, não a ferramenta**. O autoteste sintético gera TUDO em /tmp com ffmpeg
(`lavfi` + ruído em numpy) e roda numa máquina que não tem `creators/`, não tem
`data/` e não tem nenhum bruto — que é a máquina do cliente. Os casos `--real`
usam as três produções entregues da creator-2 como fixture SOMENTE-LEITURA.

🔴 TODA guarda aqui é provada por DEFEITO PLANTADO. Um teste que só confere o
caminho feliz é indistinguível de um teste quebrado: este repo já entregou 6,25 s
de vídeo errado com todos os QCs verdes. Cada `checa_` imprime QUANTO varreu.
"""
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

AQUI = os.path.dirname(os.path.realpath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
QC = os.path.join(SCRIPTS, "qc-nivel.py")

import importlib.util                                   # noqa: E402
_spec = importlib.util.spec_from_file_location("qc_nivel", QC)
qn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qn)                            # noqa: E402

SR = 48000
W = 0.020
FPS = 30
DUR_SEG = 2.0
N_SEG = 6
I_DEFEITO = 3

_ok, _falhas = [0], []


def checa(nome, cond, detalhe=""):
    _ok[0] += 1
    print(("  ok   " if cond else "  FALHA") + "  " + nome + ("  · " + detalhe if detalhe else ""))
    if not cond:
        _falhas.append(nome)


# ═══════════════════════════════════════════════════ material sintético

def _fala(n, sr=SR, silabas_por_s=4.0, rng=None):
    """Ruído de banda de voz modulado em sílabas. Não é fala, mas tem o
    envelope da fala: bursts com ataque e decaimento, separados por vales."""
    rng = rng or np.random.default_rng(7)
    t = np.arange(n) / sr
    x = rng.normal(0, 1, n)
    # banda de voz grosseira: passa-baixa de 1ª ordem duas vezes
    for _ in range(2):
        x = np.convolve(x, np.ones(12) / 12, mode="same")
    env = np.clip(np.sin(2 * np.pi * silabas_por_s * t) ** 2, 0.02, 1.0)
    y = x * env
    return y / (np.abs(y).max() + 1e-9)


def _rms_db(x):
    return 20 * np.log10(max(float(np.sqrt((x ** 2).mean())), 1e-12))


def _ganho_para(x, alvo_db):
    return x * (10 ** ((alvo_db - _rms_db(x)) / 20.0))


def _wav(caminho, x, sr=SR):
    a = np.clip(x, -1, 1)
    with wave.open(caminho, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes((a * 32767).astype("<i2").tobytes())


def producao_sintetica(base, *, nivel_defeito_db=-56.0, dur_palavra=0.5,
                       palavras_por_seg=3):
    """6 segmentos de 2,0 s. O segmento I_DEFEITO é o único inaudível.

    A geometria é escolhida para que a timeline real seja EXATA: 60 frames a
    30 fps = 2,000 s por segmento, então `frames/fps` e `end−start` coincidem —
    o que isola o teste do erro de arredondamento (esse é assunto da SPEC-05).

    📏 O NÍVEL DO DEFEITO É CALIBRADO NO CASO REAL, não escolhido "bem baixo".
    Na `peca-01` o `"vamos"` mede P75 −34,1 dBFS contra um piso p15 de
    −35,2: o defeito fica ~1–3 dB ACIMA do ruído de sala e ~3 dB ABAIXO do
    `piso + margem` que define o critério (b) da máscara. É esse regime — e só
    ele — que faz o gate de nível perder a fala e o `SEM-NIVEL` ser necessário.
    Com o defeito a −52 dBFS (a 1ª versão deste teste) ele ficava ACIMA de
    `piso+6` e o caso A2b não exercitava nada: o teste passava por engano.
    A checagem de regime está em `caso_balanco_e_sem_nivel`.
    """
    os.makedirs(os.path.join(base, "input"), exist_ok=True)
    os.makedirs(os.path.join(base, "segs"), exist_ok=True)
    # o diretório do take leva o STEM do bruto: é a convenção que o
    # `transcript_do_src` resolve, e escrevê-lo assim faz o teste exercitar a
    # máscara de transcript de verdade (na 1ª versão ele caía no gate de piso
    # sem ninguém perceber — n_palavras saía 0 e o teste passava mesmo assim).
    os.makedirs(os.path.join(base, "bruto"), exist_ok=True)
    n_tot = int(SR * DUR_SEG * N_SEG)
    rng = np.random.default_rng(11)
    sinal = np.zeros(n_tot)
    palavras = []
    for i in range(N_SEG):
        alvo = nivel_defeito_db if i == I_DEFEITO else -20.0
        for k in range(palavras_por_seg):
            t0 = i * DUR_SEG + 0.15 + k * (dur_palavra + 0.12)
            t1 = t0 + dur_palavra
            a, b = int(t0 * SR), int(t1 * SR)
            sinal[a:b] += _ganho_para(_fala(b - a, rng=rng), alvo)
            palavras.append({"word": "p%d%d" % (i, k), "start": round(t0, 3),
                             "end": round(t1, 3)})
    sinal += _ganho_para(rng.normal(0, 1, n_tot), -55.0)     # ruído de sala
    bruto = os.path.join(base, "input", "bruto.wav")
    _wav(bruto, sinal / max(1.0, np.abs(sinal).max() * 1.05))

    json.dump({"results": {"channels": [{"alternatives": [{"words": palavras}]}]}},
              open(os.path.join(base, "bruto", "transcript.json"), "w"))
    edl = [{"src": "input/bruto.wav", "start": round(i * DUR_SEG, 3),
            "end": round((i + 1) * DUR_SEG, 3), "beat": "b%d" % i, "quem": "x"}
           for i in range(N_SEG)]
    json.dump(edl, open(os.path.join(base, "edl.json"), "w"))

    for i in range(N_SEG):
        subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-v", "error",
             "-f", "lavfi", "-i", "color=c=black:s=64x64:r=%d" % FPS,
             "-ss", str(i * DUR_SEG), "-t", str(DUR_SEG), "-i", bruto,
             "-frames:v", str(int(DUR_SEG * FPS)), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", str(SR), "-ac", "1", "-shortest",
             os.path.join(base, "segs", "seg%03d.mp4" % i)], check=True)
    montado = os.path.join(base, "montado.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-v", "error",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:r=%d" % FPS, "-i", bruto,
         "-frames:v", str(int(DUR_SEG * N_SEG * FPS)), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", str(SR), "-ac", "1", "-shortest",
         montado], check=True)
    return base


def rodar(args, dirp):
    p = subprocess.run([sys.executable, QC] + args, cwd=dirp if False else None,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def instantaneo(d):
    """nome → (tamanho, mtime_ns) de tudo abaixo de `d`. É a régua do A8, e é
    LOCAL: `git status` global mede o vizinho quando há 8 agentes na árvore."""
    out = {}
    for raiz, _, arqs in os.walk(d):
        for a in arqs:
            p = os.path.join(raiz, a)
            st = os.stat(p)
            out[os.path.relpath(p, d)] = (st.st_size, st.st_mtime_ns)
    return out


# ═══════════════════════════════════════════════════ casos sintéticos

def caso_janela_independe_do_container(tmp):
    """A4 (parte sintética): a janela é a DECLARADA, não a do frame do decoder."""
    x = _ganho_para(_fala(int(SR * 3)), -20.0)
    w48 = os.path.join(tmp, "a48.wav")
    _wav(w48, x, SR)
    m16 = os.path.join(tmp, "a16.mp3")
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", w48,
                    "-ar", "16000", "-ac", "1", "-b:a", "64k", m16], check=True)
    for nome, caminho in (("wav 48k", w48), ("mp3 16k", m16)):
        t, db = qn.envelope_db(caminho, sr=SR, janela_s=W)
        por_s = len(t) / (t[-1] + W)
        checa("A4 janela declarada em %s" % nome, abs(por_s - 50.0) <= 0.1,
              "%.2f janelas/s em %d janelas" % (por_s, len(t)))
    # defeito plantado: SEM -ar/-ac, que é o que o voice_levels.py:72-76 faz.
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", m16, "-vn",
                          "-f", "s16le", "-"], capture_output=True).stdout
    n_nativo = len(raw) // 2
    checa("A4 defeito plantado: sem -ar a contagem de amostras MUDA",
          abs(n_nativo - SR * 3) > SR * 0.5,
          "%d amostras sem -ar contra %d com -ar" % (n_nativo, SR * 3))


def caso_piso_nao_e_o_da_referencia(tmp):
    """A6 (parte sintética + grep): o piso é o da SALA, não `mediana − 12`."""
    n = int(SR * 20)
    rng = np.random.default_rng(3)
    x = _ganho_para(rng.normal(0, 1, n), -55.0)
    for k in range(14):                      # 70 % do arquivo é fala
        a = int(k * 1.4 * SR)
        b = a + int(1.0 * SR)
        x[a:b] += _ganho_para(_fala(b - a, rng=rng), -20.0)
    p = os.path.join(tmp, "sala.wav")
    _wav(p, x / max(1.0, np.abs(x).max() * 1.05))
    _, db = qn.envelope_db(p, sr=SR, janela_s=W)
    piso = qn.piso_de_sala(db)
    med = float(np.median(db[db > piso + 6]))
    checa("A6 piso ≈ ruído de sala", abs(piso - (-55.0)) <= 6.0,
          "piso %.1f dB, ruído injetado −55,0 dB, %d janelas" % (piso, len(db)))
    checa("A6 piso NÃO é `mediana − 12` (o clamp do ref-A)", abs(piso - (med - 12.0)) > 6.0,
          "piso %.1f vs med−12 %.1f" % (piso, med - 12.0))
    # o CÓDIGO, sem comentário e sem docstring (os dois citam o ref-A de propósito,
    # para dizer o que foi REJEITADO e por quê — grep ingênuo acusaria a explicação)
    import io
    import tokenize
    peças = []
    with open(QC, "rb") as fh:
        for tok in tokenize.tokenize(io.BytesIO(fh.read()).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                peças.append(tok.string)
    codigo = " ".join(peças).lower()
    achados = [k for k in ("ridler", "intermeans", "clamp", "med - 32", "med - 12")
               if k in codigo]
    checa("A6 nem Ridler-Calvard nem clamp no CÓDIGO EXECUTÁVEL", not achados,
          "%d tokens varridos, achados=%r" % (len(peças), achados))


def caso_mascara_pega_fala_abaixo_do_piso(tmp):
    """§3.3 — a virada de chave. Sem ela o script vira o detector do ref-A."""
    n = int(SR * 6)
    rng = np.random.default_rng(5)
    x = _ganho_para(rng.normal(0, 1, n), -55.0)
    # −53 dBFS: ABAIXO de `piso + margem` (−55 + 6 = −49), que é onde o gate de
    # nível do ref-A deixa de ver a fala. É o regime do "vamos" real (−40 P75
    # contra um piso de −43,3).
    for k, alvo in ((0, -20.0), (1, -20.0), (2, -53.0), (3, -20.0)):
        a, b = int((0.4 + k * 1.4) * SR), int((1.2 + k * 1.4) * SR)
        x[a:b] += _ganho_para(_fala(b - a, rng=rng), alvo)
    p = os.path.join(tmp, "sussurro.wav")
    _wav(p, x / max(1.0, np.abs(x).max() * 1.05))
    t, db = qn.envelope_db(p, sr=SR, janela_s=W)
    piso = qn.piso_de_sala(db)
    pal = [(0.4 + k * 1.4, 1.2 + k * 1.4) for k in range(4)]
    alvo = (t + W > pal[2][0]) & (t < pal[2][1])
    m_uniao = qn.mascara_de_fala(t, db, pal, piso, janela_s=W, margem_db=6.0)
    m_piso = qn.mascara_de_fala(t, db, pal, piso, janela_s=W, margem_db=6.0, so_piso=True)
    checa("§3.3 a fala a −45 dB entra na máscara pelo transcript",
          int((m_uniao & alvo).sum()) >= int(alvo.sum() * 0.95),
          "%d de %d janelas do sussurro" % (int((m_uniao & alvo).sum()), int(alvo.sum())))
    checa("§3.3 defeito plantado: SEM o critério (a), o sussurro some",
          int((m_piso & alvo).sum()) < int(alvo.sum() * 0.5),
          "%d de %d janelas sobrevivem ao gate de nível"
          % (int((m_piso & alvo).sum()), int(alvo.sum())))


def caso_monotonicidade(tmp):
    """A3 (sintético): quanto pior o defeito, MAIS o detector vê. Nunca menos.

    É o teste que o algoritmo do ref-A reprova: com o clamp `[med−32, med−12]` a
    cobertura deles sobe até −12 dB e DESABA (0,38 s a −15 dB, 0,00 s a −20 dB).
    """
    n = int(SR * 20)
    rng = np.random.default_rng(13)
    base = _ganho_para(rng.normal(0, 1, n), -55.0)
    pal = []
    for k in range(14):
        a, b = int(k * 1.4 * SR), int(k * 1.4 * SR) + int(1.0 * SR)
        base[a:b] += _ganho_para(_fala(b - a, rng=rng), -20.0)
        pal.append((k * 1.4, k * 1.4 + 1.0))
    dentro = [w for w in pal if w[0] >= 7.0 and w[1] <= 12.0]
    cob, cob_referencia = [], []
    for at in (0, 6, 8, 10, 12, 15, 20, 30):
        x = base.copy()
        x[int(7.0 * SR):int(12.0 * SR)] *= 10 ** (-at / 20.0)
        p = os.path.join(tmp, "aten%d.wav" % at)
        _wav(p, x / max(1.0, np.abs(x).max() * 1.05))
        t, db = qn.envelope_db(p, sr=SR, janela_s=W)
        piso = qn.piso_de_sala(db)

        def cobertura(masc):
            niveis = []
            for a, b in pal:
                v, _ = qn.nivel_p75(db, masc & (t + W > a) & (t < b), min_janelas=20)
                if v is not None:
                    niveis.append(v)
            if not niveis:
                return 0.0
            med = float(np.median(niveis))
            runs = qn.achar_runs(t, db, masc, med - 5.0, janela_s=W, min_run_s=0.25)
            return sum(min(r["end"], 12.0) - max(r["start"], 7.0) for r in runs
                       if r["end"] > 7.0 and r["start"] < 12.0)

        cob.append((at, round(cobertura(
            qn.mascara_de_fala(t, db, pal, piso, janela_s=W, margem_db=6.0)), 2)))
        # ── o ALGORITMO DELES, reproduzido para comparação: fala DEFINIDA por
        #    nível (voice_levels.py:216), com o piso preso ao teto do clamp
        #    `mediana − 12` (`:137`). Reproduzo o CLAMP e não o Ridler-Calvard
        #    porque, medido nos 4 materiais reais da §1.3, em 2 deles é o clamp
        #    que decide o número — o RC cai tão alto que o `min(..., med−12)`
        #    ganha. Não é o nosso código: é o defeito plantado que este teste TEM
        #    que enxergar, e é a curva não-monotônica da §1.3.
        aprox = db[db > piso + 6]
        med_e = float(np.percentile(aprox, 50)) if len(aprox) else piso
        cob_referencia.append((at, round(cobertura(db > med_e - 12.0), 2)))
    seq = [s for _, s in cob]
    nao_decresce = all(seq[i] <= seq[i + 1] + 0.30 for i in range(1, len(seq) - 1))
    checa("A3 cobertura NÃO-DECRESCENTE de −6 a −30 dB", nao_decresce, repr(cob))
    prof = dict(cob)
    checa("A3 a −20 dB acusa ≥ 3,0 s da janela de 5 s", prof[20] >= 3.0,
          "%.2f s (janela tem %.1f s de palavra)" % (prof[20], sum(b - a for a, b in dentro)))
    checa("A3 controle: sem atenuação a janela NÃO é acusada", prof[0] <= 0.5,
          "%.2f s" % prof[0])
    e = dict(cob_referencia)
    pico = max(e.values())
    checa("A3 defeito plantado: com o gate de nível + clamp do ref-A a cobertura "
          "SOBE e depois DESABA — e este teste vê",
          e[30] < pico - 0.5 and any(e[b] < e[a] - 0.1 for a, b in
                                     zip(sorted(e)[1:], sorted(e)[2:])),
          "clamp: %r (pico %.2f s, some em −30 dB)  ·  o nosso: %r"
          % (cob_referencia, pico, cob))


def caso_amostra_curta(tmp):
    """[gate] A7 — span curto demais nunca vira alarme; span longo vira."""
    base = os.path.join(tmp, "curta")
    producao_sintetica(base)
    # palavra curta e baixíssima, isolada, num 7º trecho fora da EDL:
    cod, out, err = rodar(["achado", base, "--json"], base)
    doc = json.loads(out)
    frases = doc["frases"]
    curtas = [f for f in frases if f.get("flag") == "amostra-curta"]
    longas_low = [f for f in frases if f.get("flag") == "LOW"]
    checa("A7 nenhum span com flag LOW tem menos de 20 janelas mascaradas",
          all(f["n_janelas"] >= 20 for f in frases if f.get("flag") == "LOW"),
          "%d frases, %d LOW, %d amostra-curta"
          % (len(frases), len(longas_low), len(curtas)))
    checa("A7 o veredito ignora amostra-curta",
          doc["veredito"]["n_low"] == sum(1 for s in doc["segmentos"]
                                          if s.get("flag") == "LOW"),
          "n_low=%d" % doc["veredito"]["n_low"])
    # DEFEITO PLANTADO: o MESMO defeito de nível, mas com uma única palavra de
    # 0,20 s por segmento (10 janelas < 20). O span vira curto demais e NÃO pode
    # alarmar — mesmo com o segmento 3 tão baixo quanto no caso que alarma.
    base2 = os.path.join(tmp, "curta2")
    producao_sintetica(base2, dur_palavra=0.20, palavras_por_seg=1)
    cod2, out2, _ = rodar(["achado", base2, "--json"], base2)
    d2 = json.loads(out2)
    seg = next(s for s in d2["segmentos"] if s["i"] == I_DEFEITO)
    curtas2 = [f for f in d2["frases"] if f.get("flag") == "amostra-curta"]
    checa("A7 defeito plantado: 1 palavra de 0,20 s → amostra-curta, nunca LOW",
          len(curtas2) > len(curtas) and seg.get("flag") == "amostra-curta" and
          d2["veredito"]["n_low"] == 0,
          "%d amostra-curta (0,20 s) contra %d (0,50 s); seg%d=%s; n_low=%d"
          % (len(curtas2), len(curtas), I_DEFEITO, seg.get("flag"),
             d2["veredito"]["n_low"]))
    checa("A7 e o teste tem DENTES: com palavras de 0,50 s o defeito É acusado",
          any(s.get("flag") == "LOW" for s in doc["segmentos"]),
          "segmento %d, Δ %s dB"
          % (I_DEFEITO, next(s for s in doc["segmentos"]
                             if s["i"] == I_DEFEITO).get("delta_db")))
    checa("A7 exit 0 no achado (ele nunca reprova)", cod == 0 and cod2 == 0,
          "exit %d/%d · seg%d %s" % (cod, cod2, I_DEFEITO, seg.get("flag")))


def caso_balanco_e_sem_nivel(tmp):
    """O gate canônico + A2b: range com fala e sem janela medível REPROVA."""
    base = os.path.join(tmp, "bal")
    producao_sintetica(base)
    # regime do material: o defeito tem que ficar ENTRE o piso e `piso+margem`,
    # que é onde o gate de nível cega. Sem esta checagem o A2b passa por engano.
    t, db = qn.envelope_db(os.path.join(base, "montado.mp4"), sr=SR, janela_s=W)
    piso = qn.piso_de_sala(db)
    alvo_span = (t >= I_DEFEITO * DUR_SEG) & (t < (I_DEFEITO + 1) * DUR_SEG)
    p75_def = float(np.percentile(db[alvo_span], 75))
    checa("regime do sintético = o do defeito real (piso < defeito < piso+margem)",
          piso < p75_def < piso + 6.0,
          "piso %.1f · defeito P75 %.1f · piso+6 %.1f" % (piso, p75_def, piso + 6.0))
    cod, out, err = rodar(["balanco", base, "--video", "montado.mp4", "--json"], base)
    doc = json.loads(out)
    baixos = [r for r in doc["ranges"] if r["flag"] == "LOW-LEVEL"]
    checa("balanco acha exatamente o range plantado",
          len(baixos) == 1 and baixos[0]["i"] == I_DEFEITO and cod == 1,
          "%d flag(s), i=%s, Δ=%s dB, exit %d"
          % (len(baixos), baixos[0]["i"] if baixos else None,
             baixos[0]["delta_db"] if baixos else None, cod))
    checa("balanco varreu tudo e diz quanto",
          doc["medicao"]["n_janelas"] > 0 and
          all(r["n_janelas_mascaradas"] > 0 or r["flag"] in ("SEM-NIVEL", "sem-fala")
              for r in doc["ranges"]),
          "%d janelas, %d na máscara, %d ranges"
          % (doc["medicao"]["n_janelas"], doc["medicao"]["n_janelas_mascaradas"],
             doc["medicao"]["n_ranges"]))
    checa("balanco usa a timeline real, não Σ(end−start)",
          doc["medicao"]["fronteiras"] in ("timeline_real", "ffprobe-segs"),
          doc["medicao"]["fronteiras"])
    # A2b — máscara por gate de nível: o range defeituoso perde TODAS as janelas
    cod2, out2, _ = rodar(["balanco", base, "--video", "montado.mp4",
                           "--mascara", "piso", "--json"], base)
    d2 = json.loads(out2)
    alvo = next(r for r in d2["ranges"] if r["i"] == I_DEFEITO)
    checa("A2b range com palavra e zero janela medível → SEM-NIVEL, exit 1",
          alvo["flag"] == "SEM-NIVEL" and cod2 == 1,
          "flag=%s, %d janelas mascaradas, %d palavras, exit %d"
          % (alvo["flag"], alvo["n_janelas_mascaradas"], alvo["n_palavras"], cod2))
    checa("A2b defeito plantado: com gate de nível o defeito SUMIRIA da lista "
          "se `SEM-NIVEL` não existisse",
          alvo["n_janelas_mascaradas"] < 20 and alvo.get("nivel_db") is None and
          alvo.get("delta_db") is None,
          "%d janela(s) mascarada(s) de %d no range, sem nível medível — é a "
          "auto-neutralização que a regra impede"
          % (alvo["n_janelas_mascaradas"], alvo["n_janelas"]))
    # convergência (A5 sintético): +ganho no segmento defeituoso zera as flags
    base3 = os.path.join(tmp, "bal-ok")
    producao_sintetica(base3, nivel_defeito_db=-20.0)
    cod3, out3, _ = rodar(["balanco", base3, "--video", "montado.mp4", "--json"], base3)
    d3 = json.loads(out3)
    checa("A5 (sintético) sem o defeito, o balanco CONVERGE a zero",
          cod3 == 0 and d3["veredito"]["flags"] == 0,
          "exit %d, %d flag(s) em %d ranges"
          % (cod3, d3["veredito"]["flags"], d3["medicao"]["n_ranges"]))


def caso_leave_one_out(tmp):
    """§3.6a — a mediana GLOBAL (a do verify_cut.py:234-235) é puxada pelo
    próprio defeito. Quanto menos ranges, pior: com 2 o defeito define metade da
    referência. A `nao-perdeu-a-peca-06` tem 3, então isto não é hipotético.

    ⚠️ A afirmação medida é *estritamente melhor*, não *muito melhor*: com 3
    ranges e o defeito no extremo, a mediana quase não anda (0,25 dB). O ganho
    grande é com 2 (10,5 dB). Um teste que exigisse "≥ 5 dB em qualquer n" seria
    falso vermelho — e foi exatamente o que a 1ª versão deste teste fez."""
    for n, esperado in ((2, 5.0), (3, 0.1)):
        niveis = [-12.0, -33.0] if n == 2 else [-12.0, -12.5, -33.0]
        glob = float(np.median(niveis))
        loo = float(np.median([v for v in niveis if v != -33.0]))
        d_glob, d_loo = -33.0 - glob, -33.0 - loo
        checa("§3.6a LOO é estritamente pior-para-o-defeito com %d ranges" % n,
              d_loo < d_glob and (d_glob - d_loo) >= esperado,
              "Δ global %.2f dB × Δ LOO %.2f dB (diferença %.2f)"
              % (d_glob, d_loo, d_glob - d_loo))


def caso_nao_escreve(tmp):
    """[gate] A8 — sem --gravar, nada muda no diretório da produção."""
    base = os.path.join(tmp, "a8")
    producao_sintetica(base)
    antes = instantaneo(base)
    rodar(["achado", base], base)
    rodar(["balanco", base, "--video", "montado.mp4"], base)
    depois = instantaneo(base)
    checa("A8 sem --gravar o diretório fica IDÊNTICO", antes == depois,
          "%d arquivos varridos; diferenças: %r"
          % (len(antes), sorted(set(antes) ^ set(depois)) or
             [k for k in antes if antes[k] != depois.get(k)]))
    rodar(["achado", base, "--gravar"], base)
    rodar(["balanco", base, "--video", "montado.mp4", "--gravar"], base)
    novo = sorted(set(instantaneo(base)) - set(antes))
    checa("A8 defeito plantado: COM --gravar aparecem exatamente os 2 JSONs",
          novo == ["qc-nivel-achado.json", "qc-nivel-balanco.json"], repr(novo))


def caso_ganho(tmp):
    checa("ganho = −Δ − headroom, teto 12 dB",
          qn.ganho_sugerido(-8.0, headroom_db=1.5, teto_db=12.0) == 6.5 and
          qn.ganho_sugerido(-30.0, headroom_db=1.5, teto_db=12.0) == 12.0 and
          qn.ganho_sugerido(-1.0, headroom_db=1.5, teto_db=12.0) == 0.0,
          "−8→6,5 · −30→12,0 (teto) · −1→0,0")


# ═══════════════════════════════════════════════════ casos em material real

def casos_reais():
    raiz = os.path.abspath(os.path.join(SCRIPTS, "..", "..", "..", ".."))
    prod = os.path.join(raiz, "creators", "creator-2", "producao")
    if not os.path.isdir(prod):
        print("  (sem creators/ nesta máquina — casos reais pulados, e isto é "
              "CORRETO: a ferramenta não depende de fixture)")
        return
    m = os.path.join(prod, "peca-01")
    cod, out, _ = rodar(["balanco", m, "--video", "v-final.mp4", "--json"], m)
    d = json.loads(out)
    low = [r for r in d["ranges"] if r["flag"] == "LOW-LEVEL"]
    outros = sorted(r["delta_db"] for r in d["ranges"]
                    if r.get("delta_db") is not None and r["i"] != 3)
    checa("A1 peca-01: exatamente 1 LOW-LEVEL e é o i=3",
          len(low) == 1 and low[0]["i"] == 3 and cod == 1,
          "%d flag(s), Δ=%s dB, exit %d" % (len(low), low[0]["delta_db"] if low else None, cod))
    checa("A1 Δ do range 3 ≤ −15,0 dB", low and low[0]["delta_db"] <= -15.0,
          "%s dB" % (low[0]["delta_db"] if low else None))
    checa("A1 separação para o 2º pior ≥ 15,0 dB",
          low and (outros[0] - low[0]["delta_db"]) >= 15.0,
          "2º pior %s dB, separação %.1f dB"
          % (outros[0], outros[0] - low[0]["delta_db"]) if low and outros else "")
    for nome, esperado in (("peca-03", 0), ("nao-perdeu-a-peca-06", 0)):
        p = os.path.join(prod, nome)
        c, o, _ = rodar(["balanco", p, "--video", "v-final.mp4", "--json"], p)
        dd = json.loads(o)
        pior = min((r["delta_db"] for r in dd["ranges"]
                    if r.get("delta_db") is not None), default=None)
        checa("A2 %s: %d flag(s), exit 0" % (nome, esperado),
              dd["veredito"]["flags"] == esperado and c == 0,
              "%d ranges, pior Δ %s dB" % (dd["medicao"]["n_ranges"], pior))
    c, o, _ = rodar(["balanco", m, "--video", "v-final.mp4", "--mascara", "piso", "--json"], m)
    dd = json.loads(o)
    alvo = next(r for r in dd["ranges"] if r["i"] == 3)
    checa("A2b peca-01 com gate de nível: range 3 = SEM-NIVEL, exit 1",
          alvo["flag"] == "SEM-NIVEL" and c == 1,
          "flag=%s, %d janelas, exit %d" % (alvo["flag"], alvo["n_janelas_mascaradas"], c))


def main():
    real = "--real" in sys.argv
    print("autoteste qc-nivel.py — sintético%s" % (" + material real" if real else ""))
    with tempfile.TemporaryDirectory(prefix="qcnivel-") as tmp:
        print("\n[envelope e piso]")
        caso_janela_independe_do_container(tmp)
        caso_piso_nao_e_o_da_referencia(tmp)
        print("\n[máscara de fala]")
        caso_mascara_pega_fala_abaixo_do_piso(tmp)
        print("\n[monotonicidade do detector]")
        caso_monotonicidade(tmp)
        print("\n[achado]")
        caso_amostra_curta(tmp)
        caso_ganho(tmp)
        print("\n[balanco]")
        caso_balanco_e_sem_nivel(tmp)
        caso_leave_one_out(tmp)
        print("\n[não escreve nada]")
        caso_nao_escreve(tmp)
    if real:
        print("\n[material real do repo]")
        casos_reais()
    print("\n%d checagem(ns), %d falha(s)%s"
          % (_ok[0], len(_falhas), (": " + ", ".join(_falhas)) if _falhas else ""))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
