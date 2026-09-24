#!/usr/bin/env python3
"""Emite UMA linha por save novo do preview — para a tool Monitor (persistent).

Sem isto, o creator salva, vê o toast e nada acontece: é o modo de falha que o
próprio ref-A documenta (ref-A/SKILL.md:123-131, "the failure is silent on both
ends"). Aqui o watcher NÃO depende de ninguém apagar arquivo: ele guarda os nomes
já vistos e a fila é append-only.

    <dir-producao>/.preview/pendentes/*.json   ← o servidor grava (SPEC-17)
    <dir-producao>/.preview/aplicados/*.json   ← o agente MOVE ao aplicar (SPEC-16)

O ACK é o move. Um arquivo movido continua "visto" e não re-notifica.

Uso:
    python3 watch-preview.py <dir-producao> [--intervalo 2] [--uma-passada]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

INTERVALO_PADRAO = 2.0
LIMITE_RESUMO = 160


def _resumo(payload) -> str:
    """Resumo curto e legível do payload — o Monitor mostra a linha inteira."""
    if payload is None:
        return "sem payload"
    if isinstance(payload, dict):
        partes = []
        for chave, valor in list(payload.items())[:4]:
            if isinstance(valor, list):
                partes.append(f"{chave}={len(valor)} item(ns)")
            elif isinstance(valor, dict):
                partes.append(f"{chave}={{{len(valor)} campo(s)}}")
            else:
                texto = str(valor).replace("\n", " ")
                partes.append(f"{chave}={texto[:60]}")
        extra = "" if len(payload) <= 4 else f" (+{len(payload) - 4})"
        return ", ".join(partes) + extra
    if isinstance(payload, list):
        return f"{len(payload)} item(ns)"
    return str(payload)[:LIMITE_RESUMO]


def _linha(arquivo: Path) -> str:
    try:
        obj = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"preview: evento novo (ilegível ainda) — {arquivo.name}"
    tipo = obj.get("tipo", "?")
    quando = obj.get("salvo_em", "?")
    payload = obj.get("payload")
    resumo = _resumo(payload)
    if len(resumo) > LIMITE_RESUMO:
        resumo = resumo[: LIMITE_RESUMO - 1] + "…"
    # 🔴 SEGUNDA ESCOLHA NÃO É PRIMEIRA ESCOLHA. Quando o creator volta à aba com
    # um estilo JÁ aplicado e salva de novo, a galeria manda `rerender: true`. Sem
    # dizer isso aqui, a linha é idêntica à da primeira vez e a leitura natural é
    # "ele acabou de escolher" — quando o pedido é REFAZER o que já foi renderizado.
    marca = ""
    if isinstance(payload, dict) and payload.get("rerender"):
        marca = " · 🔁 REFAÇA a Fase 2 com estas escolhas (troca de estilo já aplicado)"
    return (f"preview [{tipo}] {quando} — {resumo}{marca} · aplicar e mover para "
            f"aplicados/: {arquivo}")


def observar(raiz: Path, intervalo: float, uma_passada: bool = False) -> int:
    pendentes = raiz / ".preview" / "pendentes"
    pendentes.mkdir(parents=True, exist_ok=True)   # o dir pode não existir ainda
    aplicados = raiz / ".preview" / "aplicados"

    vistos = {p.name for p in aplicados.glob("*.json")} if aplicados.is_dir() else set()
    ja = sorted(p for p in pendentes.glob("*.json") if p.name not in vistos)
    if ja:
        # uma linha só na largada: não repetir o histórico a cada rearme do Monitor
        print(f"preview: {len(ja)} evento(s) já pendentes em {pendentes} "
              f"(mais antigo: {ja[0].name})", flush=True)
        vistos.update(p.name for p in ja)

    while True:
        try:
            atuais = sorted(pendentes.glob("*.json"))
        except OSError:
            atuais = []
        for p in atuais:
            if p.name in vistos:
                continue
            vistos.add(p.name)
            print(_linha(p), flush=True)
        if uma_passada:
            return 0
        time.sleep(intervalo)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="watcher de saves do preview")
    ap.add_argument("dir", help="diretório da produção")
    ap.add_argument("--intervalo", type=float, default=INTERVALO_PADRAO)
    ap.add_argument("--uma-passada", action="store_true",
                    help="varre uma vez e sai (para teste)")
    args = ap.parse_args(argv)
    raiz = Path(args.dir).resolve()
    if not raiz.is_dir():
        print(f"erro: dir inexistente: {raiz}", file=sys.stderr)
        return 2
    try:
        return observar(raiz, args.intervalo, args.uma_passada)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
