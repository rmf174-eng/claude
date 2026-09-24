#!/usr/bin/env python3
"""palavras.py — as palavras do BRUTO, posicionadas na SAÍDA (SPEC-21).

É o mapa que as três `legendas.py` de produção implementavam à mão, agora uma vez
só, na skill, lendo a `timeline_real` da SPEC-05. Todo entregável de texto desta
skill (`srt.py`, `capitulos.py`) passa por aqui.

Uso como módulo (é o normal):

    import palavras
    ws = palavras.palavras_no_montado(dir_producao)
    # [{i_seg, src, texto, texto_cru, ini, fim, conf}]  em tempo de SAÍDA

Uso como CLI (debug / reuso por outro script):

    palavras.py <dir> [--transcript "src=path"]... [--transcritos map.json]
                      [--ortografia f.json] [--alinhamento alignment.json] [--json]

────────────────────────────────────────────────────────────────────────────
AS DUAS REGRAS QUE ESTE ARQUIVO EXISTE PARA NÃO QUEBRAR

(a) AS PALAVRAS VÊM DO BRUTO, NUNCA DO MONTADO. O ASR lê a emenda como fala
    contínua e INVENTA palavra para fazer sentido: a legenda entregue dizia
    "Você manda as empresas com o seu sócio" onde o creator-3 fala "uma das empresas
    que eu sou sócio" (SKILL.md, etapa 2). As palavras certas sempre existiram no
    transcript do bruto, onde o reconhecedor tinha contexto dos dois lados do
    corte. `fonte_palavras: "transcript-montado"` NÃO é um valor aceito aqui.

(b) A POSIÇÃO SAI DA `timeline_real`, NUNCA DE Σ(end−start). A soma nominal das
    ranges da EDL é sempre MENOR que a saída real — o render arredonda para
    frame e o erro acumula sempre no mesmo sentido. Medido: 351,7 ms no fim de
    `peca-10-27-07/c-completo`, 353 ms em `creator-2/peca-03`. Com J-cut o erro vira
    o do ref-A: 4,433 s num caso de 20 takes. Aqui não existe fallback — sem
    `timeline_real` o script ABORTA. Preferimos não entregar o arquivo a entregar
    um arquivo deslocado, porque o deslocamento é o defeito que ninguém percebe:
    áudio perfeito, cor certa, emendas limpas, e o texto meio segundo fora.

(c) INDEXAR PELO ÁUDIO, NÃO PELO VÍDEO. Legenda acompanha fala. Sem J-cut,
    `audio_offset` == `video_offset` e a distinção não aparece; com J-cut
    (SPEC-07) o áudio de um take entra ANTES da imagem dele, e indexar pelo vídeo
    poria todo cue daquele take `lead` atrasado. O `.get("audio_offset_samples",
    ...)` funciona nos dois mundos sem `if`.
"""
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io   # noqa: E402

SCHEMA = "benchmark.palavras-saida/v1"
CASAS = 6


class ErroPalavras(Exception):
    pass


class ErroPublicacao(Exception):
    pass


# ─────────────────────────────────────── o bloco `publicacao` do perfil de peça
#
# 🔒 DEFAULT EMBUTIDO, para produção sem `perfil.json` (histórica, ou anterior à
# SPEC-00). Ela RODA — só não dá para desligar por perfil. Os números são os
# mesmos da tabela da SPEC-21 §3.5, e nenhum deles é medição nossa: 42 chars × 2
# linhas, quebra em pontuação e gap de 0,7 s vêm das réguas de broadcast do
# ref-A; `cps_max 17`, `dur_min 0,833 s` e `dur_max 7 s` são convenção de
# mercado de legendagem em pt-BR, adotada como default REVISÁVEL no perfil.
#
# `capitulos.gerar = None` quer dizer AUTO: liga se houver ao menos um capítulo
# declarado. É só o caso "sem perfil.json" — os 4 perfis do catálogo declaram
# `true`/`false` explicitamente.
PADRAO_PUBLICACAO = {
    "srt": {
        "gerar": True, "arquivo": "captions.srt", "formatos": ["srt"],
        "max_chars_linha": 42, "linhas": 2, "cps_max": 17.0,
        "dur_min_s": 0.833, "dur_max_s": 7.0,
        "gap_quebra_s": 0.7, "gap_entre_cues_frames": 2,
        "caixa": "original", "fonte_palavras": "edl-bruto",
    },
    "capitulos": {
        "gerar": None, "arquivo": "chapters.txt",
        "minimo": 3, "dur_min_s": 10.0,
        "titulo_abertura": "Introdução", "max_chars_titulo": 100,
    },
}


def _fundir(base, novo):
    out = dict(base)
    for k, v in (novo or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _fundir(out[k], v)
        else:
            out[k] = v
    return out


def publicacao(d, *, ignorar_perfil=False, quieto=True):
    """(bloco `publicacao` efetivo, nome do perfil). Nunca lança por falta de perfil.

    ⚠️ O bloco `publicacao` NÃO está em `CREATOR_PODE` (perfil.py:132), então
    `creators/<n>/perfil-overrides.json` não pode ligá-lo: quem liga é o perfil
    de peça ou um `--set publicacao.…` no `perfil.py resolver`."""
    import perfil as perfil_mod   # local: só quem resolve perfil paga o import
    if ignorar_perfil:
        return json.loads(json.dumps(PADRAO_PUBLICACAO)), "(--perfil-off)"
    tem = os.path.isfile(os.path.join(d, "perfil.json")) if os.path.isdir(d) else False
    if not tem:
        return json.loads(json.dumps(PADRAO_PUBLICACAO)), "(sem perfil.json)"
    p = perfil_mod.carregar(d, quieto=quieto)
    return _fundir(PADRAO_PUBLICACAO, p.get("publicacao")), p.get("nome", "?")


# ───────────────────────────────────────────────────────── leitura de transcript

def carregar_words(path):
    """transcript Deepgram → [{word, punctuated_word, start, end, confidence}].

    Aceita o envelope completo do Deepgram e também um array nu de palavras (é o
    que `--alinhamento` e alguns transcripts derivados entregam). O formato
    Whisper (`{"type":"word","text":…}`) do `captions_srt.py` do ref-A NÃO é o
    nosso e não é aceito em silêncio: se vier, a mensagem diz o que falta."""
    if not os.path.isfile(path):
        raise ErroPalavras("transcript não encontrado: %s" % os.path.abspath(path))
    with open(path) as fh:
        doc = json.load(fh)
    ws = None
    if isinstance(doc, list):
        ws = doc
    elif isinstance(doc, dict):
        if isinstance(doc.get("words"), list):
            ws = doc["words"]
        else:
            try:
                ws = doc["results"]["channels"][0]["alternatives"][0]["words"]
            except (KeyError, IndexError, TypeError):
                ws = None
    if not isinstance(ws, list):
        raise ErroPalavras(
            "%s não tem lista de palavras. Esperado o envelope Deepgram "
            "(results.channels[0].alternatives[0].words) ou um array nu." % path)
    out = []
    for i, w in enumerate(ws):
        if not isinstance(w, dict):
            raise ErroPalavras("%s: palavra %d não é objeto" % (path, i))
        if "start" not in w or "end" not in w:
            raise ErroPalavras(
                "%s: palavra %d sem `start`/`end` (%r). Se este arquivo está no "
                "formato Whisper (`type`/`text`), converta antes — o leitor "
                "daqui é Deepgram." % (path, i, sorted(w)))
        texto = w.get("punctuated_word") or w.get("word") or w.get("text") or ""
        out.append({"word": w.get("word", texto),
                    "punctuated_word": texto,
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "confidence": float(w.get("confidence", 1.0))})
    out.sort(key=lambda x: x["start"])
    return out


# ──────────────────────────────────────────────── resolver src → transcript

def _stem(src):
    return os.path.splitext(os.path.basename(str(src)))[0]


def _abs(d, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(d, p))


def resolver_transcritos(d, srcs, explicitos=None, mapa_arq=None):
    """src (como está na EDL) → caminho do transcript. NUNCA silenciosa.

    A ordem é a da §3.2.2 da SPEC-21, e o passo 6 é ERRO FATAL: take sem
    transcript não vira buraco silencioso no `.srt` (é o que o `render.py:770-773`
    do ref-A faz — imprime "skipping", soma o offset e continua)."""
    srcs = list(dict.fromkeys(srcs))
    achados, como = {}, {}
    tentativas = []

    # 1. --transcript "src=caminho": explícito, vence tudo.
    for src, p in (explicitos or {}).items():
        alvo = None
        if src in srcs:
            alvo = src
        else:
            iguais = [s for s in srcs if s == src or _stem(s) == _stem(src)
                      or os.path.basename(s) == os.path.basename(src)]
            alvo = iguais[0] if len(iguais) == 1 else None
        if alvo is None:
            raise ErroPalavras(
                "--transcript %r: nenhum src da EDL casa com %r.\n"
                "srcs na EDL: %s" % (src + "=" + p, src, ", ".join(srcs)))
        achados[alvo], como[alvo] = _abs(d, p), "--transcript"

    # 2. <dir>/transcritos.json — o formato canônico novo.
    mapa_p = mapa_arq or os.path.join(d, "transcritos.json")
    tentativas.append(mapa_p)
    if os.path.isfile(mapa_p):
        with open(mapa_p) as fh:
            mp = json.load(fh)
        if not isinstance(mp, dict):
            raise ErroPalavras("%s: esperado objeto {src: caminho}" % mapa_p)
        for src, p in mp.items():
            if src in srcs and src not in achados:
                achados[src], como[src] = _abs(d, p), os.path.basename(mapa_p)
    elif mapa_arq:
        raise ErroPalavras("--transcritos: arquivo não existe: %s" % mapa_arq)

    # 3. <dir>/spec.json com `src` + `transcript` — o precedente já em uso.
    spec_p = os.path.join(d, "spec.json")
    tentativas.append(spec_p)
    if os.path.isfile(spec_p):
        try:
            with open(spec_p) as fh:
                sp = json.load(fh)
        except (json.JSONDecodeError, OSError):
            sp = None
        if isinstance(sp, dict) and sp.get("src") and sp.get("transcript"):
            src = sp["src"]
            alvo = src if src in srcs else next(
                (s for s in srcs if _stem(s) == _stem(src)), None)
            if alvo and alvo not in achados:
                achados[alvo], como[alvo] = _abs(d, sp["transcript"]), "spec.json"

    # 4. <dir>/<stem(src)>/transcript.json
    for src in srcs:
        if src in achados:
            continue
        cand = os.path.join(d, _stem(src), "transcript.json")
        tentativas.append(cand)
        if os.path.isfile(cand):
            achados[src], como[src] = cand, "<stem(src)>/transcript.json"

    # 4b. 🔴 <dir>/transcript.json E <dir-do-src>/transcript.json — onde o
    # `transcribe.sh` DO PRÓPRIO PACOTE grava (2026-08-12, H47-10/A-14/F47-4).
    # Medido em campo, duas vezes: com `transcript.json` na raiz da produção — o
    # lugar em que o transcritor do pacote o escreve — este resolvedor falhava, e
    # o `palavras.py` só funcionava com `--transcript` explícito. A lista tinha 5
    # portas e nenhuma delas era o lugar óbvio. No layout ad-hoc do cliente
    # (`input/bruto/take.mp4`) o transcript sai em `input/bruto/transcript.json`,
    # ao lado do bruto: essa é a segunda porta aqui.
    #
    # ⚠️ Vem DEPOIS das quatro acima e ANTES do casamento por eliminação de
    # propósito: declaração explícita (`--transcript`, `transcritos.json`,
    # `spec.json`) sempre vence, e a nota do item 5 sobre `final-transcript/`
    # continua valendo — este ramo não aceita diretório arbitrário, só a RAIZ da
    # produção e o diretório do próprio src.
    implicitos_usados = set()
    for src in srcs:
        if src in achados:
            continue
        candidatos = [
            (os.path.join(os.path.dirname(_abs(d, src)), "transcript.json"),
             "<dir-do-src>/transcript.json"),
        ]
        # Um transcript solto na raiz não identifica a qual bruto pertence. Ele
        # só é uma inferência segura quando a EDL tem uma única fonte.
        if len(srcs) == 1:
            candidatos.append((os.path.join(d, "transcript.json"),
                               "<dir>/transcript.json"))
        for cand, rotulo in candidatos:
            tentativas.append(cand)
            chave = os.path.realpath(cand)
            if os.path.isfile(cand) and chave not in implicitos_usados:
                achados[src], como[src] = cand, rotulo
                implicitos_usados.add(chave)
                break

    # 5. um único src e um único `take*/transcript.json` → casamento por eliminação.
    #
    # 🔴 O PREFIXO `take` NÃO É COSMÉTICO. `creator-2/peca-03` tem TRÊS diretórios com
    # `transcript.json`: `take-A/` (o bruto, que é o certo), `final-transcript/` e
    # `final-transcript-derivado/` — os dois últimos são transcrições DO MONTADO.
    # Aceitar "qualquer diretório com transcript.json" faria o resolvedor sortear
    # entre eles e, no dia em que sorteasse o do montado, o `.srt` sairia com a
    # palavra inventada na emenda: exatamente o defeito que esta spec existe para
    # não repetir. Com o prefixo, sobra um só candidato e a escolha é determinada.
    faltam = [s for s in srcs if s not in achados]
    if len(faltam) == 1 and len(srcs) == 1:
        nomes = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else [])
                       if n.lower().startswith("take"))
        cands = [p for p in (os.path.join(d, n, "transcript.json") for n in nomes)
                 if os.path.isfile(p)]
        tentativas.append(os.path.join(d, "take*/transcript.json"))
        if len(cands) == 1:
            achados[faltam[0]], como[faltam[0]] = cands[0], "único take*/ da pasta"

    # 6. não achou: erro fatal com a linha pronta para colar.
    faltam = [s for s in srcs if s not in achados]
    if faltam:
        linhas = ["  --transcript \"%s=<caminho>/transcript.json\"" % s for s in faltam]
        raise ErroPalavras(
            "sem transcript para %d src da EDL: %s\n"
            "Tentei, nesta ordem: --transcript, transcritos.json, spec.json, "
            "<stem(src)>/transcript.json, transcript ao lado do src (sem "
            "reuso implícito entre fontes), casamento por eliminação.\n"
            "Procurei em:\n  %s\n"
            "Declare o caminho (repetível) e rode de novo:\n%s"
            % (len(faltam), ", ".join(faltam),
               "\n  ".join(os.path.relpath(t, d) if t.startswith(d) else t
                           for t in dict.fromkeys(tentativas)),
               "\n".join(linhas)))
    for src, p in achados.items():
        if not os.path.isfile(p):
            raise ErroPalavras(
                "transcript declarado para %s não existe: %s (via %s)"
                % (src, os.path.abspath(p), como.get(src, "?")))
    return achados, como


# ─────────────────────────────────────────────────────────────────── ortografia

def _norm(s):
    s = unicodedata.normalize("NFD", str(s).lower().strip(" .,?!:;\"'"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def carregar_ortografia(d, arq=None):
    """{"troca": {token: texto}, "grupo": [{"de": [tokens], "para": texto}]}

    Corrige GRAFIA e FORMATO DE NÚMERO sobre token reconhecido. Troca que muda a
    palavra tem que estar escrita aqui — e o sidecar registra quantas foram
    aplicadas, para quem revisa ver o número."""
    p = arq or os.path.join(d, "ortografia.json")
    if not os.path.isfile(p):
        if arq:
            raise ErroPalavras("--ortografia: arquivo não existe: %s" % arq)
        return None, {"arquivo": None, "troca": {}, "grupo": []}
    with open(p) as fh:
        doc = json.load(fh)
    troca = {_norm(k): v for k, v in (doc.get("troca") or {}).items()}
    grupo = {}
    for g in (doc.get("grupo") or []):
        chave = tuple(_norm(x) for x in g["de"])
        grupo[chave] = g["para"]
    return {"troca": troca, "grupo": grupo}, {
        "arquivo": os.path.relpath(p, d) if p.startswith(d) else p,
        "troca": len(troca), "grupo": len(grupo)}


_FIM = re.compile(r"[.,?!:;…]+$")


def aplicar_ortografia(ws, orto):
    """Grupos primeiro (do mais longo para o mais curto), depois trocas de token."""
    if not orto:
        return list(ws), 0, 0
    maior = max((len(k) for k in orto["grupo"]), default=0)
    out, i, n_g, n_t = [], 0, 0, 0
    while i < len(ws):
        casou = False
        for n in range(maior, 1, -1):
            if i + n > len(ws):
                continue
            chave = tuple(_norm(x["texto"]) for x in ws[i:i + n])
            if chave in orto["grupo"]:
                texto = orto["grupo"][chave]
                m = _FIM.search(ws[i + n - 1]["texto"])
                item = dict(ws[i])
                item["texto"] = texto + (m.group(0) if m else "")
                item["fim"] = ws[i + n - 1]["fim"]
                item["conf"] = min(x["conf"] for x in ws[i:i + n])
                out.append(item)
                n_g += 1
                i += n
                casou = True
                break
        if casou:
            continue
        x = dict(ws[i])
        k = _norm(x["texto"])
        if k in orto["troca"]:
            m = _FIM.search(x["texto"])
            x["texto"] = orto["troca"][k] + (m.group(0) if m else "")
            n_t += 1
        out.append(x)
        i += 1
    return out, n_t, n_g


# ─────────────────────────────────────────────────────────────────── o mapa

def offset_audio_s(tl, seg):
    """Início do ÁUDIO deste segmento na saída, em segundos.

    `audio_offset_samples` é escrito pela SPEC-07 quando há J-cut; sem ele o
    áudio começa junto com o vídeo e `start_sample` é o mesmo número. Sem
    amostras no bloco (fps/sr sem divisão exata), cai em `start_s`, que é
    `start_frame/fps` — nunca uma soma de segundos da EDL."""
    sr = tl.get("sample_rate")
    n = seg.get("audio_offset_samples", seg.get("start_sample"))
    if n is not None and sr:
        return n / float(sr)
    return seg["start_s"]


def dur_audio_s(tl, seg):
    """Duração do áudio deste segmento na saída (a janela em que a fala dele cabe)."""
    sr = tl.get("sample_rate")
    if seg.get("samples") is not None and sr:
        return seg["samples"] / float(sr)
    return seg["dur_s"]


def descontinuidades(tl):
    """[bool] por segmento: o segmento `i` abre uma descontinuidade REAL?

    Mesmo predicado que a SPEC-00 usa em `fade_modo: so-descontinuidade`: troca de
    `src` ou `src_start_i != src_end_{i-1}`. A divisão em planos contíguos do
    `dividir-planos.py` NÃO é descontinuidade — é a mesma frase com dois
    enquadramentos, e um cue de legenda não pode quebrar ali."""
    segs = tl["segments"]
    out = [True] * len(segs)
    for i in range(1, len(segs)):
        a, b = segs[i - 1], segs[i]
        contiguo = (a.get("src") == b.get("src")
                    and a.get("src_end") is not None
                    and b.get("src_start") is not None
                    and abs(float(a["src_end"]) - float(b["src_start"])) < 1e-6)
        out[i] = not contiguo
    return out


def palavras_no_montado(d, *, tl=None, transcritos=None, mapa_arq=None,
                        alinhamento=None, ortografia=None, orto_arq=None):
    """As palavras do bruto em tempo de SAÍDA. Devolve (lista, info)."""
    tl = tl if tl is not None else edl_io.timeline(d, exigir=True)
    segs = tl["segments"]
    srcs = [s.get("src") for s in segs]
    if any(s is None for s in srcs):
        raise ErroPalavras("timeline_real tem segmento sem `src` — EDL por frames? "
                           "não dá para mapear palavra do bruto")
    mapa, como = resolver_transcritos(d, srcs, explicitos=transcritos,
                                      mapa_arq=mapa_arq)
    cache = {p: carregar_words(p) for p in set(mapa.values())}

    align = None
    if alinhamento:
        align = carregar_words(alinhamento)

    orto, info_orto = (ortografia, {"arquivo": None, "troca": 0, "grupo": 0}) \
        if ortografia is not None else carregar_ortografia(d, orto_arq)

    fora = 0
    brutas = []
    for i, seg in enumerate(segs):
        s0, s1 = seg.get("src_start"), seg.get("src_end")
        if s0 is None or s1 is None:
            raise ErroPalavras("segmento %d sem start/end na EDL: não dá para mapear" % i)
        a_off = offset_audio_s(tl, seg)
        a_dur = dur_audio_s(tl, seg)
        ws = cache[mapa[seg["src"]]]
        for k, w in enumerate(ws):
            # "começa dentro da janela" (SKILL.md, etapa 2). NÃO é sobreposição:
            # uma palavra partida por um corte pertenceria aos dois lados e
            # apareceria DUAS VEZES (é o `render.py:736-748` do ref-A).
            if not (s0 <= w["start"] < s1):
                continue
            ini_w, fim_w = w["start"], w["end"]
            if align is not None and k < len(align):
                ini_w = align[k]["start"]
                fim_w = max(align[k]["end"], ini_w)
            ini = a_off + (ini_w - s0)
            fim = a_off + (fim_w - s0)
            teto = a_off + a_dur
            if fim > teto:
                fim = teto
                fora += 1
            if ini < a_off:
                ini = a_off
            if fim <= ini:
                fim = min(teto, ini + 1e-3)
            brutas.append({"i_seg": i, "src": seg["src"],
                           "texto": w["punctuated_word"],
                           "texto_cru": w["punctuated_word"],
                           "ini": round(ini, CASAS), "fim": round(fim, CASAS),
                           "conf": round(w["confidence"], 4)})
    brutas.sort(key=lambda x: (x["ini"], x["i_seg"]))
    out, n_t, n_g = aplicar_ortografia(brutas, orto)
    info = {
        "schema": SCHEMA,
        "transcritos": {k: (os.path.relpath(v, d) if v.startswith(os.path.abspath(d))
                            or v.startswith(d) else v) for k, v in mapa.items()},
        "resolvido_por": como,
        "fonte_palavras": "edl-bruto",
        "fonte_tempo": "align" if align is not None else "asr",
        "ortografia": {"arquivo": info_orto["arquivo"],
                       "trocas_aplicadas": n_t, "grupos_aplicados": n_g},
        "palavras": len(out),
        "cauda_clampada": fora,
        "descontinuidades": descontinuidades(tl),
        "total_s": tl["total_s"],
        "fps": tl["video"]["fps"],
        "sample_rate": tl.get("sample_rate"),
        "edl_fingerprint": tl.get("edl_fingerprint"),
    }
    return out, info


# ────────────────────────────────────────────────────────────────────────── CLI

def _cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("────")[0].strip(), file=sys.stderr)
        return 64
    d = argv.pop(0)
    explicitos, mapa_arq, orto_arq, align, como_json = {}, None, None, None, False
    while argv:
        a = argv.pop(0)
        if a == "--transcript":
            v = argv.pop(0)
            if "=" not in v:
                print("--transcript espera \"src=caminho\"", file=sys.stderr)
                return 64
            k, _, p = v.partition("=")
            explicitos[k] = p
        elif a == "--transcritos":
            mapa_arq = argv.pop(0)
        elif a == "--ortografia":
            orto_arq = argv.pop(0)
        elif a == "--alinhamento":
            align = argv.pop(0)
        elif a == "--json":
            como_json = True
        else:
            print("flag desconhecida: %s" % a, file=sys.stderr)
            return 64
    try:
        ws, info = palavras_no_montado(d, transcritos=explicitos, mapa_arq=mapa_arq,
                                       alinhamento=align, orto_arq=orto_arq)
    except ErroPalavras as e:
        print("ERRO: %s" % e, file=sys.stderr)
        return 1
    print("%d palavras · %d src · tempo=%s · ortografia %s (%d trocas, %d grupos)"
          % (info["palavras"], len(info["transcritos"]), info["fonte_tempo"],
             info["ortografia"]["arquivo"] or "—",
             info["ortografia"]["trocas_aplicadas"],
             info["ortografia"]["grupos_aplicados"]), file=sys.stderr)
    if como_json:
        json.dump(ws, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        for w in ws:
            print("%8.3f %8.3f  seg%02d  %s" % (w["ini"], w["fim"], w["i_seg"], w["texto"]))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
