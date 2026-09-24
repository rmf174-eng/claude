#!/usr/bin/env python3
"""envelope — detector acústico de silêncio/fala para a skill `transcribe`.

PROCEDÊNCIA E POR QUE É CÓPIA, NÃO IMPORT
-----------------------------------------
O mecanismo (RMS em janelas → dB → piso por PERCENTIL, não absoluto) vem do nosso
próprio `.claude/skills/edit-video/scripts/bordas.py:27-38` (`envelope`) e
`:123-126` (`piso_local`). Foi **copiado de propósito**: a skill `transcribe` é
usada por benchmark, VSL, ingest de call e por quem instale só ela — acoplá-la à skill
de edição por ~20 linhas sairia mais caro que duplicá-las.

A divergência de resolução também é intencional:

    bordas.py   10 ms @ 48 kHz   decide PONTO DE CORTE (fonema importa)
    aqui        50 ms @  8 kHz   só LOCALIZA SILÊNCIO (região importa)

POR QUE O PISO É PERCENTIL E NUNCA UM NÚMERO FIXO
-------------------------------------------------
Medido em `bordas.py:75-92` (produção peca-01, 2026-07-31, gravada num
café): o piso real das pausas é **−44 dB de mediana** contra o default de −52.
Com gate absoluto o ruído de sala é lido como fala em 23 de 23 segmentos.
O ref-A comete exatamente esse erro (`tools/referencias/ref-A/helpers/
speech_regions.py:73`, `--noise` fixo em −33 dB) — está aqui como contraexemplo.

Nenhum valor de formato de entrega vive neste arquivo: `SR_ANALISE` é a taxa em
que se MEDE o envelope, não a taxa em que se entrega áudio. O arquivo de entrada
é lido como estiver.
"""
import subprocess
import numpy as np

SR_ANALISE = 8000   # taxa de ANÁLISE do envelope (não é formato de entrega)
WIN = 0.05          # 50 ms por janela


def envelope(audio_path: str, sr: int = SR_ANALISE, win: float = WIN) -> np.ndarray:
    """dB RMS por janela de `win` segundos. Decodifica o arquivo como estiver."""
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", audio_path, "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    w = int(win * sr)
    n = len(a) // w
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    rms = np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def piso_adaptativo(db: np.ndarray, lo: float = None, hi: float = None,
                    pct: int = 20, margem: float = 10.0, win: float = WIN) -> float:
    """Percentil `pct` do trecho + `margem` dB. Acompanha a sala; imune a um vale.

    `lo`/`hi` em SEGUNDOS (None = arquivo inteiro).
    """
    i0 = 0 if lo is None else max(0, int(lo / win))
    i1 = len(db) if hi is None else min(len(db), int(hi / win) + 1)
    if i1 <= i0:
        return -60.0 + margem
    return float(np.percentile(db[i0:i1], pct)) + margem


def _blocos(mask: np.ndarray, win: float):
    """(ini, fim) em segundos de cada corrida de True em `mask`."""
    if len(mask) == 0:
        return []
    d = np.diff(mask.astype(np.int8))
    ini = list(np.flatnonzero(d == 1) + 1)
    fim = list(np.flatnonzero(d == -1) + 1)
    if mask[0]:
        ini.insert(0, 0)
    if mask[-1]:
        fim.append(len(mask))
    return [(float(i) * win, float(f) * win) for i, f in zip(ini, fim)]


def vales(db: np.ndarray, t0: float, t1: float, piso: float,
          minimo: float = 0.25, win: float = WIN):
    """Trechos contínuos ABAIXO do piso, com pelo menos `minimo` segundos.

    Restrito a [t0, t1]; o resultado é recortado nessa janela.
    """
    i0, i1 = max(0, int(t0 / win)), min(len(db), int(t1 / win) + 1)
    if i1 <= i0:
        return []
    out = []
    for a, b in _blocos(db[i0:i1] < piso, win):
        a, b = a + i0 * win, b + i0 * win
        a, b = max(a, t0), min(b, t1)
        if b - a >= minimo:
            out.append((round(a, 3), round(b, 3)))
    return out


def regioes_de_fala(db: np.ndarray, piso: float, fecha: float = 0.5,
                    minima: float = 1.0, win: float = WIN):
    """Regiões ACIMA do piso, fechando buracos < `fecha` e descartando < `minima`."""
    if len(db) == 0:
        return []
    regs = _blocos(db >= piso, win)
    if not regs:
        return []
    juntas = [list(regs[0])]
    for a, b in regs[1:]:
        if a - juntas[-1][1] < fecha:
            juntas[-1][1] = b
        else:
            juntas.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in juntas if b - a >= minima]


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("uso: envelope.py <audio> [--pct 20] [--margem 10] "
              "[--fecha 0.5] [--minima 1.0]", file=sys.stderr)
        sys.exit(2)
    args = sys.argv[2:]
    def opt(nome, default, tipo=float):
        return tipo(args[args.index(nome) + 1]) if nome in args else default
    db = envelope(sys.argv[1])
    piso = piso_adaptativo(db, pct=opt("--pct", 20, int), margem=opt("--margem", 10.0))
    regs = regioes_de_fala(db, piso, fecha=opt("--fecha", 0.5),
                           minima=opt("--minima", 1.0))
    print(json.dumps({
        "duracao_analisada_s": round(len(db) * WIN, 3),
        "piso_db": round(piso, 2),
        "regioes": len(regs),
        "fala_s": round(sum(b - a for a, b in regs), 1),
    }, ensure_ascii=False))
