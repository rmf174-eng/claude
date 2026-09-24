#!/usr/bin/env python3
"""Testes de FORMATO DE PEÇA (SPEC-06) — a mesma EDL em três aspectos.

    python3 tests/test_formato.py        (sai 0 se tudo passa)

Não existe `pytest` nesta máquina: a bateria é autocontida, como as irmãs.
A parte de ffmpeg é pequena (fontes sintéticas de 1 s) e se auto-pula com aviso
se o binário não existir — o que ela mede não dá para medir sem encoder.

O que cada bloco fecha, na ordem da §7 da SPEC-06:

  §7.1  [gate] ZERO CONSTANTE DE FORMATO   grep em montar.sh e audio-exato.py
  §7.5  [gate] DECIMAL É ERRO              29,97 aborta citando 30000/1001;
                                           30.0 é aceito como 30
  §3.4        JANELA DE ASPECTO            a tabela de casos + os invariantes
  §3.5        A GUARDA MORDE               silêncio / aviso / aviso alto / abort
  §1(a)       ANAMORFOSE MORREU            fonte 16:9 em perfil 9:16 sai SAR 1:1
  REGRESSÃO   o caminho canônico 9:16@30 muda EXATAMENTE em `setsar=1`, e os
              PIXELS decodificados são idênticos byte a byte

E os controles negativos, porque portão verde sem prova de dentes é
indistinguível de portão quebrado:

  D1  uma `janela_base` que ignora o aspecto (devolve sempre o quadro inteiro)
      tem que REPROVAR no teste de anamorfose
  D2  um `vf_montagem` sem `setsar=1` tem que REPROVAR no teste de SAR
  D3  uma guarda que só avisa (nunca aborta) tem que REPROVAR no teste do abort
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
sys.path.insert(0, SCRIPTS)
import perfil as P   # noqa: E402

falhas = []
checagens = [0]
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def ok(cond, msg):
    checagens[0] += 1
    if not cond:
        falhas.append(msg)
    print(("  ok  " if cond else "  ✗   ") + msg)


def perfil_de(nome=None, **video):
    """Perfil resolvido em memória (sem tocar disco nenhum) para os testes."""
    if nome is None:
        p = json.loads(json.dumps(P.FALLBACK_REELS))
    else:
        p = P.sobre_base(P._ler(os.path.join(P.DIR_PERFIS, nome + ".json")))
    p["video"].update(video)
    return p


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


# ═════════════════════════════════════════ §7.1 [gate] zero constante de formato
print("§7.1 [gate] nenhum valor de formato dentro do código executável")
import re   # noqa: E402

RE_FORMATO = re.compile(r"(scale=|crop=)[0-9]+:[0-9]+|fps=30|1080|1920|0\.034")
for nome in ("montar.sh", "audio-exato.py"):
    alvo = os.path.join(SCRIPTS, nome)
    linhas = open(alvo, encoding="utf-8").read().splitlines()
    exec_ruins = []
    for n, l in enumerate(linhas, 1):
        s = l.strip()
        if not s or s.startswith("#"):
            continue                       # comentário e doc podem citar o número
        if RE_FORMATO.search(l):
            exec_ruins.append("%s:%d %s" % (nome, n, s[:90]))
    ok(not exec_ruins,
       "%s: 0 linha executável com constante de formato (varreu %d linhas)%s"
       % (nome, len(linhas), "" if not exec_ruins else " — " + "; ".join(exec_ruins)))
# controle: a régua ACHA quando o valor está lá
ok(bool(RE_FORMATO.search('  VF="scale=1080:1920,fps=30"')),
   "controle: a régua acusa a linha original do montar.sh pré-SPEC-00")


# ══════════════════════════════════════════════════ §7.5 [gate] decimal é erro
print("\n§7.5 [gate] cadência: 30.0 é 30, 29.97 é erro que EXPLICA")
ok(P.fps_inteiro(30) == 30 and P.fps_inteiro(30.0) == 30,
   "fps 30 e 30.0 são a mesma cadência (30)")
ok(P.fps_inteiro(29.97) is None and P.fps_inteiro(True) is None,
   "29.97 não é cadência inteira; True (bool) também não")
ok(P.spf(perfil_de(None, fps=30.0)) == 1600,
   "spf com fps 30.0 = 1600 (não aborta por causa do `.0`)")
for ruim, frac in ((29.97, "30000/1001"), (23.976, "24000/1001"),
                   (59.94, "60000/1001")):
    m = P._msg_fps(ruim, 48000)
    ok(frac in m and "REJEITADO" in m,
       "a mensagem de fps %.3f cita %s e diz REJEITADO" % (ruim, frac))
erros = P.validar(perfil_de(None, fps=29.97))
ok(any("30000/1001" in e for e in erros),
   "validar() de um perfil 29.97 devolve erro citando 30000/1001 (%d erro(s))"
   % len(erros))
ok(P.validar(perfil_de(None, fps=30.0)) == [],
   "validar() de um perfil 30.0 não devolve erro nenhum")
# controle negativo: 29 é inteiro e MESMO ASSIM tem que cair (48000 % 29 ≠ 0)
ok(any("REJEITADO" in e for e in P.validar(perfil_de(None, fps=29))),
   "controle: fps 29 (inteiro!) também cai — a régua é sr %% fps, não `é float`")


# ═══════════════════════════════════════════════════ §3.4 a janela de aspecto
print("\n§3.4 janela de aspecto: a tabela")
CASOS = [
    # (W, H, sw, sh, esperado_w, esperado_h, rótulo)
    (1080, 1920, 2160, 3840, 2160, 3840, "9:16 → 9:16 (canônico): quadro inteiro"),
    (1080, 1920, 1080, 1920, 1080, 1920, "9:16 → 9:16 mesmo tamanho"),
    (1080, 1920, 1920, 1080, 608, 1080, "16:9 → 9:16: corta lateral"),
    (1080, 1920, 1280, 720, 406, 720, "16:9 720p → 9:16: corta lateral"),
    (1920, 1080, 2160, 3840, 2160, 1216, "9:16 → 16:9: corta topo/base"),
    (1080, 1080, 2160, 3840, 2160, 2160, "9:16 → 1:1: corta topo/base"),
    (1080, 1080, 1920, 1080, 1080, 1080, "16:9 → 1:1: corta lateral"),
]
for W, H, sw, sh_, ew, eh, rot in CASOS:
    bw, bh = P.janela_base(W, H, sw, sh_)
    ok((bw, bh) == (ew, eh),
       "%s → %dx%d (esperado %dx%d)" % (rot, bw, bh, ew, eh))
    ok(bw % 2 == 0 and bh % 2 == 0, "  … %dx%d é par (yuv420p exige)" % (bw, bh))
    ok(bw <= sw and bh <= sh_, "  … a janela cabe na fonte")
    # o erro se mede NA DIMENSÃO QUE FOI ARREDONDADA — medir na outra multiplica
    # o desvio pelo aspecto e reprova um arredondamento que está a 1 px do ideal.
    if bw < sw:
        err, dim = abs(bw - sh_ * W / H), "largura"
    elif bh < sh_:
        err, dim = abs(bh - sw * H / W), "altura"
    else:
        err, dim = 0.0, "nenhuma (quadro inteiro)"
    ok(err <= 1.0, "  … arredondamento da %s erra %.2f px do ideal (≤ 1)"
       % (dim, err))
bw, bh = P.janela_base(1080, 1920, 1920, 1080, ajuste="pad")
ok((bw, bh) == (1920, 1080), "ajuste=pad devolve o quadro inteiro, sempre")


# ══════════════════════════════════════════════════════ §3.5 a guarda morde
print("\n§3.5 a guarda de aspecto: silêncio, aviso, aviso alto, abort")
ok(P.guarda_aspecto(1080, 1920, 2160, 3840) is not None,
   "9:16 → 9:16 devolve razão (1,00) e não levanta nada")
ok(abs(P.guarda_aspecto(1080, 1920, 2160, 3840) - 1.0) < 1e-9,
   "  … a razão do caso canônico é exatamente 1,00")
ok(abs(P.razao_aspecto(1080, 1080, 1080, 1920) - 1.7778) < 1e-3,
   "9:16 → 1:1 tem r = 1,78 (faixa de AVISO ALTO, não de abort)")
ok(P.guarda_aspecto(1080, 1080, 1080, 1920) is not None,
   "  … e por isso ele NÃO aborta: 1:1 a partir de vertical é legítimo")
r = P.razao_aspecto(1080, 1920, 1920, 1080)
ok(abs(r - 3.1605) < 1e-3, "9:16 ← 16:9 tem r = 3,16 (a linha da §3.5)")
try:
    P.guarda_aspecto(1080, 1920, 1920, 1080, "crop")
    ok(False, "r = 3,16 com ajuste=crop DEVIA abortar e não abortou")
except P.ErroPerfil as e:
    ok("3.16" in str(e) or "3,16" in str(e).replace(".", ","),
       "r = 3,16 aborta e a mensagem cita a razão medida")
    ok("pad" in str(e) and "--permitir-aspecto-agressivo" in str(e),
       "  … e propõe as duas saídas reais (pad e --permitir-aspecto-agressivo)")
try:
    P.guarda_aspecto(1080, 1920, 1920, 1080, "pad")
    ok(True, "com ajuste=pad o mesmo caso NÃO aborta")
except P.ErroPerfil:
    ok(False, "ajuste=pad devia passar e abortou")
try:
    P.guarda_aspecto(1080, 1920, 1920, 1080, "crop", permitir=True)
    ok(True, "--permitir-aspecto-agressivo desarma o abort")
except P.ErroPerfil:
    ok(False, "permitir=True devia passar e abortou")
# D3 — controle negativo: guarda que só avisa não pode passar neste teste
def guarda_frouxa(W, H, sw, sh, *a, **kw):
    return P.razao_aspecto(W, H, sw, sh)
try:
    guarda_frouxa(1080, 1920, 1920, 1080, "crop")
    ok(True, "D3 controle: a guarda-frouxa plantada NÃO aborta (como previsto) — "
             "é o comportamento que o teste acima reprova")
except P.ErroPerfil:
    ok(False, "D3: o controle negativo abortou, o teste perdeu o sentido")


# ══════════════════════════════════ §1(a) anamorfose: o vf e (com ffmpeg) o SAR
print("\n§1(a) anamorfose")
# ⚠️ CONTRADIÇÃO DA PRÓPRIA SPEC, resolvida aqui: o critério F (fonte 1280x720 no
# perfil reels tem que sair como crop central) e o critério G (fonte 9:16 num
# perfil 16:9 tem que ABORTAR com r = 3,16) descrevem a MESMA razão de aspecto —
# a distância r é simétrica, ela não sabe a direção. Os dois só coexistem se o F
# rodar com o consentimento explícito, que é o que a guarda existe para exigir.
vf = P.vf_montagem(perfil_de("reels"), {}, 1280, 720,
                   permitir_aspecto_agressivo=True)
ok(vf.startswith("crop=406:720:"),
   "fonte 1280x720 no perfil reels começa com o crop de aspecto: %s" % vf.split(",")[0])
ok(",setsar=1," in vf or vf.endswith(",setsar=1"),
   "  … e o vf carrega setsar=1")
# D1/D2 — controles negativos
vf_sem_janela = ",".join(x for x in vf.split(",") if not x.startswith("crop="))
ok(not vf_sem_janela.startswith("crop="),
   "D1 controle: sem a janela de aspecto o vf volta a ser `scale` puro — que é "
   "exatamente o vf que produziu SAR 256:81 na medição da §1(a)")
vf_sem_setsar = ",".join(x for x in vf.split(",") if x != "setsar=1")
ok("setsar=1" not in vf_sem_setsar,
   "D2 controle: o vf plantado sem setsar existe e é distinguível do bom")

print("\n§3.4 um crop só, nunca dois")
for nome, sw, sh_, seg in (("reels", 1280, 720, {"zoom": 1.25, "cx": 0.5, "cy": 0.4}),
                           ("vsl", 2160, 3840, {"zoom": 1.3}),
                           ("quadrado", 2160, 3840, {"zoom": 1.2})):
    v = P.vf_montagem(perfil_de(nome), seg, sw, sh_,
                      permitir_aspecto_agressivo=True)
    ok(v.count("crop=") == 1, "%s + zoom: exatamente 1 `crop=` na cadeia (%s)"
       % (nome, v.split(",")[0]))
    ok(v.count("scale=") == 1, "  … e exatamente 1 `scale=`")

print("\n§3.4 pad: barras em vez de recorte")
vp = P.vf_montagem(perfil_de("reels", ajuste="pad"), {}, 1920, 1080)
ok("force_original_aspect_ratio=decrease" in vp and "pad=1080:1920" in vp,
   "ajuste=pad produz scale-decrease + pad: %s" % vp)
ok("crop=" not in vp, "  … e nenhum crop")


# ════════════════════════════════════ REGRESSÃO: o canônico muda só no setsar=1
print("\nregressão: o caminho 9:16@30 muda EXATAMENTE em `setsar=1`")
CANONICOS = [
    (None, {}, 2160, 3840, "scale=1080:1920,setsar=1,fps=30"),
    (None, {"zoom": 1.2, "cx": 0.42, "cy": 0.42}, 2160, 3840,
     "crop=1800:3200:7:13,scale=1080:1920,setsar=1,fps=30"),
    (None, {}, 1080, 1920, "scale=1080:1920,setsar=1,fps=30"),
]
for nome, seg, sw, sh_, esperado in CANONICOS:
    v = P.vf_montagem(perfil_de(nome), seg, sw, sh_)
    ok(v == esperado, "FALLBACK %s → %s" % (seg or "z=1", v))
    ok(v.replace(",setsar=1", "", 1) == esperado.replace(",setsar=1", "", 1),
       "  … tirando o setsar=1, é a string de antes da SPEC-06")


# ══════════════════════════════════════════════════════════ ponta a ponta (ffmpeg)
if not FFMPEG:
    print("\n⚠️  ffmpeg/ffprobe ausentes: os 2 blocos de render foram PULADOS")
else:
    print("\nponta a ponta: o SAR do arquivo que sai do encoder")
    tmp = tempfile.mkdtemp(prefix="spec06-")
    try:
        fonte = os.path.join(tmp, "h.mp4")
        sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", "testsrc2=size=1280x720:rate=30:duration=1",
           "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", fonte)
        p = perfil_de("reels")
        for rotulo, v in (("com a janela de aspecto",
                           P.vf_montagem(p, {}, 1280, 720,
                                         permitir_aspecto_agressivo=True)),
                          ("SEM a janela (o defeito da §1a)",
                           "scale=1080:1920,fps=30")):
            saida = os.path.join(tmp, "o%d.mp4" % len(rotulo))
            sh("ffmpeg", "-v", "error", "-y", "-i", fonte, "-an", "-vf", v,
               "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", saida)
            r = sh("ffprobe", "-v", "error", "-select_streams", "v",
                   "-show_entries", "stream=width,height,sample_aspect_ratio",
                   "-of", "csv=p=0", saida).stdout.strip().rstrip(",")
            w, h, sar = (r.split(",") + ["", "", ""])[:3]
            bom = sar in ("1:1", "N/A") and (w, h) == ("1080", "1920")
            if "SEM" in rotulo:
                ok(not bom, "controle plantado (%s) → %s — o teste TEM que reprovar "
                            "este" % (rotulo, r))
            else:
                ok(bom, "%s → %s" % (rotulo, r))

        print("\nregressão de PIXEL: setsar=1 muda o container, não a imagem")
        vert = os.path.join(tmp, "v.mp4")
        sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", "testsrc2=size=1080x1920:rate=30:duration=1",
           "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", vert)
        hashes = []
        for v in ("scale=1080:1920,fps=30", "scale=1080:1920,setsar=1,fps=30"):
            saida = os.path.join(tmp, "r%d.mp4" % len(v))
            sh("ffmpeg", "-v", "error", "-y", "-i", vert, "-an", "-vf", v,
               "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", saida)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", saida, "-f",
                                  "rawvideo", "-pix_fmt", "yuv420p", "-"],
                                 capture_output=True).stdout
            import hashlib
            hashes.append(hashlib.md5(raw).hexdigest())
        ok(hashes[0] == hashes[1],
           "os PIXELS decodificados são idênticos com e sem setsar=1 (%s)"
           % hashes[0][:12])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("\n%d checagens · %d falha(s)" % (checagens[0], len(falhas)))
for f in falhas:
    print("  ✗ " + f)
sys.exit(1 if falhas else 0)
