#!/usr/bin/env python3
"""Teste da bateria de QC (SPEC-12) — adaptadores, classificação e orçamento.

    python3 .claude/skills/edit-video/scripts/tests/test_qc_bateria.py

RODA SEM FFMPEG E SEM REDE. Tudo aqui é função pura sobre string: as fixtures em
`fixtures/qc/` já são a saída dos QCs, capturada de uma produção sintética.

🔴 POR QUE ELE IMPRIME QUANTO VARREU E PLANTA DEFEITO DE PROPÓSITO
Um portão que varre 0 e sai 0 é indistinguível de um portão quebrado. Este repo já
entregou 6,25 s de vídeo errado com todos os QCs verdes, e já teve um QC que mediu
uma faixa vazia e imprimiu limpo. Então cada checagem aqui faz DUAS coisas: afirma
o caso bom com o número medido, e planta o defeito que o mecanismo TEM que acusar.

Nada aqui toca material de creator. As fixtures vêm de `testsrc2` 256x456 + fala
do TTS do sistema dizendo numerais, montada pelo `montar.sh` de verdade.
"""
import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(AQUI)
FX = os.path.join(AQUI, "fixtures", "qc")

_spec = importlib.util.spec_from_file_location("qc_mod", os.path.join(SCRIPTS, "qc.py"))
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)

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


def ler_fixture(nome):
    with open(os.path.join(FX, nome)) as fh:
        bruto = fh.read()
    if "\n--- stderr\n" in bruto:
        so, se = bruto.split("\n--- stderr\n", 1)
    else:
        so, se = bruto, ""
    return so.replace("--- stdout\n", "", 1), se


# ────────────────────────────────────────────────────────────────── 1. catálogo

def c1_catalogo():
    print("\n1 · o catálogo é dado válido, e o validador tem dentes")
    cat = qc.carregar_catalogo()
    conta("itens do catálogo", len(cat["itens"]))
    ok("bateria.json carrega e valida", len(cat["itens"]) >= 15,
       "%d itens, %d estágios" % (len(cat["itens"]), len(cat["estagios"])))
    ids = [i["id"] for i in cat["itens"]]
    ok("nenhum id duplicado", len(ids) == len(set(ids)))
    plano_visual = next((i for i in cat["itens"] if i["id"] == "plano-visual"), None)
    ok("entrega cobra o plano visual da Fase 2",
       plano_visual is not None
       and set(plano_visual["estagios"]) == {"compositado", "final"}
       and plano_visual["promove_falha"] == ["PLANO-VISUAL"],
       str(plano_visual))
    ok("todo adaptador citado existe",
       all(i["adaptador"] in qc.ADAPTADORES for i in cat["itens"]))
    ok("todo item declara nota_classe (a justificativa da classificação)",
       all(i.get("nota_classe") for i in cat["itens"]),
       "sem nota: %s" % [i["id"] for i in cat["itens"] if not i.get("nota_classe")])

    # 🦷 DENTES: catálogo com adaptador inexistente TEM que ser recusado.
    ruim = {"schema": qc.CONTRATO_CATALOGO, "estagios": cat["estagios"],
            "itens": [{"id": "x", "tipo": "detector", "estagios": ["montado"],
                       "adaptador": "nao_existe", "unidade": "linha"}]}
    try:
        qc.validar_catalogo(ruim)
        ok("recusa adaptador inexistente", False, "aceitou")
    except qc.ErroUso as e:
        ok("recusa adaptador inexistente", True, str(e)[:52])
    # 🦷 DENTES: tipo inválido
    ruim["itens"][0]["adaptador"] = "generico"
    ruim["itens"][0]["tipo"] = "talvez"
    try:
        qc.validar_catalogo(ruim)
        ok("recusa tipo inválido", False, "aceitou")
    except qc.ErroUso as e:
        ok("recusa tipo inválido", True, str(e)[:52])
    return cat


# ─────────────────────────────────────────────────── 2. adaptadores × fixtures

def c2_adaptadores(cat):
    print("\n2 · adaptadores contra as fixtures (o mesmo corpo do `qc.py --autoteste`)")
    with open(os.path.join(FX, "esperado.json")) as fh:
        esperado = json.load(fh)
    por_id = {i["id"]: i for i in cat["itens"]}
    for caso in esperado["casos"]:
        conta("fixtures conferidas")
        so, se = ler_fixture(caso["arquivo"])
        item = por_id[caso["item"]]
        res = qc.ADAPTADORES[item["adaptador"]](so, se, caso.get("exit", 0),
                                                caso.get("ctx", {}))
        estado, ach, fal = qc.classificar(item, res)
        got = {"unidades": res["unidades"], "esperadas": res.get("esperadas"),
               "achados": len(ach), "falhas": len(fal), "estado": estado}
        ruim = [k for k in caso["esperado"] if got.get(k) != caso["esperado"][k]]
        conta("unidades varridas nas fixtures", res["unidades"])
        ok("%-26s %s" % (caso["arquivo"], estado), not ruim,
           "" if not ruim else "; ".join("%s=%s≠%s" % (k, got.get(k),
                                                       caso["esperado"][k])
                                         for k in ruim))
    return esperado


# ────────────────────────────────────────── 3. as 4 regras, uma a uma, com dentes

def c3_regras(cat, esperado):
    print("\n3 · 🦷 cada regra de classificação, DESLIGADA, tem que mudar o veredito")
    por_id = {i["id"]: i for i in cat["itens"]}

    def roda(desligadas):
        difs = 0
        for caso in esperado["casos"]:
            so, se = ler_fixture(caso["arquivo"])
            item = por_id[caso["item"]]
            res = qc.ADAPTADORES[item["adaptador"]](so, se, caso.get("exit", 0), {})
            estado, _a, _f = qc.classificar(item, res, desligadas)
            if estado != caso["esperado"]["estado"]:
                difs += 1
        return difs

    ok("com todas as regras ligadas, 0 divergência", roda(()) == 0)
    for regra in qc.REGRAS:
        n = roda((regra,))
        conta("regras com controle negativo")
        ok("desligar %-20s muda %d caso(s)" % (regra, n), n > 0,
           "regra sem efeito = regra que não está implementada" if not n else "")


# ──────────────────────────── 4. as fixtures escritas à mão não podem apodrecer

def c4_formato_vivo():
    print("\n4 · 🦷 as fixtures hand-made citam formato que AINDA EXISTE no fonte")
    exigencias = [
        ("qc-emendas-asr.py", ["ouvido: ", "⚠️ SUMIU ", "⚠️ VAZOU ",
                              "⚠️ REVISAO ",
                              # a linha de fecho ganhou a contagem de
                              # contíguas; o adaptador casa `(\\d+) emendas`
                              # e continua pegando o número auditável.
                              " emendas de verdade · ", "⏭️ CONTÍGUO"]),
        ("edl_io.py", ["VELHA (%s) — a EDL mudou depois do render",
                       "· timeline_real: %s"]),
        ("qc-cor.py", ["varreu %d arquivo(s)", "🔴 PIXELS AINDA NÃO CONVERTIDOS"]),
        ("audit-emendas.py", ["CLIP-FIM", "CLIP-INICIO",
                              "SEM PALAVRAS mas COM ENERGIA"]),
        ("qc-ataque.py", ["⚠️ ATAQUE", " emendas · "]),
        ("qc-fonemas.py", ["alerta(s) fonético(s)", "[HERDADO"]),
        ("qc-cauda.py", ["varredura: ", "REPROVADO"]),
        ("flicker-scan.py", ["varrendo ", "salto(s) acima de "]),
    ]
    for arq, literais in exigencias:
        with open(os.path.join(SCRIPTS, arq), encoding="utf-8") as fh:
            fonte = fh.read()
        for lit in literais:
            conta("literais de formato conferidos")
            ok("%-20s ainda imprime %r" % (arq, lit[:34]), lit in fonte)


# ───────────────────────────────────────────────────── 5. predicado declarativo

def c5_predicado():
    print("\n5 · o avaliador de `requer_perfil` (sem eval, sem parênteses)")
    p = {"video": {"largura": 256, "altura": 456, "fps": 30}, "ritmo": {"floor": "auto"}}
    casos = [
        ("video.largura == 256", True),
        ("video.largura == 999", False),
        ("video.largura == 256 && video.fps >= 24", True),
        ("video.largura == 256 && video.fps > 60", False),
        ("video.largura == 999 || video.fps == 30", True),
        ("ritmo.floor == 'auto'", True),
        ("ritmo.floor != auto", False),
        ("naoexiste.chave == 1", False),
    ]
    for expr, quer in casos:
        conta("predicados avaliados")
        got, _m = qc.avaliar_predicado(expr, p)
        ok("%-38s → %s" % (expr, got), got == quer)
    try:
        qc.avaliar_predicado("video.largura 256", p)
        ok("recusa termo ilegível", False, "aceitou")
    except qc.ErroUso:
        ok("recusa termo ilegível", True)


# ────────────────────────────────────────────────────── 6. o orçamento de saída

def _item_falso(iid, estado, n_ach=0, n_fal=0, unidades=10):
    def acs(tag, n):
        return [{"onde": "seg%02d" % i, "tag": tag,
                 "detalhe": "detalhe razoavelmente longo de exemplo %d" % i}
                for i in range(n)]
    return {"id": iid, "titulo": "", "tipo": "detector", "classe": "qc",
            "unidade": "segmento", "estado": estado, "motivo": None,
            "detalhe": "resumo", "unidades": unidades, "esperadas": unidades,
            "achados": acs("CLIP-FIM", n_ach), "falhas": acs("ATAQUE", n_fal),
            "resumo": "resumo", "exec": None, "nota_classe": ""}


def c6_orcamento(cat):
    print("\n6 · o orçamento de saída, e o guarda que colapsa a seção ACHADO")
    ctx = {"dir": "/x/producao-de-teste", "perfil": {"nome": "reels"},
           "perfil_fallback": False, "n_segmentos": 29}
    limpo = ([_item_falso("qc-%d" % i, "ok") for i in range(6)]
             + [_item_falso("det-%d" % i, "achado", n_ach=30) for i in range(4)])
    txt = qc.formatar(ctx, "montado", "auto", limpo, cat, 96.0)
    conta("renderizações de veredito")
    ok("bateria com 120 achados cabe em %d chars" % qc.ORCAMENTO_LIMPO,
       len(txt) <= qc.ORCAMENTO_LIMPO, "%d chars, sem precisar colapsar" % len(txt))

    # 🦷 DENTES DO GUARDA: 30 QCs com achados de tags distintas NÃO comprimem por
    # `N× TAG` — a versão não-colapsada estoura. Se o guarda não existisse, este
    # caso passaria de 1.400. Um guarda que nunca dispara é um guarda não testado.
    largo = [_item_falso("qc-longo-%02d" % i, "achado", n_ach=2) for i in range(30)]
    for k, it in enumerate(largo):
        for j, a in enumerate(it["achados"]):
            a["tag"] = "TAG-%02d-%d" % (k, j)
    sem_guarda = sum(len("  %-13s %s" % (it["id"], qc._agrupar(it["achados"])))
                     for it in largo)
    txt_g = qc.formatar(ctx, "montado", "auto", largo, cat, 96.0)
    conta("renderizações de veredito")
    ok("o caso largo ESTOURARIA sem o guarda",
       sem_guarda > qc.ORCAMENTO_LIMPO, "só a seção ACHADO daria %d chars" % sem_guarda)
    ok("com o guarda, cabe em %d chars" % qc.ORCAMENTO_LIMPO,
       len(txt_g) <= qc.ORCAMENTO_LIMPO, "%d chars" % len(txt_g))
    ok("o colapso avisa onde está o resto",
       "(+detalhe em qc/relatorio.json)" in txt_g,
       "colapsou sem dizer que colapsou seria pior do que estourar")

    com_falha = limpo + [_item_falso("f-%d" % i, "falha", n_fal=4) for i in range(5)]
    txt2 = qc.formatar(ctx, "montado", "auto", com_falha, cat, 96.0)
    conta("renderizações de veredito")
    ok("com 5 QCs falhando cabe em %d chars" % qc.ORCAMENTO_COM_FALHA,
       len(txt2) <= qc.ORCAMENTO_COM_FALHA, "%d chars" % len(txt2))
    ok("a seção FALHA nunca é colapsada", "FALHA" in txt2 and "ATAQUE" in txt2)

    # 🦷 DENTES: um item em OK TEM que carregar a contagem do que varreu.
    so_ok = [_item_falso("qc-x", "ok", unidades=22)]
    t3 = qc.formatar(ctx, "montado", "auto", so_ok, cat, 1.0)
    conta("renderizações de veredito")
    ok("todo OK imprime a contagem", "qc-x(22/22)" in t3,
       "sem a contagem, verde é indistinguível de portão cego")
    ok("o bloco CEGO SEMPRE está sempre lá", "CEGO SEMPRE" in t3)

    revisao = _item_falso("qc-asr", "achado", n_ach=1)
    revisao["achados"][0]["tag"] = "REVISAO-ASR"
    t4 = qc.formatar(ctx, "montado", "auto", [revisao], cat, 1.0)
    conta("renderizações de veredito")
    ok("revisão ASR tem seção operacional própria",
       "REVISÃO HUMANA 1" in t4 and "esperado por construção" not in t4,
       t4.replace("\n", " | "))


# ──────────────────────────────────────────────── 7. resolução de estágio (auto)

def c7_estagio(cat):
    print("\n7 · `--estagio auto` escolhe o mais avançado que EXISTE, e diz por quê")
    for artefatos, quer in (
            ({"montado": "v1-montado.mp4"}, "montado"),
            ({"montado": "v1-montado.mp4", "final": "v-final.mp4"}, "final"),
            ({"montado": "v1-montado.mp4", "compositado": "graphics-alpha.mov"},
             "compositado"),
            ({}, "montado")):
        ctx = {"artefato_" + k: v for k, v in artefatos.items()}
        est, motivo = qc.resolver_estagio(cat, ctx, "auto")
        conta("resoluções de estágio")
        ok("%-46s → %s" % (sorted(artefatos.values()) or "nada em disco", est),
           est == quer, motivo[:60])
    try:
        qc.resolver_estagio(cat, {}, "inventado")
        ok("recusa estágio inexistente", False, "aceitou")
    except qc.ErroUso:
        ok("recusa estágio inexistente", True)
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "entregas"))
        for rel in ("entrega.Mp4", "ｖ-final.MP4", "entregas/v-final.mp4"):
            with open(os.path.join(d, rel), "wb") as fh:
                fh.write(b"nao-oficial")
        ok("QC não amplia o universo para genérico/fullwidth/subdiretório",
           qc._final1(d) is None, str(os.listdir(d)))
        with open(os.path.join(d, "v-final-COPIA.MP4"), "wb") as fh:
            fh.write(b"final-uppercase")
        ctx = qc.contexto(d, cat)
        est, motivo = qc.resolver_estagio(cat, ctx, "auto")
        conta("resoluções de estágio")
        ok("final com extensão uppercase continua visível ao QC",
           est == "final" and ctx.get("artefato_final") == "v-final-COPIA.MP4",
           motivo)
        irregular = os.path.join(d, "v-final-IRREGULAR.MP4")
        os.mkdir(irregular)
        try:
            qc._final1(d)
            ok("entrada final irregular não é ignorada pelo QC", False,
               "diretório virou ausência")
        except qc.ErroUso as exc:
            ok("entrada final irregular não é ignorada pelo QC",
               "não é arquivo regular" in str(exc), str(exc))
        os.rmdir(irregular)
        if hasattr(os, "mkfifo"):
            fifo = os.path.join(d, "v-final-PIPE.MP4")
            os.mkfifo(fifo)
            try:
                qc._final1(d)
                ok("FIFO com nome final não é ignorado pelo QC", False,
                   "FIFO virou ausência")
            except qc.ErroUso as exc:
                ok("FIFO com nome final não é ignorado pelo QC",
                   "não é arquivo regular" in str(exc), str(exc))
            os.unlink(fifo)
        def negar(_dir):
            raise PermissionError(13, "permissão negada")
        try:
            qc._final1(d, listar=negar)
            ok("erro de listagem não rebaixa estágio final", False,
               "PermissionError virou ausência")
        except qc.ErroUso as exc:
            ok("erro de listagem não rebaixa estágio final",
               "não foi possível listar" in str(exc), str(exc))


# ───────────────────────────────── 8. o registro de sonda (extensível, SPEC-26)

def c8_fragmentos(cat, tmp):
    print("\n8 · `qc/bateria.d/*.json`: registrar uma sonda sem editar o catálogo")
    import shutil
    base = os.path.join(tmp, "qc")
    os.makedirs(os.path.join(base, "bateria.d"), exist_ok=True)
    shutil.copy(qc.caminho_catalogo(), os.path.join(base, "bateria.json"))
    # ⚠️ OS FRAGMENTOS REAIS TAMBÉM. `cat` foi carregado do diretório de verdade,
    # onde `qc/bateria.d/` já registra sondas — copiar só o `bateria.json` fazia
    # a asserção seguinte comparar um catálogo COM fragmentos contra um SEM, e ela
    # falhava por construção, sempre, sem que nada estivesse errado no mecanismo.
    d_real = os.path.join(os.path.dirname(qc.caminho_catalogo()), "bateria.d")
    if os.path.isdir(d_real):
        for f in sorted(os.listdir(d_real)):
            if f.endswith(".json"):
                shutil.copy(os.path.join(d_real, f),
                            os.path.join(base, "bateria.d", f))
    with open(os.path.join(base, "bateria.d", "10-sonda-exemplo.json"), "w") as fh:
        json.dump({"itens": [{
            "id": "sonda-exemplo", "titulo": "sonda de teste", "classe": "sonda",
            "tipo": "detector", "estagios": ["montado"], "unidade": "linha",
            "adaptador": "generico", "exec": {"cmd": ["true"]},
            "requer": [], "nota_classe": "registrada por fragmento",
            "custo_s": 1}]}, fh)
    novo = qc.carregar_catalogo(os.path.join(base, "bateria.json"))
    conta("fragmentos carregados", len(novo["_fragmentos"]))
    ok("o fragmento entra no catálogo",
       "sonda-exemplo" in [i["id"] for i in novo["itens"]],
       "%d itens (era %d)" % (len(novo["itens"]), len(cat["itens"])))
    ok("nenhum item do catálogo base se perde",
       all(i["id"] in [x["id"] for x in novo["itens"]] for i in cat["itens"]))
    # sobrescrita por id, campo a campo
    with open(os.path.join(base, "bateria.d", "20-ajuste.json"), "w") as fh:
        json.dump({"itens": [{"id": "audit-emendas", "custo_s": 99}]}, fh)
    novo2 = qc.carregar_catalogo(os.path.join(base, "bateria.json"))
    ae = [i for i in novo2["itens"] if i["id"] == "audit-emendas"][0]
    ok("fragmento sobrescreve campo a campo, sem apagar o resto",
       ae["custo_s"] == 99 and ae["adaptador"] == "audit_emendas")


# ─────────────────── 9. 🦷 o guarda de saída anormal (H47-1, SPEC-47)
#
# O defeito que este bloco existe para não deixar voltar foi MEDIDO em campo
# (2026-08-12, agente externo rodando a v0.12 no Linux): `qc-cor.py` imprimiu
# "varreu 17", estourou `TypeError` e o item entrou no relatório como `ok` com
# `exec.exit=1`. Não é um caso hipotético; é uma reprodução.

_QC_QUE_MORRE = '''#!/usr/bin/env python3
"""Sub-QC que crasha DE PROPÓSITO — o controle negativo do H47-1.

Imprime a contagem que o adaptador lê (é isso que fazia o item virar `ok`) e só
depois morre, exatamente como o `qc-cor.py` da v0.12 morria."""
import sys
print("cor: varreu %d arquivo(s)" % 17)
sys.stdout.flush()
import os
os.path.exists(None)      # TypeError, igual ao medido em campo
'''

_QC_QUE_VIVE = '''#!/usr/bin/env python3
"""O MESMO sub-QC sem o crash — o controle positivo (o guarda não pode acusar
uma execução sadia, senão ele é só ruído novo)."""
print("cor: varreu %d arquivo(s)" % 17)
'''


def c9_saida_anormal(tmp):
    import subprocess
    print("\n9 · 🦷 sub-QC que morre NUNCA aparece verde (H47-1)")

    # ── (a) a função-guarda, caso a caso
    vazio = {"unidades": 3, "itens": []}
    tb = ("Traceback (most recent call last):\n"
          "  File 'qc-cor.py', line 812, in main\n"
          "TypeError: stat: path should be string, not NoneType")
    m, det = qc._saida_anormal("varreu 17", tb, 1, vazio)
    conta("casos do guarda")
    ok("traceback → crash", m == "crash" and "TypeError" in det, det)
    m, _ = qc._saida_anormal("", "", -9, vazio)
    conta("casos do guarda")
    ok("morto por sinal → crash", m == "crash")
    m, _ = qc._saida_anormal("", "", 127, vazio)
    conta("casos do guarda")
    ok("exit 127 (binário ausente) → crash", m == "crash")
    m, _ = qc._saida_anormal("nada", "", 1, vazio)
    conta("casos do guarda")
    ok("exit 1 sem item extraído → exit-inesperado", m == "exit-inesperado")
    m, _ = qc._saida_anormal("nada", "", 1, {"unidades": 1, "itens": [{"tag": "X"}]})
    conta("casos do guarda")
    ok("exit 1 COM item extraído → o adaptador explicou, não é anormal", m is None)
    m, _ = qc._saida_anormal("", "", 3, {"unidades": 0, "itens": [],
                                         "estado_forcado": "nao_verificado"})
    conta("casos do guarda")
    ok("exit que o adaptador FORÇOU estado → não é anormal (qc-cauda exit 3)",
       m is None)
    m, _ = qc._saida_anormal("tudo bem", "", 0, vazio)
    conta("casos do guarda")
    ok("execução sadia → nada (o guarda não é ruído novo)", m is None)

    # ── (b) ponta a ponta: `qc.py <dir>` com o sub-QC plantado
    def rodar_com(corpo, rotulo):
        d = os.path.join(tmp, "prod-" + rotulo)
        os.makedirs(os.path.join(d, "qc"), exist_ok=True)
        with open(os.path.join(d, "qc-plantado.py"), "w") as fh:
            fh.write(corpo)
        with open(os.path.join(d, "qc", "local.json"), "w") as fh:
            json.dump({"schema": qc.CONTRATO_LOCAL, "extras": [{
                "id": "qc-plantado", "titulo": "controle negativo do H47-1",
                "classe": "sonda", "tipo": "detector", "estagios": ["montado"],
                "unidade": "arquivo", "adaptador": "qc_cor",
                "script": "qc-plantado.py", "argv": ["{dir}"], "requer": []}]}, fh)
        env = {**os.environ, "BENCH_PERFIL_SEM_REMOTION": "1"}
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qc.py"), d,
                            "--estagio", "montado", "--so", "qc-plantado"],
                           capture_output=True, text=True, env=env)
        with open(os.path.join(d, "qc", "relatorio.json")) as fh:
            rel = json.load(fh)
        return r, rel

    r_mau, rel_mau = rodar_com(_QC_QUE_MORRE, "crash")
    itens_mau = {i["id"]: i for i in rel_mau["itens"]}
    nv_mau = {i["id"]: i for i in rel_mau["nao_verificado"]}
    conta("execuções ponta a ponta")
    ok("o item NÃO entra como ok/achado", "qc-plantado" not in itens_mau,
       "estado registrado: %s" % itens_mau.get("qc-plantado", {}).get("estado"))
    ok("o item entra como nao_verificado / crash",
       nv_mau.get("qc-plantado", {}).get("motivo") == "crash",
       str(nv_mau.get("qc-plantado")))
    ok("o relatório guarda o exit do sub-QC que morreu",
       (nv_mau.get("qc-plantado", {}).get("exec") or {}).get("exit") == 1)
    ok("o veredito da bateria é `anormal`, não `limpo`",
       rel_mau["veredito"] == "anormal", rel_mau["veredito"])
    ok("o exit do qc.py é 1 (a automação que só olha o exit não vê verde)",
       r_mau.returncode == 1, "exit %d" % r_mau.returncode)
    ok("o stdout marca 🔴 no item anormal", "🔴 qc-plantado" in r_mau.stdout,
       r_mau.stdout.splitlines()[-3:] and "")

    # 🦷 controle do controle: sem o crash, o MESMO caminho fica verde. Sem isto,
    # um guarda que reprovasse tudo passaria neste teste.
    r_bom, rel_bom = rodar_com(_QC_QUE_VIVE, "vivo")
    conta("execuções ponta a ponta")
    ok("sem o crash, o mesmo item é medido normalmente",
       rel_bom["veredito"] in ("limpo", "achados") and r_bom.returncode == 0,
       "veredito %s · exit %d" % (rel_bom["veredito"], r_bom.returncode))
    ok("e ele varreu as 17 unidades que imprimiu",
       any(i["unidades"] == 17 for i in rel_bom["itens"]),
       str([(i["id"], i["unidades"]) for i in rel_bom["itens"]]))


def c10_transcritos(cat, tmp):
    print("\n10 · preflight usa o mesmo resolvedor de transcript do auditor")
    d = os.path.join(tmp, "prod-transcript-raiz")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "take.mp4")
    for p in (src, os.path.join(d, "edl.json"), os.path.join(d, "transcript.json")):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
    item = next(i for i in cat["itens"] if i["id"] == "audit-emendas")
    ctx = {"dir": d, "srcs": [src], "local": {},
           "_artefatos_do_estagio": ["v1-montado.mp4"]}
    motivo, detalhe = qc.checar_insumos(item, ctx, "montado")
    conta("layouts de transcript resolvidos")
    ok("transcript.json na raiz não deixa a bateria cega",
       motivo is None, detalhe or "resolvido")

    os.unlink(os.path.join(d, "transcript.json"))
    motivo2, detalhe2 = qc.checar_insumos(item, ctx, "montado")
    conta("layouts de transcript resolvidos")
    ok("controle negativo continua acusando transcript ausente",
       motivo2 == "insumo" and "transcritos" in detalhe2,
       detalhe2 or "sem detalhe")

    d2 = os.path.join(tmp, "prod-multissrc-ambiguo")
    os.makedirs(d2, exist_ok=True)
    srcs = [os.path.join(d2, "take-a.mp4"), os.path.join(d2, "take-b.mp4")]
    for p in srcs + [os.path.join(d2, "edl.json"), os.path.join(d2, "transcript.json")]:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
    ctx2 = {"dir": d2, "srcs": srcs, "local": {},
            "_artefatos_do_estagio": ["v1-montado.mp4"]}
    motivo3, detalhe3 = qc.checar_insumos(item, ctx2, "montado")
    conta("layouts de transcript resolvidos")
    ok("um transcript solto não é reutilizado em dois brutos",
       motivo3 == "insumo" and "transcritos" in detalhe3,
       detalhe3 or "sem detalhe")


def c11_credencial_canonica(tmp):
    print("\n11 · requisito env: resolve $ILHA_HOME e injeta só no sub-QC")
    home = os.path.join(tmp, "ilha-home-qc")
    prod = os.path.join(tmp, "prod-chave-qc")
    os.makedirs(home, exist_ok=True)
    os.makedirs(prod, exist_ok=True)
    segredo_arquivo = "dg-qc-arquivo-" + "R4T8"
    segredo_env = "dg-qc-ambiente-" + "V9P2"
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as fh:
        fh.write("DEEPGRAM_API_KEY=%s\n" % segredo_arquivo)
    os.chmod(os.path.join(home, ".env"), 0o600)

    item = {
        "id": "qc-chave-controle", "titulo": "controle da credencial",
        "tipo": "detector", "classe": "qc", "unidade": "linha",
        "adaptador": "generico", "requer": ["env:DEEPGRAM_API_KEY"],
        "exec": {"cmd": [
            sys.executable, "-c",
            ("import os,sys; print('credencial recebida'); "
             "sys.exit(0 if os.environ.get(os.environ['ILHA_TEST_NOME']) == "
             "os.environ.get('ILHA_TEST_ESPERADA') else 9)"),
        ]},
        "custo_s": 1,
    }
    chave = item["requer"][0].split(":", 1)[1]
    ctx = {"dir": prod, "perfil": {}, "local": {}, "srcs": [],
           "_estagios": {"montado": {"artefato": []}}}

    nomes = ("ILHA_HOME", chave, "ILHA_TEST_ESPERADA", "ILHA_TEST_NOME")
    antes = {nome: os.environ.get(nome) for nome in nomes}
    try:
        os.environ["ILHA_HOME"] = home
        os.environ.pop(chave, None)
        os.environ["ILHA_TEST_ESPERADA"] = segredo_arquivo
        os.environ["ILHA_TEST_NOME"] = chave
        qc._CHAVES_MOD = None
        qc._CHAVES_TENTADO = False
        r_arquivo = qc.executar_item(item, ctx, "montado")
        conta("credenciais canônicas injetadas")
        ok("shell sem chave usa $ILHA_HOME/.env",
           r_arquivo["estado"] == "ok" and r_arquivo["exec"]["exit"] == 0,
           "%s / %s" % (r_arquivo["estado"], r_arquivo["detalhe"]))
        ok("injeção não altera o ambiente do processo pai",
           chave not in os.environ)
        texto_log = "\n".join(r_arquivo.get("_log") or ())
        ok("valor do arquivo não aparece no log",
           segredo_arquivo not in texto_log and "R4T8" not in texto_log)

        os.environ[chave] = segredo_env
        os.environ["ILHA_TEST_ESPERADA"] = segredo_env
        r_env = qc.executar_item(item, ctx, "montado")
        conta("precedências de credencial conferidas")
        ok("ambiente vence o arquivo canônico",
           r_env["estado"] == "ok" and r_env["exec"]["exit"] == 0,
           "%s / %s" % (r_env["estado"], r_env["detalhe"]))
        texto_env = "\n".join(r_env.get("_log") or ())
        ok("valor do ambiente não aparece no log",
           segredo_env not in texto_env and "V9P2" not in texto_env)
    finally:
        for nome, valor in antes.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor


def c12_plano_visual_nunca_e_pulado(tmp):
    print("\n12 · plano visual ausente ou stale é FALHA, nunca skip verde")
    item = next(i for i in qc.carregar_catalogo()["itens"]
                if i["id"] == "plano-visual")
    ok("catálogo não transforma plano ausente em preflight/insumo",
       item.get("requer") == [], str(item.get("requer")))

    env = {**os.environ, "BENCH_PERFIL_SEM_REMOTION": "1"}

    def executar(d, estagio):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "qc.py"), d,
             "--estagio", estagio, "--so", "plano-visual", "--json"],
            text=True, capture_output=True, env=env,
        )
        try:
            rel = json.loads(r.stdout)
        except ValueError as exc:
            raise AssertionError("qc.py não devolveu JSON: %s / %s" %
                                 (r.stdout, r.stderr)) from exc
        return r, rel

    # Controle negativo 1: no compositado há render, mas nenhum plano. O script
    # precisa rodar para produzir PLANO-VISUAL-AUSENTE e o orquestrador sair 1.
    d_aus = os.path.join(tmp, "prod-plano-ausente")
    os.makedirs(d_aus)
    with open(os.path.join(d_aus, "graphics-alpha.mov"), "wb") as fh:
        fh.write(b"render-grafico")
    r_aus, rel_aus = executar(d_aus, "compositado")
    it_aus = next((i for i in rel_aus["itens"] if i["id"] == "plano-visual"), None)
    conta("gates de plano visual ponta a ponta")
    ok("plano ausente no compositado reprova com exit não-zero",
       r_aus.returncode == 1 and rel_aus["veredito"] == "falha"
       and it_aus is not None and it_aus["estado"] == "falha",
       "exit %d · %s · %s" % (r_aus.returncode, rel_aus["veredito"], it_aus))
    ok("plano ausente não cai em nao_verificado",
       not any(i["id"] == "plano-visual" for i in rel_aus["nao_verificado"]),
       str(rel_aus["nao_verificado"]))

    # Controle negativo 2: plano Essencial nasce válido e depois sua autoridade
    # Markdown muda. No estágio final, STALE também precisa ser FALHA/exit 1.
    d_stale = os.path.join(tmp, "prod-plano-stale")
    os.makedirs(os.path.join(d_stale, ".preview"))
    estilo = {
        "contrato": "benchmark.edit-estilo-vigente/v1",
        "estilo": {
            "contrato": "benchmark.edit-estilo/v3",
            "direcao_edicao": {"modo": "essencial", "densidade": "leve",
                                "sfx": "sem-sfx"},
            "elementos": {"sfx": False},
        },
    }
    with open(os.path.join(d_stale, ".preview", "estilo-vigente.json"), "w") as fh:
        json.dump(estilo, fh)
    plano_md = os.path.join(d_stale, "PLANO-EDICAO.md")
    with open(plano_md, "w") as fh:
        fh.write("# Plano\n")
    with open(os.path.join(d_stale, "v1-montado.mp4"), "wb") as fh:
        fh.write(b"corte")
    with open(os.path.join(d_stale, "v-final.mp4"), "wb") as fh:
        fh.write(b"final")
    segmentos = [{"src": "bruto.mp4", "start": 0.0, "end": 1.0}]
    canon = json.dumps(segmentos, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    timeline = {
        "schema": "benchmark.timeline-real/v1",
        "edl_fingerprint": "sha1:" + hashlib.sha1(canon.encode()).hexdigest(),
        "total_s": 1.0,
    }
    with open(os.path.join(d_stale, "edl.json"), "w") as fh:
        json.dump({"schema": "benchmark.edl/v2", "segments": segmentos,
                   "timeline_real": timeline}, fh)
    iniciar = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "plano-visual.py"), d_stale,
         "--iniciar"], text=True, capture_output=True,
    )
    ok("controle positivo cria plano Essencial válido", iniciar.returncode == 0,
       iniciar.stderr or iniciar.stdout)
    with open(plano_md, "a") as fh:
        fh.write("mudou depois\n")
    r_stale, rel_stale = executar(d_stale, "final")
    it_stale = next((i for i in rel_stale["itens"] if i["id"] == "plano-visual"), None)
    conta("gates de plano visual ponta a ponta")
    ok("plano stale no final reprova com exit não-zero",
       r_stale.returncode == 1 and rel_stale["veredito"] == "falha"
       and it_stale is not None and it_stale["estado"] == "falha",
       "exit %d · %s · %s" % (r_stale.returncode, rel_stale["veredito"], it_stale))
    ok("plano stale não cai em nao_verificado",
       not any(i["id"] == "plano-visual" for i in rel_stale["nao_verificado"]),
       str(rel_stale["nao_verificado"]))


def main():
    import tempfile
    print("test_qc_bateria — bateria de QC orquestrada (SPEC-12)")
    tmp = tempfile.mkdtemp(prefix="qc-bateria-")
    try:
        cat = c1_catalogo()
        esperado = c2_adaptadores(cat)
        c3_regras(cat, esperado)
        c4_formato_vivo()
        c5_predicado()
        c6_orcamento(cat)
        c7_estagio(cat)
        c8_fragmentos(cat, tmp)
        c9_saida_anormal(tmp)
        c10_transcritos(cat, tmp)
        c11_credencial_canonica(tmp)
        c12_plano_visual_nunca_e_pulado(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n── o que este teste varreu ──")
    for k, v in sorted(varrido.items()):
        print("   %-38s %d" % (k, v))
    print("\n%s" % ("TUDO PASSOU" if not falhas
                    else "FALHOU (%d): %s" % (len(falhas), "; ".join(falhas[:6]))))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
