#!/usr/bin/env python3
"""estilo.py — a biblioteca de estilos DO USUÁRIO (SPEC-24).

Um *perfil de peça* (SPEC-00) descreve o TIPO DE PEÇA e é do produto. Um *estilo*
descreve COMO ESTE USUÁRIO QUER QUE A PEÇA FIQUE, dentro do que o perfil permite,
e é dele: privado, nomeado, versionado, exportável.

    perfil  = formato   (1080×1920, 30 fps, 48 kHz, zonas de UI do feed)
    estilo  = look e ritmo dentro daquele formato  (pads, grade, legenda, picks)

A REGRA QUE NÃO SE NEGOCIA
    Um estilo NUNCA escreve formato. `perfil_overrides` é *allowlist*
    (`estilos/_escopo.json`), não denylist: caminho fora dela é ERRO com o
    caminho na mensagem e o comando pronto — nunca campo ignorado em silêncio.
    Uma denylist esqueceria o campo que a próxima spec criar.

A PRECEDÊNCIA (§3.4) — a de cima vence, CAMPO A CAMPO
    0  invariantes físicos      48000 % fps == 0 · soma_audio == soma_video
    1  perfil de peça           perfis/_base.json → perfis/<nome>.json   (tudo)
    2  defaults do catálogo     catalogo.json `defaultDe`   (só os `picks`)
    3  estilo do usuário        estilos/<u>/<slug>/         (escopo)
    4  escolha pontual da UI    .preview/aplicados/*.json   (escopo, esta peça)
    5  pedido em texto          compilado em diff explícito (escopo, esta peça)
    Camada ausente NÃO EXISTE: não vira null, não zera nada.

BIBLIOTECA (o que perfil.py e os outros importam)
    camada_para_perfil(ref)  -> (rotulo, perfil_overrides, sha256, escopo)
    resolver_estilo(ref)     -> (estilo mesclado com o pai, meta)
    escopo()                 -> dict do estilos/_escopo.json
    dir_estilos()            -> raiz da biblioteca

CLI
    estilo.py listar   [--usuario U]
    estilo.py mostrar  <u>/<slug>[@vNNN] [--usuario U]
    estilo.py criar    <u>/<slug> --nome "…" --perfis reels[,vsl]
                       [--de-perfil <n>] [--de-producao <dir>] [--de-receita <f>]
                       [--herda <u>/<slug>] [--nota "…"]
    estilo.py resolver <dir> --perfil <n> [--usuario U] [--estilo <u>/<slug>[@vNNN]]
                       [--como-gravado] [--set k.k2=v]… [--pedido-compilado <f>]
    estilo.py pedido   <dir> "texto em português"      # compila, NÃO aplica
    estilo.py sinais   <dir> [--estilo <u>/<slug>]
    estilo.py propor   <u>/<slug> [--primeira-peca <dir>]     # NÃO escreve
    estilo.py promover <u>/<slug> --confirmar [--so p1,p2] [--por <quem>]
    estilo.py diff     <u>/<slug>@vA @vB
    estilo.py exportar <u>/<slug>[@vNNN] --saida <arquivo>
    estilo.py importar <arquivo> --usuario U [--slug s]
    estilo.py validar  <arquivo | <u>/<slug>>
    estilo.py escopo   [--conferir]

ONDE A BIBLIOTECA MORA (FRONTEIRA orientação 11b)
    $BENCH_ESTILOS_DIR → $PWD/estilos (só quando há MANIFESTO.json na raiz OU já
    existe biblioteca aí) → ${ILHA_HOME:-~/.ilha}/estilos.
    Dado de usuário mora em $ILHA_HOME: senão reinstalar apaga a biblioteca dele.

Contrato de I/O do repo: caminho do artefato no stdout, logs no stderr.
Zero dependência externa (nem `jsonschema`, que não existe nesta máquina — a
SPEC-23 mediu): o validador do fim do arquivo cobre o subconjunto de JSON Schema
que `_schema-estilo.json` usa.
"""
import copy
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys

CONTRATO = "benchmark.estilo-usuario/v1"
CONTRATO_ESCOPO = "benchmark.estilo-escopo/v1"
CONTRATO_RESOLVIDO = "benchmark.estilo-resolvido/v1"
CONTRATO_SINAL = "benchmark.estilo-sinal/v1"
CONTRATO_UPERFIL = "benchmark.estilo-usuario-perfil/v1"
CONTRATO_PEDIDO = "benchmark.estilo-pedido/v1"
CONTRATO_EXPORT = "benchmark.estilo-export/v1"

CONTRATO_UI_ESTILO = "benchmark.edit-estilo/v1"
# 🔴 O CONTRATO QUE A GALERIA REALMENTE GRAVA (achado da SPEC-41). A UI da SPEC-19
# salva `v2` — vocabulário de catálogo — e este arquivo só conhecia `v1`. Efeito
# medido: `eventos_ui()` pulava TODO evento real, `sinais` imprimia "0 evento(s)
# lidos" e saía exit 0. Os cinco `sinais.jsonl` da biblioteca estavam com 0 bytes,
# e a leitura óbvia ("ninguém usou a UI ainda") era falsa: os eventos existiam no
# disco, e o colhedor não os enxergava. `escolha-estilo.py` e `estado.py` já
# tratavam os dois; era só aqui que faltava.
CONTRATO_UI_ESTILO_V2 = "benchmark.edit-estilo/v2"
# v3 preserva o vocabulário visual do v2 e acrescenta a direção de acabamento
# da peça. A direção não vira preferência global: ela é uma autorização desta
# produção e é executada pelo plano visual, não pela biblioteca de estilos.
CONTRATO_UI_ESTILO_V3 = "benchmark.edit-estilo/v3"
CONTRATO_UI_AJUSTES = "benchmark.edit-ajustes/v1"
CONTRATO_RECEITA = "benchmark.edit-recipe/v1"
CONTRATO_EXTRAIDO = "benchmark.estilo-edicao/v1"      # saída da SPEC-23

DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))

RE_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_VERSAO = re.compile(r"^v\d{3}$")
RE_REF = re.compile(r"^([A-Za-z0-9_-]+)/([a-z0-9-]+)(?:@(v\d{3}))?$")
# §3.8 trava 3: um estilo é CONFIGURAÇÃO, não pacote. Nada de binário no export.
RE_BINARIO = re.compile(r"\.(ttf|otf|woff2?|cube|3dl|wav|mp3|mp4|mov|png|jpe?g)$", re.I)


class ErroEstilo(Exception):
    pass


# ─────────────────────────────────────────────────────────── perfil.py ao lado
def _perfil():
    """Importa o perfil.py que está AO LADO deste arquivo (a cadeia de merge é
    dele; esta spec insere UMA camada nela e não reimplementa merge nenhum)."""
    if not hasattr(_perfil, "_mod"):
        alvo = os.path.join(DIR_SCRIPT, "perfil.py")
        spec = importlib.util.spec_from_file_location("_perfil_spec00", alvo)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _perfil._mod = mod
    return _perfil._mod


# ───────────────────────────────────────────────────────────── onde a lib mora
def ilha_home():
    return os.environ.get("ILHA_HOME") or os.path.join(os.path.expanduser("~"), ".ilha")


def dir_estilos(criar=False):
    """FRONTEIRA orientação 11b, em três linhas e nesta ordem:

    1. `$BENCH_ESTILOS_DIR`, se definido — a palavra final é sempre do usuário;
    2. `$PWD/estilos`, mas SÓ quando estamos na árvore de desenvolvimento: há
       `MANIFESTO.json` na raiz (o marcador da SPEC-22) ou já existe biblioteca
       aqui (`estilos/_escopo.json`), que é o caso deste repo hoje, antes da 22;
    3. `${ILHA_HOME:-~/.ilha}/estilos`.

    🔴 O default É o item 3, e isso importa: dado de usuário dentro do diretório
    de instalação some no `reinstalar`. A regra 2 existe para o repo de
    desenvolvimento continuar tendo a biblioteca versionada onde a §5 a declara,
    e some sozinha na máquina de um cliente (que não tem nem MANIFESTO.json nem
    biblioteca dentro do $PWD)."""
    v = os.environ.get("BENCH_ESTILOS_DIR")
    if not v:
        if os.path.isfile("MANIFESTO.json") or os.path.isfile("estilos/_escopo.json"):
            v = os.path.join(os.getcwd(), "estilos")
        else:
            v = os.path.join(ilha_home(), "estilos")
    if criar:
        os.makedirs(v, exist_ok=True)
    return v


def dir_catalogo():
    """catalogo.json da SPEC-15. Ausência é SILÊNCIO com consequência declarada:
    sem catálogo não há camada 2, e `resolver` diz isso no stderr (§3.9)."""
    v = os.environ.get("BENCH_CATALOGO")
    if v:
        return v if os.path.isfile(v) else None
    base = os.environ.get("BENCH_REMOTION_DIR") or os.path.normpath(
        os.path.join(DIR_SCRIPT, "..", "..", "..", "tools", "remotion-compositor"))
    alvo = os.path.join(base, "catalogo", "catalogo.json")
    return alvo if os.path.isfile(alvo) else None


# ────────────────────────────────────────────────────────────────── utilidades
def _ler(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def _gravar(caminho, obj):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    tmp = caminho + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, caminho)
    return os.path.abspath(caminho)


def _canonico(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(obj):
    return hashlib.sha256(_canonico(obj).encode("utf-8")).hexdigest()


def _agora():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def log(*a):
    print(*a, file=sys.stderr)


def _achatar(d, prefixo=""):
    return _perfil()._achatar(d, prefixo)


def _no(d, caminho):
    cur = d
    for parte in caminho.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            return False, None
        cur = cur[parte]
    return True, cur


def _pôr(d, caminho, valor):
    cur = d
    partes = caminho.split(".")
    for parte in partes[:-1]:
        cur = cur.setdefault(parte, {})
    cur[partes[-1]] = valor
    return d


# ═══════════════════════════════════════════════════ o escopo (§4.2), semeado
#
# 🔴 POR QUE PREFIXO E NÃO A LISTA DE FOLHAS DA §4.2.
# A §4.2 enumera 20 folhas (`ritmo.pads.pre`, `legenda.y_pct`, …). Escrita em
# 2026-08-08, ela é hoje INCOMPLETA: as ondas 1–3 acrescentaram ao schema do
# perfil `legenda.estilo.*` (SPEC-13), `legenda.agrupamento.*`, `legenda.diretor.*`
# (SPEC-14) e `ritmo.cauda_alvo_s` (SPEC-09). Com a lista de folhas literal, o
# estilo `padrao` da creator-2 NÃO PODERIA carregar o `legenda.estilo` dela — que é
# exatamente o que a §3.10 manda semear no dia 1.
# A §3.4 (a tabela de precedência) descreve a camada 3 por PREFIXO — "`ritmo.*`,
# `cor.grade`, `legenda.*` exceto `legenda.fonte_palavras`, `audio.loudness.*`" —
# e é essa forma que continua correta quando o schema cresce. É também,
# literalmente, a `CREATOR_PODE` do perfil.py (menos `trilha`).
# Continua sendo ALLOWLIST: bloco novo de topo (`trilha`, `publicacao`, `broll`,
# `apoio_visual`) NÃO entra por acidente.
ESCOPO_SEMENTE = {
    "contrato": CONTRATO_ESCOPO,
    "_motivo": [
        "O único lugar do sistema que declara QUEM PODE ESCREVER O QUÊ.",
        "Versionado porque é o contrato entre a SPEC-00 (perfil), a SPEC-16 (a",
        "escolha da UI) e a SPEC-24 (o estilo do usuário).",
        "",
        "`gravavel_por_estilo` é PREFIXO e é ALLOWLIST. Um caminho fora dele é erro",
        "de validação com o caminho na mensagem — nunca campo ignorado em silêncio.",
        "Denylist esqueceria o campo que a próxima spec criar."
    ],
    "gravavel_por_estilo": ["ritmo", "cor.grade", "legenda", "audio.loudness"],
    "negado_dentro_do_gravavel": ["legenda.fonte_palavras"],
    "_negado_motivo": (
        "legenda.fonte_palavras é exclusivo do perfil DE PROPÓSITO: `transcript-montado` "
        "é proibido em talking-head porque o ASR do montado INVENTA palavra na emenda "
        "(SPEC-00 §3.4). Trava de segurança medida não se desliga por preferência de estilo."
    ),
    "exclusivo_do_perfil": [
        "video", "audio.sr", "audio.canais", "audio.codec", "audio.bitrate",
        "audio.passes_loudnorm", "cor.entrada_esperada", "cor.lut", "cor.tags_saida",
        "cor.aplicar_tags_por", "legenda.fonte_palavras", "zonas_ui", "estrutura",
        "entregaveis", "qc", "trilha", "publicacao", "broll", "apoio_visual"
    ],
    # SPEC-50 §3.5 — `min_producoes` de 3 para 1. A biblioteca de estilos é de UMA
    # pessoa: exigir três produções distintas para reconhecer uma preferência é
    # fazer o produto esperar três semanas para aprender o que ela já disse. A
    # guarda que continua tendo dentes é a de CONTRA-SINAL (`contra_recentes`) —
    # o mesmo parâmetro empurrado para os dois lados continua sendo decisão por
    # peça, e continua recusado. E `promover` continua exigindo `--confirmar`:
    # o que se cortou foi a espera, não a confirmação.
    # O número é configurável por `<estilos>/_escopo.json`: quem tiver um time
    # editando o mesmo estilo sobe de volta sem tocar em código.
    "promocao": {"min_producoes": 1, "janela": 12, "contra_recentes": 3},
}

# Grupos do catálogo da SPEC-15 que viram `picks`. `grafismo` é liga/desliga por
# slug e mora no bloco `grafismo`, não em `picks`.
GRUPOS_PICK = ("gramatica", "gancho", "legenda", "tema")


def escopo():
    """Lê `<estilos>/_escopo.json`; semeia a partir de ESCOPO_SEMENTE se não
    houver. O ARQUIVO é a fonte de verdade quando existe — `escopo --conferir`
    prova que ele e a semente não divergiram."""
    alvo = os.path.join(dir_estilos(), "_escopo.json")
    if os.path.isfile(alvo):
        e = _ler(alvo)
        if e.get("contrato") != CONTRATO_ESCOPO:
            raise ErroEstilo("%s: contrato %r, esperado %s"
                             % (alvo, e.get("contrato"), CONTRATO_ESCOPO))
        return e
    return copy.deepcopy(ESCOPO_SEMENTE)


def escopo_para_perfil(e=None):
    """A forma que o `perfil.py` consome: permite/nega/exclusivo_do_perfil."""
    e = e or escopo()
    return {"permite": list(e.get("gravavel_por_estilo", [])),
            "nega": list(e.get("negado_dentro_do_gravavel", [])),
            "exclusivo_do_perfil": list(e.get("exclusivo_do_perfil", []))}


def conferir_caminhos(ov, rotulo, e=None):
    """Levanta ErroEstilo nomeando TODO caminho fora do escopo. A mensagem traz o
    comando `perfil.py … --set` pronto: quem quer 25 fps de verdade tem caminho."""
    e = e or escopo()
    esc = escopo_para_perfil(e)
    P = _perfil()
    fora = [c for c, _v in _achatar(P._sem_comentarios(ov or {}))
            if not P._no_escopo(c, esc)]
    if fora:
        raise ErroEstilo(P._msg_fora_do_escopo(fora, rotulo, esc))
    return True


# ═════════════════════════════════════════════════════════ o catálogo (SPEC-15)
def catalogo():
    c = dir_catalogo()
    if not c:
        return None
    return _ler(c)


def _por_slug(cat):
    return {e["slug"]: e for e in (cat or {}).get("estilos", [])}


def defaults_do_catalogo(cat, perfil):
    """`{grupo: slug}` para os grupos que têm um `defaultDe` cobrindo `perfil`.
    Grupo sem default fica FORA do dict — ausente é diferente de `null`."""
    out = {}
    for e in (cat or {}).get("estilos", []):
        if perfil in (e.get("defaultDe") or []) and e.get("grupo") in GRUPOS_PICK:
            out.setdefault(e["grupo"], e["slug"])
    return out


# ═══════════════════════════════════════════════════════ usuário e referências
def usuarios():
    d = dir_estilos()
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if not n.startswith("_") and not n.startswith(".")
                  and os.path.isdir(os.path.join(d, n)))


def usuario_corrente(arg=None):
    """`--usuario` → `$BENCH_USUARIO` → o único subdiretório de usuário → erro 2
    nomeando os que existem. Nada de adivinhar."""
    if arg:
        return arg
    v = os.environ.get("BENCH_USUARIO")
    if v:
        return v
    us = usuarios()
    if len(us) == 1:
        return us[0]
    raise ErroEstilo(
        "usuário ambíguo: %s. Diga qual com `--usuario <u>` ou $BENCH_USUARIO."
        % (("existem %d em %s: %s" % (len(us), dir_estilos(), ", ".join(us)))
           if us else "a biblioteca %s está vazia" % dir_estilos()))


def parse_ref(ref, usuario=None):
    """`u/slug@v003` | `u/slug` | `slug` (com --usuario) → (u, slug, versao|None)."""
    m = RE_REF.match(ref or "")
    if m:
        return m.group(1), m.group(2), m.group(3)
    if "/" not in (ref or ""):
        slug, _, versao = (ref or "").partition("@")
        if RE_SLUG.match(slug) and (not versao or RE_VERSAO.match(versao)):
            return usuario_corrente(usuario), slug, (versao or None)
    raise ErroEstilo("referência inválida: %r (esperado <usuario>/<slug>[@vNNN])" % ref)


def dir_do_estilo(u, slug):
    return os.path.join(dir_estilos(), u, slug)


def versoes(u, slug):
    d = os.path.join(dir_do_estilo(u, slug), "versoes")
    if not os.path.isdir(d):
        return []
    return sorted(n[:-5] for n in os.listdir(d)
                  if RE_VERSAO.match(n[:-5] or "") and n.endswith(".json"))


def head(u, slug):
    """A versão corrente, lida do PONTEIRO. Sem ponteiro, a maior versão."""
    ptr = os.path.join(dir_do_estilo(u, slug), "estilo.json")
    if os.path.isfile(ptr):
        v = _ler(ptr).get("versao")
        if v:
            return v
    vs = versoes(u, slug)
    return vs[-1] if vs else None


def caminho_versao(u, slug, versao):
    return os.path.join(dir_do_estilo(u, slug), "versoes", "%s.json" % versao)


def carregar_estilo(u, slug, versao=None, usuario_pedido=None):
    """Carrega UMA versão, crua (sem herança). §3.8: isolamento é do carregador.

    Toda operação recebe um usuário e NUNCA atravessa a fronteira: pedir
    `creator-2/x --usuario creator-1` sai 1 aqui, antes de qualquer leitura."""
    if usuario_pedido and usuario_pedido != u:
        raise ErroEstilo(
            "isolamento: `%s/%s` é do usuário %r e a operação corre como %r. "
            "Estilo de um usuário não atravessa para outro — se você quer usá-lo, "
            "exporte e importe: `estilo.py exportar %s/%s --saida <f>` e "
            "`estilo.py importar <f> --usuario %s`."
            % (u, slug, u, usuario_pedido, u, slug, usuario_pedido))
    versao = versao or head(u, slug)
    if not versao:
        d = dir_do_estilo(u, slug)
        raise ErroEstilo("estilo %s/%s não existe (procurei em %s)" % (u, slug, d))
    arq = caminho_versao(u, slug, versao)
    if not os.path.isfile(arq):
        raise ErroEstilo("versão %s de %s/%s não existe (tem: %s)"
                         % (versao, u, slug, ", ".join(versoes(u, slug)) or "nenhuma"))
    e = _ler(arq)
    e["_arquivo"] = arq
    return e


def resolver_estilo(ref, usuario=None):
    """(estilo mesclado com o pai, meta). Herança de UM nível, sem ciclo (§3.3)."""
    u, slug, versao = parse_ref(ref, usuario)
    e = carregar_estilo(u, slug, versao, usuario_pedido=usuario)
    versao_efetiva = e.get("versao") or versao or head(u, slug)
    cadeia = ["%s/%s@%s" % (u, slug, versao_efetiva)]
    pai = e.get("herda")
    if pai:
        pu, pslug, pversao = parse_ref(pai, u)
        if (pu, pslug) == (u, slug):
            raise ErroEstilo("herança cíclica: %s/%s herda de si mesmo" % (u, slug))
        if pu != u:
            raise ErroEstilo("isolamento: %s/%s herda de %s, que é de outro usuário"
                             % (u, slug, pai))
        p = carregar_estilo(pu, pslug, pversao, usuario_pedido=u)
        if p.get("herda"):
            raise ErroEstilo(
                "herança com profundidade > 1: %s/%s herda de %s, que herda de %s. "
                "O máximo é 1 nível — cadeia profunda transforma 'por que essa peça "
                "saiu assim' numa investigação e zera o valor do mapa _origem."
                % (u, slug, pai, p["herda"]))
        cadeia.insert(0, "%s/%s@%s" % (pu, pslug, p.get("versao")))
        e = _mesclar_estilo(p, e)
    meta = {"usuario": u, "slug": slug, "versao": versao_efetiva, "cadeia": cadeia,
            "arquivo": caminho_versao(u, slug, versao_efetiva)}
    return e, meta


def _mesclar_estilo(pai, filho):
    """Merge profundo pai→filho nos blocos de conteúdo. Identidade (slug, versao,
    nome, herda, historico, procedencia) é sempre do FILHO."""
    out = copy.deepcopy(filho)
    for bloco in ("picks", "grafismo", "parametros", "perfil_overrides"):
        a, b = pai.get(bloco), filho.get(bloco)
        if isinstance(a, dict):
            out[bloco] = _perfil()._mesclar(a, b if isinstance(b, dict) else {})
    if not out.get("perfis") and pai.get("perfis"):
        out["perfis"] = list(pai["perfis"])
    return out


# ═══════════════════════════════════ perfil_overrides do estilo (o que a camada dá)
def perfil_overrides_do_estilo(e):
    """O bloco `perfil_overrides`, com o ritmo nomeado JÁ EXPANDIDO.

    `"ritmo": "dinamico"` é açúcar da SPEC-00; expandi-lo aqui (e não depois, no
    merge) mantém o `_origem` honesto — cada folha de `ritmo` aponta para o
    estilo que a escreveu, e não para um nome que o leitor teria de resolver de
    cabeça."""
    ov = copy.deepcopy(e.get("perfil_overrides") or {})
    r = ov.get("ritmo")
    if isinstance(r, str):
        ritmos = _perfil().ritmos_nomeados()
        if r not in ritmos:
            raise ErroEstilo("ritmo nomeado %r não existe (tem: %s)"
                             % (r, ", ".join(k for k in ritmos if not k.startswith("_"))))
        ov["ritmo"] = copy.deepcopy(ritmos[r])
    return _perfil()._sem_comentarios(ov)


def camada_para_perfil(ref, usuario=None):
    """(rotulo, perfil_overrides, sha256, escopo) — o que o `perfil.py --estilo`
    consome. Valida contra o escopo ANTES de devolver: quem mergeia não decide o
    que pode ser mergeado."""
    e, meta = resolver_estilo(ref, usuario)
    ov = perfil_overrides_do_estilo(e)
    esc = escopo()
    conferir_caminhos(ov, "estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"]),
                      esc)
    sha = _sha256(_ler(meta["arquivo"])) if os.path.isfile(meta["arquivo"]) else None
    rot = "estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])
    return rot, ov, sha, escopo_para_perfil(esc)


# ═══════════════════════════════════════════════════ camada 4 — a escolha da UI
#
# O `benchmark.edit-estilo/v1` (SPEC-16 §4.3) é o formato BRUTO da escolha. Este
# mapa é a tradução dele para o vocabulário do estilo, e é explícito de propósito:
# um mapeamento por adivinhação ("headline parece gancho") é o tipo de coisa que
# funciona no dia em que foi escrita e mente seis meses depois.
MAPA_UI_PICKS = {"legenda": "legenda", "headline": "gancho", "gramatica_plano": "gramatica"}
# `gramatica_plano` chega como valor do PERFIL (`fixa`/`alternada`/`punch-pontual`,
# enum de perfis/_schema.json), não como slug do catálogo. Ele é as duas coisas ao
# mesmo tempo: escreve `ritmo.gramatica_plano` (que está no escopo) E escolhe o
# `picks.gramatica` correspondente.
GRAMATICA_PARA_SLUG = {"fixa": "plano-fixo", "alternada": "plano-alternado",
                       "punch-pontual": "punch-pontual"}


def _traduzir_evento_ui_v2(obj, por_slug):
    """A tradução do `v2` (SPEC-19) — o contrato que a galeria realmente grava.

    Diferenças que importam contra o `v1`, e por que cada uma tem tratamento
    próprio em vez de um mapa de nomes:

      · os picks já chegam como SLUG de catálogo (`gramatica`, `tema`, `gancho`,
        `legenda`), então a conferência é contra o grupo do slug, não uma tradução;
      · `gramatica_plano` vem JUNTO, como valor de perfil, e continua indo para
        `ritmo.gramatica_plano` — é o mesmo campo do v1;
      · `grafismos[]` e `grafismos_fora[]` são duas LISTAS, e a segunda é a razão
        de o contrato existir: a galeria manda o que foi desligado, e desligado é
        um NÃO explícito, não um campo ausente. `graf[slug] = False` grava isso;
      · `elementos` no v2 são os INTERRUPTORES da peça (`legenda_ativa`, `sfx`,
        `tracking`), não slugs de grafismo. Um aviso por chave encheria o sinal de
        ruído a cada evento, então sai um aviso só, nomeando todas."""
    ov, picks, graf, avisos = {}, {}, {}, []
    for campo, grupo in (("gramatica", "gramatica"), ("tema", "tema"),
                         ("gancho", "gancho"), ("legenda", "legenda")):
        v = obj.get(campo)
        if not v:
            continue
        ent = por_slug.get(v)
        if ent and ent.get("grupo") == grupo:
            picks[grupo] = v
        else:
            avisos.append("campo %r = %r não é slug do grupo %r do catálogo — "
                          "NÃO aplicado" % (campo, v, grupo))
    gp = obj.get("gramatica_plano")
    if gp in GRAMATICA_PARA_SLUG:
        _pôr(ov, "ritmo.gramatica_plano", gp)
    for slug in obj.get("grafismos") or []:
        ent = por_slug.get(slug)
        if ent and ent.get("grupo") == "grafismo":
            graf[slug] = True
        else:
            avisos.append("grafismo %r não está no catálogo — não aplicado" % slug)
    for slug in obj.get("grafismos_fora") or []:
        if (por_slug.get(slug) or {}).get("grupo") == "grafismo":
            graf[slug] = False
    inter = sorted((obj.get("elementos") or {}).keys())
    if inter:
        avisos.append("interruptores da peça, fora do vocabulário de estilo: %s"
                      % ", ".join(inter))
    if obj.get("acento") and not obj.get("acento_usado"):
        avisos.append("acento %s marcado como NÃO usado: nenhum estilo escolhido "
                      "pinta acento. Não invente onde usá-lo." % obj["acento"])
    return ov, picks, graf, avisos


def _traduzir_evento_ui(obj, cat):
    """Um `benchmark.edit-estilo/v1`, `/v2` ou `/v3` → (perfil_overrides, picks, grafismo,
    avisos).

    Só traduz o que tem destino declarado. O resto vira AVISO nomeado — nunca um
    palpite: "caixa desmarcada é um NÃO explícito", e valor sem destino é um
    valor que ninguém aplicou, o que precisa aparecer."""
    ov, picks, graf, avisos = {}, {}, {}, []
    por_slug = _por_slug(cat)
    if obj.get("contrato") in (CONTRATO_UI_ESTILO_V2, CONTRATO_UI_ESTILO_V3):
        return _traduzir_evento_ui_v2(obj, por_slug)
    for campo, grupo in MAPA_UI_PICKS.items():
        v = obj.get(campo)
        if v is None:
            continue
        slug = v
        if campo == "gramatica_plano":
            if v in GRAMATICA_PARA_SLUG:
                _pôr(ov, "ritmo.gramatica_plano", v)
                slug = GRAMATICA_PARA_SLUG[v]
            else:
                slug = v
        ent = por_slug.get(slug)
        if ent and ent.get("grupo") == grupo:
            picks[grupo] = slug
        else:
            avisos.append(
                "campo %r = %r não é slug do grupo %r do catálogo — NÃO aplicado. "
                "Slugs válidos: %s"
                % (campo, v, grupo,
                   ", ".join(sorted(s for s, e in por_slug.items()
                                    if e.get("grupo") == grupo)) or "(sem catálogo)"))
    for k, v in (obj.get("elementos") or {}).items():
        ent = por_slug.get(k)
        if ent and ent.get("grupo") == "grafismo":
            graf[k] = bool(v)
        else:
            avisos.append("elementos.%s = %s não é slug do grupo `grafismo` — "
                          "registrado como sinal, não aplicado" % (k, v))
    if obj.get("acento") and not obj.get("acento_usado"):
        avisos.append("acento %s marcado como NÃO usado: nenhum estilo escolhido pinta "
                      "acento. Não invente onde usá-lo." % obj["acento"])
    return ov, picks, graf, avisos


def eventos_ui(dir_producao):
    """Os `benchmark.edit-estilo/v1` já aplicados, do mais antigo ao mais novo.

    Lê `.preview/aplicados/` — que existe porque a SPEC-16 §3.12 decidiu MOVER em
    vez de apagar. Aquela decisão foi tomada por outra razão ("relatório que apaga
    a evidência não serve"); esta spec é o motivo pelo qual ela estava certa: sem
    o histórico da escolha, não há sinal, e sem sinal não há evolução. O ref-A
    apaga (`SKILL.md:198`) e por isso nunca poderia ter esta funcionalidade."""
    prev = os.path.join(dir_producao, ".preview")
    out = []
    for sub in ("aplicados",):
        d = os.path.join(prev, sub)
        if not os.path.isdir(d):
            continue
        for nome in sorted(os.listdir(d)):
            if not nome.endswith(".json"):
                continue
            obj = _ler(os.path.join(d, nome))
            pay = obj.get("payload") if obj.get("schema") else obj
            if isinstance(pay, dict) and pay.get("contrato") in (
                    CONTRATO_UI_ESTILO, CONTRATO_UI_ESTILO_V2,
                    CONTRATO_UI_ESTILO_V3, CONTRATO_UI_AJUSTES):
                out.append({"arquivo": os.path.join(".preview", sub, nome),
                            "abs": os.path.join(d, nome), "payload": pay,
                            "salvo_em": pay.get("salvo_em") or ""})
    out.sort(key=lambda x: (x["salvo_em"], x["arquivo"]))
    return out


# ═══════════════════════════════════════════════ camada 5 — o pedido em texto
#
# 🔴 Linguagem natural NUNCA aplica sozinha (§3.4 regra 3). Ela é compilada num
# diff explícito, impressa antes, e gravada no `_origem` com o texto original.
# Sem isso "linguagem natural" vira a camada mais alta, opaca, que ganha de tudo
# e não deixa rastro — e a próxima pergunta ("por que essa peça saiu diferente?")
# não tem resposta.
# (regex, caminho, valor, nota, modo) — `delta` soma ao resolvido, `absoluto` troca.
REGRAS_PEDIDO = [
    (r"\bmais alto\b|\baumenta o (som|volume|áudio|audio)\b|\bmais volume\b",
     "audio.loudness.I", +2.0, "alvo de loudness 2 LU acima", "delta"),
    (r"\bmais baixo\b|\bdiminui o (som|volume|áudio|audio)\b|\bmenos volume\b",
     "audio.loudness.I", -2.0, "alvo de loudness 2 LU abaixo", "delta"),
    (r"\blegenda (mais )?(baixa|embaixo|mais para baixo)\b",
     "legenda.y_pct", +0.035, "legenda 3,5% da altura mais baixa", "delta"),
    (r"\blegenda (mais )?(alta|em cima|mais para cima)\b",
     "legenda.y_pct", -0.035, "legenda 3,5% da altura mais alta", "delta"),
    (r"\bcorte (mais )?(colado|seco|rápido|rapido)\b|\bsem respiro\b",
     "ritmo.pads.post", -0.04, "pad de saída 40 ms menor", "delta"),
    (r"\bmais respiro\b|\bcorte (mais )?(solto|lento)\b",
     "ritmo.pads.post", +0.04, "pad de saída 40 ms maior", "delta"),
    (r"\bplano fixo\b|\benquadramento fixo\b|\bsem punch\b|\bsem zoom\b",
     "ritmo.gramatica_plano", "fixa", "gramática de plano fixa", "absoluto"),
    (r"\bplano alternado\b|\balterna o (plano|enquadramento)\b",
     "ritmo.gramatica_plano", "alternada", "gramática de plano alternada", "absoluto"),
]
# Pedidos que NÃO são estilo — reconhecidos para poder RECUSAR com a frase certa.
REGRAS_PEDIDO_FORA = [
    (r"\b16[:x]9\b|\bhorizontal\b|\bpaisagem\b", "video.aspecto"),
    (r"\b9[:x]16\b|\bvertical\b", "video.aspecto"),
    (r"\b(\d{2})\s*(fps|quadros)\b", "video.fps"),
    (r"\b4k\b|\b1080p?\b|\b720p?\b", "video.largura"),
]


def compilar_pedido(texto, base):
    """(operacoes, recusas). NÃO aplica nada. `base` é o perfil já resolvido sem
    a camada 5, para o diff sair com o valor de origem e o de destino."""
    ops, recusas = [], []
    t = (texto or "").lower()
    for rx, caminho in REGRAS_PEDIDO_FORA:
        if re.search(rx, t):
            recusas.append({
                "caminho": caminho, "trecho": re.search(rx, t).group(0),
                "motivo": ("isto é escolha de PERFIL DE PEÇA, não de estilo. "
                           "Formato não se negocia por estilo."),
                "comando": "perfil.py resolver <dir> --perfil <nome> --set %s=<valor>"
                           % caminho})
    for rx, caminho, valor, nota, modo in REGRAS_PEDIDO:
        if not re.search(rx, t):
            continue
        tem, atual = _no(base, caminho)
        if modo == "delta":
            if not tem or not isinstance(atual, (int, float)) or isinstance(atual, bool):
                recusas.append({"caminho": caminho, "trecho": re.search(rx, t).group(0),
                                "motivo": "o perfil resolvido não tem valor numérico em %s"
                                          % caminho, "comando": None})
                continue
            novo = round(float(atual) + valor, 4)
        else:
            novo = valor
        if tem and _canonico(atual) == _canonico(novo):
            continue                       # já é isso: instrução sem efeito não vira op
        ops.append({"caminho": caminho, "de": atual if tem else None, "para": novo,
                    "nota": nota})
    return ops, recusas


def _ov_do_pedido(ops):
    ov = {}
    for o in ops:
        _pôr(ov, o["caminho"], o["para"])
    return ov


# ═══════════════════════════════════════════════════════════════════ validação
SCHEMA_SEMENTE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CONTRATO,
    "title": "Estilo do usuário (SPEC-24 §3.2)",
    "type": "object",
    "required": ["contrato", "usuario", "slug", "versao", "nome", "perfis"],
    "properties": {
        "contrato": {"const": CONTRATO},
        "usuario": {"type": "string", "minLength": 1},
        "slug": {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"},
        "versao": {"type": "string", "pattern": "^v[0-9]{3}$"},
        "nome": {"type": "string", "minLength": 1},
        "nota": {"type": ["string", "null"]},
        "perfis": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "herda": {"type": ["string", "null"]},
        "picks": {"type": "object"},
        "grafismo": {"type": "object"},
        "parametros": {"type": "object"},
        "perfil_overrides": {"type": "object"},
        "estado": {"enum": ["pronto", "incompleto"]},
        "requisitos": {"type": "object"},
        "procedencia": {
            "type": "object",
            "required": ["tipo"],
            "properties": {
                "tipo": {"enum": ["proprio", "modelado", "misto"]},
                "fonte": {"type": ["object", "null"]},
                "nota_de_uso": {"type": ["string", "null"]},
            },
        },
        "historico": {"type": "object"},
    },
}


def validar_estilo(e, cat=None, esc=None, dir_perfis=None):
    """Lista de erros ([] = válido). As 8 regras da §4.1, cada uma com o porquê
    na mensagem — um erro que não diz o que fazer manda o usuário adivinhar."""
    erros = []
    vistos = [0]
    _validar_no(e, SCHEMA_SEMENTE, "", erros, vistos)
    if erros:
        return erros, vistos[0]

    esc = esc or escopo()
    cat = cat if cat is not None else catalogo()
    por_slug = _por_slug(cat)
    P = _perfil()
    dir_perfis = dir_perfis or P.DIR_PERFIS

    # perfis[] tem que existir no catálogo de perfis de peça
    if os.path.isdir(dir_perfis):
        tem = {f[:-5] for f in os.listdir(dir_perfis)
               if f.endswith(".json") and not f.startswith("_")}
        for nome in e.get("perfis", []):
            if nome not in tem:
                erros.append("perfis: %r não existe em %s (tem: %s)"
                             % (nome, dir_perfis, ", ".join(sorted(tem))))

    # herança: 1 nível, sem ciclo, mesmo usuário
    pai = e.get("herda")
    if pai:
        try:
            pu, pslug, pv = parse_ref(pai, e.get("usuario"))
            if (pu, pslug) == (e.get("usuario"), e.get("slug")):
                erros.append("herda: %s herda de si mesmo (ciclo)" % pai)
            elif pu != e.get("usuario"):
                erros.append("herda: %s é de outro usuário — estilo não atravessa "
                             "fronteira de usuário (§3.8)" % pai)
            else:
                p = carregar_estilo(pu, pslug, pv, usuario_pedido=pu)
                if p.get("herda"):
                    erros.append("herda: profundidade > 1 (%s herda de %s) — o máximo "
                                 "é 1 nível (§3.3)" % (pai, p["herda"]))
        except ErroEstilo as ex:
            erros.append("herda: %s" % ex)

    # picks: slug existe, grupo certo, perfis intersectam
    for grupo, slug in (e.get("picks") or {}).items():
        if slug is None:
            continue                       # `null` explícito = grupo DESLIGADO
        ent = por_slug.get(slug)
        if cat is None:
            continue                       # sem catálogo não há o que conferir (§3.9)
        if not ent:
            erros.append("picks.%s: slug %r não existe no catálogo" % (grupo, slug))
        elif ent.get("grupo") != grupo:
            erros.append("picks.%s: %r é do grupo %r, não %r"
                         % (grupo, slug, ent.get("grupo"), grupo))
        elif not (set(ent.get("perfis") or []) & set(e.get("perfis") or [])):
            erros.append("picks.%s: %r serve aos perfis %s e este estilo declara %s — "
                         "sem interseção" % (grupo, slug, ent.get("perfis"), e.get("perfis")))

    # grafismo: chave é slug do grupo grafismo
    for slug, v in (e.get("grafismo") or {}).items():
        if cat is None:
            continue
        ent = por_slug.get(slug)
        if not ent or ent.get("grupo") != "grafismo":
            erros.append("grafismo.%s: não é slug do grupo `grafismo` do catálogo" % slug)
        elif not isinstance(v, bool):
            erros.append("grafismo.%s: esperado bool, veio %s" % (slug, type(v).__name__))

    # parametros: Param declarado no catálogo, dentro da faixa
    for slug, params in (e.get("parametros") or {}).items():
        if cat is None:
            continue
        ent = por_slug.get(slug)
        if not ent:
            erros.append("parametros.%s: slug não existe no catálogo" % slug)
            continue
        decl = {p["nome"]: p for p in (ent.get("parametros") or [])}
        for nome, v in (params or {}).items():
            if nome not in decl:
                erros.append("parametros.%s.%s: não é Param declarado no catálogo "
                             "(tem: %s)" % (slug, nome, ", ".join(sorted(decl)) or "nenhum"))
                continue
            faixa = decl[nome].get("faixa")
            if faixa and isinstance(v, (int, float)) and not isinstance(v, bool):
                if not (faixa[0] <= v <= faixa[1]):
                    erros.append("parametros.%s.%s: %r fora da faixa %s do catálogo"
                                 % (slug, nome, v, faixa))

    # perfil_overrides: a trava do formato
    try:
        ov = perfil_overrides_do_estilo(e)
        conferir_caminhos(ov, "estilo:%s/%s" % (e.get("usuario"), e.get("slug")), esc)
    except ErroEstilo as ex:
        erros.append(str(ex))

    # procedência de terceiro (§3.8 trava 1)
    proc = e.get("procedencia") or {}
    if proc.get("tipo") and proc["tipo"] != "proprio":
        f = proc.get("fonte") or {}
        if not (f.get("handle") or f.get("url")):
            erros.append("procedencia.fonte: tipo %r exige handle ou url — estilo "
                         "modelado sem fonte é modelagem sem procedência" % proc["tipo"])
        if not f.get("data"):
            erros.append("procedencia.fonte.data: ausente")
        ficha, corpus = f.get("ficha"), f.get("corpus")
        if not ficha and not corpus:
            erros.append("procedencia.fonte: tipo %r exige `ficha` (a ficha de modelagem "
                         "em intelligence/edicao/, que é o que fecha o loop — SPEC-15 §1: "
                         "3 de 5 fichas nunca viraram nada) OU `corpus` (a lista de "
                         "referências, quando o estilo vem da style-extract, que modela N "
                         "peças e não uma). Modelagem sem procedência não entra na "
                         "biblioteca." % proc["tipo"])
        elif ficha and not os.path.isfile(ficha):
            erros.append("procedencia.fonte.ficha: %r não existe (test -f falhou)" % ficha)

    # nenhum caminho absoluto, em campo nenhum (§7.7)
    for c, v in _achatar(e):
        if isinstance(v, str) and (v.startswith("/") and "/" in v[1:]) and c != "_arquivo":
            erros.append("%s: caminho absoluto (%r) — estilo é portátil por "
                         "construção; use caminho relativo" % (c, v))
    return erros, vistos[0]


def _tipo_ok(v, t):
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    return True


def _validar_no(v, esq, caminho, erros, vistos):
    if not isinstance(esq, dict):
        return
    vistos[0] += 1
    if "const" in esq and v != esq["const"]:
        erros.append("%s: esperado %r, veio %r" % (caminho or "(raiz)", esq["const"], v))
        return
    if "enum" in esq and v not in esq["enum"]:
        erros.append("%s: %r não está em %s" % (caminho or "(raiz)", v, esq["enum"]))
        return
    t = esq.get("type")
    if t is not None:
        tipos = t if isinstance(t, list) else [t]
        if not any(_tipo_ok(v, x) for x in tipos):
            erros.append("%s: tipo %s, esperado %s"
                         % (caminho or "(raiz)", type(v).__name__, "|".join(tipos)))
            return
    if isinstance(v, str):
        if "minLength" in esq and len(v) < esq["minLength"]:
            erros.append("%s: string curta demais" % caminho)
        if "pattern" in esq and not re.match(esq["pattern"], v):
            erros.append("%s: %r não casa %s" % (caminho, v, esq["pattern"]))
    if isinstance(v, list):
        if "minItems" in esq and len(v) < esq["minItems"]:
            erros.append("%s: %d itens < mínimo %d" % (caminho, len(v), esq["minItems"]))
        if "items" in esq:
            for i, x in enumerate(v):
                _validar_no(x, esq["items"], "%s[%d]" % (caminho, i), erros, vistos)
    if isinstance(v, dict):
        for r in esq.get("required", []):
            if r not in v:
                erros.append("%s: falta a chave obrigatória %r" % (caminho or "(raiz)", r))
        for k, sub in esq.get("properties", {}).items():
            if k in v:
                _validar_no(v[k], sub, ("%s.%s" % (caminho, k)) if caminho else k,
                            erros, vistos)


# ═══════════════════════════════════════════════════════════════ criar / semear
def _semente_do_creator(u):
    """§3.10 item 3: se `_usuario.json` declara `creator: <n>` e existe
    `<creators>/<n>/perfil-overrides.json`, os valores dele entram no estilo
    `padrao`. LEITURA apenas — nada em `creators/` é criado ou editado.

    É assim que a creator-2 entra no dia 1 já com o grade oficial dela e o ritmo
    `dinamico`, sem ninguém redigitar. Ausência é SILÊNCIO: um cliente do produto
    não tem `creators/`."""
    up = os.path.join(dir_estilos(), u, "_usuario.json")
    creator = _ler(up).get("creator") if os.path.isfile(up) else None
    if not creator:
        return {}, None
    P = _perfil()
    base = P.dir_creators()
    if not base:
        return {}, None
    arq = os.path.join(base, creator, "perfil-overrides.json")
    if not os.path.isfile(arq):
        return {}, None
    ov = P._sem_comentarios(_ler(arq))
    r = ov.get("ritmo")
    if isinstance(r, str):
        ritmos = P.ritmos_nomeados()
        if r in ritmos:
            ov["ritmo"] = copy.deepcopy(ritmos[r])
    # ⚠️ o rastro é o NOME do creator, nunca o CAMINHO. Um `creators/creator-2/...`
    # dentro de `versoes/*.json` amarraria o estilo à nossa instalação — é o que
    # o aceite §7.7 grepa. O caminho completo se deriva de `_usuario.json` +
    # $BENCH_CREATORS_DIR, que é exatamente onde ele deve ser resolvido.
    return ov, creator


def criar(ref, nome, perfis, usuario=None, de_perfil=None, de_producao=None,
          de_receita=None, herda=None, nota=None, forcar=False):
    u, slug, _v = parse_ref(ref, usuario)
    if not RE_SLUG.match(slug):
        raise ErroEstilo("slug %r não é kebab-case" % slug)
    d = dir_do_estilo(u, slug)
    if versoes(u, slug) and not forcar:
        raise ErroEstilo("estilo %s/%s já existe (versões: %s). Para evoluí-lo use "
                         "`propor`/`promover`; para outro estilo, outro slug."
                         % (u, slug, ", ".join(versoes(u, slug))))
    e = {
        "contrato": CONTRATO, "usuario": u, "slug": slug, "versao": "v001",
        "nome": nome or slug.replace("-", " ").capitalize(),
        "nota": nota, "perfis": list(perfis), "herda": herda,
        "picks": {}, "grafismo": {}, "parametros": {}, "perfil_overrides": {},
        "procedencia": {"tipo": "proprio", "fonte": None, "nota_de_uso": None},
        "historico": {"criado_em": _agora(), "derivado_de": None,
                      "confirmado_por": u, "mudou": []},
    }
    origens = []
    # (1) e (2): o perfil de peça e os defaults do catálogo NÃO são copiados.
    # 🔴 Copiá-los tornaria o estilo `padrao` NÃO-NEUTRO e congelaria o perfil: o
    # aceite §7.9 exige que o `padrao` semeado do próprio perfil não mude UM BYTE
    # do render. O silêncio do estilo É o que dá a vez às camadas de baixo (§3.4
    # regra 2). O que herdamos por herança não se copia.
    if de_perfil:
        if de_perfil not in e["perfis"]:
            e["perfis"].append(de_perfil)
        origens.append("perfil:%s (por herança, sem cópia)" % de_perfil)
    # (3) a semente do creator, quando o usuário declara um
    sem, arq_sem = _semente_do_creator(u)
    if sem:
        e["perfil_overrides"] = _perfil()._mesclar(e["perfil_overrides"], sem)
        origens.append("creator-override:%s" % arq_sem)
    if de_producao:
        ov, picks, graf, params = _do_estilo_resolvido(de_producao)
        e["perfil_overrides"] = _perfil()._mesclar(e["perfil_overrides"], ov)
        e["picks"].update(picks)
        e["grafismo"].update(graf)
        e["parametros"].update(params)
        origens.append("producao:%s" % os.path.basename(os.path.abspath(de_producao)))
    if de_receita:
        _aplicar_receita(e, de_receita)
        origens.append("receita:%s" % os.path.basename(de_receita))
    e["historico"]["semeado_de"] = origens

    erros, vistos = validar_estilo(e)
    if erros:
        raise ErroEstilo("o estilo semeado não valida (%d nós conferidos):\n  %s"
                         % (vistos, "\n  ".join(erros)))
    _gravar(caminho_versao(u, slug, "v001"), e)
    _gravar(os.path.join(d, "estilo.json"), _ponteiro(e))
    caminho_sinais = os.path.join(d, "sinais.jsonl")
    if not os.path.exists(caminho_sinais):
        open(caminho_sinais, "a").close()
    _historico_linha(u, slug, "v001", "criado — %s" % ("; ".join(origens) or "vazio"))
    log("estilo %s/%s@v001 criado (%s)" % (u, slug, "; ".join(origens) or "sem semente"))
    return caminho_versao(u, slug, "v001")


def _ponteiro(e):
    return {"contrato": "benchmark.estilo-ponteiro/v1", "usuario": e["usuario"],
            "slug": e["slug"], "versao": e["versao"]}


def _historico_linha(u, slug, versao, texto):
    arq = os.path.join(dir_do_estilo(u, slug), "HISTORICO.md")
    novo = not os.path.isfile(arq)
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    with open(arq, "a", encoding="utf-8") as fh:
        if novo:
            fh.write("# Histórico — %s/%s\n\n"
                     "Uma linha por versão. `versoes/vNNN.json` é IMUTÁVEL: sem git, "
                     "imutabilidade é a única forma de histórico que resiste.\n\n" % (u, slug))
        fh.write("- **%s** · %s · %s\n" % (versao, _agora()[:19], texto))
    return arq


def _do_estilo_resolvido(dir_producao):
    arq = os.path.join(dir_producao, "estilo-resolvido.json")
    if not os.path.isfile(arq):
        raise ErroEstilo("%s não tem estilo-resolvido.json — rode `estilo.py resolver` "
                         "nessa produção antes" % dir_producao)
    r = _ler(arq)
    p = os.path.join(dir_producao, "perfil.json")
    ov = {}
    if os.path.isfile(p):
        perf = _ler(p)
        esc = escopo_para_perfil()
        for c, v in _achatar(_perfil()._sem_comentarios(
                {k: x for k, x in perf.items() if not k.startswith("_")})):
            if _perfil()._no_escopo(c, esc):
                _pôr(ov, c, v)
    return ov, {k: v for k, v in (r.get("picks") or {}).items() if v}, \
        dict(r.get("grafismo") or {}), dict(r.get("parametros") or {})


# ═══════════════════ recursos medidos → slugs do catálogo (a ponte da SPEC-41)
CONF_MIGRA = ("alta", "media")


def mapa_recursos():
    """A tabela declarada `references/recurso-para-slug.json`.

    `$BENCH_RECURSO_MAPA` troca o arquivo (é assim que o teste planta uma tabela
    de controle sem tocar na de verdade). Ausência do arquivo é SILÊNCIO com
    tabela vazia: quem não tem a tabela simplesmente não ganha pick — nada quebra,
    e nada é inventado."""
    alvo = os.environ.get("BENCH_RECURSO_MAPA") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references", "recurso-para-slug.json")
    if not os.path.isfile(alvo):
        return {}, {}
    t = _ler(alvo)
    return (t.get("mapa") or {}), (t.get("sem_equivalente") or {})


def _grafismos_da_receita(e, r):
    """`eixos.grafismo.recursos` → o bloco `grafismo` do estilo (liga/desliga por
    slug), com a procedência de CADA ligação.

    Três guardas, e as três são o ponto:
      1. só migra com `conf` alta ou média — a mesma régua que já recusa
         `cortes_por_min` de conf baixa; a guarda não é nova, o campo é;
      2. só entra recurso que a tabela declara, e só se o slug EXISTIR no
         catálogo desta instalação (catálogo é dado, e pode ter sido podado);
      3. recurso medido e sem destino não some: vira linha de prosa, para quem
         lê o histórico saber o que a referência tinha e o vocabulário não tem.

    Devolve `(ligados, prosa)`."""
    p = ((r.get("eixos") or {}).get("grafismo") or {}).get("recursos") or {}
    v = p.get("v")
    if not isinstance(v, list) or not v:
        return [], []
    if p.get("conf") not in CONF_MIGRA:
        return [], ["grafismo.recursos NÃO migrado (conf %s): %s"
                    % (p.get("conf"), ", ".join(map(str, v)))]

    mapa, sem_eq = mapa_recursos()
    cat = catalogo()
    slugs = set(_por_slug(cat)) if cat else set()
    # `presente_em` por item, para a ligação carregar em quantas referências o
    # recurso apareceu — o número que justifica o pick.
    presenca = {i.get("item"): i for i in ((p.get("disp") or {}).get("itens") or [])}

    ligados, prosa = [], []
    for rec in v:
        alvo = (mapa.get(rec) or {}).get("slug")
        if not alvo:
            prosa.append("recurso medido sem equivalente no catálogo: %s%s"
                         % (rec, " — %s" % sem_eq[rec] if rec in sem_eq else ""))
            continue
        if slugs and alvo not in slugs:
            prosa.append("recurso %s aponta para %s, que não existe neste catálogo"
                         % (rec, alvo))
            continue
        d = presenca.get(rec) or {}
        ligados.append({"slug": alvo, "recurso": rec,
                        "presente_em": d.get("presente_em"),
                        "k": d.get("k"), "de": d.get("de"),
                        "porque": (mapa.get(rec) or {}).get("porque")})
    return ligados, prosa


# ══════════════════════════════ --de-receita: a porta da SPEC-23 e da model-edit
def _aplicar_receita(e, caminho):
    """Mapeia `benchmark.edit-recipe/v1` (model-edit) OU `benchmark.estilo-edicao/v1`
    (style-extract, SPEC-23) para o estilo.

    ⚠️ MEDIDO NA EXECUÇÃO: a §1 desta spec supõe que a SPEC-23 produz um
    `edit-recipe.json`. Ela não produz — a skill entregue na onda 2 produz
    `estilo.json` com contrato `benchmark.estilo-edicao/v1`, cujo bloco
    `overlay_perfil` já é exatamente o subconjunto que a SPEC-00 §3.2 autoriza a
    um override. Os dois formatos entram por esta porta; a receita da `model-edit`
    continua valendo, e é a que a §4.4 tabela campo a campo.

    Campo ausente NÃO vira default: fica ausente, e a camada de baixo governa.
    É a convenção que o próprio edit-recipe.md declara."""
    if not os.path.isfile(caminho):
        raise ErroEstilo("receita não existe: %s" % caminho)
    r = _ler(caminho)
    contrato = r.get("schema") or r.get("contrato")
    notas = []
    ov = e["perfil_overrides"]

    if contrato == CONTRATO_EXTRAIDO:
        for c, v in _achatar(_perfil()._sem_comentarios(r.get("overlay_perfil") or {})):
            _pôr(ov, c, v)
        # a ficha do estilo EXTRAÍDO é o `ESTILO.md` ao lado dele — não existe uma
        # `intelligence/edicao/<handle>.md`, porque a SPEC-23 modela N referências
        # e não uma peça de uma pessoa. Só entra se for alcançável por caminho
        # RELATIVO (o destino da 23 pode ser $ILHA_HOME, que é absoluto).
        ficha = _relativo_limpo(os.path.join(os.path.dirname(os.path.abspath(caminho)),
                                             "ESTILO.md"))
        e["procedencia"] = {"tipo": "modelado",
                            "fonte": {"handle": r.get("slug"), "url": None,
                                      "data": (r.get("gerado_em") or "")[:10],
                                      "ficha": ficha,
                                      "corpus": [x.get("id") for x in (r.get("corpus") or [])]},
                            "nota_de_uso": ("estilo agregado de %s referência(s) pela "
                                            "style-extract; todo número carrega n e "
                                            "dispersão na ficha."
                                            % r.get("n_refs"))}
        notas.append("extraído de %s (%s refs, coerência %s)"
                     % (r.get("slug"), r.get("n_refs"), (r.get("coerencia") or {}).get("estado")))
        for eixo, chaves in (r.get("eixos") or {}).items():
            for k, p in (chaves or {}).items():
                if isinstance(p, dict) and p.get("conf") == "baixa":
                    notas.append("NÃO migrado (conf baixa): %s.%s = %s" % (eixo, k, p.get("v")))
        # 🔴 A METADE QUALITATIVA (SPEC-41). Até aqui só o `overlay_perfil` atravessava
        # — números. `recursos` saía com conf ALTA (4/4 no corpus de teste) e morria no
        # artefato porque a galeria lê o CATÁLOGO, e o catálogo não conhece a palavra
        # `tachado`. A tabela `references/recurso-para-slug.json` é a tradução, e cada
        # ligação carrega em quantas referências o recurso apareceu.
        ligados, prosa = _grafismos_da_receita(e, r)
        for g in ligados:
            e["grafismo"][g["slug"]] = True
        notas.extend(prosa)
        if ligados:
            notas.append("grafismo ligado por recurso medido: %s"
                         % ", ".join("%s←%s" % (g["slug"], g["recurso"]) for g in ligados))
        e["nota"] = e.get("nota") or "; ".join(notas[:2])
        e.setdefault("historico", {})["receita"] = dict(
            {"contrato": contrato}, **_identidade_de_arquivo(caminho))
        if ligados or prosa:
            e["historico"]["receita"]["grafismo_de_recursos"] = {
                "ligados": ligados, "sem_destino": prosa}
        return

    if contrato != CONTRATO_RECEITA:
        raise ErroEstilo("receita com contrato %r — esperado %s (model-edit) ou %s "
                         "(style-extract/SPEC-23)"
                         % (contrato, CONTRATO_RECEITA, CONTRATO_EXTRAIDO))

    m = r.get("montagem") or {}
    pads = m.get("pads_estimados_s") or {}
    for k in ("pre", "post"):
        if k in pads:
            _pôr(ov, "ritmo.pads.%s" % k, pads[k])
    gram = r.get("gramatica_de_plano")
    if gram:
        planos = r.get("planos") or []
        zooms = sorted({round(float(p.get("zoom", 1)), 3) for p in planos if p.get("zoom")})
        alternado = len(zooms) >= 2
        e["picks"]["gramatica"] = "plano-alternado" if alternado else "plano-fixo"
        _pôr(ov, "ritmo.gramatica_plano", "alternada" if alternado else "fixa")
        if alternado:
            _pôr(ov, "ritmo.zoom_alternado", [zooms[0], zooms[-1]])
    leg = (r.get("tipografia") or {}).get("legenda") or {}
    if "y_centro_pct" in leg:
        y = float(leg["y_centro_pct"])
        _pôr(ov, "legenda.y_pct", round(y / 100.0, 4) if y > 1 else round(y, 4))
    ppp = leg.get("palavras_por_pagina")
    if isinstance(ppp, list) and ppp:
        _pôr(ov, "legenda.max_palavras_pagina", int(max(ppp)))
    elif isinstance(ppp, (int, float)):
        _pôr(ov, "legenda.max_palavras_pagina", int(ppp))
    tit = (r.get("tipografia") or {}).get("titulo") or {}
    anims = [l.get("anim") for l in (tit.get("linhas") or []) if l.get("anim")]
    if anims:
        e["picks"]["gancho"] = "hook-titulo-typeon" if any(
            "type" in (a or "").lower() for a in anims) else "hook-titulo-fade"
    cadeia = (r.get("cor") or {}).get("cadeia_equivalente")
    if cadeia:
        _pôr(ov, "cor.grade", cadeia)
    lufs = (r.get("audio") or {}).get("lufs_integrado")
    if isinstance(lufs, (int, float)):
        _pôr(ov, "audio.loudness.I", float(lufs))

    fonte = r.get("fonte") or {}
    handle = (fonte.get("handle") or "").lstrip("@")
    ficha = None
    for cand in (os.path.join("intelligence", "edicao", "%s.md" % handle),):
        if handle and os.path.isfile(cand):
            ficha = cand
    e["procedencia"] = {
        "tipo": "modelado",
        "fonte": {"handle": fonte.get("handle"), "url": fonte.get("url"),
                  "data": _agora()[:10], "ficha": ficha},
        "nota_de_uso": ("parâmetro medido e mecanismo são transferíveis; ativo autoral "
                        "(fonte, .cube, SFX, lettering) e identidade combinada NÃO."),
    }
    # §4.4: o que NÃO migra automaticamente vira nota e fica para revisão humana.
    fam = (leg.get("familia") or (tit.get("linhas") or [{}])[0].get("familia"))
    if fam:
        notas.append("tipografia.familia medida: %s — NÃO migrada (identidade)" % fam)
    if (r.get("audio") or {}).get("cadeia_equivalente"):
        notas.append("audio.cadeia_equivalente medida — NÃO migrada (o loudness canônico "
                     "de 2 passes é da SPEC-02): %s"
                     % (r["audio"]["cadeia_equivalente"])[:80])
    dens = r.get("densidade") or {}
    if dens.get("elementos_por_10s") is not None:
        notas.append("densidade %s elem/10s — NÃO migrada (é leitura do plano)"
                     % dens["elementos_por_10s"])
    if notas:
        e["nota"] = (e.get("nota") + " · " if e.get("nota") else "") + " · ".join(notas)
    e.setdefault("historico", {})["receita"] = dict(
        {"contrato": contrato}, **_identidade_de_arquivo(caminho))


def _rel(p):
    try:
        r = os.path.relpath(p, os.getcwd())
        return r if not r.startswith("..") else os.path.basename(p)
    except ValueError:
        return os.path.basename(p)


def _relativo_limpo(caminho):
    """O caminho relativo ao cwd, ou None se ele sair da árvore. `None` é melhor
    que um `../../..` que só resolve na máquina de quem escreveu."""
    if not os.path.exists(caminho):
        return None
    r = os.path.relpath(caminho, os.getcwd())
    return None if (r.startswith("..") or os.path.isabs(r)) else r


def _identidade_de_arquivo(caminho):
    """🔴 A IDENTIDADE de um insumo, nunca o CAMINHO dele.

    Medido na execução desta spec: gravar `data/adhoc/modelagem-edicao/
    edit-recipe.json` dentro de `versoes/v001.json` reprovou o próprio aceite
    §7.7 (`grep -rnE "creators/|input/|data/" estilos/*/*/versoes/*.json` → 0).
    E com razão: `data/` é diretório NOSSO, não do produto — o estilo que o cita
    deixa de ser portátil na primeira máquina que não o tem.
    Nome do arquivo + sha256 identificam o insumo sem amarrar a instalação. A
    única referência externa permitida num estilo continua sendo
    `procedencia.fonte.ficha` para `intelligence/edicao/` (§3.8)."""
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 16), b""):
            h.update(b)
    return {"arquivo": os.path.basename(caminho), "sha256": h.hexdigest()}


# ═══════════════════════════════════════════════════════════════════ resolver
def resolver(dir_producao, perfil_nome, usuario=None, ref=None, como_gravado=False,
             sets=None, pedido_compilado=None, creator=None, quieto=False):
    """As 6 camadas, na ordem, com `_origem` por folha. Dois arquivos:
    `<dir>/perfil.json` (forma inalterada) e `<dir>/estilo-resolvido.json`.

    ⚠️ O nome é `estilo-resolvido.json`, na RAIZ da produção. Não é `estilo.json`:
    a SPEC-16 §3.1 reserva `<dir>/.preview/estilo.json` para o canal de volta da
    UI, com outro contrato. Dois arquivos com o mesmo nome e contratos diferentes
    é o desfecho que a SPEC-16 §3.12 já teve que consertar entre duas specs."""
    P = _perfil()
    sets = list(sets or [])
    esc = escopo()
    esc_perfil = escopo_para_perfil(esc)
    cat = catalogo()
    camadas_msg = ["perfil:%s" % perfil_nome]

    # ── de onde vem a referência do estilo
    gravado = None
    arq_perfil = os.path.join(dir_producao, "perfil.json")
    if como_gravado:
        if not os.path.isfile(arq_perfil):
            raise ErroEstilo("--como-gravado: %s não existe" % arq_perfil)
        gravado = (_ler(arq_perfil).get("_procedencia") or {})
        if not gravado.get("estilo"):
            raise ErroEstilo("--como-gravado: %s não registra estilo nenhum "
                             "(_procedencia.estilo ausente)" % arq_perfil)
        ref = gravado["estilo"]
        usuario = usuario or gravado.get("usuario")
        perfil_nome = gravado.get("perfil") or perfil_nome

    # ── camada 3: o estilo do usuário (semeando `padrao` se a biblioteca é nova)
    u = None
    if ref:
        u = parse_ref(ref, usuario)[0]
    else:
        try:
            u = usuario_corrente(usuario)
        except ErroEstilo:
            u = None
        if u and not versoes(u, "padrao") and not _estilos_de(u):
            criar("%s/padrao" % u, "Padrão do %s" % u, [perfil_nome],
                  usuario=u, de_perfil=perfil_nome)
            log("§3.10: biblioteca de %r estava vazia — estilo `padrao` semeado. "
                "O usuário sai da primeira sessão com um objeto real, nomeado e "
                "editável, não com uma pasta vazia." % u)
        if u and versoes(u, "padrao"):
            ref = "%s/padrao" % u

    est, meta, ov3 = None, None, {}
    if ref:
        est, meta = resolver_estilo(ref, usuario)
        ov3 = perfil_overrides_do_estilo(est)
        conferir_caminhos(ov3, "estilo:%s" % ref, esc)
        if perfil_nome not in (est.get("perfis") or []):
            log("aviso: o estilo %s/%s declara perfis %s e a peça é %r — resolvendo "
                "assim mesmo, mas os picks podem não servir."
                % (meta["usuario"], meta["slug"], est.get("perfis"), perfil_nome))

    # ── aviso de deriva quando o estilo andou desde a gravação (§3.7)
    if gravado and gravado.get("estilo") and not como_gravado:
        pass
    if not como_gravado and os.path.isfile(arq_perfil) and meta:
        antes = (_ler(arq_perfil).get("_procedencia") or {}).get("estilo")
        if antes and antes != "%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"]):
            _avisar_deriva(antes, meta, usuario)

    # ── camada 4: a escolha pontual da UI, já aplicada nesta produção
    camadas, avisos = [], []
    if est:
        camadas.append(("estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"]),
                        ov3))
        camadas_msg.append("catalogo")
        camadas_msg.append(camadas[-1][0])
    picks_ui, graf_ui = {}, {}
    for ev in eventos_ui(dir_producao):
        # os DOIS contratos: a galeria grava `v2` desde a SPEC-19, e este filtro
        # pedia `v1`. Enquanto pediu, a CAMADA 4 inteira — "escolha pontual da UI",
        # que a docstring deste arquivo declara na precedência — não existia para
        # nenhum evento real: o `resolver` saía verde, com `camadas` terminando no
        # estilo do usuário, como se ninguém tivesse escolhido nada na tela.
        if ev["payload"].get("contrato") not in (
                CONTRATO_UI_ESTILO, CONTRATO_UI_ESTILO_V2, CONTRATO_UI_ESTILO_V3):
            continue
        ov4, p4, g4, av = _traduzir_evento_ui(ev["payload"], cat)
        avisos += av
        picks_ui.update(p4)
        graf_ui.update(g4)
        if ov4:
            camadas.append(("ui:%s" % ev["arquivo"], ov4))
            camadas_msg.append("ui:%s" % ev["arquivo"])
        elif p4 or g4:
            camadas_msg.append("ui:%s" % ev["arquivo"])

    # ── camada 5: o pedido, já compilado num diff explícito
    ops_pedido = []
    if pedido_compilado:
        pd = _ler(pedido_compilado)
        if pd.get("contrato") != CONTRATO_PEDIDO:
            raise ErroEstilo("%s: contrato %r, esperado %s"
                             % (pedido_compilado, pd.get("contrato"), CONTRATO_PEDIDO))
        ops_pedido = pd.get("operacoes") or []
        if ops_pedido:
            rot = 'pedido:"%s"' % (pd.get("texto") or "")[:60]
            camadas.append((rot, _ov_do_pedido(ops_pedido)))
            camadas_msg.append(rot)

    # ── a LINHA DE BASE: o que o estilo daria SEM as camadas pontuais.
    # 🔴 É isto que define uma correção. Medido na execução: comparar o evento da
    # UI contra o `estilo-resolvido.json` (a leitura literal da §3.6 passo 2) dá
    # SEMPRE zero diferença, porque a camada 4 já está mergeada lá dentro — o
    # colhedor de sinais saía verde e vazio, que é o defeito mais caro deste repo.
    # A correção é o delta entre o que o ESTILO dá e o que o usuário pediu NESTA
    # peça, e é isso que `correcoes[]` guarda.
    camadas_estilo = [(r, o) for r, o in camadas if r.startswith("estilo:")]
    _c0, p0, _o0 = P.resolver_completo(
        dir_producao, perfil_nome, creator=creator, sets=sets, quieto=True,
        camadas=camadas_estilo, escopo_camadas=esc_perfil, escrever=False)

    # ── o merge (é o do perfil.py; esta spec não reimplementa merge nenhum)
    caminho, p, origem = P.resolver_completo(
        dir_producao, perfil_nome, creator=creator, sets=sets, quieto=quieto,
        usuario=(meta["usuario"] if meta else usuario),
        estilo=("%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])) if meta else None,
        estilo_sha256=(_sha256(_ler(meta["arquivo"])) if meta else None),
        camadas=camadas, escopo_camadas=esc_perfil)

    # o pedido tem rastro FINO no _origem: o texto e o de→para, não só o rótulo
    for o in ops_pedido:
        if o["caminho"] in origem:
            origem[o["caminho"]] = 'pedido:"%s" → %s→%s' % (
                (_ler(pedido_compilado).get("texto") or "")[:40], o["de"], o["para"])

    # ── os picks: camada 2 (catálogo) sob a 3 (estilo) sob a 4 (UI)
    picks, origem_picks = {}, {}
    padroes = defaults_do_catalogo(cat, perfil_nome)
    for g in GRUPOS_PICK:
        if g in padroes:
            picks[g] = padroes[g]
            origem_picks["picks.%s" % g] = "catalogo:defaultDe[%s]" % perfil_nome
    if est:
        for g, slug in (est.get("picks") or {}).items():
            picks[g] = slug          # `null` explícito DESLIGA o grupo (≠ ausente)
            origem_picks["picks.%s" % g] = \
                "estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])
    for g, slug in picks_ui.items():
        picks[g] = slug
        origem_picks["picks.%s" % g] = "ui:%s" % next(
            (e["arquivo"] for e in reversed(eventos_ui(dir_producao))
             if e["payload"].get("contrato") == CONTRATO_UI_ESTILO), "?")
    for g in GRUPOS_PICK:
        picks.setdefault(g, None)
        origem_picks.setdefault("picks.%s" % g, "catalogo:sem defaultDe[%s]" % perfil_nome)

    grafismo = dict((est or {}).get("grafismo") or {})
    for g in grafismo:
        origem_picks["grafismo.%s" % g] = \
            "estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])
    for g, v in graf_ui.items():
        grafismo[g] = v
        origem_picks["grafismo.%s" % g] = "ui"
    parametros = copy.deepcopy((est or {}).get("parametros") or {})
    for slug, params in parametros.items():
        for nome in params:
            origem_picks["parametros.%s.%s" % (slug, nome)] = \
                "estilo:%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])

    # ── o mapa _origem: UMA entrada por FOLHA, do perfil.json E daqui
    origem_total = {}
    for c, _v in _achatar({k: v for k, v in p.items() if not k.startswith("_")}):
        origem_total[c] = origem.get(c, "?")
    origem_total.update(origem_picks)
    orfas = [c for c, v in origem_total.items() if v == "?"]
    if orfas:
        raise ErroEstilo("folha sem origem (%d): %s — o mapa _origem é o que torna a "
                         "precedência auditável; folha órfã é o mapa mentindo"
                         % (len(orfas), ", ".join(sorted(orfas)[:8])))

    # ── correções: o que as camadas 4 e 5 mudaram em relação à linha de base
    correcoes = []
    for c, v in _achatar({k: x for k, x in p.items() if not k.startswith("_")}):
        rot = origem.get(c, "")
        if not (rot.startswith("ui:") or rot.startswith("pedido:")):
            continue
        tem, antes = _no(p0, c)
        if tem and _canonico(antes) == _canonico(v):
            continue
        correcoes.append({"path": c, "de": antes if tem else None, "para": v,
                          "camada": rot})
    for g, slug in picks.items():
        rot = origem_picks.get("picks.%s" % g, "")
        if not rot.startswith("ui:"):
            continue
        antes = (est or {}).get("picks", {}).get(g, padroes.get(g))
        if antes == slug:
            continue
        correcoes.append({"path": "picks.%s" % g, "de": antes, "para": slug,
                          "camada": rot})
    for g, v in graf_ui.items():
        antes = ((est or {}).get("grafismo") or {}).get(g)
        if antes == v:
            continue
        correcoes.append({"path": "grafismo.%s" % g, "de": antes, "para": v,
                          "camada": "ui"})

    resolvido = {
        "contrato": CONTRATO_RESOLVIDO,
        "resolvido_em": _agora(),
        "perfil": perfil_nome,
        "usuario": meta["usuario"] if meta else usuario,
        "estilo": ("%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"])) if meta else None,
        "estilo_sha256": _sha256(_ler(meta["arquivo"])) if meta else None,
        "camadas": camadas_msg,
        "picks": picks,
        "grafismo": grafismo,
        "parametros": parametros,
        "correcoes": correcoes,
        "avisos": avisos,
        "_origem": dict(sorted(origem_total.items())),
    }
    destino = _gravar(os.path.join(dir_producao, "estilo-resolvido.json"), resolvido)
    log("camadas: %s" % " → ".join(camadas_msg))
    if cat is None:
        log("modo degradado: sem catalogo.json — camada 2 (defaults por `defaultDe`) "
            "não participou. Os `picks` saem só do estilo.")
    for a in avisos:
        log("aviso: %s" % a)
    return caminho, destino, resolvido


def _estilos_de(u):
    d = os.path.join(dir_estilos(), u)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if not n.startswith("_") and os.path.isdir(os.path.join(d, n)))


def _avisar_deriva(antes, meta, usuario):
    """§3.7: sem `--como-gravado`, resolver com o HEAD e AVISAR o que mudou.
    Nunca em silêncio — a peça remontada em outubro com um estilo que andou é o
    caso em que o silêncio custa uma entrega."""
    try:
        u0, s0, v0 = parse_ref(antes, usuario)
        a, _ = resolver_estilo("%s/%s@%s" % (u0, s0, v0), usuario)
        b, _ = resolver_estilo("%s/%s@%s" % (meta["usuario"], meta["slug"], meta["versao"]),
                               usuario)
    except ErroEstilo as ex:
        log("aviso: o perfil.json registra o estilo %s e não consegui compará-lo com o "
            "HEAD (%s)" % (antes, ex))
        return
    difs = _diff_estilos(a, b)
    log("⚠️ esta produção foi resolvida com %s e o HEAD agora é %s@%s. "
        "%d caminho(s) diferem:" % (antes, meta["slug"], meta["versao"], len(difs)))
    for c, x, y in difs:
        log("   %s: %s → %s" % (c, _canonico(x), _canonico(y)))
    log("   `--como-gravado` reproduz a peça original.")


def _diff_estilos(a, b):
    ca = dict(_achatar({k: v for k, v in a.items()
                        if k in ("picks", "grafismo", "parametros", "perfil_overrides")}))
    cb = dict(_achatar({k: v for k, v in b.items()
                        if k in ("picks", "grafismo", "parametros", "perfil_overrides")}))
    out = []
    for c in sorted(set(ca) | set(cb)):
        if _canonico(ca.get(c)) != _canonico(cb.get(c)):
            out.append((c, ca.get(c), cb.get(c)))
    return out


# ═════════════════════════════════════════════════════════════ sinais (§3.6)
def _classe(caminho, esc):
    if _perfil()._no_escopo(caminho, escopo_para_perfil(esc)) or caminho.startswith("picks.") \
            or caminho.startswith("grafismo."):
        return "candidato-a-estilo"
    return "fora-de-escopo"


def sinais(dir_producao, ref=None, usuario=None):
    """`.preview/aplicados/*.json` + `correcoes[]` → uma linha por diferença.

    🔴 A classe `peca` é o DEFAULT para tudo que referencia um `sid`, uma janela
    de tempo ou um elemento nomeado. "O corte come o começo do *porque*" é sobre
    AQUELE corte. Inverter isso enche o `.jsonl` de ruído e a primeira proposta já
    sai errada.

    🔴 E a comparação é contra a LINHA DE BASE (camadas 1–3), não contra o
    `estilo-resolvido.json`: a camada 4 já está mergeada nele, então o diff contra
    ele é sempre vazio. `correcoes[]` é o delta calculado no `resolver`, quando as
    duas resoluções ainda existem lado a lado."""
    arq_r = os.path.join(dir_producao, "estilo-resolvido.json")
    if not os.path.isfile(arq_r):
        raise ErroEstilo("%s não existe — rode `estilo.py resolver` nesta produção "
                         "antes de colher sinais" % arq_r)
    r = _ler(arq_r)
    ref = ref or r.get("estilo")
    if not ref:
        raise ErroEstilo("a produção %s foi resolvida SEM estilo — não há biblioteca "
                         "para onde mandar o sinal" % dir_producao)
    u, slug, _v = parse_ref(ref, usuario)
    esc = escopo()
    cat = catalogo()
    alvo = os.path.join(dir_do_estilo(u, slug), "sinais.jsonl")
    ja = set()
    if os.path.isfile(alvo):
        for linha in open(alvo, encoding="utf-8"):
            linha = linha.strip()
            if linha:
                sg = json.loads(linha)
                # A PRODUÇÃO entra na chave. Sem ela, duas produções cujo evento
                # tenha o mesmo NOME de arquivo (o nome é `<timestamp>-<tipo>-<n>`,
                # e produções montadas no mesmo segundo colidem) contavam como
                # uma: o segundo `sinais` saía "0 sinal(is) novo(s)" e o `propor`
                # seguinte via 1 produção onde havia 2 — que é justamente o número
                # que decide promoção. Medido nesta sessão, com 3 produções.
                ja.add((sg.get("producao"), sg.get("evento"), sg.get("path")))

    evs = eventos_ui(dir_producao)
    por_arquivo = {e["arquivo"]: e for e in evs}
    # EXATAMENTE o mesmo rótulo que `_sinal` grava em `producao` (`_rel`, que às
    # vezes é caminho relativo e às vezes basename) — a chave de deduplicação tem
    # que ser a mesma dos dois lados, senão ela nunca casa e todo sinal volta a
    # ser gravado a cada execução
    nome_prod = _rel(dir_producao)
    novos = []

    # (a) as correções medidas no resolver — camada 4/5 contra a linha de base
    for c in r.get("correcoes") or []:
        camada = c.get("camada") or ""
        arq = camada.split(":", 1)[1] if camada.startswith("ui:") else camada
        ev = por_arquivo.get(arq) or {"arquivo": arq}
        if (nome_prod, ev["arquivo"], c["path"]) in ja:
            continue
        novos.append(_sinal(dir_producao, ref, ev, c["path"], c.get("de"),
                            c.get("para"), _classe(c["path"], esc)))

    # (b) o que a UI mandou e NÃO tem destino: continua sendo sinal, com o motivo
    for ev in evs:
        pay = ev["payload"]
        if pay.get("contrato") == CONTRATO_UI_AJUSTES:
            n = len(pay.get("notas") or []) + len(pay.get("operacoes") or []) + \
                len(pay.get("elementos") or [])
            if n and (nome_prod, ev["arquivo"], "(timeline)") not in ja:
                novos.append(_sinal(dir_producao, ref, ev, "(timeline)", None, None,
                                    "peca", nota="%d correção(ões) de timeline: notas/"
                                    "operações/elementos são sobre um `sid`, uma janela "
                                    "ou um elemento nomeado — nunca contam para promoção"
                                    % n))
            continue
        _ov4, _p4, _g4, avisos = _traduzir_evento_ui(pay, cat)
        for k, v in (pay.get("elementos") or {}).items():
            path = "elementos.%s" % k
            if any(a.startswith("elementos.%s " % k) for a in avisos) and \
                    (nome_prod, ev["arquivo"], path) not in ja:
                novos.append(_sinal(dir_producao, ref, ev, path, None, v,
                                    "fora-de-escopo",
                                    nota="não é slug do grupo `grafismo` do catálogo — "
                                         "caixa desmarcada é um NÃO explícito, então o "
                                         "sinal fica registrado; aplicá-lo exigiria uma "
                                         "entrada nova no catálogo (SPEC-15)"))
        if pay.get("acento") and (nome_prod, ev["arquivo"], "acento") not in ja:
            novos.append(_sinal(dir_producao, ref, ev, "acento", None, pay["acento"],
                                "fora-de-escopo",
                                nota="acento é cor de TEMA: o estilo referencia o slug "
                                     "do tema, nunca o hex (SPEC-15 §9)"))

    os.makedirs(os.path.dirname(alvo), exist_ok=True)
    with open(alvo, "a", encoding="utf-8") as fh:
        for sg in novos:
            fh.write(_canonico(sg) + "\n")
    log("%d evento(s) lidos, %d correção(ões) medida(s), %d sinal(is) novo(s) "
        "(%d já registrados)"
        % (len(evs), len(r.get("correcoes") or []), len(novos), len(ja)))
    return alvo, novos


def _sinal(dir_producao, ref, ev, path, de, para, classe, nota=None):
    direcao = None
    if isinstance(de, (int, float)) and isinstance(para, (int, float)) \
            and not isinstance(de, bool) and not isinstance(para, bool):
        direcao = "+" if para > de else ("-" if para < de else "=")
    s = {"contrato": CONTRATO_SINAL, "observado_em": _agora(),
         "producao": _rel(dir_producao), "estilo": ref, "origem": "ui",
         "evento": ev["arquivo"], "path": path, "de": de, "para": para,
         "direcao": direcao, "classe": classe}
    if classe == "fora-de-escopo" and not nota:
        nota = ("isto é sinal sobre o PERFIL, não sobre o estilo. Se repetir, o "
                "caminho é criar/ajustar um perfil de peça, não promover o estilo.")
    if nota:
        s["nota"] = nota
    return s


def ler_sinais(u, slug):
    arq = os.path.join(dir_do_estilo(u, slug), "sinais.jsonl")
    if not os.path.isfile(arq):
        return []
    out = []
    for linha in open(arq, encoding="utf-8"):
        linha = linha.strip()
        if linha:
            out.append(json.loads(linha))
    return out


# ═════════════════════════════════════════════════════════════ propor (§3.6)
def propor(ref, usuario=None, primeira_peca=None):
    """As 4 guardas contra sobreajuste. **NÃO ESCREVE UM BYTE.**"""
    u, slug, _v = parse_ref(ref, usuario)
    esc = escopo()
    pr = esc.get("promocao") or {}
    min_prod = int(pr.get("min_producoes", 3))
    janela = int(pr.get("janela", 12))
    contra_rec = int(pr.get("contra_recentes", 3))

    S = [s for s in ler_sinais(u, slug)]
    linhas = ["estilo: %s/%s@%s" % (u, slug, head(u, slug) or "—"),
              "sinais lidos: %d  (candidato-a-estilo %d · peca %d · fora-de-escopo %d)"
              % (len(S), sum(1 for s in S if s.get("classe") == "candidato-a-estilo"),
                 sum(1 for s in S if s.get("classe") == "peca"),
                 sum(1 for s in S if s.get("classe") == "fora-de-escopo")),
              "guardas: min_producoes=%d · janela=%d produções · contra_recentes=%d"
              % (min_prod, janela, contra_rec)]

    # a janela é de PRODUÇÕES, não de sinais: ordem de primeira aparição
    ordem = []
    for s in sorted(S, key=lambda x: x.get("observado_em") or ""):
        if s.get("producao") not in ordem:
            ordem.append(s.get("producao"))
    dentro = set(ordem[-janela:]) if janela else set(ordem)
    linhas.append("produções no .jsonl: %d · dentro da janela: %d"
                  % (len(ordem), len(dentro)))

    por_path = {}
    for s in S:
        if s.get("classe") != "candidato-a-estilo":
            continue
        por_path.setdefault(s["path"], []).append(s)

    propostas, recusas = [], []
    for path, sig in sorted(por_path.items()):
        na_janela = [s for s in sig if s.get("producao") in dentro]
        fora_janela = len(sig) - len(na_janela)
        if not na_janela:
            recusas.append((path, "todos os %d sinais estão fora da janela de %d "
                                  "produções (peso 0)" % (len(sig), janela)))
            continue
        alvo = _valor_dominante(na_janela)
        a_favor = [s for s in na_janela if _canonico(s.get("para")) == _canonico(alvo)]
        contra = [s for s in na_janela if _canonico(s.get("para")) != _canonico(alvo)]
        prod_favor = {s.get("producao") for s in a_favor}
        n_producoes = len(prod_favor)
        saldo = len(prod_favor) - len({s.get("producao") for s in contra})

        # guarda 1 + 4 — repetição em produções DISTINTAS
        if n_producoes < min_prod:
            recusas.append((path,
                            "n_producoes=%d < %d (min_producoes de "
                            "<estilos>/_escopo.json). %d correção(ões) em %d "
                            "produção(ões) distinta(s): %s."
                            % (n_producoes, min_prod, len(a_favor), n_producoes,
                               ", ".join(sorted(prod_favor)))))
            continue
        # guarda 3 — contra-sinal cancela
        recentes = [p for p in ordem if p in dentro][-contra_rec:]
        contra_recente = [s for s in contra if s.get("producao") in recentes]
        if contra_recente or saldo < min_prod:
            recusas.append((path,
                            "decisão por peça, não estilo. saldo=%d (a favor %d "
                            "produção(ões), contra %d) · contra nas %d mais recentes: %d.\n"
                            "     a favor: %s\n     contra:  %s\n"
                            "     Quando o mesmo parâmetro é empurrado para os dois lados, "
                            "a conclusão certa NÃO é escolher um lado: é que esse "
                            "parâmetro é decisão por peça e não pertence ao estilo."
                            % (saldo, len(prod_favor),
                               len({s.get('producao') for s in contra}),
                               contra_rec, len(contra_recente),
                               "; ".join("%s→%s@%s" % (s.get("de"), s.get("para"),
                                                       s.get("producao")) for s in a_favor),
                               "; ".join("%s→%s@%s" % (s.get("de"), s.get("para"),
                                                       s.get("producao")) for s in contra)
                               or "—")))
            continue
        propostas.append({
            "path": path, "para": alvo,
            "de": a_favor[0].get("de"),
            "n_producoes": n_producoes, "saldo": saldo,
            "fora_da_janela": fora_janela,
            "sinais": ["%s@%s" % (s.get("producao"), (s.get("observado_em") or "")[:10])
                       for s in a_favor],
            "motivo": "%d correções na mesma direção em %d produções distintas"
                      % (len(a_favor), n_producoes),
        })

    if primeira_peca:
        linhas.append("")
        linhas.append(_primeira_peca(primeira_peca))

    linhas.append("")
    if propostas:
        linhas.append("PROPOSTO (%d) — nada foi escrito:" % len(propostas))
        for p in propostas:
            linhas.append("  %s: %s → %s" % (p["path"], _canonico(p["de"]),
                                             _canonico(p["para"])))
            linhas.append("     %s" % p["motivo"])
            for s in p["sinais"]:
                linhas.append("       · %s" % s)
        linhas.append("")
        linhas.append("Para aplicar: estilo.py promover %s/%s --confirmar --so %s"
                      % (u, slug, ",".join(p["path"] for p in propostas)))
    else:
        linhas.append("PROPOSTO: nada. (Na dúvida entre propor e não propor, não "
                      "propomos: um falso negativo custa um comando, um falso positivo "
                      "custa a confiança no sistema inteiro.)")
    if recusas:
        linhas.append("")
        linhas.append("NÃO PROPOSTO (%d):" % len(recusas))
        for path, motivo in recusas:
            linhas.append("  %s: %s" % (path, motivo))
    return propostas, "\n".join(linhas)


def _valor_dominante(sinais_):
    cont = {}
    for s in sinais_:
        k = _canonico(s.get("para"))
        cont[k] = cont.get(k, 0) + 1
    melhor = max(cont.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return json.loads(melhor)


def _primeira_peca(dir_producao):
    arq = os.path.join(dir_producao, "estilo-resolvido.json")
    if not os.path.isfile(arq):
        return "primeira-peça: %s não tem estilo-resolvido.json" % dir_producao
    r = _ler(arq)
    L = ["as escolhas efetivamente usadas em %s:" % _rel(dir_producao)]
    for g, slug in sorted((r.get("picks") or {}).items()):
        L.append("  picks.%s = %s   (%s)" % (g, slug, (r.get("_origem") or {}).get(
            "picks.%s" % g, "?")))
    ligados = [k for k, v in (r.get("grafismo") or {}).items() if v]
    L.append("  grafismo ligado: %s" % (", ".join(sorted(ligados)) or "nenhum"))
    L.append("Viram um estilo nomeado? `estilo.py criar <u>/<slug> --nome … "
             "--de-producao %s`" % _rel(dir_producao))
    return "\n".join(L)


# ═══════════════════════════════════════════════════════════ promover (§3.6)
def promover(ref, confirmar=False, so=None, por=None, usuario=None):
    u, slug, _v = parse_ref(ref, usuario)
    propostas, texto = propor("%s/%s" % (u, slug), usuario)
    if so:
        alvo = {x.strip() for x in so.split(",") if x.strip()}
        propostas = [p for p in propostas if p["path"] in alvo]
    if not propostas:
        raise ErroEstilo("nada a promover.\n%s" % texto)
    if not confirmar:
        raise ErroEstilo(
            "NADA foi escrito. Isto é o que `--confirmar` faria:\n%s\n\n"
            "Promoção automática é o modo de falha mais provável desta feature: "
            "'sempre que eu corrijo X ele passa a fazer X' degrada em duas semanas, "
            "porque as três primeiras correções de qualquer estilo são sobre a PEÇA, "
            "não sobre o gosto." % texto)

    atual = carregar_estilo(u, slug, usuario_pedido=u)
    versao_atual = atual.get("versao")
    nova = "v%03d" % (int(versao_atual[1:]) + 1)
    novo = copy.deepcopy(atual)
    novo.pop("_arquivo", None)
    novo["versao"] = nova
    mudou = []
    for p in propostas:
        alvo_bloco = "perfil_overrides." + p["path"] if not p["path"].startswith(
            ("picks.", "grafismo.", "parametros.")) else p["path"]
        tem, antes = _no(novo, alvo_bloco)
        _pôr(novo, alvo_bloco, p["para"])
        mudou.append({"path": alvo_bloco, "de": antes if tem else p.get("de"),
                      "para": p["para"], "motivo": p["motivo"], "sinais": p["sinais"]})
    novo["historico"] = {
        "criado_em": (atual.get("historico") or {}).get("criado_em"),
        "derivado_de": versao_atual,
        "confirmado_por": por or u,
        "promovido_em": _agora(),
        "mudou": mudou,
    }
    if (atual.get("historico") or {}).get("semeado_de"):
        novo["historico"]["semeado_de"] = atual["historico"]["semeado_de"]
    erros, _n = validar_estilo(novo)
    if erros:
        raise ErroEstilo("a versão promovida não valida:\n  %s" % "\n  ".join(erros))

    # 🔴 versoes/v001..vN NÃO são tocados. É isso que mantém reproduzível a peça
    # que foi editada em v002.
    caminho = caminho_versao(u, slug, nova)
    if os.path.exists(caminho):
        raise ErroEstilo("%s já existe — versão é IMUTÁVEL, não se reescreve" % caminho)
    _gravar(caminho, novo)
    _gravar(os.path.join(dir_do_estilo(u, slug), "estilo.json"), _ponteiro(novo))
    _historico_linha(u, slug, nova, "; ".join(
        "%s %s→%s (%s)" % (m["path"], _canonico(m["de"]), _canonico(m["para"]), m["motivo"])
        for m in mudou))
    log("promovido: %s/%s %s → %s (%d caminho(s))" % (u, slug, versao_atual, nova, len(mudou)))
    return caminho


# ═══════════════════════════════════════════════════ export / import (§3.8)
def exportar(ref, saida, usuario=None):
    e, meta = resolver_estilo(ref, usuario)
    bruto = carregar_estilo(meta["usuario"], meta["slug"], meta["versao"],
                            usuario_pedido=usuario)
    bruto.pop("_arquivo", None)
    # trava 3: um estilo é CONFIGURAÇÃO, não pacote.
    ofensas = []
    for c, v in _achatar(bruto):
        if not isinstance(v, str):
            continue
        if RE_BINARIO.search(v.strip()):
            ofensas.append((c, v, "referencia um ativo binário"))
        elif len(v) > 512 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", v):
            ofensas.append((c, v[:40] + "…", "parece base64 com %d chars" % len(v)))
    if ofensas:
        raise ErroEstilo(
            "export RECUSADO — %d campo(s) carregam ativo, não configuração:\n%s\n"
            "Parâmetro medido e mecanismo são transferíveis; ativo autoral (a fonte "
            "que ele comprou, o .cube dele, o SFX dele, o lettering) não é. O export "
            "nunca carrega binário."
            % (len(ofensas), "\n".join("  %s = %s  (%s)" % o for o in ofensas)))
    cat = catalogo()
    por_slug = _por_slug(cat)
    slugs = sorted({s for s in (e.get("picks") or {}).values() if s} |
                   set((e.get("grafismo") or {}).keys()) |
                   set((e.get("parametros") or {}).keys()))
    pacote = {
        "contrato": CONTRATO_EXPORT,
        "exportado_em": _agora(),
        "estilo": bruto,
        "requisitos": {
            "contrato_estilo": CONTRATO,
            "slugs_do_catalogo": [{"slug": s, "grupo": (por_slug.get(s) or {}).get("grupo")}
                                  for s in slugs],
            "perfis": list(e.get("perfis") or []),
        },
        "_nota": ("Auto-contido em DECLARAÇÃO, não em conteúdo: leva o estilo e os slugs "
                  "que ele usa, nunca binário (fonte, .cube, .wav, frame)."),
    }
    caminho = _gravar(saida, pacote)
    log("exportado %s/%s@%s → %s (%d slug(s) requeridos)"
        % (meta["usuario"], meta["slug"], meta["versao"], caminho, len(slugs)))
    return caminho


def importar(arquivo, usuario, slug=None):
    pac = _ler(arquivo)
    if pac.get("contrato") != CONTRATO_EXPORT:
        raise ErroEstilo("%s: contrato %r, esperado %s"
                         % (arquivo, pac.get("contrato"), CONTRATO_EXPORT))
    e = copy.deepcopy(pac["estilo"])
    e["usuario"] = usuario
    e["slug"] = slug or e["slug"]
    e["versao"] = "v001"
    if e.get("herda"):
        # o pai não vem no pacote: herança não atravessa instalação.
        e["_herda_original"] = e["herda"]
        e["herda"] = None
    cat = catalogo()
    por_slug = _por_slug(cat)
    faltando, ausentes = [], []
    for req in (pac.get("requisitos") or {}).get("slugs_do_catalogo", []):
        if req["slug"] not in por_slug:
            faltando.append(req["slug"])
    if faltando:
        # 🔴 NÃO falha. Um estilo 80% aplicável é útil; um erro duro torna
        # compartilhar inviável, e compartilhar é metade do valor de produto disto.
        for g, s in list((e.get("picks") or {}).items()):
            if s in faltando:
                del e["picks"][g]        # ausente → a camada 2 (catálogo) governa
        for s in list((e.get("grafismo") or {}).keys()):
            if s in faltando:
                del e["grafismo"][s]
        for s in list((e.get("parametros") or {}).keys()):
            if s in faltando:
                del e["parametros"][s]
        e["estado"] = "incompleto"
        e["requisitos"] = {"slugs_ausentes": faltando}
    else:
        e["estado"] = "pronto"
    # a ficha de modelagem é registro NOSSO: ela pode simplesmente não existir na
    # máquina de destino. Importar não pode falhar por isso (um estilo 80%%
    # aplicável é útil) — o ponteiro sobrevive renomeado, e o estado diz a verdade.
    f = (e.get("procedencia") or {}).get("fonte") or {}
    if f.get("ficha") and not os.path.isfile(f["ficha"]):
        ausentes.append("ficha:%s" % f["ficha"])
        f["ficha_ausente"], f["ficha"] = f.pop("ficha"), None
        e["estado"] = "incompleto"
        e.setdefault("requisitos", {})["ficha_ausente"] = f["ficha_ausente"]
    e.setdefault("historico", {})["importado_de"] = {
        "arquivo": _rel(arquivo), "em": _agora(),
        "estilo_original": "%s/%s@%s" % (pac["estilo"].get("usuario"),
                                         pac["estilo"].get("slug"),
                                         pac["estilo"].get("versao"))}
    erros, _n = validar_estilo(e)
    if erros:
        raise ErroEstilo("o estilo importado não valida:\n  %s" % "\n  ".join(erros))
    if versoes(usuario, e["slug"]):
        raise ErroEstilo("%s/%s já existe — escolha outro `--slug`" % (usuario, e["slug"]))
    caminho = _gravar(caminho_versao(usuario, e["slug"], "v001"), e)
    _gravar(os.path.join(dir_do_estilo(usuario, e["slug"]), "estilo.json"), _ponteiro(e))
    open(os.path.join(dir_do_estilo(usuario, e["slug"]), "sinais.jsonl"), "a").close()
    _historico_linha(usuario, e["slug"], "v001", "importado de %s (estado: %s)"
                     % (_rel(arquivo), e["estado"]))
    if ausentes:
        log("estado: incompleto — %s. O ponteiro fica em "
            "`procedencia.fonte.ficha_ausente`, não some." % "; ".join(ausentes))
    if faltando:
        log("estado: incompleto — %d slug(s) do catálogo não existem aqui: %s. "
            "O que falta cai para o default do catálogo local, e o _origem mostra isso."
            % (len(faltando), ", ".join(faltando)))
    return caminho


# ══════════════════════════════════════════════════════════════════════ CLI
def _flag(a, nome, default=None):
    return a[a.index(nome) + 1] if nome in a and a.index(nome) + 1 < len(a) else default


def _uso(code=64):
    print(__doc__.split("ONDE A BIBLIOTECA MORA")[0].strip(), file=sys.stderr)
    return code


def _cli():
    a = sys.argv[1:]
    if not a:
        return _uso()
    cmd, a = a[0], a[1:]
    usuario = _flag(a, "--usuario")

    if cmd == "listar":
        d = dir_estilos()
        us = [usuario] if usuario else usuarios()
        if not us:
            log("biblioteca vazia em %s" % d)
            return 0
        for u in us:
            for slug in _estilos_de(u):
                try:
                    e = carregar_estilo(u, slug, usuario_pedido=usuario)
                except ErroEstilo:
                    continue
                print("%s/%s@%s\t%s\tperfis=%s\t%s"
                      % (u, slug, e.get("versao"), e.get("nome"),
                         ",".join(e.get("perfis") or []),
                         (e.get("procedencia") or {}).get("tipo", "?")))
        return 0

    if cmd == "mostrar":
        if not a:
            return _uso()
        e, meta = resolver_estilo(a[0], usuario)
        e.pop("_arquivo", None)
        e["_resolvido"] = meta
        json.dump(e, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if cmd == "criar":
        if not a:
            return _uso()
        perfis = [x for x in (_flag(a, "--perfis") or "").split(",") if x]
        if not perfis:
            log("erro: --perfis é obrigatório (ex.: --perfis reels,vsl). Um estilo que "
                "não serve a nenhum perfil não valida — é o defeito do vocabulário "
                "amarrado a um formato só.")
            return 64
        print(criar(a[0], _flag(a, "--nome"), perfis, usuario=usuario,
                    de_perfil=_flag(a, "--de-perfil"),
                    de_producao=_flag(a, "--de-producao"),
                    de_receita=_flag(a, "--de-receita"),
                    herda=_flag(a, "--herda"), nota=_flag(a, "--nota"),
                    forcar="--forcar" in a))
        return 0

    if cmd == "resolver":
        if not a or a[0].startswith("-"):
            return _uso()
        nome = _flag(a, "--perfil")
        if not nome and "--como-gravado" not in a:
            log("erro: --perfil é obrigatório")
            return 64
        sets = [a[i + 1] for i, x in enumerate(a) if x == "--set" and i + 1 < len(a)]
        caminho, destino, _r = resolver(
            a[0], nome, usuario=usuario, ref=_flag(a, "--estilo"),
            como_gravado="--como-gravado" in a, sets=sets,
            pedido_compilado=_flag(a, "--pedido-compilado"),
            creator=_flag(a, "--creator"))
        print(caminho)
        print(destino)
        return 0

    if cmd == "pedido":
        if len(a) < 2:
            log("uso: estilo.py pedido <dir-producao> \"texto\"")
            return 64
        d, texto = a[0], a[1]
        base = _ler(os.path.join(d, "perfil.json")) if \
            os.path.isfile(os.path.join(d, "perfil.json")) else {}
        if not base:
            log("erro: %s/perfil.json não existe — o pedido é compilado CONTRA o perfil "
                "resolvido, para o diff sair com o valor de origem" % d)
            return 1
        ops, recusas = compilar_pedido(texto, base)
        for r in recusas:
            log("RECUSADO: %r → %s\n  %s%s"
                % (r["trecho"], r["caminho"], r["motivo"],
                   "\n  " + r["comando"] if r["comando"] else ""))
        if not ops:
            log("nada compilado de %r. A camada 5 não é canal de escrita: instrução "
                "que não vira diff explícito não vira nada." % texto)
            return 1
        log("DIFF (nada aplicado ainda):")
        for o in ops:
            log("  %s: %s → %s   (%s)" % (o["caminho"], o["de"], o["para"], o["nota"]))
        obj = {"contrato": CONTRATO_PEDIDO, "compilado_em": _agora(), "texto": texto,
               "operacoes": ops, "recusas": recusas}
        alvo = os.path.join(d, ".preview", "pedidos",
                            "%s-pedido.json" % _agora().replace(":", "").replace("-", "")[:15])
        print(_gravar(alvo, obj))
        log("aplique com: estilo.py resolver %s --perfil <n> --pedido-compilado %s" % (d, alvo))
        return 0

    if cmd == "sinais":
        if not a:
            return _uso()
        alvo, novos = sinais(a[0], ref=_flag(a, "--estilo"), usuario=usuario)
        print(alvo)
        return 0

    if cmd == "propor":
        if not a:
            return _uso()
        propostas, texto = propor(a[0], usuario, _flag(a, "--primeira-peca"))
        print(texto)
        return 0 if propostas else 0

    if cmd == "promover":
        if not a:
            return _uso()
        try:
            print(promover(a[0], "--confirmar" in a, _flag(a, "--so"),
                           _flag(a, "--por"), usuario))
        except ErroEstilo as ex:
            if "--confirmar" not in a:
                print("%s" % ex, file=sys.stderr)
                return 2
            raise
        return 0

    if cmd == "diff":
        if len(a) < 2:
            log("uso: estilo.py diff <u>/<slug>@vA @vB")
            return 64
        u, slug, va = parse_ref(a[0], usuario)
        vb = a[1].lstrip("@")
        A = carregar_estilo(u, slug, va, usuario_pedido=usuario)
        B = carregar_estilo(u, slug, vb, usuario_pedido=usuario)
        difs = _diff_estilos(A, B)
        print("%s/%s: %s → %s — %d caminho(s) diferem" % (u, slug, va, vb, len(difs)))
        for c, x, y in difs:
            print("  %s: %s → %s" % (c, _canonico(x), _canonico(y)))
        return 0

    if cmd == "exportar":
        if not a:
            return _uso()
        saida = _flag(a, "--saida")
        if not saida:
            log("erro: --saida é obrigatório")
            return 64
        print(exportar(a[0], saida, usuario))
        return 0

    if cmd == "importar":
        if not a or not usuario:
            log("uso: estilo.py importar <arquivo> --usuario U [--slug s]")
            return 64
        print(importar(a[0], usuario, _flag(a, "--slug")))
        return 0

    if cmd == "validar":
        if not a:
            return _uso()
        alvo = a[0]
        if os.path.isfile(alvo):
            e = _ler(alvo)
        else:
            u, slug, v = parse_ref(alvo, usuario)
            e = carregar_estilo(u, slug, v, usuario_pedido=usuario)
            e.pop("_arquivo", None)
        erros, vistos = validar_estilo(e)
        if erros:
            print("%s: INVÁLIDO (%d nós conferidos)\n  %s"
                  % (alvo, vistos, "\n  ".join(erros)), file=sys.stderr)
            return 1
        print("%s: OK (%d nós conferidos)" % (alvo, vistos))
        return 0

    if cmd == "escopo":
        e = escopo()
        if "--conferir" in a:
            arq = os.path.join(dir_estilos(), "_escopo.json")
            if not os.path.isfile(arq):
                log("não há %s no disco — o escopo em uso é a semente do estilo.py" % arq)
                return 0
            disco = _ler(arq)
            campos = ("gravavel_por_estilo", "negado_dentro_do_gravavel",
                      "exclusivo_do_perfil", "promocao")
            difs = [c for c in campos
                    if _canonico(disco.get(c)) != _canonico(ESCOPO_SEMENTE.get(c))]
            if difs:
                print("DIVERGEM (%d): %s\n  disco:   %s\n  semente: %s"
                      % (len(difs), ", ".join(difs),
                         _canonico({c: disco.get(c) for c in difs}),
                         _canonico({c: ESCOPO_SEMENTE.get(c) for c in difs})),
                      file=sys.stderr)
                return 1
            print("%s == semente do estilo.py (%d campos conferidos)" % (arq, len(campos)))
            return 0
        json.dump(e, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if cmd == "init":
        d = dir_estilos(criar=True)
        alvo = os.path.join(d, "_escopo.json")
        if not os.path.isfile(alvo):
            _gravar(alvo, ESCOPO_SEMENTE)
        alvo2 = os.path.join(d, "_schema-estilo.json")
        if not os.path.isfile(alvo2):
            _gravar(alvo2, SCHEMA_SEMENTE)
        print(d)
        return 0

    log("comando desconhecido: %s" % cmd)
    return _uso()


if __name__ == "__main__":
    try:
        sys.exit(_cli())
    except ErroEstilo as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(1)
    except _perfil().ErroPerfil as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(1)
