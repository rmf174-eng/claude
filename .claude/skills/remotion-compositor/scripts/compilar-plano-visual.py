#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liga plano-visual.json ao render Remotion e registra a prova pós-render.

    compilar-plano-visual.py <dir> preparar [--destino ...] [--public-dir ...]
    compilar-plano-visual.py <dir> renderizar --saida <video>
    compilar-plano-visual.py <dir> compor-final --base <video> --saida <video>

`preparar` embute o plano na partitura consumida pelo entry point. O diretor de
legenda fornece somente o item visual; timing e SFX vêm do plano. Depois do
render, `renderizar` executa o entry point oficial com os props compilados,
publica o vídeo de forma atômica e atualiza cada JSON Pointer com seu recibo.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Any


CONTRATO_PLANO = "benchmark.plano-visual/v1"
CONTRATO_PARTITURA = "benchmark.partitura/v1"
CONTRATO_COMPILACAO = "benchmark.partitura-plano-visual/v1"
CONTRATO_RECIBO = "benchmark.evento-visual-aplicado/v1"
CONTRATO_MANIFESTO = "benchmark.remotion-plano-visual-preparado/v1"
CONTRATO_RENDER = "benchmark.remotion-plano-visual-render/v1"
CONTRATO_FINAL = "benchmark.remotion-plano-visual-final/v1"
CONTRATO_PUBLIC_TREE = "benchmark.remotion-public-tree/v1"

RAIZ_ILHA = Path(__file__).resolve().parents[3]
COMPOSITOR = RAIZ_ILHA / "tools" / "remotion-compositor"
SFX_CANONICOS = COMPOSITOR / "public" / "sfx"


def _destino_padrao(d: Path) -> Path:
    return d / "remotion" / "partitura-compilada.json"


def _public_padrao(d: Path) -> Path:
    return d / "remotion" / "public"


def _manifesto_path(d: Path) -> Path:
    return d / "remotion" / "plano-visual-preparado.json"


def _manifesto_render_path(d: Path) -> Path:
    return d / "remotion" / "plano-visual-render.json"


def _manifesto_final_path(d: Path, final_rel: str) -> Path:
    """Sidecar determinístico por entregável, sem sobrescrever outra versão."""
    nome = "".join(
        c if c.isalnum() or c in "._-" else "-"
        for c in Path(final_rel).name
    )[:80] or "final"
    identidade = hashlib.sha256(final_rel.encode("utf-8")).hexdigest()
    return d / "remotion" / "plano-visual-finais" / ("%s.%s.json" %
                                                        (nome, identidade))


def _chave_casefold(nome: str) -> str:
    return unicodedata.normalize("NFKC", nome).casefold()


def _nome_final_reconhecido(nome: str) -> bool:
    if not nome.isascii():
        return False
    return re.fullmatch(r"(?:v-final|v2-final).*\.mp4", nome,
                        flags=re.ASCII | re.IGNORECASE) is not None


def _resolver_saida_final(d: Path, saida_arg: str) -> Path:
    """Aceita somente um nome oficial ASCII diretamente no root da produção."""
    entrada = Path(saida_arg)
    if ".." in entrada.parts:
        raise ErroCompilacao("--saida não aceita componente `..`")
    candidato = entrada if entrada.is_absolute() else d / entrada
    candidato = Path(os.path.abspath(str(candidato)))
    raiz = d.resolve()
    if candidato.parent != raiz:
        raise ErroCompilacao("--saida deve ficar diretamente na raiz da produção")
    if not _nome_final_reconhecido(candidato.name):
        raise ErroCompilacao(
            "--saida deve usar nome ASCII v-final*.mp4 ou v2-final*.mp4")
    try:
        modo = candidato.lstat().st_mode
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ErroCompilacao("não foi possível inspecionar --saida: %s" % exc) from exc
    else:
        if stat.S_ISLNK(modo):
            raise ErroCompilacao("--saida não pode ser symlink")
        if not stat.S_ISREG(modo):
            raise ErroCompilacao("--saida deve ser arquivo regular")
    return candidato


def _diretorio_manifestos_finais(d: Path, *, criar: bool) -> Path:
    """Valida cada pai lexical e nunca segue symlink para fora da produção."""
    atual = d.resolve()
    for nome in ("remotion", "plano-visual-finais"):
        atual = atual / nome
        try:
            modo = atual.lstat().st_mode
        except FileNotFoundError:
            if criar:
                try:
                    atual.mkdir()
                except OSError as exc:
                    raise ErroCompilacao(
                        "não foi possível criar diretório de manifestos: %s" % exc
                    ) from exc
            continue
        except OSError as exc:
            raise ErroCompilacao("não foi possível validar diretório de manifestos: %s"
                                 % exc) from exc
        else:
            if stat.S_ISLNK(modo):
                raise ErroCompilacao("diretório de manifestos não aceita symlink: %s"
                                     % atual)
            if not stat.S_ISDIR(modo):
                raise ErroCompilacao("diretório de manifestos é entrada irregular: %s"
                                     % atual)
    try:
        atual.resolve().relative_to(d.resolve())
    except (OSError, ValueError) as exc:
        raise ErroCompilacao("diretório de manifestos escapou da produção") from exc

    try:
        modo_atual = atual.lstat().st_mode
    except FileNotFoundError:
        modo_atual = None
    except OSError as exc:
        raise ErroCompilacao("não foi possível inspecionar manifestos finais: %s"
                             % exc) from exc
    if modo_atual is not None:
        por_nome: dict[str, list[Path]] = {}
        try:
            for entrada in atual.iterdir():
                if not _chave_casefold(entrada.name).endswith(".json"):
                    continue
                modo_entrada = entrada.lstat().st_mode
                if stat.S_ISLNK(modo_entrada) or not stat.S_ISREG(modo_entrada):
                    raise ErroCompilacao(
                        "manifesto final deve ser arquivo regular: %s" % entrada)
                por_nome.setdefault(_chave_casefold(entrada.name), []).append(entrada)
        except OSError as exc:
            raise ErroCompilacao("não foi possível listar manifestos finais: %s"
                                 % exc) from exc
        for grupo in por_nome.values():
            if len(grupo) > 1:
                raise ErroCompilacao(
                    "manifestos finais colidem por caixa/normalização: %s"
                    % ", ".join(sorted(p.name for p in grupo)))
    return atual


def _validar_manifesto_final_alvo(caminho: Path, final_rel: str) -> None:
    try:
        modo = caminho.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ErroCompilacao("não foi possível inspecionar manifesto final: %s"
                             % exc) from exc
    if stat.S_ISLNK(modo):
        raise ErroCompilacao("manifesto final não pode ser symlink: %s" % caminho)
    if not stat.S_ISREG(modo):
        raise ErroCompilacao("manifesto final deve ser arquivo regular: %s" % caminho)
    anterior = _ler_json(caminho)
    anterior_final = anterior.get("final") if isinstance(anterior, dict) else None
    if not isinstance(anterior_final, dict) \
            or anterior_final.get("arquivo") != final_rel:
        raise ErroCompilacao(
            "colisão de identidade no manifesto final: %s" % caminho)


def _recusar_colisao_casefold(saida: Path) -> None:
    """Evita duas saídas que só coexistiriam em filesystem case-sensitive."""
    try:
        irmaos = saida.parent.iterdir()
        for existente in irmaos:
            if existente.name != saida.name \
                    and _chave_casefold(existente.name) == _chave_casefold(saida.name):
                raise ErroCompilacao(
                    "--saida colide por caixa/normalização com %s" % existente.name)
    except OSError as exc:
        raise ErroCompilacao(
            "não foi possível verificar colisões de --saida: %s" % exc) from exc


class ErroCompilacao(RuntimeError):
    pass


def _ler_json(caminho: Path) -> Any:
    try:
        with caminho.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise ErroCompilacao("%s não é JSON legível: %s" % (caminho, exc)) from exc


def _bytes_json(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _gravar_atomico(caminho: Path, obj: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parcial = caminho.with_name(".%s.%d.%s.parcial"
                                 % (caminho.name, os.getpid(), uuid.uuid4().hex))
    try:
        with parcial.open("wb") as fh:
            fh.write(_bytes_json(obj))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(parcial, caminho)
    finally:
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass


def _copiar_atomico(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(".%s.%d.%s.parcial"
                                 % (destino.name, os.getpid(), uuid.uuid4().hex))
    try:
        with origem.open("rb") as src, parcial.open("wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(parcial, destino)
    finally:
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return "sha256:" + h.hexdigest()


def _sha256_obj(obj: Any) -> str:
    canon = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canon).hexdigest()


def _inventariar_public(d: Path, public_dir: Path) -> dict[str, Any]:
    """Descreve exatamente os bytes entregues ao `--public-dir` do Remotion.

    Symlinks são rejeitados, inclusive para destinos internos. Além de impedir
    escape da produção, isso evita que o mesmo manifesto passe a representar
    bytes diferentes entre o preparo e o render.
    """
    public_dir = _exigir_dentro_da_producao(d, public_dir, "public_dir")
    if not public_dir.is_dir():
        raise ErroCompilacao("public_dir não existe ou não é diretório: %s"
                             % public_dir)

    arquivos: list[dict[str, Any]] = []
    try:
        for atual, diretorios, nomes in os.walk(public_dir, followlinks=False):
            raiz_atual = Path(atual)
            for nome in diretorios:
                caminho = raiz_atual / nome
                if caminho.is_symlink():
                    raise ErroCompilacao(
                        "public_dir não aceita symlink: %s" % caminho)
                if not caminho.is_dir():
                    raise ErroCompilacao(
                        "entrada não regular em public_dir: %s" % caminho)
            for nome in nomes:
                caminho = raiz_atual / nome
                if caminho.is_symlink():
                    raise ErroCompilacao(
                        "public_dir não aceita symlink: %s" % caminho)
                if not caminho.is_file():
                    raise ErroCompilacao(
                        "entrada não regular em public_dir: %s" % caminho)
                antes = caminho.stat()
                digest = _sha256(caminho)
                depois = caminho.stat()
                identidade_antes = (antes.st_dev, antes.st_ino, antes.st_size,
                                     antes.st_mtime_ns)
                identidade_depois = (depois.st_dev, depois.st_ino, depois.st_size,
                                      depois.st_mtime_ns)
                if identidade_antes != identidade_depois:
                    raise ErroCompilacao(
                        "asset público mudou durante o inventário: %s" % caminho)
                arquivos.append({
                    "caminho": caminho.relative_to(public_dir).as_posix(),
                    "bytes": depois.st_size,
                    "sha256": digest,
                })
    except OSError as exc:
        raise ErroCompilacao(
            "não foi possível inventariar public_dir %s: %s" % (public_dir, exc)
        ) from exc

    arquivos.sort(key=lambda item: item["caminho"])
    inventario: dict[str, Any] = {
        "contrato": CONTRATO_PUBLIC_TREE,
        "raiz": public_dir.relative_to(d.resolve()).as_posix(),
        "arquivos": arquivos,
        "total_arquivos": len(arquivos),
        "total_bytes": sum(item["bytes"] for item in arquivos),
    }
    inventario["sha256"] = _sha256_obj(inventario)
    return inventario


def _dentro(caminho: Path, base: Path) -> bool:
    try:
        caminho.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _exigir_dentro_da_producao(d: Path, caminho: Path, rotulo: str) -> Path:
    resolvido = caminho.resolve()
    if not _dentro(resolvido, d):
        raise ErroCompilacao("%s precisa ficar dentro da produção: %s"
                             % (rotulo, caminho))
    return resolvido


def _caminho_cli(d: Path, valor: str | None, padrao: Path) -> Path:
    if not valor:
        return padrao
    caminho = Path(valor)
    return caminho.resolve() if caminho.is_absolute() else (d / caminho).resolve()


def _rel_da_producao(d: Path, valor: Any, rotulo: str) -> Path:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroCompilacao("%s deve ser caminho relativo" % rotulo)
    rel = Path(valor)
    if rel.is_absolute() or ".." in rel.parts:
        raise ErroCompilacao("%s aponta para fora da produção: %s" % (rotulo, valor))
    caminho = (d / rel).resolve()
    if not _dentro(caminho, d):
        raise ErroCompilacao("%s aponta para fora da produção: %s" % (rotulo, valor))
    return caminho


def _plano(d: Path) -> dict[str, Any]:
    caminho = d / "plano-visual.json"
    plano = _ler_json(caminho)
    if not isinstance(plano, dict) or plano.get("contrato") != CONTRATO_PLANO:
        raise ErroCompilacao("%s deve usar %s" % (caminho, CONTRATO_PLANO))
    if not isinstance(plano.get("direcao_edicao"), dict):
        raise ErroCompilacao("plano-visual.json não contém direcao_edicao")
    if not isinstance(plano.get("eventos"), list):
        raise ErroCompilacao("plano-visual.json.eventos deve ser lista")
    return plano


def _ref_do_evento(d: Path, evento: dict[str, Any]) -> tuple[Path, str]:
    eid = evento.get("id") or "evento sem id"
    impl = evento.get("implementacao")
    if not isinstance(impl, dict):
        raise ErroCompilacao("evento %s não contém implementacao" % eid)
    artefato = _rel_da_producao(d, impl.get("artefato"),
                                "evento %s implementacao.artefato" % eid)
    ref = impl.get("ref")
    if not isinstance(ref, dict) or ref.get("tipo") != "json-pointer" \
            or not isinstance(ref.get("valor"), str) or not ref["valor"].startswith("/"):
        raise ErroCompilacao(
            "evento %s: o caminho Remotion exige ref json-pointer" % eid)
    return artefato, ref["valor"]


def _resolver_pointer(obj: Any, ponteiro: str) -> Any:
    atual = obj
    for parte in ponteiro[1:].split("/"):
        chave = parte.replace("~1", "/").replace("~0", "~")
        if isinstance(atual, dict) and chave in atual:
            atual = atual[chave]
        elif isinstance(atual, list) and chave.isdigit() and int(chave) < len(atual):
            atual = atual[int(chave)]
        else:
            raise ErroCompilacao("JSON Pointer %s não existe" % ponteiro)
    return atual


def _fonte_partitura(d: Path, plano: dict[str, Any]) -> Path:
    fontes = set()
    for evento in plano["eventos"]:
        if not isinstance(evento, dict):
            raise ErroCompilacao("evento do plano não é objeto")
        artefato, _ = _ref_do_evento(d, evento)
        if artefato.name != "partitura.json":
            raise ErroCompilacao(
                "evento %s aponta para %s; o entry point Partitura só compila "
                "implementações em partitura.json" % (evento.get("id"), artefato.name))
        fontes.add(artefato)
    if not fontes:
        fontes.add((d / "partitura.json").resolve())
    if len(fontes) != 1:
        raise ErroCompilacao("uma composição não pode misturar partituras: %s"
                             % ", ".join(str(x) for x in sorted(fontes)))
    fonte = next(iter(fontes))
    if not fonte.is_file():
        raise ErroCompilacao("partitura de implementação não existe: %s" % fonte)
    return fonte


def _resolver_asset(d: Path, asset: str) -> Path:
    p = Path(asset)
    if p.is_absolute() or ".." in p.parts:
        raise ErroCompilacao("asset SFX aponta para fora da produção/biblioteca: %s" % asset)
    nomes = [p] + ([Path(str(p) + ".wav")] if not p.suffix else [])
    candidatos: list[Path] = []
    for nome in nomes:
        candidatos.extend((d / nome, d / "sfx" / nome))
        partes = nome.parts[1:] if nome.parts and nome.parts[0] == "sfx" else nome.parts
        candidatos.append(SFX_CANONICOS.joinpath(*partes))
    for candidato in candidatos:
        resolvido = candidato.resolve()
        if resolvido.is_file() \
                and (_dentro(resolvido, d) or _dentro(resolvido, SFX_CANONICOS)):
            return resolvido
    raise ErroCompilacao("asset SFX não existe: %s" % asset)


def _compilar_assets(d: Path, plano: dict[str, Any], public_dir: Path) -> tuple[dict[str, Any], list[str]]:
    compilado = copy.deepcopy(plano)
    politica = compilado["direcao_edicao"].get("sfx")
    copiados: list[str] = []
    for evento in compilado["eventos"]:
        som = evento.get("som")
        if not isinstance(som, dict) or som.get("decisao") != "usar":
            continue
        if politica != "automatico":
            raise ErroCompilacao(
                "evento %s usa SFX, mas direcao_edicao.sfx=%s"
                % (evento.get("id"), politica))
        asset = som.get("asset")
        if not isinstance(asset, str) or not asset:
            raise ErroCompilacao("evento %s usa SFX sem asset" % evento.get("id"))
        origem = _resolver_asset(d, asset)
        if _dentro(origem, public_dir):
            rel = origem.relative_to(public_dir.resolve()).as_posix()
        else:
            digest = _sha256(origem).split(":", 1)[1][:12]
            nome = "%s-%s%s" % (origem.stem, digest, origem.suffix or ".wav")
            destino = public_dir / "sfx" / nome
            if not destino.is_file() or _sha256(destino) != _sha256(origem):
                _copiar_atomico(origem, destino)
                copiados.append(str(destino))
            rel = destino.relative_to(public_dir.resolve()).as_posix()
        som["asset_publico"] = rel
    return compilado, copiados


def preparar(d: Path, destino: Path, public_dir: Path) -> dict[str, Any]:
    plano = _plano(d)
    fonte = _fonte_partitura(d, plano)
    destino = _exigir_dentro_da_producao(d, destino, "--destino")
    public_dir = _exigir_dentro_da_producao(d, public_dir, "--public-dir")
    if destino == fonte:
        raise ErroCompilacao(
            "--destino não pode sobrescrever a partitura fonte; use o artefato "
            "canônico remotion/partitura-compilada.json")
    partitura = _ler_json(fonte)
    if not isinstance(partitura, dict) or partitura.get("contrato") != CONTRATO_PARTITURA:
        raise ErroCompilacao("%s deve usar %s" % (fonte, CONTRATO_PARTITURA))
    if not isinstance(partitura.get("itens"), list):
        raise ErroCompilacao("%s não contém itens" % fonte)

    # Verifica a árvore antes de qualquer cópia: um `sfx/` symlink não pode
    # transformar o preparo em escrita fora da produção. Mesmo um plano sem SFX
    # tem uma árvore pública oficial, o conjunto vazio.
    public_dir.mkdir(parents=True, exist_ok=True)
    _inventariar_public(d, public_dir)
    plano_compilado, copiados = _compilar_assets(d, plano, public_dir)
    public_tree = _inventariar_public(d, public_dir)
    saida = copy.deepcopy(partitura)
    mapeados = []
    refs_vistas: set[tuple[Path, str]] = set()
    for evento in plano_compilado["eventos"]:
        artefato, ponteiro = _ref_do_evento(d, evento)
        if artefato != fonte:
            raise ErroCompilacao("evento %s não aponta para a partitura compilada"
                                 % evento.get("id"))
        chave_ref = (artefato, ponteiro)
        if chave_ref in refs_vistas:
            raise ErroCompilacao(
                "evento %s repete uma implementação já usada: %s%s"
                % (evento.get("id"), artefato, ponteiro))
        refs_vistas.add(chave_ref)
        alvo = _resolver_pointer(saida, ponteiro)
        if not isinstance(alvo, dict) or not isinstance(alvo.get("componente"), str):
            raise ErroCompilacao("evento %s não aponta para item visual da partitura"
                                 % evento.get("id"))
        if alvo.get("contrato") not in (None, CONTRATO_RECIBO):
            raise ErroCompilacao(
                "evento %s aponta para item com contrato incompatível %r"
                % (evento.get("id"), alvo.get("contrato")))
        alvo["plano_visual_evento_id"] = evento.get("id")
        mapeados.append({"evento_id": evento.get("id"), "ref": ponteiro,
                         "item_id": alvo.get("id")})

    saida["plano_visual"] = plano_compilado
    saida["_plano_visual_compilacao"] = {
        "contrato": CONTRATO_COMPILACAO,
        "fonte": "plano-visual.json",
        "fonte_sha256": _sha256(d / "plano-visual.json"),
        "conteudo_sha256": _sha256_obj(plano),
        "eventos": mapeados,
    }

    _gravar_atomico(destino, saida)
    manifesto = {
        "contrato": CONTRATO_MANIFESTO,
        "compilado": destino.relative_to(d.resolve()).as_posix(),
        "compilado_sha256": _sha256(destino),
        "public_dir": public_dir.relative_to(d.resolve()).as_posix(),
        "public_tree": public_tree,
        "plano_sha256": _sha256(d / "plano-visual.json"),
        "plano_conteudo_sha256": _sha256_obj(plano),
        "partitura_fonte": fonte.relative_to(d.resolve()).as_posix(),
        "partitura_fonte_sha256": _sha256(fonte),
    }
    manifesto_path = _manifesto_path(d)
    _gravar_atomico(manifesto_path, manifesto)
    return {"acao": "preparar", "veredito": "compilado", "eventos": len(mapeados),
            "partitura_fonte": str(fonte), "saida": str(destino),
            "manifesto": str(manifesto_path),
            "public_dir": str(public_dir),
            "assets_copiados": copiados}


def _carregar_preparo_atual(d: Path, plano: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    manifesto_path = _manifesto_path(d)
    if not manifesto_path.is_file():
        raise ErroCompilacao(
            "%s não existe; execute `preparar` antes do render" % manifesto_path)
    manifesto = _ler_json(manifesto_path)
    if not isinstance(manifesto, dict) or manifesto.get("contrato") != CONTRATO_MANIFESTO:
        raise ErroCompilacao(
            "%s não comprova `preparar`; execute o compilador antes do render"
            % manifesto_path)
    compilado = _rel_da_producao(d, manifesto.get("compilado"),
                                  "manifesto.compilado")
    if not compilado.is_file():
        raise ErroCompilacao("partitura compilada não existe: %s" % compilado)
    if manifesto.get("compilado_sha256") != _sha256(compilado):
        raise ErroCompilacao("partitura compilada mudou depois de `preparar`")
    public_dir = _rel_da_producao(d, manifesto.get("public_dir"),
                                  "manifesto.public_dir")
    public_tree = _inventariar_public(d, public_dir)
    if manifesto.get("public_tree") != public_tree:
        raise ErroCompilacao(
            "assets de public_dir mudaram depois de `preparar`; recompile")
    plano_sha = _sha256(d / "plano-visual.json")
    plano_conteudo_sha = _sha256_obj(plano)
    if manifesto.get("plano_sha256") != plano_sha \
            or manifesto.get("plano_conteudo_sha256") != plano_conteudo_sha:
        raise ErroCompilacao("plano-visual.json mudou depois de `preparar`; recompile")
    fonte = _rel_da_producao(d, manifesto.get("partitura_fonte"),
                             "manifesto.partitura_fonte")
    if not fonte.is_file() \
            or manifesto.get("partitura_fonte_sha256") != _sha256(fonte):
        raise ErroCompilacao("partitura fonte mudou depois de `preparar`; recompile")
    doc = _ler_json(compilado)
    meta = doc.get("_plano_visual_compilacao") if isinstance(doc, dict) else None
    if not isinstance(meta, dict) or meta.get("contrato") != CONTRATO_COMPILACAO \
            or meta.get("fonte_sha256") != plano_sha \
            or meta.get("conteudo_sha256") != plano_conteudo_sha:
        raise ErroCompilacao("partitura compilada não corresponde ao plano atual")
    embutido = doc.get("plano_visual")
    if not isinstance(embutido, dict) or embutido.get("contrato") != CONTRATO_PLANO:
        raise ErroCompilacao("partitura compilada não contém plano visual executável")
    for evento in plano["eventos"]:
        _artefato, ponteiro = _ref_do_evento(d, evento)
        alvo = _resolver_pointer(doc, ponteiro)
        if not isinstance(alvo, dict) \
                or alvo.get("plano_visual_evento_id") != evento.get("id"):
            raise ErroCompilacao(
                "partitura compilada não materializa o evento %s" % evento.get("id"))
    return compilado, manifesto


def _video_valido(caminho: Path, *, permitir_corte_base: bool = False) -> None:
    if not caminho.is_file() or caminho.stat().st_size <= 0:
        raise ErroCompilacao("render não existe ou está vazio: %s" % caminho)
    if not permitir_corte_base \
            and caminho.name in {"v1-montado.mp4", "v1-sdr.mp4", "v1-graded.mp4"}:
        raise ErroCompilacao("o render de prova não pode ser a base do corte: %s" % caminho.name)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ErroCompilacao("ffprobe ausente; não é possível provar que o render contém vídeo")
    proc = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_type", "-of", "json", str(caminho),
    ], text=True, capture_output=True)
    try:
        dados = json.loads(proc.stdout)
    except ValueError:
        dados = {}
    streams = dados.get("streams") if isinstance(dados, dict) else None
    if proc.returncode != 0 or not isinstance(streams, list) or not streams:
        raise ErroCompilacao("render não decodifica como vídeo: %s (%s)"
                             % (caminho, proc.stderr.strip()))


def _registrar_recibos(d: Path, plano: dict[str, Any], render: Path,
                       compilado: Path) -> dict[str, Any]:
    plano_sha = _sha256(d / "plano-visual.json")
    _video_valido(render)
    render_rel = render.relative_to(d.resolve()).as_posix()
    render_sha = _sha256(render)

    documentos: dict[Path, dict[str, Any]] = {}
    alterados: list[dict[str, Any]] = []
    for evento in plano["eventos"]:
        if not isinstance(evento, dict):
            raise ErroCompilacao("evento do plano não é objeto")
        artefato, ponteiro = _ref_do_evento(d, evento)
        if not artefato.is_file():
            raise ErroCompilacao("artefato de implementação não existe: %s" % artefato)
        doc = documentos.setdefault(artefato, _ler_json(artefato))
        alvo = _resolver_pointer(doc, ponteiro)
        if not isinstance(alvo, dict):
            raise ErroCompilacao("evento %s: ref não aponta para objeto JSON"
                                 % evento.get("id"))
        contrato_antigo = alvo.get("contrato")
        if contrato_antigo not in (None, CONTRATO_RECIBO):
            raise ErroCompilacao(
                "evento %s: alvo já tem contrato incompatível %r; use um objeto "
                "de implementação dedicado" % (evento.get("id"), contrato_antigo))
        visual = evento.get("visual")
        if not isinstance(visual, dict) or not isinstance(visual.get("tipo"), str):
            raise ErroCompilacao("evento %s não contém visual.tipo" % evento.get("id"))
        alvo.update({
            "contrato": CONTRATO_RECIBO,
            "evento_id": evento.get("id"),
            "inicio_s": evento.get("inicio_s"),
            "fim_s": evento.get("fim_s"),
            "visual_tipo": visual["tipo"],
            "camada": "grafismo",
            "plano_sha256": plano_sha,
            "render": {"arquivo": render_rel, "sha256": render_sha},
        })
        alterados.append({"evento_id": evento.get("id"),
                          "artefato": artefato.relative_to(d.resolve()).as_posix(),
                          "ref": ponteiro})

    # Só publica depois que TODOS os eventos, refs e contratos foram validados.
    for caminho, doc in documentos.items():
        _gravar_atomico(caminho, doc)
    return {"acao": "renderizar", "veredito": "registrado",
            "render": {"arquivo": render_rel, "sha256": render_sha},
            "plano_sha256": plano_sha,
            "compilado": compilado.relative_to(d.resolve()).as_posix(),
            "eventos": alterados, "artefatos_atualizados": len(documentos)}


def _comando_remotion(compilado: Path, public_dir: Path, parcial: Path) -> list[str]:
    binario = COMPOSITOR / "node_modules" / ".bin" / "remotion"
    if not binario.is_file():
        raise ErroCompilacao(
            "Remotion não instalado; rode `npm ci` em %s" % COMPOSITOR)
    return [
        str(binario), "render", "src/index-partitura.tsx", "Graphics", str(parcial),
        "--props=%s" % compilado,
        "--public-dir=%s" % public_dir,
        "--codec=prores",
        "--prores-profile=4444",
        "--image-format=png",
        "--pixel-format=yuva444p10le",
        "--overwrite",
    ]


def _executar_remotion(comando: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(comando, cwd=COMPOSITOR, text=True, capture_output=True)


def renderizar(d: Path, saida_arg: str, *, executor=_executar_remotion,
               construir_comando=_comando_remotion) -> dict[str, Any]:
    plano = _plano(d)
    compilado, preparo = _carregar_preparo_atual(d, plano)
    public_dir = _rel_da_producao(d, preparo.get("public_dir"),
                                  "manifesto.public_dir")
    public_tree = preparo["public_tree"]
    saida = Path(saida_arg)
    saida = saida.resolve() if saida.is_absolute() else (d / saida).resolve()
    _exigir_dentro_da_producao(d, saida, "--saida")
    if saida.name in {"v1-montado.mp4", "v1-sdr.mp4", "v1-graded.mp4"}:
        raise ErroCompilacao("--saida não pode sobrescrever o corte-base")
    if saida.suffix.lower() != ".mov":
        raise ErroCompilacao("render gráfico oficial usa extensão .mov (ProRes 4444)")
    saida.parent.mkdir(parents=True, exist_ok=True)
    parcial = saida.with_name(".%s.%d.%s.parcial.mov" %
                              (saida.stem, os.getpid(), uuid.uuid4().hex))
    comando = construir_comando(compilado, public_dir, parcial)
    try:
        proc = executor(comando)
        if proc.returncode != 0:
            detalhe = (proc.stderr or proc.stdout or "sem saída").strip()
            raise ErroCompilacao("Remotion falhou (exit %d): %s"
                                 % (proc.returncode, detalhe[-4000:]))
        # Fecha também a janela de mutação durante a execução. Se algum asset
        # mudou, o parcial é descartado e a saída anterior permanece intacta.
        if _inventariar_public(d, public_dir) != public_tree:
            raise ErroCompilacao(
                "assets de public_dir mudaram durante o render; recompile")
        _video_valido(parcial)
        os.replace(parcial, saida)
    finally:
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass

    recibos = _registrar_recibos(d, plano, saida, compilado)
    plano_sha = _sha256(d / "plano-visual.json")
    compilado_rel = compilado.relative_to(d.resolve()).as_posix()
    public_rel = public_dir.relative_to(d.resolve()).as_posix()
    render_rel = saida.relative_to(d.resolve()).as_posix()
    manifesto = {
        "contrato": CONTRATO_RENDER,
        "remotion_executado": True,
        "plano_sha256": plano_sha,
        "compilado": {"arquivo": compilado_rel, "sha256": _sha256(compilado)},
        "public_dir": public_rel,
        "public_tree": public_tree,
        "render": {"arquivo": render_rel, "sha256": _sha256(saida)},
        "comando": {
            "entrypoint": "src/index-partitura.tsx",
            "composition": "Graphics",
            "props": compilado_rel,
            "public_dir": public_rel,
        },
        "exit": 0,
    }
    manifesto_path = _manifesto_render_path(d)
    _gravar_atomico(manifesto_path, manifesto)
    return {
        **recibos,
        "veredito": "renderizado",
        "manifesto_render": str(manifesto_path),
        "comando": manifesto["comando"],
    }


def _carregar_render_atual(d: Path, plano: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    caminho = _manifesto_render_path(d)
    if not caminho.is_file():
        raise ErroCompilacao("%s não existe; execute `renderizar`" % caminho)
    doc = _ler_json(caminho)
    if not isinstance(doc, dict) or doc.get("contrato") != CONTRATO_RENDER \
            or doc.get("remotion_executado") is not True or doc.get("exit") != 0:
        raise ErroCompilacao("manifesto não comprova execução Remotion bem-sucedida")
    plano_sha = _sha256(d / "plano-visual.json")
    if doc.get("plano_sha256") != plano_sha:
        raise ErroCompilacao("render Remotion pertence a outro plano; renderize novamente")
    preparo = _ler_json(_manifesto_path(d))
    if not isinstance(preparo, dict) or preparo.get("contrato") != CONTRATO_MANIFESTO:
        raise ErroCompilacao("manifesto de preparo Remotion é inválido")
    comp = doc.get("compilado")
    if not isinstance(comp, dict) or comp.get("arquivo") != preparo.get("compilado") \
            or comp.get("sha256") != preparo.get("compilado_sha256"):
        raise ErroCompilacao("render Remotion não corresponde à partitura preparada")
    compilado = _rel_da_producao(d, comp.get("arquivo"), "render.compilado.arquivo")
    if not compilado.is_file() or _sha256(compilado) != comp.get("sha256"):
        raise ErroCompilacao("partitura do render mudou; prepare e renderize novamente")
    render = doc.get("render")
    if not isinstance(render, dict):
        raise ErroCompilacao("manifesto Remotion não contém render")
    arquivo = _rel_da_producao(d, render.get("arquivo"), "render.arquivo")
    if not arquivo.is_file() or _sha256(arquivo) != render.get("sha256"):
        raise ErroCompilacao("graphics renderizado mudou depois do Remotion")
    comando = doc.get("comando")
    esperado_public = preparo.get("public_dir")
    public_dir = _rel_da_producao(d, esperado_public, "manifesto.public_dir")
    public_tree = _inventariar_public(d, public_dir)
    if preparo.get("public_tree") != public_tree \
            or doc.get("public_tree") != public_tree:
        raise ErroCompilacao(
            "assets de public_dir não correspondem ao preparo/render Remotion")
    if not isinstance(comando, dict) \
            or comando.get("entrypoint") != "src/index-partitura.tsx" \
            or comando.get("composition") != "Graphics" \
            or comando.get("props") != preparo.get("compilado") \
            or comando.get("public_dir") != esperado_public \
            or doc.get("public_dir") != esperado_public:
        raise ErroCompilacao("manifesto Remotion não registra props/public-dir oficiais")
    _video_valido(arquivo)
    return arquivo, doc


def _tem_audio(caminho: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ErroCompilacao("ffprobe ausente; não é possível conferir o mix final")
    proc = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "json", str(caminho),
    ], text=True, capture_output=True)
    try:
        obj = json.loads(proc.stdout)
    except ValueError:
        obj = {}
    streams = obj.get("streams") if isinstance(obj, dict) else None
    return proc.returncode == 0 and isinstance(streams, list) and bool(streams)


def _comando_ffmpeg_final(base: Path, grafico: Path, parcial: Path,
                           misturar_sfx: bool) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ErroCompilacao("ffmpeg ausente; não é possível compor a entrega")
    video = (
        "[1:v]unpremultiply=inplace=1[g];"
        "[0:v][g]overlay=0:0:format=auto:eof_action=pass[v];"
        "[v]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[vo]"
    )
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(base), "-i", str(grafico)]
    if misturar_sfx:
        filtro = video + ";[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]"
        cmd.extend(["-filter_complex", filtro, "-map", "[vo]", "-map", "[a]"])
    else:
        cmd.extend(["-filter_complex", video, "-map", "[vo]", "-map", "0:a?"])
    cmd.extend([
        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(parcial),
    ])
    return cmd


def _executar_ffmpeg(comando: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(comando, text=True, capture_output=True)


def compor_final(d: Path, base_arg: str, saida_arg: str, *,
                 executor=_executar_ffmpeg,
                 construir_comando=_comando_ffmpeg_final) -> dict[str, Any]:
    _diretorio_manifestos_finais(d, criar=False)
    saida = _resolver_saida_final(d, saida_arg)
    _recusar_colisao_casefold(saida)
    final_rel = saida.name
    plano = _plano(d)
    grafico, _manifesto_render = _carregar_render_atual(d, plano)
    base = Path(base_arg)
    base = base.resolve() if base.is_absolute() else (d / base).resolve()
    _exigir_dentro_da_producao(d, base, "--base")
    _video_valido(base, permitir_corte_base=True)
    if not _tem_audio(base):
        raise ErroCompilacao("base final não contém áudio")
    if saida in {base, grafico}:
        raise ErroCompilacao("--saida não pode sobrescrever um dos inputs")
    tem_sfx = any(
        isinstance(evento, dict)
        and isinstance(evento.get("som"), dict)
        and evento["som"].get("decisao") == "usar"
        for evento in plano["eventos"]
    )
    if tem_sfx and not _tem_audio(grafico):
        raise ErroCompilacao("o plano usa SFX, mas o render gráfico não contém áudio")
    _diretorio_manifestos_finais(d, criar=True)
    manifesto_path = _manifesto_final_path(d, final_rel)
    _validar_manifesto_final_alvo(manifesto_path, final_rel)
    parcial = saida.with_name(".%s.%d.%s.parcial.mp4" %
                              (saida.stem, os.getpid(), uuid.uuid4().hex))
    comando = construir_comando(base, grafico, parcial, tem_sfx)
    try:
        proc = executor(comando)
        if proc.returncode != 0:
            detalhe = (proc.stderr or proc.stdout or "sem saída").strip()
            raise ErroCompilacao("composição ffmpeg falhou (exit %d): %s"
                                 % (proc.returncode, detalhe[-4000:]))
        _video_valido(parcial)
        if not _tem_audio(parcial):
            raise ErroCompilacao("composição final perdeu o áudio")
        _diretorio_manifestos_finais(d, criar=False)
        _validar_manifesto_final_alvo(manifesto_path, final_rel)
        os.replace(parcial, saida)
    finally:
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass
    base_rel = base.relative_to(d.resolve()).as_posix()
    grafico_rel = grafico.relative_to(d.resolve()).as_posix()
    manifesto = {
        "contrato": CONTRATO_FINAL,
        "plano_sha256": _sha256(d / "plano-visual.json"),
        "base": {"arquivo": base_rel, "sha256": _sha256(base)},
        "grafico": {"arquivo": grafico_rel, "sha256": _sha256(grafico)},
        "final": {"arquivo": final_rel, "sha256": _sha256(saida)},
        "video_grafico_sobreposto": True,
        "audio_grafico_misturado": tem_sfx,
        "sfx_esperado": tem_sfx,
        "render_manifesto_sha256": _sha256(_manifesto_render_path(d)),
        "comando": {
            "motor": "ffmpeg",
            "unpremultiply": True,
            "overlay": True,
            "audio": "amix:normalize=0:duration=first" if tem_sfx else "audio-base",
        },
        "exit": 0,
    }
    _diretorio_manifestos_finais(d, criar=False)
    _validar_manifesto_final_alvo(manifesto_path, final_rel)
    _gravar_atomico(manifesto_path, manifesto)
    return {"acao": "compor-final", "veredito": "composto",
            "final": manifesto["final"], "manifesto_final": str(manifesto_path),
            "audio_grafico_misturado": tem_sfx}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="compila plano visual para Remotion e registra recibo pós-render")
    ap.add_argument("dir", help="diretório da produção")
    subs = ap.add_subparsers(dest="comando", required=True)
    p = subs.add_parser("preparar", help="embute o plano na partitura de render")
    p.add_argument("--destino", help="partitura consumida pelo entry point")
    p.add_argument("--public-dir", help="public/ do projeto Remotion")
    p.add_argument("--json", action="store_true", help="saída JSON")
    e = subs.add_parser("renderizar", help="executa Remotion e grava recibos verificáveis")
    e.add_argument("--saida", required=True, help="MOV gráfico final, dentro da produção")
    e.add_argument("--json", action="store_true", help="saída JSON")
    f = subs.add_parser("compor-final", help="sobrepõe graphics e mistura SFX no final")
    f.add_argument("--base", required=True, help="vídeo-base com voz, dentro da produção")
    f.add_argument("--saida", required=True, help="MP4 final, dentro da produção")
    f.add_argument("--json", action="store_true", help="saída JSON")
    args = ap.parse_args(argv)

    d = Path(args.dir).resolve()
    try:
        if not d.is_dir():
            raise ErroCompilacao("produção não existe: %s" % d)
        if args.comando == "preparar":
            resultado = preparar(
                d,
                _caminho_cli(d, args.destino, _destino_padrao(d)),
                _caminho_cli(d, args.public_dir, _public_padrao(d)),
            )
        elif args.comando == "renderizar":
            resultado = renderizar(d, args.saida)
        else:
            resultado = compor_final(d, args.base, args.saida)
    except ErroCompilacao as exc:
        resultado = {"acao": args.comando, "veredito": "reprovado", "erro": str(exc)}
        if args.json:
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
        else:
            print("REPROVADO · %s\n%s" % (args.comando, exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        print("%s · %s" % (resultado["veredito"].upper(), args.comando))
        if args.comando == "preparar":
            print("eventos: %d · saída: %s" %
                  (resultado["eventos"], resultado["saida"]))
        elif args.comando == "renderizar":
            print("eventos: %d · render: %s" %
                  (len(resultado["eventos"]), resultado["render"]["arquivo"]))
        else:
            print("final: %s · SFX misturado: %s" %
                  (resultado["final"]["arquivo"],
                   "sim" if resultado["audio_grafico_misturado"] else "não"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
