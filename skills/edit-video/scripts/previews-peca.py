#!/usr/bin/env python3
"""Galeria de estilos — o gerador do `galeria.json` e dos previews de nível 1.

    previews-peca.py <dir> [--somente-defaults] [--grupo G] [--gancho T]
                           [--acento HEX] [--tema SLUG] [--forcar] [--sem-render]
    previews-peca.py <dir> --listar          slug · grupo · nível · chave (stdout)
    previews-peca.py --fixture <destino>     dir autocontido pra testar sem servidor

Contrato de saída: o caminho do `galeria.json` no stdout, logs no stderr.
Idempotente: reexecutar não custa nada; refresh = apagar `.preview/estilos/peca/`.

────────────────────────────────────────────────────────────────────────────────
OS DOIS NÍVEIS, E POR QUE NENHUM RENDER É SÍNCRONO COM CLIQUE (SPEC-19 §3.2)

  nível 0  preview genérico do catálogo (SPEC-15), versionado no repo, custo 0
  nível 1  o MESMO componente com o texto real da peça — só `legenda` e `gancho`,
           que são os únicos grupos em que o texto muda o resultado

Renderizar os 31 previews a cada abertura custaria ~8 min e é inaceitável;
renderizar zero desperdiça o diferencial. Todo card abre no nível 0 e troca
sozinho quando o nível 1 daquele slug existe.

🔴 A COISA QUE ESTE ARQUIVO NÃO PODE FAZER: escrever valor de formato.
`--scale` é DERIVADO (`LARGURA_CARD / perfil.video.largura`), `frames` é
DERIVADO (`durS × perfil.video.fps`). Um `--scale=0.3333` aqui é o
`scale=1080:1920` do `montar.sh:118` num lugar novo.

🔴 E A QUE ELE NÃO PODE FAZER EM SILÊNCIO: renderizar nível 1 num canvas que não
é o da peça. O canvas VIAJA NOS PROPS (`canvas_nos_props`), e o dente é a
medição do PNG que voltou contra o que se pediu. Até 2026-08-10 a composição
lia `src/data/perfil.json`, um arquivo GLOBAL dentro da fonte do produto que
mudava quando outra produção era resolvida — e o portão conferia a intenção
ANTES do render, deixando a janela entre conferir e renderizar aberta.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib

perfil_mod = importlib.import_module("perfil")

CONTRATO = "benchmark.galeria-estilos/v1"
GERADOR = "previews-peca.py"
# 🔴 VERSÃO DO GERADOR, NÃO DO CONTRATO (achado D-3, 2026-08-11). O conserto de
# microcopy da SPEC-40 vive AQUI, na geração: um `galeria.json` gravado antes
# dela continua exibindo o texto velho — `parametros: []` e um número de SPEC na
# primeira linha da tela — até alguém regerar, e nada na tela dizia isso. O
# contrato não serve para marcar esse tipo de mudança: o formato não mudou, só a
# prosa, e subir o contrato obrigaria a quebrar leitores que estão certos.
#
# Sobe quando muda o que a tela MOSTRA a partir do mesmo formato (microcopy,
# avisos, campos aditivos que a tela usa). Quem lê compara com o que espera e
# DIZ que a tela está velha; ninguém regenera sozinho — regerar custa render de
# preview (99,9 s medidos em 13 previews) e reescreveria artefato debaixo de
# quem está usando a tela.
#   1 — o gerador pré-SPEC-40 (implícito: `galeria.json` sem este campo)
#   2 — SPEC-40 (microcopy de creator) + SPEC-41 (semente) + SPEC-43
#       (interruptores com `tecnico`)
#   3 — SPEC-49: a galeria abre como PROPOSTA (`propostas`), os grafismos vêm do
#       plano (`grafismos_do_plano`) e a cor reflete ao vivo na tela
#   4 — escolha explícita de acabamento: essencial, animada ou surpresa
GERADOR_VERSAO = 4

SCRIPTS = Path(__file__).resolve().parent


def _raiz_por_marcador() -> Path:
    """Sobe até achar um marcador da árvore. NUNCA conta níveis.

    🔴 MEDIDO NO TESTE DO CLIENTE, 2026-08-10. Aqui estava
    `SCRIPTS.parents[2]`, que é uma AFIRMAÇÃO sobre onde a skill mora: na nossa
    árvore `ilha/skills/edit-video/scripts` sobe para `ilha/`, e `ilha/tools/
    remotion-compositor` existe. Na instalação do cliente a skill mora em
    `.claude/skills/edit-video/scripts`, os mesmos dois níveis dão `.claude/`, e
    o script foi procurar o catálogo de estilos em
    `.claude/tools/remotion-compositor/catalogo/` — que não existe. A galeria
    abortou com "sem catálogo de estilos", e a mensagem mandava rodar um comando
    que não conserta nada, porque o problema não era o catálogo.

    É classe A do auditor, e a saída certa já estava escrita e testada em
    `auditar-acoplamento.py:achar_raiz()`: subir até um marcador. O marcador aqui
    é o próprio `tools/remotion-compositor/package.json` — se ele está lá, é a
    árvore certa, esteja ela a dois ou a cinco níveis."""
    for base in [SCRIPTS, *SCRIPTS.parents]:
        if (base / "tools" / "remotion-compositor" / "package.json").is_file():
            return base
    # sem marcador: devolve o palpite histórico em vez de estourar, e quem
    # chamar vai falhar nomeando o caminho que tentou.
    return SCRIPTS.parents[2] if len(SCRIPTS.parents) > 2 else SCRIPTS


ILHA = _raiz_por_marcador()


def dir_remotion() -> Path:
    """O projeto Remotion. Env primeiro — um cliente do produto pode tê-lo noutro
    lugar, e nenhum caminho da NOSSA instalação pode estar cravado aqui."""
    v = os.environ.get("BENCH_REMOTION_DIR")
    if v:
        return Path(v).expanduser().resolve()
    return ILHA / "tools" / "remotion-compositor"


def dir_catalogo() -> Path:
    v = os.environ.get("BENCH_CATALOGO_DIR")
    if v:
        return Path(v).expanduser().resolve()
    return dir_remotion() / "catalogo"


# Largura do card na tela, em px de CSS. É medida de INTERFACE, não de formato de
# peça: a altura sai do aspecto do perfil. Trocar aqui muda o card em reels, vsl
# e longform de uma vez — que é o ponto.
LARGURA_CARD = int(os.environ.get("BENCH_LARGURA_CARD", "360"))

# Os únicos grupos em que o texto real muda o resultado (§3.2 regra 3).
GRUPOS_NIVEL1 = ("legenda", "gancho")

# Ordem das seções na tela (§3.6). `tema` vem antes dos grupos tipográficos pela
# razão deles (`ref-A/SKILL.md:180-181`): "é com ele que eles pintam".
ORDEM_GRUPOS = ("gramatica", "tema", "gancho", "legenda", "grafismo")
TITULOS = {
    "gramatica": "Gramática de plano",
    "tema": "Tema e cor de destaque",
    "gancho": "Gancho",
    "legenda": "Legenda",
    "grafismo": "Grafismos liberados",
}
SELETOR = {"grafismo": "multi"}

# Tradução `gramatica` (slug) → o campo do perfil que a remontagem lê (§4.2).
# Vive aqui e em `references/contrato-ui.md`; o consumidor da SPEC-16 não precisa
# conhecer o catálogo por causa disto.
GRAMATICA_APLICA = {
    "plano-fixo": {"perfil_campo": "ritmo.gramatica_plano", "valor": "fixa"},
    "plano-alternado": {"perfil_campo": "ritmo.gramatica_plano", "valor": "alternada"},
    # 🔴 O ELO QUE FALTAVA (achado A19). `rastrear-rosto.py` detecta 633/633
    # frames com Apple Vision, recusa cobertura <35%, e `MotionKit.CameraSegue`
    # já consome o contrato `benchmark.track-rosto/v1` — e NENHUMA etapa,
    # catálogo ou interruptor o oferecia. Pagávamos o custo de um detector
    # melhor que o do concorrente e o dado morria no disco.
    # É aqui, e só aqui, porque `CameraSegue` NÃO funciona sem zoom: com z = 1 o
    # deslocamento máximo é 0 e o componente não move nada. Punch-in é a única
    # gramática que dá margem para seguir.
    "punch-pontual": {"perfil_campo": "ritmo.gramatica_plano", "valor": "punch-pontual",
                      "liga": "tracking"},
    # não é gramática de plano: liga o `split-broll.py` (camada PIXEL) e deixa a
    # gramática no default do perfil. O digest diz isso em voz alta.
    "split-screen-esfumacado": {"perfil_campo": None, "valor": None,
                                "liga": "split_broll"},
}

DUR_GANCHO_S = 2.5          # janela de fala de onde sai o gancho, sem partitura


def log(*a):
    print(*a, file=sys.stderr)


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _ler_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def dims_png(p: Path):
    """Largura/altura do cabeçalho IHDR. MEDIDO, não deduzido do `--scale`.

    A SPEC-15 aprendeu isto do jeito caro: com o sha sozinho, um vizinho trocou o
    `src/data/perfil.json` no meio da onda e 30 cards ficaram num formato e 1 em
    outro, sem nada acusar. O sha descreve a INTENÇÃO; só o pixel descreve o
    disco."""
    try:
        with Path(p).open("rb") as f:
            cab = f.read(24)
    except OSError:
        return None
    if len(cab) < 24 or cab[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", cab[16:24])
    return int(w), int(h)


# ─────────────────────────────── entradas ───────────────────────────────
def catalogo(raiz: Path | None = None) -> dict:
    p = (Path(raiz) if raiz else dir_catalogo()) / "catalogo.json"
    cat = _ler_json(p)
    if not isinstance(cat, dict) or not cat.get("estilos"):
        sys.exit(
            "sem catálogo de estilos em %s.\n"
            "  A galeria não inventa vocabulário: rode a SPEC-15 "
            "(`npm run catalogo` em tools/remotion-compositor) antes." % p
        )
    return cat


def perfil_da_peca(dir_prod: str) -> tuple[dict, str]:
    """(perfil, fonte). `fonte ∈ {perfil.json, fallback}` — nunca adivinha calado."""
    p = Path(dir_prod) / "perfil.json"
    if p.is_file():
        obj = _ler_json(p)
        if isinstance(obj, dict) and obj.get("video"):
            return obj, "perfil.json"
    return json.loads(json.dumps(perfil_mod.FALLBACK_REELS)), "fallback"


def dim_escalada(v: int, escala: float) -> int:
    """A régua do RENDERIZADOR, não a do Python.

    🔴 MEDIDO EM 2026-08-10, no primeiro preview de peça 1920×1080. Com
    `escala = 360/1920 = 0,1875`, a altura dá exatos 202,5 px. O `round` do
    Python é banqueiro e devolve **202**; o Chrome arredonda meio pra cima e
    grava **203**. O dente que compara o PNG medido com o alvo acusava um
    defeito que não existia — e acusava só fora do reels, onde a escala é 1/3 e
    nunca cai no meio. Régua de conferência tem que falar a língua de quem
    produziu o pixel."""
    return math.floor(v * escala + 0.5)


def canvas_nos_props(props: dict, W: int, H: int, FPS: float) -> dict:
    """O canvas da PEÇA viaja no `inputProps` — não em arquivo global.

    🔴 Até 2026-08-10 o formato do card vinha de `src/data/perfil.json`, dentro
    da fonte do produto, e este gerador só conferia ANTES de renderizar se o
    arquivo batia com a peça (suspendendo o nível 1 quando não batia). Era um
    portão sobre a intenção: entre a conferência e o render, um vizinho que
    resolvesse outra produção trocava o arquivo e os cards saíam no formato
    dele — foi assim que 30 cards ficaram num formato e 1 em outro.

    Agora o número vai junto do pedido e o dente é a MEDIÇÃO do PNG que voltou
    (`dims_png`, mais abaixo): régua sobre o pixel, não sobre a promessa."""
    return dict(props, largura=int(W), altura=int(H), fps=float(FPS))


def canvas_de(p: dict) -> tuple[int, int, float]:
    v = p.get("video") or {}
    return int(v["largura"]), int(v["altura"]), float(v["fps"])


def vocabulario_de(perfil_nome: str, cat: dict) -> tuple[str, str | None]:
    """Qual nome de perfil filtra o catálogo — e o aviso quando não é o mesmo.

    🔴 MEDIDO NA PRIMEIRA EXECUÇÃO, e é um sucesso silencioso clássico: o
    `FALLBACK_REELS` da SPEC-00 se chama **`reels-fallback`**, e os `perfis` do
    catálogo dizem **`reels`**. Filtrar pelo nome cru devolve **0 estilos**, o
    `galeria.json` sai VÁLIDO e a tela abre vazia — exatamente o aceite §7.10
    ("degradação honesta") virando uma galeria sem nada, sem ninguém acusar.

    A regra: o sufixo `-fallback` é procedência, não vocabulário. Quando o nome
    resolvido não existe no catálogo, o aviso nomeia o fato em vez de a tela
    ficar muda."""
    nomes = {p for e in cat["estilos"] for p in (e.get("perfis") or [])}
    if perfil_nome in nomes:
        return perfil_nome, None
    base = perfil_nome.rsplit("-fallback", 1)[0]
    if base != perfil_nome and base in nomes:
        return base, ("o perfil resolvido é %r (fallback); o vocabulário do "
                      "catálogo foi filtrado por %r" % (perfil_nome, base))
    return perfil_nome, ("nenhum estilo do catálogo declara o perfil %r — a "
                         "galeria abre com os grupos vazios. Vocabulários "
                         "disponíveis: %s" % (perfil_nome, ", ".join(sorted(nomes))))


def oferecidos(cat: dict, perfil_nome: str, grupo: str | None = None) -> dict:
    """Filtra por `perfis`, agrupa e resolve `defaultDe`.

    A regra da SPEC-15 §4.1 — no máximo um `defaultDe` por perfil por grupo — é o
    que faz a seleção inicial ser DETERMINÍSTICA. O ref-A marca `edits[0]`, o
    primeiro do array (`app.js:592`): reordenar o catálogo muda a escolha
    default do usuário sem ninguém perceber."""
    por_grupo: dict[str, list] = {g: [] for g in ORDEM_GRUPOS}
    mudos = []
    origem = dir_catalogo()
    for e in cat["estilos"]:
        if perfil_nome not in (e.get("perfis") or []):
            continue
        if grupo and e["grupo"] != grupo:
            continue
        # 🔴 CARD MUDO NÃO ENTRA NA GALERIA (achado A14). O catálogo declara 47
        # estilos, 8 deles `candidato` — sem preview renderizado. Dois vazavam
        # para a galeria e apareciam como card SEM VÍDEO: escolha às cegas,
        # que é exatamente o que esta aba existe para evitar. A régua é o
        # ARQUIVO no disco, não o campo `estado`: um `pronto` cujo .webm sumiu é
        # tão mudo quanto um `candidato`, e só o disco sabe disso.
        if not _tem_preview(e, origem):
            mudos.append((e["slug"], e.get("estado")))
            continue
        por_grupo.setdefault(e["grupo"], []).append(e)
    if mudos:
        log("galeria: %d estilo(s) fora por não terem NENHUM preview no disco — %s"
            % (len(mudos), ", ".join("%s[%s]" % (s, st or "?") for s, st in mudos[:8])))
    return por_grupo


def _tem_preview(estilo: dict, origem: Path) -> bool:
    """A régua é o POSTER. O `.webm` é o degrau de cima, não o piso.

    🔴 A primeira versão desta função exigia os dois arquivos, e o teste do
    cliente mostrou por que isso é a régua errada (2026-08-10): num clone do
    produto chegam os **39 PNG e nenhum `.webm`** — o `.gitignore` barra
    `*.webm`. Com "os dois", a galeria do cliente abriu com **0 estilos
    oferecidos**, e o MANIFESTO chama o catálogo com preview de "a peça que nos
    distingue".

    O defeito do achado A14 é card MUDO — o que não mostra nada. Um card com
    poster mostra o estilo; sem o vídeo ele mostra menos, e isso é um aviso, não
    uma exclusão. Excluir por falta do `.webm` trocaria um defeito de 2 cards
    por um de 40."""
    prev = estilo.get("preview") or {}
    poster = prev.get("poster")
    return bool(poster) and (origem / poster).is_file()


# ─────────────────────────── o texto da peça (§3.11) ───────────────────────────
def _paginar(palavras: list[dict], por_pagina: int) -> list[list[dict]]:
    return [palavras[i:i + por_pagina] for i in range(0, len(palavras), por_pagina)]


def _captions_do_disco(dir_prod: str) -> tuple[list, str] | tuple[None, None]:
    """A legenda da peça mora na PRODUÇÃO — nunca mais em `src/data/`.

    🔴 O segundo candidato era `<remotion>/src/data/captions.<slug>.json`, e
    esse caminho é o próprio achado A6: a produção escrevia dentro da fonte do
    produto, e este leitor a procurava lá. Com a peça em
    `<dir-producao>/remotion/` (2026-08-10), os dois candidatos ficam dentro da
    instância e o produto para de ser prateleira de trabalho de creator."""
    d = Path(dir_prod)
    slug = d.resolve().name
    cands = [d / "captions.json",
             d / "remotion" / "captions.json",
             d / "remotion" / ("captions.%s.json" % slug)]
    for c in cands:
        obj = _ler_json(c)
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "startMs" in obj[0]:
            return obj, str(c)
    return None, None


def texto_da_peca(dir_prod: str, perfil: dict, dur_s: float,
                  gancho_flag: str | None = None) -> dict:
    """Resolve o texto real, e REGISTRA qual fonte venceu.

    🔴 A janela escolhida é a do PIOR CASO — a página com mais caracteres da
    peça, e as vizinhas até completar `durS`. É onde um estilo estoura, quebra
    linha errado ou invade a zona de UI. Escolher a página curta e bonita é a
    mesma família de erro que "amostrar a cada 3 s": um preview que mente por
    seleção de amostra."""
    por_pagina = int(((perfil.get("legenda") or {}).get("max_palavras_pagina")) or 3)
    avisos: list[str] = []

    # 1 — partitura (SPEC-14): já é a paginação que vai ao ar.
    part = _ler_json(Path(dir_prod) / "partitura.json")
    paginas: list[list[dict]] | None = None
    fonte = None
    itens = []
    if isinstance(part, dict) and isinstance(part.get("paginas"), list) and part["paginas"]:
        paginas = []
        for pg in part["paginas"]:
            toks = pg.get("tokens") or []
            paginas.append([
                {"text": t.get("text", ""), "startMs": t.get("fromMs", 0),
                 "endMs": t.get("toMs", 0)} for t in toks
            ])
        itens = part.get("itens") or []
        fonte = "partitura"

    # 2 — captions crus, paginados pelo agrupamento default do perfil.
    if paginas is None:
        caps, origem = _captions_do_disco(dir_prod)
        if caps:
            paginas = _paginar(caps, por_pagina)
            fonte = "captions"
            # Os `avisos` são a PRIMEIRA coisa que se lê na tela de estilo, e vão
            # para quem escolhe o look, não para quem escreveu o script: nome de
            # arquivo e número de spec aqui empurram o creator para fora da tela
            # dele. O fato técnico (a paginação vem do perfil porque não há
            # `partitura.json`) segue registrado neste comentário e no digest.
            avisos.append("a legenda foi quebrada de %d em %d palavras, do jeito "
                          "padrão desta peça — quando o roteiro de legenda existir, "
                          "ele manda" % (por_pagina, por_pagina))
            del origem

    # 3 — amostra do catálogo: SEM nível 1 (o card não ganha o selo).
    if paginas is None:
        return {"fonte": "amostra", "captions": [], "legenda_frase": None,
                "legenda_chars": 0, "gancho": None,
                "avisos": avisos + ["sem partitura.json e sem captions.json: os "
                                    "cards ficam no preview genérico do catálogo"]}

    # pior caso + vizinhas até completar a janela
    def chars(pg):
        return sum(len((t.get("text") or "").strip()) for t in pg)

    i_pior = max(range(len(paginas)), key=lambda i: chars(paginas[i]))
    janela = [paginas[i_pior]]
    esq, dir_ = i_pior - 1, i_pior + 1
    dur_ms = dur_s * 1000.0

    def span(js):
        pl = [t for pg in js for t in pg]
        return (pl[-1]["endMs"] - pl[0]["startMs"]) if pl else 0

    while span(janela) < dur_ms and (esq >= 0 or dir_ < len(paginas)):
        if dir_ < len(paginas):
            janela.append(paginas[dir_]); dir_ += 1
            if span(janela) >= dur_ms:
                break
        if esq >= 0:
            janela.insert(0, paginas[esq]); esq -= 1

    palavras = [t for pg in janela for t in pg]
    t0 = palavras[0]["startMs"] if palavras else 0
    caps = [{"text": t.get("text", ""), "startMs": int(t["startMs"] - t0),
             "endMs": int(t["endMs"] - t0),
             "timestampMs": int(t["startMs"] - t0), "confidence": 1}
            for t in palavras]
    # corta o que passa da janela: a duração do card é `durS`, não a da peça
    caps = [c for c in caps if c["startMs"] < dur_ms] or caps[:1]

    frase_pior = " ".join((t.get("text") or "").strip() for t in paginas[i_pior]).strip()

    # gancho: flag > item `tese` no primeiro terço > primeiros DUR_GANCHO_S
    gancho_txt = gancho_flag
    if not gancho_txt and itens:
        limite = (paginas[-1][-1]["endMs"] if paginas[-1] else 0) / 3.0
        for it in itens:
            if it.get("papel") == "tese" and float(it.get("fromMs", 0)) <= limite:
                gancho_txt = it.get("texto") or it.get("text")
                break
    if not gancho_txt:
        todas = [t for pg in paginas for t in pg]
        ini = todas[0]["startMs"] if todas else 0
        gancho_txt = " ".join(
            (t.get("text") or "").strip() for t in todas
            if t["startMs"] - ini < DUR_GANCHO_S * 1000
        ).strip()

    return {"fonte": fonte, "captions": caps,
            "legenda_frase": frase_pior, "legenda_chars": chars(paginas[i_pior]),
            "gancho": gancho_txt or None, "avisos": avisos}


def duas_linhas(txt: str) -> dict:
    """Gancho em duas linhas — a regra deles (`ref-A/SKILL.md:190`, 'always two
    lines'), com a quebra no meio em CONTAGEM DE CARACTERES, não de palavras."""
    ps = (txt or "").split()
    if not ps:
        return {"linha1": "", "linha2": ""}
    if len(ps) == 1:
        return {"linha1": ps[0].upper(), "linha2": ""}
    total = sum(len(p) for p in ps)
    acc, corte = 0, 1
    for i, p in enumerate(ps[:-1], start=1):
        acc += len(p)
        corte = i
        if acc >= total / 2:
            break
    return {"linha1": " ".join(ps[:corte]).upper(), "linha2": " ".join(ps[corte:])}


# ─────────────────────────────── cache (§3.2-5) ───────────────────────────────
def chave(estilo: dict, ctx: dict) -> str:
    """sha256(slug + sha do estilo no catálogo + texto + tema + acento + canvas).

    O `sha` do catálogo já cobre a entrada, o arnês e o código de origem (SPEC-15);
    o resto é o que ESTA spec acrescenta ao pixel."""
    h = hashlib.sha256()
    h.update(json.dumps({
        "slug": estilo["slug"],
        "sha": estilo.get("sha"),
        "texto": ctx.get("texto"),
        "tema": ctx.get("tema"),
        "acento": ctx.get("acento"),
        "parametros": ctx.get("parametros") or {},
        "canvas": [ctx["largura"], ctx["altura"], ctx["fps"]],
        "escala": ctx["escala"],
    }, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


# ─────────────────────────────── o render ───────────────────────────────
DRIVER = r"""
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { selectComposition, renderMedia, renderStill } from "@remotion/renderer";

const p = JSON.parse(process.env.SPEC19_PAYLOAD);

const serveUrl = await bundle({
  entryPoint: path.resolve(p.raiz, p.entry),
  outDir: p.bundleDir,
  onProgress: () => {},
});

const feitos = [];
for (const it of p.itens) {
  const comp = await selectComposition({
    serveUrl, id: "PreviewPeca", inputProps: it.props, logLevel: "error",
  });
  await renderMedia({
    composition: comp, serveUrl,
    // 🔴 VP9 OPACO. Nunca pixelFormat yuva420p: VP9/VP8 WebM com alpha derruba o
    // canal em silêncio no libvpx do Homebrew 8.x, que é o nosso. A placa está
    // por baixo — alpha aqui é convite a bug mudo.
    codec: "vp9",
    outputLocation: it.webm, inputProps: it.props,
    scale: p.escala, concurrency: p.concorrencia,
    logLevel: "error", onProgress: () => {},
  });
  await renderStill({
    composition: comp, serveUrl, output: it.png, frame: it.frame,
    inputProps: it.props, scale: p.escala, imageFormat: "png", logLevel: "error",
  });
  feitos.push({ slug: it.slug, frames: comp.durationInFrames, w: comp.width, h: comp.height });
  console.error(`  ✓ ${it.slug} (${comp.durationInFrames} frames @ ${comp.width}x${comp.height})`);
}
console.log(JSON.stringify({ ok: true, feitos }));
"""

CONCORRENCIA = int(os.environ.get("BENCH_GALERIA_CONCORRENCIA", "2"))
BUNDLE_DIR = "node_modules/.cache/spec19-bundle"

_CONTADOR = {"render": 0, "chamadas_node": 0}


def render_lote(itens: list[dict], escala: float) -> list[dict]:
    """UMA chamada de node para N previews: o bundle é feito uma vez, não uma por
    slug. (O gerador do catálogo aprendeu isso; o custo de bundling é ~0,7 s
    quente e domina o lote pequeno.)

    🔴 CAMINHO DE SAÍDA ABSOLUTO, SEMPRE — medido aqui em 2026-08-08. O driver
    roda com `cwd` no projeto Remotion; com caminho relativo, `renderMedia`
    gravou os 2 previews em `tools/remotion-compositor/creators/creator-2/…`, imprimiu
    "✓ legenda-destaque-tema (90 frames)" para os dois e o `galeria.json` saiu com
    "0 no nível 1". Sucesso silencioso completo: log verde, arquivo em lugar
    nenhum. O `assert` abaixo é o dente."""
    if not itens:
        return []
    raiz = dir_remotion()
    for it in itens:
        for campo in ("webm", "png"):
            if not os.path.isabs(it[campo]):
                raise SystemExit(
                    "caminho de saída relativo (%s=%r): o driver roda com cwd em "
                    "%s e gravaria fora da produção." % (campo, it[campo], raiz))
    payload = {"raiz": str(raiz), "entry": "src/index-galeria.tsx",
               "bundleDir": str(raiz / BUNDLE_DIR), "escala": escala,
               "concorrencia": CONCORRENCIA, "itens": itens}
    env = dict(os.environ)
    env["SPEC19_PAYLOAD"] = json.dumps(payload)
    _CONTADOR["chamadas_node"] += 1
    _CONTADOR["render"] += len(itens)
    pr = subprocess.run(["node", "--input-type=module"], input=DRIVER, text=True,
                        capture_output=True, cwd=str(raiz), env=env)
    for ln in (pr.stderr or "").strip().splitlines():
        if ln and "network requests to load fonts" not in ln:
            log(ln)
    if pr.returncode != 0:
        raise SystemExit("driver node falhou (exit %d)" % pr.returncode)
    saida = [l for l in pr.stdout.strip().splitlines() if l.startswith("{")]
    if not saida:
        raise SystemExit("driver node não devolveu JSON")
    return json.loads(saida[-1])["feitos"]


# ─────────────────────────── materialização (§3.5-3) ───────────────────────────
def materializar(estilos: list[dict], destino: Path) -> dict:
    """Nível 0 para dentro da produção por HARDLINK, com cópia de fallback.

    🔴 NUNCA symlink, por duas razões independentes e das duas pontas:
      · `servidor.py:522` (`resolver_sob`) usa `resolve()`, que SEGUE symlink —
        um link apontando para fora da produção vira 403;
      · `remotion-compositor/SKILL.md:69` já registra que "cópia real, symlink
        quebra o bundler".
    `os.link` custa 0 byte e não é seguido por `resolve()`.

    O hardlink só é seguro porque a ponta que escreve cumpre um contrato
    (SPEC-45): `gerar-previews.py` renderiza em temp e troca por `os.replace`,
    criando inode NOVO a cada re-render — este link fica com o conteúdo da
    época do pack. Escrever no caminho final de lá reescreveria ESTE arquivo,
    dentro da produção, em silêncio (A-S1, medido: links=16 no mesmo inode)."""
    destino.mkdir(parents=True, exist_ok=True)
    origem = dir_catalogo()
    n_link = n_copia = 0
    for e in estilos:
        prev = e.get("preview") or {}
        for campo in ("webm", "poster"):
            rel = prev.get(campo)
            if not rel:
                continue
            src = origem / rel
            dst = destino / Path(rel).name
            if not src.is_file():
                continue
            if dst.exists():
                try:
                    if dst.stat().st_ino == src.stat().st_ino:
                        n_link += 1
                        continue
                except OSError:
                    pass
                dst.unlink()
            try:
                os.link(src, dst)
                n_link += 1
            except OSError:
                shutil.copy2(src, dst)
                n_copia += 1
    return {"hardlink": n_link, "copia": n_copia}


# ─────────────────────────────── galeria.json ───────────────────────────────
def _entrada(e: dict, ctx: dict, padrao: bool, nivel1: dict | None) -> dict:
    prev = e.get("preview") or {}
    saida = {
        "slug": e["slug"], "nome": e["nome"], "oQuePinta": e["oQuePinta"],
        "estado": e["estado"], "padrao": padrao,
        "acento": e.get("acento"),
        "parametros": e.get("parametros") or [],
        "preview": None,
    }
    if e["estado"] == "candidato":
        saida["bloqueio"] = e.get("bloqueio") or ""
        return saida
    if nivel1:
        saida["preview"] = {
            "nivel": 1, "webm": "peca/%s.webm" % e["slug"],
            "poster": "peca/%s.png" % e["slug"],
            "w": nivel1["w"], "h": nivel1["h"], "durS": prev.get("durS"),
            "chave": nivel1["chave"],
        }
    elif prev.get("webm"):
        saida["preview"] = {
            "nivel": 0, "webm": "previews/%s" % Path(prev["webm"]).name,
            "poster": "previews/%s" % Path(prev["poster"]).name,
            "w": prev.get("w"), "h": prev.get("h"), "durS": prev.get("durS"),
        }
    if e["grupo"] == "gramatica":
        saida["aplica"] = GRAMATICA_APLICA.get(e["slug"], {"perfil_campo": None, "valor": None})
    return saida


def gerar(dir_prod: str, somente_defaults: bool = False, grupo: str | None = None,
          gancho: str | None = None, acento: str | None = None,
          tema: str | None = None, forcar: bool = False,
          sem_render: bool = False, estilo: str | None = None) -> str:
    d = Path(dir_prod).resolve()
    if not d.is_dir():
        sys.exit("diretório de produção inexistente: %s" % dir_prod)
    cat = catalogo()
    perf, fonte_perfil = perfil_da_peca(dir_prod)
    nome_real = perf.get("nome") or "reels"
    nome_perfil, aviso_vocab = vocabulario_de(nome_real, cat)
    W, H, FPS = canvas_de(perf)
    escala = LARGURA_CARD / float(W)

    base = d / ".preview" / "estilos"
    base.mkdir(parents=True, exist_ok=True)

    avisos: list[str] = []
    if fonte_perfil == "fallback":
        avisos.append("sem perfil.json nesta produção: formato e zonas vêm do "
                      "FALLBACK_REELS (perfil.py). Rode `perfil.py resolver <dir>`.")
    if aviso_vocab:
        avisos.append(aviso_vocab)

    # tema e acento: o tema default é o primeiro do perfil, o acento nasce dele
    temas = [e for e in cat["estilos"]
             if e["grupo"] == "tema" and nome_perfil in (e.get("perfis") or [])]
    tema_default = tema or next(
        (e["slug"] for e in temas if nome_perfil in (e.get("defaultDe") or [])),
        temas[0]["slug"] if temas else None)
    acento_default = acento or _acento_do_tema(cat, tema_default)
    if acento_default is None:
        # Mesma régua do aviso de legenda: o que o creator precisa saber é que o
        # campo de cor está vazio de propósito e que a escolha é dele. "um tema é
        # um conjunto de cores, não um parâmetro" é a razão, e ela vive na §4.1
        # deste arquivo — não na tela de quem está escolhendo.
        avisos.append(
            "o tema %r não traz uma cor de destaque pronta: o campo de cor abre "
            "VAZIO e a escolha é sua, na tela." % tema_default)

    dur = float(next((e["preview"]["durS"] for e in cat["estilos"]
                      if e["grupo"] == "legenda" and e.get("preview")), 3.0))
    txt = texto_da_peca(dir_prod, perf, dur, gancho)
    avisos.extend(txt.get("avisos") or [])

    por_grupo = oferecidos(cat, nome_perfil, grupo)
    cache_p = base / ".cache.json"
    cache = _ler_json(cache_p, {}) or {}

    # ── quem ganha nível 1
    ctx_comum = {"largura": W, "altura": H, "fps": FPS, "escala": escala,
                 "tema": tema_default, "acento": acento_default}
    alvos: list[tuple[dict, dict, str]] = []
    if txt["fonte"] != "amostra" and not sem_render:
        for g in GRUPOS_NIVEL1:
            for e in por_grupo.get(g, []):
                if e["estado"] != "pronto":
                    continue
                if somente_defaults and nome_perfil not in (e.get("defaultDe") or []):
                    continue
                conteudo = (txt["captions"] if g == "legenda" else txt["gancho"])
                if not conteudo:
                    continue
                ctx = dict(ctx_comum, texto=json.dumps(conteudo, ensure_ascii=False))
                k = chave(e, ctx)
                png = base / "peca" / ("%s.png" % e["slug"])
                webm = base / "peca" / ("%s.webm" % e["slug"])
                vale = (cache.get(e["slug"]) == k and png.is_file() and webm.is_file()
                        and dims_png(png) == (dim_escalada(W, escala), dim_escalada(H, escala)))
                if forcar or not vale:
                    alvos.append((e, ctx, k))

    (base / "peca").mkdir(parents=True, exist_ok=True)
    if alvos:
        itens = []
        for e, ctx, k in alvos:
            props: dict = {"slug": e["slug"], "acento": acento_default}
            if e["grupo"] == "legenda":
                props["captions"] = txt["captions"]
            else:
                props["gancho"] = duas_linhas(txt["gancho"] or "")
            props = canvas_nos_props(props, W, H, FPS)
            itens.append({
                "slug": e["slug"], "props": props,
                "frame": int((e["preview"] or {}).get("frameCartao") or 0),
                "webm": str(base / "peca" / ("%s.webm" % e["slug"])),
                "png": str(base / "peca" / ("%s.png" % e["slug"])),
            })
        log("nível 1: %d a renderizar (%d no catálogo, perfil %s)"
            % (len(itens), len(cat["estilos"]), nome_perfil))
        render_lote(itens, escala)
        # 🔴 O DENTE: o "✓" do driver diz que o render RODOU, não que o arquivo
        # está onde deveria. Só entra no cache quem tem os dois arquivos no
        # disco, no tamanho certo — medido do PNG, não deduzido do `--scale`.
        alvo_dim = (dim_escalada(W, escala), dim_escalada(H, escala))
        for it in itens:
            slug = it["slug"]
            png, webm = Path(it["png"]), Path(it["webm"])
            if not (png.is_file() and webm.is_file()):
                raise SystemExit(
                    "%s: o driver disse ✓ e o arquivo não existe (%s / %s). "
                    "Render que 'deu certo' sem produzir arquivo é o defeito mais "
                    "caro deste repo." % (slug, png, webm))
            d_png = dims_png(png)
            if d_png != alvo_dim:
                raise SystemExit(
                    "%s: poster %s contra o canvas esperado %s — o canvas que "
                    "viajou nos props (%dx%d@%s) não chegou ao render."
                    % (slug, d_png, alvo_dim, W, H, FPS))
        for e, ctx, k in alvos:
            cache[e["slug"]] = k
        cache_p.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n")
    else:
        # 🔴 "0 a renderizar" tem três causas diferentes e uma delas é defeito.
        # Um log que não as distingue é o portão verde sem prova de dentes.
        # (A quarta — "canvas do snapshot global ≠ canvas da peça" — deixou de
        # existir quando o canvas passou a viajar nos props, 2026-08-10.)
        if sem_render:
            motivo = "--sem-render"
        elif txt["fonte"] == "amostra":
            motivo = "sem texto da peça (partitura/captions ausentes)"
        else:
            motivo = "cache válido"
        log("nível 1: 0 a renderizar (%s)" % motivo)

    # ── materializa o nível 0 do subconjunto oferecido
    prontos = [e for g in por_grupo.values() for e in g if e["estado"] == "pronto"]
    mat = materializar(prontos, base / "previews")

    # ── monta o JSON
    grupos = []
    for gid in ORDEM_GRUPOS:
        lista = por_grupo.get(gid, [])
        entradas = []
        vistos_padrao = False
        for e in lista:
            padrao = (not vistos_padrao and gid != "grafismo"
                      and nome_perfil in (e.get("defaultDe") or []))
            if padrao:
                vistos_padrao = True
            n1 = None
            if e["estado"] == "pronto" and cache.get(e["slug"]):
                png = base / "peca" / ("%s.png" % e["slug"])
                dm = dims_png(png)
                if dm:
                    n1 = {"w": dm[0], "h": dm[1], "chave": cache[e["slug"]]}
            entradas.append(_entrada(e, ctx_comum, padrao, n1))
        grupos.append({"id": gid, "titulo": TITULOS[gid],
                       "seletor": SELETOR.get(gid, "unico"), "estilos": entradas})

    interruptores = _interruptores(nome_perfil)
    direcoes_edicao = _direcoes_edicao()
    vigente = _ler_json(d / ".preview" / "estilo-vigente.json")
    semente = _semente_do_estilo(d, estilo)
    do_plano = _grafismos_do_plano(d, grupos)
    aprendizado = _aprendizado(estilo)
    propostas = _propostas(grupos, semente, vigente, tema_default, acento_default,
                           do_plano)

    obj = {
        "contrato": CONTRATO,
        "gerado_em": _agora(),
        "gerador": GERADOR,
        "gerador_versao": GERADOR_VERSAO,
        "catalogo_gerado_em": cat.get("gerado_em"),
        "producao": {"slug": d.resolve().name, "creator": _creator_de(d)},
        # `nome` é o perfil RESOLVIDO (a verdade); `vocabulario` é o nome que
        # filtrou o catálogo. Iguais no caminho normal; diferentes no fallback —
        # e aí a tela mostra os dois em vez de esconder a diferença.
        "perfil": {"nome": nome_real, "vocabulario": nome_perfil,
                   "fonte": fonte_perfil,
                   "largura": W, "altura": H, "fps": FPS,
                   "zonas_ui": perf.get("zonas_ui")},
        "texto": {"fonte": txt["fonte"], "legenda_frase": txt["legenda_frase"],
                  "legenda_chars": txt["legenda_chars"],
                  "gancho": txt["gancho"]},
        "tema_default": tema_default,
        "acento_default": acento_default,
        "grupos": grupos,
        # 🔴 A GALERIA ABRE COMO PROPOSTA (SPEC-49/H49-1). `grupos` continua
        # inteiro e é a fonte de verdade do vocabulário; `propostas` é uma LEITURA
        # dele — a tela mostra a proposta primeiro e os grupos como ajuste fino.
        # Galeria antiga (sem este campo) continua desenhando como antes: a tela
        # degrada, não quebra.
        "propostas": propostas,
        "grafismos_do_plano": do_plano,
        # H49-4: o loop sinais→propor→promover deixa de ser só ritual de CLI.
        # `null` quando não há biblioteca, estilo ou base — ausência é silêncio.
        "aprendizado": aprendizado,
        # A pergunta de acabamento vem antes dos detalhes visuais. Não existe
        # escolha implícita: a ordem desta lista é só a ordem dos três cards.
        "direcoes_edicao": direcoes_edicao,
        "interruptores": interruptores,
        "vigente": vigente,
        "semente": semente,
        "pendentes": 0,
        "avisos": avisos,
        "_materializacao": mat,
    }
    erros = validar_galeria(obj)
    if erros:
        for x in erros:
            log("  ✗ %s" % x)
        raise SystemExit("galeria.json inválido (%d): não gravei nada" % len(erros))
    alvo = base / "galeria.json"
    tmp = alvo.with_name(alvo.name + ".%d.parcial" % os.getpid())
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, alvo)
    n1 = sum(1 for g in grupos for e in g["estilos"]
             if (e.get("preview") or {}).get("nivel") == 1)
    log("galeria: %d grupos · %d estilos oferecidos · %d no nível 1 · "
        "%d hardlink + %d cópia · %d render(s) nesta rodada"
        % (len(grupos), sum(len(g["estilos"]) for g in grupos), n1,
           mat["hardlink"], mat["copia"], _CONTADOR["render"]))
    return str(alvo)


# ═══════════ O ESTILO APRENDE, COMO PRODUTO (SPEC-49 / H49-4) ════════════════
#
# Decisão do dono: "quanto mais usa, mais entende os gostos". O loop
# sinais→propor→promover da SPEC-24/41 já colhe TODA escolha da galeria — e
# parava num ritual de linha de comando que só nós rodamos. Aqui ele vira
# superfície: quando o `propor` tem base (as 4 guardas dele passam, e a primeira
# exige 3 PRODUÇÕES distintas), a galeria oferece.
#
# 🔴 O QUE ESTE CAMPO NÃO FAZ: promover. Ele carrega a PROPOSTA que o `propor`
# calculou, e nada mais. A regra vigente do dono é dele: propor exige 3
# produções, promover é decisão humana. A tela pede confirmação e o `promover`
# continua sendo o único que escreve versão nova — com `--confirmar`.
def _aprendizado(ref: str | None):
    if not ref:
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import estilo as _estilo                                    # noqa: PLC0415
        propostas, texto = _estilo.propor(ref)
    except Exception as exc:                                        # noqa: BLE001
        log("  aviso: `propor` não rodou para %r (%s) — a galeria abre sem a "
            "oferta de aprendizado" % (ref, exc))
        return None
    if not propostas:
        return None
    itens = []
    for pr in propostas[:3]:
        itens.append({"path": pr["path"], "de": pr.get("de"), "para": pr.get("para"),
                      "n_producoes": pr.get("n_producoes"),
                      "motivo": pr.get("motivo"), "sinais": pr.get("sinais") or []})
    return {"estilo": ref, "propostas": itens,
            "comando": "estilo.py promover %s --confirmar --so %s"
                       % (ref, ",".join(i["path"] for i in itens)),
            "resumo_do_propor": (texto or "").splitlines()[:4]}


# ═════════════════════════ A PROPOSTA (SPEC-49 / H49-1) ══════════════════════
#
# 🔴 POR QUE A GALERIA DEIXA DE SER FORMULÁRIO. Diagnóstico do dono sobre a tela
# de hoje, com 8 prints da produção reels-01 (2026-08-12): "MUITO poluído — um
# monte de template que a maioria não vai utilizar; os motions de teste eram
# prova de conceito, os reais são criados POR CASO; a cor está escondida e não
# reflete nos previews". A tela oferecia ~40 cards em 6 seções e pedia que o
# creator montasse o look folha por folha — trabalho de quem edita, não de quem
# aprova.
#
# A direção escolhida por ele: **1 look completo montado para ESTA peça, mais 2
# variações completas**. As seções viram "ajustes finos", colapsadas.
#
# A fonte de cada folha da proposta, na ordem, é a MESMA cadeia que o
# `estilo.py resolver` já usa — e a procedência viaja em linguagem de creator,
# porque é ela que aparece na tela:
#
#   vigente   → "já escolhido nesta peça"      (alguém escolheu aqui)
#   semente   → "do seu estilo"                 (biblioteca do usuário, SPEC-24)
#   padrao    → "padrão da casa para este perfil" (o `defaultDe` do catálogo)
#   catálogo  → "primeira opção do catálogo"    (o resto, determinístico)
#
# NADA aqui inventa opção: toda folha da proposta é um slug que já está em
# `grupos`, e o `seletor`/`vocabulario` continua sendo a única fonte de verdade.
# Se a proposta some (galeria antiga, grupo vazio), a tela desenha as seções como
# antes — degradação honesta, não erro.
FRASE_FONTE = {
    "vigente": "já escolhido nesta peça",
    "semente": "do seu estilo",
    "medido": "medido das suas referências",
    "padrao": "padrão da casa para este perfil",
    "catalogo": "primeira opção do catálogo",
}


def _escolhiveis(grupo):
    """Os estilos de um grupo que o creator PODE escolher (candidato não conta)."""
    return [e for e in grupo["estilos"] if e.get("estado") != "candidato"]


def _folha(grupo, semente, vigente, ja_usados):
    """(slug, fonte) da folha deste grupo, na ordem da cadeia. (None, None) se vazio."""
    lista = _escolhiveis(grupo)
    if not lista:
        return None, None
    gid = grupo["id"]
    est_vig = ((vigente or {}).get("estilo") or {})
    por_slug = {e["slug"]: e for e in lista}
    tentativas = [
        (est_vig.get(gid), "vigente"),
        (((semente or {}).get("estilo") or {}).get(gid),
         "medido" if (semente or {}).get("versao") else "semente"),
    ]
    for slug, fonte in tentativas:
        if slug and slug in por_slug:
            return slug, fonte
    padrao = next((e["slug"] for e in lista if e.get("padrao")), None)
    if padrao:
        return padrao, "padrao"
    # a variação pega o próximo ainda não usado; a proposta pega o primeiro
    for e in lista:
        if e["slug"] not in ja_usados:
            return e["slug"], "catalogo"
    return lista[0]["slug"], "catalogo"


def _propostas(grupos, semente, vigente, tema_default, acento_default, do_plano):
    """1 proposta + até 2 variações. Cada uma é um look COMPLETO e escolhível."""
    por_id = {g["id"]: g for g in grupos}
    grupos_folha = [gid for gid in ("gramatica", "tema", "gancho", "legenda")
                    if gid in por_id and _escolhiveis(por_id[gid])]
    if not grupos_folha:
        return []

    def montar(rotulo, titulo, porque, saltar):
        """`saltar` = quantas opções pular no grupo que dá a variação."""
        escolhas, proc, usados = {}, {}, set()
        for gid in grupos_folha:
            slug, fonte = _folha(por_id[gid], semente, vigente, usados)
            if slug is None:
                continue
            if gid == saltar:
                lista = [e["slug"] for e in _escolhiveis(por_id[gid])]
                if len(lista) > 1:
                    i = (lista.index(slug) + 1) % len(lista)
                    slug, fonte = lista[i], "catalogo"
            escolhas[gid] = slug
            proc[gid] = {"fonte": fonte, "diz": FRASE_FONTE[fonte]}
            usados.add(slug)
        # o preview que representa a proposta: a LEGENDA, quando existe (é a
        # folha que o creator mais vê); senão o gancho; senão o tema.
        cartao = None
        for gid in ("legenda", "gancho", "tema", "gramatica"):
            slug = escolhas.get(gid)
            if not slug:
                continue
            e = next((x for x in por_id[gid]["estilos"] if x["slug"] == slug), None)
            if e and e.get("preview"):
                cartao = {"grupo": gid, "slug": slug, "preview": e["preview"]}
                break
        return {"id": rotulo, "titulo": titulo, "porque": porque,
                "escolhas": escolhas, "procedencia": proc,
                "grafismos": list((do_plano or {}).get("slugs") or []),
                "acento": acento_default, "tema_default": tema_default,
                "cartao": cartao}

    # o grupo que gera as variações: o primeiro com mais de uma opção, na ordem
    # de impacto visual (legenda → tema → gancho → gramática)
    candidatos = [gid for gid in ("legenda", "tema", "gancho", "gramatica")
                  if gid in por_id and len(_escolhiveis(por_id[gid])) > 1]
    fonte_vig = "vigente" if ((vigente or {}).get("estilo")) else (
        "semente" if semente else "padrao")
    props = [montar("proposta", "A proposta para esta peça",
                    {"vigente": "monta o que já está aplicado aqui",
                     "semente": "monta o seu estilo salvo",
                     "medido": "monta o estilo medido das suas referências",
                     "padrao": "monta o padrão da casa para este perfil",
                     }.get(fonte_vig, "monta o padrão da casa"), None)]
    for k, gid in enumerate(candidatos[:2]):
        props.append(montar("variacao-%d" % (k + 1),
                            "Variação %d — outra %s" % (k + 1, TITULOS[gid].lower()),
                            "mesma proposta, trocando só %s" % TITULOS[gid].lower(),
                            gid))
    # variação que repete a proposta não é variação
    vistos, saida = set(), []
    for p in props:
        chave = json.dumps(p["escolhas"], sort_keys=True)
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(p)
    return saida


# ═══════════════════ OS GRAFISMOS VÊM DO PLANO (SPEC-49 / H49-2) ══════════════
# Decisão do dono: "os motions de cada peça nascem do PLANO-EDICAO, por beat, sob
# medida. A seção mostra SÓ o que o plano desta peça pede; o catálogo inteiro fica
# atrás de `ver todos`." A tela oferecia 16 grafismos de catálogo como se fossem
# um menu — e nenhum deles era o que aquela peça precisava.
#
# A fonte é medida, nesta ordem, e SEMPRE declarada em `fonte`:
#   1. `PLANO-EDICAO*.md` da produção — os slugs do catálogo citados nele
#   2. `overlays.json` — o que a peça de fato construiu (campo `estilo`/`slug`)
#   3. nada → `fonte: null`, `slugs: []`, e a tela diz que o plano não nomeia
#      grafismo nenhum (em vez de oferecer o catálogo como se fosse proposta)
def _grafismos_do_plano(d: Path, grupos):
    grupo = next((g for g in grupos if g["id"] == "grafismo"), None)
    conhecidos = [e["slug"] for e in (grupo or {}).get("estilos", [])]
    if not conhecidos:
        return {"fonte": None, "slugs": [], "porque": "esta peça não oferece grafismo"}
    planos = sorted(d.glob("PLANO-EDICAO*.md")) + sorted(d.glob("plano-edicao*.md"))
    for p in planos:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        achados = [s for s in conhecidos if s in txt]
        if achados:
            return {"fonte": p.name, "slugs": achados,
                    "porque": "o plano desta peça nomeia %d grafismo(s)" % len(achados)}
    ov = _ler_json(d / "overlays.json") or _ler_json(
        d / "remotion" / "overlays.json")
    if isinstance(ov, (list, dict)):
        bruto = json.dumps(ov, ensure_ascii=False)
        achados = [s for s in conhecidos if s in bruto]
        if achados:
            return {"fonte": "overlays.json", "slugs": achados,
                    "porque": "o que a peça já construiu (o plano não nomeou slug)"}
    return {"fonte": None, "slugs": [],
            "porque": "o plano desta peça não nomeia grafismo — o catálogo fica "
                      "atrás de `ver todos`"}


def _semente_do_estilo(d: Path, ref: str | None):
    """A PRÉ-SELEÇÃO da galeria a partir de um estilo da biblioteca do usuário
    (SPEC-24) — o último metro da ponte da SPEC-41.

    Sem isto, um estilo extraído de N referências chegava até a biblioteca e
    parava lá: a galeria só sabia ler `vigente`, que é escrito quando alguém já
    escolheu NESTA peça. O creator via 38 cards sem marca nenhuma, e o trabalho
    de extrair o estilo não aparecia na única tela onde ele escolhe.

    🔴 `semente` NÃO é `vigente`, e a diferença é o contrato inteiro:
      · `vigente`  = alguém já escolheu para esta peça, e trocar significa REFAZER
                     a Fase 2 (é o que acende o botão âmbar);
      · `semente`  = o estilo do usuário sugere; ninguém escolheu nada ainda, e
                     confirmar é a PRIMEIRA escolha, não uma troca.
    Semear em `vigente` faria toda peça nova nascer dizendo "trocando um estilo já
    aplicado" e mandaria refazer uma Fase 2 que nunca foi feita.

    Ausência de biblioteca é SILÊNCIO: um cliente sem `estilos/` recebe `null`."""
    if not ref:
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import estilo as _estilo                                    # noqa: PLC0415
        e, _meta = _estilo.resolver_estilo(ref)
    except Exception as exc:                                        # noqa: BLE001
        log("  aviso: estilo %r não resolveu (%s) — a galeria abre sem pré-seleção"
            % (ref, exc))
        return None
    picks = dict(e.get("picks") or {})
    grafismos = sorted(s for s, lig in (e.get("grafismo") or {}).items() if lig)
    if not picks and not grafismos:
        return None
    return {"origem": ref,
            "versao": (e.get("_meta") or {}).get("versao") or e.get("versao"),
            "estilo": dict(picks, grafismos=grafismos)}


def _creator_de(d: Path):
    """Informativo e OPACO. Nenhum campo do contrato tem semântica que dependa
    dele — e o produto não tem `creators/` nenhum."""
    partes = d.resolve().parts
    if "producao" in partes:
        i = partes.index("producao")
        if i >= 1:
            return partes[i - 1]
    return None


def _acento_do_tema(cat: dict, tema_slug: str | None):
    """A cor de destaque nasce do tema (`themes.ts:7`) — quando o catálogo a
    carrega.

    🔴 HOJE ELE NÃO CARREGA, e isto é medido, não suposto: as 5 entradas de
    `tema` têm `parametros: []` por decisão explícita da SPEC-15 (*"um tema é um
    pacote que se escolhe, não uma paleta que se afina no card"*,
    `estilos.ts:106-112`), e `themes.ts` é TypeScript — que este repo proíbe
    parsear em Python (`gerar-previews.py:15-21`). Resultado: o `acento_default`
    da §4.1 não é derivável sem reabrir a decisão de outra spec.

    O que se faz aqui é o contrário de adivinhar: devolve `None` e o chamador
    NOMEIA a ausência em `avisos`. Uma cor inventada seria pior que campo
    vazio — ela apareceria no digest como se o usuário a tivesse escolhido."""
    if not tema_slug:
        return None
    for e in cat["estilos"]:
        if e["slug"] == tema_slug:
            for p in e.get("parametros") or []:
                if p.get("tipo") == "cor":
                    return p.get("padrao")
    return None


def _config_interruptores() -> dict:
    p = Path(__file__).resolve().parents[1] / "preview" / "app" / "galeria" / "interruptores.json"
    return _ler_json(p, {}) or {}


def _interruptores(perfil_nome: str) -> list[dict]:
    obj = _config_interruptores()
    itens = obj.get("itens") or []
    return [{"id": i["id"], "nome": i["nome"], "padrao": bool(i.get("padrao")),
             "aplica": i.get("aplica", ""), "tecnico": i.get("tecnico", "")}
            for i in itens if perfil_nome in (i.get("perfis") or [])]


def _direcoes_edicao() -> list[dict]:
    """Os três acabamentos que abrem a aba Look, copiados como dado.

    A tela não mantém uma segunda lista. Assim nome, descrição e defaults de
    densidade/SFX viajam juntos do arquivo versionado até o `galeria.json`.
    """
    obj = _config_interruptores()
    campos = ("modo", "nome", "descricao", "densidade", "sfx")
    return [{k: d.get(k) for k in campos} for d in obj.get("direcoes_edicao") or []]


# ─────────────────────────────── validação ───────────────────────────────
def validar_galeria(obj: dict) -> list[str]:
    """As regras do fim da §4.1. Um `galeria.json` inválido não chega ao disco."""
    e: list[str] = []
    if obj.get("contrato") != CONTRATO:
        e.append("contrato %r != %r" % (obj.get("contrato"), CONTRATO))
    for g in obj.get("grupos") or []:
        if not g.get("id"):
            e.append("grupo sem id")
        padroes = [x for x in g["estilos"] if x.get("padrao")]
        if g.get("seletor") == "unico" and len(padroes) > 1:
            e.append("%s: %d padrões num grupo de seleção única (%s)"
                     % (g["id"], len(padroes), [x["slug"] for x in padroes]))
        for x in g["estilos"]:
            prev = x.get("preview")
            if prev is None and x.get("estado") != "candidato":
                e.append("%s: sem preview e não é candidato" % x["slug"])
            if x.get("estado") == "candidato" and not x.get("bloqueio"):
                e.append("%s: candidato sem bloqueio" % x["slug"])
            if prev:
                if prev.get("nivel") not in (0, 1):
                    e.append("%s: nivel %r fora de {0,1}" % (x["slug"], prev.get("nivel")))
                for campo in ("webm", "poster"):
                    v = prev.get(campo) or ""
                    if v.startswith("/") or ".." in v:
                        e.append("%s: caminho absoluto ou com .. em %s: %r"
                                 % (x["slug"], campo, v))
            ac = x.get("acento")
            if ac is not None and (not isinstance(ac, dict) or not ac.get("param")):
                e.append("%s: acento tem que ser null ou {param}, veio %r" % (x["slug"], ac))
    e.extend(validar_direcoes_edicao(obj))
    e.extend(validar_propostas(obj))
    return e


def validar_direcoes_edicao(obj: dict) -> list[str]:
    """A galeria nova sempre oferece exatamente as três decisões de acabamento."""
    e: list[str] = []
    ds = obj.get("direcoes_edicao")
    if not isinstance(ds, list):
        return ["direcoes_edicao: esperado list"]
    modos = [d.get("modo") for d in ds if isinstance(d, dict)]
    esperados = {"essencial", "animada", "surpresa"}
    modos_texto = [m for m in modos if isinstance(m, str)]
    if len(ds) != 3 or len(modos) != 3 or set(modos_texto) != esperados:
        e.append("direcoes_edicao: esperado exatamente essencial, animada e surpresa; veio %r"
                 % modos)
    densidades = ("leve", "equilibrada", "alta")
    sfxs = ("automatico", "sem-sfx")
    campos = {"modo", "nome", "descricao", "densidade", "sfx"}
    for i, d in enumerate(ds):
        if not isinstance(d, dict):
            e.append("direcoes_edicao[%d]: esperado dict" % i)
            continue
        faltam = campos - set(d)
        sobram = set(d) - campos
        if faltam:
            e.append("direcoes_edicao[%d]: faltam %s" % (i, sorted(faltam)))
        if sobram:
            e.append("direcoes_edicao[%d]: campos desconhecidos %s" % (i, sorted(sobram)))
        if not isinstance(d.get("nome"), str) or not d.get("nome"):
            e.append("direcoes_edicao[%d].nome: esperado texto não vazio" % i)
        if not isinstance(d.get("descricao"), str) or not d.get("descricao"):
            e.append("direcoes_edicao[%d].descricao: esperado texto não vazio" % i)
        if d.get("densidade") not in densidades:
            e.append("direcoes_edicao[%d].densidade %r fora de %s"
                     % (i, d.get("densidade"), sorted(densidades)))
        if d.get("sfx") not in sfxs:
            e.append("direcoes_edicao[%d].sfx %r fora de %s"
                     % (i, d.get("sfx"), sorted(sfxs)))
        if d.get("modo") == "essencial":
            if d.get("densidade") != "leve":
                e.append("direção essencial precisa começar com densidade leve")
            if d.get("sfx") != "sem-sfx":
                e.append("direção essencial precisa começar sem-sfx")
        elif d.get("modo") in ("animada", "surpresa") \
                and d.get("sfx") != "automatico":
            e.append("direção %s precisa começar com SFX automático" % d.get("modo"))
    return e


def validar_propostas(obj: dict) -> list[str]:
    """Só os blocos da SPEC-49. Separado de `validar_galeria` porque a FIXTURE
    zera `preview` de propósito (para exercitar a placa de ausência) e por isso
    não passa na validação inteira — mas as propostas dela têm que valer."""
    e: list[str] = []
    # 🔴 A PROPOSTA NÃO PODE INVENTAR SLUG (SPEC-49/H49-1). Ela é uma LEITURA de
    # `grupos`; um slug que não está lá chegaria à tela como opção e morreria na
    # Fase 2, quando o agente fosse montar o componente que não existe. É a mesma
    # regra que o `escolha-estilo.py` já cobra do payload, um passo antes.
    por_grupo = {g.get("id"): {x["slug"] for x in g.get("estilos") or []}
                 for g in obj.get("grupos") or []}
    for prop in obj.get("propostas") or []:
        if not prop.get("id") or not prop.get("titulo"):
            e.append("proposta sem id/titulo: %r" % (prop.get("id") or prop))
        for gid, slug in (prop.get("escolhas") or {}).items():
            if gid not in por_grupo:
                e.append("proposta %s: grupo %r não existe" % (prop["id"], gid))
            elif slug not in por_grupo[gid]:
                e.append("proposta %s: slug %r não está no grupo %s"
                         % (prop["id"], slug, gid))
        for slug in prop.get("grafismos") or []:
            if slug not in por_grupo.get("grafismo", set()):
                e.append("proposta %s: grafismo %r não está no grupo grafismo"
                         % (prop["id"], slug))
    dp = obj.get("grafismos_do_plano")
    if dp is not None:
        if not isinstance(dp, dict) or "fonte" not in dp or "slugs" not in dp:
            e.append("grafismos_do_plano tem que ser {fonte, slugs, porque}")
        else:
            for slug in dp["slugs"]:
                if slug not in por_grupo.get("grafismo", set()):
                    e.append("grafismos_do_plano: %r não está no grupo grafismo" % slug)
    return e


# ───────────────────────── pacote servível (§3.4, medido) ─────────────────────
def _copiar_tela(dst: Path) -> None:
    app = Path(__file__).resolve().parents[1] / "preview" / "app" / "galeria"
    dst.mkdir(parents=True, exist_ok=True)
    for nome in ("galeria.html", "galeria.js", "galeria.css", "interruptores.json",
                 "README.md"):
        f = app / nome
        if f.is_file():
            shutil.copy2(f, dst / nome)


def pacote(dir_prod: str, destino: str) -> str:
    """Monta um dir SERVÍVEL com a tela + o `galeria.json` + as mídias.

    🔴 POR QUE ISTO EXISTE. A §3.4 previa que a tela fizesse **um** fetch para
    `../../media/.preview/estilos/galeria.json`. Medido em 2026-08-08 contra o
    servidor da SPEC-17 **já entregue**: a rota `/media/` recusa tudo que está
    sob `.preview/` (`preview/servidor.py:872-874`, 403 `{"erro":"fora da
    raiz"}`), enquanto o mesmo arquivo fora do `.preview/` responde 200 e
    `/app/…` responde 200.

    `servidor.py` é da SPEC-17 e está fora da §5 desta spec — então em vez de
    editá-lo, o gerador monta o vizinho que a tela busca:

        previews-peca.py <dir> --pacote <dst>
        servidor.py servir --dir <dir> --app <dst>
        → <url>app/galeria/galeria.html

    O pacote é descartável; os artefatos canônicos continuam em
    `<dir>/.preview/estilos/`."""
    d = Path(dir_prod).resolve()
    origem = d / ".preview" / "estilos"
    gal = origem / "galeria.json"
    if not gal.is_file():
        sys.exit("sem %s — rode `previews-peca.py %s` antes de empacotar"
                 % (gal, dir_prod))
    dst = Path(destino).resolve() / "galeria"
    _copiar_tela(dst)
    shutil.copy2(gal, dst / "galeria.json")
    n = 0
    for sub in ("previews", "peca"):
        s, t = origem / sub, dst / sub
        if not s.is_dir():
            continue
        t.mkdir(parents=True, exist_ok=True)
        for f in s.iterdir():
            if f.is_file():
                alvo = t / f.name
                if alvo.exists():
                    alvo.unlink()
                try:
                    os.link(f, alvo)
                except OSError:
                    shutil.copy2(f, alvo)
                n += 1
    log("pacote: tela + galeria.json + %d mídia(s) em %s\n"
        "  sirva com: servidor.py servir --dir %s --app %s\n"
        "  abre em:   <url>app/galeria/galeria.html" % (n, dst, dir_prod, dst.parent))
    return str(dst / "galeria.html")


# ─────────────────────────────── fixture (§8.4) ───────────────────────────────
def fixture(destino: str) -> str:
    """Dir autocontido: a tela + um `galeria.json` de exemplo com um candidato,
    um grupo de UMA opção e um grupo VAZIO. É como a tela é testada antes de o
    servidor existir — e é o que prova que grupo vazio não esconde o portão.

    🔴 A FIXTURE MENTIA SOBRE O QUE EXERCITAVA (achado A-F6, 2026-08-11). O
    `_nota` dela dizia "os caminhos de preview apontam para arquivos que a
    fixture não tem: é isso que exercita o card sem mídia". Não era: um card com
    `preview: {…}` cujo arquivo não existe renderiza um `<img>` QUEBRADO, não a
    placa "prévia ainda não renderizada" — a placa honesta só nasce de
    `preview: null` (`galeria.js`, `caixaDe`). O efeito medido eram 9 requisições
    404 no console e ícones de imagem quebrada, exatamente a confusão que o
    próprio comentário da `caixaDe` existe para impedir ("uma caixa vazia é
    indistinguível de um card que falhou ao carregar").

    O conserto exercita as DUAS coisas de verdade: o preview de nível 0 vem do
    catálogo por cópia (o arquivo existe, o card pinta), e o de nível 1 — que
    numa fixture não tem como existir, porque não há peça renderizada — vira
    `preview: null` e mostra a placa. Nada disso pesa no pacote: a mídia é
    materializada no DESTINO, que é descartável."""
    dst = Path(destino)
    _copiar_tela(dst)
    ex = SCRIPTS / "tests" / "fixtures" / "galeria-exemplo.json"
    if not ex.is_file():
        log("fixture em %s — sem galeria-exemplo.json, só a tela" % dst)
        return str(dst / "galeria.json")
    obj = json.loads(ex.read_text(encoding="utf-8"))
    origem = dir_catalogo()
    n_mid = n_placa = 0
    for g in obj.get("grupos") or []:
        for e in g.get("estilos") or []:
            prev = e.get("preview") or {}
            rels = [prev.get(c) for c in ("webm", "poster") if prev.get(c)]
            # só sobrevive o preview cujos DOIS arquivos o catálogo tem. O
            # caminho é relativo à RAIZ do catálogo (`previews/<slug>.webm`),
            # como em `materializar()` — `peca/<slug>.webm` não existe lá, e é
            # por isso que o nível 1 cai na placa.
            fontes = {r: origem / r for r in rels}
            if rels and all(s.is_file() for s in fontes.values()):
                for rel, src in fontes.items():
                    alvo = dst / rel
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, alvo)
                n_mid += 1
            elif e.get("preview") is not None:
                e["preview"] = None
                n_placa += 1
    # 🔴 A FIXTURE TAMBÉM TEM QUE MOSTRAR A PROPOSTA (SPEC-49). Ela é a única
    # tela que roda sem servidor e sem produção — se ela desenhar a galeria
    # ANTIGA, quem for conferir o conserto olha a tela errada. As propostas saem
    # das MESMAS funções da geração real, sobre os grupos da fixture.
    obj["gerador_versao"] = GERADOR_VERSAO
    obj["direcoes_edicao"] = _direcoes_edicao()
    obj["grafismos_do_plano"] = _grafismos_do_plano(dst, obj.get("grupos") or [])
    obj["propostas"] = _propostas(obj.get("grupos") or [], obj.get("semente"),
                                  obj.get("vigente"), obj.get("tema_default"),
                                  obj.get("acento_default"),
                                  obj["grafismos_do_plano"])
    erros_fx = validar_direcoes_edicao(obj) + validar_propostas(obj)
    if erros_fx:
        for x in erros_fx:
            log("  ✗ fixture: %s" % x)
        raise SystemExit("fixture inválida (%d): não gravei nada" % len(erros_fx))
    (dst / "galeria.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log("fixture em %s — %d card(s) com mídia real do catálogo, %d declarando "
        "ausência, 0 caminho apontando para o vazio.\n"
        "  sirva com `python3 -m http.server` e abra "
        "galeria.html?galeria=./galeria.json&fixture=1" % (dst, n_mid, n_placa))
    return str(dst / "galeria.json")


# ─────────────────────────────────── CLI ───────────────────────────────────
def _cli(argv=None):
    ap = argparse.ArgumentParser(
        description="Galeria de estilos: galeria.json + previews de nível 1. "
                    "Escreve SÓ dentro de <dir-producao>/.preview/.")
    ap.add_argument("dir", nargs="?", help="diretório da produção")
    ap.add_argument("--somente-defaults", action="store_true")
    ap.add_argument("--grupo")
    ap.add_argument("--gancho")
    ap.add_argument("--acento")
    ap.add_argument("--tema")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--sem-render", action="store_true")
    ap.add_argument("--estilo", metavar="U/SLUG",
                    help="pré-seleciona a galeria a partir de um estilo da "
                         "biblioteca do usuário (SPEC-24); sem biblioteca, silêncio")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--fixture", metavar="DESTINO")
    ap.add_argument("--pacote", metavar="DESTINO",
                    help="monta um dir servível (tela + galeria.json + mídias) "
                         "para usar como --app do servidor")
    a = ap.parse_args(argv)

    if a.fixture and not a.dir:
        print(fixture(a.fixture))
        return 0
    if not a.dir:
        ap.error("informe o diretório da produção (ou --fixture DESTINO)")
    if a.pacote:
        print(pacote(a.dir, a.pacote))
        return 0

    if a.listar:
        cat = catalogo()
        perf, _f = perfil_da_peca(a.dir)
        W, H, FPS = canvas_de(perf)
        base = Path(a.dir) / ".preview" / "estilos"
        cache = _ler_json(base / ".cache.json", {}) or {}
        por_grupo = oferecidos(cat, perf.get("nome") or "reels", a.grupo)
        n = 0
        for gid in ORDEM_GRUPOS:
            for e in por_grupo.get(gid, []):
                k = cache.get(e["slug"], "")
                nivel = 1 if k else 0
                print("%s\t%s\t%d\t%s" % (e["slug"], gid, nivel, k))
                n += 1
        log("--listar varreu %d estilos oferecidos ao perfil %s (de %d no catálogo)"
            % (n, perf.get("nome"), len(cat["estilos"])))
        return 0

    t0 = time.time()
    caminho = gerar(a.dir, somente_defaults=a.somente_defaults, grupo=a.grupo,
                    gancho=a.gancho, acento=a.acento, tema=a.tema,
                    forcar=a.forcar, sem_render=a.sem_render, estilo=a.estilo)
    log("%.1fs de parede · %d chamada(s) ao remotion · %d preview(s) renderizado(s)"
        % (time.time() - t0, _CONTADOR["chamadas_node"], _CONTADOR["render"]))
    print(caminho)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
