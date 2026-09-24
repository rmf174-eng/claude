#!/usr/bin/env python3
"""alinhar — engine de TEMPO (SPEC-04). O Deepgram continua sendo o engine de TEXTO.

POR QUE ISTO EXISTE
    O Deepgram entrega o texto certo em cima de uma grade de tempo de 80 ms
    (medido em 5 transcripts deste repo: 94–97% dos limites distintos são
    múltiplos exatos de 80 ms, e a menor duração de palavra é exatamente 80 ms).
    80 ms = 2,4 frames a 30 fps. E o erro não é simétrico: a energia da próxima
    palavra já sobe 30–260 ms antes do `start` informado.

    Este bloco NÃO transcreve. Ele recebe áudio + as palavras que o ASR já
    achou e mede, contra o próprio áudio, onde cada uma começa — alinhamento
    forçado CTC com `torchaudio.pipelines.MMS_FA` (multilíngue, roda em MPS).
    Stride medido: 20,0 ms, quatro vezes mais fino que a grade do ASR.

⚠️  O `end_ctc` NÃO É A SOLTURA ACÚSTICA — e o contrato PROÍBE usá-lo como
    borda de corte. CTC marca o último frame em que o token ainda é emitido,
    não o fim do som. Medido contra o Deepgram: mediana de **−141 ms** (n=35).
    Quem quer borda de corte usa `edit-video/scripts/bordas.py`
    (`decay_relativo()` existe justamente para achar a soltura, e a cauda de
    "disso."/"mundo." vive 0,3–0,4 s depois do fim do span CTC).
    Quem quer legenda karaokê usa o `start` alinhado e estende a palavra até o
    `start` da próxima — que é o que a legenda quer de qualquer jeito.

🔴 O `score` É O PORTÃO, não um enfeite. Palavra com score baixo NÃO tem posição
    confiável, e nenhuma outra salvaguarda deste bloco cobre isso. Medido em
    `peca-03/take-A` com `--chunk 25`: a palavra "Comente", encostada num
    silêncio de 4,22 s, escorregou **4.121 ms** para trás — e o score dela caiu de
    0,944 para **0,014**. Filtrando `score >= 0,30`, o erro máximo entre
    chunkings volta de 1.215 ms para 28 ms. Quem consumir o `alignment.json` sem
    olhar o score reintroduz o defeito. Números em `references/alinhamento.md` §8.

O QUE ESTE ARQUIVO NÃO SABE (SPEC-00, §3.6)
    Não sabe o que é fps, resolução, aspecto ou alvo de loudness. Os únicos
    números aqui são propriedades do modelo (16 kHz de entrada, 20 ms de
    stride) e parâmetros de CLI. A saída é em SEGUNDOS, float — quantizar para
    frame é trabalho do compositor, e o fps vem do perfil de peça.
    Não lê `creators/`, não lê perfil, não tem caminho absoluto.

Uso:
    alinhar.py <dir-ou-audio> [--transcript P] [--out P] [--audio P]
               [--device auto|mps|cpu] [--chunk 180] [--pad 1.0]
               [--idioma pt] [--sem-star] [--json] [--force]

stdout = caminho do alignment.json.  logs = stderr.  Idempotente.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

SCHEMA = "benchmark.alignment/v1"
SR = 16000  # taxa de entrada do MMS_FA. Propriedade do modelo, não de formato.
ALFABETO = set("abcdefghijklmnopqrstuvwxyz'")


def log(*a):
    print(*a, file=sys.stderr)


# --------------------------------------------------------------------------
# 0. venv — este script roda com o python do alinhador, não com o do sistema
# --------------------------------------------------------------------------
def python_do_venv() -> Path | None:
    """Ordem fixa, sem caminho absoluto cravado (a mesma do bootstrap-aligner.sh):
    1. $BENCH_ALIGNER_DIR  2. subindo daqui, o 1º dir com tools/aligner/venv já
    pronto (ou, na falta, o 1º com tools/)  3. ${ILHA_HOME:-~/.ilha}/aligner
    """
    cands = []
    if os.environ.get("BENCH_ALIGNER_DIR"):
        cands.append(Path(os.environ["BENCH_ALIGNER_DIR"]))
    # `abspath` normaliza ".." sem resolver symlink — o caminho lógico de invocação
    d = Path(os.path.abspath(__file__)).parent
    com_tools = []
    for _ in range(8):
        if (d / "tools" / "aligner" / "venv" / "bin" / "python").exists():
            cands.append(d / "tools" / "aligner")
            break
        if (d / "tools").is_dir():
            com_tools.append(d / "tools" / "aligner")
        if d.parent == d:
            break
        d = d.parent
    cands += com_tools
    cands.append(Path(os.environ.get("ILHA_HOME", str(Path.home() / ".ilha"))) / "aligner")
    for c in cands:
        p = c / "venv" / "bin" / "python"
        if p.exists():
            return p
    return None


def garantir_venv():
    try:
        import torch  # noqa: F401
        return
    except ImportError:
        pass
    py = python_do_venv()
    if py is None:
        sys.exit("ERRO: torch não disponível e venv do alinhador não encontrado.\n"
                 "      Rode primeiro: bootstrap-aligner.sh --baixar-modelo")
    if os.environ.get("_ALINHAR_REEXEC") == "1":
        sys.exit(f"ERRO: {py} não importa torch. Refaça o venv (bootstrap-aligner.sh).")
    os.environ["_ALINHAR_REEXEC"] = "1"
    os.execv(str(py), [str(py), os.path.abspath(__file__)] + sys.argv[1:])


# --------------------------------------------------------------------------
# 1. entrada
# --------------------------------------------------------------------------
def resolver(alvo: Path, transcript: Path | None, audio: Path | None, out: Path | None):
    """dir → <dir>/audio.mp3 + <dir>/transcript.json; arquivo → o próprio."""
    if alvo.is_dir():
        base = alvo
        if audio is None:
            for nome in ("audio.mp3", "audio.wav", "audio16k.wav", "video.mp4"):
                if (base / nome).exists():
                    audio = base / nome
                    break
    else:
        base = alvo.parent
        if audio is None:
            audio = alvo
    if transcript is None:
        transcript = base / "transcript.json"
    if out is None:
        out = base / "alignment.json"
    if audio is None or not audio.exists():
        sys.exit(f"ERRO: áudio não encontrado (procurei em {base}). Use --audio.")
    if not transcript.exists():
        sys.exit(f"ERRO: transcript não encontrado: {transcript}")
    return audio, transcript, out


def ler_words(transcript: Path):
    """Palavras do Deepgram, na ordem, com o texto original intocado."""
    j = json.loads(transcript.read_text())
    try:
        w = j["results"]["channels"][0]["alternatives"][0]["words"]
    except (KeyError, IndexError):
        sys.exit(f"ERRO: {transcript} não parece um transcript.json do Deepgram.")
    return [
        {
            "word": x.get("punctuated_word") or x.get("word") or "",
            "start": float(x["start"]),
            "end": float(x["end"]),
        }
        for x in w
    ]


def normalizar(palavra: str) -> str:
    """Texto original → alfabeto do MMS_FA.

    NFD → remove combining marks → minúscula → mantém só [a-z'].
    "não"→"nao"  "você"→"voce"  "R$13,60"→""  "100%"→""  "2014."→""
    Token vazio NÃO é descartado: a palavra herda fronteira do vizinho (§9.4).
    """
    s = unicodedata.normalize("NFD", palavra)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    return "".join(c for c in s if c in ALFABETO)


# --------------------------------------------------------------------------
# 2. chunking por gap de palavra
# --------------------------------------------------------------------------
def chunks_por_gap(words, alvo_s: float):
    """Parte a lista em blocos cortando no MAIOR GAP dentro de [0.7·alvo, 1.3·alvo].

    Cortar dentro de uma palavra quebra a cadeia CTC e inventa fronteira.
    Cortar num gap real de fala não custa nada — é o mesmo critério do
    cut-breaths por word-gap, que é o método deste sistema desde 2026-07-22.
    O corte é sempre ENTRE palavras: cada palavra pertence a exatamente um
    chunk e não há costura a resolver.
    """
    n = len(words)
    lo, hi = alvo_s * 0.7, alvo_s * 1.3
    blocos, i = [], 0
    while i < n:
        t0 = words[i]["start"]
        melhor_j, melhor_gap = None, -1.0
        j = i + 1
        while j < n and (words[j - 1]["end"] - t0) <= hi:
            if (words[j - 1]["end"] - t0) >= lo:
                gap = words[j]["start"] - words[j - 1]["end"]
                if gap > melhor_gap:
                    melhor_gap, melhor_j = gap, j
            j += 1
        if melhor_j is None:
            melhor_j = min(j, n)
        blocos.append((i, melhor_j))
        i = melhor_j
    return blocos


# --------------------------------------------------------------------------
# 3. áudio
# --------------------------------------------------------------------------
def decodificar(audio: Path, tmpdir: str):
    """ffmpeg → raw f32 mono 16 kHz num arquivo temporário, lido por memmap.

    Decodifica UMA vez e fatia por memmap: o resultado não depende do chunking
    (é o que o teste de invariância `--chunk 180` vs `--chunk 90` cobra) e a
    memória não cresce com a duração.
    """
    import numpy as np

    raw = os.path.join(tmpdir, "a.f32")
    cmd = ["ffmpeg", "-v", "error", "-i", str(audio), "-vn",
           "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SR), "-y", raw]
    subprocess.run(cmd, check=True)
    n = os.path.getsize(raw) // 4
    return np.memmap(raw, dtype="float32", mode="r", shape=(n,)), n / SR


# --------------------------------------------------------------------------
# 4. mapa ASR → alinhado, para as palavras sem token
# --------------------------------------------------------------------------
def mapa_piecewise(knots_x, knots_y):
    """Interpolação linear monótona por partes. Fora do domínio, extrapola pelo extremo."""
    def f(x):
        if not knots_x:
            return x
        if x <= knots_x[0]:
            return knots_y[0] + (x - knots_x[0])
        if x >= knots_x[-1]:
            return knots_y[-1] + (x - knots_x[-1])
        lo, hi = 0, len(knots_x) - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if knots_x[m] <= x:
                lo = m
            else:
                hi = m
        dx = knots_x[hi] - knots_x[lo]
        if dx <= 0:
            return knots_y[lo]
        t = (x - knots_x[lo]) / dx
        return knots_y[lo] + t * (knots_y[hi] - knots_y[lo])
    return f


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="alinhamento forçado CTC local (SPEC-04)")
    ap.add_argument("alvo", type=Path, help="dir da produção ou arquivo de áudio")
    ap.add_argument("--transcript", type=Path, default=None)
    ap.add_argument("--audio", type=Path, default=None,
                    help="áudio alternativo (o mp3 de 48k é insumo capado — §9.5)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cpu", "cuda"])
    ap.add_argument("--chunk", type=float, default=180.0, help="alvo em s; corte real cai no maior gap")
    ap.add_argument("--pad", type=float, default=1.0, help="contexto de áudio fora do chunk")
    ap.add_argument("--idioma", default=None, help="ignorado pelo MMS_FA (multilíngue); aceito para futuro")
    ap.add_argument("--star", dest="star", action="store_true", default=True,
                    help="token <star> do MMS_FA absorvendo o áudio do pad (LIGADO por padrão)")
    ap.add_argument("--sem-star", dest="star", action="store_false",
                    help="desliga o <star>. Medido em take-A, --chunk 180 vs 90: sem star "
                         "p99 35,2 ms / max 118,3 ms; com star 22,0 / 28,7 ms; e --pad 3.0 "
                         "SEM star vai a max 1.542 ms (o pad vira fala não modelada)")
    ap.add_argument("--json", action="store_true", help="resumo em json no stderr")
    ap.add_argument("--force", action="store_true", help="refaz mesmo se o alignment.json existir")
    args = ap.parse_args()

    garantir_venv()

    audio, transcript, out = resolver(args.alvo, args.transcript, args.audio, args.out)

    # idempotência
    if out.exists() and not args.force:
        try:
            if json.loads(out.read_text()).get("schema") == SCHEMA:
                log(f">> alignment.json já existe e o schema bate, pulando (--force pra refazer).")
                print(out)
                return
        except Exception:
            pass

    words = ler_words(transcript)
    if not words:
        sys.exit("ERRO: transcript sem palavras.")
    tokens = [normalizar(w["word"]) for w in words]
    n_sem = sum(1 for t in tokens if not t)
    log(f">> {len(words)} palavras · {n_sem} sem token ({n_sem / len(words) * 100:.1f}%) · "
        f"{words[-1]['end'] - words[0]['start']:.1f}s de fala")

    import numpy as np
    import torch
    from torchaudio.pipelines import MMS_FA as bundle

    if args.device == "auto":
        dev = ("mps" if torch.backends.mps.is_available()
               else "cuda" if torch.cuda.is_available() else "cpu")
    else:
        dev = args.device
    log(f">> device: {dev}")

    modelo = bundle.get_model(with_star=args.star).to(dev).eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()
    star_id = bundle.get_dict().get("*") if args.star else None

    blocos = chunks_por_gap(words, args.chunk)
    log(f">> {len(blocos)} chunk(s) (alvo {args.chunk:.0f}s, pad {args.pad:.1f}s)")

    t_ini_exec = time.time()
    saida = [None] * len(words)
    stride_visto = []

    with tempfile.TemporaryDirectory(prefix="alinhar-") as tmp:
        wav_all, dur = decodificar(audio, tmp)
        log(f">> áudio: {audio.name} · {dur:.1f}s")

        for (a, b) in blocos:
            idx = [k for k in range(a, b) if tokens[k]]
            t_ini = max(0.0, words[a]["start"] - args.pad)
            t_fim = min(dur, words[b - 1]["end"] + args.pad)
            s0, s1 = int(round(t_ini * SR)), int(round(t_fim * SR))
            if s1 <= s0:
                continue
            wav = torch.from_numpy(np.array(wav_all[s0:s1], dtype="float32")).unsqueeze(0)
            if not idx:
                continue
            with torch.inference_mode():
                emission, _ = modelo(wav.to(dev))
            emission = emission.cpu()
            n_frames = emission.size(1)
            stride = wav.size(1) / n_frames / SR  # s por frame
            stride_visto.append(stride)

            toks = tokenizer([tokens[k] for k in idx])
            if args.star and star_id is not None:
                # star ANTES e DEPOIS: o `--pad` traz áudio que não está na lista de
                # tokens, e sem um token para absorvê-lo o CTC empurra a fronteira da
                # primeira/última palavra do chunk para dentro do pad.
                toks = [[star_id]] + toks + [[star_id]]
            spans = aligner(emission[0], toks)
            if args.star and star_id is not None:
                spans = spans[1:-1]
            assert len(spans) == len(idx), (len(spans), len(idx))

            for k, sp in zip(idx, spans):
                dur_tot = sum(s.end - s.start for s in sp) or 1
                score = sum(s.score * (s.end - s.start) for s in sp) / dur_tot
                saida[k] = {
                    "start": t_ini + sp[0].start * stride,
                    "end_ctc": t_ini + sp[-1].end * stride,
                    "score": round(float(score), 4),
                }
            del emission, wav

    seg = time.time() - t_ini_exec

    # Palavras sem token herdam fronteira do vizinho por um mapa ASR→alinhado
    # construído SÓ com os `start` alinhados.
    # ⚠️ Usar `end_ctc` como nó do mapa é um defeito medido: o `end_ctc` é
    # justamente a grandeza instável (§3.4) e, numa palavra encostada num
    # silêncio longo, ele passeia. Medido em take-A, palavra "2." antes de um
    # gap de 6,8 s: com nós de end_ctc o tempo dela mudava **370,7 ms** entre
    # `--chunk 180` e `--chunk 90`; só com nós de `start`, some.
    kx, ky = [], []
    for k, s in enumerate(saida):
        if s is None:
            continue
        x, y = words[k]["start"], s["start"]
        if not kx or x > kx[-1]:
            kx.append(x)
            ky.append(max(y, ky[-1] if ky else y))
    f = mapa_piecewise(kx, ky)

    res, prev = [], -1e9
    n_align = 0
    for k, w in enumerate(words):
        if saida[k] is not None:
            st, en, sc, fonte = saida[k]["start"], saida[k]["end_ctc"], saida[k]["score"], "align"
            n_align += 1
        else:
            st, en, sc, fonte = f(w["start"]), f(w["end"]), None, "asr"
        st = max(st, prev)          # invariante: start monotônico não decrescente
        en = max(en, st)            # invariante: end_ctc >= start
        prev = st
        res.append({
            "i": k, "word": w["word"], "token": tokens[k],
            "start": round(st, 4), "end_ctc": round(en, 4),
            "score": sc, "fonte": fonte,
        })

    # --- invariantes do §4.1, verificados com assert (nunca perder palavra) ---
    assert len(res) == len(words), (len(res), len(words))
    assert all(res[i]["i"] == i for i in range(len(res)))
    assert all(res[i]["word"] == words[i]["word"] for i in range(len(res)))
    assert all(res[i]["start"] <= res[i + 1]["start"] for i in range(len(res) - 1))
    assert all(r["end_ctc"] >= r["start"] for r in res)
    assert all(r["fonte"] == "asr" for r in res if r["token"] == "")

    doc = {
        "schema": SCHEMA,
        "engine": "torchaudio/MMS_FA",
        "device": dev,
        "stride_ms": round(sum(stride_visto) / len(stride_visto) * 1000, 3) if stride_visto else None,
        "fonte_texto": "deepgram/nova-3",
        "audio": audio.name,
        "chunk_alvo_s": args.chunk,
        "pad_s": args.pad,
        "star": bool(args.star),
        "chunks": len(blocos),
        "duracao_s": round(dur, 3),
        "words": res,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    pct = n_align / len(res) * 100
    log(f">> alinhadas {n_align}/{len(res)} ({pct:.1f}%) · stride {doc['stride_ms']} ms · "
        f"{seg:.1f}s ({seg / max(dur, 1e-9):.3f}× realtime)")
    if args.json:
        log(json.dumps({"words": len(res), "align": n_align, "pct_align": round(pct, 1),
                        "chunks": len(blocos), "device": dev, "s": round(seg, 1),
                        "x_realtime": round(seg / max(dur, 1e-9), 4)}, ensure_ascii=False))
    print(out)


if __name__ == "__main__":
    main()
