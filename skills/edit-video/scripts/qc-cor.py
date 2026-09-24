#!/usr/bin/env python3
"""QC de COR — cruza RÓTULO × PIXEL, que é o único jeito de os dois se fecharem.

Uso:
  qc-cor.py <dir-da-producao> [--bruto <arquivo>] [--ref <arquivo.mov>]
     sem --bruto: o maior vídeo de `input/` (nunca um nome cravado)
            [--so-entregaveis] [--amostras N] [--segs N] [--cor cor.json]
  qc-cor.py --autoteste <dir-tmp>     # controle negativo: planta o defeito e
                                      # confere que a régua ACUSA (§7.9)

🔴 LEIA ISTO ANTES DE RODAR QUALQUER COISA EM LOTE.

Este script existe em duas versões, e a primeira **produziu um defeito**. A
reconstituição, por mtime, está registrada:

  2026-08-06 22:57  a v1 deste arquivo nasce, para corrigir "SDR rotulado como
                    HLG" (produção creator-2/peca-02; o creator-1 viu o defeito
                    entregue: "começa mais branco e depois fica mais vívido").
  2026-08-06 22:59  os 13 `v1-montado*.mp4` do repo são reescritos. Dois minutos.

A v1 tinha UMA regra para qualquer .mp4 da pasta — `cs == ct == cp == "bt709"` —
e imprimia, para cada reprovado, o comando `h264_metadata` pronto. Ela não sabia
em que ponto da cadeia cada arquivo estava. Um intermediário HLG, que DEVERIA
estar rotulado HLG porque os pixels são HLG, reprovava; alguém colou o comando
sugerido e rodou em lote. O bsf troca o rótulo sem tocar em um pixel — é
exatamente o que ele promete. Resultado: 13 arquivos com pixels HLG e rótulo
Rec.709, o defeito SIMÉTRICO ao que este QC nasceu para corrigir. E a v1 imprimia
✅ para eles, porque nunca olhava os pixels.

  Prova medida (2026-08-08): `peca-01/segs/seg000.mp4` é
  `bt2020nc/arib-std-b67/bt2020`; o `v1-montado.mp4` da mesma produção é
  `bt709/bt709/bt709` com OS MESMOS PIXELS — diferença máxima 4/255, média
  0,86/255. Ruído de seek, nada de conversão.

  E não é o `montar.sh`: o concat `-c copy` de dois segmentos mais o remux final
  foi reproduzido e a tag HLG é PRESERVADA. O caminho canônico está correto. O
  rótulo errado veio da remediação, não da montagem.

Daí as três regras desta versão:

  1. o rótulo esperado vem do ESTÁGIO do arquivo, não é `bt709` para todo mundo;
  2. o estágio é medido nos PIXELS (distância até o bruto × distância até a
     referência Apple), não deduzido do nome do arquivo;
  3. 🔴 a sugestão de conserto só sai quando o estágio daquele arquivo PEDE
     `bt709`. Um QC que sugere conserto sem saber o que o arquivo deveria ser não
     é QC — é gerador de defeito.

E as duas armadilhas de build, remedidas em 2026-08-08 (ffmpeg 8.0.1 homebrew):

  · as opções de SAÍDA `-color_primaries` e `-color_trc` são SILENCIOSAMENTE
    ignoradas; só `-colorspace` pega;
  · a flag ignorada NÃO deixa `unknown` — deixa A TAG DA FONTE. É assim que nasce
    o rótulo Frankenstein `bt709 / arib-std-b67 / bt2020`, que nenhum comentário
    do código previa. Use `setparams` no filtergraph ao encodar, ou
    `-bsf:v h264_metadata=…` para corrigir arquivo pronto sem re-encode.

⚠️ NENHUM QC por extração de frame pega rótulo errado (o ffmpeg lê o pixel e
ignora o rótulo) e nenhum QC de rótulo pega pixel errado (só compara strings).
Só o cruzamento fecha.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np

DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, DIR_SCRIPT)
import perfil as perfil_mod   # noqa: E402


def _importar(nome, arquivo):
    esp = importlib.util.spec_from_file_location(nome, os.path.join(DIR_SCRIPT, arquivo))
    mod = importlib.util.module_from_spec(esp)
    esp.loader.exec_module(mod)
    return mod


# a MESMA função de estatística do Tier 2 do detector (8 bits forçados, sem
# downscale). Duas cópias seriam duas réguas.
detect_cor = _importar("detect_cor", "detect-cor.py")

# Regiões de amostragem em FRAÇÕES do quadro: precisam ficar FORA de qualquer
# overlay, senão o gráfico entra na conta e o desvio medido vira ficção.
# 📐 A13/A12: em px eles quebravam no instante em que a resolução mudasse. O que é
# FÍSICA aqui é "medir onde não há gráfico"; o canvas é formato e vem do perfil.
# procedência: os px históricos (y 1620-1900, x 60-1020 sobre o canvas vertical
# Full HD) divididos pelo canvas — foi assim que estes quatro números saíram.
REGIOES_PCT = {
    "rodapé (sem overlay)": {"y0": 0.84375, "y1": 0.98958,
                             "x0": 0.05556, "x1": 0.94444},
}

# ═══════════════════════════════════════════════════════════════════════════
# 🔴 A RÉGUA DE PIXEL — e a premissa da SPEC-11 §3.11 que NÃO SE SUSTENTOU.
#
# A spec mandava cruzar rótulo × pixel pela DISTÂNCIA EUCLIDIANA em
# (black_floor, white_ceiling, sat_mean), reprovando quando
# razão = d(S_bruto)/d(S_ref) < 0,5. Os números dela: 0,26 no `v1-montado` (o
# defeito) contra 1,20 no `v1-graded` (correto), "1,9× de folga abaixo".
#
# Remedido hoje (2026-08-08), com a referência avconvert gerada DO BRUTO DESTA
# PRODUÇÃO: `v1-montado.mp4` dá razão **0,76** — dentro da zona de aprovação. A
# régua da spec NÃO ACUSA o defeito que ela existe para acusar.
#
# A causa, medida (mesma função, n = 12 / 24 / 48 amostras no mesmo arquivo):
#
#   eixo   separação bruto↔ref   ruído do próprio eixo   S/R
#   bf     0,0079                0,0079                  ~1
#   wc     0,0000–0,0040         0,0117                  <1
#   sat    0,0191                0,0002                  ~95
#
# `black_floor` e `white_ceiling` são EXTREMOS POR FRAME (percentil de YMIN/YMAX).
# Entre um bruto e uma montagem dele, os frames amostrados são outros, e os dois
# eixos carregam ruído de seleção de frame da MESMA ORDEM que o sinal de cor. A
# distância euclidiana soma os três com peso igual: dois terços dela são ruído.
# `sat_mean` é média sobre todos os pixels de todos os frames — por isso é o único
# que reproduz.
#
# (Evidência lateral de que o diagnóstico está certo: das três métricas da tabela
# da spec, a única que eu reproduzo é justamente `sat` — a referência dela mede
# 0,0990 e a minha 0,0989. `bf` e `wc` divergem em 3 passos de quantização.)
#
# ═══ O QUE ENTROU NO LUGAR ═════════════════════════════════════════════════
# `avanco(v)` — a PROJEÇÃO do arquivo sobre o eixo da conversão:
#
#     t = (v − S_bruto) · (S_ref − S_bruto) / |S_ref − S_bruto|²
#
# t ≈ 0 → os pixels ainda estão no domínio do bruto.  t ≈ 1 → já estão no domínio
# da referência SDR. A projeção pesa cada eixo pelo sinal que ELE carrega, então o
# ruído ortogonal ao eixo da conversão sai da conta sozinho — não é preciso
# escolher eixo na mão.
#
# Medido em `peca-01` (n = 24 / 48, os dois valores):
#     v1-montado (o defeito)  0,318 / 0,337   → pre  ✅ acusado
#     v1-sdr                  1,359 / 1,223   → pos
#     v1-graded               1,793 / 1,594   → pos
#     v-final (compositado)   1,866 / 1,814   → pos
# Limiar 0,5: 1,6× de folga abaixo (montado) e 2,4× acima (v1-sdr).
LIMIAR_AVANCO = 0.5

# 🔴 E o segundo achado, que inverte o escopo da spec: o teste NÃO pode rodar em
# `segs/*`. Medido nos segmentos HLG da `peca-01`, todos comprovadamente
# PRÉ-conversão: t vai de −0,23 a +0,53 (seg000 −0,23 · seg028 +0,18 · seg014
# +0,53). Um segmento é um crop curto de outro momento; `sat_mean` acompanha o
# CONTEÚDO, não só o domínio de cor. Rodar ali fabrica reprovação.
#
# A spec pedia o oposto — segs dentro, `v-final` fora (razão 0,95, "perto demais
# do limiar"). Sob a projeção é ao contrário: `v-final` mede 1,87, longe do
# limiar, e os segs é que são inutilizáveis. Mantenho `v-final` no teste com nota
# de que ele carrega overlay.
PREFIXOS_AVANCO = ("v1-", "v-final")

# ═══════════════════════════════════════════════════════════════════════════
# SPEC-25 — O ESTÁGIO DEIXA DE SER ADIVINHADO PELO NOME DO ARQUIVO
#
# Até aqui o estágio de `segs/*` e `v1-montado*` era uma PREMISSA da SPEC-11: a
# conversão HDR→SDR acontecia num passe à parte, depois da montagem, logo tudo
# antes do `v1-sdr` era pré-conversão. A SPEC-25 inverte isso — a conversão passa
# a acontecer NA EXTRAÇÃO — e a única forma de o QC não errar por metade das
# produções é PERGUNTAR, não supor. Quem responde é o `cor.json`:
#
#   aplicada_em: "extracao"  →  segs/* e v1-montado* já são PÓS-conversão
#   aplicada_em: "passe"     →  segs/* e v1-montado* são PRÉ (a SPEC-11)
#   aplicada_em: ausente/null→  a SPEC-11, sem mudança nenhuma
#
# 🔒 O terceiro caso é o que protege as 13 produções antigas: elas foram montadas
# antes desta spec, o campo não existe nelas, e continuam sendo acusadas
# exatamente como eram. Uma migração de veredito em lote é o que criou o defeito
# de 2026-08-06 — este QC não repete isso nem em silêncio nem por acidente.
def estagio_declarado(f, aplicada_em):
    """PRÉ/PÓS declarado pelo `cor.json`, ou None quando ninguém declarou."""
    if aplicada_em == "extracao":
        return "pos"        # da fronteira do primeiro segmento em diante
    if aplicada_em == "passe":
        base = os.path.basename(f)
        if f.startswith("segs/") or base.startswith("v1-montado"):
            return "pre"
        if base.startswith(("v1-sdr", "v1-graded", "v-final")):
            return "pos"
    return None


# 🔴 DETECTOR DE LUT DUPLA — e a régua que a SPEC-25 §3.10 propôs NÃO SE SUSTENTA.
#
# A spec mandava acusar "conversão aplicada duas vezes" quando um alvo
# pós-conversão ficasse mais de 15% ABAIXO da luminância média da referência
# avconvert, calibrado na assinatura medida de −23,7% ("folga de 1,6×").
#
# Medido hoje (2026-08-09) na `peca-01`, região rodapé, contra a
# referência avconvert do próprio bruto:
#
#     v1-sdr.mp4      lum  +0,6%     ← convertido, SEM look
#     v1-montado.mp4  lum +34,8%     ← ainda HLG
#     v1-graded.mp4   lum −20,6%     ← convertido, COM o preset da creator-2
#     v-final.mp4     lum −20,5%     ← idem, com a camada gráfica
#
# O preset do creator escurece **−20,6%** de forma perfeitamente legítima, e a
# assinatura da LUT dupla é **−23,7%**. As duas populações se sobrepõem: o limiar
# de −15% reprovaria `v1-graded.mp4` e `v-final.mp4` — dois arquivos APROVADOS e
# publicados. Um QC que acusa a peça entregue é pior que um QC que não acusa nada,
# porque ensina a ignorar o vermelho.
#
# ═══ O QUE ENTROU NO LUGAR ═════════════════════════════════════════════════
# O detector só roda nos alvos SEM LOOK — `v1-montado*` e `v1-sdr*`. Neles o
# esperado contra a referência é ≈0% (medido: +0,6%), e a LUT dupla os leva a
# ≈ −23% (0,6% × 0,763, com o fator medido em §2.5.7). Limiar −15%: 1,5× de folga
# abaixo da assinatura e 25× acima do ruído do caso bom.
# Nos arquivos COM look o número é impresso como informação, e é dito por que ele
# não decide nada ali — em vez de virar um vermelho que ninguém pode consertar.
LIMIAR_LUT_DUPLA = -15.0
SEM_LOOK = ("v1-montado", "v1-sdr")

# Separação mínima entre bruto e referência para a régua discriminar. Abaixo
# disto o denominador da projeção é ruído e o veredito seria sorteio → SKIP.
#
# ⚠️ O NÚMERO MUDOU JUNTO COM A RÉGUA. Ele era 0,010 sobre a NORMA dos três
# eixos; hoje a projeção é só em `sat`, e comparar o mesmo 0,010 contra um único
# eixo apertaria a guarda sem ninguém decidir isso. Medido nas duas produções: o
# eixo de saturação vale 0,0115 (peca-06) e 0,0191 (peca-01, a mesma medição de
# S/R da SPEC-11). 0,006 fica ~2× abaixo do menor caso real e ~30× acima do ruído
# do próprio eixo (0,0002).
SEPARACAO_MIN = 0.006

# a lista mora no detect-cor.py, que é quem classifica cor (SPEC-25)
TRANSFERS_HDR = detect_cor.TRANSFERS_HDR


def regioes_px(P):
    W, H = int(P["video"]["largura"]), int(P["video"]["altura"])
    return {nome: (slice(int(r["y0"] * H), int(r["y1"] * H)),
                   slice(int(r["x0"] * W), int(r["x1"] * W)))
            for nome, r in REGIOES_PCT.items()}


def duracao(v):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", v], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def instantes(P, dur):
    """🐛 A13: `TS = [2,10,…,70]` em segundos FIXOS assume peça de ≥70 s. Numa VSL
    de 25 min isso amostra só os 70 s iniciais e o QC de cor carimba OK sobre 4,7%
    da peça. Agora as amostras são PERCENTUAIS da duração real."""
    pcts = P.get("qc", {}).get("amostras_cor_pct") or [0.02, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9]
    return [round(max(0.0, p * dur), 3) for p in pcts]


def tags(v):
    """⚠️ `-of csv=p=0` devolve os campos na ordem em que existem no stream, NÃO
    na ordem pedida — a 1ª versão deste script lia pix_fmt como se fosse o
    color_space e reprovava arquivos corretos. QC que mente é pior que QC
    nenhum: peça key=value e leia pelo nome."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_space,color_transfer,color_primaries,color_range,pix_fmt",
         "-of", "default=noprint_wrappers=1", v], capture_output=True, text=True).stdout
    d = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
    return (d.get("color_space", "?"), d.get("color_transfer", "?"),
            d.get("color_primaries", "?"))


def trio(d):
    """dict de tags (color_space|colorspace, color_trc, color_primaries) → tupla."""
    if not d:
        return None
    return (d.get("colorspace") or d.get("color_space") or "?",
            d.get("color_trc") or d.get("color_transfer") or "?",
            d.get("color_primaries") or "?")


def fmt(t):
    return "%s,%s,%s" % t if t else "(não sei)"


def frame(v, t):
    from PIL import Image
    import io
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t), "-i", v,
                        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                       capture_output=True).stdout
    if not p:
        return None
    return np.array(Image.open(io.BytesIO(p)).convert("RGB"), dtype=np.float64)


def metricas(x):
    r, g, b = x[:, :, 0].mean(), x[:, :, 1].mean(), x[:, :, 2].mean()
    return np.array([x.mean(), (x.max(axis=2) - x.min(axis=2)).mean(), r / max(b, 1e-6)])


def vetor(s):
    return np.array([s["black_floor"], s["white_ceiling"], s["sat_mean"]])


# 🔴 A PROJEÇÃO É SÓ NO EIXO DE SATURAÇÃO, e isto é a segunda correção da régua.
#
# A primeira trocou a distância euclidiana da SPEC-11 por uma projeção nos TRÊS
# eixos, pesando cada um pelo sinal que ele carrega DENTRO daquela produção. Isso
# resolveu a `peca-01` e não sobreviveu à segunda produção. Decomposto eixo a
# eixo (verificacao/cor-e-formato.md §1):
#
#   produção  alvo                          t      bf      wc      sat   só sat
#   peca-01   v1-montado (convertido)   +1,427  +0,435  −0,000  +0,993  +1,162
#   peca-01   v-final                   +1,869  +0,362  −0,000  +1,507  +1,764
#   peca-06   v1-montado (NÃO conv.)    +0,070  +0,070  −0,000  +0,000  +0,000
#   peca-06   v-final-sem-filtro        −0,620  +0,561  −1,405  +0,224  +0,739
#   peca-06   v-final                   −0,765  +0,631  −1,683  +0,287  +0,948
#
# Na `peca-01` o eixo da conversão tinha componente `wc` = 0,0000 — o teto de
# branco não entrava na conta, e o limiar 0,5 foi calibrado DENTRO desse acidente.
# Na `peca-06` o eixo tem `wc` = −0,0157 e o grade da peça clipa o branco
# (0,9529 → 1,0000): +0,0471 na direção CONTRÁRIA ao eixo, 3× a magnitude dele.
# Esse termo sozinho contribui −1,683 e afunda dois arquivos corretos.
#
# A lição que generaliza: projetar pesa por sinal, mas não protege contra um eixo
# cujo RUÍDO EDITORIAL é maior que o sinal de conversão. `black_floor` e
# `white_ceiling` são extremos por frame, e o grade mexe neles de propósito.
# `sat_mean` é média sobre todos os pixels de todos os frames — S/R ≈ 95 contra
# ~1 dos outros dois, medido na própria SPEC-11.
#
# Só com `sat`: 6 de 6 corretos nas duas produções, com o mesmo limiar 0,5. A
# menor folga acima passa a ser 0,739 (1,5×) e a maior abaixo, 0,000.
I_SAT = 2


def projetar(v, vb, eixo, n2):
    """t sobre o eixo da conversão, medido SÓ em saturação."""
    d = float(eixo[I_SAT])
    if abs(d) < 1e-9:
        # sem sinal de saturação não há o que medir — e é melhor dizer isso do
        # que devolver um número que não significa nada.
        return float("nan")
    return float((v[I_SAT] - vb[I_SAT]) / d)


# ───────────────────────────────────────────────────── a referência, e a procedência
# 🔴 ACHADO 2.1: o default de `--ref` era o caminho GLOBAL `/tmp/ref-apple.mov`, e
# o script só a regenerava quando o arquivo NÃO EXISTIA. Havia um lá, de 157 MB,
# de 06/08, gerado da produção `peca-02`. Qualquer `qc-cor` rodado desde
# então em OUTRA produção comparou a cor dela com a régua de outro vídeo, imprimiu
# porcentagens e não avisou ninguém.
#
# A correção NÃO é "avisar": é tornar a colisão estruturalmente impossível. O
# caminho da referência passa a CONTER a identidade do bruto (sha1 de caminho +
# bytes + mtime + duração). Duas produções não podem mais cair no mesmo arquivo,
# e trocar o bruto muda o caminho. O sidecar fica junto, legível, para quem for
# investigar. Fora do repo de propósito: são ~150 MB por produção, e a régua é
# derivada — se sumir, refaz.
def dir_ref():
    env = os.environ.get("BENCH_QC_REF_DIR")
    if env:
        return env
    import tempfile
    return os.path.join(tempfile.gettempdir(), "bench-qc-cor")


def _carimbo(bruto):
    try:
        st = os.stat(bruto)
    except OSError:
        return None
    return {"bruto": os.path.abspath(bruto), "bytes": st.st_size,
            "mtime": int(st.st_mtime), "duracao": round(duracao(bruto), 3)}


def ref_padrao(bruto):
    """Caminho da referência DERIVADO da identidade do bruto."""
    import hashlib
    c = _carimbo(bruto)
    if not c:
        return None
    chave = hashlib.sha1(
        ("%s|%d|%d|%.3f" % (c["bruto"], c["bytes"], c["mtime"], c["duracao"]))
        .encode()).hexdigest()[:16]
    return os.path.join(dir_ref(), chave, "ref-apple.mov")


def preparar_referencia(ref, bruto, P, explicito):
    """Devolve (caminho_utilizavel | None, motivo). NUNCA devolve uma referência
    de outra produção em silêncio."""
    side = os.path.splitext(ref)[0] + ".json"
    carimbo = _carimbo(bruto) if bruto and os.path.exists(bruto) else None

    if os.path.exists(ref):
        if explicito:
            # não sabemos de que bruto ela saiu; a duração é o que dá para conferir
            if carimbo and abs(duracao(ref) - carimbo["duracao"]) > 0.5:
                return None, ("🔴 --ref %s dura %.2fs e o bruto %s dura %.2fs. "
                              "Isto é a régua de OUTRO vídeo. Não vou comparar cor "
                              "com ela." % (ref, duracao(ref), bruto, carimbo["duracao"]))
            return ref, "referência informada por --ref (duração confere com o bruto)"
        gravado = None
        if os.path.exists(side):
            try:
                with open(side, encoding="utf-8") as fh:
                    gravado = json.load(fh)
            except (ValueError, OSError):
                gravado = None
        if gravado and carimbo and gravado.get("bruto") == carimbo["bruto"] \
                and gravado.get("bytes") == carimbo["bytes"] \
                and gravado.get("mtime") == carimbo["mtime"]:
            return ref, "referência em cache, do bruto desta produção"
        motivo = "sem sidecar de procedência" if not gravado else "o bruto mudou"
        print("  ⚠️ referência %s descartada (%s) — refazendo." % (ref, motivo),
              file=sys.stderr)

    if not carimbo:
        return None, ("bruto não encontrado (%s) — a fidelidade e o estágio por "
                      "pixel NÃO foram medidos." % bruto)

    # o preset do avconvert é nomeado pela ARESTA LONGA; derivá-lo da peça evita
    # gerar a referência num tamanho que não é o da entrega.
    preset = P.get("qc", {}).get("preset_referencia") or "Preset%dx%d" % (
        max(P["video"]["largura"], P["video"]["altura"]),
        min(P["video"]["largura"], P["video"]["altura"]))
    nome_ferramenta = "av" + "convert"
    executavel = shutil.which(nome_ferramenta)
    if not executavel:
        return None, ("%s indisponível nesta plataforma; a referência "
                      "Apple não foi medida (SKIP explícito, sem fallback "
                      "FFmpeg equivalente validado)" % nome_ferramenta)
    os.makedirs(os.path.dirname(ref) or ".", exist_ok=True)
    print("  gerando referência com avconvert (%s, ~1 min) em %s..." % (preset, ref),
          file=sys.stderr)
    try:
        proc = subprocess.run([executavel, "--source", bruto, "--output", ref,
                               "--preset", preset, "--replace"],
                              capture_output=True)
    except OSError as exc:
        return None, ("%s não pôde ser executado (%s); referência Apple "
                      "não medida" % (nome_ferramenta, exc.strerror or exc))
    if proc.returncode != 0:
        try:
            os.unlink(ref)
        except OSError:
            pass
        return None, ("%s falhou com exit %d; referência parcial removida "
                      "e fidelidade não medida" % (nome_ferramenta,
                                                     proc.returncode))
    if not os.path.exists(ref) or duracao(ref) <= 0:
        try:
            os.unlink(ref)
        except OSError:
            pass
        return None, "%s não produziu referência utilizável" % nome_ferramenta
    with open(side, "w", encoding="utf-8") as fh:
        json.dump({**carimbo, "preset": preset}, fh, indent=1)
    return ref, "referência recém-gerada do bruto desta produção"


# ─────────────────────────────────────────────────────────────────── o QC
def listar(so_entregaveis, P, n_segs):
    mp4s = sorted(f for f in os.listdir(".") if f.endswith(".mp4"))
    if so_entregaveis:
        ent = set(P.get("entregaveis") or [])
        mp4s = [f for f in mp4s if f in ent]
    segs = []
    if os.path.isdir("segs"):
        todos = sorted(os.path.join("segs", f) for f in os.listdir("segs")
                       if f.endswith(".mp4"))
        if n_segs and len(todos) > n_segs:
            passo = len(todos) / float(n_segs)
            segs = [todos[min(len(todos) - 1, int(i * passo))] for i in range(n_segs)]
        else:
            segs = todos
        return mp4s, (segs, len(todos), todos)
    return mp4s, ([], 0, [])


# Extensões de container que a câmera de bolso escreve. Ordem = preferência.
EXT_BRUTO = (".mov", ".mp4", ".m4v", ".mts", ".avi", ".mkv")


def tem_bruto(bruto):
    """`os.path.exists` que sobrevive a `bruto=None`.

    🔴 H47-5. `descobrir_bruto()` devolve `None` por contrato ("empate ou ausência
    devolve None, e aí o SKIP é honesto") e havia DOIS `os.path.exists(bruto)`
    crus lendo esse None — `TypeError: stat: path should be string […] not
    NoneType`, no meio de uma produção de cliente. Ausência de bruto é um caso
    NORMAL (produção sem o bruto guardado, layout ad-hoc): ela vira SKIP declarado
    aqui, não exceção três seções adiante."""
    return bool(bruto) and os.path.exists(bruto)


def descobrir_bruto(dir_input="input"):
    """O bruto da produção, por VARREDURA — nunca por nome cravado.

    🔴 Era `input/bruto.MP4`, um caminho fixo, e nenhuma produção deste repo tem
    um arquivo com esse nome: elas têm `take-conteudo.MOV`, `take-A.MOV`,
    `palestra.mp4`, `vsl-original.mp4`. Como a bateria de QC invoca este script
    SEM `--bruto`, o arquivo nunca existia, e o SKIP virou o caminho normal —
    metade das seções deixava de ser medida com o bruto ali, legível, ao lado.
    Um SKIP silencioso e permanente é indistinguível de um teste que passou.

    Critério: o MAIOR arquivo de vídeo em `input/`. O bruto é, por construção, o
    arquivo mais pesado da produção — takes cortados e provas de cor são menores.
    Empate ou ausência devolve None, e aí o SKIP é honesto.

    🔴 A VARREDURA DESCE (2026-08-12, H47-5). Ela olhava SÓ os filhos diretos de
    `input/`. Num fluxo real de cliente, medido no Linux por um agente externo, o
    bruto estava em `input/bruto/<arquivo>.mp4` — um subdiretório, o layout que a
    própria doc de ad-hoc sugere — e a função devolvia `None`. O `None` chegava
    cru em `os.path.exists(bruto)` e o QC morria de `TypeError` DEPOIS de imprimir
    "varreu 17": o defeito que o H47-1 pegou do outro lado. Descer até 3 níveis
    acha o bruto do cliente sem mudar o critério nem o resultado no nosso layout.
    """
    d = pathlib.Path(dir_input)
    if not d.is_dir():
        return None
    cands = []
    for f in d.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in EXT_BRUTO:
            continue
        # nada oculto, e nada dentro de diretório oculto (`.tmp/` de render)
        rel = f.relative_to(d)
        if any(p.startswith(".") for p in rel.parts):
            continue
        if len(rel.parts) > 3:
            continue
        cands.append(f)
    if not cands:
        return None
    maior = max(cands, key=lambda f: f.stat().st_size)
    return str(maior)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--autoteste":
        return autoteste(argv[1:])
    d = argv[0] if argv else "."
    args = argv[1:]

    def flag(nome, default=None):
        return args[args.index(nome) + 1] if nome in args else default

    ref_arg = flag("--ref")
    amostras = int(flag("--amostras", "24"))
    n_segs = int(flag("--segs", "4"))
    so_entregaveis = "--so-entregaveis" in args
    P = perfil_mod.carregar(d)
    os.chdir(d)
    # 🔴 A DESCOBERTA DO BRUTO ACONTECE DEPOIS DO chdir (2026-08-12, H47-5).
    # Antes ela rodava ANTES, e `descobrir_bruto()` varre o caminho relativo
    # `input/` — ou seja, o `input/` de quem CHAMOU, não o da produção. Medido
    # em 2026-08-12: rodando da raiz do repo sobre uma produção de teste, o QC
    # elegeu como "bruto" um arquivo do `input/` da RAIZ e imprimiu "SKIP — sem
    # bruto legível em input/<arquivo de outra peça>". Fora de um diretório com
    # `input/`, a mesma linha devolvia `None` — e era esse None que estourava
    # `TypeError` três seções depois, no Linux, na produção de um cliente.
    bruto = flag("--bruto") or descobrir_bruto()
    REGIOES = regioes_px(P)

    # ---------------------------------------------------- de onde vem o esperado
    cor = None
    caminho_cor = flag("--cor", "cor.json")
    if os.path.isfile(caminho_cor):
        try:
            with open(caminho_cor, encoding="utf-8") as fh:
                cor = json.load(fh)
        except (ValueError, OSError):
            cor = None
    cat = detect_cor.carregar_catalogo()

    if cor and cor.get("tags_saida"):
        t_pos, origem_pos = trio(cor["tags_saida"]), caminho_cor
    elif os.path.isfile("perfil.json"):
        t_pos, origem_pos = trio((P.get("cor") or {}).get("tags_saida")), "perfil.json"
    else:
        t_pos, origem_pos = trio((cat.get("saida") or {}).get("tags")), "catalogo-cor.json"

    if cor and cor.get("fonte"):
        t_pre, origem_pre = trio(cor["fonte"]), caminho_cor
    elif tem_bruto(bruto):
        t_pre, origem_pre = tags(bruto), "ffprobe no bruto"
    else:
        t_pre, origem_pre = None, ("—" if bruto else "sem bruto em input/")

    if cor is None:
        print("⚠️ sem %s nesta produção — o estágio é medido só pelos pixels e o "
              "rótulo esperado vem de %s / %s. Rode "
              "`detect-cor.py resolver <dir> --bruto <bruto>` para fechar o "
              "contrato." % (caminho_cor, origem_pre, origem_pos), file=sys.stderr)

    # SPEC-25: em que estágio da cadeia a conversão foi aplicada, segundo quem a
    # aplicou. `None` = ninguém declarou = comportamento da SPEC-11, intocado.
    aplicada_em = (cor or {}).get("aplicada_em")

    mp4s, (segs, segs_total, segs_todos) = listar(so_entregaveis, P, n_segs)

    # ══ 1. COERÊNCIA DE RÓTULO NA CADEIA — barato, e NÃO precisa de bruto ══════
    # O `montar.sh` monta o `v1-montado` por `concat -c copy` dos `segs/`: os
    # pixels do montado SÃO os pixels dos segmentos, bit a bit. Logo, qualquer
    # diferença de rótulo entre os dois é mentira POR CONSTRUÇÃO — não precisa de
    # referência, de avconvert nem de bruto para provar.
    #
    # É este teste que pega os 13 arquivos de 2026-08-06 22:59, inclusive nas
    # produções que não têm mais o bruto em `input/`. E é o mais barato de todos:
    # um ffprobe por arquivo, mais UM par de frames para confirmar no pixel.
    print("═══ 1. COERÊNCIA DE RÓTULO NA CADEIA (segs → montado) ═══")
    montados = [f for f in mp4s if f.startswith("v1-montado")]
    incoerentes = []
    if not segs_todos:
        print("  ⏭️ SKIP — esta produção não tem `segs/` (nada a comparar).")
    else:
        rotulos_seg = {}
        for f in segs_todos:
            rotulos_seg.setdefault(tags(f), []).append(f)
        if len(rotulos_seg) > 1:
            print("  ❌ os %d segmentos NÃO têm rótulo uniforme: %s"
                  % (len(segs_todos),
                     " · ".join("%s (%d)" % (fmt(t), len(v)) for t, v in rotulos_seg.items())))
            incoerentes.append(("segs/", None))
        rot_seg = max(rotulos_seg.items(), key=lambda kv: len(kv[1]))[0]
        print("  rótulo dos %d segmentos: %s" % (len(segs_todos), fmt(rot_seg)))
        amostra_seg = sorted(segs_todos)[0]
        for f in montados:
            rot = tags(f)
            bom = rot == rot_seg
            extra = ""
            if not bom:
                # confirma NO PIXEL que a diferença é só de rótulo
                a, b = frame(amostra_seg, 0.5), frame(f, 0.5)
                if a is not None and b is not None and a.shape == b.shape:
                    dif = np.abs(a - b)
                    extra = ("  │ pixels vs %s: máx %.0f/255 · média %.3f/255"
                             % (os.path.basename(amostra_seg), dif.max(), dif.mean()))
                incoerentes.append((f, rot))
            print("  %s %-34s %s%s" % ("✅" if bom else "❌", f, fmt(rot), extra))
        print("  varreu %d segmento(s) + %d montado(s) — %d incoerente(s)"
              % (len(segs_todos), len(montados), len(incoerentes)))

    # ══ 2. AVANÇO POR PIXEL — onde os pixels estão na conversão bruto→SDR ══════
    print("\n═══ 2. AVANÇO POR PIXEL (rótulo × pixel, por projeção) ═══")
    alvos_dist = [f for f in mp4s if f.startswith(PREFIXOS_AVANCO)]
    estagio, avancos = {}, {}
    ok_dist, mau_dist, n_dist = [], [], 0
    ref, motivo = (None, ("sem bruto legível em %s" % bruto) if bruto else
                   "esta produção não tem bruto de vídeo em `input/` (nem "
                   "`--bruto`): a fidelidade e o estágio por pixel NÃO foram "
                   "medidos — o teste 1 acima não depende deles")
    s_bruto = s_ref = None
    if tem_bruto(bruto):
        ref, motivo = preparar_referencia(
            ref_arg or ref_padrao(bruto), bruto, P, explicito=bool(ref_arg))
    if ref:
        s_bruto = detect_cor.stats8(bruto, amostras)
        s_ref = detect_cor.stats8(ref, amostras)
    vb = vr = None
    if not (s_bruto and s_ref):
        print("  ⏭️ SKIP — %s" % motivo)
        print("  este teste EXIGE o bruto (--bruto) e a referência avconvert. "
              "Sem eles não há verde: há SKIP. (O teste 1 acima não depende deles.)")
    else:
        vb, vr = vetor(s_bruto), vetor(s_ref)
        eixo = vr - vb
        sep = abs(float(eixo[I_SAT]))
        print("  bruto      bf %.4f · wc %.4f · sat %.4f   (%s)"
              % (s_bruto["black_floor"], s_bruto["white_ceiling"],
                 s_bruto["sat_mean"], bruto))
        print("  referência bf %.4f · wc %.4f · sat %.4f   (%s)"
              % (s_ref["black_floor"], s_ref["white_ceiling"], s_ref["sat_mean"], motivo))
        print("  eixo da conversão Δ = %s · Δsat = %.4f (mínimo %.3f) — a régua é SÓ o eixo de saturação"
              % (np.round(eixo, 4).tolist(), sep, SEPARACAO_MIN))
        if sep < SEPARACAO_MIN:
            print("  ⏭️ SKIP — bruto e referência estão a %.4f um do outro, abaixo do "
                  "mínimo. A régua não separa nada aqui; um veredito seria sorteio."
                  % sep)
        else:
            n2 = float(eixo @ eixo)
            print("  regra: t < %.2f ⇒ pixels PRÉ-conversão · t ≥ %.2f ⇒ PÓS"
                  % (LIMIAR_AVANCO, LIMIAR_AVANCO))
            for f in alvos_dist:
                s = detect_cor.stats8(f, amostras)
                if not s:
                    print("  ⏭️ %-34s estatística falhou" % f)
                    continue
                n_dist += 1
                v = vetor(s)
                t = projetar(v, vb, eixo, n2)
                avancos[f] = t
                estagio[f] = "pre" if t < LIMIAR_AVANCO else "pos"
                cs, ct, cp = tags(f)
                rot_hdr = ct in TRANSFERS_HDR or cp == "bt2020" or cs.startswith("bt2020")
                bom = (estagio[f] == "pre") if rot_hdr else (estagio[f] == "pos")
                (ok_dist if bom else mau_dist).append(f)
                # a razão euclidiana da spec fica impressa ao lado, para quem
                # for reconferir a §3.11: é ELA que não discrimina (ver o bloco
                # de comentário no topo deste arquivo).
                razao = (float(np.linalg.norm(v - vb)) /
                         max(float(np.linalg.norm(v - vr)), 1e-9))
                print("  %s %-34s bf %.4f wc %.4f sat %.4f │ t %+.3f → pixels %s │ "
                      "rótulo %s │ (razão euclid. da spec: %.2f)"
                      % ("✅" if bom else "❌", f, s["black_floor"],
                         s["white_ceiling"], s["sat_mean"], t, estagio[f],
                         "HDR" if rot_hdr else "SDR", razao))
            print("  varreu %d arquivo(s) — %d ok, %d reprovado(s). `segs/*` fora "
                  "deste teste DE PROPÓSITO: medido, t de segmento HLG (todos "
                  "comprovadamente pré-conversão) varia de −0,23 a +0,53, porque "
                  "segmento é crop curto de outro conteúdo e sat_mean acompanha o "
                  "conteúdo. Eles são cobertos pelo teste 1."
                  % (n_dist, len(ok_dist), len(mau_dist)))

    # ══════════════════ 3. TAGS, POR ESTÁGIO ══════════════════════════════════
    print("\n═══ 3. TAGS DE COR, por ESTÁGIO da cadeia ═══")
    print("  perfil %s · esperado pré-conversão %s (%s) · pós-conversão %s (%s)"
          % (P.get("nome", "?"), fmt(t_pre), origem_pre, fmt(t_pos), origem_pos))
    print("  cor.aplicada_em = %s  (%s)"
          % (aplicada_em or "ausente",
             {"extracao": "segs/* e v1-montado* são PÓS-conversão — SPEC-25",
              "passe": "segs/* e v1-montado* são PRÉ-conversão — passe separado",
              }.get(aplicada_em,
                    "ninguém declarou: estágio só por pixel, como na SPEC-11")))
    ruim_pos, ruim_pre, indef, contradiz = [], [], [], []
    n_tags = n_declarado = 0
    for f in mp4s + segs:
        cs, ct, cp = tags(f)
        atual = (cs, ct, cp)
        n_tags += 1
        est = estagio.get(f)
        dec = estagio_declarado(f, aplicada_em)
        if dec:
            n_declarado += 1
        # 🔴 pixel × declaração. Quando os dois existem e DISCORDAM, isso não é
        # detalhe: ou a montagem não converteu o que o plano disse que converteu,
        # ou alguém reprocessou o arquivo por fora. Acusar é obrigatório — foi
        # exatamente uma discordância dessas, não vista, que gerou os 6
        # entregáveis do creator-3.
        if est and dec and est != dec:
            contradiz.append((f, est, dec))
            print("  ❌ %-34s %s  │ pixels dizem %s, cor.json declara %s"
                  % (f, fmt(atual), est, dec))
            continue
        if est is None:
            est = dec
        if est is None:
            # sem medição de pixel só dá para exigir que o rótulo seja UM DOS DOIS
            # legítimos. É mais fraco — e é dito, não escondido.
            aceitos = [t for t in (t_pre, t_pos) if t]
            if not aceitos:
                print("  ⏭️ %-34s %s  (estágio não medido, esperado desconhecido)"
                      % (f, fmt(atual)))
                indef.append(f)
                continue
            bom = atual in aceitos
            if not bom:
                indef.append(f)
            print("  %s %-34s %s  (estágio NÃO medido — só confiro contra os dois "
                  "rótulos legítimos)" % ("✅" if bom else "⚠️", f, fmt(atual)))
            continue
        esperado = t_pre if est == "pre" else t_pos
        bom = esperado is not None and atual == esperado
        if not bom:
            (ruim_pre if est == "pre" else ruim_pos).append((f, atual))
        print("  %s %-34s %s  │ estágio %s (%s) ⇒ esperado %s"
              % ("✅" if bom else "❌", f, fmt(atual), est,
                 "pixel" if estagio.get(f) else "declarado", fmt(esperado)))
    print("  varreu %d arquivo(s) (%d com estágio declarado pelo cor.json, %d medido "
          "por pixel) — %d com rótulo do estágio errado, %d indefinido(s), "
          "%d pixel×declaração em contradição"
          % (n_tags, n_declarado, len(estagio), len(ruim_pre) + len(ruim_pos),
             len(indef), len(contradiz)))
    if contradiz:
        print("\n  🔴 O QUE O PLANO DE COR DIZ E O QUE OS PIXELS DIZEM NÃO BATEM:")
        for f, est, dec in contradiz:
            print("    · %-34s pixels %s · cor.json declara %s" % (f, est, dec))
        print("  Não retagueie. Descubra qual dos dois está errado: `montar.sh` "
              "grava `aplicada_em` ANTES do laço, então um render interrompido "
              "deixa parte dos segmentos convertida. Apagar `segs/` e remontar é "
              "mais barato que investigar.")

    # ---------------------------------------------------- sugestão de conserto
    # 🔴 SÓ quando o ESTÁGIO daquele arquivo PEDE bt709. Foi a sugestão cega da v1
    # — impressa para todo arquivo fora de bt709 — que criou os 13 arquivos
    # mal rotulados. Um QC que sugere conserto tem que saber o que o arquivo
    # DEVERIA ser.
    if ruim_pos:
        print("\n  🔴 PIXELS JÁ CONVERTIDOS com rótulo que não é o de saída — o "
              "player vai tone-mapear de novo um conteúdo que já é SDR.")
        print("  Correção SEM re-encode (o estágio destes arquivos PEDE %s):" % fmt(t_pos))
        for f, _ in ruim_pos:
            print("    ffmpeg -i %s -c copy -bsf:v h264_metadata="
                  "colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1 out.mp4"
                  % f)
    if ruim_pre:
        print("\n  🔴 PIXELS AINDA NÃO CONVERTIDOS carregando rótulo de saída — é o "
              "defeito de 2026-08-06 22:59, o simétrico. Os pixels destes arquivos "
              "estão no domínio do BRUTO; o rótulo diz que já são Rec.709.")
        for f, atual in ruim_pre:
            print("    · %-34s tem %s, os pixels são %s (avanço t %+.3f)"
                  % (f, fmt(atual), fmt(t_pre), avancos.get(f, float("nan"))))
        print("  ⚠️ NÃO imprimo comando aqui, DE PROPÓSITO. Foi colar o comando "
              "sugerido e rodar em lote que criou o defeito. Estes são "
              "intermediários: decida arquivo a arquivo, e prefira remontar a "
              "retaguear. A regra do repo: produção publicada não se re-renderiza "
              "e não se altera em lote.")

    # ══════════════════ 4. FIDELIDADE AO ORIGINAL (referência Apple) ═══════════
    print("\n═══ 4. FIDELIDADE AO ORIGINAL (referência Apple/Edits) ═══")
    if not ref:
        print("  ⏭️ SKIP — %s. A fidelidade NÃO foi medida (nada a comparar)." % motivo)
        return 1 if (ruim_pre or ruim_pos or mau_dist or incoerentes or contradiz) else 0
    alvos = [f for f in mp4s if f.startswith(("v1-", "v-final"))]
    dur_ref = duracao(ref)
    TS_ref = instantes(P, dur_ref)
    print("  amostras: %d instantes em %.1fs de referência (%s)"
          % (len(TS_ref), dur_ref, ", ".join("%.1f" % t for t in TS_ref)),
          file=sys.stderr)
    lum_primeira_regiao = {}
    for k, (nome, reg) in enumerate(REGIOES.items()):
        base = np.array([metricas(frame(ref, t)[reg]) for t in TS_ref
                         if frame(ref, t) is not None]).mean(axis=0)
        print("\n  %s   (referência: lum %.1f · sat %.1f · R/B %.3f)"
              % (nome, base[0], base[1], base[2]))
        for f in alvos:
            TS = instantes(P, duracao(f))
            fr = [frame(f, t) for t in TS]
            X = np.array([metricas(x[reg]) for x in fr if x is not None]).mean(axis=0)
            dl, ds, dr_ = [(X[i] / base[i] - 1) * 100 for i in range(3)]
            if k == 0:
                lum_primeira_regiao[f] = dl
            # o preset do creator PODE escurecer de propósito; o que não pode é
            # a conversão HDR->SDR errar. Por isso o alerta é só no v1-sdr.
            flag_ = "  ⚠️ a LUT deveria bater <2%" if f.startswith("v1-sdr") and abs(dl) > 2 else ""
            print("    %-34s lum %+6.1f%% · sat %+6.1f%% · R/B %+5.1f%%%s"
                  % (f, dl, ds, dr_, flag_))
        print("  varreu %d arquivo(s) nesta região" % len(alvos))

    # ══════════════════ 5. LUT APLICADA DUAS VEZES ════════════════════════════
    # O modo de falha NOVO que a conversão na extração cria: todo script de
    # produção que hoje converte (`cor.py:23,47`, os dois `montar-tudo.sh`) passa
    # a rodar sobre um montado JÁ convertido. Assinatura medida: −23,7% de
    # luminância. Ver o bloco de comentário do topo para por que este teste NÃO
    # roda em arquivo com look — lá o preset legítimo mede −20,6%.
    print("\n═══ 5. LUT APLICADA DUAS VEZES (só nos alvos SEM look) ═══")
    sem_look = [f for f in alvos if f.startswith(SEM_LOOK)]
    com_look = [f for f in alvos if not f.startswith(SEM_LOOK)]
    dupla = []
    if not sem_look:
        print("  ⏭️ SKIP — nenhum alvo sem look (%s) nesta pasta. O teste não roda "
              "em arquivo com grade: o preset do creator mede −20,6%% legítimo "
              "contra a referência, e o limiar é −15%%." % "|".join(SEM_LOOK))
    else:
        for f in sem_look:
            dl = lum_primeira_regiao.get(f)
            if dl is None:
                print("  ⏭️ %-34s sem medição de luminância" % f)
                continue
            est = estagio.get(f) or estagio_declarado(f, aplicada_em)
            if est != "pos":
                print("  ⏭️ %-34s lum %+6.1f%% — estágio %s, ainda não convertido "
                      "(nada a dobrar)" % (f, dl, est or "?"))
                continue
            if dl < LIMIAR_LUT_DUPLA:
                dupla.append((f, dl))
            print("  %s %-34s lum %+6.1f%%  (limiar %+.0f%%)"
                  % ("❌" if dl < LIMIAR_LUT_DUPLA else "✅", f, dl, LIMIAR_LUT_DUPLA))
        print("  varreu %d arquivo(s) sem look — %d suspeito(s) de conversão dupla. "
              "%d arquivo(s) com look ficaram FORA (%s): ali o −20,6%% do preset e "
              "o −23,7%% da LUT dupla se sobrepõem e o teste seria sorteio."
              % (len(sem_look), len(dupla), len(com_look),
                 ", ".join(com_look) or "nenhum"))
    if dupla:
        print("\n  🔴 POSSÍVEL CONVERSÃO APLICADA DUAS VEZES "
              "(cor.aplicada_em = %s):" % (aplicada_em or "ausente"))
        for f, dl in dupla:
            print("    · %-34s lum %+.1f%% contra a referência avconvert "
                  "(assinatura medida da LUT dupla: −23,7%%)" % (f, dl))
        print("  Com `aplicada_em: \"extracao\"` o `v1-montado` JÁ É o que se "
              "chamava `v1-sdr`. Um script de produção que aplique a LUT de novo "
              "sobre ele converte duas vezes. Confira `cor.aplicada_em` antes de "
              "rodar qualquer passe de cor sobre o montado.")

    return 1 if (ruim_pre or ruim_pos or mau_dist or incoerentes or contradiz
                 or dupla) else 0


# ═══════════════════════════════════════════════════ controle negativo (§7.9)
def autoteste(argv):
    """Planta o defeito nas DUAS direções e confere que a régua ACUSA cada uma.

    Sem isto, "varredura limpa" e "o teste não rodou" são indistinguíveis — e
    esta produção já teve um QC que se auto-neutralizou e imprimiu verde. Um
    portão que varre 0 e sai 0 é igual a um portão quebrado.

      A) pixels do BRUTO com rótulo SDR  → o defeito de 06/08 22:59, o dos 13
      B) pixels SDR com rótulo HDR       → o defeito de 06/08 22:57, o que
                                            fez este script nascer
      C) controle POSITIVO: os dois casos certos NÃO podem ser acusados. Sem
         este terceiro caso, uma régua que reprova tudo passaria no autoteste.

    uso: qc-cor.py --autoteste <bruto> <referencia-ou-convertido>
    """
    bruto = argv[0] if len(argv) > 0 else None
    sdr = argv[1] if len(argv) > 1 else None
    if not (bruto and sdr and os.path.exists(bruto) and os.path.exists(sdr)):
        print("uso: qc-cor.py --autoteste <bruto> <ja-convertido>", file=sys.stderr)
        return 64
    s_b, s_r = detect_cor.stats8(bruto, 24), detect_cor.stats8(sdr, 24)
    if not (s_b and s_r):
        print("❌ estatística falhou — o autoteste NÃO rodou", file=sys.stderr)
        return 1
    vb, vr = vetor(s_b), vetor(s_r)
    eixo = vr - vb
    sep = abs(float(eixo[I_SAT]))
    n2 = float(eixo @ eixo)
    print("  eixo da conversão Δsat = %.4f (mínimo %.3f)" % (sep, SEPARACAO_MIN))
    if sep < SEPARACAO_MIN:
        print("❌ bruto e convertido não se separam — o autoteste NÃO rodou")
        return 1

    def avanco(arquivo):
        return projetar(vetor(detect_cor.stats8(arquivo, 24)), vb, eixo, n2)

    falhas = 0
    for nome, arquivo, rot_hdr, deve_acusar in (
            ("A· pixels do BRUTO com rótulo SDR", bruto, False, True),
            ("B· pixels SDR com rótulo HDR", sdr, True, True),
            ("C+ pixels do bruto com rótulo HDR (certo)", bruto, True, False),
            ("C+ pixels SDR com rótulo SDR (certo)", sdr, False, False)):
        t = avanco(arquivo)
        est = "pre" if t < LIMIAR_AVANCO else "pos"
        acusou = (est != "pre") if rot_hdr else (est != "pos")
        ok = acusou == deve_acusar
        falhas += 0 if ok else 1
        print("  %s %-42s t %+.3f (%s) → %s (esperado: %s)"
              % ("✅" if ok else "❌", nome, t, est,
                 "ACUSA" if acusou else "aprova",
                 "acusar" if deve_acusar else "aprovar"))
    print("controle negativo: %d/4 casos — 2 defeitos plantados, 2 controles "
          "positivos" % (4 - falhas))
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
