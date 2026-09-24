#!/usr/bin/env python3
"""QC FONÉTICO das emendas: acha o que o ASR e o RMS de banda larga NÃO acham.

Uso: qc-fonemas.py <dir-da-producao> [--edl edl.json] [--v]

POR QUE ISTO EXISTE (2026-07-28, produção creator-2/nao-perdeu-a-peca-06)
O creator-1 assistiu o entregue e ouviu "…que acendem ela, RES-" — um pedaço de
"Resumindo", a palavra que a EDL removia. Os dois QCs que existiam passaram:
  • `qc-emendas-asr.py` → 0 flags. O Deepgram RECONSTRÓI pela linguagem: testei
    4 pontos de corte diferentes no mesmo trecho e ele devolveu "É de forma
    específica." em TODOS. ASR é régua de PALAVRA, nunca de borda.
  • `audit-emendas.py` → acusou CLIP-FIM, que é o flag esperado quando se remove
    uma palavra do meio (a fala continua depois do corte por construção). O sinal
    verdadeiro ficou indistinguível do ruído de flags.

A causa é fonética, e o RMS de banda larga é cego pros dois lados:

  (a) FRICATIVA SURDA tem energia baixa e PARECE silêncio no envelope.
      O /ʁ/ de "Resumindo" começa em 5,320 com RMS −34 dB (piso da sala −66): o
      envelope mostra um "vale" e o corte foi posto em 5,360, levando 40 ms de
      fricativa. Quem denuncia é a RAZÃO alta/baixa frequência — ela salta +18 dB
      em relação ao corpo da palavra.

  (b) A OCLUSÃO DE UMA PLOSIVA é silêncio DE VERDADE no meio da palavra.
      Em "específica", o silêncio de 38,53–38,60 (RMS −65 dB) não era o fim da
      palavra: era a oclusão do /k/. O burst vem em 38,60–38,63 e a vogal /a/ em
      38,635–38,89. O corte em 38,58 decepou o "-ca" — e ninguém ouviu porque o
      ASR completou a palavra sozinho.

Duas regras que ficam:
  • Vale no envelope NÃO é silêncio: pode ser consoante surda.
  • Silêncio curto entre fala e fala NÃO é fim de palavra: é oclusão de plosiva.

Este script não muda corte nenhum — ele classifica a vizinhança de cada emenda e
grita. A decisão continua sendo do humano (e o ouvido do creator-1 é a régua final).
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402

# FÍSICA (não é formato — não sai daqui):
N = 512            # ~10,7 ms de janela espectral
HOP = 96           # 2 ms de passo
OCLUSAO_MAX = 0.110    # silêncio mais curto que isto, entre fala e fala, é oclusão
VOGAL_MIN = 0.060      # bloco vozeado deste tamanho depois da oclusão = a palavra continua
SURDO_DB = -22.0       # (3–9 kHz) − (150–900 Hz) acima disto = som surdo
GATE_DB = 8.0          # RMS acima do piso pra contar como som
SALTO_DB = 12.0        # salto de razão que denuncia consoante NOVA entrando no corte
FIM_S = 0.045          # trecho analisado imediatamente antes/depois do corte


def fps_de(src):
    """fps REAL do bruto — não assumir 30.

    (2026-07-29) O bruto da creator-2 veio a 60fps e o FPS fixo em 30 devolvia todo
    corte no DOBRO do tempo: o último saía em '50,000s' num vídeo de 46,8s.
    Os tempos aqui são comparados contra a EDL, que está no tempo do BRUTO —
    então quem manda é o fps do arquivo medido, não o fps da entrega."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", src],
        capture_output=True, text=True).stdout
    # o csv pode vir com linha extra/vírgula sobrando (streams de dados do iPhone)
    r = r.splitlines()[0].strip().strip(",")
    num, _, den = r.partition("/")
    return float(num) / float(den or 1)


def espectro(src, ini, dur, SR):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(max(0.0, ini)), "-t", str(dur),
         "-i", src, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if len(a) < N:
        return np.array([]), np.array([]), np.array([])
    f = np.fft.rfftfreq(N, 1 / SR)
    lo, hi = (f >= 150) & (f < 900), (f >= 3000) & (f < 9000)
    win = np.hanning(N)
    ts, rms, razao = [], [], []
    for i in range(0, len(a) - N, HOP):
        seg = a[i:i + N]
        sp = np.abs(np.fft.rfft(seg * win))
        ts.append(ini + (i + N / 2) / SR)
        rms.append(20 * np.log10(max(np.sqrt((seg ** 2).mean()), 1e-9)))
        razao.append(20 * np.log10(max(sp[hi].mean(), 1e-9))
                     - 20 * np.log10(max(sp[lo].mean(), 1e-9)))
    return np.array(ts), np.array(rms), np.array(razao)


def blocos(rms, razao, ts, piso):
    """[(classe, t_ini, t_fim)] · 0 silêncio · 1 surdo · 2 vozeado"""
    c = np.zeros(len(rms), dtype=int)
    som = rms > piso + GATE_DB
    c[som & (razao > SURDO_DB)] = 1
    c[som & (razao <= SURDO_DB)] = 2
    out, i = [], 0
    while i < len(c):
        j = i
        while j + 1 < len(c) and c[j + 1] == c[i]:
            j += 1
        if ts[j] - ts[i] > 0.004:
            out.append((int(c[i]), float(ts[i]), float(ts[j])))
        i = j + 1
    return out


def analisa(src, t, lado, piso, SR, verbose=False):
    ts, rms, razao = espectro(src, t - 0.35, 0.70, SR)
    if not len(ts):
        return []
    bl = blocos(rms, razao, ts, piso)
    al = []

    if verbose:
        nome = {0: "silêncio", 1: "SURDO   ", 2: "vozeado "}
        print(f"    blocos em volta de {t:.3f}:", file=sys.stderr)
        for cl, a, b in bl:
            if abs(a - t) < 0.3 or abs(b - t) < 0.3:
                print(f"      {nome[cl]} {a:7.3f}–{b:7.3f} ({(b-a)*1000:4.0f} ms)", file=sys.stderr)

    # ——— (a) CONSOANTE VAZADA ————————————————————————————————————————
    # No FIM: os últimos 45 ms antes do corte ficaram muito mais "surdos" que o
    # corpo da palavra → entrou uma consoante que é da PRÓXIMA palavra.
    # No INÍCIO: espelhado, os 45 ms depois do corte.
    if lado == "fim":
        alvo = (ts > t - FIM_S) & (ts <= t)
        corpo = (ts > t - 0.30) & (ts <= t - 0.06)
    else:
        alvo = (ts >= t) & (ts < t + FIM_S)
        corpo = (ts >= t + 0.06) & (ts < t + 0.30)
    corpo = corpo & (rms > np.percentile(rms, 40))
    if alvo.any() and corpo.any():
        d = float(razao[alvo].mean() - razao[corpo].mean())
        r = float(rms[alvo].mean())
        # ⚠️ Além do salto espectral, o resquício precisa estar AUDÍVEL contra a
        # fala vizinha. Sem isto o teste continua gritando depois de um dip de
        # ganho — atenuar não muda a RAZÃO alta/baixa, só o nível (medido
        # 2026-07-28: o transiente do corte da creator caiu de −28,5 para
        # −35,7 dB, 25 dB abaixo da fala ao lado, e o alerta persistia).
        nivel_fala = float(np.percentile(rms[corpo], 75))
        abaixo = nivel_fala - r
        if d > SALTO_DB and r > piso + 12 and abaixo < 18:
            al.append(("CONSOANTE-VAZADA",
                       f"nos {FIM_S*1000:.0f} ms {'antes' if lado=='fim' else 'depois'} do corte a "
                       f"razão alta/baixa sobe {d:+.0f} dB sobre o corpo da palavra (RMS {r:.0f} dB): "
                       f"é uma consoante surda da palavra VIZINHA vazando. O envelope RMS não "
                       f"mostra isso — fricativa tem energia baixa e parece vale de silêncio."))

    # ——— (b) SÍLABA TRUNCADA (só no fim) ——————————————————————————————
    # O corte caiu dentro da OCLUSÃO de uma plosiva: silêncio curto, com fala
    # antes, e a palavra RETOMANDO logo depois com um bloco vozeado de verdade.
    if lado == "fim":
        atual = next((b for b in bl if b[1] - 0.003 <= t <= b[2] + 0.003), None)
        if atual and atual[0] == 0 and (atual[2] - atual[1]) <= OCLUSAO_MAX:
            k = bl.index(atual)
            fala_antes = k > 0 and bl[k - 1][0] != 0
            vozeado = next((b for b in bl[k + 1:]
                            if b[0] == 2 and (b[2] - b[1]) >= VOGAL_MIN), None)
            if fala_antes and vozeado and vozeado[1] - atual[2] < 0.120:
                al.append(("SILABA-TRUNCADA",
                           f"o corte cai num silêncio de {(atual[2]-atual[1])*1000:.0f} ms com fala "
                           f"antes ({bl[k-1][1]:.3f}–{bl[k-1][2]:.3f}) e vogal retomando em "
                           f"{vozeado[1]:.3f}–{vozeado[2]:.3f}: silêncio curto entre fala e fala é "
                           f"OCLUSÃO DE PLOSIVA, não fim de palavra. Fim real ≈ {vozeado[2]:.3f}."))
    return al


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    args = sys.argv[2:]
    edl_nome = args[args.index("--edl") + 1] if "--edl" in args else "edl.json"
    verbose = "--v" in args
    P = perfil_mod.carregar(d)
    SR = int(P["audio"]["sr"])
    os.chdir(d)
    # analisa o BRUTO nos pontos de corte (tempo do arquivo original), então não
    # usa timeline_real — só os segmentos, em v1 ou v2. `--edl <arquivo>` continua
    # valendo: o edl_io aceita diretório OU caminho de arquivo.
    edl = edl_io.segmentos(edl_nome)

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", edl[0]["src"], "-vn", "-ac", "1",
         "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    w = int(0.01 * SR)
    n = len(a) // w
    piso = float(np.percentile(
        20 * np.log10(np.maximum(np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1)), 1e-9)), 5))
    print(f"piso de sala: {piso:.1f} dB · {len(edl)} segmentos", file=sys.stderr)

    # cortes que JÁ EXISTEM no bruto (creator que entrega o vídeo montado):
    # alerta em cima de um deles é HERDADO, não introduzido pela nossa EDL.
    #
    # 🐛 DEFEITO CORRIGIDO EM 2026-08-08 (era latente e INVISÍVEL — nenhum QC pegava,
    # porque o QC é que estava errado). O tempo de cada corte saía de `(i+1)/30.0`
    # sobre frames decodificados na taxa NATIVA DO BRUTO. Num bruto de 60 fps — o
    # único bruto real deste repo é 60 fps — todo corte herdado saía no DOBRO do
    # tempo, o teste `abs(c - t) < 0.05` da linha do `herdado` nunca casava, e o QC
    # parava de marcar alerta como herdado: passava a acusar como NOSSO um corte que
    # a creator já tinha feito. É a mesma classe de bug corrigida em
    # cortes-do-bruto.py em 2026-07-29 (`fps_de()`); a correção não tinha chegado aqui.
    W, H = perfil_mod.raster_de_medicao(P)
    herdados = {}
    for src in {s["src"] for s in edl}:
        fps_bruto = fps_de(src)
        p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vf",
                            f"scale={W}:{H}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                           capture_output=True).stdout
        nf = len(p) // (W * H)
        fr = np.frombuffer(p, dtype=np.uint8)[: nf * W * H].reshape(nf, H, W).astype(np.float32)
        dd = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
        thr = max(float(dd.mean() + 4 * dd.std()), 8.0)
        herdados[src] = [(i + 1) / fps_bruto for i in range(len(dd)) if dd[i] > thr]
        print(f"  {src}: {len(herdados[src])} cortes herdados a {fps_bruto:g}fps "
              f"(raster {W}x{H}, limiar {thr:.1f})", file=sys.stderr)

    total = 0
    for i, seg in enumerate(edl):
        for lado, t in (("inicio", seg["start"]), ("fim", seg["end"])):
            if lado == "inicio" and t <= 0.02:
                continue   # começo do bruto não é emenda
            # 🔵 SPLIT DE PLANO não é emenda: quando o fim de um segmento é EXATAMENTE o
            # início do próximo no mesmo bruto, o corte é só de imagem (troca de
            # enquadramento) e o áudio atravessa contínuo. Todo flag fonético aí é falso
            # positivo POR CONSTRUÇÃO — o que o script vê é a palavra seguindo em frente,
            # que é justamente o esperado. Medido na produção peca-01 (2026-07-31):
            # 5 dos 7 alertas eram os 6 splits de plano dela.
            viz = edl[i - 1] if lado == "inicio" and i > 0 else (
                edl[i + 1] if lado == "fim" and i + 1 < len(edl) else None)
            if viz is not None and viz["src"] == seg["src"] and \
                    abs((viz["end"] if lado == "inicio" else viz["start"]) - t) < 1e-4:
                continue
            herdado = any(abs(c - t) < 0.05 for c in herdados.get(seg["src"], []))
            for tag, msg in analisa(seg["src"], t, lado, piso, SR, verbose):
                total += 0 if herdado else 1
                sufixo = ("  [HERDADO — este ponto já era um corte do bruto; o resquício veio "
                          "montado pela creator, nossa EDL só passa por ele]" if herdado else "")
                print(f"seg{i:02d} {lado:6} {t:8.3f}  [{tag}]{sufixo}\n        {msg}")
    print(f"\n{total} alerta(s) fonético(s)"
          + ("" if total else " — emendas limpas"), file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
