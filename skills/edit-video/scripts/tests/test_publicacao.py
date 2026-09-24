#!/usr/bin/env python3
"""Teste dos entregáveis de publicação (SPEC-21) — autocontido: sem mídia, sem API.

    python3 .claude/skills/edit-video/scripts/tests/test_publicacao.py
    python3 .../test_publicacao.py --dir-real <cópia de uma produção>

Sem `--dir-real` roda só o sintético: um `timeline_real` fabricado (a 25 e a 30
fps, e um de 3.900 s para o formato `H:MM:SS`) e um transcript Deepgram mínimo.
Com `--dir-real` acrescenta os critérios 1, 2 e 4 do §7 sobre material medido —
⚠️ **sempre em CÓPIA**, nunca em `creators/**`.

🔴 POR QUE ELE PLANTA DEFEITO EM VEZ DE SÓ AFIRMAR O CASO BOM
Um portão que varre 0 e sai 0 é indistinguível de um quebrado, e este repo já
entregou 6,25 s de vídeo errado com todos os QCs verdes. Então cada checagem faz
duas coisas: afirma o caso bom com o número medido e planta o defeito que o
mecanismo TEM que acusar — cue deslocado, timeline apagada, capítulo curto demais,
stamp arredondado para cima, transcript de fonte ausente.

Nada aqui toca material de creator: as palavras sintéticas são texto inventado.
"""
import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
import capitulos as C     # noqa: E402
import edl_io             # noqa: E402
import palavras as P      # noqa: E402
import srt as S           # noqa: E402

falhas, varrido = [], {}


def ok(nome, cond, detalhe):
    print("  [%s] %s — %s" % ("PASSOU" if cond else "FALHOU", nome, detalhe))
    if not cond:
        falhas.append(nome)
    return cond


def conta(k, n):
    varrido[k] = varrido.get(k, 0) + n


# ───────────────────────────────────────────────────────── material sintético

FRASES = [
    # (texto, dur_por_palavra_s, pausa_depois_s) — comprimentos controlados
    ("A primeira frase é curta.", 0.30, 0.90),
    ("Esta segunda frase tem bastante texto para estourar o orçamento de "
     "caracteres de duas linhas e obrigar o agrupador a fechar o cue antes da "
     "pontuação.", 0.26, 0.80),
    ("Agora vem uma frase falada muito rápido mesmo.", 0.10, 0.05),
    ("E o fim.", 0.40, 0.0),
]


def fabricar_transcript(destino, t0=0.0):
    """Deepgram mínimo: results.channels[0].alternatives[0].words[]."""
    ws, t = [], t0
    for texto, dur, pausa in FRASES:
        for tok in texto.split():
            ws.append({"word": tok.strip(".,!?").lower(), "punctuated_word": tok,
                       "start": round(t, 4), "end": round(t + dur, 4),
                       "confidence": 0.97, "language": "pt"})
            t += dur
        t += pausa
    doc = {"metadata": {"duration": round(t, 3)},
           "results": {"channels": [{"alternatives": [{"words": ws}]}]}}
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    return ws, t


def fabricar(base, fps, *, cortes=2, contiguo=False, total_s=None):
    """<dir> com edl.json (v1) + timeline-real.json sintética + take-A/transcript.json.

    `contiguo=True` faz o segundo segmento COLAR no primeiro no bruto — é a divisão
    em planos do `dividir-planos.py`, que NÃO pode quebrar cue."""
    d = os.path.join(base, "prod-%d%s" % (fps, "-cont" if contiguo else ""))
    os.makedirs(os.path.join(d, "take-A"), exist_ok=True)
    ws, dur_total = fabricar_transcript(os.path.join(d, "take-A", "transcript.json"))
    # corta o bruto em `cortes+1` pedaços; sem `contiguo`, com um buraco entre eles
    bordas = [0.0]
    passo = dur_total / (cortes + 1)
    for k in range(1, cortes + 1):
        bordas.append(round(k * passo, 3))
    bordas.append(round(dur_total + 0.2, 3))
    segs, tl_segs, acc_f = [], [], 0
    sr = 48000
    for k in range(len(bordas) - 1):
        s0 = bordas[k] if (contiguo or k == 0) else bordas[k] + 0.25
        s1 = bordas[k + 1]
        segs.append({"src": "take-A.MOV", "start": round(s0, 3), "end": round(s1, 3),
                     "fala": "", "beat": "b%d" % k})
        nf = max(1, int(round((s1 - s0) * fps)))
        tl_segs.append({"i": k, "beat": "b%d" % k, "src": "take-A.MOV",
                        "src_start": round(s0, 3), "src_end": round(s1, 3),
                        "frames": nf, "start_frame": acc_f,
                        "start_s": round(acc_f / fps, 6), "dur_s": round(nf / fps, 6),
                        "start_sample": acc_f * (sr // fps), "samples": nf * (sr // fps)})
        acc_f += nf
    with open(os.path.join(d, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump(segs, fh, ensure_ascii=False, indent=1)
    tot_f = acc_f
    tl = {"schema": edl_io.SCHEMA_TL, "gerado_por": "test_publicacao.py",
          "gerado_em": "2026-08-08T00:00:00-03:00",
          "edl_fingerprint": edl_io.fingerprint(segs),
          "video": {"width": 640, "height": 360, "fps": float(fps),
                    "fps_num": fps, "fps_den": 1},
          "sample_rate": sr, "samples_por_frame": sr // fps,
          "total_frames": tot_f, "total_s": round(tot_f / fps, 6),
          "total_samples": tot_f * (sr // fps), "segments": tl_segs}
    if total_s is not None:            # estica o último segmento (formato ≥ 1 h)
        extra = int(round(total_s * fps)) - tot_f
        tl["segments"][-1]["frames"] += extra
        tl["segments"][-1]["dur_s"] = round(tl["segments"][-1]["frames"] / fps, 6)
        tl["segments"][-1]["samples"] = tl["segments"][-1]["frames"] * (sr // fps)
        tl["total_frames"] += extra
        tl["total_s"] = round(tl["total_frames"] / fps, 6)
        tl["total_samples"] = tl["total_frames"] * (sr // fps)
    edl_io.conferir_invariantes(tl)
    with open(os.path.join(d, "timeline-real.json"), "w", encoding="utf-8") as fh:
        json.dump(tl, fh, ensure_ascii=False, indent=1)
    return d, tl


# ────────────────────────────────────────────────────────────────── os casos

def caso_mapa(base):
    print("\n── o mapa: palavras do bruto em tempo de saída, a 25 e a 30 fps")
    for fps in (25, 30):
        d, tl = fabricar(base, fps)
        ws, info = P.palavras_no_montado(d)
        conta("palavras mapeadas", len(ws))
        dentro = all(-1e-6 <= w["ini"] and w["fim"] <= tl["total_s"] + 1e-6 for w in ws)
        ok("mapa/%dfps dentro de [0,total]" % fps, dentro,
           "%d palavras, última em %.3f s de %.3f s"
           % (len(ws), ws[-1]["fim"], tl["total_s"]))
        # monotônico e sem palavra duplicada na emenda (seleção por "começa dentro")
        mono = all(a["ini"] <= b["ini"] for a, b in zip(ws, ws[1:]))
        textos = [w["texto"] for w in ws]
        dupe = [t for i, t in enumerate(textos[:-1])
                if t == textos[i + 1] and ws[i]["i_seg"] != ws[i + 1]["i_seg"]]
        ok("mapa/%dfps sem duplicata na emenda" % fps, mono and not dupe,
           "monotônico=%s duplicatas=%s" % (mono, dupe or 0))
        # ⚠️ defeito plantado: soma nominal Σ(end−start) tem que DIVERGIR do real
        segs = edl_io.segmentos(d)
        nominal = sum(float(s["end"]) - float(s["start"]) for s in segs)
        ok("mapa/%dfps Σ(end−start) ≠ timeline real" % fps,
           abs(nominal - tl["total_s"]) > 1e-6,
           "nominal %.4f s vs real %.4f s (Δ %.1f ms)"
           % (nominal, tl["total_s"], (tl["total_s"] - nominal) * 1000))


def caso_sem_timeline(base):
    print("\n── critério 3: sem timeline_real não sai arquivo")
    d, _ = fabricar(base, 30)
    os.remove(os.path.join(d, "timeline-real.json"))
    saiu = []
    for nome, fn in (("palavras.py", P.palavras_no_montado),):
        try:
            fn(d)
            saiu.append(nome)
        except SystemExit:
            pass
    for nome, mod in (("srt.py", S), ("capitulos.py", C)):
        rc = 0
        try:
            rc = mod._cli([d])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        if rc == 0:
            saiu.append(nome)
    escritos = [f for f in ("captions.srt", "chapters.txt")
                if os.path.exists(os.path.join(d, f))]
    conta("dirs sem timeline testados", 1)
    ok("critério 3", not saiu and not escritos,
       "scripts que NÃO abortaram: %s · arquivos escritos: %s"
       % (saiu or "nenhum", escritos or "nenhum"))


def caso_agrupamento(base):
    print("\n── §3.3: as 5 regras de quebra, a régua de CPS e a de duração mínima")
    d, tl = fabricar(base, 30)
    ws, info = P.palavras_no_montado(d)
    regra = dict(P.PADRAO_PUBLICACAO["srt"])
    gap = regra["gap_entre_cues_frames"] / tl["video"]["fps"]
    cues = S.agrupar(ws, regra, info["descontinuidades"])
    conta("cues sintéticos", len(cues))
    # regra 4: nenhuma linha passa do orçamento
    longas = [l for c in cues for l in c["linhas"] if len(l) > regra["max_chars_linha"]]
    muitas = [c for c in cues if len(c["linhas"]) > regra["linhas"]]
    ok("agrupamento/orçamento", not longas and not muitas,
       "%d cues, maior linha %d chars (teto %d), máx %d linhas"
       % (len(cues), max((len(l) for c in cues for l in c["linhas"]), default=0),
          regra["max_chars_linha"], max((len(c["linhas"]) for c in cues), default=0)))
    # regra 2: todo cue que NÃO é o último termina em pontuação, gap, ou orçamento
    cues = S.passe_cps(cues, regra, gap, tl["total_s"])
    cues = S.passe_dur_min(cues, regra, gap, tl["total_s"])
    clamp, _, _ = S.passe_sobreposicao(cues, gap, regra)
    cues = S.snap_ms(cues, gap, tl["total_s"])
    sobre = [k for k in range(len(cues) - 1)
             if cues[k]["fim"] > cues[k + 1]["ini"] - gap + 5e-4]
    ok("agrupamento/sem sobreposição", not sobre,
       "%d clamps aplicados, %d sobreposições residuais" % (clamp, len(sobre)))
    # 🔴 o início NUNCA é antecipado (a regra que o §9 proíbe quebrar)
    ini_orig = {}
    for c in cues:
        ini_orig[c["palavras"][0]["texto"]] = c["palavras"][0]["ini"]
    antecipados = [t for c in cues
                   for t in [c["palavras"][0]["texto"]]
                   if c["ini"] < c["palavras"][0]["ini"] - 5e-4]
    ok("agrupamento/início nunca antecipado", not antecipados,
       "%d cues conferidos, %d antecipados" % (len(cues), len(antecipados)))


def caso_contiguo(base):
    print("\n── §3.3 regra 1: plano CONTÍGUO não quebra cue (o dividir-planos.py)")
    d, tl = fabricar(base, 30, contiguo=True)
    ws, info = P.palavras_no_montado(d)
    ok("contiguidade detectada", info["descontinuidades"] == [True, False, False],
       "descontinuidades=%s (só o segmento 0 abre)" % info["descontinuidades"])
    regra = dict(P.PADRAO_PUBLICACAO["srt"])
    cues = S.agrupar(ws, regra, info["descontinuidades"])
    n_cont = len(cues)
    # controle: com os MESMOS cortes marcados como descontínuos, tem que quebrar MAIS
    cues2 = S.agrupar(ws, regra, [True] * len(tl["segments"]))
    conta("cues contíguo/descontínuo", n_cont + len(cues2))
    ok("contíguo gera MENOS cues que descontínuo", n_cont < len(cues2),
       "%d cues com plano contíguo vs %d se cada segmento quebrasse" % (n_cont, len(cues2)))


def caso_srt_arquivo(base):
    print("\n── §3.3: o arquivo (UTF-8 sem BOM, LF, newline final) e o --verificar")
    d, tl = fabricar(base, 30)
    rc = S._cli([d])
    p = os.path.join(d, "captions.srt")
    bruto = open(p, "rb").read()
    ok("formato do .srt", rc == 0 and not bruto.startswith(b"\xef\xbb\xbf")
       and b"\r" not in bruto and bruto.endswith(b"\n"),
       "exit=%d · BOM=%s · CR=%s · newline final=%s"
       % (rc, bruto.startswith(b"\xef\xbb\xbf"), b"\r" in bruto, bruto.endswith(b"\n")))
    ok("--verificar no arquivo bom", S._cli([d, "--verificar"]) == 0, "exit 0")
    # ⚠️ DEFEITO PLANTADO: desloca um cue 900 ms para frente
    linhas = open(p, encoding="utf-8").read().split("\n\n")
    alvo = 1 if len(linhas) > 2 else 0
    bl = linhas[alvo].split("\n")
    bl[1] = bl[1].replace("00:00:0", "00:00:9", 1) if "00:00:0" in bl[1] else bl[1]
    linhas[alvo] = "\n".join(bl)
    open(p, "w", encoding="utf-8").write("\n\n".join(linhas))
    rc_ruim = S._cli([d, "--verificar"])
    conta("cues verificados", len(S.ler_srt(p)))
    ok("--verificar ACUSA o cue deslocado", rc_ruim == 1,
       "exit=%d com o defeito plantado (tem que ser 1)" % rc_ruim)


def caso_capitulos(base):
    print("\n── §3.4: capítulos com regra dura, floor e título de abertura")
    d, tl = fabricar(base, 30, total_s=3900.0)
    total = tl["total_s"]
    bloco = dict(P.PADRAO_PUBLICACAO["capitulos"])

    # critério 7: formato ≥ 1 h e < 1 h
    ok("stamp ≥ 1 h", [C.stamp(0, 3900), C.stamp(3750, 3900)] == ["0:00:00", "1:02:30"],
       "0 e 3750 s em peça de 3900 s → 0:00:00 e 1:02:30")
    ok("stamp < 1 h", [C.stamp(0, 900), C.stamp(150, 900)] == ["0:00", "2:30"],
       "0 e 150 s em peça de 900 s → 0:00 e 2:30")
    # critério 6(b): floor, nunca round
    ok("floor no stamp (12,7 s → 0:12)", C.stamp(12.7, 900) == "0:12",
       "round daria 0:13 e o espectador perderia a primeira palavra")
    ok("floor dá 0:00 de graça (0,4 s)", C.stamp(0.4, 900) == "0:00", "t < 1 → 0:00")

    # critério 6(a): título de abertura, sem duplicar
    itens = [(30.0, "Primeiro de verdade", "t"), (50.0, "Segundo", "t"),
             (70.0, "Terceiro", "t")]
    linhas, prob, avisos = C.montar(itens, tl, bloco)
    tit = [t for _, t in linhas]
    conta("capítulos montados", len(linhas))
    ok("abertura inserida sem duplicar título",
       linhas[0][0] == "0:00:00" and tit[0] == bloco["titulo_abertura"]
       and len(tit) == len(set(tit)),
       "%s · duplicados=%s" % (tit, len(tit) != len(set(tit))))

    # critério 5: capítulo curto demais é ERRO
    curtos = [(0.4, "Abertura", "t"), (8.9, "X", "t"), (40.0, "Terceiro", "t")]
    _, prob_c, _ = C.montar(curtos, tl, bloco)
    ok("capítulo de 8 s reprova", any("mínimo" in p for p in prob_c),
       "problemas=%s" % prob_c)
    bons = [(0.4, "Abertura", "t"), (12.0, "X", "t"), (40.0, "Terceiro", "t")]
    _, prob_b, _ = C.montar(bons, tl, bloco)
    ok("movendo para 12 s aprova", not prob_b, "0 problemas")
    # menos de 3 capítulos reprova
    _, prob_2, _ = C.montar([(0.0, "A", "t"), (30.0, "B", "t")], tl, bloco)
    ok("2 capítulos reprovam", any("mínimo %d" % bloco["minimo"] in p for p in prob_2),
       "problemas=%s" % prob_2)

    # exit 2: gerar declarado e sem capítulo nenhum
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "perfil.json"), "w") as fh:
        json.dump(_perfil_minimo(True), fh)
    rc = C._cli([d])
    ok("gerar=true e zero capítulo → exit 2", rc == 2, "exit=%d" % rc)
    os.remove(os.path.join(d, "perfil.json"))


def _perfil_minimo(cap_on):
    """Perfil COMPLETO mínimo (o validador do perfil.py exige contrato/nome/video/audio/ritmo)."""
    import perfil as perfil_mod
    p = json.loads(json.dumps(perfil_mod.FALLBACK_REELS))
    p["publicacao"] = json.loads(json.dumps(P.PADRAO_PUBLICACAO))
    p["publicacao"]["capitulos"]["gerar"] = cap_on
    p["publicacao"]["srt"]["gerar"] = True
    return p


def caso_perfil(base):
    print("\n── §3.5: quem decide o conjunto de entregáveis é o PERFIL")
    d, _ = fabricar(base, 30)
    for liga in (False, True):
        p = _perfil_minimo(liga)
        p["publicacao"]["srt"]["gerar"] = liga
        with open(os.path.join(d, "perfil.json"), "w") as fh:
            json.dump(p, fh)
        for f in ("captions.srt", "captions.srt.meta.json"):
            if os.path.exists(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
        rc = S._cli([d])
        existe = os.path.exists(os.path.join(d, "captions.srt"))
        ok("srt.gerar=%s" % liga, rc == 0 and existe == liga,
           "exit=%d · arquivo=%s (mesmo código nos dois casos)" % (rc, existe))
    os.remove(os.path.join(d, "perfil.json"))


def caso_resolvedor(base):
    print("\n── §3.2.2: take sem transcript é ERRO com a linha pronta, não buraco")
    d, _ = fabricar(base, 30)
    shutil.rmtree(os.path.join(d, "take-A"))
    try:
        P.palavras_no_montado(d)
        achou = ""
    except P.ErroPalavras as e:
        achou = str(e)
    conta("resolvedores testados", 1)
    ok("erro fatal com linha pronta para colar",
       "--transcript" in achou and "take-A.MOV" in achou,
       achou.split("\n")[0] if achou else "NÃO LANÇOU (é o render.py:770 deles)")


# ───────────────────────────────────────────────────── material real (opcional)

def caso_real(d):
    print("\n── material real em %s (critérios 1, 2 e 4)" % d)
    import collections
    tl = edl_io.timeline(d)
    ws, info = P.palavras_no_montado(d, tl=tl)
    rc = S._cli([d])
    p = os.path.join(d, "captions.srt")
    cues = S.ler_srt(p)
    side = json.load(open(p + ".meta.json"))
    conta("palavras reais", len(ws))
    conta("cues reais", len(cues))
    a = collections.Counter(t for w in ws for t in w["texto"].split())
    b = collections.Counter(t for c in cues for t in c["texto"].split())
    dif = sum(((a - b) + (b - a)).values())
    ok("real/critério 1 zero palavra inventada", rc == 0 and dif == 0,
       "%d palavras mapeadas, %d tokens no .srt, diferença %d" % (len(ws), sum(b.values()), dif))
    segs = edl_io.segmentos(d)
    nominal = sum(float(s["end"]) - float(s["start"]) for s in segs)
    ok("real/critério 2 indexação real ≠ nominal", abs(tl["total_s"] - nominal) * 1000 > 100,
       "Σ(end−start)=%.4f s vs timeline=%.4f s → %.1f ms de atraso do nominal"
       % (nominal, tl["total_s"], (tl["total_s"] - nominal) * 1000))
    r = side["regra"]
    gap = r["gap_entre_cues_frames"] / side["fps"]
    sobre = [c for k, c in enumerate(cues[:-1]) if c["fim"] > cues[k + 1]["ini"] - gap + 5e-4]
    longas = [l for c in cues for l in c["linhas"] if len(l) > r["max_chars_linha"]]
    fora = [c for c in cues if c["ini"] < 0 or c["fim"] > side["total_s"] + 5e-4]
    cps = sorted(len(c["texto"]) / (c["fim"] - c["ini"]) for c in cues)
    p95 = cps[int(round(0.95 * (len(cps) - 1)))]
    ok("real/critério 4 estrutural", not (sobre or longas or fora),
       "%d sobreposições, %d linhas longas, %d fora do intervalo · cps_p95 %.2f "
       "(teto %.1f, excedidos declarados %d)"
       % (len(sobre), len(longas), len(fora), p95, r["cps_max"], side["cps_excedidos"]))


def main():
    real = None
    if "--dir-real" in sys.argv:
        real = sys.argv[sys.argv.index("--dir-real") + 1]
    base = tempfile.mkdtemp(prefix="spec21-")
    try:
        caso_mapa(base)
        caso_sem_timeline(base)
        caso_agrupamento(base)
        caso_contiguo(base)
        caso_srt_arquivo(base)
        caso_capitulos(base)
        caso_perfil(base)
        caso_resolvedor(base)
        if real:
            caso_real(real)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-40s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas else "FALHOU: " + ", ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
