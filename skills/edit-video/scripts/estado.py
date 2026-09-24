#!/usr/bin/env python3
"""Contrato de dados da UI de aprovação (benchmark.edit-estado/v1).

O desenho de três arquivos (estado do agente / ajustes da UI / estilo da UI), a
escrita atômica e o par de coordenadas rascunho↔render são MECANISMO observado em
uma ferramenta de edição de terceiro,
helpers/preview_server.py:5-12,227-236 e assets/preview/app.js:1810-1817.
Nenhum código foi portado. Ver docs/specs/SPEC-16 §10.

────────────────────────────────────────────────────────────────────────────
O QUE ISTO É. O estado que a UI de aprovação lê é DERIVADO DO DISCO por este
script, não digitado pelo agente. O agente declara só o que o disco não sabe
(fase, mensagem, portão, aprovações, quais renders importam) e isso vive em
`.preview/estado-agente.json`. Estado escrito à mão descola do disco em silêncio
— é a mesma classe de defeito que o sidecar de procedência existe para pegar.

    <dir-producao>/.preview/
    ├── estado.json          benchmark.edit-estado/v1   ESTE script escreve
    ├── estado-agente.json   o que o agente declarou    ESTE script escreve
    ├── pendentes/*.json     envelope da SPEC-17        o servidor escreve, aqui só LÊ
    ├── aplicados/*.json     o ACK é o MOVE, não o delete
    ├── ajustes.json         benchmark.edit-ajustes/v1  caminho sem servidor
    ├── estilo.json          benchmark.edit-estilo/v1   caminho sem servidor
    ├── servidor.json        SPEC-17                    nem lido aqui
    └── cache/               SPEC-17                    nem lido aqui

🔴 TRÊS REGRAS DURAS, e cada uma paga uma dívida medida neste repo:

1. REPORTA, NUNCA CONSERTA. Órfão não é apagado, sidecar não é regravado,
   segmento não é recortado. Um relatório que conserta o defeito antes de
   relatá-lo apaga a evidência que ele existe para mostrar — e é o que permite
   rodar isto, sem medo, sobre as 8 produções já publicadas.

2. NENHUM VALOR DE FORMATO. Largura, altura e fps vêm do `perfil.json` (SPEC-00)
   ou do `ffprobe` dos segmentos. O grep de dimensões conhecidas (as do critério
   §7.9 da SPEC-16) neste arquivo tem que voltar VAZIO — e ele volta, inclusive
   deste parágrafo, que é onde a tentação de "só citar o número" mora.

3. COORDENADA DE RENDER SÓ COM `timeline_real` (SPEC-05). Sem ela,
   `notas[].render` é `null` — nunca `Σ(end−start)`. A soma nominal erra 353 ms
   no fim de `peca-03`, 317 ms em `peca-01`, 352 ms em `c-completo`, e é
   o anti-pattern que rendeu 4,433 s de erro no ref-A. Coordenada ausente a UI
   mostra desabilitada; coordenada errada manda o agente editar o take vizinho, e
   nada acusa.

   ⚠️ `Σ(end−start)` APARECE aqui, com um nome só: `rascunho`. Ela é a régua da
   TIMELINE DO RASCUNHO — a que a UI compõe virtualmente e o usuário vê antes de
   existir render. É legítima nesse papel e só nesse. `saida` é a régua do
   arquivo que existe, e ela vem da `timeline_real`.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                      # noqa: E402  SPEC-05 — envelope + timeline real
import perfil as perfil_mod        # noqa: E402  SPEC-00 — perfil de peça

CONTRATO = "benchmark.edit-estado/v1"
CONTRATO_AJUSTES = "benchmark.edit-ajustes/v1"
CONTRATO_ESTILO = "benchmark.edit-estilo/v1"
# SPEC-19 §4.5 — o v2 traz o vocabulário do catálogo de estilos. Quem conhece o
# schema é quem o define: este arquivo apenas ROTEIA para `escolha-estilo.py`.
CONTRATO_ESTILO_V2 = "benchmark.edit-estilo/v2"
CONTRATO_ESTILO_V3 = "benchmark.edit-estilo/v3"
ENVELOPE = "benchmark.preview-evento/v1"


def _escolha_estilo():
    """Carrega `escolha-estilo.py` (SPEC-19) sob demanda, ou `None`.

    Import tardio e tolerante de propósito: o nome tem hífen (não é importável
    direto) e o arquivo pode não existir numa instalação sem a SPEC-19. Sem ele,
    o v2 é recusado como contrato desconhecido — que é a verdade — em vez de o
    módulo inteiro deixar de carregar."""
    if "_ee" not in globals():
        try:
            import importlib.util
            caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "escolha-estilo.py")
            spec = importlib.util.spec_from_file_location("escolha_estilo", caminho)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            globals()["_ee"] = mod
        except Exception:                                        # noqa: BLE001
            globals()["_ee"] = None
    return globals()["_ee"]


def _plano_visual():
    """Carrega o gate da Fase 2 sob demanda, sem duplicar seu contrato aqui."""
    if "_pv" not in globals():
        try:
            import importlib.util
            caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "plano-visual.py")
            spec = importlib.util.spec_from_file_location("plano_visual", caminho)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            globals()["_pv"] = mod
        except Exception:                                        # noqa: BLE001
            globals()["_pv"] = None
    return globals()["_pv"]


def _galeria_de(dir_producao):
    return _ler_json(os.path.join(dir_preview(dir_producao), "estilos", "galeria.json"))

DIR_PREVIEW = ".preview"
NOME_ESTADO = "estado.json"
NOME_AGENTE = "estado-agente.json"

# ── de onde a aprovação nasceu (achado A10 da auditoria de 2026-08-10)
#
# 🔴 O PROBLEMA QUE ISTO FECHA. Até aqui, "aprovado" era uma string: `--por` é
# livre, o default era `$USER`, e não existia gesto de aprovação na tela. Uma
# peça saía "aprovada pelo creator" com o próprio agente assinando o nome dele —
# medido em 2026-08-09, produção inteira do bruto a 4 entregáveis, portão verde,
# tela nunca aberta. O único humano do loop era opcional.
#
# `ui-save` só o SERVIDOR escreve, e só ao receber um POST de `api/salvar` com
# `tipo: "aprovacao"` — o que exige a página aberta e o botão clicado. O CLI
# continua existindo (há máquina sem browser), mas se declara degradado, e o
# portão da entrega trata os dois de formas diferentes.
FONTE_UI = "ui-save"
FONTE_CLI = "cli-degradado"
FONTE_DESCONHECIDA = "anterior-ao-registro-de-fonte"

# O envelope de aprovação (SPEC-17) não tem `contrato` no payload: ele não é um
# PEDIDO, é o registro de um ato que o servidor já executou. O `tipo` do envelope
# é o que o identifica, e o alvo default é o mesmo do `qc-portao.py`.
TIPO_APROVACAO = "aprovacao"
ALVO_APROVACAO_PADRAO = "fase-1"
SUFIXO_PARCIAL = ".parcial"     # ACRESCENTADO, nunca `with_suffix('.tmp')`
CASAS = 6                       # segundos são derivados; 6 casas é leitura humana

# defaults do `montar.sh` para os campos de enquadramento que a EDL pode omitir —
# vêm de lá (`.zoom // 1`, `.cx // 0.5`, `.cy // 0.5`) e são geometria normalizada,
# não formato de peça: não há pixel nenhum nestes três números.
PADRAO_ENQUADRAMENTO = {"zoom": 1.0, "cx": 0.5, "cy": 0.5}
CAMPOS_CONHECIDOS_EDL = ("src", "start", "end", "fala", "beat", "zoom", "cx", "cy")


# ──────────────────────────────────────────────────────────────────── utilidades

def _agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


def _sha1_texto(txt):
    return "sha1:" + hashlib.sha1(txt.encode("utf-8")).hexdigest()


def _ler_json(caminho, default=None):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _escrever_atomico(destino, obj):
    """tmp + os.replace no MESMO diretório. O sufixo é ACRESCENTADO.

    `Path.with_suffix('.tmp')` TROCA a extensão — funciona no ref-A por acidente
    de nomenclatura e colidiria aqui no dia em que existir `ajustes.tar` ao lado.
    O pid no nome é o que faz 50 escritas concorrentes não se atropelarem no
    mesmo temporário; quem varre o diretório ignora `*.parcial`."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    parcial = "%s.%d%s" % (destino, os.getpid(), SUFIXO_PARCIAL)
    with open(parcial, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(parcial, destino)
    return os.path.abspath(destino)


def _slug(txt):
    s = re.sub(r"[^0-9a-zA-Z]+", "-", str(txt).strip().lower()).strip("-")
    return s or "seg"


def dir_preview(dir_producao):
    return os.path.join(dir_producao, DIR_PREVIEW)


# ────────────────────────────────────────────────────────────── ffprobe (cacheado)

_CACHE_PROBE = {}


def _probe(caminho, campos, fluxo="v", formato=False):
    """Uma chamada de ffprobe por (arquivo, campos) por processo.

    O `preview_server.py:271` do ref-A sonda a cada requisição, com poll de 2 s:
    ~1.200 subprocessos numa sessão de 40 min. Aqui o ffprobe roda na GERAÇÃO e o
    número fica gravado no `estado.json`; quem precisa de frescor regenera."""
    chave = (os.path.abspath(caminho), campos, fluxo, formato)
    if chave in _CACHE_PROBE:
        return _CACHE_PROBE[chave]
    cmd = ["ffprobe", "-v", "error"]
    if not formato:
        cmd += ["-select_streams", fluxo]
    cmd += ["-show_entries", ("format=" if formato else "stream=") + campos,
            "-of", "json", caminho]
    saida = subprocess.run(cmd, capture_output=True, text=True).stdout
    dados = _ler_json_texto(saida) or {}
    itens = dados.get("format") if formato else (dados.get("streams") or [None])[0]
    _CACHE_PROBE[chave] = itens or {}
    return _CACHE_PROBE[chave]


def _ler_json_texto(txt):
    try:
        return json.loads(txt)
    except ValueError:
        return None


def _fps_de(caminho):
    r = _probe(caminho, "r_frame_rate").get("r_frame_rate") or ""
    try:
        num, den = (r.split("/") + ["1"])[:2]
        num, den = int(num), int(den)
        return num / den if den else None
    except (ValueError, IndexError):
        return None


def _frames_de(caminho):
    """`nb_frames` do container quando ele existe; senão decodifica.

    ⚠️ Rótulo mente — por isso o campo `origem` viaja junto. Conferido nos 29
    segmentos de `peca-01`: `nb_frames` e `nb_read_frames` batem em
    29/29. Quando o container não declara, cai no `-count_frames`, que decodifica
    e é a verdade."""
    nb = _probe(caminho, "nb_frames").get("nb_frames")
    try:
        n = int(nb)
        if n > 0:
            return n, "nb_frames"
    except (TypeError, ValueError):
        pass
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", caminho],
        capture_output=True, text=True).stdout.strip().rstrip(",")
    try:
        return int(out), "count_frames"
    except ValueError:
        return None, "indisponivel"


def _midia(caminho):
    """Dimensão, fps, duração, pix_fmt e tags de cor de um arquivo — do ffprobe.

    🔴 Nada aqui é prescrito. Nenhum consumidor deste bloco pode assumir formato:
    o rótulo de cor, em particular, MENTE neste build (`-pix_fmt gray` sai
    `yuvj420p`, `-color_primaries` é ignorado na saída). Por isso as três tags
    viajam cruas e o veredito de cor é da SPEC-11 (`detect-cor.py`), não daqui."""
    s = _probe(caminho, "width,height,r_frame_rate,pix_fmt,"
                        "color_primaries,color_transfer,color_space")
    f = _probe(caminho, "duration", formato=True)
    st = os.stat(caminho)
    try:
        dur = round(float(f.get("duration")), CASAS)
    except (TypeError, ValueError):
        dur = None
    return {
        "largura": s.get("width"), "altura": s.get("height"),
        "fps": _fps_de(caminho), "duracao_s": dur,
        "pix_fmt": s.get("pix_fmt"),
        "tags_cor": {"color_primaries": s.get("color_primaries"),
                     "color_trc": s.get("color_transfer"),
                     "colorspace": s.get("color_space")},
        "bytes": st.st_size, "mtime": int(st.st_mtime),
    }


# ─────────────────────────────────────────────────────────────────── §3.4 — o sid

def sid_de(segments):
    """Um id por segmento, estável sob mudança de borda, sem persistência.

    chave = `beat` quando existe; senão o basename do `src` sem extensão.
    sid   = "<slug da chave>#<ordinal da ocorrência dessa chave na EDL>".

    É o que torna o bug do `app.js:1826` INEXPRIMÍVEL neste contrato: mover
    `start`/`end` de um take em 0,3 s não muda o sid (é o caso que precisa
    sobreviver, porque a nota do usuário está grudada naquele take e o agente vai
    justamente reajustá-lo), e nada precisa ser gravado ou reconciliado —
    `bordas.py` pode reescrever a EDL inteira a partir do `janelas.json` e os sid
    saem iguais. Renomear o beat, inserir ou reordenar MUDA o sid, e isso é o
    comportamento certo: nesses casos a nota deve ser reavaliada, não
    silenciosamente reaproveitada."""
    ordinais, saida = {}, []
    for s in segments:
        chave = s.get("beat")
        if chave in (None, ""):
            src = s.get("src") or ""
            chave = os.path.splitext(os.path.basename(str(src)))[0]
        k = _slug(chave)
        n = ordinais.get(k, 0) + 1
        ordinais[k] = n
        saida.append("%s#%d" % (k, n))
    return saida


# ───────────────────────────────────────────────────────── leitura do lado do agente

def _agente(dir_producao):
    d = _ler_json(os.path.join(dir_preview(dir_producao), NOME_AGENTE), {})
    return d if isinstance(d, dict) else {}


def _gravar_agente(dir_producao, obj):
    return _escrever_atomico(os.path.join(dir_preview(dir_producao), NOME_AGENTE), obj)


# ──────────────────────────────────────────────────────────────── segs/ e sidecars

def _segs_no_disco(dir_producao):
    """`segs/segNNN.mp4` por índice NUMÉRICO — 2 e 3 dígitos.

    `sorted(glob.glob())` é lexicográfico e põe `seg100` entre `seg10` e `seg11`
    (era o bug de `qc-ataque.py:46`). Os nomes não são uniformes no repo: o
    `montar.sh` usa `%03d` hoje, as produções antigas usam `%02d`."""
    base = os.path.join(dir_producao, "segs")
    if not os.path.isdir(base):
        return {}
    achados = {}
    for nome in os.listdir(base):
        m = re.match(r"^seg(\d+)\.mp4$", nome)
        if m:
            achados[int(m.group(1))] = os.path.join("segs", nome)
    return achados


def _confere_sidecar(seg_edl, sidecar, video_sha_atual):
    """Campos do sidecar × EDL. Devolve (divergentes, não-comparáveis).

    🔴 A REGRA É ESTRUTURAL, NÃO UMA LISTA DE NOMES. O sidecar carrega duas
    coisas: cópias de campos da EDL (comparáveis) e DECISÕES DE RENDER que não
    têm contraparte na EDL (`perfil_video_sha`, `video_skip_frames`, …). Comparar
    as segundas contra `None` pinta a produção inteira de vermelho.

    Medido hoje, e é o motivo de a regra não poder ser uma lista branca: o
    `montar.sh` ganhou `video_skip_frames` no sidecar DURANTE esta onda (SPEC-07,
    J-cut). Um verificador com lista fixa teria acusado 3/3 segmentos sintéticos
    como divergentes por causa de um campo novo e legítimo.

      · chave presente na EDL            → compara (float com folga de 1e-6);
      · chave ausente na EDL mas com
        default no `montar.sh`
        (`zoom`/`cx`/`cy`)               → compara contra o default;
      · `perfil_video_sha`               → compara contra o perfil resolvido, e
                                           SÓ quando há perfil (sidecar anterior
                                           à SPEC-00 não tem o campo);
      · valor `null` no sidecar com a
        chave ausente na EDL             → não declarado dos dois lados (é o caso
                                           dos 18 sidecars de `peca-09`,
                                           escritos pelo fork `montar-vsl.py`);
      · qualquer outra                   → NÃO COMPARÁVEL: sai na lista de
                                           extras, visível, nunca silenciosa.
    """
    campos, extras = [], []
    for k, v_side in sorted(sidecar.items()):
        if k == "perfil_video_sha":
            if video_sha_atual is None:
                extras.append(k)
            elif v_side != video_sha_atual:
                campos.append(k)
            continue
        tem = k in seg_edl
        if not tem and v_side is None:
            continue
        if not tem and k not in PADRAO_ENQUADRAMENTO:
            extras.append(k)
            continue
        v_edl = seg_edl.get(k, PADRAO_ENQUADRAMENTO.get(k))
        if isinstance(v_side, (int, float)) and isinstance(v_edl, (int, float)) \
                and not isinstance(v_side, bool) and not isinstance(v_edl, bool):
            if abs(float(v_side) - float(v_edl)) > 1e-6:
                campos.append(k)
        elif v_side != v_edl:
            campos.append(k)
    return campos, extras


# ────────────────────────────────────────────────────────────────── §3.3 — gerar

def gerar(dir_producao, medir_timeline=False):
    """Lê o disco e devolve o estado. NÃO grava, NÃO conserta, NÃO renderiza."""
    dir_producao = os.path.abspath(dir_producao)
    if not os.path.isdir(dir_producao):
        sys.exit("não é diretório: %s" % dir_producao)
    ag = _agente(dir_producao)
    avisos = []

    # ── perfil (SPEC-00). A AUSÊNCIA é declarada, não suprida: `perfil_mod.carregar`
    # devolveria o FALLBACK (vertical a 30 fps) e o estado passaria a afirmar um
    # formato que ninguém mediu. Por isso o teste é pelo ARQUIVO.
    arq_perfil = os.path.join(dir_producao, "perfil.json")
    perfil = perfil_sha = zonas = None
    if os.path.isfile(arq_perfil):
        perfil = perfil_mod.carregar(dir_producao)
        perfil_sha = _sha256_arquivo(arq_perfil)
        zonas = (perfil.get("zonas_ui") or None)

    # ── EDL (v1 array ou v2 envelope, SPEC-05)
    env = edl_io.carregar(dir_producao)
    segs_edl = env["segments"]
    edl_schema = "benchmark.edl/v1" if edl_io.e_v1(dir_producao) else env.get("schema")
    fp_corte = edl_io.fingerprint(segs_edl)

    disco = _segs_no_disco(dir_producao)

    # ── formato: perfil quando existe, ffprobe do primeiro segmento quando não.
    #    Não há terceiro caminho: assumir é o que esta spec proíbe.
    if perfil:
        v = perfil["video"]
        formato = {"largura": int(v["largura"]), "altura": int(v["altura"]),
                   "fps": float(v["fps"]), "fonte": "perfil"}
    else:
        formato = {"largura": None, "altura": None, "fps": None, "fonte": None}
        primeiro = disco.get(min(disco)) if disco else None
        if primeiro:
            m = _midia(os.path.join(dir_producao, primeiro))
            formato = {"largura": m["largura"], "altura": m["altura"],
                       "fps": m["fps"], "fonte": "medido"}
            avisos.append("perfil.json ausente — formato medido dos segmentos; "
                          "zonas de UI indisponíveis")
        else:
            avisos.append("perfil.json ausente e nenhum segs/segNNN.mp4 para medir — "
                          "formato indisponível")

    video_sha = perfil_mod.video_sha(perfil) if perfil else None

    # ── timeline real (SPEC-05). Persistida (edl.json inline ou sidecar); a
    #    medição offline é OPT-IN e se identifica no bloco.
    tl = None
    try:
        tl = edl_io.timeline(dir_producao, exigir=False)
    except SystemExit as e:
        avisos.append("timeline_real presente mas VELHA (não descreve este corte): %s"
                      % str(e).splitlines()[0])
        tl = None
    if tl is None and medir_timeline:
        tl = edl_io.medir_timeline(dir_producao, gerado_por="estado.py --medir-timeline")
        avisos.append("timeline_real MEDIDA OFFLINE a partir dos segs/ (não está no "
                      "disco); nada foi gravado na produção")
    if tl is None:
        avisos.append("timeline_real ausente — coordenada de render indisponível "
                      "(Σ(end−start) erra até 353 ms; ver SPEC-05)")

    # ── segmentos
    sids = sid_de(segs_edl)
    fps_rascunho = formato.get("fps")
    segmentos, acc_rascunho, soma_nominal = [], 0.0, 0.0
    sem_sidecar, divergentes = [], []
    for i, s in enumerate(segs_edl):
        rel = disco.get(i)
        item = {"sid": sids[i], "i": i,
                "src": s.get("src"), "start": s.get("start"), "end": s.get("end"),
                "fala": s.get("fala"), "beat": s.get("beat"),
                "zoom": s.get("zoom"), "cx": s.get("cx"), "cy": s.get("cy"),
                "extras": {k: v for k, v in s.items()
                           if k not in CAMPOS_CONHECIDOS_EDL},
                "arquivo": rel}

        # régua do RASCUNHO: Σ(end−start). Legítima aqui e SÓ aqui — descreve a
        # timeline virtual que a UI compõe antes de existir render.
        dur_nominal = None
        if isinstance(s.get("start"), (int, float)) and isinstance(s.get("end"), (int, float)):
            dur_nominal = float(s["end"]) - float(s["start"])
        elif isinstance(s.get("f0"), int) and isinstance(s.get("f1"), int) and fps_rascunho:
            dur_nominal = (int(s["f1"]) - int(s["f0"])) / fps_rascunho
        if dur_nominal is not None:
            item["rascunho"] = {"ini_s": round(acc_rascunho, CASAS),
                                "dur_s": round(dur_nominal, CASAS)}
            acc_rascunho += dur_nominal
            soma_nominal += dur_nominal
        else:
            item["rascunho"] = None

        # medido: o que o arquivo renderizado É
        if rel:
            m = _midia(os.path.join(dir_producao, rel))
            nf, origem = _frames_de(os.path.join(dir_producao, rel))
            item["medido"] = {"frames": nf, "frames_origem": origem,
                              "fps": m["fps"], "largura": m["largura"],
                              "altura": m["altura"], "bytes": m["bytes"]}
        else:
            item["medido"] = None

        # saída: a régua do arquivo que existe — só da timeline_real
        if tl and i < len(tl["segments"]):
            t = tl["segments"][i]
            item["saida"] = {"ini_s": t["start_s"], "dur_s": t["dur_s"],
                             "ini_frame": t["start_frame"], "frames": t["frames"]}
        else:
            item["saida"] = None

        # procedência
        if rel is None:
            item["procedencia"] = {"estado": "nao_renderizado"}
        else:
            arq_side = os.path.join(dir_producao, rel[:-4] + ".json")
            side = _ler_json(arq_side)
            if not isinstance(side, dict):
                item["procedencia"] = {"estado": "ausente"}
                sem_sidecar.append(rel)
            else:
                campos, extras = _confere_sidecar(s, side, video_sha)
                if campos:
                    item["procedencia"] = {
                        "estado": "divergente", "campos": campos,
                        "sidecar": {k: side.get(k) for k in campos},
                        "edl": {k: s.get(k, PADRAO_ENQUADRAMENTO.get(k))
                                for k in campos}}
                    divergentes.append({"seg": rel, "sid": sids[i], "campos": campos,
                                        "sidecar": item["procedencia"]["sidecar"],
                                        "edl": item["procedencia"]["edl"]})
                else:
                    item["procedencia"] = {"estado": "ok"}
                if extras:
                    # decisões de render sem contraparte na EDL — visíveis, nunca
                    # silenciosas, e nunca motivo de reprovação.
                    item["procedencia"]["extras_sidecar"] = extras
        segmentos.append(item)

    orfaos = [disco[k] for k in sorted(disco) if k >= len(segs_edl) or k < 0]

    # ── renders
    declarado_corte = ag.get("render")
    declarado_entrega = ag.get("entregavel")
    renders, render_corrente, fp_render = [], None, None
    for caminho in sorted(glob.glob(os.path.join(dir_producao, "*.mp4"))):
        nome = os.path.basename(caminho)
        m = _midia(caminho)
        papel = ("corte" if nome == declarado_corte
                 else "entrega" if nome == declarado_entrega
                 else "corte" if (declarado_corte is None and nome == "v1-montado.mp4")
                 else "outro")
        fp = _sha1_texto("%s|%d|%d" % (nome, m["bytes"], m["mtime"]))
        nf, origem_f = _frames_de(caminho)
        renders.append({"papel": papel, "arquivo": nome, "fingerprint": fp,
                        "duracao_s": m["duracao_s"], "frames": nf,
                        "frames_origem": origem_f, "largura": m["largura"],
                        "altura": m["altura"], "fps": m["fps"],
                        "pix_fmt": m["pix_fmt"], "tags_cor": m["tags_cor"],
                        "bytes": m["bytes"], "mtime": m["mtime"]})
        if papel == "corte" and render_corrente is None:
            render_corrente, fp_render = nome, fp
    if render_corrente is None:
        avisos.append("nenhum render de montagem encontrado (v1-montado.mp4 ausente e "
                      "--render não declarado) — integridade sem régua de saída")

    # ── legendas
    legendas = None
    for nome in ("captions.json", "caps.json"):
        p = os.path.join(dir_producao, nome)
        if os.path.isfile(p):
            dados = _ler_json(p)
            n = (len(dados) if isinstance(dados, list)
                 else len(dados.get("words", [])) if isinstance(dados, dict) else None)
            legendas = {"arquivo": nome, "palavras": n}
            break

    # ── plano
    plano = None
    p_plano = os.path.join(dir_producao, "PLANO-EDICAO.md")
    if os.path.isfile(p_plano):
        plano = {"arquivo": "PLANO-EDICAO.md", "sha256": _sha256_arquivo(p_plano),
                 "mtime": int(os.stat(p_plano).st_mtime)}

    # ── integridade
    # 📐 `render_s` sai de FRAMES/fps, não da duração do container. Os dois
    # divergem 6,6 ms no `v1-montado.mp4` de `peca-03` (1987 frames = 66,2333 s;
    # o container declara 66,239974 s), e essa folga de origem desconhecida comeria
    # boa parte do frame de tolerância do `delta_real_ms`. Frames é a mesma unidade
    # da `timeline_real`, então a comparação é entre duas medidas do MESMO tipo.
    r_corrente = next((r for r in renders if r["arquivo"] == render_corrente), None)
    render_s = None
    if r_corrente:
        if r_corrente["frames"] and r_corrente["fps"]:
            render_s = round(r_corrente["frames"] / r_corrente["fps"], CASAS)
        else:
            render_s = r_corrente["duracao_s"]
    tl_s = tl["total_s"] if tl else None
    d_nom = round((tl_s - soma_nominal) * 1000.0, 1) if (tl_s is not None) else None
    d_real = (round((render_s - tl_s) * 1000.0, 1)
              if (tl_s is not None and render_s is not None) else None)
    um_frame_ms = (1000.0 / formato["fps"]) if formato.get("fps") else None
    if orfaos or divergentes or (d_real is not None and um_frame_ms is not None
                                 and abs(d_real) > um_frame_ms):
        veredito = "quebrado"
    elif sem_sidecar or tl is None or render_corrente is None:
        veredito = "suspeito"
    else:
        veredito = "ok"
    integridade = {
        "veredito": veredito,
        "soma_nominal_s": round(soma_nominal, CASAS) if soma_nominal else None,
        "timeline_real_s": tl_s,
        "render_s": render_s,
        "delta_nominal_ms": d_nom,
        "delta_real_ms": d_real,
        "segs_no_disco": len(disco), "segs_na_edl": len(segs_edl),
        "orfaos": orfaos, "sem_sidecar": sem_sidecar, "divergentes": divergentes,
    }

    # ── aprovações: o agente declara, o disco confirma (§3.6)
    aprovacoes = []
    for a in (ag.get("aprovacoes") or []):
        item = dict(a)
        # `fonte` ausente = registro anterior a 2026-08-10, quando só existia o
        # caminho de CLI. Nomear a omissão é mais honesto que assumir qualquer
        # das duas (achado A10).
        item.setdefault("fonte", FONTE_DESCONHECIDA)
        motivos = []
        if item.get("plano_sha256") and (not plano or plano["sha256"] != item["plano_sha256"]):
            motivos.append("plano_sha256 divergente")
        alvo_render = item.get("render")
        atual = next((r["fingerprint"] for r in renders if r["arquivo"] == alvo_render), None)
        if item.get("render_fingerprint") and atual != item["render_fingerprint"]:
            motivos.append("render_fingerprint divergente")
        item["valida"] = not motivos
        item["motivo"] = "; ".join(motivos) if motivos else None
        aprovacoes.append(item)

    # ── estilo vigente (§3.10 da SPEC-19): O CAMPO QUE A ABA LÊ E NINGUÉM GRAVAVA
    #
    # 🔴 Achado R-3 (2026-08-11). `preview/app/js/estilos.js:69` decide se a aba
    # ESTILO fica habilitada por `e?.estilo || e?.estilo_vigente` do estado, e o
    # `galeria.js:149` calcula `rerender = !portaoAberto() && jaTemEstilo()`. Os
    # dois campos existiam só no leitor: um grep na árvore por escritor devolvia
    # ZERO. Consequência medida na tela: estilo aplicado + portão fechado → a aba
    # aparecia DESABILITADA, e o creator não tinha por onde voltar para trocar o
    # estilo. O marcador `🔁 REFAÇA` do watcher era inalcançável — não porque
    # faltasse código no watcher, mas porque o caminho até ele não existia.
    #
    # Aqui é o lugar: `estilo-vigente.json` é escrito SÓ pelo
    # `escolha-estilo.py --aplicar`, e este arquivo é quem LÊ o disco e devolve o
    # estado. O resumo é deliberadamente curto — o estado é polled a cada 2 s, e
    # embutir o payload inteiro do estilo dobraria o corpo por nada: quem quer o
    # payload lê `estilo-vigente.json`, que está nomeado em `origem`.
    vig = _ler_json(os.path.join(dir_preview(dir_producao), "estilo-vigente.json"))
    estilo_vigente = None
    if isinstance(vig, dict) and isinstance(vig.get("estilo"), dict):
        pay = vig["estilo"]
        estilo_vigente = {
            "aplicado_em": vig.get("aplicado_em"),
            "revisao_aplicada": vig.get("revisao_aplicada"),
            "arquivo": ".preview/estilo-vigente.json",
            "origem": vig.get("origem"),
            "legenda": pay.get("legenda"),
            "headline": pay.get("headline"),
            "acento": pay.get("acento"),
            "gramatica_plano": pay.get("gramatica_plano"),
            "elementos": sorted(k for k, v in (pay.get("elementos") or {}).items() if v),
        }

    est = {
        "contrato": CONTRATO,
        "revisao": int(_ler_json(os.path.join(dir_preview(dir_producao), NOME_ESTADO),
                                 {}).get("revisao") or 0),
        "gerado_em": _agora(),
        "gerado_por": "estado.py",
        "producao": {"slug": os.path.basename(dir_producao.rstrip("/")),
                     "dir": ".", "creator": ag.get("creator"),
                     "titulo": ag.get("titulo")},
        "fase": ag.get("fase"),
        "mensagem": ag.get("mensagem"),
        "portao": ag.get("portao"),
        "portao_forcado": ag.get("portao_forcado"),
        "perfil": perfil, "perfil_sha256": perfil_sha,
        "formato": formato, "zonas_ui": zonas,
        "edl_schema": edl_schema,
        "fingerprint_corte": fp_corte,
        "segmentos": segmentos,
        "timeline_real": tl,
        "renders": renders,
        "render_corrente": render_corrente,
        "fingerprint_render": fp_render,
        "legendas": legendas,
        "plano": plano,
        "aprovacoes": aprovacoes,
        "estilo_vigente": estilo_vigente,
        "integridade": integridade,
        "ultimo_ajuste_aplicado": ag.get("ultimo_ajuste_aplicado"),
        "qc": [],
        "avisos": avisos,
    }
    return est


def escrever(dir_producao, est):
    """tmp + os.replace; `revisao` monotônica; devolve o caminho."""
    destino = os.path.join(dir_preview(dir_producao), NOME_ESTADO)
    atual = _ler_json(destino, {}) or {}
    est = dict(est)
    est["revisao"] = int(atual.get("revisao") or 0) + 1
    est["gerado_em"] = _agora()
    return _escrever_atomico(destino, est)


# ────────────────────────────────────────────── §3.5 — o par de coordenadas

def coordenada_render(est, sid, ini, fim=None):
    """(ini, fim) do RASCUNHO → (ini, fim) no arquivo que existe. `None` sem régua.

    🔴 Devolver `None` é a resposta certa, não um degrau para um chute. É aqui
    que a proibição da §9 vira código: sem `timeline_real` não existe coordenada
    de render, ponto. A UI mostra a marcação desabilitada."""
    tl = est.get("timeline_real")
    if not tl:
        return None
    i = next((s["i"] for s in est["segmentos"] if s["sid"] == sid), None)
    if i is None or i >= len(tl["segments"]):
        return None
    seg = est["segmentos"][i]
    if not seg.get("rascunho"):
        return None
    base_rascunho = seg["rascunho"]["ini_s"]
    base_saida = tl["segments"][i]["start_s"]
    fora = {"ini": round(base_saida + (ini - base_rascunho), CASAS)}
    if fim is not None:
        fora["fim"] = round(base_saida + (fim - base_rascunho), CASAS)
    return fora


# ──────────────────────────────────────────────────────────────── §4 — validação

_TIPOS = {"str": str, "num": (int, float), "bool": bool, "list": list, "dict": dict}


def _tipo_ok(v, nome):
    if nome == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TIPOS[nome])


_ESQ_AJUSTES = {
    "obrigatorios": {"contrato": "str", "salvo_em": "str", "revisao_base": "num"},
    "opcionais": {"fingerprint_corte": "str", "fingerprint_render": "str",
                  "render_alvo": "str", "notas": "list", "operacoes": "list",
                  "elementos": "list", "observacao": "str"},
}
_ESQ_ESTILO = {
    "obrigatorios": {"contrato": "str", "salvo_em": "str", "revisao_base": "num"},
    "opcionais": {"rerender": "bool", "legenda": "str", "headline": "str",
                  "acento": "str", "acento_usado": "bool", "elementos": "dict",
                  "gramatica_plano": "str", "observacao": "str"},
}
OPS = ("ajustar", "remover", "restaurar")


def validar(obj, contrato=None, est=None, galeria=None):
    """Devolve a lista de violações (vazia = ok). Nunca levanta por conteúdo.

    Confere, além de tipo e campo desconhecido, as três coisas que só o ESTADO
    sabe: `sid` que não existe no corte, `revisao_base` no futuro, e — a que
    fecha a §9 — coordenada de render preenchida sem `timeline_real`."""
    erros = []
    if not isinstance(obj, dict):
        return ["objeto tem que ser dict, veio %s" % type(obj).__name__]
    contrato = contrato or obj.get("contrato")
    if contrato == CONTRATO:
        return _validar_estado(obj)
    # SPEC-19 §4.5, ponto 1: o v2 do estilo é validado por quem o define.
    if contrato in (CONTRATO_ESTILO_V2, CONTRATO_ESTILO_V3):
        ee = _escolha_estilo()
        if ee is None:
            return ["%s exige escolha-estilo.py, que não está ao lado" % contrato]
        return ee.validar(obj, galeria)
    esq = {CONTRATO_AJUSTES: _ESQ_AJUSTES, CONTRATO_ESTILO: _ESQ_ESTILO}.get(contrato)
    if esq is None:
        return ["contrato desconhecido: %r (esperado %s, %s, %s ou %s)"
                % (contrato, CONTRATO, CONTRATO_AJUSTES, CONTRATO_ESTILO,
                   "%s ou %s" % (CONTRATO_ESTILO_V2, CONTRATO_ESTILO_V3))]
    if obj.get("contrato") != contrato:
        erros.append("contrato: %r != %r" % (obj.get("contrato"), contrato))
    conhecidos = dict(esq["obrigatorios"]); conhecidos.update(esq["opcionais"])
    for k in sorted(obj):
        if k not in conhecidos:
            erros.append("campo desconhecido: %r" % k)
        elif obj[k] is not None and not _tipo_ok(obj[k], conhecidos[k]):
            erros.append("campo %r: esperado %s, veio %s"
                         % (k, conhecidos[k], type(obj[k]).__name__))
    for k in esq["obrigatorios"]:
        if k not in obj:
            erros.append("campo obrigatório ausente: %r" % k)

    sids = {s["sid"] for s in est["segmentos"]} if est else None
    tem_tl = bool(est.get("timeline_real")) if est else None

    if contrato == CONTRATO_AJUSTES:
        for n, nota in enumerate(obj.get("notas") or []):
            pref = "notas[%d]" % n
            if not isinstance(nota, dict):
                erros.append("%s: tem que ser objeto" % pref); continue
            for k in sorted(nota):
                if k not in ("sid", "rascunho", "render", "fase", "texto"):
                    erros.append("%s: campo desconhecido %r" % (pref, k))
            if "i" in nota:
                erros.append("%s: índice posicional é PROIBIDO no canal de volta "
                             "(§3.4) — use `sid`" % pref)
            if sids is not None and nota.get("sid") not in (None,) and nota["sid"] not in sids:
                erros.append("%s: sid inexistente no corte: %r" % (pref, nota["sid"]))
            if tem_tl is False and nota.get("render") is not None:
                erros.append("%s: `render` preenchido sem `timeline_real` — "
                             "coordenada de render aproximada é PROIBIDA (§9)" % pref)
        for n, op in enumerate(obj.get("operacoes") or []):
            pref = "operacoes[%d]" % n
            if not isinstance(op, dict):
                erros.append("%s: tem que ser objeto" % pref); continue
            for k in sorted(op):
                if k not in ("sid", "op", "para", "de"):
                    erros.append("%s: campo desconhecido %r" % (pref, k))
            if op.get("op") not in OPS:
                erros.append("%s: op %r fora do enum %s" % (pref, op.get("op"), list(OPS)))
            if sids is not None and op.get("sid") not in sids:
                erros.append("%s: sid inexistente no corte: %r" % (pref, op.get("sid")))
    if est is not None and isinstance(obj.get("revisao_base"), (int, float)):
        if obj["revisao_base"] > int(est.get("revisao") or 0):
            erros.append("revisao_base %s está no FUTURO (estado está em %s)"
                         % (obj["revisao_base"], est.get("revisao")))
    return erros


_CAMPOS_ESTADO = (
    "contrato", "revisao", "gerado_em", "gerado_por", "producao", "fase", "mensagem",
    "portao", "portao_forcado", "perfil", "perfil_sha256", "formato", "zonas_ui",
    "edl_schema",
    "fingerprint_corte", "segmentos", "timeline_real", "renders", "render_corrente",
    "fingerprint_render", "legendas", "plano", "aprovacoes", "estilo_vigente",
    "integridade", "ultimo_ajuste_aplicado", "qc", "avisos")
_CAMPOS_SEG = ("sid", "i", "src", "start", "end", "fala", "beat", "zoom", "cx", "cy",
               "extras", "arquivo", "rascunho", "medido", "saida", "procedencia")
_PROCEDENCIA = ("ok", "ausente", "divergente", "orfao", "nao_renderizado")


def _validar_estado(est):
    erros = []
    for k in sorted(est):
        if k not in _CAMPOS_ESTADO:
            erros.append("campo desconhecido: %r" % k)
    for k in _CAMPOS_ESTADO:
        if k not in est:
            erros.append("campo obrigatório ausente: %r" % k)
    if est.get("contrato") != CONTRATO:
        erros.append("contrato: %r != %r" % (est.get("contrato"), CONTRATO))
    if not isinstance(est.get("revisao"), int):
        erros.append("revisao tem que ser inteiro")
    vistos = set()
    for s in est.get("segmentos") or []:
        for k in sorted(s):
            if k not in _CAMPOS_SEG:
                erros.append("segmentos[%s]: campo desconhecido %r" % (s.get("i"), k))
        if s.get("sid") in vistos:
            erros.append("sid duplicado: %r" % s.get("sid"))
        vistos.add(s.get("sid"))
        proc = s.get("procedencia") or {}
        if proc.get("estado") not in _PROCEDENCIA:
            erros.append("segmentos[%s]: procedencia %r fora do enum %s"
                         % (s.get("i"), proc.get("estado"), list(_PROCEDENCIA)))
        for k in sorted(proc):
            if k not in ("estado", "campos", "sidecar", "edl", "extras_sidecar"):
                erros.append("segmentos[%s]: procedencia.%s desconhecido"
                             % (s.get("i"), k))
    if est.get("timeline_real") is None:
        for s in est.get("segmentos") or []:
            if s.get("saida") is not None:
                erros.append("segmentos[%s]: `saida` preenchida sem timeline_real"
                             % s.get("i"))
    f = est.get("formato") or {}
    if f.get("fonte") not in ("perfil", "medido", None):
        erros.append("formato.fonte %r fora do enum" % f.get("fonte"))
    if f.get("fonte") == "medido" and est.get("zonas_ui") is not None:
        erros.append("zonas_ui preenchida sem perfil — as frações vêm do perfil (§3.8)")
    ver = (est.get("integridade") or {}).get("veredito")
    if ver not in ("ok", "suspeito", "quebrado"):
        erros.append("integridade.veredito %r fora do enum" % ver)
    return erros


# ────────────────────────────────────────────── §3.12 — o canal de volta

def _tipo_do_contrato(c):
    return {CONTRATO_AJUSTES: "ajustes", CONTRATO_ESTILO: "estilo",
            CONTRATO_ESTILO_V2: "estilo", CONTRATO_ESTILO_V3: "estilo"}.get(c)


def _desembrulhar(caminho):
    """Envelope da SPEC-17 ou objeto cru — devolve (tipo, payload, salvo_em)."""
    obj = _ler_json(caminho)
    if not isinstance(obj, dict):
        return None
    if obj.get("schema") == ENVELOPE:
        pay = obj.get("payload")
        if not isinstance(pay, dict):
            return None
        return {"arquivo": caminho, "envelope": obj, "payload": pay,
                "tipo": obj.get("tipo") or _tipo_do_contrato(pay.get("contrato")),
                "salvo_em": obj.get("salvo_em") or pay.get("salvo_em") or ""}
    tipo = _tipo_do_contrato(obj.get("contrato"))
    if tipo is None:
        return None
    return {"arquivo": caminho, "envelope": None, "payload": obj, "tipo": tipo,
            "salvo_em": obj.get("salvo_em") or ""}


def pendentes(dir_producao):
    """A fila do canal de volta, por `salvo_em`, do mais antigo ao mais novo.

    Junta os dois caminhos de entrada da §3.12: o envelope carimbado que o
    servidor da SPEC-17 grava em `pendentes/`, e o objeto CRU em
    `.preview/ajustes.json` / `.preview/estilo.json` (agente à mão, teste,
    fixture). `*.parcial` é ignorado — é escrita em curso, não evento."""
    prev = dir_preview(dir_producao)
    fila = []
    dpend = os.path.join(prev, "pendentes")
    if os.path.isdir(dpend):
        for nome in sorted(os.listdir(dpend)):
            if not nome.endswith(".json") or nome.endswith(SUFIXO_PARCIAL):
                continue
            it = _desembrulhar(os.path.join(dpend, nome))
            if it:
                fila.append(it)
    for nome, tipo in (("ajustes.json", "ajustes"), ("estilo.json", "estilo")):
        p = os.path.join(prev, nome)
        if os.path.isfile(p):
            it = _desembrulhar(p)
            if it:
                it["tipo"] = it["tipo"] or tipo
                fila.append(it)
    fila.sort(key=lambda x: (x["salvo_em"], os.path.basename(x["arquivo"])))
    return fila


def _carimbo(salvo_em):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", salvo_em or "")
    if m:
        return "%s%s%sT%s%s%s" % m.groups()
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")


def _arquivar(dir_producao, item, extra):
    """Move para `aplicados/`. O ACK é o MOVE, nunca o delete.

    O delete-como-ACK vem do `watch_edits.py:129-130` e existe lá porque não há
    para onde mover. Mover preserva o que o usuário pediu, com carimbo, ao lado da
    produção — o watcher re-arma igual (o arquivo sumiu de `pendentes/`)."""
    apl = os.path.join(dir_preview(dir_producao), "aplicados")
    os.makedirs(apl, exist_ok=True)
    origem = item["arquivo"]
    if os.path.dirname(os.path.abspath(origem)).endswith(os.sep + "pendentes"):
        nome = os.path.basename(origem)
    else:
        nome = "%s-%s.json" % (_carimbo(item["salvo_em"]), item["tipo"])
    corpo = dict(item["envelope"]) if item["envelope"] else {
        "schema": ENVELOPE, "tipo": item["tipo"], "salvo_em": item["salvo_em"],
        "origem": {"ua": "arquivo cru (sem servidor)"}, "payload": item["payload"]}
    corpo.update(extra)
    destino = os.path.join(apl, nome)
    _escrever_atomico(destino, corpo)
    if os.path.abspath(origem) != os.path.abspath(destino):
        os.remove(origem)
    return destino


def _ack_aprovacao(dir_producao, est, item, superados):
    """ACK do envelope de aprovação: confere, NÃO reaplica, arquiva.

    O que se confere é só o que o disco pode confirmar. Uma aprovação registrada
    pelo servidor já está em `estado.aprovacoes` com `fonte: ui-save` e o `pid`
    da sessão; se ela NÃO estiver lá, alguém gravou o envelope sem o servidor
    executar, e isso é achado — não silêncio.
    """
    pay = item["payload"] or {}
    alvo_ap = str(pay.get("alvo") or ALVO_APROVACAO_PADRAO)
    registradas = [a for a in (est.get("aprovacoes") or [])
                   if a.get("alvo") == alvo_ap]
    if not registradas:
        sys.exit(
            "%s é envelope de aprovação de %r, e o estado NÃO tem aprovação "
            "desse alvo. O servidor grava a aprovação no POST — sem ela no "
            "estado, este envelope foi criado fora do fluxo da tela. Rode "
            "`estado.py %s` para reler o disco; se continuar ausente, a "
            "aprovação não aconteceu e mover o arquivo esconderia isso."
            % (item["arquivo"], alvo_ap, dir_producao))
    reg = registradas[-1]
    avisos = []
    por_env = pay.get("por")
    if por_env and reg.get("por") and por_env != reg.get("por"):
        avisos.append("`por` do envelope (%r) != o registrado (%r)"
                      % (por_env, reg.get("por")))
    if reg.get("fonte") != FONTE_UI:
        avisos.append("a aprovação registrada tem fonte %r, não %r — este "
                      "envelope vem da tela e o registro não"
                      % (reg.get("fonte"), FONTE_UI))
    if not reg.get("valida"):
        avisos.append("a aprovação registrada está INVÁLIDA: %s"
                      % (reg.get("motivo") or "sem motivo"))
    for s in superados:
        _arquivar(dir_producao, s,
                  {"ignorado": "superado por %s" % os.path.basename(item["arquivo"])})
    agora = _agora()
    destino = _arquivar(dir_producao, item,
                        {"conferido_em": agora, "reaplicado": False,
                         "conferido_contra": {"alvo": alvo_ap,
                                              "em": reg.get("em"),
                                              "por": reg.get("por"),
                                              "fonte": reg.get("fonte"),
                                              "valida": reg.get("valida")},
                         "avisos": avisos or None})
    ack = {"tipo": item["tipo"], "salvo_em": item["salvo_em"],
           "revisao_base": None, "aplicado_em": agora,
           "arquivo": os.path.relpath(destino, dir_producao),
           "conflito": "; ".join(avisos) or None,
           "superados": len(superados), "reaplicado": False}
    ag = _agente(dir_producao)
    ag["ultimo_ajuste_aplicado"] = ack
    _gravar_agente(dir_producao, ag)
    escrever(dir_producao, gerar(dir_producao))
    for a in avisos:
        print("aviso: %s" % a, file=sys.stderr)
    return {"item": item, "ack": ack, "destino": destino, "superados": superados}


def consumir(dir_producao, alvo, mesmo_com_conflito=False):
    """Um pendente por vez: desembrulha, valida, confere, MOVE e registra o ACK.

    `alvo` é um caminho de arquivo OU um tipo ("ajustes"/"estilo"). Com dois
    pendentes do mesmo tipo na fila, o MAIS NOVO vence e o mais antigo vai para
    `aplicados/` com `ignorado` preenchido — nunca aplicado em cima."""
    est = _ler_json(os.path.join(dir_preview(dir_producao), NOME_ESTADO))
    if est is None:
        sys.exit("sem .preview/estado.json em %s — rode `estado.py <dir>` antes de "
                 "consumir (a conferência de revisao_base precisa do estado)."
                 % dir_producao)
    fila = pendentes(dir_producao)
    if os.path.exists(alvo):
        escolhidos = [i for i in fila
                      if os.path.abspath(i["arquivo"]) == os.path.abspath(alvo)]
        if not escolhidos:
            it = _desembrulhar(alvo)
            if it is None:
                sys.exit("%s não é envelope %s nem objeto de contrato conhecido"
                         % (alvo, ENVELOPE))
            escolhidos = [it]
        superados = []
    else:
        mesmos = [i for i in fila if i["tipo"] == alvo]
        if not mesmos:
            return None
        escolhidos, superados = [mesmos[-1]], mesmos[:-1]
    item = escolhidos[0]

    # ── o envelope de APROVAÇÃO (achado R-5, 2026-08-11)
    #
    # 🔴 O watcher imprime, para TODO evento, "aplicar e mover para aplicados/:
    # <arquivo>", e o único executável que move é este. Para a aprovação ele
    # rejeitava com "contrato desconhecido: None" — o payload da aprovação não
    # tem `contrato`, porque ela não é um pedido de trabalho: o servidor já a
    # EXECUTOU no momento do POST (`servidor.py:_efeito_do_evento`), que é o que
    # dá à fonte `ui-save` um significado que o CLI não imita. Sobrava um `mv`
    # manual sem documentação, e o registro do que a UI fez ficava para sempre
    # em `pendentes/`, indistinguível de trabalho não feito.
    #
    # Aqui o consumo é ACK, não aplicação: confere o que dá conferir contra o
    # estado (a aprovação existe? o alvo e o `por` batem?), NÃO reaplica, e move.
    if item["tipo"] == TIPO_APROVACAO:
        return _ack_aprovacao(dir_producao, est, item, superados)

    # SPEC-19 §4.5, ponto 2: quando o tipo é `estilo`, o vocabulário do catálogo
    # entra na validação e o digest sai do `escolha-estilo.py`. ESTE arquivo
    # ROTEIA; ele não executa. Consumo duplo do mesmo pendente vira corrida de
    # ACK, então há um dono só por tipo (§9.8).
    gal = _galeria_de(dir_producao) if item["tipo"] == "estilo" else None
    erros = validar(item["payload"], est=est, galeria=gal)
    if erros:
        sys.exit("%s VIOLA o contrato (%d):\n  %s"
                 % (item["arquivo"], len(erros), "\n  ".join(erros)))

    conflitos = []
    pay = item["payload"]
    if pay.get("fingerprint_corte") and pay["fingerprint_corte"] != est.get("fingerprint_corte"):
        conflitos.append("o CORTE mudou desde que o usuário salvou "
                         "(fingerprint_corte %s → %s)"
                         % (pay["fingerprint_corte"], est.get("fingerprint_corte")))
    if pay.get("fingerprint_render") and pay["fingerprint_render"] != est.get("fingerprint_render"):
        conflitos.append("o RENDER mudou desde que o usuário salvou "
                         "(fingerprint_render %s → %s)"
                         % (pay["fingerprint_render"], est.get("fingerprint_render")))
    if conflitos and not mesmo_com_conflito:
        print("CONFLITO — nada foi aplicado nem movido:\n  %s\n"
              "As marcações do usuário apontam para um estado que não existe mais. "
              "Reabra o preview e peça para ele remarcar, ou rode de novo com "
              "--mesmo-com-conflito se souber que as posições continuam valendo."
              % "\n  ".join(conflitos), file=sys.stderr)
        raise SystemExit(2)

    for s in superados:
        _arquivar(dir_producao, s,
                  {"ignorado": "superado por %s" % os.path.basename(item["arquivo"])})

    agora = _agora()
    destino = _arquivar(dir_producao, item, {"aplicado_em": agora})
    ack = {"tipo": item["tipo"], "salvo_em": item["salvo_em"],
           "revisao_base": pay.get("revisao_base"), "aplicado_em": agora,
           "arquivo": os.path.relpath(destino, dir_producao),
           "conflito": "; ".join(conflitos) or None,
           "superados": len(superados)}
    if item["tipo"] == "ajustes":
        ack["notas"] = len(pay.get("notas") or [])
        ack["operacoes"] = len(pay.get("operacoes") or [])
        ack["elementos"] = len(pay.get("elementos") or [])
    ag = _agente(dir_producao)
    ag["ultimo_ajuste_aplicado"] = ack
    _gravar_agente(dir_producao, ag)
    escrever(dir_producao, gerar(dir_producao))
    return {"item": item, "ack": ack, "destino": destino, "superados": superados}


# ──────────────────────────────────────────────────────────────── §3.11 — resumo

def _n(x):
    return "—" if x is None else ("%.3f" % x if isinstance(x, float) else str(x))


def resumo(obj, galeria=None):
    """Digest legível de ajustes/estilo — o que o watcher imprime.

    Mora AQUI, e não no watcher da SPEC-17, porque quem conhece o schema é quem o
    define: no ref-A, 55% do `watch_edits.py` é digest amarrado ao schema, e
    qualquer campo novo obriga a editar dois arquivos. Depende SÓ do payload —
    é o que faz o resumo do caminho cru e o do envelope saírem byte a byte
    idênticos (§7.12)."""
    c = obj.get("contrato")
    if c in (CONTRATO_ESTILO_V2, CONTRATO_ESTILO_V3):
        ee = _escolha_estilo()
        if ee is not None:
            return ee.resumo(obj, galeria)
        return ("estilo de catálogo sem escolha-estilo.py ao lado: "
                "não tenho como digerir o vocabulário de catálogo")
    if c == CONTRATO_AJUSTES:
        L = ["ajustes · revisao_base %s · alvo %s"
             % (obj.get("revisao_base"), obj.get("render_alvo") or "—")]
        notas = obj.get("notas") or []
        L.append("  %d nota(s)" % len(notas))
        for n in notas:
            r, d = n.get("render"), n.get("rascunho") or {}
            L.append("    · %s  rascunho %s–%s  render %s"
                     % (n.get("sid") or "(livre)", _n(d.get("ini")), _n(d.get("fim")),
                        "%s–%s" % (_n(r.get("ini")), _n(r.get("fim"))) if r
                        else "— (sem timeline_real: coordenada de render indisponível)"))
            if n.get("texto"):
                L.append("      \"%s\"" % n["texto"])
        ops = obj.get("operacoes") or []
        L.append("  %d operação(ões)" % len(ops))
        for o in ops:
            de, para = o.get("de") or {}, o.get("para") or {}
            if o.get("op") == "ajustar":
                L.append("    · %s  ajustar  start %s → %s · end %s → %s"
                         % (o.get("sid"), _n(de.get("start")), _n(para.get("start")),
                            _n(de.get("end")), _n(para.get("end"))))
            else:
                L.append("    · %s  %s  (%s–%s)"
                         % (o.get("sid"), o.get("op"), _n(de.get("start")),
                            _n(de.get("end"))))
        els = obj.get("elementos") or []
        if els:
            L.append("  %d elemento(s)" % len(els))
            for e in els:
                p = e.get("para") or {}
                L.append("    · %s  %s → %s–%s" % (e.get("ref"), e.get("op"),
                                                   _n(p.get("ini")), _n(p.get("fim"))))
        if any(o.get("op") in ("ajustar", "remover", "restaurar") for o in ops):
            L.append("  ⚠️ implica REMONTAR (bordas.py → montar.sh → audio-exato.py), "
                     "não só re-render do alpha")
        return "\n".join(L)
    if c == CONTRATO_ESTILO:
        L = ["estilo · revisao_base %s · rerender: %s"
             % (obj.get("revisao_base"), "sim" if obj.get("rerender") else "não")]
        L.append("  legenda: %s · headline: %s"
                 % (obj.get("legenda") or "—", obj.get("headline") or "—"))
        if obj.get("acento"):
            L.append("  acento: %s (%s)" % (obj["acento"],
                     "usado" if obj.get("acento_usado") else
                     "NÃO usado — nenhum estilo escolhido pinta acento; não invente onde"))
        el = obj.get("elementos") or {}
        dentro = [k for k in sorted(el) if el[k]]
        fora = [k for k in sorted(el) if not el[k]]
        L.append("  dentro: %s" % (", ".join(dentro) or "—"))
        # caixa desmarcada é um NÃO EXPLÍCITO, não silêncio.
        L.append("  fora: %s" % (", ".join(fora) or "—"))
        if obj.get("gramatica_plano"):
            L.append("  gramática de plano: %s  ⚠️ afeta o CORTE (zoom/cx/cy na EDL): "
                     "aceitar implica REMONTAR, não só re-render do alpha"
                     % obj["gramatica_plano"])
        if obj.get("observacao"):
            L.append("  obs: %s" % obj["observacao"])
        return "\n".join(L)
    return "objeto de contrato desconhecido: %r" % c


def resumo_aprovacao(envelope) -> str:
    """Digest do envelope de APROVAÇÃO. Ele não tem `contrato` no payload — não é
    pedido de trabalho, é o registro de um ato que o servidor já executou — e por
    isso não passa pelo `resumo()`, que roteia por contrato."""
    pay = (envelope or {}).get("payload") or {}
    conf = (envelope or {}).get("conferido_contra") or {}
    L = ["APROVAÇÃO CONFERIDA (não reaplicada — o servidor a gravou no POST)",
         "  · alvo: %s · por: %s" % (pay.get("alvo") or ALVO_APROVACAO_PADRAO,
                                    pay.get("por") or "—")]
    if conf:
        L.append("  · registrada no estado em %s · fonte %s · válida: %s"
                 % (conf.get("em") or "—", conf.get("fonte") or "—",
                    "sim" if conf.get("valida") else "NÃO"))
    if pay.get("motivo"):
        L.append("  · motivo do creator: %s" % pay["motivo"])
    for av in ((envelope or {}).get("avisos") or []):
        L.append("  ⚠️  %s" % av)
    return "\n".join(L)


# ────────────────────────────────────────────────────── registrar uma aprovação

class ErroAprovacao(Exception):
    """Aprovação que não pôde ser registrada, com o porquê legível.

    🔴 EXISTE PORQUE `SystemExit` NÃO É `Exception`. `gerar()` nasceu como CLI e
    aborta com `sys.exit("edl.json não encontrado…")`. Quando o servidor de
    preview passou a chamar `registrar_aprovacao` de dentro de um handler HTTP,
    esse `SystemExit` atravessou o `except Exception` do handler, matou a thread
    e fechou a conexão SEM RESPOSTA: o browser via `ERR_EMPTY_RESPONSE`, tentava
    de novo, e a fila ganhou 6 envelopes do mesmo clique. Medido na tela em
    2026-08-10 — e é exatamente o tipo de defeito que DOM correto e API 200 não
    mostram, porque não houve API 200 nenhuma."""


def registrar_aprovacao(dir_producao, alvo, por, fonte=FONTE_CLI, motivo=None,
                        pid=None, ag=None, esperado=None):
    """Acrescenta uma aprovação ao estado do agente e devolve o registro.

    Existe como FUNÇÃO, e não só como flag de CLI, porque o servidor de preview
    precisa gravá-la ao receber o clique no botão APROVAR — e um `subprocess`
    disparado de dentro do handler HTTP seria o mesmo trabalho com um processo a
    mais e sem o `pid` da sessão, que é justamente a prova de que a UI estava de
    pé (achado A10). Quem chama passando `ag` fica responsável por gravá-lo.

    A aprovação nasce presa ao CONTEÚDO: `render_fingerprint` e `plano_sha256`
    vêm do disco no instante do clique, e é isso que faz "aprovou e depois
    mudou" ser detectável (exit 2 do `qc-portao.py`)."""
    proprio = ag is None
    if proprio:
        ag = _agente(dir_producao)
    try:
        est_previa = gerar(dir_producao)
    except SystemExit as e:
        raise ErroAprovacao(str(e) or "estado não pôde ser gerado") from e
    atual = {
        "alvo": "fase-2" if (est_previa.get("fase") or 1) >= 2 else "fase-1",
        "fingerprint_corte": est_previa.get("fingerprint_corte"),
        "fingerprint_render": est_previa.get("fingerprint_render"),
        "render_alvo": est_previa.get("render_corrente"),
        "plano_sha256": (est_previa.get("plano") or {}).get("sha256"),
    }
    if esperado is not None:
        divergentes = [k for k, v in esperado.items()
                       if k not in atual or atual.get(k) != v]
        if divergentes:
            raise ErroAprovacao(
                "o conteúdo mudou desde que a aprovação foi aberta: %s"
                % ", ".join(sorted(divergentes)))
    reg = {
        "alvo": alvo,
        "render": est_previa.get("render_corrente"),
        "render_fingerprint": est_previa.get("fingerprint_render"),
        "plano_sha256": (est_previa.get("plano") or {}).get("sha256"),
        "em": _agora(), "por": por, "fonte": fonte,
    }
    if motivo:
        reg["motivo_da_aprovacao"] = motivo
    if pid is not None:
        reg["sessao_pid"] = int(pid)
    ag.setdefault("aprovacoes", []).append(reg)
    if proprio:
        _gravar_agente(dir_producao, ag)
        escrever(dir_producao, gerar(dir_producao))
    return reg


def aprovacao_valida_de(dir_producao, alvo="fase-1"):
    """A última aprovação VÁLIDA de `alvo`, ou None. `valida` é o campo que o
    `gerar()` calcula conferindo sha do plano e fingerprint do render."""
    est = _ler_json(os.path.join(dir_preview(dir_producao), NOME_ESTADO)) or {}
    validas = [a for a in (est.get("aprovacoes") or [])
               if a.get("alvo") == alvo and a.get("valida")]
    return validas[-1] if validas else None


# ───────────────────────────────────────────────────────────────────────── CLI

def _cli(argv=None):
    ap = argparse.ArgumentParser(
        description="Contrato de dados da UI de aprovação (SPEC-16). "
                    "Escreve SÓ dentro de <dir-producao>/.preview/.")
    ap.add_argument("dir", help="diretório da produção")
    ap.add_argument("--fase", type=int)
    ap.add_argument("--mensagem")
    ap.add_argument("--portao", choices=("estilo", "nenhum"))
    ap.add_argument("--render", help="nome do render de MONTAGEM (papel 'corte')")
    ap.add_argument("--entregavel", help="nome do render de entrega")
    ap.add_argument("--creator", help="string OPACA, informativa; nenhum campo do "
                                      "contrato tem semântica que dependa dela")
    ap.add_argument("--titulo")
    ap.add_argument("--aprovar", help="alvo da aprovação (ex.: fase-1)")
    ap.add_argument("--por", default=os.environ.get("USER") or "agente")
    ap.add_argument("--fonte", choices=(FONTE_UI, FONTE_CLI), default=FONTE_CLI,
                    help="de onde a aprovação nasceu. O default é %s: só o "
                         "SERVIDOR grava %s, e só com o botão clicado."
                         % (FONTE_CLI, FONTE_UI))
    ap.add_argument("--motivo", help="o porquê da aprovação, texto livre")
    ap.add_argument("--force", action="store_true",
                    help="abre o portão de estilo sem aprovação de fase 1. "
                         "Exige --motivo e fica GRAVADO no estado.")
    ap.add_argument("--medir-timeline", action="store_true",
                    help="mede a timeline real offline a partir dos segs/ quando ela "
                         "não está no disco. NÃO grava nada na produção.")
    ap.add_argument("--pendentes", action="store_true")
    ap.add_argument("--consumir", metavar="ARQUIVO|aprovacao|ajustes|estilo")
    ap.add_argument("--mesmo-com-conflito", action="store_true")
    ap.add_argument("--validar", metavar="ARQUIVO.json")
    ap.add_argument("--mostrar", action="store_true")
    a = ap.parse_args(argv)

    if a.validar:
        obj = _ler_json(a.validar)
        if obj is None:
            sys.exit("não consegui ler JSON de %s" % a.validar)
        if isinstance(obj, dict) and obj.get("schema") == ENVELOPE:
            obj = obj.get("payload") or {}
        est = _ler_json(os.path.join(dir_preview(a.dir), NOME_ESTADO))
        erros = validar(obj, est=est, galeria=_galeria_de(a.dir))
        if erros:
            print("%s: %d violação(ões) do contrato %r"
                  % (a.validar, len(erros), obj.get("contrato")), file=sys.stderr)
            for e in erros:
                print("  · %s" % e, file=sys.stderr)
            return 1
        print("%s: ok (%s)" % (a.validar, obj.get("contrato")))
        return 0

    if a.pendentes:
        fila = [{"arquivo": os.path.relpath(i["arquivo"], a.dir), "tipo": i["tipo"],
                 "salvo_em": i["salvo_em"], "envelope": i["envelope"] is not None,
                 "contrato": i["payload"].get("contrato")} for i in pendentes(a.dir)]
        print(json.dumps(fila, ensure_ascii=False, indent=2))
        return 0

    if a.consumir:
        r = consumir(a.dir, a.consumir, mesmo_com_conflito=a.mesmo_com_conflito)
        if r is None:
            print("nada pendente para %r" % a.consumir, file=sys.stderr)
            return 1
        if r["item"]["tipo"] == TIPO_APROVACAO:
            print(resumo_aprovacao(_ler_json(os.path.join(a.dir, r["ack"]["arquivo"]))))
        else:
            print(resumo(r["item"]["payload"], _galeria_de(a.dir)))
        for s in r["superados"]:
            print("  ignorado (superado): %s" % os.path.basename(s["arquivo"]),
                  file=sys.stderr)
        print("ACK: %s" % r["ack"]["arquivo"], file=sys.stderr)
        return 0

    if a.mostrar:
        print(json.dumps(gerar(a.dir, medir_timeline=a.medir_timeline),
                         ensure_ascii=False, indent=2))
        return 0

    # Fase 2 é uma transição, não só um rótulo. Sem direção v3 e plano visual
    # válido, `--fase 2` era o atalho que deixava uma peça Animada terminar só
    # com legenda. O gate de entrega continua separado e roda após o render.
    if a.fase is not None and a.fase >= 2:
        pv = _plano_visual()
        if pv is None:
            sys.stderr.write("estado.py: plano-visual.py não está disponível; "
                             "a Fase 2 não pode começar sem seu gate\n")
            return 1
        codigo, resultado = pv.validar(Path(a.dir).resolve(), "planejamento")
        if codigo:
            sys.stderr.write(
                "estado.py: Fase 2 bloqueada por plano visual inválido. "
                "Rode `plano-visual.py %s --validar planejamento`.\n" % a.dir)
            for erro in resultado.get("erros") or []:
                sys.stderr.write("  [%s] %s\n" %
                                 (erro.get("codigo", "ERRO"), erro.get("mensagem", "")))
            return 1

    # modo padrão: as flags do agente PERSISTEM, então `estado.py <dir>` sem flag
    # regenera preservando o que já foi declarado.
    ag = _agente(a.dir)
    for chave, valor in (("fase", a.fase), ("mensagem", a.mensagem),
                         ("render", a.render), ("entregavel", a.entregavel),
                         ("creator", a.creator), ("titulo", a.titulo)):
        if valor is not None:
            ag[chave] = valor
    if a.portao is not None:
        # 🔴 O PORTÃO DA ABA ESTILO TEM PRÉ-CONDIÇÃO (achado A12). Abrir a aba de
        # estilo sobre um corte NÃO aprovado é o creator escolhendo o look de uma
        # peça que ele não viu inteira — exatamente o que a própria UI existe para
        # evitar. Até 2026-08-10 a flag abria sozinha, e o `--force` estava
        # documentado no tutorial como se fosse o caminho normal.
        if a.portao == "estilo":
            ap_ok = aprovacao_valida_de(a.dir, "fase-1")
            if not ap_ok and not a.force:
                sys.stderr.write(
                    "estado.py: a aba ESTILO não abre sem aprovação VÁLIDA da "
                    "fase 1 em %s.\n"
                    "  O creator aprova no BOTÃO da UI (Fase 1 → APROVAR). Sem "
                    "browser: `qc-portao.py %s --aprovar --por <nome> --motivo "
                    "\"...\"` (fica marcada como %s).\n"
                    "  Para abrir mesmo assim: --force --motivo \"...\" — fica "
                    "gravado no estado, com quem e quando.\n"
                    % (a.dir, a.dir, FONTE_CLI))
                return 1
            if not ap_ok and a.force:
                if not a.motivo:
                    sys.stderr.write("estado.py: --force exige --motivo — uma "
                                     "exceção sem porquê não é auditável\n")
                    return 1
                ag["portao_forcado"] = {
                    "portao": "estilo", "por": a.por, "em": _agora(),
                    "motivo": a.motivo,
                    "aviso": "aba de estilo aberta SEM aprovação de fase 1"}
        ag["portao"] = None if a.portao == "nenhum" else a.portao
    if a.aprovar:
        registrar_aprovacao(a.dir, a.aprovar, a.por, fonte=a.fonte,
                            motivo=a.motivo, ag=ag)
    _gravar_agente(a.dir, ag)
    print(escrever(a.dir, gerar(a.dir, medir_timeline=a.medir_timeline)))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
