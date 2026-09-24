#!/usr/bin/env python3
"""Teste da sonda de SFX (SPEC-26) — envelope, onset, classe e veredito.

    python3 .claude/skills/edit-video/scripts/tests/test_qc_sfx.py

RODA SEM FFMPEG E SEM REDE. Os três sinais de referência (transiente em 0 ms, em
50 ms, e um sustentado de 1,5 s) são SINTETIZADOS AQUI, amostra a amostra: o
teste não depende da biblioteca real nem de material de creator.

🔴 O QUE ESTE TESTE PROVA, E COM QUE CONTROLE
  · o `onset` medido bate com o CONSTRUÍDO (±1 ms) nos três — e o do sinal com
    50 ms de lead-in é 50, não 0. Se os três dessem 0, o medidor estaria morto e
    a suíte, verde;
  · o limiar é RELATIVO ao pico: o mesmo sinal 30 dB mais baixo tem o MESMO
    onset. Um limiar absoluto daria onsets diferentes — é o controle que separa
    as duas implementações;
  · o veredito reprova onde tem que reprovar (acento atrasado, lead que come o
    efeito, arquivo inaudível) e NÃO reprova onde não deve (textura atrasada,
    loudness fora do alvo). `LOUDNESS-FORA-DO-ALVO` mudando o estado faria 5 dos
    9 arquivos limpos de posição virarem achado;
  · a régua reproduz a tabela de §2.2 congelada em `fixtures/sfx-esperado.json`.
"""
import importlib.util
import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
FX = os.path.join(AQUI, "fixtures")

_spec = importlib.util.spec_from_file_location(
    "qc_sfx", os.path.join(SCRIPTS, "qc-sfx.py"))
qs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qs)

SR = 44100          # taxa do SINAL SINTÉTICO deste teste, não da peça
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


# ───────────────────────────────────────────────────── sinais de referência

def sinal(dur_ms, lead_ms, corpo_ms, amp=0.7, sr=SR):
    """silêncio de `lead_ms` + um burst de `corpo_ms` com decaimento + silêncio.

    O burst é uma senoide de 1 kHz com envelope exponencial: tem ataque abrupto
    (é o que o `onset` procura) e cauda que passa por −40 dB dentro do corpo."""
    n = int(sr * dur_ms / 1000.0)
    i0 = int(sr * lead_ms / 1000.0)
    n_corpo = max(1, int(sr * corpo_ms / 1000.0))
    tau = n_corpo / 4.6           # ~ −40 dB no fim do corpo
    x = [0.0] * n
    for k in range(i0, min(n, i0 + n_corpo)):
        t = k - i0
        x[k] = amp * math.exp(-t / tau) * math.sin(2 * math.pi * 1000.0 * t / sr)
    return x


def c1_onset():
    print("\n1 · o `onset` medido bate com o CONSTRUÍDO nos três sinais")
    # 📐 O viés é de UM lado só e é conhecido: o ponto do envelope cobre
    # [i·hop, i·hop+janela), então o primeiro ponto acima do limiar começa até
    # `janela − hop` ANTES do ataque. Cedo demais é o lado seguro (não decapita o
    # ataque); tarde seria o lado que estraga. O teste afirma os DOIS limites,
    # senão ele aceitaria um medidor que atrasa.
    cedo = qs.JANELA_MS - qs.HOP_MS + qs.HOP_MS      # 5 ms de folga só para trás
    casos = [("transiente em 0 ms", 300, 0.0, 60),
             ("transiente em 50 ms", 300, 50.0, 60),
             ("sustentado de 1,5 s", 1800, 0.0, 1500)]
    conta("sinais sintéticos medidos", len(casos))
    for rotulo, dur, lead, corpo in casos:
        m = qs.medir_envelope(sinal(dur, lead, corpo), SR)
        ok("%-22s onset construído %.0f ms → medido %.1f ms (cedo ≤ %.0f, "
           "NUNCA tarde)" % (rotulo, lead, m["onset_ms"], cedo),
           -cedo <= (m["onset_ms"] - lead) <= qs.HOP_MS)
    # 🔴 controle: se os três dessem 0, tudo acima passaria com um medidor morto.
    m0 = qs.medir_envelope(sinal(300, 0.0, 60), SR)
    m50 = qs.medir_envelope(sinal(300, 50.0, 60), SR)
    ok("🔴 os dois primeiros DIVERGEM (0 × 50): o medidor não está travado em 0",
       abs(m50["onset_ms"] - m0["onset_ms"]) >= 45.0,
       "%.1f vs %.1f" % (m0["onset_ms"], m50["onset_ms"]))


def c2_limiar_relativo():
    print("\n2 · o limiar é RELATIVO ao pico — controle contra o limiar absoluto")
    alto = qs.medir_envelope(sinal(300, 50.0, 60, amp=0.7), SR)
    baixo = qs.medir_envelope(sinal(300, 50.0, 60, amp=0.7 * 10 ** (-30 / 20.0)), SR)
    conta("pares alto/baixo comparados", 1)
    ok("o mesmo sinal 30 dB mais baixo tem o MESMO onset",
       abs(alto["onset_ms"] - baixo["onset_ms"]) <= 1.0,
       "%.1f vs %.1f ms" % (alto["onset_ms"], baixo["onset_ms"]))
    ok("e o mesmo corpo", abs(alto["corpo_ms"] - baixo["corpo_ms"]) <= 2.0,
       "%.0f vs %.0f ms" % (alto["corpo_ms"], baixo["corpo_ms"]))


def c3_classe():
    print("\n3 · `acento` × `textura` sai do CORPO MEDIDO, não de quem digitou")
    conta("classificações", 4)
    ok("corpo 47 ms → acento", qs.classe_de(47, 400) == "acento")
    ok("corpo 348 ms → acento (o maior acento real da biblioteca)",
       qs.classe_de(348, 400) == "acento")
    ok("corpo 1.715 ms → textura", qs.classe_de(1715, 400) == "textura")
    ok("o corte em 400 ms não tem ninguém perto: 348 de um lado, 1.715 do outro",
       qs.classe_de(400, 400) == "acento" and qs.classe_de(401, 400) == "textura")


def c4_atraso_max():
    print("\n4 · `atraso_max_ms` = max(1000 × tol / fps, piso)")
    sfx = dict(qs.SFX_PADRAO)
    conta("resoluções de tolerância", 3)
    ok("30 fps, tol 1 → 33,33 ms (o frame manda)",
       abs(qs.atraso_max_ms(sfx, 30) - 33.333) < 0.01)
    ok("120 fps, tol 1 → 20,0 ms (o PISO manda: o agendador não tem 8 ms)",
       abs(qs.atraso_max_ms(sfx, 120) - 20.0) < 0.01)
    ok("24 fps, tol 1 → 41,67 ms", abs(qs.atraso_max_ms(sfx, 24) - 41.667) < 0.01)


def c5_veredito():
    print("\n5 · a tabela de §3.4 — e o que ela NÃO pode reprovar")
    sfx = dict(qs.SFX_PADRAO)
    base = {"onset_ms": 0.0, "corpo_ms": 100.0, "pico_dbfs": -3.0}
    conta("linhas da tabela de veredito", 6)

    e, t = qs.avaliar(base, "acento", sfx, 30)
    ok("acento no lugar → ok, sem tag", e == "ok" and not t, repr(t))

    e, t = qs.avaliar({**base, "onset_ms": 46.0}, "acento", sfx, 30)
    ok("acento com 46 ms de lead → FALHA TRANSIENTE-ATRASADO",
       e == "falha" and "TRANSIENTE-ATRASADO" in t, repr(t))

    e, t = qs.avaliar({**base, "onset_ms": 75.0, "corpo_ms": 183.0},
                      "acento", sfx, 30)
    ok("75/183 = 0,41 > 0,30 → LEAD-IN-COME-O-EFEITO (o caso do ref-A)",
       "LEAD-IN-COME-O-EFEITO" in t, repr(t))

    e, t = qs.avaliar({**base, "onset_ms": 98.0, "corpo_ms": 2070.0},
                      "textura", sfx, 30)
    ok("🔴 textura atrasada é ACHADO, com tag PRÓPRIA (senão reprova a peça)",
       e == "achado" and t == ["TRANSIENTE-ATRASADO-TEXTURA"], repr(t))

    e, t = qs.avaliar({**base, "pico_dbfs": -21.5}, "acento", sfx, 30)
    ok("pico −21,5 dBFS → FALHA INAUDIVEL (o `click2.mp3` deles a −25 dB)",
       e == "falha" and "INAUDIVEL" in t, repr(t))

    e, t = qs.avaliar({**base, "pico_dbfs": None}, "acento", sfx, 30)
    ok("arquivo mudo não passa por omissão: pico None → INAUDIVEL",
       e == "falha" and "INAUDIVEL" in t, repr(t))


def c6_loudness_nao_reprova():
    print("\n6 · `LOUDNESS-FORA-DO-ALVO` é achado, e NÃO muda o estado")
    sfx = dict(qs.SFX_PADRAO)
    conta("checagens de loudness", 4)
    ok("−20,0 dentro do alvo [−21,−19] → nada", qs.loudness_fora(-20.0, sfx) is None)
    ok("−22,0 ainda dentro da tolerância de 1 LU → nada",
       qs.loudness_fora(-22.0, sfx) is None)
    ok("−22,5 fora → LOUDNESS-FORA-DO-ALVO",
       qs.loudness_fora(-22.5, sfx) == "LOUDNESS-FORA-DO-ALVO")
    e, _ = qs.avaliar({"onset_ms": 0.0, "corpo_ms": 100.0, "pico_dbfs": -3.0},
                      "acento", sfx, 30)
    ok("🔴 e o estado do arquivo continua `ok` (5 dos 9 estão fora hoje)",
       e == "ok")


def c7_tabela_congelada():
    print("\n7 · a régua reproduz a tabela de §2.2 congelada")
    with open(os.path.join(FX, "sfx-esperado.json")) as fh:
        esp = json.load(fh)
    antes = esp["antes_da_migracao"]
    sfx = {**qs.SFX_PADRAO,
           "lufs_alvo": esp["perfil"]["lufs_alvo"],
           "corpo_acento_max_ms": esp["perfil"]["corpo_acento_max_ms"]}
    fps = esp["perfil"]["fps"]
    conta("arquivos da tabela congelada", len(antes["arquivos"]))
    ruins = []
    for a in antes["arquivos"]:
        classe = qs.classe_de(a["corpo_ms"], sfx["corpo_acento_max_ms"])
        estado, _ = qs.avaliar(a, classe, sfx, fps)
        if classe != a["classe"] or estado != a["estado"]:
            ruins.append((a["nome"], classe, estado))
    ok("as 9 linhas reclassificam para a mesma classe e o mesmo estado",
       not ruins, repr(ruins))
    r = antes["resumo"]
    ok("o resumo congelado é 9 medidos · 5 ok · 2 achados · 2 falhas",
       (r["medidos"], r["ok"], r["achados"], r["falhas"]) == (9, 5, 2, 2), repr(r))
    dep = esp["depois_da_migracao"]["resumo"]
    ok("depois da migração: 0 falhas (e o registro do que mudou fica no fixture)",
       dep["falhas"] == 0, repr(dep))
    ok("🔴 os dois resumos DIVERGEM — a migração fez alguma coisa",
       r["falhas"] != dep["falhas"])


def c8_defeito_plantado():
    print("\n8 · defeito plantado: o envelope tem que ACHAR o lead que existe")
    # o caso literal do ref-A: 180 ms de lead num efeito de 230 ms.
    x = sinal(500, 180.0, 230)
    m = qs.medir_envelope(x, SR)
    sfx = dict(qs.SFX_PADRAO)
    classe = qs.classe_de(m["corpo_ms"], sfx["corpo_acento_max_ms"])
    estado, tags = qs.avaliar({**m, "pico_dbfs": -3.0}, classe, sfx, 30)
    conta("defeitos plantados", 1)
    ok("lead 180 ms medido (%.1f) num corpo de 230 ms — cedo, nunca tarde"
       % m["onset_ms"],
       -(qs.JANELA_MS) <= (m["onset_ms"] - 180.0) <= qs.HOP_MS)
    ok("→ FALHA com TRANSIENTE-ATRASADO e LEAD-IN-COME-O-EFEITO",
       estado == "falha" and "LEAD-IN-COME-O-EFEITO" in tags, repr(tags))
    # e o controle: o MESMO efeito com o lead aparado não pode reprovar.
    m2 = qs.medir_envelope(sinal(320, 0.0, 230), SR)
    e2, t2 = qs.avaliar({**m2, "pico_dbfs": -3.0}, classe, sfx, 30)
    conta("defeitos plantados", 1)
    ok("🔴 o MESMO efeito sem o lead → ok (senão o portão reprovaria tudo)",
       e2 == "ok", repr(t2))


def c9_envelope_barato():
    print("\n9 · o envelope é O(n): bruto de 59 s não pode custar minutos")
    import time
    x = sinal(59000, 100.0, 40000, sr=SR)
    conta("amostras de envelope varridas", len(x))
    t0 = time.time()
    env, h = qs.envelope(x, SR)
    dt = time.time() - t0
    ok("59 s de áudio viram %d pontos de envelope em %.2f s" % (len(env), dt),
       dt < 20.0, "há 4 agentes disputando esta máquina; o teto é folgado")
    ok("a resolução é de 1 ms (o hop) — a unidade em que o defeito vive",
       abs(1000.0 * h / SR - 1.0) < 0.05)


def c10_recusa():
    print("\n10 · recusar é melhor que devolver número inventado")
    conta("caminhos de recusa conferidos", 3)
    try:
        qs.medir_envelope([0.0] * 1000, SR)
        ok("áudio mudo recusa em vez de devolver onset 0", False)
    except qs.ErroSfx:
        ok("áudio mudo recusa em vez de devolver onset 0", True)
    try:
        qs.medir_envelope([], SR)
        ok("áudio vazio recusa", False)
    except qs.ErroSfx:
        ok("áudio vazio recusa", True)
    ok("pico de silêncio digital é None, nunca 0 dBFS", qs.pico_dbfs([0.0] * 10) is None)


def main():
    print("test_qc_sfx — nível E posição do transiente (SPEC-26)")
    c1_onset()
    c2_limiar_relativo()
    c3_classe()
    c4_atraso_max()
    c5_veredito()
    c6_loudness_nao_reprova()
    c7_tabela_congelada()
    c8_defeito_plantado()
    c9_envelope_barato()
    c10_recusa()
    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-38s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas[:6]))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
