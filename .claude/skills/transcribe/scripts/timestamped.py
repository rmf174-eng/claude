#!/usr/bin/env python3
"""Gera transcript-ts.md (fala com timestamp) a partir do transcript.json do Deepgram.

O transcript.md que o bloco transcribe produz é texto corrido — serve pra ler e pra
analise de conteudo, mas nao serve pra decupar timeline (onde entra a oferta, quanto
tempo dura o bloco de prova, em que segundo aparece o preco). Este script resolve isso.

Uso:
    timestamped.py <dir-ou-transcript.json> [--paragrafos|--utterances|--silencio [S]]
                                            [--sem-pontuacao] [--precisao 1|2]
                                            [--janela N]

    --paragrafos  (default) um bloco por paragrafo do Deepgram
    --utterances  um bloco por utterance (mais granular, bom pra VSL curta)
    --janela N    agrupa em blocos de ~N segundos (bom pra VSL longa; ex: 30)
    --silencio [S]  view de LEITURA POR FRASE: quebra em gap >= S OU pontuacao final
                    (.?!) OU troca de falante. S omitido -> ritmo.gap_min do
                    perfil.json ao lado da producao -> FALLBACK (aviso no stderr).
    --sem-pontuacao  no modo --silencio, quebra SO por gap. Para comparacao/debug.
    --precisao N  casas decimais do timestamp no modo --silencio (default 2). Os
                  modos antigos continuam em mm:ss.

⚠️ A fronteira de frase do modo --silencio e CANDIDATA, nao ponto de corte. Medido
neste repo (SPEC-27 §2.2): 86% dos gaps entre palavras consecutivas do Deepgram sao
exatamente 0,000 s porque ele ESTICA a ultima palavra para dentro do silencio; contra
o envelope RMS de take-conteudo.MOV o recall e de 70% (14 gaps >=0,5 s no transcript
para 20 silencios acusticos >=0,5 s) e o inicio da frase cai em media +98 ms para
dentro do silencio real. Quem acha ponto de corte e o bordas.py, no envelope.

Por que gap OU pontuacao, e nao so gap (o criterio do ref-A): no MONTADO o bordas.py
ja tirou o ar, e so-gap devolve 1 unidade para 189 s de VSL (medido). A pontuacao e o
sinal que o nosso ASR entrega e o Scribe (ElevenLabs) nao — la o silencio vem
explicito em entradas `spacing`, aqui nao vem.

Ideia modelada de uma ferramenta de edição de terceiro:
helpers/pack_transcripts.py:1-14 (view de leitura em nivel de frase como o unico
derivado que entra no contexto do agente). Copia de leitura em tools/referencias/.
Implementacao nossa e diferente: quebra por gap OU pontuacao, limiar vindo do perfil
de peca em vez de 0.5 fixo no argparse, e a fronteira declarada como candidata no
cabecalho do proprio arquivo gerado.

Imprime o caminho do arquivo final no stdout.
"""
import json
import os
import sys

# 🔒 FALLBACK — usado SO quando nao ha --silencio S nem perfil.json ao lado da
# producao. O nome do campo e o mesmo do perfil de peca de proposito: quem tiver
# perfil manda, quem nao tiver herda este numero e ve o aviso no stderr.
FALLBACK_GAP_MIN = 0.35        # perfil: ritmo.gap_min

FIM_DE_FRASE = ".?!"


def mmss(seconds):
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def blocos_de_paragrafos(alt):
    paras = (alt.get("paragraphs") or {}).get("paragraphs") or []
    for p in paras:
        texto = " ".join(s["text"] for s in p.get("sentences", []))
        if texto.strip():
            yield p["start"], p["end"], texto.strip()


def blocos_de_utterances(results):
    for u in results.get("utterances") or []:
        if u.get("transcript", "").strip():
            yield u["start"], u["end"], u["transcript"].strip()


def agrupa_por_janela(blocos, janela):
    """Junta blocos consecutivos ate fechar ~janela segundos."""
    buf, ini, fim = [], None, None
    for start, end, texto in blocos:
        if ini is None:
            ini = start
        buf.append(texto)
        fim = end
        if fim - ini >= janela:
            yield ini, fim, " ".join(buf)
            buf, ini, fim = [], None, None
    if buf:
        yield ini, fim, " ".join(buf)


# ---------------------------------------------------------------------------
# frases() — a unidade de leitura.
#
# ⚠️ Esta funcao existe DUAS vezes no repo, copiada de proposito:
#   .claude/skills/transcribe/scripts/timestamped.py   (aqui)
#   .claude/skills/edit-video/scripts/deiticos.py      (a copia)
# A skill `transcribe` e um bloco independente (CLAUDE.md: "cada bloco funciona
# sozinho e se comunica so por arquivos") e e usada em benchmark de terceiro, sem
# perfil e sem edit-video. Importar de la criaria acoplamento cross-skill que a
# SPEC-22 audita. Sao 20 linhas; um modulo comum e escopo de outra spec. Mesma
# decisao que a SPEC-10 tomou para o envelope_db.
# ---------------------------------------------------------------------------
def frases(words, *, gap_min, usar_pontuacao=True):
    """Quebra words[] em gap >= gap_min OU pontuacao final (.?!) OU troca de speaker.

    Devolve (grupos, motivos) — motivos[i] e o criterio que FECHOU grupos[i], e
    tem len(grupos)-1 itens.

    O gap sozinho nao basta: o Deepgram estica a ultima palavra para dentro do
    silencio (86% dos gaps sao 0,000 s; recall de 70% contra o envelope) e no
    MONTADO o bordas.py ja removeu o ar (1 unidade em 189 s de VSL). A pontuacao e
    o sinal que o nosso ASR entrega e o Scribe nao.
    """
    grupos, motivos, buf = [], [], []
    for i, w in enumerate(words):
        if buf:
            ant = words[i - 1]
            motivo = None
            if usar_pontuacao:
                pw = (ant.get("punctuated_word") or ant.get("word") or "").rstrip()
                if pw[-1:] in FIM_DE_FRASE and pw[-1:]:
                    motivo = "pontuacao"
            sa, sb = ant.get("speaker"), w.get("speaker")
            if sa is not None and sb is not None and sa != sb:
                motivo = "falante"
            if float(w.get("start") or 0.0) - float(ant.get("end") or 0.0) >= gap_min:
                motivo = "gap"
            if motivo:
                grupos.append(buf)
                motivos.append(motivo)
                buf = []
        buf.append(w)
    if buf:
        grupos.append(buf)
    return grupos, motivos


def texto_de(grupo):
    return " ".join((w.get("punctuated_word") or w.get("word") or "") for w in grupo).strip()


def gap_min_do_perfil(path_transcript):
    """ritmo.gap_min do perfil.json que estiver ao lado da producao.

    Le um ARQUIVO JSON — nao importa nada de edit-video/, de proposito (§3.3 da
    SPEC-27). Procura ./perfil.json e ../perfil.json a partir do diretorio do
    transcript, que e onde o `perfil.py resolver` grava o snapshot da producao.
    Devolve (valor, origem) ou (None, None).
    """
    d = os.path.dirname(os.path.abspath(path_transcript))
    for cand in (os.path.join(d, "perfil.json"),
                 os.path.join(os.path.dirname(d), "perfil.json")):
        if os.path.isfile(cand):
            try:
                with open(cand) as fh:
                    p = json.load(fh)
                v = (p.get("ritmo") or {}).get("gap_min")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(v), "perfil %s" % (p.get("nome") or os.path.basename(cand))
            except (OSError, ValueError):
                pass
    return None, None


def _valor(argv, nome):
    """--nome=V ou --nome V (V nao pode comecar com --). -> (valor, indices usados).

    Consome os proprios tokens para que a heuristica antiga do --janela (que le
    args[1]) continue enxergando exatamente o que enxergava antes.
    """
    pre = "--" + nome
    for i, a in enumerate(argv):
        if a == pre:
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                return argv[i + 1], {i, i + 1}
            return "", {i}
        if a.startswith(pre + "="):
            return a.split("=", 1)[1], {i}
    return None, set()


def main():
    argv = sys.argv[1:]
    usados = set()
    v_sil, c = _valor(argv, "silencio")
    usados |= c
    v_prec, c = _valor(argv, "precisao")
    usados |= c
    livre = [a for i, a in enumerate(argv) if i not in usados]

    args = [a for a in livre if not a.startswith("--")]
    flags = [a for a in livre if a.startswith("--")]
    if not args:
        sys.exit(__doc__)

    alvo = args[0]
    path = os.path.join(alvo, "transcript.json") if os.path.isdir(alvo) else alvo
    if not os.path.exists(path):
        sys.exit(f"nao achei: {path}")

    janela = 0
    if "--janela" in flags or any(f.startswith("--janela") for f in flags):
        # aceita "--janela 30" (em args) ou "--janela=30"
        for f in flags:
            if f.startswith("--janela="):
                janela = int(f.split("=", 1)[1])
        if not janela and len(args) > 1:
            janela = int(args[1])

    with open(path) as fh:
        j = json.load(fh)

    results = j["results"]
    alt = results["channels"][0]["alternatives"][0]
    dur = j.get("metadata", {}).get("duration", 0)

    out = os.path.join(os.path.dirname(path), "transcript-ts.md")

    if v_sil is not None:
        _escreve_frases(out, alt, dur, path, v_sil, v_prec,
                        usar_pontuacao="--sem-pontuacao" not in flags)
        print(out)
        return

    if "--utterances" in flags:
        blocos = list(blocos_de_utterances(results))
        fonte = "utterances"
    else:
        blocos = list(blocos_de_paragrafos(alt))
        fonte = "paragrafos"
        if not blocos:  # nem todo request pede paragraphs
            blocos = list(blocos_de_utterances(results))
            fonte = "utterances (fallback)"

    if janela:
        blocos = list(agrupa_por_janela(blocos, janela))
        fonte += f", agrupado em ~{janela}s"

    with open(out, "w") as fh:
        fh.write("# Transcrição com timestamp\n\n")
        fh.write(f"- Duração: {mmss(dur)} ({dur:.0f}s)\n")
        fh.write(f"- Blocos: {len(blocos)} ({fonte})\n\n")
        for start, end, texto in blocos:
            fh.write(f"**[{mmss(start)}–{mmss(end)}]** {texto}\n\n")

    print(out)


def _escreve_frases(out, alt, dur, path, v_sil, v_prec, usar_pontuacao):
    words = alt.get("words") or []
    if not words:
        sys.exit("--silencio precisa de words[] no transcript.json (este nao tem)")

    if v_sil not in ("", None):
        gap, origem = float(v_sil), "flag"
    else:
        gap, origem = gap_min_do_perfil(path)
        if gap is None:
            gap, origem = FALLBACK_GAP_MIN, "FALLBACK"
            print("aviso: sem perfil.json ao lado — gap_min = %.2f s (FALLBACK). "
                  "`--silencio S` ou `perfil.py resolver <dir> --perfil <n>` fixa o valor."
                  % gap, file=sys.stderr)

    prec = int(v_prec) if v_prec not in ("", None) else 2
    larg = 4 + prec

    grupos, motivos = frases(words, gap_min=gap, usar_pontuacao=usar_pontuacao)
    n_gap = motivos.count("gap")
    n_pon = motivos.count("pontuacao")
    n_fal = motivos.count("falante")
    crit = ("frase · gap ≥ %.2f s [%s]%s"
            % (gap, origem, " ou pontuação final" if usar_pontuacao else " (SÓ gap, --sem-pontuacao)"))

    with open(out, "w") as fh:
        fh.write("# Transcrição com timestamp\n\n")
        fh.write(f"- Duração: {mmss(dur)} ({dur:.0f}s)\n")
        fh.write(f"- Blocos: {len(grupos)} ({crit})\n")
        fh.write(f"- Quebras: {n_gap} por gap · {n_pon} por pontuação · "
                 f"{n_fal} por troca de falante\n")
        fh.write("- ⚠️ A fronteira de frase é CANDIDATA, não ponto de corte. Recall medido contra o\n"
                 "  envelope: 70 % · offset mediano +98 ms para dentro do silêncio real. O ponto de\n"
                 "  corte é do bordas.py.\n\n")
        for g in grupos:
            ini = float(g[0].get("start") or 0.0)
            fim = float(g[-1].get("end") or 0.0)
            fh.write(f"[{ini:0{larg}.{prec}f}-{fim:0{larg}.{prec}f}] {texto_de(g)}\n")


if __name__ == "__main__":
    main()
