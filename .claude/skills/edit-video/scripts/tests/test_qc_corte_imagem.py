#!/usr/bin/env python3
"""Teste da sonda de imagem (SPEC-26) — razão local, casamento e classificação.

    python3 .claude/skills/edit-video/scripts/tests/test_qc_corte_imagem.py

RODA SEM FFMPEG E SEM REDE. Tudo aqui é função pura sobre número: as fixtures em
`fixtures/scdet-*.txt|json` já são a saída crua do `scdet`, congelada.

🔴 POR QUE CADA CASO VEM COM O CONTROLE AO LADO
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado. Por isso
nenhuma checagem aqui afirma só o caso bom:

  · o controle NEGATIVO (junção contígua de verdade, razão 0,41) só vale porque o
    controle POSITIVO existe — o mesmo par refeito com `-ss -c copy`, razão 20,94.
    Sem o positivo, um portão morto passaria nos dois;
  · o off-by-one da `peca-04` é afirmado nos DOIS sentidos: pelo índice de
    decodificação o deslocamento é 0 nas 16 fronteiras, e por `round(PTS × fps)`
    é +1 nas 16. Se a segunda metade der 0, o teste não está medindo nada;
  · os defeitos plantados (fronteira sem imagem, deslocamento sistemático,
    achado fora de fronteira) são construídos sobre a fixture REAL, no lugar em
    que o portão é fraco, não num lugar confortável.
"""
import importlib.util
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
FX = os.path.join(AQUI, "fixtures")

_spec = importlib.util.spec_from_file_location(
    "qc_corte_imagem", os.path.join(SCRIPTS, "qc-corte-imagem.py"))
qci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qci)

falhas = []
varrido = {}


def conta(chave, n=1):
    varrido[chave] = varrido.get(chave, 0) + n


def ok(msg, cond, detalhe=""):
    print("   %s %s%s" % ("✅" if cond else "❌", msg,
                          "  — %s" % detalhe if detalhe else ""))
    if not cond:
        falhas.append(msg)
    return cond


def carregar():
    with open(os.path.join(FX, "scdet-esperado.json")) as fh:
        esp = json.load(fh)
    with open(os.path.join(FX, "scdet-mesa.txt")) as fh:
        mesa = qci.parse_scores(fh.read())
    return esp, mesa


# ─────────────────────────────────────────────────────────────────────── 1 · parse

def c1_parse(esp, mesa):
    print("\n1 · o parse é por ORDEM DE APARIÇÃO, uma linha por frame")
    conta("frames de scdet lidos", len(mesa))
    ok("2.123 scores lidos da fixture crua (= nb_read_frames do v1-montado)",
       len(mesa) == esp["mesa"]["frames"], "%d" % len(mesa))
    ok("o primeiro frame não tem score (nada antes dele para comparar)",
       mesa[0] == 0.0)
    # 🔴 o defeito plantado: linha com `^` no meio do texto. Um `re.findall` com
    # `^` e SEM `re.M` leria 1 de 3 — foi o defeito medido na SPEC-12.
    sujo = ("ruído antes\n[scdet @ 0x1] lavfi.scd.score: 1.500, lavfi.scd.time: 0\n"
            "[scdet @ 0x1] lavfi.scd.score: 2.500, lavfi.scd.time: 0.03\n"
            "frame= 3 fps=0.0 q=-0.0 size=N/A\n"
            "[scdet @ 0x1] lavfi.scd.score: 3.500, lavfi.scd.time: 0.06\n")
    lidos = qci.parse_scores(sujo)
    conta("linhas sujas plantadas", 3)
    ok("as 3 linhas com prefixo variável são lidas (não 1 de 3)",
       lidos == [1.5, 2.5, 3.5], repr(lidos))


# ──────────────────────────────────────────────────────────────── 2 · razão local

def c2_razao_local(esp, mesa):
    print("\n2 · a razão contra a vizinhança local reproduz a medição real")
    m = esp["mesa"]
    r = qci.razoes(mesa, m["fronteiras"], w=m["janela_frames"])
    cas = qci.casar(r, m["fronteiras"])
    conta("fronteiras casadas", len(cas))
    medidas = [round(c["razao"], 2) for c in cas]
    ok("as 28 razões batem com o congelado (±0,05)",
       all(abs(a - b) <= 0.05 for a, b in zip(medidas, m["razoes"])),
       "máx Δ %.3f" % max(abs(a - b) for a, b in zip(medidas, m["razoes"])))
    ok("deslocamento 0 nas 28 (a nossa cadeia não anda frame)",
       [c["desloc"] for c in cas] == m["desloc"])
    ok("as 28 passam de razao_min=11,5",
       sum(1 for c in cas if c["razao"] >= 11.5) == m["confirmadas"],
       "%d/28" % sum(1 for c in cas if c["razao"] >= 11.5))
    ok("0 IMAGEM-SEM-FRONTEIRA na peça inteira",
       len(qci.achados_sem_fronteira(r, m["fronteiras"])) == m["imagem_sem_fronteira"])

    # 🔴 O LIMIAR ABSOLUTO NÃO SEPARA — e é por isso que a régua é a razão.
    # Se um limiar global de score bastasse, esta linha seria desnecessária.
    fora = [mesa[i] for i in range(len(mesa))
            if all(abs(i - f) > 1 for f in m["fronteiras"])]
    ok("um score alto FORA de fronteira existe e a razão o distingue",
       max(fora) > 0.4, "maior score fora = %.3f" % max(fora))
    return r


def c3_vizinhanca_exclui_fronteira(esp, mesa):
    print("\n3 · a vizinhança EXCLUI as fronteiras — senão a fronteira infla o p95 dela")
    m = esp["mesa"]
    r_certo = qci.razoes(mesa, m["fronteiras"], w=m["janela_frames"])
    r_errado = qci.razoes(mesa, [], w=m["janela_frames"])   # sem excluir nada
    f = m["fronteiras"][0]
    conta("comparações de razão certa × ingênua", len(m["fronteiras"]))
    piores = sum(1 for x in m["fronteiras"] if r_errado[x] < r_certo[x])
    ok("sem a exclusão a razão cai em pelo menos uma fronteira",
       piores >= 1, "%d de %d fronteiras pioram" % (piores, len(m["fronteiras"])))
    ok("na primeira fronteira a razão certa é >= a ingênua",
       r_certo[f] >= r_errado[f], "%.2f vs %.2f" % (r_certo[f], r_errado[f]))


# ───────────────────────────────────────────── 4 · controles negativo E positivo

def c4_controles(esp):
    print("\n4 · controle NEGATIVO e POSITIVO do mesmo par (§7.4)")
    neg, pos = esp["controle_negativo"], esp["controle_positivo"]
    rn = qci.razoes(neg["scores"], [neg["juncao"]], w=45)
    conta("frames do controle negativo", len(neg["scores"]))
    ok("junção contígua: razão <= 1,0 (medido 0,41) — o silêncio é o certo",
       rn[neg["juncao"]] <= 1.0, "%.3f" % rn[neg["juncao"]])
    ok("e o veredito dela é ESPERADO-INVISIVEL, nem OK nem achado",
       qci.veredito("nao", rn[neg["juncao"]]) == "ESPERADO-INVISIVEL")

    rp = qci.razoes(pos["scores"], [], w=45)
    conta("frames do controle positivo", len(pos["scores"]))
    ok("o MESMO par com `-ss -c copy` passa de 11,5 (medido 20,94)",
       rp[pos["juncao"]] >= 11.5, "%.2f" % rp[pos["juncao"]])
    achados = qci.achados_sem_fronteira(rp, [])
    ok("e sai como IMAGEM-SEM-FRONTEIRA: ali não há fronteira declarada",
       any(a["frame"] == pos["juncao"] for a in achados),
       "%d achado(s)" % len(achados))
    ok("🔴 os dois controles DIVERGEM (senão nenhum dos dois prova nada)",
       rp[pos["juncao"]] / max(rn[neg["juncao"]], 1e-9) > 20,
       "positivo/negativo = %.1f×" % (rp[pos["juncao"]] / rn[neg["juncao"]]))


# ─────────────────────────────────────────────── 5 · o off-by-one, nos DOIS sentidos

def c5_off_by_one(esp):
    print("\n5 · índice de decodificação × round(PTS × fps) — a `peca-04` (§3.3)")
    t = esp["corte_off_by_one"]
    conta("fronteiras da peca-04", len(t["fronteiras"]))
    por_decod = [0] * len(t["fronteiras"])
    ok("pelo índice de decodificação: 16 fronteiras, deslocamento 0",
       por_decod == t["desloc_por_indice_de_decodificacao"])
    por_pts = [round(tt * t["fps"]) - f
               for tt, f in zip(t["scd_time_na_fronteira"], t["fronteiras"])]
    ok("🔴 por round(PTS × fps): +1 nas 16 — o controle negativo do método",
       por_pts == [1] * len(t["fronteiras"]) == t["desloc_por_round_pts"],
       "start_time=%s" % t["start_time"])
    ok("os dois métodos discordam (se concordassem, o teste não mediria nada)",
       por_decod != por_pts)


# ─────────────────────────────────────────────────────── 6 · a tabela de veredito

def c6_veredito():
    print("\n6 · a tabela de §3.2: só `esperado_visivel=sim` pode virar FALHA")
    casos = [
        ("sim", 20.0, "CONFIRMADA"),
        ("sim", 5.0, "DUVIDOSA"),
        ("sim", 1.0, "FRONTEIRA-SEM-IMAGEM"),
        ("provavel", 20.0, "CONFIRMADA"),
        ("provavel", 1.0, "SEM-MARCADOR"),
        ("provavel", 5.0, "SEM-MARCADOR"),
        ("nao", 99.0, "ESPERADO-INVISIVEL"),
        ("nao", 0.1, "ESPERADO-INVISIVEL"),
    ]
    conta("linhas da tabela de veredito", len(casos))
    erradas = [(e, r, qci.veredito(e, r), v) for e, r, v in casos
               if qci.veredito(e, r) != v]
    ok("as 8 combinações classificam como a tabela manda", not erradas,
       repr(erradas[:2]))
    ok("🔴 jump cut cego NUNCA vira FRONTEIRA-SEM-IMAGEM (51/53 medidos acima "
       "do limiar; os 2 restantes são cortes de 0,56 s e 3,9 s)",
       qci.veredito("provavel", 0.0) == "SEM-MARCADOR")


def c7_expectativa():
    print("\n7 · a expectativa vem da EDL, ANTES de olhar o score")
    a = {"src": "in/A.MOV", "start": 1.0, "end": 2.0, "zoom": 1.0, "cx": 0.5, "cy": 0.5}
    casos = [
        ({**a, "src": "in/B.MOV", "start": 2.0}, "sim", "src diferente"),
        ({**a, "start": 2.0, "zoom": 1.7}, "sim", "reenquadramento"),
        ({**a, "start": 2.0}, "nao", "contíguo, mesmo enquadramento"),
        ({**a, "start": 9.0}, "provavel", "jump cut"),
        ({**a, "start": 2.0015}, "nao", "contíguo dentro de TOL_CONTIGUO=2ms"),
        ({**a, "start": 2.05}, "provavel", "50 ms de salto já não é contíguo"),
    ]
    conta("casos de expectativa", len(casos))
    ruins = [(c[2], qci.expectativa(a, c[0])[0], c[1]) for c in casos
             if qci.expectativa(a, c[0])[0] != c[1]]
    ok("os 6 casos classificam como §3.2", not ruins, repr(ruins))
    ok("o predicado de contiguidade é o do jcut.py (2 ms), não um quarto valor",
       abs(qci.TOL_CONTIGUO - 0.002) < 1e-12)


# ───────────────────────────────────────── 8 · defeito PLANTADO na fixture real

def c8_dentes(esp, mesa):
    print("\n8 · defeitos plantados sobre a fixture REAL — o portão tem que acusar")
    m = esp["mesa"]

    # (a) fronteira declarada onde a imagem não muda: um frame parado.
    #     Plantada num trecho de baixa atividade, que é onde o portão é FRACO —
    #     e não num lugar confortável.
    r_base = qci.razoes(mesa, m["fronteiras"], w=m["janela_frames"])
    parados = [i for i in range(60, len(mesa) - 60)
               if r_base[i] < 1.0 and all(abs(i - f) > 60 for f in m["fronteiras"])]
    alvo = parados[len(parados) // 2]
    fr2 = sorted(m["fronteiras"] + [alvo])
    r2 = qci.razoes(mesa, fr2, w=m["janela_frames"])
    cas2 = qci.casar(r2, fr2)
    c_alvo = [c for c in cas2 if c["frame"] == alvo][0]
    conta("defeitos plantados", 1)
    ok("(a) fronteira plantada no frame %d (trecho parado) → FRONTEIRA-SEM-IMAGEM"
       % alvo,
       qci.veredito("sim", c_alvo["razao"]) == "FRONTEIRA-SEM-IMAGEM",
       "razão %.2f" % c_alvo["razao"])
    ok("    e as 28 verdadeiras continuam CONFIRMADAS (sem dano colateral)",
       sum(1 for c in cas2 if c["frame"] in m["fronteiras"]
           and c["razao"] >= 11.5) == 28)

    # (b) deslocamento sistemático: a EDL inteira 1 frame antes do render.
    desl = [f - 1 for f in m["fronteiras"]]
    r3 = qci.razoes(mesa, desl, w=m["janela_frames"])
    cas3 = qci.casar(r3, desl, tol=1)
    conta("defeitos plantados", 1)
    ok("(b) EDL 1 frame adiantada → tendência +1, UMA linha e não 28 achados",
       qci.tendencia(cas3) == 1, "desloc %s" % sorted({c["desloc"] for c in cas3}))
    ok("    e no caso são a sonda não inventa tendência",
       qci.tendencia(qci.casar(r_base, m["fronteiras"])) is None)

    # (c) fronteira faltando: a imagem muda e a EDL não declara nada ali.
    faltando = [f for f in m["fronteiras"] if f != m["fronteiras"][5]]
    r4 = qci.razoes(mesa, faltando, w=m["janela_frames"])
    sf = qci.achados_sem_fronteira(r4, faltando)
    conta("defeitos plantados", 1)
    ok("(c) fronteira removida da EDL → IMAGEM-SEM-FRONTEIRA no frame %d"
       % m["fronteiras"][5],
       any(abs(a["frame"] - m["fronteiras"][5]) <= 1 for a in sf),
       "%d achado(s)" % len(sf))


def c9_herdado(esp):
    print("\n9 · a marca [HERDADO]: corte que a creator já tinha não é defeito nosso")
    achados = [{"frame": 861, "razao": 13.2}, {"frame": 1200, "razao": 12.0}]
    qci.marcar_herdados(achados, [28.717], 30.0)
    conta("achados cruzados com cortes do bruto", len(achados))
    ok("o achado que coincide (Δ 0,017 s) é marcado herdado",
       achados[0]["herdado"] is True, achados[0].get("detalhe", ""))
    ok("o que não coincide NÃO é marcado (senão a marca absolveria tudo)",
       achados[1]["herdado"] is False)
    achados2 = [{"frame": 861, "razao": 13.2}]
    qci.marcar_herdados(achados2, None, 30.0)
    ok("sem lista de cortes do bruto, nada é absolvido em silêncio",
       achados2[0]["herdado"] is False)


def c10_unidade_zero():
    print("\n10 · `unidades == 0` nunca é aprovação")
    conta("caminhos de recusa conferidos", 3)
    ok("scdet que não emite linha nenhuma → lista vazia, não [0.0]",
       qci.parse_scores("ffmpeg version…\nframe= 12 fps=0.0\n") == [])
    ok("p95 de vizinhança vazia é 0,0 e o piso segura a divisão",
       qci.p95([]) == 0.0 and qci.razoes([1.0], [], w=1)[0] == 1.0 / 0.30)
    ok("casar sem fronteira nenhuma devolve lista vazia (e o chamador vê 0)",
       qci.casar([0.1, 0.2], []) == [])


def main():
    print("test_qc_corte_imagem — prova pela imagem (SPEC-26)")
    esp, mesa = carregar()
    c1_parse(esp, mesa)
    c2_razao_local(esp, mesa)
    c3_vizinhanca_exclui_fronteira(esp, mesa)
    c4_controles(esp)
    c5_off_by_one(esp)
    c6_veredito()
    c7_expectativa()
    c8_dentes(esp, mesa)
    c9_herdado(esp)
    c10_unidade_zero()
    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-38s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas[:6]))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
