#!/usr/bin/env python3
"""Bateria do `digest-marcacoes.py` — os três GATES da SPEC-18 (§7.5, §7.6, §7.8).

    python3 preview/tests/test_digest.py [--dir <producao>] [--rapido]

`--rapido` pula o que precisa decodificar os `segs/` (o gate §7.6 leva ~12 s
nesta máquina). **Sem `--dir`, constrói uma produção SINTÉTICA** (15 segmentos de
`testsrc2`, `perfil.json` pelo `perfil.py resolver`) e roda contra ela: o teste é
produto e não pode depender de instância nenhuma. Com `--dir <producao>` ele roda
contra uma produção real, só lendo. ⚠️ Até 2026-08-11 o default apontava para uma
produção que não existe em máquina nenhuma e o teste saía 0 dizendo "é esperado" —
um no-op permanente que se anunciava como esperado (R-10).

🔴 TODO teste aqui imprime QUANTO varreu e traz um CONTROLE NEGATIVO. Um
verificador que varre 0 e sai 0 é indistinguível de um quebrado — foi a lição
mais cara das ondas 1–3 deste repo.

O sandbox é sempre em /tmp, com `segs/` e o render por SYMLINK: nada é escrito
dentro da produção real, que pode estar sendo lida por outro agente.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
PREVIEW = os.path.dirname(AQUI)
DIGEST = os.path.join(PREVIEW, "digest-marcacoes.py")
SCRIPTS = os.path.normpath(os.path.join(PREVIEW, os.pardir, "scripts"))
sys.path.insert(0, PREVIEW)
sys.path.insert(0, os.path.join(PREVIEW, os.pardir, "scripts"))

import edl_io                                    # noqa: E402
import estado as estado_mod                      # noqa: E402

import importlib.util                            # noqa: E402

_spec = importlib.util.spec_from_file_location("digest_marcacoes", DIGEST)
dm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dm)

TOTAL = {"ok": 0, "falhou": 0}


def checar(nome, cond, detalhe=""):
    TOTAL["ok" if cond else "falhou"] += 1
    print("  %s %s%s" % ("✅" if cond else "❌", nome,
                         (" — " + detalhe) if detalhe else ""))
    return cond


# ───────────────────────────────────────────────────────────────── sandbox

def montar_sandbox(origem, base, com_timeline):
    """Cópia em /tmp: JSONs de verdade, mídia por symlink. Nada é escrito na origem."""
    d = os.path.join(base, "com-tl" if com_timeline else "sem-tl")
    os.makedirs(os.path.join(d, ".preview", "pendentes"), exist_ok=True)
    for nome in ("edl.json", "captions.json", "perfil.json", "overlays.json",
                 "partitura.json"):
        p = os.path.join(origem, nome)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(d, nome))
    # 🔴 O BRAÇO "SEM TIMELINE" NÃO TIRAVA A TIMELINE (achado R-10, 2026-08-11).
    # A cópia acima leva o `edl.json` inteiro, e num EDL v2 o `timeline_real` mora
    # DENTRO dele. Resultado: o gate §7.6, que existe para provar que a régua é
    # MEDIDA dos `segs/` quando não há timeline persistida, rodava com a timeline
    # persistida ali do lado. Os dois braços do teste eram o mesmo braço, e o
    # único que reprovava era o que ninguém rodava. Apontado para uma produção
    # real, o teste saía exit 1 com 3 gates vermelhos.
    edl = os.path.join(d, "edl.json")
    if not com_timeline and os.path.isfile(edl):
        with open(edl, encoding="utf-8") as fh:
            env = json.load(fh)
        if isinstance(env, dict) and env.pop("timeline_real", None) is not None:
            with open(edl, "w", encoding="utf-8") as fh:
                json.dump(env, fh, ensure_ascii=False, indent=1)
        for lado in ("timeline.json", "timeline_real.json"):
            alvo = os.path.join(d, lado)
            if os.path.lexists(alvo):
                os.remove(alvo)
    for nome in ("segs",):
        p = os.path.join(origem, nome)
        if os.path.isdir(p) and not os.path.lexists(os.path.join(d, nome)):
            os.symlink(os.path.abspath(p), os.path.join(d, nome))
    for nome in os.listdir(origem):
        if nome.endswith(".mp4") and not os.path.lexists(os.path.join(d, nome)):
            os.symlink(os.path.abspath(os.path.join(origem, nome)),
                       os.path.join(d, nome))
    return d


N_SEGS_FIXTURE = 15          # o gate §7.5 nomeia seg013 — precisa de 14+


def fixture_sintetica(d):
    """Uma produção mínima, 100% sintética, com o que os gates medem.

    `testsrc2` + `sine` porque o gate §7.6 DECODIFICA os `segs/` para medir a
    régua: um arquivo vazio não serve, e bruto de creator não viaja. Durações
    deliberadamente DESIGUAIS — a régua que este teste existe para provar é a que
    não pode ser `Σ(end−start)`, e com segmentos iguais um bug de soma passa.
    """
    segs = os.path.join(d, "segs")
    os.makedirs(segs, exist_ok=True)
    # O `perfil.json` sai do MECANISMO DO PRODUTO, não escrito à mão: o schema
    # tem 21 chaves obrigatórias e um dict à mão aqui envelheceria calado na
    # primeira que fosse acrescentada. `BENCH_PERFIL_SEM_REMOTION=1` porque não é
    # contaminação de workspace que este teste mede.
    env = dict(os.environ, BENCH_PERFIL_SEM_REMOTION="1")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "perfil.py"), "resolver",
                    d, "--perfil", "reels"],
                   check=True, capture_output=True, env=env)
    with open(os.path.join(d, "perfil.json"), encoding="utf-8") as fh:
        perf = json.load(fh)
    W, H, FPS_F = (perf["video"]["largura"], perf["video"]["altura"],
                   perf["video"]["fps"])
    duracoes = [round(0.60 + 0.07 * (i % 7), 3) for i in range(N_SEGS_FIXTURE)]
    segments, acc_fonte = [], 1.0
    for i, dur in enumerate(duracoes):
        arq = os.path.join(segs, "seg%03d.mp4" % i)
        if not os.path.isfile(arq):
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y",
                 "-f", "lavfi", "-i",
                 "testsrc2=size=%dx%d:rate=%s:duration=%s" % (W, H, FPS_F, dur),
                 "-f", "lavfi", "-i", "sine=frequency=%d:duration=%s" % (220 + i, dur),
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", arq],
                check=True, capture_output=True)
        # ⚠️ `src` sem prefixo de diretório-raiz do repo: `input/…` em posição
        # executável é classe A do auditor, e um FIXTURE não pode ensinar o que a
        # régua proíbe. O campo é um rótulo — o arquivo nem precisa existir.
        segments.append({"src": "bruto-sintetico.mp4",
                         "start": round(acc_fonte, 3),
                         "end": round(acc_fonte + dur, 3),
                         "beat": ["abertura", "meio", "fecho"][i % 3],
                         "fala": "fala sintetica %d" % i})
        acc_fonte += dur + 0.5          # buraco na fonte: corte de respiro
    with open(os.path.join(d, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "benchmark.edl/v2", "segments": segments},
                  fh, ensure_ascii=False, indent=1)
    caps, t = [], 0
    for i in range(N_SEGS_FIXTURE):
        for w in ("palavra", "sintetica", "%d" % i):
            caps.append({"text": " " + w, "startMs": t, "endMs": t + 220,
                         "timestampMs": t + 110, "confidence": 0.9})
            t += 240
    with open(os.path.join(d, "captions.json"), "w", encoding="utf-8") as fh:
        json.dump(caps, fh, ensure_ascii=False, indent=1)
    # o render de entrega: concat dos segs, que é o que a produção real teria
    lista = os.path.join(d, "concat.txt")
    with open(lista, "w", encoding="utf-8") as fh:
        for i in range(N_SEGS_FIXTURE):
            fh.write("file 'segs/seg%03d.mp4'\n" % i)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", lista, "-c", "copy", os.path.join(d, "v-final.mp4")],
                   check=True, capture_output=True, cwd=d)
    return d


def gravar_marcacao(d, notas, render_alvo="v-final.mp4", n=1, fp_render=None):
    pay = {"contrato": dm.CONTRATO,
           "salvo_em": datetime.now().astimezone().isoformat(timespec="seconds"),
           "revisao_base": 0, "fingerprint_corte": None,
           "fingerprint_render": fp_render, "render_alvo": render_alvo,
           "formato": {"largura": None, "altura": None, "fps": None, "fonte": "medido"},
           "timeline_real_ausente": True, "app": "preview/app v1", "notas": notas}
    env = {"schema": "benchmark.preview-evento/v1", "tipo": "marcacoes",
           "salvo_em": pay["salvo_em"], "origem": {"ua": "test", "token": "t"},
           "payload": pay}
    alvo = os.path.join(d, ".preview", "pendentes",
                        "20260808T174109-marcacoes-%d.json" % n)
    with open(alvo, "w", encoding="utf-8") as fh:
        json.dump(env, fh, ensure_ascii=False, indent=1)
    return alvo


def nota_de(ini, fim, fps, ident="m1", trilha="legenda", texto="sobe a legenda"):
    return {"id": ident, "tipo": "ponto" if fim == ini else "intervalo", "fase": 1,
            "trilha": trilha, "ref": None,
            "rascunho": {"ini": ini, "fim": fim}, "render": {"ini": ini, "fim": fim},
            "render_frames": [round(ini * fps), round(fim * fps)],
            "sid": None, "sid_confianca": "indisponivel", "marcado_invertido": False,
            "texto": texto,
            "contexto": {"palavras": [], "trilhas_com_conteudo": ["video"]}}


# ──────────────────────────────────────────────── §7.5 — take e coordenada de fonte

def gate_75(d, tl):
    """29/29 takes atribuídos certo, e src_ini/src_fim dentro de 1 frame."""
    print("\n[gate §7.5] o take e a coordenada na FONTE — varredura de todos os takes")
    segments = edl_io.segmentos(d)
    sids = estado_mod.sid_de(segments)
    fps = tl["video"]["fps"]
    tol = 1.0 / fps
    certos, erros = 0, []
    for s in tl["segments"]:
        i = s["i"]
        centro = s["start_s"] + s["dur_s"] / 2.0
        take = dm.take_em(tl, segments, sids, centro)
        esperado_src = segments[i]["start"] + (centro - s["start_s"])
        ok = (take and take["i"] == i and take["sid"] == sids[i]
              and abs(take["t_fonte"] - esperado_src) <= tol
              and segments[i]["start"] - tol <= take["t_fonte"]
              <= segments[i]["end"] + tol)
        certos += 1 if ok else 0
        if not ok:
            erros.append(i)
    checar("takes atribuídos", certos == len(tl["segments"]),
           "%d/%d (varridos %d; erram: %s)"
           % (certos, len(tl["segments"]), len(tl["segments"]), erros or "nenhum"))

    # o caso nomeado pela spec: o 14º segmento (i=13)
    if len(tl["segments"]) > 13:
        s = tl["segments"][13]
        gravar_marcacao(d, [nota_de(round(s["start_s"] + 0.1, 3),
                                    round(s["start_s"] + s["dur_s"] - 0.1, 3), fps)])
        saida = subprocess.run([sys.executable, DIGEST, d], capture_output=True,
                               text=True)
        txt = saida.stdout
        checar("digest nomeia segs/seg013.mp4", "segs/seg013.mp4" in txt)
        checar("digest nomeia o sid", sids[13] in txt, sids[13])
        checar("digest imprime a coordenada de FONTE",
               ("%.3f" % segments[13]["start"]).replace(".", ",")[:5] in txt
               or "fonte %s" % segments[13]["src"] in txt)
        for f in os.listdir(os.path.join(d, ".preview", "pendentes")):
            os.remove(os.path.join(d, ".preview", "pendentes", f))

    # 🔴 CONTROLE NEGATIVO, com a POPULAÇÃO medida antes.
    #
    # Amostrar o CENTRO de cada take NÃO serve aqui, e isso foi medido: a deriva
    # da régua somada chega a 316,7 ms no fim, e metade do take mais curto desta
    # produção é 366 ms — então o centro de todos os 29 continua caindo no take
    # certo (0/29 errados) e o "controle" seria um verde vazio. A deriva desloca
    # a FRONTEIRA: a régua somada põe o fim do take k em `real_fim_k − δ(k+1)`,
    # então erra todo instante da CAUDA de cada take. A população certa é o
    # conjunto dos frames do render, não 29 pontos escolhidos onde o defeito não
    # mora.
    somada = _timeline_somada(segments, fps)
    total = tl["total_frames"]
    errados, takes_afetados = 0, set()
    for f in range(total):
        t = (f + 0.5) / fps
        a = dm.take_em(tl, segments, sids, t)
        b = dm.take_em(somada, segments, sids, t)
        if a and b and a["i"] != b["i"]:
            errados += 1
            takes_afetados.add(a["i"])
    checar("controle negativo: Σ(end−start) erra o take",
           errados >= 1 and len(takes_afetados) >= 1,
           "%d de %d frames varridos caem no take errado (%.1f%%), afetando %d dos "
           "%d takes — se isto der 0, o gate não está medindo nada"
           % (errados, total, 100.0 * errados / total,
              len(takes_afetados), len(tl["segments"])))
    return somada


def _timeline_somada(segments, fps):
    """A régua PROIBIDA (Σ end−start), só para servir de controle negativo."""
    segs, acc = [], 0.0
    for i, s in enumerate(segments):
        dur = float(s["end"]) - float(s["start"])
        segs.append({"i": i, "start_s": acc, "dur_s": dur})
        acc += dur
    return {"video": {"fps": fps}, "segments": segs, "total_s": acc}


# ───────────────────────────────────────── §7.6 — sem SPEC-05 a atribuição não muda

def gate_76(d, tl_real, somada):
    print("\n[gate §7.6] sem timeline_real, a régua é MEDIDA de segs/ — e bate")
    tl, origem = dm.timeline_de(d)
    checar("origem da régua", origem == "medida", origem)
    checar("total de frames", tl["total_frames"] == tl_real["total_frames"],
           "%s frames = %s s" % (tl["total_frames"],
                                 ("%.6f" % tl["total_s"]).replace(".", ",")))
    segments = edl_io.segmentos(d)
    sids = estado_mod.sid_de(segments)
    iguais = 0
    for s in tl_real["segments"]:
        c = s["start_s"] + s["dur_s"] / 2.0
        a = dm.take_em(tl, segments, sids, c)
        b = dm.take_em(tl_real, segments, sids, c)
        iguais += 1 if (a and b and a["i"] == b["i"]) else 0
    checar("atribuição medida × timeline_real",
           iguais == len(tl_real["segments"]),
           "%d/%d" % (iguais, len(tl_real["segments"])))
    print("     Σ(end−start) = %.3f s   ×   Σ frames/fps = %.6f s   (erro %.1f ms)"
          % (somada["total_s"], tl["total_s"],
             (tl["total_s"] - somada["total_s"]) * 1000.0))
    saida = subprocess.run([sys.executable, DIGEST, d], capture_output=True, text=True)
    checar("cabeçalho diz MEDIDA de segs/", "MEDIDA de segs/" in saida.stdout)


# ────────────────────────────────────── §7.8 — o agente age sem reabrir o vídeo

def _path_sem_ffprobe(base):
    """Um PATH que comprovadamente não tem ffprobe: um diretório vazio nosso."""
    d = os.path.join(base, "path-vazio")
    os.makedirs(d, exist_ok=True)
    return d


def _path_com_ffprobe_falso(base):
    """Um PATH que comprovadamente TEM ffprobe — e um espião junto.

    O falso grava o próprio argv num arquivo-sentinela e sai 1. Se o digest o
    chamar, o sentinela deixa de estar vazio: a prova de "não invocou" passa a
    ser observação de fora, e não só o campo que o programa afirma sobre si.
    """
    d = os.path.join(base, "path-com-ffprobe")
    os.makedirs(d, exist_ok=True)
    sentinela = os.path.join(base, "ffprobe-foi-chamado.txt")
    falso = os.path.join(d, "ffprobe")
    with open(falso, "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\nprintf "%s\\n" "$*" >> "%s"\nexit 1\n'
                 % ("%s", sentinela))
    os.chmod(falso, 0o755)
    return d, sentinela


def gate_78(d_com_tl, d_sem_tl):
    print("\n[gate §7.8] PATH controlado — com e sem ffprobe")
    # 🔴 MEDIDO NO LINUX, 2026-08-12: aqui estava `PATH=/usr/bin:/bin` com um
    # `which(...) is None` de controle. Isso é uma SUPOSIÇÃO sobre onde o sistema
    # guarda binários — onde o ffprobe vem de um gerenciador de pacotes fora de
    # `/usr/bin` a suposição vale por acidente, e numa distribuição em que
    # `/usr/bin/ffprobe` existe o controle do controle reprovava uma instalação
    # correta. O PATH agora é construído pelo teste, e os dois ramos são
    # exercidos em qualquer sistema.
    base = tempfile.mkdtemp(prefix="digest-path-")
    try:
        sem = _path_sem_ffprobe(base)
        com, sentinela = _path_com_ffprobe_falso(base)
        checar("controle do controle: o PATH vazio não tem ffprobe",
               shutil.which("ffprobe", path=sem) is None,
               str(shutil.which("ffprobe", path=sem)))
        checar("controle do controle: o PATH plantado TEM ffprobe",
               shutil.which("ffprobe", path=com) is not None,
               str(shutil.which("ffprobe", path=com)))

        for rotulo, caminho in (("sem ffprobe no PATH", sem),
                                ("com ffprobe no PATH", com)):
            env = dict(os.environ, PATH=caminho)
            r = subprocess.run([sys.executable, DIGEST, d_com_tl, "--json"],
                               capture_output=True, text=True, env=env)
            checar("%s · com timeline_real: exit 0" % rotulo,
                   r.returncode == 0, r.stderr.strip()[-200:])
            try:
                j = json.loads(r.stdout)
            except ValueError:
                j = {}
                checar("%s · com timeline_real: --json parseável" % rotulo,
                       False, r.stdout[:200])
            if j:
                checar("%s · ffprobe_invocado false" % rotulo,
                       j["ffprobe_invocado"] is False, str(j.get("ffprobe_invocado")))
                checar("%s · ffmpeg_invocado false" % rotulo,
                       j["ffmpeg_invocado"] is False, str(j.get("ffmpeg_invocado")))
                checar("%s · origem da régua" % rotulo,
                       j["timeline"]["origem"] == "timeline_real",
                       j["timeline"]["origem"])
                checar("%s · o digest resolveu o take mesmo assim" % rotulo,
                       bool(j["marcacoes"]) and j["marcacoes"][0]["take"] is not None)

        # o espião: existir no PATH não é ser chamado
        chamadas = open(sentinela, encoding="utf-8").read() if \
            os.path.isfile(sentinela) else ""
        checar("o ffprobe plantado NÃO foi executado (espião vazio)",
               chamadas == "", chamadas.strip()[:120] or "0 chamadas")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    r2 = subprocess.run([sys.executable, DIGEST, d_sem_tl, "--json"],
                        capture_output=True, text=True)
    j2 = json.loads(r2.stdout) if r2.stdout.strip().startswith("{") else {}
    checar("sem timeline_real: ffprobe_invocado true",
           j2.get("ffprobe_invocado") is True, str(j2.get("ffprobe_invocado")))
    checar("sem timeline_real: ffmpeg_invocado false",
           j2.get("ffmpeg_invocado") is False, str(j2.get("ffmpeg_invocado")))


# ──────────────────────────────────────────── invariantes, bordas e o --ack

def testes_de_contrato(d, fps):
    print("\n[contrato] invariantes §4.1, casos de borda §3.4 e o ACK")
    fixture = os.path.join(AQUI, "fixtures", "marcacoes-exemplo.json")
    obj = json.load(open(fixture, encoding="utf-8"))
    pay = obj["payload"]
    erros = [e for n in pay["notas"] for e in dm.conferir_nota(n, pay["formato"]["fps"])]
    checar("a fixture do repo passa nas invariantes", not erros, "; ".join(erros))
    checar("a fixture cobre os casos de borda",
           {n["tipo"] for n in pay["notas"]} == {"intervalo", "ponto"}
           and any(n["marcado_invertido"] for n in pay["notas"]),
           "%d notas" % len(pay["notas"]))

    # 🔴 defeito PLANTADO: cada invariante tem que acusar.
    plantados = [
        ("render invertido", {"render": {"ini": 5.0, "fim": 4.0}}),
        ("ponto com intervalo", {"tipo": "ponto"}),
        ("frames fora de round(t×fps)", {"render_frames": [0, 0]}),
        ("trilha fora do enum", {"trilha": "vibe"}),
        ("texto vazio", {"texto": "   "}),
        ("sid sem confiança coerente", {"sid": None, "sid_confianca": "exata"}),
    ]
    pegos = 0
    for nome, patch in plantados:
        n = dict(nota_de(1.0, 2.0, fps))
        n.update(patch)
        achou = bool(dm.conferir_nota(n, fps))
        pegos += 1 if achou else 0
        if not achou:
            print("     ❌ o defeito %r passou em silêncio" % nome)
    checar("defeitos plantados acusados", pegos == len(plantados),
           "%d/%d" % (pegos, len(plantados)))

    # --verificar tem que sair 1 num arquivo torto, e 0 num são
    n = nota_de(1.0, 2.0, fps)
    n["texto"] = ""
    torto = gravar_marcacao(d, [n], n=9)
    r = subprocess.run([sys.executable, DIGEST, d, "--verificar"],
                       capture_output=True, text=True)
    checar("--verificar sai 1 com nota torta", r.returncode == 1, str(r.returncode))
    os.remove(torto)

    # --ack MOVE, não apaga
    gravar_marcacao(d, [nota_de(1.0, 2.0, fps)], n=8)
    antes = len(os.listdir(os.path.join(d, ".preview", "pendentes")))
    r = subprocess.run([sys.executable, DIGEST, d], capture_output=True, text=True)
    depois_leitura = len(os.listdir(os.path.join(d, ".preview", "pendentes")))
    checar("ler não consome", antes == depois_leitura,
           "%d → %d" % (antes, depois_leitura))
    subprocess.run([sys.executable, DIGEST, d, "--ack"], capture_output=True, text=True)
    pend = os.listdir(os.path.join(d, ".preview", "pendentes"))
    apl = os.listdir(os.path.join(d, ".preview", "aplicados"))
    checar("--ack move para aplicados/", not pend and len(apl) == antes,
           "pendentes=%d aplicados=%d" % (len(pend), len(apl)))


def teste_fingerprint(d, fps, tl):
    print("\n[fingerprint] render trocado depois da marcação vira ALARME no topo")
    gravar_marcacao(d, [nota_de(1.0, 2.0, fps)], n=7,
                    fp_render="sha1:0000000000000000000000000000000000000000")
    r = subprocess.run([sys.executable, DIGEST, d], capture_output=True, text=True)
    checar("alarme impresso", "o render mudou depois da marcação" in r.stdout,
           r.stdout.splitlines()[3] if len(r.stdout.splitlines()) > 3 else "")
    for f in os.listdir(os.path.join(d, ".preview", "pendentes")):
        os.remove(os.path.join(d, ".preview", "pendentes", f))


def teste_sem_nada(base):
    print("\n[degradação] produção sem segs/ e sem timeline_real")
    d = os.path.join(base, "vazia")
    os.makedirs(os.path.join(d, ".preview", "pendentes"), exist_ok=True)
    with open(os.path.join(d, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump([{"src": "input/a.mov", "start": 1.0, "end": 3.0, "beat": "g"}], fh)
    gravar_marcacao(d, [nota_de(1.0, 2.0, 30.0)])
    r = subprocess.run([sys.executable, DIGEST, d], capture_output=True, text=True)
    checar("sai 0 mesmo sem mídia", r.returncode == 0, str(r.returncode))
    checar("diz 'indisponível' em vez de chutar o take",
           "indisponível" in r.stdout, r.stdout.strip().splitlines()[-6:][0]
           if r.stdout.strip() else "")
    checar("não inventa régua", "Σ" not in r.stdout)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=None)
    p.add_argument("--rapido", action="store_true")
    args = p.parse_args()

    base = tempfile.mkdtemp(prefix="spec18-test-")

    # 🔴 O DEFAULT ERA UMA PRODUÇÃO QUE NÃO EXISTE (achado R-10, 2026-08-11).
    # Ele apontava para `creators/creator-2/producao/peca-01` — o nome
    # ANONIMIZADO, que não existe em máquina nenhuma. O teste saía exit 0 com a
    # mensagem "produção de teste ausente… é esperado", entrava verde na bateria
    # e nunca rodou. Um no-op permanente que se anuncia como esperado é a forma
    # mais silenciosa de um teste morrer.
    #
    # Agora o default é uma produção SINTÉTICA construída aqui: 15 segmentos de
    # `testsrc2` com tom, `edl.json` v2, `captions.json` e `perfil.json`. Roda em
    # qualquer máquina que tenha ffmpeg, não depende de instância nenhuma, e tem
    # os 14+ segmentos que o gate §7.5 exige (ele nomeia `segs/seg013.mp4`).
    origem = args.dir
    if origem is None:
        origem = fixture_sintetica(os.path.join(base, "fixture"))
        print("produção: SINTÉTICA em %s (15 segs de testsrc2)" % origem)
    else:
        if not os.path.isdir(origem):
            print("--dir aponta para diretório que não existe: %s" % origem)
            shutil.rmtree(base, ignore_errors=True)
            return 2
        print("produção: %s" % origem)
    try:
        d_sem = montar_sandbox(origem, base, com_timeline=False)
        tl_real = edl_io.medir_timeline(d_sem, gerado_por="test_digest.py")
        fps = tl_real["video"]["fps"]

        somada = gate_75(d_sem, tl_real)
        if not args.rapido:
            gate_76(d_sem, tl_real, somada)

        d_com = montar_sandbox(origem, base, com_timeline=True)
        env = edl_io.carregar(d_com)
        env["timeline_real"] = tl_real
        with open(os.path.join(d_com, "edl.json"), "w", encoding="utf-8") as fh:
            json.dump(env, fh, ensure_ascii=False, indent=1)
        s = tl_real["segments"][13]
        gravar_marcacao(d_com, [nota_de(round(s["start_s"] + 0.1, 3),
                                        round(s["start_s"] + s["dur_s"] - 0.1, 3), fps)])
        gate_78(d_com, d_sem)

        testes_de_contrato(d_com, fps)
        teste_fingerprint(d_com, fps, tl_real)
        teste_sem_nada(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n%d ok · %d falhou" % (TOTAL["ok"], TOTAL["falhou"]))
    return 1 if TOTAL["falhou"] else 0


if __name__ == "__main__":
    sys.exit(main())
