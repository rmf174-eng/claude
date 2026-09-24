#!/usr/bin/env python3
"""prosodia.py — quanta ÊNFASE tem cada palavra, medida no áudio (SPEC-14 §3.2 passo 1).

O envelope RMS de 10 ms já decide ONDE CORTAR neste repo desde 2026-07-25
(`bordas.py`). Ninguém nunca perguntou a ele QUAL PALAVRA foi dita com mais
força. É o mesmo dado, outra pergunta, custo zero de API — e é o que o diretor
de legenda do ref-A (`caption_style.py`, decide só por lista de palavras) não
tem como fazer.

O que sai, por palavra:

    realce_db       pico da palavra − mediana dos picos das palavras DA FRASE
    alongamento     (dur/char da palavra) ÷ mediana(dur/char) DA FRASE
    pausa_antes_ms  start_w − end_{w-1}
    pausa_depois_ms start_{w+1} − end_w
    piso_local_db   ruído de fundo em volta da palavra (percentil 15, raio 0,6 s)

TRÊS DECISÕES QUE EVITAM ARMADILHAS JÁ PAGAS NESTE REPO

1. FOLGA DE ±80 ms NA JANELA DO PICO, obrigatória. O Deepgram quantiza
   timestamp em 80 ms (`edit-video/SKILL.md`: "nunca trate um delta de ±0,08 s
   como sinal"). Medir o pico só dentro de [start, end] perde o ataque de metade
   das palavras. Pela mesma razão, NENHUM critério desta spec pode depender de
   uma diferença de tempo menor que 80 ms.

2. A REFERÊNCIA É A FRASE, NÃO A PEÇA. Comparar contra a mediana global reelege
   sistematicamente o trecho gravado mais alto — e num take único com
   aproximação de câmera isso é uma região inteira do vídeo, não uma palavra.

3. O ÁUDIO MEDIDO É O PRÉ-LIMITER (`v1-graded`/`v1-montado`). O remux final
   aplica `alimiter` e o loudnorm de 2 passes comprime exatamente a dinâmica que
   estamos medindo: medir no entregável é medir a compressão, não a creator.
   Quem chama decide o arquivo; aqui só se avisa (o diretor grava a procedência).

⚠️ O ENVELOPE DE BANDA LARGA É CEGO PARA CONSOANTE SURDA. Documentado em
`edit-video/SKILL.md`: o /ʁ/ de "Resumindo" tem RMS −34 dB e "parece vale".
Consequência: palavra que ABRE em fricativa surda ou nasal tem o pico
subestimado. A mitigação barata e suficiente é a folga de ±80 ms — análise por
banda é outro trabalho, e o critério de aceite 1 mede se o resultado já é bom o
bastante sem ela.

🔒 O envelope é REIMPLEMENTADO aqui, não importado de `bordas.py`, por dois
motivos (SPEC-14 §9): (a) `bordas.py` é arquivo de outras specs e importar cria
acoplamento entre skills que hoje só se falam por arquivo; (b) o `bordas.py`
mede o BRUTO e o diretor mede o MONTADO.

CLI
    prosodia.py <audio> <captions.json> [--perfil p.json] [--json]
"""
import json
import os
import subprocess
import sys

import numpy as np

# FÍSICA (não é valor de formato): a janela de RMS é de 10 ms, o piso de silêncio
# é percentil 15 num raio de 0,6 s. Mesmos números de `bordas.py`, pelo mesmo
# motivo — são propriedades da fala, não da peça.
WIN = 0.01
RAIO_PISO = 0.6

# A quantização de timestamp do Deepgram. Também não é formato: é a régua do ASR.
QUANT_S = 0.08


def envelope(src: str, sr: int, cache: dict | None = None) -> np.ndarray:
    """dB RMS em janelas de 10 ms do áudio de `src`. Espelho de bordas.py:51-63."""
    cache = {} if cache is None else cache
    chave = (src, sr)
    if chave not in cache:
        p = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vn",
             "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True,
        )
        a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
        if a.size == 0:
            raise SystemExit(f"prosodia: ffmpeg não devolveu áudio de {src}")
        w = int(WIN * sr)
        n = len(a) // w
        rms = np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1))
        cache[chave] = 20 * np.log10(np.maximum(rms, 1e-7))
    return cache[chave]


def piso_local(db: np.ndarray, t: float, raio: float = RAIO_PISO) -> float:
    """ruído de fundo em volta de t (percentil 15 — imune a um vale isolado).

    Espelho de bordas.py:146-149.
    """
    lo, hi = max(0, int((t - raio) / WIN)), min(len(db), int((t + raio) / WIN))
    return float(np.percentile(db[lo:hi], 15)) if hi > lo else -60.0


def pico(db: np.ndarray, ini_s: float, fim_s: float, folga: float = QUANT_S) -> float:
    """pico de dB no CORPO da palavra, com a folga da quantização do ASR."""
    lo = max(0, int((ini_s - folga) / WIN))
    hi = min(len(db), max(lo + 1, int((fim_s + folga) / WIN)))
    if hi <= lo:
        return -60.0
    return float(np.max(db[lo:hi]))


PONTUACAO_FORTE = ".!?…"


def frases(palavras: list[dict], pausa_frase_ms: float) -> list[list[int]]:
    """Índices das palavras agrupados em FRASES.

    Fronteira = pausa ≥ `pausa_frase_ms` OU pontuação forte no fim da palavra.
    É a unidade de referência do realce: comparar contra a peça inteira reelege
    o trecho gravado mais alto.
    """
    grupos: list[list[int]] = []
    atual: list[int] = []
    for i, w in enumerate(palavras):
        atual.append(i)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        if prox is None:
            break
        pausa = prox["startMs"] - w["endMs"]
        forte = w["text"].strip().rstrip("\"'”’)").endswith(tuple(PONTUACAO_FORTE))
        if forte or pausa >= pausa_frase_ms:
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def _chars(texto: str) -> int:
    return max(1, len(texto.strip()))


def medir(db: np.ndarray, palavras: list[dict], pausa_frase_ms: float) -> list[dict]:
    """A tabela de prosódia, uma linha por palavra de `palavras` (Caption[])."""
    grupos = frases(palavras, pausa_frase_ms)
    frase_de = {}
    for gi, g in enumerate(grupos):
        for i in g:
            frase_de[i] = gi

    picos = [pico(db, w["startMs"] / 1000.0, w["endMs"] / 1000.0) for w in palavras]
    dpc = [
        (w["endMs"] - w["startMs"]) / 1000.0 / _chars(w["text"])
        for w in palavras
    ]

    ref_pico, ref_dpc = {}, {}
    for gi, g in enumerate(grupos):
        ref_pico[gi] = float(np.median([picos[i] for i in g]))
        d = [dpc[i] for i in g if dpc[i] > 0]
        ref_dpc[gi] = float(np.median(d)) if d else 0.0

    saida = []
    for i, w in enumerate(palavras):
        gi = frase_de[i]
        ant = palavras[i - 1] if i > 0 else None
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        along = (dpc[i] / ref_dpc[gi]) if ref_dpc[gi] > 0 else 1.0
        meio = (w["startMs"] + w["endMs"]) / 2000.0
        saida.append({
            "idx": i,
            "text": w["text"].strip(),
            "startMs": w["startMs"],
            "endMs": w["endMs"],
            "frase": gi,
            "realce_db": round(picos[i] - ref_pico[gi], 2),
            "alongamento": round(along, 3),
            "pausa_antes_ms": (w["startMs"] - ant["endMs"]) if ant else None,
            "pausa_depois_ms": (prox["startMs"] - w["endMs"]) if prox else None,
            "piso_local_db": round(piso_local(db, meio), 2),
        })
    return saida


# —————————————————————————————————————————————————————————————————————————
# espelho de MotionKit.tsx:184-185 (writeDurationS)
#
# Mora AQUI, e não no diretor, por um motivo mecânico: `diretor-legenda.py` tem
# hífen no nome e não é importável por `import`. O teste do critério 6 importa
# desta função.
#
# ⚠️ Se esta fórmula divergir do TSX, a partitura promete uma sequencialidade
# que a tela não cumpre. O critério de aceite 6 compara as duas implementações
# sobre a mesma amostra de strings.
def write_duration_s(texto: str, fpc: float, fps: float) -> float:
    return (_len_js(texto.replace("\n", " ")) * fpc + 2) / fps


def _len_js(s: str) -> int:
    """`String.prototype.length` do JavaScript: unidades UTF-16, não code points.

    🐛 DIVERGÊNCIA REAL, achada pelo gate do critério 6 em 2026-08-08. O `len()`
    do Python conta code points; o `.length` do JS conta unidades UTF-16, e todo
    caractere fora do BMP (emoji, por exemplo) vale 2 lá e 1 aqui. Em
    `"emoji 🔴 no meio"` o Python dava 0,5167 s e o TSX 0,5467 s — 30 ms de
    janela a menos, num invariante que existe justamente para garantir que dois
    elementos não se sobreponham.

    Quem renderiza é o TSX, então quem tem razão é o TSX. Este é o espelho.
    """
    return len(s.encode("utf-16-le")) // 2


def carrega_captions(arq: str) -> list[dict]:
    c = json.load(open(arq))
    if not isinstance(c, list) or not c:
        raise SystemExit(f"prosodia: {arq} não é um Caption[] não-vazio")
    return [w for w in c if w.get("text", "").strip() != ""]


def _funde(base: dict, novo: dict) -> dict:
    """merge profundo por chave — a mesma semântica de perfil.py:_mesclar."""
    saida = dict(base)
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict):
            saida[k] = _funde(saida[k], v)
        else:
            saida[k] = v
    return saida


def carrega_perfil(arq: str) -> dict:
    """Um perfil de peça COMPLETO a partir de `arq`.

    Dois casos, e a diferença é do catálogo, não nossa:

      • `<dir-producao>/perfil.json` — já é o snapshot resolvido pela SPEC-00.
        Vem inteiro; nada a fazer.
      • `perfis/<nome>.json` — é uma CAMADA do catálogo, e sozinha não tem
        `audio.sr` nem `video.fps`. Aqui se funde `_base.json` embaixo, que é
        exatamente o que `perfil.py resolver` faz nas duas primeiras camadas.

    🔒 Não importamos `perfil.py`: ele mora em outra skill, e as skills deste
    repo se falam por ARQUIVO. O que se copia é a semântica de merge (7 linhas),
    não o módulo.
    """
    p = json.load(open(arq))
    p.pop("_comentario", None)
    base = os.path.join(os.path.dirname(os.path.abspath(arq)), "_base.json")
    if os.path.basename(arq) != "_base.json" and os.path.isfile(base):
        b = json.load(open(base))
        b.pop("_comentario", None)
        p = _funde(b, p)
    return p


def _sr_do_perfil(arq_perfil: str | None) -> int:
    if arq_perfil and os.path.exists(arq_perfil):
        sr = (carrega_perfil(arq_perfil).get("audio") or {}).get("sr")
        if sr:
            return int(sr)
    raise SystemExit(
        "prosodia: sem --perfil com audio.sr. O sample rate é VALOR DE FORMATO "
        "e vem do perfil de peça (SPEC-00), nunca do script."
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 64
    audio, cap = argv[0], argv[1]
    perfil = argv[argv.index("--perfil") + 1] if "--perfil" in argv else None
    pausa_frase = float(
        argv[argv.index("--pausa-frase-ms") + 1] if "--pausa-frase-ms" in argv else 700
    )
    sr = _sr_do_perfil(perfil)
    palavras = carrega_captions(cap)
    db = envelope(audio, sr)
    print(
        f"prosodia: {len(db)} janelas de {WIN * 1000:.0f} ms "
        f"({len(db) * WIN:.2f} s de áudio) · {len(palavras)} palavras · sr {sr}",
        file=sys.stderr,
    )
    tab = medir(db, palavras, pausa_frase)
    if "--json" in argv:
        print(json.dumps(tab, ensure_ascii=False))
        return 0
    print("%6s %-18s %8s %8s %9s %9s" %
          ("t", "palavra", "realce", "along", "pausa+", "piso"))
    for r in sorted(tab, key=lambda x: -x["realce_db"]):
        print("%6.2f %-18s %+7.1f %7.2fx %7s %8.1f" % (
            r["startMs"] / 1000, r["text"], r["realce_db"], r["alongamento"],
            r["pausa_depois_ms"] if r["pausa_depois_ms"] is not None else "-",
            r["piso_local_db"],
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
