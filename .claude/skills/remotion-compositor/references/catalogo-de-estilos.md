# Catálogo de estilos — o processo

> SPEC-15. Este arquivo é o **ritual**: como um estilo entra, onde ele vive, e
> qual é a fronteira entre catálogo e invenção. Sem o ritual o catálogo apodrece
> em duas produções — e já temos quatro proto-catálogos que apodreceram assim.

---

## Por que existe

Um estilo que nasce numa produção não fica disponível para a próxima. Medido no
repo: **53,8% das linhas de `src/`** vivem em arquivo de uma peça só; `Chip` tem
**4** implementações independentes, `passo numerado` tem **5**, `selo` tem **3**.
Um kit inteiro de 423 linhas (`src/peca-11/Kit.tsx`) foi clonado porque **uma cor**
estava cravada em `src/peca-10/Kit.tsx:18`.

E a modelagem, que é o nosso diferencial, vaza pelo mesmo buraco: das 5 fichas de
`intelligence/edicao/`, **três nunca viraram nada** que a próxima produção
pudesse escolher.

**O catálogo não conserta isso refatorando. Ele conserta tornando verificável.**

---

## As três camadas, e a fronteira é o SEGUNDO USO

| camada | onde vive | ritual |
|---|---|---|
| **1. catálogo** | `src/catalogo/estilos.ts` → componente em `MotionKit`/`Mockups`/`CaptionLayer`/… | escolhido por slug + parâmetros; o agente **não escreve TSX** |
| **2. sob medida** | o arquivo da produção (`src/peca-02.tsx` etc.) | livre, **zero burocracia**. É onde a invenção acontece |
| **3. promoção** | do 2 para o 1 | disparada pelo **segundo uso** |

> ### 🔴 Copiar componente de um arquivo de produção para outro é proibido.
> ### Se você ia copiar, é porque é catálogo — promova.

Isso é verificável: uma cópia deixa duas definições do mesmo nome em arquivos
diferentes. O grep que levantou as duplicatas passa a ser o **teste**, não o
inventário.

Duas regras que valem **dentro da camada 2**, porque o repo já pagou por
ignorá-las:

- **Timing é dado, nunca literal.** As janelas vão para `overlays.json`/`edl.json`.
  Timing cravado no TSX é invisível para o preview e o usuário não consegue
  retimar.
- **Cor é `Theme`, nunca literal.** Já é a regra escrita em `src/themes.ts:1-2`, e
  é a que `src/peca-11/Kit.tsx:8` mostra quebrada.

**O que nunca sobe**: componente cujo nome é o beat do roteiro. Teste: *dá para
descrever sem citar o assunto da peça?* `Carimbo` sim. `B6Porta` não. Promover os
~44 `B1Assunto`…`B16Cta` transformaria o catálogo em arquivo morto.

---

## Registrar um estilo novo — 5 passos

1. **O componente tem que ser genérico.** Cor e fonte vêm de `Theme`; nenhum
   número de formato no corpo (o formato vem do perfil de peça, SPEC-00); nenhum
   `staticFile` de asset de produção; nenhum timing literal da peça em que
   nasceu — timing entra por prop.
2. **Uma entrada em `src/catalogo/estilos.ts`**, com `oQuePinta` em UMA frase,
   `parametros` saídos das props REAIS (abra o arquivo; não invente prop) e
   `medido` preenchido se veio de `model-edit`.
3. **`npm run catalogo`** → regenera `catalogo/catalogo.json` e o preview do slug
   novo. É idempotente por hash: reexecutar não custa nada.
4. **Olhe o `.png` do preview** (Read na imagem). É o QC de estado final que a
   `SKILL.md` já exige de todo elemento, aplicado ao card do catálogo.
5. **Se veio de uma modelagem**, a ficha em `intelligence/edicao/<handle>.md`
   ganha a linha `→ catálogo: <slug>`. É o que fecha o loop.

> **Adicionar estilo só numa conversa, para uma produção, é proibido.** O teste
> que acusa é `python3 scripts/gerar-previews.py --check` (exit 1 + o slug).

---

## O objeto `Estilo` — os campos que resolvem problema nosso

| campo | para quê |
|---|---|
| `camada` (`edl`/`pixel`/`alpha`) | **ONDE** o estilo age. Impede alguém de implementar no Remotion um estilo que tem que viver no ffmpeg |
| `estado` + `bloqueio` | um estilo pode ser **conhecido** sem ser **escolhível**. Registrar como `candidato` com o bloqueio nomeado é honesto hoje e vira a lista de trabalho de amanhã. Sem isso a alternativa era mentir (marcar pronto) ou **esconder** — e esconder é o defeito que o catálogo existe para corrigir |
| `duplicatas` | a dívida fica **medida** no catálogo, em vez de num TODO |
| `medido` | procedência: qual peça, qual ficha, que data |
| `defaultDe` | o default é **declarado e validado**, nunca a posição do array |
| `perfis[]` | um estilo que não serve a nenhum perfil de peça não entra |

Os 5 grupos: `gramatica` · `gancho` · `legenda` · `grafismo` · `tema`.
`tema` é separado porque é o eixo que o `peca-11/Kit.tsx:8` provou — **a única
coisa que impediu o reuso de um kit de 423 linhas foi uma cor**. Se a cor é um
estilo escolhível, o kit é reutilizável.

---

## O preview

**Renderizado pelo próprio componente**, no entry point isolado
`src/index-catalogo.tsx`. Fiel por construção e impossível de dessincronizar.

Cinco decisões que você não precisa julgar de novo:

1. **Entry point isolado, sempre.** Um import quebrado em qualquer produção já
   derrubou o render de outra, o `.mov` velho ficou no lugar e a composição ffmpeg
   seguinte rodou "com sucesso" sobre camada gráfica velha. O catálogo importa de
   6 famílias: no bundle global isso multiplica a superfície.
2. **`--scale`, nunca composição menor.** A composição roda no canvas cheio do
   perfil; só o *output* é reduzido. Baixar `width`/`height` quebraria todo
   `fontSize` e toda coordenada de path.
3. **VP9 OPACO.** Nunca `yuva420p`: WebM VP9/VP8 com alpha derruba o canal em
   silêncio no libvpx do Homebrew 8.x, que é o nosso. A placa já está por baixo.
4. **O poster é o `frameCartao` = o estado FINAL desenhado.** Validar no meio da
   animação esconde bug.
5. **A placa é DESENHADA.** `src/catalogo/Placas.tsx` desenha 4 fundos sintéticos.
   🔴 **Nunca material de creator no preview** — nem bruto, nem `public/*.mp4`.
   Um detector que procura "mídia > 1 MB" passa em verde sobre 33 webm de 200 KB
   com o rosto de uma creator dentro.

**Só `estado: "pronto"` ganha preview.** Candidato aparece esmaecido na galeria,
com o `bloqueio` no tooltip, e não é selecionável.

---

## O contrato que a galeria lê

`tools/remotion-compositor/catalogo/catalogo.json` (`benchmark.catalogo-estilos/v1`),
**gerado, nunca editado à mão**. Schema executável em `catalogo/_schema.json`;
`--validar` confere o schema **mais** as 5 regras que JSON Schema não expressa.

A galeria não importa TypeScript e não roda node: ela lê esse um arquivo.
`preview.webm` e `preview.poster` são **relativos a `catalogo/`** — caminho
absoluto invalida o artefato.

---

## CLI

```
python3 scripts/gerar-previews.py             # regenera o que mudou
                        --slug <slug>         # um só
                        --grupo legenda       # um grupo
                        --check               # não renderiza; exit 1 se dessincronizou
                        --validar             # não renderiza; schema + 5 regras
                        --forcar              # ignora o hash
                        --listar              # slug · grupo · estado · sha
```

Caminho do `catalogo.json` no stdout, logs no stderr — como todo script do repo.

⚠️ **O canvas do preview do CATÁLOGO é o da fixture do produto**
(`src/data/perfil.json`). Ele é estável desde 2026-08-10: o `perfil.py resolver`
não o sobrescreve mais — o snapshot da produção passou a morar em
`<dir-producao>/remotion/perfil.json` (achado A6). O canvas entra no `sha` e o
`--check` compara a dimensão do PNG com ele, então o catálogo é determinístico
mesmo com duas produções de formatos diferentes rodando na mesma máquina.

Quem é dirigido pelo formato da PEÇA é a **galeria** (`previews-peca.py`), e ali
o canvas viaja no `inputProps` do render — não em arquivo global.
