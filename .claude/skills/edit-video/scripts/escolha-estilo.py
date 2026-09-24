#!/usr/bin/env python3
"""A ESCOLHA DE ESTILO da peça — valida, digere, consome e aplica (SPEC-19 §4.5).

    escolha-estilo.py <dir> --validar  <arquivo.json>   sai 1 com a violação nomeada
    escolha-estilo.py <dir> --resumo   <arquivo.json>   o digest (§3.9) no stdout
    escolha-estilo.py <dir> --consumir <arquivo|estilo> valida, digere, MOVE p/ aplicados/
    escolha-estilo.py <dir> --aplicar  <arquivo.json>   grava .preview/estilo-vigente.json

⚠️ NOME. Este script se chamava `estilo.py` na spec. `estilo.py` é da SPEC-24 (a
BIBLIOTECA de estilos do usuário, contrato `benchmark.estilo-usuario/v1`, com
subcomandos `listar/criar/resolver/promover/…`). São coisas diferentes com um
`validar` cada — quem executasse por último apagaria o outro em silêncio.

────────────────────────────────────────────────────────────────────────────────
AS DUAS REGRAS DELES QUE ESTE ARQUIVO EXISTE PARA HONRAR

1. **Caixa desmarcada é um NÃO explícito** (`ref-A/helpers/watch_edits.py:93-95`).
   O payload carrega o mapa COMPLETO de interruptores e o complemento dos
   grafismos; o digest imprime `fora:` com eles NOMEADOS. Mandar só os `true` é o
   que transforma ausência em silêncio — e silêncio, aqui, o agente lê como
   "tanto faz".

2. **Cor que ninguém pinta não é instrução** (`ref-A/SKILL.md:183-186`). Quando
   nenhum estilo escolhido tem `acento`, o digest diz "não se aplica" em vez de
   mandar o agente inventar um lugar para a cor. A diferença para eles: o fato
   mora no CATÁLOGO (`estilo.acento`, SPEC-19 §3.8), não numa lista espelhada à
   mão (`app.js:1051`, *"Mirrors the template — update both together"*).
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CONTRATO_V1 = "benchmark.edit-estilo/v1"
CONTRATO_V2 = "benchmark.edit-estilo/v2"
CONTRATO_V3 = "benchmark.edit-estilo/v3"
CONTRATO_VIGENTE = "benchmark.edit-estilo-vigente/v1"

SCRIPTS = Path(__file__).resolve().parent


def log(*a):
    print(*a, file=sys.stderr)


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _ler_json(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def dir_preview(dir_producao) -> Path:
    return Path(dir_producao) / ".preview"


def _desembrulhar(obj):
    """Envelope da SPEC-17 ou objeto cru — devolve o payload."""
    if isinstance(obj, dict) and obj.get("schema") == "benchmark.preview-evento/v1":
        return obj.get("payload") if isinstance(obj.get("payload"), dict) else None
    return obj if isinstance(obj, dict) else None


# ───────────────────────────────── validação ─────────────────────────────────
_TIPOS = {"str": str, "num": (int, float), "bool": bool, "list": list, "dict": dict}


def _tipo_ok(v, nome):
    if nome == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TIPOS[nome])


_OBRIG_V2 = {"contrato": "str", "salvo_em": "str", "revisao_base": "num"}
_OPC_V2 = {
    "fonte": "str", "rerender": "bool",
    "gramatica": "str", "gramatica_plano": "str", "tema": "str",
    "gancho": "str", "legenda": "str",
    "acento": "str", "acento_usado": "bool", "acento_onde": "list",
    "grafismos": "list", "grafismos_fora": "list",
    "elementos": "dict", "parametros": "dict",
    "observacao": "str", "perfil": "str", "catalogo_gerado_em": "str",
    # H49-4 (SPEC-49): a resposta do creator à oferta de aprendizado do estilo.
    # `{resposta: "sim"|"nao", estilo, comando, propostas: [path]}`. É REGISTRO,
    # não ação: nada aqui promove nada — o `estilo.py promover --confirmar`
    # continua sendo o único que escreve versão nova na biblioteca.
    "aprendizado": "dict",
}
_OBRIG_V3 = dict(_OBRIG_V2, direcao_edicao="dict")
_OPC_V3 = dict(_OPC_V2)
_OBRIG_V1 = {"contrato": "str", "salvo_em": "str", "revisao_base": "num"}
_OPC_V1 = {"rerender": "bool", "legenda": "str", "headline": "str",
           "acento": "str", "acento_usado": "bool", "elementos": "dict",
           "gramatica_plano": "str", "observacao": "str"}

FONTES = ("galeria", "chat")


def validar(obj, galeria=None) -> list[str]:
    """Devolve a lista de violações (vazia = ok). Nunca levanta por conteúdo.

    Aceita **v1, v2 e v3**. As versões anteriores continuam válidas de
    propósito: nenhum arquivo é apagado por causa de uma versão de contrato."""
    if not isinstance(obj, dict):
        return ["objeto tem que ser dict, veio %s" % type(obj).__name__]
    c = obj.get("contrato")
    if c not in (CONTRATO_V1, CONTRATO_V2, CONTRATO_V3):
        return ["contrato desconhecido: %r (esperado %s, %s ou %s)"
                % (c, CONTRATO_V3, CONTRATO_V2, CONTRATO_V1)]
    if c == CONTRATO_V3:
        obrig, opc = _OBRIG_V3, _OPC_V3
    elif c == CONTRATO_V2:
        obrig, opc = _OBRIG_V2, _OPC_V2
    else:
        obrig, opc = _OBRIG_V1, _OPC_V1
    erros: list[str] = []
    conhecidos = dict(obrig); conhecidos.update(opc)
    for k in sorted(obj):
        if k not in conhecidos:
            erros.append("campo desconhecido: %r" % k)
        elif obj[k] is not None and not _tipo_ok(obj[k], conhecidos[k]):
            erros.append("campo %r: esperado %s, veio %s"
                         % (k, conhecidos[k], type(obj[k]).__name__))
    for k in obrig:
        if k not in obj:
            erros.append("campo obrigatório ausente: %r" % k)
    if c == CONTRATO_V1:
        return erros

    if c == CONTRATO_V3:
        erros.extend(_validar_direcao_v3(obj))

    if obj.get("fonte") is not None and obj["fonte"] not in FONTES:
        erros.append("fonte %r fora de %s" % (obj["fonte"], list(FONTES)))
    ac = obj.get("acento")
    if isinstance(ac, str) and not _hex_ok(ac):
        erros.append("acento %r não é #RRGGBB" % ac)

    # 🔴 As duas coerências que só o payload INTEIRO sabe, e que são a razão de
    # `acento_usado` ser DERIVADO. Aceitar `acento_usado: true` com `acento_onde`
    # vazio é aceitar a lista paralela de volta, por outra porta.
    usado, onde = obj.get("acento_usado"), obj.get("acento_onde")
    if isinstance(usado, bool) and isinstance(onde, list):
        if usado and not onde:
            erros.append("acento_usado: true com acento_onde vazio — se ninguém "
                         "pinta, não é usado (é derivado, §3.8)")
        if not usado and onde:
            erros.append("acento_usado: false com acento_onde %s — contradição" % onde)
    for g in obj.get("acento_onde") or []:
        if g not in ("legenda", "gancho", "grafismo", "gramatica", "tema"):
            erros.append("acento_onde: grupo desconhecido %r" % g)
    juntos = set(obj.get("grafismos") or []) & set(obj.get("grafismos_fora") or [])
    if juntos:
        erros.append("slug em `grafismos` E em `grafismos_fora`: %s" % sorted(juntos))

    if galeria:
        erros.extend(_conferir_contra_galeria(obj, galeria))
    return erros


def _validar_direcao_v3(obj: dict) -> list[str]:
    """Valida a decisão de acabamento e as coerências que o payload inteiro sabe."""
    e: list[str] = []
    d = obj.get("direcao_edicao")
    if not isinstance(d, dict):
        return e  # o erro de tipo/ausência já foi produzido pelo schema acima
    campos = {"modo", "densidade", "sfx"}
    faltam = campos - set(d)
    sobram = set(d) - campos
    if faltam:
        e.append("direcao_edicao: campos obrigatórios ausentes: %s" % sorted(faltam))
    if sobram:
        e.append("direcao_edicao: campos desconhecidos: %s" % sorted(sobram))

    # Tuplas, e não sets: um JSON malformado pode trazer list/dict no lugar da
    # string. A validação deve nomear o erro, nunca levantar TypeError por hash.
    modos = ("essencial", "animada", "surpresa")
    densidades = ("leve", "equilibrada", "alta")
    sfxs = ("automatico", "sem-sfx")
    if d.get("modo") not in modos:
        e.append("direcao_edicao.modo %r fora de %s" % (d.get("modo"), sorted(modos)))
    if d.get("densidade") not in densidades:
        e.append("direcao_edicao.densidade %r fora de %s"
                 % (d.get("densidade"), sorted(densidades)))
    if d.get("sfx") not in sfxs:
        e.append("direcao_edicao.sfx %r fora de %s" % (d.get("sfx"), sorted(sfxs)))

    elementos = obj.get("elementos")
    if isinstance(elementos, dict) and isinstance(elementos.get("sfx"), bool) \
            and d.get("sfx") in sfxs:
        esperado = "automatico" if elementos["sfx"] else "sem-sfx"
        if d["sfx"] != esperado:
            e.append("direcao_edicao.sfx %r contradiz elementos.sfx=%r; esperado %r"
                     % (d["sfx"], elementos["sfx"], esperado))

    if d.get("modo") == "essencial":
        if d.get("densidade") != "leve":
            e.append("direção essencial exige densidade 'leve'")
        if d.get("sfx") != "sem-sfx":
            e.append("direção essencial exige sfx 'sem-sfx'")
        if obj.get("grafismos"):
            e.append("direção essencial não aceita grafismos")
        if obj.get("gancho"):
            e.append("direção essencial não aceita gancho animado")
        if obj.get("gramatica") not in (None, "plano-fixo"):
            e.append("direção essencial exige gramatica 'plano-fixo'")
        if obj.get("gramatica_plano") not in (None, "fixa"):
            e.append("direção essencial exige gramatica_plano 'fixa'")
        if isinstance(elementos, dict):
            animados = [k for k in ("sfx", "split_broll", "flash_no_corte", "tracking")
                        if elementos.get(k) is True]
            if animados:
                e.append("direção essencial exige interruptores de animação/SFX desligados: %s"
                         % animados)
    return e


def _hex_ok(v) -> bool:
    return (isinstance(v, str) and len(v) == 7 and v[0] == "#"
            and all(ch in "0123456789abcdefABCDEF" for ch in v[1:]))


def _indice(galeria: dict) -> dict:
    ix = {}
    for g in galeria.get("grupos") or []:
        for e in g.get("estilos") or []:
            ix[e["slug"]] = dict(e, _grupo=g["id"])
    return ix


def _conferir_contra_galeria(obj: dict, galeria: dict) -> list[str]:
    """O vocabulário é do CATÁLOGO. Um slug inventado tem que morrer aqui, não na
    hora em que o agente for montar a Fase 2 e não achar o componente."""
    e: list[str] = []
    ix = _indice(galeria)
    for campo, grupo in (("gramatica", "gramatica"), ("tema", "tema"),
                         ("gancho", "gancho"), ("legenda", "legenda")):
        slug = obj.get(campo)
        if not slug:
            continue
        alvo = ix.get(slug)
        if alvo is None:
            e.append("%s: slug %r não está na galeria deste perfil" % (campo, slug))
        elif alvo["_grupo"] != grupo:
            e.append("%s: %r é do grupo %r" % (campo, slug, alvo["_grupo"]))
        elif alvo.get("estado") == "candidato":
            e.append("%s: %r é candidato e não pode ser escolhido (%s)"
                     % (campo, slug, (alvo.get("bloqueio") or "")[:60]))
    for slug in obj.get("grafismos") or []:
        alvo = ix.get(slug)
        if alvo is None or alvo["_grupo"] != "grafismo":
            e.append("grafismos: %r não é grafismo oferecido neste perfil" % slug)
        elif alvo.get("estado") == "candidato":
            e.append("grafismos: %r é candidato" % slug)

    # o mapa COMPLETO de interruptores (§3.9-1)
    ids = {i["id"] for i in galeria.get("interruptores") or []}
    tem = set((obj.get("elementos") or {}).keys())
    faltam = ids - tem
    if faltam:
        e.append("elementos: mapa INCOMPLETO, faltam %s — caixa desmarcada é um "
                 "NÃO explícito e precisa vir como false" % sorted(faltam))
    sobra = tem - ids
    if sobra:
        e.append("elementos: id fora de interruptores.json: %s" % sorted(sobra))

    esperado = derivar_acento(obj, galeria)
    if isinstance(obj.get("acento_usado"), bool) and obj["acento_usado"] != esperado["acento_usado"]:
        e.append("acento_usado: %r, mas os estilos escolhidos dizem %r "
                 "(derive, não declare)" % (obj["acento_usado"], esperado["acento_usado"]))
    if isinstance(obj.get("acento_onde"), list) and sorted(obj["acento_onde"]) != sorted(esperado["acento_onde"]):
        e.append("acento_onde: %s, mas o catálogo diz %s"
                 % (sorted(obj["acento_onde"]), esperado["acento_onde"]))
    return e


# ─────────────────────── §3.8 — acento_usado é DERIVADO ───────────────────────
def derivar_acento(obj: dict, galeria: dict) -> dict:
    """`acento_usado = escolhidos.some(e => e.acento)`. Uma linha, dono único.

    O ref-A guarda o mesmo fato numa segunda lista (`ACCENT_USERS`, `app.js:1051`)
    com o comentário "update both together". Aqui não há o que sincronizar: quem
    pinta está declarado na entrada do catálogo, e quem escolheu está no payload."""
    ix = _indice(galeria)
    onde, params = [], {}
    escolhidos = [obj.get(c) for c in ("gramatica", "tema", "gancho", "legenda")]
    escolhidos += list(obj.get("grafismos") or [])
    for slug in escolhidos:
        if not slug:
            continue
        e = ix.get(slug)
        if e and e.get("acento"):
            g = e["_grupo"]
            if g not in onde:
                onde.append(g)
            params[slug] = e["acento"]["param"]
    ordem = ["gramatica", "tema", "gancho", "legenda", "grafismo"]
    onde.sort(key=lambda g: ordem.index(g) if g in ordem else 99)
    return {"acento_usado": bool(onde), "acento_onde": onde, "params": params}


# ───────────────────────────────── o digest ─────────────────────────────────
_ROTULO_GRUPO = {"gramatica": "gramática de plano", "tema": "tema",
                 "gancho": "gancho", "legenda": "legenda"}


def resumo(obj: dict, galeria: dict | None = None) -> str:
    """O digest que o agente lê. Depende SÓ do payload (+ a galeria, quando ela
    existe, para traduzir slug → nome humano)."""
    if obj.get("contrato") == CONTRATO_V1:
        return _resumo_v1(obj)
    ix = _indice(galeria) if galeria else {}

    def rotulo(slug):
        e = ix.get(slug)
        return "%s (%s)" % (e["nome"], slug) if e else slug

    # 🔴 O CABEÇALHO NÃO PODE AFIRMAR PROCEDÊNCIA QUE NÃO HOUVE (achado R-6,
    # 2026-08-11). Ele dizia "ESTILO ESCOLHIDO NA GALERIA" para todo payload que
    # não fosse `rerender`, inclusive um `fonte: "chat"` sem galeria nenhuma no
    # disco. O digest é o que o agente lê para montar a Fase 2, e ele estava
    # dizendo, com a autoridade de uma medição, que o creator viu os previews e
    # apontou — quando ninguém viu nada. `fonte` já existe no contrato (é `str`,
    # em `FONTES`) e é ela quem responde.
    fonte = obj.get("fonte")
    if obj.get("rerender"):
        cab = "TROCA DE ESTILO (na galeria)" if fonte == "galeria" else \
              "TROCA DE ESTILO (fonte: %s)" % (fonte or "não declarada")
    elif fonte == "galeria":
        cab = "ESTILO ESCOLHIDO NA GALERIA"
    elif fonte:
        cab = "ESCOLHA SEM GALERIA (fonte: %s)" % fonte
    else:
        cab = "ESCOLHA COM PROCEDÊNCIA NÃO DECLARADA (sem campo `fonte`)"
    L = ["%s (%s) — monte a Fase 2 assim:" % (cab, obj.get("salvo_em") or "—")]
    direcao = obj.get("direcao_edicao")
    if isinstance(direcao, dict):
        nomes = {"essencial": "essencial", "animada": "com animações",
                 "surpresa": "me surpreenda"}
        L.append("  · acabamento: %s · densidade: %s · SFX: %s"
                 % (nomes.get(direcao.get("modo"), direcao.get("modo")),
                    direcao.get("densidade"), direcao.get("sfx")))
    for campo in ("gramatica", "tema", "gancho", "legenda"):
        if obj.get(campo):
            linha = "  · %s: %s" % (_ROTULO_GRUPO[campo], rotulo(obj[campo]))
            if campo == "gramatica":
                # 🔴 gramática mexe no CORTE, não na camada gráfica: aceitar
                # implica REMONTAR. É a ressalva da SPEC-16 §4.3, impressa no
                # lugar em que o agente vai ler.
                gp = obj.get("gramatica_plano")
                linha += ("  → remontagem: ritmo.gramatica_plano = %r" % gp) if gp else \
                         "  → NÃO é gramática de plano: liga o split-broll.py e a " \
                         "gramática fica no default do perfil"
            L.append(linha)
            # 🔴 O ELO DO TRACKING CHEGA A QUEM MONTA (achado A19/R-20i,
            # 2026-08-11). `punch-pontual` é a única gramática com zoom, e
            # `CameraSegue` não move nada sem zoom — por isso é ela que "liga" o
            # interruptor `tracking` (`previews-peca.py:141-142`). Só que o
            # digest caía na ramificação genérica acima e a instrução saía sem o
            # dado NOVO do card: o agente lia "ritmo.gramatica_plano =
            # 'punch-pontual'" e não tinha como saber que existe um arquivo de
            # rastreio a gerar nem um prop por onde ligá-lo. Dois ganchos
            # pendurados (`liga` no catálogo, `elementos.tracking` no payload) e
            # nenhuma frase juntando os dois.
            if campo == "gramatica" and obj.get("gramatica") == "punch-pontual" \
                    and (obj.get("elementos") or {}).get("tracking"):
                L.append("      ↳ tracking LIGADO: rode `rastrear-rosto.py "
                         "<dir>` antes de montar (grava track-rosto.json, "
                         "contrato benchmark.track-rosto/v1) e passe o track "
                         "para o punch por `MotionKit.CameraSegue track=`. "
                         "Sem isso o zoom fica no centro do quadro.")
            elif campo == "gramatica" and obj.get("gramatica") == "punch-pontual":
                L.append("      ↳ tracking DESLIGADO: o punch é no centro do "
                         "quadro. Se quem fala se move, é aqui que a cabeça sai "
                         "de enquadramento — ligue `tracking` na galeria para o "
                         "punch seguir o rosto.")

    der = derivar_acento(obj, galeria) if galeria else {
        "acento_usado": bool(obj.get("acento_usado")),
        "acento_onde": obj.get("acento_onde") or []}
    if obj.get("acento"):
        if der["acento_usado"]:
            L.append("  · cor de destaque: %s (aplicada %s)"
                     % (obj["acento"], _lista_pt(der["acento_onde"])))
        else:
            # a regra deles, literal (`ref-A/SKILL.md:183-186`)
            L.append("  · cor de destaque: não se aplica (os estilos escolhidos "
                     "não usam destaque) — não invente um lugar para ela")

    graf = obj.get("grafismos") or []
    L.append("  · grafismos liberados: %s" % (", ".join(graf) or "—"))
    fora_g = obj.get("grafismos_fora") or []
    if fora_g:
        L.append("  · grafismos FORA: %s" % ", ".join(fora_g))

    el = obj.get("elementos") or {}
    dentro = [k for k in sorted(el) if el[k]]
    fora = [k for k in sorted(el) if not el[k]]
    L.append("  · interruptores: %s" % (", ".join(dentro) or "—"))
    # caixa desmarcada é um NÃO EXPLÍCITO, não silêncio (watch_edits.py:93-95)
    L.append("  · fora: %s" % (", ".join(fora) or "—"))

    par = obj.get("parametros") or {}
    for slug in sorted(par):
        pares = ", ".join("%s=%s" % (k, par[slug][k]) for k in sorted(par[slug]))
        L.append("  · ajuste em %s: %s" % (slug, pares))
    if obj.get("observacao"):
        L.append("  · observação do usuário: %s" % obj["observacao"])
    # H49-4: a resposta ao aprendizado chega a QUEM MONTA, com o comando exato.
    # Sem esta linha o "sim" do creator morria no JSON — a mesma classe de elo
    # perdido que o `liga` do tracking (A19).
    ap = obj.get("aprendizado") or {}
    if ap.get("resposta") == "sim":
        L.append("  🌱 o creator DISSE SIM a virar padrão o que o estilo propôs "
                 "(%s). NADA foi promovido: rode, se concordar, `%s`"
                 % (", ".join(ap.get("propostas") or []) or "—",
                    ap.get("comando") or "estilo.py promover <ref> --confirmar"))
    elif ap.get("resposta") == "nao":
        L.append("  🌱 o creator disse NÃO à promoção: a escolha vale só nesta "
                 "peça e o estilo dele não muda")
    return "\n".join(L)


_ARTIGO = {"gramatica": "na", "tema": "no", "gancho": "no",
           "legenda": "na", "grafismo": "nos"}


def _lista_pt(gs):
    if not gs:
        return "em lugar nenhum"
    pecas = ["%s %s" % (_ARTIGO.get(g, "no"), _ROTULO_GRUPO.get(g, g + "s")) for g in gs]
    if len(pecas) == 1:
        return pecas[0]
    return ", ".join(pecas[:-1]) + " e " + pecas[-1]


def _resumo_v1(obj: dict) -> str:
    L = ["ESTILO (contrato v1, sem vocabulário de catálogo) — rerender: %s"
         % ("sim" if obj.get("rerender") else "não")]
    L.append("  · legenda: %s · gancho: %s"
             % (obj.get("legenda") or "—", obj.get("headline") or "—"))
    el = obj.get("elementos") or {}
    L.append("  · interruptores: %s" % (", ".join(k for k in sorted(el) if el[k]) or "—"))
    L.append("  · fora: %s" % (", ".join(k for k in sorted(el) if not el[k]) or "—"))
    return "\n".join(L)


def migrar_v1(obj: dict) -> dict:
    """v1 → v2 sem perder nada: `headline` vira `gancho` e o aviso fica no objeto.

    Nada é apagado — a tabela da §4.2 diz que v1 continua válido."""
    novo = {k: v for k, v in obj.items() if k != "headline"}
    novo["contrato"] = CONTRATO_V2
    if obj.get("headline"):
        novo["gancho"] = obj["headline"]
    novo["fonte"] = "chat"
    return novo


# ────────────────────────── consumir / aplicar ──────────────────────────
def _galeria(dir_producao):
    return _ler_json(dir_preview(dir_producao) / "estilos" / "galeria.json")


def _avisar_sem_galeria(dir_producao, gal, onde, pedido=False):
    """🔴 ACHADO A17: SEM GALERIA, ESTE SCRIPT VALIDA MENOS — E CALAVA.

    `validar()` confere o vocabulário (os slugs existem? são do perfil desta
    peça?) contra a `galeria.json`. Sem ela no disco, essa metade da validação
    simplesmente não roda: um slug inventado no chat passa e vira
    `estilo-vigente.json`, e a Fase 2 renderiza com um estilo que não existe.

    O aviso existia — só que só no `--validar`, que é o caminho que ninguém usa
    quando está com pressa. Agora ele sai nos DOIS caminhos que APLICAM.

    ⚠️ `pedido=True` quando a ausência foi PEDIDA por `--sem-galeria` (achado
    R-6/N3, 2026-08-11: a flag existia no help e era calculada em `_cli`, e
    `consumir()`/`aplicar()` a ignoravam — liam a galeria do disco de qualquer
    jeito). Uma flag que o help promete e o código descarta é pior que flag
    nenhuma: quem a usa acredita ter desligado algo. Agora ela desliga de
    verdade, e o aviso diz que foi de propósito — porque suprimir a conferência
    A PEDIDO ainda deixa o mesmo buraco no resultado."""
    if gal:
        return
    if pedido:
        log("⚠️  --sem-galeria: vocabulário NÃO conferido, por pedido explícito.")
        log("    %s aceita qualquer slug nesta execução — inclusive um que não" % onde)
        log("    existe no catálogo, e a Fase 2 renderizaria com ele.")
        return
    log("⚠️  sem galeria.json em %s: vocabulário NÃO conferido."
        % (dir_preview(dir_producao) / "estilos"))
    log("    %s aceita qualquer slug — inclusive um que não existe no catálogo," % onde)
    log("    e a Fase 2 renderizaria com ele. Construa a galeria antes:")
    log("      previews-peca.py %s --somente-defaults" % dir_producao)


def consumir(dir_producao, alvo, sem_galeria=False) -> dict:
    """Valida, digere e MOVE de `pendentes/` para `aplicados/`. O ACK é o MOVE.

    Funciona STANDALONE: se as duas edições no `estado.py` (§4.5) não tiverem
    sido feitas, este caminho continua completo. A degradação é de ergonomia."""
    prev = dir_preview(dir_producao)
    p = Path(alvo)
    if not p.exists():
        cands = sorted((prev / "pendentes").glob("*-%s-*.json" % alvo)) if (prev / "pendentes").is_dir() else []
        cands = [c for c in cands if not c.name.endswith(".parcial")]
        if not cands:
            sys.exit("nada em pendentes/ do tipo %r em %s" % (alvo, dir_producao))
        p = cands[-1]
    bruto = _ler_json(p)
    pay = _desembrulhar(bruto)
    if pay is None:
        sys.exit("%s não é envelope nem objeto de estilo" % p)
    gal = None if sem_galeria else _galeria(dir_producao)
    _avisar_sem_galeria(dir_producao, gal, "consumir", pedido=sem_galeria)
    erros = validar(pay, gal)
    if erros:
        sys.exit("%s VIOLA o contrato (%d):\n  %s" % (p, len(erros), "\n  ".join(erros)))
    apl = prev / "aplicados"
    apl.mkdir(parents=True, exist_ok=True)
    destino = apl / p.name
    corpo = bruto if isinstance(bruto, dict) and bruto.get("schema") else {
        "schema": "benchmark.preview-evento/v1", "tipo": "estilo",
        "salvo_em": pay.get("salvo_em") or "",
        "origem": {"ua": "arquivo cru (sem servidor)"}, "payload": pay}
    corpo = dict(corpo)
    corpo["aplicado_em"] = _agora()
    _escrever_atomico(destino, corpo)
    if p.resolve() != destino.resolve():
        p.unlink()
    return {"payload": pay, "destino": str(destino), "resumo": resumo(pay, gal)}


def aplicar(dir_producao, alvo, sem_galeria=False) -> str:
    """Grava `.preview/estilo-vigente.json`. Escrito SÓ aqui — nunca pela tela,
    nunca pelo servidor. É ele que faz o portão continuar aberto depois da Fase 2
    (§3.10), sem inventar campo novo no contrato da SPEC-16."""
    bruto = _ler_json(alvo)
    pay = _desembrulhar(bruto)
    if pay is None:
        sys.exit("%s não é envelope nem objeto de estilo" % alvo)
    gal = None if sem_galeria else _galeria(dir_producao)
    _avisar_sem_galeria(dir_producao, gal, "aplicar", pedido=sem_galeria)
    erros = validar(pay, gal)
    if erros:
        sys.exit("%s VIOLA o contrato (%d):\n  %s" % (alvo, len(erros), "\n  ".join(erros)))
    est = _ler_json(dir_preview(dir_producao) / "estado.json", {}) or {}
    obj = {
        "contrato": CONTRATO_VIGENTE,
        "aplicado_em": _agora(),
        "revisao_aplicada": est.get("revisao"),
        "origem": os.path.relpath(str(alvo), str(dir_producao)),
        "estilo": pay,
    }
    destino = dir_preview(dir_producao) / "estilo-vigente.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    _escrever_atomico(destino, obj)
    _casar_galeria(dir_producao, obj)
    pend = _remontagem_pendente(dir_producao, pay)
    if pend:
        # 🔴 MEIA-APLICAÇÃO SILENCIOSA É PIOR QUE ERRO (2026-08-12, H48-7/A-5).
        # Medido em campo: o digest imprime "gramática de plano: Plano alternado
        # → remontagem: ritmo.gramatica_plano = 'alternada'", o `--aplicar` grava
        # `estilo-vigente.json` e o `galeria.json`... e o `perfil.json` fica
        # INTOCADO. O zoom/cx/cy nunca chegam à EDL, a peça é montada com a
        # gramática antiga, e a escolha mais cara da galeria — a única que
        # REMONTA — é justamente a que não se aplica. Ninguém é avisado.
        #
        # Este script NÃO remonta de propósito: remontar é decisão de custo
        # (minutos de render) e mexe na EDL, que é o artefato mais caro da
        # produção. Então ele sai ≠0 com os comandos EXATOS que faltam — o
        # arquivo já está gravado, e a saída diz o que ainda não aconteceu.
        print("⚠️ APLICAÇÃO INCOMPLETA: o estilo foi gravado, mas esta escolha "
              "pede REMONTAGEM e o perfil da produção não a tem.", file=sys.stderr)
        for campo, valor, atual in pend:
            print("   · %s = %r  (perfil.json diz %r)" % (campo, valor, atual),
                  file=sys.stderr)
        print("   Rode, nesta ordem, e a escolha passa a valer de verdade:",
              file=sys.stderr)
        print("     python3 $S/perfil.py resolver %s %s"
              % (os.path.relpath(str(dir_producao)) or ".",
                 " ".join("--set %s=%s" % (c, v) for c, v, _a in pend)),
              file=sys.stderr)
        print("     bash    $S/montar.sh %s"
              % (os.path.relpath(str(dir_producao)) or "."), file=sys.stderr)
    # ⚠️ o EXIT é do CLI, não daqui: `aplicar()` é chamado como biblioteca pelos
    # testes e pelo servidor, e um `sys.exit` no meio de uma função de biblioteca
    # mata o processo de quem chamou. A função AVISA; quem decide o código de
    # saída é o `main`.
    return str(destino)


# Os campos do estilo que só existem depois de uma REMONTAGEM: eles mudam a EDL
# ou o corte, não a camada gráfica. `gramatica_plano` é o caso medido (A-5); a
# lista é dado para poder crescer sem mexer no fluxo.
CAMPOS_QUE_REMONTAM = (("gramatica_plano", "ritmo.gramatica_plano"),)


def _remontagem_pendente(dir_producao, estilo):
    """[(campo_do_perfil, valor_pedido, valor_atual)] do que o perfil ainda não tem."""
    p = Path(dir_producao) / "perfil.json"
    perfil = _ler_json(p, {}) or {}
    pend = []
    for chave, campo in CAMPOS_QUE_REMONTAM:
        pedido = estilo.get(chave)
        if not pedido:
            continue
        no = perfil
        for parte in campo.split("."):
            no = no.get(parte) if isinstance(no, dict) else None
        if no != pedido:
            pend.append((campo, pedido, no))
    return pend


def _casar_galeria(dir_producao, vigente) -> bool:
    """Espelha o vigente no `galeria.json` que a TELA já tem carregado.

    🔴 Achado R-3 (2026-08-11). `galeria.js:148` lê `jaTemEstilo()` de
    `S.dados.vigente`, ou seja do `galeria.json` — e o ÚNICO escritor daquele
    campo era o regen completo do `previews-peca.py`, que lê
    `estilo-vigente.json` na hora de montar o arquivo. Quem aplicasse um estilo
    sem regenerar a galeria deixava `vigente: null` no disco, e a segunda escolha
    chegava ao watcher com `rerender: false` — indistinguível da primeira. O
    marcador `🔁 REFAÇA` nunca era emitido.

    Regenerar a galeria aqui seria caro (renderiza previews) e errado (este
    script não decide o catálogo). Escrever UM campo do arquivo que já existe é o
    mínimo: se a galeria não foi construída, não há o que casar e a função é
    silêncio — a ausência de instância não é erro.
    """
    p = dir_preview(dir_producao) / "estilos" / "galeria.json"
    gal = _ler_json(p)
    if not isinstance(gal, dict):
        return False
    gal["vigente"] = vigente
    _escrever_atomico(p, gal)
    log("galeria.json: campo `vigente` atualizado — a aba ESTILO continua "
        "alcançável e a próxima escolha chega como REFAÇA")
    return True


def _escrever_atomico(destino: Path, obj) -> None:
    destino = Path(destino)
    tmp = destino.with_name(destino.name + ".%d.parcial" % os.getpid())
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, destino)


# ─────────────────────────────────── CLI ───────────────────────────────────
def _cli(argv=None):
    ap = argparse.ArgumentParser(
        description="A escolha de estilo da peça (SPEC-19). Escreve SÓ dentro de "
                    "<dir-producao>/.preview/.")
    ap.add_argument("dir")
    ap.add_argument("--validar", metavar="ARQUIVO.json")
    ap.add_argument("--resumo", metavar="ARQUIVO.json")
    ap.add_argument("--consumir", metavar="ARQUIVO|estilo")
    # (o `--aplicar` e o `--consumir` também respeitam `--sem-galeria`; ver a
    #  nota em `_avisar_sem_galeria`)
    ap.add_argument("--aplicar", metavar="ARQUIVO.json")
    ap.add_argument("--sem-galeria", action="store_true",
                    help="não confere o vocabulário contra galeria.json. Vale nos "
                         "QUATRO caminhos (--validar, --resumo, --consumir, "
                         "--aplicar) e sempre imprime o aviso de que a metade da "
                         "validação que depende do catálogo não rodou.")
    a = ap.parse_args(argv)
    gal = None if a.sem_galeria else _galeria(a.dir)

    if a.validar:
        alvo = sys.stdin if a.validar == "/dev/stdin" else a.validar
        obj = _desembrulhar(json.load(alvo) if alvo is sys.stdin else _ler_json(alvo))
        if obj is None:
            sys.exit("não consegui ler JSON de %s" % a.validar)
        erros = validar(obj, gal)
        alcance = ("payload + %d slugs da galeria" % len(_indice(gal))) if gal else \
                  "payload (sem galeria.json ao lado: vocabulário NÃO conferido)"
        log("varri %s" % alcance)
        if erros:
            print("%s: %d violação(ões)" % (a.validar, len(erros)), file=sys.stderr)
            for x in erros:
                print("  ✗ %s" % x, file=sys.stderr)
            return 1
        log("  ✓ 0 violações (%s)" % obj.get("contrato"))
        print(a.validar)
        return 0

    if a.resumo:
        obj = _desembrulhar(_ler_json(a.resumo))
        if obj is None:
            sys.exit("não consegui ler JSON de %s" % a.resumo)
        print(resumo(obj, gal))
        return 0

    if a.consumir:
        r = consumir(a.dir, a.consumir, sem_galeria=a.sem_galeria)
        print(r["resumo"])
        log("→ %s" % r["destino"])
        return 0

    if a.aplicar:
        destino = aplicar(a.dir, a.aplicar, sem_galeria=a.sem_galeria)
        print(destino)
        # H48-7: escolha que pede remontagem e não foi remontada sai ≠0. Nunca
        # meia-aplicação silenciosa.
        pay = _desembrulhar(_ler_json(a.aplicar))
        if pay and _remontagem_pendente(a.dir, pay):
            return 4
        return 0
        return 0

    ap.error("informe --validar, --resumo, --consumir ou --aplicar")


if __name__ == "__main__":
    sys.exit(_cli())
