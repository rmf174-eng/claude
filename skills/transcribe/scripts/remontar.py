#!/usr/bin/env python3
"""remontar — costura as partes de uma transcrição longa NUM VALE DE SILÊNCIO.

O DEFEITO QUE ISTO SUBSTITUI
----------------------------
O `transcribe-longo.sh` antigo fatiava em `i*PARTE` com `-t PARTE` e o merge era
concatenação pura (`a0["words"].extend(a1["words"])`): sem overlap, sem
deduplicação, sem nenhuma verificação de que a emenda era limpa. A fronteira caía
onde caísse — inclusive no meio de uma palavra, que ia partida para dois requests
diferentes. Assinatura medida em `data/adhoc/aula-longa-02`: a última palavra
de cada parte tem `end` 3000,835 s e 6001,050 s **em chunks de 3.000,0 s** — o
engine esticando a palavra para além do fim do arquivo que recebeu.

POR QUE COSTURA POR TEMPO E NÃO DEDUPLICAÇÃO POR TEXTO
-------------------------------------------------------
Já está medido neste repo que comparar transcrição com transcrição dá falso
positivo em toda gagueira, repetição e estrangeirismo (rodada 4 do omni-insert: o
`qc-fala.py` teve que ser reescrito por isso — "transcrição não é verdade
acústica"). Alinhar strings na zona de overlap reintroduz exatamente esse erro.
Escolhendo um instante `T` que cai NO SILÊNCIO, o corte é trivialmente exato:
nenhuma palavra atravessa `T`, logo não há o que deduplicar nem o que perder.

Uso:
  remontar.py <dir-com-.partes> [--audio PATH] [--out DIR] [--guarda 3.0]

Lê  <dir>/.partes/pN/{transcript.json,fatia.json}   (transcripts CRUS, sem offset)
Escreve <out>/transcript.json + transcript.md; imprime o caminho no stdout.

⚠️ Os transcripts em `.partes/` ficam SEM offset de propósito: o offset é aplicado
aqui, a cada execução. É isso que torna `--remontar` idempotente e repetível de
graça — aplicar offset in-place duas vezes dobraria o deslocamento.
"""
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from envelope import envelope, piso_adaptativo, vales  # noqa: E402

CONTRATO = "benchmark.transcribe/v1"
GUARDA = 3.0        # s descartados em cada ponta da zona de overlap
MIN_VALE = 0.25     # silêncio mínimo para servir de costura
MIN_GAP = 0.15      # buraco mínimo entre palavras no fallback "gap-asr"
CANDIDATOS_AUDIO = ("audio.mp3", "audio.m4a", "audio.wav", "audio.ogg",
                    "audio.flac", "video.mp4")


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def alt_de(j):
    return j["results"]["channels"][0]["alternatives"][0]


def desloca(j, off):
    """Aplica o offset da parte. Opera sobre uma cópia — o cache fica cru."""
    a = alt_de(j)
    for w in a.get("words") or []:
        w["start"] += off
        w["end"] += off
    for par in (a.get("paragraphs") or {}).get("paragraphs") or []:
        par["start"] += off
        par["end"] += off
        for s in par.get("sentences", []):
            s["start"] += off
            s["end"] += off
    for u in j["results"].get("utterances") or []:
        u["start"] += off
        u["end"] += off
        for w in u.get("words") or []:
            w["start"] += off
            w["end"] += off
    return j


# ── escolha do ponto de costura ─────────────────────────────────────────────
def _livres(ws, t0, t1):
    """Intervalos dentro de [t0,t1] que NÃO são cobertos por palavra."""
    spans = sorted((max(w["start"], t0), min(w["end"], t1)) for w in ws
                   if w["end"] > t0 and w["start"] < t1)
    out, cur = [], t0
    for a, b in spans:
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < t1:
        out.append((cur, t1))
    return out


def _intersecta(as_, bs):
    out = []
    for a0, a1 in as_:
        for b0, b1 in bs:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                out.append((lo, hi))
    return out


def escolher_costura(db, piso, b, overlap, palavras_esq, palavras_dir):
    """Instante T onde emendar a parte que termina depois de `b` com a seguinte.

    1. vale acústico dentro da janela de busca, o mais LONGO (desempate: mais
       perto do centro da janela);
    2. senão, o maior buraco que seja buraco NOS DOIS lados (>= MIN_GAP);
    3. senão, o meio da zona de overlap, marcado como suspeita.
    """
    t0, t1 = b + GUARDA, b + overlap - GUARDA
    centro = (t0 + t1) / 2.0
    if t1 > t0:
        cand = []
        for a, z in vales(db, t0, t1, piso, minimo=MIN_VALE):
            t = (a + z) / 2.0
            # um vale cujo centro é atravessado por palavra de qualquer lado não
            # é silêncio de verdade para os dois requests — descarta.
            if any(w["start"] < t < w["end"] for w in palavras_esq):
                continue
            if any(w["start"] < t < w["end"] for w in palavras_dir):
                continue
            cand.append((z - a, -abs(t - centro), t))
        if cand:
            dur, _, t = max(cand)
            return {"t": round(t, 3), "silencio_s": round(dur, 3),
                    "metodo": "vale", "suspeita": False}

        duplo = _intersecta(_livres(palavras_esq, t0, t1),
                            _livres(palavras_dir, t0, t1))
        duplo = [(z - a, -abs((a + z) / 2 - centro), (a + z) / 2, z - a)
                 for a, z in duplo if z - a >= MIN_GAP]
        if duplo:
            dur, _, t, _ = max(duplo)
            return {"t": round(t, 3), "silencio_s": round(dur, 3),
                    "metodo": "gap-asr", "suspeita": False}

    return {"t": round(b + overlap / 2.0, 3), "silencio_s": 0.0,
            "metodo": "meio", "suspeita": True}


# ── a costura em si ─────────────────────────────────────────────────────────
def costurar(esq, dir_, T):
    """Emenda `dir_` em `esq` no instante T. Devolve (doc, t_dir, atravessou).

    Regra de palavra que atravessa T (só acontece com metodo != "vale"): ela fica
    com o lado que a contém inteira — a esquerda, cujo chunk cobre até
    b+overlap — e o corte da direita anda para o fim dessa palavra. É o mesmo
    princípio que o ref-A aplica a token sem timestamp
    (`tools/referencias/ref-A/helpers/transcribe.py:143-146`): herda a fronteira
    vizinha em vez de sumir. Palavra NUNCA desaparece.
    """
    ae, ad = alt_de(esq), alt_de(dir_)
    we = [w for w in (ae.get("words") or []) if w["start"] < T]
    atravessou = [w for w in we if w["end"] > T]
    t_dir = max([T] + [w["end"] for w in atravessou])
    wd = [w for w in (ad.get("words") or []) if w["start"] >= t_dir]

    ae["words"] = we + wd

    def corta_pars(alt, lo, hi):
        out = []
        for par in (alt.get("paragraphs") or {}).get("paragraphs") or []:
            ss = [s for s in par.get("sentences", []) if lo <= s["start"] < hi]
            if not ss:
                continue
            p = dict(par)
            p["sentences"] = ss
            p["start"], p["end"] = ss[0]["start"], ss[-1]["end"]
            out.append(p)
        return out

    pe = corta_pars(ae, float("-inf"), T)
    pd = corta_pars(ad, t_dir, float("inf"))
    ae.setdefault("paragraphs", {})["paragraphs"] = pe + pd

    def corta_utts(j, lo, hi):
        out = []
        for u in j["results"].get("utterances") or []:
            ws = [w for w in (u.get("words") or []) if lo <= w["start"] < hi]
            if not ws:
                continue
            v = dict(u)
            v["words"] = ws
            v["start"], v["end"] = ws[0]["start"], ws[-1]["end"]
            v["transcript"] = " ".join(w.get("punctuated_word") or w["word"]
                                       for w in ws)
            out.append(v)
        return out

    esq["results"]["utterances"] = (corta_utts(esq, float("-inf"), T)
                                    + corta_utts(dir_, t_dir, float("inf")))
    return esq, t_dir, len(atravessou)


def reconstruir_texto(alt):
    """Texto SEMPRE reconstruído das sentenças — nunca por concatenar as strings
    das partes (que traria a zona de overlap duplicada de volta)."""
    pars = (alt.get("paragraphs") or {}).get("paragraphs") or []
    blocos = [" ".join(s["text"] for s in p.get("sentences", [])) for p in pars]
    blocos = [b for b in blocos if b.strip()]
    if blocos:
        alt.setdefault("paragraphs", {})["transcript"] = "\n\n".join(blocos)
        alt["transcript"] = " ".join(blocos)
    else:
        alt["transcript"] = " ".join(w.get("punctuated_word") or w["word"]
                                     for w in (alt.get("words") or []))
        alt.setdefault("paragraphs", {})["transcript"] = alt["transcript"]


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__.split("Uso:")[1].split("⚠️")[0].strip(), file=sys.stderr)
        return 2
    d = argv[0]
    args = argv[1:]

    def opt(n, dv, tipo=str):
        return tipo(args[args.index(n) + 1]) if n in args else dv

    out = opt("--out", d)
    global GUARDA
    GUARDA = float(opt("--guarda", GUARDA))
    pdir = os.path.join(d, ".partes")
    if not os.path.isdir(pdir):
        print(f"ERRO: não achei {pdir}", file=sys.stderr)
        return 2

    audio = opt("--audio", None)
    if audio is None:
        for c in CANDIDATOS_AUDIO:
            p = os.path.join(d, c)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                audio = p
                break
    if not audio:
        print(f"ERRO: não achei áudio em {d} (use --audio)", file=sys.stderr)
        return 2

    fatias = []
    for nome in sorted(os.listdir(pdir)):
        f = os.path.join(pdir, nome, "fatia.json")
        t = os.path.join(pdir, nome, "transcript.json")
        if os.path.isfile(f) and os.path.isfile(t):
            fa = json.load(open(f))
            fa["_t"] = t
            fatias.append(fa)
    fatias.sort(key=lambda x: x["i"])
    if not fatias:
        print(f"ERRO: nenhuma parte completa em {pdir}", file=sys.stderr)
        return 2

    dur_arquivo = ffprobe_dur(audio)
    overlap = float(fatias[0].get("overlap_s") or 0)
    parte_s = float(fatias[0].get("parte_s") or 0)

    docs, partes_meta = [], []
    for fa in fatias:
        j = json.load(open(fa["_t"]))
        crua = alt_de(j)
        partes_meta.append({
            "i": fa["i"],
            "inicio": round(fa["inicio"], 3),
            "fim": round(fa["inicio"] + (fa.get("duracao_arquivo_s") or 0), 3),
            "duracao_arquivo_s": fa.get("duracao_arquivo_s"),
            # ⚠️ o número DECLARADO PELO ENGINE para este chunk, preservado antes
            # de qualquer sobrescrita. É esta metade do par que quebra a
            # circularidade da checagem antiga.
            "duracao_declarada_s": (j.get("metadata") or {}).get("duration"),
            "palavras": len(crua.get("words") or []),
        })
        docs.append(desloca(j, float(fa["inicio"])))

    db = piso = None
    if len(docs) > 1:
        db = envelope(audio)
        piso = piso_adaptativo(db)

    base = docs[0]
    conf = [( (alt_de(docs[0]).get("confidence") or 0.0),
              len(alt_de(docs[0]).get("words") or []) )]
    costuras = []
    for k in range(1, len(docs)):
        b = float(fatias[k]["inicio"])
        c = escolher_costura(db, piso, b, overlap,
                             alt_de(base).get("words") or [],
                             alt_de(docs[k]).get("words") or [])
        n_esq = len(alt_de(base).get("words") or [])
        base, t_dir, atrav = costurar(base, docs[k], c["t"])
        c.update({"i": k - 1, "palavras_esq": n_esq,
                  "palavras_dir": len(alt_de(docs[k]).get("words") or []),
                  "atravessando": atrav})
        if atrav:
            print(f">> costura {k-1}: {atrav} palavra(s) atravessando T="
                  f"{c['t']:.2f}s ficaram com a esquerda (metodo={c['metodo']})",
                  file=sys.stderr)
        costuras.append(c)
        conf.append(((alt_de(docs[k]).get("confidence") or 0.0),
                     len(alt_de(docs[k]).get("words") or [])))

    alt = alt_de(base)
    reconstruir_texto(alt)
    tot = sum(n for _, n in conf) or 1
    alt["confidence"] = round(sum(c * n for c, n in conf) / tot, 6)

    dec_total = max((p["inicio"] + (p["duracao_declarada_s"] or 0))
                    for p in partes_meta)
    meta = base.setdefault("metadata", {})
    mid = (meta.get("models") or [None])[0]
    nome = ((meta.get("model_info") or {}).get(mid) or {}).get("name") or mid or "?"
    meta["duration"] = dur_arquivo          # continua sendo a duração REAL
    meta["_partes"] = len(partes_meta)      # alias, para leitor antigo
    meta["benchmark_transcribe"] = {
        "contrato": CONTRATO,
        "modo": "longo",
        "engine": f"deepgram/{nome}",
        "duracao_arquivo_s": dur_arquivo,
        "duracao_declarada_s": round(dec_total, 3),
        "parte_s": parte_s,
        "overlap_s": overlap,
        "partes": partes_meta,
        "costuras": costuras,
    }

    os.makedirs(out, exist_ok=True)
    tj = os.path.join(out, "transcript.json")
    with open(tj + ".part", "w") as fh:
        json.dump(base, fh, ensure_ascii=False)
    os.replace(tj + ".part", tj)

    with open(os.path.join(out, "transcript.md"), "w") as fh:
        fh.write(f"# Transcrição\n\n- Duração: {dur_arquivo:.0f}s\n"
                 f"- Partes: {len(partes_meta)}\n\n## Texto completo\n\n")
        for par in (alt.get("paragraphs") or {}).get("paragraphs") or []:
            fh.write(" ".join(s["text"] for s in par.get("sentences", [])) + "\n\n")

    print(f">> remontado: {len(alt.get('words') or [])} palavras · "
          f"{len(costuras)} costura(s) · "
          f"metodos={[c['metodo'] for c in costuras]}", file=sys.stderr)
    print(tj)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
