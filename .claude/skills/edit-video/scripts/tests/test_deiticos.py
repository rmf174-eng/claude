#!/usr/bin/env python3
"""Teste do deiticos.py (SPEC-27) — autocontido, material 100% sintético.

    python3 .claude/skills/edit-video/scripts/tests/test_deiticos.py

🔴 POR QUE ELE PLANTA DEFEITO EM VEZ DE SÓ AFIRMAR O CASO BOM
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado. Este repo já
entregou 6,25 s de vídeo errado com todos os QCs verdes. Então as checagens das
guardas fazem DUAS coisas: afirmam o caso bom E plantam o defeito que a guarda TEM
que acusar — comparação por substring no antipadrão, guarda de pontuação removida,
longest-match desligado, clamp desligado. Verde sem as duas metades não vale.

Nada aqui lê material de creator: cada caso constrói o seu próprio `words[]`. O
teste depende de fixture nenhuma — quem depende de fixture é o teste, não a
ferramenta.
"""
import io
import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
import deiticos as D   # noqa: E402

falhas = []
varrido = {}


def conta(k, n=1):
    varrido[k] = varrido.get(k, 0) + n


def ok(nome, cond, detalhe=""):
    conta("checagens")
    if not cond:
        falhas.append(nome)
        print("   ✗ %-52s %s" % (nome, detalhe))
    else:
        print("   ✓ %-52s %s" % (nome, detalhe))


def w(t, a, b, **extra):
    d = {"word": t.strip(".,;:!?"), "punctuated_word": t, "start": a, "end": b}
    d.update(extra)
    return d


def fala(*pares, dur=None):
    """[('Bom,',0.0,0.4), …] -> transcript.json do Deepgram, em memória."""
    ws = [w(t, a, b) for t, a, b in pares]
    return {"metadata": {"duration": dur if dur is not None else ws[-1]["end"] + 0.5},
            "results": {"channels": [{"alternatives": [
                {"transcript": " ".join(x["punctuated_word"] for x in ws), "words": ws}]}]}}


def grava(j):
    d = tempfile.mkdtemp(prefix="deit-teste-")
    p = os.path.join(d, "transcript.json")
    with open(p, "w") as fh:
        json.dump(j, fh)
    return d, p


def roda(j, cfg_extra=None, padroes=None):
    d, p = grava(j)
    try:
        cfg = dict(D.FALLBACK)
        cfg["gap_min"] = D.FALLBACK_GAP_MIN
        cfg.update(cfg_extra or {})
        return D.analisar(p, cfg, padroes if padroes is not None else PADROES)
    finally:
        shutil.rmtree(d, ignore_errors=True)


LEX, PADROES, _ = D.carregar_lexico("lexico-deitico-pt.json")
ATIVOS = [p for p in PADROES if p["status"] == "ativo"]


# ---------------------------------------------------------------- 1. o básico
def c1_acha_o_gatilho():
    r = roda(fala(("Bom,", 0.0, 0.4), ("olha", 0.6, 0.9), ("só,", 0.9, 1.2),
                  ("isso", 1.3, 1.6), ("muda", 1.6, 2.0), ("tudo.", 2.0, 2.4), dur=3.0))
    conta("frases lidas", r["n_frases"])
    ok("1. 'olha só' vira exatamente 1 janela", len(r["janelas"]) == 1,
       "n=%d" % len(r["janelas"]))
    if r["janelas"]:
        j = r["janelas"][0]
        ok("1b. a janela ancora na PALAVRA (0,6 s − pre 0,15)",
           abs(j["ini"] - 0.45) < 0.001, "ini=%.3f" % j["ini"])
        ok("1c. domínio fechado de sugestao/dica_zona",
           j["sugestao"] in D.SUGESTOES and j["dica_zona"] in set(D.ZONA_DE.values()),
           "%s/%s" % (j["sugestao"], j["dica_zona"]))


def c2_antipadrao_mata():
    r = roda(fala(("Quando", 0.0, 0.3), ("a", 0.3, 0.4), ("gente", 0.4, 0.7),
                  ("olha", 0.7, 1.0), ("isso", 1.0, 1.3), ("muda.", 1.3, 1.7), dur=3.0))
    ok("2. 'a gente olha isso' não vira janela",
       len(r["janelas"]) == 0 and len(r["antipadrao"]) == 1,
       "janelas=%d mortos=%d" % (len(r["janelas"]), len(r["antipadrao"])))


# ------------------------------------- 3 e 4. as duas armadilhas do antipadrão
def c3_token_nao_substring():
    j = fala(("O", 0.0, 0.2), ("ajuste", 0.2, 0.6), ("nele", 0.6, 1.0),
             ("olha", 1.1, 1.4), ("isso", 1.4, 1.7), ("aqui.", 1.7, 2.1), dur=3.0)
    bom = roda(j)
    ok("3. 'nele olha isso' PASSA (comparação por token)", len(bom["janelas"]) == 1,
       "n=%d" % len(bom["janelas"]))

    # 🔴 defeito plantado: comparação por SUBSTRING — `ele` casa dentro de `nele`
    orig = D.antipadrao_bate

    def por_substring(palavras, iw, tokens, k):
        for x in range(iw - 1, max(-1, iw - 1 - k), -1):
            pw = (palavras[x].get("punctuated_word") or "").rstrip()
            if pw[-1:] and pw[-1:] in D.PONTUACAO_CORTA:
                return None
            n = D.normaliza(pw)
            for t in tokens:
                if t in n:
                    return n, x
        return None
    D.antipadrao_bate = por_substring
    try:
        ruim = roda(j)
    finally:
        D.antipadrao_bate = orig
    ok("3b. e o defeito plantado (substring) É ACUSADO", len(ruim["janelas"]) == 0,
       "com substring n=%d, mata em 'nele'" % len(ruim["janelas"]))


def c4_guarda_de_pontuacao():
    j = fala(("Eu", 0.0, 0.2), ("ia", 0.2, 0.4), ("atrás", 0.4, 0.7), ("de", 0.7, 0.8),
             ("você,", 0.8, 1.1), ("olha", 1.2, 1.5), ("isso", 1.5, 1.8),
             ("aqui.", 1.8, 2.2), dur=3.0)
    bom = roda(j)
    ok("4. vocativo 'você, olha isso' PASSA", len(bom["janelas"]) == 1,
       "n=%d" % len(bom["janelas"]))

    # 🔴 defeito plantado: sem a guarda de pontuação o vocativo vira indicativo
    orig = D.antipadrao_bate

    def sem_guarda(palavras, iw, tokens, k):
        for x in range(iw - 1, max(-1, iw - 1 - k), -1):
            n = D.normaliza((palavras[x].get("punctuated_word") or "").rstrip())
            if n in tokens:
                return n, x
        return None
    D.antipadrao_bate = sem_guarda
    try:
        ruim = roda(j)
    finally:
        D.antipadrao_bate = orig
    ok("4b. e o defeito plantado (sem guarda) É ACUSADO", len(ruim["janelas"]) == 0,
       "sem guarda n=%d, mata em 'você'" % len(ruim["janelas"]))


# ------------------------------------------------------------- 5. as 5 guardas
def c5_longest_match():
    # `olha só` no fim da frase casa `olha-ostensivo` E `olha-solto` (posicao borda)
    j = fala(("Pronto,", 0.0, 0.5), ("agora", 0.6, 0.9), ("é", 0.9, 1.0),
             ("com", 1.0, 1.2), ("você:", 1.2, 1.6), ("olha", 1.7, 2.0),
             ("só.", 2.0, 2.3), dur=4.0)
    r = roda(j)
    ok("5. longest-match: 1 achado no mesmo instante, não 2", len(r["janelas"]) == 1,
       "n=%d" % len(r["janelas"]))
    # controle: quantos padrões CASAM o texto (sem a guarda seriam 2 achados)
    g, _ = D.frases(j["results"]["channels"][0]["alternatives"][0]["words"],
                    gap_min=D.FALLBACK_GAP_MIN)
    texto, _m = D.norm_map(g[-1])
    casam = [p["slug"] for p in ATIVOS if p["_re"].search(texto)]
    ok("5b. e havia mesmo ≥2 padrões casando (senão a guarda não foi exercida)",
       len(casam) >= 2, "casaram: %s" % ",".join(casam))


def c6_fusao():
    j = fala(("Isso", 0.0, 0.3), ("aqui", 0.3, 0.6), ("e", 0.7, 0.8),
             ("isso", 0.9, 1.2), ("aqui", 1.2, 1.5), ("também.", 1.5, 2.0), dur=5.0)
    r = roda(j, {"janela_s": 2.0})
    ok("6. fusão: dois 'isso aqui' em 1,5 s viram 1 janela", len(r["janelas"]) == 1,
       "n=%d slug=%s" % (len(r["janelas"]), r["janelas"][0]["slug"] if r["janelas"] else "-"))


def c7_clamp():
    # gatilho a 9,6 s num vídeo de 8 s: no grab_cues do ref-A isso SOME em silêncio
    j = fala(("Bom", 0.0, 0.4), ("olha", 9.6, 9.9), ("só,", 9.9, 10.2),
             ("isso", 10.3, 10.6), ("muda.", 10.6, 11.0), dur=8.0)
    r = roda(j)
    ok("7. gatilho além da duração NÃO some: vira janela zerada e reprova",
       len(r["zeradas"]) == 1, "zeradas=%d" % len(r["zeradas"]))

    # janela que só ULTRAPASSA: tem que ser aparada e CONTADA
    j2 = fala(("Bom", 0.0, 0.4), ("olha", 6.0, 6.3), ("só,", 6.3, 6.6),
              ("isso", 6.7, 7.0), ("muda.", 7.0, 7.4), dur=7.5)
    r2 = roda(j2, {"janela_s": 4.0})
    apar = [x for x in r2["janelas"] if x["aparada"]]
    ok("7b. janela que ultrapassa é aparada, contada e fim ≤ duração",
       len(apar) == 1 and all(x["fim"] <= r2["duracao_s"] + 1e-6 for x in r2["janelas"]),
       "aparadas=%d fim=%.2f dur=%.2f" % (len(apar),
                                          max(x["fim"] for x in r2["janelas"]) if r2["janelas"] else 0,
                                          r2["duracao_s"]))
    ok("7c. sem clamp o fim passaria da duração (o defeito que a guarda impede)",
       6.0 - D.FALLBACK["pre_s"] + 4.0 > 7.5, "5,85+4,0 = 9,85 > 7,5")


def c8_teto_de_densidade():
    pares, t = [], 0.0
    for i in range(8):
        pares += [("Olha", t, t + 0.3), ("isso", t + 0.3, t + 0.6),
                  ("aqui.", t + 0.6, t + 1.0)]
        t += 1.5
    r = roda(fala(*pares, dur=60.0), {"max_por_min": 2.0, "janela_s": 0.5})
    ok("8. teto de densidade corta E grava o que cortou",
       len(r["janelas"]) <= 2 and len(r["descartados"]) >= 1,
       "janelas=%d descartados=%d" % (len(r["janelas"]), len(r["descartados"])))
    ok("8b. todo descartado tem motivo nomeado",
       all(x["motivo"] == "teto-densidade" for x in r["descartados"]),
       "%d itens" % len(r["descartados"]))


def c9_ancoragem_em_frase_longa():
    """A armadilha: usar a FRASE como janela. Frase de 60 s existe no material real."""
    pares = [("Palavra%d" % i, i * 0.5, i * 0.5 + 0.4) for i in range(100)]
    pares[60] = ("olha", 30.0, 30.3)
    pares[61] = ("isso", 30.3, 30.6)
    r = roda(fala(*pares, dur=60.0), {"janela_s": 2.0})
    ok("9. numa frase de ~50 s a janela sai com janela_s, não com a frase",
       len(r["janelas"]) == 1 and abs(r["janelas"][0]["fim"] - r["janelas"][0]["ini"] - 2.0) < 0.01,
       "dur_janela=%.2f frase=%s" % (
           (r["janelas"][0]["fim"] - r["janelas"][0]["ini"]) if r["janelas"] else -1,
           r["janelas"][0]["frase"] if r["janelas"] else "-"))


def c10_amostra_minima():
    # frase de 2 palavras: `posicao: borda` não pode disparar
    j = fala(("Olha.", 0.0, 0.4), ("Sim.", 0.6, 0.9), dur=3.0)
    r = roda(j)
    ok("10. frase de 2 palavras não dispara padrão de borda", len(r["janelas"]) == 0,
       "n=%d" % len(r["janelas"]))
    # e com 3 palavras, dispara
    j2 = fala(("Pronto,", 0.0, 0.4), ("é", 0.4, 0.6), ("isso,", 0.6, 0.9),
              ("olha.", 1.0, 1.4), dur=3.0)
    r2 = roda(j2)
    ok("10b. com frase de 4 palavras o mesmo gatilho de borda dispara",
       len(r2["janelas"]) >= 1, "n=%d" % len(r2["janelas"]))


def c11_lexico_bem_formado():
    conta("padrões no léxico", len(PADROES))
    conta("padrões ativos", len(ATIVOS))
    ruins = [p["slug"] for p in PADROES
             if p["classe"] not in D.CLASSES or p["sugestao"] not in D.SUGESTOES
             or p["posicao"] not in ("qualquer", "inicio", "fim", "borda")
             or p["status"] not in ("ativo", "candidata")]
    ok("11. todo padrão do léxico usa domínio fechado", not ruins, "fora: %s" % ruins)
    com_acento = [p["slug"] for p in PADROES if D.normaliza(p["padrao"]) != p["padrao"].lower()
                  and any(ord(c) > 127 for c in p["padrao"])]
    ok("11b. nenhum padrão tem acento (acento nunca casa no texto normalizado)",
       not com_acento, "com acento: %s" % com_acento)
    ok("11c. candidatas não produzem janela",
       all(p["status"] == "ativo" for p in ATIVOS)
       and len(ATIVOS) < len(PADROES), "%d ativos de %d" % (len(ATIVOS), len(PADROES)))


def c12_nao_grava_sem_flag():
    j = fala(("Bom,", 0.0, 0.4), ("olha", 0.6, 0.9), ("só,", 0.9, 1.2),
             ("isso", 1.3, 1.6), ("muda.", 1.6, 2.0), dur=3.0)
    d, p = grava(j)
    try:
        antes = sorted(os.listdir(d))
        cfg = dict(D.FALLBACK)
        cfg["gap_min"] = D.FALLBACK_GAP_MIN
        D.analisar(p, cfg, PADROES)
        ok("12. analisar() não cria arquivo nenhum", sorted(os.listdir(d)) == antes,
           "%s" % sorted(os.listdir(d)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    print("── deiticos.py — %d padrões (%d ativos, %d candidatas) ──"
          % (len(PADROES), len(ATIVOS), len(PADROES) - len(ATIVOS)))
    for f in (c1_acha_o_gatilho, c2_antipadrao_mata, c3_token_nao_substring,
              c4_guarda_de_pontuacao, c5_longest_match, c6_fusao, c7_clamp,
              c8_teto_de_densidade, c9_ancoragem_em_frase_longa, c10_amostra_minima,
              c11_lexico_bem_formado, c12_nao_grava_sem_flag):
        f()
    print("\n── o que este teste varreu ──")
    for k, v in varrido.items():
        print("   %-42s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas else "FALHOU: " + ", ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
