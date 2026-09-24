#!/usr/bin/env python3
"""medir-alinhamento — a régua do alinhador, e o antídoto contra a circularidade.

Responde UMA pergunta: *o alinhador erra menos que o ASR nesta fronteira, e por
quanto?* Sem custo de API, offline.

POR QUE ESTA RÉGUA É ASSIM (SPEC-04 §1.5, §3.5)
    O ref-A publica "93% das palavras caem dentro de uma região real de fala" e
    "o fim da fala é marcado com 10 ms de erro", ambos medidos contra o
    `speech_regions.py` **da própria casa** — um `silencedetect` com `-33 dB`
    fixo. Três defeitos, e nós sabemos de cada um:
      1. medir contra outro detector seu mede CONCORDÂNCIA, não acurácia;
      2. gate absoluto a −33 dB é permissivo por construção (o piso real de um
         café, medido por nós em 2026-07-31, é −44 dB de mediana);
      3. "dentro de uma região" é teste binário de contenção — não informa erro
         de fronteira, que é o número que interessa.

    Daqui não sai "% dentro". Sai, para os DOIS candidatos (ASR cru e alinhado),
    em cada referência: **n · mediana |erro| · p90 |erro| · viés · taxa de
    vitória** — e o n varrido é impresso sempre.

AS TRÊS REFERÊNCIAS (famílias independentes de evidência)
    envelope  onset por RMS de 10 ms com piso local adaptativo (percentil 15 num
              raio de 0,6 s, +10 dB) — o mesmo critério do `piso_para(--floor
              auto)` do bordas.py. Independente de qualquer modelo de linguagem.
              ⚠️ CEGO para fricativa surda e nasal (`qc-fonemas.py`,
              `bordas.py:253-263`) — e a saída diz isso.
    fonemas   silêncio/surdo/vozeado pela razão (3–9 kHz)/(150–900 Hz), a lógica
              do `qc-fonemas.py`. Pega o que o envelope não pega: é a régua que
              achou o /ʁ/ de "Resumindo" a −34 dB parecendo vale.
    edl       fronteiras de corte de um editor humano externo. ⚠️ Só vale se as
              fronteiras NÃO forem derivadas de ASR — o script mede isso e se
              recusa a publicar número quando forem (é a circularidade acima).

OS CONTROLES (verde sem prova de dentes não vale nada)
    Nenhum resultado limpo é aceito sem que a régua prove que acusa um defeito
    plantado. CINCO controles rodam sempre, e todos imprimem n:
      CONTROLE-0  candidato = a própria referência        → tem que ler 0 ms
      CONTROLE-A  candidato = referência + 100 ms         → tem que ler 100 ms
      CONTROLE-B  alinhado + 100 ms                       → o viés desloca +100 ms
      CONTROLE-D  áudio prefixado com 103 ms de silêncio  → a REFERÊNCIA anda
                  +103 ms. (103 e não 100 de propósito: 100 ms é múltiplo exato
                  da janela de 10 ms do envelope e o controle passaria limpo
                  demais por acidente de grade.)
      CONTROLE-E  candidato × referência DE OUTRA fronteira → tem que EXPLODIR

    D e E são os únicos que testam a INDEPENDÊNCIA da referência: uma régua
    circular — que devolvesse o próprio candidato — passaria em 0, A e B, e
    reprovaria nesses dois.

Uso:
    medir-alinhamento.py <dir> [--ref envelope|fonemas|edl|todas] [--edl P]
                         [--alignment P] [--audio P] [--n 0] [--gap 0.15]
                         [--score-min 0.0] [--janela 0.30] [--json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 48000          # taxa da análise acústica (a mesma do bordas.py/qc-fonemas.py)
WIN = 0.01          # 10 ms — janela do envelope RMS
N_FFT = 512         # ~10,7 ms de janela espectral
HOP = 96            # 2 ms de passo
SURDO_DB = -22.0    # (3–9 kHz) − (150–900 Hz) acima disto = som surdo
GATE_DB = 8.0       # dB acima do piso local para contar como som
DESLOC = 0.100      # o defeito sintético dos controles: 100 ms
# ⚠️ 100 ms é múltiplo EXATO da janela de 10 ms do envelope: deslocar o áudio
# nesse valor move a grade junto e o controle passa limpo demais. O CONTROLE-D
# usa de propósito um valor que NÃO cai na grade, para o teste ter dentes.
DESLOC_D = 0.103


def log(*a):
    print(*a, file=sys.stderr)


# --------------------------------------------------------------------------
# áudio
# --------------------------------------------------------------------------
def carregar(audio: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio), "-vn",
         "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def envelope_db(a: np.ndarray) -> np.ndarray:
    w = int(WIN * SR)
    n = len(a) // w
    rms = np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def piso_local(db, t, raio=0.6):
    """ruído de fundo em volta de t (percentil 15 — imune a um vale isolado)."""
    lo, hi = max(0, int((t - raio) / WIN)), min(len(db), int((t + raio) / WIN))
    return float(np.percentile(db[lo:hi], 15)) if hi > lo else -60.0


# --------------------------------------------------------------------------
# referências acústicas
# --------------------------------------------------------------------------
def ref_envelope(db, centro, janela):
    """Onset por RMS: 1ª janela acima de (piso local + 10 dB) precedida de 30 ms
    abaixo dele. Escolhe o cruzamento mais próximo de `centro` — que é o ponto
    MÉDIO dos dois candidatos, para não favorecer nenhum."""
    thr = piso_local(db, centro) + 10.0
    lo = max(3, int((centro - janela) / WIN))
    hi = min(len(db) - 1, int((centro + janela) / WIN))
    melhor, melhor_d = None, 1e9
    for k in range(lo, hi + 1):
        if db[k] >= thr and all(db[k - j] < thr for j in (1, 2, 3)):
            d = abs(k * WIN - centro)
            if d < melhor_d:
                melhor, melhor_d = k * WIN, d
    return melhor


def _espectro(a, t0, t1):
    i0, i1 = max(0, int(t0 * SR)), min(len(a), int(t1 * SR))
    seg = a[i0:i1]
    if len(seg) < N_FFT:
        return None
    nq = (len(seg) - N_FFT) // HOP + 1
    idx = np.arange(N_FFT)[None, :] + (np.arange(nq) * HOP)[:, None]
    fr = seg[idx] * np.hanning(N_FFT)[None, :]
    sp = np.abs(np.fft.rfft(fr, axis=1))
    f = np.fft.rfftfreq(N_FFT, 1 / SR)
    b_lo, b_hi = (f >= 150) & (f < 900), (f >= 3000) & (f < 9000)
    rms = 20 * np.log10(np.maximum(np.sqrt((fr ** 2).mean(axis=1)), 1e-9))
    razao = (20 * np.log10(np.maximum(sp[:, b_hi].mean(axis=1), 1e-9))
             - 20 * np.log10(np.maximum(sp[:, b_lo].mean(axis=1), 1e-9)))
    ts = i0 / SR + np.arange(nq) * HOP / SR   # borda esquerda de cada quadro
    return ts, rms, razao


def ref_fonemas(a, centro, janela):
    """Onset silêncio→som, com surdo contando como SOM (é o que o envelope perde).
    Exige 30 ms de silêncio antes e 20 ms de som depois."""
    e = _espectro(a, centro - janela - 0.10, centro + janela + 0.10)
    if e is None:
        return None
    ts, rms, razao = e
    piso = float(np.percentile(rms, 15))
    som = rms > piso + GATE_DB          # surdo E vozeado contam como som
    n_sil, n_som = 15, 10               # 30 ms · 20 ms (passo de 2 ms)
    melhor, melhor_d = None, 1e9
    for k in range(n_sil, len(som) - n_som):
        if som[k] and not som[k - 1] and not som[k - n_sil:k].any() and som[k:k + n_som].all():
            d = abs(ts[k] - centro)
            if d < janela and d < melhor_d:
                melhor, melhor_d = float(ts[k]), d
    return melhor


# --------------------------------------------------------------------------
# estatística
# --------------------------------------------------------------------------
def stats(err_ms):
    """|erro| e viés, mais a DISPERSÃO em volta do viés.

    A dispersão separa duas coisas que o |erro| mistura: um viés constante é
    compensável com um único offset; espalhamento não é. Sem ela, um candidato
    com viés grande e espalhamento pequeno parece pior do que é.
    """
    e = np.asarray(err_ms, dtype=float)
    if not len(e):
        nan = float("nan")
        return {"n": 0, "mediana_abs": nan, "p90_abs": nan, "vies": nan,
                "disp50": nan, "disp90": nan}
    v = float(np.median(e))
    r = np.abs(e - v)
    return {
        "n": int(len(e)),
        "mediana_abs": float(np.median(np.abs(e))),
        "p90_abs": float(np.percentile(np.abs(e), 90)),
        "vies": v,
        "disp50": float(np.median(r)),
        "disp90": float(np.percentile(r, 90)),
    }


def linha(rot, s, ref):
    return (f"  {rot:<22s} n={s['n']:<4d} mediana |erro| {s['mediana_abs']:6.1f} ms  "
            f"p90 {s['p90_abs']:6.1f} ms  viés {s['vies']:+7.1f} ms  "
            f"dispersão {s['disp50']:5.1f}/{s['disp90']:6.1f} ms (50/90)   [--ref {ref}]")


# --------------------------------------------------------------------------
def fronteiras(words_asr, words_al, gap_min, limite, score_min=0.0):
    """Word STARTs precedidos de pausa. É a única fronteira onde existe onset
    acústico para detectar — dentro de fala corrida não há o que medir, e fingir
    que há é o erro que a §1.5 denuncia.

    `score_min` aplica a cláusula X.2 do veredito (references/alinhamento.md):
    palavra com score baixo não tem posição confiável.
    """
    out = []
    for i in range(len(words_asr)):
        if words_al[i]["fonte"] != "align":
            continue
        if (words_al[i].get("score") or 0.0) < score_min:
            continue
        g = words_asr[i]["start"] - words_asr[i - 1]["end"] if i > 0 else 1e9
        if g < gap_min:
            continue
        out.append(i)
        if limite and len(out) >= limite:
            break
    return out


def medir(a, db, words_asr, words_al, idx, modo, janela):
    """→ (errs_asr, errs_align, refs, t_ref) em ms; refs = fronteiras com referência."""
    ea, el, refs, tref = [], [], [], []
    for i in idx:
        t_asr, t_al = words_asr[i]["start"], words_al[i]["start"]
        centro = (t_asr + t_al) / 2.0
        r = ref_envelope(db, centro, janela) if modo == "envelope" else ref_fonemas(a, centro, janela)
        if r is None:
            continue
        refs.append(i)
        tref.append(r)
        ea.append((t_asr - r) * 1000)
        el.append((t_al - r) * 1000)
    return np.array(ea), np.array(el), refs, np.array(tref)


def main():
    ap = argparse.ArgumentParser(description="régua do alinhador (SPEC-04 §3.5)")
    ap.add_argument("dir", type=Path)
    ap.add_argument("--ref", default="todas", choices=["envelope", "fonemas", "edl", "todas"])
    ap.add_argument("--edl", type=Path, default=None)
    ap.add_argument("--audio", type=Path, default=None)
    ap.add_argument("--alignment", type=Path, default=None, help="default: <dir>/alignment.json")
    ap.add_argument("--n", type=int, default=0, help="máx. de fronteiras (0 = todas)")
    ap.add_argument("--gap", type=float, default=0.15, help="pausa mínima antes da palavra")
    ap.add_argument("--score-min", type=float, default=0.0,
                    help="descarta palavra com score abaixo disto (cláusula X.2 do veredito)")
    ap.add_argument("--janela", type=float, default=0.30, help="raio de busca da referência")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    d = args.dir
    al_p, tr_p = (args.alignment or d / "alignment.json"), d / "transcript.json"
    for p in (al_p, tr_p):
        if not p.exists():
            sys.exit(f"ERRO: falta {p} (rode alinhar.py antes).")
    al = json.loads(al_p.read_text())
    words_al = al["words"]
    words_asr = json.loads(tr_p.read_text())["results"]["channels"][0]["alternatives"][0]["words"]
    if len(words_al) != len(words_asr):
        sys.exit(f"ERRO: alignment ({len(words_al)}) e transcript ({len(words_asr)}) divergem.")

    audio = args.audio or (d / al.get("audio", "audio.mp3"))
    if not audio.exists():
        sys.exit(f"ERRO: áudio não encontrado: {audio}")

    print(f"== {d}  ({len(words_asr)} palavras · áudio {audio.name})", file=sys.stderr)
    a = carregar(audio)
    db = envelope_db(a)

    idx = fronteiras(words_asr, words_al, args.gap, args.n, args.score_min)
    print(f"   fronteiras candidatas (word start após pausa >= {args.gap * 1000:.0f} ms, "
          f"palavra alinhada, score >= {args.score_min:.2f}): n={len(idx)} de {len(words_asr)}",
          file=sys.stderr)

    modos = ["envelope", "fonemas"] if args.ref == "todas" else [args.ref]
    resumo = {}

    for modo in modos:
        if modo == "edl":
            resumo["edl"] = ref_edl(d, args.edl, words_asr, words_al)
            continue
        ea, el, refs, tref = medir(a, db, words_asr, words_al, idx, modo, args.janela)
        print(f"\n-- referência: {modo}   (varridas {len(idx)}, "
              f"com referência detectada n={len(refs)}; {len(idx) - len(refs)} sem onset na janela)",
              file=sys.stderr)
        if modo == "envelope":
            print("   ⚠️ o envelope é CEGO para fricativa surda e nasal — use --ref fonemas ao lado.",
                  file=sys.stderr)
        if len(refs) == 0:
            print("   n=0 — nada medido. NÃO é resultado limpo, é ausência de medição.", file=sys.stderr)
            resumo[modo] = {"n": 0}
            continue

        s_a, s_l = stats(ea), stats(el)
        vit = float((np.abs(el) < np.abs(ea)).mean() * 100)
        print(linha("ASR cru", s_a, modo), file=sys.stderr)
        print(linha("ALINHADO", s_l, modo), file=sys.stderr)
        print(f"  {'taxa de vitória':<22s} n={len(el):<4d} "
              f"alinhado mais perto da referência em {int((np.abs(el) < np.abs(ea)).sum())}/{len(el)} "
              f"= {vit:.1f}%   [--ref {modo}]", file=sys.stderr)

        # ---- controles ----------------------------------------------------
        c0 = stats((tref - tref) * 1000)
        cA = stats((tref + DESLOC - tref) * 1000)
        cB = stats(el + DESLOC * 1000)
        a_s = np.concatenate([np.zeros(int(DESLOC_D * SR), dtype=np.float32), a])
        db_s = envelope_db(a_s)
        mov = []
        for i, r0 in zip(refs, tref):
            c = (words_asr[i]["start"] + words_al[i]["start"]) / 2.0 + DESLOC_D
            r1 = ref_envelope(db_s, c, args.janela) if modo == "envelope" else ref_fonemas(a_s, c, args.janela)
            if r1 is not None:
                mov.append((r1 - r0 - DESLOC_D) * 1000)
        cD = stats(mov)
        # CONTROLE-E: candidato de uma fronteira contra a referência de OUTRA.
        # Se a referência não localiza nada de específico, isto continua pequeno.
        t_al = np.array([words_al[i]["start"] for i in refs])
        cE = stats((t_al - np.roll(tref, 1)) * 1000) if len(refs) > 2 else stats([])

        print(f"  CONTROLE-0  n={c0['n']:<4d} candidato = a própria referência        "
              f"→ mediana |erro| {c0['mediana_abs']:.1f} ms  (tem que ser 0)", file=sys.stderr)
        print(f"  CONTROLE-A  n={cA['n']:<4d} candidato = referência +100 ms          "
              f"→ mediana |erro| {cA['mediana_abs']:.1f} ms  (tem que ser 100 ± 20)", file=sys.stderr)
        print(f"  CONTROLE-B  n={cB['n']:<4d} alinhado +100 ms                        "
              f"→ viés {s_l['vies']:+.1f} → {cB['vies']:+.1f} ms  "
              f"(deslocou {cB['vies'] - s_l['vies']:+.1f}, tem que ser +100 ± 20)", file=sys.stderr)
        print(f"  CONTROLE-D  n={cD['n']:<4d} áudio +103 ms de silêncio na frente     "
              f"→ a REFERÊNCIA andou {cD['vies'] + DESLOC_D * 1000:+.1f} ms "
              f"(resíduo {cD['vies']:+.1f}; tem que ser +103 ± 20). "
              f"Régua circular reprova aqui.", file=sys.stderr)
        print(f"  CONTROLE-E  n={cE['n']:<4d} candidato × referência DE OUTRA fronteira "
              f"→ mediana |erro| {cE['mediana_abs']:.0f} ms  "
              f"(tem que EXPLODIR; se ficar pequeno, a referência não localiza nada)",
              file=sys.stderr)

        resumo[modo] = {
            "ref": modo, "n_varridas": len(idx), "n": len(refs),
            "asr": s_a, "alinhado": s_l, "taxa_vitoria_pct": round(vit, 1),
            "controle_0_ms": round(c0["mediana_abs"], 1),
            "controle_A_ms": round(cA["mediana_abs"], 1),
            "controle_B_desloc_ms": round(cB["vies"] - s_l["vies"], 1),
            "controle_D_desloc_ms": round(cD["vies"] + DESLOC_D * 1000, 1) if cD["n"] else None,
            "controle_D_n": cD["n"],
            "controle_E_ms": round(cE["mediana_abs"], 1) if cE["n"] else None,
        }

    if args.json:
        print(json.dumps({"dir": str(d), "refs": resumo}, ensure_ascii=False, indent=1))
    return resumo


def ref_edl(d: Path, edl_p: Path | None, words_asr, words_al):
    """Fronteiras de um editor humano externo — COM guarda de circularidade.

    Se as fronteiras da EDL coincidem com timestamps do ASR, elas não são
    evidência independente: o erro do ASR contra elas é 0 por construção, e
    publicar esse número seria repetir exatamente o que a §1.5 denuncia no
    ref-A. Neste caso o script mede a coincidência, diz o número e RECUSA.
    """
    p = edl_p or (d / "edl-medida.json")
    if not p.exists():
        print(f"\n-- referência: edl   INDISPONÍVEL: {p} não existe. n=0.", file=sys.stderr)
        return {"n": 0, "motivo": f"{p} não existe"}
    e = json.loads(p.read_text())
    ts = []
    for s in e:
        for campo in ("raw_asr", "raw", "bruto"):
            if campo in s and isinstance(s[campo], list) and len(s[campo]) == 2:
                ts += [float(s[campo][0]), float(s[campo][1])]
                break
    st = {round(x["start"], 3) for x in words_asr}
    en = {round(x["end"], 3) for x in words_asr}
    bate = sum(1 for t in ts if round(t, 3) in st or round(t, 3) in en)
    print(f"\n-- referência: edl   ({p})", file=sys.stderr)
    print(f"   fronteiras na EDL: n={len(ts)} · coincidem EXATAMENTE com um "
          f"timestamp do ASR: {bate}/{len(ts)} = {bate / max(len(ts), 1) * 100:.0f}%", file=sys.stderr)
    if len(ts) and bate / len(ts) >= 0.5:
        print("   🔴 RECUSADO: esta EDL é DERIVADA DO ASR — não é evidência independente.", file=sys.stderr)
        print("      Medir o ASR contra ela dá erro 0 por construção. É a alegação circular", file=sys.stderr)
        print("      da §1.5, e repeti-la aqui seria pior, porque nós sabemos. n=0 publicado.", file=sys.stderr)
        return {"n": 0, "motivo": "EDL derivada do ASR (circular)",
                "coincidencia_pct": round(bate / len(ts) * 100, 1)}
    print("   (EDL independente do ASR — medição de fronteira de corte não implementada nesta", file=sys.stderr)
    print("    spec: corte de EDL é borda de SEGMENTO, e borda de corte é do bordas.py.)", file=sys.stderr)
    return {"n": 0, "motivo": "EDL independente, mas fora do escopo desta spec"}


if __name__ == "__main__":
    main()
