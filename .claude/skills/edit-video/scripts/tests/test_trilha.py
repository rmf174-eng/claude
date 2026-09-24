#!/usr/bin/env python3
"""Teste da trilha (SPEC-20) — autocontido: gera o próprio material sintético.

    python3 .claude/skills/edit-video/scripts/tests/test_trilha.py [--rapido]

`--rapido` roda só o que é aritmética e texto (sem ffmpeg): derivações de
`ratio`/`threshold`, aritmética do loop, moldagem de prompt e o tratamento da
resposta filtrada da API.

🔴 POR QUE CADA CHECAGEM PLANTA UM DEFEITO
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado, e este repo
já entregou 6,25 s de vídeo errado com todos os QCs verdes. Então aqui cada
mecanismo é testado DUAS vezes: o caso bom, com o número medido, e o defeito que
ele TEM que acusar —

  · `ratio` com o piso de 2,0 de volta            (o 🐛 do duck_db)
  · trilha 22 LU abaixo da voz                    (o defeito histórico de −36,4 LUFS)
  · `sidechaincompress` sem padding               (a cauda descartada, 0,4–0,8 s)
  · resposta da API sem a chave `content`         (o KeyError do filtro de copyright)
  · trilha atenuada em 30 dB                      (o controle negativo do QC)

Nada aqui toca material de creator: a voz é um tom com envelope de fala e a
música são três senoides. Nenhuma rede é chamada.
"""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)

# O `resolver` do perfil.py copia o snapshot para o Remotion. Num teste isso
# sujaria a árvore de trabalho de quem estiver rodando outra coisa; apontar a
# variável para um diretório inexistente faz o copy ser pulado em silêncio.
os.environ["BENCH_REMOTION_DIR"] = os.path.join(tempfile.gettempdir(), "nao-existe-spec20")

import trilha as T                                              # noqa: E402
import perfil as P                                              # noqa: E402


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(SCRIPTS, arquivo))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MG = _carregar("musica_gerar", "musica-gerar.py")

OK, FALHOU, N = [], [], [0]


def check(cond, o_que, detalhe=""):
    N[0] += 1
    (OK if cond else FALHOU).append(o_que)
    print(("  ✅ " if cond else "  ❌ ") + o_que + (("  — " + detalhe) if detalhe else ""))
    return cond


def perto(a, b, tol):
    return a is not None and abs(a - b) <= tol


# ══════════════════════════════════════════════════ 1. derivações (sem ffmpeg)
def teste_ratio():
    print("\n1. ratio — a tabela que reproduz o validado, e o piso que era o 🐛")
    tabela = [(0, 1.00), (5, 1.3333), (10, 2.00), (15, 4.00), (19, 20.00)]
    for duck, esperado in tabela:
        r = T.ratio_de(duck)
        check(perto(r, esperado, 0.01), "ratio(%g) = %.4f" % (duck, r),
              "esperado %.4f" % esperado)
    check(T.ratio_de(RATIO_LIMITE := 100) == 20.0,
          "ratio satura em 20 (o máximo do filtro neste build)")
    # 🐛 o defeito: com piso em 2,0 todo duck ≤ 10 vira o MESMO número
    com_piso = [max(2.0, T.ratio_de(d)) for d in (1, 3, 5, 7, 9)]
    check(len(set(round(x, 4) for x in com_piso)) == 1,
          "com o piso de 2,0 de volta, duck 1..9 colapsam num só valor",
          "é o defeito: %s" % com_piso)
    sem_piso = [round(T.ratio_de(d), 4) for d in (1, 3, 5, 7, 9)]
    check(len(set(sem_piso)) == 5,
          "sem o piso, cada duck dá um ratio diferente", str(sem_piso))


def teste_threshold():
    print("\n2. threshold — função da voz, não literal")
    t = T.threshold_de(-14.2)
    check(perto(t, 0.0195, 0.0005),
          "threshold(−14,2 LUFS) = %.6f" % t,
          "reproduz o 0,02 que rodou na produção")
    check(T.threshold_de(-200) == T.THRESHOLD_MIN,
          "clampa no mínimo do filtro (%.9f)" % T.THRESHOLD_MIN)
    check(T.threshold_de(+40) == T.THRESHOLD_MAX, "clampa no máximo do filtro (1,0)")
    a, b = T.threshold_de(-14.2), T.threshold_de(-24.4)
    check(b < a, "voz mais baixa → threshold mais baixo",
          "−14,2→%.5f  −24,4→%.5f" % (a, b))


def teste_loop():
    print("\n3. aritmética do loop")
    casos = [(30.77, 70.784, 1.5, 3), (176.61, 189.47, 1.5, 2),
             (200.0, 189.47, 1.5, 1), (10.0, 100.0, 1.0, 12)]
    for L, alvo, C, esperado in casos:
        n = T.copias_do_loop(L, alvo, C)
        cobre = n * L - (n - 1) * C
        check(n == esperado and cobre >= alvo,
              "%.2fs → %d cópia(s) para %.2fs (cobre %.2fs)" % (L, n, alvo, cobre))
    try:
        T.copias_do_loop(1.0, 60.0, 1.5)
        check(False, "faixa mais curta que o crossfade tem que ser erro")
    except T.Erro:
        check(True, "faixa mais curta que o crossfade → erro claro")


def teste_energia():
    print("\n4. _energia_somada — dB de RAZÃO não se compara com dB de energia")
    # trilha 30 dB abaixo: a energia acrescentada cai 30 dB, mas o `adicao_db`
    # cai de 0,05 para 0,00005. Comparar ESSES com um limiar de 20 reprovaria
    # um verificador que está funcionando.
    a_lin, b_lin = 0.01, 0.01 / 1000
    a_db = 10 * math.log10(1 + a_lin)
    b_db = 10 * math.log10(1 + b_lin)
    queda_ingenua = a_db - b_db
    queda = 10 * math.log10(T._energia_somada(a_db) / T._energia_somada(b_db))
    check(queda_ingenua < 1.0, "a conta ingênua mede %.4f dB (parece nada)" % queda_ingenua)
    check(perto(queda, 30.0, 0.2), "a conta certa mede %.2f dB (os 30 reais)" % queda)


# ══════════════════════════════════════════════════ 5. o prompt e o filtro
def teste_prompt():
    print("\n5. moldagem do prompt e o filtro de copyright (offline)")
    p = MG.moldar_prompt("warm lo-fi, rhodes, 80 BPM, calm")
    check("original composition" in p.lower(),
          "o prompt afirma composição original", "é o que reduz o filtro")
    check("no vocals" in p.lower() and "risers" in p.lower(),
          "as proibições estão no prompt (voz, riser, whoosh, drone)")
    check("instrumental piece" in p.lower(),
          "enquadra como PEÇA COMPOSTA, não como textura")
    try:
        MG.moldar_prompt("   ")
        check(False, "vibe vazia tem que ser erro")
    except MG.Erro:
        check(True, "vibe vazia → erro que explica o que a vibe precisa nomear")
    v1 = MG._variacoes_para(p, 4)
    v2 = MG._variacoes_para(p, 4)
    check(v1 == v2, "as variações são SEMEADAS pelo prompt (reprodutíveis)")
    check(len(set(v1)) == 4, "e não repetem entre si", "repetir refiltra")
    check(MG._variacoes_para("outro prompt", 4) != v1,
          "prompt diferente → sequência diferente")

    # 🐛 o KeyError da bancada: candidato SEM a chave `content`
    filtrado = {"candidates": [{"finishReason": "OTHER", "index": 0,
                                "finishMessage": "The generated content was filtered "
                                                 "because it may contain material that "
                                                 "resembles existing copyrighted works."}],
                "usageMetadata": {"candidatesTokenCount": 245}}
    try:
        MG._extrair_audio(filtrado)
        check(False, "resposta filtrada tem que virar Filtrado")
    except MG.Filtrado as f:
        check(f.motivo == "OTHER" and "copyrighted" in f.mensagem,
              "finishReason OTHER sem `content` → Filtrado, não KeyError",
              "mensagem preservada inteira")
    except KeyError:
        check(False, "🐛 KeyError — é exatamente o defeito que o §3.3 descreve")

    # a OUTRA forma de filtro, medida hoje: bloqueio na ENTRADA
    bloqueado = {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}
    try:
        MG._extrair_audio(bloqueado)
        check(False, "bloqueio de prompt tem que virar Filtrado")
    except MG.Filtrado as f:
        check(f.motivo == "PROHIBITED_CONTENT",
              "promptFeedback.blockReason → Filtrado", "a segunda forma do filtro")

    bom = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "[[A0]] [[B1]]"},
        {"inlineData": {"mimeType": "audio/mpeg", "data": "QUJD"}}]}}],
        "usageMetadata": {"candidatesTokenCount": 291}}
    audio, texto, toks = MG._extrair_audio(bom)
    check(audio == b"ABC" and texto == "[[A0]] [[B1]]" and toks == 291,
          "resposta boa: áudio + estrutura declarada + tokens")


# ══════════════════════════════════════════════════ 6. ponta a ponta sintético
def _ffmpeg(*a):
    r = subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-y"] + list(a),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("ffmpeg falhou:\n%s" % r.stderr[-1200:])


# Envelope de fala sintético calibrado contra a distribuição REAL de duas peças
# do repo. 1,3 s de fala + 0,7 s de pausa, e a pausa alterna três profundidades
# (0,20 / 0,10 / 0,04) porque a pausa real NÃO é silêncio: é ruído de sala.
#
# 📏 Medido nas peças reais, relativo ao integrado da própria peça:
#   p05 = −13,7 dB (reel) e −12,9 dB (VSL); cauda em −24,1 e −25,7 dB.
# Uma pausa sintética plana em 0,02 fica a −32 dB, muito mais funda que qualquer
# pausa real, e nesse buraco ATÉ UMA TRILHA MORTA parece presente (medido: a
# trilha 22 LU abaixo lia 15,8 dB de presença e o teste não acusava o defeito).
# Com as três profundidades o sintético reproduz o real: boa 8,6 dB × morta 2,52
# dB, contra 8,18 × 2,30 na peça de verdade.
ENV_PAUSA = ("if(gt(mod(t,2.0),1.3), if(lt(mod(t,6.0),2.0),0.20, "
             "if(lt(mod(t,6.0),4.0),0.10,0.04)), 1)")


def _voz(destino, seg, com_pausa):
    """Voz sintética: tom com envelope de fala. Sem `com_pausa` a fala é
    contínua — o regime da VSL, onde este QC é mais fraco e tem que DIZER isso.

    🔴 O DESTINO É `.wav` DE VERDADE, e isso é portabilidade, não estética
    (2026-08-12). Até aqui o arquivo era escrito como `v1-montado.mp4` e
    RENOMEADO para `voz.wav` — ou seja, o `voz.wav` do teste era um contêiner
    MP4 com PCM dentro, tag `ipcm` (medido: `ffprobe` diz
    `format_name=mov,mp4,m4a` e `codec_tag_string=ipcm`). PCM em ISOBMFF é o
    ISO/IEC 23003-5, que o muxer mp4 do FFmpeg só passou a escrever nas versões
    recentes; num build mais antigo o `-c:a pcm_s24le` para `.mp4` morre com
    "Could not find tag for codec pcm_s24le", e o teste inteiro cai antes da
    primeira medição. O RIFF/WAV é muxado por qualquer build desde sempre e
    decodifica para o MESMO PCM — as medições não mudam (conferido: 45/45
    checagens, os mesmos números).
    """
    env = ENV_PAUSA if com_pausa else "1"
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc='0.35*(sin(2*PI*190*t)+0.4*sin(2*PI*380*t))*%s'"
            ":s=48000:c=mono:d=%d" % (env, seg),
            "-c:a", "pcm_s24le", destino)


def _musica(destino, seg):
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc='0.25*sin(2*PI*220*t)+0.18*sin(2*PI*277*t)+0.12*sin(2*PI*330*t)'"
            ":s=44100:c=stereo:d=%d" % seg,
            "-af", "tremolo=f=0.5:d=0.3,volume=6dB", "-c:a", "libmp3lame",
            "-b:a", "192k", destino)


def _producao(raiz, nome, seg, com_pausa, perfil="reels"):
    d = os.path.join(raiz, nome)
    os.makedirs(os.path.join(d, "trilha"), exist_ok=True)
    _voz(os.path.join(d, "voz.wav"), seg, com_pausa)   # RIFF de verdade; ver _voz
    _musica(os.path.join(d, "trilha", "musica.mp3"), max(8, seg // 2))
    P.resolver(d, perfil, sets=["trilha.ativa=true"], quieto=True)
    return d


def _rodar(*argv):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "trilha.py")] + list(argv),
                       capture_output=True, text=True,
                       env=dict(os.environ, BENCH_REMOTION_DIR=os.environ["BENCH_REMOTION_DIR"]))
    return r.returncode, r.stdout, r.stderr


def teste_ponta_a_ponta(raiz):
    print("\n6. ponta a ponta — peça COM pausas")
    d = _producao(raiz, "com-pausa", 36, True)   # 36 s = 6 ciclos de pausa
    voz = os.path.join(d, "voz.wav")
    rc, _, err = _rodar("preparar", d, "--voz", voz)
    check(rc == 0, "preparar sai 0", err.strip().splitlines()[-1] if err else "")
    if rc != 0:
        return
    reg = json.load(open(os.path.join(d, "trilha.json"), encoding="utf-8"))
    check(perto(reg["medido"]["deriva_ms"], 0.0, T.DERIVA_MAX_MS),
          "a trilha bate com a voz em %.3f ms" % reg["medido"]["deriva_ms"],
          "soma_audio == soma_video é invariante")
    alvo = reg["alvo"]["i_lufs"]
    check(perto(reg["medido"]["final_i"], alvo, 0.6),
          "integrado final %.1f LUFS para um alvo de %.1f" % (reg["medido"]["final_i"], alvo))
    check(perto(reg["voz_i_lufs"] - reg["medido"]["final_i"],
                reg["alvo"]["delta_voz_lu"], 0.6),
          "o Δ para a voz é %.1f LU (pedido %.1f)"
          % (reg["voz_i_lufs"] - reg["medido"]["final_i"], reg["alvo"]["delta_voz_lu"]),
          "alvo RELATIVO, não absoluto")

    rc, _, err = _rodar("verificar", d, "--controle-negativo")
    v = json.load(open(os.path.join(d, "trilha.json"), encoding="utf-8"))["verificacao"]
    check(rc == 0, "verificar sai 0 na trilha boa",
          "presença %s dB, mascaramento %s dB" % (v["presenca_db"], v["mascaramento_db"]))
    check(v["janelas_densas"] > 0 and v["janelas_pausa"] >= T.PAUSA_MIN_JANELAS,
          "varreu %d janelas: %d densas, %d de pausa"
          % (v["janelas_total"], v["janelas_densas"], v["janelas_pausa"]),
          "dizer QUANTO varreu é obrigatório")
    check("varri" in err, "o QC imprime quanto varreu")
    check(v["controle_negativo"] == "reprovou (esperado)",
          "🔒 o controle negativo (−30 dB) REPROVA", str(v["controle"]))

    print("\n7. o defeito histórico plantado — trilha 22 LU abaixo (os −36,4 LUFS)")
    rc, _, _ = _rodar("preparar", d, "--voz", voz, "--delta-voz-lu", "22")
    check(rc == 0, "preparar aceita o delta errado (não é ele quem julga)")
    rc, _, err = _rodar("verificar", d)
    v = json.load(open(os.path.join(d, "trilha.json"), encoding="utf-8"))["verificacao"]
    check(rc == 1, "🔒 verificar REPROVA (exit 1) a trilha inaudível",
          "presença %s dB < %s" % (v["presenca_db"], v["limiares"]["presenca_min_db"]))
    check("inaudível" in err, "e diz por quê, com o número")

    print("\n8. o defeito de cauda plantado — sidechaincompress sem padding")
    # ⚠️ O DEFEITO QUE ISTO PLANTA É DE UM BUILD, não da física: a perda de cauda
    # no EOF do `sidechaincompress` foi medida no ffmpeg 8.0.1 (trilha.py:129).
    # Um build que ESVAZIE a cauda direito não reproduz o defeito, e aí um
    # `check(False, "ninguém acusa")` cravado acusaria o guarda de estar quebrado
    # quando quem mudou foi o ffmpeg. Então, quando `preparar` passa, a diferença
    # de duração é MEDIDA: só é falha se sobrou perda e o guarda ficou calado.
    pad = T.PAD_SIDECHAIN_S
    sem_pad = os.path.join(d, "sem-pad.wav")
    try:
        T.PAD_SIDECHAIN_S = 0.0
        try:
            T.preparar(d, {"musica": None, "vibe": None, "voz": voz,
                           "delta_voz_lu": None, "duck_db": None,
                           "out": sem_pad, "controle_negativo": False})
            perda_ms = abs(T.dur_audio(sem_pad)[0] - T.dur_audio(voz)[0]) * 1000.0
            check(perda_ms <= T.DERIVA_MAX_MS,
                  "sem padding este build NÃO descarta cauda (perda %.3f ms) — "
                  "o guarda não tinha o que acusar" % perda_ms,
                  "o defeito de 2026-08-08 é do ffmpeg 8.0.1; aqui não reproduz")
        except T.Erro as e:
            check(e.code == 3 and "cauda" in str(e),
                  "🔒 sem padding, o guarda de duração ACUSA (exit 3)",
                  str(e).splitlines()[0][:110])
    finally:
        T.PAD_SIDECHAIN_S = pad

    print("\n9. peça SEM pausas — o QC tem que dizer que está mais fraco")
    d2 = _producao(raiz, "sem-pausa", 20, False, perfil="vsl")
    voz2 = os.path.join(d2, "voz.wav")
    rc, _, _ = _rodar("preparar", d2, "--voz", voz2)
    check(rc == 0, "preparar sai 0 na peça de fala contínua")
    rc, _, err = _rodar("verificar", d2, "--controle-negativo")
    v = json.load(open(os.path.join(d2, "trilha.json"), encoding="utf-8"))["verificacao"]
    check(v["janelas_pausa"] < T.PAUSA_MIN_JANELAS,
          "a peça tem %d janela(s) de pausa (abaixo do mínimo de %d)"
          % (v["janelas_pausa"], T.PAUSA_MIN_JANELAS))
    check("janela(s) de pausa" in err and "de ouvido" in err,
          "o QC AVISA que a presença virou informação e manda ouvir",
          "verde sem aviso aqui seria mentira")
    check(v["controle"] is not None,
          "o controle negativo ainda roda e é registrado", str(v["controle"]))


# ══════════════════════════════════════════════════════════════════════ main
def main():
    rapido = "--rapido" in sys.argv[1:]
    print("teste da trilha (SPEC-20)%s" % ("  [--rapido]" if rapido else ""))
    teste_ratio()
    teste_threshold()
    teste_loop()
    teste_energia()
    teste_prompt()
    if not rapido:
        raiz = tempfile.mkdtemp(prefix="test-trilha-")
        try:
            teste_ponta_a_ponta(raiz)
        finally:
            shutil.rmtree(raiz, ignore_errors=True)
    else:
        print("\n(--rapido: pulei as checagens com ffmpeg)")
    print("\n%d checagens · %d ok · %d falharam" % (N[0], len(OK), len(FALHOU)))
    for f in FALHOU:
        print("  ✗ %s" % f)
    return 1 if FALHOU else 0


if __name__ == "__main__":
    sys.exit(main())
