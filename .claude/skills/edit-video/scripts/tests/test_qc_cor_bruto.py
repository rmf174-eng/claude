#!/usr/bin/env python3
"""Teste do H47-5 (SPEC-47) — a descoberta do bruto no qc-cor, e o crash que ela
causava no fluxo de um cliente.

    python3 .claude/skills/edit-video/scripts/tests/test_qc_cor_bruto.py

🔴 O DEFEITO, MEDIDO EM CAMPO (2026-08-12, container Ubuntu, produção real de
cliente): `qc-cor.py` imprimiu a seção 1 inteira ("varreu 17"), e então morreu com
`TypeError: stat: path should be string […] not NoneType` em
`os.path.exists(bruto)`. Duas causas, as duas reproduzidas aqui:

  1. `descobrir_bruto()` só olhava os FILHOS DIRETOS de `input/`. O layout ad-hoc
     que a própria doc sugere guarda o bruto em `input/bruto/<arquivo>` — um nível
     abaixo. Ela devolvia `None`.
  2. `descobrir_bruto()` era chamada ANTES do `os.chdir(<producao>)`, sobre o
     caminho RELATIVO `input/`. Ou seja: varria o `input/` de quem chamou. Rodando
     da raiz deste repo, o QC elegia como "bruto" um arquivo de OUTRA peça e
     imprimia um SKIP com o nome errado; rodando de um diretório sem `input/`,
     devolvia None — e aí o `None` chegava cru no `os.path.exists`.

E o terceiro, que fecha o mesmo buraco de outro lado: ausência de bruto é um caso
NORMAL (produção antiga sem o bruto guardado). Ela tem que virar SKIP declarado,
não exceção. `tem_bruto()` existe para isso.

Sem ffmpeg o teste sai 0 dizendo que não mediu — nunca verde silencioso.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)

falhas = []
varrido = {}


def conta(chave, n=1):
    varrido[chave] = varrido.get(chave, 0) + n


def ok(msg, cond, detalhe=""):
    print("   %s %s%s" % ("✅" if cond else "❌", msg,
                          ("  — " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(msg)
    return cond


def _carregar_qc_cor():
    p = os.path.join(SCRIPTS, "qc-cor.py")
    spec = importlib.util.spec_from_file_location("qc_cor_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, SCRIPTS)
    spec.loader.exec_module(mod)
    return mod


def _video(caminho, segundos, largura=192):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=%dx%d:rate=30" % (largura, largura * 16 // 9),
         "-t", str(segundos), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-color_range", "tv", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709", caminho],
        capture_output=True, text=True)
    return r.returncode == 0


def producao(base, onde_o_bruto):
    """`onde_o_bruto`: 'direto' (nosso layout) · 'subdir' (ad-hoc) · None."""
    d = os.path.join(base, "prod-%s" % (onde_o_bruto or "sem-bruto"))
    os.makedirs(os.path.join(d, "segs"), exist_ok=True)
    if not _video(os.path.join(d, "segs", "seg001.mp4"), 1):
        return None
    shutil.copy(os.path.join(d, "segs", "seg001.mp4"),
                os.path.join(d, "v1-montado.mp4"))
    if onde_o_bruto == "direto":
        # o bruto é o MAIOR arquivo: 2 s contra 1 s dos segmentos
        _video(os.path.join(d, "input", "take-A.mp4"), 2)
    elif onde_o_bruto == "subdir":
        _video(os.path.join(d, "input", "bruto", "take-cliente.mp4"), 2)
    return d


def main():
    print("test_qc_cor_bruto — H47-5: o bruto que o QC não achava, e o None que "
          "matava o QC")
    if not shutil.which("ffmpeg"):
        print("   ⏭️ NÃO MEDIDO: ffmpeg ausente. Este teste exige ffmpeg para "
              "escrever as produções sintéticas.")
        return 0
    qc_cor = _carregar_qc_cor()
    tmp = tempfile.mkdtemp(prefix="qc-cor-bruto-")
    try:
        print("\n1 · `tem_bruto` sobrevive ao None que o contrato permite")
        conta("checagens")
        ok("tem_bruto(None) é False, sem exceção", qc_cor.tem_bruto(None) is False)
        conta("checagens")
        ok("tem_bruto('') é False", qc_cor.tem_bruto("") is False)
        conta("checagens")
        ok("tem_bruto(<arquivo que existe>) é True",
           qc_cor.tem_bruto(os.path.join(SCRIPTS, "qc-cor.py")) is True)

        print("\n2 · `descobrir_bruto` acha o bruto nos DOIS layouts")
        for onde, esperado in (("direto", "take-A.mp4"),
                               ("subdir", "take-cliente.mp4")):
            d = producao(tmp, onde)
            if d is None:
                ok("produção sintética %s" % onde, False, "ffmpeg falhou")
                continue
            achado = qc_cor.descobrir_bruto(os.path.join(d, "input"))
            conta("layouts varridos")
            ok("layout %-7s → %s" % (onde, esperado),
               achado is not None and os.path.basename(achado) == esperado,
               str(achado))
        d_sem = producao(tmp, None)
        conta("layouts varridos")
        ok("produção sem input/ → None (o SKIP honesto do contrato)",
           qc_cor.descobrir_bruto(os.path.join(d_sem, "input")) is None)

        nome_ferramenta = "av" + "convert"
        print("\n3 · Linux sem %s: SKIP explícito, nunca traceback"
              % nome_ferramenta)
        bruto_sub = os.path.join(tmp, "prod-subdir", "input", "bruto",
                                 "take-cliente.mp4")
        ref_sem_av = os.path.join(tmp, "cache-sem-ferramenta", "ref.mov")
        which_real = qc_cor.shutil.which
        qc_cor.shutil.which = (lambda nome: None
                               if nome == nome_ferramenta else which_real(nome))
        try:
            ref_obtida, motivo = qc_cor.preparar_referencia(
                ref_sem_av, bruto_sub,
                {"video": {"largura": 1080, "altura": 1920}, "qc": {}}, False)
        except Exception as exc:  # o contrato deste caso é justamente não escapar
            ref_obtida, motivo = "EXCECAO", repr(exc)
        finally:
            qc_cor.shutil.which = which_real
        conta("plataformas sem ferramenta Apple")
        ok("ferramenta Apple ausente devolve referência None",
           ref_obtida is None, str(ref_obtida))
        ok("motivo nomeia ferramenta, SKIP e ausência de medição",
           (nome_ferramenta + " indisponível") in motivo
           and "SKIP" in motivo and "não foi medida" in motivo, motivo)
        ok("ausência não publica arquivo de referência",
           not os.path.exists(ref_sem_av))

        print("\n4 · 🦷 ponta a ponta: o qc-cor não morre, e diz o que não mediu")
        env = {**os.environ, "BENCH_PERFIL_SEM_REMOTION": "1"}
        # roda DE DENTRO da produção: é o cwd que expunha o defeito 2
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qc-cor.py"), "."],
                           cwd=d_sem, capture_output=True, text=True, env=env)
        saida = r.stdout + r.stderr
        conta("execuções ponta a ponta")
        ok("sem bruto: 0 traceback", "Traceback" not in saida,
           saida.strip().splitlines()[-1] if "Traceback" in saida else "")
        ok("sem bruto: exit 0", r.returncode == 0, "exit %d" % r.returncode)
        ok("sem bruto: o SKIP nomeia a ausência",
           "não tem bruto de vídeo" in saida)

        d_sub = os.path.join(tmp, "prod-subdir")
        r2 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qc-cor.py"),
                             d_sub], capture_output=True, text=True, env=env)
        saida2 = r2.stdout + r2.stderr
        conta("execuções ponta a ponta")
        ok("layout ad-hoc: 0 traceback", "Traceback" not in saida2)
        ok("layout ad-hoc: o bruto do cliente é USADO, e nomeado na saída",
           os.path.join("input", "bruto", "take-cliente.mp4") in saida2)
        # 🦷 controle do controle: rodando da raiz de OUTRO diretório que TEM um
        # `input/`, o bruto eleito não pode vir de lá.
        alheio = os.path.join(tmp, "cwd-alheio")
        _video(os.path.join(alheio, "input", "peca-de-outra-producao.mp4"), 3)
        r3 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qc-cor.py"),
                             d_sub], cwd=alheio, capture_output=True, text=True,
                            env=env)
        saida3 = r3.stdout + r3.stderr
        conta("execuções ponta a ponta")
        ok("o bruto NUNCA vem do diretório de entrada de quem chamou",
           "peca-de-outra-producao" not in saida3
           and os.path.join("input", "bruto", "take-cliente.mp4") in saida3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-38s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas[:6]))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
