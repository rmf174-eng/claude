#!/usr/bin/env python3
"""trilha.py — trilha de fundo com ducking pela voz, e o QC que mede o EFEITO (SPEC-20).

    trilha.py preparar  <dir-producao> [--musica f] [--vibe "…"] [--voz f]
                        [--delta-voz-lu N] [--duck-db N] [--out f]
    trilha.py verificar <dir-producao> [--controle-negativo]

Promoção ao caminho canônico do script que nasceu dentro de uma produção
(`peca-09/trilha.py`, 2026-07-25). A cadeia de 8 passos daquele script
estava certa e está preservada inteira; o que muda é que ela deixou de conhecer
UMA peça. Os três defeitos medidos que vieram junto e foram corrigidos aqui
estão marcados 🐛 abaixo.

A CADEIA, e o motivo de cada passo

    0. mede o INTEGRADO DA VOZ                🆕 nada é suposto
    1. resample + canais do perfil            casar com o programa
    2. loop com crossfade, se a faixa é curta faixa curta vira contínua sem costura
    3. trim na duração exata da VOZ           senão o amix estica ou corta errado
    4. highpass                               tira rumble que só rouba headroom
    5. loudnorm 2 passes até `base_lufs`      🆕 via loudness.py (SPEC-02)
    6. sidechaincompress pela VOZ LIMPA       a música cede quando ele fala
    7. ganho de COMPENSAÇÃO MEDIDO            o passo que o ref-A não tem
    8. fade in/out                            entra e sai sem chamar atenção
    9. sidecar trilha.json + veredito         🆕

🔴 O ERRO QUE ESTE SCRIPT JÁ COMETEU (2026-07-25): normalizar a música e SÓ
   DEPOIS duckar entregou uma trilha 22 LU abaixo da voz — inaudível. Causa:
   naquela peça a fala é contínua (2 pausas ≥0,35 s em 189 s), o ducking atenua
   ~95 % do tempo e come o nível médio inteiro. Corolário: em programa de fala
   contínua, ducking forte = trilha morta. O passo 7 — medir DEPOIS do ducking e
   compensar — é o que não pode sumir numa refatoração. E não tente resolver com
   o `makeup` do `sidechaincompress` (multiplicador cego) nem com um segundo
   `loudnorm` (briga com a dinâmica que o ducking acabou de criar): as duas já
   foram tentadas e reprovadas.

🐛 CORRIGIDO 1 — `duck_db` não fazia nada abaixo de 10. O original tinha
   `ratio = max(2.0, min(20.0, 20/(20−duck)))`. Com `--duck-db 5` a conta dá
   1,333 e o piso promovia para 2,0, DOBRANDO a atenuação — e o stderr anunciava
   "ducking: −5 dB" enquanto aplicava 10. O `ratio` do `sidechaincompress` aceita
   de 1 a 20 neste build (`ffmpeg -h filter=sidechaincompress`), então o piso era
   gratuito. Qualquer `duck_db` ≤ 10 produzia exatamente o mesmo resultado.

🐛 CORRIGIDO 2 — o alvo era absoluto e o nível da voz vinha cravado no fonte
   (o integrado real de UMA peça). Numa peça orgânica o relatório saía errado por
   10 LU. A grandeza que governa trilha é Δ EM RELAÇÃO À VOZ, e a voz é MEDIDA no
   passo 0.

🐛 CORRIGIDO 3 — o original apagava todo `_m*.wav` do diretório corrente,
   assumindo que o cwd era a pasta da produção. Aqui os temporários vivem em
   `<dir-producao>/trilha/_tmp/`, criado e removido pelo script, e nada é apagado
   por glob.

⚠️ A SIDECHAIN É A VOZ LIMPA, nunca o programa com SFX: com o programa, cada
   `pop` de overlay abre um buraco na música.

⚠️ O QC DE ÁUDIO RODA NA VERSÃO SEM TRILHA. Medido: o silêncio digital do end
   card de uma VSL só apareceu na versão sem música. Trilha ESCONDE defeito — ela
   entra depois e não substitui QC nenhum.

⚠️ PRODUTO, NÃO INSTALAÇÃO. Este script conhece dois caminhos: `<dir-producao>`
   (que chega por argumento) e o catálogo de perfis, via `perfil.py`, relativo a
   ele mesmo. Todo número de comportamento vem do bloco `trilha` do perfil de
   peça. Nenhum creator, nenhum caminho absoluto.

exit: 0 ok · 1 QC reprovou · 2 uso inválido / sem alvo · 3 falha de ffmpeg ·
      5 a licença exige crédito e o CREDITO.txt não está lá
"""
import json
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import perfil as _perfil                                        # noqa: E402
import loudness as _loud                                        # noqa: E402

CONTRATO = "benchmark.trilha/v1"

# --------------------------------------------------------------------- FÍSICA
# Nada aqui descreve o formato da peça — isso mora no perfil. O que está aqui
# descreve o INSTRUMENTO: a régua do detector e os limites do filtro.
#
# A janela de 400 ms é a resolução do envelope de fala: sílaba tônica dura
# ~150–250 ms, então 400 ms integra a sílaba sem borrar a pausa curta.
JANELA_S = 0.4
# "densa" = acima do percentil 75 do envelope DE FALA (janelas acima do piso).
PERCENTIL_DENSA = 75
# "pausa" = janela em que a voz cai N dB abaixo do nível integrado da PRÓPRIA
# peça. Piso RELATIVO: um absoluto em dBFS classificaria errado qualquer peça
# gravada mais baixa.
#
# ⚠️ A comparação é em dBFS RMS dos DOIS lados (o integrado do arquivo medido do
# mesmo jeito que a janela). Comparar janela em dBFS RMS com integrado em LUFS
# mistura domínios: o LUFS é K-ponderado (shelf de +4 dB no agudo e passa-alta) e
# a diferença chega a alguns dB em fala.
#
# 🔴 O VALOR É 10, NÃO 25, E ISSO FOI MEDIDO — a §3.7 da spec propunha 25 e com
# 25 este QC NÃO PEGA O DEFEITO QUE ELE EXISTE PARA PEGAR. Plantei o defeito
# histórico (trilha 22 LU abaixo da voz, que reproduz os −36,4 LUFS: a peça de
# VSL saiu medindo −36,3) e medi `presenca` em cada piso, nas duas peças reais:
#
#   piso   VSL(473 jan.)          reels(176 jan.)
#          n    boa    morta      n    boa    morta     limiar 3,0
#   − 8 dB  45  +3,51  +0,64      18  +7,05  +1,79      separa, margem 0,5
#   −10 dB  33  +5,03  +1,07      16  +8,18  +2,30      separa, margem ~2 ✅
#   −12 dB  27  +6,29  +1,49      11 +11,19  +4,04      MORTA PASSA ❌
#   −25 dB   8 +14,61  +6,56       1 +21,84 +13,04      MORTA PASSA ❌ (e n=1)
#
# A 25 dB a população some (1 janela em 176 no reel: veredito de uma janela não é
# veredito) e a trilha morta sobe junto com a boa, porque numa janela quase muda
# QUALQUER coisa parece presente. A 10 dB os dois regimes separam com ~2 dB de
# folga para cada lado, com o MESMO `presenca_min_db = 3,0` que a spec já pedia.
#
# 📏 De onde vinha o 25 da spec: ela colocou o limiar entre "+4,2 dB na pausa
# (aprovada)" e "+0,1 dB (reprovada)" — só que o +0,1 foi medido na FALA DENSA,
# não na pausa. O limiar foi posto com um número do outro eixo.
PISO_PAUSA_DB = 10.0
# Abaixo disto `presenca` é ruído, não medição: vira AVISO e o veredito passa a
# ser só mascaramento. Nas duas peças reais medi 16 e 33 janelas de pausa.
PAUSA_MIN_JANELAS = 3
# O detector do sidechain ouve a voz por um passa-alta e um limitador: rumble e
# plosiva disparam o ducking sem que ninguém tenha falado, e um pico isolado
# fecha a música inteira. Isto é condicionamento do DETECTOR, não da peça.
SIDECHAIN_HP_HZ = 120
SIDECHAIN_LIMIT = 0.9
# 🐛 MEDIDO AQUI, 2026-08-08, ffmpeg 8.0.1: o `sidechaincompress` NÃO ESVAZIA A
# CAUDA no EOF. Ele devolve menos amostras do que recebeu, e a perda varia com o
# material: 0,405 s numa peça real de 70,784 s, 0,805 s num sintético de 2,000 s.
# Não é latência — um impulso posto na amostra 0 sai na amostra 0, medido —, é
# cauda descartada. Nem pré-decodificar a voz para PCM nem `apad` só no lado da
# voz resolvem (medidos: ainda faltaram 0,384 s e 0,533 s).
#
# 🔴 ISTO ESTAVA NO SCRIPT DE ORIGEM e ninguém tinha medido: a trilha daquela
# produção sairia ~1 s mais curta que a voz, emudecendo antes do fim, e o
# `amix=duration=first` do compor.sh não acusa — ele só para de somar.
#
# O conserto: PADDING nos dois lados e trim exato depois. Dois segundos dão ~5×
# de folga sobre a maior perda medida, e o `-t` corta dentro do padding, então
# nenhuma amostra de sinal é perdida. A conferência dura é a do fim do
# `preparar`: a saída tem que bater com a voz em menos de 1 ms.
PAD_SIDECHAIN_S = 2.0
# Limites do `sidechaincompress` neste build (`ffmpeg -h filter=…`): ratio de 1 a
# 20, threshold de 0,000976563 a 1. Vieram do filtro, não de nós.
RATIO_MIN, RATIO_MAX = 1.0, 20.0
THRESHOLD_MIN, THRESHOLD_MAX = 0.000976563, 1.0
# O threshold é escrito como função da voz: `10^((I_voz − REF)/20)`. O REF de 20
# não é número novo — é o que REPRODUZ o valor validado em produção (com a voz a
# −14,2 LUFS a conta devolve o 0,0195 que rodou lá).
THRESHOLD_REF_DB = 20.0
# Um contêiner mp3 reporta duração com erro de até um quadro. Meia folga de
# segundo antes de decidir "não precisa de loop" evita descobrir isso depois do
# trim, com a trilha curta. A conferência dura é a do fim: a saída tem que bater
# com a voz em menos de 1 ms.
FOLGA_LOOP_S = 0.5
DERIVA_MAX_MS = 1.0
# Controle negativo: −30 dB na trilha. A queda TEM que aparecer na medição.
CONTROLE_ATENUACAO_DB = 30.0
QUEDA_MIN_CONTROLE_DB = 20.0

# Ordem de resolução da voz de referência. São nomes de artefato do pipeline
# (contrato), não valores de formato.
VOZES = ("v1-graded.mp4", "v1-sdr.mp4", "v1-montado.mp4")

# Toda chave de comportamento que o perfil TEM que trazer. Não há `.get(k, N)`
# neste script de propósito: um default no fonte é o segundo lugar onde o número
# passa a morar, e o dia em que os dois divergem ninguém descobre.
EXIGIDOS = ("ativa", "engine", "delta_voz_lu", "base_lufs", "base_tp", "base_lra",
            "duck_db", "duck_attack_ms", "duck_release_ms", "highpass_hz",
            "fade_in_s", "fade_out_s", "loop_crossfade_s", "mascara_max_pct",
            "mascara_max_db", "presenca_min_db")

# 🔒 TRILHA_FALLBACK — deliberadamente vazio. O fallback deste script NÃO é
# copiar os números do perfil para cá: é LER o catálogo (`perfis/`), que é o
# mesmo dado. Número de comportamento duplicado no fonte é como as duas verdades
# nascem — foi assim que a doc dizia 0,12/0,20 e o código fazia 0,02/0,06.
TRILHA_FALLBACK = None


class Erro(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


# ------------------------------------------------------------------ processo
def _bin(nome):
    c = shutil.which(nome)
    if not c:
        raise Erro("%s não encontrado no PATH" % nome, 3)
    return c


def sh(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode != 0:
        raise Erro("falhou: %s …\n%s" % (" ".join(a[:4]), r.stderr[-1500:]), 3)
    return r.stdout, r.stderr


def dur_audio(caminho):
    """Duração do STREAM DE ÁUDIO, com o contêiner como segunda opção.

    🔴 Nunca somar `end−start` de EDL para saber duração de saída: é o
    anti-pattern que produziu 4,433 s de erro neste repo. Aqui a duração vem do
    arquivo que existe."""
    out, _ = sh(_bin("ffprobe"), "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration:format=duration",
                "-of", "json", caminho)
    d = json.loads(out or "{}")
    st = (d.get("streams") or [{}])[0]
    for v, fonte in ((st.get("duration"), "stream"),
                     ((d.get("format") or {}).get("duration"), "format")):
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f, fonte
    raise Erro("não consegui a duração do áudio de %s" % caminho, 3)


# ------------------------------------------------------------------- derivações
def ratio_de(duck_db):
    """dB pedidos de atenuação → `ratio` do sidechaincompress.

    Um sinal que passa o threshold em X dB sai comprimido em X/ratio, então para
    ceder `duck` dB no pico da fala o ratio é X/(X−duck), com X = 20 dB acima do
    threshold. SEM PISO EM 2,0 — o piso era o defeito: ele engolia todo pedido
    abaixo de 10 dB e entregava sempre a mesma coisa."""
    return min(RATIO_MAX, max(RATIO_MIN,
                              20.0 / max(0.5, 20.0 - float(duck_db))))


def threshold_de(i_voz_lufs):
    """Integrado da voz → threshold do sidechaincompress, em amplitude linear."""
    return min(THRESHOLD_MAX,
               max(THRESHOLD_MIN,
                   10 ** ((float(i_voz_lufs) - THRESHOLD_REF_DB) / 20.0)))


def copias_do_loop(dur_musica, dur_alvo, crossfade):
    """Quantas cópias encadeadas por `acrossfade` cobrem o alvo.

    N cópias de comprimento L encadeadas duas a duas medem N·L − (N−1)·C, então
    N ≥ (alvo − C)/(L − C). Devolve 1 quando a faixa já cobre o alvo."""
    L, C = float(dur_musica), float(crossfade)
    if L >= dur_alvo + FOLGA_LOOP_S:
        return 1
    if L <= C:
        raise Erro("a faixa (%.2fs) é mais curta que o crossfade (%.2fs) — "
                   "não dá para encadear" % (L, C))
    return max(1, int(math.ceil((float(dur_alvo) + FOLGA_LOOP_S - C) / (L - C))))


# --------------------------------------------------------------------- perfil
def bloco_trilha(dir_producao, quieto=False):
    """O bloco `trilha` do perfil de peça. É a ÚNICA fonte de número."""
    p = _perfil.carregar(dir_producao, quieto=True)
    t = p.get("trilha")
    if not isinstance(t, dict) or len(t) <= 1:
        raise Erro(
            "o perfil desta produção não tem o bloco `trilha` (só %s).\n"
            "  Resolva o perfil antes:\n"
            "    python3 %s resolver %s --perfil <reels|vsl|longform|screencast> "
            "--set trilha.ativa=true"
            % (json.dumps(t, ensure_ascii=False),
               os.path.join(os.path.dirname(os.path.realpath(__file__)), "perfil.py"),
               dir_producao))
    faltando = [k for k in EXIGIDOS if k not in t]
    if faltando:
        raise Erro("bloco `trilha` incompleto — falta %s. Um default inventado no "
                   "script é exatamente o que a SPEC-00 proíbe." % ", ".join(faltando))
    if not t.get("ativa") and not quieto:
        print("⚠️ `trilha.ativa` é false neste perfil. Trilha é decisão editorial "
              "e passa pelo PLANO-EDICAO.md; rodar este comando à mão É a decisão "
              "explícita, mas ela fica registrada no trilha.json.", file=sys.stderr)
    return p, t


def _n(k, t, override=None):
    return float(override) if override is not None else float(t[k])


# ------------------------------------------------------------------ biblioteca
def _registro_da_musica(musica):
    """Acha a faixa no INDEX.json da biblioteca, para saber a licença dela."""
    import importlib.util
    aqui = os.path.dirname(os.path.realpath(__file__))
    spec = importlib.util.spec_from_file_location(
        "musica_gerar", os.path.join(aqui, "musica-gerar.py"))
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    alvo = os.path.realpath(musica)
    tam = os.path.getsize(alvo)
    sha = None
    for r in mg.ler_indice():
        arq = r.get("arquivo") or ""
        p = arq if os.path.isabs(arq) else os.path.join(mg.RAIZ_MUSICA, arq)
        if os.path.exists(p) and os.path.realpath(p) == alvo:
            return r, mg
        # A faixa é COPIADA para `<dir>/trilha/musica.mp3` e perde o nome. Casar
        # por nome erraria exatamente no caso que importa; casamento é por
        # conteúdo, com o tamanho como filtro barato antes do hash.
        if r.get("bytes") not in (None, tam):
            continue
        if sha is None:
            sha = mg.sha256_arquivo(alvo)
        if r.get("sha256") == sha:
            return r, mg
        if r.get("sha256") is None and os.path.exists(p) and \
                os.path.getsize(p) == tam and mg.sha256_arquivo(p) == sha:
            return r, mg
    return None, mg


def _credito(dir_trilha, reg):
    """Escreve o crédito exigido pela licença. Impresso e esquecido não conta.

    Se o registro exige atribuição mas não traz o TEXTO da licença, não há
    crédito verdadeiro para escrever — e escrever "licença: None" seria pior que
    não escrever. Nesse caso a entrega para (exit 5)."""
    if not (reg or {}).get("licenca"):
        raise Erro("a faixa %r exige atribuição e o registro dela não traz o "
                   "texto da licença — não dá para escrever um crédito honesto. "
                   "Complete o INDEX.json da biblioteca antes de entregar."
                   % (reg or {}).get("nome"), 5)
    caminho = os.path.join(dir_trilha, "CREDITO.txt")
    linhas = ["Crédito obrigatório da trilha desta peça.",
              "",
              "faixa:    %s" % reg.get("nome"),
              "provedor: %s" % reg.get("provedor"),
              "autor:    %s" % (reg.get("autor") or "(não declarado)"),
              "licença:  %s" % reg.get("licenca"),
              "",
              "Este texto tem que aparecer na descrição da publicação.",
              ]
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    return caminho


def _conferir_credito(dir_trilha, exige):
    if not exige:
        return None
    caminho = os.path.join(dir_trilha, "CREDITO.txt")
    if not os.path.exists(caminho) or os.path.getsize(caminho) == 0:
        raise Erro("a licença desta faixa EXIGE atribuição e %s não existe (ou "
                   "está vazio). A entrega não sai sem o crédito." % caminho, 5)
    return caminho


# --------------------------------------------------------------------- preparar
def preparar(dir_producao, args):
    if not os.path.isdir(dir_producao):
        raise Erro("não é diretório: %s" % dir_producao)
    p, t = bloco_trilha(dir_producao)
    audio = p.get("audio") or {}
    sr = int(audio.get("sr") or 0)
    canais = int(audio.get("canais") or 0)
    if not sr or not canais:
        raise Erro("o perfil não declara `audio.sr` / `audio.canais`")

    dir_trilha = os.path.join(dir_producao, "trilha")
    tmp = os.path.join(dir_trilha, "_tmp")
    os.makedirs(tmp, exist_ok=True)

    # ---- a voz de referência
    voz = args["voz"]
    if not voz:
        for nome in VOZES:
            c = os.path.join(dir_producao, nome)
            if os.path.exists(c):
                voz = c
                break
        if not voz:
            raise Erro("não achei voz de referência em %s (procurei %s). "
                       "Passe --voz." % (dir_producao, ", ".join(VOZES)))
        print("voz de referência: %s (resolvida por ordem: %s)"
              % (voz, " → ".join(VOZES)), file=sys.stderr)
    else:
        print("voz de referência: %s (explícita)" % voz, file=sys.stderr)
    if not os.path.exists(voz):
        raise Erro("voz não existe: %s" % voz)

    # ---- a música
    musica = args["musica"] or os.path.join(dir_trilha, "musica.mp3")
    if not os.path.exists(musica):
        musica = _gerar_musica(dir_producao, dir_trilha, t, args, voz)

    # ---- passo 0: MEDIR a voz. Nada é suposto.
    alvo_dur, fonte_dur = dur_audio(voz)
    mv = _loud.medir_ebur128(voz)
    i_voz = mv["i"]
    delta = _n("delta_voz_lu", t, args["delta_voz_lu"])
    alvo_i = i_voz - delta
    print("voz: I=%.1f LUFS · %.3fs (%s) · %dch @ %d Hz  →  alvo da trilha "
          "%.1f LUFS (%.1f LU abaixo)"
          % (i_voz, alvo_dur, fonte_dur, mv["canais"], mv["sr"], alvo_i, delta),
          file=sys.stderr)

    dm, _ = dur_audio(musica)
    reg_musica, _mg = _registro_da_musica(musica)
    if reg_musica is None:
        print("⚠️ %s NÃO está na biblioteca (tools/music-library/INDEX.json): a "
              "licença dela não está registrada em lugar nenhum. Registre com "
              "`musica-gerar.py --de <arquivo> --modelo arquivo --licenca \"…\"` "
              "antes de entregar." % musica, file=sys.stderr)

    # ---- 1: formato do programa
    m0 = os.path.join(tmp, "m0.wav")
    sh(_bin("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", musica,
       "-ac", str(canais), "-ar", str(sr), "-c:a", "pcm_s24le", m0)

    # ---- 2: loop com crossfade
    cross = _n("loop_crossfade_s", t)
    n = copias_do_loop(dm, alvo_dur, cross)
    mloop = os.path.join(tmp, "mloop.wav")
    if n > 1:
        print("  loop: %d cópias com crossfade de %.1fs (faixa %.2fs para %.2fs "
              "de peça)" % (n, cross, dm, alvo_dur), file=sys.stderr)
        atual = m0
        for k in range(1, n):
            prox = os.path.join(tmp, "m%d.wav" % k)
            sh(_bin("ffmpeg"), "-nostdin", "-v", "error", "-y",
               "-i", atual, "-i", m0, "-filter_complex",
               "[0][1]acrossfade=d=%.3f:c1=tri:c2=tri[a]" % cross,
               "-map", "[a]", "-c:a", "pcm_s24le", prox)
            if atual != m0:
                os.remove(atual)
            atual = prox
        os.replace(atual, mloop)
    else:
        shutil.copyfile(m0, mloop)
    dl, _ = dur_audio(mloop)
    if dl + 0.001 < alvo_dur:
        raise Erro("o loop devolveu %.3fs para uma peça de %.3fs — a aritmética "
                   "de cópias está errada, e trilha curta é deriva de A/V."
                   % (dl, alvo_dur), 3)

    # ---- 3+4+5: trim exato, highpass e loudnorm de 2 passes (SPEC-02)
    mtrim = os.path.join(tmp, "mtrim.wav")
    sh(_bin("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", mloop,
       "-t", "%.6f" % alvo_dur, "-c:a", "pcm_s24le", mtrim)
    mnorm = os.path.join(tmp, "mnorm.wav")
    _normalizar(mtrim, mnorm, t, os.path.join(dir_trilha, "base.loudness.json"))

    # ---- 6: ducking pela VOZ LIMPA
    duck = _n("duck_db", t, args["duck_db"])
    ratio = ratio_de(duck)
    thr = threshold_de(i_voz)
    atk = float(t["duck_attack_ms"])
    rel = float(t["duck_release_ms"])
    print("  ducking: −%.1f dB na fala · ratio %.2f · threshold %.5f "
          "(derivado de I_voz=%.1f) · attack %gms release %gms"
          % (duck, ratio, thr, i_voz, atk, rel), file=sys.stderr)
    mduck = os.path.join(tmp, "mduck.wav")
    layout = "mono" if canais == 1 else "stereo"
    # ⚠️ `apad=pad_dur=0` NÃO é "sem padding" — o ffmpeg lê 0 como "não definido"
    # e pada para sempre. Zero tem que virar ausência do filtro, senão o teste que
    # planta o defeito da cauda não planta nada e passa em verde.
    pad_mus = "apad=pad_dur=%g," % PAD_SIDECHAIN_S if PAD_SIDECHAIN_S > 0 else ""
    pad_voz = ",apad" if PAD_SIDECHAIN_S > 0 else ""
    sh(_bin("ffmpeg"), "-nostdin", "-v", "error", "-y",
       "-i", mnorm, "-i", voz, "-filter_complex",
       "[0:a]%sanull[mus];"
       "[1:a]aformat=sample_fmts=fltp:sample_rates=%d:channel_layouts=%s,"
       "highpass=f=%d,alimiter=limit=%g%s[voz];"
       "[mus][voz]sidechaincompress=threshold=%.6f:ratio=%.4f:attack=%g:"
       "release=%g:makeup=1:level_sc=1[duck]"
       % (pad_mus, sr, layout, SIDECHAIN_HP_HZ, SIDECHAIN_LIMIT, pad_voz,
          thr, ratio, atk, rel),
       "-map", "[duck]", "-t", "%.6f" % alvo_dur, "-c:a", "pcm_s24le", mduck)
    dd, _ = dur_audio(mduck)
    if abs(dd - alvo_dur) * 1000.0 > DERIVA_MAX_MS:
        raise Erro("o ducking devolveu %.3fs para uma peça de %.3fs. O "
                   "`sidechaincompress` deste build descarta cauda no EOF e o "
                   "padding de %.1fs não bastou — meça a perda e suba "
                   "PAD_SIDECHAIN_S." % (dd, alvo_dur, PAD_SIDECHAIN_S), 3)

    # ---- 7: ganho de COMPENSAÇÃO MEDIDO
    pos = _loud.medir_ebur128(mduck)
    ganho = alvo_i - pos["i"]
    print("  pós-ducking: I=%.1f LUFS → compensa %+.2f dB para o alvo %.1f"
          % (pos["i"], ganho, alvo_i), file=sys.stderr)

    # ---- 8: ganho + fades
    fi = _n("fade_in_s", t)
    fo = _n("fade_out_s", t)
    if fi + fo > alvo_dur:
        print("aviso: fade_in + fade_out (%.1fs) cobrem a peça inteira (%.2fs) — "
              "encurtando proporcionalmente." % (fi + fo, alvo_dur), file=sys.stderr)
        k = alvo_dur / (fi + fo)
        fi, fo = fi * k, fo * k
    saida = args["out"] or os.path.join(dir_producao, "trilha-pronta.wav")
    os.makedirs(os.path.dirname(os.path.abspath(saida)) or ".", exist_ok=True)
    sh(_bin("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", mduck,
       "-af", "volume=%.2fdB,afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f"
       % (ganho, fi, max(0.0, alvo_dur - fo), fo),
       "-t", "%.6f" % alvo_dur, "-c:a", "pcm_s24le", saida)

    fin = _loud.medir_ebur128(saida)
    df, _ = dur_audio(saida)
    deriva_ms = (df - alvo_dur) * 1000.0
    if abs(deriva_ms) > DERIVA_MAX_MS:
        raise Erro("a trilha saiu %+.3f ms fora da voz (limiar %.1f ms). "
                   "`soma_audio == soma_video` é invariante deste pipeline."
                   % (deriva_ms, DERIVA_MAX_MS), 3)
    teto = ((p.get("audio") or {}).get("loudness") or {}).get("TP")
    if teto is not None and fin["tp"] > float(teto):
        print("aviso: a trilha sozinha já está a %+.1f dBTP, acima do teto do "
              "programa (%.1f). O `--teto` do loudness.py resolve DEPOIS do amix; "
              "não re-normalize a trilha (mexe na dinâmica do ducking)."
              % (fin["tp"], float(teto)), file=sys.stderr)

    # ---- 9: licença e sidecar
    exige = bool((reg_musica or {}).get("exige_atribuicao"))
    credito = _credito(dir_trilha, reg_musica) if exige else None
    _conferir_credito(dir_trilha, exige)

    reg = {
        "contrato": CONTRATO,
        "musica": os.path.relpath(musica, dir_producao)
        if musica.startswith(os.path.abspath(dir_producao)) else musica,
        "saida": os.path.relpath(saida, dir_producao)
        if os.path.abspath(saida).startswith(os.path.abspath(dir_producao)) else saida,
        "voz_referencia": os.path.relpath(voz, dir_producao)
        if os.path.abspath(voz).startswith(os.path.abspath(dir_producao)) else voz,
        "voz_i_lufs": i_voz,
        "voz_dur_s": round(alvo_dur, 6),
        "perfil_trilha_ativa": bool(t.get("ativa")),
        "alvo": {"delta_voz_lu": delta, "i_lufs": round(alvo_i, 2)},
        "ducking": {"duck_db": duck, "ratio": round(ratio, 4),
                    "threshold": round(thr, 6), "attack_ms": atk,
                    "release_ms": rel,
                    "derivacao": "threshold = 10^((I_voz−%g)/20); "
                                 "ratio = 20/(20−duck_db), sem piso"
                                 % THRESHOLD_REF_DB},
        "loop": {"copias": n, "crossfade_s": cross, "dur_musica_s": round(dm, 3)},
        "audio": {"sr": sr, "canais": canais, "highpass_hz": t["highpass_hz"]},
        "fades": {"in_s": round(fi, 3), "out_s": round(fo, 3)},
        "medido": {"pos_ducking_i": pos["i"], "compensacao_db": round(ganho, 2),
                   "final_i": fin["i"], "final_tp": fin["tp"],
                   "dur_s": round(df, 3), "deriva_ms": round(deriva_ms, 3)},
        "licenca": {
            "na_biblioteca": reg_musica is not None,
            "faixa": (reg_musica or {}).get("nome"),
            "texto": (reg_musica or {}).get("licenca"),
            "exige_atribuicao": exige,
            "synthid": (reg_musica or {}).get("synthid"),
            "credito": os.path.relpath(credito, dir_producao) if credito else None,
        },
        "verificacao": None,
    }
    _gravar(os.path.join(dir_producao, "trilha.json"), reg)
    shutil.rmtree(tmp, ignore_errors=True)
    print("trilha pronta: I=%.1f LUFS · TP=%+.1f dBFS · %.3fs · %.1f LU abaixo "
          "da voz (faixa da casa: 12–15 LU)"
          % (fin["i"], fin["tp"], df, i_voz - fin["i"]), file=sys.stderr)
    print(os.path.abspath(saida))
    return 0


def _normalizar(entrada, saida, t, json_out):
    """Passo 5 — 2 passes de verdade, pelo loudness.py da SPEC-02.

    Não reimplementar loudnorm aqui é regra: aquele script já decide linear ×
    dinâmico pela previsão de true peak, já confere deriva de duração e já grava
    o sidecar. Duas matemáticas de loudness seriam duas verdades."""
    aqui = os.path.dirname(os.path.realpath(__file__))
    cmd = [sys.executable, os.path.join(aqui, "loudness.py"), entrada,
           "--normalizar", "--out", saida, "--canais", "manter",
           "--alvo-i", str(float(t["base_lufs"])),
           "--alvo-tp", str(float(t["base_tp"])),
           "--alvo-lra", str(float(t["base_lra"])),
           "--pre", "highpass=f=%d" % int(t["highpass_hz"]),
           "--json", json_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write("".join("    | " + l + "\n"
                             for l in r.stderr.strip().splitlines() if l.strip()))
    if r.returncode != 0 or not os.path.exists(saida):
        raise Erro("loudness.py (passo 5) saiu %d — a trilha não foi normalizada"
                   % r.returncode, 3)


def _gerar_musica(dir_producao, dir_trilha, t, args, voz):
    """Sem `--musica` e sem `trilha/musica.mp3`: gera, se o perfil pedir engine."""
    engine = str(t.get("engine") or "")
    vibe = args["vibe"]
    arq_vibe = os.path.join(dir_trilha, "vibe.txt")
    if not vibe and os.path.exists(arq_vibe):
        vibe = open(arq_vibe, encoding="utf-8").read().strip()
    if not engine.startswith("lyria"):
        raise Erro("não achei %s/musica.mp3, e o perfil não pede engine de IA "
                   "(`trilha.engine` = %r). Passe --musica <arquivo>."
                   % (dir_trilha, engine))
    if not vibe:
        raise Erro("para gerar preciso da vibe: --vibe \"gênero + instrumentos + "
                   "BPM + humor\" ou o arquivo %s. A vibe é decisão editorial e "
                   "entra no PLANO-EDICAO.md." % arq_vibe)
    os.makedirs(dir_trilha, exist_ok=True)
    destino = os.path.join(dir_trilha, "musica.mp3")
    alvo_dur, _ = dur_audio(voz)
    aqui = os.path.dirname(os.path.realpath(__file__))
    cmd = [sys.executable, os.path.join(aqui, "musica-gerar.py"),
           "--vibe", vibe, "--dur", "%.2f" % alvo_dur, "--out", destino,
           "--modelo", engine]
    print("gerando música (%s): %s" % (engine, vibe), file=sys.stderr)
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0 or not os.path.exists(destino):
        raise Erro("musica-gerar.py saiu %d" % r.returncode,
                   4 if r.returncode == 4 else 3)
    return destino


# -------------------------------------------------------------------- verificar
def _janelas(voz_pcm, trilha_pcm, sr):
    """Classifica as janelas da VOZ e mede o efeito da trilha em cada classe.

    O alvo em LUFS é o DETECTOR; ele nunca pode ser o teste de convergência. A
    referência independente é o EFEITO medido sobre a voz — foi assim que se
    descobriu que uma trilha "no alvo" somava +0,1 dB na fala densa, ou seja,
    existia só no papel."""
    import numpy as np
    n = min(voz_pcm.size, trilha_pcm.size)
    v, m = voz_pcm[:n], trilha_pcm[:n]
    w = max(1, int(round(JANELA_S * sr)))
    nq = n // w
    if nq < 3:
        raise Erro("material curto demais para o QC: %d janela(s) de %.0f ms"
                   % (nq, JANELA_S * 1000), 3)
    V = v[:nq * w].reshape(nq, w)
    M = m[:nq * w].reshape(nq, w)
    pv = (V ** 2).mean(axis=1)                      # potência da voz por janela
    pvm = ((V + M) ** 2).mean(axis=1)               # potência da soma
    rms_db = 10 * np.log10(np.maximum(pv, 1e-20))
    integrado_db = 10 * math.log10(max(float((v ** 2).mean()), 1e-20))
    piso = integrado_db - PISO_PAUSA_DB
    pausa = rms_db <= piso
    fala = ~pausa
    ref = rms_db[fala] if fala.any() else rms_db
    limiar_densa = float(np.percentile(ref, PERCENTIL_DENSA))
    densa = rms_db >= limiar_densa

    def efeito(mask):
        """dB que a trilha SOMA à voz naquelas janelas. Devolve sem arredondar:
        o controle negativo compara duas medições e o arredondamento para duas
        casas apaga justamente a diferença que ele existe para ver."""
        if not mask.any():
            return None
        a, b = float(pvm[mask].sum()), float(pv[mask].sum())
        if b <= 0:
            return None
        return 10 * math.log10(a / b)

    return {
        "janelas_total": int(nq), "janela_ms": round(JANELA_S * 1000),
        "janelas_densas": int(densa.sum()), "janelas_pausa": int(pausa.sum()),
        "janelas_fala": int(fala.sum()),
        "voz_integrado_dbfs": round(integrado_db, 2),
        "piso_pausa_dbfs": round(piso, 2),
        "limiar_densa_dbfs": round(limiar_densa, 2),
        "mascaramento_db": efeito(densa),
        "presenca_db": efeito(pausa),
        "adicao_total_db": efeito(np.ones(nq, dtype=bool)),
    }


def _r(x, casas=2):
    return None if x is None else round(float(x), casas)


def _energia_somada(adicao_db):
    """`adicao_db` é dB de uma RAZÃO de potência (1 + Pm/Pv). Para comparar duas
    medições é preciso voltar para a energia acrescentada — Pm/Pv — senão a conta
    mistura unidades: atenuar a trilha em 30 dB divide Pm/Pv por 1000, mas move o
    `adicao_db` de 0,05 para 0,00005, ou seja 0,05 dB. Comparar esses 0,05 com um
    limiar de 20 dB reprovaria um verificador que está funcionando."""
    if adicao_db is None:
        return None
    v = 10 ** (adicao_db / 10.0) - 1.0
    return v if v > 0 else None


def verificar(dir_producao, args):
    import numpy as np
    sidecar = os.path.join(dir_producao, "trilha.json")
    if not os.path.exists(sidecar):
        raise Erro("%s não existe — rode `trilha.py preparar %s` antes."
                   % (sidecar, dir_producao))
    reg = json.load(open(sidecar, encoding="utf-8"))
    p, t = bloco_trilha(dir_producao, quieto=True)

    def _abs(x):
        return x if os.path.isabs(x) else os.path.join(dir_producao, x)

    voz, saida = _abs(reg["voz_referencia"]), _abs(reg["saida"])
    for c in (voz, saida):
        if not os.path.exists(c):
            raise Erro("sumiu: %s" % c)
    _conferir_credito(os.path.join(dir_producao, "trilha"),
                      bool((reg.get("licenca") or {}).get("exige_atribuicao")))

    sr = int((reg.get("audio") or {}).get("sr") or (p.get("audio") or {})["sr"])
    vp = _pcm(voz, sr)
    tp_ = _pcm(saida, sr)
    med = _janelas(vp, tp_, sr)
    mx = float(t["mascara_max_db"])
    mn = float(t["presenca_min_db"])

    # 🔒 Prova de dentes: dizer QUANTO se varreu é obrigatório. Um classificador
    # mal calibrado devolve zero janela e imprime verde.
    print("varri %d janelas de %d ms (%.1fs): %d densas (≥%.1f dBFS), %d de pausa "
          "(≤%.1f dBFS), integrado da voz %.1f dBFS"
          % (med["janelas_total"], med["janela_ms"],
             med["janelas_total"] * JANELA_S, med["janelas_densas"],
             med["limiar_densa_dbfs"], med["janelas_pausa"],
             med["piso_pausa_dbfs"], med["voz_integrado_dbfs"]), file=sys.stderr)

    falhas, avisos = [], []
    if med["janelas_densas"] == 0:
        falhas.append("nenhuma janela densa — o classificador não mediu nada")
    if med["mascaramento_db"] is not None and med["mascaramento_db"] > mx:
        falhas.append("a trilha está cobrindo a voz: mascaramento %+.2f dB > %.2f"
                      % (med["mascaramento_db"], mx))
    if med["janelas_pausa"] < PAUSA_MIN_JANELAS:
        avisos.append("só %d janela(s) de pausa (mínimo %d para valer como "
                      "medição): `presenca` vira informação, não veredito, e a "
                      "régua passa a ser mascaramento + integrado. É o regime da "
                      "fala contínua, onde ducking forte mata a trilha — e é "
                      "exatamente onde este QC fica mais fraco. Confira de ouvido."
                      % (med["janelas_pausa"], PAUSA_MIN_JANELAS))
    elif med["presenca_db"] is not None and med["presenca_db"] < mn:
        falhas.append("a trilha é inaudível: presença %+.2f dB < %.2f"
                      % (med["presenca_db"], mn))

    controle = None
    if args["controle_negativo"]:
        # 🔒 A atenuação é feita em memória, não por um `ffmpeg volume=-30dB`:
        # um encoder no meio do caminho faria o portão medir o ENCODER. Multiplicar
        # o vetor por 10^(−30/20) é exato e grátis.
        ctrl = _janelas(vp, tp_ * (10 ** (-CONTROLE_ATENUACAO_DB / 20.0)), sr)
        reprovou = (ctrl["presenca_db"] is not None and ctrl["presenca_db"] < mn)
        ea, eb = _energia_somada(med["adicao_total_db"]), \
            _energia_somada(ctrl["adicao_total_db"])
        queda = 10 * math.log10(ea / eb) if (ea and eb) else None
        cego = []
        if med["janelas_pausa"] >= PAUSA_MIN_JANELAS and not reprovou:
            cego.append("presença do controle (%s) não caiu abaixo de %.2f"
                        % (_r(ctrl["presenca_db"]), mn))
        if queda is not None and queda < QUEDA_MIN_CONTROLE_DB:
            cego.append("a energia acrescentada caiu só %.1f dB com −%.0f dB de "
                        "trilha (esperado ≈%.0f)"
                        % (queda, CONTROLE_ATENUACAO_DB, CONTROLE_ATENUACAO_DB))
        if queda is None and med["janelas_pausa"] < PAUSA_MIN_JANELAS:
            cego.append("sem pausas E sem energia acrescentada mensurável: não há "
                        "evidência nenhuma de que a trilha exista no arquivo")
        controle = {"atenuacao_db": CONTROLE_ATENUACAO_DB,
                    "presenca_db": _r(ctrl["presenca_db"]),
                    "mascaramento_db": _r(ctrl["mascaramento_db"]),
                    "adicao_db": _r(ctrl["adicao_total_db"], 5),
                    "queda_energia_db": _r(queda, 1),
                    "veredito": "reprovou (esperado)" if not cego else "CEGO"}
        print("controle negativo (−%.0f dB): presença %s dB · energia "
              "acrescentada caiu %s dB → %s"
              % (CONTROLE_ATENUACAO_DB, _r(ctrl["presenca_db"]), _r(queda, 1),
                 controle["veredito"]), file=sys.stderr)
        if cego:
            falhas.append("CONTROLE NEGATIVO NÃO REPROVOU — o verificador está "
                          "cego: " + "; ".join(cego))

    med["mascaramento_db"] = _r(med["mascaramento_db"])
    med["presenca_db"] = _r(med["presenca_db"])
    med["adicao_total_db"] = _r(med["adicao_total_db"], 4)
    med["controle_negativo"] = (controle or {}).get("veredito")
    med["controle"] = controle
    med["limiares"] = {"mascara_max_db": mx, "presenca_min_db": mn}
    med["veredito"] = "reprovou" if falhas else ("ok-com-aviso" if avisos else "ok")
    reg["verificacao"] = med
    _gravar(sidecar, reg)

    for a in avisos:
        print("⚠️ %s" % a, file=sys.stderr)
    print("mascaramento %s dB (máx %.2f) · presença %s dB (mín %.2f) → %s"
          % (med["mascaramento_db"], mx, med["presenca_db"], mn, med["veredito"]),
          file=sys.stderr)
    for f in falhas:
        print("REPROVA: %s" % f, file=sys.stderr)
    print(os.path.abspath(sidecar))
    return 1 if falhas else 0


def _pcm(caminho, sr):
    import numpy as np
    r = subprocess.run([_bin("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error",
                        "-i", caminho, "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-c:a", "pcm_f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise Erro("decodificação falhou em %s:\n%s"
                   % (caminho, r.stderr.decode("utf-8", "replace")[-800:]), 3)
    x = np.frombuffer(r.stdout, dtype="<f4").astype("float64")
    if x.size == 0:
        raise Erro("%s decodificou 0 amostra" % caminho, 3)
    return x


def _gravar(caminho, obj):
    tmp = caminho + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, caminho)


# ------------------------------------------------------------------------ CLI
def _parse(argv):
    a = {"cmd": None, "dir": None, "musica": None, "vibe": None, "voz": None,
         "delta_voz_lu": None, "duck_db": None, "out": None,
         "controle_negativo": False}
    val = {"--musica": "musica", "--vibe": "vibe", "--voz": "voz",
           "--delta-voz-lu": "delta_voz_lu", "--duck-db": "duck_db", "--out": "out"}
    i = 0
    while i < len(argv):
        x = argv[i]
        if x in ("-h", "--help"):
            print(__doc__, file=sys.stderr)
            sys.exit(0)
        if x == "--controle-negativo":
            a["controle_negativo"] = True
        elif x in val:
            if i + 1 >= len(argv):
                raise Erro("%s espera um valor" % x)
            v = argv[i + 1]
            if x in ("--delta-voz-lu", "--duck-db"):
                v = float(v)
            a[val[x]] = v
            i += 1
        elif x.startswith("-"):
            raise Erro("opção desconhecida: %s" % x)
        elif a["cmd"] is None:
            a["cmd"] = x
        elif a["dir"] is None:
            a["dir"] = x
        else:
            raise Erro("argumento solto: %r" % x)
        i += 1
    if a["cmd"] not in ("preparar", "verificar"):
        raise Erro("comando tem que ser `preparar` ou `verificar` "
                   "(recebi %r)\n\n%s" % (a["cmd"], __doc__))
    if not a["dir"]:
        raise Erro("falta <dir-producao>\n\n%s" % __doc__)
    return a


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    a = _parse(argv)
    return (preparar if a["cmd"] == "preparar" else verificar)(a["dir"], a)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)
