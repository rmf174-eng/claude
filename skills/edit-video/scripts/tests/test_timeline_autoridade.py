#!/usr/bin/env python3
"""Gate único: consumidores derivados obedecem `timeline_real`, nunca Σ(end-start).

O fixture planta 33,333 ms de arredondamento por segmento. A divergência é
obrigatória: se ela sumir, o controle negativo reprova e o teste deixa de poder
distinguir a timeline real da conta proibida.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

AQUI = Path(__file__).resolve().parent
SCRIPTS = AQUI.parent
SKILL = SCRIPTS.parent
PREVIEW = SKILL / "preview"
ESTADO_JS = PREVIEW / "app" / "js" / "estado.js"
sys.path.insert(0, str(SCRIPTS))
import edl_io  # noqa: E402
import palavras  # noqa: E402
import srt  # noqa: E402

falhas: list[str] = []


def ok(nome: str, condicao: bool, detalhe: str) -> bool:
    print("  [%s] %s: %s" % ("PASSOU" if condicao else "FALHOU", nome, detalhe))
    if not condicao:
        falhas.append(nome)
    return bool(condicao)


def carregar_modulo(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixture(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    fps, sr, spf = 30, 48000, 1600
    janelas = [(0.0, 2.0, "Alfa."), (3.0, 5.0, "Beta."), (6.0, 8.0, "Gama.")]
    edl = [
        {"src": "take.mov", "start": ini, "end": fim,
         "fala": fala, "beat": "b%d" % i}
        for i, (ini, fim, fala) in enumerate(janelas)
    ]
    (d / "edl.json").write_text(json.dumps(edl, indent=1), encoding="utf-8")

    tl_segs = []
    acc = 0
    for i, (ini, fim, _fala) in enumerate(janelas):
        frames = 61  # 2,033333 s reais contra 2,000000 s nominais
        tl_segs.append({
            "i": i, "beat": "b%d" % i, "src": "take.mov",
            "src_start": ini, "src_end": fim, "frames": frames,
            "start_frame": acc, "start_s": round(acc / fps, 6),
            "dur_s": round(frames / fps, 6), "start_sample": acc * spf,
            "samples": frames * spf,
        })
        acc += frames
    tl = {
        "schema": edl_io.SCHEMA_TL, "gerado_por": "test_timeline_autoridade.py",
        "gerado_em": "2026-08-16T00:00:00-03:00",
        "edl_fingerprint": edl_io.fingerprint(edl),
        "video": {"width": 160, "height": 90, "fps": 30.0,
                  "fps_num": 30, "fps_den": 1},
        "sample_rate": sr, "samples_por_frame": spf,
        "total_frames": acc, "total_s": round(acc / fps, 6),
        "total_samples": acc * spf, "segments": tl_segs,
    }
    edl_io.conferir_invariantes(tl)
    (d / edl_io.SIDECAR).write_text(json.dumps(tl, indent=1), encoding="utf-8")

    ws = [
        {"word": "alfa", "punctuated_word": "Alfa.", "start": 0.2,
         "end": 0.45, "confidence": 0.99},
        {"word": "beta", "punctuated_word": "Beta.", "start": 3.2,
         "end": 3.45, "confidence": 0.99},
        {"word": "gama", "punctuated_word": "Gama.", "start": 6.2,
         "end": 6.45, "confidence": 0.99},
    ]
    transcript = d / "transcript.json"
    transcript.write_text(json.dumps({"words": ws}), encoding="utf-8")
    nominal = [0.0, 2.0, 4.0, 6.0]
    real = edl_io.fronteiras(tl)
    return edl, tl, transcript, nominal, real


def gate_legendas_srt(d: Path, transcript: Path, tl: dict, nominal: list[float]):
    print("\n1. legendas e SRT")
    mapa = {"take.mov": str(transcript)}
    ws, info = palavras.palavras_no_montado(str(d), transcritos=mapa)
    esperados = [0.2, tl["segments"][1]["start_s"] + 0.2,
                 tl["segments"][2]["start_s"] + 0.2]
    recebidos = [w["ini"] for w in ws]
    ok("mapa de palavras", all(abs(a - b) <= 1e-6 for a, b in zip(recebidos, esperados)),
       "inícios=%s" % recebidos)

    _paths, side, cues = srt.gerar(
        str(d), transcritos=mapa, perfil_off=True,
        regra={"dur_min_s": 0.1, "dur_max_s": 2.0, "gap_quebra_s": 0.1})
    inicios = [c["ini"] for c in cues]
    ok("SRT", len(cues) == 3
       and all(abs(a - b) <= 0.001 for a, b in zip(inicios, esperados))
       and abs(side["total_s"] - tl["total_s"]) <= 1e-6,
       "%d cues, inícios=%s, total=%.6fs" % (len(cues), inicios, side["total_s"]))

    # Sem timeline, os dois consumidores devem abortar em vez de ressuscitar a EDL.
    sidecar = d / edl_io.SIDECAR
    guardado = d / (edl_io.SIDECAR + ".guardado")
    sidecar.rename(guardado)
    abortos = 0
    try:
        for fn in (
                lambda: palavras.palavras_no_montado(str(d), transcritos=mapa),
                lambda: srt.gerar(str(d), transcritos=mapa, perfil_off=True)):
            try:
                fn()
            except SystemExit:
                abortos += 1
    finally:
        guardado.rename(sidecar)
    ok("sem fallback nominal", abortos == 2, "%d/2 consumidores abortaram" % abortos)

    ini_nominal_terceira = nominal[2] + 0.2
    ok("controle negativo das legendas", abs(recebidos[2] - ini_nominal_terceira) > 0.05,
       "real=%.6f, nominal=%.6f, deriva=%.1fms"
       % (recebidos[2], ini_nominal_terceira,
          (recebidos[2] - ini_nominal_terceira) * 1000))


def gate_qc(d: Path, real: list[float], nominal: list[float]):
    print("\n2. QC de emendas")
    qc = carregar_modulo("qc_emendas_timeline_autoridade",
                         SCRIPTS / "qc-emendas-asr.py")
    comandos = []
    respostas = iter([("alfa beta", {}), ("beta gama", {})])
    qc.asr = lambda _raw: next(respostas)
    run_original = qc.subprocess.run
    qc.subprocess.run = lambda cmd, **_kw: (comandos.append(list(cmd))
                                            or SimpleNamespace(stdout=b"mp3"))
    argv, cwd = list(sys.argv), os.getcwd()
    codigo = None
    try:
        sys.argv = [str(SCRIPTS / "qc-emendas-asr.py"), str(d), "--margem", "0.5"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                qc.main()
            except SystemExit as exc:
                codigo = int(exc.code or 0)
    finally:
        qc.subprocess.run = run_original
        sys.argv = argv
        os.chdir(cwd)
    centros = []
    for cmd in comandos:
        ini = float(cmd[cmd.index("-ss") + 1])
        dur = float(cmd[cmd.index("-t") + 1])
        centros.append(ini + dur / 2.0)
    ok("fronteiras do QC", codigo == 0 and len(centros) == 2
       and all(abs(a - b) <= 1e-6 for a, b in zip(centros, real[1:-1])),
       "exit=%s, centros=%s" % (codigo, [round(x, 6) for x in centros]))
    ok("controle negativo do QC",
       max(abs(a - b) for a, b in zip(centros, nominal[1:-1])) > 0.05,
       "deriva máxima contra Σ(end-start)=%.1fms"
       % (max(abs(a - b) for a, b in zip(centros, nominal[1:-1])) * 1000))


def gate_strip(d: Path, tl: dict, nominal: list[float]):
    print("\n3. filmstrip")
    servidor = carregar_modulo("servidor_timeline_autoridade", PREVIEW / "servidor.py")
    video = d / "v1-montado.mp4"
    video.write_bytes(b"fixture: sonda substituida")
    sonda_original, iniciar_original = servidor.sonda, servidor._iniciar
    try:
        servidor.sonda = lambda _p: {
            "dur": tl["total_s"], "w": 160, "h": 90, "fps": 30.0,
            "rot": 0, "tem_audio": False, "mtime_ns": video.stat().st_mtime_ns,
            "bytes": video.stat().st_size,
        }
        servidor._iniciar = lambda _chave, _tipo, _total, _alvo: {
            "estado": "gerando", "feito": 0, "erro": None}
        midia = servidor.garantir_midia(d, video, 90)
    finally:
        servidor.sonda, servidor._iniciar = sonda_original, iniciar_original
    esperado = round(tl["total_s"] / servidor.N_MIN, 6)
    nominal_i = nominal[-1] / servidor.N_MIN
    intervalo = midia["strip"]["intervalo"]
    ok("strip usa duração do render sondado", abs(intervalo - esperado) <= 1e-6,
       "intervalo=%.6fs para render=%.6fs" % (intervalo, midia["dur"]))
    ok("controle negativo do strip", abs(intervalo - nominal_i) > 0.003,
       "real=%.6f, nominal=%.6f" % (intervalo, nominal_i))


HARNESS_JS = r"""
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[1]).href + '?autoridade');
const p = JSON.parse(process.argv[2]);
const afirmar = (c, m) => { if (!c) throw new Error(m); };
const perto = (a, b) => Math.abs(a - b) <= 1e-6;
const comTopo = {edl: p.edl, timeline_real: p.tl, midia: {dur: p.tl.total_s}};
const segs = mod.segmentosDe(comTopo);
afirmar(segs.length === p.tl.segments.length, 'preview perdeu segmentos reais');
afirmar(segs.every((s, i) => perto(s.ini, p.tl.segments[i].start_s)
  && perto(s.dur, p.tl.segments[i].dur_s) && s.exato),
  'preview nao usou start_s/dur_s da timeline_real');
const dur = mod.duracaoDe(comTopo, segs, null);
afirmar(dur.exata && perto(dur.dur, p.tl.total_s), 'duracao nao veio da timeline_real');

// EDL v1: servidor pode trazer a timeline dentro do estado gerado por estado.py.
const noEstado = {edl: p.edl, estado: {timeline_real: p.tl}, midia: {dur: p.tl.total_s}};
afirmar(mod.segmentosDe(noEstado).every((s, i) => perto(s.ini, p.tl.segments[i].start_s)),
  'preview ignorou timeline_real do estado para EDL v1');

const sem = {edl: p.edl, midia: {dur: p.tl.total_s}};
afirmar(mod.segmentosDe(sem).length === 0,
  'sem timeline_real o preview ressuscitou blocos por soma nominal');
const durSem = mod.duracaoDe(sem, [], null);
afirmar(!durSem.exata && perto(durSem.dur, p.tl.total_s),
  'sem timeline_real a regua deve usar o render medido');
const deriva = Math.abs(segs[2].ini - p.nominal[2]);
afirmar(deriva > 0.05, 'controle negativo sem deriva suficiente');
console.log(JSON.stringify({segmentos: segs.length, total: dur.dur, deriva_ms: deriva * 1000}));
"""


def gate_preview(edl: list[dict], tl: dict, nominal: list[float]):
    print("\n4. preview")
    node = shutil.which("node")
    if not node:
        return ok("Node disponível", False, "necessário para executar estado.js real")
    r = subprocess.run(
        [node, "--input-type=module", "-e",
         HARNESS_JS, str(ESTADO_JS), json.dumps({"edl": edl, "tl": tl,
                                                 "nominal": nominal})],
        capture_output=True, text=True)
    ok("estado.js", r.returncode == 0,
       r.stdout.strip() if r.returncode == 0 else r.stderr.strip()[-400:])


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="timeline-autoridade-"))
    try:
        edl, tl, transcript, nominal, real = fixture(base)
        deriva = max(abs(a - b) for a, b in zip(real, nominal))
        print("controle: timeline real %.6fs, Σ(end-start) %.6fs, deriva %.1fms"
              % (real[-1], nominal[-1], deriva * 1000))
        ok("controle negativo tem dentes", deriva > 0.09,
           "%.1fms acumulados" % (deriva * 1000))
        gate_legendas_srt(base, transcript, tl, nominal)
        gate_qc(base, real, nominal)
        gate_strip(base, tl, nominal)
        gate_preview(edl, tl, nominal)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n%s" % ("TUDO PASSOU" if not falhas else "FALHOU: " + ", ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
