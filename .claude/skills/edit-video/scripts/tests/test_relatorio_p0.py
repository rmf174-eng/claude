#!/usr/bin/env python3
"""Regressões P0 do relatório técnico, com montagem de mídia sintética real.

Casos cobertos:
  1. plano J-cut ausente;
  2. `seg003.mp4.tmp-22.mp4` ignorado pelo consumidor de áudio;
  3. falha na validação do MP4 temporário antes do rename;
  4. decisão J-cut `aplicar: false` sem campos de plano ativo;
  5. plano ativo com fps divergente;
  6. plano ativo válido.

O teste usa um take de 2 s em 160x90 e não toca material de produção.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
SKILL = os.path.dirname(SCRIPTS)
MONTAR = os.path.join(SCRIPTS, "montar.sh")
QC_EMENDAS = os.path.join(SCRIPTS, "qc-emendas-asr.py")
sys.path.insert(0, SCRIPTS)
import edl_io  # noqa: E402
import jcut  # noqa: E402

falhas = []


def ok(nome, cond, detalhe):
    print("  [%s] %s: %s" % ("PASSOU" if cond else "FALHOU", nome, detalhe))
    if not cond:
        falhas.append(nome)
    return bool(cond)


def roda(cmd, *, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def sha256(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def funde(base, camada):
    for chave, valor in camada.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            funde(base[chave], valor)
        else:
            base[chave] = valor


def semear(d):
    os.makedirs(d, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "30",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-color_primaries", "bt709", "-color_trc", "bt709",
         "-colorspace", "bt709", "-shortest", os.path.join(d, "bruto.mp4")],
        check=True)
    # Dois segmentos contíguos exercitam um plano J-cut realmente ativo sem
    # chamar a API do QC: a guarda canônica reconhece que não há emenda de áudio.
    edl = [
        {"src": "bruto.mp4", "start": 0.2, "end": 0.7,
         "fala": "teste sintetico", "beat": "primeiro"},
        {"src": "bruto.mp4", "start": 0.7, "end": 1.2,
         "fala": "teste sintetico", "beat": "segundo"},
    ]
    with open(os.path.join(d, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump(edl, fh, ensure_ascii=False, indent=1)

    perfil = json.load(open(os.path.join(SKILL, "perfis", "_base.json")))
    funde(perfil, json.load(open(os.path.join(SKILL, "perfis", "screencast.json"))))
    perfil["video"].update({"largura": 160, "altura": 90, "crf": 30,
                             "preset_x264": "ultrafast"})
    perfil["audio"]["canais"] = 1
    with open(os.path.join(d, "perfil.json"), "w", encoding="utf-8") as fh:
        json.dump(perfil, fh, ensure_ascii=False, indent=1)
    return edl


def montar(d, *, env=None):
    return roda(["bash", MONTAR, d], env=env)


def qc(d):
    # Uma EDL de um segmento não chama a API: não há emenda a transcrever. Ainda
    # assim percorre toda a carga e interpretação do plano J-cut do QC.
    return roda([sys.executable, QC_EMENDAS, d])


def plano_ativo(edl, fps):
    return jcut.planejar(edl, fps=fps, sr=48000, modo="fixo",
                         lead_max_ms=165, perfil_nome="screencast")


def main():
    base = tempfile.mkdtemp(prefix="ilha-relatorio-p0-")
    d = os.path.join(base, "producao")
    try:
        edl = semear(d)
        final = os.path.join(d, "v1-montado.mp4")

        print("\n1. plano J-cut ausente")
        r = montar(d)
        q = qc(d) if r.returncode == 0 else None
        ok("plano ausente", r.returncode == 0 and q is not None and q.returncode == 0,
           "montar=%d, qc=%s" % (r.returncode, q.returncode if q else "pulado"))
        if not os.path.isfile(final):
            print(r.stderr[-3000:])
            return 1

        print("\n2. temporário seg003 ignorado")
        temporario = os.path.join(d, "segs", "seg003.mp4.tmp-22.mp4")
        open(temporario, "wb").write(b"mp4 parcial que o glob antigo capturava")
        estritos = [os.path.basename(p) for p in edl_io.segs_ordenados(d)]
        r = montar(d)
        ok("seg003.mp4.tmp-22.mp4",
           estritos == ["seg000.mp4", "seg001.mp4"] and r.returncode == 0,
           "enumerador=%s, montar=%d" % (estritos, r.returncode))

        print("\n3. falha antes do rename preserva o final")
        antes = sha256(final)
        fakebin = os.path.join(base, "fakebin")
        os.makedirs(fakebin)
        ffmpeg_real = shutil.which("ffmpeg")
        wrapper = os.path.join(fakebin, "ffmpeg")
        with open(wrapper, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
            fh.write("tmp=0; frame=0\n")
            fh.write("for arg in \"$@\"; do\n")
            fh.write("  case \"$arg\" in */.v1-montado.tmp.*/v1-montado.mp4) tmp=1;; esac\n")
            fh.write("  [ \"$arg\" = \"-frames:v\" ] && frame=1\n")
            fh.write("done\n")
            fh.write("[ \"$tmp:$frame\" = \"1:1\" ] && exit 86\n")
            fh.write("exec %s \"$@\"\n" % shlex.quote(ffmpeg_real))
        os.chmod(wrapper, 0o755)
        env = dict(os.environ)
        env["PATH"] = fakebin + os.pathsep + env["PATH"]
        r = montar(d, env=env)
        restos = [n for n in os.listdir(d) if n.startswith(".v1-montado.tmp.")]
        ok("publicação atômica", r.returncode != 0 and sha256(final) == antes and not restos,
           "exit=%d, final_preservado=%s, temporários=%s"
           % (r.returncode, sha256(final) == antes, restos or 0))

        print("\n4. decisão aplicar:false")
        jcut.gravar_nao_aplicar(d, edl, decidido_por="teste", motivo="caso negativo")
        r = montar(d)
        q = qc(d) if r.returncode == 0 else None
        ok("aplicar:false sem fps/modo", r.returncode == 0 and q is not None
           and q.returncode == 0,
           "montar=%d, qc=%s" % (r.returncode, q.returncode if q else "pulado"))

        print("\n5. plano ativo com fps divergente")
        jcut.gravar(d, plano_ativo(edl, 25))
        antes = sha256(final)
        r = montar(d)
        ok("ativo a 25 fps contra perfil a 30", r.returncode != 0
           and "25 fps" in r.stderr and sha256(final) == antes,
           "exit=%d, divergência_nomeada=%s, final_preservado=%s"
           % (r.returncode, "25 fps" in r.stderr, sha256(final) == antes))

        print("\n6. plano ativo válido")
        jcut.gravar(d, plano_ativo(edl, 30))
        r = montar(d)
        q = qc(d) if r.returncode == 0 else None
        frame = roda(["ffmpeg", "-nostdin", "-v", "error", "-i", final,
                      "-frames:v", "1", "-f", "null", "-"])
        probe = roda(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", final])
        dur = float(probe.stdout) if probe.returncode == 0 and probe.stdout.strip() else 0
        ok("ativo a 30 fps", r.returncode == 0 and q is not None and q.returncode == 0
           and frame.returncode == 0 and dur > 0,
           "montar=%d, qc=%s, primeiro_frame=%d, duração=%.3fs"
           % (r.returncode, q.returncode if q else "pulado", frame.returncode, dur))

        if falhas:
            print("\nFALHOU: " + ", ".join(falhas))
            return 1
        print("\n6 cenários, todos passaram")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
