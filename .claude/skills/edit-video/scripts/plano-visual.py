#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contrato executável do plano visual da Fase 2.

Uso:
    plano-visual.py <dir-producao> --iniciar [--json]
    plano-visual.py <dir-producao> --validar planejamento [--json]
    plano-visual.py <dir-producao> --validar entrega [--json]

O arquivo canônico é ``<dir-producao>/plano-visual.json``. ``--iniciar`` nunca
sobrepõe um plano existente e publica o esqueleto de forma atômica. Os dois gates
são somente leitura.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


CONTRATO = "benchmark.plano-visual/v1"
CONTRATO_QC = "benchmark.qc-plano-visual/v1"
CONTRATO_ESTILO = "benchmark.edit-estilo/v3"
CONTRATO_ESTILO_VIGENTE = "benchmark.edit-estilo-vigente/v1"
CONTRATO_TIMELINE = "benchmark.timeline-real/v1"
CONTRATO_PROVA_VISUAL = "benchmark.evento-visual-aplicado/v1"
CONTRATO_PREPARO_REMOTION = "benchmark.remotion-plano-visual-preparado/v1"
CONTRATO_COMPILACAO_REMOTION = "benchmark.partitura-plano-visual/v1"
CONTRATO_RENDER_REMOTION = "benchmark.remotion-plano-visual-render/v1"
CONTRATO_FINAL_REMOTION = "benchmark.remotion-plano-visual-final/v1"
CONTRATO_PUBLIC_TREE = "benchmark.remotion-public-tree/v1"
ARQUIVO = "plano-visual.json"

MODOS = {"essencial", "animada", "surpresa"}
DENSIDADES = {"leve", "equilibrada", "alta"}
POLITICAS_SFX = {"automatico", "sem-sfx"}
DECISOES_SOM = {"usar", "silencio-intencional", "nao-se-aplica"}

# ``scripts/plano-visual.py`` -> raiz da ilha.
RAIZ_ILHA = Path(__file__).resolve().parents[3]
SFX_CANONICOS = RAIZ_ILHA / "tools" / "remotion-compositor" / "public" / "sfx"


class Falhas:
    """Acumula erros estáveis para humano e automação."""

    def __init__(self) -> None:
        self.itens: list[dict[str, Any]] = []

    def add(self, codigo: str, mensagem: str, evento: str | None = None) -> None:
        item: dict[str, Any] = {"codigo": codigo, "mensagem": mensagem}
        if evento:
            item["evento"] = evento
        self.itens.append(item)

    def __bool__(self) -> bool:
        return bool(self.itens)


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _numero(valor: Any) -> bool:
    return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(float(valor)))


def _texto(valor: Any) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return "sha256:" + h.hexdigest()


def _sha256_obj(obj: Any) -> str:
    canon = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _fingerprint_edl(segmentos: list[Any]) -> str:
    canon = json.dumps(segmentos, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canon.encode("utf-8")).hexdigest()


def _fingerprint_render(caminho: Path) -> str:
    st = caminho.stat()
    texto = "%s|%d|%d" % (caminho.name, st.st_size, int(st.st_mtime))
    return "sha1:" + hashlib.sha1(texto.encode("utf-8")).hexdigest()


def _ler_json(caminho: Path) -> Any:
    with caminho.open(encoding="utf-8") as fh:
        return json.load(fh)


def _direcao_valida(direcao: Any, falhas: Falhas, prefixo: str) -> bool:
    if not isinstance(direcao, dict):
        falhas.add("DIRECAO-AUSENTE", "%s não contém `direcao_edicao` v3" % prefixo)
        return False
    ok = True
    campos = {"modo", "densidade", "sfx"}
    faltam = campos - set(direcao)
    sobram = set(direcao) - campos
    if faltam:
        falhas.add("DIRECAO-CAMPOS-AUSENTES",
                   "%s.direcao_edicao não contém: %s"
                   % (prefixo, ", ".join(sorted(faltam))))
        ok = False
    if sobram:
        falhas.add("DIRECAO-CAMPOS-DESCONHECIDOS",
                   "%s.direcao_edicao contém campos desconhecidos: %s"
                   % (prefixo, ", ".join(sorted(sobram))))
        ok = False
    if direcao.get("modo") not in MODOS:
        falhas.add("DIRECAO-MODO-INVALIDO",
                   "%s.direcao_edicao.modo deve ser %s"
                   % (prefixo, ", ".join(sorted(MODOS))))
        ok = False
    if direcao.get("densidade") not in DENSIDADES:
        falhas.add("DIRECAO-DENSIDADE-INVALIDA",
                   "%s.direcao_edicao.densidade deve ser %s"
                   % (prefixo, ", ".join(sorted(DENSIDADES))))
        ok = False
    if direcao.get("sfx") not in POLITICAS_SFX:
        falhas.add("DIRECAO-SFX-INVALIDO",
                   "%s.direcao_edicao.sfx deve ser %s"
                   % (prefixo, ", ".join(sorted(POLITICAS_SFX))))
        ok = False
    if direcao.get("modo") == "essencial" and direcao.get("densidade") != "leve":
        falhas.add("ESSENCIAL-DENSIDADE-INVALIDA",
                   "%s: modo essencial exige densidade `leve`" % prefixo)
        ok = False
    if direcao.get("modo") == "essencial" and direcao.get("sfx") != "sem-sfx":
        falhas.add("ESSENCIAL-COM-SFX",
                   "%s: modo essencial exige sfx `sem-sfx`" % prefixo)
        ok = False
    return ok


def _carregar_estilo(d: Path, falhas: Falhas) -> dict[str, Any] | None:
    caminho = d / ".preview" / "estilo-vigente.json"
    if not caminho.is_file():
        falhas.add("FONTE-ESTILO-AUSENTE", "%s não existe" % caminho)
        return None
    try:
        obj = _ler_json(caminho)
    except (OSError, ValueError) as exc:
        falhas.add("FONTE-ESTILO-INVALIDA", "%s: %s" % (caminho, exc))
        return None
    if not isinstance(obj, dict) or obj.get("contrato") != CONTRATO_ESTILO_VIGENTE:
        falhas.add("FONTE-ESTILO-INVALIDA",
                   "%s deve usar `%s`" % (caminho, CONTRATO_ESTILO_VIGENTE))
        return None
    estilo = obj.get("estilo")
    if not isinstance(estilo, dict) or estilo.get("contrato") != CONTRATO_ESTILO:
        falhas.add("ESTILO-V3-OBRIGATORIO",
                   "o estilo aplicado deve usar `%s`; v1/v2 não autorizam inferência"
                   % CONTRATO_ESTILO)
        return None
    direcao = estilo.get("direcao_edicao")
    if not _direcao_valida(direcao, falhas, "estilo-vigente.json.estilo"):
        return None

    # A decisão resumida e o interruptor detalhado não podem discordar.
    elementos = estilo.get("elementos")
    if isinstance(elementos, dict) and isinstance(elementos.get("sfx"), bool):
        esperado = "automatico" if elementos["sfx"] else "sem-sfx"
        if direcao.get("sfx") != esperado:
            falhas.add("DIRECAO-SFX-DIVERGENTE",
                       "direcao_edicao.sfx=%s diverge de elementos.sfx=%s"
                       % (direcao.get("sfx"), elementos["sfx"]))
            return None
    return {"caminho": caminho, "obj": obj, "direcao": dict(direcao),
            "sha256": _sha256_arquivo(caminho)}


def _carregar_timeline(d: Path, falhas: Falhas) -> dict[str, Any] | None:
    edl = d / "edl.json"
    if not edl.is_file():
        falhas.add("TIMELINE-AUSENTE", "%s não existe" % edl)
        return None
    try:
        bruto = _ler_json(edl)
    except (OSError, ValueError) as exc:
        falhas.add("TIMELINE-INVALIDA", "%s: %s" % (edl, exc))
        return None

    if isinstance(bruto, list):
        segmentos = bruto
        origem = d / "timeline-real.json"
        if not origem.is_file():
            falhas.add("TIMELINE-AUSENTE", "%s não existe" % origem)
            return None
        try:
            timeline = _ler_json(origem)
        except (OSError, ValueError) as exc:
            falhas.add("TIMELINE-INVALIDA", "%s: %s" % (origem, exc))
            return None
    elif isinstance(bruto, dict):
        segmentos = bruto.get("segments")
        timeline = bruto.get("timeline_real")
        origem = edl
    else:
        falhas.add("TIMELINE-INVALIDA", "edl.json deve ser array v1 ou objeto v2")
        return None

    if not isinstance(segmentos, list) or not segmentos:
        falhas.add("TIMELINE-INVALIDA", "edl.json não contém segmentos")
        return None
    if not isinstance(timeline, dict):
        falhas.add("TIMELINE-AUSENTE", "timeline_real não foi persistida")
        return None
    if timeline.get("schema") != CONTRATO_TIMELINE:
        falhas.add("TIMELINE-INVALIDA",
                   "timeline_real deve usar `%s`" % CONTRATO_TIMELINE)
        return None

    fp_atual = _fingerprint_edl(segmentos)
    if timeline.get("edl_fingerprint") != fp_atual:
        falhas.add("TIMELINE-VELHA",
                   "timeline_real descreve %s, mas o corte atual é %s"
                   % (timeline.get("edl_fingerprint"), fp_atual))
        return None
    total_s = timeline.get("total_s")
    if not _numero(total_s) or float(total_s) <= 0:
        falhas.add("TIMELINE-INVALIDA", "timeline_real.total_s deve ser positivo")
        return None

    try:
        origem_rel = origem.resolve().relative_to(d.resolve()).as_posix()
    except ValueError:
        falhas.add("TIMELINE-INVALIDA", "a timeline_real precisa estar na produção")
        return None
    return {"obj": timeline, "arquivo": origem_rel, "sha256": _sha256_obj(timeline),
            "edl_fingerprint": fp_atual, "total_s": float(total_s)}


def _render_atual(d: Path, falhas: Falhas) -> dict[str, Any] | None:
    nome: str | None = None
    estado = d / ".preview" / "estado.json"
    agente = d / ".preview" / "estado-agente.json"
    for caminho, chave in ((estado, "render_corrente"), (agente, "render")):
        if not caminho.is_file():
            continue
        try:
            obj = _ler_json(caminho)
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and _texto(obj.get(chave)):
            nome = obj[chave]
            break
    if nome is None:
        nome = "v1-montado.mp4"
    if Path(nome).is_absolute() or ".." in Path(nome).parts:
        falhas.add("RENDER-CORTE-INVALIDO", "render do corte aponta para fora da produção")
        return None
    caminho = (d / nome).resolve()
    try:
        caminho.relative_to(d.resolve())
    except ValueError:
        falhas.add("RENDER-CORTE-INVALIDO", "render do corte aponta para fora da produção")
        return None
    if not caminho.is_file():
        falhas.add("RENDER-CORTE-AUSENTE", "%s não existe" % caminho)
        return None
    return {"caminho": caminho, "arquivo": caminho.relative_to(d.resolve()).as_posix(),
            "fingerprint": _fingerprint_render(caminho)}


def _contexto_atual(d: Path, falhas: Falhas) -> dict[str, Any]:
    estilo = _carregar_estilo(d, falhas)
    plano_md = d / "PLANO-EDICAO.md"
    if not plano_md.is_file():
        falhas.add("FONTE-PLANO-AUSENTE", "%s não existe" % plano_md)
        plano = None
    else:
        plano = {"caminho": plano_md, "sha256": _sha256_arquivo(plano_md)}
    timeline = _carregar_timeline(d, falhas)
    render = _render_atual(d, falhas)
    return {"estilo": estilo, "plano": plano, "timeline": timeline, "render": render}


def _vinculos(ctx: dict[str, Any]) -> dict[str, Any]:
    estilo = ctx["estilo"]
    plano = ctx["plano"]
    timeline = ctx["timeline"]
    render = ctx["render"]
    return {
        "estilo_vigente": {
            "arquivo": ".preview/estilo-vigente.json",
            "sha256": estilo["sha256"],
        },
        "plano_edicao": {
            "arquivo": "PLANO-EDICAO.md",
            "sha256": plano["sha256"],
        },
        "render_corte": {
            "arquivo": render["arquivo"],
            "fingerprint": render["fingerprint"],
        },
        "timeline_real": {
            "arquivo": timeline["arquivo"],
            "sha256": timeline["sha256"],
            "edl_fingerprint": timeline["edl_fingerprint"],
            "total_s": timeline["total_s"],
        },
    }


def _escrever_novo_atomico(destino: Path, obj: dict[str, Any]) -> None:
    """Publica conteúdo completo sem jamais substituir o destino.

    O hardlink é a operação atômica e exclusiva: se outro processo publicar entre
    a checagem e o link, ``EEXIST`` vence e nenhum dos dois sobrescreve o outro.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        raise FileExistsError(errno.EEXIST, "o plano já existe", str(destino))
    parcial = destino.with_name(".%s.%d.%s.parcial"
                                % (destino.name, os.getpid(), uuid.uuid4().hex))
    dados = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd = None
    try:
        fd = os.open(parcial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(dados)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(parcial, destino)
        try:
            dirfd = os.open(destino.parent, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError:
            # Alguns filesystems não oferecem fsync de diretório. O link já é
            # atômico; esta tentativa existe apenas para durabilidade pós-crash.
            pass
    finally:
        if fd is not None:
            os.close(fd)
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass


def iniciar(d: Path) -> tuple[int, dict[str, Any]]:
    falhas = Falhas()
    ctx = _contexto_atual(d, falhas)
    if falhas:
        return 1, {"contrato": CONTRATO_QC, "acao": "iniciar",
                   "veredito": "reprovado", "erros": falhas.itens}
    direcao = ctx["estilo"]["direcao"]
    doc: dict[str, Any] = {
        "contrato": CONTRATO,
        "criado_em": _agora(),
        "vinculos": _vinculos(ctx),
        "direcao_edicao": direcao,
        "eventos": [],
    }
    if direcao["modo"] == "surpresa":
        doc["direcao_resolvida"] = None
    destino = d / ARQUIVO
    try:
        _escrever_novo_atomico(destino, doc)
    except FileExistsError:
        falhas.add("PLANO-JA-EXISTE",
                   "%s já existe; --iniciar nunca sobrescreve" % destino)
        return 1, {"contrato": CONTRATO_QC, "acao": "iniciar",
                   "veredito": "reprovado", "erros": falhas.itens}
    return 0, {
        "contrato": CONTRATO_QC,
        "acao": "iniciar",
        "veredito": "criado",
        "arquivo": str(destino.resolve()),
        "modo": direcao["modo"],
        "pendente": direcao["modo"] != "essencial",
        "mensagem": ("preencha eventos e valide `planejamento`"
                     if direcao["modo"] != "essencial"
                     else "o plano essencial já pode ser validado"),
    }


def _comparar_vinculo(doc: dict[str, Any], nome: str, atual: dict[str, Any],
                      codigo: str, falhas: Falhas) -> None:
    vinculos = doc.get("vinculos")
    gravado = vinculos.get(nome) if isinstance(vinculos, dict) else None
    if not isinstance(gravado, dict):
        falhas.add("VINCULO-AUSENTE", "vinculos.%s está ausente" % nome)
        return
    divergentes = [k for k, v in atual.items() if gravado.get(k) != v]
    if divergentes:
        falhas.add(codigo, "vinculos.%s divergiu em: %s"
                   % (nome, ", ".join(divergentes)))


def _validar_vinculos(doc: dict[str, Any], ctx: dict[str, Any], falhas: Falhas) -> None:
    if ctx.get("estilo"):
        _comparar_vinculo(doc, "estilo_vigente", {
            "arquivo": ".preview/estilo-vigente.json",
            "sha256": ctx["estilo"]["sha256"],
        }, "STALE-ESTILO", falhas)
    if ctx.get("plano"):
        _comparar_vinculo(doc, "plano_edicao", {
            "arquivo": "PLANO-EDICAO.md",
            "sha256": ctx["plano"]["sha256"],
        }, "STALE-PLANO-EDICAO", falhas)
    if ctx.get("render"):
        _comparar_vinculo(doc, "render_corte", {
            "arquivo": ctx["render"]["arquivo"],
            "fingerprint": ctx["render"]["fingerprint"],
        }, "STALE-RENDER-CORTE", falhas)
    if ctx.get("timeline"):
        _comparar_vinculo(doc, "timeline_real", {
            "arquivo": ctx["timeline"]["arquivo"],
            "sha256": ctx["timeline"]["sha256"],
            "edl_fingerprint": ctx["timeline"]["edl_fingerprint"],
            "total_s": ctx["timeline"]["total_s"],
        }, "STALE-TIMELINE-REAL", falhas)


def _validar_direcao_resolvida(doc: dict[str, Any], falhas: Falhas) -> None:
    resolvida = doc.get("direcao_resolvida")
    if not isinstance(resolvida, dict):
        falhas.add("SURPRESA-NAO-RESOLVIDA",
                   "modo surpresa exige `direcao_resolvida` persistida")
        return
    for campo in ("resumo", "resolvido_por", "resolvido_em"):
        if not _texto(resolvida.get(campo)):
            falhas.add("SURPRESA-NAO-RESOLVIDA",
                       "direcao_resolvida.%s deve ser texto não vazio" % campo)


def _validar_eventos(doc: dict[str, Any], direcao: dict[str, Any] | None,
                     total_s: float | None, falhas: Falhas) -> list[dict[str, Any]]:
    eventos = doc.get("eventos")
    if not isinstance(eventos, list):
        falhas.add("EVENTOS-INVALIDOS", "`eventos` deve ser uma lista")
        return []
    modo = direcao.get("modo") if isinstance(direcao, dict) else None
    if modo == "essencial":
        if eventos:
            falhas.add("ESSENCIAL-COM-EVENTOS",
                       "modo essencial exige zero eventos visuais")
        if direcao.get("sfx") != "sem-sfx":
            falhas.add("ESSENCIAL-COM-SFX",
                       "modo essencial exige direcao_edicao.sfx=`sem-sfx`")
    elif modo in {"animada", "surpresa"} and not eventos:
        falhas.add("EVENTOS-AUSENTES", "modo %s exige ao menos um evento" % modo)

    ids: set[str] = set()
    validos: list[dict[str, Any]] = []
    for indice, evento in enumerate(eventos):
        rotulo = (evento.get("id") if isinstance(evento, dict) else None) or "#%d" % indice
        if not isinstance(evento, dict):
            falhas.add("EVENTO-INVALIDO", "evento deve ser objeto", rotulo)
            continue
        eid = evento.get("id")
        if not _texto(eid):
            falhas.add("EVENTO-ID-AUSENTE", "evento.id deve ser texto não vazio", rotulo)
        elif eid in ids:
            falhas.add("EVENTO-ID-DUPLICADO", "evento.id precisa ser único", eid)
        else:
            ids.add(eid)

        ini, fim = evento.get("inicio_s"), evento.get("fim_s")
        tempo_ok = True
        if not _numero(ini) or not _numero(fim):
            falhas.add("TEMPO-INVALIDO", "inicio_s e fim_s devem ser números finitos", rotulo)
            tempo_ok = False
        elif float(ini) < 0 or float(fim) <= float(ini):
            falhas.add("TEMPO-INVALIDO", "exige 0 <= inicio_s < fim_s", rotulo)
            tempo_ok = False
        elif total_s is not None and float(fim) > total_s + 1e-6:
            falhas.add("TEMPO-FORA-TIMELINE",
                       "fim_s %.6f excede timeline_real.total_s %.6f"
                       % (float(fim), total_s), rotulo)
            tempo_ok = False

        if not _texto(evento.get("beat")):
            falhas.add("BEAT-AUSENTE", "evento.beat deve ser texto não vazio", rotulo)
        visual = evento.get("visual")
        if not isinstance(visual, dict) or not _texto(visual.get("tipo")) \
                or not _texto(visual.get("descricao")):
            falhas.add("VISUAL-AUSENTE",
                       "evento.visual exige `tipo` e `descricao`", rotulo)
        if not _texto(evento.get("zona")):
            falhas.add("ZONA-AUSENTE", "evento.zona deve ser texto não vazio", rotulo)

        som = evento.get("som")
        if not isinstance(som, dict) or som.get("decisao") not in DECISOES_SOM:
            falhas.add("SOM-DECISAO-AUSENTE",
                       "evento.som.decisao deve ser %s"
                       % ", ".join(sorted(DECISOES_SOM)), rotulo)
        else:
            decisao = som["decisao"]
            if decisao == "usar":
                if isinstance(direcao, dict) and direcao.get("sfx") == "sem-sfx":
                    falhas.add("SFX-NAO-AUTORIZADO",
                               "a direção `sem-sfx` não permite decisão `usar`", rotulo)
                if not _texto(som.get("asset")):
                    falhas.add("SFX-ASSET-AUSENTE", "som.asset é obrigatório", rotulo)
                if not _numero(som.get("at_s")):
                    falhas.add("SFX-TEMPO-AUSENTE", "som.at_s é obrigatório", rotulo)
                elif tempo_ok and not (float(ini) - 1e-6 <= float(som["at_s"])
                                       <= float(fim) + 1e-6):
                    falhas.add("SFX-FORA-DO-EVENTO",
                               "som.at_s deve cair entre inicio_s e fim_s", rotulo)
                if not _numero(som.get("ganho_db")):
                    falhas.add("SFX-GANHO-AUSENTE", "som.ganho_db é obrigatório", rotulo)
            else:
                if any(k in som for k in ("asset", "at_s", "ganho_db")):
                    falhas.add("SFX-DADOS-AMBIGUOS",
                               "decisão `%s` não pode carregar asset/at_s/ganho_db"
                               % decisao, rotulo)
                if decisao == "silencio-intencional" and not _texto(som.get("motivo")):
                    falhas.add("SILENCIO-SEM-JUSTIFICATIVA",
                               "silencio-intencional exige `motivo`", rotulo)
        validos.append(evento)
    return validos


_PALAVRAS_CAPTION = {"caption", "captions", "caps", "legenda", "legendas",
                     "subtitle", "subtitles", "srt", "vtt"}


def _e_artefato_de_caption(rel: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", rel.lower()))
    return bool(tokens & _PALAVRAS_CAPTION) or Path(rel).suffix.lower() in {".srt", ".vtt"}


def _caminho_da_producao(d: Path, rel: Any) -> Path | None:
    if not _texto(rel) or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    caminho = (d / rel).resolve()
    try:
        caminho.relative_to(d.resolve())
    except ValueError:
        return None
    return caminho


def _inventariar_public(d: Path, rel: Any, falhas: Falhas) -> dict[str, Any] | None:
    """Recalcula no gate os bytes que o Remotion recebeu em ``--public-dir``."""
    if not _texto(rel) or Path(rel).is_absolute() or ".." in Path(rel).parts:
        falhas.add("PUBLIC-TREE-INVALIDA",
                   "public_dir deve ser caminho relativo dentro da produção")
        return None
    bruto = d / rel
    if bruto.is_symlink():
        falhas.add("PUBLIC-TREE-INVALIDA",
                   "public_dir não aceita symlink: %s" % bruto)
        return None
    public_dir = bruto.resolve()
    try:
        public_dir.relative_to(d.resolve())
    except ValueError:
        falhas.add("PUBLIC-TREE-INVALIDA", "public_dir escapou da produção")
        return None
    if not public_dir.is_dir():
        falhas.add("PUBLIC-TREE-AUSENTE",
                   "public_dir não existe ou não é diretório: %s" % rel)
        return None
    arquivos: list[dict[str, Any]] = []
    try:
        for atual, diretorios, nomes in os.walk(public_dir, followlinks=False):
            raiz_atual = Path(atual)
            for nome in diretorios:
                caminho = raiz_atual / nome
                if caminho.is_symlink() or not caminho.is_dir():
                    falhas.add("PUBLIC-TREE-INVALIDA",
                               "entrada não regular em public_dir: %s" % caminho)
                    return None
            for nome in nomes:
                caminho = raiz_atual / nome
                if caminho.is_symlink() or not caminho.is_file():
                    falhas.add("PUBLIC-TREE-INVALIDA",
                               "entrada não regular em public_dir: %s" % caminho)
                    return None
                antes = caminho.stat()
                digest = _sha256_arquivo(caminho)
                depois = caminho.stat()
                identidade_antes = (antes.st_dev, antes.st_ino, antes.st_size,
                                     antes.st_mtime_ns)
                identidade_depois = (depois.st_dev, depois.st_ino, depois.st_size,
                                      depois.st_mtime_ns)
                if identidade_antes != identidade_depois:
                    falhas.add("PUBLIC-TREE-INVALIDA",
                               "asset mudou durante o inventário: %s" % caminho)
                    return None
                arquivos.append({
                    "caminho": caminho.relative_to(public_dir).as_posix(),
                    "bytes": depois.st_size,
                    "sha256": digest,
                })
    except OSError as exc:
        falhas.add("PUBLIC-TREE-INVALIDA",
                   "não foi possível inventariar public_dir: %s" % exc)
        return None
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


def _json_pointer(obj: Any, ponteiro: str) -> tuple[bool, Any]:
    if not ponteiro.startswith("/"):
        return False, None
    atual = obj
    for parte in ponteiro[1:].split("/"):
        chave = parte.replace("~1", "/").replace("~0", "~")
        if isinstance(atual, dict) and chave in atual:
            atual = atual[chave]
        elif isinstance(atual, list) and chave.isdigit() and int(chave) < len(atual):
            atual = atual[int(chave)]
        else:
            return False, None
    return atual is not None, atual


def _verificar_ref(caminho: Path, ref: Any) -> tuple[bool, Any, str]:
    if not isinstance(ref, dict) or ref.get("tipo") not in {"json-pointer", "marcador-texto"} \
            or not _texto(ref.get("valor")):
        return False, None, "ref exige {tipo: json-pointer|marcador-texto, valor: ...}"
    tipo, valor = ref["tipo"], ref["valor"]
    if tipo == "json-pointer":
        try:
            obj = _ler_json(caminho)
        except (OSError, ValueError) as exc:
            return False, None, "artefato não é JSON legível: %s" % exc
        ok, alvo = _json_pointer(obj, valor)
        return ok, alvo, ("" if ok else "JSON Pointer não existe ou aponta para null")
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return False, None, "artefato não é texto UTF-8 legível: %s" % exc
    ok = valor in texto
    return ok, None, ("" if ok else "marcador de texto não foi encontrado")


def _mesmo_tempo(a: Any, b: Any) -> bool:
    return _numero(a) and _numero(b) and abs(float(a) - float(b)) <= 1e-6


def _validar_prova_visual(d: Path, evento: dict[str, Any], prova: Any,
                          render_corte: str | None, plano_sha256: str | None,
                          render_oficial: dict[str, Any] | None,
                          hashes: dict[Path, str],
                          falhas: Falhas, eid: str) -> None:
    """Confere um recibo do compositor, não apenas a existência de um arquivo.

    O alvo do JSON Pointer precisa declarar qual evento aplicou, em que janela e
    em qual render. Assim, renomear ``captions.json`` para ``graphics.json`` não
    produz prova: o conteúdo continua sem o contrato e sem vínculo ao render.
    """
    if not isinstance(prova, dict) or prova.get("contrato") != CONTRATO_PROVA_VISUAL:
        falhas.add(
            "PROVA-VISUAL-INVALIDA",
            "a referência deve apontar para um recibo `%s`, não apenas para captions/overlay"
            % CONTRATO_PROVA_VISUAL,
            eid,
        )
        return
    if prova.get("evento_id") != evento.get("id"):
        falhas.add("PROVA-EVENTO-DIVERGENTE",
                   "recibo.evento_id não corresponde ao evento planejado", eid)
    if not _mesmo_tempo(prova.get("inicio_s"), evento.get("inicio_s")) \
            or not _mesmo_tempo(prova.get("fim_s"), evento.get("fim_s")):
        falhas.add("PROVA-TEMPO-DIVERGENTE",
                   "recibo precisa repetir inicio_s/fim_s exatos do evento", eid)
    visual = evento.get("visual")
    tipo = visual.get("tipo") if isinstance(visual, dict) else None
    if prova.get("visual_tipo") != tipo:
        falhas.add("PROVA-VISUAL-DIVERGENTE",
                   "recibo.visual_tipo não corresponde ao visual planejado", eid)
    if prova.get("camada") != "grafismo":
        falhas.add("PROVA-NAO-GRAFICA",
                   "recibo.camada deve ser `grafismo`; legenda/caption não conta", eid)
    if not _texto(plano_sha256) or prova.get("plano_sha256") != plano_sha256:
        falhas.add("STALE-PLANO-VISUAL",
                   "recibo.plano_sha256 não corresponde ao plano entregue", eid)

    render = prova.get("render")
    if not isinstance(render, dict):
        falhas.add("RENDER-VISUAL-AUSENTE",
                   "recibo.render deve vincular o evento ao render gráfico", eid)
        return
    if not isinstance(render_oficial, dict) or render != render_oficial:
        falhas.add("RENDER-SEM-PROVENIENCIA-REMOTION",
                   "recibo.render não corresponde à execução oficial do Remotion", eid)
        return
    rel = render.get("arquivo")
    caminho = _caminho_da_producao(d, rel)
    if caminho is None:
        falhas.add("RENDER-VISUAL-CAMINHO-INVALIDO",
                   "recibo.render.arquivo deve ficar dentro da produção", eid)
        return
    if _texto(render_corte) and Path(rel).as_posix() == Path(render_corte).as_posix():
        falhas.add("RENDER-VISUAL-E-CORTE",
                   "o render do corte-base não comprova a camada gráfica", eid)
        return
    if caminho.suffix.lower() not in {".mov", ".mp4", ".webm", ".mkv"}:
        falhas.add("RENDER-VISUAL-FORMATO-INVALIDO",
                   "render visual deve ser vídeo MOV, MP4, WebM ou MKV", eid)
        return
    try:
        existe = caminho.is_file() and caminho.stat().st_size > 0
    except OSError:
        existe = False
    if not existe:
        falhas.add("RENDER-VISUAL-AUSENTE", "%s não existe ou está vazio" % rel, eid)
        return
    esperado = render.get("sha256")
    atual = hashes.get(caminho)
    if atual is None:
        try:
            atual = _sha256_arquivo(caminho)
        except OSError as exc:
            falhas.add("RENDER-VISUAL-NAO-MEDIDO",
                       "não foi possível calcular SHA-256: %s" % exc, eid)
            return
        hashes[caminho] = atual
    if not _texto(esperado) or esperado != atual:
        falhas.add("STALE-RENDER-VISUAL",
                   "recibo.render.sha256 não corresponde aos bytes do render", eid)
        return
    _validar_video_render(caminho, falhas, eid)


def _validar_video_render(caminho: Path, falhas: Falhas, eid: str) -> None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        falhas.add("FFPROBE-AUSENTE",
                   "ffprobe é obrigatório para provar o render visual", eid)
        return
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_type,width,height,duration,nb_frames",
        "-show_entries", "format=duration", "-of", "json", str(caminho),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        falhas.add("RENDER-VISUAL-NAO-MEDIDO",
                   "ffprobe não conseguiu medir o render: %s" % exc, eid)
        return
    try:
        obj = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        obj = None
    streams = obj.get("streams") if isinstance(obj, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams else None
    if not isinstance(stream, dict) or stream.get("codec_type") != "video":
        detalhe = (r.stderr or "nenhum stream de vídeo").strip().splitlines()[-1]
        falhas.add("RENDER-VISUAL-INVALIDO",
                   "ffprobe não encontrou stream de vídeo: %s" % detalhe, eid)
        return
    largura, altura = stream.get("width"), stream.get("height")
    dimensoes = (_numero(largura) and _numero(altura)
                 and float(largura) > 0 and float(altura) > 0)
    duracoes = [stream.get("duration")]
    formato = obj.get("format") if isinstance(obj, dict) else None
    if isinstance(formato, dict):
        duracoes.append(formato.get("duration"))
    duracao_ok = False
    for valor in duracoes:
        try:
            duracao_ok = math.isfinite(float(valor)) and float(valor) > 0
        except (TypeError, ValueError):
            continue
        if duracao_ok:
            break
    frames = stream.get("nb_frames")
    frames_ok = isinstance(frames, (str, int)) and str(frames).isdigit() \
        and int(frames) > 0
    if not dimensoes or not (duracao_ok or frames_ok):
        falhas.add("RENDER-VISUAL-INVALIDO",
                   "stream precisa ter dimensões e duração ou frames positivos", eid)


def _resolver_sfx(d: Path, asset: str) -> Path | None:
    p = Path(asset)
    if p.is_absolute() or ".." in p.parts:
        return None
    nomes = [p]
    if not p.suffix:
        nomes.append(Path(str(p) + ".wav"))
    candidatos: list[Path] = []
    for nome in nomes:
        candidatos.extend((d / nome, d / "sfx" / nome))
        partes = nome.parts[1:] if nome.parts and nome.parts[0] == "sfx" else nome.parts
        candidatos.append(SFX_CANONICOS.joinpath(*partes))
        if nome.parts and nome.parts[0] == "tools":
            candidatos.append(RAIZ_ILHA / nome)
    bases = (d.resolve(), SFX_CANONICOS.resolve(), RAIZ_ILHA.resolve())
    for candidato in candidatos:
        resolvido = candidato.resolve()
        if not resolvido.is_file():
            continue
        if any(_dentro(resolvido, base) for base in bases):
            return resolvido
    return None


def _dentro(caminho: Path, base: Path) -> bool:
    try:
        caminho.relative_to(base)
        return True
    except ValueError:
        return False


def _validar_preparo_remotion(d: Path, eventos: list[dict[str, Any]],
                              plano_sha256: str | None,
                              falhas: Falhas) -> dict[str, Any] | None:
    """Prova que o plano atual entrou no dado consumido pelo compositor."""
    manifesto_path = d / "remotion" / "plano-visual-preparado.json"
    if not manifesto_path.is_file():
        falhas.add(
            "PREPARO-REMOTION-AUSENTE",
            "%s não existe; rode compilar-plano-visual.py preparar" % manifesto_path,
        )
        return None
    try:
        manifesto = _ler_json(manifesto_path)
    except (OSError, ValueError) as exc:
        falhas.add("PREPARO-REMOTION-INVALIDO", "%s: %s" % (manifesto_path, exc))
        return None
    if not isinstance(manifesto, dict) \
            or manifesto.get("contrato") != CONTRATO_PREPARO_REMOTION:
        falhas.add("PREPARO-REMOTION-INVALIDO",
                   "manifesto deve usar `%s`" % CONTRATO_PREPARO_REMOTION)
        return None
    if manifesto.get("plano_sha256") != plano_sha256:
        falhas.add("STALE-PREPARO-REMOTION",
                   "manifesto não corresponde ao plano-visual.json atual")
        return None
    compilado = _caminho_da_producao(d, manifesto.get("compilado"))
    if compilado is None or not compilado.is_file():
        falhas.add("PREPARO-REMOTION-AUSENTE",
                   "partitura compilada declarada no manifesto não existe")
        return None
    try:
        compilado_sha = _sha256_arquivo(compilado)
    except OSError as exc:
        falhas.add("PREPARO-REMOTION-INVALIDO",
                   "não foi possível medir a partitura compilada: %s" % exc)
        return None
    if manifesto.get("compilado_sha256") != compilado_sha:
        falhas.add("STALE-PREPARO-REMOTION",
                   "partitura compilada mudou depois de `preparar`")
        return None
    public_tree = _inventariar_public(d, manifesto.get("public_dir"), falhas)
    if public_tree is None:
        return None
    if manifesto.get("public_tree") != public_tree:
        falhas.add("STALE-PUBLIC-TREE",
                   "assets de public_dir mudaram depois de `preparar`")
        return None
    try:
        doc = _ler_json(compilado)
    except (OSError, ValueError) as exc:
        falhas.add("PREPARO-REMOTION-INVALIDO", "%s: %s" % (compilado, exc))
        return None
    meta = doc.get("_plano_visual_compilacao") if isinstance(doc, dict) else None
    if not isinstance(meta, dict) \
            or meta.get("contrato") != CONTRATO_COMPILACAO_REMOTION \
            or meta.get("fonte_sha256") != plano_sha256:
        falhas.add("STALE-PREPARO-REMOTION",
                   "partitura compilada não contém o plano atual")
        return None
    for i, evento in enumerate(eventos):
        eid = evento.get("id") if _texto(evento.get("id")) else "#%d" % i
        impl = evento.get("implementacao")
        ref = impl.get("ref") if isinstance(impl, dict) else None
        if not isinstance(ref, dict) or ref.get("tipo") != "json-pointer" \
                or not _texto(ref.get("valor")):
            falhas.add("PREPARO-EVENTO-AUSENTE",
                       "evento não tem JSON Pointer compilável", eid)
            continue
        ok, alvo = _json_pointer(doc, ref["valor"])
        if not ok or not isinstance(alvo, dict) \
                or alvo.get("plano_visual_evento_id") != evento.get("id"):
            falhas.add("PREPARO-EVENTO-AUSENTE",
                       "partitura compilada não materializa este evento", eid)
    return manifesto


def _validar_execucao_remotion(d: Path, preparo: dict[str, Any] | None,
                               plano_sha256: str | None,
                               falhas: Falhas) -> dict[str, Any] | None:
    caminho = d / "remotion" / "plano-visual-render.json"
    if not caminho.is_file():
        falhas.add(
            "RENDER-REMOTION-AUSENTE",
            "%s não existe; use compilar-plano-visual.py renderizar" % caminho,
        )
        return None
    try:
        manifesto = _ler_json(caminho)
    except (OSError, ValueError) as exc:
        falhas.add("RENDER-REMOTION-INVALIDO", "%s: %s" % (caminho, exc))
        return None
    if not isinstance(manifesto, dict) \
            or manifesto.get("contrato") != CONTRATO_RENDER_REMOTION \
            or manifesto.get("remotion_executado") is not True \
            or manifesto.get("exit") != 0:
        falhas.add("RENDER-REMOTION-INVALIDO",
                   "manifesto não comprova Remotion executado com exit 0")
        return None
    if manifesto.get("plano_sha256") != plano_sha256:
        falhas.add("STALE-RENDER-REMOTION",
                   "execução Remotion não corresponde ao plano atual")
        return None
    if not isinstance(preparo, dict):
        falhas.add("RENDER-REMOTION-INVALIDO",
                   "execução não tem preparo oficial válido como origem")
        return None
    public_tree = _inventariar_public(d, preparo.get("public_dir"), falhas)
    if public_tree is None:
        return None
    if preparo.get("public_tree") != public_tree \
            or manifesto.get("public_tree") != public_tree:
        falhas.add("STALE-PUBLIC-TREE",
                   "preparo, render e public_dir atual não têm os mesmos assets")
        return None
    compilado = manifesto.get("compilado")
    comando = manifesto.get("comando")
    if not isinstance(compilado, dict) \
            or compilado.get("arquivo") != preparo.get("compilado") \
            or compilado.get("sha256") != preparo.get("compilado_sha256"):
        falhas.add("STALE-RENDER-REMOTION",
                   "execução usou props diferentes da partitura preparada")
        return None
    esperado_comando = {
        "entrypoint": "src/index-partitura.tsx",
        "composition": "Graphics",
        "props": preparo.get("compilado"),
        "public_dir": preparo.get("public_dir"),
    }
    if comando != esperado_comando:
        falhas.add("RENDER-REMOTION-COMANDO-INVALIDO",
                   "execução não usou entrypoint, props e public-dir oficiais")
        return None
    render = manifesto.get("render")
    if not isinstance(render, dict) or not _texto(render.get("arquivo")) \
            or not _texto(render.get("sha256")):
        falhas.add("RENDER-REMOTION-INVALIDO",
                   "manifesto não identifica o render publicado")
        return None
    render_path = _caminho_da_producao(d, render["arquivo"])
    if render_path is None or not render_path.is_file():
        falhas.add("RENDER-REMOTION-AUSENTE",
                   "render declarado pela execução não existe")
        return None
    try:
        sha_atual = _sha256_arquivo(render_path)
    except OSError as exc:
        falhas.add("RENDER-REMOTION-INVALIDO",
                   "não foi possível medir o render oficial: %s" % exc)
        return None
    if render.get("sha256") != sha_atual:
        falhas.add("STALE-RENDER-REMOTION",
                   "render mudou depois da execução oficial")
        return None
    return render


def _chave_casefold(nome: str) -> str:
    """Chave portátil entre APFS/HFS+ e filesystems Linux case-sensitive."""
    return unicodedata.normalize("NFKC", nome).casefold()


def _nome_final_reconhecido(nome: str) -> bool:
    if not nome.isascii():
        return False
    return re.fullmatch(r"(?:v-final|v2-final).*\.mp4", nome,
                        flags=re.ASCII | re.IGNORECASE) is not None


def _finais_atuais(d: Path, falhas: Falhas, *, listar=None) -> list[Path]:
    """Descobre somente finais no root, sem depender da caixa da extensão."""
    finais = []
    listar = listar or (lambda raiz: raiz.iterdir())
    try:
        entradas = sorted(listar(d),
                           key=lambda p: (_chave_casefold(p.name), p.name))
    except OSError as exc:
        falhas.add(
            "FINAL-VISUAL-VARREDURA-INVALIDA",
            "não foi possível listar a raiz da produção: %s" % exc,
        )
        return finais
    for achado in entradas:
        if not _nome_final_reconhecido(achado.name):
            continue
        # Toda entrada com nome oficial entra no inventário. Regularidade é
        # verificada depois; diretório, FIFO ou symlink não podem virar ausência.
        finais.append(achado.absolute())
    return finais


def _diretorio_manifestos_finais(d: Path, falhas: Falhas) -> Path | None:
    """Resolve o diretório fixo sem seguir symlink em nenhum componente."""
    atual = d.resolve()
    for nome in ("remotion", "plano-visual-finais"):
        atual = atual / nome
        try:
            modo = atual.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                       "não foi possível validar %s: %s" % (atual, exc))
            return None
        else:
            if stat.S_ISLNK(modo):
                falhas.add(
                    "FINAL-VISUAL-CAMINHO-INVALIDO",
                    "%s não pode ser symlink" % atual,
                )
                return None
            if not stat.S_ISDIR(modo):
                falhas.add(
                    "FINAL-VISUAL-CAMINHO-INVALIDO",
                    "%s deve ser diretório regular" % atual,
                )
                return None
    try:
        atual.resolve().relative_to(d.resolve())
    except (OSError, ValueError):
        falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                   "diretório de manifestos escapou da produção")
        return None
    return atual


def _manifestos_finais(d: Path, falhas: Falhas) -> list[tuple[Path, dict[str, Any]]]:
    """Carrega a prova por entregável, com leitura do sidecar único legado.

    Um único ``plano-visual-final.json`` era sobrescrito a cada composição e,
    portanto, não conseguia provar simultaneamente a versão com grade e a versão
    sem filtro previstas pelo perfil Reels. A autoridade nova é um arquivo por
    saída em ``remotion/plano-visual-finais/``. O sidecar antigo só é consultado
    quando ainda não existe nenhum manifesto por saída.
    """
    diretorio = _diretorio_manifestos_finais(d, falhas)
    if diretorio is None:
        return []
    caminhos: list[Path] = []
    try:
        modo_diretorio = diretorio.lstat().st_mode
    except FileNotFoundError:
        modo_diretorio = None
    except OSError as exc:
        falhas.add("FINAL-VISUAL-INVALIDO",
                   "não foi possível inspecionar %s: %s" % (diretorio, exc))
        return []
    if modo_diretorio is not None:
        if stat.S_ISLNK(modo_diretorio) or not stat.S_ISDIR(modo_diretorio):
            falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                       "%s deixou de ser diretório regular" % diretorio)
            return []
        try:
            caminhos = sorted(
                (p for p in diretorio.iterdir()
                 if _chave_casefold(p.name).endswith(".json")),
                key=lambda p: (_chave_casefold(p.name), p.name),
            )
        except OSError as exc:
            falhas.add("FINAL-VISUAL-INVALIDO",
                       "não foi possível listar %s: %s" % (diretorio, exc))
    if not caminhos:
        legado = d / "remotion" / "plano-visual-final.json"
        try:
            modo_legado = legado.lstat().st_mode
        except FileNotFoundError:
            modo_legado = None
        except OSError as exc:
            falhas.add("FINAL-VISUAL-INVALIDO",
                       "não foi possível inspecionar %s: %s" % (legado, exc))
            return []
        if modo_legado is not None:
            if stat.S_ISLNK(modo_legado) or not stat.S_ISREG(modo_legado):
                falhas.add("FINAL-VISUAL-INVALIDO",
                           "manifesto legado deve ser arquivo regular: %s" % legado)
            else:
                caminhos = [legado]
    por_nome: dict[str, list[Path]] = {}
    for caminho in caminhos:
        por_nome.setdefault(_chave_casefold(caminho.name), []).append(caminho)
    colidentes = {
        caminho
        for grupo in por_nome.values() if len(grupo) > 1
        for caminho in grupo
    }
    for grupo in por_nome.values():
        if len(grupo) > 1:
            falhas.add(
                "FINAL-VISUAL-MANIFESTO-COLIDENTE",
                "manifestos diferem apenas por caixa/normalização: %s"
                % ", ".join(sorted(p.name for p in grupo)),
            )
    manifestos: list[tuple[Path, dict[str, Any]]] = []
    for caminho in caminhos:
        if caminho in colidentes:
            continue
        try:
            modo = caminho.lstat().st_mode
        except OSError as exc:
            falhas.add("FINAL-VISUAL-INVALIDO",
                       "não foi possível inspecionar %s: %s" % (caminho, exc))
            continue
        if stat.S_ISLNK(modo) or not stat.S_ISREG(modo):
            falhas.add("FINAL-VISUAL-INVALIDO",
                       "manifesto deve ser arquivo regular: %s" % caminho)
            continue
        try:
            manifesto = _ler_json(caminho)
        except (OSError, ValueError) as exc:
            falhas.add("FINAL-VISUAL-INVALIDO", "%s: %s" % (caminho, exc))
            continue
        if not isinstance(manifesto, dict):
            falhas.add("FINAL-VISUAL-INVALIDO",
                       "%s não contém um objeto JSON" % caminho)
            continue
        manifestos.append((caminho, manifesto))
    return manifestos


def _validar_manifesto_final(d: Path, final_atual: Path,
                             caminho_manifesto: Path,
                             manifesto: dict[str, Any],
                             eventos: list[dict[str, Any]],
                             plano_sha256: str | None,
                             render_oficial: dict[str, Any] | None,
                             falhas: Falhas) -> None:
    """Valida a composição oficial de exatamente um entregável final."""
    rotulo = final_atual.name
    if manifesto.get("contrato") != CONTRATO_FINAL_REMOTION \
            or manifesto.get("exit") != 0 \
            or manifesto.get("video_grafico_sobreposto") is not True:
        falhas.add("FINAL-VISUAL-INVALIDO",
                   "%s não comprova overlay oficial com exit 0" % caminho_manifesto)
        return
    if manifesto.get("plano_sha256") != plano_sha256:
        falhas.add("STALE-FINAL-VISUAL",
                   "%s não corresponde ao plano atual" % rotulo)
        return
    grafico = manifesto.get("grafico")
    if not isinstance(render_oficial, dict) or grafico != render_oficial:
        falhas.add("FINAL-GRAFICO-DIVERGENTE",
                   "%s não usou o render Remotion aprovado" % rotulo)
        return
    render_manifesto = d / "remotion" / "plano-visual-render.json"
    try:
        render_manifesto_sha = _sha256_arquivo(render_manifesto)
    except OSError as exc:
        falhas.add("FINAL-VISUAL-INVALIDO",
                   "não foi possível medir o manifesto de render: %s" % exc)
        return
    if manifesto.get("render_manifesto_sha256") != render_manifesto_sha:
        falhas.add("STALE-FINAL-VISUAL",
                   "%s não aponta para o manifesto de render atual" % rotulo)
        return
    base = manifesto.get("base")
    base_path = (_caminho_da_producao(d, base.get("arquivo"))
                 if isinstance(base, dict) else None)
    if base_path is None or not base_path.is_file():
        falhas.add("FINAL-BASE-AUSENTE",
                   "base declarada para %s não existe" % rotulo)
        return
    try:
        base_sha = _sha256_arquivo(base_path)
    except OSError as exc:
        falhas.add("FINAL-BASE-INVALIDA",
                   "não foi possível medir a base de %s: %s" % (rotulo, exc))
        return
    if base.get("sha256") != base_sha:
        falhas.add("STALE-FINAL-BASE",
                   "base de %s mudou depois da composição" % rotulo)
        return
    final = manifesto.get("final")
    final_rel = final_atual.relative_to(d.resolve()).as_posix()
    try:
        final_sha = _sha256_arquivo(final_atual)
    except OSError as exc:
        falhas.add("FINAL-VISUAL-INVALIDO",
                   "não foi possível medir %s: %s" % (rotulo, exc))
        return
    if not isinstance(final, dict) or final != {"arquivo": final_rel,
                                                "sha256": final_sha}:
        falhas.add("STALE-FINAL-VISUAL",
                   "manifesto não corresponde a %s atual" % rotulo)
        return
    sfx_esperado = any(
        isinstance(evento.get("som"), dict)
        and evento["som"].get("decisao") == "usar"
        for evento in eventos
    )
    comando = manifesto.get("comando")
    audio_esperado = ("amix:normalize=0:duration=first"
                      if sfx_esperado else "audio-base")
    if manifesto.get("sfx_esperado") is not sfx_esperado \
            or manifesto.get("audio_grafico_misturado") is not sfx_esperado \
            or not isinstance(comando, dict) \
            or comando.get("motor") != "ffmpeg" \
            or comando.get("unpremultiply") is not True \
            or comando.get("overlay") is not True \
            or comando.get("audio") != audio_esperado:
        falhas.add(
            "FINAL-SFX-NAO-MISTURADO" if sfx_esperado else "FINAL-COMPOSICAO-INVALIDA",
            ("%s com SFX exige amix do áudio gráfico" % rotulo
             if sfx_esperado else
             "%s não preservou a política de áudio" % rotulo),
        )
        return
    _validar_video_render(final_atual, falhas, "final %s" % rotulo)


def _validar_composicao_final(d: Path, eventos: list[dict[str, Any]],
                              plano_sha256: str | None,
                              render_oficial: dict[str, Any] | None,
                              falhas: Falhas) -> None:
    finais = _finais_atuais(d, falhas)
    if not finais:
        return
    por_nome: dict[str, list[Path]] = {}
    for final in finais:
        por_nome.setdefault(_chave_casefold(final.name), []).append(final)
    colidentes = {
        caminho
        for grupo in por_nome.values() if len(grupo) > 1
        for caminho in grupo
    }
    for grupo in por_nome.values():
        if len(grupo) > 1:
            falhas.add(
                "FINAL-VISUAL-NOME-COLIDENTE",
                "finais diferem apenas por caixa/normalização: %s"
                % ", ".join(sorted(p.name for p in grupo)),
            )
    manifestos = _manifestos_finais(d, falhas)
    por_saida: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for caminho, manifesto in manifestos:
        final = manifesto.get("final")
        rel = final.get("arquivo") if isinstance(final, dict) else None
        if _texto(rel):
            por_saida.setdefault(rel, []).append((caminho, manifesto))
    for final_atual in finais:
        if final_atual in colidentes:
            continue
        try:
            modo = final_atual.lstat().st_mode
        except OSError as exc:
            falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                       "não foi possível inspecionar %s: %s"
                       % (final_atual.name, exc))
            continue
        if stat.S_ISLNK(modo):
            falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                       "%s é symlink; entregável deve ser arquivo regular"
                       % final_atual.name)
            continue
        if not stat.S_ISREG(modo):
            falhas.add("FINAL-VISUAL-CAMINHO-INVALIDO",
                       "%s não é arquivo regular" % final_atual.name)
            continue
        final_rel = final_atual.relative_to(d.resolve()).as_posix()
        provas = por_saida.get(final_rel, [])
        if not provas:
            falhas.add(
                "FINAL-VISUAL-SEM-PROVENIENCIA",
                "%s existe, mas não tem composição oficial própria; use `compor-final`"
                % final_rel,
            )
            continue
        if len(provas) != 1:
            falhas.add(
                "FINAL-VISUAL-PROVENIENCIA-DUPLICADA",
                "%s tem %d manifestos de composição" % (final_rel, len(provas)),
            )
            continue
        caminho, manifesto = provas[0]
        _validar_manifesto_final(
            d, final_atual, caminho, manifesto, eventos,
            plano_sha256, render_oficial, falhas,
        )


def _validar_entrega(d: Path, eventos: list[dict[str, Any]],
                     render_corte: str | None, plano_sha256: str | None,
                     falhas: Falhas) -> None:
    if eventos:
        preparo = _validar_preparo_remotion(d, eventos, plano_sha256, falhas)
        render_oficial = _validar_execucao_remotion(d, preparo, plano_sha256, falhas)
        _validar_composicao_final(d, eventos, plano_sha256, render_oficial, falhas)
    else:
        render_oficial = None
    refs: set[str] = set()
    hashes: dict[Path, str] = {}
    for i, evento in enumerate(eventos):
        eid = evento.get("id") if _texto(evento.get("id")) else "#%d" % i
        impl = evento.get("implementacao")
        if not isinstance(impl, dict):
            falhas.add("IMPLEMENTACAO-AUSENTE",
                       "gate entrega exige evento.implementacao", eid)
        else:
            rel = impl.get("artefato")
            if not _texto(rel):
                falhas.add("ARTEFATO-GRAFICO-AUSENTE",
                           "implementacao.artefato deve ser caminho relativo", eid)
            elif _e_artefato_de_caption(rel):
                falhas.add("ARTEFATO-CAPTIONS",
                           "captions não comprovam implementação gráfica", eid)
            else:
                caminho = _caminho_da_producao(d, rel)
                if caminho is None:
                    falhas.add("ARTEFATO-CAMINHO-INVALIDO",
                               "artefato deve ficar dentro da produção", eid)
                elif not caminho.is_file():
                    falhas.add("ARTEFATO-GRAFICO-AUSENTE", "%s não existe" % rel, eid)
                else:
                    ref = impl.get("ref")
                    chave_ref = rel + "|" + json.dumps(ref, ensure_ascii=False,
                                                       sort_keys=True)
                    if chave_ref in refs:
                        falhas.add("IMPLEMENTACAO-REF-DUPLICADA",
                                   "cada evento precisa de referência própria", eid)
                    refs.add(chave_ref)
                    ok, alvo, motivo = _verificar_ref(caminho, ref)
                    if not ok:
                        falhas.add("IMPLEMENTACAO-REF-INVALIDA", motivo, eid)
                    elif ref.get("tipo") != "json-pointer":
                        falhas.add(
                            "PROVA-VISUAL-INVALIDA",
                            "gate entrega exige JSON Pointer para um recibo estruturado por evento",
                            eid,
                        )
                    else:
                        _validar_prova_visual(d, evento, alvo, render_corte,
                                              plano_sha256, render_oficial,
                                              hashes, falhas, eid)

        som = evento.get("som")
        if isinstance(som, dict) and som.get("decisao") == "usar" \
                and _texto(som.get("asset")):
            if _resolver_sfx(d, som["asset"]) is None:
                falhas.add("SFX-AUSENTE", "asset `%s` não existe" % som["asset"], eid)


def validar(d: Path, gate: str) -> tuple[int, dict[str, Any]]:
    falhas = Falhas()
    ctx = _contexto_atual(d, falhas)
    caminho = d / ARQUIVO
    if not caminho.is_file():
        falhas.add("PLANO-VISUAL-AUSENTE", "%s não existe; rode --iniciar" % caminho)
        doc: dict[str, Any] = {}
    else:
        try:
            bruto = _ler_json(caminho)
            doc = bruto if isinstance(bruto, dict) else {}
            if not isinstance(bruto, dict):
                falhas.add("PLANO-VISUAL-INVALIDO", "o plano deve ser objeto JSON")
        except (OSError, ValueError) as exc:
            falhas.add("PLANO-VISUAL-INVALIDO", "%s: %s" % (caminho, exc))
            doc = {}

    if doc.get("contrato") != CONTRATO:
        falhas.add("CONTRATO-INVALIDO", "plano deve usar `%s`" % CONTRATO)
    _validar_vinculos(doc, ctx, falhas)

    direcao_plano = doc.get("direcao_edicao")
    direcao_ok = _direcao_valida(direcao_plano, falhas, "plano-visual.json")
    direcao_atual = ctx.get("estilo", {}).get("direcao") if ctx.get("estilo") else None
    if direcao_ok and direcao_atual is not None and direcao_plano != direcao_atual:
        falhas.add("DIRECAO-DIVERGENTE",
                   "direcao_edicao do plano não é a decisão vigente da aba Estilo")
    if direcao_ok and direcao_plano.get("modo") == "surpresa":
        _validar_direcao_resolvida(doc, falhas)

    total_s = ctx.get("timeline", {}).get("total_s") if ctx.get("timeline") else None
    eventos = _validar_eventos(doc, direcao_plano if direcao_ok else None,
                               total_s, falhas)
    if gate == "entrega":
        vinculos = doc.get("vinculos")
        vinculo_corte = vinculos.get("render_corte") if isinstance(vinculos, dict) else None
        render_corte = (vinculo_corte.get("arquivo")
                        if isinstance(vinculo_corte, dict) else None)
        try:
            plano_sha256 = _sha256_arquivo(caminho) if caminho.is_file() else None
        except OSError as exc:
            plano_sha256 = None
            falhas.add("PLANO-VISUAL-NAO-MEDIDO",
                       "não foi possível calcular SHA-256 do plano: %s" % exc)
        _validar_entrega(d, eventos, render_corte, plano_sha256, falhas)

    resultado = {
        "contrato": CONTRATO_QC,
        "gate": gate,
        "arquivo": str(caminho.resolve()),
        "veredito": "reprovado" if falhas else "aprovado",
        "modo": direcao_plano.get("modo") if isinstance(direcao_plano, dict) else None,
        "timeline_real_s": total_s,
        "eventos": len(doc.get("eventos") or []) if isinstance(doc.get("eventos"), list) else 0,
        "erros": falhas.itens,
    }
    return (1 if falhas else 0), resultado


def _imprimir(resultado: dict[str, Any], como_json: bool) -> None:
    if como_json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return
    veredito = resultado.get("veredito", "")
    acao = resultado.get("gate") or resultado.get("acao") or ""
    print("%s · %s" % (veredito.upper(), acao))
    if resultado.get("arquivo"):
        print("arquivo: %s" % resultado["arquivo"])
    if resultado.get("modo"):
        print("modo: %s" % resultado["modo"])
    if resultado.get("mensagem"):
        print(resultado["mensagem"])
    for erro in resultado.get("erros") or []:
        onde = " · %s" % erro["evento"] if erro.get("evento") else ""
        print("[%s]%s %s" % (erro["codigo"], onde, erro["mensagem"]), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="inicia e valida o contrato benchmark.plano-visual/v1")
    ap.add_argument("dir", help="diretório da produção")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--iniciar", action="store_true",
                       help="cria plano-visual.json sem sobrescrever")
    grupo.add_argument("--validar", choices=("planejamento", "entrega"),
                       help="gate a conferir")
    ap.add_argument("--json", action="store_true", help="resultado estruturado")
    args = ap.parse_args(argv)

    d = Path(args.dir).resolve()
    if not d.is_dir():
        resultado = {"contrato": CONTRATO_QC, "acao": "iniciar" if args.iniciar else args.validar,
                     "veredito": "reprovado", "erros": [{
                         "codigo": "PRODUCAO-AUSENTE",
                         "mensagem": "%s não é diretório" % d,
                     }]}
        _imprimir(resultado, args.json)
        return 1
    codigo, resultado = iniciar(d) if args.iniciar else validar(d, args.validar)
    _imprimir(resultado, args.json)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
