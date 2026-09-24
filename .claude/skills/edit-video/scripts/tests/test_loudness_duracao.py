#!/usr/bin/env python3
"""Teste do H47-2 (SPEC-47) — a conferência de duração do loudness.py, e as duas
mentiras que ela contava.

    python3 .claude/skills/edit-video/scripts/tests/test_loudness_duracao.py

🔴 AS DUAS MENTIRAS, MEDIDAS (2026-08-12)

(1) **O sidecar dizia `ok` sobre uma rodada abortada.** Relato de campo: "declarou
    duração preservada, mas gerou 56,43 s de 64,50". Reproduzido aqui na v0.12: com
    entrada AAC, o `--normalizar` aborta com exit 3 por deriva de +16 ms **e grava**
    `{"duracao": {"veredito": "DERIVA"}, "veredito": "ok"}` no MESMO arquivo. O
    sidecar é o que sobrevive à sessão — quem o lê depois encontra o "ok".

(2) **A régua era só o `duration` do contêiner.** Header é o primeiro campo a
    mentir quando a escrita morre no meio. Agora conta-se também amostra
    decodificada.

🦷 E O CONTROLE ENSINOU UMA TERCEIRA COISA, que virou desenho: contar SÓ amostra
    perde a deriva do AAC. O clipe AAC de 6 s declara 6,000 s no contêiner e
    entrega 288.768 amostras (6,016 s) no decoder — o padding já está dentro do
    arquivo, e o header é que o desconta. Ao virar WAV, que não tem onde guardar
    esse desconto, os 16 ms viram áudio. Pela amostra a deriva "não existe"; pelo
    header ela é real. Por isso as DUAS réguas reprovam, e o teste cobra as duas.

Sem ffmpeg o teste sai 0 dizendo que não mediu — nunca verde silencioso.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
LOUDNESS = os.path.join(SCRIPTS, "loudness.py")

falhas = []
varrido = {}


def conta(chave, n=1):
    varrido[chave] = varrido.get(chave, 0) + n


def ok(msg, cond, detalhe=""):
    print("   %s %s%s" % ("✅" if cond else "❌", msg,
                          ("  — " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(msg)
    return cond


def _mod():
    spec = importlib.util.spec_from_file_location("loudness_mod", LOUDNESS)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, SCRIPTS)
    spec.loader.exec_module(m)
    return m


def _ff(*args):
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-y"] + list(args),
                          capture_output=True, text=True).returncode == 0


def main():
    print("test_loudness_duracao — H47-2: duas réguas de duração, e o sidecar que "
          "dizia ok")
    if not shutil.which("ffmpeg"):
        print("   ⏭️ NÃO MEDIDO: ffmpeg ausente.")
        return 0
    m = _mod()
    tmp = tempfile.mkdtemp(prefix="loudness-dur-")
    try:
        voz = os.path.join(tmp, "voz.wav")
        aac = os.path.join(tmp, "voz.m4a")
        trunc = os.path.join(tmp, "voz-truncado.wav")
        _ff("-f", "lavfi", "-i",
            "sine=frequency=200:sample_rate=48000:duration=10",
            "-c:a", "pcm_s16le", "-ac", "1", voz)
        _ff("-f", "lavfi", "-i",
            "sine=frequency=200:sample_rate=48000:duration=6",
            "-c:a", "aac", "-b:a", "128k", aac)
        # 🦷 o defeito plantado: um WAV cortado no meio (o "56,43 de 64,50")
        b = open(voz, "rb").read()
        with open(trunc, "wb") as fh:
            fh.write(b[:int(len(b) * 0.65)])

        print("\n1 · a contagem de amostras existe e não vem do header")
        n, sr = m._amostras_decodificadas(voz)
        conta("arquivos contados")
        ok("voz.wav → 480.000 amostras a 48 kHz", (n, sr) == (480000, 48000),
           "%s @ %s" % (n, sr))
        n_aac, sr_aac = m._amostras_decodificadas(aac)
        conta("arquivos contados")
        ok("o AAC entrega MAIS amostras do que o header declara (padding)",
           n_aac is not None and n_aac / float(sr_aac) > (m._duracao_audio(aac) or 0),
           "amostras %.3f s vs header %.3f s"
           % (n_aac / float(sr_aac), m._duracao_audio(aac)))

        print("\n2 · 🦷 o WAV truncado plantado é ACUSADO")
        d = m._conferir_deriva(voz, trunc, 5.0)
        conta("comparações")
        ok("veredito DERIVA", d["veredito"] == "DERIVA", d["veredito"])
        ok("a perda é medida em amostras, não só em header",
           d["amostras_saida"] == 311986 and abs(d["delta_amostras_ms"]) > 3000,
           "%s amostras · Δamostras %s ms" % (d["amostras_saida"],
                                              d["delta_amostras_ms"]))
        # 🦷 controle do controle: o caso limpo NÃO pode ser acusado
        d_ok = m._conferir_deriva(voz, voz, 5.0)
        conta("comparações")
        ok("o mesmo arquivo contra si mesmo continua ok",
           d_ok["veredito"] == "ok" and d_ok["delta_ms"] == 0.0, str(d_ok["delta_ms"]))

        print("\n3 · 🦷 o header mentindo sobre o próprio arquivo é ARQUIVO-MALFORMADO")
        # Neste build o demuxer de WAV CLAMPA a duração ao tamanho do arquivo, então
        # um truncamento não produz header mentiroso: para exercitar a regra, a
        # mentira é INJETADA no leitor de header. É o código do ramo que está sob
        # teste, e a nota existe para ninguém ler isto como "medimos um WAV
        # malformado neste ffmpeg".
        real = m._duracao_audio
        try:
            m._duracao_audio = lambda c: (64.50 if c == trunc else real(c))
            d_mal = m._conferir_deriva(voz, trunc, 5.0)
        finally:
            m._duracao_audio = real
        conta("comparações")
        ok("header 64,50 s × amostras 6,50 s → ARQUIVO-MALFORMADO",
           d_mal["veredito"] == "ARQUIVO-MALFORMADO",
           "divergência %s ms" % d_mal.get("divergencia_header_ms"))
        ok("e a regra só vale onde header e amostra TÊM que fechar (PCM)",
           d_mal["saida_exata"] is True)

        print("\n4 · 🦷 ponta a ponta: o sidecar não pode dizer `ok` num run abortado")
        for rotulo, entrada, exit_esperado, veredito_esperado in (
                ("PCM→PCM canônico", voz, 0, "ok"),
                ("AAC→WAV (+16 ms REAIS)", aac, 3, "deriva")):
            out = os.path.join(tmp, "out-%s.wav" % exit_esperado)
            r = subprocess.run([sys.executable, LOUDNESS, entrada, "--normalizar",
                                "--alvo-i", "-14", "--alvo-tp", "-1.5",
                                "--alvo-lra", "7", "--out", out,
                                "--autorizar-ganho-alto",
                                "fixture sintética do teste de duração"],
                               capture_output=True, text=True)
            with open(out + ".loudness.json") as fh:
                reg = json.load(fh)
            conta("execuções ponta a ponta")
            ok("%-24s exit %d" % (rotulo, exit_esperado),
               r.returncode == exit_esperado, "exit %d" % r.returncode)
            ok("%-24s sidecar veredito=%s" % (rotulo, veredito_esperado),
               reg["veredito"] == veredito_esperado, reg["veredito"])
            ok("%-24s sidecar e duracao NÃO se contradizem" % rotulo,
               (reg["veredito"] == "ok") == (reg["duracao"]["veredito"] == "ok"),
               "%s × %s" % (reg["veredito"], reg["duracao"]["veredito"]))
            if entrada is aac:
                ok("%-24s a régua que reprovou é nomeada" % rotulo,
                   reg["duracao"]["regua"] == "header"
                   and reg["duracao"]["delta_header_ms"] == 16.0,
                   str(reg["duracao"]["regua"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-38s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas[:6]))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
