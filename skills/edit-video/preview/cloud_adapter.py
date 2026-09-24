#!/usr/bin/env python3
"""Adaptador declarativo para uma superficie HTTPS de preview.

Este modulo nao cria tunel, nao publica porta e nao conhece endpoint do ChatGPT
Work. Ele apenas valida um endereco entregue pelo ambiente de hospedagem e o
associa a sessao local existente. Sem contrato completo e valido, a resposta e
sempre o endereco local em 127.0.0.1.

Contrato de ambiente:

* ILHA_PREVIEW_CLOUD_URL_TEMPLATE: URL HTTPS com ``{token}`` no caminho e,
  opcionalmente, ``{porta}``;
* ILHA_PREVIEW_CLOUD_ALLOWED_HOSTS: hosts exatos separados por virgula;
* ILHA_PREVIEW_CLOUD_EXPIRES_AT: instante RFC 3339 com fuso;
* ILHA_PREVIEW_CLOUD_AUTHENTICATED: ``1``/``true`` quando o proxy exige uma
  sessao autenticada antes de encaminhar a requisicao.

O template e o endpoint sao fornecidos pela plataforma. Nao existe default
inventado por este pacote.
"""

from __future__ import annotations

import os
import string
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit


ENV_TEMPLATE = "ILHA_PREVIEW_CLOUD_URL_TEMPLATE"
ENV_HOSTS = "ILHA_PREVIEW_CLOUD_ALLOWED_HOSTS"
ENV_EXPIRA = "ILHA_PREVIEW_CLOUD_EXPIRES_AT"
ENV_AUTENTICADO = "ILHA_PREVIEW_CLOUD_AUTHENTICATED"

# A sessao publica nunca pode durar mais que a sessao de UI do servidor. A
# plataforma pode entregar uma expiracao menor e renovar criando outra sessao.
TTL_MAX_S = 2 * 60 * 60


def _verdadeiro(valor: str | None) -> bool:
    return (valor or "").strip().lower() in {"1", "true", "yes", "on", "sim"}


def _fallback(url_local: str, configurado: bool, motivo: str) -> dict:
    return {
        "modo": "local",
        "url": url_local,
        "url_local": url_local,
        "cloud_configurada": bool(configurado),
        "autenticado": False,
        "isolado_por_token": True,
        "host_declarado": False,
        "host": "127.0.0.1",
        "expira_em": None,
        "expira_epoch": None,
        "motivo_fallback": motivo,
    }


def _campos_do_template(template: str) -> list[str] | None:
    campos = []
    try:
        partes = string.Formatter().parse(template)
        for _literal, campo, formato, conversao in partes:
            if campo is None:
                continue
            if campo not in {"token", "porta"} or formato or conversao:
                return None
            campos.append(campo)
    except ValueError:
        return None
    return campos


def _expiracao(valor: str, agora: float) -> tuple[float, str] | None:
    bruto = valor.strip()
    if bruto.endswith("Z"):
        bruto = bruto[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(bruto)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    epoch = dt.timestamp()
    if epoch <= agora or epoch - agora > TTL_MAX_S:
        return None
    return epoch, dt.isoformat(timespec="seconds")


def resolver(url_local: str, token: str, porta: int, *, ambiente=None,
             agora: float | None = None) -> dict:
    """Valida o contrato cloud ou devolve o fallback local seguro.

    A funcao nao faz requisicao de rede. O proxy e a autenticacao pertencem a
    plataforma que preenche o ambiente; o servidor continua em 127.0.0.1.
    """
    env = os.environ if ambiente is None else ambiente
    agora = datetime.now().astimezone().timestamp() if agora is None else float(agora)
    nomes = (ENV_TEMPLATE, ENV_HOSTS, ENV_EXPIRA, ENV_AUTENTICADO)
    configurado = any((env.get(n) or "").strip() for n in nomes)
    template = (env.get(ENV_TEMPLATE) or "").strip()
    if not configurado:
        return _fallback(url_local, False, "cloud_nao_configurada")
    if not template:
        return _fallback(url_local, True, "template_ausente")
    if not _verdadeiro(env.get(ENV_AUTENTICADO)):
        return _fallback(url_local, True, "proxy_nao_declarado_autenticado")

    campos = _campos_do_template(template)
    if campos is None or campos.count("token") != 1:
        return _fallback(url_local, True, "template_invalido")

    permitidos = {
        h.strip().lower().rstrip(".")
        for h in (env.get(ENV_HOSTS) or "").split(",") if h.strip()
    }
    if not permitidos or any(
            "/" in h or "@" in h or "://" in h or h.startswith("*.")
            for h in permitidos):
        return _fallback(url_local, True, "hosts_invalidos")

    exp = _expiracao(env.get(ENV_EXPIRA) or "", agora)
    if exp is None:
        return _fallback(url_local, True, "expiracao_invalida")
    expira_epoch, expira_em = exp

    try:
        publica = template.format(token=quote(str(token), safe=""), porta=int(porta))
        url = urlsplit(publica)
        host = (url.hostname or "").lower().rstrip(".")
        # A leitura de .port tambem valida porta malformada.
        _ = url.port
    except (KeyError, ValueError):
        return _fallback(url_local, True, "url_invalida")

    if url.scheme.lower() != "https" or not url.netloc or url.username or url.password:
        return _fallback(url_local, True, "https_obrigatorio")
    if url.fragment:
        return _fallback(url_local, True, "fragmento_proibido")
    if host not in permitidos:
        return _fallback(url_local, True, "host_nao_declarado")
    segmentos = [unquote(p) for p in url.path.split("/") if p]
    if str(token) not in segmentos:
        return _fallback(url_local, True, "token_fora_do_caminho")

    return {
        "modo": "cloud",
        "url": publica,
        "url_local": url_local,
        "cloud_configurada": True,
        "autenticado": True,
        "isolado_por_token": True,
        "host_declarado": True,
        "host": host,
        "host_header": url.netloc.lower(),
        "expira_em": expira_em,
        "expira_epoch": expira_epoch,
        "motivo_fallback": None,
    }

