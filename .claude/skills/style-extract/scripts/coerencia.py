#!/usr/bin/env python3
"""coerencia — "vale a pena agregar estas N referências?", de graça.

Duas coisas moram aqui:

  1. A BIBLIOTECA DO TIPO `Param` (§3.2/§3.3/§3.4 da SPEC-23) — as seis regras de
     agregação por classe, a fórmula de confiança e as guardas que rebaixam. É
     importada pelo `agregar.py`, e mora AQUI porque é o que decide se um
     parâmetro "fechou" — que é exatamente a pergunta da coerência.
  2. O CLI de coerência — score, estado, clusters e denominador comum, lidos das
     medições que já estão no disco. Não grava nada, não gasta nada.

O ponto da spec inteira, em uma frase: **um número sem `n` e sem dispersão é a
armadilha mais cara deste repo automatizada**. As 4 VSLs de `data/advertisers/_ritmo/`
dão mediana 16,55 cortes/min, e nenhuma das quatro corta nesse ritmo (27,9 · 18,4
· 14,7 · 8,6). Um agregador que devolve 16,55 com confiança alta está quebrado.

Uso:
    coerencia.py <corpus-dir> [--json]

`<corpus-dir>` é o diretório que tem `medicoes/*.json` (saída do `medir-ref.py`).

exit 0 ok · 2 corpus vazio/inválido
"""
import argparse
import json
import math
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.realpath(__file__))
SCHEMA = os.path.join(os.path.dirname(AQUI), "references", "_schema.json")

_ESQ = None


def esquema(caminho=SCHEMA):
    global _ESQ
    if _ESQ is None:
        with open(caminho, encoding="utf-8") as fh:
            _ESQ = json.load(fh)
    return _ESQ


def NUCLEO():
    return list(esquema()["x_nucleo"])


def LIMIAR(nome):
    return esquema()["x_limiares"][nome]


# ---------------------------------------------------------------- percentis
def pct(vals, q):
    """np.percentile com o método `linear` (o default) — é o que torna os
    números desta spec reproduzíveis e os critérios de aceite verificáveis."""
    return float(np.percentile(np.asarray(vals, dtype=float), q))


def mediana(vals):
    return pct(vals, 50)


# --------------------------------------------------------------------- cor
def _hex_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"hex inválido: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(max(0, min(255, c)))) for c in rgb)


def _f(t):
    return t ** (1 / 3) if t > 0.008856451679035631 else t / 7.787037037037035 + 4 / 29


def rgb_lab(rgb):
    """sRGB 0-255 → CIELab (D65). Sem dependência externa de propósito."""
    r, g, b = [c / 255.0 for c in rgb]
    r, g, b = [(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
               for c in (r, g, b)]
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.00000
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_rgb(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def inv(t):
        c = t ** 3
        return c if c > 0.008856451679035631 else (t - 4 / 29) * 3 * (6 / 29) ** 2
    x, y, z = inv(fx) * 0.95047, inv(fy) * 1.0, inv(fz) * 1.08883
    r = 3.2406 * x - 1.5372 * y - 0.4986 * z
    g = -0.9689 * x + 1.8758 * y + 0.0415 * z
    b2 = 0.0557 * x - 0.2040 * y + 1.0570 * z
    out = []
    for c in (r, g, b2):
        c = max(0.0, min(1.0, c))
        out.append(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))
    return tuple(out)


def deltae76(l1, l2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(l1, l2)))


# ------------------------------------------------------------------- Param
def _base_param(agg, fonte, metodo, por_ref, n_total, faltou, qualidade, nota):
    return {
        "v": None, "agg": agg, "n": len(por_ref), "n_total": n_total,
        "disp": None, "conf": "baixa", "fonte": fonte, "metodo": metodo,
        "por_ref": por_ref, "faltou": faltou, "qualidade": qualidade, "nota": nota,
    }


def _conf_regras(classe, n, qualidade, **kw):
    """A fórmula de §3.4, lida do bloco `x_conf` do schema."""
    if qualidade == "suspeita":
        return "baixa"
    if n <= 1:
        return "baixa"
    for r in esquema()["x_conf"].get(classe, []):
        if n < r.get("n_min", 0) or n > r.get("n_max", 10 ** 9):
            continue
        if "cv_max" in r and (kw.get("cv") is None or kw["cv"] > r["cv_max"]):
            continue
        if "fracao_min" in r and (kw.get("fracao") is None or kw["fracao"] < r["fracao_min"]):
            continue
        if "deltae_max" in r and (kw.get("deltae") is None or kw["deltae"] > r["deltae_max"]):
            continue
        if "presente_min" in r and (kw.get("presente") is None or kw["presente"] < r["presente_min"]):
            continue
        return r["conf"]
    return "baixa"


def param_escalar(por_ref, *, fonte, metodo, n_total, faltou=(), qualidade="ok",
                  nota=None, envelope=False):
    """Escalar contínuo → mediana + {p25,p75,iqr,cv}.
    `envelope=True` → é um LIMITE, não um alvo: v = p90 e a faixa [p10,p90]."""
    p = _base_param("faixa" if envelope else "mediana", fonte, metodo,
                    dict(por_ref), n_total, list(faltou), qualidade, nota)
    vals = [float(x) for x in por_ref.values()]
    if not vals:
        return p
    if envelope:
        p10, p90 = pct(vals, 10), pct(vals, 90)
        p["v"] = round(p90, 4)
        p["disp"] = {"p10": round(p10, 4), "p90": round(p90, 4)}
    else:
        med, p25, p75 = mediana(vals), pct(vals, 25), pct(vals, 75)
        iqr = p75 - p25
        cv = (iqr / abs(med)) if med else None
        p["v"] = round(med, 4)
        p["disp"] = {"p25": round(p25, 4), "p75": round(p75, 4),
                     "iqr": round(iqr, 4),
                     "cv": None if cv is None else round(cv, 4)}
    cv = None if p["disp"] is None else p["disp"].get("cv")
    p["conf"] = _conf_regras("escalar", p["n"], qualidade, cv=cv)
    return p


def param_categorico(por_ref, *, fonte, metodo, n_total, faltou=(), qualidade="ok", nota=None):
    p = _base_param("moda", fonte, metodo, dict(por_ref), n_total, list(faltou), qualidade, nota)
    if not por_ref:
        p["disp"] = {"votos": {}, "fracao_moda": 0.0}
        return p
    votos = {}
    for v in por_ref.values():
        k = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v
        votos[k] = votos.get(k, 0) + 1
    moda, n_moda = max(sorted(votos.items(), key=lambda kv: str(kv[0])), key=lambda kv: kv[1])
    fr = n_moda / len(por_ref)
    p["v"] = moda
    p["disp"] = {"votos": votos, "fracao_moda": round(fr, 4)}
    p["conf"] = _conf_regras("categorico", p["n"], qualidade, fracao=fr)
    # A fórmula de §3.4 é literal e não trata empate. Empate de moda torna `v`
    # ARBITRÁRIO (o desempate é alfabético) — isso vai escrito, para o consumidor
    # ver que o "vencedor" não venceu.
    empatados = sorted(k for k, c in votos.items() if c == n_moda)
    if len(empatados) > 1:
        aviso = ("empate na moda entre %s (%d voto(s) cada): `v` é o desempate "
                 "alfabético, não um vencedor" % (", ".join(map(str, empatados)), n_moda))
        p["nota"] = aviso if not p.get("nota") else f"{p['nota']} · {aviso}"
    return p


def param_cor(por_ref, *, fonte, metodo, n_total, faltou=(), qualidade="ok", nota=None):
    """Mediana em CIELab, convertida de volta para hex. Média de hex entre
    #F14418 e #EECD3B dá um marrom que não é nenhuma das duas."""
    p = _base_param("mediana", fonte, metodo, dict(por_ref), n_total, list(faltou),
                    qualidade, nota)
    labs, ok = [], {}
    for ref, h in por_ref.items():
        try:
            labs.append(rgb_lab(_hex_rgb(h)))
            ok[ref] = h
        except (ValueError, TypeError, AttributeError):
            p["faltou"].append({"ref": ref, "motivo": f"hex inválido: {h!r}"})
    p["por_ref"] = ok
    p["n"] = len(ok)
    if not labs:
        return p
    centro = tuple(float(np.median([l[i] for l in labs])) for i in range(3))
    p["v"] = _rgb_hex(lab_rgb(centro))
    des = [deltae76(l, centro) for l in labs]
    dm = float(np.median(des))
    p["disp"] = {"deltaE_mediano_ao_centro": round(dm, 2),
                 "deltaE_max": round(max(des), 2),
                 "lab_centro": [round(c, 2) for c in centro]}
    p["conf"] = _conf_regras("cor", p["n"], qualidade, deltae=dm)
    return p


def param_conjunto(por_ref, *, fonte, metodo, n_total, faltou=(), qualidade="ok",
                   nota=None, corte_presente=None):
    """União com frequência: cada item carrega `presente_em = k/N`.
    `v` é a lista de itens acima de `corte_presente` (default: o limiar da
    variante padrão), em ordem decrescente de suporte."""
    if corte_presente is None:
        corte_presente = LIMIAR("variante_padrao_presente_em")
    p = _base_param("uniao", fonte, metodo, dict(por_ref), n_total, list(faltou),
                    qualidade, nota)
    n = len(por_ref)
    if not n:
        p["disp"] = {"itens": []}
        return p
    cont = {}
    for itens in por_ref.values():
        for it in set(itens or []):
            cont[it] = cont.get(it, 0) + 1
    itens = sorted(({"item": k, "presente_em": round(v / n, 4), "k": v, "de": n}
                    for k, v in cont.items()),
                   key=lambda d: (-d["presente_em"], d["item"]))
    p["disp"] = {"itens": itens}
    p["v"] = [d["item"] for d in itens if d["presente_em"] >= corte_presente]
    melhor = max((d["presente_em"] for d in itens), default=0.0)
    p["conf"] = _conf_regras("conjunto", n, qualidade, presente=melhor)
    return p


def param_ausente(agg, *, fonte, metodo, n_total, motivo, refs=()):
    """O Param que diz honestamente 'não medi'. `v: null`, `conf: baixa`."""
    p = _base_param(agg, fonte, metodo, {}, n_total,
                    [{"ref": r, "motivo": motivo} for r in refs], "ok", motivo)
    return p


def rebaixar(p, motivo):
    """Guarda: marca o Param como suspeito e força conf baixa (§3.9a / §3.7)."""
    p["qualidade"] = "suspeita"
    p["conf"] = "baixa"
    p["nota"] = motivo if not p.get("nota") else f"{p['nota']} · {motivo}"
    return p


# --------------------------------------------------------------- o corpus
def carregar_corpus(corpus_dir):
    d = os.path.join(corpus_dir, "medicoes")
    if not os.path.isdir(d):
        sys.exit(f"erro: {d} não existe — rode medir-ref.py antes")
    meds = []
    for nome in sorted(os.listdir(d)):
        if not nome.endswith(".json"):
            continue
        with open(os.path.join(d, nome), encoding="utf-8") as fh:
            m = json.load(fh)
        if not str(m.get("contrato", "")).startswith("benchmark.medicao-ref"):
            print(f">> ignorando {nome}: contrato {m.get('contrato')!r}", file=sys.stderr)
            continue
        m["_arquivo"] = os.path.join("medicoes", nome)
        migrar_medicao(m)
        meds.append(m)
    if not meds:
        sys.exit(f"erro: nenhuma medição em {d}")
    return meds


# Campos que trocaram de nome, com a CONVERSÃO explícita quando a unidade muda.
# (grupo, campo novo, campo legado, função)
MIGRACOES_DE_LEITURA = (
    ("legenda", "altura_glifo_pct", "altura_glifo_px_1920", lambda v: round(v / 1920 * 100, 2)),
)


def migrar_medicao(m):
    """Sobe uma medição gravada por um extrator ANTIGO para os nomes de hoje.

    🔴 Por que uma tabela com função, e não uma lista de sinônimos: entre
    `altura_glifo_px_1920` e `altura_glifo_pct` não muda só o nome, muda a
    UNIDADE. Ler o px legado dentro de um campo chamado `_pct` daria 175 onde o
    valor certo é 9,1 — um número errado com nome certo, que é o pior resultado
    possível: ele agrega, dispersa e sai na ficha como se tivesse sido medido
    assim. Medido nesta sessão, no corpus de 4 VSLs, antes deste conserto.

    Não sobrescreve o que já veio no novo nome. O campo legado FICA no dict —
    quem quiser auditar a medição original continua achando o número dela."""
    med = m.get("medido") or {}
    for grupo, novo, legado, conv in MIGRACOES_DE_LEITURA:
        g = med.get(grupo)
        if not isinstance(g, dict) or g.get(novo) is not None:
            continue
        v = g.get(legado)
        if isinstance(v, (int, float)):
            g[novo] = conv(v)
            m.setdefault("_migrado", []).append("%s.%s ← %s" % (grupo, novo, legado))
    return m


def _cam(med, dotted):
    grupo, _, chave = dotted.partition(".")
    return (med.get("medido", {}).get(grupo) or {}).get(chave)


# Como cada parâmetro do NÚCLEO é lido da medição e agregado.
# (classe, campo na medição, fonte, método)
NUCLEO_MAPA = {
    "montagem.cortes_por_min":   ("escalar", "montagem.cortes_por_min", "medido", "ritmo.py --fps 8"),
    "montagem.plano_mediano_s":  ("escalar", "montagem.plano_mediano_s", "medido", "ritmo.py --fps 8"),
    "plano.gramatica":           ("categorico", "plano.gramatica", "medido", "reframe.py à mão (guarda §3.9b)"),
    "plano.punch_ins_por_min":   ("escalar", "plano.punch_ins_por_min", "semantico", "deep-edit.punch_ins[]"),
    "legenda.presente_pct":      ("escalar", "legenda.presente_pct_do_tempo", "medido", "tipografia.py --fps 2"),
    "legenda.estilo":            ("categorico", "legenda.estilo", "semantico", "deep-edit.legendas.estilo"),
    "legenda.y_centro_pct":      ("escalar", "legenda.y_centro_pct", "medido", "tipografia.py --fps 2"),
    "legenda.cor_base":          ("cor", "legenda.cor_base", "medido", "tipografia.py --fps 2"),
    "grafismo.elementos_por_10s": ("escalar", "grafismo.elementos_por_10s", "semantico", "deep-edit.densidade"),
    "grafismo.max_simultaneos":  ("escalar", "grafismo.max_simultaneos", "semantico", "deep-edit.densidade"),
    "som.trilha_tipo":           ("categorico", "som.trilha_tipo", "semantico", "deep-edit.trilha.tipo"),
    "som.lufs_integrado":        ("escalar", "som.lufs_integrado", "medido", "ffmpeg ebur128"),
}

CONSTRUTOR = {"escalar": param_escalar, "categorico": param_categorico,
              "cor": param_cor, "conjunto": param_conjunto}


def montar_param(meds, classe, campo, fonte, metodo, **kw):
    n_total = len(meds)
    por_ref, faltou = {}, []
    for m in meds:
        v = _cam(m, campo)
        if v is None:
            faltou.append({"ref": m["id"], "motivo": f"{campo} ausente na medição"})
        else:
            por_ref[m["id"]] = v
    return CONSTRUTOR[classe](por_ref, fonte=fonte, metodo=metodo, n_total=n_total,
                              faltou=faltou, **kw)


def familia_ritmo_densidade():
    return set(esquema()["x_familia_ritmo_densidade"])


def aplicar_guardas(nome, p, meds):
    """As guardas que rebaixam um Param, todas com o motivo gravado."""
    fam = familia_ritmo_densidade()
    # (a) cortes.py mede a PÓS, não a montagem — frac_camada alta contamina ritmo
    if nome in ("montagem.cortes_por_min", "montagem.plano_mediano_s",
                "montagem.plano_medio_s"):
        lim = LIMIAR("frac_camada_suspeita")
        sujas = [m["id"] for m in meds
                 if (m.get("medido", {}).get("montagem", {}).get("frac_camada") or 0) >= lim]
        if sujas:
            rebaixar(p, "cortes.py mede a pós: frac_camada >= %.2f em %s — "
                        "medir com fiducial fixo da cena" % (lim, ", ".join(sujas)))
    # temperatura mista contamina ritmo/densidade (§3.7)
    if nome in fam:
        temps = {(m.get("declarado", {}) or {}).get("temperatura") for m in meds}
        temps.discard(None)
        temps.discard("na")
        if len(temps) > 1:
            rebaixar(p, "temperatura mista no corpus (%s): ritmo/densidade é função da "
                        "temperatura do tráfego, não de gosto" % ", ".join(sorted(temps)))
    return p


def params_nucleo(meds):
    out = {}
    for nome, (classe, campo, fonte, metodo) in NUCLEO_MAPA.items():
        out[nome] = aplicar_guardas(nome, montar_param(meds, classe, campo, fonte, metodo), meds)
    return out


# --------------------------------------------------------- score / clusters
def score_de(params):
    ok = [k for k, p in params.items() if p["conf"] in ("alta", "media")]
    falhou = [k for k in params if k not in ok]
    return round(len(ok) / len(params), 4) if params else 0.0, sorted(ok), sorted(falhou)


def estado_de(score):
    if score >= LIMIAR("coerencia_pronto"):
        return "pronto"
    if score >= LIMIAR("coerencia_incoerente"):
        return "parcial"
    return "incoerente"


def clusters_de(meds, params, k=2):
    """Partição aglomerativa (ligação completa, distância euclidiana) cortada em
    k=2 sobre os 3 escalares-núcleo de maior cv, normalizados por (x-mediana)/iqr.
    Com N <= 6 isso é exato e cabe aqui — `sklearn` está fora de propósito."""
    escalares = [(k2, p) for k2, p in params.items()
                 if p["agg"] == "mediana" and isinstance(p.get("disp"), dict)
                 and p["disp"].get("cv") is not None and p["n"] == len(meds)]
    escalares.sort(key=lambda kv: -kv[1]["disp"]["cv"])
    usados = escalares[:3]
    ids = [m["id"] for m in meds]
    if len(ids) < 2 or not usados:
        return [], [u[0] for u in usados]
    X = []
    for i in ids:
        linha = []
        for nome, p in usados:
            iqr = p["disp"]["iqr"] or 1e-9
            linha.append((float(p["por_ref"][i]) - float(p["v"])) / iqr)
        X.append(linha)
    X = np.asarray(X, float)
    grupos = [[i] for i in range(len(ids))]

    def dist(a, b):
        return max(float(np.linalg.norm(X[i] - X[j])) for i in a for j in b)

    while len(grupos) > k:
        melhor, par = None, None
        for i in range(len(grupos)):
            for j in range(i + 1, len(grupos)):
                d = dist(grupos[i], grupos[j])
                if melhor is None or d < melhor:
                    melhor, par = d, (i, j)
        i, j = par
        grupos[i] = grupos[i] + grupos[j]
        grupos.pop(j)

    saida = []
    for g in grupos:
        separa, melhor = None, -1.0
        for idx, (nome, p) in enumerate(usados):
            dentro = [X[i][idx] for i in g]
            fora = [X[i][idx] for i in range(len(ids)) if i not in g]
            if not fora:
                continue
            d = abs(float(np.mean(dentro)) - float(np.mean(fora)))
            if d > melhor:
                melhor, separa = d, nome
        saida.append({"refs": sorted(ids[i] for i in g), "separa_por": separa})
    saida.sort(key=lambda c: c["refs"])
    return saida, [u[0] for u in usados]


def denominador_de(params):
    """Os Param que fecharam mesmo assim — a parte útil de um corpus incoerente."""
    return {k: p for k, p in sorted(params.items()) if p["conf"] in ("alta", "media")}


def veredito_de(meds, params, score, estado, clusters, usados):
    ids = [m["id"] for m in meds]
    denom = sorted(denominador_de(params))
    if estado == "pronto":
        return ("as %d referências compartilham estilo: %d dos %d parâmetros-núcleo "
                "fecharam (score %.2f). O que sustenta: %s."
                % (len(ids), len(denom), len(params), score, ", ".join(denom[:4])))
    sep = clusters[0]["separa_por"] if clusters else (usados[0] if usados else "—")
    p = params.get(sep or "")
    detalhe = ""
    if p and p["por_ref"]:
        grupos = [" · ".join("%s" % p["por_ref"][r] for r in c["refs"] if r in p["por_ref"])
                  for c in clusters]
        detalhe = " (%s)" % " contra ".join(g for g in grupos if g)
    comum = ", ".join(denom) if denom else "nada"
    cabeca = ("as %d referências NÃO compartilham um estilo" if estado == "incoerente"
              else "as %d referências compartilham parte do estilo")
    return (("%s: elas se separam por %s%s. Score %.2f — %d de %d parâmetros-núcleo "
             "fecharam. O que as %d têm em comum: %s. Rode de novo separando o corpus, "
             "ou aceite só o denominador comum.")
            % (cabeca % len(ids), sep, detalhe, score, len(denom), len(params),
               len(ids), comum))


def avaliar(meds, params=None):
    """`params` permite avaliar os Param que o agregador JÁ construiu, em vez de
    construir uma segunda cópia — senão o mesmo parâmetro aparece duas vezes no
    artefato, com notas diferentes. Sem ele, monta os do núcleo sozinho (é o
    modo standalone, o "vale a pena agregar isso?")."""
    params = params or params_nucleo(meds)
    faltando = [k for k in NUCLEO() if k not in params]
    if faltando:
        sys.exit("núcleo incompleto, faltam: %s" % ", ".join(faltando))
    score, ok, falhou = score_de(params)
    estado = estado_de(score)
    cl, usados = clusters_de(meds, params)
    return {
        "corpus_dir_refs": [m["id"] for m in meds],
        "score": score, "estado": estado,
        "nucleo_ok": ok, "nucleo_falhou": falhou,
        "clusters": cl, "clusters_por": usados,
        "denominador_comum": denominador_de(params),
        "veredito": veredito_de(meds, params, score, estado, cl, usados),
        "_params": params,
    }


# ---------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    meds = carregar_corpus(a.corpus_dir)
    r = avaliar(meds)

    if a.json:
        saida = {k: v for k, v in r.items() if k != "_params"}
        saida["denominador_comum"] = {k: v for k, v in r["denominador_comum"].items()}
        print(json.dumps(saida, ensure_ascii=False))
        return

    print(f"corpus: {len(meds)} referências — {', '.join(m['id'] for m in meds)}")
    print(f"score {r['score']:.2f}  →  {r['estado'].upper()}"
          f"   ({len(r['nucleo_ok'])}/{len(NUCLEO())} do núcleo fecharam)")
    print("\n  parâmetro                     conf   n   v            dispersão")
    for k in NUCLEO():
        p = r["_params"][k]
        d = p.get("disp") or {}
        disp = ""
        if "cv" in d:
            disp = f"cv={d['cv']}" if d["cv"] is not None else ""
        elif "fracao_moda" in d:
            disp = f"moda={d['fracao_moda']}"
        elif "deltaE_mediano_ao_centro" in d:
            disp = f"ΔE={d['deltaE_mediano_ao_centro']}"
        marca = {"alta": "✅", "media": "🟡", "baixa": "⚠️ "}[p["conf"]]
        print(f"  {k:<28} {marca}{p['conf']:<6} {p['n']}  {str(p['v'])[:12]:<12} {disp}")
    if r["clusters"]:
        print("\n  clusters (k=2, por %s):" % ", ".join(r["clusters_por"]))
        for c in r["clusters"]:
            print(f"    · {', '.join(c['refs'])}   separa_por={c['separa_por']}")
    print("\n  veredito: " + r["veredito"])


if __name__ == "__main__":
    main()
