# Avisos de terceiros

Este arquivo lista **todo arquivo do produto que contém código de terceiro
portado**, com origem, licença e as linhas afetadas.

## Estado hoje: **1 arquivo portado**, medido

| arquivo do produto | origem | licença | linhas |
|---|---|---|---|
| `.claude/skills/edit-video/scripts/detect-cor.py` | projeto de terceiro, MIT | MIT — cópia integral em `LICENSES/edvid-MIT.txt` | 43 de 1.045, medidas |

O cabeçalho de 3 linhas está no topo do arquivo, como o Portão 6 exige, e o nome
do titular do copyright aparece em exatamente três lugares: ali, aqui e em
`LICENSES/`. A licença MIT obriga a preservar o aviso; preservá-lo em mais lugares
que esses três seria espalhar nome de terceiro pelo pacote sem necessidade.

⚠️ **Este arquivo dizia "0 arquivos portados" e "nada neste repositório contém
código copiado de terceiro" até 2026-08-11.** Era falso desde que `detect-cor.py`
ganhou o cabeçalho de derivação: o `MANIFESTO.export.portados` o lista, o Portão 6
cobra o cabeçalho dele, e o `ORIGEM.json` de cada release registra
`"atribuicao": "1 portados"`. A doc de atribuição de um produto é o último lugar
onde uma afirmação dessas pode ficar velha — quem a lê está checando conformidade
de licença. Achado na mini-revalidação da onda E.

O resto do repositório continua sendo **mecanismo lido e reimplementado**, que não
gera obrigação legal de atribuição — e mesmo assim tem procedência registrada, por
política, fora deste repositório.

## Quem preenche isto

**O Portão 6 do `exportar-produto.py`** (SPEC-000 §3.10, fase 8). Ele lê
`MANIFESTO.export.portados` e exige, em **todo** arquivo listado ali, o bloco de
atribuição de 3 linhas definido em `SPEC-22:807-811`. Um arquivo em `portados`
sem o cabeçalho, ou um cabeçalho sem a entrada correspondente aqui, reprova o
export.

Ou seja: esta tabela **não se mantém à mão**. Se você portou código de terceiro,
o caminho é declarar o arquivo em `MANIFESTO.export.portados` e pôr o cabeçalho
de atribuição nele — a entrada aqui é consequência, e a ausência dela vira
reprovação de portão, não esquecimento silencioso.

## As licenças completas

Textos integrais de cada licença de terceiro relevante ficam em `LICENSES/`:

| arquivo | o que cobre |
|---|---|
| `LICENSES/edvid-MIT.txt` | `github.com/fillrochaa/edvid` — MIT, `Copyright (c) 2026 Creator Factory`. Cópia integral do `LICENSE` daquele repositório, sha256 `c28ef8cb…52a8f43`. Está aqui **preventivamente**: hoje não há código portado dele, mas ele é a referência lida com mais frequência, e a licença precisa acompanhar no minuto em que a primeira linha for |

⚠️ MIT é permissiva, não copyleft: exige que o aviso de copyright acompanhe as
partes substanciais reaproveitadas, **não** exige que a obra derivada seja MIT.
É o que torna a licença proprietária proposta em `LICENSE` compatível com este
código embarcado (SPEC-000 §3.12, `SPEC-22:813-815`).

## O que NÃO entra aqui

- **Dependências de runtime** (npm, PyPI). Elas não são redistribuídas por nós:
  `node_modules/` está no `.gitignore` e o cliente instala do registro. As
  licenças delas são obrigação do gerenciador de pacotes, não desta tabela.
- **Mecanismo lido sem código copiado.** Não gera obrigação legal. Vai para
  `tools/ref-edvid/PROCEDENCIA.md` e para o teardown, não para cá — misturar as
  duas coisas dilui exatamente a atribuição que este arquivo existe para tornar
  visível.
