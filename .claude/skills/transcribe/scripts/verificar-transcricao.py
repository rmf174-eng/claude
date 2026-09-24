#!/usr/bin/env python3
"""verificar-transcricao — quatro checagens sobre um transcript, NENHUMA circular.

O DEFEITO QUE ISTO SUBSTITUI
----------------------------
A checagem antiga (`transcribe-longo.sh:95` + `:108-116`, e a cópia dela em
no ingest de call) comparava `metadata.duration` com o
ffprobe do arquivo — DEPOIS de ter gravado o ffprobe do arquivo dentro de
`metadata.duration`. A conta era `abs(x-x)/x < 0.02`: sempre 0, sempre OK.
Impressão digital medida em 172 transcripts do repo: `ffprobe − metadata.duration`
fica entre −0,105 s e −0,045 s em todos, MENOS em `data/adhoc/aula-longa-02`
(o único produzido pelo `transcribe-longo.sh`), onde dá exatamente +0,000 s.

O PRINCÍPIO
-----------
"Detector de achado ≠ teste de convergência — a aprovação precisa de referência
independente" (registrado no teardown que fica fora deste repositório).
Aqui a referência independente é o **áudio**, não o número que o engine declarou.

    C1  cobertura declarada   ffprobe do arquivo × duração DECLARADA pelo engine
    C2  cobertura acústica    regiões de fala do envelope × palavras do transcript
    C3  costuras              cada emenda caiu em silêncio e nenhuma palavra a cruza
    C4  monotonicidade        words[i].start >= words[i-1].start

C1 e C2 são independentes DE PROPÓSITO: C1 pega o truncamento que o engine
confessa no `metadata`; C2 pega o que ele não confessa (bloco pulado no meio,
parte que voltou vazia, e também o truncamento). ⚠️ Nunca "calibre" C2 pelo que
C1 já aprovou — é o que mata a proteção.

Uso:
  verificar-transcricao.py <dir|transcript.json>
      [--audio PATH] [--rapido] [--estrito] [--nao-gravar]
      [--tolerancia-s 1.0] [--lacuna-max 20] [--retrocesso-max-s 1.0] [--json]

Saída: veredito em uma linha no stderr; caminho do transcript no stdout
(convenção do repo) ou o relatório JSON no stdout com --json.
Exit: 0 ok (pode ter avisos) · 1 falha dura · 2 erro de uso.

Env: BENCH_TRANSCRIBE_LACUNA_MAX  (default do --lacuna-max)
"""
import bisect
import datetime
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

CONTRATO = "benchmark.transcribe/v1"
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


def palavras(j):
    try:
        alt = j["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError, TypeError):
        return []
    return [w for w in (alt.get("words") or [])
            if isinstance(w.get("start"), (int, float))]


# ── as quatro checagens ─────────────────────────────────────────────────────
def c1_cobertura_declarada(j, bt, audio, tol):
    """ffprobe do arquivo − duração DECLARADA pelo engine. Falha se > tol."""
    itens, aviso = [], None
    if bt and bt.get("partes"):
        for p in bt["partes"]:
            arq, dec = p.get("duracao_arquivo_s"), p.get("duracao_declarada_s")
            if arq is None or dec is None:
                continue
            itens.append((f"parte {p.get('i')}", arq - dec))
        dec_total = bt.get("duracao_declarada_s")
        arq_total = ffprobe_dur(audio) if audio else bt.get("duracao_arquivo_s")
        if dec_total is not None and arq_total is not None:
            itens.append(("total", arq_total - dec_total))
    else:
        # modo legado: no passe único `metadata.duration` VEM do engine, então a
        # comparação com o ffprobe é legítima (é só no caminho longo que ela era
        # circular, porque o script sobrescrevia o campo antes de conferir).
        dec = (j.get("metadata") or {}).get("duration")
        arq = ffprobe_dur(audio) if audio else None
        if dec is None:
            aviso = "C1 pulada: metadata.duration ausente"
        elif arq is None:
            aviso = "C1 pulada: sem áudio ao lado para comparar"
        else:
            itens.append(("total", arq - dec))
    if not itens:
        return None, [], ([aviso] if aviso else ["C1 pulada: sem número comparável"])
    pior = max(itens, key=lambda x: x[1])
    falhas = [f"C1 {nome}: engine declarou {d:.3f}s A MENOS que o arquivo "
              f"(tolerância {tol}s)" for nome, d in itens if d > tol]
    return round(pior[1], 3), falhas, ([aviso] if aviso else [])


def c2_cobertura_acustica(ws, audio, limite):
    """Maior REGIÃO DE FALA do envelope sem nenhuma palavra do transcript."""
    from envelope import envelope, piso_adaptativo, regioes_de_fala
    db = envelope(audio)
    if len(db) == 0:
        return None, None, [], ["C2 pulada: áudio não decodificou"]
    piso = piso_adaptativo(db)
    regs = regioes_de_fala(db, piso)
    ini = sorted(w["start"] for w in ws)
    fim_max = []
    acc = float("-inf")
    for w in sorted(ws, key=lambda w: w["start"]):
        acc = max(acc, float(w["end"]))
        fim_max.append(acc)
    pior_d, pior_reg = 0.0, None
    for a, b in regs:
        k = bisect.bisect_left(ini, b)
        tem = k > 0 and fim_max[k - 1] > a          # alguma palavra intersecta [a,b]
        if not tem and (b - a) > pior_d:
            pior_d, pior_reg = b - a, [round(a, 1), round(b, 1)]
    falhas = ([f"C2: {pior_d:.1f}s de fala sem nenhuma palavra em {pior_reg} "
               f"(limite {limite}s)"] if pior_d > limite else [])
    return round(pior_d, 1), pior_reg, falhas, []


def c3_costuras(bt, ws, audio, estrito):
    """Cada T registrada caiu em silêncio >= 0,20s e nenhuma palavra a atravessa."""
    from envelope import envelope, piso_adaptativo, vales
    cost = (bt or {}).get("costuras") or []
    if not cost:
        return 0, [], []
    db = envelope(audio)
    piso = piso_adaptativo(db)
    ruins = []
    for c in cost:
        t = c.get("t")
        if t is None:
            continue
        motivo = []
        if c.get("suspeita"):
            motivo.append(f"metodo={c.get('metodo')}")
        if any(w["start"] < t < w["end"] for w in ws):
            motivo.append("palavra atravessa T")
        if not any(a <= t <= b for a, b in
                   vales(db, max(0.0, t - 1.5), t + 1.5, piso, minimo=0.20)):
            motivo.append("T não caiu em silêncio >= 0,20s")
        if motivo:
            ruins.append(f"C3 costura t={t:.2f}s: {'; '.join(motivo)}")
    msg = ruins
    return len(ruins), (msg if estrito else []), ([] if estrito else msg)


def c4_monotonicidade(ws, limite):
    """words[i].start >= words[i-1].start. Conta TODOS; reprova por MAGNITUDE.

    ⚠️ MEDIDO EM 2026-08-08, e é uma divergência da SPEC-01 §7.7, que afirmava
    "o corpus atual já tem 0 retrocessos". Ele tem **8 em 171 arquivos**, e são de
    duas naturezas distintas:

      • 6 micro (0,005 – 0,165 s) — palavra que o smart_format sobrepõe à seguinte
        ("porque"/"porque" em `meta-ref-E/vsl/pg-f100kd-vimeo`);
      • 2 grandes (6,960 s e 10,400 s) — palavra SOLTA com timestamp absurdo
        (`'em'` a 99,24 s no meio de uma corrida a 88,6 s, em
        `profiles/instagram-larissatopper/posts/Da8gvTTAXei`; `'c'` a 14,0 s numa
        corrida a 6,3 s, em `advertisers/meta-hust-sekey/criativos/t-eisekey-10`).

    Todos são glitch do ASR em transcript de PASSE ÚNICO — nenhum passou por
    emenda. Reprovar "qualquer retrocesso" transformaria a proteção em ruído de
    4,7% do corpus, e ruído é o que faz gente exportar
    BENCH_TRANSCRIBE_SEM_VERIFICAR=1 e matar a checagem inteira.

    O limiar é de MAGNITUDE porque é ela que separa os dois mundos: o defeito que
    C4 existe para pegar (parte emendada fora de ordem, ou offset não aplicado)
    devolve um retrocesso da ordem do OVERLAP — 30 s no default, e nunca menos que
    alguns segundos. O default de 1,0 s fica 6× acima do maior micro-glitch medido
    e 30× abaixo do overlap default. Os dois casos grandes reprovam, e está certo:
    são dado ruim de verdade, achados por esta checagem.
    """
    pior, n = 0.0, 0
    for i in range(1, len(ws)):
        d = ws[i - 1]["start"] - ws[i]["start"]
        if d > 0:
            n += 1
            pior = max(pior, d)
    falhas = ([f"C4: retrocesso de {pior:.3f}s no start das palavras "
               f"(limite {limite}s) — emenda fora de ordem ou offset errado"]
              if pior > limite else [])
    return n, round(pior, 3), falhas


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__.split("Uso:")[1].split("Saída:")[0].strip(), file=sys.stderr)
        return 2
    alvo = argv[0]
    args = argv[1:]

    def flag(n):
        return n in args

    def opt(n, d, tipo=float):
        return tipo(args[args.index(n) + 1]) if n in args else d

    if os.path.isdir(alvo):
        d, tpath = alvo, os.path.join(alvo, "transcript.json")
    else:
        d, tpath = os.path.dirname(os.path.abspath(alvo)) or ".", alvo
    if not os.path.isfile(tpath):
        print(f"ERRO: não achei {tpath}", file=sys.stderr)
        return 2

    audio = opt("--audio", None, str)
    if audio is None:
        for c in CANDIDATOS_AUDIO:
            p = os.path.join(d, c)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                audio = p
                break
    rapido, estrito = flag("--rapido"), flag("--estrito")
    tol = opt("--tolerancia-s", 1.0)
    lim = opt("--lacuna-max", float(os.environ.get("BENCH_TRANSCRIBE_LACUNA_MAX", 20)))
    ret_max = opt("--retrocesso-max-s", 1.0)

    j = json.load(open(tpath))
    bt = (j.get("metadata") or {}).get("benchmark_transcribe")
    legado = not (bt and bt.get("partes"))
    ws = palavras(j)

    falhas, avisos = [], []
    rel = {
        "em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "modo": "rapido" if rapido else "completo",
        "legado": legado,
        "palavras": len(ws),
    }

    c1, f, a = c1_cobertura_declarada(j, bt, audio, tol)
    rel["c1_delta_max_s"] = c1
    falhas += f
    avisos += a

    if rapido:
        rel["c2_lacuna_max_s"] = None
        rel["c2_lacuna_em"] = None
        rel["c3_costuras_suspeitas"] = None
    elif not audio:
        rel["c2_lacuna_max_s"] = None
        rel["c2_lacuna_em"] = None
        rel["c3_costuras_suspeitas"] = None
        avisos.append("C2/C3 puladas: sem áudio ao lado")
    else:
        if not ws:
            falhas.append("C2: transcript sem nenhuma palavra")
        lac, onde, f, a = c2_cobertura_acustica(ws, audio, lim)
        rel["c2_lacuna_max_s"], rel["c2_lacuna_em"] = lac, onde
        falhas += f
        avisos += a
        n3, f, a = c3_costuras(bt, ws, audio, estrito)
        rel["c3_costuras_suspeitas"] = n3
        falhas += f
        avisos += a

    n4, pior4, f = c4_monotonicidade(ws, ret_max)
    rel["c4_retrocessos"] = n4
    rel["c4_retrocesso_max_s"] = pior4
    falhas += f

    rel["veredito"] = "falha" if falhas else ("ok-com-aviso" if avisos else "ok")
    rel["falhas"], rel["avisos"] = falhas, avisos

    if not flag("--nao-gravar"):
        meta = j.setdefault("metadata", {})
        blk = meta.setdefault("benchmark_transcribe", {
            "contrato": CONTRATO, "modo": "legado", "legado": True})
        blk["verificacao"] = rel
        tmp = tpath + ".part"
        with open(tmp, "w") as fh:
            json.dump(j, fh, ensure_ascii=False)
        os.replace(tmp, tpath)

    c2s = "n/a" if rel["c2_lacuna_max_s"] is None else f"{rel['c2_lacuna_max_s']}s"
    print(f">> {rel['veredito'].upper()} · {len(ws)} palavras · "
          f"C1 {rel['c1_delta_max_s']}s · C2 {c2s} · "
          f"C3 {rel['c3_costuras_suspeitas']} · "
          f"C4 {rel['c4_retrocessos']}/{rel['c4_retrocesso_max_s']}s"
          + ("" if not legado else " · legado"), file=sys.stderr)
    for m in falhas + avisos:
        print(f"   {m}", file=sys.stderr)

    print(json.dumps(rel, ensure_ascii=False) if flag("--json") else tpath)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
