# Sistema de edição ref-C — decodificado (2026-07-22)

> ⚠️ **Este documento descreve o modo CONTEÚDO EDUCATIVO dela.** Em 2026-07-29 modelamos um
> terceiro vídeo, de **OFERTA** (post-ref-C-2, vendendo o SaaS dela), e vários números daqui
> **não valem** lá: ela usa **0 punch-in** (aqui: 6 e 13), o manuscrito **antecipa** a fala em
> 0,6s em vez de segui-la, a hierarquia cai de 2,5:1 pra 1,40:1, o amarelo medido é **#FCED65**
> (não #F0E14A), não há post-it nenhum, e a legenda **liga e desliga dentro do mesmo vídeo**.
>
> Antes de aplicar este arquivo num vídeo de venda, ler o delta:
> `intelligence/edicao/ref-C-oferta.md` e
> `data/adhoc/modelagem-ref-C-plataforma/RECEITA-EDICAO.md`.

Engenharia reversa de 2 vídeos escolhidos pelo creator-1 como referência de edição:
- **post-ref-C-3** (96s, "como criar começo de vídeo") — `data/profiles/instagram-ref-C/posts/post-ref-C-3/deep-edit.json` (49 elementos mapeados)
- **post-ref-C-1** (125s, "15 dias de conteúdo em 1 dia") — `data/adhoc/instagram-post-ref-C-1/deep-edit.json` (76 elementos mapeados)

Specs geradas por `deep-edit-analysis.py` (Gemini 2.5 Pro, fps=2, schema `benchmark.deep-edit/v1`): timeline elemento a elemento com animação, posição, rotação, SFX e **`sync_fala`** (a palavra que dispara o elemento).

⚠️ **Timing**: os timestamps do Gemini derrapam no terço final de vídeo longo (no post-ref-C-1 a timeline passa dos 125s reais). A fonte de verdade do QUANDO é o transcript Deepgram por palavra: `sync_fala` → busca a palavra no `transcript.json` → timestamp exato. O deep-edit é fonte de verdade do O QUE e do COMO.

## A tese do estilo

**Câmera fixa + "legenda semântica"**: quase nenhum corte de câmera; a variedade vem 100% da pós. Todo conceito-chave FALADO vira um objeto gráfico na tela em <0.5s. A edição não ilustra o vídeo — ela transcreve o raciocínio em objetos. (Ela mesma verbaliza a tese no post-ref-C-1: "50% conteúdo, 50% audiovisual".)

Números medidos (2 vídeos):
- Densidade: **5–6 elementos novos por 10s**; máx. simultâneos 7–14; **maior janela sem elemento novo: 1.2s**.
- Punch-ins leves como pontuação de bloco: 6 em 96s, 13 em 125s — SEMPRE marcando troca de assunto/ênfase, não aleatórios.
- Rotação orgânica: textos manuscritos a -3°/+3°, post-its e PiPs a ±5° — nada perfeitamente reto.

## Gramática de componentes (consistente nos 2 vídeos)

| Componente | Spec | Animação | SFX | Ocorrências |
|---|---|---|---|---|
| `texto-manuscrito` | fonte handwritten, preto, caixa alta nas frases-tese, rotação -3/+3° | **write-on** (aparece, não se move) | lápis | 18–20/vídeo — o workhorse |
| `titulo-passo` | cartão amarelo **#F0E14A**, sans geométrica bold caps, "#N TÍTULO" | pop-overshoot (curtos) ou fade (série longa) | pop/whoosh | 3–6/vídeo, SEMPRE na mesma posição (âncora estrutural) |
| `destaque-desenhado` | círculo/sublinhado mão-livre sobre palavra do texto já em tela | draw-stroke NA palavra falada | lápis | 11/vídeo |
| `tachado` | linha grossa riscando um bloco inteiro (invalida a "equação errada") | draw-stroke | **whoosh** (não lápis) | pontual, alto impacto |
| `postit-colorido` | retângulo pastel, sans humanista regular, empilha em sequência rápida (~0.5s entre cada) | pop-overshoot ±5° | pop (cada um) | 25 no post-ref-C-1 |
| `mockup-ui` | checklist, chat WhatsApp, log de ligações, cartão de calendário, folha de caderno | slide (listas) ou pop | whoosh/pop | 4–8/vídeo — materializa o exemplo falado |
| `pip-video` | clipe flutuante com rotação ±5°, borda | pop-overshoot, sai em pop-out | pop | gancho do post-ref-C-1 (5 PiPs em 1.6s = prova visual do claim) |
| `painel-fundo` | mockup grande semi-transparente ATRÁS da pessoa | fade/slide | whoosh | transições de passo |
| `foto-prop` | foto/objeto (câmera vintage, livro) | pop | **shutter** | pontual |
| `seta` | curva mão-livre conectando 2 elementos, entra logo após o 2º | draw-stroke | lápis | conector padrão |

### Paleta (post-ref-C-1 — sistema de cor SEMÂNTICO)
Post-its categorizam por cor: `#C4E4E1` verde=autoridade · `#FADADD` rosa=leve · `#D8D3EF` roxo=bastidores · `#F9EFC9` amarelo=rotina · `#C9E2F7` azul=denso. Destaque universal: `#F0E14A` (títulos + palavra ativa da legenda). Manuscrito: preto. **Trocar por creator, manter a lógica** (cor = categoria, não decoração).

### Legendas — dois modos distintos
1. **post-ref-C-3: SEM legenda tradicional.** O texto manuscrito sincronizado É a camada de legenda (transcreve as frases-tese, não palavra a palavra). Menos poluição, mais editorial.
2. **post-ref-C-1: legenda palavra-a-palavra** sans condensada bold CAPS, branca com stroke preto, palavra ativa em `#F0E14A` com scale-up leve, posição ~50% da altura (meio da tela, não terço inferior!) + camada gráfica por cima.

## Regras de composição (o "cérebro" da edição)

1. **Palavra-chave falada → elemento em <0.5s.** O `sync_fala` é a regra, não exceção.
2. **Acumulação por bloco de assunto → limpeza conjunta em corte seco** na troca de assunto (com punch-in marcando a virada). Elementos do mesmo argumento convivem; assunto novo = tela limpa.
3. **Layout de "equação"**: argumentos opostos entram meio-esq vs meio-dir + seta conectando; a síntese/refutação entra embaixo (ou risca tudo com tachado).
4. **Rosto nunca coberto**: pessoa no centro, gráficos no topo e laterais; terço inferior só complementa composição já estabelecida em cima. Painel grande = semi-transparente.
5. **Títulos numerados sempre no mesmo lugar** — quem chega no meio se localiza em 1s.
6. **SFX 1:1 com o tipo de elemento** (lápis=escrita/traço, pop=cartão, whoosh=slide/painel/tachado, shutter=foto). Baixos, sincronizados no frame do impacto.
7. **Nada perfeitamente reto, nada se movendo à toa**: rotação leve em tudo que é "à mão"; write-on aparece sem transladar (consistente com o feedback do creator-1 de 2026-07-22).

## Correções da análise FRAME A FRAME (2026-07-22 — v2 das POCs)

O `deep-edit.json` (Gemini) acerta a estrutura mas ERRA detalhes finos — antes de implementar um estilo, extrair frames (`fps=3,tile=4x3` + closes full-res) e OLHAR. O que o olho corrigiu:

1. **Orquestração SEQUENCIAL estrita** (feedback creator-1): UMA escrita por vez — cada elemento começa só quando o anterior TERMINOU. Frases curtas de contexto se SUBSTITUEM ("Você criou" → "um conflito."), não acumulam. → `SwapText` + encadear delays com `writeDurationS()`.
2. **Fonte fina minúscula** (Nanum Pen Script, ~40-50px), não marker grosso. Bloco de texto compacto acima da cabeça; a síntese entra LOGO ABAIXO da equação, não no rodapé.
3. Conector da equação = **rabisco-gancho pequeno** (`squigglePath`), não setas duplas.
4. Tachado = **X**: 2 diagonais LONGAS finas (4–5px) cruzando o bloco inteiro, em sequência (`strikeXPaths`).
5. "Sublinhado amarelo" do deep-edit era **MARCA-TEXTO** (`MarkerHighlight` varrendo atrás da palavra); círculo em palavra é FINO (3–3.5px) e entra assim que a palavra termina de escrever.
6. Título de passo = **flat**: chip "#N" amarelo com texto preto + label em TEXTO amarelo bold (`StepTitleFlat`) — não caixa amarela inteira.
7. O gancho do post-ref-C-1 **NÃO tem legenda** (Gemini alucinou captions no trecho); "15 DIAS" é o único elemento amarelo (`AccentWord`).
8. Painel do passo = calendário **FULLSCREEN** semi-transparente com PAN lateral e cards com tag DENSO/LEVE (`BigCalendarMock`), não painel pequeno.
9. Mockups são estilo-sistema REAL: janela macOS (semáforo) com checkboxes CIRCULARES azuis marcando um a um; lista de mensagens que entra e POVOA row a row; banner de ligação iOS com botões verde/vermelho.
10. PiPs: tamanhos VARIADOS, stagger na entrada E na saída (um a um), não grid simétrico.
11. **PiPs SANGRAM as bordas** (saem do quadro esq/dir/baixo) formando um ANEL ao redor do rosto — manter tudo dentro do frame deixa a composição apertada e provoca colisão com texto. Reservar zona de texto (eixo central-topo) e zona do rosto; pip nunca invade nenhuma das duas.
12. **Hierarquia tipográfica agressiva**: a palavra-destaque amarela DOMINA (~130px vs ~50px do manuscrito ao redor — proporção ~2.5:1). Linhas BEM apertadas (lineHeight ~1.0–1.05; creator-1 apertou duas vezes: 1.18 → 1.08 → 1.02).
13. **Fonte manuscrita = Shadows Into Light Two** (Google Fonts). A Nanum Pen Script foi reprovada: acento agudo torto no ú/í (fonte coreana, latin fraco). Comp `FontTest` no Root compara candidatas com amostra PT-BR acentuada — usar ao escolher fonte de creator novo.

## Mapa → remotion-compositor: o que já temos vs o que falta

**Já coberto** (validado no ovo-de-pascoa da creator-2): `WriteOn`, `DrawStroke` (seta/sublinhado/círculo, com `localBox`), `MarkerWord`, `postit`, `stack-card`+painel com recorte rembg, punch-in por segmento, legendas TikTok-style, SFX pop/whoosh/lápis/typing, layout-zones.sh.

**Gaps — TODOS implementados em 2026-07-22** (módulos em `src/MotionKit.tsx` + `src/Mockups.tsx` + `src/themes.ts`; POCs de validação lado a lado em `estudos/edicao-ref-C/`):
1. ✅ **Grupos de overlay com limpeza conjunta** → `OverlayGroup` (exit cut/fade; delayS dos filhos relativo ao grupo).
2. ✅ **Biblioteca de mockups-UI** → `ChecklistMock`, `ChatListMock` (mensageiro genérico, sem trade dress), `CallLogMock`, `CalendarCardMock`, `WeekCalendarMock`, `NotebookPageMock`.
3. ✅ **`tachado`** → `strikePath` + `DrawStroke` (+ SFX `scratch.wav` no inventário).
4. ✅ **`pip-video`** → `PipCard` (borda branca, rotação, pop-in/pop-out).
5. ✅ **Painel semi-transparente sem recorte** → `PanelLite` (rembg vira upgrade opcional).
6. ✅ **`titulo-passo`** → `StepTitle` (numerado, posição fixa, pop|fade).
7. ✅ **Legenda modo manuscrito** → documentado como modo: POC 01/02 rodam SEM caption layer (o HandText é a legenda editorial); modo 2 = `WordCaptions` (POC 03).
8. ✅ **SFX**: `shutter.wav`, `scratch.wav`, `whoosh-soft.wav`, `pop-hi`/`pop-lo` (±2 semitons) — placeholders; definitivos seguem o fluxo do creator-1 (`tools/sfx-library/`).

**Gaps do modo OFERTA — implementados em 2026-07-29** (POC `PocOferta` no Root, stills validados):
9. ✅ **`StampSticker`** — selo carimbado: retângulo sólido + brush caps + rotação (medido −12,9°).
10. ✅ **`ScrollPanel`** — pan LINEAR de imagem alta dentro de janela fixa (medido 60px/s, easing
    nenhum). Aceita `src` (print) ou `children` (mockup em CSS).
11. ✅ **`MarkerHighlight`** ganhou `rotate` (medido −7,5°) e `blend="multiply"` (o marca-texto
    dela escurece a cena, ~#D6D21A, em vez de chapar).
12. ✅ **`temaAmareloOferta`** em `themes.ts` com o amarelo medido #FCED65.
13. ⬜ **Duplicata em escala / detail pop-out** (mesma fonte em 2 escalas simultâneas) — único gap
    de custo médio que ficou aberto.

⚠️ `HandText` recebe `x` como borda **esquerda**; `align="center"` só centraliza dentro de
`width`. Sem passar `width`, o bloco fica alinhado à esquerda a partir de `x` (pegadinha que
custou um render na POC).

## Workflow de replicação (qualquer vídeo, qualquer creator)

1. Vídeo montado + transcript do montado (como sempre — zero deriva).
2. **Roteiro de overlays**: Claude lê o transcript e decide os elementos usando esta gramática (o que vira manuscrito, o que vira post-it, onde tem equação/tachado, onde punch-in) — respeitando densidade alvo 4–6/10s e as 7 regras acima. Paleta e fonte vêm da linha editorial do creator.
3. Timing: palavra-gatilho → timestamp do transcript (nunca chutar segundos).
4. Posições: `layout-zones.sh` por janela de elemento.
5. Render + QC frames-chave.

Pra REPLICAR um vídeo de referência específico: rodar `deep-edit-analysis.py` no vídeo de referência e traduzir a timeline (componente a componente) pro overlays.json do nosso vídeo.
