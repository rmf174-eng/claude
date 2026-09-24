#!/usr/bin/env python3
"""medir-ref — mede UMA referência e grava `<corpus>/medicoes/<id>.json`.

É o insumo do `agregar.py` e o cache: remedir custa Gemini, agregar não custa
nada. Contrato `benchmark.medicao-ref/v1`.

O que ele roda, nesta ordem (§3.9 da SPEC-23):

    1. ingestão      URL → video-download/scripts/download.sh · arquivo → usa no lugar
    2. transcrição   OPT-IN (`--transcrever`): transcribe.sh, ou transcribe-longo.sh
                     acima de 3600 s (o Deepgram trunca >1h e responde 200)
    3. ritmo         model-edit/scripts/ritmo.py --fps 8 --json  (30 estoura em peça longa)
    4. tipografia    model-edit/scripts/tipografia.py --fps 2 --json (+ --so-claro em
                     cenário quente, que é o limite medido em model-edit/SKILL.md:74-78)
    5. som           ffmpeg ebur128 (I/LRA/TP) + RMS em janelas de 100 ms para piso p5 e
                     fala p80. NUNCA `silencedetect`: dá "zero pausas" em peça com trilha
    6. semântica     content-analysis/scripts/deep-edit-analysis.py (Gemini) — o único
                     passo que custa dinheiro, e o único com amostragem

AS TRÊS GUARDAS, que são código e não aviso na doc:

  (a) `cortes.py` mede a PÓS, não a montagem. `frac_camada = tipos["troca de camada"]
      / cortes`; >= 0,40 marca a montagem como suspeita (ref-C dá 0,78 e dispara;
      as 4 VSLs dão 0,027/0,011/0,009/0,086 e não disparam).
  (b) `reframe.py` NÃO roda no automático e o extrator NUNCA emite "tendência de zoom":
      correlação 0,55–0,65 em talking-head de mão solta, com uma falsa tendência
      1,0→1,47. `plano.gramatica` só sai medido via `--override`.
  (c) posição e cor vêm SEMPRE do pixel; o Gemini erra os dois com confiança alta
      (85% de altura contra 56% medidos; #FFFF00 contra #F14418).

AMOSTRAGEM SEMÂNTICA (custo):
    dur <= 360 s  → deep-edit na peça inteira
    dur >  360 s  → uma janela de 90 s por bloco declarado, recortada com -c copy
Todo campo derivado de um deep-edit amostrado carrega a cobertura em segundos: o
`n` nunca mente sobre o que foi visto.

Uso:
    medir-ref.py <url|arquivo> --id <id> --objetivo <o> [--temperatura <t>]
        [--perfil <p>] [--marcos 0:00-1:22=abertura ...] [--dir <corpus>]
        [--refazer] [--sem-semantico] [--transcrever]
        [--ritmo <ritmo.json>] [--tipografia <tipografia.json>]
        [--deep-edit [<bloco>=]<deep-edit.json>]... [--override <override.json>]

`--ritmo/--tipografia/--deep-edit` reusam medição JÁ FEITA em vez de re-rodar —
é a idempotência um nível acima, e é como um corpus de peças longas se monta sem
decodificar tudo de novo.

Saída: o caminho do `medicoes/<id>.json` no stdout; logs no stderr.
exit 0 ok · 1 erro de medição · 2 erro de uso
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np

CONTRATO = "benchmark.medicao-ref/v1"
VERSAO = 1

AQUI = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(os.path.dirname(AQUI))          # .../ilha/skills
MODEL_EDIT = os.path.join(SKILLS, "model-edit", "scripts")
VIDEO_DL = os.path.join(SKILLS, "video-download", "scripts")
TRANSCRIBE = os.path.join(SKILLS, "transcribe", "scripts")
SCHEMA = os.path.join(os.path.dirname(AQUI), "references", "_schema.json")

# `content-analysis` não é skill da ilha: fica em .claude/skills/ na instalação
# atual e pode ser apontada por env quando o layout for outro.
DEEP_EDIT = os.environ.get("BENCH_DEEP_EDIT_SCRIPT") or os.path.join(
    os.getcwd(), ".claude", "skills", "content-analysis", "scripts",
    "deep-edit-analysis.py")

RMS_JANELA_S = 0.100      # física da medição de piso/fala, não formato de peça
RMS_SR = 16000            # taxa da ANÁLISE de áudio (não é o sr da peça)


def log(*a):
    print(">>", *a, file=sys.stderr)


def rel(caminho):
    """Caminho relativo ao cwd quando dá — artefato deste repo não carrega
    `/Users/<alguém>/` (§9.11: nada de caminho absoluto em script ou artefato)."""
    try:
        r = os.path.relpath(caminho, os.getcwd())
        return caminho if r.startswith("..") else r
    except ValueError:
        return caminho


def limiares():
    with open(SCHEMA, encoding="utf-8") as fh:
        return json.load(fh)["x_limiares"]


def rodar(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r


def ffprobe_dur(video):
    out = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video]).stdout.strip()
    return float(out) if out else 0.0


# Aspectos usuais, para DESCREVER a referência (é o `formato_das_refs`, que é
# descritivo). Nada aqui configura render: formato de peça é do perfil (SPEC-00).
ASPECTOS = [("9:16", 9 / 16), ("4:5", 4 / 5), ("1:1", 1.0), ("5:4", 5 / 4),
            ("4:3", 4 / 3), ("3:2", 3 / 2), ("16:9", 16 / 9), ("2.39:1", 2.39)]


def ffprobe_aspecto(video):
    out = rodar(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate",
                 "-of", "csv=p=0:s=x", video]).stdout.strip()
    try:
        w, h, rate = out.split("x")[0], out.split("x")[1], out.split("x")[2]
        num, _, den = rate.partition("/")
        fps = round(float(num) / float(den or 1), 3)
        r = int(w) / int(h)
        nome, erro = min(((n, abs(r - v) / v) for n, v in ASPECTOS), key=lambda t: t[1])
        if erro > 0.02:
            from math import gcd
            g = gcd(int(w), int(h)) or 1
            nome = f"{int(w)//g}:{int(h)//g}"
        return nome, fps
    except (ValueError, IndexError, ZeroDivisionError):
        return None, None


# ------------------------------------------------------------------- marcos
def parse_marcos(specs, dur):
    """'0:00-1:22=abertura' → [{rotulo, ini, fim}] — mesmo formato do ritmo.py:54-66."""
    def seg(t):
        p = [float(x) for x in t.split(":")]
        return p[0] * 60 + p[1] if len(p) == 2 else p[0]
    out = []
    for s in specs or []:
        faixa, _, rotulo = s.partition("=")
        ini, _, fim = faixa.partition("-")
        out.append({"rotulo": rotulo or faixa, "ini": seg(ini),
                    "fim": seg(fim) if fim else dur})
    return out


# -------------------------------------------------------------------- passos
def passo_ritmo(video, marcos_cli, reuso):
    if reuso:
        with open(reuso, encoding="utf-8") as fh:
            d = json.load(fh)
        log(f"ritmo: reusando {reuso}")
    else:
        cmd = [sys.executable, os.path.join(MODEL_EDIT, "ritmo.py"), video,
               "--fps", "8", "--json"]
        if marcos_cli:
            cmd += ["--marcos"] + list(marcos_cli)
        log("ritmo: ritmo.py --fps 8")
        r = rodar(cmd)
        if r.returncode != 0:
            sys.exit(f"ritmo.py falhou: {r.stderr[-500:]}")
        d = json.loads(r.stdout)
    tipos = d.get("tipos", {})
    cortes = d.get("cortes", 0) or 0
    frac = round(tipos.get("troca de camada", 0) / cortes, 4) if cortes else None
    return {
        "cortes": cortes,
        "cortes_por_min": d.get("cortes_por_min"),
        "plano_medio_s": d.get("plano_medio_s"),
        "plano_mediano_s": d.get("plano_mediano_s"),
        "tipos": tipos,
        "frac_camada": frac,
        "qualidade": "ok",
    }, (d.get("marcos") or [])


def passo_tipografia(video, reuso):
    if reuso:
        with open(reuso, encoding="utf-8") as fh:
            d = json.load(fh)
        log(f"tipografia: reusando {reuso}")
        return d, "reuso"
    passadas = []
    for extra, nome in (([], "padrao"), (["--so-claro"], "so-claro")):
        cmd = [sys.executable, os.path.join(MODEL_EDIT, "tipografia.py"), video,
               "--fps", "2", "--json"] + extra
        log(f"tipografia: tipografia.py --fps 2 {' '.join(extra)}".rstrip())
        r = rodar(cmd)
        if r.returncode != 0:
            log(f"tipografia ({nome}) falhou: {r.stderr[-300:]}")
            continue
        d = json.loads(r.stdout)
        passadas.append((nome, d))
        # o limite medido: em cenário quente e saturado o detector elege o
        # cenário e não devolve cor de glifo. Aí a 2ª passada é obrigatória.
        if (d.get("legenda") or {}).get("cor_base"):
            return d, nome
    if not passadas:
        return None, None
    return passadas[0][1], passadas[0][0]


def passo_som(video):
    """ebur128 (I/LRA/TP) + RMS em janelas de 100 ms, numa passada só de decode."""
    log("som: ffmpeg ebur128 + RMS 100ms")
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", video, "-map", "0:a:0",
         "-af", f"ebur128=peak=true,aresample={RMS_SR}", "-ac", "1",
         "-f", "s16le", "-"],
        capture_output=True)
    if p.returncode != 0 or not p.stdout:
        log("som: sem faixa de áudio ou ffmpeg falhou")
        return {}
    err = p.stderr.decode("utf-8", "replace")

    def cap(rx):
        m = re.search(rx, err)
        return float(m.group(1)) if m else None

    resumo = err.split("Summary:")[-1]
    I = LRA = TP = None
    m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+)\s*LUFS", resumo)
    I = float(m.group(1)) if m else cap(r"I:\s*(-?[\d.]+)\s*LUFS")
    m = re.search(r"Loudness range:\s*\n\s*LRA:\s*(-?[\d.]+)\s*LU", resumo)
    LRA = float(m.group(1)) if m else None
    m = re.search(r"True peak:\s*\n\s*Peak:\s*(-?[\d.]+)\s*dBFS", resumo)
    TP = float(m.group(1)) if m else None

    x = np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768.0
    w = int(RMS_SR * RMS_JANELA_S)
    n = len(x) // w
    if n < 2:
        return {"lufs_integrado": I, "lra_lu": LRA, "true_peak_dbtp": TP}
    r = np.sqrt((x[:n * w].reshape(n, w) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(r, 1e-6))
    return {
        "lufs_integrado": I, "lra_lu": LRA, "true_peak_dbtp": TP,
        "piso_p5_db": round(float(np.percentile(db, 5)), 1),
        "fala_p80_db": round(float(np.percentile(db, 80)), 1),
        "dinamica_db": round(float(np.percentile(db, 80) - np.percentile(db, 5)), 1),
        "janelas_rms": int(n),
    }


# ------------------------------------------------------------------ semântica
def _deep_de(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def _rodar_deep(dir_video, quieto=False):
    if not os.path.isfile(DEEP_EDIT):
        log(f"deep-edit-analysis.py não encontrado em {DEEP_EDIT} — pulando semântica")
        return None
    saida = os.path.join(dir_video, "deep-edit.json")
    if os.path.isfile(saida) and os.path.getsize(saida) > 0:
        return saida
    log(f"deep-edit: Gemini em {dir_video} (custa dinheiro)")
    r = rodar([sys.executable, DEEP_EDIT, dir_video])
    if r.returncode != 0:
        log(f"deep-edit falhou: {r.stderr[-400:]}")
        return None
    return saida if os.path.isfile(saida) else None


def _recorte(video, ini, dur, destino):
    os.makedirs(destino, exist_ok=True)
    alvo = os.path.join(destino, "video.mp4")
    if os.path.isfile(alvo) and os.path.getsize(alvo) > 0:
        return alvo
    r = rodar(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(ini),
               "-t", str(dur), "-i", video, "-c", "copy", alvo])
    if r.returncode != 0 or not os.path.isfile(alvo):
        log(f"recorte falhou em {ini}s: {r.stderr[-200:]}")
        return None
    return alvo


def coletar_semantica(video, dur, marcos, deep_cli, sem_semantico, corpus_dir, ref_id):
    """Devolve (amostragem, blocos) com blocos = [{rotulo, ini, fim, deep, arquivo}]."""
    lim = limiares()
    if deep_cli:
        blocos = []
        for spec in deep_cli:
            rotulo, _, caminho = spec.rpartition("=")
            if not caminho:
                caminho = spec
            rotulo = rotulo or "peca-inteira"
            if not os.path.isfile(caminho):
                sys.exit(f"--deep-edit: {caminho} não existe")
            d = _deep_de(caminho)
            mk = next((m for m in marcos if m["rotulo"] == rotulo), None)
            ini = mk["ini"] if mk else 0.0
            blocos.append({"rotulo": rotulo, "ini": ini,
                           "fim": ini + (d.get("duracao_s") or 0.0),
                           "deep": d, "arquivo": caminho})
        modo = "peca-inteira" if (len(blocos) == 1 and blocos[0]["rotulo"] == "peca-inteira") \
            else "blocos"
        return _amostragem(modo, blocos, dur), blocos

    vizinho = os.path.join(os.path.dirname(os.path.abspath(video)), "deep-edit.json")
    if os.path.isfile(vizinho) and os.path.getsize(vizinho) > 0:
        log(f"deep-edit: reusando {vizinho} (idempotência — Gemini não é chamado)")
        d = _deep_de(vizinho)
        blocos = [{"rotulo": "peca-inteira", "ini": 0.0,
                   "fim": d.get("duracao_s") or dur, "deep": d, "arquivo": vizinho}]
        return _amostragem("peca-inteira", blocos, dur), blocos

    if sem_semantico:
        log("semântica: pulada (--sem-semantico)")
        return {"pixel": "peca-inteira", "semantico": "nenhum", "janelas_s": [],
                "cobertura_semantica_pct": 0.0}, []

    if dur <= lim["amostragem_semantica_peca_inteira_ate_s"]:
        arq = _rodar_deep(os.path.dirname(os.path.abspath(video)))
        if not arq:
            return {"pixel": "peca-inteira", "semantico": "nenhum", "janelas_s": [],
                    "cobertura_semantica_pct": 0.0}, []
        d = _deep_de(arq)
        blocos = [{"rotulo": "peca-inteira", "ini": 0.0,
                   "fim": d.get("duracao_s") or dur, "deep": d, "arquivo": arq}]
        return _amostragem("peca-inteira", blocos, dur), blocos

    janela = lim["amostragem_semantica_janela_s"]
    alvos = marcos or [{"rotulo": "peca-inteira", "ini": 0.0, "fim": dur}]
    blocos = []
    base = os.path.join(corpus_dir, "trechos")
    for mk in alvos:
        largura = mk["fim"] - mk["ini"]
        d_janela = min(janela, largura)
        ini = mk["ini"] + max(0.0, (largura - d_janela) / 2)
        destino = os.path.join(base, f"{ref_id}-{mk['rotulo']}")
        v = _recorte(video, round(ini, 2), round(d_janela, 2), destino)
        if not v:
            continue
        arq = _rodar_deep(destino)
        if not arq:
            continue
        d = _deep_de(arq)
        blocos.append({"rotulo": mk["rotulo"], "ini": round(ini, 2),
                       "fim": round(ini + (d.get("duracao_s") or d_janela), 2),
                       "deep": d, "arquivo": arq})
    return _amostragem("blocos" if blocos else "nenhum", blocos, dur), blocos


def _amostragem(modo, blocos, dur):
    # o `duracao_s` do deep-edit é declarado pelo modelo e às vezes passa do fim
    # real do recorte; a cobertura é limitada pela peça, nunca >100%.
    janelas = [[round(b["ini"], 2), round(min(b["fim"], dur), 2)] for b in blocos]
    cob = sum(max(0.0, min(b["fim"], dur) - b["ini"]) for b in blocos)
    return {"pixel": "peca-inteira", "semantico": modo, "janelas_s": janelas,
            "cobertura_semantica_pct": round(min(100.0, 100 * cob / dur), 1) if dur else 0.0,
            "cobertura_semantica_s": round(cob, 1)}


def _moda(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    cont = {}
    for v in vals:
        cont[v] = cont.get(v, 0) + 1
    return max(sorted(cont.items(), key=lambda kv: str(kv[0])), key=lambda kv: kv[1])[0]


def consolidar_semantica(blocos):
    """N deep-edit (peça inteira ou um por bloco) → os campos de `medido`."""
    if not blocos:
        return {}, {}, {}
    total_s = sum(max(0.0, b["fim"] - b["ini"]) for b in blocos) or None
    elementos = sum(len((b["deep"].get("timeline_elementos") or [])) for b in blocos)
    punch = sum(len((b["deep"].get("punch_ins") or [])) for b in blocos)
    recursos = sorted({e.get("tipo") for b in blocos
                       for e in (b["deep"].get("timeline_elementos") or [])
                       if e.get("tipo")})
    simult = [(b["deep"].get("densidade") or {}).get("max_simultaneos") for b in blocos]
    janela = [(b["deep"].get("densidade") or {}).get("maior_janela_sem_elemento_s")
              for b in blocos]
    legs = [b["deep"].get("legendas") or {} for b in blocos]
    trilhas = [(b["deep"].get("trilha") or {}).get("tipo") for b in blocos]
    sfx = sorted({e.get("tipo") for b in blocos
                  for e in (b["deep"].get("sfx_eventos") or []) if e.get("tipo")})

    grafismo = {
        "elementos_total": elementos,
        "elementos_por_10s": round(elementos / total_s * 10, 2) if total_s else None,
        "max_simultaneos": max([s for s in simult if s is not None], default=None),
        "maior_janela_sem_elemento_s": max([j for j in janela if j is not None], default=None),
        "recursos": recursos,
    }
    plano = {"punch_ins_por_min": round(punch / total_s * 60, 2) if total_s else None}
    legenda = {
        "estilo": _moda([l.get("estilo") for l in legs]),
        "caixa_alta": _moda([l.get("caixa_alta") for l in legs]),
    }
    som = {"trilha_tipo": _moda(trilhas), "sfx": sfx}
    por_bloco = {}
    for b in blocos:
        if b["rotulo"] == "peca-inteira":
            continue          # peça inteira não é bloco: seria por_bloco de um bloco só
        d = b["deep"]
        dur_b = max(0.0, b["fim"] - b["ini"]) or None
        n_el = len(d.get("timeline_elementos") or [])
        por_bloco[b["rotulo"]] = {
            "elementos_por_10s": round(n_el / dur_b * 10, 2) if dur_b else None,
            "max_simultaneos": (d.get("densidade") or {}).get("max_simultaneos"),
        }
    regras = [r for b in blocos
              for r in ((b["deep"].get("sistema_composicao") or {}).get("regras_observadas") or [])]
    return {"grafismo": grafismo, "plano": plano, "legenda": legenda, "som": som}, \
        por_bloco, {"regras_observadas": regras,
                    "deep_edit": [rel(b["arquivo"]) for b in blocos],
                    "paleta_gemini": sorted({p.get("hex_aprox") for b in blocos
                                             for p in (b["deep"].get("paleta") or [])
                                             if p.get("hex_aprox")})}


# ---------------------------------------------------------------- transcrição
def passo_transcricao(video, dur):
    script = "transcribe-longo.sh" if dur > 3600 else "transcribe.sh"
    log(f"transcrição: {script} (peça de {dur/60:.1f} min)")
    r = rodar(["bash", os.path.join(TRANSCRIBE, script), video])
    if r.returncode != 0:
        log(f"{script} falhou: {r.stderr[-300:]}")
        return {}
    alvo = os.path.join(os.path.dirname(os.path.abspath(video)), "transcript.json")
    if not os.path.isfile(alvo):
        return {}
    with open(alvo, encoding="utf-8") as fh:
        t = json.load(fh)
    try:
        alt = t["results"]["channels"][0]["alternatives"][0]
        palavras = alt.get("words") or []
        texto = alt.get("transcript") or ""
    except (KeyError, IndexError, TypeError):
        return {}
    if not palavras or not dur:
        return {}
    return {"palavras": len(palavras),
            "palavras_por_min": round(len(palavras) / dur * 60, 1),
            "chars_por_segundo": round(len(texto) / dur, 2)}


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", help="URL ou caminho de vídeo")
    ap.add_argument("--id", required=True)
    ap.add_argument("--objetivo", required=True,
                    choices=["venda", "educativo", "autoridade", "captura",
                             "bastidor", "anuncio"])
    ap.add_argument("--temperatura", default="na",
                    choices=["frio-total", "frio", "morno", "quente", "na"])
    ap.add_argument("--perfil", default=None, help="slug de perfil de peça (SPEC-00)")
    ap.add_argument("--marcos", nargs="*", default=[])
    ap.add_argument("--dir", default="corpus", dest="corpus")
    ap.add_argument("--refazer", action="store_true")
    ap.add_argument("--sem-semantico", action="store_true", dest="sem_semantico")
    ap.add_argument("--transcrever", action="store_true",
                    help="roda o Deepgram e deriva ritmo de fala (custa dinheiro; off por default)")
    ap.add_argument("--ritmo", default=None, help="reusa um ritmo.py --json já calculado")
    ap.add_argument("--tipografia", default=None, help="reusa um tipografia.py --json já calculado")
    ap.add_argument("--deep-edit", nargs="*", default=[], dest="deep_edit",
                    help="[<bloco>=]<deep-edit.json>, repetível — reusa semântica já calculada")
    ap.add_argument("--override", default=None,
                    help="override.json com o que só sai à mão (ex.: plano.gramatica)")
    a = ap.parse_args()

    corpus = os.path.abspath(a.corpus)
    destino = os.path.join(corpus, "medicoes", f"{a.id}.json")
    if os.path.isfile(destino) and not a.refazer:
        log(f"medição já existe (use --refazer): {destino}")
        print(destino)
        return
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    # 1. ingestão
    url = None
    if re.match(r"^https?://", a.ref):
        url = a.ref
        dir_ref = os.path.join(corpus, "refs", a.id)
        os.makedirs(dir_ref, exist_ok=True)
        video = os.path.join(dir_ref, "video.mp4")
        if not os.path.isfile(video):
            log(f"download: {url}")
            r = rodar(["bash", os.path.join(VIDEO_DL, "download.sh"), url, dir_ref])
            if r.returncode != 0 or not os.path.isfile(video):
                sys.exit(f"download.sh falhou: {r.stderr[-500:]}")
    else:
        video = os.path.abspath(a.ref)
        if os.path.isdir(video):
            video = os.path.join(video, "video.mp4")
        if not os.path.isfile(video):
            sys.exit(f"erro: {video} não existe")

    dur = ffprobe_dur(video)
    if dur <= 0:
        sys.exit(f"erro: duração 0 em {video}")
    aspecto, fps_fonte = ffprobe_aspecto(video)
    marcos = parse_marcos(a.marcos, dur)
    avisos = []

    # 3/4/5
    montagem, marcos_ritmo = passo_ritmo(video, a.marcos, a.ritmo)
    lim = limiares()
    if montagem["frac_camada"] is not None and montagem["frac_camada"] >= lim["frac_camada_suspeita"]:
        montagem["qualidade"] = "suspeita"
        avisos.append(
            "frac_camada=%.3f >= %.2f: o cortes.py está contando troca de camada como corte "
            "(mede a pós, não a montagem). Ritmo desta ref não é confiável sem fiducial fixo."
            % (montagem["frac_camada"], lim["frac_camada_suspeita"]))

    tip, passada = passo_tipografia(video, a.tipografia)
    legenda = {}
    if tip:
        L = tip.get("legenda") or {}
        legenda = {
            "y_centro_pct": L.get("y_centro_pct"),
            # SPEC-41: o nome portátil primeiro, o legado como queda. Uma medição
            # antiga (gravada antes desta spec) continua entrando; uma nova entra
            # pelo campo que não carrega canvas no nome. Converter aqui em vez de
            # exigir regravação é o que mantém o corpus já medido utilizável.
            "altura_glifo_pct": (L.get("altura_glifo_pct")
                                 if L.get("altura_glifo_pct") is not None
                                 else (round(L["altura_glifo_px_1920"] / 1920 * 100, 2)
                                       if L.get("altura_glifo_px_1920") is not None else None)),
            "altura_glifo_px_1920": L.get("altura_glifo_px_1920"),
            "cor_base": L.get("cor_base"),
            "cor_destaque": L.get("cor_destaque"),
            "presente_pct_do_tempo": L.get("presente_pct_do_tempo"),
            "largura_usada_pct": L.get("largura_usada_pct"),
            "s_por_pagina": (tip.get("cadencia") or {}).get("s_por_pagina"),
            "passada": passada,
        }
        if not L.get("cor_base"):
            avisos.append("tipografia.py não devolveu cor de glifo (cenário quente/saturado, "
                          "limite medido em model-edit/SKILL.md:74-78): cor fica em faltou[], "
                          "não é preenchida pelo Gemini (§9.5)")
    else:
        avisos.append("tipografia.py não mediu esta referência")

    som = passo_som(video)

    # 6. semântica
    amostragem, blocos = coletar_semantica(video, dur, marcos, a.deep_edit,
                                           a.sem_semantico, corpus, a.id)
    sem, por_bloco_sem, semantico = consolidar_semantica(blocos)
    if amostragem["semantico"] == "blocos":
        avisos.append("semântica amostrada: %.1f s de %.1f s (%.1f%%) em %d janela(s)"
                      % (amostragem.get("cobertura_semantica_s", 0), dur,
                         amostragem["cobertura_semantica_pct"], len(blocos)))

    legenda.update({k: v for k, v in (sem.get("legenda") or {}).items() if v is not None})
    grafismo = sem.get("grafismo", {})
    som.update({k: v for k, v in (sem.get("som") or {}).items() if v is not None})
    plano = dict(sem.get("plano", {}))

    # guarda (b): gramática de plano NUNCA sai do automático
    plano["gramatica"] = None
    plano["nota"] = ("gramatica nao medida: reframe.py nao converge em talking-head de mao "
                     "solta (correlacao 0,55-0,65) — guarda §3.9b. Para medir: reframe.py à "
                     "mão em >=3 pares de planos, todas as correlacoes >=0,75, e o resultado "
                     "colado num --override")
    if a.override:
        with open(a.override, encoding="utf-8") as fh:
            ov = json.load(fh)
        g = (ov.get("plano") or {}).get("gramatica")
        corr = (ov.get("plano") or {}).get("correlacoes") or []
        if g and len(corr) >= 3 and min(corr) >= 0.75:
            plano["gramatica"] = g
            plano["nota"] = "gramatica de override: %d pares, correlacao minima %.2f" % (
                len(corr), min(corr))
        elif g:
            avisos.append("--override traz plano.gramatica sem >=3 correlações >=0,75: recusado")

    por_bloco = {}
    for mk in marcos_ritmo:
        por_bloco.setdefault(mk["rotulo"], {}).update({
            "cortes_por_min": round(mk["por_min"], 2) if mk.get("por_min") is not None else None,
            "plano_medio_s": round(mk["plano_medio"], 2) if mk.get("plano_medio") else None,
        })
    for rot, v in por_bloco_sem.items():
        por_bloco.setdefault(rot, {}).update(v)

    fala = passo_transcricao(video, dur) if a.transcrever else {}

    med = {
        "contrato": CONTRATO,
        "versao_medidor": VERSAO,
        "id": a.id,
        "fonte": {"caminho": rel(video),
                  "url": url, "dur_s": round(dur, 2),
                  "aspecto": aspecto, "fps_fonte": fps_fonte},
        "declarado": {"objetivo": a.objetivo, "temperatura": a.temperatura,
                      "perfil_sugerido": a.perfil},
        "marcos": marcos,
        "amostragem": amostragem,
        "medido": {
            "montagem": montagem,
            "legenda": legenda,
            "grafismo": grafismo,
            "som": som,
            "plano": plano,
            "fala": fala,
        },
        "por_bloco": por_bloco,
        "semantico": semantico,
        "avisos": avisos,
    }

    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(med, fh, ensure_ascii=False, indent=2)
    for av in avisos:
        log("aviso: " + av)
    log(f"medido: {a.id} · {dur/60:.1f} min · cortes/min {montagem['cortes_por_min']} · "
        f"cobertura semântica {amostragem['cobertura_semantica_pct']}%")
    print(destino)


if __name__ == "__main__":
    main()
