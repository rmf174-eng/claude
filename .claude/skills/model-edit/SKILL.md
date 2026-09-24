---
name: model-edit
description: Engenharia reversa de uma edição de vídeo alheia — mede cortes, reenquadramentos, transições, overlays, tipografia, som e cor de um vídeo editado e devolve uma RECEITA reproduzível (edit-recipe.json + ficha em intelligence/edicao/), com o gap analysis do que a nossa máquina já faz e o que falta. Use quando o creator-1 mandar um vídeo editado dizendo "quero aprender essa edição", "modela isso", "como ele fez esse efeito", ou mandar um par bastidor+editado. Alimenta as skills edit-video e remotion-compositor.
---

# model-edit

**Insumo**: um vídeo editado (idealmente com o bruto correspondente).
**Entrega**: `RECEITA-EDICAO.md` + `edit-recipe.json` na pasta de análise, ficha em
`intelligence/edicao/<handle>.md`, e uma lista priorizada do que falta implementar.

A regra da skill: **medir, nunca descrever de olho.** "Ele usa um zoom leve" não serve;
"z=1,306 com centro em cx 41,1% / cy 44,8%" vira `edl.json` e roda. Toda afirmação da
receita tem que ter vindo de um script daqui ou de um frame que eu OLHEI.

## Quando o par bruto+editado existe, ele vale mais que tudo

Creator postando bastidor ("como eu gravo vs vídeo editado") é o insumo mais rico que
existe: dá pra recuperar a EDL REAL, medir quanto do bruto foi aproveitado, onde ele
cortou e — o mais valioso — **rodar a nossa máquina no mesmo bruto e comparar frame a
frame com a entrega dele**. Sem o par, dá pra medir tudo menos a montagem.

## Fluxo

### 0. Ingestão
`data/adhoc/modelagem-<slug>/` com `editado/video.mp4` e (se houver) `quase-original/video.mp4`.
`transcribe` nos dois. Proxy 540x960 pra tudo que for análise de movimento — 4K só pra medir pixel.
⚠️ **Bastidor costuma ter grafismo queimado** (badge "COMO EU GRAVO VS EDITADO"). Meça a bbox
e remova com `delogo` antes de usar o bruto como fonte — mas mire o retângulo com **margem**:
se a borda do retângulo cair dentro do badge, o `delogo` interpola branco com branco e pinta um bloco.

### 1. Montagem — `scripts/edl-do-par.py <bruto.json> <editado.json> [edl-medida.json]`
Alinha as transcrições e devolve os segmentos, o que foi descartado, quanto de pausa saiu e
se houve speed ramp. Números que importam: **% do bruto aproveitado** e **duração média de plano**.

### 2. Cortes — `scripts/cortes.py <editado.mp4> --faixas 4`
Diff por faixa horizontal. Classifica corte duro / troca de camada / jump cut.
Cruze com as emendas de áudio da etapa 1: **emenda de áudio SEM corte de vídeo = a edição
está escondendo aquele corte** (b-roll por cima, ou o enquadramento não mudou).

### 2b. Ritmo — `scripts/ritmo.py <editado.mp4> --marcos 0:00-1:22=abertura ...`
Agrega os cortes do 2 em **perfil de montagem**: cortes/min e duração de plano por trecho, e
uma barra por janela ao longo da timeline. O `cortes.py` lista cada corte; este responde onde
a montagem acelera e onde respira.

Em peça longa use `--fps 8` (o default de 30 estoura memória num vídeo de 38 min). Alinhe os
`--marcos` aos CTAs lidos do `player-map.md`, não a divisões redondas — o que interessa é o
ritmo *do bloco de oferta*, não o do minuto 20.

Medido em 8 VSLs (2026-08-01, `intelligence/edicao/vsl-rede-ref-E.md`): o ritmo de
corte é função da temperatura do tráfego (27,9/min em frio total contra 8,6/min em quente), e
o plano **sempre** alonga no bloco de preço. Serve como QC do nosso próprio material.

⚠️ Pra medir silêncio, **não confie no `silencedetect` do ffmpeg** neste build: as três VSLs
medidas deram "zero pausas" porque há trilha contínua por baixo mascarando tudo. Decodifique
pra PCM e meça RMS em janelas de 100ms — o percentil 5 ficou entre −34 e −38 dBFS, o que
denuncia a trilha em vez de esconder.

### 2c. Camada de texto na peça inteira — `scripts/tipografia.py <video.mp4> --fps 2`
O `grafismo.py` (etapa 5) isola UM overlay comparando dois frames. Este mede a
**tipografia da peça inteira** e devolve direto os campos do `CaptionStyle`:
`yPct`, altura do glifo, `color`, `highlight`, `maxWidth`, % do tempo na tela e
segundos por página (que vira o `combinaMs`). Também dá a timeline de ocupação
de texto por região (topo/meio/base), que é como se lê a variação de estilo.

Como ele acha a legenda no meio do cenário, em dois passos — os dois necessários:
1. **texto pisca**: pesa cada pixel pela taxa de alternância da máscara. Tira
   parede clara e camisa brilhante, que acendem e ficam acesas.
2. **legenda é centralizada**: pontua por intensidade × centralidade horizontal.
   Sem isso o detector elegeu um **teclado branco na mesa** — 26% de pixels
   claros no rodapé, e as mãos passando por cima faziam a máscara piscar igual
   a uma legenda.

⚠️ **Limite medido:** funciona sem intervenção em legenda clara sobre cenário
controlado (3 de 4 VSLs). Em **cenário quente e saturado com legenda colorida**
(sala com sofá laranja e madeira) ele elege o cenário; com `--so-claro` passa a
eleger os cards de print brancos. Nesse caso: pegue a cor no `deep-edit` do
Gemini e volte pro pixel só pra achar a posição. As duas ferramentas se cobrem.

⚠️ Cor: mede o **núcleo do glifo** (percentil 75 de croma), não a média da
máscara. A média inclui pixels de borda e puxa o hex pro cenário — no caso
medido, média `#C94C2B` contra núcleo `#F14418`, a mesma legenda.

Precedente: `.claude/skills/remotion-compositor/references/sistema-vsl-trafego-pago.md`
(4 VSLs) + preset pronto em `tools/remotion-compositor/src/vsl/estilos-medidos.ts`.

### 3. Enquadramento — `scripts/reframe.py <ref.jpg> <plano.jpg> [--ybase N]`
Um frame por plano. Com o bruto → zoom absoluto; sem o bruto → contra o 1º plano do próprio
editado (zoom relativo). Imprime direto o `{"zoom","cx","cy"}` pro `edl.json` do `montar.sh`.

### 4. Camadas sobrepostas — `scripts/mascara.py <bruto.jpg> <composto.jpg> <z> <x0> <y0>`
Só quando tem b-roll/split-screen. Devolve o perfil de alpha e já imprime os
`--opaco/--fim` do `split-broll.py`. **Sempre confirme olhando um recorte da fronteira.**

### 5. Tipografia e overlays — `scripts/grafismo.py <com.jpg> <sem.jpg> --faixas y0:y1:rotulo`
Isola o grafismo por diferença. Devolve bbox em 1080x1920, cor do núcleo e a conferência das
zonas de UI. Para o **timing** das animações, extraia uma tira temporal e OLHE:
```bash
ffmpeg -ss T0 -t DUR -i proxy.mp4 -vf "fps=10,crop=540:80:0:Y,scale=540:80" -vsync 0 /tmp/l_%02d.png
```
(uma tira dessas resolveu em 10s o que 3 medições numéricas erraram: descobriu que a 2ª linha
do título entra em **pop seco**, não em fade.)
⚠️ O "frame sem" tem que ser do **mesmo plano**. De outro plano, a diferença acende a tela toda.
⚠️ Máscara por cor **não funciona** quando o texto tem a cor da cena (o destaque terracota tinha
a matiz da parede). Diferença funciona sempre.

### 6. Som e cor — `scripts/som-e-cor.py audio A B --t <dur>` · `cor A.jpg B.jpg y0:y1:x0:x1 ...`
🐛 **A LRA engana.** Comparar a LRA do bruto com a do editado mede o corte de pausa, não a
compressão — na primeira modelagem isso produziu a conclusão errada "ele comprime pesadíssimo".
Meça a **mesma janela** e olhe **piso vs fala**: com a fala no mesmo nível, piso 20dB mais alto
= compressão. `som-e-cor.py paleta` sugere a cor de destaque harmonizada com a cena.

### 7. Receita + ficha + **entrada de catálogo**
Escreva `RECEITA-EDICAO.md` (prosa, com os números) e `edit-recipe.json`
(schema em `references/edit-recipe.md`). Crie/atualize `intelligence/edicao/<handle>.md`
com o resumo em uma frase + o que é replicável hoje.

🔴 **A modelagem só termina quando o dispositivo vira ESCOLHÍVEL** (SPEC-15). Ficha
sem entrada de catálogo é receita que morre em prosa: das 5 fichas de
`intelligence/edicao/`, **três nunca viraram nada** que a próxima produção pudesse
escolher — e uma delas é justamente *"o vídeo que o creator-3 elogiou e pediu pra
replicar"*. Então:

- **todo dispositivo reutilizável** que a modelagem produziu ganha uma entrada em
  `tools/remotion-compositor/src/catalogo/estilos.ts`, com `medido: {fonte, ficha, data}`
  apontando para a SUA ficha. Rode `npm run catalogo` e olhe o `.png` gerado;
- **`estado: "candidato"` é resposta aceita** — e é a resposta certa quando o
  componente ainda está preso a uma peça (geometria cravada, `staticFile` de asset
  de produção, texto literal do roteiro). Basta nomear o `bloqueio`. Registrar como
  candidato é honesto hoje e vira a lista de trabalho de amanhã; **esconder é o
  defeito que o catálogo existe para corrigir**;
- **a ficha ganha a linha `→ catálogo: <slug>`**, que é o que fecha o loop no
  outro sentido;
- se o dispositivo medido **não tem implementação nossa equivalente**, não force o
  `medido` para um slug parecido — isso mente na procedência. Registre por que não
  tem (o caso `ref-H.md`: o split dela é **empilhado**, o nosso `split-broll.py`
  é **lateral com feather**; são mecanismos diferentes).

### 8. Gap analysis
Tabela: técnica medida → temos? → o que falta → custo. Priorize por **valor/custo**.
O que já for barato, implemente na hora nas skills `edit-video` / `remotion-compositor`.

### 9. ⭐ Replicação (só com o par) — a prova
Rode a nossa máquina no bruto dele e compare. Sem isso, a modelagem é opinião.
Aceite como "bateu" quando: bbox dos elementos ±15px, zoom ±0,02, dinâmica de áudio ±2dB,
Δcor <5%, e a montagem passa no `audit-emendas.py` + ASR limpo.

## Onde a receita vira execução

| medida | vira |
|---|---|
| EDL + pads | `janelas.json` → `bordas.py` → `edl.json` (skill `edit-video`) |
| zoom/cx/cy por plano | campos `zoom`/`cx`/`cy` na EDL → `montar.sh` |
| split-screen/feather | `split-broll.py` (skill `edit-video`) |
| título de gancho | `HookTitle` (`src/TitleCard.tsx`) |
| estilo de legenda | `CaptionLayer` + `CaptionStyle` (`src/CaptionLayer.tsx`) |
| som | cadeia `acompressor,loudnorm` calibrada pela dinâmica |
| cor | `eq=saturation=…:gamma=…` medido |

## Lições da 1ª modelagem (ref-D, 2026-07-25)

1. **A medição que mais mudou a máquina não foi a de efeito, foi a de RITMO.** O que separa
   a edição dele da nossa não é o split-screen — é cortar colado na palavra e alternar
   enquadramento. Efeito é o que se vê; ritmo é o que segura.
2. **Modelar acha bug nosso.** A comparação expôs três defeitos reais no `bordas.py`
   (onset estendendo o máximo quando não achava silêncio → sílaba fantasma; sem teto na
   correção acústica; cauda medida por piso absoluto em vez da soltura da palavra).
   Modelar não é só copiar — é ter uma régua externa.
3. **Cuidado com métrica agregada em janelas diferentes** (a saga da LRA). Antes de concluir,
   pergunte: "estou comparando a mesma janela?"
4. **A referência pode violar as nossas regras de propósito** (o título dele invade a zona
   y<290 do corte 4:5). Registre como trade-off, não copie no automático.
5. **Olho e número são complementares.** A tira temporal de 10 frames resolveu o que a
   estatística errou; a bbox por alpha pegou o que o olho não veria.

## Referências

- Primeira modelagem completa: `data/adhoc/modelagem-edicao/RECEITA-EDICAO.md`
- Replicação provada: `estudos/modelagem-ref-D/NOTAS.md`
- Biblioteca de edições modeladas: `intelligence/edicao/`
- Capacidades e limites da nossa ilha de edição: `docs/EDICAO-CAPACIDADES.md`
