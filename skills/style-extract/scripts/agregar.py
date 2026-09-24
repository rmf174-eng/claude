#!/usr/bin/env python3
"""agregar — N medições → UM estilo de edição (`benchmark.estilo-edicao/v1`).

É o contrato que a SPEC-24 consome. A regra que governa o arquivo inteiro:

    Todo valor do estilo é um `Param` — não existe `"cortes_por_min": 16.55`.
    Existe `"cortes_por_min": {v, agg, n, n_total, disp, conf, fonte, metodo,
    por_ref, faltou, qualidade, nota}`.

É esse detalhe que impede o consumidor de tratar N=1 como se fosse N=5, e é o
antídoto para a lição mais repetida deste repo (`docs/EDICAO-CAPACIDADES.md:39`,
`:65-67`, `:168-171` — três conclusões erradas por amostra pequena).

O QUE ELE RECUSA
  · corpus com `objetivo` misturado → sai 2, nomeando as refs de cada grupo
    (`--forcar-objetivo-misto` agrega assim mesmo e grava o aviso)
  · gravar um `estilo.json` que não valida contra `references/_schema.json` → sai 1.
    Gravar inválido é bug, não aviso.
  · `conf: alta` com n < 3 · chave de formato em qualquer nível · `fonte:
    semantico` carregando posição ou cor · `overlay_perfil` fora do subconjunto
    que a SPEC-00 §3.2 autoriza a um override

ONDE O ESTILO É GRAVADO (nunca `intelligence/` cravado — um cliente do produto
não tem esse diretório):
    $BENCH_ESTILOS_EXTRAIDOS   →  se definido
    intelligence/estilos/      →  se `intelligence/` existir no cwd
    $ILHA_HOME/estilos-extraidos/  (default $HOME/.ilha/estilos-extraidos)

Uso:
    agregar.py <corpus-dir> --slug <s> --perfil <p> [--objetivo <o>] [--nome "..."]
        [--temperatura <t>] [--regras <regras-propostas.json>]
        [--forcar-objetivo-misto] [--saida <dir>]
    agregar.py --validar <estilo.json>        (só valida, não grava)

exit 0 ok · 1 inválido/erro · 2 objetivo misto recusado
"""
import argparse
import datetime
import importlib.util
import math
import json
import os
import sys

AQUI = os.path.dirname(os.path.realpath(__file__))
SCHEMA = os.path.join(os.path.dirname(AQUI), "references", "_schema.json")
CONTRATO = "benchmark.estilo-edicao/v1"
VERSAO_EXTRATOR = 1


def _mod(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(AQUI, arquivo))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


co = _mod("se_coerencia", "coerencia.py")
cx = _mod("se_complexidade", "complexidade.py")


def log(*a):
    print(">>", *a, file=sys.stderr)


def esquema():
    return co.esquema(SCHEMA)


# ------------------------------------------------------------------- destino
def dir_estilos():
    """§FRONTEIRA orientação 10. A skill é produto; a saída não. Ausência de
    `intelligence/` é SILÊNCIO — avisar seria vazar a nossa instalação."""
    v = os.environ.get("BENCH_ESTILOS_EXTRAIDOS")
    if v:
        return v
    if os.path.isdir("intelligence"):
        return os.path.join("intelligence", "estilos")
    ilha_home = os.environ.get("ILHA_HOME") or os.path.join(os.path.expanduser("~"), ".ilha")
    return os.path.join(ilha_home, "estilos-extraidos")


# ------------------------------------------------------- o mapa dos eixos
# (grupo, chave) → (classe, campo na medição, fonte, método, kwargs)
#
# ⚠️ `fonte: semantico` NUNCA pode carregar posição ou cor — o Gemini erra os dois
# com confiança alta (85% de altura contra 56% medidos; #FFFF00 contra #F14418).
# Por isso `cor.paleta` sai como não-medido em vez de vir do deep-edit: a paleta
# do Gemini fica registrada na medição, não vira Param de estilo.
EIXOS = [
    ("montagem", "cortes_por_min",   "escalar", "montagem.cortes_por_min", "medido", "ritmo.py --fps 8", {}),
    ("montagem", "plano_mediano_s",  "escalar", "montagem.plano_mediano_s", "medido", "ritmo.py --fps 8", {}),
    ("montagem", "plano_medio_s",    "escalar", "montagem.plano_medio_s", "medido", "ritmo.py --fps 8", {}),
    ("montagem", "frac_camada",      "escalar", "montagem.frac_camada", "derivado", "tipos['troca de camada']/cortes", {}),
    ("plano",    "gramatica",        "categorico", "plano.gramatica", "medido", "reframe.py à mão (guarda §3.9b)", {}),
    ("plano",    "punch_ins_por_min", "escalar", "plano.punch_ins_por_min", "semantico", "deep-edit.punch_ins[]", {}),
    ("legenda",  "estilo",           "categorico", "legenda.estilo", "semantico", "deep-edit.legendas.estilo", {}),
    ("legenda",  "presente_pct",     "escalar", "legenda.presente_pct_do_tempo", "medido", "tipografia.py --fps 2", {}),
    ("legenda",  "y_centro_pct",     "escalar", "legenda.y_centro_pct", "medido", "tipografia.py --fps 2", {}),
    # SPEC-41 — o nome do campo deixa de carregar um canvas (`_px_1920`). Medição
    # antiga entra por `migrar_medicao()`, que CONVERTE a unidade antes de ler.
    ("legenda",  "altura_glifo_pct", "escalar", "legenda.altura_glifo_pct", "medido", "tipografia.py --fps 2", {}),
    ("legenda",  "largura_usada_pct", "escalar", "legenda.largura_usada_pct", "medido", "tipografia.py --fps 2", {}),
    ("legenda",  "s_por_pagina",     "escalar", "legenda.s_por_pagina", "medido", "tipografia.py --fps 2 (cadência)", {}),
    ("legenda",  "cor_base",         "cor", "legenda.cor_base", "medido", "tipografia.py --fps 2 (núcleo do glifo)", {}),
    ("legenda",  "cor_destaque",     "cor", "legenda.cor_destaque", "medido", "tipografia.py --fps 2 (núcleo do glifo)", {}),
    ("legenda",  "caixa_alta",       "categorico", "legenda.caixa_alta", "semantico", "deep-edit.legendas.caixa_alta", {}),
    ("grafismo", "elementos_por_10s", "escalar", "grafismo.elementos_por_10s", "semantico", "deep-edit.densidade", {}),
    ("grafismo", "max_simultaneos",  "escalar", "grafismo.max_simultaneos", "semantico", "deep-edit.densidade", {}),
    ("grafismo", "maior_janela_sem_elemento_s", "escalar", "grafismo.maior_janela_sem_elemento_s", "semantico", "deep-edit.densidade", {"envelope": True}),
    ("grafismo", "recursos",         "conjunto", "grafismo.recursos", "semantico", "deep-edit.timeline_elementos[].tipo", {}),
    ("som",      "lufs_integrado",   "escalar", "som.lufs_integrado", "medido", "ffmpeg ebur128", {}),
    ("som",      "lra_lu",           "escalar", "som.lra_lu", "medido", "ffmpeg ebur128", {}),
    ("som",      "true_peak_dbtp",   "escalar", "som.true_peak_dbtp", "medido", "ffmpeg ebur128", {"envelope": True}),
    ("som",      "dinamica_db",      "escalar", "som.dinamica_db", "derivado", "RMS 100ms: p80(fala) − p5(piso)", {}),
    ("som",      "trilha_tipo",      "categorico", "som.trilha_tipo", "semantico", "deep-edit.trilha.tipo", {}),
    ("som",      "sfx",              "conjunto", "som.sfx", "semantico", "deep-edit.sfx_eventos[].tipo", {}),
    ("fala",     "palavras_por_min", "escalar", "fala.palavras_por_min", "medido", "transcribe.sh (--transcrever)", {}),
    ("fala",     "chars_por_segundo", "escalar", "fala.chars_por_segundo", "medido", "transcribe.sh (--transcrever)", {}),
]

# Param que existe no contrato mas NÃO é medível hoje. Sai explícito, com o motivo
# — campo faltando fica faltando (§9.5), nunca é preenchido pelo modelo.
NAO_MEDIVEIS = [
    ("montagem", "corte_encostado", "categorico", "medido",
     "exige EDL do par bruto+editado (edl-do-par.py) — fora do modo automático"),
    ("cor", "paleta", "conjunto", "medido",
     "paleta do Gemini é COR: proibida como fonte semântica (§4.2). Medir no pixel "
     "exige som-e-cor.py com par de frames — fora do modo automático"),
    ("cor", "cor_destaque_vem_da_cena", "categorico", "derivado",
     "depende da paleta medida no pixel, que não existe no modo automático"),
]

# eixo → (bloco do perfil, chave, transformação). Só o subconjunto que a SPEC-00
# §3.2 autoriza um override a escrever: ritmo.*, legenda.*, audio.loudness, cor.grade.
OVERLAY = [
    ("legenda.y_centro_pct", "legenda", "y_pct", lambda v: round(v / 100.0, 4)),
    ("legenda.presente_pct", "legenda", "ativa", lambda v: bool(v >= 50)),
    ("som.lufs_integrado", "audio.loudness", "I", lambda v: round(v, 1)),
    ("som.lra_lu", "audio.loudness", "LRA", lambda v: round(v, 1)),
    ("som.true_peak_dbtp", "audio.loudness", "TP", lambda v: round(v, 1)),
    ("plano.gramatica", "ritmo", "gramatica_plano", lambda v: v),
]


# ---------------------------------------------------------------- montagem
def _fam():
    return set(esquema()["x_familia_ritmo_densidade"])


def nota_de_cobertura(meds):
    """`n` nunca mente sobre a cobertura: todo Param de fonte semântica derivado
    de peça AMOSTRADA carrega quantos segundos de quantos foram vistos."""
    partes = []
    for m in meds:
        am = m.get("amostragem") or {}
        if am.get("semantico") != "blocos":
            continue
        partes.append("%s: %d×%.0fs de %.0fs (%.1f%%)"
                      % (m["id"], len(am.get("janelas_s") or []),
                         (am.get("cobertura_semantica_s") or 0) / max(1, len(am.get("janelas_s") or [1])),
                         m["fonte"]["dur_s"], am.get("cobertura_semantica_pct") or 0))
    return ("amostrado — " + " · ".join(partes)) if partes else None


def montar_eixos(meds):
    eixos, avisos = {}, []
    nota_cob = nota_de_cobertura(meds)
    for grupo, chave, classe, campo, fonte, metodo, kw in EIXOS:
        p = co.montar_param(meds, classe, campo, fonte, metodo, **kw)
        co.aplicar_guardas(f"{grupo}.{chave}", p, meds)
        if fonte == "semantico" and nota_cob and p["n"]:
            p["nota"] = nota_cob if not p.get("nota") else f"{p['nota']} · {nota_cob}"
        if (grupo, chave) == ("plano", "gramatica") and p["v"] is None:
            # guarda §3.9b: o extrator NÃO roda reframe automático e NÃO emite
            # trajetória de zoom — o script inventa uma em talking-head de mão solta.
            p["nota"] = ("reframe nao converge em talking-head; medir com fiducial fixo se "
                         "importar (>=3 pares de planos, todas as correlacoes >=0,75, coladas "
                         "num --override do medir-ref.py)")
        eixos.setdefault(grupo, {})[chave] = p
    for grupo, chave, classe, fonte, motivo in NAO_MEDIVEIS:
        agg = {"escalar": "mediana", "categorico": "moda", "cor": "mediana",
               "conjunto": "uniao"}[classe]
        eixos.setdefault(grupo, {})[chave] = co.param_ausente(
            agg, fonte=fonte, metodo="não roda no automático", n_total=len(meds),
            motivo=motivo, refs=[m["id"] for m in meds])
    eixos.setdefault("legenda", {})["catalogo_slug"] = None
    return eixos, avisos


def montar_por_bloco(meds, eixos):
    """Um Param só ganha entrada em `por_bloco` quando a variação POR BLOCO é
    maior que a variação ENTRE referências (§3.7):

        |mediana_bloco − mediana_global| > iqr_global/2
        E o sinal da diferença é o mesmo em >= ceil(2N/3) refs

    Sem isso `por_bloco` vira ruído de amostragem repetido três vezes."""
    campos = {"cortes_por_min": ("montagem", "cortes_por_min"),
              "plano_medio_s": ("montagem", "plano_medio_s"),
              "elementos_por_10s": ("grafismo", "elementos_por_10s"),
              "max_simultaneos": ("grafismo", "max_simultaneos")}
    rotulos = []
    for m in meds:
        for r in (m.get("por_bloco") or {}):
            if r not in rotulos:
                rotulos.append(r)
    saida, n = {}, len(meds)
    minimo_acordo = math.ceil(2 * n / 3)
    for rot in rotulos:
        for campo, (grupo, chave) in campos.items():
            glob = eixos[grupo][chave]
            if glob["v"] is None or not isinstance(glob.get("disp"), dict):
                continue
            iqr = glob["disp"].get("iqr")
            if iqr is None:
                continue
            por_ref = {}
            for m in meds:
                v = ((m.get("por_bloco") or {}).get(rot) or {}).get(campo)
                if v is not None:
                    por_ref[m["id"]] = v
            if len(por_ref) < 2:
                continue
            p = co.param_escalar(por_ref, fonte=glob["fonte"],
                                 metodo=glob["metodo"] + f" (bloco {rot})",
                                 n_total=n, qualidade=glob["qualidade"])
            delta = p["v"] - glob["v"]
            if abs(delta) <= iqr / 2:
                continue
            sinal = 1 if delta > 0 else -1
            # empate NÃO é concordância: `v == global` não testemunha direção
            # nenhuma. Contar o zero como acordo faz um bloco entrar com metade
            # do corpus mudo.
            acordo = sum(1 for r_, v in por_ref.items()
                         if r_ in glob["por_ref"]
                         and (v - glob["por_ref"][r_]) * sinal > 0)
            if acordo < minimo_acordo:
                continue
            p["nota"] = ("bloco %s desloca %+.2f contra a mediana global %.2f "
                         "(iqr/2 = %.2f); %d de %d refs concordam na direção"
                         % (rot, delta, glob["v"], iqr / 2, acordo, n))
            saida.setdefault(rot, {})[f"{grupo}.{chave}"] = p
    return saida


def montar_variantes(meds, eixos, escala):
    """enxuta / padrao / densa — derivadas do PRÓPRIO corpus, nada inventado.

    recursos: presente_em >= 0,80 (enxuta) · >= 0,50 (padrão) · >= 0,40 (densa)
    densidade: p25 (enxuta) · mediana (padrão) · p75 (densa)
    Cada variante recomputa o próprio IC.
    """
    lim = esquema()["x_limiares"]
    rec = eixos["grafismo"]["recursos"]
    itens = (rec.get("disp") or {}).get("itens") or []
    densos = [("grafismo", "elementos_por_10s"), ("grafismo", "max_simultaneos"),
              ("montagem", "cortes_por_min"), ("legenda", "presente_pct")]
    especs = [("enxuta", lim["variante_enxuta_presente_em"], 25),
              ("padrao", lim["variante_padrao_presente_em"], 50),
              ("densa", lim["variante_densa_presente_em"], 75)]
    saida = {}
    for nome, corte, q in especs:
        recursos = [d["item"] for d in itens if d["presente_em"] >= corte]
        overrides, entradas = {}, {}
        for grupo, chave in densos:
            base = eixos[grupo][chave]
            vals = [float(v) for v in base["por_ref"].values()]
            if not vals:
                entradas[chave] = None
                continue
            v = co.pct(vals, q)
            p = dict(base)
            p["v"] = round(v, 4)
            p["agg"] = "mediana"
            p["fonte"] = "derivado"
            p["metodo"] = f"{base['metodo']} → percentil {q} do corpus (variante {nome})"
            p["nota"] = f"variante {nome}: p{q} em vez da mediana"
            overrides[f"{grupo}.{chave}"] = p
            entradas[chave] = v
        ic = cx.calcular({
            "elementos_por_10s": entradas.get("elementos_por_10s"),
            "max_simultaneos": entradas.get("max_simultaneos"),
            "recursos_distintos": len(recursos) if itens else None,
            "cortes_por_min": entradas.get("cortes_por_min"),
            "texto_fracao": (None if entradas.get("presente_pct") is None
                             else entradas["presente_pct"] / 100.0),
        }, escala)
        saida[nome] = {"ic": ic["ic"], "faixa": ic["faixa"],
                       "recursos": recursos, "overrides": overrides}
    return saida


def montar_overlay(eixos):
    """Só `Param` com conf >= media entram. É assim que 'baixa confiança vira
    sugestão, não default' deixa de ser prosa e vira AUSÊNCIA DE CAMPO."""
    ov = {"_gerado_de": None, "_apenas_conf": ["alta", "media"]}
    for dotted, bloco, chave, f in OVERLAY:
        grupo, _, k = dotted.partition(".")
        p = (eixos.get(grupo) or {}).get(k)
        if not isinstance(p, dict) or p["v"] is None or p["conf"] not in ("alta", "media"):
            continue
        alvo = ov
        for parte in bloco.split("."):
            alvo = alvo.setdefault(parte, {})
        alvo[chave] = f(p["v"])
    return ov


# ------------------------------------------------------------------- regras
def verificar_regras(propostas, meds):
    """O modelo escreve a regra; o SCRIPT confere o suporte. O modelo não é a
    autoridade sobre o próprio suporte (§3.6).

    Uma regra só entra em `regras[]` com evidência TIMESTAMPADA VÁLIDA em >= 2
    referências distintas: cada `ref` tem que estar no corpus e cada `t_s` tem
    que cair dentro da duração daquela ref."""
    durs = {m["id"]: m["fonte"]["dur_s"] for m in meds}
    n = len(meds)
    boas, candidatas = [], []
    for r in propostas or []:
        ev_ok, motivos = [], []
        for e in r.get("evidencia") or []:
            ref, t = e.get("ref"), e.get("t_s")
            if ref not in durs:
                motivos.append(f"ref {ref!r} não está no corpus")
                continue
            if t is None or not (0 <= float(t) <= durs[ref]):
                motivos.append(f"t_s={t} fora de [0, {durs[ref]}] em {ref}")
                continue
            ev_ok.append({"ref": ref, "t_s": float(t), "citacao": e.get("citacao", "")})
        suporte = len({e["ref"] for e in ev_ok})
        regra = {
            "id": r.get("id") or "sem-id",
            "tipo": r.get("tipo") or "composicao",
            "texto": r.get("texto") or "",
            "suporte": suporte, "de": n,
            "evidencia": ev_ok,
            "conf": co._conf_regras("conjunto", suporte, "ok",
                                    presente=(suporte / n if n else 0)),
            "aplicavel_por": r.get("aplicavel_por") or "plano",
            "motivo": None,
        }
        if suporte >= esquema()["x_limiares"]["regra_suporte_min"]:
            boas.append(regra)
        else:
            regra["conf"] = "baixa"
            regra["motivo"] = ("suporte %d < 2 após verificação determinística"
                               % suporte) + ((" — " + "; ".join(motivos)) if motivos else "")
            candidatas.append(regra)
    return boas, candidatas


def regras_cruas(meds):
    """Sem `--regras`, as observações do Gemini viram CANDIDATAS, nunca regras:
    são de uma referência só e não têm evidência timestampada."""
    out = []
    for m in meds:
        for i, txt in enumerate((m.get("semantico") or {}).get("regras_observadas") or []):
            out.append({
                "id": "%s-obs%d" % (m["id"], i + 1),
                "tipo": "composicao",
                "texto": txt,
                "suporte": 1, "de": len(meds),
                "evidencia": [],
                "conf": "baixa",
                "aplicavel_por": "prompt",
                "motivo": ("observação crua de deep-edit em 1 referência (%s), sem "
                           "evidência timestampada — precisa de --regras com >=2 refs"
                           % m["id"]),
            })
    return out


# ----------------------------------------------------------------- validação
_VISTOS = [0]


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


def _resolver(esq, raiz):
    while isinstance(esq, dict) and "$ref" in esq:
        alvo = esq["$ref"]
        if not alvo.startswith("#/"):
            return {}
        no = raiz
        for parte in alvo[2:].split("/"):
            no = no[parte]
        esq = no
    return esq


def _validar_no(v, esq, raiz, caminho, erros):
    esq = _resolver(esq, raiz)
    if not isinstance(esq, dict) or not esq:
        return
    _VISTOS[0] += 1
    if "const" in esq and v != esq["const"]:
        erros.append("%s: esperado %r, veio %r" % (caminho, esq["const"], v))
        return
    if "enum" in esq and v not in esq["enum"]:
        erros.append("%s: %r não está em %s" % (caminho, v, esq["enum"]))
        return
    if "anyOf" in esq:
        for sub in esq["anyOf"]:
            sub_erros = []
            _validar_no(v, sub, raiz, caminho, sub_erros)
            if not sub_erros:
                return
        erros.append("%s: não casa com nenhuma alternativa de anyOf" % caminho)
        return
    t = esq.get("type")
    if t is not None:
        tipos = t if isinstance(t, list) else [t]
        if not any(_tipo_ok(v, x) for x in tipos):
            erros.append("%s: tipo %s, esperado %s"
                         % (caminho, type(v).__name__, "|".join(tipos)))
            return
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in esq and v < esq["minimum"]:
            erros.append("%s: %r < mínimo %r" % (caminho, v, esq["minimum"]))
        if "maximum" in esq and v > esq["maximum"]:
            erros.append("%s: %r > máximo %r" % (caminho, v, esq["maximum"]))
    if isinstance(v, str) and "minLength" in esq and len(v) < esq["minLength"]:
        erros.append("%s: string curta demais" % caminho)
    if isinstance(v, list):
        if "minItems" in esq and len(v) < esq["minItems"]:
            erros.append("%s: %d itens < mínimo %d" % (caminho, len(v), esq["minItems"]))
        if "items" in esq:
            for i, x in enumerate(v):
                _validar_no(x, esq["items"], raiz, "%s[%d]" % (caminho, i), erros)
    if isinstance(v, dict):
        props = esq.get("properties", {})
        for r in esq.get("required", []):
            if r not in v:
                erros.append("%s: falta a chave obrigatória %r" % (caminho or "(raiz)", r))
        extra = esq.get("additionalProperties", True)
        for k, sub_v in v.items():
            if k in props:
                _validar_no(sub_v, props[k], raiz,
                            ("%s.%s" % (caminho, k)) if caminho else k, erros)
            elif extra is False:
                erros.append("%s: chave desconhecida %r" % (caminho or "(raiz)", k))
            elif isinstance(extra, dict):
                _validar_no(sub_v, extra, raiz,
                            ("%s.%s" % (caminho, k)) if caminho else k, erros)


def _anda_params(no, caminho, fn):
    if isinstance(no, dict):
        if "v" in no and "conf" in no and "n" in no and "agg" in no:
            fn(caminho, no)
            return
        for k, v in no.items():
            _anda_params(v, f"{caminho}.{k}" if caminho else k, fn)


def validar(est, esq=None):
    """Devolve (erros, quantos nós o validador visitou). Um verificador que varre
    0 e sai 0 é indistinguível de um quebrado — por isso ele devolve o quanto."""
    esq = esq or esquema()
    erros = []
    _VISTOS[0] = 0
    _validar_no(est, esq, esq, "", erros)
    proibidas = set(esq["x_chaves_de_formato"])
    pixel = set(esq["x_chaves_pixel"])
    ids = {c["id"] for c in est.get("corpus", [])}
    n_refs = est.get("n_refs", 0)

    # 1. chave de formato em qualquer nível, exceto aplica_a.formato_das_refs
    def varrer(no, caminho):
        if isinstance(no, dict):
            for k, v in no.items():
                p = f"{caminho}.{k}" if caminho else k
                if k in proibidas and not p.startswith("aplica_a.formato_das_refs"):
                    erros.append("chave de formato proibida em %s "
                                 "(formato de peça é do perfil, SPEC-00 §3.1)" % p)
                varrer(v, p)
        elif isinstance(no, list):
            for i, x in enumerate(no):
                varrer(x, "%s[%d]" % (caminho, i))
    varrer(est, "")

    # 2. as invariantes do Param
    n_params = [0]

    def checar(caminho, p):
        n_params[0] += 1
        folha = caminho.rsplit(".", 1)[-1]
        if p["conf"] == "alta" and p["n"] < 3:
            erros.append("%s: conf alta com n=%d (< 3)" % (caminho, p["n"]))
        if p["n"] > n_refs:
            erros.append("%s: n=%d > n_refs=%d" % (caminho, p["n"], n_refs))
        if p["n"] != len(p["por_ref"]):
            erros.append("%s: n=%d mas por_ref tem %d entradas"
                         % (caminho, p["n"], len(p["por_ref"])))
        fora = set(p["por_ref"]) - ids
        if fora:
            erros.append("%s: por_ref cita refs fora do corpus: %s" % (caminho, sorted(fora)))
        if p["fonte"] == "semantico" and folha in pixel:
            erros.append("%s: fonte semantico proibida em chave de posição/cor "
                         "(o Gemini erra posição e cor com confiança alta)" % caminho)
    for raiz_nome in ("eixos", "por_bloco", "denominador_comum"):
        _anda_params(est.get(raiz_nome, {}), raiz_nome, checar)
    for nome, var in (est.get("variantes") or {}).items():
        _anda_params(var.get("overrides", {}), f"variantes.{nome}.overrides", checar)

    # 3. estado incoerente não emite executável
    if est.get("estado") == "incoerente":
        if est.get("overlay_perfil") not in ({}, None):
            erros.append("estado incoerente exige overlay_perfil == {}")
        if est.get("variantes") not in ({}, None):
            erros.append("estado incoerente exige variantes == {}")

    # 4. overlay_perfil dentro do subconjunto que a SPEC-00 §3.2 autoriza
    permitido = esq["x_overlay_permitido"]
    for k, v in (est.get("overlay_perfil") or {}).items():
        if k.startswith("_"):
            continue
        if k in ("ritmo", "legenda"):
            continue
        if k == "audio":
            extras = set(v or {}) - {"loudness"}
            if extras:
                erros.append("overlay_perfil.audio só pode ter `loudness`, veio %s" % sorted(extras))
            continue
        if k == "cor":
            extras = set(v or {}) - {"grade"}
            if extras:
                erros.append("overlay_perfil.cor só pode ter `grade`, veio %s" % sorted(extras))
            continue
        erros.append("overlay_perfil.%s fora do subconjunto autorizado %s" % (k, permitido))

    return erros, {"nos_do_schema": _VISTOS[0], "params": n_params[0]}


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir", nargs="?")
    ap.add_argument("--slug")
    ap.add_argument("--perfil", action="append", default=None)
    ap.add_argument("--nome", default=None)
    ap.add_argument("--objetivo", default=None)
    ap.add_argument("--temperatura", default=None)
    ap.add_argument("--regras", default=None,
                    help="JSON com regras propostas pelo modelo (o script verifica o suporte)")
    ap.add_argument("--forcar-objetivo-misto", action="store_true", dest="forcar")
    ap.add_argument("--saida", default=None, help="sobrescreve o diretório de estilos")
    ap.add_argument("--validar", default=None, help="valida um estilo.json e sai")
    a = ap.parse_args()

    if a.validar:
        with open(a.validar, encoding="utf-8") as fh:
            est = json.load(fh)
        erros, cont = validar(est)
        print("varreu %d nós de schema e %d Param" % (cont["nos_do_schema"], cont["params"]),
              file=sys.stderr)
        if erros:
            for e in erros:
                print("  ✗ " + e, file=sys.stderr)
            sys.exit(1)
        print("válido: " + a.validar)
        return

    if not a.corpus_dir or not a.slug:
        ap.error("uso: agregar.py <corpus-dir> --slug <s> --perfil <p>")

    meds = co.carregar_corpus(a.corpus_dir)
    avisos = []

    # estratificação: objetivo misto é RECUSADO (§3.7)
    grupos = {}
    for m in meds:
        grupos.setdefault((m.get("declarado") or {}).get("objetivo"), []).append(m["id"])
    if len(grupos) > 1:
        msg = " · ".join("%s: %s" % (o, ", ".join(sorted(ids)))
                         for o, ids in sorted(grupos.items(), key=lambda kv: str(kv[0])))
        if not a.forcar:
            print("ABORTA: corpus com objetivo misturado — o estilo é do OBJETIVO da peça, "
                  "não da pessoa. Sugestão: dois estilos.", file=sys.stderr)
            print("  " + msg, file=sys.stderr)
            sys.exit(2)
        avisos.append("objetivo misturado no corpus (%s) — agregado sob --forcar-objetivo-misto; "
                      "os parâmetros valem para a mistura, não para nenhum dos objetivos" % msg)

    temps = sorted({(m.get("declarado") or {}).get("temperatura") for m in meds} - {None, "na"})
    if len(temps) > 1:
        avisos.append("temperatura mista no corpus (%s): ritmo e densidade rebaixados para "
                      "conf baixa — as 4 VSLs pooladas dão 16,55 cortes/min e nenhuma corta "
                      "nesse ritmo" % ", ".join(temps))

    escala = cx.carregar_escala(SCHEMA)
    eixos, av2 = montar_eixos(meds)
    avisos += av2

    # o núcleo avaliado é o MESMO objeto que está em `eixos` — não uma segunda
    # cópia. Duas cópias divergem em `nota` e o artefato passa a dizer duas coisas
    # sobre o mesmo parâmetro.
    nucleo = {}
    for nome in co.NUCLEO():
        g, _, k = nome.partition(".")
        if k in (eixos.get(g) or {}):
            nucleo[nome] = eixos[g][k]
    aval = co.avaliar(meds, nucleo)
    estado = aval["estado"]

    por_bloco = montar_por_bloco(meds, eixos)
    variantes = montar_variantes(meds, eixos, escala) if estado != "incoerente" else {}
    overlay = montar_overlay(eixos) if estado != "incoerente" else {}

    propostas = None
    if a.regras:
        with open(a.regras, encoding="utf-8") as fh:
            d = json.load(fh)
        propostas = d.get("regras") if isinstance(d, dict) else d
    regras, candidatas = verificar_regras(propostas, meds)
    # 🔴 PROPOR UMA REGRA NÃO APAGA O QUE AINDA NÃO FOI PROPOSTO (2026-08-11).
    # Era `if not propostas: candidatas = regras_cruas(meds)` — ou seja, a
    # PRIMEIRA passada com `--regras` trocava as observações cruas do deep-edit
    # pelas propostas recusadas, e as 35 do corpus de teste sumiam do artefato
    # sem uma linha de aviso. `regras_candidatas` é a fila do que ainda não é
    # regra, e as duas origens pertencem a ela: o que foi proposto e não teve
    # suporte, e o que nem chegou a ser proposto. Sai por `id`, que já é único
    # por construção (`<ref>-obs<n>` para as cruas).
    vistos = {c["id"] for c in candidatas}
    candidatas += [c for c in regras_cruas(meds) if c["id"] not in vistos]

    ic = cx.calcular(cx.de_estilo({"eixos": eixos}), escala)
    ic_por_ref = {}
    for m in meds:
        r = cx.calcular(cx.de_medicao(m), escala)
        ic_por_ref[m["id"]] = r["ic"]

    nao_medido = []
    for grupo, chaves in eixos.items():
        for chave, p in chaves.items():
            if isinstance(p, dict) and p["v"] is None:
                nao_medido.append("%s.%s: %s" % (grupo, chave, p.get("nota") or "não medido"))
    if ic["componentes_faltando"]:
        nao_medido.append("índice de complexidade: faltam os componentes "
                          + ", ".join(ic["componentes_faltando"]))

    objetivo = a.objetivo or (sorted(grupos)[0] if len(grupos) == 1 else "misto")
    temperatura = a.temperatura or (temps[0] if len(temps) == 1 else
                                    ("mista" if len(temps) > 1 else "na"))
    perfis = a.perfil or sorted({(m.get("declarado") or {}).get("perfil_sugerido")
                                 for m in meds} - {None}) or ["vsl"]
    durs = [m["fonte"]["dur_s"] for m in meds]
    aspectos = sorted({m["fonte"].get("aspecto") for m in meds} - {None})

    saida_dir = a.saida or dir_estilos()
    destino = os.path.join(saida_dir, a.slug, "estilo.json")
    if overlay:
        rel = os.path.relpath(destino, os.getcwd())
        overlay["_gerado_de"] = destino if rel.startswith("..") else rel

    est = {
        "contrato": CONTRATO,
        "slug": a.slug,
        "nome": a.nome or a.slug,
        "estado": estado,
        "gerado_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "gerador": "style-extract/scripts/agregar.py",
        "versao_extrator": VERSAO_EXTRATOR,
        "aplica_a": {
            "perfis": list(perfis),
            "objetivo": objetivo,
            "temperatura": temperatura,
            "formato_das_refs": {"aspecto": aspectos,
                                 "dur_s": {"min": min(durs), "max": max(durs)}},
        },
        "corpus": [{
            "id": m["id"], "fonte": m["fonte"]["caminho"], "url": m["fonte"].get("url"),
            "dur_s": m["fonte"]["dur_s"], "medicao": m["_arquivo"],
            "cobertura_semantica_pct": (m.get("amostragem") or {}).get("cobertura_semantica_pct"),
            "objetivo": (m.get("declarado") or {}).get("objetivo"),
            "temperatura": (m.get("declarado") or {}).get("temperatura"),
        } for m in meds],
        "n_refs": len(meds),
        "coerencia": {
            "score": aval["score"], "estado": aval["estado"],
            "nucleo_ok": aval["nucleo_ok"], "nucleo_falhou": aval["nucleo_falhou"],
            "clusters": aval["clusters"], "veredito": aval["veredito"],
        },
        "complexidade": {
            "versao_escala": ic["versao_escala"], "ic": ic["ic"], "faixa": ic["faixa"],
            "componentes": ic["componentes"],
            "componentes_faltando": ic["componentes_faltando"],
            "por_ref": ic_por_ref,
        },
        "eixos": eixos,
        "por_bloco": por_bloco,
        "denominador_comum": aval["denominador_comum"],
        "regras": regras,
        "regras_candidatas": candidatas,
        "variantes": variantes,
        "overlay_perfil": overlay,
        "nao_medido": sorted(nao_medido),
        "avisos": avisos,
    }

    erros, cont = validar(est, esquema())
    log("validação: %d nós de schema, %d Param varridos" % (cont["nos_do_schema"], cont["params"]))
    if erros:
        print("ABORTA: estilo inválido — gravar inválido é bug, não aviso.", file=sys.stderr)
        for e in erros:
            print("  ✗ " + e, file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(est, fh, ensure_ascii=False, indent=2)
    log("estado %s · score %.2f · IC %s · %d refs"
        % (estado, aval["score"], est["complexidade"]["ic"], len(meds)))
    for av in avisos:
        log("aviso: " + av)
    print(destino)


if __name__ == "__main__":
    main()
