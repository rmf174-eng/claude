#!/usr/bin/env python3
"""QC DA CAUDA: o único que procura SILÊNCIO onde não deveria haver.

Uso: qc-cauda.py <dir> [--edl edl.json] [--alvo S] [--floor N|auto] [--controle]
     stdout: nada (é QC)        stderr: tabela + veredito
     0  cauda dentro do alvo
     1  ACUSOU (p90 > 3× alvo) — inclusive no `--controle`, onde acusar é o
        resultado ESPERADO e a linha "CONTROLE OK" o confirma
     2  o `--controle` NÃO acusou: o defeito está no QC, não na peça
     3  medição inválida: piso fixo abaixo do ruído da sala (ver abaixo)

POR QUE ISTO EXISTE
Os cinco QCs desta skill (`audit-emendas`, `qc-fonemas`, `qc-ataque`,
`qc-emendas-asr`, `qc-nivel`) procuram FALA ONDE NÃO DEVERIA HAVER — sílaba
vazada, fonema decepado, palavra inventada. Nenhum procura o contrário. Uma
cauda de 460 ms tem transcript perfeito, emenda limpa, fonema íntegro, deriva de
A/V zero e `qc-fonemas.py` verde — e o vídeo respira errado. Medido na produção
`peca-01`: 1,82 s de ar de café em 8 de 23 segmentos, 2,6 % da duração.

O QUE ELE MEDE
A pergunta INVERTIDA do `cauda.py`: quantas janelas contínuas ABAIXO do piso
existem varrendo PRA TRÁS a partir do `end` de cada segmento. Não é
`silencedetect` a limiar absoluto — o piso de um café real é −44 dB e o gate fixo
lê sala como fala. É o nosso envelope RMS com `piso_local` adaptativo, o mesmo do
`bordas.py`.

📏 ONDE O PISO É AVALIADO, e o que isso custa. O `bordas.py` avalia o piso no
`asr_fim` da janela (o MESMO ponto que o `decay` daquela janela usou). Este QC lê
só a EDL — `janelas.json` pode não existir ao lado — então avalia no `end` do
segmento. Medido na `peca-01`, segmento a segmento: **22 dos 23 dão
exatamente o mesmo número** e 1 difere em **10 ms**, que é UMA janela do
envelope (`nao-adianta`: 460 ms pelo `asr_fim`, 450 pelo `end`). A escolha aqui é
por INDEPENDÊNCIA de entrada, não por sensibilidade.

🦷 A PROVA DE DENTES É OBRIGATÓRIA (`--controle`)
"Nem toda medição limpa é medição": este repo já entregou 6,25 s de vídeo errado
com todos os QCs verdes. O `--controle` PLANTA o defeito no sinal — dopa o
envelope com silêncio digital no fim de cada segmento — e exige que o script
acuse. O TAMANHO plantado sai do limiar do veredito (`tamanho_do_controle`), não
de uma constante: até 2026-08-12 ele era 400 ms fixos e o controle reprovava a si
mesmo quando o limiar era 600 ms (H47-6). O que ele NÃO faz é plantar o defeito no VEREDITO: os pisos são
calculados no envelope ORIGINAL, antes da dopagem, senão o piso desceria junto
com o silêncio plantado e o teste mediria a si mesmo.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bordas                 # noqa: E402
import cauda                  # noqa: E402
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

CONTROLE_S = 0.400   # tamanho MÍNIMO do defeito plantado pelo --controle. É a
#                      maior cauda real já medida no repo (peca-01): o controle
#                      tem que ser um defeito que EXISTE, não um absurdo.
GRITA_X = 3.0        # p90 acima de GRITA_X × alvo = reprovado
CONTROLE_FOLGA = 1.25   # ver `tamanho_do_controle`


def tamanho_do_controle(grita_s):
    """Quanto silêncio o `--controle` planta, dado o limiar que ele tem que furar.

    🔴 O CONTROLE REPROVAVA A SI MESMO (2026-08-12, H47-6/F47-10, relatado por um
    agente externo rodando a v0.12): ele plantava 400 ms fixos em todos os
    segmentos, MEDIA os 17 de 17 corretamente — e saía **2** ("o defeito plantado
    NÃO foi acusado"), porque o veredito exige `p90 > 3× alvo`. Com o alvo de 200
    ms do perfil, o limiar é 600 ms e o defeito de 400 nunca chega lá. O QC estava
    certo, a medição estava certa, e o controle acusava o QC.

    Um controle que planta MENOS que a própria régua exige não é um controle: é
    uma contradição aritmética. O tamanho plantado passa a ser derivado do limiar
    (com 25% de folga), nunca menor que os 400 ms medidos em campo. Continua sendo
    um defeito realista quando o alvo é apertado, e vira um defeito grande quando
    o alvo é largo — que é exatamente o que "plantar acima da régua" significa.
    """
    return max(CONTROLE_S, grita_s * CONTROLE_FOLGA)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    args = sys.argv[2:]
    edl_nome = args[args.index("--edl") + 1] if "--edl" in args else "edl.json"
    controle = "--controle" in args
    P = perfil_mod.carregar(d, quieto=True)
    R = P["ritmo"]
    SR = int(P["audio"]["sr"])
    # 📐 O alvo é RITMO, não constante: perfil primeiro, CLI vence. Sem
    # `cauda_alvo_s` no perfil o alvo é o pad `post` — o ar que a EDL já pretende
    # deixar depois da última palavra.
    if "--alvo" in args:
        alvo, origem = float(args[args.index("--alvo") + 1]), "--alvo"
    elif R.get("cauda_alvo_s") is not None:
        alvo, origem = float(R["cauda_alvo_s"]), "perfil ritmo.cauda_alvo_s"
    else:
        alvo, origem = float(R["pads"]["post"]), "perfil ritmo.pads.post"
    # 🔴 O PISO DEFAULT DESTE QC É `auto`, E DIVERGE DO `bordas.py` DE PROPÓSITO.
    # O `bordas.py` resolve o piso pelo perfil porque ele está TOMANDO A DECISÃO
    # de corte; este script está MEDINDO A SALA, e a EDL não registra com que
    # piso foi cortada. Medido: com o piso fixo do FALLBACK (−52 dB) sobre a
    # `peca-01` (café, ruído real −44 dB) este QC devolve **0 ms em 23 de
    # 23** — verde perfeito sobre 1,82 s de defeito real. `piso_local + 10`
    # acompanha a sala e funciona nos dois extremos. `--floor N` força.
    if "--floor" in args:
        v = args[args.index("--floor") + 1]
        FLOOR = None if v == "auto" else float(v)
    else:
        FLOOR = None
    os.chdir(d)
    segs = edl_io.segmentos(edl_nome)

    cache = {}
    pisos, sala, janelas_varridas = [], [], 0
    for s in segs:
        db = bordas.envelope(s["src"], cache, SR)
        pisos.append(bordas.piso_para(db, s["end"], FLOOR))
        sala.append(bordas.piso_local(db, s["end"]))
    # 🦷 dopagem DEPOIS dos pisos: o defeito plantado não pode mexer na régua.
    controle_s = tamanho_do_controle(alvo * GRITA_X)
    if controle:
        dopado = {k: v.copy() for k, v in cache.items()}
        for s, piso in zip(segs, pisos):
            db = dopado[s["src"]]
            a = max(0, int((s["end"] - controle_s) / bordas.WIN))
            b = min(len(db), int(s["end"] / bordas.WIN))
            db[a:b] = piso - 20.0
        cache = dopado

    caudas = []
    for s, piso in zip(segs, pisos):
        db = cache[s["src"]]
        janelas_varridas += max(0, int(s["end"] / bordas.WIN) - int(s["start"] / bordas.WIN))
        caudas.append(cauda.medir(db, s["start"], s["end"], piso, bordas.WIN))

    med, p90, mx, acima = cauda.resumo(caudas, alvo)
    grita = alvo * GRITA_X
    piores = sorted(range(len(segs)), key=lambda i: -caudas[i])[:5]
    print("varredura: %d segmento(s), %d janela(s) de envelope de %.0f ms, "
          "%d bruto(s)%s"
          % (len(segs), janelas_varridas, bordas.WIN * 1000, len(cache),
             ("  [CONTROLE: %.0f ms de silêncio plantados em cada segmento, "
              "para furar o limiar de %.0f ms]"
              % (controle_s * 1000, alvo * GRITA_X * 1000)) if controle else ""),
          file=sys.stderr)
    sala_med = float(np.median(sala))
    print("alvo %.0f ms (%s) · piso %s · ruído da sala %.0f dB (mediana do "
          "piso_local nos %d pontos de corte)"
          % (alvo * 1000, origem,
             "auto (piso_local + 10 dB)" if FLOOR is None else "%.0f dB fixo" % FLOOR,
             sala_med, len(segs)), file=sys.stderr)
    # 🔴 MEDIÇÃO INVÁLIDA ≠ PEÇA APROVADA. Piso fixo abaixo do ruído da sala faz
    # este script devolver 0 em tudo, que é indistinguível de "não há defeito".
    if FLOOR is not None and FLOOR < sala_med and mx == 0:
        print("🔴 MEDIÇÃO INVÁLIDA: o piso fixo de %.0f dB está ABAIXO do ruído "
              "real da sala (%.0f dB), então NADA é silêncio e a resposta 0 não "
              "significa nada. Rode com `--floor auto`."
              % (FLOOR, sala_med), file=sys.stderr)
        return 3
    print("cauda: mediana %d · p90 %d · máx %d ms · %d/%d acima do alvo · "
          "%d acima de %.0f ms" % (med, p90, mx, acima, len(segs),
                                   sum(1 for c in caudas if c > grita), grita * 1000),
          file=sys.stderr)
    for i in piores:
        if caudas[i] * 1000 <= alvo * 1000:
            break
        print("   ↳ seg%02d %-14s %7.3f-%7.3f  cauda %.0f ms (+%.0f sobre o alvo)"
              % (i, str(segs[i].get("beat"))[:14], segs[i]["start"], segs[i]["end"],
                 caudas[i] * 1000, (caudas[i] - alvo) * 1000), file=sys.stderr)
    excedente = float(np.maximum(np.asarray(caudas) - alvo, 0).sum())
    print("excedente total sobre o alvo: %.2fs em %d segmento(s)"
          % (excedente, acima), file=sys.stderr)

    acusou = p90 > grita * 1000
    if controle:
        # o controle plantou `controle_s` em TODOS: exigir que TODOS apareçam é o
        # que separa "o veredito disparou" de "a medição funciona". Num segmento
        # mais curto que `controle_s` o que se planta é a duração dele — cobrar
        # 400 ms de um segmento de 300 reprovaria o QC por aritmética.
        pegos = sum(1 for c, s in zip(caudas, segs)
                    if c >= min(controle_s, s["end"] - s["start"]) - bordas.WIN)
        if acusou and pegos == len(segs):
            print("CONTROLE OK: acusou %d/%d segmentos com a cauda plantada "
                  "(p90 %d ms > %.0f ms). O QC tem dentes." % (pegos, len(segs), p90, grita * 1000),
                  file=sys.stderr)
            return 1
        print("🔴 CONTROLE FALHOU: o defeito plantado NÃO foi acusado "
              "(%d/%d segmentos, p90 %d ms). O defeito está no QC, não na peça."
              % (pegos, len(segs), p90), file=sys.stderr)
        return 2
    if acusou:
        print("🔴 REPROVADO: p90 %d ms > %.0f ms (%.0f× o alvo). São %.2fs de ar "
              "que o `bordas.py --cauda %.3f` remove sem tocar em fonema."
              % (p90, grita * 1000, GRITA_X, excedente, alvo), file=sys.stderr)
        return 1
    print("ok: p90 %d ms ≤ %.0f ms" % (p90, grita * 1000), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
