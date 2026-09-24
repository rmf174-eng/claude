#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qc-portao.py — o portão de aprovação deixa de ser uma frase e vira medição.

A forma do contrato numerado e a lista do que não entra no contexto são modeladas
de uma ferramenta de edição de terceiro, SKILL.md:19-33
e :33 — cópia de leitura em tools/referencias/. O conteúdo é nosso: cada regra vem de
uma lição medida neste repo, e a lista de contexto foi verificada item a item contra
os arquivos daqui (3 dos 8 itens exigiram exceção que o original não tem). Este
script não tem equivalente lá: o ref-A tem o portão como regra e nada que confira
no disco se a camada gráfica nasceu antes da aprovação.

Ele responde UMA pergunta:

    existe artefato de camada gráfica nesta produção sem uma aprovação válida do corte?

    qc-portao.py <dir-producao> [--json] [--aceitar-degradado]
        exit 0  portão respeitado — aprovação VÁLIDA e nascida da UI
        exit 1  camada gráfica sem aprovação · entregue sem aprovação e fora da
                lista de legado · aprovação válida mas nascida fora da tela
        exit 2  a aprovação existe mas está INVALIDADA (plano ou render mudou depois)
        exit 3  erro de uso

    qc-portao.py <dir-producao> --aprovar --por <nome> [--alvo fase-1] [--motivo "..."]
        MODO DEGRADADO, e ele se declara: grava `fonte: "cli-degradado"`.
        O caminho normal é o BOTÃO da UI (Fase 1 → ✓ Aprovar o corte), que faz o
        servidor gravar `fonte: "ui-save"` com o pid da sessão. Este comando
        existe para máquina sem browser, e o portão o reprova por default.

O que ele NÃO faz: não abre tela, não pede aprovação, não escreve `estado.json`
(é da SPEC-16), não julga qualidade, não re-renderiza nada. Compara hash e mtime.

── As duas guardas, e o que a auditoria de 2026-08-10 mudou nelas ───────────────

**Legado (A11).** "Entregue e sem aprovação → exit 0" foi escrito para não
reprovar retroativamente as produções anteriores à SPEC-16. Só que a condição não
olha data: valia para sempre, para qualquer produção. O pior descumprimento
possível — entregar sem ninguém aprovar — era o caso que saía verde. Agora o
perdão é uma LISTA NOMEADA (`_portao-legado.json`, ao lado da produção; ver
`lista_legado`), que é da instância: um cliente não tem legado, o arquivo não
existe, a lista é vazia, o portão é estrito desde o primeiro dia.

**Autoria (A10).** O portão conferia que a aprovação estava presa ao conteúdo, e
nunca perguntava quem aprovou — `--por` é string livre e o default do `estado.py`
era `$USER`. Uma peça saiu "aprovada pelo creator", assinada pelo agente, com a
tela nunca aberta. Agora a fonte importa: `ui-save` (só o servidor grava, e só
com o botão clicado) passa; qualquer outra reprova sem `--aceitar-degradado`.
"""

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCHEMA = "benchmark.portao/v1"
ARQ_LOCAL = ".aprovacao.json"
ALVO_PADRAO = "fase-1"

# ── de onde a aprovação nasceu (achados A10 e A11) ───────────────────────────
FONTE_UI = "ui-save"
FONTE_CLI = "cli-degradado"

# ── a lista fechada do legado (achado A11) ───────────────────────────────────
#
# 🔴 O RAMO QUE PERDOAVA O FUTURO. A guarda "entregue e sem aprovação → legado,
# exit 0" foi escrita para não reprovar retroativamente as produções anteriores
# à SPEC-16. Só que ela não olha data nenhuma: ela vale para SEMPRE e para
# QUALQUER produção. O pior descumprimento possível — entregar sem ninguém
# aprovar — era exatamente o caso que saía verde, e ficava mais verde quanto
# mais longe fosse a entrega.
#
# Agora o perdão é NOMEADO. A lista é da INSTÂNCIA, nunca do produto: ela contém
# nome de produção nossa, e um cliente não tem legado nenhum — para ele o
# arquivo não existe, a lista é vazia, e o portão é estrito desde o primeiro dia.
# Ausência é silêncio, não aviso (a régua de uma frase do CORTE.md).
ARQ_LEGADO = "_portao-legado.json"


def _plano_visual():
    """Carrega o gate da Fase 2 sem copiar suas regras para este portão."""
    if "_pv" not in globals():
        try:
            import importlib.util
            caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "plano-visual.py")
            spec = importlib.util.spec_from_file_location("plano_visual", caminho)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            globals()["_pv"] = mod
        except Exception:                                        # noqa: BLE001
            globals()["_pv"] = None
    return globals()["_pv"]


def lista_legado(dirp):
    """(slugs, caminho). `$BENCH_PORTAO_LEGADO` vence; o default é o
    `_portao-legado.json` ao lado da produção (`<dir>/../`), que é instância por
    construção. Sem arquivo → lista vazia → nenhuma produção é perdoada."""
    env = os.environ.get("BENCH_PORTAO_LEGADO")
    caminho = env or os.path.join(os.path.dirname(os.path.abspath(dirp.rstrip("/"))),
                                  ARQ_LEGADO)
    obj = _ler_json(caminho)
    if not isinstance(obj, dict):
        return set(), caminho
    return {str(s) for s in (obj.get("producoes") or [])}, caminho

# Papéis, nunca formato: este script não sabe resolução, cadência nem sample rate.
RENDER_DO_CORTE = ("v1-montado.mp4", "v1-sdr.mp4")
GLOB_ENTREGUE = ("v-final*.mp4", "v-final*.mov")
PLANO = "PLANO-EDICAO.md"

# A camada gráfica, lista fechada.
GLOBS_GRAFICOS = ("overlays*.json", "captions*.json", "caps*.json",
                  "graphics-alpha*.mov", "graphics-alpha*.webm",
                  "*-graded.mp4", "v-final*.mp4")


def _sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


def _fingerprint(caminho):
    """O MESMO fingerprint do `estado.py` (SPEC-16), para a migração ser cópia de
    objeto: sha1 do texto "<nome>|<bytes>|<mtime inteiro>"."""
    st = os.stat(caminho)
    txt = "%s|%d|%d" % (os.path.basename(caminho), st.st_size, int(st.st_mtime))
    return "sha1:" + hashlib.sha1(txt.encode("utf-8")).hexdigest()


def _ler_json(caminho, default=None):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _agora():
    t = time.localtime()
    off = -(time.altzone if t.tm_isdst else time.timezone)
    sinal = "+" if off >= 0 else "-"
    off = abs(off)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + "%s%02d:%02d" % (sinal, off // 3600, (off % 3600) // 60)


# ── o que existe no disco ────────────────────────────────────────────────────
def render_do_corte(dirp):
    for nome in RENDER_DO_CORTE:
        p = os.path.join(dirp, nome)
        if os.path.isfile(p):
            return p
    return None


def entregaveis(dirp):
    out = []
    for g in GLOB_ENTREGUE:
        out += sorted(glob.glob(os.path.join(dirp, g)))
    return out


def graficos(dirp):
    achados = {}
    for g in GLOBS_GRAFICOS:
        for p in glob.glob(os.path.join(dirp, g)):
            if os.path.isfile(p):
                achados[os.path.abspath(p)] = p
    return sorted(achados.values())


def aprovacoes_registradas(dirp, alvo):
    """Ordem de preferência de fonte: `estado.json` da SPEC-16 vence; o
    `.aprovacao.json` do modo degradado é ignorado quando o estado existe."""
    fontes, avisos = [], []
    est = _ler_json(os.path.join(dirp, ".preview", "estado.json"))
    do_estado = [a for a in ((est or {}).get("aprovacoes") or [])
                 if a.get("alvo") == alvo] if est else []
    local = _ler_json(os.path.join(dirp, ARQ_LOCAL))
    if do_estado:
        fontes = [("estado.json", a) for a in do_estado]
        if local:
            avisos.append(".aprovacao.json ignorado: estado.json vence")
    elif local and local.get("alvo", ALVO_PADRAO) == alvo:
        fontes = [(ARQ_LOCAL, local)]
    return fontes, avisos


# ── a régua ──────────────────────────────────────────────────────────────────
def avaliar(dirp, alvo=ALVO_PADRAO, aceitar_degradado=False):
    r = {"schema": SCHEMA, "dir": dirp, "alvo": alvo, "flag": None,
         "render": None, "graficos_apos_o_corte": [], "graficos_varridos": 0,
         "aprovacao": None, "plano_visual": None,
         "motivos": [], "avisos": [], "exit": 0}
    if not os.path.isdir(dirp):
        r["flag"] = "erro"
        r["motivos"].append("diretório não existe")
        r["exit"] = 3
        return r

    rend = render_do_corte(dirp)
    r["render"] = os.path.basename(rend) if rend else None
    todos = graficos(dirp)
    r["graficos_varridos"] = len(todos)
    if rend:
        corte_mtime = os.stat(rend).st_mtime
        r["graficos_apos_o_corte"] = [os.path.basename(p) for p in todos
                                      if os.path.basename(p) != os.path.basename(rend)
                                      and os.stat(p).st_mtime > corte_mtime]
    else:
        r["graficos_apos_o_corte"] = [os.path.basename(p) for p in todos]
        r["avisos"].append("sem render de corte no disco — mtime não é comparável")

    fontes, avisos = aprovacoes_registradas(dirp, alvo)
    r["avisos"] += avisos
    entregues = [os.path.basename(p) for p in entregaveis(dirp)]

    # 1 · a guarda do legado, antes de tudo — e agora ela é uma LISTA FECHADA.
    if not fontes and entregues:
        slug = os.path.basename(os.path.abspath(dirp.rstrip("/")))
        legado, arq_legado = lista_legado(dirp)
        if slug in legado:
            r["flag"] = "legado"
            r["aprovacao"] = None
            r["motivos"].append(
                "produção já entregue (%s), sem registro de aprovação, e NOMEADA "
                "em %s — nada publicado é re-renderizado"
                % (", ".join(entregues[:3]), os.path.basename(arq_legado)))
            r["exit"] = 0
            return r
        r["flag"] = "entregue-sem-aprovacao"
        r["motivos"].append(
            "produção ENTREGUE (%s) sem nenhum registro de aprovação, e %r não "
            "está na lista de legado (%s). Entregar sem ninguém aprovar é o pior "
            "descumprimento do portão, não uma isenção."
            % (", ".join(entregues[:3]), slug, arq_legado))
        r["exit"] = 1
        return r

    # 2 · 🔴 A VALIDADE DA APROVAÇÃO É CONFERIDA ANTES DE QUALQUER ATALHO.
    #     Este era um sucesso silencioso, achado pelo defeito plantado do
    #     `test_qc_portao.py`: re-renderizar o corte DEPOIS de aprovar deixa a camada
    #     gráfica mais VELHA que o render, o atalho "sem camada nova" disparava e o
    #     portão devolvia 0 sem nunca comparar os dois fingerprints — verde exatamente
    #     no caso "aprovado, depois mudou" que ele existe para pegar.
    #
    #     ⚠️ E ELA ESTAVA ATRÁS DE UM SEGUNDO ATALHO (achado R-4, 2026-08-11), o de
    #     "sem render no disco → nao-verificado", que rodava LOGO ACIMA desta linha
    #     e devolvia 0 antes de comparar fingerprint nenhum. O comentário aqui
    #     dizia "antes de qualquer atalho" e havia um atalho na frente dele.
    #     Consequência medida: das 14 produções reais, 8 já estão sem o render do
    #     corte no disco, e apagar `v1-montado.mp4` da única que sai exit 2
    #     convertia a invalidação em exit 0. Divergência registrada é registro:
    #     ela não deixa de valer porque o arquivo que a produziu foi apagado —
    #     ao contrário, apagar o arquivo é o que a torna INVERIFICÁVEL, e portanto
    #     nunca mais reparável em silêncio.
    if fontes:
        fonte, ap = fontes[-1]
        r["aprovacao"] = _descrever((fonte, ap))
        p_plano = os.path.join(dirp, ap.get("plano") or PLANO)
        if ap.get("plano_sha256"):
            if not os.path.isfile(p_plano):
                r["motivos"].append("plano aprovado não existe mais no disco")
            elif _sha256_arquivo(p_plano) != ap["plano_sha256"]:
                r["motivos"].append("plano_sha256 divergente — o plano mudou depois de aprovado")
        if ap.get("render_fingerprint"):
            # sem `rend` no disco o nome vem SÓ do que a aprovação registrou —
            # inventar um nome aqui seria medir outro arquivo.
            nome_r = ap.get("render") or (os.path.basename(rend) if rend else None)
            p_rend = os.path.join(dirp, nome_r) if nome_r else None
            if not p_rend or not os.path.isfile(p_rend):
                r["motivos"].append(
                    "render aprovado (%s) não existe mais no disco — a aprovação "
                    "está presa a um fingerprint que já não é conferível"
                    % (nome_r or "nome não registrado"))
            elif _fingerprint(p_rend) != ap["render_fingerprint"]:
                r["motivos"].append("render_fingerprint divergente — o corte mudou depois de aprovado")

    # 3 · sem render de corte no disco não existe régua DE MTIME: a comparação não
    #     pôde ser feita, e responder "reprovado" a partir de uma medição que não
    #     aconteceu é o portão ancorado no valor que ele deveria conferir.
    #     Medido: `creator-2/peca-05` é o caso — bruto já montado pela creator, sem
    #     `v1-montado.mp4`, entregue em 2026-07-29 (NOTAS.md:5) com os entregáveis
    #     já fora do disco. Com a régua anterior ela saía 1, uma reprovação
    #     retroativa de produção publicada.
    #     O atalho continua — mas só quando NADA foi conferido e reprovado acima.
    #     "Não medi o mtime" não é "não medi nada".
    if not rend and not r["motivos"]:
        r["flag"] = "nao-verificado"
        r["motivos"].append("sem render de corte (%s) no disco — mtime não é comparável, "
                            "e este portão não reprova o que não mediu"
                            % "/".join(RENDER_DO_CORTE))
        r["exit"] = 0
        return r
    if not rend and r["motivos"]:
        r["flag"] = "invalidada"
        r["exit"] = 2
        return r

    # 4 · O corte aprovado não autoriza uma Fase 2 sem direção. Antes deste
    # gate, uma produção com overlays e só legenda passava porque a aprovação
    # conferia apenas corte + Markdown. A autoria degradada continua sendo
    # julgada pela regra 7; só validamos o plano aqui quando a fonte já pode ser
    # aceita neste modo de execução.
    fonte_ap = (fontes[-1][1] or {}).get("fonte") if fontes else None
    fonte_pode_avancar = fonte_ap == FONTE_UI or aceitar_degradado
    if fontes and not r["motivos"] and fonte_pode_avancar:
        pv = _plano_visual()
        if pv is None:
            r["flag"] = "plano-visual-indisponivel"
            r["motivos"].append("plano-visual.py não está disponível")
            r["exit"] = 1
            return r
        codigo_pv, medicao_pv = pv.validar(Path(dirp).resolve(), "planejamento")
        r["plano_visual"] = {
            "veredito": medicao_pv.get("veredito"),
            "modo": medicao_pv.get("modo"),
            "eventos": medicao_pv.get("eventos"),
        }
        if codigo_pv:
            erros_pv = medicao_pv.get("erros") or []
            r["flag"] = "plano-visual-invalido"
            r["motivos"] += ["%s: %s" % (e.get("codigo", "PLANO-VISUAL"),
                                           e.get("mensagem", ""))
                             for e in erros_pv]
            r["exit"] = 2 if any(str(e.get("codigo", "")).startswith("STALE-")
                                  for e in erros_pv) else 1
            return r

    # 5 · sem camada gráfica depois do corte, não há o que exigir.
    if not r["graficos_apos_o_corte"] and not r["motivos"]:
        r["flag"] = "sem-camada-nova"
        r["exit"] = 0
        return r

    # 6 · há camada gráfica depois do corte: exige aprovação válida.
    if not fontes:
        r["flag"] = "sem-aprovacao"
        r["motivos"].append("camada gráfica mais nova que o corte, sem aprovação de %s" % alvo)
        r["exit"] = 1
        return r

    if r["motivos"]:
        r["flag"] = "invalidada"
        r["exit"] = 2
        return r

    # 7 · 🔴 A AUTORIA (achado A10). Chegar aqui significa "existe aprovação
    #     válida, presa ao conteúdo". Falta a pergunta que o portão nunca fez:
    #     QUEM aprovou. `--por` é string livre e o default do `estado.py` era
    #     `$USER` — o agente assinava pelo creator, e o portão dizia verde.
    #     `ui-save` só o servidor de preview grava, e só com o botão clicado.
    fonte_ap = (fontes[-1][1] or {}).get("fonte")
    if fonte_ap != FONTE_UI and not aceitar_degradado:
        r["flag"] = "aprovacao-degradada"
        r["motivos"].append(
            "a aprovação existe e é válida, mas nasceu fora da tela (fonte %r). "
            "O creator aprova no BOTÃO da UI (Fase 1 → ✓ Aprovar o corte); sem "
            "browser, rode com --aceitar-degradado e assuma a exceção por escrito."
            % (fonte_ap or "não registrada"))
        r["exit"] = 1
        return r
    if fonte_ap != FONTE_UI:
        r["avisos"].append("aprovação aceita em modo degradado (fonte %r): "
                           "ninguém viu o corte na tela" % (fonte_ap or "—"))
    r["flag"] = "aprovado"
    r["exit"] = 0
    return r


def _descrever(par):
    fonte, ap = par
    return {"fonte": fonte, "origem": ap.get("fonte"), "por": ap.get("por"),
            "em": ap.get("em"), "alvo": ap.get("alvo"), "motivo": ap.get("motivo"),
            "render": ap.get("render"), "plano": ap.get("plano"),
            "sessao_pid": ap.get("sessao_pid")}


# ── gravar a aprovação (o antigo "vai direto", agora auditável) ───────────────
def aprovar(dirp, por, alvo=ALVO_PADRAO, motivo=None):
    rend = render_do_corte(dirp)
    if not rend:
        sys.stderr.write("qc-portao: não há render de corte em %s — nada a aprovar\n" % dirp)
        return 3
    p_plano = os.path.join(dirp, PLANO)
    if not os.path.isfile(p_plano):
        sys.stderr.write("qc-portao: %s não existe — a aprovação prende o plano, "
                         "e não há plano\n" % PLANO)
        return 3
    reg = {"schema": SCHEMA, "alvo": alvo,
           "render": os.path.basename(rend), "render_fingerprint": _fingerprint(rend),
           "plano": PLANO, "plano_sha256": _sha256_arquivo(p_plano),
           "em": _agora(), "por": por, "fonte": FONTE_CLI}
    if motivo:
        reg["motivo"] = motivo
    destino = os.path.join(dirp, ARQ_LOCAL)
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(destino)
    return 0


# ── saída ────────────────────────────────────────────────────────────────────
def imprimir(r):
    cab = "PORTAO %-16s %s" % (r["flag"], os.path.basename(r["dir"].rstrip("/")))
    print("%s · render %s · %d artefatos gráficos varridos, %d depois do corte"
          % (cab, r["render"] or "ausente", r["graficos_varridos"],
             len(r["graficos_apos_o_corte"])))
    for g in r["graficos_apos_o_corte"][:12]:
        print("   apos-o-corte %s" % g)
    if len(r["graficos_apos_o_corte"]) > 12:
        print("   apos-o-corte ... +%d" % (len(r["graficos_apos_o_corte"]) - 12))
    for m in r["motivos"]:
        print("   %s" % m)
    for a in r["avisos"]:
        sys.stderr.write("   aviso: %s\n" % a)
    if r["aprovacao"]:
        ap = r["aprovacao"]
        print("   aprovacao %s (origem %s) por %s em %s%s"
              % (ap["fonte"], ap.get("origem") or "—", ap["por"], ap["em"],
                 (" — %s" % ap["motivo"]) if ap.get("motivo") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--aprovar", action="store_true")
    ap.add_argument("--por")
    ap.add_argument("--alvo", default=ALVO_PADRAO)
    ap.add_argument("--motivo")
    ap.add_argument("--aceitar-degradado", action="store_true",
                    help="aceita aprovação que não nasceu do botão da UI. "
                         "É exceção declarada, não default: sem ela, aprovação "
                         "de CLI reprova (achado A10).")
    a = ap.parse_args(argv)

    if a.aprovar:
        if not a.por:
            ap.error("--aprovar exige --por <nome>: uma aprovação sem dono não é aprovação")
        return aprovar(a.dir, a.por, a.alvo, a.motivo)

    r = avaliar(a.dir, a.alvo, aceitar_degradado=a.aceitar_degradado)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        imprimir(r)
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
