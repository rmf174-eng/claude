#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validador compartilhado da arvore e do recibo de uma release ILHA.

Este modulo viaja no produto. A fabrica ``criar-release.py`` delega seus dois
gates finais para ca, e os testes extraidos chamam a mesma implementacao.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Iterable


VERSAO_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
HEADING_RE = re.compile(
    r"^##[ \t]+v(?P<versao>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))(?=\s|$)",
    re.MULTILINE,
)
ARQUIVOS_RAIZ = (
    ".codex-plugin/plugin.json",
    "README.md",
    "CHANGELOG.md",
)
ALIAS_CANONICO = ".claude/skills"
ALIAS_PLUGIN = "skills"
BASE_FORMAL = (0, 15)
CAMPOS_MANIFESTO_PRODUTO = (
    "schema", "produto", "versao_manifesto", "raiz", "ativos", "chaves",
    "plataformas",
)
CAMPOS_MANIFESTO = frozenset(
    (*CAMPOS_MANIFESTO_PRODUTO, "_reduzido_pelo_export"))
MARCADOR_MANIFESTO_REDUZIDO = (
    "O corte (inclui/nunca_sai/excecoes) e a política de release "
    "(export) são da árvore FONTE e não viajam: a lista de nomes "
    "proibidos e a lista de arquivos escondidos entregariam o "
    "inventário que o corte existe para não entregar. "
    "SPEC-000 §3.10, exportar-produto.py decisão 5."
)
SMOKES_EXPORTADOS = (
    "skills/edit-video/preview/tests/test_timeline_zoom.py",
    "skills/edit-video/preview/tests/test_aprovacao_nonce.py",
    "skills/edit-video/scripts/tests/test_galeria_estilos.py",
    "skills/edit-video/scripts/tests/test_contrato_ui.py",
)


class erro_validacao(RuntimeError):
    """Falha orientada na integridade estrutural da release."""


def _versao(texto: str) -> tuple[int, int]:
    casamento = VERSAO_RE.fullmatch(texto) if isinstance(texto, str) else None
    if casamento is None:
        raise erro_validacao("versao invalida: esperado X.Y")
    return int(casamento.group(1)), int(casamento.group(2))


def _exigir_base_formal(texto: str) -> tuple[int, int]:
    versao = _versao(texto)
    if versao < BASE_FORMAL:
        raise erro_validacao(
            "a serie formal comeca em v%d.%d" % BASE_FORMAL)
    return versao


def _ler_json_regular(caminho: Path, rotulo: str) -> dict:
    if os.path.lexists(caminho):
        try:
            estado = caminho.lstat()
        except OSError as exc:
            raise erro_validacao("nao foi possivel medir %s: %s" %
                                 (rotulo, exc)) from exc
        if stat.S_ISLNK(estado.st_mode) or not stat.S_ISREG(estado.st_mode):
            raise erro_validacao("%s precisa ser arquivo regular, sem symlink" %
                                 rotulo)
    else:
        raise erro_validacao("%s ausente" % rotulo)
    try:
        objeto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise erro_validacao("JSON invalido em %s: %s" % (rotulo, exc)) from exc
    if not isinstance(objeto, dict):
        raise erro_validacao("JSON raiz deve ser objeto: %s" % rotulo)
    return objeto


def _sha256_arquivo(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _esta_excluido(relativo: str, excluidos: set[str]) -> bool:
    return any(
        relativo == item or relativo.startswith(item.rstrip("/") + "/")
        for item in excluidos
    )


def inventariar_arvore(
    raiz: Path, *, excluir: Iterable[str] = ()
) -> tuple[tuple[str, str, int, int, str], ...]:
    """Inventario canonico usado tanto no payload quanto nos aliases."""
    if raiz.is_symlink() or not raiz.is_dir():
        raise erro_validacao("arvore invalida: %s" % raiz)
    excluidos = {PurePosixPath(item).as_posix().rstrip("/") for item in excluir}
    entradas: list[tuple[str, str, int, int, str]] = []
    for diretorio, subdirs, arquivos in os.walk(raiz, followlinks=False):
        subdirs.sort()
        arquivos.sort()
        base = Path(diretorio)
        subdirs_mantidos = []
        for nome in subdirs:
            caminho = base / nome
            relativo = caminho.relative_to(raiz).as_posix()
            if _esta_excluido(relativo, excluidos):
                continue
            estado = caminho.lstat()
            if stat.S_ISLNK(estado.st_mode):
                raise erro_validacao(
                    "link simbolico nao permitido no pacote: %s" % relativo)
            if not stat.S_ISDIR(estado.st_mode):
                raise erro_validacao("entrada especial nao permitida: %s" % relativo)
            entradas.append((relativo, "diretorio", stat.S_IMODE(estado.st_mode),
                             0, ""))
            subdirs_mantidos.append(nome)
        subdirs[:] = subdirs_mantidos
        for nome in arquivos:
            caminho = base / nome
            relativo = caminho.relative_to(raiz).as_posix()
            if _esta_excluido(relativo, excluidos):
                continue
            estado = caminho.lstat()
            if stat.S_ISLNK(estado.st_mode):
                raise erro_validacao(
                    "link simbolico nao permitido no pacote: %s" % relativo)
            if not stat.S_ISREG(estado.st_mode):
                raise erro_validacao("entrada especial nao permitida: %s" % relativo)
            entradas.append((relativo, "arquivo", stat.S_IMODE(estado.st_mode),
                             estado.st_size, _sha256_arquivo(caminho)))
    return tuple(sorted(entradas))


def resumo_arvore(
    raiz: Path, *, excluir: Iterable[str] = ()
) -> tuple[str, int, int]:
    resumo = hashlib.sha256()
    arquivos = 0
    bytes_total = 0
    for caminho, tipo, modo, tamanho, sha256 in inventariar_arvore(
            raiz, excluir=excluir):
        linha = json.dumps({
            "caminho": caminho,
            "modo": modo,
            "sha256": sha256,
            "tamanho": tamanho,
            "tipo": tipo,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        resumo.update(linha.encode("utf-8") + b"\n")
        if tipo == "arquivo":
            arquivos += 1
            bytes_total += tamanho
    return resumo.hexdigest(), arquivos, bytes_total


def _validar_manifesto_reduzido(raiz: Path) -> dict:
    caminho = raiz / "tools" / "pacote" / "MANIFESTO.json"
    manifesto = _ler_json_regular(caminho, "MANIFESTO reduzido")
    campos = frozenset(manifesto)
    if campos != CAMPOS_MANIFESTO:
        faltam = sorted(CAMPOS_MANIFESTO - campos)
        sobram = sorted(campos - CAMPOS_MANIFESTO)
        raise erro_validacao(
            "whitelist do MANIFESTO reduzido diverge: faltam=%s sobram=%s" %
            (faltam, sobram))
    if (manifesto.get("schema") != "benchmark.pacote/v1"
            or manifesto.get("produto") != "ilha-de-edicao"
            or manifesto.get("versao_manifesto") != 1
            or manifesto.get("_reduzido_pelo_export")
            != MARCADOR_MANIFESTO_REDUZIDO):
        raise erro_validacao("MANIFESTO reduzido tem identidade invalida")
    for campo in ("raiz", "ativos", "chaves", "plataformas"):
        if not isinstance(manifesto.get(campo), dict):
            raise erro_validacao("MANIFESTO reduzido tem campo invalido: %s" % campo)
    return manifesto


def validar_raiz_exportada(raiz: Path, versao: str) -> dict:
    """Valida arquivos obrigatorios, versoes, aliases e manifesto reduzido."""
    _exigir_base_formal(versao)
    for relativo in ARQUIVOS_RAIZ:
        caminho = raiz / relativo
        if caminho.is_symlink() or not caminho.is_file():
            raise erro_validacao(
                "arquivo obrigatorio fora da raiz do ZIP: %s" % relativo)

    plugin = _ler_json_regular(
        raiz / ".codex-plugin" / "plugin.json", "plugin.json")
    if plugin.get("name") != "ilha":
        raise erro_validacao(
            "nome do plugin divergente: esperado 'ilha', encontrado %r" %
            plugin.get("name"))
    esperado_plugin = versao + ".0"
    if plugin.get("version") != esperado_plugin:
        raise erro_validacao(
            "versao do plugin divergente: esperado %s, encontrado %r" %
            (esperado_plugin, plugin.get("version")))

    changelog = raiz / "CHANGELOG.md"
    try:
        texto = changelog.read_text(encoding="utf-8")
    except OSError as exc:
        raise erro_validacao("nao foi possivel ler CHANGELOG.md: %s" % exc) from exc
    headings = [m.group("versao") for m in HEADING_RE.finditer(texto)]
    if not headings:
        raise erro_validacao(
            "CHANGELOG.md nao contem heading de release no formato ## vX.Y")
    if headings[0] != versao:
        raise erro_validacao(
            "a release mais recente do CHANGELOG deve ser ## v%s; encontrado ## v%s"
            % (versao, headings[0]))
    if len(headings) != len(set(headings)):
        raise erro_validacao("CHANGELOG.md contem versao duplicada")
    ordem = [_versao(item) for item in headings]
    if any(anterior <= seguinte for anterior, seguinte in zip(ordem, ordem[1:])):
        raise erro_validacao("CHANGELOG.md deve estar em ordem decrescente de versao")

    canonico = raiz / ALIAS_CANONICO
    plugin_alias = raiz / ALIAS_PLUGIN
    if not canonico.is_dir() or canonico.is_symlink():
        raise erro_validacao("alias canonico ausente ou invalido: %s" % ALIAS_CANONICO)
    if not plugin_alias.is_dir() or plugin_alias.is_symlink():
        raise erro_validacao("alias do plugin ausente ou invalido: %s" % ALIAS_PLUGIN)
    arvore_canonica = inventariar_arvore(canonico)
    arvore_plugin = inventariar_arvore(plugin_alias)
    if arvore_canonica != arvore_plugin:
        caminhos_a = set(arvore_canonica)
        caminhos_b = set(arvore_plugin)
        diferenca = sorted(caminhos_a ^ caminhos_b)
        detalhe = diferenca[0][0] if diferenca else "conteudo desconhecido"
        raise erro_validacao("aliases divergentes em %s" % detalhe)

    _validar_manifesto_reduzido(raiz)
    return plugin


def validar_metadados_release(raiz: Path, versao: str) -> dict:
    """Valida o recibo e o hash do payload contra a arvore atual."""
    _exigir_base_formal(versao)
    dados = _ler_json_regular(raiz / "RELEASE.json", "RELEASE.json")
    if dados.get("schema") != "ilha.release/v1":
        raise erro_validacao("RELEASE.json tem schema divergente")
    if dados.get("version") != versao:
        raise erro_validacao("RELEASE.json tem versao divergente")
    if dados.get("plugin_version") != versao + ".0":
        raise erro_validacao("RELEASE.json tem versao de plugin divergente")
    if dados.get("artifact") != "ILHA-v%s.zip" % versao:
        raise erro_validacao("RELEASE.json tem nome de artefato divergente")
    gerador = "/".join(("tools", "pacote", "criar-release.py"))
    if dados.get("generated_by") != gerador:
        raise erro_validacao("RELEASE.json nao foi gerado pelo criador oficial")

    fonte = dados.get("source")
    if (not isinstance(fonte, dict)
            or set(fonte) != {"repo", "head", "dirty"}
            or fonte.get("repo") != "benchmark-system/ilha"
            or not isinstance(fonte.get("head"), str)
            or re.fullmatch(r"[0-9a-f]{40}", fonte["head"]) is None
            or type(fonte.get("dirty")) is not bool):
        raise erro_validacao("RELEASE.json tem source ausente ou invalido")

    validacao_esperada = {
        "source_gate": "scripts/verificar.sh",
        "plugin_validator": ["source", "staging", "extraction"],
        "exported_test_gate": {
            "pattern": "test_*.py",
            "coverage": "all distributed tests, semantic aliases once",
            "order": "lexicographic",
        },
        "export_smoke_tests": list(SMOKES_EXPORTADOS),
    }
    if dados.get("validation") != validacao_esperada:
        raise erro_validacao("RELEASE.json tem validation ausente ou divergente")

    payload = dados.get("payload")
    if (not isinstance(payload, dict)
            or payload.get("hash_excludes") != ["RELEASE.json"]):
        raise erro_validacao("RELEASE.json sem contrato de payload valido")
    arvore, arquivos, bytes_total = resumo_arvore(
        raiz, excluir={"RELEASE.json"})
    esperado = (payload.get("tree_sha256"), payload.get("files"),
                payload.get("bytes"))
    atual = (arvore, arquivos, bytes_total)
    if esperado != atual:
        raise erro_validacao("payload diverge do hash declarado em RELEASE.json")
    serializado = json.dumps(dados, ensure_ascii=False)
    marcadores_pessoais = (
        "/".join(("", "Users", "")),
        "/".join(("", "home", "")),
        ":\\\\" + "Users" + "\\\\",
    )
    if any(marcador in serializado for marcador in marcadores_pessoais):
        raise erro_validacao("RELEASE.json contem caminho pessoal")
    return dados
