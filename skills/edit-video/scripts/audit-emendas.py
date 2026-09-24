#!/usr/bin/env python3
"""Audita cada emenda da EDL — a régua é o ENVELOPE ACÚSTICO do bruto, não o ASR.

Flags: CLIP-FIM (o corte cai antes da fala morrer), VAZA-PROX (a próxima palavra
do bruto entra dentro do corte), CLIP-INICIO (o corte come o ataque da 1ª palavra).

⚠️ Mudou em 2026-07-25 (produção peca-03): a versão anterior comparava o corte
com o `end` do ASR e acusava CLIP-FIM em 16 de 20 segmentos — todos FALSO-POSITIVO,
porque o Deepgram atrasa o end (deixou até 0,29s de silêncio na cauda de
"telepatia"/"silêncio") e também atrasa o start (0,13s no "M" de "Mulher").
Agora o teste é: existe energia de fala (>floor) DEPOIS do corte de fim, ou ANTES
do corte de início? Só isso é clipe de verdade. O transcript continua entrando
como rótulo e pro aviso de "segmento sem palavras" (estrangeirismo não reconhecido).

Uso: audit-emendas.py <dir-producao> [--floor -52]
(espera edl.json e o transcript de cada src; o caminho é resolvido pelo
`palavras.resolver_transcritos`, o MESMO das legendas — 6 portas, ordem
declarada, e erro fatal com a linha pronta quando não acha)."""
import importlib.util, json, sys, os, subprocess
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edl_io                 # noqa: E402
import perfil as perfil_mod   # noqa: E402
import qc_evidencia           # noqa: E402

# `palavras.py` tem hífen no nome: import por spec, como os outros scripts fazem.
_esp = importlib.util.spec_from_file_location(
    "palavras", os.path.join(os.path.dirname(os.path.abspath(__file__)), "palavras.py"))
palavras = importlib.util.module_from_spec(_esp)
_esp.loader.exec_module(palavras)

WIN = 0.01     # FÍSICA: janela de RMS de 10 ms
d = sys.argv[1] if len(sys.argv) > 1 else "."
# 📐 sample rate e piso saem do perfil de peça (SPEC-00); --floor continua vencendo.
_P = perfil_mod.carregar(d)
SR = int(_P["audio"]["sr"])
_piso = _P["ritmo"].get("floor", -52.0)
FLOOR = (float(sys.argv[sys.argv.index("--floor") + 1]) if "--floor" in sys.argv
         else (-52.0 if _piso == "auto" else float(_piso)))

# opera no BRUTO (start/end da EDL, no tempo do arquivo original), então não usa
# timeline_real — só precisa dos segmentos, em v1 ou v2.
edl = edl_io.segmentos(d)
srcs = sorted({s["src"] for s in edl})
# 🔴 A CONVENÇÃO DE CAMINHO É UMA SÓ, E ELA MORA NO `palavras.py` (2026-08-12,
# H47-10/F47-4). Aqui havia um `glob("take-*/transcript.json")` + `zip(srcs,
# takes)`: duas suposições, as duas erradas fora do nosso layout. Medido em campo
# por um agente externo, num fluxo real de cliente: a transcrição estava em
# `input/bruto/transcript.json` — onde o `transcribe.sh` DO PRÓPRIO PACOTE a
# escreveu — e este auditor "não achava as palavras". Pior que não achar: o `zip`
# CASA POR POSIÇÃO, então com 2 srcs e 2 takes em ordem diferente ele auditaria as
# emendas de um bruto contra as palavras do outro, em silêncio.
#
# O `resolver_transcritos` já tem 6 portas, ordem declarada e erro fatal com a
# linha pronta para colar. Duas cópias da convenção seriam duas verdades.
words = {}
_mapa, _como = palavras.resolver_transcritos(d, srcs)
for src in srcs:
    tr = json.load(open(_mapa[src]))
    words[src] = [(w["start"], w["end"], w["word"])
                  for w in tr["results"]["channels"][0]["alternatives"][0]["words"]]
print("transcritos: " + " · ".join("%s ← %s" % (os.path.basename(s), _como[s])
                                   for s in srcs), file=sys.stderr)

env_cache = {}
def env(src):
    """dB RMS em janelas de 10ms do áudio do bruto"""
    if src not in env_cache:
        p = src if os.path.isabs(src) else os.path.join(d, src)
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", p, "-vn",
                              "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                             capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
        w = int(WIN * SR)
        n = len(a) // w
        rms = np.sqrt((a[: n * w].reshape(n, w) ** 2).mean(axis=1))
        env_cache[src] = 20 * np.log10(np.maximum(rms, 1e-7))
    return env_cache[src]

def fala_em(db, t0, t1):
    """maior nível na janela [t0,t1) — >FLOOR significa fala cortada ali"""
    i, j = max(0, int(t0 / WIN)), min(len(db), int(t1 / WIN))
    return float(db[i:j].max()) if j > i else -99.0

falhas_duras = 0
alertas_revisaveis = 0
for i, seg in enumerate(edl):
    ws = words.get(seg["src"], [])
    db = env(seg["src"])
    inside = [w for w in ws if w[0] < seg["end"] and w[1] > seg["start"]]
    rot = f"'{inside[0][2]}…{inside[-1][2]}'" if inside else "(sem palavras)"
    flags = []
    if not inside:
        # energia sem palavra = estrangeirismo/nome próprio que o ASR não ouviu
        if fala_em(db, seg["start"], seg["end"]) > FLOOR:
            flags.append("SEM PALAVRAS mas COM ENERGIA (estrangeirismo? usar keyterm)")
        else:
            flags.append("SEM PALAVRAS e sem energia (segmento mudo?)")
    # clipe de fim: ainda havia fala nos 120ms seguintes ao corte
    depois = fala_em(db, seg["end"], seg["end"] + 0.12)
    if depois > FLOOR:
        flags.append(f"CLIP-FIM (fala a {depois:.0f}dB depois do corte)")
    # clipe de início: já havia fala nos 120ms anteriores ao corte
    antes = fala_em(db, max(0, seg["start"] - 0.12), seg["start"])
    if antes > FLOOR:
        flags.append(f"CLIP-INICIO (fala a {antes:.0f}dB antes do corte)")
    # vazamento: palavra que vem DEPOIS do fim lexical declarado em `fala`, mas
    # ainda entrou no segmento. Usar `depois da última inside` era impossível:
    # se começasse antes de `seg.end`, ela própria já estaria em `inside`.
    vazaram = qc_evidencia.vazamentos_apos_fala(seg.get("fala", ""), inside, seg["end"])
    if vazaram:
        flags.append(f"VAZA-PROX ('{vazaram[0][2]}' começa em {vazaram[0][0]:.2f})")
    classe = qc_evidencia.classificar(flags)
    falhas_duras += len(classe["falhas"])
    alertas_revisaveis += len(classe["alertas"])
    print(f"seg{i:02d} [{seg['start']:.2f}-{seg['end']:.2f}] {rot} "
          + (" · ".join(flags) if flags else "ok"))
print("\nenergia nas bordas: %d alerta(s) revisavel(is) · %d falha(s) dura(s). "
      "CLIP-INICIO/CLIP-FIM so bloqueiam quando outro QC confirma fonema, "
      "ataque ou vazamento lexical."
      % (alertas_revisaveis, falhas_duras), file=sys.stderr)
sys.exit(1 if falhas_duras else 0)
