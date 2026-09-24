#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O perfil de peça, para quem NÃO é a `edit-video`.

🔴 O ACOPLAMENTO QUE ISTO DESFAZ (achado A21 da auditoria de 2026-08-10)

Três scripts da `broll-source` faziam, cada um, a mesma coisa:

    sys.path.insert(0, os.path.join(DIR, "..", "..", "edit-video", "scripts"))
    import perfil as perfil_mod

Isso é uma afirmação sobre a árvore inteira: "existe uma skill irmã chamada
`edit-video`, exatamente dois níveis acima, com um `scripts/perfil.py` dentro".
Duas coisas quebram nela, e as duas são o teste de modularidade do produto:

  · **instalar um bloco só** — quem levar a `broll-source` sem a `edit-video`
    recebe `ModuleNotFoundError` no import, antes da primeira linha útil;
  · **trocar de engine** — mover ou renomear a `edit-video` quebra um bloco que
    não tem nada a ver com ela.

O contraste estava dentro da própria árvore: a `transcribe` policia a própria
independência com um controle negativo (`test_timestamped.py:198-206`).

ESCOLHA REGISTRADA (o plano oferecia duas). Não promovemos o `perfil.py` a lib
compartilhada declarada no MANIFESTO: isso resolveria o "trocar de engine" e
NÃO resolveria o "instalar um bloco só", que é o teste que o produto promete.
O que vale aqui é o contrato: **o perfil resolvido é um arquivo**
(`<dir-producao>/perfil.json`, `benchmark.perfil-peca/v1`), e ler um arquivo não
exige a skill que o escreveu.

O import continua sendo TENTADO — com a ilha inteira instalada, o comportamento
é byte a byte o de antes, inclusive o catálogo de perfis por nome. Sem ela, o
bloco degrada para o arquivo e para o fallback DECLARADO, nomeando a fonte.
`buscar.py:297-302` é o modelo: fallback com o número escrito e o porquê.
"""

import json
import os
import sys

# O fallback é DECLARADO, e é o mesmo `FALLBACK_REELS` da SPEC-00: 1080×1920 a
# 30 fps. Ele não é "o formato certo" — é o formato que este bloco assume quando
# ninguém lhe disse qual é, e ele DIZ que assumiu.
FALLBACK = {
    "nome": "reels-fallback",
    "video": {"largura": 1080, "altura": 1920, "fps": 30, "aspecto": "9:16"},
}


def _modulo_perfil():
    """A `edit-video` quando ela existe, `None` quando não. Nunca ImportError."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    alvo = os.path.join(aqui, "..", "..", "edit-video", "scripts")
    if not os.path.isfile(os.path.join(alvo, "perfil.py")):
        return None
    if alvo not in sys.path:
        sys.path.insert(0, alvo)
    try:
        import perfil as perfil_mod
    except ImportError:
        return None
    return perfil_mod


def _do_arquivo(alvo):
    """`<alvo>/perfil.json` ou `<alvo>` — o contrato, sem a skill que o escreveu."""
    cand = alvo if str(alvo).endswith(".json") else os.path.join(alvo or ".", "perfil.json")
    try:
        with open(cand, encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) and obj.get("video") else None


def carregar(alvo=".", quieto=True):
    """(perfil, fonte). `fonte ∈ {edit-video, perfil.json, fallback}`.

    Nunca levanta e nunca adivinha calado — a fonte volta junto para quem quiser
    imprimi-la, e o caminho de fallback avisa no stderr."""
    mod = _modulo_perfil()
    if mod is not None:
        try:
            return mod.carregar(alvo, quieto=quieto), "edit-video"
        except SystemExit:
            pass                      # o `carregar` da edit-video é CLI-first
    obj = _do_arquivo(alvo)
    if obj:
        return obj, "perfil.json"
    if not quieto:
        print("perfil: sem edit-video e sem perfil.json em %r — usando o "
              "FALLBACK declarado (%dx%d @ %s fps)"
              % (alvo, FALLBACK["video"]["largura"], FALLBACK["video"]["altura"],
                 FALLBACK["video"]["fps"]), file=sys.stderr)
    return json.loads(json.dumps(FALLBACK)), "fallback"


def por_nome(nome):
    """Um perfil do CATÁLOGO, por nome. Só existe com a `edit-video` no disco —
    o catálogo é dela. Devolve (perfil, fonte) ou (None, motivo)."""
    mod = _modulo_perfil()
    if mod is None:
        return None, ("o catálogo de perfis é da skill `edit-video`, que não está "
                      "instalada aqui. Passe um diretório de produção com "
                      "perfil.json, ou instale a ilha inteira.")
    arq = os.path.join(mod.DIR_PERFIS, nome + ".json")
    if not os.path.isfile(arq):
        disp = sorted(f[:-5] for f in os.listdir(mod.DIR_PERFIS)
                      if f.endswith(".json") and not f.startswith("_"))
        return None, "perfil %r não existe (tem: %s)" % (nome, ", ".join(disp))
    return mod.sobre_base(mod._ler(arq)), "edit-video"
