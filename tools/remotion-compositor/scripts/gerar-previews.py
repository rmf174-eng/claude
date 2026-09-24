#!/usr/bin/env python3
"""Catálogo de estilos — gerador de `catalogo.json` e dos previews (SPEC-15 §4.3).

    gerar-previews.py                 regenera catalogo.json + previews com sha mudado
    gerar-previews.py --slug <slug>   um só
    gerar-previews.py --grupo legenda um grupo
    gerar-previews.py --check         NÃO renderiza: sai 1 se catalogo.json dessincronizou
    gerar-previews.py --validar       NÃO renderiza: valida catalogo.json contra _schema.json
    gerar-previews.py --forcar        ignora o hash (refresh)
    gerar-previews.py --listar        slug · grupo · estado · sha (stdout)

Contrato de saída: o caminho do `catalogo.json` no stdout, logs no stderr.

────────────────────────────────────────────────────────────────────────────────
COMO O PYTHON LÊ O REGISTRO (decisão fechada da spec, §4.3)

O registro é TypeScript e o gerador é Python. **O Python nunca faz parse de
TypeScript** — nem por regex, nem por transpilador, nem por dependência nova. A
ponte é a composição `CatalogoDump`, cujo `defaultProps` carrega o registro
serializado; um driver Node de ~60 linhas bundla o entry point isolado, lê os
`defaultProps` por `getCompositions()` e grava `catalogo/.registro.json`.

⚠️ DIVERGÊNCIA MEDIDA CONTRA A SPEC. A §4.3 propõe que o `calculateMetadata` de
`CatalogoDump` grave o arquivo e que a ponte seja `npx remotion still`. Não é
implementável: `calculateMetadata` é avaliado DENTRO do Chrome headless, onde não
existe `fs`. O mecanismo da spec (uma travessia só, sem parse de TS, `--check` e
`--listar` passando pelo mesmo caminho) está mantido na íntegra — o que mudou foi
QUEM lê os `defaultProps`: o driver Node, em vez de um `still` descartável. Efeito
colateral bom: some o `catalogo/.dump.png` que a §5 previa, e o bundle é feito UMA
vez por invocação em vez de uma por slug.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]          # tools/remotion-compositor


def _base_das_skills() -> Path:
    """O diretório a partir do qual `skills/<x>/…` resolve. Por MARCADOR.

    🔴 A MESMA FAMÍLIA DO DEFEITO QUE A SPEC-34 CONSERTOU EM `previews-peca.py`,
    viva em outro script (achado A2-resto, medido em 2026-08-11). Aqui estava
    `RAIZ.parents[1]`, que é uma AFIRMAÇÃO sobre onde este projeto mora: na nossa
    árvore `ilha/tools/remotion-compositor` sobe para `ilha/`, e `ilha/skills/`
    existe. Na instalação do cliente o projeto mora em
    `<raiz>/tools/remotion-compositor`, os mesmos dois níveis dão `<raiz>`, e
    `<raiz>/skills/` NÃO existe — as skills estão em `<raiz>/.claude/skills/`.
    Efeito medido no clone: `npm run catalogo -- --check` saía **exit 1** porque
    `caminho_origem()` procurava `skills/edit-video/perfis/reels.json` num lugar
    onde ele não está, e o terceiro comando de verificação do README reprovava
    numa instalação correta.

    O marcador é o diretório `edit-video`, que é o nome de uma skill e existe nas
    duas grafias. Contar níveis nunca funciona nas duas árvores ao mesmo tempo.
    Devolvemos o PAI de `skills/`, porque as entradas do catálogo escrevem
    `skills/edit-video/…` e é isso que tem que resolver: `ilha/` aqui,
    `<raiz>/.claude/` no pacote.
    """
    for base in [RAIZ, *RAIZ.parents]:
        if (base / "skills" / "edit-video").is_dir():
            return base
        if (base / ".claude" / "skills" / "edit-video").is_dir():
            return base / ".claude"
    # sem marcador: devolve o palpite histórico em vez de estourar, e quem
    # chamar falha nomeando o caminho que tentou.
    return RAIZ.parents[1]


ILHA = _base_das_skills()                           # `ILHA/skills/<x>` resolve
CATALOGO = RAIZ / "catalogo"
PREVIEWS = CATALOGO / "previews"
REGISTRO_JSON = CATALOGO / ".registro.json"
CATALOGO_JSON = CATALOGO / "catalogo.json"
SCHEMA_JSON = CATALOGO / "_schema.json"
ENTRY = "src/index-catalogo.tsx"
BUNDLE_DIR = RAIZ / "node_modules" / ".cache" / "spec15-bundle"

CONTRATO = "benchmark.catalogo-estilos/v1"
GERADOR = "scripts/gerar-previews.py"

# 8 agentes disputam esta máquina durante a onda. Concorrência modesta de
# propósito: o número de parede vira inútil se o render brigar com o vizinho.
CONCORRENCIA = int(os.environ.get("BENCH_CATALOGO_CONCORRENCIA", "2"))


def log(*a):
    print(*a, file=sys.stderr)


# ─────────────────────────── o driver Node ───────────────────────────
DRIVER = r"""
import fs from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import {
  getCompositions,
  selectComposition,
  renderMedia,
  renderStill,
} from "@remotion/renderer";

const p = JSON.parse(process.env.SPEC15_PAYLOAD);

const serveUrl = p.reusarBundle
  ? p.bundleDir
  : await bundle({
      entryPoint: path.resolve(p.raiz, p.entry),
      outDir: p.bundleDir,
      onProgress: () => {},
    });

if (p.modo === "dump") {
  const comps = await getCompositions(serveUrl, { logLevel: "error" });
  const dump = comps.find((c) => c.id === "CatalogoDump");
  if (!dump) throw new Error("CatalogoDump não existe no entry point");
  fs.writeFileSync(p.saidaRegistro, JSON.stringify(dump.defaultProps, null, 1));
  console.log(JSON.stringify({ ok: true, n: dump.defaultProps.estilos.length }));
} else {
  const feitos = [];
  for (const it of p.itens) {
    const inputProps = { slug: it.slug };
    const comp = await selectComposition({
      serveUrl,
      id: "CatalogoPreview",
      inputProps,
      logLevel: "error",
    });
    await renderMedia({
      composition: comp,
      serveUrl,
      codec: "vp9",
      // 🔴 OPACO. Nunca pixelFormat yuva420p: VP9/VP8 WebM com alpha derruba o
      // canal em silêncio no libvpx do Homebrew 8.x, que é o nosso.
      //
      // 🔴 E COM TETO DE BITRATE. Sem `videoBitrate`, o VP9 gasta o que precisar
      // para um preview de 3 s — e o de calendário, que anima uma grade inteira,
      // saiu com 1,2 MB. O detector de classe E da SPEC-22 acusa mídia acima de
      // 1 MB sobrevivendo ao corte, e essa emenda NÃO é suprimível por
      // `aceitos.json`: qualquer E aborta o export, de propósito. Um preview de
      // catálogo que estoura o limiar de conteúdo privado trava o release
      // inteiro por um card. 900k mantém todos com folga e o cartão continua
      // legível — é preview de 360 px de largura, não entregável.
      videoBitrate: "900k",
      // 🔴 E COM TAGS DE COR (2026-08-12, H47-3). Sem `colorSpace`, o default do
      // Remotion 4 é `"default"` — que não emite flag nenhuma — e o libvpx
      // carimba o que sobrou do pipeline: `color_range=pc` (full) com
      // `color_space=bt470bg` (BT.601 625 linhas). Medido em campo por um agente
      // externo: os 37 cards da galeria PRETOS no Chrome 148 / Electron 42, com
      // `HTMLMediaElement.error.code = 3` (PIPELINE_ERROR_DECODE); re-taguear o
      // MESMO arquivo para tv/bt709 fazia voltar. Reproduzido aqui no Chromium do
      // Playwright: 1 de 3 previews com erro 3, os outros dois decodificando —
      // ou seja, depende de versão e de conteúdo, e é exatamente o tipo de
      // defeito que só a máquina do cliente mostra.
      //
      // `colorSpace: "bt709"` faz o Remotion emitir os quatro
      // (`-colorspace bt709 -color_primaries bt709 -color_trc bt709
      // -color_range tv`) MAIS o `zscale=…:range=limited` que converte de fato —
      // não é só rótulo. Preview de catálogo não é entregável, mas rótulo de cor
      // errado aqui não é questão de fidelidade: é decodificar ou não.
      colorSpace: "bt709",
      outputLocation: it.webm,
      inputProps,
      scale: p.escala,
      concurrency: p.concorrencia,
      logLevel: "error",
      onProgress: () => {},
    });
    await renderStill({
      composition: comp,
      serveUrl,
      output: it.png,
      frame: it.frame,
      inputProps,
      scale: p.escala,
      imageFormat: "png",
      logLevel: "error",
    });
    feitos.push({
      slug: it.slug,
      frames: comp.durationInFrames,
      fps: comp.fps,
      w: comp.width,
      h: comp.height,
    });
    console.error(`  ✓ ${it.slug} (${comp.durationInFrames} frames)`);
  }
  console.log(JSON.stringify({ ok: true, feitos }));
}
"""


def roda_driver(payload: dict) -> dict:
    env = dict(os.environ)
    env["SPEC15_PAYLOAD"] = json.dumps(payload)
    pr = subprocess.run(
        ["node", "--input-type=module"],
        input=DRIVER,
        text=True,
        capture_output=True,
        cwd=str(RAIZ),
        env=env,
    )
    if pr.stderr.strip():
        for ln in pr.stderr.strip().splitlines():
            if "network requests to load fonts" in ln:
                continue
            log(ln)
    if pr.returncode != 0:
        raise SystemExit(f"driver node falhou (exit {pr.returncode})")
    ultima = [l for l in pr.stdout.strip().splitlines() if l.startswith("{")]
    if not ultima:
        raise SystemExit("driver node não devolveu JSON")
    return json.loads(ultima[-1])


def dump_registro(saida: Path | None = None) -> dict:
    """Serializa o registro TypeScript num JSON e o devolve.

    🔴 `saida` existe porque MODO DE CONFERÊNCIA NÃO ESCREVE (achado R-15,
    2026-08-11). O `--check` chamava isto sem alternativa, e a ponte gravava
    `catalogo/.registro.json` na árvore de quem só queria conferir — descoberto
    ao diffar um clone contra um clone pristino, e o clone saía SUJO depois do
    terceiro comando de verificação que o README manda rodar. Um comando de
    conferência que muda o que confere não é conferência.
    """
    destino = Path(saida) if saida else REGISTRO_JSON
    destino.parent.mkdir(parents=True, exist_ok=True)
    roda_driver(
        {
            "modo": "dump",
            "raiz": str(RAIZ),
            "entry": ENTRY,
            "bundleDir": str(BUNDLE_DIR),
            "reusarBundle": False,
            "saidaRegistro": str(destino),
        }
    )
    return json.loads(destino.read_text())


# ─────────────────────────── sha por entrada ───────────────────────────
def caminho_origem(origem: str) -> Path:
    """`origem` é "<caminho>:<linha ou campo>". `src/…` é do projeto Remotion;
    qualquer outro caminho é relativo à raiz da ilha."""
    arq = origem.split(":", 1)[0]
    return (RAIZ / arq) if arq.startswith("src/") else (ILHA / arq)


# 🔴 O ARNÊS ENTRA NO SHA. Sem isto, mexer em `Preview.tsx`, `Placas.tsx` ou
# `amostra.ts` muda o que aparece no card e NÃO re-renderiza nada: o `--check`
# fica verde sobre preview velho. É o mesmo defeito do canvas, com outra porta —
# o sha tem que descrever tudo que produziu o pixel, não só a entrada.
ARNES = [
    "src/catalogo/Preview.tsx",
    "src/catalogo/Placas.tsx",
    "src/catalogo/amostra.ts",
]


def sha_do_arnes() -> bytes:
    h = hashlib.sha256()
    for rel in ARNES:
        p = RAIZ / rel
        if not p.exists():
            raise SystemExit(f"ERRO: arnês ausente → {p}")
        h.update(p.read_bytes())
    return h.digest()


def sha_de(entrada: dict, canvas: dict) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(entrada, sort_keys=True, ensure_ascii=False).encode())
    h.update(json.dumps(canvas, sort_keys=True).encode())
    h.update(sha_do_arnes())
    p = caminho_origem(entrada["origem"])
    if not p.exists():
        raise SystemExit(
            f"ERRO {entrada['slug']}: origem inexistente → {p}\n"
            "  Uma entrada de catálogo que aponta para arquivo que não existe é "
            "exatamente o defeito que esta spec veio corrigir."
        )
    h.update(p.read_bytes())
    return h.hexdigest()[:12]


# O par que o browser aceita. `color_primaries`/`color_transfer` ficam `unknown`
# no WebM mesmo com as quatro flags passadas ao encoder (o contêiner não carrega
# esses dois campos onde o ffprobe os lê) — exigi-los aqui daria falso vermelho
# em arquivo correto. Os dois que importam para decodificar são estes.
TAGS_COR_EXIGIDAS = ("tv", "bt709")


def tags_de_cor(p: Path):
    """(color_range, color_space) do vídeo, por ffprobe. `None` se não deu medir.

    `None` NÃO é aprovação: quem chama declara "não medido" em voz alta.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=color_range,color_space", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    partes = [x.strip() for x in r.stdout.strip().split(",")]
    if len(partes) < 2:
        return None
    return partes[0], partes[1]


def dims_png(p: Path):
    """Largura/altura lidas do cabeçalho IHDR — medido, não deduzido do --scale."""
    with p.open("rb") as f:
        cab = f.read(24)
    if len(cab) < 24 or cab[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", cab[16:24])
    return int(w), int(h)


# ─────────────────────────── validador de schema ───────────────────────────
# Subconjunto de JSON Schema 2020-12 suficiente para `_schema.json`:
# type · required · properties · additionalProperties · enum · const · items ·
# minItems · maxItems · minimum · maximum · pattern · $ref (#/$defs/...) ·
# uniqueItems. Nada de dependência nova — e com dentes provados (§7 do relatório).
TIPOS = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def valida(inst, esq, raiz_esq, caminho="$", erros=None):
    erros = [] if erros is None else erros
    if "$ref" in esq:
        alvo = raiz_esq
        for parte in esq["$ref"].lstrip("#/").split("/"):
            alvo = alvo[parte]
        return valida(inst, alvo, raiz_esq, caminho, erros)
    t = esq.get("type")
    if t:
        tt = TIPOS[t]
        ok = isinstance(inst, tt) and not (t == "number" and isinstance(inst, bool))
        if t == "integer" and isinstance(inst, bool):
            ok = False
        if not ok:
            erros.append(f"{caminho}: esperava {t}, veio {type(inst).__name__}")
            return erros
    if "const" in esq and inst != esq["const"]:
        erros.append(f"{caminho}: esperava const {esq['const']!r}, veio {inst!r}")
    if "enum" in esq and inst not in esq["enum"]:
        erros.append(f"{caminho}: {inst!r} fora de {esq['enum']}")
    if isinstance(inst, str) and "pattern" in esq:
        if not re.search(esq["pattern"], inst):
            erros.append(f"{caminho}: {inst!r} não casa /{esq['pattern']}/")
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in esq and inst < esq["minimum"]:
            erros.append(f"{caminho}: {inst} < mínimo {esq['minimum']}")
        if "maximum" in esq and inst > esq["maximum"]:
            erros.append(f"{caminho}: {inst} > máximo {esq['maximum']}")
    if isinstance(inst, list):
        if "minItems" in esq and len(inst) < esq["minItems"]:
            erros.append(f"{caminho}: {len(inst)} itens < mínimo {esq['minItems']}")
        if "maxItems" in esq and len(inst) > esq["maxItems"]:
            erros.append(f"{caminho}: {len(inst)} itens > máximo {esq['maxItems']}")
        if esq.get("uniqueItems") and len(
            {json.dumps(x, sort_keys=True) for x in inst}
        ) != len(inst):
            erros.append(f"{caminho}: itens repetidos")
        if "items" in esq:
            for i, v in enumerate(inst):
                valida(v, esq["items"], raiz_esq, f"{caminho}[{i}]", erros)
    if isinstance(inst, dict):
        for req in esq.get("required", []):
            if req not in inst:
                erros.append(f"{caminho}: falta a chave obrigatória {req!r}")
        props = esq.get("properties", {})
        for k, v in inst.items():
            if k in props:
                valida(v, props[k], raiz_esq, f"{caminho}.{k}", erros)
            elif esq.get("additionalProperties") is False:
                erros.append(f"{caminho}: chave não prevista {k!r}")
    return erros


def regras_do_contrato(cat: dict) -> list[str]:
    """As 5 regras do fim da §4.1, que JSON Schema não expressa."""
    e = []
    slugs = [x["slug"] for x in cat["estilos"]]
    if len(slugs) != len(set(slugs)):
        rep = sorted({s for s in slugs if slugs.count(s) > 1})
        e.append(f"slug repetido no catálogo inteiro: {rep}")
    donos: dict[tuple[str, str], str] = {}
    for x in cat["estilos"]:
        for p in x["defaultDe"]:
            if p not in x["perfis"]:
                e.append(f"{x['slug']}: defaultDe {p!r} fora de perfis")
            k = (x["grupo"], p)
            if k in donos:
                e.append(f"dois defaults de {x['grupo']} para {p}: {donos[k]} e {x['slug']}")
            else:
                donos[k] = x["slug"]
        if x["estado"] == "candidato":
            if not x.get("bloqueio"):
                e.append(f"{x['slug']}: candidato sem bloqueio")
            if "webm" in x["preview"] or "poster" in x["preview"]:
                e.append(f"{x['slug']}: candidato não pode ter preview renderizado")
        else:
            for campo in ("webm", "poster"):
                v = x["preview"].get(campo)
                if not v:
                    e.append(f"{x['slug']}: pronto sem preview.{campo}")
                elif v.startswith("/") or ":" in v:
                    e.append(f"{x['slug']}: preview.{campo} não é relativo a catalogo/")
    return e


# ─────────────────────────── montagem do catálogo ───────────────────────────
def monta(registro: dict, shas: dict, renovados: set, antigos: dict) -> dict:
    """
    🔴 `renovados` é o que impede o defeito medido em 2026-08-08: numa rodada
    filtrada (`--slug`/`--grupo`) o gerador gravava o sha NOVO de todo mundo,
    inclusive de quem NÃO foi re-renderizado. Resultado: `catalogo.json`
    abençoando preview velho, com `--check` verde. É o bug do segmento órfão de
    novo — sucesso silencioso.

    Regra: o `sha` gravado descreve O QUE ESTÁ NO DISCO. Quem não foi tocado
    nesta rodada carrega o sha anterior, e aí o `--check` ACUSA a divergência.
    """
    canvas = registro["canvas"]
    escala = canvas["escala"]
    w = round(canvas["largura"] * escala)
    h = round(canvas["altura"] * escala)
    saida = []
    for e in registro["estilos"]:
        ent = json.loads(json.dumps(e))
        prev = dict(ent["preview"])
        prev["w"], prev["h"], prev["fps"] = w, h, canvas["fps"]
        if ent["estado"] == "pronto":
            rel_webm = f"previews/{ent['slug']}.webm"
            rel_png = f"previews/{ent['slug']}.png"
            prev["webm"] = rel_webm
            prev["poster"] = rel_png
            medido = dims_png(CATALOGO / rel_png)
            if medido:
                prev["w"], prev["h"] = medido
        ent["preview"] = prev
        s = ent["slug"]
        ent["sha"] = (
            shas[s] if s in renovados else antigos.get(s, {}).get("sha", shas[s])
        )
        saida.append(ent)
    return {
        "contrato": CONTRATO,
        "gerado_em": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "gerador": GERADOR,
        # 📐 O canvas do preview é o do PERFIL DE PEÇA corrente (SPEC-00): o
        # catálogo não crava formato. Fica registrado aqui porque ele ENTRA no
        # `sha` — trocar de perfil invalida todo preview, em vez de reusar um
        # card renderizado no formato anterior (o bug do segmento órfão).
        "canvas": canvas,
        "estilos": saida,
    }


def carrega_catalogo():
    if not CATALOGO_JSON.exists():
        return None
    try:
        return json.loads(CATALOGO_JSON.read_text())
    except json.JSONDecodeError:
        return None


def main():
    ap = argparse.ArgumentParser(description="gera catalogo.json + previews do catálogo de estilos")
    ap.add_argument("--slug")
    ap.add_argument("--grupo")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    if args.validar:
        cat = carrega_catalogo()
        if cat is None:
            log("catalogo.json ausente ou ilegível")
            raise SystemExit(1)
        esq = json.loads(SCHEMA_JSON.read_text())
        erros = valida(cat, esq, esq)
        erros += regras_do_contrato(cat)
        log(f"validado: {len(cat['estilos'])} estilos contra {SCHEMA_JSON.name}")
        if erros:
            for x in erros:
                log(f"  ✗ {x}")
            raise SystemExit(1)
        log("  ✓ schema + 5 regras do contrato")
        print(CATALOGO_JSON)
        return

    t0 = time.time()
    # `--check` e `--listar` são LEITURA: o registro vai para um temporário, e a
    # árvore de quem confere não muda um byte (R-15).
    so_leitura = bool(args.check or args.listar)
    if so_leitura:
        tmpdir = tempfile.mkdtemp(prefix="spec15-registro-")
        try:
            registro = dump_registro(Path(tmpdir) / ".registro.json")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        registro = dump_registro()
    canvas = registro["canvas"]
    log(
        f"registro: {len(registro['estilos'])} estilos · canvas "
        f"{canvas['largura']}×{canvas['altura']}@{canvas['fps']} · escala {canvas['escala']}"
    )
    shas = {e["slug"]: sha_de(e, canvas) for e in registro["estilos"]}

    if args.listar:
        for e in registro["estilos"]:
            print(f"{e['slug']}\t{e['grupo']}\t{e['estado']}\t{shas[e['slug']]}")
        return

    if args.check:
        cat = carrega_catalogo()
        if cat is None:
            log("catalogo.json ausente ou ilegível — rode sem --check")
            raise SystemExit(1)
        antigos = {e["slug"]: e for e in cat["estilos"]}
        problemas = []
        for e in registro["estilos"]:
            s = e["slug"]
            if s not in antigos:
                problemas.append(f"{s}: no registro e fora do catalogo.json")
            elif antigos[s]["sha"] != shas[s]:
                problemas.append(f"{s}: sha divergente ({antigos[s]['sha']} → {shas[s]})")
        for s in antigos:
            if s not in shas:
                problemas.append(f"{s}: no catalogo.json e fora do registro")
        # 🔴 Dimensão do PNG contra o canvas corrente. Sem isto o `--check` fica
        # verde sobre um catálogo MISTO — medido em 2026-08-08: um vizinho
        # trocou `src/data/perfil.json` de `reels` para `vsl` no meio da onda, 30
        # cards ficaram 360×640 e 1 ficou 640×360, e nada acusava. O sha sozinho
        # não pega porque ele descreve a INTENÇÃO; só o pixel descreve o disco.
        alvo_w = round(canvas["largura"] * canvas["escala"])
        alvo_h = round(canvas["altura"] * canvas["escala"])
        for e in registro["estilos"]:
            if e["estado"] != "pronto":
                continue
            for ext in ("webm", "png"):
                f = PREVIEWS / f"{e['slug']}.{ext}"
                if not f.exists():
                    problemas.append(f"{e['slug']}: preview .{ext} não existe")
            png = PREVIEWS / f"{e['slug']}.png"
            if png.exists():
                d = dims_png(png)
                if d and d != (alvo_w, alvo_h):
                    problemas.append(
                        f"{e['slug']}: poster {d[0]}×{d[1]} contra o canvas corrente "
                        f"{alvo_w}×{alvo_h} — preview renderizado em outro perfil de peça"
                    )
                gravado = antigos.get(e["slug"], {}).get("preview", {})
                if d and (gravado.get("w"), gravado.get("h")) != d:
                    problemas.append(
                        f"{e['slug']}: catalogo.json diz {gravado.get('w')}×{gravado.get('h')}, "
                        f"o arquivo tem {d[0]}×{d[1]}"
                    )
        # 🔴 AS TAGS DE COR DE CADA .webm (2026-08-12, H47-3). O `--check` conferia
        # sincronia e dimensão, e a galeria INTEIRA do cliente ficava preta: os 37
        # cards com `HTMLMediaElement.error.code = 3` (PIPELINE_ERROR_DECODE),
        # porque o `renderMedia` sem `colorSpace` deixava o libvpx carimbar
        # `color_range=pc` + `color_space=bt470bg`. Medido nesta máquina em
        # 2026-08-12, um vídeo por página no Chromium do Playwright: **38 de 38
        # previews da v0.12 falharam; os 39 com tv/bt709 passaram**.
        #
        # Esta régua é a única que roda SEMPRE (ffprobe é dependência declarada,
        # browser não é). A segunda camada, que DECODIFICA de verdade, é
        # `scripts/qc-galeria-decodifica.mjs` — e ela não substitui esta: o
        # defeito de tags não reproduz no `chrome-headless-shell` do Remotion.
        n_cor, sem_ffprobe = 0, False
        for e in registro["estilos"]:
            if e["estado"] != "pronto":
                continue
            webm = PREVIEWS / f"{e['slug']}.webm"
            if not webm.exists():
                continue
            tags = tags_de_cor(webm)
            if tags is None:
                sem_ffprobe = True
                break
            n_cor += 1
            if tags != TAGS_COR_EXIGIDAS:
                problemas.append(
                    f"{e['slug']}: preview com tags de cor {tags[0]}/{tags[1]} — "
                    f"exigido {TAGS_COR_EXIGIDAS[0]}/{TAGS_COR_EXIGIDAS[1]}. "
                    f"Regenere com --forcar (o gerador declara colorSpace bt709); "
                    f"como está, o browser do cliente recusa com "
                    f"PIPELINE_ERROR_DECODE e o card fica preto"
                )
        log(f"--check varreu {len(registro['estilos'])} estilos e {len(antigos)} entradas gravadas"
            + (f" · tags de cor conferidas em {n_cor} preview(s)" if n_cor else "")
            + (" · ⚠️ tags de cor NÃO medidas: ffprobe indisponível" if sem_ffprobe else ""))
        if problemas:
            for p in problemas:
                log(f"  ✗ {p}")
            raise SystemExit(1)
        log("  ✓ catalogo.json em sincronia com o registro")
        print(CATALOGO_JSON)
        return

    # ── seleção do que renderizar ──
    antigos = {e["slug"]: e for e in (carrega_catalogo() or {"estilos": []})["estilos"]}
    alvo = []
    for e in registro["estilos"]:
        s = e["slug"]
        if args.slug and s != args.slug:
            continue
        if args.grupo and e["grupo"] != args.grupo:
            continue
        if e["estado"] != "pronto":
            continue
        png = PREVIEWS / f"{s}.png"
        faltando = not (PREVIEWS / f"{s}.webm").exists() or not png.exists()
        mudou = antigos.get(s, {}).get("sha") != shas[s]
        # o pixel manda: preview renderizado noutro canvas volta para a fila
        # mesmo com sha igual (o sha pode ter sido gravado por uma rodada
        # filtrada anterior, e aí ele descreve a intenção, não o disco)
        d = dims_png(png) if png.exists() else None
        desalinhado = d is not None and d != (
            round(canvas["largura"] * canvas["escala"]),
            round(canvas["altura"] * canvas["escala"]),
        )
        if args.forcar or faltando or mudou or desalinhado:
            alvo.append(e)

    prontos = [e for e in registro["estilos"] if e["estado"] == "pronto"]
    log(f"{len(alvo)} a renderizar, {len(prontos) - len(alvo)} pulados (de {len(prontos)} prontos)")

    if alvo:
        PREVIEWS.mkdir(parents=True, exist_ok=True)
        for f in PREVIEWS.glob(".tmp-*"):
            f.unlink()  # resto de uma rodada que caiu no meio
        itens = [
            {
                "slug": e["slug"],
                "frame": int(e["preview"]["frameCartao"]),
                "webm": str(PREVIEWS / f".tmp-{e['slug']}.webm"),
                "png": str(PREVIEWS / f".tmp-{e['slug']}.png"),
            }
            for e in alvo
        ]
        roda_driver(
            {
                "modo": "render",
                "raiz": str(RAIZ),
                "entry": ENTRY,
                "bundleDir": str(BUNDLE_DIR),
                "reusarBundle": True,
                "escala": canvas["escala"],
                "concorrencia": CONCORRENCIA,
                "itens": itens,
            }
        )
        # 🔴 RENDER EM TEMP + os.replace, NUNCA no caminho final (A-S1, SPEC-45).
        # previews-peca.py materializa o nível 0 nas produções por HARDLINK
        # (mesmo inode). Renderizar direto no caminho final reescrevia o inode
        # compartilhado — `npm run catalogo` mudava bytes dentro de
        # creators/*/producao/** em silêncio (medido: links=16 no mesmo inode).
        # O replace atômico cria inode NOVO; o cache da produção fica congelado
        # na época do pack, que é o contrato de um cache.
        for e in alvo:
            for ext in ("webm", "png"):
                os.replace(
                    PREVIEWS / f".tmp-{e['slug']}.{ext}",
                    PREVIEWS / f"{e['slug']}.{ext}",
                )

    # previews órfãos (entrada que virou candidato ou sumiu)
    validos = {f"{e['slug']}.webm" for e in prontos} | {f"{e['slug']}.png" for e in prontos}
    if PREVIEWS.exists() and not args.slug and not args.grupo:
        for f in sorted(PREVIEWS.iterdir()):
            if f.name not in validos:
                log(f"  ⚠ preview órfão removido: {f.name}")
                f.unlink()

    filtrada = bool(args.slug or args.grupo)
    if filtrada:
        renovados = {
            e["slug"]
            for e in registro["estilos"]
            if (not args.slug or e["slug"] == args.slug)
            and (not args.grupo or e["grupo"] == args.grupo)
        }
        carregados = len(registro["estilos"]) - len(renovados)
        log(f"rodada FILTRADA: {len(renovados)} sha renovados, {carregados} carregados do catálogo anterior")
    else:
        renovados = {e["slug"] for e in registro["estilos"]}

    cat = monta(registro, shas, renovados, antigos)
    CATALOGO_JSON.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n")
    log(f"{len(alvo)} renderizados, {len(prontos) - len(alvo)} pulados · {time.time() - t0:.1f}s de parede")
    print(CATALOGO_JSON)


if __name__ == "__main__":
    main()
