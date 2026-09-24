---
name: omni-insert
description: >-
  Usa o Gemini Omni Flash na ilha de edição de três formas: EDITAR a própria
  cena com o creator em quadro (até ~4s, para inserir elemento, relight ou
  trocar fundo), ANIMAR o cenário real dele a partir de um frame, ou GERAR um
  plano novo e encaixar o resultado na janela do vídeo sem interromper a fala
  nem derivar o A/V. Use quando um beat pedir uma imagem que o Remotion não
  faz, como elemento inserido na cena, cenário, atmosfera, metáfora visual ou
  cold open.
---

# omni-insert

Bloco de edição: **beat do roteiro → plano gerado → encaixe na janela**. Complementa o `remotion-compositor` — ele faz a camada gráfica (texto, cartões, setas), esta peça faz a **imagem fotorrealista** (cenário, atmosfera, câmera).

Validado em 2026-07-25 no gancho de `peca-08` (creator-1) e em 4 planos sobre `peca-03`/`peca-04` (creator-2). Estudos com todas as medições: **`estudos/omni-insert-poc/README.md`** e **`estudos/omni-insert-poc/creator-2/README.md`**.

## ⚠️ Leia antes de propor qualquer coisa

1. **`task=edit` aceita até ~4s de input.** 3s, 3,5s e 4s passam; 5s, 6s e 8s são bloqueados (`Input blocked: real people's likenesses`) — o gatilho é a duração, não o texto (o mesmo bloqueio acontece com prompt neutro de luz). A saída **herda a duração exata da fonte**. Para janela maior que 4s, use `anim`/`gen` (cena sem o creator).
2. **Com o creator em cena, o edit funciona — mas o rosto sai reinterpretado.** Dentro dos 4s e com prompt cirúrgico, volta reconhecível (mesmos óculos, cabelo, barba, lapela no lugar); pedido de reconstrução total da cena troca o rosto por outra pessoa. É "ele levemente idealizado", não ele exato: **quem decide se serve é o creator**, sempre mostrando o still antes.
3. **Tudo que sai do Omni tem SynthID** (marca d'água invisível detectável) — vale para b-roll e, mais ainda, para plano com o creator.
4. **Nada de pessoa reconhecível no prompt** — nem nome, nem "um homem parecido com". Planos sem pessoa, ou com figuras distantes/silhuetas. **Parte do corpo passa** (o macro de mão com aliança gerou sem bloqueio) — a fronteira é rosto reconhecível. Mas descreva o tom: pedi só "uma mão" e veio mão masculina fechando o punho, que num vídeo da creator-2 lê como tensão/ameaça — errado pro conteúdo dela.
5. **A escolha de usar é editorial, não técnica.** Insert é efeito; a regra de look #1 do projeto ("sem efeitos improvisados") vale aqui. Entra no PLANO-EDICAO.md pra aprovação como qualquer outro beat, com a janela e o prompt explícitos.

## Quando vale (e quando não)

| Vale | Não vale |
|---|---|
| **Inserir um elemento na própria cena** (`edit`, ≤4s) — o creator continua em quadro | Janela maior que ~4s com o creator em cena (bloqueia) |
| **Animar o cenário real do creator** (`anim`) — cold open ou respiro sem sair da casa dele | Qualquer coisa que o Remotion já faz bem (texto, cartão, seta, mockup de UI) |
| Beat que descreve um **lugar/atmosfera** que não temos footage ("sala de controle", "escritório vazio de madrugada") | Metáfora que exige sair do mundo do vídeo sem necessidade — o barco da peca-04 é bonito, mas tira o espectador da cozinha dela |
| **Metáfora visual** do argumento (números virando vermelho, algo desmoronando) | Plano com o creator em cena — vai bloquear ou trocar o rosto |
| **Cold open** de 2–3s antes do primeiro frame do creator | Substituir a fala — o insert **cobre a imagem**, o áudio continua |
| Cutaway que **esconde uma emenda feia** da montagem | Vídeo com dado real ilustrado de forma enganosa (número inventado na tela) |

## Fluxo

```
1. escolher a janela  → beat do transcript (t_in, t_out), 3–10s, imagem-alvo clara
2. omni-gen.py        → anim (cenário real do creator) OU gen (cena nova) — 720x1280@24 com áudio
3. avaliar            → grid de frames; se não serviu, refaz o prompt
4. encaixar.py        → normaliza + overlay na janela (ou --cold-open) + QC medido
5. camada gráfica     → graphics .mov do Remotion POR CIMA do resultado (ordem importa)
```

### ⭐ Modo mais fiel: `edit` — mexer NA cena, com o creator dentro (≤4s)

Quando o beat pede que **a cena dele mude** (um elemento aparecendo no palco, outra luz, outro fundo)
e não que a gente corte para outro lugar. **A voz do creator é preservada** — ver receita abaixo.

```bash
# 1. cortar o trecho COM ÁUDIO, entre pausas naturais (nunca -an!)
ffmpeg -ss 43.89 -t 3.66 -i v1-montado.mp4 -c:v libx264 -crf 20 -c:a aac -b:a 192k trecho.mp4
# 2. editar
python3 scripts/omni-gen.py edit trecho.mp4 \
  "Keep the person, his face, his voice, his clothing, the stage, the framing and all motion \
   exactly as in the source video. Keep the original speech unchanged. The only change: <UMA mudança>." out.mp4
# 3. QC OBRIGATÓRIO da fala (veredito acústico)
python3 scripts/qc-fala.py trecho.mp4 out.mp4
# 4. encaixar usando a VOZ DEVOLVIDA (o encaixe roda os QCs de janela sozinho)
python3 scripts/encaixar.py --base v1-montado.mp4 --insert out.mp4 \
  --in 43.89 --out 47.55 --transicao corte --audio insert --saida v-edit.mp4
```

#### 🔊 A voz é preservada — e o erro clássico é mandar vídeo mudo

Medido nos dois trechos testados: **F0 177,8→174,9 Hz** e **200,0→201,3 Hz** (menos de 2% de
diferença), **similaridade espectral 0,953 e 0,982**, mesmas palavras, timing dentro dos 80ms de
quantização do Deepgram. É a voz dele, casada com os lábios que o modelo gerou — o mesmo
comportamento que o creator-1 via no Google Flow.

O que quebrava isso na primeira tentativa: **cortar o trecho com `-an`**. Sem voz na entrada o
modelo sintetiza uma nova. Se a saída vier com voz estranha, o insumo estava mudo — confira
com `ffprobe` antes de culpar o modelo.

Por isso o encaixe usa **`--audio insert`** neste modo: manter a trilha da base jogaria fora
justamente a voz preservada (e o lip sync que veio com ela).

#### 🔑 A janela do `edit` tem que caber DENTRO de um plano da EDL

Se a janela **cruza uma emenda de montagem**, o Omni vê o corte, reinterpreta a cena e **degrada a
trilha**: medido na peca-07, correlação de fala 0,445 e 0,527 (e numa das tentativas duas
palavras perdidas). A mesma cena, com a janela contida num único plano: F0 idêntico, espectro 0,994,
correlação **0,922**, todas as palavras. Bônus: terminar a janela na fronteira do plano esconde o
fim do efeito num corte de câmera que já existia.

#### 🔑 O efeito tem que MORRER dentro do insert, não na transição

Peça no prompt que o elemento *"fade out completely before the end of the clip, leaving the plain
scene in the final frames"*. Com o efeito ainda no auge no último frame, o corte de volta dá um
salto de luminância de **55** no `flicker-scan`; com ele dissipado, **5,7**. E **nunca use
`dissolve` pra mascarar isso**: o Omni desloca o corpo/mãos, então o cross-dissolve mostra duas
versões da pessoa — o creator-1 viu na primeira entrega ("essa sobreposição do print").

#### 🔑 Prefira `--audio base` quando a janela não precisa da trilha nova

Se o insert só acrescenta elemento à cena (não muda o que se ouve), manter a trilha original
intocada elimina qualquer artefato de emenda de áudio — foi a correção do "áudios juntos" reportado
pelo creator-1. Use `--audio insert` só quando o trecho editado precisar da trilha que veio com ele.

#### ⚠️ Não mencione voz nem fala no prompt

`"Keep the person, his speech and voice, ..."` devolve **`Input blocked: prompt could not be
processed`** (não é o bloqueio de likeness). Sem as palavras "speech"/"voice", o mesmo prompt passa.
A preservação da voz vem de enviar o trecho COM áudio, não de pedir no texto.

#### 🔊 Duas armadilhas de áudio no encaixe (medidas na produção peca-07)

- **O Omni devolve a trilha ~2,8 dB mais baixa** que a fonte — queda uniforme nas três bandas, sem
  som novo. Sem compensar, a janela entra com queda de volume audível. O `encaixar.py` mede o RMS da
  MESMA janela na base e aplica o ganho automaticamente (clamp ±3x).
- **`amix` não serve pra substituir trilha numa janela.** Medido com `asplit` de debug: ramo da base
  = 0 na janela, ramo do insert = 2211, e o `amix` devolvia **3127** (√2 × 2211); `amerge+pan`
  devolvia 4422 (2×). A trilha é montada em **numpy**, amostra a amostra, com crossfade de 60ms —
  determinístico. Se for mexer nesse trecho, valide medindo o RMS dentro E fora da janela.

#### ⚠️ QC da fala é acústico, não por transcrição

`qc-fala.py` compara F0, espectro e o envelope **depois de alinhar** — correlação de 0,975 e 0,972
nos dois trechos testados, ou seja, fala idêntica. O ASR entra só como indício de onde ouvir.

Por que não confiar no diff de transcrição: ele acusou "fala alterada" (`"conta que tinha gasto"` →
`"conta tinha gasto gasto"`) num caso em que **o creator gaguejou de verdade** — o modelo foi fiel e
quem errou foi o reconhecedor. Mesma armadilha já registrada na `edit-video`: transcrição não é
verdade acústica. E cuidado com a medida: envelope **sem alinhar** derruba a correlação de 0,975
para 0,147 por causa de 80ms de offset.

Cortar a janela entre **pausas naturais** (gap ≥0,25s nos word-timestamps) segue sendo boa prática
de edição — só não é remédio pra um defeito do modelo.

Duas regras que decidem o resultado:

- **Declarar a preservação** (pessoa, rosto, roupa, enquadramento, câmera, movimento) e pedir **uma
  única** mudança. Pedido de reconstrução total ("o palco vira uma sala futurista") devolve outra
  pessoa em cena.
- **O movimento é preservado** — medido no palco do creator-1: correlação de 0,870 na trajetória do
  corpo e desvio de 3,7px em 270 (1,4%), com a abertura da boca batendo nos instantes amostrados.
- ⚠️ **O primeiro frame vira um close**: o modelo re-decupa a abertura do trecho. Substituir a janela
  inteira resolve; casar frame a frame, não.
- ⚠️ **Não use `--color-match` aqui.** A cena editada costuma ser legitimamente mais luminosa (o
  elemento inserido emite luz); os ganhos batem no clamp e escurecem tudo. Color match é pra b-roll.

### `anim` (image_to_video) — animar o cenário dele, sem ninguém em quadro

O modo que casa melhor **não** é inventar uma cena — é **animar o cenário real do creator**:

```bash
# 1. recortar um pedaço do vídeo dele/dela SEM ninguém em quadro (bancada, mesa, canto da sala)
ffmpeg -ss 20 -i v1-graded.mp4 -vframes 1 -vf "crop=430:764:0:900,scale=540:960" cenario.png
# 2. animar
python3 scripts/omni-gen.py anim cenario.png "<direção de movimento>" insert.mp4
```

Validado com a cozinha da creator-2: voltou a **mesma** bancada, mesma cafeteira, mesma taça, com a câmera se aproximando — e o vídeo abre nela na mesma cozinha. É o resultado que menos denuncia IA, porque o cenário é literalmente o dela. `gen` produz imagem bonita porém genérica; `anim` produz continuidade. Sem rosto no recorte, não bloqueia.

### 1. Gerar do zero (`gen`), quando não há cenário aproveitável

```bash
python3 .claude/skills/omni-insert/scripts/omni-gen.py gen "<prompt>" insert.mp4
```

O prompt é **direção de cena**, não legenda. O que fez diferença na validação:

- **Declarar "sem nenhuma pessoa em cena"** logo no começo — evita o filtro de likeness e evita figurantes indesejados.
- **Descrever o arco temporal**, não só o quadro: *"os números verdes vão ficando vermelhos um a um enquanto alertas acendem"* → ele distribui o arco pelos 8s e dá pra casar com a fala.
- **Movimento de câmera explícito**: "travelling lento para frente", "câmera parada".
- **"Sem texto legível, sem logotipos"** — texto gerado sai borrado/errado e denuncia IA.
- **Áudio**: o modelo gera trilha junto. Pedir ambiência ("drone grave, bipes discretos") ou o encaixe descarta — o `encaixar.py` **ignora o áudio do insert** e mantém o do creator.
- **Pedir a duração no texto** ("plano de 6 segundos"): não existe parâmetro de duração, e sem pedir ele entrega 10s. São 5.792 tokens por segundo — 8s custa $0,82, 10s custa $1,02. Pedir a duração é a diferença de ~20% na conta.

Gerar duas ou três opções e escolher sai por ~$2–3 — comparável a uma iteração de Remotion, mas o gasto é em dinheiro, não em tempo.

### 2. Encaixar

```bash
# insert numa janela (a fala continua correndo por baixo)
python3 .claude/skills/omni-insert/scripts/encaixar.py \
  --base v1-graded.mp4 --insert insert.mp4 \
  --in 2.5 --out 8.0 --transicao corte --color-match --saida v-insert.mp4

# abertura antes do primeiro frame (desloca a fala — o script mede quanto)
python3 .claude/skills/omni-insert/scripts/encaixar.py \
  --base v1-graded.mp4 --insert insert.mp4 --cold-open 3.0 --saida v-cold.mp4
```

**`--nitidez`** (default `unsharp`): o upscale 1,5x custa definição. Medido na base nativa 1080p da creator-2 (variância do laplaciano numa região com detalhe): base **141** · só lanczos **47** · **+unsharp 97** · +unsharp+grão 177. O grão infla o número com ruído, não com detalhe — só usar (`unsharp+grao`) quando a base tem grão perceptível, senão fica sujo.

**`--color-match`**: mede a mediana por canal da base **vizinha à janela** (1s antes e 1s depois — é onde o olho compara) e aplica ganho por canal no insert, clampado em ±40% pra não inventar cor quando a cena é legitimamente diferente. Nos testes o insert vinha 9–17% mais escuro que a base.

**`--cold-open N`**: o plano entra antes da base. Aqui a timeline muda por definição, então é **uma emenda só**, com vídeo e áudio cortados no mesmo grafo. O QC mede o deslocamento real por correlação de envelope e imprime o valor — **some esse número a todos os timestamps de legenda/overlay**.

⚠️ **Abertura muda soa quebrada** (feedback do creator-1 na v1: 3s de silêncio digital e corte seco pra fala — "não encaixa de forma fluida"). O padrão agora resolve isso com três coisas:

- **`--leito room-tone`** (default): usa a fatia mais silenciosa da PRÓPRIA gravação (0,25s em loop, com fade) como som de sala. Nem tente usar o áudio do plano gerado: pedindo "ambiente silencioso" o Omni entrega silêncio de verdade — medido, 0,1% de fundo de escala. Em talking-head não existe janela longa de silêncio (o creator fala o tempo todo), por isso a fatia é curta e repetida.
- **`--jcut S`** (default 0,5): a **voz** da base entra S segundos antes do corte de imagem — o vídeo da base começa em S, esses frames ficam cobertos pelo plano, e áudio e vídeo dela seguem sincronizados entre si. É o que faz a emenda soar fluida. O deslocamento das legendas passa a ser `N − S`.
- **Cold open curto**: 1,5–2s. Com `--cold-open 2 --jcut 0.6` o trecho sem voz cai de 3,0s para 1,4s.

**Como o encaixe funciona — e por que é assim**: o insert entra por `overlay` numa janela `enable=between(t,…)`, com a base rodando por baixo. A duração da timeline **não muda** e a trilha é copiada (`-c:a copy`). Isso é resposta direta à correção de 2026-07-25 (deriva A/V): *num pipeline de concat, quantização por segmento é deriva garantida*. Aqui não há concat, logo não há deriva — e o script **prova** isso a cada run comparando o md5 do áudio com o da base.

🐛 **Duas armadilhas de ffmpeg que já produziram um demo dessincronizado** (voz do insert tocando em 0,00s e silêncio total depois da janela):

- **`amix` ignora o `-itsoffset` do input** — ele alinha pelo primeiro sample de cada entrada. Áudio se posiciona com **`adelay` explícito**. Por isso o insert entra duas vezes no comando: uma com `itsoffset` (vídeo, pro overlay) e outra crua (áudio), pra não deslocar duas vezes.
- **`afade=out` zera o sinal permanentemente** — um `afade=in` em série depois multiplica zero por rampa e devolve silêncio. Para tirar-e-devolver ganho use **`volume` com expressão temporal** (`eval=frame`), que é reversível.

Com `--audio insert` o script mede sozinho: **onde a voz do insert caiu** (correlação de envelope contra a janela) e se a **energia fora da janela** continua igual à da base. Foi a ausência desses dois números que deixou o demo quebrado passar.

Transições (`--transicao`):

| Modo | Quando |
|---|---|
| `corte` **(padrão)** | default de b-roll. Limpo, não chama atenção pra si |
| `flash` | insert muito diferente da base; 1 frame branco a 70% esconde a troca de textura (`--flash-frames`, `--flash-opacidade`) |
| `dissolve` | último recurso — deixa fantasma do corpo do creator sobre o insert (visível em `estudos/omni-insert-poc/frames/emenda-todas.png`) |

### 3. Ordem na cadeia de composição

```
bruto → LUT hlg2sdr → grade do creator → [omni-insert] → graphics .mov (unpremultiply+overlay) → final
```

O insert entra **antes** da camada gráfica: legendas e cartões precisam correr por cima dele, senão somem na janela. Validado — no demo o cartão "R$ 600.000" atravessa o insert inteiro.

## Especificações medidas

| Item | Valor |
|---|---|
| Saída | 720x1280, 24fps, com áudio, mp4 — **720p é o teto** (ver abaixo) |
| Duração | 10s se o prompt não pedir; obedece a duração pedida no texto (8s quando pedida) |
| Latência | 32–39s (gen/anim), ~43s (edit 3s) |
| Custo | 5.792 tokens/s × $17,50/1M = **$0,10/s** — $0,82 (8s), $1,02 (10s) |
| Normalização | upscale lanczos 1,5x → 1080x1920 + `fps=30`; o upscale é visível se comparado lado a lado com a base nativa, aceitável em movimento |
| Modelo | `gemini-omni-flash-preview` (override: `BENCH_OMNI_MODEL`) |

## API (o que custou descobrir)

Endpoint é `POST /v1beta/interactions` — **não** `generateContent`, apesar de o `models.get` anunciar `generateContent`.

- Input de vídeo precisa de `{"type": "video", "uri": …}`. Com `"document"` a API responde `Exactly one input video is required for edit task`.
- Upload é a Files API em **protocolo resumable** (multipart simples não passa vídeo), e o arquivo fica `PROCESSING` antes de `ACTIVE`.
- A URI de saída já vem com sufixo `:download?alt=media` — extrair o id entre `files/` e `:` antes de consultar o estado.
- `response_format: {"type":"video","delivery":"uri"}`; o arquivo de saída também passa por `PROCESSING`.
- `generation_config.video_config.task` aceita: `text_to_video`, `image_to_video`, `reference_to_video`, `edit`, **`extend`** (esta última ainda não testada aqui).
- **Não há parâmetro de áudio.** `audio`/`preserve_audio` são desconhecidos em `video_config` e em `response_format` — a preservação da voz vem de mandar o vídeo COM trilha, não de configuração.
- **Não há como pedir resolução nem duração.** `response_format.resolution` está no schema e conhece `360p/720p/1080p/4k` (mandar valor inválido devolve a lista), mas qualquer valor válido responde `Unknown parameter 'resolution'` — idem em `generation_config.video_config`. `duration`/`duration_seconds` também são desconhecidos. Duração se controla pelo texto do prompt; resolução, não se controla.
- Sondar o schema com **valor inválido** é grátis e devolve a lista de valores aceitos — foi assim que se mapeou `type` (`'video'`, não `'document'`) e o enum de resolução.
