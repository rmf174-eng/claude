#!/usr/bin/env python3
"""Contrato parametrizado das CLIs públicas de corte e perfil.

Ajuda sai 0. Argumento ausente ou caminho inválido sai não zero com mensagem
curta. Nenhum desses caminhos de UX pode atravessar para traceback de runtime.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent
CASOS = {
    "cortes-do-bruto.py": {
        "help": ["--help"],
        "ausente": [],
        "invalido": ["/definitivamente/inexistente/video.mp4"],
    },
    "bordas.py": {
        "help": ["--help"],
        "ausente": [],
        "invalido": ["/definitivamente/inexistente/producao"],
    },
    "perfil.py": {
        "help": ["--help"],
        "ausente": [],
        "invalido": ["validar", "/definitivamente/inexistente/perfil.json"],
    },
}


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

    for script, casos in CASOS.items():
        alvo = SCRIPTS / script
        for tipo, args in casos.items():
            r = subprocess.run([sys.executable, str(alvo), *args],
                               capture_output=True, text=True)
            texto = r.stdout + r.stderr
            rotulo = "%s %s" % (script, tipo)
            if tipo == "help":
                ok(rotulo + " sai 0", r.returncode == 0,
                   "exit %d" % r.returncode)
                ok(rotulo + " mostra uso sem falso erro",
                   ("Uso:" in texto or "usage:" in texto or "CLI" in texto)
                   and "comando desconhecido" not in texto)
            else:
                ok(rotulo + " recusa", r.returncode != 0,
                   "exit %d" % r.returncode)
                ok(rotulo + " explica o erro",
                   any(x in texto.lower() for x in
                       ("uso", "usage", "falta", "exige", "não existe")))
            ok(rotulo + " sem traceback", "Traceback" not in texto)

    print("%d checagens, %d falha(s)" % (medidos, len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(executar())
