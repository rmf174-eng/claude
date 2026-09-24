#!/usr/bin/env python3
"""musica-gerar.py — de onde vem a MÚSICA, e onde a licença fica gravada (SPEC-20).

Este script só consegue a faixa. Ele não sabe o que é ducking, nem qual peça vai
usar, nem que existe `<dir-producao>`. Quem mistura é o `trilha.py`.

O QUE ELE RESOLVE (o problema, medido)

    Até hoje "trilha" significava "alguém arruma um mp3". A única fonte com
    qualidade garantida era CC-BY com atribuição obrigatória, e as URLs
    adivinhadas de CDN devolvem 403. O caminho novo é gerar por IA com a chave
    que o repo já tem.

🔴 O QUE NÃO SE HERDA DO ref-A (`references/shortform.md:472`)

    [2:a]volume=0.10, … amix … loudnorm=I=-14

    `volume=0.10` é ganho CEGO sobre um mp3 nunca medido. O nível de saída da
    música passa a depender de quão alto o gerador entregou naquele dia. Medido
    nesta bancada: o gerador entrega quente (integrado por volta de −11 LUFS) e
    JÁ CHEGA COM TRUE PEAK POSITIVO. Duas gerações separadas por 0,5 LU passam
    despercebidas; uma faixa 7 LU mais baixa entraria inaudível sem nada mudar
    no comando. Por isso aqui toda faixa é MEDIDA antes de entrar na biblioteca,
    e o nível é decidido no `trilha.py`, relativo à voz.

🔴 O FILTRO DE DIREITOS AUTORAIS É FREQUENTE E A RESPOSTA VEM SEM `content`

    A API devolve HTTP 200 com `finishReason: "OTHER"`, um `finishMessage`
    explicando, e o candidato **sem a chave `content`**. Um leitor ingênuo
    (`d["candidates"][0]["content"]["parts"]`) estoura `KeyError`. Aqui o
    `finishReason` é lido ANTES de qualquer acesso a `content`, o
    `finishMessage` inteiro vai para o stderr, e a retentativa varia o prompt
    (repetir o mesmo prompt refiltra). Esgotadas as tentativas: exit 4.

💰 IDEMPOTÊNCIA É DINHEIRO. A chave é `sha256(prompt_canonico + modelo)`. Se a
    faixa já está na biblioteca, a segunda chamada faz ZERO requisição HTTP.

⚠️ PRODUTO, NÃO INSTALAÇÃO. Nenhum caminho absoluto, nenhuma referência a
    creator. A biblioteca sai de `$MUSIC_DIR`, com default relativo a este
    arquivo, e o diretório é CRIADO pelo script (`os.makedirs`) — um `.gitkeep`
    não sobrevive ao clone porque o `.gitignore` ignora o conteúdo, e na máquina
    de quem instalar o produto nada disso existe. A chave da API vem SÓ de
    `os.environ`. Trocar de fornecedor é acrescentar uma função ao dicionário
    `MOTORES` e não tocar em mais nada.

⚠️ LICENÇA. A saída do Lyria carrega marca d'água SynthID e vale sob os Termos
    da API do fornecedor. Isso está GRAVADO em cada registro (`licenca`,
    `synthid`), não impresso e esquecido. Não afirme em venda que a trilha é
    "livre de royalties" — é pergunta jurídica em aberto, e o campo existe
    justamente para que a resposta possa ser dada faixa a faixa depois.

USO
    musica-gerar.py --vibe "<gênero + instrumentos + BPM + humor>" --dur <s>
                    [--modelo lyria-3-clip|lyria-3-pro|arquivo] [--tentativas 3]
                    [--out <arquivo.mp3>] [--tags a,b,c] [--de <arquivo>]
    musica-gerar.py --avaliar <a.mp3> [<b.mp3> …] --voz <arquivo>
                    [--mascara-max-pct F | --dir <dir-producao>] [--amostras <dir>]
    musica-gerar.py --listar

exit: 0 ok · 2 uso inválido · 3 falha de ffmpeg/ffprobe · 4 filtrado em todas as
      tentativas
"""
import base64
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import perfil as _perfil                                        # noqa: E402

CONTRATO = "benchmark.music-library/v1"

# --------------------------------------------------------------------- FÍSICA
# Constantes de MEDIÇÃO e de PROTOCOLO DO FORNECEDOR. Nenhuma descreve o formato
# da peça — formato mora no perfil (SPEC-00), e o `trilha.py` é quem o lê.
#
# BANDA_FALA — a banda de inteligibilidade da fala (telefonia, ITU). É a banda em
# que música e voz brigam pelo mesmo espaço; foi assim que uma candidata com
# 29,6 % da energia ali foi eliminada de ouvido e a escolhida (11,9 %) aprovada.
BANDA_FALA_HZ = (300.0, 3400.0)
# Welch: janela de 4096 amostras com 50 % de sobreposição. É resolução do
# estimador (≈12 Hz a 48 kHz), não característica da peça.
WELCH_N = 4096
# Dinâmica de curto prazo: p95 − p05 do RMS em janelas de 400 ms. A janela de
# 400 ms é a mesma do QC de efeito do `trilha.py` — uma régua só.
JANELA_S = 0.4
# Amostra A/B para o creator julgar de ouvido. 13 s é o que a produção usou.
AMOSTRA_S = 13.0

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
TIMEOUT_S = 600          # `pro` leva minutos; o default do urllib (nenhum) trava
TENTATIVAS_HTTP = 3      # retentativa de ERRO DE REDE (≠ retentativa de filtro)

# Catálogo de motores. `dur_max_s` e `preco_usd` são propriedades do FORNECEDOR,
# não da peça: é por isso que vivem aqui e não no perfil. O perfil escolhe QUAL
# motor (`trilha.engine`); o motor sabe o que consegue entregar e por quanto.
MOTORES_LYRIA = {
    "lyria-3-clip": {"api": "lyria-3-clip-preview", "dur_max_s": 28.0,
                     "preco_usd": 0.04},
    "lyria-3-pro": {"api": "lyria-3-pro-preview", "dur_max_s": 170.0,
                    "preco_usd": 0.08},
}
LICENCA_LYRIA = ("Gemini API (tier pago) — saída de uso comercial permitida pelos "
                 "Termos do serviço; contém marca d'água SynthID inaudível. "
                 "⚠️ NÃO afirmar 'livre de royalties': pendência jurídica aberta.")

# Variações de retentativa do filtro de copyright (§3.3). Lista FIXA e sorteio
# SEMEADO pelo prompt: duas execuções do mesmo pedido tentam a mesma sequência.
# Gerador sem seed é o defeito do `generate_sfx.py` deles — artefato diferente
# com o mesmo nome, cache por nome, e todos os QCs verdes.
VARIACOES = [
    "reharmonize with modal color and a different chord rhythm",
    "swap the lead timbre for a muted electric piano and soften the attack",
    "change the meter feel to a relaxed 6/8 and thin out the percussion",
    "build on a walking bass figure with brushed drums and no lead melody",
    "use pizzicato strings and a low woodwind counterline",
    "slow it down and let a felt piano carry the harmony alone",
    "add a subtle analog synth pad under the main line and drop the drums",
    "make it sparser: two voices only, with space between the phrases",
]


class Erro(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


class Filtrado(Exception):
    """A API respondeu 200 e recusou gerar. NÃO é erro de rede nem de uso."""

    def __init__(self, motivo, mensagem):
        super().__init__("%s: %s" % (motivo, mensagem))
        self.motivo = motivo
        self.mensagem = mensagem


# --------------------------------------------------------------- a biblioteca
# `abspath`, não `realpath`: pelo caminho antigo (`.claude/skills/…`) ou pelo real
# (`ilha/skills/…`) subir quatro níveis dá a mesma raiz — os dois têm a mesma
# profundidade. Medido na `broll-source`, que resolve a irmã do mesmo jeito.
RAIZ_MUSICA = os.path.abspath(os.environ.get("MUSIC_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "tools", "music-library"))
TRACKS = os.path.join(RAIZ_MUSICA, "tracks")
INDEX = os.path.join(RAIZ_MUSICA, "INDEX.json")


def _garantir_biblioteca():
    """Quem cria o diretório é o script, sempre (FRONTEIRA.md, orientação 9)."""
    os.makedirs(TRACKS, exist_ok=True)
    if not os.path.exists(INDEX):
        with open(INDEX, "w", encoding="utf-8") as fh:
            fh.write("[]\n")


def ler_indice():
    if not os.path.exists(INDEX):
        return []
    try:
        with open(INDEX, encoding="utf-8") as fh:
            d = json.load(fh)
    except json.JSONDecodeError as e:
        raise Erro("INDEX.json ilegível (%s): %s" % (INDEX, e))
    if not isinstance(d, list):
        raise Erro("INDEX.json deveria ser uma lista, é %s" % type(d).__name__)
    return d


def registrar(reg, indice=None):
    """Acrescenta (ou substitui pela chave) UM registro no índice, sob lock.

    O lock é o mesmo mecanismo do `perfil.py` (mkdir atômico + PID), importado
    de lá em vez de reescrito: duas cópias de um lock são dois locks."""
    caminho = indice or INDEX
    _garantir_biblioteca()
    lock = _perfil._tomar_lock(caminho)
    try:
        atual = ler_indice() if caminho == INDEX else (
            json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else [])
        saida = [r for r in atual if r.get("chave") != reg.get("chave")
                 and r.get("nome") != reg.get("nome")]
        saida.append(reg)
        tmp = caminho + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(saida, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, caminho)
    finally:
        _perfil._soltar_lock(lock)
    return caminho


def sha256_arquivo(caminho):
    """Identidade da faixa por CONTEÚDO. Nome não serve: a faixa é copiada para
    `<dir>/trilha/musica.mp3` e perde o nome da biblioteca no caminho — e é
    justamente aí que alguém precisa saber qual é a licença dela."""
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _por_chave(chave, indice=None):
    for r in (ler_indice() if indice is None else indice):
        if r.get("chave") == chave:
            return r
    return None


# ------------------------------------------------------------------- ffmpeg/probe
def _bin(nome):
    c = shutil.which(nome)
    if not c:
        raise Erro("%s não encontrado no PATH" % nome, 3)
    return c


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(caminho):
    r = _run([_bin("ffprobe"), "-v", "error", "-select_streams", "a:0",
              "-show_entries", "stream=sample_rate,channels:format=duration",
              "-of", "json", caminho])
    if r.returncode != 0:
        raise Erro("ffprobe falhou em %s:\n%s" % (caminho, r.stderr[-800:]), 3)
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    fm = d.get("format") or {}
    if not st:
        raise Erro("%s não tem stream de áudio" % caminho, 3)
    return {"sr": int(st.get("sample_rate") or 0),
            "canais": int(st.get("channels") or 0),
            "dur": float(fm.get("duration") or 0.0)}


def pcm_mono(caminho, sr=None):
    """Decodifica para float32 mono no sample rate NATIVO (ou no pedido).

    Decodificar no nativo evita inventar um número de formato dentro do script:
    a taxa é propriedade do arquivo, e quem precisa de duas fontes na MESMA taxa
    (o QC do `trilha.py`) passa a taxa explicitamente, tirada do perfil."""
    import numpy as np
    taxa = sr or probe(caminho)["sr"]
    cmd = [_bin("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error",
           "-i", caminho, "-vn", "-ac", "1", "-ar", str(taxa),
           "-f", "f32le", "-c:a", "pcm_f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise Erro("decodificação falhou em %s:\n%s"
                   % (caminho, r.stderr.decode("utf-8", "replace")[-800:]), 3)
    x = np.frombuffer(r.stdout, dtype="<f4")
    if x.size == 0:
        raise Erro("%s decodificou 0 amostra" % caminho, 3)
    return x.astype("float64"), taxa


# ------------------------------------------------------------------- medição
def mascara_pct(caminho):
    """Fração da energia da faixa dentro da banda de inteligibilidade da fala.

    Welch com janela de Hann e 50 % de sobreposição, implementado à mão porque
    `scipy` não existe nesta máquina e uma dependência nova é a coisa que mais
    quebra caminho de produto."""
    import numpy as np
    x, sr = pcm_mono(caminho)
    n = min(WELCH_N, x.size)
    if n < 64:
        raise Erro("faixa curta demais para medir espectro: %d amostras" % x.size, 3)
    jan = np.hanning(n)
    passo = max(1, n // 2)
    acc = np.zeros(n // 2 + 1)
    q = 0
    for i in range(0, x.size - n + 1, passo):
        acc += np.abs(np.fft.rfft(x[i:i + n] * jan)) ** 2
        q += 1
    if q == 0:
        acc = np.abs(np.fft.rfft(np.pad(x, (0, n - x.size)) * jan)) ** 2
        q = 1
    psd = acc / q
    f = np.fft.rfftfreq(n, 1.0 / sr)
    tot = psd.sum()
    if tot <= 0:
        return 0.0
    faixa = (f >= BANDA_FALA_HZ[0]) & (f <= BANDA_FALA_HZ[1])
    return float(psd[faixa].sum() / tot)


def envelope_rms(x, sr, janela_s=JANELA_S):
    import numpy as np
    w = max(1, int(round(janela_s * sr)))
    nq = x.size // w
    if nq == 0:
        return np.array([np.sqrt(np.mean(x ** 2))])
    bl = x[:nq * w].reshape(nq, w)
    return np.sqrt((bl ** 2).mean(axis=1))


def dinamica_e_crest(caminho):
    import numpy as np
    x, sr = pcm_mono(caminho)
    env = envelope_rms(x, sr)
    env = np.maximum(env, 1e-12)
    db = 20 * np.log10(env)
    din = float(np.percentile(db, 95) - np.percentile(db, 5))
    rms = float(np.sqrt(np.mean(x ** 2)))
    pico = float(np.max(np.abs(x)))
    crest = float(20 * math.log10(max(pico, 1e-12) / max(rms, 1e-12)))
    return din, crest


def medir_faixa(caminho):
    """Tudo que o índice guarda sobre a faixa, sem precisar de voz nenhuma."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import loudness as _loud
    p = probe(caminho)
    lu = _loud.medir_ebur128(caminho)
    din, crest = dinamica_e_crest(caminho)
    return {"dur": round(p["dur"], 2), "sr": p["sr"], "canais": p["canais"],
            "i_lufs": lu["i"], "tp_dbfs": lu["tp"],
            "mascara_pct": round(mascara_pct(caminho), 4),
            "dinamica_db": round(din, 1), "crest_db": round(crest, 1)}


# ---------------------------------------------------------------- o prompt
def moldar_prompt(vibe, variacao=None):
    """Enquadra a `vibe` como PEÇA INSTRUMENTAL COMPOSTA.

    O mecanismo é do ref-A (`helpers/treblo_music.py:25-42`) e o motivo está no
    docstring deles: gerador de música devolve SOUND DESIGN quando o pedido lê
    como textura ("bed", "beat", "sound design") e devolve MÚSICA quando lê como
    peça composta. A string abaixo é nossa, escrita do zero, e acrescenta
    "original composition" — que nasceu do filtro de copyright: o prompt que
    passou na bancada tinha essa frase, o que foi filtrado não tinha.

    O texto vai em inglês de propósito. A §8 desta spec escreve as `vibe` em
    inglês e "original composition" é frase inglesa; um enquadramento em
    português colado numa vibe em inglês entrega ao modelo um prompt de duas
    línguas, que é pior que qualquer uma das duas. A DOC é em português; o
    prompt é a interface com o fornecedor."""
    vibe = " ".join((vibe or "").split())
    if not vibe:
        raise Erro("--vibe vazia. Ela tem que nomear GÊNERO + INSTRUMENTOS + "
                   "ANDAMENTO/BPM + HUMOR — é o que separa música de textura.")
    partes = [
        "An original composition: a fully composed instrumental piece with a "
        "clear melodic line, real harmonic movement and a rhythm section that "
        "develops over time.",
        vibe.rstrip(".") + ".",
    ]
    if variacao:
        partes.append("Variation: " + variacao.rstrip(".") + ".")
    partes.append(
        "No vocals, no singing, no spoken word. No isolated sound effects, no "
        "risers, no whooshes, no impacts, no ambient drone. Not a loop bed. "
        "It must work quietly under a speaking voice.")
    return " ".join(partes)


def _chave(prompt_canonico, modelo_api):
    return hashlib.sha256(("%s|%s" % (prompt_canonico, modelo_api))
                          .encode("utf-8")).hexdigest()[:16]


def _variacoes_para(prompt_canonico, n):
    """Sorteio SEMEADO pelo prompt: reprodutível, e sem repetir variação."""
    r = random.Random(hashlib.sha256(prompt_canonico.encode("utf-8")).digest())
    v = list(VARIACOES)
    r.shuffle(v)
    return v[:max(0, n)]


# ----------------------------------------------------------------- motores
def _chamar_api(prompt, modelo_api, chave_api):
    corpo = json.dumps({"contents": [{"role": "user",
                                      "parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT % modelo_api, data=corpo,
        headers={"Content-Type": "application/json", "x-goog-api-key": chave_api})
    ultimo = None
    for k in range(TENTATIVAS_HTTP):
        try:
            print("  POST %s (%d bytes de prompt)" % (modelo_api, len(prompt)),
                  file=sys.stderr)
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            det = e.read().decode("utf-8", "replace")[:1200]
            if e.code in (429, 500, 502, 503, 504) and k + 1 < TENTATIVAS_HTTP:
                espera = 2 ** k
                print("  HTTP %d — nova tentativa de REDE em %ds" % (e.code, espera),
                      file=sys.stderr)
                time.sleep(espera)
                ultimo = "HTTP %d: %s" % (e.code, det)
                continue
            raise Erro("HTTP %d do fornecedor:\n%s" % (e.code, det), 3)
        except urllib.error.URLError as e:
            if k + 1 < TENTATIVAS_HTTP:
                time.sleep(2 ** k)
                ultimo = str(e)
                continue
            raise Erro("rede indisponível: %s" % e, 3)
    raise Erro("fornecedor não respondeu: %s" % ultimo, 3)


def _extrair_audio(d):
    """Lê a resposta SEM assumir que `content` existe.

    🔴 É aqui que o `KeyError` da bancada acontecia. `finishReason` diferente de
    STOP significa que o candidato veio sem `content` — o filtro de copyright é
    o caso frequente, e ele responde HTTP 200."""
    pf = d.get("promptFeedback") or {}
    if pf.get("blockReason"):
        raise Filtrado(pf["blockReason"],
                       pf.get("blockReasonMessage") or "prompt bloqueado na entrada")
    cands = d.get("candidates") or []
    if not cands:
        raise Filtrado("SEM_CANDIDATO",
                       "a resposta não trouxe candidato: %s" % json.dumps(d)[:600])
    c = cands[0]
    fr = c.get("finishReason")
    if fr and fr != "STOP":
        raise Filtrado(fr, c.get("finishMessage") or "(sem finishMessage)")
    partes = ((c.get("content") or {}).get("parts")) or []
    if not partes:
        raise Filtrado(fr or "SEM_PARTES",
                       "candidato sem partes: %s" % json.dumps(c)[:600])
    audio, texto = None, []
    for p in partes:
        inl = p.get("inlineData") or p.get("inline_data")
        if inl and str(inl.get("mimeType") or inl.get("mime_type") or "").startswith("audio/"):
            audio = inl
        elif p.get("text"):
            texto.append(p["text"])
    if audio is None:
        raise Filtrado(fr or "SEM_AUDIO",
                       "nenhuma parte trouxe áudio: %s" % json.dumps(c)[:600])
    return (base64.b64decode(audio["data"]),
            " ".join(texto).strip() or None,
            (d.get("usageMetadata") or {}).get("candidatesTokenCount"))


def _gerar_lyria(prompt_canonico, motor, tentativas, destino):
    chave_api = os.environ.get("GEMINI_API_KEY")
    if not chave_api:
        raise Erro("GEMINI_API_KEY não está no ambiente. As chaves deste repo "
                   "vivem no `env` dos settings do Claude Code — script fora de "
                   "sessão precisa dela exportada no shell.")
    api = motor["api"]
    variacoes = [None] + _variacoes_para(prompt_canonico, max(0, tentativas - 1))
    tentados, filtradas = [], 0
    for i, var in enumerate(variacoes[:max(1, tentativas)], start=1):
        prompt = prompt_canonico if var is None else moldar_prompt_com(prompt_canonico, var)
        print("tentativa %d/%d%s" % (i, max(1, tentativas),
                                     "" if var is None else " · variação: " + var),
              file=sys.stderr)
        tentados.append(prompt)
        d = _chamar_api(prompt, api, chave_api)
        try:
            bruto, texto, toks = _extrair_audio(d)
        except Filtrado as f:
            filtradas += 1
            print("  ⛔ RECUSADO pelo fornecedor [%s]: %s" % (f.motivo, f.mensagem),
                  file=sys.stderr)
            continue
        with open(destino, "wb") as fh:
            fh.write(bruto)
        return {"prompt": prompt, "estrutura_declarada": texto,
                "tokens": toks, "tentativas": i, "filtradas": filtradas}
    print("\nas %d tentativas foram recusadas. O que foi pedido:" % len(tentados),
          file=sys.stderr)
    for i, p in enumerate(tentados, 1):
        print("  %d. %s" % (i, p), file=sys.stderr)
    raise Erro("geração filtrada em todas as %d tentativas — troque a vibe "
               "(não desligue o filtro)." % len(tentados), 4)


def moldar_prompt_com(prompt_canonico, variacao):
    """Insere a variação no prompt já moldado, antes do bloco de proibições."""
    marca = " No vocals,"
    if marca in prompt_canonico:
        i = prompt_canonico.index(marca)
        return (prompt_canonico[:i] + " Variation: " + variacao.rstrip(".") + "."
                + prompt_canonico[i:])
    return prompt_canonico + " Variation: " + variacao.rstrip(".") + "."


def _gerar_arquivo(prompt_canonico, motor, tentativas, destino):
    """Motor `arquivo`: a faixa vem de fora (biblioteca licenciada, CC0, CC-BY).

    É o fallback e o caminho de quem não quer IA. A licença NÃO tem default:
    quem traz a faixa declara, senão o registro sairia mentindo."""
    de = motor.get("de")
    if not de or not os.path.exists(de):
        raise Erro("motor `arquivo` precisa de --de <arquivo existente>")
    shutil.copyfile(de, destino)
    return {"prompt": None, "estrutura_declarada": None, "tokens": None,
            "tentativas": 1, "filtradas": 0}


MOTORES = {"lyria": _gerar_lyria, "arquivo": _gerar_arquivo}


# --------------------------------------------------------------------- gerar
def _escolher_motor(dur_alvo_s, modelo):
    if modelo in ("arquivo",):
        return "arquivo", {"api": "arquivo", "preco_usd": 0.0, "dur_max_s": None}
    if modelo:
        if modelo not in MOTORES_LYRIA:
            raise Erro("--modelo desconhecido: %s (tenho %s)"
                       % (modelo, ", ".join(sorted(MOTORES_LYRIA)) + ", arquivo"))
        return "lyria", dict(MOTORES_LYRIA[modelo], nome=modelo)
    if dur_alvo_s is None:
        raise Erro("sem --dur não dá para escolher o modelo; passe --modelo")
    nome = "lyria-3-clip" if dur_alvo_s <= MOTORES_LYRIA["lyria-3-clip"]["dur_max_s"] \
        else "lyria-3-pro"
    return "lyria", dict(MOTORES_LYRIA[nome], nome=nome)


def gerar(vibe, dur_alvo_s, modelo=None, tentativas=3, out=None, tags=None,
          de=None, licenca=None, exige_atribuicao=None, autor=None, nome=None):
    _garantir_biblioteca()
    familia, motor = _escolher_motor(dur_alvo_s, modelo)
    if de:
        motor = dict(motor, de=de)
    prompt_canonico = moldar_prompt(vibe) if familia != "arquivo" else \
        ("arquivo:" + os.path.basename(de or ""))
    ch = _chave(prompt_canonico, motor.get("api", familia))

    ja = _por_chave(ch)
    if ja:
        arq = os.path.join(RAIZ_MUSICA, ja["arquivo"]) \
            if not os.path.isabs(ja["arquivo"]) else ja["arquivo"]
        if os.path.exists(arq):
            print("💰 já existe na biblioteca (chave %s) — ZERO requisição HTTP: %s"
                  % (ch, ja["nome"]), file=sys.stderr)
            if out:
                os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
                if os.path.abspath(out) != os.path.abspath(arq):
                    shutil.copyfile(arq, out)
            return ja
        print("aviso: registro %s existe mas o arquivo sumiu (%s) — gerando de novo"
              % (ja["nome"], arq), file=sys.stderr)

    base = nome or ("-".join((tags or ["trilha"])[:2]) + "-" + ch[:8])
    destino = os.path.join(TRACKS, base + ".mp3")
    reg_motor = MOTORES[familia](prompt_canonico, motor, tentativas, destino)

    med = medir_faixa(destino)
    if med["dur"] <= 0:
        raise Erro("a faixa gerada tem duração 0 — %s" % destino, 3)
    if dur_alvo_s and med["dur"] + 0.001 < dur_alvo_s:
        print("aviso: o motor entregou %.2fs para um alvo de %.2fs — o trilha.py "
              "vai fazer loop com crossfade." % (med["dur"], dur_alvo_s),
              file=sys.stderr)

    lic = licenca if licenca is not None else (
        LICENCA_LYRIA if familia == "lyria" else None)
    if lic is None:
        raise Erro("motor `arquivo` exige --licenca (o texto exato do direito de "
                   "uso). Licença é o que o índice existe para guardar.")
    reg = {
        "nome": base,
        "chave": ch,
        "arquivo": os.path.relpath(destino, RAIZ_MUSICA),
        "provedor": motor.get("api") if familia == "lyria" else "arquivo",
        "id_origem": None,
        "licenca": lic,
        "exige_atribuicao": bool(exige_atribuicao) if exige_atribuicao is not None
        else (familia != "lyria"),
        "synthid": familia == "lyria",
        "autor": autor,
        "prompt": reg_motor["prompt"],
        "vibe": vibe,
        "estrutura_declarada": reg_motor["estrutura_declarada"],
        "custo_usd": motor.get("preco_usd", 0.0) if familia == "lyria" else 0.0,
        "tentativas": reg_motor["tentativas"],
        "filtradas": reg_motor["filtradas"],
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sha256": sha256_arquivo(destino),
        "bytes": os.path.getsize(destino),
        "contrato": CONTRATO,
    }
    reg.update(med)
    registrar(reg)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        shutil.copyfile(destino, out)
    print("faixa: %s · %.2fs · I=%.1f LUFS · TP=%+.1f dBFS · máscara %.1f%% · "
          "dinâmica %.1f dB · US$ %.2f · %d tentativa(s), %d filtrada(s)"
          % (base, med["dur"], med["i_lufs"], med["tp_dbfs"],
             100 * med["mascara_pct"], med["dinamica_db"], reg["custo_usd"],
             reg["tentativas"], reg["filtradas"]), file=sys.stderr)
    return reg


# -------------------------------------------------------------------- avaliar
def avaliar(arquivos, voz, mascara_max, amostras_dir=None):
    """A MEDIÇÃO ELIMINA; entre as sobreviventes, quem escolhe é o ouvido.

    O critério de eliminação é quanto a faixa ocupa a banda em que a voz vive.
    Foi assim na produção que originou esta régua: 29,6 % eliminada na hora,
    11,9 % escolhida, e a escolhida tinha também a menor dinâmica de curto
    prazo (17,3 dB contra 24–25 das outras) — música que respira muito puxa a
    atenção para si."""
    if not arquivos:
        raise Erro("--avaliar precisa de pelo menos um arquivo")
    linhas = []
    for f in arquivos:
        if not os.path.exists(f):
            raise Erro("não existe: %s" % f)
        m = medir_faixa(f)
        m["arquivo"] = f
        m["veredito"] = "elimina" if m["mascara_pct"] > mascara_max else "passa"
        linhas.append(m)
        if amostras_dir and voz:
            m["amostra"] = _amostra_ab(f, voz, amostras_dir)
    largura = max(len(os.path.basename(x["arquivo"])) for x in linhas)
    print("%-*s  %8s %8s %9s %8s  %s"
          % (largura, "faixa", "máscara", "dinâm.", "crest", "I LUFS", "veredito"),
          file=sys.stderr)
    for m in linhas:
        print("%-*s  %7.1f%% %7.1f %8.1f %8.1f  %s"
              % (largura, os.path.basename(m["arquivo"]), 100 * m["mascara_pct"],
                 m["dinamica_db"], m["crest_db"], m["i_lufs"], m["veredito"]),
              file=sys.stderr)
    print("corte: máscara > %.1f%% elimina (banda %g–%g Hz). %d candidata(s), "
          "%d passou(aram)." % (100 * mascara_max, BANDA_FALA_HZ[0], BANDA_FALA_HZ[1],
                                len(linhas), sum(1 for m in linhas
                                                 if m["veredito"] == "passa")),
          file=sys.stderr)
    return linhas


def _amostra_ab(musica, voz, destino):
    """13 s de voz+música, para o creator julgar de ouvido."""
    os.makedirs(destino, exist_ok=True)
    dv = probe(voz)["dur"]
    inicio = max(0.0, dv / 2 - AMOSTRA_S / 2)
    saida = os.path.join(destino, "ab-" + os.path.splitext(
        os.path.basename(musica))[0] + ".mp3")
    r = _run([_bin("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y",
              "-ss", "%.3f" % inicio, "-t", "%.3f" % AMOSTRA_S, "-i", voz,
              "-ss", "%.3f" % inicio, "-t", "%.3f" % AMOSTRA_S, "-i", musica,
              "-filter_complex",
              "[0:a]aformat=sample_fmts=fltp[v];[1:a]aformat=sample_fmts=fltp,"
              "volume=-18dB[m];[v][m]amix=inputs=2:duration=first:normalize=0[a]",
              "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k", saida])
    if r.returncode != 0:
        raise Erro("amostra A/B falhou:\n%s" % r.stderr[-800:], 3)
    return saida


# ------------------------------------------------------------------------ CLI
USO = __doc__


def _parse(argv):
    a = {"vibe": None, "dur": None, "modelo": None, "tentativas": 3, "out": None,
         "tags": None, "de": None, "licenca": None, "autor": None, "nome": None,
         "exige_atribuicao": None, "avaliar": [], "voz": None, "dir": None,
         "mascara_max": None, "amostras": None, "listar": False}
    val = {"--vibe": "vibe", "--dur": "dur", "--modelo": "modelo",
           "--tentativas": "tentativas", "--out": "out", "--tags": "tags",
           "--de": "de", "--licenca": "licenca", "--autor": "autor",
           "--nome": "nome", "--voz": "voz", "--dir": "dir",
           "--mascara-max-pct": "mascara_max", "--amostras": "amostras"}
    i, modo_avaliar = 0, False
    while i < len(argv):
        x = argv[i]
        if x in ("-h", "--help"):
            print(USO, file=sys.stderr)
            sys.exit(0)
        if x == "--avaliar":
            modo_avaliar = True
        elif x == "--listar":
            a["listar"] = True
        elif x == "--exige-atribuicao":
            a["exige_atribuicao"] = True
        elif x in val:
            modo_avaliar = False
            if i + 1 >= len(argv):
                raise Erro("%s espera um valor" % x)
            v = argv[i + 1]
            if x in ("--dur", "--mascara-max-pct"):
                v = float(v)
            elif x == "--tentativas":
                v = int(v)
            a[val[x]] = v
            i += 1
        elif x.startswith("-"):
            raise Erro("opção desconhecida: %s" % x)
        elif modo_avaliar:
            a["avaliar"].append(x)
        else:
            raise Erro("argumento solto: %r" % x)
        i += 1
    return a


def _mascara_max_do_perfil(a):
    if a["mascara_max"] is not None:
        return a["mascara_max"]
    p = _perfil.carregar(a["dir"], quieto=True) if a["dir"] else None
    t = (p or {}).get("trilha") or {}
    if "mascara_max_pct" in t:
        return float(t["mascara_max_pct"])
    raise Erro("sem limiar de eliminação: passe --mascara-max-pct ou --dir "
               "<dir-producao> com `trilha.mascara_max_pct` no perfil. "
               "Um limiar inventado no script é exatamente o que a SPEC-00 proíbe.")


def main(argv):
    if not argv:
        print(USO, file=sys.stderr)
        return 2
    a = _parse(argv)
    if a["listar"]:
        idx = ler_indice()
        print(json.dumps(idx, ensure_ascii=False, indent=1))
        print("%d faixa(s) em %s" % (len(idx), INDEX), file=sys.stderr)
        return 0
    if a["avaliar"]:
        avaliar(a["avaliar"], a["voz"], _mascara_max_do_perfil(a), a["amostras"])
        return 0
    if not a["vibe"] and not a["de"]:
        raise Erro("nada a fazer: passe --vibe (gerar) ou --de + --modelo arquivo "
                   "(registrar faixa de fora) ou --avaliar.\n\n%s" % USO)
    reg = gerar(a["vibe"] or os.path.basename(a["de"] or ""), a["dur"],
                modelo=a["modelo"], tentativas=a["tentativas"], out=a["out"],
                tags=[t for t in (a["tags"] or "").split(",") if t],
                de=a["de"], licenca=a["licenca"],
                exige_atribuicao=a["exige_atribuicao"], autor=a["autor"],
                nome=a["nome"])
    caminho = a["out"] or os.path.join(RAIZ_MUSICA, reg["arquivo"])
    print(os.path.abspath(caminho))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)
