#!/usr/bin/env python3
"""Cauda do segmento: quanto AR sobrou no fim do corte, e quanto dele dá pra tirar.

Uso como módulo (é o normal — quem chama é o `bordas.py` e o `qc-cauda.py`):

    import cauda
    disp                  = cauda.medir(db, s, e, piso)
    novo_e, corte, motivo = cauda.aparar(db, src, s, e, piso, alvo, sr=SR,
                                         contiguo_com_proximo=…, ultimo=…, fixo=…)

────────────────────────────────────────────────────────────────────────────
POR QUE ISTO EXISTE — 1,82 s de sala em 8 de 23 segmentos, e nenhum QC via.

Os dois `decay` do `bordas.py` fazem a mesma pergunta: *"qual é a ÚLTIMA janela
acima do limiar, varrendo PRA FRENTE?"* (`bordas.py:decay` e `decay_relativo`).
Num bruto de lugar público, uma xícara ou uma risada 300 ms depois do fim da
frase cruza qualquer limiar, e o `decay` gruda nela. O `--cap` então **não aperta
a cauda: ele só impede a fuga**, e o segmento sai com o teto colado.

Medido na produção `peca-01` (23 janelas, café, `--pre 0.02 --post 0.06
--floor auto --cap 0.15`):

    cauda mediana  60 ms  (= o pad `--post`, correto)
    cauda p90     338 ms
    cauda máxima  460 ms
    8 de 23 segmentos acima de 100 ms
    excedente sobre o alvo de 60 ms: 1,82 s — 2,6 % de um vídeo de 70 s

`--rel` NÃO resolve: com `--rel 10` a EDL encolhe 3,2 s (tira do corpo das
frases) e a cauda p90 continua **338 ms**, idêntica. São dois eixos.

A MEDIÇÃO QUE CORRIGE É A PERGUNTA INVERTIDA: *"quantas janelas contínuas ABAIXO
do piso existem, varrendo PRA TRÁS a partir do `end`?"*. Ela é imune ao estouro
que engana o `decay`, porque para na primeira janela acima do piso — um burst
DEPOIS do `end` está fora do intervalo e não a afeta, e um burst DENTRO dela
encurta a cauda em vez de alongá-la.

────────────────────────────────────────────────────────────────────────────
O QUE ESTE MÓDULO NÃO FAZ, e é decisão (SPEC-09 §3.6)

  • Não apara na montagem. O aparo mexe no `end` da EDL e mais nada — a EDL
    continua sendo a única fonte de verdade do corte, `montar.sh` e
    `audio-exato.py` não mudam uma linha. (É o que reconcilia com a SPEC-07
    §3.8: a objeção dela era contra um SEGUNDO aparo, na montagem, com constante
    de frames.)
  • Não mexe no `decay`. O `decay` decide ONDE A PALAVRA ACABA e é o que protege
    o fonema; a cauda decide QUANTO AR FICA DEPOIS. Fundir os dois faz um número
    mexer no outro e a regressão fica impossível de atribuir.
  • Não conhece formato. O alvo é em SEGUNDOS e vem do perfil de peça
    (`ritmo.cauda_alvo_s`) ou da CLI — o ref-A apara "até 2 frames"
    (`render.py:522`), que é valor de formato e erra de fps em fps.
"""
import importlib.util
import os
import sys

import numpy as np

DIR_SCRIPT = os.path.dirname(os.path.abspath(__file__))
if DIR_SCRIPT not in sys.path:
    sys.path.insert(0, DIR_SCRIPT)

# FÍSICA (não é formato — não sai daqui):
DUR_MIN = 0.10        # nenhum aparo pode deixar um segmento mais curto que isto.
#                       Guarda de sanidade, não de ritmo: abaixo disso o segmento
#                       não sobrevive ao arredondamento pra frame em fps nenhum.
MIN_QUADROS = 3       # blocos de som mais curtos que 3 quadros espectrais são
#                       transiente de decodificação, não fonema.
RAZAO_FRICATIVA = 0.0  # (3–9 kHz) − (150–900 Hz) ≥ 0 dB: a energia ALTA domina.
#                       É a assinatura de /s/ /ʃ/ /f/. Ruído de sala classifica
#                       como `surdo` pelo SURDO_DB do qc-fonemas (−22 dB) e ainda
#                       assim fica MUITO abaixo de 0: medido nas 10 janelas de
#                       aparo da peca-01, a razão mais alta de um bloco que
#                       passou o gate de nível foi −30,5 dB. É este número que
#                       separa fricativa de chiado de café.

_qcf = None


def _qc_fonemas():
    """`qc-fonemas.py` carregado por caminho — o hífen no nome impede `import`.

    ⚠️ IMPORTADO, NUNCA EDITADO. `espectro`, `blocos`, `SURDO_DB` e `GATE_DB`
    são de outra spec; se algo precisar mudar lá, pare e fale."""
    global _qcf
    if _qcf is None:
        spec = importlib.util.spec_from_file_location(
            "qc_fonemas", os.path.join(DIR_SCRIPT, "qc-fonemas.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _qcf = mod
    return _qcf


def medir(db, s, e, piso, win=0.01):
    """Segundos de silêncio CONTÍNUO no fim de [s, e], no envelope RMS já calculado.

    Varre PRA TRÁS a partir de `int(e/win)-1` enquanto `db[k] <= piso`. Para na
    primeira janela acima do piso — logo, nunca "atravessa" fala.

    `win` é a janela do envelope que o CHAMADOR calculou; o default repete a
    física do `bordas.py` (RMS de 10 ms). O `bordas.py` passa o `bordas.WIN` dele
    explicitamente, então não há dois números para divergir.
    """
    k = min(int(e / win) - 1, len(db) - 1)
    lim = int(s / win)
    n = 0
    while k >= lim and db[k] <= piso:
        n += 1
        k -= 1
    return round(n * win, 3)


def _blocos_de_fonema(src, ini, dur, piso_ruido, piso_fala, sr):
    """Blocos dentro de [ini, ini+dur] que são FONEMA, não sala.

    Duas condições, e as duas são medidas — a segunda é a que separa fricativa de
    chiado de café, e sem ela o detector vira ruído (ver o bloco de medição no fim
    deste docstring):

      1. NÍVEL — o bloco tem que estar `GATE_DB` acima do ruído REAL em volta do
         corte (`piso_local`, sem o +10 dB que o piso de decisão do `decay`
         carrega). Se o gate fosse o próprio piso do `decay`, ele estaria SEMPRE
         acima de tudo que existe dentro da janela a remover — por construção,
         já que o `medir()` só devolve janelas ABAIXO daquele piso. G5 nunca
         acusaria nada: portão verde sem dentes.
      2. TIPO — bloco `surdo` só conta com razão alta/baixa ≥ RAZAO_FRICATIVA;
         bloco `vozeado` só conta se o nível dele alcança o critério de FALA do
         próprio `decay` (`piso_fala + GATE_DB`).

    📏 MEDIDO nas 10 janelas de aparo da `peca-01` (860 quadros
    espectrais varridos): **1** bloco passou o gate de nível — classe `vozeado`,
    razão −30,5 dB, RMS −39,5 dB contra um critério de fala de −30,5 dB. Ele foi
    recusado pela condição 2 com 9 dB de folga. Zero falso positivo, e o portão
    varreu de verdade.

    📏 E o que acontece com as alternativas testadas, para ninguém refazer:
    com o piso GLOBAL de sala (percentil 5 do arquivo inteiro, −47,5 dB) o
    detector acusa em **4 dos 10** segmentos — chiado de café classificado como
    `surdo` — e o aparo cai de 1,820 s para 1,046 s, contradizendo o critério 3
    da spec. Com percentil 15 da própria janela, acusa em 1 com +0,4 dB de
    margem, ou seja, dentro do ruído.
    """
    qcf = _qc_fonemas()
    ts, rms, razao = qcf.espectro(src, ini, dur, sr)
    if not len(ts):
        return []
    achados = []
    for classe, a, b in qcf.blocos(rms, razao, ts, piso_ruido):
        if classe == 0:
            continue
        # `blocos()` mede a duração entre CENTROS de quadro: 3 quadros
        # consecutivos abrem (MIN_QUADROS-1) hops.
        if (b - a) < (MIN_QUADROS - 1) * qcf.HOP / sr:
            continue
        dentro = (ts >= a) & (ts <= b)
        r = float(razao[dentro].mean())
        nivel = float(rms[dentro].mean())
        if classe == 1 and r < RAZAO_FRICATIVA:
            continue
        if classe == 2 and nivel < piso_fala + qcf.GATE_DB:
            continue
        achados.append({"classe": classe, "ini": float(a), "fim": float(b),
                        "razao": r, "rms": nivel})
    return achados


def aparar(db, src, s, e, piso, alvo, *, sr, contiguo_com_proximo=False,
           ultimo=False, fixo=False, cauda_final=False, win=0.01):
    """Devolve `(novo_e, corte_s, motivo)`. `corte_s = 0.0` quando uma guarda barrou.

    Cada passo só pode REDUZIR o corte — nenhuma guarda pode aumentá-lo.

        disp   = medir(db, s, e, piso)
        corte  = max(0, disp - alvo)
        G1  contíguo com o próximo  → 0   ("CONTIGUO")
        G2  último segmento         → 0   ("ULTIMO", salvo cauda_final=True)
        G3  end_fixo                → 0   ("END_FIXO")
        G4  corte ≤ (e - s) - DUR_MIN     ("DUR_MIN")
        G5  guarda fonética no trecho a remover  ("FONEMA")

    Por que cada guarda existe:

    G1 🔴 **Não é opcional.** Segmentos contíguos no bruto (`dividir-planos.py`, e
       o caso "duas janelas coladas" do `bordas.py`) existem para TROCAR O
       ENQUADRAMENTO COM O ÁUDIO ATRAVESSANDO. Aparar o fim de um deles abre um
       buraco no meio de uma palavra e desfaz a igualdade `soma_audio ==
       soma_video` que o `audio-exato.py` sustenta. Critério idêntico ao do
       `qc-fonemas.py`: mesmo `src` e `|prox.start − e| < 1e-4`.
    G2 O último segmento é o fim do vídeo, não uma emenda: o ar ali é respiro de
       saída. (O ref-A faz o mesmo, `render.py:593`.)
    G3 `end_fixo` é o operador dizendo "eu medi". Vence tudo, inclusive isto.
    G4 Guarda de sanidade: nenhum aparo transforma segmento em frame solto.
    G5 A rede contra a fricativa — ver `_blocos_de_fonema`.
    """
    disp = medir(db, s, e, piso, win)
    corte = max(0.0, disp - alvo)
    if corte <= 0:
        return round(e, 3), 0.0, "SEM-EXCEDENTE"
    if contiguo_com_proximo:
        return round(e, 3), 0.0, "CONTIGUO"
    if ultimo and not cauda_final:
        return round(e, 3), 0.0, "ULTIMO"
    if fixo:
        return round(e, 3), 0.0, "END_FIXO"
    motivo = "OK"
    teto = (e - s) - DUR_MIN
    if corte > teto:
        corte = max(0.0, teto)
        motivo = "DUR_MIN"
    if corte <= 0:
        return round(e, 3), 0.0, "DUR_MIN"
    # ⚠️ A janela analisada é EXATAMENTE o trecho a remover, sem margem para trás.
    # Incluir 20 ms antes de `e - corte` puxa o corpo da palavra e o detector
    # acusa em 20 de 23 segmentos — falso positivo por construção.
    import bordas   # tardio de propósito: `bordas` importa este módulo no topo
    fonemas = _blocos_de_fonema(src, e - corte, corte,
                                bordas.piso_local(db, e), piso, sr)
    if fonemas:
        novo = max(0.0, e - (fonemas[-1]["fim"] + alvo))
        if novo < corte:
            corte = novo
            motivo = "FONEMA"
        if corte <= 0:
            return round(e, 3), 0.0, "FONEMA"
    return round(e - corte, 3), round(corte, 3), motivo


def resumo(caudas, alvo):
    """(mediana, p90, máx, quantos acima do alvo) em MILISSEGUNDOS inteiros."""
    a = np.asarray(caudas, dtype=float)
    if not len(a):
        return 0, 0, 0, 0
    return (int(round(float(np.median(a)) * 1000)),
            int(round(float(np.percentile(a, 90)) * 1000)),
            int(round(float(a.max()) * 1000)),
            int((a > alvo).sum()))
