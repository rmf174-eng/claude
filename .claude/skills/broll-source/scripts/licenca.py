#!/usr/bin/env python3
"""licenca — o gate ÚNICO de licença da skill, e a validação de bytes do download.

Existe por causa de um defeito medido (SPEC-29 §1.2): o filtro do `wikimedia()`
era `any(t in lic.lower() for t in ("cc0", "public domain", "cc by"))`, e o
comentário ao lado dele prometia cortar `CC BY-SA` e `CC BY-NC`. Não cortava:
`"cc by-sa 4.0"` CONTÉM a substring `"cc by"`. Medido contra a API do Commons em
2026-08-08: 24/24 candidatos passavam, 13 deles `CC BY-SA`.

O conserto tem duas partes, e as duas estão aqui:

  1. **tokenizar, não fatiar string.** `"CC BY-SA 3.0 de"` vira o conjunto
     {cc, by, sa, 3, 0, de}; `sa` é um token, não uma substring perdida no meio.
  2. **cláusula ANTES de família.** NC/ND/SA são testados antes de BY. Testar a
     família primeiro é exatamente o bug — e o `--autoteste` prova isso rodando a
     ordem invertida contra a mesma tabela e exigindo que ela REPROVE.

A régua não é configurável; a POLÍTICA é (`--licencas` do buscar.py). O default é
`cc0,dominio-publico,cc-by`. `desconhecido` NUNCA é livre: a decisão default é NÃO.

Uso:
    licenca.py --autoteste            # sai 1 se qualquer caso divergir
    licenca.py "CC BY-SA 4.0"         # → slug, veredito e motivo, uma linha

Biblioteca:
    classificar(bruta)  -> dict   {slug, livre_comercial, exige_atribuicao, viral, motivo}
    aprovado(cl, politica) -> (bool, motivo)
    eh_imagem(bytes)    -> bool   assinatura de formato (tabela, spec pública)
    eh_pagina(bytes)    -> bool   HTML/XML no primeiro bloco = servidor devolveu página
"""
# A classificação de licença com domínio fechado e a regra "cláusula antes de
# família" são nossas — o que se via em ferramenta de referência não filtrava
# licença nenhuma, só imprimia o nome curto dela.
import re
import sys
import unicodedata

# ---------------------------------------------------------------- domínio FECHADO
# Um slug fora desta lista é erro de programação, não entrada de usuário: quem
# escreve `--licencas` recebe abort com a lista inteira.
SLUGS_ARQUIVO = ("cc0", "dominio-publico", "cc-by", "cc-by-sa",
                 "cc-nc", "cc-nd", "gfdl", "desconhecido")
SLUGS_PROVEDOR = ("pexels", "pixabay", "mixkit")
SLUGS = SLUGS_ARQUIVO + SLUGS_PROVEDOR

# A política só se aplica a licença DE ARQUIVO (a que vem item a item do Commons).
# Mixkit/Pexels/Pixabay têm licença DE PROVEDOR, já checada no próprio provedor
# (o gate `"copyrightNotice":"Free"` do Mixkit, p.ex.) — o gate novo não os toca.
POLITICA_DEFAULT = ("cc0", "dominio-publico", "cc-by")

# ⚠️ A ORDEM DE TESTE É O CONSERTO: o MAIS ESPECÍFICO primeiro.
# "CC BY-SA 4.0" contém a substring "cc by". Testar família antes de cláusula foi
# exatamente o bug de buscar.py:120-121 (24/24 passando, 13 deles BY-SA).
CLAUSULAS_NC = ("nc", "noncommercial")
CLAUSULAS_ND = ("nd", "noderivs", "noderivatives")
CLAUSULAS_VIRAIS = ("sa", "sharealike")


def _tokens(bruta):
    """→ conjunto de tokens ASCII minúsculos.

    Tira acento ANTES de fatiar: sem isso `"NÃO é CC0"` viraria {n, o, cc0} e
    `"domínio público"` viraria {dom, nio, p, blico}. Acento como separador é o
    tipo de detalhe que faz um gate reprovar em português e passar em inglês.
    """
    s = unicodedata.normalize("NFD", (bruta or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("_", " ")
    return set(t for t in re.split(r"[^a-z0-9]+", s) if t)


def _r(slug, livre, credito, viral, motivo):
    return {"slug": slug, "livre_comercial": livre, "exige_atribuicao": credito,
            "viral": viral, "motivo": motivo}


def classificar(bruta, _inverter_ordem=False):
    """Classifica uma string de licença no domínio FECHADO acima.

    `_inverter_ordem=True` reproduz o BUG (família antes de cláusula) e existe só
    para o controle negativo do `--autoteste`. Não use em produção.
    """
    txt = (bruta or "").strip()
    if not txt or txt in ("?", "-"):
        return _r("desconhecido", False, True, False, "licença vazia ou '?'")
    t = _tokens(txt)

    # 0. licença DE PROVEDOR primeiro — a string do Pexels que o próprio buscar.py
    #    escreve contém literalmente "NÃO é CC0", e classificá-la como cc0 seria
    #    gravar um fato falso no índice.
    for p in SLUGS_PROVEDOR:
        if p in t:
            return _r(p, True, False, False, f"licença de provedor ({p}), livre para uso comercial")

    if "gfdl" in t or "gnu" in t:
        return _r("gfdl", False, True, True,
                  "GFDL: copyleft que exige carregar o texto da licença junto — inviável em vídeo")

    familia_cc = bool(t & {"cc", "cc0", "creativecommons"}) or \
        ("creative" in t and "commons" in t)
    if not familia_cc:
        # "Attribution" sozinho, "PD-old-70", texto livre… nada disso é decidível.
        if {"public", "domain"} <= t or "pdm" in t or "publicdomain" in t \
                or {"dominio", "publico"} <= t:
            return _r("dominio-publico", True, False, False, "domínio público")
        return _r("desconhecido", False, True, False,
                  f"não reconhecida no domínio fechado: {txt[:60]!r}")

    ordem = ["familia", "clausula"] if _inverter_ordem else ["clausula", "familia"]
    for etapa in ordem:
        if etapa == "clausula":
            if t & set(CLAUSULAS_NC):
                return _r("cc-nc", False, True, False,
                          "cláusula NonCommercial: proíbe o uso que a gente faz")
            if t & set(CLAUSULAS_ND):
                return _r("cc-nd", False, True, False,
                          "cláusula NoDerivatives: compor dentro de um vídeo É obra derivada")
            if t & set(CLAUSULAS_VIRAIS):
                return _r("cc-by-sa", True, True, True,
                          "cláusula ShareAlike: a obra derivada herda a licença — "
                          "o vídeo inteiro vira argumento jurídico aberto")
        else:
            if "cc0" in t or "zero" in t:
                return _r("cc0", True, False, False, "CC0: renúncia de direitos")
            if {"public", "domain"} <= t or "pdm" in t or "publicdomain" in t:
                return _r("dominio-publico", True, False, False, "domínio público")
            if "by" in t or "attribution" in t:
                return _r("cc-by", True, True, False, "CC BY: livre para uso comercial COM crédito")
    return _r("desconhecido", False, True, False,
              f"família CC sem cláusula reconhecível: {txt[:60]!r}")


def aprovado(cl, politica=POLITICA_DEFAULT):
    """(bool, motivo). A política só governa licença DE ARQUIVO."""
    if not cl["livre_comercial"]:
        return False, cl["motivo"]
    if cl["slug"] in SLUGS_PROVEDOR:
        return True, cl["motivo"]
    if cl["slug"] not in politica:
        return False, f"fora da política (--licencas): {cl['slug']} — {cl['motivo']}"
    return True, cl["motivo"]


def validar_politica(txt):
    """'cc0,cc-by' → tupla validada contra o domínio fechado. Aborta se inventar slug."""
    pol = tuple(s.strip() for s in (txt or "").split(",") if s.strip())
    ruins = [s for s in pol if s not in SLUGS]
    if ruins:
        raise ValueError("slug de licença fora do domínio fechado: %s\n  válidos: %s"
                         % (", ".join(ruins), ", ".join(SLUGS)))
    return pol or POLITICA_DEFAULT


# ------------------------------------------------------------------ bytes
# (deslocamento, bytes) da assinatura de cada formato. Os valores são a
# especificação pública de cada um — JFIF/JPEG, RFC 2083 §3.1 para PNG, GIF89a,
# RIFF/WebP —, não a escolha de ninguém: uma tabela de magic numbers não tem
# expressão a proteger. Escrita como tabela, e não como cadeia de `or`, porque
# formato novo passa a ser uma linha de dado.
_ASSINATURAS = (
    ((0, b"\xff\xd8\xff"),),                       # JPEG/JFIF
    ((0, b"\x89PNG\r\n\x1a\n"),),                  # PNG
    ((0, b"GIF8"),),                                # GIF87a/89a
    ((0, b"RIFF"), (8, b"WEBP")),                   # WebP dentro de RIFF
    ((4, b"ftypavif"),),                            # AVIF
    ((4, b"ftypheic"),), ((4, b"ftypheix"),),       # HEIF
    ((0, b"II*\x00"),), ((0, b"MM\x00*"),),         # TIFF LE/BE
    ((0, b"BM"),),                                  # BMP
)


def eh_imagem(dados):
    """O primeiro bloco começa com a assinatura de algum formato de imagem?"""
    return any(all(dados[i:i + len(sig)] == sig for i, sig in grupo)
               for grupo in _ASSINATURAS)


_ABERTURAS = (b"<!doctype", b"<html", b"<?xml", b"<head", b"<body", b"<!--")


def eh_pagina(dados):
    """O primeiro bloco é uma PÁGINA, não mídia.

    O thumb server do Commons devolve HTML de erro com HTTP 200 (é a razão de
    existir de uma checagem de bytes antes de entregar o arquivo). Vale para
    vídeo também: hoje o defeito só é
    contido pelo ffmpeg, que reporta "Invalid data" — diagnóstico errado.
    """
    inicio = dados[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return any(inicio.startswith(a) for a in _ABERTURAS)


# ------------------------------------------------------------------ autoteste
# (entrada, slug, livre_comercial, exige_atribuicao) — o veredito default usa
# POLITICA_DEFAULT. A coluna "hoje" do aceite 1 da SPEC-29 está no comentário.
CASOS = [
    ("CC0",                       "cc0",            True,  False),   # hoje: passa ✅
    ("CC0 1.0 Universal",         "cc0",            True,  False),
    ("Public domain",             "dominio-publico", True, False),   # hoje: passa ✅
    ("PD-old-70",                 "desconhecido",   False, True),
    ("CC BY 2.0",                 "cc-by",          True,  True),    # hoje: passa ✅
    ("CC BY 4.0",                 "cc-by",          True,  True),
    ("CC BY-SA 4.0",              "cc-by-sa",       True,  True),    # hoje: PASSA 🔴
    ("CC BY-SA 3.0 de",           "cc-by-sa",       True,  True),    # hoje: PASSA 🔴
    ("CC BY-SA 2.0",              "cc-by-sa",       True,  True),    # hoje: PASSA 🔴
    ("CC BY-NC 4.0",              "cc-nc",          False, True),    # hoje: PASSA 🔴
    ("CC BY-NC-SA 4.0",           "cc-nc",          False, True),    # hoje: PASSA 🔴
    ("CC BY-ND 4.0",              "cc-nd",          False, True),    # hoje: PASSA 🔴
    ("Creative Commons Attribution-ShareAlike 4.0", "cc-by-sa", True, True),
    ("GFDL",                      "gfdl",           False, True),
    ("GNU Free Documentation License 1.2", "gfdl",  False, True),
    ("",                          "desconhecido",   False, True),
    ("?",                         "desconhecido",   False, True),
    ("Attribution",               "desconhecido",   False, True),
    ("Mixkit Stock Video Free License — comercial livre, sublicenciável",
     "mixkit", True, False),
    ("Pexels License — comercial livre; NÃO é CC0. Proíbe: vender cópia crua…",
     "pexels", True, False),
    ("Pixabay Content License — comercial livre desde que COMPOSTO",
     "pixabay", True, False),
]

# Os que a POLÍTICA default tem que reprovar mesmo sendo livres: SA é viral.
REPROVA_NA_POLITICA_DEFAULT = ("cc-by-sa",)


def autoteste(verboso=True):
    """→ 0 tudo certo · 1 divergência OU controle negativo sem dentes."""
    falhas = []
    for entrada, slug, livre, credito in CASOS:
        c = classificar(entrada)
        ok, _ = aprovado(c)
        esperado_ok = livre and slug not in REPROVA_NA_POLITICA_DEFAULT
        if (c["slug"], c["livre_comercial"], c["exige_atribuicao"], ok) != \
           (slug, livre, credito, esperado_ok):
            falhas.append(f"  ✗ {entrada[:44]!r}\n"
                          f"      esperado slug={slug} livre={livre} credito={credito} aprovado={esperado_ok}\n"
                          f"      obtido   slug={c['slug']} livre={c['livre_comercial']} "
                          f"credito={c['exige_atribuicao']} aprovado={ok}")

    # ---- CONTROLE NEGATIVO, obrigatório -------------------------------------
    # Um portão verde que varreu 0 caso é indistinguível de um quebrado. Aqui o
    # defeito é PLANTADO: a ordem invertida (família antes de cláusula) É o bug de
    # buscar.py:120-121. Se a tabela acima não acusar a ordem invertida, a tabela
    # não tem dentes e o autoteste sai 1 mesmo com tudo "verde".
    pegos = []
    for entrada, slug, livre, credito in CASOS:
        c = classificar(entrada, _inverter_ordem=True)
        if c["slug"] != slug:
            pegos.append((entrada, slug, c["slug"]))
    # E o predicado literal de buscar.py:124 (a substring de família), que é o que
    # roda em produção HOJE — a tabela tem que discordar dele.
    def _hoje(l):
        return any(t in l.lower() for t in ("cc0", "public domain", "cc by"))
    vazam = [e for e, s, livre, _ in CASOS
             if _hoje(e) and not (livre and s not in REPROVA_NA_POLITICA_DEFAULT)]

    if verboso:
        print(f"casos varridos: {len(CASOS)}")
        print(f"controle negativo (ordem invertida): {len(pegos)} caso(s) acusados")
        for e, esp, obt in pegos:
            print(f"    · {e[:40]!r}: {esp} → {obt}")
        print(f"vazam pelo predicado de HOJE (buscar.py, substring de família): "
              f"{len(vazam)} — {', '.join(repr(v[:20]) for v in vazam)}")
    if not pegos:
        falhas.append("  ✗ CONTROLE NEGATIVO SEM DENTES: a ordem invertida (o bug) "
                      "passou na tabela inteira. Acrescente um caso BY-SA/NC/ND.")
    if not vazam:
        falhas.append("  ✗ CONTROLE NEGATIVO SEM DENTES: o predicado de hoje não vaza "
                      "em nenhum caso da tabela — ela não cobre o defeito que a spec conserta.")
    if falhas:
        print(f"\n{len(falhas)} FALHA(S):", *falhas, sep="\n")
        return 1
    print("autoteste: OK")
    return 0


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] == "--autoteste":
        return autoteste()
    c = classificar(" ".join(a))
    ok, motivo = aprovado(c)
    print(f"{c['slug']} · {'APROVA' if ok else 'REPROVA'} · "
          f"{'exige crédito' if c['exige_atribuicao'] else 'sem crédito'}"
          f"{' · viral' if c['viral'] else ''} · {motivo}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
