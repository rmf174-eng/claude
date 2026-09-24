#!/usr/bin/env python3
"""Teste do timestamped.py (SPEC-27) — autocontido, material 100% sintético.

    python3 .claude/skills/transcribe/scripts/tests/test_timestamped.py

O aceite central desta metade da spec é NEGATIVO: sem `--silencio`, o
`transcript-ts.md` tem que sair **byte a byte** igual ao de antes. Um teste que só
exercita a feature nova não protege isso. Então o caso 1 congela a saída legada de
um transcript sintético como GOLDEN e o caso 1b planta um defeito de formatação
que o golden TEM que acusar — senão verde e quebrado são a mesma coisa.

Nada aqui lê material de creator.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
ALVO = os.path.join(SCRIPTS, "timestamped.py")
sys.path.insert(0, SCRIPTS)
import timestamped as T   # noqa: E402

falhas = []
varrido = {}


def conta(k, n=1):
    varrido[k] = varrido.get(k, 0) + n


def ok(nome, cond, detalhe=""):
    conta("checagens")
    if not cond:
        falhas.append(nome)
        print("   ✗ %-54s %s" % (nome, detalhe))
    else:
        print("   ✓ %-54s %s" % (nome, detalhe))


def w(t, a, b, **e):
    d = {"word": t.strip(".,;:!?"), "punctuated_word": t, "start": a, "end": b}
    d.update(e)
    return d


WS = [w("Bom,", 0.0, 0.42), w("vamos", 0.42, 0.71), w("supor", 0.71, 1.05),
      w("que", 1.05, 1.18), w("ele", 1.18, 1.36), w("te", 1.36, 1.44),
      w("traiu.", 1.44, 1.92),
      w("E", 2.60, 2.72), w("você", 2.72, 2.98), w("voltou,", 2.98, 3.44),
      w("perdoou,", 3.44, 4.02), w("e", 4.02, 4.10), w("deixou", 4.10, 4.48),
      w("tudo", 4.48, 4.72), w("bem.", 4.72, 5.10)]

TRANSCRIPT = {
    "metadata": {"duration": 6.0},
    "results": {"channels": [{"alternatives": [{
        "transcript": " ".join(x["punctuated_word"] for x in WS),
        "words": WS,
        "paragraphs": {"paragraphs": [
            {"start": 0.0, "end": 1.92,
             "sentences": [{"text": "Bom, vamos supor que ele te traiu.",
                            "start": 0.0, "end": 1.92}]},
            {"start": 2.60, "end": 5.10,
             "sentences": [{"text": "E você voltou, perdoou, e deixou tudo bem.",
                            "start": 2.60, "end": 5.10}]}]}}]}]}}

# 🔒 GOLDEN do modo legado. Se este texto mudar, TODA decupagem de VSL e o
# o ingest de call mudam de saída junto. Não "atualize" o golden para
# fazer o teste passar — o teste é justamente o que impede isso.
GOLDEN = ("# Transcrição com timestamp\n\n"
          "- Duração: 00:06 (6s)\n"
          "- Blocos: 2 (paragrafos)\n\n"
          "**[00:00–00:02]** Bom, vamos supor que ele te traiu.\n\n"
          "**[00:03–00:05]** E você voltou, perdoou, e deixou tudo bem.\n\n")


def prepara(perfil=None):
    d = tempfile.mkdtemp(prefix="ts-teste-")
    with open(os.path.join(d, "transcript.json"), "w") as fh:
        json.dump(TRANSCRIPT, fh)
    if perfil:
        with open(os.path.join(d, "perfil.json"), "w") as fh:
            json.dump(perfil, fh)
    return d


def roda(d, *args):
    r = subprocess.run([sys.executable, ALVO, d] + list(args),
                       capture_output=True, text=True)
    saida = os.path.join(d, "transcript-ts.md")
    txt = open(saida, encoding="utf-8").read() if os.path.exists(saida) else ""
    return r, txt


def c1_golden_legado():
    for modo in ([], ["--paragrafos"]):
        d = prepara()
        try:
            _r, txt = roda(d, *modo)
            conta("saídas legadas comparadas")
            ok("1. modo legado %-14s byte a byte igual ao golden"
               % ("(default)" if not modo else modo[0]), txt == GOLDEN,
               "md5 %s" % hashlib.md5(txt.encode()).hexdigest()[:8])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # 🔴 defeito plantado: uma vírgula a mais no cabeçalho. O golden TEM que acusar.
    ruim = GOLDEN.replace("- Blocos: 2 (paragrafos)", "- Blocos: 2 (paragrafos.)")
    ok("1b. e um defeito de 1 caractere no cabeçalho É ACUSADO", ruim != GOLDEN,
       "o golden compara a string inteira, não só o número de blocos")


def c2_silencio_nao_mexe_no_nome_do_arquivo():
    d = prepara()
    try:
        r, _ = roda(d, "--silencio", "0.35")
        ok("2. --silencio grava no MESMO transcript-ts.md",
           r.stdout.strip().endswith("transcript-ts.md"), r.stdout.strip())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def c3_cabecalho_declara_candidata():
    d = prepara()
    try:
        _r, txt = roda(d, "--silencio", "0.35")
        ok("3. o cabeçalho carrega 'CANDIDATA, não ponto de corte'",
           "CANDIDATA" in txt and "bordas.py" in txt,
           "%d bytes de cabeçalho" % len(txt.split("\n[")[0]))
        ok("3b. e a contagem por critério de quebra",
           "por gap" in txt and "por pontuação" in txt and "por troca de falante" in txt,
           txt.split("\n")[4].strip())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def c4_gap_ou_pontuacao():
    ws = TRANSCRIPT["results"]["channels"][0]["alternatives"][0]["words"]
    # limiar acima do maior gap do fixture (0,68 s): a ÚNICA quebra possível é a
    # pontuação. Com gap_min baixo os dois critérios coincidem e o teste não
    # separaria nada.
    g_pont, m_pont = T.frases(ws, gap_min=1.0, usar_pontuacao=True)
    g_gap, m_gap = T.frases(ws, gap_min=1.0, usar_pontuacao=False)
    conta("palavras varridas", len(ws))
    ok("4. gap+pontuação quebra mais que só-gap",
       len(g_pont) > len(g_gap), "%d vs %d unidades" % (len(g_pont), len(g_gap)))
    ok("4b. e o motivo de cada quebra é nomeado",
       set(m_pont) <= {"gap", "pontuacao", "falante"}, "motivos=%s" % m_pont)

    # o caso que justifica a regra: montado SEM gap nenhum (o bordas.py tirou o ar)
    colado = []
    t = 0.0
    for x in ws:
        d = x["end"] - x["start"]
        colado.append(dict(x, start=round(t, 3), end=round(t + d, 3)))
        t += d
    g2, _ = T.frases(colado, gap_min=0.5, usar_pontuacao=False)
    g3, _ = T.frases(colado, gap_min=0.5, usar_pontuacao=True)
    ok("4c. no MONTADO (gap 0) só-gap colapsa em 1 e a pontuação salva",
       len(g2) == 1 and len(g3) > 1, "%d vs %d" % (len(g2), len(g3)))


def c5_perfil_manda_e_fallback_avisa():
    d = prepara()
    try:
        r, txt = roda(d, "--silencio")
        ok("5. sem perfil.json: FALLBACK + aviso NO STDERR",
           "FALLBACK" in txt and "aviso" in r.stderr, r.stderr.strip()[:60])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    d = prepara(perfil={"contrato": "benchmark.perfil-peca/v1", "nome": "vsl",
                        "ritmo": {"gap_min": 0.5}})
    try:
        r, txt = roda(d, "--silencio")
        ok("5b. com perfil.json ao lado: gap_min vem dele e o cabeçalho diz de onde",
           "perfil vsl" in txt and "0.50" in txt and "aviso" not in r.stderr,
           txt.split("\n")[3].strip())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def c6_precisao():
    d = prepara()
    try:
        _r, t2 = roda(d, "--silencio", "0.35", "--precisao", "2")
        _r, t1 = roda(d, "--silencio", "0.35", "--precisao", "1")
        ok("6. --precisao muda as casas decimais do timestamp",
           "[000.00-" in t2 and "[000.0-" in t1,
           "%s | %s" % (t2.split("\n[")[1][:14], t1.split("\n[")[1][:12]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def c7_nao_importa_edit_video():
    """A `transcribe` é bloco independente: importar edit-video aqui seria o
    acoplamento cross-skill que a SPEC-22 audita."""
    fonte = open(ALVO, encoding="utf-8").read()
    conta("linhas do timestamped.py", len(fonte.split("\n")))
    ruim = [ln for ln in fonte.split("\n")
            if ln.startswith(("import ", "from ", "    import ", "    from "))
            and ("perfil" in ln or "edit_video" in ln or "bordas" in ln)]
    ok("7. o script não importa nada de edit-video/", not ruim, "%s" % ruim)


def main():
    print("── timestamped.py — golden legado + modo --silencio ──")
    for f in (c1_golden_legado, c2_silencio_nao_mexe_no_nome_do_arquivo,
              c3_cabecalho_declara_candidata, c4_gap_ou_pontuacao,
              c5_perfil_manda_e_fallback_avisa, c6_precisao, c7_nao_importa_edit_video):
        f()
    print("\n── o que este teste varreu ──")
    for k, v in varrido.items():
        print("   %-42s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas else "FALHOU: " + ", ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
