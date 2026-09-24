# Sistema de edição de VSL de tráfego pago — decodificado (2026-08-02)

> Engenharia reversa da camada gráfica de 4 VSLs que estavam no ar com verba em
> cima, em quatro temperaturas de público diferentes. Complementa
> `intelligence/edicao/vsl-rede-ref-E.md` (que cobre corte, ritmo e som);
> aqui é **tipografia, overlay e a variação de estilo dentro da peça**.
>
> Preset pronto pra usar: `tools/remotion-compositor/src/vsl/estilos-medidos.ts`

**Corpus e origem de cada número:**

| peça | duração | público | medição por pixel | deep-edit (Gemini) |
|---|---|---|---|---|
| ref-G / ref-G | 25:31 | frio total | ✅ | abertura · corpo · oferta |
| ref-F FCC v2 | 37:54 | frio | ✅ (com ressalva) | abertura · corpo · oferta |
| ref-E home var1 | 7:46 | morno | ✅ | abertura · corpo · oferta |
| Imersão 7D | 6:43 | quente | ✅ | abertura · oferta |

Duas fontes, e elas **não valem para as mesmas perguntas**:

- **`tipografia.py`** (medição de pixel) é a fonte de verdade do **ONDE e do
  QUANTO**: posição, cor exata, largura, cadência, % do tempo na tela.
- **`deep-edit-analysis.py`** (Gemini 2.5 Pro, fps=2) é a fonte de verdade do
  **O QUE e do COMO**: inventário de componentes, animação, regra de
  composição, o que a cor significa.

⚠️ **O Gemini erra posição e cor com confiança alta.** Na home ele reportou
legenda em 85% da altura (medida: 56%) e destaque amarelo `#FFFF00` (medido:
`#F14418`, vermelho — 519 mil pixels vermelhos contra 3 mil amarelos na faixa da
legenda). Nunca aceite número de posição/cor do Gemini sem conferir no pixel.

---

## A tese do estilo: o estilo muda DENTRO da peça

Não existe "a edição da VSL" — existem modos, e a peça troca de modo conforme a
função do bloco. Trechos de 60–90s, medidos por `deep-edit-analysis.py`:

| peça | trecho | elementos /10s | **punch-ins** | maior janela sem elemento | legenda |
|---|---|---|---|---|---|
| **ref-E home** | abertura | 2,52 | 9 | 7,7s | páginas curtas |
| | corpo | 2,17 | 5 | 11,1s | frase inteira |
| | **oferta** | **1,57** | **15** | 15,1s | páginas curtas |
| **ref-F FCC** | abertura | 3,24 | 11 | 3,5s | palavra a palavra |
| | corpo | 2,68 | **2** | 13,3s | **desligada** |
| | **oferta** | **2,11** | **19** | 9,4s | palavra a palavra |
| **ref-G** | abertura | **1,10** | 5 | 14,2s | palavra a palavra |
| | corpo | 1,47 | 13 | 12,1s | palavra a palavra |
| | **oferta** | 1,33 | **20** | **26,5s** | palavra a palavra |
| **Imersão 7D** | abertura | 2,83 | 7 | 3,5s | páginas curtas |
| | **oferta** | **5,89** | **3** | 5,6s | páginas curtas |

### O que sobrevive aos quatro casos: o punch-in escala na oferta

| peça | punch-ins abertura → oferta |
|---|---|
| ref-E home | 9 → **15** |
| ref-F FCC | 11 → **19** |
| ref-G | 5 → **20** (4x) |
| Imersão 7D | 7 → 3 ⟵ **exceção** |

Três operações independentes, três nichos, e o mesmo movimento: **quando chega a
hora de pedir dinheiro, a câmera aproxima.** No ref-G o punch-in
quadruplica. A exceção é a Imersão 7D, e ela é a peça de público quente vendendo
ingresso de evento — o mesmo caso que já invertia a curva de ritmo de corte.

### ⚠️ O que NÃO sobrevive: "a oferta esvazia a tela"

Com os quatro casos medidos, **a densidade de grafismo não tem direção única**:

- cai da abertura pra oferta em **duas** peças (home 2,52 → 1,57; ref-F 3,24 → 2,11);
- **sobe** no ref-G (1,10 → 1,33);
- **dobra** na Imersão 7D (2,83 → **5,89**, o maior número de todo o corpus).

A Imersão 7D é o contra-exemplo forte, e faz sentido: ela vende evento com
cartelas full-screen animadas, e a oferta é justamente onde entram "LOTE 01
R$97" e "DUAS NOITES AO VIVO". **Grafismo na oferta é escolha de peça, não regra
do método.** O que é regra é o punch-in.

### E isso completa a medição de corte

Em `vsl-rede-ref-E.md` está medido que o **plano alonga** no bloco de
oferta (12,4 cortes/min na home contra 21,8 na abertura). Continua certo e não
contradiz o que está acima — são duas coisas diferentes, e juntas fecham o
mecanismo:

> **Corte de plano diminui; movimento dentro do plano aumenta.**
> A oferta troca de enquadramento com menos frequência, mas o quadro nunca fica
> parado: o punch-in faz o trabalho que o corte fazia. Dá aproximação e
> intensidade sem a agitação de trocar de plano.

### O outro achado da tabela: a legenda pode desligar

Na ref-F o modo da legenda muda **para "nenhuma"** no corpo — verificado no
arquivo, em 10:00–10:24 ela roda talking head limpo e depois entra reel de
terceiro em tela cheia. Na home o modo muda de "páginas curtas" para "frase
inteira" e volta. É um parâmetro por bloco, não da peça.

E repare na coluna da direita do ref-G na oferta: **26,5 segundos sem
nenhum elemento gráfico novo**, a maior janela do corpus inteiro. Enquanto isso
ele acumula 20 punch-ins. É a expressão mais pura do "olho no olho": zero
grafismo, câmera aproximando o tempo todo.

---

## Os quatro sistemas de legenda, medidos

| | ref-G | ref-F FCC | ref-E home | Imersão 7D |
|---|---|---|---|---|
| público | frio total | frio | morno | quente |
| **yPct** (centro) | 63% | 59% | 56% | 70% |
| cor base | `#FEFEFE` | **`#EECD3B`** | `#FFFFFF` | `#FEFEFE` |
| destaque | **nenhum** (3,1% = ruído) | nenhum (a legenda toda é amarela) | **`#F14418`** (42,7%) | `#FE5410` (15,6%) |
| itálico | não | **sim** | não | não |
| largura usada | **41,7%** | 76,4% | 64,8% | 63,0% |
| na tela | 91,2% | 83,4% | 79,7% | 89,8% |
| s por página | 1,74 | ~2,5 | 1,82 | 2,03 |

**Três leituras:**

- **Quanto mais frio, menos palavra por página.** O ref-G usa 41,7% da
  largura: 1 a 3 palavras, nunca frase. Ele não quer que você leia, quer que
  você não saia.
- **Legenda branca com destaque não é regra.** Dos quatro, só dois usam palavra
  ativa colorida. O ref-G é branco chapado (`highlight: null`) e a ref-F
  pinta a legenda **inteira** de amarelo em itálico.
- **A posição varia 14 pontos** (56% a 70%) e acompanha o enquadramento: a ref-F
  aparece de corpo inteiro e a legenda sobe; o Imersão 7D é plano médio sentado
  e ela desce.

### A ressalva da ref-F, e por que ela importa

`tipografia.py` **falhou** na primeira passada nela: elegeu o sofá laranja e a
madeira como "texto" (cenário quente e saturado), e depois, no modo `--so-claro`,
elegeu os cards de print brancos. Só acertou quando mirei a cor específica que o
Gemini reportou (`#FFA800`) e restringi a busca à faixa de 55–64%.

**O limite da ferramenta, declarado:** ela é confiável em legenda clara sobre
cenário controlado (3 dos 4 casos, sem intervenção). Em cenário quente com
legenda colorida, use o deep-edit para descobrir a cor e volte pro pixel pra
descobrir a posição. As duas ferramentas se cobrem.

---

## A gramática, contada em 195 elementos

Agregando a `timeline_elementos` dos 11 trechos — cada overlay que entra na tela
vira uma linha:

| dimensão | distribuição medida |
|---|---|
| **tipo** | **texto-sans 133 (68%)** · pip-video 14 · print-screenshot 12 · painel-fundo 10 · cartão 7 · tachado 6 · emoji 4 · texto-serif 4 · foto 2 |
| **entrada** | fade 90 (46%) · pop-overshoot 56 (29%) · scale 15 · corte-seco 15 · slide 9 · type-on 5 · draw-stroke 3 |
| **saída** | fade 124 (64%) · corte-seco 58 (30%) · pop-out 11 |
| **posição** | centro 80 · baixo-centro 54 · topo-centro 40 · **laterais somadas: 21 (11%)** |
| **SFX** | whoosh 78 (40%) · nenhum 42 · pop 38 · click 29 |
| **rotação** | **0° em 191 de 195 (98%)** · ±5° em 4 |

### As três leituras que mais mudam o nosso jeito de editar

**1. VSL é RETA.** 98% dos elementos entram com rotação zero (191 de 195). Isso é o oposto
exato do `sistema-ref-C.md`, onde a regra é *"rotação orgânica: manuscritos
a ±3°, post-its e PiPs a ±5° — nada perfeitamente reto"*. Conteúdo educativo
usa a inclinação pra parecer artesanal e próximo; **VSL de venda usa o
alinhamento pra parecer sóbria e confiável.** Aplicar o preset de rotação do
conteúdo numa VSL é errar o registro.

**2. Tudo mora no eixo central.** Centro + baixo-centro + topo-centro = 89%. As
laterais quase não existem. E o motivo aparece na regra de composição medida:
o corpo e as mãos do apresentador ocupam as laterais o tempo todo, gesticulando.

**3. Não é biblioteca de mockup, é tipografia.** 68% dos elementos são
`texto-sans` puro. O que separa uma VSL bem editada de uma malfeita não é ter
componente exótico — é ter **texto entrando na palavra certa, no lugar certo,
com animação curta**. O exemplo mais bonito do corpus: no bloco de oferta da
home, um "**2**" entra em `meio-dir`, *"ao lado da mão dele que faz o sinal de
2"*, sincronizado com a fala "2 noites", com pop-overshoot e SFX pop, e sai
1,1s depois.

## Inventário de componentes por peça

Consolidando o inventário dos trechos analisados:

| componente | onde aparece | spec medida | já temos? |
|---|---|---|---|
| `legenda-karaoke` | as 4 | ver tabela acima | ✅ `CaptionLayer` |
| `titulo-destaque-caps` | as 4 | caixa alta, cor de marca, pop-overshoot | ✅ `AccentWord` / `StepTitle` |
| `dado-impacto-central` | peça B, corpo (8x) | número em sans **extra-bold condensada**, caixa alta, sobre o torso | ✅ `AccentWord` |
| `legenda-apoio` | peça C, oferta (20 usos) | segunda linha de texto sans bold branco, fade sutil, abaixo do card | 🟡 dá com um 2º `CaptionLayer`, falta virar componente |
| `card-perfil-instagram` | ref-F (8x na abertura) | modal com foto, bio e grade de reels com contador de views | ⬜ **falta** |
| `pip-video-reel` | ref-F (3x) | moldura vertical de Reel, cantos arredondados, sombra | ✅ `PipCard` |
| `titulo-impacto-vermelho` | ref-E (6x) | display grande vermelho `#F14418` sobre a cena | ✅ `AccentWord` |
| `titulo-impacto-box` | peça B (1x) | mesma coisa, com painel preto atrás pra garantir contraste | ✅ `PanelLite` + `AccentWord` |
| `titulo-serif-fade` | peça B, abertura (3x) | **serifada elegante**, fade suave — o único uso de serifa do corpus | 🟡 só trocar `fontFamily` |
| `painel-texto-fullscreen` | ref-E (2x), Imersão 7D | cartela preta full-screen com texto display | ✅ `PanelLite` / `TitleCard` |
| `ilustracao-fullscreen` | peça B, corpo (2x) | foto/vídeo em tela cheia, fade + **whoosh** | ✅ `OverlayGroup` |
| `cartao-passo-a-passo` | ref-E (2x) | lista numerada em caixa vermelha/preta | ✅ `StepTitle` |
| `destaque-palavra-chave` | peça B, oferta (3x) | **fundo colorido atrás de uma palavra da legenda** (marca-texto, não troca de cor) | ✅ `MarkerHighlight` |
| `cartao-preco` | peça B, oferta (3x) | retângulo colorido, cantos arredondados, valor monetário | ⬜ **falta** |
| `card-oferta-empilhado` | Imersão 7D oferta (4x) | painéis laranja/preto/branco empilhados | 🟡 `ScrollPanel`/`PanelLite` cobrem parcialmente |
| `preco-desconto-tachado` | ref-F oferta (2x) | preço antigo riscado ao lado do novo | 🟡 `strikePath` existe, falta o par |
| `corte-reflexivo-pb` | ref-F oferta (3x) | filtro P&B + troca de enquadramento, marca dúvida | ⬜ **falta** |
| `texto-manuscrito-gestual` | peça B, oferta (1x) | write-on com SFX de lápis — **único manuscrito em 195 elementos** | ✅ `HandText` |
| `b-roll-vhs` | ref-F corpo (5x) | textura VHS/degradada no b-roll de apoio | ⬜ **falta** |
| `split-screen-vertical` | ref-E | b-roll em cima, talking head embaixo | 🟡 existe `split-broll.py`, não como cena |

⚠️ **O manuscrito aparece 1 vez em 195 elementos.** No sistema educativo ele é o
workhorse (18–20 por vídeo). Em VSL de venda é praticamente inexistente — mais
uma dimensão em que os dois registros são opostos.

## Regras de composição (medidas, não inferidas)

1. **O rosto é intocável; o torso é o painel.** É a única regra que aparece
   textualmente nas **quatro** peças, com palavras diferentes:
   - ref-F: *"posicionados na área do topo-centro, deixando o rosto, as mãos e o
     corpo da apresentadora completamente livres"*
   - ref-E: *"posicionados no centro da tela, sobre o peito do locutor,
     mantendo o rosto livre"*
   - peça B, corpo: *"os overlays são posicionados sobre seu torso, mantendo o
     rosto sempre visível"*
   - Imersão 7D: *"os cartões ocupam o centro da tela, cobrindo o torso do
     locutor mas raramente o rosto"*

   Note que a zona muda (topo-centro na ref-F, sobre o peito nos outros três) —
   o que não muda é **o rosto ficar livre**. Vale registrar que em VSL hospedada
   em player próprio **não existe UI de plataforma**, então o topo é imóvel
   utilizável, ao contrário do que a nossa zona segura de reels assume.
2. **Um conceito por vez.** Máximo de 3 a 4 elementos simultâneos nos quatro
   casos. Entram e saem rápido; a tela fica limpa na maior parte do tempo.
3. **Número falado vira overlay imediatamente.** Todo valor dito ganha reforço
   gráfico em menos de meio segundo.
4. **Animação curta.** *"Embora simples (fade), são muito rápidas, durando
   poucos frames, o que as torna enérgicas."* Nada de easing longo.
5. **P&B é pontuação semântica**, reservado a reflexão/dúvida — não é filtro
   estético.
6. **Uma cor de ênfase por peça.** O vermelho `#F14418` do ref-E é o mesmo na
   legenda e na segunda camada. Não há segunda cor de destaque competindo.

---

## Mapa → remotion-compositor: o que falta

**Já coberto:** `CaptionLayer` (com `yPct`, `highlight: null`, `off[]`,
`combinaMs` — tudo que os quatro presets precisam), `AccentWord`, `StepTitle`,
`PipCard`, `PanelLite`, `StampSticker`, `MarkerHighlight`, `strikePath`,
punch-in por segmento, `OverlayGroup`.

Como 68% dos elementos são `texto-sans` no eixo central com fade ou
pop-overshoot, **o arsenal atual já cobre a maior parte do volume**. Os gaps
abaixo são de registro e de estrutura, não de falta de componente.

⚠️ **Ao usar o MotionKit em VSL, zere a rotação.** Os defaults do kit nasceram
do sistema educativo (±3° a ±5°); aqui a medição é 0° em 98% dos elementos.
Deixar o default inclina a peça inteira para o registro errado.

**Gaps, em ordem de retorno:**

1. ⬜ **Curva de estilo por bloco.** É o gap conceitual, não de componente: hoje
   o compositor aplica um estilo à peça inteira. Precisa aceitar **modo por
   trecho** — abertura saturada, corpo com legenda desligada, oferta com
   punch-in denso. Sem isso, os presets viram média e a dinâmica se perde.
2. ⬜ **`CardPerfilSocial`** — modal de perfil com avatar, bio, contadores e
   grade de miniaturas com views. É o workhorse da ref-F (8x em 90s) e o que
   materializa prova social. Genérico, sem trade dress de plataforma.
3. ⬜ **`CorteReflexivoPB`** — dessaturação + troca de enquadramento, disparada
   por marcação no roteiro nos beats de dúvida.
4. 🟡 **`PrecoTachado`** — par preço-antigo/preço-novo com risco animado.
   `strikePath` já existe; falta o componente que compõe os dois.
5. ⬜ **Textura VHS** para b-roll de apoio.
6. 🟡 **Split-screen vertical como cena** (b-roll em cima, talking head embaixo)
   — existe como script, não como componente de composição.

---

## Como reproduzir em qualquer VSL

```bash
# 1. camada de texto: posição, cor, cadência, e a timeline de ocupação
python3 .claude/skills/model-edit/scripts/tipografia.py <video.mp4> --fps 2
#    cenário quente/saturado: acrescente --so-claro (e confira no frame)

# 2. o QUE e o COMO — em TRECHOS de 60-90s, nunca na peça inteira
ffmpeg -ss <ini> -t 90 -i <video.mp4> -c:v libx264 -crf 23 -c:a aac trecho/video.mp4
python3 .claude/skills/content-analysis/scripts/deep-edit-analysis.py trecho/

# 3. ritmo de montagem, alinhado aos CTAs do player-map
python3 .claude/skills/model-edit/scripts/ritmo.py <video.mp4> --marcos ...
```

**Recorte em trechos, não mande a peça inteira.** Dois motivos: custo (Gemini em
vídeo longo é o maior custo unitário do sistema, ver `docs/CUSTOS.md`) e
precisão — está registrado em `sistema-ref-C.md` que os timestamps do
Gemini derrapam no terço final de vídeo longo. Trecho de 90s não dá tempo de
derrapar. E, de quebra, é o recorte que revela a variação de estilo por bloco,
que é o achado principal deste documento.
