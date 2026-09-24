#!/usr/bin/env python3
"""Teste da EDL v2 (SPEC-05) — autocontido: gera o próprio material sintético.

    python3 .claude/skills/edit-video/scripts/tests/test_edl_v2.py [--rapido]

`--rapido` pula os dois casos que chamam o `montar.sh` (render de ~3 s de vídeo
270x480 sintético) e roda só o que é aritmética e arquivo.

🔴 POR QUE ELE IMPRIME QUANTO VARREU E PLANTA DEFEITO DE PROPÓSITO
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado. Este repo já
entregou 6,25 s de vídeo errado com todos os QCs verdes. Então cada checagem aqui
faz DUAS coisas: afirma o caso bom (com o número medido) e planta o defeito que o
mecanismo TEM que acusar — timeline corrompida, EDL alterada depois do render,
`segments: null`, segmento em ordem lexicográfica. Verde sem os dois não vale.

Nada aqui toca material de creator: o bruto é `testsrc2` + rajadas de tom.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
sys.path.insert(0, SCRIPTS)
import edl_io   # noqa: E402
import perfil as perfil_mod  # noqa: E402

# os 5 campos DESCONHECIDOS do critério 1 — nenhum deles é lido pelo bordas.py
DESCONHECIDOS = {"gain_db": -1.5, "fadeOut": 0.04, "quem": "creator-2",
                 "lut": "neutro.cube", "xyzzy_teste": [1, 2, 3]}
# os 8 RESERVADOS: insumo do resolvedor de bordas, morrem lá
RESERVADOS = ["asr_ini", "asr_fim", "pre_extra", "post_extra",
              "limite_pre", "limite_pos", "start_fixo", "end_fixo"]

falhas = []
varrido = {}


def ok(nome, cond, detalhe):
    marca = "PASSOU" if cond else "FALHOU"
    print("  [%s] %s — %s" % (marca, nome, detalhe))
    if not cond:
        falhas.append(nome)
    return cond


def morre(fn, *a, **kw):
    """Roda `fn` esperando SystemExit (é assim que o edl_io recusa). Devolve a msg."""
    try:
        fn(*a, **kw)
    except SystemExit as e:
        return str(e.code if e.code is not None else "")
    except Exception as e:                       # noqa: BLE001
        return "EXCEÇÃO " + repr(e)
    return ""


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def fixture(dst):
    """8 s: rajadas de tom de 1 s a cada 2 s sobre testsrc2 270x480@30."""
    os.makedirs(dst, exist_ok=True)
    bruto = os.path.join(dst, "bruto.mp4")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i",
        "aevalsrc='0.30*sin(2*PI*300*t)*between(mod(t,2.0),0.20,1.20)':d=8:s=48000",
        "-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=8",
        "-map", "1:v", "-map", "0:a", "-c:v", "libx264", "-crf", "28",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", bruto], check=True)
    janelas = []
    for k, (ini, fim) in enumerate([(0.25, 1.15), (2.25, 3.15), (4.25, 5.15)]):
        j = {"src": "bruto.mp4", "asr_ini": ini, "asr_fim": fim,
             "beat": "b%d" % k, "fala": "tom %d" % k}
        j.update(DESCONHECIDOS)
        # os 8 reservados, todos presentes: nenhum pode vazar para o item da EDL
        j.update({"pre_extra": 0.0, "post_extra": 0.0,
                  "limite_pre": max(0.0, ini - 0.5), "limite_pos": fim + 0.5,
                  "start_fixo": ini - 0.05, "end_fixo": fim + 0.05})
        # 🔴 o critério 2 mora aqui: um `start` no janelas.json NÃO pode virar o
        # start da EDL — ele é o operador descrevendo o ASR, não a borda resolvida.
        j["start"] = 999
        janelas.append(j)
    with open(os.path.join(dst, "janelas.json"), "w") as fh:
        json.dump(janelas, fh, indent=1, ensure_ascii=False)
    # O teste mede EDL, não compatibilidade do FALLBACK histórico HLG. Declare
    # o contrato de cor do bruto sintético para que o gate obrigatório possa
    # resolver Rec.709 sem usar um override nem enfraquecer a montagem.
    perfil = json.loads(json.dumps(perfil_mod.FALLBACK_REELS))
    perfil["nome"] = "fixture-edl-v2"
    perfil["cor"]["entrada_esperada"] = "auto"
    with open(os.path.join(dst, "perfil.json"), "w") as fh:
        json.dump(perfil, fh, indent=1, ensure_ascii=False)
    return dst


def roda(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print("     (stderr) " + "\n     (stderr) ".join(
            r.stderr.strip().splitlines()[-6:]))
    return r


# ───────────────────────────────────────────────────────────────── os critérios

def c1_c2_passthrough(d):
    print("\n1+2 · passthrough e não-sobrescrita (bordas.py sobre bruto sintético)")
    r = roda([sys.executable, os.path.join(SCRIPTS, "bordas.py"), d])
    if not ok("bordas.py roda", r.returncode == 0, "exit %d" % r.returncode):
        return
    env = edl_io.carregar(d)
    segs = env["segments"]
    varrido["segmentos do fixture"] = len(segs)
    ok("envelope v2", env.get("schema") == edl_io.SCHEMA,
       "schema=%r" % env.get("schema"))
    faltando = [k for k in DESCONHECIDOS if not all(k in s for s in segs)]
    ok("5/5 campos desconhecidos atravessam",
       not faltando, "%d/%d presentes em todos os %d segmentos%s"
       % (len(DESCONHECIDOS) - len(faltando), len(DESCONHECIDOS), len(segs),
          "" if not faltando else " — faltou " + ", ".join(faltando)))
    vazou = sorted({k for s in segs for k in RESERVADOS if k in s})
    ok("0/8 campos reservados vazam",
       not vazou, "%d/%d vazaram%s" % (len(vazou), len(RESERVADOS),
                                       "" if not vazou else ": " + ", ".join(vazou)))
    ok("`start` do janelas.json NÃO sobrescreve a borda resolvida",
       all(s["start"] != 999 for s in segs),
       "starts na EDL: %s (o janelas.json dizia 999)"
       % ", ".join("%.3f" % s["start"] for s in segs))
    # 🦷 DENTES: o mesmo mecanismo tem que DEIXAR passar campo novo que ninguém
    # previu. Se a lista voltasse a ser BRANCA, `xyzzy_teste` sumiria em silêncio.
    ok("campo que ninguém previu (`xyzzy_teste`) chega intacto",
       all(s.get("xyzzy_teste") == [1, 2, 3] for s in segs),
       "valor preservado em %d/%d segmentos"
       % (sum(s.get("xyzzy_teste") == [1, 2, 3] for s in segs), len(segs)))


def c3_ida_e_volta(d):
    print("\n3 · ida e volta com chave de topo e campo de segmento desconhecidos")
    dd = os.path.join(d, "_roundtrip")
    os.makedirs(dd, exist_ok=True)
    env = {"schema": edl_io.SCHEMA, "perfil": "reels",
           "anotacao_do_editor": "x",
           "segments": [{"src": "a.mov", "start": 1.0, "end": 2.0, "fala": "oi",
                         "beat": "g", "campo_do_futuro": {"n": 1}}]}
    edl_io.gravar(dd, env)
    volta = edl_io.carregar(dd)
    ok("carregar(gravar(env)) == env (igualdade de dict)", volta == env,
       "chaves de topo: %s" % ", ".join(sorted(volta)))
    varrido["chaves de topo no round-trip"] = len(volta)
    # 🦷 DENTES: `segments: null` faria o `jq '(.segments // .)[]'` do montar.sh
    # iterar os VALORES do objeto e montar lixo sem uma linha de erro.
    msg = morre(edl_io.gravar, dd, {"schema": edl_io.SCHEMA, "segments": None})
    ok("`segments: null` é recusado na escrita", "segments" in msg,
       (msg.splitlines() or ["(saiu 0!)"])[0][:90])
    msg = morre(edl_io.gravar, dd, {"schema": edl_io.SCHEMA, "segments": []})
    ok("`segments: []` é recusado na escrita", "vazio" in msg,
       (msg.splitlines() or ["(saiu 0!)"])[0][:90])
    ok("o arquivo continua íntegro depois das duas recusas",
       edl_io.carregar(dd) == env, "round-trip ainda bate")


def c_ordenacao(d):
    print("\n· ordenação numérica dos segs (o bug lexicográfico de qc-ataque.py:46)")
    # 📏 O fixture usa a nomenclatura %02d das produções ANTIGAS, porque é nela
    # que o bug morde: com %03d (o que o montar.sh usa hoje) lexicográfico e
    # numérico coincidem, e um teste em %03d passaria verde sobre o código bugado.
    dd = os.path.join(d, "_ordem", "segs")
    os.makedirs(dd, exist_ok=True)
    indices = list(range(12)) + [100, 101]
    for i in indices:
        open(os.path.join(dd, "seg%02d.mp4" % i), "w").close()
    open(os.path.join(dd, "..", "edl.json"), "w").write("[]")
    nomes = [os.path.basename(p) for p in
             edl_io.segs_ordenados(os.path.join(d, "_ordem"))]
    esperado = ["seg%02d.mp4" % i for i in indices]
    varrido["arquivos de segmento ordenados"] = len(nomes)
    ok("seg100 vem DEPOIS de seg011", nomes == esperado,
       "%d arquivos, ordem %s…%s" % (len(nomes), ", ".join(nomes[:3]),
                                     ", ".join(nomes[-2:])))
    # 🦷 DENTES: o que a versão antiga (sorted(glob)) devolveria
    lex = sorted(esperado)
    i_dif = next((k for k in range(len(lex)) if lex[k] != esperado[k]), None)
    ok("a ordem lexicográfica REALMENTE difere (o bug era real)", i_dif is not None,
       "na posição %s o lexicográfico poria %s onde o numérico põe %s"
       % (i_dif, lex[i_dif] if i_dif is not None else "-",
          esperado[i_dif] if i_dif is not None else "-"))
    # nomes com %03d (o montar.sh de hoje) têm que ser reconhecidos junto
    dd2 = os.path.join(d, "_ordem2", "segs")
    os.makedirs(dd2, exist_ok=True)
    for i in range(3):
        open(os.path.join(dd2, "seg%03d.mp4" % i), "w").close()
    open(os.path.join(dd2, "..", "edl.json"), "w").write("[]")
    ok("nomes %03d do montar.sh de hoje são reconhecidos",
       len(edl_io.segs_ordenados(os.path.join(d, "_ordem2"))) == 3,
       "%d achados" % len(edl_io.segs_ordenados(os.path.join(d, "_ordem2"))))


def c_invariantes(d):
    print("\n· invariantes da timeline (aritmética pura, com defeito plantado)")
    tl = {"schema": edl_io.SCHEMA_TL, "gerado_por": "t", "gerado_em": "",
          "edl_fingerprint": "sha1:0", "sample_rate": 48000,
          "samples_por_frame": 1600,
          "video": {"width": 1080, "height": 1920, "fps": 30.0,
                    "fps_num": 30, "fps_den": 1},
          "total_frames": 150, "total_s": 5.0, "total_samples": 240000,
          "segments": [
              {"i": 0, "beat": "a", "src": "x", "src_start": 0.0, "src_end": 2.0,
               "frames": 60, "start_frame": 0, "start_s": 0.0, "dur_s": 2.0,
               "start_sample": 0, "samples": 96000},
              {"i": 1, "beat": "b", "src": "x", "src_start": 5.0, "src_end": 8.0,
               "frames": 90, "start_frame": 60, "start_s": 2.0, "dur_s": 3.0,
               "start_sample": 96000, "samples": 144000}]}
    edl_io.conferir_invariantes(tl)
    ok("timeline coerente passa", True, "2 segmentos, 150 frames, 5,000000 s")
    varrido["invariantes conferidas"] = 8
    for nome, mut in (
            ("total_frames mentindo", lambda t: t.update(total_frames=149)),
            ("start_frame fora da soma",
             lambda t: t["segments"][1].update(start_frame=59)),
            ("dur_s descolado de frames/fps",
             lambda t: t["segments"][0].update(dur_s=2.5)),
            ("total_samples ≠ Σ amostras", lambda t: t.update(total_samples=1)),
            ("samples ≠ frames×spf",
             lambda t: t["segments"][0].update(samples=96001))):
        mau = json.loads(json.dumps(tl))
        mut(mau)
        msg = morre(edl_io.conferir_invariantes, mau)
        ok("acusa: " + nome, "INCONSISTENTE" in msg,
           (msg.splitlines() or ["(saiu 0! portão cego)"])[0][:80])


def c4_material_real():
    print("\n4 · timeline exata em creators/creator-2/producao/peca-03 (material real)")
    # 🔒 `creators/` é NOSSO, não produto: procura-se subindo, e a ausência é
    # PULADO silencioso, nunca falha. Um cliente da ilha não tem esta pasta.
    raiz, d = SCRIPTS, None
    while raiz != os.path.dirname(raiz):
        cand = os.path.join(raiz, "creators", "creator-2", "producao", "peca-03")
        if os.path.isdir(cand):
            d = cand
            break
        raiz = os.path.dirname(raiz)
    if d is None:
        print("  [PULADO] não há creators/creator-2/producao/peca-03 nesta árvore "
              "(material nosso, não produto)")
        return
    tl = edl_io.medir_timeline(d)
    varrido["segmentos de material real medidos"] = len(tl["segments"])
    fps = tl["video"]["fps"]
    soma = sum(s["frames"] for s in tl["segments"])
    ok("total_frames == Σ frames", tl["total_frames"] == soma,
       "%d == %d" % (tl["total_frames"], soma))
    ok("total_s == total_frames/fps (erro < 1e-6 s)",
       abs(tl["total_s"] - tl["total_frames"] / fps) < 1e-6,
       "erro %.2e s" % abs(tl["total_s"] - tl["total_frames"] / fps))
    ok("total_s = 66,2333 ± 0,001 s", abs(tl["total_s"] - 66.2333) < 0.001,
       "%.6f s (a soma nominal da EDL dá 65,880 s)" % tl["total_s"])
    wav = os.path.join(d, "audio-exato.wav")
    if os.path.exists(wav):
        n = int(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=duration_ts", "-of", "csv=p=0", wav],
            capture_output=True, text=True).stdout.strip().rstrip(","))
        ok("total_samples == amostras do audio-exato.wav (diferença 0)",
           tl["total_samples"] == n,
           "%d vs %d (diferença %d)" % (tl["total_samples"], n,
                                        tl["total_samples"] - n))
    mp4 = os.path.join(d, "v1-montado.mp4")
    if os.path.exists(mp4):
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout)
        ok("|render − total_s| ≤ 2 frames", abs(dur - tl["total_s"]) <= 2.0 / fps,
           "%.1f ms (limite %.1f ms)" % (abs(dur - tl["total_s"]) * 1000,
                                         2000.0 / fps))
    # 🦷 DENTES: o órfão tem que ser RECUSADO, não medido.
    orf = os.path.join(raiz, "creators", "creator-2", "producao", "ovo-de-pascoa")
    if os.path.isdir(orf):
        msg = morre(edl_io.medir_timeline, orf)
        ok("recusa produção com segmento órfão (ovo-de-pascoa: 22 segs / 21 EDL)",
           "ÓRFÃO" in msg, (msg.splitlines() or ["(mediu! portão cego)"])[0][:88])


def c6_staleness(d):
    print("\n6 · staleness — a timeline não sobrevive a uma mudança de corte")
    r = roda(["bash", os.path.join(SCRIPTS, "montar.sh"), d])
    if not ok("montar.sh roda sobre o fixture", r.returncode == 0,
              "exit %d" % r.returncode):
        return
    env = edl_io.carregar(d)
    ok("timeline_real gravada inline (EDL é v2)", "timeline_real" in env,
       "total_frames=%s" % env.get("timeline_real", {}).get("total_frames"))
    tl = edl_io.timeline(d)
    varrido["fronteiras conferidas"] = len(edl_io.fronteiras(tl))
    nominal = sum(s["end"] - s["start"] for s in env["segments"])
    print("     Σ(end−start) = %.4f s · Σ frames/fps = %.4f s · deriva %.1f ms"
          % (nominal, tl["total_s"], (tl["total_s"] - nominal) * 1000))
    # 🦷 DENTES 1: mexer num `end` tem que abortar a leitura da timeline
    env2 = json.loads(json.dumps(env))
    env2["segments"][0]["end"] = round(env2["segments"][0]["end"] + 0.001, 4)
    with open(os.path.join(d, "edl.json"), "w") as fh:
        json.dump(env2, fh, indent=1, ensure_ascii=False)
    msg = morre(edl_io.timeline, d)
    ok("EDL alterada depois do render → timeline() aborta citando edl_fingerprint",
       "edl_fingerprint" in msg,
       (msg.splitlines() or ["(leu! portão cego)"])[0][:88])
    ok("e aborta mesmo com exigir=False (velha nunca é tolerada)",
       "edl_fingerprint" in morre(edl_io.timeline, d, exigir=False), "idem")
    # 🦷 DENTES 2: rodar bordas.py deixa a chave AUSENTE, não desatualizada
    with open(os.path.join(d, "edl.json"), "w") as fh:
        json.dump(env, fh, indent=1, ensure_ascii=False)
    r = roda([sys.executable, os.path.join(SCRIPTS, "bordas.py"), d])
    depois = edl_io.carregar(d)
    ok("bordas.py remove timeline_real (ausente, não velha)",
       r.returncode == 0 and "timeline_real" not in depois,
       "chaves: %s" % ", ".join(sorted(depois)))
    ok("e timeline(exigir=False) devolve None sem morrer",
       edl_io.timeline(d, exigir=False) is None, "None")


def c7_v1_intocado(d):
    print("\n7 · EDL v1 sobrevive intocada (sidecar, não conversão)")
    dd = d + "-v1"
    shutil.rmtree(dd, ignore_errors=True)
    shutil.copytree(d, dd)
    segs = edl_io.segmentos(dd)
    with open(os.path.join(dd, "edl.json"), "w") as fh:      # volta pra array nu
        json.dump(segs, fh, indent=1, ensure_ascii=False)
    antes = md5(os.path.join(dd, "edl.json"))
    for f in ("audio-exato.wav", "v1-montado.mp4"):
        p = os.path.join(dd, f)
        if os.path.exists(p):
            os.remove(p)
    r = roda(["bash", os.path.join(SCRIPTS, "montar.sh"), dd])
    ok("montar.sh roda sobre EDL v1 (array nu)", r.returncode == 0,
       "exit %d" % r.returncode)
    ok("md5 do edl.json inalterado (v1 NÃO é promovido em silêncio)",
       md5(os.path.join(dd, "edl.json")) == antes, antes[:12])
    side = os.path.join(dd, edl_io.SIDECAR)
    ok("timeline foi para o sidecar %s" % edl_io.SIDECAR, os.path.exists(side),
       "existe" if os.path.exists(side) else "AUSENTE")
    if os.path.exists(side):
        ok("timeline(dir) lê o sidecar e confere o fingerprint",
           edl_io.timeline(dd) is not None, "lido e conferido")
        r = roda([sys.executable, os.path.join(SCRIPTS, "edl_io.py"),
                  "--migrar", dd])
        env = edl_io.carregar(dd)
        ok("--migrar consolida o sidecar no envelope e deixa backup",
           r.returncode == 0 and "timeline_real" in env
           and os.path.exists(os.path.join(dd, "edl.v1.bak.json")),
           "schema=%s, backup=%s" % (env.get("schema"),
                                     os.path.exists(os.path.join(dd, "edl.v1.bak.json"))))


def main():
    rapido = "--rapido" in sys.argv
    base = tempfile.mkdtemp(prefix="edlv2-")
    d = fixture(os.path.join(base, "prod"))
    print("fixture sintético em %s (8 s, 270x480@30, 3 janelas)" % d)
    try:
        c1_c2_passthrough(d)
        c3_ida_e_volta(base)
        c_ordenacao(base)
        c_invariantes(base)
        c4_material_real()
        if rapido:
            print("\n[--rapido] 6 e 7 pulados (chamam montar.sh)")
        else:
            c6_staleness(d)
            c7_v1_intocado(d)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n── o que este teste varreu ──")
    for k, v in varrido.items():
        print("   %-42s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU: " + ", ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
