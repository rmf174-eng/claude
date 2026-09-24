#!/usr/bin/env python3
"""Bateria da galeria de estilos (SPEC-19).

    python3 skills/edit-video/scripts/tests/test_galeria_estilos.py
    python3 -m pytest skills/edit-video/scripts/tests/test_galeria_estilos.py -q

⚠️ AUTOCONTIDO. **Não há pytest nesta máquina** (`python3.14` do Homebrew, sem o
módulo) — medido em 2026-08-08. Um teste que só roda sob pytest é um teste que
não roda. O shim abaixo implementa o pedaço da API que esta bateria usa
(`approx`, `mark.skipif`, `mark.parametrize`, `tmp_path`, `capsys`); quando o
pytest de verdade existe, ele é usado no lugar e nada muda.

🔴 TODO TESTE VERDE AQUI IMPRIME QUANTO VARREU. Um verificador que varre 0 e sai
0 é indistinguível de um quebrado — e este repo já foi mordido por isso. Os casos
`planta_*` existem pelo mesmo motivo: são defeitos que o validador TEM que
acusar, e um deles é o defeito real que a primeira execução do gerador produziu
(0 estilos oferecidos com o `galeria.json` válido).

Nenhum teste depende de produção nossa: o dir de trabalho é montado em `tmp_path`
com um `perfil.json` sintético. `creators/` pode não existir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

try:                                     # pragma: no cover - depende da máquina
    import pytest
except ImportError:                      # o shim: ver o cabeçalho
    import types

    class _Approx:
        def __init__(self, v, abs=None, rel=None):
            self.v, self.abs, self.rel = v, abs, rel

        def __eq__(self, outro):
            tol = self.abs if self.abs is not None else 1e-6
            return abs(float(outro) - float(self.v)) <= tol

        def __repr__(self):
            return "approx(%r)" % (self.v,)

    class _Skip(Exception):
        pass

    def _skipif(cond, reason=""):
        def deco(fn):
            fn._pular = (bool(cond), reason)
            return fn
        return deco

    def _parametrize(nomes, valores):
        chaves = [x.strip() for x in nomes.split(",")]

        def deco(fn):
            fn._casos = (chaves, list(valores))
            return fn
        return deco

    pytest = types.SimpleNamespace(
        approx=_Approx,
        mark=types.SimpleNamespace(skipif=_skipif, parametrize=_parametrize),
        skip=lambda msg="": (_ for _ in ()).throw(_Skip(msg)),
        _Skip=_Skip,
    )

SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _carregar(nome_arquivo, nome_modulo):
    spec = importlib.util.spec_from_file_location(nome_modulo, SCRIPTS / nome_arquivo)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome_modulo] = mod
    spec.loader.exec_module(mod)
    return mod


pv = _carregar("previews-peca.py", "previews_peca")
ee = _carregar("escolha-estilo.py", "escolha_estilo")

CATALOGO = pv.dir_catalogo() / "catalogo.json"
tem_catalogo = pytest.mark.skipif(
    not CATALOGO.is_file(), reason="catalogo.json ausente (rode a SPEC-15)")


# ───────────────────────────── infraestrutura ─────────────────────────────
def prod_sintetica(tmp_path: Path, nome="reels", w=1080, h=1920, fps=30,
                   com_captions=True) -> Path:
    d = tmp_path / "producao"
    d.mkdir(parents=True, exist_ok=True)
    (d / "perfil.json").write_text(json.dumps({
        "contrato": "benchmark.perfil-peca/v1", "nome": nome,
        "video": {"largura": w, "altura": h, "fps": fps},
        "legenda": {"max_palavras_pagina": 3},
        "zonas_ui": {"topo_pct": 0.151, "fundo_pct": 0.7813, "direita_pct": 0.8556},
    }))
    if com_captions:
        # a página do MEIO é a mais longa de propósito: é ela que o gerador tem
        # que escolher (§3.11, pior caso), e não a primeira nem a mais bonita.
        palavras = (["oi", "ola", "tudo"] +
                    ["extraordinariamente", "incompreensivelmente", "desproporcionais"] +
                    ["fim", "de", "papo"])
        caps = []
        for i, p in enumerate(palavras):
            caps.append({"text": " " + p, "startMs": i * 400, "endMs": i * 400 + 400,
                         "timestampMs": i * 400, "confidence": 1})
        (d / "captions.json").write_text(json.dumps(caps, ensure_ascii=False))
    return d


def galeria_de(tmp_path: Path, **kw) -> dict:
    d = prod_sintetica(tmp_path, **kw)
    caminho = pv.gerar(str(d), sem_render=True)
    return json.loads(Path(caminho).read_text())


# ─────────────────────────────── o contrato ───────────────────────────────
@tem_catalogo
def test_galeria_valida_e_com_vocabulario(tmp_path, capsys):
    g = galeria_de(tmp_path)
    n = sum(len(x["estilos"]) for x in g["grupos"])
    with capsys.disabled():
        print(f"\n  varreu {len(g['grupos'])} grupos / {n} estilos oferecidos")
    assert g["contrato"] == "benchmark.galeria-estilos/v1"
    assert pv.validar_galeria(g) == []
    assert [x["id"] for x in g["grupos"]] == list(pv.ORDEM_GRUPOS)
    # 🔴 O DEFEITO REAL que este teste existe para não deixar voltar: a primeira
    # execução do gerador devolveu 0 estilos (o fallback se chama
    # `reels-fallback` e o catálogo diz `reels`), com o JSON VÁLIDO e a tela
    # vazia. Contrato verde sobre galeria vazia é sucesso silencioso.
    assert n > 0, "galeria válida e VAZIA: é o sucesso silencioso do §7.10"


@tem_catalogo
def test_grupo_sem_opcao_continua_no_json(tmp_path):
    """Grupo vazio NÃO some: é o que faz o vocabulário faltante ser notado."""
    g = galeria_de(tmp_path, nome="screencast")
    assert [x["id"] for x in g["grupos"]] == list(pv.ORDEM_GRUPOS)


@tem_catalogo
def test_um_padrao_por_grupo_unico(tmp_path):
    g = galeria_de(tmp_path)
    for grupo in g["grupos"]:
        if grupo["seletor"] != "unico":
            continue
        marcados = [e["slug"] for e in grupo["estilos"] if e.get("padrao")]
        assert len(marcados) <= 1, (grupo["id"], marcados)


@tem_catalogo
def test_caminhos_relativos_e_sem_symlink(tmp_path):
    d = prod_sintetica(tmp_path)
    pv.gerar(str(d), sem_render=True)
    g = json.loads((d / ".preview/estilos/galeria.json").read_text())
    n = 0
    for grupo in g["grupos"]:
        for e in grupo["estilos"]:
            p = e.get("preview")
            if not p:
                continue
            for campo in ("webm", "poster"):
                v = p[campo]
                assert not v.startswith("/") and ".." not in v, v
                n += 1
    links = [x for x in (d / ".preview").rglob("*") if x.is_symlink()]
    assert links == [], links
    assert n > 0


@tem_catalogo
def test_escala_derivada_do_perfil(tmp_path):
    """Nenhum valor de formato: a escala sai de LARGURA_CARD / largura do perfil.

    Em `reels` (1080) dá 0,3333; em `vsl` (1920) dá 0,1875 — e o código é o
    mesmo. Escrever `--scale=0.3333` seria o `scale=1080:1920` do montar.sh
    num lugar novo."""
    assert pv.LARGURA_CARD / 1080 == pytest.approx(0.3333, abs=1e-4)
    assert pv.LARGURA_CARD / 1920 == pytest.approx(0.1875, abs=1e-4)
    g = galeria_de(tmp_path, nome="vsl", w=1920, h=1080)
    assert (g["perfil"]["largura"], g["perfil"]["altura"]) == (1920, 1080)


def test_pior_caso_e_a_pagina_mais_longa(tmp_path):
    d = prod_sintetica(tmp_path)
    perf = json.loads((d / "perfil.json").read_text())
    t = pv.texto_da_peca(str(d), perf, 3.0)
    assert t["fonte"] == "captions"
    # a página do meio (3 palavras enormes) tem que ganhar da primeira
    assert "extraordinariamente" in t["legenda_frase"], t["legenda_frase"]
    assert t["legenda_chars"] > len("oi ola tudo")


def test_degradacao_honesta_sem_perfil_e_sem_captions(tmp_path, capsys):
    d = tmp_path / "vazia"
    d.mkdir()
    caminho = pv.gerar(str(d), sem_render=True)
    g = json.loads(Path(caminho).read_text())
    with capsys.disabled():
        print("\n  avisos: %d" % len(g["avisos"]))
    assert g["perfil"]["fonte"] == "fallback"
    assert g["texto"]["fonte"] == "amostra"
    assert not any((e.get("preview") or {}).get("nivel") == 1
                   for grupo in g["grupos"] for e in grupo["estilos"])
    assert len(g["avisos"]) >= 2, g["avisos"]


# ───────── GATE §7.7 — acento_usado DERIVADO, sem lista paralela ─────────
def _gal_real(tmp_path) -> dict:
    return galeria_de(tmp_path)


def _slugs_por_grupo(g, gid):
    for grupo in g["grupos"]:
        if grupo["id"] == gid:
            return [e["slug"] for e in grupo["estilos"] if e["estado"] != "candidato"]
    return []


def _pay(**kw):
    base = {"contrato": "benchmark.edit-estilo/v2", "salvo_em": "2026-08-08T23:00:00-03:00",
            "revisao_base": 0, "fonte": "galeria", "rerender": False,
            "grafismos": [], "grafismos_fora": [], "elementos": {}, "parametros": {}}
    base.update(kw)
    return base


@tem_catalogo
def test_gate_acento_derivado_nos_dois_sentidos(tmp_path, capsys):
    g = _gal_real(tmp_path)
    ix = {e["slug"]: e for grupo in g["grupos"] for e in grupo["estilos"]}
    sem = [s for s in _slugs_por_grupo(g, "legenda") if not ix[s].get("acento")]
    com = [s for s in _slugs_por_grupo(g, "legenda") if ix[s].get("acento")]
    ganchos_sem = [s for s in _slugs_por_grupo(g, "gancho") if not ix[s].get("acento")]
    with capsys.disabled():
        print(f"\n  legendas sem acento: {sem}\n  legendas com acento: {com}"
              f"\n  ganchos sem acento: {ganchos_sem}")
    assert sem and com and ganchos_sem, "o catálogo precisa dos dois casos"

    p1 = _pay(legenda=sem[0], gancho=ganchos_sem[0], acento="#d14e72")
    d1 = ee.derivar_acento(p1, g)
    assert d1 == {"acento_usado": False, "acento_onde": [], "params": {}}
    dig1 = ee.resumo(dict(p1, acento_usado=False, acento_onde=[]), g)
    assert "não se aplica" in dig1 and "não invente" in dig1

    # TROCANDO SÓ A LEGENDA — nenhum arquivo de configuração é tocado
    p2 = _pay(legenda=com[0], gancho=ganchos_sem[0], acento="#d14e72")
    d2 = ee.derivar_acento(p2, g)
    assert d2["acento_usado"] is True and d2["acento_onde"] == ["legenda"]
    assert d2["params"][com[0]] == ix[com[0]]["acento"]["param"]
    dig2 = ee.resumo(dict(p2, acento_usado=True, acento_onde=["legenda"]), g)
    assert "aplicada na legenda" in dig2


# ──────────── GATE §7.8 — caixa desmarcada é um NÃO explícito ────────────
def test_gate_digest_imprime_fora():
    g = json.loads((FIXTURES / "galeria-exemplo.json").read_text())
    pay = json.loads((FIXTURES / "estilo-v2-exemplo.json").read_text())
    dig = ee.resumo(pay, g)
    ligados = [k for k, v in pay["elementos"].items() if v]
    desligados = [k for k, v in pay["elementos"].items() if not v]
    # 3/2 até 2026-08-11, 3/3 desde a SPEC-44: o par de fixtures (galeria +
    # payload) passou a carregar os 6 interruptores de `reels`, com `tracking`
    # desmarcado. O número é guarda de FORMA — sem ele, um payload esvaziado
    # deixaria o laço de baixo sem nada para conferir e o teste ficaria verde
    # sem exercitar o `fora:`. Quem mexer nos interruptores refaz os dois.
    assert len(ligados) == 3 and len(desligados) == 3
    linha = next(l for l in dig.splitlines() if l.strip().startswith("· fora:"))
    for k in desligados:
        assert k in linha, (k, linha)
    for k in ligados:
        assert k not in linha, (k, linha)
    lf = next(l for l in dig.splitlines() if "grafismos FORA" in l)
    assert "marca-texto" in lf and "postit" not in lf


def test_gate_digest_com_2_de_5_ligados():
    """O caso literal do aceite: 2 de 5 ligados ⇒ a linha `fora:` nomeia os 3."""
    g = json.loads((FIXTURES / "galeria-exemplo.json").read_text())
    pay = json.loads((FIXTURES / "estilo-v2-exemplo.json").read_text())
    pay["elementos"] = {"sfx": True, "trilha": True, "split_broll": False,
                        "flash_no_corte": False, "legenda_ativa": False}
    linha = next(l for l in ee.resumo(pay, g).splitlines()
                 if l.strip().startswith("· fora:"))
    assert linha.count(",") == 2, linha
    for k in ("split_broll", "flash_no_corte", "legenda_ativa"):
        assert k in linha


# ───────────────────── defeitos PLANTADOS (os dentes) ─────────────────────
def _gal_fix():
    return json.loads((FIXTURES / "galeria-exemplo.json").read_text())


def _pay_fix():
    return json.loads((FIXTURES / "estilo-v2-exemplo.json").read_text())


def _pay_v3(modo="animada", densidade="equilibrada", sfx="automatico"):
    p = _pay_fix()
    p["contrato"] = "benchmark.edit-estilo/v3"
    p["direcao_edicao"] = {
        "modo": modo, "densidade": densidade, "sfx": sfx,
    }
    p["elementos"]["sfx"] = sfx == "automatico"
    return p


def _pay_v3_essencial():
    p = _pay_v3("essencial", "leve", "sem-sfx")
    p["gramatica"] = "plano-fixo"
    p["gramatica_plano"] = "fixa"
    p.pop("gancho", None)
    p["grafismos"] = []
    p["grafismos_fora"] = ["postit", "marca-texto"]
    for chave in ("sfx", "split_broll", "flash_no_corte", "tracking"):
        p["elementos"][chave] = False
    return p


def test_fixture_passa_limpa():
    assert ee.validar(_pay_fix(), _gal_fix()) == []


def test_v3_passa_limpo_e_o_digest_nomeia_o_acabamento():
    p = _pay_v3()
    assert ee.validar(p, _gal_fix()) == []
    dig = ee.resumo(p, _gal_fix())
    assert "acabamento: com animações" in dig
    assert "densidade: equilibrada" in dig and "SFX: automatico" in dig


@pytest.mark.parametrize("nome,mutacao,trecho", [
    ("direção ausente", lambda p: p.pop("direcao_edicao"), "obrigatório ausente"),
    ("modo fora do enum",
     lambda p: p["direcao_edicao"].update(modo="cinematica"), "direcao_edicao.modo"),
    ("modo com tipo inválido",
     lambda p: p["direcao_edicao"].update(modo=[]), "direcao_edicao.modo"),
    ("densidade fora do enum",
     lambda p: p["direcao_edicao"].update(densidade="máxima"), "direcao_edicao.densidade"),
    ("SFX fora do enum",
     lambda p: p["direcao_edicao"].update(sfx="talvez"), "direcao_edicao.sfx"),
    ("campo interno ausente",
     lambda p: p["direcao_edicao"].pop("densidade"), "campos obrigatórios ausentes"),
    ("campo interno inventado",
     lambda p: p["direcao_edicao"].update(filtro="vintage"), "campos desconhecidos"),
    ("SFX contradiz interruptor",
     lambda p: p["elementos"].update(sfx=False), "contradiz elementos.sfx"),
])
def test_v3_planta_direcao_invalida(nome, mutacao, trecho, capsys):
    p = _pay_v3()
    mutacao(p)
    erros = ee.validar(p, _gal_fix())
    with capsys.disabled():
        print("\n  [v3 %s] → %d violação(ões)" % (nome, len(erros)))
    assert erros, "defeito de direção NÃO acusado: %s" % nome
    assert any(trecho in x for x in erros), (nome, erros)


def test_v3_essencial_valido_sem_animacoes_nem_sfx():
    p = _pay_v3_essencial()
    assert ee.validar(p, _gal_fix()) == []


@pytest.mark.parametrize("nome,mutacao,trecho", [
    ("densidade não leve",
     lambda p: p["direcao_edicao"].update(densidade="equilibrada"),
     "exige densidade 'leve'"),
    ("SFX automático",
     lambda p: (p["direcao_edicao"].update(sfx="automatico"),
                p["elementos"].update(sfx=True)), "exige sfx 'sem-sfx'"),
    ("grafismo presente", lambda p: p.update(grafismos=["postit"]),
     "não aceita grafismos"),
    ("gancho presente", lambda p: p.update(gancho="gancho-animado"),
     "não aceita gancho animado"),
    ("plano alternado",
     lambda p: p.update(gramatica="plano-alternado", gramatica_plano="alternada"),
     "exige gramatica 'plano-fixo'"),
    ("flash ligado", lambda p: p["elementos"].update(flash_no_corte=True),
     "interruptores de animação/SFX desligados"),
])
def test_v3_essencial_rejeita_animacao(nome, mutacao, trecho, capsys):
    p = _pay_v3_essencial()
    mutacao(p)
    erros = ee.validar(p, _gal_fix())
    with capsys.disabled():
        print("\n  [essencial %s] → %d violação(ões)" % (nome, len(erros)))
    assert any(trecho in x for x in erros), (nome, erros)


@pytest.mark.parametrize("modo", ["animada", "surpresa"])
def test_v3_animada_ou_surpresa_pode_desligar_sfx(modo):
    p = _pay_v3(modo, "alta", "sem-sfx")
    assert p["elementos"]["sfx"] is False
    assert ee.validar(p, _gal_fix()) == []


def test_config_oferece_tres_direcoes_e_validador_tem_dentes():
    ds = pv._direcoes_edicao()
    assert [d["modo"] for d in ds] == ["essencial", "animada", "surpresa"]
    assert pv.validar_direcoes_edicao({"direcoes_edicao": ds}) == []
    assert ds[0]["sfx"] == "sem-sfx"
    assert ds[1]["sfx"] == ds[2]["sfx"] == "automatico"

    ausente = {"direcoes_edicao": ds[:2]}
    assert pv.validar_direcoes_edicao(ausente)
    duplicada = json.loads(json.dumps(ds))
    duplicada[2]["modo"] = "animada"
    assert pv.validar_direcoes_edicao({"direcoes_edicao": duplicada})
    densidade_ruim = json.loads(json.dumps(ds))
    densidade_ruim[1]["densidade"] = "cinema"
    assert any("densidade" in x for x in
               pv.validar_direcoes_edicao({"direcoes_edicao": densidade_ruim}))


@pytest.mark.parametrize("nome,mutacao,trecho", [
    ("acento_usado declarado ao contrário",
     lambda p: p.update(acento_usado=False, acento_onde=[]), "derive, não declare"),
    ("acento_onde vazio com usado=true",
     lambda p: p.update(acento_onde=[]), "acento_onde vazio"),
    ("mapa de interruptores incompleto",
     lambda p: p["elementos"].pop("trilha"), "mapa INCOMPLETO"),
    ("interruptor inventado",
     lambda p: p["elementos"].update({"turbo": True}), "fora de interruptores.json"),
    ("slug fora da galeria",
     lambda p: p.update(legenda="legenda-que-nao-existe"), "não está na galeria"),
    ("candidato escolhido",
     lambda p: p.update(legenda="chip"), "candidato"),
    ("slug do grupo errado",
     lambda p: p.update(gancho="postit"), "é do grupo"),
    ("grafismo em dentro E fora",
     lambda p: p.update(grafismos_fora=["postit", "marca-texto"]), "E em `grafismos_fora`"),
    ("campo desconhecido",
     lambda p: p.update(cor_favorita="azul"), "campo desconhecido"),
    ("acento que não é hex",
     lambda p: p.update(acento="vermelho"), "não é #RRGGBB"),
    ("fonte fora do enum",
     lambda p: p.update(fonte="telepatia"), "fora de"),
    ("contrato errado",
     lambda p: p.update(contrato="benchmark.edit-estilo/v9"), "contrato desconhecido"),
])
def test_planta_defeito_e_o_validador_acusa(nome, mutacao, trecho, capsys):
    p = _pay_fix()
    mutacao(p)
    erros = ee.validar(p, _gal_fix())
    with capsys.disabled():
        print(f"\n  [{nome}] → {len(erros)} violação(ões)")
    assert erros, f"defeito plantado NÃO acusado: {nome}"
    assert any(trecho in e for e in erros), (nome, erros)


def test_v1_continua_valido_e_migra():
    v1 = {"contrato": "benchmark.edit-estilo/v1", "salvo_em": "2026-08-08T10:00:00-03:00",
          "revisao_base": 3, "legenda": "karaoke", "headline": "realce",
          "elementos": {"sfx": True, "trilha": False}}
    assert ee.validar(v1) == []
    dig = ee.resumo(v1)
    assert "v1" in dig and "fora: trilha" in dig
    v2 = ee.migrar_v1(v1)
    assert v2["contrato"] == "benchmark.edit-estilo/v2"
    assert v2["gancho"] == "realce" and "headline" not in v2
    assert v2["fonte"] == "chat"


def test_validar_sem_galeria_nao_confere_vocabulario():
    """Degradação declarada: sem `galeria.json` ao lado, o vocabulário não é
    conferido — e quem chama tem que saber disso (o CLI imprime)."""
    p = _pay_fix()
    p["legenda"] = "legenda-que-nao-existe"
    assert ee.validar(p, None) == []
    assert ee.validar(p, _gal_fix()) != []


def test_aplicar_grava_estilo_vigente(tmp_path):
    d = tmp_path / "prod"
    (d / ".preview" / "estilos").mkdir(parents=True)
    (d / ".preview" / "estilos" / "galeria.json").write_text(
        json.dumps(_gal_fix(), ensure_ascii=False))
    origem = d / ".preview" / "aplicados"
    origem.mkdir()
    arq = origem / "20260808T234210-estilo-1.json"
    arq.write_text(json.dumps(_pay_fix(), ensure_ascii=False))
    destino = Path(ee.aplicar(str(d), str(arq)))
    obj = json.loads(destino.read_text())
    assert obj["contrato"] == "benchmark.edit-estilo-vigente/v1"
    assert obj["estilo"]["legenda"] == "legenda-destaque-tema"
    assert not os.path.isabs(obj["origem"])


def test_consumir_move_de_pendentes_para_aplicados(tmp_path):
    d = tmp_path / "prod"
    (d / ".preview" / "estilos").mkdir(parents=True)
    (d / ".preview" / "estilos" / "galeria.json").write_text(
        json.dumps(_gal_fix(), ensure_ascii=False))
    pend = d / ".preview" / "pendentes"
    pend.mkdir()
    arq = pend / "20260808T234210-estilo-1.json"
    arq.write_text(json.dumps({
        "schema": "benchmark.preview-evento/v1", "tipo": "estilo",
        "salvo_em": "2026-08-08T23:42:10-03:00", "origem": {"ua": "teste"},
        "payload": _pay_fix()}, ensure_ascii=False))
    r = ee.consumir(str(d), str(arq))
    assert not arq.exists(), "o ACK é o MOVE: o pendente tem que sair de pendentes/"
    assert Path(r["destino"]).is_file()
    assert "ESTILO ESCOLHIDO" in r["resumo"]


def test_rerender_muda_o_cabecalho_do_digest():
    p = _pay_fix()
    assert "ESTILO ESCOLHIDO NA GALERIA" in ee.resumo(p, _gal_fix())
    p["rerender"] = True
    assert "TROCA DE ESTILO" in ee.resumo(p, _gal_fix())


# ───────────────── a tela: o que dá para conferir sem browser ─────────────────
TELA = SCRIPTS.parents[0] / "preview" / "app" / "galeria"


def _sem_comentarios(js: str) -> str:
    """Tira `//…` e `/*…*/`. O aceite §7.3 diz "fora de comentário" — e isso
    importa aqui porque o cabeçalho CITA a confissão deles, que contém `1080`
    (*"scaled by boxWidth/1080"*). Apagar a citação para o grep passar seria
    esconder a prova; o certo é o grep saber o que é código."""
    fora, i, n = [], 0, len(js)
    modo = None            # None | "linha" | "bloco" | "aspas"
    fecha = ""
    while i < n:
        c, prox = js[i], js[i + 1] if i + 1 < n else ""
        if modo is None:
            if c == "/" and prox == "/":
                modo, i = "linha", i + 2; continue
            if c == "/" and prox == "*":
                modo, i = "bloco", i + 2; continue
            if c in "\"'`":
                modo, fecha = "aspas", c
            fora.append(c)
        elif modo == "linha":
            if c == "\n":
                modo = None; fora.append(c)
        elif modo == "bloco":
            if c == "*" and prox == "/":
                modo, i = None, i + 2; continue
        else:                                   # dentro de string
            fora.append(c)
            if c == "\\":
                if i + 1 < n:
                    fora.append(js[i + 1])
                i += 2
                continue
            if c == fecha:
                modo = None
        i += 1
    return "".join(fora)


def test_tela_sem_valor_de_estilo_nem_de_formato(capsys):
    """O `grep` barato do aceite §7.1 e do §7.3, no arquivo em que ele importa.

    Um número de estilo aqui seria o `app.js:182-188` deles de novo — o preview
    reimplementado em DOM, sincronizado por disciplina humana."""
    import re
    bruto = (TELA / "galeria.js").read_text()
    js = _sem_comentarios(bruto)
    # dente do próprio removedor: a citação com `1080` está no bruto e não no
    # código; se o removedor virar no-op, este par de asserts cai.
    assert "boxWidth/1080" in bruto and "boxWidth/1080" not in js

    for p in ("bezier(", "cubic-bezier"):
        assert p not in js, p
    hexes = re.findall(r"#[0-9a-fA-F]{6}\b", js)
    # o único hex tolerado é o valor NEUTRO de um <input type=color> sem cor
    assert set(hexes) <= {"#000000"}, hexes
    formatos = re.findall(r"\b(?:1080|1920|0\.3333)\b", js)
    assert formatos == [], formatos
    assert "fontSize" not in js, "nome de parâmetro de estilo cravado no código"
    with capsys.disabled():
        print(f"\n  varreu {len(js)} chars de código (de {len(bruto)} do arquivo): "
              f"0 easing, {len(hexes)} hex neutro, 0 valor de formato")


def test_tela_existe_inteira():
    for nome in ("galeria.html", "galeria.js", "galeria.css",
                 "interruptores.json", "README.md"):
        assert (TELA / nome).is_file(), nome
    itens = json.loads((TELA / "interruptores.json").read_text())["itens"]
    # `tracking` entrou em 2026-08-11 (achado A19/R-12): `previews-peca.py` já
    # mandava o card ligá-lo e o id não existia aqui, então o validador recusava
    # `elementos.tracking` como "id fora de interruptores.json". Este número é o
    # guarda: quem tirar o id de volta reprova aqui.
    assert len(itens) == 6
    assert {i["id"] for i in itens} == {"sfx", "trilha", "split_broll",
                                        "flash_no_corte", "legenda_ativa",
                                        "tracking"}


def test_tela_exige_acabamento_e_preserva_rascunho_restyle(capsys):
    """A produção nova não ganha animação por acidente nem termina só em legenda."""
    js = (TELA / "galeria.js").read_text()
    css = (TELA / "galeria.css").read_text()
    config = json.loads((TELA / "interruptores.json").read_text())
    direcoes = config["direcoes_edicao"]

    assert [d["modo"] for d in direcoes] == ["essencial", "animada", "surpresa"]
    assert len(direcoes) == 3
    assert "benchmark.edit-estilo/v3" in js
    assert "direcaoEdicao: null" in js, "produção nova não pode nascer escolhida"
    assert "g.vigente?.estilo?.direcao_edicao" in js, "restyle v3 precisa ser relido"
    assert "direcaoValida(vig?.direcao_edicao)" not in js, \
        "semente de produção nova não pode responder a pergunta pelo usuário"
    assert 'typeof g.vigente?.estilo?.elementos?.sfx === "boolean"' in js, \
        "restyle v1/v2 precisa preservar o interruptor já salvo"
    assert "direcaoEdicao: S.direcaoEdicao ? { ...S.direcaoEdicao } : null" in js
    assert "S.direcaoEdicao = { ...r.direcaoEdicao }" in js
    assert "elBotao.disabled = S.enviando || !S.direcaoEdicao" in js
    assert '"Escolha o acabamento"' in js
    assert "raiz.appendChild(secaoDirecaoEdicao())" in js
    assert js.index("raiz.appendChild(secaoDirecaoEdicao())") < js.index(
        "const prop = blocoPropostas()")

    # SFX começa automático nas duas rotas com animação, mas a caixa continua
    # sendo a autoridade para desligá-lo e o payload espelha a escolha.
    assert "S.sfxTocado = true" in js
    assert 'cb.checked ? "automatico" : "sem-sfx"' in js
    assert 'direcao.sfx = S.elementos.sfx === false ? "sem-sfx" : "automatico"' in js

    # Essencial limpa movimentos, trava os controles e continua permitindo
    # legenda. O teste checa o código que faz, não só a microcopy do card.
    for marca in ("S.grafismos.clear()", "delete S.escolha.gancho",
                  'e.slug === "plano-fixo"', '"flash_no_corte"', '"tracking"'):
        assert marca in js, marca
    assert "galeria-direcao-grade" in css
    assert '.galeria-direcao-card[aria-pressed="true"]' in css
    assert ".galeria-chave--travada" in css
    with capsys.disabled():
        print("\n  acabamento: 3 cards / sem default / save bloqueado / "
              "rascunho, restyle e SFX explícitos")


def test_shell_da_ilha_tem_contratos_responsivos_e_ids_unicos(capsys):
    """Trava a superfície vendável em desktop e painel lateral.

    Não finge substituir inspeção visual: aqui ficam os contratos baratos que
    impedem voltar ao layout sem breakpoint, à altura 100vh e a controles sem
    alvo único no DOM.
    """
    import re

    app = TELA.parent
    html = (app / "index.html").read_text()
    css = (app / "app.css").read_text()
    main = (app / "js" / "main.js").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert ids and len(ids) == len(set(ids)), "id duplicado no shell"
    obrigatorios = {"player", "painel", "trilhas", "abas", "btn-in",
                    "btn-zonas", "estado-conexao", "painel-aba",
                    "btn-aprovar", "btn-salvar"}
    assert obrigatorios <= set(ids), obrigatorios - set(ids)
    assert "height: 100dvh" in css and "height: 100vh" not in css
    assert "@media (max-width: 640px)" in css
    assert "@media (max-width: 520px)" in css
    assert "@media (min-width: 960px)" in css
    assert "body.vertical .palco" in css
    assert "body.aba-montada .barra-transporte" in css
    assert "aoConexao" in main and "btn-zonas" in main
    assert "midiaAprovavel" in main and "midia?.servivel" in main
    assert ".coluna-timeline { overflow: visible; }" in css
    assert "overflow-y: auto" in css
    with capsys.disabled():
        print(f"\n  shell: {len(ids)} ids únicos / 3 faixas responsivas / "
              "player, régua, zonas e conexão presentes")


def test_galeria_entrega_uma_proposta_mais_duas_variacoes(capsys):
    """A autoridade da SPEC-49 é 1 direção e até 2 variações, não 40 cards."""
    import re

    js = (TELA / "galeria.js").read_text()
    css = (TELA / "galeria.css").read_text()
    m = re.search(r"const GERADOR_VERSAO_ESPERADA\s*=\s*(\d+)", js)
    assert m and int(m.group(1)) == pv.GERADOR_VERSAO
    assert "props.slice(0, 3)" in js
    assert "galeria-proposta--principal" in js
    assert "galeria-proposta--variacao" in js
    assert "const atual = [...S.grafismos].sort()" in js
    assert "const variacoes = Math.max(0, Math.min(props.length, 3) - 1)" in js
    assert "else raiz.appendChild(blocoAcentoTopo())" in js
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 520px)" in css
    assert "grid-template-rows: 210px 158px" in css
    assert "grid-template-rows: 190px 148px" in css
    assert ".aba-estilo .galeria-cabecalho { display: none; }" in css
    assert "Ajustes finos" in js
    with capsys.disabled():
        print("\n  galeria: gerador v%d / 1 proposta + até 2 variações / "
              "grafismos entram na igualdade" % pv.GERADOR_VERSAO)


def test_shell_preserva_rascunho_teclado_e_semantica_modal(capsys):
    """Trava as regressões encontradas na auditoria interativa do redesign."""
    app = TELA.parent
    main = (app / "js" / "main.js").read_text()
    estilos = (app / "js" / "estilos.js").read_text()
    modal = (app / "js" / "modal.js").read_text()
    marcas = (app / "js" / "marcacoes.js").read_text()
    timeline = (app / "js" / "timeline.js").read_text()
    estado_js = (app / "js" / "estado.js").read_text()
    trilhas = (app / "js" / "trilhas.js").read_text()
    servidor = (app.parent / "servidor.py").read_text()
    estado_py = (app.parent.parent / "scripts" / "estado.py").read_text()
    html = (app / "index.html").read_text()
    js = (TELA / "galeria.js").read_text()
    css = (TELA / "galeria.css").read_text()

    # Clicar na aba ativa não remonta; sair e voltar leva um rascunho validado.
    assert "if (id === abaAtiva) return" in main
    assert "rascunho: rascunhoAtual" in js
    assert "restaurarRascunho(opcoes.rascunho)" in js
    assert "rascunho = atual?.sujo ? atual : null" in estilos
    assert "podeDesmontar: () => g.podeDestruir?.() !== false" in estilos
    assert "podeDesmontarAba && !podeDesmontarAba()" in main
    assert "podeDestruir: () => !S.enviando" in js
    assert "protegerSaidaPendente" in js
    assert "!S.enviando && !S.sujo" in js
    assert "temRascunhoPendente" in estilos
    assert "window.addEventListener('beforeunload', protegerSaidaComRascunho)" in estilos

    # No sidecar estreito as variações preservam preview, título e ação sem
    # esmagar o conteúdo nem deixar o selo de contraste invadir o texto.
    trecho_compacto = css.split("@media (max-width: 520px)", 1)[1]
    assert ".galeria-proposta--variacao .galeria-proposta-porque {\n    display: none;" in trecho_compacto
    assert "top: 55px" in trecho_compacto
    assert 'input[type="text"] { flex: 1 1 auto; width: auto; min-width: 0; }' in trecho_compacto
    trecho_sidecar = css.split("@media (max-width: 760px)", 1)[1]
    assert ".galeria-rodape {\n    position: static;" in trecho_sidecar
    app_css = (app / "app.css").read_text()
    trecho_shell_compacto = app_css.split("@media (max-width: 640px)", 1)[1]
    assert "row-gap: 0" in trecho_shell_compacto

    # O contraste é local à faixa real, depois do layout, e respeita o contain
    # da mídia. Uma média do frame inteiro mascara exatamente o fundo sob o CTA.
    assert 'querySelector(".galeria-camada-acento")' in js
    assert "faixa.offsetLeft" in js and "faixa.offsetTop" in js
    assert "escalaMidia = Math.min" in js
    assert "getImageData(x, y, largura, altura)" in js
    assert "cv.width = 24; cv.height = 42" not in js

    # A tablist não deixa setas vazarem para seek e aponta à superfície visível.
    assert "ev.stopPropagation()" in main
    assert "if (e.defaultPrevented) return" in main
    assert "controleZoom" in main and "matches(':hover')" in main
    assert "a.montar ? 'painel-aba' : 'palco'" in main
    assert "sincronizarSemanticaAba" in main

    # `aria-modal` tem fundo inerte, ciclo de Tab e retorno ao disparador.
    assert "n.inert = true" in modal
    assert "n.hasAttribute('aria-live')" in modal
    assert "e.key !== 'Tab'" in modal
    assert "estado.retorno" in modal
    assert 'aria-modal="true"' in html

    # Marcas e dobras da timeline são alcançáveis e nomeadas por teclado.
    assert "document.createElement('button')" in marcas
    assert "editar marcação" in marcas
    assert "editando != null" in marcas
    assert "aria-expanded" in trilhas

    # Zoom reprojeta todos os indicadores, consolida wheel e recupera a mesa
    # depois de uma aba que a deixou com display:none.
    assert "posicionarIndicadores()" in timeline
    assert "deltaEmPixels" in timeline and "agendarRedesenho" in timeline
    assert "ResizeObserver" in timeline and "aoMostrar" in timeline
    assert "candidatoToque" in timeline and "sobreBarraDeRolagem" in timeline
    assert "ultimoScrollLeft" in timeline and "mudouHorizontal" in timeline
    assert "touch-action: pan-y pinch-zoom" in app_css
    assert "--scrollbar-timeline: 8px" in app_css
    assert "teclaZoomComModificador" in main
    assert "if (e.altKey && e.key !== 'Escape') return" in main

    # Poll com a mesma quantidade de clipes ainda remonta se os tempos reais
    # aparecerem. Um 404 inicial de captions nao sela a tentativa para sempre.
    assinatura_timeline = main.split("const assinatura = JSON.stringify", 1)[1].split("]);", 1)[0]
    assert "S.segmentos," in assinatura_timeline
    assert "S.segmentos.length" not in assinatura_timeline
    assert "legendaCarregada = assinaturaLegenda" in main
    assert "legendasCarregadas = true" not in main

    # Estado adiado é buscado de novo; aprovação cruza o snapshot da tela no servidor.
    assert "S.etag = null" in estado_js
    for campo in ("alvo", "fingerprint_corte", "fingerprint_render",
                  "render_alvo", "plano_sha256"):
        assert campo in main and campo in servidor and campo in estado_py
    assert "esperado=esperado" in servidor
    assert "contextoAprovacaoBate" in main
    post = servidor.split("def do_POST", 1)[1].split("def _efeito_do_evento", 1)[0]
    ramo_aprovacao = post.split('if tipo == "aprovacao":', 1)[1].split("else:", 1)[0]
    assert ramo_aprovacao.index("_efeito_do_evento") < ramo_aprovacao.index("_gravar_evento")
    assert 'extra.get("erro_aprovacao")' in ramo_aprovacao
    assert "const notaAberta = MC.caixaAberta()" in main

    # Poll idêntico não redesenha e a exceção de reduced-motion não aninha controles.
    assert "JSON.stringify(novosDados) !== JSON.stringify(S.dados)" in js
    assert "galeria-card-wrap" in js and ".galeria-card-wrap" in css
    assert "envoltorio.appendChild(ver)" in js
    assert "rotularControleReducao" in js and "pararExcedentes()" in js
    assert "controle.innerHTML = ICONES.amostra" in js
    assert "ver.innerHTML = ICONES.amostra" in js
    assert "v.controls = true" not in js
    with capsys.disabled():
        print("\n  interação: rascunho, tablist, modal, marcas e poll protegidos")


@tem_catalogo
def test_interruptores_do_galeria_batem_com_o_perfil(tmp_path):
    g = galeria_de(tmp_path)                       # reels
    ids = {i["id"] for i in g["interruptores"]}
    assert ids == {"sfx", "trilha", "split_broll", "flash_no_corte",
                   "legenda_ativa", "tracking"}
    g2 = galeria_de(tmp_path / "b", nome="longform")
    ids2 = {i["id"] for i in g2["interruptores"]}
    assert "split_broll" not in ids2, "split-broll só existe em reels"
    # `tracking` depende de zoom (CameraSegue com z=1 não move nada), e zoom só
    # existe em reels/vsl — longform não oferece o interruptor.
    assert "tracking" not in ids2, "tracking só existe onde há punch-in"


# ─────────────────────────── runner sem pytest ───────────────────────────
# ─────────────────────────────────────────────────────────── H47-7 (SPEC-47)

def test_catalogo_validar_sai_zero():
    """`gerar-previews.py --validar` tem que sair 0 — e AQUI, numa bateria.

    🔴 Até 2026-08-12 o `--validar` só era rodado à mão, e só no dev. O export
    PODA `medido.ficha` (aponta para `intelligence/edicao/*.md`, instância nossa)
    e o pacote embarcava um `_schema.json` que exigia o campo: um agente externo
    mediu **10 de 46 estilos reprovando o `--validar` no clone**, enquanto aqui os
    11 estilos com `medido` têm ficha e o comando saía 0 desde sempre. O conserto
    foi tornar `ficha` opcional no schema (o campo é opcional por construção);
    este teste é o que garante que a validação passe a rodar em TODA máquina onde
    a bateria roda — inclusive na raiz de um clone, que é onde ela falhava.
    """
    import subprocess
    # o diretório do catálogo já é resolvido pelo previews-peca.py (pv), que
    # sabe achar `catalogo/` nas DUAS grafias (nossa árvore e instalação)
    script = pv.dir_catalogo().parent / "scripts" / "gerar-previews.py"
    if not script.exists() or not CATALOGO.is_file():
        pytest.skip("gerar-previews.py/catalogo.json não estão nesta instalação")
    r = subprocess.run([sys.executable, str(script), "--validar"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "--validar saiu %d. stderr:\n%s" % (r.returncode, r.stderr[-1200:]))
    assert "schema" in (r.stderr + r.stdout), \
        "o --validar não disse o que validou: %s" % (r.stderr[-300:] or "(vazio)")


def _rodar_tudo(argv=None):
    """Descobre `test_*`, injeta `tmp_path`/`capsys`, expande `parametrize`.

    Imprime, no fim, QUANTOS casos rodaram — porque "tudo verde" sem número é
    indistinguível de "não rodou nada"."""
    import inspect
    import shutil as _sh
    import tempfile
    import traceback

    class _Capsys:
        def disabled(self):
            class _Ctx:
                def __enter__(self_i): return None
                def __exit__(self_i, *a): return False
            return _Ctx()

    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    base = Path(tempfile.mkdtemp(prefix="spec19-testes-"))
    ok = falhas = pulados = 0
    erros = []
    for nome, fn in fns:
        pular = getattr(fn, "_pular", None)
        if pular and pular[0]:
            print("  ⊘ %s (%s)" % (nome, pular[1]))
            pulados += 1
            continue
        casos = getattr(fn, "_casos", None)
        lotes = ([dict(zip(casos[0], v if isinstance(v, tuple) else (v,)))
                  for v in casos[1]] if casos else [{}])
        for i, kw in enumerate(lotes):
            params = inspect.signature(fn).parameters
            args = dict(kw)
            if "tmp_path" in params:
                d = base / ("%s-%d" % (nome, i))
                d.mkdir(parents=True, exist_ok=True)
                args["tmp_path"] = d
            if "capsys" in params:
                args["capsys"] = _Capsys()
            rotulo = nome + ("[%s]" % kw.get("nome", i) if casos else "")
            try:
                fn(**args)
                ok += 1
            except getattr(pytest, "_Skip", ()) as e:      # noqa: B902
                print("  ⊘ %s (%s)" % (rotulo, e))
                pulados += 1
            except Exception:                              # noqa: BLE001
                falhas += 1
                erros.append((rotulo, traceback.format_exc()))
                print("  ✗ %s" % rotulo)
    _sh.rmtree(base, ignore_errors=True)
    for rotulo, tb in erros:
        print("\n─── %s ───\n%s" % (rotulo, tb))
    print("\n%d caso(s) verdes · %d falha(s) · %d pulado(s) "
          "(de %d funções de teste)" % (ok, falhas, pulados, len(fns)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
