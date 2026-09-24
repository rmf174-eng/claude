#!/usr/bin/env python3
"""edl.json: o envelope `benchmark.edl/v2` e a TIMELINE REAL da saída.

Uso como módulo (é o normal — nenhum outro script abre `edl.json` na mão):

    import edl_io
    segs = edl_io.segmentos(dir)                 # a lista de segmentos, v1 ou v2
    tl   = edl_io.timeline(dir, exigir=False) or edl_io.medir_timeline(dir)
    fr   = edl_io.fronteiras(tl)                 # [start_s de cada seg] + [total_s]

Uso como CLI (auditoria, sem render):

    edl_io.py --ver    <dir>    # schema, nº de segmentos, timeline fresca/ausente/velha
    edl_io.py --medir  <dir>    # imprime o bloco timeline_real em stdout, NÃO grava
    edl_io.py --migrar <dir>    # v1 → v2 no arquivo (backup edl.v1.bak.json)

────────────────────────────────────────────────────────────────────────────
POR QUE ISTO EXISTE — dois defeitos, os dois invisíveis para todos os QCs.

(a) O SCHEMA ERA FECHADO. O `bordas.py` montava o item da EDL com uma lista
    BRANCA de campos, e qualquer campo novo do `janelas.json` sumia em silêncio:
    sem aviso, sem erro, sem log. Custou 23 `quem` redeclarados à mão em
    `planos.json` na produção peca-01, e deixou `fadeIn`/`fadeOut`
    inalcançáveis apesar de o `audio-exato.py` LER os dois. A lista virou NEGRA
    (SPEC-00) e o envelope v2 fecha o resto: chave de topo desconhecida
    sobrevive à ida e volta.

(b) A TIMELINE REAL DA SAÍDA NÃO EXISTIA COMO DADO. A duração de cada segmento
    no montado é `frames_do_seg / fps` — ela nascia dentro do `audio-exato.py`,
    travava o áudio e morria ali. Quem precisava dela ou refazia a conta com
    ffprobe (6 reimplementações no repo, já divergentes) ou somava
    `Σ(end−start)` da EDL, que é MENOR: o render arredonda para frame e o erro
    acumula sempre no mesmo sentido.

    Medido neste repo em 2026-08-08, com os `segs/` que estão no disco:

        produção            segs   Σ(end−start)   Σ frames/fps   erro no fim
        creator-2/peca-03        20      65,880 s       66,233 s       353,3 ms
        creator-2/peca-01  29      70,450 s       70,767 s       316,7 ms
        creator-2/peca-04        17      62,835 s       63,133 s       298,3 ms

    É o mesmo anti-pattern que o ref-A comete em `helpers/render.py:809` e que o
    próprio SKILL.md deles proíbe na linha 513 — eles gravam o dado certo e leem
    o errado. Aqui o dado passa a existir E os consumidores passam a lê-lo.

────────────────────────────────────────────────────────────────────────────
O CONTRATO, em três frases (a versão longa está em references/contrato-edl.md):

  1. FRAMES E AMOSTRAS SÃO INTEIROS E SÃO A VERDADE. Os segundos são derivados
     (`start_frame / fps`) e existem só para leitura humana. Nunca some segundos
     para achar posição.
  2. A ORIGEM É O SEGMENTO RENDERIZADO, nunca a EDL. `frames` vem de
     `nb_read_frames` (ou do que o `audio-exato.py` mediu para cortar o áudio);
     `width/height/fps` vêm do ffprobe do próprio seg. Nada aqui é prescrito.
  3. SE A EDL MUDAR, A TIMELINE MORRE. `bordas.py` remove o bloco ao reescrever,
     e `timeline()` aborta quando o `edl_fingerprint` não bate. As duas defesas,
     porque `planos.py:194` reescreve `edl.json` sem passar pelo `bordas.py`.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perfil as perfil_mod   # noqa: E402

SCHEMA = "benchmark.edl/v2"
SCHEMA_TL = "benchmark.timeline-real/v1"
SIDECAR = "timeline-real.json"
CASAS = 6          # segundos são DERIVADOS: 6 casas é leitura humana, não verdade


# ─────────────────────────────────────────────────────────── envelope (leitura)

def caminho(d):
    """`d` pode ser o diretório da produção OU o próprio arquivo de EDL.

    `cortes-do-bruto.py` e `qc-fonemas.py` têm `--edl <arquivo>`; aceitar os dois
    é o que permite trocar `json.load` por `edl_io.segmentos` sem mudar CLI."""
    return os.path.join(d, "edl.json") if os.path.isdir(d) else str(d)


def _ler_bruto(d):
    p = caminho(d)
    if not os.path.exists(p):
        sys.exit("edl.json não encontrado em %s" % os.path.abspath(p))
    with open(p) as fh:
        return json.load(fh), p


def e_v1(d):
    """O arquivo NO DISCO é array nu (v1)? (a decisão de gravar sidecar sai daqui)"""
    bruto, _ = _ler_bruto(d)
    return isinstance(bruto, list)


def carregar(d):
    """edl.json → envelope v2 EM MEMÓRIA. Aceita array v1 (envelopa, NÃO grava).

    Envelopar em memória é o que faz "ler v1 sempre" custar zero para o chamador:
    nenhum consumidor precisa saber em que versão o arquivo está."""
    bruto, p = _ler_bruto(d)
    if isinstance(bruto, list):
        return {"schema": SCHEMA, "perfil": None, "segments": bruto}
    if not isinstance(bruto, dict):
        sys.exit("%s: EDL tem que ser array (v1) ou objeto (v2), veio %s"
                 % (p, type(bruto).__name__))
    env = dict(bruto)
    env.setdefault("schema", SCHEMA)
    _exige_segments(env.get("segments"), p)
    return env


def segmentos(d):
    """Atalho: a lista de segmentos, seja v1 ou v2."""
    return carregar(d)["segments"]


def topo(d):
    """As chaves de TOPO do envelope que descrevem a PEÇA, não o corte.

    Serve a quem vai REESCREVER os segmentos (o `bordas.py`) e precisa preservar
    `perfil` e o que mais estiver ali. `segments` e `timeline_real` ficam de fora
    por definição: os dois descrevem o corte que está sendo substituído.

    Tolerante de propósito — arquivo ausente, ilegível ou corrompido devolve `{}`.
    Se o `bordas.py` travasse numa `edl.json` quebrada, não haveria como consertá-la
    a não ser apagando na mão. Esta é a única leitura de EDL que não valida nada, e
    ela mora AQUI para que nenhum outro script precise abrir o arquivo."""
    p = caminho(d)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as fh:
            bruto = json.load(fh)
    except (ValueError, OSError):
        return {}
    if not isinstance(bruto, dict):
        return {}          # v1 é array nu: não há chave de topo a preservar
    return {k: v for k, v in bruto.items() if k not in ("segments", "timeline_real")}


def _exige_segments(segs, onde):
    # ⚠️ `jq '(.segments // .)'` devolve o OBJETO INTEIRO quando `segments` é null
    # (null é falsy em jq), e `.[]` então itera os VALORES do objeto em silêncio —
    # o montar.sh montaria lixo sem uma linha de erro. Por isso null/vazio/não-lista
    # é fatal aqui, na escrita E na leitura.
    if not isinstance(segs, list):
        sys.exit("%s: `segments` tem que ser lista, veio %s. Um `\"segments\": null` "
                 "faz o `jq '(.segments // .)[]'` do montar.sh iterar o objeto e montar "
                 "lixo em silêncio." % (onde, type(segs).__name__))
    if not segs:
        sys.exit("%s: `segments` está vazio — não há o que montar." % onde)


# ─────────────────────────────────────────────────────────── envelope (escrita)

def gravar(d, env, *, invalida_timeline=False):
    """Grava o envelope v2. `invalida_timeline=True` remove `timeline_real`.

    🔴 Quem muda o CORTE grava com `invalida_timeline=True`. Um bloco de timeline
    que sobrevive ao corte que ele descrevia é o defeito que o ref-A documenta em
    render.py:1199-1203 ("the stale block outlives the render it described")."""
    p = caminho(d)
    saida = dict(env)
    saida["schema"] = SCHEMA
    _exige_segments(saida.get("segments"), p)
    if invalida_timeline:
        saida.pop("timeline_real", None)
    # ordem estável: as três chaves conhecidas primeiro, o resto (passthrough de
    # topo) depois, em ordem alfabética — diff de git legível entre gerações.
    ordem = ["schema", "perfil", "segments", "timeline_real"]
    fim = {k: saida[k] for k in sorted(saida) if k not in ordem}
    doc = {k: saida[k] for k in ordem if k in saida}
    doc.update(fim)
    with open(p, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return os.path.abspath(p)


def fingerprint(segments):
    """sha1 do JSON canônico dos segmentos — a identidade DO CORTE.

    Canônico = `sort_keys` + separadores fixos: reindentar o arquivo não muda o
    fingerprint, mudar um `end` em 1 ms muda."""
    canon = json.dumps(segments, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    return "sha1:" + hashlib.sha1(canon.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────── timeline real

def _probe(p, campos, contar_frames=False):
    cmd = ["ffprobe", "-v", "error"]
    if contar_frames:
        cmd += ["-count_frames"]
    cmd += ["-select_streams", "v", "-show_entries", "stream=" + campos,
            "-of", "csv=p=0", p]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return out.splitlines()[0].strip().rstrip(",") if out.strip() else ""


def segs_ordenados(d):
    """`segs/segNNN.mp4` em ordem NUMÉRICA.

    ⚠️ `sorted(glob.glob(...))` é lexicográfico e põe `seg100` entre `seg10` e
    `seg11` — acima de 99 segmentos o consumidor mede o vídeo embaralhado (era o
    caso de `qc-ataque.py:46`). E os nomes não são uniformes no repo: o
    `montar.sh` usa `%03d` hoje, as produções antigas usam `%02d`; a regex aceita
    os dois."""
    base = d if os.path.isdir(d) else os.path.dirname(os.path.abspath(d))
    dir_segs = os.path.join(base, "segs")
    if not os.path.isdir(dir_segs):
        return []
    achados = []
    for nome in os.listdir(dir_segs):
        m = re.match(r"^seg(\d+)\.mp4$", nome)
        if m:
            achados.append((int(m.group(1)), os.path.join(dir_segs, nome)))
    return [p for _, p in sorted(achados)]


def medir_timeline(d, *, sr=None, frames=None, amostras=None,
                   gerado_por="edl_io.py"):
    """Os `segs/` renderizados → o bloco `timeline_real` da §3.3. NÃO grava.

    `frames`   — nº de frames por segmento, quando o chamador já mediu (o
                 `audio-exato.py` mede: são os MESMOS frames que travaram o
                 áudio, então a timeline descreve literalmente o que foi cortado).
                 Sem isso, mede aqui com `-count_frames` (decodifica; é lento).
    `amostras` — nº de amostras POR CANAL efetivamente escritas em cada segmento.
                 Sem isso, a conta é `frames × spf`, e só quando `sr % fps == 0`.
    """
    env = carregar(d)
    segments = env["segments"]
    segs = segs_ordenados(d)
    if not segs:
        sys.exit("%s: não há segs/segNNN.mp4 — renderize a montagem primeiro "
                 "(montar.sh)." % os.path.abspath(caminho(d)))
    if len(segs) != len(segments):
        # 🔴 RECUSA, não medição. Segmento a mais no disco que na EDL é o bug do
        # ÓRFÃO — o que deixou o `c-completo` do creator-3 6,25 s mais longo com todos
        # os QCs verdes. Medir aqui produziria uma timeline coerente com o vídeo
        # ERRADO, que é a pior saída possível.
        sys.exit("%d segmento(s) em segs/ contra %d na EDL (%s).\n"
                 "Isto é ÓRFÃO: ou a EDL encolheu e sobraram .mp4 de uma geração "
                 "anterior, ou o render parou no meio. Apague segs/ e remonte — "
                 "medir agora gravaria uma timeline coerente com o vídeo errado."
                 % (len(segs), len(segments), os.path.abspath(caminho(d))))
    if frames is not None and len(frames) != len(segs):
        sys.exit("frames medidos (%d) != segmentos (%d)" % (len(frames), len(segs)))
    if amostras is not None and len(amostras) != len(segs):
        sys.exit("amostras medidas (%d) != segmentos (%d)" % (len(amostras), len(segs)))

    if sr is None:
        sr = int(perfil_mod.carregar(d, quieto=True)["audio"]["sr"])
    sr = int(sr)

    fps_num = fps_den = w = h = None
    linhas, tot_f, tot_a = [], 0, 0
    for i, p in enumerate(segs):
        wh = _probe(p, "width,height")
        fr = _probe(p, "r_frame_rate")
        try:
            pw, ph = [int(x) for x in wh.split(",")[:2]]
            num, den = (fr.split("/") + ["1"])[:2]
            num, den = int(num), int(den)
        except (ValueError, IndexError):
            sys.exit("ffprobe não devolveu formato utilizável para %s "
                     "(width,height=%r r_frame_rate=%r)" % (p, wh, fr))
        if fps_num is None:
            fps_num, fps_den, w, h = num, den, pw, ph
        else:
            # formato heterogêneo não sobrevive ao `concat -c copy`: recusar aqui
            # é mais barato que descobrir no player.
            if (num, den) != (fps_num, fps_den):
                sys.exit("fps inconsistente entre segmentos: %s tem %d/%d, o primeiro "
                         "tem %d/%d" % (p, num, den, fps_num, fps_den))
            if (pw, ph) != (w, h):
                sys.exit("dimensão inconsistente entre segmentos: %s é %dx%d, o "
                         "primeiro é %dx%d" % (p, pw, ph, w, h))
        nf = int(frames[i]) if frames is not None else int(
            _probe(p, "nb_read_frames", contar_frames=True) or 0)
        if nf <= 0:
            sys.exit("segmento sem frames: %s" % p)
        linhas.append(nf)
        tot_f += nf

    fps = fps_num / fps_den
    # 📐 `samples_por_frame` só existe quando a divisão é EXATA. Arredondar para
    # "suportar 29,97" é a deriva progressiva de A/V de 2026-07-25 voltando pela
    # porta nova — nesse caso o campo simplesmente não é gravado e a verdade das
    # amostras é o que o audio-exato.py escreveu.
    spf = sr // int(round(fps)) if abs(fps - round(fps)) < 1e-9 and \
        sr % int(round(fps)) == 0 else None

    out_segs = []
    acc_f = 0
    for i, nf in enumerate(linhas):
        s = segments[i]
        item = {
            "i": i,
            "beat": s.get("beat"),
            "src": s.get("src"),
            "src_start": s.get("start"),
            "src_end": s.get("end"),
            "frames": nf,
            "start_frame": acc_f,
            "start_s": round(acc_f / fps, CASAS),
            "dur_s": round(nf / fps, CASAS),
        }
        if amostras is not None:
            item["start_sample"] = tot_a
            item["samples"] = int(amostras[i])
            tot_a += int(amostras[i])
        elif spf is not None:
            item["start_sample"] = acc_f * spf
            item["samples"] = nf * spf
            tot_a += nf * spf
        out_segs.append(item)
        acc_f += nf

    tl = {
        "schema": SCHEMA_TL,
        "gerado_por": gerado_por,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "edl_fingerprint": fingerprint(segments),
        "video": {"width": w, "height": h, "fps": fps,
                  "fps_num": fps_num, "fps_den": fps_den},
        "sample_rate": sr,
        "total_frames": tot_f,
        "total_s": round(tot_f / fps, CASAS),
        "segments": out_segs,
    }
    if spf is not None:
        tl["samples_por_frame"] = spf
    if out_segs and "samples" in out_segs[0]:
        tl["total_samples"] = tot_a
    conferir_invariantes(tl)
    return tl


def conferir_invariantes(tl, onde="timeline_real"):
    """As invariantes da §3.3 — asseguradas na escrita, conferidas na leitura.

    Existe separado de `medir_timeline` de propósito: o bloco pode chegar de um
    arquivo escrito por outra versão do código, e um consumidor que confia sem
    conferir é como o QC que mede o codec em vez do sinal."""
    erros = []
    fps = tl["video"]["fps"]
    segs = tl["segments"]
    acc_f, acc_a = 0, 0
    spf = tl.get("samples_por_frame")
    for s in segs:
        if s["start_frame"] != acc_f:
            erros.append("seg%d: start_frame=%d, Σ frames anteriores=%d"
                         % (s["i"], s["start_frame"], acc_f))
        if abs(s["start_s"] - s["start_frame"] / fps) > 1e-6:
            erros.append("seg%d: start_s=%r != start_frame/fps=%r"
                         % (s["i"], s["start_s"], s["start_frame"] / fps))
        if abs(s["dur_s"] - s["frames"] / fps) > 1e-6:
            erros.append("seg%d: dur_s=%r != frames/fps=%r"
                         % (s["i"], s["dur_s"], s["frames"] / fps))
        if "samples" in s:
            if s["start_sample"] != acc_a:
                erros.append("seg%d: start_sample=%d, Σ amostras anteriores=%d"
                             % (s["i"], s["start_sample"], acc_a))
            if spf is not None and s["samples"] != s["frames"] * spf:
                erros.append("seg%d: samples=%d != frames*spf=%d"
                             % (s["i"], s["samples"], s["frames"] * spf))
            acc_a += s["samples"]
        acc_f += s["frames"]
    if tl["total_frames"] != acc_f:
        erros.append("total_frames=%d != Σ frames=%d" % (tl["total_frames"], acc_f))
    if abs(tl["total_s"] - tl["total_frames"] / fps) > 1e-6:
        erros.append("total_s=%r != total_frames/fps=%r"
                     % (tl["total_s"], tl["total_frames"] / fps))
    if "total_samples" in tl and tl["total_samples"] != acc_a:
        erros.append("total_samples=%d != Σ amostras=%d" % (tl["total_samples"], acc_a))
    if erros:
        sys.exit("%s INCONSISTENTE (%d invariante(s) violada(s)):\n  %s"
                 % (onde, len(erros), "\n  ".join(erros)))
    return tl


def caminho_sidecar(d):
    base = d if os.path.isdir(d) else os.path.dirname(os.path.abspath(d))
    return os.path.join(base, SIDECAR)


def gravar_timeline(d, tl):
    """Inline quando a EDL é v2; sidecar `timeline-real.json` quando é v1.

    O sidecar existe para NÃO promover a v2, em silêncio, uma produção histórica
    cujos scripts locais (`planos.py`, `legendas.py`, `cenas.py`) iteram o array."""
    conferir_invariantes(tl)
    if e_v1(d):
        p = caminho_sidecar(d)
        with open(p, "w") as fh:
            json.dump(tl, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print("  EDL v1 (array): timeline gravada no sidecar %s — "
              "`edl_io.py --migrar %s` consolida no edl.json"
              % (os.path.basename(p), d), file=sys.stderr)
        return os.path.abspath(p)
    env = carregar(d)
    env["timeline_real"] = tl
    return gravar(d, env)


def timeline(d, *, exigir=True):
    """Lê a timeline (inline ou sidecar) e CONFERE que ela descreve este corte.

    `exigir=False` devolve None quando ela não existe — é o caso legítimo da
    produção que nunca rodou o `audio-exato.py` desta versão. O que `exigir=False`
    NÃO afrouxa é a divergência de fingerprint: timeline velha é sempre fatal,
    porque ela descreve um corte que não é mais o do arquivo."""
    env = carregar(d)
    tl = env.get("timeline_real")
    origem = "edl.json"
    if tl is None:
        p = caminho_sidecar(d)
        if os.path.exists(p):
            with open(p) as fh:
                tl = json.load(fh)
            origem = os.path.basename(p)
    if tl is None:
        if exigir:
            sys.exit("timeline_real ausente em %s. Rode `montar.sh <dir>` (o "
                     "audio-exato.py grava a timeline) ou `edl_io.py --medir <dir>` "
                     "para inspecionar sem gravar." % os.path.abspath(caminho(d)))
        return None
    atual = fingerprint(env["segments"])
    if tl.get("edl_fingerprint") != atual:
        sys.exit("A EDL MUDOU DEPOIS DO RENDER — rode `montar.sh <dir>`.\n"
                 "  edl_fingerprint gravado em %s: %s\n"
                 "  edl_fingerprint dos segmentos de agora: %s\n"
                 "Usar esta timeline poria legenda, capítulo e QC em posições de "
                 "um corte que não existe mais." % (origem, tl.get("edl_fingerprint"), atual))
    conferir_invariantes(tl, onde=origem)
    return tl


# ───────────────────────────────────────────────────── consumo (posição na saída)

def fronteiras(tl):
    """[start_s de cada segmento] + [total_s] — n+1 valores.

    A emenda entre o segmento `i` e o `i+1` é `fronteiras[i+1]`; `fronteiras[0]`
    é 0,0 e `fronteiras[n]` é o fim da peça. NUNCA calcule isto somando
    `end−start` da EDL: a soma nominal é sempre MENOR (353 ms no fim de
    `peca-03`) e o consumidor lê a palavra errada dos dois lados do corte."""
    return [s["start_s"] for s in tl["segments"]] + [tl["total_s"]]


def t_saida(tl, i, t_no_bruto):
    """Tempo NA SAÍDA de um instante `t_no_bruto` que cai dentro do segmento `i`.

    É a fórmula que as três `legendas.py` de produção implementam à mão."""
    s = tl["segments"][i]
    if s.get("src_start") is None:
        raise ValueError("segmento %d não tem `start` na EDL (EDL por frames?): "
                         "não dá para mapear tempo do bruto" % i)
    return s["start_s"] + (t_no_bruto - s["src_start"])


# ────────────────────────────────────────────────────────────────────────── CLI

def _migrar(d):
    p = caminho(d)
    if not e_v1(d):
        print("%s já é %s — nada a migrar" % (p, SCHEMA), file=sys.stderr)
        return 0
    bruto, _ = _ler_bruto(d)
    bak = os.path.join(os.path.dirname(os.path.abspath(p)), "edl.v1.bak.json")
    with open(bak, "w") as fh:
        json.dump(bruto, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    env = {"schema": SCHEMA, "perfil": None, "segments": bruto}
    side = caminho_sidecar(d)
    if os.path.exists(side):
        with open(side) as fh:
            tl = json.load(fh)
        if tl.get("edl_fingerprint") == fingerprint(bruto):
            env["timeline_real"] = tl
            print("  sidecar %s consolidado no envelope" % SIDECAR, file=sys.stderr)
        else:
            print("  sidecar %s IGNORADO: descreve outro corte" % SIDECAR, file=sys.stderr)
    gravar(d, env)
    print("backup em %s" % bak, file=sys.stderr)
    print(os.path.abspath(p))
    return 0


def _ver(d):
    bruto, p = _ler_bruto(d)
    v1 = isinstance(bruto, list)
    env = carregar(d)
    n = len(env["segments"])
    tl = env.get("timeline_real")
    onde = "inline"
    if tl is None and os.path.exists(caminho_sidecar(d)):
        with open(caminho_sidecar(d)) as fh:
            tl = json.load(fh)
        onde = "sidecar"
    if tl is None:
        est = "ausente"
    elif tl.get("edl_fingerprint") == fingerprint(env["segments"]):
        est = "fresca (%s, %d frames, %.3fs)" % (onde, tl["total_frames"], tl["total_s"])
    else:
        est = "VELHA (%s) — a EDL mudou depois do render" % onde
    print("%s · %d segmentos · timeline_real: %s"
          % ("benchmark.edl/v1 (array)" if v1 else env.get("schema", "?"), n, est))
    return 0


def _cli(argv):
    modos = {"--medir", "--migrar", "--ver"}
    achados = [a for a in argv if a in modos]
    if len(achados) != 1:
        sys.exit(__doc__.split("────")[0].strip())
    modo = achados[0]
    resto = [a for a in argv if a not in modos]
    d = resto[0] if resto else "."
    if modo == "--medir":
        json.dump(medir_timeline(d), sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    if modo == "--migrar":
        return _migrar(d)
    return _ver(d)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
