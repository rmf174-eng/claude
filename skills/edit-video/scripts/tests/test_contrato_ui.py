#!/usr/bin/env python3
"""Teste do contrato de dados da UI de aprovação (SPEC-16) — autocontido.

    python3 .claude/skills/edit-video/scripts/tests/test_contrato_ui.py [--rapido]
    python3 -m pytest .claude/skills/edit-video/scripts/tests/test_contrato_ui.py

`--rapido` pula os casos que chamam o `montar.sh` (render de ~9 s de vídeo
256x456 sintético) e roda só o que é aritmética, schema e arquivo.

🔴 POR QUE ELE PLANTA DEFEITO EM VEZ DE SÓ AFIRMAR O CASO BOM
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado — este repo
já entregou 6,25 s de vídeo errado com TODOS os QCs verdes. Então cada checagem
faz duas coisas: afirma o caso bom com o número medido, e planta o defeito que o
mecanismo TEM que acusar (órfão no disco, sidecar divergente, índice posicional
no canal de volta, coordenada de render sem timeline, `revisao_base` no futuro,
plano editado depois de aprovado, dois saves do mesmo tipo na fila).

🔒 Nada aqui toca material de creator. O bruto é `testsrc2` + tom senoidal; o
bloco de material real é PULADO silencioso quando `creators/` não existe, que é
o caso de qualquer cliente do produto.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
import estado as est_mod   # noqa: E402
import edl_io              # noqa: E402

MONTAR = os.path.join(SCRIPTS, "montar.sh")
falhas = []
varrido = {}


def ok(nome, cond, detalhe):
    print("  [%s] %s — %s" % ("PASSOU" if cond else "FALHOU", nome, detalhe))
    if not cond:
        falhas.append(nome)
    return bool(cond)


def morre(fn, *a, **kw):
    """Roda `fn` esperando SystemExit. Devolve a mensagem (ou "" se NÃO morreu)."""
    try:
        fn(*a, **kw)
    except SystemExit as e:
        return str(e.code if e.code is not None else "")
    except Exception as e:                                    # noqa: BLE001
        return "EXCEÇÃO " + repr(e)
    return ""


# ────────────────────────────────────────────────────────── material sintético

def edl_sintetica():
    """Bordas DE PROPÓSITO fora do frame: é o que faz Σ(end−start) ≠ Σ frames/fps.

    Com takes de 3,00 s exatos a soma nominal acertaria por acidente e o teste da
    §7.4 não teria nada para medir."""
    return [{"src": "bruto.mp4", "start": s, "end": s + d,
             "fala": "fala sintetica %d" % k, "beat": b}
            for k, (s, d, b) in enumerate(
                [(1.03, 2.97, "abertura"), (6.27, 3.11, "meio"), (11.41, 2.62, "fecho")])]


def semear(base, com_perfil=True):
    os.makedirs(base, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=256x456:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "20", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", os.path.join(base, "bruto.mp4")], check=True)
    with open(os.path.join(base, "edl.json"), "w") as fh:
        json.dump(edl_sintetica(), fh, ensure_ascii=False, indent=1)
    if com_perfil:
        # 🔒 escrito à mão a partir do catálogo. `perfil.py resolver` também
        # ESCREVE em tools/remotion-compositor/src/data/perfil.json — fora da
        # produção, e um teste não pode mexer na árvore de ninguém.
        p = json.load(open(os.path.join(os.path.dirname(SCRIPTS), "perfis", "reels.json")))
        base_p = json.load(open(os.path.join(os.path.dirname(SCRIPTS), "perfis", "_base.json")))
        merged = json.loads(json.dumps(base_p))

        def funde(a, b):
            for k, v in b.items():
                if isinstance(v, dict) and isinstance(a.get(k), dict):
                    funde(a[k], v)
                else:
                    a[k] = v
        funde(merged, p)
        merged["video"]["largura"], merged["video"]["altura"] = 256, 456
        with open(os.path.join(base, "perfil.json"), "w") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(base, "PLANO-EDICAO.md"), "w") as fh:
        fh.write("# Plano (sintético)\n\nO raciocínio das decisões vive aqui.\n")
    return base


def montar(base):
    r = subprocess.run(["bash", MONTAR, base], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("montar.sh falhou:\n" + r.stderr[-2000:])
    return base


# ──────────────────────────────────── 0 · doc × código × fixture (achado 3.4)

def c0_doc_e_fixtures():
    """`references/contrato-ui.md` é a FONTE DE VERDADE para SPEC-17/18/19.

    Um doc que descreve um campo que o código não tem (ou o contrário) é o achado
    3.4 do `ACHADOS-DO-CODIGO.md` — `bordas.py` × `SKILL.md:44`, divergência
    doc↔código que obrigou a congelar os valores do CÓDIGO na migração. Aqui ela
    é conferível por comando, então não sobrevive a um commit."""
    print("\n0 · doc × código × fixtures: nenhum campo só de um lado (achado 3.4)")
    doc_p = os.path.join(os.path.dirname(SCRIPTS), "references", "contrato-ui.md")
    if not os.path.isfile(doc_p):
        return ok("references/contrato-ui.md existe", False, doc_p)
    doc = open(doc_p, encoding="utf-8").read()
    grupos = [("estado", est_mod._CAMPOS_ESTADO),
              ("segmento", est_mod._CAMPOS_SEG),
              ("ajustes", tuple(est_mod._ESQ_AJUSTES["obrigatorios"])
                          + tuple(est_mod._ESQ_AJUSTES["opcionais"])),
              ("estilo", tuple(est_mod._ESQ_ESTILO["obrigatorios"])
                         + tuple(est_mod._ESQ_ESTILO["opcionais"]))]
    n = 0
    for nome, campos in grupos:
        faltando = [c for c in campos
                    if ('"%s"' % c) not in doc and ("`%s`" % c) not in doc]
        n += len(campos)
        ok("todos os campos de `%s` estão documentados" % nome, not faltando,
           "%d campos, faltando: %s" % (len(campos), faltando or "nenhum"))
    varrido["campos de contrato conferidos contra o doc"] = n

    fx = os.path.join(AQUI, "fixtures")
    if not os.path.isdir(fx):
        return ok("fixtures/ existe", False, fx)
    est = json.load(open(os.path.join(fx, "estado-exemplo.json")))
    ok("fixture estado-exemplo.json é válida", est_mod.validar(est) == [],
       "0 violações · %d segmentos · veredito %s"
       % (len(est["segmentos"]), est["integridade"]["veredito"]))
    for nome in ("ajustes-exemplo.json", "estilo-exemplo.json"):
        obj = json.load(open(os.path.join(fx, nome)))
        ok("fixture %s é válida contra o estado-exemplo" % nome,
           est_mod.validar(obj, est=est) == [],
           "0 violações (%s)" % obj["contrato"])
    bruto = json.dumps(est, ensure_ascii=False).lower()
    ok("fixtures sem nome de creator e sem caminho absoluto",
       not any(t in bruto for t in ("/users/", "creator-2", "creator-3", "img_")),
       "material 100% sintético (testsrc2), como manda a FRONTEIRA §4")
    varrido["fixtures conferidas"] = 3


# ──────────────────────────────────────────────────────────── 1 · sid (§3.4, §7.7)

def c1_sid():
    print("\n1 · `sid`: estável sob borda, muda quando a identidade muda (§3.4)")
    segs = edl_sintetica()
    a = est_mod.sid_de(segs)
    varrido["segmentos com sid derivado"] = len(a)
    ok("sids únicos e legíveis", a == ["abertura#1", "meio#1", "fecho#1"], str(a))

    movidos = json.loads(json.dumps(segs))
    for s in movidos:
        s["start"] += 0.30
        s["end"] -= 0.30
    ok("borda ±0,30 s não muda sid (3/3)", est_mod.sid_de(movidos) == a,
       "os 3 preservados")

    renomeado = json.loads(json.dumps(segs))
    renomeado[1]["beat"] = "miolo"
    b = est_mod.sid_de(renomeado)
    mudou = [i for i in range(len(a)) if a[i] != b[i]]
    ok("renomear 1 beat muda EXATAMENTE 1 sid", len(mudou) == 1,
       "mudou %s → %s" % (a[mudou[0]] if mudou else "—", b[mudou[0]] if mudou else "—"))

    sem_beat = [{"src": "input/vsl-original.mp4", "f0": 0, "f1": 126},
                {"src": "input/vsl-original.mp4", "f0": 126, "f1": 250}]
    ok("sem `beat` cai no basename do src", est_mod.sid_de(sem_beat) ==
       ["vsl-original#1", "vsl-original#2"], str(est_mod.sid_de(sem_beat)))

    removido = [s for s in segs if s["beat"] != "meio"]
    c = est_mod.sid_de(removido)
    ok("remover o do MEIO não desloca os vizinhos (o bug app.js:1826)",
       c == ["abertura#1", "fecho#1"],
       "%s — no ref-A o `fecho` herdaria o índice do `meio`" % c)


# ─────────────────────────────────────────────── 2 · schema e validação (§7.1, §7.5)

def c2_validacao(d):
    print("\n2 · `validar()`: campo desconhecido, tipo, enum, sid, revisao_base (§7.5)")
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("estado real de produção sintética passa", est_mod.validar(est) == [],
       "0 violações em %d campos de topo" % len(est))

    n_defeitos = 0
    casos = [
        ("campo desconhecido no estado",
         lambda e: e.update({"xyzzy": 1}), "campo desconhecido"),
        ("campo obrigatório ausente",
         lambda e: e.pop("integridade"), "obrigatório ausente"),
        ("revisao com tipo errado",
         lambda e: e.update({"revisao": "sete"}), "inteiro"),
        ("procedencia fora do enum",
         lambda e: e["segmentos"][0]["procedencia"].update({"estado": "talvez"}),
         "fora do enum"),
        ("sid duplicado",
         lambda e: e["segmentos"][1].update({"sid": e["segmentos"][0]["sid"]}),
         "duplicado"),
        ("`saida` preenchida sem timeline_real",
         lambda e: e.update({"timeline_real": None}), "sem timeline_real"),
        ("zonas_ui sem perfil",
         lambda e: (e["formato"].update({"fonte": "medido"}),
                    e.update({"zonas_ui": {"topo_pct": 0.1}})), "sem perfil"),
        ("veredito de integridade fora do enum",
         lambda e: e["integridade"].update({"veredito": "mais ou menos"}),
         "fora do enum"),
    ]
    for nome, estraga, agulha in casos:
        corrompido = json.loads(json.dumps(est))
        estraga(corrompido)
        erros = est_mod.validar(corrompido)
        achou = any(agulha in x for x in erros)
        n_defeitos += 1
        ok("acusa: %s" % nome, achou,
           (erros[0] if erros else "NÃO ACUSOU — portão sem dentes")[:110])
    varrido["defeitos plantados no estado, todos acusados"] = n_defeitos


def c3_canal_de_volta(d):
    print("\n3 · canal de volta: sem índice, sem coordenada chutada (§7.6, §7.13)")
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    aj = ajustes_de(est)
    ok("ajustes bem formado passa", est_mod.validar(aj, est=est) == [],
       "%d nota(s), %d operação(ões)" % (len(aj["notas"]), len(aj["operacoes"])))

    ruins = [
        ("índice posicional numa nota",
         lambda o: o["notas"][0].update({"i": 3}), "índice posicional é PROIBIDO"),
        ("sid inexistente",
         lambda o: o["operacoes"][0].update({"sid": "fantasma#9"}), "sid inexistente"),
        ("op fora do enum",
         lambda o: o["operacoes"][0].update({"op": "apagar-tudo"}), "fora do enum"),
        ("revisao_base no futuro",
         lambda o: o.update({"revisao_base": 9999}), "FUTURO"),
        ("campo desconhecido no topo",
         lambda o: o.update({"ranges": []}), "campo desconhecido"),
        ("campo desconhecido dentro da nota",
         lambda o: o["notas"][0].update({"renderedStart": 1.0}), "campo desconhecido"),
        ("tipo errado em revisao_base",
         lambda o: o.update({"revisao_base": "sete"}), "esperado num"),
    ]
    for nome, estraga, agulha in ruins:
        c = json.loads(json.dumps(aj))
        estraga(c)
        erros = est_mod.validar(c, est=est)
        ok("acusa: %s" % nome, any(agulha in x for x in erros),
           (erros[0] if erros else "NÃO ACUSOU — portão sem dentes")[:110])
    varrido["defeitos plantados no canal de volta"] = len(ruins)

    # §7.13 — coordenada de render aproximada NÃO entra no canal de volta
    sem_tl = json.loads(json.dumps(est))
    sem_tl["timeline_real"] = None
    for s in sem_tl["segmentos"]:
        s["saida"] = None
    aj_sem = ajustes_de(sem_tl)
    n_render = len([n for n in aj_sem["notas"] if n["render"] is not None])
    ok("sem timeline_real: 0 notas com coordenada de render", n_render == 0,
       "%d de %d notas com `render` preenchido" % (n_render, len(aj_sem["notas"])))
    forjado = json.loads(json.dumps(aj_sem))
    forjado["notas"][0]["render"] = {"ini": 3.23, "fim": 4.43}   # o chute proibido
    erros = est_mod.validar(forjado, est=sem_tl)
    ok("acusa coordenada de render forjada sem timeline_real",
       any("PROIBIDA" in x for x in erros),
       (erros[0] if erros else "NÃO ACUSOU — portão sem dentes")[:110])
    ok("nenhum índice posicional no ajustes serializado",
       '"i":' not in json.dumps(aj, ensure_ascii=False).replace(" ", ""),
       "grep '\"i\":' → 0")


def ajustes_de(est):
    """Constrói um `benchmark.edit-ajustes/v1` a partir do estado — pelo MESMO
    caminho de código que a UI vai usar (`coordenada_render`)."""
    sids = [s["sid"] for s in est["segmentos"]]
    alvo = est["segmentos"][1]
    ini = alvo["rascunho"]["ini_s"] + 0.23
    fim = ini + 1.20
    return {
        "contrato": est_mod.CONTRATO_AJUSTES,
        "salvo_em": "2026-08-08T15:41:19-03:00",
        "revisao_base": est["revisao"],
        "fingerprint_corte": est["fingerprint_corte"],
        "fingerprint_render": est["fingerprint_render"],
        "render_alvo": est["render_corrente"],
        "notas": [{"sid": sids[1], "rascunho": {"ini": ini, "fim": fim},
                   "render": est_mod.coordenada_render(est, sids[1], ini, fim),
                   "fase": 1, "texto": "o corte come o começo da palavra"}],
        "operacoes": [{"sid": sids[2], "op": "ajustar",
                       "de": {"start": est["segmentos"][2]["start"],
                              "end": est["segmentos"][2]["end"]},
                       "para": {"start": est["segmentos"][2]["start"] - 0.10,
                                "end": est["segmentos"][2]["end"]}}],
        "elementos": [{"ref": "cartao-3", "op": "mover",
                       "para": {"ini": 1.30, "fim": 2.10}}],
    }


def estilo_de(est):
    return {"contrato": est_mod.CONTRATO_ESTILO,
            "salvo_em": "2026-08-08T15:52:03-03:00",
            "revisao_base": est["revisao"], "rerender": False,
            "legenda": "karaoke", "headline": "realce", "acento": "#D14E72",
            "acento_usado": True,
            "elementos": {"punch_alternado": True, "split_broll": False,
                          "sfx": True, "trilha": False, "flash_no_corte": False},
            "gramatica_plano": "alternada",
            "observacao": "o cartão do CTA pode entrar mais tarde"}


# ──────────────────────────────────────── 4 · coordenada honesta (§7.4) e degradação

def c4_coordenada(d):
    print("\n4 · coordenada de render: timeline_real × Σ(end−start), os DOIS na mesa (§7.4)")
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    tl = est["timeline_real"]
    fps = est["formato"]["fps"]
    um_frame_ms = 1000.0 / fps

    # instrumento independente: a duração de CONTAINER de cada segmento, somada.
    # É outro campo do ffprobe e outro caminho de código que o `nb_read_frames`
    # com que a timeline foi medida — se os dois batem, não é a régua se medindo.
    acc, medido = 0.0, []
    for s in est["segmentos"]:
        medido.append(acc)
        p = os.path.join(d, s["arquivo"])
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v",
                              "-show_entries", "format=duration", "-of", "csv=p=0", p],
                             capture_output=True, text=True).stdout.strip()
        acc += float(out)

    pior_tl = pior_nominal = 0.0
    for i, s in enumerate(est["segmentos"]):
        via_tl = tl["segments"][i]["start_s"]
        via_nominal = s["rascunho"]["ini_s"]
        pior_tl = max(pior_tl, abs(via_tl - medido[i]) * 1000)
        pior_nominal = max(pior_nominal, abs(via_nominal - medido[i]) * 1000)
    varrido["fronteiras de segmento conferidas contra ffprobe"] = len(est["segmentos"])
    ok("com timeline_real: erro < 1 frame (%.1f ms)" % um_frame_ms,
       pior_tl < um_frame_ms, "pior erro %.1f ms" % pior_tl)
    ok("por Σ(end−start): erro MAIOR que 1 frame — é o anti-pattern",
       pior_nominal > um_frame_ms,
       "pior erro %.1f ms (%.1f× o frame). É o mesmo erro que dá 353 ms em "
       "`peca-03`, 317 em `peca-01`, 352 em `c-completo`"
       % (pior_nominal, pior_nominal / um_frame_ms))

    # a régua independente mais forte: o render inteiro
    rend = next(r for r in est["renders"] if r["arquivo"] == est["render_corrente"])
    erro_total = abs(tl["total_s"] - rend["frames"] / rend["fps"]) * 1000
    ok("timeline_real total == frames do render / fps", erro_total < um_frame_ms,
       "%.6f s vs %.6f s (Δ %.2f ms); a soma nominal dá %.6f s (Δ %.1f ms)"
       % (tl["total_s"], rend["frames"] / rend["fps"], erro_total,
          est["integridade"]["soma_nominal_s"], est["integridade"]["delta_nominal_ms"]))


def c5_degradado(base):
    print("\n5 · modo degradado: sem perfil.json e sem timeline_real (§7.5)")
    d = os.path.join(base, "sem-perfil")
    shutil.copytree(os.path.join(base, "prod"), d, symlinks=True)
    os.remove(os.path.join(d, "perfil.json"))
    os.remove(os.path.join(d, "timeline-real.json"))
    shutil.rmtree(os.path.join(d, ".preview"), ignore_errors=True)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("formato.fonte == 'medido'", est["formato"]["fonte"] == "medido",
       "%(largura)sx%(altura)s@%(fps)s medidos do primeiro segmento" % est["formato"])
    ok("formato medido bate com o ffprobe do segmento",
       (est["formato"]["largura"], est["formato"]["altura"]) ==
       (est["segmentos"][0]["medido"]["largura"], est["segmentos"][0]["medido"]["altura"]),
       "%s == %s" % ((est["formato"]["largura"], est["formato"]["altura"]),
                     (est["segmentos"][0]["medido"]["largura"],
                      est["segmentos"][0]["medido"]["altura"])))
    ok("zonas_ui == null sem perfil", est["zonas_ui"] is None, "null")
    ok("perfil == null sem perfil.json", est["perfil"] is None, "null")
    ok("timeline_real == null", est["timeline_real"] is None, "null")
    ok("`saida` == null em 100% dos segmentos",
       all(s["saida"] is None for s in est["segmentos"]),
       "%d/%d" % (len(est["segmentos"]), len(est["segmentos"])))
    ok("aviso nomeia o motivo da timeline",
       any("timeline_real ausente" in a for a in est["avisos"]),
       "%d aviso(s): %s" % (len(est["avisos"]), " | ".join(est["avisos"])[:120]))
    ok("estado degradado ainda é válido", est_mod.validar(est) == [], "0 violações")
    return d


# ─────────────────────────────────────────── 6 · integridade: órfão e procedência

def c6_integridade(base):
    print("\n6 · integridade: órfão, sidecar ausente e sidecar divergente (§7.2, §7.3)")
    d = os.path.join(base, "quebrada")
    shutil.copytree(os.path.join(base, "prod"), d, symlinks=True)
    shutil.rmtree(os.path.join(d, ".preview"), ignore_errors=True)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("produção íntegra: veredito 'ok'", est["integridade"]["veredito"] == "ok",
       "delta_real %.1f ms, %d/%d sidecares"
       % (est["integridade"]["delta_real_ms"], len(est["segmentos"]),
          len(est["segmentos"])))

    # ÓRFÃO: .mp4 a mais no disco que na EDL (o defeito de 6,25 s do creator-3)
    orfao = os.path.join(d, "segs", "seg009.mp4")
    shutil.copy(os.path.join(d, "segs", "seg000.mp4"), orfao)
    antes = len(os.listdir(os.path.join(d, "segs")))
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    depois = len(os.listdir(os.path.join(d, "segs")))
    ok("acusa órfão: veredito 'quebrado'", est["integridade"]["veredito"] == "quebrado",
       "disco %d × EDL %d, orfaos=%s" % (est["integridade"]["segs_no_disco"],
                                         est["integridade"]["segs_na_edl"],
                                         est["integridade"]["orfaos"]))
    ok("REPORTA, NÃO CONSERTA: nada foi apagado", antes == depois,
       "%d arquivos em segs/ antes e depois" % depois)
    os.remove(orfao)

    # SIDECAR AUSENTE ≠ ÓRFÃO
    lado = os.path.join(d, "segs", "seg001.json")
    guardado = open(lado).read()
    os.remove(lado)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("sidecar ausente vira 'ausente' em 1 segmento, não órfão",
       est["segmentos"][1]["procedencia"]["estado"] == "ausente"
       and est["integridade"]["orfaos"] == []
       and len(est["integridade"]["sem_sidecar"]) == 1,
       "sem_sidecar=%s orfaos=%s veredito=%s"
       % (est["integridade"]["sem_sidecar"], est["integridade"]["orfaos"],
          est["integridade"]["veredito"]))

    # CAMPO NOVO NO SIDECAR, sem contraparte na EDL: NÃO é divergência.
    # Medido: o `montar.sh` ganhou `video_skip_frames` durante esta onda (SPEC-07).
    # Um comparador com lista fixa de nomes teria acusado 3/3 como divergentes.
    with open(lado, "w") as fh:
        fh.write(guardado)
    side = json.loads(guardado)
    side["campo_inventado_amanha"] = 7
    with open(lado, "w") as fh:
        json.dump(side, fh)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    pr = est["segmentos"][1]["procedencia"]
    ok("campo do sidecar sem contraparte na EDL não vira divergência, mas APARECE",
       pr["estado"] == "ok" and "campo_inventado_amanha" in (pr.get("extras_sidecar") or []),
       "estado=%s extras_sidecar=%s" % (pr["estado"], pr.get("extras_sidecar")))

    # SIDECAR DIVERGENTE: um campo, um segmento
    side = json.loads(guardado)
    side["start"] = side["start"] + 0.37
    with open(lado, "w") as fh:
        json.dump(side, fh)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    div = est["integridade"]["divergentes"]
    ok("acusa divergência em EXATAMENTE 1 segmento, campo ['start']",
       len(div) == 1 and div[0]["campos"] == ["start"]
       and est["segmentos"][1]["procedencia"]["estado"] == "divergente",
       "%s" % json.dumps(div, ensure_ascii=False)[:150])
    n_ok = sum(1 for s in est["segmentos"] if s["procedencia"]["estado"] == "ok")
    ok("os outros continuam 'ok' (não é contaminação em massa)",
       n_ok == len(est["segmentos"]) - 1, "%d de %d" % (n_ok, len(est["segmentos"])))
    with open(lado, "w") as fh:
        fh.write(guardado)
    varrido["defeitos de integridade plantados e acusados"] = 3
    return d


# ─────────────────────────────── 7 · revisão, atomicidade e aprovação (§7.8/10/11)

def c7_revisao_e_atomicidade(d):
    print("\n7 · revisão monotônica, escrita atômica e toast que não prende (§7.8, §7.10)")
    est_mod.escrever(d, est_mod.gerar(d))
    a = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ag = est_mod._agente(d)
    ag["mensagem"] = "mensagem diferente, corte idêntico"
    est_mod._gravar_agente(d, ag)
    est_mod.escrever(d, est_mod.gerar(d))
    b = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("mudar só a mensagem NÃO muda fingerprint_corte nem fingerprint_render",
       a["fingerprint_corte"] == b["fingerprint_corte"]
       and a["fingerprint_render"] == b["fingerprint_render"],
       "corte %s · render %s" % (b["fingerprint_corte"][:16], b["fingerprint_render"][:16]))
    ok("revisão avança mesmo assim (é o que mata o toast preso do app.js:726)",
       b["revisao"] == a["revisao"] + 1, "%d → %d" % (a["revisao"], b["revisao"]))

    # 50 escritas × 200 leituras concorrentes
    est_base = est_mod.gerar(d)
    revs, erros_json, leituras = [], [], [0]
    parar = threading.Event()

    def leitor():
        while not parar.is_set():
            leituras[0] += 1
            try:
                json.load(open(os.path.join(d, ".preview", "estado.json")))
            except Exception as e:                             # noqa: BLE001
                erros_json.append(repr(e))

    fios = [threading.Thread(target=leitor, daemon=True) for _ in range(4)]
    for f in fios:
        f.start()
    for _ in range(50):
        est_mod.escrever(d, est_base)
        revs.append(json.load(open(os.path.join(d, ".preview", "estado.json")))["revisao"])
    parar.set()
    for f in fios:
        f.join(timeout=2)
    varrido["escritas concorrentes"] = len(revs)
    varrido["leituras concorrentes"] = leituras[0]
    ok("50 escritas: revisão estritamente crescente",
       all(revs[i] < revs[i + 1] for i in range(len(revs) - 1)),
       "%d → %d, %d/%d crescentes" % (revs[0], revs[-1], len(revs), len(revs)))
    ok("%d leituras concorrentes: 0 falhas de json.loads" % leituras[0],
       not erros_json and leituras[0] >= 200,
       "%d erro(s)" % len(erros_json) if erros_json else "0 erros")
    sobra = [x for x in os.listdir(os.path.join(d, ".preview")) if x.endswith(".parcial")]
    ok("nenhum `.parcial` sobra", not sobra, str(sobra))


def c8_aprovacao(d):
    print("\n8 · aprovação confrontável com o disco (§7.11)")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "estado.py"), d,
                        "--aprovar", "fase-1", "--por", "teste"],
                       capture_output=True, text=True)
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("aprovação registrada e válida",
       len(est["aprovacoes"]) == 1 and est["aprovacoes"][0]["valida"] is True,
       json.dumps(est["aprovacoes"][0], ensure_ascii=False)[:130] if est["aprovacoes"]
       else "nenhuma (%s)" % r.stderr[-120:])

    # A UI envia o conteúdo que estava na tela quando abriu o diálogo. O
    # servidor precisa aceitar o par exato e recusar qualquer mudança ocorrida
    # entre abrir e confirmar, antes de acrescentar a aprovação.
    contexto = {
        "alvo": "fase-2" if (est.get("fase") or 1) >= 2 else "fase-1",
        "fingerprint_corte": est["fingerprint_corte"],
        "fingerprint_render": est["fingerprint_render"],
        "render_alvo": est["render_corrente"],
        "plano_sha256": (est.get("plano") or {}).get("sha256"),
    }
    ag_teste = {}
    reg = est_mod.registrar_aprovacao(
        d, "fase-1", "teste-ui", ag=ag_teste, esperado=contexto)
    ok("contexto exato da tela autoriza a aprovação",
       reg["render_fingerprint"] == contexto["fingerprint_render"]
       and len(ag_teste.get("aprovacoes", [])) == 1,
       str(reg))
    contexto_velho = dict(contexto)
    contexto_velho["fingerprint_render"] = "sha1:" + "0" * 40
    ag_recusado = {}
    try:
        est_mod.registrar_aprovacao(
            d, "fase-1", "teste-ui", ag=ag_recusado, esperado=contexto_velho)
        erro_contexto = None
    except est_mod.ErroAprovacao as exc:
        erro_contexto = str(exc)
    ok("contexto divergente recusa antes de registrar",
       erro_contexto and "fingerprint_render" in erro_contexto
       and not ag_recusado.get("aprovacoes"),
       erro_contexto or "não recusou")

    plano = os.path.join(d, "PLANO-EDICAO.md")
    with open(plano, "a") as fh:
        fh.write(".")                       # UM byte
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("1 byte no plano invalida a aprovação, com o motivo nomeado",
       est["aprovacoes"][0]["valida"] is False
       and "plano_sha256 divergente" in (est["aprovacoes"][0]["motivo"] or ""),
       "motivo: %r" % est["aprovacoes"][0]["motivo"])

    rend = os.path.join(d, est["render_corrente"])
    os.utime(rend, (os.stat(rend).st_atime, os.stat(rend).st_mtime + 60))
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    ok("render mexido também invalida",
       "render_fingerprint divergente" in (est["aprovacoes"][0]["motivo"] or ""),
       "motivo: %r" % est["aprovacoes"][0]["motivo"])


# ──────────────────────────── 9 · os dois caminhos de entrada (§3.12, §7.12)

def envelope(payload, tipo):
    return {"schema": est_mod.ENVELOPE, "tipo": tipo,
            "salvo_em": payload["salvo_em"],
            "origem": {"ua": "teste", "token": "0" * 12}, "payload": payload}


def c9_dois_caminhos(base):
    print("\n9 · os dois caminhos de entrada dão o MESMO resultado (§7.12)")
    resultados, contagens = [], []
    for modo in ("cru", "envelope"):
        d = os.path.join(base, "entrada-" + modo)
        shutil.copytree(os.path.join(base, "prod"), d, symlinks=True)
        shutil.rmtree(os.path.join(d, ".preview"), ignore_errors=True)
        est_mod.escrever(d, est_mod.gerar(d))
        est = json.load(open(os.path.join(d, ".preview", "estado.json")))
        aj = ajustes_de(est)
        prev = os.path.join(d, ".preview")
        if modo == "cru":
            est_mod._escrever_atomico(os.path.join(prev, "ajustes.json"), aj)
        else:
            os.makedirs(os.path.join(prev, "pendentes"), exist_ok=True)
            est_mod._escrever_atomico(
                os.path.join(prev, "pendentes", "20260808T154119-ajustes-1.json"),
                envelope(aj, "ajustes"))
        antes = len(subprocess.run(["find", prev, "-name", "*.json"],
                                   capture_output=True, text=True).stdout.split())
        r = est_mod.consumir(d, "ajustes")
        depois = len(subprocess.run(["find", prev, "-name", "*.json"],
                                    capture_output=True, text=True).stdout.split())
        resultados.append((est_mod.resumo(r["item"]["payload"]), r["ack"]))
        contagens.append((antes, depois,
                          len(os.listdir(os.path.join(prev, "pendentes")))
                          if os.path.isdir(os.path.join(prev, "pendentes")) else 0,
                          len(os.listdir(os.path.join(prev, "aplicados")))))
    ok("resumo() byte a byte idêntico nos dois caminhos",
       resultados[0][0].encode() == resultados[1][0].encode(),
       "%d bytes" % len(resultados[0][0].encode()))
    chaves = ("tipo", "salvo_em", "revisao_base", "notas", "operacoes", "elementos",
              "superados", "conflito")
    ok("ultimo_ajuste_aplicado idêntico (menos `arquivo` e `aplicado_em`)",
       {k: resultados[0][1][k] for k in chaves} == {k: resultados[1][1][k] for k in chaves},
       json.dumps({k: resultados[0][1][k] for k in chaves}, ensure_ascii=False))
    for modo, (antes, depois, n_pend, n_apl) in zip(("cru", "envelope"), contagens):
        ok("[%s] ACK é o MOVE: pendentes 0, aplicados 1, nada apagado" % modo,
           n_pend == 0 and n_apl == 1 and depois >= antes,
           "pendentes=%d aplicados=%d · %d arquivos .json antes, %d depois"
           % (n_pend, n_apl, antes, depois))
    varrido["caminhos de entrada exercitados"] = 2

    # dois pendentes do MESMO tipo: o mais novo vence, o mais velho é arquivado
    d = os.path.join(base, "fila-dupla")
    shutil.copytree(os.path.join(base, "prod"), d, symlinks=True)
    shutil.rmtree(os.path.join(d, ".preview"), ignore_errors=True)
    est_mod.escrever(d, est_mod.gerar(d))
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    pend = os.path.join(d, ".preview", "pendentes")
    os.makedirs(pend, exist_ok=True)
    velho = ajustes_de(est)
    velho["salvo_em"] = "2026-08-08T15:41:19-03:00"
    velho["notas"][0]["texto"] = "pedido VELHO, superado"
    novo = ajustes_de(est)
    novo["salvo_em"] = "2026-08-08T15:49:02-03:00"
    novo["notas"][0]["texto"] = "pedido NOVO, é o que vale"
    est_mod._escrever_atomico(os.path.join(pend, "20260808T154119-ajustes-1.json"),
                              envelope(velho, "ajustes"))
    est_mod._escrever_atomico(os.path.join(pend, "20260808T154902-ajustes-2.json"),
                              envelope(novo, "ajustes"))
    r = est_mod.consumir(d, "ajustes")
    aplicados = sorted(os.listdir(os.path.join(d, ".preview", "aplicados")))
    ignorados = [a for a in aplicados
                 if json.load(open(os.path.join(d, ".preview", "aplicados", a)))
                 .get("ignorado")]
    ok("o mais NOVO é o aplicado (1 aplicação, não 2)",
       r["item"]["payload"]["notas"][0]["texto"] == "pedido NOVO, é o que vale"
       and len(r["superados"]) == 1,
       "aplicado: %r" % r["item"]["payload"]["notas"][0]["texto"])
    ok("o mais VELHO vai para aplicados/ com `ignorado` preenchido",
       len(aplicados) == 2 and len(ignorados) == 1,
       "%d arquivo(s), %d marcado(s) ignorado: %s" % (len(aplicados), len(ignorados),
                                                      ignorados))
    ok("pendentes/ esvaziou (o watcher re-arma)",
       os.listdir(pend) == [], str(os.listdir(pend)))

    # conflito: o corte mudou entre o salvar e o aplicar
    d2 = os.path.join(base, "conflito")
    shutil.copytree(os.path.join(base, "prod"), d2, symlinks=True)
    shutil.rmtree(os.path.join(d2, ".preview"), ignore_errors=True)
    est_mod.escrever(d2, est_mod.gerar(d2))
    est2 = json.load(open(os.path.join(d2, ".preview", "estado.json")))
    aj = ajustes_de(est2)
    aj["fingerprint_corte"] = "sha1:" + "0" * 40
    est_mod._escrever_atomico(os.path.join(d2, ".preview", "ajustes.json"), aj)
    msg = morre(est_mod.consumir, d2, "ajustes")
    ainda = os.path.isfile(os.path.join(d2, ".preview", "ajustes.json"))
    ok("conflito de fingerprint_corte: recusa e NÃO move",
       msg == "2" and ainda, "exit %r · ajustes.json ainda em .preview: %s"
       % (msg, ainda))
    r = est_mod.consumir(d2, "ajustes", mesmo_com_conflito=True)
    ok("--mesmo-com-conflito FAZ o que diz (aplica e registra o conflito)",
       r is not None and r["ack"]["conflito"]
       and not os.path.isfile(os.path.join(d2, ".preview", "ajustes.json")),
       "conflito registrado: %s" % (r["ack"]["conflito"] or "")[:90])


def c10_resumo(d):
    print("\n10 · `resumo()`: o digest que o watcher imprime (§3.11)")
    est = json.load(open(os.path.join(d, ".preview", "estado.json")))
    r_aj = est_mod.resumo(ajustes_de(est))
    ok("resumo de ajustes avisa que implica REMONTAR", "REMONTAR" in r_aj,
       r_aj.splitlines()[0])
    est_sem = json.loads(json.dumps(est))
    est_sem["timeline_real"] = None
    for s in est_sem["segmentos"]:
        s["saida"] = None
    r_sem = est_mod.resumo(ajustes_de(est_sem))
    ok("sem timeline_real o resumo DIZ que a coordenada não existe",
       "indisponível" in r_sem, [x for x in r_sem.splitlines() if "render" in x][0].strip())
    r_es = est_mod.resumo(estilo_de(est))
    fora = [x for x in r_es.splitlines() if x.strip().startswith("fora:")]
    ok("caixa desmarcada é NÃO explícito (linha `fora:`)",
       fora and "split_broll" in fora[0] and "trilha" in fora[0], fora[0].strip() if fora else "—")
    e2 = estilo_de(est)
    e2["acento_usado"] = False
    ok("`acento_usado: false` sai com a ressalva de não inventar onde usar",
       "não invente" in est_mod.resumo(e2), "ok")
    ok("gramatica_plano avisa que afeta o CORTE, não só o alpha",
       "afeta o CORTE" in r_es, "ok")


# ────────────────────────────────────────────────────── 11 · material real (PULADO)

def c11_material_real():
    print("\n11 · material real (PULADO onde `creators/` não existe — é nosso, não produto)")
    raiz = SCRIPTS
    alvo = None
    while raiz != os.path.dirname(raiz):
        if os.path.isdir(os.path.join(raiz, "creators")):
            alvo = os.path.join(raiz, "creators")
            break
        raiz = os.path.dirname(raiz)
    if alvo is None:
        print("  [PULADO] não há `creators/` nesta árvore")
        return
    casos = [("creator-2/producao/peca-03", 20, "ausente", 0),
             ("creator-2/producao/peca-01", 29, "ok", 0),
             ("creator-2/producao/ovo-de-pascoa", 21, "ausente", 1),
             ("creator-2/producao/peca-04", 17, "ausente", 0),
             ("creator-1/producao/peca-09", 18, "ok", 0),
             ("creator-3/producao/peca-10-27-07/c-completo", 16, "ok", 0)]
    n = 0
    for rel, n_segs, proc, n_orfaos in casos:
        d = os.path.join(alvo, rel)
        if not os.path.isdir(d):
            print("  [PULADO] %s" % rel)
            continue
        est = est_mod.gerar(d)
        n += 1
        estados = {s["procedencia"]["estado"] for s in est["segmentos"]}
        ok("%s: %d segmentos, procedência %r em 100%%, %d órfão(s)"
           % (rel, n_segs, proc, n_orfaos),
           len(est["segmentos"]) == n_segs and estados == {proc}
           and len(est["integridade"]["orfaos"]) == n_orfaos
           and est_mod.validar(est) == [],
           "n=%d proc=%s orfaos=%d veredito=%s validar=%d"
           % (len(est["segmentos"]), sorted(estados),
              len(est["integridade"]["orfaos"]), est["integridade"]["veredito"],
              len(est_mod.validar(est))))
    varrido["produções reais varridas"] = n


# ──────────────────────────────────────────────────────────────────────── runner

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    rapido = "--rapido" in argv
    print("teste do contrato de dados da UI de aprovação (SPEC-16)")
    c0_doc_e_fixtures()
    c1_sid()
    if rapido:
        print("\n[--rapido] 2–10 pulados (chamam montar.sh)")
        c11_material_real()
    else:
        base = tempfile.mkdtemp(prefix="spec16-")
        try:
            d = montar(semear(os.path.join(base, "prod")))
            est_mod.escrever(d, est_mod.gerar(d))
            c2_validacao(d)
            c3_canal_de_volta(d)
            c4_coordenada(d)
            c5_degradado(base)
            dq = c6_integridade(base)
            c7_revisao_e_atomicidade(dq)
            c8_aprovacao(dq)
            c9_dois_caminhos(base)
            c10_resumo(d)
            c11_material_real()
        finally:
            shutil.rmtree(base, ignore_errors=True)
    print("\n── o que este teste varreu ──")
    for k, v in varrido.items():
        print("   %-48s %d" % (k, v))
    print("\n%d checagens · %s"
          % (N_CHECAGENS[0], "TUDO PASSOU" if not falhas
             else "FALHOU (%d): %s" % (len(falhas), ", ".join(falhas))))
    return 1 if falhas else 0


N_CHECAGENS = [0]
_ok_original = ok


def ok(nome, cond, detalhe):          # noqa: F811
    N_CHECAGENS[0] += 1
    return _ok_original(nome, cond, detalhe)


def test_contrato_ui():
    """Entrada do pytest — o mesmo runner, falhando o teste se algo falhar."""
    assert main([]) == 0, "falhas: %s" % ", ".join(falhas)


if __name__ == "__main__":
    sys.exit(main())
