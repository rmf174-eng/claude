#!/usr/bin/env python3
"""nivel.py — ganho POR SEGMENTO (`gain_db`) e o teto da trilha (SPEC-08).

Duas coisas, e é importante que sejam duas:

    ganho    é do SEGMENTO. Resgata o take sussurrado, e só ele.
    teto     é da TRILHA. Entra uma vez, depois da soma, e é inerte quando
             ninguém passou do fundo de escala.

    ┌───────────── audio-exato.py, por segmento ─────────────┐
    │  slice do bruto → × ganho_linear(gain_db) → micro-fade │
    └────────────────────────────┬───────────────────────────┘
                                 ↓ posiciona/soma
                         limitar(y)  ← uma vez, na trilha inteira

🔴 GANHO GLOBAL É PROIBIDO. Resgatar um take baixo com compressor/ganho na
trilha inteira bombeia os takes que já estavam certos. O `gain_db` existe
exatamente para não fazer isso — é o mesmo princípio da referência
(`tools/referencias/ref-A/SKILL.md:501`), e é o único ponto em que os dois
pipelines concordam sem ressalva.

🔴 POR QUE O LIMITADOR É NUMPY E NÃO `alimiter` DO FFMPEG. Medido em 2026-08-08
nesta máquina: `alimiter` ATRASA o sinal em ~`attack` ms preservando a contagem
de amostras — +239 amostras (4,979 ms) com o attack default de 5 ms, +191
(3,979 ms) com `attack=4`. Aplicado como passe sobre o `audio-exato.wav` isso
desloca a trilha inteira e trunca a cauda, ou seja joga fora de graça o
invariante `soma_audio == soma_video` que custou a saga de 2026-07-25 (0,28 s de
deriva em 20 emendas). O teste de tendência da SKILL.md **não pegaria** — a
deriva é constante, tendência zero — mas a régua de ±3 ms sim. Um envelope de
ganho multiplicado ponto a ponto tem latência ZERO por construção: não há
buffer, há uma janela de olhar-adiante usada só para decidir o ganho.

    📎 Isto também explica um número do ref-A-TEARDOWN.md §4: a "deriva
    constante de +5,0 ms, tendência zero" medida no caminho default deles é a
    latência do `alimiter=limit=0.95` (attack default 5 ms) de `render.py:640`,
    não arredondamento de `adelay`.

🔴 E NÃO HERDAR `level_in=1:level_out=1` SEM `level=disabled`. Medido: aplica
ganho de `1/limit` no sinal inteiro (0,5 vira 0,52631 com `limit=0.95`). Um
"limitador" que SOBE o nível de material que não precisava de nada. O ref-A faz
isso em três lugares (`render.py:320`, `:640`, `:886`); a nossa SKILL.md:93 já
usa `level=disabled` e está certa.

⚠️ ISTO É PICO DE AMOSTRA, NÃO TRUE PEAK. Um sinal a 0 dBFS de pico de amostra
pode ter pico inter-amostra acima de 0 dBTP. Não é papel deste estágio: quem
mede e trava true peak é o `loudnorm`/`ebur128` de dois passes (`loudness.py`),
sobre o mix final com SFX. Esta spec não resolve clipping de entrega.

📐 O que vem do PERFIL DE PEÇA (`audio.limiter`) e o que fica aqui:

    perfil   teto_dbfs, lookahead_ms, release_ms   — propriedades do DESTINO
    aqui     BLOCO_MS, [GAIN_MIN_DB, GAIN_MAX_DB], [-12, 0] do teto
             — física: janela de envelope, ruído de sala subindo com a voz,
               fundo de escala do int16. Não é formato de peça.

CLI
    nivel.py <entrada.wav> [saida.wav] [--teto -1.0] [--relatorio]
"""
import json
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                   # defensivo: nivel.py roda sem o catálogo
    import perfil as perfil_mod        # noqa: E402
except ImportError:                    # pragma: no cover
    perfil_mod = None

CONTRATO = "benchmark.nivel-aplicado/v1"

# ── física, não formato (fica aqui pela regra de ouro da SPEC-00 §3.1) ────────
BLOCO_MS = 1.0
#  +12 dB é o teto do ref-A (`helpers/voice_levels.py:252-260`): passando disso o
#  ruído de sala sobe junto com a voz e "soa como outro microfone". −24 dB é a
#  fronteira em que abaixar deixa de ser nivelar e vira mutar — se o take é para
#  sumir, corte-o da EDL.
GAIN_MIN_DB, GAIN_MAX_DB = -24.0, 12.0
#  o teto vive em [−12, 0] dBFS. Acima de 0 é aceitar overflow na escrita
#  `(y * 32767).astype(np.int16)` do audio-exato.py.
TETO_MIN_DBFS, TETO_MAX_DBFS = -12.0, 0.0

# ── FALLBACK: o que vale quando o perfil não declara `audio.limiter` ──────────
#  teto 0 dBFS é DECISÃO, não esquecimento: o audio-exato.wav é intermediário
#  PCM, não entregável. O teto de entrega é true peak e quem o define é o
#  loudnorm de dois passes, depois do mix com SFX. Pôr −1 dBFS aqui roubaria
#  1 dB de um estágio que vai renormalizar de qualquer jeito, e mudaria o md5 de
#  toda produção existente sem nenhum ganho.
TETO_FALLBACK_DBFS = 0.0
LOOKAHEAD_FALLBACK_MS = 5.0
RELEASE_FALLBACK_MS = 60.0
#  sample rate só é usado para converter ms → amostras. O caminho canônico
#  (audio-exato.py) SEMPRE passa o sr do perfil; a CLI lê o do cabeçalho do WAV.
SR_FALLBACK = int(perfil_mod.FALLBACK_REELS["audio"]["sr"]) if perfil_mod else 48000

#  chaves que já foram digitadas errado ou que alguém vai digitar. Depois do
#  passthrough por lista NEGRA do bordas.py, um campo escrito errado atravessa
#  INTACTO até um consumidor que o ignora — passthrough silencioso é o mesmo
#  defeito com o sinal trocado.
_ALVO = "gain_db"
_CONFUNDIVEIS = {"gaindb", "gain", "ganho", "ganhodb", "gaindbs", "gaindecibel"}


class ErroNivel(Exception):
    """erro de dado do operador; a CLI vira sys.exit, a biblioteca propaga."""


# ────────────────────────────────────────────────────────── ganho por segmento
def ganho_linear(gain_db) -> float:
    """dB → fator multiplicativo. `0.0` devolve exatamente `1.0`."""
    g = float(gain_db)
    return 1.0 if g == 0.0 else float(10.0 ** (g / 20.0))


def _normaliza_chave(k: str) -> str:
    return "".join(c for c in str(k).lower() if c.isalnum())


def ler_gain_db(seg: dict, i: int = -1) -> float:
    """Lê e VALIDA `seg['gain_db']`. Ausente → `0.0`.

    Erro FATAL, nunca aviso, em três casos:
      · não-numérico (`"3"` é string, não dB);
      · fora de [GAIN_MIN_DB, GAIN_MAX_DB];
      · chave PARECIDA e errada (`gaindb`, `ganho`, `gain_dB`, …).

    O terceiro custa 3 linhas e fecha uma classe inteira de falha silenciosa: um
    `"gaindb": 6` atravessa o bordas.py, aparece na edl.json e é ignorado aqui
    — o operador vê o campo no arquivo e o áudio não muda.
    """
    onde = "segmento %d [%s]" % (i, seg.get("beat", "?")) if i >= 0 else "o segmento"
    for k in seg:
        if k == _ALVO:
            continue
        if _normaliza_chave(k) in _CONFUNDIVEIS:
            raise ErroNivel(
                "%s tem a chave %r, que NÃO é lida por ninguém.\n"
                "Você quis dizer `%s`? (o bordas.py passa campo desconhecido "
                "adiante intacto, então um nome errado chega até aqui e é "
                "ignorado em silêncio)" % (onde, k, _ALVO))
    if _ALVO not in seg:
        return 0.0
    v = seg[_ALVO]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ErroNivel(
            "%s tem `%s` = %r (%s). Tem que ser NÚMERO em dB, sem aspas."
            % (onde, _ALVO, v, type(v).__name__))
    g = float(v)
    if not (GAIN_MIN_DB <= g <= GAIN_MAX_DB):
        raise ErroNivel(
            "%s tem `%s` = %+g dB, fora da faixa [%+g, %+g].\n"
            "Acima de %+g dB o ruído de sala sobe junto com a voz; abaixo de "
            "%+g dB não é mais nivelar, é mutar — se o take é para sumir, "
            "corte-o da EDL." % (onde, _ALVO, g, GAIN_MIN_DB, GAIN_MAX_DB,
                                 GAIN_MAX_DB, GAIN_MIN_DB))
    return g


# ───────────────────────────────────────────────────────── teto (o limitador)
def _picos_por_bloco(y: np.ndarray, B: int) -> np.ndarray:
    """|y| máximo em cada bloco de B amostras (máximo TAMBÉM entre canais).

    Estéreo é limitador LINKADO de propósito: canal a canal, a imagem estéreo se
    desloca no ataque."""
    a = np.abs(y)
    if a.ndim > 1:
        a = a.max(axis=1)
    n = a.shape[0]
    nb = -(-n // B)                                  # ceil
    if nb * B != n:
        a = np.concatenate([a, np.zeros(nb * B - n, dtype=a.dtype)])
    return a.reshape(nb, B).max(axis=1).astype(np.float64)


def _min_janela_adiante(g: np.ndarray, L: int) -> np.ndarray:
    """gl[k] = min(g[k .. k+L]) — o ganho já está baixo quando o pico chega."""
    if L <= 0:
        return g.copy()
    pad = np.concatenate([g, np.full(L, g[-1], dtype=g.dtype)])
    jan = np.lib.stride_tricks.sliding_window_view(pad, L + 1)
    return jan.min(axis=1)


def limitar(y, teto_dbfs=None, sr=None, lookahead_ms=None, release_ms=None):
    """Limitador de pico com look-ahead e **latência zero**.

    Devolve `(sinal, relatorio)`. Se `max|y| <= teto`, devolve **o MESMO array**
    (`np.array_equal` verdadeiro, mesmo objeto) e `relatorio["atuou"] is False`.

    O teto é garantido POR CONSTRUÇÃO, não por medição: para toda amostra `n` do
    bloco `k`,  `gs[n] <= gl[k] <= g[k] = teto/p[k] <= teto/|y[n]|`,  logo
    `|y[n]·gs[n]| <= teto`. Não existe recorte por amostra em lugar nenhum do
    caminho — este módulo não tem `np.clip` e não deve ganhar um.

    Sem joelho suave e sem makeup, e isso é regra, não simplificação: qualquer
    coisa que toque o sinal ABAIXO do teto destrói a inércia e, com ela, a
    regressão bit a bit de toda produção que não usa o recurso.
    """
    teto_dbfs = TETO_FALLBACK_DBFS if teto_dbfs is None else float(teto_dbfs)
    sr = SR_FALLBACK if sr is None else int(sr)
    lookahead_ms = LOOKAHEAD_FALLBACK_MS if lookahead_ms is None else float(lookahead_ms)
    release_ms = RELEASE_FALLBACK_MS if release_ms is None else float(release_ms)
    if not (TETO_MIN_DBFS <= teto_dbfs <= TETO_MAX_DBFS):
        raise ErroNivel(
            "teto_dbfs = %+g fora de [%+g, %+g]. Acima de 0 dBFS é aceitar "
            "overflow na escrita int16; abaixo de %+g é o loudnorm da entrega "
            "renormalizando por cima." % (teto_dbfs, TETO_MIN_DBFS,
                                          TETO_MAX_DBFS, TETO_MIN_DBFS))
    if lookahead_ms < 0 or release_ms <= 0:
        raise ErroNivel("lookahead_ms >= 0 e release_ms > 0 (recebi %g e %g)"
                        % (lookahead_ms, release_ms))

    y = np.asarray(y)
    if y.dtype.kind != "f":
        raise ErroNivel("limitar() opera em ponto flutuante normalizado; recebi "
                        "dtype %s. Converta antes (int16/32768)." % y.dtype)
    teto = float(10.0 ** (teto_dbfs / 20.0))
    B = max(1, int(round(sr * BLOCO_MS / 1000.0)))
    rel = {"teto_dbfs": teto_dbfs, "lookahead_ms": lookahead_ms,
           "release_ms": release_ms, "bloco_ms": BLOCO_MS, "atuou": False,
           "pico_entrada": 0.0, "pico_saida": 0.0, "reducao_max_db": 0.0,
           "blocos_reduzidos": 0, "blocos_total": 0}
    if y.size == 0:
        return y, rel

    p = _picos_por_bloco(y, B)
    rel["blocos_total"] = int(p.shape[0])
    pico_in = float(p.max())
    rel["pico_entrada"] = pico_in
    if pico_in <= teto:                      # ← INÉRCIA: nada tocou o sinal
        rel["pico_saida"] = pico_in
        return y, rel

    with np.errstate(divide="ignore", invalid="ignore"):
        g = np.where(p > 0, np.minimum(1.0, teto / np.where(p > 0, p, 1.0)), 1.0)
    L = int(round(lookahead_ms / BLOCO_MS))
    gl = _min_janela_adiante(g, L)

    # RELEASE one-pole por bloco: desce na hora, sobe devagar. O laço é
    # sequencial de propósito — vetorizar isto quebra a monotonia do release, e
    # a monotonia é o que separa "limitador" de "modulação de ganho audível".
    alfa = float(np.exp(-B / (release_ms / 1000.0 * sr)))
    gr = np.empty_like(gl)
    ant = 1.0
    for k in range(gl.shape[0]):
        subindo = 1.0 - (1.0 - ant) * alfa
        ant = gl[k] if gl[k] < subindo else subindo
        gr[k] = ant

    # interpolação linear nos CENTROS de bloco + trava anti-overshoot: sem a
    # trava, a rampa entre dois centros pode ficar acima do gl do bloco do meio
    # e furar o teto por uma amostra.
    n = y.shape[0]
    centros = np.arange(gl.shape[0], dtype=np.float64) * B + (B - 1) / 2.0
    gs = np.interp(np.arange(n, dtype=np.float64), centros, gr)
    idx = np.minimum(np.arange(n) // B, gl.shape[0] - 1)
    gs = np.minimum(gs, gl[idx])

    saida = (y * (gs[:, None] if y.ndim > 1 else gs)).astype(y.dtype, copy=False)
    rel["atuou"] = True
    rel["pico_saida"] = float(np.abs(saida).max())
    rel["reducao_max_db"] = float(-20.0 * np.log10(max(float(gs.min()), 1e-12)))
    rel["blocos_reduzidos"] = int((gr < 1.0).sum())
    return saida, rel


# ──────────────────────────────────────────────────────────────────── config
def config(dir_producao=".", p=None) -> dict:
    """Resolve teto/lookahead/release: `perfil.audio.limiter` → FALLBACK daqui.

    `p` é o perfil já carregado (o audio-exato.py tem um na mão; carregar duas
    vezes é IO à toa). Sem perfil e sem catálogo, os FALLBACK deste módulo — que
    são o comportamento de hoje do código, byte a byte."""
    cfg = {"teto_dbfs": TETO_FALLBACK_DBFS,
           "lookahead_ms": LOOKAHEAD_FALLBACK_MS,
           "release_ms": RELEASE_FALLBACK_MS,
           "bloco_ms": BLOCO_MS,
           "origem": "fallback"}
    if p is None and perfil_mod is not None:
        try:
            p = perfil_mod.carregar(dir_producao, quieto=True)
        except Exception:                                     # pragma: no cover
            p = None
    lim = (p or {}).get("audio", {}).get("limiter") if isinstance(p, dict) else None
    if isinstance(lim, dict):
        for k in ("teto_dbfs", "lookahead_ms", "release_ms"):
            if k in lim and lim[k] is not None:
                cfg[k] = float(lim[k])
                cfg["origem"] = "perfil"
    if not (TETO_MIN_DBFS <= cfg["teto_dbfs"] <= TETO_MAX_DBFS):
        raise ErroNivel("perfil.audio.limiter.teto_dbfs = %+g fora de [%+g, %+g]"
                        % (cfg["teto_dbfs"], TETO_MIN_DBFS, TETO_MAX_DBFS))
    return cfg


def limitar_cfg(y, cfg: dict, sr: int):
    """`limitar` dirigido pelo dict do `config()`.

    Existe para que NENHUM outro script precise nomear `teto_dbfs` — o valor do
    destino entra por uma porta só, e o grep que procura literal de formato fora
    deste arquivo continua dando zero."""
    y, rel = limitar(y, cfg["teto_dbfs"], sr, cfg["lookahead_ms"], cfg["release_ms"])
    rel["origem"] = cfg.get("origem", "fallback")
    return y, rel


# ─────────────────────────────────────────────────────────────────────── CLI
def _ler_wav(caminho):
    with wave.open(caminho, "rb") as w:
        if w.getsampwidth() != 2:
            raise ErroNivel("%s: só PCM 16 bits (sampwidth=%d)"
                            % (caminho, w.getsampwidth()))
        c, sr = w.getnchannels(), w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    a = a.astype(np.float32) / 32768
    return (a.reshape(-1, c) if c > 1 else a), sr, c


def _grava_wav(caminho, y, sr, canais):
    pcm = (y * 32767).astype(np.int16)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(canais)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _cli(argv):
    pos, teto, relatorio = [], None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--teto":
            i += 1
            if i >= len(argv):
                raise ErroNivel("--teto pede um valor em dBFS")
            teto = float(argv[i])
        elif a == "--relatorio":
            relatorio = True
        elif a.startswith("--"):
            raise ErroNivel("flag desconhecida: %s" % a)
        else:
            pos.append(a)
        i += 1
    if not pos:
        print("uso: nivel.py <entrada.wav> [saida.wav] [--teto -1.0] [--relatorio]",
              file=sys.stderr)
        return 64
    y, sr, canais = _ler_wav(pos[0])
    y, rel = limitar(y, teto, sr)
    if len(pos) > 1:
        _grava_wav(pos[1], y, sr, canais)
        print(os.path.abspath(pos[1]))
    if relatorio or len(pos) == 1:
        print(json.dumps(rel, indent=1, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_cli(sys.argv[1:]))
    except ErroNivel as e:
        sys.exit("ERRO: %s" % e)
