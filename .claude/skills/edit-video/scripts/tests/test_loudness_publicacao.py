#!/usr/bin/env python3
"""Controles de publicação atômica e decisão de ganho alto do loudness.py.

Planta três candidatos inválidos antes do rename: sem moov, sem vídeo e com
duração errada. Em todos, o entregável anterior tem que sobreviver byte a byte e
o parcial tem que desaparecer. Também prova que >6 dB bloqueia sem assinatura e
que a assinatura entra no sidecar quando a publicação é autorizada.
"""
import glob
import hashlib
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
    print("   %s %s%s" % ("OK" if cond else "FALHA", msg,
                          ("  | " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(msg)


def mod():
    spec = importlib.util.spec_from_file_location("loudness_publicacao_mod", LOUDNESS)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, SCRIPTS)
    spec.loader.exec_module(m)
    return m


def ff(*args):
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y"] + list(args),
                          capture_output=True, text=True)


def sha(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def corromper_mdat(origem, destino):
    dados = bytearray(open(origem, "rb").read())
    pos = 0
    while pos + 8 <= len(dados):
        tamanho = int.from_bytes(dados[pos:pos + 4], "big")
        tipo = bytes(dados[pos + 4:pos + 8])
        cab = 8
        if tamanho == 1 and pos + 16 <= len(dados):
            tamanho = int.from_bytes(dados[pos + 8:pos + 16], "big")
            cab = 16
        elif tamanho == 0:
            tamanho = len(dados) - pos
        if tamanho < cab or pos + tamanho > len(dados):
            return False
        if tipo == b"mdat":
            dados[pos + cab:pos + tamanho] = b"\x00" * (tamanho - cab)
            with open(destino, "wb") as fh:
                fh.write(dados)
            return True
        pos += tamanho
    return False


def rodar_cli(entrada, saida, autorizacao=None):
    cmd = [sys.executable, LOUDNESS, entrada, "--normalizar",
           "--alvo-i", "-14", "--alvo-tp", "-1.5", "--alvo-lra", "7",
           "--out", saida]
    if autorizacao is not None:
        cmd += ["--autorizar-ganho-alto", autorizacao]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    print("test_loudness_publicacao: decisão >6 dB e rename só depois dos portões")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("NAO MEDIDO: ffmpeg/ffprobe ausente")
        return 0
    m = mod()
    tmp = tempfile.mkdtemp(prefix="loudness-publicacao-")
    try:
        entrada = os.path.join(tmp, "entrada.mp4")
        r = ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
               "-filter:a", "volume=-35dB", "-t", "2", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", entrada)
        if r.returncode != 0:
            print("NAO MEDIDO: não foi possível gerar fixture MP4: %s" % r.stderr[-500:])
            return 0

        print("\n0. fronteira da política: 6,0000 passa; 6,0001 exige decisão")
        no_teto = m.decidir_ganho_alto(
            {"ganho_linear_db": 6.0, "ganho_linear_db_exato": 6.0}, None)
        try:
            m.decidir_ganho_alto(
                {"ganho_linear_db": 6.0, "ganho_linear_db_exato": 6.0001}, None)
            acima_bloqueou = False
        except m.Erro:
            acima_bloqueou = True
        conta("fronteiras do limiar", 2)
        ok("6,0000 dB não exige assinatura", no_teto["exigida"] is False)
        ok("6,0001 dB exige assinatura", acima_bloqueou)

        print("\n1. ganho alto sem decisão bloqueia antes de tocar o destino")
        bloqueado = os.path.join(tmp, "bloqueado.mp4")
        sentinela = b"ENTREGAVEL-ANTERIOR-NAO-TOCAR"
        with open(bloqueado, "wb") as fh:
            fh.write(sentinela)
        r = rodar_cli(entrada, bloqueado)
        conta("decisoes de ganho")
        ok("exit 2", r.returncode == 2, "exit=%d" % r.returncode)
        ok("erro exige a flag auditável", "--autorizar-ganho-alto" in r.stderr)
        ok("entregável anterior preservado", open(bloqueado, "rb").read() == sentinela)
        ok("nenhum sidecar de sucesso", not os.path.exists(bloqueado + ".loudness.json"))
        ok("nenhuma arena parcial", not glob.glob(os.path.join(tmp, ".loudness-parcial-*")))

        print("\n2. decisão explícita publica MP4 validado e fica no sidecar")
        publicado = os.path.join(tmp, "publicado.mp4")
        justificativa = "direção editorial aprovou preservar a fonte e elevar o nível"
        r = rodar_cli(entrada, publicado, justificativa)
        conta("decisoes de ganho")
        ok("exit 0", r.returncode == 0, "exit=%d stderr=%s" % (r.returncode, r.stderr[-300:]))
        reg = json.load(open(publicado + ".loudness.json", encoding="utf-8")) \
            if os.path.exists(publicado + ".loudness.json") else {}
        decisao = reg.get("decisao_ganho_alto") or {}
        ok("ganho >6 dB foi realmente exercitado",
           decisao.get("ganho_medido_db", 0) > 6.0, str(decisao.get("ganho_medido_db")))
        ok("autorização e justificativa sobrevivem no sidecar",
           decisao.get("autorizada") is True
           and decisao.get("justificativa") == justificativa)
        ok("pipeline declarado como atômico",
           (reg.get("publicacao") or {}).get("atomica") is True)
        ok("moov existe", os.path.exists(publicado) and m._tem_moov(publicado))
        dec = ff("-i", publicado, "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-")
        ok("decode integral passa", dec.returncode == 0, dec.stderr[-300:])
        ok("nenhuma arena parcial após sucesso",
           not glob.glob(os.path.join(tmp, ".loudness-parcial-*")))

        expectativa = m._expectativa_midia(entrada)
        alvo = {"canais": 1, "sr": 48000}
        final_anterior = os.path.join(tmp, "final-anterior.mp4")
        shutil.copy2(publicado, final_anterior)
        sha_anterior = sha(final_anterior)

        print("\n3. controle negativo: parcial sem moov morre antes do rename")
        sem_moov = os.path.join(tmp, "sem-moov.mp4")
        with open(sem_moov, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2")
        try:
            m._publicar_midia_atomica(sem_moov, final_anterior, expectativa, alvo, 1.0)
            recusou = False
            erro = "não recusou"
        except m.Erro as e:
            recusou = "moov" in str(e)
            erro = str(e)
        conta("falhas plantadas antes do rename")
        ok("moov ausente é acusado", recusou, erro)
        ok("parcial sem moov foi removido", not os.path.exists(sem_moov))
        ok("final anterior segue byte a byte", sha(final_anterior) == sha_anterior)

        print("\n4. controle negativo: MP4 só de áudio não substitui entrega com vídeo")
        so_audio = os.path.join(tmp, "so-audio.mp4")
        r = ff("-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=2",
               "-t", "2", "-c:a", "aac", "-movflags", "+faststart", so_audio)
        try:
            m._publicar_midia_atomica(so_audio, final_anterior, expectativa, alvo, 1.0)
            recusou = False
            erro = "não recusou"
        except m.Erro as e:
            recusou = "streams errados" in str(e)
            erro = str(e)
        conta("falhas plantadas antes do rename")
        ok("stream de vídeo ausente é acusado", r.returncode == 0 and recusou, erro)
        ok("parcial com stream errado foi removido", not os.path.exists(so_audio))
        ok("final anterior continua byte a byte", sha(final_anterior) == sha_anterior)

        print("\n5. controle negativo: duração errada não é mascarada por rename")
        curto = os.path.join(tmp, "curto.mp4")
        r = ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
               "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-movflags", "+faststart", curto)
        try:
            m._publicar_midia_atomica(curto, final_anterior, expectativa, alvo, 1.0)
            recusou = False
            erro = "não recusou"
        except m.Erro as e:
            recusou = "duração divergente" in str(e)
            erro = str(e)
        conta("falhas plantadas antes do rename")
        ok("duração divergente é acusada", r.returncode == 0 and recusou, erro)
        ok("parcial curto foi removido", not os.path.exists(curto))
        ok("final anterior ainda byte a byte", sha(final_anterior) == sha_anterior)

        print("\n6. controle negativo: moov válido não compensa payload indecodificável")
        corrompido = os.path.join(tmp, "corrompido.mp4")
        plantou = corromper_mdat(publicado, corrompido)
        try:
            m._publicar_midia_atomica(
                corrompido, final_anterior, expectativa, alvo, 1.0)
            recusou = False
            erro = "não recusou"
        except m.Erro as e:
            recusou = "decodificação integral" in str(e)
            erro = str(e)
        conta("falhas plantadas antes do rename")
        ok("decode integral acusa mdat corrompido", plantou and recusou, erro)
        ok("parcial indecodificável foi removido", not os.path.exists(corrompido))
        ok("final anterior permanece byte a byte", sha(final_anterior) == sha_anterior)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nO que este teste varreu")
    for k, v in sorted(varrido.items()):
        print("   %-42s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
