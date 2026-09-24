#!/usr/bin/env python3
"""Comparacao conservadora de ASR para emendas.

O modulo separa tres estados: aprovado, revisao e falha. Equivalencias de
formatacao numerica passam; flexao e troca PT/ES com palavra incerta pedem
revisao; palavra realmente ausente, fora de ordem ou excedente continuam
falhando.
"""

from __future__ import annotations

import re
import unicodedata


NUMEROS_PT = {
    "zero": "0", "dois": "2", "duas": "2",
    "tres": "3", "quatro": "4", "cinco": "5", "seis": "6",
    "sete": "7", "oito": "8", "nove": "9", "dez": "10",
    "onze": "11", "doze": "12", "treze": "13", "quatorze": "14",
    "catorze": "14", "quinze": "15", "dezesseis": "16",
    "dezessete": "17", "dezoito": "18", "dezenove": "19", "vinte": "20",
}

# `um` e `uma` ficam lexicais: fundi-los em `1` escondia troca de gênero/artigo.
# A equivalência com o dígito é aplicada só ao comparar palavra contra dígito.
NUMERO_UM = {"um", "uma"}

# Equivalências estreitas observadas no falso positivo PT/ES do relatório. Só a
# confiança da TRANSCRIÇÃO da própria palavra pode rebaixar a troca: confidence
# global e language_confidence não dizem que aquele token foi ouvido com dúvida.
EQUIV_PT_ES = {
    frozenset(("estou", "estoy")),
    frozenset(("e", "y")),
    frozenset(("sim", "si")),
    frozenset(("nao", "no")),
}


def tokens(texto: str) -> list[str]:
    """Normaliza acentos, caixa, pontuacao e numeros PT-BR simples."""
    s = unicodedata.normalize("NFD", (texto or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    palavras = [w for w in re.split(r"[^a-z0-9%]+", s) if w]
    return [NUMEROS_PT.get(w, w) for w in palavras]


def _numero_equivalente(a: str, b: str) -> bool:
    """Formatação `um`/`uma` ↔ `1`, sem fundir as duas formas entre si."""
    return ((a == "1" and b in NUMERO_UM)
            or (b == "1" and a in NUMERO_UM))


def _token_aprovavel(esperado: str, ouvido: str) -> bool:
    return esperado == ouvido or _numero_equivalente(esperado, ouvido)


def _flexao_equivalente(a: str, b: str) -> bool:
    """Equivalencia leve e deliberadamente estreita de gênero ou número."""
    if a == b or a.isdigit() or b.isdigit():
        return False
    if {a, b} == NUMERO_UM:
        return True
    excecoes = {"mais", "mas", "mes", "tres", "seis", "pais", "depois"}
    if a in excecoes or b in excecoes:
        return False
    if min(len(a), len(b)) < 4:
        return False
    return (a.endswith("s") and a[:-1] == b) or (b.endswith("s") and b[:-1] == a)


def _evidencia_troca_idioma(meta: dict | None, token: str) -> dict | None:
    """Evidência lexical do Nova-3 multi, nunca confiança global/de idioma.

    `words[].confidence` mede a confiança da transcrição daquela palavra. Já
    `alternatives[].confidence` é global e `language_confidence` pertence ao
    detector de idioma; nenhum dos dois autoriza sozinho uma equivalência PT/ES.
    """
    meta = meta or {}
    if not isinstance(meta.get("words"), list):
        return None
    for palavra in meta["words"]:
        texto = str(palavra.get("word") or palavra.get("punctuated_word") or "")
        if not any(_token_aprovavel(token, t) for t in tokens(texto)):
            continue
        idioma = str(palavra.get("language") or "").lower()
        try:
            confianca = float(palavra["confidence"])
        except (KeyError, TypeError, ValueError):
            continue
        if idioma and not idioma.startswith("pt") and confianca < 0.80:
            return {"idioma_palavra": idioma, "confianca_palavra": confianca}
    return None


def _pt_es_equivalente(a: str, b: str) -> bool:
    return a != b and frozenset((a, b)) in EQUIV_PT_ES


def _equivalencia(esperado: str, ouvido: str,
                  meta: dict | None) -> tuple[str, dict] | None:
    """Classe de um pareamento permitido, da mais forte à mais fraca."""
    if _token_aprovavel(esperado, ouvido):
        return "APROVADO", {}
    if _flexao_equivalente(esperado, ouvido):
        return "FLEXAO", {}
    if _pt_es_equivalente(esperado, ouvido):
        evidencia = _evidencia_troca_idioma(meta, ouvido)
        if evidencia:
            return "TROCA_IDIOMA_PALAVRA_INCERTA", evidencia
    return None


def _casa_contexto(esperado: list[str], ouvido: list[str]) -> bool:
    return (len(esperado) == len(ouvido)
            and all(_token_aprovavel(a, b) for a, b in zip(esperado, ouvido)))


def _ocorrencias_contexto(texto: list[str], contexto: list[str]) -> list[int]:
    return [i for i in range(len(texto) - len(contexto) + 1)
            if _casa_contexto(contexto, texto[i:i + len(contexto)])]


def _contexto_borda_unico(lado: list[str], posicao: str) -> list[str]:
    """Menor prefixo/sufixo que só pode apontar para a borda pretendida."""
    for largura in range(1, len(lado) + 1):
        contexto = lado[-largura:] if posicao == "fim" else lado[:largura]
        if len(_ocorrencias_contexto(lado, contexto)) == 1:
            return contexto
    return list(lado)


def _correspondencias_borda(lado: list[str], got: list[str], posicao: str,
                            meta: dict | None) -> list[tuple[int, dict | None]]:
    """Ocorrências comprovadas pelo menor contexto de borda não ambíguo.

    Um bigrama basta apenas quando ele é único. Se também se repete, amplia-se o
    contexto até distinguir a ocorrência final/inicial. A flexão ou troca PT/ES
    é tolerada somente no próprio token de borda; o restante do contexto precisa
    casar de forma aprovável.
    """
    if not lado:
        return []
    contexto = _contexto_borda_unico(lado, posicao)
    offset_borda = len(contexto) - 1 if posicao == "fim" else 0
    achados = []
    for inicio in range(len(got) - len(contexto) + 1):
        revisao = None
        for deslocamento, esperado in enumerate(contexto):
            ouvido = got[inicio + deslocamento]
            classe = _equivalencia(esperado, ouvido, meta)
            if not classe or (deslocamento != offset_borda
                              and classe[0] != "APROVADO"):
                break
            if classe[0] != "APROVADO":
                revisao = {"codigo": classe[0], "lado": posicao,
                            "esperado": esperado, "ouvido": ouvido,
                            **classe[1]}
        else:
            achados.append((inicio + offset_borda, revisao))
    return achados


def _candidatos_borda_ambigua(lado: list[str], got: list[str], posicao: str,
                              meta: dict | None) -> list[tuple[int, str, dict]]:
    """Token de borda presente, mas sem o contexto que distingue a repetição."""
    contexto = _contexto_borda_unico(lado, posicao)
    if len(contexto) <= 1:
        return []
    esperado = lado[-1] if posicao == "fim" else lado[0]
    candidatos = []
    for indice, ouvido in enumerate(got):
        classe = _equivalencia(esperado, ouvido, meta)
        if classe:
            candidatos.append((indice, ouvido, classe[1]))
    return candidatos


def _alinhar_sequencial(esperado: list[str], got: list[str],
                        meta: dict | None) -> tuple[list[dict], list[dict]]:
    """Alinha tokens em ordem e acusa cada ocorrência ouvida sem par esperado.

    Prefixo/sufixo ausente é normal numa janela curta e tokens de até dois
    caracteres mantêm a tolerância histórica. Cada ocorrência esperada, porém,
    só pode ser consumida uma vez: assim uma palavra conhecida duplicada deixa de
    desaparecer dentro de um `set`, sem punir repetição realmente prevista.
    """
    relevantes = [(i, palavra) for i, palavra in enumerate(got) if len(palavra) > 2]
    n, m = len(esperado), len(relevantes)
    # Estado: quantidade casada, qualidade (exato > revisão), pares reconstruídos.
    vazio = (0, 0, ())
    dp = [[vazio for _ in range(m + 1)] for _ in range(n + 1)]

    def chave(estado):
        return estado[0], estado[1]

    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            candidatos = []
            if i and j:
                indice_got, ouvido = relevantes[j - 1]
                classe = _equivalencia(esperado[i - 1], ouvido, meta)
                if classe:
                    anterior = dp[i - 1][j - 1]
                    qualidade = 2 if classe[0] == "APROVADO" else 1
                    par = (indice_got, i - 1, classe[0], classe[1])
                    candidatos.append((anterior[0] + 1, anterior[1] + qualidade,
                                       anterior[2] + (par,)))
            if i:
                candidatos.append(dp[i - 1][j])
            if j:
                candidatos.append(dp[i][j - 1])
            dp[i][j] = max(candidatos, key=chave)

    pares = dp[n][m][2]
    casados = {par[0] for par in pares}
    revisoes = []
    for indice_got, indice_esperado, codigo, evidencia in pares:
        if codigo == "APROVADO":
            continue
        revisoes.append({"codigo": codigo,
                          "esperado": esperado[indice_esperado],
                          "ouvido": got[indice_got], **evidencia})
    falhas = [{"codigo": "VAZOU", "palavra": palavra}
              for indice, palavra in relevantes if indice not in casados]
    return revisoes, falhas


def comparar(fala_esquerda: str, fala_direita: str, ouvido: str,
             meta: dict | None = None) -> dict:
    """Compara uma emenda e devolve estado + evidencias estruturadas."""
    esquerda, direita, got = tokens(fala_esquerda), tokens(fala_direita), tokens(ouvido)
    revisoes: list[dict] = []
    falhas: list[dict] = []

    ultima = esquerda[-1] if esquerda else None
    primeira = direita[0] if direita else None
    indices_bordas: dict[str, list[int]] = {}
    for lado, esperado, contexto in (("fim", ultima, esquerda),
                                     ("inicio", primeira, direita)):
        if not esperado:
            continue
        correspondencias = _correspondencias_borda(contexto, got, lado, meta)
        if correspondencias:
            indices_bordas[lado] = [indice for indice, _ in correspondencias]
            # Uma ocorrência aprovável vence alternativas que exigiriam revisão.
            if not any(revisao is None for _, revisao in correspondencias):
                revisoes.append(correspondencias[0][1])
        else:
            ambiguos = _candidatos_borda_ambigua(contexto, got, lado, meta)
            if ambiguos:
                indices_bordas[lado] = [indice for indice, _, _ in ambiguos]
                _, equivalente, evidencia = ambiguos[0]
                revisoes.append({
                    "codigo": "BORDA_AMBIGUA", "lado": lado,
                    "esperado": esperado, "ouvido": equivalente,
                    "contexto_necessario": _contexto_borda_unico(contexto, lado),
                    **evidencia,
                })
            else:
                falhas.append({"codigo": "SUMIU", "lado": lado,
                               "palavra": esperado})

    if (indices_bordas.get("fim") and indices_bordas.get("inicio")
            and not any(a < b for a in indices_bordas["fim"]
                        for b in indices_bordas["inicio"])):
        falhas.append({"codigo": "ORDEM_BORDA", "fim": ultima, "inicio": primeira})

    revisoes_alinhamento, falhas_alinhamento = _alinhar_sequencial(
        esquerda + direita, got, meta)
    revisoes.extend(revisoes_alinhamento)
    falhas.extend(falhas_alinhamento)

    estado = "falha" if falhas else ("revisao" if revisoes else "aprovado")
    return {"estado": estado, "falhas": falhas, "revisoes": revisoes,
            "tokens": {"esquerda": esquerda, "direita": direita, "ouvido": got}}
