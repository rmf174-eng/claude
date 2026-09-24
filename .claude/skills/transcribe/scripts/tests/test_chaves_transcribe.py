#!/usr/bin/env python3
"""Regressão: a credencial canônica chega ao transcribe sem `source`.

O teste não chama a Deepgram. Ele planta um transcript idempotente e ativa o
atalho documentado do verificador; assim mede somente a integração de
credencial, inclusive em shell limpo, sem depender de rede.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


AQUI = Path(__file__).resolve().parent
TRANSCRIBE = AQUI.parent / "transcribe.sh"


def _raiz() -> Path:
    for d in (AQUI, *AQUI.parents):
        if (d / "tools" / "pacote" / "chaves.py").is_file():
            return d
    raise RuntimeError("raiz sem tools/pacote/chaves.py")


CHAVES = _raiz() / "tools" / "pacote" / "chaves.py"


def executar() -> int:
    falhas: list[str] = []
    medidos = 0

    def ok(nome: str, cond: bool, detalhe: str = "") -> None:
        nonlocal medidos
        medidos += 1
        print("  %s %s%s" % ("OK" if cond else "FALHA", nome,
                              ("  " + detalhe) if detalhe else ""))
        if not cond:
            falhas.append(nome)

    # Construído em partes para o valor de controle não virar uma credencial
    # literal encontrada pelo scanner de segredos do pacote.
    segredo = "dg-integracao-" + "ARQ7"
    with tempfile.TemporaryDirectory(prefix="ilha-chave-transcribe-") as tmp:
        base = Path(tmp)
        home = base / "home"
        home.mkdir()
        entrada = base / "entrada.mp3"
        entrada.write_bytes(b"audio-sintetico")
        out = base / "saida"
        out.mkdir()
        (out / "transcript.json").write_text("{}\n", encoding="utf-8")
        (out / "transcript.md").write_text("# fixture\n", encoding="utf-8")

        env = dict(os.environ)
        env.update({
            "ILHA_HOME": str(home),
            "BENCH_TRANSCRIBE_SEM_VERIFICAR": "1",
        })
        env.pop("DEEPGRAM_API_KEY", None)
        env.pop("ILHA_CHAVES_REEXEC", None)

        sem = subprocess.run(
            ["bash", str(TRANSCRIBE), str(entrada), str(out)],
            capture_output=True, text=True, env=env)
        texto_sem = sem.stdout + sem.stderr
        ok("ausência falha de modo orientado", sem.returncode == 1,
           "exit %d" % sem.returncode)
        ok("ausência não gera traceback",
           "Traceback" not in texto_sem and "não está configurada" in texto_sem)
        ok("ausência orienta a entrada oculta oficial",
           "--pedir DEEPGRAM_API_KEY" in texto_sem)
        ok("ausência não sugere segredo no histórico do shell",
           "SUA_CHAVE" not in texto_sem and "gravar(" not in texto_sem)

        arquivo = home / ".env"
        arquivo.write_text("DEEPGRAM_API_KEY=%s\n" % segredo, encoding="utf-8")
        os.chmod(arquivo, stat.S_IRUSR | stat.S_IWUSR)
        com = subprocess.run(
            ["bash", str(TRANSCRIBE), str(entrada), str(out)],
            capture_output=True, text=True, env=env)
        texto_com = com.stdout + com.stderr
        ok("$ILHA_HOME/.env chega ao transcritor em shell limpo",
           com.returncode == 0 and str(out / "transcript.md") in com.stdout,
           "exit %d" % com.returncode)
        ok("wrapper não imprime a credencial",
           segredo not in texto_com and "ARQ7" not in texto_com)

        # O comando oficial injeta o valor no processo filho sem devolvê-lo em
        # stdout. O filho prova somente presença, nunca o valor.
        wrapper = subprocess.run(
            [sys.executable, str(CHAVES), "--executar-com", "DEEPGRAM_API_KEY",
             "--", sys.executable, "-c",
             ("import os,sys; sys.exit(0 if "
              "os.environ.get(os.environ['ILHA_TEST_NOME']) else 9)")],
            capture_output=True, text=True,
            env={**env, "ILHA_TEST_NOME": "DEEPGRAM_API_KEY"})
        texto_wrapper = wrapper.stdout + wrapper.stderr
        ok("wrapper oficial injeta somente no filho", wrapper.returncode == 0,
           "exit %d" % wrapper.returncode)
        ok("wrapper oficial fica silencioso sobre o valor",
           segredo not in texto_wrapper and "ARQ7" not in texto_wrapper)

    print("%d checagens, %d falha(s)" % (medidos, len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(executar())
