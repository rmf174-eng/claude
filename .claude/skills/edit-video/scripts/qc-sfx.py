#!/usr/bin/env python3
"""qc-sfx.py — NÍVEL e POSIÇÃO do transiente na biblioteca de SFX (SPEC-26).

    qc-sfx.py [--biblioteca <dir>] [--perfil reels|vsl|…] [--fps N]
              [--referenciado <nome> …] [--verificar] [--json]
              [--inventario <saida.json>]

    exit 0  nenhuma falha
         1  ao menos uma falha
         2  erro de uso
         3  NÃO VERIFICADO — não deu para medir (e isso NUNCA é aprovação)

Este arquivo é a RÉGUA do SFX. O `sfx-preparar.py` carrega este módulo para
consertar pela MESMA régua com que o QC audita: se o preparador aparasse por um
critério e o QC medisse por outro, o verde do QC provaria só que os dois
concordam entre si.

────────────────────────────────────────────────────────────────────────────
O BURACO QUE ISTO FECHA

Normalizamos SFX por LOUDNESS medida (o ref-A normaliza por PICO, e é assim que
se chega a um `click2.mp3` a −25 dB que a doc deles mesma admite ser inaudível).
Mas o agendamento é cego para o CONTEÚDO do arquivo. O `MotionKit.tsx:107` põe o
ARQUIVO no frame do beat:

    <Sequence from={Math.round(atS * fps)}><Audio src={…}/></Sequence>

Se o arquivo tem 180 ms de silêncio antes da batida, a batida chega 180 ms depois
do beat — e um efeito de 230 ms já terminou. Medido na nossa biblioteca real:
4 de 9 arquivos passam de um frame de atraso, e o pior (`whoosh-soft.wav`) gasta
41 % do próprio corpo em silêncio. Derivar por pitch/stretch multiplica o lead-in
junto: o `whoosh-soft` é o `whoosh` esticado, e o lead foi de 46 ms para 75 ms.

E as duas medições NÃO SÃO INDEPENDENTES: o integrado LUFS de um clipe curto
depende de quanto silêncio há DENTRO dele. Medido com `ebur128 -stream_loop 15`,
que é o método que a própria skill prescreve:

    pop.wav          −22,5 LUFS como está  ·  −17,5 sem a cauda muda  → Δ 5,0 LU
    whoosh.wav       −20,0 LUFS como está  ·  −18,5 sem o lead-in     → Δ 1,5 LU

Cinco LU. Por isso a ordem do `sfx-preparar.py` é APARAR → MEDIR → NORMALIZAR:
um `loudnorm` rodado antes do corte normaliza o padding junto.

POR QUE O LIMIAR É RELATIVO AO PICO, E NÃO ABSOLUTO
O `onset` é o primeiro ponto do envelope a −20 dB do pico do PRÓPRIO arquivo. Um
limiar absoluto lê ruído de sala como sinal num arquivo alto e não acha nada num
arquivo baixo — mesma lição do `piso_local` do `bordas.py:123-126`.

🔴 `LOUDNESS-FORA-DO-ALVO` é ACHADO, nunca falha: 5 dos 9 arquivos estão fora
hoje e parte disso é o padding que só o `sfx-preparar.py` remove. Promover a
falha bloquearia a bateria por um número que esta própria spec explica.

🔴 `TRANSIENTE-ATRASADO` (acento) é FALHA; `TRANSIENTE-ATRASADO-TEXTURA` é
achado. São duas TAGS porque quem classifica é o catálogo da bateria, que só
enxerga a string — uma tag só para os dois casos faria a textura reprovar a peça.

Mecanismo modelado de uma ferramenta de edição de terceiro,
references/shortform.md:329-341 — cópia de leitura em tools/referencias/.
Implementação nossa: envelope RMS com limiar relativo ao pico, separação
acento×textura por corpo medido, e a ordem aparar→medir→normalizar.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perfil as perfil_mod                                          # noqa: E402

CONTRATO = "benchmark.sfx-inventario/v1"
CONTRATO_SIDECAR = "benchmark.sfx/v1"

# ─── constantes ADIMENSIONAIS (nenhuma descreve o formato da peça) ────────────
JANELA_MS = 5.0            # envelope RMS: 5 ms enxerga o ataque de um pop
HOP_MS = 1.0               # 1 ms — a unidade em que o defeito vive
DB_ONSET = -20.0           # "o som começou", relativo ao pico do próprio envelope
DB_CORPO = -40.0           # "o som acabou", idem
LOOPS_EBUR = 15            # `-stream_loop 15` = 16 passagens (a validação que a
#                            SKILL.md:236 prescrevia e que ninguém executava)
FRACAO_LEAD_MAXIMA = 0.30  # lead acima disto COME o efeito (o caso do ref-A:
#                            180 ms de lead num efeito de 230 ms = 0,78)
SFX_PADRAO = {"tolerancia_frames": 1, "piso_ms": 20.0, "corpo_acento_max_ms": 400,
              "lufs_alvo": [-21.0, -19.0], "pico_min_dbfs": -18.0,
              "lufs_tolerancia_lu": 1.0}
EXT_AUDIO = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")


class ErroSfx(Exception):
    pass


# ══════════════════════════════════════════ funções PURAS (testáveis sem ffmpeg)

def envelope(x, sr, janela_ms=JANELA_MS, hop_ms=HOP_MS):
    """RMS por janela deslizante, em O(n) (soma cumulativa de quadrados).

    Devolve (envelope, hop_amostras). O laço ingênuo é O(n·janela) e num bruto de
    59 s custaria minutos — e bruto de 59 s é exatamente o que o creator-1 joga em
    `tools/sfx-library/`.

    📐 O ponto `i` cobre `[i·hop, i·hop + janela)`, então o índice do primeiro
    ponto acima do limiar é o COMEÇO da janela que primeiro toca o transiente:
    o `onset` sai até `janela − hop` ANTES do ataque real, nunca depois. O viés é
    de UM lado só, e é o lado seguro — quem apara um lead-in prefere deixar 4 ms
    de silêncio a decapitar o ataque. Não "corrija" isto para o centro da janela:
    a tabela de §2.2 e o limiar de `atraso_max_ms` foram calibrados nesta
    convenção, e mudá-la desloca os nove números de uma vez."""
    j = max(1, int(round(sr * janela_ms / 1000.0)))
    h = max(1, int(round(sr * hop_ms / 1000.0)))
    if not x:
        return [], h
    if len(x) < j:
        j = max(1, len(x))
    cum = [0.0] * (len(x) + 1)
    for i, v in enumerate(x):
        cum[i + 1] = cum[i] + v * v
    env = []
    for i in range(0, max(1, len(x) - j + 1), h):
        env.append(math.sqrt(max(0.0, cum[i + j] - cum[i]) / j))
    return env, h


def medir_envelope(x, sr):
    """onset_ms · pico_ms · fim_ms · corpo_ms — tudo relativo ao pico do envelope.

    `fim_ms` é o último ponto ≥ −40 dB: é onde a cauda ACÚSTICA termina, e é o que
    o aparo de cauda nunca pode cortar. O que sai depois dele é silêncio digital."""
    env, h = envelope(x, sr)
    if not env:
        raise ErroSfx("áudio vazio")
    pico = max(env)
    if pico <= 0:
        raise ErroSfx("áudio mudo (envelope todo zero)")
    ms = 1000.0 * h / float(sr)
    lim_on = pico * (10.0 ** (DB_ONSET / 20.0))
    lim_corpo = pico * (10.0 ** (DB_CORPO / 20.0))
    i_on = next((i for i, v in enumerate(env) if v >= lim_on), 0)
    i_fim = max(i for i, v in enumerate(env) if v >= lim_corpo)
    i_pico = max(range(len(env)), key=lambda i: env[i])
    return {"onset_ms": round(i_on * ms, 1), "pico_ms": round(i_pico * ms, 1),
            "fim_ms": round(i_fim * ms, 1),
            "corpo_ms": round((i_fim - i_on) * ms, 1),
            "pontos_envelope": len(env)}


def pico_dbfs(x):
    """Pico de amostra em dBFS. Silêncio digital devolve −inf, não 0."""
    if not x:
        return None
    m = max(abs(min(x)), abs(max(x)))
    return None if m <= 0 else round(20.0 * math.log10(m), 1)


def classe_de(corpo_ms, corpo_acento_max_ms):
    """`acento` × `textura`, pelo CORPO MEDIDO, não pelo julgamento de quem
    digitou o comando. Na biblioteca real o corte em 400 ms separa limpo:
    36–348 ms de um lado, 1.715–2.070 ms do outro, ninguém perto da linha."""
    return "acento" if corpo_ms <= corpo_acento_max_ms else "textura"


def atraso_max_ms(sfx, fps):
    """`max(1000 × tolerancia_frames / fps, piso_ms)`.

    O piso existe porque uma peça a 120 fps exigiria 8 ms de precisão que o
    agendador nem tem: o `from` do Remotion é inteiro em frames."""
    tol = float(sfx.get("tolerancia_frames", 1))
    piso = float(sfx.get("piso_ms", 20.0))
    return max(1000.0 * tol / float(fps), piso)


def avaliar(m, classe, sfx, fps):
    """(estado, tags) — a tabela de §3.4. `estado` é do eixo POSIÇÃO/NÍVEL.

    `LOUDNESS-FORA-DO-ALVO` entra em `tags` mas NÃO muda o `estado`: se mudasse,
    5 dos 9 arquivos limpos de posição virariam achado e o resumo deixaria de
    responder à pergunta que a sonda existe para responder."""
    tags = []
    estado = "ok"
    lim = atraso_max_ms(sfx, fps)
    onset = float(m["onset_ms"])
    corpo = float(m["corpo_ms"])
    if classe == "acento":
        if onset > lim:
            tags.append("TRANSIENTE-ATRASADO")
            estado = "falha"
        if corpo > 0 and onset > FRACAO_LEAD_MAXIMA * corpo:
            tags.append("LEAD-IN-COME-O-EFEITO")
            estado = "falha"
    else:
        if onset > lim:
            tags.append("TRANSIENTE-ATRASADO-TEXTURA")
            estado = "achado" if estado == "ok" else estado
    pk = m.get("pico_dbfs")
    if pk is None or pk < float(sfx.get("pico_min_dbfs", -18.0)):
        tags.append("INAUDIVEL")
        estado = "falha"
    return estado, tags


def loudness_fora(lufs, sfx):
    """`LOUDNESS-FORA-DO-ALVO` ou None. Achado, nunca falha — ver o docstring."""
    if lufs is None:
        return None
    alvo = sfx.get("lufs_alvo") or SFX_PADRAO["lufs_alvo"]
    tol = float(sfx.get("lufs_tolerancia_lu", SFX_PADRAO["lufs_tolerancia_lu"]))
    lo, hi = min(alvo), max(alvo)
    if lufs < lo - tol or lufs > hi + tol:
        return "LOUDNESS-FORA-DO-ALVO"
    return None


# ══════════════════════════════════════════════════════════ medição (com ffmpeg)

def decodificar(caminho, sr):
    """mono, `sr` Hz, float32. Sem numpy — não é dependência desta skill."""
    import struct
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", caminho, "-ac", "1",
         "-ar", str(int(sr)), "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise ErroSfx("ffmpeg não decodificou %s: %s"
                      % (caminho,
                         (r.stderr or b"").decode("utf-8", "replace")[-160:]))
    n = len(r.stdout) // 4
    return list(struct.unpack("<%df" % n, r.stdout[:n * 4]))


_RE_I = re.compile(r"^\s*I:\s*([-\d.]+)\s*LUFS", re.M)


def lufs_em_loop(caminho, loops=LOOPS_EBUR):
    """Integrado com `-stream_loop N`. Em clipe sub-segundo o gate do BS.1770
    engole o arquivo inteiro num passe só — daí o loop.

    ⚠️ `re.M` é obrigatório: o resumo do `ebur128` vem indentado e multilinha, e
    um `^` sem `re.M` num `findall` já leu 1 achado de 21 impressos neste repo."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-stream_loop", str(int(loops)),
         "-i", caminho, "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True)
    txt = r.stderr + "\n" + r.stdout
    if "Summary" not in txt:
        return None
    m = _RE_I.search(txt.split("Summary", 1)[1])
    return float(m.group(1)) if m else None


def medir_arquivo(caminho, sr, *, com_lufs=True):
    x = decodificar(caminho, sr)
    m = medir_envelope(x, sr)
    m["dur_s"] = round(len(x) / float(sr), 3)
    m["pico_dbfs"] = pico_dbfs(x)
    m["lufs"] = lufs_em_loop(caminho) if com_lufs else None
    return m


def sha256_arquivo(caminho):
    import hashlib
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


# ───────────────────────────────────────────────────────── resolução de caminhos

def dir_biblioteca_padrao():
    """$BENCH_SFX_DIR → <ilha>/tools/remotion-compositor/public/sfx.

    Ausência é silêncio: um cliente do produto não tem a nossa árvore e um aviso
    na máquina dele seria vazamento de arquitetura. Quem decide o que fazer com
    `None` é o chamador — aqui, NÃO VERIFICADO com a causa nomeada."""
    env = os.environ.get("BENCH_SFX_DIR")
    if env:
        return env if os.path.isdir(env) else None
    aqui = os.path.dirname(os.path.abspath(__file__))
    base = os.path.normpath(os.path.join(aqui, "..", "..", ".."))
    cand = os.path.join(base, "tools", "remotion-compositor", "public", "sfx")
    return cand if os.path.isdir(cand) else None


def arquivos_da_biblioteca(d):
    """Os áudios da biblioteca, em ordem estável. `_*` (histórico, inventário,
    sidecar interno) fica de fora."""
    if not d or not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if n.lower().endswith(EXT_AUDIO) and not n.startswith("_")]


def perfil_nomeado(nome):
    """A camada `perfis/<nome>.json` mesclada sobre `_base.json`.

    Nome desconhecido cai em `_base` e **diz que caiu** — silêncio aqui seria a
    peça sendo auditada com a régua de outro formato."""
    aviso = None
    dirp = perfil_mod.DIR_PERFIS
    limpo = re.sub(r"-fallback$", "", str(nome or "")).strip()
    arq = os.path.join(dirp, "%s.json" % limpo) if limpo else ""
    if limpo and os.path.isfile(arq):
        with open(arq, encoding="utf-8") as fh:
            camada = json.load(fh)
        return perfil_mod.sobre_base(camada), aviso
    base = os.path.join(dirp, "_base.json")
    if not os.path.isfile(base):
        raise ErroSfx("perfis/_base.json não encontrado em %s" % dirp)
    with open(base, encoding="utf-8") as fh:
        p = json.load(fh)
    if limpo:
        aviso = "perfil %r não existe em perfis/ — usando _base" % limpo
    return p, aviso


# ═════════════════════════════════════════════════════════════════════ o comando

def auditar(biblioteca, sfx, sr, fps, *, referenciados=(), verificar=False):
    arquivos = arquivos_da_biblioteca(biblioteca)
    itens = []
    for p in arquivos:
        nome = os.path.splitext(os.path.basename(p))[0]
        m = medir_arquivo(p, sr)
        classe = classe_de(m["corpo_ms"], sfx.get("corpo_acento_max_ms", 400))
        estado, tags = avaliar(m, classe, sfx, fps)
        t = loudness_fora(m.get("lufs"), sfx)
        if t:
            tags.append(t)
        side = os.path.join(biblioteca, nome + ".json")
        sidecar = None
        if os.path.isfile(side):
            with open(side, encoding="utf-8") as fh:
                sidecar = json.load(fh)
            if sidecar.get("sha256_wav") and \
                    sidecar["sha256_wav"] != sha256_arquivo(p):
                # 🔴 alguém trocou o áudio por baixo do nome. É a família do
                # segmento órfão: quem re-renderizar uma peça antiga recebe outro
                # som sem nenhum aviso.
                tags.append("SIDECAR-DIVERGENTE")
                estado = "falha"
            if verificar and sidecar.get("origem", {}).get("tipo") == "sintetizado" \
                    and sidecar.get("origem", {}).get("seed") is None:
                tags.append("SINTETIZADO-SEM-SEED")
                estado = "falha"
        itens.append({
            "nome": nome, "arquivo": os.path.basename(p), "dur_s": m["dur_s"],
            "onset_ms": m["onset_ms"], "pico_ms": m["pico_ms"],
            "corpo_ms": m["corpo_ms"], "fim_ms": m["fim_ms"],
            "atraso_frames": round(m["onset_ms"] * fps / 1000.0, 2),
            "classe": classe, "lufs": m.get("lufs"), "pico_dbfs": m.get("pico_dbfs"),
            "estado": estado, "tags": tags,
            "sidecar": sidecar.get("schema") if sidecar else None,
        })
    presentes = {i["nome"] for i in itens}
    ausentes = [n for n in referenciados if n not in presentes]
    for n in ausentes:
        itens.append({"nome": n, "arquivo": None, "estado": "falha",
                      "tags": ["SFX-AUSENTE"], "classe": None,
                      "onset_ms": None, "corpo_ms": None, "sidecar": None})
    return itens


def montar_doc(biblioteca, itens, sfx, perfil_nome, sr, fps, aviso=None):
    return {
        "schema": CONTRATO,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "biblioteca": biblioteca,
        "perfil": {"nome": perfil_nome, "fps": fps, "sr": sr,
                   "atraso_max_ms": round(atraso_max_ms(sfx, fps), 2),
                   "lufs_alvo": sfx.get("lufs_alvo"),
                   "corpo_acento_max_ms": sfx.get("corpo_acento_max_ms")},
        "aviso": aviso,
        "arquivos": itens,
        "resumo": {
            "medidos": sum(1 for i in itens if i.get("arquivo")),
            "ok": sum(1 for i in itens if i["estado"] == "ok"),
            "achados": sum(1 for i in itens if i["estado"] == "achado"),
            "falhas": sum(1 for i in itens if i["estado"] == "falha"),
            "loudness_fora": sum(1 for i in itens
                                 if "LOUDNESS-FORA-DO-ALVO" in i["tags"]),
            "sem_procedencia": sum(1 for i in itens
                                   if i.get("arquivo") and not i.get("sidecar")),
        },
    }


def imprimir(doc):
    r = doc["resumo"]
    print("qc-sfx · %s · perfil %s @ %g fps · atraso_max %.2f ms"
          % (doc["biblioteca"], doc["perfil"]["nome"], doc["perfil"]["fps"],
             doc["perfil"]["atraso_max_ms"]))
    print("arquivos_medidos: %d · %d ok · %d achado(s) · %d falha(s) · "
          "%d fora do alvo de loudness · %d sem procedência"
          % (r["medidos"], r["ok"], r["achados"], r["falhas"],
             r["loudness_fora"], r["sem_procedencia"]))
    for i in doc["arquivos"]:
        if not i["tags"]:
            continue
        if i.get("arquivo") is None:
            print("SFX-AUSENTE %s — referenciado e não está na biblioteca" % i["nome"])
            continue
        print("%s %s onset=%.1fms corpo=%.0fms (%s) lufs=%s pico=%sdBFS"
              % ("/".join(i["tags"]), i["nome"], i["onset_ms"], i["corpo_ms"],
                 i["classe"], i["lufs"], i["pico_dbfs"]))
    if doc.get("aviso"):
        print("aviso: %s" % doc["aviso"])
    return r["falhas"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--biblioteca", default=None)
    ap.add_argument("--perfil", default=None,
                    help="nome de perfis/<nome>.json (sem isto, _base)")
    ap.add_argument("--fps", type=float, default=None,
                    help="sobrepõe video.fps do perfil")
    ap.add_argument("--referenciado", action="append", default=[],
                    help="nome de SFX que alguma composição usa; ausente da "
                         "biblioteca vira SFX-AUSENTE (repetível)")
    ap.add_argument("--verificar", action="store_true",
                    help="também reprova sidecar de sintetizado sem seed")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--inventario", default=None,
                    help="onde gravar (default <biblioteca>/_inventario.json)")
    args = ap.parse_args(argv)

    biblioteca = args.biblioteca or dir_biblioteca_padrao()
    if not biblioteca or not os.path.isdir(biblioteca):
        print("qc-sfx")
        print("arquivos_medidos: 0")
        print("SEM-BIBLIOTECA: %s"
              % (biblioteca or "nenhuma biblioteca de SFX encontrada "
                               "($BENCH_SFX_DIR resolve isto)"))
        print("NÃO VERIFICADO — isto não é aprovação")
        return 3
    try:
        p, aviso = perfil_nomeado(args.perfil)
    except ErroSfx as e:
        print("qc-sfx\narquivos_medidos: 0\nSEM-PERFIL: %s\n"
              "NÃO VERIFICADO — isto não é aprovação" % e)
        return 3
    sfx = {**SFX_PADRAO, **(p.get("sfx") or {})}
    sr = int(p["audio"]["sr"])
    fps = float(args.fps or p["video"]["fps"])

    try:
        itens = auditar(biblioteca, sfx, sr, fps,
                        referenciados=args.referenciado, verificar=args.verificar)
    except ErroSfx as e:
        print("qc-sfx · %s\narquivos_medidos: 0\nSEM-MEDICAO: %s\n"
              "NÃO VERIFICADO — isto não é aprovação" % (biblioteca, e))
        return 3
    if not itens:
        print("qc-sfx · %s\narquivos_medidos: 0\n"
              "SEM-ARQUIVOS: a biblioteca está vazia\n"
              "NÃO VERIFICADO — isto não é aprovação" % biblioteca)
        return 3

    doc = montar_doc(biblioteca, itens, sfx,
                     (args.perfil or "_base"), sr, fps, aviso)
    saida = args.inventario or os.path.join(biblioteca, "_inventario.json")
    try:
        with open(saida, "w") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    except OSError as e:
        print("aviso: não gravei o inventário (%s)" % e, file=sys.stderr)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        imprimir(doc)
        print("inventário: %s" % saida, file=sys.stderr)
    return 1 if doc["resumo"]["falhas"] else 0


if __name__ == "__main__":
    sys.exit(main())
