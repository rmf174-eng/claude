#!/usr/bin/env python3
"""QC de emenda por ASR ISOLADO: transcreve cada junção do montado e compara com o esperado.

Por que existe: o `audit-emendas.py` mede ENERGIA e, no ritmo colado (`--rel`), acusa
CLIP-FIM em quase todo segmento por construção — vira ruído. E o ASR do montado
INTEIRO funde palavras na emenda e gera falso positivo (registrado no peca-07:
"empresas esse" some o "esse", mas transcrevendo só o trecho ele aparece).

A régua que sobra é esta: pegar só a vizinhança de cada corte, transcrever isolado e
perguntar duas coisas objetivas:
  • VAZOU:  apareceu palavra que não está em nenhum dos dois lados da emenda?
  • SUMIU:  a última palavra do segmento que fecha, ou a primeira do que abre, não veio?

⚠️ ONDE ESTE SCRIPT ESTAVA ERRADO ATÉ 2026-08-08 (SPEC-05, achado 2.3): as
fronteiras saíam de `Σ(end−start)` da EDL. O render arredonda cada segmento pra
frame e o erro acumula SEMPRE no mesmo sentido — medido em `creator-2/peca-03`, a
última fronteira ficava **353 ms** curta, e "descentrada" é exatamente o que faz
este QC ler a palavra errada dos dois lados do corte. É o anti-pattern que o
SKILL.md do ref-A proíbe na linha 513 (e que o código deles comete assim mesmo,
em render.py:809 — 4,433s de erro num caso de 20 takes). Agora as fronteiras vêm
de `edl_io.fronteiras()`, que são frames REAIS / fps.

🔀 J-CUT (SPEC-07): com sobreposição, a emenda deixa de ser um INSTANTE e vira uma
REGIÃO — do momento em que o áudio do take que entra começa até o frame em que a
imagem dele aparece, `lead` frames depois. Centrar a janela do ASR na fronteira de
IMAGEM descentraria a escuta em até meio lead (133 ms no teto de 165 ms a 30 fps),
e "descentrada" é exatamente o que faz este QC ler a palavra errada dos dois lados
do corte. Então a janela é centrada no MEIO da região e alargada pelo lead. Sem
`jcut.json` todo lead é 0 e a janela é a de sempre, ao ms.

Uso: qc-emendas-asr.py <dir-da-producao> [--video v1-montado.mp4] [--margem 1.2]
Precisa de DEEPGRAM_API_KEY. Lê edl.json (campo `fala`). ~US$0,005/min de áudio.
"""
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io           # noqa: E402
import jcut as jcut_mod   # noqa: E402
import asr_compare       # noqa: E402

# nova-3/multi é o default do projeto e o que aguenta trecho CURTO: o nova-2 pt-BR
# devolveu transcrição VAZIA em 3 de 16 janelas de 2,4s (medido nos criativos do
# creator-3) — o que lê como "sumiu tudo" e é só o modelo não segurando pouco contexto.
MODEL = os.environ.get("BENCH_DG_MODEL_QC", "nova-3")
LANG = os.environ.get("BENCH_DG_LANG_QC", "multi")


def resolver_chave_deepgram() -> str:
    """Ambiente -> resolvedor central, sem imprimir ou persistir o valor."""
    inicio = Path(__file__).resolve().parent
    for d in (inicio, *inicio.parents):
        alvo = d / "tools" / "pacote" / "chaves.py"
        if not alvo.is_file():
            continue
        spec = importlib.util.spec_from_file_location("ilha_chaves_asr", alvo)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        valor = mod.resolver("DEEPGRAM_API_KEY")
        if valor:
            # Só o request recebe a credencial. O resolvedor central já aplica
            # a precedência ambiente -> arquivo sem mutar o shell pai.
            return valor
        break
    raise SystemExit(
        "DEEPGRAM_API_KEY não configurada no ambiente nem em "
        "${ILHA_HOME:-~/.config/ilha-de-edicao}/.env. "
        "Use `python3 tools/pacote/chaves.py --pedir DEEPGRAM_API_KEY`.")


def extrair_resposta(j: dict) -> tuple[str, dict]:
    """Extrai texto e sinais de confiança sem depender de um modelo específico."""
    canal = j["results"]["channels"][0]
    alternativa = canal["alternatives"][0]
    def primeiro(*valores):
        return next((v for v in valores if v is not None), None)
    meta = {
        "language": primeiro(canal.get("detected_language"),
                              alternativa.get("detected_language"),
                              alternativa.get("language")),
        "language_confidence": primeiro(canal.get("language_confidence"),
                                         alternativa.get("language_confidence")),
        "confidence": alternativa.get("confidence"),
        "languages": alternativa.get("languages"),
        "words": alternativa.get("words"),
    }
    return alternativa.get("transcript", ""), {k: v for k, v in meta.items()
                                                  if v is not None}


def asr(mp3: bytes) -> tuple[str, dict]:
    url = (f"https://api.deepgram.com/v1/listen?model={MODEL}&language={LANG}"
           "&smart_format=true")
    req = urllib.request.Request(url, data=mp3, method="POST", headers={
        "Authorization": f"Token {resolver_chave_deepgram()}",
        "Content-Type": "audio/mpeg"})
    with urllib.request.urlopen(req) as r:
        j = json.load(r)
    return extrair_resposta(j)


def alertas_comparacao(comparacao: dict) -> str:
    """Serializa todas as classes do comparador para o adaptador do portao."""
    partes = []
    vazou = [x["palavra"] for x in comparacao["falhas"]
             if x["codigo"] == "VAZOU"]
    sumiu = [x["palavra"] for x in comparacao["falhas"]
             if x["codigo"] == "SUMIU"]
    ordem = [(x.get("fim"), x.get("inicio")) for x in comparacao["falhas"]
             if x["codigo"] == "ORDEM_BORDA"]
    if vazou:
        partes.append(f"⚠️ VAZOU {vazou}")
    if sumiu:
        partes.append(f"⚠️ SUMIU {sumiu}")
    if ordem:
        partes.append(f"⚠️ ORDEM-BORDA {ordem}")
    if comparacao["revisoes"]:
        codigos = sorted({x["codigo"] for x in comparacao["revisoes"]})
        partes.append(f"⚠️ REVISAO {codigos}")
    return ("  " + "  ".join(partes)) if partes else ""


def revisao_sem_corrobacao(*comparacoes: dict, instavel=False) -> dict:
    """Rebaixa uma divergência exclusivamente lexical para revisão humana.

    O comparador continua encontrando SUMIU/VAZOU/ORDEM com dentes, mas uma
    transcrição de janela curta não prova que o áudio está defeituoso. Falha dura
    continua sendo responsabilidade dos QCs acústicos (ataque, fonemas, cauda e
    envelope). A segunda janela serve para medir estabilidade, não para promover
    hipótese de ASR a verdade física.
    """
    codigos = set()
    detalhes = []
    for comparacao in comparacoes:
        for item in comparacao.get("falhas", []) + comparacao.get("revisoes", []):
            codigo = item.get("codigo")
            if codigo:
                codigos.add(codigo)
            detalhes.append(item)
    codigos.add("ASR_INSTAVEL" if instavel else "ASR_SEM_CORROBORACAO_ACUSTICA")
    return {
        "estado": "revisao",
        "falhas": [],
        "revisoes": [{"codigo": codigo} for codigo in sorted(codigos)],
        "detalhes_asr": detalhes,
    }


def _audio_janela(video, centro, margem, lead):
    """Extrai uma janela centrada na região real do J-cut."""
    dur = 2 * margem + lead
    ini = max(0.0, centro - dur / 2.0)
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(ini), "-t", str(dur),
         "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-f", "mp3", "-"],
        capture_output=True).stdout


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    a = sys.argv[2:]
    vid = a[a.index("--video") + 1] if "--video" in a else "v1-montado.mp4"
    marg = float(a[a.index("--margem") + 1]) if "--margem" in a else 1.2
    os.chdir(d)
    edl = edl_io.segmentos(".")

    # tempo de cada fronteira NO MONTADO, em FRAMES REAIS. A timeline persistida
    # é preferida (é a que o audio-exato.py usou pra travar o áudio); sem ela,
    # mede-se dos segs/ na hora. O que NÃO se faz mais é somar `end−start`.
    tl = edl_io.timeline(".", exigir=False) or edl_io.medir_timeline(".")
    fr = edl_io.fronteiras(tl)
    nominal = 0.0
    for s in edl:
        nominal += s["end"] - s["start"]
    print("fronteiras por frames reais: última = %.3fs "
          "(a soma nominal da EDL daria %.3fs — %.0f ms de deriva acumulada)"
          % (fr[-1], nominal, (fr[-1] - nominal) * 1000), file=sys.stderr)

    # 🔀 a emenda com J-cut é uma REGIÃO de `lead` frames, não um instante
    plano = jcut_mod.carregar(".", edl)
    leads_s = [0.0] * len(edl)
    if plano is not None and plano.get("aplicar") is not False:
        leads_s = [s["lead_frames_in"] / plano["fps"] for s in plano["segmentos"]]
        if any(leads_s):
            print("jcut: %d junção(ões) com sobreposição — a janela do ASR é centrada "
                  "no MEIO da região e alargada pelo lead (até %.0f ms)"
                  % (sum(1 for x in leads_s if x), max(leads_s) * 1000), file=sys.stderr)

    # 🔴 FRONTEIRA CONTÍGUA NÃO É EMENDA — e reprová-la era defeito por construção.
    #
    # Quando o segmento i+1 continua o i no MESMO bruto, sem pular um único frame,
    # o áudio atravessa: não há corte para auditar. É o split de enquadramento —
    # a mesma frase partida em dois só para trocar de plano.
    #
    # Medido: nesses pares os dois segmentos carregam a MESMA `fala` (é a mesma
    # frase), então o teste tomava como alvo a última palavra da frase INTEIRA e a
    # primeira, que ficam nas duas pontas de um par de 2,8 a 6,9 s — enquanto a
    # janela de escuta tem 2,4 s centrada no meio. As palavras-alvo estavam
    # fisicamente FORA da janela: nenhum corte podia satisfazer o teste, e toda
    # peça com split entrava na bateria com FALHAs falsas. Eram 6 das 16 numa
    # produção só.
    #
    # O predicado é o mesmo que a SPEC-09 já usa para contiguidade.
    def contiguo(a, b):
        return (a.get("src") is not None and a.get("src") == b.get("src")
                and abs(float(b["start"]) - float(a["end"])) < 1e-4)

    problemas = 0
    revisoes = 0
    n_contiguas = 0
    for i in range(len(edl) - 1):
        if contiguo(edl[i], edl[i + 1]):
            n_contiguas += 1
            print(f"[{i:02d}→{i+1:02d}] {fr[i+1]:7.2f}s "
                  f"{edl[i]['beat']:>16s} | {edl[i+1]['beat']:<16s}"
                  f"\n         ⏭️ CONTÍGUO — mesmo bruto, sem salto: o áudio "
                  f"atravessa e não há emenda a auditar")
            continue
        tb = fr[i + 1]     # fronteiras[i+1] = fim do segmento i = início do i+1
        lead = leads_s[i + 1]
        # sem lead isto é `ini = tb − marg`, `dur = 2·marg`: a janela de sempre
        centro = tb - lead / 2.0
        raw = _audio_janela(vid, centro, marg, lead)
        ouvido, meta = asr(raw)
        comparacao = asr_compare.comparar(edl[i]["fala"], edl[i + 1]["fala"],
                                           ouvido, meta)
        reescuta = None
        # Janelas de 2,4 s foram a fonte dos falsos "manda/vamos/estoy". Só
        # divergências duras pagam uma segunda chamada, agora com pelo menos
        # 4,8 s de contexto. Mesmo se repetir, continua sendo evidência ASR sem
        # corroboração acústica e, portanto, revisão em vez de bloqueio.
        if comparacao["estado"] == "falha":
            margem_contexto = max(marg * 2.0, 2.4)
            raw2 = _audio_janela(vid, centro, margem_contexto, lead)
            ouvido2, meta2 = asr(raw2)
            comparacao2 = asr_compare.comparar(
                edl[i]["fala"], edl[i + 1]["fala"], ouvido2, meta2)
            instavel = comparacao2["estado"] != comparacao["estado"] or \
                comparacao2.get("falhas") != comparacao.get("falhas")
            comparacao = revisao_sem_corrobacao(
                comparacao, comparacao2, instavel=instavel)
            reescuta = ouvido2
        flag = alertas_comparacao(comparacao)
        if comparacao["revisoes"]:
            revisoes += 1
        if comparacao["estado"] == "falha":
            problemas += 1
        print(f"[{i:02d}→{i+1:02d}] {tb:7.2f}s {edl[i]['beat']:>16s} | {edl[i+1]['beat']:<16s}"
              f"\n         ouvido: {ouvido}{flag}"
              + (f"\n         reescuta com contexto: {reescuta}" if reescuta is not None else ""))

    print(f"\n{len(edl)-1} fronteiras · {n_contiguas} contígua(s) "
          f"(não auditáveis) · {len(edl)-1-n_contiguas} emendas de verdade · "
          f"{problemas} falha(s) · {revisoes} revisao(oes)", file=sys.stderr)
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
