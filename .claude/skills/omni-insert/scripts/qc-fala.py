#!/usr/bin/env python3
"""QC do modo `edit`: a fala devolvida continua sendo a do creator, íntegra?

No modo edit o Omni re-sintetiza a trilha preservando a voz. O que se mede aqui:

1. **Acústica** (o veredito): F0, similaridade espectral e correlação do envelope
   depois de alinhar. É isto que diz se a voz é a mesma e se a fala foi respeitada.
2. **ASR** (só indício): transcreve fonte e resultado e mostra o diff das palavras.
   ⚠️ Divergência de ASR **não** é prova de defeito — na primeira vez que este
   script acusou "fala alterada" ("conta que tinha gasto" → "conta tinha gasto
   gasto"), o áudio real tinha mesmo a repetição: o creator gaguejou na gravação e
   o Omni foi fiel; quem errou foi o reconhecedor. Use o diff pra saber ONDE ouvir.

Uso: qc-fala.py <original.mp4> <editado.mp4> [--lang pt] [--sem-asr]
Código 1 só quando a ACÚSTICA reprova.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np

DG = os.environ.get("DEEPGRAM_API_KEY")
MODEL = os.environ.get("BENCH_DG_MODEL", "nova-3")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def pcm(path, sr=16000):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-f", "s16le",
                        "-ac", "1", "-ar", str(sr), "-"], capture_output=True).stdout
    return np.frombuffer(r, dtype=np.int16).astype(float)


def f0_mediano(x, sr=16000, win=1024, hop=512):
    vals = []
    for i in range(0, len(x) - win, hop):
        s = x[i:i + win]
        if np.abs(s).mean() < 200:
            continue
        s = s - s.mean()
        ac = np.correlate(s, s, "full")[win - 1:]
        lo, hi = int(sr / 350), int(sr / 70)
        if hi >= len(ac):
            continue
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.3 * ac[0]:
            vals.append(sr / k)
    return float(np.median(vals)) if vals else 0.0


def espectro(x, n=4096):
    acc, c = np.zeros(n // 2), 0
    for i in range(0, len(x) - n, n):
        s = x[i:i + n]
        if np.abs(s).mean() < 200:
            continue
        acc += np.abs(np.fft.rfft(s * np.hanning(n))[:n // 2])
        c += 1
    return acc / max(c, 1)


def envelope(x, w=160):
    n = len(x) // w * w
    return np.abs(x[:n]).reshape(-1, w).mean(1)


def palavras(path, lang):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn",
                    "-ac", "1", "-ar", "16000", wav], check=True)
    data = open(wav, "rb").read()
    os.unlink(wav)
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?model={MODEL}&language={lang}&smart_format=false",
        data=data, method="POST",
        headers={"Authorization": f"Token {DG}", "Content-Type": "audio/wav"})
    with urllib.request.urlopen(req, timeout=300) as r:
        alt = json.loads(r.read())["results"]["channels"][0]["alternatives"][0]
    return [w["word"].lower() for w in alt["words"]]


def main():
    orig, edit = sys.argv[1], sys.argv[2]
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "pt"
    o, e = pcm(orig), pcm(edit)
    if not len(o) or not len(e):
        sys.exit("um dos arquivos não tem trilha de áudio "
                 "(se a fonte foi cortada com -an, o Omni inventa a voz)")

    fo, fe = f0_mediano(o), f0_mediano(e)
    dif_f0 = abs(fe - fo) / max(fo, 1) * 100
    so, se = espectro(o), espectro(e)
    so, se = so / max(np.linalg.norm(so), 1e-9), se / max(np.linalg.norm(se), 1e-9)
    cos = float(so @ se)

    ea, eb = envelope(o), envelope(e)
    n = min(len(ea), len(eb))
    cc = np.correlate(eb[:n] - eb[:n].mean(), ea[:n] - ea[:n].mean(), "full")
    lag = (int(cc.argmax()) - (n - 1)) * 160 / 16000
    desl = int(round(lag * 16000 / 160))
    aa = ea[max(0, -desl):n - max(0, desl)]
    bb = eb[max(0, desl):n - max(0, -desl)]
    m = min(len(aa), len(bb))
    corr = float(np.corrcoef(aa[:m], bb[:m])[0, 1]) if m > 10 else 0.0

    log(f"[voz]  F0 {fo:.1f} → {fe:.1f} Hz ({dif_f0:.1f}%) · espectro {cos:.3f}")
    log(f"[fala] alinhamento {lag:+.2f}s · correlação do envelope {corr:.3f}")

    ok_voz = dif_f0 < 8 and cos > 0.90
    ok_fala = corr > 0.60
    log(f"[voz]  {'✅ mesma voz' if ok_voz else '❌ timbre destoa — conferir'}")
    log(f"[fala] {'✅ fala preservada' if ok_fala else '⚠️ prosódia destoa — OUVIR o trecho'}")

    if DG and "--sem-asr" not in sys.argv:
        try:
            pa, pb = palavras(orig, lang), palavras(edit, lang)
            if pa == pb:
                log(f"[asr]  ✅ mesmas {len(pa)} palavras")
            else:
                import difflib
                log(f"[asr]  ℹ️ transcrição diferente ({len(pa)} → {len(pb)} palavras) — "
                    "indício, não veredito; ouça o trecho")
                for l in difflib.unified_diff(pa, pb, "fonte", "editado", lineterm="", n=1):
                    log("       " + l)
        except Exception as ex:
            log(f"[asr]  (pulado: {ex})")
    elif "--sem-asr" in sys.argv:
        log("[asr]  pulado — --sem-asr na linha de comando")
    else:
        # 🔴 SILÊNCIO DE CONFIGURAÇÃO (achado A20). Sem a chave, o bloco ASR
        # simplesmente não rodava e NENHUMA linha dizia isso: a saída ficava com
        # dois ✅ e parecia completa. É a classe de defeito que este produto diz
        # combater, dentro do próprio produto.
        log("[asr]  pulado — sem DEEPGRAM_API_KEY: a conferência de PALAVRA "
            "não rodou (timbre e prosódia acima continuam valendo)")

    return 0 if (ok_voz and ok_fala) else 1


if __name__ == "__main__":
    sys.exit(main())
