#!/usr/bin/env python3
"""Regressão do sincronismo J-cut em amostras inteiras.

A fixture reduzida tem sete takes e cinco leads maiores que zero. O primeiro
take começa na amostra zero do bruto, reproduzindo o falso `-BUSCA_MS` observado
em produção. Um controle negativo planta deriva de duas amostras por take para
provar que os limites de 1 amostra e 0,10 amostra/take continuam com dentes.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SCRIPTS)

import jcut  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "qc_jcut", os.path.join(SCRIPTS, "qc-jcut.py"))
qc_jcut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qc_jcut)

falhas_teste = []


def ok(nome, condicao, detalhe=""):
    marca = "PASSOU" if condicao else "FALHOU"
    print("  [%s] %s%s" % (marca, nome, " — " + detalhe if detalhe else ""))
    if not condicao:
        falhas_teste.append(nome)
    return bool(condicao)


def criar_fixture(deslocar=None):
    sr = 4800
    fps = 30
    spf = sr // fps
    frames = 120                         # 4 s de imagem por take
    starts = [0, 5, 10, 15, 20, 25, 30]
    leads = [0, 1, 2, 1, 0, 2, 1]       # cinco sobreposições reais
    deslocar = deslocar or (lambda _i: 0)
    rng = np.random.default_rng(20260816)
    bruto = (rng.standard_normal(36 * sr) * 0.02).astype(np.float32)
    edl, segmentos, saida = [], [], []
    v_off_frames = 0
    maior_deslocamento = max(abs(int(deslocar(i))) for i in range(len(starts)))
    wav = np.zeros(len(starts) * frames * spf + maior_deslocamento + 1,
                   dtype=np.float32)

    for i, (inicio_s, lead) in enumerate(zip(starts, leads)):
        inicio = inicio_s * sr
        geo = jcut.geometria_take(
            start_s=inicio_s, video_offset_frames=v_off_frames,
            video_frames=frames, lead_frames=lead, sr=sr, spf=spf)
        take = bruto[inicio:inicio + geo["audio_samples"]]
        off = geo["audio_offset_samples"] + int(deslocar(i))
        wav[off:off + len(take)] += take
        edl.append({
            "src": "bruto.wav",
            "start": float(inicio_s),
            "end": (inicio + geo["audio_samples"]) / sr,
        })
        segmentos.append({
            "i": i,
            "start": float(inicio_s),
            "lead_frames_in": lead,
            "video_skip_frames": lead,
        })
        saida.append({
            "i": i,
            "video_offset_frames": v_off_frames,
            "video_frames": frames,
            "audio_offset_samples": geo["audio_offset_samples"],
            "audio_samples": geo["audio_samples"],
            "src_offset_samples": geo["src_visual_samples"],
            "src_offset_s": geo["src_visual_samples"] / sr,
        })
        v_off_frames += frames

    return {
        "sr": sr,
        "fps": fps,
        "spf": spf,
        "frames": frames,
        "starts": starts,
        "leads": leads,
        "bruto": bruto,
        "wav": wav,
        "edl": edl,
        "plano": {
            "fps": fps,
            "sr": sr,
            "samples_por_frame": spf,
            "segmentos": segmentos,
            "saida": saida,
        },
    }


def medir(fx):
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        falhas = qc_jcut.teste_sincronia(
            fx["plano"], fx["edl"], fx["wav"], fx["sr"],
            {"bruto.wav": fx["bruto"]}, min_dur=3.0, busca_ms=25.0)
    return falhas, log.getvalue()


def testar_geometria():
    fx = criar_fixture()
    fechou = True
    for i, (s, pl) in enumerate(zip(fx["plano"]["saida"],
                                     fx["plano"]["segmentos"])):
        geo = jcut.geometria_take(
            start_s=fx["edl"][i]["start"],
            video_offset_frames=s["video_offset_frames"],
            video_frames=s["video_frames"],
            lead_frames=pl["lead_frames_in"], sr=fx["sr"], spf=fx["spf"])
        fechou = fechou and (
            geo["audio_offset_samples"] + geo["audio_samples"]
            == geo["video_offset_samples"] + geo["video_samples"])
        fechou = fechou and (
            geo["src_visual_samples"]
            == geo["src_start_samples"] + geo["lead_samples"])
    ok("geometria compartilhada fecha cada take sem acumular", fechou,
       "7 takes, 5 leads")


def testar_saida_medida():
    fx = criar_fixture()
    plano = dict(fx["plano"])
    plano["segmentos"] = [dict(s, start=fx["edl"][i]["start"])
                           for i, s in enumerate(fx["plano"]["segmentos"])]
    plano["min_frames_plano"] = 8
    plano["saida"] = None
    tl = {
        "video": {"fps": fx["fps"]},
        "gerado_em": "fixture",
        "segments": [
            {"i": i, "start_frame": i * fx["frames"], "frames": fx["frames"]}
            for i in range(len(fx["edl"]))
        ],
    }
    timeline_original = jcut.edl_io.timeline
    try:
        jcut.edl_io.timeline = lambda *_a, **_kw: tl
        medido, avisos = jcut.medir_saida(".", plano)
    finally:
        jcut.edl_io.timeline = timeline_original
    exato = not avisos
    for i, s in enumerate(medido["saida"]):
        esperado = fx["starts"][i] * fx["sr"] + fx["leads"][i] * fx["spf"]
        exato = exato and s["src_offset_samples"] == esperado
        exato = exato and (
            s["audio_offset_samples"] + s["audio_samples"]
            == (i + 1) * fx["frames"] * fx["spf"])
    ok("--medir persiste offset da fonte em amostra inteira", exato,
       "7 de 7 offsets exatos")


def testar_padding():
    bruto = np.arange(1, 6, dtype=np.float32)
    obtido = qc_jcut.fatia_amostras(bruto, -2, 6).tolist()
    ok("janela anterior à amostra zero preserva padding à esquerda",
       obtido == [0.0, 0.0, 1.0, 2.0, 3.0, 4.0], repr(obtido))


def testar_limites():
    falhas, log = medir(criar_fixture())
    ok("sete takes com múltiplos leads ficam em lag zero",
       not falhas and "take  0: lag   +0 amostra" in log
       and "tendência: +0.0000 amostra por take" in log,
       "%d falha(s)" % len(falhas))

    falhas, log = medir(criar_fixture(deslocar=lambda _i: 1))
    ok("uma amostra constante continua dentro do limite",
       not falhas and "lag   -1 amostra" in log,
       "%d falha(s)" % len(falhas))

    falhas, log = medir(criar_fixture(deslocar=lambda i: 2 * i))
    detectou_lag = any("take 1: lag de -2 amostras" in f for f in falhas)
    detectou_slope = any("deriva progressiva: -2.000 amostra por take" in f
                         for f in falhas)
    ok("deriva plantada de duas amostras por take continua reprovando",
       detectou_lag and detectou_slope, "%d reprovação(ões)" % len(falhas))


def testar_decisao_negativa():
    plano = {"aplicar": False,
             "segmentos": [{"video_skip_frames": 4},
                            {"video_skip_frames": 3}]}
    ok("decisão aplicar:false continua zerando todos os leads",
       jcut.skips(plano, 2) == [0, 0])


def fundir(base, camada):
    for chave, valor in camada.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            fundir(base[chave], valor)
        else:
            base[chave] = valor


def testar_montagem_real():
    ausentes = [nome for nome in ("ffmpeg", "ffprobe", "jq")
                if not shutil.which(nome)]
    if ausentes:
        ok("montagem real com três leads", True,
           "PULADO, ausente: %s" % ", ".join(ausentes))
        return

    d = tempfile.mkdtemp(prefix="ilha-jcut-sync-")
    try:
        bruto = os.path.join(d, "bruto.mp4")
        gerou = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=4",
            "-f", "lavfi", "-i",
            "anoisesrc=color=pink:amplitude=0.03:sample_rate=48000:duration=4",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "30",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-colorspace", "bt709", "-shortest", bruto,
        ], capture_output=True, text=True)
        if gerou.returncode != 0:
            ok("montagem real com três leads", False, gerou.stderr[-500:])
            return

        edl = [
            {"src": "bruto.mp4", "start": 0.0, "end": 0.8,
             "beat": "s0", "fala": "fixture"},
            {"src": "bruto.mp4", "start": 1.0, "end": 1.8,
             "beat": "s1", "fala": "fixture"},
            {"src": "bruto.mp4", "start": 2.0, "end": 2.8,
             "beat": "s2", "fala": "fixture"},
            {"src": "bruto.mp4", "start": 3.0, "end": 3.8,
             "beat": "s3", "fala": "fixture"},
        ]
        with open(os.path.join(d, "edl.json"), "w", encoding="utf-8") as fh:
            json.dump(edl, fh, indent=1)

        skill = os.path.dirname(SCRIPTS)
        with open(os.path.join(skill, "perfis", "_base.json")) as fh:
            perfil = json.load(fh)
        with open(os.path.join(skill, "perfis", "screencast.json")) as fh:
            fundir(perfil, json.load(fh))
        perfil["video"].update({"largura": 160, "altura": 90, "crf": 30,
                                 "preset_x264": "ultrafast"})
        perfil["audio"]["canais"] = 1
        with open(os.path.join(d, "perfil.json"), "w", encoding="utf-8") as fh:
            json.dump(perfil, fh, indent=1)

        plano = jcut.planejar(edl, fps=30, sr=48000, modo="fixo",
                               lead_max_ms=100, perfil_nome="screencast")
        leads = [s["lead_frames_in"] for s in plano["segmentos"]]
        jcut.gravar(d, plano)
        montar = subprocess.run(["bash", os.path.join(SCRIPTS, "montar.sh"), d],
                                capture_output=True, text=True)
        if montar.returncode != 0:
            ok("montagem real com três leads", False, montar.stderr[-1000:])
            return
        plano = jcut.carregar(d, edl, exigir=True)
        plano, avisos = jcut.medir_saida(d, plano)
        jcut.gravar(d, plano)
        qc = subprocess.run([
            sys.executable, os.path.join(SCRIPTS, "qc-jcut.py"), d,
            "--min-dur", "0.3",
        ], capture_output=True, text=True)
        takes = [p for p in os.listdir(os.path.join(d, "audio-takes"))
                 if p.startswith("seg") and p.endswith(".wav")]
        passou = (leads == [0, 3, 3, 3] and not avisos and qc.returncode == 0
                  and len(takes) == 4
                  and all("src_offset_samples" in s for s in plano["saida"]))
        detalhe = ("leads=%s, PCM=%d, qc=%d" % (leads, len(takes), qc.returncode))
        if qc.returncode != 0:
            detalhe += "; " + (qc.stdout + qc.stderr)[-500:]
        ok("montagem FFmpeg real publica PCM e passa os cinco testes do J-cut",
           passou, detalhe)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    print("test_jcut_sync — sincronismo inteiro e fixture multilead")
    testar_geometria()
    testar_saida_medida()
    testar_padding()
    testar_limites()
    testar_decisao_negativa()
    testar_montagem_real()
    if falhas_teste:
        print("\nFALHOU: " + ", ".join(falhas_teste))
        return 1
    print("\n8 checagens, todas passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
