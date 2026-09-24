---
name: broll-source
description: Encontra, baixa e cataloga b-roll com licença livre para uso comercial — Mixkit (funciona sem chave nenhuma), Pexels e Pixabay (chave grátis), Wikimedia — e mantém uma biblioteca local com a licença de cada clipe registrada. Use quando um beat do roteiro pedir imagem de apoio, quando o plano de edição previr split-screen/cutaway, ou quando o creator-1 disser "acha um vídeo de X". Alimenta o split-broll.py da skill edit-video; quando não existe footage do que se precisa, o caminho é gerar com omni-insert.
---

# broll-source

**O gargalo que esta peça resolve**: a máquina já sabe INSERIR b-roll (split-screen com feather,
cutaway, PiP) — o que faltava era **ter o que inserir**. Sem isso, todo plano que pede imagem de
apoio trava. (Diagnosticado na modelagem do ref-D: o único item da receita que a gente
não conseguiu replicar com material próprio foi justamente o b-roll.)

## Regra dura, antes de tudo

**Só material CC0 ou com licença livre para uso COMERCIAL.** Baixar b-roll de vídeo viral
alheio é violação de direito autoral — não importa que "todo mundo faz". Todo clipe entra na
biblioteca com `licenca`, `autor` e `pagina` registrados: **licença sem procedência é licença
que ninguém consegue provar depois**. Se um clipe exigir atribuição, o crédito TEM que entrar
na legenda do post — prefira fontes que não exigem.

## Vídeo ou FOTO? A escada muda

Um beat que pede **referente único** — "o Cristo Redentor", "o Neymar", "a capa daquele
livro" — não tem resposta em stock: pessoa pública e monumento identificável não são
material de banco de imagem comercial. Para esses, o caminho é `--tipo imagem`, e a
ordem se **inverte**: Wikimedia Commons primeiro (sem chave), Pexels fotos depois.

```bash
python3 scripts/buscar.py "Cristo Redentor" --tipo imagem --n 6 > /tmp/cands.json
python3 scripts/baixar.py --json /tmp/cands.json --i 0 --tags "rio,monumento" --nome cristo
python3 scripts/imagem-clipe.py <BROLL_DIR>/imagens/cristo.jpg /tmp/kb.mp4 \
        --dur 4 --movimento zoom-in --perfil reels     # a foto vira plano inserível
python3 scripts/baixar.py --creditos                   # a linha de crédito, pronta pra colar
```

Três coisas que só a imagem exige, e que estão medidas em **`references/imagem.md`**:

- **crédito é regra, não exceção** — ~78% das fotos aprovadas exigem atribuição, contra
  0 dos clipes de vídeo hoje na biblioteca. Daí o `--creditos`.
- **`CC BY-SA` é a licença majoritária do Commons** e esta skill **reprova** SA (viral: a
  obra derivada herda a licença). O gate vive em `scripts/licenca.py`, com autoteste.
- **marca e pessoa** ficam muito mais fáceis de pisar em foto do que em vídeo. O
  `buscar.py --tipo imagem` imprime a advertência no stderr toda vez, de propósito.

## Ordem de tentativa

*(vídeo. Para imagem, ver acima e `references/imagem.md`.)*

0. **Biblioteca local** — `baixar.py --listar [--tag X]`. Nunca rebaixe o que já existe.
1. **Pexels** — ⭐ **primário. A chave já está configurada** (`PEXELS_API_KEY` no env dos
   settings, desde 2026-07-25; limite medido: 25.000 req/mês). Melhor acervo, filtro de
   orientação server-side, e **verticais 4K nativos** (2160×3840) — que dão folga total pro
   recorte do split sem perder resolução.
2. **Mixkit** — sem chave nenhuma, stock polido (braço gratuito da Envato), verticais
   1080×1920. Plano B se a chave falhar ou o acervo do Pexels não tiver o plano.
   ⚠️ `/discover/<tag>/` é **taxonomia, não busca livre**: tag inexistente devolve HTTP 200
   com página vazia (`drive-thru` → 0; `food` → 24). Use UMA palavra concreta.
3. **Pixabay** — secundário; acervo de vídeo menor e quase todo landscape.
4. **Wikimedia Commons** — sem chave, mas acervo documental/amador (timecode queimado, câmera
   na mão). Plano C real, não plano B.
5. **Gerar** — skill `omni-insert` (`gen`). Funciona sem cadastro (já temos `GEMINI_API_KEY`),
   ~US$0,8 por 8s. É o caminho quando **não existe** footage do que se precisa (metáfora,
   conceito, cenário específico) — não quando é só preguiça de procurar.

⚠️ **Openverse não tem vídeo** (só imagem e áudio), **Videvo morreu** (absorvido pela Freepik)
e a licença do **Coverr é ambígua** (a doc da API proíbe uso comercial, a página de licença
permite) — licença ambígua é licença reprovada. Detalhes e testes em `references/fontes.md`.

## ⚠️ Três armadilhas de licença que já pegariam a gente

0. 🔴 **O nosso próprio gate do Wikimedia vazava** — e a lição é maior que o bug. O
   filtro era `any(t in lic.lower() for t in ("cc0","public domain","cc by"))` com um
   comentário ao lado prometendo cortar `CC BY-SA` e `CC BY-NC`. **`"cc by-sa 4.0"`
   contém `"cc by"`**: medido contra a API real, **24 de 24 candidatos passavam, 13
   deles `CC BY-SA`**. Teste de família por substring decide antes do teste de
   cláusula, e o comentário afirmava o contrário do código. O conserto (tokenizar, e
   testar cláusula ANTES de família) está em `scripts/licenca.py`, com autoteste e
   controle negativo. Nenhum clipe já baixado veio do Wikimedia — foi sorte, e a sorte
   acabaria no dia em que alguém rodasse `--provedores wikimedia`.
1. **Mixkit mistura duas licenças no mesmo acervo.** A *Free License* libera comercial; a
   *Restricted License* é **uso pessoal apenas** e proíbe explicitamente "Commercial Projects,
   Advertising, Company Social Media posts, YouTube videos". Os dois aparecem lado a lado na
   busca e os dois dizem "Free Download" — a diferença só existe no HTML do item. O `buscar.py`
   faz esse gate item a item (`"copyrightNotice":"Free"`) e descarta o resto. **Não remova esse
   gate pra economizar request.**
2. **Marca registrada em b-roll.** Footage com logo/marca reconhecível não pode ser usada
   comercialmente em relação a bens e serviços (regra explícita do Pixabay, e bom senso jurídico
   em qualquer fonte). Na prática: pro beat "o McDonald's vende mais porque é o mais conhecido",
   use **hambúrguer genérico**, não fachada do McDonald's. O beat funciona igual e o risco some.

## Fluxo

```bash
# 0. o que já tenho?
python3 scripts/baixar.py --listar --tag fast-food

# 1. buscar (gera folha de contato com as miniaturas)
python3 scripts/buscar.py "fast food restaurant exterior" --n 12 --dur-max 20 > /tmp/cands.json
#    → tools/broll-library/busca-<slug>/contato.png

# 2. ⭐ OLHAR a folha de contato (Read na imagem) e escolher pelo índice.
#    A escolha é editorial e é minha; o script só traz opções com a licença carimbada.

# 3. baixar e catalogar
python3 scripts/baixar.py --json /tmp/cands.json --i 4 --tags "fast-food,fachada" --nome mc-fachada

# 4. inserir (skill edit-video)
python3 ../edit-video/scripts/split-broll.py v1-montado.mp4 \
    "$BROLL_DIR/clips/mc-fachada.mp4" 5.17 13.27 v2-split.mp4 --broll-foco centro
```

## Como escolher o termo de busca

O termo sai do **beat**, não da fala literal. "O McDonald's é uma das maiores provas disso"
→ o que a imagem precisa entregar é *marca gigante e onipresente*, não "McDonald's" literal
(e marca registrada em b-roll de stock quase não existe, por razões óbvias). Bons termos são
**concretos e visuais**: `fast food restaurant exterior`, `drive thru night`, `crowded street food`.
Termos abstratos (`sucesso`, `marketing`) devolvem stock genérico de reunião de escritório — o
tipo de imagem que faz o vídeo parecer anúncio de banco.

Regra prática: se você não consegue descrever o PLANO (o que a câmera vê), o termo está abstrato demais.

## O que o clipe precisa ter

- **Duração ≥ a janela ENCAIXADA** onde vai entrar — não a que você pediu. O `split-plano.py`
  move `t0`/`t1` para a fronteira de segmento do timeline real, e a janela encaixada pode ser
  maior que a pedida: no estudo `modelagem-ref-D`, pedir `5,20–13,20` devolve `5,1667–13,2667`,
  ou seja **100 ms a mais**. Confira em `jq '.janela' split-plano.json` antes de escolher o clipe
  (o `split-broll.py` não faz loop; se o b-roll acabar antes, o overlay some no meio).
- **Movimento suave e sem corte interno** — b-roll com corte próprio briga com o corte da montagem.
- **Sem texto queimado** (timecode, marca d'água, legenda em outro idioma).
- **Landscape serve**: o `split-broll.py` só precisa cobrir até o fim da máscara (~51% da altura),
  então um 16:9 entra com ~1,6× de recorte, não 3,2×. Vertical é melhor, mas não é requisito.
- ⭐ **Prefira PLANO ABERTO.** Em split-screen o clipe perde ~metade da altura no recorte —
  um close vira macro irreconhecível. Medido na primeira montagem real: um top-down de
  hambúrguer (ótimo em tela cheia) virou "pão gigante" ocupando a faixa inteira, enquanto a
  referência usava um plano geral de fachada com contexto. Na folha de contato, **descarte close-up
  por padrão** e use `--broll-foco cima|centro|baixo` pra escolher que parte do plano sobrevive.

## Biblioteca

Onde ela mora é `$BROLL_DIR` — os três scripts leem essa variável e, sem ela,
caem no `tools/broll-library/` ao lado da instalação. É por isso que os exemplos
deste arquivo escrevem `"$BROLL_DIR/clips/…"` em vez de um caminho fixo: o clipe
que você baixou não está onde o meu estava.

`tools/broll-library/` — `clips/*.mp4` normalizados (fps do perfil de peça, sem áudio,
bt709), `imagens/<nome>.{jpg,png,webp}` **sem re-encode** e `INDEX.json` com procedência e
licença de cada item. Os clipes **não são recortados na hora de guardar**: quem enquadra é
o `split-broll.py`, que sabe qual faixa do frame precisa cobrir. Guardar inteiro deixa reusar
o mesmo clipe em outro enquadramento depois.

O índice é `benchmark.broll-index/v2` e é retrocompatível: entrada sem `tipo` é `video`,
sem `mime` deriva da extensão, sem `licenca_slug` é classificada na leitura (e **não** é
regravada — nada de migração silenciosa de arquivo já entregue). `dur` admite `null`:
imagem não tem duração, e gravar o `0.04` que o `ffprobe` devolve numa JPEG seria um
índice que **mente**, pior que um índice incompleto.

🔴 **HTTP 200 não quer dizer mídia.** Todo download passa por validação de bytes: o
primeiro bloco é inspecionado (`<!doctype`/`<html`/`<?xml` → aborta) e imagem ainda passa
por magic number. O parcial nunca sobrevive a uma falha. Antes disso, um HTML de erro de
54 bytes virava `.download` órfão no `clips/` e o operador lia "arquivo corrompido"
quando a causa era "o servidor devolveu uma página".

## Referências

- **Imagem estática** (escada, gate de licença, crédito, Ken Burns): **`references/imagem.md`**
- Fontes, licenças e chaves (vídeo): **`references/fontes.md`**
- Onde o b-roll é inserido: `split-broll.py` da skill `edit-video`
- Quando gerar em vez de buscar: skill `omni-insert`
- Por que o b-roll importa na montagem (ele também ESCONDE jump cut): `intelligence/edicao/ref-D.md`
