#!/usr/bin/env python3
"""chaves.py — resolução preguiçosa de credencial (SPEC-22 §3.4).

    resolver(nome, *, recurso) -> str | None   # env → $ILHA_HOME/.env → None
    faltando(recurso)          -> list[str]    # quais chaves o recurso quer e não tem
    fallback(recurso)          -> str | None   # o que fazer sem chave; None = não há
    gravar(nome, valor)        -> None         # escreve no .env, chmod 600, nunca loga
    instrucoes(nome, recurso=None) -> str      # explica sem pedir nem expor valor
    pedir_e_gravar(nome)       -> int          # prompt oculto + gravação atômica
    executar_com(nome, comando)-> int          # injeta a chave só no subprocesso
    RECURSOS                   -> dict         # a tabela, lida do MANIFESTO.json

    python3 chaves.py --status                 # diagnóstico, sem valor de chave
    python3 chaves.py --pedir CHAVE            # solicita e salva com entrada oculta
    python3 chaves.py --executar-com CHAVE -- comando [args...]
    python3 chaves.py --contrato-cloud         # nomes/origens/booleanos em JSON
    python3 chaves.py --scan-segredos          # procura vazamento sem imprimir valor
    python3 chaves.py --raiz                   # onde a ilha acha que está
    python3 chaves.py --ativos                 # os ativos declarados, por sha256

═══════════════════════════════════════════════════════════════════════════
AS QUATRO DECISÕES
═══════════════════════════════════════════════════════════════════════════

1. `os.environ` SEMPRE VENCE o `.env`.

   Não é preferência: é o que impede este módulo de quebrar a sessão do Claude
   Code do creator-1, onde as chaves vivem no bloco `env` dos settings
   (`docs/CUSTOS.md`). Quem já tem tudo no ambiente não percebe que o módulo
   existe — retrocompatível por construção, não por cuidado.

2. O `.env` mora FORA da pasta da skill: `$ILHA_HOME/.env`, default
   `~/.config/ilha-de-edicao/`.

   A ferramenta de referência grava dentro da própria skill, e por isso
   o instalador dele precisa PRESERVAR o arquivo na reinstalação. Gravando
   fora, uma reinstalação que apaga a skill inteira não encosta na chave: o
   problema "preservar o .env" deixa de existir em vez de ser resolvido. Custo:
   uma variável de ambiente a mais.

3. A tabela de recursos SAI DO MANIFESTO, não daqui.

   Duas cópias da mesma tabela são duas verdades, e a que o auditor lê tem que
   ser a mesma que o runtime usa — senão a classe D vira teatro. Se o manifesto
   não for achado (produto instalado sem ele, uso da função solta), vale a
   tabela EMBUTIDA no fim deste arquivo. Ausência é silêncio, não aviso: a
   FRONTEIRA §2 é explícita — um "aviso: manifesto não encontrado" na máquina do
   cliente é vazamento de arquitetura.

4. NUNCA se loga o valor. `--status` mostra somente nome, origem e se a chave
   esta configurada. Nem prefixo nem sufixo do valor entram em stdout.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

# ── a tabela embutida — o fallback do fallback ───────────────────────────────
# Usada só quando o MANIFESTO.json não é achado. Espelha MANIFESTO.chaves.recursos.
RECURSOS_EMBUTIDOS = {
    # 🔴 `fallback: None` é MEDIDO, não esquecimento (SPEC-46, 2026-08-12). Aqui
    # estava escrito "modo local (Whisper local + alinhar.py) — nada bloqueado", e
    # não há Whisper nenhum no pacote: antes da integração com este resolvedor,
    # o `transcribe.sh` parava na variável ausente; `alinhar.py` diz no docstring
    # que NÃO transcreve. Hoje o transcritor consulta este arquivo, mas a ausência
    # da credencial continua sem fallback por definição.
    # Sem a chave, transcrição não acontece — e o `--status` tem que dizer isso.
    "transcricao": {
        "chaves": ["DEEPGRAM_API_KEY"], "no_caminho_critico": True,
        "fallback": None,
        "bloqueia_sem_chave": "transcrição — e com ela o corte por fala, as "
                              "legendas e o QC de emendas por ASR",
        "custo": "~US$0,005/min", "spec": "SPEC-04"},
    "qc-emendas-asr": {
        "chaves": ["DEEPGRAM_API_KEY"], "no_caminho_critico": False,
        "fallback": "o QC roda sem ele; qc-fonemas.py (que não usa API) continua "
                    "obrigatório",
        "custo": "~US$0,005/min de áudio", "spec": "SPEC-12"},
    "insert-gerado": {
        "chaves": ["GEMINI_API_KEY"], "no_caminho_critico": False,
        "fallback": None, "opcional_anunciado": True,
        "custo": "~US$0,10/s de vídeo gerado", "spec": "SPEC-22"},
    "broll": {
        "chaves": ["PEXELS_API_KEY", "PIXABAY_API_KEY"], "no_caminho_critico": False,
        "fallback": "Mixkit funciona sem chave nenhuma", "custo": "grátis",
        "spec": "SPEC-29"},
    "trilha": {
        "chaves": ["GEMINI_API_KEY"], "no_caminho_critico": False,
        "fallback": "sem trilha — e o QC de áudio já roda na versão sem música "
                    "por decisão da SPEC-20",
        "custo": "Lyria 3, por peça", "spec": "SPEC-20", "opcional_anunciado": True},
    "download-url": {
        "chaves": [], "no_caminho_critico": False,
        "fallback": "não precisa de chave; post que exige login precisa de "
                    "BENCH_COOKIES",
        "custo": "grátis", "spec": "—"},
}

ONDE_OBTER = {
    "DEEPGRAM_API_KEY": "console.deepgram.com (crédito inicial grátis)",
    "GEMINI_API_KEY": "aistudio.google.com/apikey",
    "PEXELS_API_KEY": "pexels.com/api (grátis, sem cartão)",
    "PIXABAY_API_KEY": "pixabay.com/api/docs (grátis, sem cartão)",
}


# ═════════════════════════════════════════════════════════════════════ caminhos
def ilha_home() -> str:
    """Onde o dado do USUÁRIO mora. Nunca dentro da instalação."""
    v = os.environ.get("ILHA_HOME")
    if v:
        return os.path.expanduser(v)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "ilha-de-edicao")


def caminho_env() -> str:
    return os.path.join(ilha_home(), ".env")


def _achar_manifesto() -> str | None:
    d = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(d, "MANIFESTO.json")
    return cand if os.path.isfile(cand) else None


def _carregar_recursos() -> dict:
    m = _achar_manifesto()
    if not m:
        return dict(RECURSOS_EMBUTIDOS)
    try:
        with open(m, encoding="utf-8") as fh:
            d = json.load(fh)
        rec = (d.get("chaves") or {}).get("recursos")
        if isinstance(rec, dict) and rec:
            return {k: v for k, v in rec.items() if not k.startswith("_")}
    except (OSError, ValueError):
        pass
    return dict(RECURSOS_EMBUTIDOS)


RECURSOS = _carregar_recursos()


# ═════════════════════════════════════════════════════════════════════ o .env
def _ler_env() -> dict:
    """`KEY=valor` por linha, `#` comenta. Erro de leitura é silêncio."""
    p = caminho_env()
    fora = {}
    try:
        with open(p, encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                k, _, v = linha.partition("=")
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                fora[k.strip()] = v
    except OSError:
        pass
    return fora


def resolver_com_origem(nome: str, *, recurso: str | None = None) \
        -> tuple[str | None, str]:
    """Resolve sem ambiguidade e nomeia a origem sem expor o valor."""
    v = os.environ.get(nome)
    if v:
        return v, "env"
    v = _ler_env().get(nome) or None
    if v:
        return v, "arquivo_local_autorizado"
    return None, "ausente"


def resolver(nome: str, *, recurso: str | None = None) -> str | None:
    """env -> $ILHA_HOME/.env -> None. Nesta ordem, sempre."""
    return resolver_com_origem(nome, recurso=recurso)[0]


def gravar(nome: str, valor: str) -> None:
    """Escreve no .env com modo 600. Não devolve nem imprime o valor."""
    d = ilha_home()
    os.makedirs(d, exist_ok=True)
    p = caminho_env()
    atual = _ler_env()
    atual[nome] = valor
    # Escrita atômica: um .env truncado por interrupção custaria a chave do
    # usuário, e ele não tem de onde tirá-la de volta.
    tmp = p + ".novo"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("# ilha-de-edicao — credenciais. Modo 600. Não versione.\n")
        for k in sorted(atual):
            fh.write("%s=%s\n" % (k, atual[k]))
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, p)
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


# ═══════════════════════════════════════════════════════════════════ consultas
def _rec(recurso: str) -> dict:
    r = RECURSOS.get(recurso)
    if r is None:
        raise KeyError("recurso desconhecido: %r (conhecidos: %s)"
                       % (recurso, ", ".join(sorted(RECURSOS))))
    return r


def faltando(recurso: str) -> list[str]:
    return [c for c in _rec(recurso).get("chaves", []) if not resolver(c)]


def fallback(recurso: str) -> str | None:
    return _rec(recurso).get("fallback")


def disponivel(recurso: str) -> bool:
    """O recurso roda hoje? Roda se tem as chaves OU se tem fallback."""
    return not faltando(recurso) or fallback(recurso) is not None


def contrato_cloud(nomes=None) -> dict:
    """Contrato minimo para um orquestrador cloud, sem valor nem caminho local.

    O consumidor recebe apenas o nome da credencial, a origem declarada e
    booleanos. Nao recebe sufixo, hash, tamanho, caminho do ``.env`` ou qualquer
    material que ajude a reconstruir ou identificar o valor.
    """
    if nomes is None:
        nomes = sorted({c for r in RECURSOS.values() for c in r.get("chaves", [])})
    credenciais = []
    for nome in nomes:
        valor, origem = resolver_com_origem(nome)
        credenciais.append({
            "nome": str(nome),
            "configurada": bool(valor),
            "origem": origem,
            "via_ambiente": origem == "env",
            "via_arquivo_local": origem == "arquivo_local_autorizado",
        })
    return {"schema": "ilha.segredos-cloud/v1", "credenciais": credenciais}


def _raiz_do_pacote() -> Path:
    manifesto = _achar_manifesto()
    if manifesto:
        return Path(manifesto).resolve().parents[2]
    return Path(__file__).resolve().parents[2]


def _arquivos_nos_alvos(alvos):
    """Arquivos regulares, sem seguir symlink para fora do escopo declarado."""
    vistos = set()
    for bruto in alvos:
        alvo = Path(bruto).expanduser().absolute()
        if alvo.is_symlink():
            continue
        if alvo.is_file():
            chave = str(alvo)
            if chave not in vistos:
                vistos.add(chave)
                yield alvo
            continue
        if not alvo.is_dir():
            continue
        for base, dirs, arquivos in os.walk(alvo, followlinks=False):
            dirs[:] = sorted(d for d in dirs
                             if not (Path(base) / d).is_symlink())
            for nome in sorted(arquivos):
                p = Path(base) / nome
                if p.is_symlink() or not p.is_file():
                    continue
                chave = str(p.absolute())
                if chave in vistos:
                    continue
                vistos.add(chave)
                yield p


def _contem_segredo(fh, agulha: bytes) -> tuple[bool, int]:
    """Busca streaming, incluindo ocorrencia que cruza a borda de dois blocos."""
    cauda = b""
    lidos = 0
    sobreposicao = max(0, len(agulha) - 1)
    while True:
        bloco = fh.read(1 << 16)
        if not bloco:
            return False, lidos
        lidos += len(bloco)
        junto = cauda + bloco
        if agulha in junto:
            return True, lidos
        cauda = junto[-sobreposicao:] if sobreposicao else b""


def _rotulo_seguro(rotulo, valor: str) -> str:
    """Nem um nome de arquivo malicioso pode fazer o scanner logar o valor."""
    return str(rotulo).replace(valor, "[SEGREDO]")


def escanear_segredo(nome: str, alvos=None) -> dict:
    """Procura o valor resolvido em repo, logs e artefatos sem imprimi-lo.

    ZIPs sao inspecionados por dentro, pois buscar apenas os bytes comprimidos
    daria verde mesmo com uma chave literal em log/documento empacotado.
    """
    valor, origem = resolver_com_origem(nome)
    if not valor:
        return {
            "schema": "ilha.segredos-scan/v1", "nome": nome,
            "resolvida": False, "origem": origem, "executado": False,
            "ok": False, "arquivos_varridos": 0, "bytes_lidos": 0,
            "ocorrencias": [], "erros": 0,
        }
    agulha = valor.encode("utf-8")
    alvos = list(alvos or [_raiz_do_pacote()])
    ocorrencias = []
    n_arquivos = bytes_lidos = erros = 0
    for caminho in _arquivos_nos_alvos(alvos):
        n_arquivos += 1
        rotulo_caminho = _rotulo_seguro(caminho, valor)
        if valor in str(caminho):
            ocorrencias.append(rotulo_caminho + " [nome]")
        try:
            with caminho.open("rb") as fh:
                achou, n = _contem_segredo(fh, agulha)
            bytes_lidos += n
            if achou:
                ocorrencias.append(rotulo_caminho + " [conteudo]")
        except OSError:
            erros += 1
            continue
        if caminho.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(caminho) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    n_arquivos += 1
                    rotulo = "%s!%s" % (caminho, info.filename)
                    rotulo_seguro = _rotulo_seguro(rotulo, valor)
                    if valor in info.filename:
                        ocorrencias.append(rotulo_seguro + " [nome]")
                    try:
                        with zf.open(info) as fh:
                            achou, n = _contem_segredo(fh, agulha)
                        bytes_lidos += n
                        if achou:
                            ocorrencias.append(rotulo_seguro + " [conteudo]")
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        erros += 1
        except (OSError, zipfile.BadZipFile):
            erros += 1
    return {
        "schema": "ilha.segredos-scan/v1", "nome": nome,
        "resolvida": True, "origem": origem, "executado": True,
        "ok": not ocorrencias and not erros,
        "arquivos_varridos": n_arquivos, "bytes_lidos": bytes_lidos,
        "ocorrencias": ocorrencias, "erros": erros,
    }


def instrucoes(nome: str, recurso: str | None = None) -> str:
    """O texto que o agente diz ao usuário. Três coisas: o que trava, quanto
    custa, onde se obtém. Nunca pede 'por precaução' — só quando o recurso é
    efetivamente acionado, que é o ponto inteiro do lazy."""
    alvos = [r for r in RECURSOS if nome in RECURSOS[r].get("chaves", [])]
    if recurso and recurso in RECURSOS:
        alvos = [recurso]
    linhas = ["A chave `%s` não está configurada." % nome]
    for r in alvos:
        fb = fallback(r)
        if fb:
            sem_ela = fb
        elif RECURSOS[r].get("no_caminho_critico"):
            sem_ela = "BLOQUEADO — %s" % (RECURSOS[r].get("bloqueia_sem_chave")
                                          or "o caminho bruto → entregue não fecha")
        else:
            sem_ela = "recurso indisponível"
        linhas.append("  · %s — sem ela: %s" % (r, sem_ela))
        custo = RECURSOS[r].get("custo")
        if custo and custo != "grátis":
            linhas.append("    custo com ela: %s" % custo)
    onde = ONDE_OBTER.get(nome)
    if onde:
        linhas.append("Onde obter: %s" % onde)
    linhas.append("Para configurar com entrada oculta (fica em %s, modo 600, "
                  "fora da pasta da skill):" % caminho_env())
    linhas.append("  python3 tools/pacote/chaves.py --pedir %s" % nome)
    return "\n".join(linhas)


# Compatibilidade para consumidores que importavam a função antes de o comando
# `--pedir` passar a pedir de verdade. A biblioteca continua devolvendo somente a
# instrução; a CLI é que faz a entrada oculta e a gravação.
pedir = instrucoes


def _chaves_declaradas() -> set[str]:
    return {nome for recurso in RECURSOS.values()
            for nome in recurso.get("chaves", [])}


def pedir_e_gravar(nome: str, *, entrada=None, saida=sys.stdout,
                   erros=sys.stderr) -> int:
    """Solicita uma chave sem eco e grava no arquivo canônico.

    `entrada` é injetável para o teste de regressão. Em uso real o valor vem
    de `getpass`, portanto não aparece no terminal, no histórico nem na saída.
    """
    if nome not in _chaves_declaradas():
        print("erro: credencial desconhecida: %s" % nome, file=erros)
        return 64
    leitor = entrada or (lambda prompt: getpass.getpass(prompt))
    try:
        valor = leitor("%s (entrada oculta): " % nome)
    except (EOFError, KeyboardInterrupt):
        print("\nconfiguração cancelada; nada foi gravado.", file=erros)
        return 1
    if not valor or not valor.strip():
        print("erro: a chave vazia não foi gravada.", file=erros)
        return 64
    gravar(nome, valor.strip())
    print("%s configurada em %s (modo 600)." % (nome, caminho_env()),
          file=saida)
    return 0


def executar_com(nome: str, comando: list[str], *, erros=sys.stderr) -> int:
    """Executa sem imprimir a credencial e sem exportá-la no shell chamador.

    O `exec` substitui este processo. A chave existe somente no ambiente do
    consumidor e dos filhos dele; nenhum valor atravessa stdout ou argumento de
    linha de comando.
    """
    if nome not in _chaves_declaradas():
        print("erro: credencial desconhecida: %s" % nome, file=erros)
        return 64
    comando = list(comando or [])
    if comando and comando[0] == "--":
        comando = comando[1:]
    if not comando:
        print("erro: --executar-com exige um comando depois de `--`.", file=erros)
        return 64
    valor = resolver(nome)
    if not valor:
        print(instrucoes(nome), file=erros)
        return 1
    ambiente = dict(os.environ)
    ambiente[nome] = valor
    try:
        os.execvpe(comando[0], comando, ambiente)
    except OSError as exc:
        print("erro: não foi possível executar %s: %s"
              % (comando[0], exc.strerror or exc), file=erros)
        return 126


# ═══════════════════════════════════════════════════════════════════════ CLI
# O mínimo que o README e a `instalacao.md` pedem. Um número só, num lugar só.
PYTHON_MINIMO = (3, 11)


def linha_do_python():
    """(texto, abaixo_do_minimo) — a versão que ESTÁ rodando, contra o que pedimos.

    🔴 H47-13 (A-18 do teste de campo, 2026-08-12): o README pede Python 3.11+, o
    ambiente do outro Mac resolveu `python3` para o 3.9.6 do sistema, TUDO rodou —
    e nada verificou. O risco não é teórico: no dia em que um script usar sintaxe
    de 3.10+ (um `match`, um `X | Y` em anotação avaliada), o erro aparece no meio
    do pipeline, na produção de alguém, e não na conferência de instalação. O
    `--status` é a conferência de instalação; é aqui que a versão se declara.

    Não é fatal: 3.9.6 rodou o pipeline inteiro. É AVISO nomeado — mentir sobre o
    requisito nas duas direções (reprovar quem funciona, ou calar sobre quem está
    fora do declarado) é pior que dizer o que se mediu.
    """
    v = sys.version_info
    atual = "%d.%d.%d" % (v.major, v.minor, v.micro)
    abaixo = (v.major, v.minor) < PYTHON_MINIMO
    txt = "python3:   %s  (%s)  ·  %s" % (
        atual, sys.executable,
        ("⚠️ ABAIXO do mínimo declarado %d.%d — rodou até hoje, mas sintaxe de "
         "%d.%d+ em qualquer script quebra no meio do pipeline, não aqui"
         % (PYTHON_MINIMO[0], PYTHON_MINIMO[1], PYTHON_MINIMO[0], PYTHON_MINIMO[1]))
        if abaixo else "≥ %d.%d, o mínimo declarado" % PYTHON_MINIMO)
    return txt, abaixo


def status(saida=sys.stdout) -> int:
    linha_py, py_abaixo = linha_do_python()
    print(linha_py, file=saida)
    print("ILHA_HOME: %s" % ilha_home(), file=saida)
    print(".env:      %s%s" % (caminho_env(),
                               "" if os.path.isfile(caminho_env()) else "  (não existe)"),
          file=saida)
    print("recursos:  %d" % len(RECURSOS), file=saida)
    print("", file=saida)
    indisponiveis = 0
    for nome in sorted(RECURSOS):
        falta = faltando(nome)
        if not falta:
            tem = RECURSOS[nome].get("chaves") or []
            marcas = []
            for c in tem:
                _valor, origem = resolver_com_origem(c)
                marcas.append("%s=configurada (%s)" % (c, origem))
            detalhe = "ok" + (" — " + ", ".join(marcas) if marcas else " — não pede chave")
        else:
            fb = fallback(nome)
            if fb is None:
                if RECURSOS[nome].get("no_caminho_critico"):
                    detalhe = "🔴 BLOQUEADO (falta %s) — sem fallback: %s" % (
                        ", ".join(falta),
                        RECURSOS[nome].get("bloqueia_sem_chave") or nome)
                else:
                    detalhe = "sem chave, indisponível (falta %s)" % ", ".join(falta)
                indisponiveis += 1
            else:
                detalhe = "sem chave, fallback: %s" % fb
        print("  %-16s %s" % (nome, detalhe), file=saida)
    print("", file=saida)
    print("indisponíveis: %d de %d" % (indisponiveis, len(RECURSOS)), file=saida)

    # 🔴 O VEREDITO DESCREVE A INSTALAÇÃO, não a tabela (SPEC-46, 2026-08-12).
    # Antes ele lia só `no_caminho_critico && fallback is None` — uma propriedade
    # do MANIFESTO — e por isso dizia "✅ nenhuma etapa do caminho bruto →
    # entregue depende de chave sem fallback" onde a transcrição
    # estava parada por falta de chave. `--status` é diagnóstico de instalação:
    # ele responde "o que roda AQUI, agora", e o que decide isso é a chave estar
    # ou não resolvida. A propriedade da tabela quem audita é a classe D do
    # `auditar-acoplamento.py`.
    bloqueados = [n for n, r in RECURSOS.items()
                  if r.get("no_caminho_critico") and r.get("fallback") is None
                  and faltando(n)]
    if bloqueados:
        for n in sorted(bloqueados):
            print("🔴 %s está BLOQUEADO nesta instalação: falta %s, e não há "
                  "fallback. Sem isso, %s." % (
                      n, ", ".join(faltando(n)),
                      RECURSOS[n].get("bloqueia_sem_chave")
                      or "o caminho bruto → entregue não fecha"), file=saida)
        print("   Para configurar:  python3 chaves.py --pedir %s"
              % faltando(bloqueados[0])[0], file=saida)
        return 1
    sem_fb = sorted(n for n, r in RECURSOS.items()
                    if r.get("no_caminho_critico") and r.get("fallback") is None)
    if sem_fb:
        print("✅ o caminho bruto → entregue está fechado com as chaves "
              "que estão resolvidas aqui (⚠️ %s depende de chave e não tem "
              "fallback: perder a chave PARA a transcrição)."
              % ", ".join(sem_fb), file=saida)
    else:
        print("✅ nenhuma etapa do caminho bruto → entregue depende de chave sem "
              "fallback.", file=saida)
    if py_abaixo:
        # exit 0: a versão baixa não bloqueia nada HOJE (medido — 3.9.6 rodou o
        # pipeline inteiro). O aviso é o produto; transformá-lo em recusa
        # reprovaria uma instalação que funciona.
        print("⚠️ e o Python desta instalação está abaixo do mínimo declarado "
              "(%d.%d): veja a primeira linha." % PYTHON_MINIMO, file=saida)
    return 0


def raiz_resolvida(saida=sys.stdout) -> int:
    """Onde a ilha acha que está — o teste que separa "instalado" de "instalado
    no lugar certo".

    🔴 Este diagnóstico existia e estava do lado ERRADO da fronteira (achado A2):
    a `instalacao.md` mandava o cliente rodar `auditar-acoplamento.py`, que é a
    régua com que NÓS cortamos o produto e não vem no pacote por decisão
    registrada. O comando falhava com "No such file", e quem instalou concluía
    que instalou errado. A pergunta é legítima; ela só precisava morar num
    script que embarca."""
    m = _achar_manifesto()
    if not m:
        print("🔴 não achei o MANIFESTO.json ao lado de %s.\n"
              "   Nenhum script da ilha vai achar os dados dele também: a "
              "instalação está incompleta ou fora do lugar."
              % os.path.dirname(os.path.abspath(__file__)), file=saida)
        return 1
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(m))))
    print("raiz:      %s" % raiz, file=saida)
    print("manifesto: %s" % m, file=saida)
    print("ILHA_HOME: %s%s" % (ilha_home(),
                               "" if os.path.isdir(ilha_home()) else "  (não existe)"),
          file=saida)
    print("✅ a resolução de raiz está funcionando.", file=saida)
    return 0


def ativos(saida=sys.stdout) -> int:
    """Os arquivos que SÃO produto e NÃO estão no git — conferidos por sha256.

    `ausentes` > 0 é esperado num clone novo (SFX, binários de plataforma).
    `divergentes` > 0 não é: o arquivo no disco não é o que o manifesto declara,
    e os dois sha aparecem lado a lado."""
    m = _achar_manifesto()
    if not m:
        print("sem MANIFESTO.json: não há inventário de ativos a conferir", file=saida)
        return 1
    with open(m, encoding="utf-8") as fh:
        decl = json.load(fh).get("ativos") or {}
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(m))))
    ok = ausentes = divergentes = 0
    linhas = []
    for grupo, bloco in decl.items():
        if grupo.startswith("_") or not isinstance(bloco, dict):
            continue
        destino = (bloco.get("destino") or "").strip("/")
        for info in (bloco.get("arquivos") or []):
            if not isinstance(info, dict) or not info.get("sha256"):
                continue
            rel = "%s/%s" % (destino, info.get("nome") or "?") if destino \
                else (info.get("nome") or "?")
            alvo = os.path.join(raiz, rel)
            if not os.path.isfile(alvo):
                ausentes += 1
                linhas.append("   ausente     %s" % rel)
                continue
            h = hashlib.sha256()
            with open(alvo, "rb") as fh:
                for b in iter(lambda: fh.read(1 << 16), b""):
                    h.update(b)
            if h.hexdigest() == info["sha256"]:
                ok += 1
            else:
                divergentes += 1
                linhas.append("   DIVERGENTE  %s\n      declarado %s\n      no disco  %s"
                              % (rel, info["sha256"][:16], h.hexdigest()[:16]))
    print("ativos:    %d conferido(s) · %d ausente(s) · %d divergente(s)"
          % (ok, ausentes, divergentes), file=saida)
    for l in linhas:
        print(l, file=saida)
    if ausentes and not divergentes:
        # ⚠️ a frase caducou em 2026-08-11: a mídia genérica do produto PASSOU a
        # ser versionada (39 previews, 2 clipes sintéticos, 7 dos 9 SFX). O que
        # continua fora do git é o binário de plataforma e os 2 SFX de licença
        # não conferida — e é só isso que "ausente" significa hoje.
        print("   (ausente é esperado num clone novo: binário de plataforma e os "
              "2 SFX de licença não conferida ficam fora do git; a mídia do "
              "produto vem no clone desde 2026-08-11)", file=saida)
    return 1 if divergentes else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="resolução de credencial (SPEC-22 §3.4)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pedir", metavar="CHAVE")
    ap.add_argument("--executar-com", metavar="CHAVE",
                    help="injeta a chave resolvida somente no comando filho")
    ap.add_argument("--raiz", action="store_true",
                    help="onde a ilha acha que está (diagnóstico de instalação)")
    ap.add_argument("--ativos", action="store_true",
                    help="os ativos declarados no MANIFESTO, conferidos por sha256")
    ap.add_argument("--contrato-cloud", action="store_true",
                    help="JSON mascarado da credencial Deepgram para o orquestrador")
    ap.add_argument("--scan-segredos", action="store_true",
                    help="busca o valor Deepgram resolvido sem imprimi-lo")
    ap.add_argument("--scan-dir", action="append", default=[], metavar="CAMINHO",
                    help="repo/log/artefato a varrer; repetivel (default: raiz do pacote)")
    ap.add_argument("comando", nargs=argparse.REMAINDER,
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.pedir:
        return pedir_e_gravar(args.pedir)
    if args.executar_com:
        return executar_com(args.executar_com, args.comando)
    if args.raiz:
        return raiz_resolvida()
    if args.ativos:
        return ativos()
    if args.contrato_cloud:
        print(json.dumps(contrato_cloud(["DEEPGRAM_API_KEY"]),
                         ensure_ascii=False, sort_keys=True))
        return 0
    if args.scan_segredos:
        resultado = escanear_segredo(
            "DEEPGRAM_API_KEY", args.scan_dir or [_raiz_do_pacote()])
        print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
        if not resultado["executado"]:
            return 2
        return 0 if resultado["ok"] else 1
    return status()


if __name__ == "__main__":
    sys.exit(main())
