#!/usr/bin/env python3
"""Entrada de cor auto/multipla deve registrar a decisao sem relabelar."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import perfil  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "detect_cor", os.path.join(SCRIPTS, "detect-cor.py"))
detect_cor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(detect_cor)

falhas = []
casos = 0


def ok(nome, cond, detalhe=""):
    global casos
    casos += 1
    print("  %s %s%s" % ("OK" if cond else "FALHA", nome,
                         (": " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(nome)


auto = detect_cor.avaliar_expectativa("rec709", "auto")
ok("auto registra SDR real", auto["estado"] == "auto"
   and auto["detectado"] == "sdr" and "sem-relabel" in auto["decisao"], repr(auto))

multipla = detect_cor.avaliar_expectativa("rec709", ["hlg", "sdr"])
ok("reels aceita HLG ou SDR", multipla["estado"] == "compativel"
   and multipla["detectado"] == "sdr", repr(multipla))

diverge = detect_cor.avaliar_expectativa("hlg", "sdr")
ok("divergencia bloqueia", diverge["estado"] == "divergente"
   and diverge["decisao"] == "bloquear-sem-converter", repr(diverge))

invalida = detect_cor.avaliar_expectativa("rec709", [])
ok("lista vazia nao vira auto", invalida["estado"] == "invalida", repr(invalida))

base = json.load(open(os.path.join(SKILL, "perfis", "_base.json"), encoding="utf-8"))
base["cor"]["entrada_esperada"] = ["hlg", "sdr"]
ok("schema aceita entrada multipla", not perfil.validar(base), repr(perfil.validar(base)))
base["cor"]["entrada_esperada"] = []
ok("schema rejeita lista vazia", bool(perfil.validar(base)), repr(perfil.validar(base)))

# Controle negativo: HLG nao pode ser aprovado por contrato SDR.
controle = detect_cor.avaliar_expectativa("hlg", ["sdr"])
ok("controle negativo tem dentes", controle["estado"] == "divergente", repr(controle))


def gerar_video(caminho, hlg=False, pq=False):
    tags = ("setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc" if pq else
            "setparams=color_primaries=bt2020:color_trc=arib-std-b67:"
            "colorspace=bt2020nc" if hlg else
            "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709")
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=90x160:rate=25:duration=0.8", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=0.8", "-shortest",
        "-vf", tags, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
        "yuv420p", "-c:a", "aac", caminho], check=True)


def gravar_json(caminho, valor):
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(valor, fh)


tmp = tempfile.mkdtemp(prefix="ilha-cor-expectativa-")
try:
    bruto = os.path.join(tmp, "bruto.mp4")
    gerar_video(bruto)
    perfil_real = json.load(open(os.path.join(SKILL, "perfis", "_base.json"),
                                 encoding="utf-8"))
    perfil_real["video"].update({"largura": 90, "altura": 160, "aspecto": "9:16",
                                  "fps": 25, "preset_x264": "ultrafast", "crf": 30})
    perfil_real["cor"]["entrada_esperada"] = ["hlg", "sdr"]
    gravar_json(os.path.join(tmp, "perfil.json"), perfil_real)
    cmd = [sys.executable, os.path.join(SCRIPTS, "detect-cor.py"), "resolver", tmp,
           "--bruto", "bruto.mp4", "--amostras", "2"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    cor = json.load(open(os.path.join(tmp, "cor.json"), encoding="utf-8"))
    ok("resolver grava decisão compatível", proc.returncode == 0
       and cor["perfil"] == "rec709"
       and cor["expectativa_cor"]["estado"] == "compativel"
       and cor["expectativa_cor"]["detectado"] == "sdr"
       and cor["perfil_esperado_sha256"] ==
       detect_cor.hash_entrada_esperada(["sdr", "hlg"]), proc.stderr[-500:])

    with open(os.path.join(tmp, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump([{"src": "bruto.mp4", "start": 0.0, "end": 0.4,
                    "fala": "fixture", "beat": "cor"}], fh)

    cor_hash_ruim = json.loads(json.dumps(cor))
    cor_hash_ruim["perfil_esperado_sha256"] = "0"
    gravar_json(os.path.join(tmp, "cor.json"), cor_hash_ruim)
    montagem_hash = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), tmp],
        capture_output=True, text=True)
    ok("hash persistido inválido fecha o portão",
       montagem_hash.returncode != 0
       and "não é um SHA-256 hexadecimal válido" in montagem_hash.stderr
       and not os.path.exists(os.path.join(tmp, "segs", "seg000.mp4")),
       montagem_hash.stderr[-700:])
    gravar_json(os.path.join(tmp, "cor.json"), cor)

    # O cor.json ainda diz "compatível", mas o perfil mudou depois da detecção.
    # Mesmo `aplicar_em=passe` não escapa: a expectativa é da peça, não do passe.
    # O portão deve morrer antes de tocar num segmento que já exista.
    perfil_real["cor"]["entrada_esperada"] = "hlg"
    perfil_real["cor"]["aplicar_em"] = "passe"
    gravar_json(os.path.join(tmp, "perfil.json"), perfil_real)
    os.makedirs(os.path.join(tmp, "segs"), exist_ok=True)
    sentinela = os.path.join(tmp, "segs", "seg000.mp4")
    with open(sentinela, "wb") as fh:
        fh.write(b"segmento-anterior")
    montagem_stale = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), tmp],
        capture_output=True, text=True)
    cor_stale = json.load(open(os.path.join(tmp, "cor.json"), encoding="utf-8"))
    ok("perfil stale aborta antes do retorno aplicar_em=passe",
       montagem_stale.returncode != 0
       and "perfil.json mudou depois do `detect-cor.py resolver`" in montagem_stale.stderr
       and "perfil.cor.aplicar_em = passe" not in montagem_stale.stderr
       and cor_stale["expectativa_cor"]["estado"] == "compativel"
       and open(sentinela, "rb").read() == b"segmento-anterior",
       montagem_stale.stderr[-900:])

    # O escape consciente continua acima desse portão: deve substituir o
    # segmento sentinela e concluir a montagem mesmo com o perfil stale.
    perfil_real["cor"]["aplicar_em"] = "extracao"
    gravar_json(os.path.join(tmp, "perfil.json"), perfil_real)
    montagem_forcada = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), tmp,
         "--cor-como", "rec709"], capture_output=True, text=True)
    ok("--cor-como preserva o override explícito",
       montagem_forcada.returncode == 0
       and os.path.isfile(os.path.join(tmp, "v1-montado.mp4"))
       and open(sentinela, "rb").read() != b"segmento-anterior"
       and "origem forcado_por_operador" in montagem_forcada.stderr,
       montagem_forcada.stderr[-1200:])

    # Depois de reresolver, o bloqueio deixa de ser stale e passa a ser a
    # divergência persistida normal. O segmento bom da rodada forçada fica intacto.
    proc = subprocess.run(cmd, capture_output=True, text=True)
    cor = json.load(open(os.path.join(tmp, "cor.json"), encoding="utf-8"))
    ok("resolver grava e bloqueia divergência", proc.returncode == detect_cor.SAI_DIVERGE
       and cor["perfil"] == "rec709"
       and cor["expectativa_cor"]["estado"] == "divergente"
       and cor["expectativa_cor"]["decisao"] == "bloquear-sem-converter",
       proc.stderr[-500:])

    segmento_antes = open(sentinela, "rb").read()
    montagem = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), tmp],
        capture_output=True, text=True)
    ok("montagem posterior respeita bloqueio persistido",
       montagem.returncode != 0
       and "cor.json registra expectativa de entrada divergente" in montagem.stderr
       and open(sentinela, "rb").read() == segmento_antes,
       montagem.stderr[-700:])

    # Upgrade de cor.json anterior ao vínculo: ele não tem valor/hash salvo, mas
    # ainda traz o perfil detectado. SDR antigo sob perfil atual HLG deve fechar.
    cor_legado = json.loads(json.dumps(cor))
    cor_legado.pop("perfil_esperado", None)
    cor_legado.pop("perfil_esperado_sha256", None)
    cor_legado.pop("expectativa_cor", None)
    gravar_json(os.path.join(tmp, "cor.json"), cor_legado)
    montagem_legada = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), tmp],
        capture_output=True, text=True)
    ok("cor.json sem vínculo reavalia SDR antigo contra HLG atual",
       montagem_legada.returncode != 0
       and "rejeita 1 fonte(s) usada(s) pela EDL" in montagem_legada.stderr
       and "bruto.mp4 detectado=sdr" in montagem_legada.stderr
       and open(sentinela, "rb").read() == segmento_antes,
       montagem_legada.stderr[-900:])

    # Produção multissrc: a fonte principal é SDR pelo tempo somado, mas a
    # secundária HLG também entra na EDL. Contrato `sdr` deve bloquear a peça.
    multi = os.path.join(tmp, "multi")
    os.makedirs(multi)
    gerar_video(os.path.join(multi, "principal-sdr.mp4"))
    gerar_video(os.path.join(multi, "secundaria-hlg.mp4"), hlg=True)
    perfil_multi = json.loads(json.dumps(perfil_real))
    perfil_multi["cor"]["entrada_esperada"] = "sdr"
    gravar_json(os.path.join(multi, "perfil.json"), perfil_multi)
    gravar_json(os.path.join(multi, "edl.json"), [
        {"src": "principal-sdr.mp4", "start": 0.0, "end": 0.4,
         "fala": "principal", "beat": "a"},
        {"src": "secundaria-hlg.mp4", "start": 0.0, "end": 0.2,
         "fala": "secundaria", "beat": "b"},
    ])
    multi_cmd = [sys.executable, os.path.join(SCRIPTS, "detect-cor.py"),
                 "resolver", multi, "--amostras", "2"]
    multi_proc = subprocess.run(multi_cmd, capture_output=True, text=True)
    multi_cor = json.load(open(os.path.join(multi, "cor.json"), encoding="utf-8"))
    exp_multi = multi_cor["expectativa_cor"]
    ok("multissrc bloqueia secundária divergente",
       multi_proc.returncode == detect_cor.SAI_DIVERGE
       and multi_cor["perfil"] == "rec709"
       and multi_cor["fontes"]["secundaria-hlg.mp4"]["perfil"] == "hlg"
       and exp_multi["detectado"] == "sdr"
       and exp_multi["estado"] == "divergente"
       and exp_multi["por_fonte"]["secundaria-hlg.mp4"]["estado"] == "divergente"
       and exp_multi["fontes_bloqueadas"] == ["secundaria-hlg.mp4"],
       multi_proc.stderr[-900:])
    multi_montagem = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), multi],
        capture_output=True, text=True)
    ok("montagem multissrc respeita bloqueio agregado",
       multi_montagem.returncode != 0
       and "cor.json registra expectativa de entrada divergente" in multi_montagem.stderr
       and not os.path.exists(os.path.join(multi, "segs", "seg000.mp4")),
       multi_montagem.stderr[-900:])

    # Compatibilidade fail-closed com cor.json do detector anterior: mesmo que o
    # estado salvo olhe só a principal e diga compatível, montar revalida a EDL.
    multi_cor["expectativa_cor"] = detect_cor.avaliar_expectativa("rec709", "sdr")
    gravar_json(os.path.join(multi, "cor.json"), multi_cor)
    multi_legado = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), multi],
        capture_output=True, text=True)
    ok("montagem fecha cor.json antigo compatível só com a principal",
       multi_legado.returncode != 0
       and "rejeita 1 fonte(s) usada(s) pela EDL" in multi_legado.stderr
       and "secundaria-hlg.mp4" in multi_legado.stderr
       and not os.path.exists(os.path.join(multi, "segs", "seg000.mp4")),
       multi_legado.stderr[-1000:])

    # Produção nova: a montagem resolve o contrato automaticamente. Rec.709
    # segue sem conversão; perfil não calibrado/baixa confiança para antes do
    # primeiro segmento. `--sem-cor` permanece o escape explícito e registrado.
    auto = os.path.join(tmp, "auto-cor")
    os.makedirs(auto)
    gerar_video(os.path.join(auto, "rec709.mp4"))
    perfil_auto = json.loads(json.dumps(perfil_real))
    perfil_auto["cor"]["entrada_esperada"] = ["hlg", "sdr"]
    gravar_json(os.path.join(auto, "perfil.json"), perfil_auto)
    gravar_json(os.path.join(auto, "edl.json"), [
        {"src": "rec709.mp4", "start": 0.0, "end": 0.4,
         "fala": "auto", "beat": "auto"},
    ])
    auto_montagem = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), auto],
        capture_output=True, text=True)
    auto_cor = json.load(open(os.path.join(auto, "cor.json"), encoding="utf-8"))
    ok("cor ausente é resolvida automaticamente para Rec.709",
       auto_montagem.returncode == 0
       and "cor.json ausente: resolvendo automaticamente" in auto_montagem.stderr
       and auto_cor["perfil"] == "rec709"
       and os.path.isfile(os.path.join(auto, "v1-montado.mp4")),
       auto_montagem.stderr[-1200:])

    pq = os.path.join(tmp, "auto-pq")
    os.makedirs(pq)
    gerar_video(os.path.join(pq, "pq.mp4"), pq=True)
    perfil_pq = json.loads(json.dumps(perfil_auto))
    perfil_pq["cor"]["entrada_esperada"] = "auto"
    gravar_json(os.path.join(pq, "perfil.json"), perfil_pq)
    gravar_json(os.path.join(pq, "edl.json"), [
        {"src": "pq.mp4", "start": 0.0, "end": 0.4,
         "fala": "pq", "beat": "pq"},
    ])
    pq_montagem = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), pq],
        capture_output=True, text=True)
    pq_cor = json.load(open(os.path.join(pq, "cor.json"), encoding="utf-8"))
    ok("cor não calibrada aborta antes do primeiro segmento",
       pq_montagem.returncode != 0 and pq_cor["perfil"] == "pq"
       and not pq_cor["calibrado"]
       and "resolvedor de cor não liberou" in pq_montagem.stderr
       and not os.path.exists(os.path.join(pq, "segs", "seg000.mp4")),
       pq_montagem.stderr[-1200:])

    explicito = os.path.join(tmp, "sem-cor-explicito")
    os.makedirs(explicito)
    gerar_video(os.path.join(explicito, "rec709.mp4"))
    gravar_json(os.path.join(explicito, "perfil.json"), perfil_auto)
    gravar_json(os.path.join(explicito, "edl.json"), [
        {"src": "rec709.mp4", "start": 0.0, "end": 0.4,
         "fala": "explicito", "beat": "explicito"},
    ])
    sem_cor = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "montar.sh"), explicito, "--sem-cor"],
        capture_output=True, text=True)
    plano = json.load(open(os.path.join(explicito, "cor-decisao.json"),
                           encoding="utf-8"))
    ok("--sem-cor continua explícito e auditável",
       sem_cor.returncode == 0 and not os.path.exists(os.path.join(explicito, "cor.json"))
       and plano["modo"] == "sem-cor" and plano["override_explicito"] is True
       and plano["edl_fingerprint"]
       and os.path.isfile(os.path.join(explicito, "v1-montado.mp4")),
       sem_cor.stderr[-1200:])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d casos, %d falha(s)" % (casos, len(falhas)))
sys.exit(1 if falhas else 0)
