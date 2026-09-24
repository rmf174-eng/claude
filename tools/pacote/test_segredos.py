#!/usr/bin/env python3
"""Autoteste do contrato mascarado e do scanner de segredos.

Roda sem rede e sem pytest:

    python3 tools/pacote/test_segredos.py

O controle negativo planta o valor resolvido em um log, em um ZIP e ate no
nome de um arquivo. O scanner precisa reprovar os tres sem repetir nenhum
caractere identificador do valor em stdout.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


AQUI = Path(__file__).resolve().parent
CHAVES = AQUI / "chaves.py"


def _carregar():
    spec = importlib.util.spec_from_file_location("ilha_chaves_teste", CHAVES)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@contextmanager
def _ambiente(**valores):
    antes = {k: os.environ.get(k) for k in valores}
    try:
        for k, v in valores.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def executar() -> int:
    chaves = _carregar()
    falhas = []
    varridos = 0

    def ok(nome, cond):
        nonlocal varridos
        varridos += 1
        print("  %s %s" % ("OK" if cond else "FALHA", nome))
        if not cond:
            falhas.append(nome)

    # O valor completo nao existe como literal contiguo neste arquivo.
    segredo_arquivo = "dg-arquivo-controle-" + "K7M2"
    segredo_env = "dg-ambiente-controle-" + "ZXQ9"
    segredo_prompt = "dg-prompt-controle-" + "H3T8"

    with tempfile.TemporaryDirectory(prefix="ilha-segredos-") as tmp:
        base = Path(tmp)
        home = base / "home-autorizada"
        home.mkdir()
        (home / ".env").write_text(
            "DEEPGRAM_API_KEY=%s\n" % segredo_arquivo, encoding="utf-8")
        os.chmod(home / ".env", 0o600)

        with _ambiente(ILHA_HOME=str(home), DEEPGRAM_API_KEY=None,
                       GEMINI_API_KEY=None, PEXELS_API_KEY=None,
                       PIXABAY_API_KEY=None):
            valor, origem = chaves.resolver_com_origem("DEEPGRAM_API_KEY")
            ok("arquivo local autorizado resolve a chave",
               valor == segredo_arquivo and origem == "arquivo_local_autorizado")

            saida_prompt, erros_prompt = io.StringIO(), io.StringIO()
            rc_prompt = chaves.pedir_e_gravar(
                "DEEPGRAM_API_KEY", entrada=lambda _prompt: segredo_prompt,
                saida=saida_prompt, erros=erros_prompt)
            texto_prompt = saida_prompt.getvalue() + erros_prompt.getvalue()
            valor, origem = chaves.resolver_com_origem("DEEPGRAM_API_KEY")
            ok("--pedir usa entrada oculta injetável e grava no caminho canônico",
               rc_prompt == 0 and valor == segredo_prompt
               and origem == "arquivo_local_autorizado"
               and stat.S_IMODE((home / ".env").stat().st_mode) == 0o600)
            ok("--pedir nunca repete o valor configurado",
               segredo_prompt not in texto_prompt and "H3T8" not in texto_prompt)

            with _ambiente(DEEPGRAM_API_KEY=segredo_env):
                valor, origem = chaves.resolver_com_origem("DEEPGRAM_API_KEY")
                ok("ambiente vence o arquivo local",
                   valor == segredo_env and origem == "env")

                saida = io.StringIO()
                chaves.status(saida)
                texto_status = saida.getvalue()
                ok("status nao mostra valor nem sufixo",
                   segredo_env not in texto_status and "ZXQ9" not in texto_status
                   and "DEEPGRAM_API_KEY=configurada (env)" in texto_status)

                contrato = chaves.contrato_cloud(["DEEPGRAM_API_KEY"])
                serializado = json.dumps(contrato, ensure_ascii=False)
                cred = contrato["credenciais"][0]
                ok("contrato cloud contem somente estado mascarado",
                   cred == {"nome": "DEEPGRAM_API_KEY", "configurada": True,
                            "origem": "env", "via_ambiente": True,
                            "via_arquivo_local": False}
                   and segredo_env not in serializado and "ZXQ9" not in serializado)

                escopo = base / "escopo"
                escopo.mkdir()
                (escopo / "limpo.log").write_text("execucao concluida\n", encoding="utf-8")
                limpo = chaves.escanear_segredo("DEEPGRAM_API_KEY", [escopo])
                ok("scanner aprova escopo limpo",
                   limpo["executado"] and limpo["ok"]
                   and limpo["arquivos_varridos"] == 1)

                # Controle negativo: os tres formatos precisam ser detectados.
                (escopo / "vazou.log").write_text(
                    "authorization=" + segredo_env + "\n", encoding="utf-8")
                nome_malicioso = escopo / ("arquivo-" + segredo_env + ".txt")
                # Filename-only: o conteudo e deliberadamente limpo para provar
                # que o scanner mede o nome sem depender de um segundo vazamento.
                nome_malicioso.write_text("conteudo limpo\n", encoding="utf-8")
                apenas_nome = chaves.escanear_segredo(
                    "DEEPGRAM_API_KEY", [nome_malicioso])
                saida_apenas_nome = json.dumps(apenas_nome, ensure_ascii=False)
                ok("controle negativo filename-only reprova e sanitiza",
                   not apenas_nome["ok"]
                   and apenas_nome["arquivos_varridos"] == 1
                   and len(apenas_nome["ocorrencias"]) == 1
                   and apenas_nome["ocorrencias"][0].endswith("[nome]")
                   and "[SEGREDO]" in apenas_nome["ocorrencias"][0]
                   and "[conteudo]" not in saida_apenas_nome
                   and segredo_env not in saida_apenas_nome
                   and "ZXQ9" not in saida_apenas_nome)
                with zipfile.ZipFile(escopo / "artefato.zip", "w") as zf:
                    zf.writestr("logs/execucao.txt", "token=" + segredo_env)
                vazou = chaves.escanear_segredo("DEEPGRAM_API_KEY", [escopo])
                saida_vazou = json.dumps(vazou, ensure_ascii=False)
                ok("controle negativo detecta log, nome e ZIP",
                   not vazou["ok"] and len(vazou["ocorrencias"]) >= 3
                   and any("artefato.zip!logs/execucao.txt" in p
                           for p in vazou["ocorrencias"])
                   and any("[SEGREDO]" in p and p.endswith("[nome]")
                           for p in vazou["ocorrencias"]))
                ok("scanner nunca repete valor nem sufixo identificador",
                   segredo_env not in saida_vazou and "ZXQ9" not in saida_vazou
                   and "[SEGREDO]" in saida_vazou)

                env_cli = dict(os.environ)
                contrato_cli = subprocess.run(
                    [sys.executable, str(CHAVES), "--contrato-cloud"],
                    text=True, capture_output=True, env=env_cli)
                scan_cli = subprocess.run(
                    [sys.executable, str(CHAVES), "--scan-segredos",
                     "--scan-dir", str(escopo)],
                    text=True, capture_output=True, env=env_cli)
                combinado = contrato_cli.stdout + contrato_cli.stderr \
                    + scan_cli.stdout + scan_cli.stderr
                ok("CLI mascara contrato e scanner e reprova o vazamento",
                   contrato_cli.returncode == 0 and scan_cli.returncode == 1
                   and segredo_env not in combinado and "ZXQ9" not in combinado)

    print("%d checagens, %d falha(s)" % (varridos, len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(executar())
