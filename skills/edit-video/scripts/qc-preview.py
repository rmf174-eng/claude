#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qc-preview.py — a tela aconteceu?

    qc-preview.py <dir-producao>
        exit 0  a aprovação desta peça nasceu da UI, ou a produção é legado
        exit 1  a peça chegou ao fim sem ninguém aprovar na tela
        exit 2  erro de uso

🔴 POR QUE ESTE QC EXISTE (achado A9 da auditoria de 2026-08-10)

A ilha tinha a peça inteira: servidor de preview, timeline interativa, galeria de
estilos com preview renderizado, watcher de fila. E **nenhum item de bateria e
nenhum portão exigiam que ela tivesse sido usada.** O fluxo inteiro rodava verde
com a tela nunca aberta — medido em 2026-08-09, produção do bruto a 4 entregáveis
com todos os QCs verdes, `.preview/` inexistente no disco, escolha de estilo
virando pergunta no chat e o portão assinado pelo próprio agente.

O rastro sempre existiu: o servidor grava `.preview/servidor.json` com pid e
`iniciado_em`; a aprovação registra de onde nasceu; o consumo de evento sem
servidor é marcado. **O produto registrava a verdade e não a cobrava.** Este
script é quem cobra.

E ele cobra a coisa certa, não a fácil: não basta `.preview/` existir no disco —
uma sessão aberta e ignorada é o mesmo silêncio de antes. O que ele exige é a
APROVAÇÃO com `fonte: ui-save`, que só o servidor grava depois de uma sessão da
UI, com contexto fresco e capacidade de uso único. Isso acusa o bypass direto e
o replay; não é atestado criptográfico de gesto humano contra um processo local
que automatize a sessão inteira. O agente é proibido pelo contrato de fazê-lo.

── o caso que ele pega e um "existe .preview/" não pegaria ──────────────────────
`.aprovacao.json` degradado convivendo com `.preview/servidor.json` de uma sessão
que esteve viva: a tela ESTAVA de pé, e mesmo assim a aprovação veio do terminal.
É o pior dos dois mundos — a UI existia e foi contornada — e sai com o motivo
nomeado, não como um genérico "sem aprovação".
"""

import json
import os
import sys

SCHEMA = "benchmark.qc-preview/v1"
FONTE_UI = "ui-save"


def _ler_json(caminho, default=None):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _legado(dirp):
    """Mesma lista fechada do `qc-portao.py` — uma fonte, não duas."""
    env = os.environ.get("BENCH_PORTAO_LEGADO")
    caminho = env or os.path.join(
        os.path.dirname(os.path.abspath(dirp.rstrip("/"))), "_portao-legado.json")
    obj = _ler_json(caminho)
    if not isinstance(obj, dict):
        return set()
    return {str(s) for s in (obj.get("producoes") or [])}


def avaliar(dirp, alvo="fase-1"):
    r = {"schema": SCHEMA, "dir": dirp, "alvo": alvo, "veredito": None,
         "fonte": None, "sessao": None, "motivos": [], "exit": 0}
    slug = os.path.basename(os.path.abspath(dirp.rstrip("/")))
    prev = os.path.join(dirp, ".preview")

    sessao = _ler_json(os.path.join(prev, "servidor.json"))
    if sessao:
        r["sessao"] = {"iniciado_em": sessao.get("iniciado_em"),
                       "pid": sessao.get("pid")}

    est = _ler_json(os.path.join(prev, "estado.json")) or {}
    do_estado = [a for a in (est.get("aprovacoes") or []) if a.get("alvo") == alvo]
    local = _ler_json(os.path.join(dirp, ".aprovacao.json"))

    ap = do_estado[-1] if do_estado else (local if local else None)
    if ap:
        r["fonte"] = ap.get("fonte")

    if ap and ap.get("fonte") == FONTE_UI and ap.get("valida") is not False:
        r["veredito"] = "aprovado-na-tela"
        return r

    if slug in _legado(dirp):
        r["veredito"] = "legado"
        r["motivos"].append("produção nomeada na lista de legado — anterior ao "
                            "portão de autoria, e nada publicado se re-renderiza")
        return r

    r["exit"] = 1
    if ap and sessao:
        r["veredito"] = "ui-contornada"
        r["motivos"].append(
            "a sessão de preview EXISTIU (iniciada em %s) e mesmo assim a "
            "aprovação nasceu fora dela (fonte %r). A tela estava de pé e foi "
            "contornada." % (sessao.get("iniciado_em") or "?",
                             ap.get("fonte") or "não registrada"))
    elif ap:
        r["veredito"] = "aprovado-fora-da-tela"
        r["motivos"].append(
            "aprovação com fonte %r e nenhuma sessão de preview no disco: o "
            "creator não viu esta peça na tela." % (ap.get("fonte") or "não registrada"))
    elif sessao:
        r["veredito"] = "tela-aberta-sem-aprovacao"
        r["motivos"].append(
            "a UI subiu (%s) e ninguém aprovou nada: a peça chegou ao fim sem o "
            "gesto que fecha a fase 1." % (sessao.get("iniciado_em") or "?"))
    else:
        r["veredito"] = "tela-nunca-abriu"
        r["motivos"].append(
            "sem .preview/servidor.json e sem aprovação: a Etapa 0 do SKILL.md "
            "(a UI sobe antes de tudo) não aconteceu. Ela não falha com erro — "
            "ela simplesmente não acontece, e o silêncio parece sucesso.")
    r["motivos"].append(
        "o caminho: `servidor.py sessao --dir <dir>` + `servir`, e o creator "
        "clica em ✓ Aprovar o corte. Sem browser, `qc-portao.py <dir> --aprovar "
        "--por <nome>` grava cli-degradado, que este QC continua reprovando.")
    return r


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__)
        return 2
    dirp = argv[0]
    if not os.path.isdir(dirp):
        sys.stderr.write("qc-preview: diretório não existe: %s\n" % dirp)
        return 2
    como_json = "--json" in argv
    r = avaliar(dirp)
    if como_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print("PREVIEW %s · fonte %s · sessao %s"
              % (r["veredito"], r["fonte"] or "—",
                 (r["sessao"] or {}).get("iniciado_em") or "nenhuma"))
        for m in r["motivos"]:
            print("   %s" % m)
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
