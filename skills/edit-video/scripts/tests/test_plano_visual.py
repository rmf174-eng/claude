#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão standalone do contrato benchmark.plano-visual/v1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# O teste de uma release valida o hash da arvore. Imports locais nao podem
# materializar __pycache__ e invalidar o proprio pacote antes dessa medicao.
sys.dont_write_bytecode = True


SCRIPT = Path(__file__).resolve().parents[1] / "plano-visual.py"
ESTADO = Path(__file__).resolve().parents[1] / "estado.py"
COMPILADOR = (Path(__file__).resolve().parents[3] / "remotion-compositor" /
              "scripts" / "compilar-plano-visual.py")

_SPEC = importlib.util.spec_from_file_location("plano_visual_gate", SCRIPT)
GATE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(GATE)

_COMP_SPEC = importlib.util.spec_from_file_location(
    "compilar_plano_visual_harness", COMPILADOR)
COMPILADOR_MOD = importlib.util.module_from_spec(_COMP_SPEC)
assert _COMP_SPEC.loader is not None
_COMP_SPEC.loader.exec_module(COMPILADOR_MOD)

VALIDADOR_RELEASE = (COMPILADOR_MOD.RAIZ_ILHA / "tools" / "pacote" /
                     "release-validacao.py")
_RELEASE_SPEC = importlib.util.spec_from_file_location(
    "ilha_release_validacao_harness", VALIDADOR_RELEASE)
VALIDACAO_RELEASE = importlib.util.module_from_spec(_RELEASE_SPEC)
assert _RELEASE_SPEC.loader is not None
_RELEASE_SPEC.loader.exec_module(VALIDACAO_RELEASE)

_RENDERS_HARNESS = {"dinamico-remotion": 0, "contrato-sem-deps": 0}


def _json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fp_edl(segmentos) -> str:
    canon = json.dumps(segmentos, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canon.encode("utf-8")).hexdigest()


def _producao(base: Path, modo="animada", sfx="automatico") -> Path:
    d = base / "producao"
    d.mkdir()
    direcao = {"modo": modo,
               "densidade": "leve" if modo == "essencial" else "equilibrada",
               "sfx": sfx}
    _json(d / ".preview" / "estilo-vigente.json", {
        "contrato": "benchmark.edit-estilo-vigente/v1",
        "estilo": {
            "contrato": "benchmark.edit-estilo/v3",
            "direcao_edicao": direcao,
            "elementos": {"sfx": sfx == "automatico"},
        },
    })
    (d / "PLANO-EDICAO.md").write_text("# Plano\n\nCorte aprovado.\n", encoding="utf-8")
    (d / "v1-montado.mp4").write_bytes(b"render-do-corte")
    segmentos = [{"src": "bruto.mp4", "start": 0.0, "end": 10.0,
                  "beat": "fala"}]
    timeline = {
        "schema": "benchmark.timeline-real/v1",
        "edl_fingerprint": _fp_edl(segmentos),
        "video": {"width": 1080, "height": 1920, "fps": 30.0,
                  "fps_num": 30, "fps_den": 1},
        "total_frames": 300,
        "total_s": 10.0,
        "segments": [{"i": 0, "frames": 300, "start_frame": 0,
                      "start_s": 0.0, "dur_s": 10.0}],
    }
    _json(d / "edl.json", {"schema": "benchmark.edl/v2", "segments": segmentos,
                            "timeline_real": timeline})
    return d


def _run(d: Path, *args: str, env=None):
    r = subprocess.run([sys.executable, str(SCRIPT), str(d), *args, "--json"],
                       text=True, capture_output=True, env=env)
    try:
        obj = json.loads(r.stdout)
    except ValueError as exc:
        raise AssertionError("stdout não é JSON:\n%s\nstderr:\n%s" %
                             (r.stdout, r.stderr)) from exc
    return r, obj


def _iniciar(d: Path) -> dict:
    r, obj = _run(d, "--iniciar")
    if r.returncode != 0:
        raise AssertionError("--iniciar falhou: %s\n%s" % (obj, r.stderr))
    return json.loads((d / "plano-visual.json").read_text(encoding="utf-8"))


def _evento(*, som=None, artefato="graphics.json", fim=2.0):
    return {
        "id": "beat-001",
        "inicio_s": 0.5,
        "fim_s": fim,
        "beat": "gancho",
        "visual": {"tipo": "cartao", "descricao": "cartão entra no verbo-chave"},
        "zona": "topo-seguro",
        "som": som or {"decisao": "silencio-intencional",
                       "motivo": "a fala já tem ataque forte"},
        "implementacao": {
            "artefato": artefato,
            "ref": {"tipo": "json-pointer", "valor": "/overlays/0"},
        },
    }


def _salvar_plano(d: Path, plano: dict) -> None:
    _json(d / "plano-visual.json", plano)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _gerar_render_sintetico(caminho: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AssertionError("ffmpeg ausente: fixture não pode fingir render com bytes")
    gerou = subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=16x16:d=0.2", "-an", "-c:v", "mpeg4", "-q:v", "5",
        str(caminho),
    ], text=True, capture_output=True)
    if gerou.returncode != 0:
        raise AssertionError("falha ao gerar render sintético: %s" % gerou.stderr)


def _lexiste(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _validar_release_extraida(raiz: Path) -> None:
    """Deriva a versao e chama exatamente os dois validadores oficiais."""
    recibo = raiz / "RELEASE.json"
    if not _lexiste(recibo):
        raise AssertionError(
            "Remotion ausente fora de release extraida: RELEASE.json ausente")
    try:
        dados = json.loads(recibo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError("RELEASE.json invalido: %s" % exc) from exc
    versao = dados.get("version") if isinstance(dados, dict) else None
    try:
        VALIDACAO_RELEASE.validar_raiz_exportada(raiz, versao)
        VALIDACAO_RELEASE.validar_metadados_release(raiz, versao)
    except (VALIDACAO_RELEASE.erro_validacao, TypeError) as exc:
        raise AssertionError("release extraida invalida: %s" % exc) from exc


def _modo_render_harness(raiz: Path | None = None) -> str:
    raiz = (raiz or COMPILADOR_MOD.RAIZ_ILHA).resolve()
    compositor = raiz / "tools" / "remotion-compositor"
    node_modules = compositor / "node_modules"
    binario = node_modules / ".bin" / "remotion"

    # A presenca lexical de node_modules caracteriza uma fonte/deps locais,
    # mesmo se for arvore vazia ou symlink quebrado. Nunca cair no fake aqui.
    if _lexiste(node_modules):
        if not _lexiste(binario):
            raise AssertionError(
                "node_modules presente, mas .bin/remotion esta ausente")
        if not binario.is_file():
            raise AssertionError(
                ".bin/remotion quebrado ou nao e arquivo regular")
        if not os.access(binario, os.X_OK):
            raise AssertionError(".bin/remotion existe, mas nao e executavel")
        return "dinamico-remotion"

    _validar_release_extraida(raiz)
    return "contrato-sem-deps"


def _comando_render_controlado(compilado: Path, public_dir: Path,
                                parcial: Path) -> list[str]:
    return [
        "teste-contrato-sem-deps", "src/index-partitura.tsx", "Graphics",
        str(compilado), str(public_dir), str(parcial),
    ]


def _executor_render_controlado(d: Path):
    """Executor do teste extraído: vídeo real, sem fingir instalação Remotion."""
    def executar(comando: list[str]):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise AssertionError(
                "ffmpeg ausente: contrato extraído não pode fabricar bytes cegos")
        saida = Path(comando[-1])
        plano = json.loads((d / "plano-visual.json").read_text(encoding="utf-8"))
        tem_sfx = any(
            isinstance(evento, dict)
            and isinstance(evento.get("som"), dict)
            and evento["som"].get("decisao") == "usar"
            for evento in plano.get("eventos", [])
        )
        cmd = [
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black@0.0:s=64x64:r=10:d=2.1,format=yuva444p10le",
        ]
        if tem_sfx:
            cmd.extend([
                "-f", "lavfi", "-i",
                "sine=frequency=1000:sample_rate=48000:duration=2.1",
                "-map", "0:v", "-map", "1:a",
            ])
        else:
            cmd.extend(["-map", "0:v", "-an"])
        cmd.extend([
            "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt",
            "yuva444p10le",
        ])
        if tem_sfx:
            cmd.extend(["-c:a", "pcm_s16le", "-shortest"])
        cmd.append(str(saida))
        proc = subprocess.run(cmd, text=True, capture_output=True)
        return subprocess.CompletedProcess(
            comando, proc.returncode, proc.stdout, proc.stderr)

    return executar


def _renderizar_prova_harness(d: Path, render: str) -> None:
    """Dinâmico na fonte; contrato controlado somente quando deps não existem."""
    modo = _modo_render_harness()
    if modo == "dinamico-remotion":
        _RENDERS_HARNESS["dinamico-remotion"] += 1
        proc = subprocess.run(
            [sys.executable, str(COMPILADOR), str(d), "renderizar",
             "--saida", render, "--json"],
            text=True, capture_output=True,
        )
        if proc.returncode != 0:
            raise AssertionError("render Remotion real falhou: %s\n%s" %
                                 (proc.stdout, proc.stderr))
        return

    _RENDERS_HARNESS["contrato-sem-deps"] += 1
    try:
        COMPILADOR_MOD.renderizar(
            d.resolve(), render,
            executor=_executor_render_controlado(d),
            construir_comando=_comando_render_controlado,
        )
    except COMPILADOR_MOD.ErroCompilacao as exc:
        raise AssertionError("render controlado do contrato falhou: %s" % exc) from exc


def _gerar_base_com_audio(caminho: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AssertionError("ffmpeg ausente: não há fixture A/V para composição")
    gerou = subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2.1",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2.1",
        "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
        str(caminho),
    ], text=True, capture_output=True)
    if gerou.returncode != 0:
        raise AssertionError("falha ao gerar base A/V: %s" % gerou.stderr)


def _aplicar_prova(d: Path, plano: dict, *, render="graphics-alpha.mov") -> None:
    evento = plano["eventos"][0]
    plano["criado_em"] = "2026-08-16T12:00:00-03:00"
    evento["implementacao"] = {
        "artefato": "partitura.json",
        "ref": {"tipo": "json-pointer", "valor": "/itens/0"},
    }
    _json(d / "partitura.json", {
        "contrato": "benchmark.partitura/v1",
        "_procedencia": {
            "tema": None,
            "perfil": {"video": {"largura": 64, "altura": 64, "fps": 10}},
            "orcamento": {"duracao_s": 2.1},
        },
        "itens": [{
            "id": "visual-001", "papel": "gancho", "componente": "HandText",
            "canal": "visual", "texto": "cartão", "inS": evento["inicio_s"],
            "outS": evento["fim_s"], "zona": "topo", "cor": "highlight",
            "score": 1.0,
        }],
    })
    _salvar_plano(d, plano)
    preparar = subprocess.run(
        [sys.executable, str(COMPILADOR), str(d), "preparar", "--json"],
        text=True, capture_output=True,
    )
    if preparar.returncode != 0:
        raise AssertionError("compilador preparar falhou: %s\n%s" %
                             (preparar.stdout, preparar.stderr))
    _exigir((d / "remotion" / "partitura-compilada.json").is_file(),
            "preparar não publicou a partitura compilada na produção")
    _exigir((d / "remotion" / "plano-visual-preparado.json").is_file(),
            "preparar não publicou o manifesto vinculante")

    _renderizar_prova_harness(d, render)
    caminho_render = d / render
    _exigir(caminho_render.is_file(), "renderizar não publicou o MOV oficial")
    manifesto_render = json.loads(
        (d / "remotion" / "plano-visual-render.json").read_text())
    _exigir(manifesto_render.get("remotion_executado") is True
            and manifesto_render.get("exit") == 0,
            "renderizar não registrou a execução real do Remotion")
    aplicado = json.loads((d / "partitura.json").read_text())["itens"][0]
    _exigir(aplicado.get("contrato") == "benchmark.evento-visual-aplicado/v1",
            "renderizar não gravou o recibo oficial")
    _exigir(aplicado.get("plano_sha256") == _sha256(d / "plano-visual.json"),
            "recibo não foi vinculado aos bytes do plano")


def _codigos(obj) -> set[str]:
    return {e["codigo"] for e in obj.get("erros") or []}


def _exigir(condicao, mensagem) -> None:
    if not condicao:
        raise AssertionError(mensagem)


def caso_essencial_zero_eventos_e_sem_sfx_passa():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), modo="essencial", sfx="sem-sfx")
        _iniciar(d)
        for gate in ("planejamento", "entrega"):
            r, obj = _run(d, "--validar", gate)
            _exigir(r.returncode == 0 and obj["veredito"] == "aprovado", obj)


def caso_iniciar_nao_sobrescreve_e_nao_deixa_parcial():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), modo="essencial", sfx="sem-sfx")
        original = _iniciar(d)
        r, obj = _run(d, "--iniciar")
        _exigir(r.returncode != 0 and "PLANO-JA-EXISTE" in _codigos(obj), obj)
        _exigir(json.loads((d / "plano-visual.json").read_text()) == original,
                "o plano existente foi alterado")
        _exigir(not list(d.glob("*.parcial")) and not list(d.glob(".*.parcial")),
                "sobrou arquivo parcial")


def caso_captions_only_renomeado_passa_planejamento_mas_falha_entrega():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        # O nome não contém caption/legenda. O dente precisa ler o objeto
        # apontado, senão bastaria renomear captions.json para escapar do gate.
        plano["eventos"] = [_evento(artefato="camada-final.json")]
        _salvar_plano(d, plano)
        _json(d / "camada-final.json", {"overlays": [{"texto": "legenda"}]})
        r, obj = _run(d, "--validar", "planejamento")
        _exigir(r.returncode == 0, obj)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0 and "PROVA-VISUAL-INVALIDA" in _codigos(obj), obj)


def caso_sfx_ausente_so_reprova_gate_entrega():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        plano["eventos"] = [_evento(som={"decisao": "usar",
                                                "asset": "nao-existe-947.wav",
                                                "at_s": 0.7,
                                                "ganho_db": -8.0})]
        _salvar_plano(d, plano)
        r, obj = _run(d, "--validar", "planejamento")
        _exigir(r.returncode == 0, obj)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0 and "SFX-AUSENTE" in _codigos(obj), obj)


def caso_silencio_intencional_justificado_passa_entrega():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        plano["eventos"] = [_evento()]
        _aplicar_prova(d, plano)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode == 0, obj)

        (d / "NOTAS.md").write_text("muda sem alterar autoridades\n")
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode == 0, obj)

        ambiente = {"PATH": str(Path(td) / "sem-binarios")}
        r, obj = _run(d, "--validar", "entrega", env=ambiente)
        _exigir(r.returncode != 0 and "FFPROBE-AUSENTE" in _codigos(obj), obj)
        _exigir("Traceback" not in r.stderr, r.stderr)

        plano["eventos"][0]["som"].pop("motivo")
        _salvar_plano(d, plano)
        _r, obj = _run(d, "--validar", "planejamento")
        _exigir("SILENCIO-SEM-JUSTIFICATIVA" in _codigos(obj), obj)
        plano["eventos"][0]["som"]["motivo"] = "a fala já tem ataque forte"
        _salvar_plano(d, plano)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode == 0, obj)

        render = d / "graphics-alpha.mov"
        with render.open("ab") as fh:
            fh.write(b"-mudou-depois-da-execucao")
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0 and "STALE-RENDER-REMOTION" in _codigos(obj), obj)

        # Mesmo adulterando recibo e manifesto para aceitarem os novos bytes,
        # um MOV falso não passa pelo probe de mídia.
        render.write_bytes(b"isto-nao-e-video")
        sha_falso = _sha256(render)
        partitura = json.loads((d / "partitura.json").read_text())
        partitura["itens"][0]["render"]["sha256"] = sha_falso
        _json(d / "partitura.json", partitura)
        manifesto_path = d / "remotion" / "plano-visual-render.json"
        manifesto = json.loads(manifesto_path.read_text())
        manifesto["render"]["sha256"] = sha_falso
        _json(manifesto_path, manifesto)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0 and "RENDER-VISUAL-INVALIDO" in _codigos(obj), obj)


def caso_surpresa_exige_e_preserva_direcao_resolvida():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), modo="surpresa")
        plano = _iniciar(d)
        plano["eventos"] = [_evento()]
        _salvar_plano(d, plano)
        _r, obj = _run(d, "--validar", "planejamento")
        _exigir("SURPRESA-NAO-RESOLVIDA" in _codigos(obj), obj)

        resolvida = {"resumo": "tipografia editorial com dois cartões",
                     "resolvido_por": "agente-editor",
                     "resolvido_em": "2026-08-16T12:00:00-03:00"}
        plano["direcao_resolvida"] = resolvida
        _salvar_plano(d, plano)
        r, obj = _run(d, "--validar", "planejamento")
        _exigir(r.returncode == 0, obj)
        persistido = json.loads((d / "plano-visual.json").read_text())
        _exigir(persistido["direcao_resolvida"] == resolvida,
                "a direção resolvida não foi preservada")


def caso_stale_em_qualquer_binding_e_detectado():
    esperados = {
        "estilo": "STALE-ESTILO",
        "plano": "STALE-PLANO-EDICAO",
        "render": "STALE-RENDER-CORTE",
        "timeline": "STALE-TIMELINE-REAL",
    }
    for caso, esperado in esperados.items():
        with tempfile.TemporaryDirectory() as td:
            d = _producao(Path(td), modo="essencial", sfx="sem-sfx")
            _iniciar(d)
            if caso == "estilo":
                p = d / ".preview" / "estilo-vigente.json"
                p.write_text(p.read_text() + "\n", encoding="utf-8")
            elif caso == "plano":
                p = d / "PLANO-EDICAO.md"
                p.write_text(p.read_text() + "mudou\n", encoding="utf-8")
            elif caso == "render":
                with (d / "v1-montado.mp4").open("ab") as fh:
                    fh.write(b"-mudou")
            else:
                p = d / "edl.json"
                edl = json.loads(p.read_text())
                edl["timeline_real"]["gerado_em"] = "depois"
                _json(p, edl)
            r, obj = _run(d, "--validar", "planejamento")
            _exigir(r.returncode != 0 and esperado in _codigos(obj),
                    "%s: %s" % (caso, obj))


def caso_preparar_mais_render_externo_nao_comprova_remotion():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        evento = _evento(artefato="partitura.json")
        evento["implementacao"]["ref"] = {"tipo": "json-pointer",
                                             "valor": "/itens/0"}
        plano["eventos"] = [evento]
        _salvar_plano(d, plano)
        _json(d / "partitura.json", {
            "contrato": "benchmark.partitura/v1",
            "_procedencia": {
                "tema": None,
                "perfil": {"video": {"largura": 64, "altura": 64, "fps": 10}},
                "orcamento": {"duracao_s": 2.1},
            },
            "itens": [{"id": "visual-001", "componente": "HandText"}],
        })
        preparar = subprocess.run(
            [sys.executable, str(COMPILADOR), str(d), "preparar", "--json"],
            text=True, capture_output=True,
        )
        _exigir(preparar.returncode == 0, preparar.stdout or preparar.stderr)
        render = d / "render-externo.mov"
        _gerar_render_sintetico(render)
        _json(d / "partitura.json", {"contrato": "benchmark.partitura/v1", "itens": [{
            "contrato": "benchmark.evento-visual-aplicado/v1",
            "evento_id": evento["id"],
            "inicio_s": evento["inicio_s"],
            "fim_s": evento["fim_s"],
            "visual_tipo": evento["visual"]["tipo"],
            "camada": "grafismo",
            "plano_sha256": _sha256(d / "plano-visual.json"),
            "render": {"arquivo": render.name, "sha256": _sha256(render)},
        }]})
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "RENDER-REMOTION-AUSENTE" in _codigos(obj), obj)


def caso_asset_publico_alterado_depois_do_render_reprova_gate():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        plano["eventos"] = [_evento(som={
            "decisao": "usar", "asset": "pop-hi.wav", "at_s": 0.7,
            "ganho_db": -8.0,
        })]
        _aplicar_prova(d, plano)
        assets = [p for p in (d / "remotion" / "public").rglob("*") if p.is_file()]
        _exigir(len(assets) == 1, assets)
        assets[0].write_bytes(b"asset-trocado-depois-do-render")
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "STALE-PUBLIC-TREE" in _codigos(obj), obj)


def caso_dois_finais_oficiais_passam_e_terceiro_externo_falha():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        _gerar_base_com_audio(d / "v1-montado.mp4")
        plano = _iniciar(d)
        plano["eventos"] = [_evento(som={
            "decisao": "usar", "asset": "pop-hi.wav", "at_s": 0.7,
            "ganho_db": -8.0,
        })]
        _aplicar_prova(d, plano)

        # Repro do bypass: final válido que copia apenas a base, sem overlay e
        # sem o áudio do MOV gráfico. A mera existência do MP4 não pode passar.
        final = d / "v-final.mp4"
        externo = subprocess.run([
            shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y",
            "-i", str(d / "v1-montado.mp4"), "-map", "0:v", "-map", "0:a",
            "-c", "copy", str(final),
        ], text=True, capture_output=True)
        _exigir(externo.returncode == 0, externo.stderr)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "FINAL-VISUAL-SEM-PROVENIENCIA" in _codigos(obj), obj)

        final.unlink()
        compor = subprocess.run([
            sys.executable, str(COMPILADOR), str(d), "compor-final",
            "--base", "v1-montado.mp4", "--saida", final.name, "--json",
        ], text=True, capture_output=True)
        _exigir(compor.returncode == 0, compor.stdout or compor.stderr)
        resultado_compor = json.loads(compor.stdout)
        manifesto = json.loads(Path(resultado_compor["manifesto_final"]).read_text())
        _exigir(manifesto["sfx_esperado"] is True
                and manifesto["audio_grafico_misturado"] is True
                and manifesto["comando"]["audio"]
                == "amix:normalize=0:duration=first", manifesto)

        # O perfil Reels prevê as duas saídas. A segunda composição não pode
        # sobrescrever a prova da primeira.
        sem_filtro = subprocess.run([
            sys.executable, str(COMPILADOR), str(d), "compor-final",
            "--base", "v1-montado.mp4", "--saida", "v-final-sem-filtro.Mp4",
            "--json",
        ], text=True, capture_output=True)
        _exigir(sem_filtro.returncode == 0,
                sem_filtro.stdout or sem_filtro.stderr)
        manifestos = sorted(
            (d / "remotion" / "plano-visual-finais").glob("*.json"))
        _exigir(len(manifestos) == 2, manifestos)
        _exigir({json.loads(path.read_text())["final"]["arquivo"]
                 for path in manifestos}
                == {"v-final.mp4", "v-final-sem-filtro.Mp4"}, manifestos)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode == 0 and obj["veredito"] == "aprovado", obj)

        # O universo continua estrito: nome genérico, truque fullwidth e final
        # enterrado em subdiretório não viram entregáveis oficiais por acidente.
        shutil.copyfile(final, d / "entrega.Mp4")
        shutil.copyfile(final, d / "ｖ-final.MP4")
        (d / "entregas").mkdir()
        shutil.copyfile(final, d / "entregas" / "v-final.mp4")
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode == 0 and obj["veredito"] == "aprovado", obj)

        irregular = d / "v-final-IRREGULAR.MP4"
        irregular.mkdir()
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "FINAL-VISUAL-CAMINHO-INVALIDO" in _codigos(obj), obj)
        irregular.rmdir()

        if hasattr(os, "mkfifo"):
            fifo = d / "v-final-PIPE.MP4"
            os.mkfifo(fifo)
            r, obj = _run(d, "--validar", "entrega")
            _exigir(r.returncode != 0
                    and "FINAL-VISUAL-CAMINHO-INVALIDO" in _codigos(obj), obj)
            fifo.unlink()

        # Nem o diretório canônico nem `remotion/`, seu pai, podem atravessar
        # symlink. Aqui o alvo externo contém cópias válidas dos manifestos para
        # provar que não basta o conteúdo bater.
        manifestos_dir = d / "remotion" / "plano-visual-finais"
        manifestos_guardados = d / "remotion" / "plano-visual-finais.guardado"
        manifestos_dir.rename(manifestos_guardados)
        fora = Path(td) / "manifestos-fora"
        shutil.copytree(manifestos_guardados, fora)
        manifestos_dir.symlink_to(fora, target_is_directory=True)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "FINAL-VISUAL-CAMINHO-INVALIDO" in _codigos(obj), obj)
        manifestos_dir.unlink()
        manifestos_guardados.rename(manifestos_dir)

        remotion_dir = d / "remotion"
        remotion_guardado = d / "remotion.guardado"
        remotion_dir.rename(remotion_guardado)
        remotion_fora = Path(td) / "remotion-fora"
        shutil.copytree(remotion_guardado, remotion_fora)
        remotion_dir.symlink_to(remotion_fora, target_is_directory=True)
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "FINAL-VISUAL-CAMINHO-INVALIDO" in _codigos(obj), obj)
        remotion_dir.unlink()
        remotion_guardado.rename(remotion_dir)

        # Uma terceira saída reconhecida, criada fora do compositor, não pode se
        # esconder atrás dos dois manifestos legítimos.
        shutil.copyfile(final, d / "v-final-COPIA.MP4")
        r, obj = _run(d, "--validar", "entrega")
        _exigir(r.returncode != 0
                and "FINAL-VISUAL-SEM-PROVENIENCIA" in _codigos(obj), obj)


def caso_erro_ao_listar_raiz_reprova_em_vez_de_sumir_com_finais():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td).resolve()
        falhas = GATE.Falhas()

        def negar(_raiz):
            raise PermissionError(13, "permissão negada")

        finais = GATE._finais_atuais(d, falhas, listar=negar)
        _exigir(finais == [], finais)
        _exigir({item["codigo"] for item in falhas.itens}
                == {"FINAL-VISUAL-VARREDURA-INVALIDA"}, falhas.itens)


def caso_tempos_fora_da_timeline_reprovam():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        plano = _iniciar(d)
        plano["eventos"] = [_evento(fim=10.1)]
        _salvar_plano(d, plano)
        r, obj = _run(d, "--validar", "planejamento")
        _exigir(r.returncode != 0 and "TEMPO-FORA-TIMELINE" in _codigos(obj), obj)


def caso_fase_2_exige_plano_valido():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), modo="essencial", sfx="sem-sfx")
        sem = subprocess.run([sys.executable, str(ESTADO), str(d), "--fase", "2"],
                             text=True, capture_output=True)
        _exigir(sem.returncode != 0 and "plano visual inválido" in sem.stderr,
                sem.stderr or sem.stdout)
        _iniciar(d)
        com = subprocess.run([sys.executable, str(ESTADO), str(d), "--fase", "2"],
                             text=True, capture_output=True)
        _exigir(com.returncode == 0, com.stderr or com.stdout)


def _fixture_release_harness(base: Path, versao="9.9") -> Path:
    """Monta uma arvore completa aceita pelos dois validadores oficiais."""
    raiz = base / "release"
    major, minor = (int(item) for item in versao.split("."))
    anterior = "%d.%d" % (major, minor - 1)
    plugin_version = versao + ".0"
    _json(raiz / ".codex-plugin" / "plugin.json", {
        "name": "ilha", "version": plugin_version,
    })
    (raiz / "README.md").write_text("# Ilha\n", encoding="utf-8")
    (raiz / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v%s\n\nAtual.\n\n## v%s\n\nAnterior.\n" %
        (versao, anterior),
        encoding="utf-8",
    )
    canonico = raiz / ".claude" / "skills" / "demo"
    canonico.mkdir(parents=True)
    (canonico / "contrato.txt").write_text("alias identico\n", encoding="utf-8")
    shutil.copytree(raiz / ".claude" / "skills", raiz / "skills",
                    copy_function=shutil.copy2)
    _json(raiz / "tools" / "pacote" / "MANIFESTO.json", {
        "schema": "benchmark.pacote/v1",
        "produto": "ilha-de-edicao",
        "versao_manifesto": 1,
        "raiz": {},
        "ativos": {},
        "chaves": {},
        "plataformas": {},
        "_reduzido_pelo_export": (
            VALIDACAO_RELEASE.MARCADOR_MANIFESTO_REDUZIDO),
    })
    shutil.copy2(VALIDADOR_RELEASE,
                 raiz / "tools" / "pacote" / "release-validacao.py")
    arvore, arquivos, bytes_total = VALIDACAO_RELEASE.resumo_arvore(
        raiz, excluir={"RELEASE.json"})
    recibo = {
        "schema": "ilha.release/v1",
        "version": versao,
        "plugin_version": plugin_version,
        "artifact": "ILHA-v%s.zip" % versao,
        "source": {"repo": "benchmark-system/ilha", "head": "0" * 40,
                   "dirty": False},
        "payload": {"tree_sha256": arvore, "files": arquivos,
                    "bytes": bytes_total,
                    "hash_excludes": ["RELEASE.json"]},
        "validation": {
            "source_gate": "scripts/verificar.sh",
            "plugin_validator": ["source", "staging", "extraction"],
            "exported_test_gate": {
                "pattern": "test_*.py",
                "coverage": "all distributed tests, semantic aliases once",
                "order": "lexicographic",
            },
            "export_smoke_tests": list(
                VALIDACAO_RELEASE.SMOKES_EXPORTADOS),
        },
        "generated_by": "/".join(("tools", "pacote", "criar-release.py")),
    }
    _json(raiz / "RELEASE.json", recibo)
    return raiz


def _exigir_ambiente_invalido(raiz: Path, trecho: str) -> None:
    try:
        modo = _modo_render_harness(raiz)
    except AssertionError as exc:
        _exigir(trecho in str(exc), str(exc))
        return
    raise AssertionError("ambiente invalido caiu em %s: %s" % (modo, raiz))


def _regressoes_classificacao_harness() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        valido = _fixture_release_harness(base / "valido")
        _exigir(_modo_render_harness(valido) == "contrato-sem-deps",
                "release oficial valida nao habilitou contrato-sem-deps")

        sem_release = _fixture_release_harness(base / "sem-release")
        (sem_release / "RELEASE.json").unlink()
        _exigir_ambiente_invalido(sem_release, "RELEASE.json ausente")

        malformado = _fixture_release_harness(base / "malformado")
        (malformado / "RELEASE.json").write_text("{", encoding="utf-8")
        _exigir_ambiente_invalido(malformado, "RELEASE.json invalido")

        incoerente = _fixture_release_harness(base / "incoerente")
        recibo = json.loads((incoerente / "RELEASE.json").read_text(
            encoding="utf-8"))
        recibo["plugin_version"] = "9.8.0"
        _json(incoerente / "RELEASE.json", recibo)
        _exigir_ambiente_invalido(incoerente, "versao de plugin divergente")

        plugin_nome = _fixture_release_harness(base / "plugin-nome")
        plugin_path = plugin_nome / ".codex-plugin" / "plugin.json"
        plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
        plugin["name"] = "outro-plugin"
        _json(plugin_path, plugin)
        _exigir_ambiente_invalido(plugin_nome, "nome do plugin divergente")

        pre_formal = _fixture_release_harness(base / "pre-formal", "0.14")
        _exigir_ambiente_invalido(pre_formal, "serie formal comeca em v0.15")

        sem_source = _fixture_release_harness(base / "sem-source")
        recibo_path = sem_source / "RELEASE.json"
        recibo = json.loads(recibo_path.read_text(encoding="utf-8"))
        recibo.pop("source")
        _json(recibo_path, recibo)
        _exigir_ambiente_invalido(sem_source, "source ausente ou invalido")

        sem_validation = _fixture_release_harness(base / "sem-validation")
        recibo_path = sem_validation / "RELEASE.json"
        recibo = json.loads(recibo_path.read_text(encoding="utf-8"))
        recibo.pop("validation")
        _json(recibo_path, recibo)
        _exigir_ambiente_invalido(
            sem_validation, "validation ausente ou divergente")

        sem_readme = _fixture_release_harness(base / "sem-readme")
        (sem_readme / "README.md").unlink()
        _exigir_ambiente_invalido(
            sem_readme, "arquivo obrigatorio fora da raiz do ZIP: README.md")

        changelog_ruim = _fixture_release_harness(base / "changelog-ruim")
        (changelog_ruim / "CHANGELOG.md").write_text(
            "# Changelog\n\n## v9.8\n\nVersao errada.\n", encoding="utf-8")
        _exigir_ambiente_invalido(
            changelog_ruim, "release mais recente do CHANGELOG")

        alias_divergente = _fixture_release_harness(base / "alias-divergente")
        (alias_divergente / "skills" / "demo" / "contrato.txt").write_text(
            "mudou\n", encoding="utf-8")
        _exigir_ambiente_invalido(alias_divergente, "aliases divergentes")

        sem_manifesto = _fixture_release_harness(base / "sem-manifesto")
        (sem_manifesto / "tools" / "pacote" / "MANIFESTO.json").unlink()
        _exigir_ambiente_invalido(sem_manifesto, "MANIFESTO reduzido ausente")

        marcador = _fixture_release_harness(base / "marcador")
        manifesto_path = marcador / "tools" / "pacote" / "MANIFESTO.json"
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
        manifesto["_reduzido_pelo_export"] = "x"
        _json(manifesto_path, manifesto)
        _exigir_ambiente_invalido(
            marcador, "MANIFESTO reduzido tem identidade invalida")

        whitelist = _fixture_release_harness(base / "whitelist")
        manifesto_path = whitelist / "tools" / "pacote" / "MANIFESTO.json"
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
        manifesto["export"] = {}
        _json(manifesto_path, manifesto)
        _exigir_ambiente_invalido(
            whitelist, "whitelist do MANIFESTO reduzido diverge")

        vazio = _fixture_release_harness(base / "node-vazio")
        (vazio / "tools" / "remotion-compositor" /
         "node_modules").mkdir(parents=True)
        _exigir_ambiente_invalido(vazio, ".bin/remotion esta ausente")

        quebrado = _fixture_release_harness(base / "bin-quebrado")
        binario = (quebrado / "tools" / "remotion-compositor" /
                   "node_modules" / ".bin" / "remotion")
        binario.parent.mkdir(parents=True)
        binario.symlink_to("../nao-existe/remotion")
        _exigir_ambiente_invalido(quebrado, "quebrado ou nao e arquivo regular")

        sem_execucao = _fixture_release_harness(base / "bin-sem-execucao")
        binario = (sem_execucao / "tools" / "remotion-compositor" /
                   "node_modules" / ".bin" / "remotion")
        binario.parent.mkdir(parents=True)
        binario.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binario.chmod(0o644)
        _exigir_ambiente_invalido(sem_execucao, "nao e executavel")


def caso_harness_separa_remotion_real_de_contrato_extraido():
    real = _RENDERS_HARNESS["dinamico-remotion"]
    controlado = _RENDERS_HARNESS["contrato-sem-deps"]
    modo = _modo_render_harness()
    if modo == "dinamico-remotion":
        _exigir(real == 3,
                "fonte com Remotion não executou os 3 renders dinâmicos")
        _exigir(controlado == 0,
                "fonte com node_modules caiu no executor controlado")
    else:
        _exigir(controlado == 3,
                "release sem deps não exercitou os 3 renders de contrato")
        _exigir(real == 0,
                "pacote sem node_modules declarou render Remotion dinâmico")
    _regressoes_classificacao_harness()


CASOS = (
    caso_essencial_zero_eventos_e_sem_sfx_passa,
    caso_iniciar_nao_sobrescreve_e_nao_deixa_parcial,
    caso_captions_only_renomeado_passa_planejamento_mas_falha_entrega,
    caso_sfx_ausente_so_reprova_gate_entrega,
    caso_silencio_intencional_justificado_passa_entrega,
    caso_surpresa_exige_e_preserva_direcao_resolvida,
    caso_stale_em_qualquer_binding_e_detectado,
    caso_preparar_mais_render_externo_nao_comprova_remotion,
    caso_asset_publico_alterado_depois_do_render_reprova_gate,
    caso_dois_finais_oficiais_passam_e_terceiro_externo_falha,
    caso_erro_ao_listar_raiz_reprova_em_vez_de_sumir_com_finais,
    caso_tempos_fora_da_timeline_reprovam,
    caso_fase_2_exige_plano_valido,
    caso_harness_separa_remotion_real_de_contrato_extraido,
)


def main() -> int:
    falhas = 0
    for caso in CASOS:
        nome = caso.__name__.removeprefix("caso_")
        try:
            caso()
            print("ok  %s" % nome)
        except Exception as exc:  # o harness precisa mostrar todos os dentes
            falhas += 1
            print("FALHA  %s: %s" % (nome, exc), file=sys.stderr)
    try:
        modo = _modo_render_harness()
        detalhe = "%d execução(ões)" % _RENDERS_HARNESS[modo]
    except AssertionError as exc:
        modo = "ambiente-invalido"
        detalhe = str(exc)
    print("\nprova de render: %s (%s)" % (modo, detalhe))
    print("%d/%d casos aprovados" % (len(CASOS) - falhas, len(CASOS)))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
