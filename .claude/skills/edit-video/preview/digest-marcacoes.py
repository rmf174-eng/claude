#!/usr/bin/env python3
"""digest-marcacoes.py — as marcações IN/OUT viram instrução acionável (SPEC-18 §3.6).

A marcação IN/OUT com instrução é MECANISMO observado em uma ferramenta de
edição de terceiro.
Nenhuma linha foi portada. Ver docs/specs/SPEC-18 §10.

────────────────────────────────────────────────────────────────────────────
O QUE ISTO RESOLVE. O canal de volta do creator-1 hoje é prosa sem coordenada ("lá
pelo meio, quando ela fala do ovo"). A app grava um par de segundos exato no
RENDER; este script traduz esse par para o que o agente vai de fato editar — a
EDL, que é escrita em tempo de FONTE — e junta o que estava na tela naquele
instante.

    t_render  ──(timeline_real | medida de segs/)──►  take k
    t_fonte   =  edl[k].start + (t_render − timeline.segments[k].start_s)

🔴 TRÊS REGRAS DURAS

1. NUNCA Σ(end−start). A soma nominal da EDL é MENOR que a saída (o render
   arredonda para frame e o erro acumula no mesmo sentido): 316,7 ms no fim da
   `peca-01`, 353,3 ms em `peca-03`. Atribuir take por essa régua manda
   o agente editar o take vizinho e NADA acusa. Ou há `timeline_real`, ou os
   `segs/` são medidos por `ffprobe -count_frames`, ou a linha do take sai
   `indisponível` — nunca chutada.

2. SÓ O QUE FOI MEDIDO. O cabeçalho diz de onde veio a régua. Camada sem dado
   sai `sem dado`, não `nenhum` — "nenhum" é uma medição de zero, e afirmar zero
   sobre o que não se olhou é o defeito que o bloco `integridade` da SPEC-16
   existe para não repetir.

3. LER NÃO CONSOME. `--ack` é um segundo comando, explícito, e ele MOVE para
   `.preview/aplicados/` (nunca apaga: relatório que apaga a evidência não
   serve — SPEC-16 §3.12).

────────────────────────────────────────────────────────────────────────────
USO

    digest-marcacoes.py <dir> [--json] [--ack] [--arquivo X] [--verificar]
                              [--componente src/Foo.tsx]

    --json         devolve benchmark.marcacoes-digest/v1 no stdout
    --ack          move os eventos lidos para .preview/aplicados/
    --arquivo X    lê só esse evento (caminho ou basename dentro de pendentes/)
    --verificar    confere as invariantes do contrato e sai 1 se alguma cair
    --componente   declara o .tsx que carrega os overlays em CÓDIGO desta peça
                   (nada dentro de <dir> aponta para ele — ver §"em código")

Markdown no stdout, logs no stderr. Sai 0 mesmo sem marcação nenhuma (dizendo
isso), 1 em erro de contrato com --verificar, 2 em erro de uso.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "scripts"))
import edl_io                    # noqa: E402  SPEC-05 — envelope v2 + timeline real
import estado as estado_mod      # noqa: E402  SPEC-16 — contrato da UI (sid_de)

CONTRATO = "benchmark.edit-marcacoes/v1"
CONTRATO_DIGEST = "benchmark.marcacoes-digest/v1"
CONTRATO_ENVELOPE = "benchmark.preview-evento/v1"

# Espelha o enum de `js/trilhas.js` (SPEC-18 §4.2). Atualizar os dois juntos.
TRILHAS = ("corte", "audio", "legenda", "enquadramento", "falante", "grafico",
           "broll", "insert", "sfx", "trilha-sonora", "geral")

MAX_PALAVRAS_CONTEXTO = 40

# Quantas vezes um subprocesso de mídia foi REALMENTE chamado neste processo.
# Não é declaração: o contador é incrementado por dentro do wrapper (§7.8).
CONTADORES = {"ffprobe": 0, "ffmpeg": 0}

_probe_original = edl_io._probe


def _probe_contado(*args, **kwargs):
    CONTADORES["ffprobe"] += 1
    return _probe_original(*args, **kwargs)


edl_io._probe = _probe_contado


# ───────────────────────────────────────────────────────────────── utilidades

def _ler_json(caminho, default=None):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _pt(x, casas=3):
    """Número com vírgula decimal — o digest é lido por humano brasileiro."""
    if x is None:
        return "—"
    return ("%.*f" % (casas, x)).replace(".", ",")


def _mmss(t):
    if t is None:
        return "—"
    m, s = divmod(float(t), 60.0)
    return "%d:%06.3f" % (int(m), s)


def _sha1_texto(txt):
    return "sha1:" + hashlib.sha1(txt.encode("utf-8")).hexdigest()


def dir_preview(d):
    return os.path.join(d, ".preview")


# ─────────────────────────────────────────────────────── entrada: os pendentes

def carregar_pendentes(d, arquivo=None):
    """Os eventos `*-marcacoes-*.json` de `.preview/pendentes/`, cronológicos.

    Aceita tanto o ENVELOPE da SPEC-17 (`{schema, tipo, payload}`) quanto o
    payload cru — o segundo é o caminho de quando não há servidor (fixture,
    teste, agente escrevendo à mão), simétrico ao que a SPEC-16 §3.3 faz.
    """
    pend = os.path.join(dir_preview(d), "pendentes")
    if arquivo:
        cam = arquivo if os.path.isabs(arquivo) or os.path.sep in arquivo \
            else os.path.join(pend, arquivo)
        caminhos = [cam] if os.path.isfile(cam) else []
    else:
        caminhos = sorted(glob.glob(os.path.join(pend, "*-marcacoes-*.json")))
    saida = []
    for c in caminhos:
        obj = _ler_json(c)
        if not isinstance(obj, dict):
            print("aviso: %s não é JSON de objeto — ignorado" % c, file=sys.stderr)
            continue
        if obj.get("schema") == CONTRATO_ENVELOPE:
            pay = obj.get("payload")
            if not isinstance(pay, dict):
                print("aviso: %s é envelope sem payload — ignorado" % c, file=sys.stderr)
                continue
            salvo = obj.get("salvo_em") or pay.get("salvo_em")
        else:
            pay, salvo = obj, obj.get("salvo_em")
        if pay.get("contrato") != CONTRATO:
            print("aviso: %s não é %s (é %r) — ignorado"
                  % (c, CONTRATO, pay.get("contrato")), file=sys.stderr)
            continue
        saida.append({"arquivo": c, "salvo_em": salvo, "payload": pay})
    saida.sort(key=lambda e: (e["salvo_em"] or "", e["arquivo"]))
    return saida


# ────────────────────────────────────────────────────────────────── a régua

def timeline_de(d):
    """(timeline, origem) — `timeline_real` | `medida` | `indisponivel`.

    NUNCA devolve uma régua somada da EDL. Quando não dá para medir, devolve
    `None` e quem chama imprime `indisponível`.
    """
    try:
        tl = edl_io.timeline(d, exigir=False)
    except SystemExit:
        tl = None
    except (OSError, ValueError, KeyError) as erro:
        print("aviso: timeline_real ilegível (%s)" % erro, file=sys.stderr)
        tl = None
    if tl:
        return tl, "timeline_real"
    try:
        tl = edl_io.medir_timeline(d, gerado_por="digest-marcacoes.py")
    except SystemExit as erro:
        motivo = str(erro.code or "").splitlines()[0] if erro.code else "sem motivo"
        print("timeline não medível: %s" % motivo, file=sys.stderr)
        return None, "indisponivel"
    except (OSError, ValueError, KeyError) as erro:
        print("timeline não medível: %s" % erro, file=sys.stderr)
        return None, "indisponivel"
    return tl, "medida"


def take_em(tl, segments, sids, t):
    """O take que contém `t` no RENDER + a coordenada correspondente na FONTE."""
    if not tl:
        return None
    segs = tl.get("segments") or []
    if not segs:
        return None
    fps = (tl.get("video") or {}).get("fps")
    k = None
    for s in segs:
        ini = s["start_s"]
        fim = ini + s["dur_s"]
        if ini - 1e-9 <= t < fim:
            k = s["i"]
            break
    if k is None:
        k = segs[-1]["i"] if t >= segs[-1]["start_s"] else segs[0]["i"]
    linha = segs[k]
    edl_seg = segments[k] if k < len(segments) else {}
    off = t - linha["start_s"]
    src_start = edl_seg.get("start")
    t_fonte = (src_start + off) if isinstance(src_start, (int, float)) else None
    return {
        "i": k,
        "sid": sids[k] if k < len(sids) else None,
        "arquivo": "segs/seg%03d.mp4" % k,
        "src": edl_seg.get("src"),
        "src_start": src_start,
        "src_end": edl_seg.get("end"),
        "t_fonte": t_fonte,
        "beat": edl_seg.get("beat"),
        "quem": edl_seg.get("quem"),
        "zoom": edl_seg.get("zoom"),
        "cx": edl_seg.get("cx"),
        "cy": edl_seg.get("cy"),
        "start_s": linha["start_s"],
        "dur_s": linha["dur_s"],
        "fps": fps,
    }


# ────────────────────────────────────────────────────── o que estava na tela

def fala_em(caps, ini, fim):
    """As palavras da `captions.json` dentro da janela (tempo de RENDER, ms)."""
    if not isinstance(caps, list):
        return []
    a, b = ini * 1000.0, max(fim, ini) * 1000.0
    saida = []
    for w in caps:
        try:
            s, e = float(w.get("startMs")), float(w.get("endMs"))
        except (TypeError, ValueError):
            continue
        if e >= a and s <= b + 1e-6:
            saida.append({"t": round(s / 1000.0, 3),
                          "w": (w.get("text") or "").strip()})
    return saida


def _janelas_de(lista, ini, fim):
    """Itens `{ini,fim}` (ou `{start,end}`) que intersectam a janela."""
    achados = []
    for it in lista or []:
        if not isinstance(it, dict):
            continue
        a = it.get("ini", it.get("start", it.get("from")))
        b = it.get("fim", it.get("end", it.get("to")))
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            continue
        if b >= ini and a <= fim:
            achados.append({"ini": a, "fim": b,
                            "id": it.get("id") or it.get("ref") or it.get("nome")})
    return achados


def camadas_em(d, ini, fim, componente=None):
    """O que existe COMO DADO na janela, e o que só existe como código.

    🔴 `em_codigo` é `None` quando ninguém declarou o componente. Medido em
    2026-08-08: nada dentro de `creators/creator-2/producao/peca-01/` aponta
    para `MesaComAmiga.tsx` — o vínculo peça↔componente vive no projeto Remotion
    (`src/index-*.tsx`), fora da produção. Um digest que fosse adivinhar isso
    estaria acoplado à NOSSA instalação, que é o que a SPEC-000 §3.0 proíbe.
    """
    caps = _ler_json(os.path.join(d, "captions.json"), [])
    palavras = fala_em(caps, ini, fim)

    legenda = {"palavras": len(palavras)}
    part = _ler_json(os.path.join(d, "partitura.json"))
    if isinstance(part, dict) and isinstance(part.get("paginas"), list):
        pgs = [p["i"] for p in part["paginas"]
               if isinstance(p, dict) and isinstance(p.get("i"), int)
               and float(p.get("endMs", 0)) >= ini * 1000.0
               and float(p.get("startMs", 0)) <= fim * 1000.0 + 1e-6]
        legenda["paginas"] = [min(pgs), max(pgs)] if pgs else []
    else:
        legenda["paginas"] = None          # sem partitura.json (SPEC-14) não há página

    ov = _ler_json(os.path.join(d, "overlays.json"))
    cards = (ov or {}).get("cards") if isinstance(ov, dict) else None
    grafico = {"em_dado": len(_janelas_de(cards, ini, fim)) if isinstance(cards, list) else 0,
               "tem_arquivo": isinstance(ov, dict),
               "em_codigo": None, "arquivo": componente}
    if componente and os.path.isfile(componente):
        try:
            with open(componente, encoding="utf-8") as fh:
                texto = fh.read()
            grafico["em_codigo"] = texto.count("<OverlayGroup")
        except OSError:
            pass

    def _lado(nome):
        obj = _ler_json(os.path.join(d, nome))
        if obj is None:
            return None                    # sem dado ≠ nenhum
        lista = obj if isinstance(obj, list) else (obj.get("janelas") or obj.get("itens"))
        return _janelas_de(lista, ini, fim)

    return {"legenda": legenda, "grafico": grafico,
            "broll": _lado("broll.json"), "insert": _lado("inserts.json"),
            "_palavras": palavras}


# ──────────────────────────────────────────────────────────── as invariantes

def conferir_nota(n, fps):
    """As invariantes de §4.1. Lista vazia = ok."""
    erros = []
    r = n.get("render") or {}
    try:
        ri, rf = float(r["ini"]), float(r["fim"])
    except (KeyError, TypeError, ValueError):
        return ["render ausente ou não numérico"]
    if ri > rf + 1e-9:
        erros.append("render.ini (%s) > render.fim (%s)" % (ri, rf))
    tipo = n.get("tipo")
    if tipo not in ("intervalo", "ponto"):
        erros.append("tipo %r fora de {intervalo, ponto}" % tipo)
    elif (tipo == "ponto") != (abs(rf - ri) < 1e-9):
        erros.append("tipo=%s com ini=%s fim=%s" % (tipo, ri, rf))
    fr = n.get("render_frames")
    if fps and isinstance(fr, list) and len(fr) == 2:
        for j, t in ((0, ri), (1, rf)):
            if fr[j] != round(t * fps):
                erros.append("render_frames[%d]=%s, round(%s×%s)=%d"
                             % (j, fr[j], t, fps, round(t * fps)))
    elif fr is not None and not (isinstance(fr, list) and len(fr) == 2):
        erros.append("render_frames malformado: %r" % (fr,))
    if n.get("sid") is None and n.get("sid_confianca") != "indisponivel":
        erros.append("sid null com sid_confianca=%r" % n.get("sid_confianca"))
    if n.get("trilha") is not None and n["trilha"] not in TRILHAS:
        erros.append("trilha %r fora do enum §4.2" % n["trilha"])
    if not (n.get("texto") or "").strip():
        erros.append("texto vazio — marcação sem pedido não é dado")
    return erros


# ──────────────────────────────────────────────────────────────────── digest

def _fingerprint_render(d, nome):
    """sha1(nome|bytes|mtime) — a mesma conta do `estado.py:492`, sem ffprobe."""
    if not nome:
        return None
    p = os.path.join(d, nome)
    try:
        st = os.stat(p)
    except OSError:
        return None
    return _sha1_texto("%s|%d|%d" % (nome, st.st_size, int(st.st_mtime)))


def coletar(d, eventos, componente=None):
    """O dado do digest — o markdown e o --json saem os dois daqui."""
    tl, origem = timeline_de(d)
    segments = edl_io.segmentos(d)
    sids = estado_mod.sid_de(segments)
    est = _ler_json(os.path.join(dir_preview(d), "estado.json"), {}) or {}

    fps = None
    if tl:
        fps = (tl.get("video") or {}).get("fps")
    if not fps:
        fps = ((est.get("formato") or {}).get("fps"))

    alvo = None
    for ev in eventos:
        alvo = ev["payload"].get("render_alvo") or alvo
    if not alvo:
        alvo = est.get("render_corrente")
    ficha = next((r for r in (est.get("renders") or [])
                  if r.get("arquivo") == alvo), None)
    dur_render = (ficha or {}).get("duracao_s")
    if dur_render is None and tl:
        dur_render = tl.get("total_s")
    if not fps and ficha:
        fps = ficha.get("fps")

    fp_atual = _fingerprint_render(d, alvo)

    marcacoes, avisos = [], []
    for ev in eventos:
        pay = ev["payload"]
        fp_nota = pay.get("fingerprint_render")
        confere = None if not (fp_nota and fp_atual) else (fp_nota == fp_atual)
        if confere is False:
            avisos.append("o render mudou depois da marcação (sha1 esperado %s, "
                          "atual %s) — as coordenadas apontam para um arquivo que "
                          "não existe mais" % (fp_nota, fp_atual))
        for n in (pay.get("notas") or []):
            r = n.get("render") or {}
            try:
                ini, fim = float(r.get("ini")), float(r.get("fim"))
            except (TypeError, ValueError):
                avisos.append("nota %s sem coordenada de render — pulada"
                              % n.get("id"))
                continue
            cam = camadas_em(d, ini, fim, componente)
            palavras = cam.pop("_palavras")
            take = take_em(tl, segments, sids, ini)
            take_fim = take_em(tl, segments, sids, fim) if fim > ini else take
            div = _divergencia(n, palavras, take)
            marcacoes.append({
                "id": n.get("id"),
                "evento": os.path.basename(ev["arquivo"]),
                "tipo": n.get("tipo"),
                "fase": n.get("fase"),
                "trilha": n.get("trilha"),
                "ref": n.get("ref"),
                "marcado_invertido": bool(n.get("marcado_invertido")),
                "render": {"ini": ini, "fim": fim},
                "frames": n.get("render_frames"),
                "fingerprint_confere": confere,
                "take": _take_publico(take, ini, fim, take_fim),
                "sid_da_nota": n.get("sid"),
                "sid_confianca": n.get("sid_confianca"),
                "fala": " ".join(w["w"] for w in palavras).strip(),
                "palavras": len(palavras),
                "camadas": cam,
                "divergencia_de_contexto": div,
                "pedido": n.get("texto"),
                "erros_de_contrato": conferir_nota(n, fps),
            })

    return {
        "contrato": CONTRATO_DIGEST,
        "dir": d,
        # None = ninguém declarou fingerprint (nada foi conferido). Dizer
        # "CONFERE" nesse caso é o verde sem dentes que a §9 proíbe.
        "render": {"arquivo": alvo, "fingerprint": fp_atual,
                   "fingerprint_confere": _veredito_fp(marcacoes),
                   "dur_s": dur_render, "fps": fps},
        "timeline": {"origem": origem,
                     "total_s": (tl or {}).get("total_s"),
                     "total_frames": (tl or {}).get("total_frames")},
        "eventos": [os.path.basename(e["arquivo"]) for e in eventos],
        "ffprobe_invocado": CONTADORES["ffprobe"] > 0,
        "ffmpeg_invocado": CONTADORES["ffmpeg"] > 0,
        "avisos": avisos,
        "marcacoes": marcacoes,
    }


def _veredito_fp(marcacoes):
    vistos = [m["fingerprint_confere"] for m in marcacoes
              if m["fingerprint_confere"] is not None]
    if not vistos:
        return None
    return all(vistos)


def _take_publico(take, ini, fim, take_fim):
    """🔴 A coordenada de FONTE do fim vem do take DO FIM, nunca de `src_ini+dur`.

    Somar a duração de saída sobre o `start` do primeiro take dá um número que
    parece certo e aponta para dentro de outro trecho do bruto quando a marcação
    atravessa uma emenda — que é o tipo de erro que este repo já pagou (o
    segmento órfão) e que ninguém percebe olhando o relatório.
    """
    if not take:
        return None
    dur = max(fim - ini, 0.0)
    atravessa = bool(take_fim and take_fim["i"] != take["i"])
    src_ini = take["t_fonte"]
    if take_fim and take_fim["t_fonte"] is not None:
        src_fim = take_fim["t_fonte"]
    elif src_ini is not None and not atravessa:
        src_fim = src_ini + dur
    else:
        src_fim = None
    fora = []
    for nome, v, t in (("ini", src_ini, take), ("fim", src_fim, take_fim or take)):
        a, b = t.get("src_start"), t.get("src_end")
        if v is None or a is None or b is None:
            continue
        if v < a - 1e-6 or v > b + 1e-6:
            fora.append("%s (%.3f) fora de [%.3f, %.3f] do take %d"
                        % (nome, v, a, b, t["i"]))
    return {"sid": take["sid"], "i": take["i"], "arquivo": take["arquivo"],
            "src": take["src"], "src_ini": src_ini, "src_fim": src_fim,
            "edl_start": take["src_start"], "edl_end": take["src_end"],
            "beat": take["beat"], "quem": take["quem"],
            "zoom": take["zoom"], "cx": take["cx"], "cy": take["cy"],
            "atravessa_takes": atravessa,
            "take_do_fim": take_fim["i"] if take_fim else None,
            "sid_do_fim": take_fim["sid"] if take_fim else None,
            "src_do_fim": take_fim["src"] if take_fim else None,
            "arquivo_do_fim": take_fim["arquivo"] if take_fim else None,
            "fora_da_janela": fora}


def _divergencia(n, palavras, take):
    """O contexto congelado na nota × o recalculado agora. Confrontar, não duplicar."""
    ctx = n.get("contexto") or {}
    fora = []
    congeladas = ctx.get("palavras")
    if isinstance(congeladas, list) and congeladas:
        a = " ".join((w.get("w") or "").strip() for w in congeladas).strip()
        b = " ".join(w["w"] for w in palavras).strip()
        # a nota congela no máximo 40 palavras (§3.5): comparar o prefixo comum.
        if a and b and not b.startswith(a) and not a.startswith(b):
            fora.append("fala congelada difere da atual")
    if n.get("sid") and take and take["sid"] and n["sid"] != take["sid"]:
        fora.append("sid da nota %s × take recalculado %s" % (n["sid"], take["sid"]))
    return "; ".join(fora) or None


# ────────────────────────────────────────────────────────────────── markdown

def _linha_camadas(cam):
    leg = cam["legenda"]
    if leg.get("paginas"):
        s_leg = "páginas %d–%d" % (leg["paginas"][0], leg["paginas"][1])
    elif leg["paginas"] == []:
        s_leg = "nenhuma página nesta janela"
    else:
        s_leg = ("%d palavra%s (sem partitura.json: página é sem dado)"
                 % (leg["palavras"], "" if leg["palavras"] == 1 else "s"))
    g = cam["grafico"]
    if g["em_codigo"] is not None:
        s_g = "%d em dado, %d em código (%s)" % (g["em_dado"], g["em_codigo"], g["arquivo"])
    elif g["tem_arquivo"]:
        s_g = "%d em dado · em código: não declarado (--componente)" % g["em_dado"]
    else:
        s_g = "sem dado (overlays.json ausente) · em código: não declarado"

    def _l(nome, v):
        if v is None:
            return "%s: sem dado (CLI, sem sidecar)" % nome
        return "%s: %d" % (nome, len(v)) if v else "%s: nenhum" % nome

    return s_leg, s_g, _l("b-roll", cam["broll"]), _l("insert", cam["insert"])


def digest(dados):
    L = []
    r, tl = dados["render"], dados["timeline"]
    n = len(dados["marcacoes"])
    plural = "marcação" if n == 1 else "marcações"
    cab = "## %d %s · %s" % (n, plural, os.path.basename(os.path.abspath(dados["dir"])))
    if r["arquivo"]:
        cab += " · %s" % r["arquivo"]
        if r["fingerprint"]:
            cab += " (%s…)" % r["fingerprint"][:12]
    if r["dur_s"]:
        cab += " · %s s" % _pt(r["dur_s"])
    if r["fps"]:
        cab += " @ %s fps" % _pt(r["fps"], 0 if float(r["fps"]).is_integer() else 3)
    L.append(cab)

    origem = {"timeline_real": "timeline_real (SPEC-05)",
              "medida": "MEDIDA de segs/ (edl.json é v1)",
              "indisponivel": "INDISPONÍVEL — take não atribuído"}[tl["origem"]]
    sub = "   timeline: %s" % origem
    if tl["total_s"]:
        sub += " · %s s (%s frames)" % (_pt(tl["total_s"], 6), tl["total_frames"])
    L.append(sub)
    if dados["eventos"]:
        L.append("   eventos: %s" % ", ".join(dados["eventos"]))
    if r["fingerprint_confere"] is True:
        L.append("   fingerprint do render: CONFERE")
    elif r["fingerprint_confere"] is None:
        L.append("   fingerprint do render: não declarado pela marcação "
                 "(nada foi conferido)")
    for a in dados["avisos"]:
        L.append("   ⚠️ %s" % a)
    L.append("")

    if not dados["marcacoes"]:
        L.append("nenhuma marcação pendente em .preview/pendentes/.")
        return "\n".join(L) + "\n"

    for j, m in enumerate(dados["marcacoes"], 1):
        ini, fim = m["render"]["ini"], m["render"]["fim"]
        fr = m["frames"] or []
        if m["tipo"] == "ponto":
            cabm = "[%d] ponto · %s" % (j, _mmss(ini))
            if fr:
                cabm += " · frame %s" % fr[0]
        else:
            cabm = "[%d] intervalo · %s → %s" % (j, _mmss(ini), _mmss(fim))
            if len(fr) == 2:
                cabm += " · frames %s–%s" % (fr[0], fr[1])
            cabm += " (%s s)" % _pt(fim - ini)
        cabm += " · trilha: %s" % (m["trilha"] or "(não indicada)")
        if m["marcado_invertido"]:
            cabm += " · marcado invertido"
        L.append(cabm)

        t = m["take"]
        if not t:
            L.append("    take  indisponível (%s)" % origem)
        else:
            L.append("    take  %s (%d de %d · i=%d) · %s"
                     % (t["sid"], t["i"] + 1, dados["_total_segs"], t["i"], t["arquivo"])
                     + (" · zoom %s" % _pt(t["zoom"], 2) if t["zoom"] is not None else "")
                     + (" cx %s" % _pt(t["cx"], 3) if t["cx"] is not None else "")
                     + (" · quem: %s" % t["quem"] if t["quem"] else ""))
            if t["atravessa_takes"]:
                L.append("    fonte %s  %s   (início, take %d)"
                         % (t["src"], _pt(t["src_ini"]), t["i"]))
                L.append("          %s  %s   (fim, take %d · %s · %s)"
                         % (t["src_do_fim"], _pt(t["src_fim"]), t["take_do_fim"],
                            t["sid_do_fim"], t["arquivo_do_fim"]))
                L.append("          ⚠️ a marcação cobre %d takes: são %d trechos "
                         "do bruto, não um intervalo contínuo"
                         % (t["take_do_fim"] - t["i"] + 1,
                            t["take_do_fim"] - t["i"] + 1))
            elif m["tipo"] == "ponto":
                L.append("    fonte %s  %s" % (t["src"], _pt(t["src_ini"])))
            else:
                L.append("    fonte %s  %s → %s"
                         % (t["src"], _pt(t["src_ini"]), _pt(t["src_fim"])))
            for f in t["fora_da_janela"]:
                L.append("          ⚠️ coordenada de fonte %s — a marcação passa "
                         "do fim do trecho cortado" % f)
        if m["sid_da_nota"] and t and m["sid_da_nota"] != t["sid"]:
            L.append("          ⚠️ a app gravou sid %s (%s); aqui o take é %s"
                     % (m["sid_da_nota"], m["sid_confianca"], t["sid"]))
        if m["fala"]:
            L.append('    fala  "%s"   (%d palavra%s, captions.json)'
                     % (m["fala"], m["palavras"], "" if m["palavras"] == 1 else "s"))
        else:
            L.append("    fala  (nenhuma palavra da captions.json nesta janela)")
        s_leg, s_g, s_b, s_i = _linha_camadas(m["camadas"])
        L.append("    tela  legenda: %s · gráfico: %s" % (s_leg, s_g))
        L.append("          %s · %s" % (s_b, s_i))
        if m["divergencia_de_contexto"]:
            L.append("          ⚠️ %s" % m["divergencia_de_contexto"])
        for e in m["erros_de_contrato"]:
            L.append("          ⚠️ contrato: %s" % e)
        L.append("    PEDIDO")
        for linha_p in (m["pedido"] or "(vazio)").splitlines() or ["(vazio)"]:
            L.append("          %s" % linha_p)
        L.append("")
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────────────────────────────── ack

def ack(d, eventos):
    destino = os.path.join(dir_preview(d), "aplicados")
    os.makedirs(destino, exist_ok=True)
    movidos = []
    for ev in eventos:
        origem = ev["arquivo"]
        alvo = os.path.join(destino, os.path.basename(origem))
        n = 1
        raiz, ext = os.path.splitext(alvo)
        while os.path.exists(alvo):
            n += 1
            alvo = "%s.%d%s" % (raiz, n, ext)
        shutil.move(origem, alvo)
        movidos.append(alvo)
    return movidos


# ─────────────────────────────────────────────────────────────────────── CLI

def main(argv=None):
    p = argparse.ArgumentParser(
        description="marcações IN/OUT → instrução acionável (SPEC-18 §3.6)")
    p.add_argument("dir", help="diretório da produção")
    p.add_argument("--json", action="store_true", dest="como_json")
    p.add_argument("--ack", action="store_true",
                   help="move os eventos lidos para .preview/aplicados/")
    p.add_argument("--arquivo", default=None)
    p.add_argument("--verificar", action="store_true",
                   help="confere as invariantes do contrato; sai 1 se alguma cair")
    p.add_argument("--componente", default=None,
                   help="o .tsx com os overlays em código desta peça")
    args = p.parse_args(argv)

    d = args.dir.rstrip("/") or "."
    if not os.path.isdir(d):
        print("não é diretório: %s" % d, file=sys.stderr)
        return 2

    eventos = carregar_pendentes(d, args.arquivo)
    dados = coletar(d, eventos, args.componente)
    dados["_total_segs"] = len(edl_io.segmentos(d))

    if args.como_json:
        publico = {k: v for k, v in dados.items() if not k.startswith("_")}
        print(json.dumps(publico, ensure_ascii=False, indent=1))
    else:
        sys.stdout.write(digest(dados))

    codigo = 0
    if args.verificar:
        ruins = [(m["id"], e) for m in dados["marcacoes"] for e in m["erros_de_contrato"]]
        for ident, erro in ruins:
            print("contrato: %s — %s" % (ident, erro), file=sys.stderr)
        print("--verificar: %d nota(s), %d violação(ões)"
              % (len(dados["marcacoes"]), len(ruins)), file=sys.stderr)
        codigo = 1 if ruins else 0

    if args.ack and eventos:
        for alvo in ack(d, eventos):
            print("movido → %s" % alvo, file=sys.stderr)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
