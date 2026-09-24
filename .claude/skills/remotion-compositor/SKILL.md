---
name: remotion-compositor
description: Camada de edição gráfica programática sobre vídeo montado — legendas animadas TikTok-style, cartões/post-its sincronizados à fala, punch-in que esconde jump cuts, setas desenhando, texto write-on, painel atrás da pessoa (recorte rembg) e SFX. Use quando pedirem edição "estilo ref-C", legendas animadas, overlays gráficos, motion graphics ou color grading num vídeo do pipeline. Bloco 6 do roadmap de edição (docs/EDICAO-CAPACIDADES.md).
---

# remotion-compositor

Bloco de edição: **vídeo montado + transcript + roteiro de overlays → vídeo editado final**. Validado numa produção real, em duas iterações. Dois sistemas de referência decodificados:

- **`references/sistema-ref-C.md`** — conteúdo educativo vertical (gramática de 10 componentes, 7 regras, paleta semântica).
- **`references/sistema-vsl-trafego-pago.md`** — **VSL de tráfego pago** (4 peças no ar, agosto/2026). Traz o achado que não aparece em vídeo curto: **o estilo muda dentro da peça**, e a curva se repete em duas operações independentes — densidade de grafismo cai da abertura pra oferta enquanto o punch-in faz um U e explode na oferta. Preset de legenda medido e pronto: `src/vsl/estilos-medidos.ts` (4 estilos por temperatura de tráfego).

Estilo de referência original: **`references/sistema-ref-C.md`** — o sistema da ref-C decodificado (gramática de 10 componentes, 7 regras de composição, paleta semântica, gaps priorizados), com timeline elemento a elemento nos `deep-edit.json` de `data/profiles/instagram-ref-C/posts/post-ref-C-3/` e `data/adhoc/instagram-post-ref-C-1/`.

## O contrato vale aqui — as Regras Duras moram numa skill só

As **Regras Duras (RD-1…RD-15)** e o **contrato de contexto (C1…C8)** estão em
`.claude/skills/edit-video/SKILL.md` e valem para tudo que se faz aqui. Elas não são
repetidas neste arquivo **de propósito**: contrato dito duas vezes é contrato que
diverge na terceira edição — o modelo que copiamos gasta 13,5% do arquivo em
anti-patterns que repetem as próprias regras, e não herdamos isso.

As que mais mordem quem escreve TSX: **RD-1** (nenhuma camada gráfica antes do OK no
corte — `qc-portao.py <dir>` tem que sair 0), **RD-11** (texto e overlay são
Remotion, nunca queimados com ffmpeg ou PIL), **RD-12** (entry point isolado por
produção — a lição nasceu aqui) e **RD-2** (produção publicada não se re-renderiza).

### Índice das seções

| onde | o que resolve |
|---|---|
| Regras de look · Fluxo por vídeo | o que é permitido e a ordem das chamadas |
| Painel atrás da pessoa · Geometria de traço | recorte por matte e medição no alpha |
| `OverlayGroup` tem DOIS referenciais de tempo · Gotchas | as armadilhas que apagam um beat inteiro |
| Color — pegadinha HDR | por que a composição é alpha sobre a base, e nunca o contrário |
| Lettering anotado · MotionKit · Peças novas da modelagem | o arsenal, componente a componente |
| Composição · Composição nova lê de `PERFIL` | render e a fronteira da produção entregue |
| Legenda por LARGURA MEDIDA · Diretor de legenda | SPEC-13 e SPEC-14 |
| Catálogo de estilos | como um estilo novo se registra |

Projeto Remotion em **`tools/remotion-compositor/`** (Remotion 4.x, node v22). Não é script — é um projeto React cujos componentes são a mecânica reutilizável — o "roteiro de edição" de cada peça (captions, overlays, partitura, perfil) mora em `<dir-producao>/remotion/`, fora daqui (ver a seção acima). **É React: dá pra construir QUALQUER visual** — quando o momento pede uma analogia/conceito (não só texto empilhado), criar uma **cena conceitual** custom (ver seção abaixo).

## ⚠️ Regras de look (feedback creator-2/creator-1 2026-07-22, produção peca-04)

1. **Vídeo NATURAL por padrão**: sem grade, sem saturação extra, sem punch-in, sem efeito de look. Efeito só como decisão editorial explícita e aprovada (ex.: virada pra P&B intencional). O punch-in do ovo saiu do padrão — se jump cut incomodar, é decisão a levar no plano, não default.
2. **Entrega por COMPOSIÇÃO ALPHA** (arquitetura atual — substitui a briga de tags): renderizar a composição `Graphics` (só camada gráfica, fundo transparente; `Main` com vídeo existe só pra preview no studio) e compor com ffmpeg sobre a base pós-conversão (`v1-graded.mp4` se houver grade do creator; senão o próprio `v1-montado.mp4`). Os pixels do vídeo nunca passam pelo Chrome → **cor fiel por construção** (o decode do Chrome difere do player mesmo com input todo-bt709 — Δsat ~0.11 medido; não dá pra vencer por tag).
   ```bash
   npx remotion render Graphics graphics.mov --codec=prores --prores-profile=4444 \
     --image-format=png --pixel-format=yuva444p10le   # SEM --pixel-format sai OPACO (yuv422p12le)!
   # conferir: ffprobe → pix_fmt precisa ser yuvA444p10le (o "a" é o alpha)
   ffmpeg -i v1-graded.mp4 -i graphics.mov \
     -filter_complex "[1:v]unpremultiply=inplace=1[g];[0:v][g]overlay=0:0:format=auto[v];[v]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[vo];[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]" \
     -map "[vo]" -map "[a]" -c:v libx264 -crf 16 -pix_fmt yuv420p \
     -c:a aac -b:a 192k v-final.mp4
   # conferir SEMPRE: .claude/skills/edit-video/scripts/qc-cor.py <dir-producao>
   ```
   🔴 **AS TAGS DE COR VÃO PELO `setparams`, NÃO pelas flags `-color_*`** (defeito
   ENTREGUE em 2026-08-06, produção `creator-2/peca-02`). Neste build (ffmpeg
   8.0.1 homebrew) as opções de SAÍDA `-color_primaries` e `-color_trc` são
   **silenciosamente ignoradas** — só `-colorspace` pega. Medido nos 3 caminhos:
   | forma | resultado |
   |---|---|
   | `-colorspace bt709 -color_primaries bt709 -color_trc bt709` | `bt709, arib-std-b67, bt2020` ❌ |
   | `-vf setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709` | `bt709, bt709, bt709` ✅ |
   | `-c copy -bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1` | `bt709, bt709, bt709` ✅ sem re-encode |

   **Por que isso é grave**: a LUT converte os PIXELS de HLG/BT.2020 pra SDR mas
   não toca no metadado. Um entregável SDR rotulado como HLG faz o player
   **tone-mapear de novo** — cor alterada, mais quente, e (porque tone-map de
   player é adaptativo ao conteúdo) **mudando ao longo do vídeo**. A descrição do
   creator-1 foi "começa mais branco e depois fica mais vívido". ⚠️ **Nenhum QC por
   extração de frame pega isso**: o ffmpeg lê os pixels e ignora o rótulo, então
   todas as medições dão certo enquanto o vídeo está errado no player. O único
   jeito é conferir `ffprobe` das tags — é o que o `qc-cor.py` faz.
   ⚠️ **Tag também no `v1-sdr`**, não só no entregável: se ela nascer errada, o
   erro se propaga por toda a cadeia (e o `v1-graded` herda).
   (`normalize=0` no amix: voz da base + SFX do mov sem atenuação. ⚠️ **`unpremultiply` é OBRIGATÓRIO**: o ProRes 4444 do Remotion/Chrome sai com **alpha premultiplicado**; o overlay assume straight e escurece toda borda suave — sombras/glow/anti-aliasing viram um halo escuro que ENTRA E SAI com cada legenda/cartão, percebido como 'vídeo piscando' (feedback creator-1, peca-04 it.5; Δ−1.84 medido na faixa da legenda, +0.28 após o fix).)
3. **Zonas seguras de UI** ("quadrado proibido" — guia do creator-1): elemento gráfico NUNCA em **y<290** (corte 4:5 do feed + status bar), **y>1500** (legenda/perfil/áudio) ou **x>924** (coluna de botões). O `layout-zones.sh` já desconta por padrão (`--no-ui-safe` desliga). Feedback real da peca-04: overlays "muito pra cima" — o lar deles é o bloco lateral livre em y≈290–1500. (Legendas de fala centro-baixo continuam ok.)

🆕 **`v1-sdr.mp4` deixou de ser produzido (SPEC-25).** A conversão HDR→SDR acontece
agora **na extração**, por segmento: `v1-montado.mp4` já é o que esse nome descrevia.
Os arquivos `v1-sdr.mp4` que existem no disco continuam válidos — nenhuma produção
publicada é remontada —, mas peça nova não tem esse arquivo. Quem for compor pergunta
ao `cor.json`: `aplicada_em: "extracao"` quer dizer que o montado já é Rec.709.

🔴 **Não aplique a LUT sobre o montado.** Com a conversão na extração, um passe de
`lut3d` sobre `v1-montado.mp4` converte **duas vezes**; assinatura medida: **−23,7%**
de luminância média. O `qc-cor.py` acusa isso na seção 5, mas só nos alvos sem look —
em arquivo com grade o −20,6% legítimo do preset da creator-2 e o −23,7% da LUT dupla se
sobrepõem, e ali o teste seria sorteio.

✅ **A composição continua não precisando de flag de cor nenhuma, e agora por um
motivo mais forte.** Medido: com a base já em `bt709`, um `overlay` de duas entradas
sai `bt709/bt709/bt709` **em qualquer ordem de entrada** e sem uma única flag na linha
de comando. É herança, não disciplina.

## 📁 Onde a produção mora — e por que NÃO é dentro do `src/`

🔴 **A peça de cada produção mora em `<dir-producao>/remotion/`, nunca em
`tools/remotion-compositor/src/`.** Até 2026-08-10 era o contrário, e a
auditoria daquele dia mediu o preço (achado A6): uma produção fez 3 dos 6
portões do exportador reprovarem, e nenhum pacote saía. Pior no cliente — a peça
dele moraria dentro do pacote, e um update que substituísse o pacote apagaria o
trabalho dele.

```
<dir-producao>/remotion/
  index.tsx        entry point isolado (RD-12): registra só Main e Graphics
  <Peca>.tsx       o componente da peça
  captions.json    a legenda desta peça
  perfil.json      o snapshot de formato, escrito por `perfil.py resolver`
  overlays.json    a decisão editorial de cartões (quando houver)
```

O kit vem por **`@ilha/*`** (alias declarado em `remotion.config.ts` +
`tsconfig.json`), nunca por `../../../..`:

```tsx
import { CaptionLayer, type CaptionStyle } from "@ilha/CaptionLayer";
import { agrupamentoDoPerfil } from "@ilha/texto/agrupar";
import caps from "./captions.json";
import perfil from "./perfil.json";
```

E o render aponta para a produção, com **cwd aqui** (o alias e a resolução de
`node_modules` dependem disso, e o config aborta nomeando o erro se não for):

```bash
cd tools/remotion-compositor
npx remotion compositions <dir-producao>/remotion/index.tsx
npx remotion render <dir-producao>/remotion/index.tsx Graphics <dir-producao>/graphics.mov \
  --codec=prores --prores-profile=4444 --image-format=png --pixel-format=yuva444p10le
```

O que continua morando em `src/data/` é **fixture do produto**: `captions.json`,
`overlays.json`, `partitura.json` e `perfil.json` são o exemplo que faz o
`Main`/`Graphics` genérico abrir num clone novo — não são a sua peça. Arquivo
novo em `src/data/` é acusado pelo auditor (classe E quando tem fala), e é assim
de propósito.

🔴 **E a fixture NÃO entra na sua peça — desde 2026-08-12 (SPEC-47/H47-4).** Se
você reusa `Graphics`/`Main` passando a sua camada em `extra`, `<Captions />` (a
fixture) **não** é renderizada:

```tsx
// a sua camada substitui overlays E desliga a legenda-fixture
const MinhaPeca = () => <Graphics extra={<Peca />} />;
// a sua camada + a sua legenda, explícita
const MinhaPeca = () => <Graphics extra={<Peca />} captions={<MinhaLegenda />} />;
```

Antes disso, `extra` trocava só os overlays e a legenda de exemplo entrava
sempre: uma peça de cliente saiu do render com **duas** legendas, a dele e "Este
é um exemplo de legenda" queimada por cima. Quem passa `extra` e **não** passa
`captions` renderiza sem legenda — a legenda daquela peça mora na camada dela.
O QC disso é `node scripts/qc-fixture-legenda.mjs` (e ele tem `--controle`).

## Fluxo por vídeo

1. **Transcrever o vídeo MONTADO** (não o bruto): `transcribe.sh <video-final>.mp4 <dir>/final-transcript/`. Isso dá timestamps já no tempo do vídeo final — **zero deriva A/V por construção** (não remapear EDL — aprendizado da segunda iteração daquela produção).
2. **Gerar `<dir-producao>/remotion/captions.json`** (formato `Caption[]` do `@remotion/captions`):
   ```bash
   jq '[.results.channels[0].alternatives[0].words[] | {text: (" " + (.punctuated_word // .word)), startMs: (.start*1000|round), endMs: (.end*1000|round), timestampMs: (((.start+.end)/2)*1000|round), confidence}]' transcript.json > <dir-producao>/remotion/captions.json
   ```
   (espaço antes de cada palavra é obrigatório — whitespace-sensitive.)
3. ~~segments.json / punch-in~~ — removido do fluxo padrão (regra de look #1). Se um plano aprovado pedir punch-in, as fronteiras vêm da EDL escaladas por `duração_real / soma_EDL`.
4. **Escrever `<dir-producao>/remotion/overlays.json`** — a decisão editorial (que cartão, quando, onde). O posicionamento é **estratégico por sub-janela** (o "encaixe onde dava" da ref-C): rode o detector de zonas livres —
   ```bash
   scripts/layout-zones.sh <video> 2.0-4.6 5.0-8.4 [--samples 5]
   # stderr: mapa ASCII de ocupação da pessoa · stdout: retângulos livres em px
   ```
   (segmenta a pessoa via rembg nos frames amostrados e faz a UNIÃO das máscaras da janela — pessoa se move; UI do Instagram já descontada.) Regra de ouro: **medir por janela de ELEMENTO, não da cena inteira** — na união de 8s sobra pouco espaço; cada elemento só precisa do seu intervalo livre, por isso os overlays entram e saem. Tipos: `postit` e `handwritten-big` (`writeOn: true` = escrito na hora; ambos aceitam `x` esquerdo, `fontSize`, `width` — com `width` o texto quebra linha; `\n` explícito funciona no writeOn), `stack-card` (pilha numerada; `panel: true` = vai pro painel atrás da pessoa), `arrow` (path SVG em coords 1080x1920, desenha com dashoffset). Campo `sfx`: `pop` | `whoosh` | `pencil` (pencil toca a 0.13 automático). 🔶 `whoosh` é um dos dois que **não vêm no pacote** — ver a nota do inventário de `public/sfx/` mais abaixo.
5. **Copiar o vídeo** pra `public/v1-montado.mp4` (**cópia real, symlink quebra o bundler**) — só pro preview `Main`/studio; a entrega usa `Graphics`+ffmpeg (regra de look #2).
6. Renderizar `Graphics` (alpha) e compor com ffmpeg — receita na regra de look #2. ~3min pra 60s no M-series.
7. **QC visual OBRIGATÓRIO — no estado FINAL desenhado**: pra cada elemento, still no frame em que ele está 100% construído (fim do write-on/traço/pop) e OLHAR a imagem (Read). Antes disso, **QC geométrico numérico**: `remotion still Graphics <out>.png --frame=N` (fundo transparente) e bbox do canal alpha → confere zona segura sem depender do olho (pegou 5 transbordos de x>924 na peca-03). Custo: ~3s por still com o bundle cacheado — dá pra validar 15 estados em menos de 1 minuto. Validar no meio da animação esconde bug — o círculo cortando o texto e o "sublinhado" riscando a linha de baixo (peca-04) só apareciam no estado final. Checklist: traço cruza letra? quebra de linha certa? dentro da zona segura? rosto livre? legenda certa? Elemento com timing apertado no fim da janela: conferir que ele TERMINA de desenhar antes do fade-out.

## Efeito "painel atrás da pessoa" (recorte)

Segmentação por frame com **Apple Vision** (`scripts/matte.py` da skill
`edit-video`). Zero instalação: Vision faz parte do SO.

```bash
S=.claude/skills/edit-video/scripts
python3 $S/matte.py <video-já-enquadrado-e-gradeado> --ini 31.0 --fim 39.2 --saida <dir>
# stdout: <dir>/matte-alpha.mp4     sidecar: <dir>/matte.json
python3 $S/qc-alpha.py <dir>/matte-alpha.mp4     # OBRIGATÓRIO, exit 1 reprova
```

O que mudou, e por quê (SPEC-03, medido 2026-08-08):

| | antes | agora |
|---|---|---|
| engine | `rembg` + venv + 176 MB de modelo | Vision, **0 B** — 38 ms/frame em `.accurate` |
| formato | `fps=30` e `-framerate 30` cravados | derivados da fonte, sempre |
| artefato | `public/cutout.webm` (RGBA lossy) | `matte-alpha.mp4` (**só o alpha**, sem perda) |
| composição | camada dentro do Remotion → vídeo no Chrome | 4 camadas no ffmpeg → vídeo **fora** do Chrome |
| verificação | nenhuma | `qc-alpha.py`, obrigatório |

**A receita anterior morreu por dependência que evaporou**: uma produção entregue
(`peca-08`) virou irreproduzível em dois dias porque só sobrou o modelo
em `~/.u2net/`, sem o pacote. Vision não tem o que desinstalar. É a mesma decisão
já registrada em `docs/ARSENAIS-ROADMAP.md:116` para o rastreamento, estendida
agora para o matte.

### O artefato padrão é SÓ o alpha

`--formato alpha` (default) grava um vídeo **cinza**: o canal alpha e nada mais.
Medido a 1 s de 9:16@30: **2,10 MB/s** contra 23,82 MB/s do ProRes 4444 RGBA.

O RGB não vai junto porque ele é **redundante**: o recorte é composto sobre a
mesma base de onde foi extraído, então os pixels da pessoa devem ser os da base,
bit a bit. Na composição, `alphamerge` reconstrói a camada da pessoa na hora.
Costura impossível por construção — e cai fora o alerta antigo de que *"o recorte
precisa do MESMO transform e do MESMO filter do vídeo base"*: o matte é medido no
vídeo **já enquadrado e já gradeado**, então não há o que replicar.

Os outros dois formatos seguem disponíveis: `--formato rgba` (ProRes 4444) quando
o recorte vira asset avulso sobre um fundo que **não** é a base, e `--formato webm`
para a pilha Remotion antiga (`OffthreadVideo(cutout.webm, transparent)`), que
continua funcionando.

### Composição: 4 camadas no ffmpeg

O Remotion passa a renderizar **duas** camadas alpha em vez de uma: `GraphicsBack`
(o que vai atrás da pessoa — painel, fundo decorativo) e `Graphics` (o que vai na
frente — cartões, legenda, traços). O ffmpeg empilha:

```
v1-graded.mp4  ←  back.mov (alpha, premultiplicado)
               ←  pessoa   (base ∩ matte-alpha, alpha STRAIGHT)
               ←  graphics.mov (alpha, premultiplicado)
```

```bash
ffmpeg -i v1-graded.mp4 -i back.mov -i matte-alpha.mp4 -i graphics.mov -filter_complex "\
 [0:v]split=2[b0][b1];\
 [b1]trim=${T0}:${T1},setpts=PTS-STARTPTS[bw];\
 [2:v]format=gray,setpts=PTS-STARTPTS[al];\
 [bw][al]alphamerge[pes];\
 [1:v]unpremultiply=inplace=1,tpad=start_duration=${T0}:color=black@0.0[bk];\
 [pes]tpad=start_duration=${T0}:color=black@0.0[pesS];\
 [b0][bk]overlay=0:0:format=auto:eof_action=pass[t1];\
 [t1][pesS]overlay=0:0:format=auto:eof_action=pass[t2];\
 [3:v]unpremultiply=inplace=1[gf];\
 [t2][gf]overlay=0:0:format=auto[v];\
 [v]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[vo]" \
 -map "[vo]" -map 0:a -c:v libx264 -crf 16 -pix_fmt yuv420p -c:a copy v-final.mp4
```

Isso mantém a regra de look #2 (o vídeo **não** entra no Chrome). Era o único
efeito do arsenal que ainda furava essa regra.

🔴 **Repare no que NÃO leva `unpremultiply`: a camada da pessoa.** Ela é alpha
**straight** (medido: RGBA `(255,255,255,128)` codificado em ProRes 4444 volta
`R=255 A=129`). As camadas do Remotion voltam **premultiplicadas** — é a causa do
"vídeo piscando" da peca-04, e ali o filtro é obrigatório. Aplicar
`unpremultiply` na pessoa divide o RGB pelo alpha e **estoura toda a borda do
cabelo**. Duas camadas, duas regras, no mesmo `filter_complex`.

Regra de camadas aprendida na primeira produção completa, que continua valendo: **fundo
decorativo atrás da pessoa, texto informacional sempre NA FRENTE** — texto atrás
fica coberto quando a pessoa ocupa o centro; e a pilha vai no topo compacto pra
não cobrir o rosto nos closes (validar com `remotion still` no frame do close
antes do render completo).

### 🔴 Guard de alpha NUNCA se escreve com `ffprobe` sozinho

`ffprobe` **não aceita `-c:v`** (medido: `Option not found`), e o alpha do WebM
VP9 não mora no plano de pixel — mora em `BlockAdditional` do Matroska. O decoder
nativo ignora, o do libvpx lê. **O mesmo arquivo**, dois leitores:

```
decoder default (vp9)   pix_fmt=yuv420p    alphaextract: "Requested planes not available"
-c:v libvpx-vp9         pix_fmt=yuva420p   alphaextract: plano completo, 2.073.600 B
```

Por isso `qc-alpha.py` é obrigatório: ele escolhe o decoder pelo codec e responde
por **varredura do canal**, não por rótulo. O padrão `ffprobe … stream=pix_fmt |
grep yuva` do `compor.sh` de uma produção real
é correto para `.mov` e **estruturalmente cego** para `.webm` — ele reprovaria o
`cutout.webm` bom que está no repo.

## 🐛 `OverlayGroup` tem DOIS referenciais de tempo — a pegadinha que apaga um beat inteiro

`OverlayGroup` é uma `Sequence`. Isso cria duas zonas de tempo no mesmo arquivo:

- o corpo do componente que **retorna** o grupo roda **FORA** dela → `useCurrentFrame()` ali é o frame **ABSOLUTO** do vídeo;
- os componentes **FILHOS** (`HandText delayS`, `DrawStroke delayS`, `Sfx atS`, componentes próprios) recebem o frame **RELATIVO** ao `fromS`.

Escrever timing absoluto na zona errada desloca a animação pelo tamanho do `fromS`. Medido em 2026-07-29 (`creator-2/peca-05`): um beat com `fromS={37.3}` teve **todos os `interpolate` jogados 37,3s pra fora do intervalo** e simplesmente **não desenhou nada** — alpha vazio. **Nenhum QC de áudio, transcript ou emenda acusa isso**: é puramente visual, e o único jeito de pegar é olhar o still (ou medir a bbox do alpha) **de cada beat**.

Padrão que ficou (topo de `MaeDoMarido.tsx`) — deixa todo número literal em tempo absoluto, que é como o transcript fala:

```tsx
const usaTempo = (FROM: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return {
    t: frame / fps,                     // ABSOLUTO (o corpo do beat está fora da Sequence)
    at: (s: number) => frame - s * fps, // ABSOLUTO, pra spring({frame: at(35.52)})
    rel: (s: number) => s - FROM,       // → relativo, pra prop de FILHO
    fps,
  };
};
```

⚠️ Erra-se nas **duas** direções: a primeira "correção" que fiz assumiu que o pai era relativo e quebrou 6 beats de uma vez. Renderize um still por beat depois de mexer nisso.

## 📏 Geometria de traço se MEDE no alpha, não se estima

Três defeitos de estado final numa produção só vieram de chutar número: círculo cortando as duas pontas da palavra (3px de folga onde a regra pede ~26), riscos passando **60 e 140px** além do texto, e ponta de seta caindo **dentro** da palavra que ela aponta.

Receita que acerta de primeira: renderize a composição `Graphics` num frame em que **o texto já está escrito e o traço ainda não desenhou**, e tire a bbox do alpha — largura real do texto, e o meio do corpo das minúsculas (as linhas com mais pixels acesos) pra altura do tachado. Com o número na mão o `strikePath`/`loopCirclePath` sai certo sem iteração.

## Color — pegadinha HDR (a mais importante)

Bruto de iPhone é **HDR BT.2020/HLG**. Alimentar o Remotion com ele direto = imagem LAVADA/esbranquiçada: o Chrome headless tone-mapeia mal (e compensar com saturação NÃO conserta — o problema é gamma/pretos levantados, reclamação da creator-2 nas 2 primeiras tentativas).

**Fix definitivo (validado): converter pra SDR ANTES do Remotion via LUT 3D própria.**
1. A LUT pronta está em **`tools/remotion-compositor/luts/hlg2sdr.cube`** (gerador reproduzível: `scripts/gen-hlg2sdr-lut.py`).

   🆕 **Qual curva se aplica a um arquivo não se decide mais no olho: está no catálogo** `tools/remotion-compositor/luts/catalogo-cor.json` (contrato `benchmark.catalogo-cor/v1`), lido por `edit-video/scripts/detect-cor.py`. Ele mapeia o perfil DETECTADO (`hlg`, `rec709`, `bt2020_sdr`, `pq`, `apple_log`, `log_*`) para a cadeia que este repo tem **medida**, e cada entrada carrega `calibrado` booleano mais a referência da medição. Os `.cube` desta pasta **não mudaram** — a divisão é: a detecção resolve a CONVERSÃO até Rec.709; o look (grade do creator, punch) continua sendo decisão editorial, e não entra no catálogo.

   🔴 **`calibrado: false` é recusa, não aviso.** `pq`, `apple_log` e os `log_*` estão no catálogo **sem cadeia entregável**: temos como detectá-los com certeza e **não** temos curva medida para eles. Detectar PQ com confiança alta não autoriza converter PQ. O caminho é medir o `avconvert` naquele material e tabelar (receita no cabeçalho de `gen-hlg2sdr-lut.py`), como foi feito para HLG — **nunca** somar um tone-mapper derivado do standard, que é exatamente a estrada que a tabela das 3 tentativas acima reprovou.

   ⚠️ **Uma entrada é calibrada sem ter passado pelo `avconvert`, e o motivo fica escrito no catálogo**: `bt2020_sdr`. Ali não há curva envolvida — BT.2020 SDR tem transferência que coincide com a do Rec.709, então é troca de primárias, matemática fechada (`colorspace=…:itrc=bt2020-10:…`), não julgamento estético.

   🎯 **A REFERÊNCIA da conversão é o conversor da APPLE — medido, não teorizado** (saga de 2026-07-25, 3 tentativas):
   | tentativa | tese | resultado |
   |---|---|---|
   | v1 (`--alvo v1`) | cadeia de manual: OOTF γ1.2 + Reinhard com white point no PICO | **reprovada**: pretos +12%, branco difuso em 196/255, faixa de contraste do rosto **−21%** → pele lavada, cabelo preto virando castanho-avermelhado |
   | `--alvo neutro` | "HLG é retrocompatível, preservar os números preserva a aparência" | **errada também**: ~38% mais CLARA que o arquivo do iPhone. A aparência do sinal HLG cru NÃO é a referência |
   | **`--alvo apple` (default)** | medir a curva do conversor da Apple e reproduzir | **erro final: lum +0,5% · sat −0,2% · R/B +0,9%** |

   **Como obter a referência** (vale pra qualquer creator com bruto de iPhone): `avconvert --source clipe.mov --output ref.mov --preset Preset1920x1080 --replace` — AVFoundation, o **mesmo motor do app Edits do Instagram**, que é a cor que o creator reconhece como "a do original". ⚠️ Só os presets **H.264** tonemapeiam; ProRes/HEVC preservam HDR (foi o que confundiu a nota antiga "avconvert não tone-mapeia"). O `scale_vt` (VideoToolbox) não funcionou nem com `-hwaccel videotoolbox` neste build.
   **O que a curva da Apple revela**: HLG→SDR correto é **~22% mais ESCURO que o sinal** — é o gamma de sistema pra display de 100 nits (BT.2100 nota 5e, γ≈1,08) com leve levante nos meios. E a Apple aplica **compensação de croma** (efeito Hunt: baixar luminância derruba a saturação percebida); sem ela a saída fica 12% menos saturada — calibrado em `--croma-ganho 1.16`.
   **Consequência**: o grade oficial do creator foi calibrado contra a LUT antiga — ao trocar a LUT, **reconferir o grade** (na creator-2 a vinheta virou pesada demais: dois erros que se cancelavam, recalibrada de PI/7 pra PI/12).
   **Testes de regressão**: (1) rampa de cinza + patch de pele por `lut3d` sozinho; (2) `faixa de contraste` (p90−p10) do montado HDR vs o graded — a perda deve ser só a do preset; (3) **erro de pele (lum/sat/R/B) contra um clipe convertido por `avconvert`** — tem que ficar <2%.

   ### Por que NÃO trocar por "o operador padrão da indústria" (medido)
   Sugestão comum: `libplacebo=tonemapping=bt.2390:gamut_mode=perceptual`.
   1. **"Padrão" não é resposta única**: implementei a EETF da BT.2390 — com alinhamento absoluto de luminância dá **+33%** de desvio (pior que a v1 reprovada); com o gamma de sistema da BT.2100 dá **−23%**. O alvo `apple` dá 0%.
   2. **Gamut perceptual não tem o que resolver aqui**: medido na footage da creator-2, **1,4–3,2% dos pixels** saem do BT.709 com severidade média 0,0004 (pior caso 0,010 do branco difuso ≈ 2–3 níveis em 255). Invisível. Só vale com LED saturado/neon/verde profundo.
   3. **Metadado Dolby Vision não ajuda em profile 8.4** (`dv_bl_signal_compatibility_id=4`, o caso do iPhone HLG): a camada base JÁ É o sinal HLG compatível — é o que a LUT consome. O RPU carrega trims pra display DV, não uma derivação SDR.
   E este build (ffmpeg 8.0.1 homebrew) **não tem libplacebo nem libzimg/zscale**.

2. **Entrega por COMPOSIÇÃO ALPHA** (arquitetura atual — substitui a briga de tags): renderizar a composição `Graphics` (só camada gráfica, fundo transparente; `Main` com vídeo existe só pra preview no studio) e compor com ffmpeg sobre a base pós-conversão (`v1-graded.mp4` se houver grade do creator; senão o próprio `v1-montado.mp4`). Os pixels do vídeo nunca passam pelo Chrome → **cor fiel por construção** (o decode do Chrome difere do player mesmo com input todo-bt709 — Δsat ~0.11 medido; não dá pra vencer por tag).
   ```bash
   npx remotion render Graphics graphics.mov --codec=prores --prores-profile=4444 \
     --image-format=png --pixel-format=yuva444p10le   # SEM --pixel-format sai OPACO (yuv422p12le)!
   # conferir: ffprobe → pix_fmt precisa ser yuvA444p10le (o "a" é o alpha)
   ffmpeg -i v1-graded.mp4 -i graphics.mov \
     -filter_complex "[1:v]unpremultiply=inplace=1[g];[0:v][g]overlay=0:0:format=auto[v];[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]" \
     -map "[v]" -map "[a]" -c:v libx264 -crf 16 -pix_fmt yuv420p \
     -c:a aac -b:a 192k v-final.mp4   # ⚠️ tags via setparams — ver bloco acima
   ```
   (`normalize=0` no amix: voz da base + SFX do mov sem atenuação. ⚠️ **`unpremultiply` é OBRIGATÓRIO**: o ProRes 4444 do Remotion/Chrome sai com **alpha premultiplicado**; o overlay assume straight e escurece toda borda suave — sombras/glow/anti-aliasing viram um halo escuro que ENTRA E SAI com cada legenda/cartão, percebido como 'vídeo piscando' (feedback creator-1, peca-04 it.5; Δ−1.84 medido na faixa da legenda, +0.28 após o fix).)
3. **Zonas seguras de UI** ("quadrado proibido" — guia do creator-1): elemento gráfico NUNCA em **y<290** (corte 4:5 do feed + status bar), **y>1500** (legenda/perfil/áudio) ou **x>924** (coluna de botões). O `layout-zones.sh` já desconta por padrão (`--no-ui-safe` desliga). Feedback real da peca-04: overlays "muito pra cima" — o lar deles é o bloco lateral livre em y≈290–1500. (Legendas de fala centro-baixo continuam ok.)

## Efeito "lettering anotado" (gancho da ref-C, validado no v5 da creator-2)

Cluster tipográfico que se constrói em timing de palavra: texto manuscrito **write-on** (stagger por caractere) → **palavra-ênfase marker** (caps, cor do creator, pop com overshoot) → **sublinhado mão-livre** (path ondulado com dashoffset) → **seta** pro cluster seguinte → cluster 2 menor **rotacionado (-7°)** → **círculo/elipse mão-livre** na palavra-chave. SFX: lápis nos traços/write-on, pop na palavra-ênfase.

- Componentes prontos em `src/HookLettering.tsx`: `WriteOn` (delayS), `DrawStroke` (path SVG 1080x1920, delayS/drawS, arrowHead opcional), `MarkerWord`. Composição de teste `HookTest` no Root (renderiza só a janela do gancho — barato de iterar).
- **Write-on SEM movimento (feedback creator-1 2026-07-22)**: escrita de verdade não anima — a letra só APARECE (fade de 2 frames, sem translateY/spring). Movimento vertical nas letras foi reprovado.
- **Volumes de SFX calibrados de ouvido (creator-1, 2 rodadas de feedback)**: pencil **0.12–0.15 com base -21 LUFS** ("bem baixo" — foi o que mais precisou descer), typing 0.32–0.4, pop 0.35, whoosh 0.4. Lápis alto/frenético incomoda rápido — na dúvida, mais baixo e mais esparso.
- `src/SfxDemo.tsx`: composição-sandbox dos SFX em contexto + componente `TypeOn` (texto digitando char a char com cursor piscante, ~3 frames/char pra casar com o ritmo do typing.wav) dentro de cartão "nota digital" (Space Mono, estética notes-app). Par de uso: manuscrito+pencil = anotação à mão; TypeOn+typing = nota/mensagem digital.
- Timing: cada elemento entra no timestamp da PALAVRA correspondente (transcript do vídeo final).
- Elipse "circulando" palavra = path fechado de 4 quadráticas (não `<ellipse>`) — fica torto de propósito, e o dashoffset desenha como caneta. **Se o texto é rotacionado, a elipse tem que ser desenhada DENTRO do container rotacionado** (prop `localBox` do `DrawStroke`) — em coords globais ela corta as letras e fecha torta (bug da 1ª versão).
- Traços mão-livre: sempre Q-curves com ondulação leve, nunca linha reta.
- **Posicionar cegos não funciona**: validar com `remotion still` nos frames-chave (o sublinhado caiu na testa dela na 1ª tentativa) e ajustar coords.
- SFX de lápis sintetizado (`public/sfx/pencil.wav`): `anoisesrc` rosa + bandpass 2.2kHz + tremolo 22Hz + fades — aceitável pra validação; trocar por sample real em produção.

## MotionKit + Mockups — módulos do sistema "legenda semântica" (2026-07-22)

Os gaps do `references/sistema-ref-C.md` viraram módulos genéricos, validados em 3 POCs de comparação lado a lado com a referência (comparação lado a lado com a referência, em 3 composições de estudo).

- **`src/themes.ts`** — `Theme` por creator: ink, highlight, paleta SEMÂNTICA de post-its (cor = categoria), painel, legenda. `neutralTheme` default; nenhum módulo hardcoda cor.
- **`src/MotionKit.tsx`**:
  - **REGRA DE ORQUESTRAÇÃO (feedback creator-1, v2)**: UMA escrita por vez — elemento só começa quando o anterior TERMINOU (`writeDurationS()` calcula quando um HandText acaba). Frases de contexto se SUBSTITUEM via `SwapText`, não acumulam.
  - `OverlayGroup {fromS,toS,exit:"cut"|"fade"}` — elementos do mesmo assunto acumulam e somem JUNTOS no corte seco; delayS dos filhos é relativo ao grupo.
  - `HandText` — manuscrito write-on fonte FINA (`pen`=Nanum Pen Script default, ~40-50px; `fpc` controla velocidade, 0.9=ritmo da referência) com quebra correta por palavra (o `WriteOn` cru quebra em qualquer char — bug pego no QC).
  - `SwapText` (frases que se substituem) · `MarkerHighlight` (marca-texto varrendo atrás da palavra) · `AccentWord` (palavra-destaque colorida pop, ex. "15 DIAS") · `StepTitleFlat` (chip "#N" + label em texto na cor de destaque — o formato da referência) · `StepTitle` (variante em caixa).
  - Geradores p/ `DrawStroke`: `underlinePath`, `loopCirclePath` (círculo FINO 3-3.5px), `strikePath`, `strikeXPaths` (o X da referência: 2 diagonais longas 4-5px em sequência), `arrowPath`, `squigglePath` (rabisco-conector).
  - `PipCard` (vídeo flutuante borda branca; tamanhos VARIADOS + stagger in/out um a um), `PanelLite`, `PostItCard`, `ScenePunch` (punch-CORTE; só decisão editorial explícita — regra de look #1), `WordCaptions` (só quando a referência do creator usa caption layer — o padrão do estilo é SEM), `Sfx {name,atS}`.
  - **SOM DE ESCRITA É MODULAR (pedido creator-1 2026-07-23)**: `<SfxProvider writing={false}>` em volta da composição (ou de um trecho) MUDA todos os sons de escrita (pencil/scratch) mantendo pops/whooshes — pra creator/trecho que quer só a animação (caso creator-2). Knobs: `enabled` (mata tudo), `writing`, `master` (multiplicador de volume); `<Sfx force>` fura o provider. `HandText` aceita `sfx` (toca o lápis junto da escrita, já respeitando o provider) — dispensa o `<Sfx>` manual na maioria dos casos.
  - Fonte manuscrita por creator: comp `FontTest` compara candidatas com amostra PT-BR acentuada (a Nanum Pen caiu pelo ú torto; padrão atual = Shadows Into Light Two).
- **`src/Mockups.tsx` (v2 — estilo-sistema real, calibrado por frames)**: `MacWindow`/`MacChecklistMock` (janela macOS com semáforo, checkboxes CIRCULARES azuis marcando um a um via `checksAtS`), `MessengerListMock` (lista de mensagens que entra subindo e POVOA row a row via `rowsAtS`; header/cor por props), `CallBannerMock` (banner iOS: incoming com botões verde/vermelho | missed), `EventCardMock`, `BigCalendarMock` (calendário FULLSCREEN semi-transparente com pan — painel do "passo"), `WeekCalendarMock`, `NotebookPageMock`.
- SFX novos em `public/sfx/`: `shutter`, `scratch` (tachado), `whoosh-soft`, `pop-hi`/`pop-lo` (±2 semitons do pop do creator-1 — variar pitch em sequências de post-its pra não soar metralhadora). Placeholders CC0/derivados — creator-1 escolhe definitivos.
- Receita de densidade da referência: 4–6 elementos novos/10s, nunca >1.2s sem estímulo, rosto livre, elemento entra na PALAVRA (transcript) — regras completas no `sistema-ref-C.md`.

## Peças novas da modelagem ref-D (2026-07-25)

Nasceram da skill `model-edit` medindo uma edição real; réplica provada em `estudos/modelagem-ref-D/`.

- **`src/TitleCard.tsx` — `HookTitle`**: gancho tipográfico de 2 linhas. Linha 1 grotesca pesada
  condensada (Anton) em caps que se **digita com cursor `|` visível** (`fpc` = frames por caractere,
  1.1 = ritmo da referência); linha 2 serif display itálica colorida em **pop seco** (sem fade),
  **alinhada à direita** da linha 1 (`align2`/`inset2`) e sobrepondo-a levemente (`gap2` negativo).
  Morre no corte, não anima a saída. Props medidas na referência estão no docstring.
  - ⚠️ **Calibre pela LARGURA**, não pelo tamanho nominal: a mesma "font-size" muda muito de família
    pra família. Renderize um still, meça a bbox pelo alpha e ajuste (`fontSize × alvo/medido`).
  - ⚠️ **Texto grande sobre fundo colorido**: o anti-aliasing puxa o tom pro fundo (medido: +20 no
    canal verde sobre parede laranja). Especificar a cor MEDIDA no vídeo alheio produz um tom mais
    claro que o dele — compense na especificação e reconfira medindo o render.
- **`src/CaptionLayer.tsx` — `CaptionLayer` + `CaptionStyle`**: o mesmo motor anti-piscada do
  `Captions.tsx` (ponte, fade só em pausa real, fade-in só pós-pausa, pop discreto) com o **estilo
  como prop**. `highlight: null` desliga a palavra ativa — legenda chapada, que não compete com o
  ritmo de corte. `aPartirDeS` segura a legenda enquanto o título de gancho está no ar (regra da
  referência: gancho e legenda não dividem a tela). `ESTILO_LEGENDA_CHAPADA` já vem calibrado.
  O `Captions.tsx` antigo continua servindo a produção da creator-2; migrar quando houver motivo.
- **Split-screen NÃO é Remotion**: mexe nos pixels do vídeo base (empurra a base pra baixo), então
  vive no ffmpeg — `scripts/split-broll.py` da skill `edit-video`. A regra continua: **Remotion só
  desenha a camada alpha; quem toca o vídeo é o ffmpeg.**
- 🆕 **E "empurrar a base pra baixo" passou a ser uma CONTA, não uma constante**
  (SPEC-28, 2026-08-09). O quanto a base desce é resolvido a partir da **cabeça
  medida por segmento** (`scripts/split-plano.py` + `scripts/matte.py`), de modo
  que o topo do cabelo caia abaixo do fim da rampa de alpha. Com a constante de
  25 % da altura, o arquivo entregue do estudo `modelagem-ref-D` tinha **mediana
  de 12,20 % de b-roll sobre o cabelo** (máx 13,48 %, 35 amostras); com plano, os
  mesmos 35 samples dão **0,00 %**. Contrato em
  `edit-video/references/contrato-split.md`.

  Duas consequências para quem escreve camada gráfica por cima de um split:

  1. **A base não está mais no mesmo lugar em toda a janela.** `(deslocamento,
     escala)` trocam **no corte** — no estudo são 4 valores diferentes numa
     janela de 8,1 s (620/620/623/624 px). Qualquer overlay posicionado em px
     absolutos sobre a metade de baixo tem que ser conferido em **cada
     segmento**, não num frame do meio.
  2. **A faixa útil para legenda encolheu.** O deslocamento saiu de 25 % para
     32–34 % da altura, ou seja **mais 7–9 % do pé do quadro sai de cena**. A
     `zonas_ui` do perfil continua valendo para o quadro; o que mudou é o que
     está **dentro** dele na janela do split.

  ⚠️ O par `(zoom, focusY)` do ref-A (`assets/shortform/src/CustomGraphics.tsx:57-59`)
  é a mesma ideia com duas constantes de layout — e o próprio código deles manda
  medir antes de confiar nos números. Aqui não existe constante: o valor é medido
  e vive no `split-plano.json` da peça; o perfil carrega só a política (faixa,
  folga, tetos).

## Gotchas conhecidos

- Render/still SEMPRE com cwd em `tools/remotion-compositor/` (público e config são resolvidos pelo cwd).
- 🆕 **Um import quebrado em QUALQUER produção derruba o render de TODAS** (2026-07-27): o `Root.tsx` registra todas as composições do repo, então o webpack empacota tudo — quando o `src/peca-10/peca-10.tsx` (produção do creator-3, editada em paralelo por outra sessão) passou a importar um `data/*.json` inexistente, o render da produção da creator-2 **falhou sem sair um frame**, e o `.mov` antigo ficou no lugar: a composição ffmpeg seguinte rodou "com sucesso" sobre a camada gráfica velha, e os dois defeitos que eu tinha acabado de corrigir continuaram no arquivo. **Sempre confira o mtime do `.mov` depois do render**, e não confie no exit code do pipe (`| tail`) — ele é do `tail`. Solução: **entry point isolado por produção**, que registra só `Main`/`Graphics`:  → RD-12
  ```bash
  # src/index-<producao>.tsx com registerRoot só das 2 composições
  npx remotion render src/index-<producao>.tsx Graphics saida.mov --codec=prores ...
  ```
  Custo zero e imuniza a produção contra o estado das outras. Modelo: `src/index-peca-06.tsx`.
- 🆕 **`DrawStroke` com `localBox` exige `height` explícito no container** (2026-07-27): os filhos são `position:absolute`, então sem `height` o div colapsa, o SVG sai com altura 0 e **o traço simplesmente não desenha** — sem erro, sem aviso. Mesma causa faz texto escapar de um balão/cartão que só tem conteúdo absoluto (a bolha de DM saiu por cima do cabeçalho). Regra: **container de traço ou de texto escrito leva altura fixa.**
- 🆕 **`CAPTION_OFF` suprime a PÁGINA, não o intervalo** (2026-07-27): a janela `[38,15 → 40,85]` matou a página inteira que abria em 40,71 ("Elogio específico") e o vídeo ficou **3,9s sem legenda** onde o plano previa 2,5s. Antes de fechar a janela, olhe no `captions.json` **qual palavra abre a próxima página** e feche antes dela (aqui: 40,65). Só a varredura de todos os frames pegou.
- `public/` não pode ter symlink (o bundle copia e quebra).
- 🔶 **DOIS DOS NOVE NÃO VÊM NO PACOTE** (2026-08-11): `whoosh.wav` e
  `whoosh-soft.wav`. A licença deles está marcada **não conferida** no
  `MANIFESTO.ativos` (vêm de catálogo de terceiro), e arquivo com licença que
  ninguém conferiu não se redistribui. Os outros sete vêm no `git clone`. Nenhuma
  das composições que o pacote traz referencia whoosh — mas **a doc abaixo ensina
  o nome**, e uma peça sua que pedir `sfx: "whoosh"` fica sem aquele som. O que
  fazer está em `instalacao.md` §2.6; `chaves.py --ativos` os reporta ausentes.
- **SFX locais em `public/sfx/`** — inventário atual: `pop.wav` (**sample do creator-1**, `tools/sfx-library/pop.mp3`), `whoosh.wav` (seta/transição, remotion.media), `pencil.wav` (**sample do creator-1**, `tools/sfx-library/pencil.mp3`; o do BigSoundBank foi reprovado como "frenético"), `typing.wav` (teclado REAL — BigSoundBank #1734, CC0), e os placeholders de 2026-07-22: `shutter.wav` (BigSoundBank s0307, CC0), `scratch.wav` (tachado — risco de lápis real, BigSoundBank s3237, CC0; o whiteboard-marker foi descartado por chiado), `whoosh-soft.wav` (derivado do whoosh: pitch ×0.85 + stretch → ~0.30s), `pop-hi.wav`/`pop-lo.wav` (±2 semitons do pop do creator-1, mesma loudness — variar em sequências de post-its). Fontes brutas em `tools/sfx-library/`. **Fluxo oficial de aquisição: o creator-1 prefere escolher os samples ele mesmo** — ele joga o mp3 em `tools/sfx-library/<nome>.mp3` e eu processo pro `public/sfx/` (fades + loudnorm ~-19 a -21 LUFS conforme o tipo). Bibliotecas (BigSoundBank etc.) viram sugestão, não decisão. **Vias pra conseguir mais**, em ordem de preferência:
  1. **BigSoundBank** (CC0, download direto sem conta — MELHOR fonte de sons reais): buscar em `bigsoundbank.com/search?q=<termo>`, baixar `https://bigsoundbank.com/UPLOAD/mp3/<ID>.mp3` (só o mp3 tem link direto; o ID está na URL da página de detalhe).
  2. **remotion.media** (11 sons prontos, catálogo no rule `sfx.md` da skill remotion-best-practices): whoosh, whip, page-turn, switch, mouse-click, shutter, ding, vine-boom etc.
  3. **Kenney via soundcn** (CC0): `https://raw.githubusercontent.com/kapishdima/soundcn/main/assets/kenney_<pack>/<som>.ogg` — packs: interface-sounds, impact-sounds, music-jingles etc.
  4. **Síntese via ffmpeg** — só validação/protótipo: o pencil e o typing sintéticos foram REPROVADOS pelo creator-1 de ouvido ("estranho"); sample real ganha sempre que existir.
  5. **Geração por IA** (som muito específico): Higgsfield MCP `generate_audio` ou ElevenLabs SFX (pago).
  **Pós-processo do corte: `sfx-preparar.py`, não comando digitado na hora.**
  A receita virou script — `.claude/skills/edit-video/scripts/sfx-preparar.py`,
  contrato em `edit-video/references/contrato-sfx.md` — porque a ordem das
  operações importa e a prosa não a impunha:

  ```
  aparar lead-in (transiente em t=0) → aparar cauda → declick/fade pela CLASSE
  MEDIDA → MEDIR o integrado (ebur128 -stream_loop 15) → NORMALIZAR → RE-MEDIR
  ```

  🔴 **Medir antes de aparar é o erro, e ele tem número**: `pop.wav` mede
  **−22,5 LUFS** como está e **−17,5 LUFS** sem a cauda muda — **5,0 LU vindos de
  silêncio dentro do arquivo**. Um `loudnorm` rodado antes do corte normaliza o
  padding junto e entrega o efeito 5 dB mais alto do que o alvo pedia.

  As duas pegadinhas de 2026-07-22 continuam valendo e agora são executadas pelo
  script: (1) `loudnorm` de passe único ERRA ~3 LU em SFX sub-segundo — o
  integrado é medido em loop ×16 no `ebur128` e o ganho é aplicado à mão;
  (2) SFX percussivo NÃO leva fade-in. **Duas emendas medidas em 2026-08-09**:
  o `afade in 30ms` genérico é **parte do problema** (é ele que explica `shutter`
  a 7 ms e `scratch` a 17 ms de onset) e virou declick de ≤ 5 ms limitado à
  guarda antes do onset; e o fade-out passa a **começar no fim acústico**,
  durando só o silêncio disponível depois dele — um `afade out 250ms` cego muda o
  corpo do `pencil` em **212 ms** e o do `typing` em **56 ms**, ou seja, come som.

  **A biblioteca é auditada, não presumida**: `qc-sfx.py --perfil <n>` mede onset,
  corpo, classe, pico e LUFS dos 9 arquivos e grava `public/sfx/_inventario.json`.
  Antes desta spec, **4 de 9** tinham o transiente a mais de um frame do início
  (`whoosh` 46 ms, `whoosh-soft` 75 ms, `typing` 98 ms, `pencil` 135 ms) e
  ninguém sabia, porque ninguém media lead-in. Depois do
  `sfx-preparar.py --migrar --confirmar`, os quatro estão em `onset ≤ 3 ms` com o
  corpo preservado (Δ máximo 1,0 ms), os `.wav` anteriores estão em
  `public/sfx/_historico/<nome>-<sha8>.wav` — **nunca apagados** — e cada arquivo
  tem sidecar `benchmark.sfx/v1` com `sha256`, `antes`/`depois` e procedência.

  Regra que não muda: SEMPRE licença CC0/livre comercial — nada de rip de
  biblioteca paga ou de vídeo alheio. Regra nova: **trocar o conteúdo de um
  `.wav` mantendo o nome exige `--confirmar`**, porque é a família exata do
  segmento órfão — quem re-renderizar uma peça antiga receberia outro som sem
  nenhum aviso.

  ⚠️ **O que continua sem existir**: compensação do onset residual em runtime
  dentro do `<Sfx>` (`from = round(atS×fps) − round(onset_ms×fps/1000)`). Exige
  `MotionKit.tsx`, protegido por baseline `md5` da SPEC-15. Um SFX de terceiro
  colocado em `public/sfx/` na mão continua caindo atrasado: o `qc-sfx.py` acusa,
  o render não conserta sozinho.
  🌱 **Se um dia SINTETIZARMOS SFX, a seed vai gravada no sidecar** (SPEC-20 §3.11).
  O gerador do ref-A (`assets/shortform/generate_sfx.py:24,34,40`) usa o RNG global
  **sem seed**: duas execuções produzem SFX diferentes com o mesmo nome de arquivo.
  Num pipeline com cache por nome isso é a mesma família do segmento órfão —
  artefato trocado em silêncio, com todos os QCs verdes. Se for para gerar:
  `rng = np.random.default_rng(seed)` com a **seed no sidecar**, e normalização por
  **loudness medida**, nunca por pico (`generate_sfx.py:8` faz `y / max(|y|)`, que é
  cego para percepção — é assim que se chega a um `click2.mp3` que a doc deles mesma
  admite ser inaudível a −25 dB). Hoje nada muda: o fluxo continua sendo o creator-1
  escolher o sample e nós processarmos.
  **Wishlist (creator-1 vai suprindo em `tools/sfx-library/`)**: prioridade alta — `marker` (risco de caneta grossa, p/ sublinhado/círculo), `whoosh-soft` (~0.3s, p/ punch-in e micro-transições), `shutter` (freeze/print), `notification` (tom de mensagem, par do TypeOn); média — `paper` (post-it/slide), `ding` (payoff/ficha), `scratch-tachado` (mito vs verdade); baixa — `sub-drop` leve, `pop-bolha` (variação p/ sequências de cartões).
- Fontes via `@remotion/google-fonts`: Caveat (manuscrita, cartões), Montserrat (legendas), Playfair Display italic (modo ênfase). Trocar por creator.
- Legendas: páginas de ~1.1s (`createTikTokStyleCaptions`), highlight da palavra ativa na cor do creator (creator-2: rosé #FF8FA3), posição ~78% da altura (não cobrir boca/mãos).
- ⚠️ **Anti-piscada de legenda** (feedback creator-1 2026-07-22, "o vídeo parece piscar"): página de legenda que CORTA SECO pra tela vazia derruba a luminância da faixa em até −30 num único frame — lê como flicker. Regras (implementadas no Captions.tsx): (1) **ponte**: se a próxima página começa <500ms após o fim das palavras desta, esta fica na tela até a próxima entrar (nada de gap por causa do cap de 1.1s); (2) em pausa longa real, a página sai com **fade de 5 frames**; (3) **fade-in de 2 frames SÓ em entrada pós-pausa — troca emendada entra a opacidade CHEIA** (fade-in na emenda cria um buraco semi-transparente no frame exato da troca; foi o 2º round do feedback de piscada); (4) pop de escala discreto (0.985→1, não 0.94→1) e SEM glow largo no textShadow (o glow amplia a área que pisca). **QC de flicker numérico**: extrair fps=30 de um trecho e medir Δ de luminância média da faixa das legendas frame a frame — salto >2 fora de troca-com-ponte = investigar (script no NOTAS da peca-04).
- Modo ênfase de legenda (frase destacável em serif itálico maior) via `captionEmphasis` no overlays.json — usar quando um cartão cobriria o rosto (closes).
- **Legenda DESLIGADA por janela** (`CAPTION_OFF` no Captions.tsx): quando um cartão gráfico carrega as mesmas palavras (ex.: o cartão de script ditado), legenda + cartão é ruído — suprima a legenda na janela. ⚠️ **Não faça isso apagando as palavras do `captions.json`**: o `createTikTokStyleCaptions` agrupa ATRAVÉS do buraco e gera uma página gigante (8,3s "doçura, sem" na produção peca-03). A supressão é na renderização, e a página anterior tem que morrer em **fade** (tratar a página suprimida como "não existe próxima", senão a ponte anti-piscada estica a legenda por cima da janela).
- **Sombra própria em `HandText`/`AccentWord`** (prop `shadow`): o default vem do `theme.inkShadow` num offset apertado (`0 1px 2px`), bom sobre papel e fraco sobre vídeo. Sobre vídeo use `0 3px 12px rgba(0,0,0,0.85)`.
- **Risco: X só em palavra isolada e grande.** O X duplo (`strikeXPaths`) cruzando uma palavra de 6+ letras pequena vira rabisco sujo (reprovado no QC da peca-03 em "ironia"/"você nunca"). Pra item de lista, `strikePath` (risco simples, um traço) lê como "não faça isso" e fica limpo.
- Punch-in: alternância 1.0/1.06 em corte seco por segmento, `transformOrigin 50% 30%` (âncora no rosto).
- Iterar ao vivo: `npm run studio`.
- Trend de áudio do Instagram: NUNCA queimar no vídeo (aplicar no app ao postar — regra do docs/EDICAO-CAPACIDADES.md).

## Composição

- Vem depois de: montagem/EDL (cut-breaths ou manual) + `transcribe` do montado.
- Referências de estilo por creator: linha editorial + análises no banco (`data/`).
- O histórico de iterações de uma produção fica no `NOTAS.md` dela, ao lado da peça.

## Composição nova lê de `PERFIL`; produção entregue não se toca

O formato da peça (resolução, fps, zonas de UI, duração da produção corrente)
deixou de morar no `Main.tsx` e no `Root.tsx` e passou a vir de um único
documento: **`<dir-producao>/remotion/perfil.json`**, escrito pelo
`edit-video/scripts/perfil.py resolver`, importado direto pelo `.tsx` da peça.
`src/data/perfil.json` é a FIXTURE do produto — o default que faz as composições
de mecanismo abrirem num clone novo, e nada mais (era o snapshot da última
produção resolvida até 2026-08-10; achado A6).

```ts
import { PERFIL, FPS, W, H, VIEWBOX, ZONAS_UI, DURACAO_PRODUCAO_S } from "./perfil";
```

| export | o que é |
|---|---|
| `FPS`, `W`, `H` | `video.fps`, `video.largura`, `video.altura` |
| `VIEWBOX` | `"0 0 W H"` pronto para SVG |
| `ZONAS_UI` | zonas proibidas em **px**, derivadas das frações — ou `null` quando a peça não toca em feed nenhum (VSL num player web, YouTube) |
| `DURACAO_PRODUCAO_S` | duração do `v1-montado.mp4` da produção corrente, gravada pelo `resolver`; `null` quando não há montagem |

### A regra

> **Composição NOVA lê de `PERFIL`. Composição de produção JÁ ENTREGUE não se
> toca.**

Migraram só as três composições **vivas** — `Main`, `Graphics` e `HookTest` — mais
o `Main.tsx`. Ficaram congeladas as 8 constantes `*_FPS` de peças já entregues,
uma por peça, e os `width`/`height` das composições delas.

Não é preguiça: a skill proíbe remontar entrega publicada, migrá-las
re-renderizaria camada gráfica aprovada, e o guarda de duração do `compor.sh`
(`|graphics − vídeo| < 0,05 s`) reprovaria a diferença de arredondamento.

`Main.tsx` também perdeu o `DURATION_S = 64.0667` cravado — a duração de **uma**
produção morando no arquivo compartilhado. Agora é
`DURACAO_PRODUCAO_S ?? 64.0667`: com um `v1-montado.mp4` resolvido vem a duração
real; sem ele, o default histórico, e nada quebra por falta de montagem.

### Medido

Na árvore de DESENVOLVIMENTO, `npx remotion compositions` lista **64** composições
antes e depois da migração (o fonte tem 26 tags `<Composition>`; dois blocos
`flatMap` no `Root.tsx` emitem várias cada — os dois números estão certos e medem
coisas diferentes). ⚠️ **No pacote instalado o comando lista 4** — `Main`,
`Graphics`, `HookTest` e `SfxDemo`: o `Root` do produto não registra as
composições de peça nomeada, que são a nossa fila de produções. Medido num clone
limpo em 2026-08-11; o número aqui é o da árvore de quem escreveu.
Trocando o perfil de `reels` para `vsl` e re-listando, **exatamente** `Main`,
`Graphics` e `HookTest` mudam de 1080×1920 para 1920×1080; as outras 61 ficam
byte a byte iguais.

---

## Legenda por LARGURA MEDIDA (SPEC-13)

Até aqui a página de legenda era fechada por **tempo**
(`createTikTokStyleCaptions`, janela de 1100 ms) e a quebra de linha era do
Chrome (`maxWidth` + `whiteSpace: "pre-wrap"`). O resultado: o número de
caracteres na tela é função da prosódia daquele segundo, não do layout.

📏 **Medido sobre a peça ENTREGUE `creator-2/peca-02`** (Montserrat 700 @58 px,
orçamento 900 px, os valores reais de `peca-02.tsx:1152-1163`):

| | páginas | p50 | máxima | CV | passam de 900 px |
|---|---|---|---|---|---|
| por tempo (hoje) | 61 | 674 px | **1133 px** | 0,275 | **10 (16,4 %)** |
| por largura (novo) | 63 | 736 px | 885 px | **0,077** | **0** |

Nos outros `captions.*.json` do `src/data/`: `peca-05` 3 → 0 estouros,
`ref-D` 2 → 0, `vsl-captions` **45 → 0**.

### Como se liga

É **opt-in**, e continua opt-in de propósito: produção entregue chama sem as
props novas e sai byte a byte igual.

```tsx
import { agrupamentoDoPerfil } from "./texto/agrupar";
import { estiloDoPerfil, CaptionLayer } from "./CaptionLayer";
import { PERFIL } from "./perfil";

const ag = agrupamentoDoPerfil(PERFIL, largura);   // null em longform
<CaptionLayer captions={caps} estilo={estiloDoPerfil(PERFIL, largura)!} agrupamento={ag!} />
```

Precedência: `paginas` (partitura pronta) > `agrupamento` > `combinaMs` (legado).

### As três regras do `measureText` que custam caro esquecer

Conferidas no fonte do pacote (`@remotion/layout-utils`,
`dist/cjs/layouts/measure-text.js`):

1. 🔴 **Medir sempre DENTRO de um `useMemo` do componente, nunca no escopo de
   módulo.** O `wordCache` do pacote guarda a **primeira** medição *para sempre*,
   por chave `texto-familia-peso-tamanho-entreletras-caixa-additionalStyles`. Se
   essa primeira medição acontecer antes de a fonte carregar, a peça inteira é
   diagramada com métrica de Arial e **nada acusa**. Fora do memo há um segundo
   custo: o `SimpleCaptions` do ref-A chama `buildCues` no corpo do componente
   (`:150`) e `splitTwo` de novo (`:163`) — em 60 s a 30 fps são 1.800
   reexecuções sobre 680 palavras.
2. ⚠️ **`validateFontIsLoaded: true` em toda chamada.** Com ele o pacote mede
   também com a fonte de fallback e **lança** se as duas medições baterem — em
   vez de mentir. Quem passa `agrupamento` ou `ajustar` assume o contrato de ter
   a fonte carregada.
3. ⚠️ **Itálico não é parâmetro.** O tipo aceito é `{text, fontFamily, fontSize,
   fontWeight, letterSpacing, fontVariantNumeric, textTransform,
   additionalStyles, validateFontIsLoaded}`. Itálico vai por
   `additionalStyles: {fontStyle: "italic"}` (o pacote inclui isso na chave do
   cache); `letterSpacing` é **string com unidade** (`"1px"`), não número; e
   caixa alta vai por `textTransform`, nunca por `.toUpperCase()` no texto — se
   for pelo texto, o type-on do `HookTitle` e a `key` do React perdem o original.

### O que NÃO se herda do ref-A nesta área

- **`MIN_SOLO_MS = 340`** (`helpers/caption_style.py:53`). A animação de entrada
  deles encolhe com a cue (`StackedCaptions.tsx:100`) e a nossa é física fixa; e
  eles testam `endMs − startMs` da **palavra** (`:104-111`) enquanto o próprio
  código estica a cue depois (`:274-282`). O nosso piso é derivado do nosso
  `spring` por `scripts/medir-assentamento.mjs`: **700 ms @30 fps**.
- **Legenda que nunca sai da tela** (`SimpleCaptions.tsx:157-160`, `duration =
  próximo início − início atual`, sem exceção). A nossa ponte anti-piscada
  (< 500 ms) com fade em pausa real é melhor e está aqui por feedback direto do
  creator-1. **Preservada, e conferida por gate**: `teste-agrupamento.mjs --espelho`
  lê os dois números direto do `CaptionLayer.tsx` e reprova se a cópia que o
  `agrupar.ts` guarda divergir.

### Ordem dos critérios: o teto de palavras é guarda-corpo, não critério

Com teto baixo ele volta a ser quem fecha a página e a largura continua dispersa.
Medido na peca-02, orçamento 900 px:

| `max_palavras_pagina` | páginas | fecha por largura / palavras | CV das fechadas por layout |
|---|---|---|---|
| 3 | 91 | 2 / 57 | 0,299 (≈ o 0,275 de hoje) |
| 5 | 65 | 18 / 18 | 0,099 |
| **6** | **63** | **27 / 2** | **0,077** |
| ∞ | 64 | 29 / 0 | 0,083 |

Por isso o catálogo passou de 3 para **6** em `reels` (e de 6 para 12 em
`vsl`/`screencast`, que rodam em 2 linhas).

### Com `linhas_max: 2`, cada LINHA tem que caber

O teste "a soma cabe em `largura_max × linhas_max`" **não basta**: medido na
`vsl-captions.json` a 1920 px ele deixa passar linha de 1322 px num orçamento de
1190 px por linha, e aí é o Chrome que decide onde ela quebra — o defeito
sobrevivendo dentro do caminho novo. O `cabeNaPagina` testa o total **e** cada
linha do melhor corte.

### Ferramentas

```bash
cd tools/remotion-compositor
python3 scripts/largura-fonte.py --familia Montserrat --peso 700   # tabela de advance widths
node scripts/medir-assentamento.mjs --fps 30                       # de onde sai o min_solo_ms
node scripts/medir-assentamento.mjs --verificar <perfil.json>       # exit 1 se o perfil estiver abaixo
node scripts/teste-agrupamento.mjs --captions <c.json> --perfil <p.json> --canvas 1080
node scripts/teste-agrupamento.mjs --espelho    # ponte × CaptionLayer
node scripts/teste-agrupamento.mjs --autoteste  # 7 defeitos plantados que os gates TÊM que acusar
node scripts/teste-agrupamento.mjs --regressao <baseline.json>   # caminho legado, igualdade exata
```

⚠️ A tabela de larguras **ignora kerning (GPOS)**. O campo `correcao` do JSON
vale `null` — que quer dizer *não medido*, não *1,0 conferido*. Medir contra o
`measureText` do Chrome é o critério 6 da SPEC-13 e exige render.

## Diretor de legenda — a partitura (SPEC-14)

**O que ele resolve**: até aqui, a decisão de *que palavra vira tipografia* era 100 %
manual — 21 elementos escritos à mão em 1.202 linhas de TSX na `peca-02`, zero
decisões automatizadas, e nenhum QC capaz de perguntar "a palavra certa recebeu o
destaque?". A partitura é o artefato onde essa decisão vira **dado auditável**.

```
captions.json ─┐
áudio montado  ├→ medir → paginar → pontuar → eleger → serializar
perfil.json    │                                  │
tema + léxico ─┘                        partitura.json + PARTITURA.md
```

```bash
S=.claude/skills/remotion-compositor/scripts
D=<dir-producao>

python3 $S/prosodia.py $D/v1-graded.mp4 $D/captions.json --perfil <perfil.json>
python3 $S/diretor-legenda.py $D --audio $D/v1-graded.mp4 --tema temaRoseSobreVideo \
        --perfil .claude/skills/edit-video/perfis/reels.json
python3 $S/diretor-legenda.py md      $D/partitura.json     # a vista humana
python3 $S/diretor-legenda.py validar $D/partitura.json --paginas   # exit 1 se violar
```

O passo 4 do fluxo desta skill passa a ser: **rodar o diretor, ler o `PARTITURA.md`,
travar o que for decisão humana** (`"travado": true` volta byte a byte na próxima
execução; `"removido": true` não volta e o slot não é reocupado).

### Onde a legenda desliga — e por que quase nunca

`legenda_off[]` nasce **ancorado em fronteira de página**, porque agora quem gera as
páginas é o diretor. Foi a falta disso que produziu os dois buracos entregues (3,9 s e
2,1 s): quem escrevia a janela à mão não sabia onde as fronteiras caíam.

🔴 **A ocupação é por ZONA, não por canal.** Só item em `faixa-legenda` ou `pleno`
disputa espaço com a legenda; `topo` e `lateral` convivem com ela. Isso não é
suavização — é o que as duas produções aprovadas dizem, com a mesma frase:

- `peca-02.tsx:1172` — `CAPTION_OFF: []`, *"a supressão nem se justifica: o cartão está
  na faixa y372–800 e a legenda em y~1400, não há colisão geométrica"*;
- `MaeDoMarido.tsx:909` — `CAPTION_OFF: []`, *"o que precisava mudar era a GEOMETRIA:
  a seta descia até y1468 e batia na legenda (y1413–1464). Subi o bloco."*

Implementado ao pé da letra ("todo item de texto desliga a legenda"), o diretor
produziu na `peca-02` uma janela de **17,3 s sem legenda** — o defeito que ele
existe para consertar, entrando pela porta nova. Com a regra por zona, o perfil `reels`
sai com `legenda_off: []`, idêntico ao que o humano aprovou.

`legenda.diretor.fracao_legenda_alvo` é **restrição, não decoração**: se a eleição
desligar mais do que o alvo, o item de menor score que suprime é descartado com motivo
`fracao-legenda`. Medido: `reels` alvo 1,00 → medido 1,000 · `vsl` alvo 0,34 → medido
**0,342** (os 34,1 % da ref-C em modo oferta, reproduzidos por construção).

### A prop `paginas` do `CaptionLayer`

`paginas` **vence** `agrupamento` (SPEC-13), e receber as duas emite
`console.warn("[LEGENDA] agrupamento ignorado: paginas tem precedência")`. O canário é
obrigatório: sem ele a precedência fica implícita e alguém a inverte sem nada acusar —
e o sintoma (segundos a mais sem legenda num beat qualquer) é silencioso.

O `paginar()` do Python é **port linha a linha** do `agrupar.ts`, sobre a mesma tabela
de advance widths. Medido: **764 páginas comparadas em 8 arquivos × 2 perfis, 0
divergências**; com 2 % de erro na régua, o mesmo teste acusa (3 e 46 divergências).

### O passe que a SPEC-13 não podia fazer: doar a fronteira

A SPEC-13 deixou **5 páginas de 1 token** abaixo do piso de solo na `peca-02`,
registradas em `avisos[]`. Ela só podia **fundir** a página inteira com a vizinha, e as
vizinhas estavam em 885–921 px de um orçamento de 900.

O diretor tem uma ferramenta a mais: **mover a fronteira**. Doa-se a palavra da ponta
da vizinha para a página curta; a curta passa do piso, a vizinha continua no orçamento.

| | SPEC-13 | + diretor |
|---|---|---|
| páginas | 63 | 63 |
| avisos `solo-nao-fundido` | **5** | **0** |
| doações de fronteira | — | 5 (todas para trás) |
| largura máxima | 885 px | 885 px (orçamento 900) |
| CV de largura (páginas de layout) | 0,077 | 0,113 |

As fronteiras novas: `peca-02 em cima` / `da cama?` · `Você sente aquele` /
`calor subindo,` · `tamanho por causa de` / `uma peca-02.` · `As brigas aqui em` /
`casa mudaram,` · `sentimento que nunca` / `foi dito.`

O custo é honesto: a dispersão de largura sobe de 0,077 para 0,113 (ainda muito abaixo
dos 0,275 da paginação por tempo). **Não se funde estourando o orçamento** — isso
reintroduz o defeito que a SPEC-13 conserta.

### `Partitura.tsx` — código imutável, dado variável

Entry point **isolado** (`src/index-partitura.tsx`), pelo mesmo motivo do
`index-peca-06.tsx`: um import quebrado no `Root.tsx` derruba o bundle inteiro.
Formato e duração vêm da própria partitura (`_procedencia.perfil.video`), não de
`src/data/perfil.json` — que é a fixture do produto, não a sua peça.

```bash
D="$(cd <dir-producao> && pwd)"
cd tools/remotion-compositor
python3 ../../skills/remotion-compositor/scripts/compilar-plano-visual.py "$D" preparar
python3 ../../skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" renderizar --saida graphics-alpha.mov
python3 ../../skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" compor-final --base v1-graded.mp4 --saida v-final.mp4
# Quando o perfil pedir também a versão sem filtro, componha a mesma camada
# gráfica sobre a base sem grade. Cada saída recebe seu próprio manifesto.
python3 ../../skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" compor-final --base v1-montado.mp4 --saida v-final-sem-filtro.mp4
npx remotion still src/index-partitura.tsx Graphics /tmp/p.png --frame=238 \
  --props="$D/remotion/partitura-compilada.json" \
  --public-dir="$D/remotion/public"
# a tinta da creator-2 é BRANCA: componha o still sobre fundo escuro antes de olhar,
# senão o alpha sobre branco engana (é a armadilha do "no alpha tudo parecia certo")
ffmpeg -f lavfi -i color=c=0x3a3a3a:s=1080x1920 -i /tmp/p.png \
       -filter_complex "[0][1]overlay" -frames:v 1 -y /tmp/p-fundo.png
```

`compor-final` grava um sidecar por saída em
`$D/remotion/plano-visual-finais/`. O segundo comando não sobrescreve a prova do
primeiro, e o gate exige proveniência própria para todo `v-final*.mp4` presente.
Se a produção não tiver grade opcional, use `v1-montado.mp4` como base única de
`v-final.mp4` e não gere uma duplicata sem filtro.

⚠️ **A partitura promete TEMPO, não geometria.** Ela carrega uma *dica de zona*
(`topo`/`lateral`/`faixa-legenda`/`pleno`) e nunca x/y. O QC de estado final continua
obrigatório — e foi ele que pegou, nesta entrega, o `loopCirclePath` desenhado no
tamanho da zona inteira (929×115 px, que na tela é uma reta). A correção foi levar a
largura do texto medida (`larguraEstimadaPx`) dentro do item.

### Gate do espelho de tempo

`writeDurationS` existe agora em três lugares (TSX, `agrupar.ts`, Python). O gate
extrai a fórmula **do `MotionKit.tsx` por regex** e avalia — não copia. Foi ele que
achou que `len()` do Python conta *code points* e `.length` do JS conta *unidades
UTF-16*: em `"emoji 🔴 no meio"` davam 0,5167 s × 0,5467 s. Quem renderiza é o TSX,
então o Python passou a contar UTF-16.

---

## Catálogo de estilos — um estilo novo se REGISTRA, não se reinventa

> SPEC-15. Processo completo (as 3 camadas, a regra dos dois usos, o que nunca
> sobe): `references/catalogo-de-estilos.md`.

**O problema medido**: 53,8% das linhas de `src/` vivem em arquivo de uma peça
só. `Chip` tem 4 implementações independentes, `passo numerado` 5, `selo` 3. Um
kit de 423 linhas (`src/peca-11/Kit.tsx`) foi clonado porque **uma cor** estava
cravada em `src/peca-10/Kit.tsx:18` — e o comentário no topo do clone diz isso com
todas as letras.

**O catálogo** vive em `src/catalogo/estilos.ts` (registro TypeScript, fonte de
verdade) e sai em `catalogo/catalogo.json` (`benchmark.catalogo-estilos/v1`,
gerado). Medido em 2026-08-11, e são DOIS números porque são duas árvores:

| | árvore de desenvolvimento | **pacote instalado** |
|---|---|---|
| estilos no `catalogo.json` | 47 | **46** |
| `pronto` · `candidato` | 39 · 8 | **38 · 8** |
| com poster no disco | 39 | **38** |
| oferecidos numa peça `reels` | 38 | **37** |
| grupos | `gramatica` 4 · `gancho` 7 · `legenda` 8 · `tema` 5 · `grafismo` 23 | idem, com `tema` 4 |

A diferença é UMA entrada de tema, e ela é deliberada: o registro do produto
(`catalogo/extras.produto.ts`) tem as listas vazias, porque as entradas do nosso
`extras.ts` citam marca nossa e apontam `duplicatas` para arquivos que o corte
subtrai. O export tira aquela entrada do `catalogo.json` junto
(`MANIFESTO.export.entradas_podadas`) — sem isso o pacote levaria um catálogo de
47 e um registro capaz de montar 46, e `npm run catalogo -- --check` reprovaria
numa instalação CORRETA.

⚠️ Estes números saíram de `jq` sobre o `catalogo.json` de cada lado, não de um
`grep` no fonte — contar tag no código foi o que produziu os "26/64" acima e os
"39/31" que estavam aqui. E dizer só o número da nossa árvore foi o que fez a doc
prometer 47 a quem recebe 46: medido num clone real da v0.7.

### A fronteira, em uma frase

> **Copiar componente de um arquivo de produção para outro é proibido.**
> **Se você ia copiar, é porque é catálogo — promova.**

Três camadas: **1. catálogo** (escolhido por slug + parâmetros, o agente não
escreve TSX) · **2. sob medida** (o arquivo da produção, livre, zero burocracia —
é onde a invenção acontece) · **3. promoção**, disparada pelo **segundo uso**.

### Registrar um estilo — 5 passos

1. **Componente genérico**: cor e fonte por `Theme`; nenhum número de formato no
   corpo; nenhum `staticFile` de asset de produção; timing por prop, nunca literal.
2. **Uma entrada em `src/catalogo/estilos.ts`** — `oQuePinta` em UMA frase,
   `parametros` saídos das props REAIS (abra o arquivo, não invente prop),
   `medido` preenchido se veio de `model-edit`.
3. **`npm run catalogo`** — regenera `catalogo.json` e só o preview do slug novo
   (idempotente por hash).
4. **Olhe o `.png`** (Read na imagem). É o QC de estado final, aplicado ao card.
5. **Se veio de modelagem**, a ficha em `intelligence/edicao/<handle>.md` ganha
   `→ catálogo: <slug>`.

**Adicionar estilo só numa conversa, para uma produção, é proibido** — e agora
existe teste que acusa: `python3 scripts/gerar-previews.py --check` sai 1 com o
slug afetado no stderr.

### Cinco decisões do preview que você não precisa julgar de novo

1. **Entry point isolado** (`src/index-catalogo.tsx`), nunca o `Root.tsx` — é a
   mesma armadilha que já derrubou o render de uma produção por causa do import
   de outra. Efeito medido: `npx remotion compositions` continua listando **64**,
   exatamente como antes.
2. **`--scale` no output, nunca composição menor** — baixar `width`/`height`
   quebraria todo `fontSize` e toda coordenada de path.
3. **VP9 OPACO**, nunca `yuva420p`: WebM com alpha derruba o canal em silêncio no
   libvpx do Homebrew 8.x, que é o nosso.
4. **O poster é o `frameCartao` = estado FINAL desenhado.**
5. 🔴 **A placa é DESENHADA** (`src/catalogo/Placas.tsx`, 4 fundos sintéticos).
   **Nunca material de creator no preview** — nem bruto, nem `public/*.mp4`. Um
   detector que procura "mídia > 1 MB" passa em verde sobre 33 webm de 200 KB com
   o rosto de uma creator dentro.

### CLI

```bash
npm run catalogo                                   # regenera o que mudou
python3 scripts/gerar-previews.py --slug <slug>    # um só
python3 scripts/gerar-previews.py --grupo legenda  # um grupo
python3 scripts/gerar-previews.py --check          # exit 1 se dessincronizou
python3 scripts/gerar-previews.py --validar        # schema + as 5 regras do contrato
python3 scripts/gerar-previews.py --listar         # slug · grupo · estado · sha
```

Custo medido: **31 previews em 4 min 33 s** (com 8 agentes disputando a máquina,
`concurrency: 2`); segunda passada em **1,3 s**; **US$ 0** de API.

⚠️ O canvas do preview é o do **perfil da peça**, e ele viaja no `inputProps` do
render (`previews-peca.py:canvas_nos_props`) — não em arquivo global. Ele entra
no `sha`, e o `--check` compara a dimensão real do PNG com o canvas pedido, com
a régua de arredondamento do renderizador (`dim_escalada`, meio pra cima). Duas
peças de formatos diferentes na mesma máquina não se atrapalham mais.
