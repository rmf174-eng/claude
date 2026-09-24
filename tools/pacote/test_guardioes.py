#!/usr/bin/env python3
"""Os guardiões dos consertos que não tinham nenhum (achado R-20b, 2026-08-11).

    python3 ilha/tools/pacote/test_guardioes.py     # na nossa árvore
    python3 tools/pacote/test_guardioes.py          # na raiz de uma instalação

A revalidação mediu: os consertos A14, A19, A21, A22 e A23 fecharam com controle
negativo REPLANTADO na hora — e nenhum deles ganhou um teste que continue
reprovando amanhã. `grep -rn` por teste sobre eles devolvia 0. Conserto sem
guardião é conserto que dura até a próxima refatoração.

Cada caso aqui é uma AFIRMAÇÃO sobre o disco, e cada um foi visto REPROVAR com o
defeito replantado antes de entrar. O modelo é o `test_timestamped.py:198-206`
(a família `cN_*`, contadores do que foi varrido, exit 1 na primeira falha).

Os guardiões `f`, `g` e `h` entraram na SPEC-46 (2026-08-12), pelos consertos que
o teste do pacote num container Linux obrigou: a sonda de permissão do servidor,
o `--status` que dizia verde com a transcrição bloqueada, e as dependências que
não estavam declaradas em lugar nenhum que o cliente lesse.

exit 0 = os guardiões passaram · 1 = algum reprovou · 2 = erro de ambiente
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))


def _base_das_skills():
    """O diretório em que `skills/<x>/…` resolve. Por MARCADOR, nunca por nível.

    🔴 MEDIDO NO PACOTE, 2026-08-12 (o dono rodou o zip da v0.11 num container
    Linux): aqui só existia o marcador `ilha/tools/pacote/MANIFESTO.json`, que
    é o layout da NOSSA árvore. Na instalação do cliente o manifesto mora em
    `<raiz>/tools/pacote/MANIFESTO.json` e as skills em `<raiz>/.claude/skills/`
    — nenhum ancestral casava, `_raiz()` devolvia None e o arquivo saía com
    "ABORTA: não achei a raiz da árvore" (exit 2) antes do primeiro guardião.
    Os 5 guardiões afirmam coisas sobre o CÓDIGO DO PRODUTO (a broll-source que
    roda sozinha, o sample rate que vem do perfil, o card que lê o disco), e
    todas continuam valendo — e sendo verificáveis — na máquina de quem instalou.

    É a mesma família de `gerar-previews.py:_base_das_skills()` e de
    `previews-peca.py:_raiz_por_marcador()`. O marcador é o diretório
    `edit-video`, que existe nas duas grafias; devolvemos o PAI de `skills/`,
    porque é isso que precisa resolver: `ilha/` aqui, `<raiz>/.claude/` no pacote.
    """
    d = AQUI
    while True:
        if os.path.isdir(os.path.join(d, "skills", "edit-video")):
            return d
        if os.path.isdir(os.path.join(d, ".claude", "skills", "edit-video")):
            return os.path.join(d, ".claude")
        if d == os.path.dirname(d):
            return None
        d = os.path.dirname(d)


ILHA = _base_das_skills()
if ILHA is None:
    print("ABORTA: não achei `skills/edit-video` em nenhum ancestral de %s."
          % AQUI, file=sys.stderr)
    sys.exit(2)

EV = os.path.join(ILHA, "skills", "edit-video")
# A raiz da árvore em que `tools/pacote/` mora: `ilha/` aqui, `<raiz>/` no pacote.
# É diferente de ILHA, que é a base de `skills/` — no pacote as duas divergem.
BASE = os.path.dirname(os.path.dirname(AQUI))
falhas: list[str] = []
nao_medidos: list[str] = []
varrido: dict[str, int] = {}


def conta(k, v):
    varrido[k] = v


def ok(nome, cond, detalhe=""):
    print("  %s %s%s" % ("✅" if cond else "❌", nome,
                         ("  — " + detalhe) if detalhe else ""))
    if not cond:
        falhas.append(nome.split(".")[0])
    return cond


def nao_medido(nome, motivo):
    """Checagem que este AMBIENTE não permite medir. Não é falha e não é verde.

    🔴 Nasceu do guardião f (2026-08-12, H47-12/F47-5). O controle do controle
    dele confere que `chmod 500` de fato trava a escrita — e **sob root não
    trava**, porque root ignora o bit de permissão. Container roda como root por
    default, então a ÚNICA falha que um agente externo colheu nos 25 arquivos de
    teste da v0.12 foi esta: o teste reprovando o ambiente, não o produto. Ruído
    permanente treina quem lê a ignorar a bateria inteira.

    A saída não é passar calado (seria exatamente o silêncio que esta casa caça):
    é dizer, em voz alta, O QUE não foi medido e POR QUE, e sair 0.
    """
    print("  ⏭️ %s — NÃO MEDIDO: %s" % (nome, motivo))
    nao_medidos.append("%s (%s)" % (nome, motivo))


def _carregar(caminho, nome):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nome] = m
    spec.loader.exec_module(m)
    return m


# ─────────────────────────────────────────────────────────────────────── a
def a_broll_nao_importa_edit_video():
    """A21: a `broll-source` roda numa árvore SEM `edit-video`.

    O conserto foi ler o perfil pelo CONTRATO (`perfil_do_bloco.py` local) em vez
    de importar `perfil.py` da skill vizinha. Um `import` novo daquele lado volta
    a fazer `--help` estourar `ModuleNotFoundError` numa instalação que só levou
    um bloco — que é o teste que o produto promete.
    """
    d = os.path.join(ILHA, "skills", "broll-source", "scripts")
    arquivos = [f for f in sorted(os.listdir(d)) if f.endswith(".py")]
    conta("scripts de broll-source varridos", len(arquivos))
    ruins = []
    for f in arquivos:
        for i, ln in enumerate(open(os.path.join(d, f), encoding="utf-8"), 1):
            t = ln.strip()
            if not (t.startswith("import ") or t.startswith("from ")):
                continue
            if "edit_video" in t or "edit-video" in t:
                ruins.append("%s:%d %s" % (f, i, t[:60]))
            # `perfil_do_bloco` é o contrato local e É o conserto; `perfil` solto
            # é a skill vizinha.
            if t in ("import perfil", "from perfil import") or \
                    t.startswith("from perfil "):
                ruins.append("%s:%d %s" % (f, i, t[:60]))
    ok("a. broll-source não importa edit-video nem perfil.py", not ruins,
       "; ".join(ruins))


# ─────────────────────────────────────────────────────────────────────── b
def b_sr_do_perfil_nas_quatro_fontes():
    """A22 + R-14: `sr_do_perfil()` nas 4 fontes, E no ramo `--cold-open`.

    A ressalva do R-14 é a parte que faltava: a função existia e o ramo do
    cold-open retornava ANTES dela, com dois `48000` cravados no filtro de áudio.
    """
    enc = os.path.join(ILHA, "skills", "omni-insert", "scripts", "encaixar.py")
    m = _carregar(enc, "_g_encaixar")
    base = tempfile.mkdtemp(prefix="guardiao-sr-")
    try:
        # 1 · perfil.json com sr declarado
        with open(os.path.join(base, "perfil.json"), "w", encoding="utf-8") as fh:
            json.dump({"audio": {"sr": 44100}}, fh)
        sr1, f1 = m.sr_do_perfil(base, quieto=True)
        # 2 · outro valor, para provar que não é constante disfarçada
        with open(os.path.join(base, "perfil.json"), "w", encoding="utf-8") as fh:
            json.dump({"audio": {"sr": 96000}}, fh)
        sr2, f2 = m.sr_do_perfil(base, quieto=True)
        # 3 · sem perfil → fallback declarado.
        #     ⚠️ em outra árvore, e não num subdiretório de `base`: a função
        #     procura `<dir>/perfil.json` E `<pai>/perfil.json` (é o desenho —
        #     um script rodado de dentro de `remotion/` acha o perfil da peça),
        #     então um `vazio/` dentro de `base/` herdaria o de cima e o teste
        #     mediria a fonte errada. Medido aqui.
        limpo = tempfile.mkdtemp(prefix="guardiao-sr-limpo-")
        vazio = os.path.join(limpo, "vazio")
        os.makedirs(vazio, exist_ok=True)
        sr3, f3 = m.sr_do_perfil(vazio, quieto=True)
        # 4 · env
        os.environ["BENCH_SR"] = "22050"
        try:
            sr4, f4 = m.sr_do_perfil(vazio, quieto=True)
        finally:
            os.environ.pop("BENCH_SR", None)
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(locals().get("limpo") or "/nonexistent", ignore_errors=True)
    conta("fontes de sr exercidas", 4)
    ok("b1. as 4 fontes de sr_do_perfil",
       (sr1, f1) == (44100, "perfil.json") and (sr2, f2) == (96000, "perfil.json")
       and (sr3, f3) == (m.SR_FALLBACK, "fallback") and (sr4, f4) == (22050, "env"),
       "%s %s %s %s" % ((sr1, f1), (sr2, f2), (sr3, f3), (sr4, f4)))

    # e o ramo do cold-open não pode ter sample rate literal
    fonte = open(enc, encoding="utf-8").read()
    linhas = fonte.split("\n")
    i_cold = next((i for i, ln in enumerate(linhas) if "if a.cold_open:" in ln), None)
    i_fim = next((i for i, ln in enumerate(linhas[i_cold:], i_cold)
                  if ln.strip() == "return"), len(linhas)) if i_cold else 0
    ramo = "\n".join(linhas[i_cold:i_fim]) if i_cold else ""
    conta("linhas do ramo --cold-open", ramo.count("\n") + 1 if ramo else 0)
    cravados = [ln.strip() for ln in ramo.split("\n")
                if ("48000" in ln or "44100" in ln) and not ln.strip().startswith("#")]
    ok("b2. o ramo --cold-open não crava sample rate", not cravados,
       "; ".join(c[:70] for c in cravados))


# ─────────────────────────────────────────────────────────────────────── c
def c_preview_e_regua_do_arquivo():
    """A14: a galeria oferece estilo por PREVIEW NO DISCO, não pelo campo `estado`.

    Um `pronto` cujo poster sumiu é tão mudo quanto um `candidato`. A régua tem
    que ler o ARQUIVO — se ela voltar a ler `estado`, apagar um poster deixa de
    excluir o card e a tela volta a mostrar cinza.
    """
    p = os.path.join(EV, "scripts", "previews-peca.py")
    fonte = open(p, encoding="utf-8").read()
    conta("linhas do previews-peca.py", len(fonte.split("\n")))
    i = fonte.find("def _tem_preview")
    ok("c1. _tem_preview existe", i > 0)
    corpo = fonte[i:fonte.find("\ndef ", i + 10)] if i > 0 else ""
    linhas_corpo = [ln.strip() for ln in corpo.split("\n")
                    if ln.strip() and not ln.strip().startswith(("#", '"""'))]
    # tem que consultar o DISCO
    olha_disco = any(t in corpo for t in ("is_file()", "exists()", "isfile("))
    ok("c2. a régua do card lê o ARQUIVO no disco", olha_disco,
       next((ln[:70] for ln in linhas_corpo
             if any(t in ln for t in ("is_file()", "exists()", "isfile("))),
            "nenhuma linha toca o disco"))
    # e não pode decidir por `estado`
    decide_por_estado = '"pronto"' in corpo or "'pronto'" in corpo
    ok("c3. e não decide pelo campo `estado`", not decide_por_estado)


# ─────────────────────────────────────────────────────────────────────── d
def d_contratos_reprova_conjunto_vazio():
    """R-20a: `doc-check --contratos` com 0 arquivos de entrada não é verde."""
    dc = os.path.join(EV, "scripts", "doc-check.py")
    doc = os.path.join(EV, "references", "contrato-cor.md")
    r = subprocess.run([sys.executable, dc, "--contratos",
                        os.path.join(tempfile.gettempdir(), "nao-existe-1.py"),
                        os.path.join(tempfile.gettempdir(), "nao-existe-2.py"),
                        "--docs", doc], capture_output=True, text=True)
    conta("invocações de doc-check --contratos", 1)
    ok("d. --contratos com conjunto vazio sai != 0", r.returncode != 0,
       "exit %d · %s" % (r.returncode, (r.stdout or "").strip().split("\n")[0][:70]))


# ─────────────────────────────────────────────────────────────────────── e
def e_interruptor_tracking_existe_e_valida():
    """A19: o interruptor `tracking` existe E o validador o aceita.

    Eram dois ganchos pendurados: `previews-peca.py` mandava o card ligar um id
    que não existia em `interruptores.json`, e por isso o validador recusava
    `elementos.tracking` como "id fora de interruptores.json".
    """
    p = os.path.join(EV, "preview", "app", "galeria", "interruptores.json")
    itens = json.load(open(p, encoding="utf-8"))["itens"]
    ids = [i["id"] for i in itens]
    conta("interruptores declarados", len(ids))
    ok("e1. `tracking` está em interruptores.json", "tracking" in ids,
       ", ".join(ids))

    ee = _carregar(os.path.join(EV, "scripts", "escolha-estilo.py"), "_g_escolha")
    # galeria mínima: os grupos vazios e o mapa COMPLETO de interruptores
    galeria = {"contrato": "benchmark.galeria-estilos/v1", "grupos": [],
               "interruptores": [{"id": i, "nome": i, "padrao": False,
                                  "aplica": ""} for i in ids]}
    payload = {"contrato": "benchmark.edit-estilo/v2",
               "salvo_em": "2026-08-11T00:00:00-03:00", "revisao_base": 0,
               "fonte": "galeria",
               "elementos": {i: (i == "tracking") for i in ids}}
    erros = ee.validar(payload, galeria)
    ok("e2. o validador aceita elementos.tracking", not erros, "; ".join(erros))

    # e o digest instrui, com o tracking ligado E desligado
    payload_pp = dict(payload, gramatica="punch-pontual",
                      gramatica_plano="punch-pontual")
    lig = ee.resumo(payload_pp, None)
    desl = ee.resumo(dict(payload_pp,
                          elementos={i: False for i in ids}), None)
    ok("e3. o digest instrui o tracking LIGADO",
       "rastrear-rosto.py" in lig and "CameraSegue" in lig)
    ok("e4. e diz o que quebra DESLIGADO",
       "centro do quadro" in desl)


# ─────────────────────────────────────────────────────────────────────── f
def f_sonda_de_permissao_no_servidor():
    """SPEC-46 I7: `servidor.py sessao` num dir sem escrita dá REMÉDIO, não traceback.

    A primeira coisa que `abrir_sessao` faz é `mkdir` do `.preview/`, então um
    dir sem escrita saía com `PermissionError` cru. Não morde numa pasta de
    projeto; morde quem põe vídeo em `~/Desktop`, onde o TCC do macOS nega com
    EPERM mesmo com dono e modo perfeitos — e EPERM e EACCES pedem remédios
    opostos.
    """
    srv = os.path.join(EV, "preview", "servidor.py")
    m = _carregar(srv, "_g_servidor")
    conta("linhas do servidor.py", len(open(srv, encoding="utf-8").read().split("\n")))

    base = tempfile.mkdtemp(prefix="guardiao-perm-")
    try:
        livre = os.path.join(base, "livre")
        os.makedirs(livre)
        ok("f1. dir com escrita: a sonda deixa passar",
           m.sonda_de_escrita(__import__("pathlib").Path(livre)) is None)
        ok("f2. e não deixa sonda para trás", os.listdir(livre) == [],
           ", ".join(os.listdir(livre)))

        travado = os.path.join(base, "travado")
        os.makedirs(travado)
        os.chmod(travado, 0o500)
        try:
            # controle do controle: rodando como root o chmod não trava nada, e
            # um "passou" aqui seria mentira.
            pode_mesmo_assim = True
            try:
                sonda = os.path.join(travado, ".teste-do-teste")
                os.mkdir(sonda)
                os.rmdir(sonda)
            except OSError:
                pode_mesmo_assim = False
            if pode_mesmo_assim:
                # root ignora o bit de permissão: o chmod não trava, e daqui para
                # baixo o guardião mediria o nada. SKIP nomeado, exit 0 (H47-12).
                nao_medido("f3..f7 (a sonda de permissão)",
                           "o `chmod 500` não travou a escrita — este processo "
                           "é root (uid %d) e root ignora o bit de permissão. "
                           "Rode como usuário comum para medir a sonda."
                           % os.geteuid())
                return
            ok("f3. controle do controle: chmod 500 de fato trava", True,
               "mkdir de teste recusado")
            remedio = m.sonda_de_escrita(__import__("pathlib").Path(travado))
            ok("f4. dir sem escrita: a sonda devolve um REMÉDIO",
               isinstance(remedio, str) and remedio,
               (remedio or "None")[:80])

            r = subprocess.run([sys.executable, srv, "sessao", "--dir", travado],
                               capture_output=True, text=True)
            conta("invocações de `servidor.py sessao`", 1)
            ok("f5. o comando sai != 0", r.returncode != 0, "exit %d" % r.returncode)
            ok("f6. e SEM traceback", "Traceback" not in (r.stderr or ""),
               (r.stderr or "").strip().split("\n")[-1][:80])
            ok("f7. o stderr nomeia o remédio",
               "permiss" in (r.stderr or "").lower(),
               (r.stderr or "").strip().split("\n")[-1][:90])
        finally:
            os.chmod(travado, 0o700)

        # os dois errno não podem colapsar numa mensagem só
        fonte = open(srv, encoding="utf-8").read()
        i = fonte.find("def sonda_de_escrita")
        corpo = fonte[i:fonte.find("\ndef ", i + 10)] if i > 0 else ""
        ok("f8. EPERM e EACCES são ramos distintos",
           "errno.EPERM" in corpo and "EACCES" in corpo)
        ok("f9. e o remédio de EPERM não afirma TCC fora do macOS",
           'sys.platform == "darwin"' in corpo)
        # e a sonda tem que rodar ANTES de `abrir_sessao`, senão o mkdir chega primeiro
        j = fonte.find("def cmd_sessao")
        cs = fonte[j:fonte.find("\ndef ", j + 10)] if j > 0 else ""
        ok("f10. `cmd_sessao` sonda ANTES de `abrir_sessao`",
           0 < cs.find("sonda_de_escrita") < cs.find("abrir_sessao("),
           "sonda em %d, abrir em %d" % (cs.find("sonda_de_escrita"),
                                         cs.find("abrir_sessao(")))
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────── g
def g_status_nao_da_verde_com_transcricao_bloqueada():
    """SPEC-46 I4: sem a chave da transcrição, `--status` diz que está parado.

    O veredito lia uma propriedade da TABELA ("nenhum crítico declara fallback
    nulo") e por isso imprimia `✅ nenhuma etapa do caminho bruto → entregue
    depende de chave sem fallback` numa instalação sem a chave — enquanto o
    `transcribe.sh` parava com a variável não definida. O fallback declarado era
    um modo local que não existe no pacote.

    ⚠️ O NOME DA CHAVE SAI DO MANIFESTO, não daqui. Não é preciosismo: uma
    segunda cópia do nome é uma segunda verdade, e este guardião existe
    justamente para afirmar que a tabela e o runtime concordam. De quebra, o
    detector de chave dura do auditor (classe D) não vê literal nenhum aqui.
    """
    ch = os.path.join(AQUI, "chaves.py")
    manif = json.load(open(os.path.join(AQUI, "MANIFESTO.json"), encoding="utf-8"))
    rec = (manif.get("chaves") or {}).get("recursos") or {}
    conta("recursos declarados no MANIFESTO", len([k for k in rec if not k.startswith("_")]))
    ok("g1. o manifesto declara transcrição SEM fallback",
       ("transcricao" in rec) and rec["transcricao"].get("fallback") is None,
       repr((rec.get("transcricao") or {}).get("fallback"))[:70])

    chave = (rec.get("transcricao") or {}).get("chaves", [None])[0]
    if not ok("g1b. o manifesto nomeia a chave da transcrição", bool(chave)):
        return
    lar = os.path.join(tempfile.gettempdir(), "guardiao-ilha-home-inexistente")
    base_env = {k: v for k, v in os.environ.items() if k != chave}
    base_env["ILHA_HOME"] = lar
    sem = subprocess.run([sys.executable, ch, "--status"], capture_output=True,
                         text=True, env=base_env)
    conta("invocações de `chaves.py --status`", 2)
    ok("g2. sem a chave: exit 1", sem.returncode == 1, "exit %d" % sem.returncode)
    ok("g3. sem a chave: nomeia a transcrição como bloqueada",
       "BLOQUEADO" in sem.stdout and "transcricao" in sem.stdout)
    ok("g4. sem a chave: NÃO imprime o verde antigo",
       "✅ nenhuma etapa" not in sem.stdout,
       "a frase que mentia continua no arquivo" if "✅ nenhuma etapa" in sem.stdout
       else "")

    com = subprocess.run([sys.executable, ch, "--status"], capture_output=True,
                         text=True, env=dict(base_env, **{chave: "guardiao1234"}))
    ok("g5. com a chave: exit 0", com.returncode == 0, "exit %d" % com.returncode)
    ok("g6. com a chave: nenhum caractere identificador do valor vaza",
       "guardiao1234" not in com.stdout and "1234" not in com.stdout
       and "%s=configurada (env)" % chave in com.stdout)


# ─────────────────────────────────────────────────────────────────────── h
def h_dependencias_declaradas():
    """SPEC-46 I5: jq, numpy e Pillow existem no texto que o cliente lê.

    `jq` é chamado 15 vezes só dentro do `montar.sh` e não estava escrito em
    lugar nenhum; `numpy` e `Pillow` eram import de topo e o instalador nunca
    dizia como obtê-los. Achado do teste em container Linux, 2026-08-12.
    """
    req = os.path.join(BASE, "requirements.txt")
    ok("h1. requirements.txt existe na raiz", os.path.isfile(req), req)
    txt = open(req, encoding="utf-8").read() if os.path.isfile(req) else ""
    ok("h2. e declara numpy e Pillow",
       "numpy" in txt and "Pillow" in txt)

    manif = json.load(open(os.path.join(AQUI, "MANIFESTO.json"), encoding="utf-8"))
    reqs = ((manif.get("plataformas") or {}).get("requisitos") or {})
    ok("h3. o MANIFESTO declara jq em plataformas.requisitos", "jq" in reqs,
       ", ".join(sorted(reqs)))

    # o README do produto: `README.produto.md` aqui, `README.md` no pacote
    cands = [os.path.join(BASE, "README.produto.md"), os.path.join(BASE, "README.md")]
    rd = next((c for c in cands if os.path.isfile(c)), None)
    conta("README do produto encontrado", 1 if rd else 0)
    rtxt = open(rd, encoding="utf-8").read() if rd else ""
    ok("h4. o README pede jq", "jq" in rtxt, rd or "nenhum README achado")
    ok("h5. e manda instalar o requirements.txt", "requirements.txt" in rtxt)

    # o jq que o README promete é o jq que o montar.sh usa
    montar = os.path.join(EV, "scripts", "montar.sh")
    n_jq = sum(1 for ln in open(montar, encoding="utf-8") if "jq " in ln)
    conta("chamadas de jq no montar.sh", n_jq)
    ok("h6. e o montar.sh de fato depende dele", n_jq > 0, "%d chamadas" % n_jq)


def main():
    print("── guardiões dos consertos das ondas C/D/E (R-20b) + SPEC-46 ──")
    for f in (a_broll_nao_importa_edit_video,
              b_sr_do_perfil_nas_quatro_fontes,
              c_preview_e_regua_do_arquivo,
              d_contratos_reprova_conjunto_vazio,
              e_interruptor_tracking_existe_e_valida,
              f_sonda_de_permissao_no_servidor,
              g_status_nao_da_verde_com_transcricao_bloqueada,
              h_dependencias_declaradas):
        f()
    print("\n── o que este teste varreu ──")
    for k, v in varrido.items():
        print("   %-42s %d" % (k, v))
    if nao_medidos:
        # visível na última linha, sempre: "passou" e "passou sem medir tudo" não
        # podem chegar iguais a quem lê (H47-12).
        print("\n── NÃO MEDIDO neste ambiente (%d) ──" % len(nao_medidos))
        for x in nao_medidos:
            print("   ⏭️ %s" % x)
    print("\n%s%s" % ("TUDO PASSOU" if not falhas
                      else "FALHOU: " + ", ".join(sorted(set(falhas))),
                      "" if not nao_medidos else
                      " (com %d checagem(ns) NÃO MEDIDA(S) — ver acima)"
                      % len(nao_medidos)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
