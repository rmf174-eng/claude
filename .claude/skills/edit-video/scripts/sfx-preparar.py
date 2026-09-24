#!/usr/bin/env python3
"""sfx-preparar.py — aquisição canônica de SFX, com a ORDEM declarada (SPEC-26).

    sfx-preparar.py <bruto> --nome <slug> [--classe acento|textura|auto]
                    [--saida <dir>] [--perfil <n>] [--licenca X --fonte Y]
    sfx-preparar.py --migrar [--so nome,nome] [--confirmar] [--saida <dir>]
    sfx-preparar.py --selar   [--confirmar] [--saida <dir>]

    exit 0  fez (ou, sem --confirmar, mostrou o que faria)
         1  recusou por guarda de segurança (o aparo comeria o som)
         2  erro de uso

O fluxo do creator-1 — ele joga o mp3 em `tools/sfx-library/<nome>.mp3` e a ilha
processa — era PROSA na `remotion-compositor/SKILL.md:230`. Aqui vira passo, com
a ordem das operações que a medição obriga.

────────────────────────────────────────────────────────────────────────────
🔴 A ORDEM NÃO É ARBITRÁRIA: APARAR → MEDIR → NORMALIZAR

  1. aparar o LEAD-IN até o transiente ficar em t = 0 (com guarda antes do onset,
     para não decapitar o ataque);
  2. aparar a CAUDA no fim acústico + release (nunca a cauda em si: o que sai é o
     silêncio digital depois dela);
  3. declick/fade pela CLASSE MEDIDA — `acento` não leva fade-in (só declick na
     saída), `textura` leva `afade in 30ms + afade out`;
  4. MEDIR o integrado em loop ×16;
  5. NORMALIZAR pelo ganho do passo 4 e RE-MEDIR para conferir.

Medir antes de aparar é o erro, e ele tem número: `pop.wav` mede −22,5 LUFS como
está e −17,5 LUFS sem a cauda muda. **5,0 LU vindos de silêncio dentro do
arquivo.** Um `loudnorm` rodado antes do corte normaliza o padding junto e
entrega um efeito 5 dB mais alto do que o alvo pedia — a mesma classe de erro do
`volume=0.10` cego que a SPEC-20 documenta na trilha do ref-A.

🔴 A MIGRAÇÃO NUNCA É SILENCIOSA. Trocar o conteúdo de um `.wav` mantendo o nome
é a família exata do segmento órfão: quem re-renderizar uma produção antiga
recebe um resultado diferente sem nenhum aviso. Por isso `--migrar` sem
`--confirmar` só IMPRIME o diff, o `.wav` anterior vai para `_historico/` e nunca
é apagado, e o sidecar guarda o `sha256` dos dois lados. O ref-A apaga.

🔴 GUARDA DE SEGURANÇA. Se o aparo mudar o `corpo_ms` em mais que o teto, o
arquivo NÃO é escrito. O achado registrado já vale mais que um arquivo estragado.

Mecanismo modelado de uma ferramenta de edição de terceiro,
references/shortform.md:334-337 (aparar o lead-in para t=0 e só então atrasar
para o beat) — cópia de leitura em tools/referencias/. Implementação nossa: a ordem
aparar→medir→normalizar com os 5,0 LU que a justificam, a classe medida em vez de
declarada, e o sidecar com procedência (eles usam RNG global sem seed e apagam o
artefato anterior).
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "qc_sfx", os.path.join(AQUI, "qc-sfx.py"))
qs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qs)

# ─── constantes ADIMENSIONAIS (nenhuma descreve o formato da peça) ────────────
GUARDA_ATAQUE_MS = 3.0     # sobra antes do onset: decapitar o ataque é pior que
#                            deixar 3 ms de silêncio
RELEASE_MS = 250.0         # sobra depois do fim acústico
DECLICK_MS = 5.0           # `acento`: só declick na saída, nunca fade-in (SFX
#                            percussivo com fade-in perde o ataque)
FADE_IN_TEXTURA_MS = 30.0
FADE_OUT_TEXTURA_MS = 250.0
TETO_PICO_DBFS = -1.0      # headroom: normalizar até clipar seria trocar um
#                            defeito medido por outro
TETO_DELTA_CORPO_MS = 5.0  # guarda: acima disto o aparo comeu som, não silêncio
TETO_ONSET_DEPOIS_MS = 3.0


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("%s\n%s" % (" ".join(cmd[:6]) + " …",
                                       (r.stderr or "")[-400:]))
    return r


def formato_de(caminho):
    """(sample_rate, canais) do próprio arquivo — nunca prescritos.

    Preservar o formato da fonte é o que impede que o preparo vire um
    reamostramento escondido. A biblioteca real é mono a 44,1 kHz; o perfil da
    PEÇA é outra coisa e não manda aqui."""
    r = sh(["ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "default=nw=1:nk=1", caminho])
    v = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if len(v) < 2:
        raise RuntimeError("ffprobe não leu stream de áudio em %s" % caminho)
    return int(v[0]), int(v[1])


def cadeia_de_filtros(inicio_s, fim_s, classe, fim_acustico_s):
    """`atrim` + declick/fade que NÃO ATRAVESSAM O CORPO. Devolve (chain, d_in_ms).

    🔴 Duas emendas medidas à receita genérica da `SKILL.md:236`
    (`afade in 30ms + afade out 200-300ms`), e as duas têm número:

    (1) O FADE-IN DE 30 ms É PARTE DO PROBLEMA, não do conserto. É ele que
        explica `shutter` a 7 ms e `scratch` a 17 ms de onset. Reaplicá-lo depois
        de aparar o lead-in para t=0 desfaria exatamente o que esta spec faz. O
        que fica é um DECLICK, limitado à guarda que existe antes do onset — nunca
        atravessa o ataque.

    (2) O FADE-OUT COMEÇA NO FIM ACÚSTICO, e dura só o silêncio disponível depois
        dele. Um `afade out 250ms` cego atenua som de verdade: medido, ele muda o
        corpo do `pencil` em 212 ms e o do `typing` em 56 ms — os dois seriam
        recusados pela guarda de §7.9, e com razão, porque estariam sendo comidos.

    Sem `apad`: `pad_dur=0` pada PARA SEMPRE neste build (0 = "não definido"), e
    um SFX infinito é pior que um atrasado."""
    dur_saida = fim_s - inicio_s
    fim_rel = max(0.0, fim_acustico_s - inicio_s)
    guarda = max(0.0, min(DECLICK_MS / 1000.0, fim_rel))
    disponivel = max(0.0, dur_saida - fim_rel)
    teto_out = (DECLICK_MS if classe == "acento" else FADE_OUT_TEXTURA_MS) / 1000.0
    d_out = max(DECLICK_MS / 1000.0, min(teto_out, disponivel))
    st_out = max(0.0, dur_saida - d_out)
    f = ["atrim=start=%.6f:end=%.6f" % (inicio_s, fim_s), "asetpts=N/SR/TB"]
    if guarda > 0:
        f.append("afade=t=in:st=0:d=%.6f" % guarda)
    f.append("afade=t=out:st=%.6f:d=%.6f" % (st_out, d_out))
    return ",".join(f), round(guarda * 1000.0, 1)


def preparar(bruto, destino, *, classe, sfx, sr_medicao, tmpdir):
    """A ordem de §3.6, com os números dos dois lados. NÃO grava em `destino`
    quando a guarda dispara — devolve o dict com `recusado`."""
    antes = qs.medir_arquivo(bruto, sr_medicao)
    if classe == "auto":
        classe = qs.classe_de(antes["corpo_ms"], sfx.get("corpo_acento_max_ms", 400))

    ini = max(0.0, (antes["onset_ms"] - GUARDA_ATAQUE_MS) / 1000.0)
    fim = min(antes["dur_s"], (antes["fim_ms"] + RELEASE_MS) / 1000.0)
    if fim <= ini:
        return {"recusado": "o aparo não deixaria amostra nenhuma",
                "antes": antes, "classe": classe}
    dur_saida = fim - ini

    sr_arq, canais = formato_de(bruto)
    cadeia, declick_ms = cadeia_de_filtros(ini, fim, classe,
                                           antes["fim_ms"] / 1000.0)
    t1 = os.path.join(tmpdir, "aparado.wav")
    sh(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", bruto,
        "-af", cadeia, "-c:a", "pcm_f32le", "-ar", str(sr_arq),
        "-ac", str(canais), t1])

    # 4 · MEDIR depois de aparar (é o passo que os 5,0 LU do `pop` justificam)
    lufs_aparado = qs.lufs_em_loop(t1)
    alvo_faixa = sfx.get("lufs_alvo") or qs.SFX_PADRAO["lufs_alvo"]
    alvo = (min(alvo_faixa) + max(alvo_faixa)) / 2.0
    med_aparado = qs.medir_arquivo(t1, sr_medicao, com_lufs=False)
    ganho = 0.0 if lufs_aparado is None else alvo - lufs_aparado
    limite_pico = TETO_PICO_DBFS - (med_aparado["pico_dbfs"] or TETO_PICO_DBFS)
    limitado = None
    if ganho > limite_pico:
        # 🔴 normalizar até clipar seria trocar um defeito medido por outro. O
        # arquivo sai mais baixo que o alvo e o QC ACUSA — que é o certo.
        limitado = "pico: ganho %.2f dB reduzido para %.2f dB" % (ganho, limite_pico)
        ganho = limite_pico

    # 5 · NORMALIZAR e RE-MEDIR
    t2 = os.path.join(tmpdir, "final.wav")
    sh(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", t1,
        "-af", "volume=%.4fdB" % ganho, "-c:a", "pcm_s16le",
        "-ar", str(sr_arq), "-ac", str(canais), t2])
    depois = qs.medir_arquivo(t2, sr_medicao)

    d_corpo = abs(depois["corpo_ms"] - antes["corpo_ms"])
    if d_corpo > TETO_DELTA_CORPO_MS:
        return {"recusado": "o aparo mudou o corpo em %.1f ms (teto %.1f) — comeu "
                            "som, não silêncio" % (d_corpo, TETO_DELTA_CORPO_MS),
                "antes": antes, "depois": depois, "classe": classe}
    if depois["onset_ms"] > TETO_ONSET_DEPOIS_MS:
        return {"recusado": "onset depois = %.1f ms (teto %.1f) — o aparo não "
                            "resolveu" % (depois["onset_ms"], TETO_ONSET_DEPOIS_MS),
                "antes": antes, "depois": depois, "classe": classe}
    return {"recusado": None, "antes": antes, "depois": depois, "classe": classe,
            "arquivo": t2, "ganho_db": round(ganho, 2),
            "ganho_limitado_por": limitado, "lufs_aparado": lufs_aparado,
            "sr": sr_arq, "canais": canais, "declick_ms": declick_ms,
            "corte_s": [round(ini, 6), round(fim, 6)]}


def sidecar(nome, classe, origem, antes, depois, caminho_wav, extra=None):
    doc = {
        "schema": qs.CONTRATO_SIDECAR,
        "nome": nome,
        "classe": classe,
        "origem": origem,
        "antes": {k: antes[k] for k in ("onset_ms", "corpo_ms", "lufs", "pico_dbfs")
                  if k in antes},
        "depois": {k: depois[k] for k in ("onset_ms", "corpo_ms", "lufs", "pico_dbfs")
                   if k in depois},
        "sha256_wav": qs.sha256_arquivo(caminho_wav),
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gerado_por": "sfx-preparar.py",
    }
    if extra:
        doc.update(extra)
    return doc


def gravar_sidecar(dirsaida, nome, doc):
    p = os.path.join(dirsaida, nome + ".json")
    with open(p, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return p


def _perfil(args):
    p, aviso = qs.perfil_nomeado(args.perfil)
    sfx = {**qs.SFX_PADRAO, **(p.get("sfx") or {})}
    return sfx, int(p["audio"]["sr"]), float(args.fps or p["video"]["fps"]), aviso


# ══════════════════════════════════════════════════════════════════════ comandos

def cmd_um(args, sfx, sr, fps):
    import shutil
    import tempfile
    destino_dir = args.saida or qs.dir_biblioteca_padrao()
    if not destino_dir:
        print("sem diretório de saída: use --saida (ou $BENCH_SFX_DIR)",
              file=sys.stderr)
        return 2
    os.makedirs(destino_dir, exist_ok=True)
    nome = args.nome or os.path.splitext(os.path.basename(args.bruto))[0]
    tmp = tempfile.mkdtemp(prefix="sfx-preparar-")
    try:
        r = preparar(args.bruto, destino_dir, classe=args.classe, sfx=sfx,
                     sr_medicao=sr, tmpdir=tmp)
        a = r["antes"]
        print("%s (%s) onset %.1f → %s ms · corpo %.0f → %s ms · lufs %s → %s"
              % (nome, r["classe"], a["onset_ms"],
                 "%.1f" % r["depois"]["onset_ms"] if r.get("depois") else "—",
                 a["corpo_ms"],
                 "%.0f" % r["depois"]["corpo_ms"] if r.get("depois") else "—",
                 a.get("lufs"), r["depois"].get("lufs") if r.get("depois") else "—"))
        if r["recusado"]:
            print("RECUSADO: %s" % r["recusado"])
            return 1
        if r.get("ganho_limitado_por"):
            print("ganho limitado — %s" % r["ganho_limitado_por"])
        alvo = os.path.join(destino_dir, nome + ".wav")
        shutil.copyfile(r["arquivo"], alvo)
        origem = {"tipo": "arquivo", "caminho": os.path.relpath(args.bruto),
                  "sha256": qs.sha256_arquivo(args.bruto),
                  "licenca": args.licenca, "fonte": args.fonte, "seed": None}
        doc = sidecar(nome, r["classe"], origem, r["antes"], r["depois"], alvo,
                      {"ganho_db": r["ganho_db"], "corte_s": r["corte_s"],
                       "reprocessado": True})
        gravar_sidecar(destino_dir, nome, doc)
        print("escrito: %s (+ sidecar)" % alvo)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_migrar(args, sfx, sr, fps):
    import shutil
    import tempfile
    lib = args.saida or qs.dir_biblioteca_padrao()
    if not lib or not os.path.isdir(lib):
        print("biblioteca de SFX não encontrada (use --saida ou $BENCH_SFX_DIR)",
              file=sys.stderr)
        return 2
    so = set(x for x in (args.so or "").split(",") if x)
    lim = qs.atraso_max_ms(sfx, fps)
    alvos, medidos = [], 0
    for p in qs.arquivos_da_biblioteca(lib):
        nome = os.path.splitext(os.path.basename(p))[0]
        if so and nome not in so:
            continue
        medidos += 1
        m = qs.medir_arquivo(p, sr, com_lufs=False)
        if m["onset_ms"] > lim:
            alvos.append((p, nome, m))
    print("varridos: %d arquivo(s) · atraso_max %.2f ms · candidatos: %d"
          % (medidos, lim, len(alvos)))
    if not alvos:
        print("nada a migrar")
        return 0
    hist = os.path.join(lib, "_historico")
    rc = 0
    for p, nome, m in alvos:
        tmp = tempfile.mkdtemp(prefix="sfx-migrar-")
        try:
            r = preparar(p, lib, classe=args.classe, sfx=sfx, sr_medicao=sr,
                         tmpdir=tmp)
            if r["recusado"]:
                print("  %-14s RECUSADO: %s" % (nome, r["recusado"]))
                rc = 1
                continue
            d = r["depois"]
            print("  %-14s onset %.1f → %.1f ms · corpo %.0f → %.0f ms (Δ%.1f) · "
                  "lufs %s → %s%s"
                  % (nome, m["onset_ms"], d["onset_ms"], m["corpo_ms"],
                     d["corpo_ms"], abs(d["corpo_ms"] - m["corpo_ms"]),
                     r["lufs_aparado"], d.get("lufs"),
                     "  [ganho limitado]" if r.get("ganho_limitado_por") else ""))
            if not args.confirmar:
                continue
            os.makedirs(hist, exist_ok=True)
            sha = qs.sha256_arquivo(p)
            arq_hist = os.path.join(hist, "%s-%s%s"
                                    % (nome, sha[:8], os.path.splitext(p)[1]))
            shutil.copyfile(p, arq_hist)          # NUNCA apagar o anterior
            shutil.copyfile(r["arquivo"], p)
            antes_completo = qs.medir_arquivo(arq_hist, sr)
            origem = {"tipo": "arquivo",
                      "caminho": os.path.relpath(arq_hist, lib),
                      "sha256": sha, "licenca": args.licenca,
                      "fonte": args.fonte or "migrado por sfx-preparar.py",
                      "seed": None}
            doc = sidecar(nome, r["classe"], origem, antes_completo, r["depois"], p,
                          {"ganho_db": r["ganho_db"], "corte_s": r["corte_s"],
                           "reprocessado": True,
                           "ganho_limitado_por": r.get("ganho_limitado_por")})
            gravar_sidecar(lib, nome, doc)
            print("      histórico: %s" % os.path.relpath(arq_hist, lib))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if not args.confirmar:
        print("(dry-run: nada foi escrito — repita com --confirmar)")
    return rc


def cmd_selar(args, sfx, sr, fps):
    """Sidecar para arquivo que JÁ está certo — medição + sha256, sem reprocessar.

    Reprocessar um arquivo que já está correto é gerar diferença binária sem
    ganho, e diferença binária num asset compartilhado é o começo do órfão."""
    lib = args.saida or qs.dir_biblioteca_padrao()
    if not lib or not os.path.isdir(lib):
        print("biblioteca de SFX não encontrada", file=sys.stderr)
        return 2
    n = 0
    for p in qs.arquivos_da_biblioteca(lib):
        nome = os.path.splitext(os.path.basename(p))[0]
        alvo = os.path.join(lib, nome + ".json")
        if os.path.exists(alvo) and not args.refazer:
            continue
        m = qs.medir_arquivo(p, sr)
        classe = qs.classe_de(m["corpo_ms"], sfx.get("corpo_acento_max_ms", 400))
        print("  %-14s onset %.1f ms · corpo %.0f ms · %s · lufs %s"
              % (nome, m["onset_ms"], m["corpo_ms"], classe, m.get("lufs")))
        n += 1
        if not args.confirmar:
            continue
        origem = {"tipo": "desconhecida", "caminho": None, "sha256": None,
                  "licenca": args.licenca, "fonte": args.fonte, "seed": None}
        gravar_sidecar(lib, nome,
                       sidecar(nome, classe, origem, m, m, p,
                               {"reprocessado": False,
                                "_nota": "arquivo anterior a esta spec: a "
                                         "procedência não é conhecida e não se "
                                         "inventa. `antes` == `depois` porque "
                                         "nada foi reprocessado."}))
    print("selados: %d arquivo(s)%s"
          % (n, "" if args.confirmar else "  (dry-run: repita com --confirmar)"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bruto", nargs="?")
    ap.add_argument("--nome")
    ap.add_argument("--classe", choices=("acento", "textura", "auto"),
                    default="auto")
    ap.add_argument("--saida", default=None)
    ap.add_argument("--perfil", default=None)
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--licenca", default=None)
    ap.add_argument("--fonte", default=None)
    ap.add_argument("--migrar", action="store_true")
    ap.add_argument("--selar", action="store_true")
    ap.add_argument("--so", default=None, help="migrar só estes nomes (a,b,c)")
    ap.add_argument("--refazer", action="store_true",
                    help="--selar: reescreve sidecar existente")
    ap.add_argument("--confirmar", action="store_true",
                    help="sem isto, --migrar e --selar só IMPRIMEM o que fariam")
    args = ap.parse_args(argv)

    try:
        sfx, sr, fps, aviso = _perfil(args)
    except qs.ErroSfx as e:
        print(str(e), file=sys.stderr)
        return 2
    if aviso:
        print("aviso: %s" % aviso, file=sys.stderr)
    if args.migrar:
        return cmd_migrar(args, sfx, sr, fps)
    if args.selar:
        return cmd_selar(args, sfx, sr, fps)
    if not args.bruto:
        ap.print_usage(sys.stderr)
        return 2
    return cmd_um(args, sfx, sr, fps)


if __name__ == "__main__":
    sys.exit(main())
