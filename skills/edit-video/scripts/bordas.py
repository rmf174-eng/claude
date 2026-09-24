#!/usr/bin/env python3
"""Bordas ACÚSTICAS de corte: janelas do ASR → edl.json com pads do creator.

Uso: bordas.py <dir-da-producao> [--pre 0.02] [--post 0.06] [--floor -52]
Lê  <dir>/janelas.json  → escreve <dir>/edl.json  (mapa das correções no stderr)

📐 Os pads (pre/post/cap/rel/floor) vêm do bloco `ritmo` do perfil de peça
(SPEC-00); as flags de CLI continuam válidas e VENCEM o perfil. Sem
`<dir>/perfil.json` vale o FALLBACK, que traz o default histórico do código
(0,02/0,06) — não o `normal` 0,12/0,20 do perfil `reels`.

janelas.json = [{"src","asr_ini","asr_fim","beat","fala"[,"pre_extra","post_extra",
                 "cortes_herdados_s"]}]
(asr_ini/asr_fim = start da 1ª palavra e end da última palavra do trecho, do transcript do bruto)

POR QUE ISTO EXISTE — o start/end do Deepgram NÃO é verdade acústica, e erra
para os dois lados (medido na produção peca-03, 2026-07-25):
  • ATRASA o start: a fala do gancho começava em 27,63 e o ASR disse 27,76 —
    cortar no ASR DECEPAVA o "M" de "Mulher" (o pior lugar possível pra um clip).
    Também comeu 0,15s da fricativa /s/ de "Sem ironia".
  • ATRASA o end: deixou até 0,29s de silêncio na cauda de "telepatia" e
    "silêncio" — aparar isso tirou 3,0s de gordura sem tocar em nenhuma palavra.
O onset anda PRA TRÁS até achar silêncio de verdade; o decay procura a ÚLTIMA
janela com energia de fala na vizinhança (resolve os dois casos).
"""
import argparse
import json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cauda                  # noqa: E402
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

WIN = 0.01     # FÍSICA: a janela de RMS é de 10 ms — não é valor de formato

# ENTRADAS DO RESOLVEDOR: campos do janelas.json que descrevem COMO calcular o
# corte. Tudo o mais é passado adiante para a edl.json.
# ⚠️ Isto é LISTA NEGRA de propósito. A versão anterior montava o item com uma
# lista BRANCA (src,start,end,fala,beat + zoom,cx,cy) e QUALQUER campo novo do
# janelas.json sumia sem aviso (teardown §5.4). É o que permite que specs futuras
# — `gain_db` por range, fadeIn/fadeOut, marcações de legenda — cheguem ao
# montar.sh sem tocar neste arquivo.
ENTRADAS_DO_RESOLVEDOR = {
    "asr_ini", "asr_fim", "pre_extra", "post_extra",
    "limite_pre", "limite_pos", "start_fixo", "end_fixo",
    "cortes_herdados_s",
}

# os campos que TODO segmento tem por construção — o resto é passthrough, e é o
# passthrough que o resumo do stderr conta (ver o fim do main()).
CANONICOS = {"src", "start", "end", "fala", "beat"}

SCHEMA_RELATORIO_BORDAS = "benchmark.relatorio-bordas/v1"
ARQ_RELATORIO_BORDAS = "relatorio-bordas.json"


def envelope(src: str, cache: dict, SR: int) -> np.ndarray:
    """dB RMS em janelas de 10ms do áudio do bruto (decodifica uma vez por arquivo)"""
    if src not in cache:
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vn",
                              "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                             capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
        w = int(WIN * SR)
        n = len(a) // w
        rms = np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1))
        cache[src] = 20 * np.log10(np.maximum(rms, 1e-7))
    return cache[src]


def onset(db, t_asr, floor, back=0.35):
    """anda PRA TRÁS do start do ASR até 3 janelas consecutivas de silêncio real.

    🐛 Se NÃO achar silêncio dentro de `back`, NÃO estende (devolve o start do ASR).
    A versão antiga devolvia o limite da busca — extensão máxima — e isso é o pior
    caso possível: "não tem silêncio antes da frase" significa quase sempre que a
    fala ANTERIOR (o take rejeitado, a gagueira) está encostada ali. Medido na
    modelagem do ref-D: o segmento "o melhor hambúrguer do mundo" recuava
    0,25s e engolia a cauda do "…porque é" da gagueira descartada — o transcript da
    montagem saía "porque é O PORQUE É o melhor hambúrguer". Sílaba fantasma clássica.
    """
    i = int(t_asr / WIN)
    lim = max(0, int((t_asr - back) / WIN))
    j = i
    achou = False
    while j > lim:
        if all(db[k] < floor for k in range(max(0, j - 3), j)):
            achou = True
            break
        j -= 1
    return round((j if achou else i) * WIN, 3)


def decay(db, t_asr, floor, fwd=0.45, back=0.45):
    """última janela com energia de fala em volta do end do ASR (que adianta E atrasa)"""
    lo = max(0, int((t_asr - back) / WIN))
    hi = min(len(db) - 2, int((t_asr + fwd) / WIN))
    last = lo
    for k in range(lo, hi + 1):
        if db[k] >= floor:
            last = k
    return round((last + 1) * WIN, 3)


def piso_para(db, t, floor):
    """Resolve o piso a usar em t: número fixo, ou ADAPTATIVO se `floor` é None.

    🔴 POR QUE ISTO EXISTE — o piso absoluto pressupõe sala silenciosa de casa, e
    quebra em bruto gravado em lugar público. Medido na produção peca-01
    (2026-07-31, creator-2 e uma amiga num café): o piso das pausas reais é **−44 dB de
    mediana** (p90 −37), contra o default de −52. Consequência: `decay` lê o ruído
    ambiente como fala, nunca acha o fim, e devolve o TETO em 23 de 23 segmentos —
    +0,25s de sala colados no fim de cada frase, o oposto do ritmo "encostado" da
    creator. E `onset` nunca acha silêncio, então devolve o start do ASR sem correção
    (a proteção do primeiro fonema simplesmente não roda).
    Baixar o número na mão não resolve: com −34 ainda sobrava +0,45s em 6 segmentos,
    porque um respiro tardio já basta pro `decay` esticar.
    O que resolve é o critério que `sair_do_ataque`/`sair_da_cauda` já usavam —
    `piso_local` (percentil 15 num raio de 0,6s) + 10 dB. Ele acompanha a sala.
    Uso: `--floor auto`.
    """
    return piso_local(db, t) + 10.0 if floor is None else floor


def decay_relativo(db, t_asr, rel_db, fwd=0.30, back=0.35):
    """Corta na SOLTURA da última palavra, não depois dela.

    O piso absoluto (`decay`) responde "quando o som acaba" — mas o editor de
    referência corta antes disso: no ponto em que a energia já caiu `rel_db`
    abaixo do PICO da própria palavra. Medido no ref-D: a cauda de
    "disso."/"mundo."/"conhecido." foi aparada em 0,3–0,4s cada, e é isso que dá
    o ritmo colado. Piso absoluto não pega porque a cauda ainda está 20dB acima
    do ruído de sala.
    """
    lo = max(0, int((t_asr - back) / WIN))
    hi = min(len(db) - 2, int((t_asr + fwd) / WIN))
    if hi <= lo:
        return round(t_asr, 3)
    # ⚠️ o PICO tem que ser o do CORPO da palavra, não o da janela de busca: medindo
    # o pico dentro da própria cauda o alvo desce junto e o corte ESTICA (testado —
    # ficou pior que o piso absoluto). Janela do pico = os 0,6s que antecedem o end do ASR.
    p_lo = max(0, int((t_asr - 0.60) / WIN))
    p_hi = max(p_lo + 1, int(t_asr / WIN))
    pico = max(db[p_lo:p_hi])
    alvo = pico - rel_db
    last = lo
    for k in range(lo, hi + 1):
        if db[k] >= alvo:
            last = k
    return round((last + 1) * WIN, 3)


def piso_local(db, t, raio=0.6):
    """ruído de fundo em volta de t (percentil 15 — imune a um vale isolado)"""
    lo, hi = max(0, int((t - raio) / WIN)), min(len(db), int((t + raio) / WIN))
    return float(np.percentile(db[lo:hi], 15)) if hi > lo else -60.0


def sair_do_ataque(db, e, margem=10.0, limite=0.35):
    """Recua o FIM do corte até sair da rampa de ataque da próxima palavra.

    🐛 O DEFEITO QUE ISTO CORRIGE (achado pelo creator-1 nos criativos do creator-3, 2026-07-27
    — "as IAs para trabalhar [pra]", "correr logo para conhecer [em]", "edição. Ba
    Basicamente"): travar o fim no `start` da próxima palavra segundo o ASR NÃO basta.
    O timestamp do Deepgram chega ATRASADO em relação ao ataque real: medido em 4 cortes,
    a energia já subia 30 a 260 ms antes do que o ASR dizia. O corte então cai no meio da
    rampa e o segmento leva junto uma rajada de ~70 ms. Medido no montado da emenda
    reveal→num-600k: pico de **−11 dB** logo antes de um silêncio — 50 dB acima do piso
    que existia 60 ms antes. É a "meia palavra" que se ouve.

    Margem calibrada em 10 dB: com 12 sobrava um caso (o ataque do "tá?" no criativo C,
    que passou por 0,4 dB). Baixar é seguro porque a decisão é pela INCLINAÇÃO — soltura
    de palavra está descendo e não é tocada, por mais alta que esteja.

    ⚠️ E o ASR NÃO enxerga isso: fragmento curto não vira token, então o
    `qc-emendas-asr.py` dá o corte como limpo. Quem denuncia é o envelope: **terminar
    alto E subindo**. Daí a regra — enquanto o último frame estiver `margem` dB acima do
    piso local E a energia estiver crescendo, recua.
    """
    piso = piso_local(db, e)
    k = min(len(db) - 1, int(e / WIN))
    lim = max(0, k - int(limite / WIN))
    if k - lim < 4 or db[k] <= piso + margem:
        return round(k * WIN, 3)
    # 1) o corte está numa RAMPA DE SUBIDA? Decide pela inclinação dos últimos 60ms, não
    #    frame a frame: a rampa de ataque tem degraus, e a comparação `db[k] > db[k-1]`
    #    parava no primeiro degrau, ainda dentro do ataque (sobrou em 2 emendas do lote).
    jan = db[max(0, k - 6):k + 1]
    incl = float(np.polyfit(range(len(jan)), jan, 1)[0]) * 100  # dB por 100ms
    if incl <= 3.0:
        return round(k * WIN, 3)   # está DESCENDO: é a soltura da palavra, o estilo colado
    # 2) recua até o ponto silencioso mais recente; se não houver, até o mínimo local
    for j in range(k, lim, -1):
        if db[j] <= piso + margem:
            return round(j * WIN, 3)
    return round((lim + int(np.argmin(db[lim:k + 1]))) * WIN, 3)


def sair_da_cauda(db, s, margem=10.0, limite=0.35):
    """Avança o INÍCIO do corte até sair da cauda da palavra anterior (espelho do acima).

    Mesmo mecanismo, outro lado: começar no `end` do ASR da palavra anterior deixa entrar
    o decaimento dela. Enquanto o frame estiver alto E DESCENDO (cauda), avança.
    Não invade a própria fala: o ataque dela é rampa de SUBIDA, então a busca para antes.

    ⚠️ No INÍCIO DO BRUTO não existe palavra anterior — não há cauda a sair. Sem esta
    guarda o corte avançava 10ms sobre a primeira palavra do arquivo (medido 2026-07-28
    na produção nao-perdeu-a-peca-06, onde o bruto já vem aparado pela creator e a fala
    começa no frame 0: comia o ataque do /v/ de "Você", a 1ª palavra do GANCHO).
    """
    if s <= 0.02:
        return round(s, 3)
    piso = piso_local(db, s)
    k = max(1, int(s / WIN))
    lim = min(len(db) - 1, k + int(limite / WIN))
    while k < lim and db[k] > piso + margem and db[k] < db[k - 1]:
        k += 1
    return round(k * WIN, 3)


# ─────────────────────────── orçamento LEXICAL de pausa (P1, 2026-08-16) ─────

def _ms(segundos):
    return int(round(float(segundos) * 1000.0))


def _metricas_pausa(item, prox, janela, janela_prox):
    """(gap bruto, tempo removido, gap que permanece), todos em segundos.

    O gap que se OUVE depois da concatenação não é `prox.start - item.end`: esse
    intervalo é justamente o pedaço REMOVIDO do bruto. O que permanece é:

        (item.end - asr_fim_anterior) + (asr_ini_proximo - prox.start)
      = gap_lexical_bruto - tempo_removido

    Esta distinção impede confundir o intervalo descartado no bruto com a pausa
    que permanece nos dois lados da emenda. Como timestamps de ASR podem alongar
    finais de palavra, o ajuste fica desligado por padrão até haver calibração
    acústica para o perfil.
    """
    bruto = float(janela_prox["asr_ini"]) - float(janela["asr_fim"])
    removido = float(prox["start"]) - float(item["end"])
    return bruto, removido, bruto - removido


def _cortes_herdados(janela, janela_prox):
    """Tempos de cortes já existentes no bruto declarados pelo gerador de janelas.

    O detector continua separado (`cortes-do-bruto.py`): `bordas.py` não decodifica
    vídeo uma segunda vez. O campo opcional é insumo do resolvedor, não passthrough
    da EDL, e pode estar em qualquer um dos dois lados da emenda.
    """
    out = []
    for j in (janela, janela_prox):
        for valor in j.get("cortes_herdados_s") or []:
            t = float(valor)
            if not any(abs(t - x) < 1e-9 for x in out):
                out.append(t)
    return sorted(out)


def _proteger_corte_herdado(candidato, minimo, maximo, cortes, margem_s):
    """Evita criar plano menor que a margem; alinhar exatamente é permitido.

    Retorna `(valor|None, motivo|None)`. `None` significa que este LADO da emenda
    não pode ser movido com segurança; o chamador ainda pode usar o outro lado.
    """
    candidato = min(max(float(candidato), float(minimo)), float(maximo))
    perto = [c for c in cortes
             if abs(c - candidato) < margem_s - 1e-9 and abs(c - candidato) > 0.001]
    if not perto:
        return candidato, None
    alinhaveis = [c for c in perto if minimo - 1e-9 <= c <= maximo + 1e-9]
    if alinhaveis:
        return min(alinhaveis, key=lambda c: abs(c - candidato)), \
            "ALINHADO-CORTE-HERDADO"
    return None, "CORTE-HERDADO-BLOQUEOU"


def atualizar_relatorios_pausa(edl, janelas, relatorios):
    """Atualiza métricas depois de qualquer estágio posterior (ex.: cauda)."""
    for rel in relatorios:
        i = rel["emenda_i"]
        item, prox = edl[i], edl[i + 1]
        j, jp = janelas[i], janelas[i + 1]
        bruto, removido, final = _metricas_pausa(item, prox, j, jp)
        rel["gap_lexical_bruto_ms"] = _ms(bruto)
        rel["tempo_removido_ms"] = _ms(removido)
        rel["gap_final_ms"] = _ms(final)
        if rel.get("gap_acustico_bruto_ms") is not None:
            rel["gap_acustico_final_ms"] = max(
                0, rel["gap_acustico_bruto_ms"] - rel["tempo_removido_ms"])
            limite = rel["orcamento"].get("max_ms", 0)
            motivos = [x for x in rel.get("motivo", "").split("+") if x]
            if limite and rel["gap_acustico_final_ms"] > limite:
                if "ALERTA-PAUSA-ACUSTICA" not in motivos:
                    motivos.append("ALERTA-PAUSA-ACUSTICA")
                rel["estado"] = "decisao-pendente"
            else:
                rel["estado"] = ("ajustada" if any(
                    x.startswith("AJUSTE-") for x in motivos) else "medida")
            rel["motivo"] = "+".join(motivos)
        rel["deslocamento_fim_ms"] = _ms(item["end"] - rel["fim_antes_s"])
        rel["deslocamento_inicio_ms"] = _ms(
            prox["start"] - rel["inicio_proximo_antes_s"])
        rel["fim_depois_s"] = round(float(item["end"]), 3)
        rel["inicio_proximo_depois_s"] = round(float(prox["start"]), 3)
    return relatorios


def limitar_pausas_lexicais(edl, janelas, cfg, fps, medidas_acusticas=None):
    """Aplica orçamento máximo de pausa, separado de `decay` e de `cauda`.

    O fim anterior é a primeira alavanca. O início seguinte só anda se ainda
    faltar orçamento, porque ataques fracos (/m/, /n/, fricativas) são mais fáceis
    de decepar. Cada lado tem proteção própria em relação ao ASR e um `*_fixo`
    nunca é alterado. Os cortes herdados usam a mesma guarda visual de 8 frames
    do `cortes-do-bruto.py`: alinhar é bom, parar perto é flash.

    A função é pura em relação a mídia: recebe EDL/janelas já resolvidas, altera
    apenas `start/end` e devolve uma decisão auditável por emenda.
    """
    if len(edl) != len(janelas):
        raise ValueError("EDL (%d) e janelas (%d) divergem no orçamento de pausa"
                         % (len(edl), len(janelas)))
    if medidas_acusticas is not None and len(medidas_acusticas) != len(janelas):
        raise ValueError("medidas acústicas (%d) e janelas (%d) divergem"
                         % (len(medidas_acusticas), len(janelas)))
    cfg = dict(cfg or {})
    ativo = cfg.get("ativo") is True
    obrig = ("min_s", "max_s", "alvo_s", "protecao_fim_s",
             "protecao_inicio_s", "min_frames_corte_herdado")
    if ativo:
        faltam = [k for k in obrig if k not in cfg]
        if faltam:
            raise ValueError("ritmo.orcamento_pausa ativo sem %s" % ", ".join(faltam))
        mn, mx, alvo = (float(cfg["min_s"]), float(cfg["max_s"]),
                        float(cfg["alvo_s"]))
        if not (0 <= mn <= alvo <= mx):
            raise ValueError("orcamento_pausa exige 0 <= min_s <= alvo_s <= max_s")
    else:
        mn = float(cfg.get("min_s", 0.0))
        mx = float(cfg.get("max_s", 0.0))
        alvo = float(cfg.get("alvo_s", mx))
    prot_fim = float(cfg.get("protecao_fim_s", 0.0))
    prot_ini = float(cfg.get("protecao_inicio_s", 0.0))
    min_frames = int(cfg.get("min_frames_corte_herdado", 8))
    if fps <= 0 or min_frames < 0:
        raise ValueError("fps e min_frames_corte_herdado precisam ser positivos")
    margem_corte = min_frames / float(fps)

    relatorios = []
    for i in range(len(edl) - 1):
        item, prox = edl[i], edl[i + 1]
        j, jp = janelas[i], janelas[i + 1]
        rel = {
            "schema": "benchmark.pausa-lexical/v1",
            "emenda_i": i,
            "beat_anterior": item.get("beat"),
            "beat_proximo": prox.get("beat"),
            "fim_antes_s": round(float(item["end"]), 3),
            "inicio_proximo_antes_s": round(float(prox["start"]), 3),
            "orcamento": {
                "ativo": ativo,
                "min_ms": _ms(mn), "alvo_ms": _ms(alvo), "max_ms": _ms(mx),
            },
            "protecao": {
                "fim_ms": _ms(prot_fim), "inicio_ms": _ms(prot_ini),
                "corte_herdado_min_frames": min_frames,
            },
        }
        bruto, removido_antes, final_antes = _metricas_pausa(item, prox, j, jp)
        rel["tempo_removido_antes_ms"] = _ms(removido_antes)
        rel["gap_final_antes_ms"] = _ms(final_antes)
        rel["gap_acustico_bruto_ms"] = None
        if medidas_acusticas is not None and item.get("src") == prox.get("src"):
            fim_acustico = float(medidas_acusticas[i]["decay_s"])
            inicio_acustico = float(medidas_acusticas[i + 1]["onset_s"])
            rel["gap_acustico_bruto_ms"] = _ms(max(0.0, inicio_acustico - fim_acustico))
        motivos = []

        if item.get("src") != prox.get("src"):
            motivos.append("FONTE-DIFERENTE")
        elif bruto <= 0:
            motivos.append("SEM-GAP-LEXICAL")
        elif not ativo:
            motivos.append("DESATIVADO")
        elif final_antes <= mx + 0.0005:
            motivos.append("DENTRO-DO-ORCAMENTO")
        else:
            cortes = _cortes_herdados(j, jp)
            falta = max(0.0, final_antes - alvo)
            max_mov = max(0.0, final_antes - mn)

            # Lado 1: recuar o fim, sem invadir a última palavra nem colapsar o take.
            if "end_fixo" in j:
                motivos.append("END_FIXO")
            elif falta > 0:
                fim_min = max(float(item["start"]) + cauda.DUR_MIN,
                              float(j["asr_fim"]) + prot_fim,
                              float(item["end"]) - max_mov)
                disponivel = max(0.0, float(item["end"]) - fim_min)
                mover = min(falta, disponivel)
                if mover > 0:
                    candidato = float(item["end"]) - mover
                    seguro, por_corte = _proteger_corte_herdado(
                        candidato, fim_min, float(item["end"]), cortes,
                        margem_corte)
                    if seguro is None:
                        motivos.append(por_corte)
                    else:
                        item["end"] = round(seguro, 3)
                        motivos.append("AJUSTE-FIM")
                        if por_corte:
                            motivos.append(por_corte)
                if disponivel + 0.0005 < falta:
                    motivos.append("PROTECAO-FONETICA-FIM")

            # Lado 2: só então avançar o início, com proteção independente do ataque.
            _, _, agora = _metricas_pausa(item, prox, j, jp)
            falta = max(0.0, agora - alvo)
            max_mov = max(0.0, agora - mn)
            if "start_fixo" in jp:
                if falta > 0:
                    motivos.append("START_FIXO")
            elif falta > 0:
                ini_max = min(float(prox["end"]) - cauda.DUR_MIN,
                              float(jp["asr_ini"]) - prot_ini,
                              float(prox["start"]) + max_mov)
                disponivel = max(0.0, ini_max - float(prox["start"]))
                mover = min(falta, disponivel)
                if mover > 0:
                    candidato = float(prox["start"]) + mover
                    seguro, por_corte = _proteger_corte_herdado(
                        candidato, float(prox["start"]), ini_max, cortes,
                        margem_corte)
                    if seguro is None:
                        motivos.append(por_corte)
                    else:
                        prox["start"] = round(seguro, 3)
                        motivos.append("AJUSTE-INICIO")
                        if por_corte:
                            motivos.append(por_corte)
                if disponivel + 0.0005 < falta:
                    motivos.append("PROTECAO-FONETICA-INICIO")

            _, _, final = _metricas_pausa(item, prox, j, jp)
            if final > mx + 0.0005:
                motivos.append("ORCAMENTO-INATINGIVEL")

        rel["motivo"] = "+".join(dict.fromkeys(motivos))
        item["pausa_lexical"] = rel
        relatorios.append(rel)

    return atualizar_relatorios_pausa(edl, janelas, relatorios)


def gravar_relatorio_bordas(relatorios, caminho=ARQ_RELATORIO_BORDAS):
    """Publica o relatório por `os.replace`, sem expor JSON parcial."""
    pendentes = [
        {"emenda_i": r["emenda_i"],
         "gap_acustico_final_ms": r.get("gap_acustico_final_ms"),
         "acao": "ouvir e aprovar a pausa, ou ativar/ajustar o orçamento sem cortar fonemas"}
        for r in relatorios if r.get("estado") == "decisao-pendente"
    ]
    doc = {"schema": SCHEMA_RELATORIO_BORDAS, "gerado_por": "bordas.py",
           "pausas_lexicais": relatorios,
           "decisoes_pendentes": pendentes}
    tmp = "%s.tmp-%d" % (caminho, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, caminho)
    return caminho


def argumentos(argv=None):
    ap = argparse.ArgumentParser(
        description="resolve bordas acústicas do ASR e grava a EDL")
    ap.add_argument("producao", help="diretório contendo janelas.json")
    ap.add_argument("--pre", type=float)
    ap.add_argument("--post", type=float)
    ap.add_argument("--floor", metavar="DB|auto")
    ap.add_argument("--cap", type=float)
    ap.add_argument("--rel", type=float)
    ap.add_argument("--cauda", default="medir", metavar="medir|auto|SEGUNDOS")
    ap.add_argument("--cauda-final", action="store_true")
    ns = ap.parse_args(argv)
    if not os.path.isdir(ns.producao):
        ap.error("diretório da produção não existe: %s" % ns.producao)
    janelas = os.path.join(ns.producao, "janelas.json")
    if not os.path.isfile(janelas):
        ap.error("janelas.json não encontrado em: %s" % ns.producao)
    if ns.floor not in (None, "auto"):
        try:
            ns.floor = float(ns.floor)
        except ValueError:
            ap.error("--floor aceita um número em dB ou `auto`")
    return ns


def main(argv=None):
    cli = argumentos(argv)
    d = cli.producao
    # o perfil dá o default; a flag de CLI, quando existe, VENCE
    P = perfil_mod.carregar(d)
    R = P["ritmo"]
    ORCAMENTO_PAUSA = R.get("orcamento_pausa") or {}
    SR = int(P["audio"]["sr"])
    PRE = cli.pre if cli.pre is not None else float(R["pads"]["pre"])
    POST = cli.post if cli.post is not None else float(R["pads"]["post"])
    # FLOOR = None significa piso ADAPTATIVO por janela (ver piso_para). Obrigatório em
    # bruto gravado em lugar público, onde não existe piso fixo. `"floor": "auto"` no
    # perfil é o mesmo que `--floor auto` na linha de comando.
    piso_perfil = R.get("floor", -52.0)
    if cli.floor is not None:
        FLOOR = None if cli.floor == "auto" else float(cli.floor)
    else:
        FLOOR = None if piso_perfil == "auto" else float(piso_perfil)
    # TETO da correção acústica. A busca no envelope existe pra REFINAR o ASR, não
    # pra passear: sem teto, o decay caminha até +0,46s atrás de cauda de reverb/respiro
    # e o onset volta 0,35s pegando a inspiração. Medido contra a referência
    # ref-D (data/adhoc/modelagem-edicao/): com floor −52 e sem teto a EDL
    # saía 17,1s onde o editor entregou 12,4s — 38% de gordura, quase toda em cauda.
    CAP = cli.cap if cli.cap is not None else float(R.get("cap", 0.25))
    # --rel N: corta a cauda N dB abaixo do pico da última palavra (ritmo "colado").
    # 0 = desligado (comportamento histórico: piso absoluto). Calibrado em 12 dB.
    REL = cli.rel if cli.rel is not None else float(R.get("rel", 0.0))
    # --cauda medir|auto|<segundos> — o AR que sobra depois da última palavra.
    # 🔒 O DEFAULT É `medir`, e é decisão: mudar o default mudaria o corte da
    # próxima produção sem ninguém pedir. O precedente é o FALLBACK do perfil de
    # peça ("produção sem perfil.json se comporta exatamente como hoje, byte a
    # byte"). O operador liga com a flag; o perfil só fornece o NÚMERO que o
    # `--cauda auto` usa. Ver cauda.py para o porquê da medição invertida.
    CAUDA = cli.cauda
    CAUDA_FINAL = cli.cauda_final
    if CAUDA == "medir":
        ALVO, APARAR = None, False
    elif CAUDA == "auto":
        APARAR = True
        ALVO = R.get("cauda_alvo_s")
        if ALVO is None:
            ALVO = POST
            print("cauda: `ritmo.cauda_alvo_s` ausente/null no perfil — "
                  "alvo = --post = %.3fs" % POST, file=sys.stderr)
    else:
        try:
            ALVO, APARAR = float(CAUDA), True
        except ValueError:
            sys.exit("--cauda aceita `medir`, `auto` ou um número em segundos; veio %r"
                     % CAUDA)
    ALVO_REF = POST if ALVO is None else ALVO
    print("perfil %s: pads %.2f/%.2f cap %.2f rel %.0f floor %s"
          % (P.get("nome", "?"), PRE, POST, CAP, REL,
             "auto" if FLOOR is None else "%.0f" % FLOOR), file=sys.stderr)
    if ORCAMENTO_PAUSA:
        print("pausa lexical: %s%s"
              % ("ATIVA" if ORCAMENTO_PAUSA.get("ativo") is True else "medição sem ajuste",
                 (" · alvo %.0f ms · faixa %.0f–%.0f ms"
                  % (float(ORCAMENTO_PAUSA.get("alvo_s", 0)) * 1000,
                     float(ORCAMENTO_PAUSA.get("min_s", 0)) * 1000,
                     float(ORCAMENTO_PAUSA.get("max_s", 0)) * 1000))
                 if "alvo_s" in ORCAMENTO_PAUSA else ""), file=sys.stderr)
    os.chdir(d)
    janelas = json.load(open("janelas.json"))
    cache: dict = {}
    edl, tot, passaram, medidas_acusticas = [], 0.0, [], []
    print("%-12s %-15s %-15s %s" % ("beat", "ASR", "ACÚSTICO", "corte"), file=sys.stderr)
    for j in janelas:
        db = envelope(j["src"], cache, SR)
        on = onset(db, j["asr_ini"], piso_para(db, j["asr_ini"], FLOOR))
        de = decay_relativo(db, j["asr_fim"], REL) if REL > 0 else \
            decay(db, j["asr_fim"], piso_para(db, j["asr_fim"], FLOOR))
        on = min(max(on, j["asr_ini"] - CAP), j["asr_ini"] + CAP)
        de = min(max(de, j["asr_fim"] - CAP), j["asr_fim"] + CAP)
        medidas_acusticas.append({"onset_s": on, "decay_s": de})
        # clamp em 0: start negativo faz o slice do áudio colapsar e o segmento sai MUDO
        s = max(0.0, round(on - PRE - j.get("pre_extra", 0), 3))
        e = round(de + POST + j.get("post_extra", 0), 3)
        # 🚧 LIMITE DAS PALAVRAS VIZINHAS no bruto (opcional: `limite_pre`/`limite_pos`).
        # Com `--rel` o decay corta na soltura da vogal e costuma querer passar do fim —
        # em quem fala SEM pausa (medido nos criativos do creator-3, 2026-07-27: 7 de 13
        # cortes) esses 250ms caem em cima do ataque da palavra seguinte e o segmento
        # entrega sílaba fantasma. O envelope não sabe onde a próxima palavra começa;
        # o transcript sabe. Quem monta a janela passa o limite e aqui ele é respeitado.
        # Duas janelas coladas (fim de uma == início da outra) viram corte exatamente na
        # fronteira: áudio contínuo, sem duplicar nem perder amostra.
        lp, ln = j.get("limite_pre"), j.get("limite_pos")
        if lp is not None and s < lp:
            print("   ↳ %-12s start travado em %.3f (palavra anterior)" % (j["beat"], lp), file=sys.stderr)
            s = round(lp, 3)
        if ln is not None and e > ln:
            print("   ↳ %-12s end travado em %.3f (próxima palavra)" % (j["beat"], ln), file=sys.stderr)
            e = round(ln, 3)
        # ⚠️ O limite do ASR é a CONDIÇÃO NECESSÁRIA, não a suficiente: o timestamp dele
        # chega atrasado em relação ao ataque real. Depois de travar pelo texto, sai da
        # rampa pelo ENVELOPE — é isto que impede a meia-palavra na emenda.
        e2 = sair_do_ataque(db, e)
        if e2 < e - 0.005:
            print("   ↳ %-12s end recuado %.0fms: estava dentro do ataque seguinte (%.1f dB)"
                  % (j["beat"], (e - e2) * 1000, db[min(len(db) - 1, int(e / WIN))]), file=sys.stderr)
            e = e2
        s2 = sair_da_cauda(db, s)
        if s2 > s + 0.005:
            print("   ↳ %-12s start avançado %.0fms: estava na cauda anterior"
                  % (j["beat"], (s2 - s) * 1000), file=sys.stderr)
            s = s2
        # 🎯 ESCAPE MEDIDO: `start_fixo`/`end_fixo` no janelas.json venceM todo o heurístico
        # acima. Existe porque o heurístico erra numa classe específica e conhecida: quando a
        # palavra ABRE em fricativa surda (/s/, /ʃ/) ou em nasal (/m/, /n/), o envelope RMS a
        # lê como silêncio, e aí o `onset` para tarde OU o `sair_da_cauda` a confunde com o
        # decaimento da palavra anterior e empurra o corte 20-30 ms pra dentro dela.
        # Medido em 2026-08-01 (produção peca-11): o "se" de "se você é medíocre" saía
        # como "e você" com o corte em 487,120 e volta inteiro em 487,100 — 20 ms de diferença,
        # na primeira palavra do melhor corte do lote. `limite_pre` não resolve: ele é PISO
        # (impede ir pra antes) e o `sair_da_cauda` empurra pra FRENTE, sem violá-lo.
        # ⚠️ Só use com o número vindo de teste de ponto de corte por ASR isolado. É o
        # operador dizendo "eu medi", não "eu acho".
        if "start_fixo" in j:
            print("   ↳ %-12s start FIXO em %.3f (medido)" % (j["beat"], j["start_fixo"]), file=sys.stderr)
            s = round(float(j["start_fixo"]), 3)
        if "end_fixo" in j:
            print("   ↳ %-12s end FIXO em %.3f (medido)" % (j["beat"], j["end_fixo"]), file=sys.stderr)
            e = round(float(j["end_fixo"]), 3)
        if e <= s:
            sys.exit(f"ERRO: {j['beat']} colapsou ({s:.3f} >= {e:.3f})")
        tot += e - s
        print("%-12s %6.2f-%6.2f  %6.2f-%6.2f  onset %+.3f / decay %+.3f → %.3f-%.3f (%.2fs)"
              % (j["beat"], j["asr_ini"], j["asr_fim"], on, de,
                 on - j["asr_ini"], de - j["asr_fim"], s, e, e - s), file=sys.stderr)
        # LISTA NEGRA (ver ENTRADAS_DO_RESOLVEDOR no topo): tudo que não for entrada
        # do cálculo atravessa para a EDL. `zoom`/`cx`/`cy` continuam chegando ao
        # montar.sh como antes, e `gain_db`/`fadeIn`/`fadeOut` passam a chegar também.
        item = {"src": j["src"], "start": s, "end": e}
        for k, v in j.items():
            # 🔒 `k not in item`: `src`/`start`/`end` NUNCA são sobrescritos. Um
            # `start` no janelas.json é o operador descrevendo o ASR, não a borda
            # resolvida — deixar passar apagaria em silêncio todo o cálculo acima.
            if k not in ENTRADAS_DO_RESOLVEDOR and k not in item:
                item[k] = v
        item.setdefault("fala", "")
        passaram.append({k for k in item if k not in CANONICOS})
        edl.append(item)

    # TERCEIRO EIXO, separado de `decay` e do aparo de cauda: o gap entre a última
    # palavra de uma janela e a primeira da próxima. Roda antes da cauda para que
    # `cauda_ms` continue descrevendo o `end` que está no arquivo, sem somar dois
    # aparos escondidos no mesmo diagnóstico. Depois da cauda as métricas abaixo
    # são atualizadas, então o relatório sempre descreve a EDL final.
    relatorios_pausa = limitar_pausas_lexicais(
        edl, janelas, ORCAMENTO_PAUSA, float(P["video"]["fps"]),
        medidas_acusticas=medidas_acusticas) \
        if ORCAMENTO_PAUSA else []
    # ───────────────────────────── CAUDA DO SEGMENTO (SPEC-09) ─────────────────
    # SEGUNDA PASSADA, e tem que ser: a guarda de contiguidade precisa do `start`
    # do PRÓXIMO segmento já resolvido, e ele não existe durante o laço acima.
    # Roda DEPOIS do `end_fixo` (que vence tudo) e antes da gravação; a checagem
    # de colapso é refeita aqui porque o aparo mexe no `end`.
    # `cauda_ms`/`cauda_aparada_ms` entram DEPOIS de `passaram` ser fechado, então
    # não poluem o resumo de campos que atravessaram — eles são nossos, não do
    # janelas.json.
    caudas, n_aparados, cortado = [], 0, 0.0
    for i, (item, j) in enumerate(zip(edl, janelas)):
        db = envelope(item["src"], cache, SR)
        piso = piso_para(db, j["asr_fim"], FLOOR)
        prox = edl[i + 1] if i + 1 < len(edl) else None
        contiguo = prox is not None and prox["src"] == item["src"] and \
            abs(prox["start"] - item["end"]) < 1e-4
        disp = cauda.medir(db, item["start"], item["end"], piso, WIN)
        corte, motivo = 0.0, "MEDIR"
        if APARAR:
            novo_e, corte, motivo = cauda.aparar(
                db, item["src"], item["start"], item["end"], piso, ALVO, sr=SR,
                contiguo_com_proximo=contiguo, ultimo=(prox is None),
                fixo=("end_fixo" in j), cauda_final=CAUDA_FINAL, win=WIN)
            if corte > 0:
                print("   ↳ %-12s cauda %.0fms → aparados %.0fms (end %.3f → %.3f)"
                      % (j["beat"], disp * 1000, corte * 1000, item["end"], novo_e),
                      file=sys.stderr)
                item["end"] = novo_e
                n_aparados += 1
                cortado += corte
            elif disp > ALVO + WIN:
                print("   ↳ %-12s cauda %.0fms MANTIDA (%s)"
                      % (j["beat"], disp * 1000, motivo), file=sys.stderr)
        caudas.append(disp)
        item["cauda_ms"] = int(round(disp * 1000))
        item["cauda_aparada_ms"] = int(round(corte * 1000))
        if item["end"] <= item["start"]:
            sys.exit("ERRO: %s colapsou depois do aparo de cauda (%.3f >= %.3f)"
                     % (j["beat"], item["start"], item["end"]))
    atualizar_relatorios_pausa(edl, janelas, relatorios_pausa)
    for rel in relatorios_pausa:
        prefixo = "⚠️ " if rel.get("estado") == "decisao-pendente" else ""
        acustico = (" · acústico %d ms" % rel["gap_acustico_final_ms"]
                    if rel.get("gap_acustico_final_ms") is not None else "")
        print("%spausa %02d %s→%s: bruto %d ms · removido %d ms · final %d ms%s · "
              "Δfim %+.0f ms · Δinício %+.0f ms · %s"
              % (prefixo, rel["emenda_i"], rel.get("beat_anterior") or "?",
                 rel.get("beat_proximo") or "?", rel["gap_lexical_bruto_ms"],
                 rel["tempo_removido_ms"], rel["gap_final_ms"], acustico,
                 rel["deslocamento_fim_ms"], rel["deslocamento_inicio_ms"],
                 rel["motivo"]), file=sys.stderr)
    med, p90, mx, acima = cauda.resumo(caudas, ALVO_REF)
    tot = sum(x["end"] - x["start"] for x in edl)
    print("cauda: mediana %d · p90 %d · máx %d ms · %d/%d acima do alvo (%.0f ms)"
          % (med, p90, mx, acima, len(edl), ALVO_REF * 1000), file=sys.stderr)
    print("       %s"
          % ("APARADOS %d segmento(s), −%.2fs" % (n_aparados, cortado) if APARAR
             else "modo `medir`: nenhum corte alterado (--cauda auto|<s> apara)"),
          file=sys.stderr)
    # ⚠️ PASSTHROUGH SILENCIOSO É O MESMO DEFEITO COM O SINAL TROCADO. Com a lista
    # negra, um campo escrito errado (`gaindb` em vez de `gain_db`) atravessa até o
    # consumidor, que o ignora — e nada acusa, de novo. Por isso o resumo abaixo:
    # ele conta em quantos segmentos cada campo extra apareceu, e o campo que
    # aparece em POUCOS segmentos é exatamente a forma que um typo tem.
    if passaram:
        universo = sorted(set().union(*passaram))
        if universo:
            print("\ncampos que atravessaram para a EDL: "
                  + " ".join("%s(%d/%d)" % (k, sum(k in p for p in passaram), len(passaram))
                             for k in universo), file=sys.stderr)
            modal = max((frozenset(p) for p in passaram),
                        key=lambda f: sum(frozenset(p) == f for p in passaram))
            for jan, p in zip(janelas, passaram):
                fora = sorted(p ^ set(modal))
                if fora:
                    print("   ↳ %-12s difere do resto: %s"
                          % (jan.get("beat", "?"), ", ".join(
                              ("+" if k in p else "−") + k for k in fora)),
                          file=sys.stderr)
    # 🔴 `invalida_timeline=True`: o corte MUDOU, então a timeline real que
    # descrevia o corte anterior tem que morrer junto. É a defesa que o ref-A
    # documenta em render.py:1199-1203 — e a segunda defesa (fingerprint) está no
    # edl_io.timeline(), porque script local de produção reescreve edl.json sem
    # passar por aqui (peca-01/planos.py:194).
    # as chaves de TOPO do envelope anterior (`perfil`, anotações) sobrevivem —
    # elas descrevem a PEÇA, não o corte; só `segments` e `timeline_real` são
    # substituídos. Quem sabe ler isso é o edl_io: nenhum script desta skill abre
    # `edl.json` na mão, nem para espiar (é o critério 9 da SPEC-05).
    env = edl_io.topo(".")
    env.setdefault("perfil", None)
    env["segments"] = edl
    edl_io.gravar(".", env, invalida_timeline=True)
    if relatorios_pausa:
        gravar_relatorio_bordas(relatorios_pausa)
        print("relatório de bordas: %s" % os.path.abspath(ARQ_RELATORIO_BORDAS),
              file=sys.stderr)
    print("\n%d segmentos | soma da EDL: %.2fs" % (len(edl), tot), file=sys.stderr)
    print(os.path.abspath("edl.json"))


if __name__ == "__main__":
    main()
