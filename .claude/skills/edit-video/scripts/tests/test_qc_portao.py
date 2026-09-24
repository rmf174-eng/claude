#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bateria do qc-portao.py — material 100% sintético, sem ffmpeg, sem creator.

    python3 .claude/skills/edit-video/scripts/tests/test_qc_portao.py

Nada aqui toca `creators/`: o portão é exercitado sobre produções de mentira num
diretório temporário. Os arquivos de mídia são bytes quaisquer — o portão compara
`mtime` e hash, nunca decodifica.

Os defeitos plantados foram escolhidos onde o portão é FRACO:
  · aprovação existente cujo PLANO mudou depois        (exit 2, não 0)
  · aprovação existente cujo RENDER mudou depois       (exit 2, não 0)
  · `estado.json` com `aprovacoes: []`                 (é legado, não aprovação)
  · produção entregue sem registro nenhum              (exit 0, nunca reprovação retroativa)
  · produção sem render de corte                       (não reprova o que não mediu)
  · `--aprovar` sem `--por`                            (aprovação sem dono não existe)
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
PORTAO = os.path.normpath(os.path.join(AQUI, "..", "qc-portao.py"))
PLANO_VISUAL = os.path.normpath(os.path.join(AQUI, "..", "plano-visual.py"))

ok, falhas, n = 0, [], 0


def checa(nome, cond, detalhe=""):
    global ok, n
    n += 1
    if cond:
        ok += 1
    else:
        falhas.append("%s — %s" % (nome, detalhe))
    print("  %s %s" % ("ok  " if cond else "FALHA", nome))


def roda(*args):
    p = subprocess.run([sys.executable, PORTAO] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def escreve(p, txt="x"):
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return p


def producao(base, nome, com_entregavel=False, com_render=True, com_grafico=True):
    d = os.path.join(base, nome)
    os.makedirs(d, exist_ok=True)
    if com_render:
        escreve(os.path.join(d, "v1-montado.mp4"), "corte sintetico")
    escreve(os.path.join(d, "PLANO-EDICAO.md"), "# plano\n")
    if com_entregavel:
        escreve(os.path.join(d, "v-final.mp4"), "entregue")
    if com_grafico:
        time.sleep(1.05)                       # a camada gráfica nasce DEPOIS do corte
        escreve(os.path.join(d, "overlays.json"), "{}")
    return d


def prepara_plano_visual_essencial(d):
    """Caminho feliz novo: escolha v3 explícita e plano sem motion."""
    prev = os.path.join(d, ".preview")
    os.makedirs(prev, exist_ok=True)
    escreve(os.path.join(prev, "estilo-vigente.json"), json.dumps({
        "contrato": "benchmark.edit-estilo-vigente/v1",
        "estilo": {
            "contrato": "benchmark.edit-estilo/v3",
            "direcao_edicao": {"modo": "essencial", "densidade": "leve",
                               "sfx": "sem-sfx"},
            "elementos": {"sfx": False},
        },
    }))
    segmentos = [{"src": "bruto.mp4", "start": 0.0, "end": 1.0}]
    canon = json.dumps(segmentos, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    fp = "sha1:" + hashlib.sha1(canon.encode("utf-8")).hexdigest()
    escreve(os.path.join(d, "edl.json"), json.dumps({
        "schema": "benchmark.edl/v2",
        "segments": segmentos,
        "timeline_real": {
            "schema": "benchmark.timeline-real/v1",
            "edl_fingerprint": fp,
            "total_s": 1.0,
            "segments": [{"i": 0, "start_s": 0.0, "dur_s": 1.0}],
        },
    }))
    p = subprocess.run([sys.executable, PLANO_VISUAL, d, "--iniciar"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("não consegui iniciar plano visual: %s%s" %
                             (p.stdout, p.stderr))


def main():
    print("test_qc_portao — produções sintéticas, nenhum byte em creators/")
    with tempfile.TemporaryDirectory() as base:
        # ── 1 · camada gráfica depois do corte, sem aprovação → reprova e LISTA
        d = producao(base, "sem-aprovacao")
        cod, out = roda(d)
        checa("sem aprovação: exit 1", cod == 1, out)
        checa("sem aprovação: nomeia o arquivo", "overlays.json" in out, out)
        checa("imprime quantos artefatos varreu", "varridos" in out, out)

        # ── 2 · --aprovar exige dono
        cod, out = roda(d, "--aprovar")
        checa("--aprovar sem --por recusa", cod != 0, out)

        # ── 3 · aprovado → verde
        cod, out = roda(d, "--aprovar", "--por", "teste", "--motivo", "vai direto")
        checa("--aprovar --por grava", cod == 0, out)
        reg = json.load(open(os.path.join(d, ".aprovacao.json"), encoding="utf-8"))
        checa("o registro tem os dois fingerprints",
              reg.get("plano_sha256") and reg.get("render_fingerprint"), str(reg))
        checa("o registro guarda o motivo (o antigo 'vai direto', auditável)",
              reg.get("motivo") == "vai direto", str(reg))
        # 🔴 O CONTRATO MUDOU EM 2026-08-10 (achado A10): aprovação de CLI é
        # MODO DEGRADADO e reprova por default. Antes, "existe aprovação válida"
        # bastava — e uma peça saiu "aprovada pelo creator" assinada pelo agente.
        cod, out = roda(d)
        checa("aprovação de CLI reprova por default (exit 1)", cod == 1, out)
        checa("e nomeia a fonte", "cli-degradado" in out, out)
        checa("e ensina o botão", "Aprovar o corte" in out, out)
        prepara_plano_visual_essencial(d)
        cod, out = roda(d, "--aceitar-degradado")
        checa("com --aceitar-degradado, exit 0", cod == 0, out)

        # ── 3b · aprovação com fonte ui-save passa sem exceção nenhuma
        dui = producao(base, "aprovado-na-ui")
        os.makedirs(os.path.join(dui, ".preview"), exist_ok=True)
        rp = os.path.join(dui, "v1-montado.mp4")
        st = os.stat(rp)
        fp = "sha1:" + hashlib.sha1(
            ("v1-montado.mp4|%d|%d" % (st.st_size, int(st.st_mtime))).encode()).hexdigest()
        sha = hashlib.sha256(open(os.path.join(dui, "PLANO-EDICAO.md"), "rb").read()).hexdigest()
        escreve(os.path.join(dui, ".preview", "estado.json"), json.dumps({
            "aprovacoes": [{"alvo": "fase-1", "por": "creator (UI)", "em": "2026-08-10",
                            "fonte": "ui-save", "sessao_pid": 4242,
                            "render": "v1-montado.mp4", "render_fingerprint": fp,
                            "plano_sha256": sha, "plano": "PLANO-EDICAO.md"}]}))
        prepara_plano_visual_essencial(dui)
        cod, out = roda(dui)
        checa("aprovação ui-save: exit 0 sem exceção", cod == 0 and "aprovado" in out, out)
        plano_visual = os.path.join(dui, "plano-visual.json")
        os.rename(plano_visual, plano_visual + ".guardado")
        cod, out = roda(dui)
        checa("aprovação sem plano visual não libera Fase 2",
              cod == 1 and "PLANO-VISUAL-AUSENTE" in out, out)
        os.rename(plano_visual + ".guardado", plano_visual)

        # ── 4 · 🔴 DEFEITO PLANTADO: o plano muda DEPOIS de aprovado
        time.sleep(1.05)
        escreve(os.path.join(d, "PLANO-EDICAO.md"), "# plano v2\n")
        cod, out = roda(d)
        checa("plano alterado depois: exit 2", cod == 2, out)
        checa("plano alterado depois: diz o motivo", "plano_sha256" in out, out)

        # ── 5 · 🔴 DEFEITO PLANTADO: o render muda DEPOIS de aprovado
        d2 = producao(base, "render-mudou")
        roda(d2, "--aprovar", "--por", "teste")
        time.sleep(1.05)
        escreve(os.path.join(d2, "v1-montado.mp4"), "outro corte")
        cod, out = roda(d2)
        checa("render alterado depois: exit 2", cod == 2, out)
        checa("render alterado depois: diz o motivo", "render_fingerprint" in out, out)

        # ── 6 · 🔴 O LEGADO É LISTA FECHADA (achado A11). O ramo "entregue e sem
        #        registro → exit 0" não olhava data: valia para sempre, e o pior
        #        descumprimento possível (entregar sem ninguém aprovar) era o
        #        caso que saía verde.
        d3 = producao(base, "entregue", com_entregavel=True)
        cod, out = roda(d3)
        checa("entregue sem aprovação e FORA da lista: exit 1", cod == 1, out)
        checa("e nomeia o slug e o arquivo da lista",
              "entregue" in out and "_portao-legado.json" in out, out)

        # ── 6b · a MESMA produção, nomeada na lista, continua verde
        escreve(os.path.join(base, "_portao-legado.json"),
                json.dumps({"schema": "benchmark.portao-legado/v1",
                            "producoes": ["entregue"]}))
        cod, out = roda(d3)
        checa("nomeada na lista: exit 0 e flag legado",
              cod == 0 and "legado" in out, out)

        # ── 7 · `estado.json` com aprovacoes vazio carrega a mesma evidência que
        #        a ausência do arquivo: continua caindo na regra do legado.
        os.makedirs(os.path.join(d3, ".preview"), exist_ok=True)
        escreve(os.path.join(d3, ".preview", "estado.json"),
                json.dumps({"aprovacoes": []}))
        cod, out = roda(d3)
        checa("estado.json vazio continua legado", cod == 0 and "legado" in out, out)
        os.remove(os.path.join(base, "_portao-legado.json"))

        # ── 8 · sem render de corte, o portão NÃO reprova o que não mediu
        d4 = producao(base, "sem-corte", com_render=False)
        cod, out = roda(d4)
        checa("sem render de corte: exit 0 e nao-verificado",
              cod == 0 and "nao-verificado" in out, out)

        # ── 9 · sem camada gráfica nova, nada a exigir
        d5 = producao(base, "so-corte", com_grafico=False)
        cod, out = roda(d5)
        checa("sem camada gráfica nova: exit 0", cod == 0 and "sem-camada-nova" in out, out)

        # ── 10 · `estado.json` da SPEC-16 vence o `.aprovacao.json`
        d6 = producao(base, "estado-vence")
        roda(d6, "--aprovar", "--por", "local")
        os.makedirs(os.path.join(d6, ".preview"), exist_ok=True)
        escreve(os.path.join(d6, ".preview", "estado.json"), json.dumps({
            "aprovacoes": [{"alvo": "fase-1", "por": "creator-1", "em": "2026-08-09",
                            "render": "v1-montado.mp4", "render_fingerprint": "sha1:errado",
                            "plano_sha256": "errado", "plano": "PLANO-EDICAO.md"}]}))
        cod, out = roda(d6)
        checa("estado.json vence o .aprovacao.json", cod == 2 and "estado.json" in out, out)

        # ── 11 · o script é somente-leitura sem --aprovar
        d7 = producao(base, "somente-leitura")
        antes = sorted(os.listdir(d7))
        mt = {f: os.stat(os.path.join(d7, f)).st_mtime for f in antes}
        roda(d7)
        depois = sorted(os.listdir(d7))
        checa("sem --aprovar não escreve nada",
              antes == depois and all(os.stat(os.path.join(d7, f)).st_mtime == mt[f]
                                      for f in antes), str(depois))

        # ── 12 · o JSON é máquina-legível
        cod, out = roda(d7, "--json")
        try:
            j = json.loads(out.split("\n{", 1)[0] if out.startswith("{") else out)
            valido = j.get("schema") == "benchmark.portao/v1"
        except ValueError:
            valido = False
        checa("--json devolve benchmark.portao/v1", valido, out[:120])

    print("\n%d checagens · %d ok · %d falhas" % (n, ok, len(falhas)))
    for f in falhas:
        print("  FALHOU: %s" % f)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
