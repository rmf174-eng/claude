#!/usr/bin/env python3
"""Testes do `split-plano.py` (SPEC-28) — autocontidos, sem bruto e sem Vision.

    python3 .claude/skills/edit-video/scripts/tests/test_split_plano.py [--rapido]

`--rapido` pula os casos que rodam ffmpeg (produção sintética de 6 s em
240x426) e roda só a aritmética do solver.

🔴 POR QUE ELE PLANTA DEFEITO EM VEZ DE SÓ AFIRMAR O CASO BOM
Um portão que varre 0 e sai 0 é indistinguível de um quebrado. Aqui cada regra é
testada nos dois sentidos:

  * o solver acerta os 5 casos MEDIDOS em produção real (§3.3 da spec) **e** a
    régua de alpha acusa o comportamento ANTIGO (S = 25 % da altura) como
    defeito — senão o critério "zero b-roll sobre a cabeça" seria verde por não
    ter nada para achar;
  * `alpha_broll` é conferida nos três pontos que a definem (1 no opaco, 0,5 no
    meio, 0 no fim): uma rampa que devolvesse 0 em todo lugar passaria em todo
    teste de "não tem b-roll sobre a cabeça";
  * o teto de escala, a perda de base, o queixo, a rejeição por segmento e a
    janela fora de fronteira são exercitados pelo CAMINHO REAL (a medição
    zerada, não uma flag que pula o cálculo).
"""
import json
import os
import subprocess
import sys
import importlib.util

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
RAPIDO = "--rapido" in sys.argv

_spec = importlib.util.spec_from_file_location(
    "split_plano", os.path.join(SCRIPTS, "split-plano.py"))
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

falhas = []
n = [0]


def ok(cond, msg):
    n[0] += 1
    print(("  ok    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def perto(a, b, tol):
    return a is not None and abs(a - b) <= tol


# ── a peça do estudo, com os números que a spec mediu ────────────────────────
# 1920 aqui é DADO DE TESTE (a altura da peça medida), não valor de formato num
# script: é exatamente o número que o perfil entrega ao solver.
ALT = 1920
SPLIT = dict(sp.FALLBACK_SPLIT)
SPLIT.update({"folga_topo_pct": 0.036})
GEO = sp.geometria(ALT, SPLIT)


def caso(c, q=None, split=None, alt=ALT, escala_max=None):
    s = split or SPLIT
    return sp.resolver_par(c, q, alt, sp.geometria(alt, s), s, escala_max)


print("\n1) a rampa de alpha existe e tem os três pontos que a definem")
ok(perto(sp.alpha_broll(GEO["y_op"], GEO["y_op"], GEO["y_fim"]), 1.0, 1e-9),
   "alpha = 1,000 em y_op (%.1f px) — o b-roll é opaco ali" % GEO["y_op"])
ok(perto(sp.alpha_broll((GEO["y_op"] + GEO["y_fim"]) / 2,
                        GEO["y_op"], GEO["y_fim"]), 0.5, 1e-9),
   "alpha = 0,500 no meio da rampa (smoothstep é simétrica)")
ok(perto(sp.alpha_broll(GEO["y_fim"], GEO["y_op"], GEO["y_fim"]), 0.0, 1e-9),
   "alpha = 0,000 em y_fim (%.1f px)" % GEO["y_fim"])
ok(sp.alpha_broll(GEO["y_op"] + 1, GEO["y_op"], GEO["y_fim"]) < 1.0,
   "a rampa DESCE (não é degrau nem constante)")

print("\n2) O DEFEITO: a constante de hoje (S = 25 % da altura) põe b-roll sobre a cabeça")
# É o controle negativo do critério 2 da spec. Sem ele, "alpha ≤ 0,5 %" seria
# verde por construção e o teste não provaria nada.
for nome, c, esperado_min in (("ref-D seg2", 433, 0.005), ("ref-D seg5", 378, 0.005),
                              ("mesa", 399, 0.005)):
    a_hoje = sp.alpha_broll(c + 0.25 * ALT, GEO["y_op"], GEO["y_fim"])
    ok(a_hoje > esperado_min,
       "%s: com S=25%%(=%d px) o topo da cabeça cai em y=%.0f e leva %.1f%% de "
       "b-roll — a régua ACUSA o defeito" % (nome, 0.25 * ALT, c + 0.25 * ALT,
                                             a_hoje * 100))

print("\n3) os 5 casos MEDIDOS do §3.3 (H=1920, opaco 0,34, fim 0,51, folga 0,036)")
tabela = [
    ("ref-D seg2", 433, 831, 615, 1.000),
    ("ref-D seg3", 431, 831, 617, 1.000),
    ("ref-D seg4", 381, 812, 653, 1.038),
    ("ref-D seg5", 378, 812, 653, 1.046),
    ("mesa janela", 399, 830, 649, 1.000),
]
for nome, c, q, s_esp, z_esp in tabela:
    r = caso(c, q)
    ok(perto(round(r["deslocamento_px"]), s_esp, 1),
       "%s: S = %.0f px (esperado %d, %.1f%% da altura)"
       % (nome, r["deslocamento_px"], s_esp, r["deslocamento_px"] / ALT * 100))
    ok(perto(r["escala"], z_esp, 0.002),
       "%s: z = %.3f (esperado %.3f)" % (nome, r["escala"], z_esp))
    ok(perto(r["alpha_broll_previsto"], 0.0, 1e-9),
       "%s: alpha de b-roll sobre a cabeça = %.4f%% (era %.1f%% com a constante)"
       % (nome, r["alpha_broll_previsto"] * 100,
          sp.alpha_broll(c + 0.25 * ALT, GEO["y_op"], GEO["y_fim"]) * 100))

print("\n4) deslocamento_pct sai de 0,25 fixo e vira 0,32–0,34 MEDIDO")
pcts = [caso(c, q)["deslocamento_px"] / ALT for _, c, q, _, _ in tabela]
ok(all(0.32 <= p <= 0.34 for p in pcts),
   "os 5 casos ficam em [%.4f, %.4f] — nenhum é 0,2500" % (min(pcts), max(pcts)))
ok(max(caso(c, q)["escala"] for _, c, q, _, _ in tabela) <= 1.05,
   "escala máxima dos 5 casos = %.3f (teto do perfil 1,08)"
   % max(caso(c, q)["escala"] for _, c, q, _, _ in tabela))

print("\n5) cabeca-ja-baixa: se a cabeça já está abaixo do alvo, não se mexe em nada")
r = caso(1200, 1700)
ok(r["motivo"] == "cabeca-ja-baixa" and r["deslocamento_px"] == 0 and r["escala"] == 1.0,
   "c=1200 (> alvo %.0f): S=0, z=1, motivo %r" % (GEO["alvo"], r["motivo"]))

print("\n6) o teto de escala MORDE e é declarado (nunca min(z, teto) em silêncio)")
r = caso(378, 812, escala_max=1.00)
ok(r["guardas"]["escala"]["ok"] is False,
   "com --escala-max 1,00 o caso que pede 1,046 REPROVA o guarda 3")
ok(perto(r["escala"], 1.046, 0.002),
   "e o z devolvido continua sendo o MEDIDO (%.3f), não o teto — quem decide o "
   "que fazer é o chamador" % r["escala"])
r2 = caso(378, 812)
ok(r2["guardas"]["escala"]["ok"] is True,
   "com o teto do perfil (1,08) o mesmo caso passa (z=%.3f)" % r2["escala"])

print("\n7) o queixo não encosta no pé do quadro")
r = caso(433, 1800)          # queixo muito baixo: o guarda 4 tem que puxar S
ok(r["guardas"]["queixo"]["ok"] is True,
   "queixo 1800 px: saída em %.0f px, limite %.0f px"
   % (r["guardas"]["queixo"]["queixo_saida"], r["guardas"]["queixo"]["limite"]))
ok(r["deslocamento_px"] < caso(433, 831)["deslocamento_px"],
   "e o guarda REDUZIU S (%.0f contra %.0f com queixo normal) em vez de deixar "
   "o queixo sair" % (r["deslocamento_px"], caso(433, 831)["deslocamento_px"]))
ok(r["guardas"]["alvo"]["ok"] is False,
   "e o conflito com o guarda 2 é DECLARADO (alvo.ok = False), não escondido")
ok(caso(433, None)["guardas"]["queixo"]["ok"] is None,
   "sem medida de queixo o guarda 4 é NÃO VERIFICADO (None), nunca 'ok'")

print("\n8) a perda de base é medida e comparada com o teto do perfil")
r = caso(381, 812)
ok(perto(r["perda_base_pct"], 1 - (ALT - r["deslocamento_px"]) / (ALT * r["escala"]), 1e-9),
   "perda = 1 − (H − S)/(H·z) = %.4f" % r["perda_base_pct"])
ok(r["guardas"]["perda_base"]["ok"] is False,
   "seg4 (perda %.1f%%) estoura o teto de 36,0%% do perfil reels — e o guarda "
   "DIZ isso" % (r["perda_base_pct"] * 100))
ok(caso(433, 831)["guardas"]["perda_base"]["ok"] is True,
   "seg2 (perda %.1f%%) cabe" % (caso(433, 831)["perda_base_pct"] * 100))
novo = sp.fim_pct_que_cabe(381, ALT, SPLIT, 0.36)
ok(novo < SPLIT["fim_pct"],
   "a curva de troca existe: fim_pct %.3f → %.3f traria a perda para dentro do teto"
   % (SPLIT["fim_pct"], novo))

print("\n9) o solver não conhece formato: as mesmas frações em 16:9")
ALT169 = 1080
g = sp.geometria(ALT169, SPLIT)
ok(perto(g["y_op"], ALT169 * SPLIT["opaco_pct"], 1e-9)
   and perto(g["y_fim"], ALT169 * SPLIT["fim_pct"], 1e-9),
   "y_op=%.1f e y_fim=%.1f saem de 1080, não de 1920" % (g["y_op"], g["y_fim"]))
r = caso(int(433 * ALT169 / ALT), None, alt=ALT169)
ok(perto(r["deslocamento_px"] / ALT169, 0.3203, 0.002),
   "e a MESMA cabeça em fração da altura dá o mesmo deslocamento relativo "
   "(%.4f contra 0,3203 em 9:16)" % (r["deslocamento_px"] / ALT169))

print("\n10) perfil sem o bloco `split`: FALLBACK congelado, e ele AVISA em vez de fingir")
ok(sp.FALLBACK_SPLIT["opaco_pct"] == 0.34 and sp.FALLBACK_SPLIT["fim_pct"] == 0.51
   and sp.FALLBACK_SPLIT["curva"] == "smooth",
   "o fallback é o comportamento de hoje (34/51/smooth)")
ok(sp.FALLBACK_SPLIT["folga_topo_pct"] is None,
   "e `folga_topo_pct` é None — sem alvo declarado o planejador PARA")
ok(sp.geometria(ALT, sp.FALLBACK_SPLIT)["alvo"] is None,
   "geometria() devolve alvo=None com o fallback (não inventa 0)")

print("\n11) o percentil é o da cabeça MAIS ALTA (p5), não a mediana")
vals = [400, 410, 420, 430, 500]
ok(sp._percentil(vals, 5) < sp._percentil(vals, 50),
   "p5=%.1f < mediana=%.1f — quem manda é a cabeça que menos cabe"
   % (sp._percentil(vals, 5), sp._percentil(vals, 50)))
ok(perto(sp._percentil([10.0], 5), 10.0, 1e-9), "percentil de 1 amostra é ela mesma")

# ─────────────────────────────────────────────────── caminho completo, com CLI
if not RAPIDO:
    import shutil
    import tempfile

    print("\n12) produção sintética: rejeição, herança, exit 1 e encaixe no corte REAL")
    tmp = tempfile.mkdtemp(prefix="spec28-")
    seg_dur, n_segs = 2.0, 3
    try:
        os.makedirs(os.path.join(tmp, "segs"))
        for i in range(n_segs):
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc2=size=240x426:rate=30:duration=%g" % seg_dur,
                 "-f", "lavfi", "-i", "sine=frequency=220:duration=%g" % seg_dur,
                 "-shortest", "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", os.path.join(tmp, "segs", "seg%03d.mp4" % i)], check=True)
        with open(os.path.join(tmp, "concat.txt"), "w") as fh:
            for i in range(n_segs):
                fh.write("file 'segs/seg%03d.mp4'\n" % i)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat",
                        "-safe", "0", "-i", os.path.join(tmp, "concat.txt"),
                        "-c", "copy", os.path.join(tmp, "v1-montado.mp4")], check=True)
        with open(os.path.join(tmp, "edl.json"), "w") as fh:
            json.dump([{"src": "x.mp4", "start": i * 3.0, "end": i * 3.0 + seg_dur,
                        "beat": "b%d" % i, "zoom": 1.0} for i in range(n_segs)], fh)
        env = dict(os.environ, BENCH_PERFIL_SEM_REMOTION="1")
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "perfil.py"), "resolver",
                        tmp, "--perfil", "reels", "--set", "video.largura=240",
                        "--set", "video.altura=426"],
                       check=True, capture_output=True, env=env)

        def roda(*args):
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "split-plano.py"),
                                tmp] + list(args), capture_output=True, text=True, env=env)
            return r.returncode, r.stdout, r.stderr

        plano_p = os.path.join(tmp, "split-plano.json")

        # 12a — encaixe: a EDL soma 6,0 s de `end−start` E os segs somam 6,0 s,
        # então o que separa as duas fontes é a FRONTEIRA pedida fora do corte.
        rc, _, err = roda("--janela", "1.9", "4.1", "--cabeca-y", "100")
        pl = json.load(open(plano_p)) if rc == 0 else {}
        ok(rc == 0 and pl["janela"]["t0"] == 2.0 and pl["janela"]["t1"] == 4.0,
           "janela 1,9–4,1 encaixou em %s–%s (fronteiras reais dos segs/)"
           % (pl.get("janela", {}).get("t0"), pl.get("janela", {}).get("t1")))
        ok(pl.get("janela", {}).get("t0_pedido") == 1.9,
           "e o pedido original ficou gravado (t0_pedido=1,9)")
        ok("timeline_real" in str(pl.get("janela", {}).get("fonte_do_encaixe")),
           "fonte_do_encaixe = %r (nunca Σ(end−start))"
           % pl.get("janela", {}).get("fonte_do_encaixe"))

        # 12b — janela fora de qualquer fronteira: exit 1, e nada gravado
        os.remove(plano_p)
        rc, _, err = roda("--janela", "0.9", "4.0", "--cabeca-y", "100")
        ok(rc == 1 and "JANELA ERRADA" in err and not os.path.exists(plano_p),
           "janela 0,9 (0,9 s da fronteira mais próxima): exit %d, plano não escrito" % rc)

        # 12c — os 3 segmentos resolvem
        rc, _, err = roda("--janela", "0", "6", "--cabeca-y", "100",
                          "--cabeca-y", "95", "--cabeca-y", "110")
        pl = json.load(open(plano_p)) if rc == 0 else {"segmentos": []}
        ok(rc == 0 and len(pl["segmentos"]) == 3,
           "3 segmentos resolvidos, motivos %s"
           % [s["motivo"] for s in pl["segmentos"]])
        ok(all(perto(s["alpha_broll_previsto"], 0.0, 1e-6) for s in pl["segmentos"]),
           "alpha de b-roll previsto sobre a cabeça = 0,0000 nos 3")

        # 12d — DEFEITO PLANTADO: medição zerada num segmento
        rc, _, err = roda("--janela", "0", "6", "--cabeca-y", "100", "--cabeca-y", "95",
                          "--cabeca-y", "110", "--simular-falha-seg", "1")
        pl = json.load(open(plano_p)) if rc == 0 else {"segmentos": []}
        s1 = [s for s in pl["segmentos"] if s["i"] == 1]
        ok(rc == 0 and s1 and s1[0]["motivo"] == "herdado",
           "seg1 com medição zerada saiu com motivo %r"
           % (s1[0]["motivo"] if s1 else None))
        ok(s1 and s1[0]["samples_rejeitados"]
           and all("razao" in r for r in s1[0]["samples_rejeitados"]),
           "e com samples_rejeitados NOMEADOS: %s"
           % (s1[0]["samples_rejeitados"] if s1 else None))
        ok("seg1" in err and "herdou" in err,
           "e o stderr NOMEIA o segmento (a regra de SKILL.md:52)")

        # 12e — todos zerados: exit 1 e o plano some do disco
        antes = os.path.getmtime(plano_p)
        rc, _, err = roda("--janela", "0", "6", "--cabeca-y", "100",
                          "--simular-falha-seg", "todos")
        ok(rc == 1 and "NENHUM segmento resolveu" in err,
           "medição zerada em TODOS: exit %d" % rc)
        ok(os.path.getmtime(plano_p) == antes,
           "e o split-plano.json anterior NÃO foi tocado (nenhum (S,z) sem medição)")

        # 12f — teto de escala pela CLI
        rc, _, err = roda("--janela", "0", "6", "--cabeca-y", "60",
                          "--escala-max", "1.00")
        ok(rc == 1 and 'motivo: "teto"' in err,
           "cabeça alta com --escala-max 1,00: exit %d, motivo teto" % rc)
        ok("fim_pct" in err and "reenquadrar" in err,
           "e a mensagem traz as DUAS saídas reais (faixa mais fina / reenquadrar)")

        # 12g — perda de base acima do teto exige --forcar
        # cabeça alta força o ramo deslocamento+escala e estoura a perda
        rc, _, err_sem = roda("--janela", "0", "6", "--cabeca-y", "84")
        rc2, _, err_com = roda("--janela", "0", "6", "--cabeca-y", "84", "--forcar")
        ok(rc == 1 and "PERDA DE BASE" in err_sem,
           "perda acima do teto sem --forcar: exit %d (o script avisa, não decide)" % rc)
        ok(rc2 == 0 and "perda_base" in " ".join(json.load(open(plano_p))["avisos"]),
           "com --forcar o plano sai, e o aviso fica GRAVADO no artefato")

        # 12h — sem pessoa nenhuma, o medidor real REJEITA tudo (não devolve verde)
        rc, _, err = roda("--janela", "2", "4")
        ok(rc == 1 and ("NENHUM segmento resolveu" in err or "matte" in err),
           "testsrc2 (sem pessoa) pelo medidor de verdade: exit %d — um detector "
           "que não acha nada e devolve verde é o defeito nº 1" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    print("\n12) [pulado: --rapido]")

print("\n%d checagens, %d falha(s)" % (n[0], len(falhas)))
for f in falhas:
    print("  FALHOU: " + f)
sys.exit(1 if falhas else 0)
