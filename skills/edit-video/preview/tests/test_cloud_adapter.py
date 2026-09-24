#!/usr/bin/env python3
"""Testes focados do adaptador cloud, sem rede e sem endpoint ficticio."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


PREVIEW = Path(__file__).resolve().parents[1]
ADAPTADOR = PREVIEW / "cloud_adapter.py"
SERVIDOR = PREVIEW / "servidor.py"
NOMES_ENV = (
    "ILHA_PREVIEW_CLOUD_URL_TEMPLATE",
    "ILHA_PREVIEW_CLOUD_ALLOWED_HOSTS",
    "ILHA_PREVIEW_CLOUD_EXPIRES_AT",
    "ILHA_PREVIEW_CLOUD_AUTHENTICATED",
)


def _carregar(caminho: Path, nome: str):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@contextmanager
def _ambiente(valores):
    antes = {k: os.environ.get(k) for k in NOMES_ENV}
    try:
        for k in NOMES_ENV:
            if k in valores:
                os.environ[k] = valores[k]
            else:
                os.environ.pop(k, None)
        yield
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def executar() -> int:
    adaptador = _carregar(ADAPTADOR, "ilha_cloud_adapter_teste")
    servidor = _carregar(SERVIDOR, "ilha_servidor_cloud_teste")
    falhas = []
    n = 0

    def ok(nome, cond):
        nonlocal n
        n += 1
        print("  %s %s" % ("OK" if cond else "FALHA", nome))
        if not cond:
            falhas.append(nome)

    agora = 1_800_000_000.0
    local = "http://127.0.0.1:43123/token-fixture/"
    valido = {
        adaptador.ENV_TEMPLATE:
            "https://preview.work.example/sessoes/{token}/?porta={porta}",
        adaptador.ENV_HOSTS: "preview.work.example",
        adaptador.ENV_EXPIRA: _iso(agora + 600),
        adaptador.ENV_AUTENTICADO: "true",
    }

    fallback = adaptador.resolver(local, "token-fixture", 43123,
                                  ambiente={}, agora=agora)
    ok("sem contrato cai no loopback",
       fallback["modo"] == "local" and fallback["url"] == local
       and fallback["motivo_fallback"] == "cloud_nao_configurada")

    cloud = adaptador.resolver(local, "token-fixture", 43123,
                               ambiente=valido, agora=agora)
    ok("contrato completo aceita somente HTTPS declarado",
       cloud["modo"] == "cloud"
       and cloud["url"].startswith("https://preview.work.example/")
       and "/token-fixture/" in cloud["url"]
       and cloud["host_declarado"] and cloud["autenticado"]
       and cloud["isolado_por_token"] and cloud["expira_epoch"] == agora + 600)

    invalidos = [
        ({**valido, adaptador.ENV_TEMPLATE:
          "http://preview.work.example/sessoes/{token}/"}, "https_obrigatorio"),
        ({**valido, adaptador.ENV_TEMPLATE:
          "https://evil.example/sessoes/{token}/"}, "host_nao_declarado"),
        ({**valido, adaptador.ENV_TEMPLATE:
          "https://preview.work.example/sessoes/sem-token/"}, "template_invalido"),
        ({**valido, adaptador.ENV_AUTENTICADO: "false"},
         "proxy_nao_declarado_autenticado"),
        ({**valido, adaptador.ENV_HOSTS: "*.work.example"}, "hosts_invalidos"),
        ({**valido, adaptador.ENV_EXPIRA: _iso(agora - 1)}, "expiracao_invalida"),
        ({**valido, adaptador.ENV_EXPIRA:
          _iso(agora + adaptador.TTL_MAX_S + 1)}, "expiracao_invalida"),
    ]
    recusados = []
    for env, motivo in invalidos:
        recebido = adaptador.resolver(local, "token-fixture", 43123,
                                      ambiente=env, agora=agora)
        recusados.append(recebido["modo"] == "local"
                         and recebido["url"] == local
                         and recebido["motivo_fallback"] == motivo)
    ok("configuracoes inseguras nunca produzem URL publica", all(recusados))

    servidor.CFG.clear()
    servidor.CFG.update({"porta": 43123, "token": "token-fixture", "preview": cloud})
    handler = servidor.Handler.__new__(servidor.Handler)
    handler.headers = {"Host": "preview.work.example"}
    host_cloud_ok = handler._host_ok()
    handler.headers = {"Host": "preview.work.example.evil"}
    host_sufixo_ok = handler._host_ok()
    handler.headers = {"Host": "127.0.0.1:43123"}
    host_local_ok = handler._host_ok()
    ok("Host aceita apenas loopback ou host cloud exato",
       host_cloud_ok and host_local_ok and not host_sufixo_ok)
    ok("expiracao absoluta tem dentes",
       not servidor.cloud_expirada(cloud["expira_epoch"] - 1)
       and servidor.cloud_expirada(cloud["expira_epoch"]))

    servidor.CFG["raiz"] = Path(tempfile.gettempdir())
    servidor.CFG["app"] = PREVIEW / "app"
    servidor.CFG["altura"] = 90
    servidor.CFG["desde"] = agora
    cookie_cloud = handler._cookie_nova_sessao_ui().lower()
    servidor.CFG["preview"] = fallback
    cookie_local = handler._cookie_nova_sessao_ui().lower()
    ok("cookie remoto e Secure; cookie HTTP local continua funcional",
       "; secure" in cookie_cloud and "; secure" not in cookie_local)
    ok("backend permanece preso ao loopback", servidor.BIND_HOST == "127.0.0.1")

    # Integra a configuracao no registro de sessao sem abrir socket ou fazer rede.
    futuro_real = _iso(time.time() + 600)
    env_real = {**valido, adaptador.ENV_EXPIRA: futuro_real}
    with tempfile.TemporaryDirectory(prefix="ilha-preview-cloud-") as d, \
            _ambiente(env_real):
        sessao = servidor.abrir_sessao(Path(d), porta=43124)
        ok("servidor.json preserva URL local e contrato cloud",
           sessao["url"] == "http://127.0.0.1:43124/%s/" % sessao["token"]
           and sessao["url_local"] == sessao["url"]
           and sessao["url_preferida"].startswith(
               "https://preview.work.example/sessoes/%s/" % sessao["token"])
           and sessao["preview"]["expira_em"] == futuro_real)

    print("%d checagens, %d falha(s)" % (n, len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(executar())

