#!/usr/bin/env python3
"""loudness.py — o ÚNICO lugar onde loudness é decidido (SPEC-02).

    O alvo de loudness NÃO tem default. Ele vem do perfil de peça (SPEC-00,
    bloco `audio.loudness`), de uma referência medida, ou de flag explícita.
    Sem nenhum dos três este script sai 2 e não escreve nada. Um número de
    loudness inventado é o defeito que esta spec existe para matar.

POR QUE ELE EXISTE (medido em 2026-08-08, `ffmpeg 8.0.1` + `ebur128=peak=true`)

O `loudnorm` de passe ÚNICO dentro do `filter_complex` da composição não atinge
o alvo — ele estima em tempo real e erra sempre para BAIXO. Nos seis entregáveis
que saíram por esse caminho:

    creator-3/peca-10-27-07/a-comando      alvo -16,0   medido -17,7   erro 1,7 LU
    creator-3/peca-10-27-07/b-conselheiro  alvo -16,0   medido -17,5   erro 1,5 LU
    creator-3/peca-10-27-07/c-16anos       alvo -16,0   medido -18,0   erro 2,0 LU
    creator-1/peca-11/r1-os-bons    alvo -14,0   medido -15,8   erro 1,8 LU
    creator-1/peca-11/r5-refem      alvo -14,0   medido -15,6   erro 1,6 LU
    creator-1/peca-11/L2-os-bons…   alvo -14,0   medido -15,9   erro 1,9 LU

Seis de seis abaixo do alvo, média 1,75 LU, nunca acima. O próprio ffmpeg
denuncia no passe 1: ele imprime `output_i` (a simulação do que o passe único
vai entregar) e `target_offset` (a correção que o segundo passe aplicaria). A
informação para acertar já existia; nós só não a usávamos.

Nenhum dos QCs do repo mede loudness. O erro saiu seis vezes sem um alerta.

MODOS
    --medir        mede e imprime JSON; não escreve mídia
    --normalizar   2 passes de verdade → --out
    --verificar    QC: mede a entrada contra o alvo, exit 1 se fora
    --teto <dBTP>  só limitador de pico, `-c:v copy`, sem tocar no loudness

⚠️ PRODUTO, NÃO INSTALAÇÃO. Este script lê exatamente dois tipos de caminho: os
que chegam por argumento e o catálogo de perfis (via perfil.py, relativo a ele
mesmo). Nunca `creators/`, nunca `LINHA-EDITORIAL.md`, nunca caminho absoluto
desta máquina. Traduzir "o nível do creator" em número é trabalho de quem chama.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import perfil as _perfil                                        # noqa: E402

CONTRATO = "benchmark.loudness/v1"

# --------------------------------------------------------------------- FÍSICA
# Estes números descrevem a PRECISÃO DO MEDIDOR e a RECEITA DO LIMITADOR, não o
# formato da peça. A regra da SPEC-00 é explícita: valor de formato (dimensão,
# fps, sample rate, alvo de loudness) vem do perfil; física fica no script.
#
# TOLERANCIA_LUFS_PADRAO 0,5 LU — o `ebur128` deste build reporta com uma casa
# decimal, e o passe 2 linear converge a ~0,1 LU. 0,5 dá folga de 5 leituras do
# medidor e ainda reprova os 1,75 LU do defeito. Sobrescritível por
# `--tolerancia-lufs` e por `audio.tolerancia_lufs` no perfil, se algum dia
# alguém quiser apertar por tipo de peça.
TOLERANCIA_LUFS_PADRAO = 0.5
TOLERANCIA_TP_PADRAO = 0.1

# Receita do limitador de teto, medida em SKILL.md:93 (I −14,99 antes e −14,99
# depois; TP −0,58 → −1,48). `limit` NÃO está aqui: sai de 10**(alvo_tp/20).
LIMITER_ATTACK_MS = 4
LIMITER_RELEASE_MS = 60

# Deriva de A/V: o `montar.sh:6-14` documenta o bug que existiu em todas as
# montagens até 2026-07-25. `soma_audio == soma_video` é invariante do pipeline,
# então este script não pode encurtar nem esticar a trilha.
#
# 📏 MEDIDO em 2026-08-08 neste build, e é por isso que o limiar é apertado:
#   PCM → PCM  (o caminho canônico, mix.wav → mix-norm.wav):  Δ = 0,000 ms
#   AAC → *    (o caminho --midia, sobre v-final.mp4 pronto): Δ = +16,0 ms
# A causa NÃO é o loudnorm: é o padding do AAC. `duration_ts` foi de 288000 para
# 288768 amostras (+768) num clipe de 6 s, com o stream de VÍDEO byte a byte
# idêntico (md5 igual, `-c:v copy`). Reencodar áudio AAC devolve o quadro
# completo que o contêiner declarava truncado.
#
# 🆕 2026-08-12 (H47-2), medido ao construir o controle de truncamento: o padding
# do AAC já está DENTRO do arquivo. O contêiner declara 6,000 s e o decoder
# entrega 288.768 amostras (6,016 s) — é o header que desconta (gapless). Logo,
# comparar CONTAGEM DE AMOSTRA entre o AAC e o WAV dá Δ 0,000 ms e some com uma
# deriva que é real na timeline. Por isso `_conferir_deriva` usa as duas réguas
# (header e amostra) e reprova se qualquer uma estourar.
#
# Por isso o default REPROVA o caminho --midia em vez de disfarçá-lo. `-shortest`
# resolveria o sintoma e é exatamente o que a armadilha 8 proíbe; um `-t` com a
# duração da entrada seria a mesma máscara com outro nome. Quem precisa migrar um
# entregável pronto sobe o limiar À MÃO (`--deriva-max-ms 25`) e assina a decisão.
DERIVA_MAX_MS_PADRAO = 1.0

# Ganho acima disto sobe a sibilância junto (clean-audio/SKILL.md:29). A partir
# daqui um aviso não basta: aplicar muda audivelmente o material e a decisão tem
# que sobreviver à sessão. `--autorizar-ganho-alto <motivo>` assina a escolha no
# sidecar. Sem a assinatura, o passe 1 pode medir, mas nenhuma mídia é escrita.
# O loudness.py continua sem aplicar de-esser, denoise ou qualquer limpeza por
# conta própria.
GANHO_EXIGE_DECISAO_DB = 6.0
GANHO_AVISA_DB = GANHO_EXIGE_DECISAO_DB       # nome antigo, para imports existentes

EXT_WAV = (".wav",)
EXT_MIDIA = (".mp4", ".mov", ".m4a", ".mkv", ".aac")


class Erro(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


# ----------------------------------------------------------------- utilidades
def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise Erro("ffmpeg não encontrado no PATH", 3)
    return exe


def _ffprobe():
    exe = shutil.which("ffprobe")
    if not exe:
        raise Erro("ffprobe não encontrado no PATH", 3)
    return exe


def _versao_ffmpeg():
    out = _run([_ffmpeg(), "-version"]).stdout.splitlines()
    m = re.search(r"ffmpeg version (\S+)", out[0] if out else "")
    return m.group(1) if m else "?"


def _probe_audio(caminho):
    """Descreve a PRIMEIRA trilha de áudio. Nada aqui vira default de formato —
    serve para preservar o que já existe quando não há perfil, e para conferir
    a deriva de duração."""
    r = _run([_ffprobe(), "-v", "error", "-select_streams", "a:0",
              "-show_entries", "stream=channels,sample_rate,codec_name,bit_rate,duration",
              "-show_entries", "format=duration", "-of", "json", caminho])
    if r.returncode != 0:
        raise Erro("ffprobe falhou em %s:\n%s" % (caminho, r.stderr.strip()), 3)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise Erro("ffprobe devolveu JSON inválido para %s" % caminho, 3)
    fluxos = d.get("streams") or []
    if not fluxos:
        raise Erro("%s não tem trilha de áudio" % caminho, 3)
    s = fluxos[0]
    fmt = d.get("format") or {}

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    return {
        "canais": int(s["channels"]),
        "sr": int(s["sample_rate"]),
        "codec": s.get("codec_name"),
        "bitrate": s.get("bit_rate"),
        "dur_stream": _f(s.get("duration")),
        "dur_format": _f(fmt.get("duration")),
    }


def _duracao_audio(caminho):
    p = _probe_audio(caminho)
    return p["dur_stream"] if p["dur_stream"] is not None else p["dur_format"]


def _tem_video(caminho):
    r = _run([_ffprobe(), "-v", "error", "-select_streams", "v",
              "-show_entries", "stream=codec_type", "-of", "csv=p=0", caminho])
    return bool(r.stdout.strip())


# ------------------------------------------------------------------ medição A
def medir_loudnorm(entrada, alvo, pre=""):
    """Passe 1: o JSON do próprio `loudnorm`. É a fonte de `input_tp` (true peak
    com oversampling 4×) usada para DECIDIR linear × dinâmico."""
    af = _cadeia(pre, "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json"
                 % (_n(alvo["i"]), _n(alvo["tp"]), _n(alvo["lra"])))
    r = _run([_ffmpeg(), "-nostdin", "-hide_banner", "-vn", "-i", entrada,
              "-af", af, "-f", "null", "-"])
    err = r.stderr
    if "{" not in err or "}" not in err:
        raise Erro("loudnorm não devolveu JSON em %s (rc=%d):\n%s"
                   % (entrada, r.returncode, err[-2000:]), 3)
    bruto = err[err.rindex("{"):err.rindex("}") + 1]
    try:
        st = json.loads(bruto)
    except json.JSONDecodeError:
        raise Erro("JSON do loudnorm ilegível: %s" % bruto[:400], 3)
    out = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh",
              "output_i", "output_tp", "output_lra", "output_thresh",
              "target_offset"):
        v = st.get(k)
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = None
    faltando = [k for k in ("input_i", "input_tp", "input_lra", "input_thresh",
                            "target_offset") if out[k] is None]
    if faltando:
        raise Erro("passe 1 sem os campos %s — medição inutilizável" % ", ".join(faltando), 3)
    out["normalization_type"] = st.get("normalization_type")
    return out


# ------------------------------------------------------------------ medição B
_RE_I = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.M)
_RE_LRA = re.compile(r"^\s*LRA:\s*(-?\d+(?:\.\d+)?)\s*LU", re.M)
_RE_TP = re.compile(r"True peak:.*?^\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS",
                    re.M | re.S)


def medir_ebur128(caminho):
    """Passe de VERIFICAÇÃO, sobre o ARQUIVO, sem cadeia de filtro nenhuma.

    🔴 Duas armadilhas já pagas neste repo, ambas fechadas aqui:

    1. O `ebur128` imprime uma linha de progresso a cada 100 ms com os MESMOS
       rótulos `I:` e `LRA:` do bloco final. Parsear o stderr inteiro lê valor
       parcial — custou um `LRA: 0,0` numa rodada
       (`peca-02/audio-candidatos.py:18-20`). Por isso o stderr é cortado
       em `Summary:` ANTES de qualquer regex.
    2. Medir ATRAVÉS de uma cadeia de filtros reporta o TP do sinal filtrado, e
       o `highpass=f=80` SOBE o pico (+1,5 dB medido, porque tira energia
       sub-80 Hz que cancelava parte da forma de onda). Foi assim que se leu
       "+0,04 dBTP" num arquivo que estava a −1,49
       (`peca-01/audio-vias.py:33-37`). Aqui nunca entra `--pre`.
    """
    r = _run([_ffmpeg(), "-nostdin", "-hide_banner", "-vn", "-i", caminho,
              "-af", "ebur128=peak=true", "-f", "null", "-"])
    err = r.stderr
    if "Summary:" not in err:
        raise Erro("ebur128 não imprimiu Summary em %s (rc=%d):\n%s"
                   % (caminho, r.returncode, err[-2000:]), 3)
    s = err[err.rindex("Summary:"):]
    mi, ml, mt = _RE_I.search(s), _RE_LRA.search(s), _RE_TP.search(s)
    if not (mi and ml and mt):
        raise Erro("Summary do ebur128 ilegível em %s:\n%s" % (caminho, s[:800]), 3)
    p = _probe_audio(caminho)
    return {"i": float(mi.group(1)), "lra": float(ml.group(1)),
            "tp": float(mt.group(1)), "canais": p["canais"], "sr": p["sr"]}


# ------------------------------------------------------------------- cadeias
def _n(x):
    """Inteiro em float vira inteiro na string do filtro — a forma com casa
    decimal muda a string do `af` e, com ela, qualquer md5 de regressão."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _cadeia(*partes):
    return ",".join(p for p in partes if p)


def _filtro_canais(canais_entrada, canais_saida):
    """A conversão de canais entra ANTES da medição. É a armadilha 1 da §9.

    🔴 O EBU R128 SOMA a energia dos canais. Normalizar em estéreo e só então
    fazer `-ac 1` entrega um mono ~3 LU abaixo do alvo, porque o loudnorm mirou
    o alvo no estéreo. Medido em `peca-02/audio-candidatos.py:12-16`;
    custou 5 rodadas. O caminho inverso (mono duplicado para estéreo) erra 3 LU
    para o outro lado pelo mesmo motivo — por isso as DUAS direções passam aqui.
    """
    if canais_saida == canais_entrada:
        return ""
    if canais_saida == 1:
        if canais_entrada == 2:
            return "pan=mono|c0=0.5*c0+0.5*c1"
        return "aformat=channel_layouts=mono"
    if canais_saida == 2:
        return "aformat=channel_layouts=stereo"
    raise Erro("canais de saída %r não suportado (1 ou 2)" % canais_saida)


# -------------------------------------------------------------------- perfil
def carregar_perfil(ref):
    """`--perfil` aceita nome do catálogo, arquivo .json ou diretório de produção.

    Delega TUDO ao perfil.py — não existe segunda leitura do formato neste repo.
    """
    if os.path.isdir(ref):
        return _perfil.carregar(ref)
    if os.path.isfile(ref) and ref.endswith(".json"):
        p = _perfil._ler(ref)
        if _perfil.e_camada_do_catalogo(ref) and not os.path.basename(ref).startswith("_"):
            p = _perfil.sobre_base(p)
        return p
    arq = os.path.join(_perfil.DIR_PERFIS, ref + ".json")
    if not os.path.isfile(arq):
        disponiveis = sorted(f[:-5] for f in os.listdir(_perfil.DIR_PERFIS)
                             if f.endswith(".json") and not f.startswith("_"))
        raise Erro("perfil %r não existe em %s (tem: %s). Também aceito caminho "
                   "de .json ou de diretório de produção."
                   % (ref, _perfil.DIR_PERFIS, ", ".join(disponiveis)))
    return _perfil.sobre_base(_perfil._ler(arq))


def _audio_do_perfil(p):
    a = (p or {}).get("audio") or {}
    ld = a.get("loudness") or {}
    return a, ld


# --------------------------------------------------------- resolução do alvo
def resolver_alvo(args, entrada, exigir=("i", "tp", "lra")):
    """Ordem de precedência (§3.5): flags > --perfil > --referencia > exit 2.

    `exigir` diz quais campos são obrigatórios NESTE modo: `--normalizar` precisa
    dos três (o filtro `loudnorm` não roda sem eles), `--verificar` precisa só do
    integrado — pedir LRA para medir um entregável seria burocracia.

    O passo final é a REGRA ARQUITETURAL, não uma inconveniência. O ref-A tem
    `LOUDNORM_I` cravado em −14,0 (`render.py:828`) e para eles funciona porque o
    produto tem duas trilhas e ambas vão para feed. Para nós fixo está errado
    por três motivos MEDIDOS: peça orgânica segue o nível do creator (as do
    creator-1 vivem a −24,4 LUFS) e anúncio vai a −16 — 8 LU de distância; VSL usa
    LRA 11 e criativo de 30 s usa LRA 7; e o nosso teto é −1,5 dBTP, não −1,0,
    porque o `amix` dos SFX sobe o pico DEPOIS da normalização.
    """
    p = carregar_perfil(args["perfil"]) if args["perfil"] else None
    a, ld = _audio_do_perfil(p)

    fontes = {}
    alvo = {"i": None, "tp": None, "lra": None}

    # 2. perfil
    for chave, campo in (("i", "I"), ("tp", "TP"), ("lra", "LRA")):
        v = ld.get(campo)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            alvo[chave] = float(v)
            fontes[chave] = "perfil:%s" % (p.get("nome") or args["perfil"])
        elif isinstance(v, str) and v.strip().lower() == "creator":
            fontes[chave] = "perfil:creator (exige --referencia ou --alvo-%s)" % chave

    # 3. referência: só preenche o que o perfil não cravou em número
    if args["referencia"]:
        if not os.path.isfile(args["referencia"]):
            raise Erro("--referencia não existe: %s" % args["referencia"])
        if alvo["i"] is None:
            m = medir_ebur128(args["referencia"])
            alvo["i"] = m["i"]
            fontes["i"] = "referencia:%s" % args["referencia"]
            if alvo["lra"] is None:
                alvo["lra"] = m["lra"]
                fontes["lra"] = "referencia:%s" % args["referencia"]

    # 1. flags explícitas vencem tudo
    for chave, flag in (("i", "alvo_i"), ("tp", "alvo_tp"), ("lra", "alvo_lra")):
        if args[flag] is not None:
            alvo[chave] = float(args[flag])
            fontes[chave] = "flag:--%s" % flag.replace("_", "-")

    if alvo["i"] is None:
        raise Erro(
            "ALVO DE LOUDNESS NÃO RESOLVIDO — e ele não tem default.\n"
            "  Dê UM destes:\n"
            "    --perfil <nome|caminho>   bloco `audio.loudness` do perfil de peça\n"
            "    --alvo-i <LUFS>           alvo explícito\n"
            "    --referencia <arquivo>    o alvo é o integrado medido nesse arquivo\n"
            "  Perfis do catálogo: %s\n"
            "  Por quê: peça orgânica segue o nível do creator (−24,4 LUFS medido no "
            "creator-1) e anúncio vai a −16. Um número embutido aqui quebraria um dos dois."
            % ", ".join(sorted(f[:-5] for f in os.listdir(_perfil.DIR_PERFIS)
                               if f.endswith(".json") and not f.startswith("_"))))
    if alvo["tp"] is None and "tp" in exigir:
        raise Erro("alvo de TRUE PEAK não resolvido: dê --alvo-tp ou use --perfil. "
                   "Sem teto de pico o loudnorm pode entregar o integrado certo e "
                   "clipar no player (medido: bruto do iPhone chegou a +1,4 dBFS).")
    if alvo["lra"] is None and "lra" in exigir:
        raise Erro("alvo de LRA não resolvido: dê --alvo-lra ou use --perfil. "
                   "LRA é escolha de dinâmica da peça (VSL 11, criativo de 30 s 7), "
                   "não constante global.")

    # canais / sr / codec / bitrate: formato, sempre do perfil quando ele existe
    ent = _probe_audio(entrada)
    canais = _canais_alvo(args["canais"], a, ent)
    sr = int(a["sr"]) if isinstance(a.get("sr"), int) else ent["sr"]
    fontes["canais"] = ("flag:--canais" if args["canais"] else
                        ("perfil" if a.get("canais") else "entrada"))
    fontes["sr"] = "perfil" if isinstance(a.get("sr"), int) else "entrada"

    tol_i = args["tol_i"] if args["tol_i"] is not None else \
        _num_ou(a.get("tolerancia_lufs"), TOLERANCIA_LUFS_PADRAO)
    tol_tp = args["tol_tp"] if args["tol_tp"] is not None else \
        _num_ou(a.get("tolerancia_tp"), TOLERANCIA_TP_PADRAO)

    passes = args["passes"] if args["passes"] is not None else \
        (a["passes_loudnorm"] if isinstance(a.get("passes_loudnorm"), int) else 2)

    return {
        "i": alvo["i"], "tp": alvo["tp"], "lra": alvo["lra"],
        "canais": canais, "sr": sr,
        "codec": a.get("codec"), "bitrate": a.get("bitrate"),
        "passes": passes, "tol_i": tol_i, "tol_tp": tol_tp,
        "perfil": (p.get("nome") if p else None),
        "fontes": fontes, "entrada_probe": ent,
    }


def _num_ou(v, padrao):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else padrao


def _canais_alvo(flag, bloco_audio, ent):
    if flag == "mono":
        return 1
    if flag == "estereo":
        return 2
    if flag == "manter":
        return ent["canais"]
    if isinstance(bloco_audio.get("canais"), int):
        return int(bloco_audio["canais"])
    return ent["canais"]


# ------------------------------------------------------------------- decisão
def decidir_modo(passe1, alvo, modo_pedido):
    """linear × dinâmico, decidido AQUI e nunca delegado ao ffmpeg.

    🔴 Armadilha 3, e nós já a sofremos. O ref-A monta o passe 2 com
    `:linear=true` SEMPRE (`render.py:957`), sem olhar o `input_tp` que ele
    acabou de medir e imprimir em `:947`. Quando o material chega com true peak
    positivo não existe ganho linear que alcance o alvo sem estourar, e o ffmpeg
    DESISTE de baixar o TP: medido neste repo, saída a +0,04 dBTP onde se pediu
    −1,5 (`peca-01/audio-vias.py:47-50`, que por isso omite o `linear` de
    propósito). O fallback automático do ffmpeg existe, mas o caso medido acima é
    justamente um em que ele NÃO caiu para dinâmico sozinho.
    """
    ganho = alvo["i"] - passe1["input_i"]
    tp_previsto = passe1["input_tp"] + ganho
    if modo_pedido == "linear":
        usar_linear = True
        motivo = ("--modo linear forçado; tp_previsto %.2f vs alvo_tp %.2f"
                  % (tp_previsto, alvo["tp"]))
        if tp_previsto > alvo["tp"]:
            motivo += " ⚠️ previsão ESTOURA o teto — o ffmpeg pode não baixar o TP"
    elif modo_pedido == "dinamico":
        usar_linear = False
        motivo = "--modo dinamico forçado"
    elif tp_previsto <= alvo["tp"]:
        usar_linear = True
        motivo = ("tp_previsto %.2f <= alvo_tp %.2f: ganho linear cabe"
                  % (tp_previsto, alvo["tp"]))
    else:
        usar_linear = False
        motivo = ("tp_previsto %.2f > alvo_tp %.2f: nenhum ganho linear alcança o "
                  "alvo sem estourar" % (tp_previsto, alvo["tp"]))
    return {"ganho_linear_db": round(ganho, 2),
            "ganho_linear_db_exato": ganho,
            "tp_previsto": round(tp_previsto, 2),
            "modo": "linear" if usar_linear else "dinamico", "motivo": motivo}


def decidir_ganho_alto(decisao_modo, autorizacao):
    """Bloqueia ganho positivo > 6 dB sem uma decisão humana auditável.

    O passe 1 já mediu o sinal, então este portão conhece o ganho antes de o
    ffmpeg escrever qualquer saída. A autorização é texto, não booleano: `sim`
    perdido no histórico não explica quem aceitou subir sibilância e piso junto
    com a fala. O texto é preservado byte a byte no sidecar.

    Este portão não "corrige" o material. De-esser, denoise e limpeza continuam
    fora deste script e exigem a via própria/A-B descrita em clean-audio.
    """
    ganho = float(decisao_modo.get("ganho_linear_db_exato",
                                    decisao_modo["ganho_linear_db"]))
    exigida = ganho > GANHO_EXIGE_DECISAO_DB
    motivo = autorizacao.strip() if isinstance(autorizacao, str) else None
    if exigida and not motivo:
        raise Erro(
            "GANHO ALTO EXIGE DECISÃO: o passe 1 mediu +%.1f dB, acima do limiar "
            "de %.1f dB. Nenhuma mídia foi publicada.\n"
            "  Escolha uma via auditável:\n"
            "    1. compare A/B pela clean-audio e trate a fonte antes; ou\n"
            "    2. se decidiu manter a fonte como está, repita com\n"
            "       --autorizar-ganho-alto \"<quem decidiu e por quê>\"\n"
            "  O loudness.py não aplica de-esser nem denoise automaticamente."
            % (ganho, GANHO_EXIGE_DECISAO_DB), 2)
    return {
        "limiar_db": GANHO_EXIGE_DECISAO_DB,
        "ganho_medido_db": round(ganho, 2),
        "exigida": exigida,
        "autorizada": bool(motivo) if exigida else None,
        "fonte": "flag:--autorizar-ganho-alto" if motivo else None,
        "justificativa": motivo,
        "processamento_automatico": [],
    }


# ------------------------------------------------------------- escrita/encode
def _opcoes_saida(saida, alvo, entrada, tem_video):
    ext = os.path.splitext(saida)[1].lower()
    if ext in EXT_WAV:
        # PCM: nada de bitrate, nada de vídeo. `-ar` explícito é OBRIGATÓRIO —
        # o loudnorm resampleia para 192 kHz internamente e o wav sai a 192 kHz
        # se ninguém forçar (clean-audio/SKILL.md:31). Este repo tem
        # audio-exato.py fazendo aritmética de amostras: um sr surpresa vira
        # deriva de A/V.
        return ["-vn", "-c:a", "pcm_s24le", "-ar", str(alvo["sr"]),
                "-ac", str(alvo["canais"]), saida]
    if ext not in EXT_MIDIA:
        raise Erro("extensão de saída %r não suportada (use %s ou %s)"
                   % (ext, ", ".join(EXT_WAV), ", ".join(EXT_MIDIA)))
    op = []
    if tem_video:
        op += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy"]
    else:
        op += ["-vn"]
    # codec/bitrate de áudio são FORMATO: quando há perfil, vêm do perfil. SEM
    # perfil não existe número aqui — o codec fica com o default do contêiner e
    # o bitrate PRESERVA o da entrada. Inventar "aac 192k" no script seria
    # exatamente o que a SPEC-00 proíbe, e silenciosamente rebaixaria material
    # que já veio melhor.
    if alvo.get("codec"):
        op += ["-c:a", alvo["codec"]]
    br = alvo.get("bitrate") or alvo["entrada_probe"].get("bitrate")
    if br:
        op += ["-b:a", str(br)]
    op += ["-ar", str(alvo["sr"]), "-ac", str(alvo["canais"]), saida]
    return op


def _executar(cmd, o_que):
    r = _run(cmd)
    if r.returncode != 0:
        raise Erro("ffmpeg falhou (%s):\n%s" % (o_que, r.stderr.strip()[-2000:]), 3)
    return r


_RE_ASTATS_N = re.compile(r"Number of samples:\s*(\d+)")


def _amostras_decodificadas(caminho):
    """Quantas amostras SAEM do decoder, e a que taxa. `None` se não deu.

    🔴 POR QUE NÃO BASTA O `duration` DO ffprobe (2026-08-12, H47-8/H47-2).
    Um agente externo rodando a v0.12 no Linux relatou: "loudness.py declarou
    duração preservada e gerou 56,43 s de 64,50". O `duration` que o ffprobe
    devolve é, em WAV, o que o **cabeçalho RIFF declara** — e cabeçalho é o
    primeiro campo a mentir quando a escrita morre no meio, quando o muxer não
    consegue voltar para carimbar o tamanho (saída em pipe), ou quando o
    contêiner declara um `duration_ts` que o stream não tem. Contar o que o
    decoder de fato entrega é a única medida que não depende de ninguém dizer a
    verdade sobre si mesmo.

    ⚠️ A TAXA VOLTA JUNTO, e isso não é enfeite: o `loudnorm` resampleia para
    192 kHz internamente e o WAV de saída sai a 192 kHz (clean-audio/SKILL.md:31
    — "não calcule duração assumindo 48 kHz"). Comparar contagem de amostras
    entre arquivos de taxas diferentes daria uma deriva de 4× que não existe.
    """
    r = _run([_ffmpeg(), "-nostdin", "-hide_banner", "-i", caminho,
              "-map", "0:a:0", "-af", "astats=metadata=1:reset=0",
              "-f", "null", "-"])
    ns = [int(m) for m in _RE_ASTATS_N.findall(r.stderr)]
    sr = (_probe_audio(caminho) or {}).get("sr")
    if not ns or not sr:
        return None, sr
    # por canal e no Overall o número é o mesmo (é contagem de frames); o máximo
    # é robusto a um canal silencioso que o astats resuma diferente.
    return max(ns), sr


def _conferir_deriva(entrada, saida, limiar_ms):
    """Armadilha 8: o loudness.py não pode encurtar nem esticar a trilha.

    NÃO usar `-shortest`. O ref-A o coloca nos dois ramos do loudnorm
    (`render.py:932` e `:966`) enquanto o próprio código dele avisa em `:644`
    que "NO -shortest here: a sub-millisecond audio shortfall would truncate
    video". A incoerência é deles; para nós `-shortest` MASCARARIA uma deriva
    em vez de acusá-la.

    🔴 DUAS RÉGUAS, PORQUE ELAS RESPONDEM PERGUNTAS DIFERENTES (H47-2, e foi o
    controle que ensinou isto — a primeira versão deste conserto só contava
    amostras e PERDIA a deriva do AAC):

      · `delta_header_ms` — a duração que o CONTÊINER declara. É o número que um
        player, um muxer e o `concat` obedecem. Mudou o header, mudou a timeline.
      · `delta_amostras_ms` — quantas amostras o DECODER entrega. É o número que
        truncamento e arquivo malformado mexem, e o header pode não acompanhar.

    Medido em 2026-08-12, no clipe AAC de 6 s que a `audio-e-cor.md`
    documenta: o contêiner declara 6,000 s e o decoder entrega 288.768 amostras =
    6,016 s. O padding do AAC já está DENTRO do arquivo; o header é que o desconta
    (gapless). Ao virar WAV — que não tem onde guardar esse desconto — os 16 ms
    passam a ser áudio de verdade. Pela contagem de amostras a deriva "não
    existe"; pelo header ela existe e é REAL. Reprovar exige as duas.

    Qualquer uma das duas fora do limiar reprova, e o campo `regua` diz qual.
    """
    n_de, sr_de = _amostras_decodificadas(entrada)
    n_para, sr_para = _amostras_decodificadas(saida)
    h_de, h_para = _duracao_audio(entrada), _duracao_audio(saida)
    a_de = (n_de / float(sr_de)) if (n_de and sr_de) else None
    a_para = (n_para / float(sr_para)) if (n_para and sr_para) else None

    def _delta(x, y):
        return None if (x is None or y is None) else round((y - x) * 1000.0, 3)

    d = {"entrada_s": round(h_de, 6) if h_de is not None else None,
         "saida_s": round(h_para, 6) if h_para is not None else None,
         "amostras_entrada": n_de, "amostras_saida": n_para,
         "sr_entrada": sr_de, "sr_saida": sr_para,
         "entrada_amostras_s": round(a_de, 6) if a_de is not None else None,
         "saida_amostras_s": round(a_para, 6) if a_para is not None else None,
         "delta_header_ms": _delta(h_de, h_para),
         "delta_amostras_ms": _delta(a_de, a_para)}
    deltas = {k: v for k, v in (("header", d["delta_header_ms"]),
                                ("amostras", d["delta_amostras_ms"]))
              if v is not None}
    if not deltas:
        d.update({"delta_ms": None, "regua": None, "veredito": "indeterminado"})
        return d
    # o `delta_ms` continua existindo, e é o PIOR dos dois — quem lê um campo só
    # não pode receber o número mais gentil.
    pior = max(deltas, key=lambda k: abs(deltas[k]))
    d["delta_ms"] = deltas[pior]
    d["regua"] = pior if len(deltas) > 1 else list(deltas)[0]
    d["veredito"] = ("ok" if all(abs(v) <= limiar_ms for v in deltas.values())
                     else "DERIVA")
    # E o contêiner mentindo sobre SI MESMO é um defeito à parte, mais grave que
    # deriva: quem lê o header depois vai acreditar nele. Só vale onde header e
    # amostras TÊM que fechar — em PCM/FLAC/ALAC. Em AAC eles divergem por
    # construção (o padding acima), e cobrar isso ali seria alarme permanente.
    codec = (_probe_audio(saida) or {}).get("codec") or ""
    exato = codec.startswith("pcm_") or codec in ("flac", "alac", "pcm_s16le")
    d["saida_exata"] = exato
    if exato and h_para is not None and a_para is not None:
        divergencia = abs(h_para - a_para) * 1000.0
        d["divergencia_header_ms"] = round(divergencia, 3)
        if divergencia > max(limiar_ms, 1.0):
            d["veredito"] = "ARQUIVO-MALFORMADO"
    return d


def _float_ou_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _probe_midia(caminho):
    """Probe estrutural usado no portão de publicação, não para decidir áudio."""
    r = _run([_ffprobe(), "-v", "error", "-show_entries",
              "stream=index,codec_type,codec_name,channels,sample_rate,duration,start_time,"
              "width,height,avg_frame_rate,nb_frames:format=format_name,duration,start_time",
              "-of", "json", caminho])
    if r.returncode != 0:
        raise Erro("ffprobe recusou a mídia candidata %s:\n%s"
                   % (caminho, r.stderr.strip()[-2000:]), 3)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise Erro("ffprobe devolveu JSON inválido para a mídia candidata %s" % caminho, 3)
    d.setdefault("streams", [])
    d.setdefault("format", {})
    return d


def _expectativa_midia(entrada):
    """Fixa, antes do render, o contrato que a saída MP4 terá que cumprir."""
    p = _probe_midia(entrada)
    videos = [s for s in p["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in p["streams"] if s.get("codec_type") == "audio"]
    if not audios:
        raise Erro("%s não tem áudio para normalizar" % entrada, 3)
    v, a = (videos[0] if videos else None), audios[0]
    dur = (_float_ou_none(v.get("duration")) if v else None)
    if dur is None:
        dur = _float_ou_none(p["format"].get("duration"))
    if dur is None:
        dur = _float_ou_none(a.get("duration"))
    if dur is None or dur <= 0:
        raise Erro("não foi possível fixar a duração autoritativa de %s" % entrada, 3)
    v_ini = _float_ou_none(v.get("start_time")) if v else 0.0
    a_ini = _float_ou_none(a.get("start_time"))
    v_ini = 0.0 if v_ini is None else v_ini
    a_ini = 0.0 if a_ini is None else a_ini
    return {
        "tem_video": bool(v),
        "duracao_s": dur,
        "video_codec": v.get("codec_name") if v else None,
        "video_width": v.get("width") if v else None,
        "video_height": v.get("height") if v else None,
        "video_frames": (int(v["nb_frames"])
                         if v and str(v.get("nb_frames", "")).isdigit() else None),
        "offset_av_ms": round((a_ini - v_ini) * 1000.0, 3),
    }


def _tem_moov(caminho):
    """Lê só os átomos de topo do ISO-BMFF; nunca varre o payload de vídeo."""
    total = os.path.getsize(caminho)
    pos = 0
    try:
        with open(caminho, "rb") as fh:
            while pos + 8 <= total:
                fh.seek(pos)
                cab = fh.read(8)
                if len(cab) != 8:
                    return False
                tamanho = int.from_bytes(cab[:4], "big")
                tipo = cab[4:8]
                minimo = 8
                if tamanho == 1:
                    ext = fh.read(8)
                    if len(ext) != 8:
                        return False
                    tamanho = int.from_bytes(ext, "big")
                    minimo = 16
                elif tamanho == 0:
                    tamanho = total - pos
                if tamanho < minimo or pos + tamanho > total:
                    return False
                if tipo == b"moov":
                    return True
                pos += tamanho
    except OSError:
        return False
    return False


def _extrair_pcm_alinhado(entrada, destino, expectativa, limiar_ms):
    """Decodifica a trilha e a fixa na duração do vídeo antes do loudnorm.

    `apad` mais `atrim` cobre as duas direções sem `-shortest`: áudio curto ganha
    silêncio; padding de AAC ou áudio longo é cortado no relógio autoritativo.
    O loudnorm passa a operar somente sobre PCM de duração conhecida.
    """
    ent = _probe_audio(entrada)
    dur = expectativa["duracao_s"]
    af = "apad,atrim=end=%.9f,asetpts=N/SR/TB" % dur
    cmd = [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", entrada,
           "-map", "0:a:0", "-af", af, "-vn", "-c:a", "pcm_s24le",
           "-ar", str(ent["sr"]), "-ac", str(ent["canais"]), destino]
    _executar(cmd, "decodificação PCM anterior ao loudnorm")
    n, sr = _amostras_decodificadas(destino)
    if not n or not sr:
        raise Erro("PCM intermediário não pôde ser contado: %s" % destino, 3)
    real = n / float(sr)
    delta = (real - dur) * 1000.0
    if abs(delta) > max(float(limiar_ms), 1.0):
        raise Erro("PCM intermediário saiu com duração %+.3f ms diferente do vídeo"
                   % delta, 3)
    return {"amostras": n, "sr": sr, "duracao_s": round(real, 6),
            "delta_ms": round(delta, 3)}


def _muxar_pcm_em_mp4(entrada, pcm, destino, alvo, expectativa):
    cmd = [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", entrada,
           "-i", pcm]
    if expectativa["tem_video"]:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
    else:
        cmd += ["-map", "1:a:0", "-vn"]
    if alvo.get("codec"):
        cmd += ["-c:a", alvo["codec"]]
    br = alvo.get("bitrate") or alvo["entrada_probe"].get("bitrate")
    if br:
        cmd += ["-b:a", str(br)]
    cmd += ["-ar", str(alvo["sr"]), "-ac", str(alvo["canais"]),
            "-t", "%.9f" % expectativa["duracao_s"],
            "-movflags", "+faststart", destino]
    _executar(cmd, "mux MP4 a partir do PCM normalizado")


def _validar_midia_publicavel(caminho, expectativa, alvo, limiar_ms):
    """Portão anterior ao rename: moov, streams, duração e decode integral."""
    if not _tem_moov(caminho):
        raise Erro("MP4 candidato sem átomo moov; publicação recusada: %s" % caminho, 3)
    p = _probe_midia(caminho)
    videos = [s for s in p["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in p["streams"] if s.get("codec_type") == "audio"]
    outros = [s for s in p["streams"] if s.get("codec_type") not in ("video", "audio")]
    n_v_esperado = 1 if expectativa["tem_video"] else 0
    if len(videos) != n_v_esperado or len(audios) != 1 or outros:
        raise Erro("MP4 candidato com streams errados: vídeo %d (esperado %d), "
                   "áudio %d (esperado 1), outros %d"
                   % (len(videos), n_v_esperado, len(audios), len(outros)), 3)
    a = audios[0]
    if alvo.get("codec") and a.get("codec_name") != alvo["codec"]:
        raise Erro("codec de áudio do MP4 é %s; esperado %s"
                   % (a.get("codec_name"), alvo["codec"]), 3)
    if int(a.get("channels") or 0) != int(alvo["canais"]):
        raise Erro("MP4 candidato com %s canais; esperado %s"
                   % (a.get("channels"), alvo["canais"]), 3)
    if int(a.get("sample_rate") or 0) != int(alvo["sr"]):
        raise Erro("MP4 candidato a %s Hz; esperado %s Hz"
                   % (a.get("sample_rate"), alvo["sr"]), 3)
    if videos:
        v = videos[0]
        if expectativa["video_codec"] and v.get("codec_name") != expectativa["video_codec"]:
            raise Erro("codec de vídeo mudou no mux: %s -> %s"
                       % (expectativa["video_codec"], v.get("codec_name")), 3)
        if (expectativa["video_width"], expectativa["video_height"]) != \
                (v.get("width"), v.get("height")):
            raise Erro("dimensão de vídeo mudou no mux: %sx%s -> %sx%s"
                       % (expectativa["video_width"], expectativa["video_height"],
                          v.get("width"), v.get("height")), 3)

    esperado_s = expectativa["duracao_s"]
    medidos = {"format": _float_ou_none(p["format"].get("duration")),
               "audio": _float_ou_none(a.get("duration"))}
    if videos:
        medidos["video"] = _float_ou_none(videos[0].get("duration"))
    ausentes = [k for k, v in medidos.items() if v is None]
    if ausentes:
        raise Erro("MP4 candidato sem duração declarada em: %s" % ", ".join(ausentes), 3)
    deltas = {k: round((v - esperado_s) * 1000.0, 3) for k, v in medidos.items()}
    tolerancia = max(float(limiar_ms), 1.0)
    fora = {k: v for k, v in deltas.items() if abs(v) > tolerancia}
    if fora:
        raise Erro("MP4 candidato com duração divergente antes da publicação: %s "
                   "(limiar %.1f ms)" % (", ".join("%s=%+.3fms" % x
                                                    for x in sorted(fora.items())),
                                         tolerancia), 3)
    if videos:
        quadros = (int(videos[0]["nb_frames"])
                   if str(videos[0].get("nb_frames", "")).isdigit() else None)
        if (expectativa["video_frames"] is not None and quadros is not None
                and quadros != expectativa["video_frames"]):
            raise Erro("contagem de frames mudou no mux: %d -> %d"
                       % (expectativa["video_frames"], quadros), 3)

    v_ini = _float_ou_none(videos[0].get("start_time")) if videos else 0.0
    a_ini = _float_ou_none(a.get("start_time"))
    v_ini = 0.0 if v_ini is None else v_ini
    a_ini = 0.0 if a_ini is None else a_ini
    offset = round((a_ini - v_ini) * 1000.0, 3)
    if abs(offset - expectativa["offset_av_ms"]) > tolerancia:
        raise Erro("offset A/V mudou no mux: %.3f ms -> %.3f ms"
                   % (expectativa["offset_av_ms"], offset), 3)

    cmd = [_ffmpeg(), "-nostdin", "-v", "error", "-xerror", "-i", caminho]
    if videos:
        cmd += ["-map", "0:v:0"]
    cmd += ["-map", "0:a:0", "-f", "null", "-"]
    r = _run(cmd)
    if r.returncode != 0:
        raise Erro("MP4 candidato falhou na decodificação integral:\n%s"
                   % r.stderr.strip()[-2000:], 3)
    pior = max(deltas, key=lambda k: abs(deltas[k]))
    return {
        "atomica": True,
        "pipeline": ["decode-pcm", "loudnorm-pcm", "mux-faststart",
                     "ffprobe", "decode-integral", "replace-atomico"],
        "moov": True,
        "streams": {"video": len(videos), "audio": len(audios),
                    "audio_codec": a.get("codec_name"),
                    "audio_sr": int(a["sample_rate"]),
                    "audio_canais": int(a["channels"]),
                    "video_frames": (int(videos[0]["nb_frames"])
                                     if videos and str(videos[0].get("nb_frames", "")).isdigit()
                                     else None)},
        "offset_av_ms": offset,
        "duracao": {"entrada_s": round(esperado_s, 6),
                    "saida_s": round(medidos["format"], 6),
                    "delta_header_ms": deltas["format"],
                    "delta_amostras_ms": None,
                    "delta_ms": deltas[pior], "regua": pior,
                    "veredito": "ok", "medidas_ms": deltas},
        "decode_integral": "ok",
    }


def _publicar_midia_atomica(parcial, saida, expectativa, alvo, limiar_ms,
                            validacao_pronta=None):
    """Valida primeiro, renomeia por último e remove o parcial em qualquer falha."""
    try:
        validacao = (validacao_pronta if validacao_pronta is not None else
                     _validar_midia_publicavel(parcial, expectativa, alvo, limiar_ms))
        os.replace(parcial, saida)
        return validacao
    except BaseException:
        try:
            if os.path.exists(parcial):
                os.remove(parcial)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------- modos
def modo_medir(entrada, args):
    m = medir_ebur128(entrada)
    saida = {"contrato": CONTRATO, "modo": "medir", "entrada": entrada,
             "medido": m, "ffmpeg": _versao_ffmpeg()}
    print(json.dumps(saida, ensure_ascii=False, indent=1))
    print("%s  I=%.1f LUFS  TP=%.1f dBFS  LRA=%.1f LU  %dch @ %d Hz"
          % (entrada, m["i"], m["tp"], m["lra"], m["canais"], m["sr"]), file=sys.stderr)
    return 0


def modo_verificar(entrada, args):
    """QC. Mede o ARQUIVO como ele está e compara com o alvo. Exit 1 se fora.

    O `--pre` é IGNORADO aqui de propósito (armadilha 2 de §3.6): medir através
    de uma cadeia de filtro reporta o número do sinal filtrado, não do entregável.
    """
    if args["pre"]:
        print("aviso: --pre ignorado em --verificar — medir através de uma cadeia de "
              "filtro reporta o TP do sinal FILTRADO, não o do entregável "
              "(highpass=f=80 sobe o pico +1,5 dB, medido).", file=sys.stderr)
    alvo = resolver_alvo(args, entrada, exigir=("i",))
    m = medir_ebur128(entrada)
    erro_i = m["i"] - alvo["i"]
    fora_i = abs(erro_i) > alvo["tol_i"]
    fora_tp = alvo["tp"] is not None and m["tp"] > alvo["tp"] + alvo["tol_tp"]
    # o domínio de canais só é COBRADO quando alguém o declarou (flag ou perfil).
    # Sem declaração, `alvo["canais"]` é o da própria entrada e a comparação seria
    # tautológica — verde sem ter varrido nada.
    ch_declarado = alvo["fontes"].get("canais") in ("flag:--canais", "perfil")
    fora_ch = ch_declarado and m["canais"] != alvo["canais"]
    ok = not (fora_i or fora_tp or fora_ch)
    motivos = []
    if fora_i:
        motivos.append("I %.1f vs alvo %.1f (erro %+.2f LU > tol %.2f)"
                       % (m["i"], alvo["i"], erro_i, alvo["tol_i"]))
    if fora_tp:
        motivos.append("TP %.1f > alvo %.1f + tol %.2f"
                       % (m["tp"], alvo["tp"], alvo["tol_tp"]))
    if fora_ch:
        motivos.append("canais %d != alvo %d (o EBU R128 soma canais: comparar "
                       "domínios diferentes é comparar números diferentes)"
                       % (m["canais"], alvo["canais"]))
    print("%s  I=%.1f TP=%.1f LRA=%.1f (alvo I=%s TP=%s) → %s%s"
          % (entrada, m["i"], m["tp"], m["lra"], _n(alvo["i"]),
             _n(alvo["tp"]) if alvo["tp"] is not None else "—",
             "OK" if ok else "REPROVA",
             "" if ok else ": " + "; ".join(motivos)))
    reg = {"contrato": CONTRATO, "modo": "verificar", "entrada": entrada,
           "alvo": {k: alvo[k] for k in ("i", "tp", "lra", "canais")},
           "fontes_do_alvo": alvo["fontes"],
           "medido": m, "erro_lufs": round(erro_i, 2),
           "veredito": "ok" if ok else "reprova",
           "motivos": motivos, "ffmpeg": _versao_ffmpeg()}
    if args["json"]:
        _gravar_json(args["json"], reg)
    return 0 if ok else 1


def modo_normalizar(entrada, args):
    saida = args["out"]
    if not saida:
        raise Erro("--normalizar exige --out")
    alvo = resolver_alvo(args, entrada)
    ent = alvo["entrada_probe"]
    pre_canais = _filtro_canais(ent["canais"], alvo["canais"])
    pre = _cadeia(pre_canais, args["pre"] or "")
    destino_abs = os.path.abspath(saida)
    destino_dir = os.path.dirname(destino_abs) or "."
    os.makedirs(destino_dir, exist_ok=True)
    mp4_atomico = os.path.splitext(saida)[1].lower() == ".mp4"
    arena = None
    publicacao = None
    pcm_preparado = None
    caminho_medicao = entrada
    caminho_render = saida
    expectativa = None

    try:
        if mp4_atomico:
            # A arena mora no MESMO diretório da saída. Assim `os.replace` é um
            # rename no mesmo filesystem, não uma cópia interrompível disfarçada.
            arena = tempfile.mkdtemp(prefix=".loudness-parcial-", dir=destino_dir)
            pcm_base = os.path.join(arena, "entrada-alinhada.wav")
            caminho_render = os.path.join(arena, "normalizado.wav")
            parcial_mp4 = os.path.join(arena, "saida.mp4")
            expectativa = _expectativa_midia(entrada)
            pcm_preparado = _extrair_pcm_alinhado(
                entrada, pcm_base, expectativa, args["deriva_ms"])
            caminho_medicao = pcm_base

        p1 = medir_loudnorm(caminho_medicao, alvo, pre=pre)
        dec = decidir_modo(p1, alvo, args["modo"])
        decisao_ganho = decidir_ganho_alto(dec, args["autorizar_ganho_alto"])
        if decisao_ganho["exigida"]:
            print("decisão registrada: ganho de +%.1f dB autorizado por "
                  "--autorizar-ganho-alto; nenhuma limpeza automática será aplicada."
                  % dec["ganho_linear_db"], file=sys.stderr)

        if alvo["passes"] == 1:
            print("⚠️ passes_loudnorm=1: passe ÚNICO. Ele ESTIMA o alvo em tempo real e "
                  "erra sempre para baixo — medido 1,75 LU de erro médio em 6 de 6 "
                  "entregáveis. O passe 1 acabou de prever output_i=%s para um alvo de "
                  "%s. Isto existe só para reproduzir comportamento antigo."
                  % (p1.get("output_i"), _n(alvo["i"])), file=sys.stderr)
            af = _cadeia(pre, "loudnorm=I=%s:TP=%s:LRA=%s"
                         % (_n(alvo["i"]), _n(alvo["tp"]), _n(alvo["lra"])))
        else:
            medidos = ("measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s"
                       ":offset=%s" % (p1["input_i"], p1["input_tp"], p1["input_lra"],
                                       p1["input_thresh"], p1["target_offset"]))
            af = _cadeia(pre, "loudnorm=I=%s:TP=%s:LRA=%s:%s%s"
                         % (_n(alvo["i"]), _n(alvo["tp"]), _n(alvo["lra"]), medidos,
                            ":linear=true" if dec["modo"] == "linear" else ""))

        cmd = [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", caminho_medicao,
               "-af", af]
        tem_video_direto = (not mp4_atomico and _tem_video(entrada)
                            and os.path.splitext(saida)[1].lower() in EXT_MIDIA)
        cmd += _opcoes_saida(caminho_render, alvo, caminho_medicao, tem_video_direto)
        _executar(cmd, "passe 2 PCM" if mp4_atomico else "passe 2")

        if mp4_atomico:
            deriva_pcm = _conferir_deriva(
                caminho_medicao, caminho_render, args["deriva_ms"])
            if deriva_pcm["veredito"] != "ok":
                raise Erro("PCM normalizado falhou antes do mux: %s (Δ=%s ms)"
                           % (deriva_pcm["veredito"], deriva_pcm.get("delta_ms")), 3)
            _muxar_pcm_em_mp4(entrada, caminho_render, parcial_mp4, alvo, expectativa)
            # O portão estrutural acontece ainda dentro da arena. Nenhum byte do
            # caminho final foi tocado até moov, streams, duração e decode passarem.
            publicacao_pronta = _validar_midia_publicavel(
                parcial_mp4, expectativa, alvo, args["deriva_ms"])
            m = medir_ebur128(parcial_mp4)
            deriva = publicacao_pronta["duracao"]
        else:
            m = medir_ebur128(saida)
            deriva = _conferir_deriva(entrada, saida, args["deriva_ms"])

        erro_i = m["i"] - alvo["i"]
        fora_i = abs(erro_i) > alvo["tol_i"]
        fora_tp = m["tp"] > alvo["tp"] + alvo["tol_tp"]
        fora = fora_i or fora_tp

        # MP4 só recebe o rename depois também do QC de loudness/true peak.
        if mp4_atomico and fora:
            raise Erro("MP4 candidato não convergiu antes da publicação: I erro %+.2f "
                       "LU (tol %.2f), TP %.2f vs teto %.2f + tol %.2f"
                       % (erro_i, alvo["tol_i"], m["tp"], alvo["tp"], alvo["tol_tp"]), 1)
        if mp4_atomico:
            publicacao = _publicar_midia_atomica(
                parcial_mp4, saida, expectativa, alvo, args["deriva_ms"],
                validacao_pronta=publicacao_pronta)

        reg = {
            "contrato": CONTRATO, "entrada": entrada, "saida": saida,
            "perfil": alvo["perfil"],
            "alvo": {"i": alvo["i"], "tp": alvo["tp"], "lra": alvo["lra"],
                     "canais": alvo["canais"], "sr": alvo["sr"]},
            "fontes_do_alvo": alvo["fontes"],
            "passes": alvo["passes"],
            "pre": pre or None,
            "passe1": {k: p1[k] for k in ("input_i", "input_tp", "input_lra",
                                          "input_thresh", "target_offset", "output_i")},
            "decisao": dec,
            "decisao_ganho_alto": decisao_ganho,
            "saida_medida": m,
            "duracao": deriva,
            "erro_lufs": round(erro_i, 2),
            "erro_true_peak_db": round(m["tp"] - alvo["tp"], 2),
            "publicacao": (publicacao if publicacao is not None else
                           {"atomica": False, "pipeline": ["loudnorm-direto"],
                            "motivo": "saída não é MP4"}),
            "pcm_preparado": pcm_preparado,
            # O veredito inclui duração e convergência. No ramo MP4 qualquer
            # valor diferente de ok já abortou ANTES do rename.
            "veredito": (deriva["veredito"].lower()
                         if deriva["veredito"] in ("DERIVA", "ARQUIVO-MALFORMADO")
                         else "fora-da-tolerancia" if fora else "ok"),
            "ffmpeg": _versao_ffmpeg(),
        }
        destino_json = args["json"] or (saida + ".loudness.json")
        _gravar_json(destino_json, reg)

        print("%s  modo=%s  I=%.1f (alvo %s, erro %+.2f LU)  TP=%.1f  %dch  "
              "Δdur=%s ms%s"
              % (saida, dec["modo"], m["i"], _n(alvo["i"]), erro_i, m["tp"],
                 m["canais"], deriva["delta_ms"],
                 "  publicação=atômica" if mp4_atomico else ""), file=sys.stderr)
        print(saida)

        if deriva["veredito"] == "ARQUIVO-MALFORMADO":
            print("ABORTA: %s está MALFORMADO. O contêiner e o decoder discordam; "
                  "a saída não é publicável." % saida, file=sys.stderr)
            return 3
        if deriva["veredito"] == "DERIVA":
            print("ABORTA: a duração do áudio mudou %+.3f ms (limiar %.1f). "
                  "Normalize em PCM antes do mux; não use -shortest."
                  % (deriva["delta_ms"], args["deriva_ms"]), file=sys.stderr)
            return 3
        if fora:
            print("REPROVA: loudness/true peak fora da tolerância. Não convergiu.",
                  file=sys.stderr)
            return 1
        return 0
    finally:
        if arena:
            shutil.rmtree(arena, ignore_errors=True)


def modo_teto(entrada, args):
    """Só limitador de pico, `-c:v copy`, sem tocar no corpo.

    Existe para o caso medido em SKILL.md:93: quando os SFX entram por `amix`
    DEPOIS da normalização, o pico sobe (a peca-03 saiu a −0,88 e a paixão a
    −0,58 dBTP mirando −1,5) e re-normalizar mexeria no corpo. A receita medida:
    I −14,99 antes e −14,99 depois; TP −0,58 → −1,48.

    `limit` sai de 10**(alvo_tp/20) — 0,841 é o valor para −1,5 dBTP, e o
    `peca-09/compor.sh:51` o tem cravado na mão. Aquela produção fica
    congelada; este é o lugar de onde o número passa a sair.
    """
    saida = args["out"]
    if not saida:
        raise Erro("--teto exige --out")
    teto = float(args["teto"])
    limite = 10 ** (teto / 20.0)
    ent = _probe_audio(entrada)
    alvo = {"sr": ent["sr"], "canais": ent["canais"], "codec": None,
            "bitrate": None, "entrada_probe": ent}
    if args["perfil"]:
        p = carregar_perfil(args["perfil"])
        a, _ = _audio_do_perfil(p)
        if isinstance(a.get("sr"), int):
            alvo["sr"] = int(a["sr"])
        if isinstance(a.get("canais"), int):
            alvo["canais"] = int(a["canais"])
        alvo["codec"], alvo["bitrate"] = a.get("codec"), a.get("bitrate")
    antes = medir_ebur128(entrada)
    af = "alimiter=limit=%.6f:attack=%d:release=%d:level=disabled" % (
        limite, LIMITER_ATTACK_MS, LIMITER_RELEASE_MS)
    os.makedirs(os.path.dirname(os.path.abspath(saida)) or ".", exist_ok=True)
    cmd = [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", entrada, "-af", af]
    cmd += _opcoes_saida(saida, alvo, entrada, _tem_video(entrada)
                         and os.path.splitext(saida)[1].lower() in EXT_MIDIA)
    _executar(cmd, "teto")
    depois = medir_ebur128(saida)
    deriva = _conferir_deriva(entrada, saida, args["deriva_ms"])
    # 🔴 O `alimiter` limita PICO DE AMOSTRA; o `ebur128=peak=true` mede TRUE
    # PEAK com oversampling 4×. Os dois não são o mesmo número: o pico
    # inter-amostra pode ficar acima do `limit` mesmo com o limitador cravado.
    # Medido aqui: material com +2 dB de ganho sobrou 0,2 dB acima do teto. A
    # receita de SKILL.md:93 fechou em −1,48 mirando −1,5 porque o material dela
    # era outro. Por isso o modo MEDE a saída e AVISA — um `--teto` que só aplica
    # o filtro e diz "feito" é um portão sem dentes.
    sobrou = depois["tp"] - teto
    reg = {"contrato": CONTRATO, "modo": "teto", "entrada": entrada, "saida": saida,
           "teto_dbtp": teto, "limit": round(limite, 6),
           "antes": antes, "depois": depois, "duracao": deriva,
           "delta_i": round(depois["i"] - antes["i"], 2),
           "sobra_tp_db": round(sobrou, 2),
           # mesma regra do --normalizar (H47-2): o veredito do sidecar não pode
           # dizer "ok" sobre um arquivo cuja duração não fecha.
           "veredito": (deriva["veredito"].lower()
                        if deriva["veredito"] in ("DERIVA", "ARQUIVO-MALFORMADO")
                        else "ok" if sobrou <= TOLERANCIA_TP_PADRAO
                        else "teto-nao-atingido"),
           "ffmpeg": _versao_ffmpeg()}
    _gravar_json(args["json"] or (saida + ".loudness.json"), reg)
    print("%s  TP %.1f → %.1f  (I %.1f → %.1f, Δ%+.2f LU)  Δdur=%s ms"
          % (saida, antes["tp"], depois["tp"], antes["i"], depois["i"],
             depois["i"] - antes["i"], deriva["delta_ms"]), file=sys.stderr)
    if sobrou > TOLERANCIA_TP_PADRAO:
        print("aviso: true peak da saída %.1f dBFS ainda está %.2f dB ACIMA do teto "
              "%.1f. O alimiter limita pico de AMOSTRA; o pico inter-amostra sobra. "
              "Baixe o --teto ou normalize o mix inteiro (--normalizar) em vez de "
              "somar SFX depois." % (depois["tp"], sobrou, teto), file=sys.stderr)
    print(saida)
    return 3 if deriva["veredito"] in ("DERIVA", "ARQUIVO-MALFORMADO") else 0


def _gravar_json(caminho, obj):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return caminho


# ------------------------------------------------------------------------ CLI
USO = """uso: loudness.py <entrada> [opções]

modos (mutuamente exclusivos; default = --normalizar se houver --out)
  --medir                     mede e imprime JSON; não escreve mídia
  --normalizar                2 passes → --out (obrigatório)
  --verificar                 mede a ENTRADA contra o alvo; exit 1 se fora
  --teto <dBTP>               só limitador de pico, -c:v copy

alvo (precedência: flags > --perfil > --referencia; SEM DEFAULT)
  --perfil <nome|caminho>     bloco `audio.loudness` do perfil de peça
  --alvo-i <LUFS>             integrado alvo
  --alvo-tp <dBTP>            true peak alvo
  --alvo-lra <LU>             loudness range alvo
  --referencia <arquivo>      alvo-i = integrado medido nesse arquivo

saída e cadeia
  --out <arquivo>             .wav (PCM s24) ou .mp4/.mov/.m4a (-c:v copy)
  --canais mono|estereo|manter   default: o do perfil, senão manter
  --pre "<cadeia ffmpeg>"     filtros ANTES do loudnorm (highpass, deesser…)
  --autorizar-ganho-alto <motivo>
                              permite ganho >6 dB e grava a decisão no sidecar
  --modo auto|linear|dinamico    default auto
  --passes 1|2                default: o do perfil (2). 1 é o defeito, documentado
  --tolerancia-lufs <LU>      default 0.5
  --tolerancia-tp <dB>        default 0.1
  --deriva-max-ms <ms>        default 1.0
  --json <arquivo>            sidecar; default <out>.loudness.json

exit  0 ok · 1 fora da tolerância · 2 alvo não resolvido/uso · 3 ffmpeg/medição
"""


def _parse(argv):
    a = {"entrada": None, "medir": False, "normalizar": False, "verificar": False,
         "teto": None, "perfil": None, "alvo_i": None, "alvo_tp": None,
         "alvo_lra": None, "referencia": None, "out": None, "canais": None,
         "pre": None, "modo": "auto", "passes": None, "tol_i": None,
         "tol_tp": None, "deriva_ms": DERIVA_MAX_MS_PADRAO, "json": None,
         "autorizar_ganho_alto": None}
    flag_val = {"--teto": "teto", "--perfil": "perfil", "--alvo-i": "alvo_i",
                "--alvo-tp": "alvo_tp", "--alvo-lra": "alvo_lra",
                "--referencia": "referencia", "--out": "out", "--canais": "canais",
                "--pre": "pre", "--autorizar-ganho-alto": "autorizar_ganho_alto",
                "--modo": "modo", "--passes": "passes",
                "--tolerancia-lufs": "tol_i", "--tolerancia-tp": "tol_tp",
                "--deriva-max-ms": "deriva_ms", "--json": "json"}
    numericas = {"teto", "alvo_i", "alvo_tp", "alvo_lra", "tol_i", "tol_tp",
                 "deriva_ms"}
    i = 0
    while i < len(argv):
        x = argv[i]
        if x in ("-h", "--help"):
            print(USO, file=sys.stderr)
            sys.exit(0)
        if x in ("--medir", "--normalizar", "--verificar"):
            a[x[2:]] = True
        elif x in flag_val:
            if i + 1 >= len(argv):
                raise Erro("%s espera um valor" % x)
            chave = flag_val[x]
            v = argv[i + 1]
            if chave in numericas:
                try:
                    v = float(v)
                except ValueError:
                    raise Erro("%s espera número, recebi %r" % (x, v))
            elif chave == "passes":
                if v not in ("1", "2"):
                    raise Erro("--passes aceita 1 ou 2, recebi %r" % v)
                v = int(v)
            a[chave] = v
            i += 1
        elif x.startswith("-"):
            raise Erro("opção desconhecida: %s\n\n%s" % (x, USO))
        elif a["entrada"] is None:
            a["entrada"] = x
        else:
            raise Erro("mais de uma entrada: %r e %r" % (a["entrada"], x))
        i += 1
    if a["canais"] and a["canais"] not in ("mono", "estereo", "manter"):
        raise Erro("--canais aceita mono|estereo|manter, recebi %r" % a["canais"])
    if a["modo"] not in ("auto", "linear", "dinamico"):
        raise Erro("--modo aceita auto|linear|dinamico, recebi %r" % a["modo"])
    return a


def main(argv):
    if not argv:
        print(USO, file=sys.stderr)
        return 2
    a = _parse(argv)
    if not a["entrada"]:
        raise Erro("falta a entrada.\n\n%s" % USO)
    if not os.path.exists(a["entrada"]):
        raise Erro("entrada não existe: %s" % a["entrada"])

    escolhidos = [n for n in ("medir", "normalizar", "verificar") if a[n]]
    if a["teto"] is not None:
        escolhidos.append("teto")
    if len(escolhidos) > 1:
        raise Erro("modos são mutuamente exclusivos, recebi: %s"
                   % ", ".join("--" + m for m in escolhidos))
    modo = escolhidos[0] if escolhidos else ("normalizar" if a["out"] else None)
    if modo is None:
        raise Erro("nenhum modo escolhido e nenhum --out.\n\n%s" % USO)

    return {"medir": modo_medir, "verificar": modo_verificar,
            "normalizar": modo_normalizar, "teto": modo_teto}[modo](a["entrada"], a)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)
