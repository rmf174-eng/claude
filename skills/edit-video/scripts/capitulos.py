#!/usr/bin/env python3
"""capitulos.py — `chapters.txt` para colar na descrição do YouTube (SPEC-21).

    capitulos.py <dir> [-o chapters.txt] [--forcar] [--json]

    stdout: o caminho do artefato · stderr: o bloco e o resumo
    exit 0 ok · 1 validação falhou · 2 declarado e sem capítulo declarado

────────────────────────────────────────────────────────────────────────────
DE ONDE VÊM OS CAPÍTULOS — as duas entradas SE SOMAM

 1. `"capitulo": "Título"` no SEGMENTO da EDL — o mecanismo do ref-A
    (`helpers/chapters.py:4-7`), adotado tal e qual, com o campo em português.
    Âncora exata: `timeline_real.segments[i].start_s`. Quem faz o campo
    sobreviver ao `bordas.py` é a lista NEGRA da SPEC-05: escreva `capitulo` no
    `janelas.json` e ele atravessa até a EDL.
 2. `<dir>/capitulos.json`, para capítulo que NÃO cai em início de segmento
    (comum em longform, onde um segmento tem 40 s):

        {"schema": "benchmark.capitulos/v1",
         "capitulos": [{"i_seg": 7, "src_t": 412.30, "titulo": "O erro"}]}

    Posição via `edl_io.t_saida(tl, i_seg, src_t)`.

AS DIFERENÇAS PARA O ref-A, TODAS MEDIDAS E TODAS DE PROPÓSITO

  · As regras do YouTube são ERRO (exit 1), não warning (`chapters.py:69-81`
    imprime aviso e grava assim mesmo). `--forcar` grava, mas o exit continua 1.
  · `floor` no stamp, nunca `round` (`chapters.py:26`). Um stamp arredondado para
    CIMA cai DENTRO da seção e o espectador perde a primeira palavra — o mesmo
    defeito de decepar o primeiro fonema que este repo já pagou seis vezes. Com
    `floor` o erro é sempre ≤ 1 s PARA TRÁS e cai dentro do pad `pre` que o
    `bordas.py` deixa antes da fala. E `floor` dá `0:00` de graça para t < 1.
  · Capítulo de abertura ausente vira `titulo_abertura` do perfil (default
    "Introdução"), NUNCA a duplicata do título do primeiro (`chapters.py:58-61`
    insere `(0.0, chapters[0][1])` e deixa duas entradas idênticas no índice).
  · As regras são validadas NOS STAMPS FLOORED, não nos floats: é o que a
    plataforma enxerga.
  · O bloco vai para o STDERR; o stdout é o caminho do artefato (convenção do
    projeto). O `chapters.py:78` deles imprime o bloco no stdout.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                      # noqa: E402
import palavras as palavras_mod    # noqa: E402

SCHEMA = "benchmark.publicacao/v1"
SCHEMA_ENTRADA = "benchmark.capitulos/v1"
SEG_POR_HORA = 3600


class ErroCapitulos(Exception):
    pass


def stamp(t, total_s):
    """`H:MM:SS` se a peça passa de 1 h, senão `M:SS`. FLOOR, sempre."""
    n = int(t) if t > 0 else 0
    h, resto = divmod(n, SEG_POR_HORA)
    m, s = divmod(resto, 60)
    if total_s >= SEG_POR_HORA:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (h * 60 + m, s)


def _titulo_limpo(t, max_chars):
    if not isinstance(t, str):
        raise ErroCapitulos("título tem que ser string, veio %r" % (t,))
    limpo = " ".join(t.replace("\n", " ").replace("\r", " ").split())
    if not limpo:
        raise ErroCapitulos("título vazio")
    if len(limpo) > max_chars:
        raise ErroCapitulos("título com %d chars (máx %d): %r"
                            % (len(limpo), max_chars, limpo[:60]))
    return limpo


def coletar(d, tl, bloco):
    """[(t_saida, titulo, origem)] das duas entradas, ordenado. Não valida ainda."""
    max_t = bloco["max_chars_titulo"]
    itens = []
    # o campo `capitulo` mora na EDL, não na timeline (a timeline copia só o que
    # ela mesma mede). Ler da EDL é o que faz o passthrough da SPEC-05 valer.
    segs_edl = edl_io.segmentos(d)
    if len(segs_edl) != len(tl["segments"]):
        raise ErroCapitulos("EDL tem %d segmentos e a timeline %d — remonte"
                            % (len(segs_edl), len(tl["segments"])))
    for i, s in enumerate(segs_edl):
        if s.get("capitulo") in (None, ""):
            continue
        itens.append((tl["segments"][i]["start_s"],
                      _titulo_limpo(s["capitulo"], max_t),
                      "edl[%d]" % i))
    p = os.path.join(d, "capitulos.json")
    if os.path.isfile(p):
        with open(p) as fh:
            doc = json.load(fh)
        if doc.get("schema") not in (None, SCHEMA_ENTRADA):
            raise ErroCapitulos("%s: schema %r, esperado %r"
                                % (p, doc.get("schema"), SCHEMA_ENTRADA))
        for k, c in enumerate(doc.get("capitulos") or []):
            i = c.get("i_seg")
            if not isinstance(i, int) or not (0 <= i < len(tl["segments"])):
                raise ErroCapitulos("capitulos.json[%d]: i_seg=%r fora de 0..%d"
                                    % (k, i, len(tl["segments"]) - 1))
            seg = tl["segments"][i]
            if "src_t" in c and c["src_t"] is not None:
                t = edl_io.t_saida(tl, i, float(c["src_t"]))
                if not (seg["start_s"] - 1e-6 <= t <= seg["start_s"] + seg["dur_s"] + 1e-6):
                    raise ErroCapitulos(
                        "capitulos.json[%d]: src_t=%.3f não cai dentro do segmento %d "
                        "([%.3f, %.3f] no bruto)"
                        % (k, c["src_t"], i, seg.get("src_start", 0.0),
                           seg.get("src_end", 0.0)))
            else:
                t = seg["start_s"]
            itens.append((t, _titulo_limpo(c.get("titulo"), max_t),
                          "capitulos.json[%d]" % k))
    itens.sort(key=lambda x: x[0])
    for a, b in zip(itens, itens[1:]):
        if abs(a[0] - b[0]) < 1e-6:
            raise ErroCapitulos("dois capítulos no mesmo instante %.3f s: %r e %r"
                                % (a[0], a[1], b[1]))
    return itens


def montar(itens, tl, bloco):
    """[(stamp, titulo)] + lista de problemas. Valida NOS STAMPS, não nos floats."""
    total_s = tl["total_s"]
    problemas, avisos = [], []
    itens = list(itens)
    if itens and itens[0][0] >= 1.0:
        # NUNCA duplicar o título do primeiro (chapters.py:58-61 do ref-A).
        itens.insert(0, (0.0, bloco["titulo_abertura"], "titulo_abertura"))
        avisos.append("primeiro capítulo estava em %s — inseri %r em 0:00"
                      % (stamp(itens[1][0], total_s), bloco["titulo_abertura"]))
    linhas = [(stamp(t, total_s), tit) for t, tit, _ in itens]
    segundos = [_do_stamp(s) for s, _ in linhas]

    if not linhas or segundos[0] != 0:
        problemas.append("o primeiro stamp é %s — o YouTube exige 0:00"
                         % (linhas[0][0] if linhas else "(nenhum)"))
    if len(linhas) < bloco["minimo"]:
        problemas.append("%d capítulo(s) — o YouTube exige no mínimo %d para exibir "
                         "o índice" % (len(linhas), bloco["minimo"]))
    for k in range(1, len(segundos)):
        if segundos[k] <= segundos[k - 1]:
            problemas.append("stamps fora de ordem: %s depois de %s"
                             % (linhas[k][0], linhas[k - 1][0]))
    dmin = bloco["dur_min_s"]
    for k, (s, tit) in enumerate(linhas):
        prox = segundos[k + 1] if k + 1 < len(segundos) else int(total_s)
        dur = prox - segundos[k]
        if dur < dmin:
            problemas.append("capítulo %r tem %d s — mínimo %g s" % (tit, dur, dmin))
    return linhas, problemas, avisos


def _do_stamp(s):
    partes = [int(x) for x in s.split(":")]
    while len(partes) < 3:
        partes.insert(0, 0)
    return partes[0] * SEG_POR_HORA + partes[1] * 60 + partes[2]


def render(linhas):
    return "".join("%s %s\n" % (s, t) for s, t in linhas)


# ────────────────────────────────────────────────────────────────────── CLI

def _cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("────")[0].strip(), file=sys.stderr)
        return 64
    d = argv.pop(0)
    saida, forcar, como_json, perfil_off = None, False, False, False
    while argv:
        a = argv.pop(0)
        if a in ("-o", "--saida"):
            saida = argv.pop(0)
        elif a == "--forcar":
            forcar = True
        elif a == "--json":
            como_json = True
        elif a == "--perfil-off":
            perfil_off = True
        else:
            print("flag desconhecida: %s" % a, file=sys.stderr)
            return 64

    try:
        pub, origem = palavras_mod.publicacao(d, ignorar_perfil=perfil_off)
    except palavras_mod.ErroPublicacao as e:
        print("ERRO: %s" % e, file=sys.stderr)
        return 2
    bloco = pub["capitulos"]
    tl = edl_io.timeline(d, exigir=True)
    try:
        itens = coletar(d, tl, bloco)
    except ErroCapitulos as e:
        print("ERRO: %s" % e, file=sys.stderr)
        return 1

    gerar = bloco.get("gerar")
    if gerar is False:
        print("perfil %s: capítulos desligados (publicacao.capitulos.gerar=false)"
              % origem, file=sys.stderr)
        return 0
    if not itens:
        if gerar is None:            # AUTO (sem perfil.json): sem capítulo, sem arquivo
            print("nenhum capítulo declarado e nenhum perfil pedindo — nada a fazer",
                  file=sys.stderr)
            return 2
        print("ERRO: perfil %s declara capitulos.gerar=true e NÃO há capítulo "
              "declarado.\nDeclare `\"capitulo\": \"Título\"` no janelas.json (atravessa "
              "até a EDL) ou escreva %s."
              % (origem, os.path.join(d, "capitulos.json")), file=sys.stderr)
        return 2

    linhas, problemas, avisos = montar(itens, tl, bloco)
    for a in avisos:
        print("aviso: %s" % a, file=sys.stderr)
    bloco_txt = render(linhas)
    print(bloco_txt, end="", file=sys.stderr)
    for p in problemas:
        print("  ✗ %s" % p, file=sys.stderr)

    alvo = saida or bloco["arquivo"]
    alvo = alvo if os.path.isabs(alvo) else os.path.join(d, alvo)
    if problemas and not forcar:
        print("%d regra(s) do YouTube violada(s) — NÃO gravei %s. `--forcar` grava "
              "assim mesmo (e mantém o exit 1) para você ver o bloco e mover o "
              "capítulo." % (len(problemas), alvo), file=sys.stderr)
        if como_json:
            json.dump({"capitulos": [{"stamp": s, "titulo": t} for s, t in linhas],
                       "problemas": problemas}, sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
        return 1

    with open(alvo, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(bloco_txt)
    side = {
        "schema": SCHEMA, "gerado_por": "capitulos.py",
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "edl_fingerprint": tl.get("edl_fingerprint"),
        "perfil": origem,
        "regra": bloco,
        "capitulos": len(linhas),
        "origens": [o for _, _, o in itens],
        "total_s": tl["total_s"],
        "problemas": problemas,
    }
    with open(alvo + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(side, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    if como_json:
        json.dump({"capitulos": [{"stamp": s, "titulo": t} for s, t in linhas],
                   "problemas": problemas}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    print(alvo)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(_cli())
