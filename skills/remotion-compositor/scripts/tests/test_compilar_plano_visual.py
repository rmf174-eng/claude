#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão standalone do consumidor Remotion de plano-visual.json."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "compilar-plano-visual.py"
RAIZ_ILHA = Path(__file__).resolve().parents[4]
DATA_CANONICO = RAIZ_ILHA / "tools" / "remotion-compositor" / "src" / "data" / "partitura.json"
SPEC = importlib.util.spec_from_file_location("compilar_plano_visual", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def _json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _producao(base: Path, *, politica="automatico", decisao="usar",
              mini=False) -> Path:
    d = base / "producao"
    d.mkdir()
    item = {
        "id": "tipografia-001",
        "papel": "gancho",
        "componente": "AccentWord",
        "canal": "tipografia",
        "texto": "Teste",
        "inS": 9.0,
        "outS": 9.8,
        "zona": "topo",
        "cor": "accent",
        "score": 1.0,
        # Dado legado plantado. O componente real nunca pode consumi-lo.
        "sfx": "palpite-do-diretor",
    }
    _json(d / "partitura.json", {
        "contrato": "benchmark.partitura/v1",
        "_procedencia": {
            "tema": None,
            "perfil": {"video": {"largura": 64 if mini else 1080,
                                    "altura": 64 if mini else 1920,
                                    "fps": 10 if mini else 30}},
            "orcamento": {"duracao_s": 0.2 if mini else 3.0},
        },
        "itens": [item],
    })
    som = ({
        "decisao": "usar",
        "asset": "audio/ping.wav",
        "at_s": 0.05 if mini else 1.3,
        "ganho_db": -6.0,
    } if decisao == "usar" else {
        "decisao": "silencio-intencional",
        "motivo": "a fala já tem ataque suficiente",
    })
    _json(d / "plano-visual.json", {
        "contrato": "benchmark.plano-visual/v1",
        "direcao_edicao": {
            "modo": "animada",
            "densidade": "equilibrada",
            "sfx": politica,
        },
        "eventos": [{
            "id": "gancho-001",
            "inicio_s": 0.0 if mini else 1.0,
            "fim_s": 0.2 if mini else 2.0,
            "beat": "gancho",
            "visual": {"tipo": "tipografia", "descricao": "palavra entra"},
            "zona": "topo",
            "som": som,
            "implementacao": {
                "artefato": "partitura.json",
                "ref": {"tipo": "json-pointer", "valor": "/itens/0"},
            },
        }],
    })
    if decisao == "usar":
        (d / "audio").mkdir()
        (d / "audio" / "ping.wav").write_bytes(b"wav-fixture-do-plano")
    return d


def _run(d: Path, *args: str):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(d), *args, "--json"],
        text=True,
        capture_output=True,
    )
    try:
        obj = json.loads(r.stdout)
    except ValueError as exc:
        raise AssertionError("stdout não é JSON:\n%s\nstderr:\n%s" %
                             (r.stdout, r.stderr)) from exc
    return r, obj


def _render(d: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg é necessário para a fixture de render")
    out = d / "graphics-alpha.mp4"
    r = subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=16x16:d=0.2", "-an", "-c:v", "mpeg4", "-q:v", "5",
        str(out),
    ], text=True, capture_output=True)
    if r.returncode != 0:
        raise AssertionError("ffmpeg falhou: %s" % r.stderr)
    return out


def _base_com_audio(d: Path, nome="v1-montado.mp4") -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg é necessário para a fixture com áudio")
    out = d / nome
    r = subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=0.2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.2",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(out),
    ], text=True, capture_output=True)
    if r.returncode != 0:
        raise AssertionError("ffmpeg base falhou: %s" % r.stderr)
    return out


def _wav_sfx(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg é necessário para a fixture SFX")
    r = subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "sine=frequency=1000:sample_rate=48000:duration=0.08",
        "-c:a", "pcm_s16le", str(path),
    ], text=True, capture_output=True)
    if r.returncode != 0:
        raise AssertionError("ffmpeg SFX falhou: %s" % r.stderr)


def _executor_fake(comandos: list[list[str]]):
    def executar(cmd: list[str]):
        comandos.append(cmd)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise AssertionError("ffmpeg é necessário para o fake controlado")
        out = Path(cmd[4])
        r = subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=16x16:d=0.2", "-an", "-c:v", "mpeg4", "-q:v", "5",
            str(out),
        ], text=True, capture_output=True)
        return subprocess.CompletedProcess(cmd, r.returncode, r.stdout, r.stderr)
    return executar


def _comando_fake(compilado: Path, public_dir: Path, parcial: Path) -> list[str]:
    return [
        "remotion-controlado", "render", "src/index-partitura.tsx", "Graphics",
        str(parcial), "--props=%s" % compilado, "--public-dir=%s" % public_dir,
        "--codec=prores", "--prores-profile=4444", "--image-format=png",
        "--pixel-format=yuva444p10le", "--overwrite",
    ]


def _exigir(condicao, mensagem) -> None:
    if not condicao:
        raise AssertionError(mensagem)


def caso_preparar_materializa_plano_sem_tocar_fonte_ou_tools():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        fonte_antes = (d / "partitura.json").read_bytes()
        canonico_antes = DATA_CANONICO.read_bytes() if DATA_CANONICO.is_file() else None
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        destino = d / "remotion" / "partitura-compilada.json"
        _exigir(Path(obj["saida"]).resolve() == destino.resolve(), obj)
        _exigir((d / "partitura.json").read_bytes() == fonte_antes,
                "preparar sobrescreveu a partitura fonte")
        if canonico_antes is not None:
            _exigir(DATA_CANONICO.read_bytes() == canonico_antes,
                    "preparar alterou src/data/partitura.json do compositor")
        compilado = json.loads(destino.read_text(encoding="utf-8"))
        evento = compilado["plano_visual"]["eventos"][0]
        _exigir(evento["som"]["asset_publico"].startswith("sfx/ping-"), evento)
        asset = d / "remotion" / "public" / evento["som"]["asset_publico"]
        _exigir(asset.read_bytes() == b"wav-fixture-do-plano", asset)
        preparo = json.loads(
            (d / "remotion" / "plano-visual-preparado.json").read_text())
        arvore = preparo["public_tree"]
        _exigir(arvore["contrato"] == "benchmark.remotion-public-tree/v1",
                arvore)
        _exigir(arvore["raiz"] == "remotion/public"
                and arvore["total_arquivos"] == 1
                and arvore["total_bytes"] == len(b"wav-fixture-do-plano"),
                arvore)
        _exigir(arvore["arquivos"] == [{
            "caminho": evento["som"]["asset_publico"],
            "bytes": len(b"wav-fixture-do-plano"),
            "sha256": _sha(asset),
        }], arvore)
        _exigir(compilado["itens"][0]["plano_visual_evento_id"] == "gancho-001",
                compilado["itens"][0])
        _exigir(compilado["itens"][0]["sfx"] == "palpite-do-diretor",
                "fixture perdeu o controle negativo do SFX legado")


def caso_caminhos_relativos_sao_da_producao_e_escape_falha():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = _producao(base)
        r, obj = _run(d, "preparar", "--destino", "remotion/custom.json",
                      "--public-dir", "remotion/assets")
        _exigir(r.returncode == 0, obj)
        _exigir((d / "remotion" / "custom.json").is_file(), obj)
        _exigir((d / "remotion" / "assets" / "sfx").is_dir(), obj)

        fora = base / "fora.json"
        r, obj = _run(d, "preparar", "--destino", "../fora.json")
        _exigir(r.returncode != 0 and "dentro da produção" in obj["erro"], obj)
        _exigir(not fora.exists(), "escape de --destino escreveu fora da produção")


def caso_renderizar_exige_preparo_e_grava_recibo_ligado_ao_plano():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        r, obj = _run(d, "renderizar", "--saida", "graphics-alpha.mov")
        _exigir(r.returncode != 0 and "preparar" in obj["erro"], obj)

        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        comandos = []
        obj = MOD.renderizar(d.resolve(), "graphics-alpha.mov",
                             executor=_executor_fake(comandos),
                             construir_comando=_comando_fake)
        _exigir(obj["veredito"] == "renderizado", obj)
        _exigir(len(comandos) == 1, comandos)
        comando = comandos[0]
        _exigir("src/index-partitura.tsx" in comando and "Graphics" in comando,
                comando)
        _exigir("--props=%s" % (d / "remotion" / "partitura-compilada.json").resolve()
                in comando, comando)
        _exigir("--public-dir=%s" % (d / "remotion" / "public").resolve()
                in comando, comando)
        render = d / "graphics-alpha.mov"
        alvo = json.loads((d / "partitura.json").read_text())["itens"][0]
        _exigir(alvo["contrato"] == "benchmark.evento-visual-aplicado/v1", alvo)
        _exigir(alvo["evento_id"] == "gancho-001" and alvo["inicio_s"] == 1.0,
                alvo)
        _exigir(alvo["render"] == {"arquivo": render.name, "sha256": _sha(render)},
                alvo)
        _exigir(alvo["plano_sha256"] == _sha(d / "plano-visual.json"), alvo)
        manifesto = json.loads((d / "remotion" / "plano-visual-render.json").read_text())
        _exigir(manifesto["contrato"] == "benchmark.remotion-plano-visual-render/v1",
                manifesto)
        _exigir(manifesto["remotion_executado"] is True and manifesto["exit"] == 0,
                manifesto)
        _exigir(manifesto["render"] == alvo["render"], manifesto)
        preparo = json.loads(
            (d / "remotion" / "plano-visual-preparado.json").read_text())
        _exigir(manifesto["public_tree"] == preparo["public_tree"], manifesto)


def caso_public_tree_alterado_adicionado_ou_removido_bloqueia_antes_do_render():
    mutacoes = {
        "alterado": lambda public, asset: asset.write_bytes(b"asset-300-hz"),
        "adicionado": lambda public, asset: (public / "intruso.wav").write_bytes(
            b"nao-estava-no-preparo"),
        "removido": lambda public, asset: asset.unlink(),
    }
    for rotulo, mutar in mutacoes.items():
        with tempfile.TemporaryDirectory() as td:
            d = _producao(Path(td))
            r, obj = _run(d, "preparar")
            _exigir(r.returncode == 0, obj)
            public = d / "remotion" / "public"
            asset = next((public / "sfx").iterdir())
            mutar(public, asset)
            executou = []

            def nao_deve_executar(cmd):
                executou.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            try:
                MOD.renderizar(d.resolve(), "graphics-alpha.mov",
                               executor=nao_deve_executar,
                               construir_comando=_comando_fake)
            except MOD.ErroCompilacao as exc:
                _exigir("assets de public_dir mudaram" in str(exc),
                        "%s: %s" % (rotulo, exc))
            else:
                raise AssertionError("asset %s depois do preparo foi aceito" % rotulo)
            _exigir(not executou,
                    "%s: Remotion executou com árvore pública stale" % rotulo)
            _exigir(not (d / "remotion" / "plano-visual-render.json").exists(),
                    "%s: mutação publicou manifesto render" % rotulo)


def caso_public_tree_mudando_durante_render_descarta_parcial_e_preserva_saida():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td))
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        public = d / "remotion" / "public"
        asset = next((public / "sfx").iterdir())
        saida = d / "graphics-alpha.mov"
        anterior = b"render-anterior-intocado"
        saida.write_bytes(anterior)
        executar_fake = _executor_fake([])

        def mutar_durante(cmd):
            proc = executar_fake(cmd)
            asset.write_bytes(b"asset-trocado-durante-render")
            return proc

        try:
            MOD.renderizar(d.resolve(), saida.name, executor=mutar_durante,
                           construir_comando=_comando_fake)
        except MOD.ErroCompilacao as exc:
            _exigir("mudaram durante o render" in str(exc), exc)
        else:
            raise AssertionError("mutação durante o render foi aceita")
        _exigir(saida.read_bytes() == anterior,
                "mutação de asset sobrescreveu a saída anterior")
        _exigir(not list(d.glob(".*.parcial.mov")), "sobrou render parcial")
        _exigir(not (d / "remotion" / "plano-visual-render.json").exists(),
                "mutação durante render publicou manifesto")


def caso_plano_alterado_depois_do_preparo_nao_recebe_prova():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), decisao="silencio")
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        plano = json.loads((d / "plano-visual.json").read_text())
        plano["eventos"][0]["som"]["motivo"] = "decisão mudou depois do bundle"
        _json(d / "plano-visual.json", plano)
        r, obj = _run(d, "renderizar", "--saida", "graphics-alpha.mov")
        _exigir(r.returncode != 0 and "mudou depois de `preparar`" in obj["erro"], obj)
        fonte = json.loads((d / "partitura.json").read_text())
        _exigir("contrato" not in fonte["itens"][0],
                "stale publicou recibo na fonte")


def caso_mp4_arbitrario_nao_tem_subcomando_para_fabricar_recibo():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), decisao="silencio")
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        video = _render(d)
        r = subprocess.run([
            sys.executable, str(SCRIPT), str(d), "registrar-entrega",
            "--render", video.name,
        ], text=True, capture_output=True)
        _exigir(r.returncode == 2 and "invalid choice" in r.stderr, r.stderr)
        fonte = json.loads((d / "partitura.json").read_text())
        _exigir("contrato" not in fonte["itens"][0],
                "MP4 arbitrário fabricou recibo")
        _exigir(not (d / "remotion" / "plano-visual-render.json").exists(),
                "MP4 arbitrário fabricou manifesto Remotion")


def caso_falha_remotion_preserva_saida_anterior():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), decisao="silencio")
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        saida = d / "graphics-alpha.mov"
        anterior = b"entrega-anterior-intocada"
        saida.write_bytes(anterior)

        def falhar(cmd):
            return subprocess.CompletedProcess(cmd, 7, "", "falha plantada")

        try:
            MOD.renderizar(d.resolve(), saida.name, executor=falhar,
                           construir_comando=_comando_fake)
        except MOD.ErroCompilacao as exc:
            _exigir("exit 7" in str(exc), exc)
        else:
            raise AssertionError("falha plantada foi aceita")
        _exigir(saida.read_bytes() == anterior,
                "falha do Remotion sobrescreveu a saída anterior")
        _exigir(not list(d.glob(".*.parcial.mov")), "sobrou render parcial")
        _exigir(not (d / "remotion" / "plano-visual-render.json").exists(),
                "falha publicou manifesto de sucesso")


def caso_comando_final_mistura_sfx_e_sem_sfx_preserva_base():
    cmd_mix = MOD._comando_ffmpeg_final(
        Path("base.mp4"), Path("graphics.mov"), Path("final.mp4"), True)
    texto_mix = " ".join(cmd_mix)
    _exigir("unpremultiply=inplace=1" in texto_mix and "overlay=0:0" in texto_mix,
            cmd_mix)
    _exigir("amix=inputs=2:duration=first:normalize=0" in texto_mix,
            cmd_mix)
    _exigir("[a]" in cmd_mix and "0:a?" not in cmd_mix, cmd_mix)

    cmd_base = MOD._comando_ffmpeg_final(
        Path("base.mp4"), Path("graphics.mov"), Path("final.mp4"), False)
    texto_base = " ".join(cmd_base)
    _exigir("unpremultiply=inplace=1" in texto_base and "overlay=0:0" in texto_base,
            cmd_base)
    _exigir("amix=" not in texto_base and "0:a?" in cmd_base, cmd_base)


def caso_integracao_remotion_real_quando_instalado():
    binario = RAIZ_ILHA / "tools" / "remotion-compositor" / "node_modules" / ".bin" / "remotion"
    if not binario.is_file():
        print("skip - integração Remotion: node_modules ausente")
        return
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), decisao="usar", mini=True)
        _wav_sfx(d / "audio" / "ping.wav")
        base = _base_com_audio(d)
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0, obj)
        r, obj = _run(d, "renderizar", "--saida", "remotion/integracao.mov")
        _exigir(r.returncode == 0 and obj["veredito"] == "renderizado", obj)
        _exigir((d / "remotion" / "integracao.mov").stat().st_size > 0, obj)
        r, obj = _run(d, "compor-final", "--base", base.name,
                      "--saida", "v-final.mp4")
        _exigir(r.returncode == 0 and obj["veredito"] == "composto", obj)
        _exigir(obj["audio_grafico_misturado"] is True, obj)
        manifesto_path = Path(obj["manifesto_final"])
        manifesto = json.loads(manifesto_path.read_text())
        _exigir(manifesto["video_grafico_sobreposto"] is True, manifesto)
        _exigir(manifesto["audio_grafico_misturado"] is True, manifesto)
        _exigir(manifesto["final"]["sha256"] == _sha(d / "v-final.mp4"), manifesto)

        r, segunda = _run(d, "compor-final", "--base", base.name,
                          "--saida", "v-final-sem-filtro.Mp4")
        _exigir(r.returncode == 0 and segunda["veredito"] == "composto", segunda)
        _exigir(segunda["manifesto_final"] != obj["manifesto_final"], segunda)
        manifestos = sorted((d / "remotion" / "plano-visual-finais").glob("*.json"))
        _exigir(len(manifestos) == 2, manifestos)
        finais = {
            json.loads(path.read_text())["final"]["arquivo"]
            for path in manifestos
        }
        _exigir(finais == {"v-final.mp4", "v-final-sem-filtro.Mp4"}, finais)


def caso_sem_sfx_e_silencio_compila_mas_uso_e_asset_ausente_falham():
    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), politica="sem-sfx", decisao="silencio")
        r, obj = _run(d, "preparar")
        _exigir(r.returncode == 0 and not obj["assets_copiados"], obj)

    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), politica="sem-sfx", decisao="usar")
        r, obj = _run(d, "preparar")
        _exigir(r.returncode != 0 and "usa SFX" in obj["erro"], obj)

    with tempfile.TemporaryDirectory() as td:
        d = _producao(Path(td), politica="automatico", decisao="usar")
        (d / "audio" / "ping.wav").unlink()
        r, obj = _run(d, "preparar")
        _exigir(r.returncode != 0 and "asset SFX não existe" in obj["erro"], obj)


def caso_ref_duplicada_e_symlink_sfx_para_fora_falham():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = _producao(base, decisao="silencio")
        plano = json.loads((d / "plano-visual.json").read_text())
        segundo = json.loads(json.dumps(plano["eventos"][0]))
        segundo["id"] = "gancho-002"
        plano["eventos"].append(segundo)
        _json(d / "plano-visual.json", plano)
        r, obj = _run(d, "preparar")
        _exigir(r.returncode != 0 and "repete uma implementação" in obj["erro"], obj)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = _producao(base)
        fora = base / "segredo.wav"
        fora.write_bytes(b"fora-da-producao")
        (d / "audio" / "ping.wav").unlink()
        (d / "audio" / "ping.wav").symlink_to(fora)
        r, obj = _run(d, "preparar")
        _exigir(r.returncode != 0 and "asset SFX não existe" in obj["erro"], obj)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = _producao(base)
        fora = base / "public-fora"
        fora.mkdir()
        public = d / "remotion" / "public"
        public.mkdir(parents=True)
        (public / "sfx").symlink_to(fora, target_is_directory=True)
        r, obj = _run(d, "preparar")
        _exigir(r.returncode != 0 and "public_dir não aceita symlink" in obj["erro"],
                obj)
        _exigir(not list(fora.iterdir()),
                "preparar escreveu através de symlink em public_dir")


def caso_saida_casefold_colidente_e_manifestos_distintos():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td).resolve()
        _exigir(MOD._resolver_saida_final(d, "v-final-sem-filtro.Mp4")
                == d / "v-final-sem-filtro.Mp4", "extensão mista foi recusada")
        for invalida in ("entregas/v-final.mp4", "ｖ-final.MP4", "entrega.Mp4"):
            try:
                MOD._resolver_saida_final(d, invalida)
            except MOD.ErroCompilacao:
                pass
            else:
                raise AssertionError("saída não oficial foi aceita: %s" % invalida)

        (d / "v-final.mp4").write_bytes(b"final-existente")
        try:
            MOD._recusar_colisao_casefold(d / "V-FINAL.MP4")
        except MOD.ErroCompilacao as exc:
            _exigir("colide por caixa/normalização" in str(exc), exc)
        else:
            raise AssertionError("saída que só difere por casefold foi aceita")

        manifesto_a = MOD._manifesto_final_path(d, "v-final.mp4")
        manifesto_b = MOD._manifesto_final_path(d, "v-final-COPIA.MP4")
        _exigir(manifesto_a != manifesto_b, (manifesto_a, manifesto_b))
        _exigir(manifesto_a.name.casefold() != manifesto_b.name.casefold(),
                "identidades de manifesto colidiram após casefold")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = base / "producao"
        externo = base / "manifestos-fora"
        (d / "remotion").mkdir(parents=True)
        externo.mkdir()
        (d / "remotion" / "plano-visual-finais").symlink_to(
            externo, target_is_directory=True)
        try:
            MOD._diretorio_manifestos_finais(d.resolve(), criar=False)
        except MOD.ErroCompilacao as exc:
            _exigir("não aceita symlink" in str(exc), exc)
        else:
            raise AssertionError("diretório de manifestos symlink foi aceito")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        d = base / "producao"
        d.mkdir()
        externo = base / "remotion-fora"
        externo.mkdir()
        (d / "remotion").symlink_to(externo, target_is_directory=True)
        try:
            MOD._diretorio_manifestos_finais(d.resolve(), criar=False)
        except MOD.ErroCompilacao as exc:
            _exigir("não aceita symlink" in str(exc), exc)
        else:
            raise AssertionError("pai remotion symlink foi aceito")


CASOS = (
    caso_preparar_materializa_plano_sem_tocar_fonte_ou_tools,
    caso_caminhos_relativos_sao_da_producao_e_escape_falha,
    caso_renderizar_exige_preparo_e_grava_recibo_ligado_ao_plano,
    caso_public_tree_alterado_adicionado_ou_removido_bloqueia_antes_do_render,
    caso_public_tree_mudando_durante_render_descarta_parcial_e_preserva_saida,
    caso_plano_alterado_depois_do_preparo_nao_recebe_prova,
    caso_mp4_arbitrario_nao_tem_subcomando_para_fabricar_recibo,
    caso_falha_remotion_preserva_saida_anterior,
    caso_comando_final_mistura_sfx_e_sem_sfx_preserva_base,
    caso_sem_sfx_e_silencio_compila_mas_uso_e_asset_ausente_falham,
    caso_ref_duplicada_e_symlink_sfx_para_fora_falham,
    caso_saida_casefold_colidente_e_manifestos_distintos,
    caso_integracao_remotion_real_quando_instalado,
)


def main() -> int:
    falhas = 0
    for caso in CASOS:
        try:
            caso()
            print("ok - %s" % caso.__name__)
        except Exception as exc:  # noqa: BLE001 - runner standalone
            falhas += 1
            print("FALHOU - %s: %s" % (caso.__name__, exc), file=sys.stderr)
    print("compilador plano visual: %d/%d casos aprovados" %
          (len(CASOS) - falhas, len(CASOS)))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
