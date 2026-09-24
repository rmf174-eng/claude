#!/usr/bin/env python3
"""jcut.py — o PLANO de sobreposição de takes (J-cut), derivado da `edl.json`.

Uso:
    jcut.py <dir> [--fps N] [--lead-max-ms N] [--modo medido|fixo|off]
                  [--perfil <nome>] [--min-frames-plano N]
    jcut.py <dir> --medir            # depois do montar.sh: preenche o bloco `saida`
    jcut.py <dir> --nao-aplicar --motivo "..." [--por <nome>]
                                     # a decisão NEGATIVA, registrada em arquivo
    jcut.py --autoteste              # sem tocar em mídia; com controle negativo

🔴 A DECISÃO É OBRIGATÓRIA; O J-CUT NÃO (achado A15). Antes de 2026-08-10,
"não aplicar" era `rm jcut.json` — e arquivo apagado é indistinguível de
"ninguém pensou no assunto". O `qc-jcut` com `requer: jcut.json` nem rodava:
saía `nao_verificado/insumo`, a mesma cara dos dois casos. Foi assim que 15
emendas butt-join saíram sem ninguém saber que houve escolha. Agora a recusa é
um artefato (`aplicar: false`, com quem, quando e por quê), e a ausência do
arquivo no estágio `montado` REPROVA.

Escreve `<dir>/jcut.json` (`benchmark.jcut/v1`) e imprime o caminho no stdout.

────────────────────────────────────────────────────────────────────────────
O QUE É O J-CUT, NA NOSSA ARQUITETURA

Toda emenda da nossa montagem é butt-join: o segmento que sai termina, o que
entra começa, encostados. Com os pads da EDL em cada ponta, cada emenda entrega
dezenas de ms de ar — 22 emendas descontínuas viram ~1,8 s de respiro. O J-cut
troca isso por sobreposição: a IMAGEM do take que entra aparece `lead` frames
antes, enquanto o SOM do take que sai corre até o fim natural dele.

Para a junção k→k+1, com `lead` amostras:

  • imagem: o take k+1 descarta `lead` frames da própria cabeça — é renderizado
    de `start_{k+1} + lead/fps` até `end_{k+1}`;
  • som:    o take k+1 é lido do bruto a partir de `start_{k+1}` (cabeça INTEIRA)
    e é SOMADO na saída começando `lead` amostras antes de onde a imagem entra.

    n_audio_k = n_video_k + lead_k          (lead_0 = 0 por definição)
    v_off_k   = Σ_{j<k} n_video_j
    a_off_k   = v_off_k − lead_k

Por indução, no instante de saída `v_off_k` (primeiro frame da imagem do take k)
o áudio está exatamente `lead_k` amostras dentro do take k — que é o tempo de
bruto que a imagem mostra. Sincronia por construção, take a take. E o total
fecha sozinho: `a_off_{n−1} + n_audio_{n−1} = Σ n_video_k`. Ou seja,
`soma_audio == soma_video` continua valendo, e ninguém precisa de `-shortest`
nem de `-t` de trava para pinar comprimento de áudio.

────────────────────────────────────────────────────────────────────────────
🔴 O LEAD É MEDIDO POR JUNÇÃO, E O TETO VEM EM MILISSEGUNDOS

O ref-A (`helpers/render.py:521`) usa lead FIXO em 5 frames. Com os nossos pads
— bem menores que os deles — isso empurraria a imagem ~85 ms PARA DENTRO da fala
do take que entra, que é o defeito que o próprio SKILL.md deles alerta. E lead em
FRAMES é o que produziu os 206,7 ms de erro deles numa fonte a 25 fps, quando o
`target_fps` caiu para uma constante no caminho longform (`render.py:1143`).

Aqui: o teto vive em MILISSEGUNDOS, no perfil de peça; `lead_frames` é derivado
com o fps da peça; e o lead de cada junção é o ar que EXISTE ali, medido no
envelope com piso ADAPTATIVO (`bordas.piso_local` + 10 dB), nunca um limiar
absoluto tipo o `silencedetect -33 dB` deles.

    lead_s = min(silêncio_final(k) + silêncio_inicial(k+1), lead_max_ms/1000)
    lead_frames = floor(lead_s × fps)      # floor: nunca come mais ar do que há

Consequência que importa: numa emenda SEM ar, `lead = 0` e nada acontece. O
J-cut só come o que já era respiro — é isso que impede o "entrando no meio da
palavra".

────────────────────────────────────────────────────────────────────────────
🔴 A GUARDA DE CONTIGUIDADE — o que o original não tem

Um segmento partido para reenquadrar (`dividir-planos.py`) ou colado por
`limite_pre`/`limite_pos` no `bordas.py` é CONTÍGUO no bruto: o fim de um é o
início do outro. Sobrepor `lead` amostras ali faria a MESMA fatia de fala tocar
duas vezes, somada consigo mesma (+6 dB e eco de flanger). Na produção
`peca-01` isso aconteceria em 6 das 28 junções.

O `plan_jcut` do ref-A (`render.py:588-611`) sobrepõe toda junção `i > 0` sem
olhar de onde vem cada range — eles não têm o conceito de segmento partido.
Aqui o predicado `contiguo()` é definido UMA vez, neste módulo, e exportado:
`audio-exato.py` e `qc-jcut.py` usam este, não uma cópia.

────────────────────────────────────────────────────────────────────────────
O QUE ESTE SCRIPT NÃO FAZ, DE PROPÓSITO

  • NÃO toca na `edl.json`. Ela é a decisão editorial; o plano de montagem é
    derivado dela e vive noutro arquivo. A uma ferramenta de edição de terceiro reescreve o próprio insumo
    (`render.py:1175-1186`) e teve que consertar a não-idempotência que veio
    junto (`render.py:392-398`). Renderizador que reescreve o insumo é bug.
  • NÃO apara a cauda do take que sai (o `tail trim` deles). A nossa cauda já é
    decidida no `bordas.py` com `decay_relativo` + `cap` + `sair_do_ataque`.
    Somar um aparo cego de N frames aqui brigaria com a decisão que a EDL já
    tomou — e com uma constante em frames, que é valor de formato.
  • NÃO vira crossfade. A sobreposição é soma flat; os micro-fades das pontas
    continuam sendo anti-click de borda, não desvanecimento ao longo do lead.

Mecanismo modelado de uma ferramenta de edição de terceiro, helpers/render.py:499-650 — cópia de leitura em tools/referencias/.
Implementação nossa: posicionamento em numpy sobre a trilha amostra-a-amostra,
lead MEDIDO por junção e guarda de contiguidade, que o original não tem.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

CONTRATO = "benchmark.jcut/v1"
ARQ = "jcut.json"
ARQ_OVERRIDE = "jcut-override.json"
MODOS = ("medido", "fixo", "off")

# ── FÍSICA E PERCEPÇÃO (não é formato: nenhum destes números descreve a peça) ──
# 2 ms: a EDL é gravada com round(...,3) em bordas.py, então "mesmo instante"
# tem 1 ms de granularidade de arquivo. Duas casas de folga.
TOL_CONTIGUO = 0.002
# piso_local (percentil 15 num raio de 0,6 s) + 10 dB é o MESMO critério de
# silêncio que `bordas.piso_para()` usa. Um limiar absoluto lê ruído de café
# como fala — medido na peca-01: piso real de −44 dB contra o −52 fixo.
MARGEM_SILENCIO_DB = 10.0
# "plano curto lê como flash": mesmo limiar (e mesma unidade) do
# `cortes-do-bruto.py --min-frames 8`. Divergir aqui criaria duas verdades sobre
# o mesmo fenômeno; quem quiser outro valor passa --min-frames-plano.
MIN_FRAMES_PLANO = 8
# fração ADIMENSIONAL da duração do take que entra. Não é valor de formato:
# não muda com resolução, fps nem sample rate.
TETO_PROPORCIONAL = 0.25


class ErroJcut(Exception):
    pass


# ─────────────────────────────────────────────────── o predicado, definido UMA vez

def contiguo(a: dict, b: dict) -> bool:
    """`b` começa exatamente onde `a` termina, no mesmo bruto → o áudio atravessa.

    🔴 Esta função é a definição canônica. `qc-ataque.py:77` e `qc-fonemas.py`
    têm o mesmo predicado com tolerâncias diferentes (0,002 e 1e-4) por razões
    históricas; quem for unificá-las importa daqui. Sobrepor uma junção contígua
    duplica áudio: a fatia de fala toca duas vezes, somada consigo mesma."""
    return b.get("src") == a.get("src") and \
        abs(float(b["start"]) - float(a["end"])) < TOL_CONTIGUO


def junções_contiguas(edl) -> list:
    """Índices `k` das junções k→k+1 que são contíguas no bruto."""
    return [k for k in range(len(edl) - 1) if contiguo(edl[k], edl[k + 1])]


def geometria_take(*, start_s, video_offset_frames, video_frames, lead_frames,
                   sr, spf):
    """Geometria inteira de um take, compartilhada por render e medição.

    O J-cut só é exato quando o mesmo `lead_frames` vira o mesmo número
    inteiro de amostras em todos os consumidores. Esta função é a única
    tradução frame → amostra: `audio-exato.py` a usa para montar e
    `qc-jcut.py` / `--medir` a usam para conferir.

    `src_start_samples` arredonda a borda decimal da EDL uma vez. Depois disso
    toda a conta permanece inteira; segundos voltam a existir apenas como campo
    legível no sidecar.
    """
    sr = int(sr)
    spf = int(spf)
    video_offset_frames = int(video_offset_frames)
    video_frames = int(video_frames)
    lead_frames = int(lead_frames)
    if sr <= 0 or spf <= 0:
        raise ErroJcut("sr e samples_por_frame precisam ser positivos")
    if video_offset_frames < 0 or video_frames < 0 or lead_frames < 0:
        raise ErroJcut("offset, duração e lead em frames não podem ser negativos")

    lead_samples = lead_frames * spf
    video_offset_samples = video_offset_frames * spf
    video_samples = video_frames * spf
    src_start_samples = int(round(float(start_s) * sr))
    return {
        "lead_samples": lead_samples,
        "video_offset_samples": video_offset_samples,
        "video_samples": video_samples,
        "audio_offset_samples": video_offset_samples - lead_samples,
        "audio_samples": video_samples + lead_samples,
        "src_start_samples": src_start_samples,
        "src_visual_samples": src_start_samples + lead_samples,
    }


# ────────────────────────────────────────────────────── medição de ar (envelope)

def _bordas():
    """Import tardio: quem só LÊ o plano (audio-exato.py, montar.sh) não paga
    o custo de carregar o resolvedor de bordas."""
    import bordas
    return bordas


def _raio_de(b):
    """O raio de `bordas.piso_local`, LIDO de lá — não copiado.

    Duas cópias do mesmo raio são duas verdades sobre a mesma vizinhança, e a
    que ficar desatualizada não avisa ninguém."""
    import inspect
    return float(inspect.signature(b.piso_local).parameters["raio"].default)


def limiar_silencio(db, t):
    """O nível abaixo do qual, EM VOLTA DE `t`, o áudio é ar. `None` = não dá.

    🔴 DEFEITO MEDIDO NA PRIMEIRA VERSÃO DESTA FUNÇÃO (bruto sintético a 25 fps,
    2026-08-08): usar `piso_local + 10 dB` sozinho mede o RUÍDO da janela, e numa
    janela SEM contraste — fala do começo ao fim — o percentil 15 É o nível da
    fala. O limiar então nasce 10 dB ACIMA da própria fala, tudo passa por
    "silêncio", e o J-cut come 200 ms de fala achando que come ar. No teste, a
    junção 4→5 pediu o teto inteiro num ponto em que o take que sai termina no
    meio de uma vogal.

    A correção é a mesma lição da SPEC-11: medir CONTRASTE, não nível absoluto.
    O limiar tem que ficar abaixo do piso do ruído (`p15 + margem`) E abaixo da
    fala local (`p85 − margem`). Quando a vizinhança não tem os 2×margem de
    contraste que separam as duas coisas, não há ar a achar ali — e a resposta
    certa é 0, não um palpite. O viés é de propósito: o J-cut só pode comer o
    que ele PROVOU que é respiro."""
    import numpy as np
    b = _bordas()
    raio = _raio_de(b)
    lo = max(0, int((t - raio) / b.WIN))
    hi = min(len(db), int((t + raio) / b.WIN))
    if hi <= lo:
        return None
    piso = b.piso_local(db, t)                     # p15 da MESMA janela
    fala = float(np.percentile(db[lo:hi], 85))
    if fala - piso < 2 * MARGEM_SILENCIO_DB:
        return None                                # sem contraste: sem ar
    return min(piso + MARGEM_SILENCIO_DB, fala - MARGEM_SILENCIO_DB)


def silencio_final(db, t_fim, teto_s, WIN) -> float:
    """Segundos de silêncio ANTES de `t_fim` (o ar que a EDL deixou na cauda).

    A busca para no teto porque tudo além dele é descartado pelo `min()` de
    qualquer forma."""
    piso = limiar_silencio(db, t_fim)
    if piso is None:
        return 0.0
    k = max(0, min(len(db), int(round(t_fim / WIN))))
    lim = max(0, k - int(math.ceil(teto_s / WIN)) - 1)
    j = k
    while j > lim and db[j - 1] < piso:
        j -= 1
    return (k - j) * WIN


def silencio_inicial(db, t_ini, teto_s, WIN) -> float:
    """Segundos de silêncio DEPOIS de `t_ini` (o ar que a EDL deixou na cabeça)."""
    piso = limiar_silencio(db, t_ini)
    if piso is None:
        return 0.0
    k = max(0, min(len(db) - 1, int(round(t_ini / WIN))))
    lim = min(len(db), k + int(math.ceil(teto_s / WIN)) + 1)
    j = k
    while j < lim and db[j] < piso:
        j += 1
    return (j - k) * WIN


def medidor_real(edl, sr):
    """Devolve `medir(i) -> (silêncio_final_de_i, silêncio_inicial_de_i)` em s.

    Decodifica cada bruto UMA vez (cache do `bordas.envelope`).

    🔴 O ABORT ABAIXO NASCEU DE UM DEFEITO DESTE ARQUIVO, medido em 2026-08-08:
    os `src` da EDL são relativos à pasta da PRODUÇÃO. Rodando `jcut.py <dir>` de
    fora dela, o ffmpeg não achava o bruto, devolvia stdout vazio, o envelope
    saía com zero janelas, toda medição dava 0 e o plano era gravado com lead 0
    em TODA junção — **saída 0, arquivo escrito, nenhuma linha de erro**. Um
    plano de J-cut que não faz J-cut nenhum é indistinguível de "esta peça não
    tem ar", e é a definição do sucesso silencioso que este repo já pagou caro.
    Agora o `main()` faz `chdir` e envelope curto demais é FATAL."""
    b = _bordas()
    cache = {}

    def medir(i, teto_s):
        seg = edl[i]
        db = b.envelope(seg["src"], cache, sr)
        precisa = int(float(seg["end"]) / b.WIN)
        if len(db) < precisa:
            sys.exit("não dá para medir silêncio no segmento %d: o envelope de %r tem "
                     "%.2fs e a EDL corta até %.3fs.\n"
                     "Ou o arquivo não abriu (os `src` da EDL são relativos à pasta da "
                     "produção — rode a partir dela, ou passe o diretório), ou o bruto "
                     "é mais curto que o corte. Plano com lead 0 em toda junção seria "
                     "indistinguível de 'esta peça não tem ar'."
                     % (i, seg["src"], len(db) * b.WIN, float(seg["end"])))
        sai = silencio_final(db, float(seg["end"]), teto_s, b.WIN)
        ent = silencio_inicial(db, float(seg["start"]), teto_s, b.WIN)
        return sai, ent
    return medir


# ─────────────────────────────────────────────────────────────────── o planejador

def planejar(edl, *, fps, sr, modo, lead_max_ms, medir=None, override=None,
             min_frames_plano=MIN_FRAMES_PLANO, perfil_nome=None, log=None):
    """A EDL → o dicionário do `jcut.json` (sem o bloco `saida`).

    `medir(i, teto_s) -> (silêncio_final_s, silêncio_inicial_s)` é INJETÁVEL de
    propósito: é o que permite o `--autoteste` exercitar todas as guardas sem
    tocar em mídia nenhuma, e com controle negativo.

    ⚠️ `frames_nominais` (abaixo) NÃO é a timeline de saída — é o orçamento do
    take ANTES de o render existir, e é a única coisa disponível neste momento.
    A timeline real é medida depois, por `--medir`, que reconfere as guardas
    contra os frames que de fato saíram. Nunca use este número para achar
    posição na saída: para isso existe `edl_io.fronteiras()`.
    """
    if modo not in MODOS:
        raise ErroJcut("modo %r inválido (tem: %s)" % (modo, ", ".join(MODOS)))
    fps = int(fps)
    sr = int(sr)
    if fps <= 0 or sr % fps:
        raise ErroJcut(perfil_mod.msg_fps(fps, sr))
    spf = sr // fps
    override = override or {}
    lead_max_ms = float(lead_max_ms or 0.0)
    teto_s = lead_max_ms / 1000.0
    n = len(edl)
    log = log if log is not None else (lambda *a: None)

    contiguas = set(junções_contiguas(edl))
    # frames nominais do take que ENTRA — orçamento pré-render (ver docstring)
    fr_nom = [max(1, int(round((float(s["end"]) - float(s["start"])) * fps))) for s in edl]

    segmentos = []
    for i, s in enumerate(edl):
        item = {
            "i": i,
            "src": s.get("src"),
            "start": s.get("start"),
            "end": s.get("end"),
            "contiguo_com_anterior": (i - 1) in contiguas,
            "video_skip_frames": 0,
            "lead_frames_in": 0,
            "lead_ms_in": 0.0,
            "silencio_saida_ms": None,
            "silencio_entrada_ms": None,
            "fade_in_s": None,
            "fade_out_s": None,
            "motivo_lead": "primeiro" if i == 0 else None,
        }
        segmentos.append(item)

    # ── fades: a guarda de contiguidade decide as bordas do plano ──────────────
    # É o fix de EDICAO-CAPACIDADES.md:200-205 (18 dips na VSL) escrito por
    # segmento e auditável. SPEC-00 já resolveu o caso geral com
    # `ritmo.fade_modo: so-descontinuidade` no perfil; aqui o plano torna a
    # decisão EXPLÍCITA por borda, e `fades: "jcut"` diz ao audio-exato.py que
    # é este arquivo que manda. Com `modo: off` o plano devolve `fades:
    # "perfil"` e não muda nada em relação a hoje.
    fades_por = "perfil" if modo == "off" else "jcut"
    if fades_por == "jcut":
        for k in contiguas:
            segmentos[k]["fade_out_s"] = 0.0
            segmentos[k + 1]["fade_in_s"] = 0.0

    if n < 2:
        # 🚧 EDL de 1 segmento: não há junção, não há J-cut.
        log("EDL de %d segmento(s): sem junção, sem J-cut" % n)
        modo_efetivo = "off"
    else:
        modo_efetivo = modo

    somado_ms = 0.0
    for k in range(n - 1):
        ent = segmentos[k + 1]
        motivo, teto_por = None, None
        lead_f = 0

        if modo_efetivo == "off":
            motivo = "off"
        elif k in contiguas:
            # 🔴 a guarda. Sobrepor aqui duplicaria a mesma fatia de bruto.
            motivo = "contiguo"
        elif str(k + 1) in override or (k + 1) in override:
            ov = override.get(str(k + 1), override.get(k + 1))
            lead_ms = float(ov["lead_ms"])
            lead_f = int(math.floor(lead_ms * fps / 1000.0))
            motivo = "override"
            log("junção %d→%d: override lead_ms=%g (%s)"
                % (k, k + 1, lead_ms, ov.get("motivo", "sem motivo declarado")))
        elif modo_efetivo == "fixo":
            lead_f = int(math.floor(lead_max_ms * fps / 1000.0))
            motivo, teto_por = "teto", "lead_max_ms"
        else:
            if medir is None:
                raise ErroJcut("modo `medido` sem medidor de silêncio")
            s_out, _ = medir(k, teto_s)
            _, s_in = medir(k + 1, teto_s)
            segmentos[k]["silencio_saida_ms"] = round(s_out * 1000.0, 1)
            ent["silencio_entrada_ms"] = round(s_in * 1000.0, 1)
            bruto_s = s_out + s_in
            if bruto_s >= teto_s:
                lead_f = int(math.floor(teto_s * fps))
                motivo, teto_por = "teto", "lead_max_ms"
            else:
                lead_f = int(math.floor(bruto_s * fps))
                motivo = "medido"

        # ── guardas de segurança, aplicadas DEPOIS (inclusive sobre o override) ──
        if lead_f > 0:
            teto_prop = int(math.floor(TETO_PROPORCIONAL * fr_nom[k + 1]))
            if lead_f > teto_prop:
                lead_f = teto_prop
                motivo, teto_por = "teto", "proporcional"
            if fr_nom[k + 1] - lead_f < min_frames_plano:
                # o que sobra de imagem lê como flash — melhor não sobrepor
                log("junção %d→%d: cabeça curta (%d frames − %d de lead < %d) → lead 0"
                    % (k, k + 1, fr_nom[k + 1], lead_f, min_frames_plano))
                lead_f, motivo, teto_por = 0, "cabeca-curta", None
        if lead_f < 0:
            lead_f = 0

        ent["video_skip_frames"] = lead_f
        ent["lead_frames_in"] = lead_f
        ent["lead_ms_in"] = round(lead_f * 1000.0 / fps, 3)
        ent["motivo_lead"] = motivo
        if teto_por:
            ent["teto_por"] = teto_por
        somado_ms += ent["lead_ms_in"]

    plano = {
        "schema": CONTRATO,
        "gerado_por": os.path.basename(__file__),
        "edl_fingerprint": edl_io.fingerprint(edl),
        "fps": fps,
        "sr": sr,
        "samples_por_frame": spf,
        "perfil": perfil_nome,
        "modo": modo,
        "lead_max_ms": lead_max_ms,
        "min_frames_plano": min_frames_plano,
        "teto_proporcional": TETO_PROPORCIONAL,
        "fades": fades_por,
        "segmentos": segmentos,
        "saida": None,
    }
    return plano


# ─────────────────────────────────────────────────────────────── leitura/escrita

def caminho(d):
    return os.path.join(d, ARQ) if os.path.isdir(d) else str(d)


def carregar(d, edl=None, *, exigir=False):
    """O plano do `<dir>`, ou None. CONFERE que ele descreve ESTE corte.

    🔴 O `edl_fingerprint` aqui é a mesma defesa que a `timeline_real` da
    SPEC-05 tem: um plano que sobrevive à EDL que ele descrevia manda a imagem
    descartar frames de um corte que não existe mais — e a trilha, montada a
    partir dos frames reais, sincronizaria perfeitamente com o vídeo errado."""
    p = caminho(d)
    if not os.path.exists(p):
        if exigir:
            sys.exit(
                "jcut.json ausente em %s.\n"
                "  A DECISÃO do J-cut é obrigatória, o J-cut não. Duas saídas:\n"
                "    aplicar:     jcut.py %s\n"
                "    não aplicar: jcut.py %s --nao-aplicar --motivo \"...\"\n"
                "  Sem o arquivo, 'decidiu não' e 'não pensou no assunto' são o "
                "mesmo estado no disco — foi assim que 15 emendas butt-join saíram "
                "sem ninguém saber que houve escolha (achado A15)."
                % (os.path.abspath(p), d, d))
        return None
    with open(p) as fh:
        plano = json.load(fh)
    if plano.get("schema") != CONTRATO:
        sys.exit("%s: schema %r, esperado %r" % (p, plano.get("schema"), CONTRATO))
    if edl is None:
        edl = edl_io.segmentos(d)
    if len(plano.get("segmentos", [])) != len(edl):
        sys.exit("%s descreve %d segmento(s) e a EDL tem %d — rode `jcut.py %s` de novo."
                 % (p, len(plano.get("segmentos", [])), len(edl), d))
    atual = edl_io.fingerprint(edl)
    if plano.get("edl_fingerprint") != atual:
        sys.exit("A EDL MUDOU DEPOIS DO PLANO DE J-CUT — rode `jcut.py %s` de novo.\n"
                 "  edl_fingerprint gravado em %s: %s\n"
                 "  edl_fingerprint dos segmentos de agora: %s\n"
                 "Usar este plano mandaria a imagem descartar frames de um corte que "
                 "não existe mais." % (d, os.path.basename(p),
                                       plano.get("edl_fingerprint"), atual))
    return plano


def skips(plano, n=None):
    """`video_skip_frames` por índice — a lista que o montar.sh consome."""
    if plano is None or plano.get("aplicar") is False:
        return [0] * (n or len(plano.get("segmentos", []) if plano else []))
    return [int(s.get("video_skip_frames", 0)) for s in plano["segmentos"]]


def gravar_nao_aplicar(d, edl, *, decidido_por, motivo):
    """`jcut.json` com `aplicar: false` — a decisão NEGATIVA, registrada.

    🔴 ACHADO A15. A decisão do J-cut era obrigatória e INVISÍVEL: aplicar =
    manter o arquivo, não aplicar = `rm jcut.json`. Só que "arquivo apagado" e
    "nunca rodou" são o mesmo estado no disco, e o `qc-jcut` com
    `requer: jcut.json` nem chegava a rodar — saía `nao_verificado/insumo`,
    que é a mesma cara de uma produção onde ninguém pensou no assunto. Foi
    assim que 15 emendas butt-join saíram sem ninguém saber que houve escolha.

    A regra antiga ("a escolha vai escrita no PLANO") era impossível de cumprir
    depois da aprovação: o `.md` está preso por `plano_sha256`, e escrever nele
    invalidaria a aprovação (exit 2 do `qc-portao.py`). A decisão mora aqui.

    O `edl_fingerprint` vai junto: uma decisão de "não aplicar" tomada sobre
    OUTRO corte não vale para este."""
    plano = {
        "schema": CONTRATO,
        "aplicar": False,
        "decidido_por": decidido_por,
        "motivo": motivo,
        "decidido_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "edl_fingerprint": edl_io.fingerprint(edl),
        "segmentos": [{"i": i, "src": s.get("src"), "start": s.get("start"),
                       "end": s.get("end"), "video_skip_frames": 0,
                       "lead_frames_in": 0, "lead_ms_in": 0.0}
                      for i, s in enumerate(edl)],
    }
    return gravar(d, plano)


def gravar(d, plano):
    p = caminho(d)
    with open(p, "w") as fh:
        json.dump(plano, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return os.path.abspath(p)


def override_de(d):
    """`jcut-override.json` opcional: {"12": {"lead_ms": 0, "motivo": "..."}}.

    Vive FORA da edl.json de propósito: hoje o `bordas.py` reescreve a EDL a
    cada resolução de bordas, e um campo de plano escrito lá seria perdido na
    próxima passada."""
    p = os.path.join(d, ARQ_OVERRIDE)
    if not os.path.exists(p):
        return {}
    with open(p) as fh:
        ov = json.load(fh)
    for chave, v in ov.items():
        if not isinstance(v, dict) or "lead_ms" not in v:
            sys.exit("%s: a entrada %r precisa de {\"lead_ms\": N, \"motivo\": \"…\"}"
                     % (p, chave))
    return ov


# ───────────────────────────────────────────────────────── configuração efetiva

def config(d, args, quieto=False):
    """(fps, sr, modo, lead_max_ms, perfil_nome) — perfil de peça, flags vencem.

    🔴 NENHUM valor de formato tem default neste arquivo. Sem bloco `jcut` no
    perfil e sem flag, o modo efetivo é `off` — e isso é DITO no stderr, não
    inferido em silêncio. Ligar J-cut com um teto inventado pelo código seria
    exatamente o "sucesso silencioso" que este repo já pagou caro."""
    nome_perfil = _flag(args, "--perfil")
    if nome_perfil:
        arq = os.path.join(perfil_mod.DIR_PERFIS, nome_perfil + ".json")
        if not os.path.isfile(arq):
            sys.exit("perfil %r não existe em %s" % (nome_perfil, perfil_mod.DIR_PERFIS))
        with open(arq) as fh:
            P = perfil_mod.sobre_base(json.load(fh))
    else:
        P = perfil_mod.carregar(d, quieto=quieto)
    fps = int(_flag(args, "--fps") or P["video"]["fps"])
    sr = int(P["audio"]["sr"])
    bloco = P.get("jcut") or {}
    modo = _flag(args, "--modo") or bloco.get("modo")
    lead_max = _flag(args, "--lead-max-ms")
    lead_max = float(lead_max) if lead_max is not None else bloco.get("lead_max_ms")
    if modo is None and lead_max is None:
        if not quieto:
            print("aviso: o perfil %r não declara o bloco `jcut` e nenhuma flag foi "
                  "passada — J-CUT DESLIGADO (modo `off`, plano com lead 0 em toda "
                  "junção; a montagem sai igual à de hoje).\n"
                  "  Para ligar:  jcut.py <dir> --modo medido --lead-max-ms N\n"
                  "  Para fixar no perfil: inscreva {\"jcut\": {\"modo\": \"medido\", "
                  "\"lead_max_ms\": N}} — o teto vive em MILISSEGUNDOS, nunca em frames."
                  % P.get("nome", "?"), file=sys.stderr)
        modo, lead_max = "off", 0.0
    if modo is None:
        modo = "medido"
    if lead_max is None:
        if modo == "off":
            lead_max = 0.0
        else:
            sys.exit("modo %r sem teto: passe --lead-max-ms N ou declare "
                     "`jcut.lead_max_ms` no perfil. O teto NÃO tem default no "
                     "código — é valor de formato." % modo)
    return fps, sr, modo, float(lead_max), P.get("nome")


def _flag(args, nome, default=None):
    return args[args.index(nome) + 1] if nome in args else default


# ─────────────────────────────────────────────────────────────────────── --medir

def medir_saida(d, plano):
    """Depois do montar.sh: preenche `saida` a partir dos frames REAIS.

    🔴 As posições saem da `timeline_real` (SPEC-05), medida dos `segs/` que
    existem — nunca de `Σ(end−start)`. É o anti-pattern que produziu 4,433 s de
    erro no render do ref-A e 353 ms no nosso `peca-03`."""
    tl = edl_io.timeline(d, exigir=False) or edl_io.medir_timeline(d)
    spf = plano["samples_por_frame"]
    sr = plano["sr"]
    fps = plano["fps"]
    if abs(tl["video"]["fps"] - fps) > 1e-9:
        sys.exit("o plano diz %g fps e os segs/ estão a %g — apague segs/ e remonte"
                 % (fps, tl["video"]["fps"]))
    saida, avisos = [], []
    for s, pl in zip(tl["segments"], plano["segmentos"]):
        lead = int(pl["lead_frames_in"])
        nf = int(s["frames"])
        v_off = int(s["start_frame"])
        geo = geometria_take(start_s=pl["start"], video_offset_frames=v_off,
                             video_frames=nf, lead_frames=lead, sr=sr, spf=spf)
        saida.append({
            "i": s["i"],
            "video_offset_frames": v_off,
            "video_frames": nf,
            "audio_offset_samples": geo["audio_offset_samples"],
            "audio_samples": geo["audio_samples"],
            "src_offset_samples": geo["src_visual_samples"],
            "src_offset_s": round(geo["src_visual_samples"] / sr, 6),
        })
        # reconferência das guardas contra os frames que de fato saíram — o
        # planejador só tinha o orçamento nominal (ver planejar()).
        if lead > 0:
            if nf < plano["min_frames_plano"]:
                avisos.append("seg%d: sobraram %d frames de imagem (< %d): o plano lê "
                              "como flash" % (s["i"], nf, plano["min_frames_plano"]))
            if lead > TETO_PROPORCIONAL * (nf + lead):
                avisos.append("seg%d: lead %d de %d frames = %.0f%% do take (> %.0f%%)"
                              % (s["i"], lead, nf + lead,
                                 100.0 * lead / (nf + lead), 100 * TETO_PROPORCIONAL))
    plano["saida"] = saida
    plano["saida_conferida_em"] = tl["gerado_em"]
    for a in avisos:
        print("  ⚠️ " + a, file=sys.stderr)
    return plano, avisos


# ──────────────────────────────────────────────────────────────────── --autoteste

def _edl_sintetica():
    """5 segmentos → 4 junções: 2 contíguas e 2 não.

    junção 0→1: contígua        (mesmo src, 8.0 == 8.0)
    junção 1→2: descontínua     (mesmo src, salto de 4 s)
    junção 2→3: contígua        (mesmo src, 20.0 == 20.0)
    junção 3→4: descontínua     (TROCA de src no MESMO instante, 26.0 == 26.0)

    A última é o controle de que o predicado olha `src`, e não só o tempo: um
    `abs(b.start − a.end) < tol` sozinho a classificaria como contígua e o
    plano sobreporia dois brutos diferentes.
    """
    return [
        {"src": "a.mov", "start": 2.0, "end": 8.0, "beat": "s0", "fala": ""},
        {"src": "a.mov", "start": 8.0, "end": 14.0, "beat": "s1", "fala": ""},
        {"src": "a.mov", "start": 18.0, "end": 20.0, "beat": "s2", "fala": ""},
        {"src": "a.mov", "start": 20.0, "end": 26.0, "beat": "s3", "fala": ""},
        {"src": "b.mov", "start": 26.0, "end": 32.0, "beat": "s4", "fala": ""},
    ]


def _afirmar_contiguas(plano, edl):
    """As afirmações do critério §7.8. Devolve a lista de falhas (vazia = ok)."""
    falhas = []
    esperadas = [k for k in range(len(edl) - 1)
                 if edl[k + 1]["src"] == edl[k]["src"]
                 and abs(edl[k + 1]["start"] - edl[k]["end"]) < TOL_CONTIGUO]
    for k in esperadas:
        ent = plano["segmentos"][k + 1]
        sai = plano["segmentos"][k]
        if ent["lead_frames_in"] != 0:
            falhas.append("junção %d→%d contígua com lead_frames_in=%d"
                          % (k, k + 1, ent["lead_frames_in"]))
        if ent["video_skip_frames"] != 0:
            falhas.append("junção %d→%d contígua com video_skip_frames=%d"
                          % (k, k + 1, ent["video_skip_frames"]))
        if ent["motivo_lead"] != "contiguo":
            falhas.append("junção %d→%d contígua com motivo_lead=%r"
                          % (k, k + 1, ent["motivo_lead"]))
        if ent.get("fade_in_s") != 0.0:
            falhas.append("junção %d→%d contígua com fade_in_s=%r"
                          % (k, k + 1, ent.get("fade_in_s")))
        if sai.get("fade_out_s") != 0.0:
            falhas.append("junção %d→%d contígua com fade_out_s=%r"
                          % (k, k + 1, sai.get("fade_out_s")))
    return falhas, esperadas


def autoteste(fps=25, sr=48000, lead_max_ms=200.0):
    """Roda SEM tocar em mídia. Verde só quando o teste tem DENTES nos dois sentidos.

    🔴 Por que o controle negativo é obrigatório: um portão que varre 0 e sai 0 é
    indistinguível de um portão quebrado. Este repo já entregou 6,25 s de vídeo
    errado com todos os QCs verdes. Então o autoteste, além de afirmar que as
    junções contíguas saem com lead 0, DESLIGA a guarda e exige que a mesma
    bateria REPROVE. Se ela passar com a guarda desligada, ela não estava
    medindo nada — e o exit é ≠ 0 do mesmo jeito.

    Os parâmetros default são de TESTE, não de produção: `fps=25` de propósito,
    para que um `30` esquecido em algum lugar apareça como erro de conta.
    """
    edl = _edl_sintetica()
    # ar de sobra em toda junção: quem zera o lead é a GUARDA, não a medição
    def medir_farto(i, teto_s):
        return teto_s, teto_s

    n_junc = len(edl) - 1
    print("autoteste: EDL sintética de %d segmentos (%d junções) a %d fps, sr %d, "
          "teto %g ms" % (len(edl), n_junc, fps, sr, lead_max_ms), file=sys.stderr)

    plano = planejar(edl, fps=fps, sr=sr, modo="medido", lead_max_ms=lead_max_ms,
                     medir=medir_farto)
    falhas, contiguas = _afirmar_contiguas(plano, edl)
    descont = [k for k in range(n_junc) if k not in contiguas]
    print("  varreu %d junções: %d contíguas %s · %d descontínuas %s"
          % (n_junc, len(contiguas), contiguas, len(descont), descont), file=sys.stderr)
    if not contiguas:
        print("  ✗ a EDL sintética não produziu junção contígua nenhuma — o teste "
              "não teria o que afirmar", file=sys.stderr)
        return 1
    if not descont:
        print("  ✗ a EDL sintética não produziu junção descontínua — sem contraste, "
              "'lead 0 em toda parte' passaria", file=sys.stderr)
        return 1

    # CONTRASTE: as descontínuas TÊM que ter lead > 0 com ar farto, senão o
    # "lead 0 nas contíguas" seria verdade por acidente (lead 0 em tudo).
    sem_lead = [k for k in descont if plano["segmentos"][k + 1]["lead_frames_in"] <= 0]
    if sem_lead:
        falhas.append("junções descontínuas SEM lead com ar farto: %s "
                      "(o teste ficaria sem contraste)" % sem_lead)
    for f in falhas:
        print("  ✗ " + f, file=sys.stderr)
    if falhas:
        print("autoteste REPROVOU: %d afirmação(ões) falhou(aram)" % len(falhas),
              file=sys.stderr)
        return 1
    leads = [plano["segmentos"][k + 1]["lead_frames_in"] for k in descont]
    print("  ✓ contíguas com lead 0, skip 0, fades 0, motivo `contiguo`; "
          "descontínuas com lead %s frames" % leads, file=sys.stderr)

    # ── CONTROLE NEGATIVO: a guarda desligada TEM que reprovar a mesma bateria ──
    global contiguo
    original = contiguo
    try:
        contiguo = lambda a, b: False           # noqa: E731  — a guarda, desligada
        plano_mau = planejar(edl, fps=fps, sr=sr, modo="medido",
                             lead_max_ms=lead_max_ms, medir=medir_farto)
    finally:
        contiguo = original
    falhas_mau, _ = _afirmar_contiguas(plano_mau, edl)
    if not falhas_mau:
        print("  ✗ CONTROLE NEGATIVO PASSOU: com a guarda de contiguidade DESLIGADA "
              "a bateria continuou verde. O teste não estava medindo nada.",
              file=sys.stderr)
        return 1
    print("  ✓ controle negativo: com a guarda desligada a bateria acusou %d "
          "violação(ões) — o teste tem dentes" % len(falhas_mau), file=sys.stderr)

    # ── e a guarda de cabeça curta, que é a outra que zera lead em silêncio ──
    curta = [{"src": "a.mov", "start": 0.0, "end": 3.0, "beat": "s0", "fala": ""},
             {"src": "a.mov", "start": 9.0, "end": 9.2, "beat": "s1", "fala": ""}]
    p2 = planejar(curta, fps=fps, sr=sr, modo="medido", lead_max_ms=lead_max_ms,
                  medir=medir_farto)
    if p2["segmentos"][1]["motivo_lead"] != "cabeca-curta" or \
            p2["segmentos"][1]["lead_frames_in"] != 0:
        print("  ✗ take de %d frames aceitou lead %d com motivo %r — a guarda de "
              "cabeça curta não rodou"
              % (int(0.2 * fps), p2["segmentos"][1]["lead_frames_in"],
                 p2["segmentos"][1]["motivo_lead"]), file=sys.stderr)
        return 1
    print("  ✓ cabeça curta: take de %d frames recusou o lead (motivo `cabeca-curta`)"
          % int(0.2 * fps), file=sys.stderr)

    # ── o teto em MS resolve contra o fps, e não é constante em frames ──
    # 🔴 os dois números abaixo são ENTRADAS DE TESTE, não default de formato: o
    # teste existe justamente para provar que o mesmo teto em ms dá contagens de
    # frame DIFERENTES em fps diferentes — é a prova negativa do `JCUT_LEAD_FRAMES`
    # fixo do ref-A e do `target_fps` que cai para uma constante no longform deles.
    pares = []
    for f in (30, 24):
        pl = planejar(edl, fps=f, sr=sr, modo="fixo", lead_max_ms=lead_max_ms,
                      medir=medir_farto)
        pares.append((f, pl["segmentos"][2]["lead_frames_in"],
                      pl["segmentos"][2]["lead_ms_in"]))
    if pares[0][1] == pares[1][1]:
        print("  ✗ o mesmo teto de %g ms deu %d frames nos dois fps (%d e %d) — o "
              "lead está constante em FRAMES, que é o defeito do render.py:521/:1143"
              % (lead_max_ms, pares[0][1], pares[0][0], pares[1][0]), file=sys.stderr)
        return 1
    print("  ✓ teto em ms: %g ms → %s"
          % (lead_max_ms, " e ".join("%d frames a %d fps (%.1f ms)" % (n, f, ms)
                                     for f, n, ms in pares)), file=sys.stderr)

    print("autoteste OK", file=sys.stderr)
    return 0


# ────────────────────────────────────────────────────────────────────────── CLI

def _uso():
    sys.exit(__doc__.split("────")[0].strip())


def _valor_de(argv, flag):
    """`--flag valor` ou `--flag=valor`."""
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a[len(flag) + 1:]
    return None


def main(argv):
    if "--autoteste" in argv:
        return autoteste()
    resto = [a for a in argv if not a.startswith("--")]
    d = resto[0] if resto else "."
    if not os.path.isdir(d):
        _uso()
    # 🔴 chdir ANTES de qualquer medição: os `src` da EDL são relativos à pasta da
    # produção (mesma disciplina de bordas.py e audio-exato.py). Sem isto,
    # `jcut.py <dir>` de fora media o nada — ver medidor_real().
    d = os.path.abspath(d)
    os.chdir(d)
    d = "."
    edl = edl_io.segmentos(d)

    if "--nao-aplicar" in argv:
        por = _valor_de(argv, "--por") or os.environ.get("USER") or "agente"
        motivo = _valor_de(argv, "--motivo")
        if not motivo:
            sys.exit("--nao-aplicar exige --motivo \"...\": a decisão NEGATIVA "
                     "também é decisão, e sem o porquê ela é indistinguível de "
                     "ninguém ter pensado no assunto (achado A15).")
        p = gravar_nao_aplicar(d, edl, decidido_por=por, motivo=motivo)
        print("J-cut NÃO será aplicado nesta peça — decisão registrada em %s "
              "por %s: %s" % (os.path.basename(p), por, motivo), file=sys.stderr)
        print(os.path.abspath(p))
        return 0

    if "--medir" in argv:
        plano = carregar(d, edl, exigir=True)
        plano, avisos = medir_saida(d, plano)
        p = gravar(d, plano)
        tot = sum(s["lead_frames_in"] for s in plano["segmentos"])
        print("saida medida: %d segmentos · Σ lead = %d frames (%.1f ms) · %d aviso(s)"
              % (len(plano["segmentos"]), tot, tot * 1000.0 / plano["fps"], len(avisos)),
              file=sys.stderr)
        print(p)
        return 0

    fps, sr, modo, lead_max_ms, nome = config(d, argv)
    mfp = int(_flag(argv, "--min-frames-plano") or MIN_FRAMES_PLANO)
    ov = override_de(d)
    medir = medidor_real(edl, sr) if modo == "medido" else None
    plano = planejar(edl, fps=fps, sr=sr, modo=modo, lead_max_ms=lead_max_ms,
                     medir=medir, override=ov, min_frames_plano=mfp,
                     perfil_nome=nome,
                     log=lambda m: print("  " + m, file=sys.stderr))

    segs = plano["segmentos"]
    junc = len(edl) - 1
    cont = [s["i"] - 1 for s in segs if s["contiguo_com_anterior"]]
    com_lead = [s["i"] - 1 for s in segs if s["lead_frames_in"] > 0]
    total_ms = sum(s["lead_ms_in"] for s in segs)
    por_motivo = {}
    for s in segs[1:]:
        por_motivo[s["motivo_lead"]] = por_motivo.get(s["motivo_lead"], 0) + 1
    print("perfil %s · modo %s · teto %g ms · %d fps (spf %d)"
          % (nome, modo, lead_max_ms, fps, plano["samples_por_frame"]), file=sys.stderr)
    print("%d junções: %d contíguas %s · %d com lead > 0"
          % (junc, len(cont), cont, len(com_lead)), file=sys.stderr)
    print("motivos: " + " ".join("%s=%d" % kv for kv in sorted(por_motivo.items())),
          file=sys.stderr)
    print("respiro removido: %.0f ms no total (%.1f ms por junção com lead)"
          % (total_ms, total_ms / max(1, len(com_lead))), file=sys.stderr)
    if modo != "off" and junc and len(com_lead) < 0.8 * (junc - len(cont)):
        print("  ⚠️ só %d de %d junções descontínuas receberam lead (< 80%%): ou o "
              "corte já está sem ar, ou o teto está baixo demais"
              % (len(com_lead), junc - len(cont)), file=sys.stderr)
    print(gravar(d, plano))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
