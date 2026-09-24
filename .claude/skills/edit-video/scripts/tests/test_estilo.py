#!/usr/bin/env python3
"""Bateria da SPEC-24 — os 9 [gate] da §7, com o número na saída.

    python3 tests/test_estilo.py            # tudo
    python3 tests/test_estilo.py 1 4 7      # só esses critérios

🔴 REGRA DESTA BATERIA: nenhum teste toca a biblioteca real. Tudo roda em
`$BENCH_ESTILOS_DIR` dentro de um tmpdir, com `BENCH_PERFIL_SEM_REMOTION=1` (o
`src/data/perfil.json` do Remotion é GLOBAL e compartilhado — a SPEC-15 viu esse
arquivo mudar 3× durante a execução dela por ação de vizinho).

🔴 E: todo portão verde imprime QUANTO varreu. Um verificador que varre 0 e sai 0
é indistinguível de um quebrado.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
FIX = os.path.join(AQUI, "fixtures-estilo")
ESTILO_PY = os.path.join(SCRIPTS, "estilo.py")

os.environ["BENCH_PERFIL_SEM_REMOTION"] = "1"
os.environ["BENCH_CATALOGO"] = os.path.join(FIX, "catalogo.json")


def _mod(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


FALHAS = []
OKS = [0]


def ok(cond, msg, medido=""):
    if cond:
        OKS[0] += 1
        print("  ok   %s %s" % (msg, medido))
    else:
        FALHAS.append("%s %s" % (msg, medido))
        print("  FALHA %s %s" % (msg, medido))
    return cond


class Arena:
    """Um tmpdir com perfis próprios, biblioteca própria e produção descartável."""

    def __init__(self):
        self.raiz = tempfile.mkdtemp(prefix="spec24-")
        self.perfis = os.path.join(self.raiz, "perfis")
        shutil.copytree(os.path.join(os.path.dirname(SCRIPTS), "perfis"), self.perfis)
        shutil.copy(os.path.join(FIX, "perfis", "teste.json"), self.perfis)
        self.lib = os.path.join(self.raiz, "estilos")
        shutil.copytree(os.path.join(FIX, "estilos"), self.lib)
        self.prod = os.path.join(self.raiz, "prod")
        os.makedirs(self.prod)
        os.environ["BENCH_PERFIS_DIR"] = self.perfis
        os.environ["BENCH_ESTILOS_DIR"] = self.lib
        self.E = _mod("estilo_%d" % id(self), ESTILO_PY)
        self.P = self.E._perfil()

    def evento(self, nome, destino="aplicados"):
        d = os.path.join(self.prod, ".preview", destino)
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(FIX, "eventos", nome), d)

    def fim(self):
        shutil.rmtree(self.raiz, ignore_errors=True)


def folhas(d, ignorar_underscore=True):
    """As folhas contáveis de um objeto: `_procedencia`, `_producao` e `_origem`
    são metadados do resolvedor, não valores resolvidos."""
    P = {k: v for k, v in d.items() if not (ignorar_underscore and k.startswith("_"))}
    saida = {}
    def anda(x, pre=""):
        if isinstance(x, dict) and x:
            for k, v in x.items():
                anda(v, ("%s.%s" % (pre, k)) if pre else k)
        else:
            saida[pre] = x
    anda(P)
    return saida


# ══════════════════════════════════════════════ 1 · precedência determinística
def gate_1():
    print("\n[gate 1] Precedência determinística e auditável (≥12 casos, §8.2)")
    A = Arena()
    E, P = A.E, A.P
    casos = []

    # 1 · ritmo.pads.pre só na camada 1
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste")
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("1  ritmo.pads.pre [1]", p["ritmo"]["pads"]["pre"], 0.11,
                  r["_origem"]["ritmo.pads.pre"], "perfil:teste"))

    # 2 · camadas 1+3 → estilo
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("2  ritmo.pads.pre [1,3]", p["ritmo"]["pads"]["pre"], 0.03,
                  r["_origem"]["ritmo.pads.pre"], "estilo:teste/a@v001"))
    casos.append(("2b ritmo.gramatica_plano [1,3]", p["ritmo"]["gramatica_plano"],
                  "punch-pontual", r["_origem"]["ritmo.gramatica_plano"],
                  "estilo:teste/a@v001"))
    # 7 · picks.legenda só na camada 2 (o estilo `a` seta legenda, então uso `tema`)
    casos.append(("7  picks.tema [2]", r["picks"]["tema"], "tema-neutro",
                  r["_origem"]["picks.tema"], "catalogo:defaultDe[teste]"))
    # 8 · picks.legenda em 2+3 → estilo
    casos.append(("8  picks.legenda [2,3]", r["picks"]["legenda"],
                  "legenda-chapada", r["_origem"]["picks.legenda"],
                  "estilo:teste/a@v001"))
    # 9 · picks.gancho com null explícito → DESLIGADO (≠ default do catálogo)
    casos.append(("9  picks.gancho [2,3=null]", r["picks"]["gancho"], None,
                  r["_origem"]["picks.gancho"], "estilo:teste/a@v001"))

    # 3 · camadas 1+3+4 → ui
    A.evento("20260808T154119-estilo-1.json")
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("3  ritmo.gramatica_plano [1,3,4]", p["ritmo"]["gramatica_plano"],
                  "alternada", r["_origem"]["ritmo.gramatica_plano"],
                  "ui:.preview/aplicados/20260808T154119-estilo-1.json"))

    # 4 · camadas 1+3+4+5 no MESMO path → pedido
    # `ritmo.gramatica_plano` é o único caminho do escopo que as 4 camadas sabem
    # escrever de verdade: perfil (`fixa`), estilo (`punch-pontual`), UI (o campo
    # `gramatica_plano` do benchmark.edit-estilo/v1) e pedido. Um caso "de 4
    # camadas" em que só duas escrevem o path não mede precedência nenhuma.
    base = json.load(open(os.path.join(A.prod, "perfil.json")))
    ok(base["ritmo"]["gramatica_plano"] == "alternada",
       "  (pré-condição do caso 4: camadas 1,3,4 já escreveram o path)",
       "1=fixa 3=punch-pontual 4=%r" % base["ritmo"]["gramatica_plano"])
    ops, _rec = E.compilar_pedido("deixa o plano fixo", base)
    ped = os.path.join(A.raiz, "pedido.json")
    json.dump({"contrato": E.CONTRATO_PEDIDO, "compilado_em": "2026-08-08T00:00:00-03:00",
               "texto": "deixa o plano fixo", "operacoes": ops, "recusas": []},
              open(ped, "w"))
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a",
                           pedido_compilado=ped)
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("4  ritmo.gramatica_plano [1,3,4,5]", p["ritmo"]["gramatica_plano"],
                  "fixa", r["_origem"]["ritmo.gramatica_plano"].split(" →")[0],
                  'pedido:"deixa o plano fixo"'))

    # 11 · audio.loudness.I por pedido, e o _origem cita o TEXTO
    ops, _rec = E.compilar_pedido("deixa mais alto pro anúncio", base)
    json.dump({"contrato": E.CONTRATO_PEDIDO, "compilado_em": "2026-08-08T00:00:00-03:00",
               "texto": "deixa mais alto pro anúncio", "operacoes": ops, "recusas": []},
              open(ped, "w"))
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a",
                           pedido_compilado=ped)
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("11 audio.loudness.I [1,5]", p["audio"]["loudness"]["I"], -12.0,
                  "deixa mais alto" in r["_origem"]["audio.loudness.I"], True))

    # 5 e 6 · herança de um nível
    shutil.rmtree(os.path.join(A.prod, ".preview"))
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/b")
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    casos.append(("5  ritmo.pads.pre [1,3-pai]", p["ritmo"]["pads"]["pre"], 0.03,
                  r["_origem"]["ritmo.pads.pre"], "estilo:teste/b@v001"))
    casos.append(("6  cor.grade [1,3-pai+filho]", p["cor"]["grade"],
                  "eq=saturation=1.40", r["_origem"]["cor.grade"],
                  "estilo:teste/b@v001"))

    # 10 · camada 3 tentando escrever video.fps → ERRO
    erro10 = ""
    try:
        E.resolver(A.prod, "teste", usuario="teste", ref="teste/formato")
    except Exception as ex:
        erro10 = str(ex)
    casos.append(("10 video.fps [1,3 tentando]", "video.fps" in erro10, True,
                  "perfil" in erro10 and "--set video.fps=" in erro10, True))

    # 12 · camada 4 tentando escrever legenda.fonte_palavras → ERRO
    erro12 = ""
    try:
        P.resolver_completo(
            A.prod, "teste",
            camadas=[("ui:x.json", {"legenda": {"fonte_palavras": "transcript-montado"}})],
            escopo_camadas=E.escopo_para_perfil())
    except Exception as ex:
        erro12 = str(ex)
    casos.append(("12 legenda.fonte_palavras [1,4]", "legenda.fonte_palavras" in erro12,
                  True, "--set legenda.fonte_palavras=" in erro12, True))

    print("  %d casos na bateria" % len(casos))
    acertos_v = acertos_o = 0
    for nome, valor, esperado, origem, origem_esp in casos:
        v_ok = valor == esperado
        o_ok = origem == origem_esp
        acertos_v += v_ok
        acertos_o += o_ok
        marca = "ok  " if (v_ok and o_ok) else "FALHA"
        print("    %s %-34s valor=%-22r origem=%r" % (marca, nome, valor, origem))
        if not v_ok:
            print("          esperava valor %r" % (esperado,))
        if not o_ok:
            print("          esperava origem %r" % (origem_esp,))
    ok(acertos_v == len(casos), "valor resolvido = camada mais alta",
       "%d/%d" % (acertos_v, len(casos)))
    ok(acertos_o == len(casos), "_origem nomeia essa camada",
       "%d/%d" % (acertos_o, len(casos)))

    # censo de folhas: perfil.json + estilo-resolvido.json vs _origem
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    p = json.load(open(os.path.join(A.prod, "perfil.json")))
    fp = folhas(p)
    fr = folhas({k: r[k] for k in ("picks", "grafismo", "parametros")})
    esperadas = set(fp) | {"picks." + k.split(".", 1)[1] if False else k for k in fr}
    origem = r["_origem"]
    faltando = sorted(esperadas - set(origem))
    ok(not faltando, "toda folha tem entrada em _origem",
       "folhas=%d origem=%d diferença=%d %s"
       % (len(esperadas), len(origem), len(faltando), faltando[:5]))

    # 🔴 controle negativo: um _origem incompleto TEM que reprovar o censo
    origem_furado = dict(origem)
    vitima = sorted(fp)[0]
    del origem_furado[vitima]
    pega = bool(esperadas - set(origem_furado))
    ok(pega, "o censo acusa um _origem com uma folha a menos (controle negativo)",
       "removi %r → acusou=%s" % (vitima, pega))
    A.fim()


# ══════════════════════════════════════════════ 2 · estilo não escreve formato
def gate_2():
    print("\n[gate 2] Estilo não escreve formato")
    A = Arena()
    E = A.E
    alvos = [("video.fps", 25), ("audio.canais", 2), ("zonas_ui.topo_pct", 0.2),
             ("legenda.fonte_palavras", "transcript-montado")]
    rejeitados = 0
    for caminho, valor in alvos:
        e = json.load(open(os.path.join(A.lib, "teste", "a", "versoes", "v001.json")))
        e["perfil_overrides"] = {}
        E._pôr(e["perfil_overrides"], caminho, valor)
        arq = os.path.join(A.raiz, "x.json")
        json.dump(e, open(arq, "w"))
        r = subprocess.run([sys.executable, ESTILO_PY, "validar", arq],
                           capture_output=True, text=True, env=os.environ)
        msg = r.stderr
        bom = (r.returncode == 1 and caminho in msg and "perfil" in msg.lower()
               and ("--set %s=" % caminho) in msg)
        rejeitados += bom
        print("    %s %-28s exit=%d  path✓=%s perfil✓=%s comando✓=%s"
              % ("ok  " if bom else "FALHA", caminho, r.returncode, caminho in msg,
                 "perfil" in msg.lower(), ("--set %s=" % caminho) in msg))
    ok(rejeitados == 4, "estilo escrevendo formato é recusado", "%d/4" % rejeitados)
    # controle positivo: um path DENTRO do escopo passa
    e = json.load(open(os.path.join(A.lib, "teste", "a", "versoes", "v001.json")))
    arq = os.path.join(A.raiz, "y.json")
    json.dump(e, open(arq, "w"))
    r = subprocess.run([sys.executable, ESTILO_PY, "validar", arq],
                       capture_output=True, text=True, env=os.environ)
    ok(r.returncode == 0, "controle positivo: estilo legítimo valida",
       "exit=%d %s" % (r.returncode, r.stdout.strip() or r.stderr.strip()[:80]))
    A.fim()


# ═══════════════════════════════════════ 3 · reprodutibilidade entre versões
def gate_3():
    print("\n[gate 3] Reprodutibilidade através de versões (--como-gravado)")
    import hashlib
    A = Arena()
    E = A.E

    def md5_sem_proc(d):
        p = json.load(open(os.path.join(d, "perfil.json")))
        p.pop("_procedencia", None)
        p.pop("_producao", None)
        return hashlib.md5(json.dumps(p, sort_keys=True, ensure_ascii=False)
                           .encode()).hexdigest()

    E.resolver(A.prod, "teste", usuario="teste", ref="teste/a@v001")
    md5_v001 = md5_sem_proc(A.prod)

    # duas promoções à mão (o caminho de promoção tem gate próprio, o 4/5/6)
    for nova, mud in (("v002", ("legenda.y_pct", 0.79)), ("v003", ("ritmo.cap", 0.30))):
        atual = E.carregar_estilo("teste", "a")
        atual.pop("_arquivo", None)
        novo = json.loads(json.dumps(atual))
        novo["versao"] = nova
        E._pôr(novo["perfil_overrides"], mud[0], mud[1])
        novo["historico"] = {"criado_em": atual["historico"]["criado_em"],
                             "derivado_de": atual["versao"], "confirmado_por": "teste",
                             "mudou": [{"path": "perfil_overrides." + mud[0], "de": None,
                                        "para": mud[1], "motivo": "fixture do gate 3",
                                        "sinais": []}]}
        E._gravar(E.caminho_versao("teste", "a", nova), novo)
        E._gravar(os.path.join(E.dir_do_estilo("teste", "a"), "estilo.json"),
                  E._ponteiro(novo))
    ok(E.head("teste", "a") == "v003", "HEAD andou para v003", E.head("teste", "a"))

    E.resolver(A.prod, "teste", usuario="teste", como_gravado=True)
    md5_gravado = md5_sem_proc(A.prod)
    ok(md5_gravado == md5_v001, "--como-gravado reproduz o perfil de @v001",
       "%s vs %s" % (md5_v001[:10], md5_gravado[:10]))

    # controle negativo: sem --como-gravado o md5 TEM que mudar
    E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    ok(md5_sem_proc(A.prod) != md5_v001, "sem --como-gravado o perfil muda (controle)",
       md5_sem_proc(A.prod)[:10])

    # o stderr lista EXATAMENTE os paths que diferem entre v001 e v003
    E.resolver(A.prod, "teste", usuario="teste", ref="teste/a@v001")
    r = subprocess.run([sys.executable, ESTILO_PY, "resolver", A.prod, "--perfil", "teste",
                        "--usuario", "teste", "--estilo", "teste/a"],
                       capture_output=True, text=True, env=os.environ)
    linhas = [l.strip() for l in r.stderr.splitlines() if l.strip().startswith(
        ("perfil_overrides.", "picks.", "grafismo.", "parametros."))]
    paths = sorted(l.split(":")[0] for l in linhas)
    esperado = ["perfil_overrides.legenda.y_pct", "perfil_overrides.ritmo.cap"]
    ok(paths == esperado, "o stderr lista exatamente os paths que diferem",
       "%s (esperado %s)" % (paths, esperado))
    A.fim()


# ═════════════════════════════════════════ 4 · guardas de sobreajuste, com número
def _sinal(prod, para, quando, direcao="+", path="legenda.y_pct", de=0.755):
    return {"contrato": "benchmark.estilo-sinal/v1", "observado_em": quando,
            "producao": prod, "estilo": "teste/a@v001", "origem": "ui",
            "evento": "%s-ev.json" % prod, "path": path, "de": de, "para": para,
            "direcao": direcao, "classe": "candidato-a-estilo"}


def gate_4():
    print("\n[gate 4] Guardas de sobreajuste, com número (5 cenários)")
    A = Arena()
    E = A.E
    S = os.path.join(A.lib, "teste", "a", "sinais.jsonl")

    def escrever(sinais):
        with open(S, "w", encoding="utf-8") as fh:
            for s in sinais:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")

    # (a) SPEC-50 — 3 correções na MESMA produção AGORA PROPÕEM (min_producoes=1).
    # O usuário é um só: três vezes a mesma correção é preferência declarada, não
    # ruído de uma peça. O que continua barrando é o contra-sinal, em (c) e (e).
    escrever([_sinal("prod/x", 0.79, "2026-08-0%dT10:00:00-03:00" % i) for i in (1, 2, 3)])
    props, texto = E.propor("teste/a")
    ok(len(props) == 1 and props[0]["n_producoes"] == 1,
       "(a) SPEC-50: 1 produção com 3 correções na mesma direção PROPÕE",
       "propostas=%d · n_producoes=%s" % (len(props),
                                          props[0]["n_producoes"] if props else "—"))

    # (b) 3 produções distintas → propõe 1 path
    escrever([_sinal("prod/%s" % p, 0.79, "2026-08-0%dT10:00:00-03:00" % (i + 1))
              for i, p in enumerate("xyz")])
    props, texto = E.propor("teste/a")
    ok(len(props) == 1 and props[0]["path"] == "legenda.y_pct",
       "(b) 3 produções distintas propõem 1 path",
       "propostas=%s" % [p["path"] for p in props])

    # (c) 3 a favor + 1 contra na produção MAIS RECENTE → não propõe
    escrever([_sinal("prod/%s" % p, 0.79, "2026-08-0%dT10:00:00-03:00" % (i + 1))
              for i, p in enumerate("xyz")] +
             [_sinal("prod/w", 0.72, "2026-08-09T10:00:00-03:00", "-")])
    props, texto = E.propor("teste/a")
    ok(not props and "decisão por peça" in texto, "(c) contra-sinal recente cancela",
       "propostas=%d · 'decisão por peça'=%s" % (len(props), "decisão por peça" in texto))

    # (d) 4 a favor, 2 fora da janela de 12 → só os 2 de dentro contam
    antigos = [_sinal("prod/velho%d" % i, 0.79, "2026-03-0%dT10:00:00-03:00" % (i + 1))
               for i in range(2)]
    # o enchimento é classe `peca`: entra na CONTAGEM DE PRODUÇÕES (que é o que
    # empurra os dois antigos para fora da janela) sem ser candidato a nada.
    meio = []
    for i in range(12):
        s = _sinal("prod/enche%d" % i, 0.60, "2026-05-%02dT10:00:00-03:00" % (i + 1),
                   "-", path="(timeline)", de=None)
        s["classe"] = "peca"
        meio.append(s)
    recentes = [_sinal("prod/novo%d" % i, 0.79, "2026-08-0%dT10:00:00-03:00" % (i + 1))
                for i in range(2)]
    escrever(antigos + meio + recentes)
    props, texto = E.propor("teste/a")
    ok(len(props) == 1 and props[0]["n_producoes"] == 2
       and props[0]["fora_da_janela"] == 2,
       "(d) a janela de 12 continua descartando os 2 antigos (propõe com 2, não 4)",
       "propostas=%s · n_producoes=%s · fora_da_janela=%s"
       % ([p["path"] for p in props],
          props[0]["n_producoes"] if props else "—",
          props[0]["fora_da_janela"] if props else "—"))

    # (e) 🦷 SPEC-50 — O CONTROLE DO CORTE. Baixar min_producoes para 1 não pode
    # abrir a porta para promover um parâmetro que a própria pessoa empurrou para
    # os dois lados NA MESMA PEÇA. É a guarda que sobrou, e ela tem que morder.
    escrever([_sinal("prod/x", 0.79, "2026-08-01T10:00:00-03:00"),
              _sinal("prod/x", 0.72, "2026-08-01T11:00:00-03:00", "-")])
    props, texto = E.propor("teste/a")
    ok(not props and "decisão por peça" in texto,
       "(e) contra-sinal na MESMA produção continua recusando, com min_producoes=1",
       "propostas=%d · 'decisão por peça'=%s" % (len(props),
                                                 "decisão por peça" in texto))
    A.fim()


# ══════════════════════════════════ 5 e 6 · nada sem confirmação; histórico vivo
def _md5_arvore(raiz):
    import hashlib
    out = {}
    for d, _sub, arqs in os.walk(raiz):
        for a in sorted(arqs):
            p = os.path.join(d, a)
            out[os.path.relpath(p, raiz)] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return out


def gate_5():
    print("\n[gate 5] Nada é promovido sem confirmação")
    A = Arena()
    E = A.E
    S = os.path.join(A.lib, "teste", "a", "sinais.jsonl")
    with open(S, "w", encoding="utf-8") as fh:
        for i, p in enumerate("xyz"):
            fh.write(json.dumps(_sinal("prod/%s" % p, 0.79,
                                       "2026-08-0%dT10:00:00-03:00" % (i + 1))) + "\n")
    antes = _md5_arvore(A.lib)
    props, _t = E.propor("teste/a")
    ok(len(props) == 1, "há proposta suficiente para promover (o teste tem dentes)",
       "%d proposta(s)" % len(props))
    depois = _md5_arvore(A.lib)
    ok(antes == depois, "`propor` não escreveu um byte",
       "%d arquivos, %d diferenças" % (len(antes),
                                       sum(1 for k in set(antes) | set(depois)
                                           if antes.get(k) != depois.get(k))))
    r = subprocess.run([sys.executable, ESTILO_PY, "promover", "teste/a",
                        "--usuario", "teste"], capture_output=True, text=True,
                       env=os.environ)
    ok(r.returncode == 2, "`promover` sem --confirmar sai 2", "exit=%d" % r.returncode)
    ok(_md5_arvore(A.lib) == antes, "e não escreveu um byte", "árvore intacta")
    A.fim()


def gate_6():
    print("\n[gate 6] Histórico não é apagado (3 promoções)")
    A = Arena()
    E = A.E
    S = os.path.join(A.lib, "teste", "a", "sinais.jsonl")
    paths = [("legenda.y_pct", 0.79), ("ritmo.cap", 0.30), ("ritmo.gap_min", 0.40)]
    antes_md5 = {}
    for n, (path, valor) in enumerate(paths):
        with open(S, "w", encoding="utf-8") as fh:
            for i, p in enumerate("xyz"):
                fh.write(json.dumps(
                    _sinal("prod/%s%d" % (p, n), valor,
                           "2026-08-%02dT10:00:00-03:00" % (i + 1 + n * 3),
                           path=path, de=0.0)) + "\n")
        E.promover("teste/a", confirmar=True)
        for v in E.versoes("teste", "a"):
            antes_md5.setdefault(v, _md5_arvore(os.path.join(
                E.dir_do_estilo("teste", "a"), "versoes")).get("%s.json" % v))
    vs = E.versoes("teste", "a")
    ok(vs == ["v001", "v002", "v003", "v004"], "versoes/ tem v001..v004", str(vs))
    agora = _md5_arvore(os.path.join(E.dir_do_estilo("teste", "a"), "versoes"))
    iguais = [v for v in ("v001", "v002", "v003")
              if antes_md5.get(v) == agora.get("%s.json" % v)]
    ok(len(iguais) == 3, "v001..v003 são byte a byte os mesmos de antes",
       "%d/3 %s" % (len(iguais), iguais))
    linhas = [l for l in open(os.path.join(E.dir_do_estilo("teste", "a"), "HISTORICO.md"),
                              encoding="utf-8") if l.startswith("- **v")]
    ok(len(linhas) == 4, "HISTORICO.md tem 4 linhas de versão", "%d" % len(linhas))
    hist = E.carregar_estilo("teste", "a")["historico"]
    ok(hist["mudou"] and hist["mudou"][0].get("motivo") and hist["mudou"][0].get("sinais"),
       "historico.mudou guarda a razão e os sinais, não só o valor",
       json.dumps(hist["mudou"][0], ensure_ascii=False)[:110])
    A.fim()


# ═══════════════════════════════════════════ 7 · isolamento e portabilidade
def gate_7():
    print("\n[gate 7] Isolamento e portabilidade")
    A = Arena()
    r = subprocess.run([sys.executable, ESTILO_PY, "mostrar", "teste/a",
                        "--usuario", "outro"], capture_output=True, text=True,
                       env=os.environ)
    ok(r.returncode == 1, "mostrar <outro-usuario>/x --usuario U sai 1",
       "exit=%d" % r.returncode)
    A.fim()

    varridos = []
    for d, _s, arqs in os.walk("estilos"):
        for a in arqs:
            varridos.append(os.path.join(d, a))
    def grep(padrao, arquivos, flags=""):
        if not arquivos:
            return []
        p = subprocess.run(["grep", "-rn" + flags, "-E", padrao] + arquivos,
                           capture_output=True, text=True)
        return [l for l in p.stdout.splitlines() if l.strip()]
    abs_ = grep("/Users/", varridos)
    ok(not abs_, "grep -rn '/Users/' estilos/ → 0", "%d linhas em %d arquivos varridos"
       % (len(abs_), len(varridos)))
    import glob
    versoes_ = glob.glob("estilos/*/*/versoes/*.json")
    acopl = grep("creators/|input/|data/", versoes_)
    ok(not acopl, "nenhuma versão referencia creators/ input/ data/",
       "%d linhas em %d versões" % (len(acopl), len(versoes_)))
    nomes = grep(r"\b(creator-1|creator-2|creator-3)\b",
                 ["estilos/_schema-estilo.json", "estilos/_escopo.json"], "i")
    ok(not nomes, "o schema e o escopo não citam usuário nosso", "%d linhas" % len(nomes))
    # Controle negativo: o grep TEM que achar quando existe.
    # ⚠️ O alvo é PLANTADO num arquivo temporário, não um caminho da nossa
    # instância. A versão anterior apontava para `estilos/<usuario>/_usuario.json`
    # e passou a falhar quando a limpeza de nomes reescreveu o literal do teste
    # sem renomear o diretório no disco — o grep varria um caminho inexistente e
    # devolvia 0 linhas, que é o mesmo resultado de um grep quebrado. Mecanismo
    # não pode depender de instância, nem em teste.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"usuario": "creator-1"}\n')
        plantado = fh.name
    try:
        achou = grep(r"\b(creator-1|creator-2|creator-3)\b", [plantado], "i")
        ok(bool(achou), "controle negativo: o mesmo grep acha o nome onde ele existe",
           "%d linhas" % len(achou))
    finally:
        os.unlink(plantado)


# ═══════════════════════════════════════════════ 8 · round-trip de export/import
def gate_8():
    print("\n[gate 8] Round-trip de export/import")
    import hashlib
    A = Arena()
    E = A.E

    def md5_sem_proc(d):
        p = json.load(open(os.path.join(d, "perfil.json")))
        p.pop("_procedencia", None)
        p.pop("_producao", None)
        return hashlib.md5(json.dumps(p, sort_keys=True, ensure_ascii=False)
                           .encode()).hexdigest()

    saida = os.path.join(A.raiz, "a.estilo.json")
    E.exportar("teste/a", saida)
    E.importar(saida, "demo")
    _c, _d, r1 = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    md1, picks1 = md5_sem_proc(A.prod), r1["picks"]
    _c, _d, r2 = E.resolver(A.prod, "teste", usuario="demo", ref="demo/a")
    md2, picks2 = md5_sem_proc(A.prod), r2["picks"]
    ok(md1 == md2, "o perfil resolvido é idêntico com os dois estilos",
       "%s vs %s" % (md1[:10], md2[:10]))
    ok(picks1 == picks2, "os picks são idênticos", json.dumps(picks1, ensure_ascii=False))

    # importar com slug ausente do catálogo → exit 0, estado incompleto
    pac = json.load(open(saida))
    pac["estilo"]["picks"]["legenda"] = "legenda-que-nao-existe"
    pac["requisitos"]["slugs_do_catalogo"].append(
        {"slug": "legenda-que-nao-existe", "grupo": "legenda"})
    faltoso = os.path.join(A.raiz, "faltoso.json")
    json.dump(pac, open(faltoso, "w"))
    r = subprocess.run([sys.executable, ESTILO_PY, "importar", faltoso,
                        "--usuario", "demo2"], capture_output=True, text=True,
                       env=os.environ)
    novo = json.load(open(os.path.join(A.lib, "demo2", "a", "versoes", "v001.json"))) \
        if r.returncode == 0 else {}
    ok(r.returncode == 0 and novo.get("estado") == "incompleto"
       and "legenda-que-nao-existe" in r.stderr,
       "slug ausente importa com estado incompleto e lista o slug",
       "exit=%d estado=%r slug-no-stderr=%s"
       % (r.returncode, novo.get("estado"), "legenda-que-nao-existe" in r.stderr))
    A.fim()


# ══════════════════════════════════════ 10 · procedência de terceiro travada
def gate_10():
    print("\n[gate 10] Procedência de terceiro travada")
    A = Arena()
    E = A.E
    e = json.load(open(os.path.join(A.lib, "teste", "a", "versoes", "v001.json")))
    e["procedencia"] = {"tipo": "modelado",
                        "fonte": {"handle": "@x", "url": None, "data": "2026-08-08",
                                  "ficha": "intelligence/edicao/nao-existe.md"},
                        "nota_de_uso": None}
    arq = os.path.join(A.raiz, "modelado.json")
    json.dump(e, open(arq, "w"))
    r = subprocess.run([sys.executable, ESTILO_PY, "validar", arq],
                       capture_output=True, text=True, env=os.environ)
    ok(r.returncode == 1 and "ficha" in r.stderr, "ficha inexistente reprova",
       "exit=%d" % r.returncode)

    # exportador rejeita ativo binário
    e2 = json.load(open(os.path.join(A.lib, "teste", "a", "versoes", "v001.json")))
    e2["perfil_overrides"]["cor"]["grade"] = "lut3d=meu.cube"
    E._gravar(E.caminho_versao("teste", "a", "v001"), e2)
    saida = os.path.join(A.raiz, "x.json")
    r2 = subprocess.run([sys.executable, ESTILO_PY, "exportar", "teste/a",
                         "--saida", saida], capture_output=True, text=True, env=os.environ)
    ok(r2.returncode == 1 and "cor.grade" in r2.stderr, "export rejeita .cube nomeando o campo",
       "exit=%d" % r2.returncode)
    ok(not os.path.exists(saida), "e não escreveu o arquivo de saída",
       "existe=%s" % os.path.exists(saida))

    # o export legítimo não carrega base64
    E._gravar(E.caminho_versao("teste", "a", "v001"),
              json.load(open(os.path.join(FIX, "estilos", "teste", "a", "versoes",
                                          "v001.json"))))
    E.exportar("teste/a", saida)
    n = subprocess.run(["grep", "-c", "base64", saida], capture_output=True, text=True)
    ok(n.stdout.strip() in ("0", ""), "grep -c base64 no export → 0", n.stdout.strip())
    A.fim()


# ═══════════════════════════════ 9-perfil · o caminho sem estilo não muda um byte
def gate_perfil():
    print("\n[extra] perfil.py sem --estilo continua byte a byte o de antes")
    import hashlib
    A = Arena()
    P = A.P
    base = subprocess.run(["git", "-C", "ilha", "show",
                           "HEAD:skills/edit-video/scripts/perfil.py"],
                          capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(
                              os.path.dirname(os.path.dirname(SCRIPTS)))))
    if base.returncode != 0:
        print("  (pulado: não consegui obter o perfil.py do HEAD)")
        A.fim()
        return
    velho = os.path.join(A.raiz, "perfil-baseline.py")
    open(velho, "w").write(base.stdout)

    def md5(d):
        p = json.load(open(os.path.join(d, "perfil.json")))
        p.get("_procedencia", {}).pop("resolvido_em", None)
        return hashlib.md5(json.dumps(p, sort_keys=True, ensure_ascii=False)
                           .encode()).hexdigest()

    iguais = total = 0
    for nome in ("reels", "vsl", "longform", "screencast", "teste"):
        for creator in (None, "creator-2"):
            for script in (velho, os.path.join(SCRIPTS, "perfil.py")):
                d = os.path.join(A.raiz, "cmp-%s" % ("a" if script == velho else "b"))
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d)
                cmd = [sys.executable, script, "resolver", d, "--perfil", nome]
                if creator:
                    cmd += ["--creator", creator]
                subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
            total += 1
            iguais += md5(os.path.join(A.raiz, "cmp-a")) == md5(os.path.join(A.raiz, "cmp-b"))
    ok(iguais == total, "perfil.json idêntico ao do HEAD sem --estilo",
       "%d/%d combinações" % (iguais, total))
    A.fim()


# ═════════════════════ extra · o colhedor de sinais não pode sair verde e vazio
def gate_sinais():
    """🔴 REGRESSÃO de um defeito medido NA EXECUÇÃO desta spec.

    A §3.6 passo 2 manda comparar o evento da UI "contra o `estilo-resolvido.json`
    daquela produção". Feito ao pé da letra, isso dá SEMPRE zero: a camada 4 já
    está mergeada dentro dele. O colhedor rodava, dizia "1 evento lido", gravava
    NADA e saía 0 — sucesso silencioso. A comparação certa é contra a linha de
    base (camadas 1–3), que é o que `correcoes[]` guarda."""
    print("\n[extra] sinais: a correção é medida contra a linha de base (1–3)")
    A = Arena()
    E = A.E
    A.evento("20260808T154119-estilo-1.json")
    A.evento("20260808T161000-ajustes-1.json")
    _c, _d, r = E.resolver(A.prod, "teste", usuario="teste", ref="teste/a")
    corr = r.get("correcoes") or []
    ok(len(corr) >= 2, "o resolver mede as correções da camada 4",
       "%d: %s" % (len(corr), [c["path"] for c in corr]))
    caminho, novos = E.sinais(A.prod)
    cand = [s for s in novos if s["classe"] == "candidato-a-estilo"]
    peca = [s for s in novos if s["classe"] == "peca"]
    fora = [s for s in novos if s["classe"] == "fora-de-escopo"]
    ok(cand and peca and fora, "as 3 classes aparecem",
       "candidato=%d peca=%d fora-de-escopo=%d" % (len(cand), len(peca), len(fora)))
    ok(all(s["de"] != s["para"] for s in cand),
       "todo candidato tem de≠para (senão não é correção)",
       "%d candidatos" % len(cand))
    ok(any(s["path"] == "(timeline)" for s in peca),
       "a correção de timeline é classe `peca` e não conta para promoção",
       [s["path"] for s in peca])
    n1 = len(open(caminho, encoding="utf-8").read().splitlines())
    E.sinais(A.prod)
    n2 = len(open(caminho, encoding="utf-8").read().splitlines())
    ok(n1 == n2, "rodar `sinais` de novo não duplica", "%d → %d linhas" % (n1, n2))
    # SPEC-50 — 1 produção AGORA propõe (min_producoes=1), e o que se mede aqui
    # é o que continua NÃO entrando: `(timeline)` é classe `peca` e nenhuma
    # proposta pode nascer dela, por mais sinais que ela tenha.
    props, texto = E.propor("teste/a")
    paths = sorted(p["path"] for p in props)
    ok(props and "(timeline)" not in paths,
       "SPEC-50: 1 produção propõe, e `(timeline)` (classe `peca`) fica de fora",
       "propostas=%d · paths=%s" % (len(props), paths))
    A.fim()


GATES = {"1": gate_1, "2": gate_2, "3": gate_3, "4": gate_4, "5": gate_5,
         "6": gate_6, "7": gate_7, "8": gate_8, "10": gate_10, "p": gate_perfil,
         "s": gate_sinais}

if __name__ == "__main__":
    alvos = sys.argv[1:] or list(GATES)
    for a in alvos:
        GATES[a]()
    print("\n%d asserções ok, %d falha(s)" % (OKS[0], len(FALHAS)))
    for f in FALHAS:
        print("  FALHA: %s" % f)
    sys.exit(1 if FALHAS else 0)
